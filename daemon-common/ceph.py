#!/usr/bin/env python3

# ceph.py - PVC client function library, Ceph cluster fuctions
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

import os
import re
import json
import time
import math

from concurrent.futures import ThreadPoolExecutor
from distutils.util import strtobool
from json import loads as jloads
from re import match, search
from uuid import uuid4
from os import path

import daemon_lib.vm as vm
import daemon_lib.common as common

from daemon_lib.celery import start, log_info, log_warn, update, fail, finish


#
# Supplemental functions
#


# Verify OSD is valid in cluster
def verifyOSD(zkhandler, osd_id):
    return zkhandler.exists(("osd", osd_id))


# Verify Pool is valid in cluster
def verifyPool(zkhandler, name):
    return zkhandler.exists(("pool", name))


# Verify Volume is valid in cluster
def verifyVolume(zkhandler, pool, name):
    return zkhandler.exists(("volume", f"{pool}/{name}"))


# Verify Snapshot is valid in cluster
def verifySnapshot(zkhandler, pool, volume, name):
    return zkhandler.exists(("snapshot", f"{pool}/{volume}/{name}"))


# Verify OSD path is valid in cluster
def verifyOSDBlock(zkhandler, node, device):
    for osd in zkhandler.children("base.osd"):
        osd_node = zkhandler.read(("osd.node", osd))
        osd_device = zkhandler.read(("osd.device", osd))
        if node == osd_node and device == osd_device:
            return osd
    return None


# Matrix of human-to-byte values
byte_unit_matrix = {
    "B": 1,
    "K": 1024,
    "M": 1024 * 1024,
    "G": 1024 * 1024 * 1024,
    "T": 1024 * 1024 * 1024 * 1024,
    "P": 1024 * 1024 * 1024 * 1024 * 1024,
    "E": 1024 * 1024 * 1024 * 1024 * 1024 * 1024,
    "Z": 1024 * 1024 * 1024 * 1024 * 1024 * 1024 * 1024,
    "Y": 1024 * 1024 * 1024 * 1024 * 1024 * 1024 * 1024 * 1024,
    "R": 1024 * 1024 * 1024 * 1024 * 1024 * 1024 * 1024 * 1024 * 1024,
    "Q": 1024 * 1024 * 1024 * 1024 * 1024 * 1024 * 1024 * 1024 * 1024 * 1024,
}

# Matrix of human-to-metric values
ops_unit_matrix = {
    "": 1,
    "K": 1000,
    "M": 1000 * 1000,
    "G": 1000 * 1000 * 1000,
    "T": 1000 * 1000 * 1000 * 1000,
    "P": 1000 * 1000 * 1000 * 1000 * 1000,
    "E": 1000 * 1000 * 1000 * 1000 * 1000 * 1000,
    "Z": 1000 * 1000 * 1000 * 1000 * 1000 * 1000 * 1000,
    "Y": 1000 * 1000 * 1000 * 1000 * 1000 * 1000 * 1000 * 1000,
    "R": 1000 * 1000 * 1000 * 1000 * 1000 * 1000 * 1000 * 1000 * 1000,
    "Q": 1000 * 1000 * 1000 * 1000 * 1000 * 1000 * 1000 * 1000 * 1000 * 1000,
}


# Format byte sizes to/from human-readable units
def format_bytes_tohuman(databytes):
    datahuman = ""
    for unit in sorted(byte_unit_matrix, key=byte_unit_matrix.get, reverse=True):
        new_bytes = int(math.ceil(databytes / byte_unit_matrix[unit]))
        # Round up if 5 or more digits
        if new_bytes > 9999:
            # We can jump down another level
            continue
        else:
            # We're at the end, display with this size
            datahuman = "{}{}".format(new_bytes, unit)

    return datahuman


def format_bytes_fromhuman(datahuman):
    if not re.search(r"[A-Za-z]+", datahuman):
        dataunit = "B"
        datasize = float(datahuman)
    else:
        dataunit = str(re.match(r"[0-9\.]+([A-Za-z])[iBb]*", datahuman).group(1))
        datasize = float(re.match(r"([0-9\.]+)[A-Za-z]+", datahuman).group(1))

    if byte_unit_matrix.get(dataunit.upper()):
        databytes = int(datasize * byte_unit_matrix[dataunit.upper()])
        return databytes
    else:
        return None


# Format ops sizes to/from human-readable units
def format_ops_tohuman(dataops):
    datahuman = ""
    for unit in sorted(ops_unit_matrix, key=ops_unit_matrix.get, reverse=True):
        new_ops = int(math.ceil(dataops / ops_unit_matrix[unit]))
        # Round up if 5 or more digits
        if new_ops > 9999:
            # We can jump down another level
            continue
        else:
            # We're at the end, display with this size
            datahuman = "{}{}".format(new_ops, unit)

    return datahuman


def format_ops_fromhuman(datahuman):
    # Trim off human-readable character
    dataunit = datahuman[-1]
    datasize = int(datahuman[:-1])
    dataops = datasize * ops_unit_matrix[dataunit.upper()]
    return "{}".format(dataops)


def format_pct_tohuman(datapct):
    datahuman = "{0:.1f}".format(float(datapct * 100.0))
    return datahuman


#
# Status functions
#
def get_status(zkhandler):
    primary_node = zkhandler.read("base.config.primary_node")
    ceph_status = zkhandler.read("base.storage").rstrip()

    # Create a data structure for the information
    status_data = {
        "type": "status",
        "primary_node": primary_node,
        "ceph_data": ceph_status,
    }
    return True, status_data


def get_health(zkhandler):
    primary_node = zkhandler.read("base.config.primary_node")
    ceph_health = zkhandler.read("base.storage.health").rstrip()

    # Create a data structure for the information
    status_data = {
        "type": "health",
        "primary_node": primary_node,
        "ceph_data": ceph_health,
    }
    return True, status_data


def get_util(zkhandler):
    primary_node = zkhandler.read("base.config.primary_node")
    ceph_df = zkhandler.read("base.storage.util").rstrip()

    # Create a data structure for the information
    status_data = {
        "type": "utilization",
        "primary_node": primary_node,
        "ceph_data": ceph_df,
    }
    return True, status_data


#
# OSD functions
#
def getClusterOSDList(zkhandler):
    # Get a list of VNIs by listing the children of /networks
    return zkhandler.children("base.osd")


def getOSDInformation(zkhandler, osd_id):
    (
        osd_fsid,
        osd_node,
        osd_device,
        _osd_is_split,
        osd_db_device,
        osd_stats_raw,
    ) = zkhandler.read_many(
        [
            ("osd.ofsid", osd_id),
            ("osd.node", osd_id),
            ("osd.device", osd_id),
            ("osd.is_split", osd_id),
            ("osd.db_device", osd_id),
            ("osd.stats", osd_id),
        ]
    )

    osd_is_split = bool(strtobool(_osd_is_split))
    # Parse the stats data
    osd_stats = dict(json.loads(osd_stats_raw))

    osd_information = {
        "id": osd_id,
        "fsid": osd_fsid,
        "node": osd_node,
        "device": osd_device,
        "is_split": osd_is_split,
        "db_device": osd_db_device,
        "stats": osd_stats,
    }
    return osd_information


def in_osd(zkhandler, osd_id):
    if not verifyOSD(zkhandler, osd_id):
        return False, 'ERROR: No OSD with ID "{}" is present in the cluster.'.format(
            osd_id
        )

    retcode, stdout, stderr = common.run_os_command("ceph osd in {}".format(osd_id))
    if retcode:
        return False, "ERROR: Failed to enable OSD {}: {}".format(osd_id, stderr)

    return True, "Set OSD {} online.".format(osd_id)


def out_osd(zkhandler, osd_id):
    if not verifyOSD(zkhandler, osd_id):
        return False, 'ERROR: No OSD with ID "{}" is present in the cluster.'.format(
            osd_id
        )

    retcode, stdout, stderr = common.run_os_command("ceph osd out {}".format(osd_id))
    if retcode:
        return False, "ERROR: Failed to disable OSD {}: {}".format(osd_id, stderr)

    return True, "Set OSD {} offline.".format(osd_id)


def set_osd(zkhandler, option):
    retcode, stdout, stderr = common.run_os_command("ceph osd set {}".format(option))
    if retcode:
        return False, 'ERROR: Failed to set property "{}": {}'.format(option, stderr)

    return True, 'Set OSD property "{}".'.format(option)


def unset_osd(zkhandler, option):
    retcode, stdout, stderr = common.run_os_command("ceph osd unset {}".format(option))
    if retcode:
        return False, 'ERROR: Failed to unset property "{}": {}'.format(option, stderr)

    return True, 'Unset OSD property "{}".'.format(option)


def get_list_osd(zkhandler, limit=None, is_fuzzy=True):
    osd_list = []
    full_osd_list = zkhandler.children("base.osd")

    if is_fuzzy and limit:
        # Implicitly assume fuzzy limits
        if not re.match(r"\^.*", limit):
            limit = ".*" + limit
        if not re.match(r".*\$", limit):
            limit = limit + ".*"

    for osd in full_osd_list:
        if limit:
            try:
                if re.fullmatch(limit, osd):
                    osd_list.append(getOSDInformation(zkhandler, osd))
            except Exception as e:
                return False, "Regex Error: {}".format(e)
        else:
            osd_list.append(getOSDInformation(zkhandler, osd))

    return True, sorted(osd_list, key=lambda x: int(x["id"]))


