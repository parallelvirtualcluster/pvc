#!/usr/bin/env python3

# pvcd.py - PVC client command-line interface
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
import click
import lxml.objectify
import configparser
import kazoo.client

import pvc.ansiiprint as ansiiprint

###############################################################################
# Supplemental functions
###############################################################################

#
# Validate a UUID
#
def validateUUID(dom_uuid):
    try:
        uuid.UUID(dom_uuid)
        return True
    except:
        return False


#
# Connect and disconnect from Zookeeper
#
def startZKConnection(zk_host):
    zk_conn = kazoo.client.KazooClient(hosts=zk_host)
    zk_conn.start()
    return zk_conn

def stopZKConnection(zk_conn):
    zk_conn.stop()
    zk_conn.close()
    return 0


#
# XML information parsing functions
#

# Get the main details for a VM object from XML
def getDomainMainDetails(parsed_xml):
    # Get the information we want from it
    duuid = str(parsed_xml.uuid)
    dname = str(parsed_xml.name)
    dmemory = str(parsed_xml.memory)
    dmemory_unit = str(parsed_xml.memory.attrib['unit'])
    if dmemory_unit == 'KiB':
        dmemory = str(int(dmemory) * 1024)
    elif dmemory_unit == 'GiB':
        dmemory = str(int(dmemory) / 1024)
    dvcpu = str(parsed_xml.vcpu)
    try:
        dvcputopo = '{}/{}/{}'.format(parsed_xml.cpu.topology.attrib['sockets'], parsed_xml.cpu.topology.attrib['cores'], parsed_xml.cpu.topology.attrib['threads'])
    except:
        dvcputopo = 'N/A'

    return duuid, dname, dmemory, dvcpu, dvcputopo

# Get long-format details
def getDomainExtraDetails(parsed_xml):
    dtype = parsed_xml.os.type
    darch = parsed_xml.os.type.attrib['arch']
    dmachine = parsed_xml.os.type.attrib['machine']
    dconsole = parsed_xml.devices.console.attrib['type']
    demulator = parsed_xml.devices.emulator

    return dtype, darch, dmachine, dconsole, demulator

# Get CPU features
def getDomainCPUFeatures(parsed_xml):
    dfeatures = []
    for feature in parsed_xml.features.getchildren():
        dfeatures.append(feature.tag)

    return dfeatures

# Get disk devices
def getDomainDisks(parsed_xml):
    ddisks = []
    for device in parsed_xml.devices.getchildren():
        if device.tag == 'disk':
            disk_attrib = device.source.attrib
            disk_target = device.target.attrib
            disk_type = device.attrib['type']
            if disk_type == 'network':
                disk_obj = { 'type': disk_attrib.get('protocol'), 'name': disk_attrib.get('name'), 'dev': disk_target.get('dev'), 'bus': disk_target.get('bus') }
            elif disk_type == 'file':
                disk_obj = { 'type': 'file', 'name': disk_attrib.get('file'), 'dev': disk_target.get('dev'), 'bus': disk_target.get('bus') }
            else:
                disk_obj = {}
            ddisks.append(disk_obj)

    return ddisks

# Get network devices
def getDomainNetworks(parsed_xml):
    dnets = []
    for device in parsed_xml.devices.getchildren():
        if device.tag == 'interface':
            net_type = device.attrib['type']
            net_mac = device.mac.attrib['address']
            net_bridge = device.source.attrib[net_type]
            net_model = device.model.attrib['type']
            net_obj = { 'type': net_type, 'mac': net_mac, 'source': net_bridge, 'model': net_model }
            dnets.append(net_obj)

    return dnets

# Get controller devices
def getDomainControllers(parsed_xml):
    dcontrollers = []
    for device in parsed_xml.devices.getchildren():
        if device.tag == 'controller':
            controller_type = device.attrib['type']
            try:
                controller_model = device.attrib['model']
            except KeyError:
                controller_model = 'none'
            controller_obj = { 'type': controller_type, 'model': controller_model }
            dcontrollers.append(controller_obj)

    return dcontrollers

# Parse an XML object
def getDomainXML(zk_conn, dom_uuid):
    try:
        xml = zk_conn.get('/domains/%s/xml' % dom_uuid)[0].decode('ascii')
    except:
        return None
    
    # Parse XML using lxml.objectify
    parsed_xml = lxml.objectify.fromstring(xml)
    return parsed_xml

