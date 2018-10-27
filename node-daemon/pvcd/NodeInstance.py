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

import pvcd.log as log
import pvcd.zkhandler as zkhandler
import pvcd.common as common

class NodeInstance(object):
    # Initialization function
    def __init__(self, name, this_node, zk_conn, config, logger, d_node, d_network, d_domain, dns_aggregator):
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
        self.dns_aggregator = dns_aggregator
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
        # Floating upstreams
        self.vni_dev = self.config['vni_dev']
        self.vni_ipaddr, self.vni_cidrnetmask = self.config['vni_floating_ip'].split('/')
        self.upstream_dev = self.config['upstream_dev']
        self.upstream_ipaddr, self.upstream_cidrnetmask = self.config['upstream_floating_ip'].split('/')
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
        time.sleep(1)
        for network in self.d_network:
            self.d_network[network].stopDHCPServer()
            self.d_network[network].removeGatewayAddress()
            self.dns_aggregator.remove_client_network(network)
        self.dns_aggregator.stop_aggregator()
        self.removeFloatingAddresses()

    def become_primary(self):
        self.logger.out('Setting router {} to primary state.'.format(self.name), state='i')
        self.logger.out('Network list: {}'.format(', '.join(self.network_list)))
        self.createFloatingAddresses()
        self.dns_aggregator.start_aggregator()
        time.sleep(0.5)
        # Start up the gateways and DHCP servers
        for network in self.d_network:
            self.dns_aggregator.add_client_network(network)
            self.d_network[network].createGatewayAddress()
            self.d_network[network].startDHCPServer()
        time.sleep(0.5)
        # Handle AXFRs after to avoid slowdowns
        for network in self.d_network: 
            self.dns_aggregator.get_axfr(network)

    def createFloatingAddresses(self):
        # VNI floating IP
        self.logger.out(
            'Creating floating management IP {}/{} on interface {}'.format(
                self.vni_ipaddr,
                self.vni_cidrnetmask,
                self.vni_dev
            ),
            state='o'
        )
        common.createIPAddress(self.vni_ipaddr, self.vni_cidrnetmask, self.vni_dev)
        # Upstream floating IP
        self.logger.out(
            'Creating floating upstream IP {}/{} on interface {}'.format(
                self.upstream_ipaddr,
                self.upstream_cidrnetmask,
                self.upstream_dev
            ),
            state='o'
        )
        common.createIPAddress(self.upstream_ipaddr, self.upstream_cidrnetmask, self.upstream_dev)

    def removeFloatingAddresses(self):
        # VNI floating IP
        self.logger.out(
            'Removing floating management IP {}/{} from interface {}'.format(
                self.vni_ipaddr,
                self.vni_cidrnetmask,
                self.vni_dev
            ),
            state='o'
        )
        common.removeIPAddress(self.vni_ipaddr, self.vni_cidrnetmask, self.vni_dev)
        # Upstream floating IP
        self.logger.out(
            'Removing floating upstream IP {}/{} from interface {}'.format(
                self.upstream_ipaddr,
                self.upstream_cidrnetmask,
                self.upstream_dev
            ),
            state='o'
        )
        common.removeIPAddress(self.upstream_ipaddr, self.upstream_cidrnetmask, self.upstream_dev)

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
