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
import apscheduler

import daemon_lib.ansiiprint as ansiiprint
import daemon_lib.zkhandler as zkhandler

class VXNetworkInstance():
    # Initialization function
    def __init__ (self, vni, zk_conn, config):
        self.vni = vni
        self.zk_conn = zk_conn
        self.vni_dev = config['vni_dev']

        self.vxlan_nic = 'vxlan{}'.format(self.vni)
        self.bridge_nic = 'br{}'.format(self.vni)

        self.corosync_provisioned = False
        self.watch_change = False

        self.update_timer = apscheduler.schedulers.background.BackgroundScheduler()
        self.update_timer.add_job(updateCorosyncResource, 'interval', seconds=1)

        # Zookeper handlers for changed states
        @zk_conn.DataWatch('/networks/{}/description'.format(self.vni))
        def watch_network_description(data, stat, event=''):
            try:
                self.description = data.decode('ascii')
            except AttributeError:
                self.description = self.vni

            self.watch_change = True

        @zk_conn.DataWatch('/networks/{}/ip_network'.format(self.vni))
        def watch_network_ip_network(data, stat, event=''):
            try:
                ip_network = data.decode('ascii')
                self.ip_network = ip_network
                self.ip_cidrnetmask = ip_network.split('/')[-1]
            except AttributeError:
                self.ip_network = ''
                self.ip_cidrnetmask = ''

            self.watch_change = True

        @zk_conn.DataWatch('/networks/{}/ip_gateway'.format(self.vni))
        def watch_network_gateway(data, stat, event=''):
            try:
                self.ip_gateway = data.decode('ascii')
            except AttributeError:
                self.ip_gateway = ''

            self.watch_change = True

        @zk_conn.DataWatch('/networks/{}/dhcp_flag'.format(self.vni))
        def watch_network_dhcp_status(data, stat, event=''):
            try:
                dhcp_flag = data.decode('ascii')
                self.dhcp_flag = ( dhcp_flag == 'True' )
            except AttributeError:
                self.dhcp_flag = False

            self.watch_change = True

    def createCorosyncResource(self):
        self.corosync_provisioned = True
        ansiiprint.echo('Creating Corosync resource for gateway {} on interface {}'.format(self.ip_gateway, self.vni), '', 'o')
        os.system(
            'echo \"
                configure
                    primitive vnivip_{0} ocf:heartbeat:IPaddr2 params ip={1} cidr_netmask={2} nic={3} op monitor interval=1s
                    commit
                    up
                resource
                    start vnivip_{0}
            \" | crm -f -'.format(
                self.description,
                self.ip_gateway,
                self.ip_cidrnetmask
                self.bridge_nic
            )
        )

    def removeCorosyncResource(self):
        ansiiprint.echo('Removing Corosync resource for gateway {} on interface {}'.format(self.ip_gateway, self.vni), '', 'o')
        os.system(
            'echo \"
                resource
                    stop vnivip_{0}
                    up
                configure
                    delete vnivip_{0}
                    commit
            \" | crm -f -'.format(
                self.description
            )
        )
        self.corosync_provisioned = False

    def createNetwork(self):
        ansiiprint.echo('Creating VNI {} device on interface {}'.format(self.vni, self.vni_dev), '', 'o')
        os.system(
            'ip link add {0} type vxlan id {1} dstport 4789 dev {2}'.format(
                self.vxlan_nic,
                self.vni,
                self.vni_dev
            )
        )
        os.system(
            'brctl addbr {0}'.format(
                self.bridge_nic
            )
        )
        os.system(
            'brctl addif {0} {1}'.format(
                self.bridge_nic
                self.vxlan_nic
            )
        )
        os.system(
            'ip link set {0} up'.format(
                self.vxlan_nic
            )
        )
        os.system(
            'ip link set {0} up'.format(
                self.bridge_nic
            )
        )

    def removeNetwork(self):
        ansiiprint.echo('Removing VNI {} device on interface {}'.format(self.vni, self.vni_dev), '', 'o')
        os.system(
            'ip link set {0} down'.format(
                self.bridge_nic
            )
        )
        os.system(
            'ip link set {0} down'.format(
                self.vxlan_nic
            )
        )
        os.system(
            'brctl delif {0} {1}'.format(
                self.bridge_nic,
                self.vxlan_nic
            )
        )
        os.system(
            'brctl delbr {0}'.format(
                self.bridge_nic
            )
        )
        os.system(
            'ip link delete {0}'.format(
                self.vxlan_nic
            )
        )

    def updateCorosyncResource(self):
        if self.corosync_provisioned and self.watch_change:
            # Rebuild the resource
            removeCorosyncResource()
            createCorosyncResource()

    def provision(self):
        createNetwork()
        createCorosyncConfig()
        self.update_timer.start()

    def deprovision(self):
        self.update_timer.shutdown()
        removeCorosyncConfig()
