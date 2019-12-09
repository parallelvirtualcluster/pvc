#!/usr/bin/env python3

# pvc-api.py - PVC HTTP API interface
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2019 Joshua M. Boniface <joshua@boniface.me>
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
import yaml
import os

import gevent.pywsgi

import api_lib.api as pvcapi

# Parse the configuration file
try:
    pvc_config_file = os.environ['PVC_CONFIG_FILE']
except:
    print('Error: The "PVC_CONFIG_FILE" environment variable must be set before starting pvc-api.')
    exit(1)

print('Starting PVC API daemon')

# Read in the config
try:
    with open(pvc_config_file, 'r') as cfgfile:
        o_config = yaml.load(cfgfile)
except Exception as e:
    print('ERROR: Failed to parse configuration file: {}'.format(e))
    exit(1)

try:
    # Create the config object
    config = {
        'debug': o_config['pvc']['debug'],
        'coordinators': o_config['pvc']['coordinators'],
        'listen_address': o_config['pvc']['api']['listen_address'],
        'listen_port': int(o_config['pvc']['api']['listen_port']),
        'auth_enabled': o_config['pvc']['api']['authentication']['enabled'],
        'auth_secret_key': o_config['pvc']['api']['authentication']['secret_key'],
        'auth_tokens': o_config['pvc']['api']['authentication']['tokens'],
        'ssl_enabled': o_config['pvc']['api']['ssl']['enabled'],
        'ssl_key_file': o_config['pvc']['api']['ssl']['key_file'],
        'ssl_cert_file': o_config['pvc']['api']['ssl']['cert_file']
    }

    # Set the config object in the pvcapi namespace
    pvcapi.config = config
except Exception as e:
    print('ERROR: {}.'.format(e))
    exit(1)

api = flask.Flask(__name__)

if config['debug']:
    api.config['DEBUG'] = True

if config['auth_enabled']:
    api.config["SECRET_KEY"] = config['auth_secret_key']

# Authentication decorator function
def authenticator(function):
    def authenticate(*args, **kwargs):
        # No authentication required
        if not config['auth_enabled']:
            return function(*args, **kwargs)

        # Session-based authentication
        if 'token' in flask.session:
            return function(*args, **kwargs)

        # Key header-based authentication
        if 'X-Api-Key' in flask.request.headers:
            if any(token for token in secret_tokens if flask.request.headers.get('X-Api-Key') == token):
                return function(*args, **kwargs)
            else:
                return "X-Api-Key Authentication failed\n", 401

        # All authentications failed
        return "X-Api-Key Authentication required\n", 401

    authenticate.__name__ = function.__name__
    return authenticate

@api.route('/api/v1', methods=['GET'])
def api_root():
    return flask.jsonify({"message":"PVC API version 1"}), 209

@api.route('/api/v1/auth/login', methods=['GET', 'POST'])
def api_auth_login():
    # Just return a 200 if auth is disabled
    if not config['auth_enabled']:
        return flask.jsonify({"message":"Authentication is disabled."}), 200

    if flask.request.method == 'GET':
        return '''
            <form method="post">
                <p>
                    Enter your authentication token:
                    <input type=text name=token style='width:24em'>
                    <input type=submit value=Login>
                </p>
            </form>
        '''

    if flask.request.method == 'POST':
        if any(token for token in config['auth_tokens'] if flask.request.values['token'] in token['token']):
            flask.session['token'] = flask.request.form['token']
            return flask.redirect(flask.url_for('api_root'))
        else:
            return flask.jsonify({"message":"Authentication failed"}), 401

@api.route('/api/v1/auth/logout', methods=['GET', 'POST'])
def api_auth_logout():
    # Just return a 200 if auth is disabled
    if not config['auth_enabled']:
        return flask.jsonify({"message":"Authentication is disabled."}), 200

    # remove the username from the session if it's there
    flask.session.pop('token', None)
    return flask.redirect(flask.url_for('api_root'))

#
# Node endpoints
#
@api.route('/api/v1/node', methods=['GET'])
@authenticator
def api_node_root():
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    return pvcapi.node_list(limit)

@api.route('/api/v1/node/<node>', methods=['GET'])
@authenticator
def api_node_element(node):
    # Same as specifying /node?limit=NODE
    return pvcapi.node_list(node)

