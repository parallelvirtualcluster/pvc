#!/usr/bin/env python3

# NodeInstance.py - Class implementing a PVC node in pvchealthd
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


class NodeInstance(object):
    # Initialization function
    def __init__(
        self,
        name,
        zkhandler,
        config,
        logger,
    ):
        # Passed-in variables on creation
        self.name = name
        self.zkhandler = zkhandler
        self.config = config
        self.logger = logger
        # States
        self.daemon_state = "stop"
        self.coordinator_state = "client"
        self.domain_state = "flushed"
        # Node resources
        self.health = 100
        self.active_domains_count = 0
        self.provisioned_domains_count = 0
        self.memused = 0
        self.memfree = 0
        self.memalloc = 0
        self.vcpualloc = 0

        # Zookeeper handlers for changed states
        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.state.daemon", self.name)
        )
        def watch_node_daemonstate(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = "stop"

            if data != self.daemon_state:
                self.daemon_state = data

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.state.router", self.name)
        )
        def watch_node_routerstate(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = "client"

            if data != self.coordinator_state:
                self.coordinator_state = data

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.state.domain", self.name)
        )
        def watch_node_domainstate(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = "unknown"

            if data != self.domain_state:
                self.domain_state = data

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.monitoring.health", self.name)
        )
        def watch_node_health(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = 100

            try:
                data = int(data)
            except ValueError:
                pass

            if data != self.health:
                self.health = data

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.memory.free", self.name)
        )
        def watch_node_memfree(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = 0

            if data != self.memfree:
                self.memfree = data

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.memory.used", self.name)
        )
        def watch_node_memused(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = 0

            if data != self.memused:
                self.memused = data

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.memory.allocated", self.name)
        )
        def watch_node_memalloc(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = 0

            if data != self.memalloc:
                self.memalloc = data

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.vcpu.allocated", self.name)
        )
        def watch_node_vcpualloc(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = 0

            if data != self.vcpualloc:
                self.vcpualloc = data

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.running_domains", self.name)
        )
        def watch_node_runningdomains(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii").split()
            except AttributeError:
                data = []

            if len(data) != self.active_domains_count:
                self.active_domains_count = len(data)

        @self.zkhandler.zk_conn.DataWatch(
            self.zkhandler.schema.path("node.count.provisioned_domains", self.name)
        )
        def watch_node_domainscount(data, stat, event=""):
            if event and event.type == "DELETED":
                # The key has been deleted after existing before; terminate this watcher
                # because this class instance is about to be reaped in Daemon.py
                return False

            try:
                data = data.decode("ascii")
            except AttributeError:
                data = 0

            if data != self.provisioned_domains_count:
                self.provisioned_domains_count = data
