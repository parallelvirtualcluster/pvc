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
        # Register somewhere that the session was lost
        pass
    elif state == KazooState.SUSPENDED:
        # Handle being disconnected from Zookeeper
        pass
    else:
        # Handle being connected/reconnected to Zookeeper
        pass

zk.add_listener(zk_listener)

def cleanup():
    t_node[socket.gethostname()].stop()
    zk.stop()

atexit.register(cleanup)

node_list = zk.get_children('/nodes')
print(node_list)

domain_list = zk.get_children('/domains')
print(domain_list)

t_node = dict()
s_domain = dict()

for node in node_list:
    t_node[node] = NodeInstance.NodeInstance(node, zk);
    t_node[node].start()

for domain in domain_list:
    s_domain[domain] = VMInstance.VMInstance(domain, zk, socket.gethostname());

while True:
    # Tick loop
    try:
        time.sleep(1)
    except:
        cleanup()
        exit(0)