@api.route('/api/v1/node/<node>/daemon-state', methods=['GET'])
@authenticator
def api_node_daemon_state(node):
    if flask.request.method == 'GET':
        return pvcapi.node_daemon_state(node)

@api.route('/api/v1/node/<node>/coordinator-state', methods=['GET', 'POST'])
@authenticator
def api_node_coordinator_state(node):
    if flask.request.method == 'GET':
        return pvcapi.node_coordinator_state(node)

    if flask.request.method == 'POST':
        if not 'coordinator-state' in flask.request.values:
            flask.abort(400)
        new_state = flask.request.values['coordinator-state']
        if new_state == 'primary':
            return pvcapi.node_primary(node)
        if new_state == 'secondary':
            return pvcapi.node_secondary(node)
        flask.abort(400)

@api.route('/api/v1/node/<node>/domain-state', methods=['GET', 'POST'])
@authenticator
def api_node_domain_state(node):
    if flask.request.method == 'GET':
        return pvcapi.node_domain_state(node)

    if flask.request.method == 'POST':
        if not 'domain-state' in flask.request.values:
            flask.abort(400)
        new_state = flask.request.values['domain-state']
        if new_state == 'ready':
            return pvcapi.node_ready(node)
        if new_state == 'flush':
            return pvcapi.node_flush(node)
        flask.abort(400)

#
# VM endpoints
#
@api.route('/api/v1/vm', methods=['GET', 'POST'])
@authenticator
def api_vm_root():
    if flask.request.method == 'GET':
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

    if flask.request.method == 'POST':
        # Get XML data
        if 'xml' in flask.request.values:
            libvirt_xml = flask.request.values['xml']
        else:
            return flask.jsonify({"message":"ERROR: A Libvirt XML document must be specified."}), 400

        # Get node name
        if 'node' in flask.request.values:
            node = flask.request.values['node']
        else:
            node = None

        # Set target limit metadata
        if 'limit' in flask.request.values:
            limit = flask.request.values['limit']
        else:
            limit = None

        # Set target selector metadata
        if 'selector' in flask.request.values:
            selector = flask.request.values['selector']
        else:
            selector = 'mem'

        # Set target autostart metadata
        if 'autostart' in flask.request.values:
            autostart = True
        else:
            autostart = False

        return pvcapi.vm_define(vm, libvirt_xml, node, selector)

@api.route('/api/v1/vm/<vm>', methods=['GET', 'POST', 'PUT', 'DELETE'])
@authenticator
def api_vm_element(vm):
    if flask.request.method == 'GET':
        # Same as specifying /vm?limit=VM
        return pvcapi.vm_list(None, None, vm, is_fuzzy=False)

    if flask.request.method == 'POST':
        # Set target limit metadata
        if 'limit' in flask.request.values:
            limit = flask.request.values['limit']
        else:
            limit = None

        # Set target selector metadata
        if 'selector' in flask.request.values:
            selector = flask.request.values['selector']
        else:
            selector = None

        # Set target autostart metadata
        if 'no-autostart' in flask.request.values:
            autostart = False
        elif 'autostart' in flask.request.values:
            autostart = True
        else:
            autostart = None

       return pvcapi.vm_meta(vm, limit, selector, autostart)

    if flask.request.method == 'PUT':
        libvirt_xml = flask.request.data

        if 'restart' in flask.request.values and flask.request.values['restart']:
            flag_restart = True
        else:
            flag_restart = False

        return pvcapi.vm_modify(vm, flag_restart, libvirt_xml)

    if flask.request.method == 'DELETE':
        if 'delete_disks' in flask.request.values and flask.request.values['delete_disks']:
            return pvcapi.vm_remove(vm)
        else:
            return pvcapi.vm_undefine(vm)

@api.route('/api/v1/vm/<vm>/state', methods=['GET', 'POST'])
@authenticator
def api_vm_state(vm):
    if flask.request.method == 'GET':
        return pvcapi.vm_state(vm)

    if flask.request.method == 'POST':
        if not 'state' in flask.request.values:
            flask.abort(400)
        new_state = flask.request.values['state']
        if new_state == 'start':
            return pvcapi.vm_start(vm)
        if new_state == 'shutdown':
            return pvcapi.vm_shutdown(vm)
        if new_state == 'stop':
            return pvcapi.vm_stop(vm)
        if new_state == 'restart':
            return pvcapi.vm_restart(vm)
        flask.abort(400)

