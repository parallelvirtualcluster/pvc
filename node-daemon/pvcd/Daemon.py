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
import json
import apscheduler.schedulers.background

import pvcd.log as log
import pvcd.zkhandler as zkhandler
import pvcd.fencing as fencing
import pvcd.common as common

import pvcd.DomainInstance as DomainInstance
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
    global update_timer
    interval = int(config['keepalive_interval'])
    logger.out('Starting keepalive timer ({} second interval)'.format(interval), state='s')
    update_timer.add_job(update_zookeeper, 'interval', seconds=interval)
    update_timer.start()

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
mynodeid = re.findall(r'\d+', myhostname)[-1]

# Gather useful data about our host
# Static data format: 'cpu_count', 'arch', 'os', 'kernel'
staticdata = []
staticdata.append(str(psutil.cpu_count()))
staticdata.append(subprocess.run(['uname', '-r'], stdout=subprocess.PIPE).stdout.decode('ascii').strip())
staticdata.append(subprocess.run(['uname', '-o'], stdout=subprocess.PIPE).stdout.decode('ascii').strip())
staticdata.append(subprocess.run(['uname', '-m'], stdout=subprocess.PIPE).stdout.decode('ascii').strip())

# Create our timer object
update_timer = apscheduler.schedulers.background.BackgroundScheduler()

# Config values dictionary
config_values = [
    'coordinators',
    'dynamic_directory',
    'log_directory',
    'file_logging',
    'keepalive_interval',
    'fence_intervals',
    'suicide_intervals',
    'successful_fence',
    'failed_fence',
    'migration_target_selector',
    'vni_dev',
    'vni_dev_ip',
    'vni_floating_ip',
    'storage_dev',
    'storage_dev_ip',
    'upstream_dev',
    'upstream_dev_ip',
    'upstream_floating_ip',
    'ipmi_hostname',
    'ipmi_username',
    'ipmi_password'
]

# Read and parse the config file
def readConfig(pvcd_config_file, myhostname):
    print('Loading configuration from file "{}"'.format(pvcd_config_file))

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

# Get the config object from readConfig()
config = readConfig(pvcd_config_file, myhostname)

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
# PHASE 1d - Prepare sysctl for pvcd
###############################################################################

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

# Disable RP filtering on the VNI dev interface (to allow traffic pivoting from primary)
common.run_os_command('sysctl net.ipv4.conf.{}.rp_filter=0'.format(config['vni_dev']))
common.run_os_command('sysctl net.ipv6.conf.{}.rp_filter=0'.format(config['vni_dev']))

###############################################################################
# PHASE 2 - Determine coordinator mode and start Zookeeper on coordinators
###############################################################################

# What is the list of coordinator hosts
coordinator_hosts = config['coordinators'].split(',')

if myhostname in coordinator_hosts:
    # We are indeed a coordinator host
    config['daemon_mode'] = 'coordinator'
    # Start the zookeeper service using systemctl
    logger.out('Node is a ' + logger.fmt_blue + 'coordinator' + logger.fmt_end +'; starting Zookeeper daemon', state='i')
    common.run_os_command('systemctl start zookeeper.service')
    time.sleep(1)
else:
    config['daemon_mode'] = 'hypervisor'

###############################################################################
# PHASE 3 - Attempt to connect to the coordinators and start zookeeper client
###############################################################################

# Start the connection to the coordinators
zk_conn = kazoo.client.KazooClient(hosts=config['coordinators'])
try:
    logger.out('Connecting to Zookeeper cluster hosts {}'.format(config['coordinators']), state='i')
    # Start connection
    zk_conn.start()
except Exception as e:
    logger.out('ERROR: Failed to connect to Zookeeper cluster: {}'.format(e), state='e')
    exit(1)

# Handle zookeeper failures
def zk_listener(state):
    global zk_conn, update_timer
    if state == kazoo.client.KazooState.SUSPENDED:
        logger.out('Connection to Zookeeper lost; retrying', state='w')

        # Stop keepalive thread
        if update_timer:
            stopKeepaliveTimer()

        while True:
            _zk_conn = kazoo.client.KazooClient(hosts=config['coordinators'])
            try:
                _zk_conn.start()
                zk_conn = _zk_conn
                break
            except:
                time.sleep(1)
    elif state == kazoo.client.KazooState.CONNECTED:
        logger.out('Connection to Zookeeper restarted', state='o')

        # Start keepalive thread
        if update_timer:
            update_timer = createKeepaliveTimer()
    else:
        pass