#
# Pool functions
#
def getPoolInformation(zkhandler, pool):
    # Parse the stats data
    (
        pool_stats_raw,
        tier,
        pgs,
    ) = zkhandler.read_many(
        [
            ("pool.stats", pool),
            ("pool.tier", pool),
            ("pool.pgs", pool),
        ]
    )

    pool_stats = dict(json.loads(pool_stats_raw))
    volume_count = len(getCephVolumes(zkhandler, pool))
    if tier is None:
        tier = "default"

    pool_information = {
        "name": pool,
        "volume_count": volume_count,
        "tier": tier,
        "pgs": pgs,
        "stats": pool_stats,
    }
    return pool_information


def add_pool(zkhandler, name, pgs, replcfg, tier=None):
    # Prepare the copies/mincopies variables
    try:
        copies, mincopies = replcfg.split(",")
        copies = int(copies.replace("copies=", ""))
        mincopies = int(mincopies.replace("mincopies=", ""))
    except Exception:
        copies = None
        mincopies = None
    if not copies or not mincopies:
        return False, f'ERROR: Replication configuration "{replcfg}" is not valid.'

    # Prepare the tiers if applicable
    if tier is not None and tier in ["hdd", "ssd", "nvme"]:
        crush_rule = f"{tier}_tier"
        # Create a CRUSH rule for the relevant tier
        retcode, stdout, stderr = common.run_os_command(
            f"ceph osd crush rule create-replicated {crush_rule} default host {tier}"
        )
        if retcode:
            return (
                False,
                f"ERROR: Failed to create CRUSH rule {tier} for pool {name}: {stderr}",
            )
    else:
        tier = "default"
        crush_rule = "replicated"

    # Create the pool
    retcode, stdout, stderr = common.run_os_command(
        f"ceph osd pool create {name} {pgs} {pgs} {crush_rule}"
    )
    if retcode:
        return False, f'ERROR: Failed to create pool "{name}" with {pgs} PGs: {stderr}'

    # Set the size and minsize
    retcode, stdout, stderr = common.run_os_command(
        f"ceph osd pool set {name} size {copies}"
    )
    if retcode:
        return False, f'ERROR: Failed to set pool "{name}" size of {copies}: {stderr}'

    retcode, stdout, stderr = common.run_os_command(
        f"ceph osd pool set {name} min_size {mincopies}"
    )
    if retcode:
        return (
            False,
            f'ERROR: Failed to set pool "{name}" minimum size of {mincopies}: {stderr}',
        )

    # Enable RBD application
    retcode, stdout, stderr = common.run_os_command(
        f"ceph osd pool application enable {name} rbd"
    )
    if retcode:
        return (
            False,
            f'ERROR: Failed to enable RBD application on pool "{name}" : {stderr}',
        )

    # Add the new pool to Zookeeper
    zkhandler.write(
        [
            (("pool", name), ""),
            (("pool.pgs", name), pgs),
            (("pool.tier", name), tier),
            (("pool.stats", name), "{}"),
            (("volume", name), ""),
            (("snapshot", name), ""),
        ]
    )

    return True, f'Created RBD pool "{name}" with {pgs} PGs'


def remove_pool(zkhandler, name):
    if not verifyPool(zkhandler, name):
        return False, 'ERROR: No pool with name "{}" is present in the cluster.'.format(
            name
        )

    # 1. Remove pool volumes
    for volume in zkhandler.children(("volume", name)):
        remove_volume(zkhandler, name, volume)

    # 2. Remove the pool
    retcode, stdout, stderr = common.run_os_command(
        "ceph osd pool rm {pool} {pool} --yes-i-really-really-mean-it".format(pool=name)
    )
    if retcode:
        return False, 'ERROR: Failed to remove pool "{}": {}'.format(name, stderr)

    # 3. Delete pool from Zookeeper
    zkhandler.delete(
        [
            ("pool", name),
            ("volume", name),
            ("snapshot", name),
        ]
    )

    return True, 'Removed RBD pool "{}" and all volumes.'.format(name)


def set_pgs_pool(zkhandler, name, pgs):
    if not verifyPool(zkhandler, name):
        return False, f'ERROR: No pool with name "{name}" is present in the cluster.'

    # Validate new PGs count
    pgs = int(pgs)
    if (pgs == 0) or (pgs & (pgs - 1) != 0):
        return (
            False,
            f'ERROR: Invalid PGs number "{pgs}": must be a non-zero power of 2.',
        )

    # Set the new pgs number
    retcode, stdout, stderr = common.run_os_command(
        f"ceph osd pool set {name} pg_num {pgs}"
    )
    if retcode:
        return False, f"ERROR: Failed to set pg_num on pool {name} to {pgs}: {stderr}"

    # Set the new pgps number if increasing
    current_pgs = int(zkhandler.read(("pool.pgs", name)))
    if current_pgs >= pgs:
        retcode, stdout, stderr = common.run_os_command(
            f"ceph osd pool set {name} pgp_num {pgs}"
        )
        if retcode:
            return (
                False,
                f"ERROR: Failed to set pg_num on pool {name} to {pgs}: {stderr}",
            )

    # Update Zookeeper count
    zkhandler.write(
        [
            (("pool.pgs", name), pgs),
        ]
    )

    return True, f'Set PGs count to {pgs} for RBD pool "{name}".'


def get_list_pool(zkhandler, limit=None, is_fuzzy=True):
    full_pool_list = zkhandler.children("base.pool")

    if is_fuzzy and limit:
        # Implicitly assume fuzzy limits
        if not re.match(r"\^.*", limit):
            limit = ".*" + limit
        if not re.match(r".*\$", limit):
            limit = limit + ".*"

    get_pool_info = dict()
    for pool in full_pool_list:
        is_limit_match = False
        if limit:
            try:
                if re.fullmatch(limit, pool):
                    is_limit_match = True
            except Exception as e:
                return False, "Regex Error: {}".format(e)
        else:
            is_limit_match = True

        get_pool_info[pool] = True if is_limit_match else False

    pool_execute_list = [pool for pool in full_pool_list if get_pool_info[pool]]
    pool_data_list = list()
    with ThreadPoolExecutor(max_workers=32, thread_name_prefix="pool_list") as executor:
        futures = []
        for pool in pool_execute_list:
            futures.append(executor.submit(getPoolInformation, zkhandler, pool))
        for future in futures:
            pool_data_list.append(future.result())

    return True, sorted(pool_data_list, key=lambda x: int(x["stats"].get("id", 0)))


#
# Volume functions
#
def getCephVolumes(zkhandler, pool):
    volume_list = list()
    if not pool:
        pool_list = zkhandler.children("base.pool")
    else:
        pool_list = [pool]

    for pool_name in pool_list:
        children = zkhandler.children(("volume", pool_name))
        if children is None:
            continue
        for volume_name in children:
            volume_list.append("{}/{}".format(pool_name, volume_name))

    return volume_list


def getVolumeInformation(zkhandler, pool, volume):
    # Parse the stats data
    volume_stats_raw = zkhandler.read(("volume.stats", f"{pool}/{volume}"))
    volume_stats = dict(json.loads(volume_stats_raw))
    # Format the size to something nicer
    volume_stats["size"] = format_bytes_tohuman(volume_stats["size"])

    volume_information = {"name": volume, "pool": pool, "stats": volume_stats}
    return volume_information


def scan_volume(zkhandler, pool, name):
    retcode, stdout, stderr = common.run_os_command(
        "rbd info --format json {}/{}".format(pool, name)
    )
    volstats = stdout

    # 3. Add the new volume to Zookeeper
    zkhandler.write(
        [
            (("volume.stats", f"{pool}/{name}"), volstats),
        ]
    )


def add_volume(zkhandler, pool, name, size, force_flag=False, zk_only=False):
    # 1. Verify the size of the volume
    pool_information = getPoolInformation(zkhandler, pool)
    size_bytes = format_bytes_fromhuman(size)
    if size_bytes is None:
        return (
            False,
            f"ERROR: Requested volume size '{size}' does not have a valid SI unit",
        )

    pool_total_free_bytes = int(pool_information["stats"]["free_bytes"])
    if size_bytes >= pool_total_free_bytes:
        return (
            False,
            f"ERROR: Requested volume size '{format_bytes_tohuman(size_bytes)}' is greater than the available free space in the pool ('{format_bytes_tohuman(pool_information['stats']['free_bytes'])}')",
        )

    # Check if we're greater than 80% utilization after the create; error if so unless we have the force flag
    pool_total_bytes = (
        int(pool_information["stats"]["used_bytes"]) + pool_total_free_bytes
    )
    pool_safe_total_bytes = int(pool_total_bytes * 0.80)
    pool_safe_free_bytes = pool_safe_total_bytes - int(
        pool_information["stats"]["used_bytes"]
    )
    if size_bytes >= pool_safe_free_bytes and not force_flag:
        return (
            False,
            f"ERROR: Requested volume size '{format_bytes_tohuman(size_bytes)}' is greater than the safe free space in the pool ('{format_bytes_tohuman(pool_safe_free_bytes)}' for 80% full); retry with force to ignore this error",
        )

    # 2. Create the volume
    # zk_only flag skips actually creating the volume - this would be done by some other mechanism
    if not zk_only:
        retcode, stdout, stderr = common.run_os_command(
            "rbd create --size {}B {}/{}".format(size_bytes, pool, name)
        )
        if retcode:
            return False, 'ERROR: Failed to create RBD volume "{}": {}'.format(
                name, stderr
            )

    # 3. Add the new volume to Zookeeper
    zkhandler.write(
        [
            (("volume", f"{pool}/{name}"), ""),
            (("volume.stats", f"{pool}/{name}"), ""),
            (("snapshot", f"{pool}/{name}"), ""),
        ]
    )

    # 4. Scan the volume stats
    scan_volume(zkhandler, pool, name)

    return True, 'Created RBD volume "{}" of size "{}" in pool "{}".'.format(
        name, format_bytes_tohuman(size_bytes), pool
    )


