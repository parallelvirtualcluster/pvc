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

def getInformationFromNode(zk_conn, node_name, long_output):
    node_daemon_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(node_name))
    node_router_state = zkhandler.readdata(zk_conn, '/nodes/{}/routerstate'.format(node_name))
    node_domain_state = zkhandler.readdata(zk_conn, '/nodes/{}/domainstate'.format(node_name))
    node_static_data = zkhandler.readdata(zk_conn, '/nodes/{}/staticdata'.format(node_name)).split()
    node_cpu_count = node_static_data[0]
    node_kernel = node_static_data[1]
    node_os = node_static_data[2]
    node_arch = node_static_data[3]
    node_mem_allocated = int(zkhandler.readdata(zk_conn, '/nodes/{}/memalloc'.format(node_name)))
    node_mem_used = int(zkhandler.readdata(zk_conn, '/nodes/{}/memused'.format(node_name)))
    node_mem_free = int(zkhandler.readdata(zk_conn, '/nodes/{}/memfree'.format(node_name)))
    node_mem_total = node_mem_used + node_mem_free
    node_load = zkhandler.readdata(zk_conn, '/nodes/{}/cpuload'.format(node_name))
    node_domains_count = zkhandler.readdata(zk_conn, '/nodes/{}/domainscount'.format(node_name))
    node_running_domains = zkhandler.readdata(zk_conn, '/nodes/{}/runningdomains'.format(node_name)).split()

    if node_daemon_state == 'run':
        daemon_state_colour = ansiprint.green()
    elif node_daemon_state == 'stop':
        daemon_state_colour = ansiprint.red()
    elif node_daemon_state == 'init':
        daemon_state_colour = ansiprint.yellow()
    elif node_daemon_state == 'dead':
        daemon_state_colour = ansiprint.red() + ansiprint.bold()
    else:
        daemon_state_colour = ansiprint.blue()

    if node_router_state == 'primary':
        router_state_colour = ansiprint.green()
    elif node_router_state == 'secondary':
        router_state_colour = ansiprint.blue()
    else:
        router_state_colour = ansiprint.purple()

    if node_domain_state == 'ready':
        domain_state_colour = ansiprint.green()
    else:
        domain_state_colour = ansiprint.blue()

    # Format a nice output; do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append('{}Node information:{}'.format(ansiprint.bold(), ansiprint.end()))
    ainformation.append('')
    # Basic information
    ainformation.append('{}Name:{}                 {}'.format(ansiprint.purple(), ansiprint.end(), node_name))
    ainformation.append('{}Daemon State:{}         {}{}{}'.format(ansiprint.purple(), ansiprint.end(), daemon_state_colour, node_daemon_state, ansiprint.end()))
    ainformation.append('{}Router State:{}         {}{}{}'.format(ansiprint.purple(), ansiprint.end(), router_state_colour, node_router_state, ansiprint.end()))
    ainformation.append('{}Domain State:{}         {}{}{}'.format(ansiprint.purple(), ansiprint.end(), domain_state_colour, node_domain_state, ansiprint.end()))
    ainformation.append('{}Active VM Count:{}      {}'.format(ansiprint.purple(), ansiprint.end(), node_domains_count))
    if long_output == True:
        ainformation.append('')
        ainformation.append('{}Architecture:{}         {}'.format(ansiprint.purple(), ansiprint.end(), node_arch))
        ainformation.append('{}Operating System:{}     {}'.format(ansiprint.purple(), ansiprint.end(), node_os))
        ainformation.append('{}Kernel Version:{}       {}'.format(ansiprint.purple(), ansiprint.end(), node_kernel))
    ainformation.append('')
    ainformation.append('{}CPUs:{}                 {}'.format(ansiprint.purple(), ansiprint.end(), node_cpu_count))
    ainformation.append('{}Load:{}                 {}'.format(ansiprint.purple(), ansiprint.end(), node_load))
    ainformation.append('{}Total RAM (MiB):{}      {}'.format(ansiprint.purple(), ansiprint.end(), node_mem_total))
    ainformation.append('{}Used RAM (MiB):{}       {}'.format(ansiprint.purple(), ansiprint.end(), node_mem_used))
    ainformation.append('{}Free RAM (MiB):{}       {}'.format(ansiprint.purple(), ansiprint.end(), node_mem_free))
    ainformation.append('{}Allocated RAM (MiB):{}  {}'.format(ansiprint.purple(), ansiprint.end(), node_mem_allocated))

    # Join it all together
    information = '\n'.join(ainformation)
    return information

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

    # Get current state
    current_state = zkhandler.readdata(zk_conn, '/nodes/{}/routerstate'.format(node))
    if current_state == 'primary':
        click.echo('Setting node {} in secondary router mode.'.format(node))
        zkhandler.writedata(zk_conn, {
            '/primary_node': 'none'
        })
    else:
        click.echo('Node {} is already in secondary router mode.'.format(node))

    return True, ''

