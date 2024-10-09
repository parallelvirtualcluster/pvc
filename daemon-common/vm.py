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
import rados
import requests

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from distutils.util import strtobool
from json import dump as jdump
from json import load as jload
from json import loads as jloads
from libvirt import open as lvopen
from os import scandir
from packaging.version import parse as parse_version
from rbd import Image as RBDImage
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
            (("domain.snapshots", dom_uuid), ""),
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
    if state not in ["stop", "disable", "mirror"]:
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

    # Edit the VM data
    zkhandler.write(
        [
            (("domain", dom_uuid), new_domain),
            (("domain.xml", dom_uuid), vm_config_new),
        ]
    )

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


def start_vm(zkhandler, domain, force=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    current_vm_state = zkhandler.read(("domain.state", dom_uuid))
    if current_vm_state in ["mirror"] and not force:
        return (
            False,
            'ERROR: VM "{}" is a snapshot mirror and start not forced!'.format(domain),
        )

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


def stop_vm(zkhandler, domain, force=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    current_vm_state = zkhandler.read(("domain.state", dom_uuid))
    if current_vm_state in ["mirror"] and not force:
        return False, 'ERROR: VM "{}" is a snapshot mirror and stop not forced!'.format(
            domain
        )

    # Set the VM to stop
    change_state(zkhandler, dom_uuid, "stop")

    return True, 'Forcibly stopping VM "{}".'.format(domain)


def disable_vm(zkhandler, domain, force=False):
    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        return False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain)

    # Get state and perform a shutdown/stop if VM is online
    current_vm_state = zkhandler.read(("domain.state", dom_uuid))
    if current_vm_state in ["mirror"] and not force:
        return (
            False,
            'ERROR: VM "{}" is a snapshot mirror and disable not forced!'.format(
                domain
            ),
        )
    elif current_vm_state in ["start"]:
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
            "mirror",
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


#
# VM Backup Tasks
#
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
    if not force_unlock and domain_state not in ["stop", "disable", "fail", "mirror"]:
        fail(
            celery,
            f"VM state {domain_state} not in [stop, disable, fail, mirror] and not forcing",
        )
        return False

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
            return False

        try:
            lock_list = jloads(lock_list_stdout)
        except Exception as e:
            fail(
                celery,
                f"Failed to parse JSON lock list for volume {rbd}: {e}",
            )
            return False

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
            return False

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
        return False

    dom = vm_worker_helper_getdom(dom_uuid)
    if dom is None:
        fail(
            celery,
            f"Failed to find Libvirt object for VM {domain}",
        )
        return False

    try:
        dom.attachDevice(xml_spec)
    except Exception as e:
        fail(celery, e)
        return False

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
        total=total_stages,
    )

    dom_uuid = getDomainUUID(zkhandler, domain)

    state = zkhandler.read(("domain.state", dom_uuid))
    if state not in ["start"]:
        fail(
            celery,
            f"VM {domain} not in start state; hot-detach unnecessary or impossible",
        )
        return False

    dom = vm_worker_helper_getdom(dom_uuid)
    if dom is None:
        fail(
            celery,
            f"Failed to find Libvirt object for VM {domain}",
        )
        return False

    try:
        dom.detachDevice(xml_spec)
    except Exception as e:
        fail(celery, e)
        return False

    current_stage += 1
    return finish(
        celery,
        f"Successfully hot-detached XML device from VM {domain}",
        current=current_stage,
        total=total_stages,
    )


def vm_worker_create_snapshot(
    zkhandler,
    celery,
    domain,
    snapshot_name=None,
    zk_only=False,
):
    if snapshot_name is None:
        now = datetime.now()
        snapshot_name = now.strftime("%Y%m%d%H%M%S")

    current_stage = 0
    total_stages = 1
    start(
        celery,
        f"Creating snapshot '{snapshot_name}' of VM '{domain}'",
        current=current_stage,
        total=total_stages,
    )

    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        fail(
            celery,
            f"Could not find VM '{domain}' in the cluster",
        )
        return False

    reg = re.compile("^[a-z0-9.-_]+$")
    if not reg.match(snapshot_name):
        fail(
            celery,
            "Snapshot name '{snapshot_name}' contains invalid characters; only alphanumeric, '.', '-', and '_' characters are allowed",
        )
        return False

    current_snapshots = zkhandler.children(("domain.snapshots", dom_uuid))
    if current_snapshots and snapshot_name in current_snapshots:
        fail(
            celery,
            f"Snapshot name '{snapshot_name}' already exists for VM '{domain}'!",
        )
        return False

    # Get the list of all RBD volumes
    rbd_list = zkhandler.read(("domain.storage.volumes", dom_uuid)).split(",")

    total_stages += 1 + len(rbd_list)

    snap_list = list()

    # If a snapshot fails, clean up any snapshots that were successfuly created
    def cleanup_failure():
        for snapshot in snap_list:
            rbd, snapshot_name = snapshot.split("@")
            pool, volume = rbd.split("/")
            # We capture no output here, because if this fails too we're in a deep
            # error chain and will just ignore it
            ceph.remove_snapshot(zkhandler, pool, volume, snapshot_name)

    # Iterrate through and create a snapshot for each RBD volume
    for rbd in rbd_list:
        current_stage += 1
        update(
            celery,
            f"Creating RBD snapshot of {rbd}",
            current=current_stage,
            total=total_stages,
        )

        pool, volume = rbd.split("/")
        ret, msg = ceph.add_snapshot(
            zkhandler, pool, volume, snapshot_name, zk_only=zk_only
        )
        if not ret:
            cleanup_failure()
            fail(
                celery,
                msg.replace("ERROR: ", ""),
            )
            return False
        else:
            snap_list.append(f"{pool}/{volume}@{snapshot_name}")

    current_stage += 1
    update(
        celery,
        "Creating VM configuration snapshot",
        current=current_stage,
        total=total_stages,
    )

    # Get the current timestamp
    tstart = time.time()
    # Get the current domain XML
    vm_config = zkhandler.read(("domain.xml", dom_uuid))

    # Add the snapshot entry to Zookeeper
    zkhandler.write(
        [
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.name",
                    snapshot_name,
                ),
                snapshot_name,
            ),
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.timestamp",
                    snapshot_name,
                ),
                tstart,
            ),
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.xml",
                    snapshot_name,
                ),
                vm_config,
            ),
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.rbd_snapshots",
                    snapshot_name,
                ),
                ",".join(snap_list),
            ),
        ]
    )

    current_stage += 1
    return finish(
        celery,
        f"Successfully created snapshot '{snapshot_name}' of VM '{domain}'",
        current=current_stage,
        total=total_stages,
    )


def vm_worker_remove_snapshot(
    zkhandler,
    celery,
    domain,
    snapshot_name,
):
    current_stage = 0
    total_stages = 1
    start(
        celery,
        f"Removing snapshot '{snapshot_name}' of VM '{domain}'",
        current=current_stage,
        total=total_stages,
    )

    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        fail(
            celery,
            f"Could not find VM '{domain}' in the cluster",
        )
        return False

    if not zkhandler.exists(
        ("domain.snapshots", dom_uuid, "domain_snapshot.name", snapshot_name)
    ):
        fail(
            celery,
            f"Could not find snapshot '{snapshot_name}' of VM '{domain}'!",
        )
        return False

    _snapshots = zkhandler.read(
        ("domain.snapshots", dom_uuid, "domain_snapshot.rbd_snapshots", snapshot_name)
    )
    rbd_snapshots = _snapshots.split(",")

    total_stages += 1 + len(rbd_snapshots)

    for snap in rbd_snapshots:
        current_stage += 1
        update(
            celery,
            f"Removing RBD snapshot {snap}",
            current=current_stage,
            total=total_stages,
        )

        rbd, name = snap.split("@")
        pool, volume = rbd.split("/")
        ret, msg = ceph.remove_snapshot(zkhandler, pool, volume, name)
        if not ret:
            fail(
                celery,
                msg.replace("ERROR: ", ""),
            )
            return False

    current_stage += 1
    update(
        celery,
        "Removing VM configuration snapshot",
        current=current_stage,
        total=total_stages,
    )

    ret = zkhandler.delete(
        ("domain.snapshots", dom_uuid, "domain_snapshot.name", snapshot_name)
    )
    if not ret:
        fail(
            celery,
            f'Failed to remove snapshot "{snapshot_name}" of VM "{domain}" from Zookeeper',
        )
        return False

    current_stage += 1
    return finish(
        celery,
        f"Successfully removed snapshot '{snapshot_name}' of VM '{domain}'",
        current=current_stage,
        total=total_stages,
    )


