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

import os, sys, socket, time, threading, libvirt, kazoo.client

class VMInstance:
    def __init__(self, domuuid, zk, thishypervisor):
        # Passed-in variables on creation
        self.domuuid = domuuid
        self.zkey = '/domains/%s' % domuuid
        self.zk = zk
        self.thishypervisor = thishypervisor

        # These will all be set later
        self.hypervisor = None
        self.state = None
        self.instart = False
        self.instop = False
        self.inshutdown = False
        self.inmigrate = False
        self.inreceive = False

        self.dom = lookupByUUID(self.domuuid)

        # Watch for changes to the hypervisor field in Zookeeper
        @zk.DataWatch(self.zkey + '/hypervisor')
        def watch_hypervisor(data, stat, event=""):
            self.hypervisor = data.decode('ascii')
            self.manage_vm_state()

        # Watch for changes to the state field in Zookeeper
        @zk.DataWatch(self.zkey + '/state')
        def watch_state(data, stat, event=""):
            self.state = data.decode('ascii')
            self.manage_vm_state()

    # Get data functions
    def getstate(self):
        return self.state

    def gethypervisor(self):
        return self.hypervisor

    # Start up the VM
    def start_vm(self, xmlconfig):
        print(">>> %s - Starting VM" % self.domuuid)
        self.instart = True

        # Start up a new Libvirt connection
        libvirt_name = "qemu:///system"
        conn = libvirt.open(libvirt_name)
        if conn == None:
            print('>>> %s - Failed to open local libvirt connection.' % self.domuuid)
            self.instart = False
            return
    
        try:
            dom = conn.createXML(xmlconfig, 0)
        except libvirt.libvirtError as e:
            print('>>> %s - Failed to create VM' % self.domuuid)
            self.zk.set(self.zkey + '/state', 'stop'.encode('ascii'))

        if not self.domuuid in self.thishypervisor.domain_list:
            self.thishypervisor.domain_list.append(self.domuuid)

        conn.close()
        self.dom = dom
        self.instart = False
   
    # Stop the VM forcibly
    def stop_vm(self):
        print(">>> %s - Forcibly stopping VM" % self.domuuid)
        self.instop = True
        self.dom.destroy()
        if self.domuuid in self.thishypervisor.domain_list:
            try:
                self.thishypervisor.domain_list.remove(self.domuuid)
            except ValueError:
                pass

        self.zk.set(self.zkey + '/state', 'stop'.encode('ascii'))
        self.dom = None
        self.instop = False
    
    # Shutdown the VM gracefully
    def shutdown_vm(self):
        print(">>> %s - Gracefully stopping VM" % self.domuuid)
        self.inshutdown = True
        self.dom.shutdown()
        try:
            tick = 0
            while self.dom.state()[0] == libvirt.VIR_DOMAIN_RUNNING and tick < 60:
                tick += 1
                time.sleep(0.5)

            if tick >= 60:
                print(">>> %s - Shutdown timeout expired" % self.domuuid)
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

        self.zk.set(self.zkey + '/state', 'stop'.encode('ascii'))
        self.dom = None
        self.inshutdown = False

    def live_migrate_vm(self, dest_hypervisor):
        try:
            dest_conn = libvirt.open('qemu+tcp://%s/system' % self.hypervisor)
            if dest_conn == None:
                raise
        except:
            print('>>> %s - Failed to open connection to qemu+tcp://%s/system; aborting migration' % self.hypervisor)
            return 1

        try:
            target_dom = self.dom.migrate(dest_conn, libvirt.VIR_MIGRATE_LIVE, None, None, 0)
            if target_dom == None:
                raise
            print('>>> %s - Migrated successfully' % self.domuuid)
        except:
            dest_conn.close()
            print('>>> %s - Could not live migrate VM' % self.domuuid)
            return 1

        dest_conn.close()
        return 0

    # Migrate the VM to a target host
    def migrate_vm(self):
        self.inmigrate = True

        print('>>> %s - Migrating VM to %s' % (self.domuuid, self.hypervisor))
        migrate_ret = self.live_migrate_vm(self.hypervisor)
        if migrate_ret != 0:
            print('>>> %s - Could not live migrate VM; forcing away' % self.domuuid)
            self.shutdown_vm()
            time.sleep(0.5)
        else:
            try:
                self.thishypervisor.domain_list.remove(self.domuuid)
            except ValueError:
                pass

        self.inmigrate = False

    # Receive the migration from another host (wait until VM is running)
    def receive_migrate(self):
        print('>>> %s - Receiving migration' % self.domuuid)
        self.inreceive = True
        while True:
            self.dom = lookupByUUID(self.domuuid)
            if self.dom == None:
                time.sleep(0.2)
                continue

            if self.dom.state()[0] == libvirt.VIR_DOMAIN_RUNNING:
                break

        self.zk.set(self.zkey + '/state', 'start'.encode('ascii'))
        if not self.domuuid in self.thishypervisor.domain_list:
            self.thishypervisor.domain_list.append(self.domuuid)

        print('>>> %s - Migrated successfully' % self.domuuid)
        self.inreceive = False

    #
    # Main function to manage a VM (taking only self)
    #
    def manage_vm_state(self):
        # Check the current state of the VM
        try:
            if self.dom != None:
                running, reason = self.dom.state()
            else:
                raise
        except:
            running = libvirt.VIR_DOMAIN_NOSTATE

        # VM should be stopped
        if running == libvirt.VIR_DOMAIN_RUNNING and self.state == "stop" and self.hypervisor == self.thishypervisor.name and self.instop == False:
            self.stop_vm()

        # VM should be shut down
        elif running == libvirt.VIR_DOMAIN_RUNNING and self.state == "shutdown" and self.hypervisor == self.thishypervisor.name and self.inshutdown == False:
            self.shutdown_vm()

        # VM should be migrated to this hypervisor
        elif running != libvirt.VIR_DOMAIN_RUNNING and self.state == "migrate" and self.hypervisor == self.thishypervisor.name and self.inreceive == False:
            self.receive_migrate()

        # VM should be migrated away from this hypervisor
        elif running == libvirt.VIR_DOMAIN_RUNNING and self.state == "migrate" and self.hypervisor != self.thishypervisor.name and self.inmigrate == False:
            self.migrate_vm()
            
        # VM is already running and should be
        elif running == libvirt.VIR_DOMAIN_RUNNING and self.state == "start" and self.hypervisor == self.thishypervisor.name:
            if not self.domuuid in self.thishypervisor.domain_list:
                self.thishypervisor.domain_list.append(self.domuuid)
    
        # VM should be started
        elif running != libvirt.VIR_DOMAIN_RUNNING and self.state == "start" and self.hypervisor == self.thishypervisor.name and self.instart == False:
            # Grab the domain information from Zookeeper
            domxml, domxmlstat = self.zk.get(self.zkey + '/xml')
            domxml = str(domxml.decode('ascii'))
            self.start_vm(domxml)

# This function is a wrapper for libvirt.lookupByUUID which fixes some problems
# 1. Takes a text UUID and handles converting it to bytes
# 2. Try's it and returns a sensible value if not
def lookupByUUID(tuuid):
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
            print('>>> %s - Failed to open local libvirt connection.' % self.domuuid)
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
