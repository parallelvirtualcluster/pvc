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
import yaml
import os

import gevent.pywsgi

import api_lib.pvcapi as pvcapi

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

def authenticator(function):
    def authenticate(*args, **kwargs):
        # Check if authentication is enabled
        if not config['auth_enabled']:
            return function(*args, **kwargs)
        else:
            # Session-based authentication
            if 'token' in flask.session:
                return function(*args, **kwargs)
            # Direct token-based authentication
            if 'token' in flask.request.values:
                if any(token for token in config['auth_tokens'] if flask.request.values['token'] == token['token']):
                    return function(*args, **kwargs)
                else:
                    return flask.jsonify({"message":"Authentication failed"}), 401

            return flask.jsonify({"message":"Authentication required"}), 401

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

    if flask.request.method == 'POST':
        if any(token for token in config['auth_tokens'] if flask.request.values['token'] in token['token']):
            flask.session['token'] = flask.request.form['token']
            return flask.redirect(flask.url_for('api_root'))
        else:
            return flask.jsonify({"message":"Authentication failed"}), 401
    return '''
        <form method="post">
            <p>
                Enter your authentication token:
                <input type=text name=token style='width:24em'>
                <input type=submit value=Login>
            </p>
        </form>
    '''

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
def api_node():
    """
    Return a list of nodes with limit LIMIT.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    return pvcapi.node_list(limit)

@api.route('/api/v1/node/<node>', methods=['GET'])
@authenticator
def api_node_root(node):
    """
    Return information about node NODE.
    """
    # Same as specifying /node?limit=NODE
    return pvcapi.node_list(node)


@api.route('/api/v1/node/<node>/coordinator-state', methods=['GET', 'POST'])
@authenticator
def api_node_coordinator_state(node):
    """
    Manage NODE coordinator state.
    """

    if flask.request.method == 'GET':
        return "Test", 200

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
    """
    Manage NODE domain state.
    """

    if flask.request.method == 'GET':
        return "Test", 200

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
def api_vm():
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
    
        # Get target selector
        if 'selector' in flask.request.values:
            selector = flask.request.values['selector']
        else:
            selector = None
    
        return pvcapi.vm_define(vm, libvirt_xml, node, selector)

@api.route('/api/v1/vm/<vm>', methods=['GET', 'POST', 'PUT', 'DELETE'])
@authenticator
def api_vm_root(vm):
    if flask.request.method == 'GET':
        # Same as specifying /vm?limit=VM
        return pvcapi.vm_list(None, None, vm, is_fuzzy=False)

    if flask.request.method == 'POST':
        # TODO: #22
        flask.abort(501)

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
        return "Test", 200

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
        return "Test", 200
    
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
        # Get target selector
        if 'selector' in flask.request.values:
            selector = flask.request.values['selector']
        else:
            selector = None
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
            return pvcapi.vm_migrate(vm, node, selector, flag_force)
        if action == 'migrate' and flag_permanent:
            return pvcapi.vm_move(vm, node, selector)
        if action == 'unmigrate' and is_migrated:
            return pvcapi.vm_unmigrate(vm)

        flask.abort(400)


#
# Network endpoints
#
@api.route('/api/v1/network', methods=['GET'])
@authenticator
def api_net():
    """
    Return a list of virtual client networks with limit LIMIT.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    return pvcapi.net_list(limit)

@api.route('/api/v1/network/<network>', methods=['GET'])
@authenticator
def api_net_info(network):
    """
    Get information about a virtual client network with description NETWORK.
    """
    # Same as specifying /network?limit=NETWORK
    return pvcapi.net_list(network)

@api.route('/api/v1/network/<network>/add', methods=['POST'])
@authenticator
def api_net_add(network):
    """
    Add a virtual client network with description NETWORK.
    """
    # Get network VNI
    if 'vni' in flask.request.values:
        vni = flask.request.values['vni']
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
    if 'flag_dhcp4' in flask.request.values:
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

    return pvcapi.net_add(vni, network, nettype, domain,
                          ip4_network, ip4_gateway, ip6_network, ip6_gateway,
                          dhcp4_flag, dhcp4_start, dhcp4_end)

@api.route('/api/v1/network/<network>/modify', methods=['POST'])
@authenticator
def api_net_modify(network):
    """
    Modify a virtual client network with description NETWORK.
    """
    # Get network VNI
    if 'vni' in flask.request.values:
        vni = flask.request.values['vni']
    else:
        vni = None

    # Get network type
    if 'nettype' in flask.request.values:
        nettype = flask.request.values['nettype']
    else:
        vni = None

    # Get network domain
    if 'domain' in flask.request.values:
        domain = flask.request.values['domain']
    else:
        domain = None

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
    if 'flag_dhcp4' in flask.request.values:
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

    return pvcapi.net_modify(vni, network, nettype, domain,
                             ip4_network, ip4_gateway, ip6_network, ip6_gateway,
                             dhcp4_flag, dhcp4_start, dhcp4_end)

