#!/usr/bin/env python3

# node.py - PVC client function library, node management
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

import time
import re

import daemon_lib.zkhandler as zkhandler
import daemon_lib.common as common


def getNodeInformation(zk_conn, node_name):
    """
    Gather information about a node from the Zookeeper database and return a dict() containing it.
    """
    node_daemon_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(node_name))
    node_coordinator_state = zkhandler.readdata(zk_conn, '/nodes/{}/routerstate'.format(node_name))
    node_domain_state = zkhandler.readdata(zk_conn, '/nodes/{}/domainstate'.format(node_name))
    node_static_data = zkhandler.readdata(zk_conn, '/nodes/{}/staticdata'.format(node_name)).split()
    node_cpu_count = int(node_static_data[0])
    node_kernel = node_static_data[1]
    node_os = node_static_data[2]
    node_arch = node_static_data[3]
    node_vcpu_allocated = int(zkhandler.readdata(zk_conn, 'nodes/{}/vcpualloc'.format(node_name)))
    node_mem_total = int(zkhandler.readdata(zk_conn, '/nodes/{}/memtotal'.format(node_name)))
    node_mem_allocated = int(zkhandler.readdata(zk_conn, '/nodes/{}/memalloc'.format(node_name)))
    node_mem_provisioned = int(zkhandler.readdata(zk_conn, '/nodes/{}/memprov'.format(node_name)))
    node_mem_used = int(zkhandler.readdata(zk_conn, '/nodes/{}/memused'.format(node_name)))
    node_mem_free = int(zkhandler.readdata(zk_conn, '/nodes/{}/memfree'.format(node_name)))
    node_load = float(zkhandler.readdata(zk_conn, '/nodes/{}/cpuload'.format(node_name)))
    node_domains_count = int(zkhandler.readdata(zk_conn, '/nodes/{}/domainscount'.format(node_name)))
    node_running_domains = zkhandler.readdata(zk_conn, '/nodes/{}/runningdomains'.format(node_name)).split()

    # Construct a data structure to represent the data
    node_information = {
        'name': node_name,
        'daemon_state': node_daemon_state,
        'coordinator_state': node_coordinator_state,
        'domain_state': node_domain_state,
        'cpu_count': node_cpu_count,
        'kernel': node_kernel,
        'os': node_os,
        'arch': node_arch,
        'load': node_load,
        'domains_count': node_domains_count,
        'running_domains': node_running_domains,
        'vcpu': {
            'total': node_cpu_count,
            'allocated': node_vcpu_allocated
        },
        'memory': {
            'total': node_mem_total,
            'allocated': node_mem_allocated,
            'provisioned': node_mem_provisioned,
            'used': node_mem_used,
            'free': node_mem_free
        }
    }
    return node_information


#
# Direct Functions
#
def secondary_node(zk_conn, node):
    # Verify node is valid
    if not common.verifyNode(zk_conn, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    # Ensure node is a coordinator
    daemon_mode = zkhandler.readdata(zk_conn, '/nodes/{}/daemonmode'.format(node))
    if daemon_mode == 'hypervisor':
        return False, 'ERROR: Cannot change router mode on non-coordinator node "{}"'.format(node)

    # Ensure node is in run daemonstate
    daemon_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(node))
    if daemon_state != 'run':
        return False, 'ERROR: Node "{}" is not active'.format(node)

    # Get current state
    current_state = zkhandler.readdata(zk_conn, '/nodes/{}/routerstate'.format(node))
    if current_state == 'primary':
        retmsg = 'Setting node {} in secondary router mode.'.format(node)
        zkhandler.writedata(zk_conn, {
            '/primary_node': 'none'
        })
    else:
        return False, 'Node "{}" is already in secondary router mode.'.format(node)

    return True, retmsg


def primary_node(zk_conn, node):
    # Verify node is valid
    if not common.verifyNode(zk_conn, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    # Ensure node is a coordinator
    daemon_mode = zkhandler.readdata(zk_conn, '/nodes/{}/daemonmode'.format(node))
    if daemon_mode == 'hypervisor':
        return False, 'ERROR: Cannot change router mode on non-coordinator node "{}"'.format(node)

    # Ensure node is in run daemonstate
    daemon_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(node))
    if daemon_state != 'run':
        return False, 'ERROR: Node "{}" is not active'.format(node)

    # Get current state
    current_state = zkhandler.readdata(zk_conn, '/nodes/{}/routerstate'.format(node))
    if current_state == 'secondary':
        retmsg = 'Setting node {} in primary router mode.'.format(node)
        zkhandler.writedata(zk_conn, {
            '/primary_node': node
        })
    else:
        return False, 'Node "{}" is already in primary router mode.'.format(node)

    return True, retmsg


def flush_node(zk_conn, node, wait=False):
    # Verify node is valid
    if not common.verifyNode(zk_conn, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    retmsg = 'Flushing hypervisor {} of running VMs.'.format(node)

    # Add the new domain to Zookeeper
    zkhandler.writedata(zk_conn, {
        '/nodes/{}/domainstate'.format(node): 'flush'
    })

    if wait:
        while zkhandler.readdata(zk_conn, '/nodes/{}/domainstate'.format(node)) == 'flush':
            time.sleep(1)
        retmsg = 'Flushed hypervisor {} of running VMs.'.format(node)

    return True, retmsg


def ready_node(zk_conn, node, wait=False):
    # Verify node is valid
    if not common.verifyNode(zk_conn, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    retmsg = 'Restoring hypervisor {} to active service.'.format(node)

    # Add the new domain to Zookeeper
    zkhandler.writedata(zk_conn, {
        '/nodes/{}/domainstate'.format(node): 'unflush'
    })

    if wait:
        while zkhandler.readdata(zk_conn, '/nodes/{}/domainstate'.format(node)) == 'unflush':
            time.sleep(1)
        retmsg = 'Restored hypervisor {} to active service.'.format(node)

    return True, retmsg


def get_info(zk_conn, node):
    # Verify node is valid
    if not common.verifyNode(zk_conn, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    # Get information about node in a pretty format
    node_information = getNodeInformation(zk_conn, node)
    if not node_information:
        return False, 'ERROR: Could not get information about node "{}".'.format(node)

    return True, node_information


def get_list(zk_conn, limit, daemon_state=None, coordinator_state=None, domain_state=None, is_fuzzy=True):
    node_list = []
    full_node_list = zkhandler.listchildren(zk_conn, '/nodes')

    for node in full_node_list:
        if limit:
            try:
                if not is_fuzzy:
                    limit = '^' + limit + '$'

                if re.match(limit, node):
                    node_list.append(getNodeInformation(zk_conn, node))
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            node_list.append(getNodeInformation(zk_conn, node))

    if daemon_state or coordinator_state or domain_state:
        limited_node_list = []
        for node in node_list:
            add_node = False
            if daemon_state and node['daemon_state'] == daemon_state:
                add_node = True
            if coordinator_state and node['coordinator_state'] == coordinator_state:
                add_node = True
            if domain_state and node['domain_state'] == domain_state:
                add_node = True
            if add_node:
                limited_node_list.append(node)
        node_list = limited_node_list

    return True, node_list
