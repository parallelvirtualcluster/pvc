#!/usr/bin/env python3

# pvcf.py - Supplemental functions for the PVC CLI client
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

import os, sys, libvirt, uuid, kazoo.client, lxml.objectify, click, ansiiprint

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
    ainformation.append('{}Memory [MiB]:{}       {}'.format(ansiiprint.purple(), ansiiprint.end(), dmemory))
    ainformation.append('{}vCPUs:{}              {}'.format(ansiiprint.purple(), ansiiprint.end(), dvcpu))
    ainformation.append('{}Topology [S/C/T]:{}   {}'.format(ansiiprint.purple(), ansiiprint.end(), dvcputopo))

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
        'stop': ansiiprint.red(),
        'shutdown': ansiiprint.yellow(),
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
