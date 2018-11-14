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

import client_lib.ansiprint as ansiprint
import client_lib.zkhandler as zkhandler
import client_lib.common as common

#
# Cluster search functions
#
def getClusterNetworkList(zk_conn):
    # Get a list of VNIs by listing the children of /networks
    vni_list = zkhandler.listchildren(zk_conn, '/networks')
    description_list = []
    # For each VNI, get the corresponding description from the data
    for vni in vni_list:
        description_list.append(zkhandler.readdata(zk_conn, '/networks/{}'.format(vni)))
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

def getNetworkDHCPLeases(zk_conn, vni):
    # Get a list of DHCP leases by listing the children of /networks/<vni>/dhcp_leases
    dhcp_leases = zkhandler.listchildren(zk_conn, '/networks/{}/dhcp_leases'.format(vni))
    return sorted(dhcp_leases)

def getNetworkDHCPReservations(zk_conn, vni):
    # Get a list of DHCP reservations by listing the children of /networks/<vni>/dhcp_reservations
    dhcp_reservations = zkhandler.listchildren(zk_conn, '/networks/{}/dhcp_reservations'.format(vni))
    return sorted(dhcp_reservations)

def getNetworkACLs(zk_conn, vni, _direction):
    # Get the (sorted) list of active ACLs
    if _direction == 'both':
        directions = ['in', 'out']
    else:
        directions = [_direction]

    full_acl_list = []
    for direction in directions:
        unordered_acl_list = zkhandler.listchildren(zk_conn, '/networks/{}/firewall_rules/{}'.format(vni, direction))
        ordered_acls = dict()
        for acl in unordered_acl_list:
            order = zkhandler.readdata(zk_conn, '/networks/{}/firewall_rules/{}/{}/order'.format(vni, direction, acl))
            ordered_acls[order] = acl

        for order in sorted(ordered_acls.keys()):
            full_acl_list.append({'direction': direction, 'description': ordered_acls[order]})

    return full_acl_list

def getNetworkInformation(zk_conn, vni):
    description = zkhandler.readdata(zk_conn, '/networks/{}'.format(vni))
    domain = zkhandler.readdata(zk_conn, '/networks/{}/domain'.format(vni))
    ip6_network = zkhandler.readdata(zk_conn, '/networks/{}/ip6_network'.format(vni))
    ip6_gateway = zkhandler.readdata(zk_conn, '/networks/{}/ip6_gateway'.format(vni))
    dhcp6_flag = zkhandler.readdata(zk_conn, '/networks/{}/dhcp6_flag'.format(vni))
    ip4_network = zkhandler.readdata(zk_conn, '/networks/{}/ip4_network'.format(vni))
    ip4_gateway = zkhandler.readdata(zk_conn, '/networks/{}/ip4_gateway'.format(vni))
    dhcp4_flag = zkhandler.readdata(zk_conn, '/networks/{}/dhcp4_flag'.format(vni))
    dhcp4_start = zkhandler.readdata(zk_conn, '/networks/{}/dhcp4_start'.format(vni))
    dhcp4_end = zkhandler.readdata(zk_conn, '/networks/{}/dhcp4_end'.format(vni))
    return description, domain, ip6_network, ip6_gateway, dhcp6_flag, ip4_network, ip4_gateway, dhcp4_flag, dhcp4_start, dhcp4_end

def getDHCPLeaseInformation(zk_conn, vni, mac_address):
    hostname = zkhandler.readdata(zk_conn, '/networks/{}/dhcp_leases/{}/hostname'.format(vni, mac_address))
    ip4_address = zkhandler.readdata(zk_conn, '/networks/{}/dhcp_leases/{}/ipaddr'.format(vni, mac_address))
    try:
        timestamp = zkhandler.readdata(zk_conn, '/networks/{}/dhcp_leases/{}/expiry'.format(vni, mac_address))
    except:
        timestamp = 'static'
    return hostname, ip4_address, mac_address, timestamp

