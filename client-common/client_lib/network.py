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
import client_lib.zkhandler as zkhandler
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
    # Get a list of VNIs by listing the children of /networks/<vni>/dhcp_reservations
    dhcp_reservations = sorted(zk_conn.get_children('/networks/{}/dhcp_reservations'.format(vni)))
    return dhcp_reservations

def getNetworkFirewallRules(zk_conn, vni):
    firewall_rules = zk_conn.get_children('/networks/{}/firewall_rules'.format(vni))
    return None

def getNetworkInformation(zk_conn, vni):
    description = zk_conn.get('/networks/{}'.format(vni))[0].decode('ascii')
    ip_network = zk_conn.get('/networks/{}/ip_network'.format(vni))[0].decode('ascii')
    ip_gateway = zk_conn.get('/networks/{}/ip_gateway'.format(vni))[0].decode('ascii')
    dhcp_flag = zk_conn.get('/networks/{}/dhcp_flag'.format(vni))[0].decode('ascii')
    return description, ip_network, ip_gateway, dhcp_flag

def getDHCPReservationInformation(zk_conn, vni, reservation):
    description = zkhandler.readdata(zk_conn, '/networks/{}/dhcp_reservations/{}'.format(vni, reservation))
    ip_address = zkhandler.readdata(zk_conn, '/networks/{}/dhcp_reservations/{}/ipv4addr'.format(vni, reservation))
    mac_address = zkhandler.readdata(zk_conn, '/networks/{}/dhcp_reservations/{}/macaddr'.format(vni, reservation))
    return description, ip_address, mac_address

def formatNetworkInformation(zk_conn, vni, long_output):
    description, ip_network, ip_gateway, dhcp_flag = getNetworkInformation(zk_conn, vni)

    if dhcp_flag:
        dhcp_flag_colour = ansiiprint.green()
    else:
        dhcp_flag_colour = ansiiprint.blue()
    colour_off = ansiiprint.end()

    # Format a nice output: do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append('{}Virtual network information:{}'.format(ansiiprint.bold(), ansiiprint.end()))
    ainformation.append('')
    # Basic information
    ainformation.append('{}VNI:{}          {}'.format(ansiiprint.purple(), ansiiprint.end(), vni))
    ainformation.append('{}Description:{}  {}'.format(ansiiprint.purple(), ansiiprint.end(), description))
    ainformation.append('{}IP network:{}   {}'.format(ansiiprint.purple(), ansiiprint.end(), ip_network))
    ainformation.append('{}IP gateway:{}   {}'.format(ansiiprint.purple(), ansiiprint.end(), ip_gateway))
    ainformation.append('{}DHCP enabled:{} {}{}{}'.format(ansiiprint.purple(), ansiiprint.end(), dhcp_flag_colour, dhcp_flag, colour_off))

    if long_output:
        dhcp_reservations_list = zk_conn.get_children('/networks/{}/dhcp_reservations'.format(vni))
        if dhcp_reservations_list:
            ainformation.append('')
            ainformation.append('{}Client DHCP reservations:{}'.format(ansiiprint.bold(), ansiiprint.end()))
            ainformation.append('')
            dhcp_reservations_string = formatDHCPReservationList(zk_conn, vni, dhcp_reservations_list)
            for line in dhcp_reservations_string.split('\n'):
                ainformation.append(line)
        firewall_rules = zk_conn.get_children('/networks/{}/firewall_rules'.format(vni))
        if firewall_rules:
            ainformation.append('')
            ainformation.append('{}Network firewall rules:{}'.format(ansiiprint.bold(), ansiiprint.end()))
            ainformation.append('')
            formatted_firewall_rules = get_list_firewall_rules(zk_conn, vni)

    # Join it all together
    information = '\n'.join(ainformation)
    return information

