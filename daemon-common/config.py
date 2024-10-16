#!/usr/bin/env python3

# config.py - Utility functions for pvcnoded configuration parsing
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2024 Joshua M. Boniface <joshua@boniface.me>
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
import subprocess
import yaml

from socket import gethostname
from re import findall
from psutil import cpu_count
from ipaddress import ip_address, ip_network


class MalformedConfigurationError(Exception):
    """
    An except when parsing the PVC Node daemon configuration file
    """

    def __init__(self, error=None):
        self.msg = f"ERROR: Configuration file is malformed: {error}"

    def __str__(self):
        return str(self.msg)


def get_static_data():
    """
    Data that is obtained once at node startup for use later
    """
    staticdata = list()
    staticdata.append(str(cpu_count()))  # CPU count
    staticdata.append(
        subprocess.run(["uname", "-r"], stdout=subprocess.PIPE)
        .stdout.decode("ascii")
        .strip()
    )
    staticdata.append(
        subprocess.run(["uname", "-o"], stdout=subprocess.PIPE)
        .stdout.decode("ascii")
        .strip()
    )
    staticdata.append(
        subprocess.run(["uname", "-m"], stdout=subprocess.PIPE)
        .stdout.decode("ascii")
        .strip()
    )

    return staticdata


def get_configuration_path():
    try:
        _config_file = os.environ["PVC_CONFIG_FILE"]
        if not os.path.exists(_config_file):
            raise
        config_file = _config_file
    except Exception:
        print('ERROR: The "PVC_CONFIG_FILE" environment variable must be set.')
        os._exit(1)

    return config_file


def get_hostname():
    node_fqdn = gethostname()
    node_hostname = node_fqdn.split(".", 1)[0]
    node_domain = "".join(node_fqdn.split(".", 1)[1:])
    try:
        node_id = findall(r"\d+", node_hostname)[-1]
    except IndexError:
        node_id = 0

    return node_fqdn, node_hostname, node_domain, node_id


def validate_floating_ip(config, network):
    if network not in ["cluster", "storage", "upstream"]:
        return False, f'Specified network type "{network}" is not valid'

    floating_key = f"{network}_floating_ip"
    network_key = f"{network}_network"

    # Verify the network provided is valid
    try:
        network = ip_network(config[network_key])
    except Exception:
        return (
            False,
            f"Network address {config[network_key]} for {network_key} is not valid",
        )

    # Verify that the floating IP is valid (and in the network)
    try:
        floating_address = ip_address(config[floating_key].split("/")[0])
        if floating_address not in list(network.hosts()):
            raise
    except Exception:
        return (
            False,
            f"Floating address {config[floating_key]} for {floating_key} is not valid",
        )

    return True, ""