def clone_volume(zkhandler, pool, name_src, name_new, force_flag=False):
    # 1. Verify the volume
    if not verifyVolume(zkhandler, pool, name_src):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(
            name_src, pool
        )

    volume_stats_raw = zkhandler.read(("volume.stats", f"{pool}/{name_src}"))
    volume_stats = dict(json.loads(volume_stats_raw))
    size_bytes = volume_stats["size"]
    pool_information = getPoolInformation(zkhandler, pool)
    pool_total_free_bytes = int(pool_information["stats"]["free_bytes"])
    if size_bytes >= pool_total_free_bytes:
        return (
            False,
            f"ERROR: Clone volume size '{format_bytes_tohuman(size_bytes)}' is greater than the available free space in the pool ('{format_bytes_tohuman(pool_information['stats']['free_bytes'])}')",
        )

    # Check if we're greater than 80% utilization after the create; error if so unless we have the force flag
    pool_total_bytes = (
        int(pool_information["stats"]["used_bytes"]) + pool_total_free_bytes
    )
    pool_safe_total_bytes = int(pool_total_bytes * 0.80)
    pool_safe_free_bytes = pool_safe_total_bytes - int(
        pool_information["stats"]["used_bytes"]
    )
    if size_bytes >= pool_safe_free_bytes and not force_flag:
        return (
            False,
            f"ERROR: Clone volume size '{format_bytes_tohuman(size_bytes)}' is greater than the safe free space in the pool ('{format_bytes_tohuman(pool_safe_free_bytes)}' for 80% full); retry with force to ignore this error",
        )

    # 2. Clone the volume
    retcode, stdout, stderr = common.run_os_command(
        "rbd copy {}/{} {}/{}".format(pool, name_src, pool, name_new)
    )
    if retcode:
        return (
            False,
            'ERROR: Failed to clone RBD volume "{}" to "{}" in pool "{}": {}'.format(
                name_src, name_new, pool, stderr
            ),
        )

    # 3. Add the new volume to Zookeeper
    zkhandler.write(
        [
            (("volume", f"{pool}/{name_new}"), ""),
            (("volume.stats", f"{pool}/{name_new}"), ""),
            (("snapshot", f"{pool}/{name_new}"), ""),
        ]
    )

    # 4. Scan the volume stats
    scan_volume(zkhandler, pool, name_new)

    return True, 'Cloned RBD volume "{}" to "{}" in pool "{}"'.format(
        name_src, name_new, pool
    )


def resize_volume(zkhandler, pool, name, size, force_flag=False):
    if not verifyVolume(zkhandler, pool, name):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(
            name, pool
        )

    # 1. Verify the size of the volume
    pool_information = getPoolInformation(zkhandler, pool)
    size_bytes = format_bytes_fromhuman(size)
    if size_bytes is None:
        return (
            False,
            f"ERROR: Requested volume size '{size}' does not have a valid SI unit",
        )

    pool_total_free_bytes = int(pool_information["stats"]["free_bytes"])
    if size_bytes >= pool_total_free_bytes:
        return (
            False,
            f"ERROR: Requested volume size '{format_bytes_tohuman(size_bytes)}' is greater than the available free space in the pool ('{format_bytes_tohuman(pool_information['stats']['free_bytes'])}')",
        )

    # Check if we're greater than 80% utilization after the create; error if so unless we have the force flag
    pool_total_bytes = (
        int(pool_information["stats"]["used_bytes"]) + pool_total_free_bytes
    )
    pool_safe_total_bytes = int(pool_total_bytes * 0.80)
    pool_safe_free_bytes = pool_safe_total_bytes - int(
        pool_information["stats"]["used_bytes"]
    )
    if size_bytes >= pool_safe_free_bytes and not force_flag:
        return (
            False,
            f"ERROR: Requested volume size '{format_bytes_tohuman(size_bytes)}' is greater than the safe free space in the pool ('{format_bytes_tohuman(pool_safe_free_bytes)}' for 80% full); retry with force to ignore this error",
        )

    # 2. Resize the volume
    retcode, stdout, stderr = common.run_os_command(
        "rbd resize --size {} {}/{}".format(
            format_bytes_tohuman(size_bytes), pool, name
        )
    )
    if retcode:
        return (
            False,
            'ERROR: Failed to resize RBD volume "{}" to size "{}" in pool "{}": {}'.format(
                name, format_bytes_tohuman(size_bytes), pool, stderr
            ),
        )

    # 3a. Determine the node running this VM if applicable
    active_node = None
    volume_vm_name = name.split("_")[0]
    retcode, vm_info = vm.get_info(zkhandler, volume_vm_name)
    if retcode:
        for disk in vm_info["disks"]:
            # This block device is present in this VM so we can continue
            if disk["name"] == "{}/{}".format(pool, name):
                active_node = vm_info["node"]
                volume_id = disk["dev"]
    # 3b. Perform a live resize in libvirt if the VM is running
    if active_node is not None and vm_info.get("state", "") == "start":
        import libvirt

        # Run the libvirt command against the target host
        try:
            dest_lv = "qemu+tcp://{}/system".format(active_node)
            target_lv_conn = libvirt.open(dest_lv)
            target_vm_conn = target_lv_conn.lookupByName(vm_info["name"])
            if target_vm_conn:
                target_vm_conn.blockResize(
                    volume_id,
                    size_bytes,
                    libvirt.VIR_DOMAIN_BLOCK_RESIZE_BYTES,
                )
            target_lv_conn.close()
        except Exception:
            pass

    # 4. Scan the volume stats
    scan_volume(zkhandler, pool, name)

    return True, 'Resized RBD volume "{}" to size "{}" in pool "{}".'.format(
        name, format_bytes_tohuman(size_bytes), pool
    )


def rename_volume(zkhandler, pool, name, new_name):
    if not verifyVolume(zkhandler, pool, name):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(
            name, pool
        )

    # 1. Rename the volume
    retcode, stdout, stderr = common.run_os_command(
        "rbd rename {}/{} {}".format(pool, name, new_name)
    )
    if retcode:
        return (
            False,
            'ERROR: Failed to rename volume "{}" to "{}" in pool "{}": {}'.format(
                name, new_name, pool, stderr
            ),
        )

    # 2. Rename the volume in Zookeeper
    zkhandler.rename(
        [
            (("volume", f"{pool}/{name}"), ("volume", f"{pool}/{new_name}")),
            (("snapshot", f"{pool}/{name}"), ("snapshot", f"{pool}/{new_name}")),
        ]
    )

    # 3. Scan the volume stats
    scan_volume(zkhandler, pool, new_name)

    return True, 'Renamed RBD volume "{}" to "{}" in pool "{}".'.format(
        name, new_name, pool
    )


def remove_volume(zkhandler, pool, name):
    if not verifyVolume(zkhandler, pool, name):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(
            name, pool
        )

    # 1a. Remove PVC-managed volume snapshots
    for snapshot in zkhandler.children(("snapshot", f"{pool}/{name}")):
        remove_snapshot(zkhandler, pool, name, snapshot)

    # 1b. Purge any remaining volume snapshots
    retcode, stdout, stderr = common.run_os_command(
        "rbd snap purge {}/{}".format(pool, name)
    )
    if retcode:
        return (
            False,
            'ERROR: Failed to purge snapshots from RBD volume "{}" in pool "{}": {}'.format(
                name, pool, stderr
            ),
        )

    # 2. Remove the volume
    retcode, stdout, stderr = common.run_os_command("rbd rm {}/{}".format(pool, name))
    if retcode:
        return False, 'ERROR: Failed to remove RBD volume "{}" in pool "{}": {}'.format(
            name, pool, stderr
        )

    # 3. Delete volume from Zookeeper
    zkhandler.delete(
        [
            ("volume", f"{pool}/{name}"),
            ("snapshot", f"{pool}/{name}"),
        ]
    )

    return True, 'Removed RBD volume "{}" in pool "{}".'.format(name, pool)


def map_volume(zkhandler, pool, name):
    if not verifyVolume(zkhandler, pool, name):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(
            name, pool
        )

    # 1. Map the volume onto the local system
    retcode, stdout, stderr = common.run_os_command("rbd map {}/{}".format(pool, name))
    if retcode:
        return False, 'ERROR: Failed to map RBD volume "{}" in pool "{}": {}'.format(
            name, pool, stderr
        )

    # 2. Calculate the absolute path to the mapped volume
    mapped_volume = "/dev/rbd/{}/{}".format(pool, name)

    # 3. Ensure the volume exists
    if not os.path.exists(mapped_volume):
        return (
            False,
            'ERROR: Mapped volume not found at expected location "{}".'.format(
                mapped_volume
            ),
        )

    return True, mapped_volume


def unmap_volume(zkhandler, pool, name):
    if not verifyVolume(zkhandler, pool, name):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(
            name, pool
        )

    mapped_volume = "/dev/rbd/{}/{}".format(pool, name)

    # 1. Ensure the volume exists
    if not os.path.exists(mapped_volume):
        return (
            False,
            'ERROR: Mapped volume not found at expected location "{}".'.format(
                mapped_volume
            ),
        )

    # 2. Unap the volume
    retcode, stdout, stderr = common.run_os_command(
        "rbd unmap {}".format(mapped_volume)
    )
    if retcode:
        return False, 'ERROR: Failed to unmap RBD volume at "{}": {}'.format(
            mapped_volume, stderr
        )

    return True, 'Unmapped RBD volume at "{}".'.format(mapped_volume)


