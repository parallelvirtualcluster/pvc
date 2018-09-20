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
import tempfile
import subprocess
import difflib
import colorama
import click
import lxml.objectify
import configparser
import kazoo.client

import lib.ansiiprint as ansiiprint
import lib.common as common

#
# XML information parsing functions
#
def getInformationFromXML(zk_conn, uuid, long_output):
    # Obtain the contents of the XML from Zookeeper
    try:
        dstate = zk_conn.get('/domains/{}/state'.format(uuid))[0].decode('ascii')
        dhypervisor = zk_conn.get('/domains/{}/hypervisor'.format(uuid))[0].decode('ascii')
        dlasthypervisor = zk_conn.get('/domains/{}/lasthypervisor'.format(uuid))[0].decode('ascii')
    except:
        return None

    if dlasthypervisor == '':
        dlasthypervisor = 'N/A'

    try:
        parsed_xml = common.getDomainXML(zk_conn, uuid)
        duuid, dname, ddescription, dmemory, dvcpu, dvcputopo = common.getDomainMainDetails(parsed_xml)
    except AttributeError:
        click.echo('Error: Domain {} does not exist.'.format(domain))

    if long_output == True:
        dtype, darch, dmachine, dconsole, demulator = common.getDomainExtraDetails(parsed_xml)
        dfeatures = common.getDomainCPUFeatures(parsed_xml)
        ddisks = common.getDomainDisks(parsed_xml)
        dnets = common.getDomainNetworks(parsed_xml)
        dcontrollers = common.getDomainControllers(parsed_xml)

    # Format a nice output; do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append('{}Virtual machine information:{}'.format(ansiiprint.bold(), ansiiprint.end()))
    ainformation.append('')
    # Basic information
    ainformation.append('{}UUID:{}               {}'.format(ansiiprint.purple(), ansiiprint.end(), duuid))
    ainformation.append('{}Name:{}               {}'.format(ansiiprint.purple(), ansiiprint.end(), dname))
    ainformation.append('{}Description:{}        {}'.format(ansiiprint.purple(), ansiiprint.end(), ddescription))
    ainformation.append('{}Memory (MiB):{}       {}'.format(ansiiprint.purple(), ansiiprint.end(), dmemory))
    ainformation.append('{}vCPUs:{}              {}'.format(ansiiprint.purple(), ansiiprint.end(), dvcpu))
    ainformation.append('{}Topology (S/C/T):{}   {}'.format(ansiiprint.purple(), ansiiprint.end(), dvcputopo))

    if long_output == True:
        # Virtualization information
        ainformation.append('')
        ainformation.append('{}Emulator:{}           {}'.format(ansiiprint.purple(), ansiiprint.end(), demulator))
        ainformation.append('{}Type:{}               {}'.format(ansiiprint.purple(), ansiiprint.end(), dtype))
        ainformation.append('{}Arch:{}               {}'.format(ansiiprint.purple(), ansiiprint.end(), darch))
        ainformation.append('{}Machine:{}            {}'.format(ansiiprint.purple(), ansiiprint.end(), dmachine))
        ainformation.append('{}Features:{}           {}'.format(ansiiprint.purple(), ansiiprint.end(), ' '.join(dfeatures)))

    # PVC cluster information
    ainformation.append('')
    dstate_colour = {
        'start': ansiiprint.green(),
        'restart': ansiiprint.yellow(),
        'shutdown': ansiiprint.yellow(),
        'stop': ansiiprint.red(),
        'failed': ansiiprint.red(),
        'migrate': ansiiprint.blue(),
        'unmigrate': ansiiprint.blue()
    }
    ainformation.append('{}State:{}              {}{}{}'.format(ansiiprint.purple(), ansiiprint.end(), dstate_colour[dstate], dstate, ansiiprint.end()))
    ainformation.append('{}Active Hypervisor:{}  {}'.format(ansiiprint.purple(), ansiiprint.end(), dhypervisor))
    ainformation.append('{}Last Hypervisor:{}    {}'.format(ansiiprint.purple(), ansiiprint.end(), dlasthypervisor))

    if long_output == True:
        # Disk list
        ainformation.append('')
        name_length = 0
        for disk in ddisks:
            _name_length = len(disk['name']) + 1
            if _name_length > name_length:
                name_length = _name_length
        ainformation.append('{0}Disks:{1}        {2}ID  Type  {3: <{width}} Dev  Bus{4}'.format(ansiiprint.purple(), ansiiprint.end(), ansiiprint.bold(), 'Name', ansiiprint.end(), width=name_length))
        for disk in ddisks:
            ainformation.append('              {0: <3} {1: <5} {2: <{width}} {3: <4} {4: <5}'.format(ddisks.index(disk), disk['type'], disk['name'], disk['dev'], disk['bus'], width=name_length))
        # Network list
        ainformation.append('')
        ainformation.append('{}Interfaces:{}   {}ID  Type     Source     Model    MAC{}'.format(ansiiprint.purple(), ansiiprint.end(), ansiiprint.bold(), ansiiprint.end()))
        for net in dnets:
            ainformation.append('              {0: <3} {1: <8} {2: <10} {3: <8} {4}'.format(dnets.index(net), net['type'], net['source'], net['model'], net['mac']))
        # Controller list
        ainformation.append('')
        ainformation.append('{}Controllers:{}  {}ID  Type           Model{}'.format(ansiiprint.purple(), ansiiprint.end(), ansiiprint.bold(), ansiiprint.end()))
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

