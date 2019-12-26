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

import click
import json

import cli_lib.ansiprint as ansiprint

def format_info(cluster_information, oformat):
    if oformat == 'json':
        print(json.dumps(cluster_information))
        return

    if oformat == 'json-pretty':
        print(json.dumps(cluster_information, indent=4))
        return

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

    nodes_string = '{}Nodes:{} {}/{} {}ready,run{}'.format(ansiprint.purple(), ansiprint.end(), cluster_information['nodes']['run,ready'], cluster_information['nodes']['total'], ansiprint.green(), ansiprint.end())
    for state, count in cluster_information['nodes'].items():
        if state == 'total' or state == 'run,ready':
            continue

        nodes_string += ' {}/{} {}{}{}'.format(count, cluster_information['nodes']['total'], ansiprint.yellow(), state, ansiprint.end())

    ainformation.append('')
    ainformation.append(nodes_string)

    vms_string = '{}VMs:{} {}/{} {}start{}'.format(ansiprint.purple(), ansiprint.end(), cluster_information['vms']['start'], cluster_information['vms']['total'], ansiprint.green(), ansiprint.end())
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

    information = '\n'.join(ainformation)
    click.echo(information)

    click.echo('')
        