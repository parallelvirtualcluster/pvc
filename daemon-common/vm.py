#!/usr/bin/env python3

# vm.py - PVC client function library, VM fuctions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2021 Joshua M. Boniface <joshua@boniface.me>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, version 3.
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
import lxml.etree

from uuid import UUID
from concurrent.futures import ThreadPoolExecutor

import daemon_lib.common as common

import daemon_lib.ceph as ceph
from daemon_lib.network import set_sriov_vf_vm, unset_sriov_vf_vm


#
# Cluster search functions
#
def getClusterDomainList(zkhandler):
    # Get a list of UUIDs by listing the children of /domains
    uuid_list = zkhandler.children('base.domain')
    name_list = []
    # For each UUID, get the corresponding name from the data
    for uuid in uuid_list:
        name_list.append(zkhandler.read(('domain', uuid)))
    return uuid_list, name_list


def searchClusterByUUID(zkhandler, uuid):
    try:
        # Get the lists
        uuid_list, name_list = getClusterDomainList(zkhandler)
        # We're looking for UUID, so find that element ID
        index = uuid_list.index(uuid)
        # Get the name_list element at that index
        name = name_list[index]
    except ValueError:
        # We didn't find anything
        return None

    return name


def searchClusterByName(zkhandler, name):
    try:
        # Get the lists
        uuid_list, name_list = getClusterDomainList(zkhandler)
        # We're looking for name, so find that element ID
        index = name_list.index(name)
        # Get the uuid_list element at that index
        uuid = uuid_list[index]
    except ValueError:
        # We didn't find anything
        return None

    return uuid


def getDomainUUID(zkhandler, domain):
    # Validate that VM exists in cluster
    if common.validateUUID(domain):
        dom_name = searchClusterByUUID(zkhandler, domain)
        dom_uuid = searchClusterByName(zkhandler, dom_name)
    else:
        dom_uuid = searchClusterByName(zkhandler, domain)
        dom_name = searchClusterByUUID(zkhandler, dom_uuid)

    return dom_uuid


def getDomainName(zkhandler, domain):
    # Validate that VM exists in cluster
    if common.validateUUID(domain):
        dom_name = searchClusterByUUID(zkhandler, domain)
        dom_uuid = searchClusterByName(zkhandler, dom_name)
    else:
        dom_uuid = searchClusterByName(zkhandler, domain)
        dom_name = searchClusterByUUID(zkhandler, dom_uuid)

    return dom_name


#
# Helper functions
#
def change_state(zkhandler, dom_uuid, new_state):
        lock = zkhandler.exclusivelock(('domain.state', dom_uuid))
        with lock:
            zkhandler.write([
                (('domain.state', dom_uuid), new_state)
            ])

            # Wait for 1/2 second to allow state to flow to all nodes
            time.sleep(0.5)


