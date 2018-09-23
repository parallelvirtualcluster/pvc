#!/usr/bin/env python3

# network.py - PVC client function library, Network fuctions
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

import os
import socket
import time
import uuid
import re
import tempfile
import subprocess
import difflib
import colorama
import click
import lxml.objectify
import configparser
import kazoo.client

import client_lib.ansiiprint as ansiiprint
import client_lib.common as common

#
# Cluster search functions
#
def getClusterNetworkList(zk_conn):
    # Get a list of VNIs by listing the children of /networks
    vni_list = zk_conn.get_children('/networks')
    description_list = []
    # For each VNI, get the corresponding description from the data
    for vni in vni_list:
        description_list.append(zk_conn.get('/networks/{}'.format(vni))[0].decode('ascii'))
    return vni_list, description_list

def searchClusterByVNI(zk_conn, vni):
    try:
        # Get the lists
        vni_list, description_list = getClusterNetworkList(zk_conn)
        # We're looking for UUID, so find that element ID
        index = vni_list.index(vni)
        # Get the name_list element at that index
        description = description_list[index]
    except ValueError:
        # We didn't find anything
        return None

    return description

def searchClusterByDescription(zk_conn, description):
    try:
        # Get the lists
        vni_list, description_list = getClusterNetworkList(zk_conn)
        # We're looking for name, so find that element ID
        index = description_list.index(description)
        # Get the uuid_list element at that index
        vni = vni_list[index]
    except ValueError:
        # We didn't find anything
        return None

    return vni

def getNetworkVNI(zk_conn, network):
    # Validate and obtain alternate passed value
    if network.isdigit():
        net_description = searchClusterByVNI(zk_conn, network)
        net_vni = searchClusterByDescription(zk_conn, net_description)
    else:
        net_vni = searchClusterByDescription(zk_conn, network)
        net_description = searchClusterByVNI(zk_conn, net_vni)

    return net_vni

def getNetworkDescription(zk_conn, network):
    # Validate and obtain alternate passed value
    if network.isdigit():
        net_description = searchClusterByVNI(zk_conn, network)
        net_vni = searchClusterByDescription(zk_conn, net_description)
    else:
        net_vni = searchClusterByDescription(zk_conn, network)
        net_description = searchClusterByVNI(zk_conn, net_vni)

    return net_description

def getNetworkDHCPReservations(zk_conn, vni):
    n_dhcp_reservations = zk_conn.get_children('/networks/{}/dhcp_reservations'.format(vni))
    return None

def getNetworkFirewallRules(zk_conn, vni):
    n_firewall_rules = zk_conn.get_children('/networks/{}/firewall_rules'.format(vni))
    return None

def getNetworkInformation(zk_conn, vni):
    # Obtain basic information
    description = zk_conn.get('/networks/{}'.format(vni))[0].decode('ascii')
    ip_network = zk_conn.get('/networks/{}/ip_network'.format(vni))[0].decode('ascii')
    ip_gateway = zk_conn.get('/networks/{}/ip_gateway'.format(vni))[0].decode('ascii')
    ip_routers_raw = zk_conn.get('/networks/{}/ip_routers'.format(vni))[0].decode('ascii')
    dhcp_flag = zk_conn.get('/networks/{}/dhcp_flag'.format(vni))[0].decode('ascii')

    # Add a human-friendly space
    ip_routers = ', '.join(ip_routers_raw.split(','))

    return description, ip_network, ip_gateway, ip_routers, dhcp_flag

