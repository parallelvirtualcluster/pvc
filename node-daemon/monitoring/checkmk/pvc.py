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

from .agent_based_api.v1 import *
from cmk.base.check_api import host_name
from time import time
from json import loads


def discover_pvc(section):
    my_node = host_name().split(".")[0]
    yield Service(item=f"PVC Node {my_node}")
    yield Service(item="PVC Cluster")


def check_pvc(item, params, section):
    state = State.OK
    summary = "Stuff"
    details = None
    data = loads(" ".join(section[0]))
    my_node = host_name().split(".")[0]

    maintenance_map = {
        "true": "on",
        "false": "off",
    }
    maintenance = maintenance_map[data["maintenance"]]

    # Node check
    if item == f"PVC Node {my_node}":
        my_node = host_name().split(".")[0]
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
            details = ", ".join(cluster_messages)

        if cluster_health <= 50 and maintenance == "off":
            state = State.CRIT
        elif cluster_health <= 90 and maintenance == "off":
            state = State.WARN
        else:
            state = State.OK

        yield Metric(name="cluster-health", value=cluster_health)

    yield Result(state=state, summary=summary, details=details)
    return


register.check_plugin(
    name="pvc",
    service_name="%s",
    check_ruleset_name="pvc",
    discovery_function=discover_pvc,
    check_function=check_pvc,
    check_default_parameters={},
)
