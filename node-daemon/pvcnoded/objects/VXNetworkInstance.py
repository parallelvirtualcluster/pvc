#!/usr/bin/env python3

# VXNetworkInstance.py - Class implementing a PVC VM network and run by pvcnoded
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

import os
import time

from textwrap import dedent

import daemon_lib.common as common


class VXNetworkInstance(object):
    # Initialization function
    def __init__(self, vni, zkhandler, config, logger, this_node, dns_aggregator):
        self.vni = vni
        self.zkhandler = zkhandler
        self.config = config
        self.logger = logger
        self.this_node = this_node
        self.dns_aggregator = dns_aggregator
        self.cluster_dev = config["cluster_dev"]
        self.cluster_mtu = config["cluster_mtu"]
        self.bridge_dev = config["bridge_dev"]
        self.bridge_mtu = config["bridge_mtu"]

        self.nettype = self.zkhandler.read(("network.type", self.vni))
        if self.nettype == "bridged":
            self.base_nic = "vlan{}".format(self.vni)
            self.bridge_nic = "vmbr{}".format(self.vni)
            self.max_mtu = self.bridge_mtu
            self.logger.out(
                "Creating new bridged network",
                prefix="VNI {}".format(self.vni),
                state="i",
            )
            self.init_bridged()
        elif self.nettype == "managed":
            self.base_nic = "vxlan{}".format(self.vni)
            self.bridge_nic = "vmbr{}".format(self.vni)
            self.max_mtu = self.cluster_mtu - 50
            self.logger.out(
                "Creating new managed network",
                prefix="VNI {}".format(self.vni),
                state="i",
            )
            self.init_managed()
        else:
            self.base_nic = None
            self.bridge_nic = None
            self.max_mtu = 0
            self.logger.out(
                "Invalid network type {}".format(self.nettype),
                prefix="VNI {}".format(self.vni),
                state="i",
            )
            pass

    # Initialize a bridged network
    def init_bridged(self):
        self.old_description = None
        self.description = None

        try:
            self.vx_mtu = self.zkhandler.read(("network.mtu", self.vni))
            self.validateNetworkMTU()
        except Exception:
            self.vx_mtu = None

        # Zookeper handlers for changed states
        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("network", self.vni)
        )
        def watch_network_description(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.description != data.decode("ascii"):
                self.old_description = self.description
                self.description = data.decode("ascii")

        # Try block for migration purposes
        try:

            @self.zkhandler.zk_conn.DataWatch(
                self.zkhandler.schema.path("network.mtu", self.vni)
            )
            def watch_network_mtu(data, stat, event=""):
                if event and event.type == "DELETED":
                    # The key has been deleted after existing before; terminate this watcher
                    # because this class instance is about to be reaped in Daemon.py
                    return False

                if data and str(self.vx_mtu) != data.decode("ascii"):
                    self.vx_mtu = data.decode("ascii")
                    self.validateNetworkMTU()
                    self.updateNetworkMTU()

        except Exception:
            self.validateNetworkMTU()

        self.createNetworkBridged()

    # Initialize a managed network
    def init_managed(self):
        self.old_description = None
        self.description = None
        self.domain = None
        self.name_servers = None
        self.ip6_gateway = self.zkhandler.read(("network.ip6.gateway", self.vni))
        self.ip6_network = self.zkhandler.read(("network.ip6.network", self.vni))
        self.ip6_cidrnetmask = self.zkhandler.read(
            ("network.ip6.network", self.vni)
        ).split("/")[-1]
        self.dhcp6_flag = self.zkhandler.read(("network.ip6.dhcp", self.vni))
        self.ip4_gateway = self.zkhandler.read(("network.ip4.gateway", self.vni))
        self.ip4_network = self.zkhandler.read(("network.ip4.network", self.vni))
        self.ip4_cidrnetmask = self.zkhandler.read(
            ("network.ip4.network", self.vni)
        ).split("/")[-1]
        self.dhcp4_flag = self.zkhandler.read(("network.ip4.dhcp", self.vni))
        self.dhcp4_start = self.zkhandler.read(("network.ip4.dhcp_start", self.vni))
        self.dhcp4_end = self.zkhandler.read(("network.ip4.dhcp_end", self.vni))

        try:
            self.vx_mtu = self.zkhandler.read(("network.mtu", self.vni))
            self.validateNetworkMTU()
        except Exception:
            self.vx_mtu = None

        self.nftables_netconf_filename = "{}/networks/{}.nft".format(
            self.config["nft_dynamic_directory"], self.vni
        )
        self.firewall_rules = []

        self.dhcp_server_daemon = None
        self.dnsmasq_hostsdir = "{}/{}".format(
            self.config["dnsmasq_dynamic_directory"], self.vni
        )
        self.dhcp_reservations = []

        # Create the network hostsdir
        common.run_os_command("/bin/mkdir --parents {}".format(self.dnsmasq_hostsdir))

        self.firewall_rules_base = """# Rules for network {vxlannic}
add chain inet filter {vxlannic}-in
add chain inet filter {vxlannic}-out
add rule inet filter {vxlannic}-in counter
add rule inet filter {vxlannic}-out counter
# Allow ICMP traffic into the router from network
add rule inet filter input ip protocol icmp meta iifname {bridgenic} counter accept
add rule inet filter input ip6 nexthdr icmpv6 meta iifname {bridgenic} counter accept
# Allow DNS, DHCP, and NTP traffic into the router from network
add rule inet filter input tcp dport 53 meta iifname {bridgenic} counter accept
add rule inet filter input udp dport 53 meta iifname {bridgenic} counter accept
add rule inet filter input udp dport 67 meta iifname {bridgenic} counter accept
add rule inet filter input udp dport 123 meta iifname {bridgenic} counter accept
add rule inet filter input ip6 nexthdr udp udp dport 547 meta iifname {bridgenic} counter accept
# Allow metadata API into the router from network
add rule inet filter input tcp dport 80 meta iifname {bridgenic} counter accept
# Block traffic into the router from network
add rule inet filter input meta iifname {bridgenic} counter drop
""".format(
            vxlannic=self.base_nic, bridgenic=self.bridge_nic
        )

        self.firewall_rules_v4 = """# Jump from forward chain to this chain when matching net (IPv4)
add rule inet filter forward ip daddr {netaddr4} counter jump {vxlannic}-in
add rule inet filter forward ip saddr {netaddr4} counter jump {vxlannic}-out
""".format(
            netaddr4=self.ip4_network,
            vxlannic=self.base_nic,
        )
        self.firewall_rules_v6 = """# Jump from forward chain to this chain when matching net (IPv4)
add rule inet filter forward ip6 daddr {netaddr6} counter jump {vxlannic}-in
add rule inet filter forward ip6 saddr {netaddr6} counter jump {vxlannic}-out
""".format(
            netaddr6=self.ip6_network,
            vxlannic=self.base_nic,
        )

        self.firewall_rules_in = self.zkhandler.children(("network.rule.in", self.vni))
        self.firewall_rules_out = self.zkhandler.children(
            ("network.rule.out", self.vni)
        )

        # Zookeper handlers for changed states
        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("network", self.vni)
        )
        def watch_network_description(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.description != data.decode("ascii"):
                self.old_description = self.description
                self.description = data.decode("ascii")
                if self.dhcp_server_daemon:
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("network.domain", self.vni)
        )
        def watch_network_domain(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.domain != data.decode("ascii"):
                domain = data.decode("ascii")
                if self.dhcp_server_daemon:
                    self.dns_aggregator.remove_network(self)
                self.domain = domain
                if self.dhcp_server_daemon:
                    self.dns_aggregator.add_network(self)
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("network.nameservers", self.vni)
        )
        def watch_network_name_servers(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.name_servers != data.decode("ascii"):
                name_servers = data.decode("ascii").split(",")
                if self.dhcp_server_daemon:
                    self.dns_aggregator.remove_network(self)
                self.name_servers = name_servers
                if self.dhcp_server_daemon:
                    self.dns_aggregator.add_network(self)
                    self.stopDHCPServer()
                    self.startDHCPServer()

        # Try block for migration purposes
        try:

            @self.zkhandler.zk_conn.DataWatch(
                self.zkhandler.schema.path("network.mtu", self.vni)
            )
            def watch_network_mtu(data, stat, event=""):
                if event and event.type == "DELETED":
                    # The key has been deleted after existing before; terminate this watcher
                    # because this class instance is about to be reaped in Daemon.py
                    return False

                if data and str(self.vx_mtu) != data.decode("ascii"):
                    self.vx_mtu = data.decode("ascii")
                    self.validateNetworkMTU()
                    self.updateNetworkMTU()

        except Exception:
            self.validateNetworkMTU()

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("network.ip6.network", self.vni)
        )
        def watch_network_ip6_network(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.ip6_network != data.decode("ascii"):
                ip6_network = data.decode("ascii")
                self.ip6_network = ip6_network
                self.ip6_cidrnetmask = ip6_network.split("/")[-1]
                if self.dhcp_server_daemon:
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("network.ip6.gateway", self.vni)
        )
        def watch_network_gateway6(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.ip6_gateway != data.decode("ascii"):
                orig_gateway = self.ip6_gateway
                if self.this_node.coordinator_state in ["primary", "takeover"]:
                    if orig_gateway:
                        self.removeGateway6Address()
                self.ip6_gateway = data.decode("ascii")
                if self.this_node.coordinator_state in ["primary", "takeover"]:
                    self.createGateway6Address()
                    if self.dhcp_server_daemon:
                        self.stopDHCPServer()
                        self.startDHCPServer()
                if self.dhcp_server_daemon:
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("network.ip6.dhcp", self.vni)
        )
        def watch_network_dhcp6_status(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.dhcp6_flag != (data.decode("ascii") == "True"):
                self.dhcp6_flag = data.decode("ascii") == "True"
                if (
                    self.dhcp6_flag
                    and not self.dhcp_server_daemon
                    and self.this_node.coordinator_state in ["primary", "takeover"]
                ):
                    self.startDHCPServer()
                elif (
                    self.dhcp_server_daemon
                    and not self.dhcp4_flag
                    and self.this_node.coordinator_state in ["primary", "takeover"]
                ):
                    self.stopDHCPServer()

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("network.ip4.network", self.vni)
        )
        def watch_network_ip4_network(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.ip4_network != data.decode("ascii"):
                ip4_network = data.decode("ascii")
                self.ip4_network = ip4_network
                self.ip4_cidrnetmask = ip4_network.split("/")[-1]
                if self.dhcp_server_daemon:
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("network.ip4.gateway", self.vni)
        )
        def watch_network_gateway4(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.ip4_gateway != data.decode("ascii"):
                orig_gateway = self.ip4_gateway
                if self.this_node.coordinator_state in ["primary", "takeover"]:
                    if orig_gateway:
                        self.removeGateway4Address()
                self.ip4_gateway = data.decode("ascii")
                if self.this_node.coordinator_state in ["primary", "takeover"]:
                    self.createGateway4Address()
                    if self.dhcp_server_daemon:
                        self.stopDHCPServer()
                        self.startDHCPServer()
                if self.dhcp_server_daemon:
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("network.ip4.dhcp", self.vni)
        )
        def watch_network_dhcp4_status(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.dhcp4_flag != (data.decode("ascii") == "True"):
                self.dhcp4_flag = data.decode("ascii") == "True"
                if (
                    self.dhcp4_flag
                    and not self.dhcp_server_daemon
                    and self.this_node.coordinator_state in ["primary", "takeover"]
                ):
                    self.startDHCPServer()
                elif (
                    self.dhcp_server_daemon
                    and not self.dhcp6_flag
                    and self.this_node.coordinator_state in ["primary", "takeover"]
                ):
                    self.stopDHCPServer()

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("network.ip4.dhcp_start", self.vni)
        )
        def watch_network_dhcp4_start(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.dhcp4_start != data.decode("ascii"):
                self.dhcp4_start = data.decode("ascii")
                if self.dhcp_server_daemon:
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("network.ip4.dhcp_end", self.vni)
        )
        def watch_network_dhcp4_end(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.dhcp4_end != data.decode("ascii"):
                self.dhcp4_end = data.decode("ascii")
                if self.dhcp_server_daemon:
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zkhandler.zk_conn.ChildrenWatch(
            self.zkhandler.schema.path("network.reservation", self.vni)
        )
        def watch_network_dhcp_reservations(new_reservations, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if self.dhcp_reservations != new_reservations:
                old_reservations = self.dhcp_reservations
                self.dhcp_reservations = new_reservations
                if self.this_node.coordinator_state in ["primary", "takeover"]:
                    self.updateDHCPReservations(old_reservations, new_reservations)
                if self.dhcp_server_daemon:
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zkhandler.zk_conn.ChildrenWatch(
            self.zkhandler.schema.path("network.rule.in", self.vni)
        )
        def watch_network_firewall_rules_in(new_rules, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            # Don't run on the first pass
            if self.firewall_rules_in != new_rules:
                self.firewall_rules_in = new_rules
                self.updateFirewallRules()

        @self.zkhandler.zk_conn.ChildrenWatch(
            self.zkhandler.schema.path("network.rule.out", self.vni)
        )
        def watch_network_firewall_rules_out(new_rules, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            # Don't run on the first pass
            if self.firewall_rules_out != new_rules:
                self.firewall_rules_out = new_rules
                self.updateFirewallRules()

        self.createNetworkManaged()
        self.createFirewall()

    def getvni(self):
        return self.vni

    def validateNetworkMTU(self):
        update_mtu = False

        # Explicitly set the MTU to max_mtu if unset (in Zookeeper too assuming the key exists)
        if self.vx_mtu == "" or self.vx_mtu is None:
            self.logger.out(
                "MTU not specified; setting to maximum MTU {} instead".format(
                    self.max_mtu
                ),
                prefix="VNI {}".format(self.vni),
                state="w",
            )
            self.vx_mtu = self.max_mtu
            update_mtu = True

        # Set MTU to an integer (if it's not)
        if not isinstance(self.vx_mtu, int):
            self.vx_mtu = int(self.vx_mtu)

        # Ensure the MTU is valid
        if self.vx_mtu > self.max_mtu:
            self.logger.out(
                "MTU {} is larger than maximum MTU {}; setting to maximum MTU instead".format(
                    self.vx_mtu, self.max_mtu
                ),
                prefix="VNI {}".format(self.vni),
                state="w",
            )
            self.vx_mtu = self.max_mtu
            update_mtu = True

        if update_mtu:
            # Try block for migration purposes
            try:
                self.zkhandler.write([(("network.mtu", self.vni), self.vx_mtu)])
            except Exception as e:
                self.logger.out(
                    "Could not update MTU in Zookeeper: {}".format(e),
                    prefix="VNI {}".format(self.vni),
                    state="w",
                )

    def updateNetworkMTU(self):
        self.logger.out(
            "Setting network MTU to {}".format(self.vx_mtu),
            prefix="VNI {}".format(self.vni),
            state="i",
        )
        # Set MTU of base and bridge NICs
        common.run_os_command(
            "ip link set {} mtu {} up".format(self.base_nic, self.vx_mtu)
        )
        common.run_os_command(
            "ip link set {} mtu {} up".format(self.bridge_nic, self.vx_mtu)
        )

    def updateDHCPReservations(self, old_reservations_list, new_reservations_list):
        for reservation in new_reservations_list:
            if reservation not in old_reservations_list:
                # Add new reservation file
                filename = "{}/{}".format(self.dnsmasq_hostsdir, reservation)
                ipaddr = self.zkhandler.read(
                    ("network.reservation", self.vni, "reservation.ip", reservation)
                )
                entry = "{},{}".format(reservation, ipaddr)
                # Write the entry
                with open(filename, "w") as outfile:
                    outfile.write(entry)

        for reservation in old_reservations_list:
            if reservation not in new_reservations_list:
                # Remove old reservation file
                filename = "{}/{}".format(self.dnsmasq_hostsdir, reservation)
                try:
                    os.remove(filename)
                    self.dhcp_server_daemon.signal("hup")
                except Exception:
                    pass

    def updateFirewallRules(self):
        if not self.ip4_network:
            return

        self.logger.out(
            "Updating firewall rules", prefix="VNI {}".format(self.vni), state="i"
        )
        ordered_acls_in = {}
        ordered_acls_out = {}
        sorted_acl_list = {"in": [], "out": []}
        full_ordered_rules = []

        for acl in self.firewall_rules_in:
            order = self.zkhandler.read(
                ("network.rule.in", self.vni, "rule.order", acl)
            )
            ordered_acls_in[order] = acl
        for acl in self.firewall_rules_out:
            order = self.zkhandler.read(
                ("network.rule.out", self.vni, "rule.order", acl)
            )
            ordered_acls_out[order] = acl

        for order in sorted(ordered_acls_in.keys()):
            sorted_acl_list["in"].append(ordered_acls_in[order])
        for order in sorted(ordered_acls_out.keys()):
            sorted_acl_list["out"].append(ordered_acls_out[order])

        for direction in "in", "out":
            for acl in sorted_acl_list[direction]:
                rule_prefix = "add rule inet filter vxlan{}-{} counter".format(
                    self.vni, direction
                )
                rule_data = self.zkhandler.read(
                    (f"network.rule.{direction}", self.vni, "rule.rule", acl)
                )
                rule = "{} {}".format(rule_prefix, rule_data)
                full_ordered_rules.append(rule)

        firewall_rules = self.firewall_rules_base
        if self.ip6_gateway != "None":
            firewall_rules += self.firewall_rules_v6
        if self.ip4_gateway != "None":
            firewall_rules += self.firewall_rules_v4

        output = "{}\n# User rules\n{}\n".format(
            firewall_rules, "\n".join(full_ordered_rules)
        )

        with open(self.nftables_netconf_filename, "w") as nfnetfile:
            nfnetfile.write(dedent(output))

        # Reload firewall rules
        nftables_base_filename = "{}/base.nft".format(
            self.config["nft_dynamic_directory"]
        )
        common.reload_firewall_rules(nftables_base_filename, logger=self.logger)

    # Create bridged network configuration
    def createNetworkBridged(self):
        self.logger.out(
            "Creating bridged vLAN device {} on interface {}".format(
                self.base_nic, self.bridge_dev
            ),
            prefix="VNI {}".format(self.vni),
            state="i",
        )

        # Create vLAN interface
        common.run_os_command(
            "ip link add link {} name {} type vlan id {}".format(
                self.bridge_dev, self.base_nic, self.vni
            )
        )
        # Create bridge interface
        common.run_os_command("brctl addbr {}".format(self.bridge_nic))

        self.updateNetworkMTU()

        # Disable tx checksum offload on bridge interface (breaks DHCP on Debian < 9)
        common.run_os_command("ethtool -K {} tx off".format(self.bridge_nic))

        # Disable IPv6 on bridge interface (prevents leakage)
        common.run_os_command(
            "sysctl net.ipv6.conf.{}.disable_ipv6=1".format(self.bridge_nic)
        )

        # Add vLAN interface to bridge interface
        common.run_os_command(
            "brctl addif {} {}".format(self.bridge_nic, self.base_nic)
        )

    # Create managed network configuration
    def createNetworkManaged(self):
        self.logger.out(
            "Creating VXLAN device on interface {}".format(self.cluster_dev),
            prefix="VNI {}".format(self.vni),
            state="i",
        )

        # Create VXLAN interface
        common.run_os_command(
            "ip link add {} type vxlan id {} dstport 4789 dev {}".format(
                self.base_nic, self.vni, self.cluster_dev
            )
        )
        # Create bridge interface
        common.run_os_command("brctl addbr {}".format(self.bridge_nic))

        self.updateNetworkMTU()

        # Disable tx checksum offload on bridge interface (breaks DHCP on Debian < 9)
        common.run_os_command("ethtool -K {} tx off".format(self.bridge_nic))

        # Disable IPv6 DAD on bridge interface
        common.run_os_command(
            "sysctl net.ipv6.conf.{}.accept_dad=0".format(self.bridge_nic)
        )

        # Add VXLAN interface to bridge interface
        common.run_os_command(
            "brctl addif {} {}".format(self.bridge_nic, self.base_nic)
        )

    def createFirewall(self):
        if self.nettype == "managed":
            # For future use
            self.updateFirewallRules()

    def createGateways(self):
        if self.nettype == "managed":
            if self.ip6_gateway != "None":
                self.createGateway6Address()
            if self.ip4_gateway != "None":
                self.createGateway4Address()

    def createGateway6Address(self):
        if self.this_node.coordinator_state in ["primary", "takeover"]:
            self.logger.out(
                "Creating gateway {}/{} on interface {}".format(
                    self.ip6_gateway, self.ip6_cidrnetmask, self.bridge_nic
                ),
                prefix="VNI {}".format(self.vni),
                state="i",
            )
            common.createIPAddress(
                self.ip6_gateway, self.ip6_cidrnetmask, self.bridge_nic
            )

    def createGateway4Address(self):
        if self.this_node.coordinator_state in ["primary", "takeover"]:
            self.logger.out(
                "Creating gateway {}/{} on interface {}".format(
                    self.ip4_gateway, self.ip4_cidrnetmask, self.bridge_nic
                ),
                prefix="VNI {}".format(self.vni),
                state="i",
            )
            common.createIPAddress(
                self.ip4_gateway, self.ip4_cidrnetmask, self.bridge_nic
            )

    def startDHCPServer(self):
        if (
            self.this_node.coordinator_state in ["primary", "takeover"]
            and self.nettype == "managed"
        ):
            self.logger.out(
                "Starting dnsmasq DHCP server on interface {}".format(self.bridge_nic),
                prefix="VNI {}".format(self.vni),
                state="i",
            )

            # Recreate the environment we need for dnsmasq
            pvcnoded_config_file = os.environ["PVCD_CONFIG_FILE"]
            dhcp_environment = {
                "DNSMASQ_BRIDGE_INTERFACE": self.bridge_nic,
                "PVCD_CONFIG_FILE": pvcnoded_config_file,
            }

            # Define the dnsmasq config fragments
            dhcp_configuration_base = [
                "--domain-needed",
                "--bogus-priv",
                "--no-hosts",
                "--dhcp-authoritative",
                "--filterwin2k",
                "--expand-hosts",
                "--domain-needed",
                "--domain={}".format(self.domain),
                "--local=/{}/".format(self.domain),
                "--log-facility=-",
                "--log-dhcp",
                "--keep-in-foreground",
                "--leasefile-ro",
                "--dhcp-script={}/pvcnoded/dnsmasq-zookeeper-leases.py".format(
                    os.getcwd()
                ),
                "--dhcp-hostsdir={}".format(self.dnsmasq_hostsdir),
                "--bind-interfaces",
            ]
            dhcp_configuration_v4 = [
                "--listen-address={}".format(self.ip4_gateway),
                "--auth-zone={}".format(self.domain),
                "--auth-peer={}".format(self.ip4_gateway),
                "--auth-server={}".format(self.ip4_gateway),
                "--auth-sec-servers={}".format(self.ip4_gateway),
            ]
            dhcp_configuration_v4_dhcp = [
                "--dhcp-option=option:ntp-server,{}".format(self.ip4_gateway),
                "--dhcp-range={},{},48h".format(self.dhcp4_start, self.dhcp4_end),
            ]
            dhcp_configuration_v6 = [
                "--listen-address={}".format(self.ip6_gateway),
                "--auth-zone={}".format(self.domain),
                "--auth-peer={}".format(self.ip6_gateway),
                "--auth-server={}".format(self.ip6_gateway),
                "--auth-sec-servers={}".format(self.ip6_gateway),
                "--dhcp-option=option6:dns-server,[{}]".format(self.ip6_gateway),
                "--dhcp-option=option6:sntp-server,[{}]".format(self.ip6_gateway),
                "--enable-ra",
            ]
            dhcp_configuration_v6_dualstack = [
                "--dhcp-range=net:{nic},::,constructor:{nic},ra-stateless,ra-names".format(
                    nic=self.bridge_nic
                ),
            ]
            dhcp_configuration_v6_only = [
                "--auth-server={}".format(self.ip6_gateway),
                "--dhcp-range=net:{nic},::2,::ffff:ffff:ffff:ffff,constructor:{nic},64,24h".format(
                    nic=self.bridge_nic
                ),
            ]

            # Assemble the DHCP configuration
            dhcp_configuration = dhcp_configuration_base
            if self.dhcp6_flag:
                dhcp_configuration += dhcp_configuration_v6
                if self.dhcp4_flag:
                    dhcp_configuration += dhcp_configuration_v6_dualstack
                else:
                    dhcp_configuration += dhcp_configuration_v6_only
            else:
                dhcp_configuration += dhcp_configuration_v4
            if self.dhcp4_flag:
                dhcp_configuration += dhcp_configuration_v4_dhcp

            # Start the dnsmasq process in a thread
            print("/usr/sbin/dnsmasq {}".format(" ".join(dhcp_configuration)))
            self.dhcp_server_daemon = common.run_os_daemon(
                "/usr/sbin/dnsmasq {}".format(" ".join(dhcp_configuration)),
                environment=dhcp_environment,
                logfile="{}/dnsmasq-{}.log".format(
                    self.config["dnsmasq_log_directory"], self.vni
                ),
            )

    # Remove network
    def removeNetwork(self):
        if self.nettype == "bridged":
            self.removeNetworkBridged()
        elif self.nettype == "managed":
            self.removeNetworkManaged()

    # Remove bridged network configuration
    def removeNetworkBridged(self):
        self.logger.out(
            "Removing VNI device on interface {}".format(self.cluster_dev),
            prefix="VNI {}".format(self.vni),
            state="i",
        )
        common.run_os_command("ip link set {} down".format(self.bridge_nic))
        common.run_os_command("ip link set {} down".format(self.base_nic))
        common.run_os_command(
            "brctl delif {} {}".format(self.bridge_nic, self.base_nic)
        )
        common.run_os_command("brctl delbr {}".format(self.bridge_nic))
        common.run_os_command("ip link delete {}".format(self.base_nic))

    # Remove managed network configuration
    def removeNetworkManaged(self):
        self.logger.out(
            "Removing VNI device on interface {}".format(self.cluster_dev),
            prefix="VNI {}".format(self.vni),
            state="i",
        )
        common.run_os_command("ip link set {} down".format(self.bridge_nic))
        common.run_os_command("ip link set {} down".format(self.base_nic))
        common.run_os_command(
            "brctl delif {} {}".format(self.bridge_nic, self.base_nic)
        )
        common.run_os_command("brctl delbr {}".format(self.bridge_nic))
        common.run_os_command("ip link delete {}".format(self.base_nic))

    def removeFirewall(self):
        self.logger.out(
            "Removing firewall rules", prefix="VNI {}".format(self.vni), state="i"
        )

        try:
            os.remove(self.nftables_netconf_filename)
        except Exception:
            pass

        # Reload firewall rules
        nftables_base_filename = "{}/base.nft".format(
            self.config["nft_dynamic_directory"]
        )
        common.reload_firewall_rules(nftables_base_filename, logger=self.logger)

    def removeGateways(self):
        if self.nettype == "managed":
            if self.ip6_gateway != "None":
                self.removeGateway6Address()
            if self.ip4_gateway != "None":
                self.removeGateway4Address()

    def removeGateway6Address(self):
        self.logger.out(
            "Removing gateway {}/{} from interface {}".format(
                self.ip6_gateway, self.ip6_cidrnetmask, self.bridge_nic
            ),
            prefix="VNI {}".format(self.vni),
            state="i",
        )
        common.removeIPAddress(self.ip6_gateway, self.ip6_cidrnetmask, self.bridge_nic)

    def removeGateway4Address(self):
        self.logger.out(
            "Removing gateway {}/{} from interface {}".format(
                self.ip4_gateway, self.ip4_cidrnetmask, self.bridge_nic
            ),
            prefix="VNI {}".format(self.vni),
            state="i",
        )
        common.removeIPAddress(self.ip4_gateway, self.ip4_cidrnetmask, self.bridge_nic)

    def stopDHCPServer(self):
        if self.nettype == "managed" and self.dhcp_server_daemon:
            self.logger.out(
                "Stopping dnsmasq DHCP server on interface {}".format(self.bridge_nic),
                prefix="VNI {}".format(self.vni),
                state="i",
            )
            # Terminate, then kill
            self.dhcp_server_daemon.signal("term")
            time.sleep(0.2)
            self.dhcp_server_daemon.signal("kill")
            self.dhcp_server_daemon = None
