#!/usr/bin/env python3

# vm.py - PVC client function library, VM fuctions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2024 Joshua M. Boniface <joshua@boniface.me>
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
import os.path
import lxml.objectify
import lxml.etree

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from distutils.util import strtobool
from json import dump as jdump
from json import load as jload
from json import loads as jloads
from libvirt import open as lvopen
from os import scandir
from shutil import rmtree
from socket import gethostname
from uuid import UUID

import daemon_lib.common as common
import daemon_lib.ceph as ceph

from daemon_lib.network import set_sriov_vf_vm, unset_sriov_vf_vm
from daemon_lib.celery import start, update, fail, finish


#
# Cluster search functions
#
def getClusterDomainList(zkhandler):
    # Get a list of UUIDs by listing the children of /domains
    uuid_list = zkhandler.children("base.domain")
    name_list = []
    # For each UUID, get the corresponding name from the data
    for uuid in uuid_list:
        name_list.append(zkhandler.read(("domain", uuid)))
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
    lock = zkhandler.exclusivelock(("domain.state", dom_uuid))
    with lock:
        zkhandler.write([(("domain.state", dom_uuid), new_state)])

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

    last_node = zkhandler.read(("domain.last_node", dom_uuid))
    if last_node:
        return True
    else:
        return False


def define_vm(
    zkhandler,
    config_data,
    target_node,
    node_limit,
    node_selector,
    node_autostart,
    migration_method=None,
    migration_max_downtime=300,
    profile=None,
    tags=[],
    initial_state="stop",
):
    # Parse the XML data
    try:
        parsed_xml = lxml.objectify.fromstring(config_data)
    except Exception as e:
        return False, f"ERROR: Failed to parse XML data: {e}"

    # Extract the required items from the XML document and error if not valid
    next_field = 0
    next_map = {
        0: "uuid",
        1: "name",
        2: "memory",
        3: "vcpu",
        4: "networks",
        5: "disks",
    }
    try:
        dom_uuid = parsed_xml.uuid.text
        next_field += 1
        dom_name = parsed_xml.name.text
        next_field += 1
        parsed_memory = int(parsed_xml.memory.text)
        next_field += 1
        parsed_vcpu = int(parsed_xml.vcpu.text)
        next_field += 1
        dnetworks = common.getDomainNetworks(parsed_xml, {})
        next_field += 1
        ddisks = common.getDomainDisks(parsed_xml, {})
        next_field += 1
    except Exception as e:
        return (
            False,
            f'ERROR: Failed to parse XML data: field data for "{next_map[next_field]}" is not valid: {e}',
        )

    # Ensure that the UUID and name are unique
    if searchClusterByUUID(zkhandler, dom_uuid) or searchClusterByName(
        zkhandler, dom_name
    ):
        return (
            False,
            'ERROR: Specified VM "{}" or UUID "{}" matches an existing VM on the cluster'.format(
                dom_name, dom_uuid
            ),
        )

    if not target_node:
        target_node = common.findTargetNode(zkhandler, dom_uuid)
    else:
        # Verify node is valid
        valid_node = common.verifyNode(zkhandler, target_node)
        if not valid_node:
            return False, 'ERROR: Specified node "{}" is invalid.'.format(target_node)

    # Validate the new RAM against the current active node
    node_total_memory = int(zkhandler.read(("node.memory.total", target_node)))
    if parsed_memory >= node_total_memory:
        return (
            False,
            'ERROR: VM configuration specifies more memory ({} MiB) than node "{}" has available ({} MiB).'.format(
                parsed_memory, target_node, node_total_memory
            ),
        )

    # Validate the number of vCPUs against the current active node
    node_total_cpus = int(zkhandler.read(("node.data.static", target_node)).split()[0])
    if parsed_vcpu >= (node_total_cpus - 2):
        return (
            False,
            'ERROR: VM configuration specifies more vCPUs ({}) than node "{}" has available ({} minus 2).'.format(
                parsed_vcpu, target_node, node_total_cpus
            ),
        )

    # If a SR-IOV network device is being added, set its used state
    for network in dnetworks:
        if network["type"] in ["direct", "hostdev"]:
            dom_node = zkhandler.read(("domain.node", dom_uuid))

            # Check if the network is already in use
            is_used = zkhandler.read(
                ("node.sriov.vf", dom_node, "sriov_vf.used", network["source"])
            )
            if is_used == "True":
                used_by_name = searchClusterByUUID(
                    zkhandler,
                    zkhandler.read(
                        (
                            "node.sriov.vf",
                            dom_node,
                            "sriov_vf.used_by",
                            network["source"],
                        )
                    ),
                )
                return (
                    False,
                    'ERROR: Attempted to use SR-IOV network "{}" which is already used by VM "{}" on node "{}".'.format(
                        network["source"], used_by_name, dom_node
                    ),
                )

            # We must update the "used" section
            set_sriov_vf_vm(
                zkhandler,
                dom_uuid,
                dom_node,
                network["source"],
                network["mac"],
                network["type"],
            )

    # Obtain the RBD disk list using the common functions
    rbd_list = []
    for disk in ddisks:
        if disk["type"] == "rbd":
            rbd_list.append(disk["name"])

    # Join the limit
    if isinstance(node_limit, list) and node_limit:
        formatted_node_limit = ",".join(node_limit)
    else:
        formatted_node_limit = ""

    # Join the RBD list
    if isinstance(rbd_list, list) and rbd_list:
        formatted_rbd_list = ",".join(rbd_list)
    else:
        formatted_rbd_list = ""

    # Add the new domain to Zookeeper
    zkhandler.write(
        [
            (("domain", dom_uuid), dom_name),
            (("domain.xml", dom_uuid), config_data),
            (("domain.state", dom_uuid), initial_state),
            (("domain.profile", dom_uuid), profile),
            (("domain.stats", dom_uuid), ""),
            (("domain.node", dom_uuid), target_node),
            (("domain.last_node", dom_uuid), ""),
            (("domain.failed_reason", dom_uuid), ""),
            (("domain.storage.volumes", dom_uuid), formatted_rbd_list),
            (("domain.console.log", dom_uuid), ""),
            (("domain.console.vnc", dom_uuid), ""),
            (("domain.meta.autostart", dom_uuid), node_autostart),
            (("domain.meta.migrate_method", dom_uuid), str(migration_method).lower()),
            (
                ("domain.meta.migrate_max_downtime", dom_uuid),
                int(migration_max_downtime),
            ),
            (("domain.meta.node_limit", dom_uuid), formatted_node_limit),
            (("domain.meta.node_selector", dom_uuid), str(node_selector).lower()),
            (("domain.meta.tags", dom_uuid), ""),
            (("domain.migrate.sync_lock", dom_uuid), ""),
        ]
    )

    for tag in tags:
        tag_name = tag["name"]
        zkhandler.write(
            [
                (("domain.meta.tags", dom_uuid, "tag.name", tag_name), tag["name"]),
                (("domain.meta.tags", dom_uuid, "tag.type", tag_name), tag["type"]),
                (
                    ("domain.meta.tags", dom_uuid, "tag.protected", tag_name),
                    tag["protected"],
                ),
            ]
        )

    return True, 'Added new VM with Name "{}" and UUID "{}" to database.'.format(
        dom_name, dom_uuid
    )