def get_list_volume(zkhandler, pool, limit=None, is_fuzzy=True):
    if pool and not verifyPool(zkhandler, pool):
        return False, 'ERROR: No pool with name "{}" is present in the cluster.'.format(
            pool
        )

    full_volume_list = getCephVolumes(zkhandler, pool)

    if is_fuzzy and limit:
        # Implicitly assume fuzzy limits
        if not re.match(r"\^.*", limit):
            limit = ".*" + limit
        if not re.match(r".*\$", limit):
            limit = limit + ".*"

    get_volume_info = dict()
    for volume in full_volume_list:
        pool_name, volume_name = volume.split("/")
        is_limit_match = False

        # Check on limit
        if limit:
            # Try to match the limit against the volume name
            try:
                if re.fullmatch(limit, volume_name):
                    is_limit_match = True
            except Exception as e:
                return False, "Regex Error: {}".format(e)
        else:
            is_limit_match = True

        get_volume_info[volume] = True if is_limit_match else False

    # Obtain our volume data in a thread pool
    volume_execute_list = [
        volume for volume in full_volume_list if get_volume_info[volume]
    ]
    volume_data_list = list()
    with ThreadPoolExecutor(
        max_workers=32, thread_name_prefix="volume_list"
    ) as executor:
        futures = []
        for volume in volume_execute_list:
            pool_name, volume_name = volume.split("/")
            futures.append(
                executor.submit(getVolumeInformation, zkhandler, pool_name, volume_name)
            )
        for future in futures:
            volume_data_list.append(future.result())

    return True, sorted(volume_data_list, key=lambda x: str(x["name"]))


#
# Snapshot functions
#
def getCephSnapshots(zkhandler, pool, volume):
    snapshot_list = list()
    volume_list = list()

    volume_list = getCephVolumes(zkhandler, pool)
    if volume:
        for volume_entry in volume_list:
            volume_pool, volume_name = volume_entry.split("/")
            if volume_name == volume:
                volume_list = ["{}/{}".format(volume_pool, volume_name)]

    for volume_entry in volume_list:
        for snapshot_name in zkhandler.children(("snapshot", volume_entry)):
            snapshot_list.append("{}@{}".format(volume_entry, snapshot_name))

    return snapshot_list


def add_snapshot(zkhandler, pool, volume, name, zk_only=False):
    if not verifyVolume(zkhandler, pool, volume):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(
            volume, pool
        )

    # 1. Create the snapshot
    if not zk_only:
        retcode, stdout, stderr = common.run_os_command(
            "rbd snap create {}/{}@{}".format(pool, volume, name)
        )
        if retcode:
            return (
                False,
                'ERROR: Failed to create RBD snapshot "{}" of volume "{}" in pool "{}": {}'.format(
                    name, volume, pool, stderr
                ),
            )

    # 2. Get snapshot stats
    retcode, stdout, stderr = common.run_os_command(
        "rbd info --format json {}/{}@{}".format(pool, volume, name)
    )
    snapstats = stdout

    # 3. Add the snapshot to Zookeeper
    zkhandler.write(
        [
            (("snapshot", f"{pool}/{volume}/{name}"), ""),
            (("snapshot.stats", f"{pool}/{volume}/{name}"), snapstats),
        ]
    )

    # 4. Update the count of snapshots on this volume
    volume_stats_raw = zkhandler.read(("volume.stats", f"{pool}/{volume}"))
    volume_stats = dict(json.loads(volume_stats_raw))
    volume_stats["snapshot_count"] = volume_stats["snapshot_count"] + 1
    zkhandler.write(
        [
            (("volume.stats", f"{pool}/{volume}"), json.dumps(volume_stats)),
        ]
    )

    return True, 'Created RBD snapshot "{}" of volume "{}" in pool "{}".'.format(
        name, volume, pool
    )


def rename_snapshot(zkhandler, pool, volume, name, new_name):
    if not verifyVolume(zkhandler, pool, volume):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(
            volume, pool
        )
    if not verifySnapshot(zkhandler, pool, volume, name):
        return (
            False,
            'ERROR: No snapshot with name "{}" is present for volume "{}" in pool "{}".'.format(
                name, volume, pool
            ),
        )

    # 1. Rename the snapshot
    retcode, stdout, stderr = common.run_os_command(
        "rbd snap rename {pool}/{volume}@{name} {pool}/{volume}@{new_name}".format(
            pool=pool, volume=volume, name=name, new_name=new_name
        )
    )
    if retcode:
        return (
            False,
            'ERROR: Failed to rename RBD snapshot "{}" to "{}" for volume "{}" in pool "{}": {}'.format(
                name, new_name, volume, pool, stderr
            ),
        )

    # 2. Rename the snapshot in ZK
    zkhandler.rename(
        [
            (
                ("snapshot", f"{pool}/{volume}/{name}"),
                ("snapshot", f"{pool}/{volume}/{new_name}"),
            ),
        ]
    )

    return (
        True,
        'Renamed RBD snapshot "{}" to "{}" for volume "{}" in pool "{}".'.format(
            name, new_name, volume, pool
        ),
    )


def rollback_snapshot(zkhandler, pool, volume, name):
    if not verifyVolume(zkhandler, pool, volume):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(
            volume, pool
        )
    if not verifySnapshot(zkhandler, pool, volume, name):
        return (
            False,
            'ERROR: No snapshot with name "{}" is present for volume "{}" in pool "{}".'.format(
                name, volume, pool
            ),
        )

        # 1. Roll back the snapshot
        retcode, stdout, stderr = common.run_os_command(
            "rbd snap rollback {}/{}@{}".format(pool, volume, name)
        )
        if retcode:
            return (
                False,
                'ERROR: Failed to roll back RBD volume "{}" in pool "{}" to snapshot "{}": {}'.format(
                    volume, pool, name, stderr
                ),
            )

    return True, 'Rolled back RBD volume "{}" in pool "{}" to snapshot "{}".'.format(
        volume, pool, name
    )


def remove_snapshot(zkhandler, pool, volume, name):
    if not verifyVolume(zkhandler, pool, volume):
        return False, 'ERROR: No volume with name "{}" is present in pool "{}".'.format(
            volume, pool
        )
    if not verifySnapshot(zkhandler, pool, volume, name):
        return (
            False,
            'ERROR: No snapshot with name "{}" is present of volume {} in pool {}.'.format(
                name, volume, pool
            ),
        )

    # 1. Remove the snapshot
    retcode, stdout, stderr = common.run_os_command(
        "rbd snap rm {}/{}@{}".format(pool, volume, name)
    )
    if retcode:
        return (
            False,
            'Failed to remove RBD snapshot "{}" of volume "{}" in pool "{}": {}'.format(
                name, volume, pool, stderr
            ),
        )

    # 2. Delete snapshot from Zookeeper
    zkhandler.delete([("snapshot", f"{pool}/{volume}/{name}")])

    # 3. Update the count of snapshots on this volume
    volume_stats_raw = zkhandler.read(("volume.stats", f"{pool}/{volume}"))
    volume_stats = dict(json.loads(volume_stats_raw))
    # Format the size to something nicer
    volume_stats["snapshot_count"] = volume_stats["snapshot_count"] - 1
    volume_stats_raw = json.dumps(volume_stats)
    zkhandler.write([(("volume.stats", f"{pool}/{volume}"), volume_stats_raw)])

    return True, 'Removed RBD snapshot "{}" of volume "{}" in pool "{}".'.format(
        name, volume, pool
    )


def get_list_snapshot(zkhandler, target_pool, target_volume, limit=None, is_fuzzy=True):
    snapshot_list = []
    full_snapshot_list = getCephSnapshots(zkhandler, target_pool, target_volume)

    if is_fuzzy and limit:
        # Implicitly assume fuzzy limits
        if not re.match(r"\^.*", limit):
            limit = ".*" + limit
        if not re.match(r".*\$", limit):
            limit = limit + ".*"

    for snapshot in full_snapshot_list:
        volume, snapshot_name = snapshot.split("@")
        pool_name, volume_name = volume.split("/")
        if target_pool and pool_name != target_pool:
            continue
        if target_volume and volume_name != target_volume:
            continue
        try:
            snapshot_stats = json.loads(
                zkhandler.read(
                    ("snapshot.stats", f"{pool_name}/{volume_name}/{snapshot_name}")
                )
            )
        except Exception:
            snapshot_stats = []
        if limit:
            try:
                if re.fullmatch(limit, snapshot_name):
                    snapshot_list.append(
                        {
                            "pool": pool_name,
                            "volume": volume_name,
                            "snapshot": snapshot_name,
                            "stats": snapshot_stats,
                        }
                    )
            except Exception as e:
                return False, "Regex Error: {}".format(e)
        else:
            snapshot_list.append(
                {
                    "pool": pool_name,
                    "volume": volume_name,
                    "snapshot": snapshot_name,
                    "stats": snapshot_stats,
                }
            )

    return True, sorted(snapshot_list, key=lambda x: str(x["snapshot"]))


#
# Celery worker tasks (must be run on node, outputs log messages to worker)
#
def osd_worker_helper_find_osds_from_block(device):
    # Try to query the passed block device directly
    retcode, stdout, stderr = common.run_os_command(
        f"ceph-volume lvm list --format json {device}"
    )
    if retcode:
        found_osds = []
    else:
        found_osds = jloads(stdout)

    return found_osds


