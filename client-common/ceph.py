
# ceph.py - PVC client function library, Ceph cluster fuctions
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

import re
import click
import json
import time
import math

import client_lib.ansiprint as ansiprint
import client_lib.zkhandler as zkhandler
import client_lib.common as common

#
# Supplemental functions
#

# Verify OSD is valid in cluster
def verifyOSD(zk_conn, osd_id):
    if zkhandler.exists(zk_conn, '/ceph/osds/{}'.format(osd_id)):
        return True
    else:
        return False

# Verify Pool is valid in cluster
def verifyPool(zk_conn, name):
    if zkhandler.exists(zk_conn, '/ceph/pools/{}'.format(name)):
        return True
    else:
        return False

# Verify Volume is valid in cluster
def verifyVolume(zk_conn, pool, name):
    if zkhandler.exists(zk_conn, '/ceph/volumes/{}/{}'.format(pool, name)):
        return True
    else:
        return False

# Verify Snapshot is valid in cluster
def verifySnapshot(zk_conn, pool, volume, name):
    if zkhandler.exists(zk_conn, '/ceph/snapshots/{}/{}/{}'.format(pool, volume, name)):
        return True
    else:
        return False

# Verify OSD path is valid in cluster
def verifyOSDBlock(zk_conn, node, device):
    for osd in zkhandler.listchildren(zk_conn, '/ceph/osds'):
        osd_node = zkhandler.readdata(zk_conn, '/ceph/osds/{}/node'.format(osd))
        osd_device = zkhandler.readdata(zk_conn, '/ceph/osds/{}/device'.format(osd))
        if node == osd_node and device == osd_device:
            return osd
    return None

# Format byte sizes in human-readable units
def format_bytes(databytes):
    unit_matrix = {
        'K': 1024,
        'M': 1024*1024,
        'G': 1024*1024*1024,
        'T': 1024*1024*1024*1024,
        'P': 1024*1024*1024*1024*1024
    }
    databytes_formatted = ''
    if databytes > 9999:
        for unit in sorted(unit_matrix, key=unit_matrix.get, reverse=True):
            new_bytes = int(math.ceil(databytes / unit_matrix[unit]))
            # Round up if 5 or more digits
            if new_bytes > 9999:
                # We can jump down another level
                continue
            else:
                # We're at the end, display with this size
                databytes_formatted = '{}{}'.format(new_bytes, unit)
    else:
        databytes_formatted = '{}B'.format(databytes)

    return databytes_formatted

#
# Cluster search functions
#
def getClusterOSDList(zk_conn):
    # Get a list of VNIs by listing the children of /networks
    osd_list = zkhandler.listchildren(zk_conn, '/ceph/osds')
    return osd_list

def getOSDInformation(zk_conn, osd_id):
    # Parse the stats data
    osd_stats_raw = zkhandler.readdata(zk_conn, '/ceph/osds/{}/stats'.format(osd_id))
    osd_stats = dict(json.loads(osd_stats_raw))
    # Deal with the size
    databytes = osd_stats['kb'] * 1024
    databytes_formatted = format_bytes(databytes)
    osd_stats['size'] = databytes_formatted
    return osd_stats

def getCephOSDs(zk_conn):
    osd_list = zkhandler.listchildren(zk_conn, '/ceph/osds')
    return osd_list

