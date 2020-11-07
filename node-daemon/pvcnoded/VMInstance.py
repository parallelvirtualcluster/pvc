#!/usr/bin/env python3

# VMInstance.py - Class implementing a PVC virtual machine in pvcnoded
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

import uuid
import time
import libvirt
import json

from threading import Thread

import pvcnoded.zkhandler as zkhandler
import pvcnoded.common as common

import pvcnoded.VMConsoleWatcherInstance as VMConsoleWatcherInstance

import daemon_lib.common as daemon_common

def flush_locks(zk_conn, logger, dom_uuid):
    logger.out('Flushing RBD locks for VM "{}"'.format(dom_uuid), state='i')
    # Get the list of RBD images
    rbd_list = zkhandler.readdata(zk_conn, '/domains/{}/rbdlist'.format(dom_uuid)).split(',')
    for rbd in rbd_list:
        # Check if a lock exists
        lock_list_retcode, lock_list_stdout, lock_list_stderr = common.run_os_command('rbd lock list --format json {}'.format(rbd))
        if lock_list_retcode != 0:
            logger.out('Failed to obtain lock list for volume "{}"'.format(rbd), state='e')
            continue

        try:
            lock_list = json.loads(lock_list_stdout)
        except Exception as e:
            logger.out('Failed to parse lock list for volume "{}": {}'.format(rbd, e), state='e')
            continue

        # If there's at least one lock
        if lock_list:
            # Loop through the locks
            for lock in lock_list:
                # Free the lock
                lock_remove_retcode, lock_remove_stdout, lock_remove_stderr = common.run_os_command('rbd lock remove {} "{}" "{}"'.format(rbd, lock['id'], lock['locker']))
                if lock_remove_retcode != 0:
                    logger.out('Failed to free RBD lock "{}" on volume "{}"\n{}'.format(lock['id'], rbd, lock_remove_stderr), state='e')
                    continue
                logger.out('Freed RBD lock "{}" on volume "{}"'.format(lock['id'], rbd), state='o')

    return True

# Primary command function
def run_command(zk_conn, logger, this_node, data):
    # Get the command and args
    command, args = data.split()

    # Flushing VM RBD locks
    if command == 'flush_locks':
        dom_uuid = args
        # If this node is taking over primary state, wait until it's done
        while this_node.router_state == 'takeover':
            time.sleep(1)
        if this_node.router_state == 'primary':
            # Lock the command queue
            zk_lock = zkhandler.writelock(zk_conn, '/cmd/domains')
            with zk_lock:
                # Add the OSD
                result = flush_locks(zk_conn, logger, dom_uuid)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/cmd/domains': 'success-{}'.format(data)})
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/cmd/domains': 'failure-{}'.format(data)})
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

