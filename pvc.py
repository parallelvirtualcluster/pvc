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
    zk = kazoo.client.KazooClient(hosts=zk_host)
    zk.start()
    return zk

def stopZKConnection(zk):
    zk.stop()
    zk.close()
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
def getDomainXML(zk, dom_uuid):
    try:
        xml = zk.get('/domains/%s/xml' % dom_uuid)[0].decode('ascii')
    except:
        return None
    
    # Parse XML using lxml.objectify
    parsed_xml = lxml.objectify.fromstring(xml)
    return parsed_xml

# Root functions
def getInformationFromNode(zk, node_name, long_output):
    node_daemon_state = zk.get('/nodes/{}/daemonstate'.format(node_name))[0].decode('ascii')
    node_domain_state = zk.get('/nodes/{}/domainstate'.format(node_name))[0].decode('ascii')
    node_cpu_count = zk.get('/nodes/{}/staticdata'.format(node_name))[0].decode('ascii').split()[0]
    node_arch = zk.get('/nodes/{}/staticdata'.format(node_name))[0].decode('ascii').split()[1]
    node_os = zk.get('/nodes/{}/staticdata'.format(node_name))[0].decode('ascii').split()[2]
    node_kernel = zk.get('/nodes/{}/staticdata'.format(node_name))[0].decode('ascii').split()[3]
    node_mem_used = zk.get('/nodes/{}/memused'.format(node_name))[0].decode('ascii')
    node_mem_free = zk.get('/nodes/{}/memfree'.format(node_name))[0].decode('ascii')
    node_mem_total = int(node_mem_used) + int(node_mem_free)
    node_domains_count = zk.get('/nodes/{}/domainscount'.format(node_name))[0].decode('ascii')
    node_running_domains = zk.get('/nodes/{}/runningdomains'.format(node_name))[0].decode('ascii').split()
    node_mem_allocated = 0
    for domain in node_running_domains:
        parsed_xml = getDomainXML(zk, domain)
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
    ainformation.append('{}Active Domain Count:{}  {}'.format(ansiiprint.purple(), ansiiprint.end(), node_domains_count))
    if long_output == True:
        ainformation.append('')
        ainformation.append('{}Architecture:{}         {}'.format(ansiiprint.purple(), ansiiprint.end(), node_arch))
        ainformation.append('{}Operating System:{}     {}'.format(ansiiprint.purple(), ansiiprint.end(), node_os))
        ainformation.append('{}Kernel Version:{}       {}'.format(ansiiprint.purple(), ansiiprint.end(), node_kernel))
    ainformation.append('')
    ainformation.append('{}CPUs:{}                 {}'.format(ansiiprint.purple(), ansiiprint.end(), node_cpu_count))
    ainformation.append('{}Total RAM (MiB):{}      {}'.format(ansiiprint.purple(), ansiiprint.end(), node_mem_total))
    ainformation.append('{}Used RAM (MiB):{}       {}'.format(ansiiprint.purple(), ansiiprint.end(), node_mem_used))
    ainformation.append('{}Free RAM (MiB):{}       {}'.format(ansiiprint.purple(), ansiiprint.end(), node_mem_free))
    ainformation.append('{}Allocated RAM (MiB):{}  {}'.format(ansiiprint.purple(), ansiiprint.end(), node_mem_allocated))

    # Join it all together
    information = '\n'.join(ainformation)
    return information


def getInformationFromXML(zk, uuid, long_output):
    # Obtain the contents of the XML from Zookeeper
    try:
        dstate = zk.get('/domains/{}/state'.format(uuid))[0].decode('ascii')
        dhypervisor = zk.get('/domains/{}/hypervisor'.format(uuid))[0].decode('ascii')
        dlasthypervisor = zk.get('/domains/{}/lasthypervisor'.format(uuid))[0].decode('ascii')
    except:
        return None

    if dlasthypervisor == '':
        dlasthypervisor = 'N/A'

    parsed_xml = getDomainXML(zk, uuid)

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
def getClusterDomainList(zk):
    # Get a list of UUIDs by listing the children of /domains
    uuid_list = zk.get_children('/domains')
    name_list = []
    # For each UUID, get the corresponding name from the data
    for uuid in uuid_list:
        name_list.append(zk.get('/domains/%s' % uuid)[0].decode('ascii'))
    return uuid_list, name_list

