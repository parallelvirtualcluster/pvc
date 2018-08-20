#!/usr/bin/env python3

# NodeInstance.py - Class implementing a PVC node and run by pvcd
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

import os, sys, psutil, socket, time, libvirt, kazoo.client, threading, subprocess
import pvcd.ansiiprint as ansiiprint
import pvcd.zkhandler as zkhandler

class NodeInstance():
    # Initialization function
    def __init__(self, this_node, name, t_node, s_domain, zk_conn, config):
        # Passed-in variables on creation
        self.zk_conn = zk_conn
        self.config = config
        self.this_node = this_node
        self.name = name
        self.daemon_state = 'stop'
        self.domain_state = 'ready'
        self.t_node = t_node
        self.active_node_list = []
        self.flushed_node_list = []
        self.inactive_node_list = []
        self.s_domain = s_domain
        self.domain_list = []
        self.ipmi_hostname = self.config['ipmi_hostname']
        self.domains_count = 0
        self.memused = 0
        self.memfree = 0
        self.memalloc = 0
        self.vcpualloc = 0
        self.inflush = False

        # Zookeeper handlers for changed states
        @zk_conn.DataWatch('/nodes/{}/daemonstate'.format(self.name))
        def watch_hypervisor_daemonstate(data, stat, event=""):
            try:
                self.daemon_state = data.decode('ascii')
            except AttributeError:
                self.daemon_state = 'stop'

        @zk_conn.DataWatch('/nodes/{}/domainstate'.format(self.name))
        def watch_hypervisor_domainstate(data, stat, event=""):
            try:
                self.domain_state = data.decode('ascii')
            except AttributeError:
                self.domain_state = 'unknown'

            # toggle state management of this node
            if self.name == self.this_node:
                if self.domain_state == 'flush' and self.inflush == False:
                    # Do flushing in a thread so it doesn't block the migrates out
                    flush_thread = threading.Thread(target=self.flush, args=(), kwargs={})
                    flush_thread.start()
                if self.domain_state == 'unflush' and self.inflush == False:
                    self.unflush()

        @zk_conn.DataWatch('/nodes/{}/memfree'.format(self.name))
        def watch_hypervisor_memfree(data, stat, event=""):
            try:
                self.memfree = data.decode('ascii')
            except AttributeError:
                self.memfree = 0
    
        @zk_conn.DataWatch('/nodes/{}/memused'.format(self.name))
        def watch_hypervisor_memused(data, stat, event=""):
            try:
                self.memused = data.decode('ascii')
            except AttributeError:
                self.memused = 0
    
        @zk_conn.DataWatch('/nodes/{}/memalloc'.format(self.name))
        def watch_hypervisor_memalloc(data, stat, event=""):
            try:
                self.memalloc = data.decode('ascii')
            except AttributeError:
                self.memalloc = 0
    
        @zk_conn.DataWatch('/nodes/{}/vcpualloc'.format(self.name))
        def watch_hypervisor_vcpualloc(data, stat, event=""):
            try:
                self.vcpualloc = data.decode('ascii')
            except AttributeError:
                self.vcpualloc = 0
    
        @zk_conn.DataWatch('/nodes/{}/runningdomains'.format(self.name))
        def watch_hypervisor_runningdomains(data, stat, event=""):
            try:
                self.domain_list = data.decode('ascii').split()
            except AttributeError:
                self.domain_list = []

        @zk_conn.DataWatch('/nodes/{}/domainscount'.format(self.name))
        def watch_hypervisor_domainscount(data, stat, event=""):
            try:
                self.domains_count = data.decode('ascii')
            except AttributeError:
                self.domains_count = 0
    
    # Get value functions
    def getfreemem(self):
        return self.memfree

    def getallocmem(self):
        return self.memalloc

    def getallocvcpu(self):
        return self.vcpualloc

    def getcpuload(self):
        return self.cpuload

    def getname(self):
        return self.name

    def getdaemonstate(self):
        return self.daemon_state

    def getdomainstate(self):
        return self.domain_state

    def getdomainlist(self):
        return self.domain_list

    # Update value functions
    def updatenodelist(self, t_node):
        self.t_node = t_node

    def updatedomainlist(self, s_domain):
        self.s_domain = s_domain

    # Flush all VMs on the host
    def flush(self):
        self.inflush = True
        ansiiprint.echo('Flushing node "{}" of running VMs'.format(self.name), '', 'i')
        ansiiprint.echo('Domain list: {}'.format(', '.join(self.domain_list)), '', 'c')
        fixed_domain_list = self.domain_list.copy()
        for dom_uuid in fixed_domain_list:
            ansiiprint.echo('Selecting target to migrate VM "{}"'.format(dom_uuid), '', 'i')

            current_hypervisor = zkhandler.readdata(self.zk_conn, '/domains/{}/hypervisor'.format(dom_uuid))
            target_hypervisor = findTargetHypervisor(self.zk_conn, 'mem', dom_uuid)
            if target_hypervisor == None:
                ansiiprint.echo('Failed to find migration target for VM "{}"; shutting down'.format(dom_uuid), '', 'e')
                zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(dom_uuid): 'shutdown' })
            else:
                ansiiprint.echo('Migrating VM "{}" to hypervisor "{}"'.format(dom_uuid, target_hypervisor), '', 'i')
                zkhandler.writedata(self.zk_conn, {
                    '/domains/{}/state'.format(dom_uuid): 'migrate',
                    '/domains/{}/hypervisor'.format(dom_uuid): target_hypervisor,
                    '/domains/{}/lasthypervisor'.format(dom_uuid): current_hypervisor
                })

                # Wait for the VM to migrate so the next VM's free RAM count is accurate (they migrate in serial anyways)
                while True:
                    time.sleep(1)
                    vm_current_state = zkhandler.readdata(self.zk_conn, '/domains/{}/state'.format(dom_uuid))
                    if vm_current_state == "start":
                        break

        zkhandler.writedata(self.zk_conn, { '/nodes/{}/runningdomains'.format(self.name): '' })
        zkhandler.writedata(self.zk_conn, { '/nodes/{}/domainstate'.format(self.name): 'flushed' })
        self.inflush = False

    def unflush(self):
        self.inflush = True
        ansiiprint.echo('Restoring node {} to active service.'.format(self.name), '', 'i')
        zkhandler.writedata(self.zk_conn, { '/nodes/{}/domainstate'.format(self.name): 'ready' })
        fixed_domain_list = self.s_domain.copy()
        for dom_uuid in fixed_domain_list:
            try:
                last_hypervisor = zkhandler.readdata(self.zk_conn, '/domains/{}/lasthypervisor'.format(dom_uuid))
            except:
                continue

            if last_hypervisor != self.name:
                continue

            ansiiprint.echo('Setting unmigration for VM "{}"'.format(dom_uuid), '', 'i')
            zkhandler.writedata(self.zk_conn, {
                '/domains/{}/state'.format(dom_uuid): 'migrate',
                '/domains/{}/hypervisor'.format(dom_uuid): self.name,
                '/domains/{}/lasthypervisor'.format(dom_uuid): ''
            })

        self.inflush = False

    def update_zookeeper(self):
        # Connect to libvirt
        libvirt_name = "qemu:///system"
        lv_conn = libvirt.open(libvirt_name)
        if lv_conn == None:
            ansiiprint.echo('Failed to open connection to "{}"'.format(libvirt_name), '', 'e')
            return

        # Get past state and update if needed
        past_state = zkhandler.readdata(self.zk_conn, '/nodes/{}/daemonstate'.format(self.name))
        if past_state != 'run':
            self.daemon_state = 'run'
            zkhandler.writedata(self.zk_conn, { '/nodes/{}/daemonstate'.format(self.name): 'run' })
        else:
            self.daemon_state = 'run'

        # Toggle state management of dead VMs to restart them
        memalloc = 0
        vcpualloc = 0
        for domain, instance in self.s_domain.items():
            if instance.inshutdown == False and domain in self.domain_list:
                # Add the allocated memory to our memalloc value
                memalloc += instance.getmemory()
                vcpualloc += instance.getvcpus()
                if instance.getstate() == 'start' and instance.gethypervisor() == self.name:
                    if instance.getdom() != None:
                        try:
                            if instance.getdom().state()[0] != libvirt.VIR_DOMAIN_RUNNING:
                                raise
                        except Exception as e:
                            # Toggle a state "change"
                            zkhandler.writedata(self.zk_conn, { '/domains/{}/state'.format(domain): instance.getstate() })

        # Ensure that any running VMs are readded to the domain_list
        running_domains = lv_conn.listAllDomains(libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE)
        for domain in running_domains:
            domain_uuid = domain.UUIDString()
            if domain_uuid not in self.domain_list:
                self.domain_list.append(domain_uuid)

        # Set our information in zookeeper
        self.name = lv_conn.getHostname()
        self.memused = int(psutil.virtual_memory().used / 1024 / 1024)
        self.memfree = int(psutil.virtual_memory().free / 1024 / 1024)
        self.memalloc = memalloc
        self.vcpualloc = vcpualloc
        self.cpuload = os.getloadavg()[0]
        self.domains_count = len(lv_conn.listDomainsID())
        keepalive_time = int(time.time())
        try:
            zkhandler.writedata(self.zk_conn, {
                '/nodes/{}/memused'.format(self.name): str(self.memused),
                '/nodes/{}/memfree'.format(self.name): str(self.memfree),
                '/nodes/{}/memalloc'.format(self.name): str(self.memalloc),
                '/nodes/{}/vcpualloc'.format(self.name): str(self.vcpualloc),
                '/nodes/{}/cpuload'.format(self.name): str(self.cpuload),
                '/nodes/{}/runningdomains'.format(self.name): ' '.join(self.domain_list),
                '/nodes/{}/domainscount'.format(self.name): str(self.domains_count),
                '/nodes/{}/keepalive'.format(self.name): str(keepalive_time)
            })
        except:
            ansiiprint.echo('Failed to set keepalive data', '', 'e')
            return

        # Close the Libvirt connection
        lv_conn.close()

        # Display node information to the terminal
        ansiiprint.echo('{}{} keepalive{}'.format(ansiiprint.purple(), self.name, ansiiprint.end()), '', 't')
        ansiiprint.echo('{0}Active domains:{1} {2}  {0}Allocated memory [MiB]:{1} {6}  {0}Free memory [MiB]:{1} {3}  {0}Used memory [MiB]:{1} {4}  {0}Load:{1} {5}'.format(ansiiprint.bold(), ansiiprint.end(), self.domains_count, self.memfree, self.memused, self.cpuload, self.memalloc), '', 'c')

        # Update our local node lists
        for node_name in self.t_node:
            try:
                node_daemon_state = zkhandler.readdata(self.zk_conn, '/nodes/{}/daemonstate'.format(node_name))
                node_domain_state = zkhandler.readdata(self.zk_conn, '/nodes/{}/domainstate'.format(node_name))
                node_keepalive = int(zkhandler.readdata(self.zk_conn, '/nodes/{}/keepalive'.format(node_name)))
            except:
                node_daemon_state = 'unknown'
                node_domain_state = 'unknown'
                node_keepalive = 0

            # Handle deadtime and fencng if needed
            # (A node is considered dead when its keepalive timer is >6*keepalive_interval seconds
            # out-of-date while in 'start' state)
            node_deadtime = int(time.time()) - ( int(self.config['keepalive_interval']) * int(self.config['fence_intervals']) )
            if node_keepalive < node_deadtime and node_daemon_state == 'run':
                ansiiprint.echo('Node {} seems dead - starting monitor for fencing'.format(node_name), '', 'w')
                zkhandler.writedata(self.zk_conn, { '/nodes/{}/daemonstate'.format(node_name): 'dead' })
                fence_thread = threading.Thread(target=fenceNode, args=(node_name, self.zk_conn, self.config), kwargs={})
                fence_thread.start()

            # Update the arrays
            if node_daemon_state == 'run' and node_domain_state != 'flushed' and node_name not in self.active_node_list:
                self.active_node_list.append(node_name)
                try:
                    self.flushed_node_list.remove(node_name)
                except ValueError:
                    pass
                try:
                    self.inactive_node_list.remove(node_name)
                except ValueError:
                    pass
            if node_daemon_state != 'run' and node_domain_state != 'flushed' and node_name not in self.inactive_node_list:
                self.inactive_node_list.append(node_name)
                try:
                    self.active_node_list.remove(node_name)
                except ValueError:
                    pass
                try:
                    self.flushed_node_list.remove(node_name)
                except ValueError:
                    pass
            if node_domain_state == 'flushed' and node_name not in self.flushed_node_list:
                self.flushed_node_list.append(node_name)
                try:
                    self.active_node_list.remove(node_name)
                except ValueError:
                    pass
                try:
                    self.inactive_node_list.remove(node_name)
                except ValueError:
                    pass
        
        # Display cluster information to the terminal
        ansiiprint.echo('{}Cluster status{}'.format(ansiiprint.purple(), ansiiprint.end()), '', 't')
        ansiiprint.echo('{}Active nodes:{} {}'.format(ansiiprint.bold(), ansiiprint.end(), ' '.join(self.active_node_list)), '', 'c')
        ansiiprint.echo('{}Inactive nodes:{} {}'.format(ansiiprint.bold(), ansiiprint.end(), ' '.join(self.inactive_node_list)), '', 'c')
        ansiiprint.echo('{}Flushed nodes:{} {}'.format(ansiiprint.bold(), ansiiprint.end(), ' '.join(self.flushed_node_list)), '', 'c')