def getDHCPReservationInformation(zk_conn, vni, mac_address):
    hostname = zkhandler.readdata(zk_conn, '/networks/{}/dhcp_reservations/{}/hostname'.format(vni, mac_address))
    ip4_address = zkhandler.readdata(zk_conn, '/networks/{}/dhcp_reservations/{}/ipaddr'.format(vni, mac_address))
    timestamp = 'static'
    return hostname, ip4_address, mac_address, timestamp

def getACLInformation(zk_conn, vni, direction, description):
    order = zkhandler.readdata(zk_conn, '/networks/{}/firewall_rules/{}/{}/order'.format(vni, direction, description))
    rule = zkhandler.readdata(zk_conn, '/networks/{}/firewall_rules/{}/{}/rule'.format(vni, direction, description))
    return order, description, rule

def formatNetworkInformation(zk_conn, vni, long_output):
    description, domain, ip6_network, ip6_gateway, dhcp6_flag, ip4_network, ip4_gateway, dhcp4_flag, dhcp4_start, dhcp4_end = getNetworkInformation(zk_conn, vni)

    if dhcp6_flag == "True":
        dhcp6_flag_colour = ansiprint.green()
    else:
        dhcp6_flag_colour = ansiprint.blue()
    if dhcp4_flag == "True":
        dhcp4_flag_colour = ansiprint.green()
    else:
        dhcp4_flag_colour = ansiprint.blue()
    colour_off = ansiprint.end()

    # Format a nice output: do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append('{}Virtual network information:{}'.format(ansiprint.bold(), ansiprint.end()))
    ainformation.append('')
    # Basic information
    ainformation.append('{}VNI:{}            {}'.format(ansiprint.purple(), ansiprint.end(), vni))
    ainformation.append('{}Description:{}    {}'.format(ansiprint.purple(), ansiprint.end(), description))
    ainformation.append('{}Domain:{}         {}'.format(ansiprint.purple(), ansiprint.end(), domain))
    if ip6_network != "None":
        ainformation.append('')
        ainformation.append('{}IPv6 network:{}   {}'.format(ansiprint.purple(), ansiprint.end(), ip6_network))
        ainformation.append('{}IPv6 gateway:{}   {}'.format(ansiprint.purple(), ansiprint.end(), ip6_gateway))
        ainformation.append('{}DHCPv6 enabled:{} {}{}{}'.format(ansiprint.purple(), ansiprint.end(), dhcp6_flag_colour, dhcp6_flag, colour_off))
    if ip4_network != "None":
        ainformation.append('')
        ainformation.append('{}IPv4 network:{}   {}'.format(ansiprint.purple(), ansiprint.end(), ip4_network))
        ainformation.append('{}IPv4 gateway:{}   {}'.format(ansiprint.purple(), ansiprint.end(), ip4_gateway))
        ainformation.append('{}DHCPv4 enabled:{} {}{}{}'.format(ansiprint.purple(), ansiprint.end(), dhcp4_flag_colour, dhcp4_flag, colour_off))
    if dhcp4_flag == "True":
        ainformation.append('{}DHCPv4 range:{}   {} - {}'.format(ansiprint.purple(), ansiprint.end(), dhcp4_start, dhcp4_end))

    if long_output:
        dhcp4_reservations_list = getNetworkDHCPReservations(zk_conn, vni)
        if dhcp4_reservations_list:
            ainformation.append('')
            ainformation.append('{}Client DHCPv4 reservations:{}'.format(ansiprint.bold(), ansiprint.end()))
            ainformation.append('')
            # Only show static reservations in the detailed information
            dhcp4_reservations_string = formatDHCPLeaseList(zk_conn, vni, dhcp4_reservations_list, reservations=True)
            for line in dhcp4_reservations_string.split('\n'):
                ainformation.append(line)

        firewall_rules = zkhandler.listchildren(zk_conn, '/networks/{}/firewall_rules'.format(vni))
        if firewall_rules:
            ainformation.append('')
            ainformation.append('{}Network firewall rules:{}'.format(ansiprint.bold(), ansiprint.end()))
            ainformation.append('')
            formatted_firewall_rules = get_list_firewall_rules(zk_conn, vni)

    # Join it all together
    information = '\n'.join(ainformation)
    return information