def modify_vm_metadata(
    zkhandler,
    domain,
    node_limit,
    node_selector,
    node_autostart,
    provisioner_profile,
    migration_method,
    migration_max_downtime,
):
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    update_list = list()

    if node_limit is not None:
        update_list.append((("domain.meta.node_limit", dom_uuid), node_limit))

    if node_selector is not None:
        update_list.append(
            (("domain.meta.node_selector", dom_uuid), str(node_selector).lower())
        )

    if node_autostart is not None:
        update_list.append((("domain.meta.autostart", dom_uuid), node_autostart))

    if provisioner_profile is not None:
        update_list.append((("domain.profile", dom_uuid), provisioner_profile))

    if migration_method is not None:
        update_list.append(
            (("domain.meta.migrate_method", dom_uuid), str(migration_method).lower())
        )

    if migration_max_downtime is not None:
        update_list.append(
            (
                ("domain.meta.migrate_max_downtime", dom_uuid),
                int(migration_max_downtime),
            )
        )

    if len(update_list) < 1:
        return False, "ERROR: No updates to apply."

    zkhandler.write(update_list)

    return True, 'Successfully modified PVC metadata of VM "{}".'.format(domain)


def modify_vm_tag(zkhandler, domain, action, tag, protected=False):
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    if action == "add":
        zkhandler.write(
            [
                (("domain.meta.tags", dom_uuid, "tag.name", tag), tag),
                (("domain.meta.tags", dom_uuid, "tag.type", tag), "user"),
                (("domain.meta.tags", dom_uuid, "tag.protected", tag), protected),
            ]
        )

        return True, 'Successfully added tag "{}" to VM "{}".'.format(tag, domain)
    elif action == "remove":
        if not zkhandler.exists(("domain.meta.tags", dom_uuid, "tag", tag)):
            return False, 'The tag "{}" does not exist.'.format(tag)

        if zkhandler.read(("domain.meta.tags", dom_uuid, "tag.type", tag)) != "user":
            return (
                False,
                'The tag "{}" is not a user tag and cannot be removed.'.format(tag),
            )

        if bool(
            strtobool(
                zkhandler.read(("domain.meta.tags", dom_uuid, "tag.protected", tag))
            )
        ):
            return False, 'The tag "{}" is protected and cannot be removed.'.format(tag)

        zkhandler.delete([(("domain.meta.tags", dom_uuid, "tag", tag))])

        return True, 'Successfully removed tag "{}" from VM "{}".'.format(tag, domain)
    else:
        return False, "Specified tag action is not available."


def modify_vm(zkhandler, domain, restart, new_vm_config):
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)
    dom_name = getDomainName(zkhandler, domain)

    # Parse and valiate the XML
    try:
        parsed_xml = lxml.objectify.fromstring(new_vm_config)
    except Exception:
        return False, "ERROR: Failed to parse new XML data."

    # Extract the required items from the XML document and error if not valid
    next_field = 0
    next_map = {
        0: "uuid",
        1: "name",
        2: "memory",
        3: "vcpu",
        4: "networks",
        5: "disks",
    }
    try:
        dom_uuid = parsed_xml.uuid.text
        next_field += 1
        dom_name = parsed_xml.name.text
        next_field += 1
        parsed_memory = int(parsed_xml.memory.text)
        next_field += 1
        parsed_vcpu = int(parsed_xml.vcpu.text)
        next_field += 1
        dnetworks = common.getDomainNetworks(parsed_xml, {})
        next_field += 1
        ddisks = common.getDomainDisks(parsed_xml, {})
        next_field += 1
    except Exception as e:
        return (
            False,
            f'ERROR: Failed to parse XML data: field data for "{next_map[next_field]}" is not valid: {e}',
        )

    # Get our old network list for comparison purposes
    old_vm_config = zkhandler.read(("domain.xml", dom_uuid))
    old_parsed_xml = lxml.objectify.fromstring(old_vm_config)
    old_dnetworks = common.getDomainNetworks(old_parsed_xml, {})

    # Validate the new RAM against the current active node
    node_name = zkhandler.read(("domain.node", dom_uuid))
    node_total_memory = int(zkhandler.read(("node.memory.total", node_name)))
    if parsed_memory >= node_total_memory:
        return (
            False,
            'ERROR: Updated VM configuration specifies more memory ({} MiB) than node "{}" has available ({} MiB).'.format(
                parsed_memory, node_name, node_total_memory
            ),
        )

    # Validate the number of vCPUs against the current active node
    node_total_cpus = int(zkhandler.read(("node.data.static", node_name)).split()[0])
    if parsed_vcpu >= (node_total_cpus - 2):
        return (
            False,
            'ERROR: Updated VM configuration specifies more vCPUs ({}) than node "{}" has available ({} minus 2).'.format(
                parsed_vcpu, node_name, node_total_cpus
            ),
        )

    # If a SR-IOV network device is being added, set its used state
    for network in dnetworks:
        # Ignore networks that are already there
        if network["source"] in [net["source"] for net in old_dnetworks]:
            continue

        if network["type"] in ["direct", "hostdev"]:
            dom_node = zkhandler.read(("domain.node", dom_uuid))

            # Check if the network is already in use
            is_used = zkhandler.read(
                ("node.sriov.vf", dom_node, "sriov_vf.used", network["source"])
            )
            if is_used == "True":
                used_by_name = searchClusterByUUID(
                    zkhandler,
                    zkhandler.read(
                        (
                            "node.sriov.vf",
                            dom_node,
                            "sriov_vf.used_by",
                            network["source"],
                        )
                    ),
                )
                return (
                    False,
                    'ERROR: Attempted to use SR-IOV network "{}" which is already used by VM "{}" on node "{}".'.format(
                        network["source"], used_by_name, dom_node
                    ),
                )

            # We must update the "used" section
            set_sriov_vf_vm(
                zkhandler,
                dom_uuid,
                dom_node,
                network["source"],
                network["mac"],
                network["type"],
            )

    # If a SR-IOV network device is being removed, unset its used state
    for network in old_dnetworks:
        if network["type"] in ["direct", "hostdev"]:
            if network["mac"] not in [n["mac"] for n in dnetworks]:
                dom_node = zkhandler.read(("domain.node", dom_uuid))
                # We must update the "used" section
                unset_sriov_vf_vm(zkhandler, dom_node, network["source"])

    # Obtain the RBD disk list using the common functions
    rbd_list = []
    for disk in ddisks:
        if disk["type"] == "rbd":
            rbd_list.append(disk["name"])

    # Join the RBD list
    if isinstance(rbd_list, list) and rbd_list:
        formatted_rbd_list = ",".join(rbd_list)
    else:
        formatted_rbd_list = ""

    # Add the modified config to Zookeeper
    zkhandler.write(
        [
            (("domain", dom_uuid), dom_name),
            (("domain.storage.volumes", dom_uuid), formatted_rbd_list),
            (("domain.xml", dom_uuid), new_vm_config),
        ]
    )

    if restart:
        change_state(zkhandler, dom_uuid, "restart")

    return True, 'Successfully modified configuration of VM "{}".'.format(domain)


def dump_vm(zkhandler, domain):
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Gram the domain XML and dump it to stdout
    vm_xml = zkhandler.read(("domain.xml", dom_uuid))

    return True, vm_xml


