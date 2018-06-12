#!/usr/bin/env python3

# VMInstance.py - Class implementing a PVC virtual machine and run by pvcd
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

import os, sys, uuid, socket, time, threading, libvirt, kazoo.client, ansiiprint

class VMInstance:
    # Initialization function
    def __init__(self, domuuid, zk, config, thishypervisor):
        # Passed-in variables on creation
        self.domuuid = domuuid
        self.zk = zk
        self.config = config
        self.thishypervisor = thishypervisor

        # These will all be set later
        self.hypervisor = None
        self.state = None
        self.instart = False
        self.instop = False
        self.inshutdown = False
        self.inmigrate = False
        self.inreceive = False
        self.ininit = True

        self.dom = self.lookupByUUID(self.domuuid)

        # Watch for changes to the state field in Zookeeper
        @zk.DataWatch('/domains/{}/state'.format(self.domuuid))
        def watch_state(data, stat, event=""):
            if self.ininit == False:
                self.manage_vm_state()

        # Watch for changes to the hypervisor field in Zookeeper
        @zk.DataWatch('/domains/{}/hypervisor'.format(self.domuuid))
        def watch_hypervisor(data, stat, event=""):
            if self.ininit == False:
                self.manage_vm_state()
            else:
                # This case handles the very first init at startup to avoid it happening twice
                self.ininit = False
                self.manage_vm_state()

    # Get data functions
    def getstate(self):
        return self.state

    def gethypervisor(self):
        return self.hypervisor

    # Start up the VM
    def start_vm(self, xmlconfig):
        ansiiprint.echo('Starting VM', '{}:'.format(self.domuuid), 'i')
        self.instart = True

        # Start up a new Libvirt connection
        libvirt_name = "qemu:///system"
        conn = libvirt.open(libvirt_name)
        if conn == None:
            ansiiprint.echo('Failed to open local libvirt connection', '{}:'.format(self.domuuid), 'e')
            self.instart = False
            return
    
        try:
            dom = conn.createXML(xmlconfig, 0)
            if not self.domuuid in self.thishypervisor.domain_list:
                self.thishypervisor.domain_list.append(self.domuuid)

            ansiiprint.echo('Successfully started VM', '{}:'.format(self.domuuid), 'o')
            self.dom = dom
        except libvirt.libvirtError as e:
            ansiiprint.echo('Failed to create VM', '{}:'.format(self.domuuid), 'e')
            self.zk.set('/domains/{}/state'.format(self.domuuid), 'stop'.encode('ascii'))
            self.dom = None

        conn.close()
        self.instart = False
   
    # Stop the VM forcibly without updating state
    def terminate_vm(self):
        ansiiprint.echo('Terminating VM', '{}:'.format(self.domuuid), 'i')
        self.instop = True
        try:
            self.dom.destroy()
        except AttributeError:
            ansiiprint.echo('Failed to terminate VM', '{}:'.format(self.domuuid), 'e')
        if self.domuuid in self.thishypervisor.domain_list:
            try:
                self.thishypervisor.domain_list.remove(self.domuuid)
            except ValueError:
                pass
        ansiiprint.echo('Successfully terminated VM', '{}:'.format(self.domuuid), 'o')
        self.instop = False

    # Stop the VM forcibly
    def stop_vm(self):
        ansiiprint.echo('Forcibly stopping VM', '{}:'.format(self.domuuid), 'i')
        self.instop = True
        try:
            self.dom.destroy()
        except AttributeError:
            ansiiprint.echo('Failed to stop VM', '{}:'.format(self.domuuid), 'e')
        if self.domuuid in self.thishypervisor.domain_list:
            try:
                self.thishypervisor.domain_list.remove(self.domuuid)
            except ValueError:
                pass

        self.zk.set('/domains/{}/state'.format(self.domuuid), 'stop'.encode('ascii'))
        ansiiprint.echo('Successfully stopped VM', '{}:'.format(self.domuuid), 'o')
        self.dom = None
        self.instop = False
    
    # Shutdown the VM gracefully
    def shutdown_vm(self):
        ansiiprint.echo('Gracefully stopping VM', '{}:'.format(self.domuuid), 'i')
        self.inshutdown = True
        self.dom.shutdown()
        try:
            tick = 0
            while self.dom.state()[0] == libvirt.VIR_DOMAIN_RUNNING and tick < 60:
                tick += 1
                time.sleep(0.5)

            if tick >= 60:
                ansiiprint.echo('Shutdown timeout expired', '{}:'.format(self.domuuid), 'e')
                self.stop_vm()
                self.inshutdown = False
                return
        except:
            pass

        if self.domuuid in self.thishypervisor.domain_list:
            try:
                self.thishypervisor.domain_list.remove(self.domuuid)
            except ValueError:
                pass

        self.zk.set('/domains/{}/state'.format(self.domuuid), 'stop'.encode('ascii'))
        ansiiprint.echo('Successfully shutdown VM', '{}:'.format(self.domuuid), 'o')
        self.dom = None
        self.inshutdown = False

    def live_migrate_vm(self, dest_hypervisor):
        try:
            dest_conn = libvirt.open('qemu+tcp://{}/system'.format(self.hypervisor))
            if dest_conn == None:
                raise
        except:
            ansiiprint.echo('Failed to open connection to qemu+tcp://{}/system; aborting migration.'.format(self.hypervisor), '{}:'.format(self.domuuid), 'e')
            return 1

        try:
            target_dom = self.dom.migrate(dest_conn, libvirt.VIR_MIGRATE_LIVE, None, None, 0)
            if target_dom == None:
                raise
            ansiiprint.echo('Successfully migrated VM', '{}:'.format(self.domuuid), 'o')

        except:
            dest_conn.close()
            return 1

        dest_conn.close()
        return 0

    # Migrate the VM to a target host
    def migrate_vm(self):
        self.inmigrate = True
        ansiiprint.echo('Migrating VM to hypervisor "{}"'.format(self.hypervisor), '{}:'.format(self.domuuid), 'i')
        migrate_ret = self.live_migrate_vm(self.hypervisor)
        if migrate_ret != 0:
            ansiiprint.echo('Could not live migrate VM; shutting down to migrate instead', '{}:'.format(self.domuuid), 'e')
            self.shutdown_vm()
            time.sleep(1)
            self.zk.set('/domains/{}/state'.format(self.domuuid), 'start'.encode('ascii'))
        else:
            try:
                self.thishypervisor.domain_list.remove(self.domuuid)
            except ValueError:
                pass
            time.sleep(1)
            self.zk.set('/domains/{}/state'.format(self.domuuid), 'start'.encode('ascii'))

        self.inmigrate = False

    # Receive the migration from another host (wait until VM is running)
    def receive_migrate(self):
        self.inreceive = True
        ansiiprint.echo('Receiving migration', '{}:'.format(self.domuuid), 'i')
        while True:
            self.state = self.zk.get('/domains/{}/state'.format(self.domuuid))[0].decode('ascii')
            self.dom = self.lookupByUUID(self.domuuid)

            if self.dom == None and self.state == 'migrate':
                continue

            if self.state != 'migrate':
                break

            try:
                if self.dom.state()[0] == libvirt.VIR_DOMAIN_RUNNING:
                    break
            except:
                continue

        if self.dom.state()[0] == libvirt.VIR_DOMAIN_RUNNING:
            if not self.domuuid in self.thishypervisor.domain_list:
                self.thishypervisor.domain_list.append(self.domuuid)
            ansiiprint.echo('Successfully received migrated VM', '{}:'.format(self.domuuid), 'o')
            self.zk.set('/domains/{}/state'.format(self.domuuid), 'start'.encode('ascii'))
        else:
            ansiiprint.echo('Failed to receive migrated VM', '{}:'.format(self.domuuid), 'e')
            self.zk.set('/domains/{}/state'.format(self.domuuid), 'start'.encode('ascii'))

        self.inreceive = False

    #
    # Main function to manage a VM (taking only self)
    #
    def manage_vm_state(self):
        # Get the current values from zookeeper
        self.state = self.zk.get('/domains/{}/state'.format(self.domuuid))[0].decode('ascii')
        self.hypervisor = self.zk.get('/domains/{}/hypervisor'.format(self.domuuid))[0].decode('ascii')

        # Check the current state of the VM
        try:
            if self.dom != None:
                running, reason = self.dom.state()
            else:
                raise
        except:
            running = libvirt.VIR_DOMAIN_NOSTATE

        ansiiprint.echo('VM state change for "{}": {} {}'.format(self.domuuid, self.state, self.hypervisor), '', 'i')

        # Conditional pass one - If we're already doing something, bail out
        if self.instart == True or self.instop == True or self.inshutdown == True or self.inmigrate == True or self.inreceive == True:
            return 0

        # VM should be stopped
        if running == libvirt.VIR_DOMAIN_RUNNING and self.state == "stop" and self.hypervisor == self.thishypervisor.name:
            self.stop_vm()

        # VM should be shut down
        elif running == libvirt.VIR_DOMAIN_RUNNING and self.state == "shutdown" and self.hypervisor == self.thishypervisor.name:
            self.shutdown_vm()

        # VM should be migrated to this hypervisor
        elif running != libvirt.VIR_DOMAIN_RUNNING and self.state == "migrate" and self.hypervisor == self.thishypervisor.name:
            self.receive_migrate()

        # VM should be migrated away from this hypervisor
        elif running == libvirt.VIR_DOMAIN_RUNNING and self.state == "migrate" and self.hypervisor != self.thishypervisor.name:
            self.migrate_vm()
            
        # VM should be running but not on this hypervisor
        elif running == libvirt.VIR_DOMAIN_RUNNING and self.state == "start" and self.hypervisor != self.thishypervisor.name:
            self.terminate_vm()

        # VM is already running and should be
        elif running == libvirt.VIR_DOMAIN_RUNNING and self.state == "start" and self.hypervisor == self.thishypervisor.name:
            if not self.domuuid in self.thishypervisor.domain_list:
                self.thishypervisor.domain_list.append(self.domuuid)
    
        # VM is already running and should be but stuck in migrate state
        elif running == libvirt.VIR_DOMAIN_RUNNING and self.state == "migrate" and self.hypervisor == self.thishypervisor.name:
            self.zk.set('/domains/{}/state'.format(self.domuuid), 'start'.encode('ascii'))
            if not self.domuuid in self.thishypervisor.domain_list:
                self.thishypervisor.domain_list.append(self.domuuid)
    
        # VM should be started
        elif running != libvirt.VIR_DOMAIN_RUNNING and self.state == "start" and self.hypervisor == self.thishypervisor.name:
            # Grab the domain information from Zookeeper
            domxml, domxmlstat = self.zk.get('/domains/{}/xml'.format(self.domuuid))
            domxml = str(domxml.decode('ascii'))
            self.start_vm(domxml)

    # This function is a wrapper for libvirt.lookupByUUID which fixes some problems
    # 1. Takes a text UUID and handles converting it to bytes
    # 2. Try's it and returns a sensible value if not
    def lookupByUUID(self, tuuid):
        conn = None
        dom = None
        libvirt_name = "qemu:///system"
    
        # Convert the text UUID to bytes
        buuid = uuid.UUID(tuuid).bytes
    
        # Try
        try:
            # Open a libvirt connection
            conn = libvirt.open(libvirt_name)
            if conn == None:
                ansiiprint.echo('Failed to open local libvirt connection', '{}:'.format(self.domuuid), 'e')
                return dom
        
            # Lookup the UUID
            dom = conn.lookupByUUID(buuid)
    
        # Fail
        except:
            pass
    
        # After everything
        finally:
            # Close the libvirt connection
            if conn != None:
                conn.close()
    
        # Return the dom object (or None)
        return dom