class VMInstance(object):
    # Initialization function
    def __init__(self, domuuid, zk_conn, config, logger, this_node):
        # Passed-in variables on creation
        self.domuuid = domuuid
        self.zk_conn = zk_conn
        self.config = config
        self.logger = logger
        self.this_node = this_node

        # Get data from zookeeper
        self.domname = zkhandler.readdata(zk_conn, '/domains/{}'.format(domuuid))
        self.state = zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(self.domuuid))
        self.node = zkhandler.readdata(self.zk_conn, '/domains/{}/node'.format(self.domuuid))
        self.lastnode = zkhandler.readdata(self.zk_conn, '/domains/{}/lastnode'.format(self.domuuid))
        self.last_currentnode = zkhandler.readdata(self.zk_conn, '/domains/{}/node'.format(self.domuuid))
        self.last_lastnode = zkhandler.readdata(self.zk_conn, '/domains/{}/lastnode'.format(self.domuuid))
        try:
            self.pinpolicy = zkhandler.readdata(self.zk_conn, '/domains/{}/pinpolicy'.format(self.domuuid))
        except Exception:
            self.pinpolicy = "none"
        try:
            self.migration_method = zkhandler.readdata(self.zk_conn, '/domains/{}/migration_method'.format(self.domuuid))
        except Exception:
            self.migration_method = 'none'

        # These will all be set later
        self.instart = False
        self.inrestart = False
        self.inmigrate = False
        self.inreceive = False
        self.inshutdown = False
        self.instop = False

        # Libvirt domuuid
        self.dom = self.lookupByUUID(self.domuuid)

        # Log watcher instance
        self.console_log_instance = VMConsoleWatcherInstance.VMConsoleWatcherInstance(self.domuuid, self.domname, self.zk_conn, self.config, self.logger, self.this_node)

        # Watch for changes to the state field in Zookeeper
        @self.zk_conn.DataWatch('/domains/{}/state'.format(self.domuuid))
        def watch_state(data, stat, event=""):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            # Perform a management command
            self.logger.out('Updating state of VM {}'.format(self.domuuid), state='i')
            state_thread = Thread(target=self.manage_vm_state, args=(), kwargs={})
            state_thread.start()

    # Get data functions
    def getstate(self):
        return self.state

    def getnode(self):
        return self.node

    def getlastnode(self):
        return self.lastnode

    def getdom(self):
        return self.dom

    def getmemory(self):
        try:
            if self.dom is not None:
                memory = int(self.dom.info()[2] / 1024)
            else:
                domain_information = daemon_common.getInformationFromXML(self.zk_conn, self.domuuid)
                memory = int(domain_information['memory'])
        except Exception:
            memory = 0

        return memory

    def getvcpus(self):
        try:
            vcpus = int(self.dom.info()[3])
        except Exception:
            vcpus = 0

        return vcpus

    # Manage local node domain_list
    def addDomainToList(self):
        if self.domuuid not in self.this_node.domain_list:
            try:
                # Add the domain to the domain_list array
                self.this_node.domain_list.append(self.domuuid)
                # Push the change up to Zookeeper
                zkhandler.writedata(self.zk_conn, {'/nodes/{}/runningdomains'.format(self.this_node.name): ' '.join(self.this_node.domain_list)})
            except Exception as e:
                self.logger.out('Error adding domain to list: {}'.format(e), state='e')

    def removeDomainFromList(self):
        if self.domuuid in self.this_node.domain_list:
            try:
                # Remove the domain from the domain_list array
                self.this_node.domain_list.remove(self.domuuid)
                # Push the change up to Zookeeper
                zkhandler.writedata(self.zk_conn, {'/nodes/{}/runningdomains'.format(self.this_node.name): ' '.join(self.this_node.domain_list)})
            except Exception as e:
                self.logger.out('Error removing domain from list: {}'.format(e), state='e')

    # Start up the VM
    def start_vm(self):
        # Start the log watcher
        self.console_log_instance.start()

        self.logger.out('Starting VM', state='i', prefix='Domain {}'.format(self.domuuid))
        self.instart = True

        # Start up a new Libvirt connection
        libvirt_name = "qemu:///system"
        lv_conn = libvirt.open(libvirt_name)
        if lv_conn is None:
            self.logger.out('Failed to open local libvirt connection', state='e', prefix='Domain {}'.format(self.domuuid))
            self.instart = False
            return

        # Try to get the current state in case it's already running
        try:
            self.dom = self.lookupByUUID(self.domuuid)
            curstate = self.dom.state()[0]
        except Exception:
            curstate = 'notstart'

        if curstate == libvirt.VIR_DOMAIN_RUNNING:
            # If it is running just update the model
            self.addDomainToList()
            zkhandler.writedata(self.zk_conn, {'/domains/{}/failedreason'.format(self.domuuid): ''})
        else:
            # Or try to create it
            try:
                # Grab the domain information from Zookeeper
                xmlconfig = zkhandler.readdata(self.zk_conn, '/domains/{}/xml'.format(self.domuuid))
                dom = lv_conn.createXML(xmlconfig, 0)
                self.addDomainToList()
                self.logger.out('Successfully started VM', state='o', prefix='Domain {}'.format(self.domuuid))
                self.dom = dom
                zkhandler.writedata(self.zk_conn, {'/domains/{}/failedreason'.format(self.domuuid): ''})
            except libvirt.libvirtError as e:
                self.logger.out('Failed to create VM', state='e', prefix='Domain {}'.format(self.domuuid))
                zkhandler.writedata(self.zk_conn, {'/domains/{}/state'.format(self.domuuid): 'fail'})
                zkhandler.writedata(self.zk_conn, {'/domains/{}/failedreason'.format(self.domuuid): str(e)})
                self.dom = None

        lv_conn.close()

        self.instart = False

    # Restart the VM
    def restart_vm(self):
        self.logger.out('Restarting VM', state='i', prefix='Domain {}'.format(self.domuuid))
        self.inrestart = True

        # Start up a new Libvirt connection
        libvirt_name = "qemu:///system"
        lv_conn = libvirt.open(libvirt_name)
        if lv_conn is None:
            self.logger.out('Failed to open local libvirt connection', state='e', prefix='Domain {}'.format(self.domuuid))
            self.inrestart = False
            return

        self.shutdown_vm()
        time.sleep(0.2)
        self.start_vm()
        self.addDomainToList()

        zkhandler.writedata(self.zk_conn, {'/domains/{}/state'.format(self.domuuid): 'start'})
        lv_conn.close()
        self.inrestart = False

    # Stop the VM forcibly without updating state
    def terminate_vm(self):
        self.logger.out('Terminating VM', state='i', prefix='Domain {}'.format(self.domuuid))
        self.instop = True
        try:
            self.dom.destroy()
        except AttributeError:
            self.logger.out('Failed to terminate VM', state='e', prefix='Domain {}'.format(self.domuuid))
        self.removeDomainFromList()
        self.logger.out('Successfully terminated VM', state='o', prefix='Domain {}'.format(self.domuuid))
        self.dom = None
        self.instop = False

        # Stop the log watcher
        self.console_log_instance.stop()

    # Stop the VM forcibly
    def stop_vm(self):
        self.logger.out('Forcibly stopping VM', state='i', prefix='Domain {}'.format(self.domuuid))
        self.instop = True
        try:
            self.dom.destroy()
        except AttributeError:
            self.logger.out('Failed to stop VM', state='e', prefix='Domain {}'.format(self.domuuid))
        self.removeDomainFromList()

        if self.inrestart is False:
            zkhandler.writedata(self.zk_conn, {'/domains/{}/state'.format(self.domuuid): 'stop'})

        self.logger.out('Successfully stopped VM', state='o', prefix='Domain {}'.format(self.domuuid))
        self.dom = None
        self.instop = False

        # Stop the log watcher
        self.console_log_instance.stop()

    # Shutdown the VM gracefully
    def shutdown_vm(self):
        self.logger.out('Gracefully stopping VM', state='i', prefix='Domain {}'.format(self.domuuid))
        is_aborted = False
        self.inshutdown = True
        self.dom.shutdown()
        tick = 0
        while True:
            tick += 1
            time.sleep(1)

            # Abort shutdown if the state changes to start
            current_state = zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(self.domuuid))
            if current_state not in ['shutdown', 'restart']:
                self.logger.out('Aborting VM shutdown due to state change', state='i', prefix='Domain {}'.format(self.domuuid))
                is_aborted = True
                break

            try:
                lvdomstate = self.dom.state()[0]
            except Exception:
                lvdomstate = None

            if lvdomstate != libvirt.VIR_DOMAIN_RUNNING:
                self.removeDomainFromList()
                zkhandler.writedata(self.zk_conn, {'/domains/{}/state'.format(self.domuuid): 'stop'})
                self.logger.out('Successfully shutdown VM', state='o', prefix='Domain {}'.format(self.domuuid))
                self.dom = None
                # Stop the log watcher
                self.console_log_instance.stop()
                break

            if tick >= self.config['vm_shutdown_timeout']:
                self.logger.out('Shutdown timeout ({}s) expired, forcing off'.format(self.config['vm_shutdown_timeout']), state='e', prefix='Domain {}'.format(self.domuuid))
                zkhandler.writedata(self.zk_conn, {'/domains/{}/state'.format(self.domuuid): 'stop'})
                break

        self.inshutdown = False

        if is_aborted:
            self.manage_vm_state()

        if self.inrestart:
            # Wait to prevent race conditions
            time.sleep(1)
            zkhandler.writedata(self.zk_conn, {'/domains/{}/state'.format(self.domuuid): 'start'})

    # Migrate the VM to a target host
    def migrate_vm(self, force_live=False, force_shutdown=False):
        # Wait for any previous migration
        while self.inmigrate:
            time.sleep(0.1)

        if self.migration_method == 'live':
            force_live = True
        elif self.migration_method == 'shutdown':
            force_shutdown = True

        self.inmigrate = True
        self.logger.out('Migrating VM to node "{}"'.format(self.node), state='i', prefix='Domain {}'.format(self.domuuid))

        # Used for sanity checking later
        target_node = zkhandler.readdata(self.zk_conn, '/domains/{}/node'.format(self.domuuid))

        aborted = False

        def abort_migrate(reason):
            zkhandler.writedata(self.zk_conn, {
                '/domains/{}/state'.format(self.domuuid): 'start',
                '/domains/{}/node'.format(self.domuuid): self.this_node.name,
                '/domains/{}/lastnode'.format(self.domuuid): self.last_lastnode
            })
            migrate_lock_node.release()
            migrate_lock_state.release()
            self.logger.out('Aborted migration: {}'.format(reason), state='i', prefix='Domain {}'.format(self.domuuid))

        # Acquire exclusive lock on the domain node key
        migrate_lock_node = zkhandler.exclusivelock(self.zk_conn, '/domains/{}/node'.format(self.domuuid))
        migrate_lock_state = zkhandler.exclusivelock(self.zk_conn, '/domains/{}/state'.format(self.domuuid))
        migrate_lock_node.acquire()
        migrate_lock_state.acquire()

        time.sleep(0.2) # Initial delay for the first writer to grab the lock

        # Don't try to migrate a node to itself, set back to start
        if self.node == self.lastnode or self.node == self.this_node.name:
            abort_migrate('Target node matches the current active node during initial check')
            return

        # Synchronize nodes A (I am reader)
        lock = zkhandler.readlock(self.zk_conn, '/locks/domain_migrate/{}'.format(self.domuuid))
        self.logger.out('Acquiring read lock for synchronization phase A', state='i', prefix='Domain {}'.format(self.domuuid))
        lock.acquire()
        self.logger.out('Acquired read lock for synchronization phase A', state='o', prefix='Domain {}'.format(self.domuuid))
        if zkhandler.readdata(self.zk_conn, '/locks/domain_migrate/{}'.format(self.domuuid)) == '':
            self.logger.out('Waiting for peer', state='i', prefix='Domain {}'.format(self.domuuid))
            ticks = 0
            while zkhandler.readdata(self.zk_conn, '/locks/domain_migrate/{}'.format(self.domuuid)) == '':
                time.sleep(0.1)
                ticks += 1
                if ticks > 300:
                    self.logger.out('Timed out waiting 30s for peer', state='e', prefix='Domain {}'.format(self.domuuid))
                    aborted = True
                    break
        self.logger.out('Releasing read lock for synchronization phase A', state='i', prefix='Domain {}'.format(self.domuuid))
        lock.release()
        self.logger.out('Released read lock for synchronization phase A', state='o', prefix='Domain {}'.format(self.domuuid))

        if aborted:
            abort_migrate('Timed out waiting for peer')
            return

        # Synchronize nodes B (I am writer)
        lock = zkhandler.writelock(self.zk_conn, '/locks/domain_migrate/{}'.format(self.domuuid))
        self.logger.out('Acquiring write lock for synchronization phase B', state='i', prefix='Domain {}'.format(self.domuuid))
        lock.acquire()
        self.logger.out('Acquired write lock for synchronization phase B', state='o', prefix='Domain {}'.format(self.domuuid))
        time.sleep(0.5) # Time for reader to acquire the lock

        def migrate_live():
            self.logger.out('Setting up live migration', state='i', prefix='Domain {}'.format(self.domuuid))
            # Set up destination connection
            dest_lv = 'qemu+tcp://{}.{}/system'.format(self.node, self.config['cluster_domain'])
            dest_tcp = 'tcp://{}.{}'.format(self.node, self.config['cluster_domain'])
            try:
                self.logger.out('Opening remote libvirt connection', state='i', prefix='Domain {}'.format(self.domuuid))
                # Open a connection to the destination
                dest_lv_conn = libvirt.open(dest_lv)
                if not dest_lv_conn:
                    raise
            except Exception:
                self.logger.out('Failed to open connection to {}; aborting live migration.'.format(dest_lv), state='e', prefix='Domain {}'.format(self.domuuid))
                return False

            try:
                self.logger.out('Live migrating VM', state='i', prefix='Domain {}'.format(self.domuuid))
                # Send the live migration; force the destination URI to ensure we transit over the cluster network
                target_dom = self.dom.migrate(dest_lv_conn, libvirt.VIR_MIGRATE_LIVE, None, dest_tcp, 0)
                if not target_dom:
                    raise
            except Exception as e:
                self.logger.out('Failed to send VM to {} - aborting live migration; error: {}'.format(dest_lv, e), state='e', prefix='Domain {}'.format(self.domuuid))
                dest_lv_conn.close()
                return False

            self.logger.out('Successfully migrated VM', state='o', prefix='Domain {}'.format(self.domuuid))
            dest_lv_conn.close()
            self.console_log_instance.stop()
            self.removeDomainFromList()

            return True

        def migrate_shutdown():
            self.logger.out('Shutting down VM for offline migration', state='i', prefix='Domain {}'.format(self.domuuid))
            zkhandler.writedata(self.zk_conn, {'/domains/{}/state'.format(self.domuuid): 'shutdown'})
            while zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(self.domuuid)) != 'stop':
                time.sleep(0.5)
            return True

        do_migrate_shutdown = False
        migrate_live_result = False

        # Do a final verification
        if self.node == self.lastnode or self.node == self.this_node.name:
            abort_migrate('Target node matches the current active node during final check')
            return
        if self.node != target_node:
            abort_migrate('Target node changed during preparation')
            return

        if not force_shutdown:
            # A live migrate is attemped 3 times in succession
            ticks = 0
            while True:
                ticks += 1
                self.logger.out('Attempting live migration try {}'.format(ticks), state='i', prefix='Domain {}'.format(self.domuuid))
                migrate_live_result = migrate_live()
                if migrate_live_result:
                    break
                time.sleep(0.5)
                if ticks > 2:
                    break
        else:
            migrate_live_result = False

        if not migrate_live_result:
            if force_live:
                self.logger.out('Could not live migrate VM while live migration enforced', state='e', prefix='Domain {}'.format(self.domuuid))
                aborted = True
            else:
                do_migrate_shutdown = True

        self.logger.out('Releasing write lock for synchronization phase B', state='i', prefix='Domain {}'.format(self.domuuid))
        lock.release()
        self.logger.out('Released write lock for synchronization phase B', state='o', prefix='Domain {}'.format(self.domuuid))

        if aborted:
            abort_migrate('Live migration failed and is required')
            return

        # Synchronize nodes C (I am writer)
        lock = zkhandler.writelock(self.zk_conn, '/locks/domain_migrate/{}'.format(self.domuuid))
        self.logger.out('Acquiring write lock for synchronization phase C', state='i', prefix='Domain {}'.format(self.domuuid))
        lock.acquire()
        self.logger.out('Acquired write lock for synchronization phase C', state='o', prefix='Domain {}'.format(self.domuuid))
        time.sleep(0.5) # Time for reader to acquire the lock

        if do_migrate_shutdown:
            migrate_shutdown()

        self.logger.out('Releasing write lock for synchronization phase C', state='i', prefix='Domain {}'.format(self.domuuid))
        lock.release()
        self.logger.out('Released write lock for synchronization phase C', state='o', prefix='Domain {}'.format(self.domuuid))

        # Synchronize nodes D (I am reader)
        lock = zkhandler.readlock(self.zk_conn, '/locks/domain_migrate/{}'.format(self.domuuid))
        self.logger.out('Acquiring read lock for synchronization phase D', state='i', prefix='Domain {}'.format(self.domuuid))
        lock.acquire()
        self.logger.out('Acquired read lock for synchronization phase D', state='o', prefix='Domain {}'.format(self.domuuid))

        self.last_currentnode = zkhandler.readdata(self.zk_conn, '/domains/{}/node'.format(self.domuuid))
        self.last_lastnode = zkhandler.readdata(self.zk_conn, '/domains/{}/lastnode'.format(self.domuuid))

        self.logger.out('Releasing read lock for synchronization phase D', state='i', prefix='Domain {}'.format(self.domuuid))
        lock.release()
        self.logger.out('Released read lock for synchronization phase D', state='o', prefix='Domain {}'.format(self.domuuid))

        # Wait for the receive side to complete before we declare all-done and release locks
        while zkhandler.readdata(self.zk_conn, '/locks/domain_migrate/{}'.format(self.domuuid)) != '':
            time.sleep(0.5)
        migrate_lock_node.release()
        migrate_lock_state.release()

        self.inmigrate = False
        return

    # Receive the migration from another host
    def receive_migrate(self):
        # Wait for any previous migration
        while self.inreceive:
            time.sleep(0.1)

        self.inreceive = True

        self.logger.out('Receiving VM migration from node "{}"'.format(self.node), state='i', prefix='Domain {}'.format(self.domuuid))

        # Ensure our lock key is populated
        zkhandler.writedata(self.zk_conn, {'/locks/domain_migrate/{}'.format(self.domuuid): self.domuuid})

        # Synchronize nodes A (I am writer)
        lock = zkhandler.writelock(self.zk_conn, '/locks/domain_migrate/{}'.format(self.domuuid))
        self.logger.out('Acquiring write lock for synchronization phase A', state='i', prefix='Domain {}'.format(self.domuuid))
        lock.acquire()
        self.logger.out('Acquired write lock for synchronization phase A', state='o', prefix='Domain {}'.format(self.domuuid))
        time.sleep(0.5) # Time for reader to acquire the lock
        self.logger.out('Releasing write lock for synchronization phase A', state='i', prefix='Domain {}'.format(self.domuuid))
        lock.release()
        self.logger.out('Released write lock for synchronization phase A', state='o', prefix='Domain {}'.format(self.domuuid))
        time.sleep(0.1) # Time for new writer to acquire the lock

        # Synchronize nodes B (I am reader)
        lock = zkhandler.readlock(self.zk_conn, '/locks/domain_migrate/{}'.format(self.domuuid))
        self.logger.out('Acquiring read lock for synchronization phase B', state='i', prefix='Domain {}'.format(self.domuuid))
        lock.acquire()
        self.logger.out('Acquired read lock for synchronization phase B', state='o', prefix='Domain {}'.format(self.domuuid))
        self.logger.out('Releasing read lock for synchronization phase B', state='i', prefix='Domain {}'.format(self.domuuid))
        lock.release()
        self.logger.out('Released read lock for synchronization phase B', state='o', prefix='Domain {}'.format(self.domuuid))

        # Synchronize nodes C (I am reader)
        lock = zkhandler.readlock(self.zk_conn, '/locks/domain_migrate/{}'.format(self.domuuid))
        self.logger.out('Acquiring read lock for synchronization phase C', state='i', prefix='Domain {}'.format(self.domuuid))
        lock.acquire()
        self.logger.out('Acquired read lock for synchronization phase C', state='o', prefix='Domain {}'.format(self.domuuid))

        # Set the updated data
        self.last_currentnode = zkhandler.readdata(self.zk_conn, '/domains/{}/node'.format(self.domuuid))
        self.last_lastnode = zkhandler.readdata(self.zk_conn, '/domains/{}/lastnode'.format(self.domuuid))

        self.logger.out('Releasing read lock for synchronization phase C', state='i', prefix='Domain {}'.format(self.domuuid))
        lock.release()
        self.logger.out('Released read lock for synchronization phase C', state='o', prefix='Domain {}'.format(self.domuuid))

        # Synchronize nodes D (I am writer)
        lock = zkhandler.writelock(self.zk_conn, '/locks/domain_migrate/{}'.format(self.domuuid))
        self.logger.out('Acquiring write lock for synchronization phase D', state='i', prefix='Domain {}'.format(self.domuuid))
        lock.acquire()
        self.logger.out('Acquired write lock for synchronization phase D', state='o', prefix='Domain {}'.format(self.domuuid))
        time.sleep(0.5) # Time for reader to acquire the lock

        self.state = zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(self.domuuid))
        self.dom = self.lookupByUUID(self.domuuid)
        if self.dom:
            lvdomstate = self.dom.state()[0]
            if lvdomstate == libvirt.VIR_DOMAIN_RUNNING:
                # VM has been received and started
                self.addDomainToList()
                zkhandler.writedata(self.zk_conn, {'/domains/{}/state'.format(self.domuuid): 'start'})
                self.logger.out('Successfully received migrated VM', state='o', prefix='Domain {}'.format(self.domuuid))
            else:
                # The receive somehow failed
                zkhandler.writedata(self.zk_conn, {'/domains/{}/state'.format(self.domuuid): 'fail'})
        else:
            if self.node == self.this_node.name:
                if self.state in ['start']:
                    # The receive was aborted
                    self.logger.out('Receive aborted via state change', state='w', prefix='Domain {}'.format(self.domuuid))
                elif self.state in ['stop']:
                    # The send was shutdown-based
                    zkhandler.writedata(self.zk_conn, {'/domains/{}/state'.format(self.domuuid): 'start'})
                else:
                    # The send failed or was aborted
                    self.logger.out('Migrate aborted or failed; VM in state {}'.format(self.state), state='w', prefix='Domain {}'.format(self.domuuid))

        self.logger.out('Releasing write lock for synchronization phase D', state='i', prefix='Domain {}'.format(self.domuuid))
        lock.release()
        self.logger.out('Released write lock for synchronization phase D', state='o', prefix='Domain {}'.format(self.domuuid))

        zkhandler.writedata(self.zk_conn, {'/locks/domain_migrate/{}'.format(self.domuuid): ''})
        self.inreceive = False
        return

    #
    # Main function to manage a VM (taking only self)
    #
    def manage_vm_state(self):
        # Update the current values from zookeeper
        self.state = zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(self.domuuid))
        self.node = zkhandler.readdata(self.zk_conn, '/domains/{}/node'.format(self.domuuid))
        self.lastnode = zkhandler.readdata(self.zk_conn, '/domains/{}/lastnode'.format(self.domuuid))

        # Check the current state of the VM
        try:
            if self.dom is not None:
                running, reason = self.dom.state()
            else:
                raise
        except Exception:
            running = libvirt.VIR_DOMAIN_NOSTATE

        self.logger.out('VM state change for "{}": {} {}'.format(self.domuuid, self.state, self.node), state='i')

        #######################
        # Handle state changes
        #######################
        # Valid states are:
        #   start
        #   migrate
        #   migrate-live
        #   restart
        #   shutdown
        #   stop
        # States we don't (need to) handle are:
        #   disable
        #   provision

        # Conditional pass one - Are we already performing an action
        if self.instart is False \
        and self.inrestart is False \
        and self.inmigrate is False \
        and self.inreceive is False \
        and self.inshutdown is False \
        and self.instop is False:
            # Conditional pass two - Is this VM configured to run on this node
            if self.node == self.this_node.name:
                # Conditional pass three - Is this VM currently running on this node
                if running == libvirt.VIR_DOMAIN_RUNNING:
                    # VM is already running and should be
                    if self.state == "start":
                        # Start the log watcher
                        self.console_log_instance.start()
                        # Add domain to running list
                        self.addDomainToList()
                    # VM is already running and should be but stuck in migrate state
                    elif self.state == "migrate" or self.state == "migrate-live":
                        # Start the log watcher
                        self.console_log_instance.start()
                        zkhandler.writedata(self.zk_conn, {'/domains/{}/state'.format(self.domuuid): 'start'})
                        # Add domain to running list
                        self.addDomainToList()
                    # VM should be restarted
                    elif self.state == "restart":
                        self.restart_vm()
                    # VM should be shut down
                    elif self.state == "shutdown":
                        self.shutdown_vm()
                    # VM should be stopped
                    elif self.state == "stop":
                        self.stop_vm()
                else:
                    # VM should be started
                    if self.state == "start":
                        # Start the domain
                        self.start_vm()
                    # VM should be migrated to this node
                    elif self.state == "migrate" or self.state == "migrate-live":
                        # Receive the migration
                        self.receive_migrate()
                    # VM should be restarted (i.e. started since it isn't running)
                    if self.state == "restart":
                        zkhandler.writedata(self.zk_conn, {'/domains/{}/state'.format(self.domuuid): 'start'})
                    # VM should be shut down; ensure it's gone from this node's domain_list
                    elif self.state == "shutdown":
                        self.removeDomainFromList()
                        # Stop the log watcher
                        self.console_log_instance.stop()
                    # VM should be stoped; ensure it's gone from this node's domain_list
                    elif self.state == "stop":
                        self.removeDomainFromList()
                        # Stop the log watcher
                        self.console_log_instance.stop()

            else:
                # Conditional pass three - Is this VM currently running on this node
                if running == libvirt.VIR_DOMAIN_RUNNING:
                    # VM should be migrated away from this node
                    if self.state == "migrate":
                        self.migrate_vm(force_live=False)
                    # VM should be migrated away from this node, live only (no shutdown fallback)
                    elif self.state == "migrate-live":
                        self.migrate_vm(force_live=True)
                    # VM should be shutdown gracefully
                    elif self.state == 'shutdown':
                        self.shutdown_vm()
                    # VM should be forcibly terminated
                    else:
                        self.terminate_vm()

    # This function is a wrapper for libvirt.lookupByUUID which fixes some problems
    # 1. Takes a text UUID and handles converting it to bytes
    # 2. Try's it and returns a sensible value if not
    def lookupByUUID(self, tuuid):
        # Don't do anything if the VM shouldn't live on this node
        if self.node != self.this_node.name:
            return None

        lv_conn = None
        libvirt_name = "qemu:///system"

        # Convert the text UUID to bytes
        buuid = uuid.UUID(tuuid).bytes

        # Try
        try:
            # Open a libvirt connection
            lv_conn = libvirt.open(libvirt_name)
            if lv_conn is None:
                self.logger.out('Failed to open local libvirt connection', state='e', prefix='Domain {}'.format(self.domuuid))
                return None

            # Lookup the UUID
            dom = lv_conn.lookupByUUID(buuid)

        # Fail
        except Exception:
            dom = None

        # After everything
        finally:
            # Close the libvirt connection
            if lv_conn is not None:
                lv_conn.close()

        # Return the dom object (or None)
        return dom