def osd_worker_add_osd(
    zkhandler,
    celery,
    node,
    device,
    weight,
    ext_db_ratio=None,
    ext_db_size=None,
    split_count=None,
):
    current_stage = 0
    total_stages = 5
    if split_count is None:
        split_count = 1
    else:
        split_count = int(split_count)
    total_stages = total_stages + 3 * int(split_count)
    if ext_db_ratio is not None or ext_db_size is not None:
        total_stages = total_stages + 3 * int(split_count) + 1

    start(
        celery,
        f"Adding {split_count} new OSD(s) on device {device} with weight {weight}",
        current=current_stage,
        total=total_stages,
    )

    # Handle a detect device if that is passed
    if match(r"detect:", device):
        ddevice = common.get_detect_device(device)
        if ddevice is None:
            fail(
                celery,
                f"Failed to determine block device from detect string {device}",
            )
            return
        else:
            log_info(
                celery, f"Determined block device {ddevice} from detect string {device}"
            )
            device = ddevice

    if ext_db_size is not None and ext_db_ratio is not None:
        fail(
            celery,
            "Invalid configuration: both an ext_db_size and ext_db_ratio were specified",
        )
        return

    # Check if device has a partition table; it's not valid if it does
    retcode, _, _ = common.run_os_command(f"sfdisk --dump {device}")
    if retcode < 1:
        fail(
            celery,
            f"Device {device} has a partition table and is unsuitable for an OSD",
        )
        return

    if ext_db_size is not None or ext_db_ratio is not None:
        ext_db_flag = True
    else:
        ext_db_flag = False

    if split_count > 1:
        split_flag = f"--osds-per-device {split_count}"
        is_split = True
        log_info(
            celery, f"Creating {split_count} new OSD disks on block device {device}"
        )
    else:
        split_flag = ""
        is_split = False
        log_info(celery, f"Creating 1 new OSD disk on block device {device}")

    if "nvme" in device:
        class_flag = "--crush-device-class nvme"
    else:
        class_flag = "--crush-device-class ssd"

    # 1. Zap the block device
    current_stage += 1
    update(
        celery,
        f"Zapping block device {device}",
        current=current_stage,
        total=total_stages,
    )
    retcode, stdout, stderr = common.run_os_command(
        f"ceph-volume lvm zap --destroy {device}"
    )
    log_info(celery, f"stdout: {stdout}")
    log_info(celery, f"stderr: {stderr}")
    if retcode:
        fail(celery, f"Failed to perform ceph-volume lvm zap on {device}")
        return

    # 2. Prepare the OSD(s)
    current_stage += 1
    update(
        celery,
        f"Preparing OSD(s) on device {device}",
        current=current_stage,
        total=total_stages,
    )
    retcode, stdout, stderr = common.run_os_command(
        f"ceph-volume lvm batch --yes --prepare --bluestore {split_flag} {class_flag} {device}"
    )
    log_info(celery, f"stdout: {stdout}")
    log_info(celery, f"stderr: {stderr}")
    if retcode:
        fail(celery, f"Failed to perform ceph-volume lvm batch on {device}")
        return

    # 3. Get the list of created OSDs on the device (initial pass)
    current_stage += 1
    update(
        celery,
        f"Querying OSD(s) on device {device}",
        current=current_stage,
        total=total_stages,
    )
    retcode, stdout, stderr = common.run_os_command(
        f"ceph-volume lvm list --format json {device}"
    )
    log_info(celery, f"stdout: {stdout}")
    log_info(celery, f"stderr: {stderr}")
    if retcode:
        fail(celery, f"Failed to perform ceph-volume lvm list on {device}")
        return

    created_osds = jloads(stdout)

    # 4. Prepare the WAL and DB devices
    if ext_db_flag:
        for created_osd in created_osds:
            # 4a. Get the OSD FSID and ID from the details
            osd_details = created_osds[created_osd][0]
            osd_fsid = osd_details["tags"]["ceph.osd_fsid"]
            osd_id = osd_details["tags"]["ceph.osd_id"]
            osd_lv = osd_details["lv_path"]

            current_stage += 1
            update(
                celery,
                f"Preparing DB LV for OSD {osd_id}",
                current=current_stage,
                total=total_stages,
            )

            # 4b. Prepare the logical volume if ext_db_flag
            if ext_db_ratio is not None:
                _, osd_size_bytes, _ = common.run_os_command(
                    f"blockdev --getsize64 {osd_lv}"
                )
                osd_size_bytes = int(osd_size_bytes)
                osd_db_size_bytes = int(osd_size_bytes * ext_db_ratio)
            if ext_db_size is not None:
                osd_db_size_bytes = format_bytes_fromhuman(ext_db_size)
            osd_db_size_mb = int(osd_db_size_bytes / 1024 / 1024)

            db_device = f"osd-db/osd-{osd_id}"

            current_stage += 1
            update(
                celery,
                f"Preparing Bluestore DB volume for OSD {osd_id} on {db_device}",
                current=current_stage,
                total=total_stages,
            )

            retcode, stdout, stderr = common.run_os_command(
                f"lvcreate -L {osd_db_size_mb}M -n osd-{osd_id} --yes osd-db"
            )
            log_info(celery, f"stdout: {stdout}")
            log_info(celery, f"stderr: {stderr}")
            if retcode:
                fail(celery, f"Failed to run lvcreate on {db_device}")
                return

            # 4c. Attach the new DB device to the OSD
            current_stage += 1
            update(
                celery,
                f"Attaching Bluestore DB volume to OSD {osd_id}",
                current=current_stage,
                total=total_stages,
            )
            retcode, stdout, stderr = common.run_os_command(
                f"ceph-volume lvm new-db --osd-id {osd_id} --osd-fsid {osd_fsid} --target {db_device}"
            )
            log_info(celery, f"stdout: {stdout}")
            log_info(celery, f"stderr: {stderr}")
            if retcode:
                fail(
                    celery, f"Failed to perform ceph-volume lvm new-db on OSD {osd_id}"
                )
                return

        # 4d. Get the list of created OSDs on the device (final pass)
        current_stage += 1
        update(
            celery,
            f"Requerying OSD(s) on device {device}",
            current=current_stage,
            total=total_stages,
        )
        retcode, stdout, stderr = common.run_os_command(
            f"ceph-volume lvm list --format json {device}"
        )
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            fail(celery, f"Failed to perform ceph-volume lvm list on {device}")
            return

        created_osds = jloads(stdout)

    # 5. Activate the OSDs
    for created_osd in created_osds:
        # 5a. Get the OSD FSID and ID from the details
        osd_details = created_osds[created_osd][0]
        osd_clusterfsid = osd_details["tags"]["ceph.cluster_fsid"]
        osd_fsid = osd_details["tags"]["ceph.osd_fsid"]
        osd_id = osd_details["tags"]["ceph.osd_id"]
        db_device = osd_details["tags"].get("ceph.db_device", "")
        osd_vg = osd_details["vg_name"]
        osd_lv = osd_details["lv_name"]

        # 5b. Add it to the crush map
        current_stage += 1
        update(
            celery,
            f"Adding OSD {osd_id} to CRUSH map",
            current=current_stage,
            total=total_stages,
        )
        retcode, stdout, stderr = common.run_os_command(
            f"ceph osd crush add osd.{osd_id} {weight} root=default host={node}"
        )
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            fail(celery, f"Failed to perform ceph osd crush add for OSD {osd_id}")
            return

        # 5c. Activate the OSD
        current_stage += 1
        update(
            celery,
            f"Activating OSD {osd_id}",
            current=current_stage,
            total=total_stages,
        )
        retcode, stdout, stderr = common.run_os_command(
            f"ceph-volume lvm activate --bluestore {osd_id} {osd_fsid}"
        )
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            fail(celery, f"Failed to perform ceph osd crush add for OSD {osd_id}")
            return

        # 5d. Wait 1 second for it to activate
        time.sleep(1)

        # 5e. Verify it started
        retcode, stdout, stderr = common.run_os_command(
            f"systemctl status ceph-osd@{osd_id}"
        )
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            fail(celery, f"Failed to start OSD {osd_id} process")
            return

        # 5f. Add the new OSD to PVC
        current_stage += 1
        update(
            celery,
            f"Adding OSD {osd_id} to PVC",
            current=current_stage,
            total=total_stages,
        )
        zkhandler.write(
            [
                (("osd", osd_id), ""),
                (("osd.node", osd_id), node),
                (("osd.device", osd_id), device),
                (("osd.db_device", osd_id), db_device),
                (("osd.fsid", osd_id), ""),
                (("osd.ofsid", osd_id), osd_fsid),
                (("osd.cfsid", osd_id), osd_clusterfsid),
                (("osd.lvm", osd_id), ""),
                (("osd.vg", osd_id), osd_vg),
                (("osd.lv", osd_id), osd_lv),
                (("osd.is_split", osd_id), is_split),
                (
                    ("osd.stats", osd_id),
                    '{"uuid": "|", "up": 0, "in": 0, "primary_affinity": "|", "utilization": "|", "var": "|", "pgs": "|", "kb": "|", "weight": "|", "reweight": "|", "node": "|", "used": "|", "avail": "|", "wr_ops": "|", "wr_data": "|", "rd_ops": "|", "rd_data": "|", "state": "|"}',
                ),
            ]
        )

    # 6. Wait for OSD to check in
    current_stage += 1
    update(
        celery,
        "Waiting for new OSD(s) to report stats",
        current=current_stage,
        total=total_stages,
    )

    last_osd = None
    for osd in created_osds:
        last_osd = osd

    while (
        jloads(
            zkhandler.read(
                ("osd.stats", created_osds[last_osd][0]["tags"]["ceph.osd_id"])
            )
        )["weight"]
        == "|"
    ):
        time.sleep(1)

    # 7. Log it
    current_stage += 1
    return finish(
        celery,
        f"Successfully created {len(created_osds.keys())} new OSD(s) {','.join(created_osds.keys())} on device {device}",
        current=current_stage,
        total=total_stages,
    )


