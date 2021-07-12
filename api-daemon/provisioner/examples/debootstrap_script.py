#!/usr/bin/env python3

# debootstrap_script.py - PVC Provisioner example script for Debootstrap
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2021 Joshua M. Boniface <joshua@boniface.me>
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

# This script provides an example of a PVC provisioner script. It will install
# a Debian system, of the release specified in the keyword argument `deb_release`
# and from the mirror specified in the keyword argument `deb_mirror`, and
# including the packages specified in the keyword argument `deb_packages` (a list
# of strings, which is then joined together as a CSV and passed to debootstrap),
# to the configured disks, configure fstab, and install GRUB. Any later config
# should be done within the VM, for instance via cloud-init.

# This script can thus be used as an example or reference implementation of a
# PVC provisioner script and expanded upon as required.

# This script will run under root privileges as the provisioner does. Be careful
# with that.

import os
from contextlib import contextmanager


# Create a chroot context manager
# This can be used later in the script to chroot to the destination directory
# for instance to run commands within the target.
@contextmanager
def chroot_target(destination):
    try:
        real_root = os.open("/", os.O_RDONLY)
        os.chroot(destination)
        fake_root = os.open("/", os.O_RDONLY)
        os.fchdir(fake_root)
        yield
    finally:
        os.fchdir(real_root)
        os.chroot(".")
        os.fchdir(real_root)
        os.close(fake_root)
        os.close(real_root)
        del fake_root
        del real_root


