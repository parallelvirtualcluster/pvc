#!/usr/bin/env python3

# helper.py - PVC HTTP API helper functions
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

import flask
import json
import logging
import lxml.etree as etree
import sys

from re import match
from requests import get
from werkzeug.formparser import parse_form_data

from pvcapid.Daemon import config, strtobool

from daemon_lib.zkhandler import ZKConnection

import daemon_lib.common as pvc_common
import daemon_lib.cluster as pvc_cluster
import daemon_lib.faults as pvc_faults
import daemon_lib.node as pvc_node
import daemon_lib.vm as pvc_vm
import daemon_lib.network as pvc_network
import daemon_lib.ceph as pvc_ceph


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)


#
# Cluster base functions
#
@ZKConnection(config)
def initialize_cluster(zkhandler, overwrite=False):
    """
    Initialize a new cluster
    """
    retflag, retmsg = pvc_cluster.cluster_initialize(zkhandler, overwrite)

    retmsg = {"message": retmsg}
    if retflag:
        retcode = 200
    else:
        retcode = 400

    return retmsg, retcode


@ZKConnection(config)
def backup_cluster(zkhandler):
    retflag, retdata = pvc_cluster.cluster_backup(zkhandler)

    if retflag:
        retcode = 200
        retdata = json.dumps(retdata)
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@ZKConnection(config)
def restore_cluster(zkhandler, cluster_data_raw):
    try:
        cluster_data = json.loads(cluster_data_raw)
    except Exception as e:
        return {"message": "ERROR: Failed to parse JSON data: {}".format(e)}, 400

    retflag, retdata = pvc_cluster.cluster_restore(zkhandler, cluster_data)

    retdata = {"message": retdata}
    if retflag:
        retcode = 200
    else:
        retcode = 400

    return retdata, retcode


#
# Cluster functions
#
@pvc_common.Profiler(config)
@ZKConnection(config)
def cluster_status(zkhandler):
    """
    Get the overall status of the PVC cluster
    """
    retflag, retdata = pvc_cluster.get_info(zkhandler)

    return retdata, 200


@ZKConnection(config)
def cluster_maintenance(zkhandler, maint_state="false"):
    """
    Set the cluster in or out of maintenance state
    """
    retflag, retdata = pvc_cluster.set_maintenance(zkhandler, maint_state)

    retdata = {"message": retdata}
    if retflag:
        retcode = 200
    else:
        retcode = 400

    return retdata, retcode


#
# Metrics functions
#
@pvc_common.Profiler(config)
@ZKConnection(config)
def cluster_health_metrics(zkhandler):
    """
    Get cluster-wide Prometheus metrics for health
    """

    retflag, retdata = pvc_cluster.get_health_metrics(zkhandler)
    if retflag:
        retcode = 200
    else:
        retcode = 400
    return retdata, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def cluster_resource_metrics(zkhandler):
    """
    Get cluster-wide Prometheus metrics for resource utilization
    """

    retflag, retdata = pvc_cluster.get_resource_metrics(zkhandler)
    if retflag:
        retcode = 200
    else:
        retcode = 400
    return retdata, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def ceph_metrics(zkhandler):
    """
    Obtain current Ceph Prometheus metrics from the active MGR
    """
    # We have to parse out the *name* of the currently active MGR
    # While the JSON version of the "ceph status" output provides a
    # URL, this URL is in the backend (i.e. storage) network, which
    # the API might not have access to. This way, we can connect to
    # the node name which can be handled however.
    retcode, retdata = pvc_ceph.get_status(zkhandler)
    if not retcode:
        ceph_mgr_node = None
    else:
        ceph_data = retdata["ceph_data"]
        try:
            ceph_mgr_line = [
                n for n in ceph_data.split("\n") if match(r"^mgr:", n.strip())
            ][0]
            ceph_mgr_node = ceph_mgr_line.split()[1].split("(")[0]
        except Exception:
            ceph_mgr_node = None

    if ceph_mgr_node is not None:
        # Get the data from the endpoint
        # We use the default port of 9283
        ceph_prometheus_uri = f"http://{ceph_mgr_node}:9283/metrics"
        response = get(ceph_prometheus_uri)

        if response.status_code == 200:
            output = response.text
            status_code = 200
        else:
            output = (
                f"Error: Failed to obtain metric data from {ceph_mgr_node} MGR daemon\n"
            )
            status_code = 400
    else:
        output = "Error: Failed to find an active MGR node\n"
        status_code = 400

    return output, status_code


@pvc_common.Profiler(config)
@ZKConnection(config)
def zookeeper_metrics(zkhandler):
    """
    Obtain current Zookeeper Prometheus metrics from the active coordinator node
    """
    primary_node = zkhandler.read("base.config.primary_node")
    if primary_node is not None:
        # Get the data from the endpoint
        # We use the default port of 9141
        zookeeper_prometheus_uri = f"http://{primary_node}:9141/metrics"
        response = get(zookeeper_prometheus_uri)

        if response.status_code == 200:
            output = response.text
            # Parse the text to remove annoying ports (":2181")
            output = output.replace(":2181", "")
            # Sort the output text
            output_lines = output.split("\n")
            output_lines.sort()
            output = "\n".join(output_lines) + "\n"
            status_code = 200
        else:
            output = f"Error: Failed to obtain metric data from {primary_node} primary node daemon\n"
            status_code = 400
    else:
        output = "Error: Failed to find an active primary node\n"
        status_code = 400

    return output, status_code


