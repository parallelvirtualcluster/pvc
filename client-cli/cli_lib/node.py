#!/usr/bin/env python3

# node.py - PVC CLI client function library, node management
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

import cli_lib.ansiprint as ansiprint
from cli_lib.common import call_api


#
# Primary functions
#
def node_coordinator_state(config, node, action):
    """
    Set node coordinator state state (primary/secondary)

    API endpoint: POST /api/v1/node/{node}/coordinator-state
    API arguments: action={action}
    API schema: {"message": "{data}"}
    """
    params = {
        'state': action
    }
    response = call_api(config, 'post', '/node/{node}/coordinator-state'.format(node=node), params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get('message', '')


def node_domain_state(config, node, action, wait):
    """
    Set node domain state state (flush/ready)

    API endpoint: POST /api/v1/node/{node}/domain-state
    API arguments: action={action}, wait={wait}
    API schema: {"message": "{data}"}
    """
    params = {
        'state': action,
        'wait': str(wait).lower()
    }
    response = call_api(config, 'post', '/node/{node}/domain-state'.format(node=node), params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get('message', '')


def node_info(config, node):
    """
    Get information about node

    API endpoint: GET /api/v1/node/{node}
    API arguments:
    API schema: {json_data_object}
    """
    response = call_api(config, 'get', '/node/{node}'.format(node=node))

    if response.status_code == 200:
        if isinstance(response.json(), list) and len(response.json()) != 1:
            # No exact match, return not found
            return False, "Node not found."
        else:
            # Return a single instance if the response is a list
            if isinstance(response.json(), list):
                return True, response.json()[0]
            # This shouldn't happen, but is here just in case
            else:
                return True, response.json()
    else:
        return False, response.json().get('message', '')


def node_list(config, limit, target_daemon_state, target_coordinator_state, target_domain_state):
    """
    Get list information about nodes (limited by {limit})

    API endpoint: GET /api/v1/node
    API arguments: limit={limit}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    if limit:
        params['limit'] = limit
    if target_daemon_state:
        params['daemon_state'] = target_daemon_state
    if target_coordinator_state:
        params['coordinator_state'] = target_coordinator_state
    if target_domain_state:
        params['domain_state'] = target_domain_state

    response = call_api(config, 'get', '/node', params=params)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json().get('message', '')


#
# Output display functions
#
def getOutputColours(node_information):
    if node_information['daemon_state'] == 'run':
        daemon_state_colour = ansiprint.green()
    elif node_information['daemon_state'] == 'stop':
        daemon_state_colour = ansiprint.red()
    elif node_information['daemon_state'] == 'shutdown':
        daemon_state_colour = ansiprint.yellow()
    elif node_information['daemon_state'] == 'init':
        daemon_state_colour = ansiprint.yellow()
    elif node_information['daemon_state'] == 'dead':
        daemon_state_colour = ansiprint.red() + ansiprint.bold()
    else:
        daemon_state_colour = ansiprint.blue()

    if node_information['coordinator_state'] == 'primary':
        coordinator_state_colour = ansiprint.green()
    elif node_information['coordinator_state'] == 'secondary':
        coordinator_state_colour = ansiprint.blue()
    else:
        coordinator_state_colour = ansiprint.cyan()

    if node_information['domain_state'] == 'ready':
        domain_state_colour = ansiprint.green()
    else:
        domain_state_colour = ansiprint.blue()

    if node_information['memory']['allocated'] > node_information['memory']['total']:
        mem_allocated_colour = ansiprint.yellow()
    else:
        mem_allocated_colour = ''

    if node_information['memory']['provisioned'] > node_information['memory']['total']:
        mem_provisioned_colour = ansiprint.yellow()
    else:
        mem_provisioned_colour = ''

    return daemon_state_colour, coordinator_state_colour, domain_state_colour, mem_allocated_colour, mem_provisioned_colour


def format_info(node_information, long_output):
    daemon_state_colour, coordinator_state_colour, domain_state_colour, mem_allocated_colour, mem_provisioned_colour = getOutputColours(node_information)

    # Format a nice output; do this line-by-line then concat the elements at the end
    ainformation = []
    # Basic information
    ainformation.append('{}Name:{}                  {}'.format(ansiprint.purple(), ansiprint.end(), node_information['name']))
    ainformation.append('{}Daemon State:{}          {}{}{}'.format(ansiprint.purple(), ansiprint.end(), daemon_state_colour, node_information['daemon_state'], ansiprint.end()))
    ainformation.append('{}Coordinator State:{}     {}{}{}'.format(ansiprint.purple(), ansiprint.end(), coordinator_state_colour, node_information['coordinator_state'], ansiprint.end()))
    ainformation.append('{}Domain State:{}          {}{}{}'.format(ansiprint.purple(), ansiprint.end(), domain_state_colour, node_information['domain_state'], ansiprint.end()))
    ainformation.append('{}Active VM Count:{}       {}'.format(ansiprint.purple(), ansiprint.end(), node_information['domains_count']))
    if long_output:
        ainformation.append('')
        ainformation.append('{}Architecture:{}          {}'.format(ansiprint.purple(), ansiprint.end(), node_information['arch']))
        ainformation.append('{}Operating System:{}      {}'.format(ansiprint.purple(), ansiprint.end(), node_information['os']))
        ainformation.append('{}Kernel Version:{}        {}'.format(ansiprint.purple(), ansiprint.end(), node_information['kernel']))
    ainformation.append('')
    ainformation.append('{}Host CPUs:{}             {}'.format(ansiprint.purple(), ansiprint.end(), node_information['vcpu']['total']))
    ainformation.append('{}vCPUs:{}                 {}'.format(ansiprint.purple(), ansiprint.end(), node_information['vcpu']['allocated']))
    ainformation.append('{}Load:{}                  {}'.format(ansiprint.purple(), ansiprint.end(), node_information['load']))
    ainformation.append('{}Total RAM (MiB):{}       {}'.format(ansiprint.purple(), ansiprint.end(), node_information['memory']['total']))
    ainformation.append('{}Used RAM (MiB):{}        {}'.format(ansiprint.purple(), ansiprint.end(), node_information['memory']['used']))
    ainformation.append('{}Free RAM (MiB):{}        {}'.format(ansiprint.purple(), ansiprint.end(), node_information['memory']['free']))
    ainformation.append('{}Allocated RAM (MiB):{}   {}{}{}'.format(ansiprint.purple(), ansiprint.end(), mem_allocated_colour, node_information['memory']['allocated'], ansiprint.end()))
    ainformation.append('{}Provisioned RAM (MiB):{} {}{}{}'.format(ansiprint.purple(), ansiprint.end(), mem_provisioned_colour, node_information['memory']['provisioned'], ansiprint.end()))

    # Join it all together
    ainformation.append('')
    return '\n'.join(ainformation)


def format_list(node_list, raw):
    if raw:
        ainformation = list()
        for node in sorted(item['name'] for item in node_list):
            ainformation.append(node)
        return '\n'.join(ainformation)

    node_list_output = []

    # Determine optimal column widths
    node_name_length = 5
    daemon_state_length = 7
    coordinator_state_length = 12
    domain_state_length = 8
    domains_count_length = 4
    cpu_count_length = 6
    load_length = 5
    mem_total_length = 6
    mem_used_length = 5
    mem_free_length = 5
    mem_alloc_length = 6
    mem_prov_length = 5
    for node_information in node_list:
        # node_name column
        _node_name_length = len(node_information['name']) + 1
        if _node_name_length > node_name_length:
            node_name_length = _node_name_length
        # daemon_state column
        _daemon_state_length = len(node_information['daemon_state']) + 1
        if _daemon_state_length > daemon_state_length:
            daemon_state_length = _daemon_state_length
        # coordinator_state column
        _coordinator_state_length = len(node_information['coordinator_state']) + 1
        if _coordinator_state_length > coordinator_state_length:
            coordinator_state_length = _coordinator_state_length
        # domain_state column
        _domain_state_length = len(node_information['domain_state']) + 1
        if _domain_state_length > domain_state_length:
            domain_state_length = _domain_state_length
        # domains_count column
        _domains_count_length = len(str(node_information['domains_count'])) + 1
        if _domains_count_length > domains_count_length:
            domains_count_length = _domains_count_length
        # cpu_count column
        _cpu_count_length = len(str(node_information['cpu_count'])) + 1
        if _cpu_count_length > cpu_count_length:
            cpu_count_length = _cpu_count_length
        # load column
        _load_length = len(str(node_information['load'])) + 1
        if _load_length > load_length:
            load_length = _load_length
        # mem_total column
        _mem_total_length = len(str(node_information['memory']['total'])) + 1
        if _mem_total_length > mem_total_length:
            mem_total_length = _mem_total_length
        # mem_used column
        _mem_used_length = len(str(node_information['memory']['used'])) + 1
        if _mem_used_length > mem_used_length:
            mem_used_length = _mem_used_length
        # mem_free column
        _mem_free_length = len(str(node_information['memory']['free'])) + 1
        if _mem_free_length > mem_free_length:
            mem_free_length = _mem_free_length
        # mem_alloc column
        _mem_alloc_length = len(str(node_information['memory']['allocated'])) + 1
        if _mem_alloc_length > mem_alloc_length:
            mem_alloc_length = _mem_alloc_length

        # mem_prov column
        _mem_prov_length = len(str(node_information['memory']['provisioned'])) + 1
        if _mem_prov_length > mem_prov_length:
            mem_prov_length = _mem_prov_length

    # Format the string (header)
    node_list_output.append(
        '{bold}{node_name: <{node_name_length}} \
St: {daemon_state_colour}{node_daemon_state: <{daemon_state_length}}{end_colour} {coordinator_state_colour}{node_coordinator_state: <{coordinator_state_length}}{end_colour} {domain_state_colour}{node_domain_state: <{domain_state_length}}{end_colour} \
Res: {node_domains_count: <{domains_count_length}} {node_cpu_count: <{cpu_count_length}} {node_load: <{load_length}} \
Mem (M): {node_mem_total: <{mem_total_length}} {node_mem_used: <{mem_used_length}} {node_mem_free: <{mem_free_length}} {node_mem_allocated: <{mem_alloc_length}} {node_mem_provisioned: <{mem_prov_length}}{end_bold}'.format(
            node_name_length=node_name_length,
            daemon_state_length=daemon_state_length,
            coordinator_state_length=coordinator_state_length,
            domain_state_length=domain_state_length,
            domains_count_length=domains_count_length,
            cpu_count_length=cpu_count_length,
            load_length=load_length,
            mem_total_length=mem_total_length,
            mem_used_length=mem_used_length,
            mem_free_length=mem_free_length,
            mem_alloc_length=mem_alloc_length,
            mem_prov_length=mem_prov_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            daemon_state_colour='',
            coordinator_state_colour='',
            domain_state_colour='',
            end_colour='',
            node_name='Name',
            node_daemon_state='Daemon',
            node_coordinator_state='Coordinator',
            node_domain_state='Domain',
            node_domains_count='VMs',
            node_cpu_count='vCPUs',
            node_load='Load',
            node_mem_total='Total',
            node_mem_used='Used',
            node_mem_free='Free',
            node_mem_allocated='Alloc',
            node_mem_provisioned='Prov'
        )
    )

    # Format the string (elements)
    for node_information in node_list:
        daemon_state_colour, coordinator_state_colour, domain_state_colour, mem_allocated_colour, mem_provisioned_colour = getOutputColours(node_information)
        node_list_output.append(
            '{bold}{node_name: <{node_name_length}} \
    {daemon_state_colour}{node_daemon_state: <{daemon_state_length}}{end_colour} {coordinator_state_colour}{node_coordinator_state: <{coordinator_state_length}}{end_colour} {domain_state_colour}{node_domain_state: <{domain_state_length}}{end_colour} \
     {node_domains_count: <{domains_count_length}} {node_cpu_count: <{cpu_count_length}} {node_load: <{load_length}} \
         {node_mem_total: <{mem_total_length}} {node_mem_used: <{mem_used_length}} {node_mem_free: <{mem_free_length}} {mem_allocated_colour}{node_mem_allocated: <{mem_alloc_length}}{end_colour} {mem_provisioned_colour}{node_mem_provisioned: <{mem_prov_length}}{end_colour}{end_bold}'.format(
                node_name_length=node_name_length,
                daemon_state_length=daemon_state_length,
                coordinator_state_length=coordinator_state_length,
                domain_state_length=domain_state_length,
                domains_count_length=domains_count_length,
                cpu_count_length=cpu_count_length,
                load_length=load_length,
                mem_total_length=mem_total_length,
                mem_used_length=mem_used_length,
                mem_free_length=mem_free_length,
                mem_alloc_length=mem_alloc_length,
                mem_prov_length=mem_prov_length,
                bold='',
                end_bold='',
                daemon_state_colour=daemon_state_colour,
                coordinator_state_colour=coordinator_state_colour,
                domain_state_colour=domain_state_colour,
                mem_allocated_colour=mem_allocated_colour,
                mem_provisioned_colour=mem_allocated_colour,
                end_colour=ansiprint.end(),
                node_name=node_information['name'],
                node_daemon_state=node_information['daemon_state'],
                node_coordinator_state=node_information['coordinator_state'],
                node_domain_state=node_information['domain_state'],
                node_domains_count=node_information['domains_count'],
                node_cpu_count=node_information['vcpu']['allocated'],
                node_load=node_information['load'],
                node_mem_total=node_information['memory']['total'],
                node_mem_used=node_information['memory']['used'],
                node_mem_free=node_information['memory']['free'],
                node_mem_allocated=node_information['memory']['allocated'],
                node_mem_provisioned=node_information['memory']['provisioned']
            )
        )

    return '\n'.join(sorted(node_list_output))
