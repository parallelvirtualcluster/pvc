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
import json
import psutil

import pvcd.log as log
import pvcd.zkhandler as zkhandler
import pvcd.common as common

class CephOSDInstance(object):
    def __init__(self, zk_conn, this_node, osd_id):
        self.zk_conn = zk_conn
        self.this_node = this_node
        self.osd_id = osd_id
        self.node = None
        self.size = None
        self.stats = dict()

        @self.zk_conn.DataWatch('/ceph/osds/{}/node'.format(self.osd_id))
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

        @self.zk_conn.DataWatch('/ceph/osds/{}/stats'.format(self.osd_id))
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

def add_osd(zk_conn, logger, node, device, weight):
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
        zkhandler.writedata(zk_conn, {
            '/ceph/osds/{}'.format(osd_id): '',
            '/ceph/osds/{}/node'.format(osd_id): node,
            '/ceph/osds/{}/device'.format(osd_id): device,
            '/ceph/osds/{}/stats'.format(osd_id): '{}'
        })

        # Log it
        logger.out('Created new OSD disk with ID {}'.format(osd_id), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to create new OSD disk: {}'.format(e), state='e')
        return False

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
            retcode, stdout, stderr = common.run_os_command('ceph pg dump osds --format json')
            dump_string = json.loads(stdout)
            for osd in dump_string:
                if str(osd['osd']) == osd_id:
                    osd_string = osd
            num_pgs = osd_string['num_pgs']
            if num_pgs > 0:
               time.sleep(5)
            else:
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
        vg_name = stdout.split('/')[-2] # e.g. /dev/ceph-<uuid>/osd-block-<uuid>
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
        zkhandler.deletekey(zk_conn, '/ceph/osds/{}'.format(osd_id))

        # Log it
        logger.out('Removed OSD disk with ID {}'.format(osd_id), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to purge OSD disk with ID {}: {}'.format(osd_id, e), state='e')
        return False

def in_osd(zk_conn, logger, osd_id):
    # We are ready to create a new pool on this node
    logger.out('Setting OSD {} in'.format(osd_id), state='i')
    try:
        # 1. Set it in
        retcode, stdout, stderr = common.run_os_command('ceph osd in {}'.format(osd_id))
        if retcode:
            print('ceph osd in')
            print(stdout)
            print(stderr)
            raise

        # Log it
        logger.out('Set OSD {} in'.format(osd_id), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to set OSD {} in: {}'.format(osd_id, e), state='e')
        return False

def out_osd(zk_conn, logger, osd_id):
    # We are ready to create a new pool on this node
    logger.out('Settoutg OSD {} out'.format(osd_id), state='i')
    try:
        # 1. Set it out
        retcode, stdout, stderr = common.run_os_command('ceph osd out {}'.format(osd_id))
        if retcode:
            proutt('ceph osd out')
            proutt(stdout)
            proutt(stderr)
            raise

        # Log it
        logger.out('Set OSD {} out'.format(osd_id), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to set OSD {} out: {}'.format(osd_id, e), state='e')
        return False

def set_property(zk_conn, logger, option):
    # We are ready to create a new pool on this node
    logger.out('Setting OSD property {}'.format(option), state='i')
    try:
        # 1. Set it in
        retcode, stdout, stderr = common.run_os_command('ceph osd set {}'.format(option))
        if retcode:
            prsett('ceph osd set')
            print(stdout)
            print(stderr)
            raise

        # Log it
        logger.out('Set OSD property {}'.format(option), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to set OSD property {}: {}'.format(option, e), state='e')
        return False

def unset_property(zk_conn, logger, option):
    # We are ready to create a new pool on this node
    logger.out('Unsetting OSD property {}'.format(option), state='i')
    try:
        # 1. Set it in
        retcode, stdout, stderr = common.run_os_command('ceph osd unset {}'.format(option))
        if retcode:
            prunsett('ceph osd unset')
            print(stdout)
            print(stderr)
            raise

        # Log it
        logger.out('Unset OSD property {}'.format(option), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to unset OSD property {}: {}'.format(option, e), state='e')
        return False

class CephPoolInstance(object):
    def __init__(self, zk_conn, this_node, name):
        self.zk_conn = zk_conn
        self.this_node = this_node
        self.name = name
        self.pgs = ''
        self.stats = dict()

        @self.zk_conn.DataWatch('/ceph/pools/{}/pgs'.format(self.name))
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

        @self.zk_conn.DataWatch('/ceph/pools/{}/stats'.format(self.name))
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

def add_pool(zk_conn, logger, name, pgs):
    # We are ready to create a new pool on this node
    logger.out('Creating new RBD pool {}'.format(name), state='i')
    try:
        # 1. Create the pool
        retcode, stdout, stderr = common.run_os_command('ceph osd pool create {} {} replicated'.format(name, pgs))
        if retcode:
            print('ceph osd pool create')
            print(stdout)
            print(stderr)
            raise

        # 2. Enable RBD application
        retcode, stdout, stderr = common.run_os_command('ceph osd pool application enable {} rbd'.format(name))
        if retcode:
            print('ceph osd pool application enable')
            print(stdout)
            print(stderr)
            raise

        # 3. Add the new pool to ZK
        zkhandler.writedata(zk_conn, {
            '/ceph/pools/{}'.format(name): '',
            '/ceph/pools/{}/pgs'.format(name): pgs,
            '/ceph/pools/{}/stats'.format(name): '{}',
            '/ceph/volumes/{}'.format(name): '',
            '/ceph/snapshots/{}'.format(name): '',
        })

        # Log it
        logger.out('Created new RBD pool {}'.format(name), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to create new RBD pool {}: {}'.format(name, e), state='e')
        return False

def remove_pool(zk_conn, logger, name):
    # We are ready to create a new pool on this node
    logger.out('Removing RBD pool {}'.format(name), state='i')
    try:
        # Remove pool volumes first
        for volume in zkhandler.listchildren(zk_conn, '/ceph/volumes/{}'.format(name)):
            remove_volume(zk_conn, logger, name, volume)

        # Remove the pool
        retcode, stdout, stderr = common.run_os_command('ceph osd pool rm {pool} {pool} --yes-i-really-really-mean-it'.format(pool=name))
        if retcode:
            print('ceph osd pool rm')
            print(stdout)
            print(stderr)
            raise

        # Delete pool from ZK
        zkhandler.deletekey(zk_conn, '/ceph/pools/{}'.format(name))
        zkhandler.deletekey(zk_conn, '/ceph/volumes/{}'.format(name))
        zkhandler.deletekey(zk_conn, '/ceph/snapshots/{}'.format(name))

        # Log it
        logger.out('Removed RBD pool {}'.format(name), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to remove RBD pool {}: {}'.format(name, e), state='e')
        return False

class CephVolumeInstance(object):
    def __init__(self, zk_conn, this_node, pool, name):
        self.zk_conn = zk_conn
        self.this_node = this_node
        self.pool = pool
        self.name = name
        self.stats = dict()

        @self.zk_conn.DataWatch('/ceph/volumes/{}/{}/stats'.format(self.pool, self.name))
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

def add_volume(zk_conn, logger, pool, name, size):
    # We are ready to create a new volume on this node
    logger.out('Creating new RBD volume {} on pool {} of size {}'.format(name, pool, size), state='i')
    try:
        # Create the volume
        retcode, stdout, stderr = common.run_os_command('rbd create --size {} --image-feature layering,exclusive-lock {}/{}'.format(size, pool, name))
        if retcode:
            print('rbd create')
            print(stdout)
            print(stderr)
            raise

        # Get volume stats
        retcode, stdout, stderr = common.run_os_command('rbd info --format json {}/{}'.format(pool, name))
        volstats = stdout

        # Add the new volume to ZK
        zkhandler.writedata(zk_conn, {
            '/ceph/volumes/{}/{}'.format(pool, name): '',
            '/ceph/volumes/{}/{}/stats'.format(pool, name): volstats,
            '/ceph/snapshots/{}/{}'.format(pool, name): '',
        })

        # Log it
        logger.out('Created new RBD volume {} on pool {}'.format(name, pool), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to create new RBD volume {} on pool {}: {}'.format(name, pool, e), state='e')
        return False

def resize_volume(zk_conn, logger, pool, name, size):
    logger.out('Resizing RBD volume {} on pool {} to size {}'.format(name, pool, size), state='i')
    try:
        # Resize the volume
        retcode, stdout, stderr = common.run_os_command('rbd resize --size {} {}/{}'.format(size, pool, name))
        if retcode:
            print('rbd resize')
            print(stdout)
            print(stderr)
            raise

        # Get volume stats
        retcode, stdout, stderr = common.run_os_command('rbd info --format json {}/{}'.format(pool, name))
        volstats = stdout

        # Update the volume to ZK
        zkhandler.writedata(zk_conn, {
            '/ceph/volumes/{}/{}'.format(pool, name): '',
            '/ceph/volumes/{}/{}/stats'.format(pool, name): volstats,
            '/ceph/snapshots/{}/{}'.format(pool, name): '',
        })

        # Log it
        logger.out('Created new RBD volume {} on pool {}'.format(name, pool), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to resize RBD volume {} on pool {}: {}'.format(name, pool, e), state='e')
        return False

def rename_volume(zk_conn, logger, pool, name, new_name):
    logger.out('Renaming RBD volume {} to {} on pool {}'.format(name, new_name, pool))
    try:
        # Rename the volume
        retcode, stdout, stderr = common.run_os_command('rbd rename {}/{} {}'.format(pool, name, new_name))
        if retcode:
            print('rbd rename')
            print(stdout)
            print(stderr)
            raise

        # Rename the volume in ZK
        zkhandler.renamekey(zk_conn, {
            '/ceph/volumes/{}/{}'.format(pool, name): '/ceph/volumes/{}/{}'.format(pool, new_name),
            '/ceph/snapshots/{}/{}'.format(pool, name): '/ceph/snapshots/{}/{}'.format(pool, new_name),
        })

        # Get volume stats
        retcode, stdout, stderr = common.run_os_command('rbd info --format json {}/{}'.format(pool, new_name))
        volstats = stdout

        # Update the volume stats in ZK
        zkhandler.writedata(zk_conn, {
            '/ceph/volumes/{}/{}/stats'.format(pool, new_name): volstats,
        })

        # Log it
        logger.out('Renamed RBD volume {} to {} on pool {}'.format(name, new_name, pool), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to rename RBD volume {} on pool {}: {}'.format(name, pool, e), state='e')
        return False

def remove_volume(zk_conn, logger, pool, name):
    # We are ready to create a new volume on this node
    logger.out('Removing RBD volume {} from pool {}'.format(name, pool), state='i')
    try:
        # Remove the volume
        retcode, stdout, stderr = common.run_os_command('rbd rm {}/{}'.format(pool, name))
        if retcode:
            print('ceph osd volume rm')
            print(stdout)
            print(stderr)
            raise

        # Delete volume from ZK
        zkhandler.deletekey(zk_conn, '/ceph/volumes/{}/{}'.format(pool, name))
        zkhandler.deletekey(zk_conn, '/ceph/snapshots/{}/{}'.format(pool, name))

        # Log it
        logger.out('Removed RBD volume {} from pool {}'.format(name, pool), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to remove RBD volume {} from pool {}: {}'.format(name, pool, e), state='e')
        return False

class CephSnapshotInstance(object):
    def __init__(self, zk_conn, this_node, name):
        self.zk_conn = zk_conn
        self.this_node = this_node
        self.pool = pool
        self.volume = volume
        self.name = name
        self.stats = dict()

        @self.zk_conn.DataWatch('/ceph/snapshots/{}/{}/{}/stats'.format(self.pool, self.volume, self.name))
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

def add_snapshot(zk_conn, logger, pool, volume, name):
    # We are ready to create a new snapshot on this node
    logger.out('Creating new RBD snapshot {} of volume {} on pool {}'.format(name, volume, pool), state='i')
    try:
        # 1. Create the snapshot
        retcode, stdout, stderr = common.run_os_command('rbd snap create {}/{}@{}'.format(pool, volume, name))
        if retcode:
            print('rbd snap create')
            print(stdout)
            print(stderr)
            raise

        # 2. Add the new snapshot to ZK
        zkhandler.writedata(zk_conn, {
            '/ceph/snapshots/{}/{}/{}'.format(pool, volume, name): '',
            '/ceph/snapshots/{}/{}/{}/stats'.format(pool, volume, name): '{}'
        })

        # Log it
        logger.out('Created new RBD snapshot {} of volume {} on pool {}'.format(name, volume, pool), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to create new RBD snapshot {} of volume {} on pool {}: {}'.format(name, volume, pool, e), state='e')
        return False

def rename_snapshot(zk_conn, logger, pool, volume, name, new_name):
    logger.out('Renaming RBD volume snapshot {} to {} for volume {} on pool {}'.format(name, new_name, volume, pool))
    try:
        # Rename the volume
        retcode, stdout, stderr = common.run_os_command('rbd snap rename {}/{}@{} {}'.format(pool, volume, name, new_name))
        if retcode:
            print('rbd snap rename')
            print(stdout)
            print(stderr)
            raise

        # Rename the snapshot in ZK
        zkhandler.renamekey(zk_conn, {
            '/ceph/snapshots/{}/{}/{}'.format(pool, volume, name): '/ceph/snapshots/{}/{}/{}'.format(pool, volume, new_name)
        })

        # Update the snapshot stats in ZK
        zkhandler.writedata(zk_conn, {
            '/ceph/snapshots/{}/{}/{}/stats'.format(pool, volume, new_name): '{}',
        })

        # Log it
        logger.out('Renamed RBD volume snapshot {} to {} for volume {} on pool {}'.format(name, new_name, volume, pool), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to rename RBD volume snapshot {} for volume {} on pool {}: {}'.format(name, volume, pool, e), state='e')
        return False

def remove_snapshot(zk_conn, logger, pool, volume, name):
    # We are ready to create a new snapshot on this node
    logger.out('Removing RBD snapshot {} of volume {} on pool {}'.format(name, volume, pool), state='i')
    try:
        # Delete snapshot from ZK
        zkhandler.deletekey(zk_conn, '/ceph/snapshots/{}/{}/{}'.format(pool, volume, name))

        # Remove the snapshot
        retcode, stdout, stderr = common.run_os_command('rbd snap rm {}/{}@{}'.format(pool, volume, name))
        if retcode:
            print('rbd snap rm')
            print(stdout)
            print(stderr)
            raise

        # Log it
        logger.out('Removed RBD snapshot {} of volume {} on pool {}'.format(name, volume, pool), state='o')
        return True
    except Exception as e:
        # Log it
        logger.out('Failed to remove RBD snapshot {} of volume {} on pool {}: {}'.format(name, volume, pool, e), state='e')
        return False

# Primary command function
def run_command(zk_conn, logger, this_node, data, d_osd):
    # Get the command and args
    command, args = data.split()

    # Adding a new OSD
    if command == 'osd_add':
        node, device, weight = args.split(',')
        if node == this_node.name:
            # Lock the command queue
            zk_lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
            with zk_lock:
                # Add the OSD
                result = add_osd(zk_conn, logger, node, device, weight)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'success-{}'.format(data)})
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'failure-{}'.format(data)})
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Removing an OSD
    elif command == 'osd_remove':
        osd_id = args

        # Verify osd_id is in the list
        if d_osd[osd_id] and d_osd[osd_id].node == this_node.name:
            # Lock the command queue
            zk_lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
            with zk_lock:
                # Remove the OSD
                result = remove_osd(zk_conn, logger, osd_id, d_osd[osd_id])
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'success-{}'.format(data)})
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'failure-{}'.format(data)})
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Online an OSD
    elif command == 'osd_in':
        osd_id = args

        # Verify osd_id is in the list
        if d_osd[osd_id] and d_osd[osd_id].node == this_node.name:
            # Lock the command queue
            zk_lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
            with zk_lock:
                # Online the OSD
                result = in_osd(zk_conn, logger, osd_id)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'success-{}'.format(data)})
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'failure-{}'.format(data)})
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Offline an OSD
    elif command == 'osd_out':
        osd_id = args

        # Verify osd_id is in the list
        if d_osd[osd_id] and d_osd[osd_id].node == this_node.name:
            # Lock the command queue
            zk_lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
            with zk_lock:
                # Offline the OSD
                result = out_osd(zk_conn, logger, osd_id)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'success-{}'.format(data)})
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'failure-{}'.format(data)})
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Set a property
    elif command == 'osd_set':
        option = args

        if this_node.router_state == 'primary':
            # Lock the command queue
            zk_lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
            with zk_lock:
                # Set the property
                result = set_property(zk_conn, logger, option)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'success-{}'.format(data)})
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'failure-{}'.format(data)})
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Unset a property
    elif command == 'osd_unset':
        option = args

        if this_node.router_state == 'primary':
            # Lock the command queue
            zk_lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
            with zk_lock:
                # Unset the property
                result = unset_property(zk_conn, logger, option)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'success-{}'.format(data)})
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'failure-{}'.format(data)})
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Adding a new pool
    elif command == 'pool_add':
        name, pgs = args.split(',')

        if this_node.router_state == 'primary':
            # Lock the command queue
            zk_lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
            with zk_lock:
                # Add the pool
                result = add_pool(zk_conn, logger, name, pgs)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'success-{}'.format(data)})
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'failure-{}'.format(data)})
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Removing a pool
    elif command == 'pool_remove':
        name = args

        if this_node.router_state == 'primary':
            # Lock the command queue
            zk_lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
            with zk_lock:
                # Remove the pool
                result = remove_pool(zk_conn, logger, name)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'success-{}'.format(data)})
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'failure-{}'.format(data)})
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Adding a new volume
    elif command == 'volume_add':
        pool, name, size = args.split(',')

        if this_node.router_state == 'primary':
            # Lock the command queue
            zk_lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
            with zk_lock:
                # Add the volume
                result = add_volume(zk_conn, logger, pool, name, size)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'success-{}'.format(data)})
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'failure-{}'.format(data)})
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Resizing a volume
    elif command == 'volume_resize':
        pool, name, size = args.split(',')

        if this_node.router_state == 'primary':
            # Lock the command queue
            zk_lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
            with zk_lock:
                # Add the volume
                result = resize_volume(zk_conn, logger, pool, name, size)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'success-{}'.format(data)})
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'failure-{}'.format(data)})
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Renaming a new volume
    elif command == 'volume_rename':
        pool, name, new_name = args.split(',')

        if this_node.router_state == 'primary':
            # Lock the command queue
            zk_lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
            with zk_lock:
                # Add the volume
                result = rename_volume(zk_conn, logger, pool, name, new_name)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'success-{}'.format(data)})
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'failure-{}'.format(data)})
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Removing a volume
    elif command == 'volume_remove':
        pool, name = args.split(',')

        if this_node.router_state == 'primary':
            # Lock the command queue
            zk_lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
            with zk_lock:
                # Remove the volume
                result = remove_volume(zk_conn, logger, pool, name)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'success-{}'.format(data)})
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'failure-{}'.format(data)})
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Adding a new snapshot
    elif command == 'snapshot_add':
        pool, volume, name = args.split(',')

        if this_node.router_state == 'primary':
            # Lock the command queue
            zk_lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
            with zk_lock:
                # Add the snapshot
                result = add_snapshot(zk_conn, logger, pool, volume, name)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'success-{}'.format(data)})
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'failure-{}'.format(data)})
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Renaming a snapshot
    elif command == 'snapshot_rename':
        pool, volume, name, new_name = args.split(',')

        if this_node.router_state == 'primary':
            # Lock the command queue
            zk_lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
            with zk_lock:
                # Add the snapshot
                result = rename_snapshot(zk_conn, logger, pool, volume, name, new_name)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'success-{}'.format(data)})
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'failure-{}'.format(data)})
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Removing a snapshot
    elif command == 'snapshot_remove':
        pool, volume, name = args.split(',')

        if this_node.router_state == 'primary':
            # Lock the command queue
            zk_lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
            with zk_lock:
                # Remove the snapshot
                result = remove_snapshot(zk_conn, logger, pool, volume, name)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'success-{}'.format(data)})
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.writedata(zk_conn, {'/ceph/cmd': 'failure-{}'.format(data)})
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)
