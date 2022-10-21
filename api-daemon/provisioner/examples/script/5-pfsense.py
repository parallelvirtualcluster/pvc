#!/usr/bin/env python3

# 6-pfsense.py - PVC Provisioner example script for pfSense install
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
# standard VM config, download and configure pfSense with Packer, and then copy
# the resulting raw disk image into the first RBD volume ready for first boot.
#
# This script has 4 custom arguments and will error if they are not properly configured:
#   pfsense_wan_iface: the (internal) interface name for the WAN, usually "vtnet0" or similar
#   pfsense_wan_dhcp: if set to any value (even empty), will use DHCP for the WAN interface
#                     and obsolete the following arguments
#   pfsense_wan_address: the static IPv4 address (including CIDR netmask) of the WAN interface
#   pfsense_wan_gateway: the default gateway IPv4 address of the WAN interface
#
# In addition, the following standard arguments can be utilized:
#   vm_fqdn: Sets an FQDN (hostname + domain); if unspecified, defaults to `vm_name` as the
#            hostname with no domain set.
#
# The resulting pfSense instance will use the default "root"/"pfsense" credentials and
# will support both serial and VNC interfaces; boot messages will only show on serial.
# SLAAC will be used for IPv6 on WAN in addition to the specified IPv4 configuration.
# A set of default-permit rules on the WAN interface are included to allow management on the
# WAN side, and these should be modified or removed once the system is configured.
# Finally, the Web Configurator is set to use HTTP only.
#
# Other than the above specified values, the new pfSense instance will be completely
# unconfigured and must then be adjusted as needed via the Web Configurator ASAP to ensure
# the system is not compromised.
#
# NOTE: Due to the nature of the Packer provisioning, this script will use approximately
#       2GB of RAM for tmpfs during the provisioning. Be careful on heavily-loaded nodes.

# This script can thus be used as an example or reference implementation of a
# PVC provisioner script and expanded upon as required.
# *** READ THIS SCRIPT THOROUGHLY BEFORE USING TO UNDERSTAND HOW IT WORKS. ***

# A script must implement the class "VMBuilderScript" which extends "VMBuilder",
# providing the 5 functions indicated. Detailed explanation of the role of each
# function is provided in context of the example; see the other examples for
# more potential uses.

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


# This import is always required here, as VMBuilder is used by the VMBuilderScript class
# and ProvisioningError is the primary exception that should be raised within the class.
from pvcapid.vmbuilder import VMBuilder, ProvisioningError


# Set up some variables for later; if you frequently use these tools, you might benefit from
# a local mirror, or store them on the hypervisor and adjust the prepare() tasks to use
# those local copies instead.
PACKER_VERSION = "1.8.2"
PACKER_URL = f"https://releases.hashicorp.com/packer/{PACKER_VERSION}/packer_{PACKER_VERSION}_linux_amd64.zip"
PFSENSE_VERSION = "2.5.2"
PFSENSE_ISO_URL = f"https://atxfiles.netgate.com/mirror/downloads/pfSense-CE-{PFSENSE_VERSION}-RELEASE-amd64.iso.gz"


