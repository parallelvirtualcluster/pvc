#!/usr/bin/env python3

# config.py - Utility functions for pvcnoded configuration parsing
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

import daemon_lib.common as common

import os
import subprocess
import yaml

from socket import gethostname
from re import findall
from psutil import cpu_count
from ipaddress import ip_address, ip_network
from json import loads


class MalformedConfigurationError(Exception):
    """
    An except when parsing the PVC Node daemon configuration file
    """
    def __init__(self, error=None):
        self.msg = f'ERROR: Configuration file is malformed: {error}'

    def __str__(self):
        return str(self.msg)


def get_static_data():
    """
    Data that is obtained once at node startup for use later
    """
    staticdata = list()
    staticdata.append(str(cpu_count()))  # CPU count
    staticdata.append(
        subprocess.run(
            ['uname', '-r'], stdout=subprocess.PIPE
        ).stdout.decode('ascii').strip()
    )
    staticdata.append(
        subprocess.run(
            ['uname', '-o'], stdout=subprocess.PIPE
        ).stdout.decode('ascii').strip()
    )
    staticdata.append(
        subprocess.run(
            ['uname', '-m'], stdout=subprocess.PIPE
        ).stdout.decode('ascii').strip()
    )

    return staticdata


def get_configuration_path():
    try:
        return os.environ['PVCD_CONFIG_FILE']
    except KeyError:
        print('ERROR: The "PVCD_CONFIG_FILE" environment variable must be set.')
        os._exit(1)


def get_hostname():
    node_fqdn = gethostname()
    node_hostname = node_fqdn.split('.', 1)[0]
    node_domain = ''.join(node_fqdn.split('.', 1)[1:])
    try:
        node_id = findall(r'\d+', node_hostname)[-1]
    except IndexError:
        node_id = 0

    return node_fqdn, node_hostname, node_domain, node_id


def validate_floating_ip(config, network):
    if network not in ['cluster', 'storage', 'upstream']:
        return False, f'Specified network type "{network}" is not valid'

    floating_key = f'{network}_floating_ip'
    network_key = f'{network}_network'

    # Verify the network provided is valid
    try:
        network = ip_network(config[network_key])
    except Exception:
        return False, f'Network address {config[network_key]} for {network_key} is not valid'

    # Verify that the floating IP is valid (and in the network)
    try:
        floating_address = ip_address(config[floating_key].split('/')[0])
        if floating_address not in list(network.hosts()):
            raise
    except Exception:
        return False, f'Floating address {config[floating_key]} for {floating_key} is not valid'

    return True, ''


