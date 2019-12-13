#!/usr/bin/env python3

# pvc-provisioner.py - PVC Provisioner API interface
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
import uu
import distutils.util
import threading
import time
import gevent.pywsgi

import celery as Celery

import provisioner_lib.provisioner as pvc_provisioner

import client_lib.common as pvc_common
import client_lib.vm as pvc_vm
import client_lib.network as pvc_network

# Parse the configuration file
try:
    pvc_config_file = os.environ['PVC_CONFIG_FILE']
except:
    print('Error: The "PVC_CONFIG_FILE" environment variable must be set before starting pvc-provisioner.')
    exit(1)

print('Starting PVC Provisioner daemon')

# Read in the config
try:
    with open(pvc_config_file, 'r') as cfgfile:
        o_config = yaml.load(cfgfile)
except Exception as e:
    print('Failed to parse configuration file: {}'.format(e))
    exit(1)

try:
    # Create the config object
    config = {
        'debug': o_config['pvc']['debug'],
        'coordinators': o_config['pvc']['coordinators'],
        'listen_address': o_config['pvc']['provisioner']['listen_address'],
        'listen_port': int(o_config['pvc']['provisioner']['listen_port']),
        'auth_enabled': o_config['pvc']['provisioner']['authentication']['enabled'],
        'auth_secret_key': o_config['pvc']['provisioner']['authentication']['secret_key'],
        'auth_tokens': o_config['pvc']['provisioner']['authentication']['tokens'],
        'ssl_enabled': o_config['pvc']['provisioner']['ssl']['enabled'],
        'ssl_key_file': o_config['pvc']['provisioner']['ssl']['key_file'],
        'ssl_cert_file': o_config['pvc']['provisioner']['ssl']['cert_file'],
        'database_host': o_config['pvc']['provisioner']['database']['host'],
        'database_port': int(o_config['pvc']['provisioner']['database']['port']),
        'database_name': o_config['pvc']['provisioner']['database']['name'],
        'database_user': o_config['pvc']['provisioner']['database']['user'],
        'database_password': o_config['pvc']['provisioner']['database']['pass'],
        'queue_host': o_config['pvc']['provisioner']['queue']['host'],
        'queue_port': o_config['pvc']['provisioner']['queue']['port'],
        'queue_path': o_config['pvc']['provisioner']['queue']['path'],
        'storage_hosts': o_config['pvc']['cluster']['storage_hosts'],
        'storage_domain': o_config['pvc']['cluster']['storage_domain'],
        'ceph_monitor_port': o_config['pvc']['cluster']['ceph_monitor_port'],
        'ceph_storage_secret_uuid': o_config['pvc']['cluster']['ceph_storage_secret_uuid']
    }

    if not config['storage_hosts']:
        config['storage_hosts'] = config['coordinators']

    # Set the config object in the pvcapi namespace
    pvc_provisioner.config = config
except Exception as e:
    print('{}'.format(e))
    exit(1)

# Try to connect to the database or fail
try:
    print('Verifying connectivity to database')
    conn, cur = pvc_provisioner.open_database(config)
    pvc_provisioner.close_database(conn, cur)
except Exception as e:
    print('{}'.format(e))
    exit(1)

# Primary provisioning API
prapi = flask.Flask(__name__)
prapi.config['CELERY_BROKER_URL'] = 'redis://{}:{}{}'.format(config['queue_host'], config['queue_port'], config['queue_path'])
prapi.config['CELERY_RESULT_BACKEND'] = 'redis://{}:{}{}'.format(config['queue_host'], config['queue_port'], config['queue_path'])

if config['debug']:
    prapi.config['DEBUG'] = True

if config['auth_enabled']:
    prapi.config["SECRET_KEY"] = config['auth_secret_key']

celery = Celery.Celery(prapi.name, broker=prapi.config['CELERY_BROKER_URL'])
celery.conf.update(prapi.config)

