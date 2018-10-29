#!/usr/bin/env python3

# CehpInstance.py - Class implementing a PVC node Ceph instance
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

import time
import ast

import pvcd.log as log
import pvcd.zkhandler as zkhandler
import pvcd.fencing as fencing
import pvcd.common as common

class CephInstance(object):
    def __init__(self):
        pass

class CephOSDInstance(object):
    def __init__(self, zk_conn, this_node, osd_id):
        self.zk_conn = zk_conn
        self.this_node = this_node
        self.osd_id = osd_id
        self.node = None
        self.size = None
        self.stats = dict()

        @self.zk_conn.DataWatch('/ceph/osds/{}/node'.format(self.osd_id))
        def watch_osd_host(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = ''

            if data != self.node:
                self.node = data

        @self.zk_conn.DataWatch('/ceph/osds/{}/size'.format(self.osd_id))
        def watch_osd_host(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = ''

            if data != self.size:
                self.size = data

        @self.zk_conn.DataWatch('/ceph/osds/{}/stats'.format(self.osd_id))
        def watch_osd_host(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = ''

            if data != self.stats:
                self.stats.update(ast.literal_eval(data))

def add_osd(zk_conn, logger, node, device):
    # We are ready to create a new OSD on this host
    logger.out('Creating new OSD disk', state='i')
    try:
        # 1. Create an OSD; we do this so we know what ID will be gen'd
        retcode, stdout, stderr = common.run_os_command('ceph osd create')
        if retcode != 0:
            print(stdout)
            print(stderr)
            raise
        osd_id = stdout.rstrip()

        # 2. Remove that newly-created OSD
        retcode, stdout, stderr = common.run_os_command('ceph osd rm {}'.format(osd_id))
        if retcode != 0:
            print(stdout)
            print(stderr)
            raise

        # 3. Create the OSD for real
        retcode, stdout, stderr = common.run_os_command(
            'ceph-volume lvm prepare --bluestore --data {device}'.format(
                osdid=osd_id,
                device=device
            )
        )
        if retcode != 0:
            print(stdout)
            print(stderr)
            raise

        # 4. Activate the OSD
        retcode, stdout, stderr = common.run_os_command(
            'ceph-volume lvm activate --bluestore {osdid}'.format(
                osdid=osd_id
            )
        )
        if retcode != 0:
            print(stdout)
            print(stderr)
            raise

        # 5. Add it to the crush map
        retcode, stdout, stderr = common.run_os_command(
            'ceph osd crush add osd.{osdid} 1.0 root=default host={node}'.format(
                osdid=osd_id,
                node=node
            )
        )
        if retcode != 0:
            print(stdout)
            print(stderr)
            raise
        time.sleep(0.5)

        # 6. Verify it started
        retcode, stdout, stderr = common.run_os_command(
            'systemctl status ceph-osd@{osdid}'.format(
                osdid=osd_id
            )
        )
        if retcode != 0:
            print(stdout)
            print(stderr)
            raise

        # 7. Add the new OSD to the list
        zkhandler.writedata(zk_conn, {
            '/ceph/osds/{}'.format(osd_id): '',
            '/ceph/osds/{}/node'.format(osd_id): node,
            '/ceph/osds/{}/size'.format(osd_id): '',
            '/ceph/osds/{}/stats'.format(osd_id): '{}'
        })

        # Log it
        logger.out('Created new OSD disk with ID {}'.format(osd_id), state='o')
    except Exception as e:
        # Log it
        logger.out('Failed to create new OSD disk: {}'.format(e), state='e')

def remove_osd(zk_conn, logger, osd_id, osd_obj):
    logger.out('Removing OSD disk {}'.format(osd_id), state='i')
    try:
        # 1. Verify the OSD is present
        retcode, stdout, stderr = common.run_os_command('ceph osd ls')
        osd_list = stdout.split('\n')
        if not osd_id in osd_list:
            logger.out('Could not find OSD {} in the cluster'.format(osd_id), state='e')
            return True
            
        # 1. Set the OSD out so it will flush
        retcode, stdout, stderr = common.run_os_command('ceph osd out {}'.format(osd_id))
        if retcode != 0:
            print(stdout)
            print(stderr)
        
        # 2. Wait for the OSD to flush
        while True:
            retcode, stdout, stderr = common.run_os_command('ceph health')
            health_string = stdout
    except:
        pass

class CephPool(object):
    def __init__(self):
        pass
