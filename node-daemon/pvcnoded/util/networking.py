#!/usr/bin/env python3

# networking.py - Utility functions for pvcnoded networking
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

import daemon_lib.common as common

from time import sleep
from os import makedirs


def setup_sriov(logger, config):
    logger.out('Setting up SR-IOV device support', state='i')

    # Enable unsafe interrupts for the vfio_iommu_type1 kernel module
    try:
        common.run_os_command('modprobe vfio_iommu_type1 allow_unsafe_interrupts=1')
        with open('/sys/module/vfio_iommu_type1/parameters/allow_unsafe_interrupts', 'w') as mfh:
            mfh.write('Y')
    except Exception:
        logger.out('Failed to enable vfio_iommu_type1 kernel module; SR-IOV may fail', state='w')

    # Loop through our SR-IOV NICs and enable the numvfs for each
    for device in config['sriov_device']:
        logger.out(f'Preparing SR-IOV PF {device["phy"]} with {device["vfcount"]} VFs', state='i')
        try:
            with open(f'/sys/class/net/{device["phy"]}/device/sriov_numvfs', 'r') as vfh:
                current_vf_count = vfh.read().strip()
            with open(f'/sys/class/net/{device["phy"]}/device/sriov_numvfs', 'w') as vfh:
                vfh.write(str(device['vfcount']))
        except FileNotFoundError:
            logger.out(f'Failed to open SR-IOV configuration for PF {device["phy"]}; device may not support SR-IOV', state='w')
        except OSError:
            logger.out(f'Failed to set SR-IOV VF count for PF {device["phy"]} to {device["vfcount"]}; already set to {current_vf_count}', state='w')

        if device.get('mtu', None) is not None:
            logger.out(f'Setting SR-IOV PF {device["phy"]} to MTU {device["mtu"]}', state='i')
            common.run_os_command(f'ip link set {device["phy"]} mtu {device["mtu"]} up')