def get_parsed_configuration(config_file):
    print('Loading configuration from file "{}"'.format(config_file))

    with open(config_file, "r") as cfgfh:
        try:
            o_config = yaml.load(cfgfh, Loader=yaml.SafeLoader)
        except Exception as e:
            print(f"ERROR: Failed to parse configuration file: {e}")
            os._exit(1)

    config = dict()

    node_fqdn, node_hostname, node_domain, node_id = get_hostname()

    config_thisnode = {
        "node": node_hostname,
        "node_hostname": node_hostname,
        "node_fqdn": node_fqdn,
        "node_domain": node_domain,
        "node_id": node_id,
    }
    config = {**config, **config_thisnode}

    try:
        o_path = o_config["path"]
        config_path = {
            "plugin_directory": o_path.get(
                "plugin_directory", "/usr/share/pvc/plugins"
            ),
            "dynamic_directory": o_path["dynamic_directory"],
            "log_directory": o_path["system_log_directory"],
            "console_log_directory": o_path["console_log_directory"],
            "ceph_directory": o_path["ceph_directory"],
        }
        # Define our dynamic directory schema
        config_path["dnsmasq_dynamic_directory"] = (
            config_path["dynamic_directory"] + "/dnsmasq"
        )
        config_path["pdns_dynamic_directory"] = (
            config_path["dynamic_directory"] + "/pdns"
        )
        config_path["nft_dynamic_directory"] = config_path["dynamic_directory"] + "/nft"
        # Define our log directory schema
        config_path["dnsmasq_log_directory"] = config_path["log_directory"] + "/dnsmasq"
        config_path["pdns_log_directory"] = config_path["log_directory"] + "/pdns"
        config_path["nft_log_directory"] = config_path["log_directory"] + "/nft"
        config = {**config, **config_path}

        o_subsystem = o_config["subsystem"]
        config_subsystem = {
            "enable_hypervisor": o_subsystem.get("enable_hypervisor", True),
            "enable_networking": o_subsystem.get("enable_networking", True),
            "enable_storage": o_subsystem.get("enable_storage", True),
            "enable_worker": o_subsystem.get("enable_worker", True),
            "enable_api": o_subsystem.get("enable_api", True),
            "enable_prometheus": o_subsystem.get("enable_prometheus", True),
        }
        config = {**config, **config_subsystem}

        o_cluster = o_config["cluster"]
        config_cluster = {
            "cluster_name": o_cluster["name"],
            "all_nodes": o_cluster["all_nodes"],
            "coordinators": o_cluster["coordinator_nodes"],
        }
        config = {**config, **config_cluster}

        o_cluster_networks = o_cluster["networks"]
        for network_type in ["cluster", "storage", "upstream"]:
            o_cluster_networks_specific = o_cluster_networks[network_type]
            config_cluster_networks_specific = {
                f"{network_type}_domain": o_cluster_networks_specific["domain"],
                f"{network_type}_dev": o_cluster_networks_specific["device"],
                f"{network_type}_mtu": o_cluster_networks_specific["mtu"],
                f"{network_type}_network": o_cluster_networks_specific["ipv4"][
                    "network_address"
                ]
                + "/"
                + str(o_cluster_networks_specific["ipv4"]["netmask"]),
                f"{network_type}_floating_ip": o_cluster_networks_specific["ipv4"][
                    "floating_address"
                ]
                + "/"
                + str(o_cluster_networks_specific["ipv4"]["netmask"]),
                f"{network_type}_node_ip_selection": o_cluster_networks_specific[
                    "node_ip_selection"
                ],
            }

            if (
                o_cluster_networks_specific["ipv4"].get("gateway_address", None)
                is not None
            ):
                config[f"{network_type}_gateway"] = o_cluster_networks_specific["ipv4"][
                    "gateway_address"
                ]

            result, msg = validate_floating_ip(
                config_cluster_networks_specific, network_type
            )
            if not result:
                raise MalformedConfigurationError(msg)

            network = ip_network(
                config_cluster_networks_specific[f"{network_type}_network"]
            )

            if (
                config_cluster_networks_specific[f"{network_type}_node_ip_selection"]
                == "by-id"
            ):
                address_id = int(node_id) - 1
            else:
                # This roundabout solution ensures the given IP is in the subnet and is something valid
                address_id = [
                    idx
                    for idx, ip in enumerate(list(network.hosts()))
                    if str(ip)
                    == config_cluster_networks_specific[
                        f"{network_type}_node_ip_selection"
                    ]
                ][0]

            config_cluster_networks_specific[f"{network_type}_dev_ip"] = (
                f"{list(network.hosts())[address_id]}/{network.prefixlen}"
            )

            config = {**config, **config_cluster_networks_specific}

        o_database = o_config["database"]
        config_database = {
            "zookeeper_port": o_database["zookeeper"]["port"],
            "keydb_port": o_database["keydb"]["port"],
            "keydb_host": o_database["keydb"]["hostname"],
            "keydb_path": o_database["keydb"]["path"],
            "api_postgresql_port": o_database["postgres"]["port"],
            "api_postgresql_host": o_database["postgres"]["hostname"],
            "api_postgresql_dbname": o_database["postgres"]["credentials"]["api"][
                "database"
            ],
            "api_postgresql_user": o_database["postgres"]["credentials"]["api"][
                "username"
            ],
            "api_postgresql_password": o_database["postgres"]["credentials"]["api"][
                "password"
            ],
            "pdns_postgresql_port": o_database["postgres"]["port"],
            "pdns_postgresql_host": o_database["postgres"]["hostname"],
            "pdns_postgresql_dbname": o_database["postgres"]["credentials"]["dns"][
                "database"
            ],
            "pdns_postgresql_user": o_database["postgres"]["credentials"]["dns"][
                "username"
            ],
            "pdns_postgresql_password": o_database["postgres"]["credentials"]["dns"][
                "password"
            ],
        }
        config = {**config, **config_database}

        o_timer = o_config["timer"]
        config_timer = {
            "vm_shutdown_timeout": int(o_timer.get("vm_shutdown_timeout", 180)),
            "keepalive_interval": int(o_timer.get("keepalive_interval", 5)),
            "monitoring_interval": int(o_timer.get("monitoring_interval", 15)),
        }
        config = {**config, **config_timer}

        o_fencing = o_config["fencing"]
        config_fencing = {
            "disable_on_ipmi_failure": o_fencing["disable_on_ipmi_failure"],
            "fence_intervals": int(o_fencing["intervals"].get("fence_intervals", 6)),
            "suicide_intervals": int(o_fencing["intervals"].get("suicide_interval", 0)),
            "successful_fence": o_fencing["actions"].get("successful_fence", None),
            "failed_fence": o_fencing["actions"].get("failed_fence", None),
            "ipmi_hostname": o_fencing["ipmi"]["hostname"].format(node_id=node_id),
            "ipmi_username": o_fencing["ipmi"]["username"],
            "ipmi_password": o_fencing["ipmi"]["password"],
        }
        config = {**config, **config_fencing}

        o_migration = o_config["migration"]
        config_migration = {
            "migration_target_selector": o_migration.get("target_selector", "mem"),
        }
        config = {**config, **config_migration}

        o_logging = o_config["logging"]
        config_logging = {
            "debug": o_logging.get("debug_logging", False),
            "file_logging": o_logging.get("file_logging", False),
            "stdout_logging": o_logging.get("stdout_logging", False),
            "zookeeper_logging": o_logging.get("zookeeper_logging", False),
            "log_colours": o_logging.get("log_colours", False),
            "log_dates": o_logging.get("log_dates", False),
            "log_keepalives": o_logging.get("log_keepalives", False),
            "log_keepalive_cluster_details": o_logging.get(
                "log_cluster_details", False
            ),
            "log_monitoring_details": o_logging.get("log_monitoring_details", False),
            "console_log_lines": o_logging.get("console_log_lines", False),
            "node_log_lines": o_logging.get("node_log_lines", False),
        }
        config = {**config, **config_logging}

        o_guest_networking = o_config["guest_networking"]
        config_guest_networking = {
            "bridge_dev": o_guest_networking["bridge_device"],
            "bridge_mtu": o_guest_networking["bridge_mtu"],
            "enable_sriov": o_guest_networking.get("sriov_enable", False),
            "sriov_device": o_guest_networking.get("sriov_device", list()),
        }
        config = {**config, **config_guest_networking}

        o_ceph = o_config["ceph"]
        config_ceph = {
            "ceph_config_file": config["ceph_directory"]
            + "/"
            + o_ceph["ceph_config_file"],
            "ceph_admin_keyring": config["ceph_directory"]
            + "/"
            + o_ceph["ceph_keyring_file"],
            "ceph_monitor_port": o_ceph["monitor_port"],
            "ceph_secret_uuid": o_ceph["secret_uuid"],
            "storage_hosts": o_ceph.get("monitor_hosts", None),
        }
        config = {**config, **config_ceph}

        o_api = o_config["api"]

        o_api_listen = o_api["listen"]
        config_api_listen = {
            "api_listen_address": o_api_listen["address"],
            "api_listen_port": o_api_listen["port"],
        }
        config = {**config, **config_api_listen}

        o_api_authentication = o_api["authentication"]
        config_api_authentication = {
            "api_auth_enabled": o_api_authentication.get("enabled", False),
            "api_auth_secret_key": o_api_authentication.get("secret_key", ""),
            "api_auth_source": o_api_authentication.get("source", "token"),
        }
        config = {**config, **config_api_authentication}

        o_api_ssl = o_api["ssl"]
        config_api_ssl = {
            "api_ssl_enabled": o_api_ssl.get("enabled", False),
            "api_ssl_cert_file": o_api_ssl.get("certificate", None),
            "api_ssl_key_file": o_api_ssl.get("private_key", None),
        }
        config = {**config, **config_api_ssl}

        # Use coordinators as storage hosts if not explicitly specified
        # These are added as FQDNs in the storage domain
        if not config["storage_hosts"] or len(config["storage_hosts"]) < 1:
            config["storage_hosts"] = []
            for host in config["coordinators"]:
                config["storage_hosts"].append(f"{host}.{config['storage_domain']}")

        # Set up our token list if specified
        if config["api_auth_source"] == "token":
            config["api_auth_tokens"] = o_api["token"]
        else:
            if config["api_auth_enabled"]:
                print(
                    "WARNING: No authentication method provided; disabling API authentication."
                )
                config["api_auth_enabled"] = False

        # Add our node static data to the config
        config["static_data"] = get_static_data()

    except Exception as e:
        raise MalformedConfigurationError(e)

    return config