# Installation function - performs a debootstrap install of a Debian system
# Note that the only arguments are keyword arguments.
def install(**kwargs):
    # The provisioner has already mounted the disks on kwargs['temporary_directory'].
    # by this point, so we can get right to running the debootstrap after setting
    # some nicer variable names; you don't necessarily have to do this.
    vm_name = kwargs['vm_name']
    temporary_directory = kwargs['temporary_directory']
    disks = kwargs['disks']
    networks = kwargs['networks']
    # Our own required arguments. We should, though are not required to, handle
    # failures of these gracefully, should administrators forget to specify them.
    try:
        deb_release = kwargs['deb_release']
    except Exception:
        deb_release = "stable"
    try:
        deb_mirror = kwargs['deb_mirror']
    except Exception:
        deb_mirror = "http://ftp.debian.org/debian"
    try:
        deb_packages = kwargs['deb_packages'].split(',')
    except Exception:
        deb_packages = ["linux-image-amd64", "grub-pc", "cloud-init", "python3-cffi-backend", "wget"]

    # We need to know our root disk
    root_disk = None
    for disk in disks:
        if disk['mountpoint'] == '/':
            root_disk = disk
    if not root_disk:
        return

    # Ensure we have debootstrap intalled on the provisioner system; this is a
    # good idea to include if you plan to use anything that is not part of the
    # base Debian host system, just in case the provisioner host is not properly
    # configured already.
    os.system(
        "apt-get install -y debootstrap"
    )

    # Perform a deboostrap installation
    os.system(
        "debootstrap --include={pkgs} {suite} {target} {mirror}".format(
            suite=deb_release,
            target=temporary_directory,
            mirror=deb_mirror,
            pkgs=','.join(deb_packages)
        )
    )

    # Bind mount the devfs
    os.system(
        "mount --bind /dev {}/dev".format(
            temporary_directory
        )
    )

    # Create an fstab entry for each disk
    fstab_file = "{}/etc/fstab".format(temporary_directory)
    # The disk ID starts at zero and increments by one for each disk in the fixed-order
    # disk list. This lets us work around the insanity of Libvirt IDs not matching guest IDs,
    # while still letting us have some semblance of control here without enforcing things
    # like labels. It increments in the for loop below at the end of each iteration, and is
    # used to craft a /dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsi0-0-0-X device ID
    # which will always match the correct order from Libvirt (unlike sdX/vdX names).
    disk_id = 0
    for disk in disks:
        # We assume SSD-based/-like storage, and dislike atimes
        options = "defaults,discard,noatime,nodiratime"

        # The root, var, and log volumes have specific values
        if disk['mountpoint'] == "/":
            root_disk['scsi_id'] = disk_id
            dump = 0
            cpass = 1
        elif disk['mountpoint'] == '/var' or disk['mountpoint'] == '/var/log':
            dump = 0
            cpass = 2
        else:
            dump = 0
            cpass = 0

        # Append the fstab line
        with open(fstab_file, 'a') as fh:
            data = "/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsi0-0-0-{disk} {mountpoint} {filesystem} {options} {dump} {cpass}\n".format(
                disk=disk_id,
                mountpoint=disk['mountpoint'],
                filesystem=disk['filesystem'],
                options=options,
                dump=dump,
                cpass=cpass
            )
            fh.write(data)

        # Increment the disk_id
        disk_id += 1

    # Write the hostname
    hostname_file = "{}/etc/hostname".format(temporary_directory)
    with open(hostname_file, 'w') as fh:
        fh.write("{}".format(vm_name))

    # Fix the cloud-init.target since it's broken
    cloudinit_target_file = "{}/etc/systemd/system/cloud-init.target".format(temporary_directory)
    with open(cloudinit_target_file, 'w') as fh:
        data = """[Install]
WantedBy=multi-user.target
[Unit]
Description=Cloud-init target
After=multi-user.target
"""
        fh.write(data)

    # NOTE: Due to device ordering within the Libvirt XML configuration, the first Ethernet interface
    #       will always be on PCI bus ID 2, hence the name "ens2".
    # Write a DHCP stanza for ens2
    ens2_network_file = "{}/etc/network/interfaces.d/ens2".format(temporary_directory)
    with open(ens2_network_file, 'w') as fh:
        data = """auto ens2
iface ens2 inet dhcp
"""
        fh.write(data)

    # Write the DHCP config for ens2
    dhclient_file = "{}/etc/dhcp/dhclient.conf".format(temporary_directory)
    with open(dhclient_file, 'w') as fh:
        data = """# DHCP client configuration
# Written by the PVC provisioner
option rfc3442-classless-static-routes code 121 = array of unsigned integer 8;
interface "ens2" {
""" + """        send fqdn.fqdn = "{hostname}";
        send host-name = "{hostname}";
""".format(hostname=vm_name) + """        request subnet-mask, broadcast-address, time-offset, routers,
                domain-name, domain-name-servers, domain-search, host-name,
                dhcp6.name-servers, dhcp6.domain-search, dhcp6.fqdn, dhcp6.sntp-servers,
                netbios-name-servers, netbios-scope, interface-mtu,
                rfc3442-classless-static-routes, ntp-servers;
}
"""
        fh.write(data)

    # Write the GRUB configuration
    grubcfg_file = "{}/etc/default/grub".format(temporary_directory)
    with open(grubcfg_file, 'w') as fh:
        data = """# Written by the PVC provisioner
GRUB_DEFAULT=0
GRUB_TIMEOUT=1
GRUB_DISTRIBUTOR="PVC Virtual Machine"
GRUB_CMDLINE_LINUX_DEFAULT="root=/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsi0-0-0-{root_disk} console=tty0 console=ttyS0,115200n8"
GRUB_CMDLINE_LINUX=""
GRUB_TERMINAL=console
GRUB_SERIAL_COMMAND="serial --speed=115200 --unit=0 --word=8 --parity=no --stop=1"
GRUB_DISABLE_LINUX_UUID=false
""".format(root_disk=root_disk['scsi_id'])
        fh.write(data)

    # Chroot, do some in-root tasks, then exit the chroot
    with chroot_target(temporary_directory):
        # Install and update GRUB
        os.system(
            "grub-install --force /dev/rbd/{}/{}_{}".format(root_disk['pool'], vm_name, root_disk['disk_id'])
        )
        os.system(
            "update-grub"
        )
        # Set a really dumb root password [TEMPORARY]
        os.system(
            "echo root:test123 | chpasswd"
        )
        # Enable cloud-init target on (first) boot
        # NOTE: Your user-data should handle this and disable it once done, or things get messy.
        #       That cloud-init won't run without this hack seems like a bug... but even the official
        #       Debian cloud images are affected, so who knows.
        os.system(
            "systemctl enable cloud-init.target"
        )

    # Unmount the bound devfs
    os.system(
        "umount {}/dev".format(
            temporary_directory
        )
    )

    # Everything else is done via cloud-init user-data
