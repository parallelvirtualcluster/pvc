#!/usr/bin/python3

# dnsmasq-zookeeper-leases.py - DNSMASQ leases script for Zookeeper
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
import argparse
import os
import sys
import kazoo.client
import re
import yaml

#
# Variables
#
#
# General Functions
#
def get_zookeeper_key():
    # Get the interface from environment (passed by dnsmasq)
    try:
        interface = os.environ['DNSMASQ_BRIDGE_INTERFACE']
    except Exception as e:
        print('ERROR: DNSMASQ_BRIDGE_INTERFACE environment variable not found: {}'.format(e), file=sys.stderr)
        exit(1)
    # Get the ID of the interface (the digits)
    network_vni = re.findall(r'\d+', interface)[0]
    # Create the key
    zookeeper_key = '/networks/{}/dhcp4_leases'.format(network_vni)
    return zookeeper_key

def get_lease_expiry():
    try:
        expiry = os.environ['DNSMASQ_LEASE_EXPIRES']
    except Exception:
        expiry = '0'
    return expiry

def get_client_id():
    try:
        client_id = os.environ['DNSMASQ_CLIENT_ID']
    except Exception:
        client_id = '*'
    return client_id

def connect_zookeeper():
    # We expect the environ to contain the config file
    try:
        pvcnoded_config_file = os.environ['PVCD_CONFIG_FILE']
    except Exception:
        # Default place
        pvcnoded_config_file = '/etc/pvc/pvcnoded.yaml'

    with open(pvcnoded_config_file, 'r') as cfgfile:
        try:
            o_config = yaml.load(cfgfile)
        except Exception as e:
            print('ERROR: Failed to parse configuration file: {}'.format(e), file=sys.stderr)
            exit(1)

    try:
        zk_conn = kazoo.client.KazooClient(hosts=o_config['pvc']['cluster']['coordinators'])
        zk_conn.start()
    except Exception as e:
        print('ERROR: Failed to connect to Zookeeper: {}'.format(e), file=sys.stderr)
        exit(1)

    return zk_conn

def read_data(zk_conn, key):
    return zk_conn.get(key)[0].decode('ascii')

def get_lease(zk_conn, zk_leases_key, macaddr):
    expiry = read_data(zk_conn, '{}/{}/expiry'.format(zk_leases_key, macaddr))
    ipaddr = read_data(zk_conn, '{}/{}/ipaddr'.format(zk_leases_key, macaddr))
    hostname = read_data(zk_conn, '{}/{}/hostname'.format(zk_leases_key, macaddr))
    clientid = read_data(zk_conn, '{}/{}/clientid'.format(zk_leases_key, macaddr))
    return expiry, ipaddr, hostname, clientid

#
# Command Functions
#
def read_lease_database(zk_conn, zk_leases_key):
    leases_list = zk_conn.get_children(zk_leases_key)
    output_list = []
    for macaddr in leases_list:
        expiry, ipaddr, hostname, clientid = get_lease(zk_conn, zk_leases_key, macaddr)
        data_string = '{} {} {} {} {}'.format(expiry, macaddr, ipaddr, hostname, clientid)
        print('Reading lease from Zookeeper: {}'.format(data_string), file=sys.stderr)
        output_list.append('{}'.format(data_string))

    # Output list
    print('\n'.join(output_list))

def add_lease(zk_conn, zk_leases_key, expiry, macaddr, ipaddr, hostname, clientid):
    if not hostname:
        hostname = ''
    transaction = zk_conn.transaction()
    transaction.create('{}/{}'.format(zk_leases_key, macaddr), ''.encode('ascii'))
    transaction.create('{}/{}/expiry'.format(zk_leases_key, macaddr), expiry.encode('ascii'))
    transaction.create('{}/{}/ipaddr'.format(zk_leases_key, macaddr), ipaddr.encode('ascii'))
    transaction.create('{}/{}/hostname'.format(zk_leases_key, macaddr), hostname.encode('ascii'))
    transaction.create('{}/{}/clientid'.format(zk_leases_key, macaddr), clientid.encode('ascii'))
    transaction.commit()

def del_lease(zk_conn, zk_leases_key, macaddr, expiry):
    zk_conn.delete('{}/{}'.format(zk_leases_key, macaddr), recursive=True)


#
# Instantiate the parser
#
parser = argparse.ArgumentParser(description='Store or retrieve dnsmasq leases in Zookeeper')
parser.add_argument('action', type=str, help='Action')
parser.add_argument('macaddr', type=str, help='MAC Address', nargs='?', default=None)
parser.add_argument('ipaddr', type=str, help='IP Address', nargs='?', default=None)
parser.add_argument('hostname', type=str, help='Hostname', nargs='?', default=None)
args = parser.parse_args()

action = args.action
macaddr = args.macaddr
ipaddr = args.ipaddr
hostname = args.hostname

zk_conn = connect_zookeeper()
zk_leases_key = get_zookeeper_key()

if action == 'init':
    read_lease_database(zk_conn, zk_leases_key)
    exit(0)

expiry = get_lease_expiry()
clientid = get_client_id()

#
# Choose action
#
print('Lease action - {} {} {} {}'.format(action, macaddr, ipaddr, hostname), file=sys.stderr)
if action == 'add':
    add_lease(zk_conn, zk_leases_key, expiry, macaddr, ipaddr, hostname, clientid)
elif action == 'del':
    del_lease(zk_conn, zk_leases_key, macaddr, expiry)
elif action == 'old':
    pass