def formatNetworkList(zk_conn, net_list):
    net_list_output = []
    description = dict()
    domain = dict()
    v6_flag = dict()
    v6_flag_colour = dict()
    ip6_network = dict()
    ip6_gateway = dict()
    dhcp6_flag = dict()
    dhcp6_flag_colour = dict()
    v4_flag = dict()
    v4_flag_colour = dict()
    ip4_network = dict()
    ip4_gateway = dict()
    dhcp4_flag = dict()
    dhcp4_flag_colour = dict()
    dhcp4_start = dict()
    dhcp4_end = dict()
    dhcp4_range = dict()
    colour_off = ansiprint.end()

    # Gather information for printing
    for net in net_list:
        # get info
        description[net], domain[net], ip6_network[net], ip6_gateway[net], dhcp6_flag[net], ip4_network[net], ip4_gateway[net], dhcp4_flag[net], dhcp4_start[net], dhcp4_end[net] = getNetworkInformation(zk_conn, net)

        if ip4_network[net] != "None":
            v4_flag_colour[net] = ansiprint.green()
            v4_flag[net] = 'True'
        else:
            v4_flag_colour[net] = ansiprint.blue()
            v4_flag[net] = 'False'

        if ip6_network[net] != "None":
            v6_flag_colour[net] = ansiprint.green()
            v6_flag[net] = 'True'
        else:
            v6_flag_colour[net] = ansiprint.blue()
            v6_flag[net] = 'False'

        if dhcp6_flag[net] == "True":
            dhcp6_flag_colour[net] = ansiprint.green()
        else:
            dhcp6_flag_colour[net] = ansiprint.blue()

        if dhcp4_flag[net] == "True":
            dhcp4_flag_colour[net] = ansiprint.green()
            dhcp4_range[net] = '{} - {}'.format(dhcp4_start[net], dhcp4_end[net])
        else:
            dhcp4_flag_colour[net] = ansiprint.blue()
            dhcp4_range[net] = 'N/A'

    # Determine optimal column widths
    # Dynamic columns: node_name, hypervisor, migrated
    net_vni_length = 5
    net_description_length = 13
    net_domain_length = 8
    net_v6_flag_length = 6
    net_dhcp6_flag_length = 7
    net_v4_flag_length = 6
    net_dhcp4_flag_length = 7
    for net in net_list:
        # vni column
        _net_vni_length = len(net) + 1
        if _net_vni_length > net_vni_length:
            net_vni_length = _net_vni_length
        # description column
        _net_description_length = len(description[net]) + 1
        if _net_description_length > net_description_length:
            net_description_length = _net_description_length
        # domain column
        _net_domain_length = len(domain[net]) + 1
        if _net_domain_length > net_domain_length:
            net_domain_length = _net_domain_length

    # Format the string (header)
    net_list_output_header = '{bold}\
{net_vni: <{net_vni_length}} \
{net_description: <{net_description_length}} \
{net_domain: <{net_domain_length}}  \
{net_v6_flag: <{net_v6_flag_length}} \
{net_dhcp6_flag: <{net_dhcp6_flag_length}} \
{net_v4_flag: <{net_v4_flag_length}} \
{net_dhcp4_flag: <{net_dhcp4_flag_length}} \
{end_bold}'.format(
        bold=ansiprint.bold(),
        end_bold=ansiprint.end(),
        net_vni_length=net_vni_length,
        net_description_length=net_description_length,
        net_domain_length=net_domain_length,
        net_v6_flag_length=net_v6_flag_length,
        net_dhcp6_flag_length=net_dhcp6_flag_length,
        net_v4_flag_length=net_v4_flag_length,
        net_dhcp4_flag_length=net_dhcp4_flag_length,
        net_vni='VNI',
        net_description='Description',
        net_domain='Domain',
        net_v6_flag='IPv6',
        net_dhcp6_flag='DHCPv6',
        net_v4_flag='IPv4',
        net_dhcp4_flag='DHCPv4',
    )

    for net in net_list:
        net_list_output.append(
            '{bold}\
{net_vni: <{net_vni_length}} \
{net_description: <{net_description_length}} \
{net_domain: <{net_domain_length}}  \
{v6_flag_colour}{net_v6_flag: <{net_v6_flag_length}}{colour_off} \
{dhcp6_flag_colour}{net_dhcp6_flag: <{net_dhcp6_flag_length}}{colour_off} \
{v4_flag_colour}{net_v4_flag: <{net_v4_flag_length}}{colour_off} \
{dhcp4_flag_colour}{net_dhcp4_flag: <{net_dhcp4_flag_length}}{colour_off} \
{end_bold}'.format(
                bold='',
                end_bold='',
                net_vni_length=net_vni_length,
                net_description_length=net_description_length,
                net_domain_length=net_domain_length,
                net_v6_flag_length=net_v6_flag_length,
                net_dhcp6_flag_length=net_dhcp6_flag_length,
                net_v4_flag_length=net_v4_flag_length,
                net_dhcp4_flag_length=net_dhcp4_flag_length,
                net_vni=net,
                net_description=description[net],
                net_domain=domain[net],
                net_v6_flag=v6_flag[net],
                v6_flag_colour=v6_flag_colour[net],
                net_dhcp6_flag=dhcp6_flag[net],
                dhcp6_flag_colour=dhcp6_flag_colour[net],
                net_v4_flag=v4_flag[net],
                v4_flag_colour=v4_flag_colour[net],
                net_dhcp4_flag=dhcp4_flag[net],
                dhcp4_flag_colour=dhcp4_flag_colour[net],
                colour_off=colour_off
            )
        )

    output_string = net_list_output_header + '\n' + '\n'.join(sorted(net_list_output))
    return output_string

