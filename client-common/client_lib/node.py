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

import client_lib.ansiiprint as ansiiprint
import client_lib.common as common

def getInformationFromNode(zk_conn, node_name, long_output):
    node_daemon_state = zk_conn.get('/nodes/{}/daemonstate'.format(node_name))[0].decode('ascii')
    node_domain_state = zk_conn.get('/nodes/{}/domainstate'.format(node_name))[0].decode('ascii')
    node_cpu_count = zk_conn.get('/nodes/{}/staticdata'.format(node_name))[0].decode('ascii').split()[0]
    node_kernel = zk_conn.get('/nodes/{}/staticdata'.format(node_name))[0].decode('ascii').split()[1]
    node_os = zk_conn.get('/nodes/{}/staticdata'.format(node_name))[0].decode('ascii').split()[2]
    node_arch = zk_conn.get('/nodes/{}/staticdata'.format(node_name))[0].decode('ascii').split()[3]
    node_mem_used = zk_conn.get('/nodes/{}/memused'.format(node_name))[0].decode('ascii')
    node_mem_free = zk_conn.get('/nodes/{}/memfree'.format(node_name))[0].decode('ascii')
    node_mem_total = int(node_mem_used) + int(node_mem_free)
    node_load = zk_conn.get('/nodes/{}/cpuload'.format(node_name))[0].decode('ascii')
    node_domains_count = zk_conn.get('/nodes/{}/domainscount'.format(node_name))[0].decode('ascii')
    node_running_domains = zk_conn.get('/nodes/{}/runningdomains'.format(node_name))[0].decode('ascii').split()
    node_mem_allocated = 0
    for domain in node_running_domains:
        try:
            parsed_xml = common.getDomainXML(zk_conn, domain)
            duuid, dname, ddescription, dmemory, dvcpu, dvcputopo = common.getDomainMainDetails(parsed_xml)
            node_mem_allocated += int(dmemory)
        except AttributeError:
            click.echo('Error: Domain {} does not exist.'.format(domain))

    if node_daemon_state == 'run':
        daemon_state_colour = ansiiprint.green()
    elif node_daemon_state == 'stop':
        daemon_state_colour = ansiiprint.red()
    elif node_daemon_state == 'init':
        daemon_state_colour = ansiiprint.yellow()
    elif node_daemon_state == 'dead':
        daemon_state_colour = ansiiprint.red() + ansiiprint.bold()
    else:
        daemon_state_colour = ansiiprint.blue()

    if node_domain_state == 'ready':
        domain_state_colour = ansiiprint.green()
    else:
        domain_state_colour = ansiiprint.blue()

    # Format a nice output; do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append('{}Hypervisor Node information:{}'.format(ansiiprint.bold(), ansiiprint.end()))
    ainformation.append('')
    # Basic information
    ainformation.append('{}Name:{}                 {}'.format(ansiiprint.purple(), ansiiprint.end(), node_name))
    ainformation.append('{}Daemon State:{}         {}{}{}'.format(ansiiprint.purple(), ansiiprint.end(), daemon_state_colour, node_daemon_state, ansiiprint.end()))
    ainformation.append('{}Domain State:{}         {}{}{}'.format(ansiiprint.purple(), ansiiprint.end(), domain_state_colour, node_domain_state, ansiiprint.end()))
    ainformation.append('{}Active VM Count:{}      {}'.format(ansiiprint.purple(), ansiiprint.end(), node_domains_count))
    if long_output == True:
        ainformation.append('')
        ainformation.append('{}Architecture:{}         {}'.format(ansiiprint.purple(), ansiiprint.end(), node_arch))
        ainformation.append('{}Operating System:{}     {}'.format(ansiiprint.purple(), ansiiprint.end(), node_os))
        ainformation.append('{}Kernel Version:{}       {}'.format(ansiiprint.purple(), ansiiprint.end(), node_kernel))
    ainformation.append('')
    ainformation.append('{}CPUs:{}                 {}'.format(ansiiprint.purple(), ansiiprint.end(), node_cpu_count))
    ainformation.append('{}Load:{}                 {}'.format(ansiiprint.purple(), ansiiprint.end(), node_load))
    ainformation.append('{}Total RAM (MiB):{}      {}'.format(ansiiprint.purple(), ansiiprint.end(), node_mem_total))
    ainformation.append('{}Used RAM (MiB):{}       {}'.format(ansiiprint.purple(), ansiiprint.end(), node_mem_used))
    ainformation.append('{}Free RAM (MiB):{}       {}'.format(ansiiprint.purple(), ansiiprint.end(), node_mem_free))
    ainformation.append('{}Allocated RAM (MiB):{}  {}'.format(ansiiprint.purple(), ansiiprint.end(), node_mem_allocated))

    # Join it all together
    information = '\n'.join(ainformation)
    return information