# Root functions
def getInformationFromNode(zk_conn, node_name, long_output):
    node_daemon_state = zk_conn.get('/nodes/{}/daemonstate'.format(node_name))[0].decode('ascii')
    node_domain_state = zk_conn.get('/nodes/{}/domainstate'.format(node_name))[0].decode('ascii')
    node_cpu_count = zk_conn.get('/nodes/{}/staticdata'.format(node_name))[0].decode('ascii').split()[0]
    node_kernel = zk_conn.get('/nodes/{}/staticdata'.format(node_name))[0].decode('ascii').split()[1]
    node_os = zk_conn.get('/nodes/{}/staticdata'.format(node_name))[0].decode('ascii').split()[2]
    node_arch = zk_conn.get('/nodes/{}/staticdata'.format(node_name))[0].decode('ascii').split()[3]
    node_mem_used = zk_conn.get('/nodes/{}/memused'.format(node_name))[0].decode('ascii')
    node_mem_free = zk_conn.get('/nodes/{}/memfree'.format(node_name))[0].decode('ascii')
    node_mem_total = int(node_mem_used) + int(node_mem_free)
    node_load = zk_conn.get('/nodes/{}/cpuload'.format(node_name))[0].decode('ascii')
    node_domains_count = zk_conn.get('/nodes/{}/domainscount'.format(node_name))[0].decode('ascii')
    node_running_domains = zk_conn.get('/nodes/{}/runningdomains'.format(node_name))[0].decode('ascii').split()
    node_mem_allocated = 0
    for domain in node_running_domains:
        parsed_xml = getDomainXML(zk_conn, domain)
        duuid, dname, dmemory, dvcpu, dvcputopo = getDomainMainDetails(parsed_xml)
        node_mem_allocated += int(dmemory)

    if node_daemon_state == 'run':
        daemon_state_colour = ansiiprint.green()
    elif node_daemon_state == 'stop':
        daemon_state_colour = ansiiprint.red()
    elif node_daemon_state == 'init':
        daemon_state_colour = ansiiprint.yellow()
    elif node_daemon_state == 'dead':
        daemon_state_colour = ansiiprint.red() + ansiiprint.bold()
    else:
        daemon_state_colour = ansiiprint.blue()

    if node_domain_state == 'ready':
        domain_state_colour = ansiiprint.green()
    else:
        domain_state_colour = ansiiprint.blue()

    # Format a nice output; do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append('{}Hypervisor Node information:{}'.format(ansiiprint.bold(), ansiiprint.end()))
    ainformation.append('')
    # Basic information
    ainformation.append('{}Name:{}                 {}'.format(ansiiprint.purple(), ansiiprint.end(), node_name))
    ainformation.append('{}Daemon State:{}         {}{}{}'.format(ansiiprint.purple(), ansiiprint.end(), daemon_state_colour, node_daemon_state, ansiiprint.end()))
    ainformation.append('{}Domain State:{}         {}{}{}'.format(ansiiprint.purple(), ansiiprint.end(), domain_state_colour, node_domain_state, ansiiprint.end()))
    ainformation.append('{}Active VM Count:{}      {}'.format(ansiiprint.purple(), ansiiprint.end(), node_domains_count))
    if long_output == True:
        ainformation.append('')
        ainformation.append('{}Architecture:{}         {}'.format(ansiiprint.purple(), ansiiprint.end(), node_arch))
        ainformation.append('{}Operating System:{}     {}'.format(ansiiprint.purple(), ansiiprint.end(), node_os))
        ainformation.append('{}Kernel Version:{}       {}'.format(ansiiprint.purple(), ansiiprint.end(), node_kernel))
    ainformation.append('')
    ainformation.append('{}CPUs:{}                 {}'.format(ansiiprint.purple(), ansiiprint.end(), node_cpu_count))
    ainformation.append('{}Load:{}                 {}'.format(ansiiprint.purple(), ansiiprint.end(), node_load))
    ainformation.append('{}Total RAM (MiB):{}      {}'.format(ansiiprint.purple(), ansiiprint.end(), node_mem_total))
    ainformation.append('{}Used RAM (MiB):{}       {}'.format(ansiiprint.purple(), ansiiprint.end(), node_mem_used))
    ainformation.append('{}Free RAM (MiB):{}       {}'.format(ansiiprint.purple(), ansiiprint.end(), node_mem_free))
    ainformation.append('{}Allocated RAM (MiB):{}  {}'.format(ansiiprint.purple(), ansiiprint.end(), node_mem_allocated))

    # Join it all together
    information = '\n'.join(ainformation)
    return information


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

    parsed_xml = getDomainXML(zk_conn, uuid)

    duuid, dname, dmemory, dvcpu, dvcputopo = getDomainMainDetails(parsed_xml)
    if long_output == True:
        dtype, darch, dmachine, dconsole, demulator = getDomainExtraDetails(parsed_xml)
        dfeatures = getDomainCPUFeatures(parsed_xml)
        ddisks = getDomainDisks(parsed_xml)
        dnets = getDomainNetworks(parsed_xml)
        dcontrollers = getDomainControllers(parsed_xml)

    # Format a nice output; do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append('{}Virtual machine information:{}'.format(ansiiprint.bold(), ansiiprint.end()))
    ainformation.append('')
    # Basic information
    ainformation.append('{}UUID:{}               {}'.format(ansiiprint.purple(), ansiiprint.end(), duuid))
    ainformation.append('{}Name:{}               {}'.format(ansiiprint.purple(), ansiiprint.end(), dname))
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

def verifyNode(zk_conn, node):
    # Verify node is valid
    try:
        zk_conn.get('/nodes/{}'.format(node))
    except:
        click.echo('ERROR: No node named "{}" is present in the cluster.'.format(node))
        exit(1)

#
# Find a migration target
#
def findTargetHypervisor(zk_conn, search_field, dom_uuid):
    if search_field == 'mem':
        return findTargetHypervisorMem(zk_conn, dom_uuid)
    if search_field == 'load':
        return findTargetHypervisorLoad(zk_conn, dom_uuid)
    if search_field == 'vcpus':
        return findTargetHypervisorVCPUs(zk_conn, dom_uuid)
    if search_field == 'vms':
        return findTargetHypervisorVMs(zk_conn, dom_uuid)
    return None