# The VMBuilderScript class must be named as such, and extend VMBuilder.
class VMBuilderScript(VMBuilder):
    def setup(self):
        """
        setup(): Perform special setup steps or validation before proceeding

        Fetches Packer and the pfSense installer ISO, and prepares the Packer config.
        """

        # Run any imports first; as shown here, you can import anything from the PVC
        # namespace, as well as (of course) the main Python namespaces
        import daemon_lib.common as pvc_common
        import os

        # Ensure that our required runtime variables are defined

        if self.vm_data["script_arguments"].get("pfsense_wan_iface") is None:
            raise ProvisioningError(
                "Required script argument 'pfsense_wan_iface' not provided"
            )

        if self.vm_data["script_arguments"].get("pfsense_wan_dhcp") is None:
            for argument in [
                "pfsense_wan_address",
                "pfsense_wan_gateway",
            ]:
                if self.vm_data["script_arguments"].get(argument) is None:
                    raise ProvisioningError(
                        f"Required script argument '{argument}' not provided"
                    )

        # Ensure we have all dependencies intalled on the provisioner system
        for dependency in "wget", "unzip", "gzip":
            retcode, stdout, stderr = pvc_common.run_os_command(f"which {dependency}")
            if retcode:
                # Raise a ProvisioningError for any exception; the provisioner will handle
                # this gracefully and properly, avoiding dangling mounts, RBD maps, etc.
                raise ProvisioningError(
                    f"Failed to find critical dependency: {dependency}"
                )

        # Create a temporary directory to use for Packer binaries/scripts
        packer_temp_dir = "/tmp/packer"

        if not os.path.isdir(packer_temp_dir):
            os.mkdir(f"{packer_temp_dir}")
            os.mkdir(f"{packer_temp_dir}/http")
            os.mkdir(f"{packer_temp_dir}/dl")

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
        import pvcapid.libvirt_schema as libvirt_schema
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

        # Run any imports first; as shown here, you can import anything from the PVC
        # namespace, as well as (of course) the main Python namespaces
        from pvcapid.vmbuilder import open_zk
        from pvcapid.Daemon import config
        import daemon_lib.common as pvc_common
        import daemon_lib.ceph as pvc_ceph
        import json
        import os

        packer_temp_dir = "/tmp/packer"

        # Download pfSense image file to temporary target directory
        print(f"Downloading pfSense ISO image from {PFSENSE_ISO_URL}")
        retcode, stdout, stderr = pvc_common.run_os_command(
            f"wget --output-document={packer_temp_dir}/dl/pfsense.iso.gz {PFSENSE_ISO_URL}"
        )
        if retcode:
            raise ProvisioningError(
                f"Failed to download pfSense image from {PFSENSE_ISO_URL}"
            )

        # Extract pfSense image file under temporary target directory
        print(f"Extracting pfSense ISO image")
        retcode, stdout, stderr = pvc_common.run_os_command(
            f"gzip --decompress {packer_temp_dir}/dl/pfsense.iso.gz"
        )
        if retcode:
            raise ProvisioningError("Failed to extract pfSense ISO image")

        # Download Packer to temporary target directory
        print(f"Downloading Packer from {PACKER_URL}")
        retcode, stdout, stderr = pvc_common.run_os_command(
            f"wget --output-document={packer_temp_dir}/packer.zip {PACKER_URL}"
        )
        if retcode:
            raise ProvisioningError(f"Failed to download Packer from {PACKER_URL}")

        # Extract Packer under temporary target directory
        print(f"Extracting Packer binary")
        retcode, stdout, stderr = pvc_common.run_os_command(
            f"unzip {packer_temp_dir}/packer.zip -d {packer_temp_dir}"
        )
        if retcode:
            raise ProvisioningError("Failed to extract Packer binary")

        # Output the Packer configuration
        print(f"Generating Packer configurations")
        first_volume = self.vm_data["volumes"][0]
        first_volume_size_mb = int(first_volume["disk_size_gb"]) * 1024

        builder = {
            "builders": [
                {
                    "type": "qemu",
                    "vm_name": self.vm_name,
                    "accelerator": "kvm",
                    "memory": 1024,
                    "headless": True,
                    "disk_interface": "virtio",
                    "disk_size": first_volume_size_mb,
                    "format": "raw",
                    "net_device": "virtio-net",
                    "communicator": "none",
                    "http_port_min": "8100",
                    "http_directory": f"{packer_temp_dir}/http",
                    "output_directory": f"{packer_temp_dir}/bin",
                    "iso_urls": [f"{packer_temp_dir}/dl/pfsense.iso"],
                    "iso_checksum": "none",
                    "boot_wait": "3s",
                    "boot_command": [
                        "1",
                        "<wait90>",
                        # Run through the installer
                        "<enter>",
                        "<wait1>",
                        "<enter>",
                        "<wait1>",
                        "<enter>",
                        "<wait1>",
                        "<enter>",
                        "<wait1>",
                        "<enter>",
                        "<wait1>",
                        "<enter>",
                        "<wait1>",
                        "<spacebar><enter>",
                        "<wait1>",
                        "<left><enter>",
                        "<wait120>",
                        "<enter>",
                        "<wait1>",
                        # Enter shell
                        "<right><enter>",
                        # Set up serial console
                        "<wait1>",
                        "echo '-S115200 -D' | tee /mnt/boot.config<enter>",
                        "<wait1>",
                        'sed -i.bak \'s/boot_serial="NO"/boot_serial="YES"/\' /mnt/boot/loader.conf<enter>',
                        "<wait1>",
                        "echo 'boot_multicons=\"YES\"' >> /mnt/boot/loader.conf<enter>",
                        "<wait1>",
                        "echo 'console=\"comconsole,vidconsole\"' >> /mnt/boot/loader.conf<enter>",
                        "<wait1>",
                        "echo 'comconsole_speed=\"115200\"' >> /mnt/boot/loader.conf<enter>",
                        "<wait1>",
                        "sed -i.bak '/^ttyu/s/off/on/' /mnt/etc/ttys<enter>",
                        "<wait1>",
                        # Grab template configuration from provisioner
                        # We have to do DHCP first, then do the telnet fetch inside a chroot
                        "dhclient vtnet0<enter>",
                        "<wait5>"
                        "chroot /mnt<enter>"
                        "<wait1>"
                        "telnet {{ .HTTPIP }} {{ .HTTPPort }} | sed '1,/^$/d' | tee /cf/conf/config.xml<enter>",
                        "GET /config.xml HTTP/1.0<enter><enter>",
                        "<wait1>",
                        "passwd root<enter>",
                        "opnsense<enter>",
                        "opnsense<enter>",
                        "<wait1>",
                        "exit<enter>",
                        "<wait1>"
                        # Shut down to complete provisioning
                        "poweroff<enter>",
                    ],
                }
            ],
            "provisioners": [],
            "post-processors": [],
        }

        with open(f"{packer_temp_dir}/build.json", "w") as fh:
            json.dump(builder, fh)

        # Set the hostname and domain if vm_fqdn is set
        if self.vm_data["script_arguments"].get("vm_fqdn") is not None:
            pfsense_hostname = self.vm_data["script_arguments"]["vm_fqdn"].split(".")[0]
            pfsense_domain = ".".join(
                self.vm_data["script_arguments"]["vm_fqdn"].split(".")[1:]
            )
        else:
            pfsense_hostname = self.vm_name
            pfsense_domain = ""

        # Output the pfSense configuration
        # This is a default configuration with the serial console enabled and with our WAN
        # interface pre-configured via the provided script arguments.
        pfsense_config = """<?xml version="1.0"?>
<pfsense>
       <version>21.7</version>
       <lastchange></lastchange>
       <system>
              <optimization>normal</optimization>
              <hostname>{pfsense_hostname}</hostname>
              <domain>{pfsense_domain}</domain>
              <dnsserver></dnsserver>
              <dnsallowoverride></dnsallowoverride>
              <group>
                     <name>all</name>
                     <description><![CDATA[All Users]]></description>
                     <scope>system</scope>
                     <gid>1998</gid>
                     <member>0</member>
              </group>
              <group>
                     <name>admins</name>
                     <description><![CDATA[System Administrators]]></description>
                     <scope>system</scope>
                     <gid>1999</gid>
                     <member>0</member>
                     <priv>page-all</priv>
              </group>
              <user>
                     <name>admin</name>
                     <descr><![CDATA[System Administrator]]></descr>
                     <scope>system</scope>
                     <groupname>admins</groupname>
                     <bcrypt-hash>$2b$10$13u6qwCOwODv34GyCMgdWub6oQF3RX0rG7c3d3X4JvzuEmAXLYDd2</bcrypt-hash>
                     <uid>0</uid>
                     <priv>user-shell-access</priv>
              </user>
              <nextuid>2000</nextuid>
              <nextgid>2000</nextgid>
              <timeservers>2.pfsense.pool.ntp.org</timeservers>
              <webgui>
                     <protocol>http</protocol>
                     <loginautocomplete></loginautocomplete>
                     <port></port>
                     <max_procs>2</max_procs>
              </webgui>
              <disablenatreflection>yes</disablenatreflection>
              <disablesegmentationoffloading></disablesegmentationoffloading>
              <disablelargereceiveoffloading></disablelargereceiveoffloading>
              <ipv6allow></ipv6allow>
              <maximumtableentries>400000</maximumtableentries>
              <powerd_ac_mode>hadp</powerd_ac_mode>
              <powerd_battery_mode>hadp</powerd_battery_mode>
              <powerd_normal_mode>hadp</powerd_normal_mode>
              <bogons>
                     <interval>monthly</interval>
              </bogons>
              <hn_altq_enable></hn_altq_enable>
              <already_run_config_upgrade></already_run_config_upgrade>
              <ssh>
                     <enable>enabled</enable>
              </ssh>
              <enableserial></enableserial>
              <serialspeed>115200</serialspeed>
              <primaryconsole>serial</primaryconsole>
              <sshguard_threshold></sshguard_threshold>
              <sshguard_blocktime></sshguard_blocktime>
              <sshguard_detection_time></sshguard_detection_time>
              <sshguard_whitelist></sshguard_whitelist>
       </system>
""".format(
            pfsense_hostname=pfsense_hostname,
            pfsense_domain=pfsense_domain,
        )

        if self.vm_data["script_arguments"].get("pfsense_wan_dhcp") is not None:
            pfsense_config += """
       <interfaces>
              <wan>
                     <enable></enable>
                     <if>{wan_iface}</if>
                     <mtu></mtu>
                     <ipaddr>dhcp</ipaddr>
                     <ipaddrv6>slaac</ipaddrv6>
                     <subnet></subnet>
                     <gateway></gateway>
                     <blockbogons></blockbogons>
                     <dhcphostname></dhcphostname>
                     <media></media>
                     <mediaopt></mediaopt>
                     <dhcp6-duid></dhcp6-duid>
                     <dhcp6-ia-pd-len>0</dhcp6-ia-pd-len>
              </wan>
       </interfaces>
       <gateways>
       </gateways>
""".format(
                wan_iface=self.vm_data["script_arguments"]["pfsense_wan_iface"],
            )
        else:
            pfsense_config += """
       <interfaces>
              <wan>
                     <enable></enable>
                     <if>{wan_iface}</if>
                     <mtu></mtu>
                     <ipaddr>{wan_ipaddr}</ipaddr>
                     <ipaddrv6>slaac</ipaddrv6>
                     <subnet>{wan_netmask}</subnet>
                     <gateway>WAN</gateway>
                     <blockbogons></blockbogons>
                     <dhcphostname></dhcphostname>
                     <media></media>
                     <mediaopt></mediaopt>
                     <dhcp6-duid></dhcp6-duid>
                     <dhcp6-ia-pd-len>0</dhcp6-ia-pd-len>
              </wan>
       </interfaces>
       <gateways>
              <gateway_item>
                     <interface>wan</interface>
                     <gateway>{wan_gateway}</gateway>
                     <name>WAN</name>
                     <weight>1</weight>
                     <ipprotocol>inet</ipprotocol>
                     <descr/>
              </gateway_item>
       </gateways>
""".format(
                wan_iface=self.vm_data["script_arguments"]["pfsense_wan_iface"],
                wan_ipaddr=self.vm_data["script_arguments"][
                    "pfsense_wan_address"
                ].split("/")[0],
                wan_netmask=self.vm_data["script_arguments"][
                    "pfsense_wan_address"
                ].split("/")[1],
                wan_gateway=self.vm_data["script_arguments"]["pfsense_wan_gateway"],
            )

        pfsense_config += """
       <staticroutes></staticroutes>
       <dhcpd></dhcpd>
       <dhcpdv6></dhcpdv6>
       <snmpd>
              <syslocation></syslocation>
              <syscontact></syscontact>
              <rocommunity>public</rocommunity>
       </snmpd>
       <diag>
              <ipv6nat>
                     <ipaddr></ipaddr>
              </ipv6nat>
       </diag>
       <syslog>
              <filterdescriptions>1</filterdescriptions>
       </syslog>
       <filter>
              <rule>
                     <type>pass</type>
                     <ipprotocol>inet</ipprotocol>
                     <descr><![CDATA[Default allow LAN to any rule]]></descr>
                     <interface>lan</interface>
                     <tracker>0100000101</tracker>
                     <source>
                            <network>lan</network>
                     </source>
                     <destination>
                            <any></any>
                     </destination>
              </rule>
              <rule>
                     <type>pass</type>
                     <ipprotocol>inet6</ipprotocol>
                     <descr><![CDATA[Default allow LAN IPv6 to any rule]]></descr>
                     <interface>lan</interface>
                     <tracker>0100000102</tracker>
                     <source>
                            <network>lan</network>
                     </source>
                     <destination>
                            <any></any>
                     </destination>
              </rule>
              <rule>
                     <type>pass</type>
                     <ipprotocol>inet</ipprotocol>
                     <descr><![CDATA[Default allow WAN to any rule - REMOVE ME AFTER CREATING LAN/OTHER WAN RULES]]></descr>
                     <interface>wan</interface>
                     <tracker>0100000103</tracker>
                     <source>
                            <network>wan</network>
                     </source>
                     <destination>
                            <any></any>
                     </destination>
              </rule>
              <rule>
                     <type>pass</type>
                     <ipprotocol>inet6</ipprotocol>
                     <descr><![CDATA[Default allow WAN IPv6 to any rule - REMOVE ME AFTER CREATING LAN/OTHER WAN RULES]]></descr>
                     <interface>wan</interface>
                     <tracker>0100000104</tracker>
                     <source>
                            <network>wan</network>
                     </source>
                     <destination>
                            <any></any>
                     </destination>
              </rule>
       </filter>
       <ipsec>
              <vtimaps></vtimaps>
       </ipsec>
       <aliases></aliases>
       <proxyarp></proxyarp>
       <cron>
              <item>
                     <minute>*/1</minute>
                     <hour>*</hour>
                     <mday>*</mday>
                     <month>*</month>
                     <wday>*</wday>
                     <who>root</who>
                     <command>/usr/sbin/newsyslog</command>
              </item>
              <item>
                     <minute>1</minute>
                     <hour>3</hour>
                     <mday>*</mday>
                     <month>*</month>
                     <wday>*</wday>
                     <who>root</who>
                     <command>/etc/rc.periodic daily</command>
              </item>
              <item>
                     <minute>15</minute>
                     <hour>4</hour>
                     <mday>*</mday>
                     <month>*</month>
                     <wday>6</wday>
                     <who>root</who>
                     <command>/etc/rc.periodic weekly</command>
              </item>
              <item>
                     <minute>30</minute>
                     <hour>5</hour>
                     <mday>1</mday>
                     <month>*</month>
                     <wday>*</wday>
                     <who>root</who>
                     <command>/etc/rc.periodic monthly</command>
              </item>
              <item>
                     <minute>1,31</minute>
                     <hour>0-5</hour>
                     <mday>*</mday>
                     <month>*</month>
                     <wday>*</wday>
                     <who>root</who>
                     <command>/usr/bin/nice -n20 adjkerntz -a</command>
              </item>
              <item>
                     <minute>1</minute>
                     <hour>3</hour>
                     <mday>1</mday>
                     <month>*</month>
                     <wday>*</wday>
                     <who>root</who>
                     <command>/usr/bin/nice -n20 /etc/rc.update_bogons.sh</command>
              </item>
              <item>
                     <minute>1</minute>
                     <hour>1</hour>
                     <mday>*</mday>
                     <month>*</month>
                     <wday>*</wday>
                     <who>root</who>
                     <command>/usr/bin/nice -n20 /etc/rc.dyndns.update</command>
              </item>
              <item>
                     <minute>*/60</minute>
                     <hour>*</hour>
                     <mday>*</mday>
                     <month>*</month>
                     <wday>*</wday>
                     <who>root</who>
                     <command>/usr/bin/nice -n20 /usr/local/sbin/expiretable -v -t 3600 virusprot</command>
              </item>
              <item>
                     <minute>30</minute>
                     <hour>12</hour>
                     <mday>*</mday>
                     <month>*</month>
                     <wday>*</wday>
                     <who>root</who>
                     <command>/usr/bin/nice -n20 /etc/rc.update_urltables</command>
              </item>
              <item>
                     <minute>1</minute>
                     <hour>0</hour>
                     <mday>*</mday>
                     <month>*</month>
                     <wday>*</wday>
                     <who>root</who>
                     <command>/usr/bin/nice -n20 /etc/rc.update_pkg_metadata</command>
              </item>
       </cron>
       <wol></wol>
       <rrd>
              <enable></enable>
       </rrd>
       <widgets>
              <sequence>system_information:col1:show,netgate_services_and_support:col2:show,interfaces:col2:show</sequence>
              <period>10</period>
       </widgets>
       <openvpn></openvpn>
       <dnshaper></dnshaper>
       <unbound>
              <enable></enable>
              <dnssec></dnssec>
              <active_interface></active_interface>
              <outgoing_interface></outgoing_interface>
              <custom_options></custom_options>
              <hideidentity></hideidentity>
              <hideversion></hideversion>
              <dnssecstripped></dnssecstripped>
       </unbound>
       <ppps></ppps>
       <shaper></shaper>
</pfsense>
"""

        with open(f"{packer_temp_dir}/http/config.xml", "w") as fh:
            fh.write(pfsense_config)

        # Create the disk(s)
        print(f"Creating volumes")
        for volume in self.vm_data["volumes"]:
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

        # Map the target RBD volumes
        print(f"Mapping volumes")
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
                if not success:
                    raise ProvisioningError(f"Failed to map volume '{dst_volume}'.")

    def install(self):
        """
        install(): Perform the installation
        """

        # Run any imports first
        import os
        import time

        packer_temp_dir = "/tmp/packer"

        print(
            f"Running Packer: PACKER_LOG=1 PACKER_CONFIG_DIR={packer_temp_dir} PACKER_CACHE_DIR={packer_temp_dir} {packer_temp_dir}/packer build {packer_temp_dir}/build.json"
        )
        os.system(
            f"PACKER_LOG=1 PACKER_CONFIG_DIR={packer_temp_dir} PACKER_CACHE_DIR={packer_temp_dir} {packer_temp_dir}/packer build {packer_temp_dir}/build.json"
        )

        if not os.path.exists(f"{packer_temp_dir}/bin/{self.vm_name}"):
            raise ProvisioningError("Packer failed to build output image")

        print("Copying output image to first volume")
        first_volume = self.vm_data["volumes"][0]
        dst_volume_name = f"{self.vm_name}_{first_volume['disk_id']}"
        dst_volume = f"{first_volume['pool']}/{dst_volume_name}"
        os.system(
            f"dd if={packer_temp_dir}/bin/{self.vm_name} of=/dev/rbd/{dst_volume} bs=1M status=progress"
        )

    def cleanup(self):
        """
        cleanup(): Perform any cleanup required due to prepare()/install()

        This function is also called if there is ANY exception raised in the prepare()
        or install() steps. While this doesn't mean you shouldn't or can't raise exceptions
        here, be warned that doing so might cause loops. Do this only if you really need to.
        """

        # Run any imports first
        from pvcapid.vmbuilder import open_zk
        from pvcapid.Daemon import config
        import daemon_lib.ceph as pvc_ceph

        # Use this construct for reversing the list, as the normal reverse() messes with the list
        for volume in list(reversed(self.vm_data["volumes"])):
            dst_volume_name = f"{self.vm_name}_{volume['disk_id']}"
            dst_volume = f"{volume['pool']}/{dst_volume_name}"
            mapped_dst_volume = f"/dev/rbd/{dst_volume}"

            # Unmap volume
            with open_zk(config) as zkhandler:
                success, message = pvc_ceph.unmap_volume(
                    zkhandler,
                    volume["pool"],
                    dst_volume_name,
                )
