#!/usr/bin/env python3

# RouterInstance.py - Class implementing a PVC router and run by pvcrd
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

import os
import sys
import psutil
import socket
import time
import threading
import subprocess

import daemon_lib.ansiiprint as ansiiprint
import daemon_lib.zkhandler as zkhandler
import daemon_lib.common as common

class RouterInstance():
    # Initialization function
    def __init__(self, this_router, name, t_router, s_network, zk_conn, config):
        # Passed-in variables on creation
        self.zk_conn = zk_conn
        self.config = config
        self.this_router = this_router
        self.name = name
        self.daemon_state = 'stop'
        self.network_state = 'secondary'
        self.t_router = t_router
        self.primary_router_list = []
        self.secondary_router_list = []
        self.inactive_router_list = []
        self.s_network = s_network
        self.network_list = []
        self.ipmi_hostname = self.config['ipmi_hostname']

        # Zookeeper handlers for changed states
        @zk_conn.DataWatch('/routers/{}/daemonstate'.format(self.name))
        def watch_hypervisor_daemonstate(data, stat, event=""):
            try:
                self.daemon_state = data.decode('ascii')
            except AttributeError:
                self.daemon_state = 'stop'

        @zk_conn.DataWatch('/routers/{}/networkstate'.format(self.name))
        def watch_hypervisor_networkstate(data, stat, event=""):
            try:
                self.network_state = data.decode('ascii')
            except AttributeError:
                self.network_state = 'secondary'

            # toggle state management of this router
            if s_network != {}: # If there's no network list, we're too early in startup
                if self.name == self.this_router:
                    if self.network_state == 'secondary':
                        self.become_secondary()
                    if self.network_state == 'primary':
                        self.become_primary()

    # Get value functions
    def getname(self):
        return self.name

    def getdaemonstate(self):
        return self.daemon_state

    def getnetworkstate(self):
        return self.network_state

    def getnetworklist(self):
        return self.network_list

    # Update value functions
    def updaterouterlist(self, t_router):
        self.t_router = t_router

    def updatenetworklist(self, s_network):
        self.s_network = s_network
        for network in s_network:
            self.network_list.append(s_network[network].getvni())

    def become_secondary(self):
        ansiiprint.echo('Setting router {} to secondary state'.format(self.name), '', 'i')
        ansiiprint.echo('Network list: {}'.format(', '.join(self.network_list)), '', 'c')
        for router in self.t_router:
            if self.t_router[router].getname() != self.this_router:
                if self.t_router[router].getnetworkstate() != 'primary':
                    zkhandler.writedata(self.zk_conn, { '/routers/{}/networkstate'.format(self.t_router[router].getname()): 'primary' })
        time.sleep(2)
        for network in self.s_network:
            self.s_network[network].stopDHCPServer()
            self.s_network[network].removeGatewayAddress()

    def set_secondary(self):
        result = zkhandler.writedata(self.zk_conn, {
                '/routers/{}/networkstate'.format(self.name): 'secondary'
            })
        if not result:
            time.sleep(1)

    def become_primary(self):
        ansiiprint.echo('Setting router {} to primary state.'.format(self.name), '', 'i')
        ansiiprint.echo('Network list: {}'.format(', '.join(self.network_list)), '', 'c')
        for network in self.s_network:
            self.s_network[network].createGatewayAddress()
            self.s_network[network].startDHCPServer()
        for router in self.t_router:
            if self.t_router[router].getname() != self.this_router:
                if self.t_router[router].getnetworkstate() != 'secondary':
                    zkhandler.writedata(self.zk_conn, { '/routers/{}/networkstate'.format(self.t_router[router].getname()): 'secondary' })

    def set_primary(self):
        result = zkhandler.writedata(self.zk_conn, { 
                '/routers': self.name,
                '/routers/{}/networkstate'.format(self.name): 'primary',
            })
        if not result:
            time.sleep(1)
                

    def update_zookeeper(self):
        # Get past state and update if needed
        past_state = zkhandler.readdata(self.zk_conn, '/routers/{}/daemonstate'.format(self.name))
        if past_state != 'run':
            self.daemon_state = 'run'
            zkhandler.writedata(self.zk_conn, { '/routers/{}/daemonstate'.format(self.name): 'run' })
        else:
            self.daemon_state = 'run'

        # Set our information in zookeeper
        cpuload = os.getloadavg()[0]
        keepalive_time = int(time.time())
        try:
            zkhandler.writedata(self.zk_conn, {
                '/routers/{}/keepalive'.format(self.name): str(keepalive_time),
                '/routers/{}/cpuload'.format(self.name): str(cpuload),
            })
        except:
            ansiiprint.echo('Failed to set keepalive data', '', 'e')
            return

        # Display router information to the terminal
        ansiiprint.echo('{}{} keepalive{}'.format(ansiiprint.purple(), self.name, ansiiprint.end()), '', 't')
        ansiiprint.echo('{0}Networks count:{1} {2}  {0}Load average:{1} {3}'.format(ansiiprint.bold(), ansiiprint.end(), len(self.network_list), cpuload), '', 'c')

        # Update our local router lists
        for router_name in self.t_router:
            try:
                router_daemon_state = zkhandler.readdata(self.zk_conn, '/routers/{}/daemonstate'.format(router_name))
                router_network_state = zkhandler.readdata(self.zk_conn, '/routers/{}/networkstate'.format(router_name))
                router_keepalive = int(zkhandler.readdata(self.zk_conn, '/routers/{}/keepalive'.format(router_name)))
            except:
                router_daemon_state = 'unknown'
                router_network_state = 'unknown'
                router_keepalive = 0

            # Handle deadtime and fencng if needed
            # (A router is considered dead when its keepalive timer is >6*keepalive_interval seconds
            # out-of-date while in 'start' state)
            router_deadtime = int(time.time()) - ( int(self.config['keepalive_interval']) * int(self.config['fence_intervals']) )
            if router_keepalive < router_deadtime and router_daemon_state == 'run':
                ansiiprint.echo('Router {} seems dead - starting monitor for fencing'.format(router_name), '', 'w')
                zkhandler.writedata(self.zk_conn, { '/routers/{}/daemonstate'.format(router_name): 'dead' })
                fence_thread = threading.Thread(target=fenceRouter, args=(router_name, self.zk_conn, self.config), kwargs={})
                fence_thread.start()

            # Update the arrays
            if router_daemon_state == 'run' and router_network_state != 'secondary' and router_name not in self.primary_router_list:
                self.primary_router_list.append(router_name)
                try:
                    self.secondary_router_list.remove(router_name)
                except ValueError:
                    pass
                try:
                    self.inactive_router_list.remove(router_name)
                except ValueError:
                    pass
            if router_daemon_state != 'run' and router_network_state != 'secondary' and router_name not in self.inactive_router_list:
                self.inactive_router_list.append(router_name)
                try:
                    self.primary_router_list.remove(router_name)
                except ValueError:
                    pass
                try:
                    self.secondary_router_list.remove(router_name)
                except ValueError:
                    pass
            if router_network_state == 'secondary' and router_name not in self.secondary_router_list:
                self.secondary_router_list.append(router_name)
                try:
                    self.primary_router_list.remove(router_name)
                except ValueError:
                    pass
                try:
                    self.inactive_router_list.remove(router_name)
                except ValueError:
                    pass
       
       # Try to set ourself primary if there is no primary in the cluster
        cluster_has_primary = False
        for router in self.t_router:
            if self.t_router[router].getnetworkstate() == 'primary':
                cluster_has_primary = True
                break
        if not cluster_has_primary:
            self.set_primary()

        # Display cluster information to the terminal
        ansiiprint.echo('{}Cluster status{}'.format(ansiiprint.purple(), ansiiprint.end()), '', 't')
        ansiiprint.echo('{}Primary router:{} {}'.format(ansiiprint.bold(), ansiiprint.end(), ' '.join(self.primary_router_list)), '', 'c')
        ansiiprint.echo('{}Secondary router:{} {}'.format(ansiiprint.bold(), ansiiprint.end(), ' '.join(self.secondary_router_list)), '', 'c')
        ansiiprint.echo('{}Inactive routers:{} {}'.format(ansiiprint.bold(), ansiiprint.end(), ' '.join(self.inactive_router_list)), '', 'c')

