#!/usr/bin/env python3

# DNSAggregatorInstance.py - Class implementing a DNS aggregator and run by pvcd
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
import sys
import time
import threading
import dns.zone
import dns.query
import psycopg2

import pvcd.log as log
import pvcd.zkhandler as zkhandler
import pvcd.common as common

class DNSAggregatorInstance(object):
    # Initialization function
    def __init__(self, zk_conn, config, logger):
        self.zk_conn = zk_conn
        self.config = config
        self.logger = logger
        self.dns_networks = dict()
        self.is_active = False

        self.dns_server_daemon = PowerDNSInstance(self)
        self.dns_axfr_daemon = AXFRDaemonInstance(self)

    # Start up the PowerDNS instance
    def start_aggregator(self):
        # Restart the SQL connection
        self.dns_server_daemon.start()
        self.dns_axfr_daemon.start()
        self.is_active = True

    # Stop the PowerDNS instance
    def stop_aggregator(self):
        self.is_active = False
        self.dns_axfr_daemon.stop()
        self.dns_server_daemon.stop()

    def add_network(self, network):
        self.dns_networks[network] = DNSNetworkInstance(self, network)
        self.dns_networks[network].add_network()
        self.dns_axfr_daemon.update_networks(self.dns_networks)

    def remove_network(self, network):
        if self.dns_networks[network]:
            self.dns_networks[network].remove_network()
            del self.dns_networks[network]
            self.dns_axfr_daemon.update_networks(self.dns_networks)

class PowerDNSInstance(object):
    # Initialization function
    def __init__(self, aggregator):
        self.aggregator = aggregator
        self.config = self.aggregator.config
        self.logger = self.aggregator.logger
        self.dns_server_daemon = None

        # Floating upstreams
        self.vni_ipaddr, self.vni_cidrnetmask = self.config['vni_floating_ip'].split('/')
        self.upstream_ipaddr, self.upstream_cidrnetmask = self.config['upstream_floating_ip'].split('/')

    def start(self):
        self.logger.out(
            'Starting PowerDNS zone aggregator',
            state='i'
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
            '--local-address={},{}'.format(self.vni_ipaddr, self.upstream_ipaddr),
                                                # Listen on floating IPs
            '--local-port=53',                  # On port 53
            '--log-dns-details=on',             # Log details
            '--loglevel=3',                     # Log info
            '--master=yes',                     # Enable master mode
            '--slave=yes',                      # Enable slave mode
            '--slave-renotify=yes',             # Renotify out for our slaved zones
            '--version-string=powerdns',        # Set the version string
            '--default-soa-name=dns.pvc.local', # Override dnsmasq's invalid name
            '--socket-dir={}'.format(self.config['pdns_dynamic_directory']),
                                                # Standard socket directory
            '--launch=gpgsql',                  # Use the PostgreSQL backend
            '--gpgsql-host={}'.format(self.config['pdns_postgresql_host']),
                                                # PostgreSQL instance
            '--gpgsql-port={}'.format(self.config['pdns_postgresql_port']),
                                                # Default port
            '--gpgsql-dbname={}'.format(self.config['pdns_postgresql_dbname']),
                                                # Database name
            '--gpgsql-user={}'.format(self.config['pdns_postgresql_user']),
                                                # User name
            '--gpgsql-password={}'.format(self.config['pdns_postgresql_password']),
                                                # User password
            '--gpgsql-dnssec=no',               # Do DNSSEC elsewhere
        ]
        # Start the pdns process in a thread
        self.dns_server_daemon = common.run_os_daemon(
            '/usr/sbin/pdns_server {}'.format(
                ' '.join(dns_configuration)
            ),
            environment=None,
            logfile='{}/pdns-aggregator.log'.format(self.config['pdns_log_directory'])
        )
        if self.dns_server_daemon:
            self.logger.out(
                'Successfully started PowerDNS zone aggregator',
                state='o'
            )


    def stop(self):
        if self.dns_server_daemon:
            self.logger.out(
                'Stopping PowerDNS zone aggregator',
                state='i'
            )
            # Terminate, then kill
            self.dns_server_daemon.signal('term')
            time.sleep(0.2)
            self.dns_server_daemon.signal('kill')
            self.logger.out(
                'Successfully stopped PowerDNS zone aggregator',
                state='o'
            )

