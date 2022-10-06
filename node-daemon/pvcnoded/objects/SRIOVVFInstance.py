#!/usr/bin/env python3

# SRIOVVFInstance.py - Class implementing a PVC SR-IOV VF and run by pvcnoded
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

import daemon_lib.common as common


def boolToOnOff(state):
    if state and str(state) == "True":
        return "on"
    else:
        return "off"


class SRIOVVFInstance(object):
    # Initialization function
    def __init__(self, vf, zkhandler, config, logger, this_node):
        self.vf = vf
        self.zkhandler = zkhandler
        self.config = config
        self.logger = logger
        self.this_node = this_node
        self.myhostname = self.this_node.name

        self.pf = self.zkhandler.read(
            ("node.sriov.vf", self.myhostname, "sriov_vf.pf", self.vf)
        )
        self.mtu = self.zkhandler.read(
            ("node.sriov.vf", self.myhostname, "sriov_vf.mtu", self.vf)
        )
        self.vfid = self.vf.replace("{}v".format(self.pf), "")

        self.logger.out(
            "Setting MTU to {}".format(self.mtu),
            state="i",
            prefix="SR-IOV VF {}".format(self.vf),
        )
        common.run_os_command("ip link set {} mtu {}".format(self.vf, self.mtu))

        # These properties are set via the DataWatch functions, to ensure they are configured on the system
        self.mac = None
        self.vlan_id = None
        self.vlan_qos = None
        self.tx_rate_min = None
        self.tx_rate_max = None
        self.spoof_check = None
        self.link_state = None
        self.trust = None
        self.query_rss = None

        # Zookeeper handlers for changed configs
        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.sriov.vf", self.myhostname)
            + self.zkhandler.schema.path("sriov_vf.mac", self.vf)
        )
        def watch_vf_mac(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = "00:00:00:00:00:00"

            if data != self.mac:
                self.mac = data

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.sriov.vf", self.myhostname)
            + self.zkhandler.schema.path("sriov_vf.config.vlan_id", self.vf)
        )
        def watch_vf_vlan_id(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = "0"

            if data != self.vlan_id:
                self.vlan_id = data
                self.logger.out(
                    "Setting vLAN ID to {}".format(self.vlan_id),
                    state="i",
                    prefix="SR-IOV VF {}".format(self.vf),
                )
                common.run_os_command(
                    "ip link set {} vf {} vlan {} qos {}".format(
                        self.pf, self.vfid, self.vlan_id, self.vlan_qos
                    )
                )

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.sriov.vf", self.myhostname)
            + self.zkhandler.schema.path("sriov_vf.config.vlan_qos", self.vf)
        )
        def watch_vf_vlan_qos(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = "0"

            if data != self.vlan_qos:
                self.vlan_qos = data
                self.logger.out(
                    "Setting vLAN QOS to {}".format(self.vlan_qos),
                    state="i",
                    prefix="SR-IOV VF {}".format(self.vf),
                )
                common.run_os_command(
                    "ip link set {} vf {} vlan {} qos {}".format(
                        self.pf, self.vfid, self.vlan_id, self.vlan_qos
                    )
                )

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.sriov.vf", self.myhostname)
            + self.zkhandler.schema.path("sriov_vf.config.tx_rate_min", self.vf)
        )
        def watch_vf_tx_rate_min(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = "0"

            if data != self.tx_rate_min:
                self.tx_rate_min = data
                self.logger.out(
                    "Setting minimum TX rate to {}".format(self.tx_rate_min),
                    state="i",
                    prefix="SR-IOV VF {}".format(self.vf),
                )
                common.run_os_command(
                    "ip link set {} vf {} min_tx_rate {}".format(
                        self.pf, self.vfid, self.tx_rate_min
                    )
                )

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.sriov.vf", self.myhostname)
            + self.zkhandler.schema.path("sriov_vf.config.tx_rate_max", self.vf)
        )
        def watch_vf_tx_rate_max(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; termaxate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = "0"

            if data != self.tx_rate_max:
                self.tx_rate_max = data
                self.logger.out(
                    "Setting maximum TX rate to {}".format(self.tx_rate_max),
                    state="i",
                    prefix="SR-IOV VF {}".format(self.vf),
                )
                common.run_os_command(
                    "ip link set {} vf {} max_tx_rate {}".format(
                        self.pf, self.vfid, self.tx_rate_max
                    )
                )

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.sriov.vf", self.myhostname)
            + self.zkhandler.schema.path("sriov_vf.config.spoof_check", self.vf)
        )
        def watch_vf_spoof_check(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = "0"

            if data != self.spoof_check:
                self.spoof_check = data
                self.logger.out(
                    "Setting spoof checking {}".format(boolToOnOff(self.spoof_check)),
                    state="i",
                    prefix="SR-IOV VF {}".format(self.vf),
                )
                common.run_os_command(
                    "ip link set {} vf {} spoofchk {}".format(
                        self.pf, self.vfid, boolToOnOff(self.spoof_check)
                    )
                )

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.sriov.vf", self.myhostname)
            + self.zkhandler.schema.path("sriov_vf.config.link_state", self.vf)
        )
        def watch_vf_link_state(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = "on"

            if data != self.link_state:
                self.link_state = data
                self.logger.out(
                    "Setting link state to {}".format(boolToOnOff(self.link_state)),
                    state="i",
                    prefix="SR-IOV VF {}".format(self.vf),
                )
                common.run_os_command(
                    "ip link set {} vf {} state {}".format(
                        self.pf, self.vfid, self.link_state
                    )
                )

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.sriov.vf", self.myhostname)
            + self.zkhandler.schema.path("sriov_vf.config.trust", self.vf)
        )
        def watch_vf_trust(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = "off"

            if data != self.trust:
                self.trust = data
                self.logger.out(
                    "Setting trust mode {}".format(boolToOnOff(self.trust)),
                    state="i",
                    prefix="SR-IOV VF {}".format(self.vf),
                )
                common.run_os_command(
                    "ip link set {} vf {} trust {}".format(
                        self.pf, self.vfid, boolToOnOff(self.trust)
                    )
                )

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.sriov.vf", self.myhostname)
            + self.zkhandler.schema.path("sriov_vf.config.query_rss", self.vf)
        )
        def watch_vf_query_rss(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = "off"

            if data != self.query_rss:
                self.query_rss = data
                self.logger.out(
                    "Setting RSS query ability {}".format(boolToOnOff(self.query_rss)),
                    state="i",
                    prefix="SR-IOV VF {}".format(self.vf),
                )
                common.run_os_command(
                    "ip link set {} vf {} query_rss {}".format(
                        self.pf, self.vfid, boolToOnOff(self.query_rss)
                    )
                )