def searchClusterByUUID(zk, uuid):
    try:
        # Get the lists
        uuid_list, name_list = getClusterDomainList(zk)
        # We're looking for UUID, so find that element ID
        index = uuid_list.index(uuid)
        # Get the name_list element at that index
        name = name_list[index]
    except ValueError:
        # We didn't find anything
        return None

    return name

def searchClusterByName(zk, name):
    try:
        # Get the lists
        uuid_list, name_list = getClusterDomainList(zk)
        # We're looking for name, so find that element ID
        index = name_list.index(name)
        # Get the uuid_list element at that index
        uuid = uuid_list[index]
    except ValueError:
        # We didn't find anything
        return None

    return uuid


#
# Allow mutually exclusive options in Click
#
class MutuallyExclusiveOption(click.Option):
    def __init__(self, *args, **kwargs):
        meargs = kwargs.pop('mutually_exclusive', [])
        _me_arg = []
        _me_func = []

        for arg in meargs:
            _me_arg.append(arg['argument'])
            _me_func.append(arg['function'])

        self.me_arg = set(_me_arg)
        self.me_func = set(_me_func)

        help = kwargs.get('help', '')
        if self.me_func:
            ex_str = ', '.join(self.me_arg)
            kwargs['help'] = help + (
                ' Mutually exclusive with `' + ex_str + '`.'
            )

        super(MutuallyExclusiveOption, self).__init__(*args, **kwargs)

    def handle_parse_result(self, ctx, opts, args):
        if self.me_func.intersection(opts) and self.name in opts:
            raise click.UsageError(
                "Illegal usage: `{}` is mutually exclusive with "
                "arguments `{}`.".format(
                    self.opts[-1],
                    ', '.join(self.me_arg)
                )
            )

        return super(MutuallyExclusiveOption, self).handle_parse_result(
            ctx,
            opts,
            args
        )

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
    '-n', '--name', 'node_name', default=myhostname, show_default=True,
    help='The PVC node to operate on.'
)
def flush_host(node_name):
    """
    Take a node out of active service and migrate away all VMs.

    Notes:

    * The '--name' option defaults to the current host if not set, which is likely not what you want when running this command from a remote host!
    """

    # Open a Zookeeper connection
    zk = startZKConnection(zk_host)

    # Verify node is valid
    try:
        zk.get('/nodes/{}'.format(node_name))
    except:
        click.echo('ERROR: No node named {} is present in the cluster.'.format(node_name))
        exit(1)

    click.echo('Flushing hypervisor {} of running VMs.'.format(node_name))

    # Add the new domain to Zookeeper
    transaction = zk.transaction()
    transaction.set_data('/nodes/{}/domainstate'.format(node_name), 'flush'.encode('ascii'))
    results = transaction.commit()

    # Close the Zookeeper connection
    stopZKConnection(zk)


###############################################################################
# pvc node ready
###############################################################################
@click.command(name='ready', short_help='Restore node to service')
@click.option(
    '-n', '--name', 'node_name', default=myhostname, show_default=True,
    help='The PVC node to operate on.'
)
def ready_host(node_name):
    """
    Restore a host to active service and migrate back all VMs.

    Notes:

    * The '--name' option defaults to the current host if not set, which is likely not what you want when running this command from a remote host!
    """

    # Open a Zookeeper connection
    zk = startZKConnection(zk_host)

    # Verify node is valid
    try:
        zk.get('/nodes/{}'.format(node_name))
    except:
        click.echo('ERROR: No node named {} is present in the cluster.'.format(node_name))
        exit(1)

    click.echo('Restoring hypervisor {} to active service.'.format(node_name))

    # Add the new domain to Zookeeper
    transaction = zk.transaction()
    transaction.set_data('/nodes/{}/domainstate'.format(node_name), 'unflush'.encode('ascii'))
    results = transaction.commit()

    # Close the Zookeeper connection
    stopZKConnection(zk)