@api.route('/api/v1/network/<network>/remove', methods=['POST'])
@authenticator
def api_net_remove(network):
    """
    Remove a virtual client network with description NETWORK.
    """
    return pvcapi.net_remove(network)

@api.route('/api/v1/network/<network>/dhcp', methods=['GET'])
@authenticator
def api_net_dhcp(network):
    """
    Return a list of DHCP leases in virtual client network with description NETWORK with limit LIMIT.
    """
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

@api.route('/api/v1/network/<network>/dhcp/<lease>', methods=['GET'])
@authenticator
def api_net_dhcp_info(network, lease):
    """
    Get information about a DHCP lease for MAC address LEASE in virtual client network with description NETWORK.
    """
    # Same as specifying /network?limit=NETWORK
    return pvcapi.net_dhcp_list(network, lease, False)

@api.route('/api/v1/network/<network>/dhcp/<lease>/add', methods=['POST'])
@authenticator
def api_net_dhcp_add(network, lease):
    """
    Add a static DHCP lease for MAC address LEASE to virtual client network with description NETWORK.
    """
    # Get lease ipaddress
    if 'ipaddress' in flask.request.values:
        ipaddress = flask.request.values['ipaddress']
    else:
        return flask.jsonify({"message":"ERROR: An IP address must be specified for the lease."}), 520

    # Get lease hostname
    if 'hostname' in flask.request.values:
        hostname = flask.request.values['hostname']
    else:
        hostname = None

    return pvcapi.net_dhcp_add(network, ipaddress, lease, hostname)

@api.route('/api/v1/network/<network>/dhcp/<lease>/remove', methods=['POST'])
@authenticator
def api_net_dhcp_remove(network, lease):
    """
    Remove a static DHCP lease for MAC address LEASE from virtual client network with description NETWORK.
    """
    return pvcapi.net_dhcp_remove(network, lease)

