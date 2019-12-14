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

import distutils.util
import gevent.pywsgi

import celery as Celery

import api_lib.pvcapi_helper as api_helper
import api_lib.pvcapi_provisioner as api_provisioner

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
        'ssl_cert_file': o_config['pvc']['api']['ssl']['cert_file'],
        'database_host': o_config['pvc']['provisioner']['database']['host'],
        'database_port': int(o_config['pvc']['provisioner']['database']['port']),
        'database_name': o_config['pvc']['provisioner']['database']['name'],
        'database_user': o_config['pvc']['provisioner']['database']['user'],
        'database_password': o_config['pvc']['provisioner']['database']['pass'],
        'queue_host': o_config['pvc']['provisioner']['queue']['host'],
        'queue_port': o_config['pvc']['provisioner']['queue']['port'],
        'queue_path': o_config['pvc']['provisioner']['queue']['path'],
        'storage_hosts': o_config['pvc']['provisioner']['ceph_cluster']['storage_hosts'],
        'storage_domain': o_config['pvc']['provisioner']['ceph_cluster']['storage_domain'],
        'ceph_monitor_port': o_config['pvc']['provisioner']['ceph_cluster']['ceph_monitor_port'],
        'ceph_storage_secret_uuid': o_config['pvc']['provisioner']['ceph_cluster']['ceph_storage_secret_uuid']
    }

    # Use coordinators as storage hosts if not explicitly specified
    if not config['storage_hosts']:
        config['storage_hosts'] = config['coordinators']

    # Set the config object in the api_helper namespace
    api_helper.config = config
    # Set the config object in the api_provisioner namespace
    api_provisioner.config = config
except Exception as e:
    print('ERROR: {}.'.format(e))
    exit(1)

api = flask.Flask(__name__)
api.config['CELERY_BROKER_URL'] = 'redis://{}:{}{}'.format(config['queue_host'], config['queue_port'], config['queue_path'])
api.config['CELERY_RESULT_BACKEND'] = 'redis://{}:{}{}'.format(config['queue_host'], config['queue_port'], config['queue_path'])

if config['debug']:
    api.config['DEBUG'] = True

if config['auth_enabled']:
    api.config["SECRET_KEY"] = config['auth_secret_key']

celery = Celery.Celery(api.name, broker=api.config['CELERY_BROKER_URL'])
celery.conf.update(api.config)

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

#
# Job functions
#

@celery.task(bind=True)
def create_vm(self, vm_name, profile_name):
    return api_provisioner.create_vm(self, vm_name, profile_name)

##########################################################
# API Root/Authentication
##########################################################

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

##########################################################
# Cluster API
##########################################################

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

    return api_helper.node_list(limit)

@api.route('/api/v1/node/<node>', methods=['GET'])
@authenticator
def api_node_element(node):
    # Same as specifying /node?limit=NODE
    return api_helper.node_list(node)

@api.route('/api/v1/node/<node>/daemon-state', methods=['GET'])
@authenticator
def api_node_daemon_state(node):
    if flask.request.method == 'GET':
        return api_helper.node_daemon_state(node)

@api.route('/api/v1/node/<node>/coordinator-state', methods=['GET', 'POST'])
@authenticator
def api_node_coordinator_state(node):
    if flask.request.method == 'GET':
        return api_helper.node_coordinator_state(node)

    if flask.request.method == 'POST':
        if not 'coordinator-state' in flask.request.values:
            flask.abort(400)
        new_state = flask.request.values['coordinator-state']
        if new_state == 'primary':
            return api_helper.node_primary(node)
        if new_state == 'secondary':
            return api_helper.node_secondary(node)
        flask.abort(400)

@api.route('/api/v1/node/<node>/domain-state', methods=['GET', 'POST'])
@authenticator
def api_node_domain_state(node):
    if flask.request.method == 'GET':
        return api_helper.node_domain_state(node)

    if flask.request.method == 'POST':
        if not 'domain-state' in flask.request.values:
            flask.abort(400)
        new_state = flask.request.values['domain-state']
        if new_state == 'ready':
            return api_helper.node_ready(node)
        if new_state == 'flush':
            return api_helper.node_flush(node)
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

        return api_helper.vm_list(node, state, limit)

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

        return api_helper.vm_define(vm, libvirt_xml, node, selector)

@api.route('/api/v1/vm/<vm>', methods=['GET', 'POST', 'PUT', 'DELETE'])
@authenticator
def api_vm_element(vm):
    if flask.request.method == 'GET':
        # Same as specifying /vm?limit=VM
        return api_helper.vm_list(None, None, vm, is_fuzzy=False)

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

        return api_helper.vm_meta(vm, limit, selector, autostart)

    if flask.request.method == 'PUT':
        libvirt_xml = flask.request.data

        if 'restart' in flask.request.values and flask.request.values['restart']:
            flag_restart = True
        else:
            flag_restart = False

        return api_helper.vm_modify(vm, flag_restart, libvirt_xml)

    if flask.request.method == 'DELETE':
        if 'delete_disks' in flask.request.values and flask.request.values['delete_disks']:
            return api_helper.vm_remove(vm)
        else:
            return api_helper.vm_undefine(vm)

@api.route('/api/v1/vm/<vm>/state', methods=['GET', 'POST'])
@authenticator
def api_vm_state(vm):
    if flask.request.method == 'GET':
        return api_helper.vm_state(vm)

    if flask.request.method == 'POST':
        if not 'state' in flask.request.values:
            flask.abort(400)
        new_state = flask.request.values['state']
        if new_state == 'start':
            return api_helper.vm_start(vm)
        if new_state == 'shutdown':
            return api_helper.vm_shutdown(vm)
        if new_state == 'stop':
            return api_helper.vm_stop(vm)
        if new_state == 'restart':
            return api_helper.vm_restart(vm)
        flask.abort(400)

