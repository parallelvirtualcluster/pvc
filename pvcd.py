#!/usr/bin/env python3

from kazoo.client import KazooClient
from kazoo.client import KazooState
import libvirt
import sys
import socket
import uuid
import VMInstance
import NodeInstance
import time
import threading
import atexit

def help():
    print("pvcd - Parallel Virtual Cluster management daemon")
#    exit(0)

help()

# Connect to zookeeper
zk = KazooClient(hosts='127.0.0.1:2181')
try:
    zk.start()
except:
    print("Failed to connect to local Zookeeper instance")
    exit(1)

def zk_listener(state):
    if state == KazooState.LOST:
        cleanup()
        exit(2)
    elif state == KazooState.SUSPENDED:
        cleanup()
        exit(2)
    else:
        # Handle being connected/reconnected to Zookeeper
        pass

zk.add_listener(zk_listener)

myhostname = socket.gethostname()

def cleanup():
    for node in node_list:
        t_node[node].stop()
    zk.stop()

atexit.register(cleanup)

# Check if our node exists in Zookeeper, and create it if not
mynodestring = '/nodes/%s' % myhostname
if not zk.exists('%s' + mynodestring):
    zk.create('%s' % mynodestring, 'hypervisor'.encode('ascii'))
    zk.create('%s/state' % mynodestring, 'stop'.encode('ascii'))
    zk.create('%s/cpucount' % mynodestring, '0'.encode('ascii'))
    zk.create('%s/memfree' % mynodestring, '0'.encode('ascii'))
    zk.create('%s/cpuload' % mynodestring, '0.0'.encode('ascii'))

time.sleep(1)

def updatenodes():
    node_list = zk.get_children('/nodes')
    print(node_list)
    for node in node_list:
        if t_node[node] is None:
            t_node[node] = NodeInstance.NodeInstance(node, node_list, zk);
        else:
            t_node[node].updatenodelist(node_list)

node_list = zk.get_children('/nodes')

domain_list = zk.get_children('/domains')
print(domain_list)

t_node = dict()
s_domain = dict()

time.sleep(1)

for domain in domain_list:
    s_domain[domain] = VMInstance.VMInstance(domain, zk, t_node[myhostname]);

while True:
    # Tick loop
    try:
        time.sleep(0.1)
    except:
        cleanup()
        exit(0)
