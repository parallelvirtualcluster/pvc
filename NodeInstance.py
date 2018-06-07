#!/usr/bin/env python3

# NodeInstance.py - Class implementing a PVC node and run by pvcd
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018  Joshua M. Boniface <joshua@boniface.me>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
###############################################################################

import os, sys, socket, time, libvirt, kazoo.client, threading, fencenode

# ANSII colours for output
class bcolours:
    PURPLE = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class NodeInstance():
    def __init__(self, name, t_node, s_domain, zk):
        # Passed-in variables on creation
        self.zk = zk
        self.name = name
        self.state = 'stop'
        self.t_node = t_node
        self.active_node_list = []
        self.flushed_node_list = []
        self.inactive_node_list = []
        self.s_domain = s_domain
        self.domain_list = []

        # Zookeeper handlers for changed states
        @zk.DataWatch('/nodes/{}/state'.format(self.name))
        def watch_hypervisor_state(data, stat, event=""):
            try:
                self.state = data.decode('ascii')
            except AttributeError:
                self.state = 'stop'

            if self.state == 'flush':
                self.flush()
            if self.state == 'unflush':
                self.unflush()
    
        @zk.DataWatch('/nodes/{}/memfree'.format(self.name))
        def watch_hypervisor_memfree(data, stat, event=""):
            try:
                self.memfree = data.decode('ascii')
            except AttributeError:
                self.memfree = 0
    
        @zk.DataWatch('/nodes/{}/runningdomains'.format(self.name))
        def watch_hypervisor_runningdomains(data, stat, event=""):
            try:
                self.domain_list = data.decode('ascii').split()
            except AttributeError:
                self.domain_list = []

    # Get value functions
    def getfreemem(self):
        return self.memfree

    def getcpuload(self):
        return self.cpuload

    def getname(self):
        return self.name

    def getstate(self):
        return self.state

    def getdomainlist(self):
        return self.domain_list

    # Update value functions
    def updatenodelist(self, t_node):
        self.t_node = t_node

    def updatedomainlist(self, s_domain):
        self.s_domain = s_domain

    # Flush all VMs on the host
    def flush(self):
        print(bcolours.BLUE + '>>> ' + bcolours.ENDC + 'Flushing node {} of running VMs.'.format(self.name))
        for dom_uuid in self.domain_list:
            most_memfree = 0
            target_hypervisor = None
            hypervisor_list = self.zk.get_children('/nodes')
            current_hypervisor = self.zk.get('/domains/{}/hypervisor'.format(dom_uuid))[0].decode('ascii')
            for hypervisor in hypervisor_list:
                state = self.zk.get('/nodes/{}/state'.format(hypervisor))[0].decode('ascii')
                if state != 'start' or hypervisor == current_hypervisor:
                    continue
    
                memfree = int(self.zk.get('/nodes/{}/memfree'.format(hypervisor))[0].decode('ascii'))
                if memfree > most_memfree:
                    most_memfree = memfree
                    target_hypervisor = hypervisor
    
            if target_hypervisor == None:
                print(bcolours.RED + '>>> ' + bcolours.ENDC + 'Failed to find migration target for VM "{}"; shutting down.'.format(dom_uuid))
                transaction = self.zk.transaction()
                transaction.set_data('/domains/{}/state'.format(dom_uuid), 'shutdown'.encode('ascii'))
                transaction.commit()
            else:
                print(bcolours.BLUE + '>>> ' + bcolours.ENDC + 'Migrating VM "{}" to hypervisor "{}".'.format(dom_uuid, target_hypervisor))
                transaction = self.zk.transaction()
                transaction.set_data('/domains/{}/state'.format(dom_uuid), 'migrate'.encode('ascii'))
                transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
                transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), current_hypervisor.encode('ascii'))
                result = transaction.commit()

            # Wait 1s between migrations
            time.sleep(1)

    def unflush(self):
        print(bcolours.BLUE + '>>> ' + bcolours.ENDC + 'Restoring node {} to active service.'.format(self.name))
        self.zk.set('/nodes/{}/state'.format(self.name), 'start'.encode('ascii'))
        for dom_uuid in self.s_domain:
            last_hypervisor = self.zk.get('/domains/{}/lasthypervisor'.format(dom_uuid))[0].decode('ascii')
            if last_hypervisor != self.name:
                continue

            print(bcolours.BLUE + '>>> ' + bcolours.ENDC + 'Setting unmigration for VM "{}".'.format(dom_uuid))
            transaction = self.zk.transaction()
            transaction.set_data('/domains/{}/state'.format(dom_uuid), 'migrate'.encode('ascii'))
            transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), self.name.encode('ascii'))
            transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), ''.encode('ascii'))
            result = transaction.commit()

            # Wait 1s between migrations
            time.sleep(1)

    def update_zookeeper(self):
        # Connect to libvirt
        libvirt_name = "qemu:///system"
        conn = libvirt.open(libvirt_name)
        if conn == None:
            print(bcolours.RED  + '>>> ' + bcolours.ENDC + 'Failed to open connection to {}'.format(libvirt_name))
            return

        # Get past state and update if needed
        past_state = self.zk.get('/nodes/{}/state'.format(self.name))[0].decode('ascii')
        if past_state != 'flush':
            self.state = 'start'
            self.zk.set('/nodes/{}/state'.format(self.name), 'start'.encode('ascii'))
        else:
            self.state = 'flush'

        # Toggle state management of all VMs and remove any non-running VMs
        for domain, instance in self.s_domain.items():
            if instance.inshutdown == False and domain in self.domain_list:
                instance.manage_vm_state()
                if instance.dom == None:
                    try:
                        self.domain_list.remove(domain)
                    except:
                        pass
                else:
                    try:
                        state = instance.dom.state()[0]
                    except:
                        state = libvirt.VIR_DOMAIN_NOSTATE
                        
                    if state != libvirt.VIR_DOMAIN_RUNNING:
                        try:
                            self.domain_list.remove(domain)
                        except:
                            pass

        # Set our information in zookeeper
        self.name = conn.getHostname()
        self.cpucount = conn.getCPUMap()[0]
        self.memfree = conn.getFreeMemory()
        self.cpuload = os.getloadavg()[0]
        keepalive_time = int(time.time())
        try:
            self.zk.set('/nodes/{}/cpucount'.format(self.name), str(self.cpucount).encode('ascii'))
            self.zk.set('/nodes/{}/memfree'.format(self.name), str(self.memfree).encode('ascii'))
            self.zk.set('/nodes/{}/cpuload'.format(self.name), str(self.cpuload).encode('ascii'))
            self.zk.set('/nodes/{}/runningdomains'.format(self.name), ' '.join(self.domain_list).encode('ascii'))
            self.zk.set('/nodes/{}/keepalive'.format(self.name), str(keepalive_time).encode('ascii'))
        except:
            return

        # Close the Libvirt connection
        conn.close()

        # Display node information to the terminal
        print(bcolours.PURPLE + '>>> ' + bcolours.ENDC + '{} - {} keepalive'.format(time.strftime('%d/%m/%Y %H:%M:%S'), self.name))
        print('    CPUs: {} | Free memory: {} | Load: {}'.format(self.cpucount, self.memfree, self.cpuload))
        print('    Active domains: {}'.format(' '.join(self.domain_list)))

        # Update our local node lists
        for node_name in self.t_node:
            try:
                node_state = self.zk.get('/nodes/{}/state'.format(node_name))[0].decode('ascii')
                node_keepalive = int(self.zk.get('/nodes/{}/keepalive'.format(node_name))[0].decode('ascii'))
            except:
                node_state = 'unknown'
                node_keepalive = 0

            # Handle deadtime and fencng if needed
            # (A node is considered dead when its keepalive timer is >30s out-of-date while in 'start' state)
            node_deadtime = int(time.time()) - 30
            if node_keepalive < node_deadtime and node_state == 'start':
                print(bcolours.RED + '>>> ' + bcolours.ENDC + 'Node {} is dead! Performing fence operation in 3 seconds.'.format(node_name))
                self.zk.set('/nodes/{}/state'.format(node_name), 'dead'.encode('ascii'))
                fence_thread = threading.Thread(target=fencenode.fence, args=(node_name, self.zk), kwargs={})
                fence_thread.start()

            # Update the arrays
            if node_state == 'start' and node_name not in self.active_node_list:
                self.active_node_list.append(node_name)
                try:
                    self.flushed_node_list.remove(node_name)
                except ValueError:
                    pass
                try:
                    self.inactive_node_list.remove(node_name)
                except ValueError:
                    pass
            if node_state == 'flush' and node_name not in self.flushed_node_list:
                self.flushed_node_list.append(node_name)
                try:
                    self.active_node_list.remove(node_name)
                except ValueError:
                    pass
                try:
                    self.inactive_node_list.remove(node_name)
                except ValueError:
                    pass
            if node_state != 'start' and node_state != 'flush' and node_name not in self.inactive_node_list:
                self.inactive_node_list.append(node_name)
                try:
                    self.active_node_list.remove(node_name)
                except ValueError:
                    pass
                try:
                    self.flushed_node_list.remove(node_name)
                except ValueError:
                    pass
        
        # Display cluster information to the terminal
        print(bcolours.PURPLE + '>>> ' + bcolours.ENDC + '{} - Cluster status'.format(time.strftime('%d/%m/%Y %H:%M:%S')))
        print('    Active nodes: {}'.format(' '.join(self.active_node_list)))
        print('    Flushed nodes: {}'.format(' '.join(self.flushed_node_list)))
        print('    Inactive nodes: {}'.format(' '.join(self.inactive_node_list)))
