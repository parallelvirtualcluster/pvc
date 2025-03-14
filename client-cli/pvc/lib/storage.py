#!/usr/bin/env python3

# ceph.py - PVC CLI client function library, Ceph cluster functions
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

import math

from os import path
from json import loads

import pvc.lib.ansiprint as ansiprint
from pvc.lib.common import UploadProgressBar, call_api, get_wait_retdata
from pvc.cli.helpers import MAX_CONTENT_WIDTH

#
# Supplemental functions
#

# Matrix of human-to-byte values
byte_unit_matrix = {
    "B": 1,
    "K": 1024,
    "M": 1024 * 1024,
    "G": 1024 * 1024 * 1024,
    "T": 1024 * 1024 * 1024 * 1024,
    "P": 1024 * 1024 * 1024 * 1024 * 1024,
}

# Matrix of human-to-metric values
ops_unit_matrix = {
    "": 1,
    "K": 1000,
    "M": 1000 * 1000,
    "G": 1000 * 1000 * 1000,
    "T": 1000 * 1000 * 1000 * 1000,
    "P": 1000 * 1000 * 1000 * 1000 * 1000,
}


# Format byte sizes to/from human-readable units
def format_bytes_tohuman(databytes):
    datahuman = ""
    for unit in sorted(byte_unit_matrix, key=byte_unit_matrix.get, reverse=True):
        new_bytes = int(math.ceil(databytes / byte_unit_matrix[unit]))
        # Round up if 5 or more digits
        if new_bytes > 9999:
            # We can jump down another level
            continue
        else:
            # We're at the end, display with this size
            datahuman = "{}{}".format(new_bytes, unit)

    return datahuman


def format_bytes_fromhuman(datahuman):
    # Trim off human-readable character
    dataunit = datahuman[-1]
    datasize = int(datahuman[:-1])
    databytes = datasize * byte_unit_matrix[dataunit]
    return "{}B".format(databytes)


# Format ops sizes to/from human-readable units
def format_ops_tohuman(dataops):
    datahuman = ""
    for unit in sorted(ops_unit_matrix, key=ops_unit_matrix.get, reverse=True):
        new_ops = int(math.ceil(dataops / ops_unit_matrix[unit]))
        # Round up if 6 or more digits
        if new_ops > 99999:
            # We can jump down another level
            continue
        else:
            # We're at the end, display with this size
            datahuman = "{}{}".format(new_ops, unit)

    return datahuman


def format_ops_fromhuman(datahuman):
    # Trim off human-readable character
    dataunit = datahuman[-1]
    datasize = int(datahuman[:-1])
    dataops = datasize * ops_unit_matrix[dataunit]
    return "{}".format(dataops)


def format_pct_tohuman(datapct):
    datahuman = "{0:.1f}".format(float(datapct * 100.0))
    return datahuman


#
# Status functions
#
def ceph_status(config):
    """
    Get status of the Ceph cluster

    API endpoint: GET /api/v1/storage/ceph/status
    API arguments:
    API schema: {json_data_object}
    """
    response = call_api(config, "get", "/storage/ceph/status")

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json().get("message", "")


def ceph_util(config):
    """
    Get utilization of the Ceph cluster

    API endpoint: GET /api/v1/storage/ceph/utilization
    API arguments:
    API schema: {json_data_object}
    """
    response = call_api(config, "get", "/storage/ceph/utilization")

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json().get("message", "")


def format_raw_output(config, status_data):
    ainformation = list()
    ainformation.append(
        "{bold}Ceph cluster {stype} (primary node {end}{blue}{primary}{end}{bold}){end}\n".format(
            bold=ansiprint.bold(),
            end=ansiprint.end(),
            blue=ansiprint.blue(),
            stype=status_data["type"],
            primary=status_data["primary_node"],
        )
    )
    ainformation.append(status_data["ceph_data"])
    ainformation.append("")

    return "\n".join(ainformation)


#
# OSD DB VG functions
#
def ceph_osd_db_vg_add(config, node, device, wait_flag):
    """
    Add new Ceph OSD database volume group

    API endpoint: POST /api/v1/storage/ceph/osddb
    API arguments: node={node}, device={device}
    API schema: {"message":"{data}"}
    """
    params = {"node": node, "device": device}
    response = call_api(config, "post", "/storage/ceph/osddb", params=params)

    return get_wait_retdata(response, wait_flag)


#
# OSD functions
#
def ceph_osd_info(config, osd):
    """
    Get information about Ceph OSD

    API endpoint: GET /api/v1/storage/ceph/osd/{osd}
    API arguments:
    API schema: {json_data_object}
    """
    response = call_api(config, "get", "/storage/ceph/osd/{osd}".format(osd=osd))

    if response.status_code == 200:
        if isinstance(response.json(), list) and len(response.json()) != 1:
            # No exact match; return not found
            return False, "OSD not found."
        else:
            # Return a single instance if the response is a list
            if isinstance(response.json(), list):
                return True, response.json()[0]
            # This shouldn't happen, but is here just in case
            else:
                return True, response.json()
    else:
        return False, response.json().get("message", "")