@api.route('/api/v1/vm/<vm>/node', methods=['GET', 'POST'])
@authenticator
def api_vm_node(vm):
    if flask.request.method == 'GET':
        return pvcapi.vm_node(vm)

    if flask.request.method == 'POST':
        if 'action' in flask.request.values:
            action = flask.request.values['action']
        else:
            flask.abort(400)

        # Get node name
        if 'node' in flask.request.values:
            node = flask.request.values['node']
        else:
            node = None
        # Get permanent flag
        if 'permanent' in flask.request.values and flask.request.values['permanent']:
            flag_permanent = True
        else:
            flag_permanent = False
        # Get force flag
        if 'force' in flask.request.values and flask.request.values['force']:
            flag_force = True
        else:
            flag_force = False

        # Check if VM is presently migrated
        is_migrated = pvcapi.vm_is_migrated(vm)

        if action == 'migrate' and not flag_permanent:
            return pvcapi.vm_migrate(vm, node, flag_force)
        if action == 'migrate' and flag_permanent:
            return pvcapi.vm_move(vm, node)
        if action == 'unmigrate' and is_migrated:
            return pvcapi.vm_unmigrate(vm)

        flask.abort(400)

@api.route('/api/v1/vm/<vm>/locks', methods=['GET', 'POST'])
@authenticator
def api_vm_locks(vm):
    if flask.request.method == 'GET':
        return "Not implemented", 400

    if flask.request.method == 'POST':
        return pvcapi.vm_flush_locks(vm)


#
# Network endpoints
#
@api.route('/api/v1/network', methods=['GET', 'POST'])
@authenticator
def api_net_root():
    if flask.request.method == 'GET':
        # Get name limit
        if 'limit' in flask.request.values:
            limit = flask.request.values['limit']
        else:
            limit = None

        return pvcapi.net_list(limit)

    if flask.request.method == 'POST':
        # Get network VNI
        if 'vni' in flask.request.values:
            vni = flask.request.values['vni']
        else:
            return flask.jsonify({"message":"ERROR: A VNI must be specified for the virtual network."}), 520

        # Get network description
        if 'description' in flask.request.values:
            description = flask.request.values['vni']
        else:
            return flask.jsonify({"message":"ERROR: A VNI must be specified for the virtual network."}), 520

        # Get network type
        if 'nettype' in flask.request.values:
            nettype = flask.request.values['nettype']
            if not 'managed' in nettype and not 'bridged' in nettype:
                return flask.jsonify({"message":"ERROR: A valid nettype must be specified: 'managed' or 'bridged'."}), 520
        else:
            return flask.jsonify({"message":"ERROR: A nettype must be specified for the virtual network."}), 520

        # Get network domain
        if 'domain' in flask.request.values:
            domain = flask.request.values['domain']
        else:
            domain = None

        # Get network name servers
        if 'name_server' in flask.request.values:
            name_servers = flask.request.values.getlist('name_server')
        else:
            name_servers = None

        # Get ipv4 network
        if 'ip4_network' in flask.request.values:
            ip4_network = flask.request.values['ip4_network']
        else:
            ip4_network = None

        # Get ipv4 gateway
        if 'ip4_gateway' in flask.request.values:
            ip4_gateway = flask.request.values['ip4_gateway']
        else:
            ip4_gateway = None

        # Get ipv6 network
        if 'ip6_network' in flask.request.values:
            ip6_network = flask.request.values['ip6_network']
        else:
            ip6_network = None

        # Get ipv6 gateway
        if 'ip6_gateway' in flask.request.values:
            ip6_gateway = flask.request.values['ip6_gateway']
        else:
            ip6_gateway = None

        # Get ipv4 DHCP flag
        if 'dhcp4' in flask.request.values and flask.request.values['dhcp4']:
            dhcp4_flag = True
        else:
            dhcp4_flag = False

        # Get ipv4 DHCP start
        if 'dhcp4_start' in flask.request.values:
            dhcp4_start = flask.request.values['dhcp4_start']
        else:
            dhcp4_start = None

        # Get ipv4 DHCP end
        if 'dhcp4_end' in flask.request.values:
            dhcp4_end = flask.request.values['dhcp4_end']
        else:
            dhcp4_end = None

        return pvcapi.net_add(vni, description, nettype, domain, name_servers,
                              ip4_network, ip4_gateway, ip6_network, ip6_gateway,
                              dhcp4_flag, dhcp4_start, dhcp4_end)

