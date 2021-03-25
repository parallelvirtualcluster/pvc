#!/usr/bin/env python3

# network.py - PVC CLI client function library, Network functions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2021 Joshua M. Boniface <joshua@boniface.me>
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
import cli_lib.ansiprint as ansiprint
from cli_lib.common import call_api


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
# Primary functions
#
def net_info(config, net):
    """
    Get information about network

    API endpoint: GET /api/v1/network/{net}
    API arguments:
    API schema: {json_data_object}
    """
    response = call_api(config, 'get', '/network/{net}'.format(net=net))

    if response.status_code == 200:
        if isinstance(response.json(), list) and len(response.json()) != 1:
            # No exact match; return not found
            return False, "Network not found."
        else:
            # Return a single instance if the response is a list
            if isinstance(response.json(), list):
                return True, response.json()[0]
            # This shouldn't happen, but is here just in case
            else:
                return True, response.json()
    else:
        return False, response.json().get('message', '')


def net_list(config, limit):
    """
    Get list information about networks (limited by {limit})

    API endpoint: GET /api/v1/network
    API arguments: limit={limit}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    if limit:
        params['limit'] = limit

    response = call_api(config, 'get', '/network', params=params)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json().get('message', '')


def net_add(config, vni, description, nettype, domain, name_servers, ip4_network, ip4_gateway, ip6_network, ip6_gateway, dhcp4_flag, dhcp4_start, dhcp4_end):
    """
    Add new network

    API endpoint: POST /api/v1/network
    API arguments: lots
    API schema: {"message":"{data}"}
    """
    params = {
        'vni': vni,
        'description': description,
        'nettype': nettype,
        'domain': domain,
        'name_servers': name_servers,
        'ip4_network': ip4_network,
        'ip4_gateway': ip4_gateway,
        'ip6_network': ip6_network,
        'ip6_gateway': ip6_gateway,
        'dhcp4': dhcp4_flag,
        'dhcp4_start': dhcp4_start,
        'dhcp4_end': dhcp4_end
    }
    response = call_api(config, 'post', '/network', params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get('message', '')


def net_modify(config, net, description, domain, name_servers, ip4_network, ip4_gateway, ip6_network, ip6_gateway, dhcp4_flag, dhcp4_start, dhcp4_end):
    """
    Modify a network

    API endpoint: POST /api/v1/network/{net}
    API arguments: lots
    API schema: {"message":"{data}"}
    """
    params = dict()
    if description is not None:
        params['description'] = description
    if domain is not None:
        params['domain'] = domain
    if name_servers is not None:
        params['name_servers'] = name_servers
    if ip4_network is not None:
        params['ip4_network'] = ip4_network
    if ip4_gateway is not None:
        params['ip4_gateway'] = ip4_gateway
    if ip6_network is not None:
        params['ip6_network'] = ip6_network
    if ip6_gateway is not None:
        params['ip6_gateway'] = ip6_gateway
    if dhcp4_flag is not None:
        params['dhcp4'] = dhcp4_flag
    if dhcp4_start is not None:
        params['dhcp4_start'] = dhcp4_start
    if dhcp4_end is not None:
        params['dhcp4_end'] = dhcp4_end

    response = call_api(config, 'put', '/network/{net}'.format(net=net), params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get('message', '')


def net_remove(config, net):
    """
    Remove a network

    API endpoint: DELETE /api/v1/network/{net}
    API arguments:
    API schema: {"message":"{data}"}
    """
    response = call_api(config, 'delete', '/network/{net}'.format(net=net))

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get('message', '')


#
# DHCP lease functions
#
def net_dhcp_info(config, net, mac):
    """A
    Get information about network DHCP lease

    API endpoint: GET /api/v1/network/{net}/lease/{mac}
    API arguments:
    API schema: {json_data_object}
    """
    response = call_api(config, 'get', '/network/{net}/lease/{mac}'.format(net=net, mac=mac))

    if response.status_code == 200:
        if isinstance(response.json(), list) and len(response.json()) != 1:
            # No exact match; return not found
            return False, "Lease not found."
        else:
            # Return a single instance if the response is a list
            if isinstance(response.json(), list):
                return True, response.json()[0]
            # This shouldn't happen, but is here just in case
            else:
                return True, response.json()
    else:
        return False, response.json().get('message', '')


def net_dhcp_list(config, net, limit, only_static=False):
    """
    Get list information about leases (limited by {limit})

    API endpoint: GET /api/v1/network/{net}/lease
    API arguments: limit={limit}, static={only_static}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    if limit:
        params['limit'] = limit

    if only_static:
        params['static'] = True
    else:
        params['static'] = False

    response = call_api(config, 'get', '/network/{net}/lease'.format(net=net), params=params)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json().get('message', '')


