#!/usr/bin/env python3

# Daemon.py - PVC hypervisor virtualization daemon
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

import lib.ansiiprint as ansiiprint
import lib.zkhandler as zkhandler

import pvcvd.VMInstance as VMInstance
import pvcvd.NodeInstance as NodeInstance

print(ansiiprint.bold() + "pvcvd - Parallel Virtual Cluster virtualization daemon" + ansiiprint.end())

# Get the config file variable from the environment
try:
    pvcvd_config_file = os.environ['PVCVD_CONFIG_FILE']
except:
    print('ERROR: The "PVCVD_CONFIG_FILE" environment variable must be set before starting pvcvd.')
    exit(1)

myhostname = socket.gethostname()
myshorthostname = myhostname.split('.', 1)[0]
mydomainname = ''.join(myhostname.split('.', 1)[1:])

# Config values dictionary
config_values = [
    'zookeeper',
    'keepalive_interval',
    'fence_intervals',
    'suicide_intervals',
    'successful_fence',
    'failed_fence',
    'migration_target_selector',
    'ipmi_hostname',
    'ipmi_username',
    'ipmi_password'
]
def readConfig(pvcvd_config_file, myhostname):
    print('Loading configuration from file {}'.format(pvcvd_config_file))

    o_config = configparser.ConfigParser()
    o_config.read(pvcvd_config_file)
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

# Get config
config = readConfig(pvcvd_config_file, myhostname)

# Check that libvirtd is listening TCP
libvirt_check_name = "qemu+tcp://127.0.0.1:16509/system"
try:
    print('Connecting to Libvirt instance at {}'.format(libvirt_check_name))
    lv_conn = libvirt.open(libvirt_check_name)
    if lv_conn == None:
        raise
except:
    print('ERROR: Failed to open local libvirt connection via TCP; required for PVC!')
    exit(1)
lv_conn.close()

# Connect to local zookeeper
zk_conn = kazoo.client.KazooClient(hosts=config['zookeeper'])
try:
    print('Connecting to Zookeeper instance at {}'.format(config['zookeeper']))
    zk_conn.start()
except:
    print('ERROR: Failed to connect to Zookeeper')
    exit(1)

# Handle zookeeper failures
def zk_listener(state):
    global zk_conn, update_timer
    if state == kazoo.client.KazooState.SUSPENDED:
        ansiiprint.echo('Connection to Zookeeper lost; retrying', '', 'e')

        # Stop keepalive thread
        stopKeepaliveTimer(update_timer)

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

        # Start keepalive thread
        update_timer = createKeepaliveTimer()
    else:
        pass

zk_conn.add_listener(zk_listener)

# Cleanup function
def cleanup(signum, frame):
    ansiiprint.echo('Terminating daemon', '', 'e')
    # Set stop state in Zookeeper
    zkhandler.writedata(zk_conn, { '/nodes/{}/daemonstate'.format(myhostname): 'stop' })
    # Close the Zookeeper connection
    try:
        zk_conn.stop()
        zk_conn.close()
    except:
        pass
    # Stop keepalive thread
    stopKeepaliveTimer(update_timer)
    # Exit
    sys.exit(0)

# Handle signals gracefully
signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGQUIT, cleanup)

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
print('  {0}Arch:{1} {2}'.format(ansiiprint.bold(), ansiiprint.end(), staticdata[3]))
print('  {0}OS:{1} {2}'.format(ansiiprint.bold(), ansiiprint.end(), staticdata[2]))
print('  {0}Kernel:{1} {2}'.format(ansiiprint.bold(), ansiiprint.end(), staticdata[1]))

# Check if our node exists in Zookeeper, and create it if not
if zk_conn.exists('/nodes/{}'.format(myhostname)):
    print("Node is " + ansiiprint.green() + "present" + ansiiprint.end() + " in Zookeeper")
    # Update static data just in case it's changed
    zkhandler.writedata(zk_conn, { '/nodes/{}/staticdata'.format(myhostname): ' '.join(staticdata) })
