#!/usr/bin/env python3

# VXNetworkInstance.py - Class implementing a PVC VM network and run by pvcd
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018  Joshua M. Boniface <joshua@boniface.me>
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
import sys
from textwrap import dedent

import pvcd.log as log
import pvcd.zkhandler as zkhandler
import pvcd.common as common

class VXNetworkInstance(object):
    # Initialization function
    def __init__ (self, vni, zk_conn, config, logger, this_node):
        self.vni = vni
        self.zk_conn = zk_conn
        self.config = config
        self.logger = logger
        self.this_node = this_node
        self.vni_dev = config['vni_dev']

        self.old_description = None
        self.description = None
        self.domain = None
        self.ip_gateway = zkhandler.readdata(self.zk_conn, '/networks/{}/ip_gateway'.format(self.vni))
        self.ip_network = None
        self.ip_cidrnetmask = None
        self.dhcp_flag = zkhandler.readdata(self.zk_conn, '/networks/{}/dhcp_flag'.format(self.vni))
        self.dhcp_start = None
        self.dhcp_end = None

        self.vxlan_nic = 'vxlan{}'.format(self.vni)
        self.bridge_nic = 'br{}'.format(self.vni)

        self.nftables_update_filename = '{}/update'.format(config['nft_dynamic_directory'])
        self.nftables_netconf_filename = '{}/networks/{}.nft'.format(config['nft_dynamic_directory'], self.vni)
        self.firewall_rules = []

        self.dhcp_server_daemon = None
        self.dnsmasq_hostsdir = '{}/{}'.format(config['dnsmasq_dynamic_directory'], self.vni)
        self.dhcp_reservations = []

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

        @self.zk_conn.DataWatch('/networks/{}/domain'.format(self.vni))
        def watch_network_domain(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.domain != data.decode('ascii'):
                domain = data.decode('ascii')
                self.domain = domain

        @self.zk_conn.DataWatch('/networks/{}/ip_network'.format(self.vni))
        def watch_network_ip_network(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.ip_network != data.decode('ascii'):
                ip_network = data.decode('ascii')
                self.ip_network = ip_network
                self.ip_cidrnetmask = ip_network.split('/')[-1]

        @self.zk_conn.DataWatch('/networks/{}/ip_gateway'.format(self.vni))
        def watch_network_gateway(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.ip_gateway != data.decode('ascii'):
                orig_gateway = self.ip_gateway
                self.ip_gateway = data.decode('ascii')
                if self.this_node.router_state == 'primary':
                    if orig_gateway:
                        self.removeGatewayAddress()
                    self.createGatewayAddress()

        @self.zk_conn.DataWatch('/networks/{}/dhcp_flag'.format(self.vni))
        def watch_network_dhcp_status(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.dhcp_flag != data.decode('ascii'):
                self.dhcp_flag = ( data.decode('ascii') == 'True' )
                if self.dhcp_flag and self.this_node.router_state == 'primary':
                    self.startDHCPServer()
                elif self.this_node.router_state == 'primary':
                    self.stopDHCPServer()

        @self.zk_conn.DataWatch('/networks/{}/dhcp_start'.format(self.vni))
        def watch_network_dhcp_start(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.dhcp_start != data.decode('ascii'):
                self.dhcp_start = data.decode('ascii')

        @self.zk_conn.DataWatch('/networks/{}/dhcp_end'.format(self.vni))
        def watch_network_dhcp_end(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if data and self.dhcp_end != data.decode('ascii'):
                self.dhcp_end = data.decode('ascii')

        @self.zk_conn.ChildrenWatch('/networks/{}/dhcp_reservations'.format(self.vni))
        def watch_network_dhcp_reservations(new_reservations, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if self.dhcp_reservations != new_reservations:
                old_reservations = self.dhcp_reservations
                self.dhcp_reservations = new_reservations
                self.updateDHCPReservations(old_reservations, new_reservations)

        @self.zk_conn.ChildrenWatch('/networks/{}/firewall_rules'.format(self.vni))
        def watch_network_firewall_rules(new_rules, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            if self.firewall_rules != new_rules:
                old_rules = self.firewall_rules
                self.firewall_rules = new_rules
                self.updateFirewallRules(old_rules, new_rules)

        self.createNetwork()
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
                    '/networks/{}/dhcp_reservations/{}/ipaddr'.format(
                        self.vni,
                        reservation
                    )
                )
                entry = '{},{}'.format(reservation, ipaddr)
                outfile = open(filename, 'w')
                outfile.write(entry)
                outfile.close()

        for reservation in old_reservations_list:
            if reservation not in new_reservations_list:
                # Remove old reservation file
                filename = '{}/{}'.format(self.dnsmasq_hostsdir, reservation)
                try:
                    os.remove(filename)
                    self.dhcp_server_daemon.signal('hup')
                except:
                    pass

    def updateFirewallRules(self, old_rules_list, new_rules_list):
        for rule in new_rules_list:
            if rule not in old_rules_list:
                # Add new rule entry
                pass

        for rule in old_rules_list:
            if rule not in new_rules_list:
                pass

    def createNetwork(self):
        self.logger.out(
            'Creating VXLAN device on interface {}'.format(
                self.vni_dev
            ),
            prefix='VNI {}'.format(self.vni),
            state='o'
        )
        common.run_os_command(
            'ip link add {} type vxlan id {} dstport 4789 dev {}'.format(
                self.vxlan_nic,
                self.vni,
                self.vni_dev
            )
        )
        common.run_os_command(
            'brctl addbr {}'.format(
                self.bridge_nic
            )
        )
        common.run_os_command(
            'brctl addif {} {}'.format(
                self.bridge_nic,
                self.vxlan_nic
            )
        )
        common.run_os_command(
            'ip link set {} up'.format(
                self.vxlan_nic
            )
        )
        common.run_os_command(
            'ip link set {} up'.format(
                self.bridge_nic
            )
        )

    def createFirewall(self):
        nftables_network_rules = """# Rules for network {vxlannic}
add chain inet filter {vxlannic}-in
add chain inet filter {vxlannic}-out
add rule inet filter {vxlannic}-in counter
add rule inet filter {vxlannic}-out counter
# Jump from forward chain to this chain when matching net
add rule inet filter forward ip daddr {netaddr} counter jump {vxlannic}-in
add rule inet filter forward ip saddr {netaddr} counter jump {vxlannic}-out
# Allow ICMP traffic into the router from network
add rule inet filter input ip protocol icmp meta iifname {bridgenic} counter accept
# Allow DNS and DHCP traffic into the router from network
add rule inet filter input tcp dport 53 meta iifname {bridgenic} counter accept
add rule inet filter input udp dport 53 meta iifname {bridgenic} counter accept
add rule inet filter input udp dport 67 meta iifname {bridgenic} counter accept
# Block traffic into the router from network
add rule inet filter input meta iifname {bridgenic} counter drop
""".format(
            netaddr=self.ip_network,
            vxlannic=self.vxlan_nic,
            bridgenic=self.bridge_nic
        )
        with open(self.nftables_netconf_filename, 'w') as nfbasefile:
            nfbasefile.write(dedent(nftables_network_rules))
            open(self.nftables_update_filename, 'a').close()
        pass

    def createGatewayAddress(self):
        if self.this_node.router_state == 'primary':
            self.logger.out(
                'Creating gateway {} on interface {}'.format(
                    self.ip_gateway,
                    self.bridge_nic
                ),
                prefix='VNI {}'.format(self.vni),
                state='o'
            )
            common.run_os_command(
                'ip address add {}/{} dev {}'.format(
                    self.ip_gateway,
                    self.ip_cidrnetmask,
                    self.bridge_nic
                )
            )
            common.run_os_command(
                'arping -A -c2 -I {} {}'.format(
                    self.bridge_nic,
                    self.ip_gateway
                ),
                background=True
            )

    def startDHCPServer(self):
        if self.this_node.router_state == 'primary':
            self.logger.out(
                'Starting dnsmasq DHCP server on interface {}'.format(
                    self.bridge_nic
                ),
                prefix='VNI {}'.format(self.vni),
                state='o'
            )
            # Create the network hostsdir
            common.run_os_command(
                '/bin/mkdir --parents {}'.format(
                    self.dnsmasq_hostsdir
                )
            )
            # Recreate the environment we need for dnsmasq
            pvcd_config_file = os.environ['PVCD_CONFIG_FILE']
            dhcp_environment = {
                'DNSMASQ_BRIDGE_INTERFACE': self.bridge_nic,
                'PVCD_CONFIG_FILE': pvcd_config_file
            }
            # Define the dnsmasq config
            dhcp_configuration = [
                '--domain-needed',
                '--bogus-priv',
                '--no-hosts',
                '--filterwin2k',
                '--expand-hosts',
                '--domain-needed',
                '--domain={}'.format(self.domain),
                '--local=/{}/'.format(self.domain),
                '--auth-zone={}'.format(self.domain),
                '--auth-peer=127.0.0.1,{}'.format(self.ip_gateway),
                '--auth-sec-servers=127.0.0.1,[::1],{}'.format(self.ip_gateway),
                '--auth-soa=1,pvc@localhost,10,10',
                '--listen-address={}'.format(self.ip_gateway),
                '--bind-interfaces',
                '--leasefile-ro',
                '--dhcp-script=/usr/share/pvc/pvcd/dnsmasq-zookeeper-leases.py',
                '--dhcp-range={},{},48h'.format(self.dhcp_start, self.dhcp_end),
                '--dhcp-hostsdir={}'.format(self.dnsmasq_hostsdir),
                '--log-facility=-',
                '--log-queries=extra',
                '--keep-in-foreground'
            ]
            # Start the dnsmasq process in a thread
            self.dhcp_server_daemon = common.run_os_daemon(
                '/usr/sbin/dnsmasq {}'.format(
                    ' '.join(dhcp_configuration)
                ),
                environment=dhcp_environment,
                logfile='{}/dnsmasq-{}.log'.format(self.config['dnsmasq_log_directory'], self.vni)
            )

    def removeNetwork(self):
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
        os.remove(self.nftables_netconf_filename)
        open(self.nftables_update_filename, 'a').close()
        pass

    def removeGatewayAddress(self):
        self.logger.out(
            'Removing gateway {} from interface {}'.format(
                self.ip_gateway,
                self.bridge_nic
            ),
            prefix='VNI {}'.format(self.vni),
            state='o'
        )
        common.run_os_command(
            'ip address delete {}/{} dev {}'.format(
                self.ip_gateway,
                self.ip_cidrnetmask,
                self.bridge_nic
            )
        )

    def stopDHCPServer(self):
        if self.dhcp_server_daemon:
            self.logger.out(
                'Stopping dnsmasq DHCP server on interface {}'.format(
                    self.bridge_nic
                ),
                prefix='VNI {}'.format(self.vni),
                state='o'
            )
            self.dhcp_server_daemon.signal('int')
            time.sleep(0.2)
            self.dhcp_server_daemon.signal('term')
