#!/usr/bin/env python3

# cluster.py - PVC client function library, cluster management
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

from distutils.util import strtobool
from json import loads

import daemon_lib.common as common
import daemon_lib.faults as faults
import daemon_lib.node as pvc_node
import daemon_lib.vm as pvc_vm
import daemon_lib.ceph as pvc_ceph

# import daemon_lib.osd as pvc_osd


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

        try:
            node_health_value = int(node_health_value)
        except Exception:
            pass

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
        pos_start = vidx * 2
        pos_end = vidx * 2 + 2
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
        osd_up = up_texts[osd_stats["up"]]
        osd_in = in_texts[osd_stats["in"]]
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
    ceph_volume_list = list()
    for pool in ceph_pool_list:
        ceph_volume_list_pool = zkhandler.children(("volume", pool))
        if ceph_volume_list_pool is not None:
            ceph_volume_list += [f"{pool}/{volume}" for volume in ceph_volume_list_pool]
    ceph_volume_count = len(ceph_volume_list)

    # Get the list of Ceph snapshots
    ceph_snapshot_list = list()
    for volume in ceph_volume_list:
        ceph_snapshot_list_volume = zkhandler.children(("snapshot", volume))
        if ceph_snapshot_list_volume is not None:
            ceph_snapshot_list += [
                f"{volume}@{snapshot}" for snapshot in ceph_snapshot_list_volume
            ]
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
        },
    }

    return cluster_information


def get_info(zkhandler):
    # This is a thin wrapper function for naming purposes
    cluster_information = getClusterInformation(zkhandler)
    if cluster_information:
        return True, cluster_information
    else:
        return False, "ERROR: Failed to obtain cluster information!"


def get_health_metrics(zkhandler):
    """
    Get health-related metrics from the PVC cluster
    """
    status_retflag, status_data = get_info(zkhandler)
    if not status_retflag:
        return False, "Error: Status data threw error"

    faults_data = status_data["detail"]["faults"]
    node_data = status_data["detail"]["node"]
    vm_data = status_data["detail"]["vm"]
    osd_data = status_data["detail"]["osd"]

    output_lines = list()

    output_lines.append("# HELP pvc_info PVC cluster information")
    output_lines.append("# TYPE pvc_info gauge")
    output_lines.append(
        f"pvc_info{{primary_node=\"{status_data['primary_node']}\", version=\"{status_data['pvc_version']}\", upstream_ip=\"{status_data['upstream_ip']}\"}} 1"
    )

    output_lines.append("# HELP pvc_cluster_maintenance PVC cluster maintenance state")
    output_lines.append("# TYPE pvc_cluster_maintenance gauge")
    output_lines.append(
        f"pvc_cluster_maintenance {1 if bool(strtobool(status_data['maintenance'])) else 0}"
    )

    output_lines.append("# HELP pvc_cluster_health PVC cluster health status")
    output_lines.append("# TYPE pvc_cluster_health gauge")
    output_lines.append(f"pvc_cluster_health {status_data['cluster_health']['health']}")

    output_lines.append("# HELP pvc_cluster_faults PVC cluster new faults")
    output_lines.append("# TYPE pvc_cluster_faults gauge")
    fault_map = dict()
    for fault_type in common.fault_state_combinations:
        fault_map[fault_type] = 0
    for fault in faults_data:
        fault_map[fault["status"]] += 1
    for fault_type in fault_map:
        output_lines.append(
            f'pvc_cluster_faults{{status="{fault_type}"}} {fault_map[fault_type]}'
        )

    # output_lines.append("# HELP pvc_cluster_faults PVC cluster health faults")
    # output_lines.append("# TYPE pvc_cluster_faults gauge")
    # for fault_msg in status_data["cluster_health"]["messages"]:
    #     output_lines.append(
    #         f"pvc_cluster_faults{{id=\"{fault_msg['id']}\", message=\"{fault_msg['text']}\"}} {fault_msg['health_delta']}"
    #     )

    output_lines.append("# HELP pvc_node_health PVC cluster node health status")
    output_lines.append("# TYPE pvc_node_health gauge")
    for node in status_data["node_health"]:
        node_health = status_data["node_health"][node]["health"]
        if isinstance(node_health, (int, float)):
            output_lines.append(f'pvc_node_health{{node="{node}"}} {node_health}')

    output_lines.append("# HELP pvc_node_daemon_states PVC Node daemon state counts")
    output_lines.append("# TYPE pvc_node_daemon_states gauge")
    node_daemon_state_map = dict()
    for state in set([s.split(",")[0] for s in common.node_state_combinations]):
        node_daemon_state_map[state] = 0
    for node in node_data:
        node_daemon_state_map[node["daemon_state"]] += 1
    for state in node_daemon_state_map:
        output_lines.append(
            f'pvc_node_daemon_states{{state="{state}"}} {node_daemon_state_map[state]}'
        )

    output_lines.append("# HELP pvc_node_domain_states PVC Node domain state counts")
    output_lines.append("# TYPE pvc_node_domain_states gauge")
    node_domain_state_map = dict()
    for state in set([s.split(",")[1] for s in common.node_state_combinations]):
        node_domain_state_map[state] = 0
    for node in node_data:
        node_domain_state_map[node["domain_state"]] += 1
    for state in node_domain_state_map:
        output_lines.append(
            f'pvc_node_domain_states{{state="{state}"}} {node_domain_state_map[state]}'
        )

    output_lines.append("# HELP pvc_vm_states PVC VM state counts")
    output_lines.append("# TYPE pvc_vm_states gauge")
    vm_state_map = dict()
    for state in set(common.vm_state_combinations):
        vm_state_map[state] = 0
    for vm in vm_data:
        vm_state_map[vm["state"]] += 1
    for state in vm_state_map:
        output_lines.append(f'pvc_vm_states{{state="{state}"}} {vm_state_map[state]}')

    output_lines.append("# HELP pvc_ceph_osd_up_states PVC OSD up state counts")
    output_lines.append("# TYPE pvc_ceph_osd_up_states gauge")
    osd_up_state_map = dict()
    for state in set([s.split(",")[0] for s in common.ceph_osd_state_combinations]):
        osd_up_state_map[state] = 0
    for osd in osd_data:
        if osd["up"] == "up":
            osd_up_state_map["up"] += 1
        else:
            osd_up_state_map["down"] += 1
    for state in osd_up_state_map:
        output_lines.append(
            f'pvc_ceph_osd_up_states{{state="{state}"}} {osd_up_state_map[state]}'
        )

    output_lines.append("# HELP pvc_ceph_osd_in_states PVC OSD in state counts")
    output_lines.append("# TYPE pvc_ceph_osd_in_states gauge")
    osd_in_state_map = dict()
    for state in set([s.split(",")[1] for s in common.ceph_osd_state_combinations]):
        osd_in_state_map[state] = 0
    for osd in osd_data:
        if osd["in"] == "in":
            osd_in_state_map["in"] += 1
        else:
            osd_in_state_map["out"] += 1
    for state in osd_in_state_map:
        output_lines.append(
            f'pvc_ceph_osd_in_states{{state="{state}"}} {osd_in_state_map[state]}'
        )

    output_lines.append("# HELP pvc_nodes PVC Node count")
    output_lines.append("# TYPE pvc_nodes gauge")
    output_lines.append(f"pvc_nodes {status_data['nodes']['total']}")

    output_lines.append("# HELP pvc_vms PVC VM count")
    output_lines.append("# TYPE pvc_vms gauge")
    output_lines.append(f"pvc_vms {status_data['vms']['total']}")

    output_lines.append("# HELP pvc_osds PVC OSD count")
    output_lines.append("# TYPE pvc_osds gauge")
    output_lines.append(f"pvc_osds {status_data['osds']['total']}")

    output_lines.append("# HELP pvc_networks PVC Network count")
    output_lines.append("# TYPE pvc_networks gauge")
    output_lines.append(f"pvc_networks {status_data['networks']}")

    output_lines.append("# HELP pvc_pools PVC Storage Pool count")
    output_lines.append("# TYPE pvc_pools gauge")
    output_lines.append(f"pvc_pools {status_data['pools']}")

    output_lines.append("# HELP pvc_volumes PVC Storage Volume count")
    output_lines.append("# TYPE pvc_volumes gauge")
    output_lines.append(f"pvc_volumes {status_data['volumes']}")

    output_lines.append("# HELP pvc_snapshots PVC Storage Snapshot count")
    output_lines.append("# TYPE pvc_snapshots gauge")
    output_lines.append(f"pvc_snapshots {status_data['snapshots']}")

    return True, "\n".join(output_lines) + "\n"


