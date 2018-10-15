#!/usr/bin/env python3

# NodeInstance.py - Class implementing a PVC node in pvcd
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

import os
import sys
import psutil
import socket
import time
import libvirt
import threading
import subprocess

import pvcd.log as log
import pvcd.zkhandler as zkhandler
import pvcd.common as common

class NodeInstance(object):
    # Initialization function
    def __init__(self, name, this_node, zk_conn, config, logger, d_node, d_network, d_domain):
        # Passed-in variables on creation
        self.name = name
        self.this_node = this_node
        self.zk_conn = zk_conn
        self.config = config
        self.logger = logger
        # The IPMI hostname for fencing
        self.ipmi_hostname = self.config['ipmi_hostname']
        # Which node is primary
        self.primary_node = None
        # States
        self.daemon_mode = zkhandler.readdata(self.zk_conn, '/nodes/{}/daemonmode'.format(self.name))
        self.daemon_state = 'stop'
        self.router_state = 'client'
        self.domain_state = 'ready'
        # Object lists
        self.d_node = d_node
        self.d_network = d_network
        self.d_domain = d_domain
        # Printable lists
        self.active_node_list = []
        self.flushed_node_list = []
        self.inactive_node_list = []
        self.network_list = []
        self.domain_list = []
        # Node resources
        self.networks_count = 0
        self.domains_count = 0
        self.memused = 0
        self.memfree = 0
        self.memalloc = 0
        self.vcpualloc = 0
        # Flags
        self.inflush = False

        # Zookeeper handlers for changed states
        @self.zk_conn.DataWatch('/nodes/{}/daemonstate'.format(self.name))
        def watch_node_daemonstate(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = 'stop'

            if data != self.daemon_state:
                self.daemon_state = data

        @self.zk_conn.DataWatch('/nodes/{}/routerstate'.format(self.name))
        def watch_node_routerstate(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = 'client'

            if self.name == self.this_node and self.daemon_mode == 'coordinator':
                # We're a coordinator so we care about networking
                if data != self.router_state:
                    self.router_state = data
                    if self.router_state == 'primary':
                        self.become_primary()
                    else:
                        self.become_secondary()

        @self.zk_conn.DataWatch('/nodes/{}/domainstate'.format(self.name))
        def watch_node_domainstate(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = 'unknown'

            if data != self.domain_state:
                self.domain_state = data

                # toggle state management of this node
                if self.name == self.this_node:
                    if self.domain_state == 'flush' and self.inflush == False:
                        # Do flushing in a thread so it doesn't block the migrates out
                        flush_thread = threading.Thread(target=self.flush, args=(), kwargs={})
                        flush_thread.start()
                    if self.domain_state == 'unflush' and self.inflush == False:
                        self.unflush()

        @self.zk_conn.DataWatch('/primary_node')
        def watch_primary_node(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = 'none'

            if data != self.primary_node:
                if self.daemon_mode == 'coordinator':
                    # We're a coordinator so we care about networking
                    if data == 'none':
                        # Toggle state management of routing functions
                        if self.name == self.this_node:
                            if self.daemon_state == 'run' and self.router_state != 'primary':
                                # Contend for primary
                                self.logger.out('Contending for primary routing state', state='i')
                                zkhandler.writedata(self.zk_conn, {'/primary_node': self.name })
                    elif data == self.this_node:
                        if self.name == self.this_node:
                            zkhandler.writedata(self.zk_conn, { '/nodes/{}/routerstate'.format(self.name): 'primary' })
                            self.primary_node = data
                    else:
                        if self.name == self.this_node:
                            zkhandler.writedata(self.zk_conn, { '/nodes/{}/routerstate'.format(self.name): 'secondary' })
                            self.primary_node = data
                else:
                    self.primary_node = data
                    

        @self.zk_conn.DataWatch('/nodes/{}/memfree'.format(self.name))
        def watch_node_memfree(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = 0

            if data != self.memfree:
                self.memfree = data
    
        @self.zk_conn.DataWatch('/nodes/{}/memused'.format(self.name))
        def watch_node_memused(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = 0

            if data != self.memused:
                self.memused = data
    
        @self.zk_conn.DataWatch('/nodes/{}/memalloc'.format(self.name))
        def watch_node_memalloc(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = 0

            if data != self.memalloc:
                self.memalloc = data
    
        @self.zk_conn.DataWatch('/nodes/{}/vcpualloc'.format(self.name))
        def watch_node_vcpualloc(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = 0

            if data != self.vcpualloc:
                self.vcpualloc = data
    
        @self.zk_conn.DataWatch('/nodes/{}/runningdomains'.format(self.name))
        def watch_node_runningdomains(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii').split()
            except AttributeError:
                data = []

            if data != self.domain_list:
                self.domain_list = data

        @self.zk_conn.DataWatch('/nodes/{}/networkscount'.format(self.name))
        def watch_node_networkscount(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = 0

            if data != self.networks_count:
                self.networks_count = data
    
        @self.zk_conn.DataWatch('/nodes/{}/domainscount'.format(self.name))
        def watch_node_domainscount(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = 0

            if data != self.domains_count:
                self.domains_count = data
    
    # Update value functions
    def update_node_list(self, d_node):
        self.d_node = d_node

    def update_network_list(self, d_network):
        self.d_network = d_network
        network_list = []
        for network in self.d_network:
            network_list.append(d_network[network].vni)
        self.network_list = network_list

    def update_domain_list(self, d_domain):
        self.d_domain = d_domain

    # Routing primary/secondary states
    def become_secondary(self):
        self.logger.out('Setting router {} to secondary state'.format(self.name), state='i')
        self.logger.out('Network list: {}'.format(', '.join(self.network_list)))
        time.sleep(0.5)
        for network in self.d_network:
            self.d_network[network].stopDHCPServer()
            self.d_network[network].removeGatewayAddress()

    def become_primary(self):
        self.logger.out('Setting router {} to primary state.'.format(self.name), state='i')
        self.logger.out('Network list: {}'.format(', '.join(self.network_list)))
        for network in self.d_network:
            self.d_network[network].createGatewayAddress()
            self.d_network[network].startDHCPServer()

    # Flush all VMs on the host
    def flush(self):
        self.inflush = True
        self.logger.out('Flushing node "{}" of running VMs'.format(self.name), state='i')
        self.logger.out('Domain list: {}'.format(', '.join(self.domain_list)))
        fixed_domain_list = self.domain_list.copy()
        for dom_uuid in fixed_domain_list:
            self.logger.out('Selecting target to migrate VM "{}"'.format(dom_uuid), state='i')

            current_node = zkhandler.readdata(self.zk_conn, '/domains/{}/node'.format(dom_uuid))
            target_node = findTargetHypervisor(self.zk_conn, 'mem', dom_uuid)
            if target_node == None:
                self.logger.out('Failed to find migration target for VM "{}"; shutting down'.format(dom_uuid), state='e')
                zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(dom_uuid): 'shutdown' })
            else:
                self.logger.out('Migrating VM "{}" to node "{}"'.format(dom_uuid, target_node), state='i')
                zkhandler.writedata(self.zk_conn, {
                    '/domains/{}/state'.format(dom_uuid): 'migrate',
                    '/domains/{}/node'.format(dom_uuid): target_node,
                    '/domains/{}/lastnode'.format(dom_uuid): current_node
                })

                # Wait for the VM to migrate so the next VM's free RAM count is accurate (they migrate in serial anyways)
                while True:
                    time.sleep(1)
                    vm_current_state = zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(dom_uuid))
                    if vm_current_state == "start":
                        break

        zkhandler.writedata(self.zk_conn, { '/nodes/{}/runningdomains'.format(self.name): '' })
        zkhandler.writedata(self.zk_conn, { '/nodes/{}/domainstate'.format(self.name): 'flushed' })
        self.inflush = False

    def unflush(self):
        self.inflush = True
        self.logger.out('Restoring node {} to active service.'.format(self.name), state='i')
        zkhandler.writedata(self.zk_conn, { '/nodes/{}/domainstate'.format(self.name): 'ready' })
        fixed_domain_list = self.d_domain.copy()
        for dom_uuid in fixed_domain_list:
            try:
                last_node = zkhandler.readdata(self.zk_conn, '/domains/{}/lastnode'.format(dom_uuid))
            except:
                continue

            if last_node != self.name:
                continue

            self.logger.out('Setting unmigration for VM "{}"'.format(dom_uuid), state='i')
            zkhandler.writedata(self.zk_conn, {
                '/domains/{}/state'.format(dom_uuid): 'migrate',
                '/domains/{}/node'.format(dom_uuid): self.name,
                '/domains/{}/lastnode'.format(dom_uuid): ''
            })

        self.inflush = False

    def update_zookeeper(self):
        # Connect to libvirt
        libvirt_name = "qemu:///system"
        lv_conn = libvirt.open(libvirt_name)
        if lv_conn == None:
            self.logger.out('Failed to open connection to "{}"'.format(libvirt_name), state='e')
            return

        # Get past state and update if needed
        past_state = zkhandler.readdata(self.zk_conn, '/nodes/{}/daemonstate'.format(self.name))
        if past_state != 'run':
            self.daemon_state = 'run'
            zkhandler.writedata(self.zk_conn, { '/nodes/{}/daemonstate'.format(self.name): 'run' })
        else:
            self.daemon_state = 'run'

        # Ensure the primary key is properly set
        if self.name == self.this_node:
            if self.router_state == 'primary':
                if zkhandler.readdata(self.zk_conn, '/primary_node') != self.name:
                    zkhandler.writedata(self.zk_conn, {'/primary_node': self.name})

        # Toggle state management of dead VMs to restart them
        memalloc = 0
        vcpualloc = 0
        for domain, instance in self.d_domain.items():
            if domain in self.domain_list:
                # Add the allocated memory to our memalloc value
                memalloc += instance.getmemory()
                vcpualloc += instance.getvcpus()
                if instance.getstate() == 'start' and instance.getnode() == self.name:
                    if instance.getdom() != None:
                        try:
                            if instance.getdom().state()[0] != libvirt.VIR_DOMAIN_RUNNING:
                                raise
                        except Exception as e:
                            # Toggle a state "change"
                            zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(domain): instance.getstate() })

        # Ensure that any running VMs are readded to the domain_list
        running_domains = lv_conn.listAllDomains(libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE)
        for domain in running_domains:
            domain_uuid = domain.UUIDString()
            if domain_uuid not in self.domain_list:
                self.domain_list.append(domain_uuid)

        # Set our information in zookeeper
        #self.name = lv_conn.getHostname()
        self.memused = int(psutil.virtual_memory().used / 1024 / 1024)
        self.memfree = int(psutil.virtual_memory().free / 1024 / 1024)
        self.memalloc = memalloc
        self.vcpualloc = vcpualloc
        self.cpuload = os.getloadavg()[0]
        self.domains_count = len(lv_conn.listDomainsID())
        keepalive_time = int(time.time())
        try:
            zkhandler.writedata(self.zk_conn, {
                '/nodes/{}/memused'.format(self.name): str(self.memused),
                '/nodes/{}/memfree'.format(self.name): str(self.memfree),
                '/nodes/{}/memalloc'.format(self.name): str(self.memalloc),
                '/nodes/{}/vcpualloc'.format(self.name): str(self.vcpualloc),
                '/nodes/{}/cpuload'.format(self.name): str(self.cpuload),
                '/nodes/{}/networkscount'.format(self.name): str(self.networks_count),
                '/nodes/{}/domainscount'.format(self.name): str(self.domains_count),
                '/nodes/{}/runningdomains'.format(self.name): ' '.join(self.domain_list),
                '/nodes/{}/keepalive'.format(self.name): str(keepalive_time)
            })
        except:
            self.logger.out('Failed to set keepalive data', state='e')
            return

        # Close the Libvirt connection
        lv_conn.close()

        # Display node information to the terminal
        self.logger.out('{}{} keepalive{}'.format(self.logger.fmt_purple, self.name, self.logger.fmt_end), state='t')
        self.logger.out(
            '{bold}Domains:{nobold} {domcount}  '
            '{bold}Networks:{nobold} {netcount}  '
            '{bold}VM memory [MiB]:{nobold} {allocmem}  '
            '{bold}Free memory [MiB]:{nobold} {freemem}  '
            '{bold}Used memory [MiB]:{nobold} {usedmem}  '
            '{bold}Load:{nobold} {load}'.format(
                bold=self.logger.fmt_bold,
                nobold=self.logger.fmt_end,
                domcount=self.domains_count,
                freemem=self.memfree,
                usedmem=self.memused,
                load=self.cpuload,
                allocmem=self.memalloc,
                netcount=self.networks_count
            ),
        )

        # Update our local node lists
        for node_name in self.d_node:
            try:
                node_daemon_state = zkhandler.readdata(self.zk_conn, '/nodes/{}/daemonstate'.format(node_name))
                node_domain_state = zkhandler.readdata(self.zk_conn, '/nodes/{}/domainstate'.format(node_name))
                node_keepalive = int(zkhandler.readdata(self.zk_conn, '/nodes/{}/keepalive'.format(node_name)))
            except:
                node_daemon_state = 'unknown'
                node_domain_state = 'unknown'
                node_keepalive = 0

            # Handle deadtime and fencng if needed
            # (A node is considered dead when its keepalive timer is >6*keepalive_interval seconds
            # out-of-date while in 'start' state)
            node_deadtime = int(time.time()) - ( int(self.config['keepalive_interval']) * int(self.config['fence_intervals']) )
            if node_keepalive < node_deadtime and node_daemon_state == 'run':
                self.logger.out('Node {} seems dead - starting monitor for fencing'.format(node_name), state='w')
                zkhandler.writedata(self.zk_conn, { '/nodes/{}/daemonstate'.format(node_name): 'dead' })
                fence_thread = threading.Thread(target=fenceNode, args=(node_name, self.zk_conn, self.config, self.logger), kwargs={})
                fence_thread.start()

            # Update the arrays
            if node_daemon_state == 'run' and node_domain_state != 'flushed' and node_name not in self.active_node_list:
                self.active_node_list.append(node_name)
                try:
                    self.flushed_node_list.remove(node_name)
                except ValueError:
                    pass
                try:
                    self.inactive_node_list.remove(node_name)
                except ValueError:
                    pass
            if node_daemon_state != 'run' and node_domain_state != 'flushed' and node_name not in self.inactive_node_list:
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
       
        # List of the non-primary coordinators
        secondary_node_list = self.config['coordinators'].split(',')
        if secondary_node_list:
            secondary_node_list.remove(self.primary_node)
            for node in secondary_node_list:
                if node in self.inactive_node_list:
                    secondary_node_list.remove(node)

        # Display cluster information to the terminal
        self.logger.out('{}Cluster status{}'.format(self.logger.fmt_purple, self.logger.fmt_end), state='t')
        self.logger.out('{}Primary coordinator:{} {}'.format(self.logger.fmt_bold, self.logger.fmt_end, self.primary_node))
        self.logger.out('{}Secondary coordinators:{} {}'.format(self.logger.fmt_bold, self.logger.fmt_end, ' '.join(secondary_node_list)))
        self.logger.out('{}Active hypervisors:{} {}'.format(self.logger.fmt_bold, self.logger.fmt_end, ' '.join(self.active_node_list)))
        self.logger.out('{}Flushed hypervisors:{} {}'.format(self.logger.fmt_bold, self.logger.fmt_end, ' '.join(self.flushed_node_list)))
        self.logger.out('{}Inactive nodes:{} {}'.format(self.logger.fmt_bold, self.logger.fmt_end, ' '.join(self.inactive_node_list)))

#
# Find a migration target
#
def findTargetHypervisor(zk_conn, search_field, dom_uuid):
    if search_field == 'mem':
        return findTargetHypervisorMem(zk_conn, dom_uuid)
    if search_field == 'load':
        return findTargetHypervisorLoad(zk_conn, dom_uuid)
    if search_field == 'vcpus':
        return findTargetHypervisorVCPUs(zk_conn, dom_uuid)
    if search_field == 'vms':
        return findTargetHypervisorVMs(zk_conn, dom_uuid)
    return None

# Get the list of valid target nodes
def getHypervisors(zk_conn, dom_uuid):
    valid_node_list = []
    full_node_list = zkhandler.listchildren(zk_conn, '/nodes')
    current_node = zkhandler.readdata(zk_conn, '/domains/{}/node'.format(dom_uuid))

    for node in full_node_list:
        daemon_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(node))
        domain_state = zkhandler.readdata(zk_conn, '/nodes/{}/domainstate'.format(node))

        if node == current_node:
            continue

        if daemon_state != 'run' or domain_state != 'ready':
            continue

        valid_node_list.append(node)

    return valid_node_list
    
# via free memory (relative to allocated memory)
def findTargetHypervisorMem(zk_conn, dom_uuid):
    most_allocfree = 0
    target_node = None

    node_list = getHypervisors(zk_conn, dom_uuid)
    for node in node_list:
        memalloc = int(zkhandler.readdata(zk_conn, '/nodes/{}/memalloc'.format(node)))
        memused = int(zkhandler.readdata(zk_conn, '/nodes/{}/memused'.format(node)))
        memfree = int(zkhandler.readdata(zk_conn, '/nodes/{}/memfree'.format(node)))
        memtotal = memused + memfree
        allocfree = memtotal - memalloc

        if allocfree > most_allocfree:
            most_allocfree = allocfree
            target_node = node

    return target_node

# via load average
def findTargetHypervisorLoad(zk_conn, dom_uuid):
    least_load = 9999
    target_node = None

    node_list = getHypervisors(zk_conn, dom_uuid)
    for node in node_list:
        load = int(zkhandler.readdata(zk_conn, '/nodes/{}/load'.format(node)))

        if load < least_load:
            least_load = load
            target_hypevisor = node

    return target_node

# via total vCPUs
def findTargetHypervisorVCPUs(zk_conn, dom_uuid):
    least_vcpus = 9999
    target_node = None

    node_list = getHypervisors(zk_conn, dom_uuid)
    for node in node_list:
        vcpus = int(zkhandler.readdata(zk_conn, '/nodes/{}/vcpualloc'.format(node)))

        if vcpus < least_vcpus:
            least_vcpus = vcpus
            target_node = node

    return target_node

# via total VMs
def findTargetHypervisorVMs(zk_conn, dom_uuid):
    least_vms = 9999
    target_node = None

    node_list = getHypervisors(zk_conn, dom_uuid)
    for node in node_list:
        vms = int(zkhandler.readdata(zk_conn, '/nodes/{}/domainscount'.format(node)))

        if vms < least_vms:
            least_vms = vms
            target_node = node

    return target_node


#
# Fence thread entry function
#
def fenceNode(node_name, zk_conn, config, logger):
    failcount = 0
    # We allow exactly 3 saving throws for the host to come back online
    while failcount < 3:
        # Wait 5 seconds
        time.sleep(5)
        # Get the state
        node_daemon_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(node_name))
        # Is it still 'dead'
        if node_daemon_state == 'dead':
            failcount += 1
            logger.out('Node "{}" failed {} saving throws'.format(node_name, failcount), state='w')
        # It changed back to something else so it must be alive
        else:
            logger.out('Node "{}" passed a saving throw; canceling fence'.format(node_name), state='o')
            return

    logger.out('Fencing node "{}" via IPMI reboot signal'.format(node_name), state='e')

    # Get IPMI information
    ipmi_hostname = zkhandler.readdata(zk_conn, '/nodes/{}/ipmihostname'.format(node_name))
    ipmi_username = zkhandler.readdata(zk_conn, '/nodes/{}/ipmiusername'.format(node_name))
    ipmi_password = zkhandler.readdata(zk_conn, '/nodes/{}/ipmipassword'.format(node_name))

    # Shoot it in the head
    fence_status = rebootViaIPMI(ipmi_hostname, ipmi_username, ipmi_password, logger)
    # Hold to ensure the fence takes effect
    time.sleep(3)

    # Force into secondary network state if needed
    if node_name in config['coordinators'].split(','):
        zkhandler.writedata(zk_conn, { '/nodes/{}/routerstate'.format(node_name): 'secondary' })
        if zkhandler.readdata(zk_conn, '/primary_node') == node_name:
            zkhandler.writedata(zk_conn, { '/primary_node': 'none' })
        
    # If the fence succeeded and successful_fence is migrate
    if fence_status == True and config['successful_fence'] == 'migrate':
        migrateFromFencedNode(zk_conn, node_name, logger)
    # If the fence failed and failed_fence is migrate
    if fence_status == False and config['failed_fence'] == 'migrate' and config['suicide_intervals'] != '0':
        migrateFromFencedNode(zk_conn, node_name, logger)

# Migrate hosts away from a fenced node
def migrateFromFencedNode(zk_conn, node_name, logger):
    logger.out('Moving VMs from dead node "{}" to new hosts'.format(node_name), state='i')
    dead_node_running_domains = zkhandler.readdata(zk_conn, '/nodes/{}/runningdomains'.format(node_name)).split()
    for dom_uuid in dead_node_running_domains:
        target_node = findTargetHypervisor(zk_conn, 'mem', dom_uuid)

        logger.out('Moving VM "{}" to node "{}"'.format(dom_uuid, target_node), state='i')
        zkhandler.writedata(zk_conn, {
            '/domains/{}/state'.format(dom_uuid): 'start',
            '/domains/{}/node'.format(dom_uuid): target_node,
            '/domains/{}/lastnode'.format(dom_uuid): node_name
        })

    # Set node in flushed state for easy remigrating when it comes back
    zkhandler.writedata(zk_conn, { '/nodes/{}/domainstate'.format(node_name): 'flushed' })

#
# Perform an IPMI fence
#
def rebootViaIPMI(ipmi_hostname, ipmi_user, ipmi_password, logger):
    ipmi_command = ['/usr/bin/ipmitool', '-I', 'lanplus', '-H', ipmi_hostname, '-U', ipmi_user, '-P', ipmi_password, 'chassis', 'power', 'reset']
    ipmi_command_output = subprocess.run(ipmi_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if ipmi_command_output.returncode == 0:
        logger.out('Successfully rebooted dead node', state='o')
        return True
    else:
        logger.out('Failed to reboot dead node', state='e')
        return False