###############################################################################
# pvc node info
###############################################################################
@click.command(name='info', short_help='Show details of a node object')
@click.option(
    '-n', '--name', 'node_name',
    help='Search for this name.'
)
@click.option(
    '-l', '--long', 'long_output', is_flag=True, default=False,
    help='Display more detailed information.'
)
def node_info(node_name, long_output):
    """
    Search the cluster for a node's information.
    """

    # Open a Zookeeper connection
    zk = startZKConnection(zk_host)

    # Verify node is valid
    try:
        zk.get('/nodes/{}'.format(node_name))
    except:
        click.echo('ERROR: No node named {} is present in the cluster.'.format(node_name))
        exit(1)

    # Get information about node in a pretty format
    information = getInformationFromNode(zk, node_name, long_output)

    if information == None:
        click.echo('ERROR: Could not find a domain matching that name or UUID.')
        return

    click.echo(information)

    if long_output == True:
        click.echo('')
        click.echo('{}Virtual machines on node:{}'.format(ansiiprint.bold(), ansiiprint.end()))
        click.echo('')
        # List all VMs on this node
        _vm_list(node_name)

    # Close the Zookeeper connection
    stopZKConnection(zk)


###############################################################################
# pvc node list
###############################################################################
@click.command(name='list', short_help='List all Node objects')
def node_list():
    """
    List all hypervisor nodes in the cluster.
    """

    # Open a Zookeeper connection
    zk = startZKConnection(zk_host)

    node_list = zk.get_children('/nodes')
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

    # Gather information for printing
    for node_name in node_list:
        node_daemon_state[node_name] = zk.get('/nodes/{}/daemonstate'.format(node_name))[0].decode('ascii')
        node_domain_state[node_name] = zk.get('/nodes/{}/domainstate'.format(node_name))[0].decode('ascii')
        node_cpu_count[node_name] = zk.get('/nodes/{}/staticdata'.format(node_name))[0].decode('ascii').split()[0]
        node_mem_used[node_name] = zk.get('/nodes/{}/memused'.format(node_name))[0].decode('ascii')
        node_mem_free[node_name] = zk.get('/nodes/{}/memfree'.format(node_name))[0].decode('ascii')
        node_mem_total[node_name] = int(node_mem_used[node_name]) + int(node_mem_free[node_name])
        node_domains_count[node_name] = zk.get('/nodes/{}/domainscount'.format(node_name))[0].decode('ascii')
        node_running_domains[node_name] = zk.get('/nodes/{}/runningdomains'.format(node_name))[0].decode('ascii').split()
        node_mem_allocated[node_name] = 0
        for domain in node_running_domains[node_name]:
            parsed_xml = getDomainXML(zk, domain)
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
Resources: {node_domains_count: <4} {node_cpu_count: <5}  \
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
            node_mem_total='Total',
            node_mem_used='Used',
            node_mem_free='Free',
            node_mem_allocated='VMs'
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

        if node_domain_state[node_name] == 'ready':
            domain_state_colour = ansiiprint.green()
        else:
            domain_state_colour = ansiiprint.blue()

        node_list_output.append(
            '{bold}{node_name: <{node_name_length}}  \
       {daemon_state_colour}{node_daemon_state: <7}{end_colour} {domain_state_colour}{node_domain_state: <8}{end_colour}  \
           {node_domains_count: <4} {node_cpu_count: <5}  \
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
                node_mem_total=node_mem_total[node_name],
                node_mem_used=node_mem_used[node_name],
                node_mem_free=node_mem_free[node_name],
                node_mem_allocated=node_mem_allocated[node_name]
            )
        )

    click.echo('\n'.join(sorted(node_list_output)))

    # Close the Zookeeper connection
    stopZKConnection(zk)


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
    '-x', '--xml', 'xml_config_file',
    help='The XML config file to define the domain from.'
)
@click.option(
    '-t', '--hypervisor', 'target_hypervisor', default=myhostname, show_default=True,
    help='The home hypervisor for this domain.'
)
def define_vm(xml_config_file, target_hypervisor):
    """
    Define a new virtual machine from a Libvirt XML configuration file.

    Notes:

    * The '--hypervisor' option defaults to the current host if not set, which is likely not what you want when running this command from a remote host!
    """

    # Open the XML file
    with open(xml_config_file, 'r') as f_domxmlfile:
        data = f_domxmlfile.read()
        f_domxmlfile.close()

    # Parse the XML data
    parsed_xml = lxml.objectify.fromstring(data)
    dom_uuid = parsed_xml.uuid.text
    dom_name = parsed_xml.name.text
    click.echo('Adding new VM with Name "{}" and UUID "{}" to database.'.format(dom_name, dom_uuid))

    # Open a Zookeeper connection
    zk = startZKConnection(zk_host)

    # Add the new domain to Zookeeper
    transaction = zk.transaction()
    transaction.create('/domains/{}'.format(dom_uuid), dom_name.encode('ascii'))
    transaction.create('/domains/{}/state'.format(dom_uuid), 'stop'.encode('ascii'))
    transaction.create('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
    transaction.create('/domains/{}/lasthypervisor'.format(dom_uuid), ''.encode('ascii'))
    transaction.create('/domains/{}/xml'.format(dom_uuid), data.encode('ascii'))
    results = transaction.commit()

    # Close the Zookeeper connection
    stopZKConnection(zk)


###############################################################################
# pvc vm undefine
###############################################################################
@click.command(name='undefine', short_help='Undefine and stop a virtual machine.')
@click.option(
    '-n', '--name', 'dom_name',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_uuid', 'argument': '--uuid' }],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_name', 'argument': '--name' }],
    help='Search for this UUID.'
)
def undefine_vm(dom_name, dom_uuid):
    """
    Stop a virtual machine and remove it from the cluster database.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("ERROR: You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = searchClusterByName(zk, dom_name)

    # Verify we got a result or abort
    if not validateUUID(dom_uuid):
        if dom_name != None:
            message_name = dom_name
        else:
            message_name = dom_uuid
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(message_name))
        return

    current_vm_state = zk.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_vm_state != 'stop':
        click.echo('Forcibly stopping VM "{}".'.format(dom_uuid))
        # Set the domain into stop mode
        transaction = zk.transaction()
        transaction.set_data('/domains/{}/state'.format(dom_uuid), 'stop'.encode('ascii'))
        transaction.commit()

        # Wait for 3 seconds to allow state to flow to all hypervisors
        click.echo('Waiting for cluster to update.')
        time.sleep(1)

    # Gracefully terminate the class instances
    zk.set('/domains/{}/state'.format(dom_uuid), 'delete'.encode('ascii'))
    time.sleep(5)
    # Delete the configurations
    click.echo('Undefining VM "{}".'.format(dom_uuid))
    transaction = zk.transaction()
    transaction.delete('/domains/{}/state'.format(dom_uuid))
    transaction.delete('/domains/{}/hypervisor'.format(dom_uuid))
    transaction.delete('/domains/{}/lasthypervisor'.format(dom_uuid))
    transaction.delete('/domains/{}/xml'.format(dom_uuid))
    transaction.delete('/domains/{}'.format(dom_uuid))
    transaction.commit()

    # Close the Zookeeper connection
    stopZKConnection(zk)


###############################################################################
# pvc vm start
###############################################################################
@click.command(name='start', short_help='Start up a defined virtual machine.')
@click.option(
    '-n', '--name', 'dom_name',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_uuid', 'argument': '--uuid' }],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_name', 'argument': '--name' }],
    help='Search for this UUID.'
)
def start_vm(dom_name, dom_uuid):
    """
    Start up a virtual machine on its configured hypervisor.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("ERROR: You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = searchClusterByName(zk, dom_name)

    # Verify we got a result or abort
    if not validateUUID(dom_uuid):
        if dom_name != None:
            message_name = dom_name
        else:
            message_name = dom_uuid
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(message_name))
        return

    # Set the VM to start
    click.echo('Starting VM "{}".'.format(dom_uuid))
    zk.set('/domains/%s/state' % dom_uuid, 'start'.encode('ascii'))

    # Close the Zookeeper connection
    stopZKConnection(zk)