#
# Find a migration target
#
def findTargetHypervisor(zk_conn, search_field, dom_uuid):
    if search_field == 'mem':
        return findTargetHypervisorMem(zk_conn, dom_uuid)
    if search_field == 'load':
        return findTargetHypervisorLoad(zk_conn, dom_uuid)
    if search_field == 'vcpus':
        return findTargetHypervisorVCPUs(zk_conn, dom_uuid)
    if search_field == 'vms':
        return findTargetHypervisorVMs(zk_conn, dom_uuid)
    return None

# Get the list of valid target hypervisors
def getHypervisors(zk_conn, dom_uuid):
    valid_hypervisor_list = []
    full_hypervisor_list = zkhandler.listchildren(zk_conn, '/nodes')
    current_hypervisor = zkhandler.readdata(zk_conn, '/domains/{}/hypervisor'.format(dom_uuid))

    for hypervisor in full_hypervisor_list:
        daemon_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(hypervisor))
        domain_state = zkhandler.readdata(zk_conn, '/nodes/{}/domainstate'.format(hypervisor))

        if hypervisor == current_hypervisor:
            continue

        if daemon_state != 'run' or domain_state != 'ready':
            continue

        valid_hypervisor_list.append(hypervisor)

    return valid_hypervisor_list
    
# via free memory (relative to allocated memory)
def findTargetHypervisorMem(zk_conn, dom_uuid):
    most_allocfree = 0
    target_hypervisor = None

    hypervisor_list = getHypervisors(zk_conn, dom_uuid)
    for hypervisor in hypervisor_list:
        memalloc = int(zkhandler.readdata(zk_conn, '/nodes/{}/memalloc'.format(hypervisor)))
        memused = int(zkhandler.readdata(zk_conn, '/nodes/{}/memused'.format(hypervisor)))
        memfree = int(zkhandler.readdata(zk_conn, '/nodes/{}/memfree'.format(hypervisor)))
        memtotal = memused + memfree
        allocfree = memtotal - memalloc

        if allocfree > most_allocfree:
            most_allocfree = allocfree
            target_hypervisor = hypervisor

    return target_hypervisor