# Metadata API
mdapi = flask.Flask(__name__)

if config['debug']:
    mdapi.config['DEBUG'] = True

#
# Job functions
#

@celery.task(bind=True)
def create_vm(self, vm_name, profile_name):
    return pvc_provisioner.create_vm(self, vm_name, profile_name)

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
# Provisioning API
#

@prapi.route('/api/v1', methods=['GET'])
def api_root():
    return flask.jsonify({"message": "PVC Provisioner API version 1"}), 209

@prapi.route('/api/v1/auth/login', methods=['GET', 'POST'])
def api_auth_login():
    # Just return a 200 if auth is disabled
    if not config['auth_enabled']:
        return flask.jsonify({"message": "Authentication is disabled."}), 200

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
            return flask.jsonify({"message": "Authentication failed"}), 401

@prapi.route('/api/v1/auth/logout', methods=['GET', 'POST'])
def api_auth_logout():
    # Just return a 200 if auth is disabled
    if not config['auth_enabled']:
        return flask.jsonify({"message": "Authentication is disabled."}), 200

    # remove the username from the session if it's there
    flask.session.pop('token', None)
    return flask.redirect(flask.url_for('api_root'))

#
# Template endpoints
#
@prapi.route('/api/v1/template', methods=['GET'])
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

    return flask.jsonify(pvc_provisioner.template_list(limit)), 200

@prapi.route('/api/v1/template/system', methods=['GET', 'POST'])
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

        return flask.jsonify(pvc_provisioner.list_template_system(limit)), 200

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

        return pvc_provisioner.create_template_system(name, vcpu_count, vram_mb, serial, vnc, vnc_bind, node_limit, node_selector, start_with_node)

@prapi.route('/api/v1/template/system/<template>', methods=['GET', 'POST', 'DELETE'])
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
        return flask.jsonify(pvc_provisioner.list_template_system(template, is_fuzzy=False)), 200

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

        return pvc_provisioner.create_template_system(template, vcpu_count, vram_mb, serial, vnc, vnc_bind)

    if flask.request.method == 'DELETE':
        return pvc_provisioner.delete_template_system(template)

@prapi.route('/api/v1/template/network', methods=['GET', 'POST'])
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

        return flask.jsonify(pvc_provisioner.list_template_network(limit)), 200

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
           
        return pvc_provisioner.create_template_network(name, mac_template)

@prapi.route('/api/v1/template/network/<template>', methods=['GET', 'POST', 'DELETE'])
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
        return flask.jsonify(pvc_provisioner.list_template_network(template, is_fuzzy=False)), 200

    if flask.request.method == 'POST':
        if 'mac_template' in flask.request.values:
            mac_template = flask.request.values['mac_template']
        else:
            mac_template = None
           
        return pvc_provisioner.create_template_network(template, mac_template)

    if flask.request.method == 'DELETE':
        return pvc_provisioner.delete_template_network(template)

@prapi.route('/api/v1/template/network/<template>/net', methods=['GET', 'POST', 'DELETE'])
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
        return flask.jsonify(pvc_provisioner.list_template_network(template, is_fuzzy=False)), 200

    if flask.request.method == 'POST':
        if 'vni' in flask.request.values:
            vni = flask.request.values['vni']
        else:
            return flask.jsonify({"message": "A VNI must be specified."}), 400

        return pvc_provisioner.create_template_network_element(template, vni)

    if flask.request.method == 'DELETE':
        if 'vni' in flask.request.values:
            vni = flask.request.values['vni']
        else:
            return flask.jsonify({"message": "A VNI must be specified."}), 400

        return pvc_provisioner.delete_template_network_element(template, vni)
        