#
# Fault functions
#
@pvc_common.Profiler(config)
@ZKConnection(config)
def fault_list(zkhandler, limit=None, sort_key="last_reported"):
    """
    Return a list of all faults sorted by SORT_KEY.
    """
    retflag, retdata = pvc_faults.get_list(zkhandler, limit=limit, sort_key=sort_key)

    if retflag:
        retcode = 200
    elif retflag and limit is not None and len(retdata) < 1:
        retcode = 404
        retdata = {"message": f"No fault with ID {limit} found"}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def fault_acknowledge(zkhandler, fault_id):
    """
    Acknowledge a fault of FAULT_ID.
    """
    retflag, retdata = pvc_faults.acknowledge(zkhandler, fault_id=fault_id)

    if retflag:
        retcode = 200
    else:
        retcode = 404

    retdata = {"message": retdata}

    return retdata, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def fault_acknowledge_all(zkhandler):
    """
    Acknowledge all faults.
    """
    retflag, retdata = pvc_faults.acknowledge(zkhandler)

    if retflag:
        retcode = 200
    else:
        retcode = 404

    retdata = {"message": retdata}

    return retdata, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def fault_delete(zkhandler, fault_id):
    """
    Delete a fault of FAULT_ID.
    """
    retflag, retdata = pvc_faults.delete(zkhandler, fault_id=fault_id)

    if retflag:
        retcode = 200
    else:
        retcode = 404

    retdata = {"message": retdata}

    return retdata, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def fault_delete_all(zkhandler):
    """
    Delete all faults.
    """
    retflag, retdata = pvc_faults.delete(zkhandler)

    if retflag:
        retcode = 200
    else:
        retcode = 404

    retdata = {"message": retdata}

    return retdata, retcode


#
# Node functions
#
@pvc_common.Profiler(config)
@ZKConnection(config)
def node_list(
    zkhandler,
    limit=None,
    daemon_state=None,
    coordinator_state=None,
    domain_state=None,
    is_fuzzy=True,
):
    """
    Return a list of nodes with limit LIMIT.
    """
    retflag, retdata = pvc_node.get_list(
        zkhandler,
        limit,
        daemon_state=daemon_state,
        coordinator_state=coordinator_state,
        domain_state=domain_state,
        is_fuzzy=is_fuzzy,
    )

    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {"message": "Node not found."}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@ZKConnection(config)
def node_daemon_state(zkhandler, node):
    """
    Return the daemon state of node NODE.
    """
    retflag, retdata = pvc_node.get_list(zkhandler, node, is_fuzzy=False)

    if retflag:
        if retdata:
            retcode = 200
            retdata = {"name": node, "daemon_state": retdata[0]["daemon_state"]}
        else:
            retcode = 404
            retdata = {"message": "Node not found."}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@ZKConnection(config)
def node_coordinator_state(zkhandler, node):
    """
    Return the coordinator state of node NODE.
    """
    retflag, retdata = pvc_node.get_list(zkhandler, node, is_fuzzy=False)

    if retflag:
        if retdata:
            retcode = 200
            retdata = {
                "name": node,
                "coordinator_state": retdata[0]["coordinator_state"],
            }
        else:
            retcode = 404
            retdata = {"message": "Node not found."}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@ZKConnection(config)
def node_domain_state(zkhandler, node):
    """
    Return the domain state of node NODE.
    """
    retflag, retdata = pvc_node.get_list(zkhandler, node, is_fuzzy=False)

    if retflag:
        if retdata:
            retcode = 200
            retdata = {"name": node, "domain_state": retdata[0]["domain_state"]}
        else:
            retcode = 404
            retdata = {"message": "Node not found."}
    else:
        retcode = 400

    return retdata, retcode


@ZKConnection(config)
def node_secondary(zkhandler, node):
    """
    Take NODE out of primary coordinator mode.
    """
    retflag, retdata = pvc_node.secondary_node(zkhandler, node)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def node_primary(zkhandler, node):
    """
    Set NODE to primary coordinator mode.
    """
    retflag, retdata = pvc_node.primary_node(zkhandler, node)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def node_flush(zkhandler, node, wait):
    """
    Flush NODE of running VMs.
    """
    retflag, retdata = pvc_node.flush_node(zkhandler, node, wait)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def node_ready(zkhandler, node, wait):
    """
    Restore NODE to active service.
    """
    retflag, retdata = pvc_node.ready_node(zkhandler, node, wait)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def node_log(zkhandler, node, lines=None):
    """
    Return the current logs for Node.
    """
    # Default to 10 lines of log if not set
    try:
        lines = int(lines)
    except TypeError:
        lines = 10

    retflag, retdata = pvc_node.get_node_log(zkhandler, node, lines)

    if retflag:
        retcode = 200
        retdata = {"name": node, "data": retdata}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


#
# VM functions
#
@ZKConnection(config)
def vm_is_migrated(zkhandler, vm):
    """
    Determine if a VM is migrated or not
    """
    retdata = pvc_vm.is_migrated(zkhandler, vm)

    return retdata


@pvc_common.Profiler(config)
@ZKConnection(config)
def vm_state(zkhandler, vm):
    """
    Return the state of virtual machine VM.
    """
    retflag, retdata = pvc_vm.get_list(
        zkhandler, None, None, None, vm, is_fuzzy=False, negate=False
    )

    if retflag:
        if retdata:
            retcode = 200
            retdata = {"name": vm, "state": retdata["state"]}
        else:
            retcode = 404
            retdata = {"message": "VM not found."}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def vm_node(zkhandler, vm):
    """
    Return the current node of virtual machine VM.
    """
    retflag, retdata = pvc_vm.get_list(
        zkhandler, None, None, None, vm, is_fuzzy=False, negate=False
    )

    if len(retdata) > 0:
        retdata = retdata[0]

    if retflag:
        if retdata:
            retcode = 200
            retdata = {
                "name": vm,
                "node": retdata["node"],
                "last_node": retdata["last_node"],
            }
        else:
            retcode = 404
            retdata = {"message": "VM not found."}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@ZKConnection(config)
def vm_console(zkhandler, vm, lines=None):
    """
    Return the current console log for VM.
    """
    # Default to 10 lines of log if not set
    try:
        lines = int(lines)
    except TypeError:
        lines = 10

    retflag, retdata = pvc_vm.get_console_log(zkhandler, vm, lines)

    if retflag:
        retcode = 200
        retdata = {"name": vm, "data": retdata}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def vm_list(
    zkhandler, node=None, state=None, tag=None, limit=None, is_fuzzy=True, negate=False
):
    """
    Return a list of VMs with limit LIMIT.
    """
    retflag, retdata = pvc_vm.get_list(
        zkhandler, node, state, tag, limit, is_fuzzy, negate
    )

    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {"message": "VM not found."}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@ZKConnection(config)