class DNSNetworkInstance(object):
    # Initialization function
    def __init__(self, aggregator, network):
        self.aggregator = aggregator
        self.config = self.aggregator.config
        self.logger = self.aggregator.logger
        self.sql_conn = None
        self.network = network

    # Add a new network to the aggregator database
    def add_network(self):
        network_domain = self.network.domain
        if self.network.ip4_gateway != 'None':
            network_gateway = self.network.ip4_gateway
        else:
            network_gateway = self.network.ip6_gateway

        self.logger.out(
            'Adding entry for client domain {}'.format(
                network_domain
            ),
            prefix='DNS aggregator',
            state='o'
        )

        # Connect to the database
        self.sql_conn = psycopg2.connect(
            "host='{}' port='{}' dbname='{}' user='{}' password='{}' sslmode='disable'".format(
               self.config['pdns_postgresql_host'],
               self.config['pdns_postgresql_port'],
               self.config['pdns_postgresql_dbname'],
               self.config['pdns_postgresql_user'],
               self.config['pdns_postgresql_password']
            )
        )
        sql_curs = self.sql_conn.cursor()
        # Try to access the domains entry
        sql_curs.execute(
            "SELECT * FROM domains WHERE name=%s",
            (network_domain,)
        )
        results = sql_curs.fetchone()

        # If we got back a result, don't try to add the domain to the DB
        if results:
            write_domain = False
        else:
            write_domain = True

        # Write the domain to the database if we're active
        if self.aggregator.is_active and write_domain:
            sql_curs.execute(
                "INSERT INTO domains (name, type, account, notified_serial) VALUES (%s, 'MASTER', 'internal', 0)",
                (network_domain,)
            )
            self.sql_conn.commit()

            sql_curs.execute(
                "SELECT id FROM domains WHERE name=%s",
                (network_domain,)
            )
            domain_id = sql_curs.fetchone()

            sql_curs.execute(
                """
                INSERT INTO records (domain_id, name, content, type, ttl, prio) VALUES
                (%s, %s, %s, %s, %s, %s)
                """,
                (domain_id, network_domain, 'nsX.{d} root.{d} 1 10800 1800 86400 86400'.format(d=self.config['upstream_domain']), 'SOA', 86400, 0)
            )

            if self.network.name_servers:
                ns_servers = self.network.name_servers
            else:
                ns_servers = ['pvc-dns.{}'.format(self.config['upstream_domain'])]

            for ns_server in ns_servers:
                sql_curs.execute(
                    """
                    INSERT INTO records (domain_id, name, content, type, ttl, prio) VALUES
                    (%s, %s, %s, %s, %s, %s)
                    """,
                    (domain_id, network_domain, ns_server, 'NS', 86400, 0)
                )

        self.sql_conn.commit()
        self.sql_conn.close()
        self.sql_conn = None

    # Remove a deleted network from the aggregator database
    def remove_network(self):
        network_domain = self.network.domain

        self.logger.out(
            'Removing entry for client domain {}'.format(
                network_domain
            ),
            prefix='DNS aggregator',
            state='o'
        )

        # Connect to the database
        self.sql_conn = psycopg2.connect(
            "host='{}' port='{}' dbname='{}' user='{}' password='{}' sslmode='disable'".format(
               self.config['pdns_postgresql_host'],
               self.config['pdns_postgresql_port'],
               self.config['pdns_postgresql_dbname'],
               self.config['pdns_postgresql_user'],
               self.config['pdns_postgresql_password']
            )
        )
        sql_curs = self.sql_conn.cursor()

        # Get the domain ID
        sql_curs.execute(
            "SELECT id FROM domains WHERE name=%s",
            (network_domain,)
        )
        domain_id = sql_curs.fetchone()

        # Delete the domain from the database if we're active
        if self.aggregator.is_active and domain_id:
            sql_curs.execute(
                "DELETE FROM domains WHERE id=%s",
                (domain_id,)
            )
            sql_curs.execute(
                "DELETE FROM records WHERE domain_id=%s",
                (domain_id,)
            )

        self.sql_conn.commit()
        self.sql_conn.close()
        self.sql_conn = None