def get_resource_metrics(zkhandler):
    """
    Get resource-related metrics from the PVC cluster (except Ceph metrics)
    """
    node_retflag, node_data = pvc_node.get_list(zkhandler)
    if not node_retflag:
        return False, "Error: Node data threw error"

    vm_retflag, vm_data = pvc_vm.get_list(zkhandler)
    if not vm_retflag:
        return False, "Error: VM data threw error"

    osd_retflag, osd_data = pvc_ceph.get_list_osd(zkhandler)
    if not osd_retflag:
        return False, "Error: OSD data threw error"

    pool_retflag, pool_data = pvc_ceph.get_list_pool(zkhandler)
    if not pool_retflag:
        return False, "Error: Pool data threw error"

    output_lines = list()

    #
    # Network Utilization stats
    #
    # This is a bit of a doozie. First, for each node, we have to determine the % utilization
    # of all the (active) network interface on that node, averaged together. Then we average
    # the values of all the nodes together.
    # This is very rough, but should give some idea as to the total network bandwidth used
    # and available.
    all_total_speed = 0
    all_total_util = 0
    all_total_count = 0
    per_node_network_utilization = dict()
    for node in node_data:
        if node["daemon_state"] != "run":
            continue

        total_speed = 0
        total_util = 0
        total_count = 0
        for iface in node["interfaces"].keys():
            link_state = node["interfaces"][iface]["state"]
            if link_state != "up":
                continue

            link_speed = node["interfaces"][iface]["link_speed"] * 2  # full-duplex
            total_speed += link_speed

            total_bps = node["interfaces"][iface]["total_bps"]
            total_util += total_bps

            total_count += 1

        if total_count > 0:
            # Average the speed and util by the count
            avg_speed = float(total_speed / total_count)
            all_total_speed += avg_speed
            avg_util = float(total_util / total_count)
            all_total_util += avg_util

            all_total_count += 1

            per_node_network_utilization[node["name"]] = avg_util / avg_speed * 100
        else:
            per_node_network_utilization[node["name"]] = 0.0

    if all_total_count > 0:
        all_avg_speed = all_total_speed / all_total_count
        all_avg_util = all_total_util / all_total_count

        used_network_percentage = all_avg_util / all_avg_speed * 100
    else:
        used_network_percentage = 0

    #
    # Cluster stats
    #
    output_lines.append(
        "# HELP pvc_cluster_cpu_utilization PVC cluster CPU utilization percentage (n-1)"
    )
    output_lines.append("# TYPE pvc_cluster_cpu_utilization gauge")
    node_sorted_cpu = [
        n["cpu_count"]
        for n in sorted(node_data, key=lambda n: n["cpu_count"], reverse=False)
    ]
    total_cpu = sum(node_sorted_cpu[:-1])
    used_cpu = sum([n["load"] for n in node_data])
    used_cpu_percentage = used_cpu / total_cpu * 100
    output_lines.append(f"pvc_cluster_cpu_utilization {used_cpu_percentage:2.2f}")

    output_lines.append(
        "# HELP pvc_cluster_network_utilization PVC cluster network utilization percentage"
    )
    output_lines.append("# TYPE pvc_cluster_network_utilization gauge")
    output_lines.append(
        f"pvc_cluster_network_utilization {used_network_percentage:2.2f}"
    )

    node_sorted_memory = [
        n["memory"]["total"]
        for n in sorted(node_data, key=lambda n: n["memory"]["total"], reverse=False)
    ]
    total_memory = sum(node_sorted_memory[:-1])

    used_memory = sum([n["memory"]["used"] for n in node_data])
    used_memory_percentage = used_memory / total_memory * 100
    output_lines.append(
        "# HELP pvc_cluster_memory_real_utilization PVC cluster real memory utilization percentage (n-1)"
    )
    output_lines.append("# TYPE pvc_cluster_memory_real_utilization gauge")
    output_lines.append(
        f"pvc_cluster_memory_real_utilization {used_memory_percentage:2.2f}"
    )

    allocated_memory = sum([n["memory"]["allocated"] for n in node_data])
    allocated_memory_percentage = allocated_memory / total_memory * 100
    output_lines.append(
        "# HELP pvc_cluster_memory_allocated_utilization PVC cluster allocated memory utilization percentage (n-1)"
    )
    output_lines.append("# TYPE pvc_cluster_memory_allocated_utilization gauge")
    output_lines.append(
        f"pvc_cluster_memory_allocated_utilization {allocated_memory_percentage:2.2f}"
    )

    provisioned_memory = sum([n["memory"]["provisioned"] for n in node_data])
    provisioned_memory_percentage = provisioned_memory / total_memory * 100
    output_lines.append(
        "# HELP pvc_cluster_memory_provisioned_utilization PVC cluster provisioned memory utilization percentage (n-1)"
    )
    output_lines.append("# TYPE pvc_cluster_memory_provisioned_utilization gauge")
    output_lines.append(
        f"pvc_cluster_memory_provisioned_utilization {provisioned_memory_percentage:2.2f}"
    )

    output_lines.append(
        "# HELP pvc_cluster_disk_utilization PVC cluster disk utilization percentage (n-2)"
    )
    output_lines.append("# TYPE pvc_cluster_disk_utilization gauge")
    # Do it manually rather than a sum() in case one OSD is not fully up yet
    total_disk = 0
    used_disk = 0
    for osd in osd_data:
        try:
            total_disk += osd["stats"]["kb"]
            used_disk += osd["stats"]["kb_used"]
        except Exception:
            continue
    used_disk_percentage = used_disk / total_disk * 100
    output_lines.append(f"pvc_cluster_disk_utilization {used_disk_percentage:2.2f}")

    #
    # Node stats
    #
    output_lines.append("# HELP pvc_node_host_cpus PVC node host CPU count")
    output_lines.append("# TYPE pvc_node_host_cpus gauge")
    for node in node_data:
        total_cpus = (
            node["vcpu"]["total"]
            if isinstance(node["vcpu"]["total"], (int, float))
            else 0
        )
        output_lines.append(
            f"pvc_node_host_cpus{{node=\"{node['name']}\"}} {total_cpus}"
        )

    output_lines.append("# HELP pvc_node_allocated_vcpus PVC node allocated vCPU count")
    output_lines.append("# TYPE pvc_node_allocated_vcpus gauge")
    for node in node_data:
        allocated_cpus = (
            node["vcpu"]["allocated"]
            if isinstance(node["vcpu"]["allocated"], (int, float))
            else 0
        )
        output_lines.append(
            f"pvc_node_allocated_vcpus{{node=\"{node['name']}\"}} {allocated_cpus}"
        )

    output_lines.append("# HELP pvc_node_load PVC node 1 minute load average")
    output_lines.append("# TYPE pvc_node_load gauge")
    for node in node_data:
        load_average = node["load"] if isinstance(node["load"], (int, float)) else 0.0
        output_lines.append(
            f"pvc_node_load_average{{node=\"{node['name']}\"}} {load_average}"
        )

    output_lines.append("# HELP pvc_node_cpu_utilization PVC node CPU utilization")
    output_lines.append("# TYPE pvc_node_cpu_utilization gauge")
    for node in node_data:
        load_average = node["load"] if isinstance(node["load"], (int, float)) else 0.0
        cpu_count = (
            node["cpu_count"] if isinstance(node["cpu_count"], (int, float)) else 0
        )
        if cpu_count > 0:
            used_cpu_percentage = load_average / cpu_count * 100
        else:
            used_cpu_percentage = 0.0
        output_lines.append(
            f"pvc_node_cpu_utilization{{node=\"{node['name']}\"}} {used_cpu_percentage:2.2f}"
        )

    output_lines.append("# HELP pvc_node_domains_count PVC node running domain count")
    output_lines.append("# TYPE pvc_node_domains_count gauge")
    for node in node_data:
        running_domains_count = (
            node["domains_count"]
            if isinstance(node["domains_count"], (int, float))
            else 0
        )
        output_lines.append(
            f"pvc_node_domains_count{{node=\"{node['name']}\"}} {running_domains_count}"
        )

    output_lines.append("# HELP pvc_node_architecture PVC node system architecture")
    output_lines.append("# TYPE pvc_node_architecture gauge")
    for node in node_data:
        architecture = node["arch"]
        output_lines.append(
            f"pvc_node_architecture{{node=\"{node['name']}\",architecture=\"{architecture}\"}} 1"
        )

    output_lines.append("# HELP pvc_node_kernel PVC node active kernel version")
    output_lines.append("# TYPE pvc_node_kernel gauge")
    for node in node_data:
        kernel = node["kernel"]
        output_lines.append(
            f"pvc_node_kernel{{node=\"{node['name']}\",kernel=\"{kernel}\"}} 1"
        )

    output_lines.append(
        "# HELP pvc_node_network_traffic_rx PVC node received network traffic"
    )
    output_lines.append("# TYPE pvc_node_network_traffic_rx gauge")
    for node in node_data:
        rx_bps = 0
        for interface in node["interfaces"].keys():
            rx_bps += node["interfaces"][interface]["rx_bps"]
        output_lines.append(
            f"pvc_node_network_traffic_rx{{node=\"{node['name']}\"}} {rx_bps:2.2f}"
        )

    output_lines.append(
        "# HELP pvc_node_network_traffic_tx PVC node transmitted network traffic"
    )
    output_lines.append("# TYPE pvc_node_network_traffic_tx gauge")
    for node in node_data:
        tx_bps = 0
        for interface in node["interfaces"].keys():
            tx_bps += node["interfaces"][interface]["tx_bps"]
        output_lines.append(
            f"pvc_node_network_traffic_tx{{node=\"{node['name']}\"}} {tx_bps:2.2f}"
        )

    output_lines.append(
        "# HELP pvc_node_network_packets_rx PVC node received network packets"
    )
    output_lines.append("# TYPE pvc_node_network_packets_rx gauge")
    for node in node_data:
        rx_pps = 0
        for interface in node["interfaces"].keys():
            rx_pps += node["interfaces"][interface]["rx_pps"]
        output_lines.append(
            f"pvc_node_network_packets_rx{{node=\"{node['name']}\"}} {rx_pps:2.2f}"
        )

    output_lines.append(
        "# HELP pvc_node_network_packets_tx PVC node transmitted network packets"
    )
    output_lines.append("# TYPE pvc_node_network_packets_tx gauge")
    for node in node_data:
        tx_pps = 0
        for interface in node["interfaces"].keys():
            tx_pps += node["interfaces"][interface]["tx_pps"]
        output_lines.append(
            f"pvc_node_network_packets_tx{{node=\"{node['name']}\"}} {tx_pps:2.2f}"
        )

    output_lines.append(
        "# HELP pvc_node_network_utilization PVC node network utilization percentage"
    )
    output_lines.append("# TYPE pvc_node_network_utilization gauge")
    for node in node_data:
        used_network_percentage = per_node_network_utilization.get(node["name"], 0)
        output_lines.append(
            f"pvc_node_network_utilization{{node=\"{node['name']}\"}} {used_network_percentage:2.2f}"
        )

    output_lines.append("# HELP pvc_node_total_memory PVC node total memory in MB")
    output_lines.append("# TYPE pvc_node_total_memory gauge")
    for node in node_data:
        total_memory = (
            node["memory"]["total"]
            if isinstance(node["memory"]["total"], (int, float))
            else 0
        )
        output_lines.append(
            f"pvc_node_total_memory{{node=\"{node['name']}\"}} {total_memory}"
        )

    output_lines.append(
        "# HELP pvc_node_allocated_memory PVC node allocated memory in MB"
    )
    output_lines.append("# TYPE pvc_node_allocated_memory gauge")
    for node in node_data:
        allocated_memory = (
            node["memory"]["allocated"]
            if isinstance(node["memory"]["allocated"], (int, float))
            else 0
        )
        output_lines.append(
            f"pvc_node_allocated_memory{{node=\"{node['name']}\"}} {allocated_memory}"
        )

    output_lines.append(
        "# HELP pvc_node_allocated_memory_utilization PVC node allocated memory utilization"
    )
    output_lines.append("# TYPE pvc_node_allocated_memory_utilization gauge")
    for node in node_data:
        allocated_memory = (
            node["memory"]["allocated"]
            if isinstance(node["memory"]["allocated"], (int, float))
            else 0
        )
        total_memory = (
            node["memory"]["total"]
            if isinstance(node["memory"]["total"], (int, float))
            else 0
        )
        allocated_memory_utilization = (
            (allocated_memory / total_memory * 100) if total_memory > 0 else 0.0
        )
        output_lines.append(
            f"pvc_node_allocated_memory_utilization{{node=\"{node['name']}\"}} {allocated_memory_utilization}"
        )

    output_lines.append(
        "# HELP pvc_node_provisioned_memory PVC node provisioned memory in MB"
    )
    output_lines.append("# TYPE pvc_node_provisioned_memory gauge")
    for node in node_data:
        provisioned_memory = (
            node["memory"]["provisioned"]
            if isinstance(node["memory"]["provisioned"], (int, float))
            else 0
        )
        output_lines.append(
            f"pvc_node_provisioned_memory{{node=\"{node['name']}\"}} {provisioned_memory}"
        )

    output_lines.append(
        "# HELP pvc_node_provisioned_memory_utilization PVC node provisioned memory utilization"
    )
    output_lines.append("# TYPE pvc_node_provisioned_memory_utilization gauge")
    for node in node_data:
        provisioned_memory = (
            node["memory"]["provisioned"]
            if isinstance(node["memory"]["provisioned"], (int, float))
            else 0
        )
        total_memory = (
            node["memory"]["total"]
            if isinstance(node["memory"]["total"], (int, float))
            else 0
        )
        provisioned_memory_utilization = (
            (provisioned_memory / total_memory * 100) if total_memory > 0 else 0.0
        )
        output_lines.append(
            f"pvc_node_provisioned_memory_utilization{{node=\"{node['name']}\"}} {provisioned_memory_utilization}"
        )

    output_lines.append("# HELP pvc_node_used_memory PVC node used memory in MB")
    output_lines.append("# TYPE pvc_node_used_memory gauge")
    for node in node_data:
        used_memory = (
            node["memory"]["used"]
            if isinstance(node["memory"]["used"], (int, float))
            else 0
        )
        output_lines.append(
            f"pvc_node_used_memory{{node=\"{node['name']}\"}} {used_memory}"
        )

    output_lines.append(
        "# HELP pvc_node_used_memory_utilization PVC node used memory utilization"
    )
    output_lines.append("# TYPE pvc_node_used_memory_utilization gauge")
    for node in node_data:
        used_memory = (
            node["memory"]["used"]
            if isinstance(node["memory"]["used"], (int, float))
            else 0
        )
        total_memory = (
            node["memory"]["total"]
            if isinstance(node["memory"]["total"], (int, float))
            else 0
        )
        used_memory_utilization = (
            (used_memory / total_memory * 100) if total_memory > 0 else 0.0
        )
        output_lines.append(
            f"pvc_node_used_memory_utilization{{node=\"{node['name']}\"}} {used_memory_utilization}"
        )

    output_lines.append("# HELP pvc_node_free_memory PVC node free memory in MB")
    output_lines.append("# TYPE pvc_node_free_memory gauge")
    for node in node_data:
        free_memory = (
            node["memory"]["free"]
            if isinstance(node["memory"]["free"], (int, float))
            else 0
        )
        output_lines.append(
            f"pvc_node_free_memory{{node=\"{node['name']}\"}} {free_memory}"
        )

    #
    # VM stats
    #
    output_lines.append("# HELP pvc_vm_uuid PVC VM UUID")
    output_lines.append("# TYPE pvc_vm_uuid gauge")
    for vm in vm_data:
        uuid = vm["uuid"]
        output_lines.append(f"pvc_vm_uuid{{vm=\"{vm['name']}\", uuid=\"{uuid}\"}} 1")

    output_lines.append("# HELP pvc_vm_description PVC VM description")
    output_lines.append("# TYPE pvc_vm_description gauge")
    for vm in vm_data:
        description = vm["description"]
        output_lines.append(
            f"pvc_vm_description{{vm=\"{vm['name']}\", description=\"{description}\"}} 1"
        )

    output_lines.append("# HELP pvc_vm_profile PVC VM profile")
    output_lines.append("# TYPE pvc_vm_profile gauge")
    for vm in vm_data:
        profile = vm["profile"]
        output_lines.append(
            f"pvc_vm_profile{{vm=\"{vm['name']}\", profile=\"{profile}\"}} 1"
        )

    output_lines.append("# HELP pvc_vm_state PVC VM state")
    output_lines.append("# TYPE pvc_vm_state gauge")
    for vm in vm_data:
        state_colour_map = {
            "start": 0,
            "migrate": 1,
            "unmigrate": 2,
            "provision": 3,
            "disable": 4,
            "shutdown": 5,
            "restart": 6,
            "stop": 7,
            "fail": 8,
            "import": 9,
            "restore": 10,
        }
        state = vm["state"]
        output_lines.append(
            f"pvc_vm_state{{vm=\"{vm['name']}\", state=\"{state}\"}} {state_colour_map[vm['state']]}"
        )

    output_lines.append("# HELP pvc_vm_failed_reason PVC VM failed_reason")
    output_lines.append("# TYPE pvc_vm_failed_reason gauge")
    for vm in vm_data:
        failed_reason = vm["failed_reason"] if vm["failed_reason"] else "N/A"
        output_lines.append(
            f"pvc_vm_failed_reason{{vm=\"{vm['name']}\", failed_reason=\"{failed_reason}\"}} 1"
        )

    output_lines.append("# HELP pvc_vm_node_limit PVC VM node_limit")
    output_lines.append("# TYPE pvc_vm_node_limit gauge")
    for vm in vm_data:
        node_limit = vm["node_limit"]
        output_lines.append(
            f"pvc_vm_node_limit{{vm=\"{vm['name']}\", node_limit=\"{node_limit}\"}} 1"
        )

    output_lines.append("# HELP pvc_vm_node_selector PVC VM node_selector")
    output_lines.append("# TYPE pvc_vm_node_selector gauge")
    for vm in vm_data:
        node_selector = (
            "Default"
            if vm["node_selector"] is None or vm["node_selector"] == "None"
            else vm["node_selector"]
        )
        output_lines.append(
            f"pvc_vm_node_selector{{vm=\"{vm['name']}\", node_selector=\"{node_selector}\"}} 1"
        )

    output_lines.append("# HELP pvc_vm_node_autostart PVC VM node_autostart")
    output_lines.append("# TYPE pvc_vm_node_autostart gauge")
    for vm in vm_data:
        autostart = vm["node_autostart"]
        autostart_val = 1 if vm["node_autostart"] else 0
        output_lines.append(
            f"pvc_vm_autostart{{vm=\"{vm['name']}\", autostart=\"{autostart}\"}} {autostart_val}"
        )

    output_lines.append("# HELP pvc_vm_migration_method PVC VM migration_method")
    output_lines.append("# TYPE pvc_vm_migration_method gauge")
    for vm in vm_data:
        migration_method = (
            "Default"
            if vm["migration_method"] is None or vm["migration_method"] == "None"
            else vm["migration_method"]
        )
        output_lines.append(
            f"pvc_vm_migration_method{{vm=\"{vm['name']}\", migration_method=\"{migration_method}\"}} 1"
        )

    output_lines.append("# HELP pvc_vm_tags PVC VM tags")
    output_lines.append("# TYPE pvc_vm_tags gauge")
    for vm in vm_data:
        tags = [f"tag=\"{t['name']}\"" for t in vm["tags"]]
        for tag in tags:
            output_lines.append(f"pvc_vm_tags{{vm=\"{vm['name']}\", {tag}}} 1")

    output_lines.append("# HELP pvc_vm_active_node PVC VM active node")
    output_lines.append("# TYPE pvc_vm_active_node gauge")
    for vm in vm_data:
        active_node = vm["node"]
        output_lines.append(
            f"pvc_vm_active_node{{vm=\"{vm['name']}\", node=\"{active_node}\"}} 1"
        )

    output_lines.append("# HELP pvc_vm_migrated PVC VM migrated state")
    output_lines.append("# TYPE pvc_vm_migrated gauge")
    for vm in vm_data:
        migrated = 0 if vm["migrated"] == "no" else 1
        last_node = vm["last_node"] if vm["last_node"] else "No"
        output_lines.append(
            f"pvc_vm_migrated{{vm=\"{vm['name']}\", last_node=\"{last_node}\"}} {migrated}"
        )

    output_lines.append("# HELP pvc_vm_machine_type PVC VM machine type")
    output_lines.append("# TYPE pvc_vm_machine_type gauge")
    for vm in vm_data:
        machine_type = vm["machine"]
        output_lines.append(
            f"pvc_vm_machine_type{{vm=\"{vm['name']}\", machine_type=\"{machine_type}\"}} 1"
        )

    output_lines.append("# HELP pvc_vm_serial_console PVC VM serial console")
    output_lines.append("# TYPE pvc_vm_serial_console gauge")
    for vm in vm_data:
        output_lines.append(
            f"pvc_vm_serial_console{{vm=\"{vm['name']}\"}} {1 if vm.get('console', '') == 'pty' else 0}"
        )

    output_lines.append("# HELP pvc_vm_vnc_console PVC VM VNC console")
    output_lines.append("# TYPE pvc_vm_vnc_console gauge")
    for vm in vm_data:
        output_lines.append(
            f"pvc_vm_vnc_console{{vm=\"{vm['name']}\"}} {1 if vm['vnc'].get('listen', '') == 'pty' else 0}"
        )

    output_lines.append("# HELP pvc_vm_vnc_listen_address PVC VM VNC listen address")
    output_lines.append("# TYPE pvc_vm_vnc_listen_address gauge")
    for vm in vm_data:
        vnc_listen_address = vm["vnc"]["listen"]
        output_lines.append(
            f"pvc_vm_vnc_listen_address{{vm=\"{vm['name']}\", address=\"{vnc_listen_address}\"}} {1 if vnc_listen_address is not None else 0}"
        )

    output_lines.append("# HELP pvc_vm_vnc_listen_port PVC VM VNC listen port")
    output_lines.append("# TYPE pvc_vm_vnc_listen_port gauge")
    for vm in vm_data:
        vnc_listen_port = vm["vnc"]["port"]
        output_lines.append(
            f"pvc_vm_vnc_listen_port{{vm=\"{vm['name']}\", port=\"{vnc_listen_port}\"}} {1 if vnc_listen_port is not None else 0}"
        )

    output_lines.append("# HELP pvc_vm_vcpus PVC VM provisioned vCPUs")
    output_lines.append("# TYPE pvc_vm_vcpus gauge")
    for vm in vm_data:
        vcpus = vm["vcpu"]
        output_lines.append(f"pvc_vm_vcpus{{vm=\"{vm['name']}\"}} {vcpus}")

    output_lines.append("# HELP pvc_vm_vcpu_topology PVC VM vCPU topology")
    output_lines.append("# TYPE pvc_vm_vcpu_topology gauge")
    for vm in vm_data:
        vcpu_topology = vm["vcpu_topology"]
        output_lines.append(
            f"pvc_vm_vcpu_topology{{vm=\"{vm['name']}\", topology=\"{vcpu_topology}\"}} 1"
        )

    output_lines.append(
        "# HELP pvc_vm_vcpus_cpu_time PVC VM vCPU CPU time milliseconds"
    )
    output_lines.append("# TYPE pvc_vm_vcpus_cpu_time gauge")
    for vm in vm_data:
        try:
            cpu_time = vm["vcpu_stats"]["cpu_time"] / 1000000
        except Exception:
            cpu_time = 0
        output_lines.append(f"pvc_vm_vcpus_cpu_time{{vm=\"{vm['name']}\"}} {cpu_time}")

    output_lines.append(
        "# HELP pvc_vm_vcpus_user_time PVC VM vCPU User time milliseconds"
    )
    output_lines.append("# TYPE pvc_vm_vcpus_user_time gauge")
    for vm in vm_data:
        try:
            user_time = vm["vcpu_stats"]["user_time"] / 1000000
        except Exception:
            user_time = 0
        output_lines.append(
            f"pvc_vm_vcpus_user_time{{vm=\"{vm['name']}\"}} {user_time}"
        )

    output_lines.append(
        "# HELP pvc_vm_vcpus_system_time PVC VM vCPU System time milliseconds"
    )
    output_lines.append("# TYPE pvc_vm_vcpus_system_time gauge")
    for vm in vm_data:
        try:
            system_time = vm["vcpu_stats"]["system_time"] / 1000000
        except Exception:
            system_time = 0
        output_lines.append(
            f"pvc_vm_vcpus_system_time{{vm=\"{vm['name']}\"}} {system_time}"
        )

    output_lines.append("# HELP pvc_vm_memory PVC VM provisioned memory MB")
    output_lines.append("# TYPE pvc_vm_memory gauge")
    for vm in vm_data:
        memory = vm["memory"]
        output_lines.append(f"pvc_vm_memory{{vm=\"{vm['name']}\"}} {memory}")

    output_lines.append(
        "# HELP pvc_vm_memory_stats_actual PVC VM actual memory allocation KB"
    )
    output_lines.append("# TYPE pvc_vm_memory_stats_actual gauge")
    for vm in vm_data:
        actual_memory = vm["memory_stats"].get("actual", 0)
        output_lines.append(
            f"pvc_vm_memory_stats_actual{{vm=\"{vm['name']}\"}} {actual_memory}"
        )

    output_lines.append("# HELP pvc_vm_memory_stats_rss PVC VM RSS memory KB")
    output_lines.append("# TYPE pvc_vm_memory_stats_rss gauge")
    for vm in vm_data:
        rss_memory = vm["memory_stats"].get("rss", 0)
        output_lines.append(
            f"pvc_vm_memory_stats_rss{{vm=\"{vm['name']}\"}} {rss_memory}"
        )

    output_lines.append("# HELP pvc_vm_memory_stats_unused PVC VM unused memory KB")
    output_lines.append("# TYPE pvc_vm_memory_stats_unused gauge")
    for vm in vm_data:
        unused_memory = vm["memory_stats"].get("unused", 0)
        output_lines.append(
            f"pvc_vm_memory_stats_unused{{vm=\"{vm['name']}\"}} {unused_memory}"
        )

    output_lines.append(
        "# HELP pvc_vm_memory_stats_available PVC VM available memory KB"
    )
    output_lines.append("# TYPE pvc_vm_memory_stats_available gauge")
    for vm in vm_data:
        available_memory = vm["memory_stats"].get("available", 0)
        output_lines.append(
            f"pvc_vm_memory_stats_available{{vm=\"{vm['name']}\"}} {available_memory}"
        )

    output_lines.append("# HELP pvc_vm_memory_stats_usable PVC VM usable memory KB")
    output_lines.append("# TYPE pvc_vm_memory_stats_usable gauge")
    for vm in vm_data:
        usable_memory = vm["memory_stats"].get("usable", 0)
        output_lines.append(
            f"pvc_vm_memory_stats_usable{{vm=\"{vm['name']}\"}} {usable_memory}"
        )

    output_lines.append(
        "# HELP pvc_vm_memory_stats_disk_caches PVC VM disk cache memory KB"
    )
    output_lines.append("# TYPE pvc_vm_memory_stats_disk_caches gauge")
    for vm in vm_data:
        disk_caches_memory = vm["memory_stats"].get("disk_caches", 0)
        output_lines.append(
            f"pvc_vm_memory_stats_disk_caches{{vm=\"{vm['name']}\"}} {disk_caches_memory}"
        )

    output_lines.append("# HELP pvc_vm_memory_swap_in PVC VM memory swap in")
    output_lines.append("# TYPE pvc_vm_memory_swap_in gauge")
    for vm in vm_data:
        swap_in_memory = vm["memory_stats"].get("swap_in", 0)
        output_lines.append(
            f"pvc_vm_memory_stats_swap_in{{vm=\"{vm['name']}\"}} {swap_in_memory}"
        )

    output_lines.append("# HELP pvc_vm_memory_swap_out PVC VM memory swap out")
    output_lines.append("# TYPE pvc_vm_memory_swap_out gauge")
    for vm in vm_data:
        swap_out_memory = vm["memory_stats"].get("swap_out", 0)
        output_lines.append(
            f"pvc_vm_memory_stats_swap_out{{vm=\"{vm['name']}\"}} {swap_out_memory}"
        )

    output_lines.append("# HELP pvc_vm_memory_major_fault PVC VM memory major faults")
    output_lines.append("# TYPE pvc_vm_memory_major_fault gauge")
    for vm in vm_data:
        major_fault_memory = vm["memory_stats"].get("major_fault", 0)
        output_lines.append(
            f"pvc_vm_memory_stats_major_fault{{vm=\"{vm['name']}\"}} {major_fault_memory}"
        )

    output_lines.append("# HELP pvc_vm_memory_minor_fault PVC VM memory minor faults")
    output_lines.append("# TYPE pvc_vm_memory_minor_fault gauge")
    for vm in vm_data:
        minor_fault_memory = vm["memory_stats"].get("minor_fault", 0)
        output_lines.append(
            f"pvc_vm_memory_stats_minor_fault{{vm=\"{vm['name']}\"}} {minor_fault_memory}"
        )

    output_lines.append(
        "# HELP pvc_vm_memory_hugetlb_pgalloc PVC VM memory huge table allocations"
    )
    output_lines.append("# TYPE pvc_vm_memory_hugetlb_pgalloc gauge")
    for vm in vm_data:
        hugetlb_pgalloc_memory = vm["memory_stats"].get("hugetlb_pgalloc", 0)
        output_lines.append(
            f"pvc_vm_memory_stats_hugetlb_pgalloc{{vm=\"{vm['name']}\"}} {hugetlb_pgalloc_memory}"
        )

    output_lines.append(
        "# HELP pvc_vm_memory_hugetlb_pgfail PVC VM memory huge table failures"
    )
    output_lines.append("# TYPE pvc_vm_memory_hugetlb_pgfail gauge")
    for vm in vm_data:
        hugetlb_pgfail_memory = vm["memory_stats"].get("hugetlb_pgfail", 0)
        output_lines.append(
            f"pvc_vm_memory_stats_hugetlb_pgfail{{vm=\"{vm['name']}\"}} {hugetlb_pgfail_memory}"
        )

    #
    # VM Network stats
    #
    output_lines.append("# HELP pvc_vm_network_macaddr PVC VM network MAC address")
    output_lines.append("# TYPE pvc_vm_network_macaddr gauge")
    for vm in vm_data:
        for network in vm["networks"]:
            vni = network["vni"]
            mac_address = network["mac"]
            output_lines.append(
                f"pvc_vm_network_macaddr{{vm=\"{vm['name']}\",vni=\"{vni}\",macaddr=\"{mac_address}\"}} 1"
            )

    output_lines.append("# HELP pvc_vm_network_model PVC VM network device model")
    output_lines.append("# TYPE pvc_vm_network_model gauge")
    for vm in vm_data:
        for network in vm["networks"]:
            vni = network["vni"]
            model = network["model"]
            output_lines.append(
                f"pvc_vm_network_model{{vm=\"{vm['name']}\",vni=\"{vni}\",model=\"{model}\"}} 1"
            )

    output_lines.append("# HELP pvc_vm_network_rd_packets PVC VM network packets read")
    output_lines.append("# TYPE pvc_vm_network_rd_packets gauge")
    for vm in vm_data:
        for network in vm["networks"]:
            vni = network["vni"]
            rd_packets = network["rd_packets"]
            output_lines.append(
                f"pvc_vm_network_rd_packets{{vm=\"{vm['name']}\",vni=\"{vni}\"}} {rd_packets}"
            )

    output_lines.append("# HELP pvc_vm_network_rd_bits PVC VM network bits read")
    output_lines.append("# TYPE pvc_vm_network_rd_bits gauge")
    for vm in vm_data:
        for network in vm["networks"]:
            vni = network["vni"]
            rd_bits = network["rd_bytes"] * 8
            output_lines.append(
                f"pvc_vm_network_rd_bits{{vm=\"{vm['name']}\",vni=\"{vni}\"}} {rd_bits}"
            )

    output_lines.append("# HELP pvc_vm_network_rd_errors PVC VM network read errors")
    output_lines.append("# TYPE pvc_vm_network_rd_errors gauge")
    for vm in vm_data:
        for network in vm["networks"]:
            vni = network["vni"]
            rd_errors = network["rd_errors"]
            output_lines.append(
                f"pvc_vm_network_rd_errors{{vm=\"{vm['name']}\",vni=\"{vni}\"}} {rd_errors}"
            )

    output_lines.append("# HELP pvc_vm_network_rd_drops PVC VM network read drops")
    output_lines.append("# TYPE pvc_vm_network_rd_drops gauge")
    for vm in vm_data:
        for network in vm["networks"]:
            vni = network["vni"]
            rd_drops = network["rd_drops"]
            output_lines.append(
                f"pvc_vm_network_rd_drops{{vm=\"{vm['name']}\",vni=\"{vni}\"}} {rd_drops}"
            )

    output_lines.append("# HELP pvc_vm_network_wr_packets PVC VM network packets write")
    output_lines.append("# TYPE pvc_vm_network_wr_packets gauge")
    for vm in vm_data:
        for network in vm["networks"]:
            vni = network["vni"]
            wr_packets = network["wr_packets"]
            output_lines.append(
                f"pvc_vm_network_wr_packets{{vm=\"{vm['name']}\",vni=\"{vni}\"}} {wr_packets}"
            )

    output_lines.append("# HELP pvc_vm_network_wr_bits PVC VM network bits write")
    output_lines.append("# TYPE pvc_vm_network_wr_bits gauge")
    for vm in vm_data:
        for network in vm["networks"]:
            vni = network["vni"]
            wr_bits = network["wr_bytes"] * 8
            output_lines.append(
                f"pvc_vm_network_wr_bits{{vm=\"{vm['name']}\",vni=\"{vni}\"}} {wr_bits}"
            )

    output_lines.append("# HELP pvc_vm_network_wr_errors PVC VM network write errors")
    output_lines.append("# TYPE pvc_vm_network_wr_errors gauge")
    for vm in vm_data:
        for network in vm["networks"]:
            vni = network["vni"]
            wr_errors = network["wr_errors"]
            output_lines.append(
                f"pvc_vm_network_wr_errors{{vm=\"{vm['name']}\",vni=\"{vni}\"}} {wr_errors}"
            )

    output_lines.append("# HELP pvc_vm_network_wr_drops PVC VM network write drops")
    output_lines.append("# TYPE pvc_vm_network_wr_drops gauge")
    for vm in vm_data:
        for network in vm["networks"]:
            vni = network["vni"]
            wr_drops = network["wr_drops"]
            output_lines.append(
                f"pvc_vm_network_wr_drops{{vm=\"{vm['name']}\",vni=\"{vni}\"}} {wr_drops}"
            )

    #
    # VM Disk stats
    #
    output_lines.append("# HELP pvc_vm_disk_rd_req PVC VM disk read requests")
    output_lines.append("# TYPE pvc_vm_disk_rd_req gauge")
    for vm in vm_data:
        for disk in vm["disks"]:
            dev = disk["dev"]
            rd_req = disk["rd_req"]
            output_lines.append(
                f"pvc_vm_disk_rd_req{{vm=\"{vm['name']}\",disk=\"{dev}\"}} {rd_req}"
            )

    output_lines.append("# HELP pvc_vm_disk_rd_bytes PVC VM disk bytes read")
    output_lines.append("# TYPE pvc_vm_disk_rd_bytes gauge")
    for vm in vm_data:
        for disk in vm["disks"]:
            dev = disk["dev"]
            rd_bytes = disk["rd_bytes"]
            output_lines.append(
                f"pvc_vm_disk_rd_bytes{{vm=\"{vm['name']}\",disk=\"{dev}\"}} {rd_bytes}"
            )

    output_lines.append("# HELP pvc_vm_disk_wr_req PVC VM disk write requests")
    output_lines.append("# TYPE pvc_vm_disk_wr_req gauge")
    for vm in vm_data:
        for disk in vm["disks"]:
            dev = disk["dev"]
            wr_req = disk["wr_req"]
            output_lines.append(
                f"pvc_vm_disk_wr_req{{vm=\"{vm['name']}\",disk=\"{dev}\"}} {wr_req}"
            )

    output_lines.append("# HELP pvc_vm_disk_wr_bytes PVC VM disk bytes write")
    output_lines.append("# TYPE pvc_vm_disk_wr_bytes gauge")
    for vm in vm_data:
        for disk in vm["disks"]:
            dev = disk["dev"]
            wr_bytes = disk["wr_bytes"]
            output_lines.append(
                f"pvc_vm_disk_wr_bytes{{vm=\"{vm['name']}\",disk=\"{dev}\"}} {wr_bytes}"
            )

    #
    # Ceph OSD stats
    #
    output_lines.append("# HELP pvc_ceph_osd_device PVC OSD device (host + blockdev)")
    output_lines.append("# TYPE pvc_ceph_osd_device gauge")
    for osd in osd_data:
        osd_node = osd["node"]
        osd_blockdev = osd["device"]
        osd_device = f"{osd_node}:{osd_blockdev}"
        output_lines.append(
            f"pvc_ceph_osd_device{{osd=\"{osd['id']}\",device=\"{osd_device}\"}} 1"
        )

    output_lines.append("# HELP pvc_ceph_osd_db_device PVC OSD database device")
    output_lines.append("# TYPE pvc_ceph_osd_db_device gauge")
    for osd in osd_data:
        osd_db_device = osd["db_device"]
        output_lines.append(
            f"pvc_ceph_osd_db_device{{osd=\"{osd['id']}\",db_device=\"{osd_db_device}\"}} 1"
        )

    output_lines.append("# HELP pvc_ceph_osd_device_class PVC OSD device class")
    output_lines.append("# TYPE pvc_ceph_osd_device_class gauge")
    for osd in osd_data:
        try:
            osd_device_class = osd["stats"]["class"]
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_osd_device_class{{osd=\"{osd['id']}\",device_class=\"{osd_device_class}\"}} 1"
        )

    output_lines.append("# HELP pvc_ceph_osd_util PVC OSD utilization percentage")
    output_lines.append("# TYPE pvc_ceph_osd_util gauge")
    for osd in osd_data:
        try:
            osd_util = osd["stats"]["utilization"]
        except Exception:
            continue
        output_lines.append(f"pvc_ceph_osd_util{{osd=\"{osd['id']}\"}} {osd_util}")

    output_lines.append("# HELP pvc_ceph_osd_var PVC OSD utilization variability")
    output_lines.append("# TYPE pvc_ceph_osd_var gauge")
    for osd in osd_data:
        try:
            osd_var = osd["stats"]["var"]
        except Exception:
            continue
        output_lines.append(f"pvc_ceph_osd_var{{osd=\"{osd['id']}\"}} {osd_var}")

    output_lines.append("# HELP pvc_ceph_osd_pgs PVC OSD placement groups")
    output_lines.append("# TYPE pvc_ceph_osd_pgs gauge")
    for osd in osd_data:
        try:
            osd_pgs = osd["stats"]["pgs"]
        except Exception:
            continue
        output_lines.append(f"pvc_ceph_osd_pgs{{osd=\"{osd['id']}\"}} {osd_pgs}")

    output_lines.append("# HELP pvc_ceph_osd_size PVC OSD size KB")
    output_lines.append("# TYPE pvc_ceph_osd_size gauge")
    for osd in osd_data:
        try:
            osd_size = osd["stats"]["kb"]
        except Exception:
            continue
        output_lines.append(f"pvc_ceph_osd_size{{osd=\"{osd['id']}\"}} {osd_size}")

    output_lines.append("# HELP pvc_ceph_osd_used PVC OSD used bytes")
    output_lines.append("# TYPE pvc_ceph_osd_used gauge")
    for osd in osd_data:
        try:
            osd_used = osd["stats"]["kb_used"] * 1024
        except Exception:
            continue
        output_lines.append(f"pvc_ceph_osd_used{{osd=\"{osd['id']}\"}} {osd_used}")

    output_lines.append("# HELP pvc_ceph_osd_used_data PVC OSD used (data) bytes")
    output_lines.append("# TYPE pvc_ceph_osd_used_data gauge")
    for osd in osd_data:
        try:
            osd_used_data = osd["stats"]["kb_used_data"] * 1024
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_osd_used_data{{osd=\"{osd['id']}\"}} {osd_used_data}"
        )

    output_lines.append("# HELP pvc_ceph_osd_used_omap PVC OSD used (omap) bytes")
    output_lines.append("# TYPE pvc_ceph_osd_used_omap gauge")
    for osd in osd_data:
        try:
            osd_used_omap = osd["stats"]["kb_used_omap"] * 1024
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_osd_used_omap{{osd=\"{osd['id']}\"}} {osd_used_omap}"
        )

    output_lines.append("# HELP pvc_ceph_osd_used_meta PVC OSD used (meta) bytes")
    output_lines.append("# TYPE pvc_ceph_osd_used_meta gauge")
    for osd in osd_data:
        try:
            osd_used_meta = osd["stats"]["kb_used_meta"] * 1024
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_osd_used_meta{{osd=\"{osd['id']}\"}} {osd_used_meta}"
        )

    output_lines.append("# HELP pvc_ceph_osd_avail PVC OSD available bytes")
    output_lines.append("# TYPE pvc_ceph_osd_avail gauge")
    for osd in osd_data:
        try:
            osd_avail = osd["stats"]["kb_avail"] * 1024
        except Exception:
            continue
        output_lines.append(f"pvc_ceph_osd_avail{{osd=\"{osd['id']}\"}} {osd_avail}")

    output_lines.append("# HELP pvc_ceph_osd_weight PVC OSD weight")
    output_lines.append("# TYPE pvc_ceph_osd_weight gauge")
    for osd in osd_data:
        try:
            osd_weight = osd["stats"]["weight"]
        except Exception:
            continue
        output_lines.append(f"pvc_ceph_osd_weight{{osd=\"{osd['id']}\"}} {osd_weight}")

    output_lines.append("# HELP pvc_ceph_osd_reweight PVC OSD reweight")
    output_lines.append("# TYPE pvc_ceph_osd_reweight gauge")
    for osd in osd_data:
        try:
            osd_reweight = osd["stats"]["reweight"]
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_osd_reweight{{osd=\"{osd['id']}\"}} {osd_reweight}"
        )

    output_lines.append(
        "# HELP pvc_ceph_osd_wr_ops PVC OSD write operations per second"
    )
    output_lines.append("# TYPE pvc_ceph_osd_wr_ops gauge")
    for osd in osd_data:
        try:
            osd_wr_ops = osd["stats"]["wr_ops"]
        except Exception:
            continue
        output_lines.append(f"pvc_ceph_osd_wr_ops{{osd=\"{osd['id']}\"}} {osd_wr_ops}")

    output_lines.append("# HELP pvc_ceph_osd_wr_data PVC OSD write bytes per second")
    output_lines.append("# TYPE pvc_ceph_osd_wr_data gauge")
    for osd in osd_data:
        try:
            osd_wr_data = pvc_ceph.format_bytes_fromhuman(osd["stats"]["wr_data"])
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_osd_wr_data{{osd=\"{osd['id']}\"}} {osd_wr_data}"
        )

    output_lines.append("# HELP pvc_ceph_osd_rd_ops PVC OSD read operations per second")
    output_lines.append("# TYPE pvc_ceph_osd_rd_ops gauge")
    for osd in osd_data:
        try:
            osd_rd_ops = osd["stats"]["rd_ops"]
        except Exception:
            continue
        output_lines.append(f"pvc_ceph_osd_rd_ops{{osd=\"{osd['id']}\"}} {osd_rd_ops}")

    output_lines.append("# HELP pvc_ceph_osd_rd_data PVC OSD read bytes per second")
    output_lines.append("# TYPE pvc_ceph_osd_rd_data gauge")
    for osd in osd_data:
        try:
            osd_rd_data = pvc_ceph.format_bytes_fromhuman(osd["stats"]["rd_data"])
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_osd_rd_data{{osd=\"{osd['id']}\"}} {osd_rd_data}"
        )

    #
    # Ceph Pool stats
    #
    output_lines.append("# HELP pvc_ceph_pool_tier PVC Pool tier")
    output_lines.append("# TYPE pvc_ceph_pool_tier gauge")
    for pool in pool_data:
        pool_tier = pool["tier"]
        output_lines.append(
            f"pvc_ceph_pool_tier{{pool=\"{pool['name']}\",tier=\"{pool_tier}\"}} 1"
        )

    output_lines.append("# HELP pvc_ceph_pool_pgs PVC Pool placement groups")
    output_lines.append("# TYPE pvc_ceph_pool_pgs gauge")
    for pool in pool_data:
        pool_pgs = pool["pgs"]
        output_lines.append(f"pvc_ceph_pool_pgs{{pool=\"{pool['name']}\"}} {pool_pgs}")

    output_lines.append("# HELP pvc_ceph_pool_volumes PVC Pool volumes count")
    output_lines.append("# TYPE pvc_ceph_pool_volumes gauge")
    for pool in pool_data:
        pool_volumes = pool["volume_count"]
        output_lines.append(
            f"pvc_ceph_pool_volumes{{pool=\"{pool['name']}\"}} {pool_volumes}"
        )

    output_lines.append("# HELP pvc_ceph_pool_stored_bytes PVC Pool stored bytes")
    output_lines.append("# TYPE pvc_ceph_pool_stored_bytes gauge")
    for pool in pool_data:
        try:
            pool_stored_bytes = pool["stats"]["stored_bytes"]
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_pool_stored_bytes{{pool=\"{pool['name']}\"}} {pool_stored_bytes}"
        )

    output_lines.append("# HELP pvc_ceph_pool_free_bytes PVC Pool free bytes")
    output_lines.append("# TYPE pvc_ceph_pool_free_bytes gauge")
    for pool in pool_data:
        try:
            pool_free_bytes = pool["stats"]["free_bytes"]
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_pool_free_bytes{{pool=\"{pool['name']}\"}} {pool_free_bytes}"
        )

    output_lines.append("# HELP pvc_ceph_pool_used_bytes PVC Pool used bytes")
    output_lines.append("# TYPE pvc_ceph_pool_used_bytes gauge")
    for pool in pool_data:
        try:
            pool_used_bytes = pool["stats"]["used_bytes"]
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_pool_used_bytes{{pool=\"{pool['name']}\"}} {pool_used_bytes}"
        )

    output_lines.append("# HELP pvc_ceph_pool_used_percent PVC Pool used percent")
    output_lines.append("# TYPE pvc_ceph_pool_used_percent gauge")
    for pool in pool_data:
        try:
            pool_used_percent = pool["stats"]["used_percent"] * 100
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_pool_used_percent{{pool=\"{pool['name']}\"}} {pool_used_percent:2.2f}"
        )

    output_lines.append("# HELP pvc_ceph_pool_num_objects PVC Pool total objects")
    output_lines.append("# TYPE pvc_ceph_pool_num_objects gauge")
    for pool in pool_data:
        try:
            pool_num_objects = pool["stats"]["num_objects"]
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_pool_num_objects{{pool=\"{pool['name']}\"}} {pool_num_objects}"
        )

    output_lines.append(
        "# HELP pvc_ceph_pool_num_objects_clones PVC Pool clone objects"
    )
    output_lines.append("# TYPE pvc_ceph_pool_num_objects_clones gauge")
    for pool in pool_data:
        try:
            pool_num_objects_clones = pool["stats"]["num_object_clones"]
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_pool_num_objects_clones{{pool=\"{pool['name']}\"}} {pool_num_objects_clones}"
        )

    output_lines.append(
        "# HELP pvc_ceph_pool_num_objects_copies PVC Pool object copies"
    )
    output_lines.append("# TYPE pvc_ceph_pool_num_objects_copies gauge")
    for pool in pool_data:
        try:
            pool_num_objects_copies = pool["stats"]["num_object_copies"]
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_pool_num_objects_copies{{pool=\"{pool['name']}\"}} {pool_num_objects_copies}"
        )

    output_lines.append(
        "# HELP pvc_ceph_pool_num_objects_missing_on_primary PVC Pool objects missing on primary"
    )
    output_lines.append("# TYPE pvc_ceph_pool_num_objects_missing_on_primary gauge")
    for pool in pool_data:
        try:
            pool_num_objects_missing_on_primary = pool["stats"][
                "num_objects_missing_on_primary"
            ]
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_pool_num_objects_missing_on_primary{{pool=\"{pool['name']}\"}} {pool_num_objects_missing_on_primary}"
        )

    output_lines.append(
        "# HELP pvc_ceph_pool_num_objects_unfound PVC Pool objects unfound"
    )
    output_lines.append("# TYPE pvc_ceph_pool_num_objects_unfound gauge")
    for pool in pool_data:
        try:
            pool_num_objects_unfound = pool["stats"]["num_objects_unfound"]
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_pool_num_objects_unfound{{pool=\"{pool['name']}\"}} {pool_num_objects_unfound}"
        )

    output_lines.append(
        "# HELP pvc_ceph_pool_num_objects_degraded PVC Pool objects degraded"
    )
    output_lines.append("# TYPE pvc_ceph_pool_num_objects_degraded gauge")
    for pool in pool_data:
        try:
            pool_num_objects_degraded = pool["stats"]["num_objects_degraded"]
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_pool_num_objects_degraded{{pool=\"{pool['name']}\"}} {pool_num_objects_degraded}"
        )

    output_lines.append(
        "# HELP pvc_ceph_pool_read_ops PVC Pool read operations lifetime"
    )
    output_lines.append("# TYPE pvc_ceph_pool_read_ops gauge")
    for pool in pool_data:
        try:
            pool_read_ops = pool["stats"]["read_ops"]
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_pool_read_ops{{pool=\"{pool['name']}\"}} {pool_read_ops}"
        )

    output_lines.append("# HELP pvc_ceph_pool_read_bytes PVC Pool read bytes lifetime")
    output_lines.append("# TYPE pvc_ceph_pool_read_bytes gauge")
    for pool in pool_data:
        try:
            pool_read_bytes = pool["stats"]["read_bytes"]
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_pool_read_bytes{{pool=\"{pool['name']}\"}} {pool_read_bytes}"
        )

    output_lines.append(
        "# HELP pvc_ceph_pool_write_ops PVC Pool write operations lifetime"
    )
    output_lines.append("# TYPE pvc_ceph_pool_write_ops gauge")
    for pool in pool_data:
        try:
            pool_write_ops = pool["stats"]["write_ops"]
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_pool_write_ops{{pool=\"{pool['name']}\"}} {pool_write_ops}"
        )

    output_lines.append(
        "# HELP pvc_ceph_pool_write_bytes PVC Pool write bytes lifetime"
    )
    output_lines.append("# TYPE pvc_ceph_pool_write_bytes gauge")
    for pool in pool_data:
        try:
            pool_write_bytes = pool["stats"]["write_bytes"]
        except Exception:
            continue
        output_lines.append(
            f"pvc_ceph_pool_write_bytes{{pool=\"{pool['name']}\"}} {pool_write_bytes}"
        )

    return True, "\n".join(output_lines) + "\n"


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