@api.route('/api/v1/network/<network>', methods=['GET', 'PUT', 'DELETE'])
@authenticator
def api_net_element(network):
    # Same as specifying /network?limit=NETWORK
    if flask.request.method == 'GET':
        return pvcapi.net_list(network)

    if flask.request.method == 'PUT':
        # Get network description
        if 'description' in flask.request.values:
            description = flask.request.values['description']
        else:
            description = None

        # Get network domain
        if 'domain' in flask.request.values:
            domain = flask.request.values['domain']
        else:
            domain = None

        # Get network name servers
        if 'name_server' in flask.request.values:
            name_servers = flask.request.values.getlist('name_server')
        else:
            name_servers = None

        # Get ipv4 network
        if 'ip4_network' in flask.request.values:
            ip4_network = flask.request.values['ip4_network']
        else:
            ip4_network = None

        # Get ipv4 gateway
        if 'ip4_gateway' in flask.request.values:
            ip4_gateway = flask.request.values['ip4_gateway']
        else:
            ip4_gateway = None

        # Get ipv6 network
        if 'ip6_network' in flask.request.values:
            ip6_network = flask.request.values['ip6_network']
        else:
            ip6_network = None

        # Get ipv6 gateway
        if 'ip6_gateway' in flask.request.values:
            ip6_gateway = flask.request.values['ip6_gateway']
        else:
            ip6_gateway = None

        # Get ipv4 DHCP flag
        if 'dhcp4' in flask.request.values and flask.request.values['dhcp4']:
            dhcp4_flag = True
        else:
            dhcp4_flag = False

        # Get ipv4 DHCP start
        if 'dhcp4_start' in flask.request.values:
            dhcp4_start = flask.request.values['dhcp4_start']
        else:
            dhcp4_start = None

        # Get ipv4 DHCP end
        if 'dhcp4_end' in flask.request.values:
            dhcp4_end = flask.request.values['dhcp4_end']
        else:
            dhcp4_end = None

        return pvcapi.net_modify(network, description, domain, name_servers,
                                 ip4_network, ip4_gateway,
                                 ip6_network, ip6_gateway,
                                 dhcp4_flag, dhcp4_start, dhcp4_end)

    if flask.request.method == 'DELETE':
        return pvcapi.net_remove(network)

@api.route('/api/v1/network/<network>/lease', methods=['GET', 'POST'])
@authenticator
def api_net_lease_root(network):
    if flask.request.method == 'GET':
        # Get name limit
        if 'limit' in flask.request.values:
            limit = flask.request.values['limit']
        else:
            limit = None

        # Get static-only flag
        if 'static' in flask.request.values and flask.request.values['static']:
            flag_static = True
        else:
            flag_static = False

        return pvcapi.net_dhcp_list(network, limit. flag_static)

    if flask.request.method == 'POST':
        # Get lease macaddr
        if 'macaddress' in flask.request.values:
            macaddress = flask.request.values['macaddress']
        else:
            return flask.jsonify({"message":"ERROR: An IP address must be specified for the lease."}), 400
        # Get lease ipaddress
        if 'ipaddress' in flask.request.values:
            ipaddress = flask.request.values['ipaddress']
        else:
            return flask.jsonify({"message":"ERROR: An IP address must be specified for the lease."}), 400

        # Get lease hostname
        if 'hostname' in flask.request.values:
            hostname = flask.request.values['hostname']
        else:
            hostname = None

        return pvcapi.net_dhcp_add(network, ipaddress, lease, hostname)

@api.route('/api/v1/network/<network>/lease/<lease>', methods=['GET', 'DELETE'])
@authenticator
def api_net_lease_element(network, lease):
    if flask.request.method == 'GET':
        # Same as specifying /network?limit=NETWORK
        return pvcapi.net_dhcp_list(network, lease, False)

    if flask.request.method == 'DELETE':
        return pvcapi.net_dhcp_remove(network, lease)

