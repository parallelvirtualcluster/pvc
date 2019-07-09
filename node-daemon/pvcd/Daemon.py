#!/usr/bin/env python3

# Daemon.py - Node daemon
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

# Version string for startup output
version = '0.4'

import kazoo.client
import libvirt
import sys
import os
import signal
import atexit
import socket
import psutil
import subprocess
import uuid
import time
import re
import configparser
import threading
import yaml
import json
import ipaddress
import apscheduler.schedulers.background

import pvcd.log as log
import pvcd.zkhandler as zkhandler
import pvcd.fencing as fencing
import pvcd.common as common

import pvcd.VMInstance as VMInstance
import pvcd.NodeInstance as NodeInstance
import pvcd.VXNetworkInstance as VXNetworkInstance
import pvcd.DNSAggregatorInstance as DNSAggregatorInstance
import pvcd.CephInstance as CephInstance

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
    update_timer = apscheduler.schedulers.background.BackgroundScheduler()
    interval = int(config['keepalive_interval'])
    logger.out('Starting keepalive timer ({} second interval)'.format(interval), state='s')
    update_timer.add_job(update_zookeeper, 'interval', seconds=interval)
    update_timer.start()
    update_zookeeper()
    return update_timer

def stopKeepaliveTimer():
    global update_timer
    try:
        update_timer.shutdown()
        logger.out('Stopping keepalive timer', state='s')
    except:
        pass

###############################################################################
# PHASE 1a - Configuration parsing
###############################################################################

# Get the config file variable from the environment
try:
    pvcd_config_file = os.environ['PVCD_CONFIG_FILE']
except:
    print('ERROR: The "PVCD_CONFIG_FILE" environment variable must be set before starting pvcd.')
    exit(1)

# Set local hostname and domain variables
myfqdn = socket.gethostname()
#myfqdn = 'pvc-hv1.domain.net'
myhostname = myfqdn.split('.', 1)[0]
mydomainname = ''.join(myfqdn.split('.', 1)[1:])
try:
    mynodeid = re.findall(r'\d+', myhostname)[-1]
except IndexError:
    mynodeid = 1

# Gather useful data about our host
# Static data format: 'cpu_count', 'arch', 'os', 'kernel'
staticdata = []
staticdata.append(str(psutil.cpu_count()))
staticdata.append(subprocess.run(['uname', '-r'], stdout=subprocess.PIPE).stdout.decode('ascii').strip())
staticdata.append(subprocess.run(['uname', '-o'], stdout=subprocess.PIPE).stdout.decode('ascii').strip())
staticdata.append(subprocess.run(['uname', '-m'], stdout=subprocess.PIPE).stdout.decode('ascii').strip())

# Read and parse the config file
def readConfig(pvcd_config_file, myhostname):
    print('Loading configuration from file "{}"'.format(pvcd_config_file))

    with open(pvcd_config_file, 'r') as cfgfile:
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
            'log_keepalives': o_config['pvc']['system']['configuration']['logging']['log_keepalives'],
            'log_keepalive_cluster_details': o_config['pvc']['system']['configuration']['logging']['log_keepalive_cluster_details'],
            'log_keepalive_storage_details': o_config['pvc']['system']['configuration']['logging']['log_keepalive_storage_details'],
            'console_log_lines': o_config['pvc']['system']['configuration']['logging']['console_log_lines'],
            'keepalive_interval': o_config['pvc']['system']['fencing']['intervals']['keepalive_interval'],
            'fence_intervals': o_config['pvc']['system']['fencing']['intervals']['fence_intervals'],
            'suicide_intervals': o_config['pvc']['system']['fencing']['intervals']['suicide_intervals'],
            'successful_fence': o_config['pvc']['system']['fencing']['actions']['successful_fence'],
            'failed_fence': o_config['pvc']['system']['fencing']['actions']['failed_fence'],
            'migration_target_selector': o_config['pvc']['system']['migration']['target_selector'],
            'ipmi_hostname': o_config['pvc']['system']['fencing']['ipmi']['host'],
            'ipmi_username': o_config['pvc']['system']['fencing']['ipmi']['user'],
            'ipmi_password': o_config['pvc']['system']['fencing']['ipmi']['pass']
        }
    except Exception as e:
        print('ERROR: {}!'.format(e))
        exit(1)
    config = config_general

    # Handle debugging config
    try:
        config_debug = {
            'debug': o_config['debug']
        }
    except:
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
            print('ERROR: {}!'.format(e))
            exit(1)
        config = {**config, **config_networking}

        # Create the by-id address entries
        for net in [ 'vni',
                     'storage',
                     'upstream' ]:
            address_key = '{}_dev_ip'.format(net)
            floating_key = '{}_floating_ip'.format(net)
            network_key = '{}_network'.format(net)

            # Verify the network provided is valid
            try:
                network = ipaddress.ip_network(config[network_key])
            except Exception as e:
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
                floating_addr = ipaddress.ip_address(config[floating_key].split('/')[0])
                # Verify we're in the network
                if not floating_addr in list(network.hosts()):
                    raise
            except Exception as e:
                print('ERROR: Floating address {} for {} is not valid!'.format(config[floating_key], floating_key))
                exit(1)

    # Handle the storage config
    if config['enable_storage']:
        try:
            config_storage = dict()
        except Exception as e:
            print('ERROR: {}!'.format(e))
            exit(1)
        config = {**config, **config_storage}

    # Handle an empty ipmi_hostname
    if config['ipmi_hostname'] == '':
        config['ipmi_hostname'] = myshorthostname + '-lom.' + mydomainname

    return config