#
# Direct Functions
#
def flush_node(zk_conn, node, wait):
    # Verify node is valid
    if not common.verifyNode(zk_conn, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    click.echo('Flushing hypervisor {} of running VMs.'.format(node))

    # Add the new domain to Zookeeper
    transaction = zk_conn.transaction()
    transaction.set_data('/nodes/{}/domainstate'.format(node), 'flush'.encode('ascii'))
    results = transaction.commit()

    if wait == True:
        while True:
            time.sleep(1)
            node_state = zk_conn.get('/nodes/{}/domainstate'.format(node))[0].decode('ascii')
            if node_state == "flushed":
                break

    return True, ''

def ready_node(zk_conn, node):
    # Verify node is valid
    if not common.verifyNode(zk_conn, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    click.echo('Restoring hypervisor {} to active service.'.format(node))

    # Add the new domain to Zookeeper
    transaction = zk_conn.transaction()
    transaction.set_data('/nodes/{}/domainstate'.format(node), 'unflush'.encode('ascii'))
    results = transaction.commit()

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
        click.echo('{}Virtual machines on node:{}'.format(ansiiprint.bold(), ansiiprint.end()))
        # List all VMs on this node
        common.get_list(zk_conn, node, None)

    click.echo('')

    return True, ''

def get_list(zk_conn, limit):
    # Match our limit
    node_list = []
    full_node_list = zk_conn.get_children('/nodes')
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
        node_daemon_state[node_name] = zk_conn.get('/nodes/{}/daemonstate'.format(node_name))[0].decode('ascii')
        node_domain_state[node_name] = zk_conn.get('/nodes/{}/domainstate'.format(node_name))[0].decode('ascii')
        node_cpu_count[node_name] = zk_conn.get('/nodes/{}/staticdata'.format(node_name))[0].decode('ascii').split()[0]
        node_mem_used[node_name] = zk_conn.get('/nodes/{}/memused'.format(node_name))[0].decode('ascii')
        node_mem_free[node_name] = zk_conn.get('/nodes/{}/memfree'.format(node_name))[0].decode('ascii')
        node_mem_total[node_name] = int(node_mem_used[node_name]) + int(node_mem_free[node_name])
        node_load[node_name] = zk_conn.get('/nodes/{}/cpuload'.format(node_name))[0].decode('ascii')
        node_domains_count[node_name] = zk_conn.get('/nodes/{}/domainscount'.format(node_name))[0].decode('ascii')
        node_running_domains[node_name] = zk_conn.get('/nodes/{}/runningdomains'.format(node_name))[0].decode('ascii').split()
        node_mem_allocated[node_name] = 0
        for domain in node_running_domains[node_name]:
            try:
                parsed_xml = common.getDomainXML(zk_conn, domain)
                duuid, dname, ddescription, dmemory, dvcpu, dvcputopo = common.getDomainMainDetails(parsed_xml)
                node_mem_allocated[node_name] += int(dmemory)
            except AttributeError:
                click.echo('Error: Domain {} does not exist.'.format(domain))

    # Determine optimal column widths
    # Dynamic columns: node_name, hypervisor, migrated
    node_name_length = 0
    for node_name in node_list:
        # node_name column
        _node_name_length = len(node_name) + 1
        if _node_name_length > node_name_length:
            node_name_length = _node_name_length

    # Format the string (header)
    node_list_output.append(
        '{bold}{node_name: <{node_name_length}}  \
State: {daemon_state_colour}{node_daemon_state: <7}{end_colour} {domain_state_colour}{node_domain_state: <8}{end_colour}  \
Resources: {node_domains_count: <4} {node_cpu_count: <5} {node_load: <6}  \
RAM (MiB): {node_mem_total: <6} {node_mem_used: <6} {node_mem_free: <6} {node_mem_allocated: <6}{end_bold}'.format(
            node_name_length=node_name_length,
            bold=ansiiprint.bold(),
            end_bold=ansiiprint.end(),
            daemon_state_colour='',
            domain_state_colour='',
            end_colour='',
            node_name='Name',
            node_daemon_state='Daemon',
            node_domain_state='Domains',
            node_domains_count='VMs',
            node_cpu_count='CPUs',
            node_load='Load',
            node_mem_total='Total',
            node_mem_used='Used',
            node_mem_free='Free',
            node_mem_allocated='VMs',
        )
    )
            
    # Format the string (elements)
    for node_name in node_list:
        if node_daemon_state[node_name] == 'run':
            daemon_state_colour = ansiiprint.green()
        elif node_daemon_state[node_name] == 'stop':
            daemon_state_colour = ansiiprint.red()
        elif node_daemon_state[node_name] == 'init':
            daemon_state_colour = ansiiprint.yellow()
        elif node_daemon_state[node_name] == 'dead':
            daemon_state_colour = ansiiprint.red() + ansiiprint.bold()
        else:
            daemon_state_colour = ansiiprint.blue()

        if node_mem_allocated[node_name] >= node_mem_total[node_name]:
            node_domain_state[node_name] = 'overprov'
            domain_state_colour = ansiiprint.yellow()
        elif node_domain_state[node_name] == 'ready':
            domain_state_colour = ansiiprint.green()
        else:
            domain_state_colour = ansiiprint.blue()

        node_list_output.append(
            '{bold}{node_name: <{node_name_length}}  \
       {daemon_state_colour}{node_daemon_state: <7}{end_colour} {domain_state_colour}{node_domain_state: <8}{end_colour}  \
           {node_domains_count: <4} {node_cpu_count: <5} {node_load: <6}  \
           {node_mem_total: <6} {node_mem_used: <6} {node_mem_free: <6} {node_mem_allocated: <6}{end_bold}'.format(
                node_name_length=node_name_length,
                bold='',
                end_bold='',
                daemon_state_colour=daemon_state_colour,
                domain_state_colour=domain_state_colour,
                end_colour=ansiiprint.end(),
                node_name=node_name,
                node_daemon_state=node_daemon_state[node_name],
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
