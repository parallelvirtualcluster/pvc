#!/usr/bin/env python3

# pvcapi.py - PVC HTTP API interface
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

pvcapi = flask.Flask(__name__)
pvcapi.config["DEBUG"] = True

@pvcapi.route('/api/v1', methods=['GET'])
def api_root():
    return "PVC API version 1", 209

#
# Node endpoints
#
@pvcapi.route('/api/v1/node', methods=['GET'])
def api_node():
    """
    Manage the state of a node in the PVC cluster.
    """
    return "Manage the state of a node in the PVC cluster.\n", 209

@pvcapi.route('/api/v1/node/secondary', methods=['POST'])
def api_node_secondary():
    """
    Take NODE out of primary router mode.
    """
    # Get node
    if 'node' in flask.request.values:
        node = flask.request.values['node']
    else:
        return "Error: No node provided. Please specify a node.\n", 510

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

@pvcapi.route('/api/v1/node/primary', methods=['POST'])
def api_node_primary():
    """
    Set NODE to primary router mode.
    """
    # Get node
    if 'node' in flask.request.values:
        node = flask.request.values['node']
    else:
        return "Error: No node provided. Please specify a node.\n", 510

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

@pvcapi.route('/api/v1/node/flush', methods=['POST'])
def api_node_flush():
    """
    Flush NODE of running VMs.
    """
    # Get node
    if 'node' in flask.request.values:
        node = flask.request.values['node']
    else:
        return "Error: No node provided. Please specify a node.\n", 510

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

@pvcapi.route('/api/v1/node/unflush', methods=['POST'])
@pvcapi.route('/api/v1/node/ready', methods=['POST'])
def api_node_ready():
    """
    Restore NODE to active service.
    """
    # Get node
    if 'node' in flask.request.values:
        node = flask.request.values['node']
    else:
        return "Error: No node provided. Please specify a node.\n", 510

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

@pvcapi.route('/api/v1/node/list', methods=['GET'])
def api_node_list():
    """
    Return a list of nodes with limit LIMIT.
    """
    # Get limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_node.get_list(zk_conn, limit)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

#
# VM endpoints
#
@pvcapi.route('/api/v1/vm', methods=['GET'])
def api_vm():
    """
    Manage the state of a VM in the PVC cluster.
    """
    return "Manage the state of a VM in the PVC cluster.\n", 209

@pvcapi.route('/api/v1/vm/add', methods=['POST'])
def api_vm_add():
    """
    Add a VM named NAME to the PVC cluster.
    """
    pass

@pvcapi.route('/api/v1/vm/define', methods=['POST'])
def api_vm_define():
    """
    Define a VM from Libvirt XML in the PVC cluster.
    """
    pass

@pvcapi.route('/api/v1/vm/modify', methods=['POST'])
def api_vm_modify():
    """
    Modify a VM Libvirt XML in the PVC cluster.
    """
    pass

@pvcapi.route('/api/v1/vm/undefine', methods=['POST'])
def api_vm_undefine():
    """
    Undefine a VM from the PVC cluster.
    """
    pass

@pvcapi.route('/api/v1/vm/dump', methods=['GET'])
def api_vm_dump():
    """
    Dump a VM Libvirt XML configuration.
    """
    pass

@pvcapi.route('/api/v1/vm/start', methods=['POST'])
def api_vm_start():
    """
    Start a VM in the PVC cluster.
    """
    pass

@pvcapi.route('/api/v1/vm/restart', methods=['POST'])
def api_vm_restart():
    """
    Restart a VM in the PVC cluster.
    """
    pass

@pvcapi.route('/api/v1/vm/shutdown', methods=['POST'])
def api_vm_shutdown():
    """
    Shutdown a VM in the PVC cluster.
    """
    pass

@pvcapi.route('/api/v1/vm/stop', methods=['POST'])
def api_vm_stop():
    """
    Forcibly stop a VM in the PVC cluster.
    """
    pass

@pvcapi.route('/api/v1/vm/move', methods=['POST'])
def api_vm_move():
    """
    Move a VM to another node.
    """
    pass

@pvcapi.route('/api/v1/vm/migrate', methods=['POST'])
def api_vm_migrate():
    """
    Temporarily migrate a VM to another node.
    """
    pass

@pvcapi.route('/api/v1/vm/unmigrate', methods=['POST'])
def api_vm_unmigrate():
    """
    Unmigrate a migrated VM.
    """
    pass

