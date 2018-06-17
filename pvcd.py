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
import signal
import socket
import psutil
import subprocess
import uuid
import time
import configparser
import apscheduler.schedulers.background

import pvc.ansiiprint as ansiiprint
import pvc.VMInstance as VMInstance
import pvc.NodeInstance as NodeInstance

print(ansiiprint.bold() + "pvcd - Parallel Virtual Cluster management daemon" + ansiiprint.end())

# Get the config file variable from the environment
try:
    pvcd_config_file = os.environ['PVCD_CONFIG_FILE']
except:
    print('ERROR: The "PVCD_CONFIG_FILE" environment variable must be set before starting pvcd.')
    exit(1)

myhostname = socket.gethostname()
myshorthostname = myhostname.split('.', 1)[0]
mydomainname = ''.join(myhostname.split('.', 1)[1:])

# Config values dictionary
config_values = [
    'zookeeper',
    'keepalive_interval',
    'ipmi_hostname',
    'ipmi_username',
    'ipmi_password'
]
def readConfig(pvcd_config_file, myhostname):
    print('Loading configuration from file {}'.format(pvcd_config_file))

    o_config = configparser.ConfigParser()
    o_config.read(pvcd_config_file)
    config = {}

    try:
        entries = o_config[myhostname]
    except:
        try:
            entries = o_config['default']
        except Exception as e:
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

    # Handle an empty ipmi_hostname
    if config['ipmi_hostname'] == '':
        config['ipmi_hostname'] = myshorthostname + '-lom.' + mydomainname

    return config

config = {}

def getConfig():
    global config
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
    elif state == kazoo.client.KazooState.SUSPENDED:
        cleanup()
    else:
        pass

zk.add_listener(zk_listener)

def cleanup():
    update_timer.shutdown()
    zk.set('/nodes/{}/daemonstate'.format(myhostname), 'stop'.encode('ascii'))
    zk.stop()
    zk.close()
    sys.exit(0)

# Handle signals gracefully
signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGQUIT, cleanup)
signal.signal(signal.SIGHUP, getConfig)

# Gather useful data about our host for staticdata
# Static data format: 'cpu_count', 'arch', 'os', 'kernel'
staticdata = []
staticdata.append(str(psutil.cpu_count()))
staticdata.append(subprocess.run(['uname', '-r'], stdout=subprocess.PIPE).stdout.decode('ascii').strip())
staticdata.append(subprocess.run(['uname', '-o'], stdout=subprocess.PIPE).stdout.decode('ascii').strip())
staticdata.append(subprocess.run(['uname', '-m'], stdout=subprocess.PIPE).stdout.decode('ascii').strip())
# Print static data on start

print('{0}Node hostname:{1} {2}'.format(ansiiprint.bold(), ansiiprint.end(), myhostname))
print('{0}IPMI hostname:{1} {2}'.format(ansiiprint.bold(), ansiiprint.end(), config['ipmi_hostname']))
print('{0}Machine details:{1}'.format(ansiiprint.bold(), ansiiprint.end()))
print('  {0}CPUs:{1} {2}'.format(ansiiprint.bold(), ansiiprint.end(), staticdata[0]))
print('  {0}Arch:{1} {2}'.format(ansiiprint.bold(), ansiiprint.end(), staticdata[1]))
print('  {0}OS:{1} {2}'.format(ansiiprint.bold(), ansiiprint.end(), staticdata[2]))
print('  {0}Kernel:{1} {2}'.format(ansiiprint.bold(), ansiiprint.end(), staticdata[3]))

# Check if our node exists in Zookeeper, and create it if not
if zk.exists('/nodes/{}'.format(myhostname)):
    print("Node is " + ansiiprint.green() + "present" + ansiiprint.end() + " in Zookeeper")
    # Update static data just in case it's changed
    zk.set('/nodes/{}/staticdata'.format(myhostname), ' '.join(staticdata).encode('ascii'))
else:
    print("Node is " + ansiiprint.red() + "absent" + ansiiprint.end() + " in Zookeeper; adding new node")
    keepalive_time = int(time.time())
    zk.create('/nodes/{}'.format(myhostname), 'hypervisor'.encode('ascii'))
    # Basic state information
    zk.create('/nodes/{}/daemonstate'.format(myhostname), 'stop'.encode('ascii'))
    zk.create('/nodes/{}/domainstate'.format(myhostname), 'ready'.encode('ascii'))
    zk.create('/nodes/{}/staticdata'.format(myhostname), ' '.join(staticdata).encode('ascii'))
    zk.create('/nodes/{}/memfree'.format(myhostname), '0'.encode('ascii'))
    zk.create('/nodes/{}/memused'.format(myhostname), '0'.encode('ascii'))
    zk.create('/nodes/{}/cpuload'.format(myhostname), '0.0'.encode('ascii'))
    zk.create('/nodes/{}/runningdomains'.format(myhostname), ''.encode('ascii'))
    zk.create('/nodes/{}/domainscount'.format(myhostname), '0'.encode('ascii'))
    # Keepalives and fencing information
    zk.create('/nodes/{}/keepalive'.format(myhostname), str(keepalive_time).encode('ascii'))
    zk.create('/nodes/{}/ipmihostname'.format(myhostname), config['ipmi_hostname'].encode('ascii'))
    zk.create('/nodes/{}/ipmiusername'.format(myhostname), config['ipmi_username'].encode('ascii'))
    zk.create('/nodes/{}/ipmipassword'.format(myhostname), config['ipmi_password'].encode('ascii'))

zk.set('/nodes/{}/daemonstate'.format(myhostname), 'init'.encode('ascii'))

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
            t_node[node] = NodeInstance.NodeInstance(myhostname, node, t_node, s_domain, zk, config)

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
