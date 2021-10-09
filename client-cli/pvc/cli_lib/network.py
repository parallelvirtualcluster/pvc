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
import pvc.cli_lib.ansiprint as ansiprint
from pvc.cli_lib.common import call_api


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


def net_add(config, vni, description, nettype, mtu, domain, name_servers, ip4_network, ip4_gateway, ip6_network, ip6_gateway, dhcp4_flag, dhcp4_start, dhcp4_end):
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
        'mtu': mtu,
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


def net_modify(config, net, description, mtu, domain, name_servers, ip4_network, ip4_gateway, ip6_network, ip6_gateway, dhcp4_flag, dhcp4_start, dhcp4_end):
    """
    Modify a network

    API endpoint: POST /api/v1/network/{net}
    API arguments: lots
    API schema: {"message":"{data}"}
    """
    params = dict()
    if description is not None:
        params['description'] = description
    if mtu is not None:
        params['mtu'] = mtu
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
# SR-IOV functions
#
def net_sriov_pf_list(config, node):
    """
    List all PFs on NODE

    API endpoint: GET /api/v1/sriov/pf/<node>
    API arguments: node={node}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    response = call_api(config, 'get', '/sriov/pf/{}'.format(node))

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json().get('message', '')


def net_sriov_vf_set(config, node, vf, vlan_id, vlan_qos, tx_rate_min, tx_rate_max, link_state, spoof_check, trust, query_rss):
    """
    Mdoify configuration of a SR-IOV VF

    API endpoint: PUT /api/v1/sriov/vf/<node>/<vf>
    API arguments: vlan_id={vlan_id}, vlan_qos={vlan_qos}, tx_rate_min={tx_rate_min}, tx_rate_max={tx_rate_max},
                   link_state={link_state}, spoof_check={spoof_check}, trust={trust}, query_rss={query_rss}
    API schema: {"message": "{data}"}
    """
    params = dict()

    # Update any params that we've sent
    if vlan_id is not None:
        params['vlan_id'] = vlan_id

    if vlan_qos is not None:
        params['vlan_qos'] = vlan_qos

    if tx_rate_min is not None:
        params['tx_rate_min'] = tx_rate_min

    if tx_rate_max is not None:
        params['tx_rate_max'] = tx_rate_max

    if link_state is not None:
        params['link_state'] = link_state

    if spoof_check is not None:
        params['spoof_check'] = spoof_check

    if trust is not None:
        params['trust'] = trust

    if query_rss is not None:
        params['query_rss'] = query_rss

    # Write the new configuration to the API
    response = call_api(config, 'put', '/sriov/vf/{node}/{vf}'.format(node=node, vf=vf), params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get('message', '')


def net_sriov_vf_list(config, node, pf=None):
    """
    List all VFs on NODE, optionally limited by PF

    API endpoint: GET /api/v1/sriov/vf/<node>
    API arguments: node={node}, pf={pf}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    params['pf'] = pf

    response = call_api(config, 'get', '/sriov/vf/{}'.format(node), params=params)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json().get('message', '')


def net_sriov_vf_info(config, node, vf):
    """
    Get info about VF on NODE

    API endpoint: GET /api/v1/sriov/vf/<node>/<vf>
    API arguments:
    API schema: [{json_data_object}]
    """
    response = call_api(config, 'get', '/sriov/vf/{}/{}'.format(node, vf))

    if response.status_code == 200:
        if isinstance(response.json(), list) and len(response.json()) != 1:
            # No exact match; return not found
            return False, "VF not found."
        else:
            # Return a single instance if the response is a list
            if isinstance(response.json(), list):
                return True, response.json()[0]
            # This shouldn't happen, but is here just in case
            else:
                return True, response.json()
    else:
        return False, response.json().get('message', '')


#
# Output display functions
#
def getColour(value):
    if value in ["False", "None"]:
        return ansiprint.blue()
    else:
        return ansiprint.green()


