#!/usr/bin/env python3

# 3-debootstrap.py - PVC Provisioner example script for debootstrap install
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
# standard VM config and install a Debian-like OS using debootstrap.

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

        This example uses the PVC built-in command runner to verify that debootstrap is
        installed and throws and error if not.

        Note that, due to the aforementioned chroot, you *cannot* install or otherwise
        modify the hypervisor system here: any tooling, etc. must be pre-installed.
        """

        # Run any imports first; as shown here, you can import anything from the PVC
        # namespace, as well as (of course) the main Python namespaces
        import daemon_lib.common as pvc_common

        # Ensure we have debootstrap intalled on the provisioner system
        retcode, stdout, stderr = pvc_common.run_os_command(f"which debootstrap")
        if retcode:
            # Raise a ProvisioningError for any exception; the provisioner will handle
            # this gracefully and properly, avoiding dangling mounts, RBD maps, etc.
            self.fail("Failed to find critical dependency: debootstrap")

    def create(self):
        """
        create(): Create the VM libvirt schema definition

        This step *must* return a fully-formed Libvirt XML document as a string or the
        provisioning task will fail.

        This example leverages the built-in libvirt_schema objects provided by PVC; these
        can be used as-is, or replaced with your own schema(s) on a per-script basis.
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

        This function should use the various exposed PVC commands as indicated to create
        RBD block devices and map them to the host as required.

        open_zk is exposed from daemon_lib.vmbuilder to provide a context manager for opening
        connections to the PVC Zookeeper cluster; ensure you also import (and pass it)
        the config object from pvcworkerd.Daemon as well. This context manager then allows
        the use of various common daemon library functions, without going through the API.
        """

        # Run any imports first
        import os
        from daemon_lib.vmbuilder import open_zk
        from pvcworkerd.Daemon import config
        import daemon_lib.common as pvc_common
        import daemon_lib.ceph as pvc_ceph

        # First loop: Create the disks, either by cloning (pvc_ceph.clone_volume), or by
        # new creation (pvc_ceph.add_volume), depending on the source_volume entry
        for volume in self.vm_data["volumes"]:
            if volume.get("source_volume") is not None:
                with open_zk(config) as zkhandler:
                    success, message = pvc_ceph.clone_volume(
                        zkhandler,
                        volume["pool"],
                        volume["source_volume"],
                        f"{self.vm_name}_{volume['disk_id']}",
                    )
                    self.log_info(message)
                    if not success:
                        self.fail(
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
                    self.log_info(message)
                    if not success:
                        self.fail(f"Failed to create volume '{volume['disk_id']}'.")

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
                self.log_info(message)
                if not success:
                    self.fail(f"Failed to map volume '{dst_volume}'.")

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
                    self.fail(f"Failed to create swap on '{dst_volume}': {stderr}")
            else:
                retcode, stdout, stderr = pvc_common.run_os_command(
                    f"mkfs.{volume['filesystem']} {filesystem_args} /dev/rbd/{dst_volume}"
                )
                if retcode:
                    self.fail(
                        f"Faield to create {volume['filesystem']} file on '{dst_volume}': {stderr}"
                    )

            self.log_info(stdout)

        # Create a temporary directory to use during install
        temp_dir = "/tmp/target"

        if not os.path.isdir(temp_dir):
            os.mkdir(temp_dir)

        # Fourth loop: Mount the volumes to a set of temporary directories
        for volume in self.vm_data["volumes"]:
            dst_volume_name = f"{self.vm_name}_{volume['disk_id']}"
            dst_volume = f"{volume['pool']}/{dst_volume_name}"

            if volume.get("source_volume") is not None:
                continue

            if volume.get("filesystem") is None or volume.get("filesystem") == "swap":
                continue

            mapped_dst_volume = f"/dev/rbd/{dst_volume}"

            mount_path = f"{temp_dir}/{volume['mountpoint']}"

            if not os.path.isdir(mount_path):
                os.mkdir(mount_path)

            # Mount filesystem
            retcode, stdout, stderr = pvc_common.run_os_command(
                f"mount {mapped_dst_volume} {mount_path}"
            )
            if retcode:
                self.fail(
                    f"Failed to mount '{mapped_dst_volume}' on '{mount_path}': {stderr}"
                )

    def install(self):
        """
        install(): Perform the installation

        This example, unlike noop, performs a full debootstrap install and base config
        of a Debian-like system, including installing GRUB for fully-virtualized boot
        (required by PVC) and cloud-init for later configuration with the PVC userdata
        functionality, leveraging a PVC managed network on the first NIC for DHCP.

        Several arguments are also supported; these can be set either in the provisioner
        profile itself, or on the command line at runtime.

        To show the options, this function does not use the previous PVC-exposed
        run_os_command function, but instead just uses os.system. The downside here is
        a lack of response and error handling, but the upside is simpler-to-read code.
        Use whichever you feel is appropriate for your situation.
        """

        # Run any imports first
        import os
        from daemon_lib.vmbuilder import chroot

        # The directory we mounted things on earlier during prepare(); this could very well
        # be exposed as a module-level variable if you so choose
        temp_dir = "/tmp/target"

        # Use these convenient aliases for later (avoiding lots of "self.vm_data" everywhere)
        vm_name = self.vm_name
        volumes = self.vm_data["volumes"]
        networks = self.vm_data["networks"]

        # Parse these arguments out of self.vm_data["script_arguments"]
        if self.vm_data["script_arguments"].get("deb_release") is not None:
            deb_release = self.vm_data["script_arguments"].get("deb_release")
        else:
            deb_release = "stable"

        if self.vm_data["script_arguments"].get("deb_mirror") is not None:
            deb_mirror = self.vm_data["script_arguments"].get("deb_mirror")
        else:
            deb_mirror = "http://ftp.debian.org/debian"

        if self.vm_data["script_arguments"].get("deb_packages") is not None:
            deb_packages = (
                self.vm_data["script_arguments"].get("deb_packages").split(",")
            )
        else:
            deb_packages = [
                "linux-image-amd64",
                "grub-pc",
                "cloud-init",
                "python3-cffi-backend",
                "acpid",
                "acpi-support-base",
                "wget",
            ]

        # We need to know our root disk for later GRUB-ing
        root_volume = None
        for volume in volumes:
            if volume["mountpoint"] == "/":
                root_volume = volume
        if not root_volume:
            self.fail("Failed to find root volume in volumes list")

        # Perform a debootstrap installation
        self.log_info(
            f"Installing system with debootstrap: debootstrap --include={','.join(deb_packages)} {deb_release} {temp_dir} {deb_mirror}"
        )
        ret = os.system(
            f"debootstrap --include={','.join(deb_packages)} {deb_release} {temp_dir} {deb_mirror}"
        )
        if ret > 0:
            self.fail("Failed to run debootstrap")

        # Bind mount the devfs so we can grub-install later
        os.system("mount --bind /dev {}/dev".format(temp_dir))

        # Create an fstab entry for each volume
        fstab_file = "{}/etc/fstab".format(temp_dir)
        # The volume ID starts at zero and increments by one for each volume in the fixed-order
        # volume list. This lets us work around the insanity of Libvirt IDs not matching guest IDs,
        # while still letting us have some semblance of control here without enforcing things
        # like labels. It increments in the for loop below at the end of each iteration, and is
        # used to craft a /dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsi0-0-0-X device ID
        # which will always match the correct order from Libvirt (unlike sdX/vdX names).
        volume_id = 0
        for volume in volumes:
            # We assume SSD-based/-like storage (because Ceph behaves this way), and dislike atimes
            options = "defaults,discard,noatime,nodiratime"

            # The root, var, and log volumes have specific values
            if volume["mountpoint"] == "/":
                # This will be used later by GRUB's cmdline
                root_volume["scsi_id"] = volume_id
                dump = 0
                cpass = 1
            elif volume["mountpoint"] == "/var" or volume["mountpoint"] == "/var/log":
                dump = 0
                cpass = 2
            else:
                dump = 0
                cpass = 0

            # Append the fstab line
            with open(fstab_file, "a") as fh:
                # Using these /dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK entries guarantees
                # proper ordering; /dev/sdX (or similar) names are NOT guaranteed to be
                # in any order nor are they guaranteed to match the volume's sdX/vdX name
                # when inside the VM due to Linux's quirks.
                data = "/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsi0-0-0-{volume} {mountpoint} {filesystem} {options} {dump} {cpass}\n".format(
                    volume=volume_id,
                    mountpoint=volume["mountpoint"],
                    filesystem=volume["filesystem"],
                    options=options,
                    dump=dump,
                    cpass=cpass,
                )
                fh.write(data)

            # Increment the volume_id
            volume_id += 1

        # Write the hostname; you could also take an FQDN argument for this as an example
        hostname_file = "{}/etc/hostname".format(temp_dir)
        with open(hostname_file, "w") as fh:
            fh.write("{}".format(vm_name))

        # Fix the cloud-init.target since it's broken by default in Debian 11
        cloudinit_target_file = "{}/etc/systemd/system/cloud-init.target".format(
            temp_dir
        )
        with open(cloudinit_target_file, "w") as fh:
            # We lose our indent on these raw blocks to preserve the apperance of the files
            # inside the VM itself
            data = """[Install]
