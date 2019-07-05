#!/usr/bin/env python3

# node.py - PVC client function library, node management
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

import os
import socket
import time
import uuid
import re
import tempfile
import subprocess
import difflib
import colorama
import click
import lxml.objectify
import configparser
import kazoo.client

import client_lib.ansiprint as ansiprint
import client_lib.zkhandler as zkhandler
import client_lib.common as common
import client_lib.vm as pvc_vm

def getNodeInformation(zk_conn, node_name):
    """
    Gather information about a node from the Zookeeper database and return a dict() containing it.
    """
    node_daemon_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(node_name))
    node_coordinator_state = zkhandler.readdata(zk_conn, '/nodes/{}/routerstate'.format(node_name))
    node_domain_state = zkhandler.readdata(zk_conn, '/nodes/{}/domainstate'.format(node_name))
    node_static_data = zkhandler.readdata(zk_conn, '/nodes/{}/staticdata'.format(node_name)).split()
    node_cpu_count = node_static_data[0]
    node_kernel = node_static_data[1]
    node_os = node_static_data[2]
    node_arch = node_static_data[3]
    node_vcpu_allocated = zkhandler.readdata(zk_conn, 'nodes/{}/vcpualloc'.format(node_name))
    node_mem_total = int(zkhandler.readdata(zk_conn, '/nodes/{}/memtotal'.format(node_name)))
    node_mem_allocated = int(zkhandler.readdata(zk_conn, '/nodes/{}/memalloc'.format(node_name)))
    node_mem_used = int(zkhandler.readdata(zk_conn, '/nodes/{}/memused'.format(node_name)))
    node_mem_free = int(zkhandler.readdata(zk_conn, '/nodes/{}/memfree'.format(node_name)))
    node_load = zkhandler.readdata(zk_conn, '/nodes/{}/cpuload'.format(node_name))
    node_domains_count = zkhandler.readdata(zk_conn, '/nodes/{}/domainscount'.format(node_name))
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
        return False, 'Node {} is already in secondary router mode.'.format(node)

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
        return False, 'Node {} is already in primary router mode.'.format(node)

    return True, retmsg

