#!/usr/bin/env python3

# router.py - PVC client function library, router management
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
import client_lib.zkhandler as zkhandler
import client_lib.common as common

def getInformationFromRouter(zk_conn, router_name, long_output):
    router_daemon_state = zk_conn.get('/routers/{}/daemonstate'.format(router_name))[0].decode('ascii')
    router_network_state = zk_conn.get('/routers/{}/networkstate'.format(router_name))[0].decode('ascii')
    router_cpu_count = zk_conn.get('/routers/{}/staticdata'.format(router_name))[0].decode('ascii').split()[0]
    router_cpu_load = zk_conn.get('/routers/{}/cpuload'.format(router_name))[0].decode('ascii').split()[0]
    router_kernel = zk_conn.get('/routers/{}/staticdata'.format(router_name))[0].decode('ascii').split()[1]
    router_os = zk_conn.get('/routers/{}/staticdata'.format(router_name))[0].decode('ascii').split()[2]
    router_arch = zk_conn.get('/routers/{}/staticdata'.format(router_name))[0].decode('ascii').split()[3]

    if router_daemon_state == 'run':
        daemon_state_colour = ansiiprint.green()
    elif router_daemon_state == 'stop':
        daemon_state_colour = ansiiprint.red()
    elif router_daemon_state == 'init':
        daemon_state_colour = ansiiprint.yellow()
    elif router_daemon_state == 'dead':
        daemon_state_colour = ansiiprint.red() + ansiiprint.bold()
    else:
        daemon_state_colour = ansiiprint.blue()

    if router_network_state == 'primary':
        network_state_colour = ansiiprint.green()
    else:
        network_state_colour = ansiiprint.blue()

    # Format a nice output; do this line-by-line then concat the elements at the end
    ainformation = []
    ainformation.append('{}Router information:{}'.format(ansiiprint.bold(), ansiiprint.end()))
    ainformation.append('')
    # Basic information
    ainformation.append('{}Name:{}                 {}'.format(ansiiprint.purple(), ansiiprint.end(), router_name))
    ainformation.append('{}Daemon State:{}         {}{}{}'.format(ansiiprint.purple(), ansiiprint.end(), daemon_state_colour, router_daemon_state, ansiiprint.end()))
    ainformation.append('{}Network State:{}        {}{}{}'.format(ansiiprint.purple(), ansiiprint.end(), network_state_colour, router_network_state, ansiiprint.end()))
    ainformation.append('{}CPUs:{}                 {}'.format(ansiiprint.purple(), ansiiprint.end(), router_cpu_count))
    ainformation.append('{}Load:{}                 {}'.format(ansiiprint.purple(), ansiiprint.end(), router_cpu_load))
    if long_output == True:
        ainformation.append('')
        ainformation.append('{}Architecture:{}         {}'.format(ansiiprint.purple(), ansiiprint.end(), router_arch))
        ainformation.append('{}Operating System:{}     {}'.format(ansiiprint.purple(), ansiiprint.end(), router_os))
        ainformation.append('{}Kernel Version:{}       {}'.format(ansiiprint.purple(), ansiiprint.end(), router_kernel))

    # Join it all together
    information = '\n'.join(ainformation)
    return information

#
# Direct Functions
#
def secondary_router(zk_conn, router):
    # Verify router is valid
    if not common.verifyRouter(zk_conn, router):
        return False, 'ERROR: No router named "{}" is present in the cluster.'.format(router)

    click.echo('Setting router {} in secondary mode.'.format(router))
    zkhandler.writedata(zk_conn, { '/routers/{}/networkstate'.format(router): 'secondary' })
    return True, ''

def primary_router(zk_conn, router):
    # Verify router is valid
    if not common.verifyRouter(zk_conn, router):
        return False, 'ERROR: No router named "{}" is present in the cluster.'.format(router)

    click.echo('Setting router {} in primary mode.'.format(router))
    zkhandler.writedata(zk_conn, { '/routers/{}/networkstate'.format(router): 'primary' })
    return True, ''

