#!/usr/bin/env python3

# network.py - PVC client function library, Network fuctions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2020 Joshua M. Boniface <joshua@boniface.me>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, version 3.
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

import re

from kazoo.exceptions import NoNodeError

import daemon_lib.zkhandler as zkhandler


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
    # Check whether this is a dynamic or static lease
    try:
        zkhandler.readdata(zk_conn, '/networks/{}/dhcp4_leases/{}'.format(vni, mac_address))
        type_key = 'dhcp4_leases'
    except NoNodeError:
        zkhandler.readdata(zk_conn, '/networks/{}/dhcp4_reservations/{}'.format(vni, mac_address))
        type_key = 'dhcp4_reservations'

    hostname = zkhandler.readdata(zk_conn, '/networks/{}/{}/{}/hostname'.format(vni, type_key, mac_address))
    ip4_address = zkhandler.readdata(zk_conn, '/networks/{}/{}/{}/ipaddr'.format(vni, type_key, mac_address))
    if type_key == 'dhcp4_leases':
        timestamp = zkhandler.readdata(zk_conn, '/networks/{}/{}/{}/expiry'.format(vni, type_key, mac_address))
    else:
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
                         re.VERBOSE | re.IGNORECASE)

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
    if dhcp4_flag and (not dhcp4_start or not dhcp4_end):
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
    if description is not None:
        zk_data.update({'/networks/{}'.format(vni): description})
    if domain is not None:
        zk_data.update({'/networks/{}/domain'.format(vni): domain})
    if name_servers is not None:
        zk_data.update({'/networks/{}/name_servers'.format(vni): name_servers})
    if ip4_network is not None:
        zk_data.update({'/networks/{}/ip4_network'.format(vni): ip4_network})
    if ip4_gateway is not None:
        zk_data.update({'/networks/{}/ip4_gateway'.format(vni): ip4_gateway})
    if ip6_network is not None:
        zk_data.update({'/networks/{}/ip6_network'.format(vni): ip6_network})
        if ip6_network:
            zk_data.update({'/networks/{}/dhcp6_flag'.format(vni): 'True'})
        else:
            zk_data.update({'/networks/{}/dhcp6_flag'.format(vni): 'False'})
    if ip6_gateway is not None:
        zk_data.update({'/networks/{}/ip6_gateway'.format(vni): ip6_gateway})
    else:
        # If we're changing the network, but don't also specify the gateway,
        # generate a new one automatically
        if ip6_network:
            ip6_netpart, ip6_maskpart = ip6_network.split('/')
            ip6_gateway = '{}1'.format(ip6_netpart)
            zk_data.update({'/networks/{}/ip6_gateway'.format(vni): ip6_gateway})
    if dhcp4_flag is not None:
        zk_data.update({'/networks/{}/dhcp4_flag'.format(vni): dhcp4_flag})
    if dhcp4_start is not None:
        zk_data.update({'/networks/{}/dhcp4_start'.format(vni): dhcp4_start})
    if dhcp4_end is not None:
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
    except Exception:
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

    return True, net_list


def get_list_dhcp(zk_conn, network, limit, only_static=False, is_fuzzy=True):
    # Validate and obtain alternate passed value
    net_vni = getNetworkVNI(zk_conn, network)
    if not net_vni:
        return False, 'ERROR: Could not find network "{}" in the cluster!'.format(network)

    dhcp_list = []

    if only_static:
        full_dhcp_list = getNetworkDHCPReservations(zk_conn, net_vni)
    else:
        full_dhcp_list = getNetworkDHCPReservations(zk_conn, net_vni)
        full_dhcp_list += getNetworkDHCPLeases(zk_conn, net_vni)

    if limit:
        try:
            if not is_fuzzy:
                limit = '^' + limit + '$'

            # Implcitly assume fuzzy limits
            if not re.match(r'\^.*', limit):
                limit = '.*' + limit
            if not re.match(r'.*\$', limit):
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
            if not re.match(r'\^.*', limit):
                limit = '.*' + limit
            if not re.match(r'.*\$', limit):
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

    return True, acl_list
