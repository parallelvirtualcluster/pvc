#!/usr/bin/env python3

# provisioner.py - PVC API Provisioner functions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2024 Joshua M. Boniface <joshua@boniface.me>
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

import psycopg2
import psycopg2.extras
import re

from pvcapid.Daemon import config, strtobool

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
        host=config["api_postgresql_host"],
        port=config["api_postgresql_port"],
        dbname=config["api_postgresql_dbname"],
        user=config["api_postgresql_user"],
        password=config["api_postgresql_password"],
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
            if not re.match(r"\^.*", limit):
                limit = "%" + limit
            else:
                limit = limit[1:]
            if not re.match(r".*\$", limit):
                limit = limit + "%"
            else:
                limit = limit[:-1]

        args = (limit,)
        query = "SELECT * FROM {} WHERE name LIKE %s;".format(table)
    else:
        args = ()
        query = "SELECT * FROM {};".format(table)

    conn, cur = open_database(config)
    cur.execute(query, args)
    data = cur.fetchall()

    if not isinstance(data, list):
        data = [data]

    if table == "network_template":
        for template_id, template_data in enumerate(data):
            # Fetch list of VNIs from network table
            query = "SELECT * FROM network WHERE network_template = %s;"
            args = (template_data["id"],)
            cur.execute(query, args)
            vnis = cur.fetchall()
            data[template_id]["networks"] = vnis

    if table == "storage_template":
        for template_id, template_data in enumerate(data):
            # Fetch list of VNIs from network table
            query = "SELECT * FROM storage WHERE storage_template = %s"
            args = (template_data["id"],)
            cur.execute(query, args)
            disks = cur.fetchall()
            data[template_id]["disks"] = disks

    close_database(conn, cur)

    return data


def list_template_system(limit, is_fuzzy=True):
    """
    Obtain a list of system templates.
    """
    data = list_template(limit, "system_template", is_fuzzy)
    if data:
        return data, 200
    else:
        return {"message": "No system templates found."}, 404


def list_template_network(limit, is_fuzzy=True):
    """
    Obtain a list of network templates.
    """
    data = list_template(limit, "network_template", is_fuzzy)
    if data:
        return data, 200
    else:
        return {"message": "No network templates found."}, 404


def list_template_network_vnis(name):
    """
    Obtain a list of network template VNIs.
    """
    data = list_template(name, "network_template", is_fuzzy=False)[0]
    networks = data["networks"]
    if networks:
        return networks, 200
    else:
        return {"message": "No network template networks found."}, 404


def list_template_storage(limit, is_fuzzy=True):
    """
    Obtain a list of storage templates.
    """
    data = list_template(limit, "storage_template", is_fuzzy)
    if data:
        return data, 200
    else:
        return {"message": "No storage templates found."}, 404


def list_template_storage_disks(name):
    """
    Obtain a list of storage template disks.
    """
    data = list_template(name, "storage_template", is_fuzzy=False)[0]
    disks = data["disks"]
    if disks:
        return disks, 200
    else:
        return {"message": "No storage template disks found."}, 404


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

    return {
        "system_templates": system_templates,
        "network_templates": network_templates,
        "storage_templates": storage_templates,
    }


#
# Template Create functions
#
def create_template_system(
    name,
    vcpu_count,
    vram_mb,
    serial=False,
    vnc=False,
    vnc_bind=None,
    node_limit=None,
    node_selector=None,
    node_autostart=False,
    migration_method=None,
    migration_max_downtime=None,
    ova=None,
):
    if list_template_system(name, is_fuzzy=False)[-1] != 404:
        retmsg = {"message": 'The system template "{}" already exists.'.format(name)}
        retcode = 400
        return retmsg, retcode

    if node_selector == "none":
        node_selector = None

    query = "INSERT INTO system_template (name, vcpu_count, vram_mb, serial, vnc, vnc_bind, node_limit, node_selector, node_autostart, migration_method, migration_max_downtime, ova) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);"
    args = (
        name,
        vcpu_count,
        vram_mb,
        serial,
        vnc,
        vnc_bind,
        node_limit,
        node_selector,
        node_autostart,
        migration_method,
        migration_max_downtime,
        ova,
    )

    conn, cur = open_database(config)
    try:
        cur.execute(query, args)
        retmsg = {"message": 'Added new system template "{}".'.format(name)}
        retcode = 200
    except Exception as e:
        retmsg = {
            "message": 'Failed to create system template "{}": {}'.format(name, e)
        }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode


def create_template_network(name, mac_template=None):
    if list_template_network(name, is_fuzzy=False)[-1] != 404:
        retmsg = {"message": 'The network template "{}" already exists.'.format(name)}
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "INSERT INTO network_template (name, mac_template) VALUES (%s, %s);"
        args = (name, mac_template)
        cur.execute(query, args)
        retmsg = {"message": 'Added new network template "{}".'.format(name)}
        retcode = 200
    except Exception as e:
        retmsg = {
            "message": 'Failed to create network template "{}": {}'.format(name, e)
        }
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode


def create_template_network_element(name, vni):
    if list_template_network(name, is_fuzzy=False)[-1] != 200:
        retmsg = {"message": 'The network template "{}" does not exist.'.format(name)}
        retcode = 400
        return retmsg, retcode

    networks, code = list_template_network_vnis(name)
    if code != 200:
        networks = []
    found_vni = False
    for network in networks:
        if network["vni"] == vni:
            found_vni = True
    if found_vni:
        retmsg = {
            "message": 'The VNI "{}" in network template "{}" already exists.'.format(
                vni, name
            )
        }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "SELECT id FROM network_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        template_id = cur.fetchone()["id"]
        query = "INSERT INTO network (network_template, vni) VALUES (%s, %s);"
        args = (template_id, vni)
        cur.execute(query, args)
        retmsg = {
            "message": 'Added new network "{}" to network template "{}".'.format(
                vni, name
            )
        }
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to create entry "{}": {}'.format(vni, e)}
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode


def create_template_storage(name):
    if list_template_storage(name, is_fuzzy=False)[-1] != 404:
        retmsg = {"message": 'The storage template "{}" already exists.'.format(name)}
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "INSERT INTO storage_template (name) VALUES (%s);"
        args = (name,)
        cur.execute(query, args)
        retmsg = {"message": 'Added new storage template "{}".'.format(name)}
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to create entry "{}": {}'.format(name, e)}
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode


def create_template_storage_element(
    name,
    disk_id,
    pool,
    source_volume=None,
    disk_size_gb=None,
    filesystem=None,
    filesystem_args=[],
    mountpoint=None,
):
    if list_template_storage(name, is_fuzzy=False)[-1] != 200:
        retmsg = {"message": 'The storage template "{}" does not exist.'.format(name)}
        retcode = 400
        return retmsg, retcode

    disks, code = list_template_storage_disks(name)
    if code != 200:
        disks = []
    found_disk = False
    for disk in disks:
        if disk["disk_id"] == disk_id:
            found_disk = True
    if found_disk:
        retmsg = {
            "message": 'The disk "{}" in storage template "{}" already exists.'.format(
                disk_id, name
            )
        }
        retcode = 400
        return retmsg, retcode

    if mountpoint and not filesystem:
        retmsg = {"message": "A filesystem must be specified along with a mountpoint."}
        retcode = 400
        return retmsg, retcode

    if source_volume and (disk_size_gb or filesystem or mountpoint):
        retmsg = {
            "message": "Clone volumes are not compatible with disk size, filesystem, or mountpoint specifications."
        }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "SELECT id FROM storage_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        template_id = cur.fetchone()["id"]
        query = "INSERT INTO storage (storage_template, pool, disk_id, source_volume, disk_size_gb, mountpoint, filesystem, filesystem_args) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);"
        if filesystem_args:
            fsargs = " ".join(filesystem_args)
        else:
            fsargs = ""
        args = (
            template_id,
            pool,
            disk_id,
            source_volume,
            disk_size_gb,
            mountpoint,
            filesystem,
            fsargs,
        )
        cur.execute(query, args)
        retmsg = {
            "message": 'Added new disk "{}" to storage template "{}".'.format(
                disk_id, name
            )
        }
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to create entry "{}": {}'.format(disk_id, e)}
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode


#
# Template Modify functions
#
def modify_template_system(
    name,
    vcpu_count=None,
    vram_mb=None,
    serial=None,
    vnc=None,
    vnc_bind=None,
    node_limit=None,
    node_selector=None,
    node_autostart=None,
    migration_method=None,
    migration_max_downtime=None,
):
    if list_template_system(name, is_fuzzy=False)[-1] != 200:
        retmsg = {"message": 'The system template "{}" does not exist.'.format(name)}
        retcode = 404
        return retmsg, retcode

    fields = []

    if vcpu_count is not None:
        try:
            vcpu_count = int(vcpu_count)
        except Exception:
            retmsg = {"message": "The vcpus value must be an integer."}
            retcode = 400
            return retmsg, retcode
        fields.append({"field": "vcpu_count", "data": vcpu_count})

    if vram_mb is not None:
        try:
            vram_mb = int(vram_mb)
        except Exception:
            retmsg = {"message": "The vram value must be an integer."}
            retcode = 400
            return retmsg, retcode
        fields.append({"field": "vram_mb", "data": vram_mb})

    if serial is not None:
        try:
            serial = bool(strtobool(serial))
        except Exception:
            retmsg = {"message": "The serial value must be a boolean."}
            retcode = 400
            return retmsg, retcode
        fields.append({"field": "serial", "data": serial})

    if vnc is not None:
        try:
            vnc = bool(strtobool(vnc))
        except Exception:
            retmsg = {"message": "The vnc value must be a boolean."}
            retcode = 400
            return retmsg, retcode
        fields.append({"field": "vnc", "data": vnc})

    if vnc_bind is not None:
        fields.append({"field": "vnc_bind", "data": vnc_bind})

    if node_limit is not None:
        fields.append({"field": "node_limit", "data": node_limit})

    if node_selector is not None:
        if node_selector == "none":
            node_selector = "None"

        fields.append({"field": "node_selector", "data": node_selector})

    if node_autostart is not None:
        try:
            node_autostart = bool(strtobool(node_autostart))
        except Exception:
            retmsg = {"message": "The node_autostart value must be a boolean."}
            retcode = 400
        fields.append({"field": "node_autostart", "data": node_autostart})

    if migration_method is not None:
        fields.append({"field": "migration_method", "data": migration_method})

    if migration_max_downtime is not None:
        fields.append(
            {"field": "migration_max_downtime", "data": int(migration_max_downtime)}
        )

    conn, cur = open_database(config)
    try:
        for field in fields:
            query = "UPDATE system_template SET {} = %s WHERE name = %s;".format(
                field.get("field")
            )
            args = (field.get("data"), name)
            cur.execute(query, args)
        retmsg = {"message": 'Modified system template "{}".'.format(name)}
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to modify entry "{}": {}'.format(name, e)}
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode


#
# Template Delete functions
#
def delete_template_system(name):
    if list_template_system(name, is_fuzzy=False)[-1] != 200:
        retmsg = {"message": 'The system template "{}" does not exist.'.format(name)}
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "DELETE FROM system_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        retmsg = {"message": 'Removed system template "{}".'.format(name)}
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to delete entry "{}": {}'.format(name, e)}
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode


def delete_template_network(name):
    if list_template_network(name, is_fuzzy=False)[-1] != 200:
        retmsg = {"message": 'The network template "{}" does not exist.'.format(name)}
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "SELECT id FROM network_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        template_id = cur.fetchone()["id"]
        query = "DELETE FROM network WHERE network_template = %s;"
        args = (template_id,)
        cur.execute(query, args)
        query = "DELETE FROM network_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        retmsg = {"message": 'Removed network template "{}".'.format(name)}
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to delete entry "{}": {}'.format(name, e)}
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode


def delete_template_network_element(name, vni):
    if list_template_network(name, is_fuzzy=False)[-1] != 200:
        retmsg = {"message": 'The network template "{}" does not exist.'.format(name)}
        retcode = 400
        return retmsg, retcode

    networks, code = list_template_network_vnis(name)
    found_vni = False
    for network in networks:
        if network["vni"] == vni:
            found_vni = True
    if not found_vni:
        retmsg = {
            "message": 'The VNI "{}" in network template "{}" does not exist.'.format(
                vni, name
            )
        }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "SELECT id FROM network_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        template_id = cur.fetchone()["id"]
        query = "DELETE FROM network WHERE network_template = %s and vni = %s;"
        args = (template_id, vni)
        cur.execute(query, args)
        retmsg = {
            "message": 'Removed network "{}" from network template "{}".'.format(
                vni, name
            )
        }
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to delete entry "{}": {}'.format(name, e)}
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode


def delete_template_storage(name):
    if list_template_storage(name, is_fuzzy=False)[-1] != 200:
        retmsg = {"message": 'The storage template "{}" does not exist.'.format(name)}
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "SELECT id FROM storage_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        template_id = cur.fetchone()["id"]
        query = "DELETE FROM storage WHERE storage_template = %s;"
        args = (template_id,)
        cur.execute(query, args)
        query = "DELETE FROM storage_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        retmsg = {"message": 'Removed storage template "{}".'.format(name)}
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to delete entry "{}": {}'.format(name, e)}
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode


def delete_template_storage_element(name, disk_id):
    if list_template_storage(name, is_fuzzy=False)[-1] != 200:
        retmsg = {"message": 'The storage template "{}" does not exist.'.format(name)}
        retcode = 400
        return retmsg, retcode

    disks, code = list_template_storage_disks(name)
    found_disk = False
    for disk in disks:
        if disk["disk_id"] == disk_id:
            found_disk = True
    if not found_disk:
        retmsg = {
            "message": 'The disk "{}" in storage template "{}" does not exist.'.format(
                disk_id, name
            )
        }
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "SELECT id FROM storage_template WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        template_id = cur.fetchone()["id"]
        query = "DELETE FROM storage WHERE storage_template = %s and disk_id = %s;"
        args = (template_id, disk_id)
        cur.execute(query, args)
        retmsg = {
            "message": 'Removed disk "{}" from storage template "{}".'.format(
                disk_id, name
            )
        }
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to delete entry "{}": {}'.format(name, e)}
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
            if not re.match(r"\^.*", limit):
                limit = "%" + limit
            else:
                limit = limit[1:]
            if not re.match(r".*\$", limit):
                limit = limit + "%"
            else:
                limit = limit[:-1]

        query = "SELECT * FROM {} WHERE name LIKE %s;".format("userdata")
        args = (limit,)
    else:
        query = "SELECT * FROM {};".format("userdata")
        args = ()

    conn, cur = open_database(config)
    cur.execute(query, args)
    data = cur.fetchall()
    close_database(conn, cur)
    if data:
        return data, 200
    else:
        return {"message": "No userdata documents found."}, 404


def create_userdata(name, userdata):
    if list_userdata(name, is_fuzzy=False)[-1] != 404:
        retmsg = {"message": 'The userdata document "{}" already exists.'.format(name)}
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "INSERT INTO userdata (name, userdata) VALUES (%s, %s);"
        args = (name, userdata)
        cur.execute(query, args)
        retmsg = {"message": 'Created userdata document "{}".'.format(name)}
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to create entry "{}": {}'.format(name, e)}
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode


def update_userdata(name, userdata):
    if list_userdata(name, is_fuzzy=False)[-1] != 200:
        retmsg = {"message": 'The userdata "{}" does not exist.'.format(name)}
        retcode = 400
        return retmsg, retcode

    data, code = list_userdata(name, is_fuzzy=False)
    tid = data[0]["id"]

    conn, cur = open_database(config)
    try:
        query = "UPDATE userdata SET userdata = %s WHERE id = %s;"
        args = (userdata, tid)
        cur.execute(query, args)
        retmsg = {"message": 'Updated userdata document "{}".'.format(name)}
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to update entry "{}": {}'.format(name, e)}
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode


def delete_userdata(name):
    if list_userdata(name, is_fuzzy=False)[-1] != 200:
        retmsg = {"message": 'The userdata "{}" does not exist.'.format(name)}
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "DELETE FROM userdata WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        retmsg = {"message": 'Removed userdata document "{}".'.format(name)}
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to delete entry "{}": {}'.format(name, e)}
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
            if not re.match(r"\^.*", limit):
                limit = "%" + limit
            else:
                limit = limit[1:]
            if not re.match(r".*\$", limit):
                limit = limit + "%"
            else:
                limit = limit[:-1]

        query = "SELECT * FROM {} WHERE name LIKE %s;".format("script")
        args = (limit,)
    else:
        query = "SELECT * FROM {};".format("script")
        args = ()

    conn, cur = open_database(config)
    cur.execute(query, args)
    data = cur.fetchall()
    close_database(conn, cur)
    if data:
        return data, 200
    else:
        return {"message": "No scripts found."}, 404


def create_script(name, script):
    if list_script(name, is_fuzzy=False)[-1] != 404:
        retmsg = {"message": 'The script "{}" already exists.'.format(name)}
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "INSERT INTO script (name, script) VALUES (%s, %s);"
        args = (name, script)
        cur.execute(query, args)
        retmsg = {"message": 'Created provisioning script "{}".'.format(name)}
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to create entry "{}": {}'.format(name, e)}
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode


def update_script(name, script):
    if list_script(name, is_fuzzy=False)[-1] != 200:
        retmsg = {"message": 'The script "{}" does not exist.'.format(name)}
        retcode = 400
        return retmsg, retcode

    data, code = list_script(name, is_fuzzy=False)
    tid = data[0]["id"]

    conn, cur = open_database(config)
    try:
        query = "UPDATE script SET script = %s WHERE id = %s;"
        args = (script, tid)
        cur.execute(query, args)
        retmsg = {"message": 'Updated provisioning script "{}".'.format(name)}
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to update entry "{}": {}'.format(name, e)}
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode


def delete_script(name):
    if list_script(name, is_fuzzy=False)[-1] != 200:
        retmsg = {"message": 'The script "{}" does not exist.'.format(name)}
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "DELETE FROM script WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        retmsg = {"message": 'Removed provisioning script "{}".'.format(name)}
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to delete entry "{}": {}'.format(name, e)}
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
            if not re.match(r"\^.*", limit):
                limit = "%" + limit
            else:
                limit = limit[1:]
            if not re.match(r".*\$", limit):
                limit = limit + "%"
            else:
                limit = limit[:-1]

        query = "SELECT * FROM {} WHERE name LIKE %s;".format("profile")
        args = (limit,)
    else:
        query = "SELECT * FROM {};".format("profile")
        args = ()

    conn, cur = open_database(config)
    cur.execute(query, args)
    orig_data = cur.fetchall()
    data = list()
    for profile in orig_data:
        profile_data = dict()
        profile_data["id"] = profile["id"]
        profile_data["name"] = profile["name"]
        profile_data["type"] = profile["profile_type"]
        # Parse the name of each subelement
        for etype in (
            "system_template",
            "network_template",
            "storage_template",
            "userdata",
            "script",
            "ova",
        ):
            query = "SELECT name from {} WHERE id = %s".format(etype)
            args = (profile[etype],)
            cur.execute(query, args)
            try:
                name = cur.fetchone()["name"]
            except Exception:
                name = "N/A"
            profile_data[etype] = name
        # Split the arguments back into a list
        profile_data["arguments"] = profile["arguments"].split("|")
        # Append the new data to our actual output structure
        data.append(profile_data)
    close_database(conn, cur)
    if data:
        return data, 200
    else:
        return {"message": "No profiles found."}, 404


