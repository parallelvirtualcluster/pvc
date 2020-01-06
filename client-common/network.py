#!/usr/bin/env python3

# network.py - PVC client function library, Network fuctions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2019 Joshua M. Boniface <joshua@boniface.me>
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
    # Get a list of DHCP leases by listing the children of /networks/<vni>/dhcp4_leases
    dhcp4_leases = zkhandler.listchildren(zk_conn, '/networks/{}/dhcp4_leases'.format(vni))
    return sorted(dhcp4_leases)

def getNetworkDHCPReservations(zk_conn, vni):
    # Get a list of DHCP reservations by listing the children of /networks/<vni>/dhcp4_reservations
    dhcp4_reservations = zkhandler.listchildren(zk_conn, '/networks/{}/dhcp4_reservations'.format(vni))
    return sorted(dhcp4_reservations)

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
            rule = zkhandler.readdata(zk_conn, '/networks/{}/firewall_rules/{}/{}/rule'.format(vni, direction, acl))
            full_acl_list.append({'direction': direction, 'order': int(order), 'description': ordered_acls[order], 'rule': rule})

    return full_acl_list

def getNetworkInformation(zk_conn, vni):
    description = zkhandler.readdata(zk_conn, '/networks/{}'.format(vni))
    nettype = zkhandler.readdata(zk_conn, '/networks/{}/nettype'.format(vni))
    domain = zkhandler.readdata(zk_conn, '/networks/{}/domain'.format(vni))
    name_servers = zkhandler.readdata(zk_conn, '/networks/{}/name_servers'.format(vni))
    ip6_network = zkhandler.readdata(zk_conn, '/networks/{}/ip6_network'.format(vni))
    ip6_gateway = zkhandler.readdata(zk_conn, '/networks/{}/ip6_gateway'.format(vni))
    dhcp6_flag = zkhandler.readdata(zk_conn, '/networks/{}/dhcp6_flag'.format(vni))
    ip4_network = zkhandler.readdata(zk_conn, '/networks/{}/ip4_network'.format(vni))
    ip4_gateway = zkhandler.readdata(zk_conn, '/networks/{}/ip4_gateway'.format(vni))
    dhcp4_flag = zkhandler.readdata(zk_conn, '/networks/{}/dhcp4_flag'.format(vni))
    dhcp4_start = zkhandler.readdata(zk_conn, '/networks/{}/dhcp4_start'.format(vni))
    dhcp4_end = zkhandler.readdata(zk_conn, '/networks/{}/dhcp4_end'.format(vni))

    # Construct a data structure to represent the data
    network_information = {
        'vni': int(vni),
        'description': description,
        'type': nettype,
        'domain': domain,
        'name_servers': name_servers.split(','),
        'ip6': {
            'network': ip6_network,
            'gateway': ip6_gateway,
            'dhcp_flag': dhcp6_flag,
         },
         'ip4': {
            'network': ip4_network,
            'gateway': ip4_gateway,
            'dhcp_flag': dhcp4_flag,
            'dhcp_start': dhcp4_start,
            'dhcp_end': dhcp4_end
         }
    }
    return network_information

def getDHCPLeaseInformation(zk_conn, vni, mac_address):
    hostname = zkhandler.readdata(zk_conn, '/networks/{}/dhcp4_leases/{}/hostname'.format(vni, mac_address))
    ip4_address = zkhandler.readdata(zk_conn, '/networks/{}/dhcp4_leases/{}/ipaddr'.format(vni, mac_address))
    try:
        timestamp = zkhandler.readdata(zk_conn, '/networks/{}/dhcp4_leases/{}/expiry'.format(vni, mac_address))
    except:
        timestamp = 'static'

    # Construct a data structure to represent the data
    lease_information = {
        'hostname': hostname,
        'ip4_address': ip4_address,
        'mac_address': mac_address,
        'timestamp': timestamp
    }
    return lease_information

def getACLInformation(zk_conn, vni, direction, description):
    order = zkhandler.readdata(zk_conn, '/networks/{}/firewall_rules/{}/{}/order'.format(vni, direction, description))
    rule = zkhandler.readdata(zk_conn, '/networks/{}/firewall_rules/{}/{}/rule'.format(vni, direction, description))

    # Construct a data structure to represent the data
    acl_information = {
        'order': order,
        'description': description,
        'rule': rule,
        'direction': direction
    }
    return acl_information

