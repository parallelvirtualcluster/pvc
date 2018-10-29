#!/usr/bin/env python3

# ceph.py - PVC client function library, Ceph cluster fuctions
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

#
# Supplemental functions
#


#
# Direct functions
#
def get_status(zk_conn):
    status_data = zkhandler.readdata(zk_conn, '/ceph').rstrip()
    primary_node = zkhandler.readdata(zk_conn, '/primary_node')
    click.echo('{bold}Ceph cluster status (primary node {end}{blue}{primary}{end}{bold}){end}\n'.format(bold=ansiprint.bold(), end=ansiprint.end(), blue=ansiprint.blue(), primary=primary_node))
    click.echo(status_data)
    click.echo('')
    return True, ''

def add_osd(zk_conn, node, device):
    if not common.verifyNode(zk_conn, node):
        return False, 'ERROR: No node named "{}" is present in the cluster.'.format(node)

    # Tell the cluster to create a new OSD for the host
    new_osd_string = 'new {},{}'.format(node, device) 
    zkhandler.writedata(zk_conn, {'/ceph/osd_cmd': new_osd_string})
    click.echo('Created new OSD with block device {} on node {}.'.format(device, node))
    return True, ''

def remove_osd(zk_conn, osd_id):
    remove_osd_string = 'remove {}'.format(osd_id)
    zkhandler.writedata(zk_conn, {'/ceph/osd_cmd': remove_osd_string})
    click.echo('Remove OSD {} from the cluster.'.format(osd_id))
    return True, ''
