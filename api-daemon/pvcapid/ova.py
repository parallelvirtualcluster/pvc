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
import json
import psycopg2
import psycopg2.extras
import os
import re
import time
import math
import tarfile
import shutil
import shlex
import subprocess

import lxml.etree

import daemon_lib.common as pvc_common
import daemon_lib.node as pvc_node
import daemon_lib.vm as pvc_vm
import daemon_lib.network as pvc_network
import daemon_lib.ceph as pvc_ceph

import pvcapid.libvirt_schema as libvirt_schema

#
# OVA upload function
#
def upload_ova(ova_data, ova_size, pool, name, define_vm, start_vm):
    # Upload flow is as follows:
    # 1. Create temporary volume of ova_size
    # 2. Map the temporary volume for reading
    # 3. Write OVA upload file to temporary volume
    # 4. Read tar from temporary volume, extract OVF
    # 5. Parse OVF, obtain disk list and VM details
    # 6. Extract and "upload" via API each disk image to Ceph
    # 7. Unmap and remove the temporary volume
    # 8. Define VM (if applicable)
    # 9. Start VM (if applicable)
    ###########################################################

    # Cleanup function
    def cleanup_ova_maps_and_volumes():
        # Close the OVA archive
        ova_archive.close()
        zk_conn = pvc_common.startZKConnection(config['coordinators'])
        # Unmap the OVA temporary blockdev
        retflag, retdata = pvc_ceph.unmap_volume(zk_conn, pool, "{}_ova".format(name))
        # Remove the OVA temporary blockdev
        retflag, retdata = pvc_ceph.remove_volume(zk_conn, pool, "{}_ova".format(name))
        pvc_common.stopZKConnection(zk_conn)

    # Normalize the OVA size to MB
    print("Normalize the OVA size to MB")
    # The function always return XXXXB, so strip off the B and convert to an integer
    ova_size_bytes = int(pvc_ceph.format_bytes_fromhuman(ova_size)[:-1])
    # Put the size into KB which rbd --size can understand
    ova_size_kb = math.ceil(ova_size_bytes / 1024)
    ova_size = "{}K".format(ova_size_kb)

    # Create a temporary OVA blockdev
    print("Create a temporary OVA blockdev")
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    print(ova_size)
    retflag, retdata = pvc_ceph.add_volume(zk_conn, pool, "{}_ova".format(name), ova_size)
    pvc_common.stopZKConnection(zk_conn)
    if not retflag:
        output = {
            'message': retdata.replace('\"', '\'')
        }
        retcode = 400
        cleanup_ova_maps_and_volumes()
        return output, retcode

    # Map the temporary OVA blockdev
    print("Map the temporary OVA blockdev")
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.map_volume(zk_conn, pool, "{}_ova".format(name))
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
    print("Save the OVA data to the temporary blockdev directly")
    try:
        ova_data.save(ova_blockdev)
    except:
        output = {
            'message': "ERROR: Failed to write OVA file to temporary volume."
        }
        retcode = 400
        cleanup_ova_maps_and_volumes()
        return output, retcode

    try:
        # Set up the TAR reader for the OVA temporary blockdev
        print("Set up the TAR reader for the OVA temporary blockdev")
        ova_archive = tarfile.open(name=ova_blockdev)
        # Determine the files in the OVA
        print("Determine the files in the OVA")
        members = ova_archive.getmembers()
    except tarfile.TarError:
        output = {
            'message': "ERROR: The uploaded OVA file is not readable."
        }
        retcode = 400
        cleanup_ova_maps_and_volumes()
        return output, retcode

    # Parse through the members list and extract the OVF file
    print("Parse through the members list and extract the OVF file")
    for element in set(x for x in members if re.match('.*\.ovf$', x.name)):
        ovf_file = ova_archive.extractfile(element)
        print(ovf_file)

    # Parse the OVF file to get our VM details
    print("Parse the OVF file to get our VM details")
    ovf_parser = OVFParser(ovf_file)
    virtual_system = ovf_parser.getVirtualSystems()[0]
    virtual_hardware = ovf_parser.getVirtualHardware(virtual_system)
    disk_map = ovf_parser.getDiskMap(virtual_system)

    # Close the OVF file
    print("Close the OVF file")
    ovf_file.close()

    print(virtual_hardware)
    print(disk_map)

    # Verify that the cluster has enough space to store all OVA disk volumes
    total_size_bytes = 0
    for disk in disk_map:
        # Normalize the dev size to MB
        print("Normalize the dev size to MB")
        # The function always return XXXXB, so strip off the B and convert to an integer
        dev_size_bytes = int(pvc_ceph.format_bytes_fromhuman(disk.get('capacity', 0))[:-1])
        ova_size_bytes = int(pvc_ceph.format_bytes_fromhuman(ova_size)[:-1])
        # Get the actual image size
        total_size_bytes += dev_size_bytes
        # Add on the OVA size to account for the VMDK
        total_size_bytes += ova_size_bytes

    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    pool_information = pvc_ceph.getPoolInformation(zk_conn, pool)
    pvc_common.stopZKConnection(zk_conn)
    pool_free_space_bytes = int(pool_information['stats']['free_bytes'])
    if total_size_bytes >= pool_free_space_bytes:
        output = {
            'message': "ERROR: The cluster does not have enough free space ({}) to store the VM ({}).".format(
                pvc_ceph.format_bytes_tohuman(pool_free_space_bytes),
                pvc_ceph.format_bytes_tohuman(total_size_bytes)
            )
        }
        retcode = 400
        cleanup_ova_maps_and_volumes()
        return output, retcode

    # Create and upload each disk volume
    for idx, disk in enumerate(disk_map):
        disk_identifier = "sd{}".format(chr(ord('a') + idx))
        volume = "{}_{}".format(name, disk_identifier)
        dev_size = disk.get('capacity')

        # Normalize the dev size to MB
        print("Normalize the dev size to MB")
        # The function always return XXXXB, so strip off the B and convert to an integer
        dev_size_bytes = int(pvc_ceph.format_bytes_fromhuman(dev_size)[:-1])
        dev_size_mb = math.ceil(dev_size_bytes / 1024 / 1024)
        dev_size = "{}M".format(dev_size_mb)

        def cleanup_img_maps_and_volumes():
            zk_conn = pvc_common.startZKConnection(config['coordinators'])
            # Unmap the target blockdev
            retflag, retdata = pvc_ceph.unmap_volume(zk_conn, pool, volume)
            # Unmap the temporary blockdev
            retflag, retdata = pvc_ceph.unmap_volume(zk_conn, pool, "{}_tmp".format(volume))
            # Remove the temporary blockdev
            retflag, retdata = pvc_ceph.remove_volume(zk_conn, pool, "{}_tmp".format(volume))
            pvc_common.stopZKConnection(zk_conn)

        # Create target blockdev
        zk_conn = pvc_common.startZKConnection(config['coordinators'])
        pool_information = pvc_ceph.add_volume(zk_conn, pool, volume, dev_size)
        pvc_common.stopZKConnection(zk_conn)
       
        # Create a temporary blockdev
        zk_conn = pvc_common.startZKConnection(config['coordinators'])
        retflag, retdata = pvc_ceph.add_volume(zk_conn, pool, "{}_tmp".format(volume), ova_size)
        pvc_common.stopZKConnection(zk_conn)
        if not retflag:
            output = {
                'message': retdata.replace('\"', '\'')
            }
            retcode = 400
            cleanup_img_maps_and_volumes()
            cleanup_ova_maps_and_volumes()
            return output, retcode

        # Map the temporary target blockdev
        zk_conn = pvc_common.startZKConnection(config['coordinators'])
        retflag, retdata = pvc_ceph.map_volume(zk_conn, pool, "{}_tmp".format(volume))
        pvc_common.stopZKConnection(zk_conn)
        if not retflag:
            output = {
                'message': retdata.replace('\"', '\'')
            }
            retcode = 400
            cleanup_img_maps_and_volumes()
            cleanup_ova_maps_and_volumes()
            return output, retcode
        temp_blockdev = retdata

        # Map the target blockdev
        zk_conn = pvc_common.startZKConnection(config['coordinators'])
        retflag, retdata = pvc_ceph.map_volume(zk_conn, pool, volume)
        pvc_common.stopZKConnection(zk_conn)
        if not retflag:
            output = {
                'message': retdata.replace('\"', '\'')
            }
            retcode = 400
            cleanup_img_maps_and_volumes()
            cleanup_ova_maps_and_volumes()
            return output, retcode
        dest_blockdev = retdata

        # Save the data to the temporary blockdev directly
        img_type = disk.get('src').split('.')[-1]

        try:
            # Open (extract) the TAR archive file and seek to byte 0
            vmdk_file = ova_archive.extractfile(disk.get('src'))
            vmdk_file.seek(0)
            # Open the temporary blockdev and seek to byte 0
            blk_file = open(temp_blockdev, 'wb')
            blk_file.seek(0)
            # Write the contents of vmdk_file into blk_file
            bytes_written = blk_file.write(vmdk_file.read())
            # Close blk_file (and flush the buffers)
            blk_file.close()
            # Close vmdk_file
            vmdk_file.close()
            # Perform an OS-level sync
            pvc_common.run_os_command('sync')
            # Shrink the tmp RBD image to the exact size of the written file
            # This works around a bug in this method where an EOF is never written to the end of the
            # target blockdev, thus causing an "Invalid footer" error. Instead, if we just shrink the
            # RBD volume to the exact size, this is treated as an EOF
            pvc_common.run_os_command('rbd resize {}/{}_{}_tmp --size {}B --allow-shrink'.format(pool, name, disk_identifier, bytes_written))
        except:
            output = {
                'message': "ERROR: Failed to write image file '{}' to temporary volume.".format(disk.get('src'))
            }
            retcode = 400
            cleanup_img_maps_and_volumes()
            cleanup_ova_maps_and_volumes()
            return output, retcode

        # Convert from the temporary to destination format on the blockdevs
        retcode, stdout, stderr = pvc_common.run_os_command(
            'qemu-img convert -C -f {} -O raw {} {}'.format(img_type, temp_blockdev, dest_blockdev)
        )
        if retcode:
            output = {
                'message': "ERROR: Failed to convert image '{}' format from '{}' to 'raw': {}".format(disk.get('src'), img_type, stderr)
            }
            retcode = 400
            cleanup_img_maps_and_volumes()
            cleanup_ova_maps_and_volumes()
            return output, retcode

        cleanup_img_maps_and_volumes()

    cleanup_ova_maps_and_volumes()

    # Prepare a VM configuration

    output = {
        'message': "Imported OVA file to new VM '{}'".format(name)
    }
    retcode = 200
    return output, retcode

