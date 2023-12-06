#!/usr/bin/env python3

# faults.py - PVC CLI client function library, faults management
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

from pvc.lib.common import call_api


def get_list(config, limit=None, sort_key="last_reported"):
    """
    Get list of PVC faults

    API endpoint: GET /api/v1/faults
    API arguments: sort_key={sort_key}
    API schema: {json_data_object}
    """
    if limit is not None:
        params = {}
        endpoint = f"/faults/{limit}"
    else:
        params = {"sort_key": sort_key}
        endpoint = "/faults"

    response = call_api(config, "get", endpoint, params=params)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json().get("message", "")


def acknowledge(config, fault_id):
    """
    Acknowledge a PVC fault

    API endpoint: PUT /api/v1/faults/<fault_id>
    API arguments:
    API schema: {json_message}
    """
    response = call_api(config, "put", f"/faults/{fault_id}")

    if response.status_code == 200:
        return True, response.json().get("message", "")
    else:
        return False, response.json().get("message", "")


def acknowledge_all(config):
    """
    Acknowledge all PVC faults

    API endpoint: PUT /api/v1/faults
    API arguments:
    API schema: {json_message}
    """
    response = call_api(config, "put", "/faults")

    if response.status_code == 200:
        return True, response.json().get("message", "")
    else:
        return False, response.json().get("message", "")


def delete(config, fault_id):
    """
    Delete a PVC fault

    API endpoint: DELETE /api/v1/faults/<fault_id>
    API arguments:
    API schema: {json_message}
    """
    response = call_api(config, "delete", f"/faults/{fault_id}")

    if response.status_code == 200:
        return True, response.json().get("message", "")
    else:
        return False, response.json().get("message", "")


def delete_all(config):
    """
    Delete all PVC faults

    API endpoint: DELETE /api/v1/faults
    API arguments:
    API schema: {json_message}
    """
    response = call_api(config, "delete", "/faults")

    if response.status_code == 200:
        return True, response.json().get("message", "")
    else:
        return False, response.json().get("message", "")