def osd_worker_replace_osd(
    zkhandler,
    celery,
    node,
    osd_id,
    new_device,
    old_device=None,
    weight=None,
    ext_db_ratio=None,
    ext_db_size=None,
):
    # Try to determine if any other OSDs shared a block device with this OSD
    _, osd_list = get_list_osd(zkhandler, None)
    osd_block = zkhandler.read(("osd.device", osd_id))
    all_osds_on_block = [
        o for o in osd_list if o["node"] == node and o["device"] == osd_block
    ]
    all_osds_on_block_ids = [o["id"] for o in all_osds_on_block]

    # Set up stages
    current_stage = 0
    total_stages = 3
    _split_count = len(all_osds_on_block_ids)
    total_stages = total_stages + 10 * int(_split_count)
    if (
        ext_db_ratio is not None
        or ext_db_size is not None
        or any([True for o in all_osds_on_block if o["db_device"]])
    ):
        total_stages = total_stages + 2 * int(_split_count)

    start(
        celery,
        f"Replacing OSD(s) {','.join(all_osds_on_block_ids)} with device {new_device}",
        current=current_stage,
        total=total_stages,
    )

    # Handle a detect device if that is passed
    if match(r"detect:", new_device):
        ddevice = common.get_detect_device(new_device)
        if ddevice is None:
            fail(
                celery,
                f"Failed to determine block device from detect string {new_device}",
            )
            return
        else:
            log_info(
                celery,
                f"Determined block device {ddevice} from detect string {new_device}",
            )
            new_device = ddevice

    # Check if device has a partition table; it's not valid if it does
    retcode, _, _ = common.run_os_command(f"sfdisk --dump {new_device}")
    if retcode < 1:
        fail(
            celery,
            f"Device {new_device} has a partition table and is unsuitable for an OSD",
        )
        return

    # Phase 1: Try to determine what we can about the old device
    real_old_device = None

    # Determine information from a passed old_device
    if old_device is not None:
        found_osds = osd_worker_helper_find_osds_from_block(old_device)
        if found_osds and osd_id in found_osds.keys():
            real_old_device = old_device
        else:
            log_warn(
                celery,
                f"No OSD(s) found on device {old_device}; falling back to PVC detection",
            )

    # Try to get an old_device from our PVC information
    if real_old_device is None:
        found_osds = osd_worker_helper_find_osds_from_block(osd_block)

        if osd_id in found_osds.keys():
            real_old_device = osd_block

    if real_old_device is None:
        skip_zap = True
        log_warn(
            celery,
            "No valid old block device found for OSD(s); skipping zap",
        )
    else:
        skip_zap = False

    # Determine the weight of the OSD(s)
    if weight is None:
        weight = all_osds_on_block[0]["stats"]["weight"]

    # Take down the OSD(s), but keep it's CRUSH map details and IDs
    for osd in all_osds_on_block:
        osd_id = osd["id"]

        # 1. Set the OSD down and out so it will flush
        current_stage += 1
        update(
            celery,
            f"Setting OSD {osd_id} down",
            current=current_stage,
            total=total_stages,
        )
        retcode, stdout, stderr = common.run_os_command(f"ceph osd down {osd_id}")
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            fail(celery, f"Failed to set OSD {osd_id} down")
            return

        current_stage += 1
        update(
            celery,
            f"Setting OSD {osd_id} out",
            current=current_stage,
            total=total_stages,
        )
        retcode, stdout, stderr = common.run_os_command(f"ceph osd out {osd_id}")
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            fail(celery, f"Failed to set OSD {osd_id} out")
            return

        # 2. Wait for the OSD to be safe to remove (but don't wait for rebalancing to complete)
        current_stage += 1
        update(
            celery,
            f"Waiting for OSD {osd_id} to be safe to remove",
            current=current_stage,
            total=total_stages,
        )
        tcount = 0
        while True:
            retcode, stdout, stderr = common.run_os_command(
                f"ceph osd safe-to-destroy osd.{osd_id}"
            )
            if int(retcode) in [0, 11]:
                break
            else:
                common.run_os_command(f"ceph osd down {osd_id}")
                common.run_os_command(f"ceph osd out {osd_id}")
                time.sleep(1)
                tcount += 1
            if tcount > 60:
                log_warn(
                    celery,
                    f"Timed out (60s) waiting for OSD {osd_id} to be safe to remove; proceeding anyways",
                )
                break

        # 3. Stop the OSD process and wait for it to be terminated
        current_stage += 1
        update(
            celery,
            f"Stopping OSD {osd_id}",
            current=current_stage,
            total=total_stages,
        )
        retcode, stdout, stderr = common.run_os_command(
            f"systemctl stop ceph-osd@{osd_id}"
        )
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            fail(celery, f"Failed to stop OSD {osd_id}")
            return
        time.sleep(5)

        # 4. Destroy the OSD
        current_stage += 1
        update(
            celery,
            f"Destroying OSD {osd_id}",
            current=current_stage,
            total=total_stages,
        )
        retcode, stdout, stderr = common.run_os_command(
            f"ceph osd destroy {osd_id} --yes-i-really-mean-it"
        )
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            fail(celery, f"Failed to destroy OSD {osd_id}")
            return

    current_stage += 1
    update(
        celery,
        f"Zapping old disk {real_old_device} if possible",
        current=current_stage,
        total=total_stages,
    )
    if not skip_zap:
        # 5. Zap the old disk
        retcode, stdout, stderr = common.run_os_command(
            f"ceph-volume lvm zap --destroy {real_old_device}"
        )
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            log_warn(
                celery, f"Failed to zap old disk {real_old_device}; proceeding anyways"
            )

    # 6. Prepare the volume group on the new device
    current_stage += 1
    update(
        celery,
        f"Preparing LVM volume group on new disk {new_device}",
        current=current_stage,
        total=total_stages,
    )
    retcode, stdout, stderr = common.run_os_command(
        f"ceph-volume lvm zap --destroy {new_device}"
    )
    log_info(celery, f"stdout: {stdout}")
    log_info(celery, f"stderr: {stderr}")
    if retcode:
        fail(celery, f"Failed to run ceph-volume lvm zap on new disk {new_device}")
        return

    retcode, stdout, stderr = common.run_os_command(f"pvcreate {new_device}")
    log_info(celery, f"stdout: {stdout}")
    log_info(celery, f"stderr: {stderr}")
    if retcode:
        fail(celery, f"Failed to run pvcreate on new disk {new_device}")
        return

    vg_uuid = str(uuid4())
    retcode, stdout, stderr = common.run_os_command(
        f"vgcreate ceph-{vg_uuid} {new_device}"
    )
    log_info(celery, f"stdout: {stdout}")
    log_info(celery, f"stderr: {stderr}")
    if retcode:
        fail(celery, f"Failed to run vgcreate on new disk {new_device}")
        return

    # Determine how many OSDs we want on the new device
    osds_count = len(all_osds_on_block)

    # Determine the size of the new device
    _, new_device_size_bytes, _ = common.run_os_command(
        f"blockdev --getsize64 {new_device}"
    )

    # Calculate the size of each OSD (in MB) based on the default 4M extent size
    new_osd_size_mb = (
        int(int(int(new_device_size_bytes) / osds_count) / 1024 / 1024 / 4) * 4
    )

    # Calculate the size, if applicable, of the OSD block if we were passed a ratio
    if ext_db_ratio is not None:
        osd_new_db_size_mb = int(int(int(new_osd_size_mb * ext_db_ratio) / 4) * 4)
    elif ext_db_size is not None:
        osd_new_db_size_mb = int(
            int(int(format_bytes_fromhuman(ext_db_size)) / 1024 / 1024 / 4) * 4
        )
    else:
        if all_osds_on_block[0]["db_device"]:
            _, new_device_size_bytes, _ = common.run_os_command(
                f"blockdev --getsize64 {all_osds_on_block[0]['db_device']}"
            )
            osd_new_db_size_mb = int(
                int(int(new_device_size_bytes) / 1024 / 1024 / 4) * 4
            )
        else:
            osd_new_db_size_mb = None

    for osd in all_osds_on_block:
        osd_id = osd["id"]
        osd_fsid = osd["fsid"]

        current_stage += 1
        update(
            celery,
            f"Preparing LVM logical volume for OSD {osd_id} on new disk {new_device}",
            current=current_stage,
            total=total_stages,
        )
        retcode, stdout, stderr = common.run_os_command(
            f"lvcreate -L {new_osd_size_mb}M -n osd-block-{osd_fsid} ceph-{vg_uuid}"
        )
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            fail(celery, f"Failed to run lvcreate for OSD {osd_id}")
            return

        current_stage += 1
        update(
            celery,
            f"Preparing OSD {osd_id} on new disk {new_device}",
            current=current_stage,
            total=total_stages,
        )
        retcode, stdout, stderr = common.run_os_command(
            f"ceph-volume lvm prepare --bluestore --osd-id {osd_id} --osd-fsid {osd_fsid} --data /dev/ceph-{vg_uuid}/osd-block-{osd_fsid}"
        )
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            fail(celery, f"Failed to run ceph-volume lvm prepare for OSD {osd_id}")
            return

    for osd in all_osds_on_block:
        osd_id = osd["id"]
        osd_fsid = osd["fsid"]

        if osd["db_device"]:
            db_device = f"osd-db/osd-{osd_id}"

            current_stage += 1
            update(
                celery,
                f"Preparing Bluestore DB volume for OSD {osd_id} on {db_device}",
                current=current_stage,
                total=total_stages,
            )

            retcode, stdout, stderr = common.run_os_command(
                f"lvremove --force {db_device}"
            )
            log_info(celery, f"stdout: {stdout}")
            log_info(celery, f"stderr: {stderr}")
            if retcode:
                fail(celery, f"Failed to run lvremove on {db_device}")
                return

            retcode, stdout, stderr = common.run_os_command(
                f"lvcreate -L {osd_new_db_size_mb}M -n osd-{osd_id} --yes osd-db"
            )
            log_info(celery, f"stdout: {stdout}")
            log_info(celery, f"stderr: {stderr}")
            if retcode:
                fail(celery, f"Failed to run lvcreate on {db_device}")
                return

            current_stage += 1
            update(
                celery,
                f"Attaching Bluestore DB volume to OSD {osd_id}",
                current=current_stage,
                total=total_stages,
            )
            retcode, stdout, stderr = common.run_os_command(
                f"ceph-volume lvm new-db --osd-id {osd_id} --osd-fsid {osd_fsid} --target {db_device}"
            )
            log_info(celery, f"stdout: {stdout}")
            log_info(celery, f"stderr: {stderr}")
            if retcode:
                fail(celery, f"Failed to run ceph-volume lvm new-db for OSD {osd_id}")
                return

        current_stage += 1
        update(
            celery,
            f"Updating OSD {osd_id} in CRUSH map",
            current=current_stage,
            total=total_stages,
        )
        retcode, stdout, stderr = common.run_os_command(
            f"ceph osd crush add osd.{osd_id} {weight} root=default host={node}"
        )
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            fail(celery, f"Failed to run ceph osd crush add for OSD {osd_id}")
            return

        current_stage += 1
        update(
            celery,
            f"Activating OSD {osd_id}",
            current=current_stage,
            total=total_stages,
        )
        retcode, stdout, stderr = common.run_os_command(
            f"ceph-volume lvm activate --bluestore {osd_id} {osd_fsid}"
        )
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            fail(celery, f"Failed to run ceph-volume lvm activate for OSD {osd_id}")
            return

        # Wait 1 second for it to activate
        time.sleep(1)

        # Verify it started
        retcode, stdout, stderr = common.run_os_command(
            f"systemctl status ceph-osd@{osd_id}"
        )
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            fail(celery, f"Failed to start OSD {osd_id} process")
            return

        current_stage += 1
        update(
            celery,
            f"Updating OSD {osd_id} in PVC",
            current=current_stage,
            total=total_stages,
        )
        zkhandler.write(
            [
                (("osd.device", osd_id), new_device),
                (("osd.vg", osd_id), f"ceph-{vg_uuid}"),
                (("osd.lv", osd_id), f"osd-block-{osd_fsid}"),
            ]
        )

    # 6. Log it
    current_stage += 1
    return finish(
        celery,
        f"Successfully replaced OSD(s) {','.join(all_osds_on_block_ids)} on new disk {new_device}",
        current=current_stage,
        total=total_stages,
    )


