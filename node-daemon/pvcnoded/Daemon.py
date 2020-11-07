#!/usr/bin/env python3

# Daemon.py - Node daemon
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2020 Joshua M. Boniface <joshua@boniface.me>
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
import psutil
import subprocess
import time
import re
import yaml
import json

from socket import gethostname
from threading import Thread
from ipaddress import ip_address, ip_network
from apscheduler.schedulers.background import BackgroundScheduler
from distutils.util import strtobool
from queue import Queue
from xml.etree import ElementTree
from rados import Rados

import pvcnoded.log as log
import pvcnoded.zkhandler as zkhandler
import pvcnoded.fencing as fencing
import pvcnoded.common as common

import pvcnoded.VMInstance as VMInstance
import pvcnoded.NodeInstance as NodeInstance
import pvcnoded.VXNetworkInstance as VXNetworkInstance
import pvcnoded.DNSAggregatorInstance as DNSAggregatorInstance
import pvcnoded.CephInstance as CephInstance
import pvcnoded.MetadataAPIInstance as MetadataAPIInstance

# Version string for startup output
version = '0.9.1'

###############################################################################
# PVCD - node daemon startup program
###############################################################################
#
# The PVC daemon starts a node and configures all the required components for
# the node to run. It determines which of the 3 daemon modes it should be in
# during initial setup based on hostname and the config file, and then starts
# any required services. The 3 daemon modes are:
#  * leader: the cluster leader, follows the Zookeeper leader
#  * coordinator: a Zookeeper cluster member
#  * hypervisor: a hypervisor without any cluster intelligence
#
###############################################################################

###############################################################################
# Daemon functions
###############################################################################


# Create timer to update this node in Zookeeper
def startKeepaliveTimer():
    # Create our timer object
    update_timer = BackgroundScheduler()
    interval = int(config['keepalive_interval'])
    logger.out('Starting keepalive timer ({} second interval)'.format(interval), state='s')
    update_timer.add_job(node_keepalive, 'interval', seconds=interval)
    update_timer.start()
    node_keepalive()
    return update_timer


def stopKeepaliveTimer():
    global update_timer
    try:
        update_timer.shutdown()
        logger.out('Stopping keepalive timer', state='s')
    except Exception:
        pass


###############################################################################
# PHASE 1a - Configuration parsing
###############################################################################

# Get the config file variable from the environment
try:
    pvcnoded_config_file = os.environ['PVCD_CONFIG_FILE']
except Exception:
    print('ERROR: The "PVCD_CONFIG_FILE" environment variable must be set before starting pvcnoded.')
    exit(1)

# Set local hostname and domain variables
myfqdn = gethostname()
myhostname = myfqdn.split('.', 1)[0]
mydomainname = ''.join(myfqdn.split('.', 1)[1:])
try:
    mynodeid = re.findall(r'\d+', myhostname)[-1]
except IndexError:
    mynodeid = 1

# Maintenance mode off by default
maintenance = False

# Gather useful data about our host
# Static data format: 'cpu_count', 'arch', 'os', 'kernel'
staticdata = []
staticdata.append(str(psutil.cpu_count()))
staticdata.append(subprocess.run(['uname', '-r'], stdout=subprocess.PIPE).stdout.decode('ascii').strip())
staticdata.append(subprocess.run(['uname', '-o'], stdout=subprocess.PIPE).stdout.decode('ascii').strip())
staticdata.append(subprocess.run(['uname', '-m'], stdout=subprocess.PIPE).stdout.decode('ascii').strip())


# Read and parse the config file
def readConfig(pvcnoded_config_file, myhostname):
    print('Loading configuration from file "{}"'.format(pvcnoded_config_file))

    with open(pvcnoded_config_file, 'r') as cfgfile:
        try:
            o_config = yaml.load(cfgfile)
        except Exception as e:
            print('ERROR: Failed to parse configuration file: {}'.format(e))
            exit(1)

    # Handle the basic config (hypervisor-only)
    try:
        config_general = {
            'coordinators': o_config['pvc']['cluster']['coordinators'],
            'enable_hypervisor': o_config['pvc']['functions']['enable_hypervisor'],
            'enable_networking': o_config['pvc']['functions']['enable_networking'],
            'enable_storage': o_config['pvc']['functions']['enable_storage'],
            'enable_api': o_config['pvc']['functions']['enable_api'],
            'dynamic_directory': o_config['pvc']['system']['configuration']['directories']['dynamic_directory'],
            'log_directory': o_config['pvc']['system']['configuration']['directories']['log_directory'],
            'console_log_directory': o_config['pvc']['system']['configuration']['directories']['console_log_directory'],
            'file_logging': o_config['pvc']['system']['configuration']['logging']['file_logging'],
            'stdout_logging': o_config['pvc']['system']['configuration']['logging']['stdout_logging'],
            'log_colours': o_config['pvc']['system']['configuration']['logging']['log_colours'],
            'log_dates': o_config['pvc']['system']['configuration']['logging']['log_dates'],
            'log_keepalives': o_config['pvc']['system']['configuration']['logging']['log_keepalives'],
            'log_keepalive_cluster_details': o_config['pvc']['system']['configuration']['logging']['log_keepalive_cluster_details'],
            'log_keepalive_storage_details': o_config['pvc']['system']['configuration']['logging']['log_keepalive_storage_details'],
            'console_log_lines': o_config['pvc']['system']['configuration']['logging']['console_log_lines'],
            'vm_shutdown_timeout': int(o_config['pvc']['system']['intervals']['vm_shutdown_timeout']),
            'keepalive_interval': int(o_config['pvc']['system']['intervals']['keepalive_interval']),
            'fence_intervals': int(o_config['pvc']['system']['intervals']['fence_intervals']),
            'suicide_intervals': int(o_config['pvc']['system']['intervals']['suicide_intervals']),
            'successful_fence': o_config['pvc']['system']['fencing']['actions']['successful_fence'],
            'failed_fence': o_config['pvc']['system']['fencing']['actions']['failed_fence'],
            'migration_target_selector': o_config['pvc']['system']['migration']['target_selector'],
            'ipmi_hostname': o_config['pvc']['system']['fencing']['ipmi']['host'],
            'ipmi_username': o_config['pvc']['system']['fencing']['ipmi']['user'],
            'ipmi_password': o_config['pvc']['system']['fencing']['ipmi']['pass']
        }
    except Exception as e:
        print('ERROR: Failed to load configuration: {}'.format(e))
        exit(1)
    config = config_general

    # Handle debugging config
    try:
        config_debug = {
            'debug': o_config['pvc']['debug']
        }
    except Exception:
        config_debug = {
            'debug': False
        }
    config = {**config, **config_debug}

    # Handle the networking config
    if config['enable_networking']:
        try:
            config_networking = {
                'cluster_domain': o_config['pvc']['cluster']['networks']['cluster']['domain'],
                'vni_floating_ip': o_config['pvc']['cluster']['networks']['cluster']['floating_ip'],
                'vni_network': o_config['pvc']['cluster']['networks']['cluster']['network'],
                'storage_domain': o_config['pvc']['cluster']['networks']['storage']['domain'],
                'storage_floating_ip': o_config['pvc']['cluster']['networks']['storage']['floating_ip'],
                'storage_network': o_config['pvc']['cluster']['networks']['storage']['network'],
                'upstream_domain': o_config['pvc']['cluster']['networks']['upstream']['domain'],
                'upstream_floating_ip': o_config['pvc']['cluster']['networks']['upstream']['floating_ip'],
                'upstream_network': o_config['pvc']['cluster']['networks']['upstream']['network'],
                'upstream_gateway': o_config['pvc']['cluster']['networks']['upstream']['gateway'],
                'pdns_postgresql_host': o_config['pvc']['coordinator']['dns']['database']['host'],
                'pdns_postgresql_port': o_config['pvc']['coordinator']['dns']['database']['port'],
                'pdns_postgresql_dbname': o_config['pvc']['coordinator']['dns']['database']['name'],
                'pdns_postgresql_user': o_config['pvc']['coordinator']['dns']['database']['user'],
                'pdns_postgresql_password': o_config['pvc']['coordinator']['dns']['database']['pass'],
                'metadata_postgresql_host': o_config['pvc']['coordinator']['metadata']['database']['host'],
                'metadata_postgresql_port': o_config['pvc']['coordinator']['metadata']['database']['port'],
                'metadata_postgresql_dbname': o_config['pvc']['coordinator']['metadata']['database']['name'],
                'metadata_postgresql_user': o_config['pvc']['coordinator']['metadata']['database']['user'],
                'metadata_postgresql_password': o_config['pvc']['coordinator']['metadata']['database']['pass'],
                'bridge_dev': o_config['pvc']['system']['configuration']['networking']['bridge_device'],
                'vni_dev': o_config['pvc']['system']['configuration']['networking']['cluster']['device'],
                'vni_mtu': o_config['pvc']['system']['configuration']['networking']['cluster']['mtu'],
                'vni_dev_ip': o_config['pvc']['system']['configuration']['networking']['cluster']['address'],
                'storage_dev': o_config['pvc']['system']['configuration']['networking']['storage']['device'],
                'storage_mtu': o_config['pvc']['system']['configuration']['networking']['storage']['mtu'],
                'storage_dev_ip': o_config['pvc']['system']['configuration']['networking']['storage']['address'],
                'upstream_dev': o_config['pvc']['system']['configuration']['networking']['upstream']['device'],
                'upstream_mtu': o_config['pvc']['system']['configuration']['networking']['upstream']['mtu'],
                'upstream_dev_ip': o_config['pvc']['system']['configuration']['networking']['upstream']['address'],
            }
        except Exception as e:
            print('ERROR: Failed to load configuration: {}'.format(e))
            exit(1)
        config = {**config, **config_networking}

        # Create the by-id address entries
        for net in ['vni', 'storage', 'upstream']:
            address_key = '{}_dev_ip'.format(net)
            floating_key = '{}_floating_ip'.format(net)
            network_key = '{}_network'.format(net)

            # Verify the network provided is valid
            try:
                network = ip_network(config[network_key])
            except Exception:
                print('ERROR: Network address {} for {} is not valid!'.format(config[network_key], network_key))
                exit(1)

            # If we should be autoselected
            if config[address_key] == 'by-id':
                # Construct an IP from the relevant network
                # The NodeID starts at 1, but indexes start at 0
                address_id = int(mynodeid) - 1
                # Grab the nth address from the network
                config[address_key] = '{}/{}'.format(list(network.hosts())[address_id], network.prefixlen)

            # Verify that the floating IP is valid

            try:
                # Set the ipaddr
                floating_addr = ip_address(config[floating_key].split('/')[0])
                # Verify we're in the network
                if floating_addr not in list(network.hosts()):
                    raise
            except Exception:
                print('ERROR: Floating address {} for {} is not valid!'.format(config[floating_key], floating_key))
                exit(1)

    # Handle the storage config
    if config['enable_storage']:
        try:
            config_storage = {
                'ceph_config_file': o_config['pvc']['system']['configuration']['storage']['ceph_config_file'],
                'ceph_admin_keyring': o_config['pvc']['system']['configuration']['storage']['ceph_admin_keyring']
            }
        except Exception as e:
            print('ERROR: Failed to load configuration: {}'.format(e))
            exit(1)
        config = {**config, **config_storage}

    # Handle an empty ipmi_hostname
    if config['ipmi_hostname'] == '':
        config['ipmi_hostname'] = myhostname + '-lom.' + mydomainname

    return config