WantedBy=multi-user.target
[Unit]
Description=Cloud-init target
After=multi-user.target
"""
            fh.write(data)

        # Write the cloud-init configuration
        ci_cfg_file = "{}/etc/cloud/cloud.cfg".format(temp_dir)
        with open(ci_cfg_file, "w") as fh:
            fh.write(
                """
                disable_root: true
                
                preserve_hostname: true
                
                datasource:
                  Ec2:
                    metadata_urls: ["http://169.254.169.254:80"]
                    max_wait: 30
                    timeout: 30
                    apply_full_imds_network_config: true
                
                cloud_init_modules:
                 - migrator
                 - bootcmd
                 - write-files
                 - resizefs
                 - set_hostname
                 - update_hostname
                 - update_etc_hosts
                 - ca-certs
                 - ssh
                
                cloud_config_modules:
                 - mounts
                 - ssh-import-id
                 - locale
                 - set-passwords
                 - grub-dpkg
                 - apt-pipelining
                 - apt-configure
                 - package-update-upgrade-install
                 - timezone
                 - disable-ec2-metadata
                 - runcmd
                
                cloud_final_modules:
                 - rightscale_userdata
                 - scripts-per-once
                 - scripts-per-boot
                 - scripts-per-instance
                 - scripts-user
                 - ssh-authkey-fingerprints
                 - keys-to-console
                 - phone-home
                 - final-message
                 - power-state-change
                
                system_info:
                   distro: debian
                   paths:
                      cloud_dir: /var/lib/cloud/
                      templates_dir: /etc/cloud/templates/
                      upstart_dir: /etc/init/
                   package_mirrors:
                     - arches: [default]
                       failsafe:
                         primary: {deb_mirror}
                """.format(
                    deb_mirror=deb_mirror
                )
            )

        # Due to device ordering within the Libvirt XML configuration, the first Ethernet interface
        # will always be on PCI bus ID 2, hence the name "ens2".
        # Write a DHCP stanza for ens2
        ens2_network_file = "{}/etc/network/interfaces.d/ens2".format(temp_dir)
        with open(ens2_network_file, "w") as fh:
            data = """auto ens2
