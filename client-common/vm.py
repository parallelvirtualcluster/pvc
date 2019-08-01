#!/usr/bin/env python3

# vm.py - PVC client function library, VM fuctions
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
import subprocess
import difflib
import colorama
import click
import lxml.objectify
import configparser
import kazoo.client

from collections import deque

import client_lib.ansiprint as ansiprint
import client_lib.zkhandler as zkhandler
import client_lib.common as common

import client_lib.ceph as ceph

#
# Cluster search functions
#
def getClusterDomainList(zk_conn):
    # Get a list of UUIDs by listing the children of /domains
    uuid_list = zkhandler.listchildren(zk_conn, '/domains')
    name_list = []
    # For each UUID, get the corresponding name from the data
    for uuid in uuid_list:
        name_list.append(zkhandler.readdata(zk_conn, '/domains/%s' % uuid))
    return uuid_list, name_list

def searchClusterByUUID(zk_conn, uuid):
    try:
        # Get the lists
        uuid_list, name_list = getClusterDomainList(zk_conn)
        # We're looking for UUID, so find that element ID
        index = uuid_list.index(uuid)
        # Get the name_list element at that index
        name = name_list[index]
    except ValueError:
        # We didn't find anything
        return None

    return name

def searchClusterByName(zk_conn, name):
    try:
        # Get the lists
        uuid_list, name_list = getClusterDomainList(zk_conn)
        # We're looking for name, so find that element ID
        index = name_list.index(name)
        # Get the uuid_list element at that index
        uuid = uuid_list[index]
    except ValueError:
        # We didn't find anything
        return None

    return uuid

def getDomainUUID(zk_conn, domain):
    # Validate that VM exists in cluster
    if common.validateUUID(domain):
        dom_name = searchClusterByUUID(zk_conn, domain)
        dom_uuid = searchClusterByName(zk_conn, dom_name)
    else:
        dom_uuid = searchClusterByName(zk_conn, domain)
        dom_name = searchClusterByUUID(zk_conn, dom_uuid)

    return dom_uuid

def getDomainName(zk_conn, domain):
    # Validate that VM exists in cluster
    if common.validateUUID(domain):
        dom_name = searchClusterByUUID(zk_conn, domain)
        dom_uuid = searchClusterByName(zk_conn, dom_name)
    else:
        dom_uuid = searchClusterByName(zk_conn, domain)
        dom_name = searchClusterByUUID(zk_conn, dom_uuid)

    return dom_name

#
# Direct functions
#
def is_migrated(zk_conn, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    last_node = zkhandler.readdata(zk_conn, '/domains/{}/lastnode'.format(dom_uuid))
    common.stopZKConnection(zk_conn)
    if last_node:
        return True
    else:
        return False

def define_vm(zk_conn, config_data, target_node, selector):
    # Parse the XML data
    try:
        parsed_xml = lxml.objectify.fromstring(config_data)
    except:
        return False, 'ERROR: Failed to parse XML data.'
    dom_uuid = parsed_xml.uuid.text
    dom_name = parsed_xml.name.text

    if not target_node:
        target_node = common.findTargetNode(zk_conn, selector, dom_uuid)
    else:
        # Verify node is valid
        valid_node = common.verifyNode(zk_conn, target_node)
        if not valid_node:
            return False, 'ERROR: Specified node "{}" is invalid.'.format(target_node)

    # Obtain the RBD disk list using the common functions
    ddisks = common.getDomainDisks(parsed_xml)
    rbd_list = []
    for disk in ddisks:
        if disk['type'] == 'rbd':
            rbd_list.append(disk['name'])

    # Add the new domain to Zookeeper
    zkhandler.writedata(zk_conn, {
        '/domains/{}'.format(dom_uuid): dom_name,
        '/domains/{}/state'.format(dom_uuid): 'stop',
        '/domains/{}/node'.format(dom_uuid): target_node,
        '/domains/{}/lastnode'.format(dom_uuid): '',
        '/domains/{}/failedreason'.format(dom_uuid): '',
        '/domains/{}/consolelog'.format(dom_uuid): '',
        '/domains/{}/rbdlist'.format(dom_uuid): ','.join(rbd_list),
        '/domains/{}/xml'.format(dom_uuid): config_data
    })

    return True, 'Added new VM with Name "{}" and UUID "{}" to database.'.format(dom_name, dom_uuid)

def modify_vm(zk_conn, domain, restart, new_vm_config):
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)
    dom_name = getDomainName(zk_conn, domain)

    # Add the modified config to Zookeeper
    zk_data = {
        '/domains/{}'.format(dom_uuid): dom_name,
        '/domains/{}/xml'.format(dom_uuid): new_vm_config
    }
    if restart == True:
        zk_data.update({'/domains/{}/state'.format(dom_uuid): 'restart'})
    zkhandler.writedata(zk_conn, zk_data)

    return True, ''