# via load average
def findTargetHypervisorLoad(zk_conn, dom_uuid):
    least_load = 9999
    target_hypervisor = None

    hypervisor_list = getHypervisors(zk_conn, dom_uuid)
    for hypervisor in hypervisor_list:
        load = int(zkhandler.readdata(zk_conn, '/nodes/{}/load'.format(hypervisor)))

        if load < least_load:
            least_load = load
            target_hypevisor = hypervisor

    return target_hypervisor

# via total vCPUs
def findTargetHypervisorVCPUs(zk_conn, dom_uuid):
    least_vcpus = 9999
    target_hypervisor = None

    hypervisor_list = getHypervisors(zk_conn, dom_uuid)
    for hypervisor in hypervisor_list:
        vcpus = int(zkhandler.readdata(zk_conn, '/nodes/{}/vcpualloc'.format(hypervisor)))

        if vcpus < least_vcpus:
            least_vcpus = vcpus
            target_hypervisor = hypervisor

    return target_hypervisor

# via total VMs
def findTargetHypervisorVMs(zk_conn, dom_uuid):
    least_vms = 9999
    target_hypervisor = None

    hypervisor_list = getHypervisors(zk_conn, dom_uuid)
    for hypervisor in hypervisor_list:
        vms = int(zkhandler.readdata(zk_conn, '/nodes/{}/domainscount'.format(hypervisor)))

        if vms < least_vms:
            least_vms = vms
            target_hypervisor = hypervisor

    return target_hypervisor


