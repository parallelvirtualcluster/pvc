#!/usr/bin/env python3

# NodeInstance.py - Class implementing a PVC node in pvcnoded
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2020 Joshua M. Boniface <joshua@boniface.me>
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

import pvcnoded.log as log
import pvcnoded.zkhandler as zkhandler
import pvcnoded.common as common

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
        # Floating IP configurations
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
                            self.logger.out('Setting node {} to primary state'.format(self.name), state='i')
                            transition_thread = threading.Thread(target=self.become_primary, args=(), kwargs={})
                            transition_thread.start()
                        else:
                            # Skip becoming secondary unless already running
                            if self.daemon_state == 'run' or self.daemon_state == 'shutdown':
                                self.logger.out('Setting node {} to secondary state'.format(self.name), state='i')
                                transition_thread = threading.Thread(target=self.become_secondary, args=(), kwargs={})
                                transition_thread.start()

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
                    if self.flush_thread is not None:
                        self.logger.out('Waiting for previous migration to complete'.format(self.name), state='i')
                        self.flush_stopper = True
                        while self.flush_stopper:
                            time.sleep(0.1)

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

    ######
    # Phases of node transition
    #
    # Current Primary                   Candidate Secondary
    #   -> secondary                      -> primary
    #
    # def become_secondary()            def become_primary()
    #
    # A ----------------------------------------------------------------- SYNC (candidate)
    # B ----------------------------------------------------------------- SYNC (current)
    # 1. Stop DNS aggregator                                               ||
    # 2. Stop DHCP servers                                                 ||
    #    4a) network 1                                                     ||
    #    4b) network 2                                                     ||
    #    etc.                                                              ||
    # 3. Stop client API                                                   ||
    # 4. Stop metadata API                                                 ||
    #                                                                      --
    # C ----------------------------------------------------------------- SYNC (candidate)
    # 5. Remove upstream floating IP    1. Add upstream floating IP        ||
    #                                                                      --
    # D ----------------------------------------------------------------- SYNC (candidate)
    # 6. Remove cluster floating IP     2. Add cluster floating IP         ||
    #                                                                      --
    # E ----------------------------------------------------------------- SYNC (candidate)
    # 7. Remove metadata floating IP    3. Add metadata floating IP        ||
    #                                                                      --
    # F ----------------------------------------------------------------- SYNC (candidate)
    # 8. Remove gateway IPs             4. Add gateway IPs                 ||
    #    8a) network 1                     4a) network 1                   ||
    #    8b) network 2                     4b) network 2                   ||
    #    etc.                              etc.                            ||
    #                                                                      --
    # G ----------------------------------------------------------------- SYNC (candidate)
    #                                   5. Transition Patroni primary      ||
    #                                   6. Start client API                ||
    #                                   7. Start metadata API              ||
    #                                   8. Start DHCP servers              ||
    #                                      5a) network 1                   ||
    #                                      5b) network 2                   ||
    #                                      etc.                            ||
    #                                   9. Start DNS aggregator            ||
    #                                                                      --
    ######
    def become_primary(self):
        """
        Acquire primary coordinator status from a peer node
        """
        # Lock the primary node until transition is complete
        primary_lock = zkhandler.writelock(self.zk_conn, '/primary_node')
        primary_lock.acquire()

        # Ensure our lock key is populated
        zkhandler.writedata(self.zk_conn, {'/locks/primary_node': ''})

        # Synchronize nodes A (I am writer)
        lock = zkhandler.writelock(self.zk_conn, '/locks/primary_node')
        self.logger.out('Acquiring write lock for synchronization A', state='i')
        lock.acquire()
        self.logger.out('Acquired write lock for synchronization A', state='o')
        time.sleep(1) # Time for reader to acquire the lock
        self.logger.out('Releasing write lock for synchronization A', state='i')
        zkhandler.writedata(self.zk_conn, {'/locks/primary_node': ''})
        lock.release()
        self.logger.out('Released write lock for synchronization A', state='o')
        time.sleep(0.1) # Time for new writer to acquire the lock

        # Synchronize nodes B (I am reader)
        lock = zkhandler.readlock(self.zk_conn, '/locks/primary_node')
        self.logger.out('Acquiring read lock for synchronization B', state='i')
        lock.acquire()
        self.logger.out('Acquired read lock for synchronization B', state='o')
        self.logger.out('Releasing read lock for synchronization B', state='i')
        lock.release()
        self.logger.out('Released read lock for synchronization B', state='o')

        # Synchronize nodes C (I am writer)
        lock = zkhandler.writelock(self.zk_conn, '/locks/primary_node')
        self.logger.out('Acquiring write lock for synchronization C', state='i')
        lock.acquire()
        self.logger.out('Acquired write lock for synchronization C', state='o')
        time.sleep(0.5) # Time for reader to acquire the lock
        # 1. Add Upstream floating IP
        self.logger.out(
            'Creating floating upstream IP {}/{} on interface {}'.format(
                self.upstream_ipaddr,
                self.upstream_cidrnetmask,
                'brupstream'
            ),
            state='o'
        )
        common.createIPAddress(self.upstream_ipaddr, self.upstream_cidrnetmask, 'brupstream')
        self.logger.out('Releasing write lock for synchronization C', state='i')
        zkhandler.writedata(self.zk_conn, {'/locks/primary_node': ''})
        lock.release()
        self.logger.out('Released write lock for synchronization C', state='o')

        # Synchronize nodes D (I am writer)
        lock = zkhandler.writelock(self.zk_conn, '/locks/primary_node')
        self.logger.out('Acquiring write lock for synchronization D', state='i')
        lock.acquire()
        self.logger.out('Acquired write lock for synchronization D', state='o')
        time.sleep(0.2) # Time for reader to acquire the lock
        # 2. Add Cluster floating IP
        self.logger.out(
            'Creating floating management IP {}/{} on interface {}'.format(
                self.vni_ipaddr,
                self.vni_cidrnetmask,
                'brcluster'
            ),
            state='o'
        )
        common.createIPAddress(self.vni_ipaddr, self.vni_cidrnetmask, 'brcluster')
        self.logger.out('Releasing write lock for synchronization D', state='i')
        zkhandler.writedata(self.zk_conn, {'/locks/primary_node': ''})
        lock.release()
        self.logger.out('Released write lock for synchronization D', state='o')

        # Synchronize nodes E (I am writer)
        lock = zkhandler.writelock(self.zk_conn, '/locks/primary_node')
        self.logger.out('Acquiring write lock for synchronization E', state='i')
        lock.acquire()
        self.logger.out('Acquired write lock for synchronization E', state='o')
        time.sleep(0.2) # Time for reader to acquire the lock
        # 3. Add Metadata link-local IP
        self.logger.out(
            'Creating Metadata link-local IP {}/{} on interface {}'.format(
                '169.254.169.254',
                '32',
                'lo'
            ),
            state='o'
        )
        common.createIPAddress('169.254.169.254', '32', 'lo')
        self.logger.out('Releasing write lock for synchronization E', state='i')
        zkhandler.writedata(self.zk_conn, {'/locks/primary_node': ''})
        lock.release()
        self.logger.out('Released write lock for synchronization E', state='o')

        # Synchronize nodes F (I am writer)
        lock = zkhandler.writelock(self.zk_conn, '/locks/primary_node')
        self.logger.out('Acquiring write lock for synchronization F', state='i')
        lock.acquire()
        self.logger.out('Acquired write lock for synchronization F', state='o')
        time.sleep(0.2) # Time for reader to acquire the lock
        # 4. Add gateway IPs
        for network in self.d_network:
            self.d_network[network].createGateways()
        self.logger.out('Releasing write lock for synchronization F', state='i')
        zkhandler.writedata(self.zk_conn, {'/locks/primary_node': ''})
        lock.release()
        self.logger.out('Released write lock for synchronization F', state='o')

        # Synchronize nodes G (I am writer)
        lock = zkhandler.writelock(self.zk_conn, '/locks/primary_node')
        self.logger.out('Acquiring write lock for synchronization G', state='i')
        lock.acquire()
        self.logger.out('Acquired write lock for synchronization G', state='o')
        time.sleep(0.2) # Time for reader to acquire the lock
        # 5. Transition Patroni primary
        self.logger.out('Setting Patroni leader to this node', state='i')
        tick = 1
        patroni_failed = True
        # As long as we're primary, keep trying to set the Patroni leader to us
        while self.router_state == 'primary':
            # Switch Patroni leader to the local instance
            retcode, stdout, stderr = common.run_os_command(
                """
                patronictl
                    -c /etc/patroni/config.yml
                    -d zookeeper://localhost:2181
                    switchover
                    --candidate {}
                    --force
                    pvc
                """.format(self.name)
            )

            # Combine the stdout and stderr and strip the output
            # Patronictl's output is pretty junky
            if stderr:
                stdout += stderr
            stdout = stdout.strip()

            # Handle our current Patroni leader being us
            if stdout and stdout.split('\n')[-1].split() == ["Error:", "Switchover", "target", "and", "source", "are", "the", "same."]:
                self.logger.out('Failed to switch Patroni leader to ourselves; this is fine\n{}'.format(stdout), state='w')
                break
            # Handle a failed switchover
            elif stdout and (stdout.split('\n')[-1].split()[:2] == ["Switchover", "failed,"] or stdout.strip().split('\n')[-1].split()[:1] == ["Error"]):
                if tick > 4:
                    self.logger.out('Failed to switch Patroni leader after 5 tries; aborting', state='e')
                    break
                else:
                    self.logger.out('Failed to switch Patroni leader; retrying [{}/5]\n{}\n'.format(tick, stdout), state='e')
                    tick += 1
                    time.sleep(5)
            # Otherwise, we succeeded
            else:
                self.logger.out('Successfully switched Patroni leader\n{}'.format(stdout), state='o')
                patroni_failed = False
                time.sleep(0.2)
                break
        # 6. Start client API (and provisioner worker)
        if self.config['enable_api']:
            self.logger.out('Starting PVC API client service', state='i')
            common.run_os_command("systemctl start pvcapid.service")
            self.logger.out('Starting PVC Provisioner Worker service', state='i')
            common.run_os_command("systemctl start pvcapid-worker.service")
        # 7. Start metadata API; just continue if we fail
        self.metadata_api.start()
        # 8. Start DHCP servers
        for network in self.d_network:
            self.d_network[network].startDHCPServer()
        # 9. Start DNS aggregator; just continue if we fail
        if not patroni_failed:
            self.dns_aggregator.start_aggregator()
        else:
            self.logger.out('Not starting DNS aggregator due to Patroni failures', state='e')
        self.logger.out('Releasing write lock for synchronization G', state='i')
        zkhandler.writedata(self.zk_conn, {'/locks/primary_node': ''})
        lock.release()
        self.logger.out('Released write lock for synchronization G', state='o')

        primary_lock.release()
        self.logger.out('Node {} transitioned to primary state'.format(self.name), state='o')

    def become_secondary(self):
        """
        Relinquish primary coordinator status to a peer node
        """
        time.sleep(0.2) # Initial delay for the first writer to grab the lock

        # Synchronize nodes A (I am reader)
        lock = zkhandler.readlock(self.zk_conn, '/locks/primary_node')
        self.logger.out('Acquiring read lock for synchronization A', state='i')
        lock.acquire()
        self.logger.out('Acquired read lock for synchronization A', state='o')
        self.logger.out('Releasing read lock for synchronization A', state='i')
        lock.release()
        self.logger.out('Released read lock for synchronization A', state='o')

        # Synchronize nodes B (I am writer)
        lock = zkhandler.writelock(self.zk_conn, '/locks/primary_node')
        self.logger.out('Acquiring write lock for synchronization B', state='i')
        lock.acquire()
        self.logger.out('Acquired write lock for synchronization B', state='o')
        time.sleep(0.2) # Time for reader to acquire the lock
        # 1. Stop DNS aggregator
        self.dns_aggregator.stop_aggregator()
        # 2. Stop DHCP servers
        for network in self.d_network:
            self.d_network[network].stopDHCPServer()
        self.logger.out('Releasing write lock for synchronization B', state='i')
        zkhandler.writedata(self.zk_conn, {'/locks/primary_node': ''})
        lock.release()
        self.logger.out('Released write lock for synchronization B', state='o')
        # 3. Stop client API
        if self.config['enable_api']:
            self.logger.out('Stopping PVC API client service', state='i')
            common.run_os_command("systemctl stop pvcapid.service")
        # 4. Stop metadata API
        self.metadata_api.stop()
        time.sleep(0.1) # Time for new writer to acquire the lock

        # Synchronize nodes C (I am reader)
        lock = zkhandler.readlock(self.zk_conn, '/locks/primary_node')
        self.logger.out('Acquiring read lock for synchronization C', state='i')
        lock.acquire()
        self.logger.out('Acquired read lock for synchronization C', state='o')
        # 5. Remove Upstream floating IP
        self.logger.out(
            'Removing floating upstream IP {}/{} from interface {}'.format(
                self.upstream_ipaddr,
                self.upstream_cidrnetmask,
                'brupstream'
            ),
            state='o'
        )
        common.removeIPAddress(self.upstream_ipaddr, self.upstream_cidrnetmask, 'brupstream')
        self.logger.out('Releasing read lock for synchronization C', state='i')
        lock.release()
        self.logger.out('Released read lock for synchronization C', state='o')

        # Synchronize nodes D (I am reader)
        lock = zkhandler.readlock(self.zk_conn, '/locks/primary_node')
        self.logger.out('Acquiring read lock for synchronization D', state='i')
        lock.acquire()
        self.logger.out('Acquired read lock for synchronization D', state='o')
        # 6. Remove Cluster floating IP
        self.logger.out(
            'Removing floating management IP {}/{} from interface {}'.format(
                self.vni_ipaddr,
                self.vni_cidrnetmask,
                'brcluster'
            ),
            state='o'
        )
        common.removeIPAddress(self.vni_ipaddr, self.vni_cidrnetmask, 'brcluster')
        self.logger.out('Releasing read lock for synchronization D', state='i')
        lock.release()
        self.logger.out('Released read lock for synchronization D', state='o')

        # Synchronize nodes E (I am reader)
        lock = zkhandler.readlock(self.zk_conn, '/locks/primary_node')
        self.logger.out('Acquiring read lock for synchronization E', state='i')
        lock.acquire()
        self.logger.out('Acquired read lock for synchronization E', state='o')
        # 7. Remove Metadata link-local IP
        self.logger.out(
            'Removing Metadata link-local IP {}/{} from interface {}'.format(
                '169.254.169.254',
                '32',
                'lo'
            ),
            state='o'
        )
        common.removeIPAddress('169.254.169.254', '32', 'lo')
        self.logger.out('Releasing read lock for synchronization E', state='i')
        lock.release()
        self.logger.out('Released read lock for synchronization E', state='o')

        # Synchronize nodes F (I am reader)
        lock = zkhandler.readlock(self.zk_conn, '/locks/primary_node')
        self.logger.out('Acquiring read lock for synchronization F', state='i')
        lock.acquire()
        self.logger.out('Acquired read lock for synchronization F', state='o')
        # 8. Remove gateway IPs
        for network in self.d_network:
            self.d_network[network].removeGateways()
        self.logger.out('Releasing read lock for synchronization F', state='i')
        lock.release()
        self.logger.out('Released read lock for synchronization F', state='o')

        # Synchronize nodes G (I am reader)
        lock = zkhandler.readlock(self.zk_conn, '/locks/primary_node')
        self.logger.out('Acquiring read lock for synchronization G', state='i')
        try:
            lock.acquire(timeout=60) # Don't wait forever and completely block us
            self.logger.out('Acquired read lock for synchronization G', state='o')
        except:
            pass
        self.logger.out('Releasing read lock for synchronization G', state='i')
        lock.release()
        self.logger.out('Released read lock for synchronization G', state='o')

        self.logger.out('Node {} transitioned to secondary state'.format(self.name), state='o')

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
                while zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(dom_uuid)) in ['shutdown']:
                    time.sleep(0.1)

                continue

            self.logger.out('Migrating VM "{}" to node "{}"'.format(dom_uuid, target_node), state='i')
            zkhandler.writedata(self.zk_conn, {
                '/domains/{}/state'.format(dom_uuid): 'migrate',
                '/domains/{}/node'.format(dom_uuid): target_node,
                '/domains/{}/lastnode'.format(dom_uuid): current_node
            })

            # Wait for the VM to migrate so the next VM's free RAM count is accurate (they migrate in serial anyways)
            while zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(dom_uuid)) in ['migrate', 'unmigrate', 'shutdown']:
                time.sleep(0.1)

        zkhandler.writedata(self.zk_conn, { '/nodes/{}/runningdomains'.format(self.name): '' })
        zkhandler.writedata(self.zk_conn, { '/nodes/{}/domainstate'.format(self.name): 'flushed' })
        self.flush_thread = None
        self.flush_stopper = False
        return

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
            while zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(dom_uuid)) in ['migrate', 'unmigrate', 'shutdown']:
                time.sleep(0.1)

        zkhandler.writedata(self.zk_conn, { '/nodes/{}/domainstate'.format(self.name): 'ready' })
        self.flush_thread = None
        self.flush_stopper = False
        return
