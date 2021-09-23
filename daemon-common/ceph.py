#!/usr/bin/env python3

# ceph.py - PVC client function library, Ceph cluster fuctions
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

import os
import re
import json
import time
import math

from concurrent.futures import ThreadPoolExecutor

import daemon_lib.vm as vm
import daemon_lib.common as common


#
# Supplemental functions
#

# Verify OSD is valid in cluster
def verifyOSD(zkhandler, osd_id):
    return zkhandler.exists(('osd', osd_id))


# Verify Pool is valid in cluster
def verifyPool(zkhandler, name):
    return zkhandler.exists(('pool', name))


# Verify Volume is valid in cluster
def verifyVolume(zkhandler, pool, name):
    return zkhandler.exists(('volume', f'{pool}/{name}'))


# Verify Snapshot is valid in cluster
def verifySnapshot(zkhandler, pool, volume, name):
    return zkhandler.exists(('snapshot', f'{pool}/{volume}/{name}'))


# Verify OSD path is valid in cluster
def verifyOSDBlock(zkhandler, node, device):
    for osd in zkhandler.children('base.osd'):
        osd_node = zkhandler.read(('osd.node', osd))
        osd_device = zkhandler.read(('osd.device', osd))
        if node == osd_node and device == osd_device:
            return osd
    return None


# Matrix of human-to-byte values
byte_unit_matrix = {
    'B': 1,
    'K': 1024,
    'M': 1024 * 1024,
    'G': 1024 * 1024 * 1024,
    'T': 1024 * 1024 * 1024 * 1024,
    'P': 1024 * 1024 * 1024 * 1024 * 1024
}

# Matrix of human-to-metric values
ops_unit_matrix = {
    '': 1,
    'K': 1000,
    'M': 1000 * 1000,
    'G': 1000 * 1000 * 1000,
    'T': 1000 * 1000 * 1000 * 1000,
    'P': 1000 * 1000 * 1000 * 1000 * 1000
}


# Format byte sizes to/from human-readable units
def format_bytes_tohuman(databytes):
    datahuman = ''
    for unit in sorted(byte_unit_matrix, key=byte_unit_matrix.get, reverse=True):
        new_bytes = int(math.ceil(databytes / byte_unit_matrix[unit]))
        # Round up if 5 or more digits
        if new_bytes > 9999:
            # We can jump down another level
            continue
        else:
            # We're at the end, display with this size
            datahuman = '{}{}'.format(new_bytes, unit)

    return datahuman


def format_bytes_fromhuman(datahuman):
    # Trim off human-readable character
    dataunit = str(datahuman)[-1]
    datasize = int(str(datahuman)[:-1])
    if not re.match(r'[A-Z]', dataunit):
        dataunit = 'B'
        datasize = int(datahuman)
    databytes = datasize * byte_unit_matrix[dataunit]
    return databytes


# Format ops sizes to/from human-readable units
def format_ops_tohuman(dataops):
    datahuman = ''
    for unit in sorted(ops_unit_matrix, key=ops_unit_matrix.get, reverse=True):
        new_ops = int(math.ceil(dataops / ops_unit_matrix[unit]))
        # Round up if 5 or more digits
        if new_ops > 9999:
            # We can jump down another level
            continue
        else:
            # We're at the end, display with this size
            datahuman = '{}{}'.format(new_ops, unit)

    return datahuman


def format_ops_fromhuman(datahuman):
    # Trim off human-readable character
    dataunit = datahuman[-1]
    datasize = int(datahuman[:-1])
    dataops = datasize * ops_unit_matrix[dataunit]
    return '{}'.format(dataops)


def format_pct_tohuman(datapct):
    datahuman = "{0:.1f}".format(float(datapct * 100.0))
    return datahuman


#
# Status functions
#
def get_status(zkhandler):
    primary_node = zkhandler.read('base.config.primary_node')
    ceph_status = zkhandler.read('base.storage').rstrip()

    # Create a data structure for the information
    status_data = {
        'type': 'status',
        'primary_node': primary_node,
        'ceph_data': ceph_status
    }
    return True, status_data