@api.route('/api/v1/network/<network>/acl', methods=['GET', 'POST'])
@authenticator
def api_net_acl_root(network):
    if flask.request.method == 'GET':
        # Get name limit
        if 'limit' in flask.request.values:
            limit = flask.request.values['limit']
        else:
            limit = None

        # Get direction limit
        if 'direction' in flask.request.values:
            direction = flask.request.values['direction']
            if not 'in' in direction and not 'out' in direction:
                return flash.jsonify({"message":"ERROR: Direction must be either 'in' or 'out'; for both, do not specify a direction."}), 400
        else:
            direction = None

        return pvcapi.net_acl_list(network, limit, direction)

    if flask.request.method == 'POST':
        # Get ACL description
        if 'description' in flask.request.values:
            description = flask.request.values['description']
        else:
            return flask.jsonify({"message":"ERROR: A description must be provided."}), 400

        # Get rule direction
        if 'direction' in flask.request.values:
            direction = flask.request.values['limit']
            if not 'in' in direction and not 'out' in direction:
                return flask.jsonify({"message":"ERROR: Direction must be either 'in' or 'out'."}), 400
        else:
            return flask.jsonify({"message":"ERROR: A direction must be specified for the ACL."}), 400

        # Get rule data
        if 'rule' in flask.request.values:
            rule = flask.request.values['rule']
        else:
            return flask.jsonify({"message":"ERROR: A valid NFT rule line must be specified for the ACL."}), 400

        # Get order value
        if 'order' in flask.request.values:
            order = flask.request.values['order']
        else:
            order = None

        return pvcapi.net_acl_add(network, direction, acl, rule, order)

@api.route('/api/v1/network/<network>/acl/<acl>', methods=['GET', 'DELETE'])
@authenticator
def api_net_acl_element(network, acl):
    if flask.request.method == 'GET':
        # Same as specifying /network?limit=NETWORK
        return pvcapi.net_acl_list(network, acl, None)

    if flask.request.method == 'DELETE':
        # Get rule direction
        if 'direction' in flask.request.values:
            direction = flask.request.values['limit']
            if not 'in' in direction and not 'out' in direction:
                return flask.jsonify({"message":"ERROR: Direction must be either 'in' or 'out'."}), 400
        else:
            return flask.jsonify({"message":"ERROR: A direction must be specified for the ACL."}), 400

        return pvcapi.net_acl_remove(network, direction, acl)

#
# Storage (Ceph) endpoints
#
# Note: The prefix `/storage` allows future potential storage subsystems.
#       Since Ceph is the only section not abstracted by PVC directly
#       (i.e. it references Ceph-specific concepts), this makes more
#       sense in the long-term.
#
@api.route('/api/v1/storage', methods=['GET'])
def api_storage():
    return flask.jsonify({"message":"Manage the storage of the PVC cluster."}), 200

@api.route('/api/v1/storage/ceph', methods=['GET'])
@api.route('/api/v1/storage/ceph/status', methods=['GET'])
@authenticator
def api_ceph_status():
    return pvcapi.ceph_status()

@api.route('/api/v1/storage/ceph/df', methods=['GET'])
@authenticator
def api_ceph_radosdf():
    return pvcapi.ceph_radosdf()

@api.route('/api/v1/storage/ceph/cluster-option', methods=['POST'])
@authenticator
def api_ceph_cluster_option():
    if flask.request.method == 'POST':
        # Get action
        if 'action' in flask.request.values:
            action = flask.request.values['action']
            if not 'set' in action and not 'unset' in action:
                return flask.jsonify({"message":"ERROR: Action must be one of: set, unset"}), 400
        else:
            return flask.jsonify({"message":"ERROR: An action must be specified."}), 400
        # Get option
        if 'option' in flask.request.values:
            option = flask.request.values['option']
        else:
            return flask.jsonify({"message":"ERROR: An option must be specified."}), 400

        if action == 'set':
            return pvcapi.ceph_osd_set(option)
        if action == 'unset':
            return pvcapi.ceph_osd_unset(option)

@api.route('/api/v1/storage/ceph/osd', methods=['GET', 'POST'])
@authenticator
def api_ceph_osd_root():
    if flask.request.method == 'GET':
        # Get name limit
        if 'limit' in flask.request.values:
            limit = flask.request.values['limit']
        else:
            limit = None

        return pvcapi.ceph_osd_list(limit)

    if flask.request.method == 'POST':
        # Get OSD node
        if 'node' in flask.request.values:
            node = flask.request.values['node']
        else:
            return flask.jsonify({"message":"ERROR: A node must be specified."}), 400

        # Get OSD device
        if 'device' in flask.request.values:
            device = flask.request.values['device']
        else:
            return flask.jsonify({"message":"ERROR: A block device must be specified."}), 400

        # Get OSD weight
        if 'weight' in flask.request.values:
            weight = flask.request.values['weight']
        else:
            return flask.jsonify({"message":"ERROR: An OSD weight must be specified."}), 400

        return pvcapi.ceph_osd_add(node, device, weight)