# Get the list of valid target hypervisors
def getHypervisors(zk_conn, dom_uuid):
    valid_hypervisor_list = {}
    full_hypervisor_list = zk_conn.get_children('/nodes')
    current_hypervisor = zk_conn.get('/domains/{}/hypervisor'.format(dom_uuid))[0].decode('ascii')

    for hypervisor in full_hypervisor_list:
        daemon_state = zk_conn.get('/nodes/{}/daemonstate'.format(hypervisor))[0].decode('ascii')
        domain_state = zk_conn.get('/nodes/{}/domainstate'.format(hypervisor))[0].decode('ascii')

        if hypervisor == current_hypervisor:
            continue

        if daemon_state != 'run' or domain_state != 'ready':
            continue

        valid_hypervisor_list.append(hypervisor)

    return full_hypervisor_list
    
# via free memory (relative to allocated memory)
def findTargetHypervisorMem(zk_conn, dom_uuid):
    most_allocfree = 0
    target_hypervisor = None

    hypervisor_list = getHypervisors(zk_conn, dom_uuid)
    for hypervisor in hypervisor_list:
        memalloc = int(zk_conn.get('/nodes/{}/memalloc'.format(hypervisor))[0].decode('ascii'))
        memused = int(zk_conn.get('/nodes/{}/memused'.format(hypervisor))[0].decode('ascii'))
        memfree = int(zk_conn.get('/nodes/{}/memfree'.format(hypervisor))[0].decode('ascii'))
        memtotal = memused + memfree
        allocfree = memtotal - memalloc

        if allocfree > most_allocfree:
            most_allocfree = allocfree
            target_hypervisor = hypervisor

    return target_hypervisor

# via load average
def findTargetHypervisorLoad(zk_conn, dom_uuid):
    least_load = 9999
    target_hypervisor = None

    hypervisor_list = getHypervisors(zk_conn, dom_uuid)
    for hypervisor in hypervisor_list:
        load = int(zk_conn.get('/nodes/{}/load'.format(hypervisor))[0].decode('ascii'))

        if load < least_load:
            least_load = load
            target_hypevisor = hypervisor

    return target_hypervisor

# via total vCPUs
def findTargetHypervisorVCPUs(zk_conn, dom_uuid):
    least_vcpus = 9999
    target_hypervisor = None

    hypervisor_list = getHypervisors(zk_conn, dom_uuid)
    for hypervisor in hypervisor_list:
        vcpus = int(zk_conn.get('/nodes/{}/vcpualloc'.format(hypervisor))[0].decode('ascii'))

        if vcpus < least_vcpus:
            least_vcpus = vcpus
            target_hypervisor = hypervisor

    return target_hypervisor

# via total VMs
def findTargetHypervisorVMs(zk_conn, dom_uuid):
    least_vms = 9999
    target_hypervisor = None

    hypervisor_list = getHypervisors(zk_conn, dom_uuid)
    for hypervisor in hypervisor_list:
        vms = int(zk_conn.get('/nodes/{}/domainscount'.format(hypervisor))[0].decode('ascii'))

        if vms < least_vms:
            least_vms = vms
            target_hypervisor = hypervisor

    return target_hypervisor


########################
########################
##                    ##
##  CLICK COMPONENTS  ##
##                    ##
########################
########################

myhostname = socket.gethostname()
zk_host = ''

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'], max_content_width=120)

###############################################################################
# pvc node
###############################################################################
@click.group(name='node', short_help='Manage a PVC hypervisor node', context_settings=CONTEXT_SETTINGS)
def node():
    """
    Manage the state of a node in the PVC cluster.
    """
    pass


###############################################################################
# pvc node flush
###############################################################################
@click.command(name='flush', short_help='Take a node out of service')
@click.option(
    '-w', '--wait', 'wait', is_flag=True, default=False,
    help='Wait for migrations to complete before returning.'
)
@click.argument(
    'node', default=myhostname
)
def flush_host(node, wait):
    """
    Take NODE out of active service and migrate away all VMs. If unspecified, defaults to this host.
    """

    # Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    # Verify node is valid
    verifyNode(zk_conn, node)

    click.echo('Flushing hypervisor {} of running VMs.'.format(node))

    # Add the new domain to Zookeeper
    transaction = zk_conn.transaction()
    transaction.set_data('/nodes/{}/domainstate'.format(node), 'flush'.encode('ascii'))
    results = transaction.commit()

    if wait == True:
        while True:
            time.sleep(1)
            node_state = zk_conn.get('/nodes/{}/domainstate'.format(node))[0].decode('ascii')
            if node_state == "flushed":
                break

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)


###############################################################################
# pvc node ready/unflush
###############################################################################
@click.command(name='ready', short_help='Restore node to service')
@click.argument(
    'node', default=myhostname
)
def ready_host(node):
    do_ready_host(node)

@click.command(name='unflush', short_help='Restore node to service')
@click.argument(
    'node', default=myhostname
)
def unflush_host(node):
    do_ready_host(node)


