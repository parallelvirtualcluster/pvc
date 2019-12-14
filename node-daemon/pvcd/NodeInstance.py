#!/usr/bin/env python3

# NodeInstance.py - Class implementing a PVC node in pvcd
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2019 Joshua M. Boniface <joshua@boniface.me>
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
    def __init__(self, name, this_node, zk_conn, config, logger, d_node, d_network, d_domain, dns_aggregator, metadata_api):
        # Passed-in variables on creation
        self.name = name
        self.this_node = this_node
        self.zk_conn = zk_conn
        self.config = config
        self.logger = logger
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
        self.metadata_api = metadata_api
        # Printable lists
        self.active_node_list = []
        self.flushed_node_list = []
        self.inactive_node_list = []
        self.network_list = []
        self.domain_list = []
        # Node resources
        self.domains_count = 0
        self.memused = 0
        self.memfree = 0
        self.memalloc = 0
        self.vcpualloc = 0
        # Floating upstreams
        if self.config['enable_networking']:
            self.vni_dev = self.config['vni_dev']
            self.vni_ipaddr, self.vni_cidrnetmask = self.config['vni_floating_ip'].split('/')
            self.upstream_dev = self.config['upstream_dev']
            self.upstream_ipaddr, self.upstream_cidrnetmask = self.config['upstream_floating_ip'].split('/')
        else:
            self.vni_dev = None
            self.vni_ipaddr = None
            self.vni_cidrnetmask = None
            self.upstream_dev = None
            self.upstream_ipaddr = None
            self.upstream_cidrnetmask = None
        # Threads
        self.flush_thread = None
        # Flags
        self.flush_stopper = False

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
                    if self.config['enable_networking']:
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
                    # Stop any existing flush jobs
                    if self.flush_thread:
                        self.flush_stopper = True
                        self.logger.out('Waiting for previous migration to complete'.format(self.name), state='i')
                        while self.flush_stopper:
                            time.sleep(1)
                    self.flush_stopper = False
                    # Do flushing in a thread so it doesn't block the migrates out
                    if self.domain_state == 'flush':
                        self.flush_thread = threading.Thread(target=self.flush, args=(), kwargs={})
                        self.flush_thread.start()
                    # Do unflushing in a thread so it doesn't block the migrates in
                    if self.domain_state == 'unflush':
                        self.flush_thread = threading.Thread(target=self.unflush, args=(), kwargs={})
                        self.flush_thread.start()

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
        self.logger.out('Network list: {}'.format(', '.join(self.network_list)), state='i')
        time.sleep(2)
        if self.config['enable_api']:
            self.logger.out('Stopping PVC API client service', state='i')
            common.run_os_command("systemctl stop pvc-api.service")
        for network in self.d_network:
            self.d_network[network].stopDHCPServer()
            self.d_network[network].removeGateways()
        self.dns_aggregator.stop_aggregator()
        self.metadata_api.stop()
        self.removeFloatingAddresses()

    def become_primary(self):
        # Establish a lock
        with zkhandler.writelock(self.zk_conn, '/primary_node'):
            self.logger.out('Setting router {} to primary state'.format(self.name), state='i')

            # Create floating addresses
            self.logger.out('Network list: {}'.format(', '.join(self.network_list)), state='i')
            self.createFloatingAddresses()
            # Start up the gateways and DHCP servers
            for network in self.d_network:
                self.d_network[network].createGateways()
                self.d_network[network].startDHCPServer()
            time.sleep(1)

            # Switch Patroni leader to the local instance
            self.logger.out('Setting Patroni leader to this node', state='i')
            tick = 1
            while True:
                retcode, stdout, stderr = common.run_os_command(
                    """
                    patronictl
                        -c /etc/patroni/config.yml
                        -d zookeeper://localhost:2181
                        switchover
                        --candidate {}
                        --force
                        pvcdns
                    """.format(self.name)
                )
                if stdout:
                    self.logger.out('Successfully switched Patroni leader\n{}'.format(stdout), state='o')
                    break
                elif stderr == "Error: Switchover target and source are the same.\n":
                    self.logger.out('Failed to switch Patroni leader to ourselves; this is fine\n{}'.format(stderr), state='w')
                    break
                elif tick >= 5:
                    self.logger.out('Failed to switch Patroni leader after 5 tries; aborting\n{}'.format(stderr), state='e')
                    break
                else:
                    self.logger.out('Failed to switch Patroni leader; retrying [{}/5]\n{}'.format(tick, stderr), state='e')
                    tick += 1
                    time.sleep(2)

            # Start the DNS aggregator instance
            time.sleep(1)
            self.dns_aggregator.start_aggregator()
            self.metadata_api.start()

            # Start the clients
            if self.config['enable_api']:
                self.logger.out('Starting PVC API client service', state='i')
                common.run_os_command("systemctl start pvc-api.service")
                self.logger.out('Starting PVC Provisioner Worker service', state='i')
                common.run_os_command("systemctl start pvc-provisioner-worker.service")

    def createFloatingAddresses(self):
        # Metadata link-local IP
        self.logger.out(
            'Creating Metadata link-local IP {}/{} on interface {}'.format(
                '169.254.169.254',
                '32',
                'lo'
            ),
            state='o'
        )
        common.createIPAddress('169.254.169.254', '32', 'lo')

        # VNI floating IP
        self.logger.out(
            'Creating floating management IP {}/{} on interface {}'.format(
                self.vni_ipaddr,
                self.vni_cidrnetmask,
                'brcluster'
            ),
            state='o'
        )
        common.createIPAddress(self.vni_ipaddr, self.vni_cidrnetmask, 'brcluster')

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
        # Metadata link-local IP
        self.logger.out(
            'Removing Metadata link-local IP {}/{} from interface {}'.format(
                '169.254.169.254',
                '32',
                'lo'
            ),
            state='o'
        )
        common.removeIPAddress('169.254.169.254', '32', 'lo')

        # VNI floating IP
        self.logger.out(
            'Removing floating management IP {}/{} from interface {}'.format(
                self.vni_ipaddr,
                self.vni_cidrnetmask,
                'brcluster'
            ),
            state='o'
        )
        common.removeIPAddress(self.vni_ipaddr, self.vni_cidrnetmask, 'brcluster')

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
        # Begin flush
        self.logger.out('Flushing node "{}" of running VMs'.format(self.name), state='i')
        self.logger.out('VM list: {}'.format(', '.join(self.domain_list)), state='i')
        fixed_domain_list = self.domain_list.copy()
        for dom_uuid in fixed_domain_list:
            # Allow us to cancel the operation
            if self.flush_stopper:
                self.logger.out('Aborting node flush'.format(self.name), state='i')
                self.flush_thread = None
                self.flush_stopper = False
                return

            self.logger.out('Selecting target to migrate VM "{}"'.format(dom_uuid), state='i')

            target_node = common.findTargetNode(self.zk_conn, self.config, dom_uuid)

            # Don't replace the previous node if the VM is already migrated
            if zkhandler.readdata(self.zk_conn, '/domains/{}/lastnode'.format(dom_uuid)):
                current_node = zkhandler.readdata(self.zk_conn, '/domains/{}/lastnode'.format(dom_uuid))
            else:
                current_node = zkhandler.readdata(self.zk_conn, '/domains/{}/node'.format(dom_uuid))

            if target_node is None:
                self.logger.out('Failed to find migration target for VM "{}"; shutting down and setting autostart flag'.format(dom_uuid), state='e')
                zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(dom_uuid): 'shutdown' })
                zkhandler.writedata(self.zk_conn, { '/domains/{}/node_autostart'.format(dom_uuid): 'True' })

                # Wait for the VM to shut down
                while zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(dom_uuid)) != 'stop':
                    time.sleep(1)

                continue

            self.logger.out('Migrating VM "{}" to node "{}"'.format(dom_uuid, target_node), state='i')
            zkhandler.writedata(self.zk_conn, {
                '/domains/{}/state'.format(dom_uuid): 'migrate',
                '/domains/{}/node'.format(dom_uuid): target_node,
                '/domains/{}/lastnode'.format(dom_uuid): current_node
            })

            # Wait for the VM to migrate so the next VM's free RAM count is accurate (they migrate in serial anyways)
            while zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(dom_uuid)) != 'start':
                time.sleep(1)

        zkhandler.writedata(self.zk_conn, { '/nodes/{}/runningdomains'.format(self.name): '' })
        zkhandler.writedata(self.zk_conn, { '/nodes/{}/domainstate'.format(self.name): 'flushed' })
        self.flush_thread = None
        self.flush_stopper = False

    def unflush(self):
        self.logger.out('Restoring node {} to active service.'.format(self.name), state='i')
        fixed_domain_list = self.d_domain.copy()
        for dom_uuid in fixed_domain_list:
            # Allow us to cancel the operation
            if self.flush_stopper:
                self.logger.out('Aborting node unflush'.format(self.name), state='i')
                self.flush_thread = None
                self.flush_stopper = False
                return

            # Handle autostarts
            autostart = zkhandler.readdata(self.zk_conn, '/domains/{}/node_autostart'.format(dom_uuid))
            node = zkhandler.readdata(self.zk_conn, '/domains/{}/node'.format(dom_uuid))
            if autostart == 'True' and node == self.name:
                self.logger.out('Starting autostart VM "{}"'.format(dom_uuid), state='i')
                zkhandler.writedata(self.zk_conn, {
                    '/domains/{}/state'.format(dom_uuid): 'start',
                    '/domains/{}/node'.format(dom_uuid): self.name,
                    '/domains/{}/lastnode'.format(dom_uuid): '',
                    '/domains/{}/node_autostart'.format(dom_uuid): 'False'
                })
                continue

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

            # Wait for the VM to migrate back
            while zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(dom_uuid)) != 'start':
                time.sleep(1)

        zkhandler.writedata(self.zk_conn, { '/nodes/{}/domainstate'.format(self.name): 'ready' })
        self.flush_thread = None
        self.flush_stopper = False
