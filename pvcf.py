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
def getInformationFromXML(zk, uuid, long_output):
    # Obtain the contents of the XML from Zookeeper
    try:
        xml = zk.get('/domains/%s/xml' % uuid)[0].decode('ascii')
        dstate = zk.get('/domains/%s/state' % uuid)[0].decode('ascii')
        dhypervisor = zk.get('/domains/%s/hypervisor' % uuid)[0].decode('ascii')
        dlasthypervisor = zk.get('/domains/%s/lasthypervisor' % uuid)[0].decode('ascii')
    except:
        return None

    if dlasthypervisor == '':
        dlasthypervisor = 'N/A'

    # Parse XML using lxml.objectify
    parsed_xml = lxml.objectify.fromstring(xml)

    # Get the information we want from it
    duuid = parsed_xml.uuid
    dname = parsed_xml.name
    dmemory = parsed_xml.memory
    dmemory_unit = parsed_xml.memory.attrib['unit']
    dvcpu = parsed_xml.vcpu
    try:
        dvcputopo = '{}/{}/{}'.format(parsed_xml.cpu.topology.attrib['sockets'], parsed_xml.cpu.topology.attrib['cores'], parsed_xml.cpu.topology.attrib['threads'])
    except:
        dvcputopo = 'N/A'
    dtype = parsed_xml.os.type
    darch = parsed_xml.os.type.attrib['arch']
    dmachine = parsed_xml.os.type.attrib['machine']
    dfeatures = []
    for feature in parsed_xml.features.getchildren():
        dfeatures.append(feature.tag)
    dconsole = parsed_xml.devices.console.attrib['type']
    demulator = parsed_xml.devices.emulator
    ddisks = []
    dnets = []
    dcontrollers = []
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
        if device.tag == 'interface':
            net_type = device.attrib['type']
            net_mac = device.mac.attrib['address']
            net_bridge = device.source.attrib[net_type]
            net_model = device.model.attrib['type']
            net_obj = { 'type': net_type, 'mac': net_mac, 'source': net_bridge, 'model': net_model }
            dnets.append(net_obj)
        if device.tag == 'controller':
            controller_type = device.attrib['type']
            try:
                controller_model = device.attrib['model']
            except KeyError:
                controller_model = 'none'
            controller_obj = { 'type': controller_type, 'model': controller_model }
            dcontrollers.append(controller_obj)

    # Format a nice output; do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append('{}Virtual machine information:{}'.format(ansiiprint.bold(), ansiiprint.end()))
    ainformation.append('')
    # Basic information
    ainformation.append('{}UUID:{}               {}'.format(ansiiprint.purple(), ansiiprint.end(), duuid))
    ainformation.append('{}Name:{}               {}'.format(ansiiprint.purple(), ansiiprint.end(), dname))
    ainformation.append('{}Memory:{}             {} {}'.format(ansiiprint.purple(), ansiiprint.end(), dmemory, dmemory_unit))
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