def vm_define(
    zkhandler,
    xml,
    node,
    limit,
    selector,
    autostart,
    migration_method,
    migration_max_downtime=300,
    user_tags=[],
    protected_tags=[],
):
    """
    Define a VM from Libvirt XML in the PVC cluster.
    """
    # Verify our XML is sensible
    try:
        xml_data = etree.fromstring(xml)
        new_cfg = etree.tostring(xml_data, pretty_print=True).decode("utf8")
    except Exception as e:
        return {"message": "XML is malformed or incorrect: {}".format(e)}, 400

    tags = list()
    for tag in user_tags:
        tags.append({"name": tag, "type": "user", "protected": False})
    for tag in protected_tags:
        tags.append({"name": tag, "type": "user", "protected": True})

    retflag, retdata = pvc_vm.define_vm(
        zkhandler,
        new_cfg,
        node,
        limit,
        selector,
        autostart,
        migration_method,
        migration_max_downtime,
        profile=None,
        tags=tags,
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_backup(
    zkhandler,
    domain,
    backup_path,
    incremental_parent=None,
    retain_snapshot=False,
):
    """
    Back up a VM to a local (primary coordinator) filesystem path.
    """
    retflag, retdata = pvc_vm.backup_vm(
        zkhandler,
        domain,
        backup_path,
        incremental_parent,
        retain_snapshot,
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_remove_backup(
    zkhandler,
    domain,
    source_path,
    datestring,
):
    """
    Remove a VM backup from snapshots and a local (primary coordinator) filesystem path.
    """
    retflag, retdata = pvc_vm.remove_backup(
        zkhandler,
        domain,
        source_path,
        datestring,
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_restore(
    zkhandler,
    domain,
    backup_path,
    datestring,
    retain_snapshot=False,
):
    """
    Restore a VM from a local (primary coordinator) filesystem path.
    """
    retflag, retdata = pvc_vm.restore_vm(
        zkhandler,
        domain,
        backup_path,
        datestring,
        retain_snapshot,
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def create_vm_snapshot(
    zkhandler,
    domain,
    snapshot_name=None,
):
    """
    Take a snapshot of a VM.
    """
    retflag, retdata = pvc_vm.create_vm_snapshot(
        zkhandler,
        domain,
        snapshot_name,
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def remove_vm_snapshot(
    zkhandler,
    domain,
    snapshot_name,
):
    """
    Take a snapshot of a VM.
    """
    retflag, retdata = pvc_vm.remove_vm_snapshot(
        zkhandler,
        domain,
        snapshot_name,
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def rollback_vm_snapshot(
    zkhandler,
    domain,
    snapshot_name,
):
    """
    Roll back to a snapshot of a VM.
    """
    retflag, retdata = pvc_vm.rollback_vm_snapshot(
        zkhandler,
        domain,
        snapshot_name,
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def export_vm_snapshot(
    zkhandler,
    domain,
    snapshot_name,
    export_path,
    incremental_parent=None,
):
    """
    Export a snapshot of a VM to files.
    """
    retflag, retdata = pvc_vm.export_vm_snapshot(
        zkhandler,
        domain,
        snapshot_name,
        export_path,
        incremental_parent,
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def import_vm_snapshot(
    zkhandler,
    domain,
    snapshot_name,
    export_path,
    retain_snapshot=False,
):
    """
    Import a snapshot of a VM from files.
    """
    retflag, retdata = pvc_vm.import_vm_snapshot(
        zkhandler,
        domain,
        snapshot_name,
        export_path,
        retain_snapshot,
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_attach_device(zkhandler, vm, device_spec_xml):
    """
    Hot-attach a device (via XML spec) to a VM.
    """
    try:
        _ = etree.fromstring(device_spec_xml)
    except Exception as e:
        return {"message": "XML is malformed or incorrect: {}".format(e)}, 400

    retflag, retdata = pvc_vm.attach_vm_device(zkhandler, vm, device_spec_xml)

    if retflag:
        retcode = 200
        output = {"message": retdata.replace('"', "'")}
    else:
        retcode = 400
        output = {
            "message": "WARNING: Failed to perform hot attach; device will be added on next VM start/restart."
        }

    return output, retcode


@ZKConnection(config)
def vm_detach_device(zkhandler, vm, device_spec_xml):
    """
    Hot-detach a device (via XML spec) from a VM.
    """
    try:
        _ = etree.fromstring(device_spec_xml)
    except Exception as e:
        return {"message": "XML is malformed or incorrect: {}".format(e)}, 400

    retflag, retdata = pvc_vm.detach_vm_device(zkhandler, vm, device_spec_xml)

    if retflag:
        retcode = 200
        output = {"message": retdata.replace('"', "'")}
    else:
        retcode = 400
        output = {
            "message": "WARNING: Failed to perform hot detach; device will be removed on next VM start/restart."
        }

    return output, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def get_vm_meta(zkhandler, vm):
    """
    Get metadata of a VM.
    """
    dom_uuid = pvc_vm.getDomainUUID(zkhandler, vm)
    if not dom_uuid:
        return {"message": "VM not found."}, 404

    (
        domain_node_limit,
        domain_node_selector,
        domain_node_autostart,
        domain_migrate_method,
        domain_migrate_max_downtime,
    ) = pvc_common.getDomainMetadata(zkhandler, dom_uuid)

    retcode = 200
    retdata = {
        "name": vm,
        "node_limit": domain_node_limit,
        "node_selector": domain_node_selector.lower(),
        "node_autostart": domain_node_autostart,
        "migration_method": domain_migrate_method.lower(),
        "migration_max_downtime": int(domain_migrate_max_downtime),
    }

    return retdata, retcode


@ZKConnection(config)
def update_vm_meta(
    zkhandler,
    vm,
    limit,
    selector,
    autostart,
    provisioner_profile,
    migration_method,
    migration_max_downtime,
):
    """
    Update metadata of a VM.
    """
    dom_uuid = pvc_vm.getDomainUUID(zkhandler, vm)
    if not dom_uuid:
        return {"message": "VM not found."}, 404

    if autostart is not None:
        try:
            autostart = bool(strtobool(autostart))
        except Exception:
            autostart = False

    retflag, retdata = pvc_vm.modify_vm_metadata(
        zkhandler,
        vm,
        limit,
        selector,
        autostart,
        provisioner_profile,
        migration_method,
        migration_max_downtime,
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def get_vm_tags(zkhandler, vm):
    """
    Get the tags of a VM.
    """
    dom_uuid = pvc_vm.getDomainUUID(zkhandler, vm)
    if not dom_uuid:
        return {"message": "VM not found."}, 404

    tags = pvc_common.getDomainTags(zkhandler, dom_uuid)

    retcode = 200
    retdata = {"name": vm, "tags": tags}

    return retdata, retcode


@ZKConnection(config)
def update_vm_tag(zkhandler, vm, action, tag, protected=False):
    """
    Update a tag of a VM.
    """
    if action not in ["add", "remove"]:
        return {"message": "Tag action must be one of 'add', 'remove'."}, 400

    dom_uuid = pvc_vm.getDomainUUID(zkhandler, vm)
    if not dom_uuid:
        return {"message": "VM not found."}, 404

    retflag, retdata = pvc_vm.modify_vm_tag(
        zkhandler, vm, action, tag, protected=protected
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_modify(zkhandler, name, restart, xml):
    """
    Modify a VM Libvirt XML in the PVC cluster.
    """
    # Verify our XML is sensible
    try:
        xml_data = etree.fromstring(xml)
        new_cfg = etree.tostring(xml_data, pretty_print=True).decode("utf8")
    except Exception as e:
        return {"message": "XML is malformed or incorrect: {}".format(e)}, 400

    retflag, retdata = pvc_vm.modify_vm(zkhandler, name, restart, new_cfg)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_rename(zkhandler, name, new_name):
    """
    Rename a VM in the PVC cluster.
    """
    if new_name is None:
        output = {"message": "A new VM name must be specified"}
        return 400, output

    if pvc_vm.searchClusterByName(zkhandler, new_name) is not None:
        output = {
            "message": "A VM named '{}' is already present in the cluster".format(
                new_name
            )
        }
        return 400, output

    retflag, retdata = pvc_vm.rename_vm(zkhandler, name, new_name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_undefine(zkhandler, name):
    """
    Undefine a VM from the PVC cluster.
    """
    retflag, retdata = pvc_vm.undefine_vm(zkhandler, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_remove(zkhandler, name):
    """
    Remove a VM from the PVC cluster.
    """
    retflag, retdata = pvc_vm.remove_vm(zkhandler, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_start(zkhandler, name, force=False):
    """
    Start a VM in the PVC cluster.
    """
    retflag, retdata = pvc_vm.start_vm(zkhandler, name, force=force)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_restart(zkhandler, name, wait=False):
    """
    Restart a VM in the PVC cluster.
    """
    retflag, retdata = pvc_vm.restart_vm(zkhandler, name, wait=wait)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_shutdown(zkhandler, name, wait):
    """
    Shutdown a VM in the PVC cluster.
    """
    retflag, retdata = pvc_vm.shutdown_vm(zkhandler, name, wait)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_stop(zkhandler, name, force=False):
    """
    Forcibly stop a VM in the PVC cluster.
    """
    retflag, retdata = pvc_vm.stop_vm(zkhandler, name, force=force)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_disable(zkhandler, name, force=False):
    """
    Disable (shutdown or force stop if required) a VM in the PVC cluster.
    """
    retflag, retdata = pvc_vm.disable_vm(zkhandler, name, force=force)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_move(zkhandler, name, node, wait, force_live):
    """
    Move a VM to another node.
    """
    retflag, retdata = pvc_vm.move_vm(zkhandler, name, node, wait, force_live)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_migrate(zkhandler, name, node, flag_force, wait, force_live):
    """
    Temporarily migrate a VM to another node.
    """
    retflag, retdata = pvc_vm.migrate_vm(
        zkhandler, name, node, flag_force, wait, force_live
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_unmigrate(zkhandler, name, wait, force_live):
    """
    Unmigrate a migrated VM.
    """
    retflag, retdata = pvc_vm.unmigrate_vm(zkhandler, name, wait, force_live)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_flush_locks(zkhandler, vm):
    """
    Flush locks of a (stopped) VM.
    """
    retflag, retdata = pvc_vm.get_list(
        zkhandler, None, None, None, vm, is_fuzzy=False, negate=False
    )

    if retdata[0].get("state") not in ["stop", "disable", "mirror"]:
        return {"message": "VM must be stopped to flush locks"}, 400

    retflag, retdata = pvc_vm.flush_locks(zkhandler, vm)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def vm_snapshot_receive_block_full(zkhandler, pool, volume, snapshot, size, request):
    """
    Receive an RBD volume from a remote system
    """
    import rados
    import rbd

    _, rbd_detail = pvc_ceph.get_list_volume(
        zkhandler, pool, limit=volume, is_fuzzy=False
    )
    if len(rbd_detail) > 0:
        volume_exists = True
    else:
        volume_exists = False

    cluster = rados.Rados(conffile="/etc/ceph/ceph.conf")
    cluster.connect()
    ioctx = cluster.open_ioctx(pool)

    if not volume_exists:
        rbd_inst = rbd.RBD()
        rbd_inst.create(ioctx, volume, size)
        retflag, retdata = pvc_ceph.add_volume(
            zkhandler, pool, volume, str(size) + "B", force_flag=True, zk_only=True
        )
        if not retflag:
            ioctx.close()
            cluster.shutdown()

            if retflag:
                retcode = 200
            else:
                retcode = 400

            output = {"message": retdata.replace('"', "'")}
            return output, retcode

    image = rbd.Image(ioctx, volume)

    last_chunk = 0
    chunk_size = 1024 * 1024 * 1024

    logger.info(f"Importing full snapshot {pool}/{volume}@{snapshot}")
    while True:
        chunk = request.stream.read(chunk_size)
        if not chunk:
            break
        image.write(chunk, last_chunk)
        last_chunk += len(chunk)

    image.close()
    ioctx.close()
    cluster.shutdown()

    return {"message": "Successfully received RBD block device"}, 200


@ZKConnection(config)
def vm_snapshot_receive_block_diff(
    zkhandler, pool, volume, snapshot, source_snapshot, request
):
    """
    Receive an RBD volume from a remote system
    """
    import rados
    import rbd

    cluster = rados.Rados(conffile="/etc/ceph/ceph.conf")
    cluster.connect()
    ioctx = cluster.open_ioctx(pool)
    image = rbd.Image(ioctx, volume)

    if len(request.files) > 0:
        logger.info(f"Applying {len(request.files)} RBD diff chunks for {snapshot}")

        for i in range(len(request.files)):
            object_key = f"object_{i}"
            if object_key in request.files:
                object_data = request.files[object_key].read()
                offset = int.from_bytes(object_data[:8], "big")
                length = int.from_bytes(object_data[8:16], "big")
                data = object_data[16 : 16 + length]
                logger.info(f"Applying RBD diff chunk at {offset} ({length} bytes)")
                image.write(data, offset)
    else:
        return {"message": "No data received"}, 400

    image.close()
    ioctx.close()
    cluster.shutdown()

    return {
        "message": f"Successfully received {len(request.files)} RBD diff chunks"
    }, 200


@ZKConnection(config)
def vm_snapshot_receive_block_createsnap(zkhandler, pool, volume, snapshot):
    """
    Create the snapshot of a remote volume
    """
    import rados
    import rbd

    cluster = rados.Rados(conffile="/etc/ceph/ceph.conf")
    cluster.connect()
    ioctx = cluster.open_ioctx(pool)
    image = rbd.Image(ioctx, volume)
    image.create_snap(snapshot)
    image.close()
    ioctx.close()
    cluster.shutdown()

    retflag, retdata = pvc_ceph.add_snapshot(
        zkhandler, pool, volume, snapshot, zk_only=True
    )
    if not retflag:

        if retflag:
            retcode = 200
        else:
            retcode = 400

        output = {"message": retdata.replace('"', "'")}
        return output, retcode

    return {"message": "Successfully received RBD snapshot"}, 200


@ZKConnection(config)
def vm_snapshot_receive_config(zkhandler, snapshot, vm_config, source_snapshot=None):
    """
    Receive a VM configuration snapshot from a remote system, and modify it to work on our system
    """

    def parse_unified_diff(diff_text, original_text):
        """
        Take a unified diff and apply it to an original string
        """
        # Split the original string into lines
        original_lines = original_text.splitlines(keepends=True)
        patched_lines = []
        original_idx = 0  # Track position in original lines

        diff_lines = diff_text.splitlines(keepends=True)

        for line in diff_lines:
            if line.startswith("---") or line.startswith("+++"):
                # Ignore prefix lines
                continue
            if line.startswith("@@"):
                # Extract line numbers from the diff hunk header
                hunk_header = line
                parts = hunk_header.split(" ")
                original_range = parts[1]

                # Get the starting line number and range length for the original file
                original_start, _ = map(int, original_range[1:].split(","))

                # Adjust for zero-based indexing
                original_start -= 1

                # Add any lines between the current index and the next hunk's start
                while original_idx < original_start:
                    patched_lines.append(original_lines[original_idx])
                    original_idx += 1

            elif line.startswith("-"):
                # This line should be removed from the original, skip it
                original_idx += 1
            elif line.startswith("+"):
                # This line should be added to the patched version, removing the '+'
                patched_lines.append(line[1:])
            else:
                # Context line (unchanged), it has no prefix, add from the original
                patched_lines.append(original_lines[original_idx])
                original_idx += 1

        # Add any remaining lines from the original file after the last hunk
        patched_lines.extend(original_lines[original_idx:])

        return "".join(patched_lines).strip()

    # Get our XML configuration for this snapshot
    # We take the main XML configuration, then apply the diff for this particular incremental
    current_snapshot = [s for s in vm_config["snapshots"] if s["name"] == snapshot][0]
    vm_xml = vm_config["xml"]
    vm_xml_diff = "\n".join(current_snapshot["xml_diff_lines"])
    snapshot_vm_xml = parse_unified_diff(vm_xml_diff, vm_xml)
    xml_data = etree.fromstring(snapshot_vm_xml)

    # Replace the Ceph storage secret UUID with this cluster's
    our_ceph_secret_uuid = config["ceph_secret_uuid"]
    ceph_secrets = xml_data.xpath("//secret[@type='ceph']")
    for ceph_secret in ceph_secrets:
        ceph_secret.set("uuid", our_ceph_secret_uuid)

    # Replace the Ceph source hosts with this cluster's
    our_ceph_storage_hosts = config["storage_hosts"]
    our_ceph_storage_port = str(config["ceph_monitor_port"])
    ceph_sources = xml_data.xpath("//source[@protocol='rbd']")
    for ceph_source in ceph_sources:
        for host in ceph_source.xpath("host"):
            ceph_source.remove(host)
        for ceph_storage_host in our_ceph_storage_hosts:
            new_host = etree.Element("host")
            new_host.set("name", ceph_storage_host)
            new_host.set("port", our_ceph_storage_port)
            ceph_source.append(new_host)

    # Regenerate the VM XML
    snapshot_vm_xml = etree.tostring(xml_data, pretty_print=True).decode("utf8")

    if (
        source_snapshot is not None
        or pvc_vm.searchClusterByUUID(zkhandler, vm_config["uuid"]) is not None
    ):
        logger.info(
            f"Receiving incremental VM configuration for {vm_config['name']}@{snapshot}"
        )

        # Modify the VM based on our passed detail
        retcode, retmsg = pvc_vm.modify_vm(
            zkhandler,
            vm_config["uuid"],
            False,
            snapshot_vm_xml,
        )
        if not retcode:
            retcode = 400
            retdata = {"message": retmsg}
            return retdata, retcode

        retcode, retmsg = pvc_vm.modify_vm_metadata(
            zkhandler,
            vm_config["uuid"],
            None,  # Node limits are left unchanged
            vm_config["node_selector"],
            vm_config["node_autostart"],
            vm_config["profile"],
            vm_config["migration_method"],
            vm_config["migration_max_downtime"],
        )
        if not retcode:
            retcode = 400
            retdata = {"message": retmsg}
            return retdata, retcode

        current_vm_tags = zkhandler.children(("domain.meta.tags", vm_config["uuid"]))
        new_vm_tags = [t["name"] for t in vm_config["tags"]]
        remove_tags = []
        add_tags = []
        for tag in vm_config["tags"]:
            if tag["name"] not in current_vm_tags:
                add_tags.append((tag["name"], tag["protected"]))
        for tag in current_vm_tags:
            if tag not in new_vm_tags:
                remove_tags.append(tag)

        for tag in add_tags:
            name, protected = tag
            pvc_vm.modify_vm_tag(
                zkhandler, vm_config["uuid"], "add", name, protected=protected
            )
        for tag in remove_tags:
            pvc_vm.modify_vm_tag(zkhandler, vm_config["uuid"], "remove", name)
    else:
        logger.info(
            f"Receiving full VM configuration for {vm_config['name']}@{snapshot}"
        )

        # Define the VM based on our passed detail
        retcode, retmsg = pvc_vm.define_vm(
            zkhandler,
            snapshot_vm_xml,
            None,  # Target node is autoselected
            None,  # Node limits are invalid here so ignore them
            vm_config["node_selector"],
            vm_config["node_autostart"],
            vm_config["migration_method"],
            vm_config["migration_max_downtime"],
            vm_config["profile"],
            vm_config["tags"],
            "mirror",
        )
        if not retcode:
            retcode = 400
            retdata = {"message": retmsg}
            return retdata, retcode

    # Add this snapshot to the VM manually in Zookeeper
    zkhandler.write(
        [
            (
                (
                    "domain.snapshots",
                    vm_config["uuid"],
                    "domain_snapshot.name",
                    snapshot,
                ),
                snapshot,
            ),
            (
                (
                    "domain.snapshots",
                    vm_config["uuid"],
                    "domain_snapshot.timestamp",
                    snapshot,
                ),
                current_snapshot["timestamp"],
            ),
            (
                (
                    "domain.snapshots",
                    vm_config["uuid"],
                    "domain_snapshot.xml",
                    snapshot,
                ),
                snapshot_vm_xml,
            ),
            (
                (
                    "domain.snapshots",
                    vm_config["uuid"],
                    "domain_snapshot.rbd_snapshots",
                    snapshot,
                ),
                ",".join(current_snapshot["rbd_snapshots"]),
            ),
        ]
    )

    return {"message": "Successfully received VM configuration snapshot"}, 200


#
# Network functions
#
@pvc_common.Profiler(config)
@ZKConnection(config)
def net_list(zkhandler, limit=None, is_fuzzy=True):
    """
    Return a list of client networks with limit LIMIT.
    """
    retflag, retdata = pvc_network.get_list(zkhandler, limit, is_fuzzy)

    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {"message": "Network not found."}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@ZKConnection(config)
def net_add(
    zkhandler,
    vni,
    description,
    nettype,
    mtu,
    domain,
    name_servers,
    ip4_network,
    ip4_gateway,
    ip6_network,
    ip6_gateway,
    dhcp4_flag,
    dhcp4_start,
    dhcp4_end,
):
    """
    Add a virtual client network to the PVC cluster.
    """
    if dhcp4_flag:
        dhcp4_flag = bool(strtobool(dhcp4_flag))
    retflag, retdata = pvc_network.add_network(
        zkhandler,
        vni,
        description,
        nettype,
        mtu,
        domain,
        name_servers,
        ip4_network,
        ip4_gateway,
        ip6_network,
        ip6_gateway,
        dhcp4_flag,
        dhcp4_start,
        dhcp4_end,
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def net_modify(
    zkhandler,
    vni,
    description,
    mtu,
    domain,
    name_servers,
    ip4_network,
    ip4_gateway,
    ip6_network,
    ip6_gateway,
    dhcp4_flag,
    dhcp4_start,
    dhcp4_end,
):
    """
    Modify a virtual client network in the PVC cluster.
    """
    if dhcp4_flag is not None:
        dhcp4_flag = bool(strtobool(dhcp4_flag))
    retflag, retdata = pvc_network.modify_network(
        zkhandler,
        vni,
        description,
        mtu,
        domain,
        name_servers,
        ip4_network,
        ip4_gateway,
        ip6_network,
        ip6_gateway,
        dhcp4_flag,
        dhcp4_start,
        dhcp4_end,
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def net_remove(zkhandler, network):
    """
    Remove a virtual client network from the PVC cluster.
    """
    retflag, retdata = pvc_network.remove_network(zkhandler, network)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def net_dhcp_list(zkhandler, network, limit=None, static=False):
    """
    Return a list of DHCP leases in network NETWORK with limit LIMIT.
    """
    retflag, retdata = pvc_network.get_list_dhcp(zkhandler, network, limit, static)

    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {"message": "Lease not found."}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@ZKConnection(config)
def net_dhcp_add(zkhandler, network, ipaddress, macaddress, hostname):
    """
    Add a static DHCP lease to a virtual client network.
    """
    retflag, retdata = pvc_network.add_dhcp_reservation(
        zkhandler, network, ipaddress, macaddress, hostname
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def net_dhcp_remove(zkhandler, network, macaddress):
    """
    Remove a static DHCP lease from a virtual client network.
    """
    retflag, retdata = pvc_network.remove_dhcp_reservation(
        zkhandler, network, macaddress
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def net_acl_list(zkhandler, network, limit=None, direction=None, is_fuzzy=True):
    """
    Return a list of network ACLs in network NETWORK with limit LIMIT.
    """
    retflag, retdata = pvc_network.get_list_acl(
        zkhandler, network, limit, direction, is_fuzzy=True
    )

    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {"message": "ACL not found."}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@ZKConnection(config)
def net_acl_add(zkhandler, network, direction, description, rule, order):
    """
    Add an ACL to a virtual client network.
    """
    retflag, retdata = pvc_network.add_acl(
        zkhandler, network, direction, description, rule, order
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def net_acl_remove(zkhandler, network, description):
    """
    Remove an ACL from a virtual client network.
    """
    retflag, retdata = pvc_network.remove_acl(zkhandler, network, description)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


#
# SR-IOV functions
#
@pvc_common.Profiler(config)
@ZKConnection(config)
def sriov_pf_list(zkhandler, node):
    """
    List all PFs on a given node.
    """
    retflag, retdata = pvc_network.get_list_sriov_pf(zkhandler, node)

    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {"message": "PF not found."}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def sriov_vf_list(zkhandler, node, pf=None):
    """
    List all VFs on a given node, optionally limited to PF.
    """
    retflag, retdata = pvc_network.get_list_sriov_vf(zkhandler, node, pf)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {"message": "VF not found."}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@ZKConnection(config)
def update_sriov_vf_config(
    zkhandler,
    node,
    vf,
    vlan_id,
    vlan_qos,
    tx_rate_min,
    tx_rate_max,
    link_state,
    spoof_check,
    trust,
    query_rss,
):
    """
    Update configuration of a VF on NODE.
    """
    retflag, retdata = pvc_network.set_sriov_vf_config(
        zkhandler,
        node,
        vf,
        vlan_id,
        vlan_qos,
        tx_rate_min,
        tx_rate_max,
        link_state,
        spoof_check,
        trust,
        query_rss,
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


#
# Ceph functions
#
@ZKConnection(config)
def ceph_status(zkhandler):
    """
    Get the current Ceph cluster status.
    """
    retflag, retdata = pvc_ceph.get_status(zkhandler)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    return retdata, retcode


@ZKConnection(config)
def ceph_util(zkhandler):
    """
    Get the current Ceph cluster utilization.
    """
    retflag, retdata = pvc_ceph.get_util(zkhandler)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    return retdata, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def ceph_osd_list(zkhandler, limit=None):
    """
    Get the list of OSDs in the Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.get_list_osd(zkhandler, limit)

    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {"message": "OSD not found."}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def ceph_osd_node(zkhandler, osd):
    """
    Return the current node of OSD OSD.
    """
    retflag, retdata = pvc_ceph.get_list_osd(zkhandler, None)

    if retflag:
        if retdata:
            osd = [o for o in retdata if o["id"] == osd]
            if len(osd) < 1:
                retcode = 404
                retdata = {"message": "OSD not found."}
            else:
                retcode = 200
                retdata = {
                    "id": osd[0]["id"],
                    "node": osd[0]["node"],
                }
        else:
            retcode = 404
            retdata = {"message": "OSD not found."}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@ZKConnection(config)
def ceph_osd_state(zkhandler, osd):
    retflag, retdata = pvc_ceph.get_list_osd(zkhandler, osd)

    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {"message": "OSD not found."}
    else:
        retcode = 400
        retdata = {"message": retdata}

    in_state = retdata[0]["stats"]["in"]
    up_state = retdata[0]["stats"]["up"]

    return {"id": osd, "in": in_state, "up": up_state}, retcode


@ZKConnection(config)
def ceph_osd_db_vg_add(zkhandler, node, device):
    """
    Add a Ceph OSD database VG to the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.add_osd_db_vg(zkhandler, node, device)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_osd_add(
    zkhandler,
    node,
    device,
    weight,
    ext_db_ratio=None,
    ext_db_size=None,
    split_count=None,
):
    """
    Add a Ceph OSD to the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.add_osd(
        zkhandler,
        node,
        device,
        weight,
        ext_db_ratio,
        ext_db_size,
        split_count,
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_osd_replace(
    zkhandler,
    osd_id,
    new_device,
    old_device=None,
    weight=None,
    ext_db_ratio=None,
    ext_db_size=None,
):
    """
    Replace a Ceph OSD in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.replace_osd(
        zkhandler, osd_id, new_device, old_device, weight, ext_db_ratio, ext_db_size
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_osd_refresh(zkhandler, osd_id, device):
    """
    Refresh (reimport) a Ceph OSD in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.refresh_osd(zkhandler, osd_id, device)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_osd_remove(zkhandler, osd_id, force_flag):
    """
    Remove a Ceph OSD from the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.remove_osd(zkhandler, osd_id, force_flag)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_osd_in(zkhandler, osd_id):
    """
    Set in a Ceph OSD in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.in_osd(zkhandler, osd_id)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_osd_out(zkhandler, osd_id):
    """
    Set out a Ceph OSD in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.out_osd(zkhandler, osd_id)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_osd_set(zkhandler, option):
    """
    Set options on a Ceph OSD in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.set_osd(zkhandler, option)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_osd_unset(zkhandler, option):
    """
    Unset options on a Ceph OSD in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.unset_osd(zkhandler, option)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def ceph_pool_list(zkhandler, limit=None, is_fuzzy=True):
    """
    Get the list of RBD pools in the Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.get_list_pool(zkhandler, limit, is_fuzzy)

    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {"message": "Pool not found."}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@ZKConnection(config)
def ceph_pool_add(zkhandler, name, pgs, replcfg, tier=None):
    """
    Add a Ceph RBD pool to the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.add_pool(zkhandler, name, pgs, replcfg, tier)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata}
    return output, retcode


@ZKConnection(config)
def ceph_pool_remove(zkhandler, name):
    """
    Remove a Ceph RBD pool to the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.remove_pool(zkhandler, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_pool_set_pgs(zkhandler, name, pgs):
    """
    Set the PGs of a ceph RBD pool.
    """
    retflag, retdata = pvc_ceph.set_pgs_pool(zkhandler, name, pgs)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def ceph_volume_list(zkhandler, pool=None, limit=None, is_fuzzy=True):
    """
    Get the list of RBD volumes in the Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.get_list_volume(zkhandler, pool, limit, is_fuzzy)

    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {"message": "Volume not found."}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@ZKConnection(config)
def ceph_volume_scan(zkhandler, pool, name):
    """
    (Re)scan a Ceph RBD volume for stats in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.scan_volume(zkhandler, pool, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_volume_add(zkhandler, pool, name, size, force_flag=False):
    """
    Add a Ceph RBD volume to the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.add_volume(
        zkhandler, pool, name, size, force_flag=force_flag
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_volume_clone(zkhandler, pool, name, source_volume, force_flag):
    """
    Clone a Ceph RBD volume to a new volume on the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.clone_volume(
        zkhandler, pool, source_volume, name, force_flag=force_flag
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_volume_resize(zkhandler, pool, name, size, force_flag):
    """
    Resize an existing Ceph RBD volume in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.resize_volume(
        zkhandler, pool, name, size, force_flag=force_flag
    )

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_volume_rename(zkhandler, pool, name, new_name):
    """
    Rename a Ceph RBD volume in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.rename_volume(zkhandler, pool, name, new_name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_volume_remove(zkhandler, pool, name):
    """
    Remove a Ceph RBD volume to the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.remove_volume(zkhandler, pool, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_volume_upload(zkhandler, pool, volume, img_type, file_size=None):
    """
    Upload a raw file via HTTP post to a PVC Ceph volume
    """
    # Determine the image conversion options
    if img_type not in ["raw", "vmdk", "qcow2", "qed", "vdi", "vpc"]:
        output = {"message": "Image type '{}' is not valid.".format(img_type)}
        retcode = 400
        return output, retcode

    # Get the size of the target block device
    retcode, retdata = pvc_ceph.get_list_volume(zkhandler, pool, volume, is_fuzzy=False)
    # If there's no target, return failure
    if not retcode or len(retdata) < 1:
        output = {
            "message": "Target volume '{}' does not exist in pool '{}'.".format(
                volume, pool
            )
        }
        retcode = 400
        return output, retcode

    try:
        dev_size = retdata[0]["stats"]["size"]
    except Exception:
        output = {
            "message": "Target volume '{}' does not exist in pool '{}'.".format(
                volume, pool
            )
        }
        retcode = 400
        return output, retcode

    def cleanup_maps_and_volumes():
        # Unmap the target blockdev
        retflag, retdata = pvc_ceph.unmap_volume(zkhandler, pool, volume)
        # Unmap the temporary blockdev
        retflag, retdata = pvc_ceph.unmap_volume(
            zkhandler, pool, "{}_tmp".format(volume)
        )
        # Remove the temporary blockdev
        retflag, retdata = pvc_ceph.remove_volume(
            zkhandler, pool, "{}_tmp".format(volume)
        )

    if img_type == "raw":
        if file_size is not None and file_size != dev_size:
            output = {
                "message": f"Image file size {file_size} does not match volume size {dev_size}"
            }
            retcode = 400
            return output, retcode

        # Map the target blockdev
        retflag, retdata = pvc_ceph.map_volume(zkhandler, pool, volume)
        if not retflag:
            output = {"message": retdata.replace('"', "'")}
            retcode = 400
            cleanup_maps_and_volumes()
            return output, retcode
        dest_blockdev = retdata

        # Save the data to the blockdev directly
        try:
            # This sets up a custom stream_factory that writes directly into the ova_blockdev,
            # rather than the standard stream_factory which writes to a temporary file waiting
            # on a save() call. This will break if the API ever uploaded multiple files, but
            # this is an acceptable workaround.
            def image_stream_factory(
                total_content_length, filename, content_type, content_length=None
            ):
                return open(dest_blockdev, "wb")

            parse_form_data(flask.request.environ, stream_factory=image_stream_factory)
        except Exception:
            output = {
                "message": "Failed to upload or write image file to temporary volume."
            }
            retcode = 400
            cleanup_maps_and_volumes()
            return output, retcode

        output = {
            "message": "Wrote uploaded file to volume '{}' in pool '{}'.".format(
                volume, pool
            )
        }
        retcode = 200
        cleanup_maps_and_volumes()
        return output, retcode

    else:
        if file_size is None:
            output = {"message": "A file size must be specified"}
            retcode = 400
            return output, retcode

        # Create a temporary blockdev
        retflag, retdata = pvc_ceph.add_volume(
            zkhandler, pool, "{}_tmp".format(volume), file_size
        )
        if not retflag:
            output = {"message": retdata.replace('"', "'")}
            retcode = 400
            cleanup_maps_and_volumes()
            return output, retcode

        # Map the temporary target blockdev
        retflag, retdata = pvc_ceph.map_volume(zkhandler, pool, "{}_tmp".format(volume))
        if not retflag:
            output = {"message": retdata.replace('"', "'")}
            retcode = 400
            cleanup_maps_and_volumes()
            return output, retcode
        temp_blockdev = retdata

        # Map the target blockdev
        retflag, retdata = pvc_ceph.map_volume(zkhandler, pool, volume)
        if not retflag:
            output = {"message": retdata.replace('"', "'")}
            retcode = 400
            cleanup_maps_and_volumes()
            return output, retcode
        dest_blockdev = retdata

        # Save the data to the temporary blockdev directly
        try:
            # This sets up a custom stream_factory that writes directly into the ova_blockdev,
            # rather than the standard stream_factory which writes to a temporary file waiting
            # on a save() call. This will break if the API ever uploaded multiple files, but
            # this is an acceptable workaround.
            def image_stream_factory(
                total_content_length, filename, content_type, content_length=None
            ):
                return open(temp_blockdev, "wb")

            parse_form_data(flask.request.environ, stream_factory=image_stream_factory)
        except Exception:
            output = {
                "message": "Failed to upload or write image file to temporary volume."
            }
            retcode = 400
            cleanup_maps_and_volumes()
            return output, retcode

        # Convert from the temporary to destination format on the blockdevs
        retcode, stdout, stderr = pvc_common.run_os_command(
            "qemu-img convert -C -f {} -O raw {} {}".format(
                img_type, temp_blockdev, dest_blockdev
            )
        )
        if retcode:
            output = {
                "message": "Failed to convert image format from '{}' to 'raw': {}".format(
                    img_type, stderr
                )
            }
            retcode = 400
            cleanup_maps_and_volumes()
            return output, retcode

        output = {
            "message": "Converted and wrote uploaded file to volume '{}' in pool '{}'.".format(
                volume, pool
            )
        }
        retcode = 200
        cleanup_maps_and_volumes()
        return output, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def ceph_volume_snapshot_list(
    zkhandler, pool=None, volume=None, limit=None, is_fuzzy=True
):
    """
    Get the list of RBD volume snapshots in the Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.get_list_snapshot(
        zkhandler, pool, volume, limit, is_fuzzy
    )

    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {"message": "Volume snapshot not found."}
    else:
        retcode = 400
        retdata = {"message": retdata}

    return retdata, retcode


@ZKConnection(config)
def ceph_volume_snapshot_add(zkhandler, pool, volume, name):
    """
    Add a Ceph RBD volume snapshot to the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.add_snapshot(zkhandler, pool, volume, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_volume_snapshot_rename(zkhandler, pool, volume, name, new_name):
    """
    Rename a Ceph RBD volume snapshot in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.rename_snapshot(zkhandler, pool, volume, name, new_name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_volume_snapshot_rollback(zkhandler, pool, volume, name):
    """
    Roll back a Ceph RBD volume to a given snapshot in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.rollback_snapshot(zkhandler, pool, volume, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode


@ZKConnection(config)
def ceph_volume_snapshot_remove(zkhandler, pool, volume, name):
    """
    Remove a Ceph RBD volume snapshot from the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.remove_snapshot(zkhandler, pool, volume, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {"message": retdata.replace('"', "'")}
    return output, retcode