@api.route('/api/v1/vm/<vm>/node', methods=['GET', 'POST'])
@authenticator
def api_vm_node(vm):
    if flask.request.method == 'GET':
        return api_helper.vm_node(vm)

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
        is_migrated = api_helper.vm_is_migrated(vm)

        if action == 'migrate' and not flag_permanent:
            return api_helper.vm_migrate(vm, node, flag_force)
        if action == 'migrate' and flag_permanent:
            return api_helper.vm_move(vm, node)
        if action == 'unmigrate' and is_migrated:
            return api_helper.vm_unmigrate(vm)

        flask.abort(400)

@api.route('/api/v1/vm/<vm>/locks', methods=['GET', 'POST'])
@authenticator
def api_vm_locks(vm):
    if flask.request.method == 'GET':
        return "Not implemented", 400

    if flask.request.method == 'POST':
        return api_helper.vm_flush_locks(vm)


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

        return api_helper.net_list(limit)

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

        return api_helper.net_add(vni, description, nettype, domain, name_servers,
                              ip4_network, ip4_gateway, ip6_network, ip6_gateway,
                              dhcp4_flag, dhcp4_start, dhcp4_end)

@api.route('/api/v1/network/<network>', methods=['GET', 'PUT', 'DELETE'])
@authenticator
def api_net_element(network):
    # Same as specifying /network?limit=NETWORK
    if flask.request.method == 'GET':
        return api_helper.net_list(network)

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

        return api_helper.net_modify(network, description, domain, name_servers,
                                 ip4_network, ip4_gateway,
                                 ip6_network, ip6_gateway,
                                 dhcp4_flag, dhcp4_start, dhcp4_end)

    if flask.request.method == 'DELETE':
        return api_helper.net_remove(network)

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

        return api_helper.net_dhcp_list(network, limit. flag_static)

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

        return api_helper.net_dhcp_add(network, ipaddress, lease, hostname)

@api.route('/api/v1/network/<network>/lease/<lease>', methods=['GET', 'DELETE'])
@authenticator
def api_net_lease_element(network, lease):
    if flask.request.method == 'GET':
        # Same as specifying /network?limit=NETWORK
        return api_helper.net_dhcp_list(network, lease, False)

    if flask.request.method == 'DELETE':
        return api_helper.net_dhcp_remove(network, lease)

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

        return api_helper.net_acl_list(network, limit, direction)

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

        return api_helper.net_acl_add(network, direction, acl, rule, order)

@api.route('/api/v1/network/<network>/acl/<acl>', methods=['GET', 'DELETE'])
@authenticator
def api_net_acl_element(network, acl):
    if flask.request.method == 'GET':
        # Same as specifying /network?limit=NETWORK
        return api_helper.net_acl_list(network, acl, None)

    if flask.request.method == 'DELETE':
        # Get rule direction
        if 'direction' in flask.request.values:
            direction = flask.request.values['limit']
            if not 'in' in direction and not 'out' in direction:
                return flask.jsonify({"message":"ERROR: Direction must be either 'in' or 'out'."}), 400
        else:
            return flask.jsonify({"message":"ERROR: A direction must be specified for the ACL."}), 400

        return api_helper.net_acl_remove(network, direction, acl)

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
    return api_helper.ceph_status()

@api.route('/api/v1/storage/ceph/df', methods=['GET'])
@authenticator
def api_ceph_radosdf():
    return api_helper.ceph_radosdf()

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
            return api_helper.ceph_osd_set(option)
        if action == 'unset':
            return api_helper.ceph_osd_unset(option)

@api.route('/api/v1/storage/ceph/osd', methods=['GET', 'POST'])
@authenticator
def api_ceph_osd_root():
    if flask.request.method == 'GET':
        # Get name limit
        if 'limit' in flask.request.values:
            limit = flask.request.values['limit']
        else:
            limit = None

        return api_helper.ceph_osd_list(limit)

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

        return api_helper.ceph_osd_add(node, device, weight)

@api.route('/api/v1/storage/ceph/osd/<osd>', methods=['GET', 'DELETE'])
@authenticator
def api_ceph_osd_element(osd):
    if flask.request.method == 'GET':
        # Same as specifying /osd?limit=OSD
        return api_helper.ceph_osd_list(osd)

    if flask.request.method == 'DELETE':
        # Verify yes-i-really-mean-it flag
        if not 'yes_i_really_mean_it' in flask.request.values:
            return flask.jsonify({"message":"ERROR: This command can have unintended consequences and should not be automated; if you're sure you know what you're doing, resend with the argument 'yes_i_really_mean_it'."}), 400

        return api_helper.ceph_osd_remove(osd)

@api.route('/api/v1/storage/ceph/osd/<osd>/state', methods=['GET', 'POST'])
@authenticator
def api_ceph_osd_state(osd):
    if flask.request.method == 'GET':
        return api_helper.ceph_osd_state(osd)

    if flask.request.method == 'POST':
        if 'state' in flask.request.values:
            state = flask.request.values['state']
            if not 'in' in state and not 'out' in state:
                return flask.jsonify({"message":"ERROR: State must be one of: in, out."}), 400
        else:
            return flask.jsonify({"message":"ERROR: A state must be specified."}), 400

        if state == 'in':
            return api_helper.ceph_osd_in(osd)
        if state == 'out':
            return api_helper.ceph_osd_out(osd)

@api.route('/api/v1/storage/ceph/pool', methods=['GET', 'POST'])
@authenticator
def api_ceph_pool_root():
    if flask.request.method == 'GET':
        # Get name limit
        if 'limit' in flask.request.values:
            limit = flask.request.values['limit']
        else:
            limit = None

        return api_helper.ceph_pool_list(limit)

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

        return api_helper.ceph_pool_add(pool, pgs)

