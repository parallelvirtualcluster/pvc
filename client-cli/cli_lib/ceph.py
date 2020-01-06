#!/usr/bin/env python3

# ceph.py - PVC CLI client function library, Ceph cluster functions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2019 Joshua M. Boniface <joshua@boniface.me>
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
import json
import time
import math
import requests

import cli_lib.ansiprint as ansiprint

def debug_output(config, request_uri, response):
    if config['debug']:
        from click import echo
        click.echo('API endpoint: {}'.format(request_uri), err=True)
        click.echo('Response code: {}'.format(response.status_code), err=True)
        click.echo('Response headers: {}'.format(response.headers), err=True)

#
# Supplemental functions
#

def get_request_uri(config, endpoint):
    """
    Return the fully-formed URI for {endpoint}
    """
    uri = '{}://{}{}{}'.format(
        config['api_scheme'],
        config['api_host'],
        config['api_prefix'],
        endpoint
    )
    return uri

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

def format_pct_tohuman(datapct):
    datahuman = "{0:.1f}".format(float(datapct * 100.0))
    return datahuman

#
# Status functions
#
def ceph_status(config):
    """
    Get status of the Ceph cluster

    API endpoint: GET /api/v1/storage/ceph/status
    API arguments:
    API schema: {json_data_object}
    """
    request_uri = get_request_uri(config, '/storage/ceph/status')
    response = requests.get(
        request_uri
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']
	
def ceph_util(config):
    """
    Get utilization of the Ceph cluster

    API endpoint: GET /api/v1/storage/ceph/utilization
    API arguments:
    API schema: {json_data_object}
    """
    request_uri = get_request_uri(config, '/storage/ceph/utilization')
    response = requests.get(
        request_uri
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']
	
def format_raw_output(status_data):
    ainformation = list()
    ainformation.append('{bold}Ceph cluster {stype} (primary node {end}{blue}{primary}{end}{bold}){end}\n'.format(bold=ansiprint.bold(), end=ansiprint.end(), blue=ansiprint.blue(), stype=status_data['type'], primary=status_data['primary_node']))
    ainformation.append(status_data['ceph_data'])
    ainformation.append('')

    return '\n'.join(ainformation)

#
# OSD functions
#
def ceph_osd_info(config, osd):
    """
    Get information about Ceph OSD

    API endpoint: GET /api/v1/storage/ceph/osd/{osd}
    API arguments:
    API schema: {json_data_object}
    """
    request_uri = get_request_uri(config, '/storage/ceph/osd/{osd}'.format(osd=osd))
    response = requests.get(
        request_uri
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']

def ceph_osd_list(config, limit):
    """
    Get list information about Ceph OSDs (limited by {limit})

    API endpoint: GET /api/v1/storage/ceph/osd
    API arguments: limit={limit}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    if limit:
        params['limit'] = limit

    request_uri = get_request_uri(config, '/storage/ceph/osd')
    response = requests.get(
        request_uri,
        params=params
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']

def ceph_osd_add(config, node, device, weight):
    """
    Add new Ceph OSD

    API endpoint: POST /api/v1/storage/ceph/osd
    API arguments: node={node}, device={device}, weight={weight}
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/storage/ceph/osd')
    response = requests.post(
        request_uri,
        params={
            'node': node,
            'device': device,
            'weight': weight
        }
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def ceph_osd_remove(config, osdid):
    """
    Remove Ceph OSD

    API endpoint: POST /api/v1/storage/ceph/osd/{osdid}
    API arguments:
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/storage/ceph/osd/{osdid}'.format(osdid=osdid))
    response = requests.post(
        request_uri,
        params={
            'yes-i-really-mean-it': 'yes'
        }
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def ceph_osd_state(config, osdid, state):
    """
    Set state of Ceph OSD

    API endpoint: POST /api/v1/storage/ceph/osd/{osdid}/state
    API arguments: state={state}
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/storage/ceph/osd/{osdid}/state'.format(osdid=osdid))
    response = requests.post(
        request_uri,
        params={
            'state': state
        }
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def ceph_osd_option(config, option, action):
    """
    Set cluster option of Ceph OSDs

    API endpoint: POST /api/v1/storage/ceph/option
    API arguments: option={option}, action={action}
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/storage/ceph/option')
    response = requests.post(
        request_uri,
        params={
            'option': option,
            'action': action
        }
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

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

def format_list_osd(osd_list):
    # Handle empty list
    if not osd_list:
        osd_list = list()
    # Handle single-item list
    if not isinstance(osd_list, list):
        osd_list = [ osd_list ]

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

    return '\n'.join(sorted(osd_list_output))


#
# Pool functions
#
def ceph_pool_info(config, pool):
    """
    Get information about Ceph OSD

    API endpoint: GET /api/v1/storage/ceph/pool/{pool}
    API arguments:
    API schema: {json_data_object}
    """
    request_uri = get_request_uri(config, '/storage/ceph/pool/{pool}'.format(pool=pool))
    response = requests.get(
        request_uri
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']

def ceph_pool_list(config, limit):
    """
    Get list information about Ceph OSDs (limited by {limit})

    API endpoint: GET /api/v1/storage/ceph/pool
    API arguments: limit={limit}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    if limit:
        params['limit'] = limit

    request_uri = get_request_uri(config, '/storage/ceph/pool')
    response = requests.get(
        request_uri,
        params=params
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']

def ceph_pool_add(config, pool, pgs, replcfg):
    """
    Add new Ceph OSD

    API endpoint: POST /api/v1/storage/ceph/pool
    API arguments: pool={pool}, pgs={pgs}, replcfg={replcfg}
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/storage/ceph/pool')
    response = requests.post(
        request_uri,
        params={
            'pool': pool,
            'pgs': pgs,
            'replcfg': replcfg
        }
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def ceph_pool_remove(config, pool):
    """
    Remove Ceph OSD

    API endpoint: DELETE /api/v1/storage/ceph/pool/{pool}
    API arguments:
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/storage/ceph/pool/{pool}'.format(pool=pool))
    response = requests.delete(
        request_uri,
        params={
            'yes-i-really-mean-it': 'yes'
        }
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def format_list_pool(pool_list):
    # Handle empty list
    if not pool_list:
        pool_list = list()
    # Handle single-entry list
    if not isinstance(pool_list, list):
        pool_list = [ pool_list ]

    pool_list_output = []

    pool_name_length = 5
    pool_id_length = 3
    pool_used_length = 5
    pool_usedpct_length = 5
    pool_free_length = 5
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
        for datatype in ['free_bytes', 'used_bytes', 'write_bytes', 'read_bytes']:
            databytes = pool_information['stats'][datatype]
            databytes_formatted = format_bytes_tohuman(int(databytes))
            pool_information['stats'][datatype] = databytes_formatted
        for datatype in ['write_ops', 'read_ops']:
            dataops = pool_information['stats'][datatype]
            dataops_formatted = format_ops_tohuman(int(dataops))
            pool_information['stats'][datatype] = dataops_formatted
        for datatype in ['used_percent']:
            datapct = pool_information['stats'][datatype]
            datapct_formatted = format_pct_tohuman(float(datapct))
            pool_information['stats'][datatype] = datapct_formatted

        # Set the Pool name length
        _pool_name_length = len(pool_information['name']) + 1
        if _pool_name_length > pool_name_length:
            pool_name_length = _pool_name_length

        # Set the id and length
        _pool_id_length = len(str(pool_information['stats']['id'])) + 1
        if _pool_id_length > pool_id_length:
            pool_id_length = _pool_id_length

        # Set the used and length
        _pool_used_length = len(str(pool_information['stats']['used_bytes'])) + 1
        if _pool_used_length > pool_used_length:
            pool_used_length = _pool_used_length

        # Set the usedpct and length
        _pool_usedpct_length = len(str(pool_information['stats']['used_percent'])) + 1
        if _pool_usedpct_length > pool_usedpct_length:
            pool_usedpct_length = _pool_usedpct_length

        # Set the free and length
        _pool_free_length = len(str(pool_information['stats']['free_bytes'])) + 1
        if _pool_free_length > pool_free_length:
            pool_free_length = _pool_free_length

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
{pool_used: <{pool_used_length}} \
{pool_usedpct: <{pool_usedpct_length}} \
{pool_free: <{pool_free_length}} \
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
            pool_used_length=pool_used_length,
            pool_usedpct_length=pool_usedpct_length,
            pool_free_length=pool_free_length,
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
            pool_used='Used',
            pool_usedpct='%',
            pool_free='Free',
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

    for pool_information in pool_list:
        # Format the output header
        pool_list_output.append('{bold}\
{pool_id: <{pool_id_length}} \
{pool_name: <{pool_name_length}} \
{pool_used: <{pool_used_length}} \
{pool_usedpct: <{pool_usedpct_length}} \
{pool_free: <{pool_free_length}} \
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
                pool_used_length=pool_used_length,
                pool_usedpct_length=pool_usedpct_length,
                pool_free_length=pool_free_length,
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
                pool_used=pool_information['stats']['used_bytes'],
                pool_usedpct=pool_information['stats']['used_percent'],
                pool_free=pool_information['stats']['free_bytes'],
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

    return '\n'.join(sorted(pool_list_output))

#
# Volume functions
#
def ceph_volume_info(config, pool, volume):
    """
    Get information about Ceph volume

    API endpoint: GET /api/v1/storage/ceph/volume/{pool}/{volume}
    API arguments:
    API schema: {json_data_object}
    """
    request_uri = get_request_uri(config, '/storage/ceph/volume/{pool}/{volume}'.format(volume=volume, pool=pool))
    response = requests.get(
        request_uri
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']

def ceph_volume_list(config, limit, pool):
    """
    Get list information about Ceph volumes (limited by {limit} and by {pool})

    API endpoint: GET /api/v1/storage/ceph/volume
    API arguments: limit={limit}, pool={pool}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    if limit:
        params['limit'] = limit
    if pool:
        params['pool'] = pool

    request_uri = get_request_uri(config, '/storage/ceph/volume')
    response = requests.get(
        request_uri,
        params=params
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']

def ceph_volume_add(config, pool, volume, size):
    """
    Add new Ceph volume

    API endpoint: POST /api/v1/storage/ceph/volume
    API arguments: volume={volume}, pool={pool}, size={size}
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/storage/ceph/volume')
    response = requests.post(
        request_uri,
        params={
            'volume': volume,
            'pool': pool,
            'size': size
        }
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def ceph_volume_remove(config, pool, volume):
    """
    Remove Ceph volume

    API endpoint: DELETE /api/v1/storage/ceph/volume/{pool}/{volume}
    API arguments:
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/storage/ceph/volume/{pool}/{volume}'.format(volume=volume, pool=pool))
    response = requests.delete(
        request_uri
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def ceph_volume_modify(config, pool, volume, new_name=None, new_size=None):
    """
    Modify Ceph volume

    API endpoint: PUT /api/v1/storage/ceph/volume/{pool}/{volume}
    API arguments:
    API schema: {"message":"{data}"}
    """

    params = dict()
    if new_name:
        params['new_name'] = new_name
    if new_size:
        params['new_size'] = new_size

    request_uri = get_request_uri(config, '/storage/ceph/volume/{pool}/{volume}'.format(volume=volume, pool=pool))
    response = requests.put(
        request_uri,
        params=params
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def ceph_volume_clone(config, pool, volume, new_volume):
    """
    Clone Ceph volume

    API endpoint: POST /api/v1/storage/ceph/volume/{pool}/{volume}
    API arguments: new_volume={new_volume
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/storage/ceph/volume/{pool}/{volume}/clone'.format(volume=volume, pool=pool))
    response = requests.post(
        request_uri,
        params={
            'new_volume': new_volume
        }
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def format_list_volume(volume_list):
    # Handle empty list
    if not volume_list:
        volume_list = list()
    # Handle single-entry list
    if not isinstance(volume_list, list):
        volume_list = [ volume_list ]

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

    return '\n'.join(sorted(volume_list_output))


#
# Snapshot functions
#
def ceph_snapshot_info(config, pool, volume, snapshot):
    """
    Get information about Ceph snapshot

    API endpoint: GET /api/v1/storage/ceph/snapshot/{pool}/{volume}/{snapshot}
    API arguments:
    API schema: {json_data_object}
    """
    request_uri = get_request_uri(config, '/storage/ceph/snapshot/{pool}/{volume}/{snapshot}'.format(snapshot=snapshot, volume=volume, pool=pool))
    response = requests.get(
        request_uri
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']

def ceph_snapshot_list(config, limit, volume, pool):
    """
    Get list information about Ceph snapshots (limited by {limit}, by {pool}, or by {volume})

    API endpoint: GET /api/v1/storage/ceph/snapshot
    API arguments: limit={limit}, volume={volume}, pool={pool}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    if limit:
        params['limit'] = limit
    if volume:
        params['volume'] = volume
    if pool:
        params['pool'] = pool

    request_uri = get_request_uri(config, '/storage/ceph/snapshot')
    response = requests.get(
        request_uri,
        params=params
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']

def ceph_snapshot_add(config, pool, volume, snapshot):
    """
    Add new Ceph snapshot

    API endpoint: POST /api/v1/storage/ceph/snapshot
    API arguments: snapshot={snapshot}, volume={volume}, pool={pool}
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/storage/ceph/snapshot')
    response = requests.post(
        request_uri,
        params={
            'snapshot': snapshot,
            'volume': volume,
            'pool': pool
        }
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def ceph_snapshot_remove(config, pool, volume, snapshot):
    """
    Remove Ceph snapshot

    API endpoint: DELETE /api/v1/storage/ceph/snapshot/{pool}/{volume}/{snapshot}
    API arguments:
    API schema: {"message":"{data}"}
    """
    request_uri = get_request_uri(config, '/storage/ceph/snapshot/{pool}/{volume}/{snapshot}'.format(snapshot=snapshot, volume=volume, pool=pool))
    response = requests.delete(
        request_uri
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def ceph_snapshot_modify(config, pool, volume, snapshot, new_name=None):
    """
    Modify Ceph snapshot

    API endpoint: PUT /api/v1/storage/ceph/snapshot/{pool}/{volume}/{snapshot}
    API arguments:
    API schema: {"message":"{data}"}
    """

    params = dict()
    if new_name:
        params['new_name'] = new_name

    request_uri = get_request_uri(config, '/storage/ceph/snapshot/{pool}/{volume}/{snapshot}'.format(snapshot=snapshot, volume=volume, pool=pool))
    response = requests.put(
        request_uri,
        params=params
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def format_list_snapshot(snapshot_list):
    # Handle empty list
    if not snapshot_list:
        snapshot_list = list()
    # Handle single-entry list
    if not isinstance(snapshot_list, list):
        snapshot_list = [ snapshot_list ]

    snapshot_list_output = []

    snapshot_name_length = 5
    snapshot_volume_length = 7
    snapshot_pool_length = 5

    for snapshot in snapshot_list:
        snapshot_name = snapshot['snapshot']
        snapshot_volume = snapshot['volume']
        snapshot_pool = snapshot['pool']

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
        snapshot_name = snapshot['snapshot']
        snapshot_volume = snapshot['volume']
        snapshot_pool = snapshot['pool']
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

    return '\n'.join(sorted(snapshot_list_output))