#
# Direct functions
#
def define_vm(zk_conn, config_data, target_hypervisor, selector):
    # Parse the XML data
    parsed_xml = lxml.objectify.fromstring(data)
    dom_uuid = parsed_xml.uuid.text
    dom_name = parsed_xml.name.text
    click.echo('Adding new VM with Name "{}" and UUID "{}" to database.'.format(dom_name, dom_uuid))

    if target_hypervisor == None:
        target_hypervisor = common.findTargetHypervisor(zk_conn, selector, dom_uuid)

    # Verify node is valid
    common.verifyNode(zk_conn, target_hypervisor)

    # Add the new domain to Zookeeper
    transaction = zk_conn.transaction()
    transaction.create('/domains/{}'.format(dom_uuid), dom_name.encode('ascii'))
    transaction.create('/domains/{}/state'.format(dom_uuid), 'stop'.encode('ascii'))
    transaction.create('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
    transaction.create('/domains/{}/lasthypervisor'.format(dom_uuid), ''.encode('ascii'))
    transaction.create('/domains/{}/failedreason'.format(dom_uuid), ''.encode('ascii'))
    transaction.create('/domains/{}/xml'.format(dom_uuid), data.encode('ascii'))
    results = transaction.commit()

    return True, ''

def modify_vm(zk_conn, domain, restart):
    dom_uuid = getDomainUUID(zk_conn, domain)
    if dom_uuid == None:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

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

            # Wait for 3 seconds to allow state to flow to all hypervisors
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
        transaction = zk_conn.transaction()
        transaction.delete('/domains/{}/state'.format(dom_uuid))
        transaction.delete('/domains/{}/hypervisor'.format(dom_uuid))
        transaction.delete('/domains/{}/lasthypervisor'.format(dom_uuid))
        transaction.delete('/domains/{}/failedreason'.format(dom_uuid))
        transaction.delete('/domains/{}/xml'.format(dom_uuid))
        transaction.delete('/domains/{}'.format(dom_uuid))
        transaction.commit()
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

def move_vm(zk_conn, domain, target_hypervisor, selector):
    # Validate and obtain alternate passed value
    dom_uuid = getDomainUUID(zk_conn, domain)
    if dom_uuid == None:
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    current_hypervisor = zk_conn.get('/domains/{}/hypervisor'.format(dom_uuid))[0].decode('ascii')

    if target_hypervisor == None:
        target_hypervisor = common.findTargetHypervisor(zk_conn, selector, dom_uuid)
    else:
        if target_hypervisor == current_hypervisor:
            common.stopZKConnection(zk_conn)
            return False, 'ERROR: VM "{}" is already running on hypervisor "{}".'.format(dom_uuid, current_hypervisor)

        # Verify node is valid
        common.verifyNode(zk_conn, target_hypervisor)

    current_vm_state = zk_conn.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_vm_state == 'start':
        click.echo('Permanently migrating VM "{}" to hypervisor "{}".'.format(dom_uuid, target_hypervisor))
        transaction = zk_conn.transaction()
        transaction.set_data('/domains/{}/state'.format(dom_uuid), 'migrate'.encode('ascii'))
        transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
        transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), ''.encode('ascii'))
        transaction.commit()
    else:
        click.echo('Permanently moving VM "{}" to hypervisor "{}".'.format(dom_uuid, target_hypervisor))
        transaction = zk_conn.transaction()
        transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
        transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), ''.encode('ascii'))
        transaction.commit()

    return True, ''