@pvcapi.route('/api/v1/vm/list', methods=['GET'])
def api_vm_list():
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

    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_vm.get_list(zk_conn, node, state, limit)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

#
# Network endpoints
#
@pvcapi.route('/api/v1/network', methods=['GET'])
def api_net():
    """
    Manage the state of a client network in the PVC cluster.
    """
    return "Manage the state of a VM in the PVC cluster.\n", 209

@pvcapi.route('/api/v1/network/add', methods=['POST'])
def api_net_add():
    """
    Add a virtual client network to the PVC cluster.
    """
    pass

@pvcapi.route('/api/v1/network/modify', methods=['POST'])
def api_net_modify():
    """
    Modify a virtual client network in the PVC cluster.
    """
    pass

@pvcapi.route('/api/v1/network/remove', methods=['POST'])
def api_net_remove():
    """
    Remove a virtual client network from the PVC cluster.
    """
    pass

@pvcapi.route('/api/v1/network/list', methods=['GET'])
def api_net_list():
    """
    Return a list of client networks with limit LIMIT.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_network.get_list(zk_conn, limit)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

@pvcapi.route('/api/v1/network/dhcp', methods=['GET'])
def api_net_dhcp():
    """
    Manage the state of a client network DHCP in the PVC cluster.
    """
    return "Manage the state of a VM in the PVC cluster.\n", 209

@pvcapi.route('/api/v1/network/dhcp/list', methods=['GET'])
def api_net_dhcp_list():
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

    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_network.get_list_dhcp(zk_conn, network, limit, False)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

@pvcapi.route('/api/v1/network/dhcp/static', methods=['GET'])
def api_net_dhcp_static():
    """
    Manage the state of a client network static DHCP lease in the PVC cluster.
    """
    return "Manage the state of a VM in the PVC cluster.\n", 209

@pvcapi.route('/api/v1/network/dhcp/static/add', methods=['POST'])
def api_net_dhcp_static_add():
    """
    Add a static DHCP lease to a virtual client network.
    """
    pass

@pvcapi.route('/api/v1/network/dhcp/static/remove', methods=['POST'])
def api_net_dhcp_static_remove():
    """
    Remove a static DHCP lease from a virtual client network.
    """
    pass

@pvcapi.route('/api/v1/network/dhcp/static/list', methods=['GET'])
def api_net_dhcp_static_list():
    """
    Return a list of static DHCP leases in network NETWORK with limit LIMIT.
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

    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_network.get_list_dhcp(zk_conn, network, limit, True)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

@pvcapi.route('/api/v1/network/acl', methods=['GET'])
def api_net_acl():
    """
    Manage the state of a client network ACL in the PVC cluster.
    """
    return "Manage the state of a VM in the PVC cluster.\n", 209

@pvcapi.route('/api/v1/network/acl/add', methods=['POST'])
def api_net_acl_add():
    """
    Add an ACL to a virtual client network.
    """
    pass

@pvcapi.route('/api/v1/network/acl/remove', methods=['POST'])
def api_net_acl_remove():
    """
    Remove an ACL from a virtual client network.
    """
    pass

@pvcapi.route('/api/v1/network/acl/list', methods=['GET'])
def api_net_acl_list():
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
            return "Error: Direction must be either 'in' or 'out'.\n", 510
    else:
        direction = None

    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_network.get_list_acl(zk_conn, network, limit, direction)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

#
# Ceph endpoints
#
@pvcapi.route('/api/v1/ceph', methods=['GET'])
def api_ceph():
    """
    Manage the state of the Ceph storage cluster.
    """
    return "Manage the state of the Ceph storage cluster.\n", 209

@pvcapi.route('/api/v1/ceph/status', methods=['GET'])
def api_ceph_status():
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

@pvcapi.route('/api/v1/ceph/osd', methods=['GET'])
def api_ceph_osd():
    """
    Manage the state of OSDs in the Ceph storage cluster.
    """
    return "Manage the state of OSDs in the Ceph storage cluster.\n", 209

@pvcapi.route('/api/v1/ceph/osd/add', methods=['POST'])
def api_ceph_osd_add():
    """
    Add a Ceph OSD to the PVC Ceph storage cluster.
    """
    pass

@pvcapi.route('/api/v1/ceph/osd/remove', methods=['POST'])
def api_ceph_osd_remove():
    """
    Remove a Ceph OSD from the PVC Ceph storage cluster.
    """
    pass