def get_configuration():
    """
    Parse the configuration of the node daemon.
    """
    pvcnoded_config_file = get_configuration_path()

    print('Loading configuration from file "{}"'.format(pvcnoded_config_file))

    with open(pvcnoded_config_file, 'r') as cfgfile:
        try:
            o_config = yaml.load(cfgfile, Loader=yaml.SafeLoader)
        except Exception as e:
            print('ERROR: Failed to parse configuration file: {}'.format(e))
            os._exit(1)

    node_fqdn, node_hostname, node_domain, node_id = get_hostname()

    # Create the configuration dictionary
    config = dict()

    # Get the initial base configuration
    try:
        o_base = o_config['pvc']
        o_cluster = o_config['pvc']['cluster']
    except Exception as e:
        raise MalformedConfigurationError(e)

    config_general = {
        'node':          o_base.get('node', node_hostname),
        'node_hostname': node_hostname,
        'node_fqdn':     node_fqdn,
        'node_domain':   node_domain,
        'node_id':       node_id,
        'coordinators':  o_cluster.get('coordinators', list()),
        'debug':         o_base.get('debug', False),
    }

    config = {**config, **config_general}

    # Get the functions configuration
    try:
        o_functions = o_config['pvc']['functions']
    except Exception as e:
        raise MalformedConfigurationError(e)

    config_functions = {
        'enable_hypervisor': o_functions.get('enable_hypervisor', False),
        'enable_networking': o_functions.get('enable_networking', False),
        'enable_storage':    o_functions.get('enable_storage', False),
        'enable_api':        o_functions.get('enable_api', False),
    }

    config = {**config, **config_functions}

    # Get the directory configuration
    try:
        o_directories = o_config['pvc']['system']['configuration']['directories']
    except Exception as e:
        raise MalformedConfigurationError(e)

    config_directories = {
        'dynamic_directory':     o_directories.get('dynamic_directory', None),
        'log_directory':         o_directories.get('log_directory', None),
        'console_log_directory': o_directories.get('console_log_directory', None),
    }

    # Define our dynamic directory schema
    config_directories['dnsmasq_dynamic_directory'] = config_directories['dynamic_directory'] + '/dnsmasq'
    config_directories['pdns_dynamic_directory'] = config_directories['dynamic_directory'] + '/pdns'
    config_directories['nft_dynamic_directory'] = config_directories['dynamic_directory'] + '/nft'

    # Define our log directory schema
    config_directories['dnsmasq_log_directory'] = config_directories['log_directory'] + '/dnsmasq'
    config_directories['pdns_log_directory'] = config_directories['log_directory'] + '/pdns'
    config_directories['nft_log_directory'] = config_directories['log_directory'] + '/nft'

    config = {**config, **config_directories}

    # Get the logging configuration
    try:
        o_logging = o_config['pvc']['system']['configuration']['logging']
    except Exception as e:
        raise MalformedConfigurationError(e)

    config_logging = {
        'file_logging':                  o_logging.get('file_logging', False),
        'stdout_logging':                o_logging.get('stdout_logging', False),
        'zookeeper_logging':             o_logging.get('zookeeper_logging', False),
        'log_colours':                   o_logging.get('log_colours', False),
        'log_dates':                     o_logging.get('log_dates', False),
        'log_keepalives':                o_logging.get('log_keepalives', False),
        'log_keepalive_cluster_details': o_logging.get('log_keepalive_cluster_details', False),
        'log_keepalive_storage_details': o_logging.get('log_keepalive_storage_details', False),
        'console_log_lines':             o_logging.get('console_log_lines', False),
        'node_log_lines':                o_logging.get('node_log_lines', False),
    }

    config = {**config, **config_logging}

    # Get the interval configuration
    try:
        o_intervals = o_config['pvc']['system']['intervals']
    except Exception as e:
        raise MalformedConfigurationError(e)

    config_intervals = {
        'vm_shutdown_timeout':  int(o_intervals.get('vm_shutdown_timeout', 60)),
        'keepalive_interval':   int(o_intervals.get('keepalive_interval', 5)),
        'fence_intervals':      int(o_intervals.get('fence_intervals', 6)),
        'suicide_intervals':    int(o_intervals.get('suicide_interval', 0)),
    }

    config = {**config, **config_intervals}

    # Get the fencing configuration
    try:
        o_fencing = o_config['pvc']['system']['fencing']
        o_fencing_actions = o_fencing['actions']
        o_fencing_ipmi = o_fencing['ipmi']
    except Exception as e:
        raise MalformedConfigurationError(e)

    config_fencing = {
        'successful_fence': o_fencing_actions.get('successful_fence', None),
        'failed_fence':     o_fencing_actions.get('failed_fence', None),
        'ipmi_hostname':    o_fencing_ipmi.get('host', f'{node_hostname}-lom.{node_domain}'),
        'ipmi_username':    o_fencing_ipmi.get('user', 'null'),
        'ipmi_password':    o_fencing_ipmi.get('pass', 'null'),
    }

    config = {**config, **config_fencing}

    # Get the migration configuration
    try:
        o_migration = o_config['pvc']['system']['migration']
    except Exception as e:
        raise MalformedConfigurationError(e)

    config_migration = {
        'migration_target_selector': o_migration.get('target_selector', 'mem'),
    }

    config = {**config, **config_migration}

    if config['enable_networking']:
        # Get the node networks configuration
        try:
            o_networks = o_config['pvc']['cluster']['networks']
            o_network_cluster = o_networks['cluster']
            o_network_storage = o_networks['storage']
            o_network_upstream = o_networks['upstream']
            o_sysnetworks = o_config['pvc']['system']['configuration']['networking']
            o_sysnetwork_cluster = o_sysnetworks['cluster']
            o_sysnetwork_storage = o_sysnetworks['storage']
            o_sysnetwork_upstream = o_sysnetworks['upstream']
        except Exception as e:
            raise MalformedConfigurationError(e)

        config_networks = {
            'cluster_domain':       o_network_cluster.get('domain', None),
            'cluster_network':      o_network_cluster.get('network', None),
            'cluster_floating_ip':  o_network_cluster.get('floating_ip', None),
            'cluster_dev':          o_sysnetwork_cluster.get('device', None),
            'cluster_mtu':          o_sysnetwork_cluster.get('mtu', None),
            'cluster_dev_ip':       o_sysnetwork_cluster.get('address', None),
            'storage_domain':       o_network_storage.get('domain', None),
            'storage_network':      o_network_storage.get('network', None),
            'storage_floating_ip':  o_network_storage.get('floating_ip', None),
            'storage_dev':          o_sysnetwork_storage.get('device', None),
            'storage_mtu':          o_sysnetwork_storage.get('mtu', None),
            'storage_dev_ip':       o_sysnetwork_storage.get('address', None),
            'upstream_domain':      o_network_upstream.get('domain', None),
            'upstream_network':     o_network_upstream.get('network', None),
            'upstream_floating_ip': o_network_upstream.get('floating_ip', None),
            'upstream_gateway':     o_network_upstream.get('gateway', None),
            'upstream_dev':         o_sysnetwork_upstream.get('device', None),
            'upstream_mtu':         o_sysnetwork_upstream.get('mtu', None),
            'upstream_dev_ip':      o_sysnetwork_upstream.get('address', None),
            'bridge_dev':           o_sysnetworks.get('bridge_device', None),
            'bridge_mtu':           o_sysnetworks.get('bridge_mtu', None),
            'enable_sriov':         o_sysnetworks.get('sriov_enable', False),
            'sriov_device':         o_sysnetworks.get('sriov_device', list())
        }

        config = {**config, **config_networks}

        if config_networks['bridge_mtu'] is None:
            # Read the current MTU of bridge_dev and set bridge_mtu to it; avoids weird resets
            retcode, stdout, stderr = common.run_os_command(f"ip -json link show dev {config_networks['bridge_dev']}")
            current_bridge_mtu = loads(stdout)[0]['mtu']
            print(f"Config key bridge_mtu not explicitly set; using live MTU {current_bridge_mtu} from {config_networks['bridge_dev']}")
            config_networks['bridge_mtu'] = current_bridge_mtu

        for network_type in ['cluster', 'storage', 'upstream']:
            result, msg = validate_floating_ip(config, network_type)
            if not result:
                raise MalformedConfigurationError(msg)

            address_key = '{}_dev_ip'.format(network_type)
            network_key = f'{network_type}_network'
            network = ip_network(config[network_key])
            # With autoselection of addresses, construct an IP from the relevant network
            if config[address_key] == 'by-id':
                # The NodeID starts at 1, but indexes start at 0
                address_id = int(config['node_id']) - 1
                # Grab the nth address from the network
                config[address_key] = '{}/{}'.format(list(network.hosts())[address_id], network.prefixlen)
            # Validate the provided IP instead
            else:
                try:
                    address = ip_address(config[address_key].split('/')[0])
                    if address not in list(network.hosts()):
                        raise
                except Exception:
                    raise MalformedConfigurationError(
                        f'IP address {config[address_key]} for {address_key} is not valid'
                    )

        # Get the PowerDNS aggregator database configuration
        try:
            o_pdnsdb = o_config['pvc']['coordinator']['dns']['database']
        except Exception as e:
            raise MalformedConfigurationError(e)

        config_pdnsdb = {
            'pdns_postgresql_host':     o_pdnsdb.get('host', None),
            'pdns_postgresql_port':     o_pdnsdb.get('port', None),
            'pdns_postgresql_dbname':   o_pdnsdb.get('name', None),
            'pdns_postgresql_user':     o_pdnsdb.get('user', None),
            'pdns_postgresql_password': o_pdnsdb.get('pass', None),
        }

        config = {**config, **config_pdnsdb}

        # Get the Cloud-Init Metadata database configuration
        try:
            o_metadatadb = o_config['pvc']['coordinator']['metadata']['database']
        except Exception as e:
            raise MalformedConfigurationError(e)

        config_metadatadb = {
            'metadata_postgresql_host':     o_metadatadb.get('host', None),
            'metadata_postgresql_port':     o_metadatadb.get('port', None),
            'metadata_postgresql_dbname':   o_metadatadb.get('name', None),
            'metadata_postgresql_user':     o_metadatadb.get('user', None),
            'metadata_postgresql_password': o_metadatadb.get('pass', None),
        }

        config = {**config, **config_metadatadb}

    if config['enable_storage']:
        # Get the storage configuration
        try:
            o_storage = o_config['pvc']['system']['configuration']['storage']
        except Exception as e:
            raise MalformedConfigurationError(e)

        config_storage = {
            'ceph_config_file':   o_storage.get('ceph_config_file', None),
            'ceph_admin_keyring': o_storage.get('ceph_admin_keyring', None),
        }

        config = {**config, **config_storage}

        # Add our node static data to the config
        config['static_data'] = get_static_data()

    return config


def validate_directories(config):
    if not os.path.exists(config['dynamic_directory']):
        os.makedirs(config['dynamic_directory'])
        os.makedirs(config['dnsmasq_dynamic_directory'])
        os.makedirs(config['pdns_dynamic_directory'])
        os.makedirs(config['nft_dynamic_directory'])

    if not os.path.exists(config['log_directory']):
        os.makedirs(config['log_directory'])
        os.makedirs(config['dnsmasq_log_directory'])
        os.makedirs(config['pdns_log_directory'])
        os.makedirs(config['nft_log_directory'])