def formatDHCPLeaseList(zk_conn, vni, dhcp_leases_list, reservations=False):
    dhcp_lease_list_output = []
    hostname = dict()
    ip4_address = dict()
    mac_address = dict()
    timestamp = dict()

    # Gather information for printing
    for dhcp_lease in dhcp_leases_list:
        if reservations:
            hostname[dhcp_lease], ip4_address[dhcp_lease], mac_address[dhcp_lease], timestamp[dhcp_lease] = getDHCPReservationInformation(zk_conn, vni, dhcp_lease)
        else:
            hostname[dhcp_lease], ip4_address[dhcp_lease], mac_address[dhcp_lease], timestamp[dhcp_lease] = getDHCPLeaseInformation(zk_conn, vni, dhcp_lease)

    # Determine optimal column widths
    lease_hostname_length = 9
    lease_ip4_address_length = 11
    lease_mac_address_length = 13
    lease_timestamp_length = 13
    for dhcp_lease in dhcp_leases_list:
        # hostname column
        _lease_hostname_length = len(hostname[dhcp_lease]) + 1
        if _lease_hostname_length > lease_hostname_length:
            lease_hostname_length = _lease_hostname_length
        # ip4_address column
        _lease_ip4_address_length = len(ip4_address[dhcp_lease]) + 1
        if _lease_ip4_address_length > lease_ip4_address_length:
            lease_ip4_address_length = _lease_ip4_address_length
        # mac_address column
        _lease_mac_address_length = len(mac_address[dhcp_lease]) + 1
        if _lease_mac_address_length > lease_mac_address_length:
            lease_mac_address_length = _lease_mac_address_length

    # Format the string (header)
    dhcp_lease_list_output_header = '{bold}\
{lease_hostname: <{lease_hostname_length}} \
{lease_ip4_address: <{lease_ip4_address_length}} \
{lease_mac_address: <{lease_mac_address_length}} \
{lease_timestamp: <{lease_timestamp_length}} \
{end_bold}'.format(
        bold=ansiprint.bold(),
        end_bold=ansiprint.end(),
        lease_hostname_length=lease_hostname_length,
        lease_ip4_address_length=lease_ip4_address_length,
        lease_mac_address_length=lease_mac_address_length,
        lease_timestamp_length=lease_timestamp_length,
        lease_hostname='Hostname',
        lease_ip4_address='IP Address',
        lease_mac_address='MAC Address',
        lease_timestamp='Timestamp'
    )

    for dhcp_lease in dhcp_leases_list:
        dhcp_lease_list_output.append('{bold}\
{lease_hostname: <{lease_hostname_length}} \
{lease_ip4_address: <{lease_ip4_address_length}} \
{lease_mac_address: <{lease_mac_address_length}} \
{lease_timestamp: <{lease_timestamp_length}} \
{end_bold}'.format(
                bold='',
                end_bold='',
                lease_hostname_length=lease_hostname_length,
                lease_ip4_address_length=lease_ip4_address_length,
                lease_mac_address_length=lease_mac_address_length,
                lease_timestamp_length=12,
                lease_hostname=hostname[dhcp_lease],
                lease_ip4_address=ip4_address[dhcp_lease],
                lease_mac_address=mac_address[dhcp_lease],
                lease_timestamp=timestamp[dhcp_lease]
            )
        )

    output_string = dhcp_lease_list_output_header + '\n' + '\n'.join(sorted(dhcp_lease_list_output))
    return output_string

