#!/usr/bin/env python3

# CephInstance.py - Class implementing a PVC node Ceph instance
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

import time
import json

import daemon_lib.common as common
from daemon_lib.ceph import format_bytes_fromhuman

from distutils.util import strtobool
from re import search, match, sub
from json import loads as jloads


def get_detect_device(detect_string):
    """
    Parses a "detect:" string into a normalized block device path using lsscsi.

    A detect string is formatted "detect:<NAME>:<SIZE>:<ID>", where
    NAME is some unique identifier in lsscsi, SIZE is a human-readable
    size value to within +/- 3% of the real size of the device, and
    ID is the Nth (0-indexed) matching entry of that NAME and SIZE.
    """
    _, name, size, idd = detect_string.split(":")
    if _ != "detect":
        return None

    retcode, stdout, stderr = common.run_os_command("lsscsi -s")
    if retcode:
        print(f"Failed to run lsscsi: {stderr}")
        return None

    # Get valid lines
    lsscsi_lines_raw = stdout.split("\n")
    lsscsi_lines = list()
    for line in lsscsi_lines_raw:
        if not line:
            continue
        split_line = line.split()
        if split_line[1] != "disk":
            continue
        lsscsi_lines.append(line)

    # Handle size determination (+/- 3%)
    lsscsi_sizes = set()
    for line in lsscsi_lines:
        lsscsi_sizes.add(split_line[-1])
    for l_size in lsscsi_sizes:
        b_size = float(sub(r"\D.", "", size))
        t_size = float(sub(r"\D.", "", l_size))

        plusthreepct = t_size * 1.03
        minusthreepct = t_size * 0.97

        if b_size > minusthreepct and b_size < plusthreepct:
            size = l_size
            break

    blockdev = None
    matches = list()
    for idx, line in enumerate(lsscsi_lines):
        # Skip non-disk entries
        if line.split()[1] != "disk":
            continue
        # Skip if name is not contained in the line (case-insensitive)
        if name.lower() not in line.lower():
            continue
        # Skip if the size does not match
        if size != line.split()[-1]:
            continue
        # Get our blockdev and append to the list
        matches.append(line.split()[-2])

    blockdev = None
    # Find the blockdev at index {idd}
    for idx, _blockdev in enumerate(matches):
        if int(idx) == int(idd):
            blockdev = _blockdev
            break

    return blockdev


