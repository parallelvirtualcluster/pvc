#!/usr/bin/env python3

import os, socket, time, uuid, threading, libvirt, kazoo.client

class NodeInstance(threading.Thread):
    def __init__(self, name, node_list, zk):
        super(NodeInstance, self).__init__()
        # Passed-in variables on creation
        self.zkey = '/nodes/%s' % name
        self.zk = zk
        self.name = name
        self.state = 'stop'
        self.stop_thread = threading.Event()
        self.node_list = node_list
        self.domainlist = []

    # Get value functions
    def getfreemem(self):
        return self.memfree

    def getcpuload(self):
        return self.cpuload

    def getname(self):
        return self.name

    def getstate(self):
        return self.state

    # Update value functions
    def updatenodelist(self, node_list):
        self.node_list = node_list

    # Shutdown the thread
    def stop(self):
        self.stop_thread.set()

    # Flush all VMs on the host
    def flush(self):
        for domain in self.domainlist:
            # Determine the best target hypervisor
            least_mem = (2^64)/8
            least_load = 999.0
            least_host = ""
            for node in node_list:
                node_freemem = node.getfreemem()
                if node_freemem < least_mem:
                    least_mem = node_freemem
                    least_host = node.getname()

            self.zk.set('/domains/' + domain + '/state', 'flush'.encode('ascii'))
            self.zk.set('/domains/' + domain + '/hypervisor', least_host.encode('ascii'))

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
        self.state = 'start'
        self.zk.set(self.zkey + '/state', 'start'.encode('ascii'))
        self.zk.set(self.zkey + '/cpucount', str(self.cpucount).encode('ascii'))
        print("Node hostname: %s" % self.name)
        print("CPUs: %s" % self.cpucount)

        while True:
            self.memfree = conn.getFreeMemory()
            self.cpuload = os.getloadavg()[0]
            try:
                self.zk.set(self.zkey + '/memfree', str(self.memfree).encode('ascii'))
                self.zk.set(self.zkey + '/cpuload', str(self.cpuload).encode('ascii'))
            except:
                if self.stop_thread.is_set():
                    return

            print("%s - Free memory: %s | Load: %s" % ( time.strftime("%d/%m/%Y %H:%M:%S"), self.memfree, self.cpuload ))
            print("Active domains: %s" % self.domainlist)
            active_node_list = []
            flushed_node_list = []
            inactive_node_list = []
    
            for node in self.node_list:
                #node_state = t_node[node].getstate()
                state, stat = self.zk.get('/nodes/%s/state' % node)
                node_state = state.decode('ascii')
                if node_state == 'start':
                    active_node_list.append(node)
                elif node_state == 'flush':
                    flushed_node_list.append(node)
                else:
                    inactive_node_list.append(node)
            
            print('Active nodes: %s' % active_node_list)
            print('Flushed nodes: %s' % flushed_node_list)
            print('Inactive nodes: %s' % inactive_node_list)
        
            for x in range(0,100):
                time.sleep(0.1)
                if self.stop_thread.is_set():
                    return

    def setup_remote_node(self):
        while True:
            for x in range(0,100):
                time.sleep(0.1)
                if self.stop_thread.is_set():
                    return


