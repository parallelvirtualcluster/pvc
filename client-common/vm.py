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

import client_lib.ansiprint as ansiprint
import client_lib.zkhandler as zkhandler
import client_lib.common as common

#
# XML information parsing functions
#
def getInformationFromXML(zk_conn, uuid, long_output):
    # Obtain the contents of the XML from Zookeeper
    try:
        dstate = zk_conn.get('/domains/{}/state'.format(uuid))[0].decode('ascii')
        dnode = zk_conn.get('/domains/{}/node'.format(uuid))[0].decode('ascii')
        dlastnode = zk_conn.get('/domains/{}/lastnode'.format(uuid))[0].decode('ascii')
    except:
        return None

    if dlastnode == '':
        dlastnode = 'N/A'

    parsed_xml = common.getDomainXML(zk_conn, uuid)
    duuid, dname, ddescription, dmemory, dvcpu, dvcputopo = common.getDomainMainDetails(parsed_xml)
    dnets = common.getDomainNetworks(parsed_xml)

    if long_output == True:
        dtype, darch, dmachine, dconsole, demulator = common.getDomainExtraDetails(parsed_xml)
        dfeatures = common.getDomainCPUFeatures(parsed_xml)
        ddisks = common.getDomainDisks(parsed_xml)
        dcontrollers = common.getDomainControllers(parsed_xml)

    # Format a nice output; do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append('{}Virtual machine information:{}'.format(ansiprint.bold(), ansiprint.end()))
    ainformation.append('')
    # Basic information
    ainformation.append('{}UUID:{}               {}'.format(ansiprint.purple(), ansiprint.end(), duuid))
    ainformation.append('{}Name:{}               {}'.format(ansiprint.purple(), ansiprint.end(), dname))
    ainformation.append('{}Description:{}        {}'.format(ansiprint.purple(), ansiprint.end(), ddescription))
    ainformation.append('{}Memory (MiB):{}       {}'.format(ansiprint.purple(), ansiprint.end(), dmemory))
    ainformation.append('{}vCPUs:{}              {}'.format(ansiprint.purple(), ansiprint.end(), dvcpu))
    ainformation.append('{}Topology (S/C/T):{}   {}'.format(ansiprint.purple(), ansiprint.end(), dvcputopo))

    if long_output == True:
        # Virtualization information
        ainformation.append('')
        ainformation.append('{}Emulator:{}           {}'.format(ansiprint.purple(), ansiprint.end(), demulator))
        ainformation.append('{}Type:{}               {}'.format(ansiprint.purple(), ansiprint.end(), dtype))
        ainformation.append('{}Arch:{}               {}'.format(ansiprint.purple(), ansiprint.end(), darch))
        ainformation.append('{}Machine:{}            {}'.format(ansiprint.purple(), ansiprint.end(), dmachine))
        ainformation.append('{}Features:{}           {}'.format(ansiprint.purple(), ansiprint.end(), ' '.join(dfeatures)))

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
    ainformation.append('{}State:{}              {}{}{}'.format(ansiprint.purple(), ansiprint.end(), dstate_colour[dstate], dstate, ansiprint.end()))
    ainformation.append('{}Current Node:{}       {}'.format(ansiprint.purple(), ansiprint.end(), dnode))
    ainformation.append('{}Previous Node:{}      {}'.format(ansiprint.purple(), ansiprint.end(), dlastnode))

    # Network list
    net_list = []
    for net in dnets:
        # Split out just the numerical (VNI) part of the brXXXX name
        net_vni = re.findall(r'\d+', net['source'])[0]
        net_exists = zkhandler.exists(zk_conn, '/networks/{}'.format(net_vni))
        if not net_exists:
            net_list.append(ansiprint.red() + net_vni + ansiprint.end() + ' [invalid]')
        else:
            net_list.append(net_vni)
    ainformation.append('')
    ainformation.append('{}Networks:{}           {}'.format(ansiprint.purple(), ansiprint.end(), ', '.join(net_list)))

    if long_output == True:
        # Disk list
        ainformation.append('')
        name_length = 0
        for disk in ddisks:
            _name_length = len(disk['name']) + 1
            if _name_length > name_length:
                name_length = _name_length
        ainformation.append('{0}Disks:{1}        {2}ID  Type  {3: <{width}} Dev  Bus{4}'.format(ansiprint.purple(), ansiprint.end(), ansiprint.bold(), 'Name', ansiprint.end(), width=name_length))
        for disk in ddisks:
            ainformation.append('              {0: <3} {1: <5} {2: <{width}} {3: <4} {4: <5}'.format(ddisks.index(disk), disk['type'], disk['name'], disk['dev'], disk['bus'], width=name_length))
        ainformation.append('')
        ainformation.append('{}Interfaces:{}   {}ID  Type     Source     Model    MAC{}'.format(ansiprint.purple(), ansiprint.end(), ansiprint.bold(), ansiprint.end()))
        for net in dnets:
            ainformation.append('              {0: <3} {1: <8} {2: <10} {3: <8} {4}'.format(dnets.index(net), net['type'], net['source'], net['model'], net['mac']))
        # Controller list
        ainformation.append('')
        ainformation.append('{}Controllers:{}  {}ID  Type           Model{}'.format(ansiprint.purple(), ansiprint.end(), ansiprint.bold(), ansiprint.end()))
        for controller in dcontrollers:
            ainformation.append('              {0: <3} {1: <14} {2: <8}'.format(dcontrollers.index(controller), controller['type'], controller['model']))

    # Join it all together
    information = '\n'.join(ainformation)
    return information