def rename_vm(zkhandler, domain, new_domain):
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Verify that the VM is in a stopped state; renaming is not supported otherwise
    state = zkhandler.read(("domain.state", dom_uuid))
    if state not in ["stop", "disable"]:
        return (
            False,
            'ERROR: VM "{}" is not in stopped state; VMs cannot be renamed while running.'.format(
                domain
            ),
        )

    # Parse and valiate the XML
    vm_config = common.getDomainXML(zkhandler, dom_uuid)

    # Obtain the RBD disk list using the common functions
    ddisks = common.getDomainDisks(vm_config, {})
    pool_list = []
    rbd_list = []
    for disk in ddisks:
        if disk["type"] == "rbd":
            pool_list.append(disk["name"].split("/")[0])
            rbd_list.append(disk["name"].split("/")[1])

    # Rename each volume in turn
    for idx, rbd in enumerate(rbd_list):
        rbd_new = re.sub(r"{}".format(domain), new_domain, rbd)
        # Skip renaming if nothing changed
        if rbd_new == rbd:
            continue
        ceph.rename_volume(zkhandler, pool_list[idx], rbd, rbd_new)

    # Replace the name in the config
    vm_config_new = (
        lxml.etree.tostring(vm_config, encoding="ascii", method="xml")
        .decode()
        .replace(domain, new_domain)
    )

    # Get VM information
    _b, dom_info = get_info(zkhandler, dom_uuid)

    # Undefine the old VM
    undefine_vm(zkhandler, dom_uuid)

    # Define the new VM
    define_vm(
        zkhandler,
        vm_config_new,
        dom_info["node"],
        dom_info["node_limit"],
        dom_info["node_selector"],
        dom_info["node_autostart"],
        migration_method=dom_info["migration_method"],
        migration_max_downtime=dom_info["migration_max_downtime"],
        profile=dom_info["profile"],
        tags=dom_info["tags"],
        initial_state="stop",
    )

    # If the VM is migrated, store that
    if dom_info["migrated"] != "no":
        zkhandler.write([(("domain.last_node", dom_uuid), dom_info["last_node"])])

    return True, 'Successfully renamed VM "{}" to "{}".'.format(domain, new_domain)