# Get the config object from readConfig()
config = readConfig(pvcnoded_config_file, myhostname)
debug = config['debug']
if debug:
    print('DEBUG MODE ENABLED')

# Handle the enable values
enable_hypervisor = config['enable_hypervisor']
enable_networking = config['enable_networking']
enable_storage = config['enable_storage']

###############################################################################
# PHASE 1b - Prepare filesystem directories
###############################################################################

# Define our dynamic directory schema
# <dynamic_directory>/
#                     dnsmasq/
#                     pdns/
#                     nft/
config['dnsmasq_dynamic_directory'] = config['dynamic_directory'] + '/dnsmasq'
config['pdns_dynamic_directory'] = config['dynamic_directory'] + '/pdns'
config['nft_dynamic_directory'] = config['dynamic_directory'] + '/nft'

# Create our dynamic directories if they don't exist
if not os.path.exists(config['dynamic_directory']):
    os.makedirs(config['dynamic_directory'])
    os.makedirs(config['dnsmasq_dynamic_directory'])
    os.makedirs(config['pdns_dynamic_directory'])
    os.makedirs(config['nft_dynamic_directory'])

# Define our log directory schema
# <log_directory>/
#                 dnsmasq/
#                 pdns/
#                 nft/
config['dnsmasq_log_directory'] = config['log_directory'] + '/dnsmasq'
config['pdns_log_directory'] = config['log_directory'] + '/pdns'
config['nft_log_directory'] = config['log_directory'] + '/nft'

# Create our log directories if they don't exist
if not os.path.exists(config['log_directory']):
    os.makedirs(config['log_directory'])
    os.makedirs(config['dnsmasq_log_directory'])
    os.makedirs(config['pdns_log_directory'])
    os.makedirs(config['nft_log_directory'])

###############################################################################
# PHASE 1c - Set up logging
###############################################################################

logger = log.Logger(config)

# Print our startup messages
logger.out('Parallel Virtual Cluster node daemon v{}'.format(version))
logger.out('FQDN: {}'.format(myfqdn))
logger.out('Host: {}'.format(myhostname))
logger.out('ID: {}'.format(mynodeid))
logger.out('IPMI hostname: {}'.format(config['ipmi_hostname']))
logger.out('Machine details:')
logger.out('  CPUs: {}'.format(staticdata[0]))
logger.out('  Arch: {}'.format(staticdata[3]))
logger.out('  OS: {}'.format(staticdata[2]))
logger.out('  Kernel: {}'.format(staticdata[1]))
logger.out('Starting pvcnoded on host {}'.format(myfqdn), state='s')

# Define some colours for future messages if applicable
if config['log_colours']:
    fmt_end = logger.fmt_end
    fmt_bold = logger.fmt_bold
    fmt_blue = logger.fmt_blue
    fmt_cyan = logger.fmt_cyan
    fmt_green = logger.fmt_green
    fmt_yellow = logger.fmt_yellow
    fmt_red = logger.fmt_red
    fmt_purple = logger.fmt_purple
else:
    fmt_end = ''
    fmt_bold = ''
    fmt_blue = ''
    fmt_cyan = ''
    fmt_green = ''
    fmt_yellow = ''
    fmt_red = ''
    fmt_purple = ''

###############################################################################
# PHASE 2a - Create local IP addresses for static networks
###############################################################################