def get_util(zkhandler):
    primary_node = zkhandler.read('base.config.primary_node')
    ceph_df = zkhandler.read('base.storage.util').rstrip()

    # Create a data structure for the information
    status_data = {
        'type': 'utilization',
        'primary_node': primary_node,
        'ceph_data': ceph_df
    }
    return True, status_data


#
# OSD functions
#
def getClusterOSDList(zkhandler):
    # Get a list of VNIs by listing the children of /networks
    return zkhandler.children('base.osd')


def getOSDInformation(zkhandler, osd_id):
    # Get the devices
    osd_device = zkhandler.read(('osd.device', osd_id))
    osd_db_device = zkhandler.read(('osd.db_device', osd_id))
    # Parse the stats data
    osd_stats_raw = zkhandler.read(('osd.stats', osd_id))
    osd_stats = dict(json.loads(osd_stats_raw))

    osd_information = {
        'id': osd_id,
        'device': osd_device,
        'db_device': osd_db_device,
        'stats': osd_stats,
    }
    return osd_information


# OSD DB VG actions use the /cmd/ceph pipe
# These actions must occur on the specific node they reference
def add_osd_db_vg(zkhandler, node, device):
    # Verify the target node exists
    if not common.verifyNode(zkhandler, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    # Tell the cluster to create a new OSD for the host
    add_osd_db_vg_string = 'db_vg_add {},{}'.format(node, device)
    zkhandler.write([
        ('base.cmd.ceph', add_osd_db_vg_string)
    ])
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    with zkhandler.readlock('base.cmd.ceph'):
        try:
            result = zkhandler.read('base.cmd.ceph').split()[0]
            if result == 'success-db_vg_add':
                message = 'Created new OSD database VG at "{}" on node "{}".'.format(device, node)
                success = True
            else:
                message = 'ERROR: Failed to create new OSD database VG; check node logs for details.'
                success = False
        except Exception:
            message = 'ERROR: Command ignored by node.'
            success = False

    # Acquire a write lock to ensure things go smoothly
    with zkhandler.writelock('base.cmd.ceph'):
        time.sleep(0.5)
        zkhandler.write([
            ('base.cmd.ceph', '')
        ])

    return success, message


# OSD addition and removal uses the /cmd/ceph pipe
# These actions must occur on the specific node they reference
def add_osd(zkhandler, node, device, weight, ext_db_flag=False):
    # Verify the target node exists
    if not common.verifyNode(zkhandler, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    # Verify target block device isn't in use
    block_osd = verifyOSDBlock(zkhandler, node, device)
    if block_osd:
        return False, 'ERROR: Block device "{}" on node "{}" is used by OSD "{}"'.format(device, node, block_osd)

    # Tell the cluster to create a new OSD for the host
    add_osd_string = 'osd_add {},{},{},{}'.format(node, device, weight, ext_db_flag)
    zkhandler.write([
        ('base.cmd.ceph', add_osd_string)
    ])
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    with zkhandler.readlock('base.cmd.ceph'):
        try:
            result = zkhandler.read('base.cmd.ceph').split()[0]
            if result == 'success-osd_add':
                message = 'Created new OSD with block device "{}" on node "{}".'.format(device, node)
                success = True
            else:
                message = 'ERROR: Failed to create new OSD; check node logs for details.'
                success = False
        except Exception:
            message = 'ERROR: Command ignored by node.'
            success = False

    # Acquire a write lock to ensure things go smoothly
    with zkhandler.writelock('base.cmd.ceph'):
        time.sleep(0.5)
        zkhandler.write([
            ('base.cmd.ceph', '')
        ])

    return success, message


def remove_osd(zkhandler, osd_id):
    if not verifyOSD(zkhandler, osd_id):
        return False, 'ERROR: No OSD with ID "{}" is present in the cluster.'.format(osd_id)

    # Tell the cluster to remove an OSD
    remove_osd_string = 'osd_remove {}'.format(osd_id)
    zkhandler.write([
        ('base.cmd.ceph', remove_osd_string)
    ])
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    with zkhandler.readlock('base.cmd.ceph'):
        try:
            result = zkhandler.read('base.cmd.ceph').split()[0]
            if result == 'success-osd_remove':
                message = 'Removed OSD "{}" from the cluster.'.format(osd_id)
                success = True
            else:
                message = 'ERROR: Failed to remove OSD; check node logs for details.'
                success = False
        except Exception:
            success = False
            message = 'ERROR Command ignored by node.'

    # Acquire a write lock to ensure things go smoothly
    with zkhandler.writelock('base.cmd.ceph'):
        time.sleep(0.5)
        zkhandler.write([
            ('base.cmd.ceph', '')
        ])

    return success, message


def in_osd(zkhandler, osd_id):
    if not verifyOSD(zkhandler, osd_id):
        return False, 'ERROR: No OSD with ID "{}" is present in the cluster.'.format(osd_id)

    retcode, stdout, stderr = common.run_os_command('ceph osd in {}'.format(osd_id))
    if retcode:
        return False, 'ERROR: Failed to enable OSD {}: {}'.format(osd_id, stderr)

    return True, 'Set OSD {} online.'.format(osd_id)


def out_osd(zkhandler, osd_id):
    if not verifyOSD(zkhandler, osd_id):
        return False, 'ERROR: No OSD with ID "{}" is present in the cluster.'.format(osd_id)

    retcode, stdout, stderr = common.run_os_command('ceph osd out {}'.format(osd_id))
    if retcode:
        return False, 'ERROR: Failed to disable OSD {}: {}'.format(osd_id, stderr)

    return True, 'Set OSD {} offline.'.format(osd_id)


def set_osd(zkhandler, option):
    retcode, stdout, stderr = common.run_os_command('ceph osd set {}'.format(option))
    if retcode:
        return False, 'ERROR: Failed to set property "{}": {}'.format(option, stderr)

    return True, 'Set OSD property "{}".'.format(option)


def unset_osd(zkhandler, option):
    retcode, stdout, stderr = common.run_os_command('ceph osd unset {}'.format(option))
    if retcode:
        return False, 'ERROR: Failed to unset property "{}": {}'.format(option, stderr)

    return True, 'Unset OSD property "{}".'.format(option)


def get_list_osd(zkhandler, limit, is_fuzzy=True):
    osd_list = []
    full_osd_list = zkhandler.children('base.osd')

    if is_fuzzy and limit:
        # Implicitly assume fuzzy limits
        if not re.match(r'\^.*', limit):
            limit = '.*' + limit
        if not re.match(r'.*\$', limit):
            limit = limit + '.*'

    for osd in full_osd_list:
        if limit:
            try:
                if re.match(limit, osd):
                    osd_list.append(getOSDInformation(zkhandler, osd))
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            osd_list.append(getOSDInformation(zkhandler, osd))

    return True, sorted(osd_list, key=lambda x: int(x['id']))


#
# Pool functions
#
def getPoolInformation(zkhandler, pool):
    # Parse the stats data
    pool_stats_raw = zkhandler.read(('pool.stats', pool))
    pool_stats = dict(json.loads(pool_stats_raw))
    volume_count = len(getCephVolumes(zkhandler, pool))

    pool_information = {
        'name': pool,
        'volume_count': volume_count,
        'stats': pool_stats
    }
    return pool_information


def add_pool(zkhandler, name, pgs, replcfg):
    # Prepare the copies/mincopies variables
    try:
        copies, mincopies = replcfg.split(',')
        copies = int(copies.replace('copies=', ''))
        mincopies = int(mincopies.replace('mincopies=', ''))
    except Exception:
        copies = None
        mincopies = None
    if not copies or not mincopies:
        return False, 'ERROR: Replication configuration "{}" is not valid.'.format(replcfg)

    # 1. Create the pool
    retcode, stdout, stderr = common.run_os_command('ceph osd pool create {} {} replicated'.format(name, pgs))
    if retcode:
        return False, 'ERROR: Failed to create pool "{}" with {} PGs: {}'.format(name, pgs, stderr)

    # 2. Set the size and minsize
    retcode, stdout, stderr = common.run_os_command('ceph osd pool set {} size {}'.format(name, copies))
    if retcode:
        return False, 'ERROR: Failed to set pool "{}" size of {}: {}'.format(name, copies, stderr)

    retcode, stdout, stderr = common.run_os_command('ceph osd pool set {} min_size {}'.format(name, mincopies))
    if retcode:
        return False, 'ERROR: Failed to set pool "{}" minimum size of {}: {}'.format(name, mincopies, stderr)

    # 3. Enable RBD application
    retcode, stdout, stderr = common.run_os_command('ceph osd pool application enable {} rbd'.format(name))
    if retcode:
        return False, 'ERROR: Failed to enable RBD application on pool "{}" : {}'.format(name, stderr)

    # 4. Add the new pool to Zookeeper
    zkhandler.write([
        (('pool', name), ''),
        (('pool.pgs', name), pgs),
        (('pool.stats', name), '{}'),
        (('volume', name), ''),
        (('snapshot', name), ''),
    ])

    return True, 'Created RBD pool "{}" with {} PGs'.format(name, pgs)


def remove_pool(zkhandler, name):
    if not verifyPool(zkhandler, name):
        return False, 'ERROR: No pool with name "{}" is present in the cluster.'.format(name)

    # 1. Remove pool volumes
    for volume in zkhandler.children(('volume', name)):
        remove_volume(zkhandler, name, volume)

    # 2. Remove the pool
    retcode, stdout, stderr = common.run_os_command('ceph osd pool rm {pool} {pool} --yes-i-really-really-mean-it'.format(pool=name))
    if retcode:
        return False, 'ERROR: Failed to remove pool "{}": {}'.format(name, stderr)

    # 3. Delete pool from Zookeeper
    zkhandler.delete([
        ('pool', name),
        ('volume', name),
        ('snapshot', name),
    ])

    return True, 'Removed RBD pool "{}" and all volumes.'.format(name)


def get_list_pool(zkhandler, limit, is_fuzzy=True):
    full_pool_list = zkhandler.children('base.pool')

    if limit:
        if not is_fuzzy:
            limit = '^' + limit + '$'

    get_pool_info = dict()
    for pool in full_pool_list:
        is_limit_match = False
        if limit:
            try:
                if re.match(limit, pool):
                    is_limit_match = True
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            is_limit_match = True

        get_pool_info[pool] = True if is_limit_match else False

    pool_execute_list = [pool for pool in full_pool_list if get_pool_info[pool]]
    pool_data_list = list()
    with ThreadPoolExecutor(max_workers=32, thread_name_prefix='pool_list') as executor:
        futures = []
        for pool in pool_execute_list:
            futures.append(executor.submit(getPoolInformation, zkhandler, pool))
        for future in futures:
            pool_data_list.append(future.result())

    return True, sorted(pool_data_list, key=lambda x: int(x['stats']['id']))


#
# Volume functions
#
def getCephVolumes(zkhandler, pool):
    volume_list = list()
    if not pool:
        pool_list = zkhandler.children('base.pool')
    else:
        pool_list = [pool]

    for pool_name in pool_list:
        for volume_name in zkhandler.children(('volume', pool_name)):
            volume_list.append('{}/{}'.format(pool_name, volume_name))

    return volume_list


def getVolumeInformation(zkhandler, pool, volume):
    # Parse the stats data
    volume_stats_raw = zkhandler.read(('volume.stats', f'{pool}/{volume}'))
    volume_stats = dict(json.loads(volume_stats_raw))
    # Format the size to something nicer
    volume_stats['size'] = format_bytes_tohuman(volume_stats['size'])

    volume_information = {
        'name': volume,
        'pool': pool,
        'stats': volume_stats
    }
    return volume_information


def add_volume(zkhandler, pool, name, size):
    # Add 'B' if the volume is in bytes
    if re.match(r'^[0-9]+$', size):
        size = '{}B'.format(size)

    # 1. Verify the size of the volume
    pool_information = getPoolInformation(zkhandler, pool)
    size_bytes = format_bytes_fromhuman(size)
    if size_bytes >= int(pool_information['stats']['free_bytes']):
        return False, 'ERROR: Requested volume size is greater than the available free space in the pool'

    # 2. Create the volume
    retcode, stdout, stderr = common.run_os_command('rbd create --size {} {}/{}'.format(size, pool, name))
    if retcode:
        return False, 'ERROR: Failed to create RBD volume "{}": {}'.format(name, stderr)

    # 2. Get volume stats
    retcode, stdout, stderr = common.run_os_command('rbd info --format json {}/{}'.format(pool, name))
    volstats = stdout

    # 3. Add the new volume to Zookeeper
    zkhandler.write([
        (('volume', f'{pool}/{name}'), ''),
        (('volume.stats', f'{pool}/{name}'), volstats),
        (('snapshot', f'{pool}/{name}'), ''),
    ])

    return True, 'Created RBD volume "{}/{}" ({}).'.format(pool, name, size)


def clone_volume(zkhandler, pool, name_src, name_new):
    if not verifyVolume(zkhandler, pool, name_src):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(name_src, pool)

    # 1. Clone the volume
    retcode, stdout, stderr = common.run_os_command('rbd copy {}/{} {}/{}'.format(pool, name_src, pool, name_new))
    if retcode:
        return False, 'ERROR: Failed to clone RBD volume "{}" to "{}" in pool "{}": {}'.format(name_src, name_new, pool, stderr)

    # 2. Get volume stats
    retcode, stdout, stderr = common.run_os_command('rbd info --format json {}/{}'.format(pool, name_new))
    volstats = stdout

    # 3. Add the new volume to Zookeeper
    zkhandler.write([
        (('volume', f'{pool}/{name_new}'), ''),
        (('volume.stats', f'{pool}/{name_new}'), volstats),
        (('snapshot', f'{pool}/{name_new}'), ''),
    ])

    return True, 'Cloned RBD volume "{}" to "{}" in pool "{}"'.format(name_src, name_new, pool)


def resize_volume(zkhandler, pool, name, size):
    if not verifyVolume(zkhandler, pool, name):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(name, pool)

    # Add 'B' if the volume is in bytes
    if re.match(r'^[0-9]+$', size):
        size = '{}B'.format(size)

    # 1. Verify the size of the volume
    pool_information = getPoolInformation(zkhandler, pool)
    size_bytes = format_bytes_fromhuman(size)
    if size_bytes >= int(pool_information['stats']['free_bytes']):
        return False, 'ERROR: Requested volume size is greater than the available free space in the pool'

    # 2. Resize the volume
    retcode, stdout, stderr = common.run_os_command('rbd resize --size {} {}/{}'.format(size, pool, name))
    if retcode:
        return False, 'ERROR: Failed to resize RBD volume "{}" to size "{}" in pool "{}": {}'.format(name, size, pool, stderr)

    # 3a. Determine the node running this VM if applicable
    active_node = None
    volume_vm_name = name.split('_')[0]
    retcode, vm_info = vm.get_info(zkhandler, volume_vm_name)
    if retcode:
        for disk in vm_info['disks']:
            # This block device is present in this VM so we can continue
            if disk['name'] == '{}/{}'.format(pool, name):
                active_node = vm_info['node']
                volume_id = disk['dev']
    # 3b. Perform a live resize in libvirt if the VM is running
    if active_node is not None and vm_info.get('state', '') == 'start':
        import libvirt
        # Run the libvirt command against the target host
        try:
            dest_lv = 'qemu+tcp://{}/system'.format(active_node)
            target_lv_conn = libvirt.open(dest_lv)
            target_vm_conn = target_lv_conn.lookupByName(vm_info['name'])
            if target_vm_conn:
                target_vm_conn.blockResize(volume_id, format_bytes_fromhuman(size), libvirt.VIR_DOMAIN_BLOCK_RESIZE_BYTES)
            target_lv_conn.close()
        except Exception:
            pass

    # 4. Get volume stats
    retcode, stdout, stderr = common.run_os_command('rbd info --format json {}/{}'.format(pool, name))
    volstats = stdout

    # 5. Update the volume in Zookeeper
    zkhandler.write([
        (('volume', f'{pool}/{name}'), ''),
        (('volume.stats', f'{pool}/{name}'), volstats),
        (('snapshot', f'{pool}/{name}'), ''),
    ])

    return True, 'Resized RBD volume "{}" to size "{}" in pool "{}".'.format(name, size, pool)


def rename_volume(zkhandler, pool, name, new_name):
    if not verifyVolume(zkhandler, pool, name):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(name, pool)

    # 1. Rename the volume
    retcode, stdout, stderr = common.run_os_command('rbd rename {}/{} {}'.format(pool, name, new_name))
    if retcode:
        return False, 'ERROR: Failed to rename volume "{}" to "{}" in pool "{}": {}'.format(name, new_name, pool, stderr)

    # 2. Rename the volume in Zookeeper
    zkhandler.rename([
        (('volume', f'{pool}/{name}'), ('volume', f'{pool}/{new_name}')),
        (('snapshot', f'{pool}/{name}'), ('snapshot', f'{pool}/{new_name}')),
    ])

    # 3. Get volume stats
    retcode, stdout, stderr = common.run_os_command('rbd info --format json {}/{}'.format(pool, new_name))
    volstats = stdout

    # 4. Update the volume stats in Zookeeper
    zkhandler.write([
        (('volume.stats', f'{pool}/{new_name}'), volstats),
    ])

    return True, 'Renamed RBD volume "{}" to "{}" in pool "{}".'.format(name, new_name, pool)


def remove_volume(zkhandler, pool, name):
    if not verifyVolume(zkhandler, pool, name):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(name, pool)

    # 1. Remove volume snapshots
    for snapshot in zkhandler.children(('snapshot', f'{pool}/{name}')):
        remove_snapshot(zkhandler, pool, name, snapshot)

    # 2. Remove the volume
    retcode, stdout, stderr = common.run_os_command('rbd rm {}/{}'.format(pool, name))
    if retcode:
        return False, 'ERROR: Failed to remove RBD volume "{}" in pool "{}": {}'.format(name, pool, stderr)

    # 3. Delete volume from Zookeeper
    zkhandler.delete([
        ('volume', f'{pool}/{name}'),
        ('snapshot', f'{pool}/{name}'),
    ])

    return True, 'Removed RBD volume "{}" in pool "{}".'.format(name, pool)


def map_volume(zkhandler, pool, name):
    if not verifyVolume(zkhandler, pool, name):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(name, pool)

    # 1. Map the volume onto the local system
    retcode, stdout, stderr = common.run_os_command('rbd map {}/{}'.format(pool, name))
    if retcode:
        return False, 'ERROR: Failed to map RBD volume "{}" in pool "{}": {}'.format(name, pool, stderr)

    # 2. Calculate the absolute path to the mapped volume
    mapped_volume = '/dev/rbd/{}/{}'.format(pool, name)

    # 3. Ensure the volume exists
    if not os.path.exists(mapped_volume):
        return False, 'ERROR: Mapped volume not found at expected location "{}".'.format(mapped_volume)

    return True, mapped_volume


def unmap_volume(zkhandler, pool, name):
    if not verifyVolume(zkhandler, pool, name):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(name, pool)

    mapped_volume = '/dev/rbd/{}/{}'.format(pool, name)

    # 1. Ensure the volume exists
    if not os.path.exists(mapped_volume):
        return False, 'ERROR: Mapped volume not found at expected location "{}".'.format(mapped_volume)

    # 2. Unap the volume
    retcode, stdout, stderr = common.run_os_command('rbd unmap {}'.format(mapped_volume))
    if retcode:
        return False, 'ERROR: Failed to unmap RBD volume at "{}": {}'.format(mapped_volume, stderr)

    return True, 'Unmapped RBD volume at "{}".'.format(mapped_volume)


def get_list_volume(zkhandler, pool, limit, is_fuzzy=True):
    if pool and not verifyPool(zkhandler, pool):
        return False, 'ERROR: No pool with name "{}" is present in the cluster.'.format(pool)

    full_volume_list = getCephVolumes(zkhandler, pool)

    if limit:
        if not is_fuzzy:
            limit = '^' + limit + '$'
        else:
            # Implicitly assume fuzzy limits
            if not re.match(r'\^.*', limit):
                limit = '.*' + limit
            if not re.match(r'.*\$', limit):
                limit = limit + '.*'

    get_volume_info = dict()
    for volume in full_volume_list:
        pool_name, volume_name = volume.split('/')
        is_limit_match = False

        # Check on limit
        if limit:
            # Try to match the limit against the volume name
            try:
                if re.match(limit, volume_name):
                    is_limit_match = True
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            is_limit_match = True

        get_volume_info[volume] = True if is_limit_match else False

    # Obtain our volume data in a thread pool
    volume_execute_list = [volume for volume in full_volume_list if get_volume_info[volume]]
    volume_data_list = list()
    with ThreadPoolExecutor(max_workers=32, thread_name_prefix='volume_list') as executor:
        futures = []
        for volume in volume_execute_list:
            pool_name, volume_name = volume.split('/')
            futures.append(executor.submit(getVolumeInformation, zkhandler, pool_name, volume_name))
        for future in futures:
            volume_data_list.append(future.result())

    return True, sorted(volume_data_list, key=lambda x: str(x['name']))


#
# Snapshot functions
#
def getCephSnapshots(zkhandler, pool, volume):
    snapshot_list = list()
    volume_list = list()

    volume_list = getCephVolumes(zkhandler, pool)
    if volume:
        for volume_entry in volume_list:
            volume_pool, volume_name = volume_entry.split('/')
            if volume_name == volume:
                volume_list = ['{}/{}'.format(volume_pool, volume_name)]

    for volume_entry in volume_list:
        for snapshot_name in zkhandler.children(('snapshot', volume_entry)):
            snapshot_list.append('{}@{}'.format(volume_entry, snapshot_name))

    return snapshot_list


def add_snapshot(zkhandler, pool, volume, name):
    if not verifyVolume(zkhandler, pool, volume):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(volume, pool)

    # 1. Create the snapshot
    retcode, stdout, stderr = common.run_os_command('rbd snap create {}/{}@{}'.format(pool, volume, name))
    if retcode:
        return False, 'ERROR: Failed to create RBD snapshot "{}" of volume "{}" in pool "{}": {}'.format(name, volume, pool, stderr)

    # 2. Add the snapshot to Zookeeper
    zkhandler.write([
        (('snapshot', f'{pool}/{volume}/{name}'), ''),
        (('snapshot.stats', f'{pool}/{volume}/{name}'), '{}'),
    ])

    # 3. Update the count of snapshots on this volume
    volume_stats_raw = zkhandler.read(('volume.stats', f'{pool}/{volume}'))
    volume_stats = dict(json.loads(volume_stats_raw))
    # Format the size to something nicer
    volume_stats['snapshot_count'] = volume_stats['snapshot_count'] + 1
    volume_stats_raw = json.dumps(volume_stats)
    zkhandler.write([
        (('volume.stats', f'{pool}/{volume}'), volume_stats_raw),
    ])

    return True, 'Created RBD snapshot "{}" of volume "{}" in pool "{}".'.format(name, volume, pool)


def rename_snapshot(zkhandler, pool, volume, name, new_name):
    if not verifyVolume(zkhandler, pool, volume):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(volume, pool)
    if not verifySnapshot(zkhandler, pool, volume, name):
        return False, 'ERROR: No snapshot with name "{}" is present for volume "{}" in pool "{}".'.format(name, volume, pool)

    # 1. Rename the snapshot
    retcode, stdout, stderr = common.run_os_command('rbd snap rename {pool}/{volume}@{name} {pool}/{volume}@{new_name}'.format(pool=pool, volume=volume, name=name, new_name=new_name))
    if retcode:
        return False, 'ERROR: Failed to rename RBD snapshot "{}" to "{}" for volume "{}" in pool "{}": {}'.format(name, new_name, volume, pool, stderr)

    # 2. Rename the snapshot in ZK
    zkhandler.rename([
        (('snapshot', f'{pool}/{volume}/{name}'), ('snapshot', f'{pool}/{volume}/{new_name}')),
    ])

    return True, 'Renamed RBD snapshot "{}" to "{}" for volume "{}" in pool "{}".'.format(name, new_name, volume, pool)


def remove_snapshot(zkhandler, pool, volume, name):
    if not verifyVolume(zkhandler, pool, volume):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(volume, pool)
    if not verifySnapshot(zkhandler, pool, volume, name):
        return False, 'ERROR: No snapshot with name "{}" is present of volume {} in pool {}.'.format(name, volume, pool)

    # 1. Remove the snapshot
    retcode, stdout, stderr = common.run_os_command('rbd snap rm {}/{}@{}'.format(pool, volume, name))
    if retcode:
        return False, 'Failed to remove RBD snapshot "{}" of volume "{}" in pool "{}": {}'.format(name, volume, pool, stderr)

    # 2. Delete snapshot from Zookeeper
    zkhandler.delete([
        ('snapshot', f'{pool}/{volume}/{name}')
    ])

    # 3. Update the count of snapshots on this volume
    volume_stats_raw = zkhandler.read(('volume.stats', f'{pool}/{volume}'))
    volume_stats = dict(json.loads(volume_stats_raw))
    # Format the size to something nicer
    volume_stats['snapshot_count'] = volume_stats['snapshot_count'] - 1
    volume_stats_raw = json.dumps(volume_stats)
    zkhandler.write([
        (('volume.stats', f'{pool}/{volume}'), volume_stats_raw)
    ])

    return True, 'Removed RBD snapshot "{}" of volume "{}" in pool "{}".'.format(name, volume, pool)


def get_list_snapshot(zkhandler, pool, volume, limit, is_fuzzy=True):
    snapshot_list = []
    if pool and not verifyPool(zkhandler, pool):
        return False, 'ERROR: No pool with name "{}" is present in the cluster.'.format(pool)

    if volume and not verifyPool(zkhandler, volume):
        return False, 'ERROR: No volume with name "{}" is present in the cluster.'.format(volume)

    full_snapshot_list = getCephSnapshots(zkhandler, pool, volume)

    if is_fuzzy and limit:
        # Implicitly assume fuzzy limits
        if not re.match(r'\^.*', limit):
            limit = '.*' + limit
        if not re.match(r'.*\$', limit):
            limit = limit + '.*'

    for snapshot in full_snapshot_list:
        volume, snapshot_name = snapshot.split('@')
        pool_name, volume_name = volume.split('/')
        if limit:
            try:
                if re.match(limit, snapshot_name):
                    snapshot_list.append({'pool': pool_name, 'volume': volume_name, 'snapshot': snapshot_name})
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            snapshot_list.append({'pool': pool_name, 'volume': volume_name, 'snapshot': snapshot_name})

    return True, sorted(snapshot_list, key=lambda x: str(x['snapshot']))
