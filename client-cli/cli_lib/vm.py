#!/usr/bin/env python3

# vm.py - PVC CLI client function library, VM functions
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

import time
import re

import cli_lib.ansiprint as ansiprint
from cli_lib.common import call_api, format_bytes, format_metric


#
# Primary functions
#
def vm_info(config, vm):
    """
    Get information about (single) VM

    API endpoint: GET /api/v1/vm/{vm}
    API arguments:
    API schema: {json_data_object}
    """
    response = call_api(config, 'get', '/vm/{vm}'.format(vm=vm))

    if response.status_code == 200:
        if isinstance(response.json(), list) and len(response.json()) > 1:
            # No exact match; return not found
            return False, "VM not found."
        else:
            if isinstance(response.json(), list):
                response = response.json()[0]
            else:
                response = response.json()
            return True, response
        return True, response.json()
    else:
        return False, response.json().get('message', '')


def vm_list(config, limit, target_node, target_state):
    """
    Get list information about VMs (limited by {limit}, {target_node}, or {target_state})

    API endpoint: GET /api/v1/vm
    API arguments: limit={limit}, node={target_node}, state={target_state}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    if limit:
        params['limit'] = limit
    if target_node:
        params['node'] = target_node
    if target_state:
        params['state'] = target_state

    response = call_api(config, 'get', '/vm', params=params)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json().get('message', '')


def vm_define(config, xml, node, node_limit, node_selector, node_autostart, migration_method):
    """
    Define a new VM on the cluster

    API endpoint: POST /vm
    API arguments: xml={xml}, node={node}, limit={node_limit}, selector={node_selector}, autostart={node_autostart}, migration_method={migration_method}
    API schema: {"message":"{data}"}
    """
    params = {
        'node': node,
        'limit': node_limit,
        'selector': node_selector,
        'autostart': node_autostart,
        'migration_method': migration_method
    }
    data = {
        'xml': xml
    }
    response = call_api(config, 'post', '/vm', params=params, data=data)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get('message', '')


def vm_modify(config, vm, xml, restart):
    """
    Modify the configuration of VM

    API endpoint: PUT /vm/{vm}
    API arguments: xml={xml}, restart={restart}
    API schema: {"message":"{data}"}
    """
    params = {
        'restart': restart
    }
    data = {
        'xml': xml
    }
    response = call_api(config, 'put', '/vm/{vm}'.format(vm=vm), params=params, data=data)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get('message', '')


def vm_metadata(config, vm, node_limit, node_selector, node_autostart, migration_method, provisioner_profile):
    """
    Modify PVC metadata of a VM

    API endpoint: GET /vm/{vm}/meta,  POST /vm/{vm}/meta
    API arguments: limit={node_limit}, selector={node_selector}, autostart={node_autostart}, migration_method={migration_method} profile={provisioner_profile}
    API schema: {"message":"{data}"}
    """
    params = dict()

    # Update any params that we've sent
    if node_limit is not None:
        params['limit'] = node_limit

    if node_selector is not None:
        params['selector'] = node_selector

    if node_autostart is not None:
        params['autostart'] = node_autostart

    if migration_method is not None:
        params['migration_method'] = migration_method

    if provisioner_profile is not None:
        params['profile'] = provisioner_profile

    # Write the new metadata
    response = call_api(config, 'post', '/vm/{vm}/meta'.format(vm=vm), params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get('message', '')


def vm_remove(config, vm, delete_disks=False):
    """
    Remove a VM

    API endpoint: DELETE /vm/{vm}
    API arguments: delete_disks={delete_disks}
    API schema: {"message":"{data}"}
    """
    params = {
        'delete_disks': delete_disks
    }
    response = call_api(config, 'delete', '/vm/{vm}'.format(vm=vm), params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get('message', '')


def vm_state(config, vm, target_state, wait=False):
    """
    Modify the current state of VM

    API endpoint: POST /vm/{vm}/state
    API arguments: state={state}, wait={wait}
    API schema: {"message":"{data}"}
    """
    params = {
        'state': target_state,
        'wait': str(wait).lower()
    }
    response = call_api(config, 'post', '/vm/{vm}/state'.format(vm=vm), params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get('message', '')


def vm_node(config, vm, target_node, action, force=False, wait=False, force_live=False):
    """
    Modify the current node of VM via {action}

    API endpoint: POST /vm/{vm}/node
    API arguments: node={target_node}, action={action}, force={force}, wait={wait}, force_live={force_live}
    API schema: {"message":"{data}"}
    """
    params = {
        'node': target_node,
        'action': action,
        'force': str(force).lower(),
        'wait': str(wait).lower(),
        'force_live': str(force_live).lower()
    }
    response = call_api(config, 'post', '/vm/{vm}/node'.format(vm=vm), params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get('message', '')


def vm_locks(config, vm):
    """
    Flush RBD locks of (stopped) VM

    API endpoint: POST /vm/{vm}/locks
    API arguments:
    API schema: {"message":"{data}"}
    """
    response = call_api(config, 'post', '/vm/{vm}/locks'.format(vm=vm))

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get('message', '')


def view_console_log(config, vm, lines=100):
    """
    Return console log lines from the API (and display them in a pager in the main CLI)

    API endpoint: GET /vm/{vm}/console
    API arguments: lines={lines}
    API schema: {"name":"{vmname}","data":"{console_log}"}
    """
    params = {
        'lines': lines
    }
    response = call_api(config, 'get', '/vm/{vm}/console'.format(vm=vm), params=params)

    if response.status_code != 200:
        return False, response.json().get('message', '')

    console_log = response.json()['data']

    # Shrink the log buffer to length lines
    shrunk_log = console_log.split('\n')[-lines:]
    loglines = '\n'.join(shrunk_log)

    return True, loglines


def follow_console_log(config, vm, lines=10):
    """
    Return and follow console log lines from the API

    API endpoint: GET /vm/{vm}/console
    API arguments: lines={lines}
    API schema: {"name":"{vmname}","data":"{console_log}"}
    """
    params = {
        'lines': lines
    }
    response = call_api(config, 'get', '/vm/{vm}/console'.format(vm=vm), params=params)

    if response.status_code != 200:
        return False, response.json().get('message', '')

    # Shrink the log buffer to length lines
    console_log = response.json()['data']
    shrunk_log = console_log.split('\n')[-lines:]
    loglines = '\n'.join(shrunk_log)

    # Print the initial data and begin following
    print(loglines, end='')

    while True:
        # Grab the next line set
        try:
            response = call_api(config, 'get', '/vm/{vm}/console'.format(vm=vm), params=params)
            new_console_log = response.json()['data']
        except Exception:
            break
        # Split the new and old log strings into constitutent lines
        old_console_loglines = console_log.split('\n')
        new_console_loglines = new_console_log.split('\n')
        # Set the console log to the new log value for the next iteration
        console_log = new_console_log
        # Remove the lines from the old log until we hit the first line of the new log; this
        # ensures that the old log is a string that we can remove from the new log entirely
        for index, line in enumerate(old_console_loglines, start=0):
            if line == new_console_loglines[0]:
                del old_console_loglines[0:index]
                break
        # Rejoin the log lines into strings
        old_console_log = '\n'.join(old_console_loglines)
        new_console_log = '\n'.join(new_console_loglines)
        # Remove the old lines from the new log
        diff_console_log = new_console_log.replace(old_console_log, "")
        # If there's a difference, print it out
        if diff_console_log:
            print(diff_console_log, end='')
        # Wait a second
        time.sleep(1)

    return True, ''


#
# Output display functions
#
def format_info(config, domain_information, long_output):
    # Format a nice output; do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append('{}Virtual machine information:{}'.format(ansiprint.bold(), ansiprint.end()))
    ainformation.append('')
    # Basic information
    ainformation.append('{}UUID:{}               {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['uuid']))
    ainformation.append('{}Name:{}               {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['name']))
    ainformation.append('{}Description:{}        {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['description']))
    ainformation.append('{}Profile:{}            {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['profile']))
    ainformation.append('{}Memory (M):{}         {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['memory']))
    ainformation.append('{}vCPUs:{}              {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['vcpu']))
    ainformation.append('{}Topology (S/C/T):{}   {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['vcpu_topology']))

    if long_output is True:
        # Virtualization information
        ainformation.append('')
        ainformation.append('{}Emulator:{}           {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['emulator']))
        ainformation.append('{}Type:{}               {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['type']))
        ainformation.append('{}Arch:{}               {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['arch']))
        ainformation.append('{}Machine:{}            {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['machine']))
        ainformation.append('{}Features:{}           {}'.format(ansiprint.purple(), ansiprint.end(), ' '.join(domain_information['features'])))
        ainformation.append('')
        ainformation.append('{0}Memory stats:{1}       {2}Swap In  Swap Out  Faults (maj/min)  Available  Usable  Unused  RSS{3}'.format(ansiprint.purple(), ansiprint.end(), ansiprint.bold(), ansiprint.end()))
        ainformation.append('                    {0: <7}  {1: <8}  {2: <16}  {3: <10} {4: <7} {5: <7} {6: <10}'.format(
            format_metric(domain_information['memory_stats'].get('swap_in')),
            format_metric(domain_information['memory_stats'].get('swap_out')),
            '/'.join([format_metric(domain_information['memory_stats'].get('major_fault')), format_metric(domain_information['memory_stats'].get('minor_fault'))]),
            format_bytes(domain_information['memory_stats'].get('available') * 1024),
            format_bytes(domain_information['memory_stats'].get('usable') * 1024),
            format_bytes(domain_information['memory_stats'].get('unused') * 1024),
            format_bytes(domain_information['memory_stats'].get('rss') * 1024)
        ))
        ainformation.append('')
        ainformation.append('{0}vCPU stats:{1}         {2}CPU time (ns)     User time (ns)    System time (ns){3}'.format(ansiprint.purple(), ansiprint.end(), ansiprint.bold(), ansiprint.end()))
        ainformation.append('                    {0: <16}  {1: <16}  {2: <15}'.format(
            str(domain_information['vcpu_stats'].get('cpu_time')),
            str(domain_information['vcpu_stats'].get('user_time')),
            str(domain_information['vcpu_stats'].get('system_time'))
        ))

    # PVC cluster information
    ainformation.append('')
    dstate_colour = {
        'start': ansiprint.green(),
        'restart': ansiprint.yellow(),
        'shutdown': ansiprint.yellow(),
        'stop': ansiprint.red(),
        'disable': ansiprint.blue(),
        'fail': ansiprint.red(),
        'migrate': ansiprint.blue(),
        'unmigrate': ansiprint.blue(),
        'provision': ansiprint.blue()
    }
    ainformation.append('{}State:{}              {}{}{}'.format(ansiprint.purple(), ansiprint.end(), dstate_colour[domain_information['state']], domain_information['state'], ansiprint.end()))
    ainformation.append('{}Current Node:{}       {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['node']))
    if not domain_information['last_node']:
        domain_information['last_node'] = "N/A"
    ainformation.append('{}Previous Node:{}      {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['last_node']))

    # Get a failure reason if applicable
    if domain_information['failed_reason']:
        ainformation.append('')
        ainformation.append('{}Failure reason:{}     {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['failed_reason']))

    if not domain_information.get('node_selector'):
        formatted_node_selector = "False"
    else:
        formatted_node_selector = domain_information['node_selector']

    if not domain_information.get('node_limit'):
        formatted_node_limit = "False"
    else:
        formatted_node_limit = ', '.join(domain_information['node_limit'])

    if not domain_information.get('node_autostart'):
        formatted_node_autostart = "False"
    else:
        formatted_node_autostart = domain_information['node_autostart']

    if not domain_information.get('migration_method'):
        formatted_migration_method = "none"
    else:
        formatted_migration_method = domain_information['migration_method']

    ainformation.append('{}Migration selector:{} {}'.format(ansiprint.purple(), ansiprint.end(), formatted_node_selector))
    ainformation.append('{}Node limit:{}         {}'.format(ansiprint.purple(), ansiprint.end(), formatted_node_limit))
    ainformation.append('{}Autostart:{}          {}'.format(ansiprint.purple(), ansiprint.end(), formatted_node_autostart))
    ainformation.append('{}Migration Method:{}   {}'.format(ansiprint.purple(), ansiprint.end(), formatted_migration_method))

    # Network list
    net_list = []
    for net in domain_information['networks']:
        # Split out just the numerical (VNI) part of the brXXXX name
        net_vnis = re.findall(r'\d+', net['source'])
        if net_vnis:
            net_vni = net_vnis[0]
        else:
            net_vni = re.sub('br', '', net['source'])

        response = call_api(config, 'get', '/network/{net}'.format(net=net_vni))
        if response.status_code != 200 and net_vni not in ['cluster', 'storage', 'upstream']:
            net_list.append(ansiprint.red() + net_vni + ansiprint.end() + ' [invalid]')
        else:
            net_list.append(net_vni)

    ainformation.append('')
    ainformation.append('{}Networks:{}           {}'.format(ansiprint.purple(), ansiprint.end(), ', '.join(net_list)))

    if long_output is True:
        # Disk list
        ainformation.append('')
        name_length = 0
        for disk in domain_information['disks']:
            _name_length = len(disk['name']) + 1
            if _name_length > name_length:
                name_length = _name_length
        ainformation.append('{0}Disks:{1}        {2}ID  Type  {3: <{width}} Dev  Bus    Requests (r/w)   Data (r/w){4}'.format(ansiprint.purple(), ansiprint.end(), ansiprint.bold(), 'Name', ansiprint.end(), width=name_length))
        for disk in domain_information['disks']:
            ainformation.append('              {0: <3} {1: <5} {2: <{width}} {3: <4} {4: <5}  {5: <15}  {6}'.format(
                domain_information['disks'].index(disk),
                disk['type'],
                disk['name'],
                disk['dev'],
                disk['bus'],
                '/'.join([str(format_metric(disk['rd_req'])), str(format_metric(disk['wr_req']))]),
                '/'.join([str(format_bytes(disk['rd_bytes'])), str(format_bytes(disk['wr_bytes']))]),
                width=name_length
            ))
        ainformation.append('')
        ainformation.append('{}Interfaces:{}   {}ID  Type    Source     Model    MAC                 Data (r/w)   Packets (r/w)   Errors (r/w){}'.format(ansiprint.purple(), ansiprint.end(), ansiprint.bold(), ansiprint.end()))
        for net in domain_information['networks']:
            ainformation.append('              {0: <3} {1: <7} {2: <10} {3: <8} {4: <18}  {5: <12} {6: <15} {7: <12}'.format(
                domain_information['networks'].index(net),
                net['type'],
                net['source'],
                net['model'],
                net['mac'],
                '/'.join([str(format_bytes(net['rd_bytes'])), str(format_bytes(net['wr_bytes']))]),
                '/'.join([str(format_metric(net['rd_packets'])), str(format_metric(net['wr_packets']))]),
                '/'.join([str(format_metric(net['rd_errors'])), str(format_metric(net['wr_errors']))]),
            ))
        # Controller list
        ainformation.append('')
        ainformation.append('{}Controllers:{}  {}ID  Type           Model{}'.format(ansiprint.purple(), ansiprint.end(), ansiprint.bold(), ansiprint.end()))
        for controller in domain_information['controllers']:
            ainformation.append('              {0: <3} {1: <14} {2: <8}'.format(domain_information['controllers'].index(controller), controller['type'], controller['model']))

    # Join it all together
    ainformation.append('')
    return '\n'.join(ainformation)


def format_list(config, vm_list, raw):
    # Handle single-element lists
    if not isinstance(vm_list, list):
        vm_list = [vm_list]

    # Function to strip the "br" off of nets and return a nicer list
    def getNiceNetID(domain_information):
        # Network list
        net_list = []
        for net in domain_information['networks']:
            # Split out just the numerical (VNI) part of the brXXXX name
            net_vnis = re.findall(r'\d+', net['source'])
            if net_vnis:
                net_vni = net_vnis[0]
            else:
                net_vni = re.sub('br', '', net['source'])
            net_list.append(net_vni)
        return net_list

    # Handle raw mode since it just lists the names
    if raw:
        ainformation = list()
        for vm in sorted(item['name'] for item in vm_list):
            ainformation.append(vm)
        return '\n'.join(ainformation)

    vm_list_output = []

    # Determine optimal column widths
    # Dynamic columns: node_name, node, migrated
    vm_name_length = 5
    vm_uuid_length = 37
    vm_state_length = 6
    vm_nets_length = 9
    vm_ram_length = 8
    vm_vcpu_length = 6
    vm_node_length = 8
    vm_migrated_length = 10
    for domain_information in vm_list:
        net_list = getNiceNetID(domain_information)
        # vm_name column
        _vm_name_length = len(domain_information['name']) + 1
        if _vm_name_length > vm_name_length:
            vm_name_length = _vm_name_length
        # vm_state column
        _vm_state_length = len(domain_information['state']) + 1
        if _vm_state_length > vm_state_length:
            vm_state_length = _vm_state_length
        # vm_nets column
        _vm_nets_length = len(','.join(net_list)) + 1
        if _vm_nets_length > vm_nets_length:
            vm_nets_length = _vm_nets_length
        # vm_node column
        _vm_node_length = len(domain_information['node']) + 1
        if _vm_node_length > vm_node_length:
            vm_node_length = _vm_node_length
        # vm_migrated column
        _vm_migrated_length = len(domain_information['migrated']) + 1
        if _vm_migrated_length > vm_migrated_length:
            vm_migrated_length = _vm_migrated_length

    # Format the string (header)
    vm_list_output.append(
        '{bold}{vm_name: <{vm_name_length}} {vm_uuid: <{vm_uuid_length}} \
{vm_state_colour}{vm_state: <{vm_state_length}}{end_colour} \
{vm_networks: <{vm_nets_length}} \
{vm_memory: <{vm_ram_length}} {vm_vcpu: <{vm_vcpu_length}} \
{vm_node: <{vm_node_length}} \
{vm_migrated: <{vm_migrated_length}}{end_bold}'.format(
            vm_name_length=vm_name_length,
            vm_uuid_length=vm_uuid_length,
            vm_state_length=vm_state_length,
            vm_nets_length=vm_nets_length,
            vm_ram_length=vm_ram_length,
            vm_vcpu_length=vm_vcpu_length,
            vm_node_length=vm_node_length,
            vm_migrated_length=vm_migrated_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            vm_state_colour='',
            end_colour='',
            vm_name='Name',
            vm_uuid='UUID',
            vm_state='State',
            vm_networks='Networks',
            vm_memory='RAM (M)',
            vm_vcpu='vCPUs',
            vm_node='Node',
            vm_migrated='Migrated'
        )
    )

    # Keep track of nets we found to be valid to cut down on duplicate API hits
    valid_net_list = []
    # Format the string (elements)
    for domain_information in vm_list:
        if domain_information['state'] == 'start':
            vm_state_colour = ansiprint.green()
        elif domain_information['state'] == 'restart':
            vm_state_colour = ansiprint.yellow()
        elif domain_information['state'] == 'shutdown':
            vm_state_colour = ansiprint.yellow()
        elif domain_information['state'] == 'stop':
            vm_state_colour = ansiprint.red()
        elif domain_information['state'] == 'fail':
            vm_state_colour = ansiprint.red()
        else:
            vm_state_colour = ansiprint.blue()

        # Handle colouring for an invalid network config
        raw_net_list = getNiceNetID(domain_information)
        net_list = []
        vm_net_colour = ''
        for net_vni in raw_net_list:
            if net_vni not in valid_net_list:
                response = call_api(config, 'get', '/network/{net}'.format(net=net_vni))
                if response.status_code != 200 and net_vni not in ['cluster', 'storage', 'upstream']:
                    vm_net_colour = ansiprint.red()
                else:
                    valid_net_list.append(net_vni)

            net_list.append(net_vni)

        vm_list_output.append(
            '{bold}{vm_name: <{vm_name_length}} {vm_uuid: <{vm_uuid_length}} \
{vm_state_colour}{vm_state: <{vm_state_length}}{end_colour} \
{vm_net_colour}{vm_networks: <{vm_nets_length}}{end_colour} \
{vm_memory: <{vm_ram_length}} {vm_vcpu: <{vm_vcpu_length}} \
{vm_node: <{vm_node_length}} \
{vm_migrated: <{vm_migrated_length}}{end_bold}'.format(
                vm_name_length=vm_name_length,
                vm_uuid_length=vm_uuid_length,
                vm_state_length=vm_state_length,
                vm_nets_length=vm_nets_length,
                vm_ram_length=vm_ram_length,
                vm_vcpu_length=vm_vcpu_length,
                vm_node_length=vm_node_length,
                vm_migrated_length=vm_migrated_length,
                bold='',
                end_bold='',
                vm_state_colour=vm_state_colour,
                end_colour=ansiprint.end(),
                vm_name=domain_information['name'],
                vm_uuid=domain_information['uuid'],
                vm_state=domain_information['state'],
                vm_net_colour=vm_net_colour,
                vm_networks=','.join(net_list),
                vm_memory=domain_information['memory'],
                vm_vcpu=domain_information['vcpu'],
                vm_node=domain_information['node'],
                vm_migrated=domain_information['migrated']
            )
        )

    return '\n'.join(sorted(vm_list_output))