@pvcapi.route('/api/v1/ceph/osd/in', methods=['POST'])
def api_ceph_osd_in():
    """
    Set in a Ceph OSD in the PVC Ceph storage cluster.
    """
    pass

@pvcapi.route('/api/v1/ceph/osd/out', methods=['POST'])
def api_ceph_osd_out():
    """
    Set out a Ceph OSD in the PVC Ceph storage cluster.
    """
    pass

@pvcapi.route('/api/v1/ceph/osd/set', methods=['POST'])
def api_ceph_osd_set():
    """
    Set options on a Ceph OSD in the PVC Ceph storage cluster.
    """
    pass

@pvcapi.route('/api/v1/ceph/osd/unset', methods=['POST'])
def api_ceph_osd_unset():
    """
    Unset options on a Ceph OSD in the PVC Ceph storage cluster.
    """
    pass

@pvcapi.route('/api/v1/ceph/osd/list', methods=['GET'])
def api_ceph_osd_list():
    """
    Get the list of OSDs in the Ceph storage cluster.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_ceph.get_list_osd(zk_conn, limit)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

@pvcapi.route('/api/v1/ceph/pool', methods=['GET'])
def api_ceph_pool():
    """
    Manage the state of RBD pools in the Ceph storage cluster.
    """
    return "Manage the state of RBD pools in the Ceph storage cluster.\n", 209

@pvcapi.route('/api/v1/ceph/pool/add', methods=['POST'])
def api_ceph_pool_add():
    """
    Add a Ceph RBD pool to the PVC Ceph storage cluster.
    """
    pass

@pvcapi.route('/api/v1/ceph/pool/remove', methods=['POST'])
def api_ceph_pool_remove():
    """
    Remove a Ceph RBD pool to the PVC Ceph storage cluster.
    """
    pass

@pvcapi.route('/api/v1/ceph/pool/list', methods=['GET'])
def api_ceph_pool_list():
    """
    Get the list of RBD pools in the Ceph storage cluster.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_ceph.get_list_pool(zk_conn, limit)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

@pvcapi.route('/api/v1/ceph/volume', methods=['GET'])
def api_ceph_volume():
    """
    Manage the state of RBD volumes in the Ceph storage cluster.
    """
    return "Manage the state of RBD volumes in the Ceph storage cluster.\n", 209

@pvcapi.route('/api/v1/ceph/volume/add', methods=['POST'])
def api_ceph_volume_add():
    """
    Add a Ceph RBD volume to the PVC Ceph storage cluster.
    """
    pass

@pvcapi.route('/api/v1/ceph/volume/remove', methods=['POST'])
def api_ceph_volume_remove():
    """
    Remove a Ceph RBD volume to the PVC Ceph storage cluster.
    """
    pass

@pvcapi.route('/api/v1/ceph/volume/list', methods=['GET'])
def api_ceph_volume_list():
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
        pool = 'all'

    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_ceph.get_list_volume(zk_conn, pool, limit)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

@pvcapi.route('/api/v1/ceph/volume/snapshot', methods=['GET'])
def api_ceph_volume_snapshot():
    """
    Manage the state of RBD volume snapshots in the Ceph storage cluster.
    """
    return "Manage the state of RBD volume snapshots in the Ceph storage cluster.\n", 209

@pvcapi.route('/api/v1/ceph/volume/snapshot/add', methods=['POST'])
def api_ceph_volume_snapshot_add():
    """
    Add a Ceph RBD volume snapshot to the PVC Ceph storage cluster.
    """
    pass

@pvcapi.route('/api/v1/ceph/volume/snapshot/remove', methods=['POST'])
def api_ceph_volume_snapshot_remove():
    """
    Remove a Ceph RBD volume snapshot to the PVC Ceph storage cluster.
    """
    pass

@pvcapi.route('/api/v1/ceph/volume/snapshot/list', methods=['GET'])
def api_ceph_volume_snapshot_list():
    """
    Get the list of RBD volume snapshots in the Ceph storage cluster.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    # Get volume limit
    if 'volume' in flask.request.values:
        volume = flask.request.values['volume']
    else:
        volume = 'all'

    # Get pool limit
    if 'pool' in flask.request.values:
        pool = flask.request.values['pool']
    else:
        pool = 'all'

    zk_conn = pvc_common.startZKConnection(zk_host)
    retflag, retdata = pvc_ceph.get_list_snapshot(zk_conn, pool, volume, limit)
    if retflag:
        retcode = 200
    else:
        retcode = 510

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

#
# Entrypoint
#
pvcapi.run()