zk_conn.add_listener(zk_listener)

###############################################################################
# PHASE 4 - Gracefully handle termination
###############################################################################

# Cleanup function
def cleanup():
    global zk_conn, update_timer

    # Stop keepalive thread
    stopKeepaliveTimer()

    logger.out('Terminating pvcd and cleaning up', state='s')

    # Force into secondary network state if needed
    if zkhandler.readdata(zk_conn, '/nodes/{}/routerstate'.format(myhostname)) == 'primary':
        is_primary = True
        zkhandler.writedata(zk_conn, {
            '/nodes/{}/routerstate'.format(myhostname): 'secondary',
            '/primary_node': 'none'
        })
    else:
        is_primary = False

    # Wait for things to flush
    if is_primary:
        logger.out('Waiting for primary migration', state='s')
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

# Handle exit gracefully
atexit.register(cleanup)

# Termination function
def term(signum='', frame=''):
    # Exit
    sys.exit(0)

# Handle signals gracefully
signal.signal(signal.SIGTERM, term)
signal.signal(signal.SIGINT, term)
signal.signal(signal.SIGQUIT, term)

###############################################################################
# PHASE 5 - Prepare host in Zookeeper
###############################################################################

# Check if our node exists in Zookeeper, and create it if not
if zk_conn.exists('/nodes/{}'.format(myhostname)):
    logger.out("Node is " + logger.fmt_green + "present" + logger.fmt_end + " in Zookeeper", state='i')
    zkhandler.writedata(zk_conn, { '/nodes/{}/daemonstate'.format(myhostname): 'init' })
    # Update static data just in case it's changed
    zkhandler.writedata(zk_conn, { '/nodes/{}/staticdata'.format(myhostname): ' '.join(staticdata) })
else:
    logger.out("Node is " + logger.fmt_red + "absent" + logger.fmt_end + " in Zookeeper; adding new node", state='i')
    keepalive_time = int(time.time())
    transaction = zk_conn.transaction()
    transaction.create('/nodes/{}'.format(myhostname), config['daemon_mode'].encode('ascii'))
    # Basic state information
    transaction.create('/nodes/{}/daemonmode'.format(myhostname), config['daemon_mode'].encode('ascii'))
    transaction.create('/nodes/{}/daemonstate'.format(myhostname), 'init'.encode('ascii'))
    transaction.create('/nodes/{}/routerstate'.format(myhostname), 'client'.encode('ascii'))
    transaction.create('/nodes/{}/domainstate'.format(myhostname), 'flushed'.encode('ascii'))
    transaction.create('/nodes/{}/staticdata'.format(myhostname), ' '.join(staticdata).encode('ascii'))
    transaction.create('/nodes/{}/memfree'.format(myhostname), '0'.encode('ascii'))
    transaction.create('/nodes/{}/memused'.format(myhostname), '0'.encode('ascii'))
    transaction.create('/nodes/{}/memalloc'.format(myhostname), '0'.encode('ascii'))
    transaction.create('/nodes/{}/vcpualloc'.format(myhostname), '0'.encode('ascii'))
    transaction.create('/nodes/{}/cpuload'.format(myhostname), '0.0'.encode('ascii'))
    transaction.create('/nodes/{}/networkscount'.format(myhostname), '0'.encode('ascii'))
    transaction.create('/nodes/{}/domainscount'.format(myhostname), '0'.encode('ascii'))
    transaction.create('/nodes/{}/runningdomains'.format(myhostname), ''.encode('ascii'))
    # Keepalives and fencing information
    transaction.create('/nodes/{}/keepalive'.format(myhostname), str(keepalive_time).encode('ascii'))
    transaction.create('/nodes/{}/ipmihostname'.format(myhostname), config['ipmi_hostname'].encode('ascii'))
    transaction.create('/nodes/{}/ipmiusername'.format(myhostname), config['ipmi_username'].encode('ascii'))
    transaction.create('/nodes/{}/ipmipassword'.format(myhostname), config['ipmi_password'].encode('ascii'))
    transaction.commit()