def formatOSDList(zk_conn, osd_list):
    osd_list_output = []

    osd_uuid = dict()
    osd_up = dict()
    osd_up_colour = dict()
    osd_in = dict()
    osd_in_colour = dict()
    osd_size = dict()
    osd_weight = dict()
    osd_reweight = dict()
    osd_pgs = dict()
    osd_node = dict()
    osd_used = dict()
    osd_free = dict()
    osd_util = dict()
    osd_var= dict()
    osd_wrops = dict()
    osd_wrdata = dict()
    osd_rdops = dict()
    osd_rddata = dict()

    osd_id_length = 3
    osd_up_length = 4
    osd_in_length = 4
    osd_size_length = 5
    osd_weight_length = 3
    osd_reweight_length = 5
    osd_pgs_length = 4
    osd_node_length = 5
    osd_used_length = 5
    osd_free_length = 6
    osd_util_length = 6
    osd_var_length = 6
    osd_wrops_length = 4
    osd_wrdata_length = 5
    osd_rdops_length = 4
    osd_rddata_length = 5

    for osd in osd_list:
        # Set the OSD ID length
        _osd_id_length = len(osd) + 1
        if _osd_id_length > osd_id_length:
            osd_id_length = _osd_id_length

        # Get stats
        osd_stats = getOSDInformation(zk_conn, osd)

        # Set the parent node and length
        try:
            osd_node[osd] = osd_stats['node']
            # If this happens, the node hasn't checked in fully yet, so just ignore it
            if osd_node[osd] == '|':
                continue
        except KeyError:
            continue

        _osd_node_length = len(osd_node[osd]) + 1
        if _osd_node_length > osd_node_length:
            osd_node_length = _osd_node_length

        # Set the UP status
        if osd_stats['up'] == 1:
            osd_up[osd] = 'Yes'
            osd_up_colour[osd] = ansiprint.green()
        else:
            osd_up[osd] = 'No'
            osd_up_colour[osd] = ansiprint.red()

        # Set the IN status
        if osd_stats['in'] == 1:
            osd_in[osd] = 'Yes'
            osd_in_colour[osd] = ansiprint.green()
        else:
            osd_in[osd] = 'No'
            osd_in_colour[osd] = ansiprint.red()

        # Set the size and length
        osd_size[osd] = osd_stats['size']
        _osd_size_length = len(str(osd_size[osd])) + 1
        if _osd_size_length > osd_size_length:
            osd_size_length = _osd_size_length

        # Set the weight and length
        osd_weight[osd] = osd_stats['weight']
        _osd_weight_length = len(str(osd_weight[osd])) + 1
        if _osd_weight_length > osd_weight_length:
            osd_weight_length = _osd_weight_length

        # Set the reweight and length
        osd_reweight[osd] = osd_stats['reweight']
        _osd_reweight_length = len(str(osd_reweight[osd])) + 1
        if _osd_reweight_length > osd_reweight_length:
            osd_reweight_length = _osd_reweight_length

        # Set the pgs and length
        osd_pgs[osd] = osd_stats['pgs']
        _osd_pgs_length = len(str(osd_pgs[osd])) + 1
        if _osd_pgs_length > osd_pgs_length:
            osd_pgs_length = _osd_pgs_length

        # Set the used/available/utlization%/variance and lengths
        osd_used[osd] = osd_stats['used']
        _osd_used_length = len(osd_used[osd]) + 1
        if _osd_used_length > osd_used_length:
            osd_used_length = _osd_used_length
        osd_free[osd] = osd_stats['avail']
        _osd_free_length = len(osd_free[osd]) + 1
        if _osd_free_length > osd_free_length:
            osd_free_length = _osd_free_length
        osd_util[osd] = round(osd_stats['utilization'], 2)
        _osd_util_length = len(str(osd_util[osd])) + 1
        if _osd_util_length > osd_util_length:
            osd_util_length = _osd_util_length
        osd_var[osd] = round(osd_stats['var'], 2)
        _osd_var_length = len(str(osd_var[osd])) + 1
        if _osd_var_length > osd_var_length:
            osd_var_length = _osd_var_length

        # Set the write IOPS/data and length
        osd_wrops[osd] = osd_stats['wr_ops']
        _osd_wrops_length = len(osd_wrops[osd]) + 1
        if _osd_wrops_length > osd_wrops_length:
            osd_wrops_length = _osd_wrops_length
        osd_wrdata[osd] = osd_stats['wr_data']
        _osd_wrdata_length = len(osd_wrdata[osd]) + 1
        if _osd_wrdata_length > osd_wrdata_length:
            osd_wrdata_length = _osd_wrdata_length

        # Set the read IOPS/data and length
        osd_rdops[osd] = osd_stats['rd_ops']
        _osd_rdops_length = len(osd_rdops[osd]) + 1
        if _osd_rdops_length > osd_rdops_length:
            osd_rdops_length = _osd_rdops_length
        osd_rddata[osd] = osd_stats['rd_data']
        _osd_rddata_length = len(osd_rddata[osd]) + 1
        if _osd_rddata_length > osd_rddata_length:
            osd_rddata_length = _osd_rddata_length

    # Format the output header
    osd_list_output_header = '{bold}\
{osd_id: <{osd_id_length}} \
{osd_node: <{osd_node_length}} \
{osd_up: <{osd_up_length}} \
{osd_in: <{osd_in_length}} \
{osd_size: <{osd_size_length}} \
{osd_pgs: <{osd_pgs_length}} \
{osd_weight: <{osd_weight_length}} \
{osd_reweight: <{osd_reweight_length}} \
Sp: {osd_used: <{osd_used_length}} \
{osd_free: <{osd_free_length}} \
{osd_util: <{osd_util_length}} \
{osd_var: <{osd_var_length}} \
Rd: {osd_rdops: <{osd_rdops_length}} \
{osd_rddata: <{osd_rddata_length}} \
Wr: {osd_wrops: <{osd_wrops_length}} \
{osd_wrdata: <{osd_wrdata_length}} \
{end_bold}'.format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            osd_id_length=osd_id_length,
            osd_node_length=osd_node_length,
            osd_up_length=osd_up_length,
            osd_in_length=osd_in_length,
            osd_size_length=osd_size_length,
            osd_pgs_length=osd_pgs_length,
            osd_weight_length=osd_weight_length,
            osd_reweight_length=osd_reweight_length,
            osd_used_length=osd_used_length,
            osd_free_length=osd_free_length,
            osd_util_length=osd_util_length,
            osd_var_length=osd_var_length,
            osd_wrops_length=osd_wrops_length,
            osd_wrdata_length=osd_wrdata_length,
            osd_rdops_length=osd_rdops_length,
            osd_rddata_length=osd_rddata_length,
            osd_id='ID',
            osd_node='Node',
            osd_up='Up',
            osd_in='In',
            osd_size='Size',
            osd_pgs='PGs',
            osd_weight='Wt',
            osd_reweight='ReWt',
            osd_used='Used',
            osd_free='Free',
            osd_util='Util%',
            osd_var='Var',
            osd_wrops='OPS',
            osd_wrdata='Data',
            osd_rdops='OPS',
            osd_rddata='Data'
        )

    for osd in osd_list:
        # Format the output header
        osd_list_output.append('{bold}\
{osd_id: <{osd_id_length}} \
{osd_node: <{osd_node_length}} \
{osd_up_colour}{osd_up: <{osd_up_length}}{end_colour} \
{osd_in_colour}{osd_in: <{osd_in_length}}{end_colour} \
{osd_size: <{osd_size_length}} \
{osd_pgs: <{osd_pgs_length}} \
{osd_weight: <{osd_weight_length}} \
{osd_reweight: <{osd_reweight_length}} \
    {osd_used: <{osd_used_length}} \
{osd_free: <{osd_free_length}} \
{osd_util: <{osd_util_length}} \
{osd_var: <{osd_var_length}} \
    {osd_rdops: <{osd_rdops_length}} \
{osd_rddata: <{osd_rddata_length}} \
    {osd_wrops: <{osd_wrops_length}} \
{osd_wrdata: <{osd_wrdata_length}} \
{end_bold}'.format(
                bold=ansiprint.bold(),
                end_bold=ansiprint.end(),
                end_colour=ansiprint.end(),
                osd_id_length=osd_id_length,
                osd_node_length=osd_node_length,
                osd_up_length=osd_up_length,
                osd_in_length=osd_in_length,
                osd_size_length=osd_size_length,
                osd_pgs_length=osd_pgs_length,
                osd_weight_length=osd_weight_length,
                osd_reweight_length=osd_reweight_length,
                osd_used_length=osd_used_length,
                osd_free_length=osd_free_length,
                osd_util_length=osd_util_length,
                osd_var_length=osd_var_length,
                osd_wrops_length=osd_wrops_length,
                osd_wrdata_length=osd_wrdata_length,
                osd_rdops_length=osd_rdops_length,
                osd_rddata_length=osd_rddata_length,
                osd_id=osd,
                osd_node=osd_node[osd],
                osd_up_colour=osd_up_colour[osd],
                osd_up=osd_up[osd],
                osd_in_colour=osd_in_colour[osd],
                osd_in=osd_in[osd],
                osd_size=osd_size[osd],
                osd_pgs=osd_pgs[osd],
                osd_weight=osd_weight[osd],
                osd_reweight=osd_reweight[osd],
                osd_used=osd_used[osd],
                osd_free=osd_free[osd],
                osd_util=osd_util[osd],
                osd_var=osd_var[osd],
                osd_wrops=osd_wrops[osd],
                osd_wrdata=osd_wrdata[osd],
                osd_rdops=osd_rdops[osd],
                osd_rddata=osd_rddata[osd]
            )
        )
   
    output_string = osd_list_output_header + '\n' + '\n'.join(sorted(osd_list_output))
    return output_string