@api.route('/api/v1/storage/ceph/osd/<osd>', methods=['GET', 'DELETE'])
@authenticator
def api_ceph_osd_element(osd):
    if flask.request.method == 'GET':
        # Same as specifying /osd?limit=OSD
        return pvcapi.ceph_osd_list(osd)

    if flask.request.method == 'DELETE':
        # Verify yes-i-really-mean-it flag
        if not 'yes_i_really_mean_it' in flask.request.values:
            return flask.jsonify({"message":"ERROR: This command can have unintended consequences and should not be automated; if you're sure you know what you're doing, resend with the argument 'yes_i_really_mean_it'."}), 400

        return pvcapi.ceph_osd_remove(osd)

@api.route('/api/v1/storage/ceph/osd/<osd>/state', methods=['GET', 'POST'])
@authenticator
def api_ceph_osd_state(osd):
    if flask.request.method == 'GET':
        return pvcapi.ceph_osd_state(osd)

    if flask.request.method == 'POST':
        if 'state' in flask.request.values:
            state = flask.request.values['state']
            if not 'in' in state and not 'out' in state:
                return flask.jsonify({"message":"ERROR: State must be one of: in, out."}), 400
        else:
            return flask.jsonify({"message":"ERROR: A state must be specified."}), 400

        if state == 'in':
            return pvcapi.ceph_osd_in(osd)
        if state == 'out':
            return pvcapi.ceph_osd_out(osd)

@api.route('/api/v1/storage/ceph/pool', methods=['GET', 'POST'])
@authenticator
def api_ceph_pool_root():
    if flask.request.method == 'GET':
        # Get name limit
        if 'limit' in flask.request.values:
            limit = flask.request.values['limit']
        else:
            limit = None

        return pvcapi.ceph_pool_list(limit)

    if flask.request.method == 'POST':
        # Get pool name
        if 'pool' in flask.request.values:
            pool = flask.request.values['pool']
        else:
            return flask.jsonify({"message":"ERROR: A pool name must be specified."}), 400

        # Get placement groups
        if 'pgs' in flask.request.values:
            pgs = flask.request.values['pgs']
        else:
            # We default to a very small number; DOCUMENT THIS
            pgs = 128

        # Get replication configuration
        if 'replcfg' in flask.request.values:
            replcfg = flask.request.values['replcfg']
        else:
            # We default to copies=3,mincopies=2
            replcfg = 'copies=3,mincopies=2'

        return pvcapi.ceph_pool_add(pool, pgs)

@api.route('/api/v1/storage/ceph/pool/<pool>', methods=['GET', 'DELETE'])
@authenticator
def api_ceph_pool_element(pool):
    if flask.request.method == 'GET':
        # Same as specifying /pool?limit=POOL
        return pvcapi.ceph_pool_list(pool)

    if flask.request.method == 'DELETE':
        # Verify yes-i-really-mean-it flag
        if not 'yes_i_really_mean_it' in flask.request.values:
            return flask.jsonify({"message":"ERROR: This command can have unintended consequences and should not be automated; if you're sure you know what you're doing, resend with the argument 'yes_i_really_mean_it'."}), 400

        return pvcapi.ceph_pool_remove(pool)