# Check that the primary key exists, and create it with us as master if not
current_primary = zkhandler.readdata(zk_conn, '/primary_node')
if current_primary and current_primary != 'none':
    logger.out('Current primary node is {}{}{}.'.format(logger.fmt_blue, current_primary, logger.fmt_end), state='i')
else:
    if config['daemon_mode'] == 'coordinator':
        logger.out('No primary node found; creating with us as primary.', state='i')
        zkhandler.writedata(zk_conn, { '/primary_node': myhostname })

###############################################################################
# PHASE 6 - Create local IP addresses for static networks
###############################################################################

# VNI configuration
vni_dev = config['vni_dev']
vni_dev_ip = config['vni_dev_ip']
logger.out('Setting up VNI network on interface {} with IP {}'.format(vni_dev, vni_dev_ip), state='i')
common.run_os_command('ip link set {} up'.format(vni_dev))
common.run_os_command('ip address add {} dev {}'.format(vni_dev_ip, vni_dev))

# Storage configuration
storage_dev = config['storage_dev']
storage_dev_ip = config['storage_dev_ip']
logger.out('Setting up Storage network on interface {} with IP {}'.format(storage_dev, storage_dev_ip), state='i')
common.run_os_command('ip link set {} up'.format(storage_dev))
common.run_os_command('ip address add {} dev {}'.format(storage_dev_ip, storage_dev))

# Upstream configuration
if config['daemon_mode'] == 'coordinator':
    upstream_dev = config['upstream_dev']
    upstream_dev_ip = config['upstream_dev_ip']
    logger.out('Setting up Upstream network on interface {} with IP {}'.format(upstream_dev, upstream_dev_ip), state='i')
    common.run_os_command('ip link set {} up'.format(upstream_dev))
    common.run_os_command('ip address add {} dev {}'.format(upstream_dev_ip, upstream_dev))

###############################################################################
# PHASE 7a - Ensure Libvirt is running on the local host
###############################################################################

# Start the zookeeper service using systemctl
logger.out('Starting Libvirt daemon', state='i')
common.run_os_command('systemctl start libvirtd.service')
time.sleep(1)

# Check that libvirtd is listening TCP
libvirt_check_name = "qemu+tcp://127.0.0.1:16509/system"
logger.out('Connecting to Libvirt daemon at {}'.format(libvirt_check_name), state='i')
try:
    lv_conn = libvirt.open(libvirt_check_name)
    lv_conn.close()
except Exception as e:
    logger.out('ERROR: Failed to connect to Libvirt daemon: {}'.format(e), state='e')
    exit(1)

###############################################################################
# PHASE 7b - Ensure Ceph is running on the local host
###############################################################################

# if coordinator, start ceph-mon
# if hypervisor or coodinator, start ceph-osds

###############################################################################
# PHASE 7c - Ensure NFT is running on the local host
###############################################################################

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
node_list = []
network_list = []
domain_list = []
osd_list = []

# Create an instance of the DNS Aggregator if we're a coordinator
if config['daemon_mode'] == 'coordinator':
    dns_aggregator = DNSAggregatorInstance.DNSAggregatorInstance(zk_conn, config, logger, d_network)
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
                    logger.out('Contending for primary routing state', state='i')
                    zkhandler.writedata(zk_conn, {'/primary_node': myhostname})
            elif new_primary == myhostname:
                zkhandler.writedata(zk_conn, {'/nodes/{}/routerstate'.format(myhostname): 'primary'})
            else:
                zkhandler.writedata(zk_conn, {'/nodes/{}/routerstate'.format(myhostname): 'secondary'})
        else:
            zkhandler.writedata(zk_conn, {'/nodes/{}/routerstate'.format(myhostname): 'client'})

        for node in d_node:
            d_node[node].primary_node = new_primary