def vm_worker_rollback_snapshot(zkhandler, celery, domain, snapshot_name):
    current_stage = 0
    total_stages = 1
    start(
        celery,
        f"Rolling back to snapshot '{snapshot_name}' of VM '{domain}'",
        current=current_stage,
        total=total_stages,
    )

    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        fail(
            celery,
            f"Could not find VM '{domain}' in the cluster",
        )
        return False

    # Verify that the VM is in a stopped state; renaming is not supported otherwise
    state = zkhandler.read(("domain.state", dom_uuid))
    if state not in ["stop", "disable", "mirror"]:
        fail(
            celery,
            f"VM '{domain}' is not stopped or disabled; VMs cannot be rolled back while running",
        )
        return False

    # Verify that the snapshot exists
    if not zkhandler.exists(
        ("domain.snapshots", dom_uuid, "domain_snapshot.name", snapshot_name)
    ):
        fail(
            celery,
            f"Could not find snapshot '{snapshot_name}' of VM '{domain}'",
        )

    _snapshots = zkhandler.read(
        ("domain.snapshots", dom_uuid, "domain_snapshot.rbd_snapshots", snapshot_name)
    )
    rbd_snapshots = _snapshots.split(",")

    total_stages += 1 + len(rbd_snapshots)

    for snap in rbd_snapshots:
        current_stage += 1
        update(
            celery,
            f"Rolling back RBD snapshot {snap}",
            current=current_stage,
            total=total_stages,
        )

        rbd, name = snap.split("@")
        pool, volume = rbd.split("/")
        ret, msg = ceph.rollback_snapshot(zkhandler, pool, volume, name)
        if not ret:
            fail(
                celery,
                msg.replace("ERROR: ", ""),
            )
            return False

    current_stage += 1
    update(
        celery,
        "Rolling back VM configuration snapshot",
        current=current_stage,
        total=total_stages,
    )

    # Get the snapshot domain XML
    vm_config = zkhandler.read(
        ("domain.snapshots", dom_uuid, "domain_snapshot.xml", snapshot_name)
    )

    # Write the restored config to the main XML config
    zkhandler.write(
        [
            (
                (
                    "domain.xml",
                    dom_uuid,
                ),
                vm_config,
            ),
        ]
    )

    current_stage += 1
    return finish(
        celery,
        f"Successfully rolled back to snapshot '{snapshot_name}' of VM '{domain}'",
        current=current_stage,
        total=total_stages,
    )


