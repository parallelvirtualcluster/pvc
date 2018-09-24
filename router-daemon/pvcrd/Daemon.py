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
import subprocess
import time
import configparser
import apscheduler.schedulers.background

import daemon_lib.ansiiprint as ansiiprint
import daemon_lib.zkhandler as zkhandler
import daemon_lib.common as common

import pvcrd.RouterInstance as RouterInstance
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
mynetworkname = ''.join(myhostname.split('.', 1)[1:])

# Config values dictionary
config_values = [
    'zookeeper',
    'keepalive_interval',
    'keepalive_interval',
    'fence_intervals',
    'vni_dev',
    'vni_dev_ip',
    'ipmi_hostname',
    'ipmi_username',
    'ipmi_password'
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
        config['ipmi_hostname'] = myshorthostname + '-lom.' + mynetworkname

    return config

# Get config
config = readConfig(pvcrd_config_file, myhostname)

# Set up our VNI interface
vni_dev = config['vni_dev']
vni_dev_ip = config['vni_dev_ip']
print('Setting up VNI interface {} with IP {}'.format(vni_dev, vni_dev_ip)
common.run_os_command('ip link set {} up'.format(vni_dev))
common.run_os_command('ip address add {} dev {}'.format(vni_dev_ip, vni_dev))

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
    zkhandler.writedata(zk_conn, { '/routers/{}/daemonstate'.format(myhostname): 'stop' })
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

print('{0}Router hostname:{1} {2}'.format(ansiiprint.bold(), ansiiprint.end(), myhostname))
print('{0}IPMI hostname:{1} {2}'.format(ansiiprint.bold(), ansiiprint.end(), config['ipmi_hostname']))
print('{0}Machine details:{1}'.format(ansiiprint.bold(), ansiiprint.end()))
print('  {0}CPUs:{1} {2}'.format(ansiiprint.bold(), ansiiprint.end(), staticdata[0]))
print('  {0}Arch:{1} {2}'.format(ansiiprint.bold(), ansiiprint.end(), staticdata[3]))
print('  {0}OS:{1} {2}'.format(ansiiprint.bold(), ansiiprint.end(), staticdata[2]))
print('  {0}Kernel:{1} {2}'.format(ansiiprint.bold(), ansiiprint.end(), staticdata[1]))

# Check if our router exists in Zookeeper, and create it if not
if zk_conn.exists('/routers/{}'.format(myhostname)):
    print("Router is " + ansiiprint.green() + "present" + ansiiprint.end() + " in Zookeeper")
    # Update static data just in case it's changed
    zkhandler.writedata(zk_conn, { '/routers/{}/staticdata'.format(myhostname): ' '.join(staticdata) })
else:
    print("Router is " + ansiiprint.red() + "absent" + ansiiprint.end() + " in Zookeeper; adding new router")
    keepalive_time = int(time.time())
    transaction = zk_conn.transaction()
    transaction.create('/routers/{}'.format(myhostname), 'hypervisor'.encode('ascii'))
    # Basic state information
    transaction.create('/routers/{}/daemonstate'.format(myhostname), 'stop'.encode('ascii'))
    transaction.create('/routers/{}/networkstate'.format(myhostname), 'secondary'.encode('ascii'))
    transaction.create('/routers/{}/staticdata'.format(myhostname), ' '.join(staticdata).encode('ascii'))
    # Keepalives and fencing information
    transaction.create('/routers/{}/keepalive'.format(myhostname), str(keepalive_time).encode('ascii'))
    transaction.create('/routers/{}/ipmihostname'.format(myhostname), config['ipmi_hostname'].encode('ascii'))
    transaction.create('/routers/{}/ipmiusername'.format(myhostname), config['ipmi_username'].encode('ascii'))
    transaction.create('/routers/{}/ipmipassword'.format(myhostname), config['ipmi_password'].encode('ascii'))
    transaction.commit()

zkhandler.writedata(zk_conn, { '/routers/{}/daemonstate'.format(myhostname): 'init' })

t_router = dict()
s_network = dict()
router_list = []
network_list = []

@zk_conn.ChildrenWatch('/routers')
def updaterouters(new_router_list):
    global router_list
    router_list = new_router_list
    print(ansiiprint.blue() + 'Router list: ' + ansiiprint.end() + '{}'.format(' '.join(router_list)))
    for router in router_list:
        if router in t_router:
            t_router[router].updaterouterlist(t_router)
        else:
            t_router[router] = RouterInstance.RouterInstance(myhostname, router, t_router, s_network, zk_conn, config)

# Set up our update function
this_router = t_router[myhostname]
update_zookeeper = this_router.update_zookeeper
update_zookeeper()

@zk_conn.ChildrenWatch('/networks')
def updatenetworks(new_network_list):
    global network_list
    for network in new_network_list:
        if not network in s_network:
            s_network[network] = VXNetworkInstance.VXNetworkInstance(network, zk_conn, config, t_router[myhostname])
        if not network in new_network_list:
            s_network[network].removeAddress()
            s_network[network].removeNetwork()
    for router in router_list:
        if router in t_router:
            t_router[router].updatenetworklist(s_network)
    network_list = new_network_list
    print(ansiiprint.blue() + 'Network list: ' + ansiiprint.end() + '{}'.format(' '.join(network_list)))

# Ensure we force startup of interfaces if we're primary
if this_router.getnetworkstate() == 'primary':
    this_router.become_primary()

# Create timer to update this router in Zookeeper
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
