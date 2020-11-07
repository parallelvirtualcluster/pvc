#!/usr/bin/env python3

# vm.py - PVC client function library, VM fuctions
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

import time
import re
import lxml.objectify

import daemon_lib.ansiprint as ansiprint
import daemon_lib.zkhandler as zkhandler
import daemon_lib.common as common

import daemon_lib.ceph as ceph

#
# Cluster search functions
#
def getClusterDomainList(zk_conn):
    # Get a list of UUIDs by listing the children of /domains
    uuid_list = zkhandler.listchildren(zk_conn, '/domains')
    name_list = []
    # For each UUID, get the corresponding name from the data
    for uuid in uuid_list:
        name_list.append(zkhandler.readdata(zk_conn, '/domains/%s' % uuid))
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
    # Validate that VM exists in cluster
    if common.validateUUID(domain):
        dom_name = searchClusterByUUID(zk_conn, domain)
        dom_uuid = searchClusterByName(zk_conn, dom_name)
    else:
        dom_uuid = searchClusterByName(zk_conn, domain)
        dom_name = searchClusterByUUID(zk_conn, dom_uuid)

    return dom_uuid

def getDomainName(zk_conn, domain):
    # Validate that VM exists in cluster
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
def is_migrated(zk_conn, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    last_node = zkhandler.readdata(zk_conn, '/domains/{}/lastnode'.format(dom_uuid))
    if last_node:
        return True
    else:
        return False

def flush_locks(zk_conn, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Verify that the VM is in a stopped state; freeing locks is not safe otherwise
    state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid))
    if state != 'stop':
        return False, 'ERROR: VM "{}" is not in stopped state; flushing RBD locks on a running VM is dangerous.'.format(domain)

    # Tell the cluster to create a new OSD for the host
    flush_locks_string = 'flush_locks {}'.format(dom_uuid)
    zkhandler.writedata(zk_conn, {'/cmd/domains': flush_locks_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/cmd/domains')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/cmd/domains').split()[0]
            if result == 'success-flush_locks':
                message = 'Flushed locks on VM "{}"'.format(domain)
                success = True
            else:
                message = 'ERROR: Failed to flush locks on VM "{}"; check node logs for details.'.format(domain)
                success = False
        except Exception:
            message = 'ERROR: Command ignored by node.'
            success = False

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/cmd/domains')
    with lock:
        time.sleep(0.5)
        zkhandler.writedata(zk_conn, {'/cmd/domains': ''})

    return success, message

def define_vm(zk_conn, config_data, target_node, node_limit, node_selector, node_autostart, migration_method=None, profile=None, initial_state='stop'):
    # Parse the XML data
    try:
        parsed_xml = lxml.objectify.fromstring(config_data)
    except Exception:
        return False, 'ERROR: Failed to parse XML data.'
    dom_uuid = parsed_xml.uuid.text
    dom_name = parsed_xml.name.text

    # Ensure that the UUID and name are unique
    if searchClusterByUUID(zk_conn, dom_uuid) or searchClusterByName(zk_conn, dom_name):
        return False, 'ERROR: Specified VM "{}" or UUID "{}" matches an existing VM on the cluster'.format(dom_name, dom_uuid)

    if not target_node:
        target_node = common.findTargetNode(zk_conn, dom_uuid)
    else:
        # Verify node is valid
        valid_node = common.verifyNode(zk_conn, target_node)
        if not valid_node:
            return False, 'ERROR: Specified node "{}" is invalid.'.format(target_node)

    # Obtain the RBD disk list using the common functions
    ddisks = common.getDomainDisks(parsed_xml, {})
    rbd_list = []
    for disk in ddisks:
        if disk['type'] == 'rbd':
            rbd_list.append(disk['name'])

    # Join the limit
    if isinstance(node_limit, list) and node_limit:
        formatted_node_limit = ','.join(node_limit)
    else:
        formatted_node_limit = ''

    # Join the RBD list
    if isinstance(rbd_list, list) and rbd_list:
        formatted_rbd_list = ','.join(rbd_list)
    else:
        formatted_rbd_list = ''

    # Add the new domain to Zookeeper
    zkhandler.writedata(zk_conn, {
        '/domains/{}'.format(dom_uuid): dom_name,
        '/domains/{}/state'.format(dom_uuid): initial_state,
        '/domains/{}/node'.format(dom_uuid): target_node,
        '/domains/{}/lastnode'.format(dom_uuid): '',
        '/domains/{}/node_limit'.format(dom_uuid): formatted_node_limit,
        '/domains/{}/node_selector'.format(dom_uuid): node_selector,
        '/domains/{}/node_autostart'.format(dom_uuid): node_autostart,
        '/domains/{}/migration_method'.format(dom_uuid): migration_method,
        '/domains/{}/failedreason'.format(dom_uuid): '',
        '/domains/{}/consolelog'.format(dom_uuid): '',
        '/domains/{}/rbdlist'.format(dom_uuid): formatted_rbd_list,
        '/domains/{}/profile'.format(dom_uuid): profile,
        '/domains/{}/xml'.format(dom_uuid): config_data
    })

    return True, 'Added new VM with Name "{}" and UUID "{}" to database.'.format(dom_name, dom_uuid)

def modify_vm_metadata(zk_conn, domain, node_limit, node_selector, node_autostart, provisioner_profile, migration_method):
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    if node_limit is not None:
        zkhandler.writedata(zk_conn, {
            '/domains/{}/node_limit'.format(dom_uuid): node_limit
        })

    if node_selector is not None:
        zkhandler.writedata(zk_conn, {
            '/domains/{}/node_selector'.format(dom_uuid): node_selector
        })

    if node_autostart is not None:
        zkhandler.writedata(zk_conn, {
            '/domains/{}/node_autostart'.format(dom_uuid): node_autostart
        })

    if provisioner_profile is not None:
        zkhandler.writedata(zk_conn, {
            '/domains/{}/profile'.format(dom_uuid): provisioner_profile
        })

    if migration_method is not None:
        zkhandler.writedata(zk_conn, {
            '/domains/{}/migration_method'.format(dom_uuid): migration_method
        })

    return True, 'Successfully modified PVC metadata of VM "{}".'.format(domain)

def modify_vm(zk_conn, domain, restart, new_vm_config):
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)
    dom_name = getDomainName(zk_conn, domain)

    # Parse and valiate the XML
    try:
        parsed_xml = lxml.objectify.fromstring(new_vm_config)
    except Exception:
        return False, 'ERROR: Failed to parse XML data.'

    # Obtain the RBD disk list using the common functions
    ddisks = common.getDomainDisks(parsed_xml, {})
    rbd_list = []
    for disk in ddisks:
        if disk['type'] == 'rbd':
            rbd_list.append(disk['name'])

    # Join the RBD list
    if isinstance(rbd_list, list) and rbd_list:
        formatted_rbd_list = ','.join(rbd_list)
    else:
        formatted_rbd_list = ''

    # Add the modified config to Zookeeper
    zk_data = {
        '/domains/{}'.format(dom_uuid): dom_name,
        '/domains/{}/rbdlist'.format(dom_uuid): formatted_rbd_list,
        '/domains/{}/xml'.format(dom_uuid): new_vm_config
    }
    zkhandler.writedata(zk_conn, zk_data)

    if restart:
        lock = zkhandler.exclusivelock(zk_conn, '/domains/{}/state'.format(dom_uuid))
        lock.acquire()
        zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'restart'})
        lock.release()

    return True, ''

