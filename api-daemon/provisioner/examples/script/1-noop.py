#!/usr/bin/env python3

# 1-noop.py - PVC Provisioner example script for noop install
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

# This script provides an example of a PVC provisioner script. It will create a
# standard VM config but do no actual setup/prepare/install/cleanup (noop).

# This script can thus be used as an example or reference implementation of a
# PVC provisioner script and expanded upon as required.
# *** READ THIS SCRIPT THOROUGHLY BEFORE USING TO UNDERSTAND HOW IT WORKS. ***

# A script must implement the class "VMBuilderScript" which extends "VMBuilder",
# providing the 5 functions indicated. Detailed explanation of the role of each
# function is provided in context of the example; see the other examples for
# more potential uses.

# Within the VMBuilderScript class, several helper functions are exposed through
# the parent VMBuilder class:
#  self.log_info(message):
#    Use this function to log an "informational" message instead of "print()"
#  self.log_warn(message):
#    Use this function to log a "warning" message
#  self.log_err(message):
#    Use this function to log an "error" message outside of an exception (see below)
#  self.fail(message, exception=<ExceptionClass>):
#    Use this function to bail out of the script safely instead if raising a
#    normal Python exception. You may pass an optional exception class keyword
#    argument for posterity in the logs if you wish; otherwise, ProvisioningException
#    is used. This function implicitly calls a "self.log_err" with the passed message

# Within the VMBuilderScript class, several common variables are exposed through
# the parent VMBuilder class:
#  self.vm_name: The name of the VM from PVC's perspective
#  self.vm_id: The VM ID (numerical component of the vm_name) from PVC's perspective
#  self.vm_uuid: An automatically-generated UUID for the VM
#  self.vm_profile: The PVC provisioner profile name used for the VM
#  self.vm_data: A dictionary of VM data collected by the provisioner; as an example:
#    {
#      "ceph_monitor_list": [
#        "hv1.pvcstorage.tld",
#        "hv2.pvcstorage.tld",
#        "hv3.pvcstorage.tld"
#      ],
#      "ceph_monitor_port": "6789",
#      "ceph_monitor_secret": "96721723-8650-4a72-b8f6-a93cd1a20f0c",
#      "mac_template": null,
#      "networks": [
#        {
#          "eth_bridge": "vmbr1001",
#          "id": 72,
#          "network_template": 69,
#          "vni": "1001"
#        },
#        {
#          "eth_bridge": "vmbr101",
#          "id": 73,
#          "network_template": 69,
#          "vni": "101"
#        }
#      ],
#      "script": [contents of this file]
#      "script_arguments": {
#        "deb_mirror": "http://ftp.debian.org/debian",
#        "deb_release": "bullseye"
#      },
#      "system_architecture": "x86_64",
#      "system_details": {
#        "id": 78,
#        "migration_method": "live",
#        "name": "small",
#        "node_autostart": false,
#        "node_limit": null,
#        "node_selector": null,
#        "ova": null,
#        "serial": true,
#        "vcpu_count": 2,
#        "vnc": false,
#        "vnc_bind": null,
#        "vram_mb": 2048
#      },
#      "volumes": [
#        {
#          "disk_id": "sda",
#          "disk_size_gb": 4,
#          "filesystem": "ext4",
#          "filesystem_args": "-L=root",
#          "id": 9,
#          "mountpoint": "/",
#          "pool": "vms",
#          "source_volume": null,
#          "storage_template": 67
#        },
#        {
#          "disk_id": "sdb",
#          "disk_size_gb": 4,
#          "filesystem": "ext4",
#          "filesystem_args": "-L=var",
#          "id": 10,
#          "mountpoint": "/var",
#          "pool": "vms",
#          "source_volume": null,
#          "storage_template": 67
#        },
#        {
#          "disk_id": "sdc",
#          "disk_size_gb": 4,
#          "filesystem": "ext4",
#          "filesystem_args": "-L=log",
#          "id": 11,
#          "mountpoint": "/var/log",
#          "pool": "vms",
#          "source_volume": null,
#          "storage_template": 67
#        }
#      ]
#    }
#
# Any other information you may require must be obtained manually.

# WARNING:
#
# For safety reasons, the script runs in a modified chroot. It will have full access to
# the entire / (root partition) of the hypervisor, but read-only. In addition it has
# access to /dev, /sys, /run, and a fresh /tmp to write to; use /tmp/target (as
# convention) as the destination for any mounting of volumes and installation.
# Of course, in addition to this safety, it is VERY IMPORTANT to be aware that this
# script runs AS ROOT ON THE HYPERVISOR SYSTEM. You should never allow arbitrary,
# untrusted users the ability to add provisioning scripts even with this safeguard,
# since they could still do destructive things to /dev and the like!


# This import is always required here, as VMBuilder is used by the VMBuilderScript class.
from daemon_lib.vmbuilder import VMBuilder


