
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

# Format byte sizes to/from human-readable units
byte_unit_matrix = {
    'B': 1,
    'K': 1024,
    'M': 1024*1024,
    'G': 1024*1024*1024,
    'T': 1024*1024*1024*1024,
    'P': 1024*1024*1024*1024*1024
}
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
    dataunit = datahuman[-1]
    datasize = int(datahuman[:-1])
    databytes = datasize * byte_unit_matrix[dataunit]
    return '{}B'.format(databytes)

# Format ops sizes to/from human-readable units
ops_unit_matrix = {
    '': 1,
    'K': 1000,
    'M': 1000*1000,
    'G': 1000*1000*1000,
    'T': 1000*1000*1000*1000,
    'P': 1000*1000*1000*1000*1000
}
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

#
# Status functions
#
def get_status(zk_conn):
    primary_node = zkhandler.readdata(zk_conn, '/primary_node')
    ceph_status = zkhandler.readdata(zk_conn, '/ceph').rstrip()

    # Create a data structure for the information
    status_data = {
        'type': 'status',
        'primary_node': primary_node,
        'ceph_data': ceph_status
    }
    return True, status_data

def get_radosdf(zk_conn):
    primary_node = zkhandler.readdata(zk_conn, '/primary_node')
    ceph_df = zkhandler.readdata(zk_conn, '/ceph/radosdf').rstrip()

    # Create a data structure for the information
    status_data = {
        'type': 'utilization',
        'primary_node': primary_node,
        'ceph_data': ceph_df
    }
    return True, status_data

def format_raw_output(status_data):
    click.echo('{bold}Ceph cluster {stype} (primary node {end}{blue}{primary}{end}{bold}){end}\n'.format(bold=ansiprint.bold(), end=ansiprint.end(), blue=ansiprint.blue(), stype=status_data['type'], primary=status_data['primary_node']))
    click.echo(status_data['ceph_data'])
    click.echo('')

#
# OSD functions
#
def getClusterOSDList(zk_conn):
    # Get a list of VNIs by listing the children of /networks
    osd_list = zkhandler.listchildren(zk_conn, '/ceph/osds')
    return osd_list

def getOSDInformation(zk_conn, osd_id):
    # Parse the stats data
    osd_stats_raw = zkhandler.readdata(zk_conn, '/ceph/osds/{}/stats'.format(osd_id))
    osd_stats = dict(json.loads(osd_stats_raw))

    osd_information = {
        'id': osd_id,
        'stats': osd_stats
    }
    return osd_information

def getOutputColoursOSD(osd_information):
    # Set the UP status
    if osd_information['stats']['up'] == 1:
        osd_up_flag = 'Yes'
        osd_up_colour = ansiprint.green()
    else:
        osd_up_flag = 'No'
        osd_up_colour = ansiprint.red()

    # Set the IN status
    if osd_information['stats']['in'] == 1:
        osd_in_flag = 'Yes'
        osd_in_colour = ansiprint.green()
    else:
        osd_in_flag = 'No'
        osd_in_colour = ansiprint.red()

    return osd_up_flag, osd_up_colour, osd_in_flag, osd_in_colour

