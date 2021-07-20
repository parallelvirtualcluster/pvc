#!/usr/bin/env python3

# Daemon.py - PVC HTTP API daemon
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2021 Joshua M. Boniface <joshua@boniface.me>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, version 3.
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

import os
import yaml

from distutils.util import strtobool as dustrtobool

# Daemon version
version = '0.9.30'

# API version
API_VERSION = 1.0


##########################################################
# Helper Functions
##########################################################

def strtobool(stringv):
    if stringv is None:
        return False
    if isinstance(stringv, bool):
        return bool(stringv)
    try:
        return bool(dustrtobool(stringv))
    except Exception:
        return False


##########################################################
# Configuration Parsing
##########################################################

# Parse the configuration file
try:
    pvcapid_config_file = os.environ['PVC_CONFIG_FILE']
except Exception:
    print('Error: The "PVC_CONFIG_FILE" environment variable must be set before starting pvcapid.')
    exit(1)

print('Loading configuration from file "{}"'.format(pvcapid_config_file))

# Read in the config
try:
    with open(pvcapid_config_file, 'r') as cfgfile:
        o_config = yaml.load(cfgfile, Loader=yaml.BaseLoader)
except Exception as e:
    print('ERROR: Failed to parse configuration file: {}'.format(e))
    exit(1)

try:
    # Create the config object
    config = {
        'debug': strtobool(o_config['pvc']['debug']),
        'coordinators': o_config['pvc']['coordinators'],
        'listen_address': o_config['pvc']['api']['listen_address'],
        'listen_port': int(o_config['pvc']['api']['listen_port']),
        'auth_enabled': strtobool(o_config['pvc']['api']['authentication']['enabled']),
        'auth_secret_key': o_config['pvc']['api']['authentication']['secret_key'],
        'auth_tokens': o_config['pvc']['api']['authentication']['tokens'],
        'ssl_enabled': strtobool(o_config['pvc']['api']['ssl']['enabled']),
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

except Exception as e:
    print('ERROR: Failed to load configuration: {}'.format(e))
    exit(1)


##########################################################
# Entrypoint
##########################################################

def entrypoint():
    import pvcapid.flaskapi as pvc_api  # noqa: E402

    if config['ssl_enabled']:
        context = (config['ssl_cert_file'], config['ssl_key_file'])
    else:
        context = None

    # Print our startup messages
    print('')
    print('|----------------------------------------------------------|')
    print('|                                                          |')
    print('|           ███████████ ▜█▙      ▟█▛ █████ █ █ █           |')
    print('|                    ██  ▜█▙    ▟█▛  ██                    |')
    print('|           ███████████   ▜█▙  ▟█▛   ██                    |')
    print('|           ██             ▜█▙▟█▛    ███████████           |')
    print('|                                                          |')
    print('|----------------------------------------------------------|')
    print('| Parallel Virtual Cluster API daemon v{0: <19} |'.format(version))
    print('| Debug: {0: <49} |'.format(str(config['debug'])))
    print('| API version: v{0: <42} |'.format(API_VERSION))
    print('| Listen: {0: <48} |'.format('{}:{}'.format(config['listen_address'], config['listen_port'])))
    print('| SSL: {0: <51} |'.format(str(config['ssl_enabled'])))
    print('| Authentication: {0: <40} |'.format(str(config['auth_enabled'])))
    print('|----------------------------------------------------------|')
    print('')

    pvc_api.app.run(config['listen_address'], config['listen_port'], threaded=True, ssl_context=context)
