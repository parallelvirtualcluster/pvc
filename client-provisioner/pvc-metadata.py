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
import sys
import uu
import distutils.util

import gevent.pywsgi

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

print('Starting PVC Provisioner Metadata API daemon')

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

# Get our listening address from the CLI
router_address = sys.argv[1]

# Try to connect to the database or fail
try:
    print('Verifying connectivity to database')
    conn, cur = pvc_provisioner.open_database(config)
    pvc_provisioner.close_database(conn, cur)
except Exception as e:
    print('{}'.format(e))
    exit(1)

api = flask.Flask(__name__)

if config['debug']:
    api.config['DEBUG'] = True

if config['auth_enabled']:
    api.config["SECRET_KEY"] = config['auth_secret_key']

print(api.name)

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

@api.route('/', methods=['GET'])
def api_root():
    return flask.jsonify({"message": "PVC Provisioner Metadata API version 1"}), 209

@api.route('/<version>/meta-data/', methods=['GET'])
def api_metadata_root(version):
    metadata = """instance-id"""
    return metadata, 200

@api.route('/<version>/meta-data/instance-id', methods=['GET'])
def api_metadata_instanceid(version):
#    router_address = flask.request.__dict__['environ']['SERVER_NAME']
    source_address = flask.request.__dict__['environ']['REMOTE_ADDR']
    vm_details = get_vm_details(source_address)
    instance_id = vm_details['uuid']
    return instance_id, 200

@api.route('/<version>/user-data', methods=['GET'])
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
    return flask.Response(userdata, mimetype='text/cloud-config')

#
# Entrypoint
#
if __name__ == '__main__':
    # Start main API
    if config['debug']:
        # Run in Flask standard mode
        api.run('169.254.169.254', 80)
    else:
        # Run the PYWSGI serve
        http_server = gevent.pywsgi.WSGIServer(
            ('10.200.0.1', 80),
            api
        )
    
        print('Starting PyWSGI server at {}:{}'.format('169.254.169.254', 80))
        http_server.serve_forever()
    
