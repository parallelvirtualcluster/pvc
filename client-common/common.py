#!/usr/bin/env python3

# common.py - PVC client function library, common fuctions
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

import uuid
import lxml
import kazoo.client

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
# Parse a Domain XML object
#
def getDomainXML(zk_conn, dom_uuid):
    try:
        xml = zk_conn.get('/domains/%s/xml' % dom_uuid)[0].decode('ascii')
    except:
        return None
    
    # Parse XML using lxml.objectify
    parsed_xml = lxml.objectify.fromstring(xml)
    return parsed_xml

#
# Get the main details for a VM object from XML
#
def getDomainMainDetails(parsed_xml):
    # Get the information we want from it
    duuid = str(parsed_xml.uuid)
    try:
        ddescription = str(parsed_xml.description)
    except AttributeError:
        ddescription = "N/A"
    dname = str(parsed_xml.name)
    dmemory = str(parsed_xml.memory)
    dmemory_unit = str(parsed_xml.memory.attrib['unit'])
    if dmemory_unit == 'KiB':
        dmemory = int(int(dmemory) / 1024)
    elif dmemory_unit == 'GiB':
        dmemory = int(int(dmemory) * 1024)
    dvcpu = str(parsed_xml.vcpu)
    try:
        dvcputopo = '{}/{}/{}'.format(parsed_xml.cpu.topology.attrib['sockets'], parsed_xml.cpu.topology.attrib['cores'], parsed_xml.cpu.topology.attrib['threads'])
    except:
        dvcputopo = 'N/A'

    return duuid, dname, ddescription, dmemory, dvcpu, dvcputopo

#
# Get long-format details
#
def getDomainExtraDetails(parsed_xml):
    dtype = parsed_xml.os.type
    darch = parsed_xml.os.type.attrib['arch']
    dmachine = parsed_xml.os.type.attrib['machine']
    dconsole = parsed_xml.devices.console.attrib['type']
    demulator = parsed_xml.devices.emulator

    return dtype, darch, dmachine, dconsole, demulator

#
# Get CPU features
#
def getDomainCPUFeatures(parsed_xml):
    dfeatures = []
    for feature in parsed_xml.features.getchildren():
        dfeatures.append(feature.tag)

    return dfeatures

#
# Get disk devices
#
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

#
# Get network devices
#
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

#
# Get controller devices
#
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

#
# Verify node is valid in cluster
#
def verifyNode(zk_conn, node):
    try:
        zk_conn.get('/nodes/{}'.format(node))
        return True
    except:
        return False
#
# Verify router is valid in cluster
#
def verifyRouter(zk_conn, router):
    try:
        zk_conn.get('/routers/{}'.format(router))
        return True
    except:
        return False


#
# Get the list of valid target nodes
#
def getNodes(zk_conn, dom_uuid):
    valid_node_list = []
    full_node_list = zk_conn.get_children('/nodes')

    try:
        current_node = zk_conn.get('/domains/{}/node'.format(dom_uuid))[0].decode('ascii')
    except:
        current_node = None

    for node in full_node_list:
        daemon_state = zk_conn.get('/nodes/{}/daemonstate'.format(node))[0].decode('ascii')
        domain_state = zk_conn.get('/nodes/{}/domainstate'.format(node))[0].decode('ascii')

        if node == current_node:
            continue

        if daemon_state != 'run' or domain_state != 'ready':
            continue

        valid_node_list.append(node)

    return valid_node_list
    
#
# Find a migration target
#
def findTargetNode(zk_conn, search_field, dom_uuid):
    if search_field == 'mem':
        return findTargetNodeMem(zk_conn, dom_uuid)
    if search_field == 'load':
        return findTargetNodeLoad(zk_conn, dom_uuid)
    if search_field == 'vcpus':
        return findTargetNodeVCPUs(zk_conn, dom_uuid)
    if search_field == 'vms':
        return findTargetNodeVMs(zk_conn, dom_uuid)
    return None

# via free memory (relative to allocated memory)
def findTargetNodeMem(zk_conn, dom_uuid):
    most_allocfree = 0
    target_node = None

    node_list = getNodes(zk_conn, dom_uuid)
    for node in node_list:
        memalloc = int(zk_conn.get('/nodes/{}/memalloc'.format(node))[0].decode('ascii'))
        memused = int(zk_conn.get('/nodes/{}/memused'.format(node))[0].decode('ascii'))
        memfree = int(zk_conn.get('/nodes/{}/memfree'.format(node))[0].decode('ascii'))
        memtotal = memused + memfree
        allocfree = memtotal - memalloc

        if allocfree > most_allocfree:
            most_allocfree = allocfree
            target_node = node

    return target_node

# via load average
def findTargetNodeLoad(zk_conn, dom_uuid):
    least_load = 9999
    target_node = None

    node_list = getNodes(zk_conn, dom_uuid)
    for node in node_list:
        load = float(zk_conn.get('/nodes/{}/cpuload'.format(node))[0].decode('ascii'))

        if load < least_load:
            least_load = load
            target_node = node

    return target_node

# via total vCPUs
def findTargetNodeVCPUs(zk_conn, dom_uuid):
    least_vcpus = 9999
    target_node = None

    node_list = getNodes(zk_conn, dom_uuid)
    for node in node_list:
        vcpus = int(zk_conn.get('/nodes/{}/vcpualloc'.format(node))[0].decode('ascii'))

        if vcpus < least_vcpus:
            least_vcpus = vcpus
            target_node = node

    return target_node

# via total VMs
def findTargetNodeVMs(zk_conn, dom_uuid):
    least_vms = 9999
    target_node = None

    node_list = getNodes(zk_conn, dom_uuid)
    for node in node_list:
        vms = int(zk_conn.get('/nodes/{}/domainscount'.format(node))[0].decode('ascii'))

        if vms < least_vms:
            least_vms = vms
            target_node = node

    return target_node