def primary_node(zk_conn, node):
    # Verify node is valid
    if not common.verifyNode(zk_conn, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    # Ensure node is a coordinator
    daemon_mode = zkhandler.readdata(zk_conn, '/nodes/{}/daemonmode'.format(node))
    if daemon_mode == 'hypervisor':
        return False, 'ERROR: Cannot change router mode on non-coordinator node "{}"'.format(node)

    # Get current state
    current_state = zkhandler.readdata(zk_conn, '/nodes/{}/routerstate'.format(node))
    if current_state == 'secondary':
        click.echo('Setting node {} in primary router mode.'.format(node))
        zkhandler.writedata(zk_conn, {
            '/primary_node': node
        })
    else:
        click.echo('Node {} is already in primary router mode.'.format(node))

    return True, ''

def flush_node(zk_conn, node, wait):
    # Verify node is valid
    if not common.verifyNode(zk_conn, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    click.echo('Flushing hypervisor {} of running VMs.'.format(node))

    # Add the new domain to Zookeeper
    zkhandler.writedata(zk_conn, {
        '/nodes/{}/domainstate'.format(node): 'flush'
    })

    if wait == True:
        while True:
            time.sleep(1)
            node_state = zkhandler.readdata(zk_conn, '/nodes/{}/domainstate'.format(node))
            if node_state == "flushed":
                break

    return True, ''

def ready_node(zk_conn, node):
    # Verify node is valid
    if not common.verifyNode(zk_conn, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    click.echo('Restoring hypervisor {} to active service.'.format(node))

    # Add the new domain to Zookeeper
    zkhandler.writedata(zk_conn, {
        '/nodes/{}/domainstate'.format(node): 'unflush'
    })

    return True, ''

def get_info(zk_conn, node, long_output):
    # Verify node is valid
    if not common.verifyNode(zk_conn, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    # Get information about node in a pretty format
    information = getInformationFromNode(zk_conn, node, long_output)

    if information == None:
        return False, 'ERROR: Could not find a node matching that name.'

    click.echo(information)

    if long_output == True:
        click.echo('')
        click.echo('{}Virtual machines on node:{}'.format(ansiprint.bold(), ansiprint.end()))
        click.echo('')
        # List all VMs on this node
        pvc_vm.get_list(zk_conn, node, None)

    click.echo('')

    return True, ''

def get_list(zk_conn, limit):
    # Match our limit
    node_list = []
    full_node_list = zkhandler.list_children(zk_conn, '/nodes')
    for node in full_node_list:
        if limit != None:
            try:
                # Implcitly assume fuzzy limits
                if re.match('\^.*', limit) == None:
                    limit = '.*' + limit
                if re.match('.*\$', limit) == None:
                    limit = limit + '.*'

                if re.match(limit, node) != None:
                    node_list.append(node)
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            node_list.append(node)

    node_list_output = []
    node_daemon_state = {}
    node_router_state = {}
    node_domain_state = {}
    node_cpu_count = {}
    node_mem_used = {}
    node_mem_free = {}
    node_mem_total = {}
    node_domains_count = {}
    node_running_domains = {}
    node_mem_allocated = {}
    node_load = {}

    # Gather information for printing
    for node_name in node_list:
        node_daemon_state[node_name] = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(node_name))
        node_router_state[node_name] = zkhandler.readdata(zk_conn, '/nodes/{}/routerstate'.format(node_name))
        node_domain_state[node_name] = zkhandler.readdata(zk_conn, '/nodes/{}/domainstate'.format(node_name))
        node_cpu_count[node_name] = zkhandler.readdata(zk_conn, '/nodes/{}/staticdata'.format(node_name)).split()[0]
        node_mem_allocated[node_name] = int(zkhandler.readdata(zk_conn, '/nodes/{}/memalloc'.format(node_name)))
        node_mem_used[node_name] = int(zkhandler.readdata(zk_conn, '/nodes/{}/memused'.format(node_name)))
        node_mem_free[node_name] = int(zkhandler.readdata(zk_conn, '/nodes/{}/memfree'.format(node_name)))
        node_mem_total[node_name] = node_mem_used[node_name] + node_mem_free[node_name]
        node_load[node_name] = zkhandler.readdata(zk_conn, '/nodes/{}/cpuload'.format(node_name))
        node_domains_count[node_name] = zkhandler.readdata(zk_conn, '/nodes/{}/domainscount'.format(node_name))
        node_running_domains[node_name] = zkhandler.readdata(zk_conn, '/nodes/{}/runningdomains'.format(node_name)).split()

    # Determine optimal column widths
    # Dynamic columns: node_name, daemon_state, network_state, domain_state, load
    node_name_length = 5
    daemon_state_length = 7
    router_state_length = 7
    domain_state_length = 8
    for node_name in node_list:
        # node_name column
        _node_name_length = len(node_name) + 1
        if _node_name_length > node_name_length:
            node_name_length = _node_name_length
        # daemon_state column
        _daemon_state_length = len(node_daemon_state[node_name]) + 1
        if _daemon_state_length > daemon_state_length:
            daemon_state_length = _daemon_state_length
        # router_state column
        _router_state_length = len(node_router_state[node_name]) + 1
        if _router_state_length > router_state_length:
            router_state_length = _router_state_length
        # domain_state column
        _domain_state_length = len(node_domain_state[node_name]) + 1
        if _domain_state_length > domain_state_length:
            domain_state_length = _domain_state_length

    # Format the string (header)
    node_list_output.append(
        '{bold}{node_name: <{node_name_length}}  \
State: {daemon_state_colour}{node_daemon_state: <{daemon_state_length}}{end_colour} {router_state_colour}{node_router_state: <{router_state_length}}{end_colour} {domain_state_colour}{node_domain_state: <{domain_state_length}}{end_colour}  \
Resources: {node_domains_count: <4} {node_cpu_count: <5} {node_load: <6}  \
RAM (MiB): {node_mem_total: <6} {node_mem_used: <6} {node_mem_free: <6} {node_mem_allocated: <6}{end_bold}'.format(
            node_name_length=node_name_length,
            daemon_state_length=daemon_state_length,
            router_state_length=router_state_length,
            domain_state_length=domain_state_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            daemon_state_colour='',
            router_state_colour='',
            domain_state_colour='',
            end_colour='',
            node_name='Name',
            node_daemon_state='Daemon',
            node_router_state='Router',
            node_domain_state='Domain',
            node_domains_count='VMs',
            node_cpu_count='CPUs',
            node_load='Load',
            node_mem_total='Total',
            node_mem_used='Used',
            node_mem_free='Free',
            node_mem_allocated='VMs'
        )
    )
            
    # Format the string (elements)
    for node_name in node_list:
        if node_daemon_state[node_name] == 'run':
            daemon_state_colour = ansiprint.green()
        elif node_daemon_state[node_name] == 'stop':
            daemon_state_colour = ansiprint.red()
        elif node_daemon_state[node_name] == 'init':
            daemon_state_colour = ansiprint.yellow()
        elif node_daemon_state[node_name] == 'dead':
            daemon_state_colour = ansiprint.red() + ansiprint.bold()
        else:
            daemon_state_colour = ansiprint.blue()

        if node_router_state[node_name] == 'primary':
            router_state_colour = ansiprint.green()
        elif node_router_state[node_name] == 'secondary':
            router_state_colour = ansiprint.blue()
        else:
            router_state_colour = ansiprint.purple()

        if node_mem_allocated[node_name] != 0 and node_mem_allocated[node_name] >= node_mem_total[node_name]:
            node_domain_state[node_name] = 'overprov'
            domain_state_colour = ansiprint.yellow()
        elif node_domain_state[node_name] == 'ready':
            domain_state_colour = ansiprint.green()
        else:
            domain_state_colour = ansiprint.blue()

        node_list_output.append(
            '{bold}{node_name: <{node_name_length}}  \
       {daemon_state_colour}{node_daemon_state: <{daemon_state_length}}{end_colour} {router_state_colour}{node_router_state: <{router_state_length}}{end_colour} {domain_state_colour}{node_domain_state: <{domain_state_length}}{end_colour}  \
           {node_domains_count: <4} {node_cpu_count: <5} {node_load: <6}  \
           {node_mem_total: <6} {node_mem_used: <6} {node_mem_free: <6} {node_mem_allocated: <6}{end_bold}'.format(
                node_name_length=node_name_length,
                daemon_state_length=daemon_state_length,
                router_state_length=router_state_length,
                domain_state_length=domain_state_length,
                bold='',
                end_bold='',
                daemon_state_colour=daemon_state_colour,
                router_state_colour=router_state_colour,
                domain_state_colour=domain_state_colour,
                end_colour=ansiprint.end(),
                node_name=node_name,
                node_daemon_state=node_daemon_state[node_name],
                node_router_state=node_router_state[node_name],
                node_domain_state=node_domain_state[node_name],
                node_domains_count=node_domains_count[node_name],
                node_cpu_count=node_cpu_count[node_name],
                node_load=node_load[node_name],
                node_mem_total=node_mem_total[node_name],
                node_mem_used=node_mem_used[node_name],
                node_mem_free=node_mem_free[node_name],
                node_mem_allocated=node_mem_allocated[node_name]
            )
        )

    click.echo('\n'.join(sorted(node_list_output)))

    return True, ''