def osd_worker_refresh_osd(
    zkhandler,
    celery,
    node,
    osd_id,
    device,
    ext_db_flag,
):
    # Try to determine if any other OSDs shared a block device with this OSD
    _, osd_list = get_list_osd(zkhandler, None)
    osd_block = zkhandler.read(("osd.device", osd_id))
    all_osds_on_block = [
        o for o in osd_list if o["node"] == node and o["device"] == osd_block
    ]
    all_osds_on_block_ids = [o["id"] for o in all_osds_on_block]

    # Set up stages
    current_stage = 0
    total_stages = 1
    _split_count = len(all_osds_on_block_ids)
    total_stages = total_stages + 3 * int(_split_count)

    start(
        celery,
        f"Refreshing/reimporting OSD(s) {','.join(all_osds_on_block_ids)} on device {device}",
        current=current_stage,
        total=total_stages,
    )

    # Handle a detect device if that is passed
    if match(r"detect:", device):
        ddevice = common.get_detect_device(device)
        if ddevice is None:
            fail(
                celery,
                f"Failed to determine block device from detect string {device}",
            )
            return
        else:
            log_info(
                celery,
                f"Determined block device {ddevice} from detect string {device}",
            )
            device = ddevice

    retcode, stdout, stderr = common.run_os_command("ceph osd ls")
    osd_list = stdout.split("\n")
    if osd_id not in osd_list:
        fail(
            celery,
            f"Could not find OSD {osd_id} in the cluster",
        )
        return

    found_osds = osd_worker_helper_find_osds_from_block(device)
    if osd_id not in found_osds.keys():
        fail(
            celery,
            f"Could not find OSD {osd_id} on device {device}",
        )
        return

    for osd in found_osds:
        found_osd = found_osds[osd][0]
        lv_device = found_osd["lv_path"]

        _, osd_pvc_information = get_list_osd(zkhandler, osd)
        osd_information = osd_pvc_information[0]

        current_stage += 1
        update(
            celery,
            "Querying for OSD on device",
            current=current_stage,
            total=total_stages,
        )
        retcode, stdout, stderr = common.run_os_command(
            f"ceph-volume lvm list --format json {lv_device}"
        )
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            fail(celery, f"Failed to run ceph-volume lvm list for OSD {osd}")
            return

        osd_detail = jloads(stdout)[osd][0]

        osd_fsid = osd_detail["tags"]["ceph.osd_fsid"]
        if osd_fsid != osd_information["fsid"]:
            fail(
                celery,
                f"OSD {osd} FSID {osd_information['fsid']} does not match volume FSID {osd_fsid}; OSD cannot be imported",
            )
            return

        dev_flags = f"--data {lv_device}"

        if ext_db_flag:
            db_device = "osd-db/osd-{osd}"
            dev_flags += f" --block.db {db_device}"

            if not path.exists(f"/dev/{db_device}"):
                fail(
                    celery,
                    f"OSD Bluestore DB volume {db_device} does not exist; OSD cannot be imported",
                )
                return
        else:
            db_device = ""

        current_stage += 1
        update(
            celery,
            f"Activating OSD {osd}",
            current=current_stage,
            total=total_stages,
        )
        retcode, stdout, stderr = common.run_os_command(
            f"ceph-volume lvm activate --bluestore {osd} {osd_fsid}"
        )
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            fail(celery, f"Failed to run ceph-volume lvm activate for OSD {osd}")
            return

        # Wait 1 second for it to activate
        time.sleep(1)

        # Verify it started
        retcode, stdout, stderr = common.run_os_command(
            f"systemctl status ceph-osd@{osd}"
        )
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            fail(celery, f"Failed to start OSD {osd} process")
            return

        current_stage += 1
        update(
            celery,
            f"Updating OSD {osd} in PVC",
            current=current_stage,
            total=total_stages,
        )
        zkhandler.write(
            [
                (("osd.device", osd), device),
                (("osd.vg", osd), osd_detail["vg_name"]),
                (("osd.lv", osd), osd_detail["lv_name"]),
            ]
        )

    # 6. Log it
    current_stage += 1
    return finish(
        celery,
        f"Successfully reimported OSD(s) {','.join(all_osds_on_block_ids)} on device {device}",
        current=current_stage,
        total=total_stages,
    )


