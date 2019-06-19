#!/usr/bin/env python3

# pvcd.py - PVC client command-line interface
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018  Joshua M. Boniface <joshua@boniface.me>
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

import locale
import socket
import click
import tempfile
import sys
import os
import tempfile
import subprocess
import difflib
import re
import yaml
import colorama
import netifaces
import ipaddress
import urllib.request
import tarfile

from dialog import Dialog

import client_lib.common as pvc_common
import client_lib.node as pvc_node


# Repository configurations
#deb_mirror = "ftp.debian.org"
deb_mirror = "deb1.i.bonilan.net:3142"
deb_release = "buster"
deb_arch = "amd64"
deb_packages = "mdadm,lvm2,parted,gdisk,debootstrap,grub-pc,linux-image-amd64"

# Scripts
cluster_floating_ip = "10.10.1.254"
bootstrap_script = """#!/bin/bash
# Check in and get our nodename, pvcd.conf, and install script
output="$( curl {}:10080/node_checkin )"
# Export node_id
node_id="$( jq -r '.node_id' <<<"${output}" )"
export node_id
# Export pvcd.conf
pvcd_conf="$( jq -r '.pvcd_conf' <<<"${output}" )"
export pvcd_conf
# Execute install script
jq -r '.install_script' <<<"${output}" | bash
"""
install_script = """#!/bin/bash
#
"""