def isValidMAC(macaddr):
    allowed = re.compile(r"""
                         (
                            ^([0-9A-F]{2}[:]){5}([0-9A-F]{2})$
                         )
                         """,
                         re.VERBOSE|re.IGNORECASE)

    if allowed.match(macaddr):
        return True
    else:
        return False

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
def add_network(zk_conn, vni, description, nettype,
                domain, name_servers, ip4_network, ip4_gateway, ip6_network, ip6_gateway,
                dhcp4_flag, dhcp4_start, dhcp4_end):
    # Ensure start and end DHCP ranges are set if the flag is set
    if dhcp4_flag and ( not dhcp4_start or not dhcp4_end ):
        return False, 'ERROR: DHCPv4 start and end addresses are required for a DHCPv4-enabled network.'

    # Check if a network with this VNI or description already exists
    if zkhandler.exists(zk_conn, '/networks/{}'.format(vni)):
        return False, 'ERROR: A network with VNI "{}" already exists!'.format(vni)
    for network in zkhandler.listchildren(zk_conn, '/networks'):
        network_description = zkhandler.readdata(zk_conn, '/networks/{}'.format(network))
        if network_description == description:
            return False, 'ERROR: A network with description "{}" already exists!'.format(description)

    # We're generating the default gateway to be ip6_network::1/YY
    if ip6_network:
        dhcp6_flag = 'True'
        if not ip6_gateway:
            ip6_netpart, ip6_maskpart = ip6_network.split('/')
            ip6_gateway = '{}1'.format(ip6_netpart)
    else:
        dhcp6_flag = 'False'

    if nettype == 'managed' and not domain:
        domain = '{}.local'.format(description)

    # Make sure the DHCP4 flag is always boolean 
    if dhcp4_flag is None:
        dhcp4_flag = False

    # Add the new network to Zookeeper
    zkhandler.writedata(zk_conn, {
        '/networks/{}'.format(vni): description,
        '/networks/{}/nettype'.format(vni): nettype,
        '/networks/{}/domain'.format(vni): domain,
        '/networks/{}/name_servers'.format(vni): name_servers,
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

def modify_network(zk_conn, vni, description=None, domain=None, name_servers=None,
                   ip4_network=None, ip4_gateway=None, ip6_network=None, ip6_gateway=None,
                   dhcp4_flag=None, dhcp4_start=None, dhcp4_end=None):
    # Add the modified parameters to Zookeeper
    zk_data = dict()
    if description:
        zk_data.update({'/networks/{}'.format(vni): description})
    if domain:
        zk_data.update({'/networks/{}/domain'.format(vni): domain})
    if name_servers:
        zk_data.update({'/networks/{}/name_servers'.format(vni): name_servers})
    if ip4_network:
        zk_data.update({'/networks/{}/ip4_network'.format(vni): ip4_network})
    if ip4_gateway:
        zk_data.update({'/networks/{}/ip4_gateway'.format(vni): ip4_gateway})
    if ip6_network:
        zk_data.update({'/networks/{}/ip6_network'.format(vni): ip6_network})
        if ip6_network is not None:
            zk_data.update({'/networks/{}/dhcp6_flag'.format(vni): 'True'})
        else:
            zk_data.update({'/networks/{}/dhcp6_flag'.format(vni): 'False'})
    if ip6_gateway:
        zk_data.update({'/networks/{}/ip6_gateway'.format(vni): ip6_gateway})
    else:
        # If we're changing the network, but don't also specify the gateway,
        # generate a new one automatically
        if ip6_network:
            ip6_netpart, ip6_maskpart = ip6_network.split('/')
            ip6_gateway = '{}1'.format(ip6_netpart)
            zk_data.update({'/networks/{}/ip6_gateway'.format(vni): ip6_gateway})
    if dhcp4_flag:
        zk_data.update({'/networks/{}/dhcp4_flag'.format(vni): dhcp4_flag})
    if dhcp4_start:
        zk_data.update({'/networks/{}/dhcp4_start'.format(vni): dhcp4_start})
    if dhcp4_end:
        zk_data.update({'/networks/{}/dhcp4_end'.format(vni): dhcp4_end})

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
    if not net_vni:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    # Use lowercase MAC format exclusively
    macaddress = macaddress.lower()

    if not isValidMAC(macaddress):
        return False, 'ERROR: MAC address "{}" is not valid! Always use ":" as a separator.'.format(macaddress)

    if not isValidIP(ipaddress):
        return False, 'ERROR: IP address "{}" is not valid!'.format(macaddress)

    if zkhandler.exists(zk_conn, '/networks/{}/dhcp4_reservations/{}'.format(net_vni, macaddress)):
        return False, 'ERROR: A reservation with MAC "{}" already exists!'.format(macaddress)

    # Add the new static lease to ZK
    try:
        zkhandler.writedata(zk_conn, {
            '/networks/{}/dhcp4_reservations/{}'.format(net_vni, macaddress): 'static',
            '/networks/{}/dhcp4_reservations/{}/hostname'.format(net_vni, macaddress): hostname,
            '/networks/{}/dhcp4_reservations/{}/ipaddr'.format(net_vni, macaddress): ipaddress
        })
    except Exception as e:
        return False, 'ERROR: Failed to write to Zookeeper! Exception: "{}".'.format(e)

    return True, 'DHCP reservation "{}" added successfully!'.format(macaddress)

def remove_dhcp_reservation(zk_conn, network, reservation):
    # Validate and obtain standard passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if not net_vni:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    match_description = ''

    # Check if the reservation matches a static reservation description, a mac, or an IP address currently in the database
    dhcp4_reservations_list = getNetworkDHCPReservations(zk_conn, net_vni)
    for macaddr in dhcp4_reservations_list:
        hostname = zkhandler.readdata(zk_conn, '/networks/{}/dhcp4_reservations/{}/hostname'.format(net_vni, macaddr))
        ipaddress = zkhandler.readdata(zk_conn, '/networks/{}/dhcp4_reservations/{}/ipaddr'.format(net_vni, macaddr))
        if reservation == macaddr or reservation == hostname or reservation == ipaddress:
            match_description = macaddr
            lease_type_zk = 'reservations'
            lease_type_human = 'static reservation'

    # Check if the reservation matches a dynamic reservation description, a mac, or an IP address currently in the database
    dhcp4_leases_list = getNetworkDHCPLeases(zk_conn, net_vni)
    for macaddr in dhcp4_leases_list:
        hostname = zkhandler.readdata(zk_conn, '/networks/{}/dhcp4_leases/{}/hostname'.format(net_vni, macaddr))
        ipaddress = zkhandler.readdata(zk_conn, '/networks/{}/dhcp4_leases/{}/ipaddr'.format(net_vni, macaddr))
        if reservation == macaddr or reservation == hostname or reservation == ipaddress:
            match_description = macaddr
            lease_type_zk = 'leases'
            lease_type_human = 'dynamic lease'

    if not match_description:
        return False, 'ERROR: No DHCP reservation or lease exists matching "{}"!'.format(reservation)

    # Remove the entry from zookeeper
    try:
        zkhandler.deletekey(zk_conn, '/networks/{}/dhcp4_{}/{}'.format(net_vni, lease_type_zk, match_description))
    except:
        return False, 'ERROR: Failed to write to Zookeeper!'

    return True, 'DHCP {} "{}" removed successfully!'.format(lease_type_human, match_description)

def add_acl(zk_conn, network, direction, description, rule, order):
    # Validate and obtain standard passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if not net_vni:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    # Check if the ACL matches a description currently in the database
    match_description = ''
    full_acl_list = getNetworkACLs(zk_conn, net_vni, 'both')
    for acl in full_acl_list:
        if acl['description'] == description:
            match_description = acl['description']

    if match_description:
        return False, 'ERROR: A rule with description "{}" already exists!'.format(description)

    # Change direction to something more usable
    if direction:
        direction = "in"
    else:
        direction = "out"

    # Handle reordering
    full_acl_list = getNetworkACLs(zk_conn, net_vni, direction)
    acl_list_length = len(full_acl_list)
    # Set order to len
    if not order or int(order) > acl_list_length:
        order = acl_list_length
    # Convert passed-in order to an integer
    else:
        order = int(order)

    # Insert into the array at order-1
    full_acl_list.insert(order, {'direction': direction, 'description': description, 'rule': rule})

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

def remove_acl(zk_conn, network, description):
    # Validate and obtain standard passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if not net_vni:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    match_description = ''

    # Check if the ACL matches a description currently in the database
    acl_list = getNetworkACLs(zk_conn, net_vni, 'both')
    for acl in acl_list:
        if acl['description'] == description:
            match_description = acl['description']
            match_direction = acl['direction']

    if not match_description:
        return False, 'ERROR: No firewall rule exists matching description "{}"!'.format(description)

    # Remove the entry from zookeeper
    try:
        zkhandler.deletekey(zk_conn, '/networks/{}/firewall_rules/{}/{}'.format(net_vni, match_direction, match_description))
    except Exception as e:
        return False, 'ERROR: Failed to write to Zookeeper! Exception: "{}".'.format(e)

    # Update the existing ordering
    updated_acl_list = getNetworkACLs(zk_conn, net_vni, match_direction)
    updated_orders = dict()
    for idx, acl in enumerate(updated_acl_list):
        updated_orders[
            '/networks/{}/firewall_rules/{}/{}/order'.format(net_vni, match_direction, acl['description'])
        ] = idx

    if updated_orders:
        try:
            zkhandler.writedata(zk_conn, updated_orders)
        except Exception as e:
            return False, 'ERROR: Failed to write to Zookeeper! Exception: "{}".'.format(e)

    return True, 'Firewall rule "{}" removed successfully!'.format(match_description)

def get_info(zk_conn, network):
    # Validate and obtain alternate passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if not net_vni:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    network_information = getNetworkInformation(zk_conn, network)
    if not network_information:
        return False, 'ERROR: Could not get information about network "{}"'.format(network)

    return True, network_information

def get_list(zk_conn, limit, is_fuzzy=True):
    net_list = []
    full_net_list = zkhandler.listchildren(zk_conn, '/networks')

    for net in full_net_list:
        description = zkhandler.readdata(zk_conn, '/networks/{}'.format(net))
        if limit:
            try:
                if not is_fuzzy:
                    limit = '^' + limit + '$'

                if re.match(limit, net):
                    net_list.append(getNetworkInformation(zk_conn, net))
                if re.match(limit, description):
                    net_list.append(getNetworkInformation(zk_conn, net))
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            net_list.append(getNetworkInformation(zk_conn, net))

    #output_string = formatNetworkList(zk_conn, net_list)
    return True, net_list

def get_list_dhcp(zk_conn, network, limit, only_static=False, is_fuzzy=True):
    # Validate and obtain alternate passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if not net_vni:
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
            if not is_fuzzy:
                limit = '^' + limit + '$'

            # Implcitly assume fuzzy limits
            if not re.match('\^.*', limit):
                limit = '.*' + limit
            if not re.match('.*\$', limit):
                limit = limit + '.*'
        except Exception as e:
            return False, 'Regex Error: {}'.format(e)


    for lease in full_dhcp_list:
        valid_lease = False
        if limit:
            if re.match(limit, lease):
                valid_lease = True
            if re.match(limit, lease):
                valid_lease = True
        else:
            valid_lease = True

        if valid_lease:
            dhcp_list.append(getDHCPLeaseInformation(zk_conn, net_vni, lease))

    #output_string = formatDHCPLeaseList(zk_conn, net_vni, dhcp_list, reservations=reservations)
    return True, dhcp_list

def get_list_acl(zk_conn, network, limit, direction, is_fuzzy=True):
    # Validate and obtain alternate passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if not net_vni:
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
            if not is_fuzzy:
                limit = '^' + limit + '$'

            # Implcitly assume fuzzy limits
            if not re.match('\^.*', limit):
                limit = '.*' + limit
            if not re.match('.*\$', limit):
                limit = limit + '.*'
        except Exception as e:
            return False, 'Regex Error: {}'.format(e)

    for acl in full_acl_list:
        valid_acl = False
        if limit:
            if re.match(limit, acl['description']):
                valid_acl = True
        else:
            valid_acl = True

        if valid_acl:
            acl_list.append(acl)

    #output_string = formatACLList(zk_conn, net_vni, direction, acl_list)
    return True, acl_list

# CLI-only functions
def getOutputColours(network_information):
    if network_information['ip6']['network'] != "None":
        v6_flag_colour = ansiprint.green()
    else:
        v6_flag_colour = ansiprint.blue()
    if network_information['ip4']['network'] != "None":
        v4_flag_colour = ansiprint.green()
    else:
        v4_flag_colour = ansiprint.blue()

    if network_information['ip6']['dhcp_flag'] == "True":
        dhcp6_flag_colour = ansiprint.green()
    else:
        dhcp6_flag_colour = ansiprint.blue()
    if network_information['ip4']['dhcp_flag'] == "True":
        dhcp4_flag_colour = ansiprint.green()
    else:
        dhcp4_flag_colour = ansiprint.blue()

    return v6_flag_colour, v4_flag_colour, dhcp6_flag_colour, dhcp4_flag_colour

def format_info(network_information, long_output):
    if not network_information:
        click.echo("No network found")
        return

    v6_flag_colour, v4_flag_colour, dhcp6_flag_colour, dhcp4_flag_colour = getOutputColours(network_information)

    # Format a nice output: do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append('{}Virtual network information:{}'.format(ansiprint.bold(), ansiprint.end()))
    ainformation.append('')
    # Basic information
    ainformation.append('{}VNI:{}            {}'.format(ansiprint.purple(), ansiprint.end(), network_information['vni']))
    ainformation.append('{}Type:{}           {}'.format(ansiprint.purple(), ansiprint.end(), network_information['type']))
    ainformation.append('{}Description:{}    {}'.format(ansiprint.purple(), ansiprint.end(), network_information['description']))
    if network_information['type'] == 'managed':
        ainformation.append('{}Domain:{}         {}'.format(ansiprint.purple(), ansiprint.end(), network_information['domain']))
        ainformation.append('{}DNS Servers:{}    {}'.format(ansiprint.purple(), ansiprint.end(), ', '.join(network_information['name_servers'])))
        if network_information['ip6']['network'] != "None":
            ainformation.append('')
            ainformation.append('{}IPv6 network:{}   {}'.format(ansiprint.purple(), ansiprint.end(), network_information['ip6']['network']))
            ainformation.append('{}IPv6 gateway:{}   {}'.format(ansiprint.purple(), ansiprint.end(), network_information['ip6']['gateway']))
            ainformation.append('{}DHCPv6 enabled:{} {}{}{}'.format(ansiprint.purple(), ansiprint.end(), dhcp6_flag_colour, network_information['ip6']['dhcp_flag'], ansiprint.end()))
        if network_information['ip4']['network'] != "None":
            ainformation.append('')
            ainformation.append('{}IPv4 network:{}   {}'.format(ansiprint.purple(), ansiprint.end(), network_information['ip4']['network']))
            ainformation.append('{}IPv4 gateway:{}   {}'.format(ansiprint.purple(), ansiprint.end(), network_information['ip4']['gateway']))
            ainformation.append('{}DHCPv4 enabled:{} {}{}{}'.format(ansiprint.purple(), ansiprint.end(), dhcp4_flag_colour, network_information['ip4']['dhcp_flag'], ansiprint.end()))
            if network_information['ip4']['dhcp_flag'] == "True":
                ainformation.append('{}DHCPv4 range:{}   {} - {}'.format(ansiprint.purple(), ansiprint.end(), network_information['ip4']['dhcp_start'], network_information['ip4']['dhcp_end']))

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
    click.echo('\n'.join(ainformation))

def format_list(network_list):
    if not network_list:
        click.echo("No network found")
        return

    network_list_output = []

    # Determine optimal column widths
    net_vni_length = 5
    net_description_length = 12
    net_nettype_length = 8
    net_domain_length = 6
    net_v6_flag_length = 6
    net_dhcp6_flag_length = 7
    net_v4_flag_length = 6
    net_dhcp4_flag_length = 7
    for network_information in network_list:
        # vni column
        _net_vni_length = len(str(network_information['vni'])) + 1
        if _net_vni_length > net_vni_length:
            net_vni_length = _net_vni_length
        # description column
        _net_description_length = len(network_information['description']) + 1
        if _net_description_length > net_description_length:
            net_description_length = _net_description_length
        # domain column
        _net_domain_length = len(network_information['domain']) + 1
        if _net_domain_length > net_domain_length:
            net_domain_length = _net_domain_length

    # Format the string (header)
    network_list_output.append('{bold}\
{net_vni: <{net_vni_length}} \
{net_description: <{net_description_length}} \
{net_nettype: <{net_nettype_length}} \
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
            net_nettype_length=net_nettype_length,
            net_domain_length=net_domain_length,
            net_v6_flag_length=net_v6_flag_length,
            net_dhcp6_flag_length=net_dhcp6_flag_length,
            net_v4_flag_length=net_v4_flag_length,
            net_dhcp4_flag_length=net_dhcp4_flag_length,
            net_vni='VNI',
            net_description='Description',
            net_nettype='Type',
            net_domain='Domain',
            net_v6_flag='IPv6',
            net_dhcp6_flag='DHCPv6',
            net_v4_flag='IPv4',
            net_dhcp4_flag='DHCPv4',
        )
    )

    for network_information in network_list:
        v6_flag_colour, v4_flag_colour, dhcp6_flag_colour, dhcp4_flag_colour = getOutputColours(network_information)
        if network_information['ip4']['network'] != "None":
            v4_flag = 'True'
        else:
            v4_flag = 'False'

        if network_information['ip6']['network'] != "None":
            v6_flag = 'True'
        else:
            v6_flag = 'False'

        if network_information['ip4']['dhcp_flag'] == "True":
            dhcp4_range = '{} - {}'.format(network_information['ip4']['dhcp_start'], network_information['ip4']['dhcp_end'])
        else:
            dhcp4_range = 'N/A'

        network_list_output.append(
            '{bold}\
{net_vni: <{net_vni_length}} \
{net_description: <{net_description_length}} \
{net_nettype: <{net_nettype_length}} \
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
                net_nettype_length=net_nettype_length,
                net_domain_length=net_domain_length,
                net_v6_flag_length=net_v6_flag_length,
                net_dhcp6_flag_length=net_dhcp6_flag_length,
                net_v4_flag_length=net_v4_flag_length,
                net_dhcp4_flag_length=net_dhcp4_flag_length,
                net_vni=network_information['vni'],
                net_description=network_information['description'],
                net_nettype=network_information['type'],
                net_domain=network_information['domain'],
                net_v6_flag=v6_flag,
                v6_flag_colour=v6_flag_colour,
                net_dhcp6_flag=network_information['ip6']['dhcp_flag'],
                dhcp6_flag_colour=dhcp6_flag_colour,
                net_v4_flag=v4_flag,
                v4_flag_colour=v4_flag_colour,
                net_dhcp4_flag=network_information['ip4']['dhcp_flag'],
                dhcp4_flag_colour=dhcp4_flag_colour,
                colour_off=ansiprint.end()
            )
        )

    click.echo('\n'.join(sorted(network_list_output)))