if enable_networking:
    # VNI configuration
    vni_dev = config['vni_dev']
    vni_mtu = config['vni_mtu']
    vni_dev_ip = config['vni_dev_ip']
    logger.out('Setting up VNI network interface {} with MTU {}'.format(vni_dev, vni_mtu), state='i')
    common.run_os_command('ip link set {} mtu {} up'.format(vni_dev, vni_mtu))

    # Cluster bridge configuration
    logger.out('Setting up Cluster network bridge on interface {} with IP {}'.format(vni_dev, vni_dev_ip), state='i')
    common.run_os_command('brctl addbr brcluster')
    common.run_os_command('brctl addif brcluster {}'.format(vni_dev))
    common.run_os_command('ip link set brcluster mtu {} up'.format(vni_mtu))
    common.run_os_command('ip address add {} dev {}'.format(vni_dev_ip, 'brcluster'))

    # Storage configuration
    storage_dev = config['storage_dev']
    storage_mtu = config['storage_mtu']
    storage_dev_ip = config['storage_dev_ip']
    logger.out('Setting up Storage network interface {} with MTU {}'.format(storage_dev, vni_mtu), state='i')
    common.run_os_command('ip link set {} mtu {} up'.format(storage_dev, storage_mtu))

    # Storage bridge configuration
    if storage_dev == vni_dev:
        logger.out('Adding Storage network IP {} to VNI Cluster bridge brcluster'.format(storage_dev_ip), state='i')
        common.run_os_command('ip address add {} dev {}'.format(storage_dev_ip, 'brcluster'))
    else:
        logger.out('Setting up Storage network bridge on interface {} with IP {}'.format(vni_dev, vni_dev_ip), state='i')
        common.run_os_command('brctl addbr brstorage')
        common.run_os_command('brctl addif brstorage {}'.format(storage_dev))
        common.run_os_command('ip link set brstorage mtu {} up'.format(storage_mtu))
        common.run_os_command('ip address add {} dev {}'.format(storage_dev_ip, 'brstorage'))

    # Upstream configuration
    upstream_dev = config['upstream_dev']
    upstream_mtu = config['upstream_mtu']
    upstream_dev_ip = config['upstream_dev_ip']
    logger.out('Setting up Upstream network interface {} with MTU {}'.format(upstream_dev, upstream_mtu), state='i')
    common.run_os_command('ip link set {} mtu {} up'.format(upstream_dev, upstream_mtu))

    # Upstream bridge configuration
    if upstream_dev == vni_dev:
        logger.out('Adding Upstream network IP {} to VNI Cluster bridge brcluster'.format(upstream_dev_ip), state='i')
        common.run_os_command('ip address add {} dev {}'.format(upstream_dev_ip, 'brcluster'))
    else:
        logger.out('Setting up Upstream network bridge on interface {} with IP {}'.format(vni_dev, vni_dev_ip), state='i')
        common.run_os_command('brctl addbr brupstream')
        common.run_os_command('brctl addif brupstream {}'.format(upstream_dev))
        common.run_os_command('ip link set brupstream mtu {} up'.format(upstream_mtu))
        common.run_os_command('ip address add {} dev {}'.format(upstream_dev_ip, 'brupstream'))

    # Add upstream default gateway
    upstream_gateway = config.get('upstream_gateway', None)
    if upstream_gateway:
        logger.out('Setting up Upstream default gateway IP {}'.format(upstream_gateway), state='i')
        if upstream_dev == vni_dev:
            common.run_os_command('ip route add default via {} dev {}'.format(upstream_gateway, 'brcluster'))
        else:
            common.run_os_command('ip route add default via {} dev {}'.format(upstream_gateway, 'brupstream'))

###############################################################################
# PHASE 2b - Prepare sysctl for pvcnoded
###############################################################################

if enable_networking:
    # Enable routing functions
    common.run_os_command('sysctl net.ipv4.ip_forward=1')
    common.run_os_command('sysctl net.ipv6.ip_forward=1')

    # Send redirects
    common.run_os_command('sysctl net.ipv4.conf.all.send_redirects=1')
    common.run_os_command('sysctl net.ipv4.conf.default.send_redirects=1')
    common.run_os_command('sysctl net.ipv6.conf.all.send_redirects=1')
    common.run_os_command('sysctl net.ipv6.conf.default.send_redirects=1')

    # Accept source routes
    common.run_os_command('sysctl net.ipv4.conf.all.accept_source_route=1')
    common.run_os_command('sysctl net.ipv4.conf.default.accept_source_route=1')
    common.run_os_command('sysctl net.ipv6.conf.all.accept_source_route=1')
    common.run_os_command('sysctl net.ipv6.conf.default.accept_source_route=1')

    # Disable RP filtering on the VNI Cluster and Upstream interfaces (to allow traffic pivoting)
    common.run_os_command('sysctl net.ipv4.conf.{}.rp_filter=0'.format(config['vni_dev']))
    common.run_os_command('sysctl net.ipv4.conf.{}.rp_filter=0'.format(config['upstream_dev']))
    common.run_os_command('sysctl net.ipv4.conf.brcluster.rp_filter=0')
    common.run_os_command('sysctl net.ipv4.conf.brupstream.rp_filter=0')
    common.run_os_command('sysctl net.ipv6.conf.{}.rp_filter=0'.format(config['vni_dev']))
    common.run_os_command('sysctl net.ipv6.conf.{}.rp_filter=0'.format(config['upstream_dev']))
    common.run_os_command('sysctl net.ipv6.conf.brcluster.rp_filter=0')
    common.run_os_command('sysctl net.ipv6.conf.brupstream.rp_filter=0')

###############################################################################
# PHASE 3a - Determine coordinator mode
###############################################################################

# What is the list of coordinator hosts
coordinator_nodes = config['coordinators']

if myhostname in coordinator_nodes:
    # We are indeed a coordinator host
    config['daemon_mode'] = 'coordinator'
    # Start the zookeeper service using systemctl
    logger.out('Node is a ' + fmt_blue + 'coordinator' + fmt_end, state='i')
else:
    config['daemon_mode'] = 'hypervisor'

###############################################################################
# PHASE 3b - Start system daemons
###############################################################################
if config['daemon_mode'] == 'coordinator':
    logger.out('Starting Zookeeper daemon', state='i')
    common.run_os_command('systemctl start zookeeper.service')

if enable_hypervisor:
    logger.out('Starting Libvirt daemon', state='i')
    common.run_os_command('systemctl start libvirtd.service')

if enable_networking:
    if config['daemon_mode'] == 'coordinator':
        logger.out('Starting Patroni daemon', state='i')
        common.run_os_command('systemctl start patroni.service')
        logger.out('Starting FRRouting daemon', state='i')
        common.run_os_command('systemctl start frr.service')

if enable_storage:
    if config['daemon_mode'] == 'coordinator':
        logger.out('Starting Ceph monitor daemon', state='i')
        common.run_os_command('systemctl start ceph-mon@{}'.format(myhostname))
        logger.out('Starting Ceph manager daemon', state='i')
        common.run_os_command('systemctl start ceph-mgr@{}'.format(myhostname))

logger.out('Waiting 5s for daemons to start', state='s')
time.sleep(5)

###############################################################################
# PHASE 4 - Attempt to connect to the coordinators and start zookeeper client
###############################################################################

# Start the connection to the coordinators
zk_conn = kazoo.client.KazooClient(hosts=config['coordinators'])
try:
    logger.out('Connecting to Zookeeper cluster nodes {}'.format(config['coordinators']), state='i')
    # Start connection
    zk_conn.start()
except Exception as e:
    logger.out('ERROR: Failed to connect to Zookeeper cluster: {}'.format(e), state='e')
    exit(1)


# Handle zookeeper failures
def zk_listener(state):
    global zk_conn, update_timer
    if state == kazoo.client.KazooState.CONNECTED:
        logger.out('Connection to Zookeeper restarted', state='o')

        # Start keepalive thread
        if update_timer:
            update_timer = startKeepaliveTimer()
    else:
        # Stop keepalive thread
        if update_timer:
            stopKeepaliveTimer()

        logger.out('Connection to Zookeeper lost; retrying', state='w')

        while True:
            time.sleep(1)

            _zk_conn = kazoo.client.KazooClient(hosts=config['coordinators'])
            try:
                _zk_conn.start()
            except Exception:
                del _zk_conn
                continue

            # Overwrite global zk_conn with new connection
            zk_conn = _zk_conn
            # Readd the listener
            zk_conn.add_listener(zk_listener)
            break


zk_conn.add_listener(zk_listener)

###############################################################################
# PHASE 5 - Gracefully handle termination
###############################################################################