def getClusterPoolList(zk_conn):
    # Get a list of pools under /ceph/pools
    pool_list = zkhandler.listchildren(zk_conn, '/ceph/pools')
    return pool_list

def getPoolInformation(zk_conn, name):
    # Parse the stats data
    pool_stats_raw = zkhandler.readdata(zk_conn, '/ceph/pools/{}/stats'.format(name))
    pool_stats = dict(json.loads(pool_stats_raw))
    # Deal with the size issues
    for datatype in 'size_bytes', 'read_bytes', 'write_bytes':
        databytes = pool_stats[datatype]
        databytes_formatted = format_bytes(databytes)
        new_name = datatype.replace('bytes', 'formatted')
        pool_stats[new_name] = databytes_formatted
    return pool_stats

def getCephPools(zk_conn):
    pool_list = zkhandler.listchildren(zk_conn, '/ceph/pools')
    return pool_list

def formatPoolList(zk_conn, pool_list):
    pool_list_output = []

    pool_id = dict()
    pool_size = dict()
    pool_num_objects = dict()
    pool_num_clones = dict()
    pool_num_copies = dict()
    pool_num_degraded = dict()
    pool_read_ops = dict()
    pool_read_data = dict()
    pool_write_ops = dict()
    pool_write_data = dict()

    pool_name_length = 5
    pool_id_length = 3
    pool_size_length = 5
    pool_num_objects_length = 6
    pool_num_clones_length = 7
    pool_num_copies_length = 7
    pool_num_degraded_length = 9
    pool_read_ops_length = 4
    pool_read_data_length = 5
    pool_write_ops_length = 4
    pool_write_data_length = 5

    for pool in pool_list:
        # Set the Pool name length
        _pool_name_length = len(pool) + 1
        if _pool_name_length > pool_name_length:
            pool_name_length = _pool_name_length

        # Get stats
        pool_stats = getPoolInformation(zk_conn, pool)

        # Set the parent node and length
        try:
            pool_id[pool] = pool_stats['id']
            # If this happens, the node hasn't checked in fully yet, so just ignore it
            if not pool_id[pool]:
                continue
        except KeyError:
            continue

        # Set the id and length
        pool_id[pool] = pool_stats['id']
        _pool_id_length = len(str(pool_id[pool])) + 1
        if _pool_id_length > pool_id_length:
            pool_id_length = _pool_id_length

        # Set the size and length
        pool_size[pool] = pool_stats['size_formatted']
        _pool_size_length = len(str(pool_size[pool])) + 1
        if _pool_size_length > pool_size_length:
            pool_size_length = _pool_size_length

        # Set the num_objects and length
        pool_num_objects[pool] = pool_stats['num_objects']
        _pool_num_objects_length = len(str(pool_num_objects[pool])) + 1
        if _pool_num_objects_length > pool_num_objects_length:
            pool_num_objects_length = _pool_num_objects_length

        # Set the num_clones and length
        pool_num_clones[pool] = pool_stats['num_object_clones']
        _pool_num_clones_length = len(str(pool_num_clones[pool])) + 1
        if _pool_num_clones_length > pool_num_clones_length:
            pool_num_clones_length = _pool_num_clones_length

        # Set the num_copies and length
        pool_num_copies[pool] = pool_stats['num_object_copies']
        _pool_num_copies_length = len(str(pool_num_copies[pool])) + 1
        if _pool_num_copies_length > pool_num_copies_length:
            pool_num_copies_length = _pool_num_copies_length

        # Set the num_degraded and length
        pool_num_degraded[pool] = pool_stats['num_objects_degraded']
        _pool_num_degraded_length = len(str(pool_num_degraded[pool])) + 1
        if _pool_num_degraded_length > pool_num_degraded_length:
            pool_num_degraded_length = _pool_num_degraded_length

        # Set the write IOPS/data and length
        pool_write_ops[pool] = pool_stats['write_ops']
        _pool_write_ops_length = len(str(pool_write_ops[pool])) + 1
        if _pool_write_ops_length > pool_write_ops_length:
            pool_write_ops_length = _pool_write_ops_length
        pool_write_data[pool] = pool_stats['write_formatted']
        _pool_write_data_length = len(pool_write_data[pool]) + 1
        if _pool_write_data_length > pool_write_data_length:
            pool_write_data_length = _pool_write_data_length

        # Set the read IOPS/data and length
        pool_read_ops[pool] = pool_stats['read_ops']
        _pool_read_ops_length = len(str(pool_read_ops[pool])) + 1
        if _pool_read_ops_length > pool_read_ops_length:
            pool_read_ops_length = _pool_read_ops_length
        pool_read_data[pool] = pool_stats['read_formatted']
        _pool_read_data_length = len(pool_read_data[pool]) + 1
        if _pool_read_data_length > pool_read_data_length:
            pool_read_data_length = _pool_read_data_length

    # Format the output header
    pool_list_output_header = '{bold}\
{pool_id: <{pool_id_length}} \
{pool_name: <{pool_name_length}} \
{pool_size: <{pool_size_length}} \
Obj: {pool_objects: <{pool_objects_length}} \
{pool_clones: <{pool_clones_length}} \
{pool_copies: <{pool_copies_length}} \
{pool_degraded: <{pool_degraded_length}} \
Rd: {pool_read_ops: <{pool_read_ops_length}} \
{pool_read_data: <{pool_read_data_length}} \
Wr: {pool_write_ops: <{pool_write_ops_length}} \
{pool_write_data: <{pool_write_data_length}} \
{end_bold}'.format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            pool_id_length=pool_id_length,
            pool_name_length=pool_name_length,
            pool_size_length=pool_size_length,
            pool_objects_length=pool_num_objects_length,
            pool_clones_length=pool_num_clones_length,
            pool_copies_length=pool_num_copies_length,
            pool_degraded_length=pool_num_degraded_length,
            pool_write_ops_length=pool_write_ops_length,
            pool_write_data_length=pool_write_data_length,
            pool_read_ops_length=pool_read_ops_length,
            pool_read_data_length=pool_read_data_length,
            pool_id='ID',
            pool_name='Name',
            pool_size='Used',
            pool_objects='Count',
            pool_clones='Clones',
            pool_copies='Copies',
            pool_degraded='Degraded',
            pool_write_ops='OPS',
            pool_write_data='Data',
            pool_read_ops='OPS',
            pool_read_data='Data'
        )

    for pool in pool_list:
        # Format the output header
        pool_list_output.append('{bold}\
{pool_id: <{pool_id_length}} \
{pool_name: <{pool_name_length}} \
{pool_size: <{pool_size_length}} \
     {pool_objects: <{pool_objects_length}} \
{pool_clones: <{pool_clones_length}} \
{pool_copies: <{pool_copies_length}} \
{pool_degraded: <{pool_degraded_length}} \
    {pool_read_ops: <{pool_read_ops_length}} \
{pool_read_data: <{pool_read_data_length}} \
    {pool_write_ops: <{pool_write_ops_length}} \
{pool_write_data: <{pool_write_data_length}} \
{end_bold}'.format(
                bold=ansiprint.bold(),
                end_bold=ansiprint.end(),
                pool_id_length=pool_id_length,
                pool_name_length=pool_name_length,
                pool_size_length=pool_size_length,
                pool_objects_length=pool_num_objects_length,
                pool_clones_length=pool_num_clones_length,
                pool_copies_length=pool_num_copies_length,
                pool_degraded_length=pool_num_degraded_length,
                pool_write_ops_length=pool_write_ops_length,
                pool_write_data_length=pool_write_data_length,
                pool_read_ops_length=pool_read_ops_length,
                pool_read_data_length=pool_read_data_length,
                pool_id=pool_id[pool],
                pool_name=pool,
                pool_size=pool_size[pool],
                pool_objects=pool_num_objects[pool],
                pool_clones=pool_num_clones[pool],
                pool_copies=pool_num_copies[pool],
                pool_degraded=pool_num_degraded[pool],
                pool_write_ops=pool_write_ops[pool],
                pool_write_data=pool_write_data[pool],
                pool_read_ops=pool_read_ops[pool],
                pool_read_data=pool_read_data[pool]
            )
        )
   
    output_string = pool_list_output_header + '\n' + '\n'.join(sorted(pool_list_output))
    return output_string

