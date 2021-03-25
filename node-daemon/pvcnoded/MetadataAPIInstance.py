#!/usr/bin/env python3

# MetadataAPIInstance.py - Class implementing an EC2-compatible cloud-init Metadata server
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2020 Joshua M. Boniface <joshua@boniface.me>
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

import gevent.pywsgi
import flask
import sys
import time
import psycopg2

from threading import Thread
from psycopg2.extras import RealDictCursor

import daemon_lib.vm as pvc_vm
import daemon_lib.network as pvc_network


class MetadataAPIInstance(object):
    mdapi = flask.Flask(__name__)

    # Initialization function
    def __init__(self, zk_conn, config, logger):
        self.zk_conn = zk_conn
        self.config = config
        self.logger = logger
        self.thread = None
        self.md_http_server = None
        self.add_routes()

    # Add flask routes inside our instance
    def add_routes(self):
        @self.mdapi.route('/', methods=['GET'])
        def api_root():
            return flask.jsonify({"message": "PVC Provisioner Metadata API version 1"}), 209

        @self.mdapi.route('/<version>/meta-data/', methods=['GET'])
        def api_metadata_root(version):
            metadata = """instance-id\nname\nprofile"""
            return metadata, 200

        @self.mdapi.route('/<version>/meta-data/instance-id', methods=['GET'])
        def api_metadata_instanceid(version):
            source_address = flask.request.__dict__['environ']['REMOTE_ADDR']
            vm_details = self.get_vm_details(source_address)
            instance_id = vm_details.get('uuid', None)
            return instance_id, 200

        @self.mdapi.route('/<version>/meta-data/name', methods=['GET'])
        def api_metadata_hostname(version):
            source_address = flask.request.__dict__['environ']['REMOTE_ADDR']
            vm_details = self.get_vm_details(source_address)
            vm_name = vm_details.get('name', None)
            return vm_name, 200

        @self.mdapi.route('/<version>/meta-data/profile', methods=['GET'])
        def api_metadata_profile(version):
            source_address = flask.request.__dict__['environ']['REMOTE_ADDR']
            vm_details = self.get_vm_details(source_address)
            vm_profile = vm_details.get('profile', None)
            return vm_profile, 200

        @self.mdapi.route('/<version>/user-data', methods=['GET'])
        def api_userdata(version):
            source_address = flask.request.__dict__['environ']['REMOTE_ADDR']
            vm_details = self.get_vm_details(source_address)
            vm_profile = vm_details.get('profile', None)
            # Get the userdata
            if vm_profile:
                userdata = self.get_profile_userdata(vm_profile)
                self.logger.out("Returning userdata for profile {}".format(vm_profile), state='i', prefix='Metadata API')
            else:
                userdata = None
            return flask.Response(userdata)

    def launch_wsgi(self):
        try:
            self.md_http_server = gevent.pywsgi.WSGIServer(
                ('169.254.169.254', 80),
                self.mdapi,
                log=sys.stdout,
                error_log=sys.stdout
            )
            self.md_http_server.serve_forever()
        except Exception as e:
            self.logger.out('Error starting Metadata API: {}'.format(e), state='e')

    # WSGI start/stop
    def start(self):
        # Launch Metadata API
        self.logger.out('Starting Metadata API at 169.254.169.254:80', state='i')
        self.thread = Thread(target=self.launch_wsgi)
        self.thread.start()
        self.logger.out('Successfully started Metadata API thread', state='o')

    def stop(self):
        if not self.md_http_server:
            return

        self.logger.out('Stopping Metadata API at 169.254.169.254:80', state='i')
        try:
            self.md_http_server.stop()
            time.sleep(0.1)
            self.md_http_server.close()
            time.sleep(0.1)
            self.md_http_server = None
            self.logger.out('Successfully stopped Metadata API', state='o')
        except Exception as e:
            self.logger.out('Error stopping Metadata API: {}'.format(e), state='e')

    # Helper functions
    def open_database(self):
        conn = psycopg2.connect(
            host=self.config['metadata_postgresql_host'],
            port=self.config['metadata_postgresql_port'],
            dbname=self.config['metadata_postgresql_dbname'],
            user=self.config['metadata_postgresql_user'],
            password=self.config['metadata_postgresql_password']
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)
        return conn, cur

    def close_database(self, conn, cur):
        cur.close()
        conn.close()

    # Obtain a list of templates
    def get_profile_userdata(self, vm_profile):
        query = """SELECT userdata.userdata FROM profile
        JOIN userdata ON profile.userdata = userdata.id
        WHERE profile.name = %s;
        """
        args = (vm_profile,)

        conn, cur = self.open_database()
        cur.execute(query, args)
        data_raw = cur.fetchone()
        self.close_database(conn, cur)
        data = data_raw.get('userdata', None)
        return data

    # VM details function
    def get_vm_details(self, source_address):
        # Start connection to Zookeeper
        _discard, networks = pvc_network.get_list(self.zk_conn, None)

        # Figure out which server this is via the DHCP address
        host_information = dict()
        networks_managed = (x for x in networks if x.get('type') == 'managed')
        for network in networks_managed:
            network_leases = pvc_network.getNetworkDHCPLeases(self.zk_conn, network.get('vni'))
            for network_lease in network_leases:
                information = pvc_network.getDHCPLeaseInformation(self.zk_conn, network.get('vni'), network_lease)
                try:
                    if information.get('ip4_address', None) == source_address:
                        host_information = information
                except Exception:
                    pass

        # Get our real information on the host; now we can start querying about it
        client_macaddr = host_information.get('mac_address', None)

        # Find the VM with that MAC address - we can't assume that the hostname is actually right
        _discard, vm_list = pvc_vm.get_list(self.zk_conn, None, None, None)
        vm_details = dict()
        for vm in vm_list:
            try:
                for network in vm.get('networks'):
                    if network.get('mac', None) == client_macaddr:
                        vm_details = vm
            except Exception:
                pass

        return vm_details