# Cleanup function
def cleanup():
    global zk_conn, update_timer, d_domain

    logger.out('Terminating pvcnoded and cleaning up', state='s')

    # Set shutdown state in Zookeeper
    zkhandler.writedata(zk_conn, {'/nodes/{}/daemonstate'.format(myhostname): 'shutdown'})

    # Waiting for any flushes to complete
    logger.out('Waiting for any active flushes', state='s')
    while this_node.flush_thread is not None:
        time.sleep(0.5)

    # Stop console logging on all VMs
    logger.out('Stopping domain console watchers', state='s')
    for domain in d_domain:
        if d_domain[domain].getnode() == myhostname:
            try:
                d_domain[domain].console_log_instance.stop()
            except NameError:
                pass
            except AttributeError:
                pass

    # Force into secondary coordinator state if needed
    try:
        if this_node.router_state == 'primary':
            zkhandler.writedata(zk_conn, {
                '/primary_node': 'none'
            })
            logger.out('Waiting for primary migration', state='s')
            while this_node.router_state != 'secondary':
                time.sleep(0.5)
    except Exception:
        pass

    # Stop keepalive thread
    try:
        stopKeepaliveTimer()
    except NameError:
        pass
    except AttributeError:
        pass

    logger.out('Performing final keepalive update', state='s')
    node_keepalive()

    # Set stop state in Zookeeper
    zkhandler.writedata(zk_conn, {'/nodes/{}/daemonstate'.format(myhostname): 'stop'})

    # Forcibly terminate dnsmasq because it gets stuck sometimes
    common.run_os_command('killall dnsmasq')

    # Close the Zookeeper connection
    try:
        zk_conn.stop()
        zk_conn.close()
    except Exception:
        pass

    logger.out('Terminated pvc daemon', state='s')
    sys.exit(0)


# Termination function
def term(signum='', frame=''):
    cleanup()


# Hangup (logrotate) function
def hup(signum='', frame=''):
    if config['file_logging']:
        logger.hup()


# Handle signals gracefully
signal.signal(signal.SIGTERM, term)
signal.signal(signal.SIGINT, term)
signal.signal(signal.SIGQUIT, term)
signal.signal(signal.SIGHUP, hup)

###############################################################################
# PHASE 6 - Prepare host in Zookeeper
###############################################################################

# Check if our node exists in Zookeeper, and create it if not
if zk_conn.exists('/nodes/{}'.format(myhostname)):
    logger.out("Node is " + fmt_green + "present" + fmt_end + " in Zookeeper", state='i')
    if config['daemon_mode'] == 'coordinator':
        init_routerstate = 'secondary'
    else:
        init_routerstate = 'client'
    # Update static data just in case it's changed
    zkhandler.writedata(zk_conn, {
        '/nodes/{}/daemonmode'.format(myhostname): config['daemon_mode'],
        '/nodes/{}/daemonstate'.format(myhostname): 'init',
        '/nodes/{}/routerstate'.format(myhostname): init_routerstate,
        '/nodes/{}/staticdata'.format(myhostname): ' '.join(staticdata),
        # Keepalives and fencing information (always load and set from config on boot)
        '/nodes/{}/ipmihostname'.format(myhostname): config['ipmi_hostname'],
        '/nodes/{}/ipmiusername'.format(myhostname): config['ipmi_username'],
        '/nodes/{}/ipmipassword'.format(myhostname): config['ipmi_password']
    })
else:
    logger.out("Node is " + fmt_red + "absent" + fmt_end + " in Zookeeper; adding new node", state='i')
    keepalive_time = int(time.time())
    zkhandler.writedata(zk_conn, {
        '/nodes/{}'.format(myhostname): config['daemon_mode'],
        # Basic state information
        '/nodes/{}/daemonmode'.format(myhostname): config['daemon_mode'],
        '/nodes/{}/daemonstate'.format(myhostname): 'init',
        '/nodes/{}/routerstate'.format(myhostname): 'client',
        '/nodes/{}/domainstate'.format(myhostname): 'flushed',
        '/nodes/{}/staticdata'.format(myhostname): ' '.join(staticdata),
        '/nodes/{}/memtotal'.format(myhostname): '0',
        '/nodes/{}/memfree'.format(myhostname): '0',
        '/nodes/{}/memused'.format(myhostname): '0',
        '/nodes/{}/memalloc'.format(myhostname): '0',
        '/nodes/{}/memprov'.format(myhostname): '0',
        '/nodes/{}/vcpualloc'.format(myhostname): '0',
        '/nodes/{}/cpuload'.format(myhostname): '0.0',
        '/nodes/{}/networkscount'.format(myhostname): '0',
        '/nodes/{}/domainscount'.format(myhostname): '0',
        '/nodes/{}/runningdomains'.format(myhostname): '',
        # Keepalives and fencing information
        '/nodes/{}/keepalive'.format(myhostname): str(keepalive_time),
        '/nodes/{}/ipmihostname'.format(myhostname): config['ipmi_hostname'],
        '/nodes/{}/ipmiusername'.format(myhostname): config['ipmi_username'],
        '/nodes/{}/ipmipassword'.format(myhostname): config['ipmi_password']
    })

# Check that the primary key exists, and create it with us as master if not
try:
    current_primary = zkhandler.readdata(zk_conn, '/primary_node')
except kazoo.exceptions.NoNodeError:
    current_primary = 'none'

if current_primary and current_primary != 'none':
    logger.out('Current primary node is {}{}{}.'.format(fmt_blue, current_primary, fmt_end), state='i')
else:
    if config['daemon_mode'] == 'coordinator':
        logger.out('No primary node found; creating with us as primary.', state='i')
        zkhandler.writedata(zk_conn, {'/primary_node': myhostname})

###############################################################################
# PHASE 7a - Ensure IPMI is reachable and working
###############################################################################
if not fencing.verifyIPMI(config['ipmi_hostname'], config['ipmi_username'], config['ipmi_password']):
    logger.out('Our IPMI is not reachable; fencing of this node will likely fail', state='w')

###############################################################################
# PHASE 7b - Ensure Libvirt is working
###############################################################################

if enable_hypervisor:
    # Check that libvirtd is listening TCP
    libvirt_check_name = "qemu+tcp://{}:16509/system".format(myhostname)
    logger.out('Connecting to Libvirt daemon at {}'.format(libvirt_check_name), state='i')
    try:
        lv_conn = libvirt.open(libvirt_check_name)
        lv_conn.close()
    except Exception as e:
        logger.out('ERROR: Failed to connect to Libvirt daemon: {}'.format(e), state='e')
        exit(1)

###############################################################################
# PHASE 7c - Ensure NFT is running on the local host
###############################################################################

if enable_networking:
    logger.out("Creating NFT firewall configuration", state='i')

    # Create our config dirs
    common.run_os_command(
        '/bin/mkdir --parents {}/networks'.format(
            config['nft_dynamic_directory']
        )
    )
    common.run_os_command(
        '/bin/mkdir --parents {}/static'.format(
            config['nft_dynamic_directory']
        )
    )
    common.run_os_command(
        '/bin/mkdir --parents {}'.format(
            config['nft_dynamic_directory']
        )
    )

    # Set up the basic features of the nftables firewall
    nftables_base_rules = """# Base rules
    flush ruleset
    # Add the filter table and chains
    add table inet filter
    add chain inet filter forward {{type filter hook forward priority 0; }}
    add chain inet filter input {{type filter hook input priority 0; }}
    # Include static rules and network rules
    include "{rulesdir}/static/*"
    include "{rulesdir}/networks/*"
    """.format(
        rulesdir=config['nft_dynamic_directory']
    )

    # Write the basic firewall config
    nftables_base_filename = '{}/base.nft'.format(config['nft_dynamic_directory'])
    with open(nftables_base_filename, 'w') as nfbasefile:
        nfbasefile.write(nftables_base_rules)
    common.reload_firewall_rules(logger, nftables_base_filename)

###############################################################################
# PHASE 7d - Ensure DNSMASQ is not running
###############################################################################

common.run_os_command('systemctl stop dnsmasq.service')

###############################################################################
# PHASE 8 - Set up our objects
###############################################################################

logger.out('Setting up objects', state='i')

d_node = dict()
d_network = dict()
d_domain = dict()
d_osd = dict()
d_pool = dict()
d_volume = dict()  # Dict of Dicts
node_list = []
network_list = []
domain_list = []
osd_list = []
pool_list = []
volume_list = dict()  # Dict of Lists

if enable_networking:
    # Create an instance of the DNS Aggregator and Metadata API if we're a coordinator
    if config['daemon_mode'] == 'coordinator':
        dns_aggregator = DNSAggregatorInstance.DNSAggregatorInstance(zk_conn, config, logger)
        metadata_api = MetadataAPIInstance.MetadataAPIInstance(zk_conn, config, logger)
    else:
        dns_aggregator = None
        metadata_api = None