def flush_node(zk_conn, node, wait):
    # Verify node is valid
    if not common.verifyNode(zk_conn, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    if zkhandler.readdata(zk_conn, '/locks/flush_lock') == 'True':
        if not wait:
            retmsg = 'A lock currently exists; use --wait to wait for it, or try again later.'.format(node)
            return False, retmsg
        retmsg = 'A lock currently exists; waiting for it to complete... '
        lock_wait = True
    else:
        retmsg = 'Flushing hypervisor {} of running VMs.'.format(node)
        lock_wait = False
        
    # Wait cannot be triggered from the API
    if wait:
        click.echo(retmsg)
        retmsg = ""
        if lock_wait:
            time.sleep(2)
            while zkhandler.readdata(zk_conn, '/locks/flush_lock') == 'True':
                time.sleep(2)
            click.echo('Previous flush completed. Proceeding with flush.')

    # Add the new domain to Zookeeper
    zkhandler.writedata(zk_conn, {
        '/nodes/{}/domainstate'.format(node): 'flush'
    })

    # Wait cannot be triggered from the API
    if wait:
        time.sleep(2)
        while zkhandler.readdata(zk_conn, '/locks/flush_lock') == 'True':
            time.sleep(2)

    return True, retmsg

def ready_node(zk_conn, node, wait):
    # Verify node is valid
    if not common.verifyNode(zk_conn, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    if zkhandler.readdata(zk_conn, '/locks/flush_lock') == 'True':
        if not wait:
            retmsg = 'A lock currently exists; use --wait to wait for it, or try again later.'.format(node)
            return False, retmsg
        retmsg = 'A lock currently exists; waiting for it to complete... '
        lock_wait = True
    else:
        retmsg = 'Restoring hypervisor {} to active service.'.format(node)
        lock_wait = False
        
    # Wait cannot be triggered from the API
    if wait:
        click.echo(retmsg)
        retmsg = ""
        if lock_wait:
            time.sleep(1)
            while zkhandler.readdata(zk_conn, '/locks/flush_lock') == 'True':
                time.sleep(1)
            click.echo('Previous flush completed. Proceeding with unflush.')

    # Add the new domain to Zookeeper
    zkhandler.writedata(zk_conn, {
        '/nodes/{}/domainstate'.format(node): 'unflush'
    })

    # Wait cannot be triggered from the API
    if wait:
        time.sleep(1)
        while zkhandler.readdata(zk_conn, '/locks/flush_lock') == 'True':
            time.sleep(1)

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

def get_list(zk_conn, limit):
    node_list = []
    full_node_list = zkhandler.listchildren(zk_conn, '/nodes')

    for node in full_node_list:
        if limit:
            try:
                # Implcitly assume fuzzy limits
                if not re.match('\^.*', limit):
                    limit = '.*' + limit
                if not re.match('.*\$', limit):
                    limit = limit + '.*'

                if re.match(limit, node):
                    node_list.append(getNodeInformation(zk_conn, node))
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            node_list.append(getNodeInformation(zk_conn, node))

    return True, node_list

#
# CLI-specific functions
#
def getOutputColours(node_information):
    if node_information['daemon_state'] == 'run':
        daemon_state_colour = ansiprint.green()
    elif node_information['daemon_state'] == 'stop':
        daemon_state_colour = ansiprint.red()
    elif node_information['daemon_state'] == 'shutdown':
        daemon_state_colour = ansiprint.yellow()
    elif node_information['daemon_state'] == 'init':
        daemon_state_colour = ansiprint.yellow()
    elif node_information['daemon_state'] == 'dead':
        daemon_state_colour = ansiprint.red() + ansiprint.bold()
    else:
        daemon_state_colour = ansiprint.blue()

    if node_information['coordinator_state'] == 'primary':
        coordinator_state_colour = ansiprint.green()
    elif node_information['coordinator_state'] == 'secondary':
        coordinator_state_colour = ansiprint.blue()
    else:
        coordinator_state_colour = ansiprint.purple()

    if node_information['domain_state'] == 'ready':
        domain_state_colour = ansiprint.green()
    else:
        domain_state_colour = ansiprint.blue()

    return daemon_state_colour, coordinator_state_colour, domain_state_colour

def format_info(node_information, long_output):
    daemon_state_colour, coordinator_state_colour, domain_state_colour = getOutputColours(node_information)

    # Format a nice output; do this line-by-line then concat the elements at the end
    ainformation = []
    # Basic information
    ainformation.append('{}Name:{}                 {}'.format(ansiprint.purple(), ansiprint.end(), node_information['name']))
    ainformation.append('{}Daemon State:{}         {}{}{}'.format(ansiprint.purple(), ansiprint.end(), daemon_state_colour, node_information['daemon_state'], ansiprint.end()))
    ainformation.append('{}Coordinator State:{}    {}{}{}'.format(ansiprint.purple(), ansiprint.end(), coordinator_state_colour, node_information['coordinator_state'], ansiprint.end()))
    ainformation.append('{}Domain State:{}         {}{}{}'.format(ansiprint.purple(), ansiprint.end(), domain_state_colour, node_information['domain_state'], ansiprint.end()))
    ainformation.append('{}Active VM Count:{}      {}'.format(ansiprint.purple(), ansiprint.end(), node_information['domains_count']))
    if long_output:
        ainformation.append('')
        ainformation.append('{}Architecture:{}         {}'.format(ansiprint.purple(), ansiprint.end(), node_information['arch']))
        ainformation.append('{}Operating System:{}     {}'.format(ansiprint.purple(), ansiprint.end(), node_information['os']))
        ainformation.append('{}Kernel Version:{}       {}'.format(ansiprint.purple(), ansiprint.end(), node_information['kernel']))
    ainformation.append('')
    ainformation.append('{}Host CPUs:{}            {}'.format(ansiprint.purple(), ansiprint.end(), node_information['vcpu']['total']))
    ainformation.append('{}vCPUs:{}                {}'.format(ansiprint.purple(), ansiprint.end(), node_information['vcpu']['allocated']))
    ainformation.append('{}Load:{}                 {}'.format(ansiprint.purple(), ansiprint.end(), node_information['load']))
    ainformation.append('{}Total RAM (MiB):{}      {}'.format(ansiprint.purple(), ansiprint.end(), node_information['memory']['total']))
    ainformation.append('{}Used RAM (MiB):{}       {}'.format(ansiprint.purple(), ansiprint.end(), node_information['memory']['used']))
    ainformation.append('{}Free RAM (MiB):{}       {}'.format(ansiprint.purple(), ansiprint.end(), node_information['memory']['free']))
    ainformation.append('{}Allocated RAM (MiB):{}  {}'.format(ansiprint.purple(), ansiprint.end(), node_information['memory']['allocated']))

    # Join it all together
    information = '\n'.join(ainformation)
    click.echo(information)

    click.echo('')

def format_list(node_list):
    node_list_output = []

    # Determine optimal column widths
    node_name_length = 5
    daemon_state_length = 7
    coordinator_state_length = 12
    domain_state_length = 8
    domains_count_length = 4
    cpu_count_length = 6
    load_length = 5
    mem_total_length = 6
    mem_used_length = 5
    mem_free_length = 5
    mem_alloc_length = 4
    for node_information in node_list:
        # node_name column
        _node_name_length = len(node_information['name']) + 1
        if _node_name_length > node_name_length:
            node_name_length = _node_name_length
        # daemon_state column
        _daemon_state_length = len(node_information['daemon_state']) + 1
        if _daemon_state_length > daemon_state_length:
            daemon_state_length = _daemon_state_length
        # coordinator_state column
        _coordinator_state_length = len(node_information['coordinator_state']) + 1
        if _coordinator_state_length > coordinator_state_length:
            coordinator_state_length = _coordinator_state_length
        # domain_state column
        _domain_state_length = len(node_information['domain_state']) + 1
        if _domain_state_length > domain_state_length:
            domain_state_length = _domain_state_length
        # domains_count column
        _domains_count_length = len(node_information['domains_count']) + 1
        if _domains_count_length > domains_count_length:
            domains_count_length = _domains_count_length
        # cpu_count column
        _cpu_count_length = len(node_information['cpu_count']) + 1
        if _cpu_count_length > cpu_count_length:
            cpu_count_length = _cpu_count_length
        # load column
        _load_length = len(node_information['load']) + 1
        if _load_length > load_length:
            load_length = _load_length
        # mem_total column
        _mem_total_length = len(str(node_information['memory']['total'])) + 1
        if _mem_total_length > mem_total_length:
            mem_total_length = _mem_total_length
        # mem_used column
        _mem_used_length = len(str(node_information['memory']['used'])) + 1
        if _mem_used_length > mem_used_length:
            mem_used_length = _mem_used_length
        # mem_free column
        _mem_free_length = len(str(node_information['memory']['free'])) + 1
        if _mem_free_length > mem_free_length:
            mem_free_length = _mem_free_length
        # mem_alloc column
        _mem_alloc_length = len(str(node_information['memory']['allocated'])) + 1
        if _mem_alloc_length > mem_alloc_length:
            mem_alloc_length = _mem_alloc_length

    # Format the string (header)
    node_list_output.append(
        '{bold}{node_name: <{node_name_length}} \
St: {daemon_state_colour}{node_daemon_state: <{daemon_state_length}}{end_colour} {coordinator_state_colour}{node_coordinator_state: <{coordinator_state_length}}{end_colour} {domain_state_colour}{node_domain_state: <{domain_state_length}}{end_colour} \
Res: {node_domains_count: <{domains_count_length}} {node_cpu_count: <{cpu_count_length}} {node_load: <{load_length}} \
Mem (M): {node_mem_total: <{mem_total_length}} {node_mem_used: <{mem_used_length}} {node_mem_free: <{mem_free_length}} {node_mem_allocated: <{mem_alloc_length}}{end_bold}'.format(
            node_name_length=node_name_length,
            daemon_state_length=daemon_state_length,
            coordinator_state_length=coordinator_state_length,
            domain_state_length=domain_state_length,
            domains_count_length=domains_count_length,
            cpu_count_length=cpu_count_length,
            load_length=load_length,
            mem_total_length=mem_total_length,
            mem_used_length=mem_used_length,
            mem_free_length=mem_free_length,
            mem_alloc_length=mem_alloc_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            daemon_state_colour='',
            coordinator_state_colour='',
            domain_state_colour='',
            end_colour='',
            node_name='Name',
            node_daemon_state='Daemon',
            node_coordinator_state='Coordinator',
            node_domain_state='Domain',
            node_domains_count='VMs',
            node_cpu_count='vCPUs',
            node_load='Load',
            node_mem_total='Total',
            node_mem_used='Used',
            node_mem_free='Free',
            node_mem_allocated='VMs'
        )
    )
            
    # Format the string (elements)
    for node_information in node_list:
        daemon_state_colour, coordinator_state_colour, domain_state_colour = getOutputColours(node_information)
        node_list_output.append(
            '{bold}{node_name: <{node_name_length}} \
    {daemon_state_colour}{node_daemon_state: <{daemon_state_length}}{end_colour} {coordinator_state_colour}{node_coordinator_state: <{coordinator_state_length}}{end_colour} {domain_state_colour}{node_domain_state: <{domain_state_length}}{end_colour} \
     {node_domains_count: <{domains_count_length}} {node_cpu_count: <{cpu_count_length}} {node_load: <{load_length}} \
         {node_mem_total: <{mem_total_length}} {node_mem_used: <{mem_used_length}} {node_mem_free: <{mem_free_length}} {node_mem_allocated: <{mem_alloc_length}}{end_bold}'.format(
                node_name_length=node_name_length,
                daemon_state_length=daemon_state_length,
                coordinator_state_length=coordinator_state_length,
                domain_state_length=domain_state_length,
                domains_count_length=domains_count_length,
                cpu_count_length=cpu_count_length,
                load_length=load_length,
                mem_total_length=mem_total_length,
                mem_used_length=mem_used_length,
                mem_free_length=mem_free_length,
                mem_alloc_length=mem_alloc_length,
                bold='',
                end_bold='',
                daemon_state_colour=daemon_state_colour,
                coordinator_state_colour=coordinator_state_colour,
                domain_state_colour=domain_state_colour,
                end_colour=ansiprint.end(),
                node_name=node_information['name'],
                node_daemon_state=node_information['daemon_state'],
                node_coordinator_state=node_information['coordinator_state'],
                node_domain_state=node_information['domain_state'],
                node_domains_count=node_information['domains_count'],
                node_cpu_count=node_information['vcpu']['allocated'],
                node_load=node_information['load'],
                node_mem_total=node_information['memory']['total'],
                node_mem_used=node_information['memory']['used'],
                node_mem_free=node_information['memory']['free'],
                node_mem_allocated=node_information['memory']['allocated']
            )
        )

    click.echo('\n'.join(sorted(node_list_output)))