def do_ready_host(node):
    """
    Restore NODE to active service and migrate back all VMs. If unspecified, defaults to this host.
    """

    # Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    # Verify node is valid
    verifyNode(zk_conn, node)

    click.echo('Restoring hypervisor {} to active service.'.format(node))

    # Add the new domain to Zookeeper
    transaction = zk_conn.transaction()
    transaction.set_data('/nodes/{}/domainstate'.format(node), 'unflush'.encode('ascii'))
    results = transaction.commit()

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)


###############################################################################
# pvc node info
###############################################################################
@click.command(name='info', short_help='Show details of a node object')
@click.argument(
    'node', default=myhostname
)
@click.option(
    '-l', '--long', 'long_output', is_flag=True, default=False,
    help='Display more detailed information.'
)
def node_info(node, long_output):
    """
    Show information about node NODE. If unspecified, defaults to this host.
    """

    # Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    # Verify node is valid
    verifyNode(zk_conn, node)

    # Get information about node in a pretty format
    information = getInformationFromNode(zk_conn, node, long_output)

    if information == None:
        click.echo('ERROR: Could not find a node matching that name.')
        return

    click.echo(information)

    if long_output == True:
        click.echo('')
        click.echo('{}Virtual machines on node:{}'.format(ansiiprint.bold(), ansiiprint.end()))
        click.echo('')
        # List all VMs on this node
        get_vm_list(node)

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)


###############################################################################
# pvc node list
###############################################################################
@click.command(name='list', short_help='List all node objects')
def node_list():
    """
    List all hypervisor nodes in the cluster.
    """

    # Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    node_list = zk_conn.get_children('/nodes')
    node_list_output = []
    node_daemon_state = {}
    node_daemon_state = {}
    node_domain_state = {}
    node_cpu_count = {}
    node_mem_used = {}
    node_mem_free = {}
    node_mem_total = {}
    node_domains_count = {}
    node_running_domains = {}
    node_mem_allocated = {}
    node_load = {}

    # Gather information for printing
    for node_name in node_list:
        node_daemon_state[node_name] = zk_conn.get('/nodes/{}/daemonstate'.format(node_name))[0].decode('ascii')
        node_domain_state[node_name] = zk_conn.get('/nodes/{}/domainstate'.format(node_name))[0].decode('ascii')
        node_cpu_count[node_name] = zk_conn.get('/nodes/{}/staticdata'.format(node_name))[0].decode('ascii').split()[0]
        node_mem_used[node_name] = zk_conn.get('/nodes/{}/memused'.format(node_name))[0].decode('ascii')
        node_mem_free[node_name] = zk_conn.get('/nodes/{}/memfree'.format(node_name))[0].decode('ascii')
        node_mem_total[node_name] = int(node_mem_used[node_name]) + int(node_mem_free[node_name])
        node_load[node_name] = zk_conn.get('/nodes/{}/cpuload'.format(node_name))[0].decode('ascii')
        node_domains_count[node_name] = zk_conn.get('/nodes/{}/domainscount'.format(node_name))[0].decode('ascii')
        node_running_domains[node_name] = zk_conn.get('/nodes/{}/runningdomains'.format(node_name))[0].decode('ascii').split()
        node_mem_allocated[node_name] = 0
        for domain in node_running_domains[node_name]:
            parsed_xml = getDomainXML(zk_conn, domain)
            duuid, dname, dmemory, dvcpu, dvcputopo = getDomainMainDetails(parsed_xml)
            node_mem_allocated[node_name] += int(dmemory)

    # Determine optimal column widths
    # Dynamic columns: node_name, hypervisor, migrated
    node_name_length = 0
    for node_name in node_list:
        # node_name column
        _node_name_length = len(node_name) + 1
        if _node_name_length > node_name_length:
            node_name_length = _node_name_length

    # Format the string (header)
    node_list_output.append(
        '{bold}{node_name: <{node_name_length}}  \
State: {daemon_state_colour}{node_daemon_state: <7}{end_colour} {domain_state_colour}{node_domain_state: <8}{end_colour}  \
Resources: {node_domains_count: <4} {node_cpu_count: <5} {node_load: <6}  \
RAM (MiB): {node_mem_total: <6} {node_mem_used: <6} {node_mem_free: <6} {node_mem_allocated: <6}{end_bold}'.format(
            node_name_length=node_name_length,
            bold=ansiiprint.bold(),
            end_bold=ansiiprint.end(),
            daemon_state_colour='',
            domain_state_colour='',
            end_colour='',
            node_name='Name',
            node_daemon_state='Daemon',
            node_domain_state='Domains',
            node_domains_count='VMs',
            node_cpu_count='CPUs',
            node_load='Load',
            node_mem_total='Total',
            node_mem_used='Used',
            node_mem_free='Free',
            node_mem_allocated='VMs',
        )
    )
            
    # Format the string (elements)
    for node_name in node_list:
        if node_daemon_state[node_name] == 'run':
            daemon_state_colour = ansiiprint.green()
        elif node_daemon_state[node_name] == 'stop':
            daemon_state_colour = ansiiprint.red()
        elif node_daemon_state[node_name] == 'init':
            daemon_state_colour = ansiiprint.yellow()
        elif node_daemon_state[node_name] == 'dead':
            daemon_state_colour = ansiiprint.red() + ansiiprint.bold()
        else:
            daemon_state_colour = ansiiprint.blue()

        if node_mem_allocated[node_name] >= node_mem_total[node_name]:
            node_domain_state[node_name] = 'overprov'
            domain_state_colour = ansiiprint.yellow()
        elif node_domain_state[node_name] == 'ready':
            domain_state_colour = ansiiprint.green()
        else:
            domain_state_colour = ansiiprint.blue()

        node_list_output.append(
            '{bold}{node_name: <{node_name_length}}  \
       {daemon_state_colour}{node_daemon_state: <7}{end_colour} {domain_state_colour}{node_domain_state: <8}{end_colour}  \
           {node_domains_count: <4} {node_cpu_count: <5} {node_load: <6}  \
           {node_mem_total: <6} {node_mem_used: <6} {node_mem_free: <6} {node_mem_allocated: <6}{end_bold}'.format(
                node_name_length=node_name_length,
                bold='',
                end_bold='',
                daemon_state_colour=daemon_state_colour,
                domain_state_colour=domain_state_colour,
                end_colour=ansiiprint.end(),
                node_name=node_name,
                node_daemon_state=node_daemon_state[node_name],
                node_domain_state=node_domain_state[node_name],
                node_domains_count=node_domains_count[node_name],
                node_cpu_count=node_cpu_count[node_name],
                node_load=node_load[node_name],
                node_mem_total=node_mem_total[node_name],
                node_mem_used=node_mem_used[node_name],
                node_mem_free=node_mem_free[node_name],
                node_mem_allocated=node_mem_allocated[node_name]
            )
        )

    click.echo('\n'.join(sorted(node_list_output)))

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)