@prapi.route('/api/v1/template/network/<template>/net/<vni>', methods=['GET', 'POST', 'DELETE'])
@authenticator
def api_template_network_net_element(template, vni):
    """
    /template/network/<template>/net/<vni> - Manage network VNI <vni> in network provisioning template <template>.

    GET: Show details of network template <template>.

    POST: Add new network VNI <vni> to network template <template>.

    DELETE: Remove network VNI <vni> from network template <template>.
    """
    if flask.request.method == 'GET':
        networks = pvc_provisioner.list_template_network_vnis(template)
        for network in networks:
            if int(network['vni']) == int(vni):
                return flask.jsonify(network), 200
        return flask.jsonify({"message": "Found no network with VNI {} in network template {}".format(vni, template)}), 404


    if flask.request.method == 'POST':
        return pvc_provisioner.create_template_network_element(template, vni)

    if flask.request.method == 'DELETE':
        return pvc_provisioner.delete_template_network_element(template, vni)
        
@prapi.route('/api/v1/template/storage', methods=['GET', 'POST'])
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

        return flask.jsonify(pvc_provisioner.list_template_storage(limit)), 200

    if flask.request.method == 'POST':
        # Get name data
        if 'name' in flask.request.values:
            name = flask.request.values['name']
        else:
            return flask.jsonify({"message": "A name must be specified."}), 400

        return pvc_provisioner.create_template_storage(name)

@prapi.route('/api/v1/template/storage/<template>', methods=['GET', 'POST', 'DELETE'])
@authenticator
def api_template_storage_element(template):
    """
    /template/storage/<template> - Manage storage provisioning template <template>.

    GET: Show details of storage template.

    POST: Add new storage template.

    DELETE: Remove storage template.
    """
    if flask.request.method == 'GET':
        return flask.jsonify(pvc_provisioner.list_template_storage(template, is_fuzzy=False)), 200

    if flask.request.method == 'POST':
        return pvc_provisioner.create_template_storage(template)

    if flask.request.method == 'DELETE':
        return pvc_provisioner.delete_template_storage(template)

        if 'disk' in flask.request.values:
            disks = list()
            for disk in flask.request.values.getlist('disk'):
                disk_data = disk.split(',')
                disks.append(disk_data)
        else:
            return flask.jsonify({"message": "A disk must be specified."}), 400

@prapi.route('/api/v1/template/storage/<template>/disk', methods=['GET', 'POST', 'DELETE'])
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
        return flask.jsonify(pvc_provisioner.list_template_storage(template, is_fuzzy=False)), 200

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
           
        return pvc_provisioner.create_template_storage_element(template, pool, disk_id, disk_size, filesystem, filesystem_args, mountpoint)

    if flask.request.method == 'DELETE':
        if 'disk_id' in flask.request.values:
            disk_id = flask.request.values['disk_id']
        else:
            return flask.jsonify({"message": "A disk ID in sdX/vdX format must be specified."}), 400

        return pvc_provisioner.delete_template_storage_element(template, disk_id)
        
@prapi.route('/api/v1/template/storage/<template>/disk/<disk_id>', methods=['GET', 'POST', 'DELETE'])
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
        disks = pvc_provisioner.list_template_storage_disks(template)
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
           
        return pvc_provisioner.create_template_storage_element(template, pool, disk_id, disk_size, filesystem, filesystem_args, mountpoint)

    if flask.request.method == 'DELETE':
        return pvc_provisioner.delete_template_storage_element(template, disk_id)

@prapi.route('/api/v1/template/userdata', methods=['GET', 'POST', 'PUT'])
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

        return flask.jsonify(pvc_provisioner.list_template_userdata(limit)), 200

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

        return pvc_provisioner.create_template_userdata(name, data)

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

        return pvc_provisioner.update_template_userdata(name, data)