# The VMBuilderScript class must be named as such, and extend VMBuilder.
class VMBuilderScript(VMBuilder):
    def setup(self):
        """
        setup(): Perform special setup steps or validation before proceeding
        """

        pass

    def create(self):
        """
        create(): Create the VM libvirt schema definition

        This step *must* return a fully-formed Libvirt XML document as a string or the
        provisioning task will fail.

        This example leverages the built-in libvirt_schema objects provided by PVC; these
        can be used as-is, or replaced with your own schema(s) on a per-script basis.

        Even though we noop the rest of the script, we still create a fully-formed libvirt
        XML document here as a demonstration.
        """

        # Run any imports first
        import daemon_lib.libvirt_schema as libvirt_schema
        import datetime
        import random

        # Create the empty schema document that we will append to and return at the end
        schema = ""

        # Prepare a description based on the VM profile
        description = (
            f"PVC provisioner @ {datetime.datetime.now()}, profile '{self.vm_profile}'"
        )

        # Format the header
        schema += libvirt_schema.libvirt_header.format(
            vm_name=self.vm_name,
            vm_uuid=self.vm_uuid,
            vm_description=description,
            vm_memory=self.vm_data["system_details"]["vram_mb"],
            vm_vcpus=self.vm_data["system_details"]["vcpu_count"],
            vm_architecture=self.vm_data["system_architecture"],
        )

        # Add the disk devices
        monitor_list = self.vm_data["ceph_monitor_list"]
        monitor_port = self.vm_data["ceph_monitor_port"]
        monitor_secret = self.vm_data["ceph_monitor_secret"]

        for volume in self.vm_data["volumes"]:
            schema += libvirt_schema.devices_disk_header.format(
                ceph_storage_secret=monitor_secret,
                disk_pool=volume["pool"],
                vm_name=self.vm_name,
                disk_id=volume["disk_id"],
            )
            for monitor in monitor_list:
                schema += libvirt_schema.devices_disk_coordinator.format(
                    coordinator_name=monitor,
                    coordinator_ceph_mon_port=monitor_port,
                )
            schema += libvirt_schema.devices_disk_footer

        # Add the special vhostmd device for hypervisor information inside the VM
        schema += libvirt_schema.devices_vhostmd

        # Add the network devices
        network_id = 0
        for network in self.vm_data["networks"]:
            vm_id_hex = "{:x}".format(int(self.vm_id % 16))
            net_id_hex = "{:x}".format(int(network_id % 16))

            if self.vm_data.get("mac_template") is not None:
                mac_prefix = "52:54:01"
                macgen_template = self.vm_data["mac_template"]
                eth_macaddr = macgen_template.format(
                    prefix=mac_prefix, vmid=vm_id_hex, netid=net_id_hex
                )
            else:
                mac_prefix = "52:54:00"
                random_octet_A = "{:x}".format(random.randint(16, 238))
                random_octet_B = "{:x}".format(random.randint(16, 238))
                random_octet_C = "{:x}".format(random.randint(16, 238))

                macgen_template = "{prefix}:{octetA}:{octetB}:{octetC}"
                eth_macaddr = macgen_template.format(
                    prefix=mac_prefix,
                    octetA=random_octet_A,
                    octetB=random_octet_B,
                    octetC=random_octet_C,
                )

            schema += libvirt_schema.devices_net_interface.format(
                eth_macaddr=eth_macaddr,
                eth_bridge=network["eth_bridge"],
            )

            network_id += 1

        # Add default devices
        schema += libvirt_schema.devices_default

        # Add serial device
        if self.vm_data["system_details"]["serial"]:
            schema += libvirt_schema.devices_serial.format(vm_name=self.vm_name)

        # Add VNC device
        if self.vm_data["system_details"]["vnc"]:
            if self.vm_data["system_details"]["vnc_bind"]:
                vm_vnc_bind = self.vm_data["system_details"]["vnc_bind"]
            else:
                vm_vnc_bind = "127.0.0.1"

            vm_vncport = 5900
            vm_vnc_autoport = "yes"

            schema += libvirt_schema.devices_vnc.format(
                vm_vncport=vm_vncport,
                vm_vnc_autoport=vm_vnc_autoport,
                vm_vnc_bind=vm_vnc_bind,
            )

        # Add SCSI controller
        schema += libvirt_schema.devices_scsi_controller

        # Add footer
        schema += libvirt_schema.libvirt_footer

        return schema

    def prepare(self):
        """
        prepare(): Prepare any disks/volumes for the install() step
        """

        pass

    def install(self):
        """
        install(): Perform the installation
        """

        pass

    def cleanup(self):
        """
        cleanup(): Perform any cleanup required due to prepare()/install()

        This function is also called if there is ANY exception raised in the prepare()
        or install() steps. While this doesn't mean you shouldn't or can't raise exceptions
        here, be warned that doing so might cause loops. Do this only if you really need to.
        """

        pass
