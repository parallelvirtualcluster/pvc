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
import socket
import uuid
import VMInstance
import NodeInstance
import time
import atexit
import apscheduler.schedulers.background

# ANSII colours for output
class bcolours:
    PURPLE = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def help():
    print(bcolours.BOLD + "pvcd - Parallel Virtual Cluster management daemon" + bcolours.ENDC)
#    exit(0)

help()

# Connect to local zookeeper
zk = kazoo.client.KazooClient(hosts='127.0.0.1:2181')
try:
    zk.start()
except:
    print(bcolours.RED + "Failed to connect to local Zookeeper instance" + bcolours.ENDC)
    exit(1)

def zk_listener(state):
    if state == kazoo.client.KazooState.LOST:
        cleanup()
        exit(2)
    elif state == kazoo.client.KazooState.SUSPENDED:
        cleanup()
        exit(2)
    else:
        pass

zk.add_listener(zk_listener)

myhostname = socket.gethostname()
mynodestring = '/nodes/%s' % myhostname

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
    print("> Node is " + bcolours.GREEN + "present" + bcolours.ENDC + " in Zookeeper.")
else:
    print("> Node is " + bcolours.RED + "absent" + bcolours.ENDC + " in Zookeeper; adding new node.")
    keepalive_time = int(time.time())
    zk.create('/domains/{}'.format(myhostname), 'hypervisor'.encode('ascii'))
    zk.create('/domains/{}/state'.format(myhostname), 'stop'.encode('ascii'))
    zk.create('/domains/{}/cpucount'.format(myhostname), '0'.encode('ascii'))
    zk.create('/domains/{}/memfree'.format(myhostname), '0'.encode('ascii'))
    zk.create('/domains/{}/cpuload'.format(myhostname), '0.0'.encode('ascii'))
    zk.create('/domains/{}/runningdomains'.format(myhostname), ''.encode('ascii'))
    zk.create('/domains/{}/keepalive'.format(myhostname), str(keepalive_time).encode('ascii'))

t_node = dict()
s_domain = dict()
node_list = []
domain_list = []

@zk.ChildrenWatch('/nodes')
def updatenodes(new_node_list):
    global node_list
    node_list = new_node_list
    print('Node list: ' + bcolours.BLUE + '{}'.format(' '.join(node_list)) + bcolours.ENDC)
    for node in node_list:
        if node in t_node:
            t_node[node].updatenodelist(t_node)
        else:
            t_node[node] = NodeInstance.NodeInstance(node, t_node, s_domain, zk)

@zk.ChildrenWatch('/domains')
def updatedomains(new_domain_list):
    global domain_list
    domain_list = new_domain_list
    print('Domain list: ' + bcolours.BLUE + '{}'.format(' '.join(domain_list)) + bcolours.ENDC)
    for domain in domain_list:
        if not domain in s_domain:
            s_domain[domain] = VMInstance.VMInstance(domain, zk, t_node[myhostname]);
            for node in node_list:
                if node in t_node:
                    t_node[node].updatedomainlist(s_domain)

# Set up our update function
this_node = t_node[myhostname]
update_zookeeper = this_node.update_zookeeper

# Create timer to update this node in Zookeeper
update_timer = apscheduler.schedulers.background.BackgroundScheduler()
update_timer.add_job(update_zookeeper, 'interval', seconds=5)
update_timer.start()

# Tick loop
while True:
    try:
        time.sleep(0.1)
    except:
        break
