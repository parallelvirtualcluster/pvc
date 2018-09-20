#!/usr/bin/env python3

# VXNetworkInstance.py - Class implementing a PVC VM network and run by pvcnd
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

class VXNetworkInstance():
    # Initialization function
    def __init__ (self, vni, zk_conn, config):
        self.vni = vni
        self.zk_conn = zk_conn
        self.vni_dev = config['vni_dev']

    def createNetwork(self):
        ansiiprint.echo('Creating VNI {} device on interface {}'.format(self.vni, self.vni_dev), '', 'o')
        os.system(
            'sudo ip link add vxlan{0} type vxlan id {0} dstport 4789 dev {1} nolearning'.format(
                self.vni,
                self.vni_dev
            )
        )
        os.system(
            'sudo brctl addbr br{0}'.format(
                self.vni
            )
        )
        os.system(
            'sudo brctl addif br{0} vxlan{0}'.format(
                self.vni
            )
        )
        os.system(
            'sudo ip link set vxlan{0} up'.format(
                self.vni
            )
        )
        os.system(
            'sudo ip link set br{0} up'.format(
                self.vni
            )
        )

    def removeNetwork(self):
        ansiiprint.echo('Removing VNI {} device on interface {}'.format(self.vni, self.vni_dev), '', 'o')
        os.system(
            'sudo ip link set br{0} down'.format(
                self.vni
            )
        )
        os.system(
            'sudo ip link set vxlan{0} down'.format(
                self.vni
            )
        )
        os.system(
            'sudo brctl delif br{0} vxlan{0}'.format(
                self.vni
            )
        )
        os.system(
            'sudo brctl delbr br{0}'.format(
                self.vni
            )
        )
        os.system(
            'sudo ip link delete vxlan{0}'.format(
                self.vni
            )
        )