def ceph_osd_list(config, limit):
    """
    Get list information about Ceph OSDs (limited by {limit})

    API endpoint: GET /api/v1/storage/ceph/osd
    API arguments: limit={limit}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    if limit:
        params["limit"] = limit

    response = call_api(config, "get", "/storage/ceph/osd", params=params)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json().get("message", "")


def ceph_osd_add(
    config, node, device, weight, ext_db_ratio, ext_db_size, osd_count, wait_flag
):
    """
    Add new Ceph OSD

    API endpoint: POST /api/v1/storage/ceph/osd
    API arguments: node={node}, device={device}, weight={weight}, [ext_db_ratio={ext_db_ratio}, ext_db_size={ext_db_size}, osd_count={osd_count}]
    API schema: {"message":"{data}"}
    """
    params = {
        "node": node,
        "device": device,
        "weight": weight,
    }

    if ext_db_ratio is not None:
        params["ext_db_ratio"] = ext_db_ratio
    if ext_db_size is not None:
        params["ext_db_size"] = ext_db_size
    if osd_count is not None:
        params["osd_count"] = osd_count

    response = call_api(config, "post", "/storage/ceph/osd", params=params)

    return get_wait_retdata(response, wait_flag)


def ceph_osd_replace(
    config, osdid, new_device, old_device, weight, ext_db_ratio, ext_db_size, wait_flag
):
    """
    Replace an existing Ceph OSD with a new device

    API endpoint: POST /api/v1/storage/ceph/osd/{osdid}
    API arguments: new_device, [old_device={old_device}, weight={weight}, ext_db_ratio={ext_db_ratio}, ext_db_size={ext_db_size}]
    API schema: {"message":"{data}"}
    """
    params = {
        "new_device": new_device,
        "yes-i-really-mean-it": "yes",
    }

    if old_device is not None:
        params["old_device"] = old_device
    if weight is not None:
        params["weight"] = weight
    if ext_db_ratio is not None:
        params["ext_db_ratio"] = ext_db_ratio
    if ext_db_size is not None:
        params["ext_db_size"] = ext_db_size

    response = call_api(config, "post", f"/storage/ceph/osd/{osdid}", params=params)

    return get_wait_retdata(response, wait_flag)


def ceph_osd_refresh(config, osdid, device, wait_flag):
    """
    Refresh (reimport) an existing Ceph OSD with device {device}

    API endpoint: PUT /api/v1/storage/ceph/osd/{osdid}
    API arguments: device={device}
    API schema: {"message":"{data}"}
    """
    params = {
        "device": device,
    }
    response = call_api(config, "put", f"/storage/ceph/osd/{osdid}", params=params)

    return get_wait_retdata(response, wait_flag)


def ceph_osd_remove(config, osdid, force_flag, wait_flag):
    """
    Remove Ceph OSD

    API endpoint: DELETE /api/v1/storage/ceph/osd/{osdid}
    API arguments:
    API schema: {"message":"{data}"}
    """
    params = {"force": force_flag, "yes-i-really-mean-it": "yes"}
    response = call_api(
        config, "delete", "/storage/ceph/osd/{osdid}".format(osdid=osdid), params=params
    )

    return get_wait_retdata(response, wait_flag)


def ceph_osd_state(config, osdid, state):
    """
    Set state of Ceph OSD

    API endpoint: POST /api/v1/storage/ceph/osd/{osdid}/state
    API arguments: state={state}
    API schema: {"message":"{data}"}
    """
    params = {"state": state}
    response = call_api(
        config,
        "post",
        "/storage/ceph/osd/{osdid}/state".format(osdid=osdid),
        params=params,
    )

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def ceph_osd_option(config, option, action):
    """
    Set cluster option of Ceph OSDs

    API endpoint: POST /api/v1/storage/ceph/option
    API arguments: option={option}, action={action}
    API schema: {"message":"{data}"}
    """
    params = {"option": option, "action": action}
    response = call_api(config, "post", "/storage/ceph/option", params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def getOutputColoursOSD(osd_information):
    # Set the UP status
    if osd_information["stats"]["up"] == 1:
        osd_up_flag = "Yes"
        osd_up_colour = ansiprint.green()
    else:
        osd_up_flag = "No"
        osd_up_colour = ansiprint.red()

    # Set the IN status
    if osd_information["stats"]["in"] == 1:
        osd_in_flag = "Yes"
        osd_in_colour = ansiprint.green()
    else:
        osd_in_flag = "No"
        osd_in_colour = ansiprint.red()

    return osd_up_flag, osd_up_colour, osd_in_flag, osd_in_colour


def format_list_osd(config, osd_list):
    # Handle empty list
    if not osd_list:
        osd_list = list()

    osd_list_output = []

    osd_id_length = 3
    osd_node_length = 5
    osd_device_length = 6
    osd_db_device_length = 9
    osd_up_length = 4
    osd_in_length = 4
    osd_size_length = 5
    osd_weight_length = 3
    osd_reweight_length = 5
    osd_pgs_length = 4
    osd_used_length = 5
    osd_free_length = 6
    osd_util_length = 6
    osd_wrops_length = 4
    osd_wrdata_length = 5
    osd_rdops_length = 4
    osd_rddata_length = 5

    for osd_information in osd_list:
        try:
            # If this happens, the node hasn't checked in fully yet, so use some dummy data
            if osd_information["stats"]["node"] == "|":
                for key in osd_information["stats"].keys():
                    if (
                        osd_information["stats"][key] == "|"
                        or osd_information["stats"][key] is None
                    ):
                        osd_information["stats"][key] = "N/A"
                for key in osd_information.keys():
                    if osd_information[key] is None:
                        osd_information[key] = "N/A"
            else:
                for key in osd_information["stats"].keys():
                    if key in ["utilization", "var"] and isinstance(
                        osd_information["stats"][key], float
                    ):
                        osd_information["stats"][key] = round(
                            osd_information["stats"][key], 2
                        )
        except KeyError:
            print(
                f"Details for OSD {osd_information['id']} missing required keys, skipping."
            )
            continue

        if osd_information.get("is_split") is not None and osd_information.get(
            "is_split"
        ):
            osd_information["device"] = f"{osd_information['device']} [s]"

        # Deal with the size to human readable
        if isinstance(osd_information["stats"]["kb"], int):
            osd_information["stats"]["size"] = osd_information["stats"]["kb"] * 1024
        else:
            osd_information["stats"]["size"] = "N/A"
        for datatype in "size", "wr_data", "rd_data":
            databytes = osd_information["stats"][datatype]
            if isinstance(databytes, int):
                databytes_formatted = format_bytes_tohuman(databytes)
            else:
                databytes_formatted = databytes
            osd_information["stats"][datatype] = databytes_formatted
        for datatype in "wr_ops", "rd_ops":
            dataops = osd_information["stats"][datatype]
            if isinstance(dataops, int):
                dataops_formatted = format_ops_tohuman(dataops)
            else:
                dataops_formatted = dataops
            osd_information["stats"][datatype] = dataops_formatted

        # Set the OSD ID length
        _osd_id_length = len(osd_information["id"]) + 1
        if _osd_id_length > osd_id_length:
            osd_id_length = _osd_id_length

        # Set the OSD node length
        _osd_node_length = len(osd_information["node"]) + 1
        if _osd_node_length > osd_node_length:
            osd_node_length = _osd_node_length

        # Set the OSD device length
        _osd_device_length = len(osd_information["device"]) + 1
        if _osd_device_length > osd_device_length:
            osd_device_length = _osd_device_length

        # Set the OSD db_device length
        _osd_db_device_length = len(osd_information["db_device"]) + 1
        if _osd_db_device_length > osd_db_device_length:
            osd_db_device_length = _osd_db_device_length

        # Set the size and length
        _osd_size_length = len(str(osd_information["stats"]["size"])) + 1
        if _osd_size_length > osd_size_length:
            osd_size_length = _osd_size_length

        # Set the weight and length
        _osd_weight_length = len(str(osd_information["stats"]["weight"])) + 1
        if _osd_weight_length > osd_weight_length:
            osd_weight_length = _osd_weight_length

        # Set the reweight and length
        _osd_reweight_length = len(str(osd_information["stats"]["reweight"])) + 1
        if _osd_reweight_length > osd_reweight_length:
            osd_reweight_length = _osd_reweight_length

        # Set the pgs and length
        _osd_pgs_length = len(str(osd_information["stats"]["pgs"])) + 1
        if _osd_pgs_length > osd_pgs_length:
            osd_pgs_length = _osd_pgs_length

        # Set the used/available/utlization%/variance and lengths
        _osd_used_length = len(osd_information["stats"]["used"]) + 1
        if _osd_used_length > osd_used_length:
            osd_used_length = _osd_used_length

        _osd_free_length = len(osd_information["stats"]["avail"]) + 1
        if _osd_free_length > osd_free_length:
            osd_free_length = _osd_free_length

        _osd_util_length = len(str(osd_information["stats"]["utilization"])) + 1
        if _osd_util_length > osd_util_length:
            osd_util_length = _osd_util_length

        # Set the read/write IOPS/data and length
        _osd_wrops_length = len(osd_information["stats"]["wr_ops"]) + 1
        if _osd_wrops_length > osd_wrops_length:
            osd_wrops_length = _osd_wrops_length

        _osd_wrdata_length = len(osd_information["stats"]["wr_data"]) + 1
        if _osd_wrdata_length > osd_wrdata_length:
            osd_wrdata_length = _osd_wrdata_length

        _osd_rdops_length = len(osd_information["stats"]["rd_ops"]) + 1
        if _osd_rdops_length > osd_rdops_length:
            osd_rdops_length = _osd_rdops_length

        _osd_rddata_length = len(osd_information["stats"]["rd_data"]) + 1
        if _osd_rddata_length > osd_rddata_length:
            osd_rddata_length = _osd_rddata_length

    # Format the output header
    osd_list_output.append(
        "{bold}{osd_header: <{osd_header_length}} {state_header: <{state_header_length}} {details_header: <{details_header_length}} {read_header: <{read_header_length}} {write_header: <{write_header_length}}{end_bold}".format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            osd_header_length=osd_id_length
            + osd_node_length
            + osd_device_length
            + osd_db_device_length
            + 3,
            state_header_length=osd_up_length + osd_in_length + 1,
            details_header_length=osd_size_length
            + osd_pgs_length
            + osd_weight_length
            + osd_reweight_length
            + osd_used_length
            + osd_free_length
            + osd_util_length
            + 6,
            read_header_length=osd_rdops_length + osd_rddata_length + 1,
            write_header_length=osd_wrops_length + osd_wrdata_length + 1,
            osd_header="OSDs "
            + "".join(
                [
                    "-"
                    for _ in range(
                        5,
                        osd_id_length
                        + osd_node_length
                        + osd_device_length
                        + osd_db_device_length
                        + 2,
                    )
                ]
            ),
            state_header="State "
            + "".join(["-" for _ in range(6, osd_up_length + osd_in_length)]),
            details_header="Details "
            + "".join(
                [
                    "-"
                    for _ in range(
                        8,
                        osd_size_length
                        + osd_pgs_length
                        + osd_weight_length
                        + osd_reweight_length
                        + osd_used_length
                        + osd_free_length
                        + osd_util_length
                        + 5,
                    )
                ]
            ),
            read_header="Read "
            + "".join(["-" for _ in range(5, osd_rdops_length + osd_rddata_length)]),
            write_header="Write "
            + "".join(["-" for _ in range(6, osd_wrops_length + osd_wrdata_length)]),
        )
    )

    osd_list_output.append(
        "{bold}\
{osd_id: <{osd_id_length}} \
{osd_node: <{osd_node_length}} \
{osd_device: <{osd_device_length}} \
{osd_db_device: <{osd_db_device_length}} \
{osd_up: <{osd_up_length}} \
{osd_in: <{osd_in_length}} \
{osd_size: <{osd_size_length}} \
{osd_pgs: <{osd_pgs_length}} \
{osd_weight: <{osd_weight_length}} \
{osd_reweight: <{osd_reweight_length}} \
{osd_used: <{osd_used_length}} \
{osd_free: <{osd_free_length}} \
{osd_util: <{osd_util_length}} \
{osd_rdops: <{osd_rdops_length}} \
{osd_rddata: <{osd_rddata_length}} \
{osd_wrops: <{osd_wrops_length}} \
{osd_wrdata: <{osd_wrdata_length}} \
{end_bold}".format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            osd_id_length=osd_id_length,
            osd_node_length=osd_node_length,
            osd_device_length=osd_device_length,
            osd_db_device_length=osd_db_device_length,
            osd_up_length=osd_up_length,
            osd_in_length=osd_in_length,
            osd_size_length=osd_size_length,
            osd_pgs_length=osd_pgs_length,
            osd_weight_length=osd_weight_length,
            osd_reweight_length=osd_reweight_length,
            osd_used_length=osd_used_length,
            osd_free_length=osd_free_length,
            osd_util_length=osd_util_length,
            osd_wrops_length=osd_wrops_length,
            osd_wrdata_length=osd_wrdata_length,
            osd_rdops_length=osd_rdops_length,
            osd_rddata_length=osd_rddata_length,
            osd_id="ID",
            osd_node="Node",
            osd_device="Block",
            osd_db_device="DB Block",
            osd_up="Up",
            osd_in="In",
            osd_size="Size",
            osd_pgs="PGs",
            osd_weight="Wt",
            osd_reweight="ReWt",
            osd_used="Used",
            osd_free="Free",
            osd_util="Util%",
            osd_wrops="OPS",
            osd_wrdata="Data",
            osd_rdops="OPS",
            osd_rddata="Data",
        )
    )

    for osd_information in sorted(osd_list, key=lambda x: int(x["id"])):
        osd_up_flag, osd_up_colour, osd_in_flag, osd_in_colour = getOutputColoursOSD(
            osd_information
        )

        osd_db_device = osd_information["db_device"]
        if not osd_db_device:
            osd_db_device = "N/A"

        # Format the output header
        osd_list_output.append(
            "{bold}\
{osd_id: <{osd_id_length}} \
{osd_node: <{osd_node_length}} \
{osd_device: <{osd_device_length}} \
{osd_db_device: <{osd_db_device_length}} \
{osd_up_colour}{osd_up: <{osd_up_length}}{end_colour} \
{osd_in_colour}{osd_in: <{osd_in_length}}{end_colour} \
{osd_size: <{osd_size_length}} \
{osd_pgs: <{osd_pgs_length}} \
{osd_weight: <{osd_weight_length}} \
{osd_reweight: <{osd_reweight_length}} \
{osd_used: <{osd_used_length}} \
{osd_free: <{osd_free_length}} \
{osd_util: <{osd_util_length}} \
{osd_rdops: <{osd_rdops_length}} \
{osd_rddata: <{osd_rddata_length}} \
{osd_wrops: <{osd_wrops_length}} \
{osd_wrdata: <{osd_wrdata_length}} \
{end_bold}".format(
                bold="",
                end_bold="",
                end_colour=ansiprint.end(),
                osd_id_length=osd_id_length,
                osd_node_length=osd_node_length,
                osd_device_length=osd_device_length,
                osd_db_device_length=osd_db_device_length,
                osd_up_length=osd_up_length,
                osd_in_length=osd_in_length,
                osd_size_length=osd_size_length,
                osd_pgs_length=osd_pgs_length,
                osd_weight_length=osd_weight_length,
                osd_reweight_length=osd_reweight_length,
                osd_used_length=osd_used_length,
                osd_free_length=osd_free_length,
                osd_util_length=osd_util_length,
                osd_wrops_length=osd_wrops_length,
                osd_wrdata_length=osd_wrdata_length,
                osd_rdops_length=osd_rdops_length,
                osd_rddata_length=osd_rddata_length,
                osd_id=osd_information["id"],
                osd_node=osd_information["node"],
                osd_device=osd_information["device"],
                osd_db_device=osd_db_device,
                osd_up_colour=osd_up_colour,
                osd_up=osd_up_flag,
                osd_in_colour=osd_in_colour,
                osd_in=osd_in_flag,
                osd_size=osd_information["stats"]["size"],
                osd_pgs=osd_information["stats"]["pgs"],
                osd_weight=osd_information["stats"]["weight"],
                osd_reweight=osd_information["stats"]["reweight"],
                osd_used=osd_information["stats"]["used"],
                osd_free=osd_information["stats"]["avail"],
                osd_util=osd_information["stats"]["utilization"],
                osd_wrops=osd_information["stats"]["wr_ops"],
                osd_wrdata=osd_information["stats"]["wr_data"],
                osd_rdops=osd_information["stats"]["rd_ops"],
                osd_rddata=osd_information["stats"]["rd_data"],
            )
        )

    return "\n".join(osd_list_output)


#
# Pool functions
#
def ceph_pool_info(config, pool):
    """
    Get information about Ceph OSD

    API endpoint: GET /api/v1/storage/ceph/pool/{pool}
    API arguments:
    API schema: {json_data_object}
    """
    response = call_api(config, "get", "/storage/ceph/pool/{pool}".format(pool=pool))

    if response.status_code == 200:
        if isinstance(response.json(), list) and len(response.json()) != 1:
            # No exact match; return not found
            return False, "Pool not found."
        else:
            # Return a single instance if the response is a list
            if isinstance(response.json(), list):
                return True, response.json()[0]
            # This shouldn't happen, but is here just in case
            else:
                return True, response.json()
    else:
        return False, response.json().get("message", "")


def ceph_pool_list(config, limit):
    """
    Get list information about Ceph pools (limited by {limit})

    API endpoint: GET /api/v1/storage/ceph/pool
    API arguments: limit={limit}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    if limit:
        params["limit"] = limit

    response = call_api(config, "get", "/storage/ceph/pool", params=params)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json().get("message", "")


