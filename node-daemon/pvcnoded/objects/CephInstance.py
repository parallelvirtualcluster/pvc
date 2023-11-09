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

import json

import daemon_lib.common as common


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