@api.route('/api/v1/storage/ceph/pool/<pool>', methods=['GET', 'DELETE'])
@authenticator
def api_ceph_pool_element(pool):
    if flask.request.method == 'GET':
        # Same as specifying /pool?limit=POOL
        return api_helper.ceph_pool_list(pool)

    if flask.request.method == 'DELETE':
        # Verify yes-i-really-mean-it flag
        if not 'yes_i_really_mean_it' in flask.request.values:
            return flask.jsonify({"message":"ERROR: This command can have unintended consequences and should not be automated; if you're sure you know what you're doing, resend with the argument 'yes_i_really_mean_it'."}), 400

        return api_helper.ceph_pool_remove(pool)

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

        return api_helper.ceph_volume_list(pool, limit)

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
            return api_helper.ceph_volume_clone(pool, volume, source_volume)
        else:
            return api_helper.ceph_volume_add(pool, volume, size)

@api.route('/api/v1/storage/ceph/volume/<pool>/<volume>', methods=['GET', 'PUT', 'DELETE'])
@authenticator
def api_ceph_volume_element(pool, volume):
    if flask.request.method == 'GET':
        # Same as specifying /volume?limit=VOLUME
        return api_helper.ceph_volume_list(pool, volume)

    if flask.request.method == 'PUT':
        if 'size' in flask.request.values:
            size = flask.request.values['size']

        if 'name' in flask.request.values:
            name = flask.request.values['name']

        if size and not name:
            return api_helper.ceph_volume_resize(pool, volume, size)

        if name and not size:
            return api_helper.ceph_volume_rename(pool, volume, name)

        return flask.jsonify({"message":"ERROR: No name or size specified, or both specified; not changing anything."}), 400

    if flask.request.method == 'DELETE':
        return api_helper.ceph_volume_remove(pool, volume)

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

        return api_helper.ceph_volume_snapshot_list(pool, volume, limit)

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

        return api_helper.ceph_volume_snapshot_add(pool, volume, snapshot)


@api.route('/api/v1/storage/ceph/volume/snapshot/<pool>/<volume>/<snapshot>', methods=['GET', 'PUT', 'DELETE'])
@authenticator
def api_ceph_volume_snapshot_element(pool, volume, snapshot):
    if flask.request.method == 'GET':
        # Same as specifying /snapshot?limit=VOLUME
        return api_helper.ceph_volume_snapshot_list(pool, volume, snapshot)

    if flask.request.method == 'PUT':
        if 'name' in flask.request.values:
            name = flask.request.values['name']
        else:
            return flask.jsonify({"message":"ERROR: A new name must be specified."}), 400

        return api_helper.ceph_volume_snapshot_rename(pool, volume, snapshot, name)

    if flask.request.method == 'DELETE':
        return api_helper.ceph_volume_snapshot_remove(pool, volume, snapshot)

##########################################################
# Provisioner API
##########################################################

#
# Template endpoints
#
@api.route('/api/v1/provisioner/template', methods=['GET'])
@authenticator
def api_template_root():
    """
    /template - Manage provisioning templates for VM creation.

    GET: List all templates in the provisioning system.
        ?limit: Specify a limit to queries. Fuzzy by default; use ^ and $ to force exact matches.
    """
    # Get name limit
    if 'limit' in flask.request.values:
        limit = flask.request.values['limit']
    else:
        limit = None

    return flask.jsonify(api_provisioner.template_list(limit)), 200

@api.route('/api/v1/provisioner/template/system', methods=['GET', 'POST'])
@authenticator
def api_template_system_root():
    """
    /template/system - Manage system provisioning templates for VM creation.

    GET: List all system templates in the provisioning system.
        ?limit: Specify a limit to queries. Fuzzy by default; use ^ and $ to force exact matches.
            * type: text
            * optional: true
            * requires: N/A

    POST: Add new system template.
        ?name: The name of the template.
            * type: text
            * optional: false
            * requires: N/A
        ?vcpus: The number of VCPUs.
            * type: integer
            * optional: false
            * requires: N/A
        ?vram: The amount of RAM in MB.
            * type: integer, Megabytes (MB)
            * optional: false
            * requires: N/A
        ?serial: Enable serial console.
            * type: boolean
            * optional: false
            * requires: N/A
        ?vnc: True/False, enable VNC console.
            * type: boolean
            * optional: false
            * requires: N/A
        ?vnc_bind: Address to bind VNC to.
            * default: '127.0.0.1'
            * type: IP Address (or '0.0.0.0' wildcard)
            * optional: true
            * requires: vnc=True
        ?node_limit: CSV list of node(s) to limit VM operation to
            * type: CSV of valid PVC nodes
            * optional: true
            * requires: N/A
        ?node_selector: Selector to use for node migrations after initial provisioning
            * type: Valid PVC node selector
            * optional: true
            * requires: N/A
        ?start_with_node: Whether to start limited node with the parent node
            * default: false
            * type: boolean
            * optional: true
            * requires: N/A
    """
    if flask.request.method == 'GET':
        # Get name limit
        if 'limit' in flask.request.values:
            limit = flask.request.values['limit']
        else:
            limit = None

        return flask.jsonify(api_provisioner.list_template_system(limit)), 200

    if flask.request.method == 'POST':
        # Get name data
        if 'name' in flask.request.values:
            name = flask.request.values['name']
        else:
            return flask.jsonify({"message": "A name must be specified."}), 400

        # Get vcpus data
        if 'vcpus' in flask.request.values:
            try:
                vcpu_count = int(flask.request.values['vcpus'])
            except:
                return flask.jsonify({"message": "A vcpus value must be an integer."}), 400
        else:
            return flask.jsonify({"message": "A vcpus value must be specified."}), 400

        # Get vram data
        if 'vram' in flask.request.values:
            try:
                vram_mb = int(flask.request.values['vram'])
            except:
                return flask.jsonify({"message": "A vram integer value in Megabytes must be specified."}), 400
        else:
            return flask.jsonify({"message": "A vram integer value in Megabytes must be specified."}), 400

        # Get serial configuration
        if 'serial' in flask.request.values and bool(distutils.util.strtobool(flask.request.values['serial'])):
            serial = True
        else:
            serial = False

        # Get VNC configuration
        if 'vnc' in flask.request.values and bool(distutils.util.strtobool(flask.request.values['vnc'])):
            vnc = True

            if 'vnc_bind' in flask.request.values:
                vnc_bind = flask.request.values['vnc_bind_address']
            else:
                vnc_bind = None
        else:
            vnc = False
            vnc_bind = None

        # Get metadata
        if 'node_limit' in flask.request.values:
            node_limit = flask.request.values['node_limit']
        else:
            node_limit = None

        if 'node_selector' in flask.request.values:
            node_selector = flask.request.values['node_selector']
        else:
            node_selector = None

        if 'start_with_node' in flask.request.values and bool(distutils.util.strtobool(flask.request.values['start_with_node'])):
            start_with_node = True
        else:
            start_with_node = False

        return api_provisioner.create_template_system(name, vcpu_count, vram_mb, serial, vnc, vnc_bind, node_limit, node_selector, start_with_node)