###############################################################################
# pvc vm restart
###############################################################################
@click.command(name='restart', short_help='Restart virtual machine.')
@click.option(
    '-n', '--name', 'dom_name',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_uuid', 'argument': '--uuid' }],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_name', 'argument': '--name' }],
    help='Search for this UUID.'
)
def restart_vm(dom_name, dom_uuid):
    """
    Restart a virtual machine on its configured hypervisor.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("ERROR: You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = searchClusterByName(zk, dom_name)

    # Verify we got a result or abort
    if not validateUUID(dom_uuid):
        if dom_name != None:
            message_name = dom_name
        else:
            message_name = dom_uuid
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(message_name))
        return

    # Get state and verify we're OK to proceed
    current_state = zk.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_state != 'start':
        click.echo('ERROR: The VM "{}" is not in "start" state!'.format(dom_uuid))
        return

    # Set the VM to start
    click.echo('Restarting VM "{}".'.format(dom_uuid))
    zk.set('/domains/%s/state' % dom_uuid, 'restart'.encode('ascii'))

    # Close the Zookeeper connection
    stopZKConnection(zk)


###############################################################################
# pvc vm shutdown
###############################################################################
@click.command(name='shutdown', short_help='Gracefully shut down a running virtual machine.')
@click.option(
    '-n', '--name', 'dom_name',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_uuid', 'argument': '--uuid' }],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_name', 'argument': '--name' }],
    help='Search for this UUID.'
)
def shutdown_vm(dom_name, dom_uuid):
    """
    Gracefully shut down a running virtual machine.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("ERROR: You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = searchClusterByName(zk, dom_name)

    # Verify we got a result or abort
    if not validateUUID(dom_uuid):
        if dom_name != None:
            message_name = dom_name
        else:
            message_name = dom_uuid
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(message_name))
        return

    # Get state and verify we're OK to proceed
    current_state = zk.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_state != 'start':
        click.echo('ERROR: The VM "{}" is not in "start" state!'.format(dom_uuid))
        return

    # Set the VM to shutdown
    click.echo('Shutting down VM "{}".'.format(dom_uuid))
    zk.set('/domains/%s/state' % dom_uuid, 'shutdown'.encode('ascii'))

    # Close the Zookeeper connection
    stopZKConnection(zk)