def migrate_vm(zk_conn, domain, target_hypervisor, selector, force_migrate):
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

    current_hypervisor = zk_conn.get('/domains/{}/hypervisor'.format(dom_uuid))[0].decode('ascii')
    last_hypervisor = zk_conn.get('/domains/{}/lasthypervisor'.format(dom_uuid))[0].decode('ascii')

    if last_hypervisor != '' and force_migrate != True:
        click.echo('ERROR: VM "{}" has been previously migrated.'.format(dom_uuid))
        click.echo('> Last hypervisor: {}'.format(last_hypervisor))
        click.echo('> Current hypervisor: {}'.format(current_hypervisor))
        click.echo('Run `vm unmigrate` to restore the VM to its previous hypervisor, or use `--force` to override this check.')
        common.stopZKConnection(zk_conn)
        return False, ''

    if target_hypervisor == None:
        target_hypervisor = findTargetHypervisor(zk_conn, selector, dom_uuid)
    else:
        if target_hypervisor == current_hypervisor:
            common.stopZKConnection(zk_conn)
            return False, 'ERROR: VM "{}" is already running on hypervisor "{}".'.format(dom_uuid, current_hypervisor)

        # Verify node is valid
        common.verifyNode(zk_conn, target_hypervisor)

    click.echo('Migrating VM "{}" to hypervisor "{}".'.format(dom_uuid, target_hypervisor))
    transaction = zk_conn.transaction()
    transaction.set_data('/domains/{}/state'.format(dom_uuid), target_state.encode('ascii'))
    transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
    transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), current_hypervisor.encode('ascii'))
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

    target_hypervisor = zk_conn.get('/domains/{}/lasthypervisor'.format(dom_uuid))[0].decode('ascii')

    if target_hypervisor == '':
        common.stopZKConnection(zk_conn)
        return False, 'ERROR: VM "{}" has not been previously migrated.'.format(dom_uuid)

    click.echo('Unmigrating VM "{}" back to hypervisor "{}".'.format(dom_uuid, target_hypervisor))
    transaction = zk_conn.transaction()
    transaction.set_data('/domains/{}/state'.format(dom_uuid), target_state.encode('ascii'))
    transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
    transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), ''.encode('ascii'))
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
        click.echo('{}Failure reason:{}     {}'.format(ansiiprint.purple(), ansiiprint.end(), failedreason))

    click.echo('')

    return True, ''