# Get the config object from readConfig()
config = readConfig(pvcd_config_file, myhostname)
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
logger.out('Starting pvcd on host {}'.format(myfqdn), state='s')

###############################################################################
# PHASE 2a - Create local IP addresses for static networks
###############################################################################

if enable_networking:
    # VNI configuration
    vni_dev = config['vni_dev']
    vni_mtu = config['vni_mtu']
    vni_dev_ip = config['vni_dev_ip']
    logger.out('Setting up VNI network interface {}'.format(vni_dev, vni_dev_ip), state='i')
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
    if storage_dev == vni_dev:
        storage_dev = 'brcluster'
        storage_mtu = vni_mtu
    storage_dev_ip = config['storage_dev_ip']
    logger.out('Setting up Storage network on interface {} with IP {}'.format(storage_dev, storage_dev_ip), state='i')
    common.run_os_command('ip link set {} mtu {} up'.format(storage_dev, storage_mtu))
    common.run_os_command('ip address add {} dev {}'.format(storage_dev_ip, storage_dev))

    # Upstream configuration
    if config['upstream_dev']:
        upstream_dev = config['upstream_dev']
        upstream_mtu = config['upstream_mtu']
        upstream_dev_ip = config['upstream_dev_ip']
        upstream_dev_gateway = config['upstream_gateway']
        logger.out('Setting up Upstream network on interface {} with IP {}'.format(upstream_dev, upstream_dev_ip), state='i')
        common.run_os_command('ip link set {} mtu {} up'.format(upstream_dev, upstream_mtu))
        common.run_os_command('ip address add {} dev {}'.format(upstream_dev_ip, upstream_dev))
        if upstream_dev_gateway:
            common.run_os_command('ip route add default via {} dev {}'.format(upstream_dev_gateway, upstream_dev))

###############################################################################
# PHASE 2b - Prepare sysctl for pvcd
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

    # Disable RP filtering on the VNI dev and bridge interfaces (to allow traffic pivoting)
    common.run_os_command('sysctl net.ipv4.conf.{}.rp_filter=0'.format(config['vni_dev']))
    common.run_os_command('sysctl net.ipv4.conf.{}.rp_filter=0'.format(config['upstream_dev']))
    common.run_os_command('sysctl net.ipv4.conf.brcluster.rp_filter=0')
    common.run_os_command('sysctl net.ipv6.conf.{}.rp_filter=0'.format(config['vni_dev']))
    common.run_os_command('sysctl net.ipv6.conf.{}.rp_filter=0'.format(config['upstream_dev']))
    common.run_os_command('sysctl net.ipv6.conf.brcluster.rp_filter=0')

###############################################################################
# PHASE 3a - Determine coordinator mode
###############################################################################

# What is the list of coordinator hosts
coordinator_nodes = config['coordinators']

if myhostname in coordinator_nodes:
    # We are indeed a coordinator host
    config['daemon_mode'] = 'coordinator'
    # Start the zookeeper service using systemctl
    logger.out('Node is a ' + logger.fmt_blue + 'coordinator' + logger.fmt_end, state='i')
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
            _zk_conn = kazoo.client.KazooClient(hosts=config['coordinators'])
            try:
                _zk_conn.start()
                zk_conn = _zk_conn
                break
            except:
                time.sleep(1)
