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
    
    # Start up the VM
    def start_vm(self, conn, xmlconfig):
        print("Starting VM %s" % self.domuuid)
        try:
            dom = conn.createXML(xmlconfig, 0)
        except:
            print('Failed to create domain %s' % self.domuuid)
            self.zk.set(self.zkey + '/state', 'stop'.encode('ascii'))
            return None

        if not self.domuuid in self.thishypervisor.domain_list:
            self.thishypervisor.domain_list.append(self.domuuid)

        return dom
   
    # Stop the VM forcibly
    def stop_vm(self):
        print("Forcibly stopping VM %s" % self.domuuid)
        self.dom.destroy()
        if self.domuuid in self.thishypervisor.domain_list:
            self.thishypervisor.domain_list.remove(self.domuuid)
    
    # Shutdown the VM gracefully
    def shutdown_vm(self):
        print("Stopping VM %s" % self.domuuid)
        self.dom.shutdown()
        if self.domuuid in self.thishypervisor.domain_list:
            self.thishypervisor.domain_list.remove(self.domuuid)

    # Migrate the VM to a target host
    def migrate_vm(self):
        self.zk.set(self.zkey + '/status', b'migrate')
        dest_conn = libvirt.open('qemu+ssh://%s/system' % target)
        if dest_conn == None:
            print('Failed to open connection to qemu+ssh://%s/system' % target)
            exit(1)

        target_dom = self.dom.migrate(dest_conn, libvirt.VIR_MIGRATE_LIVE, None, None, 0)
        if target_dom == None:
            print('Could not migrate to the new domain')
            exit(1)

        self.thishypervisor.domain_list.remove(self.domuuid)
        print('Migrated successfully')
        dest_conn.close()
   
    # Receive the migration from another host (wait until VM is running)
    def receive_migrate(self):
        while True:
            if self.dom == None or self.dom.state() != libvirt.VIR_DOMAIN_RUNNING:
                continue
            else:
                self.zk.set(self.zkey + '/status', b'start')
                if not self.domuuid in self.thishypervisor.domain_list:
                    self.thishypervisor.domain_list.append(self.domuuid)
                break

    #
    # Main function to manage a VM (taking only self)
    #
    def manage_vm_state(self):
        # Start up a new Libvirt connection
        libvirt_name = "qemu:///system"
        conn = libvirt.open(libvirt_name)
        if conn == None:
            print('Failed to open local libvirt connection.')
            exit(1)
    
        # Check the current state of the VM
        try:
            self.dom = conn.lookupByUUID(uuid.UUID(self.domuuid).bytes)
            if self.dom != None:
                running, reason = self.dom.state()
            else:
                running = libvirt.VIR_DOMAIN_NOSTATE
        except:
            running = libvirt.VIR_DOMAIN_NOSTATE

        if running == libvirt.VIR_DOMAIN_RUNNING and self.state == "stop" and self.hypervisor == self.thishypervisor.name:
            self.stop_vm()

        if running == libvirt.VIR_DOMAIN_RUNNING and self.state == "shutdown" and self.hypervisor == self.thishypervisor.name:
            self.shutdown_vm()

        elif running != libvirt.VIR_DOMAIN_RUNNING and self.state == "migrate" and self.hypervisor == self.thishypervisor.name:
            self.receive_migrate()
            
        elif running == libvirt.VIR_DOMAIN_RUNNING and self.state == "migrate" and self.hypervisor != self.thishypervisor.name:
            self.migrate_vm()
            
        elif running != libvirt.VIR_DOMAIN_RUNNING and self.state == "start" and self.hypervisor == self.thishypervisor.name:
            # Grab the domain information from Zookeeper
            domxml, domxmlstat = self.zk.get(self.zkey + '/xml')
            domxml = str(domxml.decode('ascii'))
            self.dom = self.start_vm(conn, domxml)

        elif running == libvirt.VIR_DOMAIN_RUNNING and self.state == "start" and self.hypervisor == self.thishypervisor.name:
            if not self.domuuid in self.thishypervisor.domain_list:
                self.thishypervisor.domain_list.append(self.domuuid)
    
        # The VM should now be running so return the domain and active connection
        conn.close
