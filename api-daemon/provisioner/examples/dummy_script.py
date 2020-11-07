#!/usr/bin/env python3

# dummy_script.py - PVC Provisioner example script for noop
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

# This script provides an example of a PVC provisioner script. It will do
# nothing and return back to the provisioner without taking any action, and
# expecting no special arguments.

# This script can thus be used as an example or reference implementation of a
# PVC provisioner script and expanded upon as required.

# This script will run under root privileges as the provisioner does. Be careful
# with that.

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
    # No operation - this script just returns
    pass