def dump_vm(zk_conn, domain):
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Gram the domain XML and dump it to stdout
    vm_xml = zkhandler.readdata(zk_conn, '/domains/{}/xml'.format(dom_uuid))

    return True, vm_xml

def purge_vm(zk_conn, domain, is_cli=False):
    """
    Helper function for both undefine and remove VM to perform the shutdown, termination,
    and configuration deletion.
    """

def undefine_vm(zk_conn, domain, is_cli=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Shut down the VM
    current_vm_state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid))
    if current_vm_state != 'stop':
        if is_cli:
            click.echo('Forcibly stopping VM "{}".'.format(domain))
        # Set the domain into stop mode
        zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'stop'})

        # Wait for 1 second to allow state to flow to all nodes
        if is_cli:
            click.echo('Waiting for cluster to update.')
        time.sleep(2)

    # Gracefully terminate the class instances
    if is_cli:
        click.echo('Deleting VM "{}" from nodes.'.format(domain))
    zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'delete'})
    time.sleep(2)

    # Delete the configurations
    if is_cli:
        click.echo('Undefining VM "{}".'.format(domain))
    zkhandler.deletekey(zk_conn, '/domains/{}'.format(dom_uuid))

    return True, 'Undefined VM "{}" from the cluster.'.format(domain)

def remove_vm(zk_conn, domain, is_cli=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    disk_list = common.getDomainDiskList(zk_conn, dom_uuid)

    # Shut down the VM
    current_vm_state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid))
    if current_vm_state != 'stop':
        if is_cli:
            click.echo('Forcibly stopping VM "{}".'.format(domain))
        # Set the domain into stop mode
        zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'stop'})

        # Wait for 1 second to allow state to flow to all nodes
        if is_cli:
            click.echo('Waiting for cluster to update.')
        time.sleep(2)

    # Gracefully terminate the class instances
    if is_cli:
        click.echo('Deleting VM "{}" from nodes.'.format(domain))
    zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'delete'})
    time.sleep(2)

    # Delete the configurations
    if is_cli:
        click.echo('Undefining VM "{}".'.format(domain))
    zkhandler.deletekey(zk_conn, '/domains/{}'.format(dom_uuid))
    time.sleep(2)

    # Remove disks
    for disk in disk_list:
        # vmpool/vmname_volume
        try:
            disk_pool, disk_name = disk.split('/')
            retcode, message = ceph.remove_volume(zk_conn, disk_pool, disk_name)
            if is_cli and message:
                click.echo('{}'.format(message))
        except ValueError:
            continue

    return True, 'Removed VM "{}" and disks from the cluster.'.format(domain)

def start_vm(zk_conn, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Set the VM to start
    zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'start'})

    return True, 'Starting VM "{}".'.format(domain)

def restart_vm(zk_conn, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid))
    if current_state != 'start':
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: VM "{}" is not in "start" state!'.format(domain)

    # Set the VM to start
    zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'restart'})

    return True, 'Restarting VM "{}".'.format(domain)

def shutdown_vm(zk_conn, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid))
    if current_state != 'start':
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: VM "{}" is not in "start" state!'.format(domain)

    # Set the VM to shutdown
    zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'shutdown'})

    return True, 'Shutting down VM "{}".'.format(domain)

def stop_vm(zk_conn, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid))

    # Set the VM to start
    zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'stop'})

    return True, 'Forcibly stopping VM "{}".'.format(domain)

def move_vm(zk_conn, domain, target_node, selector):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    current_node = zkhandler.readdata(zk_conn, '/domains/{}/node'.format(dom_uuid))

    if not target_node:
        target_node = common.findTargetNode(zk_conn, selector, dom_uuid)
    else:
        # Verify node is valid
        valid_node = common.verifyNode(zk_conn, target_node)
        if not valid_node:
            return False, 'Specified node "{}" is invalid.'.format(target_node)

        # Verify if node is current node
        if target_node == current_node:
            common.stopZKConnection(zk_conn)
            return False, 'ERROR: VM "{}" is already running on node "{}".'.format(domain, current_node)

    current_vm_state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid))
    if current_vm_state == 'start':
        zkhandler.writedata(zk_conn, {
            '/domains/{}/state'.format(dom_uuid): 'migrate',
            '/domains/{}/node'.format(dom_uuid): target_node,
            '/domains/{}/lastnode'.format(dom_uuid): ''
        })
    else:
        zkhandler.writedata(zk_conn, {
            '/domains/{}/node'.format(dom_uuid): target_node,
            '/domains/{}/lastnode'.format(dom_uuid): ''
        })

    return True, 'Permanently migrating VM "{}" to node "{}".'.format(domain, target_node)

def migrate_vm(zk_conn, domain, target_node, selector, force_migrate, is_cli=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid))
    if current_state != 'start':
        target_state = 'start'
    else:
        target_state = 'migrate'

    current_node = zkhandler.readdata(zk_conn, '/domains/{}/node'.format(dom_uuid))
    last_node = zkhandler.readdata(zk_conn, '/domains/{}/lastnode'.format(dom_uuid))

    if last_node and not force_migrate:
        if is_cli:
            click.echo('ERROR: VM "{}" has been previously migrated.'.format(domain))
            click.echo('> Last node: {}'.format(last_node))
            click.echo('> Current node: {}'.format(current_node))
            click.echo('Run `vm unmigrate` to restore the VM to its previous node, or use `--force` to override this check.')
            return False, ''
        else:
            return False, 'ERROR: VM "{}" has been previously migrated.'.format(domain)

    if not target_node:
        target_node = common.findTargetNode(zk_conn, selector, dom_uuid)
    else:
        # Verify node is valid
        valid_node = common.verifyNode(zk_conn, target_node)
        if not valid_node:
            return False, 'Specified node "{}" is invalid.'.format(target_node)

        # Verify if node is current node
        if target_node == current_node:
            common.stopZKConnection(zk_conn)
            return False, 'ERROR: VM "{}" is already running on node "{}".'.format(domain, current_node)

    # Don't overwrite an existing last_node when using force_migrate
    if last_node and force_migrate:
        current_node = last_node

    zkhandler.writedata(zk_conn, {
        '/domains/{}/state'.format(dom_uuid): 'migrate',
        '/domains/{}/node'.format(dom_uuid): target_node,
        '/domains/{}/lastnode'.format(dom_uuid): current_node
    })

    return True, 'Migrating VM "{}" to node "{}".'.format(domain, target_node)

def unmigrate_vm(zk_conn, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid))
    if current_state != 'start':
        # If the current state isn't start, preserve it; we're not doing live migration
        target_state = current_state
    else:
        target_state = 'migrate'

    target_node = zkhandler.readdata(zk_conn, '/domains/{}/lastnode'.format(dom_uuid))

    if target_node == '':
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: VM "{}" has not been previously migrated.'.format(domain)

    zkhandler.writedata(zk_conn, {
        '/domains/{}/state'.format(dom_uuid): target_state,
        '/domains/{}/node'.format(dom_uuid): target_node,
        '/domains/{}/lastnode'.format(dom_uuid): ''
    })

    return True, 'Unmigrating VM "{}" back to node "{}".'.format(domain, target_node)

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

    return True, ''