###############################################################################
# pvc vm
###############################################################################
@click.group(name='vm', short_help='Manage a PVC virtual machine', context_settings=CONTEXT_SETTINGS)
def vm():
    """
    Manage the state of a virtual machine in the PVC cluster.
    """
    pass


###############################################################################
# pvc vm define
###############################################################################
@click.command(name='define', short_help='Define a new virtual machine from a Libvirt XML file.')
@click.option(
    '-t', '--hypervisor', 'target_hypervisor',
    help='The home hypervisor for this domain; autoselects if unspecified.'
)
@click.option(
    '-s', '--selector', 'selector', default='mem',
    type=click.Choice(['mem','load','vcpus','vms']),
    help='Method to determine the optimal target hypervisor automatically.'
)
@click.argument(
    'config', type=click.File()
)
def define_vm(config, target_hypervisor, selector):
    """
    Define a new virtual machine from Libvirt XML configuration file CONFIG.
    """

    # Open the XML file
    data = config.read()
    config.close()

    # Parse the XML data
    parsed_xml = lxml.objectify.fromstring(data)
    dom_uuid = parsed_xml.uuid.text
    dom_name = parsed_xml.name.text
    click.echo('Adding new VM with Name "{}" and UUID "{}" to database.'.format(dom_name, dom_uuid))

    # Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    if target_hypervisor == None:
        target_hypervisor = findTargetHypervisor(zk_conn, selector, dom_uuid)

    # Verify node is valid
    verifyNode(zk_conn, target_hypervisor)

    # Add the new domain to Zookeeper
    transaction = zk_conn.transaction()
    transaction.create('/domains/{}'.format(dom_uuid), dom_name.encode('ascii'))
    transaction.create('/domains/{}/state'.format(dom_uuid), 'stop'.encode('ascii'))
    transaction.create('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
    transaction.create('/domains/{}/lasthypervisor'.format(dom_uuid), ''.encode('ascii'))
    transaction.create('/domains/{}/xml'.format(dom_uuid), data.encode('ascii'))
    results = transaction.commit()

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)


###############################################################################
# pvc vm undefine
###############################################################################
@click.command(name='undefine', short_help='Undefine and stop a virtual machine.')
@click.argument(
    'domain'
)
def undefine_vm(domain):
    """
    Stop virtual machine DOMAIN and remove it from the cluster database. DOMAIN may be a UUID or name.
    """

    # Ensure at least one search method is set
    if domain == None:
        click.echo("ERROR: You must specify either a name or UUID value.")
        return

    # Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    # Validate and obtain alternate passed value
    if validateUUID(domain):
        dom_name = searchClusterByUUID(zk_conn, domain)
        dom_uuid = searchClusterByName(zk_conn, dom_name)
    else:
        dom_uuid = searchClusterByName(zk_conn, domain)
        dom_name = searchClusterByUUID(zk_conn, dom_uuid)

    if dom_uuid == None:
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(domain))
        stopZKConnection(zk_conn)
        return

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

    # Gracefully terminate the class instances
    click.echo('Deleting VM "{}" from nodes.'.format(dom_uuid))
    zk_conn.set('/domains/{}/state'.format(dom_uuid), 'delete'.encode('ascii'))
    time.sleep(5)
    # Delete the configurations
    click.echo('Undefining VM "{}".'.format(dom_uuid))
    transaction = zk_conn.transaction()
    transaction.delete('/domains/{}/state'.format(dom_uuid))
    transaction.delete('/domains/{}/hypervisor'.format(dom_uuid))
    transaction.delete('/domains/{}/lasthypervisor'.format(dom_uuid))
    transaction.delete('/domains/{}/xml'.format(dom_uuid))
    transaction.delete('/domains/{}'.format(dom_uuid))
    transaction.commit()

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)


