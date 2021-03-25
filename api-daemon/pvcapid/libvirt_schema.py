#!/usr/bin/env python3

# libvirt_schema.py - Libvirt schema elements
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

# File header, containing default values for various non-device components
# Variables:
#  * vm_name
#  * vm_uuid
#  * vm_description
#  * vm_memory
#  * vm_vcpus
#  * vm_architecture
libvirt_header = """<domain type='kvm'>
  <name>{vm_name}</name>
  <uuid>{vm_uuid}</uuid>
  <description>{vm_description}</description>
  <memory unit='MiB'>{vm_memory}</memory>
  <vcpu>{vm_vcpus}</vcpu>
  <cpu>
    <topology sockets='1' cores='{vm_vcpus}' threads='1'/>
  </cpu>
  <os>
    <type arch='{vm_architecture}' machine='pc-i440fx-2.7'>hvm</type>
    <bootmenu enable='yes'/>
    <boot dev='cdrom'/>
    <boot dev='hd'/>
  </os>
  <features>
    <acpi/>
    <apic/>
    <pae/>
  </features>
  <clock offset='utc'/>
  <on_poweroff>destroy</on_poweroff>
  <on_reboot>restart</on_reboot>
  <on_crash>restart</on_crash>
  <devices>
    <console type='pty'/>
"""

# File footer, closing devices and domain elements
libvirt_footer = """  </devices>
</domain>"""

# Default devices for all VMs
devices_default = """    <emulator>/usr/bin/kvm</emulator>
    <controller type='usb' index='0'/>
    <controller type='pci' index='0' model='pci-root'/>
    <rng model='virtio'>
      <rate period="1000" bytes="2048"/>
      <backend model='random'>/dev/random</backend>
    </rng>
"""

# Serial device
# Variables:
#  * vm_name
devices_serial = """    <serial type='pty'>
      <log file='/var/log/libvirt/{vm_name}.log' append='on'/>
    </serial>
"""

# VNC device
# Variables:
#  * vm_vncport
#  * vm_vnc_autoport
#  * vm_vnc_bind
devices_vnc = """    <graphics type='vnc' port='{vm_vncport}' autoport='{vm_vnc_autoport}' listen='{vm_vnc_bind}'/>
"""

# VirtIO SCSI device
devices_scsi_controller = """    <controller type='scsi' index='0' model='virtio-scsi'/>
"""

# Disk device header
# Variables:
#  * ceph_storage_secret
#  * disk_pool
#  * vm_name
#  * disk_id
devices_disk_header = """    <disk type='network' device='disk'>
      <driver name='qemu' discard='unmap'/>
      <target dev='{disk_id}' bus='scsi'/>
      <auth username='libvirt'>
        <secret type='ceph' uuid='{ceph_storage_secret}'/>
      </auth>
      <source protocol='rbd' name='{disk_pool}/{vm_name}_{disk_id}'>
"""

# Disk device coordinator element
# Variables:
#  * coordinator_name
#  * coordinator_ceph_mon_port
devices_disk_coordinator = """        <host name='{coordinator_name}' port='{coordinator_ceph_mon_port}'/>
"""

# Disk device footer
devices_disk_footer = """      </source>
    </disk>
"""

# vhostmd virtualization passthrough device
devices_vhostmd = """    <disk type='file' device='disk'>
      <driver name='qemu' type='raw'/>
      <source file='/dev/shm/vhostmd0'/>
      <target dev='sdz' bus='usb'/>
      <readonly/>
    </disk>
"""

# Network interface device
# Variables:
#  * eth_macaddr
#  * eth_bridge
devices_net_interface = """    <interface type='bridge'>
      <mac address='{eth_macaddr}'/>
      <source bridge='{eth_bridge}'/>
      <model type='virtio'/>
    </interface>
"""