def getCephVolumes(zk_conn, pool):
    volume_list = list()
    if pool == 'all':
        pool_list = zkhandler.listchildren(zk_conn, '/ceph/pools')
    else:
        pool_list = [ pool ]

    for pool_name in pool_list:
        for volume_name in zkhandler.listchildren(zk_conn, '/ceph/volumes/{}'.format(pool_name)):
            volume_list.append('{}/{}'.format(pool_name, volume_name))

    return volume_list

def getVolumeInformation(zk_conn, pool, name):
    # Parse the stats data
    volume_stats_raw = zkhandler.readdata(zk_conn, '/ceph/volumes/{}/{}/stats'.format(pool, name))
    volume_stats = dict(json.loads(volume_stats_raw))
    # Format the size to something nicer
    volume_stats['size'] = format_bytes(volume_stats['size'])
    return volume_stats

def formatVolumeList(zk_conn, volume_list):
    volume_list_output = []

    volume_size = dict()
    volume_objects = dict()
    volume_order = dict()
    volume_format = dict()
    volume_features = dict()

    volume_name_length = 5
    volume_pool_length = 5
    volume_size_length = 5
    volume_objects_length = 8
    volume_order_length = 6
    volume_format_length = 7
    volume_features_length = 10

    for volume in volume_list:
        volume_pool, volume_name = volume.split('/')

        # Set the Volume name length
        _volume_name_length = len(volume_name) + 1
        if _volume_name_length > volume_name_length:
            volume_name_length = _volume_name_length

        # Set the Volume pool length
        _volume_pool_length = len(volume_pool) + 1
        if _volume_pool_length > volume_pool_length:
            volume_pool_length = _volume_pool_length

        # Get stats
        volume_stats = getVolumeInformation(zk_conn, volume_pool, volume_name)

        # Set the size and length
        volume_size[volume] = volume_stats['size']
        _volume_size_length = len(str(volume_size[volume])) + 1
        if _volume_size_length > volume_size_length:
            volume_size_length = _volume_size_length

        # Set the num_objects and length
        volume_objects[volume] = volume_stats['objects']
        _volume_objects_length = len(str(volume_objects[volume])) + 1
        if _volume_objects_length > volume_objects_length:
            volume_objects_length = _volume_objects_length

        # Set the order and length
        volume_order[volume] = volume_stats['order']
        _volume_order_length = len(str(volume_order[volume])) + 1
        if _volume_order_length > volume_order_length:
            volume_order_length = _volume_order_length

        # Set the format and length
        volume_format[volume] = volume_stats['format']
        _volume_format_length = len(str(volume_format[volume])) + 1
        if _volume_format_length > volume_format_length:
            volume_format_length = _volume_format_length

        # Set the features and length
        volume_features[volume] = ','.join(volume_stats['features'])
        _volume_features_length = len(str(volume_features[volume])) + 1
        if _volume_features_length > volume_features_length:
            volume_features_length = _volume_features_length

    # Format the output header
    volume_list_output_header = '{bold}\
{volume_name: <{volume_name_length}} \
{volume_pool: <{volume_pool_length}} \
{volume_size: <{volume_size_length}} \
{volume_objects: <{volume_objects_length}} \
{volume_order: <{volume_order_length}} \
{volume_format: <{volume_format_length}} \
{volume_features: <{volume_features_length}} \
{end_bold}'.format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            volume_name_length=volume_name_length,
            volume_pool_length=volume_pool_length,
            volume_size_length=volume_size_length,
            volume_objects_length=volume_objects_length,
            volume_order_length=volume_order_length,
            volume_format_length=volume_format_length,
            volume_features_length=volume_features_length,
            volume_name='Name',
            volume_pool='Pool',
            volume_size='Size',
            volume_objects='Objects',
            volume_order='Order',
            volume_format='Format',
            volume_features='Features',
        )

    for volume in volume_list:
        volume_pool, volume_name = volume.split('/')
        volume_list_output.append('{bold}\
{volume_name: <{volume_name_length}} \
{volume_pool: <{volume_pool_length}} \
{volume_size: <{volume_size_length}} \
{volume_objects: <{volume_objects_length}} \
{volume_order: <{volume_order_length}} \
{volume_format: <{volume_format_length}} \
{volume_features: <{volume_features_length}} \
{end_bold}'.format(
                bold=ansiprint.bold(),
                end_bold=ansiprint.end(),
                volume_name_length=volume_name_length,
                volume_pool_length=volume_pool_length,
                volume_size_length=volume_size_length,
                volume_objects_length=volume_objects_length,
                volume_order_length=volume_order_length,
                volume_format_length=volume_format_length,
                volume_features_length=volume_features_length,
                volume_name=volume_name,
                volume_pool=volume_pool,
                volume_size=volume_size[volume],
                volume_objects=volume_objects[volume],
                volume_order=volume_order[volume],
                volume_format=volume_format[volume],
                volume_features=volume_features[volume],
            )
        )
   
    output_string = volume_list_output_header + '\n' + '\n'.join(sorted(volume_list_output))
    return output_string

