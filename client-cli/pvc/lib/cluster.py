#!/usr/bin/env python3

# cluster.py - PVC CLI client function library, cluster management
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

import json

from time import sleep

from pvc.lib.common import call_api


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


def get_primary_node(config):
    """
    Get the current primary node of the PVC cluster

    API endpoint: GET /api/v1/status/primary_node
    API arguments:
    API schema: {json_data_object}
    """
    while True:
        response = call_api(config, "get", "/status/primary_node")
        resp_code = response.status_code
        if resp_code == 200:
            break
        else:
            sleep(1)

    return True, response.json()["primary_node"]
