#!/usr/bin/env python3

# CephInstance.py - Class implementing a PVC node Ceph instance
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

import time
import json
import psutil

import daemon_lib.common as common

from distutils.util import strtobool
from re import search, match, sub


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
    def __init__(self, zkhandler, this_node, osd_id):
        self.zkhandler = zkhandler
        self.this_node = this_node
        self.osd_id = osd_id
        self.node = None
        self.size = None
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

    @staticmethod
    def add_osd(
        zkhandler, logger, node, device, weight, ext_db_flag=False, ext_db_ratio=0.05
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

        # We are ready to create a new OSD on this node
        logger.out("Creating new OSD disk on block device {}".format(device), state="i")
        try:
            # 1. Create an OSD; we do this so we know what ID will be gen'd
            retcode, stdout, stderr = common.run_os_command("ceph osd create")
            if retcode:
                print("ceph osd create")
                print(stdout)
                print(stderr)
                raise Exception
            osd_id = stdout.rstrip()

            # 2. Remove that newly-created OSD
            retcode, stdout, stderr = common.run_os_command(
                "ceph osd rm {}".format(osd_id)
            )
            if retcode:
                print("ceph osd rm")
                print(stdout)
                print(stderr)
                raise Exception

            # 3a. Zap the disk to ensure it is ready to go
            logger.out("Zapping disk {}".format(device), state="i")
            retcode, stdout, stderr = common.run_os_command(
                "ceph-volume lvm zap --destroy {}".format(device)
            )
            if retcode:
                print("ceph-volume lvm zap")
                print(stdout)
                print(stderr)
                raise Exception

            dev_flags = "--data {}".format(device)

            # 3b. Prepare the logical volume if ext_db_flag
            if ext_db_flag:
                _, osd_size_bytes, _ = common.run_os_command(
                    "blockdev --getsize64 {}".format(device)
                )
                osd_size_bytes = int(osd_size_bytes)
                result = CephOSDInstance.create_osd_db_lv(
                    zkhandler, logger, osd_id, ext_db_ratio, osd_size_bytes
                )
                if not result:
                    raise Exception
                db_device = "osd-db/osd-{}".format(osd_id)
                dev_flags += " --block.db {}".format(db_device)
            else:
                db_device = ""

            # 3c. Create the OSD for real
            logger.out(
                "Preparing LVM for new OSD disk with ID {} on {}".format(
                    osd_id, device
                ),
                state="i",
            )
            retcode, stdout, stderr = common.run_os_command(
                "ceph-volume lvm prepare --bluestore {devices}".format(
                    devices=dev_flags
                )
            )
            if retcode:
                print("ceph-volume lvm prepare")
                print(stdout)
                print(stderr)
                raise Exception

            # 4a. Get OSD FSID
            logger.out(
                "Getting OSD FSID for ID {} on {}".format(osd_id, device), state="i"
            )
            retcode, stdout, stderr = common.run_os_command(
                "ceph-volume lvm list {device}".format(device=device)
            )
            for line in stdout.split("\n"):
                if "osd fsid" in line:
                    osd_fsid = line.split()[-1]

            if not osd_fsid:
                print("ceph-volume lvm list")
                print("Could not find OSD fsid in data:")
                print(stdout)
                print(stderr)
                raise Exception

            # 4b. Activate the OSD
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

            # 5. Add it to the crush map
            logger.out(
                "Adding new OSD disk with ID {} to CRUSH map".format(osd_id), state="i"
            )
            retcode, stdout, stderr = common.run_os_command(
                "ceph osd crush add osd.{osdid} {weight} root=default host={node}".format(
                    osdid=osd_id, weight=weight, node=node
                )
            )
            if retcode:
                print("ceph osd crush add")
                print(stdout)
                print(stderr)
                raise Exception
            time.sleep(0.5)

            # 6. Verify it started
            retcode, stdout, stderr = common.run_os_command(
                "systemctl status ceph-osd@{osdid}".format(osdid=osd_id)
            )
            if retcode:
                print("systemctl status")
                print(stdout)
                print(stderr)
                raise Exception

            # 7. Add the new OSD to the list
            logger.out(
                "Adding new OSD disk with ID {} to Zookeeper".format(osd_id), state="i"
            )
            zkhandler.write(
                [
                    (("osd", osd_id), ""),
                    (("osd.node", osd_id), node),
                    (("osd.device", osd_id), device),
                    (("osd.db_device", osd_id), db_device),
                    (("osd.stats", osd_id), "{}"),
                ]
            )

            # Log it
            logger.out("Created new OSD disk with ID {}".format(osd_id), state="o")
            return True
        except Exception as e:
            # Log it
            logger.out("Failed to create new OSD disk: {}".format(e), state="e")
            return False

    @staticmethod
    def remove_osd(zkhandler, logger, osd_id, osd_obj):
        logger.out("Removing OSD disk {}".format(osd_id), state="i")
        try:
            # 1. Verify the OSD is present
            retcode, stdout, stderr = common.run_os_command("ceph osd ls")
            osd_list = stdout.split("\n")
            if osd_id not in osd_list:
                logger.out(
                    "Could not find OSD {} in the cluster".format(osd_id), state="e"
                )
                return True

            # 1. Set the OSD out so it will flush
            logger.out("Setting out OSD disk with ID {}".format(osd_id), state="i")
            retcode, stdout, stderr = common.run_os_command(
                "ceph osd out {}".format(osd_id)
            )
            if retcode:
                print("ceph osd out")
                print(stdout)
                print(stderr)
                raise Exception

            # 2. Wait for the OSD to flush
            logger.out("Flushing OSD disk with ID {}".format(osd_id), state="i")
            osd_string = str()
            while True:
                try:
                    retcode, stdout, stderr = common.run_os_command(
                        "ceph pg dump osds --format json"
                    )
                    dump_string = json.loads(stdout)
                    for osd in dump_string:
                        if str(osd["osd"]) == osd_id:
                            osd_string = osd
                    num_pgs = osd_string["num_pgs"]
                    if num_pgs > 0:
                        time.sleep(5)
                    else:
                        raise Exception
                except Exception:
                    break

            # 3. Stop the OSD process and wait for it to be terminated
            logger.out("Stopping OSD disk with ID {}".format(osd_id), state="i")
            retcode, stdout, stderr = common.run_os_command(
                "systemctl stop ceph-osd@{}".format(osd_id)
            )
            if retcode:
                print("systemctl stop")
                print(stdout)
                print(stderr)
                raise Exception

            # FIXME: There has to be a better way to do this /shrug
            while True:
                is_osd_up = False
                # Find if there is a process named ceph-osd with arg '--id {id}'
                for p in psutil.process_iter(attrs=["name", "cmdline"]):
                    if "ceph-osd" == p.info["name"] and "--id {}".format(
                        osd_id
                    ) in " ".join(p.info["cmdline"]):
                        is_osd_up = True
                # If there isn't, continue
                if not is_osd_up:
                    break

            # 4. Determine the block devices
            retcode, stdout, stderr = common.run_os_command(
                "readlink /var/lib/ceph/osd/ceph-{}/block".format(osd_id)
            )
            vg_name = stdout.split("/")[-2]  # e.g. /dev/ceph-<uuid>/osd-block-<uuid>
            retcode, stdout, stderr = common.run_os_command(
                "vgs --separator , --noheadings -o pv_name {}".format(vg_name)
            )
            pv_block = stdout.strip()

            # 5. Zap the volumes
            logger.out(
                "Zapping OSD disk with ID {} on {}".format(osd_id, pv_block), state="i"
            )
            retcode, stdout, stderr = common.run_os_command(
                "ceph-volume lvm zap --destroy {}".format(pv_block)
            )
            if retcode:
                print("ceph-volume lvm zap")
                print(stdout)
                print(stderr)
                raise Exception

            # 6. Purge the OSD from Ceph
            logger.out("Purging OSD disk with ID {}".format(osd_id), state="i")
            retcode, stdout, stderr = common.run_os_command(
                "ceph osd purge {} --yes-i-really-mean-it".format(osd_id)
            )
            if retcode:
                print("ceph osd purge")
                print(stdout)
                print(stderr)
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
            logger.out(
                "Deleting OSD disk with ID {} from Zookeeper".format(osd_id), state="i"
            )
            zkhandler.delete(("osd", osd_id), recursive=True)

            # Log it
            logger.out("Removed OSD disk with ID {}".format(osd_id), state="o")
            return True
        except Exception as e:
            # Log it
            logger.out(
                "Failed to purge OSD disk with ID {}: {}".format(osd_id, e), state="e"
            )
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
    def create_osd_db_lv(zkhandler, logger, osd_id, ext_db_ratio, osd_size_bytes):
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
            osd_db_size = int(osd_size_bytes * ext_db_ratio / 1024 / 1024)

            # 2. Create the LV
            logger.out(
                'Creating DB LV "osd-db/osd-{}" of {}M ({} * {})'.format(
                    osd_id, osd_db_size, osd_size_bytes, ext_db_ratio
                ),
                state="i",
            )
            retcode, stdout, stderr = common.run_os_command(
                "lvcreate --yes --name osd-{} --size {} osd-db".format(
                    osd_id, osd_db_size
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
    def __init__(self, zkhandler, this_node, name):
        self.zkhandler = zkhandler
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
    def __init__(self, zkhandler, this_node, pool, name):
        self.zkhandler = zkhandler
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
    # Get the command and args
    command, args = data.split()

    # Adding a new OSD
    if command == "osd_add":
        node, device, weight, ext_db_flag, ext_db_ratio = args.split(",")
        ext_db_flag = bool(strtobool(ext_db_flag))
        ext_db_ratio = float(ext_db_ratio)
        if node == this_node.name:
            # Lock the command queue
            zk_lock = zkhandler.writelock("base.cmd.ceph")
            with zk_lock:
                # Add the OSD
                result = CephOSDInstance.add_osd(
                    zkhandler, logger, node, device, weight, ext_db_flag, ext_db_ratio
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
        osd_id = args

        # Verify osd_id is in the list
        if d_osd[osd_id] and d_osd[osd_id].node == this_node.name:
            # Lock the command queue
            zk_lock = zkhandler.writelock("base.cmd.ceph")
            with zk_lock:
                # Remove the OSD
                result = CephOSDInstance.remove_osd(
                    zkhandler, logger, osd_id, d_osd[osd_id]
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
