#!/usr/bin/env python3

# Daemon.py - PVC hypervisor router daemon
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

import kazoo.client
import sys
import os
import signal
import socket
import psutil
import configparser
import time
import subprocess

import daemon_lib.ansiiprint as ansiiprint
import daemon_lib.zkhandler as zkhandler
import daemon_lib.common as common

import pvcrd.VXNetworkInstance as VXNetworkInstance

print(ansiiprint.bold() + "pvcrd - Parallel Virtual Cluster router daemon" + ansiiprint.end())

# Get the config file variable from the environment
try:
    pvcrd_config_file = os.environ['PVCRD_CONFIG_FILE']
except:
    print('ERROR: The "PVCRD_CONFIG_FILE" environment variable must be set before starting pvcrd.')
    exit(1)

myhostname = socket.gethostname()
myshorthostname = myhostname.split('.', 1)[0]
mydomainname = ''.join(myhostname.split('.', 1)[1:])

# Config values dictionary
config_values = [
    'zookeeper',
    'vni_dev',
    'vni_dev_ip',
]
def readConfig(pvcrd_config_file, myhostname):
    print('Loading configuration from file {}'.format(pvcrd_config_file))

    o_config = configparser.ConfigParser()
    o_config.read(pvcrd_config_file)
    config = {}

    try:
        entries = o_config[myhostname]
    except:
        try:
            entries = o_config['default']
        except:
            print('ERROR: Config file is not valid!')
            exit(1)

    for entry in config_values:
        try:
            config[entry] = entries[entry]
        except:
            try:
                config[entry] = o_config['default'][entry]
            except:
                print('ERROR: Config file missing required value "{}" for this host!'.format(entry))
                exit(1)

    return config

config = readConfig(pvcrd_config_file, myhostname)

zk_conn = kazoo.client.KazooClient(hosts=config['zookeeper'])
try:
    print('Connecting to Zookeeper instance at {}'.format(config['zookeeper']))
    zk_conn.start()
except:
    print('ERROR: Failed to connect to Zookeeper!')
    exit(1)

# Handle zookeeper failures gracefully
def zk_listener(state):
    global zk_conn
    if state == kazoo.client.KazooState.SUSPENDED:
        ansiiprint.echo('Connection to Zookeeper list; retrying', '', 'e')

        while True:
            _zk_conn = kazoo.client.KazooClient(hosts=config['zookeeper'])
            try:
                _zk_conn.start()
                zk_conn = _zk_conn
                break
            except:
                time.sleep(1)
    elif state == kazoo.client.KazooState.CONNECTED:
        ansiiprint.echo('Connection to Zookeeper started', '', 'o')
    else:
        pass

zk_conn.add_listener(zk_listener)

# Cleanup function
def cleanup(signum, frame):
    ansiiprint.echo('Terminating daemon', '', 'e')
    # Close the Zookeeper connection
    try:
        zk_conn.stop()
        zk_conn.close()
    except:
        pass
    # Exit
    exit(0)

# Handle signals with cleanup
signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGQUIT, cleanup)

# What this daemon does:
#  1. Configure public networks dynamically on startup (e.g. bonding, vlans, etc.) from config
#   * no /etc/network/interfaces config for these - just mgmt interface via DHCP!
#  2. Watch ZK /networks
#  3. Provision required network interfaces when a network is added
#   a. create vxlan interface targeting local dev from config
#   b. create bridge interface
#   c. add vxlan to bridge
#   d. set interfaces up
#   e. add corosync config for virtual gateway IP
#  4. Remove network interfaces when network disapears

# Zookeeper schema:
#   networks/
#       <VXLANID>/
#           ipnet <NETWORK-CIDR>  e.g. 10.101.0.0/24
#           gateway <IPADDR>      e.g. 10.101.0.1 [1]
#           dhcp <YES/NO>         e.g. YES [2]
#           reservations/
#               <HOSTNAME/DESCRIPTION>/
#                   address <IPADDR> e.g. 10.101.0.30
#                   mac <MACADDR>    e.g. ff:ff:fe:ab:cd:ef
#           fwrules/
#               <RULENAME>/
#                   description <DESCRIPTION>                  e.g. Allow HTTP from any to this net
#                   src <HOSTNAME/IPADDR/SUBNET/"any"/"this">  e.g. any
#                   dest <HOSTNAME/IPADDR/SUBNET/"any"/"this"> e.g. this
#                   port <PORT/RANGE/"any">                    e.g. 80

# Notes:          
# [1] becomes a VIP between the pair of routers in multi-router envs
# [2] enables or disables a DHCP subnet definition for the network


# Enable routing
common.run_os_command('sysctl sysctl net.ipv4.ip_forward=1')
common.run_os_command('sysctl sysctl net.ipv6.ip_forward=1')
common.run_os_command('sysctl sysctl net.ipv4.all.send_redirects=1')
common.run_os_command('sysctl sysctl net.ipv6.all.send_redirects=1')
common.run_os_command('sysctl sysctl net.ipv4.all.accept_source_route=1')
common.run_os_command('sysctl sysctl net.ipv6.all.accept_source_route=1')

# Prepare underlying interface
if config['vni_dev_ip'] == 'dhcp':
    vni_dev = config['vni_dev']
    ansiiprint.echo('Configuring VNI parent device {} with DHCP IP'.format(vni_dev), '', 'o')
    common.run_os_command('ip link set {0} up'.format(vni_dev))
    common.run_os_command('dhclient {0}'.format(vni_dev))
else:
    vni_dev = config['vni_dev']
    vni_dev_ip = config['vni_dev_ip']
    ansiiprint.echo('Configuring VNI parent device {} with IP {}'.format(vni_dev, vni_dev_ip), '', 'o')
    common.run_os_command('ip link set {0} up'.format(vni_dev))
    common.run_os_command('ip address add {0} dev {1}'.format(vni_dev_ip, vni_dev))

# Disable stonith in corosync
common.run_os_command('crm configure property stonith-enabled="false"')

# Prepare VNI list
t_vni = dict()
vni_list = []

@zk_conn.ChildrenWatch('/networks')
def updatenetworks(new_vni_list):
    global vni_list
    print(ansiiprint.blue() + 'Network list: ' + ansiiprint.end() + '{}'.format(' '.join(new_vni_list)))
    # Add new VNIs
    for vni in new_vni_list:
        if vni not in vni_list:
            vni_list.append(vni)
            t_vni[vni] = VXNetworkInstance.VXNetworkInstance(vni, zk_conn, config)
            t_vni[vni].provision()

    # Remove deleted VNIs
    for vni in vni_list:
        if vni not in new_vni_list:
            vni_list.remove(vni)
            t_vni[vni].deprovision()
            
# Tick loop
while True:
    try:
        time.sleep(0.1)
    except:
        break
