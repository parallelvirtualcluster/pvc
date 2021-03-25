#!/usr/bin/env python3

# cluster.py - PVC client function library, cluster management
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2020 Joshua M. Boniface <joshua@boniface.me>
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

import re

import daemon_lib.zkhandler as zkhandler
import daemon_lib.common as common
import daemon_lib.vm as pvc_vm
import daemon_lib.node as pvc_node
import daemon_lib.network as pvc_network
import daemon_lib.ceph as pvc_ceph


def set_maintenance(zk_conn, maint_state):
    try:
        if maint_state == 'true':
            zkhandler.writedata(zk_conn, {'/maintenance': 'true'})
            return True, 'Successfully set cluster in maintenance mode'
        else:
            zkhandler.writedata(zk_conn, {'/maintenance': 'false'})
            return True, 'Successfully set cluster in normal mode'
    except Exception:
        return False, 'Failed to set cluster maintenance state'


def getClusterInformation(zk_conn):
    # Get cluster maintenance state
    try:
        maint_state = zkhandler.readdata(zk_conn, '/maintenance')
    except Exception:
        maint_state = 'false'

    # List of messages to display to the clients
    cluster_health_msg = []
    storage_health_msg = []

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

    # Determinations for general cluster health
    cluster_healthy_status = True
    # Check for (n-1) overprovisioning
    #   Assume X nodes. If the total VM memory allocation (counting only running VMss) is greater than
    #   the total memory of the (n-1) smallest nodes, trigger this warning.
    n_minus_1_total = 0
    alloc_total = 0

    node_largest_index = None
    node_largest_count = 0
    for index, node in enumerate(node_list):
        node_mem_total = node['memory']['total']
        node_mem_alloc = node['memory']['allocated']
        alloc_total += node_mem_alloc

        # Determine if this node is the largest seen so far
        if node_mem_total > node_largest_count:
            node_largest_index = index
            node_largest_count = node_mem_total
    n_minus_1_node_list = list()
    for index, node in enumerate(node_list):
        if index == node_largest_index:
            continue
        n_minus_1_node_list.append(node)
    for index, node in enumerate(n_minus_1_node_list):
        n_minus_1_total += node['memory']['total']
    if alloc_total > n_minus_1_total:
        cluster_healthy_status = False
        cluster_health_msg.append("Total VM memory ({}) is overprovisioned (max {}) for (n-1) failure scenarios".format(alloc_total, n_minus_1_total))

    # Determinations for node health
    node_healthy_status = list(range(0, node_count))
    node_report_status = list(range(0, node_count))
    for index, node in enumerate(node_list):
        daemon_state = node['daemon_state']
        domain_state = node['domain_state']
        if daemon_state != 'run' and domain_state != 'ready':
            node_healthy_status[index] = False
            cluster_health_msg.append("Node '{}' in {},{} state".format(node['name'], daemon_state, domain_state))
        else:
            node_healthy_status[index] = True
        node_report_status[index] = daemon_state + ',' + domain_state

    # Determinations for VM health
    vm_healthy_status = list(range(0, vm_count))
    vm_report_status = list(range(0, vm_count))
    for index, vm in enumerate(vm_list):
        vm_state = vm['state']
        if vm_state not in ['start', 'disable', 'migrate', 'unmigrate', 'provision']:
            vm_healthy_status[index] = False
            cluster_health_msg.append("VM '{}' in {} state".format(vm['name'], vm_state))
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

        up_texts = {1: 'up', 0: 'down'}
        in_texts = {1: 'in', 0: 'out'}

        if not ceph_osd_up or not ceph_osd_in:
            ceph_osd_healthy_status[index] = False
            cluster_health_msg.append('OSD {} in {},{} state'.format(ceph_osd['id'], up_texts[ceph_osd_up], in_texts[ceph_osd_in]))
        else:
            ceph_osd_healthy_status[index] = True
        ceph_osd_report_status[index] = up_texts[ceph_osd_up] + ',' + in_texts[ceph_osd_in]

    # Find out the overall cluster health; if any element of a healthy_status is false, it's unhealthy
    if maint_state == 'true':
        cluster_health = 'Maintenance'
    elif cluster_healthy_status is False or False in node_healthy_status or False in vm_healthy_status or False in ceph_osd_healthy_status:
        cluster_health = 'Degraded'
    else:
        cluster_health = 'Optimal'

    # Find out our storage health from Ceph
    ceph_status = zkhandler.readdata(zk_conn, '/ceph').split('\n')
    ceph_health = ceph_status[2].split()[-1]

    # Parse the status output to get the health indicators
    line_record = False
    for index, line in enumerate(ceph_status):
        if re.search('services:', line):
            line_record = False
        if line_record and len(line.strip()) > 0:
            storage_health_msg.append(line.strip())
        if re.search('health:', line):
            line_record = True

    if maint_state == 'true':
        storage_health = 'Maintenance'
    elif ceph_health != 'HEALTH_OK':
        storage_health = 'Degraded'
    else:
        storage_health = 'Optimal'

    # State lists
    node_state_combinations = [
        'run,ready', 'run,flush', 'run,flushed', 'run,unflush',
        'init,ready', 'init,flush', 'init,flushed', 'init,unflush',
        'stop,ready', 'stop,flush', 'stop,flushed', 'stop,unflush',
        'dead,ready', 'dead,flush', 'dead,flushed', 'dead,unflush'
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
        'health_msg': cluster_health_msg,
        'storage_health': storage_health,
        'storage_health_msg': storage_health_msg,
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
