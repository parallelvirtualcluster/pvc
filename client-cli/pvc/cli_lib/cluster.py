#!/usr/bin/env python3

# cluster.py - PVC CLI client function library, cluster management
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

import json

import pvc.cli_lib.ansiprint as ansiprint
from pvc.cli_lib.common import call_api


def initialize(config, overwrite=False):
    """
    Initialize the PVC cluster

    API endpoint: GET /api/v1/initialize
    API arguments: overwrite, yes-i-really-mean-it
    API schema: {json_data_object}
    """
    params = {"yes-i-really-mean-it": "yes", "overwrite": overwrite}
    response = call_api(config, "post", "/initialize", params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def backup(config):
    """
    Get a JSON backup of the cluster

    API endpoint: GET /api/v1/backup
    API arguments:
    API schema: {json_data_object}
    """
    response = call_api(config, "get", "/backup")

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json().get("message", "")


def restore(config, cluster_data):
    """
    Restore a JSON backup to the cluster

    API endpoint: POST /api/v1/restore
    API arguments: yes-i-really-mean-it
    API schema: {json_data_object}
    """
    cluster_data_json = json.dumps(cluster_data)

    params = {"yes-i-really-mean-it": "yes"}
    data = {"cluster_data": cluster_data_json}
    response = call_api(config, "post", "/restore", params=params, data=data)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def maintenance_mode(config, state):
    """
    Enable or disable PVC cluster maintenance mode

    API endpoint: POST /api/v1/status
    API arguments: {state}={state}
    API schema: {json_data_object}
    """
    params = {"state": state}
    response = call_api(config, "post", "/status", params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def get_info(config):
    """
    Get status of the PVC cluster

    API endpoint: GET /api/v1/status
    API arguments:
    API schema: {json_data_object}
    """
    response = call_api(config, "get", "/status")

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json().get("message", "")


def format_info(cluster_information, oformat):
    if oformat == "json":
        return json.dumps(cluster_information)

    if oformat == "json-pretty":
        return json.dumps(cluster_information, indent=4)

    # Plain formatting, i.e. human-readable
    if cluster_information.get("maintenance") == "true":
        health_colour = ansiprint.blue()
    elif cluster_information.get("cluster_health", {}).get("health", 100) > 90:
        health_colour = ansiprint.green()
    elif cluster_information.get("cluster_health", {}).get("health", 100) > 50:
        health_colour = ansiprint.yellow()
    else:
        health_colour = ansiprint.red()

    ainformation = []

    ainformation.append(
        "{}PVC cluster status:{}".format(ansiprint.bold(), ansiprint.end())
    )
    ainformation.append("")

    health_text = (
        f"{cluster_information.get('cluster_health', {}).get('health', 'N/A')}"
    )
    if health_text != "N/A":
        health_text += "%"
    if cluster_information.get("maintenance") == "true":
        health_text += " (maintenance on)"

    ainformation.append(
        "{}Cluster health:{}  {}{}{}".format(
            ansiprint.purple(),
            ansiprint.end(),
            health_colour,
            health_text,
            ansiprint.end(),
        )
    )
    if cluster_information.get("cluster_health", {}).get("messages"):
        health_messages = "\n                 > ".join(
            sorted(cluster_information["cluster_health"]["messages"])
        )
        ainformation.append(
            "{}Health messages:{} > {}".format(
                ansiprint.purple(),
                ansiprint.end(),
                health_messages,
            )
        )
    else:
        ainformation.append(
            "{}Health messages:{} N/A".format(
                ansiprint.purple(),
                ansiprint.end(),
            )
        )

    if oformat == "short":
        return "\n".join(ainformation)

    ainformation.append("")
    ainformation.append(
        "{}Primary node:{}        {}".format(
            ansiprint.purple(), ansiprint.end(), cluster_information["primary_node"]
        )
    )
    ainformation.append(
        "{}PVC version:{}         {}".format(
            ansiprint.purple(),
            ansiprint.end(),
            cluster_information.get("pvc_version", "N/A"),
        )
    )
    ainformation.append(
        "{}Cluster upstream IP:{} {}".format(
            ansiprint.purple(), ansiprint.end(), cluster_information["upstream_ip"]
        )
    )
    ainformation.append("")
    ainformation.append(
        "{}Total nodes:{}     {}".format(
            ansiprint.purple(), ansiprint.end(), cluster_information["nodes"]["total"]
        )
    )
    ainformation.append(
        "{}Total VMs:{}       {}".format(
            ansiprint.purple(), ansiprint.end(), cluster_information["vms"]["total"]
        )
    )
    ainformation.append(
        "{}Total networks:{}  {}".format(
            ansiprint.purple(), ansiprint.end(), cluster_information["networks"]
        )
    )
    ainformation.append(
        "{}Total OSDs:{}      {}".format(
            ansiprint.purple(), ansiprint.end(), cluster_information["osds"]["total"]
        )
    )
    ainformation.append(
        "{}Total pools:{}     {}".format(
            ansiprint.purple(), ansiprint.end(), cluster_information["pools"]
        )
    )
    ainformation.append(
        "{}Total volumes:{}   {}".format(
            ansiprint.purple(), ansiprint.end(), cluster_information["volumes"]
        )
    )
    ainformation.append(
        "{}Total snapshots:{} {}".format(
            ansiprint.purple(), ansiprint.end(), cluster_information["snapshots"]
        )
    )

    nodes_string = "{}Nodes:{} {}/{} {}ready,run{}".format(
        ansiprint.purple(),
        ansiprint.end(),
        cluster_information["nodes"].get("run,ready", 0),
        cluster_information["nodes"].get("total", 0),
        ansiprint.green(),
        ansiprint.end(),
    )
    for state, count in cluster_information["nodes"].items():
        if state == "total" or state == "run,ready":
            continue

        nodes_string += " {}/{} {}{}{}".format(
            count,
            cluster_information["nodes"]["total"],
            ansiprint.yellow(),
            state,
            ansiprint.end(),
        )

    ainformation.append("")
    ainformation.append(nodes_string)

    vms_string = "{}VMs:{} {}/{} {}start{}".format(
        ansiprint.purple(),
        ansiprint.end(),
        cluster_information["vms"].get("start", 0),
        cluster_information["vms"].get("total", 0),
        ansiprint.green(),
        ansiprint.end(),
    )
    for state, count in cluster_information["vms"].items():
        if state == "total" or state == "start":
            continue

        if state in ["disable", "migrate", "unmigrate", "provision"]:
            colour = ansiprint.blue()
        else:
            colour = ansiprint.yellow()

        vms_string += " {}/{} {}{}{}".format(
            count, cluster_information["vms"]["total"], colour, state, ansiprint.end()
        )

    ainformation.append("")
    ainformation.append(vms_string)

    if cluster_information["osds"]["total"] > 0:
        osds_string = "{}Ceph OSDs:{} {}/{} {}up,in{}".format(
            ansiprint.purple(),
            ansiprint.end(),
            cluster_information["osds"].get("up,in", 0),
            cluster_information["osds"].get("total", 0),
            ansiprint.green(),
            ansiprint.end(),
        )
        for state, count in cluster_information["osds"].items():
            if state == "total" or state == "up,in":
                continue

            osds_string += " {}/{} {}{}{}".format(
                count,
                cluster_information["osds"]["total"],
                ansiprint.yellow(),
                state,
                ansiprint.end(),
            )

        ainformation.append("")
        ainformation.append(osds_string)

    ainformation.append("")
    return "\n".join(ainformation)
