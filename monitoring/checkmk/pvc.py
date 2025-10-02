#!/usr/bin/env python3
#
# Check_MK PVC plugin
#
# Copyright 2017-2021, Joshua Boniface <joshua@boniface.me>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from cmk.agent_based.v2 import *
from time import time
from json import loads


def parse_pvc(string_table):
    hostname = string_table[0][0]
    data = loads(" ".join(string_table[1]))
    parsed = (hostname, data)
    return parsed


def discover_pvc(section):
    my_node, _ = section
    yield Service(item=f"PVC Node {my_node}")
    yield Service(item="PVC Cluster")


def check_pvc(item, params, section):
    my_node, data = section
    state = State.OK
    summary = ""
    details = None

    maintenance_map = {
        "true": "on",
        "false": "off",
    }
    maintenance = maintenance_map[data["maintenance"]]

    # Node check
    if item == f"PVC Node {my_node}":
        node_health = data["node_health"][my_node]["health"]
        node_messages = data["node_health"][my_node]["messages"]

        summary = f"Node health is {node_health}% (maintenance {maintenance})"

        if len(node_messages) > 0:
            details = ", ".join(node_messages)

        if node_health <= 50 and maintenance == "off":
            state = State.CRIT
        elif node_health <= 90 and maintenance == "off":
            state = State.WARN
        else:
            state = State.OK

        yield Metric(name="node-health", value=node_health)

    # Cluster check
    elif item == "PVC Cluster":
        cluster_health = data["cluster_health"]["health"]
        cluster_messages = data["cluster_health"]["messages"]

        summary = f"Cluster health is {cluster_health}% (maintenance {maintenance})"

        if len(cluster_messages) > 0:
            details = ", ".join([m["text"] for m in cluster_messages])

        if cluster_health <= 50 and maintenance == "off":
            state = State.CRIT
        elif cluster_health <= 90 and maintenance == "off":
            state = State.WARN
        else:
            state = State.OK

        yield Metric(name="cluster-health", value=cluster_health)

    yield Result(state=state, summary=summary, details=details)
    return


agent_section_pvc = AgentSection(
    name="pvc",
    parse_function=parse_pvc,
)

check_plugin_pvc = CheckPlugin(
    name="pvc",
    service_name="%s",
    check_ruleset_name="pvc",
    discovery_function=discover_pvc,
    check_function=check_pvc,
    check_default_parameters={},
)
