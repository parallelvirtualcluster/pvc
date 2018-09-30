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

import daemon_lib.ansiiprint as ansiiprint
import daemon_lib.zkhandler as zkhandler
import daemon_lib.common as common

import pvcrd.DHCPServer as DHCPServer

class VXNetworkInstance():
    # Initialization function
    def __init__ (self, vni, zk_conn, config, this_router):
        self.vni = vni
        self.zk_conn = zk_conn
        self.this_router = this_router
        self.vni_dev = config['vni_dev']

        self.old_description = zkhandler.readdata(self.zk_conn, '/networks/{}'.format(self.vni))
        self.description = zkhandler.readdata(self.zk_conn, '/networks/{}'.format(self.vni))
        self.domain = zkhandler.readdata(self.zk_conn, '/networks/{}/domain'.format(self.vni))
        self.ip_gateway = zkhandler.readdata(self.zk_conn, '/networks/{}/ip_gateway'.format(self.vni))
        self.ip_network = zkhandler.readdata(self.zk_conn, '/networks/{}/ip_network'.format(self.vni))
        self.ip_cidrnetmask = self.ip_network.split('/')[-1]
        self.dhcp_flag = ( zkhandler.readdata(self.zk_conn, '/networks/{}/dhcp_flag'.format(self.vni)) == 'True' )

        self.vxlan_nic = 'vxlan{}'.format(self.vni)
        self.bridge_nic = 'br{}'.format(self.vni)

        self.dhcp_reservations = {}
        self.firewall_rules = {}

        self.createNetwork()

        # Zookeper handlers for changed states
        @zk_conn.DataWatch('/networks/{}'.format(self.vni))
        def watch_network_description(data, stat, event=''):
            if data != None and self.description != data.decode('ascii'):
                self.old_description = self.description
                self.description = data.decode('ascii')

        @zk_conn.DataWatch('/networks/{}/ip_network'.format(self.vni))
        def watch_network_ip_network(data, stat, event=''):
            if data != None and self.ip_network != data.decode('ascii'):
                ip_network = data.decode('ascii')
                self.ip_network = ip_network
                self.ip_cidrnetmask = ip_network.split('/')[-1]

        @zk_conn.DataWatch('/networks/{}/ip_gateway'.format(self.vni))
        def watch_network_gateway(data, stat, event=''):
            if data != None and self.ip_gateway != data.decode('ascii'):
                self.removeAddress()
                self.ip_gateway = data.decode('ascii')
                self.addAddress()

        @zk_conn.DataWatch('/networks/{}/dhcp_flag'.format(self.vni))
        def watch_network_dhcp_status(data, stat, event=''):
            if data != None and self.dhcp_flag != data.decode('ascii'):
                self.dhcp_flag = ( data.decode('ascii') == 'True' )
                if self.dhcp_flag:
                    self.dhcp_instance = DHCPServer.DHCPServer(self.vni, self.config)
                else:
                    self.dhcp_instance.remove()
                    self.dhcp_instance = None


        @zk_conn.ChildrenWatch('/networks/{}/dhcp_reservations'.format(self.vni))
        def watch_network_dhcp_reservations(data, event=''):
            print(data)

    def getvni(self):
        return self.vni

    def createNetwork(self):
        ansiiprint.echo(
            'Creating VNI {} device on interface {}'.format(
                self.vni,
                self.vni_dev
            ),
            '',
            'o'
        )
        common.run_os_command(
            'ip link add {} type vxlan id {} dstport 4789 dev {}'.format(
                self.vxlan_nic,
                self.vni,
                self.vni_dev
            )
        )
        common.run_os_command(
            'brctl addbr {}'.format(
                self.bridge_nic
            )
        )
        common.run_os_command(
            'brctl addif {} {}'.format(
                self.bridge_nic,
                self.vxlan_nic
            )
        )
        common.run_os_command(
            'ip link set {} up'.format(
                self.vxlan_nic
            )
        )
        common.run_os_command(
            'ip link set {} up'.format(
                self.bridge_nic
            )
        )

    def createGatewayAddress(self):
        if self.this_router.getnetworkstate() == 'primary':
            ansiiprint.echo(
                'Creating gateway {} on interface {} (VNI {})'.format(
                    self.ip_gateway,
                    self.bridge_nic,
                    self.vni
                ),
                '',
                'o'
            )
            common.run_os_command(
                'ip address add {}/{} dev {}'.format(
                    self.ip_gateway,
                    self.ip_cidrnetmask,
                    self.bridge_nic
                )
            )
            common.run_os_command(
                'arping -A -c2 -I {} {}'.format(
                    self.bridge_nic,
                    self.ip_gateway
                ),
                background=True
            )

    def startDHCPServer(self):
        if self.this_router.getnetworkstate() == 'primary':
            ansiiprint.echo(
                'Starting DHCP server on interface {} (VNI {})'.format(
                    self.bridge_nic,
                    self.vni
                ),
                '',
                'o'
            )
            dhcp_configuration = DHCPServerConfiguration(
                zk_conn=self.zk_conn,
                ipaddr=self.ip_gateway,
                iface=self.bridge_nic,
                vni=self.vni,
                network=self.ip_network,
                router=[self.ip_gateway],
                dns_servers=[self.ip_gateway]
            )
            dhcp_configuration.debug = print
            self.dhcp_server = DHCPServer.DHCPServer(dhcp_configuration)
            self.dhcp_server.start()

    def removeNetwork(self):
        ansiiprint.echo(
            'Removing VNI {} device on interface {}'.format(
                self.vni,
                self.vni_dev
            ),
            '',
            'o'
        )
        common.run_os_command(
            'ip link set {} down'.format(
                self.bridge_nic
            )
        )
        common.run_os_command(
            'ip link set {} down'.format(
                self.vxlan_nic
            )
        )
        common.run_os_command(
            'brctl delif {} {}'.format(
                self.bridge_nic,
                self.vxlan_nic
            )
        )
        common.run_os_command(
            'brctl delbr {}'.format(
                self.bridge_nic
            )
        )
        common.run_os_command(
            'ip link delete {}'.format(
                self.vxlan_nic
            )
        )

    def removeGatewayAddress(self):
        ansiiprint.echo(
            'Removing gateway {} from interface {} (VNI {})'.format(
                self.ip_gateway,
                self.bridge_nic,
                self.vni
            ),
            '',
            'o'
        )
        common.run_os_command(
            'ip address delete {}/{} dev {}'.format(
                self.ip_gateway,
                self.ip_cidrnetmask,
                self.bridge_nic
            )
        )

    def stopDHCPServer(self):
        self.dhcp_server.close()
