#!/usr/bin/env python3

# pvcapi.py - PVC HTTP API functions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018  Joshua M. Boniface <joshua@boniface.me>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
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

import client_lib.common as pvc_common
import client_lib.node as pvc_node
import client_lib.vm as pvc_vm
import client_lib.network as pvc_network
import client_lib.ceph as pvc_ceph

zk_host = "hv1:2181,hv2:2181,hv3:2181"

#
# Node functions
#
def node_list(limit=None):
    """
    Return a list of nodes with limit LIMIT.
    """
    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_node.get_list(zk_conn, limit)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def node_secondary(node):
    """
    Take NODE out of primary router mode.
    """
    zk_conn = pvc_common.startZKConnection(zk_host) 
    retflag, retmsg = pvc_node.secondary_node(zk_conn, node)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retmsg,
    }
    return flask.jsonify(output), retcode

def node_primary(node):
    """
    Set NODE to primary router mode.
    """
    zk_conn = pvc_common.startZKConnection(zk_host) 
    retflag, retmsg = pvc_node.primary_node(zk_conn, node)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retmsg,
    }
    return flask.jsonify(output), retcode

def node_flush(node):
    """
    Flush NODE of running VMs.
    """
    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retmsg = pvc_node.flush_node(zk_conn, node, False)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retmsg,
    }
    return flask.jsonify(output), retcode

def node_ready(node):
    """
    Restore NODE to active service.
    """
    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retmsg = pvc_node.ready_node(zk_conn, node)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retmsg,
    }
    return flask.jsonify(output), retcode

#
# VM functions
#
def vm_list(node=None, state=None, limit=None):
    """
    Return a list of VMs with limit LIMIT.
    """
    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_vm.get_list(zk_conn, node, state, limit)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def vm_add():
    """
    Add a VM named NAME to the PVC cluster.
    """
    return '', 200

def vm_define():
    """
    Define a VM from Libvirt XML in the PVC cluster.
    """
    return '', 200

def vm_modify():
    """
    Modify a VM Libvirt XML in the PVC cluster.
    """
    return '', 200

def vm_undefine():
    """
    Undefine a VM from the PVC cluster.
    """
    return '', 200

def vm_dump():
    """
    Dump a VM Libvirt XML configuration.
    """
    return '', 200

def vm_start():
    """
    Start a VM in the PVC cluster.
    """
    return '', 200

def vm_restart():
    """
    Restart a VM in the PVC cluster.
    """
    return '', 200

def vm_shutdown():
    """
    Shutdown a VM in the PVC cluster.
    """
    return '', 200

def vm_stop():
    """
    Forcibly stop a VM in the PVC cluster.
    """
    return '', 200

def vm_move():
    """
    Move a VM to another node.
    """
    return '', 200

def vm_migrate():
    """
    Temporarily migrate a VM to another node.
    """
    return '', 200

def vm_unmigrate():
    """
    Unmigrate a migrated VM.
    """
    return '', 200

#
# Network functions
#
def net_list(limit=None):
    """
    Return a list of client networks with limit LIMIT.
    """
    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_network.get_list(zk_conn, limit)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def net_add():
    """
    Add a virtual client network to the PVC cluster.
    """
    return '', 200

def net_modify():
    """
    Modify a virtual client network in the PVC cluster.
    """
    return '', 200

def net_remove():
    """
    Remove a virtual client network from the PVC cluster.
    """
    return '', 200

def net_dhcp_list(network, limit=None, static=False):
    """
    Return a list of DHCP leases in network NETWORK with limit LIMIT.
    """
    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_network.get_list_dhcp(zk_conn, network, limit, static)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def net_dhcp_add():
    """
    Add a static DHCP lease to a virtual client network.
    """
    return '', 200

def net_dhcp_remove():
    """
    Remove a static DHCP lease from a virtual client network.
    """
    return '', 200

def net_acl_list(network, limit=None, direction=None):
    """
    Return a list of network ACLs in network NETWORK with limit LIMIT.
    """
    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_network.get_list_acl(zk_conn, network, limit, direction)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def net_acl_add():
    """
    Add an ACL to a virtual client network.
    """
    return '', 200

def net_acl_remove():
    """
    Remove an ACL from a virtual client network.
    """
    return '', 200

#
# Ceph functions
#
def ceph_status():
    """
    Get the current Ceph cluster status.
    """
    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_ceph.get_status(zk_conn)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def ceph_osd_list(limit=None):
    """
    Get the list of OSDs in the Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_ceph.get_list_osd(zk_conn, limit)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def ceph_osd_add():
    """
    Add a Ceph OSD to the PVC Ceph storage cluster.
    """
    return '', 200

def ceph_osd_remove():
    """
    Remove a Ceph OSD from the PVC Ceph storage cluster.
    """
    return '', 200

def ceph_osd_in():
    """
    Set in a Ceph OSD in the PVC Ceph storage cluster.
    """
    return '', 200

def ceph_osd_out():
    """
    Set out a Ceph OSD in the PVC Ceph storage cluster.
    """
    return '', 200

def ceph_osd_set():
    """
    Set options on a Ceph OSD in the PVC Ceph storage cluster.
    """
    return '', 200

def ceph_osd_unset():
    """
    Unset options on a Ceph OSD in the PVC Ceph storage cluster.
    """
    return '', 200

def ceph_pool_list(limit=None):
    """
    Get the list of RBD pools in the Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_ceph.get_list_pool(zk_conn, limit)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def ceph_pool_add():
    """
    Add a Ceph RBD pool to the PVC Ceph storage cluster.
    """
    return '', 200

def ceph_pool_remove():
    """
    Remove a Ceph RBD pool to the PVC Ceph storage cluster.
    """
    return '', 200

def ceph_volume_list(pool=None, limit=None):
    """
    Get the list of RBD volumes in the Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_ceph.get_list_volume(zk_conn, pool, limit)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def ceph_volume_add():
    """
    Add a Ceph RBD volume to the PVC Ceph storage cluster.
    """
    return '', 200

def ceph_volume_remove():
    """
    Remove a Ceph RBD volume to the PVC Ceph storage cluster.
    """
    return '', 200

def ceph_volume_snapshot_list(pool=None, volume=None, limit=None):
    """
    Get the list of RBD volume snapshots in the Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_ceph.get_list_snapshot(zk_conn, pool, volume, limit)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def ceph_volume_snapshot_add():
    """
    Add a Ceph RBD volume snapshot to the PVC Ceph storage cluster.
    """
    return '', 200

def ceph_volume_snapshot_remove():
    """
    Remove a Ceph RBD volume snapshot to the PVC Ceph storage cluster.
    """
    return '', 200