def vm_worker_export_snapshot(
    zkhandler,
    celery,
    domain,
    snapshot_name,
    export_path,
    incremental_parent=None,
):
    current_stage = 0
    total_stages = 1
    start(
        celery,
        f"Exporting snapshot '{snapshot_name}' of VM '{domain}' to '{export_path}'",
        current=current_stage,
        total=total_stages,
    )

    # Validate that the target path is valid
    if not re.match(r"^/", export_path):
        fail(
            celery,
            f"Target path '{export_path}' is not a valid absolute path",
        )
        return False

    # Ensure that backup_path (on this node) exists
    myhostname = gethostname().split(".")[0]
    if not os.path.isdir(export_path):
        fail(
            celery,
            f"Target path '{export_path}' does not exist on node '{myhostname}'",
        )
        return False

    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        fail(
            celery,
            f"Could not find VM '{domain}' in the cluster",
        )
        return False

    if not zkhandler.exists(
        ("domain.snapshots", dom_uuid, "domain_snapshot.name", snapshot_name)
    ):
        fail(
            celery,
            f"Could not find snapshot '{snapshot_name}' of VM '{domain}'",
        )
        return False

    if incremental_parent is not None and not zkhandler.exists(
        ("domain.snapshots", dom_uuid, "domain_snapshot.name", incremental_parent)
    ):
        fail(
            celery,
            f"Could not find snapshot '{snapshot_name}' of VM '{domain}'",
        )
        return False

    # Get details about VM snapshot
    _, snapshot_timestamp, snapshot_xml, snapshot_rbdsnaps = zkhandler.read_many(
        [
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.name",
                    snapshot_name,
                )
            ),
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.timestamp",
                    snapshot_name,
                )
            ),
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.xml",
                    snapshot_name,
                )
            ),
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.rbd_snapshots",
                    snapshot_name,
                )
            ),
        ]
    )
    snapshot_rbdsnaps = snapshot_rbdsnaps.split(",")

    total_stages += 1 + len(snapshot_rbdsnaps)

    # Create destination directory
    export_target_path = f"{export_path}/{domain}/{snapshot_name}/images"
    try:
        os.makedirs(export_target_path)
    except Exception as e:
        fail(
            celery,
            f"Failed to create target directory '{export_target_path}': {e}",
        )
        return False

    def export_cleanup():
        from shutil import rmtree

        rmtree(f"{export_path}/{domain}/{snapshot_name}")

    export_type = "incremental" if incremental_parent is not None else "full"

    # Get information about VM
    vm_detail = get_list(zkhandler, limit=dom_uuid, is_fuzzy=False)[1][0]
    if not isinstance(vm_detail, dict):
        fail(celery, f"VM listing returned invalid data: {vm_detail}")
        return False

    # Override the current XML with the snapshot XML; but all other metainfo is current
    vm_detail["xml"] = snapshot_xml

    # Get the list of volumes
    snapshot_volumes = list()
    for rbdsnap in snapshot_rbdsnaps:
        pool, _volume = rbdsnap.split("/")
        volume, name = _volume.split("@")
        ret, snapshots = ceph.get_list_snapshot(
            zkhandler, pool, volume, limit=name, is_fuzzy=False
        )
        if ret:
            snapshot_volumes += snapshots

    # Set the export filetype
    if incremental_parent is not None:
        export_fileext = "rbddiff"
    else:
        export_fileext = "rbdimg"

    # Dump snapshot to folder with `rbd export` (full) or `rbd export-diff` (incremental)
    export_files = list()
    for snapshot_volume in snapshot_volumes:
        pool = snapshot_volume["pool"]
        volume = snapshot_volume["volume"]
        snapshot_name = snapshot_volume["snapshot"]
        size = snapshot_volume["stats"]["size"]
        snap = f"{pool}/{volume}@{snapshot_name}"

        current_stage += 1
        update(
            celery,
            f"Exporting RBD snapshot {snap}",
            current=current_stage,
            total=total_stages,
        )

        if incremental_parent is not None:
            retcode, stdout, stderr = common.run_os_command(
                f"rbd export-diff --from-snap {incremental_parent} {pool}/{volume}@{snapshot_name} {export_target_path}/{pool}.{volume}.{export_fileext}"
            )
            if retcode:
                export_cleanup()
                fail(
                    celery, f"Failed to export snapshot for volume(s) '{pool}/{volume}'"
                )
                return False
            else:
                export_files.append((f"images/{pool}.{volume}.{export_fileext}", size))
        else:
            retcode, stdout, stderr = common.run_os_command(
                f"rbd export --export-format 2 {pool}/{volume}@{snapshot_name} {export_target_path}/{pool}.{volume}.{export_fileext}"
            )
            if retcode:
                export_cleanup()
                fail(
                    celery, f"Failed to export snapshot for volume(s) '{pool}/{volume}'"
                )
                return False
            else:
                export_files.append((f"images/{pool}.{volume}.{export_fileext}", size))

    current_stage += 1
    update(
        celery,
        "Writing snapshot details",
        current=current_stage,
        total=total_stages,
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

    export_files_size = get_dir_size(export_target_path)

    export_details = {
        "type": export_type,
        "snapshot_name": snapshot_name,
        "incremental_parent": incremental_parent,
        "vm_detail": vm_detail,
        "export_files": export_files,
        "export_size_bytes": export_files_size,
    }
    try:
        with open(f"{export_path}/{domain}/{snapshot_name}/snapshot.json", "w") as fh:
            jdump(export_details, fh)
    except Exception as e:
        export_cleanup()
        fail(celery, f"Failed to export configuration snapshot: {e}")
        return False

    current_stage += 1
    return finish(
        celery,
        f"Successfully exported snapshot '{snapshot_name}' of VM '{domain}' to '{export_path}'",
        current=current_stage,
        total=total_stages,
    )


def vm_worker_import_snapshot(
    zkhandler, celery, domain, snapshot_name, import_path, retain_snapshot=True
):
    myhostname = gethostname().split(".")[0]

    current_stage = 0
    total_stages = 1
    start(
        celery,
        f"Importing snapshot '{snapshot_name}' of VM '{domain}' from '{import_path}'",
        current=current_stage,
        total=total_stages,
    )

    # 0. Validations
    # Validate that VM does not exist in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if dom_uuid:
        fail(
            celery,
            f"VM '{domain}' (UUID '{dom_uuid}') already exists in the cluster; remove it before importing a snapshot",
        )
        return False

    # Validate that the source path is valid
    if not re.match(r"^/", import_path):
        fail(
            celery,
            f"Source path '{import_path}; is not a valid absolute path",
        )
        return False

    # Ensure that import_path (on this node) exists
    if not os.path.isdir(import_path):
        fail(
            celery,
            f"Source path '{import_path}' does not exist on node '{myhostname}'",
        )
        return False

    # Ensure that domain path (on this node) exists
    vm_import_path = f"{import_path}/{domain}"
    if not os.path.isdir(vm_import_path):
        fail(celery, f"Source VM path '{vm_import_path}' does not exist")
        return False

    # Ensure that the archives are present
    export_source_snapshot_file = f"{vm_import_path}/{snapshot_name}/snapshot.json"
    if not os.path.isfile(export_source_snapshot_file):
        fail(celery, f"The specified source export '{snapshot_name}' do not exist")
        return False

    # Read the export file and get VM details
    try:
        with open(export_source_snapshot_file) as fh:
            export_source_details = jload(fh)
    except Exception as e:
        fail(
            celery,
            f"Failed to read source export details: {e}",
        )
        return False

    # Check that another VM with the same UUID doesn't already exist (rename is not enough!)
    dom_name = getDomainName(zkhandler, export_source_details["vm_detail"]["uuid"])
    if dom_name:
        fail(
            celery,
            f"VM UUID '{export_source_details['vm_detail']['uuid']}' (Name '{dom_name}') already exists in the cluster; remove it before importing a snapshot",
        )
        return False

    # Handle incrementals
    incremental_parent = export_source_details.get("incremental_parent", None)
    if incremental_parent is not None:
        export_source_parent_snapshot_file = (
            f"{vm_import_path}/{incremental_parent}/snapshot.json"
        )
        if not os.path.isfile(export_source_parent_snapshot_file):
            fail(
                celery,
                f"Export is incremental but required incremental parent files do not exist at '{myhostname}:{vm_import_path}/{incremental_parent}'",
            )
            return False

        try:
            with open(export_source_parent_snapshot_file) as fh:
                export_source_parent_details = jload(fh)
        except Exception as e:
            fail(
                celery,
                f"Failed to read source incremental parent export details: {e}",
            )
            return False

    total_stages += 3 * len(export_source_details.get("export_files"))
    if incremental_parent is not None:
        total_stages += 3
        total_stages += len(export_source_parent_details.get("export_files"))

    # 4. Import volumes
    if incremental_parent is not None:
        for volume_file, volume_size in export_source_details.get("export_files"):
            volume_size = f"{volume_size}B"
            pool, volume, _ = volume_file.split("/")[-1].split(".")

            try:
                parent_volume_file = [
                    f[0]
                    for f in export_source_parent_details.get("export_files")
                    if f[0].split("/")[-1].replace(".rbdimg", "")
                    == volume_file.split("/")[-1].replace(".rbddiff", "")
                ][0]
            except Exception as e:
                fail(
                    celery,
                    f"Failed to find parent volume for volume {pool}/{volume}; export may be corrupt or invalid: {e}",
                )
                return False

            # First we create the expected volumes then clean them up
            #   This process is a bit of a hack because rbd import does not expect an existing volume,
            #   but we need the information in PVC.
            #   Thus create the RBD volume using ceph.add_volume based on the export size, and then
            #   manually remove the RBD volume (leaving the PVC metainfo)
            current_stage += 1
            update(
                celery,
                f"Preparing RBD volume {pool}/{volume}",
                current=current_stage,
                total=total_stages,
            )

            retcode, retmsg = ceph.add_volume(zkhandler, pool, volume, volume_size)
            if not retcode:
                fail(celery, f"Failed to create imported volume: {retmsg}")
                return False

            retcode, stdout, stderr = common.run_os_command(
                f"rbd remove {pool}/{volume}"
            )
            if retcode:
                fail(
                    celery,
                    f"Failed to remove temporary RBD volume '{pool}/{volume}': {stderr}",
                )
                return False

            current_stage += 1
            update(
                celery,
                f"Importing RBD snapshot {pool}/{volume}@{incremental_parent}",
                current=current_stage,
                total=total_stages,
            )

            # Next we import the parent image
            retcode, stdout, stderr = common.run_os_command(
                f"rbd import --export-format 2 --dest-pool {pool} {import_path}/{domain}/{incremental_parent}/{parent_volume_file} {volume}"
            )
            if retcode:
                fail(
                    celery,
                    f"Failed to import parent export image {parent_volume_file}: {stderr}",
                )
                return False

        # Import VM config and metadata in import state, from the *source* details
        current_stage += 1
        update(
            celery,
            f"Importing VM configuration snapshot {incremental_parent}",
            current=current_stage,
            total=total_stages,
        )

        try:
            retcode, retmsg = define_vm(
                zkhandler,
                export_source_parent_details["vm_detail"]["xml"],
                export_source_parent_details["vm_detail"]["node"],
                export_source_parent_details["vm_detail"]["node_limit"],
                export_source_parent_details["vm_detail"]["node_selector"],
                export_source_parent_details["vm_detail"]["node_autostart"],
                export_source_parent_details["vm_detail"]["migration_method"],
                export_source_parent_details["vm_detail"]["migration_max_downtime"],
                export_source_parent_details["vm_detail"]["profile"],
                export_source_parent_details["vm_detail"]["tags"],
                "import",
            )
            if not retcode:
                fail(
                    celery,
                    f"Failed to define imported VM: {retmsg}",
                )
                return False
        except Exception as e:
            fail(
                celery,
                f"Failed to parse VM export details: {e}",
            )
            return False

        # Handle the VM snapshots
        if retain_snapshot:
            current_stage += 1
            update(
                celery,
                "Recreating incremental parent snapshot",
                current=current_stage,
                total=total_stages,
            )

            # Create the parent snapshot
            retcode = vm_worker_create_snapshot(
                zkhandler, None, domain, snapshot_name=incremental_parent, zk_only=True
            )
            if retcode is False:
                fail(
                    celery,
                    f"Failed to create imported snapshot for {incremental_parent} (parent)",
                )
                return False

        for volume_file, volume_size in export_source_details.get("export_files"):
            current_stage += 1
            update(
                celery,
                f"Importing RBD snapshot {pool}/{volume}@{snapshot_name}",
                current=current_stage,
                total=total_stages,
            )

            volume_size = f"{volume_size}B"
            pool, volume, _ = volume_file.split("/")[-1].split(".")
            # Then we import the incremental diffs
            retcode, stdout, stderr = common.run_os_command(
                f"rbd import-diff {import_path}/{domain}/{snapshot_name}/{volume_file} {pool}/{volume}"
            )
            if retcode:
                fail(
                    celery,
                    f"Failed to import incremental export image {volume_file}: {stderr}",
                )
                return False

            if not retain_snapshot:
                retcode, stdout, stderr = common.run_os_command(
                    f"rbd snap rm {pool}/{volume}@{incremental_parent}"
                )
                if retcode:
                    fail(
                        celery,
                        f"Failed to remove imported image snapshot '{pool}/{volume}@{incremental_parent}': {stderr}",
                    )
                    return False

                retcode, stdout, stderr = common.run_os_command(
                    f"rbd snap rm {pool}/{volume}@{snapshot_name}"
                )
                if retcode:
                    fail(
                        celery,
                        f"Failed to remove imported image snapshot '{pool}/{volume}@{snapshot_name}': {stderr}",
                    )
                    return False

        # Now update VM config and metadata, from the *current* details
        current_stage += 1
        update(
            celery,
            f"Importing VM configuration snapshot {snapshot_name}",
            current=current_stage,
            total=total_stages,
        )

        try:
            retcode, retmsg = modify_vm(
                zkhandler,
                domain,
                False,
                export_source_details["vm_detail"]["xml"],
            )
            if not retcode:
                fail(
                    celery,
                    f"Failed to modify imported VM: {retmsg}",
                )
                return False

            retcode, retmsg = move_vm(
                zkhandler,
                domain,
                export_source_details["vm_detail"]["node"],
            )
            if not retcode:
                # We don't actually care if this fails, because it just means the vm was never moved
                pass

            retcode, retmsg = modify_vm_metadata(
                zkhandler,
                domain,
                export_source_details["vm_detail"]["node_limit"],
                export_source_details["vm_detail"]["node_selector"],
                export_source_details["vm_detail"]["node_autostart"],
                export_source_details["vm_detail"]["profile"],
                export_source_details["vm_detail"]["migration_method"],
                export_source_details["vm_detail"]["migration_max_downtime"],
            )
            if not retcode:
                fail(
                    celery,
                    f"Failed to modify imported VM: {retmsg}",
                )
                return False
        except Exception as e:
            fail(
                celery,
                f"Failed to parse VM export details: {e}",
            )
            return False

        if retain_snapshot:
            current_stage += 1
            update(
                celery,
                "Recreating imported snapshot",
                current=current_stage,
                total=total_stages,
            )

            # Create the child snapshot
            retcode = vm_worker_create_snapshot(
                zkhandler, None, domain, snapshot_name=snapshot_name, zk_only=True
            )
            if retcode is False:
                fail(
                    celery,
                    f"Failed to create imported snapshot for {snapshot_name}",
                )
                return False
    else:
        for volume_file, volume_size in export_source_details.get("export_files"):
            volume_size = f"{volume_size}B"
            pool, volume, _ = volume_file.split("/")[-1].split(".")

            # First we create the expected volumes then clean them up
            #   This process is a bit of a hack because rbd import does not expect an existing volume,
            #   but we need the information in PVC.
            #   Thus create the RBD volume using ceph.add_volume based on the export size, and then
            #   manually remove the RBD volume (leaving the PVC metainfo)
            current_stage += 1
            update(
                celery,
                f"Preparing RBD volume {pool}/{volume}",
                current=current_stage,
                total=total_stages,
            )

            retcode, retmsg = ceph.add_volume(zkhandler, pool, volume, volume_size)
            if not retcode:
                fail(
                    celery,
                    f"Failed to create imported volume: {retmsg}",
                )
                return False

            retcode, stdout, stderr = common.run_os_command(
                f"rbd remove {pool}/{volume}"
            )
            if retcode:
                fail(
                    celery,
                    f"Failed to remove temporary RBD volume '{pool}/{volume}': {stderr}",
                )
                return False

            # Then we perform the actual import
            current_stage += 1
            update(
                celery,
                f"Importing RBD snapshot {pool}/{volume}@{snapshot_name}",
                current=current_stage,
                total=total_stages,
            )

            retcode, stdout, stderr = common.run_os_command(
                f"rbd import --export-format 2 --dest-pool {pool} {import_path}/{domain}/{snapshot_name}/{volume_file} {volume}"
            )
            if retcode:
                fail(
                    celery,
                    f"Failed to import export image {volume_file}: {stderr}",
                )

            if not retain_snapshot:
                retcode, stdout, stderr = common.run_os_command(
                    f"rbd snap rm {pool}/{volume}@{snapshot_name}"
                )
                if retcode:
                    fail(
                        celery,
                        f"Failed to remove imported image snapshot '{pool}/{volume}@{snapshot_name}': {stderr}",
                    )
                    return False

        # Import VM config and metadata in provision state
        current_stage += 1
        update(
            celery,
            f"Importing VM configuration snapshot {snapshot_name}",
            current=current_stage,
            total=total_stages,
        )

        try:
            retcode, retmsg = define_vm(
                zkhandler,
                export_source_details["vm_detail"]["xml"],
                export_source_details["vm_detail"]["node"],
                export_source_details["vm_detail"]["node_limit"],
                export_source_details["vm_detail"]["node_selector"],
                export_source_details["vm_detail"]["node_autostart"],
                export_source_details["vm_detail"]["migration_method"],
                export_source_details["vm_detail"]["migration_max_downtime"],
                export_source_details["vm_detail"]["profile"],
                export_source_details["vm_detail"]["tags"],
                "import",
            )
            if not retcode:
                fail(
                    celery,
                    f"Failed to define imported VM: {retmsg}",
                )
                return False
        except Exception as e:
            fail(
                celery,
                f"Failed to parse VM export details: {e}",
            )
            return False

        # Finally we handle the VM snapshot
        if retain_snapshot:
            current_stage += 1
            update(
                celery,
                "Recreating imported snapshot",
                current=current_stage,
                total=total_stages,
            )

            retcode = vm_worker_create_snapshot(
                zkhandler, None, domain, snapshot_name=snapshot_name, zk_only=True
            )
            if retcode is False:
                fail(
                    celery,
                    f"Failed to create imported snapshot for {snapshot_name}",
                )
                return False

    # 5. Start VM
    retcode, retmsg = start_vm(zkhandler, domain)
    if not retcode:
        fail(
            celery,
            f"Failed to start imported VM {domain}: {retmsg}",
        )
        return False

    current_stage += 1
    return finish(
        celery,
        f"Successfully imported VM '{domain}' at snapshot '{snapshot_name}' from '{myhostname}:{import_path}'",
        current=current_stage,
        total=total_stages,
    )


def vm_worker_send_snapshot(
    zkhandler,
    celery,
    domain,
    snapshot_name,
    destination_api_uri,
    destination_api_key,
    destination_api_verify_ssl=True,
    incremental_parent=None,
    destination_storage_pool=None,
):

    current_stage = 0
    total_stages = 1
    start(
        celery,
        f"Sending snapshot '{snapshot_name}' of VM '{domain}' to remote cluster '{destination_api_uri}'",
        current=current_stage,
        total=total_stages,
    )

    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        fail(
            celery,
            f"Could not find VM '{domain}' in the cluster",
        )
        return False

    # Get our side's VM configuration details
    try:
        vm_detail = get_list(zkhandler, limit=dom_uuid, is_fuzzy=False)[1][0]
    except KeyError:
        vm_detail = None

    if not isinstance(vm_detail, dict):
        fail(
            celery,
            f"VM listing returned invalid data: {vm_detail}",
        )
        return False

    # Check if the snapshot exists
    if not zkhandler.exists(
        ("domain.snapshots", dom_uuid, "domain_snapshot.name", snapshot_name)
    ):
        fail(
            celery,
            f"Could not find snapshot '{snapshot_name}' of VM '{domain}'",
        )
        return False

    # Check if the incremental parent exists
    if incremental_parent is not None and not zkhandler.exists(
        ("domain.snapshots", dom_uuid, "domain_snapshot.name", incremental_parent)
    ):
        fail(
            celery,
            f"Could not find snapshot '{snapshot_name}' of VM '{domain}'",
        )
        return False

    vm_name = vm_detail["name"]

    # Validate that the destination cluster can be reached
    destination_api_timeout = (3.05, 172800)
    destination_api_headers = {
        "X-Api-Key": destination_api_key,
    }

    session = requests.Session()
    session.headers.update(destination_api_headers)
    session.verify = destination_api_verify_ssl
    session.timeout = destination_api_timeout

    try:
        # Hit the API root; this should return "PVC API version x"
        response = session.get(
            f"{destination_api_uri}/",
            timeout=destination_api_timeout,
            params=None,
            data=None,
        )
        if "PVC API" not in response.json().get("message"):
            raise ValueError("Remote API is not a PVC API or incorrect URI given")
    except requests.exceptions.ConnectionError as e:
        fail(
            celery,
            f"Connection to remote API timed out: {e}",
        )
        return False
    except ValueError as e:
        fail(
            celery,
            f"Connection to remote API is not valid: {e}",
        )
        return False
    except Exception as e:
        fail(
            celery,
            f"Connection to remote API failed: {e}",
        )
        return False

    # Hit the API "/status" endpoint to validate API key and cluster status
    response = session.get(
        f"{destination_api_uri}/status",
        params=None,
        data=None,
    )
    destination_cluster_status = response.json()
    current_destination_pvc_version = destination_cluster_status.get(
        "pvc_version", None
    )
    if current_destination_pvc_version is None:
        fail(
            celery,
            "Connection to remote API failed: no PVC version information returned",
        )
        return False

    expected_destination_pvc_version = "0.9.100"  # TODO: 0.9.101 when completed
    # Work around development versions
    current_destination_pvc_version = re.sub(
        r"~git-.*", "", current_destination_pvc_version
    )
    # Compare versions
    if parse_version(current_destination_pvc_version) < parse_version(
        expected_destination_pvc_version
    ):
        fail(
            celery,
            f"Remote PVC cluster is too old: requires version {expected_destination_pvc_version} or higher",
        )
        return False

    # Check if the VM already exists on the remote
    response = session.get(
        f"{destination_api_uri}/vm/{domain}",
        params=None,
        data=None,
    )
    destination_vm_detail = response.json()
    if type(destination_vm_detail) is list and len(destination_vm_detail) > 0:
        destination_vm_detail = destination_vm_detail[0]
    else:
        destination_vm_detail = {}

    current_destination_vm_state = destination_vm_detail.get("state", None)
    if (
        current_destination_vm_state is not None
        and current_destination_vm_state != "mirror"
    ):
        fail(
            celery,
            "Remote PVC VM exists and is not a mirror",
        )
        return False

    # Get details about VM snapshot
    _, snapshot_timestamp, snapshot_xml, snapshot_rbdsnaps = zkhandler.read_many(
        [
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.name",
                    snapshot_name,
                )
            ),
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.timestamp",
                    snapshot_name,
                )
            ),
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.xml",
                    snapshot_name,
                )
            ),
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.rbd_snapshots",
                    snapshot_name,
                )
            ),
        ]
    )
    snapshot_rbdsnaps = snapshot_rbdsnaps.split(",")

    # Get details about remote VM snapshots
    destination_vm_snapshots = destination_vm_detail.get("snapshots", [])

    # Check if this snapshot is in the remote list already
    if snapshot_name in [s["name"] for s in destination_vm_snapshots]:
        fail(
            celery,
            f"Snapshot {snapshot_name} already exists on the target",
        )
        return False

    # Check if this snapshot is older than the latest remote VM snapshot
    if (
        len(destination_vm_snapshots) > 0
        and snapshot_timestamp < destination_vm_snapshots[0]["timestamp"]
    ):
        fail(
            celery,
            f"Target has a newer snapshot ({destination_vm_snapshots[0]['name']}); cannot send old snapshot {snapshot_name}",
        )
        return False

    # Check that our incremental parent exists on the remote VM
    if incremental_parent is not None:
        if incremental_parent not in [s["name"] for s in destination_vm_snapshots]:
            fail(
                celery,
                f"Can not send incremental for a snapshot ({incremental_parent}) which does not exist on the target",
            )
            return False

    # Begin send, set stages
    total_stages += 1 + (3 * len(snapshot_rbdsnaps))

    current_stage += 1
    update(
        celery,
        f"Sending VM configuration for {vm_name}@{snapshot_name}",
        current=current_stage,
        total=total_stages,
    )

    send_params = {
        "snapshot": snapshot_name,
        "source_snapshot": incremental_parent,
    }
    try:
        response = session.post(
            f"{destination_api_uri}/vm/{vm_name}/snapshot/receive/config",
            headers={"Content-Type": "application/json"},
            params=send_params,
            json=vm_detail,
        )
        response.raise_for_status()
    except Exception as e:
        fail(
            celery,
            f"Failed to send config: {e}",
        )
        return False

    # Create the block devices on the remote side if this is a new VM send
    block_t_start = time.time()
    block_total_mb = 0

    for rbd_detail in [r for r in vm_detail["disks"] if r["type"] == "rbd"]:
        rbd_name = rbd_detail["name"]
        pool, volume = rbd_name.split("/")

        current_stage += 1
        update(
            celery,
            f"Preparing remote volume for {rbd_name}@{snapshot_name}",
            current=current_stage,
            total=total_stages,
        )

        # Get the storage volume details
        retcode, retdata = ceph.get_list_volume(zkhandler, pool, volume, is_fuzzy=False)
        if not retcode or len(retdata) != 1:
            if len(retdata) < 1:
                error_message = f"No detail returned for volume {rbd_name}"
            elif len(retdata) > 1:
                error_message = f"Multiple details returned for volume {rbd_name}"
            else:
                error_message = f"Error getting details for volume {rbd_name}"
            fail(
                celery,
                error_message,
            )
            return False

        try:
            local_volume_size = ceph.format_bytes_fromhuman(retdata[0]["stats"]["size"])
        except Exception as e:
            error_message = f"Failed to get volume size for {rbd_name}: {e}"

        if destination_storage_pool is not None:
            pool = destination_storage_pool

        current_stage += 1
        update(
            celery,
            f"Checking remote volume {rbd_name} for compliance",
            current=current_stage,
            total=total_stages,
        )

        # Check if the volume exists on the target
        response = session.get(
            f"{destination_api_uri}/storage/ceph/volume/{pool}/{volume}",
            params=None,
            data=None,
        )
        if response.status_code != 404 and current_destination_vm_state is None:
            fail(
                celery,
                f"Remote storage pool {pool} already contains volume {volume}",
            )
            return False

        if current_destination_vm_state is not None:
            try:
                remote_volume_size = ceph.format_bytes_fromhuman(
                    response.json()[0]["stats"]["size"]
                )
            except Exception as e:
                error_message = f"Failed to get volume size for remote {rbd_name}: {e}"
                fail(celery, error_message)
                return False

            if local_volume_size != remote_volume_size:
                response = session.put(
                    f"{destination_api_uri}/storage/ceph/volume/{pool}/{volume}",
                    params={"new_size": local_volume_size, "force": True},
                )
                if response.status_code != 200:
                    fail(
                        celery,
                        "Failed to resize remote volume to match local volume",
                    )
                    return False

        # Send the volume to the remote
        cluster = rados.Rados(conffile="/etc/ceph/ceph.conf")
        cluster.connect()
        ioctx = cluster.open_ioctx(pool)
        image = RBDImage(ioctx, name=volume, snapshot=snapshot_name, read_only=True)
        size = image.size()
        chunk_size_mb = 1024

        if incremental_parent is not None:
            # Diff between incremental_parent and snapshot
            celery_message = (
                f"Sending diff of {rbd_name}@{incremental_parent} → {snapshot_name}"
            )
        else:
            # Full image transfer
            celery_message = f"Sending full image of {rbd_name}@{snapshot_name}"

        current_stage += 1
        update(
            celery,
            celery_message,
            current=current_stage,
            total=total_stages,
        )

        if incremental_parent is not None:
            # Createa single session to reuse connections
            send_params = {
                "pool": pool,
                "volume": volume,
                "snapshot": snapshot_name,
                "source_snapshot": incremental_parent,
            }

            session.params.update(send_params)

            # Send 32 objects (128MB) at once
            send_max_objects = 32
            batch_size_mb = 4 * send_max_objects
            batch_size = batch_size_mb * 1024 * 1024

            total_chunks = 0

            def diff_cb_count(offset, length, exists):
                nonlocal total_chunks
                if exists:
                    total_chunks += 1

            current_chunk = 0
            buffer = list()
            buffer_size = 0
            last_chunk_time = time.time()

            def send_batch_multipart(buffer):
                nonlocal last_chunk_time
                files = {}
                for i in range(len(buffer)):
                    files[f"object_{i}"] = (
                        f"object_{i}",
                        buffer[i],
                        "application/octet-stream",
                    )
                try:
                    response = session.put(
                        f"{destination_api_uri}/vm/{vm_name}/snapshot/receive/block",
                        files=files,
                        stream=True,
                    )
                    response.raise_for_status()
                except Exception as e:
                    fail(
                        celery,
                        f"Failed to send diff batch ({e}): {response.json()['message']}",
                    )
                    return False

                current_chunk_time = time.time()
                chunk_time = current_chunk_time - last_chunk_time
                last_chunk_time = current_chunk_time
                chunk_speed = round(batch_size_mb / chunk_time, 1)
                update(
                    celery,
                    celery_message + f" ({chunk_speed} MB/s)",
                    current=current_stage,
                    total=total_stages,
                )

            def add_block_to_multipart(buffer, offset, length, data):
                part_data = (
                    offset.to_bytes(8, "big") + length.to_bytes(8, "big") + data
                )  # Add header and data
                buffer.append(part_data)

            def diff_cb_send(offset, length, exists):
                nonlocal current_chunk, buffer, buffer_size
                if exists:
                    # Read the data for the current block
                    data = image.read(offset, length)
                    # Add the block to the multipart buffer
                    add_block_to_multipart(buffer, offset, length, data)
                    current_chunk += 1
                    buffer_size += len(data)
                    if buffer_size >= batch_size:
                        send_batch_multipart(buffer)
                        buffer.clear()  # Clear the buffer after sending
                        buffer_size = 0  # Reset buffer size

            try:
                image.set_snap(snapshot_name)
                image.diff_iterate(
                    0, size, incremental_parent, diff_cb_count, whole_object=True
                )
                block_total_mb += total_chunks * 4
                image.diff_iterate(
                    0, size, incremental_parent, diff_cb_send, whole_object=True
                )

                if buffer:
                    send_batch_multipart(buffer)
                    buffer.clear()  # Clear the buffer after sending
                    buffer_size = 0  # Reset buffer size
            except Exception:
                fail(
                    celery,
                    f"Failed to send snapshot: {response.json()['message']}",
                )
                return False
            finally:
                image.close()
                ioctx.close()
                cluster.shutdown()
        else:

            def full_chunker():
                nonlocal block_total_mb
                chunk_size = 1024 * 1024 * chunk_size_mb
                current_chunk = 0
                last_chunk_time = time.time()
                while current_chunk < size:
                    chunk = image.read(current_chunk, chunk_size)
                    yield chunk
                    current_chunk += chunk_size
                    block_total_mb += len(chunk) / 1024 / 1024
                    current_chunk_time = time.time()
                    chunk_time = current_chunk_time - last_chunk_time
                    last_chunk_time = current_chunk_time
                    chunk_speed = round(chunk_size_mb / chunk_time, 1)
                    update(
                        celery,
                        celery_message + f" ({chunk_speed} MB/s)",
                        current=current_stage,
                        total=total_stages,
                    )

            send_params = {
                "pool": pool,
                "volume": volume,
                "snapshot": snapshot_name,
                "size": size,
                "source_snapshot": incremental_parent,
            }

            try:
                response = session.post(
                    f"{destination_api_uri}/vm/{vm_name}/snapshot/receive/block",
                    headers={"Content-Type": "application/octet-stream"},
                    params=send_params,
                    data=full_chunker(),
                )
                response.raise_for_status()
            except Exception:
                fail(
                    celery,
                    f"Failed to send snapshot: {response.json()['message']}",
                )
                return False
            finally:
                image.close()
                ioctx.close()
                cluster.shutdown()

        send_params = {
            "pool": pool,
            "volume": volume,
            "snapshot": snapshot_name,
        }
        try:
            response = session.patch(
                f"{destination_api_uri}/vm/{vm_name}/snapshot/receive/block",
                params=send_params,
            )
            response.raise_for_status()
        except Exception:
            fail(
                celery,
                f"Failed to send snapshot: {response.json()['message']}",
            )
            return False
        finally:
            image.close()
            ioctx.close()
            cluster.shutdown()

    block_t_end = time.time()
    block_mbps = round(block_total_mb / (block_t_end - block_t_start), 1)

    current_stage += 1
    return finish(
        celery,
        f"Successfully sent snapshot '{snapshot_name}' of VM '{domain}' to remote cluster '{destination_api_uri}' (average {block_mbps} MB/s)",
        current=current_stage,
        total=total_stages,
    )