def osd_worker_remove_osd(
    zkhandler, celery, node, osd_id, force_flag=False, skip_zap_flag=False
):
    # Get initial data
    data_device = zkhandler.read(("osd.device", osd_id))
    if zkhandler.exists(("osd.db_device", osd_id)):
        db_device = zkhandler.read(("osd.db_device", osd_id))
    else:
        db_device = None

    # Set up stages
    current_stage = 0
    total_stages = 7
    if not force_flag:
        total_stages += 1
    if not skip_zap_flag:
        total_stages += 2
    if db_device:
        total_stages += 1

    start(
        celery,
        f"Removing OSD {osd_id}",
        current=current_stage,
        total=total_stages,
    )

    # Verify the OSD is present
    retcode, stdout, stderr = common.run_os_command("ceph osd ls")
    osd_list = stdout.split("\n")
    if osd_id not in osd_list:
        if not force_flag:
            fail(
                celery,
                f"OSD {osd_id} not found in Ceph",
            )
            return
        else:
            log_warn(
                celery,
                f"OSD {osd_id} not found in Ceph; ignoring error due to force flag",
            )

    # 1. Set the OSD down and out so it will flush
    current_stage += 1
    update(
        celery,
        f"Setting OSD {osd_id} down",
        current=current_stage,
        total=total_stages,
    )
    retcode, stdout, stderr = common.run_os_command(f"ceph osd down {osd_id}")
    log_info(celery, f"stdout: {stdout}")
    log_info(celery, f"stderr: {stderr}")
    if retcode:
        if not force_flag:
            fail(
                celery,
                f"Failed to set OSD {osd_id} down",
            )
            return
        else:
            log_warn(
                celery,
                f"Failed to set OSD {osd_id} down; ignoring error due to force flag",
            )

    current_stage += 1
    update(
        celery,
        f"Setting OSD {osd_id} out",
        current=current_stage,
        total=total_stages,
    )
    retcode, stdout, stderr = common.run_os_command(f"ceph osd out {osd_id}")
    log_info(celery, f"stdout: {stdout}")
    log_info(celery, f"stderr: {stderr}")
    if retcode:
        if not force_flag:
            fail(
                celery,
                f"Failed to set OSD {osd_id} down",
            )
            return
        else:
            log_warn(
                celery,
                f"Failed to set OSD {osd_id} down; ignoring error due to force flag",
            )

    # 2. Wait for the OSD to be safe to remove (but don't wait for rebalancing to complete)
    if not force_flag:
        current_stage += 1
        update(
            celery,
            f"Waiting for OSD {osd_id} to be safe to remove",
            current=current_stage,
            total=total_stages,
        )
        tcount = 0
        while True:
            retcode, stdout, stderr = common.run_os_command(
                f"ceph osd safe-to-destroy osd.{osd_id}"
            )
            if int(retcode) in [0, 11]:
                break
            else:
                common.run_os_command(f"ceph osd down {osd_id}")
                common.run_os_command(f"ceph osd out {osd_id}")
                time.sleep(1)
                tcount += 1
            if tcount > 60:
                log_warn(
                    celery,
                    f"Timed out (60s) waiting for OSD {osd_id} to be safe to remove; proceeding anyways",
                )
                break

    # 3. Stop the OSD process and wait for it to be terminated
    current_stage += 1
    update(
        celery,
        f"Stopping OSD {osd_id}",
        current=current_stage,
        total=total_stages,
    )
    retcode, stdout, stderr = common.run_os_command(f"systemctl stop ceph-osd@{osd_id}")
    log_info(celery, f"stdout: {stdout}")
    log_info(celery, f"stderr: {stderr}")
    if retcode:
        if not force_flag:
            fail(
                celery,
                f"Failed to stop OSD {osd_id} process",
            )
            return
        else:
            log_warn(
                celery,
                f"Failed to stop OSD {osd_id} process; ignoring error due to force flag",
            )
    time.sleep(5)

    # 4. Delete OSD from ZK
    current_stage += 1
    update(
        celery,
        f"Deleting OSD {osd_id} from PVC",
        current=current_stage,
        total=total_stages,
    )

    zkhandler.delete(("osd", osd_id), recursive=True)

    # 5a. Destroy the OSD from Ceph
    current_stage += 1
    update(
        celery,
        f"Destroying OSD {osd_id}",
        current=current_stage,
        total=total_stages,
    )
    retcode, stdout, stderr = common.run_os_command(
        f"ceph osd destroy {osd_id} --yes-i-really-mean-it"
    )
    log_info(celery, f"stdout: {stdout}")
    log_info(celery, f"stderr: {stderr}")
    if retcode:
        if not force_flag:
            fail(
                celery,
                f"Failed to destroy OSD {osd_id}",
            )
            return
        else:
            log_warn(
                celery,
                f"Failed to destroy OSD {osd_id}; ignoring error due to force flag",
            )
    time.sleep(2)

    # 5b. Purge the OSD from Ceph
    current_stage += 1
    update(
        celery,
        f"Removing OSD {osd_id} from CRUSH map",
        current=current_stage,
        total=total_stages,
    )

    # Remove the OSD from the CRUSH map
    retcode, stdout, stderr = common.run_os_command(f"ceph osd crush rm osd.{osd_id}")
    log_info(celery, f"stdout: {stdout}")
    log_info(celery, f"stderr: {stderr}")
    if retcode:
        if not force_flag:
            fail(
                celery,
                f"Failed to remove OSD {osd_id} from CRUSH map",
            )
            return
        else:
            log_warn(
                celery,
                f"Failed to remove OSD {osd_id} from CRUSH map; ignoring error due to force flag",
            )

    # Purge the OSD
    current_stage += 1
    update(
        celery,
        f"Purging OSD {osd_id}",
        current=current_stage,
        total=total_stages,
    )

    if force_flag:
        force_arg = "--force"
    else:
        force_arg = ""

    retcode, stdout, stderr = common.run_os_command(
        f"ceph osd purge {osd_id} {force_arg} --yes-i-really-mean-it"
    )
    log_info(celery, f"stdout: {stdout}")
    log_info(celery, f"stderr: {stderr}")
    if retcode:
        if not force_flag:
            fail(
                celery,
                f"Failed to purge OSD {osd_id}",
            )
            return
        else:
            log_warn(
                celery,
                f"Failed to purge OSD {osd_id}; ignoring error due to force flag",
            )

    # 6. Remove the DB device
    if db_device:
        current_stage += 1
        update(
            celery,
            f"Removing OSD DB logical volume {db_device}",
            current=current_stage,
            total=total_stages,
        )
        retcode, stdout, stderr = common.run_os_command(
            f"lvremove --yes --force {db_device}"
        )
        log_info(celery, f"stdout: {stdout}")
        log_info(celery, f"stderr: {stderr}")
        if retcode:
            if not force_flag:
                fail(
                    celery,
                    f"Failed to remove OSD DB logical volume {db_device}",
                )
                return
            else:
                log_warn(
                    celery,
                    f"Failed to remove OSD DB logical volume {db_device}; ignoring error due to force flag",
                )

    if not skip_zap_flag:
        current_stage += 1
        update(
            celery,
            f"Zapping old disk {data_device} if possible",
            current=current_stage,
            total=total_stages,
        )

        # 7. Determine the block devices
        found_osds = osd_worker_helper_find_osds_from_block(data_device)
        if osd_id in found_osds.keys():
            # Try to determine if any other OSDs shared a block device with this OSD
            _, osd_list = get_list_osd(zkhandler, None)
            all_osds_on_block = [
                o for o in osd_list if o["node"] == node and o["device"] == data_device
            ]

            if len(all_osds_on_block) < 1:
                log_info(
                    celery,
                    f"Found no peer split OSD(s) on {data_device}; zapping disk",
                )
                retcode, stdout, stderr = common.run_os_command(
                    f"ceph-volume lvm zap --destroy {data_device}"
                )
                log_info(celery, f"stdout: {stdout}")
                log_info(celery, f"stderr: {stderr}")
                if retcode:
                    if not force_flag:
                        fail(
                            celery,
                            f"Failed to run ceph-volume lvm zap on device {data_device}",
                        )
                        return
                    else:
                        log_warn(
                            celery,
                            f"Failed to run ceph-volume lvm zap on device {data_device}; ignoring error due to force flag",
                        )
            else:
                log_warn(
                    celery,
                    f"Found {len(all_osds_on_block)} OSD(s) still remaining on {data_device}; skipping zap",
                )
        else:
            log_warn(
                celery,
                f"Could not find OSD {osd_id} on device {data_device}; skipping zap",
            )

    # 6. Log it
    current_stage += 1
    return finish(
        celery,
        f"Successfully removed OSD {osd_id}",
        current=current_stage,
        total=total_stages,
    )


def osd_worker_add_db_vg(zkhandler, celery, device):
    # Set up stages
    current_stage = 0
    total_stages = 4

    start(
        celery,
        f"Creating new OSD database volume group on device {device}",
        current=current_stage,
        total=total_stages,
    )
    # Check if an existsing volume group exists
    retcode, stdout, stderr = common.run_os_command("vgdisplay osd-db")
    if retcode != 5:
        fail(
            celery,
            "Ceph OSD database VG already exists",
        )
        return

    # Handle a detect device if that is passed
    if match(r"detect:", device):
        ddevice = common.get_detect_device(device)
        if ddevice is None:
            fail(
                celery,
                f"Failed to determine block device from detect string {device}",
            )
            return
        else:
            log_info(
                celery,
                f"Determined block device {ddevice} from detect string {device}",
            )
            device = ddevice

    # 1. Create an empty partition table
    current_stage += 1
    update(
        celery,
        f"Creating partitions on device {device}",
        current=current_stage,
        total=total_stages,
    )
    retcode, stdout, stderr = common.run_os_command("sgdisk --clear {}".format(device))
    log_info(celery, f"stdout: {stdout}")
    log_info(celery, f"stderr: {stderr}")
    if retcode:
        fail(
            celery,
            f"Failed to create partition table on device {device}",
        )
        return

    retcode, stdout, stderr = common.run_os_command(
        "sgdisk --new 1:: --typecode 1:8e00 {}".format(device)
    )
    log_info(celery, f"stdout: {stdout}")
    log_info(celery, f"stderr: {stderr}")
    if retcode:
        fail(
            celery,
            f"Failed to set partition type to LVM PV on device {device}",
        )
        return

    # Handle the partition ID portion
    if search(r"by-path", device) or search(r"by-id", device):
        # /dev/disk/by-path/pci-0000:03:00.0-scsi-0:1:0:0 -> pci-0000:03:00.0-scsi-0:1:0:0-part1
        partition = "{}-part1".format(device)
    elif search(r"nvme", device):
        # /dev/nvme0n1 -> nvme0n1p1
        partition = "{}p1".format(device)
    else:
        # /dev/sda -> sda1
        # No other '/dev/disk/by-*' types are valid for raw block devices anyways
        partition = "{}1".format(device)

    # 2. Create the PV
    current_stage += 1
    update(
        celery,
        f"Creating LVM PV on device {device}",
        current=current_stage,
        total=total_stages,
    )
    retcode, stdout, stderr = common.run_os_command(
        "pvcreate --force {}".format(partition)
    )
    log_info(celery, f"stdout: {stdout}")
    log_info(celery, f"stderr: {stderr}")
    if retcode:
        fail(
            celery,
            f"Failed to create LVM PV on device {device}",
        )
        return

    # 2. Create the VG (named 'osd-db')
    current_stage += 1
    update(
        celery,
        f'Creating LVM VG "osd-db" on device {device}',
        current=current_stage,
        total=total_stages,
    )
    retcode, stdout, stderr = common.run_os_command(
        "vgcreate --force osd-db {}".format(partition)
    )
    log_info(celery, f"stdout: {stdout}")
    log_info(celery, f"stderr: {stderr}")
    if retcode:
        fail(
            celery,
            f"Failed to create LVM VG on device {device}",
        )
        return

    # Log it
    current_stage += 1
    return finish(
        celery,
        f"Successfully created new OSD DB volume group on device {device}",
        current=current_stage,
        total=total_stages,
    )