#
# Cluster search functions
#
def getClusterDomainList(zk_conn):
    # Get a list of UUIDs by listing the children of /domains
    uuid_list = zk_conn.get_children('/domains')
    name_list = []
    # For each UUID, get the corresponding name from the data
    for uuid in uuid_list:
        name_list.append(zk_conn.get('/domains/%s' % uuid)[0].decode('ascii'))
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
    # Validate and obtain alternate passed value
    if common.validateUUID(domain):
        dom_name = searchClusterByUUID(zk_conn, domain)
        dom_uuid = searchClusterByName(zk_conn, dom_name)
    else:
        dom_uuid = searchClusterByName(zk_conn, domain)
        dom_name = searchClusterByUUID(zk_conn, dom_uuid)

    return dom_uuid

def getDomainName(zk_conn, domain):
    # Validate and obtain alternate passed value
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
def define_vm(zk_conn, config_data, target_node, selector):
    # Parse the XML data
    parsed_xml = lxml.objectify.fromstring(config_data)
    dom_uuid = parsed_xml.uuid.text
    dom_name = parsed_xml.name.text
    click.echo('Adding new VM with Name "{}" and UUID "{}" to database.'.format(dom_name, dom_uuid))

    if target_node == None:
        target_node = common.findTargetNode(zk_conn, selector, dom_uuid)

    # Verify node is valid
    common.verifyNode(zk_conn, target_node)

    # Add the new domain to Zookeeper
    transaction = zk_conn.transaction()
    transaction.create('/domains/{}'.format(dom_uuid), dom_name.encode('ascii'))
    transaction.create('/domains/{}/state'.format(dom_uuid), 'stop'.encode('ascii'))
    transaction.create('/domains/{}/node'.format(dom_uuid), target_node.encode('ascii'))
    transaction.create('/domains/{}/lastnode'.format(dom_uuid), ''.encode('ascii'))
    transaction.create('/domains/{}/failedreason'.format(dom_uuid), ''.encode('ascii'))
    transaction.create('/domains/{}/xml'.format(dom_uuid), config_data.encode('ascii'))
    results = transaction.commit()

    return True, ''