def vm_worker_create_mirror(
    zkhandler,
    celery,
    domain,
    destination_api_uri,
    destination_api_key,
    destination_api_verify_ssl,
    destination_storage_pool,
):
    now = datetime.now()
    datestring = now.strftime("%Y%m%d%H%M%S")
    snapshot_name = f"mr{datestring}"

    current_stage = 0
    total_stages = 1
    start(
        celery,
        f"Creating mirror of VM '{domain}' to cluster '{destination_api_uri}'",
        current=current_stage,
        total=total_stages,
    )

    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        fail(
            celery,
            f"Could not find VM '{domain}' in the cluster",
        )
        return False

    current_snapshots = zkhandler.children(("domain.snapshots", dom_uuid))
    if current_snapshots and snapshot_name in current_snapshots:
        # This should never actually happen since snapshots with mirror are dated, but worth
        # checking just in case someone tries to be sneaky
        fail(
            celery,
            f"Snapshot name '{snapshot_name}' already exists for VM '{domain}'!",
        )
        return False

    # Get our side's VM configuration details
    try:
        vm_detail = get_list(zkhandler, limit=dom_uuid, is_fuzzy=False)[1][0]
    except KeyError:
        vm_detail = None

    if not isinstance(vm_detail, dict):
        fail(
            celery,
            f"VM listing returned invalid data: {vm_detail}",
        )
        return False

    vm_name = vm_detail["name"]

    # Validate that the destination cluster can be reached
    destination_api_timeout = (3.05, 172800)
    destination_api_headers = {
        "X-Api-Key": destination_api_key,
    }

    session = requests.Session()
    session.headers.update(destination_api_headers)
    session.verify = destination_api_verify_ssl
    session.timeout = destination_api_timeout

    try:
        # Hit the API root; this should return "PVC API version x"
        response = session.get(
            f"{destination_api_uri}/",
            timeout=destination_api_timeout,
            params=None,
            data=None,
        )
        if "PVC API" not in response.json().get("message"):
            raise ValueError("Remote API is not a PVC API or incorrect URI given")
    except requests.exceptions.ConnectionError as e:
        fail(
            celery,
            f"Connection to remote API timed out: {e}",
        )
        return False
    except ValueError as e:
        fail(
            celery,
            f"Connection to remote API is not valid: {e}",
        )
        return False
    except Exception as e:
        fail(
            celery,
            f"Connection to remote API failed: {e}",
        )
        return False

    # Hit the API "/status" endpoint to validate API key and cluster status
    response = session.get(
        f"{destination_api_uri}/status",
        params=None,
        data=None,
    )
    destination_cluster_status = response.json()
    current_destination_pvc_version = destination_cluster_status.get(
        "pvc_version", None
    )
    if current_destination_pvc_version is None:
        fail(
            celery,
            "Connection to remote API failed: no PVC version information returned",
        )
        return False

    expected_destination_pvc_version = "0.9.100"  # TODO: 0.9.101 when completed
    # Work around development versions
    current_destination_pvc_version = re.sub(
        r"~git-.*", "", current_destination_pvc_version
    )
    # Compare versions
    if parse_version(current_destination_pvc_version) < parse_version(
        expected_destination_pvc_version
    ):
        fail(
            celery,
            f"Remote PVC cluster is too old: requires version {expected_destination_pvc_version} or higher",
        )
        return False

    # Check if the VM already exists on the remote
    response = session.get(
        f"{destination_api_uri}/vm/{domain}",
        params=None,
        data=None,
    )
    destination_vm_detail = response.json()
    if type(destination_vm_detail) is list and len(destination_vm_detail) > 0:
        destination_vm_detail = destination_vm_detail[0]
    else:
        destination_vm_detail = {}

    current_destination_vm_state = destination_vm_detail.get("state", None)
    if (
        current_destination_vm_state is not None
        and current_destination_vm_state != "mirror"
    ):
        fail(
            celery,
            "Remote PVC VM exists and is not a mirror",
        )
        return False

    # Get the list of all RBD volumes
    rbd_list = zkhandler.read(("domain.storage.volumes", dom_uuid)).split(",")

    # Snapshot creation stages
    total_stages += 1 + len(rbd_list)
    # Snapshot sending stages
    total_stages += 1 + (3 * len(rbd_list))

    #
    # 1. Create snapshot
    #

    snap_list = list()

    # If a snapshot fails, clean up any snapshots that were successfuly created
    def cleanup_failure():
        for snapshot in snap_list:
            rbd, snapshot_name = snapshot.split("@")
            pool, volume = rbd.split("/")
            # We capture no output here, because if this fails too we're in a deep
            # error chain and will just ignore it
            ceph.remove_snapshot(zkhandler, pool, volume, snapshot_name)

    # Iterrate through and create a snapshot for each RBD volume
    for rbd in rbd_list:
        current_stage += 1
        update(
            celery,
            f"Creating RBD snapshot of {rbd}",
            current=current_stage,
            total=total_stages,
        )

        pool, volume = rbd.split("/")
        ret, msg = ceph.add_snapshot(
            zkhandler, pool, volume, snapshot_name, zk_only=False
        )
        if not ret:
            cleanup_failure()
            fail(
                celery,
                msg.replace("ERROR: ", ""),
            )
            return False
        else:
            snap_list.append(f"{pool}/{volume}@{snapshot_name}")

    current_stage += 1
    update(
        celery,
        "Creating VM configuration snapshot",
        current=current_stage,
        total=total_stages,
    )

    # Get the current timestamp
    tstart = time.time()
    # Get the current domain XML
    vm_config = zkhandler.read(("domain.xml", dom_uuid))

    # Add the snapshot entry to Zookeeper
    zkhandler.write(
        [
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.name",
                    snapshot_name,
                ),
                snapshot_name,
            ),
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.timestamp",
                    snapshot_name,
                ),
                tstart,
            ),
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.xml",
                    snapshot_name,
                ),
                vm_config,
            ),
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.rbd_snapshots",
                    snapshot_name,
                ),
                ",".join(snap_list),
            ),
        ]
    )

    #
    # 2. Send snapshot to remote
    #

    # Re-get our side's VM configuration details (since we now have the snapshot)
    vm_detail = get_list(zkhandler, limit=dom_uuid, is_fuzzy=False)[1][0]

    # Determine if there's a valid shared snapshot to send an incremental diff from
    if destination_vm_detail:
        local_snapshots = {s["name"] for s in vm_detail["snapshots"]}
        remote_snapshots = {s["name"] for s in destination_vm_detail["snapshots"]}
        incremental_parent = next(
            (s for s in local_snapshots if s in remote_snapshots), None
        )
    else:
        incremental_parent = None

    current_stage += 1
    update(
        celery,
        f"Sending VM configuration for {vm_name}@{snapshot_name}",
        current=current_stage,
        total=total_stages,
    )

    send_params = {
        "snapshot": snapshot_name,
        "source_snapshot": incremental_parent,
    }
    try:
        response = session.post(
            f"{destination_api_uri}/vm/{vm_name}/snapshot/receive/config",
            headers={"Content-Type": "application/json"},
            params=send_params,
            json=vm_detail,
        )
        response.raise_for_status()
    except Exception as e:
        fail(
            celery,
            f"Failed to send config: {e}",
        )
        return False

    # Create the block devices on the remote side if this is a new VM send
    block_t_start = time.time()
    block_total_mb = 0

    for rbd_detail in [r for r in vm_detail["disks"] if r["type"] == "rbd"]:
        rbd_name = rbd_detail["name"]
        pool, volume = rbd_name.split("/")

        current_stage += 1
        update(
            celery,
            f"Preparing remote volume for {rbd_name}@{snapshot_name}",
            current=current_stage,
            total=total_stages,
        )

        # Get the storage volume details
        retcode, retdata = ceph.get_list_volume(zkhandler, pool, volume, is_fuzzy=False)
        if not retcode or len(retdata) != 1:
            if len(retdata) < 1:
                error_message = f"No detail returned for volume {rbd_name}"
            elif len(retdata) > 1:
                error_message = f"Multiple details returned for volume {rbd_name}"
            else:
                error_message = f"Error getting details for volume {rbd_name}"
            fail(
                celery,
                error_message,
            )
            return False

        try:
            local_volume_size = ceph.format_bytes_fromhuman(retdata[0]["stats"]["size"])
        except Exception as e:
            error_message = f"Failed to get volume size for {rbd_name}: {e}"

        if destination_storage_pool is not None:
            pool = destination_storage_pool

        current_stage += 1
        update(
            celery,
            f"Checking remote volume {rbd_name} for compliance",
            current=current_stage,
            total=total_stages,
        )

        # Check if the volume exists on the target
        response = session.get(
            f"{destination_api_uri}/storage/ceph/volume/{pool}/{volume}",
            params=None,
            data=None,
        )
        if response.status_code != 404 and current_destination_vm_state is None:
            fail(
                celery,
                f"Remote storage pool {pool} already contains volume {volume}",
            )
            return False

        if current_destination_vm_state is not None:
            try:
                remote_volume_size = ceph.format_bytes_fromhuman(
                    response.json()[0]["stats"]["size"]
                )
            except Exception as e:
                error_message = f"Failed to get volume size for remote {rbd_name}: {e}"
                fail(celery, error_message)
                return False

            if local_volume_size != remote_volume_size:
                response = session.put(
                    f"{destination_api_uri}/storage/ceph/volume/{pool}/{volume}",
                    params={"new_size": local_volume_size, "force": True},
                )
                if response.status_code != 200:
                    fail(
                        celery,
                        "Failed to resize remote volume to match local volume",
                    )
                    return False

        # Send the volume to the remote
        cluster = rados.Rados(conffile="/etc/ceph/ceph.conf")
        cluster.connect()
        ioctx = cluster.open_ioctx(pool)
        image = RBDImage(ioctx, name=volume, snapshot=snapshot_name, read_only=True)
        size = image.size()
        chunk_size_mb = 1024

        if incremental_parent is not None:
            # Diff between incremental_parent and snapshot
            celery_message = (
                f"Sending diff of {rbd_name}@{incremental_parent} → {snapshot_name}"
            )
        else:
            # Full image transfer
            celery_message = f"Sending full image of {rbd_name}@{snapshot_name}"

        current_stage += 1
        update(
            celery,
            celery_message,
            current=current_stage,
            total=total_stages,
        )

        if incremental_parent is not None:
            # Createa single session to reuse connections
            send_params = {
                "pool": pool,
                "volume": volume,
                "snapshot": snapshot_name,
                "source_snapshot": incremental_parent,
            }

            session.params.update(send_params)

            # Send 32 objects (128MB) at once
            send_max_objects = 32
            batch_size_mb = 4 * send_max_objects
            batch_size = batch_size_mb * 1024 * 1024

            total_chunks = 0

            def diff_cb_count(offset, length, exists):
                nonlocal total_chunks
                if exists:
                    total_chunks += 1

            current_chunk = 0
            buffer = list()
            buffer_size = 0
            last_chunk_time = time.time()

            def send_batch_multipart(buffer):
                nonlocal last_chunk_time
                files = {}
                for i in range(len(buffer)):
                    files[f"object_{i}"] = (
                        f"object_{i}",
                        buffer[i],
                        "application/octet-stream",
                    )
                try:
                    response = session.put(
                        f"{destination_api_uri}/vm/{vm_name}/snapshot/receive/block",
                        files=files,
                        stream=True,
                    )
                    response.raise_for_status()
                except Exception as e:
                    fail(
                        celery,
                        f"Failed to send diff batch ({e}): {response.json()['message']}",
                    )
                    return False

                current_chunk_time = time.time()
                chunk_time = current_chunk_time - last_chunk_time
                last_chunk_time = current_chunk_time
                chunk_speed = round(batch_size_mb / chunk_time, 1)
                update(
                    celery,
                    celery_message + f" ({chunk_speed} MB/s)",
                    current=current_stage,
                    total=total_stages,
                )

            def add_block_to_multipart(buffer, offset, length, data):
                part_data = (
                    offset.to_bytes(8, "big") + length.to_bytes(8, "big") + data
                )  # Add header and data
                buffer.append(part_data)

            def diff_cb_send(offset, length, exists):
                nonlocal current_chunk, buffer, buffer_size
                if exists:
                    # Read the data for the current block
                    data = image.read(offset, length)
                    # Add the block to the multipart buffer
                    add_block_to_multipart(buffer, offset, length, data)
                    current_chunk += 1
                    buffer_size += len(data)
                    if buffer_size >= batch_size:
                        send_batch_multipart(buffer)
                        buffer.clear()  # Clear the buffer after sending
                        buffer_size = 0  # Reset buffer size

            try:
                image.set_snap(snapshot_name)
                image.diff_iterate(
                    0, size, incremental_parent, diff_cb_count, whole_object=True
                )
                block_total_mb += total_chunks * 4
                image.diff_iterate(
                    0, size, incremental_parent, diff_cb_send, whole_object=True
                )

                if buffer:
                    send_batch_multipart(buffer)
                    buffer.clear()  # Clear the buffer after sending
                    buffer_size = 0  # Reset buffer size
            except Exception:
                fail(
                    celery,
                    f"Failed to create mirror: {response.json()['message']}",
                )
                return False
            finally:
                image.close()
                ioctx.close()
                cluster.shutdown()
        else:

            def full_chunker():
                nonlocal block_total_mb
                chunk_size = 1024 * 1024 * chunk_size_mb
                current_chunk = 0
                last_chunk_time = time.time()
                while current_chunk < size:
                    chunk = image.read(current_chunk, chunk_size)
                    yield chunk
                    current_chunk += chunk_size
                    block_total_mb += len(chunk) / 1024 / 1024
                    current_chunk_time = time.time()
                    chunk_time = current_chunk_time - last_chunk_time
                    last_chunk_time = current_chunk_time
                    chunk_speed = round(chunk_size_mb / chunk_time, 1)
                    update(
                        celery,
                        celery_message + f" ({chunk_speed} MB/s)",
                        current=current_stage,
                        total=total_stages,
                    )

            send_params = {
                "pool": pool,
                "volume": volume,
                "snapshot": snapshot_name,
                "size": size,
                "source_snapshot": incremental_parent,
            }

            try:
                response = session.post(
                    f"{destination_api_uri}/vm/{vm_name}/snapshot/receive/block",
                    headers={"Content-Type": "application/octet-stream"},
                    params=send_params,
                    data=full_chunker(),
                )
                response.raise_for_status()
            except Exception:
                fail(
                    celery,
                    f"Failed to create mirror: {response.json()['message']}",
                )
                return False
            finally:
                image.close()
                ioctx.close()
                cluster.shutdown()

        send_params = {
            "pool": pool,
            "volume": volume,
            "snapshot": snapshot_name,
        }
        try:
            response = session.patch(
                f"{destination_api_uri}/vm/{vm_name}/snapshot/receive/block",
                params=send_params,
            )
            response.raise_for_status()
        except Exception:
            fail(
                celery,
                f"Failed to create mirror: {response.json()['message']}",
            )
            return False
        finally:
            image.close()
            ioctx.close()
            cluster.shutdown()

    block_t_end = time.time()
    block_mbps = round(block_total_mb / (block_t_end - block_t_start), 1)

    if incremental_parent is not None:
        verb = "updated"
    else:
        verb = "created"

    current_stage += 1
    return finish(
        celery,
        f"Successfully {verb} mirror of VM '{domain}' (snapshot '{snapshot_name}') on remote cluster '{destination_api_uri}' (average {block_mbps} MB/s)",
        current=current_stage,
        total=total_stages,
    )


