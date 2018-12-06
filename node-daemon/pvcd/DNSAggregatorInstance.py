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
import threading
import dns.zone
import dns.query
import MySQLdb as mysqldb

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

        self.mysql_conn = mysqldb.connect(
            host=self.config['pdns_mysql_host'],
            port=int(self.config['pdns_mysql_port']),
            user=self.config['pdns_mysql_user'],
            passwd=self.config['pdns_mysql_password'],
            db=self.config['pdns_mysql_dbname']
        )
        self.dns_server_daemon = PowerDNSInstance(self.config, self.logger, self.dns_networks)
        self.dns_axfr_daemon = AXFRDaemonInstance(self.config, self.logger, self.mysql_conn, self.dns_networks)

    # Start up the PowerDNS instance
    def start_aggregator(self):
        self.dns_server_daemon.start()
        self.dns_axfr_daemon.start()

    # Stop the PowerDNS instance
    def stop_aggregator(self):
        self.dns_axfr_daemon.stop()
        self.dns_server_daemon.stop()

    def add_network(self, network):
        self.dns_networks[network] =  DNSNetworkInstance(self.config, self.logger, self.mysql_conn, network)
        self.dns_networks[network].add_network()
        self.dns_axfr_daemon.update_networks(self.dns_networks)

    def remove_network(self, network):
        if self.dns_networks[network]:
            self.dns_networks[network].remove_network()
            del self.dns_networks[network]
            self.dns_axfr_daemon.update_networks(self.dns_networks)

class PowerDNSInstance(object):
    # Initialization function
    def __init__(self, config, logger, dns_networks):
        self.config = config
        self.logger = logger
        self.dns_server_daemon = None

        # Floating upstreams
        self.vni_dev = self.config['vni_dev']
        self.vni_ipaddr, self.vni_cidrnetmask = self.config['vni_floating_ip'].split('/')
        self.upstream_dev = self.config['upstream_dev']
        self.upstream_ipaddr, self.upstream_cidrnetmask = self.config['upstream_floating_ip'].split('/')

    def start(self):
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
#            '--also-notify=10.101.0.60',        # Notify upstreams
            '--local-address={},{}'.format(self.vni_ipaddr, self.upstream_ipaddr),
                                                # Listen on floating IPs
            '--local-port=10053',                  # On port 10053
            '--log-dns-details=on',             # Log details
            '--loglevel=3',                     # Log info
            '--master=yes',                     # Enable master mode
            '--slave=yes',                      # Enable slave mode
            '--slave-renotify=yes',             # Renotify out for our slaved zones
            '--version-string=powerdns',        # Set the version string
            '--default-soa-name=dns.pvc.local', # Override dnsmasq's invalid name
            '--socket-dir={}'.format(self.config['pdns_dynamic_directory']),
                                                # Standard socket directory
            '--launch=gmysql',                  # Use the MySQL backend
            '--gmysql-host={}'.format(self.config['pdns_mysql_host']),
                                                # MySQL instance
            '--gmysql-port={}'.format(self.config['pdns_mysql_port']),
                                                # Default port
            '--gmysql-dbname={}'.format(self.config['pdns_mysql_dbname']),
                                                # Database name
            '--gmysql-user={}'.format(self.config['pdns_mysql_user']),
                                                # User name
            '--gmysql-password={}'.format(self.config['pdns_mysql_password']),
                                                # User password
            '--gmysql-dnssec=no',               # Do DNSSEC elsewhere
        ]
        # Start the pdns process in a thread
        self.dns_server_daemon = common.run_os_daemon(
            '/usr/sbin/pdns_server {}'.format(
                ' '.join(dns_configuration)
            ),
            environment=None,
            logfile='{}/pdns-aggregator.log'.format(self.config['pdns_log_directory'])
        )

    def stop(self):
        if self.dns_server_daemon:
            self.logger.out(
                'Stopping PowerDNS zone aggregator',
                state='o'
            )
            # Terminate, then kill
            self.dns_server_daemon.signal('term')
            time.sleep(0.2)
            self.dns_server_daemon.signal('kill')