#
# Direct functions
#
def is_migrated(zkhandler, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    last_node = zkhandler.read(('domain.last_node', dom_uuid))
    if last_node:
        return True
    else:
        return False


def flush_locks(zkhandler, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Verify that the VM is in a stopped state; freeing locks is not safe otherwise
    state = zkhandler.read(('domain.state', dom_uuid))
    if state != 'stop':
        return False, 'ERROR: VM "{}" is not in stopped state; flushing RBD locks on a running VM is dangerous.'.format(domain)

    # Tell the cluster to create a new OSD for the host
    flush_locks_string = 'flush_locks {}'.format(dom_uuid)
    zkhandler.write([
        ('base.cmd.domain', flush_locks_string)
    ])
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock('base.cmd.domain')
    with lock:
        try:
            result = zkhandler.read('base.cmd.domain').split()[0]
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
    lock = zkhandler.writelock('base.cmd.domain')
    with lock:
        time.sleep(0.5)
        zkhandler.write([
            ('base.cmd.domain', '')
        ])

    return success, message


def define_vm(zkhandler, config_data, target_node, node_limit, node_selector, node_autostart, migration_method=None, profile=None, initial_state='stop'):
    # Parse the XML data
    try:
        parsed_xml = lxml.objectify.fromstring(config_data)
    except Exception:
        return False, 'ERROR: Failed to parse XML data.'
    dom_uuid = parsed_xml.uuid.text
    dom_name = parsed_xml.name.text

    # Ensure that the UUID and name are unique
    if searchClusterByUUID(zkhandler, dom_uuid) or searchClusterByName(zkhandler, dom_name):
        return False, 'ERROR: Specified VM "{}" or UUID "{}" matches an existing VM on the cluster'.format(dom_name, dom_uuid)

    if not target_node:
        target_node = common.findTargetNode(zkhandler, dom_uuid)
    else:
        # Verify node is valid
        valid_node = common.verifyNode(zkhandler, target_node)
        if not valid_node:
            return False, 'ERROR: Specified node "{}" is invalid.'.format(target_node)

    # If a SR-IOV network device is being added, set its used state
    dnetworks = common.getDomainNetworks(parsed_xml, {})
    for network in dnetworks:
        if network['type'] in ['direct', 'hostdev']:
            dom_node = zkhandler.read(('domain.node', dom_uuid))

            # Check if the network is already in use
            is_used = zkhandler.read(('node.sriov.vf', dom_node, 'sriov_vf.used', network['source']))
            if is_used == 'True':
                used_by_name = searchClusterByUUID(zkhandler, zkhandler.read(('node.sriov.vf', dom_node, 'sriov_vf.used_by', network['source'])))
                return False, 'ERROR: Attempted to use SR-IOV network "{}" which is already used by VM "{}" on node "{}".'.format(network['source'], used_by_name, dom_node)

            # We must update the "used" section
            set_sriov_vf_vm(zkhandler, dom_uuid, dom_node, network['source'], network['mac'], network['type'])

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
    zkhandler.write([
        (('domain', dom_uuid), dom_name),
        (('domain.xml', dom_uuid), config_data),
        (('domain.state', dom_uuid), initial_state),
        (('domain.profile', dom_uuid), profile),
        (('domain.stats', dom_uuid), ''),
        (('domain.node', dom_uuid), target_node),
        (('domain.last_node', dom_uuid), ''),
        (('domain.failed_reason', dom_uuid), ''),
        (('domain.storage.volumes', dom_uuid), formatted_rbd_list),
        (('domain.console.log', dom_uuid), ''),
        (('domain.console.vnc', dom_uuid), ''),
        (('domain.meta.autostart', dom_uuid), node_autostart),
        (('domain.meta.migrate_method', dom_uuid), migration_method),
        (('domain.meta.node_limit', dom_uuid), formatted_node_limit),
        (('domain.meta.node_selector', dom_uuid), node_selector),
        (('domain.migrate.sync_lock', dom_uuid), ''),
    ])

    return True, 'Added new VM with Name "{}" and UUID "{}" to database.'.format(dom_name, dom_uuid)


def modify_vm_metadata(zkhandler, domain, node_limit, node_selector, node_autostart, provisioner_profile, migration_method):
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    update_list = list()

    if node_limit is not None:
        update_list.append((('domain.meta.node_limit', dom_uuid), node_limit))

    if node_selector is not None:
        update_list.append((('domain.meta.node_selector', dom_uuid), node_selector))

    if node_autostart is not None:
        update_list.append((('domain.meta.autostart', dom_uuid), node_autostart))

    if provisioner_profile is not None:
        update_list.append((('domain.profile', dom_uuid), provisioner_profile))

    if migration_method is not None:
        update_list.append((('domain.meta.migrate_method', dom_uuid), migration_method))

    if len(update_list) < 1:
        return False, 'ERROR: No updates to apply.'

    zkhandler.write(update_list)

    return True, 'Successfully modified PVC metadata of VM "{}".'.format(domain)


def modify_vm(zkhandler, domain, restart, new_vm_config):
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)
    dom_name = getDomainName(zkhandler, domain)

    # Parse and valiate the XML
    try:
        parsed_xml = lxml.objectify.fromstring(new_vm_config)
    except Exception:
        return False, 'ERROR: Failed to parse new XML data.'

    # Get our old network list for comparison purposes
    old_vm_config = zkhandler.read(('domain.xml', dom_uuid))
    old_parsed_xml = lxml.objectify.fromstring(old_vm_config)
    old_dnetworks = common.getDomainNetworks(old_parsed_xml, {})

    # If a SR-IOV network device is being added, set its used state
    dnetworks = common.getDomainNetworks(parsed_xml, {})
    for network in dnetworks:
        # Ignore networks that are already there
        if network['source'] in [net['source'] for net in old_dnetworks]:
            continue

        if network['type'] in ['direct', 'hostdev']:
            dom_node = zkhandler.read(('domain.node', dom_uuid))

            # Check if the network is already in use
            is_used = zkhandler.read(('node.sriov.vf', dom_node, 'sriov_vf.used', network['source']))
            if is_used == 'True':
                used_by_name = searchClusterByUUID(zkhandler, zkhandler.read(('node.sriov.vf', dom_node, 'sriov_vf.used_by', network['source'])))
                return False, 'ERROR: Attempted to use SR-IOV network "{}" which is already used by VM "{}" on node "{}".'.format(network['source'], used_by_name, dom_node)

            # We must update the "used" section
            set_sriov_vf_vm(zkhandler, dom_uuid, dom_node, network['source'], network['mac'], network['type'])

    # If a SR-IOV network device is being removed, unset its used state
    for network in old_dnetworks:
        if network['type'] in ['direct', 'hostdev']:
            if network['mac'] not in [n['mac'] for n in dnetworks]:
                dom_node = zkhandler.read(('domain.node', dom_uuid))
                # We must update the "used" section
                unset_sriov_vf_vm(zkhandler, dom_node, network['source'])

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
    zkhandler.write([
        (('domain', dom_uuid), dom_name),
        (('domain.storage.volumes', dom_uuid), formatted_rbd_list),
        (('domain.xml', dom_uuid), new_vm_config),
    ])

    if restart:
        change_state(zkhandler, dom_uuid, 'restart')

    return True, 'Successfully modified configuration of VM "{}".'.format(domain)


def dump_vm(zkhandler, domain):
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Gram the domain XML and dump it to stdout
    vm_xml = zkhandler.read(('domain.xml', dom_uuid))

    return True, vm_xml


def rename_vm(zkhandler, domain, new_domain):
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Verify that the VM is in a stopped state; renaming is not supported otherwise
    state = zkhandler.read(('domain.state', dom_uuid))
    if state != 'stop':
        return False, 'ERROR: VM "{}" is not in stopped state; VMs cannot be renamed while running.'.format(domain)

    # Parse and valiate the XML
    vm_config = common.getDomainXML(zkhandler, dom_uuid)

    # Obtain the RBD disk list using the common functions
    ddisks = common.getDomainDisks(vm_config, {})
    pool_list = []
    rbd_list = []
    for disk in ddisks:
        if disk['type'] == 'rbd':
            pool_list.append(disk['name'].split('/')[0])
            rbd_list.append(disk['name'].split('/')[1])

    # Rename each volume in turn
    for idx, rbd in enumerate(rbd_list):
        rbd_new = re.sub(r"{}".format(domain), new_domain, rbd)
        # Skip renaming if nothing changed
        if rbd_new == rbd:
            continue
        ceph.rename_volume(zkhandler, pool_list[idx], rbd, rbd_new)

    # Replace the name in the config
    vm_config_new = lxml.etree.tostring(vm_config, encoding='ascii', method='xml').decode().replace(domain, new_domain)

    # Get VM information
    _b, dom_info = get_info(zkhandler, dom_uuid)

    # Undefine the old VM
    undefine_vm(zkhandler, dom_uuid)

    # Define the new VM
    define_vm(zkhandler, vm_config_new, dom_info['node'], dom_info['node_limit'], dom_info['node_selector'], dom_info['node_autostart'], migration_method=dom_info['migration_method'], profile=dom_info['profile'], initial_state='stop')

    # If the VM is migrated, store that
    if dom_info['migrated'] != 'no':
        zkhandler.write([
            (('domain.last_node', dom_uuid), dom_info['last_node'])
        ])

    return True, 'Successfully renamed VM "{}" to "{}".'.format(domain, new_domain)


def undefine_vm(zkhandler, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Shut down the VM
    current_vm_state = zkhandler.read(('domain.state', dom_uuid))
    if current_vm_state != 'stop':
        change_state(zkhandler, dom_uuid, 'stop')

    # Gracefully terminate the class instances
    change_state(zkhandler, dom_uuid, 'delete')

    # Delete the configurations
    zkhandler.delete([
        ('domain', dom_uuid)
    ])

    return True, 'Undefined VM "{}" from the cluster.'.format(domain)


def remove_vm(zkhandler, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    disk_list = common.getDomainDiskList(zkhandler, dom_uuid)

    # Shut down the VM
    current_vm_state = zkhandler.read(('domain.state', dom_uuid))
    if current_vm_state != 'stop':
        change_state(zkhandler, dom_uuid, 'stop')

    # Wait for 1 second to allow state to flow to all nodes
    time.sleep(1)

    # Remove disks
    for disk in disk_list:
        # vmpool/vmname_volume
        try:
            disk_pool, disk_name = disk.split('/')
        except ValueError:
            continue

        retcode, message = ceph.remove_volume(zkhandler, disk_pool, disk_name)
        if not retcode:
            if re.match('^ERROR: No volume with name', message):
                continue
            else:
                return False, message

    # Gracefully terminate the class instances
    change_state(zkhandler, dom_uuid, 'delete')

    # Wait for 1/2 second to allow state to flow to all nodes
    time.sleep(0.5)

    # Delete the VM configuration from Zookeeper
    zkhandler.delete([
        ('domain', dom_uuid)
    ])

    return True, 'Removed VM "{}" and its disks from the cluster.'.format(domain)


def start_vm(zkhandler, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Set the VM to start
    change_state(zkhandler, dom_uuid, 'start')

    return True, 'Starting VM "{}".'.format(domain)


def restart_vm(zkhandler, domain, wait=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.read(('domain.state', dom_uuid))
    if current_state != 'start':
        return False, 'ERROR: VM "{}" is not in "start" state!'.format(domain)

    retmsg = 'Restarting VM "{}".'.format(domain)

    # Set the VM to restart
    change_state(zkhandler, dom_uuid, 'restart')

    if wait:
        while zkhandler.read(('domain.state', dom_uuid)) == 'restart':
            time.sleep(0.5)
        retmsg = 'Restarted VM "{}"'.format(domain)

    return True, retmsg


def shutdown_vm(zkhandler, domain, wait=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.read(('domain.state', dom_uuid))
    if current_state != 'start':
        return False, 'ERROR: VM "{}" is not in "start" state!'.format(domain)

    retmsg = 'Shutting down VM "{}"'.format(domain)

    # Set the VM to shutdown
    change_state(zkhandler, dom_uuid, 'shutdown')

    if wait:
        while zkhandler.read(('domain.state', dom_uuid)) == 'shutdown':
            time.sleep(0.5)
        retmsg = 'Shut down VM "{}"'.format(domain)

    return True, retmsg


def stop_vm(zkhandler, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Set the VM to stop
    change_state(zkhandler, dom_uuid, 'stop')

    return True, 'Forcibly stopping VM "{}".'.format(domain)


def disable_vm(zkhandler, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.read(('domain.state', dom_uuid))
    if current_state != 'stop':
        return False, 'ERROR: VM "{}" must be stopped before disabling!'.format(domain)

    # Set the VM to disable
    change_state(zkhandler, dom_uuid, 'disable')

    return True, 'Marked VM "{}" as disable.'.format(domain)


def update_vm_sriov_nics(zkhandler, dom_uuid, source_node, target_node):
    # Update all the SR-IOV device states on both nodes, used during migrations but called by the node-side
    vm_config = zkhandler.read(('domain.xml', dom_uuid))
    parsed_xml = lxml.objectify.fromstring(vm_config)
    dnetworks = common.getDomainNetworks(parsed_xml, {})
    retcode = True
    retmsg = ''
    for network in dnetworks:
        if network['type'] in ['direct', 'hostdev']:
            # Check if the network is already in use
            is_used = zkhandler.read(('node.sriov.vf', target_node, 'sriov_vf.used', network['source']))
            if is_used == 'True':
                used_by_name = searchClusterByUUID(zkhandler, zkhandler.read(('node.sriov.vf', target_node, 'sriov_vf.used_by', network['source'])))
                if retcode:
                    retcode_this = False
                    retmsg = 'Attempting to use SR-IOV network "{}" which is already used by VM "{}"'.format(network['source'], used_by_name)
            else:
                retcode_this = True

            # We must update the "used" section
            if retcode_this:
                # This conditional ensure that if we failed the is_used check, we don't try to overwrite the information of a VF that belongs to another VM
                set_sriov_vf_vm(zkhandler, dom_uuid, target_node, network['source'], network['mac'], network['type'])
            # ... but we still want to free the old node in an case
            unset_sriov_vf_vm(zkhandler, source_node, network['source'])

            if not retcode_this:
                retcode = retcode_this

    return retcode, retmsg


def move_vm(zkhandler, domain, target_node, wait=False, force_live=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.read(('domain.state', dom_uuid))
    if current_state != 'start':
        # If the current state isn't start, preserve it; we're not doing live migration
        target_state = current_state
    else:
        if force_live:
            target_state = 'migrate-live'
        else:
            target_state = 'migrate'

    current_node = zkhandler.read(('domain.node', dom_uuid))

    if not target_node:
        target_node = common.findTargetNode(zkhandler, dom_uuid)
    else:
        # Verify node is valid
        valid_node = common.verifyNode(zkhandler, target_node)
        if not valid_node:
            return False, 'ERROR: Specified node "{}" is invalid.'.format(target_node)

        # Check if node is within the limit
        node_limit = zkhandler.read(('domain.meta.node_limit', dom_uuid))
        if node_limit and target_node not in node_limit.split(','):
            return False, 'ERROR: Specified node "{}" is not in the allowed list of nodes for VM "{}".'.format(target_node, domain)

        # Verify if node is current node
        if target_node == current_node:
            last_node = zkhandler.read(('domain.last_node', dom_uuid))
            if last_node:
                zkhandler.write([
                    (('domain.last_node', dom_uuid), '')
                ])
                return True, 'Making temporary migration permanent for VM "{}".'.format(domain)

            return False, 'ERROR: VM "{}" is already running on node "{}".'.format(domain, current_node)

    if not target_node:
        return False, 'ERROR: Could not find a valid migration target for VM "{}".'.format(domain)

    retmsg = 'Permanently migrating VM "{}" to node "{}".'.format(domain, target_node)

    lock = zkhandler.exclusivelock(('domain.state', dom_uuid))
    with lock:
        zkhandler.write([
            (('domain.state', dom_uuid), target_state),
            (('domain.node', dom_uuid), target_node),
            (('domain.last_node', dom_uuid), '')
        ])

        # Wait for 1/2 second for migration to start
        time.sleep(0.5)

    # Update any SR-IOV NICs
    update_vm_sriov_nics(zkhandler, dom_uuid, current_node, target_node)

    if wait:
        while zkhandler.read(('domain.state', dom_uuid)) == target_state:
            time.sleep(0.5)
        retmsg = 'Permanently migrated VM "{}" to node "{}"'.format(domain, target_node)

    return True, retmsg


def migrate_vm(zkhandler, domain, target_node, force_migrate, wait=False, force_live=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.read(('domain.state', dom_uuid))
    if current_state != 'start':
        # If the current state isn't start, preserve it; we're not doing live migration
        target_state = current_state
    else:
        if force_live:
            target_state = 'migrate-live'
        else:
            target_state = 'migrate'

    current_node = zkhandler.read(('domain.node', dom_uuid))
    last_node = zkhandler.read(('domain.last_node', dom_uuid))

    if last_node and not force_migrate:
        return False, 'ERROR: VM "{}" has been previously migrated.'.format(domain)

    if not target_node:
        target_node = common.findTargetNode(zkhandler, dom_uuid)
    else:
        # Verify node is valid
        valid_node = common.verifyNode(zkhandler, target_node)
        if not valid_node:
            return False, 'ERROR: Specified node "{}" is invalid.'.format(target_node)

        # Check if node is within the limit
        node_limit = zkhandler.read(('domain.meta.node_limit', dom_uuid))
        if node_limit and target_node not in node_limit.split(','):
            return False, 'ERROR: Specified node "{}" is not in the allowed list of nodes for VM "{}".'.format(target_node, domain)

        # Verify if node is current node
        if target_node == current_node:
            return False, 'ERROR: VM "{}" is already running on node "{}".'.format(domain, current_node)

    if not target_node:
        return False, 'ERROR: Could not find a valid migration target for VM "{}".'.format(domain)

    # Don't overwrite an existing last_node when using force_migrate
    real_current_node = current_node  # Used for the SR-IOV update
    if last_node and force_migrate:
        current_node = last_node

    retmsg = 'Migrating VM "{}" to node "{}".'.format(domain, target_node)

    lock = zkhandler.exclusivelock(('domain.state', dom_uuid))
    with lock:
        zkhandler.write([
            (('domain.state', dom_uuid), target_state),
            (('domain.node', dom_uuid), target_node),
            (('domain.last_node', dom_uuid), current_node)
        ])

        # Wait for 1/2 second for migration to start
        time.sleep(0.5)

    # Update any SR-IOV NICs
    update_vm_sriov_nics(zkhandler, dom_uuid, real_current_node, target_node)

    if wait:
        while zkhandler.read(('domain.state', dom_uuid)) == target_state:
            time.sleep(0.5)
        retmsg = 'Migrated VM "{}" to node "{}"'.format(domain, target_node)

    return True, retmsg


def unmigrate_vm(zkhandler, domain, wait=False, force_live=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.read(('domain.state', dom_uuid))
    if current_state != 'start':
        # If the current state isn't start, preserve it; we're not doing live migration
        target_state = current_state
    else:
        if force_live:
            target_state = 'migrate-live'
        else:
            target_state = 'migrate'

    current_node = zkhandler.read(('domain.node', dom_uuid))
    target_node = zkhandler.read(('domain.last_node', dom_uuid))

    if target_node == '':
        return False, 'ERROR: VM "{}" has not been previously migrated.'.format(domain)

    retmsg = 'Unmigrating VM "{}" back to node "{}".'.format(domain, target_node)

    lock = zkhandler.exclusivelock(('domain.state', dom_uuid))
    with lock:
        zkhandler.write([
            (('domain.state', dom_uuid), target_state),
            (('domain.node', dom_uuid), target_node),
            (('domain.last_node', dom_uuid), '')
        ])

        # Wait for 1/2 second for migration to start
        time.sleep(0.5)

    # Update any SR-IOV NICs
    update_vm_sriov_nics(zkhandler, dom_uuid, current_node, target_node)

    if wait:
        while zkhandler.read(('domain.state', dom_uuid)) == target_state:
            time.sleep(0.5)
        retmsg = 'Unmigrated VM "{}" back to node "{}"'.format(domain, target_node)

    return True, retmsg


def get_console_log(zkhandler, domain, lines=1000):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get the data from ZK
    console_log = zkhandler.read(('domain.console.log', dom_uuid))

    if console_log is None:
        return True, ''

    # Shrink the log buffer to length lines
    shrunk_log = console_log.split('\n')[-lines:]
    loglines = '\n'.join(shrunk_log)

    return True, loglines


def get_info(zkhandler, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: No VM named "{}" is present in the cluster.'.format(domain)

    # Gather information from XML config and print it
    domain_information = common.getInformationFromXML(zkhandler, dom_uuid)
    if not domain_information:
        return False, 'ERROR: Could not get information about VM "{}".'.format(domain)

    return True, domain_information


def get_list(zkhandler, node, state, limit, is_fuzzy=True):
    if node:
        # Verify node is valid
        if not common.verifyNode(zkhandler, node):
            return False, 'Specified node "{}" is invalid.'.format(node)

    if state:
        valid_states = ['start', 'restart', 'shutdown', 'stop', 'disable', 'fail', 'migrate', 'unmigrate', 'provision']
        if state not in valid_states:
            return False, 'VM state "{}" is not valid.'.format(state)

    full_vm_list = zkhandler.children('base.domain')

    # Set our limit to a sensible regex
    if limit:
        # Check if the limit is a UUID
        is_limit_uuid = False
        try:
            uuid_obj = UUID(limit, version=4)
            limit = str(uuid_obj)
            is_limit_uuid = True
        except ValueError:
            pass

        if is_fuzzy and not is_limit_uuid:
            try:
                # Implcitly assume fuzzy limits
                if not re.match(r'\^.*', limit):
                    limit = '.*' + limit
                if not re.match(r'.*\$', limit):
                    limit = limit + '.*'
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)

    get_vm_info = dict()
    for vm in full_vm_list:
        name = zkhandler.read(('domain', vm))
        is_limit_match = False
        is_node_match = False
        is_state_match = False

        # Check on limit
        if limit:
            # Try to match the limit against the UUID (if applicable) and name
            try:
                if is_limit_uuid and re.match(limit, vm):
                    is_limit_match = True
                if re.match(limit, name):
                    is_limit_match = True
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            is_limit_match = True

        # Check on node
        if node:
            vm_node = zkhandler.read(('domain.node', vm))
            if vm_node == node:
                is_node_match = True
        else:
            is_node_match = True

        # Check on state
        if state:
            vm_state = zkhandler.read(('domain.state', vm))
            if vm_state == state:
                is_state_match = True
        else:
            is_state_match = True

        get_vm_info[vm] = True if is_limit_match and is_node_match and is_state_match else False

    # Obtain our VM data in a thread pool
    # This helps parallelize the numerous Zookeeper calls a bit, within the bounds of the GIL, and
    # should help prevent this task from becoming absurdly slow with very large numbers of VMs.
    # The max_workers is capped at 32 to avoid creating an absurd number of threads especially if
    # the list gets called multiple times simultaneously by the API, but still provides a noticeable
    # speedup.
    vm_execute_list = [vm for vm in full_vm_list if get_vm_info[vm]]
    vm_data_list = list()
    with ThreadPoolExecutor(max_workers=32, thread_name_prefix='vm_list') as executor:
        futures = []
        for vm_uuid in vm_execute_list:
            futures.append(executor.submit(common.getInformationFromXML, zkhandler, vm_uuid))
        for future in futures:
            try:
                vm_data_list.append(future.result())
            except Exception:
                pass

    return True, vm_data_list
