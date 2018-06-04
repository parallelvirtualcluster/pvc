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
        self.active_node_list = []
        self.flushed_node_list = []
        self.inactive_node_list = []
        self.s_domain = s_domain
        self.domain_list = []

        # Zookeeper handlers for changed states
        @zk.DataWatch(self.zkey + '/state')
        def watch_hypervisor_state(data, stat, event=""):
            self.state = data.decode('ascii')
            if self.state == 'flush':
                self.flush()
            if self.state == 'unflush':
                self.unflush()
    
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
            # Determine the best target hypervisor
            least_mem = 2**64
            least_host = None
            for node_name in self.active_node_list:
                # It should never include itself, but just in case
                if node_name == self.name:
                    continue

                # Get our node object and free memory
                node = self.t_node[node_name]
                node_freemem = int(node.getfreemem())

                # Calculate who has the most free memory
                if node_freemem < least_mem:
                    least_mem = node_freemem
                    least_host = node_name

            if least_host == None:
                print(">>> Failed to find valid migration target for %s" % domain)
                transaction = self.zk.transaction()
                transaction.set_data('/domains/' + domain + '/state', 'shutdown'.encode('ascii'))
                transaction.commit()
            else:
                print(">>> Setting migration to %s for %s" % (least_host, domain))
                transaction = self.zk.transaction()
                transaction.set_data('/domains/' + domain + '/state', 'migrate'.encode('ascii'))
                transaction.set_data('/domains/' + domain + '/hypervisor', least_host.encode('ascii'))
                result = transaction.commit()

            # Wait 1s between migrations
            time.sleep(1)

    def unflush(self):
        print('>>> Restoring node %s to active service' % self.name)
        for domain in self.s_domain:
            former_hypervisor = self.zk.get("/domains/" + domain + '/formerhypervisor')[0].decode('ascii')
            if former_hypervisor == self.name:
                print(">>> Setting unmigration for %s" % domain)
                transaction = self.zk.transaction()
                transaction.set_data('/domains/' + domain + '/state', 'migrate'.encode('ascii'))
                transaction.set_data('/domains/' + domain + '/hypervisor', self.name.encode('ascii'))
                result = transaction.commit()

                # Wait 1s between migrations
                time.sleep(1)

        self.zk.set("/nodes/" + self.name + "/state", 'start'.encode('ascii'))

    def run(self):
        if self.name == socket.gethostname():
            self.setup_local_node()

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
        self.zk.set(self.zkey + '/cpucount', str(self.cpucount).encode('ascii'))
        print("Node hostname: %s" % self.name)
        print("CPUs: %s" % self.cpucount)

        # Get past state and update if needed
        past_state = self.zk.get(self.zkey + '/state')[0].decode('ascii')
        if past_state != 'flush':
            self.state = 'start'
            self.zk.set(self.zkey + '/state', 'start'.encode('ascii'))
        else:
            self.state = 'flush'

        while True:
            # Toggle state management of all VMs and remove any non-running VMs
            for domain, instance in self.s_domain.items():
                if instance.inshutdown == False and domain in self.domain_list:
                    instance.manage_vm_state()
                    if instance.dom == None:
                        try:
                            self.domain_list.remove(domain)
                        except:
                            pass
                    else:
                        try:
                            state = instance.dom.state()[0]
                        except:
                            state = libvirt.VIR_DOMAIN_NOSTATE
                            
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
   
            # Update our local node lists
            for node_name in self.t_node:
                state, stat = self.zk.get('/nodes/%s/state' % node_name)
                node_state = state.decode('ascii')

                if node_state == 'start' and node_name not in self.active_node_list:
                    self.active_node_list.append(node_name)
                    try:
                        self.flushed_node_list.remove(node_name)
                    except ValueError:
                        pass
                    try:
                        self.inactive_node_list.remove(node_name)
                    except ValueError:
                        pass
                if node_state == 'flush' and node_name not in self.flushed_node_list:
                    self.flushed_node_list.append(node_name)
                    try:
                        self.active_node_list.remove(node_name)
                    except ValueError:
                        pass
                    try:
                        self.inactive_node_list.remove(node_name)
                    except ValueError:
                        pass
                if node_state != 'start' and node_state != 'flush' and node_name not in self.inactive_node_list:
                    self.inactive_node_list.append(node_name)
                    try:
                        self.active_node_list.remove(node_name)
                    except ValueError:
                        pass
                    try:
                        self.flushed_node_list.remove(node_name)
                    except ValueError:
                        pass
            
            print('Active nodes: %s' % self.active_node_list)
            print('Flushed nodes: %s' % self.flushed_node_list)
            print('Inactive nodes: %s' % self.inactive_node_list)

            # Sleep for 9s but with quick interruptability
            for x in range(0,90):
                time.sleep(0.1)
                if self.stop_thread.is_set():
                    return