#
# OVF parser
#
OVF_SCHEMA = "http://schemas.dmtf.org/ovf/envelope/2"
RASD_SCHEMA = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData"
SASD_SCHEMA = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_StorageAllocationSettingData.xsd"
VSSD_SCHEMA = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData"
XML_SCHEMA = "http://www.w3.org/2001/XMLSchema-instance"

RASD_TYPE = { 
    "3":  "vcpus",
    "4":  "vram",
    "5":  "ide-controller",
    "6":  "scsi-controller",
    "10": "ethernet-adapter",
    "15": "cdrom",
    "17": "disk",
    "20": "other-storage-device",
    "23": "usb-controller",
    "24": "graphics-controller",
    "35": "sound-controller"
}
SASD_TYPE = {
    "15": "cdrom",
    "17": "disk"
}

class OVFParser(object):
    def _getFilelist(self):
        path = "{{{schema}}}References/{{{schema}}}File".format(schema=OVF_SCHEMA)
        id_attr = "{{{schema}}}id".format(schema=OVF_SCHEMA)
        href_attr = "{{{schema}}}href".format(schema=OVF_SCHEMA)
        current_list = self.xml.findall(path) 
        results = [(x.get(id_attr), x.get(href_attr)) for x in current_list]
        return results

    def _getDisklist(self):
        path = "{{{schema}}}DiskSection/{{{schema}}}Disk".format(schema=OVF_SCHEMA)
        id_attr = "{{{schema}}}diskId".format(schema=OVF_SCHEMA)
        ref_attr = "{{{schema}}}fileRef".format(schema=OVF_SCHEMA)
        cap_attr = "{{{schema}}}capacity".format(schema=OVF_SCHEMA)
        current_list = self.xml.findall(path) 
        results = [(x.get(id_attr), x.get(ref_attr), x.get(cap_attr)) for x in current_list]
        return results

    def _getAttributes(self, virtual_system, path, attribute):
        current_list = virtual_system.findall(path) 
        results = [x.get(attribute) for x in current_list]
        return results

    def __init__(self, ovf_file):
        self.xml = lxml.etree.parse(ovf_file)
        self.filelist = self._getFilelist()
        self.disklist = self._getDisklist()

    def getVirtualSystems(self):
        return self.xml.findall("{{{schema}}}VirtualSystem".format(schema=OVF_SCHEMA))

    def getVirtualHardware(self, virtual_system):
        hardware_list = virtual_system.findall(
            "{{{schema}}}VirtualHardwareSection/{{{schema}}}Item".format(schema=OVF_SCHEMA)
        )
        virtual_hardware = {}

        for item in hardware_list:
            try:
                item_type = RASD_TYPE[item.find("{{{rasd}}}ResourceType".format(rasd=RASD_SCHEMA)).text]
            except:
                continue
            quantity = item.find("{{{rasd}}}VirtualQuantity".format(rasd=RASD_SCHEMA))
            if quantity is None:
                continue
            print(item_type)
            virtual_hardware[item_type] = quantity.text

        return virtual_hardware

    def getDiskMap(self, virtual_system):
        hardware_list = virtual_system.findall(
            "{{{schema}}}VirtualHardwareSection/{{{schema}}}StorageItem".format(schema=OVF_SCHEMA)
        )
        disk_list = []
        
        for item in hardware_list:
            item_type = None
            try:
                item_type = SASD_TYPE[item.find("{{{sasd}}}ResourceType".format(sasd=SASD_SCHEMA)).text]
            except:
                item_type = RASD_TYPE[item.find("{{{rasd}}}ResourceType".format(rasd=RASD_SCHEMA)).text]

            if item_type != 'disk':
                continue

            hostref = None
            try:
                hostref = item.find("{{{sasd}}}HostResource".format(sasd=SASD_SCHEMA))
            except:
                hostref = item.find("{{{rasd}}}HostResource".format(rasd=RASD_SCHEMA))
            if hostref is None:
                continue
            disk_res = hostref.text

            # Determine which file this disk_res ultimately represents
            (disk_id, disk_ref, disk_capacity) = [x for x in self.disklist if x[0] == disk_res.split('/')[-1]][0]
            (file_id, disk_src) = [x for x in self.filelist if x[0] == disk_ref][0]

            # Append the disk with all details to the list
            disk_list.append({
                "id": disk_id,
                "ref": disk_ref,
                "capacity": disk_capacity,
                "src": disk_src
            })

        return disk_list
