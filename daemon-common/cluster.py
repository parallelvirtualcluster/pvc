#!/usr/bin/env python3

# cluster.py - PVC client function library, cluster management
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2022 Joshua M. Boniface <joshua@boniface.me>
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

from json import loads

import daemon_lib.common as common
import daemon_lib.vm as pvc_vm
import daemon_lib.node as pvc_node
import daemon_lib.network as pvc_network
import daemon_lib.ceph as pvc_ceph


def set_maintenance(zkhandler, maint_state):
    current_maint_state = zkhandler.read("base.config.maintenance")
    if maint_state == current_maint_state:
        if maint_state == "true":
            return True, "Cluster is already in maintenance mode"
        else:
            return True, "Cluster is already in normal mode"

    if maint_state == "true":
        zkhandler.write([("base.config.maintenance", "true")])
        return True, "Successfully set cluster in maintenance mode"
    else:
        zkhandler.write([("base.config.maintenance", "false")])
        return True, "Successfully set cluster in normal mode"


def getClusterHealth(zkhandler, node_list, vm_list, ceph_osd_list):
    health_delta_map = {
        "node_stopped": 50,
        "node_flushed": 10,
        "vm_stopped": 10,
        "osd_out": 50,
        "osd_down": 10,
        "memory_overprovisioned": 50,
        "ceph_err": 50,
        "ceph_warn": 10,
    }

    # Generate total cluster health numbers
    cluster_health = 100
    messages = list()

    for index, node in enumerate(node_list):
        # Apply node health values to total health number
        cluster_health -= 100 - node["health"]
        for entry in node["health_details"]:
            if entry["health_delta"] > 0:
                messages.append(
                    f"{node['name']}: plugin {entry['plugin_name']}: {entry['message']}"
                )

        # Handle unhealthy node states
        if node["daemon_state"] not in ["run"]:
            cluster_health -= health_delta_map["node_stopped"]
            messages.append(
                f"cluster: {node['name']} in {node['daemon_state']} daemon state"
            )
        elif node["domain_state"] not in ["ready"]:
            cluster_health -= health_delta_map["node_flushed"]
            messages.append(
                f"cluster: {node['name']} in {node['domain_state']} domain state"
            )

    for index, vm in enumerate(vm_list):
        # Handle unhealthy VM states
        if vm["state"] not in ["start", "disable", "migrate", "unmigrate", "provision"]:
            cluster_health -= health_delta_map["vm_stopped"]
            messages.append(f"cluster: {vm['name']} in {vm['state']} state")

    for index, ceph_osd in enumerate(ceph_osd_list):
        in_texts = {1: "in", 0: "out"}
        up_texts = {1: "up", 0: "down"}

        # Handle unhealthy OSD states
        if in_texts[ceph_osd["stats"]["in"]] not in ["in"]:
            cluster_health -= health_delta_map["osd_out"]
            messages.append(
                f"cluster: OSD {ceph_osd['id']} in {in_texts[ceph_osd['stats']['in']]} state"
            )
        elif up_texts[ceph_osd["stats"]["up"]] not in ["up"]:
            cluster_health -= health_delta_map["osd_down"]
            messages.append(
                f"cluster: OSD {ceph_osd['id']} in {up_texts[ceph_osd['stats']['up']]} state"
            )

    # Check for (n-1) overprovisioning
    #   Assume X nodes. If the total VM memory allocation (counting only running VMss) is greater than
    #   the total memory of the (n-1) smallest nodes, trigger this warning.
    n_minus_1_total = 0
    alloc_total = 0
    node_largest_index = None
    node_largest_count = 0
    for index, node in enumerate(node_list):
        node_mem_total = node["memory"]["total"]
        node_mem_alloc = node["memory"]["allocated"]
        alloc_total += node_mem_alloc
        # Determine if this node is the largest seen so far
        if node_mem_total > node_largest_count:
            node_largest_index = index
            node_largest_count = node_mem_total
    n_minus_1_node_list = list()
    for index, node in enumerate(node_list):
        if index == node_largest_index:
            continue
        n_minus_1_node_list.append(node)
    for index, node in enumerate(n_minus_1_node_list):
        n_minus_1_total += node["memory"]["total"]
    if alloc_total > n_minus_1_total:
        cluster_health -= health_delta_map["memory_overprovisioned"]
        messages.append(
            f"cluster: Total VM memory is overprovisioned ({alloc_total} > {n_minus_1_total} n-1)"
        )

    # Check Ceph cluster health
    ceph_health = loads(zkhandler.read("base.storage.health"))
    ceph_health_status = ceph_health["status"]
    ceph_health_entries = ceph_health["checks"].keys()

    if ceph_health_status == "HEALTH_ERR":
        cluster_health -= health_delta_map["ceph_err"]
        messages.append(
            f"cluster: Ceph cluster in ERROR state: {', '.join(ceph_health_entries)}"
        )
    elif ceph_health_status == "HEALTH_WARN":
        cluster_health -= health_delta_map["ceph_warn"]
        messages.append(
            f"cluster: Ceph cluster in WARNING state: {', '.join(ceph_health_entries)}"
        )

    return cluster_health, messages


