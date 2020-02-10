#!/usr/bin/env python3

# common.py - PVC client function library, common fuctions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2020 Joshua M. Boniface <joshua@boniface.me>
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
import math
import shlex
import subprocess
import kazoo.client

from distutils.util import strtobool

import daemon_lib.zkhandler as zkhandler

###############################################################################
# Supplemental functions
###############################################################################

#
# Run a local OS command via shell
#
def run_os_command(command_string, background=False, environment=None, timeout=None, shell=False):
    command = shlex.split(command_string)
    try:
        command_output = subprocess.run(
            command,
            shell=shell,
            env=environment,
            timeout=timeout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        retcode = command_output.returncode
    except subprocess.TimeoutExpired:
        retcode = 128

    try:
        stdout = command_output.stdout.decode('ascii')
    except:
        stdout = ''
    try:
        stderr = command_output.stderr.decode('ascii')
    except:
        stderr = ''
    return retcode, stdout, stderr

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
    try:
        zk_conn.start()
    except kazoo.handlers.threading.KazooTimeoutError:
        print('Timed out connecting to Zookeeper at "{}".'.format(zk_host))
        exit(1)
    except Exception as e:
        print('Failed to connect to Zookeeper at "{}": {}'.format(zk_host, e))
        exit(1)
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
        xml = zkhandler.readdata(zk_conn, '/domains/{}/xml'.format(dom_uuid))
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
    dtype = str(parsed_xml.os.type)
    darch = str(parsed_xml.os.type.attrib['arch'])
    dmachine = str(parsed_xml.os.type.attrib['machine'])
    dconsole = str(parsed_xml.devices.console.attrib['type'])
    demulator = str(parsed_xml.devices.emulator)

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
# Get a list of disk devices
#
def getDomainDiskList(zk_conn, dom_uuid):
    domain_information = getInformationFromXML(zk_conn, dom_uuid)
    disk_list = []
    for disk in domain_information['disks']:
        disk_list.append(disk['name'])
       
    return disk_list

#
# Get domain information from XML
#
def getInformationFromXML(zk_conn, uuid):
    """
    Gather information about a VM from the Libvirt XML configuration in the Zookeper database
    and return a dict() containing it.
    """
    domain_state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(uuid))
    domain_node = zkhandler.readdata(zk_conn, '/domains/{}/node'.format(uuid))
    domain_lastnode = zkhandler.readdata(zk_conn, '/domains/{}/lastnode'.format(uuid))
    domain_failedreason = zkhandler.readdata(zk_conn, '/domains/{}/failedreason'.format(uuid))

    try:
        domain_node_limit = zkhandler.readdata(zk_conn, '/domains/{}/node_limit'.format(uuid))
    except:
        domain_node_limit = None
    try:
        domain_node_selector = zkhandler.readdata(zk_conn, '/domains/{}/node_selector'.format(uuid))
    except:
        domain_node_selector = None
    try:
        domain_node_autostart = zkhandler.readdata(zk_conn, '/domains/{}/node_autostart'.format(uuid))
    except:
        domain_node_autostart = None

    if not domain_node_limit:
        domain_node_limit = None
    else:
        domain_node_limit = domain_node_limit.split(',')

    if not domain_node_autostart:
        domain_node_autostart = None

    try:
        domain_profile = zkhandler.readdata(zk_conn, '/domains/{}/profile'.format(uuid))
    except:
        domain_profile = None

    parsed_xml = getDomainXML(zk_conn, uuid)

    domain_uuid, domain_name, domain_description, domain_memory, domain_vcpu, domain_vcputopo = getDomainMainDetails(parsed_xml)
    domain_networks = getDomainNetworks(parsed_xml)

    domain_type, domain_arch, domain_machine, domain_console, domain_emulator = getDomainExtraDetails(parsed_xml)

    domain_features = getDomainCPUFeatures(parsed_xml)
    domain_disks = getDomainDisks(parsed_xml)
    domain_controllers = getDomainControllers(parsed_xml)
    
    if domain_lastnode:
        domain_migrated = 'from {}'.format(domain_lastnode)
    else:
        domain_migrated = 'no'

    domain_information = {
        'name': domain_name,
        'uuid': domain_uuid,
        'state': domain_state,
        'node': domain_node,
        'last_node': domain_lastnode,
        'migrated': domain_migrated,
        'failed_reason': domain_failedreason,
        'node_limit': domain_node_limit,
        'node_selector': domain_node_selector,
        'node_autostart': bool(strtobool(domain_node_autostart)),
        'description': domain_description,
        'profile': domain_profile,
        'memory': int(domain_memory),
        'vcpu': int(domain_vcpu),
        'vcpu_topology': domain_vcputopo,
        'networks': domain_networks,
        'type': domain_type,
        'arch': domain_arch,
        'machine': domain_machine,
        'console': domain_console,
        'emulator': domain_emulator,
        'features': domain_features,
        'disks': domain_disks,
        'controllers': domain_controllers,
        'xml': lxml.etree.tostring(parsed_xml, encoding='ascii', method='xml').decode().replace('\"', '\'')
    }

    return domain_information

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
    if zkhandler.exists(zk_conn, '/nodes/{}'.format(node)):
        return True
    else:
        return False