iface ens2 inet dhcp
"""
            fh.write(data)

        # Write the DHCP config for ens2
        dhclient_file = "{}/etc/dhcp/dhclient.conf".format(temp_dir)
        with open(dhclient_file, "w") as fh:
            # We can use fstrings too, since PVC will always have Python 3.6+, though
            # using format() might be preferable for clarity in some situations
            data = f"""# DHCP client configuration
# Written by the PVC provisioner
option rfc3442-classless-static-routes code 121 = array of unsigned integer 8;
interface "ens2" {{
        send fqdn.fqdn = "{vm_name}";
        send host-name = "{vm_name}";
        request subnet-mask, broadcast-address, time-offset, routers,
                domain-name, domain-name-servers, domain-search, host-name,
                dhcp6.name-servers, dhcp6.domain-search, dhcp6.fqdn, dhcp6.sntp-servers,
                netbios-name-servers, netbios-scope, interface-mtu,
                rfc3442-classless-static-routes, ntp-servers;
}}
"""
            fh.write(data)

        # Write the GRUB configuration
        grubcfg_file = "{}/etc/default/grub".format(temp_dir)
        with open(grubcfg_file, "w") as fh:
            data = """# Written by the PVC provisioner
GRUB_DEFAULT=0
GRUB_TIMEOUT=1
GRUB_DISTRIBUTOR="PVC Virtual Machine"
GRUB_CMDLINE_LINUX_DEFAULT="root=/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsi0-0-0-{root_volume} console=tty0 console=ttyS0,115200n8"
GRUB_CMDLINE_LINUX=""
GRUB_TERMINAL=console
GRUB_SERIAL_COMMAND="serial --speed=115200 --unit=0 --word=8 --parity=no --stop=1"
GRUB_DISABLE_LINUX_UUID=false
""".format(
                root_volume=root_volume["scsi_id"]
            )
            fh.write(data)

        # Do some tasks inside the chroot using the provided context manager
        with chroot(temp_dir):
            # Install and update GRUB
            os.system(
                "grub-install --force /dev/rbd/{}/{}_{}".format(
                    root_volume["pool"], vm_name, root_volume["disk_id"]
                )
            )
            os.system("update-grub")

            # Set a really dumb root password so the VM can be debugged
            # EITHER CHANGE THIS YOURSELF, here or in Userdata, or run something after install
            # to change the root password: don't leave it like this on an Internet-facing machine!
            os.system("echo root:test123 | chpasswd")

            # Enable cloud-init target on (first) boot
            # Your user-data should handle this and disable it once done, or things get messy.
            # That cloud-init won't run without this hack seems like a bug... but even the official
            # Debian cloud images are affected, so who knows.
            os.system("systemctl enable cloud-init.target")

    def cleanup(self):
        """
        cleanup(): Perform any cleanup required due to prepare()/install()

        It is important to now reverse *all* steps taken in those functions that might
        need cleanup before teardown of the upper chroot environment.

        This function is also called if there is ANY exception raised in the prepare()
        or install() steps. While this doesn't mean you shouldn't or can't raise exceptions
        here, be warned that doing so might cause loops. Do this only if you really need to.
        """

        # Run any imports first
        import os
        from daemon_lib.vmbuilder import open_zk
        from pvcworkerd.Daemon import config
        import daemon_lib.common as pvc_common
        import daemon_lib.ceph as pvc_ceph

        # Set the temp_dir we used in the prepare() and install() steps
        temp_dir = "/tmp/target"

        # Unmount the bound devfs
        os.system("umount {}/dev".format(temp_dir))

        # Use this construct for reversing the list, as the normal reverse() messes with the list
        for volume in list(reversed(self.vm_data["volumes"])):
            dst_volume_name = f"{self.vm_name}_{volume['disk_id']}"
            dst_volume = f"{volume['pool']}/{dst_volume_name}"
            mapped_dst_volume = f"/dev/rbd/{dst_volume}"
            mount_path = f"{temp_dir}/{volume['mountpoint']}"
            self.log_info(f"Unmounting {dst_volume} from {mount_path}")

            if (
                volume.get("source_volume") is None
                and volume.get("filesystem") is not None
                and volume.get("filesystem") != "swap"
            ):
                # Unmount filesystem
                retcode, stdout, stderr = pvc_common.run_os_command(
                    f"umount {mount_path}"
                )
                if retcode:
                    self.log_err(
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
                    self.log_err(f"Failed to unmap '{mapped_dst_volume}': {stderr}")