def ceph_pool_add(config, pool, pgs, replcfg, tier):
    """
    Add new Ceph pool

    API endpoint: POST /api/v1/storage/ceph/pool
    API arguments: pool={pool}, pgs={pgs}, replcfg={replcfg}, tier={tier}
    API schema: {"message":"{data}"}
    """
    params = {"pool": pool, "pgs": pgs, "replcfg": replcfg, "tier": tier}
    response = call_api(config, "post", "/storage/ceph/pool", params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def ceph_pool_remove(config, pool):
    """
    Remove Ceph pool

    API endpoint: DELETE /api/v1/storage/ceph/pool/{pool}
    API arguments:
    API schema: {"message":"{data}"}
    """
    params = {"yes-i-really-mean-it": "yes"}
    response = call_api(
        config, "delete", "/storage/ceph/pool/{pool}".format(pool=pool), params=params
    )

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def ceph_pool_set_pgs(config, pool, pgs):
    """
    Set the PGs of a Ceph pool

    API endpoint: PUT /api/v1/storage/ceph/pool/{pool}
    API arguments: {"pgs": "{pgs}"}
    API schema: {"message":"{data}"}
    """
    params = {"pgs": pgs}
    response = call_api(
        config, "put", "/storage/ceph/pool/{pool}".format(pool=pool), params=params
    )

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def format_list_pool(config, pool_list):
    # Handle empty list
    if not pool_list:
        pool_list = list()

    pool_list_output = []

    pool_name_length = 5
    pool_id_length = 3
    pool_tier_length = 5
    pool_pgs_length = 4
    pool_used_length = 5
    pool_usedpct_length = 6
    pool_free_length = 5
    pool_num_objects_length = 6
    pool_num_clones_length = 7
    pool_num_copies_length = 7
    pool_num_degraded_length = 9
    pool_read_ops_length = 4
    pool_read_data_length = 5
    pool_write_ops_length = 4
    pool_write_data_length = 5

    for pool_information in pool_list:
        # Deal with the size to human readable
        for datatype in ["free_bytes", "used_bytes", "write_bytes", "read_bytes"]:
            databytes = pool_information["stats"][datatype]
            databytes_formatted = format_bytes_tohuman(int(databytes))
            pool_information["stats"][datatype] = databytes_formatted
        for datatype in ["write_ops", "read_ops"]:
            dataops = pool_information["stats"][datatype]
            dataops_formatted = format_ops_tohuman(int(dataops))
            pool_information["stats"][datatype] = dataops_formatted
        for datatype in ["used_percent"]:
            datapct = pool_information["stats"][datatype]
            datapct_formatted = format_pct_tohuman(float(datapct))
            pool_information["stats"][datatype] = datapct_formatted

        # Set the Pool name length
        _pool_name_length = len(pool_information["name"]) + 1
        if _pool_name_length > pool_name_length:
            pool_name_length = _pool_name_length

        # Set the id and length
        _pool_id_length = len(str(pool_information["stats"]["id"])) + 1
        if _pool_id_length > pool_id_length:
            pool_id_length = _pool_id_length

        # Set the tier and length
        _pool_tier_length = len(str(pool_information["tier"])) + 1
        if _pool_tier_length > pool_tier_length:
            pool_tier_length = _pool_tier_length

        # Set the pgs and length
        _pool_pgs_length = len(str(pool_information["pgs"])) + 1
        if _pool_pgs_length > pool_pgs_length:
            pool_pgs_length = _pool_pgs_length

        # Set the used and length
        _pool_used_length = len(str(pool_information["stats"]["used_bytes"])) + 1
        if _pool_used_length > pool_used_length:
            pool_used_length = _pool_used_length

        # Set the usedpct and length
        _pool_usedpct_length = len(str(pool_information["stats"]["used_percent"])) + 1
        if _pool_usedpct_length > pool_usedpct_length:
            pool_usedpct_length = _pool_usedpct_length

        # Set the free and length
        _pool_free_length = len(str(pool_information["stats"]["free_bytes"])) + 1
        if _pool_free_length > pool_free_length:
            pool_free_length = _pool_free_length

        # Set the num_objects and length
        _pool_num_objects_length = (
            len(str(pool_information["stats"]["num_objects"])) + 1
        )
        if _pool_num_objects_length > pool_num_objects_length:
            pool_num_objects_length = _pool_num_objects_length

        # Set the num_clones and length
        _pool_num_clones_length = (
            len(str(pool_information["stats"]["num_object_clones"])) + 1
        )
        if _pool_num_clones_length > pool_num_clones_length:
            pool_num_clones_length = _pool_num_clones_length

        # Set the num_copies and length
        _pool_num_copies_length = (
            len(str(pool_information["stats"]["num_object_copies"])) + 1
        )
        if _pool_num_copies_length > pool_num_copies_length:
            pool_num_copies_length = _pool_num_copies_length

        # Set the num_degraded and length
        _pool_num_degraded_length = (
            len(str(pool_information["stats"]["num_objects_degraded"])) + 1
        )
        if _pool_num_degraded_length > pool_num_degraded_length:
            pool_num_degraded_length = _pool_num_degraded_length

        # Set the read/write IOPS/data and length
        _pool_write_ops_length = len(str(pool_information["stats"]["write_ops"])) + 1
        if _pool_write_ops_length > pool_write_ops_length:
            pool_write_ops_length = _pool_write_ops_length

        _pool_write_data_length = len(pool_information["stats"]["write_bytes"]) + 1
        if _pool_write_data_length > pool_write_data_length:
            pool_write_data_length = _pool_write_data_length

        _pool_read_ops_length = len(str(pool_information["stats"]["read_ops"])) + 1
        if _pool_read_ops_length > pool_read_ops_length:
            pool_read_ops_length = _pool_read_ops_length

        _pool_read_data_length = len(pool_information["stats"]["read_bytes"]) + 1
        if _pool_read_data_length > pool_read_data_length:
            pool_read_data_length = _pool_read_data_length

    # Format the output header
    pool_list_output.append(
        "{bold}{pool_header: <{pool_header_length}} {objects_header: <{objects_header_length}} {read_header: <{read_header_length}} {write_header: <{write_header_length}}{end_bold}".format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            pool_header_length=pool_id_length
            + pool_name_length
            + pool_tier_length
            + pool_pgs_length
            + pool_used_length
            + pool_usedpct_length
            + pool_free_length
            + 6,
            objects_header_length=pool_num_objects_length
            + pool_num_clones_length
            + pool_num_copies_length
            + pool_num_degraded_length
            + 3,
            read_header_length=pool_read_ops_length + pool_read_data_length + 1,
            write_header_length=pool_write_ops_length + pool_write_data_length + 1,
            pool_header="Pools "
            + "".join(
                [
                    "-"
                    for _ in range(
                        6,
                        pool_id_length
                        + pool_name_length
                        + pool_tier_length
                        + pool_pgs_length
                        + pool_used_length
                        + pool_usedpct_length
                        + pool_free_length
                        + 5,
                    )
                ]
            ),
            objects_header="Objects "
            + "".join(
                [
                    "-"
                    for _ in range(
                        8,
                        pool_num_objects_length
                        + pool_num_clones_length
                        + pool_num_copies_length
                        + pool_num_degraded_length
                        + 2,
                    )
                ]
            ),
            read_header="Read "
            + "".join(
                ["-" for _ in range(5, pool_read_ops_length + pool_read_data_length)]
            ),
            write_header="Write "
            + "".join(
                ["-" for _ in range(6, pool_write_ops_length + pool_write_data_length)]
            ),
        )
    )

    pool_list_output.append(
        "{bold}\
{pool_id: <{pool_id_length}} \
{pool_name: <{pool_name_length}} \
{pool_tier: <{pool_tier_length}} \
{pool_pgs: <{pool_pgs_length}} \
{pool_used: <{pool_used_length}} \
{pool_usedpct: <{pool_usedpct_length}} \
{pool_free: <{pool_free_length}} \
{pool_objects: <{pool_objects_length}} \
{pool_clones: <{pool_clones_length}} \
{pool_copies: <{pool_copies_length}} \
{pool_degraded: <{pool_degraded_length}} \
{pool_read_ops: <{pool_read_ops_length}} \
{pool_read_data: <{pool_read_data_length}} \
{pool_write_ops: <{pool_write_ops_length}} \
{pool_write_data: <{pool_write_data_length}} \
{end_bold}".format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            pool_id_length=pool_id_length,
            pool_name_length=pool_name_length,
            pool_tier_length=pool_tier_length,
            pool_pgs_length=pool_pgs_length,
            pool_used_length=pool_used_length,
            pool_usedpct_length=pool_usedpct_length,
            pool_free_length=pool_free_length,
            pool_objects_length=pool_num_objects_length,
            pool_clones_length=pool_num_clones_length,
            pool_copies_length=pool_num_copies_length,
            pool_degraded_length=pool_num_degraded_length,
            pool_write_ops_length=pool_write_ops_length,
            pool_write_data_length=pool_write_data_length,
            pool_read_ops_length=pool_read_ops_length,
            pool_read_data_length=pool_read_data_length,
            pool_id="ID",
            pool_name="Name",
            pool_tier="Tier",
            pool_pgs="PGs",
            pool_used="Used",
            pool_usedpct="Used%",
            pool_free="Free",
            pool_objects="Count",
            pool_clones="Clones",
            pool_copies="Copies",
            pool_degraded="Degraded",
            pool_write_ops="OPS",
            pool_write_data="Data",
            pool_read_ops="OPS",
            pool_read_data="Data",
        )
    )

    for pool_information in sorted(pool_list, key=lambda x: int(x["stats"]["id"])):
        # Format the output header
        pool_list_output.append(
            "{bold}\
{pool_id: <{pool_id_length}} \
{pool_name: <{pool_name_length}} \
{pool_tier: <{pool_tier_length}} \
{pool_pgs: <{pool_pgs_length}} \
{pool_used: <{pool_used_length}} \
{pool_usedpct: <{pool_usedpct_length}} \
{pool_free: <{pool_free_length}} \
{pool_objects: <{pool_objects_length}} \
{pool_clones: <{pool_clones_length}} \
{pool_copies: <{pool_copies_length}} \
{pool_degraded: <{pool_degraded_length}} \
{pool_read_ops: <{pool_read_ops_length}} \
{pool_read_data: <{pool_read_data_length}} \
{pool_write_ops: <{pool_write_ops_length}} \
{pool_write_data: <{pool_write_data_length}} \
{end_bold}".format(
                bold="",
                end_bold="",
                pool_id_length=pool_id_length,
                pool_name_length=pool_name_length,
                pool_tier_length=pool_tier_length,
                pool_pgs_length=pool_pgs_length,
                pool_used_length=pool_used_length,
                pool_usedpct_length=pool_usedpct_length,
                pool_free_length=pool_free_length,
                pool_objects_length=pool_num_objects_length,
                pool_clones_length=pool_num_clones_length,
                pool_copies_length=pool_num_copies_length,
                pool_degraded_length=pool_num_degraded_length,
                pool_write_ops_length=pool_write_ops_length,
                pool_write_data_length=pool_write_data_length,
                pool_read_ops_length=pool_read_ops_length,
                pool_read_data_length=pool_read_data_length,
                pool_id=pool_information["stats"]["id"],
                pool_name=pool_information["name"],
                pool_tier=pool_information["tier"],
                pool_pgs=pool_information["pgs"],
                pool_used=pool_information["stats"]["used_bytes"],
                pool_usedpct=pool_information["stats"]["used_percent"],
                pool_free=pool_information["stats"]["free_bytes"],
                pool_objects=pool_information["stats"]["num_objects"],
                pool_clones=pool_information["stats"]["num_object_clones"],
                pool_copies=pool_information["stats"]["num_object_copies"],
                pool_degraded=pool_information["stats"]["num_objects_degraded"],
                pool_write_ops=pool_information["stats"]["write_ops"],
                pool_write_data=pool_information["stats"]["write_bytes"],
                pool_read_ops=pool_information["stats"]["read_ops"],
                pool_read_data=pool_information["stats"]["read_bytes"],
            )
        )

    return "\n".join(pool_list_output)


