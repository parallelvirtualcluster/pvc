#!/usr/bin/env python3

import os, socket, time, uuid, threading, libvirt, kazoo.client

class NodeInstance(threading.Thread):
    def __init__(self, name, zk):
        super(NodeInstance, self).__init__()
        # Passed-in variables on creation
        self.zkey = '/nodes/%s' % name
        self.zk = zk
        self.name = name
        self.stop_thread = threading.Event()

    def stop(self):
        self.stop_thread.set()

    def run(self):
        if self.name == socket.gethostname():
            self.setup_local_node()
        else:
            self.setup_remote_node()

    def setup_local_node(self):
        # Connect to libvirt
        libvirt_name = "qemu:///system"
        conn = libvirt.open(libvirt_name)
        if conn == None:
            print('Failed to open connection to %s' % libvirt_name)
            exit(1)
        
        # Gather data about hypervisor
        self.name = conn.getHostname()
        self.cpucount = conn.getCPUMap()[0]
        self.zk.set(self.zkey + '/state', self.name.encode('ascii'))
        self.zk.set(self.zkey + '/cpucount', str(self.cpucount).encode('ascii'))
        print("Node hostname: %s" % self.name)
        print("CPUs: %s" % self.cpucount)

        while True:
            self.memfree = conn.getFreeMemory()
            self.cpuload = os.getloadavg()[0]
            self.zk.set(self.zkey + '/memfree', str(self.memfree).encode('ascii'))
            self.zk.set(self.zkey + '/cpuload', str(self.cpuload).encode('ascii'))
            print("Free memory: %s | Load: %s" % ( self.memfree, self.cpuload ))
            time.sleep(1)
            if self.stop_thread.is_set():
                break


    def setup_remote_node(self):
        @zk.DataWatch(self.zkey + '/state')
        def watch_state(data, stat):
            self.state = data.decode('ascii')
            print("Version: %s, data: %s" % (stat.version, self.state))

        @zk.DataWatch(self.zkey + '/cpucount')
        def watch_state(data, stat):
            self.cpucount = data.decode('ascii')
            print("Version: %s, data: %s" % (stat.version, self.cpucount))

        @zk.DataWatch(self.zkey + '/cpuload')
        def watch_state(data, stat):
            self.cpuload = data.decode('ascii')
            print("Version: %s, data: %s" % (stat.version, self.cpuload))

        @zk.DataWatch(self.zkey + '/memfree')
        def watch_state(data, stat):
            self.memfree = data.decode('ascii')
            print("Version: %s, data: %s" % (stat.version, self.memfree))