def formatACLList(zk_conn, vni, _direction, acl_list):
    acl_list_output = []
    direction = dict()
    order = dict()
    description = dict()
    rule = dict()

    if _direction is None:
        directions = ['in', 'out']
    else:
        directions = [_direction]

    # Gather information for printing
    for acl in acl_list:
        acld = acl['description']
        order[acld], description[acld], rule[acld] = getACLInformation(zk_conn, vni, acl['direction'], acl['description'])
        direction[acld] = acl['direction']

    # Determine optimal column widths
    acl_direction_length = 10
    acl_order_length = 6
    acl_description_length = 12
    acl_rule_length = 5
    for acl in acl_list:
        acld = acl['description']
        # order column
        _acl_order_length = len(order[acld]) + 1
        if _acl_order_length > acl_order_length:
            acl_order_length = _acl_order_length
        # description column
        _acl_description_length = len(description[acld]) + 1
        if _acl_description_length > acl_description_length:
            acl_description_length = _acl_description_length
        # rule column
        _acl_rule_length = len(rule[acld]) + 1
        if _acl_rule_length > acl_rule_length:
            acl_rule_length = _acl_rule_length

    # Format the string (header)
    acl_list_output_header = '{bold}\
{acl_direction: <{acl_direction_length}} \
{acl_order: <{acl_order_length}} \
{acl_description: <{acl_description_length}} \
{acl_rule: <{acl_rule_length}} \
{end_bold}'.format(
        bold=ansiprint.bold(),
        end_bold=ansiprint.end(),
        acl_direction_length=acl_direction_length,
        acl_order_length=acl_order_length,
        acl_description_length=acl_description_length,
        acl_rule_length=acl_rule_length,
        acl_direction='Direction',
        acl_order='Order',
        acl_description='Description',
        acl_rule='Rule',
    )

    for acl in acl_list:
        acld = acl['description']
        acl_list_output.append('{bold}\
{acl_direction: <{acl_direction_length}} \
{acl_order: <{acl_order_length}} \
{acl_description: <{acl_description_length}} \
{acl_rule: <{acl_rule_length}} \
{end_bold}'.format(
                bold='',
                end_bold='',
                acl_direction_length=acl_direction_length,
                acl_order_length=acl_order_length,
                acl_description_length=acl_description_length,
                acl_rule_length=acl_rule_length,
                acl_direction=direction[acld],
                acl_order=order[acld],
                acl_description=description[acld],
                acl_rule=rule[acld],
            )
        )

    output_string = acl_list_output_header + '\n' + '\n'.join(sorted(acl_list_output))
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
    ip4_blocks = str(ipaddr).split(".")
    if len(ip4_blocks) == 4:
        for block in ip4_blocks:
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
def add_network(zk_conn, vni, description, domain,
                ip4_network, ip4_gateway, ip6_network, ip6_gateway,
                dhcp4_flag, dhcp4_start, dhcp4_end):
    # Ensure start and end DHCP ranges are set if the flag is set
    if dhcp4_flag and ( not dhcp4_start or not dhcp4_end ):
        return False, 'ERROR: DHCPv4 start and end addresses are required for a DHCPv4-enabled network.'

    # Check if a network with this VNI or description already exists
    if zkhandler.exists(zk_conn, '/networks/{}'.format(vni)):
        return False, 'ERROR: A network with VNI {} already exists!'.format(vni)
    for network in zkhandler.listchildren(zk_conn, '/networks'):
        network_description = zkhandler.readdata(zk_conn, '/networks/{}'.format(network))
        if network_description == description:
            return False, 'ERROR: A network with description {} already exists!'.format(description)

    # We're generating the default gateway to be ip6_network::1/YY
    if ip6_network:
        dhcp6_flag = 'True'
        if not ip6_gateway:
            ip6_netpart, ip6_maskpart = ip6_network.split('/')
            ip6_gateway = '{}1'.format(ip6_netpart)
    else:
        dhcp6_flag = 'False'

    # Add the new network to Zookeeper
    zkhandler.writedata(zk_conn, {
        '/networks/{}'.format(vni): description,
        '/networks/{}/domain'.format(vni): domain,
        '/networks/{}/ip6_network'.format(vni): ip6_network,
        '/networks/{}/ip6_gateway'.format(vni): ip6_gateway,
        '/networks/{}/dhcp6_flag'.format(vni): dhcp6_flag,
        '/networks/{}/ip4_network'.format(vni): ip4_network,
        '/networks/{}/ip4_gateway'.format(vni): ip4_gateway,
        '/networks/{}/dhcp4_flag'.format(vni): dhcp4_flag,
        '/networks/{}/dhcp4_start'.format(vni): dhcp4_start,
        '/networks/{}/dhcp4_end'.format(vni): dhcp4_end,
        '/networks/{}/dhcp4_leases'.format(vni): '',
        '/networks/{}/dhcp4_reservations'.format(vni): '',
        '/networks/{}/firewall_rules'.format(vni): '',
        '/networks/{}/firewall_rules/in'.format(vni): '',
        '/networks/{}/firewall_rules/out'.format(vni): ''
    })

    return True, 'Network "{}" added successfully!'.format(description)