@api.route('/api/v1/provisioner/template/system/<template>', methods=['GET', 'POST', 'DELETE'])
@authenticator
def api_template_system_element(template):
    """
    /template/system/<template> - Manage system provisioning template <template>.

    GET: Show details of system template <template>.

    POST: Add new system template with name <template>.
        ?vcpus: The number of VCPUs.
            * type: integer
            * optional: false
            * requires: N/A
        ?vram: The amount of RAM in MB.
            * type: integer, Megabytes (MB)
            * optional: false
            * requires: N/A
        ?serial: Enable serial console.
            * type: boolean
            * optional: false
            * requires: N/A
        ?vnc: True/False, enable VNC console.
            * type: boolean
            * optional: false
            * requires: N/A
        ?vnc_bind: Address to bind VNC to.
            * default: '127.0.0.1'
            * type: IP Address (or '0.0.0.0' wildcard)
            * optional: true
            * requires: vnc=True
        ?node_limit: CSV list of node(s) to limit VM operation to
            * type: CSV of valid PVC nodes
            * optional: true
            * requires: N/A
        ?node_selector: Selector to use for node migrations after initial provisioning
            * type: Valid PVC node selector
            * optional: true
            * requires: N/A
        ?start_with_node: Whether to start limited node with the parent node
            * default: false
            * type: boolean
            * optional: true

    DELETE: Remove system template <template>.
    """
    if flask.request.method == 'GET':
        return flask.jsonify(api_provisioner.list_template_system(template, is_fuzzy=False)), 200

    if flask.request.method == 'POST':
        # Get vcpus data
        if 'vcpus' in flask.request.values:
            try:
                vcpu_count = int(flask.request.values['vcpus'])
            except:
                return flask.jsonify({"message": "A vcpus value must be an integer."}), 400
        else:
            return flask.jsonify({"message": "A vcpus value must be specified."}), 400

        # Get vram data
        if 'vram' in flask.request.values:
            try:
                vram_mb = int(flask.request.values['vram'])
            except:
                return flask.jsonify({"message": "A vram integer value in Megabytes must be specified."}), 400
        else:
            return flask.jsonify({"message": "A vram integer value in Megabytes must be specified."}), 400

        # Get serial configuration
        if 'serial' in flask.request.values and bool(distutils.util.strtobool(flask.request.values['serial'])):
            serial = True
        else:
            serial = False

        # Get VNC configuration
        if 'vnc' in flask.request.values and bool(distutils.util.strtobool(flask.request.values['vnc'])):
            vnc = True

            if 'vnc_bind' in flask.request.values:
                vnc_bind = flask.request.values['vnc_bind_address']
            else:
                vnc_bind = None
        else:
            vnc = False
            vnc_bind = None

        # Get metadata
        if 'node_limit' in flask.request.values:
            node_limit = flask.request.values['node_limit']
        else:
            node_limit = None

        if 'node_selector' in flask.request.values:
            node_selector = flask.request.values['node_selector']
        else:
            node_selector = None

        if 'start_with_node' in flask.request.values and bool(distutils.util.strtobool(flask.request.values['start_with_node'])):
            start_with_node = True
        else:
            start_with_node = False

        return api_provisioner.create_template_system(template, vcpu_count, vram_mb, serial, vnc, vnc_bind)

    if flask.request.method == 'DELETE':
        return api_provisioner.delete_template_system(template)

@api.route('/api/v1/provisioner/template/network', methods=['GET', 'POST'])
@authenticator
def api_template_network_root():
    """
    /template/network - Manage network provisioning templates for VM creation.

    GET: List all network templates in the provisioning system.
        ?limit: Specify a limit to queries. Fuzzy by default; use ^ and $ to force exact matches.
            * type: text
            * optional: true
            * requires: N/A

    POST: Add new network template.
        ?name: The name of the template.
            * type: text
            * optional: false
            * requires: N/A
        ?mac_template: The MAC address template for the template.
            * type: MAC address template
            * optional: true
            * requires: N/A

    The MAC address template should use the following conventions:
      * use {prefix} to represent the Libvirt MAC prefix, always "52:54:00"
      * use {vmid} to represent the hex value (<16) of the host's ID (e.g. server4 has ID 4, server has ID 0)
      * use {netid} to represent the hex value (<16) of the network's sequential integer ID (first is 0, etc.)

      Example: "{prefix}:ff:ff:{vmid}{netid}"
    """
    if flask.request.method == 'GET':
        # Get name limit
        if 'limit' in flask.request.values:
            limit = flask.request.values['limit']
        else:
            limit = None

        return flask.jsonify(api_provisioner.list_template_network(limit)), 200

    if flask.request.method == 'POST':
        # Get name data
        if 'name' in flask.request.values:
            name = flask.request.values['name']
        else:
            return flask.jsonify({"message": "A name must be specified."}), 400

        if 'mac_template' in flask.request.values:
            mac_template = flask.request.values['mac_template']
        else:
            mac_template = None
           
        return api_provisioner.create_template_network(name, mac_template)

