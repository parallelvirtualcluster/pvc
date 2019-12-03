#!/usr/bin/env python3

# pvcapi.py - PVC HTTP API functions
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

import flask
import json
import psycopg2
import psycopg2.extras
import os
import re

import client_lib.common as pvc_common
import client_lib.vm as pvc_vm
import client_lib.network as pvc_network
import client_lib.ceph as pvc_ceph

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
            query = "SELECT vni FROM network WHERE network_template = %s;"
            args = (template_data['id'],)
            cur.execute(query, args)
            vnis = cur.fetchall()
            data[template_id]['networks'] = vnis

    if table == 'storage_template':
        for template_id, template_data in enumerate(data):
            # Fetch list of VNIs from network table
            query = "SELECT * FROM storage WHERE storage_template = %s;"
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
    return data

def list_template_network(limit, is_fuzzy=True):
    """
    Obtain a list of network templates.
    """
    data = list_template(limit, 'network_template', is_fuzzy)
    return data

def list_template_network_vnis(name):
    """
    Obtain a list of network template VNIs.
    """
    data = list_template(name, 'network_template', is_fuzzy=False)[0]
    networks = data['networks']
    return networks

def list_template_storage(limit, is_fuzzy=True):
    """
    Obtain a list of storage templates.
    """
    data = list_template(limit, 'storage_template', is_fuzzy)
    return data

def list_template_storage_disks(name):
    """
    Obtain a list of storage template disks.
    """
    data = list_template(name, 'storage_template', is_fuzzy=False)[0]
    disks = data['disks']
    return disks

def template_list(limit):
    system_templates = list_template_system(limit)
    network_templates = list_template_network(limit)
    storage_templates = list_template_storage(limit)

    return { "system_templates": system_templates, "network_templates": network_templates, "storage_templates": storage_templates }