#
# Fence thread entry function
#
def fenceNode(node_name, zk_conn, config):
    failcount = 0
    # We allow exactly 3 saving throws for the host to come back online
    while failcount < 3:
        # Wait 5 seconds
        time.sleep(5)
        # Get the state
        node_daemon_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(node_name))
        # Is it still 'dead'
        if node_daemon_state == 'dead':
            failcount += 1
            ansiiprint.echo('Node "{}" failed {} saving throws'.format(node_name, failcount), '', 'w')
        # It changed back to something else so it must be alive
        else:
            ansiiprint.echo('Node "{}" passed a saving throw; canceling fence'.format(node_name), '', 'o')
            return

    ansiiprint.echo('Fencing node "{}" via IPMI reboot signal'.format(node_name), '', 'e')

    # Get IPMI information
    ipmi_hostname = zkhandler.readdata(zk_conn, '/nodes/{}/ipmihostname'.format(node_name))
    ipmi_username = zkhandler.readdata(zk_conn, '/nodes/{}/ipmiusername'.format(node_name))
    ipmi_password = zkhandler.readdata(zk_conn, '/nodes/{}/ipmipassword'.format(node_name))

    # Shoot it in the head
    fence_status = rebootViaIPMI(ipmi_hostname, ipmi_username, ipmi_password)
    # Hold to ensure the fence takes effect
    time.sleep(3)

    # If the fence succeeded and successful_fence is migrate
    if fence_status == True and config['successful_fence'] == 'migrate':
        migrateFromFencedHost(zk_conn, node_name)
    # If the fence failed and failed_fence is migrate
    if fence_status == False and config['failed_fence'] == 'migrate' and config['suicide_intervals'] != '0':
        migrateFromFencedHost(zk_conn, node_name)