@api.route('/api/v1/provisioner/template/network/<template>', methods=['GET', 'POST', 'DELETE'])
@authenticator
def api_template_network_element(template):
    """
    /template/network/<template> - Manage network provisioning template <template>.

    GET: Show details of network template <template>.

    POST: Add new network template with name <template>.
        ?mac_template: The MAC address template for the template.
            * type: text
            * optional: true
            * requires: N/A

    DELETE: Remove network template <template>.
    """
    if flask.request.method == 'GET':
        return flask.jsonify(api_provisioner.list_template_network(template, is_fuzzy=False)), 200

    if flask.request.method == 'POST':
        if 'mac_template' in flask.request.values:
            mac_template = flask.request.values['mac_template']
        else:
            mac_template = None
           
        return api_provisioner.create_template_network(template, mac_template)

    if flask.request.method == 'DELETE':
        return api_provisioner.delete_template_network(template)

@api.route('/api/v1/provisioner/template/network/<template>/net', methods=['GET', 'POST', 'DELETE'])
@authenticator
def api_template_network_net_root(template):
    """
    /template/network/<template>/net - Manage network VNIs in network provisioning template <template>.

    GET: Show details of network template <template>.

    POST: Add new network VNI to network template <template>.
        ?vni: The network VNI.
            * type: integer
            * optional: false
            * requires: N/A

    DELETE: Remove network VNI from network template <template>.
        ?vni: The network VNI.
            * type: integer
            * optional: false
            * requires: N/A
    """
    if flask.request.method == 'GET':
        return flask.jsonify(api_provisioner.list_template_network(template, is_fuzzy=False)), 200

    if flask.request.method == 'POST':
        if 'vni' in flask.request.values:
            vni = flask.request.values['vni']
        else:
            return flask.jsonify({"message": "A VNI must be specified."}), 400

        return api_provisioner.create_template_network_element(template, vni)

    if flask.request.method == 'DELETE':
        if 'vni' in flask.request.values:
            vni = flask.request.values['vni']
        else:
            return flask.jsonify({"message": "A VNI must be specified."}), 400

        return api_provisioner.delete_template_network_element(template, vni)
        
@api.route('/api/v1/provisioner/template/network/<template>/net/<vni>', methods=['GET', 'POST', 'DELETE'])
@authenticator
def api_template_network_net_element(template, vni):
    """
    /template/network/<template>/net/<vni> - Manage network VNI <vni> in network provisioning template <template>.

    GET: Show details of network template <template>.

    POST: Add new network VNI <vni> to network template <template>.

    DELETE: Remove network VNI <vni> from network template <template>.
    """
    if flask.request.method == 'GET':
        networks = api_provisioner.list_template_network_vnis(template)
        for network in networks:
            if int(network['vni']) == int(vni):
                return flask.jsonify(network), 200
        return flask.jsonify({"message": "Found no network with VNI {} in network template {}".format(vni, template)}), 404


    if flask.request.method == 'POST':
        return api_provisioner.create_template_network_element(template, vni)

    if flask.request.method == 'DELETE':
        return api_provisioner.delete_template_network_element(template, vni)
        
@api.route('/api/v1/provisioner/template/storage', methods=['GET', 'POST'])
@authenticator
def api_template_storage_root():
    """
    /template/storage - Manage storage provisioning templates for VM creation.

    GET: List all storage templates in the provisioning system.
        ?limit: Specify a limit to queries. Fuzzy by default; use ^ and $ to force exact matches.
            * type: text
            * optional: true
            * requires: N/A

    POST: Add new storage template.
        ?name: The name of the template.
            * type: text
            * optional: false
            * requires: N/A
    """
    if flask.request.method == 'GET':
        # Get name limit
        if 'limit' in flask.request.values:
            limit = flask.request.values['limit']
        else:
            limit = None

        return flask.jsonify(api_provisioner.list_template_storage(limit)), 200

    if flask.request.method == 'POST':
        # Get name data
        if 'name' in flask.request.values:
            name = flask.request.values['name']
        else:
            return flask.jsonify({"message": "A name must be specified."}), 400

        return api_provisioner.create_template_storage(name)

@api.route('/api/v1/provisioner/template/storage/<template>', methods=['GET', 'POST', 'DELETE'])
@authenticator
def api_template_storage_element(template):
    """
    /template/storage/<template> - Manage storage provisioning template <template>.

    GET: Show details of storage template.

    POST: Add new storage template.

    DELETE: Remove storage template.
    """
    if flask.request.method == 'GET':
        return flask.jsonify(api_provisioner.list_template_storage(template, is_fuzzy=False)), 200

    if flask.request.method == 'POST':
        return api_provisioner.create_template_storage(template)

    if flask.request.method == 'DELETE':
        return api_provisioner.delete_template_storage(template)

        if 'disk' in flask.request.values:
            disks = list()
            for disk in flask.request.values.getlist('disk'):
                disk_data = disk.split(',')
                disks.append(disk_data)
        else:
            return flask.jsonify({"message": "A disk must be specified."}), 400