def getClusterInformation(zkhandler):
    # Get cluster maintenance state
    maintenance_state = zkhandler.read("base.config.maintenance")

    # Get node information object list
    retcode, node_list = pvc_node.get_list(zkhandler, None)

    # Get vm information object list
    retcode, vm_list = pvc_vm.get_list(zkhandler, None, None, None, None)

    # Get network information object list
    retcode, network_list = pvc_network.get_list(zkhandler, None, None)

    # Get storage information object list
    retcode, ceph_osd_list = pvc_ceph.get_list_osd(zkhandler, None)
    retcode, ceph_pool_list = pvc_ceph.get_list_pool(zkhandler, None)
    retcode, ceph_volume_list = pvc_ceph.get_list_volume(zkhandler, None, None)
    retcode, ceph_snapshot_list = pvc_ceph.get_list_snapshot(
        zkhandler, None, None, None
    )

    # Determine, for each subsection, the total count
    node_count = len(node_list)
    vm_count = len(vm_list)
    network_count = len(network_list)
    ceph_osd_count = len(ceph_osd_list)
    ceph_pool_count = len(ceph_pool_list)
    ceph_volume_count = len(ceph_volume_list)
    ceph_snapshot_count = len(ceph_snapshot_list)

    # State lists
    node_state_combinations = [
        "run,ready",
        "run,flush",
        "run,flushed",
        "run,unflush",
        "init,ready",
        "init,flush",
        "init,flushed",
        "init,unflush",
        "stop,ready",
        "stop,flush",
        "stop,flushed",
        "stop,unflush",
        "dead,ready",
        "dead,flush",
        "dead,flushed",
        "dead,unflush",
    ]
    vm_state_combinations = [
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
    ceph_osd_state_combinations = [
        "up,in",
        "up,out",
        "down,in",
        "down,out",
    ]

    # Format the Node states
    formatted_node_states = {"total": node_count}
    for state in node_state_combinations:
        state_count = 0
        for node in node_list:
            node_state = f"{node['daemon_state']},{node['domain_state']}"
            if node_state == state:
                state_count += 1
        if state_count > 0:
            formatted_node_states[state] = state_count

    # Format the VM states
    formatted_vm_states = {"total": vm_count}
    for state in vm_state_combinations:
        state_count = 0
        for vm in vm_list:
            if vm["state"] == state:
                state_count += 1
        if state_count > 0:
            formatted_vm_states[state] = state_count

    # Format the OSD states
    up_texts = {1: "up", 0: "down"}
    in_texts = {1: "in", 0: "out"}
    formatted_osd_states = {"total": ceph_osd_count}
    for state in ceph_osd_state_combinations:
        state_count = 0
        for ceph_osd in ceph_osd_list:
            ceph_osd_state = f"{up_texts[ceph_osd['stats']['up']]},{in_texts[ceph_osd['stats']['in']]}"
            if ceph_osd_state == state:
                state_count += 1
        if state_count > 0:
            formatted_osd_states[state] = state_count

    # Get cluster health data
    cluster_health, cluster_health_messages = getClusterHealth(
        zkhandler, node_list, vm_list, ceph_osd_list
    )

    # Format the status data
    cluster_information = {
        "health": cluster_health,
        "health_messages": cluster_health_messages,
        "maintenance": maintenance_state,
        "primary_node": common.getPrimaryNode(zkhandler),
        "upstream_ip": zkhandler.read("base.config.upstream_ip"),
        "nodes": formatted_node_states,
        "vms": formatted_vm_states,
        "networks": network_count,
        "osds": formatted_osd_states,
        "pools": ceph_pool_count,
        "volumes": ceph_volume_count,
        "snapshots": ceph_snapshot_count,
    }

    return cluster_information


def get_info(zkhandler):
    # This is a thin wrapper function for naming purposes
    cluster_information = getClusterInformation(zkhandler)
    if cluster_information:
        return True, cluster_information
    else:
        return False, "ERROR: Failed to obtain cluster information!"


def cluster_initialize(zkhandler, overwrite=False):
    # Abort if we've initialized the cluster before
    if zkhandler.exists("base.config.primary_node") and not overwrite:
        return False, "ERROR: Cluster contains data and overwrite not set."

    if overwrite:
        # Delete the existing keys
        for key in zkhandler.schema.keys("base"):
            if key == "root":
                # Don't delete the root key
                continue

            status = zkhandler.delete("base.{}".format(key), recursive=True)
            if not status:
                return (
                    False,
                    "ERROR: Failed to delete data in cluster; running nodes perhaps?",
                )

    # Create the root keys
    zkhandler.schema.apply(zkhandler)

    return True, "Successfully initialized cluster"


def cluster_backup(zkhandler):
    # Dictionary of values to come
    cluster_data = dict()

    def get_data(path):
        data = zkhandler.read(path)
        children = zkhandler.children(path)

        cluster_data[path] = data

        if children:
            if path == "/":
                child_prefix = "/"
            else:
                child_prefix = path + "/"

            for child in children:
                if child_prefix + child == "/zookeeper":
                    # We must skip the built-in /zookeeper tree
                    continue
                if child_prefix + child == "/patroni":
                    # We must skip the /patroni tree
                    continue

                get_data(child_prefix + child)

    try:
        get_data("/")
    except Exception as e:
        return False, "ERROR: Failed to obtain backup: {}".format(e)

    return True, cluster_data


def cluster_restore(zkhandler, cluster_data):
    # Build a key+value list
    kv = []
    schema_version = None
    for key in cluster_data:
        if key == zkhandler.schema.path("base.schema.version"):
            schema_version = cluster_data[key]
        data = cluster_data[key]
        kv.append((key, data))

    if int(schema_version) != int(zkhandler.schema.version):
        return (
            False,
            "ERROR: Schema version of backup ({}) does not match cluster schema version ({}).".format(
                schema_version, zkhandler.schema.version
            ),
        )

    # Close the Zookeeper connection
    result = zkhandler.write(kv)

    if result:
        return True, "Restore completed successfully."
    else:
        return False, "Restore failed."
