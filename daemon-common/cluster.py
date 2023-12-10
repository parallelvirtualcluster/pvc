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
import daemon_lib.faults as faults
import daemon_lib.node as pvc_node


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


def getClusterHealthFromFaults(zkhandler, faults_list):
    unacknowledged_faults = [fault for fault in faults_list if fault["status"] != "ack"]

    # Generate total cluster health numbers
    cluster_health_value = 100
    cluster_health_messages = list()

    for fault in sorted(
        unacknowledged_faults,
        key=lambda x: (x["health_delta"], x["last_reported"]),
        reverse=True,
    ):
        cluster_health_value -= fault["health_delta"]
        message = {
            "id": fault["id"],
            "health_delta": fault["health_delta"],
            "text": fault["message"],
        }
        cluster_health_messages.append(message)

    if cluster_health_value < 0:
        cluster_health_value = 0

    cluster_health = {
        "health": cluster_health_value,
        "messages": cluster_health_messages,
    }

    return cluster_health


def getClusterHealth(zkhandler, node_list, vm_list, ceph_osd_list):
    health_delta_map = {
        "node_stopped": 50,
        "node_flushed": 10,
        "vm_stopped": 10,
        "osd_out": 50,
        "osd_down": 10,
        "osd_full": 50,
        "osd_nearfull": 10,
        "memory_overprovisioned": 50,
        "ceph_err": 50,
        "ceph_warn": 10,
    }

    # Generate total cluster health numbers
    cluster_health_value = 100
    cluster_health_messages = list()

    for index, node in enumerate(node_list):
        # Apply node health values to total health number
        try:
            node_health_int = int(node["health"])
        except Exception:
            node_health_int = 100
        cluster_health_value -= 100 - node_health_int

        for entry in node["health_details"]:
            if entry["health_delta"] > 0:
                cluster_health_messages.append(
                    f"{node['name']}: plugin '{entry['name']}': {entry['message']}"
                )

        # Handle unhealthy node states
        if node["daemon_state"] not in ["run"]:
            cluster_health_value -= health_delta_map["node_stopped"]
            cluster_health_messages.append(
                f"cluster: Node {node['name']} in {node['daemon_state'].upper()} daemon state"
            )
        elif node["domain_state"] not in ["ready"]:
            cluster_health_value -= health_delta_map["node_flushed"]
            cluster_health_messages.append(
                f"cluster: Node {node['name']} in {node['domain_state'].upper()} domain state"
            )

    for index, vm in enumerate(vm_list):
        # Handle unhealthy VM states
        if vm["state"] in ["stop", "fail"]:
            cluster_health_value -= health_delta_map["vm_stopped"]
            cluster_health_messages.append(
                f"cluster: VM {vm['name']} in {vm['state'].upper()} state"
            )

    for index, ceph_osd in enumerate(ceph_osd_list):
        in_texts = {1: "in", 0: "out"}
        up_texts = {1: "up", 0: "down"}

        # Handle unhealthy OSD states
        if in_texts[ceph_osd["stats"]["in"]] not in ["in"]:
            cluster_health_value -= health_delta_map["osd_out"]
            cluster_health_messages.append(
                f"cluster: Ceph OSD {ceph_osd['id']} in {in_texts[ceph_osd['stats']['in']].upper()} state"
            )
        elif up_texts[ceph_osd["stats"]["up"]] not in ["up"]:
            cluster_health_value -= health_delta_map["osd_down"]
            cluster_health_messages.append(
                f"cluster: Ceph OSD {ceph_osd['id']} in {up_texts[ceph_osd['stats']['up']].upper()} state"
            )

        # Handle full or nearfull OSDs (>85%)
        if ceph_osd["stats"]["utilization"] >= 90:
            cluster_health_value -= health_delta_map["osd_full"]
            cluster_health_messages.append(
                f"cluster: Ceph OSD {ceph_osd['id']} is FULL ({ceph_osd['stats']['utilization']:.1f}% > 90%)"
            )
        elif ceph_osd["stats"]["utilization"] >= 85:
            cluster_health_value -= health_delta_map["osd_nearfull"]
            cluster_health_messages.append(
                f"cluster: Ceph OSD {ceph_osd['id']} is NEARFULL ({ceph_osd['stats']['utilization']:.1f}% > 85%)"
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
        cluster_health_value -= health_delta_map["memory_overprovisioned"]
        cluster_health_messages.append(
            f"cluster: Total memory is OVERPROVISIONED ({alloc_total} > {n_minus_1_total} @ N-1)"
        )

    # Check Ceph cluster health
    ceph_health = loads(zkhandler.read("base.storage.health"))
    ceph_health_status = ceph_health["status"]
    ceph_health_entries = ceph_health["checks"].keys()

    ceph_health_status_map = {
        "HEALTH_ERR": "ERROR",
        "HEALTH_WARN": "WARNING",
    }
    for entry in ceph_health_entries:
        cluster_health_messages.append(
            f"cluster: Ceph {ceph_health_status_map[ceph_health['checks'][entry]['severity']]} {entry}: {ceph_health['checks'][entry]['summary']['message']}"
        )

    if ceph_health_status == "HEALTH_ERR":
        cluster_health_value -= health_delta_map["ceph_err"]
    elif ceph_health_status == "HEALTH_WARN":
        cluster_health_value -= health_delta_map["ceph_warn"]

    if cluster_health_value < 0:
        cluster_health_value = 0

    cluster_health = {
        "health": cluster_health_value,
        "messages": cluster_health_messages,
    }

    return cluster_health


def getNodeHealth(zkhandler, node_list):
    # Get the health state of all nodes
    node_health_reads = list()
    for node in node_list:
        node_health_reads += [
            ("node.monitoring.health", node),
            ("node.monitoring.plugins", node),
        ]
    all_node_health_details = zkhandler.read_many(node_health_reads)
    # Parse out the Node health details
    node_health = dict()
    for nidx, node in enumerate(node_list):
        # Split the large list of return values by the IDX of this node
        # Each node result is 2 fields long
        pos_start = nidx * 2
        pos_end = nidx * 2 + 2
        node_health_value, node_health_plugins = tuple(
            all_node_health_details[pos_start:pos_end]
        )
        node_health_details = pvc_node.getNodeHealthDetails(
            zkhandler, node, node_health_plugins.split()
        )

        node_health_messages = list()
        for entry in node_health_details:
            if entry["health_delta"] > 0:
                node_health_messages.append(f"'{entry['name']}': {entry['message']}")

        node_health_entry = {
            "health": node_health_value,
            "messages": node_health_messages,
        }
        node_health[node] = node_health_entry

    return node_health


def getClusterInformation(zkhandler):
    # Get cluster maintenance state
    maintenance_state = zkhandler.read("base.config.maintenance")

    # Get primary node
    maintenance_state, primary_node = zkhandler.read_many(
        [
            ("base.config.maintenance"),
            ("base.config.primary_node"),
        ]
    )

    # Get PVC version of primary node
    pvc_version = zkhandler.read(("node.data.pvc_version", primary_node))

    # Get the list of Nodes
    node_list = zkhandler.children("base.node")
    node_count = len(node_list)
    # Get the daemon and domain states of all Nodes
    node_state_reads = list()
    for node in node_list:
        node_state_reads += [
            ("node.state.daemon", node),
            ("node.state.domain", node),
        ]
    all_node_states = zkhandler.read_many(node_state_reads)
    # Parse out the Node states
    node_data = list()
    formatted_node_states = {"total": node_count}
    for nidx, node in enumerate(node_list):
        # Split the large list of return values by the IDX of this node
        # Each node result is 2 fields long
        pos_start = nidx * 2
        pos_end = nidx * 2 + 2
        node_daemon_state, node_domain_state = tuple(all_node_states[pos_start:pos_end])
        node_data.append(
            {
                "name": node,
                "daemon_state": node_daemon_state,
                "domain_state": node_domain_state,
            }
        )
        node_state = f"{node_daemon_state},{node_domain_state}"
        # Add to the count for this node's state
        if node_state in common.node_state_combinations:
            if formatted_node_states.get(node_state) is not None:
                formatted_node_states[node_state] += 1
            else:
                formatted_node_states[node_state] = 1

    # Get the list of VMs
    vm_list = zkhandler.children("base.domain")
    vm_count = len(vm_list)
    # Get the states of all VMs
    vm_state_reads = list()
    for vm in vm_list:
        vm_state_reads += [
            ("domain", vm),
            ("domain.state", vm),
        ]
    all_vm_states = zkhandler.read_many(vm_state_reads)
    # Parse out the VM states
    vm_data = list()
    formatted_vm_states = {"total": vm_count}
    for vidx, vm in enumerate(vm_list):
        # Split the large list of return values by the IDX of this VM
        # Each VM result is 2 field long
        pos_start = nidx * 2
        pos_end = nidx * 2 + 2
        vm_name, vm_state = tuple(all_vm_states[pos_start:pos_end])
        vm_data.append(
            {
                "uuid": vm,
                "name": vm_name,
                "state": vm_state,
            }
        )
        # Add to the count for this VM's state
        if vm_state in common.vm_state_combinations:
            if formatted_vm_states.get(vm_state) is not None:
                formatted_vm_states[vm_state] += 1
            else:
                formatted_vm_states[vm_state] = 1

    # Get the list of Ceph OSDs
    ceph_osd_list = zkhandler.children("base.osd")
    ceph_osd_count = len(ceph_osd_list)
    # Get the states of all OSDs ("stat" is not a typo since we're reading stats; states are in
    # the stats JSON object)
    osd_stat_reads = list()
    for osd in ceph_osd_list:
        osd_stat_reads += [("osd.stats", osd)]
    all_osd_stats = zkhandler.read_many(osd_stat_reads)
    # Parse out the OSD states
    osd_data = list()
    formatted_osd_states = {"total": ceph_osd_count}
    up_texts = {1: "up", 0: "down"}
    in_texts = {1: "in", 0: "out"}
    for oidx, osd in enumerate(ceph_osd_list):
        # Split the large list of return values by the IDX of this OSD
        # Each OSD result is 1 field long, so just use the IDX
        _osd_stats = all_osd_stats[oidx]
        # We have to load this JSON object and get our up/in states from it
        osd_stats = loads(_osd_stats)
        # Get our states
        osd_up = up_texts[osd_stats['up']]
        osd_in = in_texts[osd_stats['in']]
        osd_data.append(
            {
                "id": osd,
                "up": osd_up,
                "in": osd_in,
            }
        )
        osd_state = f"{osd_up},{osd_in}"
        # Add to the count for this OSD's state
        if osd_state in common.ceph_osd_state_combinations:
            if formatted_osd_states.get(osd_state) is not None:
                formatted_osd_states[osd_state] += 1
            else:
                formatted_osd_states[osd_state] = 1

    # Get the list of Networks
    network_list = zkhandler.children("base.network")
    network_count = len(network_list)

    # Get the list of Ceph pools
    ceph_pool_list = zkhandler.children("base.pool")
    ceph_pool_count = len(ceph_pool_list)

    # Get the list of Ceph volumes
    ceph_volume_list = zkhandler.children("base.volume")
    ceph_volume_count = len(ceph_volume_list)

    # Get the list of Ceph snapshots
    ceph_snapshot_list = zkhandler.children("base.snapshot")
    ceph_snapshot_count = len(ceph_snapshot_list)

    # Get the list of faults
    faults_data = faults.getAllFaults(zkhandler)

    # Format the status data
    cluster_information = {
        "cluster_health": getClusterHealthFromFaults(zkhandler, faults_data),
        "node_health": getNodeHealth(zkhandler, node_list),
        "maintenance": maintenance_state,
        "primary_node": primary_node,
        "pvc_version": pvc_version,
        "upstream_ip": zkhandler.read("base.config.upstream_ip"),
        "nodes": formatted_node_states,
        "vms": formatted_vm_states,
        "networks": network_count,
        "osds": formatted_osd_states,
        "pools": ceph_pool_count,
        "volumes": ceph_volume_count,
        "snapshots": ceph_snapshot_count,
        "detail": {
            "node": node_data,
            "vm": vm_data,
            "osd": osd_data,
            "faults": faults_data,
        }
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