@api.route('/api/v1/provisioner/template/storage/<template>/disk', methods=['GET', 'POST', 'DELETE'])
@authenticator
def api_template_storage_disk_root(template):
    """
    /template/storage/<template>/disk - Manage disks in storage provisioning template <template>.

    GET: Show details of storage template <template>.

    POST: Add new disk to storage template <template>.
        ?disk_id: The identifier of the disk.
            * type: Disk identifier in 'sdX' or 'vdX' format, unique within template
            * optional: false
            * requires: N/A
        ?pool: The storage pool in which to store the disk.
            * type: Storage Pool name
            * optional: false
            * requires: N/A
        ?disk_size: The disk size in GB.
            * type: integer, Gigabytes (GB)
            * optional: false
            * requires: N/A
        ?filesystem: The Linux guest filesystem for the disk
            * default: unformatted filesystem
            * type: Valid Linux filesystem
            * optional: true
            * requires: N/A
        ?filesystem_arg: Argument for the guest filesystem
            * type: Valid mkfs.<filesystem> argument, multiple
            * optional: true
            * requires: N/A
        ?mountpoint: The Linux guest mountpoint for the disk
            * default: unmounted in guest
            * type: Valid Linux mountpoint (e.g. '/', '/var', etc.)
            * optional: true
            * requires: ?filesystem

    DELETE: Remove disk from storage template <template>.
        ?disk_id: The identifier of the disk.
            * type: Disk identifier in 'sdX' or 'vdX' format
            * optional: false
            * requires: N/A
    """
    if flask.request.method == 'GET':
        return flask.jsonify(api_provisioner.list_template_storage(template, is_fuzzy=False)), 200

    if flask.request.method == 'POST':
        if 'disk_id' in flask.request.values:
            disk_id = flask.request.values['disk_id']
        else:
            return flask.jsonify({"message": "A disk ID in sdX/vdX format must be specified."}), 400

        if 'pool' in flask.request.values:
            pool = flask.request.values['pool']
        else:
            return flask.jsonify({"message": "A pool name must be specified."}), 400

        if 'disk_size' in flask.request.values:
            disk_size = flask.request.values['disk_size']
        else:
            return flask.jsonify({"message": "A disk size in GB must be specified."}), 400

        if 'filesystem' in flask.request.values:
            filesystem = flask.request.values['filesystem']
        else:
            filesystem = None
           
        if 'filesystem_arg' in flask.request.values:
            filesystem_args = flask.request.values.getlist('filesystem_arg')
        else:
            filesystem_args = None
           
        if 'mountpoint' in flask.request.values:
            mountpoint = flask.request.values['mountpoint']
        else:
            mountpoint = None
           
        return api_provisioner.create_template_storage_element(template, pool, disk_id, disk_size, filesystem, filesystem_args, mountpoint)

    if flask.request.method == 'DELETE':
        if 'disk_id' in flask.request.values:
            disk_id = flask.request.values['disk_id']
        else:
            return flask.jsonify({"message": "A disk ID in sdX/vdX format must be specified."}), 400

        return api_provisioner.delete_template_storage_element(template, disk_id)
        
@api.route('/api/v1/provisioner/template/storage/<template>/disk/<disk_id>', methods=['GET', 'POST', 'DELETE'])
@authenticator
def api_template_storage_disk_element(template, disk_id):
    """
    /template/storage/<template>/disk/<disk_id> - Manage disk <disk_id> in storage provisioning template <template>.

    GET: Show details of disk <disk_id> storage template <template>.

    POST: Add new storage VNI <vni> to storage template <template>.
        ?pool: The storage pool in which to store the disk.
            * type: Storage Pool name
            * optional: false
            * requires: N/A
        ?disk_size: The disk size in GB.
            * type: integer, Gigabytes (GB)
            * optional: false
            * requires: N/A
        ?filesystem: The Linux guest filesystem for the disk
            * default: unformatted filesystem
            * type: Valid Linux filesystem
            * optional: true
            * requires: N/A
        ?mountpoint: The Linux guest mountpoint for the disk
            * default: unmounted in guest
            * type: Valid Linux mountpoint (e.g. '/', '/var', etc.)
            * optional: true
            * requires: ?filesystem

    DELETE: Remove storage VNI <vni> from storage template <template>.
    """
    if flask.request.method == 'GET':
        disks = api_provisioner.list_template_storage_disks(template)
        for disk in disks:
            if disk['disk_id'] == disk_id:
                return flask.jsonify(disk), 200
        return flask.jsonify({"message": "Found no disk with ID {} in storage template {}".format(disk_id, template)}), 404

    if flask.request.method == 'POST':
        if 'pool' in flask.request.values:
            pool = flask.request.values['pool']
        else:
            return flask.jsonify({"message": "A pool name must be specified."}), 400

        if 'disk_size' in flask.request.values:
            disk_size = flask.request.values['disk_size']
        else:
            return flask.jsonify({"message": "A disk size in GB must be specified."}), 400

        if 'filesystem' in flask.request.values:
            filesystem = flask.request.values['filesystem']
        else:
            filesystem = None
           
        if 'filesystem_arg' in flask.request.values:
            filesystem_args = flask.request.values.getlist('filesystem_arg')
        else:
            filesystem_args = None
           
        if 'mountpoint' in flask.request.values:
            mountpoint = flask.request.values['mountpoint']
        else:
            mountpoint = None
           
        return api_provisioner.create_template_storage_element(template, pool, disk_id, disk_size, filesystem, filesystem_args, mountpoint)

    if flask.request.method == 'DELETE':
        return api_provisioner.delete_template_storage_element(template, disk_id)

@api.route('/api/v1/provisioner/template/userdata', methods=['GET', 'POST', 'PUT'])
@authenticator
def api_template_userdata_root():
    """
    /template/userdata - Manage userdata provisioning templates for VM creation.

    GET: List all userdata templates in the provisioning system.
        ?limit: Specify a limit to queries. Fuzzy by default; use ^ and $ to force exact matches.
            * type: text
            * optional: true
            * requires: N/A

    POST: Add new userdata template.
        ?name: The name of the template.
            * type: text
            * optional: false
            * requires: N/A
        ?data: The raw text of the cloud-init user-data.
            * type: text (freeform)
            * optional: false
            * requires: N/A

    PUT: Update existing userdata template.
        ?name: The name of the template.
            * type: text
            * optional: false
            * requires: N/A
        ?data: The raw text of the cloud-init user-data.
            * type: text (freeform)
            * optional: false
            * requires: N/A
    """
    if flask.request.method == 'GET':
        # Get name limit
        if 'limit' in flask.request.values:
            limit = flask.request.values['limit']
        else:
            limit = None

        return flask.jsonify(api_provisioner.list_template_userdata(limit)), 200

    if flask.request.method == 'POST':
        # Get name data
        if 'name' in flask.request.values:
            name = flask.request.values['name']
        else:
            return flask.jsonify({"message": "A name must be specified."}), 400

        # Get userdata data
        if 'data' in flask.request.values:
            data = flask.request.values['data']
        else:
            return flask.jsonify({"message": "A userdata object must be specified."}), 400

        return api_provisioner.create_template_userdata(name, data)

    if flask.request.method == 'PUT':
        # Get name data
        if 'name' in flask.request.values:
            name = flask.request.values['name']
        else:
            return flask.jsonify({"message": "A name must be specified."}), 400

        # Get userdata data
        if 'data' in flask.request.values:
            data = flask.request.values['data']
        else:
            return flask.jsonify({"message": "A userdata object must be specified."}), 400

        return api_provisioner.update_template_userdata(name, data)

