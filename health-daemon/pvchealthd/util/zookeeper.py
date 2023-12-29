#!/usr/bin/env python3

# <Filename> - <Description>
# zookeeper.py - Utility functions for pvcnoded Zookeeper connections
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
##############################################################################

from daemon_lib.zkhandler import ZKHandler

import os
import time


def connect(logger, config):
    # Create an instance of the handler
    zkhandler = ZKHandler(config, logger)

    try:
        logger.out(
            "Connecting to Zookeeper on coordinator nodes {}".format(
                config["coordinators"]
            ),
            state="i",
        )
        # Start connection
        zkhandler.connect(persistent=True)
    except Exception as e:
        logger.out(
            "ERROR: Failed to connect to Zookeeper cluster: {}".format(e), state="e"
        )
        os._exit(1)

    logger.out("Validating Zookeeper schema", state="i")

    try:
        node_schema_version = int(
            zkhandler.read(("node.data.active_schema", config["node_hostname"]))
        )
    except Exception:
        node_schema_version = int(zkhandler.read("base.schema.version"))
        zkhandler.write(
            [
                (
                    ("node.data.active_schema", config["node_hostname"]),
                    node_schema_version,
                )
            ]
        )

    # Load in the current node schema version
    zkhandler.schema.load(node_schema_version)

    # Record the latest intalled schema version
    latest_schema_version = zkhandler.schema.find_latest()
    logger.out("Latest installed schema is {}".format(latest_schema_version), state="i")
    zkhandler.write(
        [(("node.data.latest_schema", config["node_hostname"]), latest_schema_version)]
    )

    # If we are the last node to get a schema update, fire the master update
    if latest_schema_version > node_schema_version:
        node_latest_schema_version = list()
        for node in zkhandler.children("base.node"):
            node_latest_schema_version.append(
                int(zkhandler.read(("node.data.latest_schema", node)))
            )

        # This is true if all elements of the latest schema version are identical to the latest version,
        # i.e. they have all had the latest schema installed and ready to load.
        if node_latest_schema_version.count(latest_schema_version) == len(
            node_latest_schema_version
        ):
            zkhandler.write([("base.schema.version", latest_schema_version)])

    return zkhandler, node_schema_version


def validate_schema(logger, zkhandler):
    # Validate our schema against the active version
    if not zkhandler.schema.validate(zkhandler, logger):
        logger.out("Found schema violations, applying", state="i")
        zkhandler.schema.apply(zkhandler)
    else:
        logger.out("Schema successfully validated", state="o")


def setup_node(logger, config, zkhandler):
    # Check if our node exists in Zookeeper, and create it if not
    if config["daemon_mode"] == "coordinator":
        init_routerstate = "secondary"
    else:
        init_routerstate = "client"

    if zkhandler.exists(("node", config["node_hostname"])):
        logger.out(
            f"Node is {logger.fmt_green}present{logger.fmt_end} in Zookeeper", state="i"
        )
        # Update static data just in case it's changed
        zkhandler.write(
            [
                (("node", config["node_hostname"]), config["daemon_mode"]),
                (("node.mode", config["node_hostname"]), config["daemon_mode"]),
                (("node.state.daemon", config["node_hostname"]), "init"),
                (("node.state.router", config["node_hostname"]), init_routerstate),
                (
                    ("node.data.static", config["node_hostname"]),
                    " ".join(config["static_data"]),
                ),
                (
                    ("node.data.pvc_version", config["node_hostname"]),
                    config["daemon_version"],
                ),
                (
                    ("node.ipmi.hostname", config["node_hostname"]),
                    config["ipmi_hostname"],
                ),
                (
                    ("node.ipmi.username", config["node_hostname"]),
                    config["ipmi_username"],
                ),
                (
                    ("node.ipmi.password", config["node_hostname"]),
                    config["ipmi_password"],
                ),
            ]
        )
    else:
        logger.out(
            f"Node is {logger.fmt_red}absent{logger.fmt_end} in Zookeeper; adding new node",
            state="i",
        )
        keepalive_time = int(time.time())
        zkhandler.write(
            [
                (("node", config["node_hostname"]), config["daemon_mode"]),
                (("node.keepalive", config["node_hostname"]), str(keepalive_time)),
                (("node.mode", config["node_hostname"]), config["daemon_mode"]),
                (("node.state.daemon", config["node_hostname"]), "init"),
                (("node.state.domain", config["node_hostname"]), "flushed"),
                (("node.state.router", config["node_hostname"]), init_routerstate),
                (
                    ("node.data.static", config["node_hostname"]),
                    " ".join(config["static_data"]),
                ),
                (
                    ("node.data.pvc_version", config["node_hostname"]),
                    config["daemon_version"],
                ),
                (
                    ("node.ipmi.hostname", config["node_hostname"]),
                    config["ipmi_hostname"],
                ),
                (
                    ("node.ipmi.username", config["node_hostname"]),
                    config["ipmi_username"],
                ),
                (
                    ("node.ipmi.password", config["node_hostname"]),
                    config["ipmi_password"],
                ),
                (("node.memory.total", config["node_hostname"]), "0"),
                (("node.memory.used", config["node_hostname"]), "0"),
                (("node.memory.free", config["node_hostname"]), "0"),
                (("node.memory.allocated", config["node_hostname"]), "0"),
                (("node.memory.provisioned", config["node_hostname"]), "0"),
                (("node.vcpu.allocated", config["node_hostname"]), "0"),
                (("node.cpu.load", config["node_hostname"]), "0.0"),
                (("node.running_domains", config["node_hostname"]), "0"),
                (("node.count.provisioned_domains", config["node_hostname"]), "0"),
                (("node.count.networks", config["node_hostname"]), "0"),
            ]
        )