def getCephSnapshots(zk_conn, pool, volume):
    snapshot_list = list()
    volume_list = list()

    if volume == 'all':
        volume_list = getCephVolumes(zk_conn, pool)
    else:
        volume_list = [ '{}/{}'.format(pool, volume) ]

    for volume_name in volume_list:
        for snapshot_name in zkhandler.listchildren(zk_conn, '/ceph/snapshots/{}'.format(volume_name)):
            snapshot_list.append('{}@{}'.format(volume_name, snapshot_name))

    return snapshot_list

def formatSnapshotList(zk_conn, snapshot_list):
    snapshot_list_output = []

    snapshot_name_length = 5
    snapshot_volume_length = 7
    snapshot_pool_length = 5

    for snapshot in snapshot_list:
        snapshot_pool, snapshot_detail = snapshot.split('/')
        snapshot_volume, snapshot_name = snapshot_detail.split('@')

        # Set the Snapshot name length
        _snapshot_name_length = len(snapshot_name) + 1
        if _snapshot_name_length > snapshot_name_length:
            snapshot_name_length = _snapshot_name_length

        # Set the Snapshot volume length
        _snapshot_volume_length = len(snapshot_volume) + 1
        if _snapshot_volume_length > snapshot_volume_length:
            snapshot_volume_length = _snapshot_volume_length

        # Set the Snapshot pool length
        _snapshot_pool_length = len(snapshot_pool) + 1
        if _snapshot_pool_length > snapshot_pool_length:
            snapshot_pool_length = _snapshot_pool_length

    # Format the output header
    snapshot_list_output_header = '{bold}\
{snapshot_name: <{snapshot_name_length}} \
{snapshot_volume: <{snapshot_volume_length}} \
{snapshot_pool: <{snapshot_pool_length}} \
{end_bold}'.format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            snapshot_name_length=snapshot_name_length,
            snapshot_volume_length=snapshot_volume_length,
            snapshot_pool_length=snapshot_pool_length,
            snapshot_name='Name',
            snapshot_volume='Volume',
            snapshot_pool='Pool',
        )

    for snapshot in snapshot_list:
        snapshot_pool, snapshot_detail = snapshot.split('/')
        snapshot_volume, snapshot_name = snapshot_detail.split('@')
        snapshot_list_output.append('{bold}\
{snapshot_name: <{snapshot_name_length}} \
{snapshot_volume: <{snapshot_volume_length}} \
{snapshot_pool: <{snapshot_pool_length}} \
{end_bold}'.format(
                bold=ansiprint.bold(),
                end_bold=ansiprint.end(),
                snapshot_name_length=snapshot_name_length,
                snapshot_volume_length=snapshot_volume_length,
                snapshot_pool_length=snapshot_pool_length,
                snapshot_name=snapshot_name,
                snapshot_volume=snapshot_volume,
                snapshot_pool=snapshot_pool,
            )
        )
   
    output_string = snapshot_list_output_header + '\n' + '\n'.join(sorted(snapshot_list_output))
    return output_string

#
# Direct functions
#
def get_status(zk_conn):
    status_data = zkhandler.readdata(zk_conn, '/ceph').rstrip()
    primary_node = zkhandler.readdata(zk_conn, '/primary_node')
    click.echo('{bold}Ceph cluster status (primary node {end}{blue}{primary}{end}{bold}){end}\n'.format(bold=ansiprint.bold(), end=ansiprint.end(), blue=ansiprint.blue(), primary=primary_node))
    click.echo(status_data)
    click.echo('')
    return True, ''

def add_osd(zk_conn, node, device, weight):
    # Verify the target node exists
    if not common.verifyNode(zk_conn, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    # Verify target block device isn't in use
    block_osd = verifyOSDBlock(zk_conn, node, device)
    if block_osd:
        return False, 'ERROR: Block device {} on node {} is used by OSD {}'.format(device, node, block_osd)

    # Tell the cluster to create a new OSD for the host
    add_osd_string = 'osd_add {},{},{}'.format(node, device, weight) 
    zkhandler.writedata(zk_conn, {'/ceph/cmd': add_osd_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/ceph/cmd')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/ceph/cmd').split()[0]
            if result == 'success-osd_add':
                message = 'Created new OSD with block device {} on node {}.'.format(device, node)
                success = True
            else:
                message = 'ERROR: Failed to create new OSD; check node logs for details.'
                success = False
        except:
            message = 'ERROR: Command ignored by node.'
            success = False

    zkhandler.writedata(zk_conn, {'/ceph/cmd': ''})
    return success, message

def remove_osd(zk_conn, osd_id):
    if not verifyOSD(zk_conn, osd_id):
        return False, 'ERROR: No OSD with ID "{}" is present in the cluster.'.format(osd_id)

    # Tell the cluster to remove an OSD
    remove_osd_string = 'osd_remove {}'.format(osd_id)
    zkhandler.writedata(zk_conn, {'/ceph/cmd': remove_osd_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/ceph/cmd')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/ceph/cmd').split()[0]
            if result == 'success-osd_remove':
                message = 'Removed OSD {} from the cluster.'.format(osd_id)
                success = True
            else:
                message = 'ERROR: Failed to remove OSD; check node logs for details.'
                success = False
        except:
            success = False
            message = 'ERROR Command ignored by node.'

    zkhandler.writedata(zk_conn, {'/ceph/cmd': ''})
    return success, message

def in_osd(zk_conn, osd_id):
    if not verifyOSD(zk_conn, osd_id):
        return False, 'ERROR: No OSD with ID "{}" is present in the cluster.'.format(osd_id)

    # Tell the cluster to online an OSD
    in_osd_string = 'osd_in {}'.format(osd_id)
    zkhandler.writedata(zk_conn, {'/ceph/cmd': in_osd_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/ceph/cmd')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/ceph/cmd').split()[0]
            if result == 'success-osd_in':
                message = 'Set OSD {} online in the cluster.'.format(osd_id)
                success = True
            else:
                message = 'ERROR: Failed to set OSD online; check node logs for details.'
                success = False
        except:
            success = False
            message = 'ERROR Command ignored by node.'

    zkhandler.writedata(zk_conn, {'/ceph/cmd': ''})
    return success, message

def out_osd(zk_conn, osd_id):
    if not verifyOSD(zk_conn, osd_id):
        return False, 'ERROR: No OSD with ID "{}" is present in the cluster.'.format(osd_id)

    # Tell the cluster to offline an OSD
    out_osd_string = 'osd_out {}'.format(osd_id)
    zkhandler.writedata(zk_conn, {'/ceph/cmd': out_osd_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/ceph/cmd')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/ceph/cmd').split()[0]
            if result == 'success-osd_out':
                message = 'Set OSD {} offline in the cluster.'.format(osd_id)
                success = True
            else:
                message = 'ERROR: Failed to set OSD offline; check node logs for details.'
                success = False
        except:
            success = False
            message = 'ERROR Command ignored by node.'

    zkhandler.writedata(zk_conn, {'/ceph/cmd': ''})
    return success, message

def set_osd(zk_conn, option):
    # Tell the cluster to set an OSD property
    set_osd_string = 'osd_set {}'.format(option)
    zkhandler.writedata(zk_conn, {'/ceph/cmd': set_osd_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/ceph/cmd')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/ceph/cmd').split()[0]
            if result == 'success-osd_set':
                message = 'Set OSD property {} on the cluster.'.format(option)
                success = True
            else:
                message = 'ERROR: Failed to set OSD property; check node logs for details.'
                success = False
        except:
            success = False
            message = 'ERROR Command ignored by node.'

    zkhandler.writedata(zk_conn, {'/ceph/cmd': ''})
    return success, message

def unset_osd(zk_conn, option):
    # Tell the cluster to unset an OSD property
    unset_osd_string = 'osd_unset {}'.format(option)
    zkhandler.writedata(zk_conn, {'/ceph/cmd': unset_osd_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/ceph/cmd')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/ceph/cmd').split()[0]
            if result == 'success-osd_unset':
                message = 'Unset OSD property {} on the cluster.'.format(option)
                success = True
            else:
                message = 'ERROR: Failed to unset OSD property; check node logs for details.'
                success = False
        except:
            success = False
            message = 'ERROR Command ignored by node.'

    zkhandler.writedata(zk_conn, {'/ceph/cmd': ''})
    return success, message

def get_list_osd(zk_conn, limit):
    osd_list = []
    full_osd_list = getCephOSDs(zk_conn)

    if limit:
        try:
            # Implicitly assume fuzzy limits
            if re.match('\^.*', limit) == None:
                limit = '.*' + limit
            if re.match('.*\$', limit) == None:
                limit = limit + '.*'
        except Exception as e:
            return False, 'Regex Error: {}'.format(e)

    for osd in full_osd_list:
        valid_osd = False
        if limit:
            if re.match(limit, osd['osd_id']) != None:
                valid_osd = True
        else:
            valid_osd = True

        if valid_osd:
            osd_list.append(osd)

    output_string = formatOSDList(zk_conn, osd_list)
    click.echo(output_string)

    return True, ''

def add_pool(zk_conn, name, pgs):
    # Tell the cluster to create a new pool
    add_pool_string = 'pool_add {},{}'.format(name, pgs) 
    zkhandler.writedata(zk_conn, {'/ceph/cmd': add_pool_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/ceph/cmd')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/ceph/cmd').split()[0]
            if result == 'success-pool_add':
                message = 'Created new RBD pool {} with {} PGs.'.format(name, pgs)
                success = True
            else:
                message = 'ERROR: Failed to create new pool; check node logs for details.'
                success = False
        except:
            message = 'ERROR: Command ignored by node.'
            success = False

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
    with lock:
        time.sleep(3)
        zkhandler.writedata(zk_conn, {'/ceph/cmd': ''})

    return success, message

def remove_pool(zk_conn, name):
    if not verifyPool(zk_conn, name):
        return False, 'ERROR: No pool with name "{}" is present in the cluster.'.format(name)

    # Tell the cluster to create a new pool
    remove_pool_string = 'pool_remove {}'.format(name) 
    zkhandler.writedata(zk_conn, {'/ceph/cmd': remove_pool_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/ceph/cmd')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/ceph/cmd').split()[0]
            if result == 'success-pool_remove':
                message = 'Removed RBD pool {} and all volumes.'.format(name)
                success = True
            else:
                message = 'ERROR: Failed to remove pool; check node logs for details.'
                success = False
        except Exception as e:
            message = 'ERROR: Command ignored by node: {}'.format(e)
            success = False

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
    with lock:
        time.sleep(3)
        zkhandler.writedata(zk_conn, {'/ceph/cmd': ''})

    return success, message

def get_list_pool(zk_conn, limit):
    pool_list = []
    full_pool_list = getCephPools(zk_conn)

    if limit:
        try:
            # Implicitly assume fuzzy limits
            if re.match('\^.*', limit) == None:
                limit = '.*' + limit
            if re.match('.*\$', limit) == None:
                limit = limit + '.*'
        except Exception as e:
            return False, 'Regex Error: {}'.format(e)

    for pool in full_pool_list:
        valid_pool = False
        if limit:
            if re.match(limit, pool['pool_id']) != None:
                valid_pool = True
        else:
            valid_pool = True

        if valid_pool:
            pool_list.append(pool)

    output_string = formatPoolList(zk_conn, pool_list)
    click.echo(output_string)

    return True, ''

def add_volume(zk_conn, pool, name, size):
    # Tell the cluster to create a new volume
    add_volume_string = 'volume_add {},{},{}'.format(pool, name, size) 
    zkhandler.writedata(zk_conn, {'/ceph/cmd': add_volume_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/ceph/cmd')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/ceph/cmd').split()[0]
            if result == 'success-volume_add':
                message = 'Created new RBD volume {} of size {} GiB on pool {}.'.format(name, size, pool)
                success = True
            else:
                message = 'ERROR: Failed to create new volume; check node logs for details.'
                success = False
        except:
            message = 'ERROR: Command ignored by node.'
            success = False

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
    with lock:
        time.sleep(1)
        zkhandler.writedata(zk_conn, {'/ceph/cmd': ''})

    return success, message

def remove_volume(zk_conn, pool, name):
    if not verifyVolume(zk_conn, pool, name):
        return False, 'ERROR: No volume with name "{}" is present in pool {}.'.format(name, pool)

    # Tell the cluster to create a new volume
    remove_volume_string = 'volume_remove {},{}'.format(pool, name) 
    zkhandler.writedata(zk_conn, {'/ceph/cmd': remove_volume_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/ceph/cmd')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/ceph/cmd').split()[0]
            if result == 'success-volume_remove':
                message = 'Removed RBD volume {} in pool {}.'.format(name, pool)
                success = True
            else:
                message = 'ERROR: Failed to remove volume; check node logs for details.'
                success = False
        except Exception as e:
            message = 'ERROR: Command ignored by node: {}'.format(e)
            success = False

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
    with lock:
        time.sleep(1)
        zkhandler.writedata(zk_conn, {'/ceph/cmd': ''})

    return success, message

def get_list_volume(zk_conn, pool, limit):
    volume_list = []
    full_volume_list = getCephVolumes(zk_conn, pool)

    if limit:
        try:
            # Implicitly assume fuzzy limits
            if re.match('\^.*', limit) == None:
                limit = '.*' + limit
            if re.match('.*\$', limit) == None:
                limit = limit + '.*'
        except Exception as e:
            return False, 'Regex Error: {}'.format(e)

    for volume in full_volume_list:
        valid_volume = False
        if limit:
            if re.match(limit, volume) != None:
                valid_volume = True
        else:
            valid_volume = True

        if valid_volume:
            volume_list.append(volume)

    output_string = formatVolumeList(zk_conn, volume_list)
    click.echo(output_string)

    return True, ''

def add_snapshot(zk_conn, pool, volume, name):
    # Tell the cluster to create a new snapshot
    add_snapshot_string = 'snapshot_add {},{},{}'.format(pool, volume, name) 
    zkhandler.writedata(zk_conn, {'/ceph/cmd': add_snapshot_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/ceph/cmd')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/ceph/cmd').split()[0]
            if result == 'success-snapshot_add':
                message = 'Created new RBD snapshot {} of volume {} on pool {}.'.format(name, volume, pool)
                success = True
            else:
                message = 'ERROR: Failed to create new snapshot; check node logs for details.'
                success = False
        except:
            message = 'ERROR: Command ignored by node.'
            success = False

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
    with lock:
        time.sleep(1)
        zkhandler.writedata(zk_conn, {'/ceph/cmd': ''})

    return success, message

def remove_snapshot(zk_conn, pool, volume, name):
    if not verifySnapshot(zk_conn, pool, volume, name):
        return False, 'ERROR: No snapshot with name "{}" is present of volume {} on pool {}.'.format(name, volume, pool)

    # Tell the cluster to create a new snapshot
    remove_snapshot_string = 'snapshot_remove {},{},{}'.format(pool, volume, name) 
    zkhandler.writedata(zk_conn, {'/ceph/cmd': remove_snapshot_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/ceph/cmd')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/ceph/cmd').split()[0]
            if result == 'success-snapshot_remove':
                message = 'Removed RBD snapshot {} and all volumes.'.format(name)
                success = True
            else:
                message = 'ERROR: Failed to remove snapshot; check node logs for details.'
                success = False
        except Exception as e:
            message = 'ERROR: Command ignored by node: {}'.format(e)
            success = False

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/ceph/cmd')
    with lock:
        time.sleep(1)
        zkhandler.writedata(zk_conn, {'/ceph/cmd': ''})

    return success, message

def get_list_snapshot(zk_conn, pool, volume, limit):
    snapshot_list = []
    full_snapshot_list = getCephSnapshots(zk_conn, pool, volume)

    if limit:
        try:
            # Implicitly assume fuzzy limits
            if re.match('\^.*', limit) == None:
                limit = '.*' + limit
            if re.match('.*\$', limit) == None:
                limit = limit + '.*'
        except Exception as e:
            return False, 'Regex Error: {}'.format(e)

    for snapshot in full_snapshot_list:
        valid_snapshot = False
        if limit:
            if re.match(limit, snapshot['snapshot_id']) != None:
                valid_snapshot = True
        else:
            valid_snapshot = True

        if valid_snapshot:
            snapshot_list.append(snapshot)

    output_string = formatSnapshotList(zk_conn, snapshot_list)
    click.echo(output_string)

    return True, ''

