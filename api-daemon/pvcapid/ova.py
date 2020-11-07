#!/usr/bin/env python3

# ova.py - PVC OVA parser library
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
import psycopg2
import psycopg2.extras
import re
import math
import tarfile

import lxml.etree

from werkzeug.formparser import parse_form_data

import daemon_lib.common as pvc_common
import daemon_lib.ceph as pvc_ceph

import pvcapid.provisioner as provisioner

config = None  # Set in this namespace by flaskapi


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
# OVA functions
#
def list_ova(limit, is_fuzzy=True):
    if limit:
        if is_fuzzy:
            # Handle fuzzy vs. non-fuzzy limits
            if not re.match('[^].*', limit):
                limit = '%' + limit
            else:
                limit = limit[1:]
            if not re.match('.*[$]', limit):
                limit = limit + '%'
            else:
                limit = limit[:-1]

        query = "SELECT id, name FROM {} WHERE name LIKE %s;".format('ova')
        args = (limit, )
    else:
        query = "SELECT id, name FROM {};".format('ova')
        args = ()

    conn, cur = open_database(config)
    cur.execute(query, args)
    data = cur.fetchall()
    close_database(conn, cur)

    ova_data = list()

    for ova in data:
        ova_id = ova.get('id')
        ova_name = ova.get('name')

        query = "SELECT pool, volume_name, volume_format, disk_id, disk_size_gb FROM {} WHERE ova = %s;".format('ova_volume')
        args = (ova_id,)
        conn, cur = open_database(config)
        cur.execute(query, args)
        volumes = cur.fetchall()
        close_database(conn, cur)

        ova_data.append({'id': ova_id, 'name': ova_name, 'volumes': volumes})

    if ova_data:
        return ova_data, 200
    else:
        return {'message': 'No OVAs found.'}, 404


def delete_ova(name):
    ova_data, retcode = list_ova(name, is_fuzzy=False)
    if retcode != 200:
        retmsg = {'message': 'The OVA "{}" does not exist.'.format(name)}
        retcode = 400
        return retmsg, retcode

    conn, cur = open_database(config)
    ova_id = ova_data[0].get('id')
    try:
        # Get the list of volumes for this OVA
        query = "SELECT pool, volume_name FROM ova_volume WHERE ova = %s;"
        args = (ova_id,)
        cur.execute(query, args)
        volumes = cur.fetchall()

        # Remove each volume for this OVA
        zk_conn = pvc_common.startZKConnection(config['coordinators'])
        for volume in volumes:
            pvc_ceph.remove_volume(zk_conn, volume.get('pool'), volume.get('volume_name'))

        # Delete the volume entries from the database
        query = "DELETE FROM ova_volume WHERE ova = %s;"
        args = (ova_id,)
        cur.execute(query, args)

        # Delete the profile entries from the database
        query = "DELETE FROM profile WHERE ova = %s;"
        args = (ova_id,)
        cur.execute(query, args)

        # Delete the system_template entries from the database
        query = "DELETE FROM system_template WHERE ova = %s;"
        args = (ova_id,)
        cur.execute(query, args)

        # Delete the OVA entry from the database
        query = "DELETE FROM ova WHERE id = %s;"
        args = (ova_id,)
        cur.execute(query, args)

        retmsg = {"message": 'Removed OVA image "{}".'.format(name)}
        retcode = 200
    except Exception as e:
        retmsg = {'message': 'Failed to remove OVA "{}": {}'.format(name, e)}
        retcode = 400
    close_database(conn, cur)
    return retmsg, retcode


