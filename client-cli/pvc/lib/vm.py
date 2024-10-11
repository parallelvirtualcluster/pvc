#!/usr/bin/env python3

# vm.py - PVC CLI client function library, VM functions
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

import pvc.lib.ansiprint as ansiprint
from pvc.lib.common import call_api, format_bytes, format_metric, get_wait_retdata


#
# Primary functions
#
def vm_info(config, vm):
    """
    Get information about (single) VM

    API endpoint: GET /api/v1/vm/{vm}
    API arguments:
    API schema: {json_data_object}
    """
    response = call_api(config, "get", "/vm/{vm}".format(vm=vm))

    if response.status_code == 200:
        if isinstance(response.json(), list) and len(response.json()) != 1:
            # No exact match; return not found
            return False, "VM not found."
        else:
            # Return a single instance if the response is a list
            if isinstance(response.json(), list):
                return True, response.json()[0]
            # This shouldn't happen, but is here just in case
            else:
                return True, response.json()
    else:
        return False, response.json().get("message", "")


def vm_list(config, limit, target_node, target_state, target_tag, negate):
    """
    Get list information about VMs (limited by {limit}, {target_node}, or {target_state})

    API endpoint: GET /api/v1/vm
    API arguments: limit={limit}, node={target_node}, state={target_state}, tag={target_tag}, negate={negate}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    if limit:
        params["limit"] = limit
    if target_node:
        params["node"] = target_node
    if target_state:
        params["state"] = target_state
    if target_tag:
        params["tag"] = target_tag
    params["negate"] = negate

    response = call_api(config, "get", "/vm", params=params)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json().get("message", "")


def vm_define(
    config,
    xml,
    node,
    node_limit,
    node_selector,
    node_autostart,
    migration_method,
    migration_max_downtime,
    user_tags,
    protected_tags,
):
    """
    Define a new VM on the cluster

    API endpoint: POST /vm
    API arguments: xml={xml}, node={node}, limit={node_limit}, selector={node_selector}, autostart={node_autostart}, migration_method={migration_method}, migration_max_downtime={migration_max_downtime}, user_tags={user_tags}, protected_tags={protected_tags}
    API schema: {"message":"{data}"}
    """
    params = {
        "node": node,
        "limit": node_limit,
        "selector": node_selector,
        "autostart": node_autostart,
        "migration_method": migration_method,
        "migration_max_downtime": migration_max_downtime,
        "user_tags": user_tags,
        "protected_tags": protected_tags,
    }
    data = {"xml": xml}
    response = call_api(config, "post", "/vm", params=params, data=data)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def vm_modify(config, vm, xml, restart):
    """
    Modify the configuration of VM

    API endpoint: PUT /vm/{vm}
    API arguments: xml={xml}, restart={restart}
    API schema: {"message":"{data}"}
    """
    params = {"restart": restart}
    data = {"xml": xml}
    response = call_api(
        config, "put", "/vm/{vm}".format(vm=vm), params=params, data=data
    )

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def vm_device_attach(config, vm, xml):
    """
    Attach a device to a VM

    API endpoint: POST /vm/{vm}/device
    API arguments: xml={xml}
    API schema: {"message":"{data}"}
    """
    data = {"xml": xml}
    response = call_api(config, "post", "/vm/{vm}/device".format(vm=vm), data=data)

    if response.status_code in [200, 202]:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def vm_device_detach(config, vm, xml):
    """
    Detach a device from a VM

    API endpoint: DELETE /vm/{vm}/device
    API arguments: xml={xml}
    API schema: {"message":"{data}"}
    """
    data = {"xml": xml}
    response = call_api(config, "delete", "/vm/{vm}/device".format(vm=vm), data=data)

    if response.status_code in [200, 202]:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def vm_rename(config, vm, new_name):
    """
    Rename VM to new name

    API endpoint: POST /vm/{vm}/rename
    API arguments: new_name={new_name}
    API schema: {"message":"{data}"}
    """
    params = {"new_name": new_name}
    response = call_api(config, "post", "/vm/{vm}/rename".format(vm=vm), params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def vm_metadata(
    config,
    vm,
    node_limit,
    node_selector,
    node_autostart,
    migration_method,
    migration_max_downtime,
    provisioner_profile,
):
    """
    Modify PVC metadata of a VM

    API endpoint: POST /vm/{vm}/meta
    API arguments: limit={node_limit}, selector={node_selector}, autostart={node_autostart}, migration_method={migration_method} profile={provisioner_profile}
    API schema: {"message":"{data}"}
    """
    params = dict()

    # Update any params that we've sent
    if node_limit is not None:
        params["limit"] = node_limit

    if node_selector is not None:
        params["selector"] = node_selector

    if node_autostart is not None:
        params["autostart"] = node_autostart

    if migration_method is not None:
        params["migration_method"] = migration_method

    if migration_max_downtime is not None:
        params["migration_max_downtime"] = migration_max_downtime

    if provisioner_profile is not None:
        params["profile"] = provisioner_profile

    # Write the new metadata
    response = call_api(config, "post", "/vm/{vm}/meta".format(vm=vm), params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def vm_tags_get(config, vm):
    """
    Get PVC tags of a VM

    API endpoint: GET /vm/{vm}/tags
    API arguments:
    API schema: {{"name": "{name}", "type": "{type}"},...}
    """

    response = call_api(config, "get", "/vm/{vm}/tags".format(vm=vm))

    if response.status_code == 200:
        retstatus = True
        retdata = response.json()
    else:
        retstatus = False
        retdata = response.json().get("message", "")

    return retstatus, retdata


def vm_tag_set(config, vm, action, tag, protected=False):
    """
    Modify PVC tags of a VM

    API endpoint: POST /vm/{vm}/tags
    API arguments: action={action}, tag={tag}, protected={protected}
    API schema: {"message":"{data}"}
    """

    params = {"action": action, "tag": tag, "protected": protected}

    # Update the tags
    response = call_api(config, "post", "/vm/{vm}/tags".format(vm=vm), params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def format_vm_tags(config, data):
    """
    Format the output of a tags dictionary in a nice table
    """

    tags = data.get("tags", [])

    if len(tags) < 1:
        return "No tags found."

    output_list = []

    tags_name_length = 4
    tags_type_length = 5
    tags_protected_length = 10
    for tag in tags:
        _tags_name_length = len(tag["name"]) + 1
        if _tags_name_length > tags_name_length:
            tags_name_length = _tags_name_length

        _tags_type_length = len(tag["type"]) + 1
        if _tags_type_length > tags_type_length:
            tags_type_length = _tags_type_length

        _tags_protected_length = len(str(tag["protected"])) + 1
        if _tags_protected_length > tags_protected_length:
            tags_protected_length = _tags_protected_length

    output_list.append(
        "{bold}{tags_name: <{tags_name_length}}  \
{tags_type: <{tags_type_length}}  \
{tags_protected: <{tags_protected_length}}{end_bold}".format(
            tags_name_length=tags_name_length,
            tags_type_length=tags_type_length,
            tags_protected_length=tags_protected_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            tags_name="Name",
            tags_type="Type",
            tags_protected="Protected",
        )
    )

    for tag in sorted(tags, key=lambda t: t["name"]):
        output_list.append(
            "{bold}{tags_name: <{tags_name_length}}  \
{tags_type: <{tags_type_length}}  \
{tags_protected: <{tags_protected_length}}{end_bold}".format(
                tags_type_length=tags_type_length,
                tags_name_length=tags_name_length,
                tags_protected_length=tags_protected_length,
                bold="",
                end_bold="",
                tags_name=tag["name"],
                tags_type=tag["type"],
                tags_protected=str(tag["protected"]),
            )
        )

    return "\n".join(output_list)


def vm_remove(config, vm, delete_disks=False):
    """
    Remove a VM

    API endpoint: DELETE /vm/{vm}
    API arguments: delete_disks={delete_disks}
    API schema: {"message":"{data}"}
    """
    params = {"delete_disks": delete_disks}
    response = call_api(config, "delete", "/vm/{vm}".format(vm=vm), params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def vm_state(config, vm, target_state, force=False, wait=False):
    """
    Modify the current state of VM

    API endpoint: POST /vm/{vm}/state
    API arguments: state={state}, wait={wait}
    API schema: {"message":"{data}"}
    """
    params = {
        "state": target_state,
        "force": force,
        "wait": wait,
    }
    response = call_api(config, "post", "/vm/{vm}/state".format(vm=vm), params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def vm_node(config, vm, target_node, action, force=False, wait=False, force_live=False):
    """
    Modify the current node of VM via {action}

    API endpoint: POST /vm/{vm}/node
    API arguments: node={target_node}, action={action}, force={force}, wait={wait}, force_live={force_live}
    API schema: {"message":"{data}"}
    """
    params = {
        "node": target_node,
        "action": action,
        "force": str(force).lower(),
        "wait": str(wait).lower(),
        "force_live": str(force_live).lower(),
    }
    response = call_api(config, "post", "/vm/{vm}/node".format(vm=vm), params=params)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json().get("message", "")


def vm_locks(config, vm, wait_flag=True):
    """
    Flush RBD locks of (stopped) VM

    API endpoint: POST /vm/{vm}/locks
    API arguments:
    API schema: {"message":"{data}"}
    """
    response = call_api(config, "post", f"/vm/{vm}/locks")

    return get_wait_retdata(response, wait_flag)


def vm_backup(config, vm, backup_path, incremental_parent=None, retain_snapshot=False):
    """
    Create a backup of {vm} and its volumes to a local primary coordinator filesystem path

    API endpoint: POST /vm/{vm}/backup
    API arguments: backup_path={backup_path}, incremental_parent={incremental_parent}, retain_snapshot={retain_snapshot}
    API schema: {"message":"{data}"}
    """
    params = {
        "backup_path": backup_path,
        "incremental_parent": incremental_parent,
        "retain_snapshot": retain_snapshot,
    }
    response = call_api(config, "post", "/vm/{vm}/backup".format(vm=vm), params=params)

    if response.status_code != 200:
        return False, response.json().get("message", "")
    else:
        return True, response.json().get("message", "")


def vm_remove_backup(config, vm, backup_path, backup_datestring):
    """
    Remove a backup of {vm}, including snapshots, from a local primary coordinator filesystem path

    API endpoint: DELETE /vm/{vm}/backup
    API arguments: backup_path={backup_path}, backup_datestring={backup_datestring}
    API schema: {"message":"{data}"}
    """
    params = {
        "backup_path": backup_path,
        "backup_datestring": backup_datestring,
    }
    response = call_api(
        config, "delete", "/vm/{vm}/backup".format(vm=vm), params=params
    )

    if response.status_code != 200:
        return False, response.json().get("message", "")
    else:
        return True, response.json().get("message", "")


def vm_restore(config, vm, backup_path, backup_datestring, retain_snapshot=False):
    """
    Restore a backup of {vm} and its volumes from a local primary coordinator filesystem path

    API endpoint: POST /vm/{vm}/restore
    API arguments: backup_path={backup_path}, backup_datestring={backup_datestring}, retain_snapshot={retain_snapshot}
    API schema: {"message":"{data}"}
    """
    params = {
        "backup_path": backup_path,
        "backup_datestring": backup_datestring,
        "retain_snapshot": retain_snapshot,
    }
    response = call_api(config, "post", "/vm/{vm}/restore".format(vm=vm), params=params)

    if response.status_code != 200:
        return False, response.json().get("message", "")
    else:
        return True, response.json().get("message", "")


def vm_create_snapshot(config, vm, snapshot_name=None, wait_flag=True):
    """
    Take a snapshot of a VM's disks and configuration

    API endpoint: POST /vm/{vm}/snapshot
    API arguments: snapshot_name=snapshot_name
    API schema: {"message":"{data}"}
    """
    params = dict()
    if snapshot_name is not None:
        params["snapshot_name"] = snapshot_name
    response = call_api(
        config, "post", "/vm/{vm}/snapshot".format(vm=vm), params=params
    )

    return get_wait_retdata(response, wait_flag)


def vm_remove_snapshot(config, vm, snapshot_name, wait_flag=True):
    """
    Remove a snapshot of a VM's disks and configuration

    API endpoint: DELETE /vm/{vm}/snapshot
    API arguments: snapshot_name=snapshot_name
    API schema: {"message":"{data}"}
    """
    params = {"snapshot_name": snapshot_name}
    response = call_api(
        config, "delete", "/vm/{vm}/snapshot".format(vm=vm), params=params
    )

    return get_wait_retdata(response, wait_flag)


def vm_rollback_snapshot(config, vm, snapshot_name, wait_flag=True):
    """
    Roll back to a snapshot of a VM's disks and configuration

    API endpoint: POST /vm/{vm}/snapshot/rollback
    API arguments: snapshot_name=snapshot_name
    API schema: {"message":"{data}"}
    """
    params = {"snapshot_name": snapshot_name}
    response = call_api(
        config, "post", "/vm/{vm}/snapshot/rollback".format(vm=vm), params=params
    )

    return get_wait_retdata(response, wait_flag)


def vm_export_snapshot(
    config, vm, snapshot_name, export_path, incremental_parent=None, wait_flag=True
):
    """
    Export an (existing) snapshot of a VM's disks and configuration to export_path, optionally
    incremental with incremental_parent

    API endpoint: POST /vm/{vm}/snapshot/export
    API arguments: snapshot_name=snapshot_name, export_path=export_path, incremental_parent=incremental_parent
    API schema: {"message":"{data}"}
    """
    params = {
        "snapshot_name": snapshot_name,
        "export_path": export_path,
    }
    if incremental_parent is not None:
        params["incremental_parent"] = incremental_parent

    response = call_api(
        config, "post", "/vm/{vm}/snapshot/export".format(vm=vm), params=params
    )

    return get_wait_retdata(response, wait_flag)


def vm_import_snapshot(
    config, vm, snapshot_name, import_path, retain_snapshot=False, wait_flag=True
):
    """
    Import a snapshot of {vm} and its volumes from a local primary coordinator filesystem path

    API endpoint: POST /vm/{vm}/snapshot/import
    API arguments: snapshot_name={snapshot_name}, import_path={import_path}, retain_snapshot={retain_snapshot}
    API schema: {"message":"{data}"}
    """
    params = {
        "snapshot_name": snapshot_name,
        "import_path": import_path,
        "retain_snapshot": retain_snapshot,
    }
    response = call_api(
        config, "post", "/vm/{vm}/snapshot/import".format(vm=vm), params=params
    )

    return get_wait_retdata(response, wait_flag)


def vm_send_snapshot(
    config,
    vm,
    snapshot_name,
    destination_api_uri,
    destination_api_key,
    destination_api_verify_ssl=True,
    destination_storage_pool=None,
    incremental_parent=None,
    wait_flag=True,
):
    """
    Send an (existing) snapshot of a VM's disks and configuration to a destination PVC cluster, optionally
    incremental with incremental_parent

    API endpoint: POST /vm/{vm}/snapshot/send
    API arguments: snapshot_name=snapshot_name, destination_api_uri=destination_api_uri, destination_api_key=destination_api_key, destination_api_verify_ssl=destination_api_verify_ssl, incremental_parent=incremental_parent, destination_storage_pool=destination_storage_pool
    API schema: {"message":"{data}"}
    """
    params = {
        "snapshot_name": snapshot_name,
        "destination_api_uri": destination_api_uri,
        "destination_api_key": destination_api_key,
        "destination_api_verify_ssl": destination_api_verify_ssl,
    }
    if destination_storage_pool is not None:
        params["destination_storage_pool"] = destination_storage_pool
    if incremental_parent is not None:
        params["incremental_parent"] = incremental_parent

    response = call_api(
        config, "post", "/vm/{vm}/snapshot/send".format(vm=vm), params=params
    )

    return get_wait_retdata(response, wait_flag)


def vm_create_mirror(
    config,
    vm,
    destination_api_uri,
    destination_api_key,
    destination_api_verify_ssl=True,
    destination_storage_pool=None,
    wait_flag=True,
):
    """
    Create a new snapshot and send the snapshot to a destination PVC cluster, with automatic incremental handling

    API endpoint: POST /vm/{vm}/mirror/create
    API arguments: destination_api_uri=destination_api_uri, destination_api_key=destination_api_key, destination_api_verify_ssl=destination_api_verify_ssl, destination_storage_pool=destination_storage_pool
    API schema: {"message":"{data}"}
    """
    params = {
        "destination_api_uri": destination_api_uri,
        "destination_api_key": destination_api_key,
        "destination_api_verify_ssl": destination_api_verify_ssl,
    }
    if destination_storage_pool is not None:
        params["destination_storage_pool"] = destination_storage_pool

    response = call_api(
        config, "post", "/vm/{vm}/mirror/create".format(vm=vm), params=params
    )

    return get_wait_retdata(response, wait_flag)


def vm_promote_mirror(
    config,
    vm,
    destination_api_uri,
    destination_api_key,
    destination_api_verify_ssl=True,
    destination_storage_pool=None,
    remove_on_source=False,
    wait_flag=True,
):
    """
    Shut down a VM, create a new snapshot, send the snapshot to a destination PVC cluster, start the VM on the remote cluster, and optionally remove the local VM, with automatic incremental handling

    API endpoint: POST /vm/{vm}/mirror/promote
    API arguments: destination_api_uri=destination_api_uri, destination_api_key=destination_api_key, destination_api_verify_ssl=destination_api_verify_ssl, destination_storage_pool=destination_storage_pool, remove_on_source=remove_on_source
    API schema: {"message":"{data}"}
    """
    params = {
        "destination_api_uri": destination_api_uri,
        "destination_api_key": destination_api_key,
        "destination_api_verify_ssl": destination_api_verify_ssl,
        "remove_on_source": remove_on_source,
    }
    if destination_storage_pool is not None:
        params["destination_storage_pool"] = destination_storage_pool

    response = call_api(
        config, "post", "/vm/{vm}/mirror/promote".format(vm=vm), params=params
    )

    return get_wait_retdata(response, wait_flag)


def vm_autobackup(config, email_recipients=None, force_full_flag=False, wait_flag=True):
    """
    Perform a cluster VM autobackup

    API endpoint: POST /vm//autobackup
    API arguments: email_recipients=email_recipients, force_full_flag=force_full_flag
    API schema: {"message":"{data}"}
    """
    params = {
        "email_recipients": email_recipients,
        "force_full": force_full_flag,
    }

    response = call_api(config, "post", "/vm/autobackup", params=params)

    return get_wait_retdata(response, wait_flag)


def vm_vcpus_set(config, vm, vcpus, topology, restart):
    """
    Set the vCPU count of the VM with topology

    Calls vm_info to get the VM XML.

    Calls vm_modify to set the VM XML.
    """
    from lxml.objectify import fromstring
    from lxml.etree import tostring

    status, domain_information = vm_info(config, vm)
    if not status:
        return status, domain_information

    xml = domain_information.get("xml", None)
    if xml is None:
        return False, "VM does not have a valid XML doccument."

    try:
        parsed_xml = fromstring(xml)
    except Exception:
        return False, "ERROR: Failed to parse XML data."

    parsed_xml.vcpu._setText(str(vcpus))
    parsed_xml.cpu.topology.set("sockets", str(topology[0]))
    parsed_xml.cpu.topology.set("cores", str(topology[1]))
    parsed_xml.cpu.topology.set("threads", str(topology[2]))

    try:
        new_xml = tostring(parsed_xml, pretty_print=True)
    except Exception:
        return False, "ERROR: Failed to dump XML data."

    return vm_modify(config, vm, new_xml, restart)


def vm_vcpus_get(config, vm):
    """
    Get the vCPU count of the VM

    Calls vm_info to get VM XML.

    Returns a tuple of (vcpus, (sockets, cores, threads))
    """
    from lxml.objectify import fromstring

    status, domain_information = vm_info(config, vm)
    if not status:
        return status, domain_information

    xml = domain_information.get("xml", None)
    if xml is None:
        return False, "VM does not have a valid XML doccument."

    try:
        parsed_xml = fromstring(xml)
    except Exception:
        return False, "ERROR: Failed to parse XML data."

    data = dict()
    data["name"] = vm
    data["vcpus"] = int(parsed_xml.vcpu.text)
    data["sockets"] = parsed_xml.cpu.topology.attrib.get("sockets")
    data["cores"] = parsed_xml.cpu.topology.attrib.get("cores")
    data["threads"] = parsed_xml.cpu.topology.attrib.get("threads")

    return True, data


def format_vm_vcpus(config, data):
    """
    Format the output of a vCPU value in a nice table
    """
    output_list = []

    vcpus_length = 6
    sockets_length = 8
    cores_length = 6
    threads_length = 8

    output_list.append(
        "{bold}{vcpus: <{vcpus_length}}  \
{sockets: <{sockets_length}} \
{cores: <{cores_length}} \
{threads: <{threads_length}}{end_bold}".format(
            vcpus_length=vcpus_length,
            sockets_length=sockets_length,
            cores_length=cores_length,
            threads_length=threads_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            vcpus="vCPUs",
            sockets="Sockets",
            cores="Cores",
            threads="Threads",
        )
    )
    output_list.append(
        "{bold}{vcpus: <{vcpus_length}}  \
{sockets: <{sockets_length}} \
{cores: <{cores_length}} \
{threads: <{threads_length}}{end_bold}".format(
            vcpus_length=vcpus_length,
            sockets_length=sockets_length,
            cores_length=cores_length,
            threads_length=threads_length,
            bold="",
            end_bold="",
            vcpus=data["vcpus"],
            sockets=data["sockets"],
            cores=data["cores"],
            threads=data["threads"],
        )
    )
    return "\n".join(output_list)


def vm_memory_set(config, vm, memory, restart):
    """
    Set the provisioned memory of the VM with topology

    Calls vm_info to get the VM XML.

    Calls vm_modify to set the VM XML.
    """
    from lxml.objectify import fromstring
    from lxml.etree import tostring

    status, domain_information = vm_info(config, vm)
    if not status:
        return status, domain_information

    xml = domain_information.get("xml", None)
    if xml is None:
        return False, "VM does not have a valid XML doccument."

    try:
        parsed_xml = fromstring(xml)
    except Exception:
        return False, "ERROR: Failed to parse XML data."

    parsed_xml.memory._setText(str(memory))

    try:
        new_xml = tostring(parsed_xml, pretty_print=True)
    except Exception:
        return False, "ERROR: Failed to dump XML data."

    return vm_modify(config, vm, new_xml, restart)


def vm_memory_get(config, vm):
    """
    Get the provisioned memory of the VM

    Calls vm_info to get VM XML.

    Returns an integer memory value.
    """
    from lxml.objectify import fromstring

    status, domain_information = vm_info(config, vm)
    if not status:
        return status, domain_information

    xml = domain_information.get("xml", None)
    if xml is None:
        return False, "VM does not have a valid XML doccument."

    try:
        parsed_xml = fromstring(xml)
    except Exception:
        return False, "ERROR: Failed to parse XML data."

    data = dict()
    data["name"] = vm
    data["memory"] = int(parsed_xml.memory.text)

    return True, data


def format_vm_memory(config, data):
    """
    Format the output of a memory value in a nice table
    """
    output_list = []

    memory_length = 6

    output_list.append(
        "{bold}{memory: <{memory_length}}{end_bold}".format(
            memory_length=memory_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            memory="RAM (M)",
        )
    )
    output_list.append(
        "{bold}{memory: <{memory_length}}{end_bold}".format(
            memory_length=memory_length,
            bold="",
            end_bold="",
            memory=data["memory"],
        )
    )
    return "\n".join(output_list)


def vm_networks_add(
    config, vm, network, macaddr, model, sriov, sriov_mode, live, restart
):
    """
    Add a new network to the VM

    Calls vm_info to get the VM XML.

    Calls vm_modify to set the VM XML.

    Calls vm_device_attach if live to hot-attach the device.
    """
    from lxml.objectify import fromstring
    from lxml.etree import tostring
    from random import randint
    import pvc.lib.network as pvc_network

    network_exists, _ = pvc_network.net_info(config, network)
    if not network_exists:
        return False, "Network {} not found on the cluster.".format(network)

    status, domain_information = vm_info(config, vm)
    if not status:
        return status, domain_information

    xml = domain_information.get("xml", None)
    if xml is None:
        return False, "VM does not have a valid XML doccument."

    try:
        parsed_xml = fromstring(xml)
    except Exception:
        return False, "ERROR: Failed to parse XML data."

    if macaddr is None:
        mac_prefix = "52:54:00"
        random_octet_A = "{:x}".format(randint(16, 238))
        random_octet_B = "{:x}".format(randint(16, 238))
        random_octet_C = "{:x}".format(randint(16, 238))
        macaddr = "{prefix}:{octetA}:{octetB}:{octetC}".format(
            prefix=mac_prefix,
            octetA=random_octet_A,
            octetB=random_octet_B,
            octetC=random_octet_C,
        )

    # Add an SR-IOV network
    if sriov:
        valid, sriov_vf_information = pvc_network.net_sriov_vf_info(
            config, domain_information["node"], network
        )
        if not valid:
            return (
                False,
                'Specified SR-IOV VF "{}" does not exist on VM node "{}".'.format(
                    network, domain_information["node"]
                ),
            )

        # Add a hostdev (direct PCIe) SR-IOV network
        if sriov_mode == "hostdev":
            bus_address = 'domain="0x{pci_domain}" bus="0x{pci_bus}" slot="0x{pci_slot}" function="0x{pci_function}"'.format(
                pci_domain=sriov_vf_information["pci"]["domain"],
                pci_bus=sriov_vf_information["pci"]["bus"],
                pci_slot=sriov_vf_information["pci"]["slot"],
                pci_function=sriov_vf_information["pci"]["function"],
            )
            device_string = '<interface type="hostdev" managed="yes"><mac address="{macaddr}"/><source><address type="pci" {bus_address}/></source><sriov_device>{network}</sriov_device></interface>'.format(
                macaddr=macaddr, bus_address=bus_address, network=network
            )
        # Add a macvtap SR-IOV network
        elif sriov_mode == "macvtap":
            device_string = '<interface type="direct"><mac address="{macaddr}"/><source dev="{network}" mode="passthrough"/><model type="{model}"/></interface>'.format(
                macaddr=macaddr, network=network, model=model
            )
        else:
            return False, "ERROR: Invalid SR-IOV mode specified."
    # Add a normal bridged PVC network
    else:
        # Set the bridge prefix
        if network in ["upstream", "cluster", "storage"]:
            br_prefix = "br"
        else:
            br_prefix = "vmbr"

        device_string = '<interface type="bridge"><mac address="{macaddr}"/><source bridge="{bridge}"/><model type="{model}"/></interface>'.format(
            macaddr=macaddr, bridge="{}{}".format(br_prefix, network), model=model
        )

    device_xml = fromstring(device_string)

    all_interfaces = parsed_xml.devices.find("interface")
    if all_interfaces is None:
        all_interfaces = []
    for interface in all_interfaces:
        if sriov:
            if sriov_mode == "hostdev":
                if interface.attrib.get("type") == "hostdev":
                    interface_address = 'domain="{pci_domain}" bus="{pci_bus}" slot="{pci_slot}" function="{pci_function}"'.format(
                        pci_domain=interface.source.address.attrib.get("domain"),
                        pci_bus=interface.source.address.attrib.get("bus"),
                        pci_slot=interface.source.address.attrib.get("slot"),
                        pci_function=interface.source.address.attrib.get("function"),
                    )
                    if interface_address == bus_address:
                        return (
                            False,
                            'SR-IOV device "{}" is already configured for VM "{}".'.format(
                                network, vm
                            ),
                        )
            elif sriov_mode == "macvtap":
                if interface.attrib.get("type") == "direct":
                    interface_dev = interface.source.attrib.get("dev")
                    if interface_dev == network:
                        return (
                            False,
                            'SR-IOV device "{}" is already configured for VM "{}".'.format(
                                network, vm
                            ),
                        )

    # Add the interface at the end of the list (or, right above emulator)
    if len(all_interfaces) > 0:
        for idx, interface in enumerate(parsed_xml.devices.find("interface")):
            if idx == len(all_interfaces) - 1:
                interface.addnext(device_xml)
    else:
        parsed_xml.devices.find("emulator").addprevious(device_xml)

    try:
        new_xml = tostring(parsed_xml, pretty_print=True)
    except Exception:
        return False, "ERROR: Failed to dump XML data."

    modify_retcode, modify_retmsg = vm_modify(config, vm, new_xml, restart)

    if not modify_retcode:
        return modify_retcode, modify_retmsg

    if live:
        attach_retcode, attach_retmsg = vm_device_attach(config, vm, device_string)

        if not attach_retcode:
            retcode = attach_retcode
            retmsg = attach_retmsg
        else:
            retcode = attach_retcode
            retmsg = "Network '{}' successfully added to VM config and hot attached to running VM.".format(
                network
            )
    else:
        retcode = modify_retcode
        retmsg = modify_retmsg

    return retcode, retmsg


def vm_networks_remove(config, vm, network, macaddr, sriov, live, restart):
    """
    Remove a network from the VM, optionally by MAC

    Calls vm_info to get the VM XML.

    Calls vm_modify to set the VM XML.

    Calls vm_device_detach to hot-remove the device.
    """
    from lxml.objectify import fromstring
    from lxml.etree import tostring

    if network is None and macaddr is None:
        return False, "A network or MAC address must be specified for removal."

    status, domain_information = vm_info(config, vm)
    if not status:
        return status, domain_information

    xml = domain_information.get("xml", None)
    if xml is None:
        return False, "VM does not have a valid XML doccument."

    try:
        parsed_xml = fromstring(xml)
    except Exception:
        return False, "ERROR: Failed to parse XML data."

    changed = False
    device_string = None
    for interface in parsed_xml.devices.find("interface"):
        if sriov:
            if interface.attrib.get("type") == "hostdev":
                if_dev = str(interface.sriov_device)
                if macaddr is None and network == if_dev:
                    interface.getparent().remove(interface)
                    changed = True
                elif macaddr is not None and macaddr == interface.mac.attrib.get(
                    "address"
                ):
                    interface.getparent().remove(interface)
                    changed = True
            elif interface.attrib.get("type") == "direct":
                if_dev = str(interface.source.attrib.get("dev"))
                if macaddr is None and network == if_dev:
                    interface.getparent().remove(interface)
                    changed = True
                elif macaddr is not None and macaddr == interface.mac.attrib.get(
                    "address"
                ):
                    interface.getparent().remove(interface)
                    changed = True
        else:
            if_vni = re.match(
                r"[vm]*br([0-9a-z]+)", interface.source.attrib.get("bridge")
            ).group(1)
            if macaddr is None and network == if_vni:
                interface.getparent().remove(interface)
                changed = True
            elif macaddr is not None and macaddr == interface.mac.attrib.get("address"):
                interface.getparent().remove(interface)
                changed = True
        if changed:
            device_string = tostring(interface)

    if changed:
        try:
            new_xml = tostring(parsed_xml, pretty_print=True)
        except Exception:
            return False, "ERROR: Failed to dump XML data."
    elif not changed and macaddr is not None:
        return False, 'ERROR: Interface with MAC "{}" does not exist on VM.'.format(
            macaddr
        )
    elif not changed and network is not None:
        return False, 'ERROR: Network "{}" does not exist on VM.'.format(network)
    else:
        return False, "ERROR: Unspecified error finding interface to remove."

    modify_retcode, modify_retmsg = vm_modify(config, vm, new_xml, restart)

    if not modify_retcode:
        return modify_retcode, modify_retmsg

    if live and device_string:
        detach_retcode, detach_retmsg = vm_device_detach(config, vm, device_string)

        if not detach_retcode:
            retcode = detach_retcode
            retmsg = detach_retmsg
        else:
            retcode = detach_retcode
            retmsg = "Network '{}' successfully removed from VM config and hot detached from running VM.".format(
                network
            )
    else:
        retcode = modify_retcode
        retmsg = modify_retmsg

    return retcode, retmsg


def vm_networks_get(config, vm):
    """
    Get the networks of the VM

    Calls vm_info to get VM XML.

    Returns a list of tuples of (network_vni, mac_address, model)
    """
    from lxml.objectify import fromstring

    status, domain_information = vm_info(config, vm)
    if not status:
        return status, domain_information

    xml = domain_information.get("xml", None)
    if xml is None:
        return False, "VM does not have a valid XML doccument."

    try:
        parsed_xml = fromstring(xml)
    except Exception:
        return False, "ERROR: Failed to parse XML data."

    data = dict()
    data["name"] = vm
    data["networks"] = list()
    for interface in parsed_xml.devices.find("interface"):
        mac_address = interface.mac.attrib.get("address")
        model = interface.model.attrib.get("type")
        interface_type = interface.attrib.get("type")
        if interface_type == "bridge":
            network = re.search(
                r"[vm]*br([0-9a-z]+)", interface.source.attrib.get("bridge")
            ).group(1)
        elif interface_type == "direct":
            network = "macvtap:{}".format(interface.source.attrib.get("dev"))
        elif interface_type == "hostdev":
            network = "hostdev:{}".format(interface.source.attrib.get("dev"))

        data["networks"].append(
            {"network": network, "mac_address": mac_address, "model": model}
        )

    return True, data


def format_vm_networks(config, data):
    """
    Format the output of a network list in a nice table
    """
    output_list = []

    network_length = 8
    macaddr_length = 12
    model_length = 6

    for network in data["networks"]:
        _network_length = len(network["network"]) + 1
        if _network_length > network_length:
            network_length = _network_length

        _macaddr_length = len(network["mac_address"]) + 1
        if _macaddr_length > macaddr_length:
            macaddr_length = _macaddr_length

        _model_length = len(network["model"]) + 1
        if _model_length > model_length:
            model_length = _model_length

    output_list.append(
        "{bold}{network: <{network_length}} \
{macaddr: <{macaddr_length}} \
{model: <{model_length}}{end_bold}".format(
            network_length=network_length,
            macaddr_length=macaddr_length,
            model_length=model_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            network="Network",
            macaddr="MAC Address",
            model="Model",
        )
    )
    count = 0
    for network in data["networks"]:
        count += 1
        output_list.append(
            "{bold}{network: <{network_length}} \
{macaddr: <{macaddr_length}} \
{model: <{model_length}}{end_bold}".format(
                network_length=network_length,
                macaddr_length=macaddr_length,
                model_length=model_length,
                bold="",
                end_bold="",
                network=network["network"],
                macaddr=network["mac_address"],
                model=network["model"],
            )
        )
    return "\n".join(output_list)


def vm_volumes_add(config, vm, volume, disk_id, bus, disk_type, live, restart):
    """
    Add a new volume to the VM

    Calls vm_info to get the VM XML.

    Calls vm_modify to set the VM XML.
    """
    from lxml.objectify import fromstring
    from lxml.etree import tostring
    from copy import deepcopy
    import pvc.lib.storage as pvc_storage

    if disk_type == "rbd":
        # Verify that the provided volume is valid
        vpool = volume.split("/")[0]
        vname = volume.split("/")[1]
        retcode, retdata = pvc_storage.ceph_volume_info(config, vpool, vname)
        if not retcode:
            return False, "Volume {} is not present in the cluster.".format(volume)

    status, domain_information = vm_info(config, vm)
    if not status:
        return status, domain_information

    xml = domain_information.get("xml", None)
    if xml is None:
        return False, "VM does not have a valid XML doccument."

    try:
        parsed_xml = fromstring(xml)
    except Exception:
        return False, "ERROR: Failed to parse XML data."

    last_disk = None
    id_list = list()
    all_disks = parsed_xml.devices.find("disk")
    if all_disks is None:
        all_disks = []
    for disk in all_disks:
        id_list.append(disk.target.attrib.get("dev"))
        if disk.source.attrib.get("protocol") == disk_type:
            if disk_type == "rbd":
                last_disk = disk.source.attrib.get("name")
            elif disk_type == "file":
                last_disk = disk.source.attrib.get("file")
            if last_disk == volume:
                return False, "Volume {} is already configured for VM {}.".format(
                    volume, vm
                )
            last_disk_details = deepcopy(disk)

    if disk_id is not None:
        if disk_id in id_list:
            return (
                False,
                "Manually specified disk ID {} is already in use for VM {}.".format(
                    disk_id, vm
                ),
            )
    else:
        # Find the next free disk ID
        first_dev_prefix = id_list[0][0:-1]

        for char in range(ord("a"), ord("z")):
            char = chr(char)
            next_id = "{}{}".format(first_dev_prefix, char)
            if next_id not in id_list:
                break
            else:
                next_id = None
        if next_id is None:
            return (
                False,
                "Failed to find a valid disk_id and none specified; too many disks for VM {}?".format(
                    vm
                ),
            )
        disk_id = next_id

    if last_disk is None:
        if disk_type == "rbd":
            # RBD volumes need an example to be based on
            return (
                False,
                "There are no existing RBD volumes attached to this VM. Autoconfiguration failed; use the 'vm modify' command to manually configure this volume with the required details for authentication, hosts, etc..",
            )
        elif disk_type == "file":
            # File types can be added ad-hoc
            disk_template = '<disk type="file" device="disk"><driver name="qemu" type="raw"/><source file="{source}"/><target dev="{dev}" bus="{bus}"/></disk>'.format(
                source=volume, dev=disk_id, bus=bus
            )
            last_disk_details = fromstring(disk_template)

    new_disk_details = last_disk_details
    new_disk_details.target.set("dev", disk_id)
    new_disk_details.target.set("bus", bus)
    if disk_type == "rbd":
        new_disk_details.source.set("name", volume)
    elif disk_type == "file":
        new_disk_details.source.set("file", volume)
    device_xml = new_disk_details

    all_disks = parsed_xml.devices.find("disk")
    if all_disks is None:
        all_disks = []
    for disk in all_disks:
        last_disk = disk

    # Add the disk at the end of the list (or, right above emulator)
    if len(all_disks) > 0:
        for idx, disk in enumerate(parsed_xml.devices.find("disk")):
            if idx == len(all_disks) - 1:
                disk.addnext(device_xml)
    else:
        parsed_xml.devices.find("emulator").addprevious(device_xml)

    try:
        new_xml = tostring(parsed_xml, pretty_print=True)
    except Exception:
        return False, "ERROR: Failed to dump XML data."

    modify_retcode, modify_retmsg = vm_modify(config, vm, new_xml, restart)

    if not modify_retcode:
        return modify_retcode, modify_retmsg

    if live:
        device_string = tostring(device_xml)
        attach_retcode, attach_retmsg = vm_device_attach(config, vm, device_string)

        if not attach_retcode:
            retcode = attach_retcode
            retmsg = attach_retmsg
        else:
            retcode = attach_retcode
            retmsg = "Volume '{}/{}' successfully added to VM config and hot attached to running VM.".format(
                vpool, vname
            )
    else:
        retcode = modify_retcode
        retmsg = modify_retmsg

    return retcode, retmsg


def vm_volumes_remove(config, vm, volume, live, restart):
    """
    Remove a volume to the VM

    Calls vm_info to get the VM XML.

    Calls vm_modify to set the VM XML.
    """
    from lxml.objectify import fromstring
    from lxml.etree import tostring

    status, domain_information = vm_info(config, vm)
    if not status:
        return status, domain_information

    xml = domain_information.get("xml", None)
    if xml is None:
        return False, "VM does not have a valid XML document."

    try:
        parsed_xml = fromstring(xml)
    except Exception:
        return False, "ERROR: Failed to parse XML data."

    changed = False
    device_string = None
    for disk in parsed_xml.devices.find("disk"):
        disk_name = disk.source.attrib.get("name")
        if not disk_name:
            disk_name = disk.source.attrib.get("file")
        if volume == disk_name:
            device_string = tostring(disk)
            disk.getparent().remove(disk)
            changed = True

    if changed:
        try:
            new_xml = tostring(parsed_xml, pretty_print=True)
        except Exception:
            return False, "ERROR: Failed to dump XML data."
    else:
        return False, 'ERROR: Volume "{}" does not exist on VM.'.format(volume)

    modify_retcode, modify_retmsg = vm_modify(config, vm, new_xml, restart)

    if not modify_retcode:
        return modify_retcode, modify_retmsg

    if live and device_string:
        detach_retcode, detach_retmsg = vm_device_detach(config, vm, device_string)

        if not detach_retcode:
            retcode = detach_retcode
            retmsg = detach_retmsg
        else:
            retcode = detach_retcode
            retmsg = "Volume '{}' successfully removed from VM config and hot detached from running VM.".format(
                volume
            )
    else:
        retcode = modify_retcode
        retmsg = modify_retmsg

    return retcode, retmsg


def vm_volumes_get(config, vm):
    """
    Get the volumes of the VM

    Calls vm_info to get VM XML.

    Returns a list of tuples of (volume, disk_id, type, bus)
    """
    from lxml.objectify import fromstring

    status, domain_information = vm_info(config, vm)
    if not status:
        return status, domain_information

    xml = domain_information.get("xml", None)
    if xml is None:
        return False, "VM does not have a valid XML doccument."

    try:
        parsed_xml = fromstring(xml)
    except Exception:
        return False, "ERROR: Failed to parse XML data."

    data = dict()
    data["name"] = vm
    data["volumes"] = list()
    for disk in parsed_xml.devices.find("disk"):
        protocol = disk.attrib.get("type")
        disk_id = disk.target.attrib.get("dev")
        bus = disk.target.attrib.get("bus")
        if protocol == "network":
            protocol = disk.source.attrib.get("protocol")
            source = disk.source.attrib.get("name")
        elif protocol == "file":
            protocol = "file"
            source = disk.source.attrib.get("file")
        else:
            protocol = "unknown"
            source = "unknown"

        data["volumes"].append(
            {"volume": source, "disk_id": disk_id, "protocol": protocol, "bus": bus}
        )

    return True, data


def format_vm_volumes(config, data):
    """
    Format the output of a volume value in a nice table
    """
    output_list = []

    volume_length = 7
    disk_id_length = 4
    protocol_length = 5
    bus_length = 4

    for volume in data["volumes"]:
        _volume_length = len(volume["volume"]) + 1
        if _volume_length > volume_length:
            volume_length = _volume_length

        _disk_id_length = len(volume["disk_id"]) + 1
        if _disk_id_length > disk_id_length:
            disk_id_length = _disk_id_length

        _protocol_length = len(volume["protocol"]) + 1
        if _protocol_length > protocol_length:
            protocol_length = _protocol_length

        _bus_length = len(volume["bus"]) + 1
        if _bus_length > bus_length:
            bus_length = _bus_length

    output_list.append(
        "{bold}{volume: <{volume_length}} \
{disk_id: <{disk_id_length}} \
{protocol: <{protocol_length}} \
{bus: <{bus_length}}{end_bold}".format(
            volume_length=volume_length,
            disk_id_length=disk_id_length,
            protocol_length=protocol_length,
            bus_length=bus_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            volume="Volume",
            disk_id="Dev",
            protocol="Type",
            bus="Bus",
        )
    )
    count = 0
    for volume in data["volumes"]:
        count += 1
        output_list.append(
            "{bold}{volume: <{volume_length}} \
{disk_id: <{disk_id_length}} \
{protocol: <{protocol_length}} \
{bus: <{bus_length}}{end_bold}".format(
                volume_length=volume_length,
                disk_id_length=disk_id_length,
                protocol_length=protocol_length,
                bus_length=bus_length,
                bold="",
                end_bold="",
                volume=volume["volume"],
                disk_id=volume["disk_id"],
                protocol=volume["protocol"],
                bus=volume["bus"],
            )
        )
    return "\n".join(output_list)


def view_console_log(config, vm, lines=100):
    """
    Return console log lines from the API (and display them in a pager in the main CLI)

    API endpoint: GET /vm/{vm}/console
    API arguments: lines={lines}
    API schema: {"name":"{vmname}","data":"{console_log}"}
    """
    params = {"lines": lines}
    response = call_api(config, "get", "/vm/{vm}/console".format(vm=vm), params=params)

    if response.status_code != 200:
        return False, response.json().get("message", "")

    console_log = response.json()["data"]

    # Shrink the log buffer to length lines
    shrunk_log = console_log.split("\n")[-lines:]
    loglines = "\n".join(shrunk_log)

    return True, loglines


def follow_console_log(config, vm, lines=10):
    """
    Return and follow console log lines from the API

    API endpoint: GET /vm/{vm}/console
    API arguments: lines={lines}
    API schema: {"name":"{vmname}","data":"{console_log}"}
    """
    # We always grab 200 to match the follow call, but only _show_ `lines` number
    params = {"lines": 200}
    response = call_api(config, "get", "/vm/{vm}/console".format(vm=vm), params=params)

    if response.status_code != 200:
        return False, response.json().get("message", "")

    # Shrink the log buffer to length lines
    console_log = response.json()["data"]
    shrunk_log = console_log.split("\n")[-int(lines) :]
    loglines = "\n".join(shrunk_log)

    # Print the initial data and begin following
    print(loglines, end="")

    while True:
        # Grab the next line set (200 is a reasonable number of lines per half-second; any more are skipped)
        try:
            params = {"lines": 200}
            response = call_api(
                config, "get", "/vm/{vm}/console".format(vm=vm), params=params
            )
            new_console_log = response.json()["data"]
        except Exception:
            break
        # Split the new and old log strings into constitutent lines
        old_console_loglines = console_log.split("\n")
        new_console_loglines = new_console_log.split("\n")

        # Set the console log to the new log value for the next iteration
        console_log = new_console_log

        # Remove the lines from the old log until we hit the first line of the new log; this
        # ensures that the old log is a string that we can remove from the new log entirely
        for index, line in enumerate(old_console_loglines, start=0):
            if line == new_console_loglines[0]:
                del old_console_loglines[0:index]
                break
        # Rejoin the log lines into strings
        old_console_log = "\n".join(old_console_loglines)
        new_console_log = "\n".join(new_console_loglines)
        # Remove the old lines from the new log
        diff_console_log = new_console_log.replace(old_console_log, "")
        # If there's a difference, print it out
        if diff_console_log:
            print(diff_console_log, end="")
        # Wait half a second
        time.sleep(0.5)

    return True, ""


#
# Output display functions
#
def format_info(config, domain_information, long_output):
    # Format a nice output; do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append(
        "{}Virtual machine information:{}".format(ansiprint.bold(), ansiprint.end())
    )
    ainformation.append("")
    # Basic information
    ainformation.append(
        "{}Name:{}               {}".format(
            ansiprint.purple(), ansiprint.end(), domain_information["name"]
        )
    )
    ainformation.append(
        "{}UUID:{}               {}".format(
            ansiprint.purple(), ansiprint.end(), domain_information["uuid"]
        )
    )
    ainformation.append(
        "{}Description:{}        {}".format(
            ansiprint.purple(), ansiprint.end(), domain_information["description"]
        )
    )
    ainformation.append(
        "{}Profile:{}            {}".format(
            ansiprint.purple(), ansiprint.end(), domain_information["profile"]
        )
    )
    ainformation.append(
        "{}Memory (M):{}         {}".format(
            ansiprint.purple(), ansiprint.end(), domain_information["memory"]
        )
    )
    ainformation.append(
        "{}vCPUs:{}              {}".format(
            ansiprint.purple(), ansiprint.end(), domain_information["vcpu"]
        )
    )
    if long_output:
        ainformation.append(
            "{}Topology (S/C/T):{}   {}".format(
                ansiprint.purple(), ansiprint.end(), domain_information["vcpu_topology"]
            )
        )

    if (
        domain_information["vnc"].get("listen")
        and domain_information["vnc"].get("port")
    ) or long_output:
        listen = (
            domain_information["vnc"]["listen"]
            if domain_information["vnc"].get("listen")
            else "N/A"
        )
        port = (
            domain_information["vnc"]["port"]
            if domain_information["vnc"].get("port")
            else "N/A"
        )
        ainformation.append("")
        ainformation.append(
            "{}VNC listen:{}         {}".format(
                ansiprint.purple(), ansiprint.end(), listen
            )
        )
        ainformation.append(
            "{}VNC port:{}           {}".format(
                ansiprint.purple(), ansiprint.end(), port
            )
        )

    if long_output:
        # Virtualization information
        ainformation.append("")
        ainformation.append(
            "{}Emulator:{}           {}".format(
                ansiprint.purple(), ansiprint.end(), domain_information["emulator"]
            )
        )
        ainformation.append(
            "{}Type:{}               {}".format(
                ansiprint.purple(), ansiprint.end(), domain_information["type"]
            )
        )
        ainformation.append(
            "{}Arch:{}               {}".format(
                ansiprint.purple(), ansiprint.end(), domain_information["arch"]
            )
        )
        ainformation.append(
            "{}Machine:{}            {}".format(
                ansiprint.purple(), ansiprint.end(), domain_information["machine"]
            )
        )
        ainformation.append(
            "{}Features:{}           {}".format(
                ansiprint.purple(),
                ansiprint.end(),
                " ".join(domain_information["features"]),
            )
        )
        ainformation.append("")
        ainformation.append(
            "{0}Memory stats:{1}       {2}Swap In  Swap Out  Faults (maj/min)  Available  Usable  Unused  RSS{3}".format(
                ansiprint.purple(), ansiprint.end(), ansiprint.bold(), ansiprint.end()
            )
        )
        ainformation.append(
            "                    {0: <7}  {1: <8}  {2: <16}  {3: <10} {4: <7} {5: <7} {6: <10}".format(
                format_metric(domain_information["memory_stats"].get("swap_in", 0)),
                format_metric(domain_information["memory_stats"].get("swap_out", 0)),
                "/".join(
                    [
                        format_metric(
                            domain_information["memory_stats"].get("major_fault", 0)
                        ),
                        format_metric(
                            domain_information["memory_stats"].get("minor_fault", 0)
                        ),
                    ]
                ),
                format_bytes(
                    domain_information["memory_stats"].get("available", 0) * 1024
                ),
                format_bytes(
                    domain_information["memory_stats"].get("usable", 0) * 1024
                ),
                format_bytes(
                    domain_information["memory_stats"].get("unused", 0) * 1024
                ),
                format_bytes(domain_information["memory_stats"].get("rss", 0) * 1024),
            )
        )
        ainformation.append("")
        ainformation.append(
            "{0}vCPU stats:{1}         {2}CPU time (ns)     User time (ns)    System time (ns){3}".format(
                ansiprint.purple(), ansiprint.end(), ansiprint.bold(), ansiprint.end()
            )
        )
        ainformation.append(
            "                    {0: <16}  {1: <16}  {2: <15}".format(
                str(domain_information["vcpu_stats"].get("cpu_time", 0)),
                str(domain_information["vcpu_stats"].get("user_time", 0)),
                str(domain_information["vcpu_stats"].get("system_time", 0)),
            )
        )

    # PVC cluster information
    ainformation.append("")
    dstate_colour = {
        "start": ansiprint.green(),
        "restart": ansiprint.yellow(),
        "shutdown": ansiprint.yellow(),
        "stop": ansiprint.red(),
        "disable": ansiprint.blue(),
        "fail": ansiprint.red(),
        "migrate": ansiprint.blue(),
        "unmigrate": ansiprint.blue(),
        "provision": ansiprint.blue(),
        "restore": ansiprint.blue(),
        "import": ansiprint.blue(),
        "mirror": ansiprint.purple(),
    }
    ainformation.append(
        "{}State:{}              {}{}{}".format(
            ansiprint.purple(),
            ansiprint.end(),
            dstate_colour[domain_information["state"]],
            domain_information["state"],
            ansiprint.end(),
        )
    )
    ainformation.append(
        "{}Current node:{}       {}".format(
            ansiprint.purple(), ansiprint.end(), domain_information["node"]
        )
    )
    if not domain_information["last_node"]:
        domain_information["last_node"] = "N/A"
    ainformation.append(
        "{}Previous node:{}      {}".format(
            ansiprint.purple(), ansiprint.end(), domain_information["last_node"]
        )
    )

    # Get a failure reason if applicable
    if domain_information["failed_reason"]:
        ainformation.append("")
        ainformation.append(
            "{}Failure reason:{}     {}".format(
                ansiprint.purple(), ansiprint.end(), domain_information["failed_reason"]
            )
        )

    if (
        not domain_information.get("node_selector")
        or domain_information.get("node_selector") == "None"
    ):
        formatted_node_selector = "Default"
    else:
        formatted_node_selector = str(domain_information["node_selector"]).title()

    if (
        not domain_information.get("node_limit")
        or domain_information.get("node_limit") == "None"
    ):
        formatted_node_limit = "Any"
    else:
        formatted_node_limit = ", ".join(domain_information["node_limit"])

    if not domain_information.get("node_autostart"):
        autostart_colour = ansiprint.blue()
        formatted_node_autostart = "False"
    else:
        autostart_colour = ansiprint.green()
        formatted_node_autostart = "True"

    if (
        not domain_information.get("migration_method")
        or domain_information.get("migration_method") == "None"
    ):
        formatted_migration_method = "Live, Shutdown"
    else:
        formatted_migration_method = (
            f"{str(domain_information['migration_method']).title()} only"
        )

    ainformation.append(
        "{}Node limit:{}         {}".format(
            ansiprint.purple(), ansiprint.end(), formatted_node_limit
        )
    )
    ainformation.append(
        "{}Autostart:{}          {}{}{}".format(
            ansiprint.purple(),
            ansiprint.end(),
            autostart_colour,
            formatted_node_autostart,
            ansiprint.end(),
        )
    )
    ainformation.append(
        "{}Migration method:{}   {}".format(
            ansiprint.purple(), ansiprint.end(), formatted_migration_method
        )
    )
    ainformation.append(
        "{}Migration selector:{} {}".format(
            ansiprint.purple(), ansiprint.end(), formatted_node_selector
        )
    )
    ainformation.append(
        "{}Max live downtime:{}  {}".format(
            ansiprint.purple(),
            ansiprint.end(),
            f"{domain_information.get('migration_max_downtime')} ms",
        )
    )

    # Tag list
    tags_name_length = 5
    tags_type_length = 5
    tags_protected_length = 10
    for tag in domain_information["tags"]:
        _tags_name_length = len(tag["name"]) + 1
        if _tags_name_length > tags_name_length:
            tags_name_length = _tags_name_length

        _tags_type_length = len(tag["type"]) + 1
        if _tags_type_length > tags_type_length:
            tags_type_length = _tags_type_length

        _tags_protected_length = len(str(tag["protected"])) + 1
        if _tags_protected_length > tags_protected_length:
            tags_protected_length = _tags_protected_length

    if len(domain_information["tags"]) > 0:
        ainformation.append("")
        ainformation.append(
            "{purple}Tags:{end}               {bold}{tags_name: <{tags_name_length}} {tags_type: <{tags_type_length}} {tags_protected: <{tags_protected_length}}{end}".format(
                purple=ansiprint.purple(),
                bold=ansiprint.bold(),
                end=ansiprint.end(),
                tags_name_length=tags_name_length,
                tags_type_length=tags_type_length,
                tags_protected_length=tags_protected_length,
                tags_name="Name",
                tags_type="Type",
                tags_protected="Protected",
            )
        )

        for tag in sorted(
            domain_information["tags"], key=lambda t: t["type"] + t["name"]
        ):
            ainformation.append(
                "                    {tags_name: <{tags_name_length}} {tags_type: <{tags_type_length}} {tags_protected_colour}{tags_protected: <{tags_protected_length}}{end}".format(
                    tags_name_length=tags_name_length,
                    tags_type_length=tags_type_length,
                    tags_protected_length=tags_protected_length,
                    tags_name=tag["name"],
                    tags_type=tag["type"],
                    tags_protected=str(tag["protected"]),
                    tags_protected_colour=(
                        ansiprint.green() if tag["protected"] else ansiprint.blue()
                    ),
                    end=ansiprint.end(),
                )
            )
    else:
        ainformation.append("")
        ainformation.append(
            "{purple}Tags:{end}               N/A".format(
                purple=ansiprint.purple(),
                end=ansiprint.end(),
            )
        )

    # Snapshot list
    snapshots_name_length = 5
    snapshots_age_length = 4
    snapshots_xml_changes_length = 12
    for snapshot in domain_information.get("snapshots", list()):
        xml_diff_plus = 0
        xml_diff_minus = 0
        for line in snapshot["xml_diff_lines"]:
            if re.match(r"^\+ ", line):
                xml_diff_plus += 1
            elif re.match(r"^- ", line):
                xml_diff_minus += 1
        xml_diff_counts = f"+{xml_diff_plus}/-{xml_diff_minus}"

        _snapshots_name_length = len(snapshot["name"]) + 1
        if _snapshots_name_length > snapshots_name_length:
            snapshots_name_length = _snapshots_name_length

        _snapshots_age_length = len(snapshot["age"]) + 1
        if _snapshots_age_length > snapshots_age_length:
            snapshots_age_length = _snapshots_age_length

        _snapshots_xml_changes_length = len(xml_diff_counts) + 1
        if _snapshots_xml_changes_length > snapshots_xml_changes_length:
            snapshots_xml_changes_length = _snapshots_xml_changes_length

    if len(domain_information.get("snapshots", list())) > 0:
        ainformation.append("")
        ainformation.append(
            "{purple}Snapshots:{end}          {bold}{snapshots_name: <{snapshots_name_length}} {snapshots_age: <{snapshots_age_length}} {snapshots_xml_changes: <{snapshots_xml_changes_length}}{end}".format(
                purple=ansiprint.purple(),
                bold=ansiprint.bold(),
                end=ansiprint.end(),
                snapshots_name_length=snapshots_name_length,
                snapshots_age_length=snapshots_age_length,
                snapshots_xml_changes_length=snapshots_xml_changes_length,
                snapshots_name="Name",
                snapshots_age="Age",
                snapshots_xml_changes="XML Changes",
            )
        )

        for snapshot in domain_information.get("snapshots", list()):
            xml_diff_plus = 0
            xml_diff_minus = 0
            for line in snapshot["xml_diff_lines"]:
                if re.match(r"^\+ ", line):
                    xml_diff_plus += 1
                elif re.match(r"^- ", line):
                    xml_diff_minus += 1
            xml_diff_counts = f"{ansiprint.green()}+{xml_diff_plus}{ansiprint.end()}/{ansiprint.red()}-{xml_diff_minus}{ansiprint.end()}"

            ainformation.append(
                "                    {snapshots_name: <{snapshots_name_length}} {snapshots_age: <{snapshots_age_length}} {snapshots_xml_changes: <{snapshots_xml_changes_length}}{end}".format(
                    snapshots_name_length=snapshots_name_length,
                    snapshots_age_length=snapshots_age_length,
                    snapshots_xml_changes_length=snapshots_xml_changes_length,
                    snapshots_name=snapshot["name"],
                    snapshots_age=snapshot["age"],
                    snapshots_xml_changes=xml_diff_counts,
                    end=ansiprint.end(),
                )
            )
    else:
        ainformation.append("")
        ainformation.append(
            "{purple}Snapshots:{end}          N/A".format(
                purple=ansiprint.purple(),
                end=ansiprint.end(),
            )
        )

    # Network list
    net_list = []
    cluster_net_list = call_api(config, "get", "/network").json()
    for net in domain_information["networks"]:
        net_vni = net["vni"]
        if (
            net_vni not in ["cluster", "storage", "upstream"]
            and not re.match(r"^macvtap:.*", net_vni)
            and not re.match(r"^hostdev:.*", net_vni)
        ):
            if int(net_vni) not in [net["vni"] for net in cluster_net_list]:
                net_list.append(
                    ansiprint.red() + net_vni + ansiprint.end() + " [invalid]"
                )
            else:
                net_list.append(net_vni)
        else:
            net_list.append(net_vni)

    ainformation.append("")
    ainformation.append(
        "{}Networks:{}           {}".format(
            ansiprint.purple(), ansiprint.end(), ", ".join(net_list)
        )
    )

    if long_output:
        # Disk list
        ainformation.append("")
        name_length = 0
        for disk in domain_information["disks"]:
            _name_length = len(disk["name"]) + 1
            if _name_length > name_length:
                name_length = _name_length
        ainformation.append(
            "{0}Disks:{1}        {2}ID  Type  {3: <{width}} Dev  Bus    Requests (r/w)   Data (r/w){4}".format(
                ansiprint.purple(),
                ansiprint.end(),
                ansiprint.bold(),
                "Name",
                ansiprint.end(),
                width=name_length,
            )
        )
        for disk in domain_information["disks"]:
            ainformation.append(
                "              {0: <3} {1: <5} {2: <{width}} {3: <4} {4: <5}  {5: <15}  {6}".format(
                    domain_information["disks"].index(disk),
                    disk["type"],
                    disk["name"],
                    disk["dev"],
                    disk["bus"],
                    "/".join(
                        [
                            str(format_metric(disk.get("rd_req", 0))),
                            str(format_metric(disk.get("wr_req", 0))),
                        ]
                    ),
                    "/".join(
                        [
                            str(format_bytes(disk.get("rd_bytes", 0))),
                            str(format_bytes(disk.get("wr_bytes", 0))),
                        ]
                    ),
                    width=name_length,
                )
            )
        ainformation.append("")
        ainformation.append(
            "{}Interfaces:{}   {}ID  Type     Source       Model    MAC                 Data (r/w)   Packets (r/w)   Errors (r/w){}".format(
                ansiprint.purple(), ansiprint.end(), ansiprint.bold(), ansiprint.end()
            )
        )
        for net in domain_information["networks"]:
            net_type = net["type"]
            net_source = net["source"]
            net_mac = net["mac"]
            if net_type in ["direct", "hostdev"]:
                net_model = "N/A"
                net_bytes = "N/A"
                net_packets = "N/A"
                net_errors = "N/A"
            elif net_type in ["bridge"]:
                net_model = net["model"]
                net_bytes = "/".join(
                    [
                        str(format_bytes(net.get("rd_bytes", 0))),
                        str(format_bytes(net.get("wr_bytes", 0))),
                    ]
                )
                net_packets = "/".join(
                    [
                        str(format_metric(net.get("rd_packets", 0))),
                        str(format_metric(net.get("wr_packets", 0))),
                    ]
                )
                net_errors = "/".join(
                    [
                        str(format_metric(net.get("rd_errors", 0))),
                        str(format_metric(net.get("wr_errors", 0))),
                    ]
                )

            ainformation.append(
                "              {0: <3} {1: <8} {2: <12} {3: <8} {4: <18}  {5: <12} {6: <15} {7: <12}".format(
                    domain_information["networks"].index(net),
                    net_type,
                    net_source,
                    net_model,
                    net_mac,
                    net_bytes,
                    net_packets,
                    net_errors,
                )
            )
        # Controller list
        ainformation.append("")
        ainformation.append(
            "{}Controllers:{}  {}ID  Type           Model{}".format(
                ansiprint.purple(), ansiprint.end(), ansiprint.bold(), ansiprint.end()
            )
        )
        for controller in domain_information["controllers"]:
            ainformation.append(
                "              {0: <3} {1: <14} {2: <8}".format(
                    domain_information["controllers"].index(controller),
                    controller["type"],
                    str(controller["model"]),
                )
            )

    # Join it all together
    ainformation.append("")
    return "\n".join(ainformation)


def format_list(config, vm_list):
    # Function to strip the "br" off of nets and return a nicer list
    def getNiceNetID(domain_information):
        # Network list
        net_list = []
        for net in domain_information["networks"]:
            net_list.append(net["vni"])
        return net_list

    # Function to get tag names and returna  nicer list
    def getNiceTagName(domain_information):
        # Tag list
        tag_list = []
        for tag in sorted(
            domain_information["tags"], key=lambda t: t["type"] + t["name"]
        ):
            tag_list.append(tag["name"])
        return tag_list

    vm_list_output = []

    # Determine optimal column widths
    # Dynamic columns: node_name, node, migrated
    vm_name_length = 5
    vm_state_length = 6
    vm_tags_length = 5
    vm_snapshots_length = 10
    vm_nets_length = 9
    vm_ram_length = 8
    vm_vcpu_length = 6
    vm_node_length = 8
    vm_migrated_length = 9
    for domain_information in vm_list:
        net_list = getNiceNetID(domain_information)
        tag_list = getNiceTagName(domain_information)
        # vm_name column
        _vm_name_length = len(domain_information["name"]) + 1
        if _vm_name_length > vm_name_length:
            vm_name_length = _vm_name_length
        # vm_state column
        _vm_state_length = len(domain_information["state"]) + 1
        if _vm_state_length > vm_state_length:
            vm_state_length = _vm_state_length
        # vm_tags column
        _vm_tags_length = len(",".join(tag_list)) + 1
        if _vm_tags_length > vm_tags_length:
            vm_tags_length = _vm_tags_length
        # vm_snapshots column
        _vm_snapshots_length = (
            len(str(len(domain_information.get("snapshots", list())))) + 1
        )
        if _vm_snapshots_length > vm_snapshots_length:
            vm_snapshots_length = _vm_snapshots_length
        # vm_nets column
        _vm_nets_length = len(",".join(net_list)) + 1
        if _vm_nets_length > vm_nets_length:
            vm_nets_length = _vm_nets_length
        # vm_node column
        _vm_node_length = len(domain_information["node"]) + 1
        if _vm_node_length > vm_node_length:
            vm_node_length = _vm_node_length
        # vm_migrated column
        _vm_migrated_length = len(domain_information["migrated"]) + 1
        if _vm_migrated_length > vm_migrated_length:
            vm_migrated_length = _vm_migrated_length

    # Format the string (header)
    vm_list_output.append(
        "{bold}{vm_header: <{vm_header_length}} {resource_header: <{resource_header_length}} {node_header: <{node_header_length}}{end_bold}".format(
            vm_header_length=vm_name_length
            + vm_state_length
            + vm_tags_length
            + vm_snapshots_length
            + 3,
            resource_header_length=vm_nets_length + vm_ram_length + vm_vcpu_length + 2,
            node_header_length=vm_node_length + vm_migrated_length + 1,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            vm_header="VMs "
            + "".join(
                [
                    "-"
                    for _ in range(
                        4,
                        vm_name_length
                        + vm_state_length
                        + vm_tags_length
                        + +vm_snapshots_length
                        + 2,
                    )
                ]
            ),
            resource_header="Resources "
            + "".join(
                [
                    "-"
                    for _ in range(
                        10, vm_nets_length + vm_ram_length + vm_vcpu_length + 1
                    )
                ]
            ),
            node_header="Node "
            + "".join(["-" for _ in range(5, vm_node_length + vm_migrated_length)]),
        )
    )

    vm_list_output.append(
        "{bold}{vm_name: <{vm_name_length}} \
{vm_state_colour}{vm_state: <{vm_state_length}}{end_colour} \
{vm_tags: <{vm_tags_length}} \
{vm_snapshots: <{vm_snapshots_length}} \
{vm_networks: <{vm_nets_length}} \
{vm_memory: <{vm_ram_length}} {vm_vcpu: <{vm_vcpu_length}} \
{vm_node: <{vm_node_length}} \
{vm_migrated: <{vm_migrated_length}}{end_bold}".format(
            vm_name_length=vm_name_length,
            vm_state_length=vm_state_length,
            vm_tags_length=vm_tags_length,
            vm_snapshots_length=vm_snapshots_length,
            vm_nets_length=vm_nets_length,
            vm_ram_length=vm_ram_length,
            vm_vcpu_length=vm_vcpu_length,
            vm_node_length=vm_node_length,
            vm_migrated_length=vm_migrated_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            vm_state_colour="",
            end_colour="",
            vm_name="Name",
            vm_state="State",
            vm_tags="Tags",
            vm_snapshots="Snapshots",
            vm_networks="Networks",
            vm_memory="RAM (M)",
            vm_vcpu="vCPUs",
            vm_node="Current",
            vm_migrated="Migrated",
        )
    )

    # Get a list of cluster networks for validity comparisons
    cluster_net_list = call_api(config, "get", "/network").json()

    # Format the string (elements)
    for domain_information in sorted(vm_list, key=lambda v: v["name"]):
        if domain_information["state"] in ["start"]:
            vm_state_colour = ansiprint.green()
        elif domain_information["state"] in ["restart", "shutdown"]:
            vm_state_colour = ansiprint.yellow()
        elif domain_information["state"] in ["stop", "fail"]:
            vm_state_colour = ansiprint.red()
        elif domain_information["state"] in ["mirror"]:
            vm_state_colour = ansiprint.purple()
        else:
            vm_state_colour = ansiprint.blue()

        # Handle colouring for an invalid network config
        net_list = getNiceNetID(domain_information)
        tag_list = getNiceTagName(domain_information)
        if len(tag_list) < 1:
            tag_list = ["N/A"]

        net_invalid_list = []
        for net_vni in net_list:
            if (
                net_vni not in ["cluster", "storage", "upstream"]
                and not re.match(r"^macvtap:.*", net_vni)
                and not re.match(r"^hostdev:.*", net_vni)
            ):
                if int(net_vni) not in [net["vni"] for net in cluster_net_list]:
                    net_invalid_list.append(True)
                else:
                    net_invalid_list.append(False)
            else:
                net_invalid_list.append(False)

        net_string_list = []
        for net_idx, net_vni in enumerate(net_list):
            if net_invalid_list[net_idx]:
                net_string_list.append(
                    "{}{}{}".format(
                        ansiprint.red(),
                        net_vni,
                        ansiprint.end(),
                    )
                )
            else:
                net_string_list.append(net_vni)

        vm_list_output.append(
            "{bold}{vm_name: <{vm_name_length}} \
{vm_state_colour}{vm_state: <{vm_state_length}}{end_colour} \
{vm_tags: <{vm_tags_length}} \
{vm_snapshots: <{vm_snapshots_length}} \
{vm_networks: <{vm_nets_length}} \
{vm_memory: <{vm_ram_length}} {vm_vcpu: <{vm_vcpu_length}} \
{vm_node: <{vm_node_length}} \
{vm_migrated: <{vm_migrated_length}}{end_bold}".format(
                vm_name_length=vm_name_length,
                vm_state_length=vm_state_length,
                vm_tags_length=vm_tags_length,
                vm_snapshots_length=vm_snapshots_length,
                vm_nets_length=vm_nets_length,
                vm_ram_length=vm_ram_length,
                vm_vcpu_length=vm_vcpu_length,
                vm_node_length=vm_node_length,
                vm_migrated_length=vm_migrated_length,
                bold="",
                end_bold="",
                vm_state_colour=vm_state_colour,
                end_colour=ansiprint.end(),
                vm_name=domain_information["name"],
                vm_state=domain_information["state"],
                vm_tags=",".join(tag_list),
                vm_snapshots=len(domain_information.get("snapshots", list())),
                vm_networks=",".join(net_string_list)
                + ("" if all(net_invalid_list) else " "),
                vm_memory=domain_information["memory"],
                vm_vcpu=domain_information["vcpu"],
                vm_node=domain_information["node"],
                vm_migrated=domain_information["migrated"],
            )
        )

    return "\n".join(vm_list_output)