else:
    dns_aggregator = None
    metadata_api = None


# Node objects
@zk_conn.ChildrenWatch('/nodes')
def update_nodes(new_node_list):
    global node_list, d_node

    # Add any missing nodes to the list
    for node in new_node_list:
        if node not in node_list:
            d_node[node] = NodeInstance.NodeInstance(node, myhostname, zk_conn, config, logger, d_node, d_network, d_domain, dns_aggregator, metadata_api)

    # Remove any deleted nodes from the list
    for node in node_list:
        if node not in new_node_list:
            # Delete the object
            del(d_node[node])

    # Update and print new list
    node_list = new_node_list
    logger.out('{}Node list:{} {}'.format(fmt_blue, fmt_end, ' '.join(node_list)), state='i')

    # Update node objects' list
    for node in d_node:
        d_node[node].update_node_list(d_node)


# Alias for our local node (passed to network and domain objects)
this_node = d_node[myhostname]


# Maintenance mode
@zk_conn.DataWatch('/maintenance')
def set_maintenance(_maintenance, stat, event=''):
    global maintenance
    try:
        maintenance = bool(strtobool(_maintenance.decode('ascii')))
    except Exception:
        maintenance = False


# Primary node
@zk_conn.DataWatch('/primary_node')
def update_primary(new_primary, stat, event=''):
    try:
        new_primary = new_primary.decode('ascii')
    except AttributeError:
        new_primary = 'none'
    key_version = stat.version

    if new_primary != this_node.primary_node:
        if config['daemon_mode'] == 'coordinator':
            # We're a coordinator and there is no primary
            if new_primary == 'none':
                if this_node.daemon_state == 'run' and this_node.router_state not in ['primary', 'takeover', 'relinquish']:
                    logger.out('Contending for primary coordinator state', state='i')
                    # Acquire an exclusive lock on the primary_node key
                    primary_lock = zkhandler.exclusivelock(zk_conn, '/primary_node')
                    try:
                        # This lock times out after 0.4s, which is 0.1s less than the pre-takeover
                        # timeout below, thus ensuring that a primary takeover will not deadlock
                        # against a node that failed the contention
                        primary_lock.acquire(timeout=0.4)
                        # Ensure when we get the lock that the versions are still consistent and that
                        # another node hasn't already acquired primary state
                        if key_version == zk_conn.get('/primary_node')[1].version:
                            zkhandler.writedata(zk_conn, {'/primary_node': myhostname})
                        # Cleanly release the lock
                        primary_lock.release()
                    # We timed out acquiring a lock, which means we failed contention, so just pass
                    except kazoo.exceptions.LockTimeout:
                        pass
            elif new_primary == myhostname:
                if this_node.router_state == 'secondary':
                    time.sleep(0.5)
                    zkhandler.writedata(zk_conn, {'/nodes/{}/routerstate'.format(myhostname): 'takeover'})
            else:
                if this_node.router_state == 'primary':
                    time.sleep(0.5)
                    zkhandler.writedata(zk_conn, {'/nodes/{}/routerstate'.format(myhostname): 'relinquish'})
        else:
            zkhandler.writedata(zk_conn, {'/nodes/{}/routerstate'.format(myhostname): 'client'})

        for node in d_node:
            d_node[node].primary_node = new_primary


if enable_networking:
    # Network objects
    @zk_conn.ChildrenWatch('/networks')
    def update_networks(new_network_list):
        global network_list, d_network

        # Add any missing networks to the list
        for network in new_network_list:
            if network not in network_list:
                d_network[network] = VXNetworkInstance.VXNetworkInstance(network, zk_conn, config, logger, this_node, dns_aggregator)
                if config['daemon_mode'] == 'coordinator' and d_network[network].nettype == 'managed':
                    try:
                        dns_aggregator.add_network(d_network[network])
                    except Exception as e:
                        logger.out('Failed to create DNS Aggregator for network {}: {}'.format(network, e), 'w')
                # Start primary functionality
                if this_node.router_state == 'primary' and d_network[network].nettype == 'managed':
                    d_network[network].createGateways()
                    d_network[network].startDHCPServer()

        # Remove any deleted networks from the list
        for network in network_list:
            if network not in new_network_list:
                if d_network[network].nettype == 'managed':
                    # Stop primary functionality
                    if this_node.router_state == 'primary':
                        d_network[network].stopDHCPServer()
                        d_network[network].removeGateways()
                        dns_aggregator.remove_network(d_network[network])
                    # Stop general functionality
                    d_network[network].removeFirewall()
                d_network[network].removeNetwork()
                # Delete the object
                del(d_network[network])

        # Update and print new list
        network_list = new_network_list
        logger.out('{}Network list:{} {}'.format(fmt_blue, fmt_end, ' '.join(network_list)), state='i')

        # Update node objects' list
        for node in d_node:
            d_node[node].update_network_list(d_network)

if enable_hypervisor:
    # VM command pipeline key
    @zk_conn.DataWatch('/cmd/domains')
    def cmd_domains(data, stat, event=''):
        if data:
            VMInstance.run_command(zk_conn, logger, this_node, data.decode('ascii'))

    # VM domain objects
    @zk_conn.ChildrenWatch('/domains')
    def update_domains(new_domain_list):
        global domain_list, d_domain

        # Add any missing domains to the list
        for domain in new_domain_list:
            if domain not in domain_list:
                d_domain[domain] = VMInstance.VMInstance(domain, zk_conn, config, logger, this_node)

        # Remove any deleted domains from the list
        for domain in domain_list:
            if domain not in new_domain_list:
                # Delete the object
                del(d_domain[domain])

        # Update and print new list
        domain_list = new_domain_list
        logger.out('{}VM list:{} {}'.format(fmt_blue, fmt_end, ' '.join(domain_list)), state='i')

        # Update node objects' list
        for node in d_node:
            d_node[node].update_domain_list(d_domain)

if enable_storage:
    # Ceph command pipeline key
    @zk_conn.DataWatch('/cmd/ceph')
    def cmd_ceph(data, stat, event=''):
        if data:
            CephInstance.run_command(zk_conn, logger, this_node, data.decode('ascii'), d_osd)

    # OSD objects
    @zk_conn.ChildrenWatch('/ceph/osds')
    def update_osds(new_osd_list):
        global osd_list, d_osd

        # Add any missing OSDs to the list
        for osd in new_osd_list:
            if osd not in osd_list:
                d_osd[osd] = CephInstance.CephOSDInstance(zk_conn, this_node, osd)

        # Remove any deleted OSDs from the list
        for osd in osd_list:
            if osd not in new_osd_list:
                # Delete the object
                del(d_osd[osd])

        # Update and print new list
        osd_list = new_osd_list
        logger.out('{}OSD list:{} {}'.format(fmt_blue, fmt_end, ' '.join(osd_list)), state='i')

    # Pool objects
    @zk_conn.ChildrenWatch('/ceph/pools')
    def update_pools(new_pool_list):
        global pool_list, d_pool

        # Add any missing Pools to the list
        for pool in new_pool_list:
            if pool not in pool_list:
                d_pool[pool] = CephInstance.CephPoolInstance(zk_conn, this_node, pool)
                d_volume[pool] = dict()
                volume_list[pool] = []

        # Remove any deleted Pools from the list
        for pool in pool_list:
            if pool not in new_pool_list:
                # Delete the object
                del(d_pool[pool])

        # Update and print new list
        pool_list = new_pool_list
        logger.out('{}Pool list:{} {}'.format(fmt_blue, fmt_end, ' '.join(pool_list)), state='i')

        # Volume objects in each pool
        for pool in pool_list:
            @zk_conn.ChildrenWatch('/ceph/volumes/{}'.format(pool))
            def update_volumes(new_volume_list):
                global volume_list, d_volume

                # Add any missing Volumes to the list
                for volume in new_volume_list:
                    if volume not in volume_list[pool]:
                        d_volume[pool][volume] = CephInstance.CephVolumeInstance(zk_conn, this_node, pool, volume)

                # Remove any deleted Volumes from the list
                for volume in volume_list[pool]:
                    if volume not in new_volume_list:
                        # Delete the object
                        del(d_volume[pool][volume])

                # Update and print new list
                volume_list[pool] = new_volume_list
                logger.out('{}Volume list [{pool}]:{} {plist}'.format(fmt_blue, fmt_end, pool=pool, plist=' '.join(volume_list[pool])), state='i')


