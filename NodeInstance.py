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

class NodeInstance():
    def __init__(self, name, t_node, s_domain, zk):
        # Passed-in variables on creation
        self.zkey = '/nodes/%s' % name
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
        @zk.DataWatch(self.zkey + '/state')
        def watch_hypervisor_state(data, stat, event=""):
            try:
                self.state = data.decode('ascii')
            except AttributeError:
                self.state = 'stop'

            if self.state == 'flush':
                self.flush()
            if self.state == 'unflush':
                self.unflush()
    
        @zk.DataWatch(self.zkey + '/memfree')
        def watch_hypervisor_memfree(data, stat, event=""):
            try:
                self.memfree = data.decode('ascii')
            except AttributeError:
                self.memfree = 0
    
        @zk.DataWatch(self.zkey + '/runningdomains')
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
        for domain in self.domain_list:
            # Determine the best target hypervisor
            least_mem = 2**64
            least_host = None
            for node_name in self.active_node_list:
                # It should never include itself, but just in case
                if node_name == self.name:
                    continue

                # Get our node object and free memory
                node = self.t_node[node_name]
                node_freemem = int(node.getfreemem())

                # Calculate who has the most free memory
                if node_freemem < least_mem:
                    least_mem = node_freemem
                    least_host = node_name

            if least_host == None:
                print(">>> Failed to find valid migration target for %s" % domain)
                transaction = self.zk.transaction()
                transaction.set_data('/domains/' + domain + '/state', 'shutdown'.encode('ascii'))
                transaction.commit()
            else:
                print(">>> Setting migration to %s for %s" % (least_host, domain))
                transaction = self.zk.transaction()
                transaction.set_data('/domains/' + domain + '/state', 'migrate'.encode('ascii'))
                transaction.set_data('/domains/' + domain + '/hypervisor', least_host.encode('ascii'))
                result = transaction.commit()

            # Wait 1s between migrations
            time.sleep(1)

    def unflush(self):
        print('>>> Restoring node %s to active service' % self.name)
        for domain in self.s_domain:
            last_hypervisor = self.zk.get("/domains/" + domain + '/lasthypervisor')[0].decode('ascii')
            if last_hypervisor == self.name:
                print(">>> Setting unmigration for %s" % domain)
                transaction = self.zk.transaction()
                transaction.set_data('/domains/' + domain + '/state', 'migrate'.encode('ascii'))
                transaction.set_data('/domains/' + domain + '/hypervisor', self.name.encode('ascii'))
                result = transaction.commit()

                # Wait 1s between migrations
                time.sleep(1)

        self.zk.set("/nodes/" + self.name + "/state", 'start'.encode('ascii'))

    def update_zookeeper(self):
        # Connect to libvirt
        libvirt_name = "qemu:///system"
        conn = libvirt.open(libvirt_name)
        if conn == None:
            print('>>> Failed to open connection to %s' % libvirt_name)
            return

        # Get past state and update if needed
        past_state = self.zk.get(self.zkey + '/state')[0].decode('ascii')
        if past_state != 'flush':
            self.state = 'start'
            self.zk.set(self.zkey + '/state', 'start'.encode('ascii'))
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
            self.zk.set(self.zkey + '/cpucount', str(self.cpucount).encode('ascii'))
            self.zk.set(self.zkey + '/memfree', str(self.memfree).encode('ascii'))
            self.zk.set(self.zkey + '/cpuload', str(self.cpuload).encode('ascii'))
            self.zk.set(self.zkey + '/runningdomains', ' '.join(self.domain_list).encode('ascii'))
            self.zk.set(self.zkey + '/keepalive', str(keepalive_time).encode('ascii'))
        except:
            return

        # Close the Libvirt connection
        conn.close()

        # Display node information to the terminal
        print('>>> {} - {} keepalive'.format(time.strftime('%d/%m/%Y %H:%M:%S'), self.name))
        print('    CPUs: {} | Free memory: {} | Load: {}'.format(self.cpucount, self.memfree, self.cpuload))
        print('    Active domains: {}'.format(' '.join(self.domain_list)))

        # Update our local node lists
        for node_name in self.t_node:
            try:
                node_state = self.zk.get('/nodes/%s/state' % node_name)[0].decode('ascii')
                node_keepalive = int(self.zk.get('/nodes/%s/keepalive' % node_name)[0].decode('ascii'))
            except:
                node_state = 'unknown'
                node_keepalive = 0

            # Handle deadtime and fencng if needed
            # (A node is considered dead when its keepalive timer is >30s out-of-date while in 'start' state)
            node_deadtime = int(time.time()) - 30
            if node_keepalive < node_deadtime and node_state == 'start':
                print('>>> Node {} is dead! Performing fence operation in 3 seconds.'.format(node_name))
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
        print('>>> {} - Cluster status'.format(time.strftime('%d/%m/%Y %H:%M:%S')))
        print('    Active nodes: {}'.format(' '.join(self.active_node_list)))
        print('    Flushed nodes: {}'.format(' '.join(self.flushed_node_list)))
        print('    Inactive nodes: {}'.format(' '.join(self.inactive_node_list)))
