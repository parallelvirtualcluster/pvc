#!/usr/bin/env python3

# node.py - PVC client function library, node management
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
import json

import daemon_lib.common as common


def getNodeHealthDetails(zkhandler, node_name, node_health_plugins):
    plugin_reads = list()
    for plugin in node_health_plugins:
        plugin_reads += [
            (
                "node.monitoring.data",
                node_name,
                "monitoring_plugin.last_run",
                plugin,
            ),
            (
                "node.monitoring.data",
                node_name,
                "monitoring_plugin.health_delta",
                plugin,
            ),
            (
                "node.monitoring.data",
                node_name,
                "monitoring_plugin.message",
                plugin,
            ),
            (
                "node.monitoring.data",
                node_name,
                "monitoring_plugin.data",
                plugin,
            ),
        ]
    all_plugin_data = list(zkhandler.read_many(plugin_reads))

    node_health_details = list()
    for pidx, plugin in enumerate(node_health_plugins):
        # Split the large list of return values by the IDX of this plugin
        # Each plugin result is 4 fields long
        pos_start = pidx * 4
        pos_end = pidx * 4 + 4
        (
            plugin_last_run,
            plugin_health_delta,
            plugin_message,
            plugin_data,
        ) = tuple(all_plugin_data[pos_start:pos_end])
        if plugin_data is None:
            continue
        plugin_output = {
            "name": plugin,
            "last_run": int(plugin_last_run) if plugin_last_run is not None else None,
            "health_delta": int(plugin_health_delta),
            "message": plugin_message,
            "data": json.loads(plugin_data),
        }
        node_health_details.append(plugin_output)

    return node_health_details


def getNodeInformation(zkhandler, node_name):
    """
    Gather information about a node from the Zookeeper database and return a dict() containing it.
    """

    (
        node_daemon_state,
        node_coordinator_state,
        node_domain_state,
        node_pvc_version,
        _node_static_data,
        _node_vcpu_allocated,
        _node_mem_total,
        _node_mem_allocated,
        _node_mem_provisioned,
        _node_mem_used,
        _node_mem_free,
        _node_load,
        _node_domains_count,
        _node_running_domains,
        _node_health,
        _node_health_plugins,
        _node_network_stats,
    ) = zkhandler.read_many(
        [
            ("node.state.daemon", node_name),
            ("node.state.router", node_name),
            ("node.state.domain", node_name),
            ("node.data.pvc_version", node_name),
            ("node.data.static", node_name),
            ("node.vcpu.allocated", node_name),
            ("node.memory.total", node_name),
            ("node.memory.allocated", node_name),
            ("node.memory.provisioned", node_name),
            ("node.memory.used", node_name),
            ("node.memory.free", node_name),
            ("node.cpu.load", node_name),
            ("node.count.provisioned_domains", node_name),
            ("node.running_domains", node_name),
            ("node.monitoring.health", node_name),
            ("node.monitoring.plugins", node_name),
            ("node.network.stats", node_name),
        ]
    )

    node_static_data = _node_static_data.split()
    node_cpu_count = int(node_static_data[0])
    node_kernel = node_static_data[1]
    node_os = node_static_data[2]
    node_arch = node_static_data[3]

    node_vcpu_allocated = int(_node_vcpu_allocated)
    node_mem_total = int(_node_mem_total)
    node_mem_allocated = int(_node_mem_allocated)
    node_mem_provisioned = int(_node_mem_provisioned)
    node_mem_used = int(_node_mem_used)
    node_mem_free = int(_node_mem_free)
    node_load = float(_node_load)
    node_domains_count = int(_node_domains_count)
    node_running_domains = _node_running_domains.split()

    try:
        node_health = int(_node_health)
    except Exception:
        node_health = "N/A"

    try:
        node_health_plugins = _node_health_plugins.split()
    except Exception:
        node_health_plugins = list()

    node_health_details = getNodeHealthDetails(
        zkhandler, node_name, node_health_plugins
    )

    try:
        node_network_stats = json.loads(_node_network_stats)
    except Exception:
        node_network_stats = dict()

    # Construct a data structure to represent the data
    node_information = {
        "name": node_name,
        "daemon_state": node_daemon_state,
        "coordinator_state": node_coordinator_state,
        "domain_state": node_domain_state,
        "pvc_version": node_pvc_version,
        "cpu_count": node_cpu_count,
        "kernel": node_kernel,
        "os": node_os,
        "arch": node_arch,
        "health": node_health,
        "health_plugins": node_health_plugins,
        "health_details": node_health_details,
        "load": node_load,
        "domains_count": node_domains_count,
        "running_domains": node_running_domains,
        "vcpu": {
            "total": node_cpu_count,
            "allocated": node_vcpu_allocated,
        },
        "memory": {
            "total": node_mem_total,
            "allocated": node_mem_allocated,
            "provisioned": node_mem_provisioned,
            "used": node_mem_used,
            "free": node_mem_free,
        },
        "interfaces": node_network_stats,
    }
    return node_information