###############################################################################
# pvc vm start
###############################################################################
@click.command(name='start', short_help='Start up a defined virtual machine.')
@click.argument(
    'domain'
)
def start_vm(domain):
    """
    Start virtual machine DOMAIN on its configured hypervisor. DOMAIN may be a UUID or name.
    """

    # Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    # Validate and obtain alternate passed value
    if validateUUID(domain):
        dom_name = searchClusterByUUID(zk_conn, domain)
        dom_uuid = searchClusterByName(zk_conn, dom_name)
    else:
        dom_uuid = searchClusterByName(zk_conn, domain)
        dom_name = searchClusterByUUID(zk_conn, dom_uuid)

    if dom_uuid == None:
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(domain))
        stopZKConnection(zk_conn)
        return

    # Set the VM to start
    click.echo('Starting VM "{}".'.format(dom_uuid))
    zk_conn.set('/domains/%s/state' % dom_uuid, 'start'.encode('ascii'))

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)


###############################################################################
# pvc vm restart
###############################################################################
@click.command(name='restart', short_help='Restart a running virtual machine.')
@click.argument(
    'domain'
)
def restart_vm(domain):
    """
    Restart running virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    # Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    # Validate and obtain alternate passed value
    if validateUUID(domain):
        dom_name = searchClusterByUUID(zk_conn, domain)
        dom_uuid = searchClusterByName(zk_conn, dom_name)
    else:
        dom_uuid = searchClusterByName(zk_conn, domain)
        dom_name = searchClusterByUUID(zk_conn, dom_uuid)

    if dom_uuid == None:
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(domain))
        stopZKConnection(zk_conn)
        return

    # Get state and verify we're OK to proceed
    current_state = zk_conn.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_state != 'start':
        click.echo('ERROR: The VM "{}" is not in "start" state!'.format(dom_uuid))
        return

    # Set the VM to start
    click.echo('Restarting VM "{}".'.format(dom_uuid))
    zk_conn.set('/domains/%s/state' % dom_uuid, 'restart'.encode('ascii'))

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)


###############################################################################
# pvc vm shutdown
###############################################################################
@click.command(name='shutdown', short_help='Gracefully shut down a running virtual machine.')
@click.argument(
	'domain'
)
def shutdown_vm(domain):
    """
    Gracefully shut down virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    # Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    # Validate and obtain alternate passed value
    if validateUUID(domain):
        dom_name = searchClusterByUUID(zk_conn, domain)
        dom_uuid = searchClusterByName(zk_conn, dom_name)
    else:
        dom_uuid = searchClusterByName(zk_conn, domain)
        dom_name = searchClusterByUUID(zk_conn, dom_uuid)

    if dom_uuid == None:
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(domain))
        stopZKConnection(zk_conn)
        return

    # Get state and verify we're OK to proceed
    current_state = zk_conn.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_state != 'start':
        click.echo('ERROR: The VM "{}" is not in "start" state!'.format(dom_uuid))
        return

    # Set the VM to shutdown
    click.echo('Shutting down VM "{}".'.format(dom_uuid))
    zk_conn.set('/domains/%s/state' % dom_uuid, 'shutdown'.encode('ascii'))

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)


