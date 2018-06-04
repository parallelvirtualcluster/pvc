#!/usr/bin/env python3

import os, sys, socket, time, threading, libvirt, kazoo.client, pvcf

class NodeInstance(threading.Thread):
    def __init__(self, name, t_node, s_domain, zk):
        super(NodeInstance, self).__init__()
        # Passed-in variables on creation
        self.zkey = '/nodes/%s' % name
        self.zk = zk
        self.name = name
        self.state = 'stop'
        self.stop_thread = threading.Event()
        self.t_node = t_node
        self.s_domain = s_domain
        self.domain_list = []

        # Zookeeper handlers for changed states
        @zk.DataWatch(self.zkey + '/state')
        def watch_hypervisor_state(data, stat, event=""):
            self.state = data.decode('ascii')
    
        @zk.DataWatch(self.zkey + '/memfree')
        def watch_hypervisor_memfree(data, stat, event=""):
            self.memfree = data.decode('ascii')
    
        @zk.DataWatch(self.zkey + '/runningdomains')
        def watch_hypervisor_runningdomains(data, stat, event=""):
            self.domain_list = data.decode('ascii').split()

    # Get value functions
    def getfreemem(self):
        return self.memfree

    def getcpuload(self):
        return self.cpuload

    def getname(self):
        return self.name

    def getstate(self):
        return self.state

    def getdomainlist(self):
        return self.domain_list

    # Update value functions
    def updatenodelist(self, t_node):
        self.t_node = t_node

    def updatedomainlist(self, s_domain):
        self.s_domain = s_domain

    # Shutdown the thread
    def stop(self):
        self.stop_thread.set()

    # Flush all VMs on the host
    def flush(self):
        for domain in self.domain_list:
            print(domain)
            # Determine the best target hypervisor
            least_mem = (2^64)/8
            least_load = 999.0
            least_host = ""
            for node in self.t_node:
                node_freemem = node.getfreemem()
                if node_freemem < least_mem:
                    least_mem = node_freemem
                    least_host = node.getname()

            transaction = self.zk.transaction()
            transaction.set_data('/domains/' + domain + '/state', 'migrate'.encode('ascii'))
            transaction.set_data('/domains/' + domain + '/hypervisor', least_host.encode('ascii'))
            transaction.commit()

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
            print('>>> Failed to open connection to %s' % libvirt_name)
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
            # Toggle state management of all VMs
            for domain, instance in self.s_domain.items():
                if instance.inshutdown == False and domain in self.domain_list:
                    instance.manage_vm_state()

            # Remove any non-running VMs from our list
            for domain in self.domain_list:
                dom = pvcf.lookupByUUID(domain)
                if dom == None:
                    try:
                        self.domain_list.remove(domain)
                    except:
                        pass
                else:
                    state = dom.state()[0]
                    if state != libvirt.VIR_DOMAIN_RUNNING:
                        try:
                            self.domain_list.remove(domain)
                        except:
                            pass

            # Set our information in zookeeper
            self.memfree = conn.getFreeMemory()
            self.cpuload = os.getloadavg()[0]
            try:
                self.zk.set(self.zkey + '/memfree', str(self.memfree).encode('ascii'))
                self.zk.set(self.zkey + '/cpuload', str(self.cpuload).encode('ascii'))
                self.zk.set(self.zkey + '/runningdomains', ' '.join(self.domain_list).encode('ascii'))
            except:
                if self.stop_thread.is_set():
                    return

            print(">>> %s - Free memory: %s | Load: %s" % ( time.strftime("%d/%m/%Y %H:%M:%S"), self.memfree, self.cpuload ))
            print("Active domains: %s" % self.domain_list)
            active_node_list = []
            flushed_node_list = []
            inactive_node_list = []
    
            for node in self.t_node:
                node_name = node.getname()
                state, stat = self.zk.get('/nodes/%s/state' % node_name)
                node_state = state.decode('ascii')
                if node_state == 'start':
                    active_node_list.append(node_name)
                elif node_state == 'flush':
                    flushed_node_list.append(node_name)
                    self.flush()
                else:
                    inactive_node_list.append(node_name)
            
            print('Active nodes: %s' % active_node_list)
            print('Flushed nodes: %s' % flushed_node_list)
            print('Inactive nodes: %s' % inactive_node_list)
        
            # Sleep for 10s but with quick interruptability
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