def setup_interfaces(logger, config):
    # Set up the Cluster interface
    cluster_dev = config['cluster_dev']
    cluster_mtu = config['cluster_mtu']
    cluster_dev_ip = config['cluster_dev_ip']

    logger.out(f'Setting up Cluster network interface {cluster_dev} with MTU {cluster_mtu}', state='i')

    common.run_os_command(f'ip link set {cluster_dev} mtu {cluster_mtu} up')

    logger.out(f'Setting up Cluster network bridge on interface {cluster_dev} with IP {cluster_dev_ip}', state='i')

    common.run_os_command(f'brctl addbr brcluster')
    common.run_os_command(f'brctl addif brcluster {cluster_dev}')
    common.run_os_command(f'ip link set brcluster mtu {cluster_mtu} up')
    common.run_os_command(f'ip address add {cluster_dev_ip} dev brcluster')

    # Set up the Storage interface
    storage_dev = config['storage_dev']
    storage_mtu = config['storage_mtu']
    storage_dev_ip = config['storage_dev_ip']

    logger.out(f'Setting up Storage network interface {storage_dev} with MTU {storage_mtu}', state='i')

    common.run_os_command(f'ip link set {storage_dev} mtu {storage_mtu} up')

    if storage_dev == cluster_dev:
        if storage_dev_ip != cluster_dev_ip:
            logger.out(f'Setting up Storage network on Cluster network bridge with IP {storage_dev_ip}', state='i')

            common.run_os_command(f'ip address add {storage_dev_ip} dev brcluster')
    else:
        logger.out(f'Setting up Storage network bridge on interface {storage_dev} with IP {storage_dev_ip}', state='i')

        common.run_os_command(f'brctl addbr brstorage')
        common.run_os_command(f'brctl addif brstorage {storage_dev}')
        common.run_os_command(f'ip link set brstorage mtu {storage_mtu} up')
        common.run_os_command(f'ip address add {storage_dev_ip} dev brstorage')

    # Set up the Upstream interface
    upstream_dev = config['upstream_dev']
    upstream_mtu = config['upstream_mtu']
    upstream_dev_ip = config['upstream_dev_ip']

    logger.out(f'Setting up Upstream network interface {upstream_dev} with MTU {upstream_mtu}', state='i')

    if upstream_dev == cluster_dev:
        if upstream_dev_ip != cluster_dev_ip:
            logger.out(f'Setting up Upstream network on Cluster network bridge with IP {upstream_dev_ip}', state='i')

            common.run_os_command(f'ip address add {upstream_dev_ip} dev brcluster')
    else:
        logger.out(f'Setting up Upstream network bridge on interface {upstream_dev} with IP {upstream_dev_ip}', state='i')

        common.run_os_command(f'brctl addbr brupstream')
        common.run_os_command(f'brctl addif brupstream {upstream_dev}')
        common.run_os_command(f'ip link set brupstream mtu {upstream_mtu} up')
        common.run_os_command(f'ip address add {upstream_dev_ip} dev brupstream')

    upstream_gateway = config['upstream_gateway']
    if upstream_gateway is not None:
        logger.out(f'Setting up Upstream networok default gateway IP {upstream_gateway}', state='i')
        if upstream_dev == cluster_dev:
            common.run_os_command(f'ip route add default via {upstream_gateway} dev brcluster')
        else:
            common.run_os_command(f'ip route add default via {upstream_gateway} dev brupstream')

    # Set up sysctl tweaks to optimize networking
    # Enable routing functions
    common.run_os_command('sysctl net.ipv4.ip_forward=1')
    common.run_os_command('sysctl net.ipv6.ip_forward=1')
    # Enable send redirects
    common.run_os_command('sysctl net.ipv4.conf.all.send_redirects=1')
    common.run_os_command('sysctl net.ipv4.conf.default.send_redirects=1')
    common.run_os_command('sysctl net.ipv6.conf.all.send_redirects=1')
    common.run_os_command('sysctl net.ipv6.conf.default.send_redirects=1')
    # Accept source routes
    common.run_os_command('sysctl net.ipv4.conf.all.accept_source_route=1')
    common.run_os_command('sysctl net.ipv4.conf.default.accept_source_route=1')
    common.run_os_command('sysctl net.ipv6.conf.all.accept_source_route=1')
    common.run_os_command('sysctl net.ipv6.conf.default.accept_source_route=1')
    # Disable RP filtering on Cluster and Upstream interfaces (to allow traffic pivoting)
    common.run_os_command(f'sysctl net.ipv4.conf.{cluster_dev}.rp_filter=0')
    common.run_os_command(f'sysctl net.ipv4.conf.brcluster.rp_filter=0')
    common.run_os_command(f'sysctl net.ipv4.conf.{upstream_dev}.rp_filter=0')
    common.run_os_command(f'sysctl net.ipv4.conf.brupstream.rp_filter=0')
    common.run_os_command(f'sysctl net.ipv6.conf.{cluster_dev}.rp_filter=0')
    common.run_os_command(f'sysctl net.ipv6.conf.brcluster.rp_filter=0')
    common.run_os_command(f'sysctl net.ipv6.conf.{upstream_dev}.rp_filter=0')
    common.run_os_command(f'sysctl net.ipv6.conf.brupstream.rp_filter=0')

    # Stop DNSMasq if it is running
    common.run_os_command('systemctl stop dnsmasq.service')

    logger.out('Waiting 3 seconds for networking to come up', state='s')
    sleep(3)


def create_nft_configuration(logger, config):
    if config['enable_networking']:
        logger.out('Creating NFT firewall configuration', state='i')

        dynamic_directory = config['nft_dynamic_directory']

        # Create directories
        makedirs(f'{dynamic_directory}/networks', exist_ok=True)
        makedirs(f'{dynamic_directory}/static', exist_ok=True)

        # Set up the base rules
        nftables_base_rules = f"""# Base rules
        flush ruleset
        # Add the filter table and chains
        add table inet filter
        add chain inet filter forward {{ type filter hook forward priority 0; }}
        add chain inet filter input {{ type filter hook input priority 0; }}
        # Include static rules and network rules
        include "{dynamic_directory}/static/*"
        include "{dynamic_directory}/networks/*"
        """

        # Write the base firewall config
        nftables_base_filename = f'{dynamic_directory}/base.nft'
        with open(nftables_base_filename, 'w') as nftfh:
            nftfh.write(nftables_base_rules)
        common.reload_firewall_rules(nftables_base_filename, logger)
