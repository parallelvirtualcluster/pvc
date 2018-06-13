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

import os, sys, psutil, socket, time, libvirt, kazoo.client, threading, fencenode, ansiiprint

class NodeInstance():
    # Initialization function
    def __init__(self, this_node, name, t_node, s_domain, zk, config):
        # Passed-in variables on creation
        self.zk = zk
        self.config = config
        self.this_node = this_node
        self.name = name
        self.daemon_state = 'stop'
        self.domain_state = 'ready'
        self.t_node = t_node
        self.active_node_list = []
        self.flushed_node_list = []
        self.inactive_node_list = []
        self.s_domain = s_domain
        self.domain_list = []
        self.ipmi_hostname = self.config['ipmi_hostname']
        self.domains_count = 0
        self.memused = 0
        self.memfree = 0
        self.inflush = False

        # Zookeeper handlers for changed states
        @zk.DataWatch('/nodes/{}/daemonstate'.format(self.name))
        def watch_hypervisor_daemonstate(data, stat, event=""):
            try:
                self.daemon_state = data.decode('ascii')
            except AttributeError:
                self.daemon_state = 'stop'

        @zk.DataWatch('/nodes/{}/domainstate'.format(self.name))
        def watch_hypervisor_domainstate(data, stat, event=""):
            try:
                self.domain_state = data.decode('ascii')
            except AttributeError:
                self.domain_state = 'unknown'

            # toggle state management of this node
            if self.domain_state == 'flush' and self.inflush == False:
                self.flush()
            if self.domain_state == 'unflush' and self.inflush == False:
                self.unflush()


        @zk.DataWatch('/nodes/{}/memfree'.format(self.name))
        def watch_hypervisor_memfree(data, stat, event=""):
            try:
                self.memfree = data.decode('ascii')
            except AttributeError:
                self.memfree = 0
    
        @zk.DataWatch('/nodes/{}/memused'.format(self.name))
        def watch_hypervisor_memused(data, stat, event=""):
            try:
                self.memused = data.decode('ascii')
            except AttributeError:
                self.memused = 0
    
        @zk.DataWatch('/nodes/{}/runningdomains'.format(self.name))
        def watch_hypervisor_runningdomains(data, stat, event=""):
            try:
                self.domain_list = data.decode('ascii').split()
            except AttributeError:
                self.domain_list = []

        @zk.DataWatch('/nodes/{}/domainscount'.format(self.name))
        def watch_hypervisor_domainscount(data, stat, event=""):
            try:
                self.domains_count = data.decode('ascii')
            except AttributeError:
                self.domains_count = 0
    
    # Get value functions
    def getfreemem(self):
        return self.memfree

    def getcpuload(self):
        return self.cpuload

    def getname(self):
        return self.name

    def getdaemonstate(self):
        return self.daemon_state

    def getdomainstate(self):
        return self.domain_state

    def getdomainlist(self):
        return self.domain_list

    # Update value functions
    def updatenodelist(self, t_node):
        self.t_node = t_node

    def updatedomainlist(self, s_domain):
        self.s_domain = s_domain

    # Flush all VMs on the host
    def flush(self):
        self.inflush = True
        ansiiprint.echo('Flushing node "{}" of running VMs'.format(self.name), '', 'i')
        ansiiprint.echo('Domain list: {}'.format(', '.join(self.domain_list)), '', 'c')
        for dom_uuid in self.domain_list:
            most_memfree = 0
            target_hypervisor = None
            hypervisor_list = self.zk.get_children('/nodes')
            current_hypervisor = self.zk.get('/domains/{}/hypervisor'.format(dom_uuid))[0].decode('ascii')
            for hypervisor in hypervisor_list:
                daemon_state = self.zk.get('/nodes/{}/daemonstate'.format(hypervisor))[0].decode('ascii')
                domain_state = self.zk.get('/nodes/{}/domainstate'.format(hypervisor))[0].decode('ascii')
                if hypervisor == current_hypervisor:
                    continue

                if daemon_state != 'start' or domain_state != 'ready':
                    continue
    
                memfree = int(self.zk.get('/nodes/{}/memfree'.format(hypervisor))[0].decode('ascii'))
                if memfree > most_memfree:
                    most_memfree = memfree
                    target_hypervisor = hypervisor

            if target_hypervisor == None:
                ansiiprint.echo('Failed to find migration target for VM "{}"; shutting down'.format(dom_uuid), '', 'e')
                transaction = self.zk.transaction()
                transaction.set_data('/domains/{}/state'.format(dom_uuid), 'shutdown'.encode('ascii'))
                transaction.commit()
            else:
                ansiiprint.echo('Migrating VM "{}" to hypervisor "{}"'.format(dom_uuid, target_hypervisor), '', 'i')
                transaction = self.zk.transaction()
                transaction.set_data('/domains/{}/state'.format(dom_uuid), 'migrate'.encode('ascii'))
                transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
                transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), current_hypervisor.encode('ascii'))
                transaction.commit()

            # Wait 2s between migrations
            time.sleep(2)

        self.zk.set('/nodes/{}/domainstate'.format(self.name), 'flushed'.encode('ascii'))
        self.inflush = False

    def unflush(self):
        self.inflush = True
        ansiiprint.echo('Restoring node {} to active service.'.format(self.name), '', 'i')
        self.zk.set('/nodes/{}/domainstate'.format(self.name), 'ready'.encode('ascii'))
        for dom_uuid in self.s_domain:
            last_hypervisor = self.zk.get('/domains/{}/lasthypervisor'.format(dom_uuid))[0].decode('ascii')
            if last_hypervisor != self.name:
                continue

            ansiiprint.echo('Setting unmigration for VM "{}"'.format(dom_uuid), '', 'i')
            transaction = self.zk.transaction()
            transaction.set_data('/domains/{}/state'.format(dom_uuid), 'migrate'.encode('ascii'))
            transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), self.name.encode('ascii'))
            transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), ''.encode('ascii'))
            transaction.commit()

            # Wait 2s between migrations
            time.sleep(2)

        self.inflush = False

    def update_zookeeper(self):
        # Connect to libvirt
        libvirt_name = "qemu:///system"
        conn = libvirt.open(libvirt_name)
        if conn == None:
            ansiiprint.echo('Failed to open connection to "{}"'.format(libvirt_name), '', 'e')
            return

        # Get past state and update if needed
        past_state = self.zk.get('/nodes/{}/daemonstate'.format(self.name))[0].decode('ascii')
        if past_state != 'start':
            self.daemon_state = 'start'
            self.zk.set('/nodes/{}/daemonstate'.format(self.name), 'run'.encode('ascii'))
        else:
            self.daemon_state = 'start'

        # Toggle state management of dead VMs to restart them
        for domain, instance in self.s_domain.items():
            if instance.inshutdown == False and domain in self.domain_list:
                if instance.getstate() == 'start' and instance.gethypervisor() == self.name:
                    if instance.getdom() != None:
                        try:
                            if instance.getdom().state()[0] != libvirt.VIR_DOMAIN_RUNNING:
                                raise
                        except Exception as e:
                            # Toggle a state "change"
                            self.zk.set('/domains/{}/state'.format(domain), instance.getstate().encode('ascii'))

        # Set our information in zookeeper
        self.name = conn.getHostname()
        self.memused = int(psutil.virtual_memory().used / 1024 / 1024)
        self.memfree = int(psutil.virtual_memory().free / 1024 / 1024)
        self.cpuload = os.getloadavg()[0]
        self.domains_count = len(conn.listDomainsID())
        keepalive_time = int(time.time())
        try:
            transaction = self.zk.transaction()
            transaction.set_data('/nodes/{}/memused'.format(self.name), str(self.memused).encode('ascii'))
            transaction.set_data('/nodes/{}/memfree'.format(self.name), str(self.memfree).encode('ascii'))
            transaction.set_data('/nodes/{}/cpuload'.format(self.name), str(self.cpuload).encode('ascii'))
            transaction.set_data('/nodes/{}/runningdomains'.format(self.name), ' '.join(self.domain_list).encode('ascii'))
            transaction.set_data('/nodes/{}/domainscount'.format(self.name), str(self.domains_count).encode('ascii'))
            transaction.set_data('/nodes/{}/keepalive'.format(self.name), str(keepalive_time).encode('ascii'))
            transaction.commit()
        except:
            return

        # Close the Libvirt connection
        conn.close()

        # Display node information to the terminal
        ansiiprint.echo('{}{} keepalive{}'.format(ansiiprint.purple(), self.name, ansiiprint.end()), '', 't')
        ansiiprint.echo('{0}Active domains:{1} {2}  {0}Free memory [MiB]:{1} {3}  {0}Used memory [MiB]:{1} {4}  {0}Load:{1} {5}'.format(ansiiprint.bold(), ansiiprint.end(), self.domains_count, self.memfree, self.memused, self.cpuload), '', 'c')

        # Update our local node lists
        for node_name in self.t_node:
            try:
                node_daemon_state = self.zk.get('/nodes/{}/daemonstate'.format(node_name))[0].decode('ascii')
                node_domain_state = self.zk.get('/nodes/{}/domainstate'.format(node_name))[0].decode('ascii')
                node_keepalive = int(self.zk.get('/nodes/{}/keepalive'.format(node_name))[0].decode('ascii'))
            except:
                node_daemon_state = 'unknown'
                node_domain_state = 'unknown'
                node_keepalive = 0

            # Handle deadtime and fencng if needed
            # (A node is considered dead when its keepalive timer is >6*keepalive_interval seconds
            # out-of-date while in 'start' state)
            node_deadtime = int(time.time()) - ( int(self.config['keepalive_interval']) * 6 )
            if node_keepalive < node_deadtime and node_daemon_state == 'start':
                ansiiprint.echo('Node {} seems dead - starting monitor for fencing'.format(node_name), '', 'w')
                self.zk.set('/nodes/{}/daemonstate'.format(node_name), 'dead'.encode('ascii'))
                fence_thread = threading.Thread(target=fencenode.fence, args=(node_name, self.zk), kwargs={})
                fence_thread.start()

            # Update the arrays
            if node_daemon_state == 'start' and node_domain_state != 'flushed' and node_name not in self.active_node_list:
                self.active_node_list.append(node_name)
                try:
                    self.flushed_node_list.remove(node_name)
                except ValueError:
                    pass
                try:
                    self.inactive_node_list.remove(node_name)
                except ValueError:
                    pass
            if node_daemon_state != 'start' and node_daemon_state != 'flushed' and node_name not in self.inactive_node_list:
                self.inactive_node_list.append(node_name)
                try:
                    self.active_node_list.remove(node_name)
                except ValueError:
                    pass
                try:
                    self.flushed_node_list.remove(node_name)
                except ValueError:
                    pass
            if node_domain_state == 'flushed' and node_name not in self.flushed_node_list:
                self.flushed_node_list.append(node_name)
                try:
                    self.active_node_list.remove(node_name)
                except ValueError:
                    pass
                try:
                    self.inactive_node_list.remove(node_name)
                except ValueError:
                    pass
        
        # Display cluster information to the terminal
        ansiiprint.echo('{}Cluster status{}'.format(ansiiprint.purple(), ansiiprint.end()), '', 't')
        ansiiprint.echo('{}Active nodes:{} {}'.format(ansiiprint.bold(), ansiiprint.end(), ' '.join(self.active_node_list)), '', 'c')
        ansiiprint.echo('{}Inactive nodes:{} {}'.format(ansiiprint.bold(), ansiiprint.end(), ' '.join(self.inactive_node_list)), '', 'c')
        ansiiprint.echo('{}Flushed nodes:{} {}'.format(ansiiprint.bold(), ansiiprint.end(), ' '.join(self.flushed_node_list)), '', 'c')