###############################################################################
# pvc vm stop
###############################################################################
@click.command(name='stop', short_help='Forcibly halt a running virtual machine.')
@click.option(
    '-n', '--name', 'dom_name',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_uuid', 'argument': '--uuid' }],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_name', 'argument': '--name' }],
    help='Search for this UUID.'
)
def stop_vm(dom_name, dom_uuid):
    """
    Forcibly halt (destroy) a running virtual machine.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("ERROR: You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = searchClusterByName(zk, dom_name)

    # Verify we got a result or abort
    if not validateUUID(dom_uuid):
        if dom_name != None:
            message_name = dom_name
        else:
            message_name = dom_uuid
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(message_name))
        return

    # Get state and verify we're OK to proceed
    current_state = zk.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_state != 'start':
        click.echo('ERROR: The VM "{}" is not in "start" state!'.format(dom_uuid))
        return

    # Set the VM to start
    click.echo('Forcibly stopping VM "{}".'.format(dom_uuid))
    zk.set('/domains/%s/state' % dom_uuid, 'stop'.encode('ascii'))

    # Close the Zookeeper connection
    stopZKConnection(zk)


###############################################################################
# pvc vm move
###############################################################################
@click.command(name='move', short_help='Permanently move a virtual machine to another node.')
@click.option(
    '-n', '--name', 'dom_name',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_uuid', 'argument': '--uuid' }],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_name', 'argument': '--name' }],
    help='Search for this UUID.'
)
@click.option(
    '-t', '--target', 'target_hypervisor', default=None,
    help='The target hypervisor to migrate to.'
)
def move_vm(dom_name, dom_uuid, target_hypervisor):
    """
    Permanently move a virtual machine, via live migration if running and possible, to another hypervisor node.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("ERROR: You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = searchClusterByName(zk, dom_name)

    # Verify we got a result or abort
    if not validateUUID(dom_uuid):
        if dom_name != None:
            message_name = dom_name
        else:
            message_name = dom_uuid
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(message_name))
        return

    # Get state and verify we're OK to proceed
    current_state = zk.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_state != 'start':
        click.echo('ERROR: The VM "{}" is not in "start" state!'.format(dom_uuid))
        return

    current_hypervisor = zk.get('/domains/{}/hypervisor'.format(dom_uuid))[0].decode('ascii')

    if target_hypervisor == None:
        # Determine the best hypervisor to migrate the VM to based on active memory usage
        hypervisor_list = zk.get_children('/nodes')
        most_memfree = 0
        for hypervisor in hypervisor_list:
            state = zk.get('/nodes/{}/state'.format(hypervisor))[0].decode('ascii')
            if state != 'start' or hypervisor == current_hypervisor:
                continue

            memfree = int(zk.get('/nodes/{}/memfree'.format(hypervisor))[0].decode('ascii'))
            if memfree > most_memfree:
                most_memfree = memfree
                target_hypervisor = hypervisor
    else:
        if target_hypervisor == current_hypervisor:
            click.echo('ERROR: The VM "{}" is already running on hypervisor "{}".'.format(dom_uuid, current_hypervisor))
            return

    current_vm_state = zk.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_vm_state == 'start':
        click.echo('Permanently migrating VM "{}" to hypervisor "{}".'.format(dom_uuid, target_hypervisor))
        transaction = zk.transaction()
        transaction.set_data('/domains/{}/state'.format(dom_uuid), 'migrate'.encode('ascii'))
        transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
        transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), ''.encode('ascii'))
        transaction.commit()
    else:
        click.echo('Permanently moving VM "{}" to hypervisor "{}".'.format(dom_uuid, target_hypervisor))
        transaction = zk.transaction()
        transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
        transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), ''.encode('ascii'))
        transaction.commit()

    # Close the Zookeeper connection
    stopZKConnection(zk)


