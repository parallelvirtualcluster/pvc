#!/usr/bin/env python3

# DNSAggregatorInstance.py - Class implementing a DNS aggregator and run by pvcd
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
import time
import sqlite3

import pvcd.log as log
import pvcd.zkhandler as zkhandler
import pvcd.common as common

# A barebones PowerDNS sqlite schema (relative to the active dir)
sql_schema_file = 'pvcd/powerdns-aggregator-schema.sql'

class DNSAggregatorInstance(object):
    # Initialization function
    def __init__(self, zk_conn, config, logger, d_network):
        self.zk_conn = zk_conn
        self.config = config
        self.logger = logger
        self.d_network = d_network

        # Floating upstreams
        self.vni_dev = self.config['vni_dev']
        self.vni_ipaddr, self.vni_cidrnetmask = self.config['vni_floating_ip'].split('/')
        self.upstream_dev = self.config['upstream_dev']
        self.upstream_ipaddr, self.upstream_cidrnetmask = self.config['upstream_floating_ip'].split('/')

        self.database_file = self.config['pdns_dynamic_directory'] + '/pdns-aggregator.sqlite3'

        self.dns_server_daemon = None

        self.prepare_db()
        
    # Preparation function
    def prepare_db(self):
        # Connect to the database
        sql_conn = sqlite3.connect(self.database_file)
        sql_curs = sql_conn.cursor()

        # Try to access the domains table
        try:
            sql_curs.execute(
                'select * from domains'
            )
            write_schema = False
        # The table doesn't exist, so we should create it
        except sqlite3.OperationalError:
            write_schema = True

        if write_schema:
            with open('{}/{}'.format(os.getcwd(), sql_schema_file), 'r') as schema_file:
                schema = ''.join(schema_file.readlines())
            sql_curs.executescript(schema)

        sql_conn.close()

    # Add a new network to the aggregator database
    def add_client_network(self, network):
        network_domain = self.d_network[network].domain
        network_gateway = self.d_network[network].ip_gateway

        self.logger.out(
            'Adding entry for client domain {}'.format(
                network_domain
            ),
            prefix='DNS aggregator',
            state='o'
        )
        # Connect to the database
        sql_conn = sqlite3.connect(self.database_file)
        sql_curs = sql_conn.cursor()
        # Try to access the domains entry
        sql_curs.execute(
            'select * from domains where name=?',
            (network_domain,)
        )
        results = sql_curs.fetchall()
        if results:
            write_domain = False
        else:
            write_domain = True

        if write_domain:
            sql_curs.execute(
                'insert into domains (name, master, type, account) values (?, ?, "MASTER", "internal")',
                (network_domain, network_gateway)
            )
            sql_conn.commit()

        sql_conn.close()

    # Remove a deleted network from the aggregator database
    def remove_client_network(self, network):
        network_domain = self.d_network[network].domain

        self.logger.out(
            'Removing entry for client domain {}'.format(
                network_domain
            ),
            prefix='DNS aggregator',
            state='o'
        )
        # Connect to the database
        sql_conn = sqlite3.connect(self.database_file)
        sql_curs = sql_conn.cursor()
        sql_curs.execute(
            'delete from domains where name=?',
            (network_domain,)
        )
        sql_conn.commit()
        sql_conn.close()

    # Force AXFR
    def get_axfr(self, network):
        self.logger.out(
            'Perform AXFR for {}'.format(
                self.d_network[network].domain
            ),
            prefix='DNS aggregator',
            state='o'
        )
        common.run_os_command(
            '/usr/bin/pdns_control --socket-dir={} retrieve {}'.format(
                self.config['pdns_dynamic_directory'],
                self.d_network[network].domain
            ),
            background=True
        )

    # Start up the PowerDNS instance
    def start_aggregator(self):
        self.logger.out(
            'Starting PowerDNS zone aggregator',
            state='o'
        )
        # Define the PowerDNS config
        dns_configuration = [
            # Option                            # Explanation
            '--no-config',
            '--daemon=no',                      # Start directly
            '--guardian=yes',                   # Use a guardian
            '--disable-syslog=yes',             # Log only to stdout (which is then captured)
            '--disable-axfr=no',                # Allow AXFRs
            '--allow-axfr-ips=0.0.0.0/0',       # Allow AXFRs to anywhere
            '--also-notify=10.101.0.60',        # Notify upstreams
            '--local-address={},{}'.format(self.vni_ipaddr, self.upstream_ipaddr),
                                                # Listen on floating IPs
            '--local-port=10053',               # On port 10053
            '--log-dns-details=on',             # Log details
            '--loglevel=3',                     # Log info
            '--master=yes',                     # Enable master mode
            '--slave=yes',                      # Enable slave mode
            '--slave-renotify=yes',             # Renotify out for our slaved zones
            '--version-string=powerdns',        # Set the version string
            '--default-soa-name=dns.pvc.local', # Override dnsmasq's invalid name
            '--socket-dir={}'.format(self.config['pdns_dynamic_directory']),
                                                # Standard socket directory
            '--launch=gsqlite3',                # Use the sqlite3 backend
            '--gsqlite3-database={}'.format(self.database_file),
                                                # Database file
            '--gsqlite3-dnssec=no'              # Don't do DNSSEC here
        ]
        # Start the pdns process in a thread
        self.dns_server_daemon = common.run_os_daemon(
            '/usr/sbin/pdns_server {}'.format(
                ' '.join(dns_configuration)
            ),
            environment=None,
            logfile='{}/pdns-aggregator.log'.format(self.config['pdns_log_directory'])
        )

    # Stop the PowerDNS instance
    def stop_aggregator(self):
        if self.dns_server_daemon:
            self.logger.out(
                'Stopping PowerDNS zone aggregator',
                state='o'
            )
            # Terminate, then kill
            self.dns_server_daemon.signal('term')
            time.sleep(0.2)
            self.dns_server_daemon.signal('kill')
