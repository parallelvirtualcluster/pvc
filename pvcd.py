#!/usr/bin/env python3

# pvcd.py - PVC hypervisor node daemon
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
import libvirt
import sys
import os
import socket
import uuid
import VMInstance
import NodeInstance
import time
import atexit
import configparser
import apscheduler.schedulers.background
import fencenode
import ansiiprint

print(ansiiprint.bold() + "pvcd - Parallel Virtual Cluster management daemon" + ansiiprint.end())

# Get the config file variable from the environment
try:
    pvcd_config_file = os.environ['PVC_CONFIG_FILE']
except:
    print('ERROR: The "PVC_CONFIG_FILE" environment variable must be set before starting pvcd.')
    exit(1)

print('Loading configuration from file {}'.format(pvcd_config_file))

def readConfig(pvcd_config_file, myhostname):
    o_config = configparser.ConfigParser()
    o_config.read(pvcd_config_file)
    entries = o_config[myhostname]
    config = {}
    for entry in entries:
        config[entry] = entries[entry]
    return config

myhostname = socket.gethostname()
config = readConfig(pvcd_config_file, myhostname)

# Connect to local zookeeper
zk = kazoo.client.KazooClient(hosts=config['zookeeper'])
try:
    print('Connecting to Zookeeper instance at {}'.format(config['zookeeper']))
    zk.start()
except:
    print('ERROR: Failed to connect to Zookeeper')
    exit(1)

def zk_listener(state):
    if state == kazoo.client.KazooState.LOST:
        cleanup()
        exit(1)
    elif state == kazoo.client.KazooState.SUSPENDED:
        cleanup()
        exit(1)
    else:
        pass

zk.add_listener(zk_listener)

def cleanup():
    try:
        update_timer.shutdown()
        if t_node[myhostname].getstate() != 'flush':
            zk.set('/nodes/{}/state'.format(myhostname), 'stop'.encode('ascii'))
        zk.stop()
        zk.close()
    except:
        pass

atexit.register(cleanup)

# Check if our node exists in Zookeeper, and create it if not
if zk.exists('/nodes/{}'.format(myhostname)):
    print("Node is " + ansiiprint.green() + "present" + ansiiprint.end() + " in Zookeeper")
else:
    print("Node is " + ansiiprint.red() + "absent" + ansiiprint.end() + " in Zookeeper; adding new node")
    keepalive_time = int(time.time())
    zk.create('/domains/{}'.format(myhostname), 'hypervisor'.encode('ascii'))
    # Basic state information
    zk.create('/domains/{}/state'.format(myhostname), 'stop'.encode('ascii'))
    zk.create('/domains/{}/cpucount'.format(myhostname), '0'.encode('ascii'))
    zk.create('/domains/{}/memfree'.format(myhostname), '0'.encode('ascii'))
    zk.create('/domains/{}/cpuload'.format(myhostname), '0.0'.encode('ascii'))
    zk.create('/domains/{}/runningdomains'.format(myhostname), ''.encode('ascii'))
    # Keepalives and fencing information
    zk.create('/domains/{}/keepalive'.format(myhostname), str(keepalive_time).encode('ascii'))
    zk.create('/domains/{}/ipmihostname'.format(config['ipmi_hostname']), ''.encode('ascii'))
    zk.create('/domains/{}/ipmiusername'.format(config['ipmi_username']), ''.encode('ascii'))
    zk.create('/domains/{}/ipmipassword'.format(config['ipmi_password']), ''.encode('ascii'))

t_node = dict()
s_domain = dict()
node_list = []
domain_list = []

@zk.ChildrenWatch('/nodes')
def updatenodes(new_node_list):
    global node_list
    node_list = new_node_list
    print(ansiiprint.blue() + 'Node list: ' + ansiiprint.end() + '{}'.format(' '.join(node_list)))
    for node in node_list:
        if node in t_node:
            t_node[node].updatenodelist(t_node)
        else:
            t_node[node] = NodeInstance.NodeInstance(node, t_node, s_domain, zk, config)

@zk.ChildrenWatch('/domains')
def updatedomains(new_domain_list):
    global domain_list
    domain_list = new_domain_list
    print(ansiiprint.blue() + 'Domain list: ' + ansiiprint.end() + '{}'.format(' '.join(domain_list)))
    for domain in domain_list:
        if not domain in s_domain:
            s_domain[domain] = VMInstance.VMInstance(domain, zk, config, t_node[myhostname]);
            for node in node_list:
                if node in t_node:
                    t_node[node].updatedomainlist(s_domain)

# Set up our update function
this_node = t_node[myhostname]
update_zookeeper = this_node.update_zookeeper

# Create timer to update this node in Zookeeper
update_timer = apscheduler.schedulers.background.BackgroundScheduler()
update_timer.add_job(update_zookeeper, 'interval', seconds=int(config['keepalive_interval']))
update_timer.start()

# Tick loop
while True:
    try:
        time.sleep(0.1)
    except:
        break
