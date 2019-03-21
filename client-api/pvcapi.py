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
    return "Manage the state of a node in the PVC cluster", 209

@pvcapi.route('/api/v1/node/secondary', methods=['GET'])
def api_node_secondary():
    """
    Take NODE out of primary router mode.
    """
    # Mandatory args
    if 'node' in flask.request.args:
        node = flask.request.args['node']
    else:
        return "Error: No node provided. Please specify a node.", 510

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

@pvcapi.route('/api/v1/node/primary', methods=['GET'])
def api_node_primary():
    """
    Set NODE to primary router mode.
    """
    # Mandatory args
    if 'node' in flask.request.args:
        node = flask.request.args['node']
    else:
        return "Error: No node provided. Please specify a node.", 510

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

#@pvcapi.route('/api/v1/node/flush', methods=['GET'])
#@pvcapi.route('/api/v1/node/unflush', methods=['GET'])
#@pvcapi.route('/api/v1/node/ready', methods=['GET'])
#@pvcapi.route('/api/v1/node/info', methods=['GET'])
#@pvcapi.route('/api/v1/node/list', methods=['GET'])
#@pvcapi.route('/api/v1/vm', methods=['GET'])
#@pvcapi.route('/api/v1/vm/add', methods=['GET'])
#@pvcapi.route('/api/v1/vm/define', methods=['GET'])
#@pvcapi.route('/api/v1/vm/modify', methods=['GET'])
#@pvcapi.route('/api/v1/vm/undefine', methods=['GET'])
#@pvcapi.route('/api/v1/vm/dump', methods=['GET'])
#@pvcapi.route('/api/v1/vm/start', methods=['GET'])
#@pvcapi.route('/api/v1/vm/restart', methods=['GET'])
#@pvcapi.route('/api/v1/vm/shutdown', methods=['GET'])
#@pvcapi.route('/api/v1/vm/stop', methods=['GET'])
#@pvcapi.route('/api/v1/vm/move', methods=['GET'])
#@pvcapi.route('/api/v1/vm/migrate', methods=['GET'])
#@pvcapi.route('/api/v1/vm/unmigrate', methods=['GET'])
#@pvcapi.route('/api/v1/vm/info', methods=['GET'])
#@pvcapi.route('/api/v1/vm/list', methods=['GET'])
#@pvcapi.route('/api/v1/network', methods=['GET'])
#@pvcapi.route('/api/v1/network/add', methods=['GET'])
#@pvcapi.route('/api/v1/network/modify', methods=['GET'])
#@pvcapi.route('/api/v1/network/remove', methods=['GET'])
#@pvcapi.route('/api/v1/network/info', methods=['GET'])
#@pvcapi.route('/api/v1/network/list', methods=['GET'])
#@pvcapi.route('/api/v1/network/dhcp', methods=['GET'])
#@pvcapi.route('/api/v1/network/dhcp/list', methods=['GET'])
#@pvcapi.route('/api/v1/network/dhcp/static', methods=['GET'])
#@pvcapi.route('/api/v1/network/dhcp/static/add', methods=['GET'])
#@pvcapi.route('/api/v1/network/dhcp/static/remove', methods=['GET'])
#@pvcapi.route('/api/v1/network/dhcp/static/list', methods=['GET'])
#@pvcapi.route('/api/v1/network/acl', methods=['GET'])
#@pvcapi.route('/api/v1/network/acl/add', methods=['GET'])
#@pvcapi.route('/api/v1/network/acl/remove', methods=['GET'])
#@pvcapi.route('/api/v1/network/acl/list', methods=['GET'])
# Ceph endpoints
#@pvcapi.route('/api/v1/ceph', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/status', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/osd', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/osd/add', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/osd/remove', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/osd/in', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/osd/out', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/osd/set', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/osd/unset', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/osd/list', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/pool', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/pool/add', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/pool/remove', methods=['GET'])
#@pvcapi.route('/api/v1/ceph/pool/list', methods=['GET'])

pvcapi.run()