class AXFRDaemonInstance(object):
    # Initialization function
    def __init__(self, aggregator):
        self.aggregator = aggregator
        self.config = self.aggregator.config
        self.logger = self.aggregator.logger
        self.dns_networks = self.aggregator.dns_networks
        self.thread_stopper = threading.Event()
        self.thread = None
        self.sql_conn = None

    def update_networks(self, dns_networks):
        self.dns_networks = dns_networks

    def start(self):
        # Create the thread
        self.thread_stopper.clear()
        self.thread = threading.Thread(target=self.run, args=(), kwargs={})

        # Start a local instance of the SQL connection
        # Trying to use the instance from the main DNS Aggregator can result in connection failures
        # after the leader transitions
        self.sql_conn = psycopg2.connect(
            "host='{}' port='{}' dbname='{}' user='{}' password='{}' sslmode='disable'".format(
               self.config['pdns_postgresql_host'],
               self.config['pdns_postgresql_port'],
               self.config['pdns_postgresql_dbname'],
               self.config['pdns_postgresql_user'],
               self.config['pdns_postgresql_password']
            )
        )

        # Start the thread
        self.thread.start() 

    def stop(self):
        self.thread_stopper.set()
        if self.sql_conn:
            self.sql_conn.close()
            self.sql_conn = None

    def run(self):
        # Wait for all the DNSMASQ instances to actually start
        time.sleep(5)

        while not self.thread_stopper.is_set():
            # We do this for each network
            for network, instance in self.dns_networks.items():
                zone_modified = False

                # Set up our SQL cursor
                sql_curs = self.sql_conn.cursor()

                # Set up our basic variables
                domain = network.domain
                if network.ip4_gateway != 'None':
                    dnsmasq_ip = network.ip4_gateway
                else:
                    dnsmasq_ip = network.ip6_gateway

                #
                # Get an AXFR from the dnsmasq instance and list of records
                #
                try:
                    axfr = dns.query.xfr(dnsmasq_ip, domain, lifetime=5.0)
                    z = dns.zone.from_xfr(axfr)
                    records_raw = [z[n].to_text(n) for n in z.nodes.keys()]
                except Exception as e:
                    if self.config['debug']:
                        print('{} {} ({})'.format(e, dnsmasq_ip, domain))
                    continue

                # Fix the formatting because it's useless
                # reference: ['@ 600 IN SOA . . 4 1200 180 1209600 600\n@ 600 IN NS .', 'test3 600 IN A 10.1.1.203\ntest3 600 IN AAAA 2001:b23e:1113:0:5054:ff:fe5c:f131', etc.]
                # We don't really care about dnsmasq's terrible SOA or NS records which are in [0]
                string_records = '\n'.join(records_raw[1:])
                # Split into individual records
                records_new = list()
                for element in string_records.split('\n'):
                    if element:
                        record = element.split()
                        # Handle space-containing data elements
                        if domain not in record[0]:
                            name = '{}.{}'.format(record[0], domain)
                        else:
                            name = record[0]
                        entry = '{} {} IN {} {}'.format(name, record[1], record[3], ' '.join(record[4:]))
                        records_new.append(entry)

                #
                # Get the current zone from the database
                #
                try:
                    sql_curs.execute(
                        "SELECT id FROM domains WHERE name=%s",
                        (domain,)
                    )
                    domain_id = sql_curs.fetchone()
                    sql_curs.execute(
                        "SELECT * FROM records WHERE domain_id=%s",
                        (domain_id,)
                    )
                    results = list(sql_curs.fetchall())
                    if self.config['debug']:
                        print('SQL query results: {}'.format(results))
                except Exception as e:
                    self.logger.out('ERROR: Failed to obtain DNS records from database: {}'.format(e))

                # Fix the formatting because it's useless for comparison
                # reference: ((10, 28, 'testnet01.i.bonilan.net', 'SOA', 'nsX.pvc.local root.pvc.local 1 10800 1800 86400 86400', 86400, 0, None, 0, None, 1), etc.)
                records_old = list()
                records_old_ids = list()
                if not results:
                    if self.config['debug']:
                        print('No results found, skipping.')
                    continue
                for record in results:
                    # Skip the non-A
                    r_id = record[0]
                    r_name = record[2]
                    r_ttl = record[5]
                    r_type = record[3]
                    r_data = record[4]
                    # Assemble a list element in the same format as the AXFR data
                    entry = '{} {} IN {} {}'.format(r_name, r_ttl, r_type, r_data)
                    if self.config['debug']:
                        print('Found record: {}'.format(entry))

                    # Skip non-A or AAAA records
                    if r_type != 'A' and r_type != 'AAAA':
                        if self.config['debug']:
                            print('Skipping record {}, not A or AAAA: "{}"'.format(entry, r_type))
                        continue

                    records_old.append(entry)
                    records_old_ids.append(r_id)

                records_new.sort()
                records_old.sort()

                if self.config['debug']:
                    print('New: {}'.format(records_new))
                    print('Old: {}'.format(records_old))

                # Find the differences between the lists
                # Basic check one: are they completely equal
                if records_new != records_old:
                    # Get set elements
                    in_new = set(records_new)
                    in_old = set(records_old)
                    in_new_not_in_old = in_new - in_old
                    in_old_not_in_new = in_old - in_new

                    if self.config['debug']:
                        print('New but not old: {}'.format(in_new_not_in_old))
                        print('Old but not new: {}'.format(in_old_not_in_new))

                    # Go through the old list
                    remove_records = list() # list of database IDs
                    for i in range(len(records_old)):
                        record_id = records_old_ids[i]
                        record = records_old[i]
                        splitrecord = records_old[i].split()

                        # If the record is not in the new list, remove it
                        if record in in_old_not_in_new:
                            remove_records.append(record_id)

                        # Go through the new elements
                        for newrecord in in_new_not_in_old:
                            splitnewrecord = newrecord.split()
                            # If there's a name and type match with different content, remove the old one
                            if splitrecord[0] == splitnewrecord[0] and splitrecord[3] == splitnewrecord[3]:
                                remove_records.append(record_id)

                    changed = False
                    if len(remove_records) > 0:
                        # Remove the invalid old records
                        for record_id in remove_records:
                            if self.config['debug']:
                                print('Removing record: {}'.format(record_id))
                            sql_curs.execute(
                                "DELETE FROM records WHERE id=%s",
                                (record_id,)
                            )
                            changed = True

                    if len(in_new_not_in_old) > 0:
                        # Add the new records
                        for record in in_new_not_in_old:
                            # [NAME, TTL, 'IN', TYPE, DATA]
                            record = record.split()
                            r_name = record[0]
                            r_ttl = record[1]
                            r_type = record[3]
                            r_data = record[4]
                            if self.config['debug']:
                                print('Add record: {}'.format(name))
                            try:
                                sql_curs.execute(
                                    "INSERT INTO records (domain_id, name, ttl, type, prio, content) VALUES (%s, %s, %s, %s, %s, %s)",
                                    (domain_id, r_name, r_ttl, r_type, 0, r_data)
                                )
                                changed = True
                            except psycopg2.IntegrityError as e:
                                if self.config['debug']:
                                    print('Failed to add record due to {}: {}'.format(e, name))

                    if changed:
                        # Increase SOA serial
                        sql_curs.execute(
                            "SELECT content FROM records WHERE domain_id=%s AND type='SOA'",
                            (domain_id,)
                        )
                        soa_record = list(sql_curs.fetchone())[0].split()
                        current_serial = int(soa_record[2])
                        new_serial = current_serial + 1
                        soa_record[2] = str(new_serial)
                        if self.config['debug']:
                            print('Records changed; bumping SOA: {}'.format(new_serial))
                        sql_curs.execute(
                            "UPDATE records SET content=%s WHERE domain_id=%s AND type='SOA'",
                            (' '.join(soa_record), domain_id)
                        )

                        # Commit all the previous changes
                        if self.config['debug']:
                            print('Committing database changes and reloading PDNS')
                        try:
                            self.sql_conn.commit()
                        except Exception as e:
                            self.logger.out('ERROR: Failed to commit DNS aggregator changes: {}'.format(e), state='e')

                        # Reload the domain
                        common.run_os_command(
                            '/usr/bin/pdns_control --socket-dir={} reload {}'.format(
                                self.config['pdns_dynamic_directory'],
                                domain
                            ),
                            background=False
                        )

            # Wait for 10 seconds
            time.sleep(10)