###############################################################################
# PHASE 9 - Run the daemon
###############################################################################

# Ceph stats update function
def collect_ceph_stats(queue):
    if debug:
        logger.out("Thread starting", state='d', prefix='ceph-thread')

    # Connect to the Ceph cluster
    try:
        ceph_conn = Rados(conffile=config['ceph_config_file'], conf=dict(keyring=config['ceph_admin_keyring']))
        if debug:
            logger.out("Connecting to cluster", state='d', prefix='ceph-thread')
        ceph_conn.connect(timeout=1)
    except Exception as e:
        logger.out('Failed to open connection to Ceph cluster: {}'.format(e), state='e')
        return

    if debug:
        logger.out("Getting health stats from monitor", state='d', prefix='ceph-thread')

    # Get Ceph cluster health for local status output
    command = {"prefix": "health", "format": "json"}
    try:
        health_status = json.loads(ceph_conn.mon_command(json.dumps(command), b'', timeout=1)[1])
        ceph_health = health_status['status']
    except Exception as e:
        logger.out('Failed to obtain Ceph health data: {}'.format(e), state='e')
        return

    if ceph_health == 'HEALTH_OK':
        ceph_health_colour = fmt_green
    elif ceph_health == 'HEALTH_WARN':
        ceph_health_colour = fmt_yellow
    else:
        ceph_health_colour = fmt_red

    # Primary-only functions
    if this_node.router_state == 'primary':
        if debug:
            logger.out("Set ceph health information in zookeeper (primary only)", state='d', prefix='ceph-thread')

        command = {"prefix": "status", "format": "pretty"}
        ceph_status = ceph_conn.mon_command(json.dumps(command), b'', timeout=1)[1].decode('ascii')
        try:
            zkhandler.writedata(zk_conn, {
                '/ceph': str(ceph_status)
            })
        except Exception as e:
            logger.out('Failed to set Ceph status data: {}'.format(e), state='e')
            return

        if debug:
            logger.out("Set ceph rados df information in zookeeper (primary only)", state='d', prefix='ceph-thread')

        # Get rados df info
        command = {"prefix": "df", "format": "pretty"}
        ceph_df = ceph_conn.mon_command(json.dumps(command), b'', timeout=1)[1].decode('ascii')
        try:
            zkhandler.writedata(zk_conn, {
                '/ceph/util': str(ceph_df)
            })
        except Exception as e:
            logger.out('Failed to set Ceph utilization data: {}'.format(e), state='e')
            return

        if debug:
            logger.out("Set pool information in zookeeper (primary only)", state='d', prefix='ceph-thread')

        # Get pool info
        command = {"prefix": "df", "format": "json"}
        try:
            ceph_pool_df_raw = json.loads(ceph_conn.mon_command(json.dumps(command), b'', timeout=1)[1])['pools']
        except Exception as e:
            logger.out('Failed to obtain Pool data (ceph df): {}'.format(e), state='w')
            ceph_pool_df_raw = []

        retcode, stdout, stderr = common.run_os_command('rados df --format json', timeout=1)
        try:
            rados_pool_df_raw = json.loads(stdout)['pools']
        except Exception as e:
            logger.out('Failed to obtain Pool data (rados df): {}'.format(e), state='w')
            rados_pool_df_raw = []

        pool_count = len(ceph_pool_df_raw)
        if debug:
            logger.out("Getting info for {} pools".format(pool_count), state='d', prefix='ceph-thread')
        for pool_idx in range(0, pool_count):
            try:
                # Combine all the data for this pool
                ceph_pool_df = ceph_pool_df_raw[pool_idx]
                rados_pool_df = rados_pool_df_raw[pool_idx]
                pool = ceph_pool_df
                pool.update(rados_pool_df)

                # Ignore any pools that aren't in our pool list
                if pool['name'] not in pool_list:
                    if debug:
                        logger.out("Pool {} not in pool list {}".format(pool['name'], pool_list), state='d', prefix='ceph-thread')
                    continue
                else:
                    if debug:
                        logger.out("Parsing data for pool {}".format(pool['name']), state='d', prefix='ceph-thread')

                # Assemble a useful data structure
                pool_df = {
                    'id': pool['id'],
                    'free_bytes': pool['stats']['max_avail'],
                    'used_bytes': pool['stats']['bytes_used'],
                    'used_percent': pool['stats']['percent_used'],
                    'num_objects': pool['stats']['objects'],
                    'num_object_clones': pool['num_object_clones'],
                    'num_object_copies': pool['num_object_copies'],
                    'num_objects_missing_on_primary': pool['num_objects_missing_on_primary'],
                    'num_objects_unfound': pool['num_objects_unfound'],
                    'num_objects_degraded': pool['num_objects_degraded'],
                    'read_ops': pool['read_ops'],
                    'read_bytes': pool['read_bytes'],
                    'write_ops': pool['write_ops'],
                    'write_bytes': pool['write_bytes']
                }

                # Write the pool data to Zookeeper
                zkhandler.writedata(zk_conn, {
                    '/ceph/pools/{}/stats'.format(pool['name']): str(json.dumps(pool_df))
                })
            except Exception as e:
                # One or more of the status commands timed out, just continue
                logger.out('Failed to format and send pool data: {}'.format(e), state='w')
                pass

    # Only grab OSD stats if there are OSDs to grab (otherwise `ceph osd df` hangs)
    osds_this_node = 0
    if len(osd_list) > 0:
        # Get data from Ceph OSDs
        if debug:
            logger.out("Get data from Ceph OSDs", state='d', prefix='ceph-thread')

        # Parse the dump data
        osd_dump = dict()

        command = {"prefix": "osd dump", "format": "json"}
        try:
            retcode, stdout, stderr = common.run_os_command('ceph osd dump --format json --connect-timeout 2', timeout=2)
            osd_dump_raw = json.loads(stdout)['osds']
        except Exception as e:
            logger.out('Failed to obtain OSD data: {}'.format(e), state='w')
            osd_dump_raw = []

        if debug:
            logger.out("Loop through OSD dump", state='d', prefix='ceph-thread')
        for osd in osd_dump_raw:
            osd_dump.update({
                str(osd['osd']): {
                    'uuid': osd['uuid'],
                    'up': osd['up'],
                    'in': osd['in'],
                    'primary_affinity': osd['primary_affinity']
                }
            })

        # Parse the df data
        if debug:
            logger.out("Parse the OSD df data", state='d', prefix='ceph-thread')

        osd_df = dict()

        command = {"prefix": "osd df", "format": "json"}
        try:
            osd_df_raw = json.loads(ceph_conn.mon_command(json.dumps(command), b'', timeout=1)[1])['nodes']
        except Exception as e:
            logger.out('Failed to obtain OSD data: {}'.format(e), state='w')
            osd_df_raw = []

        if debug:
            logger.out("Loop through OSD df", state='d', prefix='ceph-thread')
        for osd in osd_df_raw:
            osd_df.update({
                str(osd['id']): {
                    'utilization': osd['utilization'],
                    'var': osd['var'],
                    'pgs': osd['pgs'],
                    'kb': osd['kb'],
                    'weight': osd['crush_weight'],
                    'reweight': osd['reweight'],
                }
            })

        # Parse the status data
        if debug:
            logger.out("Parse the OSD status data", state='d', prefix='ceph-thread')

        osd_status = dict()

        command = {"prefix": "osd status", "format": "pretty"}
        try:
            osd_status_raw = ceph_conn.mon_command(json.dumps(command), b'', timeout=1)[1].decode('ascii')
        except Exception as e:
            logger.out('Failed to obtain OSD status data: {}'.format(e), state='w')
            osd_status_raw = []

        if debug:
            logger.out("Loop through OSD status data", state='d', prefix='ceph-thread')

        for line in osd_status_raw.split('\n'):
            # Strip off colour
            line = re.sub(r'\x1b(\[.*?[@-~]|\].*?(\x07|\x1b\\))', '', line)
            # Split it for parsing
            line = line.split()
            if len(line) > 1 and line[1].isdigit():
                # This is an OSD line so parse it
                osd_id = line[1]
                node = line[3].split('.')[0]
                used = line[5]
                avail = line[7]
                wr_ops = line[9]
                wr_data = line[11]
                rd_ops = line[13]
                rd_data = line[15]
                state = line[17]
                osd_status.update({
                    str(osd_id): {
                        'node': node,
                        'used': used,
                        'avail': avail,
                        'wr_ops': wr_ops,
                        'wr_data': wr_data,
                        'rd_ops': rd_ops,
                        'rd_data': rd_data,
                        'state': state
                    }
                })

        # Merge them together into a single meaningful dict
        if debug:
            logger.out("Merge OSD data together", state='d', prefix='ceph-thread')

        osd_stats = dict()

        for osd in osd_list:
            try:
                this_dump = osd_dump[osd]
                this_dump.update(osd_df[osd])
                this_dump.update(osd_status[osd])
                osd_stats[osd] = this_dump
            except KeyError as e:
                # One or more of the status commands timed out, just continue
                logger.out('Failed to parse OSD stats into dictionary: {}'.format(e), state='w')

        # Trigger updates for each OSD on this node
        if debug:
            logger.out("Trigger updates for each OSD on this node", state='d', prefix='ceph-thread')

        for osd in osd_list:
            if d_osd[osd].node == myhostname:
                try:
                    stats = json.dumps(osd_stats[osd])
                    zkhandler.writedata(zk_conn, {
                        '/ceph/osds/{}/stats'.format(osd): str(stats)
                    })
                except KeyError as e:
                    # One or more of the status commands timed out, just continue
                    logger.out('Failed to upload OSD stats from dictionary: {}'.format(e), state='w')
                osds_this_node += 1

    ceph_conn.shutdown()

    queue.put(ceph_health_colour)
    queue.put(ceph_health)
    queue.put(osds_this_node)

    if debug:
        logger.out("Thread finished", state='d', prefix='ceph-thread')