def formatNetworkInformation(zk_conn, vni, long_output):
    description, ip_network, ip_gateway, ip_routers, dhcp_flag = getNetworkInformation(zk_conn, vni)

    # Format a nice output: do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append('{}Virtual network information:{}'.format(ansiiprint.bold(), ansiiprint.end()))
    ainformation.append('')
    # Basic information
    ainformation.append('{}VNI:{}          {}'.format(ansiiprint.purple(), ansiiprint.end(), vni))
    ainformation.append('{}Description:{}  {}'.format(ansiiprint.purple(), ansiiprint.end(), description))
    ainformation.append('{}IP network:{}   {}'.format(ansiiprint.purple(), ansiiprint.end(), ip_network))
    ainformation.append('{}IP gateway:{}   {}'.format(ansiiprint.purple(), ansiiprint.end(), ip_gateway))
    ainformation.append('{}Routers:{}      {}'.format(ansiiprint.purple(), ansiiprint.end(), ip_routers))
    ainformation.append('{}DHCP enabled:{} {}'.format(ansiiprint.purple(), ansiiprint.end(), dhcp_flag))

    if long_output:
        dhcp_reservations = getNetworkDHCPReservations(zk_conn, vni)
        if dhcp_reservations:
            ainformation.append('')
            ainformation.append('{}Client DHCP reservations:{}'.format(ansiiprint.bold(), ansiiprint.end()))
            ainformation.append('')

        firewall_rules = getNetworkFirewallRules(zk_conn, vni)
        if firewall_rules:
            ainformation.append('')
            ainformation.append('{}Network firewall rules:{}'.format(ansiiprint.bold(), ansiiprint.end()))
            ainformation.append('')

    # Join it all together
    information = '\n'.join(ainformation)
    return information

#
# Direct functions
#
def add_network(zk_conn, vni, description, ip_network, ip_gateway, ip_routers, dhcp_flag):
    if description == '':
        description = vni

    # Check if a network with this VNI already exists
    if zk_conn.exists('/networks/{}'.format(vni)):
        return False, 'ERROR: A network with VNI {} already exists!'.format(vni)

    # Add the new network to Zookeeper
    transaction = zk_conn.transaction()
    transaction.create('/networks/{}'.format(vni), description.encode('ascii'))
    transaction.create('/networks/{}/ip_network'.format(vni), ip_network.encode('ascii'))
    transaction.create('/networks/{}/ip_gateway'.format(vni), ip_gateway.encode('ascii'))
    transaction.create('/networks/{}/ip_routers'.format(vni), ','.join(ip_routers).encode('ascii'))
    transaction.create('/networks/{}/dhcp_flag'.format(vni), str(dhcp_flag).encode('ascii'))
    transaction.create('/networks/{}/dhcp_reservations'.format(vni), ''.encode('ascii'))
    transaction.create('/networks/{}/firewall_rules'.format(vni), ''.encode('ascii'))
    results = transaction.commit()

    return True, 'Network "{}" added successfully!'.format(description)

def modify_network(zk_conn, vni, **parameters):
    # Add the new network to Zookeeper
    transaction = zk_conn.transaction()
    if parameters['description'] != None:
        transaction.set_data('/networks/{}'.format(vni), parameters['description'].encode('ascii'))
    if parameters['ip_network'] != None:
        transaction.set_data('/networks/{}/ip_network'.format(vni), parameters['ip_network'].encode('ascii'))
    if parameters['ip_gateway'] != None:
        transaction.set_data('/networks/{}/ip_gateway'.format(vni), parameters['ip_gateway'].encode('ascii'))
    if parameters['ip_routers'] != ():
        transaction.set_data('/networks/{}/ip_routers'.format(vni), ','.join(parameters['ip_routers']).encode('ascii'))
    if parameters['dhcp_flag'] != None:
        transaction.set_data('/networks/{}/dhcp_flag'.format(vni), str(parameters['dhcp_flag']).encode('ascii'))
    results = transaction.commit()
    
    return True, 'Network "{}" modified successfully!'.format(vni)

def remove_network(zk_conn, network):
    # Validate and obtain alternate passed value
    vni = getNetworkVNI(zk_conn, network)
    description = getNetworkDescription(zk_conn, network)
    if not vni:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    # Delete the configuration
    try:
        zk_conn.delete('/networks/{}'.format(vni), recursive=True)
    except:
        pass

    return True, 'Network "{}" removed successfully!'.format(description)

