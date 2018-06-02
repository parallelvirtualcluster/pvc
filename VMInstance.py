#!/usr/bin/env python3

import os, time, uuid, threading, libvirt, kazoo.client

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

        # Start up a new Libvirt connection
        libvirt_name = "qemu:///system"
        conn = libvirt.open(libvirt_name)
        if conn == None:
            print('>>> Failed to open local libvirt connection.')
            exit(1)
    
        try:
            self.dom = conn.lookupByUUID(uuid.UUID(self.domuuid).bytes)
            conn.close()
        except libvirt.libvirtError:
            self.dom = None

        # Watch for changes to the hypervisor field in Zookeeper
        @zk.DataWatch(self.zkey + '/hypervisor')
        def watch_hypervisor(data, stat, event=""):
            if self.hypervisor != data.decode('ascii'):
                self.hypervisor = data.decode('ascii')
                self.manage_vm_state()

        # Watch for changes to the state field in Zookeeper
        @zk.DataWatch(self.zkey + '/state')
        def watch_state(data, stat, event=""):
            if self.state != data.decode('ascii'):
                self.state = data.decode('ascii')
                self.manage_vm_state()

    # Get data functions
    def getstate(self):
        return self.state

    def gethypervisor(self):
        return self.hypervisor

    # Start up the VM
    def start_vm(self, conn, xmlconfig):
        print(">>> Starting VM %s" % self.domuuid)
        self.instart = True
        try:
            dom = conn.createXML(xmlconfig, 0)
        except libvirt.libvirtError as e:
            print('>>> Failed to create domain %s' % self.domuuid)
            self.zk.set(self.zkey + '/state', 'stop'.encode('ascii'))

        if not self.domuuid in self.thishypervisor.domain_list:
            self.thishypervisor.domain_list.append(self.domuuid)

        self.dom = dom
        self.instart = False
   
    # Stop the VM forcibly
    def stop_vm(self):
        print(">>> Forcibly stopping VM %s" % self.domuuid)
        self.instop = True
        self.dom.destroy()
        if self.domuuid in self.thishypervisor.domain_list:
            try:
                self.thishypervisor.domain_list.remove(self.domuuid)
            except ValueError:
                pass

        self.dom = None
        self.instop = False
    
    # Shutdown the VM gracefully
    def shutdown_vm(self):
        print(">>> Stopping VM %s" % self.domuuid)
        self.inshutdown = True
        self.dom.shutdown()
        try:
            tick = 0
            while self.dom.state()[0] == libvirt.VIR_DOMAIN_RUNNING and tick < 60:
                tick += 1
                time.sleep(0.5)

            if tick >= 60:
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

        self.dom = None
        self.inshutdown = False

    # Migrate the VM to a target host
    def migrate_vm(self):
        print('>>> Migrating %s to %s' % (self.domuuid, self.hypervisor))
        self.inmigrate = True
        try:
            dest_conn = libvirt.open('qemu+tcp://%s/system' % self.hypervisor)
            if dest_conn == None:
                raise
        except:
            print('>>> Failed to open connection to qemu+tcp://%s/system' % self.hypervisor)
            self.zk.set(self.zkey + '/hypervisor', self.thishypervisor.name.encode('ascii'))
            self.zk.set(self.zkey + '/state', 'start'.encode('ascii'))
            return

        try:
            target_dom = self.dom.migrate(dest_conn, libvirt.VIR_MIGRATE_LIVE, None, None, 0)
            if target_dom == None:
                raise
            print('>>> Migrated successfully')
        except:
            print('>>> Could not migrate to the new domain; forcing away uncleanly')
            self.stop_vm()
            time.sleep(0.5)
            self.zk.set(self.zkey + '/state', 'start'.encode('ascii'))

        try:
            self.thishypervisor.domain_list.remove(self.domuuid)
        except ValueError:
            pass

        dest_conn.close()
        self.inmigrate = False
   
    # Receive the migration from another host (wait until VM is running)
    def receive_migrate(self):
        print('>>> Receiving migration of %s' % self.domuuid)
        self.inreceive = True
        while True:
            try:
                if self.dom == None or self.dom.state()[0] != libvirt.VIR_DOMAIN_RUNNING:
                    self.dom = conn.lookupByUUID(uuid.UUID(self.domuuid).bytes)
                else:
                    self.zk.set(self.zkey + '/state', 'start'.encode('ascii'))
                    if not self.domuuid in self.thishypervisor.domain_list:
                        self.thishypervisor.domain_list.append(self.domuuid)
                    break
            except:
                pass
            time.sleep(0.2)
        print('>>> Migrated successfully' % self.domuuid)
        self.inreceive = False

    #
    # Main function to manage a VM (taking only self)
    #
    def manage_vm_state(self):
        # Start up a new Libvirt connection
        libvirt_name = "qemu:///system"
        conn = libvirt.open(libvirt_name)
        if conn == None:
            print('>>> Failed to open local libvirt connection.')
            exit(1)
    
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
            self.start_vm(conn, domxml)

        # The VM should now be running so return the domain and active connection
        conn.close()