def get_info(zk_conn, router, long_output):
    # Verify router is valid
    if not common.verifyRouter(zk_conn, router):
        return False, 'ERROR: No router named "{}" is present in the cluster.'.format(router)

    # Get information about router in a pretty format
    information = getInformationFromRouter(zk_conn, router, long_output)
    click.echo(information)
    return True, ''

def get_list(zk_conn, limit):
    # Match our limit
    router_list = []
    full_router_list = zk_conn.get_children('/routers')
    for router in full_router_list:
        if limit != None:
            try:
                # Implcitly assume fuzzy limits
                if re.match('\^.*', limit) == None:
                    limit = '.*' + limit
                if re.match('.*\$', limit) == None:
                    limit = limit + '.*'

                if re.match(limit, router) != None:
                    router_list.append(router)
            except Exception as e:
                return False, 'Regex Error: {}'.format(e)
        else:
            router_list.append(router)

    router_list_output = []
    router_daemon_state = {}
    router_network_state = {}
    router_cpu_count = {}
    router_cpu_load = {}

    # Gather information for printing
    for router_name in router_list:
        router_daemon_state[router_name] = zk_conn.get('/routers/{}/daemonstate'.format(router_name))[0].decode('ascii')
        router_network_state[router_name] = zk_conn.get('/routers/{}/networkstate'.format(router_name))[0].decode('ascii')
        router_cpu_count[router_name] = zk_conn.get('/routers/{}/staticdata'.format(router_name))[0].decode('ascii').split()[0]
        router_cpu_load[router_name] = zk_conn.get('/routers/{}/cpuload'.format(router_name))[0].decode('ascii').split()[0]

    # Determine optimal column widths
    # Dynamic columns: router_name
    router_name_length = 0
    for router_name in router_list:
        # router_name column
        _router_name_length = len(router_name) + 1
        if _router_name_length > router_name_length:
            router_name_length = _router_name_length

    # Format the string (header)
    router_list_output.append(
        '{bold}{router_name: <{router_name_length}}  \
State: {daemon_state_colour}{router_daemon_state: <7}{end_colour} {network_state_colour}{router_network_state: <10}{end_colour}  \
Resources: {router_cpu_count: <5} {router_cpu_load: <6}{end_bold}'.format(
            router_name_length=router_name_length,
            bold=ansiiprint.bold(),
            end_bold=ansiiprint.end(),
            daemon_state_colour='',
            network_state_colour='',
            end_colour='',
            router_name='Name',
            router_daemon_state='Daemon',
            router_network_state='Network',
            router_cpu_count='CPUs',
            router_cpu_load='Load'
        )
    )
            
    # Format the string (elements)
    for router_name in router_list:
        if router_daemon_state[router_name] == 'run':
            daemon_state_colour = ansiiprint.green()
        elif router_daemon_state[router_name] == 'stop':
            daemon_state_colour = ansiiprint.red()
        elif router_daemon_state[router_name] == 'init':
            daemon_state_colour = ansiiprint.yellow()
        elif router_daemon_state[router_name] == 'dead':
            daemon_state_colour = ansiiprint.red() + ansiiprint.bold()
        else:
            daemon_state_colour = ansiiprint.blue()

        if router_network_state[router_name] == 'primary':
            network_state_colour = ansiiprint.green()
        else:
            network_state_colour = ansiiprint.blue()

        router_list_output.append(
            '{bold}{router_name: <{router_name_length}}  \
       {daemon_state_colour}{router_daemon_state: <7}{end_colour} {network_state_colour}{router_network_state: <10}{end_colour}  \
           {router_cpu_count: <5} {router_cpu_load: <6}{end_bold}'.format(
                router_name_length=router_name_length,
                bold='',
                end_bold='',
                daemon_state_colour=daemon_state_colour,
                network_state_colour=network_state_colour,
                end_colour=ansiiprint.end(),
                router_name=router_name,
                router_daemon_state=router_daemon_state[router_name],
                router_network_state=router_network_state[router_name],
                router_cpu_count=router_cpu_count[router_name],
                router_cpu_load=router_cpu_load[router_name]
            )
        )

    click.echo('\n'.join(sorted(router_list_output)))

    return True, ''