zk_conn.add_listener(zk_listener)

###############################################################################
# PHASE 5 - Gracefully handle termination
###############################################################################

# Cleanup function
def cleanup():
    global zk_conn, update_timer, d_domains

    logger.out('Performing final keepalive update', state='s')
    update_zookeeper()

    # Set shutdown state in Zookeeper
    zkhandler.writedata(zk_conn, { '/nodes/{}/daemonstate'.format(myhostname): 'shutdown' })

    logger.out('Terminating pvcd and cleaning up', state='s')

    # Stop keepalive thread
    try:
        stopKeepaliveTimer()
    except NameError:
        pass
    except AttributeError:
        pass

    # Stop console logging on all VMs
    logger.out('Stopping domain console watchers', state='s')
    for domain in d_domain:
        if d_domain[domain].getnode() == myhostname:
            try:
                d_domain[domain].console_log_instance.stop()
            except NameError as e:
                pass
            except AttributeError as e:
                pass

    # Force into secondary network state if needed
    if zkhandler.readdata(zk_conn, '/nodes/{}/routerstate'.format(myhostname)) == 'primary':
        is_primary = True
        zkhandler.writedata(zk_conn, {
            '/nodes/{}/routerstate'.format(myhostname): 'secondary',
            '/primary_node': 'none'
        })
        logger.out('Waiting 3 seconds for primary migration', state='s')
        time.sleep(3)

    # Set stop state in Zookeeper
    zkhandler.writedata(zk_conn, { '/nodes/{}/daemonstate'.format(myhostname): 'stop' })

    # Forcibly terminate dnsmasq because it gets stuck sometimes
    common.run_os_command('killall dnsmasq')

    # Close the Zookeeper connection
    try:
        zk_conn.stop()
        zk_conn.close()
    except:
        pass

    logger.out('Terminated pvc daemon', state='s')
    sys.exit(0)

# Termination function
def term(signum='', frame=''):
    cleanup()

# Handle signals gracefully
signal.signal(signal.SIGTERM, term)
signal.signal(signal.SIGINT, term)
signal.signal(signal.SIGQUIT, term)

###############################################################################
# PHASE 6 - Prepare host in Zookeeper
###############################################################################

# Check if our node exists in Zookeeper, and create it if not
if zk_conn.exists('/nodes/{}'.format(myhostname)):
    logger.out("Node is " + logger.fmt_green + "present" + logger.fmt_end + " in Zookeeper", state='i')
    # Update static data just in case it's changed
    zkhandler.writedata(zk_conn, {
        '/nodes/{}/daemonstate'.format(myhostname): 'init',
        '/nodes/{}/staticdata'.format(myhostname): ' '.join(staticdata),
    # Keepalives and fencing information (always load and set from config on boot)
        '/nodes/{}/ipmihostname'.format(myhostname): config['ipmi_hostname'],
        '/nodes/{}/ipmiusername'.format(myhostname): config['ipmi_username'],
        '/nodes/{}/ipmipassword'.format(myhostname): config['ipmi_password']
    })
else:
    logger.out("Node is " + logger.fmt_red + "absent" + logger.fmt_end + " in Zookeeper; adding new node", state='i')
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
    logger.out('Current primary node is {}{}{}.'.format(logger.fmt_blue, current_primary, logger.fmt_end), state='i')
else:
    if config['daemon_mode'] == 'coordinator':
        logger.out('No primary node found; creating with us as primary.', state='i')
        zkhandler.writedata(zk_conn, { '/primary_node': myhostname })

###############################################################################
# PHASE 7 - Ensure Libvirt is working
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
    add chain inet filter forward {{ type filter hook forward priority 0; }}
    add chain inet filter input {{ type filter hook input priority 0; }}
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
d_volume = dict() # Dict of Dicts
node_list = []
network_list = []
domain_list = []
osd_list = []
pool_list = []
volume_list = dict() # Dict of Lists

if enable_networking:
    # Create an instance of the DNS Aggregator if we're a coordinator
    if config['daemon_mode'] == 'coordinator':
        dns_aggregator = DNSAggregatorInstance.DNSAggregatorInstance(zk_conn, config, logger)
    else:
        dns_aggregator = None
else:
    dns_aggregator = None