def getOutputColours(network_information):
    v6_flag_colour = getColour(network_information['ip6']['network'])
    v4_flag_colour = getColour(network_information['ip4']['network'])
    dhcp6_flag_colour = getColour(network_information['ip6']['dhcp_flag'])
    dhcp4_flag_colour = getColour(network_information['ip4']['dhcp_flag'])

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
    ainformation.append('{}MTU:{}            {}'.format(ansiprint.purple(), ansiprint.end(), network_information['mtu']))
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
    net_mtu_length = 4
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
        # mtu column
        _net_mtu_length = len(str(network_information['mtu'])) + 1
        if _net_mtu_length > net_mtu_length:
            net_mtu_length = _net_mtu_length
        # domain column
        _net_domain_length = len(network_information['domain']) + 1
        if _net_domain_length > net_domain_length:
            net_domain_length = _net_domain_length

    # Format the string (header)
    network_list_output.append('{bold}{networks_header: <{networks_header_length}} {config_header: <{config_header_length}}{end_bold}'.format(
        bold=ansiprint.bold(),
        end_bold=ansiprint.end(),
        networks_header_length=net_vni_length + net_description_length + 1,
        config_header_length=net_nettype_length + net_mtu_length + net_domain_length + net_v6_flag_length + net_dhcp6_flag_length + net_v4_flag_length + net_dhcp4_flag_length + 7,
        networks_header='Networks ' + ''.join(['-' for _ in range(9, net_vni_length + net_description_length)]),
        config_header='Config ' + ''.join(['-' for _ in range(7, net_nettype_length + net_mtu_length + net_domain_length + net_v6_flag_length + net_dhcp6_flag_length + net_v4_flag_length + net_dhcp4_flag_length + 6)]))
    )
    network_list_output.append('{bold}\
{net_vni: <{net_vni_length}} \
{net_description: <{net_description_length}} \
{net_nettype: <{net_nettype_length}} \
{net_mtu: <{net_mtu_length}} \
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
        net_mtu_length=net_mtu_length,
        net_domain_length=net_domain_length,
        net_v6_flag_length=net_v6_flag_length,
        net_dhcp6_flag_length=net_dhcp6_flag_length,
        net_v4_flag_length=net_v4_flag_length,
        net_dhcp4_flag_length=net_dhcp4_flag_length,
        net_vni='VNI',
        net_description='Description',
        net_nettype='Type',
        net_mtu='MTU',
        net_domain='Domain',
        net_v6_flag='IPv6',
        net_dhcp6_flag='DHCPv6',
        net_v4_flag='IPv4',
        net_dhcp4_flag='DHCPv4')
    )

    for network_information in sorted(network_list, key=lambda n: int(n['vni'])):
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
{net_mtu: <{net_mtu_length}} \
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
            net_mtu_length=net_mtu_length,
            net_domain_length=net_domain_length,
            net_v6_flag_length=net_v6_flag_length,
            net_dhcp6_flag_length=net_dhcp6_flag_length,
            net_v4_flag_length=net_v4_flag_length,
            net_dhcp4_flag_length=net_dhcp4_flag_length,
            net_vni=network_information['vni'],
            net_description=network_information['description'],
            net_nettype=network_information['type'],
            net_mtu=network_information['mtu'],
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

    return '\n'.join(network_list_output)


def format_list_dhcp(dhcp_lease_list):
    dhcp_lease_list_output = []

    # Determine optimal column widths
    lease_hostname_length = 9
    lease_ip4_address_length = 11
    lease_mac_address_length = 13
    lease_timestamp_length = 10
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
        # timestamp column
        _lease_timestamp_length = len(str(dhcp_lease_information['timestamp'])) + 1
        if _lease_timestamp_length > lease_timestamp_length:
            lease_timestamp_length = _lease_timestamp_length

    # Format the string (header)
    dhcp_lease_list_output.append('{bold}{lease_header: <{lease_header_length}}{end_bold}'.format(
        bold=ansiprint.bold(),
        end_bold=ansiprint.end(),
        lease_header_length=lease_hostname_length + lease_ip4_address_length + lease_mac_address_length + lease_timestamp_length + 3,
        lease_header='Leases ' + ''.join(['-' for _ in range(7, lease_hostname_length + lease_ip4_address_length + lease_mac_address_length + lease_timestamp_length + 2)]))
    )

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

    for dhcp_lease_information in sorted(dhcp_lease_list, key=lambda l: l['hostname']):
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

    return '\n'.join(dhcp_lease_list_output)


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
    acl_list_output.append('{bold}{acl_header: <{acl_header_length}}{end_bold}'.format(
        bold=ansiprint.bold(),
        end_bold=ansiprint.end(),
        acl_header_length=acl_direction_length + acl_order_length + acl_description_length + acl_rule_length + 3,
        acl_header='ACLs ' + ''.join(['-' for _ in range(5, acl_direction_length + acl_order_length + acl_description_length + acl_rule_length + 2)]))
    )

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

    for acl_information in sorted(acl_list, key=lambda l: l['direction'] + str(l['order'])):
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

    return '\n'.join(acl_list_output)