def modify_network(zk_conn, vni, **parameters):
    # Add the new network to Zookeeper
    zk_data = dict()
    if parameters['description'] != None:
        zk_data.update({'/networks/{}'.format(vni): parameters['description']})
    if parameters['domain'] != None:
        zk_data.update({'/networks/{}/domain'.format(vni): parameters['domain']})
    if parameters['ip4_network'] != None:
        zk_data.update({'/networks/{}/ip4_network'.format(vni): parameters['ip4_network']})
    if parameters['ip4_gateway'] != None:
        zk_data.update({'/networks/{}/ip4_gateway'.format(vni): parameters['ip4_gateway']})
    if parameters['ip6_network'] != None:
        zk_data.update({'/networks/{}/ip6_network'.format(vni): parameters['ip6_network']})
        if parameters['ip6_network'] != '':
            zk_data.update({'/networks/{}/dhcp6_flag'.format(vni): 'True'})
        else:
            zk_data.update({'/networks/{}/dhcp6_flag'.format(vni): 'False'})
    if parameters['ip6_gateway'] != None:
        zk_data.update({'/networks/{}/ip6_gateway'.format(vni): parameters['ip6_gateway']})
    else:
        # If we're changing the network, but don't also specify the gateway,
        # generate a new one automatically
        if parameters['ip6_network'] != None:
            ip6_netpart, ip6_maskpart = parameters['ip6_network'].split('/')
            ip6_gateway = '{}1'.format(ip6_netpart)
            zk_data.update({'/networks/{}/ip6_gateway'.format(vni): ip6_gateway})
    if parameters['dhcp_flag'] != None:
        zk_data.update({'/networks/{}/dhcp_flag'.format(vni): parameters['dhcp_flag']})
    if parameters['dhcp_start'] != None:
        zk_data.update({'/networks/{}/dhcp_start'.format(vni): parameters['dhcp_start']})
    if parameters['dhcp_end'] != None:
        zk_data.update({'/networks/{}/dhcp_end'.format(vni): parameters['dhcp_end']})

    zkhandler.writedata(zk_conn, zk_data)
    
    return True, 'Network "{}" modified successfully!'.format(vni)