def dump_vm(zk_conn, domain):
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Gram the domain XML and dump it to stdout
    vm_xml = zkhandler.readdata(zk_conn, '/domains/{}/xml'.format(dom_uuid))

    return True, vm_xml

def undefine_vm(zk_conn, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Shut down the VM
    current_vm_state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid))
    if current_vm_state != 'stop':
        # Set the domain into stop mode
        lock = zkhandler.exclusivelock(zk_conn, '/domains/{}/state'.format(dom_uuid))
        lock.acquire()
        zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'stop'})
        lock.release()

        # Wait for 2 seconds to allow state to flow to all nodes
        time.sleep(2)

    # Gracefully terminate the class instances
    zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'delete'})
    time.sleep(2)

    # Delete the configurations
    zkhandler.deletekey(zk_conn, '/domains/{}'.format(dom_uuid))

    return True, 'Undefined VM "{}" from the cluster.'.format(domain)

def remove_vm(zk_conn, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    disk_list = common.getDomainDiskList(zk_conn, dom_uuid)

    # Shut down the VM
    current_vm_state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid))
    if current_vm_state != 'stop':
        # Set the domain into stop mode
        lock = zkhandler.exclusivelock(zk_conn, '/domains/{}/state'.format(dom_uuid))
        lock.acquire()
        zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'stop'})
        lock.release()

        # Wait for 2 seconds to allow state to flow to all nodes
        time.sleep(2)

    # Gracefully terminate the class instances
    zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'delete'})
    time.sleep(2)

    # Delete the configurations
    zkhandler.deletekey(zk_conn, '/domains/{}'.format(dom_uuid))
    time.sleep(2)

    # Remove disks
    for disk in disk_list:
        # vmpool/vmname_volume
        try:
            disk_pool, disk_name = disk.split('/')
            retcode, message = ceph.remove_volume(zk_conn, disk_pool, disk_name)
        except ValueError:
            continue

    return True, 'Removed VM "{}" and disks from the cluster.'.format(domain)