def get_configuration():
    """
    Get the configuration.
    """
    pvc_config_file = get_configuration_path()
    config = get_parsed_configuration(pvc_config_file)
    return config


def get_parsed_autobackup_configuration(config_file):
    """
    Load the configuration; this is the same main pvc.conf that the daemons read
    """
    print('Loading configuration from file "{}"'.format(config_file))

    with open(config_file, "r") as cfgfh:
        try:
            o_config = yaml.load(cfgfh, Loader=yaml.SafeLoader)
        except Exception as e:
            print(f"ERROR: Failed to parse configuration file: {e}")
            os._exit(1)

    config = dict()

    try:
        o_cluster = o_config["cluster"]
        config_cluster = {
            "cluster": o_cluster["name"],
            "autobackup_enabled": True,
        }
        config = {**config, **config_cluster}

        o_autobackup = o_config["autobackup"]
        if o_autobackup is None:
            config["autobackup_enabled"] = False
            return config

        config_autobackup = {
            "backup_root_path": o_autobackup["backup_root_path"],
            "backup_root_suffix": o_autobackup["backup_root_suffix"],
            "backup_tags": o_autobackup["backup_tags"],
            "backup_schedule": o_autobackup["backup_schedule"],
        }
        config = {**config, **config_autobackup}

        o_automount = o_autobackup["auto_mount"]
        config_automount = {
            "auto_mount_enabled": o_automount["enabled"],
        }
        config = {**config, **config_automount}
        if config["auto_mount_enabled"]:
            config["mount_cmds"] = list()
            for _mount_cmd in o_automount["mount_cmds"]:
                if "{backup_root_path}" in _mount_cmd:
                    _mount_cmd = _mount_cmd.format(
                        backup_root_path=config["backup_root_path"]
                    )
                config["mount_cmds"].append(_mount_cmd)
            config["unmount_cmds"] = list()
            for _unmount_cmd in o_automount["unmount_cmds"]:
                if "{backup_root_path}" in _unmount_cmd:
                    _unmount_cmd = _unmount_cmd.format(
                        backup_root_path=config["backup_root_path"]
                    )
                config["unmount_cmds"].append(_unmount_cmd)

    except Exception as e:
        raise MalformedConfigurationError(e)

    return config


def get_autobackup_configuration():
    """
    Get the configuration.
    """
    pvc_config_file = get_configuration_path()
    config = get_parsed_autobackup_configuration(pvc_config_file)
    return config


def validate_directories(config):
    if not os.path.exists(config["dynamic_directory"]):
        os.makedirs(config["dynamic_directory"])
        os.makedirs(config["dnsmasq_dynamic_directory"])
        os.makedirs(config["pdns_dynamic_directory"])
        os.makedirs(config["nft_dynamic_directory"])

    if not os.path.exists(config["log_directory"]):
        os.makedirs(config["log_directory"])
        os.makedirs(config["dnsmasq_log_directory"])
        os.makedirs(config["pdns_log_directory"])
        os.makedirs(config["nft_log_directory"])