class DNSNetworkInstance(object):
    # Initialization function
    def __init__(self, config, logger, mysql_conn, network):
        self.config = config
        self.logger = logger
        self.mysql_conn = mysql_conn
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
        mysql_curs = self.mysql_conn.cursor()
        # Try to access the domains entry
        mysql_curs.execute(
            'SELECT * FROM domains WHERE name=%s',
            (network_domain,)
        )
        results = mysql_curs.fetchone()

        # If we got back a result, don't try to add the domain to the DB
        if results:
            write_domain = False
        else:
            write_domain = True

        # Write the domain to the database
        if write_domain:
            mysql_curs.execute(
                'INSERT INTO domains (name, type, account, notified_serial) VALUES (%s, "MASTER", "internal", 0)',
                (network_domain,)
            )
            self.mysql_conn.commit()

            mysql_curs.execute(
                'SELECT id FROM domains WHERE name=%s',
                (network_domain,)
            )
            domain_id = mysql_curs.fetchone()

            mysql_curs.execute(
                """
                INSERT INTO records (domain_id, name, content, type, ttl, prio) VALUES
                (%s, %s, %s, %s, %s, %s)
                """,
                (domain_id, network_domain, 'nsX.{d} root.{d} 1 10800 1800 86400 86400'.format(d=self.config['cluster_domain']), 'SOA', 86400, 0)
            )

            ns_servers = [network_gateway, 'pvc-ns1.{}'.format(self.config['cluster_domain']), 'pvc-ns2.{}'.format(self.config['cluster_domain'])]
            for ns_server in ns_servers:
                mysql_curs.execute(
                    """
                    INSERT INTO records (domain_id, name, content, type, ttl, prio) VALUES
                    (%s, %s, %s, %s, %s, %s)
                    """,
                    (domain_id, network_domain, ns_server, 'NS', 86400, 0)
                )
            
            self.mysql_conn.commit()

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
        mysql_curs = self.mysql_conn.cursor()
        mysql_curs.execute(
            'SELECT id FROM domains WHERE name=%s',
            (network_domain,)
        )
        domain_id = mysql_curs.fetchone()

        mysql_curs.execute(
            'DELETE FROM domains WHERE id=%s',
            (domain_id,)
        )
        mysql_curs.execute(
            'DELETE FROM records WHERE domain_id=%s',
            (domain_id,)
        )

        self.mysql_conn.commit()


class AXFRDaemonInstance(object):
    # Initialization function
    def __init__(self, config, logger, mysql_conn, dns_networks):
        self.config = config
        self.logger = logger
        self.mysql_conn = mysql_conn
        self.dns_networks = dns_networks
        self.thread_stopper = threading.Event()
        self.thread = None

    def update_networks(self, dns_networks):
        self.dns_networks = dns_networks

    def start(self):
        self.thread_stopper.clear()
        self.thread = threading.Thread(target=self.run, args=(), kwargs={})
        self.thread.start() 

    def stop(self):
        self.thread_stopper.set()

    def run(self):
        # Wait for all the DNSMASQ instances to actually start
        time.sleep(2)

        while not self.thread_stopper.is_set():
            # We do this for each network
            for network, instance in self.dns_networks.items():
                zone_modified = False

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
                except OSError as e:
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
                mysql_curs = self.mysql_conn.cursor()
                mysql_curs.execute(
                    'SELECT id FROM domains WHERE name=%s',
                    (domain,)
                )
                domain_id = mysql_curs.fetchone()
                mysql_curs.execute(
                    'SELECT * FROM records WHERE domain_id=%s',
                    (domain_id,)
                )
                results = list(mysql_curs.fetchall())

                # Fix the formatting because it's useless for comparison
                # reference: ((10, 28, 'testnet01.i.bonilan.net', 'SOA', 'nsX.pvc.local root.pvc.local 1 10800 1800 86400 86400', 86400, 0, None, 0, None, 1), etc.)
                records_old = list()
                records_old_ids = list()
                for record in results:
                    # Skip the SOA and NS records
                    if record[3] == 'SOA' or record[3] == 'NS':
                        continue
                    # Assemble a list element in the same format as the AXFR data
                    entry = '{} {} IN {} {}'.format(record[2], record[5], record[3], record[4])
                    records_old.append(entry)
                    records_old_ids.append(record[0])

                records_new.sort()
                records_old.sort()

                # Find the differences between the lists
                # Basic check one: are they completely equal
                if records_new != records_old:
                    # Get set elements
                    in_new = set(records_new)
                    in_old = set(records_old)
                    in_new_not_in_old = in_new - in_old
                    in_old_not_in_new = in_old - in_new

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
                            mysql_curs = self.mysql_conn.cursor()
                            mysql_curs.execute(
                                'DELETE FROM records WHERE id=%s',
                                (record_id,)
                            )
                            changed = True

                    if len(in_new_not_in_old) > 0:
                        # Add the new records
                        for record in in_new_not_in_old:
                            # [NAME, TTL, 'IN', TYPE, DATA]
                            record = record.split()
                            rname = record[0]
                            rttl = record[1]
                            rtype = record[3]
                            rdata = record[4]
                            mysql_curs = self.mysql_conn.cursor()
                            mysql_curs.execute(
                                'INSERT INTO records (domain_id, name, ttl, type, prio, content) VALUES (%s, %s, %s, %s, %s, %s)',
                                (domain_id, rname, rttl, rtype, 0, rdata)
                            )
                            changed = True

                    if changed:
                        # Increase SOA serial
                        mysql_curs.execute(
                            'SELECT content FROM records WHERE domain_id=%s AND type="SOA"',
                            (domain_id,)
                        )
                        soa_record = list(mysql_curs.fetchone())[0].split()
                        current_serial = int(soa_record[2])
                        new_serial = current_serial + 1
                        soa_record[2] = str(new_serial)
                        mysql_curs.execute(
                            'UPDATE records SET content=%s WHERE domain_id=%s AND type="SOA"',
                            (' '.join(soa_record), domain_id)
                        )

                        # Commit all the previous changes
                        self.mysql_conn.commit()
    
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