###############################################################################
# pvc vm migrate
###############################################################################
@click.command(name='migrate', short_help='Migrate a virtual machine to another node.')
@click.option(
    '-n', '--name', 'dom_name',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_uuid', 'argument': '--uuid' }],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_name', 'argument': '--name' }],
    help='Search for this UUID.'
)
@click.option(
    '-t', '--target', 'target_hypervisor', default=None,
    help='The target hypervisor to migrate to.'
)
@click.option(
    '-f', '--force', 'force_migrate', is_flag=True, default=False,
    help='Force migrate an already migrated VM.'
)
def migrate_vm(dom_name, dom_uuid, target_hypervisor, force_migrate):
    """
    Migrate a running virtual machine, via live migration if possible, to another hypervisor node.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("ERROR: You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = searchClusterByName(zk, dom_name)

    # Verify we got a result or abort
    if not validateUUID(dom_uuid):
        if dom_name != None:
            message_name = dom_name
        else:
            message_name = dom_uuid
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(message_name))
        return

    # Get state and verify we're OK to proceed
    current_state = zk.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_state != 'start':
        click.echo('ERROR: The VM "{}" is not in "start" state!'.format(dom_uuid))
        return

    current_hypervisor = zk.get('/domains/{}/hypervisor'.format(dom_uuid))[0].decode('ascii')
    last_hypervisor = zk.get('/domains/{}/lasthypervisor'.format(dom_uuid))[0].decode('ascii')

    if last_hypervisor != '' and force_migrate != True:
        click.echo('ERROR: The VM "{}" has been previously migrated.'.format(dom_uuid))
        click.echo('> Last hypervisor: {}'.format(last_hypervisor))
        click.echo('> Current hypervisor: {}'.format(current_hypervisor))
        click.echo('Run `vm unmigrate` to restore the VM to its previous hypervisor, or use `--force` to override this check.')
        return

    if target_hypervisor == None:
        # Determine the best hypervisor to migrate the VM to based on active memory usage
        hypervisor_list = zk.get_children('/nodes')
        most_memfree = 0
        for hypervisor in hypervisor_list:
            daemon_state = zk.get('/nodes/{}/daemonstate'.format(hypervisor))[0].decode('ascii')
            domain_state = zk.get('/nodes/{}/domainstate'.format(hypervisor))[0].decode('ascii')
            if daemon_state != 'run' or domain_state != 'ready' or hypervisor == current_hypervisor:
                continue

            memfree = int(zk.get('/nodes/{}/memfree'.format(hypervisor))[0].decode('ascii'))
            if memfree > most_memfree:
                most_memfree = memfree
                target_hypervisor = hypervisor
    else:
        if target_hypervisor == current_hypervisor:
            click.echo('ERROR: The VM "{}" is already running on hypervisor "{}".'.format(dom_uuid, current_hypervisor))
            return

    click.echo('Migrating VM "{}" to hypervisor "{}".'.format(dom_uuid, target_hypervisor))
    transaction = zk.transaction()
    transaction.set_data('/domains/{}/state'.format(dom_uuid), 'migrate'.encode('ascii'))
    transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
    transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), current_hypervisor.encode('ascii'))
    transaction.commit()

    # Close the Zookeeper connection
    stopZKConnection(zk)


###############################################################################
# pvc vm unmigrate
###############################################################################
@click.command(name='unmigrate', short_help='Restore a migrated virtual machine to its original node.')
@click.option(
    '-n', '--name', 'dom_name',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_uuid', 'argument': '--uuid' }],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_name', 'argument': '--name' }],
    help='Search for this UUID.'
)
def unmigrate_vm(dom_name, dom_uuid):
    """
    Restore a previously migrated virtual machine, via live migration if possible, to its original hypervisor node.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("ERROR: You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = searchClusterByName(zk, dom_name)

    # Verify we got a result or abort
    if not validateUUID(dom_uuid):
        if dom_name != None:
            message_name = dom_name
        else:
            message_name = dom_uuid
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(message_name))
        return

    # Get state and verify we're OK to proceed
    current_state = zk.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_state != 'start':
        click.echo('ERROR: The VM "{}" is not in "start" state!'.format(dom_uuid))
        return

    target_hypervisor = zk.get('/domains/{}/lasthypervisor'.format(dom_uuid))[0].decode('ascii')

    if target_hypervisor == '':
        click.echo('ERROR: The VM "{}" has not been previously migrated.'.format(dom_uuid))
        return

    click.echo('Unmigrating VM "{}" back to hypervisor "{}".'.format(dom_uuid, target_hypervisor))
    transaction = zk.transaction()
    transaction.set_data('/domains/{}/state'.format(dom_uuid), 'migrate'.encode('ascii'))
    transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
    transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), ''.encode('ascii'))
    transaction.commit()

    # Close the Zookeeper connection
    stopZKConnection(zk)