def start_vm(zk_conn, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Set the VM to start
    lock = zkhandler.exclusivelock(zk_conn, '/domains/{}/state'.format(dom_uuid))
    lock.acquire()
    zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'start'})
    lock.release()

    return True, 'Starting VM "{}".'.format(domain)

def restart_vm(zk_conn, domain, wait=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid))
    if current_state != 'start':
        return False, 'ERROR: VM "{}" is not in "start" state!'.format(domain)

    retmsg = 'Restarting VM "{}".'.format(domain)

    # Set the VM to restart
    lock = zkhandler.exclusivelock(zk_conn, '/domains/{}/state'.format(dom_uuid))
    lock.acquire()
    zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'restart'})
    lock.release()

    if wait:
        while zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid)) == 'restart':
            time.sleep(1)
        retmsg = 'Restarted VM "{}"'.format(domain)

    return True, retmsg

def shutdown_vm(zk_conn, domain, wait=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid))
    if current_state != 'start':
        return False, 'ERROR: VM "{}" is not in "start" state!'.format(domain)

    retmsg = 'Shutting down VM "{}"'.format(domain)

    # Set the VM to shutdown
    lock = zkhandler.exclusivelock(zk_conn, '/domains/{}/state'.format(dom_uuid))
    lock.acquire()
    zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'shutdown'})
    lock.release()

    if wait:
        while zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid)) == 'shutdown':
            time.sleep(1)
        retmsg = 'Shut down VM "{}"'.format(domain)

    return True, retmsg

def stop_vm(zk_conn, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Set the VM to start
    lock = zkhandler.exclusivelock(zk_conn, '/domains/{}/state'.format(dom_uuid))
    lock.acquire()
    zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'stop'})
    lock.release()

    return True, 'Forcibly stopping VM "{}".'.format(domain)

def disable_vm(zk_conn, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid))
    if current_state != 'stop':
        return False, 'ERROR: VM "{}" must be stopped before disabling!'.format(domain)

    # Set the VM to start
    lock = zkhandler.exclusivelock(zk_conn, '/domains/{}/state'.format(dom_uuid))
    lock.acquire()
    zkhandler.writedata(zk_conn, {'/domains/{}/state'.format(dom_uuid): 'disable'})
    lock.release()

    return True, 'Marked VM "{}" as disable.'.format(domain)