###############################################################################
# pvc vm stop
###############################################################################
@click.command(name='stop', short_help='Forcibly halt a running virtual machine.')
@click.argument(
    'domain'
)
def stop_vm(domain):
    """
    Forcibly halt (destroy) running virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    # Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    # Validate and obtain alternate passed value
    if validateUUID(domain):
        dom_name = searchClusterByUUID(zk_conn, domain)
        dom_uuid = searchClusterByName(zk_conn, dom_name)
    else:
        dom_uuid = searchClusterByName(zk_conn, domain)
        dom_name = searchClusterByUUID(zk_conn, dom_uuid)

    if dom_uuid == None:
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(domain))
        stopZKConnection(zk_conn)
        return

    # Get state and verify we're OK to proceed
    current_state = zk_conn.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_state != 'start':
        click.echo('ERROR: The VM "{}" is not in "start" state!'.format(dom_uuid))
        return

    # Set the VM to start
    click.echo('Forcibly stopping VM "{}".'.format(dom_uuid))
    zk_conn.set('/domains/%s/state' % dom_uuid, 'stop'.encode('ascii'))

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)


###############################################################################
# pvc vm move
###############################################################################
@click.command(name='move', short_help='Permanently move a virtual machine to another node.')
@click.argument(
	'domain'
)
@click.option(
    '-t', '--hypervisor', 'target_hypervisor', default=None,
    help='The target hypervisor to migrate to. Autodetect based on most free RAM if unspecified.'
)
@click.option(
    '-s', '--selector', 'selector', default='mem',
    type=click.Choice(['mem','load','vcpus','vms']),
    help='Method to determine the optimal target hypervisor automatically.'
)
def move_vm(domain, target_hypervisor, selector):
    """
    Permanently move virtual machine DOMAIN, via live migration if running and possible, to another hypervisor node. DOMAIN may be a UUID or name.
    """

    # Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    # Validate and obtain alternate passed value
    if validateUUID(domain):
        dom_name = searchClusterByUUID(zk_conn, domain)
        dom_uuid = searchClusterByName(zk_conn, dom_name)
    else:
        dom_uuid = searchClusterByName(zk_conn, domain)
        dom_name = searchClusterByUUID(zk_conn, dom_uuid)

    if dom_uuid == None:
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(domain))
        stopZKConnection(zk_conn)
        return

    current_hypervisor = zk_conn.get('/domains/{}/hypervisor'.format(dom_uuid))[0].decode('ascii')

    if target_hypervisor == None:
        target_hypervisor = findTargetHypervisor(zk_conn, selector, dom_uuid)
    else:
        if target_hypervisor == current_hypervisor:
            click.echo('ERROR: The VM "{}" is already running on hypervisor "{}".'.format(dom_uuid, current_hypervisor))
            return

        # Verify node is valid
        verifyNode(zk_conn, target_hypervisor)

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

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)


###############################################################################
# pvc vm migrate
###############################################################################
@click.command(name='migrate', short_help='Temporarily migrate a virtual machine to another node.')
@click.argument(
    'domain'
)
@click.option(
    '-t', '--hypervisor', 'target_hypervisor', default=None,
    help='The target hypervisor to migrate to. Autodetect based on most free RAM if unspecified.'
)
@click.option(
    '-s', '--selector', 'selector', default='mem',
    type=click.Choice(['mem','load','vcpus','vms']),
    help='Method to determine the optimal target hypervisor automatically.'
)
@click.option(
    '-f', '--force', 'force_migrate', is_flag=True, default=False,
    help='Force migrate an already migrated VM.'
)
def migrate_vm(domain, target_hypervisor, selector, force_migrate):
    """
    Temporarily migrate running virtual machine DOMAIN, via live migration if possible, to another hypervisor node. DOMAIN may be a UUID or name. If DOMAIN is not running, it will be started on the target node.
    """

    # Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    # Validate and obtain alternate passed value
    if validateUUID(domain):
        dom_name = searchClusterByUUID(zk_conn, domain)
        dom_uuid = searchClusterByName(zk_conn, dom_name)
    else:
        dom_uuid = searchClusterByName(zk_conn, domain)
        dom_name = searchClusterByUUID(zk_conn, dom_uuid)

    if dom_uuid == None:
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(domain))
        stopZKConnection(zk_conn)
        return

    # Get state and verify we're OK to proceed
    current_state = zk_conn.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_state != 'start':
        target_state = 'start'
    else:
        target_state = 'migrate'

    current_hypervisor = zk_conn.get('/domains/{}/hypervisor'.format(dom_uuid))[0].decode('ascii')
    last_hypervisor = zk_conn.get('/domains/{}/lasthypervisor'.format(dom_uuid))[0].decode('ascii')

    if last_hypervisor != '' and force_migrate != True:
        click.echo('ERROR: The VM "{}" has been previously migrated.'.format(dom_uuid))
        click.echo('> Last hypervisor: {}'.format(last_hypervisor))
        click.echo('> Current hypervisor: {}'.format(current_hypervisor))
        click.echo('Run `vm unmigrate` to restore the VM to its previous hypervisor, or use `--force` to override this check.')
        return

    if target_hypervisor == None:
        target_hypervisor = findTargetHypervisor(zk_conn, selector, dom_uuid)
    else:
        if target_hypervisor == current_hypervisor:
            click.echo('ERROR: The VM "{}" is already running on hypervisor "{}".'.format(dom_uuid, current_hypervisor))
            return

        # Verify node is valid
        verifyNode(zk_conn, target_hypervisor)

    click.echo('Migrating VM "{}" to hypervisor "{}".'.format(dom_uuid, target_hypervisor))
    transaction = zk_conn.transaction()
    transaction.set_data('/domains/{}/state'.format(dom_uuid), target_state.encode('ascii'))
    transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
    transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), current_hypervisor.encode('ascii'))
    transaction.commit()

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)


###############################################################################
# pvc vm unmigrate
###############################################################################
@click.command(name='unmigrate', short_help='Restore a migrated virtual machine to its original node.')
@click.argument(
    'domain'
)
def unmigrate_vm(domain):
    """
    Restore previously migrated virtual machine DOMAIN, via live migration if possible, to its original hypervisor node. DOMAIN may be a UUID or name. If DOMAIN is not running, it will be started on the target node.
    """

    # Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    # Validate and obtain alternate passed value
    if validateUUID(domain):
        dom_name = searchClusterByUUID(zk_conn, domain)
        dom_uuid = searchClusterByName(zk_conn, dom_name)
    else:
        dom_uuid = searchClusterByName(zk_conn, domain)
        dom_name = searchClusterByUUID(zk_conn, dom_uuid)

    if dom_uuid == None:
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(domain))
        stopZKConnection(zk_conn)
        return

    # Get state and verify we're OK to proceed
    current_state = zk_conn.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_state != 'start':
        target_state = 'start'
    else:
        target_state = 'migrate'

    target_hypervisor = zk_conn.get('/domains/{}/lasthypervisor'.format(dom_uuid))[0].decode('ascii')

    if target_hypervisor == '':
        click.echo('ERROR: The VM "{}" has not been previously migrated.'.format(dom_uuid))
        return

    click.echo('Unmigrating VM "{}" back to hypervisor "{}".'.format(dom_uuid, target_hypervisor))
    transaction = zk_conn.transaction()
    transaction.set_data('/domains/{}/state'.format(dom_uuid), target_state.encode('ascii'))
    transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
    transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), ''.encode('ascii'))
    transaction.commit()

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)


###############################################################################
# pvc vm info
###############################################################################
@click.command(name='info', short_help='Show details of a VM object')
@click.argument(
    'domain'
)
@click.option(
    '-l', '--long', 'long_output', is_flag=True, default=False,
    help='Display more detailed information.'
)
def vm_info(domain, long_output):
    """
	Show information about virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

	# Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    # Validate and obtain alternate passed value
    if validateUUID(domain):
        dom_name = searchClusterByUUID(zk_conn, domain)
        dom_uuid = searchClusterByName(zk_conn, dom_name)
    else:
        dom_uuid = searchClusterByName(zk_conn, domain)
        dom_name = searchClusterByUUID(zk_conn, dom_uuid)

    if dom_uuid == None:
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(domain))
        stopZKConnection(zk_conn)
        return

    # Gather information from XML config and print it
    information = getInformationFromXML(zk_conn, dom_uuid, long_output)
    click.echo(information)

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)