#
# Volume functions
#
def ceph_volume_info(config, pool, volume):
    """
    Get information about Ceph volume

    API endpoint: GET /api/v1/storage/ceph/volume/{pool}/{volume}
    API arguments:
    API schema: {json_data_object}
    """
    response = call_api(
        config,
        "get",
        "/storage/ceph/volume/{pool}/{volume}".format(volume=volume, pool=pool),
    )

    if response.status_code == 200:
        if isinstance(response.json(), list) and len(response.json()) != 1:
            # No exact match; return not found
            return False, "Volume not found."
        else:
            # Return a single instance if the response is a list
            if isinstance(response.json(), list):
                return True, response.json()[0]
            # This shouldn't happen, but is here just in case
            else:
                return True, response.json()
    else:
        return False, response.json().get("message", "")


def ceph_volume_list(config, limit, pool):
    """
    Get list information about Ceph volumes (limited by {limit} and by {pool})

    API endpoint: GET /api/v1/storage/ceph/volume
    API arguments: limit={limit}, pool={pool}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    if limit:
        params["limit"] = limit
    if pool:
        params["pool"] = pool

    response = call_api(config, "get", "/storage/ceph/volume", params=params)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json().get("message", "")


def ceph_volume_add(config, pool, volume, size, force_flag=False):
    """
    Add new Ceph volume

    API endpoint: POST /api/v1/storage/ceph/volume
    API arguments: volume={volume}, pool={pool}, size={size}, force={force_flag}
    API schema: {"message":"{data}"}
    """
    params = {"volume": volume, "pool": pool, "size": size, "force": force_flag}
    response = call_api(config, "post", "/storage/ceph/volume", params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def ceph_volume_upload(config, pool, volume, image_format, image_file):
    """
    Upload a disk image to a Ceph volume

    API endpoint: POST /api/v1/storage/ceph/volume/{pool}/{volume}/upload
    API arguments: image_format={image_format}
    API schema: {"message":"{data}"}
    """
    import click

    if image_format != "raw":
        file_size = path.getsize(image_file)
    else:
        file_size = None

    bar = UploadProgressBar(
        image_file, end_message="Parsing file on remote side...", end_nl=False
    )

    from requests_toolbelt.multipart.encoder import (
        MultipartEncoder,
        MultipartEncoderMonitor,
    )

    upload_data = MultipartEncoder(
        fields={
            "file": ("filename", open(image_file, "rb"), "application/octet-stream")
        }
    )
    upload_monitor = MultipartEncoderMonitor(upload_data, bar.update)

    headers = {"Content-Type": upload_monitor.content_type}
    params = {"image_format": image_format, "file_size": file_size}

    response = call_api(
        config,
        "post",
        "/storage/ceph/volume/{}/{}/upload".format(pool, volume),
        headers=headers,
        params=params,
        data=upload_monitor,
    )

    click.echo("done.")
    click.echo()

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def ceph_volume_remove(config, pool, volume):
    """
    Remove Ceph volume

    API endpoint: DELETE /api/v1/storage/ceph/volume/{pool}/{volume}
    API arguments:
    API schema: {"message":"{data}"}
    """
    response = call_api(
        config,
        "delete",
        "/storage/ceph/volume/{pool}/{volume}".format(volume=volume, pool=pool),
    )

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def ceph_volume_modify(
    config, pool, volume, new_name=None, new_size=None, force_flag=False
):
    """
    Modify Ceph volume

    API endpoint: PUT /api/v1/storage/ceph/volume/{pool}/{volume}
    API arguments: [new_name={new_name}], [new_size={new_size}], force_flag={force_flag}
    API schema: {"message":"{data}"}
    """

    params = dict()
    if new_name:
        params["new_name"] = new_name
    if new_size:
        params["new_size"] = new_size
        params["force"] = force_flag

    response = call_api(
        config,
        "put",
        "/storage/ceph/volume/{pool}/{volume}".format(volume=volume, pool=pool),
        params=params,
    )

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def ceph_volume_clone(config, pool, volume, new_volume, force_flag=False):
    """
    Clone Ceph volume

    API endpoint: POST /api/v1/storage/ceph/volume/{pool}/{volume}
    API arguments: new_volume={new_volume, force_flag={force_flag}
    API schema: {"message":"{data}"}
    """
    params = {"new_volume": new_volume, "force_flag": force_flag}
    response = call_api(
        config,
        "post",
        "/storage/ceph/volume/{pool}/{volume}/clone".format(volume=volume, pool=pool),
        params=params,
    )

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def format_list_volume(config, volume_list):
    # Handle empty list
    if not volume_list:
        volume_list = list()

    volume_list_output = []

    volume_name_length = 5
    volume_pool_length = 5
    volume_size_length = 5
    volume_objects_length = 8
    volume_order_length = 6
    volume_format_length = 7
    volume_features_length = 10

    for volume_information in volume_list:
        # Set the Volume name length
        _volume_name_length = len(volume_information["name"]) + 1
        if _volume_name_length > volume_name_length:
            volume_name_length = _volume_name_length

        # Set the Volume pool length
        _volume_pool_length = len(volume_information["pool"]) + 1
        if _volume_pool_length > volume_pool_length:
            volume_pool_length = _volume_pool_length

        # Set the size and length
        _volume_size_length = len(str(volume_information["stats"]["size"])) + 1
        if _volume_size_length > volume_size_length:
            volume_size_length = _volume_size_length

        # Set the num_objects and length
        _volume_objects_length = len(str(volume_information["stats"]["objects"])) + 1
        if _volume_objects_length > volume_objects_length:
            volume_objects_length = _volume_objects_length

        # Set the order and length
        _volume_order_length = len(str(volume_information["stats"]["order"])) + 1
        if _volume_order_length > volume_order_length:
            volume_order_length = _volume_order_length

        # Set the format and length
        _volume_format_length = len(str(volume_information["stats"]["format"])) + 1
        if _volume_format_length > volume_format_length:
            volume_format_length = _volume_format_length

        # Set the features and length
        _volume_features_length = (
            len(str(",".join(volume_information["stats"]["features"]))) + 1
        )
        if _volume_features_length > volume_features_length:
            volume_features_length = _volume_features_length

    # Format the output header
    volume_list_output.append(
        "{bold}{volume_header: <{volume_header_length}} {details_header: <{details_header_length}}{end_bold}".format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            volume_header_length=volume_name_length + volume_pool_length + 1,
            details_header_length=volume_size_length
            + volume_objects_length
            + volume_order_length
            + volume_format_length
            + volume_features_length
            + 4,
            volume_header="Volumes "
            + "".join(["-" for _ in range(8, volume_name_length + volume_pool_length)]),
            details_header="Details "
            + "".join(
                [
                    "-"
                    for _ in range(
                        8,
                        volume_size_length
                        + volume_objects_length
                        + volume_order_length
                        + volume_format_length
                        + volume_features_length
                        + 3,
                    )
                ]
            ),
        )
    )

    volume_list_output.append(
        "{bold}\
{volume_name: <{volume_name_length}} \
{volume_pool: <{volume_pool_length}} \
{volume_size: <{volume_size_length}} \
{volume_objects: <{volume_objects_length}} \
{volume_order: <{volume_order_length}} \
{volume_format: <{volume_format_length}} \
{volume_features: <{volume_features_length}} \
{end_bold}".format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            volume_name_length=volume_name_length,
            volume_pool_length=volume_pool_length,
            volume_size_length=volume_size_length,
            volume_objects_length=volume_objects_length,
            volume_order_length=volume_order_length,
            volume_format_length=volume_format_length,
            volume_features_length=volume_features_length,
            volume_name="Name",
            volume_pool="Pool",
            volume_size="Size",
            volume_objects="Objects",
            volume_order="Order",
            volume_format="Format",
            volume_features="Features",
        )
    )

    for volume_information in sorted(volume_list, key=lambda v: v["pool"] + v["name"]):
        volume_list_output.append(
            "{bold}\
{volume_name: <{volume_name_length}} \
{volume_pool: <{volume_pool_length}} \
{volume_size: <{volume_size_length}} \
{volume_objects: <{volume_objects_length}} \
{volume_order: <{volume_order_length}} \
{volume_format: <{volume_format_length}} \
{volume_features: <{volume_features_length}} \
{end_bold}".format(
                bold="",
                end_bold="",
                volume_name_length=volume_name_length,
                volume_pool_length=volume_pool_length,
                volume_size_length=volume_size_length,
                volume_objects_length=volume_objects_length,
                volume_order_length=volume_order_length,
                volume_format_length=volume_format_length,
                volume_features_length=volume_features_length,
                volume_name=volume_information["name"],
                volume_pool=volume_information["pool"],
                volume_size=volume_information["stats"]["size"],
                volume_objects=volume_information["stats"]["objects"],
                volume_order=volume_information["stats"]["order"],
                volume_format=volume_information["stats"]["format"],
                volume_features=",".join(volume_information["stats"]["features"]),
            )
        )

    return "\n".join(volume_list_output)


#
# Snapshot functions
#
def ceph_snapshot_info(config, pool, volume, snapshot):
    """
    Get information about Ceph snapshot

    API endpoint: GET /api/v1/storage/ceph/snapshot/{pool}/{volume}/{snapshot}
    API arguments:
    API schema: {json_data_object}
    """
    response = call_api(
        config,
        "get",
        "/storage/ceph/snapshot/{pool}/{volume}/{snapshot}".format(
            snapshot=snapshot, volume=volume, pool=pool
        ),
    )

    if response.status_code == 200:
        if isinstance(response.json(), list) and len(response.json()) != 1:
            # No exact match; return not found
            return False, "Snapshot not found."
        else:
            # Return a single instance if the response is a list
            if isinstance(response.json(), list):
                return True, response.json()[0]
            # This shouldn't happen, but is here just in case
            else:
                return True, response.json()
    else:
        return False, response.json().get("message", "")


def ceph_snapshot_list(config, limit, volume, pool):
    """
    Get list information about Ceph snapshots (limited by {limit}, by {pool}, or by {volume})

    API endpoint: GET /api/v1/storage/ceph/snapshot
    API arguments: limit={limit}, volume={volume}, pool={pool}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    if limit:
        params["limit"] = limit
    if volume:
        params["volume"] = volume
    if pool:
        params["pool"] = pool

    response = call_api(config, "get", "/storage/ceph/snapshot", params=params)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json().get("message", "")


def ceph_snapshot_add(config, pool, volume, snapshot):
    """
    Add new Ceph snapshot

    API endpoint: POST /api/v1/storage/ceph/snapshot
    API arguments: snapshot={snapshot}, volume={volume}, pool={pool}
    API schema: {"message":"{data}"}
    """
    params = {"snapshot": snapshot, "volume": volume, "pool": pool}
    response = call_api(config, "post", "/storage/ceph/snapshot", params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def ceph_snapshot_rollback(config, pool, volume, snapshot):
    """
    Roll back Ceph volume to snapshot

    API endpoint: POST /api/v1/storage/ceph/snapshot/{pool}/{volume}/{snapshot}/rollback
    API arguments:
    API schema: {"message":"{data}"}
    """
    response = call_api(
        config,
        "post",
        "/storage/ceph/snapshot/{pool}/{volume}/{snapshot}/rollback".format(
            snapshot=snapshot, volume=volume, pool=pool
        ),
    )

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def ceph_snapshot_remove(config, pool, volume, snapshot):
    """
    Remove Ceph snapshot

    API endpoint: DELETE /api/v1/storage/ceph/snapshot/{pool}/{volume}/{snapshot}
    API arguments:
    API schema: {"message":"{data}"}
    """
    response = call_api(
        config,
        "delete",
        "/storage/ceph/snapshot/{pool}/{volume}/{snapshot}".format(
            snapshot=snapshot, volume=volume, pool=pool
        ),
    )

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def ceph_snapshot_modify(config, pool, volume, snapshot, new_name=None):
    """
    Modify Ceph snapshot

    API endpoint: PUT /api/v1/storage/ceph/snapshot/{pool}/{volume}/{snapshot}
    API arguments:
    API schema: {"message":"{data}"}
    """

    params = dict()
    if new_name:
        params["new_name"] = new_name

    response = call_api(
        config,
        "put",
        "/storage/ceph/snapshot/{pool}/{volume}/{snapshot}".format(
            snapshot=snapshot, volume=volume, pool=pool
        ),
        params=params,
    )

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def format_list_snapshot(config, snapshot_list):
    # Handle empty list
    if not snapshot_list:
        snapshot_list = list()

    snapshot_list_output = []

    snapshot_name_length = 5
    snapshot_volume_length = 7
    snapshot_pool_length = 5

    for snapshot_information in snapshot_list:
        snapshot_name = snapshot_information["snapshot"]
        snapshot_volume = snapshot_information["volume"]
        snapshot_pool = snapshot_information["pool"]

        # Set the Snapshot name length
        _snapshot_name_length = len(snapshot_name) + 1
        if _snapshot_name_length > snapshot_name_length:
            snapshot_name_length = _snapshot_name_length

        # Set the Snapshot volume length
        _snapshot_volume_length = len(snapshot_volume) + 1
        if _snapshot_volume_length > snapshot_volume_length:
            snapshot_volume_length = _snapshot_volume_length

        # Set the Snapshot pool length
        _snapshot_pool_length = len(snapshot_pool) + 1
        if _snapshot_pool_length > snapshot_pool_length:
            snapshot_pool_length = _snapshot_pool_length

    # Format the output header
    snapshot_list_output.append(
        "{bold}{snapshot_header: <{snapshot_header_length}}{end_bold}".format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            snapshot_header_length=snapshot_name_length
            + snapshot_volume_length
            + snapshot_pool_length
            + 2,
            snapshot_header="Snapshots "
            + "".join(
                [
                    "-"
                    for _ in range(
                        10,
                        snapshot_name_length
                        + snapshot_volume_length
                        + snapshot_pool_length
                        + 1,
                    )
                ]
            ),
        )
    )

    snapshot_list_output.append(
        "{bold}\
{snapshot_name: <{snapshot_name_length}} \
{snapshot_volume: <{snapshot_volume_length}} \
{snapshot_pool: <{snapshot_pool_length}} \
{end_bold}".format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            snapshot_name_length=snapshot_name_length,
            snapshot_volume_length=snapshot_volume_length,
            snapshot_pool_length=snapshot_pool_length,
            snapshot_name="Name",
            snapshot_volume="Volume",
            snapshot_pool="Pool",
        )
    )

    for snapshot_information in sorted(
        snapshot_list, key=lambda s: s["pool"] + s["volume"] + s["snapshot"]
    ):
        snapshot_name = snapshot_information["snapshot"]
        snapshot_volume = snapshot_information["volume"]
        snapshot_pool = snapshot_information["pool"]
        snapshot_list_output.append(
            "{bold}\
{snapshot_name: <{snapshot_name_length}} \
{snapshot_volume: <{snapshot_volume_length}} \
{snapshot_pool: <{snapshot_pool_length}} \
{end_bold}".format(
                bold="",
                end_bold="",
                snapshot_name_length=snapshot_name_length,
                snapshot_volume_length=snapshot_volume_length,
                snapshot_pool_length=snapshot_pool_length,
                snapshot_name=snapshot_name,
                snapshot_volume=snapshot_volume,
                snapshot_pool=snapshot_pool,
            )
        )

    return "\n".join(snapshot_list_output)