# Run a oneshot command, optionally without blocking
def run_os_command(command_string, environment=None):
    command = command_string.split()
    try:
        command_output = subprocess.run(
            command,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
       return 1, "", ""

    retcode = command_output.returncode
    try:
        stdout = command_output.stdout.decode('ascii')
    except:
        stdout = ''
    try:
        stderr = command_output.stderr.decode('ascii')
    except:
        stderr = ''
    return retcode, stdout, stderr


# Start the initalization of a new cluster
def orun():
    locale.setlocale(locale.LC_ALL, '')

    # You may want to use 'autowidgetsize=True' here (requires pythondialog >= 3.1)
    d = Dialog(dialog="dialog", autowidgetsize=True)
    de = Dialog(dialog="dialog", autowidgetsize=True)
    # Dialog.set_background_title() requires pythondialog 2.13 or later
    d.set_background_title("PVC Cluster Initialization")

    # Initial message
    d.msgbox("""Welcome to the PVC cluster initalization tool. This tool
will ask you several questions about the cluster, and then
perform the required tasks to bootstrap the cluster.

PLEASE READ ALL SCREENS CAREFULLY.

Before proceeding, ensure that:
(a) This system is connected, wired if possible, to a switch.
(b) This system has a second network connection with Internet
    connectivity and is able to download files.
(c) The initial nodes are powered off, connected to the 
    mentioned switch, and are configured to boot from PXE.
(d) All non-system disks are disconnected from all nodes.
    Storage disks will be added after bootstrapping.

Once these prerequisites are complete, press Enter to proceed.
""")

    #
    # Phase 0 - get our local interface
    #
    interfaces = netifaces.interfaces()
    interface_list = list()
    for idx, val in enumerate(interfaces):
        interface_list.append(("{}".format(idx), "{}".format(val)))
    code, index = d.menu("""Select a network interface to use for cluster bootstrapping.""",
        choices=interface_list)
    if code == d.CANCEL:
        print("Aborted.")
        exit(0)
    interface = interfaces[int(index)]

    #
    # Phase 1 - coordinator list
    #
    code, coordinator_count = d.menu("Select the number of initial (coordinator) nodes:",
        choices=[("1", "Testing and very small non-redundant deployments"),
                 ("3", "Standard (3-20) hypervisor deployments"),
                 ("5", "Large (21-99) hypervisor deployments")])
    coordinator_count = int(coordinator_count)
    if code == d.CANCEL:
        print("Aborted.")
        exit(0)

    #
    # Phase 2 - Get the networks
    #
    d.msgbox("""The next screens will ask for the cluster networks in CIDR
format as well as a floating IP in each. The networks are:
(a) Cluster: Used by the nodes to communicate VXLANs and
    pass virtualization (migration) traffic between each
    other. Each node will be assigned an address in this
    network equal to its node ID (e.g. node1 at .1, etc.).
    Each node with IPMI support will be assigned an IPMI
    address in this network equal to its node ID plus 120
    (e.g. node1-lom at .121, etc.). IPs 241-254 will be
    reserved for cluster management; the floating IP should
    be in this range.
(b) Storage: Used by the nodes to pass storage traffic
    between each other, both for Ceph OSDs and for RBD
    access. Each node will be assigned an address in this
    network equal to its node ID. IPs 241-254 will be
    reserved for cluster management; the floating IP should
    be in this range.
(c) Upstream: Used by the nodes to communicate upstream
    outside of the cluster. This network has several
    functions depending on the configuration of the
    virtual networks; relevant questions will be asked
    later in the configuration.
* The first two networks are dedicated to the cluster. They
should be RFC1918 private networks and be sized sufficiently
for the future growth of the cluster; a /24 is recommended
for most situations and will support up to 99 nodes.
* The third network, as mentioned, has several potential
functions depending on the final network configuration of the
cluster. It should already exist, and nodes may or may not
have individual addresses in this network. Further questions
about this network will be asked later during setup.
* All networks should have a DNS domain which will be asked
during this stage. For the first two networks, the domain
may be private and unresolvable outside the network if
desired; the third should be a valid but will generally
be unused in the administration of the cluster. The FQDNs
of each node will contain the Cluster domain.
""")

    # Get the primary cluster network
    valid_network = False
    message = "Enter the new cluster's primary network in CIDR format."
    while not valid_network:
        code, network = d.inputbox(message)
        if code == d.CANCEL:
            print("Aborted.")
            exit(0)
        try:
            cluster_network = ipaddress.ip_network(network) 
            valid_network = True
        except ValueError:
            message = "Error - network {} is not valid.\n\nEnter the new cluster's primary network in CIDR format.".format(network)
            continue

    valid_address = False
    message = "Enter the CIDR floating IP address for the cluster's primary network."
    while not valid_address:
        code, address = d.inputbox(message)
        if code == d.CANCEL:
            print("Aborted.")
            exit (0)
        try:
            cluster_floating_ip = ipaddress.ip_address(address)
            if not cluster_floating_ip in list(cluster_network.hosts()):
                message = "Error - address {} is not in network {}.\n\nEnter the CIDR floating IP address for the cluster's primary network.".format(cluster_floating_ip, cluster_network)
                continue
            valid_address = True
        except ValueError:
            message = "Error - address {} is not valid.\n\nEnter the CIDR floating IP address for the cluster's primary network.".format(cluster_floating_ip, cluster_network)
            continue

    code, cluster_domain = d.inputbox("""Enter the new cluster's primary DNS domain.""")
    if code == d.CANCEL:
        print("Aborted.")
        exit(0)

    # Get the storage network
    valid_network = False
    message = "Enter the new cluster's storage network in CIDR format."
    while not valid_network:
        code, network = d.inputbox(message)
        if code == d.CANCEL:
            print("Aborted.")
            exit(0)
        try:
            storage_network = ipaddress.ip_network(network) 
            valid_network = True
        except ValueError:
            message = "Error - network {} is not valid.\n\nEnter the new cluster's storage network in CIDR format.".format(network)
            continue

    valid_address = False
    message = "Enter the CIDR floating IP address for the cluster's storage network."
    while not valid_address:
        code, address = d.inputbox(message)
        if code == d.CANCEL:
            print("Aborted.")
            exit (0)
        try:
            storage_floating_ip = ipaddress.ip_address(address)
            if not storage_floating_ip in list(storage_network.hosts()):
                message = "Error - address {} is not in network {}.\n\nEnter the CIDR floating IP address for the cluster's storage network.".format(storage_floating_ip, storage_network)
                continue
            valid_address = True
        except ValueError:
            message = "Error - address {} is not valid.\n\nEnter the CIDR floating IP address for the cluster's storage network.".format(storage_floating_ip, storage_network)
            continue

    code, storage_domain = d.inputbox("""Enter the new cluster's storage DNS domain.""")
    if code == d.CANCEL:
        print("Aborted.")
        exit(0)

    # Get the upstream network
    valid_network = False
    message = "Enter the new cluster's upstream network in CIDR format."
    while not valid_network:
        code, network = d.inputbox(message)
        if code == d.CANCEL:
            print("Aborted.")
            exit(0)
        try:
            upstream_network = ipaddress.ip_network(network) 
            valid_network = True
        except ValueError:
            message = "Error - network {} is not valid.\n\nEnter the new cluster's upstream network in CIDR format.".format(network)
            continue

    valid_address = False
    message = "Enter the CIDR floating IP address for the cluster's upstream network."
    while not valid_address:
        code, address = d.inputbox(message)
        if code == d.CANCEL:
            print("Aborted.")
            exit (0)
        try:
            upstream_floating_ip = ipaddress.ip_address(address)
            if not upstream_floating_ip in list(upstream_network.hosts()):
                message = "Error - address {} is not in network {}.\n\nEnter the CIDR floating IP address for the cluster's upstream network.".format(upstream_floating_ip, upstream_network)
                continue
            valid_address = True
        except ValueError:
            message = "Error - address {} is not valid.\n\nEnter the CIDR floating IP address for the cluster's upstream network.".format(upstream_floating_ip, upstream_network)
            continue

    code, upstream_domain = d.inputbox("""Enter the new cluster's upstream DNS domain.""")
    if code == d.CANCEL:
        print("Aborted.")
        exit(0)

    #
    # Phase 3 - Upstream settings
    #
    d.msgbox("""The next screens will present several questions regarding
the upstream and guest network configuration for the new
cluster, in an attempt to determine some default values
for the initial template files. Most of these options can
be overridden later by the client configuration tool or by
manual modification of the node configuration files, but
will shape the initial VM configuration and node config
file.
""")
    
    if d.yesno("""Should the PVC cluster manage client IP addressing?""") == d.OK:
        enable_routing = True
    else:
        enable_routing = False
    
    if d.yesno("""Should the PVC cluster provide NAT functionality?""") == d.OK:
        enable_nat = True
    else:
        enable_nat = False

    if d.yesno("""Should the PVC cluster manage client DNS records?""") == d.OK:
        enable_dns = True
    else:
        enable_dns = False

    #
    # Phase 4 - Configure templates
    #
    d.msgbox("""The next screens will present templates for several
configuration files in your $EDITOR, based on the options
selected above. These templates will be distributed to the
cluster nodes during bootstrapping.

Various values are indicated for '<replacement>' by you,
as 'TEMPLATE' values to be filled in from other information,
gained during these dialogs, or as default values.

Once you are finished editing the files, write and quit the
editor.

For more information on any particular field, see the PVC
documentation.
""")

    # Generate the node interfaces file template
    interfaces_configuration = """#
# pvc node network interfaces file
#
# Writing this template requires knowledge of the default
# persistent network names of the target server class.
#
# Configure any required bonding here, however do not
# configure any vLANs or VXLANs as those are managed
# by the PVC daemon itself.
#
# Make note of the interfaces specified for each type,
# as these will be required in the daemon config as
# well.
#
# Note that the Cluster and Storage networks *may* use
# the same underlying network device; in which case,
# only define one here and specify the same device
# for both networks in the daemon config.

auto lo
iface lo inet loopback

# Upstream physical interface
auto <upstream_dev_interface>
iface <upstream_dev_interface> inet manual

# Cluster physical interface
auto <cluster_dev_interface>
iface <cluster_dev_interface> inet manual

# Storage physical interface
auto <storage_dev_interface>
iface <storage_dev_interface> inet manual
"""
    with tempfile.NamedTemporaryFile(suffix=".tmp") as tf:
        EDITOR = os.environ.get('EDITOR', 'vi')
        tf.write(interfaces_configuration.encode("utf-8"))
        tf.flush()
        subprocess.call([EDITOR, tf.name])
        tf.seek(0)
        interfaces_configuration = tf.read().decode("utf-8")

    # Generate the configuration file template
    coordinator_list = list()
    for i in range(0,coordinator_count):
        coordinator_list.append("node{}".format(i + 1))
    dnssql_password = "Sup3rS3cr37SQL"
    ipmi_password = "Sup3rS3cr37IPMI"
    pvcd_configuration = {
        "pvc": {
            "node": "NODENAME",
            "cluster": {
                "coordinators": coordinator_list,
                "networks": {
                    "upstream": {
                        "domain": upstream_domain,
                        "network": str(upstream_network),
                        "floating_ip": str(upstream_floating_ip)
                    },
                    "cluster": {
                        "domain": cluster_domain,
                        "network": str(cluster_network),
                        "floating_ip": str(cluster_floating_ip)
                    },
                    "storage": {
                        "domain": storage_domain,
                        "network": str(storage_network),
                        "floating_ip": str(storage_floating_ip)
                    },
                }
            },
            "coordinator": {
                "dns": {
                    "database": {
                        "host": "localhost",
                        "port": "3306",
                        "name": "pvcdns",
                        "user": "pvcdns",
                        "pass": dnssql_password
                    }
                }
            },
            "system": {
                "fencing": {
                    "intervals": {
                        "keepalive_interval": "5",
                        "fence_intervals": "6",
                        "suicide_intervals": "0"
                    },
                    "actions": {
                        "successful_fence": "migrate",
                        "failed_fence": "None"
                    },
                    "ipmi": {
                        "address": "by-id",
                        "user": "pvcipmi",
                        "pass": ipmi_password
                    }
                },
                "migration": {
                    "target_selector": "mem"
                },
                "configuration":{
                    "directories": {
                        "dynamic_directory": "/run/pvc",
                        "log_directory": "/var/log/pvc"
                    },
                    "logging": {
                        "file_logging": "True",
                        "stdout_logging": "True"
                    },
                    "networking": {
                        "upstream": {
                            "device": "<upstream_interface_dev>",
                            "address": "None"
                        },
                        "cluster": {
                            "device": "<cluster_interface_dev>",
                            "address": "by-id"
                        },
                        "storage": {
                            "device": "<storage_interface_dev>",
                            "address": "by-id"
                        }
                    }
                }
            }
        }
    }
    pvcd_configuration_header = """#
# pvcd node configuration file
#
# For full details on the available options, consult the PVC documentation.
#
# The main pertanent replacements are:
#  <upstream_interface_dev>: the upstream device name from the interface template
#  <cluster_interface_dev>: the cluster device name from the interface template
#  <storage_interface_dev>: the storage device name from the interface template

"""

    with tempfile.NamedTemporaryFile(suffix=".tmp") as tf:
        EDITOR = os.environ.get('EDITOR', 'vi')
        pvcd_configuration_string = pvcd_configuration_header + yaml.dump(pvcd_configuration, default_style='"', default_flow_style=False)
        tf.write(pvcd_configuration_string.encode("utf-8"))
        tf.flush()
        subprocess.call([EDITOR, tf.name])
        tf.seek(0)
        pvcd_configuration = yaml.load(tf.read().decode("utf-8"))

    # We now have all the details to begin
    #  - interface
    #  - coordinator_count
    #  - cluster_network
    #  - cluster_floating_ip
    #  - cluster_domain
    #  - storage_network
    #  - storage_floating_ip
    #  - storage_domain
    #  - upstream_network
    #  - upstream_floating_ip
    #  - upstream_domain
    #  - enable_routing
    #  - enable_nat
    #  - enable_dns
    #  - interfaces_configuration [template]
    #  - coordinator_list
    #  - dnssql_password
    #  - ipmi_password
    #  - pvcd_configuration [ template]

    d.msgbox("""Information gathering complete. The PVC bootstrap
utility will now prepare the local system:
(a) Generate the node bootstrap image(s).
(b) Start up dnsmasq listening on the interface.
""")

def run():
    # Begin preparing the local system - install required packages
    required_packages = [
        'dnsmasq',
        'debootstrap',
        'debconf-utils',
        'squashfs-tools',
        'live-boot',
        'ansible'
    ]
    apt_command = "sudo apt install -y " + ' '.join(required_packages)
    retcode, stdout, stderr = run_os_command(apt_command)
    print(stdout)
    if retcode:
        print("ERROR: Package installation failed. Aborting setup.")
        print(stderr)
        exit(1)

    #
    # Generate a TFTP image for the installer
    #
    
    # Create our temporary working directory
    print("Create temporary directory...")
    tempdir = tempfile.mkdtemp()
    print(" > " + tempdir)

    # Download the netboot files
    print("Download PXE boot files...")
    download_path = "http://{mirror}/debian/dists/{release}/main/installer-{arch}/current/images/netboot/netboot.tar.gz".format(
        mirror=deb_mirror,
        release=deb_release,
        arch=deb_arch
    )
    bootarchive_file, headers = urllib.request.urlretrieve (download_path, tempdir + "/netboot.tar.gz")
    print(" > " + bootarchive_file)

    # Extract the netboot files
    print("Extract PXE boot files...")
    with tarfile.open(bootarchive_file) as tar:
        tar.extractall(tempdir + "/bootfiles")

    # Prepare a bare system with debootstrap
    print("Prepare installer debootstrap install...")
    debootstrap_command = "sudo -u root debootstrap --include={instpkg} {release} {tempdir}/rootfs http://{mirror}/debian".format(
        instpkg=deb_packages,
        release=deb_release,
        tempdir=tempdir,
        mirror=deb_mirror
    )
    retcode, stdout, stderr = run_os_command(debootstrap_command)
    if retcode:
        print("ERROR: Debootstrap failed. Aborting setup.")
        print(stdout)
        exit(1)

    # Prepare some useful configuration tweaks
    print("Tweaking installed image for boot...")
    sedtty_command = """sudo -u root sed -i
                      's|/sbin/agetty --noclear|/sbin/agetty --noclear --autologin root|g'
                      {}/rootfs/etc/systemd/system/getty@tty1.service""".format(tempdir)
    retcode, stdout, stderr = run_os_command(sedtty_command)

    # "Fix" permissions so we can write
    retcode, stdout, stderr = run_os_command("sudo chmod 777 {}/rootfs/root".format(tempdir))
    retcode, stdout, stderr = run_os_command("sudo chmod 666 {}/rootfs/root/.bashrc".format(tempdir))
    # Write the install script to root's bashrc
    with open("{}/rootfs/root/.bashrc".format(tempdir), "w") as bashrcf:
        bashrcf.write(bootstrap_script)
    # Restore permissions
    retcode, stdout, stderr = run_os_command("sudo chmod 600 {}/rootfs/root/.bashrc".format(tempdir))
    retcode, stdout, stderr = run_os_command("sudo chmod 700 {}/rootfs/root".format(tempdir))

    # Create the squashfs
    print("Create the squashfs...")
    squashfs_command = "sudo nice mksquashfs {tempdir}/rootfs {tempdir}/bootfiles/installer.squashfs".format(
        tempdir=tempdir
    )
    retcode, stdout, stderr = run_os_command(squashfs_command)
    if retcode:
        print("ERROR: SquashFS creation failed. Aborting setup.")
        print(stderr)
        exit(1)

    #
    # Prepare the DHCP and TFTP dnsmasq daemon
    #
    
    #
    # Prepare the HTTP listenener for the first node
    #




#
# Initialize the Zookeeper cluster
#
def init_zookeeper(zk_host):
    click.echo('Initializing a new cluster with Zookeeper address "{}".'.format(zk_host))

    # Open a Zookeeper connection
    zk_conn = pvc_common.startZKConnection(zk_host)

    # Destroy the existing data
    try:
        zk_conn.delete('/networks', recursive=True)
        zk_conn.delete('/domains', recursive=True)
        zk_conn.delete('/nodes', recursive=True)
        zk_conn.delete('/primary_node', recursive=True)
        zk_conn.delete('/ceph', recursive=True)
    except:
        pass

    # Create the root keys
    transaction = zk_conn.transaction()
    transaction.create('/nodes', ''.encode('ascii'))
    transaction.create('/primary_node', 'none'.encode('ascii'))
    transaction.create('/domains', ''.encode('ascii'))
    transaction.create('/networks', ''.encode('ascii'))
    transaction.create('/ceph', ''.encode('ascii'))
    transaction.create('/ceph/osds', ''.encode('ascii'))
    transaction.create('/ceph/pools', ''.encode('ascii'))
    transaction.create('/ceph/volumes', ''.encode('ascii'))
    transaction.create('/ceph/snapshots', ''.encode('ascii'))
    transaction.create('/locks', ''.encode('ascii'))
    transaction.create('/locks/flush_lock', 'False'.encode('ascii'))
    transaction.commit()

    # Close the Zookeeper connection
    pvc_common.stopZKConnection(zk_conn)

    click.echo('Successfully initialized new cluster. Any running PVC daemons will need to be restarted.')