@prapi.route('/api/v1/template/userdata/<template>', methods=['GET', 'POST','PUT', 'DELETE'])
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
        return flask.jsonify(pvc_provisioner.list_template_userdata(template, is_fuzzy=False)), 200

    if flask.request.method == 'POST':
        # Get userdata data
        if 'data' in flask.request.values:
            data = flask.request.values['data']
        else:
            return flask.jsonify({"message": "A userdata object must be specified."}), 400

        return pvc_provisioner.create_template_userdata(template, data)

    if flask.request.method == 'PUT':
        # Get userdata data
        if 'data' in flask.request.values:
            data = flask.request.values['data']
        else:
            return flask.jsonify({"message": "A userdata object must be specified."}), 400

        return pvc_provisioner.update_template_userdata(template, data)

    if flask.request.method == 'DELETE':
        return pvc_provisioner.delete_template_userdata(template)

#
# Script endpoints
#
@prapi.route('/api/v1/script', methods=['GET', 'POST', 'PUT'])
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

        return flask.jsonify(pvc_provisioner.list_script(limit)), 200

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

        return pvc_provisioner.create_script(name, data)

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

        return pvc_provisioner.update_script(name, data)


@prapi.route('/api/v1/script/<script>', methods=['GET', 'POST', 'PUT', 'DELETE'])
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
        return flask.jsonify(pvc_provisioner.list_script(script, is_fuzzy=False)), 200

    if flask.request.method == 'POST':
        # Get script data
        if 'data' in flask.request.values:
            data = flask.request.values['data']
        else:
            return flask.jsonify({"message": "Script data must be specified."}), 400

        return pvc_provisioner.create_script(script, data)

    if flask.request.method == 'PUT':
        # Get script data
        if 'data' in flask.request.values:
            data = flask.request.values['data']
        else:
            return flask.jsonify({"message": "Script data must be specified."}), 400

        return pvc_provisioner.update_script(script, data)

    if flask.request.method == 'DELETE':
        return pvc_provisioner.delete_script(script)

#
# Profile endpoints
#
@prapi.route('/api/v1/profile', methods=['GET', 'POST'])
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

        return flask.jsonify(pvc_provisioner.list_profile(limit)), 200

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

        return pvc_provisioner.create_profile(name, system_template, network_template, storage_template, userdata_template, script, arguments)

@prapi.route('/api/v1/profile/<profile>', methods=['GET', 'POST', 'DELETE'])
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
        return flask.jsonify(pvc_provisioner.list_profile(profile, is_fuzzy=False)), 200

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

        return pvc_provisioner.create_profile(profile, system_template, network_template, storage_template, userdata_template, script)

    if flask.request.method == 'DELETE':
        return pvc_provisioner.delete_profile(profile)

#
# Provisioning endpoints
#
@prapi.route('/api/v1/create', methods=['POST'])
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

@prapi.route('/api/v1/status/<task_id>', methods=['GET'])
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
# Metadata API
#

# VM details function
def get_vm_details(source_address):
    # Start connection to Zookeeper
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    _discard, networks = pvc_network.get_list(zk_conn, None)

    # Figure out which server this is via the DHCP address
    host_information = dict()
    networks_managed = (x for x in networks if x['type'] == 'managed')
    for network in networks_managed:
        network_leases = pvc_network.getNetworkDHCPLeases(zk_conn, network['vni'])
        for network_lease in network_leases:
            information = pvc_network.getDHCPLeaseInformation(zk_conn, network['vni'], network_lease)
            try:
                if information['ip4_address'] == source_address:
                    host_information = information
            except:
                pass

    # Get our real information on the host; now we can start querying about it
    client_hostname = host_information['hostname']
    client_macaddr = host_information['mac_address']
    client_ipaddr = host_information['ip4_address']

    # Find the VM with that MAC address - we can't assume that the hostname is actually right
    _discard, vm_list = pvc_vm.get_list(zk_conn, None, None, None)
    vm_name = None
    vm_details = dict()
    for vm in vm_list:
        try:
            for network in vm['networks']:
                if network['mac'] == client_macaddr:
                    vm_name = vm['name']
                    vm_details = vm
        except:
            pass
    
    # Stop connection to Zookeeper
    pvc_common.stopZKConnection(zk_conn)

    return vm_details

