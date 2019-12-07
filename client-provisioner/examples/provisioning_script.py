#!/usr/bin/env python3

# provisioing_script.py - PVC Provisioner example script
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
    except:
        deb_release = "stable"
    try:
        deb_mirror = kwargs['deb_mirror']
    except:
        deb_mirror = "http://ftp.debian.org/debian"
    try:
        deb_packages = kwargs['deb_packages'].split(',')
    except:
        deb_packages = ["linux-image-amd64", "grub-pc", "cloud-init", "python3-cffi-backend"]

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
    for disk in disks:
        # We assume SSD-based/-like storage, and dislike atimes
        options = "defaults,discard,noatime,nodiratime"

        # The root and var volumes have specific values
        if disk['mountpoint'] == "/":
            dump = 0
            cpass = 1
        elif disk['mountpoint'] == '/var':
            dump = 0
            cpass = 2
        else:
            dump = 0
            cpass = 0

        # Append the fstab line
        with open(fstab_file, 'a') as fh:
            fh.write("/dev/{disk} {mountpoint} {filesystem} {options} {dump} {cpass}\n".format(
                disk=disk['disk_id'],
                mountpoint=disk['mountpoint'],
                filesystem=disk['filesystem'],
                options=options,
                dump=dump,
                cpass=cpass
            ))

    # Write the GRUB configuration
    grubcfg_file = "{}/etc/default/grub".format(temporary_directory)
    with open(grubcfg_file, 'w') as fh:
        fh.write("""# Written by the PVC provisioner
GRUB_DEFAULT=0
GRUB_TIMEOUT=1
GRUB_DISTRIBUTOR="PVC Virtual Machine"
GRUB_CMDLINE_LINUX_DEFAULT="root=/dev/{root_disk} console=tty0 console=ttyS0,115200n8"
GRUB_CMDLINE_LINUX=""
GRUB_TERMINAL=console
GRUB_SERIAL_COMMAND="serial --speed=115200 --unit=0 --word=8 --parity=no --stop=1"
GRUB_DISABLE_LINUX_UUID=false
""".format(root_disk=root_disk['disk_id']))

    # Chroot and install GRUB so we can boot, then exit the chroot
    # EXITING THE CHROOT IS VERY IMPORTANT OR THE FOLLOWING STAGES OF THE PROVISIONER
    # WILL FAIL IN UNEXPECTED WAYS! Keep this in mind when using chroot in your scripts.
    real_root = os.open("/", os.O_RDONLY)
    os.chroot(temporary_directory)
    fake_root = os.open("/", os.O_RDONLY)
    os.fchdir(fake_root)
    os.system(
        "grub-install /dev/rbd/{}/{}_{}".format(root_disk['pool'], vm_name, root_disk['disk_id'])
    )
    os.system( 
        "update-grub"
    )
    # Restore our original root
    os.fchdir(real_root)
    os.chroot(".")
    os.fchdir(real_root)
    os.close(fake_root)
    os.close(real_root)

    # Unmount the bound devfs
    os.system(
        "umount {}/dev".format(
            temporary_directory
        )
    )

    # Everything else is done via cloud-init