else:
    print("Node is " + ansiiprint.red() + "absent" + ansiiprint.end() + " in Zookeeper; adding new node")
    keepalive_time = int(time.time())
    transaction = zk_conn.transaction()
    transaction.create('/nodes/{}'.format(myhostname), 'hypervisor'.encode('ascii'))
    # Basic state information
    transaction.create('/nodes/{}/daemonstate'.format(myhostname), 'stop'.encode('ascii'))
    transaction.create('/nodes/{}/domainstate'.format(myhostname), 'ready'.encode('ascii'))
    transaction.create('/nodes/{}/staticdata'.format(myhostname), ' '.join(staticdata).encode('ascii'))
    transaction.create('/nodes/{}/memfree'.format(myhostname), '0'.encode('ascii'))
    transaction.create('/nodes/{}/memused'.format(myhostname), '0'.encode('ascii'))
    transaction.create('/nodes/{}/memalloc'.format(myhostname), '0'.encode('ascii'))
    transaction.create('/nodes/{}/vcpualloc'.format(myhostname), '0'.encode('ascii'))
    transaction.create('/nodes/{}/cpuload'.format(myhostname), '0.0'.encode('ascii'))
    transaction.create('/nodes/{}/runningdomains'.format(myhostname), ''.encode('ascii'))
    transaction.create('/nodes/{}/domainscount'.format(myhostname), '0'.encode('ascii'))
    # Keepalives and fencing information
    transaction.create('/nodes/{}/keepalive'.format(myhostname), str(keepalive_time).encode('ascii'))
    transaction.create('/nodes/{}/ipmihostname'.format(myhostname), config['ipmi_hostname'].encode('ascii'))
    transaction.create('/nodes/{}/ipmiusername'.format(myhostname), config['ipmi_username'].encode('ascii'))
    transaction.create('/nodes/{}/ipmipassword'.format(myhostname), config['ipmi_password'].encode('ascii'))
    transaction.commit()

zkhandler.writedata(zk_conn, { '/nodes/{}/daemonstate'.format(myhostname): 'init' })

t_node = dict()
s_domain = dict()
node_list = []
domain_list = []

@zk_conn.ChildrenWatch('/nodes')
def updatenodes(new_node_list):
    global node_list
    node_list = new_node_list
    print(ansiiprint.blue() + 'Node list: ' + ansiiprint.end() + '{}'.format(' '.join(node_list)))
    for node in node_list:
        if node in t_node:
            t_node[node].updatenodelist(t_node)
        else:
            t_node[node] = NodeInstance.NodeInstance(myhostname, node, t_node, s_domain, zk_conn, config)

@zk_conn.ChildrenWatch('/domains')
def updatedomains(new_domain_list):
    global domain_list
    domain_list = new_domain_list
    print(ansiiprint.blue() + 'Domain list: ' + ansiiprint.end() + '{}'.format(' '.join(domain_list)))
    for domain in domain_list:
        if not domain in s_domain:
            s_domain[domain] = VMInstance.VMInstance(domain, zk_conn, config, t_node[myhostname]);
            for node in node_list:
                if node in t_node:
                    t_node[node].updatedomainlist(s_domain)

# Set up our update function
this_node = t_node[myhostname]
update_zookeeper = this_node.update_zookeeper

# Create timer to update this node in Zookeeper
def createKeepaliveTimer():
    interval = int(config['keepalive_interval'])
    ansiiprint.echo('Starting keepalive timer ({} second interval)'.format(interval), '', 'o')
    update_timer = apscheduler.schedulers.background.BackgroundScheduler()
    update_timer.add_job(update_zookeeper, 'interval', seconds=interval)
    update_timer.start()
    return update_timer

def stopKeepaliveTimer(update_timer):
    ansiiprint.echo('Stopping keepalive timer', '', 'c')
    update_timer.shutdown()

# Start keepalive thread
update_timer = createKeepaliveTimer()

# Tick loop
while True:
    try:
        time.sleep(0.1)
    except:
        break