def remove_network(zk_conn, network):
    # Validate and obtain alternate passed value
    vni = getNetworkVNI(zk_conn, network)
    description = getNetworkDescription(zk_conn, network)
    if not vni:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    # Delete the configuration
    zkhandler.deletekey(zk_conn, '/networks/{}'.format(vni))

    return True, 'Network "{}" removed successfully!'.format(description)


def add_dhcp_reservation(zk_conn, network, ipaddress, macaddress, hostname):
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

    if zkhandler.exists(zk_conn, '/networks/{}/dhcp_reservations/{}'.format(net_vni, macaddress)):
        return False, 'ERROR: A reservation with MAC "{}" already exists!'.format(macaddress)

    # Add the new static lease to ZK
    try:
        zkhandler.writedata(zk_conn, {
            '/networks/{}/dhcp_reservations/{}'.format(net_vni, macaddress): 'static',
            '/networks/{}/dhcp_reservations/{}/hostname'.format(net_vni, macaddress): hostname,
            '/networks/{}/dhcp_reservations/{}/ipaddr'.format(net_vni, macaddress): ipaddress
        })
    except Exception as e:
        return False, 'ERROR: Failed to write to Zookeeper! Exception: "{}".'.format(e)

    return True, 'DHCP reservation "{}" added successfully!'.format(macaddress)

def remove_dhcp_reservation(zk_conn, network, reservation):
    # Validate and obtain standard passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if net_vni == None:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    match_description = ''

    # Check if the reservation matches a description, a mac, or an IP address currently in the database
    dhcp_reservations_list = getNetworkDHCPReservations(zk_conn, net_vni)
    for macaddr in dhcp_reservations_list:
        hostname = zkhandler.readdata(zk_conn, '/networks/{}/dhcp_reservations/{}/hostname'.format(net_vni, macaddr))
        ipaddress = zkhandler.readdata(zk_conn, '/networks/{}/dhcp_reservations/{}/ipaddr'.format(net_vni, macaddr))
        if reservation == macaddr or reservation == hostname or reservation == ipaddress:
            match_description = macaddr
    
    if not match_description:
        return False, 'ERROR: No DHCP reservation exists matching "{}"!'.format(reservation)

    # Remove the entry from zookeeper
    try:
        zkhandler.deletekey(zk_conn, '/networks/{}/dhcp_reservations/{}'.format(net_vni, match_description))
    except:
        return False, 'ERROR: Failed to write to Zookeeper!'

    return True, 'DHCP reservation "{}" removed successfully!'.format(match_description)

def add_acl(zk_conn, network, direction, description, rule, order):
    # Validate and obtain standard passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if net_vni == None:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    # Change direction to something more usable
    if direction:
        direction = "in"
    else:
        direction = "out"

    if zkhandler.exists(zk_conn, '/networks/{}/firewall_rules/{}/{}'.format(net_vni, direction, description)):
        return False, 'ERROR: A rule with description "{}" already exists!'.format(description)

    # Handle reordering
    full_acl_list = getNetworkACLs(zk_conn, net_vni, direction)
    acl_list_length = len(full_acl_list)
    # Set order to len
    if order == None or int(order) > acl_list_length:
        order = acl_list_length
    # Convert passed-in order to an integer
    else:
        order = int(order)
      
    # Insert into the array at order-1
    full_acl_list.insert(order, {'direction': direction, 'description': description})

    # Update the existing ordering
    updated_orders = dict()
    for idx, acl in enumerate(full_acl_list):
        if acl['description'] == description:
            continue

        updated_orders[
            '/networks/{}/firewall_rules/{}/{}/order'.format(net_vni, direction, acl['description'])
        ] = idx

    if updated_orders:
        try:
            zkhandler.writedata(zk_conn, updated_orders)
        except Exception as e:
            return False, 'ERROR: Failed to write to Zookeeper! Exception: "{}".'.format(e)

    # Add the new rule
    try:
        zkhandler.writedata(zk_conn, {
            '/networks/{}/firewall_rules/{}/{}'.format(net_vni, direction, description): '',
            '/networks/{}/firewall_rules/{}/{}/order'.format(net_vni, direction, description): order,
            '/networks/{}/firewall_rules/{}/{}/rule'.format(net_vni, direction, description): rule
        })
    except Exception as e:
        return False, 'ERROR: Failed to write to Zookeeper! Exception: "{}".'.format(e)

    return True, 'Firewall rule "{}" added successfully!'.format(description)

