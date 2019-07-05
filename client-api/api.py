#!/usr/bin/env python3

# api.py - PVC HTTP API interface
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

import api_lib.pvcapi as pvcapi

zk_host = "hv1:2181,hv2:2181,hv3:2181"

api = flask.Flask(__name__)
api.config["DEBUG"] = True

@api.route('/api/v1', methods=['GET'])
def api_root():
    return "PVC API version 1", 209

#
# Node endpoints
#
@api.route('/api/v1/node', methods=['GET'])
def api_node():
    """
    Return a list of nodes.
    """
    return pvcapi.node_list()

@api.route('/api/v1/node/<name>', methods=['GET'])
def api_node_name(name):
    """
    Return information about node NAME.
    """
    return pvcapi.node_list(name)

@api.route('/api/v1/node/secondary', methods=['POST'])
def api_node_secondary():
    """
    Take NODE out of primary router mode.
    """
    # Get node
    if 'node' in flask.request.values:
        node = flask.request.values['node']
    else:
        return "Error: No node provided. Please specify a node.\n", 510

    return pvcapi.node_secondary(node)

@api.route('/api/v1/node/primary', methods=['POST'])
def api_node_primary():
    """
    Set NODE to primary router mode.
    """
    # Get node
    if 'node' in flask.request.values:
        node = flask.request.values['node']
    else:
        return "Error: No node provided. Please specify a node.\n", 510

    return pvcapi.node_primary(node)

@api.route('/api/v1/node/flush', methods=['POST'])
def api_node_flush():
    """
    Flush NODE of running VMs.
    """
    # Get node
    if 'node' in flask.request.values:
        node = flask.request.values['node']
    else:
        return "Error: No node provided. Please specify a node.\n", 510

    return pvcapi.node_flush(node)

@api.route('/api/v1/node/unflush', methods=['POST'])
@api.route('/api/v1/node/ready', methods=['POST'])
def api_node_ready():
    """
    Restore NODE to active service.
    """
    # Get node
    if 'node' in flask.request.values:
        node = flask.request.values['node']
    else:
        return "Error: No node provided. Please specify a node.\n", 510

    return pvcapi.node_ready(node)

#
# VM endpoints
#
@api.route('/api/v1/vm', methods=['GET'])
def api_vm():
    """
    Return a list of VMs with limit LIMIT.
    """
    # Get node limit
    if 'node' in flask.request.values:
        node = flask.request.values['node']
    else:
        node = None

    # Get state limit
    if 'state' in flask.request.values:
        state = flask.request.values['state']
    else:
        state = None

    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    return pvcapi.vm_list(node, state, limit)

@api.route('/api/v1/vm/add', methods=['POST'])
def api_vm_add():
    """
    Add a VM named NAME to the PVC cluster.
    """
    return pvcapi.vm_add()

@api.route('/api/v1/vm/define', methods=['POST'])
def api_vm_define():
    """
    Define a VM from Libvirt XML in the PVC cluster.
    """
    return pvcapi.vm_define()

@api.route('/api/v1/vm/modify', methods=['POST'])
def api_vm_modify():
    """
    Modify a VM Libvirt XML in the PVC cluster.
    """
    return pvcapi.vm_modify()

@api.route('/api/v1/vm/undefine', methods=['POST'])
def api_vm_undefine():
    """
    Undefine a VM from the PVC cluster.
    """
    return pvcapi.vm_undefine()

@api.route('/api/v1/vm/dump', methods=['GET'])
def api_vm_dump():
    """
    Dump a VM Libvirt XML configuration.
    """
    return pvcapi.vm_dump()

@api.route('/api/v1/vm/start', methods=['POST'])
def api_vm_start():
    """
    Start a VM in the PVC cluster.
    """
    return pvcapi.vm_start()

@api.route('/api/v1/vm/restart', methods=['POST'])
def api_vm_restart():
    """
    Restart a VM in the PVC cluster.
    """
    return pvcapi.vm_restart()

@api.route('/api/v1/vm/shutdown', methods=['POST'])
def api_vm_shutdown():
    """
    Shutdown a VM in the PVC cluster.
    """
    return pvcapi.vm_shutdown()