def undefine_vm(zkhandler, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Shut down the VM
    current_vm_state = zkhandler.read(("domain.state", dom_uuid))
    if current_vm_state != "stop":
        change_state(zkhandler, dom_uuid, "stop")

    # Gracefully terminate the class instances
    change_state(zkhandler, dom_uuid, "delete")

    # Delete the configurations
    zkhandler.delete([("domain", dom_uuid)])

    return True, 'Undefined VM "{}" from the cluster.'.format(domain)


def remove_vm(zkhandler, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    disk_list = common.getDomainDiskList(zkhandler, dom_uuid)

    # Shut down the VM
    current_vm_state = zkhandler.read(("domain.state", dom_uuid))
    if current_vm_state != "stop":
        change_state(zkhandler, dom_uuid, "stop")

    # Wait for 1 second to allow state to flow to all nodes
    time.sleep(1)

    # Remove disks
    for disk in disk_list:
        # vmpool/vmname_volume
        try:
            disk_pool, disk_name = disk.split("/")
        except ValueError:
            continue

        retcode, message = ceph.remove_volume(zkhandler, disk_pool, disk_name)
        if not retcode:
            if re.match("^ERROR: No volume with name", message):
                continue
            else:
                return False, message

    # Gracefully terminate the class instances
    change_state(zkhandler, dom_uuid, "delete")

    # Wait for 1/2 second to allow state to flow to all nodes
    time.sleep(0.5)

    # Delete the VM configuration from Zookeeper
    zkhandler.delete([("domain", dom_uuid)])

    return True, 'Removed VM "{}" and its disks from the cluster.'.format(domain)


def start_vm(zkhandler, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Set the VM to start
    change_state(zkhandler, dom_uuid, "start")

    return True, 'Starting VM "{}".'.format(domain)


def restart_vm(zkhandler, domain, wait=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.read(("domain.state", dom_uuid))
    if current_state != "start":
        return False, 'ERROR: VM "{}" is not in "start" state!'.format(domain)

    retmsg = 'Restarting VM "{}".'.format(domain)

    # Set the VM to restart
    change_state(zkhandler, dom_uuid, "restart")

    if wait:
        while zkhandler.read(("domain.state", dom_uuid)) == "restart":
            time.sleep(0.5)
        retmsg = 'Restarted VM "{}"'.format(domain)

    return True, retmsg


def shutdown_vm(zkhandler, domain, wait=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.read(("domain.state", dom_uuid))
    if current_state != "start":
        return False, 'ERROR: VM "{}" is not in "start" state!'.format(domain)

    retmsg = 'Shutting down VM "{}"'.format(domain)

    # Set the VM to shutdown
    change_state(zkhandler, dom_uuid, "shutdown")

    if wait:
        while zkhandler.read(("domain.state", dom_uuid)) == "shutdown":
            time.sleep(0.5)
        retmsg = 'Shut down VM "{}"'.format(domain)

    return True, retmsg


def stop_vm(zkhandler, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Set the VM to stop
    change_state(zkhandler, dom_uuid, "stop")

    return True, 'Forcibly stopping VM "{}".'.format(domain)


def disable_vm(zkhandler, domain, force=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and perform a shutdown/stop if VM is online
    current_state = zkhandler.read(("domain.state", dom_uuid))
    if current_state in ["start"]:
        if force:
            change_state(zkhandler, dom_uuid, "stop")
            # Wait for the command to be registered by the node
            time.sleep(0.5)
        else:
            change_state(zkhandler, dom_uuid, "shutdown")
            # Wait for the shutdown to complete
            while zkhandler.read(("domain.state", dom_uuid)) != "stop":
                time.sleep(0.5)

    # Set the VM to disable
    change_state(zkhandler, dom_uuid, "disable")

    return True, 'Disabled VM "{}".'.format(domain)


def update_vm_sriov_nics(zkhandler, dom_uuid, source_node, target_node):
    # Update all the SR-IOV device states on both nodes, used during migrations but called by the node-side
    vm_config = zkhandler.read(("domain.xml", dom_uuid))
    parsed_xml = lxml.objectify.fromstring(vm_config)
    # Extract the required items from the XML document and error if not valid
    try:
        dnetworks = common.getDomainNetworks(parsed_xml, {})
    except Exception as e:
        return (
            False,
            f'ERROR: Failed to parse XML data: field data for "networks" is not valid: {e}',
        )

    retcode = True
    retmsg = ""
    for network in dnetworks:
        if network["type"] in ["direct", "hostdev"]:
            # Check if the network is already in use
            is_used = zkhandler.read(
                ("node.sriov.vf", target_node, "sriov_vf.used", network["source"])
            )
            if is_used == "True":
                used_by_name = searchClusterByUUID(
                    zkhandler,
                    zkhandler.read(
                        (
                            "node.sriov.vf",
                            target_node,
                            "sriov_vf.used_by",
                            network["source"],
                        )
                    ),
                )
                if retcode:
                    retcode_this = False
                    retmsg = 'Attempting to use SR-IOV network "{}" which is already used by VM "{}"'.format(
                        network["source"], used_by_name
                    )
            else:
                retcode_this = True

            # We must update the "used" section
            if retcode_this:
                # This conditional ensure that if we failed the is_used check, we don't try to overwrite the information of a VF that belongs to another VM
                set_sriov_vf_vm(
                    zkhandler,
                    dom_uuid,
                    target_node,
                    network["source"],
                    network["mac"],
                    network["type"],
                )
            # ... but we still want to free the old node in an case
            unset_sriov_vf_vm(zkhandler, source_node, network["source"])

            if not retcode_this:
                retcode = retcode_this

    return retcode, retmsg


def move_vm(zkhandler, domain, target_node, wait=False, force_live=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.read(("domain.state", dom_uuid))
    if current_state != "start":
        # If the current state isn't start, preserve it; we're not doing live migration
        target_state = current_state
    else:
        if force_live:
            target_state = "migrate-live"
        else:
            target_state = "migrate"

    current_node = zkhandler.read(("domain.node", dom_uuid))

    if not target_node:
        target_node = common.findTargetNode(zkhandler, dom_uuid)
    else:
        # Verify node is valid
        valid_node = common.verifyNode(zkhandler, target_node)
        if not valid_node:
            return False, 'ERROR: Specified node "{}" is invalid.'.format(target_node)

        # Check if node is within the limit
        node_limit = zkhandler.read(("domain.meta.node_limit", dom_uuid))
        if node_limit and target_node not in node_limit.split(","):
            return (
                False,
                'ERROR: Specified node "{}" is not in the allowed list of nodes for VM "{}".'.format(
                    target_node, domain
                ),
            )

        # Verify if node is current node
        if target_node == current_node:
            last_node = zkhandler.read(("domain.last_node", dom_uuid))
            if last_node:
                zkhandler.write([(("domain.last_node", dom_uuid), "")])
                return True, 'Making temporary migration permanent for VM "{}".'.format(
                    domain
                )

            return False, 'ERROR: VM "{}" is already running on node "{}".'.format(
                domain, current_node
            )

    if not target_node:
        return (
            False,
            'ERROR: Could not find a valid migration target for VM "{}".'.format(
                domain
            ),
        )

    retmsg = 'Permanently migrating VM "{}" to node "{}".'.format(domain, target_node)

    lock = zkhandler.exclusivelock(("domain.state", dom_uuid))
    with lock:
        zkhandler.write(
            [
                (("domain.state", dom_uuid), target_state),
                (("domain.node", dom_uuid), target_node),
                (("domain.last_node", dom_uuid), ""),
            ]
        )

        # Wait for 1/2 second for migration to start
        time.sleep(0.5)

    # Update any SR-IOV NICs
    update_vm_sriov_nics(zkhandler, dom_uuid, current_node, target_node)

    if wait:
        while zkhandler.read(("domain.state", dom_uuid)) == target_state:
            time.sleep(0.5)
        retmsg = 'Permanently migrated VM "{}" to node "{}"'.format(domain, target_node)

    return True, retmsg


def migrate_vm(
    zkhandler, domain, target_node, force_migrate, wait=False, force_live=False
):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.read(("domain.state", dom_uuid))
    if current_state != "start":
        # If the current state isn't start, preserve it; we're not doing live migration
        target_state = current_state
    else:
        if force_live:
            target_state = "migrate-live"
        else:
            target_state = "migrate"

    current_node = zkhandler.read(("domain.node", dom_uuid))
    last_node = zkhandler.read(("domain.last_node", dom_uuid))

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
        node_limit = zkhandler.read(("domain.meta.node_limit", dom_uuid))
        if node_limit and target_node not in node_limit.split(","):
            return (
                False,
                'ERROR: Specified node "{}" is not in the allowed list of nodes for VM "{}".'.format(
                    target_node, domain
                ),
            )

        # Verify if node is current node
        if target_node == current_node:
            return False, 'ERROR: VM "{}" is already running on node "{}".'.format(
                domain, current_node
            )

    if not target_node:
        return (
            False,
            'ERROR: Could not find a valid migration target for VM "{}".'.format(
                domain
            ),
        )

    # Don't overwrite an existing last_node when using force_migrate
    real_current_node = current_node  # Used for the SR-IOV update
    if last_node and force_migrate:
        current_node = last_node

    retmsg = 'Migrating VM "{}" to node "{}".'.format(domain, target_node)

    lock = zkhandler.exclusivelock(("domain.state", dom_uuid))
    with lock:
        zkhandler.write(
            [
                (("domain.state", dom_uuid), target_state),
                (("domain.node", dom_uuid), target_node),
                (("domain.last_node", dom_uuid), current_node),
            ]
        )

        # Wait for 1/2 second for migration to start
        time.sleep(0.5)

    # Update any SR-IOV NICs
    update_vm_sriov_nics(zkhandler, dom_uuid, real_current_node, target_node)

    if wait:
        while zkhandler.read(("domain.state", dom_uuid)) == target_state:
            time.sleep(0.5)
        retmsg = 'Migrated VM "{}" to node "{}"'.format(domain, target_node)

    return True, retmsg


def unmigrate_vm(zkhandler, domain, wait=False, force_live=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and verify we're OK to proceed
    current_state = zkhandler.read(("domain.state", dom_uuid))
    if current_state != "start":
        # If the current state isn't start, preserve it; we're not doing live migration
        target_state = current_state
    else:
        if force_live:
            target_state = "migrate-live"
        else:
            target_state = "migrate"

    current_node = zkhandler.read(("domain.node", dom_uuid))
    target_node = zkhandler.read(("domain.last_node", dom_uuid))

    if target_node == "":
        return False, 'ERROR: VM "{}" has not been previously migrated.'.format(domain)

    retmsg = 'Unmigrating VM "{}" back to node "{}".'.format(domain, target_node)

    lock = zkhandler.exclusivelock(("domain.state", dom_uuid))
    with lock:
        zkhandler.write(
            [
                (("domain.state", dom_uuid), target_state),
                (("domain.node", dom_uuid), target_node),
                (("domain.last_node", dom_uuid), ""),
            ]
        )

        # Wait for 1/2 second for migration to start
        time.sleep(0.5)

    # Update any SR-IOV NICs
    update_vm_sriov_nics(zkhandler, dom_uuid, current_node, target_node)

    if wait:
        while zkhandler.read(("domain.state", dom_uuid)) == target_state:
            time.sleep(0.5)
        retmsg = 'Unmigrated VM "{}" back to node "{}"'.format(domain, target_node)

    return True, retmsg


def get_console_log(zkhandler, domain, lines=1000):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get the data from ZK
    console_log = zkhandler.read(("domain.console.log", dom_uuid))

    if console_log is None:
        return True, ""

    # Shrink the log buffer to length lines
    shrunk_log = console_log.split("\n")[-lines:]
    loglines = "\n".join(shrunk_log)

    return True, loglines


def get_info(zkhandler, domain):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: No VM named "{}" is present in the cluster.'.format(
            domain
        )

    # Gather information from XML config and print it
    domain_information = common.getInformationFromXML(zkhandler, dom_uuid)
    if not domain_information:
        return False, 'ERROR: Could not get information about VM "{}".'.format(domain)

    return True, domain_information


def get_list(
    zkhandler, node=None, state=None, tag=None, limit=None, is_fuzzy=True, negate=False
):
    if node is not None:
        # Verify node is valid
        if not common.verifyNode(zkhandler, node):
            return False, 'Specified node "{}" is invalid.'.format(node)

    if state is not None:
        valid_states = [
            "start",
            "restart",
            "shutdown",
            "stop",
            "disable",
            "fail",
            "migrate",
            "unmigrate",
            "provision",
        ]
        if state not in valid_states:
            return False, 'VM state "{}" is not valid.'.format(state)

    full_vm_list = zkhandler.children("base.domain")
    full_vm_list.sort()

    # Set our limit to a sensible regex
    if limit is not None:
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
                if not re.match(r"\^.*", limit):
                    limit = ".*" + limit
                if not re.match(r".*\$", limit):
                    limit = limit + ".*"
            except Exception as e:
                return False, "Regex Error: {}".format(e)

    get_vm_info = dict()
    for vm in full_vm_list:
        name = zkhandler.read(("domain", vm))
        is_limit_match = False
        is_tag_match = False
        is_node_match = False
        is_state_match = False

        # Check on limit
        if limit is not None:
            # Try to match the limit against the UUID (if applicable) and name
            try:
                if is_limit_uuid and re.fullmatch(limit, vm):
                    is_limit_match = True
                if re.fullmatch(limit, name):
                    is_limit_match = True
            except Exception as e:
                return False, "Regex Error: {}".format(e)
        else:
            is_limit_match = True

        if tag is not None:
            vm_tags = zkhandler.children(("domain.meta.tags", vm))
            if negate and tag not in vm_tags:
                is_tag_match = True
            if not negate and tag in vm_tags:
                is_tag_match = True
        else:
            is_tag_match = True

        # Check on node
        if node is not None:
            vm_node = zkhandler.read(("domain.node", vm))
            if negate and vm_node != node:
                is_node_match = True
            if not negate and vm_node == node:
                is_node_match = True
        else:
            is_node_match = True

        # Check on state
        if state is not None:
            vm_state = zkhandler.read(("domain.state", vm))
            if negate and vm_state != state:
                is_state_match = True
            if not negate and vm_state == state:
                is_state_match = True
        else:
            is_state_match = True

        get_vm_info[vm] = (
            True
            if is_limit_match and is_tag_match and is_node_match and is_state_match
            else False
        )

    # Obtain our VM data in a thread pool
    # This helps parallelize the numerous Zookeeper calls a bit, within the bounds of the GIL, and
    # should help prevent this task from becoming absurdly slow with very large numbers of VMs.
    # The max_workers is capped at 32 to avoid creating an absurd number of threads especially if
    # the list gets called multiple times simultaneously by the API, but still provides a noticeable
    # speedup.
    vm_execute_list = [vm for vm in full_vm_list if get_vm_info[vm]]
    vm_data_list = list()
    with ThreadPoolExecutor(max_workers=32, thread_name_prefix="vm_list") as executor:
        futures = []
        for vm_uuid in vm_execute_list:
            futures.append(
                executor.submit(common.getInformationFromXML, zkhandler, vm_uuid)
            )
        for future in futures:
            try:
                vm_data_list.append(future.result())
            except Exception:
                pass

    return True, sorted(vm_data_list, key=lambda d: d["name"])


def backup_vm(
    zkhandler, domain, backup_path, incremental_parent=None, retain_snapshot=False
):
    # 0a. Set datestring in YYYYMMDDHHMMSS format
    now = datetime.now()
    datestring = now.strftime("%Y%m%d%H%M%S")

    snapshot_name = f"backup_{datestring}"

    # 0b. Validations part 1
    # Validate that the target path is valid
    if not re.match(r"^/", backup_path):
        return (
            False,
            f"ERROR in backup {datestring}: Target path {backup_path} is not a valid absolute path on the primary coordinator!",
        )

    # Ensure that backup_path (on this node) exists
    if not os.path.isdir(backup_path):
        return (
            False,
            f"ERROR in backup {datestring}: Target path {backup_path} does not exist!",
        )

    # 1a. Create destination directory
    vm_target_root = f"{backup_path}/{domain}"
    vm_target_backup = f"{backup_path}/{domain}/{datestring}/pvcdisks"
    if not os.path.isdir(vm_target_backup):
        try:
            os.makedirs(vm_target_backup)
        except Exception as e:
            return (
                False,
                f"ERROR in backup {datestring}: Failed to create backup directory: {e}",
            )

    tstart = time.time()
    backup_type = "incremental" if incremental_parent is not None else "full"

    # 1b. Prepare backup JSON write (it will write on any result
    def write_pvcbackup_json(
        result=False,
        result_message="",
        vm_detail=None,
        backup_files=None,
        backup_files_size=0,
        ttot=None,
    ):
        if ttot is None:
            tend = time.time()
            ttot = round(tend - tstart, 2)

        backup_details = {
            "type": backup_type,
            "datestring": datestring,
            "incremental_parent": incremental_parent,
            "retained_snapshot": retain_snapshot,
            "result": result,
            "result_message": result_message,
            "runtime_secs": ttot,
            "vm_detail": vm_detail,
            "backup_files": backup_files,
            "backup_size_bytes": backup_files_size,
        }
        with open(f"{vm_target_root}/{datestring}/pvcbackup.json", "w") as fh:
            jdump(backup_details, fh)

    # 2. Validations part 2
    # Disallow retaining snapshots with an incremental parent
    if incremental_parent is not None and retain_snapshot:
        error_message = "Retaining snapshots of incremental backups is not supported!"
        write_pvcbackup_json(result=False, result_message=f"ERROR: {error_message}")
        return (
            False,
            f"ERROR in backup {datestring}: {error_message}",
        )

    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        error_message = f'Could not find VM "{domain}" in the cluster!'
        write_pvcbackup_json(result=False, result_message=f"ERROR: {error_message}")
        return False, f"ERROR in backup {datestring}: {error_message}"

    # 3. Get information about VM
    vm_detail = get_list(zkhandler, limit=dom_uuid, is_fuzzy=False)[1][0]
    if not isinstance(vm_detail, dict):
        error_message = f"VM listing returned invalid data: {vm_detail}"
        write_pvcbackup_json(result=False, result_message=f"ERROR: {error_message}")
        return False, f"ERROR in backup {datestring}: {error_message}"

    vm_volumes = list()
    for disk in vm_detail["disks"]:
        if disk["type"] != "rbd":
            continue

        pool, volume = disk["name"].split("/")

        retcode, retdata = ceph.get_list_volume(zkhandler, pool, volume, is_fuzzy=False)
        if not retcode or len(retdata) != 1:
            if len(retdata) < 1:
                retdata = "No volumes returned."
            elif len(retdata) > 1:
                retdata = "Multiple volumes returned."

            error_message = (
                f"Failed to get volume details for {pool}/{volume}: {retdata}"
            )
            write_pvcbackup_json(
                result=False,
                result_message=f"ERROR: {error_message}",
                vm_detail=vm_detail,
            )
            return (
                False,
                f"ERROR in backup {datestring}: {error_message}",
            )

        try:
            size = retdata[0]["stats"]["size"]
        except Exception as e:
            error_message = f"Failed to get volume size for {pool}/{volume}: {e}"
            write_pvcbackup_json(
                result=False,
                result_message=f"ERROR: {error_message}",
                vm_detail=vm_detail,
            )
            return (
                False,
                f"ERROR in backup {datestring}: {error_message}",
            )

        vm_volumes.append((pool, volume, size))

    # 4a. Validate that all volumes exist (they should, but just in case)
    for pool, volume, _ in vm_volumes:
        if not ceph.verifyVolume(zkhandler, pool, volume):
            error_message = f"VM defines a volume {pool}/{volume} which does not exist!"
            write_pvcbackup_json(
                result=False,
                result_message=f"ERROR: {error_message}",
                vm_detail=vm_detail,
            )
            return (
                False,
                f"ERROR in backup {datestring}: {error_message}",
            )

    # 4b. Validate that, if an incremental_parent is given, it is valid
    # The incremental parent is just a datestring
    if incremental_parent is not None:
        for pool, volume, _ in vm_volumes:
            if not ceph.verifySnapshot(
                zkhandler, pool, volume, f"backup_{incremental_parent}"
            ):
                error_message = f"Incremental parent {incremental_parent} given, but no snapshots were found; cannot export an incremental backup."
                write_pvcbackup_json(
                    result=False,
                    result_message=f"ERROR: {error_message}",
                    vm_detail=vm_detail,
                )
                return (
                    False,
                    f"ERROR in backup {datestring}: {error_message}",
                )

        export_fileext = "rbddiff"
    else:
        export_fileext = "rbdimg"

    # 4c. Validate that there's enough space on the target
    # TODO

    # 5. Take snapshot of each disks with the name @backup_{datestring}
    is_snapshot_create_failed = False
    which_snapshot_create_failed = list()
    for pool, volume, _ in vm_volumes:
        retcode, retmsg = ceph.add_snapshot(zkhandler, pool, volume, snapshot_name)
        if not retcode:
            is_snapshot_create_failed = True
            which_snapshot_create_failed.append(f"{pool}/{volume}")

    if is_snapshot_create_failed:
        for pool, volume, _ in vm_volumes:
            if ceph.verifySnapshot(zkhandler, pool, volume, snapshot_name):
                ceph.remove_snapshot(zkhandler, pool, volume, snapshot_name)

        error_message = f'Failed to create snapshot for volume(s) {", ".join(which_snapshot_create_failed)}'
        write_pvcbackup_json(
            result=False,
            result_message=f"ERROR: {error_message}",
            vm_detail=vm_detail,
        )
        return (
            False,
            f"ERROR in backup {datestring}: {error_message}",
        )

    # 6. Dump snapshot to folder with `rbd export` (full) or `rbd export-diff` (incremental)
    is_snapshot_export_failed = False
    which_snapshot_export_failed = list()
    backup_files = list()
    for pool, volume, size in vm_volumes:
        if incremental_parent is not None:
            incremental_parent_snapshot_name = f"backup_{incremental_parent}"
            retcode, stdout, stderr = common.run_os_command(
                f"rbd export-diff --from-snap {incremental_parent_snapshot_name} {pool}/{volume}@{snapshot_name} {vm_target_backup}/{pool}.{volume}.{export_fileext}"
            )
            if retcode:
                is_snapshot_export_failed = True
                which_snapshot_export_failed.append(f"{pool}/{volume}")
            else:
                backup_files.append(
                    (f"pvcdisks/{pool}.{volume}.{export_fileext}", size)
                )
        else:
            retcode, stdout, stderr = common.run_os_command(
                f"rbd export --export-format 2 {pool}/{volume}@{snapshot_name} {vm_target_backup}/{pool}.{volume}.{export_fileext}"
            )
            if retcode:
                is_snapshot_export_failed = True
                which_snapshot_export_failed.append(f"{pool}/{volume}")
            else:
                backup_files.append(
                    (f"pvcdisks/{pool}.{volume}.{export_fileext}", size)
                )

    def get_dir_size(path):
        total = 0
        with scandir(path) as it:
            for entry in it:
                if entry.is_file():
                    total += entry.stat().st_size
                elif entry.is_dir():
                    total += get_dir_size(entry.path)
        return total

    backup_files_size = get_dir_size(vm_target_backup)

    if is_snapshot_export_failed:
        for pool, volume, _ in vm_volumes:
            if ceph.verifySnapshot(zkhandler, pool, volume, snapshot_name):
                ceph.remove_snapshot(zkhandler, pool, volume, snapshot_name)

        error_message = f'Failed to export snapshot for volume(s) {", ".join(which_snapshot_export_failed)}'
        write_pvcbackup_json(
            result=False,
            result_message=f"ERROR: {error_message}",
            vm_detail=vm_detail,
            backup_files=backup_files,
            backup_files_size=backup_files_size,
        )
        return (
            False,
            f"ERROR in backup {datestring}: {error_message}",
        )

    # 8. Remove snapshots if retain_snapshot is False
    is_snapshot_remove_failed = False
    which_snapshot_remove_failed = list()
    if not retain_snapshot:
        for pool, volume, _ in vm_volumes:
            if ceph.verifySnapshot(zkhandler, pool, volume, snapshot_name):
                retcode, retmsg = ceph.remove_snapshot(
                    zkhandler, pool, volume, snapshot_name
                )
                if not retcode:
                    is_snapshot_remove_failed = True
                    which_snapshot_remove_failed.append(f"{pool}/{volume}")

    tend = time.time()
    ttot = round(tend - tstart, 2)

    retlines = list()

    if is_snapshot_remove_failed:
        retlines.append(
            f"WARNING: Failed to remove snapshot(s) as requested for volume(s) {', '.join(which_snapshot_remove_failed)}"
        )

    myhostname = gethostname().split(".")[0]
    if retain_snapshot:
        result_message = f"Successfully backed up VM '{domain}' ({backup_type}@{datestring}, snapshots retained) to '{myhostname}:{backup_path}' in {ttot}s."
    else:
        result_message = f"Successfully backed up VM '{domain}' ({backup_type}@{datestring}) to '{myhostname}:{backup_path}' in {ttot}s."
    retlines.append(result_message)

    write_pvcbackup_json(
        result=True,
        result_message=result_message,
        vm_detail=vm_detail,
        backup_files=backup_files,
        backup_files_size=backup_files_size,
        ttot=ttot,
    )

    return True, "\n".join(retlines)


def remove_backup(zkhandler, domain, backup_path, datestring):
    tstart = time.time()

    # 0. Validation
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Validate that the source path is valid
    if not re.match(r"^/", backup_path):
        return (
            False,
            f"ERROR: Source path {backup_path} is not a valid absolute path on the primary coordinator!",
        )

    # Ensure that backup_path (on this node) exists
    if not os.path.isdir(backup_path):
        return False, f"ERROR: Source path {backup_path} does not exist!"

    # Ensure that domain path (on this node) exists
    vm_backup_path = f"{backup_path}/{domain}"
    if not os.path.isdir(vm_backup_path):
        return False, f"ERROR: Source VM path {vm_backup_path} does not exist!"

    # Ensure that the archives are present
    backup_source_pvcbackup_file = f"{vm_backup_path}/{datestring}/pvcbackup.json"
    if not os.path.isfile(backup_source_pvcbackup_file):
        return False, "ERROR: The specified source backup files do not exist!"

    backup_source_pvcdisks_path = f"{vm_backup_path}/{datestring}/pvcdisks"
    if not os.path.isdir(backup_source_pvcdisks_path):
        return False, "ERROR: The specified source backup files do not exist!"

    # 1. Read the backup file and get VM details
    try:
        with open(backup_source_pvcbackup_file) as fh:
            backup_source_details = jload(fh)
    except Exception as e:
        return False, f"ERROR: Failed to read source backup details: {e}"

    # 2. Remove snapshots
    is_snapshot_remove_failed = False
    which_snapshot_remove_failed = list()
    if backup_source_details["retained_snapshot"]:
        for volume_file, _ in backup_source_details.get("backup_files"):
            pool, volume, _ = volume_file.split("/")[-1].split(".")
            snapshot = f"backup_{datestring}"
            retcode, retmsg = ceph.remove_snapshot(zkhandler, pool, volume, snapshot)
            if not retcode:
                is_snapshot_remove_failed = True
                which_snapshot_remove_failed.append(f"{pool}/{volume}")

    # 3. Remove files
    is_files_remove_failed = False
    msg_files_remove_failed = None
    try:
        rmtree(f"{vm_backup_path}/{datestring}")
    except Exception as e:
        is_files_remove_failed = True
        msg_files_remove_failed = e

    tend = time.time()
    ttot = round(tend - tstart, 2)
    retlines = list()

    if is_snapshot_remove_failed:
        retlines.append(
            f"WARNING: Failed to remove snapshot(s) as requested for volume(s) {', '.join(which_snapshot_remove_failed)}"
        )

    if is_files_remove_failed:
        retlines.append(
            f"WARNING: Failed to remove backup file(s) from {backup_path}: {msg_files_remove_failed}"
        )

    myhostname = gethostname().split(".")[0]
    retlines.append(
        f"Removed VM backup {datestring} for '{domain}' from '{myhostname}:{backup_path}' in {ttot}s."
    )

    return True, "\n".join(retlines)


def restore_vm(zkhandler, domain, backup_path, datestring, retain_snapshot=False):
    tstart = time.time()

    # 0. Validations
    # Validate that VM does not exist in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if dom_uuid:
        return (
            False,
            f'ERROR: VM "{domain}" already exists in the cluster! Remove or rename it before restoring a backup.',
        )

    # Validate that the source path is valid
    if not re.match(r"^/", backup_path):
        return (
            False,
            f"ERROR: Source path {backup_path} is not a valid absolute path on the primary coordinator!",
        )

    # Ensure that backup_path (on this node) exists
    if not os.path.isdir(backup_path):
        return False, f"ERROR: Source path {backup_path} does not exist!"

    # Ensure that domain path (on this node) exists
    vm_backup_path = f"{backup_path}/{domain}"
    if not os.path.isdir(vm_backup_path):
        return False, f"ERROR: Source VM path {vm_backup_path} does not exist!"

    # Ensure that the archives are present
    backup_source_pvcbackup_file = f"{vm_backup_path}/{datestring}/pvcbackup.json"
    if not os.path.isfile(backup_source_pvcbackup_file):
        return False, "ERROR: The specified source backup files do not exist!"

    # 1. Read the backup file and get VM details
    try:
        with open(backup_source_pvcbackup_file) as fh:
            backup_source_details = jload(fh)
    except Exception as e:
        return False, f"ERROR: Failed to read source backup details: {e}"

    # Handle incrementals
    incremental_parent = backup_source_details.get("incremental_parent", None)
    if incremental_parent is not None:
        backup_source_parent_pvcbackup_file = (
            f"{vm_backup_path}/{incremental_parent}/pvcbackup.json"
        )
        if not os.path.isfile(backup_source_parent_pvcbackup_file):
            return (
                False,
                "ERROR: The specified backup is incremental but the required incremental parent source backup files do not exist!",
            )

        try:
            with open(backup_source_parent_pvcbackup_file) as fh:
                backup_source_parent_details = jload(fh)
        except Exception as e:
            return (
                False,
                f"ERROR: Failed to read source incremental parent backup details: {e}",
            )

    # 2. Import VM config and metadata in provision state
    try:
        retcode, retmsg = define_vm(
            zkhandler,
            backup_source_details["vm_detail"]["xml"],
            backup_source_details["vm_detail"]["node"],
            backup_source_details["vm_detail"]["node_limit"],
            backup_source_details["vm_detail"]["node_selector"],
            backup_source_details["vm_detail"]["node_autostart"],
            backup_source_details["vm_detail"]["migration_method"],
            backup_source_details["vm_detail"]["migration_max_downtime"],
            backup_source_details["vm_detail"]["profile"],
            backup_source_details["vm_detail"]["tags"],
            "restore",
        )
        if not retcode:
            return False, f"ERROR: Failed to define restored VM: {retmsg}"
    except Exception as e:
        return False, f"ERROR: Failed to parse VM backup details: {e}"

    # 4. Import volumes
    is_snapshot_remove_failed = False
    which_snapshot_remove_failed = list()
    if incremental_parent is not None:
        for volume_file, volume_size in backup_source_details.get("backup_files"):
            pool, volume, _ = volume_file.split("/")[-1].split(".")
            try:
                parent_volume_file = [
                    f[0]
                    for f in backup_source_parent_details.get("backup_files")
                    if f[0].split("/")[-1].replace(".rbdimg", "")
                    == volume_file.split("/")[-1].replace(".rbddiff", "")
                ][0]
            except Exception as e:
                return (
                    False,
                    f"ERROR: Failed to find parent volume for volume {pool}/{volume}; backup may be corrupt or invalid: {e}",
                )

            # First we create the expected volumes then clean them up
            #   This process is a bit of a hack because rbd import does not expect an existing volume,
            #   but we need the information in PVC.
            #   Thus create the RBD volume using ceph.add_volume based on the backup size, and then
            #   manually remove the RBD volume (leaving the PVC metainfo)
            retcode, retmsg = ceph.add_volume(zkhandler, pool, volume, volume_size)
            if not retcode:
                return False, f"ERROR: Failed to create restored volume: {retmsg}"

            retcode, stdout, stderr = common.run_os_command(
                f"rbd remove {pool}/{volume}"
            )
            if retcode:
                return (
                    False,
                    f"ERROR: Failed to remove temporary RBD volume '{pool}/{volume}': {stderr}",
                )

            # Next we import the parent images
            retcode, stdout, stderr = common.run_os_command(
                f"rbd import --export-format 2 --dest-pool {pool} {backup_path}/{domain}/{incremental_parent}/{parent_volume_file} {volume}"
            )
            if retcode:
                return (
                    False,
                    f"ERROR: Failed to import parent backup image {parent_volume_file}: {stderr}",
                )

            # Then we import the incremental diffs
            retcode, stdout, stderr = common.run_os_command(
                f"rbd import-diff {backup_path}/{domain}/{datestring}/{volume_file} {pool}/{volume}"
            )
            if retcode:
                return (
                    False,
                    f"ERROR: Failed to import incremental backup image {volume_file}: {stderr}",
                )

            # Finally we remove the parent and child snapshots (no longer required required)
            if retain_snapshot:
                retcode, retmsg = ceph.add_snapshot(
                    zkhandler,
                    pool,
                    volume,
                    f"backup_{incremental_parent}",
                    zk_only=True,
                )
                if not retcode:
                    return (
                        False,
                        f"ERROR: Failed to add imported image snapshot for {parent_volume_file}: {retmsg}",
                    )
            else:
                retcode, stdout, stderr = common.run_os_command(
                    f"rbd snap rm {pool}/{volume}@backup_{incremental_parent}"
                )
                if retcode:
                    is_snapshot_remove_failed = True
                    which_snapshot_remove_failed.append(f"{pool}/{volume}")
            retcode, stdout, stderr = common.run_os_command(
                f"rbd snap rm {pool}/{volume}@backup_{datestring}"
            )
            if retcode:
                is_snapshot_remove_failed = True
                which_snapshot_remove_failed.append(f"{pool}/{volume}")

    else:
        for volume_file, volume_size in backup_source_details.get("backup_files"):
            pool, volume, _ = volume_file.split("/")[-1].split(".")

            # First we create the expected volumes then clean them up
            #   This process is a bit of a hack because rbd import does not expect an existing volume,
            #   but we need the information in PVC.
            #   Thus create the RBD volume using ceph.add_volume based on the backup size, and then
            #   manually remove the RBD volume (leaving the PVC metainfo)
            retcode, retmsg = ceph.add_volume(zkhandler, pool, volume, volume_size)
            if not retcode:
                return False, f"ERROR: Failed to create restored volume: {retmsg}"

            retcode, stdout, stderr = common.run_os_command(
                f"rbd remove {pool}/{volume}"
            )
            if retcode:
                return (
                    False,
                    f"ERROR: Failed to remove temporary RBD volume '{pool}/{volume}': {stderr}",
                )

            # Then we perform the actual import
            retcode, stdout, stderr = common.run_os_command(
                f"rbd import --export-format 2 --dest-pool {pool} {backup_path}/{domain}/{datestring}/{volume_file} {volume}"
            )
            if retcode:
                return (
                    False,
                    f"ERROR: Failed to import backup image {volume_file}: {stderr}",
                )

            # Finally we remove the source snapshot (not required)
            if retain_snapshot:
                retcode, retmsg = ceph.add_snapshot(
                    zkhandler,
                    pool,
                    volume,
                    f"backup_{datestring}",
                    zk_only=True,
                )
                if not retcode:
                    return (
                        False,
                        f"ERROR: Failed to add imported image snapshot for {volume_file}: {retmsg}",
                    )
            else:
                retcode, stdout, stderr = common.run_os_command(
                    f"rbd snap rm {pool}/{volume}@backup_{datestring}"
                )
                if retcode:
                    return (
                        False,
                        f"ERROR: Failed to remove imported image snapshot for {volume_file}: {stderr}",
                    )

    # 5. Start VM
    retcode, retmsg = start_vm(zkhandler, domain)
    if not retcode:
        return False, f"ERROR: Failed to start restored VM {domain}: {retmsg}"

    tend = time.time()
    ttot = round(tend - tstart, 2)
    retlines = list()

    if is_snapshot_remove_failed:
        retlines.append(
            f"WARNING: Failed to remove hanging snapshot(s) as requested for volume(s) {', '.join(which_snapshot_remove_failed)}"
        )

    myhostname = gethostname().split(".")[0]
    retlines.append(
        f"Successfully restored VM backup {datestring} for '{domain}' from '{myhostname}:{backup_path}' in {ttot}s."
    )

    return True, "\n".join(retlines)


#
# Celery worker tasks (must be run on node, outputs log messages to worker)
#
def vm_worker_helper_getdom(tuuid):
    lv_conn = None
    libvirt_uri = "qemu:///system"

    # Convert (text) UUID into bytes
    buuid = UUID(tuuid).bytes

    try:
        lv_conn = lvopen(libvirt_uri)
        if lv_conn is None:
            raise Exception("Failed to open local libvirt connection")

        # Lookup the UUID
        dom = lv_conn.lookupByUUID(buuid)
    except Exception as e:
        print(f"Error: {e}")
        dom = None
    finally:
        if lv_conn is not None:
            lv_conn.close()

    return dom


def vm_worker_flush_locks(zkhandler, celery, domain, force_unlock=False):
    current_stage = 0
    total_stages = 3

    start(
        celery,
        f"Flushing RBD locks for VM {domain} [forced={force_unlock}]",
        current=current_stage,
        total=total_stages,
    )

    dom_uuid = getDomainUUID(zkhandler, domain)

    # Check that the domain is stopped (unless force_unlock is set)
    domain_state = zkhandler.read(("domain.state", dom_uuid))
    if not force_unlock and domain_state not in ["stop", "disable", "fail"]:
        fail(
            celery,
            f"VM state {domain_state} not in [stop, disable, fail] and not forcing",
        )
        return

    # Get the list of RBD images
    rbd_list = zkhandler.read(("domain.storage.volumes", dom_uuid)).split(",")

    current_stage += 1
    update(
        celery,
        f"Obtaining RBD locks for VM {domain}",
        current=current_stage,
        total=total_stages,
    )

    # Prepare a list of locks
    rbd_locks = list()
    for rbd in rbd_list:
        # Check if a lock exists
        (
            lock_list_retcode,
            lock_list_stdout,
            lock_list_stderr,
        ) = common.run_os_command(f"rbd lock list --format json {rbd}")

        if lock_list_retcode != 0:
            fail(
                celery,
                f"Failed to obtain lock list for volume {rbd}: {lock_list_stderr}",
            )
            return

        try:
            lock_list = jloads(lock_list_stdout)
        except Exception as e:
            fail(
                celery,
                f"Failed to parse JSON lock list for volume {rbd}: {e}",
            )
            return

        if lock_list:
            for lock in lock_list:
                rbd_locks.append({"rbd": rbd, "lock": lock})

    current_stage += 1
    update(
        celery,
        f"Freeing RBD locks for VM {domain}",
        current=current_stage,
        total=total_stages,
    )

    for _lock in rbd_locks:
        rbd = _lock["rbd"]
        lock = _lock["lock"]

        (
            lock_remove_retcode,
            lock_remove_stdout,
            lock_remove_stderr,
        ) = common.run_os_command(
            f"rbd lock remove {rbd} \"{lock['id']}\" \"{lock['locker']}\""
        )

        if lock_remove_retcode != 0:
            fail(
                celery,
                f"Failed to free RBD lock {lock['id']} on volume {rbd}: {lock_remove_stderr}",
            )
            return

    current_stage += 1
    return finish(
        celery,
        f"Successfully flushed RBD locks for VM {domain}",
        current=4,
        total=4,
    )


def vm_worker_attach_device(zkhandler, celery, domain, xml_spec):
    current_stage = 0
    total_stages = 1

    start(
        celery,
        f"Hot-attaching XML device to VM {domain}",
        current=current_stage,
        total=total_stages,
    )

    dom_uuid = getDomainUUID(zkhandler, domain)

    state = zkhandler.read(("domain.state", dom_uuid))
    if state not in ["start"]:
        fail(
            celery,
            f"VM {domain} not in start state; hot-attach unnecessary or impossible",
        )
        return

    dom = vm_worker_helper_getdom(dom_uuid)
    if dom is None:
        fail(
            celery,
            f"Failed to find Libvirt object for VM {domain}",
        )
        return

    try:
        dom.attachDevice(xml_spec)
    except Exception as e:
        fail(celery, e)
        return

    current_stage += 1
    return finish(
        celery,
        f"Successfully hot-attached XML device to VM {domain}",
        current=current_stage,
        total=total_stages,
    )


def vm_worker_detach_device(zkhandler, celery, domain, xml_spec):
    current_stage = 0
    total_stages = 1

    start(
        celery,
        f"Hot-detaching XML device from VM {domain}",
        current=current_stage,
        total_stages=total_stages,
    )

    dom_uuid = getDomainUUID(zkhandler, domain)

    state = zkhandler.read(("domain.state", dom_uuid))
    if state not in ["start"]:
        fail(
            celery,
            f"VM {domain} not in start state; hot-detach unnecessary or impossible",
        )
        return

    dom = vm_worker_helper_getdom(dom_uuid)
    if dom is None:
        fail(
            celery,
            f"Failed to find Libvirt object for VM {domain}",
        )
        return

    try:
        dom.detachDevice(xml_spec)
    except Exception as e:
        fail(celery, e)
        return

    current_stage += 1
    return finish(
        celery,
        f"Successfully hot-detached XML device from VM {domain}",
        current=current_stage,
        total_stages=total_stages,
    )
