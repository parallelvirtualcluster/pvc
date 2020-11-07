#!/usr/bin/env python3

# VXNetworkInstance.py - Class implementing a PVC VM network and run by pvcnoded
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2020 Joshua M. Boniface <joshua@boniface.me>
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

import os
import time

from textwrap import dedent

import pvcnoded.zkhandler as zkhandler
import pvcnoded.common as common

class VXNetworkInstance(object):
    # Initialization function
    def __init__(self, vni, zk_conn, config, logger, this_node, dns_aggregator):
        self.vni = vni
        self.zk_conn = zk_conn
        self.config = config
        self.logger = logger
        self.this_node = this_node
        self.dns_aggregator = dns_aggregator
        self.vni_dev = config['vni_dev']
        self.vni_mtu = config['vni_mtu']
        self.bridge_dev = config['bridge_dev']

        self.nettype = zkhandler.readdata(self.zk_conn, '/networks/{}/nettype'.format(self.vni))
        if self.nettype == 'bridged':
            self.logger.out(
                'Creating new bridged network',
                prefix='VNI {}'.format(self.vni),
                state='o'
            )
            self.init_bridged()
        elif self.nettype == 'managed':
            self.logger.out(
                'Creating new managed network',
                prefix='VNI {}'.format(self.vni),
                state='o'
            )
            self.init_managed()
        else:
            self.logger.out(
                'Invalid network type {}'.format(self.nettype),
                prefix='VNI {}'.format(self.vni),
                state='o'
            )
            pass

    # Initialize a bridged network
    def init_bridged(self):
        self.old_description = None
        self.description = None

        self.vlan_nic = 'vlan{}'.format(self.vni)
        self.bridge_nic = 'vmbr{}'.format(self.vni)

        # Zookeper handlers for changed states
        @self.zk_conn.DataWatch('/networks/{}'.format(self.vni))
        def watch_network_description(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.description != data.decode('ascii'):
                self.old_description = self.description
                self.description = data.decode('ascii')

        self.createNetworkBridged()

    # Initialize a managed network
    def init_managed(self):
        self.old_description = None
        self.description = None
        self.domain = None
        self.name_servers = None
        self.ip6_gateway = zkhandler.readdata(self.zk_conn, '/networks/{}/ip6_gateway'.format(self.vni))
        self.ip6_network = zkhandler.readdata(self.zk_conn, '/networks/{}/ip6_network'.format(self.vni))
        self.ip6_cidrnetmask = zkhandler.readdata(self.zk_conn, '/networks/{}/ip6_network'.format(self.vni)).split('/')[-1]
        self.dhcp6_flag = ( zkhandler.readdata(self.zk_conn, '/networks/{}/dhcp6_flag'.format(self.vni)) == 'True' )
        self.ip4_gateway = zkhandler.readdata(self.zk_conn, '/networks/{}/ip4_gateway'.format(self.vni))
        self.ip4_network = zkhandler.readdata(self.zk_conn, '/networks/{}/ip4_network'.format(self.vni))
        self.ip4_cidrnetmask = zkhandler.readdata(self.zk_conn, '/networks/{}/ip4_network'.format(self.vni)).split('/')[-1]
        self.dhcp4_flag = ( zkhandler.readdata(self.zk_conn, '/networks/{}/dhcp4_flag'.format(self.vni)) == 'True' )
        self.dhcp4_start = ( zkhandler.readdata(self.zk_conn, '/networks/{}/dhcp4_start'.format(self.vni)) == 'True' )
        self.dhcp4_end = ( zkhandler.readdata(self.zk_conn, '/networks/{}/dhcp4_end'.format(self.vni)) == 'True' )

        self.vxlan_nic = 'vxlan{}'.format(self.vni)
        self.bridge_nic = 'vmbr{}'.format(self.vni)

        self.nftables_netconf_filename = '{}/networks/{}.nft'.format(self.config['nft_dynamic_directory'], self.vni)
        self.firewall_rules = []

        self.dhcp_server_daemon = None
        self.dnsmasq_hostsdir = '{}/{}'.format(self.config['dnsmasq_dynamic_directory'], self.vni)
        self.dhcp_reservations = []

        # Create the network hostsdir
        common.run_os_command(
            '/bin/mkdir --parents {}'.format(
                self.dnsmasq_hostsdir
            )
        )

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
            vxlannic=self.vxlan_nic,
            bridgenic=self.bridge_nic
        )

        self.firewall_rules_v4 = """# Jump from forward chain to this chain when matching net (IPv4)
add rule inet filter forward ip daddr {netaddr4} counter jump {vxlannic}-in
add rule inet filter forward ip saddr {netaddr4} counter jump {vxlannic}-out
""".format(
            netaddr4=self.ip4_network,
            vxlannic=self.vxlan_nic,
        )
        self.firewall_rules_v6 = """# Jump from forward chain to this chain when matching net (IPv4)
add rule inet filter forward ip6 daddr {netaddr6} counter jump {vxlannic}-in
add rule inet filter forward ip6 saddr {netaddr6} counter jump {vxlannic}-out
""".format(
            netaddr6=self.ip6_network,
            vxlannic=self.vxlan_nic,
        )

        self.firewall_rules_in = zkhandler.listchildren(self.zk_conn, '/networks/{}/firewall_rules/in'.format(self.vni))
        self.firewall_rules_out = zkhandler.listchildren(self.zk_conn, '/networks/{}/firewall_rules/out'.format(self.vni))

        # Zookeper handlers for changed states
        @self.zk_conn.DataWatch('/networks/{}'.format(self.vni))
        def watch_network_description(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.description != data.decode('ascii'):
                self.old_description = self.description
                self.description = data.decode('ascii')
                if self.dhcp_server_daemon:
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zk_conn.DataWatch('/networks/{}/domain'.format(self.vni))
        def watch_network_domain(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.domain != data.decode('ascii'):
                domain = data.decode('ascii')
                if self.dhcp_server_daemon:
                    self.dns_aggregator.remove_network(self)
                self.domain = domain
                if self.dhcp_server_daemon:
                    self.dns_aggregator.add_network(self)
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zk_conn.DataWatch('/networks/{}/name_servers'.format(self.vni))
        def watch_network_name_servers(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.name_servers != data.decode('ascii'):
                name_servers = data.decode('ascii').split(',')
                if self.dhcp_server_daemon:
                    self.dns_aggregator.remove_network(self)
                self.name_servers = name_servers
                if self.dhcp_server_daemon:
                    self.dns_aggregator.add_network(self)
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zk_conn.DataWatch('/networks/{}/ip6_network'.format(self.vni))
        def watch_network_ip6_network(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.ip6_network != data.decode('ascii'):
                ip6_network = data.decode('ascii')
                self.ip6_network = ip6_network
                self.ip6_cidrnetmask = ip6_network.split('/')[-1]
                if self.dhcp_server_daemon:
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zk_conn.DataWatch('/networks/{}/ip6_gateway'.format(self.vni))
        def watch_network_gateway6(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.ip6_gateway != data.decode('ascii'):
                orig_gateway = self.ip6_gateway
                if self.this_node.router_state in ['primary', 'takeover']:
                    if orig_gateway:
                        self.removeGateway6Address()
                self.ip6_gateway = data.decode('ascii')
                if self.this_node.router_state in ['primary', 'takeover']:
                    self.createGateway6Address()
                    if self.dhcp_server_daemon:
                        self.stopDHCPServer()
                        self.startDHCPServer()
                if self.dhcp_server_daemon:
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zk_conn.DataWatch('/networks/{}/dhcp6_flag'.format(self.vni))
        def watch_network_dhcp6_status(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.dhcp6_flag != ( data.decode('ascii') == 'True' ):
                self.dhcp6_flag = ( data.decode('ascii') == 'True' )
                if self.dhcp6_flag and not self.dhcp_server_daemon and self.this_node.router_state in ['primary', 'takeover']:
                    self.startDHCPServer()
                elif self.dhcp_server_daemon and not self.dhcp4_flag and self.this_node.router_state in ['primary', 'takeover']:
                    self.stopDHCPServer()

        @self.zk_conn.DataWatch('/networks/{}/ip4_network'.format(self.vni))
        def watch_network_ip4_network(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.ip4_network != data.decode('ascii'):
                ip4_network = data.decode('ascii')
                self.ip4_network = ip4_network
                self.ip4_cidrnetmask = ip4_network.split('/')[-1]
                if self.dhcp_server_daemon:
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zk_conn.DataWatch('/networks/{}/ip4_gateway'.format(self.vni))
        def watch_network_gateway4(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.ip4_gateway != data.decode('ascii'):
                orig_gateway = self.ip4_gateway
                if self.this_node.router_state in ['primary', 'takeover']:
                    if orig_gateway:
                        self.removeGateway4Address()
                self.ip4_gateway = data.decode('ascii')
                if self.this_node.router_state in ['primary', 'takeover']:
                    self.createGateway4Address()
                    if self.dhcp_server_daemon:
                        self.stopDHCPServer()
                        self.startDHCPServer()
                if self.dhcp_server_daemon:
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zk_conn.DataWatch('/networks/{}/dhcp4_flag'.format(self.vni))
        def watch_network_dhcp4_status(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.dhcp4_flag != ( data.decode('ascii') == 'True' ):
                self.dhcp4_flag = ( data.decode('ascii') == 'True' )
                if self.dhcp4_flag and not self.dhcp_server_daemon and self.this_node.router_state in ['primary', 'takeover']:
                    self.startDHCPServer()
                elif self.dhcp_server_daemon and not self.dhcp6_flag and self.this_node.router_state in ['primary', 'takeover']:
                    self.stopDHCPServer()

        @self.zk_conn.DataWatch('/networks/{}/dhcp4_start'.format(self.vni))
        def watch_network_dhcp4_start(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.dhcp4_start != data.decode('ascii'):
                self.dhcp4_start = data.decode('ascii')
                if self.dhcp_server_daemon:
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zk_conn.DataWatch('/networks/{}/dhcp4_end'.format(self.vni))
        def watch_network_dhcp4_end(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.dhcp4_end != data.decode('ascii'):
                self.dhcp4_end = data.decode('ascii')
                if self.dhcp_server_daemon:
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zk_conn.ChildrenWatch('/networks/{}/dhcp4_reservations'.format(self.vni))
        def watch_network_dhcp_reservations(new_reservations, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if self.dhcp_reservations != new_reservations:
                old_reservations = self.dhcp_reservations
                self.dhcp_reservations = new_reservations
                if self.this_node.router_state in ['primary', 'takeover']:
                    self.updateDHCPReservations(old_reservations, new_reservations)
                if self.dhcp_server_daemon:
                    self.stopDHCPServer()
                    self.startDHCPServer()

        @self.zk_conn.ChildrenWatch('/networks/{}/firewall_rules/in'.format(self.vni))
        def watch_network_firewall_rules_in(new_rules, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            # Don't run on the first pass
            if self.firewall_rules_in != new_rules:
                self.firewall_rules_in = new_rules
                self.updateFirewallRules()

        @self.zk_conn.ChildrenWatch('/networks/{}/firewall_rules/out'.format(self.vni))
        def watch_network_firewall_rules_out(new_rules, event=''):
            if event and event.type == 'DELETED':
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

    def updateDHCPReservations(self, old_reservations_list, new_reservations_list):
        for reservation in new_reservations_list:
            if reservation not in old_reservations_list:
                # Add new reservation file
                filename = '{}/{}'.format(self.dnsmasq_hostsdir, reservation)
                ipaddr = zkhandler.readdata(
                    self.zk_conn,
                    '/networks/{}/dhcp4_reservations/{}/ipaddr'.format(
                        self.vni,
                        reservation
                    )
                )
                entry = '{},{}'.format(reservation, ipaddr)
                # Write the entry
                with open(filename, 'w') as outfile:
                    outfile.write(entry)

        for reservation in old_reservations_list:
            if reservation not in new_reservations_list:
                # Remove old reservation file
                filename = '{}/{}'.format(self.dnsmasq_hostsdir, reservation)
                try:
                    os.remove(filename)
                    self.dhcp_server_daemon.signal('hup')
                except Exception:
                    pass

    def updateFirewallRules(self):
        if not self.ip4_network:
            return

        self.logger.out(
            'Updating firewall rules',
            prefix='VNI {}'.format(self.vni),
            state='o'
        )
        ordered_acls_in = {}
        ordered_acls_out = {}
        sorted_acl_list = {'in': [], 'out': []}
        full_ordered_rules = []

        for acl in self.firewall_rules_in:
            order = zkhandler.readdata(self.zk_conn, '/networks/{}/firewall_rules/in/{}/order'.format(self.vni, acl))
            ordered_acls_in[order] = acl
        for acl in self.firewall_rules_out:
            order = zkhandler.readdata(self.zk_conn, '/networks/{}/firewall_rules/out/{}/order'.format(self.vni, acl))
            ordered_acls_out[order] = acl

        for order in sorted(ordered_acls_in.keys()):
            sorted_acl_list['in'].append(ordered_acls_in[order])
        for order in sorted(ordered_acls_out.keys()):
            sorted_acl_list['out'].append(ordered_acls_out[order])

        for direction in 'in', 'out':
            for acl in sorted_acl_list[direction]:
                rule_prefix = "add rule inet filter vxlan{}-{} counter".format(self.vni, direction)
                rule_data = zkhandler.readdata(self.zk_conn, '/networks/{}/firewall_rules/{}/{}/rule'.format(self.vni, direction, acl))
                rule = '{} {}'.format(rule_prefix, rule_data)
                full_ordered_rules.append(rule)

        firewall_rules = self.firewall_rules_base
        if self.ip6_gateway != 'None':
            firewall_rules += self.firewall_rules_v6
        if self.ip4_gateway != 'None':
            firewall_rules += self.firewall_rules_v4

        output = "{}\n# User rules\n{}\n".format(
                     firewall_rules,
                     '\n'.join(full_ordered_rules)
                 )

        with open(self.nftables_netconf_filename, 'w') as nfnetfile:
            nfnetfile.write(dedent(output))

        # Reload firewall rules
        nftables_base_filename = '{}/base.nft'.format(self.config['nft_dynamic_directory'])
        common.reload_firewall_rules(self.logger, nftables_base_filename)

    # Create bridged network configuration
    def createNetworkBridged(self):
        self.logger.out(
            'Creating bridged vLAN device {} on interface {}'.format(
                self.vlan_nic,
                self.bridge_dev
            ),
            prefix='VNI {}'.format(self.vni),
            state='o'
        )

        # Create vLAN interface
        common.run_os_command(
            'ip link add link {} name {} type vlan id {}'.format(
                self.bridge_dev,
                self.vlan_nic,
                self.vni
            )
        )
        # Create bridge interface
        common.run_os_command(
            'brctl addbr {}'.format(
                self.bridge_nic
            )
        )

        # Set MTU of vLAN and bridge NICs
        vx_mtu = self.vni_mtu
        common.run_os_command(
            'ip link set {} mtu {} up'.format(
                self.vlan_nic,
                vx_mtu
            )
        )
        common.run_os_command(
            'ip link set {} mtu {} up'.format(
                self.bridge_nic,
                vx_mtu
            )
        )

        # Disable tx checksum offload on bridge interface (breaks DHCP on Debian < 9)
        common.run_os_command(
            'ethtool -K {} tx off'.format(
                self.bridge_nic
            )
        )

        # Disable IPv6 on bridge interface (prevents leakage)
        common.run_os_command(
            'sysctl net.ipv6.conf.{}.disable_ipv6=1'.format(
                self.bridge_nic
            )
        )

        # Add vLAN interface to bridge interface
        common.run_os_command(
            'brctl addif {} {}'.format(
                self.bridge_nic,
                self.vlan_nic
            )
        )

    # Create managed network configuration
    def createNetworkManaged(self):
        self.logger.out(
            'Creating VXLAN device on interface {}'.format(
                self.vni_dev
            ),
            prefix='VNI {}'.format(self.vni),
            state='o'
        )

        # Create VXLAN interface
        common.run_os_command(
            'ip link add {} type vxlan id {} dstport 4789 dev {}'.format(
                self.vxlan_nic,
                self.vni,
                self.vni_dev
            )
        )
        # Create bridge interface
        common.run_os_command(
            'brctl addbr {}'.format(
                self.bridge_nic
            )
        )

        # Set MTU of VXLAN and bridge NICs
        vx_mtu = self.vni_mtu - 50
        common.run_os_command(
            'ip link set {} mtu {} up'.format(
                self.vxlan_nic,
                vx_mtu
            )
        )
        common.run_os_command(
            'ip link set {} mtu {} up'.format(
                self.bridge_nic,
                vx_mtu
            )
        )

        # Disable tx checksum offload on bridge interface (breaks DHCP on Debian < 9)
        common.run_os_command(
            'ethtool -K {} tx off'.format(
                self.bridge_nic
            )
        )

        # Disable IPv6 DAD on bridge interface
        common.run_os_command(
            'sysctl net.ipv6.conf.{}.accept_dad=0'.format(
                self.bridge_nic
            )
        )

        # Add VXLAN interface to bridge interface
        common.run_os_command(
            'brctl addif {} {}'.format(
                self.bridge_nic,
                self.vxlan_nic
            )
        )

    def createFirewall(self):
        if self.nettype == 'managed':
            # For future use
            self.updateFirewallRules()

    def createGateways(self):
        if self.nettype == 'managed':
            if self.ip6_gateway != 'None':
                self.createGateway6Address()
            if self.ip4_gateway != 'None':
                self.createGateway4Address()

    def createGateway6Address(self):
        if self.this_node.router_state in ['primary', 'takeover']:
            self.logger.out(
                'Creating gateway {}/{} on interface {}'.format(
                    self.ip6_gateway,
                    self.ip6_cidrnetmask,
                    self.bridge_nic
                ),
                prefix='VNI {}'.format(self.vni),
                state='o'
            )
            common.createIPAddress(self.ip6_gateway, self.ip6_cidrnetmask, self.bridge_nic)

    def createGateway4Address(self):
        if self.this_node.router_state in ['primary', 'takeover']:
            self.logger.out(
                'Creating gateway {}/{} on interface {}'.format(
                    self.ip4_gateway,
                    self.ip4_cidrnetmask,
                    self.bridge_nic
                ),
                prefix='VNI {}'.format(self.vni),
                state='o'
            )
            common.createIPAddress(self.ip4_gateway, self.ip4_cidrnetmask, self.bridge_nic)

    def startDHCPServer(self):
        if self.this_node.router_state in ['primary', 'takeover'] and self.nettype == 'managed':
            self.logger.out(
                'Starting dnsmasq DHCP server on interface {}'.format(
                    self.bridge_nic
                ),
                prefix='VNI {}'.format(self.vni),
                state='o'
            )

            # Recreate the environment we need for dnsmasq
            pvcnoded_config_file = os.environ['PVCD_CONFIG_FILE']
            dhcp_environment = {
                'DNSMASQ_BRIDGE_INTERFACE': self.bridge_nic,
                'PVCD_CONFIG_FILE': pvcnoded_config_file
            }

            # Define the dnsmasq config fragments
            dhcp_configuration_base = [
                '--domain-needed',
                '--bogus-priv',
                '--no-hosts',
                '--dhcp-authoritative',
                '--filterwin2k',
                '--expand-hosts',
                '--domain-needed',
                '--domain={}'.format(self.domain),
                '--local=/{}/'.format(self.domain),
                '--log-facility=-',
                '--log-dhcp',
                '--keep-in-foreground',
                '--leasefile-ro',
                '--dhcp-script={}/pvcnoded/dnsmasq-zookeeper-leases.py'.format(os.getcwd()),
                '--dhcp-hostsdir={}'.format(self.dnsmasq_hostsdir),
                '--bind-interfaces',
            ]
            dhcp_configuration_v4 = [
                '--listen-address={}'.format(self.ip4_gateway),
                '--auth-zone={}'.format(self.domain),
                '--auth-peer={}'.format(self.ip4_gateway),
                '--auth-server={}'.format(self.ip4_gateway),
                '--auth-sec-servers={}'.format(self.ip4_gateway),
            ]
            dhcp_configuration_v4_dhcp = [
                '--dhcp-option=option:ntp-server,{}'.format(self.ip4_gateway),
                '--dhcp-range={},{},48h'.format(self.dhcp4_start, self.dhcp4_end),
            ]
            dhcp_configuration_v6 = [
                '--listen-address={}'.format(self.ip6_gateway),
                '--auth-zone={}'.format(self.domain),
                '--auth-peer={}'.format(self.ip6_gateway),
                '--auth-server={}'.format(self.ip6_gateway),
                '--auth-sec-servers={}'.format(self.ip6_gateway),
                '--dhcp-option=option6:dns-server,[{}]'.format(self.ip6_gateway),
                '--dhcp-option=option6:sntp-server,[{}]'.format(self.ip6_gateway),
                '--enable-ra',
            ]
            dhcp_configuration_v6_dualstack = [
                '--dhcp-range=net:{nic},::,constructor:{nic},ra-stateless,ra-names'.format(nic=self.bridge_nic),
            ]
            dhcp_configuration_v6_only = [
                '--auth-server={}'.format(self.ip6_gateway),
                '--dhcp-range=net:{nic},::2,::ffff:ffff:ffff:ffff,constructor:{nic},64,24h'.format(nic=self.bridge_nic),
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
            print('/usr/sbin/dnsmasq {}'.format(' '.join(dhcp_configuration)))
            self.dhcp_server_daemon = common.run_os_daemon(
                '/usr/sbin/dnsmasq {}'.format(
                    ' '.join(dhcp_configuration)
                ),
                environment=dhcp_environment,
                logfile='{}/dnsmasq-{}.log'.format(self.config['dnsmasq_log_directory'], self.vni)
            )

    # Remove network
    def removeNetwork(self):
        if self.nettype == 'bridged':
            self.removeNetworkBridged()
        elif self.nettype == 'managed':
            self.removeNetworkManaged()

    # Remove bridged network configuration
    def removeNetworkBridged(self):
        self.logger.out(
            'Removing VNI device on interface {}'.format(
                self.vni_dev
            ),
            prefix='VNI {}'.format(self.vni),
            state='o'
        )
        common.run_os_command(
            'ip link set {} down'.format(
                self.bridge_nic
            )
        )
        common.run_os_command(
            'ip link set {} down'.format(
                self.vlan_nic
            )
        )
        common.run_os_command(
            'brctl delif {} {}'.format(
                self.bridge_nic,
                self.vlan_nic
            )
        )
        common.run_os_command(
            'brctl delbr {}'.format(
                self.bridge_nic
            )
        )
        common.run_os_command(
            'ip link delete {}'.format(
                self.vlan_nic
            )
        )

    # Remove managed network configuration
    def removeNetworkManaged(self):
        self.logger.out(
            'Removing VNI device on interface {}'.format(
                self.vni_dev
            ),
            prefix='VNI {}'.format(self.vni),
            state='o'
        )
        common.run_os_command(
            'ip link set {} down'.format(
                self.bridge_nic
            )
        )
        common.run_os_command(
            'ip link set {} down'.format(
                self.vxlan_nic
            )
        )
        common.run_os_command(
            'brctl delif {} {}'.format(
                self.bridge_nic,
                self.vxlan_nic
            )
        )
        common.run_os_command(
            'brctl delbr {}'.format(
                self.bridge_nic
            )
        )
        common.run_os_command(
            'ip link delete {}'.format(
                self.vxlan_nic
            )
        )

    def removeFirewall(self):
        self.logger.out(
            'Removing firewall rules',
            prefix='VNI {}'.format(self.vni),
            state='o'
        )

        try:
            os.remove(self.nftables_netconf_filename)
        except Exception:
            pass

        # Reload firewall rules
        nftables_base_filename = '{}/base.nft'.format(self.config['nft_dynamic_directory'])
        common.reload_firewall_rules(self.logger, nftables_base_filename)

    def removeGateways(self):
        if self.nettype == 'managed':
            if self.ip6_gateway != 'None':
                self.removeGateway6Address()
            if self.ip4_gateway != 'None':
                self.removeGateway4Address()

    def removeGateway6Address(self):
        self.logger.out(
            'Removing gateway {}/{} from interface {}'.format(
                self.ip6_gateway,
                self.ip6_cidrnetmask,
                self.bridge_nic
            ),
            prefix='VNI {}'.format(self.vni),
            state='o'
        )
        common.removeIPAddress(self.ip6_gateway, self.ip6_cidrnetmask, self.bridge_nic)

    def removeGateway4Address(self):
        self.logger.out(
            'Removing gateway {}/{} from interface {}'.format(
                self.ip4_gateway,
                self.ip4_cidrnetmask,
                self.bridge_nic
            ),
            prefix='VNI {}'.format(self.vni),
            state='o'
        )
        common.removeIPAddress(self.ip4_gateway, self.ip4_cidrnetmask, self.bridge_nic)

    def stopDHCPServer(self):
        if self.nettype == 'managed' and self.dhcp_server_daemon:
            self.logger.out(
                'Stopping dnsmasq DHCP server on interface {}'.format(
                    self.bridge_nic
                ),
                prefix='VNI {}'.format(self.vni),
                state='o'
            )
            # Terminate, then kill
            self.dhcp_server_daemon.signal('term')
            time.sleep(0.2)
            self.dhcp_server_daemon.signal('kill')
            self.dhcp_server_daemon = None
