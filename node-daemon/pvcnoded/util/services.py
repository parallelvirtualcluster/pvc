#!/usr/bin/env python3

# services.py - Utility functions for pvcnoded external services
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

import daemon_lib.common as common
from time import sleep


def start_zookeeper(logger, config):
    if config["daemon_mode"] == "coordinator":
        logger.out("Starting Zookeeper daemon", state="i")
        # TODO: Move our handling out of Systemd and integrate it directly as a subprocess?
        common.run_os_command("systemctl start zookeeper.service")


def start_libvirtd(logger, config):
    if config["enable_hypervisor"]:
        logger.out("Starting Libvirt daemon", state="i")
        # TODO: Move our handling out of Systemd and integrate it directly as a subprocess?
        common.run_os_command("systemctl start libvirtd.service")


def start_patroni(logger, config):
    if config["enable_networking"] and config["daemon_mode"] == "coordinator":
        logger.out("Starting Patroni daemon", state="i")
        # TODO: Move our handling out of Systemd and integrate it directly as a subprocess?
        common.run_os_command("systemctl start patroni.service")


def start_frrouting(logger, config):
    if config["enable_networking"] and config["daemon_mode"] == "coordinator":
        logger.out("Starting FRRouting daemon", state="i")
        # TODO: Move our handling out of Systemd and integrate it directly as a subprocess?
        common.run_os_command("systemctl start frr.service")


def start_ceph_mon(logger, config):
    if config["enable_storage"] and config["daemon_mode"] == "coordinator":
        logger.out("Starting Ceph Monitor daemon", state="i")
        # TODO: Move our handling out of Systemd and integrate it directly as a subprocess?
        common.run_os_command(
            f'systemctl start ceph-mon@{config["node_hostname"]}.service'
        )


def start_ceph_mgr(logger, config):
    if config["enable_storage"] and config["daemon_mode"] == "coordinator":
        logger.out("Starting Ceph Manager daemon", state="i")
        # TODO: Move our handling out of Systemd and integrate it directly as a subprocess?
        common.run_os_command(
            f'systemctl start ceph-mgr@{config["node_hostname"]}.service'
        )


def start_keydb(logger, config):
    if (config["enable_api"] or config["enable_worker"]) and config[
        "daemon_mode"
    ] == "coordinator":
        logger.out("Starting KeyDB daemon", state="i")
        # TODO: Move our handling out of Systemd and integrate it directly as a subprocess?
        common.run_os_command("systemctl start keydb-server.service")


def start_workerd(logger, config):
    if config["enable_worker"]:
        logger.out("Starting Celery Worker daemon", state="i")
        # TODO: Move our handling out of Systemd and integrate it directly as a subprocess?
        common.run_os_command("systemctl start pvcworkerd.service")


def start_healthd(logger, config):
    logger.out("Starting Health Monitoring daemon", state="i")
    # TODO: Move our handling out of Systemd and integrate it directly as a subprocess?
    common.run_os_command("systemctl start pvchealthd.service")


def start_system_services(logger, config):
    start_zookeeper(logger, config)
    start_libvirtd(logger, config)
    start_patroni(logger, config)
    start_frrouting(logger, config)
    start_ceph_mon(logger, config)
    start_ceph_mgr(logger, config)
    start_keydb(logger, config)
    start_workerd(logger, config)
    start_healthd(logger, config)

    logger.out("Waiting 10 seconds for daemons to start", state="s")
    sleep(10)