def create_profile(
    name,
    profile_type,
    system_template,
    network_template,
    storage_template,
    userdata=None,
    script=None,
    ova=None,
    arguments=None,
):
    if list_profile(name, is_fuzzy=False)[-1] != 404:
        retmsg = {"message": 'The profile "{}" already exists.'.format(name)}
        retcode = 400
        return retmsg, retcode

    if profile_type not in ["provisioner", "ova"]:
        retmsg = {
            "message": "A valid profile type (provisioner, ova) must be specified."
        }
        retcode = 400
        return retmsg, retcode

    system_templates, code = list_template_system(None)
    system_template_id = None
    if code != 200:
        system_templates = []
    for template in system_templates:
        if template["name"] == system_template:
            system_template_id = template["id"]
    if not system_template_id:
        retmsg = {
            "message": 'The system template "{}" for profile "{}" does not exist.'.format(
                system_template, name
            )
        }
        retcode = 400
        return retmsg, retcode

    network_templates, code = list_template_network(None)
    network_template_id = None
    if code != 200:
        network_templates = []
    for template in network_templates:
        if template["name"] == network_template:
            network_template_id = template["id"]
    if not network_template_id and profile_type != "ova":
        retmsg = {
            "message": 'The network template "{}" for profile "{}" does not exist.'.format(
                network_template, name
            )
        }
        retcode = 400
        return retmsg, retcode

    storage_templates, code = list_template_storage(None)
    storage_template_id = None
    if code != 200:
        storage_templates = []
    for template in storage_templates:
        if template["name"] == storage_template:
            storage_template_id = template["id"]
    if not storage_template_id and profile_type != "ova":
        retmsg = {
            "message": 'The storage template "{}" for profile "{}" does not exist.'.format(
                storage_template, name
            )
        }
        retcode = 400
        return retmsg, retcode

    userdatas, code = list_userdata(None)
    userdata_id = None
    if code != 200:
        userdatas = []
    for template in userdatas:
        if template["name"] == userdata:
            userdata_id = template["id"]

    scripts, code = list_script(None)
    script_id = None
    if code != 200:
        scripts = []
    for scr in scripts:
        if scr["name"] == script:
            script_id = scr["id"]

    ovas, code = list_ova(None)
    ova_id = None
    if code != 200:
        ovas = []
    for ov in ovas:
        if ov["name"] == ova:
            ova_id = ov["id"]

    if arguments is not None and isinstance(arguments, list):
        arguments_formatted = "|".join(arguments)
    else:
        arguments_formatted = ""

    conn, cur = open_database(config)
    try:
        query = "INSERT INTO profile (name, profile_type, system_template, network_template, storage_template, userdata, script, ova, arguments) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);"
        args = (
            name,
            profile_type,
            system_template_id,
            network_template_id,
            storage_template_id,
            userdata_id,
            script_id,
            ova_id,
            arguments_formatted,
        )
        cur.execute(query, args)
        retmsg = {"message": 'Created VM profile "{}".'.format(name)}
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to create entry "{}": {}'.format(name, e)}
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode


def modify_profile(
    name,
    profile_type,
    system_template,
    network_template,
    storage_template,
    userdata,
    script,
    ova,
    arguments=None,
):
    if list_profile(name, is_fuzzy=False)[-1] != 200:
        retmsg = {"message": 'The profile "{}" does not exist.'.format(name)}
        retcode = 400
        return retmsg, retcode

    fields = []

    if profile_type is not None:
        if profile_type not in ["provisioner", "ova"]:
            retmsg = {
                "message": "A valid profile type (provisioner, ova) must be specified."
            }
            retcode = 400
            return retmsg, retcode
        fields.append({"field": "type", "data": profile_type})

    if system_template is not None:
        system_templates, code = list_template_system(None)
        system_template_id = None
        for template in system_templates:
            if template["name"] == system_template:
                system_template_id = template["id"]
        if not system_template_id:
            retmsg = {
                "message": 'The system template "{}" for profile "{}" does not exist.'.format(
                    system_template, name
                )
            }
            retcode = 400
            return retmsg, retcode
        fields.append({"field": "system_template", "data": system_template_id})

    if network_template is not None:
        network_templates, code = list_template_network(None)
        network_template_id = None
        for template in network_templates:
            if template["name"] == network_template:
                network_template_id = template["id"]
        if not network_template_id:
            retmsg = {
                "message": 'The network template "{}" for profile "{}" does not exist.'.format(
                    network_template, name
                )
            }
            retcode = 400
            return retmsg, retcode
        fields.append({"field": "network_template", "data": network_template_id})

    if storage_template is not None:
        storage_templates, code = list_template_storage(None)
        storage_template_id = None
        for template in storage_templates:
            if template["name"] == storage_template:
                storage_template_id = template["id"]
        if not storage_template_id:
            retmsg = {
                "message": 'The storage template "{}" for profile "{}" does not exist.'.format(
                    storage_template, name
                )
            }
            retcode = 400
            return retmsg, retcode
        fields.append({"field": "storage_template", "data": storage_template_id})

    if userdata is not None:
        userdatas, code = list_userdata(None)
        userdata_id = None
        for template in userdatas:
            if template["name"] == userdata:
                userdata_id = template["id"]
        if not userdata_id:
            retmsg = {
                "message": 'The userdata template "{}" for profile "{}" does not exist.'.format(
                    userdata, name
                )
            }
            retcode = 400
            return retmsg, retcode
        fields.append({"field": "userdata", "data": userdata_id})

    if script is not None:
        scripts, code = list_script(None)
        script_id = None
        for scr in scripts:
            if scr["name"] == script:
                script_id = scr["id"]
        if not script_id:
            retmsg = {
                "message": 'The script "{}" for profile "{}" does not exist.'.format(
                    script, name
                )
            }
            retcode = 400
            return retmsg, retcode
        fields.append({"field": "script", "data": script_id})

    if ova is not None:
        ovas, code = list_ova(None)
        ova_id = None
        for ov in ovas:
            if ov["name"] == ova:
                ova_id = ov["id"]
        if not ova_id:
            retmsg = {
                "message": 'The OVA "{}" for profile "{}" does not exist.'.format(
                    ova, name
                )
            }
            retcode = 400
            return retmsg, retcode
        fields.append({"field": "ova", "data": ova_id})

    if arguments is not None:
        if isinstance(arguments, list):
            arguments_formatted = "|".join(arguments)
        else:
            arguments_formatted = ""
        fields.append({"field": "arguments", "data": arguments_formatted})

    conn, cur = open_database(config)
    try:
        for field in fields:
            query = "UPDATE profile SET {}=%s WHERE name=%s;".format(field.get("field"))
            args = (field.get("data"), name)
            cur.execute(query, args)
        retmsg = {"message": 'Modified VM profile "{}".'.format(name)}
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to modify entry "{}": {}'.format(name, e)}
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode


def delete_profile(name):
    if list_profile(name, is_fuzzy=False)[-1] != 200:
        retmsg = {"message": 'The profile "{}" does not exist.'.format(name)}
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    try:
        query = "DELETE FROM profile WHERE name = %s;"
        args = (name,)
        cur.execute(query, args)
        retmsg = {"message": 'Removed VM profile "{}".'.format(name)}
        retcode = 200
    except Exception as e:
        retmsg = {"message": 'Failed to delete entry "{}": {}'.format(name, e)}
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode
