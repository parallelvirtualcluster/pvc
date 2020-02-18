#!/usr/bin/env python3

# provisioner.py - PVC API Provisioner functions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2020 Joshua M. Boniface <joshua@boniface.me>
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

import flask
import json
import psycopg2
import psycopg2.extras
import os
import re
import time
import shlex
import subprocess

import daemon_lib.common as pvc_common
import daemon_lib.node as pvc_node
import daemon_lib.vm as pvc_vm
import daemon_lib.network as pvc_network
import daemon_lib.ceph as pvc_ceph

import pvcapid.libvirt_schema as libvirt_schema

from pvcapid.ova import list_ova

#
# Exceptions (used by Celery tasks)
#
class ValidationError(Exception):
    """
    An exception that results from some value being un- or mis-defined.
    """
    pass

class ClusterError(Exception):
    """
    An exception that results from the PVC cluster being out of alignment with the action.
    """
    pass

class ProvisioningError(Exception):
    """
    An exception that results from a failure of a provisioning command.
    """
    pass

#
# Common functions
#

# Database connections
def open_database(config):
    conn = psycopg2.connect(
        host=config['database_host'],
        port=config['database_port'],
        dbname=config['database_name'],
        user=config['database_user'],
        password=config['database_password']
    )
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn, cur

def close_database(conn, cur, failed=False):
    if not failed:
        conn.commit()
    cur.close()
    conn.close()

#
# Template List functions
#
def list_template(limit, table, is_fuzzy=True):
    if limit:
        if is_fuzzy:
            # Handle fuzzy vs. non-fuzzy limits
            if not re.match('\^.*', limit):
                limit = '%' + limit
            else:
                limit = limit[1:]
            if not re.match('.*\$', limit):
                limit = limit + '%'
            else:
                limit = limit[:-1]

        args = (limit, )
        query = "SELECT * FROM {} WHERE name LIKE %s;".format(table)
    else:
        args = ()
        query = "SELECT * FROM {};".format(table)

    conn, cur = open_database(config)
    cur.execute(query, args)
    data = cur.fetchall()

    if table == 'network_template':
        for template_id, template_data in enumerate(data):
            # Fetch list of VNIs from network table
            query = "SELECT * FROM network WHERE network_template = %s;"
            args = (template_data['id'],)
            cur.execute(query, args)
            vnis = cur.fetchall()
            data[template_id]['networks'] = vnis

    if table == 'storage_template':
        for template_id, template_data in enumerate(data):
            # Fetch list of VNIs from network table
            query = 'SELECT * FROM storage WHERE storage_template = %s'
            args = (template_data['id'],)
            cur.execute(query, args)
            disks = cur.fetchall()
            data[template_id]['disks'] = disks

    close_database(conn, cur)

    return data

def list_template_system(limit, is_fuzzy=True):
    """
    Obtain a list of system templates.
    """
    data = list_template(limit, 'system_template', is_fuzzy)
    if data:
        return data, 200
    else:
        return {'message': 'No system templates found'}, 404

def list_template_network(limit, is_fuzzy=True):
    """
    Obtain a list of network templates.
    """
    data = list_template(limit, 'network_template', is_fuzzy)
    if data:
        return data, 200
    else:
        return {'message': 'No network templates found'}, 404

def list_template_network_vnis(name):
    """
    Obtain a list of network template VNIs.
    """
    data = list_template(name, 'network_template', is_fuzzy=False)[0]
    networks = data['networks']
    if networks:
        return networks, 200
    else:
        return {'message': 'No network template networks found'}, 404

def list_template_storage(limit, is_fuzzy=True):
    """
    Obtain a list of storage templates.
    """
    data = list_template(limit, 'storage_template', is_fuzzy)
    if data:
        return data, 200
    else:
        return {'message': 'No storage templates found'}, 404

def list_template_storage_disks(name):
    """
    Obtain a list of storage template disks.
    """
    data = list_template(name, 'storage_template', is_fuzzy=False)[0]
    disks = data['disks']
    if disks:
        return disks, 200
    else:
        return {'message': 'No storage template disks found'}, 404

def template_list(limit):
    system_templates, code = list_template_system(limit)
    if code != 200:
        system_templates = []
    network_templates, code = list_template_network(limit)
    if code != 200:
        network_templates = []
    storage_templates, code = list_template_storage(limit)
    if code != 200:
        storage_templates = []

    return { "system_templates": system_templates, "network_templates": network_templates, "storage_templates": storage_templates }