def add_osd(zk_conn, node, device, weight):
    # Verify the target node exists
    if not common.verifyNode(zk_conn, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    # Verify target block device isn't in use
    block_osd = verifyOSDBlock(zk_conn, node, device)
    if block_osd:
        return False, 'ERROR: Block device "{}" on node "{}" is used by OSD "{}"'.format(device, node, block_osd)

    # Tell the cluster to create a new OSD for the host
    add_osd_string = 'osd_add {},{},{}'.format(node, device, weight)
    zkhandler.writedata(zk_conn, {'/cmd/ceph': add_osd_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/cmd/ceph')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/cmd/ceph').split()[0]
            if result == 'success-osd_add':
                message = 'Created new OSD with block device "{}" on node "{}".'.format(device, node)
                success = True
            else:
                message = 'ERROR: Failed to create new OSD; check node logs for details.'
                success = False
        except:
            message = 'ERROR: Command ignored by node.'
            success = False

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/cmd/ceph')
    with lock:
        time.sleep(5)
        zkhandler.writedata(zk_conn, {'/cmd/ceph': ''})

    return success, message

def remove_osd(zk_conn, osd_id):
    if not verifyOSD(zk_conn, osd_id):
        return False, 'ERROR: No OSD with ID "{}" is present in the cluster.'.format(osd_id)

    # Tell the cluster to remove an OSD
    remove_osd_string = 'osd_remove {}'.format(osd_id)
    zkhandler.writedata(zk_conn, {'/cmd/ceph': remove_osd_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/cmd/ceph')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/cmd/ceph').split()[0]
            if result == 'success-osd_remove':
                message = 'Removed OSD "{}" from the cluster.'.format(osd_id)
                success = True
            else:
                message = 'ERROR: Failed to remove OSD; check node logs for details.'
                success = False
        except:
            success = False
            message = 'ERROR Command ignored by node.'

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/cmd/ceph')
    with lock:
        time.sleep(5)
        zkhandler.writedata(zk_conn, {'/cmd/ceph': ''})

    return success, message

def in_osd(zk_conn, osd_id):
    if not verifyOSD(zk_conn, osd_id):
        return False, 'ERROR: No OSD with ID "{}" is present in the cluster.'.format(osd_id)

    # Tell the cluster to online an OSD
    in_osd_string = 'osd_in {}'.format(osd_id)
    zkhandler.writedata(zk_conn, {'/cmd/ceph': in_osd_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/cmd/ceph')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/cmd/ceph').split()[0]
            if result == 'success-osd_in':
                message = 'Set OSD {} online in the cluster.'.format(osd_id)
                success = True
            else:
                message = 'ERROR: Failed to set OSD online; check node logs for details.'
                success = False
        except:
            success = False
            message = 'ERROR Command ignored by node.'

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/cmd/ceph')
    with lock:
        time.sleep(1)
        zkhandler.writedata(zk_conn, {'/cmd/ceph': ''})

    return success, message

def out_osd(zk_conn, osd_id):
    if not verifyOSD(zk_conn, osd_id):
        return False, 'ERROR: No OSD with ID "{}" is present in the cluster.'.format(osd_id)

    # Tell the cluster to offline an OSD
    out_osd_string = 'osd_out {}'.format(osd_id)
    zkhandler.writedata(zk_conn, {'/cmd/ceph': out_osd_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/cmd/ceph')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/cmd/ceph').split()[0]
            if result == 'success-osd_out':
                message = 'Set OSD {} offline in the cluster.'.format(osd_id)
                success = True
            else:
                message = 'ERROR: Failed to set OSD offline; check node logs for details.'
                success = False
        except:
            success = False
            message = 'ERROR Command ignored by node.'

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/cmd/ceph')
    with lock:
        time.sleep(1)
        zkhandler.writedata(zk_conn, {'/cmd/ceph': ''})

    return success, message

def set_osd(zk_conn, option):
    # Tell the cluster to set an OSD property
    set_osd_string = 'osd_set {}'.format(option)
    zkhandler.writedata(zk_conn, {'/cmd/ceph': set_osd_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/cmd/ceph')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/cmd/ceph').split()[0]
            if result == 'success-osd_set':
                message = 'Set OSD property {} on the cluster.'.format(option)
                success = True
            else:
                message = 'ERROR: Failed to set OSD property; check node logs for details.'
                success = False
        except:
            success = False
            message = 'ERROR Command ignored by node.'

    zkhandler.writedata(zk_conn, {'/cmd/ceph': ''})
    return success, message

def unset_osd(zk_conn, option):
    # Tell the cluster to unset an OSD property
    unset_osd_string = 'osd_unset {}'.format(option)
    zkhandler.writedata(zk_conn, {'/cmd/ceph': unset_osd_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/cmd/ceph')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/cmd/ceph').split()[0]
            if result == 'success-osd_unset':
                message = 'Unset OSD property {} on the cluster.'.format(option)
                success = True
            else:
                message = 'ERROR: Failed to unset OSD property; check node logs for details.'
                success = False
        except:
            success = False
            message = 'ERROR Command ignored by node.'

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/cmd/ceph')
    with lock:
        time.sleep(1)
        zkhandler.writedata(zk_conn, {'/cmd/ceph': ''})

    return success, message

def get_list_osd(zk_conn, limit, is_fuzzy=True):
    osd_list = []
    full_osd_list = zkhandler.listchildren(zk_conn, '/ceph/osds')

    if is_fuzzy and limit:
        # Implicitly assume fuzzy limits
        if not re.match('\^.*', limit):
            limit = '.*' + limit
        if not re.match('.*\$', limit):
            limit = limit + '.*'

    for osd in full_osd_list:
        if limit:
            try:
                if re.match(limit, osd):
                    osd_list.append(getOSDInformation(zk_conn, osd))
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            osd_list.append(getOSDInformation(zk_conn, osd))

    return True, osd_list

def format_list_osd(osd_list):
    osd_list_output = []

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
    osd_var_length = 5
    osd_wrops_length = 4
    osd_wrdata_length = 5
    osd_rdops_length = 4
    osd_rddata_length = 5

    for osd_information in osd_list:
        try:
            # If this happens, the node hasn't checked in fully yet, so just ignore it
            if osd_information['stats']['node'] == '|':
                continue
        except KeyError:
            continue

        # Deal with the size to human readable
        osd_information['stats']['size'] = osd_information['stats']['kb'] * 1024
        for datatype in 'size', 'wr_data', 'rd_data':
            databytes = osd_information['stats'][datatype]
            databytes_formatted = format_bytes_tohuman(int(databytes))
            osd_information['stats'][datatype] = databytes_formatted
        for datatype in 'wr_ops', 'rd_ops':
            dataops = osd_information['stats'][datatype]
            dataops_formatted = format_ops_tohuman(int(dataops))
            osd_information['stats'][datatype] = dataops_formatted

        # Set the OSD ID length
        _osd_id_length = len(osd_information['id']) + 1
        if _osd_id_length > osd_id_length:
            osd_id_length = _osd_id_length

        _osd_node_length = len(osd_information['stats']['node']) + 1
        if _osd_node_length > osd_node_length:
            osd_node_length = _osd_node_length

        # Set the size and length
        _osd_size_length = len(str(osd_information['stats']['size'])) + 1
        if _osd_size_length > osd_size_length:
            osd_size_length = _osd_size_length

        # Set the weight and length
        _osd_weight_length = len(str(osd_information['stats']['weight'])) + 1
        if _osd_weight_length > osd_weight_length:
            osd_weight_length = _osd_weight_length

        # Set the reweight and length
        _osd_reweight_length = len(str(osd_information['stats']['reweight'])) + 1
        if _osd_reweight_length > osd_reweight_length:
            osd_reweight_length = _osd_reweight_length

        # Set the pgs and length
        _osd_pgs_length = len(str(osd_information['stats']['pgs'])) + 1
        if _osd_pgs_length > osd_pgs_length:
            osd_pgs_length = _osd_pgs_length

        # Set the used/available/utlization%/variance and lengths
        _osd_used_length = len(osd_information['stats']['used']) + 1
        if _osd_used_length > osd_used_length:
            osd_used_length = _osd_used_length

        _osd_free_length = len(osd_information['stats']['avail']) + 1
        if _osd_free_length > osd_free_length:
            osd_free_length = _osd_free_length

        osd_util = round(osd_information['stats']['utilization'], 2)
        _osd_util_length = len(str(osd_util)) + 1
        if _osd_util_length > osd_util_length:
            osd_util_length = _osd_util_length

        osd_var = round(osd_information['stats']['var'], 2)
        _osd_var_length = len(str(osd_var)) + 1
        if _osd_var_length > osd_var_length:
            osd_var_length = _osd_var_length

        # Set the read/write IOPS/data and length
        _osd_wrops_length = len(osd_information['stats']['wr_ops']) + 1
        if _osd_wrops_length > osd_wrops_length:
            osd_wrops_length = _osd_wrops_length

        _osd_wrdata_length = len(osd_information['stats']['wr_data']) + 1
        if _osd_wrdata_length > osd_wrdata_length:
            osd_wrdata_length = _osd_wrdata_length

        _osd_rdops_length = len(osd_information['stats']['rd_ops']) + 1
        if _osd_rdops_length > osd_rdops_length:
            osd_rdops_length = _osd_rdops_length

        _osd_rddata_length = len(osd_information['stats']['rd_data']) + 1
        if _osd_rddata_length > osd_rddata_length:
            osd_rddata_length = _osd_rddata_length

    # Format the output header
    osd_list_output.append('{bold}\
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
    )

    for osd_information in osd_list:
        try:
            # If this happens, the node hasn't checked in fully yet, so just ignore it
            if osd_information['stats']['node'] == '|':
                continue
        except KeyError:
            continue

        osd_up_flag, osd_up_colour, osd_in_flag, osd_in_colour = getOutputColoursOSD(osd_information)
        osd_util = round(osd_information['stats']['utilization'], 2)
        osd_var = round(osd_information['stats']['var'], 2)

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
                bold='',
                end_bold='',
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
                osd_id=osd_information['id'],
                osd_node=osd_information['stats']['node'],
                osd_up_colour=osd_up_colour,
                osd_up=osd_up_flag,
                osd_in_colour=osd_in_colour,
                osd_in=osd_in_flag,
                osd_size=osd_information['stats']['size'],
                osd_pgs=osd_information['stats']['pgs'],
                osd_weight=osd_information['stats']['weight'],
                osd_reweight=osd_information['stats']['reweight'],
                osd_used=osd_information['stats']['used'],
                osd_free=osd_information['stats']['avail'],
                osd_util=osd_util,
                osd_var=osd_var,
                osd_wrops=osd_information['stats']['wr_ops'],
                osd_wrdata=osd_information['stats']['wr_data'],
                osd_rdops=osd_information['stats']['rd_ops'],
                osd_rddata=osd_information['stats']['rd_data']
            )
        )

    click.echo('\n'.join(sorted(osd_list_output)))


#
# Pool functions
#
def getPoolInformation(zk_conn, pool):
    # Parse the stats data
    pool_stats_raw = zkhandler.readdata(zk_conn, '/ceph/pools/{}/stats'.format(pool))
    pool_stats = dict(json.loads(pool_stats_raw))

    pool_information = {
        'name': pool,
        'stats': pool_stats
    }
    return pool_information

def add_pool(zk_conn, name, pgs, replcfg):
    # Tell the cluster to create a new pool
    add_pool_string = 'pool_add {},{},{}'.format(name, pgs, replcfg)
    zkhandler.writedata(zk_conn, {'/cmd/ceph': add_pool_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/cmd/ceph')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/cmd/ceph').split()[0]
            if result == 'success-pool_add':
                message = 'Created new RBD pool "{}" with "{}" PGs and replication configuration {}.'.format(name, pgs, replcfg)
                success = True
            else:
                message = 'ERROR: Failed to create new pool; check node logs for details.'
                success = False
        except:
            message = 'ERROR: Command ignored by node.'
            success = False

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/cmd/ceph')
    with lock:
        time.sleep(3)
        zkhandler.writedata(zk_conn, {'/cmd/ceph': ''})

    return success, message

def remove_pool(zk_conn, name):
    if not verifyPool(zk_conn, name):
        return False, 'ERROR: No pool with name "{}" is present in the cluster.'.format(name)

    # Tell the cluster to create a new pool
    remove_pool_string = 'pool_remove {}'.format(name)
    zkhandler.writedata(zk_conn, {'/cmd/ceph': remove_pool_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/cmd/ceph')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/cmd/ceph').split()[0]
            if result == 'success-pool_remove':
                message = 'Removed RBD pool "{}" and all volumes.'.format(name)
                success = True
            else:
                message = 'ERROR: Failed to remove pool; check node logs for details.'
                success = False
        except Exception as e:
            message = 'ERROR: Command ignored by node: {}'.format(e)
            success = False

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/cmd/ceph')
    with lock:
        time.sleep(3)
        zkhandler.writedata(zk_conn, {'/cmd/ceph': ''})

    return success, message

def get_list_pool(zk_conn, limit, is_fuzzy=True):
    pool_list = []
    full_pool_list = zkhandler.listchildren(zk_conn, '/ceph/pools')

    if is_fuzzy and limit:
        # Implicitly assume fuzzy limits
        if not re.match('\^.*', limit):
            limit = '.*' + limit
        if not re.match('.*\$', limit):
            limit = limit + '.*'

    for pool in full_pool_list:
        if limit:
            try:
                if re.match(limit, pool):
                    pool_list.append(getPoolInformation(zk_conn, pool))
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            pool_list.append(getPoolInformation(zk_conn, pool))

    return True, pool_list

def format_list_pool(pool_list):
    pool_list_output = []

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

    for pool_information in pool_list:
        # Deal with the size to human readable
        for datatype in 'size_bytes', 'write_bytes', 'read_bytes':
            databytes = pool_information['stats'][datatype]
            databytes_formatted = format_bytes_tohuman(int(databytes))
            pool_information['stats'][datatype] = databytes_formatted
        for datatype in 'write_ops', 'read_ops':
            dataops = pool_information['stats'][datatype]
            dataops_formatted = format_ops_tohuman(int(dataops))
            pool_information['stats'][datatype] = dataops_formatted

        # Set the Pool name length
        _pool_name_length = len(pool_information['name']) + 1
        if _pool_name_length > pool_name_length:
            pool_name_length = _pool_name_length

        # Set the id and length
        _pool_id_length = len(str(pool_information['stats']['id'])) + 1
        if _pool_id_length > pool_id_length:
            pool_id_length = _pool_id_length

        # Set the size and length
        _pool_size_length = len(str(pool_information['stats']['size_bytes'])) + 1
        if _pool_size_length > pool_size_length:
            pool_size_length = _pool_size_length

        # Set the num_objects and length
        _pool_num_objects_length = len(str(pool_information['stats']['num_objects'])) + 1
        if _pool_num_objects_length > pool_num_objects_length:
            pool_num_objects_length = _pool_num_objects_length

        # Set the num_clones and length
        _pool_num_clones_length = len(str(pool_information['stats']['num_object_clones'])) + 1
        if _pool_num_clones_length > pool_num_clones_length:
            pool_num_clones_length = _pool_num_clones_length

        # Set the num_copies and length
        _pool_num_copies_length = len(str(pool_information['stats']['num_object_copies'])) + 1
        if _pool_num_copies_length > pool_num_copies_length:
            pool_num_copies_length = _pool_num_copies_length

        # Set the num_degraded and length
        _pool_num_degraded_length = len(str(pool_information['stats']['num_objects_degraded'])) + 1
        if _pool_num_degraded_length > pool_num_degraded_length:
            pool_num_degraded_length = _pool_num_degraded_length

        # Set the read/write IOPS/data and length
        _pool_write_ops_length = len(str(pool_information['stats']['write_ops'])) + 1
        if _pool_write_ops_length > pool_write_ops_length:
            pool_write_ops_length = _pool_write_ops_length

        _pool_write_data_length = len(pool_information['stats']['write_bytes']) + 1
        if _pool_write_data_length > pool_write_data_length:
            pool_write_data_length = _pool_write_data_length

        _pool_read_ops_length = len(str(pool_information['stats']['read_ops'])) + 1
        if _pool_read_ops_length > pool_read_ops_length:
            pool_read_ops_length = _pool_read_ops_length

        _pool_read_data_length = len(pool_information['stats']['read_bytes']) + 1
        if _pool_read_data_length > pool_read_data_length:
            pool_read_data_length = _pool_read_data_length

    # Format the output header
    pool_list_output.append('{bold}\
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
                bold='',
                end_bold='',
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
                pool_id=pool_information['stats']['id'],
                pool_name=pool_information['name'],
                pool_size=pool_information['stats']['size_bytes'],
                pool_objects=pool_information['stats']['num_objects'],
                pool_clones=pool_information['stats']['num_object_clones'],
                pool_copies=pool_information['stats']['num_object_copies'],
                pool_degraded=pool_information['stats']['num_objects_degraded'],
                pool_write_ops=pool_information['stats']['write_ops'],
                pool_write_data=pool_information['stats']['write_bytes'],
                pool_read_ops=pool_information['stats']['read_ops'],
                pool_read_data=pool_information['stats']['read_bytes']
            )
        )

    click.echo('\n'.join(sorted(pool_list_output)))


#
# Volume functions
#
def getCephVolumes(zk_conn, pool):
    volume_list = list()
    if not pool:
        pool_list = zkhandler.listchildren(zk_conn, '/ceph/pools')
    else:
        pool_list = [ pool ]

    for pool_name in pool_list:
        for volume_name in zkhandler.listchildren(zk_conn, '/ceph/volumes/{}'.format(pool_name)):
            volume_list.append('{}/{}'.format(pool_name, volume_name))

    return volume_list

def getVolumeInformation(zk_conn, pool, volume):
    # Parse the stats data
    volume_stats_raw = zkhandler.readdata(zk_conn, '/ceph/volumes/{}/{}/stats'.format(pool, volume))
    volume_stats = dict(json.loads(volume_stats_raw))
    # Format the size to something nicer
    volume_stats['size'] = format_bytes_tohuman(volume_stats['size'])

    volume_information = {
        'name': volume,
        'pool': pool,
        'stats': volume_stats
    }
    return volume_information

def add_volume(zk_conn, pool, name, size):
    # Tell the cluster to create a new volume
    databytes = format_bytes_fromhuman(size)
    add_volume_string = 'volume_add {},{},{}'.format(pool, name, databytes)
    zkhandler.writedata(zk_conn, {'/cmd/ceph': add_volume_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/cmd/ceph')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/cmd/ceph').split()[0]
            if result == 'success-volume_add':
                message = 'Created new RBD volume "{}" of size "{}" on pool "{}".'.format(name, size, pool)
                success = True
            else:
                message = 'ERROR: Failed to create new volume; check node logs for details.'
                success = False
        except:
            message = 'ERROR: Command ignored by node.'
            success = False

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/cmd/ceph')
    with lock:
        time.sleep(1)
        zkhandler.writedata(zk_conn, {'/cmd/ceph': ''})

    return success, message

def resize_volume(zk_conn, pool, name, size):
    # Tell the cluster to resize the volume
    databytes = format_bytes_fromhuman(size)
    resize_volume_string = 'volume_resize {},{},{}'.format(pool, name, databytes)
    zkhandler.writedata(zk_conn, {'/cmd/ceph': resize_volume_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/cmd/ceph')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/cmd/ceph').split()[0]
            if result == 'success-volume_resize':
                message = 'Resized RBD volume "{}" to size "{}" on pool "{}".'.format(name, size, pool)
                success = True
            else:
                message = 'ERROR: Failed to resize volume; check node logs for details.'
                success = False
        except:
            message = 'ERROR: Command ignored by node.'
            success = False

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/cmd/ceph')
    with lock:
        time.sleep(1)
        zkhandler.writedata(zk_conn, {'/cmd/ceph': ''})

    return success, message

def rename_volume(zk_conn, pool, name, new_name):
    # Tell the cluster to rename
    rename_volume_string = 'volume_rename {},{},{}'.format(pool, name, new_name)
    zkhandler.writedata(zk_conn, {'/cmd/ceph': rename_volume_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/cmd/ceph')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/cmd/ceph').split()[0]
            if result == 'success-volume_rename':
                message = 'Renamed RBD volume "{}" to "{}" on pool "{}".'.format(name, new_name, pool)
                success = True
            else:
                message = 'ERROR: Failed to rename volume {} to {}; check node logs for details.'.format(name, new_name)
                success = False
        except:
            message = 'ERROR: Command ignored by node.'
            success = False

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/cmd/ceph')
    with lock:
        time.sleep(1)
        zkhandler.writedata(zk_conn, {'/cmd/ceph': ''})

    return success, message

def remove_volume(zk_conn, pool, name):
    if not verifyVolume(zk_conn, pool, name):
        return False, 'ERROR: No volume with name "{}" is present in pool {}.'.format(name, pool)

    # Tell the cluster to create a new volume
    remove_volume_string = 'volume_remove {},{}'.format(pool, name)
    zkhandler.writedata(zk_conn, {'/cmd/ceph': remove_volume_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/cmd/ceph')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/cmd/ceph').split()[0]
            if result == 'success-volume_remove':
                message = 'Removed RBD volume "{}" in pool "{}".'.format(name, pool)
                success = True
            else:
                message = 'ERROR: Failed to remove volume; check node logs for details.'
                success = False
        except Exception as e:
            message = 'ERROR: Command ignored by node: {}'.format(e)
            success = False

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/cmd/ceph')
    with lock:
        time.sleep(1)
        zkhandler.writedata(zk_conn, {'/cmd/ceph': ''})

    return success, message

def get_list_volume(zk_conn, pool, limit, is_fuzzy=True):
    volume_list = []
    if pool and not verifyPool(zk_conn, name):
        return False, 'ERROR: No pool with name "{}" is present in the cluster.'.format(name)

    full_volume_list = getCephVolumes(zk_conn, pool)

    if is_fuzzy and limit:
        # Implicitly assume fuzzy limits
        if not re.match('\^.*', limit):
            limit = '.*' + limit
        if not re.match('.*\$', limit):
            limit = limit + '.*'

    for volume in full_volume_list:
        pool_name, volume_name = volume.split('/')
        if limit:
            try:
                if re.match(limit, volume):
                    volume_list.append(getVolumeInformation(zk_conn, pool_name, volume_name))
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            volume_list.append(getVolumeInformation(zk_conn, pool_name, volume_name))

    return True, volume_list

def format_list_volume(volume_list):
    volume_list_output = []

    volume_name_length = 5
    volume_pool_length = 5
    volume_size_length = 5
    volume_objects_length = 8
    volume_order_length = 6
    volume_format_length = 7
    volume_features_length = 10

    for volume_information in volume_list:
        # Set the Volume name length
        _volume_name_length = len(volume_information['name']) + 1
        if _volume_name_length > volume_name_length:
            volume_name_length = _volume_name_length

        # Set the Volume pool length
        _volume_pool_length = len(volume_information['pool']) + 1
        if _volume_pool_length > volume_pool_length:
            volume_pool_length = _volume_pool_length

        # Set the size and length
        _volume_size_length = len(str(volume_information['stats']['size'])) + 1
        if _volume_size_length > volume_size_length:
            volume_size_length = _volume_size_length

        # Set the num_objects and length
        _volume_objects_length = len(str(volume_information['stats']['objects'])) + 1
        if _volume_objects_length > volume_objects_length:
            volume_objects_length = _volume_objects_length

        # Set the order and length
        _volume_order_length = len(str(volume_information['stats']['order'])) + 1
        if _volume_order_length > volume_order_length:
            volume_order_length = _volume_order_length

        # Set the format and length
        _volume_format_length = len(str(volume_information['stats']['format'])) + 1
        if _volume_format_length > volume_format_length:
            volume_format_length = _volume_format_length

        # Set the features and length
        _volume_features_length = len(str(','.join(volume_information['stats']['features']))) + 1
        if _volume_features_length > volume_features_length:
            volume_features_length = _volume_features_length

    # Format the output header
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
            volume_name='Name',
            volume_pool='Pool',
            volume_size='Size',
            volume_objects='Objects',
            volume_order='Order',
            volume_format='Format',
            volume_features='Features',
        )
    )

    for volume_information in volume_list:
        volume_list_output.append('{bold}\
{volume_name: <{volume_name_length}} \
{volume_pool: <{volume_pool_length}} \
{volume_size: <{volume_size_length}} \
{volume_objects: <{volume_objects_length}} \
{volume_order: <{volume_order_length}} \
{volume_format: <{volume_format_length}} \
{volume_features: <{volume_features_length}} \
{end_bold}'.format(
                bold='',
                end_bold='',
                volume_name_length=volume_name_length,
                volume_pool_length=volume_pool_length,
                volume_size_length=volume_size_length,
                volume_objects_length=volume_objects_length,
                volume_order_length=volume_order_length,
                volume_format_length=volume_format_length,
                volume_features_length=volume_features_length,
                volume_name=volume_information['name'],
                volume_pool=volume_information['pool'],
                volume_size=volume_information['stats']['size'],
                volume_objects=volume_information['stats']['objects'],
                volume_order=volume_information['stats']['order'],
                volume_format=volume_information['stats']['format'],
                volume_features=','.join(volume_information['stats']['features']),
            )
        )

    click.echo('\n'.join(sorted(volume_list_output)))


#
# Snapshot functions
#

def getCephSnapshots(zk_conn, pool, volume):
    snapshot_list = list()
    volume_list = list()

    volume_list = getCephVolumes(zk_conn, pool)
    if volume:
        for volume_entry in volume_list:
            volume_pool, volume_name = volume_entry.split('/')
            if volume_name == volume:
                volume_list = [ '{}/{}'.format(volume_pool, volume_name) ]

    for volume_entry in volume_list:
        for snapshot_name in zkhandler.listchildren(zk_conn, '/ceph/snapshots/{}'.format(volume_entry)):
            snapshot_list.append('{}@{}'.format(volume_entry, snapshot_name))

    return snapshot_list

def add_snapshot(zk_conn, pool, volume, name):
    # Tell the cluster to create a new snapshot
    add_snapshot_string = 'snapshot_add {},{},{}'.format(pool, volume, name)
    zkhandler.writedata(zk_conn, {'/cmd/ceph': add_snapshot_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/cmd/ceph')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/cmd/ceph').split()[0]
            if result == 'success-snapshot_add':
                message = 'Created new RBD snapshot "{}" of volume "{}" on pool "{}".'.format(name, volume, pool)
                success = True
            else:
                message = 'ERROR: Failed to create new snapshot; check node logs for details.'
                success = False
        except:
            message = 'ERROR: Command ignored by node.'
            success = False

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/cmd/ceph')
    with lock:
        time.sleep(1)
        zkhandler.writedata(zk_conn, {'/cmd/ceph': ''})

    return success, message

def rename_snapshot(zk_conn, pool, volume, name, new_name):
    # Tell the cluster to rename
    rename_snapshot_string = 'snapshot_rename {},{},{}'.format(pool, name, new_name)
    zkhandler.writedata(zk_conn, {'/cmd/ceph': rename_snapshot_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/cmd/ceph')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/cmd/ceph').split()[0]
            if result == 'success-snapshot_rename':
                message = 'Renamed RBD volume snapshot "{}" to "{}" for volume {} on pool "{}".'.format(name, new_name, volume, pool)
                success = True
            else:
                message = 'ERROR: Failed to rename volume {} to {}; check node logs for details.'.format(name, new_name)
                success = False
        except:
            message = 'ERROR: Command ignored by node.'
            success = False

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/cmd/ceph')
    with lock:
        time.sleep(1)
        zkhandler.writedata(zk_conn, {'/cmd/ceph': ''})

    return success, message

def remove_snapshot(zk_conn, pool, volume, name):
    if not verifySnapshot(zk_conn, pool, volume, name):
        return False, 'ERROR: No snapshot with name "{}" is present of volume {} on pool {}.'.format(name, volume, pool)

    # Tell the cluster to create a new snapshot
    remove_snapshot_string = 'snapshot_remove {},{},{}'.format(pool, volume, name)
    zkhandler.writedata(zk_conn, {'/cmd/ceph': remove_snapshot_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/cmd/ceph')
    with lock:
        try:
            result = zkhandler.readdata(zk_conn, '/cmd/ceph').split()[0]
            if result == 'success-snapshot_remove':
                message = 'Removed RBD snapshot "{}" of volume "{}" in pool "{}".'.format(name, volume, pool)
                success = True
            else:
                message = 'ERROR: Failed to remove snapshot; check node logs for details.'
                success = False
        except Exception as e:
            message = 'ERROR: Command ignored by node: {}'.format(e)
            success = False

    # Acquire a write lock to ensure things go smoothly
    lock = zkhandler.writelock(zk_conn, '/cmd/ceph')
    with lock:
        time.sleep(1)
        zkhandler.writedata(zk_conn, {'/cmd/ceph': ''})

    return success, message

def get_list_snapshot(zk_conn, pool, volume, limit, is_fuzzy=True):
    snapshot_list = []
    if pool and not verifyPool(zk_conn, pool):
        return False, 'ERROR: No pool with name "{}" is present in the cluster.'.format(pool)

    if volume and not verifyPool(zk_conn, volume):
        return False, 'ERROR: No volume with name "{}" is present in the cluster.'.format(volume)

    full_snapshot_list = getCephSnapshots(zk_conn, pool, volume)

    if is_fuzzy and limit:
        # Implicitly assume fuzzy limits
        if not re.match('\^.*', limit):
            limit = '.*' + limit
        if not re.match('.*\$', limit):
            limit = limit + '.*'

    for snapshot in full_snapshot_list:
        volume, snapshot_name = snapshot.split('@')
        pool_name, volume_name = volume.split('/')
        if limit:
            try:
                if re.match(limit, snapshot):
                    snapshot_list.append(snapshot)
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            snapshot_list.append(snapshot)

    return True, snapshot_list

def format_list_snapshot(snapshot_list):
    snapshot_list_output = []

    snapshot_name_length = 5
    snapshot_volume_length = 7
    snapshot_pool_length = 5

    for snapshot in snapshot_list:
        volume, snapshot_name = snapshot.split('@')
        snapshot_pool, snapshot_volume = volume.split('/')

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
            snapshot_name='Name',
            snapshot_volume='Volume',
            snapshot_pool='Pool',
        )
    )

    for snapshot in snapshot_list:
        volume, snapshot_name = snapshot.split('@')
        snapshot_pool, snapshot_volume = volume.split('/')
        snapshot_list_output.append('{bold}\
{snapshot_name: <{snapshot_name_length}} \
{snapshot_volume: <{snapshot_volume_length}} \
{snapshot_pool: <{snapshot_pool_length}} \
{end_bold}'.format(
                bold='',
                end_bold='',
                snapshot_name_length=snapshot_name_length,
                snapshot_volume_length=snapshot_volume_length,
                snapshot_pool_length=snapshot_pool_length,
                snapshot_name=snapshot_name,
                snapshot_volume=snapshot_volume,
                snapshot_pool=snapshot_pool,
            )
        )

    click.echo('\n'.join(sorted(snapshot_list_output)))