def vm_worker_promote_mirror(
    zkhandler,
    celery,
    domain,
    destination_api_uri,
    destination_api_key,
    destination_api_verify_ssl,
    destination_storage_pool,
    remove_on_source=False,
):
    now = datetime.now()
    datestring = now.strftime("%Y%m%d%H%M%S")
    snapshot_name = f"mr{datestring}"

    current_stage = 0
    total_stages = 1
    start(
        celery,
        f"Creating mirror of VM '{domain}' to cluster '{destination_api_uri}'",
        current=current_stage,
        total=total_stages,
    )

    # Validate that VM exists in cluster
    dom_uuid = getDomainUUID(zkhandler, domain)
    if not dom_uuid:
        fail(
            celery,
            f"Could not find VM '{domain}' in the cluster",
        )
        return False

    current_snapshots = zkhandler.children(("domain.snapshots", dom_uuid))
    if current_snapshots and snapshot_name in current_snapshots:
        # This should never actually happen since snapshots with mirror are dated, but worth
        # checking just in case someone tries to be sneaky
        fail(
            celery,
            f"Snapshot name '{snapshot_name}' already exists for VM '{domain}'!",
        )
        return False

    # Get our side's VM configuration details
    try:
        vm_detail = get_list(zkhandler, limit=dom_uuid, is_fuzzy=False)[1][0]
    except KeyError:
        vm_detail = None

    if not isinstance(vm_detail, dict):
        fail(
            celery,
            f"VM listing returned invalid data: {vm_detail}",
        )
        return False

    vm_name = vm_detail["name"]

    # Validate that the destination cluster can be reached
    destination_api_timeout = (3.05, 172800)
    destination_api_headers = {
        "X-Api-Key": destination_api_key,
    }

    session = requests.Session()
    session.headers.update(destination_api_headers)
    session.verify = destination_api_verify_ssl
    session.timeout = destination_api_timeout

    try:
        # Hit the API root; this should return "PVC API version x"
        response = session.get(
            f"{destination_api_uri}/",
            timeout=destination_api_timeout,
            params=None,
            data=None,
        )
        if "PVC API" not in response.json().get("message"):
            raise ValueError("Remote API is not a PVC API or incorrect URI given")
    except requests.exceptions.ConnectionError as e:
        fail(
            celery,
            f"Connection to remote API timed out: {e}",
        )
        return False
    except ValueError as e:
        fail(
            celery,
            f"Connection to remote API is not valid: {e}",
        )
        return False
    except Exception as e:
        fail(
            celery,
            f"Connection to remote API failed: {e}",
        )
        return False

    # Hit the API "/status" endpoint to validate API key and cluster status
    response = session.get(
        f"{destination_api_uri}/status",
        params=None,
        data=None,
    )
    destination_cluster_status = response.json()
    current_destination_pvc_version = destination_cluster_status.get(
        "pvc_version", None
    )
    if current_destination_pvc_version is None:
        fail(
            celery,
            "Connection to remote API failed: no PVC version information returned",
        )
        return False

    expected_destination_pvc_version = "0.9.100"  # TODO: 0.9.101 when completed
    # Work around development versions
    current_destination_pvc_version = re.sub(
        r"~git-.*", "", current_destination_pvc_version
    )
    # Compare versions
    if parse_version(current_destination_pvc_version) < parse_version(
        expected_destination_pvc_version
    ):
        fail(
            celery,
            f"Remote PVC cluster is too old: requires version {expected_destination_pvc_version} or higher",
        )
        return False

    # Check if the VM already exists on the remote
    response = session.get(
        f"{destination_api_uri}/vm/{domain}",
        params=None,
        data=None,
    )
    destination_vm_detail = response.json()
    if type(destination_vm_detail) is list and len(destination_vm_detail) > 0:
        destination_vm_detail = destination_vm_detail[0]
    else:
        destination_vm_detail = {}

    current_destination_vm_state = destination_vm_detail.get("state", None)
    if (
        current_destination_vm_state is not None
        and current_destination_vm_state != "mirror"
    ):
        fail(
            celery,
            "Remote PVC VM exists and is not a mirror",
        )
        return False

    # Get the list of all RBD volumes
    rbd_list = zkhandler.read(("domain.storage.volumes", dom_uuid)).split(",")

    # VM shutdown stages
    total_stages += 1
    # Snapshot creation stages
    total_stages += 1 + len(rbd_list)
    # Snapshot sending stages
    total_stages += 1 + (3 * len(rbd_list))
    # Cleanup stages
    total_stages += 2

    #
    # 1. Shut down VM
    #

    current_stage += 1
    update(
        celery,
        f"Shutting down VM '{vm_name}'",
        current=current_stage,
        total=total_stages,
    )

    retcode, retmsg = shutdown_vm(zkhandler, domain, wait=True)
    if not retcode:
        fail(
            celery,
            "Failed to shut down VM",
        )
        return False

    #
    # 2. Create snapshot
    #

    snap_list = list()

    # If a snapshot fails, clean up any snapshots that were successfuly created
    def cleanup_failure():
        for snapshot in snap_list:
            rbd, snapshot_name = snapshot.split("@")
            pool, volume = rbd.split("/")
            # We capture no output here, because if this fails too we're in a deep
            # error chain and will just ignore it
            ceph.remove_snapshot(zkhandler, pool, volume, snapshot_name)

    # Iterrate through and create a snapshot for each RBD volume
    for rbd in rbd_list:
        current_stage += 1
        update(
            celery,
            f"Creating RBD snapshot of {rbd}",
            current=current_stage,
            total=total_stages,
        )

        pool, volume = rbd.split("/")
        ret, msg = ceph.add_snapshot(
            zkhandler, pool, volume, snapshot_name, zk_only=False
        )
        if not ret:
            cleanup_failure()
            fail(
                celery,
                msg.replace("ERROR: ", ""),
            )
            return False
        else:
            snap_list.append(f"{pool}/{volume}@{snapshot_name}")

    current_stage += 1
    update(
        celery,
        "Creating VM configuration snapshot",
        current=current_stage,
        total=total_stages,
    )

    # Get the current timestamp
    tstart = time.time()
    # Get the current domain XML
    vm_config = zkhandler.read(("domain.xml", dom_uuid))

    # Add the snapshot entry to Zookeeper
    zkhandler.write(
        [
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.name",
                    snapshot_name,
                ),
                snapshot_name,
            ),
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.timestamp",
                    snapshot_name,
                ),
                tstart,
            ),
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.xml",
                    snapshot_name,
                ),
                vm_config,
            ),
            (
                (
                    "domain.snapshots",
                    dom_uuid,
                    "domain_snapshot.rbd_snapshots",
                    snapshot_name,
                ),
                ",".join(snap_list),
            ),
        ]
    )

    #
    # 3. Send snapshot to remote
    #

    # Re-get our side's VM configuration details (since we now have the snapshot)
    vm_detail = get_list(zkhandler, limit=dom_uuid, is_fuzzy=False)[1][0]

    # Determine if there's a valid shared snapshot to send an incremental diff from
    local_snapshots = {s["name"] for s in vm_detail["snapshots"]}
    remote_snapshots = {s["name"] for s in destination_vm_detail["snapshots"]}
    incremental_parent = next(
        (s for s in local_snapshots if s in remote_snapshots), None
    )

    current_stage += 1
    update(
        celery,
        f"Sending VM configuration for {vm_name}@{snapshot_name}",
        current=current_stage,
        total=total_stages,
    )

    send_params = {
        "snapshot": snapshot_name,
        "source_snapshot": incremental_parent,
    }
    try:
        response = session.post(
            f"{destination_api_uri}/vm/{vm_name}/snapshot/receive/config",
            headers={"Content-Type": "application/json"},
            params=send_params,
            json=vm_detail,
        )
        response.raise_for_status()
    except Exception as e:
        fail(
            celery,
            f"Failed to send config: {e}",
        )
        return False

    # Create the block devices on the remote side if this is a new VM send
    block_t_start = time.time()
    block_total_mb = 0

    for rbd_detail in [r for r in vm_detail["disks"] if r["type"] == "rbd"]:
        rbd_name = rbd_detail["name"]
        pool, volume = rbd_name.split("/")

        current_stage += 1
        update(
            celery,
            f"Preparing remote volume for {rbd_name}@{snapshot_name}",
            current=current_stage,
            total=total_stages,
        )

        # Get the storage volume details
        retcode, retdata = ceph.get_list_volume(zkhandler, pool, volume, is_fuzzy=False)
        if not retcode or len(retdata) != 1:
            if len(retdata) < 1:
                error_message = f"No detail returned for volume {rbd_name}"
            elif len(retdata) > 1:
                error_message = f"Multiple details returned for volume {rbd_name}"
            else:
                error_message = f"Error getting details for volume {rbd_name}"
            fail(
                celery,
                error_message,
            )
            return False

        try:
            local_volume_size = ceph.format_bytes_fromhuman(retdata[0]["stats"]["size"])
        except Exception as e:
            error_message = f"Failed to get volume size for {rbd_name}: {e}"

        if destination_storage_pool is not None:
            pool = destination_storage_pool

        current_stage += 1
        update(
            celery,
            f"Checking remote volume {rbd_name} for compliance",
            current=current_stage,
            total=total_stages,
        )

        # Check if the volume exists on the target
        response = session.get(
            f"{destination_api_uri}/storage/ceph/volume/{pool}/{volume}",
            params=None,
            data=None,
        )
        if response.status_code != 404 and current_destination_vm_state is None:
            fail(
                celery,
                f"Remote storage pool {pool} already contains volume {volume}",
            )
            return False

        if current_destination_vm_state is not None:
            try:
                remote_volume_size = ceph.format_bytes_fromhuman(
                    response.json()[0]["stats"]["size"]
                )
            except Exception as e:
                error_message = f"Failed to get volume size for remote {rbd_name}: {e}"
                fail(celery, error_message)
                return False

            if local_volume_size != remote_volume_size:
                response = session.put(
                    f"{destination_api_uri}/storage/ceph/volume/{pool}/{volume}",
                    params={"new_size": local_volume_size, "force": True},
                )
                if response.status_code != 200:
                    fail(
                        celery,
                        "Failed to resize remote volume to match local volume",
                    )
                    return False

        # Send the volume to the remote
        cluster = rados.Rados(conffile="/etc/ceph/ceph.conf")
        cluster.connect()
        ioctx = cluster.open_ioctx(pool)
        image = RBDImage(ioctx, name=volume, snapshot=snapshot_name, read_only=True)
        size = image.size()
        chunk_size_mb = 1024

        if incremental_parent is not None:
            # Diff between incremental_parent and snapshot
            celery_message = (
                f"Sending diff of {rbd_name}@{incremental_parent} → {snapshot_name}"
            )
        else:
            # Full image transfer
            celery_message = f"Sending full image of {rbd_name}@{snapshot_name}"

        current_stage += 1
        update(
            celery,
            celery_message,
            current=current_stage,
            total=total_stages,
        )

        if incremental_parent is not None:
            # Createa single session to reuse connections
            send_params = {
                "pool": pool,
                "volume": volume,
                "snapshot": snapshot_name,
                "source_snapshot": incremental_parent,
            }

            session.params.update(send_params)

            # Send 32 objects (128MB) at once
            send_max_objects = 32
            batch_size_mb = 4 * send_max_objects
            batch_size = batch_size_mb * 1024 * 1024

            total_chunks = 0

            def diff_cb_count(offset, length, exists):
                nonlocal total_chunks
                if exists:
                    total_chunks += 1

            current_chunk = 0
            buffer = list()
            buffer_size = 0
            last_chunk_time = time.time()

            def send_batch_multipart(buffer):
                nonlocal last_chunk_time
                files = {}
                for i in range(len(buffer)):
                    files[f"object_{i}"] = (
                        f"object_{i}",
                        buffer[i],
                        "application/octet-stream",
                    )
                try:
                    response = session.put(
                        f"{destination_api_uri}/vm/{vm_name}/snapshot/receive/block",
                        files=files,
                        stream=True,
                    )
                    response.raise_for_status()
                except Exception as e:
                    fail(
                        celery,
                        f"Failed to send diff batch ({e}): {response.json()['message']}",
                    )
                    return False

                current_chunk_time = time.time()
                chunk_time = current_chunk_time - last_chunk_time
                last_chunk_time = current_chunk_time
                chunk_speed = round(batch_size_mb / chunk_time, 1)
                update(
                    celery,
                    celery_message + f" ({chunk_speed} MB/s)",
                    current=current_stage,
                    total=total_stages,
                )

            def add_block_to_multipart(buffer, offset, length, data):
                part_data = (
                    offset.to_bytes(8, "big") + length.to_bytes(8, "big") + data
                )  # Add header and data
                buffer.append(part_data)

            def diff_cb_send(offset, length, exists):
                nonlocal current_chunk, buffer, buffer_size
                if exists:
                    # Read the data for the current block
                    data = image.read(offset, length)
                    # Add the block to the multipart buffer
                    add_block_to_multipart(buffer, offset, length, data)
                    current_chunk += 1
                    buffer_size += len(data)
                    if buffer_size >= batch_size:
                        send_batch_multipart(buffer)
                        buffer.clear()  # Clear the buffer after sending
                        buffer_size = 0  # Reset buffer size

            try:
                image.set_snap(snapshot_name)
                image.diff_iterate(
                    0, size, incremental_parent, diff_cb_count, whole_object=True
                )
                block_total_mb += total_chunks * 4
                image.diff_iterate(
                    0, size, incremental_parent, diff_cb_send, whole_object=True
                )

                if buffer:
                    send_batch_multipart(buffer)
                    buffer.clear()  # Clear the buffer after sending
                    buffer_size = 0  # Reset buffer size
            except Exception:
                fail(
                    celery,
                    f"Failed to promote mirror: {response.json()['message']}",
                )
                return False
            finally:
                image.close()
                ioctx.close()
                cluster.shutdown()
        else:

            def full_chunker():
                nonlocal block_total_mb
                chunk_size = 1024 * 1024 * chunk_size_mb
                current_chunk = 0
                last_chunk_time = time.time()
                while current_chunk < size:
                    chunk = image.read(current_chunk, chunk_size)
                    yield chunk
                    current_chunk += chunk_size
                    block_total_mb += len(chunk) / 1024 / 1024
                    current_chunk_time = time.time()
                    chunk_time = current_chunk_time - last_chunk_time
                    last_chunk_time = current_chunk_time
                    chunk_speed = round(chunk_size_mb / chunk_time, 1)
                    update(
                        celery,
                        celery_message + f" ({chunk_speed} MB/s)",
                        current=current_stage,
                        total=total_stages,
                    )

            send_params = {
                "pool": pool,
                "volume": volume,
                "snapshot": snapshot_name,
                "size": size,
                "source_snapshot": incremental_parent,
            }

            try:
                response = session.post(
                    f"{destination_api_uri}/vm/{vm_name}/snapshot/receive/block",
                    headers={"Content-Type": "application/octet-stream"},
                    params=send_params,
                    data=full_chunker(),
                )
                response.raise_for_status()
            except Exception:
                fail(
                    celery,
                    f"Failed to promote mirror: {response.json()['message']}",
                )
                return False
            finally:
                image.close()
                ioctx.close()
                cluster.shutdown()

        send_params = {
            "pool": pool,
            "volume": volume,
            "snapshot": snapshot_name,
        }
        try:
            response = session.patch(
                f"{destination_api_uri}/vm/{vm_name}/snapshot/receive/block",
                params=send_params,
            )
            response.raise_for_status()
        except Exception:
            fail(
                celery,
                f"Failed to promote mirror: {response.json()['message']}",
            )
            return False
        finally:
            image.close()
            ioctx.close()
            cluster.shutdown()

    block_t_end = time.time()
    block_mbps = round(block_total_mb / (block_t_end - block_t_start), 1)

    #
    # 4. Start VM on remote
    #

    current_stage += 1
    update(
        celery,
        f"Starting VM '{vm_name}' on remote cluster",
        current=current_stage,
        total=total_stages,
    )

    try:
        response = session.post(
            f"{destination_api_uri}/vm/{vm_name}/state",
            headers={"Content-Type": "application/octet-stream"},
            params={"state": "start", "wait": True, "force": True},
        )
        response.raise_for_status()
    except Exception:
        fail(
            celery,
            f"Failed to promote mirror: {response.json()['message']}",
        )
        return False

    #
    # 5. Set mirror state OR remove VM
    #

    if remove_on_source:
        current_stage += 1
        update(
            celery,
            f"Removing VM '{vm_name}' from local cluster",
            current=current_stage,
            total=total_stages,
        )

        retcode, retmsg = remove_vm(zkhandler, domain)
    else:
        current_stage += 1
        update(
            celery,
            f"Setting VM '{vm_name}' state to mirror on local cluster",
            current=current_stage,
            total=total_stages,
        )

        change_state(zkhandler, dom_uuid, "mirror")

    current_stage += 1
    return finish(
        celery,
        f"Successfully promoted VM '{domain}' (snapshot '{snapshot_name}') on remote cluster '{destination_api_uri}' (average {block_mbps} MB/s)",
        current=current_stage,
        total=total_stages,
    )
