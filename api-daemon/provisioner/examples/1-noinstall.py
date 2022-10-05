#!/usr/bin/env python3

# 1-noinstall.py - PVC Provisioner example script for noop install
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2022 Joshua M. Boniface <joshua@boniface.me>
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
# standard VM config but do no preparation/installation/cleanup (noop).

# This script can thus be used as an example or reference implementation of a
# PVC provisioner script and expanded upon as required.

# The script must implement the class "VMBuilderScript" which extens "VMBuilder",
# providing the 5 functions indicated. Detailed explanation of the role of each
# function is provided.

# Within the VMBuilderScript class, several common variables are exposed:
#  self.vm_name: The name of the VM from PVC's perspective
#  self.vm_id: The VM ID (numerical component of the vm_name) from PVC's perspective
#  self.vm_uuid: An automatically-generated UUID for the VM
#  self.vm_profile: The PVC provisioner profile name used for the VM
#  self.vm-data: A dictionary of VM data collected by the provisioner; an example:
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


from pvcapi.vmbuilder import VMBuilder


class VMBuilderScript(VMBuilder):
    def setup(self):
        """
        setup(): Perform special setup steps or validation before proceeding

        Since we do no install in this example, it does nothing.
        """

        pass

    def create(self):
        """
        create(): Create the VM libvirt schema definition

        This step *must* return a fully-formed Libvirt XML document as a string.

        This example leverages the built-in libvirt_schema objects provided by PVC; these
        can be used as-is, or replaced with your own schema(s) on a per-script basis.
        """

        # Run any imports first
        import datetime
        import random
        import pvcapid.libvirt_schema as libvirt_schema

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

        This function should use the various exposed PVC commands as indicated to create
        block devices and map them to the host.
        """

        # First loop: Create the disks, either by cloning (pvc_ceph.clone_volume), or by
        # new creation (pvc_ceph.add_volume).
        for volume in self.vm_data["volumes"]:
            if volume.get("source_volume") is not None:
                with open_zk(config) as zkhandler:
                    success, message = pvc_ceph.clone_volume(
                        zkhandler,
                        volume["pool"],
                        volume["source_volume"],
                        f"{self.vm_name}_{volume['disk_id']}",
                    )
                    print(message)
                    if not success:
                        raise ProvisioningError(
                            f"Failed to clone volume '{volume['source_volume']}' to '{volume['disk_id']}'."
                        )
            else:
                with open_zk(config) as zkhandler:
                    success, message = pvc_ceph.add_volume(
                        zkhandler,
                        volume["pool"],
                        f"{self.vm_name}_{volume['disk_id']}",
                        f"{volume['disk_size_gb']}G",
                    )
                    print(message)
                    if not success:
                        raise ProvisioningError(
                            f"Failed to create volume '{volume['disk_id']}'."
                        )

        # Second loop: Map the disks to the local system
        for volume in self.vm_data["volumes"]:
            dst_volume_name = f"{self.vm_name}_{volume['disk_id']}"
            dst_volume = f"{volume['pool']}/{dst_volume_name}"

            with open_zk(config) as zkhandler:
                success, message = pvc_ceph.map_volume(
                    zkhandler,
                    volume["pool"],
                    dst_volume_name,
                )
                print(message)
                if not retcode:
                    raise ProvisioningError(f"Failed to map volume '{dst_volume}'.")

        # Third loop: Create filesystems on the volumes
        for volume in self.vm_data["volumes"]:
            dst_volume_name = f"{self.vm_name}_{volume['disk_id']}"
            dst_volume = f"{volume['pool']}/{dst_volume_name}"

            if volume.get("source_volume") is not None:
                continue

            if volume.get("filesystem") is None:
                continue

            filesystem_args_list = list()
            for arg in volume["filesystem_args"].split():
                arg_entry, *arg_data = arg.split("=")
                arg_data = "=".join(arg_data)
                filesystem_args_list.append(arg_entry)
                filesystem_args_list.append(arg_data)
            filesystem_args = " ".join(filesystem_args_list)

            if volume["filesystem"] == "swap":
                retcode, stdout, stderr = pvc_common.run_os_command(
                    f"mkswap -f /dev/rbd/{dst_volume}"
                )
                if retcode:
                    raise ProvisioningError(
                        f"Failed to create swap on '{dst_volume}': {stderr}"
                    )
            else:
                retcode, stdout, stderr = pvc_common.run_os_command(
                    f"mkfs.{volume['filesystem']} {filesystem_args} /dev/rbd/{dst_volume}"
                )
                if retcode:
                    raise ProvisioningError(
                        f"Faield to create {volume['filesystem']} file on '{dst_volume}': {stderr}"
                    )

            print(stdout)

        # Create a temporary directory to use during install
        temp_dir = "/tmp/target"
        if not os.exists(temp_dir):
            os.mkdir(temp_dir)

        # Fourth loop: Mount the volumes to a set of temporary directories
        for volume in self.vm_data["volumes"]:
            dst_volume_name = f"{self.vm_name}_{volume['disk_id']}"
            dst_volume = f"{volume['pool']}/{dst_volume_name}"

            if volume.get("source_volume") is not None:
                continue

            if volume.get("filesystem") is None:
                continue

            mapped_dst_volume = f"/dev/rbd/{dst_volume}"

            mount_path = f"{temp_dir}/{volume['mountpoint']}"

            if not os.exists(mount_path):
                os.mkdir(mount_path)

            # Mount filesystem
            retcode, stdout, stderr = pvc_common.run_os_command(
                f"mount {mapped_dst_volume} {mount_path}"
            )
            if retcode:
                raise ProvisioningError(
                    f"Failed to mount '{mapped_dst_volume}' on '{mount_path}': {stderr}"
                )

    def install(self):
        """
        install(): Perform the installation

        Since this is a noop example, this step does nothing, aside from getting some
        arguments for demonstration.
        """

        arguments = self.vm_data["script_arguments"]
        if arguments.get("vm_fqdn"):
            vm_fqdn = arguments.get("vm_fqdn")
        else:
            vm_fqdn = self.vm_name

        pass

    def cleanup(self):
        """
        cleanup(): Perform any cleanup required due to prepare()/install()

        It is important to now reverse *all* steps taken in those functions that might
        need cleanup before teardown of the overlay chroot environment.
        """

        temp_dir = "/tmp/target"

        for volume in list(reversed(self.vm_data["volumes"])):
            dst_volume_name = f"{self.vm_name}_{volume['disk_id']}"
            dst_volume = f"{volume['pool']}/{dst_volume_name}"
            mapped_dst_volume = f"/dev/rbd/{dst_volume}"
            mount_path = f"{temp_dir}/{volume['mountpoint']}"

            if (
                volume.get("source_volume") is None
                and volume.get("filesystem") is not None
            ):
                # Unmount filesystem
                retcode, stdout, stderr = pvc_common.run_os_command(
                    f"umount {mount_path}"
                )
                if retcode:
                    raise ProvisioningError(
                        f"Failed to unmount '{mapped_dst_volume}' on '{mount_path}': {stderr}"
                    )

                # Unmap volume
                with open_zk(config) as zkhandler:
                    success, message = pvc_ceph.unmap_volume(
                        zkhandler,
                        volume["pool"],
                        dst_volume_name,
                    )
                    if not success:
                        raise ProvisioningError(
                            f"Failed to unmap '{mapped_dst_volume}': {stderr}"
                        )