def upload_ova(pool, name, ova_size):
    ova_archive = None

    # Cleanup function
    def cleanup_ova_maps_and_volumes():
        # Close the OVA archive
        if ova_archive:
            ova_archive.close()
        zk_conn = pvc_common.startZKConnection(config['coordinators'])
        # Unmap the OVA temporary blockdev
        retflag, retdata = pvc_ceph.unmap_volume(zk_conn, pool, "ova_{}".format(name))
        # Remove the OVA temporary blockdev
        retflag, retdata = pvc_ceph.remove_volume(zk_conn, pool, "ova_{}".format(name))
        pvc_common.stopZKConnection(zk_conn)

    # Normalize the OVA size to bytes
    ova_size_bytes = int(pvc_ceph.format_bytes_fromhuman(ova_size)[:-1])
    ova_size = pvc_ceph.format_bytes_fromhuman(ova_size)

    # Verify that the cluster has enough space to store the OVA volumes (2x OVA size, temporarily, 1x permanently)
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    pool_information = pvc_ceph.getPoolInformation(zk_conn, pool)
    pvc_common.stopZKConnection(zk_conn)
    pool_free_space_bytes = int(pool_information['stats']['free_bytes'])
    if ova_size_bytes * 2 >= pool_free_space_bytes:
        output = {
            'message': "The cluster does not have enough free space ({}) to store the OVA volume ({}).".format(
                pvc_ceph.format_bytes_tohuman(pool_free_space_bytes),
                pvc_ceph.format_bytes_tohuman(ova_size_bytes)
            )
        }
        retcode = 400
        cleanup_ova_maps_and_volumes()
        return output, retcode

    # Create a temporary OVA blockdev
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.add_volume(zk_conn, pool, "ova_{}".format(name), ova_size)
    pvc_common.stopZKConnection(zk_conn)
    if not retflag:
        output = {
            'message': retdata.replace('\"', '\'')
        }
        retcode = 400
        cleanup_ova_maps_and_volumes()
        return output, retcode

    # Map the temporary OVA blockdev
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.map_volume(zk_conn, pool, "ova_{}".format(name))
    pvc_common.stopZKConnection(zk_conn)
    if not retflag:
        output = {
            'message': retdata.replace('\"', '\'')
        }
        retcode = 400
        cleanup_ova_maps_and_volumes()
        return output, retcode
    ova_blockdev = retdata

    # Save the OVA data to the temporary blockdev directly
    try:
        # This sets up a custom stream_factory that writes directly into the ova_blockdev,
        # rather than the standard stream_factory which writes to a temporary file waiting
        # on a save() call. This will break if the API ever uploaded multiple files, but
        # this is an acceptable workaround.
        def ova_stream_factory(total_content_length, filename, content_type, content_length=None):
            return open(ova_blockdev, 'wb')
        parse_form_data(flask.request.environ, stream_factory=ova_stream_factory)
    except Exception:
        output = {
            'message': "Failed to upload or write OVA file to temporary volume."
        }
        retcode = 400
        cleanup_ova_maps_and_volumes()
        return output, retcode

    try:
        # Set up the TAR reader for the OVA temporary blockdev
        ova_archive = tarfile.open(name=ova_blockdev)
        # Determine the files in the OVA
        members = ova_archive.getmembers()
    except tarfile.TarError:
        output = {
            'message': "The uploaded OVA file is not readable."
        }
        retcode = 400
        cleanup_ova_maps_and_volumes()
        return output, retcode

    # Parse through the members list and extract the OVF file
    for element in set(x for x in members if re.match('.*\.ovf$', x.name)):
        ovf_file = ova_archive.extractfile(element)

    # Parse the OVF file to get our VM details
    ovf_parser = OVFParser(ovf_file)
    ovf_xml_raw = ovf_parser.getXML()
    virtual_system = ovf_parser.getVirtualSystems()[0]
    virtual_hardware = ovf_parser.getVirtualHardware(virtual_system)
    disk_map = ovf_parser.getDiskMap(virtual_system)

    # Close the OVF file
    ovf_file.close()

    # Create and upload each disk volume
    for idx, disk in enumerate(disk_map):
        disk_identifier = "sd{}".format(chr(ord('a') + idx))
        volume = "ova_{}_{}".format(name, disk_identifier)
        dev_src = disk.get('src')
        dev_size_raw = ova_archive.getmember(dev_src).size
        vm_volume_size = disk.get('capacity')

        # Normalize the dev size to bytes
        dev_size = pvc_ceph.format_bytes_fromhuman(dev_size_raw)

        def cleanup_img_maps():
            zk_conn = pvc_common.startZKConnection(config['coordinators'])
            # Unmap the temporary blockdev
            retflag, retdata = pvc_ceph.unmap_volume(zk_conn, pool, volume)
            pvc_common.stopZKConnection(zk_conn)

        # Create the blockdev
        zk_conn = pvc_common.startZKConnection(config['coordinators'])
        retflag, retdata = pvc_ceph.add_volume(zk_conn, pool, volume, dev_size)
        pvc_common.stopZKConnection(zk_conn)
        if not retflag:
            output = {
                'message': retdata.replace('\"', '\'')
            }
            retcode = 400
            cleanup_img_maps()
            cleanup_ova_maps_and_volumes()
            return output, retcode

        # Map the blockdev
        zk_conn = pvc_common.startZKConnection(config['coordinators'])
        retflag, retdata = pvc_ceph.map_volume(zk_conn, pool, volume)
        pvc_common.stopZKConnection(zk_conn)
        if not retflag:
            output = {
                'message': retdata.replace('\"', '\'')
            }
            retcode = 400
            cleanup_img_maps()
            cleanup_ova_maps_and_volumes()
            return output, retcode
        temp_blockdev = retdata

        try:
            # Open (extract) the TAR archive file and seek to byte 0
            vmdk_file = ova_archive.extractfile(disk.get('src'))
            vmdk_file.seek(0)
            # Open the temporary blockdev and seek to byte 0
            blk_file = open(temp_blockdev, 'wb')
            blk_file.seek(0)
            # Close blk_file (and flush the buffers)
            blk_file.close()
            # Close vmdk_file
            vmdk_file.close()
            # Perform an OS-level sync
            pvc_common.run_os_command('sync')
        except Exception:
            output = {
                'message': "Failed to write image file '{}' to temporary volume.".format(disk.get('src'))
            }
            retcode = 400
            cleanup_img_maps()
            cleanup_ova_maps_and_volumes()
            return output, retcode

        cleanup_img_maps()

    cleanup_ova_maps_and_volumes()

    # Prepare the database entries
    query = "INSERT INTO ova (name, ovf) VALUES (%s, %s);"
    args = (name, ovf_xml_raw)
    conn, cur = open_database(config)
    try:
        cur.execute(query, args)
        close_database(conn, cur)
    except Exception as e:
        output = {
            'message': 'Failed to create OVA entry "{}": {}'.format(name, e)
        }
        retcode = 400
        close_database(conn, cur)
        return output, retcode

    # Get the OVA database id
    query = "SELECT id FROM ova WHERE name = %s;"
    args = (name, )
    conn, cur = open_database(config)
    cur.execute(query, args)
    ova_id = cur.fetchone()['id']
    close_database(conn, cur)

    # Prepare disk entries in ova_volume
    for idx, disk in enumerate(disk_map):
        disk_identifier = "sd{}".format(chr(ord('a') + idx))
        volume_type = disk.get('src').split('.')[-1]
        volume = "ova_{}_{}".format(name, disk_identifier)
        vm_volume_size = disk.get('capacity')

        # The function always return XXXXB, so strip off the B and convert to an integer
        vm_volume_size_bytes = int(pvc_ceph.format_bytes_fromhuman(vm_volume_size)[:-1])
        vm_volume_size_gb = math.ceil(vm_volume_size_bytes / 1024 / 1024 / 1024)

        query = "INSERT INTO ova_volume (ova, pool, volume_name, volume_format, disk_id, disk_size_gb) VALUES (%s, %s, %s, %s, %s, %s);"
        args = (ova_id, pool, volume, volume_type, disk_identifier, vm_volume_size_gb)

        conn, cur = open_database(config)
        try:
            cur.execute(query, args)
            close_database(conn, cur)
        except Exception as e:
            output = {
                'message': 'Failed to create OVA volume entry "{}": {}'.format(volume, e)
            }
            retcode = 400
            close_database(conn, cur)
            return output, retcode

    # Prepare a system_template for the OVA
    vcpu_count = virtual_hardware.get('vcpus')
    vram_mb = virtual_hardware.get('vram')
    if virtual_hardware.get('graphics-controller') == 1:
        vnc = True
        serial = False
    else:
        vnc = False
        serial = True
    retdata, retcode = provisioner.create_template_system(name, vcpu_count, vram_mb, serial, vnc, vnc_bind=None, ova=ova_id)
    if retcode != 200:
        return retdata, retcode
    system_template, retcode = provisioner.list_template_system(name, is_fuzzy=False)
    if retcode != 200:
        return retdata, retcode
    system_template_name = system_template[0].get('name')

    # Prepare a barebones profile for the OVA
    retdata, retcode = provisioner.create_profile(name, 'ova', system_template_name, None, None, userdata=None, script=None, ova=name, arguments=None)
    if retcode != 200:
        return retdata, retcode

    output = {
        'message': "Imported OVA image '{}'.".format(name)
    }
    retcode = 200
    return output, retcode


#
# OVF parser
#
class OVFParser(object):
    RASD_TYPE = {
        "1": "vmci",
        "3": "vcpus",
        "4": "vram",
        "5": "ide-controller",
        "6": "scsi-controller",
        "10": "ethernet-adapter",
        "15": "cdrom",
        "17": "disk",
        "20": "other-storage-device",
        "23": "usb-controller",
        "24": "graphics-controller",
        "35": "sound-controller"
    }

    def _getFilelist(self):
        path = "{{{schema}}}References/{{{schema}}}File".format(schema=self.OVF_SCHEMA)
        id_attr = "{{{schema}}}id".format(schema=self.OVF_SCHEMA)
        href_attr = "{{{schema}}}href".format(schema=self.OVF_SCHEMA)
        current_list = self.xml.findall(path)
        results = [(x.get(id_attr), x.get(href_attr)) for x in current_list]
        return results

    def _getDisklist(self):
        path = "{{{schema}}}DiskSection/{{{schema}}}Disk".format(schema=self.OVF_SCHEMA)
        id_attr = "{{{schema}}}diskId".format(schema=self.OVF_SCHEMA)
        ref_attr = "{{{schema}}}fileRef".format(schema=self.OVF_SCHEMA)
        cap_attr = "{{{schema}}}capacity".format(schema=self.OVF_SCHEMA)
        cap_units = "{{{schema}}}capacityAllocationUnits".format(schema=self.OVF_SCHEMA)
        current_list = self.xml.findall(path)
        results = [(x.get(id_attr), x.get(ref_attr), x.get(cap_attr), x.get(cap_units)) for x in current_list]
        return results

    def _getAttributes(self, virtual_system, path, attribute):
        current_list = virtual_system.findall(path)
        results = [x.get(attribute) for x in current_list]
        return results

    def __init__(self, ovf_file):
        self.xml = lxml.etree.parse(ovf_file)

        # Define our schemas
        envelope_tag = self.xml.find(".")
        self.XML_SCHEMA = envelope_tag.nsmap.get('xsi')
        self.OVF_SCHEMA = envelope_tag.nsmap.get('ovf')
        self.RASD_SCHEMA = envelope_tag.nsmap.get('rasd')
        self.SASD_SCHEMA = envelope_tag.nsmap.get('sasd')
        self.VSSD_SCHEMA = envelope_tag.nsmap.get('vssd')

        self.ovf_version = int(self.OVF_SCHEMA.split('/')[-1])

        # Get the file and disk lists
        self.filelist = self._getFilelist()
        self.disklist = self._getDisklist()

    def getVirtualSystems(self):
        return self.xml.findall("{{{schema}}}VirtualSystem".format(schema=self.OVF_SCHEMA))

    def getXML(self):
        return lxml.etree.tostring(self.xml, pretty_print=True).decode('utf8')

    def getVirtualHardware(self, virtual_system):
        hardware_list = virtual_system.findall(
            "{{{schema}}}VirtualHardwareSection/{{{schema}}}Item".format(schema=self.OVF_SCHEMA)
        )
        virtual_hardware = {}

        for item in hardware_list:
            try:
                item_type = self.RASD_TYPE[item.find("{{{rasd}}}ResourceType".format(rasd=self.RASD_SCHEMA)).text]
            except Exception:
                continue
            quantity = item.find("{{{rasd}}}VirtualQuantity".format(rasd=self.RASD_SCHEMA))
            if quantity is None:
                virtual_hardware[item_type] = 1
            else:
                virtual_hardware[item_type] = quantity.text

        return virtual_hardware

    def getDiskMap(self, virtual_system):
        # OVF v2 uses the StorageItem field, while v1 uses the normal Item field
        if self.ovf_version < 2:
            hardware_list = virtual_system.findall(
                "{{{schema}}}VirtualHardwareSection/{{{schema}}}Item".format(schema=self.OVF_SCHEMA)
            )
        else:
            hardware_list = virtual_system.findall(
                "{{{schema}}}VirtualHardwareSection/{{{schema}}}StorageItem".format(schema=self.OVF_SCHEMA)
            )
        disk_list = []

        for item in hardware_list:
            item_type = None

            if self.SASD_SCHEMA is not None:
                item_type = self.RASD_TYPE[item.find("{{{sasd}}}ResourceType".format(sasd=self.SASD_SCHEMA)).text]
            else:
                item_type = self.RASD_TYPE[item.find("{{{rasd}}}ResourceType".format(rasd=self.RASD_SCHEMA)).text]

            if item_type != 'disk':
                continue

            hostref = None
            if self.SASD_SCHEMA is not None:
                hostref = item.find("{{{sasd}}}HostResource".format(sasd=self.SASD_SCHEMA))
            else:
                hostref = item.find("{{{rasd}}}HostResource".format(rasd=self.RASD_SCHEMA))
            if hostref is None:
                continue
            disk_res = hostref.text

            # Determine which file this disk_res ultimately represents
            (disk_id, disk_ref, disk_capacity, disk_capacity_unit) = [x for x in self.disklist if x[0] == disk_res.split('/')[-1]][0]
            (file_id, disk_src) = [x for x in self.filelist if x[0] == disk_ref][0]

            if disk_capacity_unit is not None:
                # Handle the unit conversion
                base_unit, action, multiple = disk_capacity_unit.split()
                multiple_base, multiple_exponent = multiple.split('^')
                disk_capacity = int(disk_capacity) * (int(multiple_base) ** int(multiple_exponent))

            # Append the disk with all details to the list
            disk_list.append({
                "id": disk_id,
                "ref": disk_ref,
                "capacity": disk_capacity,
                "src": disk_src
            })

        return disk_list
