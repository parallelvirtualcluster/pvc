#!/usr/bin/env python3

from kazoo.client import KazooClient
from kazoo.client import KazooState
import libvirt
import sys
import uuid
import VMInstance
import time

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

# Connect to libvirt
libvirt_name = "qemu:///system"
conn = libvirt.open(libvirt_name)
if conn == None:
    print('Failed to open connection to %s' % libvirt_name)
    exit(1)

# Gather data about hypervisor
hostname = conn.getHostname()
nodeinfo = conn.getInfo()
numnodes = nodeinfo[4]
memlistNUMA = conn.getCellsFreeMemory(0, numnodes)
memlistTOTAL = conn.getFreeMemory()

print("Node hostname: %s" % hostname)
print("Free memory: %s" % memlistTOTAL)
cell = 0
for cellfreemem in memlistNUMA:
    print('NUMA Node '+str(cell)+': '+str(cellfreemem)+' bytes free memory')
    cell += 1

print('Virtualization type: '+conn.getType())
uri = conn.getURI()
print('Canonical URI: '+uri)

print()

map = conn.getCPUMap()

print("CPUs: " + str(map[0]))
print("Available: " + str(map[1]))


print()

def start_vm(vmname):
    print("Starting VM %s" % vmname)

vm = VMInstance.VMInstance('b1dc4e21-544f-47aa-9bb7-8af0bc443b78', zk, hostname);

while True:
    # Tick loop
    time.sleep(1)
    pass

conn.close()
zk.stop()
