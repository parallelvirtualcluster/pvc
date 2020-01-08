#!/usr/bin/env python3

# cluster.py - PVC client function library, cluster management
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

import client_lib.ansiprint as ansiprint
import client_lib.zkhandler as zkhandler
import client_lib.common as common
import client_lib.vm as pvc_vm
import client_lib.node as pvc_node
import client_lib.network as pvc_network
import client_lib.ceph as pvc_ceph

def getClusterInformation(zk_conn):
    # Get node information object list
    retcode, node_list = pvc_node.get_list(zk_conn, None)

    # Get vm information object list
    retcode, vm_list = pvc_vm.get_list(zk_conn, None, None, None)

    # Get network information object list
    retcode, network_list = pvc_network.get_list(zk_conn, None, None)

    # Get storage information object list
    retcode, ceph_osd_list = pvc_ceph.get_list_osd(zk_conn, None)
    retcode, ceph_pool_list = pvc_ceph.get_list_pool(zk_conn, None)
    retcode, ceph_volume_list = pvc_ceph.get_list_volume(zk_conn, None, None)
    retcode, ceph_snapshot_list = pvc_ceph.get_list_snapshot(zk_conn, None, None, None)

    # Determine, for each subsection, the total count
    node_count = len(node_list)
    vm_count = len(vm_list)
    network_count = len(network_list)
    ceph_osd_count = len(ceph_osd_list)
    ceph_pool_count = len(ceph_pool_list)
    ceph_volume_count = len(ceph_volume_list)
    ceph_snapshot_count = len(ceph_snapshot_list)

    # Determinations for node health
    node_healthy_status = list(range(0, node_count))
    node_report_status = list(range(0, node_count))
    for index, node in enumerate(node_list):
        daemon_state = node['daemon_state']
        domain_state = node['domain_state']
        if daemon_state != 'run' and domain_state != 'ready':
            node_healthy_status[index] = False
        else:
            node_healthy_status[index] = True
        node_report_status[index] = daemon_state + ',' +  domain_state

    # Determinations for VM health
    vm_healthy_status = list(range(0, vm_count))
    vm_report_status = list(range(0, vm_count))
    for index, vm in enumerate(vm_list):
        vm_state = vm['state']
        if vm_state not in ['start', 'disable', 'migrate', 'unmigrate', 'provision']:
            vm_healthy_status[index] = False
        else:
            vm_healthy_status[index] = True
        vm_report_status[index] = vm_state

    # Determinations for OSD health
    ceph_osd_healthy_status = list(range(0, ceph_osd_count))
    ceph_osd_report_status = list(range(0, ceph_osd_count))
    for index, ceph_osd in enumerate(ceph_osd_list):
        try:
            ceph_osd_up = ceph_osd['stats']['up']
        except KeyError:
            ceph_osd_up = 0

        try:
            ceph_osd_in = ceph_osd['stats']['in']
        except KeyError:
            ceph_osd_in = 0

        if not ceph_osd_up or not ceph_osd_in:
            ceph_osd_healthy_status[index] = False
        else:
            ceph_osd_healthy_status[index] = True
        up_texts = { 1: 'up', 0: 'down' }
        in_texts = { 1: 'in', 0: 'out' }
        ceph_osd_report_status[index] = up_texts[ceph_osd_up] + ',' + in_texts[ceph_osd_in]

    # Find out the overall cluster health; if any element of a healthy_status is false, it's unhealthy
    if False in node_healthy_status or False in vm_healthy_status or False in ceph_osd_healthy_status:
        cluster_health = 'Degraded'
    else:
        cluster_health = 'Optimal'

    # State lists
    node_state_combinations = [
        'run,ready', 'run,flush', 'run,flushed', 'run,unflush',
        'init,ready', 'init,flush', 'init,flushed', 'init,unflush',
        'stop,ready', 'stop,flush', 'stop,flushed', 'stop,unflush'
    ]
    vm_state_combinations = [
        'start', 'restart', 'shutdown', 'stop', 'disable', 'fail', 'migrate', 'unmigrate', 'provision'
    ]
    ceph_osd_state_combinations = [
        'up,in', 'up,out', 'down,in', 'down,out'
    ]

    # Format the Node states
    formatted_node_states = {'total': node_count}
    for state in node_state_combinations:
        state_count = 0
        for node_state in node_report_status:
            if node_state == state:
                state_count += 1
        if state_count > 0:
            formatted_node_states[state] = state_count

    # Format the VM states
    formatted_vm_states = {'total': vm_count}
    for state in vm_state_combinations:
        state_count = 0
        for vm_state in vm_report_status:
            if vm_state == state:
                state_count += 1
        if state_count > 0:
            formatted_vm_states[state] = state_count

    # Format the OSD states
    formatted_osd_states = {'total': ceph_osd_count}
    for state in ceph_osd_state_combinations:
        state_count = 0
        for ceph_osd_state in ceph_osd_report_status:
            if ceph_osd_state == state:
                state_count += 1
        if state_count > 0:
            formatted_osd_states[state] = state_count

    # Format the status data
    cluster_information = {
        'health': cluster_health,
        'primary_node': common.getPrimaryNode(zk_conn),
        'upstream_ip': zkhandler.readdata(zk_conn, '/upstream_ip'),
        'nodes': formatted_node_states,
        'vms': formatted_vm_states,
        'networks': network_count,
        'osds': formatted_osd_states,
        'pools': ceph_pool_count,
        'volumes': ceph_volume_count,
        'snapshots': ceph_snapshot_count
    }

    return cluster_information

def get_info(zk_conn):
    # This is a thin wrapper function for naming purposes
    cluster_information = getClusterInformation(zk_conn)
    if cluster_information:
        return True, cluster_information
    else:
        return False, 'ERROR: Failed to obtain cluster information!'

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
        