class CephOSDInstance(object):
    def __init__(self, zkhandler, logger, this_node, osd_id):
        self.zkhandler = zkhandler
        self.logger = logger
        self.this_node = this_node
        self.osd_id = osd_id
        self.node = None
        self.device = None
        self.vg = None
        self.lv = None
        self.stats = dict()

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("osd.node", self.osd_id)
        )
        def watch_osd_node(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = ""

            if data and data != self.node:
                self.node = data

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("osd.stats", self.osd_id)
        )
        def watch_osd_stats(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = ""

            if data and data != self.stats:
                self.stats = json.loads(data)

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("osd.device", self.osd_id)
        )
        def watch_osd_device(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = ""

            if data and data != self.device:
                self.device = data

        # Exception conditional for migration from schema v7 to schema v8
        try:

            @self.zkhandler.zk_conn.DataWatch(
                self.zkhandler.schema.path("osd.vg", self.osd_id)
            )
            def watch_osd_vg(data, stat, event=""):
                if event and event.type == "DELETED":
                    # The key has been deleted after existing before; terminate this watcher
                    # because this class instance is about to be reaped in Daemon.py
                    return False

                try:
                    data = data.decode("ascii")
                except AttributeError:
                    data = ""

                if data and data != self.vg:
                    self.vg = data

            @self.zkhandler.zk_conn.DataWatch(
                self.zkhandler.schema.path("osd.lv", self.osd_id)
            )
            def watch_osd_lv(data, stat, event=""):
                if event and event.type == "DELETED":
                    # The key has been deleted after existing before; terminate this watcher
                    # because this class instance is about to be reaped in Daemon.py
                    return False

                try:
                    data = data.decode("ascii")
                except AttributeError:
                    data = ""

                if data and data != self.lv:
                    self.lv = data

            if self.node == self.this_node.name:
                self.update_information()
        except TypeError:
            return

    def update_information(self):
        if self.vg is not None and self.lv is not None:
            find_device = f"/dev/{self.vg}/{self.lv}"
        else:
            find_device = self.device

        self.logger.out(
            f"Updating stored disk information for OSD {self.osd_id}",
            state="i",
        )

        retcode, stdout, stderr = common.run_os_command(
            f"ceph-volume lvm list {find_device}"
        )
        osd_blockdev = None
        osd_fsid = None
        osd_clusterfsid = None
        osd_device = None
        for line in stdout.split("\n"):
            if "block device" in line:
                osd_blockdev = line.split()[-1]
            if "osd fsid" in line:
                osd_fsid = line.split()[-1]
            if "cluster fsid" in line:
                osd_clusterfsid = line.split()[-1]
            if "devices" in line:
                osd_device = line.split()[-1]

        if not osd_blockdev or not osd_fsid or not osd_clusterfsid or not osd_device:
            self.logger.out(
                f"Failed to find updated OSD information via ceph-volume for {find_device}",
                state="e",
            )
            return

        # Split OSD blockdev into VG and LV components
        # osd_blockdev = /dev/ceph-<uuid>/osd-block-<uuid>
        _, _, osd_vg, osd_lv = osd_blockdev.split("/")

        # Except for potentially the "osd.device", this should never change, but this ensures
        # that the data is added at lease once on initialization for existing OSDs.
        self.zkhandler.write(
            [
                (("osd.device", self.osd_id), osd_device),
                (("osd.fsid", self.osd_id), ""),
                (("osd.ofsid", self.osd_id), osd_fsid),
                (("osd.cfsid", self.osd_id), osd_clusterfsid),
                (("osd.lvm", self.osd_id), ""),
                (("osd.vg", self.osd_id), osd_vg),
                (("osd.lv", self.osd_id), osd_lv),
            ]
        )
        self.device = osd_device
        self.vg = osd_vg
        self.lv = osd_lv

    @staticmethod
    def add_osd(
        zkhandler,
        logger,
        node,
        device,
        weight,
        ext_db_ratio=None,
        ext_db_size=None,
        split_count=None,
    ):
        # Handle a detect device if that is passed
        if match(r"detect:", device):
            ddevice = get_detect_device(device)
            if ddevice is None:
                logger.out(
                    f"Failed to determine block device from detect string {device}",
                    state="e",
                )
                return False
            else:
                logger.out(
                    f"Determined block device {ddevice} from detect string {device}",
                    state="i",
                )
                device = ddevice

        if ext_db_size is not None and ext_db_ratio is not None:
            logger.out(
                "Invalid configuration: both an ext_db_size and ext_db_ratio were specified",
                state="e",
            )
            return False

        if ext_db_size is not None or ext_db_ratio is not None:
            ext_db_flag = True
        else:
            ext_db_flag = False

        if split_count is not None:
            split_flag = f"--osds-per-device {split_count}"
            is_split = True
            logger.out(
                f"Creating {split_count} new OSD disks on block device {device}",
                state="i",
            )
        else:
            split_flag = ""
            is_split = False
            logger.out(f"Creating 1 new OSD disk on block device {device}", state="i")

        if "nvme" in device:
            class_flag = "--crush-device-class nvme"
        else:
            class_flag = "--crush-device-class ssd"

        try:
            # 1. Zap the block device
            logger.out(f"Zapping disk {device}", state="i")
            retcode, stdout, stderr = common.run_os_command(
                f"ceph-volume lvm zap --destroy {device}"
            )
            if retcode:
                logger.out("Failed: ceph-volume lvm zap", state="e")
                logger.out(stdout, state="d")
                logger.out(stderr, state="d")
                raise Exception

            # 2. Prepare the OSD(s)
            logger.out(f"Preparing OSD(s) on disk {device}", state="i")
            retcode, stdout, stderr = common.run_os_command(
                f"ceph-volume lvm batch --yes --prepare --bluestore {split_flag} {class_flag} {device}"
            )
            if retcode:
                logger.out("Failed: ceph-volume lvm batch", state="e")
                logger.out(stdout, state="d")
                logger.out(stderr, state="d")
                raise Exception

            # 3. Get the list of created OSDs on the device (initial pass)
            logger.out(f"Querying OSD(s) on disk {device}", state="i")
            retcode, stdout, stderr = common.run_os_command(
                f"ceph-volume lvm list --format json {device}"
            )
            if retcode:
                logger.out("Failed: ceph-volume lvm list", state="e")
                logger.out(stdout, state="d")
                logger.out(stderr, state="d")
                raise Exception

            created_osds = jloads(stdout)

            # 4. Prepare the WAL and DB devices
            if ext_db_flag:
                for created_osd in created_osds:
                    # 4a. Get the OSD FSID and ID from the details
                    osd_details = created_osds[created_osd][0]
                    osd_fsid = osd_details["tags"]["ceph.osd_fsid"]
                    osd_id = osd_details["tags"]["ceph.osd_id"]
                    osd_lv = osd_details["lv_path"]

                    logger.out(
                        f"Creating Bluestore DB volume for OSD {osd_id}", state="i"
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

                    result = CephOSDInstance.create_osd_db_lv(
                        zkhandler, logger, osd_id, osd_db_size_bytes
                    )
                    if not result:
                        raise Exception
                    db_device = f"osd-db/osd-{osd_id}"

                    # 4c. Attach the new DB device to the OSD
                    retcode, stdout, stderr = common.run_os_command(
                        f"ceph-volume lvm new-db --osd-id {osd_id} --osd-fsid {osd_fsid} --target {db_device}"
                    )
                    if retcode:
                        logger.out("Failed: ceph-volume lvm new-db", state="e")
                        logger.out(stdout, state="d")
                        logger.out(stderr, state="d")
                        raise Exception

                # 4d. Get the list of created OSDs on the device (final pass)
                logger.out(f"(Requerying OSD(s) on disk {device}", state="i")
                retcode, stdout, stderr = common.run_os_command(
                    f"ceph-volume lvm list --format json {device}"
                )
                if retcode:
                    logger.out("Failed: ceph-volume lvm list", state="e")
                    logger.out(stdout, state="d")
                    logger.out(stderr, state="d")
                    raise Exception

                created_osds = jloads(stdout)

            # 5. Activate the OSDs
            logger.out(f"Activating OSD(s) on disk {device}", state="i")
            for created_osd in created_osds:
                # 5a. Get the OSD FSID and ID from the details
                osd_details = created_osds[created_osd][0]
                osd_clusterfsid = osd_details["tags"]["ceph.cluster_fsid"]
                osd_fsid = osd_details["tags"]["ceph.osd_fsid"]
                osd_id = osd_details["tags"]["ceph.osd_id"]
                db_device = osd_details["tags"].get("ceph.db_device", "")
                osd_vg = osd_details["vg_name"]
                osd_lv = osd_details["lv_name"]

                # 5b. Activate the OSD
                logger.out(f"Activating OSD {osd_id}", state="i")
                retcode, stdout, stderr = common.run_os_command(
                    f"ceph-volume lvm activate --bluestore {osd_id} {osd_fsid}"
                )
                if retcode:
                    logger.out("Failed: ceph-volume lvm activate", state="e")
                    logger.out(stdout, state="d")
                    logger.out(stderr, state="d")
                    raise Exception

                # 5c. Add it to the crush map
                logger.out(f"Adding OSD {osd_id} to CRUSH map", state="i")
                retcode, stdout, stderr = common.run_os_command(
                    f"ceph osd crush add osd.{osd_id} {weight} root=default host={node}"
                )
                if retcode:
                    logger.out("Failed: ceph osd crush add", state="e")
                    logger.out(stdout, state="d")
                    logger.out(stderr, state="d")
                    raise Exception

                # 5d. Wait half a second for it to activate
                time.sleep(0.5)

                # 5e. Verify it started
                retcode, stdout, stderr = common.run_os_command(
                    "systemctl status ceph-osd@{osdid}".format(osdid=osd_id)
                )
                if retcode:
                    logger.out(f"Failed: OSD {osd_id} unit is not active", state="e")
                    logger.out(stdout, state="d")
                    logger.out(stderr, state="d")
                    raise Exception

                # 5f. Add the new OSD to PVC
                logger.out(f"Adding OSD {osd_id} to PVC", state="i")
                zkhandler.write(
                    [
                        (("osd", osd_id), ""),
                        (("osd.node", osd_id), node),
                        (("osd.device", osd_id), device),
                        (("osd.db_device", osd_id), db_device),
                        (("osd.fsid", osd_id), osd_fsid),
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

            # 6. Log it
            logger.out(
                f"Successfully created {split_count} new OSD(s) {','.join(created_osds.keys())} on disk {device}",
                state="o",
            )
            return True
        except Exception as e:
            logger.out(
                f"Failed to create {split_count} new OSD(s) on disk {device}: {e}",
                state="e",
            )
            return False

    @staticmethod
    def replace_osd(
        zkhandler,
        logger,
        node,
        osd_id,
        old_device,
        new_device,
        weight,
        ext_db_flag=False,
    ):
        # Handle a detect device if that is passed
        if match(r"detect:", new_device):
            ddevice = get_detect_device(new_device)
            if ddevice is None:
                logger.out(
                    f"Failed to determine block device from detect string {new_device}",
                    state="e",
                )
                return False
            else:
                logger.out(
                    f"Determined block device {ddevice} from detect string {new_device}",
                    state="i",
                )
                new_device = ddevice

        # We are ready to create a new OSD on this node
        logger.out(
            "Replacing OSD {} disk with block device {}".format(osd_id, new_device),
            state="i",
        )
        try:
            # Verify the OSD is present
            retcode, stdout, stderr = common.run_os_command("ceph osd ls")
            osd_list = stdout.split("\n")
            if osd_id not in osd_list:
                logger.out(
                    "Could not find OSD {} in the cluster".format(osd_id), state="e"
                )
                return True

            # 1. Set the OSD down and out so it will flush
            logger.out("Setting down OSD disk with ID {}".format(osd_id), state="i")
            retcode, stdout, stderr = common.run_os_command(
                "ceph osd down {}".format(osd_id)
            )
            if retcode:
                print("ceph osd down")
                print(stdout)
                print(stderr)
                raise Exception

            logger.out("Setting out OSD disk with ID {}".format(osd_id), state="i")
            retcode, stdout, stderr = common.run_os_command(
                "ceph osd out {}".format(osd_id)
            )
            if retcode:
                print("ceph osd out")
                print(stdout)
                print(stderr)
                raise Exception

            # 2. Wait for the OSD to be safe to remove (but don't wait for rebalancing to complete)
            logger.out(f"Waiting for OSD {osd_id} to be safe to remove", state="i")
            while True:
                retcode, stdout, stderr = common.run_os_command(
                    f"ceph osd safe-to-destroy osd.{osd_id}"
                )
                if retcode in [0, 11]:
                    # Code 0 = success
                    # Code 11 = "Error EAGAIN: OSD(s) 5 have no reported stats, and not all PGs are active+clean; we cannot draw any conclusions." which means all PGs have been remappped but backfill is still occurring
                    break
                else:
                    time.sleep(5)

            # 3. Stop the OSD process
            logger.out("Stopping OSD disk with ID {}".format(osd_id), state="i")
            retcode, stdout, stderr = common.run_os_command(
                "systemctl stop ceph-osd@{}".format(osd_id)
            )
            if retcode:
                print("systemctl stop")
                print(stdout)
                print(stderr)
                raise Exception
            time.sleep(2)

            # 4. Destroy the OSD
            logger.out("Destroying OSD with ID {osd_id}", state="i")
            retcode, stdout, stderr = common.run_os_command(
                f"ceph osd destroy {osd_id} --yes-i-really-mean-it"
            )
            if retcode:
                print("ceph osd destroy")
                print(stdout)
                print(stderr)
                raise Exception

            # 5. Adjust the weight
            logger.out(
                "Adjusting weight of OSD disk with ID {} in CRUSH map".format(osd_id),
                state="i",
            )
            retcode, stdout, stderr = common.run_os_command(
                "ceph osd crush reweight osd.{osdid} {weight}".format(
                    osdid=osd_id, weight=weight
                )
            )
            if retcode:
                print("ceph osd crush reweight")
                print(stdout)
                print(stderr)
                raise Exception

            # 6a. Zap the new disk to ensure it is ready to go
            logger.out("Zapping disk {}".format(new_device), state="i")
            retcode, stdout, stderr = common.run_os_command(
                "ceph-volume lvm zap --destroy {}".format(new_device)
            )
            if retcode:
                print("ceph-volume lvm zap")
                print(stdout)
                print(stderr)
                raise Exception

            dev_flags = "--data {}".format(new_device)

            # 6b. Prepare the logical volume if ext_db_flag
            if ext_db_flag:
                db_device = "osd-db/osd-{}".format(osd_id)
                dev_flags += " --block.db {}".format(db_device)
            else:
                db_device = ""

            # 6c. Replace the OSD
            logger.out(
                "Preparing LVM for replaced OSD {} disk on {}".format(
                    osd_id, new_device
                ),
                state="i",
            )
            retcode, stdout, stderr = common.run_os_command(
                "ceph-volume lvm prepare --osd-id {osdid} --bluestore {devices}".format(
                    osdid=osd_id, devices=dev_flags
                )
            )
            if retcode:
                print("ceph-volume lvm prepare")
                print(stdout)
                print(stderr)
                raise Exception

            # 7a. Get OSD information
            logger.out(
                "Getting OSD information for ID {} on {}".format(osd_id, new_device),
                state="i",
            )
            retcode, stdout, stderr = common.run_os_command(
                "ceph-volume lvm list {device}".format(device=new_device)
            )
            for line in stdout.split("\n"):
                if "block device" in line:
                    osd_blockdev = line.split()[-1]
                if "osd fsid" in line:
                    osd_fsid = line.split()[-1]
                if "cluster fsid" in line:
                    osd_clusterfsid = line.split()[-1]
                if "devices" in line:
                    osd_device = line.split()[-1]

            if not osd_fsid:
                print("ceph-volume lvm list")
                print("Could not find OSD information in data:")
                print(stdout)
                print(stderr)
                raise Exception

            # Split OSD blockdev into VG and LV components
            # osd_blockdev = /dev/ceph-<uuid>/osd-block-<uuid>
            _, _, osd_vg, osd_lv = osd_blockdev.split("/")

            # Reset whatever we were given to Ceph's /dev/xdX naming
            if new_device != osd_device:
                new_device = osd_device

            # 7b. Activate the OSD
            logger.out("Activating new OSD disk with ID {}".format(osd_id), state="i")
            retcode, stdout, stderr = common.run_os_command(
                "ceph-volume lvm activate --bluestore {osdid} {osdfsid}".format(
                    osdid=osd_id, osdfsid=osd_fsid
                )
            )
            if retcode:
                print("ceph-volume lvm activate")
                print(stdout)
                print(stderr)
                raise Exception

            time.sleep(0.5)

            # 8. Verify it started
            retcode, stdout, stderr = common.run_os_command(
                "systemctl status ceph-osd@{osdid}".format(osdid=osd_id)
            )
            if retcode:
                print("systemctl status")
                print(stdout)
                print(stderr)
                raise Exception

            # 9. Update Zookeeper information
            logger.out(
                "Adding new OSD disk with ID {} to Zookeeper".format(osd_id), state="i"
            )
            zkhandler.write(
                [
                    (("osd", osd_id), ""),
                    (("osd.node", osd_id), node),
                    (("osd.device", osd_id), new_device),
                    (("osd.db_device", osd_id), db_device),
                    (("osd.fsid", osd_id), ""),
                    (("osd.ofsid", osd_id), osd_fsid),
                    (("osd.cfsid", osd_id), osd_clusterfsid),
                    (("osd.lvm", osd_id), ""),
                    (("osd.vg", osd_id), osd_vg),
                    (("osd.lv", osd_id), osd_lv),
                    (
                        ("osd.stats", osd_id),
                        '{"uuid": "|", "up": 0, "in": 0, "primary_affinity": "|", "utilization": "|", "var": "|", "pgs": "|", "kb": "|", "weight": "|", "reweight": "|", "node": "|", "used": "|", "avail": "|", "wr_ops": "|", "wr_data": "|", "rd_ops": "|", "rd_data": "|", "state": "|"}',
                    ),
                ]
            )

            # Log it
            logger.out(
                "Replaced OSD {} disk with device {}".format(osd_id, new_device),
                state="o",
            )
            return True
        except Exception as e:
            # Log it
            logger.out("Failed to replace OSD {} disk: {}".format(osd_id, e), state="e")
            return False

    @staticmethod
    def refresh_osd(zkhandler, logger, node, osd_id, device, ext_db_flag):
        # Handle a detect device if that is passed
        if match(r"detect:", device):
            ddevice = get_detect_device(device)
            if ddevice is None:
                logger.out(
                    f"Failed to determine block device from detect string {device}",
                    state="e",
                )
                return False
            else:
                logger.out(
                    f"Determined block device {ddevice} from detect string {device}",
                    state="i",
                )
                device = ddevice

        # We are ready to create a new OSD on this node
        logger.out(
            "Refreshing OSD {} disk on block device {}".format(osd_id, device),
            state="i",
        )
        try:
            # 1. Verify the OSD is present
            retcode, stdout, stderr = common.run_os_command("ceph osd ls")
            osd_list = stdout.split("\n")
            if osd_id not in osd_list:
                logger.out(
                    "Could not find OSD {} in the cluster".format(osd_id), state="e"
                )
                return True

            dev_flags = "--data {}".format(device)

            if ext_db_flag:
                db_device = "osd-db/osd-{}".format(osd_id)
                dev_flags += " --block.db {}".format(db_device)
            else:
                db_device = ""

            # 2. Get OSD information
            logger.out(
                "Getting OSD information for ID {} on {}".format(osd_id, device),
                state="i",
            )
            retcode, stdout, stderr = common.run_os_command(
                "ceph-volume lvm list {device}".format(device=device)
            )
            for line in stdout.split("\n"):
                if "block device" in line:
                    osd_blockdev = line.split()[-1]
                if "osd fsid" in line:
                    osd_fsid = line.split()[-1]
                if "cluster fsid" in line:
                    osd_clusterfsid = line.split()[-1]
                if "devices" in line:
                    osd_device = line.split()[-1]

            if not osd_fsid:
                print("ceph-volume lvm list")
                print("Could not find OSD information in data:")
                print(stdout)
                print(stderr)
                raise Exception

            # Split OSD blockdev into VG and LV components
            # osd_blockdev = /dev/ceph-<uuid>/osd-block-<uuid>
            _, _, osd_vg, osd_lv = osd_blockdev.split("/")

            # Reset whatever we were given to Ceph's /dev/xdX naming
            if device != osd_device:
                device = osd_device

            # 3. Activate the OSD
            logger.out("Activating new OSD disk with ID {}".format(osd_id), state="i")
            retcode, stdout, stderr = common.run_os_command(
                "ceph-volume lvm activate --bluestore {osdid} {osdfsid}".format(
                    osdid=osd_id, osdfsid=osd_fsid
                )
            )
            if retcode:
                print("ceph-volume lvm activate")
                print(stdout)
                print(stderr)
                raise Exception

            time.sleep(0.5)

            # 4. Verify it started
            retcode, stdout, stderr = common.run_os_command(
                "systemctl status ceph-osd@{osdid}".format(osdid=osd_id)
            )
            if retcode:
                print("systemctl status")
                print(stdout)
                print(stderr)
                raise Exception

            # 5. Update Zookeeper information
            logger.out(
                "Adding new OSD disk with ID {} to Zookeeper".format(osd_id), state="i"
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
                    (
                        ("osd.stats", osd_id),
                        '{"uuid": "|", "up": 0, "in": 0, "primary_affinity": "|", "utilization": "|", "var": "|", "pgs": "|", "kb": "|", "weight": "|", "reweight": "|", "node": "|", "used": "|", "avail": "|", "wr_ops": "|", "wr_data": "|", "rd_ops": "|", "rd_data": "|", "state": "|"}',
                    ),
                ]
            )

            # Log it
            logger.out("Refreshed OSD {} disk on {}".format(osd_id, device), state="o")
            return True
        except Exception as e:
            # Log it
            logger.out("Failed to refresh OSD {} disk: {}".format(osd_id, e), state="e")
            return False

    @staticmethod
    def remove_osd(zkhandler, logger, osd_id, osd_obj, force_flag):
        logger.out("Removing OSD {}".format(osd_id), state="i")
        try:
            # Verify the OSD is present
            retcode, stdout, stderr = common.run_os_command("ceph osd ls")
            osd_list = stdout.split("\n")
            if osd_id not in osd_list:
                logger.out(
                    "Could not find OSD {} in the cluster".format(osd_id), state="e"
                )
                if force_flag:
                    logger.out("Ignoring error due to force flag", state="i")
                else:
                    return True

            # 1. Set the OSD down and out so it will flush
            logger.out("Setting down OSD {}".format(osd_id), state="i")
            retcode, stdout, stderr = common.run_os_command(
                "ceph osd down {}".format(osd_id)
            )
            if retcode:
                print("ceph osd down")
                print(stdout)
                print(stderr)
                if force_flag:
                    logger.out("Ignoring error due to force flag", state="i")
                else:
                    raise Exception

            logger.out("Setting out OSD {}".format(osd_id), state="i")
            retcode, stdout, stderr = common.run_os_command(
                "ceph osd out {}".format(osd_id)
            )
            if retcode:
                print("ceph osd out")
                print(stdout)
                print(stderr)
                if force_flag:
                    logger.out("Ignoring error due to force flag", state="i")
                else:
                    raise Exception

            # 2. Wait for the OSD to be safe to remove (but don't wait for rebalancing to complete)
            logger.out(f"Waiting for OSD {osd_id} to be safe to remove", state="i")
            while True:
                retcode, stdout, stderr = common.run_os_command(
                    f"ceph osd safe-to-destroy osd.{osd_id}"
                )
                if int(retcode) in [0, 11]:
                    break
                else:
                    time.sleep(5)

            # 3. Stop the OSD process and wait for it to be terminated
            logger.out("Stopping OSD {}".format(osd_id), state="i")
            retcode, stdout, stderr = common.run_os_command(
                "systemctl stop ceph-osd@{}".format(osd_id)
            )
            if retcode:
                print("systemctl stop")
                print(stdout)
                print(stderr)
                if force_flag:
                    logger.out("Ignoring error due to force flag", state="i")
                else:
                    raise Exception
            time.sleep(2)

            # 4. Determine the block devices
            osd_vg = zkhandler.read(("osd.vg", osd_id))
            osd_lv = zkhandler.read(("osd.lv", osd_id))
            osd_lvm = f"/dev/{osd_vg}/{osd_lv}"
            osd_device = None

            logger.out(
                f"Getting disk info for OSD {osd_id} LV {osd_lvm}",
                state="i",
            )
            retcode, stdout, stderr = common.run_os_command(
                f"ceph-volume lvm list {osd_lvm}"
            )
            for line in stdout.split("\n"):
                if "devices" in line:
                    osd_device = line.split()[-1]

            if not osd_device:
                print("ceph-volume lvm list")
                print("Could not find OSD information in data:")
                print(stdout)
                print(stderr)
                if force_flag:
                    logger.out("Ignoring error due to force flag", state="i")
                else:
                    raise Exception

            # 5. Purge the OSD from Ceph
            logger.out("Purging OSD {}".format(osd_id), state="i")
            retcode, stdout, stderr = common.run_os_command(
                "ceph osd purge {} --yes-i-really-mean-it".format(osd_id)
            )
            if retcode:
                print("ceph osd purge")
                print(stdout)
                print(stderr)
                if force_flag:
                    logger.out("Ignoring error due to force flag", state="i")
                else:
                    raise Exception

            # 7. Remove the DB device
            if zkhandler.exists(("osd.db_device", osd_id)):
                db_device = zkhandler.read(("osd.db_device", osd_id))
                logger.out(
                    'Removing OSD DB logical volume "{}"'.format(db_device), state="i"
                )
                retcode, stdout, stderr = common.run_os_command(
                    "lvremove --yes --force {}".format(db_device)
                )

            # 8. Delete OSD from ZK
            logger.out("Deleting OSD {} from Zookeeper".format(osd_id), state="i")
            zkhandler.delete(("osd", osd_id), recursive=True)

            # Log it
            logger.out("Successfully removed OSD {}".format(osd_id), state="o")
            return True
        except Exception as e:
            # Log it
            logger.out("Failed to remove OSD {}: {}".format(osd_id, e), state="e")
            return False

    @staticmethod
    def add_db_vg(zkhandler, logger, device):
        # Check if an existsing volume group exists
        retcode, stdout, stderr = common.run_os_command("vgdisplay osd-db")
        if retcode != 5:
            logger.out('Ceph OSD database VG "osd-db" already exists', state="e")
            return False

        # Handle a detect device if that is passed
        if match(r"detect:", device):
            ddevice = get_detect_device(device)
            if ddevice is None:
                logger.out(
                    f"Failed to determine block device from detect string {device}",
                    state="e",
                )
                return False
            else:
                logger.out(
                    f"Determined block device {ddevice} from detect string {device}",
                    state="i",
                )
                device = ddevice

        logger.out(
            "Creating new OSD database volume group on block device {}".format(device),
            state="i",
        )
        try:
            # 1. Create an empty partition table
            logger.out(
                "Creating partitions on block device {}".format(device), state="i"
            )
            retcode, stdout, stderr = common.run_os_command(
                "sgdisk --clear {}".format(device)
            )
            if retcode:
                print("sgdisk create partition table")
                print(stdout)
                print(stderr)
                raise Exception

            retcode, stdout, stderr = common.run_os_command(
                "sgdisk --new 1:: --typecode 1:8e00 {}".format(device)
            )
            if retcode:
                print("sgdisk create pv partition")
                print(stdout)
                print(stderr)
                raise Exception

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
            logger.out("Creating PV on block device {}".format(partition), state="i")
            retcode, stdout, stderr = common.run_os_command(
                "pvcreate --force {}".format(partition)
            )
            if retcode:
                print("pv creation")
                print(stdout)
                print(stderr)
                raise Exception

            # 2. Create the VG (named 'osd-db')
            logger.out(
                'Creating VG "osd-db" on block device {}'.format(partition), state="i"
            )
            retcode, stdout, stderr = common.run_os_command(
                "vgcreate --force osd-db {}".format(partition)
            )
            if retcode:
                print("vg creation")
                print(stdout)
                print(stderr)
                raise Exception

            # Log it
            logger.out(
                "Created new OSD database volume group on block device {}".format(
                    device
                ),
                state="o",
            )
            return True
        except Exception as e:
            # Log it
            logger.out(
                "Failed to create OSD database volume group: {}".format(e), state="e"
            )
            return False

    @staticmethod
    def create_osd_db_lv(zkhandler, logger, osd_id, osd_db_size_bytes):
        logger.out(
            "Creating new OSD database logical volume for OSD ID {}".format(osd_id),
            state="i",
        )
        try:
            # 0. Check if an existsing logical volume exists
            retcode, stdout, stderr = common.run_os_command(
                "lvdisplay osd-db/osd{}".format(osd_id)
            )
            if retcode != 5:
                logger.out(
                    'Ceph OSD database LV "osd-db/osd{}" already exists'.format(osd_id),
                    state="e",
                )
                return False

            # 1. Determine LV sizing
            osd_db_size_m = int(osd_db_size_bytes / 1024 / 1024)

            # 2. Create the LV
            logger.out(
                f'Creating DB LV "osd-db/osd-{osd_id}" of size {osd_db_size_m}M',
                state="i",
            )
            retcode, stdout, stderr = common.run_os_command(
                "lvcreate --yes --name osd-{} --size {} osd-db".format(
                    osd_id, osd_db_size_m
                )
            )
            if retcode:
                print("db lv creation")
                print(stdout)
                print(stderr)
                raise Exception

            # Log it
            logger.out(
                'Created new OSD database logical volume "osd-db/osd-{}"'.format(
                    osd_id
                ),
                state="o",
            )
            return True
        except Exception as e:
            # Log it
            logger.out(
                "Failed to create OSD database logical volume: {}".format(e), state="e"
            )
            return False


class CephPoolInstance(object):
    def __init__(self, zkhandler, logger, this_node, name):
        self.zkhandler = zkhandler
        self.logger = logger
        self.this_node = this_node
        self.name = name
        self.pgs = ""
        self.stats = dict()

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("pool.pgs", self.name)
        )
        def watch_pool_node(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = ""

            if data and data != self.pgs:
                self.pgs = data

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("pool.stats", self.name)
        )
        def watch_pool_stats(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = ""

            if data and data != self.stats:
                self.stats = json.loads(data)


class CephVolumeInstance(object):
    def __init__(self, zkhandler, logger, this_node, pool, name):
        self.zkhandler = zkhandler
        self.logger = logger
        self.this_node = this_node
        self.pool = pool
        self.name = name
        self.stats = dict()

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("volume.stats", f"{self.pool}/{self.name}")
        )
        def watch_volume_stats(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = ""

            if data and data != self.stats:
                self.stats = json.loads(data)


class CephSnapshotInstance(object):
    def __init__(self, zkhandler, this_node, pool, volume, name):
        self.zkhandler = zkhandler
        self.this_node = this_node
        self.pool = pool
        self.volume = volume
        self.name = name
        self.stats = dict()

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path(
                "snapshot.stats", f"{self.pool}/{self.volume}/{self.name}"
            )
        )
        def watch_snapshot_stats(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = ""

            if data and data != self.stats:
                self.stats = json.loads(data)


# Primary command function
# This command pipe is only used for OSD adds and removes
def ceph_command(zkhandler, logger, this_node, data, d_osd):
    # Get the command and args; the * + join ensures arguments with spaces (e.g. detect strings) are recombined right
    command, *args = data.split()
    args = " ".join(args)

    # Adding a new OSD
    if command == "osd_add":
        (
            node,
            device,
            weight,
            ext_db_ratio,
            ext_db_size,
            split_count,
        ) = args.split(",")
        try:
            ext_db_ratio = float(ext_db_ratio)
        except Exception:
            ext_db_ratio = None
        try:
            split_count = int(split_count)
        except Exception:
            split_count = None

        if node == this_node.name:
            # Lock the command queue
            zk_lock = zkhandler.writelock("base.cmd.ceph")
            with zk_lock:
                # Add the OSD
                result = CephOSDInstance.add_osd(
                    zkhandler,
                    logger,
                    node,
                    device,
                    weight,
                    ext_db_ratio,
                    ext_db_size,
                    split_count,
                )
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.write([("base.cmd.ceph", "success-{}".format(data))])
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.write([("base.cmd.ceph", "failure-{}".format(data))])
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Replacing an OSD
    if command == "osd_replace":
        node, osd_id, old_device, new_device, weight, ext_db_flag = args.split(",")
        ext_db_flag = bool(strtobool(ext_db_flag))
        if node == this_node.name:
            # Lock the command queue
            zk_lock = zkhandler.writelock("base.cmd.ceph")
            with zk_lock:
                # Add the OSD
                result = CephOSDInstance.replace_osd(
                    zkhandler,
                    logger,
                    node,
                    osd_id,
                    old_device,
                    new_device,
                    weight,
                    ext_db_flag,
                )
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.write([("base.cmd.ceph", "success-{}".format(data))])
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.write([("base.cmd.ceph", "failure-{}".format(data))])
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Refreshing an OSD
    if command == "osd_refresh":
        node, osd_id, device, ext_db_flag = args.split(",")
        ext_db_flag = bool(strtobool(ext_db_flag))
        if node == this_node.name:
            # Lock the command queue
            zk_lock = zkhandler.writelock("base.cmd.ceph")
            with zk_lock:
                # Add the OSD
                result = CephOSDInstance.refresh_osd(
                    zkhandler, logger, node, osd_id, device, ext_db_flag
                )
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.write([("base.cmd.ceph", "success-{}".format(data))])
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.write([("base.cmd.ceph", "failure-{}".format(data))])
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Removing an OSD
    elif command == "osd_remove":
        osd_id, force = args.split(",")
        force_flag = bool(strtobool(force))

        # Verify osd_id is in the list
        if osd_id not in d_osd.keys():
            return

        if d_osd[osd_id] and d_osd[osd_id].node == this_node.name:
            # Lock the command queue
            zk_lock = zkhandler.writelock("base.cmd.ceph")
            with zk_lock:
                # Remove the OSD
                result = CephOSDInstance.remove_osd(
                    zkhandler, logger, osd_id, d_osd[osd_id], force_flag
                )
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.write([("base.cmd.ceph", "success-{}".format(data))])
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.write([("base.cmd.ceph", "failure-{}".format(data))])
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)

    # Adding a new DB VG
    elif command == "db_vg_add":
        node, device = args.split(",")
        if node == this_node.name:
            # Lock the command queue
            zk_lock = zkhandler.writelock("base.cmd.ceph")
            with zk_lock:
                # Add the VG
                result = CephOSDInstance.add_db_vg(zkhandler, logger, device)
                # Command succeeded
                if result:
                    # Update the command queue
                    zkhandler.write([("base.cmd.ceph", "success-{}".format(data))])
                # Command failed
                else:
                    # Update the command queue
                    zkhandler.write([("base.cmd.ceph", "failure={}".format(data))])
                # Wait 1 seconds before we free the lock, to ensure the client hits the lock
                time.sleep(1)
