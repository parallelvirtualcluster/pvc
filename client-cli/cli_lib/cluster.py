#!/usr/bin/env python3

# cluster.py - PVC CLI client function library, cluster management
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

import json
import requests

import cli_lib.ansiprint as ansiprint

def debug_output(config, request_uri, response):
    if config['debug']:
        import click.echo
        click.echo('API endpoint: POST {}'.format(request_uri), err=True)
        click.echo('Response code: {}'.format(response.status_code), err=True)
        click.echo('Response headers: {}'.format(response.headers), err=True)

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

def initialize(config):
    """
    Initialize the PVC cluster

    API endpoint: GET /api/v1/initialize
    API arguments:
    API schema: {json_data_object}
    """
    request_uri = get_request_uri(config, '/initialize')
    response = requests.get(
        request_uri
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retstatus = True
    else:
        retstatus = False

    return retstatus, response.json()['message']

def get_info(config):
    """
    Get status of the PVC cluster

    API endpoint: GET /api/v1/status
    API arguments:
    API schema: {json_data_object}
    """
    request_uri = get_request_uri(config, '/status')
    response = requests.get(
        request_uri
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']

def format_info(cluster_information, oformat):
    if oformat == 'json':
        return json.dumps(cluster_information))

    if oformat == 'json-pretty':
        return json.dumps(cluster_information, indent=4))

    # Plain formatting, i.e. human-readable
    if cluster_information['health'] == 'Optimal':
        health_colour = ansiprint.green()
    else:
        health_colour = ansiprint.yellow()

    ainformation = []
    ainformation.append('{}PVC cluster status:{}'.format(ansiprint.bold(), ansiprint.end()))
    ainformation.append('')
    ainformation.append('{}Cluster health:{}      {}{}{}'.format(ansiprint.purple(), ansiprint.end(), health_colour, cluster_information['health'], ansiprint.end()))
    ainformation.append('{}Primary node:{}        {}'.format(ansiprint.purple(), ansiprint.end(), cluster_information['primary_node']))
    ainformation.append('{}Cluster upstream IP:{} {}'.format(ansiprint.purple(), ansiprint.end(), cluster_information['upstream_ip']))
    ainformation.append('')
    ainformation.append('{}Total nodes:{}     {}'.format(ansiprint.purple(), ansiprint.end(), cluster_information['nodes']['total']))
    ainformation.append('{}Total VMs:{}       {}'.format(ansiprint.purple(), ansiprint.end(), cluster_information['vms']['total']))
    ainformation.append('{}Total networks:{}  {}'.format(ansiprint.purple(), ansiprint.end(), cluster_information['networks']))
    ainformation.append('{}Total OSDs:{}      {}'.format(ansiprint.purple(), ansiprint.end(), cluster_information['osds']['total']))
    ainformation.append('{}Total pools:{}     {}'.format(ansiprint.purple(), ansiprint.end(), cluster_information['pools']))
    ainformation.append('{}Total volumes:{}   {}'.format(ansiprint.purple(), ansiprint.end(), cluster_information['volumes']))
    ainformation.append('{}Total snapshots:{} {}'.format(ansiprint.purple(), ansiprint.end(), cluster_information['snapshots']))

    nodes_string = ''
    if cluster_information['nodes'].get('run,ready', None):
        nodes_string += '{}Nodes:{} {}/{} {}ready,run{}'.format(ansiprint.purple(), ansiprint.end(), cluster_information['nodes']['run,ready'], cluster_information['nodes']['total'], ansiprint.green(), ansiprint.end())
    for state, count in cluster_information['nodes'].items():
        if state == 'total' or state == 'run,ready':
            continue

        nodes_string += ' {}/{} {}{}{}'.format(count, cluster_information['nodes']['total'], ansiprint.yellow(), state, ansiprint.end())

    ainformation.append('')
    ainformation.append(nodes_string)

    vms_string = ''
    if cluster_information['vms'].get('start', None):
        vms_string += '{}VMs:{} {}/{} {}start{}'.format(ansiprint.purple(), ansiprint.end(), cluster_information['vms']['start'], cluster_information['vms']['total'], ansiprint.green(), ansiprint.end())
    for state, count in cluster_information['vms'].items():
        if state == 'total' or state == 'start':
            continue

        if state == 'disable':
            colour = ansiprint.blue()
        else:
            colour = ansiprint.yellow()

        vms_string += ' {}/{} {}{}{}'.format(count, cluster_information['vms']['total'], colour, state, ansiprint.end())

    ainformation.append('')
    ainformation.append(vms_string)

    if cluster_information['osds']['total'] > 0:
        osds_string = '{}Ceph OSDs:{} {}/{} {}up,in{}'.format(ansiprint.purple(), ansiprint.end(), cluster_information['osds']['up,in'], cluster_information['osds']['total'], ansiprint.green(), ansiprint.end())
        for state, count in cluster_information['osds'].items():
            if state == 'total' or state == 'up,in':
                continue

            osds_string += ' {}/{} {}{}{}'.format(count, cluster_information['osds']['total'], ansiprint.yellow(), state, ansiprint.end())

        ainformation.append('')
        ainformation.append(osds_string)

    ainformation.append('')
    return '\n'.join(ainformation)