def format_list_dhcp(dhcp_lease_list):
    dhcp_lease_list_output = []

    # Determine optimal column widths
    lease_hostname_length = 9
    lease_ip4_address_length = 11
    lease_mac_address_length = 13
    lease_timestamp_length = 13
    for dhcp_lease_information in dhcp_lease_list:
        # hostname column
        _lease_hostname_length = len(dhcp_lease_information['hostname']) + 1
        if _lease_hostname_length > lease_hostname_length:
            lease_hostname_length = _lease_hostname_length
        # ip4_address column
        _lease_ip4_address_length = len(dhcp_lease_information['ip4_address']) + 1
        if _lease_ip4_address_length > lease_ip4_address_length:
            lease_ip4_address_length = _lease_ip4_address_length
        # mac_address column
        _lease_mac_address_length = len(dhcp_lease_information['mac_address']) + 1
        if _lease_mac_address_length > lease_mac_address_length:
            lease_mac_address_length = _lease_mac_address_length

    # Format the string (header)
    dhcp_lease_list_output.append('{bold}\
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
    )

    for dhcp_lease_information in dhcp_lease_list:
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
                lease_hostname=dhcp_lease_information['hostname'],
                lease_ip4_address=dhcp_lease_information['ip4_address'],
                lease_mac_address=dhcp_lease_information['mac_address'],
                lease_timestamp=dhcp_lease_information['timestamp']
            )
        )

    click.echo('\n'.join(sorted(dhcp_lease_list_output)))

def format_list_acl(acl_list):
    acl_list_output = []

    # Determine optimal column widths
    acl_direction_length = 10
    acl_order_length = 6
    acl_description_length = 12
    acl_rule_length = 5
    for acl_information in acl_list:
        # order column
        _acl_order_length = len(str(acl_information['order'])) + 1
        if _acl_order_length > acl_order_length:
            acl_order_length = _acl_order_length
        # description column
        _acl_description_length = len(acl_information['description']) + 1
        if _acl_description_length > acl_description_length:
            acl_description_length = _acl_description_length
        # rule column
        _acl_rule_length = len(acl_information['rule']) + 1
        if _acl_rule_length > acl_rule_length:
            acl_rule_length = _acl_rule_length

    # Format the string (header)
    acl_list_output.append('{bold}\
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
    )

    for acl_information in acl_list:
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
                acl_direction=acl_information['direction'],
                acl_order=acl_information['order'],
                acl_description=acl_information['description'],
                acl_rule=acl_information['rule'],
            )
        )

    click.echo('\n'.join(sorted(acl_list_output)))