def format_list_sriov_pf(pf_list):
    # The maximum column width of the VFs column
    max_vfs_length = 70

    # Handle when we get an empty entry
    if not pf_list:
        pf_list = list()

    pf_list_output = []

    # Determine optimal column widths
    pf_phy_length = 6
    pf_mtu_length = 4
    pf_vfs_length = 4

    for pf_information in pf_list:
        # phy column
        _pf_phy_length = len(str(pf_information['phy'])) + 1
        if _pf_phy_length > pf_phy_length:
            pf_phy_length = _pf_phy_length
        # mtu column
        _pf_mtu_length = len(str(pf_information['mtu'])) + 1
        if _pf_mtu_length > pf_mtu_length:
            pf_mtu_length = _pf_mtu_length
        # vfs column
        _pf_vfs_length = len(str(', '.join(pf_information['vfs']))) + 1
        if _pf_vfs_length > pf_vfs_length:
            pf_vfs_length = _pf_vfs_length

    # We handle columnizing very long lists later
    if pf_vfs_length > max_vfs_length:
        pf_vfs_length = max_vfs_length

    # Format the string (header)
    pf_list_output.append('{bold}{pf_header: <{pf_header_length}}{end_bold}'.format(
        bold=ansiprint.bold(),
        end_bold=ansiprint.end(),
        pf_header_length=pf_phy_length + pf_mtu_length + pf_vfs_length + 2,
        pf_header='PFs ' + ''.join(['-' for _ in range(4, pf_phy_length + pf_mtu_length + pf_vfs_length + 1)]))
    )

    pf_list_output.append('{bold}\
{pf_phy: <{pf_phy_length}} \
{pf_mtu: <{pf_mtu_length}} \
{pf_vfs: <{pf_vfs_length}} \
{end_bold}'.format(
        bold=ansiprint.bold(),
        end_bold=ansiprint.end(),
        pf_phy_length=pf_phy_length,
        pf_mtu_length=pf_mtu_length,
        pf_vfs_length=pf_vfs_length,
        pf_phy='Device',
        pf_mtu='MTU',
        pf_vfs='VFs')
    )

    for pf_information in sorted(pf_list, key=lambda p: p['phy']):
        # Figure out how to nicely columnize our list
        nice_vfs_list = [list()]
        vfs_lines = 0
        cur_vfs_length = 0
        for vfs in pf_information['vfs']:
            vfs_len = len(vfs)
            cur_vfs_length += vfs_len + 2  # for the comma and space
            if cur_vfs_length > max_vfs_length:
                cur_vfs_length = 0
                vfs_lines += 1
                nice_vfs_list.append(list())
            nice_vfs_list[vfs_lines].append(vfs)

        # Append the lines
        pf_list_output.append('{bold}\
{pf_phy: <{pf_phy_length}} \
{pf_mtu: <{pf_mtu_length}} \
{pf_vfs: <{pf_vfs_length}} \
{end_bold}'.format(
            bold='',
            end_bold='',
            pf_phy_length=pf_phy_length,
            pf_mtu_length=pf_mtu_length,
            pf_vfs_length=pf_vfs_length,
            pf_phy=pf_information['phy'],
            pf_mtu=pf_information['mtu'],
            pf_vfs=', '.join(nice_vfs_list[0]))
        )

        if len(nice_vfs_list) > 1:
            for idx in range(1, len(nice_vfs_list)):
                pf_list_output.append('{bold}\
{pf_phy: <{pf_phy_length}} \
{pf_mtu: <{pf_mtu_length}} \
{pf_vfs: <{pf_vfs_length}} \
{end_bold}'.format(
                    bold='',
                    end_bold='',
                    pf_phy_length=pf_phy_length,
                    pf_mtu_length=pf_mtu_length,
                    pf_vfs_length=pf_vfs_length,
                    pf_phy='',
                    pf_mtu='',
                    pf_vfs=', '.join(nice_vfs_list[idx]))
                )

    return '\n'.join(pf_list_output)