#
# Template Create functions
#
def create_template_system(name, vcpu_count, vram_mb, serial=False, vnc=False, vnc_bind=None):
    if list_template_system(name, is_fuzzy=False):
        retmsg = { "message": "The system template {} already exists".format(name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    query = "INSERT INTO system_template (name, vcpu_count, vram_mb, serial, vnc, vnc_bind) VALUES (%s, %s, %s, %s, %s, %s);"
    args = (name, vcpu_count, vram_mb, serial, vnc, vnc_bind)

    conn, cur = open_database(config)
    try:
        cur.execute(query, args)
        retmsg = { "name": name }
        retcode = 200
    except psycopg2.IntegrityError as e:
        retmsg = { "message": "Failed to create entry {}".format(name), "error": e }
        retcode = 400
    close_database(conn, cur)
    return flask.jsonify(retmsg), retcode

def create_template_network(name, mac_template=None):
    if list_template_network(name, is_fuzzy=False):
        retmsg = { "message": "The network template {} already exists".format(name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    conn, cur = open_database(config)
    try:
        query = "INSERT INTO network_template (name, mac_template) VALUES (%s, %s);"
        args = (name, mac_template)
        cur.execute(query, args)
        retmsg = { "name": name }
        retcode = 200
    except psycopg2.IntegrityError as e:
        retmsg = { "message": "Failed to create entry {}".format(name), "error": e }
        retcode = 400
    close_database(conn, cur)
    return flask.jsonify(retmsg), retcode

def create_template_network_element(name, network):
    if not list_template_network(name, is_fuzzy=False):
        retmsg = { "message": "The network template {} does not exist".format(name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    networks = list_template_network_vnis(name)
    found_vni = False
    for network in networks:
        if network['vni'] == vni:
            found_vni = True
    if found_vni:
        retmsg = { "message": "The VNI {} in network template {} already exists".format(vni, name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    conn, cur = open_database(config)
    try:
        query = "SELECT id FROM network_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        template_id = cur.fetchone()['id']
        query = "INSERT INTO network (network_template, vni) VALUES (%s, %s);"
        args = (template_id, network)
        cur.execute(query, args)
        retmsg = { "name": name, "vni": network }
        retcode = 200
    except psycopg2.IntegrityError as e:
        retmsg = { "message": "Failed to create entry {}".format(network), "error": e }
        retcode = 400
    close_database(conn, cur)
    return flask.jsonify(retmsg), retcode

def create_template_storage(name):
    if list_template_storage(name, is_fuzzy=False):
        retmsg = { "message": "The storage template {} already exists".format(name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    conn, cur = open_database(config)
    try:
        query = "INSERT INTO storage_template (name) VALUES (%s);"
        args = (name,)
        cur.execute(query, args)
        retmsg = { "name": name }
        retcode = 200
    except psycopg2.IntegrityError as e:
        retmsg = { "message": "Failed to create entry {}".format(name), "error": e }
        retcode = 400
    close_database(conn, cur)
    return flask.jsonify(retmsg), retcode

def create_template_storage_element(name, disk_id, disk_size_gb, mountpoint=None, filesystem=None):
    if not list_template_storage(name, is_fuzzy=False):
        retmsg = { "message": "The storage template {} does not exist".format(name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    disks = list_template_storage_disks(name)
    found_disk = False
    for disk in disks:
        if disk['disk_id'] == disk_id:
            found_disk = True
    if found_disk:
        retmsg = { "message": "The disk {} in storage template {} already exists".format(disk_id, name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    if mountpoint and not filesystem:
        retmsg = { "message": "A filesystem must be specified along with a mountpoint." }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    conn, cur = open_database(config)
    try:
        query = "SELECT id FROM storage_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        template_id = cur.fetchone()['id']
        query = "INSERT INTO storage (storage_template, disk_id, disk_size_gb, mountpoint, filesystem) VALUES (%s, %s, %s, %s, %s);"
        args = (template_id, disk_id, disk_size_gb, mountpoint, filesystem)
        cur.execute(query, args)
        retmsg = { "name": name, "disk_id": disk_id }
        retcode = 200
    except psycopg2.IntegrityError as e:
        retmsg = { "message": "Failed to create entry {}".format(disk_id), "error": e }
        retcode = 400
    close_database(conn, cur)
    return flask.jsonify(retmsg), retcode

def delete_template_system(name):
    if not list_template_system(name, is_fuzzy=False):
        retmsg = { "message": "The system template {} does not exist".format(name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    conn, cur = open_database(config)
    try:
        query = "DELETE FROM system_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        retmsg = { "name": name }
        retcode = 200
    except psycopg2.IntegrityError as e:
        retmsg = { "message": "Failed to delete entry {}".format(name), "error": e }
        retcode = 400
    close_database(conn, cur)
    return flask.jsonify(retmsg), retcode

def delete_template_network(name):
    if not list_template_network(name, is_fuzzy=False):
        retmsg = { "message": "The network template {} does not exist".format(name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

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
        retmsg = { "name": name }
        retcode = 200
    except psycopg2.IntegrityError as e:
        retmsg = { "message": "Failed to delete entry {}".format(name), "error": e }
        retcode = 400
    close_database(conn, cur)
    return flask.jsonify(retmsg), retcode

def delete_template_network_element(name, vni):
    if not list_template_network(name, is_fuzzy=False):
        retmsg = { "message": "The network template {} does not exist".format(name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    networks = list_template_network_vnis(name)
    found_vni = False
    for network in networks:
        if network['vni'] == vni:
            found_vni = True
    if not found_vni:
        retmsg = { "message": "The VNI {} in network template {} does not exist".format(vni, name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    conn, cur = open_database(config)
    try:
        query = "SELECT id FROM network_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        template_id = cur.fetchone()['id']
        query = "DELETE FROM network WHERE network_template = %s and vni = %s;"
        args = (template_id, vni)
        cur.execute(query, args)
        retmsg = { "name": name, "vni": vni }
        retcode = 200
    except psycopg2.IntegrityError as e:
        retmsg = { "message": "Failed to delete entry {}".format(name), "error": e }
        retcode = 400
    close_database(conn, cur)
    return flask.jsonify(retmsg), retcode

def delete_template_storage(name):
    if not list_template_storage(name, is_fuzzy=False):
        retmsg = { "message": "The storage template {} does not exist".format(name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

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
        retmsg = { "name": name }
        retcode = 200
    except psycopg2.IntegrityError as e:
        retmsg = { "message": "Failed to delete entry {}".format(name), "error": e }
        retcode = 400
    close_database(conn, cur)
    return flask.jsonify(retmsg), retcode

def delete_template_storage_element(name, disk_id):
    if not list_template_storage(name, is_fuzzy=False):
        retmsg = { "message": "The storage template {} does not exist".format(name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    disks = list_template_storage_disks(name)
    found_disk = False
    for disk in disks:
        if disk['disk_id'] == disk_id:
            found_disk = True
    if not found_disk:
        retmsg = { "message": "The disk {} in storage template {} does not exist".format(disk_id, name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    conn, cur = open_database(config)
    try:
        query = "SELECT id FROM storage_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        template_id = cur.fetchone()['id']
        query = "DELETE FROM storage WHERE storage_template = %s and disk_id = %s;"
        args = (template_id, disk_id)
        cur.execute(query, args)
        retmsg = { "name": name, "disk_id": disk_id }
        retcode = 200
    except psycopg2.IntegrityError as e:
        retmsg = { "message": "Failed to delete entry {}".format(name), "error": e }
        retcode = 400
    close_database(conn, cur)
    return flask.jsonify(retmsg), retcode

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
    return data

def create_script(name, script):
    if list_script(name, is_fuzzy=False):
        retmsg = { "message": "The script {} already exists".format(name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    conn, cur = open_database(config)
    try:
        query = "INSERT INTO script (name, script) VALUES (%s, %s);"
        args = (name, script)
        cur.execute(query, args)
        retmsg = { "name": name }
        retcode = 200
    except psycopg2.IntegrityError as e:
        retmsg = { "message": "Failed to create entry {}".format(name), "error": e }
        retcode = 400
    close_database(conn, cur)
    return flask.jsonify(retmsg), retcode

def delete_script(name):
    if not list_script(name, is_fuzzy=False):
        retmsg = { "message": "The script {} does not exist".format(name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    conn, cur = open_database(config)
    try:
        query = "DELETE FROM script WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        retmsg = { "name": name }
        retcode = 200
    except psycopg2.IntegrityError as e:
        retmsg = { "message": "Failed to delete entry {}".format(name), "error": e }
        retcode = 400
    close_database(conn, cur)
    return flask.jsonify(retmsg), retcode

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
        profile_data['name'] = profile['name']
        for etype in 'system_template', 'network_template', 'storage_template', 'script':
            query = 'SELECT name from {} WHERE id = %s'.format(etype)
            args = (profile[etype],)
            cur.execute(query, args)
            name = cur.fetchone()['name']
            profile_data[etype] = name
        data.append(profile_data)
    close_database(conn, cur)
    return data

def create_profile(name, system_template, network_template, storage_template, script):
    if list_profile(name, is_fuzzy=False):
        retmsg = { "message": "The profile {} already exists".format(name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    system_templates = list_template_system(None)
    system_template_id = None
    for template in system_templates:
        if template['name'] == system_template:
            system_template_id = template['id']
    if not system_template_id:
        retmsg = { "message": "The system template {} for profile {} does not exist".format(system_template, name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    network_templates = list_template_network(None)
    network_template_id = None
    for template in network_templates:
        if template['name'] == network_template:
            network_template_id = template['id']
    if not network_template_id:
        retmsg = { "message": "The network template {} for profile {} does not exist".format(network_template, name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    storage_templates = list_template_storage(None)
    storage_template_id = None
    for template in storage_templates:
        if template['name'] == storage_template:
            storage_template_id = template['id']
    if not storage_template_id:
        retmsg = { "message": "The storage template {} for profile {} does not exist".format(storage_template, name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    scripts = list_script(None)
    script_id = None
    for scr in scripts:
        if scr['name'] == script:
            script_id = scr['id']
    if not script_id:
        retmsg = { "message": "The script {} for profile {} does not exist".format(script, name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    conn, cur = open_database(config)
    try:
        query = "INSERT INTO profile (name, system_template, network_template, storage_template, script) VALUES (%s, %s, %s, %s, %s);"
        args = (name, system_template_id, network_template_id, storage_template_id, script_id)
        cur.execute(query, args)
        retmsg = { "name": name }
        retcode = 200
    except psycopg2.IntegrityError as e:
        retmsg = { "message": "Failed to create entry {}".format(name), "error": e }
        retcode = 400
    close_database(conn, cur)
    return flask.jsonify(retmsg), retcode

def delete_profile(name):
    if not list_profile(name, is_fuzzy=False):
        retmsg = { "message": "The profile {} does not exist".format(name) }
        retcode = 400
        return flask.jsonify(retmsg), retcode

    conn, cur = open_database(config)
    try:
        query = "DELETE FROM profile WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        retmsg = { "name": name }
        retcode = 200
    except psycopg2.IntegrityError as e:
        retmsg = { "message": "Failed to delete entry {}".format(name), "error": e }
        retcode = 400
    close_database(conn, cur)
    return flask.jsonify(retmsg), retcode

#
# Job functions
#
def create_vm(vm_name, profile_name):
    pass