def modify_vm(zk_conn, domain, restart, new_vm_config):
    dom_uuid = getDomainUUID(zk_conn, domain)
    if dom_uuid == None:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)
    dom_name = getDomainName(zk_conn, domain)

    # Add the modified config to Zookeeper
    transaction = zk_conn.transaction()
    transaction.set_data('/domains/{}'.format(dom_uuid), dom_name.encode('ascii'))
    transaction.set_data('/domains/{}/xml'.format(dom_uuid), new_vm_config.encode('ascii'))
    if restart == True:
        transaction.set_data('/domains/{}/state'.format(dom_uuid), 'restart'.encode('ascii'))
    results = transaction.commit()

    return True, ''

def undefine_vm(zk_conn, domain):
    # Validate and obtain alternate passed value
    dom_uuid = getDomainUUID(zk_conn, domain)
    if dom_uuid == None:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Shut down the VM
    try:
        current_vm_state = zk_conn.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
        if current_vm_state != 'stop':
            click.echo('Forcibly stopping VM "{}".'.format(dom_uuid))
            # Set the domain into stop mode
            transaction = zk_conn.transaction()
            transaction.set_data('/domains/{}/state'.format(dom_uuid), 'stop'.encode('ascii'))
            transaction.commit()

            # Wait for 3 seconds to allow state to flow to all nodes
            click.echo('Waiting for cluster to update.')
            time.sleep(1)
    except:
        pass

    # Gracefully terminate the class instances
    try:
        click.echo('Deleting VM "{}" from nodes.'.format(dom_uuid))
        zk_conn.set('/domains/{}/state'.format(dom_uuid), 'delete'.encode('ascii'))
        time.sleep(5)
    except:
        pass

    # Delete the configurations
    try:
        click.echo('Undefining VM "{}".'.format(dom_uuid))
        zk_conn.delete('/domains/{}'.format(dom_uuid), recursive=True)
    except:
        pass

    return True, ''

def start_vm(zk_conn, domain):
    # Validate and obtain alternate passed value
    dom_uuid = getDomainUUID(zk_conn, domain)
    if dom_uuid == None:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Set the VM to start
    click.echo('Starting VM "{}".'.format(dom_uuid))
    zk_conn.set('/domains/%s/state' % dom_uuid, 'start'.encode('ascii'))

    return True, ''

def restart_vm(zk_conn, domain):
    # Validate and obtain alternate passed value
    dom_uuid = getDomainUUID(zk_conn, domain)
    if dom_uuid == None:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zk_conn.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_state != 'start':
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: VM "{}" is not in "start" state!'.format(dom_uuid)

    # Set the VM to start
    click.echo('Restarting VM "{}".'.format(dom_uuid))
    zk_conn.set('/domains/%s/state' % dom_uuid, 'restart'.encode('ascii'))

    return True, ''

def shutdown_vm(zk_conn, domain):
    # Validate and obtain alternate passed value
    dom_uuid = getDomainUUID(zk_conn, domain)
    if dom_uuid == None:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zk_conn.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_state != 'start':
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: VM "{}" is not in "start" state!'.format(dom_uuid)

    # Set the VM to shutdown
    click.echo('Shutting down VM "{}".'.format(dom_uuid))
    zk_conn.set('/domains/%s/state' % dom_uuid, 'shutdown'.encode('ascii'))

    return True, ''

def stop_vm(zk_conn, domain):
    # Validate and obtain alternate passed value
    dom_uuid = getDomainUUID(zk_conn, domain)
    if dom_uuid == None:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zk_conn.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_state != 'start':
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: VM "{}" is not in "start" state!'.format(dom_uuid)

    # Set the VM to start
    click.echo('Forcibly stopping VM "{}".'.format(dom_uuid))
    zk_conn.set('/domains/%s/state' % dom_uuid, 'stop'.encode('ascii'))

    return True, ''