def format_list_sriov_vf(vf_list):
    # Handle when we get an empty entry
    if not vf_list:
        vf_list = list()

    vf_list_output = []

    # Determine optimal column widths
    vf_phy_length = 4
    vf_pf_length = 3
    vf_mtu_length = 4
    vf_mac_length = 11
    vf_used_length = 5
    vf_domain_length = 5

    for vf_information in vf_list:
        # phy column
        _vf_phy_length = len(str(vf_information['phy'])) + 1
        if _vf_phy_length > vf_phy_length:
            vf_phy_length = _vf_phy_length
        # pf column
        _vf_pf_length = len(str(vf_information['pf'])) + 1
        if _vf_pf_length > vf_pf_length:
            vf_pf_length = _vf_pf_length
        # mtu column
        _vf_mtu_length = len(str(vf_information['mtu'])) + 1
        if _vf_mtu_length > vf_mtu_length:
            vf_mtu_length = _vf_mtu_length
        # mac column
        _vf_mac_length = len(str(vf_information['mac'])) + 1
        if _vf_mac_length > vf_mac_length:
            vf_mac_length = _vf_mac_length
        # used column
        _vf_used_length = len(str(vf_information['usage']['used'])) + 1
        if _vf_used_length > vf_used_length:
            vf_used_length = _vf_used_length
        # domain column
        _vf_domain_length = len(str(vf_information['usage']['domain'])) + 1
        if _vf_domain_length > vf_domain_length:
            vf_domain_length = _vf_domain_length

    # Format the string (header)
    vf_list_output.append('{bold}{vf_header: <{vf_header_length}}{end_bold}'.format(
        bold=ansiprint.bold(),
        end_bold=ansiprint.end(),
        vf_header_length=vf_phy_length + vf_pf_length + vf_mtu_length + vf_mac_length + vf_used_length + vf_domain_length + 5,
        vf_header='VFs ' + ''.join(['-' for _ in range(4, vf_phy_length + vf_pf_length + vf_mtu_length + vf_mac_length + vf_used_length + vf_domain_length + 4)]))
    )

    vf_list_output.append('{bold}\
{vf_phy: <{vf_phy_length}} \
{vf_pf: <{vf_pf_length}} \
{vf_mtu: <{vf_mtu_length}} \
{vf_mac: <{vf_mac_length}} \
{vf_used: <{vf_used_length}} \
{vf_domain: <{vf_domain_length}} \
{end_bold}'.format(
        bold=ansiprint.bold(),
        end_bold=ansiprint.end(),
        vf_phy_length=vf_phy_length,
        vf_pf_length=vf_pf_length,
        vf_mtu_length=vf_mtu_length,
        vf_mac_length=vf_mac_length,
        vf_used_length=vf_used_length,
        vf_domain_length=vf_domain_length,
        vf_phy='Device',
        vf_pf='PF',
        vf_mtu='MTU',
        vf_mac='MAC Address',
        vf_used='Used',
        vf_domain='Domain')
    )

    for vf_information in sorted(vf_list, key=lambda v: v['phy']):
        vf_domain = vf_information['usage']['domain']
        if not vf_domain:
            vf_domain = 'N/A'

        vf_list_output.append('{bold}\
{vf_phy: <{vf_phy_length}} \
{vf_pf: <{vf_pf_length}} \
{vf_mtu: <{vf_mtu_length}} \
{vf_mac: <{vf_mac_length}} \
{vf_used: <{vf_used_length}} \
{vf_domain: <{vf_domain_length}} \
{end_bold}'.format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            vf_phy_length=vf_phy_length,
            vf_pf_length=vf_pf_length,
            vf_mtu_length=vf_mtu_length,
            vf_mac_length=vf_mac_length,
            vf_used_length=vf_used_length,
            vf_domain_length=vf_domain_length,
            vf_phy=vf_information['phy'],
            vf_pf=vf_information['pf'],
            vf_mtu=vf_information['mtu'],
            vf_mac=vf_information['mac'],
            vf_used=vf_information['usage']['used'],
            vf_domain=vf_domain)
        )

    return '\n'.join(vf_list_output)


def format_info_sriov_vf(config, vf_information, node):
    if not vf_information:
        return "No VF found"

    # Get information on the using VM if applicable
    if vf_information['usage']['used'] == 'True' and vf_information['usage']['domain']:
        vm_information = call_api(config, 'get', '/vm/{vm}'.format(vm=vf_information['usage']['domain'])).json()
        if isinstance(vm_information, list) and len(vm_information) > 0:
            vm_information = vm_information[0]
        else:
            vm_information = None

    # Format a nice output: do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append('{}SR-IOV VF information:{}'.format(ansiprint.bold(), ansiprint.end()))
    ainformation.append('')
    # Basic information
    ainformation.append('{}PHY:{}               {}'.format(ansiprint.purple(), ansiprint.end(), vf_information['phy']))
    ainformation.append('{}PF:{}                {} @ {}'.format(ansiprint.purple(), ansiprint.end(), vf_information['pf'], node))
    ainformation.append('{}MTU:{}               {}'.format(ansiprint.purple(), ansiprint.end(), vf_information['mtu']))
    ainformation.append('{}MAC Address:{}       {}'.format(ansiprint.purple(), ansiprint.end(), vf_information['mac']))
    ainformation.append('')
    # Configuration information
    ainformation.append('{}vLAN ID:{}           {}'.format(ansiprint.purple(), ansiprint.end(), vf_information['config']['vlan_id']))
    ainformation.append('{}vLAN QOS priority:{} {}'.format(ansiprint.purple(), ansiprint.end(), vf_information['config']['vlan_qos']))
    ainformation.append('{}Minimum TX Rate:{}   {}'.format(ansiprint.purple(), ansiprint.end(), vf_information['config']['tx_rate_min']))
    ainformation.append('{}Maximum TX Rate:{}   {}'.format(ansiprint.purple(), ansiprint.end(), vf_information['config']['tx_rate_max']))
    ainformation.append('{}Link State:{}        {}'.format(ansiprint.purple(), ansiprint.end(), vf_information['config']['link_state']))
    ainformation.append('{}Spoof Checking:{}    {}{}{}'.format(ansiprint.purple(), ansiprint.end(), getColour(vf_information['config']['spoof_check']), vf_information['config']['spoof_check'], ansiprint.end()))
    ainformation.append('{}VF User Trust:{}     {}{}{}'.format(ansiprint.purple(), ansiprint.end(), getColour(vf_information['config']['trust']), vf_information['config']['trust'], ansiprint.end()))
    ainformation.append('{}Query RSS Config:{}  {}{}{}'.format(ansiprint.purple(), ansiprint.end(), getColour(vf_information['config']['query_rss']), vf_information['config']['query_rss'], ansiprint.end()))
    ainformation.append('')
    # PCIe bus information
    ainformation.append('{}PCIe domain:{}       {}'.format(ansiprint.purple(), ansiprint.end(), vf_information['pci']['domain']))
    ainformation.append('{}PCIe bus:{}          {}'.format(ansiprint.purple(), ansiprint.end(), vf_information['pci']['bus']))
    ainformation.append('{}PCIe slot:{}         {}'.format(ansiprint.purple(), ansiprint.end(), vf_information['pci']['slot']))
    ainformation.append('{}PCIe function:{}     {}'.format(ansiprint.purple(), ansiprint.end(), vf_information['pci']['function']))
    ainformation.append('')
    # Usage information
    ainformation.append('{}VF Used:{}           {}{}{}'.format(ansiprint.purple(), ansiprint.end(), getColour(vf_information['usage']['used']), vf_information['usage']['used'], ansiprint.end()))
    if vf_information['usage']['used'] == 'True' and vm_information is not None:
        ainformation.append('{}Using Domain:{}      {} ({}) ({}{}{})'.format(ansiprint.purple(), ansiprint.end(), vf_information['usage']['domain'], vm_information['name'], getColour(vm_information['state']), vm_information['state'], ansiprint.end()))
    else:
        ainformation.append('{}Using Domain:{}      N/A'.format(ansiprint.purple(), ansiprint.end()))

    # Join it all together
    return '\n'.join(ainformation)
