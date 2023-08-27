#!/usr/bin/env python3

# Daemon.py - PVC Node daemon main entrypoing
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2022 Joshua M. Boniface <joshua@boniface.me>
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

import pvcnoded.util.keepalive
import pvcnoded.util.config
import pvcnoded.util.fencing
import pvcnoded.util.networking
import pvcnoded.util.services
import pvcnoded.util.libvirt
import pvcnoded.util.zookeeper

import pvcnoded.objects.MonitoringInstance as MonitoringInstance
import pvcnoded.objects.DNSAggregatorInstance as DNSAggregatorInstance
import pvcnoded.objects.MetadataAPIInstance as MetadataAPIInstance
import pvcnoded.objects.VMInstance as VMInstance
import pvcnoded.objects.NodeInstance as NodeInstance
import pvcnoded.objects.VXNetworkInstance as VXNetworkInstance
import pvcnoded.objects.SRIOVVFInstance as SRIOVVFInstance
import pvcnoded.objects.CephInstance as CephInstance

import daemon_lib.log as log
import daemon_lib.common as common

from time import sleep
from distutils.util import strtobool

import os
import sys
import signal
import re
import json

# Daemon version
version = "0.9.66"


##########################################################
# Entrypoint
##########################################################


def entrypoint():
    keepalive_timer = None
    monitoring_instance = None

    # Get our configuration
    config = pvcnoded.util.config.get_configuration()
    config["pvcnoded_version"] = version

    # Set some useful booleans for later (fewer characters)
    debug = config["debug"]
    if debug:
        print("DEBUG MODE ENABLED")

    # Create and validate our directories
    pvcnoded.util.config.validate_directories(config)

    # Set up the logger instance
    logger = log.Logger(config)

    # Print our startup message
    logger.out("")
    logger.out("|----------------------------------------------------------|")
    logger.out("|                                                          |")
    logger.out("|           ███████████ ▜█▙      ▟█▛ █████ █ █ █           |")
    logger.out("|                    ██  ▜█▙    ▟█▛  ██                    |")
    logger.out("|           ███████████   ▜█▙  ▟█▛   ██                    |")
    logger.out("|           ██             ▜█▙▟█▛    ███████████           |")
    logger.out("|                                                          |")
    logger.out("|----------------------------------------------------------|")
    logger.out("| Parallel Virtual Cluster node daemon v{0: <18} |".format(version))
    logger.out("| Debug: {0: <49} |".format(str(config["debug"])))
    logger.out("| FQDN: {0: <50} |".format(config["node_fqdn"]))
    logger.out("| Host: {0: <50} |".format(config["node_hostname"]))
    logger.out("| ID: {0: <52} |".format(config["node_id"]))
    logger.out("| IPMI hostname: {0: <41} |".format(config["ipmi_hostname"]))
    logger.out("| Machine details:                                         |")
    logger.out("|   CPUs: {0: <48} |".format(config["static_data"][0]))
    logger.out("|   Arch: {0: <48} |".format(config["static_data"][3]))
    logger.out("|   OS: {0: <50} |".format(config["static_data"][2]))
    logger.out("|   Kernel: {0: <46} |".format(config["static_data"][1]))
    logger.out("|----------------------------------------------------------|")
    logger.out("")
    logger.out(f'Starting pvcnoded on host {config["node_fqdn"]}', state="s")

    if config["enable_networking"]:
        if config["enable_sriov"]:
            # Set up SR-IOV devices
            pvcnoded.util.networking.setup_sriov(logger, config)

        # Set up our interfaces
        pvcnoded.util.networking.setup_interfaces(logger, config)

    # Get list of coordinator nodes
    coordinator_nodes = config["coordinators"]

    if config["node_hostname"] in coordinator_nodes:
        # We are indeed a coordinator node
        config["daemon_mode"] = "coordinator"
        logger.out(
            f"This node is a {logger.fmt_blue}coordinator{logger.fmt_end}", state="i"
        )
    else:
        # We are a hypervisor node
        config["daemon_mode"] = "hypervisor"
        logger.out(
            f"This node is a {logger.fmt_cyan}hypervisor{logger.fmt_end}", state="i"
        )

    pvcnoded.util.services.start_system_services(logger, config)

    # Connect to Zookeeper and return our handler and current schema version
    zkhandler, node_schema_version = pvcnoded.util.zookeeper.connect(logger, config)

    # Watch for a global schema update and fire
    # This will only change by the API when triggered after seeing all nodes can update
    @zkhandler.zk_conn.DataWatch(zkhandler.schema.path("base.schema.version"))
    def update_schema(new_schema_version, stat, event=""):
        nonlocal zkhandler, keepalive_timer, node_schema_version

        try:
            new_schema_version = int(new_schema_version.decode("ascii"))
        except Exception:
            new_schema_version = 0

        if new_schema_version == node_schema_version:
            return True

        logger.out("Hot update of schema version started", state="s")
        logger.out(
            f"Current version: {node_schema_version,}  New version: {new_schema_version}",
            state="s",
        )

        # Prevent any keepalive updates while this happens
        if keepalive_timer is not None:
            pvcnoded.util.keepalive.stop_keepalive_timer(logger, keepalive_timer)
            sleep(1)

        # Perform the migration (primary only)
        if zkhandler.read("base.config.primary_node") == config["node_hostname"]:
            logger.out("Primary node acquiring exclusive lock", state="s")
            # Wait for things to settle
            sleep(0.5)
            # Acquire a write lock on the root key
            with zkhandler.exclusivelock("base.schema.version"):
                # Perform the schema migration tasks
                logger.out("Performing schema update", state="s")
                if new_schema_version > node_schema_version:
                    zkhandler.schema.migrate(zkhandler, new_schema_version)
                if new_schema_version < node_schema_version:
                    zkhandler.schema.rollback(zkhandler, new_schema_version)
        # Wait for the exclusive lock to be lifted
        else:
            logger.out("Non-primary node acquiring read lock", state="s")
            # Wait for things to settle
            sleep(1)
            # Wait for a read lock
            lock = zkhandler.readlock("base.schema.version")
            lock.acquire()
            # Wait a bit more for the primary to return to normal
            sleep(1)

        # Update the local schema version
        logger.out("Updating node target schema version", state="s")
        zkhandler.write(
            [(("node.data.active_schema", config["node_hostname"]), new_schema_version)]
        )
        node_schema_version = new_schema_version

        # Restart the API daemons if applicable
        logger.out("Restarting services", state="s")
        common.run_os_command("systemctl restart pvcapid-worker.service")
        if zkhandler.read("base.config.primary_node") == config["node_hostname"]:
            common.run_os_command("systemctl restart pvcapid.service")

        # Restart ourselves with the new schema
        logger.out("Reloading node daemon", state="s")
        try:
            zkhandler.disconnect(persistent=True)
            del zkhandler
        except Exception:
            pass
        os.execv(sys.argv[0], sys.argv)

    # Validate the schema
    pvcnoded.util.zookeeper.validate_schema(logger, zkhandler)

    # Define a cleanup function
    def cleanup(failure=False):
        nonlocal logger, zkhandler, keepalive_timer, d_domain, monitoring_instance

        logger.out("Terminating pvcnoded and cleaning up", state="s")

        # Set shutdown state in Zookeeper
        zkhandler.write([(("node.state.daemon", config["node_hostname"]), "shutdown")])

        # Waiting for any flushes to complete
        logger.out("Waiting for any active flushes", state="s")
        try:
            if this_node is not None:
                while this_node.flush_thread is not None:
                    sleep(0.5)
        except Exception:
            # We really don't care here, just proceed
            pass

        # Stop console logging on all VMs
        logger.out("Stopping domain console watchers", state="s")
        try:
            if d_domain is not None:
                for domain in d_domain:
                    if d_domain[domain].getnode() == config["node_hostname"]:
                        d_domain[domain].console_log_instance.stop()
        except Exception:
            pass

        # Force into secondary coordinator state if needed
        try:
            if this_node.router_state == "primary" and len(d_node) > 1:
                zkhandler.write([("base.config.primary_node", "none")])
                logger.out("Waiting for primary migration", state="s")
                timeout = 240
                count = 0
                while this_node.router_state != "secondary" and count < timeout:
                    sleep(0.5)
                    count += 1
        except Exception:
            pass

        # Stop keepalive thread
        try:
            pvcnoded.util.keepalive.stop_keepalive_timer(logger, keepalive_timer)

            logger.out("Performing final keepalive update", state="s")
            pvcnoded.util.keepalive.node_keepalive(logger, config, zkhandler, this_node)
        except Exception:
            pass

        # Clean up any monitoring plugins that have cleanup
        try:
            logger.out("Performing monitoring plugin cleanup", state="s")
            monitoring_instance.run_cleanups()
        except Exception:
            pass

        # Set stop state in Zookeeper
        zkhandler.write([(("node.state.daemon", config["node_hostname"]), "stop")])

        # Forcibly terminate dnsmasq because it gets stuck sometimes
        common.run_os_command("killall dnsmasq")

        # Close the Zookeeper connection
        try:
            zkhandler.disconnect(persistent=True)
            del zkhandler
        except Exception:
            pass

        logger.out("Terminated pvc daemon", state="s")
        logger.terminate()

        if failure:
            retcode = 1
        else:
            retcode = 0

        os._exit(retcode)

    # Termination function
    def term(signum="", frame=""):
        cleanup(failure=False)

    # Hangup (logrotate) function
    def hup(signum="", frame=""):
        if config["file_logging"]:
            logger.hup()

    # Handle signals gracefully
    signal.signal(signal.SIGTERM, term)
    signal.signal(signal.SIGINT, term)
    signal.signal(signal.SIGQUIT, term)
    signal.signal(signal.SIGHUP, hup)

    # Set up this node in Zookeeper
    pvcnoded.util.zookeeper.setup_node(logger, config, zkhandler)

    # Check that the primary node key exists and create it with us as primary if not
    try:
        current_primary = zkhandler.read("base.config.primary_node")
    except Exception:
        current_primary = "none"

    if current_primary and current_primary != "none":
        logger.out(
            f"Current primary node is {logger.fmt_blue}{current_primary}{logger.fmt_end}",
            state="i",
        )
    else:
        if config["daemon_mode"] == "coordinator":
            logger.out("No primary node found; setting us as primary", state="i")
            zkhandler.write([("base.config.primary_node", config["node_hostname"])])

    # Ensure that IPMI is reachable and working
    if not pvcnoded.util.fencing.verify_ipmi(
        config["ipmi_hostname"], config["ipmi_username"], config["ipmi_password"]
    ):
        logger.out(
            "Our IPMI is not reachable; fencing of this node will likely fail",
            state="w",
        )

    # Validate libvirt
    if not pvcnoded.util.libvirt.validate_libvirtd(logger, config):
        cleanup(failure=True)

    # Set up NFT
    pvcnoded.util.networking.create_nft_configuration(logger, config)

    # Create our object dictionaries
    logger.out("Setting up objects", state="s")

    d_node = dict()
    node_list = list()
    d_network = dict()
    network_list = list()
    sriov_pf_list = list()
    d_sriov_vf = dict()
    sriov_vf_list = list()
    d_domain = dict()
    domain_list = list()
    d_osd = dict()
    osd_list = list()
    d_pool = dict()
    pool_list = list()
    d_volume = dict()
    volume_list = dict()

    if config["enable_networking"] and config["daemon_mode"] == "coordinator":
        # Create an instance of the DNS Aggregator and Metadata API if we're a coordinator
        dns_aggregator = DNSAggregatorInstance.DNSAggregatorInstance(config, logger)
        metadata_api = MetadataAPIInstance.MetadataAPIInstance(
            zkhandler, config, logger
        )
    else:
        dns_aggregator = None
        metadata_api = None

    #
    # Zookeeper watchers for objects
    #

    # Node objects
    @zkhandler.zk_conn.ChildrenWatch(zkhandler.schema.path("base.node"))
    def set_nodes(new_node_list):
        nonlocal d_node, node_list

        # Add missing nodes to list
        for node in [node for node in new_node_list if node not in node_list]:
            d_node[node] = NodeInstance.NodeInstance(
                node,
                config["node_hostname"],
                zkhandler,
                config,
                logger,
                d_node,
                d_network,
                d_domain,
                dns_aggregator,
                metadata_api,
            )

        # Remove deleted nodes from list
        for node in [node for node in node_list if node not in new_node_list]:
            del d_node[node]

        node_list = new_node_list
        logger.out(
            f'{logger.fmt_blue}Node list:{logger.fmt_end} {" ".join(node_list)}',
            state="i",
        )

        # Update node objects lists
        for node in d_node:
            d_node[node].update_node_list(d_node)

    # Create helpful alias for this node
    this_node = d_node[config["node_hostname"]]

    # Maintenance status
    @zkhandler.zk_conn.DataWatch(zkhandler.schema.path("base.config.maintenance"))
    def update_maintenance(_maintenance, stat):
        try:
            maintenance = bool(strtobool(_maintenance.decode("ascii")))
        except Exception:
            maintenance = False

        this_node.maintenance = maintenance

    # Primary node
    @zkhandler.zk_conn.DataWatch(zkhandler.schema.path("base.config.primary_node"))
    def update_primary_node(new_primary, stat, event=""):
        try:
            new_primary = new_primary.decode("ascii")
        except AttributeError:
            new_primary = "none"
        key_version = stat.version

        # TODO: Move this to the Node structure
        if new_primary != this_node.primary_node:
            if config["daemon_mode"] == "coordinator":
                # We're a coordinator and there's no primary
                if new_primary == "none":
                    if (
                        this_node.daemon_state == "run"
                        and this_node.router_state
                        not in ["primary", "takeover", "relinquish"]
                    ):
                        logger.out(
                            "Contending for primary coordinator state", state="i"
                        )
                        # Acquire an exclusive lock on the primary_node key
                        primary_lock = zkhandler.exclusivelock(
                            "base.config.primary_node"
                        )
                        try:
                            # This lock times out after 0.4s, which is 0.1s less than the pre-takeover
                            # timeout beow. This ensures a primary takeover will not deadlock against
                            # a node which has failed the contention
                            primary_lock.acquire(timeout=0.4)
                            # Ensure that when we get the lock the versions are still consistent and
                            # that another node hasn't already acquired the primary state (maybe we're
                            # extremely slow to respond)
                            if (
                                key_version
                                == zkhandler.zk_conn.get(
                                    zkhandler.schema.path("base.config.primary_node")
                                )[1].version
                            ):
                                # Set the primary to us
                                logger.out(
                                    "Acquiring primary coordinator state", state="o"
                                )
                                zkhandler.write(
                                    [
                                        (
                                            "base.config.primary_node",
                                            config["node_hostname"],
                                        )
                                    ]
                                )
                            # Cleanly release the lock
                            primary_lock.release()
                        # We timed out acquiring a lock, or failed to write, which means we failed the
                        # contention and should just log that
                        except Exception:
                            logger.out(
                                "Timed out contending for primary coordinator state",
                                state="i",
                            )
                elif new_primary == config["node_hostname"]:
                    if this_node.router_state == "secondary":
                        # Wait for 0.5s to ensure other contentions time out, then take over
                        sleep(0.5)
                        zkhandler.write(
                            [
                                (
                                    ("node.state.router", config["node_hostname"]),
                                    "takeover",
                                )
                            ]
                        )
                else:
                    if this_node.router_state == "primary":
                        # Wait for 0.5s to ensure other contentions time out, then relinquish
                        sleep(0.5)
                        zkhandler.write(
                            [
                                (
                                    ("node.state.router", config["node_hostname"]),
                                    "relinquish",
                                )
                            ]
                        )
            else:
                zkhandler.write(
                    [(("node.state.router", config["node_hostname"]), "client")]
                )

            # TODO: Turn this into a function like the others for clarity
            for node in d_node:
                d_node[node].primary_node = new_primary

    if config["enable_networking"]:
        # Network objects
        @zkhandler.zk_conn.ChildrenWatch(zkhandler.schema.path("base.network"))
        def update_networks(new_network_list):
            nonlocal network_list, d_network

            # Add any missing networks to the list
            for network in [
                network for network in new_network_list if network not in network_list
            ]:
                d_network[network] = VXNetworkInstance.VXNetworkInstance(
                    network, zkhandler, config, logger, this_node, dns_aggregator
                )
                # TODO: Move this to the Network structure
                if (
                    config["daemon_mode"] == "coordinator"
                    and d_network[network].nettype == "managed"
                ):
                    try:
                        dns_aggregator.add_network(d_network[network])
                    except Exception as e:
                        logger.out(
                            f"Failed to create DNS Aggregator for network {network}: {e}",
                            state="w",
                        )
                # Start primary functionality
                if (
                    this_node.router_state == "primary"
                    and d_network[network].nettype == "managed"
                ):
                    d_network[network].createGateways()
                    d_network[network].startDHCPServer()

            # Remove any missing networks from the list
            for network in [
                network for network in network_list if network not in new_network_list
            ]:
                # TODO: Move this to the Network structure
                if d_network[network].nettype == "managed":
                    # Stop primary functionality
                    if this_node.router_state == "primary":
                        d_network[network].stopDHCPServer()
                        d_network[network].removeGateways()
                        dns_aggregator.remove_network(d_network[network])
                    # Stop firewalling
                    d_network[network].removeFirewall()
                # Delete the network
                d_network[network].removeNetwork()
                del d_network[network]

            # Update the new list
            network_list = new_network_list
            logger.out(
                f'{logger.fmt_blue}Network list:{logger.fmt_end} {" ".join(network_list)}',
                state="i",
            )

            # Update node objects list
            for node in d_node:
                d_node[node].update_network_list(d_network)

        # Add the SR-IOV PFs and VFs to Zookeeper
        # These do not behave like the objects; they are not dynamic (the API cannot change them), and they
        # exist for the lifetime of this Node instance. The objects are set here in Zookeeper on a per-node
        # basis, under the Node configuration tree.
        # MIGRATION: The schema.schema.get ensures that the current active Schema contains the required keys
        if (
            config["enable_sriov"]
            and zkhandler.schema.schema.get("sriov_pf", None) is not None
        ):
            vf_list = list()
            for device in config["sriov_device"]:
                pf = device["phy"]
                vfcount = device["vfcount"]
                if device.get("mtu", None) is None:
                    mtu = 1500
                else:
                    mtu = device["mtu"]

                # Create the PF device in Zookeeper
                zkhandler.write(
                    [
                        (
                            ("node.sriov.pf", config["node_hostname"], "sriov_pf", pf),
                            "",
                        ),
                        (
                            (
                                "node.sriov.pf",
                                config["node_hostname"],
                                "sriov_pf.mtu",
                                pf,
                            ),
                            mtu,
                        ),
                        (
                            (
                                "node.sriov.pf",
                                config["node_hostname"],
                                "sriov_pf.vfcount",
                                pf,
                            ),
                            vfcount,
                        ),
                    ]
                )
                # Append the device to the list of PFs
                sriov_pf_list.append(pf)

                # Get the list of VFs from `ip link show`
                vf_list = json.loads(
                    common.run_os_command(f"ip --json link show {pf}")[1]
                )[0].get("vfinfo_list", [])
                for vf in vf_list:
                    # {
                    #   'vf': 3,
                    #   'link_type': 'ether',
                    #   'address': '00:00:00:00:00:00',
                    #   'broadcast': 'ff:ff:ff:ff:ff:ff',
                    #   'vlan_list': [{'vlan': 101, 'qos': 2}],
                    #   'rate': {'max_tx': 0, 'min_tx': 0},
                    #   'spoofchk': True,
                    #   'link_state': 'auto',
                    #   'trust': False,
                    #   'query_rss_en': False
                    # }
                    vfphy = f'{pf}v{vf["vf"]}'

                    # Get the PCIe bus information
                    dev_pcie_path = None
                    try:
                        with open(f"/sys/class/net/{vfphy}/device/uevent") as vfh:
                            dev_uevent = vfh.readlines()
                        for line in dev_uevent:
                            if re.match(r"^PCI_SLOT_NAME=.*", line):
                                dev_pcie_path = line.rstrip().split("=")[-1]
                    except FileNotFoundError:
                        # Something must already be using the PCIe device
                        pass

                    # Add the VF to Zookeeper if it does not yet exist
                    if not zkhandler.exists(
                        ("node.sriov.vf", config["node_hostname"], "sriov_vf", vfphy)
                    ):
                        if dev_pcie_path is not None:
                            pcie_domain, pcie_bus, pcie_slot, pcie_function = re.split(
                                r":|\.", dev_pcie_path
                            )
                        else:
                            # We can't add the device - for some reason we can't get any information on its PCIe bus path,
                            # so just ignore this one, and continue.
                            # This shouldn't happen under any real circumstances, unless the admin tries to attach a non-existent
                            # VF to a VM manually, then goes ahead and adds that VF to the system with the VM running.
                            continue

                        zkhandler.write(
                            [
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf",
                                        vfphy,
                                    ),
                                    "",
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.pf",
                                        vfphy,
                                    ),
                                    pf,
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.mtu",
                                        vfphy,
                                    ),
                                    mtu,
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.mac",
                                        vfphy,
                                    ),
                                    vf["address"],
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.phy_mac",
                                        vfphy,
                                    ),
                                    vf["address"],
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.config",
                                        vfphy,
                                    ),
                                    "",
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.config.vlan_id",
                                        vfphy,
                                    ),
                                    vf["vlan_list"][0].get("vlan", "0"),
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.config.vlan_qos",
                                        vfphy,
                                    ),
                                    vf["vlan_list"][0].get("qos", "0"),
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.config.tx_rate_min",
                                        vfphy,
                                    ),
                                    vf["rate"]["min_tx"],
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.config.tx_rate_max",
                                        vfphy,
                                    ),
                                    vf["rate"]["max_tx"],
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.config.spoof_check",
                                        vfphy,
                                    ),
                                    vf["spoofchk"],
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.config.link_state",
                                        vfphy,
                                    ),
                                    vf["link_state"],
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.config.trust",
                                        vfphy,
                                    ),
                                    vf["trust"],
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.config.query_rss",
                                        vfphy,
                                    ),
                                    vf["query_rss_en"],
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.pci",
                                        vfphy,
                                    ),
                                    "",
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.pci.domain",
                                        vfphy,
                                    ),
                                    pcie_domain,
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.pci.bus",
                                        vfphy,
                                    ),
                                    pcie_bus,
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.pci.slot",
                                        vfphy,
                                    ),
                                    pcie_slot,
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.pci.function",
                                        vfphy,
                                    ),
                                    pcie_function,
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.used",
                                        vfphy,
                                    ),
                                    False,
                                ),
                                (
                                    (
                                        "node.sriov.vf",
                                        config["node_hostname"],
                                        "sriov_vf.used_by",
                                        vfphy,
                                    ),
                                    "",
                                ),
                            ]
                        )

                    # Append the device to the list of VFs
                    sriov_vf_list.append(vfphy)

            # Remove any obsolete PFs from Zookeeper if they go away
            for pf in zkhandler.children(("node.sriov.pf", config["node_hostname"])):
                if pf not in sriov_pf_list:
                    zkhandler.delete(
                        [("node.sriov.pf", config["node_hostname"], "sriov_pf", pf)]
                    )
            # Remove any obsolete VFs from Zookeeper if their PF goes away
            for vf in zkhandler.children(("node.sriov.vf", config["node_hostname"])):
                vf_pf = zkhandler.read(
                    ("node.sriov.vf", config["node_hostname"], "sriov_vf.pf", vf)
                )
                if vf_pf not in sriov_pf_list:
                    zkhandler.delete(
                        [("node.sriov.vf", config["node_hostname"], "sriov_vf", vf)]
                    )

            # SR-IOV VF objects
            # This is a ChildrenWatch just for consistency; the list never changes at runtime
            @zkhandler.zk_conn.ChildrenWatch(
                zkhandler.schema.path("node.sriov.vf", config["node_hostname"])
            )
            def update_sriov_vfs(new_sriov_vf_list):
                nonlocal sriov_vf_list, d_sriov_vf

                # Add VFs to the list
                for vf in common.sortInterfaceNames(new_sriov_vf_list):
                    d_sriov_vf[vf] = SRIOVVFInstance.SRIOVVFInstance(
                        vf, zkhandler, config, logger, this_node
                    )

                sriov_vf_list = sorted(new_sriov_vf_list)
                logger.out(
                    f'{logger.fmt_blue}SR-IOV VF list:{logger.fmt_end} {" ".join(sriov_vf_list)}',
                    state="i",
                )

    if config["enable_hypervisor"]:
        # VM command pipeline key
        @zkhandler.zk_conn.DataWatch(zkhandler.schema.path("base.cmd.domain"))
        def run_domain_command(data, stat, event=""):
            if data:
                VMInstance.vm_command(
                    zkhandler, logger, this_node, data.decode("ascii")
                )

        # VM domain objects
        @zkhandler.zk_conn.ChildrenWatch(zkhandler.schema.path("base.domain"))
        def update_domains(new_domain_list):
            nonlocal domain_list, d_domain

            # Add missing domains to the list
            for domain in [
                domain for domain in new_domain_list if domain not in domain_list
            ]:
                d_domain[domain] = VMInstance.VMInstance(
                    domain, zkhandler, config, logger, this_node
                )

            # Remove any deleted domains from the list
            for domain in [
                domain for domain in domain_list if domain not in new_domain_list
            ]:
                del d_domain[domain]

            # Update the new list
            domain_list = new_domain_list
            logger.out(
                f'{logger.fmt_blue}Domain list:{logger.fmt_end} {" ".join(domain_list)}',
                state="i",
            )

            # Update node objects' list
            for node in d_node:
                d_node[node].update_domain_list(d_domain)

    if config["enable_storage"]:
        # Ceph command pipeline key
        @zkhandler.zk_conn.DataWatch(zkhandler.schema.path("base.cmd.ceph"))
        def run_ceph_command(data, stat, event=""):
            if data:
                CephInstance.ceph_command(
                    zkhandler, logger, this_node, data.decode("ascii"), d_osd
                )

        # OSD objects
        @zkhandler.zk_conn.ChildrenWatch(zkhandler.schema.path("base.osd"))
        def update_osds(new_osd_list):
            nonlocal osd_list, d_osd

            # Add any missing OSDs to the list
            for osd in [osd for osd in new_osd_list if osd not in osd_list]:
                d_osd[osd] = CephInstance.CephOSDInstance(
                    zkhandler, logger, this_node, osd
                )

            # Remove any deleted OSDs from the list
            for osd in [osd for osd in osd_list if osd not in new_osd_list]:
                del d_osd[osd]

            # Update the new list
            osd_list = new_osd_list
            logger.out(
                f'{logger.fmt_blue}OSD list:{logger.fmt_end} {" ".join(osd_list)}',
                state="i",
            )

        # Pool objects
        @zkhandler.zk_conn.ChildrenWatch(zkhandler.schema.path("base.pool"))
        def update_pools(new_pool_list):
            nonlocal pool_list, d_pool, volume_list, d_volume

            # Add any missing pools to the list
            for pool in [pool for pool in new_pool_list if pool not in pool_list]:
                d_pool[pool] = CephInstance.CephPoolInstance(
                    zkhandler, logger, this_node, pool
                )
                # Prepare the volume components for this pool
                volume_list[pool] = list()
                d_volume[pool] = dict()

            # Remove any deleted pools from the list
            for pool in [pool for pool in pool_list if pool not in new_pool_list]:
                del d_pool[pool]

            # Update the new list
            pool_list = new_pool_list
            logger.out(
                f'{logger.fmt_blue}Pool list:{logger.fmt_end} {" ".join(pool_list)}',
                state="i",
            )

            # Volume objects (in each pool)
            for pool in pool_list:

                @zkhandler.zk_conn.ChildrenWatch(zkhandler.schema.path("volume", pool))
                def update_volumes(new_volume_list):
                    nonlocal volume_list, d_volume

                    # Add any missing volumes to the list
                    for volume in [
                        volume
                        for volume in new_volume_list
                        if volume not in volume_list[pool]
                    ]:
                        d_volume[pool][volume] = CephInstance.CephVolumeInstance(
                            zkhandler, logger, this_node, pool, volume
                        )

                    # Remove any deleted volumes from the list
                    for volume in [
                        volume
                        for volume in volume_list[pool]
                        if volume not in new_volume_list
                    ]:
                        del d_volume[pool][volume]

                    # Update the new list
                    volume_list[pool] = new_volume_list
                    logger.out(
                        f'{logger.fmt_blue}Volume list [{pool}]:{logger.fmt_end} {" ".join(volume_list[pool])}',
                        state="i",
                    )

    # Set up the node monitoring instance
    monitoring_instance = MonitoringInstance.MonitoringInstance(
        zkhandler, config, logger, this_node
    )

    # Start keepalived thread
    keepalive_timer = pvcnoded.util.keepalive.start_keepalive_timer(
        logger, config, zkhandler, this_node, monitoring_instance
    )

    # Tick loop; does nothing since everything is async
    while True:
        try:
            sleep(1)
        except Exception:
            break