@api.route('/api/v1/storage/ceph/volume', methods=['GET', 'POST'])
@authenticator
def api_ceph_volume_root():
    if flask.request.method == 'GET':
        # Get pool limit
        if 'pool' in flask.request.values:
            pool = flask.request.values['pool']
        else:
            pool = None

        # Get name limit
        if 'limit' in flask.request.values:
            limit = flask.request.values['limit']
        else:
            limit = None

        return pvcapi.ceph_volume_list(pool, limit)

    if flask.request.method == 'POST':
        # Get volume name
        if 'volume' in flask.request.values:
            volume = flask.request.values['volume']
        else:
            return flask.jsonify({"message":"ERROR: A volume name must be specified."}), 400

        # Get volume pool
        if 'pool' in flask.request.values:
            pool = flask.request.values['pool']
        else:
            return flask.jsonify({"message":"ERROR: A pool name must be spcified."}), 400

        # Get source_volume
        if 'source_volume' in flask.request.values:
            source_volume = flask.request.values['source_volume']
        else:
            source_volume = None

        # Get volume size
        if 'size' in flask.request.values:
            size = flask.request.values['size']
        elif source_volume:
            # We ignore size if we're cloning a volume
            size = None
        else:
            return flask.jsonify({"message":"ERROR: A volume size in bytes (or with an M/G/T suffix) must be specified."}), 400

        if source_volume:
            return pvcapi.ceph_volume_clone(pool, volume, source_volume)
        else:
            return pvcapi.ceph_volume_add(pool, volume, size)

@api.route('/api/v1/storage/ceph/volume/<pool>/<volume>', methods=['GET', 'PUT', 'DELETE'])
@authenticator
def api_ceph_volume_element(pool, volume):
    if flask.request.method == 'GET':
        # Same as specifying /volume?limit=VOLUME
        return pvcapi.ceph_volume_list(pool, volume)

    if flask.request.method == 'PUT':
        if 'size' in flask.request.values:
            size = flask.request.values['size']

        if 'name' in flask.request.values:
            name = flask.request.values['name']

        if size and not name:
            return pvcapi.ceph_volume_resize(pool, volume, size)

        if name and not size:
            return pvcapi.ceph_volume_rename(pool, volume, name)

        return flask.jsonify({"message":"ERROR: No name or size specified, or both specified; not changing anything."}), 400

    if flask.request.method == 'DELETE':
        return pvcapi.ceph_volume_remove(pool, volume)

@api.route('/api/v1/storage/ceph/volume/snapshot', methods=['GET', 'POST'])
@authenticator
def api_ceph_volume_snapshot_root():
    if flask.request.method == 'GET':
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

    if flask.request.method == 'POST':
        # Get snapshot name
        if 'snapshot' in flask.request.values:
            snapshot = flask.request.values['snapshot']
        else:
            return flask.jsonify({"message":"ERROR: A snapshot name must be specified."}), 400

        # Get volume name
        if 'volume' in flask.request.values:
            volume = flask.request.values['volume']
        else:
            return flask.jsonify({"message":"ERROR: A volume name must be specified."}), 400

        # Get volume pool
        if 'pool' in flask.request.values:
            pool = flask.request.values['pool']
        else:
            return flask.jsonify({"message":"ERROR: A pool name must be spcified."}), 400

        return pvcapi.ceph_volume_snapshot_add(pool, volume, snapshot)


@api.route('/api/v1/storage/ceph/volume/snapshot/<pool>/<volume>/<snapshot>', methods=['GET', 'PUT', 'DELETE'])
@authenticator
def api_ceph_volume_snapshot_element(pool, volume, snapshot):
    if flask.request.method == 'GET':
        # Same as specifying /snapshot?limit=VOLUME
        return pvcapi.ceph_volume_snapshot_list(pool, volume, snapshot)

    if flask.request.method == 'PUT':
        if 'name' in flask.request.values:
            name = flask.request.values['name']
        else:
            return flask.jsonify({"message":"ERROR: A new name must be specified."}), 400

        return pvcapi.ceph_volume_snapshot_rename(pool, volume, snapshot, name)

    if flask.request.method == 'DELETE':
        return pvcapi.ceph_volume_snapshot_remove(pool, volume, snapshot)

#
# Entrypoint
#
if config['debug']:
    # Run in Flask standard mode
    api.run(config['listen_address'], config['listen_port'])
else:
    if config['ssl_enabled']:
        # Run the WSGI server with SSL
        http_server = gevent.pywsgi.WSGIServer(
            (config['listen_address'], config['listen_port']),
            api,
            keyfile=config['ssl_key_file'],
            certfile=config['ssl_cert_file']
        )
    else:
        # Run the ?WSGI server without SSL
        http_server = gevent.pywsgi.WSGIServer(
            (config['listen_address'], config['listen_port']),
            api
        )

    print('Starting PyWSGI server at {}:{} with SSL={}, Authentication={}'.format(config['listen_address'], config['listen_port'], config['ssl_enabled'], config['auth_enabled']))
    http_server.serve_forever()