# State table for pretty stats
libvirt_vm_states = {
    0: "NOSTATE",
    1: "RUNNING",
    2: "BLOCKED",
    3: "PAUSED",
    4: "SHUTDOWN",
    5: "SHUTOFF",
    6: "CRASHED",
    7: "PMSUSPENDED"
}


# VM stats update function
def collect_vm_stats(queue):
    if debug:
        logger.out("Thread starting", state='d', prefix='vm-thread')

    # Connect to libvirt
    libvirt_name = "qemu:///system"
    if debug:
        logger.out("Connecting to libvirt", state='d', prefix='vm-thread')
    lv_conn = libvirt.open(libvirt_name)
    if lv_conn is None:
        logger.out('Failed to open connection to "{}"'.format(libvirt_name), state='e')
        return

    memalloc = 0
    memprov = 0
    vcpualloc = 0
    # Toggle state management of dead VMs to restart them
    if debug:
        logger.out("Toggle state management of dead VMs to restart them", state='d', prefix='vm-thread')
    # Make a copy of the d_domain; if not, and it changes in flight, this can fail
    fixed_d_domain = this_node.d_domain.copy()
    for domain, instance in fixed_d_domain.items():
        if domain in this_node.domain_list:
            # Add the allocated memory to our memalloc value
            memalloc += instance.getmemory()
            memprov += instance.getmemory()
            vcpualloc += instance.getvcpus()
            if instance.getstate() == 'start' and instance.getnode() == this_node.name:
                if instance.getdom() is not None:
                    try:
                        if instance.getdom().state()[0] != libvirt.VIR_DOMAIN_RUNNING:
                            raise
                    except Exception:
                        # Toggle a state "change"
                        zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(domain): instance.getstate()})
        elif instance.getnode() == this_node.name:
            memprov += instance.getmemory()

    # Get list of running domains from Libvirt
    running_domains = lv_conn.listAllDomains(libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE)

    # Get statistics from any running VMs
    for domain in running_domains:
        try:
            # Get basic information about the VM
            tree = ElementTree.fromstring(domain.XMLDesc())
            domain_uuid = domain.UUIDString()
            domain_name = domain.name()

            # Get all the raw information about the VM
            if debug:
                logger.out("Getting general statistics for VM {}".format(domain_name), state='d', prefix='vm-thread')
            domain_state, domain_maxmem, domain_mem, domain_vcpus, domain_cputime = domain.info()
            # We can't properly gather stats from a non-running VMs so continue
            if domain_state != libvirt.VIR_DOMAIN_RUNNING:
                continue
            domain_memory_stats = domain.memoryStats()
            domain_cpu_stats = domain.getCPUStats(True)[0]
        except Exception as e:
            if debug:
                try:
                    logger.out("Failed getting VM information for {}: {}".format(domain.name(), e), state='d', prefix='vm-thread')
                except Exception:
                    pass
            continue

        # Ensure VM is present in the domain_list
        if domain_uuid not in this_node.domain_list:
            this_node.domain_list.append(domain_uuid)

        if debug:
            logger.out("Getting disk statistics for VM {}".format(domain_name), state='d', prefix='vm-thread')
        domain_disk_stats = []
        for disk in tree.findall('devices/disk'):
            disk_name = disk.find('source').get('name')
            if not disk_name:
                disk_name = disk.find('source').get('file')
            disk_stats = domain.blockStats(disk.find('target').get('dev'))
            domain_disk_stats.append({
                "name": disk_name,
                "rd_req": disk_stats[0],
                "rd_bytes": disk_stats[1],
                "wr_req": disk_stats[2],
                "wr_bytes": disk_stats[3],
                "err": disk_stats[4]
            })

        if debug:
            logger.out("Getting network statistics for VM {}".format(domain_name), state='d', prefix='vm-thread')
        domain_network_stats = []
        for interface in tree.findall('devices/interface'):
            interface_name = interface.find('target').get('dev')
            interface_bridge = interface.find('source').get('bridge')
            interface_stats = domain.interfaceStats(interface_name)
            domain_network_stats.append({
                "name": interface_name,
                "bridge": interface_bridge,
                "rd_bytes": interface_stats[0],
                "rd_packets": interface_stats[1],
                "rd_errors": interface_stats[2],
                "rd_drops": interface_stats[3],
                "wr_bytes": interface_stats[4],
                "wr_packets": interface_stats[5],
                "wr_errors": interface_stats[6],
                "wr_drops": interface_stats[7]
            })

        # Create the final dictionary
        domain_stats = {
            "state": libvirt_vm_states[domain_state],
            "maxmem": domain_maxmem,
            "livemem": domain_mem,
            "cpus": domain_vcpus,
            "cputime": domain_cputime,
            "mem_stats": domain_memory_stats,
            "cpu_stats": domain_cpu_stats,
            "disk_stats": domain_disk_stats,
            "net_stats": domain_network_stats
        }

        if debug:
            logger.out("Writing statistics for VM {} to Zookeeper".format(domain_name), state='d', prefix='vm-thread')

        try:
            zkhandler.writedata(zk_conn, {
                "/domains/{}/stats".format(domain_uuid): str(json.dumps(domain_stats))
            })
        except Exception as e:
            if debug:
                logger.out("{}".format(e), state='d', prefix='vm-thread')

    # Close the Libvirt connection
    lv_conn.close()

    queue.put(len(running_domains))
    queue.put(memalloc)
    queue.put(memprov)
    queue.put(vcpualloc)

    if debug:
        logger.out("Thread finished", state='d', prefix='vm-thread')