@mdapi.route('/', methods=['GET'])
def api_root():
    return flask.jsonify({"message": "PVC Provisioner Metadata API version 1"}), 209

@mdapi.route('/<version>/meta-data/', methods=['GET'])
def api_metadata_root(version):
    metadata = """instance-id
name
profile
"""
    return metadata, 200

@mdapi.route('/<version>/meta-data/instance-id', methods=['GET'])
def api_metadata_instanceid(version):
    source_address = flask.request.__dict__['environ']['REMOTE_ADDR']
    vm_details = get_vm_details(source_address)
    instance_id = vm_details['uuid']
    return instance_id, 200

@mdapi.route('/<version>/meta-data/name', methods=['GET'])
def api_metadata_hostname(version):
    source_address = flask.request.__dict__['environ']['REMOTE_ADDR']
    vm_details = get_vm_details(source_address)
    vm_name = vm_details['name']
    return vm_name, 200

@mdapi.route('/<version>/meta-data/profile', methods=['GET'])
def api_metadata_profile(version):
    source_address = flask.request.__dict__['environ']['REMOTE_ADDR']
    vm_details = get_vm_details(source_address)
    vm_profile = vm_details['profile']
    return vm_profile, 200

@mdapi.route('/<version>/user-data', methods=['GET'])
def api_userdata(version):
    source_address = flask.request.__dict__['environ']['REMOTE_ADDR']
    vm_details = get_vm_details(source_address)
    vm_profile = vm_details['profile']
    print("Profile: {}".format(vm_profile))
    # Get profile details
    profile_details = pvc_provisioner.list_profile(vm_profile, is_fuzzy=False)[0]
    # Get the userdata
    userdata = pvc_provisioner.list_template_userdata(profile_details['userdata_template'])[0]['userdata']
    print(userdata)
    return flask.Response(userdata)

#
# Launch/threading functions
#
def debug_run_prapi():
    # Run provisioner API in Flask standard mode on listen_address and listen_port
    prapi.run(config['listen_address'], config['listen_port'], use_reloader=False)

def debug_run_mdapi():
    # Run metadata API on 169.254.169.254 and port 80
    mdapi.run('169.254.169.254', 80, use_reloader=False)

def launch_debug():
    # Launch Provisioning API
    threading.Thread(target=debug_run_prapi).start()
    time.sleep(1)
    # Launch Metadata API
    threading.Thread(target=debug_run_mdapi).start()

def production_run_api(http_server):
    http_server.serve_forever()

def launch_production():
    if config['ssl_enabled']:
        # Run the provisioning API WSGI server on listen_address and listen_port with SSL
        pr_http_server = gevent.pywsgi.WSGIServer(
            (config['listen_address'], config['listen_port']),
            prapi,
            keyfile=config['ssl_key_file'],
            certfile=config['ssl_cert_file']
        )
    else:
        # Run the provisioning API WSGI server on listen_address and listen_port without SSL
        pr_http_server = gevent.pywsgi.WSGIServer(
            (config['listen_address'], config['listen_port']),
            prapi
        )

    # Run metadata API on 169.254.169.254 and port 80 without SSL
    md_http_server = gevent.pywsgi.WSGIServer(
        ('169.254.169.254', 80),
        mdapi
    )

    # Launch Provisioning API
    print('Starting PyWSGI server for Provisioning API at {}:{} with SSL={}, Authentication={}'.format(config['listen_address'], config['listen_port'], config['ssl_enabled'], config['auth_enabled']))
    threading.Thread(target=production_run_api, args=(pr_http_server)).start()
    time.sleep(1)
    # Launch Metadata API
    print('Starting PyWSGI server for Metadata API at 169.254.169.254:80')
    threading.Thread(target=production_run_api, args=(md_http_server)).start()

#
# Entrypoint
#
if __name__ == '__main__':
    # Start main API
    if config['debug']:
        launch_debug()
    else:
        launch_production()
    