# Network objects
@zk_conn.ChildrenWatch('/networks')
def update_networks(new_network_list):
    global network_list, d_network

    # Add any missing networks to the list
    for network in new_network_list:
        if not network in network_list:
            d_network[network] = VXNetworkInstance.VXNetworkInstance(network, zk_conn, config, logger, this_node)
            # Start primary functionality
            if this_node.router_state == 'primary':
                dns_aggregator.add_client_network(network)
                d_network[network].createGatewayAddress()
                d_network[network].startDHCPServer()

    # Remove any deleted networks from the list
    for network in network_list:
        if not network in new_network_list:
            # Stop primary functionality
            if this_node.router_state == 'primary':
                d_network[network].stopDHCPServer()
                d_network[network].removeGatewayAddress()
                dns_aggregator.remove_client_network(network)
            # Stop general functionality
            d_network[network].removeFirewall()
            d_network[network].removeNetwork()
            # Delete the object
            del(d_network[network])

#    if config['daemon_mode'] == 'coordinator':
#        # Update the DNS aggregator
#        dns_aggregator.update_network_list(d_network)
            
    # Update and print new list
    network_list = new_network_list
    logger.out('{}Network list:{} {}'.format(logger.fmt_blue, logger.fmt_end, ' '.join(network_list)), state='i')

    # Update node objects' list
    for node in d_node:
        d_node[node].update_network_list(d_network)

# VM domain objects
@zk_conn.ChildrenWatch('/domains')
def update_domains(new_domain_list):
    global domain_list, d_domain

    # Add any missing domains to the list
    for domain in new_domain_list:
        if not domain in domain_list:
            d_domain[domain] = DomainInstance.DomainInstance(domain, zk_conn, config, logger, this_node)

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

# Ceph OSD provisioning key
@zk_conn.DataWatch('/ceph/osd_cmd')
def osd_cmd(data, stat, event=''):
    if data:
        data = data.decode('ascii')
    else:
        data = ''

    if data:
        # Get the command and args
        command, args = data.split()

        # Adding a new OSD
        if command == 'add':
            node, device = args.split(',')
            if node == this_node.name:
                # Clean up the command queue
                zkhandler.writedata(zk_conn, {'/ceph/osd_cmd': ''})
                # Add the OSD
                CephInstance.add_osd(zk_conn, logger, node, device)
        # Removing an OSD
        elif command == 'remove':
            osd_id = args

            # Verify osd_id is in the list
            if not d_osd[osd_id]:
                return True

            if d_osd[osd_id].node == this_node.name:
                # Clean up the command queue
                zkhandler.writedata(zk_conn, {'/ceph/osd_cmd': ''})
                # Remove the OSD
                CephInstance.remove_osd(zk_conn, logger, osd_id, d_osd[osd_id])

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

###############################################################################
# PHASE 9 - Run the daemon
###############################################################################

