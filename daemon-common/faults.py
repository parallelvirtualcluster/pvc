#!/usr/bin/env python3

# faults.py - PVC client function library, faults management
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

from datetime import datetime


def getFault(zkhandler, fault_id):
    """
    Get the details of a fault based on the fault ID
    """
    if not zkhandler.exists(("faults.id", fault_id)):
        return None

    fault_id = fault_id
    fault_last_time = zkhandler.read(("faults.last_time", fault_id))
    fault_first_time = zkhandler.read(("faults.first_time", fault_id))
    fault_ack_time = zkhandler.read(("faults.ack_time", fault_id))
    fault_status = zkhandler.read(("faults.status", fault_id))
    fault_delta = int(zkhandler.read(("faults.delta", fault_id)))
    fault_message = zkhandler.read(("faults.message", fault_id))

    # Acknowledged faults have a delta of 0
    if fault_ack_time != "":
        fault_delta = 0

    fault = {
        "id": fault_id,
        "last_reported": fault_last_time,
        "first_reported": fault_first_time,
        "acknowledged_at": fault_ack_time,
        "status": fault_status,
        "health_delta": fault_delta,
        "message": fault_message,
    }

    return fault


def getAllFaults(zkhandler, sort_key="last_reported"):
    """
    Get the details of all registered faults
    """

    all_faults = zkhandler.children(("base.faults"))

    faults_detail = list()

    for fault_id in all_faults:
        fault_detail = getFault(zkhandler, fault_id)
        faults_detail.append(fault_detail)

    sorted_faults = sorted(faults_detail, key=lambda x: x[sort_key])
    # Sort newest-first for time-based sorts
    if sort_key in ["first_reported", "last_reported", "acknowledge_at"]:
        sorted_faults.reverse()

    return sorted_faults


def get_list(zkhandler, limit=None, sort_key="last_reported"):
    """
    Get a list of all known faults, sorted by {sort_key}
    """
    if sort_key not in [
        "first_reported",
        "last_reported",
        "acknowledged_at",
        "status",
        "health_delta",
        "message",
    ]:
        return False, f"Invalid sort key {sort_key} provided"

    all_faults = getAllFaults(zkhandler, sort_key=sort_key)

    if limit is not None:
        all_faults = [fault for fault in all_faults if fault["id"] == limit]

    return True, all_faults


def acknowledge(zkhandler, fault_id):
    """
    Acknowledge a fault
    """
    fault = getFault(zkhandler, fault_id)

    if fault is None:
        return False, f"No fault with ID {fault_id} found"

    zkhandler.write(
        [
            (("faults.ack_time", fault_id), datetime.now()),
            (("faults.status", fault_id), "ack"),
        ]
    )

    return True, f"Successfully acknowledged fault {fault_id}"


def delete(zkhandler, fault_id):
    """
    Delete a fault
    """
    fault = getFault(zkhandler, fault_id)

    if fault is None:
        return False, f"No fault with ID {fault_id} found"

    zkhandler.delete(("faults.id", fault_id), recursive=True)

    return True, f"Successfully deleted fault {fault_id}"