# Node objects
@zk_conn.ChildrenWatch('/nodes')
def update_nodes(new_node_list):
    global node_list, d_node

    # Add any missing nodes to the list
    for node in new_node_list:
        if not node in node_list:
            d_node[node] = NodeInstance.NodeInstance(node, myhostname, zk_conn, config, logger, d_node, d_network, d_domain, dns_aggregator)

    # Remove any deleted nodes from the list
    for node in node_list:
        if not node in new_node_list:
            # Delete the object
            del(d_node[node])

    # Update and print new list
    node_list = new_node_list
    logger.out('{}Node list:{} {}'.format(logger.fmt_blue, logger.fmt_end, ' '.join(node_list)), state='i')

    # Update node objects' list
    for node in d_node:
        d_node[node].update_node_list(d_node)

# Alias for our local node (passed to network and domain objects)
this_node = d_node[myhostname]

# Primary node
@zk_conn.DataWatch('/primary_node')
def update_primary(new_primary, stat, event=''):
    try:
        new_primary = new_primary.decode('ascii')
    except AttributeError:
        new_primary = 'none'

    if new_primary != this_node.primary_node:
        if config['daemon_mode'] == 'coordinator':
            # We're a coordinator and there is no primary
            if new_primary == 'none':
                if this_node.daemon_state == 'run' and this_node.router_state != 'primary':
                    logger.out('Contending for primary coordinator state', state='i')
                    zkhandler.writedata(zk_conn, {'/primary_node': myhostname})
            elif new_primary == myhostname:
                zkhandler.writedata(zk_conn, {'/nodes/{}/routerstate'.format(myhostname): 'primary'})
            else:
                zkhandler.writedata(zk_conn, {'/nodes/{}/routerstate'.format(myhostname): 'secondary'})
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
            if not network in network_list:
                d_network[network] = VXNetworkInstance.VXNetworkInstance(network, zk_conn, config, logger, this_node)
                if config['daemon_mode'] == 'coordinator' and d_network[network].nettype == 'managed':
                    dns_aggregator.add_network(d_network[network])
                # Start primary functionality
                if this_node.router_state == 'primary' and d_network[network].nettype == 'managed':
                    d_network[network].createGateways()
                    d_network[network].startDHCPServer()

        # Remove any deleted networks from the list
        for network in network_list:
            if not network in new_network_list:
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
        logger.out('{}Network list:{} {}'.format(logger.fmt_blue, logger.fmt_end, ' '.join(network_list)), state='i')

        # Update node objects' list
        for node in d_node:
            d_node[node].update_network_list(d_network)

if enable_hypervisor:
    # VM domain objects
    @zk_conn.ChildrenWatch('/domains')
    def update_domains(new_domain_list):
        global domain_list, d_domain

        # Add any missing domains to the list
        for domain in new_domain_list:
            if not domain in domain_list:
                d_domain[domain] = VMInstance.VMInstance(domain, zk_conn, config, logger, this_node)

        # Remove any deleted domains from the list
        for domain in domain_list:
            if not domain in new_domain_list:
                # Delete the object
                del(d_domain[domain])

        # Update and print new list
        domain_list = new_domain_list
        logger.out('{}Domain list:{} {}'.format(logger.fmt_blue, logger.fmt_end, ' '.join(domain_list)), state='i')

        # Update node objects' list
        for node in d_node:
            d_node[node].update_domain_list(d_domain)

