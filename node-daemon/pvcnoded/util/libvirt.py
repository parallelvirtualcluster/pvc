#!/usr/bin/env python3

# libvirt.py - Utility functions for pvcnoded libvirt
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

import libvirt


def validate_libvirtd(logger, config):
    if config["enable_hypervisor"]:
        libvirt_check_name = f'qemu+tcp://{config["node_hostname"]}/system'
        logger.out(f"Connecting to Libvirt daemon at {libvirt_check_name}", state="i")
        try:
            lv_conn = libvirt.open(libvirt_check_name)
            lv_conn.close()
        except Exception as e:
            logger.out(f"Failed to connect to Libvirt daemon: {e}", state="e")
            return False

    return True
