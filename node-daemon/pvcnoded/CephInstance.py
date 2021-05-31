#!/usr/bin/env python3

# CephInstance.py - Class implementing a PVC node Ceph instance
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2021 Joshua M. Boniface <joshua@boniface.me>
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

import time
import json
import psutil

import pvcnoded.common as common


class CephOSDInstance(object):
    def __init__(self, zkhandler, this_node, osd_id):
        self.zkhandler = zkhandler
        self.this_node = this_node
        self.osd_id = osd_id
        self.node = None
        self.size = None
        self.stats = dict()

        @self.zkhandler.zk_conn.DataWatch('/ceph/osds/{}/node'.format(self.osd_id))
        def watch_osd_node(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = ''

            if data and data != self.node:
                self.node = data

        @self.zkhandler.zk_conn.DataWatch('/ceph/osds/{}/stats'.format(self.osd_id))
        def watch_osd_stats(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = ''

            if data and data != self.stats:
                self.stats = json.loads(data)


def add_osd(zkhandler, logger, node, device, weight):
    # We are ready to create a new OSD on this node
    logger.out('Creating new OSD disk on block device {}'.format(device), state='i')
    try:
        # 1. Create an OSD; we do this so we know what ID will be gen'd
        retcode, stdout, stderr = common.run_os_command('ceph osd create')
        if retcode:
            print('ceph osd create')
            print(stdout)
            print(stderr)
            raise
        osd_id = stdout.rstrip()

        # 2. Remove that newly-created OSD
        retcode, stdout, stderr = common.run_os_command('ceph osd rm {}'.format(osd_id))
        if retcode:
            print('ceph osd rm')
            print(stdout)
            print(stderr)
            raise

        # 3a. Zap the disk to ensure it is ready to go
        logger.out('Zapping disk {}'.format(device), state='i')
        retcode, stdout, stderr = common.run_os_command('ceph-volume lvm zap --destroy {}'.format(device))
        if retcode:
            print('ceph-volume lvm zap')
            print(stdout)
            print(stderr)
            raise

        # 3b. Create the OSD for real
        logger.out('Preparing LVM for new OSD disk with ID {} on {}'.format(osd_id, device), state='i')
        retcode, stdout, stderr = common.run_os_command(
            'ceph-volume lvm prepare --bluestore --data {device}'.format(
                osdid=osd_id,
                device=device
            )
        )
        if retcode:
            print('ceph-volume lvm prepare')
            print(stdout)
            print(stderr)
            raise

        # 4a. Get OSD FSID
        logger.out('Getting OSD FSID for ID {} on {}'.format(osd_id, device), state='i')
        retcode, stdout, stderr = common.run_os_command(
            'ceph-volume lvm list {device}'.format(
                osdid=osd_id,
                device=device
            )
        )
        for line in stdout.split('\n'):
            if 'osd fsid' in line:
                osd_fsid = line.split()[-1]

        if not osd_fsid:
            print('ceph-volume lvm list')
            print('Could not find OSD fsid in data:')
            print(stdout)
            print(stderr)
            raise

        # 4b. Activate the OSD
        logger.out('Activating new OSD disk with ID {}'.format(osd_id, device), state='i')
        retcode, stdout, stderr = common.run_os_command(
            'ceph-volume lvm activate --bluestore {osdid} {osdfsid}'.format(
                osdid=osd_id,
                osdfsid=osd_fsid
            )
        )
        if retcode:
            print('ceph-volume lvm activate')
            print(stdout)
            print(stderr)
            raise

        # 5. Add it to the crush map
        logger.out('Adding new OSD disk with ID {} to CRUSH map'.format(osd_id), state='i')
        retcode, stdout, stderr = common.run_os_command(
            'ceph osd crush add osd.{osdid} {weight} root=default host={node}'.format(
                osdid=osd_id,
                weight=weight,
                node=node
            )
        )
        if retcode:
            print('ceph osd crush add')
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
        if retcode:
            print('systemctl status')
            print(stdout)
            print(stderr)
            raise

        # 7. Add the new OSD to the list
        logger.out('Adding new OSD disk with ID {} to Zookeeper'.format(osd_id), state='i')
        zkhandler.write([
            ('/ceph/osds/{}'.format(osd_id), ''),
            ('/ceph/osds/{}/node'.format(osd_id), node),
            ('/ceph/osds/{}/device'.format(osd_id), device),
            ('/ceph/osds/{}/stats'.format(osd_id), '{}')
        ])

        # Log it
        logger.out('Created new OSD disk with ID {}'.format(osd_id), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to create new OSD disk: {}'.format(e), state='e')
        return False


def remove_osd(zkhandler, logger, osd_id, osd_obj):
    logger.out('Removing OSD disk {}'.format(osd_id), state='i')
    try:
        # 1. Verify the OSD is present
        retcode, stdout, stderr = common.run_os_command('ceph osd ls')
        osd_list = stdout.split('\n')
        if osd_id not in osd_list:
            logger.out('Could not find OSD {} in the cluster'.format(osd_id), state='e')
            return True

        # 1. Set the OSD out so it will flush
        logger.out('Setting out OSD disk with ID {}'.format(osd_id), state='i')
        retcode, stdout, stderr = common.run_os_command('ceph osd out {}'.format(osd_id))
        if retcode:
            print('ceph osd out')
            print(stdout)
            print(stderr)
            raise

        # 2. Wait for the OSD to flush
        logger.out('Flushing OSD disk with ID {}'.format(osd_id), state='i')
        osd_string = str()
        while True:
            try:
                retcode, stdout, stderr = common.run_os_command('ceph pg dump osds --format json')
                dump_string = json.loads(stdout)
                for osd in dump_string:
                    if str(osd['osd']) == osd_id:
                        osd_string = osd
                num_pgs = osd_string['num_pgs']
                if num_pgs > 0:
                    time.sleep(5)
                else:
                    raise
            except Exception:
                break

        # 3. Stop the OSD process and wait for it to be terminated
        logger.out('Stopping OSD disk with ID {}'.format(osd_id), state='i')
        retcode, stdout, stderr = common.run_os_command('systemctl stop ceph-osd@{}'.format(osd_id))
        if retcode:
            print('systemctl stop')
            print(stdout)
            print(stderr)
            raise

        # FIXME: There has to be a better way to do this /shrug
        while True:
            is_osd_up = False
            # Find if there is a process named ceph-osd with arg '--id {id}'
            for p in psutil.process_iter(attrs=['name', 'cmdline']):
                if 'ceph-osd' == p.info['name'] and '--id {}'.format(osd_id) in ' '.join(p.info['cmdline']):
                    is_osd_up = True
            # If there isn't, continue
            if not is_osd_up:
                break

        # 4. Determine the block devices
        retcode, stdout, stderr = common.run_os_command('readlink /var/lib/ceph/osd/ceph-{}/block'.format(osd_id))
        vg_name = stdout.split('/')[-2]  # e.g. /dev/ceph-<uuid>/osd-block-<uuid>
        retcode, stdout, stderr = common.run_os_command('vgs --separator , --noheadings -o pv_name {}'.format(vg_name))
        pv_block = stdout.strip()

        # 5. Zap the volumes
        logger.out('Zapping OSD disk with ID {} on {}'.format(osd_id, pv_block), state='i')
        retcode, stdout, stderr = common.run_os_command('ceph-volume lvm zap --destroy {}'.format(pv_block))
        if retcode:
            print('ceph-volume lvm zap')
            print(stdout)
            print(stderr)
            raise

        # 6. Purge the OSD from Ceph
        logger.out('Purging OSD disk with ID {}'.format(osd_id), state='i')
        retcode, stdout, stderr = common.run_os_command('ceph osd purge {} --yes-i-really-mean-it'.format(osd_id))
        if retcode:
            print('ceph osd purge')
            print(stdout)
            print(stderr)
            raise

        # 7. Delete OSD from ZK
        logger.out('Deleting OSD disk with ID {} from Zookeeper'.format(osd_id), state='i')
        zkhandler.delete('/ceph/osds/{}'.format(osd_id), recursive=True)

        # Log it
        logger.out('Removed OSD disk with ID {}'.format(osd_id), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to purge OSD disk with ID {}: {}'.format(osd_id, e), state='e')
        return False


class CephPoolInstance(object):
    def __init__(self, zkhandler, this_node, name):
        self.zkhandler = zkhandler
        self.this_node = this_node
        self.name = name
        self.pgs = ''
        self.stats = dict()

        @self.zkhandler.zk_conn.DataWatch('/ceph/pools/{}/pgs'.format(self.name))
        def watch_pool_node(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = ''

            if data and data != self.pgs:
                self.pgs = data

        @self.zkhandler.zk_conn.DataWatch('/ceph/pools/{}/stats'.format(self.name))
        def watch_pool_stats(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = ''

            if data and data != self.stats:
                self.stats = json.loads(data)


class CephVolumeInstance(object):
    def __init__(self, zkhandler, this_node, pool, name):
        self.zkhandler = zkhandler
        self.this_node = this_node
        self.pool = pool
        self.name = name
        self.stats = dict()

        @self.zkhandler.zk_conn.DataWatch('/ceph/volumes/{}/{}/stats'.format(self.pool, self.name))
        def watch_volume_stats(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = ''

            if data and data != self.stats:
                self.stats = json.loads(data)


class CephSnapshotInstance(object):
    def __init__(self, zkhandler, this_node, pool, volume, name):
        self.zkhandler = zkhandler
        self.this_node = this_node
        self.pool = pool
        self.volume = volume
        self.name = name
        self.stats = dict()

        @self.zkhandler.zk_conn.DataWatch('/ceph/snapshots/{}/{}/{}/stats'.format(self.pool, self.volume, self.name))
        def watch_snapshot_stats(data, stat, event=''):
            if event and event.type == 'DELETED':
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode('ascii')
            except AttributeError:
                data = ''

            if data and data != self.stats:
                self.stats = json.loads(data)


# Primary command function
# This command pipe is only used for OSD adds and removes
def run_command(zkhandler, logger, this_node, data, d_osd):
    # Get the command and args
    command, args = data.split()

    # Adding a new OSD
    if command == 'osd_add':
        node, device, weight = args.split(',')
        if node == this_node.name:
            # Lock the command queue
            zk_lock = zkhandler.writelock('/cmd/ceph')
            with zk_lock:
                # Add the OSD
                result = add_osd(zkhandler, logger, node, device, weight)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.write([
                        ('/cmd/ceph', 'success-{}'.format(data))
                    ])
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.write([
                        ('/cmd/ceph', 'failure-{}'.format(data))
                    ])
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Removing an OSD
    elif command == 'osd_remove':
        osd_id = args

        # Verify osd_id is in the list
        if d_osd[osd_id] and d_osd[osd_id].node == this_node.name:
            # Lock the command queue
            zk_lock = zkhandler.writelock('/cmd/ceph')
            with zk_lock:
                # Remove the OSD
                result = remove_osd(zkhandler, logger, osd_id, d_osd[osd_id])
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.write([
                        ('/cmd/ceph', 'success-{}'.format(data))
                    ])
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.write([
                        ('/cmd/ceph', 'failure-{}'.format(data))
                    ])
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)