def formatNetworkList(zk_conn, net_list):
    net_list_output = []
    description = {}
    ip_network = {}
    ip_gateway = {}
    dhcp_flag = {}
    dhcp_flag_colour = {}
    colour_off = ansiiprint.end()

    # Gather information for printing
    for net in net_list:
        # get info
        description[net], ip_network[net], ip_gateway[net], dhcp_flag[net] = getNetworkInformation(zk_conn, net)
        if dhcp_flag[net]:
            dhcp_flag_colour[net] = ansiiprint.green()
        else:
            dhcp_flag_colour[net] = ansiiprint.blue()

    # Determine optimal column widths
    # Dynamic columns: node_name, hypervisor, migrated
    net_vni_length = 5
    net_description_length = 13
    net_ip_network_length = 12
    net_ip_gateway_length = 9
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

    # Format the string (header)
    net_list_output_header = '{bold}\
{net_vni: <{net_vni_length}} \
{net_description: <{net_description_length}} \
{net_ip_network: <{net_ip_network_length}} \
{net_ip_gateway: <{net_ip_gateway_length}} \
{net_dhcp_flag: <8}\
{end_bold}'.format(
        bold=ansiiprint.bold(),
        end_bold=ansiiprint.end(),
        net_vni_length=net_vni_length,
        net_description_length=net_description_length,
        net_ip_network_length=net_ip_network_length,
        net_ip_gateway_length=net_ip_gateway_length,
        net_vni='VNI',
        net_description='Description',
        net_ip_network='Network',
        net_ip_gateway='Gateway',
        net_dhcp_flag='DHCP'
    )

    for net in net_list:
        net_list_output.append(
            '{bold}\
{net_vni: <{net_vni_length}} \
{net_description: <{net_description_length}} \
{net_ip_network: <{net_ip_network_length}} \
{net_ip_gateway: <{net_ip_gateway_length}} \
{dhcp_flag_colour}{net_dhcp_flag: <8}{colour_off}\
{end_bold}'.format(
                bold='',
                end_bold='',
                net_vni_length=net_vni_length,
                net_description_length=net_description_length,
                net_ip_network_length=net_ip_network_length,
                net_ip_gateway_length=net_ip_gateway_length,
                net_vni=net,
                net_description=description[net],
                net_ip_network=ip_network[net],
                net_ip_gateway=ip_gateway[net],
                net_dhcp_flag=dhcp_flag[net],
                dhcp_flag_colour=dhcp_flag_colour[net],
                colour_off=colour_off
            )
        )

    output_string = net_list_output_header + '\n' + '\n'.join(sorted(net_list_output))
    return output_string

def formatDHCPReservationList(zk_conn, vni, dhcp_reservations_list):
    dhcp_reservation_list_output = []
    description = {}
    ip_address = {}
    mac_address = {}

    # Gather information for printing
    for dhcp_reservation in dhcp_reservations_list:
        # get info
        description[dhcp_reservation], ip_address[dhcp_reservation], mac_address[dhcp_reservation] = getDHCPReservationInformation(zk_conn, vni, dhcp_reservation)
       

    # Determine optimal column widths
    # Dynamic columns: node_name, hypervisor, migrated
    reservation_description_length = 13
    reservation_ip_address_length = 13
    reservation_mac_address_length = 13
    for dhcp_reservation in dhcp_reservations_list:
        # description column
        _reservation_description_length = len(description[dhcp_reservation]) + 1
        if _reservation_description_length > reservation_description_length:
            reservation_description_length = _reservation_description_length
        # ip_network column
        _reservation_ip_address_length = len(ip_address[dhcp_reservation]) + 1
        if _reservation_ip_address_length > reservation_ip_address_length:
            reservation_ip_address_length = _reservation_ip_address_length
        # ip_gateway column
        _reservation_mac_address_length = len(mac_address[dhcp_reservation]) + 1
        if _reservation_mac_address_length > reservation_mac_address_length:
            reservation_mac_address_length = _reservation_mac_address_length

    # Format the string (header)
    dhcp_reservation_list_output_header = '{bold}\
{reservation_description: <{reservation_description_length}} \
{reservation_ip_address: <{reservation_ip_address_length}} \
{reservation_mac_address: <{reservation_mac_address_length}} \
{end_bold}'.format(
        bold=ansiiprint.bold(),
        end_bold=ansiiprint.end(),
        reservation_description_length=reservation_description_length,
        reservation_ip_address_length=reservation_ip_address_length,
        reservation_mac_address_length=reservation_mac_address_length,
        reservation_description='Description',
        reservation_ip_address='IP Address',
        reservation_mac_address='MAC Address'
    )

    for dhcp_reservation in dhcp_reservations_list:
        dhcp_reservation_list_output.append('{bold}\
{reservation_description: <{reservation_description_length}} \
{reservation_ip_address: <{reservation_ip_address_length}} \
{reservation_mac_address: <{reservation_mac_address_length}} \
{end_bold}'.format(
                bold='',
                end_bold='',
                reservation_description_length=reservation_description_length,
                reservation_ip_address_length=reservation_ip_address_length,
                reservation_mac_address_length=reservation_mac_address_length,
                reservation_description=description[dhcp_reservation],
                reservation_ip_address=ip_address[dhcp_reservation],
                reservation_mac_address=mac_address[dhcp_reservation]
            )
        )

    output_string = dhcp_reservation_list_output_header + '\n' + '\n'.join(sorted(dhcp_reservation_list_output))
    return output_string

def isValidMAC(macaddr):
    allowed = re.compile(r"""
                         (
                            ^([0-9A-F]{2}[:]){5}([0-9A-F]{2})$
                         )
                         """,
                         re.VERBOSE|re.IGNORECASE)

    if allowed.match(macaddr) is None:
        return False
    else:
        return True

def isValidIP(ipaddr):
    ip_blocks = str(ipaddr).split(".")
    if len(ip_blocks) == 4:
        for block in ip_blocks:
            # Check if number is digit, if not checked before calling this function
            if not block.isdigit():
                 return False
            tmp = int(block)
            if 0 > tmp > 255:
                 return False
        return True
    return False

#
# Direct functions
#
def add_network(zk_conn, vni, description, ip_network, ip_gateway, dhcp_flag):
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


def add_dhcp_reservation(zk_conn, network, ipaddress, macaddress, description):
    # Validate and obtain standard passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if net_vni == None:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    # Use lowercase MAC format exclusively
    macaddress = macaddress.lower()

    if not isValidMAC(macaddress):
        return False, 'ERROR: MAC address "{}" is not valid! Always use ":" as a separator.'.format(macaddress)

    if not isValidIP(ipaddress):
        return False, 'ERROR: IP address "{}" is not valid!'.format(macaddress)

    if not description:
        description = macaddress

    if zk_conn.exists('/networks/{}/dhcp_reservations/{}'.format(net_vni, description)):
        return False, 'ERROR: A reservation with description {} already exists!'.format(description)

    # Add the new network to ZK
    try:
        zkhandler.writedata(zk_conn, {
            '/networks/{}/dhcp_reservations/{}'.format(net_vni, description): description,
            '/networks/{}/dhcp_reservations/{}/macaddr'.format(net_vni, description): macaddress,
            '/networks/{}/dhcp_reservations/{}/ipv4addr'.format(net_vni, description): ipaddress
        })
    except Exception as e:
        return False, 'ERROR: Failed to write to Zookeeper! Exception: "{}".'.format(e)

    return True, 'DHCP reservation "{}" added successfully!'.format(description)

def remove_dhcp_reservation(zk_conn, network, reservation):
    # Validate and obtain standard passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if net_vni == None:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    match_description = ''

    # Check if the reservation matches a description, a mac, or an IP address currently in the database
    reservation_list = zk_conn.get_children('/networks/{}/dhcp_reservations'.format(net_vni))
    for description in reservation_list:
        macaddress = zkhandler.readdata(zk_conn, '/networks/{}/dhcp_reservations/{}/macaddr'.format(net_vni, description))
        ipaddress = zkhandler.readdata(zk_conn, '/networks/{}/dhcp_reservations/{}/ipv4addr'.format(net_vni, description))
        if reservation == description or reservation == macaddress or reservation == ipaddress:
            match_description = description
    
    if not match_description:
        return False, 'ERROR: No DHCP reservation exists matching "{}"!'.format(reservation)

    # Remove the entry from zookeeper
    try:
        zk_conn.delete('/networks/{}/dhcp_reservations/{}'.format(net_vni, match_description), recursive=True)
    except:
        return False, 'ERROR: Failed to write to Zookeeper!'

    return True, 'DHCP reservation "{}" removed successfully!'.format(match_description)

def get_info(zk_conn, network, long_output):
    # Validate and obtain alternate passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if net_vni == None:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    information = formatNetworkInformation(zk_conn, net_vni, long_output)
    click.echo(information)
    click.echo('')

    return True, ''

def get_list(zk_conn, limit):
    net_list = []
    full_net_list = zk_conn.get_children('/networks')

    for net in full_net_list:
        description = zkhandler.readdata(zk_conn, '/networks/{}'.format(net))
        if limit != None:
            try:
                # Implcitly assume fuzzy limits
                if re.match('\^.*', limit) == None:
                    limit = '.*' + limit
                if re.match('.*\$', limit) == None:
                    limit = limit + '.*'

                if re.match(limit, net) != None:
                    net_list.append(net)
                if re.match(limit, description) != None:
                    net_list.append(net)
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            net_list.append(net)

    output_string = formatNetworkList(zk_conn, net_list)
    click.echo(output_string)

    return True, ''

def get_list_dhcp_reservations(zk_conn, network, limit):
    # Validate and obtain alternate passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if net_vni == None:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    dhcp_reservations_list = []
    full_dhcp_reservations_list = zk_conn.get_children('/networks/{}/dhcp_reservations'.format(net_vni))

    for dhcp_reservation in full_dhcp_reservations_list:
        if limit != None:
            try:
                # Implcitly assume fuzzy limits
                if re.match('\^.*', limit) == None:
                    limit = '.*' + limit
                if re.match('.*\$', limit) == None:
                    limit = limit + '.*'

                if re.match(limit, net) != None:
                    dhcp_reservations_list.append(dhcp_reservation)
                if re.match(limit, description) != None:
                    dhcp_reservations_list.append(dhcp_reservation)
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            dhcp_reservations_list.append(dhcp_reservation)

    output_string = formatDHCPReservationList(zk_conn, net_vni, dhcp_reservations_list)
    click.echo(output_string)

    return True, ''

def get_list_firewall_rules(zk_conn, network):
    # Validate and obtain alternate passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if net_vni == None:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    firewall_rules = getNetworkFirewallRules(zk_conn, net_vni)
    return firewall_rules
