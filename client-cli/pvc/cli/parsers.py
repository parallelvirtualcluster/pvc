#!/usr/bin/env python3

# parsers.py - PVC Click CLI data parser function library
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

from os import path
from re import sub

from pvc.cli.helpers import read_config_from_yaml, get_config

import pvc.lib.cluster


def cli_connection_list_parser(connections_config, show_keys_flag):
    """
    Parse connections_config into formatable data for cli_connection_list
    """

    connections_data = list()

    for connection, details in connections_config.items():
        if details.get("cfgfile", None) is not None:
            if path.isfile(details.get("cfgfile")):
                description, address, port, scheme, api_key = read_config_from_yaml(
                    details.get("cfgfile")
                )
            else:
                continue
            if not show_keys_flag and api_key is not None:
                api_key = sub(r"[a-z0-9]", "x", api_key)
            connections_data.append(
                {
                    "name": connection,
                    "description": description,
                    "address": address,
                    "port": port,
                    "scheme": scheme,
                    "api_key": api_key,
                }
            )
        else:
            if not show_keys_flag:
                details["api_key"] = sub(r"[a-z0-9]", "x", details["api_key"])
            connections_data.append(
                {
                    "name": connection,
                    "description": details["description"],
                    "address": details["host"],
                    "port": details["port"],
                    "scheme": details["scheme"],
                    "api_key": details["api_key"],
                }
            )

    # Return, ensuring local is always first
    return sorted(connections_data, key=lambda x: (x.get("name") != "local"))


def cli_connection_detail_parser(connections_config):
    """
    Parse connections_config into formatable data for cli_connection_detail
    """
    connections_data = list()
    for connection, details in connections_config.items():
        cluster_config = get_config(connections_config, connection=connection)
        if cluster_config.get("badcfg", False):
            continue
        # Connect to each API and gather cluster status
        retcode, retdata = pvc.lib.cluster.get_info(cluster_config)
        if retcode == 0:
            # Create dummy data of N/A for all fields
            connections_data.append(
                {
                    "name": cluster_config["connection"],
                    "description": cluster_config["description"],
                    "health": "N/A",
                    "maintenance": "N/A",
                    "primary_node": "N/A",
                    "pvc_version": "N/A",
                    "nodes": "N/A",
                    "vms": "N/A",
                    "networks": "N/A",
                    "osds": "N/A",
                    "pools": "N/A",
                    "volumes": "N/A",
                    "snapshots": "N/A",
                }
            )
        else:
            # Normalize data into nice formattable version
            connections_data.append(
                {
                    "name": cluster_config["connection"],
                    "description": cluster_config["description"],
                    "health": retdata.get("cluster_health", {}).get("health", "N/A"),
                    "maintenance": retdata.get("maintenance", "N/A"),
                    "primary_node": retdata.get("primary_node", "N/A"),
                    "pvc_version": retdata.get("pvc_version", "N/A"),
                    "nodes": retdata.get("nodes", {}).get("total", "N/A"),
                    "vms": retdata.get("vms", {}).get("total", "N/A"),
                    "networks": retdata.get("networks", "N/A"),
                    "osds": retdata.get("osds", {}).get("total", "N/A"),
                    "pools": retdata.get("pools", "N/A"),
                    "volumes": retdata.get("volumes", "N/A"),
                    "snapshots": retdata.get("snapshots", "N/A"),
                }
            )

    # Return, ensuring local is always first
    return sorted(connections_data, key=lambda x: (x.get("name") != "local"))
