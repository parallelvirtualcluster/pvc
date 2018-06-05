#!/usr/bin/env python3

import os, sys, libvirt, uuid
import kazoo.client
import lxml
import click
import operator
#from click import command, option, Option, UsageError

#
# Generic function helpers for PVC
#

# > lookupByUUID
# This function is a wrapper for libvirt.lookupByUUID which fixes some problems
# 1. Takes a text UUID and handles converting it to bytes
# 2. Try's it and returns a sensible value if not
def lookupByUUID(tuuid):
    conn = None
    dom = None
    libvirt_name = "qemu:///system"

    # Convert the text UUID to bytes
    buuid = uuid.UUID(tuuid).bytes

    # Try
    try:
        # Open a libvirt connection
        conn = libvirt.open(libvirt_name)
        if conn == None:
            print('>>> %s - Failed to open local libvirt connection.' % self.domuuid)
            return dom
    
        # Lookup the UUID
        dom = conn.lookupByUUID(buuid)

    # Fail
    except:
        pass

    # After everything
    finally:
        # Close the libvirt connection
        if conn != None:
            conn.close()

    # Return the dom object (or None)
    return dom


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
    xml = zk.get('/domains/%s/xml' % uuid)[0].decode('ascii')
    dstate = zk.get('/domains/%s/state' % uuid)[0].decode('ascii')
    dhypervisor = zk.get('/domains/%s/hypervisor' % uuid)[0].decode('ascii')
    dformerhypervisor = zk.get('/domains/%s/formerhypervisor' % uuid)[0].decode('ascii')
    if dformerhypervisor == '':
        dformerhypervisor = 'N/A'

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
    ainformation.append('Virtual machine information:')
    ainformation.append('')
    # Basic information
    ainformation.append('UUID:               {}'.format(duuid))
    ainformation.append('Name:               {}'.format(dname))
    ainformation.append('Memory:             {} {}'.format(dmemory, dmemory_unit))
    ainformation.append('vCPUs:              {}'.format(dvcpu))
    ainformation.append('Topology [S/C/T]:   {}'.format(dvcputopo))

    if long_output == True:
        # Virtualization information
        ainformation.append('')
        ainformation.append('Emulator:           {}'.format(demulator))
        ainformation.append('Type:               {}'.format(dtype))
        ainformation.append('Arch:               {}'.format(darch))
        ainformation.append('Machine:            {}'.format(dmachine))
        ainformation.append('Features:           {}'.format(' '.join(dfeatures)))

    # PVC cluster information
    ainformation.append('')
    ainformation.append('State:              {}'.format(dstate))
    ainformation.append('Active Hypervisor:  {}'.format(dhypervisor))
    ainformation.append('Former Hypervisor:  {}'.format(dformerhypervisor))

    if long_output == True:
        # Disk list
        ainformation.append('')
        ainformation.append('Disks:        ID  Type  Name                 Dev  Bus')
        for disk in ddisks:
            ainformation.append('              {0: <3} {1: <5} {2: <20} {3: <4} {4: <5}'.format(ddisks.index(disk), disk['type'], disk['name'], disk['dev'], disk['bus']))
        # Network list
        ainformation.append('')
        ainformation.append('Interfaces:   ID  Type     Source   Model    MAC')
        for net in dnets:
            ainformation.append('              {0: <3} {1: <8} {2: <8} {3: <8} {4: <17}'.format(dnets.index(net), net['type'], net['source'], net['model'], net['mac']))
        # Controller list
        ainformation.append('')
        ainformation.append('Controllers:  ID  Type     Model')
        for controller in dcontrollers:
            ainformation.append('              {0: <3} {1: <8} {2: <8}'.format(dcontrollers.index(controller), controller['type'], controller['model']))

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
        return None, None

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
        return None, None

    return uuid


#
# Allow mutually exclusive options in Click
#
class MutuallyExclusiveOption(click.Option):
    def __init__(self, *args, **kwargs):
        self.mutually_exclusive = set(kwargs.pop('mutually_exclusive', []))
        help = kwargs.get('help', '')
        if self.mutually_exclusive:
            ex_str = ', '.join(self.mutually_exclusive)
            kwargs['help'] = help + (
                ' NOTE: This argument is mutually exclusive with '
                'arguments: [' + ex_str + '].'
            )
        super(MutuallyExclusiveOption, self).__init__(*args, **kwargs)

    def handle_parse_result(self, ctx, opts, args):
        if self.mutually_exclusive.intersection(opts) and self.name in opts:
            raise click.UsageError(
                "Illegal usage: `{}` is mutually exclusive with "
                "arguments `{}`.".format(
                    self.name,
                    ', '.join(self.mutually_exclusive)
                )
            )

        return super(MutuallyExclusiveOption, self).handle_parse_result(
            ctx,
            opts,
            args
        )