# Keepalive update function
def node_keepalive():
    if debug:
        logger.out("Keepalive starting", state='d', prefix='main-thread')

    # Set the upstream IP in Zookeeper for clients to read
    if config['enable_networking']:
        if this_node.router_state == 'primary':
            try:
                if zkhandler.readdata(zk_conn, '/upstream_ip') != config['upstream_floating_ip']:
                    raise
            except Exception:
                zkhandler.writedata(zk_conn, {'/upstream_ip': config['upstream_floating_ip']})

    # Get past state and update if needed
    if debug:
        logger.out("Get past state and update if needed", state='d', prefix='main-thread')
    past_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(this_node.name))
    if past_state != 'run':
        this_node.daemon_state = 'run'
        zkhandler.writedata(zk_conn, {'/nodes/{}/daemonstate'.format(this_node.name): 'run'})
    else:
        this_node.daemon_state = 'run'

    # Ensure the primary key is properly set
    if debug:
        logger.out("Ensure the primary key is properly set", state='d', prefix='main-thread')
    if this_node.router_state == 'primary':
        if zkhandler.readdata(zk_conn, '/primary_node') != this_node.name:
            zkhandler.writedata(zk_conn, {'/primary_node': this_node.name})

    # Run VM statistics collection in separate thread for parallelization
    if enable_hypervisor:
        vm_thread_queue = Queue()
        vm_stats_thread = Thread(target=collect_vm_stats, args=(vm_thread_queue,), kwargs={})
        vm_stats_thread.start()

    # Run Ceph status collection in separate thread for parallelization
    if enable_storage:
        ceph_thread_queue = Queue()
        ceph_stats_thread = Thread(target=collect_ceph_stats, args=(ceph_thread_queue,), kwargs={})
        ceph_stats_thread.start()

    # Get node performance statistics
    this_node.memtotal = int(psutil.virtual_memory().total / 1024 / 1024)
    this_node.memused = int(psutil.virtual_memory().used / 1024 / 1024)
    this_node.memfree = int(psutil.virtual_memory().free / 1024 / 1024)
    this_node.cpuload = os.getloadavg()[0]

    # Join against running threads
    if enable_hypervisor:
        vm_stats_thread.join(timeout=4.0)
        if vm_stats_thread.is_alive():
            logger.out('VM stats gathering exceeded 4s timeout, continuing', state='w')
    if enable_storage:
        ceph_stats_thread.join(timeout=4.0)
        if ceph_stats_thread.is_alive():
            logger.out('Ceph stats gathering exceeded 4s timeout, continuing', state='w')

    # Get information from thread queues
    if enable_hypervisor:
        try:
            this_node.domains_count = vm_thread_queue.get()
            this_node.memalloc = vm_thread_queue.get()
            this_node.memprov = vm_thread_queue.get()
            this_node.vcpualloc = vm_thread_queue.get()
        except Exception:
            pass
    else:
        this_node.domains_count = 0
        this_node.memalloc = 0
        this_node.memprov = 0
        this_node.vcpualloc = 0

    if enable_storage:
        try:
            ceph_health_colour = ceph_thread_queue.get()
            ceph_health = ceph_thread_queue.get()
            osds_this_node = ceph_thread_queue.get()
        except Exception:
            ceph_health_colour = fmt_cyan
            ceph_health = 'UNKNOWN'
            osds_this_node = '?'

    # Set our information in zookeeper
    keepalive_time = int(time.time())
    if debug:
        logger.out("Set our information in zookeeper", state='d', prefix='main-thread')
    try:
        zkhandler.writedata(zk_conn, {
            '/nodes/{}/memtotal'.format(this_node.name): str(this_node.memtotal),
            '/nodes/{}/memused'.format(this_node.name): str(this_node.memused),
            '/nodes/{}/memfree'.format(this_node.name): str(this_node.memfree),
            '/nodes/{}/memalloc'.format(this_node.name): str(this_node.memalloc),
            '/nodes/{}/memprov'.format(this_node.name): str(this_node.memprov),
            '/nodes/{}/vcpualloc'.format(this_node.name): str(this_node.vcpualloc),
            '/nodes/{}/cpuload'.format(this_node.name): str(this_node.cpuload),
            '/nodes/{}/domainscount'.format(this_node.name): str(this_node.domains_count),
            '/nodes/{}/runningdomains'.format(this_node.name): ' '.join(this_node.domain_list),
            '/nodes/{}/keepalive'.format(this_node.name): str(keepalive_time)
        })
    except Exception:
        logger.out('Failed to set keepalive data', state='e')
        return

    # Display node information to the terminal
    if config['log_keepalives']:
        if this_node.router_state == 'primary':
            cst_colour = fmt_green
        elif this_node.router_state == 'secondary':
            cst_colour = fmt_blue
        else:
            cst_colour = fmt_cyan
        logger.out(
            '{}{} keepalive{} [{}{}{}]'.format(
                fmt_purple,
                myhostname,
                fmt_end,
                fmt_bold + cst_colour,
                this_node.router_state,
                fmt_end
            ),
            state='t'
        )
        if config['log_keepalive_cluster_details']:
            logger.out(
                '{bold}Maintenance:{nofmt} {maint}  '
                '{bold}Active VMs:{nofmt} {domcount}  '
                '{bold}Networks:{nofmt} {netcount}  '
                '{bold}Load:{nofmt} {load}  '
                '{bold}Memory [MiB]: VMs:{nofmt} {allocmem}  '
                '{bold}Used:{nofmt} {usedmem}  '
                '{bold}Free:{nofmt} {freemem}'.format(
                    bold=fmt_bold,
                    nofmt=fmt_end,
                    maint=maintenance,
                    domcount=this_node.domains_count,
                    netcount=len(network_list),
                    load=this_node.cpuload,
                    freemem=this_node.memfree,
                    usedmem=this_node.memused,
                    allocmem=this_node.memalloc,
                ),
                state='t'
            )
        if enable_storage and config['log_keepalive_storage_details']:
            logger.out(
                '{bold}Ceph cluster status:{nofmt} {health_colour}{health}{nofmt}  '
                '{bold}Total OSDs:{nofmt} {total_osds}  '
                '{bold}Node OSDs:{nofmt} {node_osds}  '
                '{bold}Pools:{nofmt} {total_pools}  '.format(
                    bold=fmt_bold,
                    health_colour=ceph_health_colour,
                    nofmt=fmt_end,
                    health=ceph_health,
                    total_osds=len(osd_list),
                    node_osds=osds_this_node,
                    total_pools=len(pool_list)
                ),
                state='t'
            )

    # Look for dead nodes and fence them
    if not maintenance:
        if debug:
            logger.out("Look for dead nodes and fence them", state='d', prefix='main-thread')
        if config['daemon_mode'] == 'coordinator':
            for node_name in d_node:
                try:
                    node_daemon_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(node_name))
                    node_keepalive = int(zkhandler.readdata(zk_conn, '/nodes/{}/keepalive'.format(node_name)))
                except Exception:
                    node_daemon_state = 'unknown'
                    node_keepalive = 0

                # Handle deadtime and fencng if needed
                # (A node is considered dead when its keepalive timer is >6*keepalive_interval seconds
                # out-of-date while in 'start' state)
                node_deadtime = int(time.time()) - (int(config['keepalive_interval']) * int(config['fence_intervals']))
                if node_keepalive < node_deadtime and node_daemon_state == 'run':
                    logger.out('Node {} seems dead - starting monitor for fencing'.format(node_name), state='w')
                    zk_lock = zkhandler.writelock(zk_conn, '/nodes/{}/daemonstate'.format(node_name))
                    with zk_lock:
                        # Ensures that, if we lost the lock race and come out of waiting,
                        # we won't try to trigger our own fence thread.
                        if zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(node_name)) != 'dead':
                            fence_thread = Thread(target=fencing.fenceNode, args=(node_name, zk_conn, config, logger), kwargs={})
                            fence_thread.start()
                            # Write the updated data after we start the fence thread
                            zkhandler.writedata(zk_conn, {'/nodes/{}/daemonstate'.format(node_name): 'dead'})

    if debug:
        logger.out("Keepalive finished", state='d', prefix='main-thread')


# Start keepalive thread
update_timer = startKeepaliveTimer()

# Tick loop; does nothing since everything else is async
while True:
    try:
        time.sleep(1)
    except Exception:
        break