#
# Fence thread entry function
#
def fenceRouter(router_name, zk_conn, config):
    failcount = 0
    # We allow exactly 3 saving throws for the host to come back online
    while failcount < 3:
        # Wait 5 seconds
        time.sleep(5)
        # Get the state
        router_daemon_state = zkhandler.readdata(zk_conn, '/routers/{}/daemonstate'.format(router_name))
        # Is it still 'dead'
        if router_daemon_state == 'dead':
            failcount += 1
            ansiiprint.echo('Router "{}" failed {} saving throws'.format(router_name, failcount), '', 'w')
        # It changed back to something else so it must be alive
        else:
            ansiiprint.echo('Router "{}" passed a saving throw; canceling fence'.format(router_name), '', 'o')
            return

    ansiiprint.echo('Fencing router "{}" via IPMI reboot signal'.format(router_name), '', 'e')

    # Get IPMI information
    ipmi_hostname = zkhandler.readdata(zk_conn, '/routers/{}/ipmihostname'.format(router_name))
    ipmi_username = zkhandler.readdata(zk_conn, '/routers/{}/ipmiusername'.format(router_name))
    ipmi_password = zkhandler.readdata(zk_conn, '/routers/{}/ipmipassword'.format(router_name))

    # Shoot it in the head
    fence_status = rebootViaIPMI(ipmi_hostname, ipmi_username, ipmi_password)
    # Hold to ensure the fence takes effect
    time.sleep(3)

    # Set router in secondary state
    zkhandler.writedata(zk_conn, { '/routers/{}/networkstate'.format(router_name): 'secondary' })

#
# Perform an IPMI fence
#
def rebootViaIPMI(ipmi_hostname, ipmi_user, ipmi_password):
    retcode = common.run_os_command('ipmitool -I lanplus -H {} -U {} -P {} chassis power reset'.format(
        ipmi_hostname, ipmi_user, ipmi_password
    ))
    if retcode == 0:
        ansiiprint.echo('Successfully rebooted dead router', '', 'o')
        return True
    else:
        ansiiprint.echo('Failed to reboot dead router', '', 'e')
        return False
