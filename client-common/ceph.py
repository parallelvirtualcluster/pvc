#!/usr/bin/env python3

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
import ast
import time

import client_lib.ansiprint as ansiprint
import client_lib.zkhandler as zkhandler
import client_lib.common as common

#
# Supplemental functions
#

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
    osd_stats = dict(ast.literal_eval(osd_stats_raw))
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
    osd_weight = dict()
    osd_node = dict()
    osd_used = dict()
    osd_free = dict()
    osd_wrops = dict()
    osd_wrdata = dict()
    osd_rdops = dict()
    osd_rddata = dict()
    osd_state = dict()
    osd_state_colour = dict()

    osd_id_length = 3
    osd_up_length = 4
    osd_in_length = 4
    osd_weight_length = 7
    osd_node_length = 5
    osd_used_length = 5
    osd_free_length = 6
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

        # Set the weight and length
        osd_weight[osd] = osd_stats['weight']
        _osd_weight_length = len(str(osd_weight[osd])) + 1
        if _osd_weight_length > osd_weight_length:
            osd_weight_length = _osd_weight_length

        # Set the used/available space and length
        osd_used[osd] = osd_stats['used']
        _osd_used_length = len(osd_used[osd]) + 1
        if _osd_used_length > osd_used_length:
            osd_used_length = _osd_used_length
        osd_free[osd] = osd_stats['avail']
        _osd_free_length = len(osd_free[osd]) + 1
        if _osd_free_length > osd_free_length:
            osd_free_length = _osd_free_length

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
{osd_weight: <{osd_weight_length}} \
Space: {osd_used: <{osd_used_length}} \
{osd_free: <{osd_free_length}} \
Write: {osd_wrops: <{osd_wrops_length}} \
{osd_wrdata: <{osd_wrdata_length}} \
Read: {osd_rdops: <{osd_rdops_length}} \
{osd_rddata: <{osd_rddata_length}} \
{end_bold}'.format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            osd_id_length=osd_id_length,
            osd_node_length=osd_node_length,
            osd_up_length=osd_up_length,
            osd_in_length=osd_in_length,
            osd_weight_length=osd_weight_length,
            osd_used_length=osd_used_length,
            osd_free_length=osd_free_length,
            osd_wrops_length=osd_wrops_length,
            osd_wrdata_length=osd_wrdata_length,
            osd_rdops_length=osd_rdops_length,
            osd_rddata_length=osd_rddata_length,
            osd_id='ID',
            osd_node='Node',
            osd_up='Up',
            osd_in='In',
            osd_weight='Weight',
            osd_used='Used',
            osd_free='Free',
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
{osd_weight: <{osd_weight_length}} \
       {osd_used: <{osd_used_length}} \
{osd_free: <{osd_free_length}} \
       {osd_wrops: <{osd_wrops_length}} \
{osd_wrdata: <{osd_wrdata_length}} \
      {osd_rdops: <{osd_rdops_length}} \
{osd_rddata: <{osd_rddata_length}} \
{end_bold}'.format(
                bold=ansiprint.bold(),
                end_bold=ansiprint.end(),
                end_colour=ansiprint.end(),
                osd_id_length=osd_id_length,
                osd_node_length=osd_node_length,
                osd_up_length=osd_up_length,
                osd_in_length=osd_in_length,
                osd_weight_length=osd_weight_length,
                osd_used_length=osd_used_length,
                osd_free_length=osd_free_length,
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
                osd_weight=osd_weight[osd],
                osd_used=osd_used[osd],
                osd_free=osd_free[osd],
                osd_wrops=osd_wrops[osd],
                osd_wrdata=osd_wrdata[osd],
                osd_rdops=osd_rdops[osd],
                osd_rddata=osd_rddata[osd]
            )
        )
   
    output_string = osd_list_output_header + '\n' + '\n'.join(sorted(osd_list_output))
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

def add_osd(zk_conn, node, device):
    # Verify the target node exists
    if not common.verifyNode(zk_conn, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    # Tell the cluster to create a new OSD for the host
    add_osd_string = 'add {},{}'.format(node, device) 
    zkhandler.writedata(zk_conn, {'/ceph/osd_cmd': add_osd_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/ceph/osd_cmd')
    with lock:
        result = zkhandler.readdata(zk_conn, '/ceph/osd_cmd').split()[0]
        if result == 'success-add':
            success = True
        else:
            success = False
            
    if success:
        return True, 'Created new OSD with block device {} on node {}.'.format(device, node)
    else:
        return False, 'Failed to create new OSD; check node logs for details.'

def remove_osd(zk_conn, osd_id):
    if not common.verifyOSD(zk_conn, osd_id):
        return False, 'ERROR: No OSD with ID "{}" is present in the cluster.'.format(osd_id)

    # Tell the cluster to remove an OSD
    remove_osd_string = 'remove {}'.format(osd_id)
    zkhandler.writedata(zk_conn, {'/ceph/osd_cmd': remove_osd_string})
    # Wait 1/2 second for the cluster to get the message and start working
    time.sleep(0.5)
    # Acquire a read lock, so we get the return exclusively
    lock = zkhandler.readlock(zk_conn, '/ceph/osd_cmd')
    with lock:
        result = zkhandler.readdata(zk_conn, '/ceph/osd_cmd').split()[0]
        if result == 'success-remove':
            success = True
        else:
            success = False

    if success:
        return True, 'Removed OSD {} from the cluster.'.format(osd_id)
    else:
        return False, 'Failed to remove OSD; check node logs for details.'

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