#
# Template Create functions
#
def create_template_system(name, vcpu_count, vram_mb, serial=False, vnc=False, vnc_bind=None, node_limit=None, node_selector=None, node_autostart=False, ova=None):
    if list_template_system(name, is_fuzzy=False)[-1] != 404:
        retmsg = { 'message': 'The system template "{}" already exists'.format(name) }
        retcode = 400
        return retmsg, retcode

    query = "INSERT INTO system_template (name, vcpu_count, vram_mb, serial, vnc, vnc_bind, node_limit, node_selector, node_autostart, ova) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);"
    args = (name, vcpu_count, vram_mb, serial, vnc, vnc_bind, node_limit, node_selector, node_autostart, ova)

    conn, cur = open_database(config)
    try:
        cur.execute(query, args)
        retmsg = { 'message': 'Added new system template "{}"'.format(name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to create system template "{}": {}'.format(name, e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

def create_template_network(name, mac_template=None):
    if list_template_network(name, is_fuzzy=False)[-1] != 404:
        retmsg = { 'message': 'The network template "{}" already exists'.format(name) }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "INSERT INTO network_template (name, mac_template) VALUES (%s, %s);"
        args = (name, mac_template)
        cur.execute(query, args)
        retmsg = { 'message': 'Added new network template "{}"'.format(name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to create network template "{}": {}'.format(name, e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

def create_template_network_element(name, vni):
    if list_template_network(name, is_fuzzy=False)[-1] != 200:
        retmsg = { 'message': 'The network template "{}" does not exist'.format(name) }
        retcode = 400
        return retmsg, retcode

    networks, code = list_template_network_vnis(name)
    if code != 200:
        networks = []
    found_vni = False
    for network in networks:
        if int(network['vni']) == vni:
            found_vni = True
    if found_vni:
        retmsg = { 'message': 'The VNI "{}" in network template "{}" already exists'.format(vni, name) }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "SELECT id FROM network_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        template_id = cur.fetchone()['id']
        query = "INSERT INTO network (network_template, vni) VALUES (%s, %s);"
        args = (template_id, vni)
        cur.execute(query, args)
        retmsg = { 'message': 'Added new network "{}" to network template "{}"'.format(vni, name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to create entry "{}"'.format(vni, e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

def create_template_storage(name):
    if list_template_storage(name, is_fuzzy=False)[-1] != 404:
        retmsg = { 'message': 'The storage template "{}" already exists'.format(name) }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "INSERT INTO storage_template (name) VALUES (%s);"
        args = (name,)
        cur.execute(query, args)
        retmsg = { 'message': 'Added new storage template "{}"'.format(name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to create entry "{}": {}'.format(name, e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

def create_template_storage_element(name, disk_id, pool, source_volume=None, disk_size_gb=None, filesystem=None, filesystem_args=[], mountpoint=None):
    if list_template_storage(name, is_fuzzy=False)[-1] != 200:
        retmsg = { 'message': 'The storage template "{}" does not exist'.format(name) }
        retcode = 400
        return retmsg, retcode

    disks, code = list_template_storage_disks(name)
    if code != 200:
        disks = []
    found_disk = False
    for disk in disks:
        if disk['disk_id'] == disk_id:
            found_disk = True
    if found_disk:
        retmsg = { 'message': 'The disk "{}" in storage template "{}" already exists'.format(disk_id, name) }
        retcode = 400
        return retmsg, retcode

    if mountpoint and not filesystem:
        retmsg = { "message": "A filesystem must be specified along with a mountpoint." }
        retcode = 400
        return retmsg, retcode

    if source_volume and (disk_size_gb or filesystem or mountpoint):
        retmsg = { "message": "Clone volumes are not compatible with disk size, filesystem, or mountpoint specifications." }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "SELECT id FROM storage_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        template_id = cur.fetchone()['id']
        query = "INSERT INTO storage (storage_template, pool, disk_id, source_volume, disk_size_gb, mountpoint, filesystem, filesystem_args) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);"
        if filesystem_args:
            fsargs = ' '.join(filesystem_args)
        else:
            fsargs = ''
        args = (template_id, pool, disk_id, source_volume, disk_size_gb, mountpoint, filesystem, fsargs)
        cur.execute(query, args)
        retmsg = { 'message': 'Added new disk "{}" to storage template "{}"'.format(disk_id, name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to create entry "{}"'.format(disk_id, e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

#
# Template Delete functions
#
def delete_template_system(name):
    if list_template_system(name, is_fuzzy=False)[-1] != 200:
        retmsg = { 'message': 'The system template "{}" does not exist'.format(name) }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "DELETE FROM system_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        retmsg = { "message": 'Removed system template "{}"'.format(name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to delete entry "{}": {}'.format(name, e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

def delete_template_network(name):
    if list_template_network(name, is_fuzzy=False)[-1] != 200:
        retmsg = { 'message': 'The network template "{}" does not exist'.format(name) }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "SELECT id FROM network_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        template_id = cur.fetchone()['id']
        query = "DELETE FROM network WHERE network_template = %s;"
        args = (template_id,)
        cur.execute(query, args)
        query = "DELETE FROM network_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        retmsg = { "message": 'Removed network template "{}"'.format(name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to delete entry "{}": {}'.format(name, e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

def delete_template_network_element(name, vni):
    if list_template_network(name, is_fuzzy=False)[-1] != 200:
        retmsg = { 'message': 'The network template "{}" does not exist'.format(name) }
        retcode = 400
        return retmsg, retcode

    networks, code = list_template_network_vnis(name)
    found_vni = False
    for network in networks:
        if network['vni'] == int(vni):
            found_vni = True
    if not found_vni:
        retmsg = { 'message': 'The VNI "{}" in network template "{}" does not exist'.format(vni, name) }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "SELECT id FROM network_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        template_id = cur.fetchone()['id']
        query = "DELETE FROM network WHERE network_template = %s and vni = %s;"
        args = (template_id, vni)
        cur.execute(query, args)
        retmsg = { "message": 'Removed network "{}" from network template "{}"'.format(vni, name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to delete entry "{}": {}'.format(name, e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

def delete_template_storage(name):
    if list_template_storage(name, is_fuzzy=False)[-1] != 200:
        retmsg = { 'message': 'The storage template "{}" does not exist'.format(name) }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "SELECT id FROM storage_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        template_id = cur.fetchone()['id']
        query = "DELETE FROM storage WHERE storage_template = %s;"
        args = (template_id,)
        cur.execute(query, args)
        query = "DELETE FROM storage_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        retmsg = { "message": 'Removed storage template "{}"'.format(name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to delete entry "{}": {}'.format(name, e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

def delete_template_storage_element(name, disk_id):
    if list_template_storage(name, is_fuzzy=False)[-1] != 200:
        retmsg = { 'message': 'The storage template "{}" does not exist'.format(name) }
        retcode = 400
        return retmsg, retcode

    disks, code = list_template_storage_disks(name)
    found_disk = False
    for disk in disks:
        if disk['disk_id'] == disk_id:
            found_disk = True
    if not found_disk:
        retmsg = { 'message': 'The disk "{}" in storage template "{}" does not exist'.format(disk_id, name) }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "SELECT id FROM storage_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        template_id = cur.fetchone()['id']
        query = "DELETE FROM storage WHERE storage_template = %s and disk_id = %s;"
        args = (template_id, disk_id)
        cur.execute(query, args)
        retmsg = { "message": 'Removed disk "{}" from storage template "{}"'.format(disk_id, name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to delete entry "{}": {}'.format(name, e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

#
# Userdata functions
#
def list_userdata(limit, is_fuzzy=True):
    if limit:
        if is_fuzzy:
            # Handle fuzzy vs. non-fuzzy limits
            if not re.match('\^.*', limit):
                limit = '%' + limit
            else:
                limit = limit[1:]
            if not re.match('.*\$', limit):
                limit = limit + '%'
            else:
                limit = limit[:-1]

        query = "SELECT * FROM {} WHERE name LIKE %s;".format('userdata')
        args = (limit, )
    else:
        query = "SELECT * FROM {};".format('userdata')
        args = ()

    conn, cur = open_database(config)
    cur.execute(query, args)
    data = cur.fetchall()
    close_database(conn, cur)
    if data:
        return data, 200
    else:
        return {'message': 'No userdata documents found'}, 404

def create_userdata(name, userdata):
    if list_userdata(name, is_fuzzy=False)[-1] != 404:
        retmsg = { 'message': 'The userdata document "{}" already exists'.format(name) }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "INSERT INTO userdata (name, userdata) VALUES (%s, %s);"
        args = (name, userdata)
        cur.execute(query, args)
        retmsg = { "message": 'Created userdata document "{}"'.format(name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to create entry "{}": {}'.format(name, e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

def update_userdata(name, userdata):
    if list_userdata(name, is_fuzzy=False)[-1] != 200:
        retmsg = { 'message': 'The userdata "{}" does not exist'.format(name) }
        retcode = 400
        return retmsg, retcode

    data, code = list_userdata(name, is_fuzzy=False)
    tid = data[0]['id']

    conn, cur = open_database(config)
    try:
        query = "UPDATE userdata SET userdata = %s WHERE id = %s;"
        args = (userdata, tid)
        cur.execute(query, args)
        retmsg = { "message": 'Updated userdata document "{}"'.format(name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to update entry "{}": {}'.format(name, e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

def delete_userdata(name):
    if list_userdata(name, is_fuzzy=False)[-1] != 200:
        retmsg = { 'message': 'The userdata "{}" does not exist'.format(name) }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "DELETE FROM userdata WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        retmsg = { "message": 'Removed userdata document "{}"'.format(name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to delete entry "{}"'.format(name), 'error': str(e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

#
# Script functions
#
def list_script(limit, is_fuzzy=True):
    if limit:
        if is_fuzzy:
            # Handle fuzzy vs. non-fuzzy limits
            if not re.match('\^.*', limit):
                limit = '%' + limit
            else:
                limit = limit[1:]
            if not re.match('.*\$', limit):
                limit = limit + '%'
            else:
                limit = limit[:-1]

        query = "SELECT * FROM {} WHERE name LIKE %s;".format('script')
        args = (limit, )
    else:
        query = "SELECT * FROM {};".format('script')
        args = ()

    conn, cur = open_database(config)
    cur.execute(query, args)
    data = cur.fetchall()
    close_database(conn, cur)
    if data:
        return data, 200
    else:
        return {'message': 'No scripts found'}, 404

def create_script(name, script):
    if list_script(name, is_fuzzy=False)[-1] != 404:
        retmsg = { 'message': 'The script "{}" already exists'.format(name) }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "INSERT INTO script (name, script) VALUES (%s, %s);"
        args = (name, script)
        cur.execute(query, args)
        retmsg = { "message": 'Created provisioning script "{}"'.format(name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to create entry "{}": {}'.format(name, e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

def update_script(name, script):
    if list_script(name, is_fuzzy=False)[-1] != 200:
        retmsg = { 'message': 'The script "{}" does not exist'.format(name) }
        retcode = 400
        return retmsg, retcode

    data, code = list_script(name, is_fuzzy=False)
    tid = data[0]['id']

    conn, cur = open_database(config)
    try:
        query = "UPDATE script SET script = %s WHERE id = %s;"
        args = (script, tid)
        cur.execute(query, args)
        retmsg = { "message": 'Updated provisioning script "{}"'.format(name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to update entry "{}": {}'.format(name, e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

def delete_script(name):
    if list_script(name, is_fuzzy=False)[-1] != 200:
        retmsg = { 'message': 'The script "{}" does not exist'.format(name) }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "DELETE FROM script WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        retmsg = { "message": 'Removed provisioning script "{}"'.format(name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to delete entry "{}"'.format(name), 'error': str(e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

#
# Profile functions
#
def list_profile(limit, is_fuzzy=True):
    if limit:
        if is_fuzzy:
            # Handle fuzzy vs. non-fuzzy limits
            if not re.match('\^.*', limit):
                limit = '%' + limit
            else:
                limit = limit[1:]
            if not re.match('.*\$', limit):
                limit = limit + '%'
            else:
                limit = limit[:-1]

        query = "SELECT * FROM {} WHERE name LIKE %s;".format('profile')
        args = (limit, )
    else:
        query = "SELECT * FROM {};".format('profile')
        args = ()

    conn, cur = open_database(config)
    cur.execute(query, args)
    orig_data = cur.fetchall()
    data = list()
    for profile in orig_data:
        profile_data = dict()
        profile_data['id'] = profile['id']
        profile_data['name'] = profile['name']
        profile_data['type'] = profile['profile_type']
        # Parse the name of each subelement
        for etype in 'system_template', 'network_template', 'storage_template', 'userdata', 'script', 'ova':
            query = 'SELECT name from {} WHERE id = %s'.format(etype)
            args = (profile[etype],)
            cur.execute(query, args)
            try:
                name = cur.fetchone()['name']
            except Exception as e:
                name = "N/A"
            profile_data[etype] = name
        # Split the arguments back into a list
        profile_data['arguments'] = profile['arguments'].split('|')
        # Append the new data to our actual output structure
        data.append(profile_data)
    close_database(conn, cur)
    if data:
        return data, 200
    else:
        return {'message': 'No profiles found'}, 404

def create_profile(name, profile_type, system_template, network_template, storage_template, userdata=None, script=None, ova=None, arguments=None):
    if list_profile(name, is_fuzzy=False)[-1] != 404:
        retmsg = { 'message': 'The profile "{}" already exists'.format(name) }
        retcode = 400
        return retmsg, retcode

    if profile_type not in ['provisioner', 'ova']:
        retmsg = { 'message': 'A valid profile type (provisioner, ova) must be specified' }
        retcode = 400
        return retmsg, retcode

    system_templates, code = list_template_system(None)
    system_template_id = None
    for template in system_templates:
        if template['name'] == system_template:
            system_template_id = template['id']
    if not system_template_id:
        retmsg = { 'message': 'The system template "{}" for profile "{}" does not exist'.format(system_template, name) }
        retcode = 400
        return retmsg, retcode

    network_templates, code = list_template_network(None)
    network_template_id = None
    for template in network_templates:
        if template['name'] == network_template:
            network_template_id = template['id']
    if not network_template_id and profile_type != 'ova':
        retmsg = { 'message': 'The network template "{}" for profile "{}" does not exist'.format(network_template, name) }
        retcode = 400
        return retmsg, retcode

    storage_templates, code = list_template_storage(None)
    storage_template_id = None
    for template in storage_templates:
        if template['name'] == storage_template:
            storage_template_id = template['id']
    if not storage_template_id and profile_type != 'ova':
        retmsg = { 'message': 'The storage template "{}" for profile "{}" does not exist'.format(storage_template, name) }
        retcode = 400
        return retmsg, retcode

    userdatas, code = list_userdata(None)
    userdata_id = None
    for template in userdatas:
        if template['name'] == userdata:
            userdata_id = template['id']

    scripts, code = list_script(None)
    script_id = None
    for scr in scripts:
        if scr['name'] == script:
            script_id = scr['id']

    ovas, code = list_ova(None)
    ova_id = None
    for ov in ovas:
        if ov['name'] == ova:
            ova_id = ov['id']

    if arguments is not None and isinstance(arguments, list):
        arguments_formatted = '|'.join(arguments)
    else:
        arguments_formatted = ''

    conn, cur = open_database(config)
    try:
        query = "INSERT INTO profile (name, profile_type, system_template, network_template, storage_template, userdata, script, ova, arguments) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);"
        args = (name, profile_type, system_template_id, network_template_id, storage_template_id, userdata_id, script_id, ova_id, arguments_formatted)
        cur.execute(query, args)
        retmsg = { "message": 'Created VM profile "{}"'.format(name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to create entry "{}": {}'.format(name, e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

def modify_profile(name, profile_type, system_template, network_template, storage_template, userdata, script, ova, arguments=None):
    if list_profile(name, is_fuzzy=False)[-1] != 200:
        retmsg = { 'message': 'The profile "{}" does not exist'.format(name) }
        retcode = 400
        return retmsg, retcode

    fields = []

    if profile_type is not None:
        if profile_type not in ['provisioner', 'ova']:
            retmsg = { 'message': 'A valid profile type (provisioner, ova) must be specified' }
            retcode = 400
            return retmsg, retcode
        fields.append({'field': 'type', 'data': profile_type})

    if system_template is not None:
        system_templates, code = list_template_system(None)
        system_template_id = None
        for template in system_templates:
            if template['name'] == system_template:
                system_template_id = template['id']
        if not system_template_id:
            retmsg = { 'message': 'The system template "{}" for profile "{}" does not exist'.format(system_template, name) }
            retcode = 400
            return retmsg, retcode
        fields.append({'field': 'system_template', 'data': system_template_id})

    if network_template is not None:
        network_templates, code = list_template_network(None)
        network_template_id = None
        for template in network_templates:
            if template['name'] == network_template:
                network_template_id = template['id']
        if not network_template_id:
            retmsg = { 'message': 'The network template "{}" for profile "{}" does not exist'.format(network_template, name) }
            retcode = 400
            return retmsg, retcode
        fields.append({'field': 'network_template', 'data': network_template_id})

    if storage_template is not None:
        storage_templates, code = list_template_storage(None)
        storage_template_id = None
        for template in storage_templates:
            if template['name'] == storage_template:
                storage_template_id = template['id']
        if not storage_template_id:
            retmsg = { 'message': 'The storage template "{}" for profile "{}" does not exist'.format(storage_template, name) }
            retcode = 400
            return retmsg, retcode
        fields.append({'field': 'storage_template', 'data': storage_template_id})

    if userdata is not None:
        userdatas, code = list_userdata(None)
        userdata_id = None
        for template in userdatas:
            if template['name'] == userdata:
                userdata_id = template['id']
        if not userdata_id:
            retmsg = { 'message': 'The userdata template "{}" for profile "{}" does not exist'.format(userdata, name) }
            retcode = 400
            return retmsg, retcode
        fields.append({'field': 'userdata', 'data': userdata_id})

    if script is not None:
        scripts, code = list_script(None)
        script_id = None
        for scr in scripts:
            if scr['name'] == script:
                script_id = scr['id']
        if not script_id:
            retmsg = { 'message': 'The script "{}" for profile "{}" does not exist'.format(script, name) }
            retcode = 400
            return retmsg, retcode
        fields.append({'field': 'script', 'data': script_id})

    if ova is not None:
        ovas, code = list_ova(None)
        ova_id = None
        for ov in ovas:
            if ov['name'] == ova:
                ova_id = ov['id']
        if not ova_id:
            retmsg = { 'message': 'The OVA "{}" for profile "{}" does not exist'.format(ova, name) }
            retcode = 400
            return retmsg, retcode
        fields.append({'field': 'ova', 'data': ova_id})

    if arguments is not None:
        if isinstance(arguments, list):
            arguments_formatted = '|'.join(arguments)
        else:
            arguments_formatted = ''
        fields.append({'field': 'arguments', 'data': arguments_formatted})

    conn, cur = open_database(config)
    try:
        for field in fields:
            query = "UPDATE profile SET {}=%s WHERE name=%s;".format(field.get('field'))
            args = (field.get('data'), name)
            cur.execute(query, args)
        retmsg = { "message": 'Modified VM profile "{}"'.format(name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to modify entry "{}": {}'.format(name, e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

def delete_profile(name):
    if list_profile(name, is_fuzzy=False)[-1] != 200:
        retmsg = { 'message': 'The profile "{}" does not exist'.format(name) }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "DELETE FROM profile WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        retmsg = { "message": 'Removed VM profile "{}"'.format(name) }
        retcode = 200
    except Exception as e:
        retmsg = { 'message': 'Failed to delete entry "{}": {}'.format(name, e) }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode

#
# Cloned VM provisioning function - executed by the Celery worker
#
def clone_vm(self, vm_name, vm_profile, source_volumes):
    pass

#
# Main VM provisioning function - executed by the Celery worker
#
def create_vm(self, vm_name, vm_profile, define_vm=True, start_vm=True):
    # Runtime imports
    import time
    import importlib
    import uuid
    import datetime
    import random

    time.sleep(2)

    print("Starting provisioning of VM '{}' with profile '{}'".format(vm_name, vm_profile))

    # Phase 0 - connect to databases
    try:
        db_conn, db_cur = open_database(config)
    except:
        print('FATAL - failed to connect to Postgres')
        raise Exception

    try:
        zk_conn = pvc_common.startZKConnection(config['coordinators'])
    except:
        print('FATAL - failed to connect to Zookeeper')
        raise Exception

    # Phase 1 - setup
    #  * Get the profile elements
    #  * Get the details from these elements
    #  * Assemble a VM configuration dictionary
    self.update_state(state='RUNNING', meta={'current': 1, 'total': 10, 'status': 'Collecting configuration'})
    time.sleep(1)
   
    vm_id = re.findall(r'/(\d+)$/', vm_name)
    if not vm_id:
        vm_id = 0
    else:
        vm_id = vm_id[0]
 
    vm_data = dict()

    # Get the profile information
    query = "SELECT * FROM profile WHERE name = %s"
    args = (vm_profile,)
    db_cur.execute(query, args)
    profile_data = db_cur.fetchone()
    if profile_data['arguments']:
        vm_data['script_arguments'] = profile_data['arguments'].split('|')
    else:
        vm_data['script_arguments'] = []
    
    # Get the system details
    query = 'SELECT * FROM system_template WHERE id = %s'
    args = (profile_data['system_template'],)
    db_cur.execute(query, args)
    vm_data['system_details'] = db_cur.fetchone()

    # Get the MAC template
    query = 'SELECT * FROM network_template WHERE id = %s'
    args = (profile_data['network_template'],)
    db_cur.execute(query, args)
    vm_data['mac_template'] = db_cur.fetchone()['mac_template']

    # Get the networks
    query = 'SELECT * FROM network WHERE network_template = %s'
    args = (profile_data['network_template'],)
    db_cur.execute(query, args)
    vm_data['networks'] = db_cur.fetchall()

    # Get the storage volumes
    # ORDER BY ensures disks are always in the sdX/vdX order, regardless of add order
    query = 'SELECT * FROM storage WHERE storage_template = %s ORDER BY disk_id'
    args = (profile_data['storage_template'],)
    db_cur.execute(query, args)
    vm_data['volumes'] = db_cur.fetchall()

    # Get the script
    query = 'SELECT * FROM script WHERE id = %s'
    args = (profile_data['script'],)
    db_cur.execute(query, args)
    vm_data['script'] = db_cur.fetchone()['script']

    if not vm_data['script']:
        # We do not have a script; skip it
        is_script_install = False
    else:
        is_script_install = True

  
    close_database(db_conn, db_cur)

    print("VM configuration data:\n{}".format(json.dumps(vm_data, sort_keys=True, indent=2)))

    # Phase 2 - verification
    #  * Ensure that at least one node has enough free RAM to hold the VM (becomes main host)
    #  * Ensure that all networks are valid
    #  * Ensure that there is enough disk space in the Ceph cluster for the disks
    # This is the "safe fail" step when an invalid configuration will be caught
    self.update_state(state='RUNNING', meta={'current': 2, 'total': 10, 'status': 'Verifying configuration against cluster'})
    time.sleep(1)

    # Verify that a VM with this name does not already exist
    if pvc_vm.searchClusterByName(zk_conn, vm_name):
        raise ClusterError("A VM with the name '{}' already exists in the cluster".format(vm_name))

    # Verify that at least one host has enough free RAM to run the VM
    _discard, nodes = pvc_node.get_list(zk_conn, None)
    target_node = None
    last_free = 0
    for node in nodes:
        # Skip the node if it is not ready to run VMs
        if node ['daemon_state'] != "run" or node['domain_state'] != "ready":
            continue
        # Skip the node if its free memory is less than the new VM's size, plus a 512MB buffer
        if node['memory']['free'] < (vm_data['system_details']['vram_mb'] + 512):
            continue
        # If this node has the most free, use it
        if node['memory']['free'] > last_free:
            last_free = node['memory']['free']
            target_node = node['name']
    # Raise if no node was found
    if not target_node:
        raise ClusterError("No ready cluster node contains at least {}+512 MB of free RAM".format(vm_data['system_details']['vram_mb']))

    print('Selecting target node "{}" with "{}" MB free RAM'.format(target_node, last_free))

    # Verify that all configured networks are present on the cluster
    cluster_networks, _discard = pvc_network.getClusterNetworkList(zk_conn)
    for network in vm_data['networks']:
        vni = str(network['vni'])
        if not vni in cluster_networks:
            raise ClusterError('The network VNI "{}" is not present on the cluster'.format(vni))

    print("All configured networks for VM are valid")

    # Verify that there is enough disk space free to provision all VM disks
    pools = dict()
    for volume in vm_data['volumes']:
        if volume['source_volume'] is not None:
            if not volume['pool'] in pools:
                volume_data, status = pvc_ceph.getVolumeInformation(zk_conn, volume['pool'], volume['source_volume'])
                pools[volume['pool']] = volume_data['disk_size_gb']
                if not status:
                    raise ClusterError('The source volume {}/{} could not be found'.format(volume['pool'], volume['source_volume']))
            else:
                volume_data, status = pvc_ceph.getVolumeInformation(zk_conn, volume['pool'], volume['source_volume'])
                pools[volume['pool']] += volume_data['disk_size_gb']
                if not status:
                    raise ClusterError('The source volume {}/{} could not be found'.format(volume['pool'], volume['source_volume']))
        else:
            if not volume['pool'] in pools:
                pools[volume['pool']] = volume['disk_size_gb']
            else:
                pools[volume['pool']] += volume['disk_size_gb']

    for pool in pools:
        pool_information = pvc_ceph.getPoolInformation(zk_conn, pool)
        if not pool_information:
            raise ClusterError('Pool "{}" is not present on the cluster'.format(pool))
        pool_free_space_gb = int(pool_information['stats']['free_bytes'] / 1024 / 1024 / 1024)
        pool_vm_usage_gb = int(pools[pool])

        if pool_vm_usage_gb >= pool_free_space_gb:
            raise ClusterError('Pool "{}" has only {} GB free and VM requires {} GB'.format(pool, pool_free_space_gb, pool_vm_usage_gb))

    print("There is enough space on cluster to store VM volumes")

    # Verify that every specified filesystem is valid
    used_filesystems = list()
    for volume in vm_data['volumes']:
        if volume['source_volume'] is not None:
            continue
        if volume['filesystem'] and volume['filesystem'] not in used_filesystems:
            used_filesystems.append(volume['filesystem'])

    for filesystem in used_filesystems:
        if filesystem == 'swap':
            retcode, stdout, stderr = pvc_common.run_os_command("which mkswap")
            if retcode:
                raise ProvisioningError("Failed to find binary for mkswap: {}".format(filesystem, stderr))
        else:
            retcode, stdout, stderr = pvc_common.run_os_command("which mkfs.{}".format(filesystem))
            if retcode:
                raise ProvisioningError("Failed to find binary for mkfs.{}: {}".format(filesystem, stderr))

    print("All selected filesystems are valid")

    # Phase 3 - provisioning script preparation
    #  * Import the provisioning script as a library with importlib
    #  * Ensure the required function(s) are present
    self.update_state(state='RUNNING', meta={'current': 3, 'total': 10, 'status': 'Preparing provisioning script'})
    time.sleep(1)

    if is_script_install:
        # Write the script out to a temporary file
        retcode, stdout, stderr = pvc_common.run_os_command("mktemp")
        if retcode:
            raise ProvisioningError("Failed to create a temporary file: {}".format(stderr))
        script_file = stdout.strip()
        with open(script_file, 'w') as fh:
            fh.write(vm_data['script'])
            fh.write('\n')

        # Import the script file
        loader = importlib.machinery.SourceFileLoader('installer_script', script_file)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        installer_script = importlib.util.module_from_spec(spec)
        loader.exec_module(installer_script)

        # Verify that the install() function is valid
        if not "install" in dir(installer_script):
            raise ProvisioningError("Specified script does not contain an install() function")

        print("Provisioning script imported successfully")

    # Phase 4 - configuration creation
    #  * Create the libvirt XML configuration
    self.update_state(state='RUNNING', meta={'current': 4, 'total': 10, 'status': 'Preparing Libvirt XML configuration'})
    time.sleep(1)

    print("Creating Libvirt configuration")

    # Get information about VM
    vm_uuid = uuid.uuid4()
    vm_description = "PVC provisioner @ {}, profile '{}'".format(datetime.datetime.now(), vm_profile)

    retcode, stdout, stderr = pvc_common.run_os_command("uname -m")
    system_architecture = stdout.strip()

    # Begin assembling libvirt schema
    vm_schema = ""

    vm_schema += libvirt_schema.libvirt_header.format(
        vm_name=vm_name,
        vm_uuid=vm_uuid,
        vm_description=vm_description,
        vm_memory=vm_data['system_details']['vram_mb'],
        vm_vcpus=vm_data['system_details']['vcpu_count'],
        vm_architecture=system_architecture
    )

    # Add network devices
    network_id = 0
    for network in vm_data['networks']:
        vni = network['vni']
        eth_bridge = "vmbr{}".format(vni)

        vm_id_hex = '{:x}'.format(int(vm_id % 16))
        net_id_hex = '{:x}'.format(int(network_id % 16))

        if vm_data['mac_template']:
            mac_prefix = '52:54:01'
            mactemplate = "{prefix}:ff:f6:{vmid}{netid}"
            macgen_template = vm_data['mac_template']
            eth_macaddr = macgen_template.format(
                prefix=mac_prefix,
                vmid=vm_id_hex,
                netid=net_id_hex,
            )
        else:
            mac_prefix = '52:54:00'
            random_octet_A = '{:x}'.format(random.randint(16,238))
            random_octet_B = '{:x}'.format(random.randint(16,238))
            random_octet_C = '{:x}'.format(random.randint(16,238))

            macgen_template = '{prefix}:{octetA}:{octetB}:{octetC}'
            eth_macaddr = macgen_template.format(
                prefix=mac_prefix,
                octetA=random_octet_A,
                octetB=random_octet_B,
                octetC=random_octet_C
            )

        vm_schema += libvirt_schema.devices_net_interface.format(
            eth_macaddr=eth_macaddr,
            eth_bridge=eth_bridge
        )

        network_id += 1

    # Add disk devices
    monitor_list = list()
    coordinator_names = config['storage_hosts']
    for coordinator in coordinator_names:
        monitor_list.append("{}.{}".format(coordinator, config['storage_domain']))

    ceph_storage_secret = config['ceph_storage_secret_uuid']

    for volume in vm_data['volumes']:
        vm_schema += libvirt_schema.devices_disk_header.format(
            ceph_storage_secret=ceph_storage_secret,
            disk_pool=volume['pool'],
            vm_name=vm_name,
            disk_id=volume['disk_id']
        )
        for monitor in monitor_list:
            vm_schema += libvirt_schema.devices_disk_coordinator.format(
                coordinator_name=monitor,
                coordinator_ceph_mon_port=config['ceph_monitor_port']
            )
        vm_schema += libvirt_schema.devices_disk_footer

    vm_schema += libvirt_schema.devices_vhostmd

    # Add default devices
    vm_schema += libvirt_schema.devices_default

    # Add serial device
    if vm_data['system_details']['serial']:
        vm_schema += libvirt_schema.devices_serial.format(
            vm_name=vm_name
        )

    # Add VNC device
    if vm_data['system_details']['vnc']:
        if vm_data['system_details']['vnc_bind']:
            vm_vnc_bind = vm_data['system_details']['vnc_bind']
        else:
            vm_vnc_bind = "127.0.0.1"

        vm_vncport = 5900
        vm_vnc_autoport = "yes"

        vm_schema += libvirt_schema.devices_vnc.format(
            vm_vncport=vm_vncport,
            vm_vnc_autoport=vm_vnc_autoport,
            vm_vnc_bind=vm_vnc_bind
        )

    # Add SCSI controller
    vm_schema += libvirt_schema.devices_scsi_controller

    # Add footer
    vm_schema += libvirt_schema.libvirt_footer

    print("Final VM schema:\n{}\n".format(vm_schema))
    
    # Phase 5 - definition
    #  * Create the VM in the PVC cluster
    self.update_state(state='RUNNING', meta={'current': 5, 'total': 10, 'status': 'Defining VM on the cluster'})
    time.sleep(1)

    if define_vm:
        print("Defining VM on cluster")
        node_limit = vm_data['system_details']['node_limit']
        if node_limit:
            node_limit = node_limit.split(',')
        node_selector = vm_data['system_details']['node_selector']
        node_autostart = vm_data['system_details']['node_autostart']
        retcode, retmsg = pvc_vm.define_vm(zk_conn, vm_schema.strip(), target_node, node_limit, node_selector, node_autostart, vm_profile, initial_state='provision')
        print(retmsg)
    else:
        print("Skipping VM definition")

    # Phase 6 - disk creation
    #  * Create each Ceph storage volume for the disks
    self.update_state(state='RUNNING', meta={'current': 6, 'total': 10, 'status': 'Creating storage volumes'})
    time.sleep(1)
    
    for volume in vm_data['volumes']:
        if volume['source_volume'] is not None:
            success, message = pvc_ceph.clone_volume(zk_conn, volume['pool'], "{}_{}".format(vm_name, volume['disk_id']), volume['source_volume'])
            print(message)
            if not success:
                raise ClusterError('Failed to clone volume "{}" to "{}"'.format(volume['source_volume'], volume['disk_id']))
        else:
            success, message = pvc_ceph.add_volume(zk_conn, volume['pool'], "{}_{}".format(vm_name, volume['disk_id']), "{}G".format(volume['disk_size_gb']))
            print(message)
            if not success:
                raise ClusterError('Failed to create volume "{}"'.format(volume['disk_id']))

    # Phase 7 - disk mapping
    #  * Map each volume to the local host in order
    #  * Format each volume with any specified filesystems
    #  * If any mountpoints are specified, create a temporary mount directory
    #  * Mount any volumes to their respective mountpoints
    self.update_state(state='RUNNING', meta={'current': 7, 'total': 10, 'status': 'Mapping, formatting, and mounting storage volumes locally'})
    time.sleep(1)

    for volume in vm_data['volumes']:
        if volume['source_volume'] is not None:
            continue

        if not volume['filesystem']:
            continue

        rbd_volume = "{}/{}_{}".format(volume['pool'], vm_name, volume['disk_id'])

        filesystem_args_list = list()
        for arg in volume['filesystem_args'].split():
            arg_entry, arg_data = arg.split('=')
            filesystem_args_list.append(arg_entry)
            filesystem_args_list.append(arg_data)
        filesystem_args = ' '.join(filesystem_args_list)

        # Map the RBD device
        retcode, stdout, stderr = pvc_common.run_os_command("rbd map {}".format(rbd_volume))
        if retcode:
            raise ProvisioningError('Failed to map volume "{}": {}'.format(rbd_volume, stderr))

        # Create the filesystem
        if volume['filesystem'] == 'swap':
            retcode, stdout, stderr = pvc_common.run_os_command("mkswap -f /dev/rbd/{}".format(rbd_volume))
            if retcode:
                raise ProvisioningError('Failed to create swap on "{}": {}'.format(rbd_volume, stderr))
        else:
            retcode, stdout, stderr = pvc_common.run_os_command("mkfs.{} {} /dev/rbd/{}".format(volume['filesystem'], filesystem_args, rbd_volume))
            if retcode:
                raise ProvisioningError('Failed to create {} filesystem on "{}": {}'.format(volume['filesystem'], rbd_volume, stderr))

        print("Created {} filesystem on {}:\n{}".format(volume['filesystem'], rbd_volume, stdout))

    if is_script_install:
        # Create temporary directory
        retcode, stdout, stderr = pvc_common.run_os_command("mktemp -d")
        if retcode:
            raise ProvisioningError("Failed to create a temporary directory: {}".format(stderr))
        temp_dir = stdout.strip()

        for volume in vm_data['volumes']:
            if volume['source_volume'] is not None:
                continue

            if not volume['mountpoint'] or volume['mountpoint'] == 'swap':
                continue

            mapped_rbd_volume = "/dev/rbd/{}/{}_{}".format(volume['pool'], vm_name, volume['disk_id'])
            mount_path = "{}{}".format(temp_dir, volume['mountpoint'])

            # Ensure the mount path exists (within the filesystems)
            retcode, stdout, stderr = pvc_common.run_os_command("mkdir -p {}".format(mount_path))
            if retcode:
                raise ProvisioningError('Failed to create mountpoint "{}": {}'.format(mount_path, stderr))

            # Mount filesystems to temporary directory
            retcode, stdout, stderr = pvc_common.run_os_command("mount {} {}".format(mapped_rbd_volume, mount_path))
            if retcode:
                raise ProvisioningError('Failed to mount "{}" on "{}": {}'.format(mapped_rbd_volume, mount_path, stderr))

            print("Successfully mounted {} on {}".format(mapped_rbd_volume, mount_path))

    # Phase 8 - provisioning script execution
    #  * Execute the provisioning script main function ("install") passing any custom arguments
    self.update_state(state='RUNNING', meta={'current': 8, 'total': 10, 'status': 'Executing provisioning script'})
    time.sleep(1)

    if is_script_install:
        print("Running installer script")

        # Parse the script arguments
        script_arguments = dict()
        for argument in vm_data['script_arguments']:
            argument_name, argument_data = argument.split('=')
            script_arguments[argument_name] = argument_data

        # Run the script
        try:
            installer_script.install(
                vm_name=vm_name,
                vm_id=vm_id,
                temporary_directory=temp_dir,
                disks=vm_data['volumes'],
                networks=vm_data['networks'],
                **script_arguments
            )
        except:
            pass

    # Phase 9 - install cleanup
    #  * Unmount any mounted volumes
    #  * Remove any temporary directories
    self.update_state(state='RUNNING', meta={'current': 9, 'total': 10, 'status': 'Cleaning up local mounts and directories'})
    time.sleep(1)

    for volume in list(reversed(vm_data['volumes'])):
        if volume['source_volume'] is not None:
            continue

        if is_script_install:
            # Unmount the volume
            if volume['mountpoint'] and volume['mountpoint'] != 'swap':
                print("Cleaning up mount {}{}".format(temp_dir, volume['mountpoint']))

                mount_path = "{}{}".format(temp_dir, volume['mountpoint'])
                retcode, stdout, stderr = pvc_common.run_os_command("umount {}".format(mount_path))
                if retcode:
                    raise ProvisioningError('Failed to unmount "{}": {}'.format(mount_path, stderr))

        # Unmap the RBD device
        if volume['filesystem']:
            print("Cleaning up RBD mapping /dev/rbd/{}/{}_{}".format(volume['pool'], vm_name, volume['disk_id']))

            rbd_volume = "/dev/rbd/{}/{}_{}".format(volume['pool'], vm_name, volume['disk_id'])
            retcode, stdout, stderr = pvc_common.run_os_command("rbd unmap {}".format(rbd_volume))
            if retcode:
                raise ProvisioningError('Failed to unmap volume "{}": {}'.format(rbd_volume, stderr))

    print("Cleaning up temporary directories and files")

    if is_script_install:
        # Remove temporary mount directory (don't fail if not removed)
        retcode, stdout, stderr = pvc_common.run_os_command("rmdir {}".format(temp_dir))
        if retcode:
            print('Failed to delete temporary directory "{}": {}'.format(temp_dir, stderr))

        # Remote temporary script (don't fail if not removed)
        retcode, stdout, stderr = pvc_common.run_os_command("rm -f {}".format(script_file))
        if retcode:
            print('Failed to delete temporary script file "{}": {}'.format(script_file, stderr))

    # Phase 10 - startup
    #  * Start the VM in the PVC cluster
    self.update_state(state='RUNNING', meta={'current': 10, 'total': 10, 'status': 'Starting VM'})
    time.sleep(1)

    if start_vm:
        retcode, retmsg = pvc_vm.start_vm(zk_conn, vm_name)
        print(retmsg)

    pvc_common.stopZKConnection(zk_conn)
    return {'status': 'VM "{}" with profile "{}" has been provisioned and started successfully'.format(vm_name, vm_profile), 'current': 10, 'total': 10}