def move_vm(zk_conn, domain, target_node, wait=False, force_live=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid))
    if current_state != 'start':
        # If the current state isn't start, preserve it; we're not doing live migration
        target_state = current_state
    else:
        if force_live:
            target_state = 'migrate-live'
        else:
            target_state = 'migrate'

    current_node = zkhandler.readdata(zk_conn, '/domains/{}/node'.format(dom_uuid))

    if not target_node:
        target_node = common.findTargetNode(zk_conn, dom_uuid)
    else:
        # Verify node is valid
        valid_node = common.verifyNode(zk_conn, target_node)
        if not valid_node:
            return False, 'ERROR: Specified node "{}" is invalid.'.format(target_node)

        # Check if node is within the limit
        node_limit = zkhandler.readdata(zk_conn, '/domains/{}/node_limit'.format(dom_uuid))
        if node_limit and target_node not in node_limit.split(','):
            return False, 'ERROR: Specified node "{}" is not in the allowed list of nodes for VM "{}".'.format(target_node, domain)

        # Verify if node is current node
        if target_node == current_node:
            last_node = zkhandler.readdata(zk_conn, '/domains/{}/lastnode'.format(dom_uuid))
            if last_node:
                zkhandler.writedata(zk_conn, {'/domains/{}/lastnode'.format(dom_uuid): ''})
                return True, 'Making temporary migration permanent for VM "{}".'.format(domain)

            return False, 'ERROR: VM "{}" is already running on node "{}".'.format(domain, current_node)

    if not target_node:
        return False, 'ERROR: Could not find a valid migration target for VM "{}".'.format(domain)

    retmsg = 'Permanently migrating VM "{}" to node "{}".'.format(domain, target_node)

    lock = zkhandler.exclusivelock(zk_conn, '/domains/{}/state'.format(dom_uuid))
    lock.acquire()
    zkhandler.writedata(zk_conn, {
            '/domains/{}/state'.format(dom_uuid): target_state,
            '/domains/{}/node'.format(dom_uuid): target_node,
            '/domains/{}/lastnode'.format(dom_uuid): ''
        })
    lock.release()

    if wait:
        while zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid)) == target_state:
            time.sleep(1)
        retmsg = 'Permanently migrated VM "{}" to node "{}"'.format(domain, target_node)

    return True, retmsg

def migrate_vm(zk_conn, domain, target_node, force_migrate, wait=False, force_live=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid))
    if current_state != 'start':
        # If the current state isn't start, preserve it; we're not doing live migration
        target_state = current_state
    else:
        if force_live:
            target_state = 'migrate-live'
        else:
            target_state = 'migrate'

    current_node = zkhandler.readdata(zk_conn, '/domains/{}/node'.format(dom_uuid))
    last_node = zkhandler.readdata(zk_conn, '/domains/{}/lastnode'.format(dom_uuid))

    if last_node and not force_migrate:
        return False, 'ERROR: VM "{}" has been previously migrated.'.format(domain)

    if not target_node:
        target_node = common.findTargetNode(zk_conn, dom_uuid)
    else:
        # Verify node is valid
        valid_node = common.verifyNode(zk_conn, target_node)
        if not valid_node:
            return False, 'ERROR: Specified node "{}" is invalid.'.format(target_node)

        # Check if node is within the limit
        node_limit = zkhandler.readdata(zk_conn, '/domains/{}/node_limit'.format(dom_uuid))
        if node_limit and target_node not in node_limit.split(','):
            return False, 'ERROR: Specified node "{}" is not in the allowed list of nodes for VM "{}".'.format(target_node, domain)

        # Verify if node is current node
        if target_node == current_node:
            return False, 'ERROR: VM "{}" is already running on node "{}".'.format(domain, current_node)

    if not target_node:
        return False, 'ERROR: Could not find a valid migration target for VM "{}".'.format(domain)

    # Don't overwrite an existing last_node when using force_migrate
    if last_node and force_migrate:
        current_node = last_node

    retmsg = 'Migrating VM "{}" to node "{}".'.format(domain, target_node)

    lock = zkhandler.exclusivelock(zk_conn, '/domains/{}/state'.format(dom_uuid))
    lock.acquire()
    zkhandler.writedata(zk_conn, {
        '/domains/{}/state'.format(dom_uuid): target_state,
        '/domains/{}/node'.format(dom_uuid): target_node,
        '/domains/{}/lastnode'.format(dom_uuid): current_node
    })
    lock.release()

    if wait:
        while zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid)) == target_state:
            time.sleep(1)
        retmsg = 'Migrated VM "{}" to node "{}"'.format(domain, target_node)

    return True, retmsg

