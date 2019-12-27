#!/usr/bin/env python3

# vm.py - PVC CLI client function library, VM fuctions
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

import time
import re
import subprocess
import click
import requests

from collections import deque

import cli_lib.ansiprint as ansiprint
import cli_lib.ceph as ceph

def get_request_uri(config, endpoint):
    """
    Return the fully-formed URI for {endpoint}
    """
    uri = '{}://{}{}{}'.format(
        config['api_scheme'],
        config['api_host'],
        config['api_prefix'],
        endpoint
    )
    return uri

#
# Primary functions
#
def vm_info(config, vm):
    """
    Get information about VM

    API endpoint: GET /api/v1/vm/{vm}
    API arguments:
    API schema: {json_data_object}
    """
    request_uri = get_request_uri(config, '/vm/{vm}'.format(vm=vm))
    response = requests.get(
        request_uri
    )

    if config['debug']:
        print('API endpoint: POST {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']

def vm_list(config, limit, target_node, target_state):
    """
    Get list information about nodes (limited by {limit}, {target_node}, or {target_state})

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

    request_uri = get_request_uri(config, '/vm')
    response = requests.get(
        request_uri,
        params=params
    )

    if config['debug']:
        print('API endpoint: POST {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']

def vm_define(config, xml, node, node_limit, node_selector, node_autostart):
    """
    Define a new VM on the cluster

    API endpoint: POST /vm
    API arguments: xml={xml}, node={node}, limit={node_limit}, selector={node_selector}, autostart={node_autostart}
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/vm')
    response = requests.post(
        request_uri,
        params={
            'xml': xml,
            'node': node,
            'limit': node_limit,
            'selector': node_selector,
            'autostart': node_autostart
        }
    )

    if config['debug']:
        print('API endpoint: POST {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def vm_modify(config, vm, xml, restart):
    """
    Modify the configuration of VM

    API endpoint: POST /vm/{vm}
    API arguments: xml={xml}, restart={restart}
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/vm/{vm}'.format(vm=vm))
    response = requests.post(
        request_uri,
        params={
            'xml': xml,
            'restart': restart
        }
    )

    if config['debug']:
        print('API endpoint: POST {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def vm_metadata(config, vm, node_limit, node_selector, node_autostart):
    """
    Modify PVC metadata of a VM

    API endpoint: GET /vm/{vm}/meta,  POST /vm/{vm}/meta
    API arguments: limit={node_limit}, selector={node_selector}, autostart={node_autostart}
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/vm/{vm}/meta'.format(vm=vm))

    # Get the existing metadata so we can perform a fully dynamic update
    response = requests.get(
        request_uri
    )

    if config['debug']:
        print('API endpoint: GET {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    metadata = response.json()

    # Update any params that we've sent
    if node_limit is not None:
        metadata['node_limit'] = node_limit
    else:
        # Collapse the existing list back down to a CSV
        metadata['node_limit'] = ','.join(metadata['node_limit'])

    if node_selector is not None:
        metadata['node_selector'] = node_selector

    if node_autostart is not None:
        metadata['node_autostart'] = node_autostart

    # Write the new metadata
    print(metadata['node_limit'])
    response = requests.post(
        request_uri,
        params={
            'limit': metadata['node_limit'],
            'selector': metadata['node_selector'],
            'autostart': metadata['node_autostart']
        }
    )

    if config['debug']:
        print('API endpoint: POST {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def vm_remove(config, vm, delete_disks=False):
    """
    Remove a VM

    API endpoint: DELETE /vm/{vm}
    API arguments: delete_disks={delete_disks}
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/vm/{vm}'.format(vm=vm))
    response = requests.delete(
        request_uri,
        params={
            'delete_disks': delete_disks
        }
    )

    if config['debug']:
        print('API endpoint: DELETE {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def vm_state(config, vm, target_state):
    """
    Modify the current state of VM

    API endpoint: POST /vm/{vm}/state
    API arguments: state={state}
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/vm/{vm}/state'.format(vm=vm))
    response = requests.post(
        request_uri,
        params={
            'state': target_state,
        }
    )

    if config['debug']:
        print('API endpoint: POST {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def vm_node(config, vm, target_node, action, force=False):
    """
    Modify the current node of VM via {action}

    API endpoint: POST /vm/{vm}/node
    API arguments: node={target_node}, action={action}, force={force}
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/vm/{vm}/node'.format(vm=vm))
    response = requests.post(
        request_uri,
        params={
            'node': target_node,
            'action': action,
            'force': force
        }
    )

    if config['debug']:
        print('API endpoint: POST {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def vm_locks(config, vm):
    """
    Flush RBD locks of (stopped) VM

    API endpoint: POST /vm/{vm}/locks
    API arguments:
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/vm/{vm}/locks'.format(vm=vm))
    response = requests.post(
        request_uri
    )

    if config['debug']:
        print('API endpoint: POST {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def view_console_log(config, vm, lines=100):
    """
    Return console log lines from the API and display them in a pager

    API endpoint: GET /vm/{vm}/console
    API arguments: lines={lines}
    API schema: {"name":"{vmname}","data":"{console_log}"}
    """
    request_uri = get_request_uri(config, '/vm/{vm}/console'.format(vm=vm))
    response = requests.get(
        request_uri,
        params={'lines': lines}
    )

    if config['debug']:
        print('API endpoint: GET {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    console_log = response.json()['data']

    # Shrink the log buffer to length lines
    shrunk_log = console_log.split('\n')[-lines:]
    loglines = '\n'.join(shrunk_log)

    # Show it in the pager (less)
    try:
        pager = subprocess.Popen(['less', '-R'], stdin=subprocess.PIPE)
        pager.communicate(input=loglines.encode('utf8'))
    except FileNotFoundError:
        click.echo("Error: `less` pager not found, dumping log ({} lines) to stdout".format(lines))
        return True, loglines

    return True, ''

def follow_console_log(config, vm, lines=10):
    """
    Return and follow console log lines from the API

    API endpoint: GET /vm/{vm}/console
    API arguments: lines={lines}
    API schema: {"name":"{vmname}","data":"{console_log}"}
    """
    request_uri = get_request_uri(config, '/vm/{vm}/console'.format(vm=vm))
    response = requests.get(
        request_uri,
        params={'lines': lines}
    )

    if config['debug']:
        print('API endpoint: GET {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    console_log = response.json()['data']

    # Shrink the log buffer to length lines
    shrunk_log = console_log.split('\n')[-lines:]
    loglines = '\n'.join(shrunk_log)

    # Print the initial data and begin following
    print(loglines, end='')

    while True:
        # Grab the next line set
        # Get the (initial) data from the API
        response = requests.get(
            '{}://{}{}{}'.format(
                config['api_scheme'],
                config['api_host'],
                config['api_prefix'],
                '/vm/{}/console'.format(vm)
            ),
            params={'lines': lines}
        )
    
        if config['debug']:
            print(
                'Response code: {}'.format(
                    response.status_code
                )
            )
            print(
                'Response headers: {}'.format(
                    response.headers
                )
            )
    
        new_console_log = response.json()['data']
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

    if long_output == True:
        # Virtualization information
        ainformation.append('')
        ainformation.append('{}Emulator:{}           {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['emulator']))
        ainformation.append('{}Type:{}               {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['type']))
        ainformation.append('{}Arch:{}               {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['arch']))
        ainformation.append('{}Machine:{}            {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['machine']))
        ainformation.append('{}Features:{}           {}'.format(ansiprint.purple(), ansiprint.end(), ' '.join(domain_information['features'])))

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
        'unmigrate': ansiprint.blue()
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

    if not domain_information['node_selector']:
        formatted_node_selector = "False"
    else:
        formatted_node_selector = domain_information['node_selector']

    if not domain_information['node_limit']:
        formatted_node_limit = "False"
    else:
        formatted_node_limit = ', '.join(domain_information['node_limit'])

    if not domain_information['node_autostart']:
        formatted_node_autostart = "False"
    else:
        formatted_node_autostart = domain_information['node_autostart']

    ainformation.append('{}Migration selector:{} {}'.format(ansiprint.purple(), ansiprint.end(), formatted_node_selector))
    ainformation.append('{}Node limit:{}         {}'.format(ansiprint.purple(), ansiprint.end(), formatted_node_limit))
    ainformation.append('{}Autostart:{}          {}'.format(ansiprint.purple(), ansiprint.end(), formatted_node_autostart))

    # Network list
    net_list = []
    for net in domain_information['networks']:
        # Split out just the numerical (VNI) part of the brXXXX name
        net_vnis = re.findall(r'\d+', net['source'])
        if net_vnis:
            net_vni = net_vnis[0]
        else:
            net_vni = re.sub('br', '', net['source'])

        request_uri = get_request_uri(config, '/network/{net}'.format(net=net_vni))
        response = requests.get(
            request_uri
        )
        if response.status_code != 200 and net_vni != 'cluster':
            net_list.append(ansiprint.red() + net_vni + ansiprint.end() + ' [invalid]')
        else:
            net_list.append(net_vni)

    ainformation.append('')
    ainformation.append('{}Networks:{}           {}'.format(ansiprint.purple(), ansiprint.end(), ', '.join(net_list)))

    if long_output == True:
        # Disk list
        ainformation.append('')
        name_length = 0
        for disk in domain_information['disks']:
            _name_length = len(disk['name']) + 1
            if _name_length > name_length:
                name_length = _name_length
        ainformation.append('{0}Disks:{1}        {2}ID  Type  {3: <{width}} Dev  Bus{4}'.format(ansiprint.purple(), ansiprint.end(), ansiprint.bold(), 'Name', ansiprint.end(), width=name_length))
        for disk in domain_information['disks']:
            ainformation.append('              {0: <3} {1: <5} {2: <{width}} {3: <4} {4: <5}'.format(domain_information['disks'].index(disk), disk['type'], disk['name'], disk['dev'], disk['bus'], width=name_length))
        ainformation.append('')
        ainformation.append('{}Interfaces:{}   {}ID  Type     Source     Model    MAC{}'.format(ansiprint.purple(), ansiprint.end(), ansiprint.bold(), ansiprint.end()))
        for net in domain_information['networks']:
            ainformation.append('              {0: <3} {1: <8} {2: <10} {3: <8} {4}'.format(domain_information['networks'].index(net), net['type'], net['source'], net['model'], net['mac']))
        # Controller list
        ainformation.append('')
        ainformation.append('{}Controllers:{}  {}ID  Type           Model{}'.format(ansiprint.purple(), ansiprint.end(), ansiprint.bold(), ansiprint.end()))
        for controller in domain_information['controllers']:
            ainformation.append('              {0: <3} {1: <14} {2: <8}'.format(domain_information['controllers'].index(controller), controller['type'], controller['model']))

    # Join it all together
    information = '\n'.join(ainformation)
    click.echo(information)

    click.echo('')

def format_list(config, vm_list, raw):
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
        for vm in sorted(item['name'] for item in vm_list):
            click.echo(vm)
        return True, ''

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
            if not net_vni in valid_net_list:
                request_uri = get_request_uri(config, '/network/{net}'.format(net=net_vni))
                response = requests.get(
                    request_uri
                )
                if response.status_code != 200 and net_vni != 'cluster':
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

    click.echo('\n'.join(sorted(vm_list_output)))

    return True, ''