#
# Benchmark functions
#
def ceph_benchmark_run(config, pool, name, wait_flag):
    """
    Run a storage benchmark against {pool}

    API endpoint: POST /api/v1/storage/ceph/benchmark
    API arguments: pool={pool}, name={name}
    API schema: {message}
    """
    params = {"pool": pool}
    if name:
        params["name"] = name
    response = call_api(config, "post", "/storage/ceph/benchmark", params=params)

    return get_wait_retdata(response, wait_flag)


def ceph_benchmark_list(config, job):
    """
    View results of one or more previous benchmark runs

    API endpoint: GET /api/v1/storage/ceph/benchmark
    API arguments: job={job}
    API schema: {results}
    """
    if job is not None:
        params = {"job": job}
    else:
        params = {}

    response = call_api(config, "get", "/storage/ceph/benchmark", params=params)

    if response.status_code == 200:
        retvalue = True
        retdata = response.json()
    else:
        retvalue = False
        retdata = response.json().get("message", "")

    return retvalue, retdata


def get_benchmark_list_results_legacy(benchmark_data):
    if isinstance(benchmark_data, str):
        benchmark_data = loads(benchmark_data)
    benchmark_bandwidth = dict()
    benchmark_iops = dict()
    for test in ["seq_read", "seq_write", "rand_read_4K", "rand_write_4K"]:
        benchmark_bandwidth[test] = format_bytes_tohuman(
            int(benchmark_data[test]["overall"]["bandwidth"]) * 1024
        )
        benchmark_iops[test] = format_ops_tohuman(
            int(benchmark_data[test]["overall"]["iops"])
        )

    return benchmark_bandwidth, benchmark_iops


def get_benchmark_list_results_json(benchmark_data):
    benchmark_bandwidth = dict()
    benchmark_iops = dict()
    for test in ["seq_read", "seq_write", "rand_read_4K", "rand_write_4K"]:
        benchmark_test_data = benchmark_data[test]
        active_class = None
        for io_class in ["read", "write"]:
            if benchmark_test_data["jobs"][0][io_class]["io_bytes"] > 0:
                active_class = io_class
        if active_class is not None:
            benchmark_bandwidth[test] = format_bytes_tohuman(
                int(benchmark_test_data["jobs"][0][active_class]["bw_bytes"])
            )
            benchmark_iops[test] = format_ops_tohuman(
                int(benchmark_test_data["jobs"][0][active_class]["iops"])
            )

    return benchmark_bandwidth, benchmark_iops


def get_benchmark_list_results(benchmark_format, benchmark_data):
    if benchmark_format == 0:
        benchmark_bandwidth, benchmark_iops = get_benchmark_list_results_legacy(
            benchmark_data
        )
    elif benchmark_format == 1 or benchmark_format == 2:
        benchmark_bandwidth, benchmark_iops = get_benchmark_list_results_json(
            benchmark_data
        )

    seq_benchmark_bandwidth = "{} / {}".format(
        benchmark_bandwidth["seq_read"], benchmark_bandwidth["seq_write"]
    )
    seq_benchmark_iops = "{} / {}".format(
        benchmark_iops["seq_read"], benchmark_iops["seq_write"]
    )
    rand_benchmark_bandwidth = "{} / {}".format(
        benchmark_bandwidth["rand_read_4K"], benchmark_bandwidth["rand_write_4K"]
    )
    rand_benchmark_iops = "{} / {}".format(
        benchmark_iops["rand_read_4K"], benchmark_iops["rand_write_4K"]
    )

    return (
        seq_benchmark_bandwidth,
        seq_benchmark_iops,
        rand_benchmark_bandwidth,
        rand_benchmark_iops,
    )