# Migrate hosts away from a fenced node
def migrateFromFencedHost(zk_conn, node_name):
    ansiiprint.echo('Moving VMs from dead hypervisor "{}" to new hosts'.format(node_name), '', 'i')
    dead_node_running_domains = zkhandler.readdata(zk_conn, '/nodes/{}/runningdomains'.format(node_name)).split()
    for dom_uuid in dead_node_running_domains:
        target_hypervisor = findTargetHypervisor(zk_conn, 'mem', dom_uuid)

        ansiiprint.echo('Moving VM "{}" to hypervisor "{}"'.format(dom_uuid, target_hypervisor), '', 'i')
        zkhandler.writedata(zk_conn, {
            '/domains/{}/state'.format(dom_uuid): 'start',
            '/domains/{}/hypervisor'.format(dom_uuid): target_hypervisor,
            '/domains/{}/lasthypervisor'.format(dom_uuid): current_hypervisor
        })

    # Set node in flushed state for easy remigrating when it comes back
    zkhandler.writedata(zk_conn, { '/nodes/{}/domainstate'.format(node_name): 'flushed' })

#
# Perform an IPMI fence
#
def rebootViaIPMI(ipmi_hostname, ipmi_user, ipmi_password):
    ipmi_command = ['/usr/bin/ipmitool', '-I', 'lanplus', '-H', ipmi_hostname, '-U', ipmi_user, '-P', ipmi_password, 'chassis', 'power', 'reset']
    ipmi_command_output = subprocess.run(ipmi_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if ipmi_command_output.returncode == 0:
        ansiiprint.echo('Successfully rebooted dead node', '', 'o')
        return True
    else:
        ansiiprint.echo('Failed to reboot dead node', '', 'e')
        return False