def move_vm(zk_conn, domain, target_node, selector):
    # Validate and obtain alternate passed value
    dom_uuid = getDomainUUID(zk_conn, domain)
    if dom_uuid == None:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    current_node = zk_conn.get('/domains/{}/node'.format(dom_uuid))[0].decode('ascii')

    if target_node == None:
        target_node = common.findTargetNode(zk_conn, selector, dom_uuid)
    else:
        if target_node == current_node:
            common.stopZKConnection(zk_conn)
            return False, 'ERROR: VM "{}" is already running on node "{}".'.format(dom_uuid, current_node)

        # Verify node is valid
        common.verifyNode(zk_conn, target_node)

    current_vm_state = zk_conn.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_vm_state == 'start':
        click.echo('Permanently migrating VM "{}" to node "{}".'.format(dom_uuid, target_node))
        transaction = zk_conn.transaction()
        transaction.set_data('/domains/{}/state'.format(dom_uuid), 'migrate'.encode('ascii'))
        transaction.set_data('/domains/{}/node'.format(dom_uuid), target_node.encode('ascii'))
        transaction.set_data('/domains/{}/lastnode'.format(dom_uuid), ''.encode('ascii'))
        transaction.commit()
    else:
        click.echo('Permanently moving VM "{}" to node "{}".'.format(dom_uuid, target_node))
        transaction = zk_conn.transaction()
        transaction.set_data('/domains/{}/node'.format(dom_uuid), target_node.encode('ascii'))
        transaction.set_data('/domains/{}/lastnode'.format(dom_uuid), ''.encode('ascii'))
        transaction.commit()

    return True, ''

def migrate_vm(zk_conn, domain, target_node, selector, force_migrate):
    # Validate and obtain alternate passed value
    dom_uuid = getDomainUUID(zk_conn, domain)
    if dom_uuid == None:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zk_conn.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_state != 'start':
        target_state = 'start'
    else:
        target_state = 'migrate'

    current_node = zk_conn.get('/domains/{}/node'.format(dom_uuid))[0].decode('ascii')
    last_node = zk_conn.get('/domains/{}/lastnode'.format(dom_uuid))[0].decode('ascii')

    if last_node != '' and force_migrate != True:
        click.echo('ERROR: VM "{}" has been previously migrated.'.format(dom_uuid))
        click.echo('> Last node: {}'.format(last_node))
        click.echo('> Current node: {}'.format(current_node))
        click.echo('Run `vm unmigrate` to restore the VM to its previous node, or use `--force` to override this check.')
        common.stopZKConnection(zk_conn)
        return False, ''

    if target_node == None:
        target_node = common.findTargetNode(zk_conn, selector, dom_uuid)
    else:
        if target_node == current_node:
            common.stopZKConnection(zk_conn)
            return False, 'ERROR: VM "{}" is already running on node "{}".'.format(dom_uuid, current_node)

        # Verify node is valid
        common.verifyNode(zk_conn, target_node)

    click.echo('Migrating VM "{}" to node "{}".'.format(dom_uuid, target_node))
    transaction = zk_conn.transaction()
    transaction.set_data('/domains/{}/state'.format(dom_uuid), target_state.encode('ascii'))
    transaction.set_data('/domains/{}/node'.format(dom_uuid), target_node.encode('ascii'))
    transaction.set_data('/domains/{}/lastnode'.format(dom_uuid), current_node.encode('ascii'))
    transaction.commit()

    return True, ''

def unmigrate_vm(zk_conn, domain):
    # Validate and obtain alternate passed value
    dom_uuid = getDomainUUID(zk_conn, domain)
    if dom_uuid == None:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zk_conn.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_state != 'start':
        target_state = 'start'
    else:
        target_state = 'migrate'

    target_node = zk_conn.get('/domains/{}/lastnode'.format(dom_uuid))[0].decode('ascii')

    if target_node == '':
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: VM "{}" has not been previously migrated.'.format(dom_uuid)

    click.echo('Unmigrating VM "{}" back to node "{}".'.format(dom_uuid, target_node))
    transaction = zk_conn.transaction()
    transaction.set_data('/domains/{}/state'.format(dom_uuid), target_state.encode('ascii'))
    transaction.set_data('/domains/{}/node'.format(dom_uuid), target_node.encode('ascii'))
    transaction.set_data('/domains/{}/lastnode'.format(dom_uuid), ''.encode('ascii'))
    transaction.commit()

    return True, ''