def get_list(zk_conn, hypervisor, limit):
    if hypervisor != None:
        # Verify node is valid
        common.verifyNode(zk_conn, hypervisor)

    vm_list_raw = zk_conn.get_children('/domains')
    vm_list = []
    vm_list_output = []

    vm_hypervisor = {}
    vm_state = {}
    vm_migrated = {}
    vm_uuid = {}
    vm_name = {}
    vm_description = {}
    vm_memory = {}
    vm_vcpu = {}

    # If we're limited, remove other nodes' VMs
    for vm in vm_list_raw:
        # Check we don't match the limit
        name = zk_conn.get('/domains/{}'.format(vm))[0].decode('ascii')
        if limit != None:
            try:
                if re.match(limit, name) == None:
                    continue
            except Exception as e:
                click.echo('Regex Error: {}'.format(e))
                exit(1)
        # Check hypervisor to avoid unneeded ZK calls
        vm_hypervisor[vm] = zk_conn.get('/domains/{}/hypervisor'.format(vm))[0].decode('ascii')
        if hypervisor == None:
            vm_list.append(vm)
        else:
            if vm_hypervisor[vm] == hypervisor:
                vm_list.append(vm)

    # Gather information for printing
    for vm in vm_list:
        vm_state[vm] = zk_conn.get('/domains/{}/state'.format(vm))[0].decode('ascii')
        vm_lasthypervisor = zk_conn.get('/domains/{}/lasthypervisor'.format(vm))[0].decode('ascii')
        if vm_lasthypervisor != '':
            vm_migrated[vm] = 'from {}'.format(vm_lasthypervisor)
        else:
            vm_migrated[vm] = 'no'

        try:
            vm_xml = common.getDomainXML(zk_conn, vm)
            vm_uuid[vm], vm_name[vm], vm_description[vm], vm_memory[vm], vm_vcpu[vm], vm_vcputopo = common.getDomainMainDetails(vm_xml)
        except AttributeError:
            click.echo('Error: Domain {} does not exist.'.format(domain))

    # Determine optimal column widths
    # Dynamic columns: node_name, hypervisor, migrated
    vm_name_length = 0
    vm_hypervisor_length = 0
    vm_migrated_length = 0
    for vm in vm_list:
        # vm_name column
        _vm_name_length = len(vm_name[vm]) + 1
        if _vm_name_length > vm_name_length:
            vm_name_length = _vm_name_length
        # vm_hypervisor column
        _vm_hypervisor_length = len(vm_hypervisor[vm]) + 1
        if _vm_hypervisor_length > vm_hypervisor_length:
            vm_hypervisor_length = _vm_hypervisor_length
        # vm_migrated column
        _vm_migrated_length = len(vm_migrated[vm]) + 1
        if _vm_migrated_length > vm_migrated_length:
            vm_migrated_length = _vm_migrated_length

    # Format the string (header)
    vm_list_header = ansiiprint.bold() + 'Name             UUID                                  State     RAM [MiB]  vCPUs  Hypervisor            Migrated?' + ansiiprint.end()
    vm_list_output.append(
        '{bold}{vm_name: <{vm_name_length}} {vm_uuid: <37} \
{vm_state_colour}{vm_state: <8}{end_colour} \
{vm_memory: <10} {vm_vcpu: <6} \
{vm_hypervisor: <{vm_hypervisor_length}} \
{vm_migrated: <{vm_migrated_length}}{end_bold}'.format(
            vm_name_length=vm_name_length,
            vm_hypervisor_length=vm_hypervisor_length,
            vm_migrated_length=vm_migrated_length,
            bold=ansiiprint.bold(),
            end_bold=ansiiprint.end(),
            vm_state_colour='',
            end_colour='',
            vm_name='Name',
            vm_uuid='UUID',
            vm_state='State',
            vm_memory='RAM (MiB)',
            vm_vcpu='vCPUs',
            vm_hypervisor='Hypervisor',
            vm_migrated='Migrated'
        )
    )
            
    # Format the string (elements)
    for vm in vm_list:
        if vm_state[vm] == 'start':
            vm_state_colour = ansiiprint.green()
        elif vm_state[vm] == 'restart':
            vm_state_colour = ansiiprint.yellow()
        elif vm_state[vm] == 'shutdown':
            vm_state_colour = ansiiprint.yellow()
        elif vm_state[vm] == 'stop':
            vm_state_colour = ansiiprint.red()
        elif vm_state[vm] == 'failed':
            vm_state_colour = ansiiprint.red()
        else:
            vm_state_colour = ansiiprint.blue()

        vm_list_output.append(
            '{bold}{vm_name: <{vm_name_length}} {vm_uuid: <37} \
{vm_state_colour}{vm_state: <8}{end_colour} \
{vm_memory: <10} {vm_vcpu: <6} \
{vm_hypervisor: <{vm_hypervisor_length}} \
{vm_migrated: <{vm_migrated_length}}{end_bold}'.format(
                vm_name_length=vm_name_length,
                vm_hypervisor_length=vm_hypervisor_length,
                vm_migrated_length=vm_migrated_length,
                bold='',
                end_bold='',
                vm_state_colour=vm_state_colour,
                end_colour=ansiiprint.end(),
                vm_name=vm_name[vm],
                vm_uuid=vm_uuid[vm],
                vm_state=vm_state[vm],
                vm_memory=vm_memory[vm],
                vm_vcpu=vm_vcpu[vm],
                vm_hypervisor=vm_hypervisor[vm],
                vm_migrated=vm_migrated[vm]
            )
        )

    click.echo('\n'.join(sorted(vm_list_output)))

    return True, ''