def net_dhcp_add(config, net, ipaddr, macaddr, hostname):
    """
    Add new network DHCP lease

    API endpoint: POST /api/v1/network/{net}/lease
    API arguments: macaddress=macaddr, ipaddress=ipaddr, hostname=hostname
    API schema: {"message":"{data}"}
    """
    params = {
        'macaddress': macaddr,
        'ipaddress': ipaddr,
        'hostname': hostname
    }
    response = call_api(config, 'post', '/network/{net}/lease'.format(net=net), params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get('message', '')


def net_dhcp_remove(config, net, mac):
    """
    Remove a network DHCP lease

    API endpoint: DELETE /api/v1/network/{vni}/lease/{mac}
    API arguments:
    API schema: {"message":"{data}"}
    """
    response = call_api(config, 'delete', '/network/{net}/lease/{mac}'.format(net=net, mac=mac))

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get('message', '')


#
# ACL functions
#
def net_acl_info(config, net, description):
    """
    Get information about network ACL

    API endpoint: GET /api/v1/network/{net}/acl/{description}
    API arguments:
    API schema: {json_data_object}
    """
    response = call_api(config, 'get', '/network/{net}/acl/{description}'.format(net=net, description=description))

    if response.status_code == 200:
        if isinstance(response.json(), list) and len(response.json()) != 1:
            # No exact match; return not found
            return False, "ACL not found."
        else:
            # Return a single instance if the response is a list
            if isinstance(response.json(), list):
                return True, response.json()[0]
            # This shouldn't happen, but is here just in case
            else:
                return True, response.json()
    else:
        return False, response.json().get('message', '')


def net_acl_list(config, net, limit, direction):
    """
    Get list information about ACLs (limited by {limit})

    API endpoint: GET /api/v1/network/{net}/acl
    API arguments: limit={limit}, direction={direction}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    if limit:
        params['limit'] = limit
    if direction is not None:
        params['direction'] = direction

    response = call_api(config, 'get', '/network/{net}/acl'.format(net=net), params=params)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json().get('message', '')


def net_acl_add(config, net, direction, description, rule, order):
    """
    Add new network acl

    API endpoint: POST /api/v1/network/{net}/acl
    API arguments: description=description, direction=direction, order=order, rule=rule
    API schema: {"message":"{data}"}
    """
    params = dict()
    params['description'] = description
    params['direction'] = direction
    params['rule'] = rule
    if order is not None:
        params['order'] = order

    response = call_api(config, 'post', '/network/{net}/acl'.format(net=net), params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get('message', '')


def net_acl_remove(config, net, description):

    """
    Remove a network ACL

    API endpoint: DELETE /api/v1/network/{vni}/acl/{description}
    API arguments:
    API schema: {"message":"{data}"}
    """
    response = call_api(config, 'delete', '/network/{net}/acl/{description}'.format(net=net, description=description))

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get('message', '')


#
# Output display functions
#
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


def format_info(config, network_information, long_output):
    if not network_information:
        return "No network found"

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
            retcode, dhcp4_reservations_list = net_dhcp_list(config, network_information['vni'], None)
            if dhcp4_reservations_list:
                ainformation.append('')
                ainformation.append('{}Client DHCPv4 reservations:{}'.format(ansiprint.bold(), ansiprint.end()))
                ainformation.append('')
                if retcode:
                    dhcp4_reservations_string = format_list_dhcp(dhcp4_reservations_list)
                    for line in dhcp4_reservations_string.split('\n'):
                        ainformation.append(line)
                else:
                    ainformation.append("No leases found")

            retcode, firewall_rules_list = net_acl_list(config, network_information['vni'], None, None)
            if firewall_rules_list:
                ainformation.append('')
                ainformation.append('{}Network firewall rules:{}'.format(ansiprint.bold(), ansiprint.end()))
                ainformation.append('')
                if retcode:
                    firewall_rules_string = format_list_acl(firewall_rules_list)
                    for line in firewall_rules_string.split('\n'):
                        ainformation.append(line)
                else:
                    ainformation.append("No ACLs found")

    # Join it all together
    return '\n'.join(ainformation)


def format_list(config, network_list):
    if not network_list:
        return "No network found"

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
        net_dhcp4_flag='DHCPv4')
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

        network_list_output.append('{bold}\
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
            colour_off=ansiprint.end())
        )

    return '\n'.join(sorted(network_list_output))


def format_list_dhcp(dhcp_lease_list):
    dhcp_lease_list_output = []

    # Determine optimal column widths
    lease_hostname_length = 9
    lease_ip4_address_length = 11
    lease_mac_address_length = 13
    lease_timestamp_length = 13
    for dhcp_lease_information in dhcp_lease_list:
        # hostname column
        _lease_hostname_length = len(str(dhcp_lease_information['hostname'])) + 1
        if _lease_hostname_length > lease_hostname_length:
            lease_hostname_length = _lease_hostname_length
        # ip4_address column
        _lease_ip4_address_length = len(str(dhcp_lease_information['ip4_address'])) + 1
        if _lease_ip4_address_length > lease_ip4_address_length:
            lease_ip4_address_length = _lease_ip4_address_length
        # mac_address column
        _lease_mac_address_length = len(str(dhcp_lease_information['mac_address'])) + 1
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
        lease_timestamp='Timestamp')
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
            lease_hostname=str(dhcp_lease_information['hostname']),
            lease_ip4_address=str(dhcp_lease_information['ip4_address']),
            lease_mac_address=str(dhcp_lease_information['mac_address']),
            lease_timestamp=str(dhcp_lease_information['timestamp']))
        )

    return '\n'.join(sorted(dhcp_lease_list_output))


def format_list_acl(acl_list):
    # Handle when we get an empty entry
    if not acl_list:
        acl_list = list()

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
        acl_rule='Rule')
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
            acl_rule=acl_information['rule'])
        )

    return '\n'.join(sorted(acl_list_output))