def unmigrate_vm(zk_conn, domain, wait=False, force_live=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid))
    if current_state != 'start':
        # If the current state isn't start, preserve it; we're not doing live migration
        target_state = current_state
    else:
        if force_live:
            target_state = 'migrate-live'
        else:
            target_state = 'migrate'

    target_node = zkhandler.readdata(zk_conn, '/domains/{}/lastnode'.format(dom_uuid))

    if target_node == '':
        return False, 'ERROR: VM "{}" has not been previously migrated.'.format(domain)

    retmsg = 'Unmigrating VM "{}" back to node "{}".'.format(domain, target_node)

    lock = zkhandler.exclusivelock(zk_conn, '/domains/{}/state'.format(dom_uuid))
    lock.acquire()
    zkhandler.writedata(zk_conn, {
        '/domains/{}/state'.format(dom_uuid): target_state,
        '/domains/{}/node'.format(dom_uuid): target_node,
        '/domains/{}/lastnode'.format(dom_uuid): ''
    })
    lock.release()

    if wait:
        while zkhandler.readdata(zk_conn, '/domains/{}/state'.format(dom_uuid)) == target_state:
            time.sleep(1)
        retmsg = 'Unmigrated VM "{}" back to node "{}"'.format(domain, target_node)

    return True, retmsg

def get_console_log(zk_conn, domain, lines=1000):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get the data from ZK
    console_log = zkhandler.readdata(zk_conn, '/domains/{}/consolelog'.format(dom_uuid))

    # Shrink the log buffer to length lines
    shrunk_log = console_log.split('\n')[-lines:]
    loglines = '\n'.join(shrunk_log)

    return True, loglines

def get_info(zk_conn, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zk_conn, domain)
    if not dom_uuid:
        return False, 'ERROR: No VM named "{}" is present in the cluster.'.format(domain)

    # Gather information from XML config and print it
    domain_information = common.getInformationFromXML(zk_conn, dom_uuid)
    if not domain_information:
        return False, 'ERROR: Could not get information about VM "{}".'.format(domain)

    return True, domain_information

def get_list(zk_conn, node, state, limit, is_fuzzy=True):
    if node:
        # Verify node is valid
        if not common.verifyNode(zk_conn, node):
            return False, 'Specified node "{}" is invalid.'.format(node)

    if state:
        valid_states = ['start', 'restart', 'shutdown', 'stop', 'disable', 'fail', 'migrate', 'unmigrate', 'provision']
        if state not in valid_states:
            return False, 'VM state "{}" is not valid.'.format(state)

    full_vm_list = zkhandler.listchildren(zk_conn, '/domains')
    vm_list = []

    # Set our limit to a sensible regex
    if limit and is_fuzzy:
        try:
            # Implcitly assume fuzzy limits
            if not re.match('[^].*', limit):
                limit = '.*' + limit
            if not re.match('.*[$]', limit):
                limit = limit + '.*'
        except Exception as e:
            return False, 'Regex Error: {}'.format(e)

    # If we're limited, remove other nodes' VMs
    vm_node = {}
    vm_state = {}
    for vm in full_vm_list:
        # Check we don't match the limit
        name = zkhandler.readdata(zk_conn, '/domains/{}'.format(vm))
        vm_node[vm] = zkhandler.readdata(zk_conn, '/domains/{}/node'.format(vm))
        vm_state[vm] = zkhandler.readdata(zk_conn, '/domains/{}/state'.format(vm))
        # Handle limiting
        if limit:
            try:
                if re.match(limit, vm):
                    if not node and not state:
                        vm_list.append(common.getInformationFromXML(zk_conn, vm))
                    else:
                        if vm_node[vm] == node or vm_state[vm] == state:
                            vm_list.append(common.getInformationFromXML(zk_conn, vm))

                if re.match(limit, name):
                    if not node and not state:
                        vm_list.append(common.getInformationFromXML(zk_conn, vm))
                    else:
                        if vm_node[vm] == node or vm_state[vm] == state:
                            vm_list.append(common.getInformationFromXML(zk_conn, vm))
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            # Check node to avoid unneeded ZK calls
            if not node and not state:
                vm_list.append(common.getInformationFromXML(zk_conn, vm))
            else:
                if vm_node[vm] == node or vm_state[vm] == state:
                    vm_list.append(common.getInformationFromXML(zk_conn, vm))

    return True, vm_list