#
# Direct Functions
#
def secondary_node(zkhandler, node):
    # Verify node is valid
    if not common.verifyNode(zkhandler, node):
        return False, "ERROR: No node named {} is present in the cluster.".format(node)

    # Ensure node is a coordinator
    daemon_mode = zkhandler.read(("node.mode", node))
    if daemon_mode == "hypervisor":
        return (
            False,
            "ERROR: Cannot change coordinator state on non-coordinator node {}".format(
                node
            ),
        )

    # Ensure node is in run daemonstate
    daemon_state = zkhandler.read(("node.state.daemon", node))
    if daemon_state != "run":
        return False, "ERROR: Node {} is not active".format(node)

    # Get current state
    current_state = zkhandler.read(("node.state.router", node))
    if current_state == "secondary":
        return True, "Node {} is already in secondary coordinator state.".format(node)

    retmsg = "Setting node {} in secondary coordinator state.".format(node)
    zkhandler.write([("base.config.primary_node", "none")])

    return True, retmsg


def primary_node(zkhandler, node):
    # Verify node is valid
    if not common.verifyNode(zkhandler, node):
        return False, "ERROR: No node named {} is present in the cluster.".format(node)

    # Ensure node is a coordinator
    daemon_mode = zkhandler.read(("node.mode", node))
    if daemon_mode == "hypervisor":
        return (
            False,
            "ERROR: Cannot change coordinator state on non-coordinator node {}".format(
                node
            ),
        )

    # Ensure node is in run daemonstate
    daemon_state = zkhandler.read(("node.state.daemon", node))
    if daemon_state != "run":
        return False, "ERROR: Node {} is not active".format(node)

    # Get current state
    current_state = zkhandler.read(("node.state.router", node))
    if current_state == "primary":
        return True, "Node {} is already in primary coordinator state.".format(node)

    retmsg = "Setting node {} in primary coordinator state.".format(node)
    zkhandler.write([("base.config.primary_node", node)])

    return True, retmsg


def flush_node(zkhandler, node, wait=False):
    # Verify node is valid
    if not common.verifyNode(zkhandler, node):
        return False, "ERROR: No node named {} is present in the cluster.".format(node)

    if zkhandler.read(("node.state.domain", node)) == "flushed":
        return True, "Node {} is already flushed.".format(node)

    retmsg = "Removing node {} from active service.".format(node)

    # Add the new domain to Zookeeper
    zkhandler.write([(("node.state.domain", node), "flush")])

    if wait:
        while zkhandler.read(("node.state.domain", node)) == "flush":
            time.sleep(1)
        retmsg = "Removed node {} from active service.".format(node)

    return True, retmsg


def ready_node(zkhandler, node, wait=False):
    # Verify node is valid
    if not common.verifyNode(zkhandler, node):
        return False, "ERROR: No node named {} is present in the cluster.".format(node)

    if zkhandler.read(("node.state.domain", node)) == "ready":
        return True, "Node {} is already ready.".format(node)

    retmsg = "Restoring node {} to active service.".format(node)

    # Add the new domain to Zookeeper
    zkhandler.write([(("node.state.domain", node), "unflush")])

    if wait:
        while zkhandler.read(("node.state.domain", node)) == "unflush":
            time.sleep(1)
        retmsg = "Restored node {} to active service.".format(node)

    return True, retmsg


def get_node_log(zkhandler, node, lines=2000):
    # Verify node is valid
    if not common.verifyNode(zkhandler, node):
        return False, "ERROR: No node named {} is present in the cluster.".format(node)

    # Get the data from ZK
    node_log = zkhandler.read(("logs.messages", node))

    if node_log is None:
        return True, ""

    # Shrink the log buffer to length lines
    shrunk_log = node_log.split("\n")[-lines:]
    loglines = "\n".join(shrunk_log)

    return True, loglines


def get_info(zkhandler, node):
    # Verify node is valid
    if not common.verifyNode(zkhandler, node):
        return False, "ERROR: No node named {} is present in the cluster.".format(node)

    # Get information about node in a pretty format
    node_information = getNodeInformation(zkhandler, node)
    if not node_information:
        return False, "ERROR: Could not get information about node {}.".format(node)

    return True, node_information


def get_list(
    zkhandler,
    limit=None,
    daemon_state=None,
    coordinator_state=None,
    domain_state=None,
    is_fuzzy=True,
):
    node_list = []
    full_node_list = zkhandler.children("base.node")
    if full_node_list is None:
        full_node_list = list()
    full_node_list.sort()

    if is_fuzzy and limit:
        # Implicitly assume fuzzy limits
        if not re.match(r"\^.*", limit):
            limit = ".*" + limit
        if not re.match(r".*\$", limit):
            limit = limit + ".*"

    for node in full_node_list:
        if limit:
            try:
                if re.fullmatch(limit, node):
                    node_list.append(getNodeInformation(zkhandler, node))
            except Exception as e:
                return False, "Regex Error: {}".format(e)
        else:
            node_list.append(getNodeInformation(zkhandler, node))

    if daemon_state or coordinator_state or domain_state:
        limited_node_list = []
        for node in node_list:
            add_node = False
            if daemon_state and node["daemon_state"] == daemon_state:
                add_node = True
            if coordinator_state and node["coordinator_state"] == coordinator_state:
                add_node = True
            if domain_state and node["domain_state"] == domain_state:
                add_node = True
            if add_node:
                limited_node_list.append(node)
        node_list = limited_node_list

    return True, node_list