###############################################################################
# pvc vm list
###############################################################################
@click.command(name='list', short_help='List all VM objects')
@click.option(
    '-t', '--hypervisor', 'hypervisor', default=None,
    help='Limit list to this hypervisor.'
)
def vm_list(hypervisor):
    get_vm_list(hypervisor)

# Wrapped function to allow calling from `node info`
def get_vm_list(hypervisor):
    """
    List all virtual machines in the cluster.
    """

    # Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    if hypervisor != None:
        # Verify node is valid
        verifyNode(zk_conn, hypervisor)

    vm_list_raw = zk_conn.get_children('/domains')
    vm_list = []
    vm_list_output = []

    vm_hypervisor = {}
    vm_state = {}
    vm_migrated = {}
    vm_uuid = {}
    vm_name = {}
    vm_memory = {}
    vm_vcpu = {}

    # If we're limited, remove other nodes' VMs
    for vm in vm_list_raw:
        # Check hypervisor to avoid unneeded ZK calls
        vm_hypervisor[vm] = zk_conn.get('/domains/{}/hypervisor'.format(vm))[0].decode('ascii')
        if hypervisor != None:
            if vm_hypervisor[vm] == hypervisor:
                vm_list.append(vm)
        else:
            vm_list.append(vm)

    # Gather information for printing
    for vm in vm_list:
        vm_state[vm] = zk_conn.get('/domains/{}/state'.format(vm))[0].decode('ascii')
        vm_lasthypervisor = zk_conn.get('/domains/{}/lasthypervisor'.format(vm))[0].decode('ascii')
        if vm_lasthypervisor != '':
            vm_migrated[vm] = 'from {}'.format(vm_lasthypervisor)
        else:
            vm_migrated[vm] = 'no'

        vm_xml = getDomainXML(zk_conn, vm)
        vm_uuid[vm], vm_name[vm], vm_memory[vm], vm_vcpu[vm], vm_vcputopo = getDomainMainDetails(vm_xml)

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

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)


###############################################################################
# pvc init
###############################################################################
@click.command(name='init', short_help='Initialize a new cluster')
@click.option('--yes', is_flag=True,
              expose_value=False,
              prompt='DANGER: This command will destroy any existing cluster data. Do you want to continue?')
def init_cluster():
    """
    Perform initialization of Zookeeper to act as a PVC cluster
    """

    click.echo('Initializing a new cluster with Zookeeper address "{}".'.format(zk_host))

    # Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    # Destroy the existing data
    try:
        zk_conn.delete('/domains', recursive=True)
        zk_conn.delete('nodes', recursive=True)
    except:
        pass

    # Create the root keys
    transaction = zk_conn.transaction()
    transaction.create('/domains', ''.encode('ascii'))
    transaction.create('/nodes', ''.encode('ascii'))
    transaction.commit()

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)

    click.echo('Successfully initialized new cluster. Any running PVC daemons will need to be restarted.')


###############################################################################
# pvc
###############################################################################
@click.group(context_settings=CONTEXT_SETTINGS)
@click.option(
    '-z', '--zookeeper', '_zk_host', envvar='PVC_ZOOKEEPER', default='{}:2181'.format(myhostname), show_default=True,
    help='Zookeeper connection string.'
)
def cli(_zk_host):
    """
    Parallel Virtual Cluster CLI management tool

    You can use the environment variable "PVC_ZOOKEEPER" to set the Zookeeper address in addition to using "--zookeeper".
    """

    global zk_host
    zk_host = _zk_host


#
# Click command tree
#
node.add_command(flush_host)
node.add_command(ready_host)
node.add_command(unflush_host)
node.add_command(node_info)
node.add_command(node_list)

vm.add_command(define_vm)
vm.add_command(undefine_vm)
vm.add_command(start_vm)
vm.add_command(restart_vm)
vm.add_command(shutdown_vm)
vm.add_command(stop_vm)
vm.add_command(move_vm)
vm.add_command(migrate_vm)
vm.add_command(unmigrate_vm)
vm.add_command(vm_info)
vm.add_command(vm_list)

cli.add_command(node)
cli.add_command(vm)
cli.add_command(init_cluster)

#
# Main entry point
#
def main():
    return cli(obj={})

if __name__ == '__main__':
    main()