def get_info(zk_conn, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: No VM named "{}" is present in the cluster.'.format(domain)

    # Gather information from XML config and print it
    domain_information = common.getInformationFromXML(zk_conn, dom_uuid)
    if not domain_information:
        return False, 'ERROR: Could not get information about VM "{}".'.format(domain)

    return True, domain_information

def get_list(zk_conn, node, state, limit, is_fuzzy=True):
    if node:
        # Verify node is valid
        if not common.verifyNode(zk_conn, node):
            return False, 'Specified node "{}" is invalid.'.format(node)

    if state:
        valid_states = [ 'start', 'restart', 'shutdown', 'stop', 'failed', 'migrate', 'unmigrate' ]
        if not state in valid_states:
            return False, 'VM state "{}" is not valid.'.format(state)

    full_vm_list = zkhandler.listchildren(zk_conn, '/domains')
    vm_list = []

    # Set our limit to a sensible regex
    if limit and is_fuzzy:
        try:
            # Implcitly assume fuzzy limits
            if not re.match('\^.*', limit):
                limit = '.*' + limit
            if not re.match('.*\$', limit):
                limit = limit + '.*'
        except Exception as e:
            return False, 'Regex Error: {}'.format(e)

    # If we're limited, remove other nodes' VMs
    vm_node = {}
    vm_state = {}
    for vm in full_vm_list:
        # Check we don't match the limit
        name = zkhandler.readdata(zk_conn, '/domains/{}'.format(vm))
        vm_node[vm] = zkhandler.readdata(zk_conn, '/domains/{}/node'.format(vm))
        vm_state[vm] = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(vm))
        # Handle limiting
        if limit:
            try:
                if re.match(limit, vm):
                    if not node and not state:
                        vm_list.append(common.getInformationFromXML(zk_conn, vm))
                    else:
                        if vm_node[vm] == node or vm_state[vm] == state:
                            vm_list.append(common.getInformationFromXML(zk_conn, vm))

                if re.match(limit, name):
                    if not node and not state:
                        vm_list.append(common.getInformationFromXML(zk_conn, vm))
                    else:
                        if vm_node[vm] == node or vm_state[vm] == state:
                            vm_list.append(common.getInformationFromXML(zk_conn, vm))
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            # Check node to avoid unneeded ZK calls
            if not node and not state:
                vm_list.append(common.getInformationFromXML(zk_conn, vm))
            else:
                if vm_node[vm] == node or vm_state[vm] == state:
                    vm_list.append(common.getInformationFromXML(zk_conn, vm))

    return True, vm_list

#
# CLI-specific functions
#
def format_info(zk_conn, domain_information, long_output):
    # Format a nice output; do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append('{}Virtual machine information:{}'.format(ansiprint.bold(), ansiprint.end()))
    ainformation.append('')
    # Basic information
    ainformation.append('{}UUID:{}               {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['uuid']))
    ainformation.append('{}Name:{}               {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['name']))
    ainformation.append('{}Description:{}        {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['description']))
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
        'failed': ansiprint.red(),
        'migrate': ansiprint.blue(),
        'unmigrate': ansiprint.blue()
    }
    ainformation.append('{}State:{}              {}{}{}'.format(ansiprint.purple(), ansiprint.end(), dstate_colour[domain_information['state']], domain_information['state'], ansiprint.end()))
    ainformation.append('{}Current Node:{}       {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['node']))
    ainformation.append('{}Previous Node:{}      {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['last_node']))

    # Get a failure reason if applicable
    if domain_information['failed_reason']:
        ainformation.append('')
        ainformation.append('{}Failure reason:{}     {}'.format(ansiprint.purple(), ansiprint.end(), domain_information['failed_reason']))

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
        elif domain_information['state'] == 'failed':
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

