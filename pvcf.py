#!/usr/bin/env python3

import os, sys, libvirt, uuid
import kazoo.client
import lxml
import click
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
def getInformationFromXML(zk, uuid):
    # Obtain the contents of the XML from Zookeeper
    xml = zk.get('/domains/%s/xml' % uuid)[0].decode('ascii')
    # Parse XML using lxml.objectify
    parsed_xml = lxml.objectify.fromstring(xml)
    # Now get the information we want from it
    dmemory = parsed_xml.memory
    dmemory_unit = parsed_xml.memory.attrib['unit']
    dcurrentMemory = parsed_xml.currentMemory
    dcurrentMemory_unit = parsed_xml.currentMemory.attrib['unit']
    dvcpu = parsed_xml.vcpu
    dtype = parsed_xml.os.type
    darch = parsed_xml.os.type.attrib['arch']
    dmachine = parsed_xml.os.type.attrib['machine']
    dfeatures = []
    for feature in parsed_xml.features.getchildren():
        dfeatures.append(feature.tag)
    ddisks = []
    for disk in parsed_xml.devices.disk.getchildren():
        ddisks.append(disk.attrib)

    print(ddisks)
    return None



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