@api.route('/api/v1/provisioner/template/userdata/<template>', methods=['GET', 'POST','PUT', 'DELETE'])
@authenticator
def api_template_userdata_element(template):
    """
    /template/userdata/<template> - Manage userdata provisioning template <template>.

    GET: Show details of userdata template.

    POST: Add new userdata template.
        ?data: The raw text of the cloud-init user-data.
            * type: text (freeform)
            * optional: false
            * requires: N/A

    PUT: Modify existing userdata template.
        ?data: The raw text of the cloud-init user-data.
            * type: text (freeform)
            * optional: false
            * requires: N/A

    DELETE: Remove userdata template.
    """
    if flask.request.method == 'GET':
        return flask.jsonify(api_provisioner.list_template_userdata(template, is_fuzzy=False)), 200

    if flask.request.method == 'POST':
        # Get userdata data
        if 'data' in flask.request.values:
            data = flask.request.values['data']
        else:
            return flask.jsonify({"message": "A userdata object must be specified."}), 400

        return api_provisioner.create_template_userdata(template, data)

    if flask.request.method == 'PUT':
        # Get userdata data
        if 'data' in flask.request.values:
            data = flask.request.values['data']
        else:
            return flask.jsonify({"message": "A userdata object must be specified."}), 400

        return api_provisioner.update_template_userdata(template, data)

    if flask.request.method == 'DELETE':
        return api_provisioner.delete_template_userdata(template)

#
# Script endpoints
#
@api.route('/api/v1/provisioner/script', methods=['GET', 'POST', 'PUT'])
@authenticator
def api_script_root():
    """
    /script - Manage provisioning scripts for VM creation.

    GET: List all scripts in the provisioning system.
        ?limit: Specify a limit to queries. Fuzzy by default; use ^ and $ to force exact matches.
            * type: text
            * optional: true
            * requires: N/A

    POST: Add new provisioning script.
        ?name: The name of the script.
            * type: text
            * optional: false
            * requires: N/A
        ?data: The raw text of the script.
            * type: text (freeform)
            * optional: false
            * requires: N/A
    PUT: Modify existing provisioning script.
        ?name: The name of the script.
            * type: text
            * optional: false
            * requires: N/A
        ?data: The raw text of the script.
            * type: text (freeform)
            * optional: false
            * requires: N/A
    """
    if flask.request.method == 'GET':
        # Get name limit
        if 'limit' in flask.request.values:
            limit = flask.request.values['limit']
        else:
            limit = None

        return flask.jsonify(api_provisioner.list_script(limit)), 200

    if flask.request.method == 'POST':
        # Get name data
        if 'name' in flask.request.values:
            name = flask.request.values['name']
        else:
            return flask.jsonify({"message": "A name must be specified."}), 400

        # Get script data
        if 'data' in flask.request.values:
            data = flask.request.values['data']
        else:
            return flask.jsonify({"message": "Script data must be specified."}), 400

        return api_provisioner.create_script(name, data)

    if flask.request.method == 'PUT':
        # Get name data
        if 'name' in flask.request.values:
            name = flask.request.values['name']
        else:
            return flask.jsonify({"message": "A name must be specified."}), 400

        # Get script data
        if 'data' in flask.request.values:
            data = flask.request.values['data']
        else:
            return flask.jsonify({"message": "Script data must be specified."}), 400

        return api_provisioner.update_script(name, data)


@api.route('/api/v1/provisioner/script/<script>', methods=['GET', 'POST', 'PUT', 'DELETE'])
@authenticator
def api_script_element(script):
    """
    /script/<script> - Manage provisioning script <script>.

    GET: Show details of provisioning script.

    POST: Add new provisioning script.
        ?data: The raw text of the script.
            * type: text (freeform)
            * optional: false
            * requires: N/A

    PUT: Modify existing provisioning script.
        ?data: The raw text of the script.
            * type: text (freeform)
            * optional: false
            * requires: N/A

    DELETE: Remove provisioning script.
    """
    if flask.request.method == 'GET':
        return flask.jsonify(api_provisioner.list_script(script, is_fuzzy=False)), 200

    if flask.request.method == 'POST':
        # Get script data
        if 'data' in flask.request.values:
            data = flask.request.values['data']
        else:
            return flask.jsonify({"message": "Script data must be specified."}), 400

        return api_provisioner.create_script(script, data)

    if flask.request.method == 'PUT':
        # Get script data
        if 'data' in flask.request.values:
            data = flask.request.values['data']
        else:
            return flask.jsonify({"message": "Script data must be specified."}), 400

        return api_provisioner.update_script(script, data)

    if flask.request.method == 'DELETE':
        return api_provisioner.delete_script(script)