# Zookeeper keepalive update function
def update_zookeeper():
    # Get past state and update if needed
    past_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(this_node.name))
    if past_state != 'run':
        this_node.daemon_state = 'run'
        zkhandler.writedata(zk_conn, { '/nodes/{}/daemonstate'.format(this_node.name): 'run' })
    else:
        this_node.daemon_state = 'run'

    # Ensure the primary key is properly set
    if this_node.router_state == 'primary':
        if zkhandler.readdata(zk_conn, '/primary_node') != this_node.name:
            zkhandler.writedata(zk_conn, {'/primary_node': this_node.name})

    # Get Ceph cluster health (for local printing)
    retcode, stdout, stderr = common.run_os_command('ceph health')
    ceph_health = stdout.rstrip()
    if 'HEALTH_OK' in ceph_health:
        ceph_health_colour = logger.fmt_green
    elif 'HEALTH_WARN' in ceph_health:
        ceph_health_colour = logger.fmt_yellow
    else:
        ceph_health_colour = logger.fmt_red

    # Set ceph health information in zookeeper (primary only)
    if this_node.router_state == 'primary':
        # Get status info
        retcode, stdout, stderr = common.run_os_command('ceph status')
        ceph_status = stdout
        try:
            zkhandler.writedata(zk_conn, {
                '/ceph': str(ceph_status)
            })
        except:
            logger.out('Failed to set Ceph status data', state='e')
            return

    # Get data from Ceph OSDs
    # Parse the dump data
    osd_dump = dict()
    retcode, stdout, stderr = common.run_os_command('ceph osd dump --format json')
    osd_dump_raw = json.loads(stdout)['osds']
    for osd in osd_dump_raw:
        osd_dump.update({
            str(osd['osd']): {
                'uuid': osd['uuid'],
                'up': osd['up'],
                'in': osd['in'],
                'weight': osd['weight'],
                'primary_affinity': osd['primary_affinity']
            }
        })
    # Parse the status data
    osd_status = dict()
    retcode, stdout, stderr = common.run_os_command('ceph osd status')
    for line in stderr.split('\n'):
        # Strip off colour
        line = re.sub(r'\x1b(\[.*?[@-~]|\].*?(\x07|\x1b\\))', '', line)
        # Split it for parsing
        line = line.split()
        if len(line) > 1 and line[1].isdigit():
            # This is an OSD line so parse it
            osd_id = line[1]
            host = line[3].split('.')[0]
            used = line[5]
            avail = line[7]
            wr_ops = line[9]
            wr_data = line[11]
            rd_ops = line[13]
            rd_data = line[15]
            state = line[17]
            osd_status.update({
#            osd_stats.update({
                str(osd_id): { 
                    'host': host,
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
    osd_stats = dict()
    for osd in osd_list:
        this_dump = osd_dump[osd]
        this_dump.update(osd_status[osd])
        osd_stats[osd] = this_dump

    # Trigger updates for each OSD on this node
    osds_this_host = 0
    for osd in osd_list:
        if d_osd[osd].node == myhostname:
            zkhandler.writedata(zk_conn, {
                '/ceph/osds/{}/stats'.format(osd): str(osd_stats[osd])
            })
            osds_this_host += 1


    # Toggle state management of dead VMs to restart them
    memalloc = 0
    vcpualloc = 0
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
    libvirt_name = "qemu:///system"
    lv_conn = libvirt.open(libvirt_name)
    if lv_conn == None:
        logger.out('Failed to open connection to "{}"'.format(libvirt_name), state='e')
        return

    # Ensure that any running VMs are readded to the domain_list
    running_domains = lv_conn.listAllDomains(libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE)
    for domain in running_domains:
        domain_uuid = domain.UUIDString()
        if domain_uuid not in this_node.domain_list:
            this_node.domain_list.append(domain_uuid)

    # Set our information in zookeeper
    #this_node.name = lv_conn.getHostname()
    this_node.memused = int(psutil.virtual_memory().used / 1024 / 1024)
    this_node.memfree = int(psutil.virtual_memory().free / 1024 / 1024)
    this_node.memalloc = memalloc
    this_node.vcpualloc = vcpualloc
    this_node.cpuload = os.getloadavg()[0]
    this_node.domains_count = len(lv_conn.listDomainsID())
    keepalive_time = int(time.time())
    try:
        zkhandler.writedata(zk_conn, {
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

    # Close the Libvirt connection
    lv_conn.close()

    # Update our local node lists
    flushed_node_list = []
    active_node_list = []
    inactive_node_list = []
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
            zkhandler.writedata(zk_conn, { '/nodes/{}/daemonstate'.format(node_name): 'dead' })
            fence_thread = threading.Thread(target=fencing.fenceNode, args=(node_name, zk_conn, config, logger), kwargs={})
            fence_thread.start()

    # Display node information to the terminal
    logger.out(
        '{}{} keepalive{}'.format(
            logger.fmt_purple,
            myhostname,
            logger.fmt_end
        ),
        state='t'
    )
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
    logger.out(
        '{bold}Ceph cluster status:{nofmt} {health_colour}{health}{nofmt}  '
        '{bold}Total OSDs:{nofmt} {total_osds}  '
        '{bold}Host OSDs:{nofmt} {host_osds}'.format(
            bold=logger.fmt_bold,
            health_colour=ceph_health_colour,
            nofmt=logger.fmt_end,
            health=ceph_health,
            total_osds=len(osd_list),
            host_osds=osds_this_host
        ),
    )


# Start keepalive thread and immediately update Zookeeper
startKeepaliveTimer()
update_zookeeper()

# Tick loop; does nothing since everything else is async
while True:
    try:
        time.sleep(1)
    except:
        break