@api.route('/api/v1/vm/stop', methods=['POST'])
def api_vm_stop():
    """
    Forcibly stop a VM in the PVC cluster.
    """
    return pvcapi.vm_stop()

@api.route('/api/v1/vm/move', methods=['POST'])
def api_vm_move():
    """
    Move a VM to another node.
    """
    return pvcapi.vm_move()

@api.route('/api/v1/vm/migrate', methods=['POST'])
def api_vm_migrate():
    """
    Temporarily migrate a VM to another node.
    """
    return pvcapi.vm_migrate()

@api.route('/api/v1/vm/unmigrate', methods=['POST'])
def api_vm_unmigrate():
    """
    Unmigrate a migrated VM.
    """
    return pvcapi.vm_unmigrate()

#
# Network endpoints
#
@api.route('/api/v1/network', methods=['GET'])
def api_net():
    """
    Return a list of client networks with limit LIMIT.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    return pvcapi.net_list(limit)

@api.route('/api/v1/network/add', methods=['POST'])
def api_net_add():
    """
    Add a virtual client network to the PVC cluster.
    """
    return pvcapi.net_add()

@api.route('/api/v1/network/modify', methods=['POST'])
def api_net_modify():
    """
    Modify a virtual client network in the PVC cluster.
    """
    return pvcapi.net_modify()

@api.route('/api/v1/network/remove', methods=['POST'])
def api_net_remove():
    """
    Remove a virtual client network from the PVC cluster.
    """
    return pvcapi.net_remove()

@api.route('/api/v1/network/dhcp', methods=['GET'])
def api_net_dhcp():
    """
    Return a list of DHCP leases in network NETWORK with limit LIMIT.
    """
    # Get network
    if 'network' in flask.request.values:
        network = flask.request.values['network']
    else:
        return "Error: No network provided. Please specify a network.\n", 510

    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    # Get static-only flag
    if 'flag_static' in flask.request.values:
        flag_static = True
    else:
        flag_static = False

    return pvcapi.net_dhcp_list(network, limit. flag_static)

@api.route('/api/v1/network/dhcp/add', methods=['POST'])
def api_net_dhcp_add():
    """
    Add a static DHCP lease to a virtual client network.
    """
    return pvcapi.net_dhcp_add()

@api.route('/api/v1/network/dhcp/remove', methods=['POST'])
def api_net_dhcp_remove():
    """
    Remove a static DHCP lease from a virtual client network.
    """
    return pvcapi.net_dhcp_remove()

@api.route('/api/v1/network/acl', methods=['GET'])
def api_net_acl():
    """
    Return a list of network ACLs in network NETWORK with limit LIMIT.
    """
    # Get network
    if 'network' in flask.request.values:
        network = flask.request.values['network']
    else:
        return "Error: No network provided. Please specify a network.\n", 510

    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    # Get direction limit
    if 'direction' in flask.request.values:
        direction = flask.request.values['direction']
        if not 'in' in direction or not 'out' in direction:
            return "Error: Direction must be either 'in' or 'out'; for both, do not specify a direction.\n", 510
    else:
        direction = None

    return pvcapi.net_acl_list(network, limit, direction)

@api.route('/api/v1/network/acl/add', methods=['POST'])
def api_net_acl_add():
    """
    Add an ACL to a virtual client network.
    """
    return pvcapi.net_acl_add()

@api.route('/api/v1/network/acl/remove', methods=['POST'])
def api_net_acl_remove():
    """
    Remove an ACL from a virtual client network.
    """
    return pvcapi.net_acl_remove()

#
# Ceph endpoints
#
@api.route('/api/v1/ceph', methods=['GET'])
def api_ceph():
    """
    Get the current Ceph cluster status.
    """
    return pvcapi.ceph_status()

@api.route('/api/v1/ceph/osd', methods=['GET'])
def api_ceph_osd():
    """
    Get the list of OSDs in the Ceph storage cluster.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    return pvcapi.ceph_osd_list(limit)