if enable_storage:
    # Ceph OSD provisioning key
    @zk_conn.DataWatch('/ceph/cmd')
    def cmd(data, stat, event=''):
        if data:
            CephInstance.run_command(zk_conn, logger, this_node, data.decode('ascii'), d_osd)

    # OSD objects
    @zk_conn.ChildrenWatch('/ceph/osds')
    def update_osds(new_osd_list):
        global osd_list, d_osd

        # Add any missing OSDs to the list
        for osd in new_osd_list:
            if not osd in osd_list:
                d_osd[osd] = CephInstance.CephOSDInstance(zk_conn, this_node, osd)

        # Remove any deleted OSDs from the list
        for osd in osd_list:
            if not osd in new_osd_list:
                # Delete the object
                del(d_osd[osd])

        # Update and print new list
        osd_list = new_osd_list
        logger.out('{}OSD list:{} {}'.format(logger.fmt_blue, logger.fmt_end, ' '.join(osd_list)), state='i')

    # Pool objects
    @zk_conn.ChildrenWatch('/ceph/pools')
    def update_pools(new_pool_list):
        global pool_list, d_pool

        # Add any missing Pools to the list
        for pool in new_pool_list:
            if not pool in pool_list:
                d_pool[pool] = CephInstance.CephPoolInstance(zk_conn, this_node, pool)
                d_volume[pool] = dict()
                volume_list[pool] = []

        # Remove any deleted Pools from the list
        for pool in pool_list:
            if not pool in new_pool_list:
                # Delete the object
                del(d_pool[pool])

        # Update and print new list
        pool_list = new_pool_list
        logger.out('{}Pool list:{} {}'.format(logger.fmt_blue, logger.fmt_end, ' '.join(pool_list)), state='i')

        # Volume objects in each pool
        for pool in pool_list:
            @zk_conn.ChildrenWatch('/ceph/volumes/{}'.format(pool))
            def update_volumes(new_volume_list):
                global volume_list, d_volume

                # Add any missing Volumes to the list
                for volume in new_volume_list:
                    if not volume in volume_list[pool]:
                        d_volume[pool][volume] = CephInstance.CephVolumeInstance(zk_conn, this_node, pool, volume)

                # Remove any deleted Volumes from the list
                for volume in volume_list[pool]:
                    if not volume in new_volume_list:
                        # Delete the object
                        del(d_volume[pool][volume])

                # Update and print new list
                volume_list[pool] = new_volume_list
                logger.out('{}Volume list [{pool}]:{} {plist}'.format(logger.fmt_blue, logger.fmt_end, pool=pool, plist=' '.join(volume_list[pool])), state='i')

###############################################################################
# PHASE 9 - Run the daemon
###############################################################################