@api.route('/api/v1/network/<network>/acl', methods=['GET'])
@authenticator
def api_net_acl(network):
    """
    Return a list of network ACLs in network NETWORK with limit LIMIT.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    # Get direction limit
    if 'direction' in flask.request.values:
        direction = flask.request.values['direction']
        if not 'in' in direction and not 'out' in direction:
            return flash.jsonify({"message":"ERROR: Direction must be either 'in' or 'out'; for both, do not specify a direction."}), 510
    else:
        direction = None

    return pvcapi.net_acl_list(network, limit, direction)

@api.route('/api/v1/network/<network>/acl/<acl>', methods=['GET'])
@authenticator
def api_net_acl_info(network, acl):
    """
    Get information about a network access control entry with description ACL in virtual client network with description NETWORK.
    """
    # Same as specifying /network?limit=NETWORK
    return pvcapi.net_acl_list(network, acl, None)

@api.route('/api/v1/network/<network>/acl/<acl>/add', methods=['POST'])
@authenticator
def api_net_acl_add(network, acl):
    """
    Add an access control list with description ACL to virtual client network with description NETWORK.
    """
    # Get rule direction
    if 'direction' in flask.request.values:
        direction = flask.request.values['limit']
        if not 'in' in direction and not 'out' in direction:
            return flask.jsonify({"message":"ERROR: Direction must be either 'in' or 'out'."}), 510
    else:
        return flask.jsonify({"message":"ERROR: A direction must be specified for the ACL."}), 510

    # Get rule data
    if 'rule' in flask.request.values:
        rule = flask.request.values['rule']
    else:
        return flask.jsonify({"message":"ERROR: A valid NFT rule line must be specified for the ACL."}), 510

    # Get order value
    if 'order' in flask.request.values:
        order = flask.request.values['order']
    else:
        order = None

    return pvcapi.net_acl_add(network, direction, acl, rule, order)

@api.route('/api/v1/network/<network>/acl/<acl>/remove', methods=['POST'])
@authenticator
def api_net_acl_remove(network, acl):
    """
    Remove an access control list with description ACL from virtual client network with description NETWORK.
    """
    # Get rule direction
    if 'direction' in flask.request.values:
        direction = flask.request.values['limit']
        if not 'in' in direction and not 'out' in direction:
            return flask.jsonify({"message":"ERROR: Direction must be either 'in' or 'out'."}), 510
    else:
        return flask.jsonify({"message":"ERROR: A direction must be specified for the ACL."}), 510

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
    """
    Manage the storage of the PVC cluster.
    """
    return flask.jsonify({"message":"Manage the storage of the PVC cluster."}), 200

@api.route('/api/v1/storage/ceph', methods=['GET'])
@api.route('/api/v1/storage/ceph/status', methods=['GET'])
@authenticator
def api_ceph_status():
    """
    Get the current Ceph cluster status.
    """
    return pvcapi.ceph_status()

@api.route('/api/v1/storage/ceph/df', methods=['GET'])
@authenticator
def api_ceph_radosdf():
    """
    Get the current Ceph cluster utilization.
    """
    return pvcapi.ceph_radosdf()

@api.route('/api/v1/storage/ceph/osd', methods=['GET'])
@authenticator
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

@api.route('/api/v1/storage/ceph/osd/set', methods=['POST'])
@authenticator
def api_ceph_osd_set():
    """
    Set OSD option OPTION on the PVC Ceph storage cluster, e.g. 'noout' or 'noscrub'.
    """
    # Get OSD option
    if 'option' in flask.request.options:
        option = flask.request.options['option']
    else:
        return flask.jsonify({"message":"ERROR: An OSD option must be specified."}), 510

    return pvcapi.ceph_osd_set(option)

@api.route('/api/v1/storage/ceph/osd/unset', methods=['POST'])
@authenticator
def api_ceph_osd_unset():
    """
    Unset OSD option OPTION on the PVC Ceph storage cluster, e.g. 'noout' or 'noscrub'.
    """
    # Get OSD option
    if 'option' in flask.request.options:
        option = flask.request.options['option']
    else:
        return flask.jsonify({"message":"ERROR: An OSD option must be specified."}), 510

    return pvcapi.ceph_osd_unset(option)

@api.route('/api/v1/storage/ceph/osd/<osd>', methods=['GET'])
@authenticator
def api_ceph_osd_info(osd):
    """
    Get information about an OSD with ID OSD.
    """
    # Same as specifying /osd?limit=OSD
    return pvcapi.ceph_osd_list(osd)

@api.route('/api/v1/storage/ceph/osd/<node>/add', methods=['POST'])
@authenticator
def api_ceph_osd_add(node):
    """
    Add a Ceph OSD to node NODE.
    """
    # Get OSD device
    if 'device' in flask.request.devices:
        device = flask.request.devices['device']
    else:
        return flask.jsonify({"message":"ERROR: A block device must be specified."}), 510

    # Get OSD weight
    if 'weight' in flask.request.weights:
        weight = flask.request.weights['weight']
    else:
        return flask.jsonify({"message":"ERROR: An OSD weight must be specified."}), 510

    return pvcapi.ceph_osd_add(node, device, weight)

@api.route('/api/v1/storage/ceph/osd/<osd>/remove', methods=['POST'])
@authenticator
def api_ceph_osd_remove(osd):
    """
    Remove a Ceph OSD with ID OSD.
    """
    # Verify yes-i-really-mean-it flag
    if not 'flag_yes_i_really_mean_it' in flask.request.values:
        return flask.jsonify({"message":"ERROR: This command can have unintended consequences and should not be automated; if you're sure you know what you're doing, resend with the argument 'flag_yes_i_really_mean_it'."}), 599

    return pvcapi.ceph_osd_remove(osd)

@api.route('/api/v1/storage/ceph/osd/<osd>/in', methods=['POST'])
@authenticator
def api_ceph_osd_in(osd):
    """
    Set in a Ceph OSD with ID OSD.
    """
    return pvcapi.ceph_osd_in(osd)

@api.route('/api/v1/storage/ceph/osd/<osd>/out', methods=['POST'])
@authenticator
def api_ceph_osd_out(osd):
    """
    Set out a Ceph OSD with ID OSD.
    """
    return pvcapi.ceph_osd_out(osd)

@api.route('/api/v1/storage/ceph/pool', methods=['GET'])
@authenticator
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

@api.route('/api/v1/storage/ceph/pool/<pool>', methods=['GET'])
@authenticator
def api_ceph_pool_info(pool):
    """
    Get information about an RBD pool with name POOL.
    """
    # Same as specifying /pool?limit=POOL
    return pvcapi.ceph_pool_list(pool)

@api.route('/api/v1/storage/ceph/pool/<pool>/add', methods=['POST'])
@authenticator
def api_ceph_pool_add(pool):
    """
    Add a Ceph RBD pool with name POOL.
    """
    # Get placement groups
    if 'pgs' in flask.request.values:
        pgs = flask.request.values['pgs']
    else:
        # We default to a very small number; DOCUMENT THIS
        pgs = 128

    return pvcapi.ceph_pool_add(pool, pgs)

@api.route('/api/v1/storage/ceph/pool/<pool>/remove', methods=['POST'])
@authenticator
def api_ceph_pool_remove(pool):
    """
    Remove a Ceph RBD pool with name POOL.
    """
    # Verify yes-i-really-mean-it flag
    if not 'flag_yes_i_really_mean_it' in flask.request.values:
        return flask.jsonify({"message":"ERROR: This command can have unintended consequences and should not be automated; if you're sure you know what you're doing, resend with the argument 'flag_yes_i_really_mean_it'."}), 599

    return pvcapi.ceph_pool_remove(pool)

@api.route('/api/v1/storage/ceph/volume', methods=['GET'])
@authenticator
def api_ceph_volume():
    """
    Get the list of RBD volumes in the Ceph storage cluster.
    """
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

@api.route('/api/v1/storage/ceph/volume/<pool>/<volume>', methods=['GET'])
@authenticator
def api_ceph_volume_info(pool, volume):
    """
    Get information about an RBD volume with name VOLUME in RBD pool with name POOL.
    """
    # Same as specifying /volume?limit=VOLUME
    return pvcapi.ceph_osd_list(pool, osd)

@api.route('/api/v1/storage/ceph/volume/<pool>/<volume>/add', methods=['POST'])
@authenticator
def api_ceph_volume_add(pool, volume):
    """
    Add a Ceph RBD volume with name VOLUME to RBD pool with name POOL.
    """
    # Get volume size
    if 'size' in flask.request.values:
        size = flask.request.values['size']
    else:
        return flask.jsonify({"message":"ERROR: A volume size in bytes (or with an M/G/T suffix) must be specified."}), 510

    return pvcapi.ceph_volume_add(pool, volume, size)

@api.route('/api/v1/storage/ceph/volume/<pool>/<volume>/remove', methods=['POST'])
@authenticator
def api_ceph_volume_remove(pool, volume):
    """
    Remove a Ceph RBD volume with name VOLUME from RBD pool with name POOL.
    """
    return pvcapi.ceph_volume_remove(pool, volume)

@api.route('/api/v1/storage/ceph/volume/snapshot', methods=['GET'])
@authenticator
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

@api.route('/api/v1/storage/ceph/volume/snapshot/<pool>/<volume>/<snapshot>', methods=['GET'])
@authenticator
def api_ceph_volume_snapshot_info(pool, volume, snapshot):
    """
    Get information about a snapshot with name SNAPSHOT of RBD volume with name VOLUME in RBD pool with name POOL.
    """
    # Same as specifying /snapshot?limit=VOLUME
    return pvcapi.ceph_snapshot_list(pool, volume, snapshot)

@api.route('/api/v1/storage/ceph/volume/snapshot/<pool>/<volume>/<snapshot>/add', methods=['POST'])
@authenticator
def api_ceph_volume_snapshot_add(pool, volume, snapshot):
    """
    Add a Ceph RBD volume snapshot with name SNAPSHOT of RBD volume with name VOLUME in RBD pool with name POOL.
    """
    return pvcapi.ceph_volume_snapshot_add(pool, volume, snapshot)

@api.route('/api/v1/storage/ceph/volume/snapshot/<pool>/<volume>/<snapshot>/remove', methods=['POST'])
@authenticator
def api_ceph_volume_snapshot_remove(pool, volume, snapshot):
    """
    Remove a Ceph RBD volume snapshot with name SNAPSHOT from RBD volume with name VOLUME in RBD pool with name POOL.
    """
    return pvcapi.ceph_volume_snapshot_remove(pool, volume, snapshot)

#
# Entrypoint
#
if config['debug']:
    api.run(config['listen_address'], config['listen_port'])
else:
    if config['ssl_enabled']:
        # Run the WSGI server with SSL
        http_server = gevent.pywsgi.WSGIServer((config['listen_address'], config['listen_port']), api,                                           keyfile=config['ssl_key_file'], certfile=config['ssl_cert_file'])
    else:
        # Run the ?WSGI server without SSL
        http_server = gevent.pywsgi.WSGIServer((config['listen_address'], config['listen_port']), api)

    print('Starting PyWSGI server at {}:{} with SSL={}, Authentication={}'.format(config['listen_address'], config['listen_port'], config['ssl_enabled'], config['auth_enabled']))
    http_server.serve_forever()