@api.route('/api/v1/ceph/osd/add', methods=['POST'])
def api_ceph_osd_add():
    """
    Add a Ceph OSD to the PVC Ceph storage cluster.
    """
    return pvcapi.ceph_osd_add()

@api.route('/api/v1/ceph/osd/remove', methods=['POST'])
def api_ceph_osd_remove():
    """
    Remove a Ceph OSD from the PVC Ceph storage cluster.
    """
    return pvcapi.ceph_osd_remove()

@api.route('/api/v1/ceph/osd/in', methods=['POST'])
def api_ceph_osd_in():
    """
    Set in a Ceph OSD in the PVC Ceph storage cluster.
    """
    return pvcapi.ceph_osd_in()

@api.route('/api/v1/ceph/osd/out', methods=['POST'])
def api_ceph_osd_out():
    """
    Set out a Ceph OSD in the PVC Ceph storage cluster.
    """
    return pvcapi.ceph_osd_out()

@api.route('/api/v1/ceph/osd/set', methods=['POST'])
def api_ceph_osd_set():
    """
    Set options on a Ceph OSD in the PVC Ceph storage cluster.
    """
    return pvcapi.ceph_osd_set()

@api.route('/api/v1/ceph/osd/unset', methods=['POST'])
def api_ceph_osd_unset():
    """
    Unset options on a Ceph OSD in the PVC Ceph storage cluster.
    """
    return pvcapi.ceph_osd_unset()

@api.route('/api/v1/ceph/pool', methods=['GET'])
def api_ceph_pool():
    """
    Get the list of RBD pools in the Ceph storage cluster.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    return pvcapi.ceph_pool_list(limit)

@api.route('/api/v1/ceph/pool/add', methods=['POST'])
def api_ceph_pool_add():
    """
    Add a Ceph RBD pool to the PVC Ceph storage cluster.
    """
    return pvcapi.ceph_pool_add()

@api.route('/api/v1/ceph/pool/remove', methods=['POST'])
def api_ceph_pool_remove():
    """
    Remove a Ceph RBD pool to the PVC Ceph storage cluster.
    """
    return pvcapi.ceph_pool_remove()

@api.route('/api/v1/ceph/volume', methods=['GET'])
def api_ceph_volume():
    """
    Get the list of RBD volumes in the Ceph storage cluster.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    # Get pool limit
    if 'pool' in flask.request.values:
        pool = flask.request.values['pool']
    else:
        pool = None

    return pvcapi.ceph_volume_list(pool, limit)

@api.route('/api/v1/ceph/volume/add', methods=['POST'])
def api_ceph_volume_add():
    """
    Add a Ceph RBD volume to the PVC Ceph storage cluster.
    """
    return pvcapi.ceph_volume_add()

@api.route('/api/v1/ceph/volume/remove', methods=['POST'])
def api_ceph_volume_remove():
    """
    Remove a Ceph RBD volume to the PVC Ceph storage cluster.
    """
    return pvcapi.ceph_volume_remove()

@api.route('/api/v1/ceph/volume/snapshot', methods=['GET'])
def api_ceph_volume_snapshot():
    """
    Get the list of RBD volume snapshots in the Ceph storage cluster.
    """
    # Get pool limit
    if 'pool' in flask.request.values:
        pool = flask.request.values['pool']
    else:
        pool = None

    # Get volume limit
    if 'volume' in flask.request.values:
        volume = flask.request.values['volume']
    else:
        volume = None

    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    return pvcapi.ceph_volume_snapshot_list(pool, volume, limit)

@api.route('/api/v1/ceph/volume/snapshot/add', methods=['POST'])
def api_ceph_volume_snapshot_add():
    """
    Add a Ceph RBD volume snapshot to the PVC Ceph storage cluster.
    """
    return pvcapi.ceph_volume_snapshot_add()

@api.route('/api/v1/ceph/volume/snapshot/remove', methods=['POST'])
def api_ceph_volume_snapshot_remove():
    """
    Remove a Ceph RBD volume snapshot to the PVC Ceph storage cluster.
    """
    return pvcapi.ceph_volume_snapshot_remove()

#
# Entrypoint
#
api.run()