#
# Get the primary coordinator node
#
def getPrimaryNode(zk_conn):
    failcount = 0
    while True:
        try:
            primary_node = zkhandler.readdata(zk_conn, '/primary_node')
        except:
            primary_node == 'none'

        if primary_node == 'none':
            raise
            time.sleep(1)
            failcount += 1
            continue
        else:
            break

        if failcount > 2:
            return None

    return primary_node

#
# Find a migration target
#
def findTargetNode(zk_conn, dom_uuid):
    # Determine VM node limits; set config value if read fails
    try:
        node_limit = zkhandler.readdata(zk_conn, '/domains/{}/node_limit'.format(dom_uuid)).split(',')
        if not any(node_limit):
            node_limit = None
    except:
        node_limit = None

    # Determine VM search field or use default; set config value if read fails
    try:
        search_field = zkhandler.readdata(zk_conn, '/domains/{}/node_selector'.format(dom_uuid))
    except:
        search_field = 'mem'

    # Execute the search
    if search_field == 'mem':
        return findTargetNodeMem(zk_conn, node_limit, dom_uuid)
    if search_field == 'load':
        return findTargetNodeLoad(zk_conn, node_limit, dom_uuid)
    if search_field == 'vcpus':
        return findTargetNodeVCPUs(zk_conn, node_limit, dom_uuid)
    if search_field == 'vms':
        return findTargetNodeVMs(zk_conn, node_limit, dom_uuid)

    # Nothing was found
    return None

# Get the list of valid target nodes
def getNodes(zk_conn, node_limit, dom_uuid):
    valid_node_list = []
    full_node_list = zkhandler.listchildren(zk_conn, '/nodes')
    try:
        current_node = zkhandler.readdata(zk_conn, '/domains/{}/node'.format(dom_uuid))
    except kazoo.exceptions.NoNodeError:
        current_node = None

    for node in full_node_list:
        if node_limit and node not in node_limit:
            continue

        daemon_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(node))
        domain_state = zkhandler.readdata(zk_conn, '/nodes/{}/domainstate'.format(node))

        if node == current_node:
            continue

        if daemon_state != 'run' or domain_state != 'ready':
            continue

        valid_node_list.append(node)

    return valid_node_list

# via free memory (relative to allocated memory)
def findTargetNodeMem(zk_conn, node_limit, dom_uuid):
    most_allocfree = 0
    target_node = None

    node_list = getNodes(zk_conn, node_limit, dom_uuid)
    for node in node_list:
        memalloc = int(zkhandler.readdata(zk_conn, '/nodes/{}/memalloc'.format(node)))
        memused = int(zkhandler.readdata(zk_conn, '/nodes/{}/memused'.format(node)))
        memfree = int(zkhandler.readdata(zk_conn, '/nodes/{}/memfree'.format(node)))
        memtotal = memused + memfree
        allocfree = memtotal - memalloc

        if allocfree > most_allocfree:
            most_allocfree = allocfree
            target_node = node

    return target_node

# via load average
def findTargetNodeLoad(zk_conn, node_limit, dom_uuid):
    least_load = 9999.0
    target_node = None

    node_list = getNodes(zk_conn, node_limit, dom_uuid)
    for node in node_list:
        load = float(zkhandler.readdata(zk_conn, '/nodes/{}/cpuload'.format(node)))

        if load < least_load:
            least_load = load
            target_node = node

    return target_node

# via total vCPUs
def findTargetNodeVCPUs(zk_conn, node_limit, dom_uuid):
    least_vcpus = 9999
    target_node = None

    node_list = getNodes(zk_conn, node_limit, dom_uuid)
    for node in node_list:
        vcpus = int(zkhandler.readdata(zk_conn, '/nodes/{}/vcpualloc'.format(node)))

        if vcpus < least_vcpus:
            least_vcpus = vcpus
            target_node = node

    return target_node

# via total VMs
def findTargetNodeVMs(zk_conn, node_limit, dom_uuid):
    least_vms = 9999
    target_node = None

    node_list = getNodes(zk_conn, node_limit, dom_uuid)
    for node in node_list:
        vms = int(zkhandler.readdata(zk_conn, '/nodes/{}/domainscount'.format(node)))

        if vms < least_vms:
            least_vms = vms
            target_node = node

    return target_node

# Connect to the primary host and run a command
def runRemoteCommand(node, command, become=False):
    import paramiko
    import hashlib
    import dns.resolver
    import dns.flags

    # Support doing SSHFP checks
    class DnssecPolicy(paramiko.client.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            sshfp_expect = hashlib.sha1(key.asbytes()).hexdigest()
            ans = dns.resolver.query(hostname, 'SSHFP')
            if not ans.response.flags & dns.flags.DO:
                raise AssertionError('Answer is not DNSSEC signed')
            for answer in ans.response.answer:
                for item in answer.items:
                    if sshfp_expect in item.to_text():
                        client._log(paramiko.common.DEBUG, 'Found {} in SSHFP for host {}'.format(key.get_name(), hostname))
                        return
            raise AssertionError('SSHFP not published in DNS')

    if become:
        command = 'sudo ' + command

    ssh_client = paramiko.client.SSHClient()
    ssh_client.load_system_host_keys()
    ssh_client.set_missing_host_key_policy(DnssecPolicy())
    #ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_client.connect(node)
    stdin, stdout, stderr = ssh_client.exec_command(command)
    return stdout.read().decode('ascii').rstrip(), stderr.read().decode('ascii').rstrip()
