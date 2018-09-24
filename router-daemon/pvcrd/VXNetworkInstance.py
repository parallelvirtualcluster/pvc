#!/usr/bin/env python3

# VXNetworkInstance.py - Class implementing a PVC VM network (router-side) and run by pvcrd
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
import time
import subprocess
import apscheduler.schedulers.background

import daemon_lib.ansiiprint as ansiiprint
import daemon_lib.zkhandler as zkhandler
import daemon_lib.common as common

class VXNetworkInstance():
    # Initialization function
    def __init__ (self, vni, zk_conn, config):
        self.vni = vni
        self.zk_conn = zk_conn
        self.vni_dev = config['vni_dev']

        self.old_description = zkhandler.readdata(self.zk_conn, '/networks/{}'.format(self.vni))
        self.description = zkhandler.readdata(self.zk_conn, '/networks/{}'.format(self.vni))
        self.ip_gateway = zkhandler.readdata(self.zk_conn, '/networks/{}/ip_gateway'.format(self.vni))
        self.ip_network = zkhandler.readdata(self.zk_conn, '/networks/{}/ip_network'.format(self.vni))
        self.ip_cidrnetmask = self.ip_network.split('/')[-1]
        self.dhcp_flag = ( zkhandler.readdata(self.zk_conn, '/networks/{}/dhcp_flag'.format(self.vni)) == 'True' )

        self.vxlan_nic = 'vxlan{}'.format(self.vni)
        self.bridge_nic = 'br{}'.format(self.vni)

        self.corosync_provisioned = False
        self.watch_change = False

        self.update_timer = apscheduler.schedulers.background.BackgroundScheduler()
        self.update_timer.add_job(self.updateCorosyncResource, 'interval', seconds=1)

        # Zookeper handlers for changed states
        @zk_conn.DataWatch('/networks/{}'.format(self.vni))
        def watch_network_description(data, stat, event=''):
            if self.description != data.decode('ascii'):
                self.old_description = self.description
                self.description = data.decode('ascii')
                self.watch_change = True

        @zk_conn.DataWatch('/networks/{}/ip_network'.format(self.vni))
        def watch_network_ip_network(data, stat, event=''):
            if self.ip_network != data.decode('ascii'):
                ip_network = data.decode('ascii')
                self.ip_network = ip_network
                self.ip_cidrnetmask = ip_network.split('/')[-1]
                self.watch_change = True

        @zk_conn.DataWatch('/networks/{}/ip_gateway'.format(self.vni))
        def watch_network_gateway(data, stat, event=''):
            if self.ip_gateway != data.decode('ascii'):
                self.ip_gateway = data.decode('ascii')
                self.watch_change = True

        @zk_conn.DataWatch('/networks/{}/dhcp_flag'.format(self.vni))
        def watch_network_dhcp_status(data, stat, event=''):
            if self.dhcp_flag != data.decode('ascii'):
                self.dhcp_flag = ( data.decode('ascii') == 'True' )
                self.watch_change = True

    def createCorosyncResource(self):
        ansiiprint.echo('Creating Corosync resource for network {} gateway {} on VNI {}'.format(self.description, self.ip_gateway, self.vni), '', 'o')
        common.run_os_command("""
            crm configure
            primitive vnivip_{} ocf:heartbeat:IPaddr2
            params ip={} cidr_netmask={} nic={}
            op monitor interval=1s
        """.format( self.description, self.ip_gateway, self.ip_cidrnetmask, self.bridge_nic))
        self.watch_change = False
        self.corosync_provisioned = True

    def removeCorosyncResource(self):
        ansiiprint.echo('Removing Corosync resource for network {} on VNI {}'.format(self.old_description, self.vni), '', 'o')
        common.run_os_command('crm resource stop vnivip_{}'.format(self.old_description))
        common.run_os_command('crm configure delete vnivip_{}'.format(self.old_description))
        self.corosync_provisioned = False

    def createNetwork(self):
        ansiiprint.echo('Creating VNI {} device on interface {}'.format(self.vni, self.vni_dev), '', 'o')
        common.run_os_command('ip link add {} type vxlan id {} dstport 4789 dev {}'.format(self.vxlan_nic, self.vni, self.vni_dev))
        common.run_os_command('brctl addbr {}'.format(self.bridge_nic))
        common.run_os_command('brctl addif {} {}'.format(self.bridge_nic, self.vxlan_nic))
        common.run_os_command('ip link set {} up'.format(self.vxlan_nic))
        common.run_os_command('ip link set {} up'.format(self.bridge_nic))

    def removeNetwork(self):
        ansiiprint.echo('Removing VNI {} device on interface {}'.format(self.vni, self.vni_dev), '', 'o')
        common.run_os_command('ip link set {} down'.format(self.bridge_nic))
        common.run_os_command('ip link set {} down'.format(self.vxlan_nic))
        common.run_os_command('brctl delif {} {}'.format(self.bridge_nic, self.vxlan_nic))
        common.run_os_command('brctl delbr {}'.format(self.bridge_nic))
        common.run_os_command('ip link delete {}'.format(self.vxlan_nic))

    def updateCorosyncResource(self):
        if self.corosync_provisioned and self.watch_change:
            self.watch_change = False
            # Rebuild the resource
            self.removeCorosyncResource()
            self.createCorosyncResource()

    def provision(self):
        self.update_timer.start()
        self.createNetwork()
        self.createCorosyncResource()

    def deprovision(self):
        self.update_timer.shutdown()
        self.removeCorosyncResource()
        self.removeNetwork()
