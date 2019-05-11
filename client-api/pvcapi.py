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
    print(flask.request)
    print(flask.request.args)
    return "", 200

@pvcapi.route('/api/v1/node', methods=['GET'])
def api_node():
    """
    Manage the state of a node in the PVC cluster
    """
    return "Manage the state of a node in the PVC cluster.\n", 209

@pvcapi.route('/api/v1/node/secondary', methods=['POST'])
def api_node_secondary():
    """
    Take NODE out of primary router mode.
    """
    # Get data from flask
    data = json.loads(flask.request.data.decode('utf8'))
    # Get node
    if 'node' in data:
        node = data['node']
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
    # Get data from flask
    data = json.loads(flask.request.data.decode('utf8'))
    # Get node
    if 'node' in data:
        node = data['node']
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
    # Get data from flask
    data = json.loads(flask.request.data.decode('utf8'))
    # Get node
    if 'node' in data:
        node = data['node']
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
    # Get data from flask
    data = json.loads(flask.request.data.decode('utf8'))
    # Get node
    if 'node' in data:
        node = data['node']
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


#@pvcapi.route('/api/v1/node/info', methods=['GET'])
#@pvcapi.route('/api/v1/node/list', methods=['GET'])
# VM endpoints
#@pvcapi.route('/api/v1/vm', methods=['GET'])
#@pvcapi.route('/api/v1/vm/add', methods=['POST'])
#@pvcapi.route('/api/v1/vm/define', methods=['POST'])
#@pvcapi.route('/api/v1/vm/modify', methods=['POST'])
#@pvcapi.route('/api/v1/vm/undefine', methods=['POST'])
#@pvcapi.route('/api/v1/vm/dump', methods=['GET'])
#@pvcapi.route('/api/v1/vm/start', methods=['POST'])
#@pvcapi.route('/api/v1/vm/restart', methods=['POST'])
#@pvcapi.route('/api/v1/vm/shutdown', methods=['POST'])
#@pvcapi.route('/api/v1/vm/stop', methods=['POST'])
#@pvcapi.route('/api/v1/vm/move', methods=['POST'])
#@pvcapi.route('/api/v1/vm/migrate', methods=['POST'])
#@pvcapi.route('/api/v1/vm/unmigrate', methods=['POST'])
#@pvcapi.route('/api/v1/vm/info', methods=['GET'])
#@pvcapi.route('/api/v1/vm/list', methods=['GET'])
# Network endpoints
#@pvcapi.route('/api/v1/network', methods=['GET'])
#@pvcapi.route('/api/v1/network/add', methods=['POST'])
#@pvcapi.route('/api/v1/network/modify', methods=['POST'])
#@pvcapi.route('/api/v1/network/remove', methods=['POST'])
#@pvcapi.route('/api/v1/network/info', methods=['GET'])
#@pvcapi.route('/api/v1/network/list', methods=['GET'])
#@pvcapi.route('/api/v1/network/dhcp', methods=['GET'])
#@pvcapi.route('/api/v1/network/dhcp/list', methods=['GET'])
#@pvcapi.route('/api/v1/network/dhcp/static', methods=['GET'])
#@pvcapi.route('/api/v1/network/dhcp/static/add', methods=['POST'])
#@pvcapi.route('/api/v1/network/dhcp/static/remove', methods=['POST'])
#@pvcapi.route('/api/v1/network/dhcp/static/list', methods=['GET'])
#@pvcapi.route('/api/v1/network/acl', methods=['GET'])
#@pvcapi.route('/api/v1/network/acl/add', methods=['POST'])
#@pvcapi.route('/api/v1/network/acl/remove', methods=['POST'])
#@pvcapi.route('/api/v1/network/acl/list', methods=['GET'])
# Ceph endpoints
#@pvcapi.route('/api/v1/ceph', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/status', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/osd', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/osd/add', methods=['POST'])
#@pvcapi.route('/api/v1/ceph/osd/remove', methods=['POST'])
#@pvcapi.route('/api/v1/ceph/osd/in', methods=['POST'])
#@pvcapi.route('/api/v1/ceph/osd/out', methods=['POST'])
#@pvcapi.route('/api/v1/ceph/osd/set', methods=['POST'])
#@pvcapi.route('/api/v1/ceph/osd/unset', methods=['POST'])
#@pvcapi.route('/api/v1/ceph/osd/list', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/pool', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/pool/add', methods=['POST'])
#@pvcapi.route('/api/v1/ceph/pool/remove', methods=['POST'])
#@pvcapi.route('/api/v1/ceph/pool/list', methods=['GET'])

pvcapi.run()