###############################################################################
# pvc vm info
###############################################################################
@click.command(name='info', short_help='Show details of a VM object')
@click.option(
    '-n', '--name', 'dom_name',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_uuid', 'argument': '--uuid' }],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_name', 'argument': '--name' }],
    help='Search for this UUID.'
)
@click.option(
    '-l', '--long', 'long_output', is_flag=True, default=False,
    help='Display more detailed information.'
)
def vm_info(dom_name, dom_uuid, long_output):
    """
    Search the cluster for a virtual machine's information.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("ERROR: You must specify either a `--name` or `--uuid` value.")
        return

    zk = startZKConnection(zk_host)
    if dom_name != None:
        dom_uuid = searchClusterByName(zk, dom_name)
    if dom_uuid != None:
        dom_name = searchClusterByUUID(zk, dom_uuid)

    information = getInformationFromXML(zk, dom_uuid, long_output)

    if information == None:
        click.echo('ERROR: Could not find a domain matching that name or UUID.')
        return

    click.echo(information)
    stopZKConnection(zk)


###############################################################################
# pvc vm list
###############################################################################
@click.command(name='list', short_help='List all VM objects')
@click.option(
    '-t', '--hypervisor', 'hypervisor', default=None,
    help='Limit list to this hypervisor.'
)
def vm_list(hypervisor):
    _vm_list(hypervisor)

# Wrapped function to allow calling from `node info`
def _vm_list(hypervisor):
    """
    List all virtual machines in the cluster.
    """

    # Open a Zookeeper connection
    zk = startZKConnection(zk_host)

    vm_list_raw = zk.get_children('/domains')
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
        vm_hypervisor[vm] = zk.get('/domains/{}/hypervisor'.format(vm))[0].decode('ascii')
        if hypervisor != None:
            if vm_hypervisor[vm] == hypervisor:
                vm_list.append(vm)
        else:
            vm_list.append(vm)

    # Gather information for printing
    for vm in vm_list:
        vm_state[vm] = zk.get('/domains/{}/state'.format(vm))[0].decode('ascii')
        vm_lasthypervisor = zk.get('/domains/{}/lasthypervisor'.format(vm))[0].decode('ascii')
        if vm_lasthypervisor != '':
            vm_migrated[vm] = 'from {}'.format(vm_lasthypervisor)
        else:
            vm_migrated[vm] = 'no'

        vm_xml = getDomainXML(zk, vm)
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
    stopZKConnection(zk)


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
    zk = startZKConnection(zk_host)

    # Destroy the existing data
    try:
        zk.delete('/domains', recursive=True)
        zk.delete('nodes', recursive=True)
    except:
        pass

    # Create the root keys
    transaction = zk.transaction()
    transaction.create('/domains', ''.encode('ascii'))
    transaction.create('/nodes', ''.encode('ascii'))
    transaction.commit()

    # Close the Zookeeper connection
    stopZKConnection(zk)

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
    """

    global zk_host
    zk_host = _zk_host


#
# Click command tree
#
node.add_command(flush_host)
node.add_command(ready_host)
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

