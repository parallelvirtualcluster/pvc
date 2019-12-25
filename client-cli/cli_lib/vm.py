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

import difflib
import colorama
import click

from collections import deque

import client_lib.ansiprint as ansiprint
import client_lib.zkhandler as zkhandler
import client_lib.common as common

import client_lib.ceph as ceph

def get_console_log(zk_conn, domain, lines=1000):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get the data from ZK
    console_log = zkhandler.readdata(zk_conn, '/domains/{}/consolelog'.format(dom_uuid))

    # Shrink the log buffer to length lines
    shrunk_log = console_log.split('\n')[-lines:]
    loglines = '\n'.join(shrunk_log)

    # Show it in the pager (less)
    try:
        pager = subprocess.Popen(['less', '-R'], stdin=subprocess.PIPE)
        pager.communicate(input=loglines.encode('utf8'))
    except FileNotFoundError:
        return False, 'ERROR: The "less" pager is required to view console logs.'

    return True, ''

def follow_console_log(zk_conn, domain, lines=10):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get the initial data from ZK
    console_log = zkhandler.readdata(zk_conn, '/domains/{}/consolelog'.format(dom_uuid))

    # Shrink the log buffer to length lines
    shrunk_log = console_log.split('\n')[-lines:]
    loglines = '\n'.join(shrunk_log)

    # Print the initial data and begin following
    print(loglines, end='')

    try:
        while True:
            # Grab the next line set
            new_console_log = zkhandler.readdata(zk_conn, '/domains/{}/consolelog'.format(dom_uuid))
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
    except kazoo.exceptions.NoNodeError:
        return False, 'ERROR: VM has gone away.'
    except:
        return False, 'ERROR: Lost connection to Zookeeper node.'

    return True, ''

def format_info(zk_conn, domain_information, long_output):
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
        net_exists = zkhandler.exists(zk_conn, '/networks/{}'.format(net_vni))
        if not net_exists and net_vni != 'cluster':
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

def format_list(zk_conn, vm_list, raw):
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
            net_exists = zkhandler.exists(zk_conn, '/networks/{}'.format(net_vni))
            if not net_exists and net_vni != 'cluster':
                vm_net_colour = ansiprint.red()
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