def remove_acl(zk_conn, network, rule, direction):
    # Validate and obtain standard passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if net_vni == None:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    # Change direction to something more usable
    if direction:
        direction = "in"
    else:
        direction = "out"

    match_description = ''

    # Check if the ACL matches a description currently in the database
    acl_list = getNetworkACLs(zk_conn, net_vni, direction)
    for acl in acl_list:
        if acl['description'] == rule:
            match_description = acl['description']
    
    if not match_description:
        return False, 'ERROR: No firewall rule exists matching description "{}"!'.format(rule)

    # Remove the entry from zookeeper
    try:
        zkhandler.deletekey(zk_conn, '/networks/{}/firewall_rules/{}/{}'.format(net_vni, direction, match_description))
    except Exception as e:
        return False, 'ERROR: Failed to write to Zookeeper! Exception: "{}".'.format(e)

    # Update the existing ordering
    updated_acl_list = getNetworkACLs(zk_conn, net_vni, direction)
    updated_orders = dict()
    for idx, acl in enumerate(updated_acl_list):
        updated_orders[
            '/networks/{}/firewall_rules/{}/{}/order'.format(net_vni, direction, acl['description'])
        ] = idx

    if updated_orders:
        try:
            zkhandler.writedata(zk_conn, updated_orders)
        except Exception as e:
            return False, 'ERROR: Failed to write to Zookeeper! Exception: "{}".'.format(e)

    return True, 'Firewall rule "{}" removed successfully!'.format(match_description)

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
    full_net_list = zkhandler.listchildren(zk_conn, '/networks')

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

def get_list_dhcp(zk_conn, network, limit, only_static=False):
    # Validate and obtain alternate passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if net_vni == None:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    dhcp_list = []

    if only_static:
        full_dhcp_list = getNetworkDHCPReservations(zk_conn, net_vni)
        reservations = True
    else:
        full_dhcp_list = getNetworkDHCPLeases(zk_conn, net_vni)
        reservations = False

    if limit:
        try:
            # Implcitly assume fuzzy limits
            if re.match('\^.*', limit) == None:
                limit = '.*' + limit
            if re.match('.*\$', limit) == None:
                limit = limit + '.*'
        except Exception as e:
            return False, 'Regex Error: {}'.format(e)
        

    for lease in full_dhcp_list:
        valid_lease = False
        if limit:
            if re.match(limit, lease) != None:
                valid_lease = True
            if re.match(limit, lease) != None:
                valid_lease = True
        else:
            valid_lease = True

        if valid_lease:
            dhcp_list.append(lease)

    output_string = formatDHCPLeaseList(zk_conn, net_vni, dhcp_list, reservations=reservations)
    click.echo(output_string)

    return True, ''

def get_list_acl(zk_conn, network, limit, direction):
    # Validate and obtain alternate passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if net_vni == None:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    # Change direction to something more usable
    if direction is None:
        direction = "both"
    elif direction is True:
        direction = "in"
    elif direction is False:
        direction = "out"

    acl_list = []
    full_acl_list = getNetworkACLs(zk_conn, net_vni, direction)

    if limit:
        try:
            # Implcitly assume fuzzy limits
            if re.match('\^.*', limit) == None:
                limit = '.*' + limit
            if re.match('.*\$', limit) == None:
                limit = limit + '.*'
        except Exception as e:
            return False, 'Regex Error: {}'.format(e)

    for acl in full_acl_list:
        valid_acl = False
        if limit:
            if re.match(limit, acl['description']) != None:
                valid_acl = True
        else:
            valid_acl = True

        if valid_acl:
            acl_list.append(acl)

    output_string = formatACLList(zk_conn, net_vni, direction, acl_list)
    click.echo(output_string)

    return True, ''