#
# Profile endpoints
#
@api.route('/api/v1/provisioner/profile', methods=['GET', 'POST'])
@authenticator
def api_profile_root():
    """
    /profile - Manage VM profiles for VM creation.

    GET: List all VM profiles in the provisioning system.
        ?limit: Specify a limit to queries. Fuzzy by default; use ^ and $ to force exact matches.
            * type: text
            * optional: true
            * requires: N/A

    POST: Add new VM profile.
        ?name: The name of the profile.
            * type: text
            * optional: false
            * requires: N/A
        ?system_template: The name of the system template.
            * type: text
            * optional: false
            * requires: N/A
        ?network_template: The name of the network template.
            * type: text
            * optional: false
            * requires: N/A
        ?storage_template: The name of the storage template.
            * type: text
            * optional: false
            * requires: N/A
        ?userdata_template: The name of the userdata template.
            * type: text
            * optional: false
            * requires: N/A
        ?script: The name of the provisioning script.
            * type: text
            * optional: false
            * requires: N/A
        ?arg: An arbitrary key=value argument for use by the provisioning script.
            * type: key-value pair, multiple
            * optional: true
            * requires: N/A
    """
    if flask.request.method == 'GET':
        # Get name limit
        if 'limit' in flask.request.values:
            limit = flask.request.values['limit']
        else:
            limit = None

        return flask.jsonify(api_provisioner.list_profile(limit)), 200

    if flask.request.method == 'POST':
        # Get name data
        if 'name' in flask.request.values:
            name = flask.request.values['name']
        else:
            return flask.jsonify({"message": "A name must be specified."}), 400

        # Get system_template data
        if 'system_template' in flask.request.values:
            system_template = flask.request.values['system_template']
        else:
            return flask.jsonify({"message": "A system template must be specified."}), 400

        # Get network_template data
        if 'network_template' in flask.request.values:
            network_template = flask.request.values['network_template']
        else:
            return flask.jsonify({"message": "A network template must be specified."}), 400

        # Get storage_template data
        if 'storage_template' in flask.request.values:
            storage_template = flask.request.values['storage_template']
        else:
            return flask.jsonify({"message": "A storage template must be specified."}), 400

        # Get userdata_template data
        if 'userdata_template' in flask.request.values:
            userdata_template = flask.request.values['userdata_template']
        else:
            return flask.jsonify({"message": "A userdata template must be specified."}), 400

        # Get script data
        if 'script' in flask.request.values:
            script = flask.request.values['script']
        else:
            return flask.jsonify({"message": "A script must be specified."}), 400

        if 'arg' in flask.request.values:
            arguments = flask.request.values.getlist('arg')
        else:
            arguments = None

        return api_provisioner.create_profile(name, system_template, network_template, storage_template, userdata_template, script, arguments)

@api.route('/api/v1/provisioner/profile/<profile>', methods=['GET', 'POST', 'DELETE'])
@authenticator
def api_profile_element(profile):
    """
    /profile/<profile> - Manage VM profile <profile>.

    GET: Show details of VM profile.

    POST: Add new VM profile.
        ?system_template: The name of the system template.
            * type: text
            * optional: false
            * requires: N/A
        ?network_template: The name of the network template.
            * type: text
            * optional: false
            * requires: N/A
        ?storage_template: The name of the storage template.
            * type: text
            * optional: false
            * requires: N/A
        ?userdata_template: The name of the userdata template.
            * type: text
            * optional: false
            * requires: N/A
        ?script: The name of the provisioning script.
            * type: text
            * optional: false
            * requires: N/A

    DELETE: Remove VM profile.
    """
    if flask.request.method == 'GET':
        return flask.jsonify(api_provisioner.list_profile(profile, is_fuzzy=False)), 200

    if flask.request.method == 'POST':
        # Get system_template data
        if 'system_template' in flask.request.values:
            system_template = flask.request.values['system_template']
        else:
            return flask.jsonify({"message": "A system template must be specified."}), 400

        # Get network_template data
        if 'network_template' in flask.request.values:
            network_template = flask.request.values['network_template']
        else:
            return flask.jsonify({"message": "A network template must be specified."}), 400

        # Get storage_template data
        if 'storage_template' in flask.request.values:
            storage_template = flask.request.values['storage_template']
        else:
            return flask.jsonify({"message": "A storage template must be specified."}), 400

        # Get userdata_template data
        if 'userdata_template' in flask.request.values:
            userdata_template = flask.request.values['userdata_template']
        else:
            return flask.jsonify({"message": "A userdata template must be specified."}), 400

        # Get script data
        if 'script' in flask.request.values:
            script = flask.request.values['script']
        else:
            return flask.jsonify({"message": "A script must be specified."}), 400

        return api_provisioner.create_profile(profile, system_template, network_template, storage_template, userdata_template, script)

    if flask.request.method == 'DELETE':
        return api_provisioner.delete_profile(profile)

#
# Provisioning endpoints
#
@api.route('/api/v1/provisioner/create', methods=['POST'])
@authenticator
def api_create_root():
    """
    /create - Create new VM on the cluster.

    POST: Create new VM.
        ?name: The name of the VM.
            * type: text
            * optional: false
            * requires: N/A
        ?profile: The profile name of the VM.
            * type: text
            * optional: flase
            * requires: N/A
    """
    if 'name' in flask.request.values:
        name = flask.request.values['name']
    else:
        return flask.jsonify({"message": "A VM name must be specified."}), 400

    if 'profile' in flask.request.values:
        profile = flask.request.values['profile']
    else:
        return flask.jsonify({"message": "A VM profile must be specified."}), 400

    task = create_vm.delay(name, profile)

    return flask.jsonify({"task_id": task.id}), 202, {'Location': flask.url_for('api_status_root', task_id=task.id)}

@api.route('/api/v1/provisioner/status/<task_id>', methods=['GET'])
@authenticator
def api_status_root(task_id):
    """
    /status - Report on VM creation status.

    GET: Get status of the VM provisioning.
        ?task: The task ID returned from the '/create' endpoint.
            * type: text
            * optional: flase
            * requires: N/A
    """
    task = create_vm.AsyncResult(task_id)
    if task.state == 'PENDING':
        # job did not start yet
        response = {
            'state': task.state,
            'current': 0,
            'total': 1,
            'status': 'Pending...'
        }
    elif task.state != 'FAILURE':
        # job is still running
        response = {
            'state': task.state,
            'current': task.info.get('current', 0),
            'total': task.info.get('total', 1),
            'status': task.info.get('status', '')
        }
        if 'result' in task.info:
            response['result'] = task.info['result']
    else:
        # something went wrong in the background job
        response = {
            'state': task.state,
            'current': 1,
            'total': 1,
            'status': str(task.info),  # this is the exception raised
        }
    return flask.jsonify(response)


#
# Entrypoint
#
if __name__ == '__main__':
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