def format_list_benchmark(config, benchmark_information):
    benchmark_list_output = []

    benchmark_job_length = 20
    benchmark_format_length = 6
    benchmark_bandwidth_length = dict()
    benchmark_iops_length = dict()

    # For this output, we're only showing the Sequential (seq_read and seq_write) and 4k Random (rand_read_4K and rand_write_4K) results since we're showing them for each test result.
    for test in ["seq_read", "seq_write", "rand_read_4K", "rand_write_4K"]:
        benchmark_bandwidth_length[test] = 7
        benchmark_iops_length[test] = 6

    benchmark_seq_bw_length = 15
    benchmark_seq_iops_length = 10
    benchmark_rand_bw_length = 15
    benchmark_rand_iops_length = 10

    for benchmark in benchmark_information:
        benchmark_job = benchmark["job"]
        benchmark_format = benchmark.get("test_format", 0)  # noqa: F841

        _benchmark_job_length = len(benchmark_job)
        if _benchmark_job_length > benchmark_job_length:
            benchmark_job_length = _benchmark_job_length

        if benchmark["benchmark_result"] == "Running":
            continue

        benchmark_data = benchmark["benchmark_result"]
        (
            seq_benchmark_bandwidth,
            seq_benchmark_iops,
            rand_benchmark_bandwidth,
            rand_benchmark_iops,
        ) = get_benchmark_list_results(benchmark_format, benchmark_data)

        _benchmark_seq_bw_length = len(seq_benchmark_bandwidth) + 1
        if _benchmark_seq_bw_length > benchmark_seq_bw_length:
            benchmark_seq_bw_length = _benchmark_seq_bw_length

        _benchmark_seq_iops_length = len(seq_benchmark_iops) + 1
        if _benchmark_seq_iops_length > benchmark_seq_iops_length:
            benchmark_seq_iops_length = _benchmark_seq_iops_length

        _benchmark_rand_bw_length = len(rand_benchmark_bandwidth) + 1
        if _benchmark_rand_bw_length > benchmark_rand_bw_length:
            benchmark_rand_bw_length = _benchmark_rand_bw_length

        _benchmark_rand_iops_length = len(rand_benchmark_iops) + 1
        if _benchmark_rand_iops_length > benchmark_rand_iops_length:
            benchmark_rand_iops_length = _benchmark_rand_iops_length

    # Format the output header line 1
    benchmark_list_output.append(
        "{bold}\
{benchmark_job: <{benchmark_job_length}}   \
{seq_header: <{seq_header_length}}  \
{rand_header: <{rand_header_length}}\
{end_bold}".format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            benchmark_job_length=benchmark_job_length + benchmark_format_length + 1,
            seq_header_length=benchmark_seq_bw_length + benchmark_seq_iops_length + 1,
            rand_header_length=benchmark_rand_bw_length
            + benchmark_rand_iops_length
            + 1,
            benchmark_job="Benchmarks "
            + "".join(
                [
                    "-"
                    for _ in range(
                        11, benchmark_job_length + benchmark_format_length + 2
                    )
                ]
            ),
            seq_header="Sequential (4M blocks) "
            + "".join(
                [
                    "-"
                    for _ in range(
                        23, benchmark_seq_bw_length + benchmark_seq_iops_length
                    )
                ]
            ),
            rand_header="Random (4K blocks) "
            + "".join(
                [
                    "-"
                    for _ in range(
                        19, benchmark_rand_bw_length + benchmark_rand_iops_length
                    )
                ]
            ),
        )
    )

    benchmark_list_output.append(
        "{bold}\
{benchmark_job: <{benchmark_job_length}}  \
{benchmark_format: <{benchmark_format_length}}   \
{seq_benchmark_bandwidth: <{seq_benchmark_bandwidth_length}} \
{seq_benchmark_iops: <{seq_benchmark_iops_length}}  \
{rand_benchmark_bandwidth: <{rand_benchmark_bandwidth_length}} \
{rand_benchmark_iops: <{rand_benchmark_iops_length}}\
{end_bold}".format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            benchmark_job_length=benchmark_job_length,
            benchmark_format_length=benchmark_format_length,
            seq_benchmark_bandwidth_length=benchmark_seq_bw_length,
            seq_benchmark_iops_length=benchmark_seq_iops_length,
            rand_benchmark_bandwidth_length=benchmark_rand_bw_length,
            rand_benchmark_iops_length=benchmark_rand_iops_length,
            benchmark_job="Job",
            benchmark_format="Format",
            seq_benchmark_bandwidth="R/W Bandwith/s",
            seq_benchmark_iops="R/W IOPS",
            rand_benchmark_bandwidth="R/W Bandwith/s",
            rand_benchmark_iops="R/W IOPS",
        )
    )

    for benchmark in benchmark_information:
        benchmark_job = benchmark["job"]
        benchmark_format = benchmark.get("test_format", 0)  # noqa: F841

        if benchmark["benchmark_result"] == "Running":
            seq_benchmark_bandwidth = "Running"
            seq_benchmark_iops = "Running"
            rand_benchmark_bandwidth = "Running"
            rand_benchmark_iops = "Running"
        else:
            benchmark_data = benchmark["benchmark_result"]
            (
                seq_benchmark_bandwidth,
                seq_benchmark_iops,
                rand_benchmark_bandwidth,
                rand_benchmark_iops,
            ) = get_benchmark_list_results(benchmark_format, benchmark_data)

        benchmark_list_output.append(
            "{bold}\
{benchmark_job: <{benchmark_job_length}}  \
{benchmark_format: <{benchmark_format_length}}   \
{seq_benchmark_bandwidth: <{seq_benchmark_bandwidth_length}} \
{seq_benchmark_iops: <{seq_benchmark_iops_length}}  \
{rand_benchmark_bandwidth: <{rand_benchmark_bandwidth_length}} \
{rand_benchmark_iops: <{rand_benchmark_iops_length}}\
{end_bold}".format(
                bold="",
                end_bold="",
                benchmark_job_length=benchmark_job_length,
                benchmark_format_length=benchmark_format_length,
                seq_benchmark_bandwidth_length=benchmark_seq_bw_length,
                seq_benchmark_iops_length=benchmark_seq_iops_length,
                rand_benchmark_bandwidth_length=benchmark_rand_bw_length,
                rand_benchmark_iops_length=benchmark_rand_iops_length,
                benchmark_job=benchmark_job,
                benchmark_format=benchmark_format,
                seq_benchmark_bandwidth=seq_benchmark_bandwidth,
                seq_benchmark_iops=seq_benchmark_iops,
                rand_benchmark_bandwidth=rand_benchmark_bandwidth,
                rand_benchmark_iops=rand_benchmark_iops,
            )
        )

    return "\n".join(benchmark_list_output)


def format_info_benchmark(config, benchmark_information):
    # This matrix is a list of the possible format functions for a benchmark result
    # It is extensable in the future should newer formats be required.
    benchmark_matrix = {
        0: format_info_benchmark_legacy,
        1: format_info_benchmark_json,
        2: format_info_benchmark_json,
    }

    benchmark_version = benchmark_information[0]["test_format"]

    return benchmark_matrix[benchmark_version](config, benchmark_information[0])