def get_info(zk_conn, domain, long_output):
    # Validate and obtain alternate passed value
    dom_uuid = getDomainUUID(zk_conn, domain)
    if dom_uuid == None:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Gather information from XML config and print it
    information = getInformationFromXML(zk_conn, dom_uuid, long_output)
    click.echo(information)

    # Get a failure reason if applicable
    failedreason = zk_conn.get('/domains/{}/failedreason'.format(dom_uuid))[0].decode('ascii')
    if failedreason != '':
        click.echo('')
        click.echo('{}Failure reason:{}     {}'.format(ansiprint.purple(), ansiprint.end(), failedreason))

    click.echo('')

    return True, ''

def get_list(zk_conn, node, limit):
    if node != None:
        # Verify node is valid
        common.verifyNode(zk_conn, node)

    full_vm_list = zk_conn.get_children('/domains')
    vm_list = []
    vm_list_output = []

    vm_node = {}
    vm_state = {}
    vm_migrated = {}
    vm_uuid = {}
    vm_name = {}
    vm_description = {}
    vm_memory = {}
    vm_vcpu = {}
    vm_nets = {}

    # If we're limited, remove other nodes' VMs
    for vm in full_vm_list:

        # Check we don't match the limit
        name = zkhandler.readdata(zk_conn, '/domains/{}'.format(vm))
        vm_node[vm] = zkhandler.readdata(zk_conn, '/domains/{}/node'.format(vm))
        if limit != None:
            try:
                # Implcitly assume fuzzy limits
                if re.match('\^.*', limit) == None:
                    limit = '.*' + limit
                if re.match('.*\$', limit) == None:
                    limit = limit + '.*'

                if re.match(limit, vm) != None:
                    if node == None:
                        vm_list.append(vm)
                    else:
                        if vm_node[vm] == node:
                            vm_list.append(vm)

                if re.match(limit, name) != None:
                    if node == None:
                        vm_list.append(vm)
                    else:
                        if vm_node[vm] == node:
                            vm_list.append(vm)
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            # Check node to avoid unneeded ZK calls
            if node == None:
                vm_list.append(vm)
            else:
                if vm_node[vm] == node:
                    vm_list.append(vm)

    # Gather information for printing
    for vm in vm_list:
        vm_state[vm] = zk_conn.get('/domains/{}/state'.format(vm))[0].decode('ascii')
        vm_lastnode = zk_conn.get('/domains/{}/lastnode'.format(vm))[0].decode('ascii')
        if vm_lastnode != '':
            vm_migrated[vm] = 'from {}'.format(vm_lastnode)
        else:
            vm_migrated[vm] = 'no'

        try:
            vm_xml = common.getDomainXML(zk_conn, vm)
            vm_uuid[vm], vm_name[vm], vm_description[vm], vm_memory[vm], vm_vcpu[vm], vm_vcputopo = common.getDomainMainDetails(vm_xml)
            dnets = common.getDomainNetworks(vm_xml)
            vm_nets[vm] = []
            for net in dnets:
                # Split out just the numerical (VNI) part of the brXXXX name
                net_vni = re.findall(r'\d+', net['source'])[0]
                vm_nets[vm].append(net_vni)
        except AttributeError:
            click.echo('Error: Domain {} does not exist.'.format(domain))

    # Determine optimal column widths
    # Dynamic columns: node_name, node, migrated
    vm_name_length = 10
    vm_node_length = 8
    vm_nets_length = 9
    vm_migrated_length = 10
    for vm in vm_list:
        # vm_name column
        _vm_name_length = len(vm_name[vm]) + 1
        if _vm_name_length > vm_name_length:
            vm_name_length = _vm_name_length
        # vm_node column
        _vm_node_length = len(vm_node[vm]) + 1
        if _vm_node_length > vm_node_length:
            vm_node_length = _vm_node_length
        # vm_nets column
        # Strip off any ANSII chars
        _vm_nets_length = len(','.join(vm_nets[vm])) + 1
        if _vm_nets_length > vm_nets_length:
            vm_nets_length = _vm_nets_length
        # vm_migrated column
        _vm_migrated_length = len(vm_migrated[vm]) + 1
        if _vm_migrated_length > vm_migrated_length:
            vm_migrated_length = _vm_migrated_length

    # Format the string (header)
    vm_list_output.append(
        '{bold}{vm_name: <{vm_name_length}} {vm_uuid: <37} \
{vm_state_colour}{vm_state: <8}{end_colour} \
{vm_networks: <{vm_nets_length}} \
{vm_memory: <10} {vm_vcpu: <6} \
{vm_node: <{vm_node_length}} \
{vm_migrated: <{vm_migrated_length}}{end_bold}'.format(
            vm_name_length=vm_name_length,
            vm_node_length=vm_node_length,
            vm_nets_length=vm_nets_length,
            vm_migrated_length=vm_migrated_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            vm_state_colour='',
            end_colour='',
            vm_name='Name',
            vm_uuid='UUID',
            vm_state='State',
            vm_networks='Networks',
            vm_memory='RAM (MiB)',
            vm_vcpu='vCPUs',
            vm_node='Node',
            vm_migrated='Migrated'
        )
    )
            
    # Format the string (elements)
    for vm in vm_list:
        if vm_state[vm] == 'start':
            vm_state_colour = ansiprint.green()
        elif vm_state[vm] == 'restart':
            vm_state_colour = ansiprint.yellow()
        elif vm_state[vm] == 'shutdown':
            vm_state_colour = ansiprint.yellow()
        elif vm_state[vm] == 'stop':
            vm_state_colour = ansiprint.red()
        elif vm_state[vm] == 'failed':
            vm_state_colour = ansiprint.red()
        else:
            vm_state_colour = ansiprint.blue()

        # Handle colouring for an invalid network config
        net_list = []
        vm_nets_colour = ansiprint.end()
        for net in vm_nets[vm]:
            net_exists = zkhandler.exists(zk_conn, '/networks/{}'.format(net))
            net_list.append(net)
            if not net_exists:
                vm_nets_colour = ansiprint.red()
        vm_nets[vm] = ','.join(net_list)

        vm_list_output.append(
            '{bold}{vm_name: <{vm_name_length}} {vm_uuid: <37} \
{vm_state_colour}{vm_state: <8}{end_colour} \
{vm_nets_colour}{vm_networks: <{vm_nets_length}}{end_colour} \
{vm_memory: <10} {vm_vcpu: <6} \
{vm_node: <{vm_node_length}} \
{vm_migrated: <{vm_migrated_length}}{end_bold}'.format(
                vm_name_length=vm_name_length,
                vm_node_length=vm_node_length,
                vm_nets_length=vm_nets_length,
                vm_migrated_length=vm_migrated_length,
                bold='',
                end_bold='',
                vm_state_colour=vm_state_colour,
                vm_nets_colour=vm_nets_colour,
                end_colour=ansiprint.end(),
                vm_name=vm_name[vm],
                vm_uuid=vm_uuid[vm],
                vm_state=vm_state[vm],
                vm_networks=vm_nets[vm],
                vm_memory=vm_memory[vm],
                vm_vcpu=vm_vcpu[vm],
                vm_node=vm_node[vm],
                vm_migrated=vm_migrated[vm]
            )
        )

    click.echo('\n'.join(sorted(vm_list_output)))

    return True, ''