# Zookeeper keepalive update function
def update_zookeeper():
    # Get past state and update if needed
    if debug:
        print("Get past state and update if needed")
    past_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(this_node.name))
    if past_state != 'run':
        this_node.daemon_state = 'run'
        zkhandler.writedata(zk_conn, { '/nodes/{}/daemonstate'.format(this_node.name): 'run' })
    else:
        this_node.daemon_state = 'run'

    # Ensure the primary key is properly set
    if debug:
        print("Ensure the primary key is properly set")
    if this_node.router_state == 'primary':
        if zkhandler.readdata(zk_conn, '/primary_node') != this_node.name:
            zkhandler.writedata(zk_conn, {'/primary_node': this_node.name})

    if enable_storage:
        # Get Ceph cluster health (for local printing)
        if debug:
            print("Get Ceph cluster health (for local printing)")
        retcode, stdout, stderr = common.run_os_command('ceph --connect-timeout=1 health')
        ceph_health = stdout.rstrip()
        if 'HEALTH_OK' in ceph_health:
            ceph_health_colour = logger.fmt_green
        elif 'HEALTH_WARN' in ceph_health:
            ceph_health_colour = logger.fmt_yellow
        else:
            ceph_health_colour = logger.fmt_red

        # Set ceph health information in zookeeper (primary only)
        if this_node.router_state == 'primary':
            if debug:
                print("Set ceph health information in zookeeper (primary only)")
            # Get status info
            retcode, stdout, stderr = common.run_os_command('ceph --connect-timeout=1 status')
            ceph_status = stdout
            try:
                zkhandler.writedata(zk_conn, {
                    '/ceph': str(ceph_status)
                })
            except:
                logger.out('Failed to set Ceph status data', state='e')
                return

        # Set ceph rados df information in zookeeper (primary only)
        if this_node.router_state == 'primary':
            if debug:
                print("Set ceph rados df information in zookeeper (primary only)")
            # Get rados df info
            retcode, stdout, stderr = common.run_os_command('rados df')
            rados_df = stdout
            try:
                zkhandler.writedata(zk_conn, {
                    '/ceph/radosdf': str(rados_df)
                })
            except:
                logger.out('Failed to set Rados space data', state='e')
                return

        # Set pool information in zookeeper (primary only)
        if this_node.router_state == 'primary':
            if debug:
                print("Set pool information in zookeeper (primary only)")
            # Get pool info
            pool_df = dict()
            retcode, stdout, stderr = common.run_os_command('rados df --format json')
            pool_df_raw = json.loads(stdout)['pools']
            for pool in pool_df_raw:
                pool_df.update({
                    str(pool['name']): {
                        'id': pool['id'],
                        'size_bytes': pool['size_bytes'],
                        'num_objects': pool['num_objects'],
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
                })

            # Trigger updates for each pool on this node
            for pool in pool_list:
                zkhandler.writedata(zk_conn, {
                    '/ceph/pools/{}/stats'.format(pool): str(json.dumps(pool_df[pool]))
                })

        # Only grab OSD stats if there are OSDs to grab (otherwise `ceph osd df` hangs)
        osds_this_node = 0
        if len(osd_list) > 0:
            # Get data from Ceph OSDs
            if debug:
                print("Get data from Ceph OSDs")
            # Parse the dump data
            osd_dump = dict()
            retcode, stdout, stderr = common.run_os_command('ceph --connect-timeout=1 osd dump --format json')
            osd_dump_raw = json.loads(stdout)['osds']
            if debug:
                print("Loop through OSD dump")
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
                print("Parse the OSD df data")
            osd_df = dict()
            retcode, stdout, stderr = common.run_os_command('ceph --connect-timeout=1 osd df --format json')
            try:
                osd_df_raw = json.loads(stdout)['nodes']
            except:
                logger.out('Failed to parse OSD list', state='w')

            if debug:
                print("Loop through OSD df")
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
                print("Parse the OSD status data")
            osd_status = dict()
            retcode, stdout, stderr = common.run_os_command('ceph --connect-timeout=1 osd status')
            if debug:
                print("Loop through OSD status data")
            for line in stderr.split('\n'):
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
                print("Merge OSD data together")
            osd_stats = dict()
            for osd in osd_list:
                this_dump = osd_dump[osd]
                this_dump.update(osd_df[osd])
                this_dump.update(osd_status[osd])
                osd_stats[osd] = this_dump

            # Trigger updates for each OSD on this node
            if debug:
                print("Trigger updates for each OSD on this node")
            for osd in osd_list:
                if d_osd[osd].node == myhostname:
                    zkhandler.writedata(zk_conn, {
                        '/ceph/osds/{}/stats'.format(osd): str(json.dumps(osd_stats[osd]))
                    })
                    osds_this_node += 1

    memalloc = 0
    vcpualloc = 0
    if enable_hypervisor:
        # Toggle state management of dead VMs to restart them
        if debug:
            print("Toggle state management of dead VMs to restart them")
        for domain, instance in this_node.d_domain.items():
            if domain in this_node.domain_list:
                # Add the allocated memory to our memalloc value
                memalloc += instance.getmemory()
                vcpualloc += instance.getvcpus()
                if instance.getstate() == 'start' and instance.getnode() == this_node.name:
                    if instance.getdom() != None:
                        try:
                            if instance.getdom().state()[0] != libvirt.VIR_DOMAIN_RUNNING:
                                raise
                        except Exception as e:
                            # Toggle a state "change"
                            zkhandler.writedata(zk_conn, { '/domains/{}/state'.format(domain): instance.getstate() })

        # Connect to libvirt
        if debug:
            print("Connect to libvirt")
        libvirt_name = "qemu:///system"
        lv_conn = libvirt.open(libvirt_name)
        if lv_conn == None:
            logger.out('Failed to open connection to "{}"'.format(libvirt_name), state='e')
            return

        # Ensure that any running VMs are readded to the domain_list
        if debug:
            print("Ensure that any running VMs are readded to the domain_list")
        running_domains = lv_conn.listAllDomains(libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE)
        for domain in running_domains:
            domain_uuid = domain.UUIDString()
            if domain_uuid not in this_node.domain_list:
                this_node.domain_list.append(domain_uuid)

    # Set our information in zookeeper
    if debug:
        print("Set our information in zookeeper")
    #this_node.name = lv_conn.getHostname()
    this_node.memtotal = int(psutil.virtual_memory().total / 1024 / 1024)
    this_node.memused = int(psutil.virtual_memory().used / 1024 / 1024)
    this_node.memfree = int(psutil.virtual_memory().free / 1024 / 1024)
    this_node.memalloc = memalloc
    this_node.vcpualloc = vcpualloc
    this_node.cpuload = os.getloadavg()[0]
    if enable_hypervisor:
        this_node.domains_count = len(lv_conn.listDomainsID())
    else:
        this_node.domains_count = 0
    keepalive_time = int(time.time())
    try:
        zkhandler.writedata(zk_conn, {
            '/nodes/{}/memtotal'.format(this_node.name): str(this_node.memtotal),
            '/nodes/{}/memused'.format(this_node.name): str(this_node.memused),
            '/nodes/{}/memfree'.format(this_node.name): str(this_node.memfree),
            '/nodes/{}/memalloc'.format(this_node.name): str(this_node.memalloc),
            '/nodes/{}/vcpualloc'.format(this_node.name): str(this_node.vcpualloc),
            '/nodes/{}/cpuload'.format(this_node.name): str(this_node.cpuload),
            '/nodes/{}/domainscount'.format(this_node.name): str(this_node.domains_count),
            '/nodes/{}/runningdomains'.format(this_node.name): ' '.join(this_node.domain_list),
            '/nodes/{}/keepalive'.format(this_node.name): str(keepalive_time)
        })
    except:
        logger.out('Failed to set keepalive data', state='e')
        return

    if enable_hypervisor:
        # Close the Libvirt connection
        lv_conn.close()

    # Display node information to the terminal
    if config['log_keepalives']:
        logger.out(
            '{}{} keepalive{}'.format(
                logger.fmt_purple,
                myhostname,
                logger.fmt_end
            ),
            state='t'
        )
        if config['log_keepalive_cluster_details']:
            logger.out(
                '{bold}Domains:{nofmt} {domcount}  '
                '{bold}Networks:{nofmt} {netcount}  '
                '{bold}VM memory [MiB]:{nofmt} {allocmem}  '
                '{bold}Free memory [MiB]:{nofmt} {freemem}  '
                '{bold}Used memory [MiB]:{nofmt} {usedmem}  '
                '{bold}Load:{nofmt} {load}'.format(
                    bold=logger.fmt_bold,
                    nofmt=logger.fmt_end,
                    domcount=this_node.domains_count,
                    freemem=this_node.memfree,
                    usedmem=this_node.memused,
                    load=this_node.cpuload,
                    allocmem=this_node.memalloc,
                    netcount=len(network_list)
                ),
            )
        if enable_storage and config['log_keepalive_storage_details']:
            logger.out(
                '{bold}Ceph cluster status:{nofmt} {health_colour}{health}{nofmt}  '
                '{bold}Total OSDs:{nofmt} {total_osds}  '
                '{bold}Node OSDs:{nofmt} {node_osds}  '
                '{bold}Pools:{nofmt} {total_pools}  '.format(
                    bold=logger.fmt_bold,
                    health_colour=ceph_health_colour,
                    nofmt=logger.fmt_end,
                    health=ceph_health,
                    total_osds=len(osd_list),
                    node_osds=osds_this_node,
                    total_pools=len(pool_list)
                ),
            )

    # Look for dead nodes and fence them
    if debug:
        print("Look for dead nodes and fence them")
    if config['daemon_mode'] == 'coordinator':
        for node_name in d_node:
            try:
                node_daemon_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(node_name))
                node_domain_state = zkhandler.readdata(zk_conn, '/nodes/{}/domainstate'.format(node_name))
                node_keepalive = int(zkhandler.readdata(zk_conn, '/nodes/{}/keepalive'.format(node_name)))
            except:
                node_daemon_state = 'unknown'
                node_domain_state = 'unknown'
                node_keepalive = 0

            # Handle deadtime and fencng if needed
            # (A node is considered dead when its keepalive timer is >6*keepalive_interval seconds
            # out-of-date while in 'start' state)
            node_deadtime = int(time.time()) - ( int(config['keepalive_interval']) * int(config['fence_intervals']) )
            if node_keepalive < node_deadtime and node_daemon_state == 'run':
                logger.out('Node {} seems dead - starting monitor for fencing'.format(node_name), state='w')
                zk_lock = zkhandler.writelock(zk_conn, '/nodes/{}/daemonstate'.format(node_name))
                with zk_lock:
                    # Ensures that, if we lost the lock race and come out of waiting,
                    # we won't try to trigger our own fence thread.
                    if zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(node_name)) != 'dead':
                        fence_thread = threading.Thread(target=fencing.fenceNode, args=(node_name, zk_conn, config, logger), kwargs={})
                        fence_thread.start()
                    # Write the updated data after we start the fence thread
                    zkhandler.writedata(zk_conn, { '/nodes/{}/daemonstate'.format(node_name): 'dead' })

# Start keepalive thread
update_timer = startKeepaliveTimer()

# Tick loop; does nothing since everything else is async
while True:
    try:
        time.sleep(1)
    except:
        break