def format_info_benchmark_legacy(config, benchmark_information):
    if benchmark_information["benchmark_result"] == "Running":
        return "Benchmark test is still running."

    benchmark_details = benchmark_information["benchmark_result"]

    # Format a nice output; do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append(
        "{}Storage Benchmark details:{}".format(ansiprint.bold(), ansiprint.end())
    )

    nice_test_name_map = {
        "seq_read": "Sequential Read (4M blocks)",
        "seq_write": "Sequential Write (4M blocks)",
        "rand_read_4M": "Random Read (4M blocks)",
        "rand_write_4M": "Random Write (4M blocks)",
        "rand_read_4K": "Random Read (4K blocks)",
        "rand_write_4K": "Random Write (4K blocks)",
        "rand_read_4K_lowdepth": "Random Read (4K blocks, single-queue)",
        "rand_write_4K_lowdepth": "Random Write (4K blocks, single-queue)",
    }

    test_name_length = 30
    overall_label_length = 12
    overall_column_length = 8
    bandwidth_label_length = 9
    bandwidth_column_length = 10
    iops_column_length = 6
    latency_column_length = 8
    cpuutil_label_length = 11
    cpuutil_column_length = 9

    # Work around old results that did not have these tests
    if "rand_read_4K_lowdepth" not in benchmark_details:
        del nice_test_name_map["rand_read_4K_lowdepth"]
        del nice_test_name_map["rand_write_4K_lowdepth"]

    for test in benchmark_details:
        # Work around old results that had these obsolete tests
        if test == "rand_read_256K" or test == "rand_write_256K":
            continue

        _test_name_length = len(nice_test_name_map[test])
        if _test_name_length > test_name_length:
            test_name_length = _test_name_length

        for element in benchmark_details[test]["overall"]:
            _element_length = len(benchmark_details[test]["overall"][element])
            if _element_length > overall_column_length:
                overall_column_length = _element_length

        for element in benchmark_details[test]["bandwidth"]:
            try:
                _element_length = len(
                    format_bytes_tohuman(
                        int(float(benchmark_details[test]["bandwidth"][element]))
                    )
                )
            except Exception:
                _element_length = len(benchmark_details[test]["bandwidth"][element])
            if _element_length > bandwidth_column_length:
                bandwidth_column_length = _element_length

        for element in benchmark_details[test]["iops"]:
            try:
                _element_length = len(
                    format_ops_tohuman(
                        int(float(benchmark_details[test]["iops"][element]))
                    )
                )
            except Exception:
                _element_length = len(benchmark_details[test]["iops"][element])
            if _element_length > iops_column_length:
                iops_column_length = _element_length

        for element in benchmark_details[test]["latency"]:
            _element_length = len(benchmark_details[test]["latency"][element])
            if _element_length > latency_column_length:
                latency_column_length = _element_length

        for element in benchmark_details[test]["cpu"]:
            _element_length = len(benchmark_details[test]["cpu"][element])
            if _element_length > cpuutil_column_length:
                cpuutil_column_length = _element_length

    for test in benchmark_details:
        # Work around old results that had these obsolete tests
        if test == "rand_read_256K" or test == "rand_write_256K":
            continue

        ainformation.append("")

        test_details = benchmark_details[test]

        # Top row (Headers)
        ainformation.append(
            "{bold}\
{test_name: <{test_name_length}} \
{overall_label: <{overall_label_length}} \
{overall: <{overall_length}} \
{bandwidth_label: <{bandwidth_label_length}} \
{bandwidth: <{bandwidth_length}} \
{iops: <{iops_length}} \
{latency: <{latency_length}} \
{cpuutil_label: <{cpuutil_label_length}} \
{cpuutil: <{cpuutil_length}} \
{end_bold}".format(
                bold=ansiprint.bold(),
                end_bold=ansiprint.end(),
                test_name="Test:",
                test_name_length=test_name_length,
                overall_label="",
                overall_label_length=overall_label_length,
                overall="General",
                overall_length=overall_column_length,
                bandwidth_label="",
                bandwidth_label_length=bandwidth_label_length,
                bandwidth="Bandwidth",
                bandwidth_length=bandwidth_column_length,
                iops="IOPS",
                iops_length=iops_column_length,
                latency="Latency (μs)",
                latency_length=latency_column_length,
                cpuutil_label="",
                cpuutil_label_length=cpuutil_label_length,
                cpuutil="CPU Util",
                cpuutil_length=cpuutil_column_length,
            )
        )
        # Second row (Test, Size, Min, User))
        ainformation.append(
            "{bold}\
{test_name: <{test_name_length}} \
{overall_label: >{overall_label_length}} \
{overall: <{overall_length}} \
{bandwidth_label: >{bandwidth_label_length}} \
{bandwidth: <{bandwidth_length}} \
{iops: <{iops_length}} \
{latency: <{latency_length}} \
{cpuutil_label: >{cpuutil_label_length}} \
{cpuutil: <{cpuutil_length}} \
{end_bold}".format(
                bold="",
                end_bold="",
                test_name=nice_test_name_map[test],
                test_name_length=test_name_length,
                overall_label="Test Size:",
                overall_label_length=overall_label_length,
                overall=format_bytes_tohuman(
                    int(test_details["overall"]["iosize"]) * 1024
                ),
                overall_length=overall_column_length,
                bandwidth_label="Min:",
                bandwidth_label_length=bandwidth_label_length,
                bandwidth=format_bytes_tohuman(
                    int(test_details["bandwidth"]["min"]) * 1024
                ),
                bandwidth_length=bandwidth_column_length,
                iops=format_ops_tohuman(int(test_details["iops"]["min"])),
                iops_length=iops_column_length,
                latency=test_details["latency"]["min"],
                latency_length=latency_column_length,
                cpuutil_label="User:",
                cpuutil_label_length=cpuutil_label_length,
                cpuutil=test_details["cpu"]["user"],
                cpuutil_length=cpuutil_column_length,
            )
        )
        # Third row (blank, BW/s, Max, System))
        ainformation.append(
            "{bold}\
{test_name: <{test_name_length}} \
{overall_label: >{overall_label_length}} \
{overall: <{overall_length}} \
{bandwidth_label: >{bandwidth_label_length}} \
{bandwidth: <{bandwidth_length}} \
{iops: <{iops_length}} \
{latency: <{latency_length}} \
{cpuutil_label: >{cpuutil_label_length}} \
{cpuutil: <{cpuutil_length}} \
{end_bold}".format(
                bold="",
                end_bold="",
                test_name="",
                test_name_length=test_name_length,
                overall_label="Bandwidth/s:",
                overall_label_length=overall_label_length,
                overall=format_bytes_tohuman(
                    int(test_details["overall"]["bandwidth"]) * 1024
                ),
                overall_length=overall_column_length,
                bandwidth_label="Max:",
                bandwidth_label_length=bandwidth_label_length,
                bandwidth=format_bytes_tohuman(
                    int(test_details["bandwidth"]["max"]) * 1024
                ),
                bandwidth_length=bandwidth_column_length,
                iops=format_ops_tohuman(int(test_details["iops"]["max"])),
                iops_length=iops_column_length,
                latency=test_details["latency"]["max"],
                latency_length=latency_column_length,
                cpuutil_label="System:",
                cpuutil_label_length=cpuutil_label_length,
                cpuutil=test_details["cpu"]["system"],
                cpuutil_length=cpuutil_column_length,
            )
        )
        # Fourth row (blank, IOPS, Mean, CtxSq))
        ainformation.append(
            "{bold}\
{test_name: <{test_name_length}} \
{overall_label: >{overall_label_length}} \
{overall: <{overall_length}} \
{bandwidth_label: >{bandwidth_label_length}} \
{bandwidth: <{bandwidth_length}} \
{iops: <{iops_length}} \
{latency: <{latency_length}} \
{cpuutil_label: >{cpuutil_label_length}} \
{cpuutil: <{cpuutil_length}} \
{end_bold}".format(
                bold="",
                end_bold="",
                test_name="",
                test_name_length=test_name_length,
                overall_label="IOPS:",
                overall_label_length=overall_label_length,
                overall=format_ops_tohuman(int(test_details["overall"]["iops"])),
                overall_length=overall_column_length,
                bandwidth_label="Mean:",
                bandwidth_label_length=bandwidth_label_length,
                bandwidth=format_bytes_tohuman(
                    int(float(test_details["bandwidth"]["mean"])) * 1024
                ),
                bandwidth_length=bandwidth_column_length,
                iops=format_ops_tohuman(int(float(test_details["iops"]["mean"]))),
                iops_length=iops_column_length,
                latency=test_details["latency"]["mean"],
                latency_length=latency_column_length,
                cpuutil_label="CtxSw:",
                cpuutil_label_length=cpuutil_label_length,
                cpuutil=test_details["cpu"]["ctxsw"],
                cpuutil_length=cpuutil_column_length,
            )
        )
        # Fifth row (blank, Runtime, StdDev, MajFault))
        ainformation.append(
            "{bold}\
{test_name: <{test_name_length}} \
{overall_label: >{overall_label_length}} \
{overall: <{overall_length}} \
{bandwidth_label: >{bandwidth_label_length}} \
{bandwidth: <{bandwidth_length}} \
{iops: <{iops_length}} \
{latency: <{latency_length}} \
{cpuutil_label: >{cpuutil_label_length}} \
{cpuutil: <{cpuutil_length}} \
{end_bold}".format(
                bold="",
                end_bold="",
                test_name="",
                test_name_length=test_name_length,
                overall_label="Runtime (s):",
                overall_label_length=overall_label_length,
                overall=int(test_details["overall"]["runtime"]) / 1000.0,
                overall_length=overall_column_length,
                bandwidth_label="StdDev:",
                bandwidth_label_length=bandwidth_label_length,
                bandwidth=format_bytes_tohuman(
                    int(float(test_details["bandwidth"]["stdev"])) * 1024
                ),
                bandwidth_length=bandwidth_column_length,
                iops=format_ops_tohuman(int(float(test_details["iops"]["stdev"]))),
                iops_length=iops_column_length,
                latency=test_details["latency"]["stdev"],
                latency_length=latency_column_length,
                cpuutil_label="MajFault:",
                cpuutil_label_length=cpuutil_label_length,
                cpuutil=test_details["cpu"]["majfault"],
                cpuutil_length=cpuutil_column_length,
            )
        )
        # Sixth row (blank, blank, Samples, MinFault))
        ainformation.append(
            "{bold}\
{test_name: <{test_name_length}} \
{overall_label: >{overall_label_length}} \
{overall: <{overall_length}} \
{bandwidth_label: >{bandwidth_label_length}} \
{bandwidth: <{bandwidth_length}} \
{iops: <{iops_length}} \
{latency: <{latency_length}} \
{cpuutil_label: >{cpuutil_label_length}} \
{cpuutil: <{cpuutil_length}} \
{end_bold}".format(
                bold="",
                end_bold="",
                test_name="",
                test_name_length=test_name_length,
                overall_label="",
                overall_label_length=overall_label_length,
                overall="",
                overall_length=overall_column_length,
                bandwidth_label="Samples:",
                bandwidth_label_length=bandwidth_label_length,
                bandwidth=test_details["bandwidth"]["numsamples"],
                bandwidth_length=bandwidth_column_length,
                iops=test_details["iops"]["numsamples"],
                iops_length=iops_column_length,
                latency="",
                latency_length=latency_column_length,
                cpuutil_label="MinFault:",
                cpuutil_label_length=cpuutil_label_length,
                cpuutil=test_details["cpu"]["minfault"],
                cpuutil_length=cpuutil_column_length,
            )
        )

        ainformation.append("")

    return "\n".join(ainformation)