def get_info(zk_conn, network, long_output):
    # Validate and obtain alternate passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if net_vni == None:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    information = getNetworkInformation(zk_conn, net_vni, long_output)
    click.echo(information)
    click.echo('')

    return True, ''

def get_list(zk_conn,  limit):
    net_list = zk_conn.get_children('/networks')
    net_list_output = []

    description = {}
    ip_network = {}
    ip_gateway = {}
    ip_routers = {}
    dhcp_flag = {}

    # Gather information for printing
    for net in net_list:
        # get info
        description[net], ip_network[net], ip_gateway[net], ip_routers[net], dhcp_flag[net] = getNetworkInformation(zk_conn, net)

    # Determine optimal column widths
    # Dynamic columns: node_name, hypervisor, migrated
    net_vni_length = 5
    net_description_length = 13
    net_ip_network_length = 12
    net_ip_gateway_length = 9
    net_ip_routers_length = 9
    for net in net_list:
        # vni column
        _net_vni_length = len(net) + 1
        if _net_vni_length > net_vni_length:
            net_vni_length = _net_vni_length
        # description column
        _net_description_length = len(description[net]) + 1
        if _net_description_length > net_description_length:
            net_description_length = _net_description_length
        # ip_network column
        _net_ip_network_length = len(ip_network[net]) + 1
        if _net_ip_network_length > net_ip_network_length:
            net_ip_network_length = _net_ip_network_length
        # ip_gateway column
        _net_ip_gateway_length = len(ip_gateway[net]) + 1
        if _net_ip_gateway_length > net_ip_gateway_length:
            net_ip_gateway_length = _net_ip_gateway_length
        # ip_routers column
        _net_ip_routers_length = len(ip_routers[net]) + 1
        if _net_ip_routers_length > net_ip_routers_length:
            net_ip_routers_length = _net_ip_routers_length

    # Format the string (header)
    net_list_output_header = '{bold}\
{net_vni: <{net_vni_length}} \
{net_description: <{net_description_length}} \
{net_ip_network: <{net_ip_network_length}} \
{net_ip_gateway: <{net_ip_gateway_length}} \
{net_ip_routers: <{net_ip_routers_length}} \
{net_dhcp_flag: <8}\
{end_bold}'.format(
        bold=ansiiprint.bold(),
        end_bold=ansiiprint.end(),
        net_vni_length=net_vni_length,
        net_description_length=net_description_length,
        net_ip_network_length=net_ip_network_length,
        net_ip_gateway_length=net_ip_gateway_length,
        net_ip_routers_length=net_ip_routers_length,
        net_vni='VNI',
        net_description='Description',
        net_ip_network='Network',
        net_ip_gateway='Gateway',
        net_ip_routers='Routers',
        net_dhcp_flag='DHCP'
    )

    for net in net_list:
        net_list_output.append(
            '{bold}\
{net_vni: <{net_vni_length}} \
{net_description: <{net_description_length}} \
{net_ip_network: <{net_ip_network_length}} \
{net_ip_gateway: <{net_ip_gateway_length}} \
{net_ip_routers: <{net_ip_routers_length}} \
{net_dhcp_flag: <8}\
{end_bold}'.format(
                bold='',
                end_bold='',
                net_vni_length=net_vni_length,
                net_description_length=net_description_length,
                net_ip_network_length=net_ip_network_length,
                net_ip_gateway_length=net_ip_gateway_length,
                net_ip_routers_length=net_ip_routers_length,
                net_vni=net,
                net_description=description[net],
                net_ip_network=ip_network[net],
                net_ip_gateway=ip_gateway[net],
                net_ip_routers=ip_routers[net],
                net_dhcp_flag=dhcp_flag[net]
            )
        )

    click.echo(net_list_output_header)
    click.echo('\n'.join(sorted(net_list_output)))

    return True, ''
