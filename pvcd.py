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
mynodestring = '/nodes/%s' % myhostname

def cleanup():
    t_node[myhostname].stop()
    time.sleep(0.2)
    try:
        zk.set('/nodes/' + myhostname + '/state', 'stop'.encode('ascii'))
        zk.stop()
        zk.close()
    except:
        pass

atexit.register(cleanup)

# Check if our node exists in Zookeeper, and create it if not
if zk.exists('%s' % mynodestring):
    print("Node is present in Zookeeper")
else:
    zk.create('%s' % mynodestring, 'hypervisor'.encode('ascii'))
    zk.create('%s/state' % mynodestring, 'stop'.encode('ascii'))
    zk.create('%s/cpucount' % mynodestring, '0'.encode('ascii'))
    zk.create('%s/memfree' % mynodestring, '0'.encode('ascii'))
    zk.create('%s/cpuload' % mynodestring, '0.0'.encode('ascii'))
    zk.create('%s/runningdomains' % mynodestring, ''.encode('ascii'))

t_node = dict()
s_domain = dict()
node_list = []

@zk.ChildrenWatch('/nodes')
def updatenodes(new_node_list):
    node_list = new_node_list
    print('Node list: %s' % node_list)
    for node in node_list:
        if node in t_node:
            t_node[node].updatenodelist(node_list)
        else:
            t_node[node] = NodeInstance.NodeInstance(node, node_list, zk);
            if node == myhostname:
                t_node[node].start()
                time.sleep(0.5)

@zk.ChildrenWatch('/domains')
def updatedomains(new_domain_list):
    time.sleep(0.5)
    domain_list = new_domain_list
    print('Domain list: %s' % domain_list)
    for domain in domain_list:
        if not domain in s_domain:
            s_domain[domain] = VMInstance.VMInstance(domain, zk, t_node[myhostname]);

while True:
    # Tick loop
    try:
        time.sleep(0.1)
    except:
        cleanup()
        exit(0)