def format_info_benchmark_json(config, benchmark_information):
    if benchmark_information["benchmark_result"] == "Running":
        return "Benchmark test is still running."

    benchmark_format = benchmark_information["test_format"]
    benchmark_details = benchmark_information["benchmark_result"]

    # Format a nice output; do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append(
        "{}Storage Benchmark details (format {}):{}".format(
            ansiprint.bold(), benchmark_format, ansiprint.end()
        )
    )

    nice_test_name_map = {
        "seq_read": "Sequential Read (4M blocks, queue depth 64)",
        "seq_write": "Sequential Write (4M blocks, queue depth 64)",
        "rand_read_4M": "Random Read (4M blocks, queue depth 64)",
        "rand_write_4M": "Random Write (4M blocks queue depth 64)",
        "rand_read_4K": "Random Read (4K blocks, queue depth 64)",
        "rand_write_4K": "Random Write (4K blocks, queue depth 64)",
        "rand_read_4K_lowdepth": "Random Read (4K blocks, queue depth 1)",
        "rand_write_4K_lowdepth": "Random Write (4K blocks, queue depth 1)",
    }

    for test in benchmark_details:
        ainformation.append("")

        io_class = None
        for _io_class in ["read", "write"]:
            if benchmark_details[test]["jobs"][0][_io_class]["io_bytes"] > 0:
                io_class = _io_class
        if io_class is None:
            continue

        job_details = benchmark_details[test]["jobs"][0]

        # Calculate the unified latency categories (in us)
        latency_tree = list()
        for field in job_details["latency_ns"]:
            bucket = str(int(field) / 1000)
            latency_tree.append((bucket, job_details["latency_ns"][field]))
        for field in job_details["latency_us"]:
            bucket = field
            latency_tree.append((bucket, job_details["latency_us"][field]))
        for field in job_details["latency_ms"]:
            # That one annoying one
            if field == ">=2000":
                bucket = ">=2000000"
            else:
                bucket = str(int(field) * 1000)
            latency_tree.append((bucket, job_details["latency_ms"][field]))

        # Find the minimum entry without a zero
        useful_latency_tree = list()
        for element in latency_tree:
            if element[1] != 0:
                useful_latency_tree.append(element)

        max_rows = 5
        if len(useful_latency_tree) > 9:
            max_rows = len(useful_latency_tree)
        elif len(useful_latency_tree) < 9:
            while len(useful_latency_tree) < 9:
                useful_latency_tree.append(("", ""))

        # Format the static data
        overall_label = [
            "BW/s:",
            "IOPS:",
            "I/O:",
            "Time:",
        ]
        while len(overall_label) < max_rows:
            overall_label.append("")

        overall_data = [
            format_bytes_tohuman(int(job_details[io_class]["bw_bytes"])),
            format_ops_tohuman(int(job_details[io_class]["iops"])),
            format_bytes_tohuman(int(job_details[io_class]["io_bytes"])),
            str(job_details["job_runtime"] / 1000) + "s",
        ]
        while len(overall_data) < max_rows:
            overall_data.append("")

        cpu_label = [
            "Total:",
            "User:",
            "Sys:",
            "OSD:",
            "MON:",
        ]
        while len(cpu_label) < max_rows:
            cpu_label.append("")

        cpu_data = [
            (
                benchmark_details[test]["avg_cpu_util_percent"]["total"]
                if benchmark_format > 1
                else "N/A"
            ),
            round(job_details["usr_cpu"], 2),
            round(job_details["sys_cpu"], 2),
            (
                benchmark_details[test]["avg_cpu_util_percent"]["ceph-osd"]
                if benchmark_format > 1
                else "N/A"
            ),
            (
                benchmark_details[test]["avg_cpu_util_percent"]["ceph-mon"]
                if benchmark_format > 1
                else "N/A"
            ),
        ]
        while len(cpu_data) < max_rows:
            cpu_data.append("")

        memory_label = [
            "Total:",
            "OSD:",
            "MON:",
        ]
        while len(memory_label) < max_rows:
            memory_label.append("")

        memory_data = [
            (
                benchmark_details[test]["avg_memory_util_percent"]["total"]
                if benchmark_format > 1
                else "N/A"
            ),
            (
                benchmark_details[test]["avg_memory_util_percent"]["ceph-osd"]
                if benchmark_format > 1
                else "N/A"
            ),
            (
                benchmark_details[test]["avg_memory_util_percent"]["ceph-mon"]
                if benchmark_format > 1
                else "N/A"
            ),
        ]
        while len(memory_data) < max_rows:
            memory_data.append("")

        network_label = [
            "Total:",
            "Sent:",
            "Recv:",
        ]
        while len(network_label) < max_rows:
            network_label.append("")

        network_data = [
            (
                format_bytes_tohuman(
                    int(benchmark_details[test]["avg_network_util_bps"]["total"])
                )
                if benchmark_format > 1
                else "N/A"
            ),
            (
                format_bytes_tohuman(
                    int(benchmark_details[test]["avg_network_util_bps"]["sent"])
                )
                if benchmark_format > 1
                else "N/A"
            ),
            (
                format_bytes_tohuman(
                    int(benchmark_details[test]["avg_network_util_bps"]["recv"])
                )
                if benchmark_format > 1
                else "N/A"
            ),
        ]
        while len(network_data) < max_rows:
            network_data.append("")

        bandwidth_label = [
            "Min:",
            "Max:",
            "Mean:",
            "StdDev:",
            "Samples:",
        ]
        while len(bandwidth_label) < max_rows:
            bandwidth_label.append("")

        bandwidth_data = [
            format_bytes_tohuman(int(job_details[io_class]["bw_min"]) * 1024)
            + " / "
            + format_ops_tohuman(int(job_details[io_class]["iops_min"])),
            format_bytes_tohuman(int(job_details[io_class]["bw_max"]) * 1024)
            + " / "
            + format_ops_tohuman(int(job_details[io_class]["iops_max"])),
            format_bytes_tohuman(int(job_details[io_class]["bw_mean"]) * 1024)
            + " / "
            + format_ops_tohuman(int(job_details[io_class]["iops_mean"])),
            format_bytes_tohuman(int(job_details[io_class]["bw_dev"]) * 1024)
            + " / "
            + format_ops_tohuman(int(job_details[io_class]["iops_stddev"])),
            str(job_details[io_class]["bw_samples"])
            + " / "
            + str(job_details[io_class]["iops_samples"]),
        ]
        while len(bandwidth_data) < max_rows:
            bandwidth_data.append("")

        lat_label = [
            "Min:",
            "Max:",
            "Mean:",
            "StdDev:",
        ]
        while len(lat_label) < max_rows:
            lat_label.append("")

        lat_data = [
            int(job_details[io_class]["lat_ns"]["min"]) / 1000,
            int(job_details[io_class]["lat_ns"]["max"]) / 1000,
            int(job_details[io_class]["lat_ns"]["mean"]) / 1000,
            int(job_details[io_class]["lat_ns"]["stddev"]) / 1000,
        ]
        while len(lat_data) < max_rows:
            lat_data.append("")

        # Format the dynamic buckets
        lat_bucket_label = list()
        lat_bucket_data = list()
        for element in useful_latency_tree:
            lat_bucket_label.append(element[0] + ":" if element[0] else "")
            lat_bucket_data.append(round(float(element[1]), 2) if element[1] else "")
        while len(lat_bucket_label) < max_rows:
            lat_bucket_label.append("")
        while len(lat_bucket_data) < max_rows:
            lat_bucket_label.append("")

        # Column default widths
        overall_label_length = 5
        overall_column_length = 0
        cpu_label_length = 6
        cpu_column_length = 0
        memory_label_length = 6
        memory_column_length = 0
        network_label_length = 6
        network_column_length = 6
        bandwidth_label_length = 8
        bandwidth_column_length = 0
        latency_label_length = 7
        latency_column_length = 0
        latency_bucket_label_length = 0
        latency_bucket_column_length = 0

        # Column layout:
        #    Overall    CPU   Memory  Network  Bandwidth/IOPS  Latency   Percentiles
        #    ---------  ----- ------- -------- --------------  --------  ---------------
        #    BW         Total Total   Total    Min             Min       A
        #    IOPS       Usr   OSD     Send     Max             Max       B
        #    Time       Sys   MON     Recv     Mean            Mean      ...
        #    Size       OSD                    StdDev          StdDev    Z
        #               MON                    Samples

        # Set column widths
        for item in overall_data:
            _item_length = len(str(item))
            if _item_length > overall_column_length:
                overall_column_length = _item_length

        for item in cpu_data:
            _item_length = len(str(item))
            if _item_length > cpu_column_length:
                cpu_column_length = _item_length

        for item in memory_data:
            _item_length = len(str(item))
            if _item_length > memory_column_length:
                memory_column_length = _item_length

        for item in network_data:
            _item_length = len(str(item))
            if _item_length > network_column_length:
                network_column_length = _item_length

        for item in bandwidth_data:
            _item_length = len(str(item))
            if _item_length > bandwidth_column_length:
                bandwidth_column_length = _item_length

        for item in lat_data:
            _item_length = len(str(item))
            if _item_length > latency_column_length:
                latency_column_length = _item_length

        for item in lat_bucket_data:
            _item_length = len(str(item))
            if _item_length > latency_bucket_column_length:
                latency_bucket_column_length = _item_length

        # Top row (Headers)
        ainformation.append(
            "{bold}{overall_label: <{overall_label_length}} {header_fill}{end_bold}".format(
                bold=ansiprint.bold(),
                end_bold=ansiprint.end(),
                overall_label=nice_test_name_map[test],
                overall_label_length=overall_label_length,
                header_fill="-"
                * (
                    (MAX_CONTENT_WIDTH if MAX_CONTENT_WIDTH <= 120 else 120)
                    - len(nice_test_name_map[test])
                    - 4
                ),
            )
        )

        ainformation.append(
            "{bold}\
{overall_label: <{overall_label_length}}  \
{cpu_label: <{cpu_label_length}}  \
{memory_label: <{memory_label_length}}  \
{network_label: <{network_label_length}}  \
{bandwidth_label: <{bandwidth_label_length}}  \
{latency_label: <{latency_label_length}}  \
{latency_bucket_label: <{latency_bucket_label_length}}\
{end_bold}".format(
                bold=ansiprint.bold(),
                end_bold=ansiprint.end(),
                overall_label="Overall",
                overall_label_length=overall_label_length + overall_column_length + 1,
                cpu_label="CPU (%)",
                cpu_label_length=cpu_label_length + cpu_column_length + 1,
                memory_label="Memory (%)",
                memory_label_length=memory_label_length + memory_column_length + 1,
                network_label="Network (bps)",
                network_label_length=network_label_length + network_column_length + 1,
                bandwidth_label="Bandwidth / IOPS",
                bandwidth_label_length=bandwidth_label_length
                + bandwidth_column_length
                + 1,
                latency_label="Latency (μs)",
                latency_label_length=latency_label_length + latency_column_length + 1,
                latency_bucket_label="Buckets (μs/%)",
                latency_bucket_label_length=latency_bucket_label_length
                + latency_bucket_column_length,
            )
        )

        for idx in range(0, max_rows):
            # Top row (Headers)
            ainformation.append(
                "{bold}\
{overall_label: <{overall_label_length}} \
{overall: <{overall_length}}  \
{cpu_label: <{cpu_label_length}} \
{cpu: <{cpu_length}}  \
{memory_label: <{memory_label_length}} \
{memory: <{memory_length}}  \
{network_label: <{network_label_length}} \
{network: <{network_length}}  \
{bandwidth_label: <{bandwidth_label_length}} \
{bandwidth: <{bandwidth_length}}  \
{latency_label: <{latency_label_length}} \
{latency: <{latency_length}}  \
{latency_bucket_label: <{latency_bucket_label_length}} \
{latency_bucket}\
{end_bold}".format(
                    bold="",
                    end_bold="",
                    overall_label=overall_label[idx],
                    overall_label_length=overall_label_length,
                    overall=overall_data[idx],
                    overall_length=overall_column_length,
                    cpu_label=cpu_label[idx],
                    cpu_label_length=cpu_label_length,
                    cpu=cpu_data[idx],
                    cpu_length=cpu_column_length,
                    memory_label=memory_label[idx],
                    memory_label_length=memory_label_length,
                    memory=memory_data[idx],
                    memory_length=memory_column_length,
                    network_label=network_label[idx],
                    network_label_length=network_label_length,
                    network=network_data[idx],
                    network_length=network_column_length,
                    bandwidth_label=bandwidth_label[idx],
                    bandwidth_label_length=bandwidth_label_length,
                    bandwidth=bandwidth_data[idx],
                    bandwidth_length=bandwidth_column_length,
                    latency_label=lat_label[idx],
                    latency_label_length=latency_label_length,
                    latency=lat_data[idx],
                    latency_length=latency_column_length,
                    latency_bucket_label=lat_bucket_label[idx],
                    latency_bucket_label_length=latency_bucket_label_length,
                    latency_bucket=lat_bucket_data[idx],
                )
            )

    return "\n".join(ainformation) + "\n"
