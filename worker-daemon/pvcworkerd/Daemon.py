#!/usr/bin/env python3

# Daemon.py - PVC Node Worker daemon
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

from celery import Celery

import daemon_lib.config as cfg

from daemon_lib.zkhandler import ZKConnection
from daemon_lib.vm import (
    vm_worker_flush_locks,
    vm_worker_attach_device,
    vm_worker_detach_device,
)
from daemon_lib.ceph import (
    osd_worker_add_osd,
    osd_worker_replace_osd,
    osd_worker_refresh_osd,
    osd_worker_remove_osd,
    osd_worker_add_db_vg,
)
from daemon_lib.benchmark import (
    worker_run_benchmark,
)
from daemon_lib.vmbuilder import (
    worker_create_vm,
)

# Daemon version
version = "0.9.88"


config = cfg.get_configuration()
config["daemon_name"] = "pvcworkerd"
config["daemon_version"] = version


celery_task_uri = "redis://{}:{}{}".format(
    config["keydb_host"], config["keydb_port"], config["keydb_path"]
)
celery = Celery(
    "pvcworkerd",
    broker=celery_task_uri,
    backend=celery_task_uri,
    result_extended=True,
)


#
# Job functions
#
@celery.task(name="provisioner.create", bind=True, routing_key="run_on")
def create_vm(
    self,
    vm_name=None,
    profile_name=None,
    define_vm=True,
    start_vm=True,
    script_run_args=[],
    run_on="primary",
):
    return worker_create_vm(
        self,
        config,
        vm_name,
        profile_name,
        define_vm=define_vm,
        start_vm=start_vm,
        script_run_args=script_run_args,
    )


@celery.task(name="storage.benchmark", bind=True, routing_key="run_on")
def storage_benchmark(self, pool=None, run_on="primary"):
    @ZKConnection(config)
    def run_storage_benchmark(zkhandler, self, pool):
        return worker_run_benchmark(zkhandler, self, config, pool)

    return run_storage_benchmark(self, pool)


@celery.task(name="vm.flush_locks", bind=True, routing_key="run_on")
def vm_flush_locks(self, domain=None, force_unlock=False, run_on="primary"):
    @ZKConnection(config)
    def run_vm_flush_locks(zkhandler, self, domain, force_unlock=False):
        return vm_worker_flush_locks(zkhandler, self, domain, force_unlock=force_unlock)

    return run_vm_flush_locks(self, domain, force_unlock=force_unlock)


@celery.task(name="vm.device_attach", bind=True, routing_key="run_on")
def vm_device_attach(self, domain=None, xml=None, run_on=None):
    @ZKConnection(config)
    def run_vm_device_attach(zkhandler, self, domain, xml):
        return vm_worker_attach_device(zkhandler, self, domain, xml)

    return run_vm_device_attach(self, domain, xml)


@celery.task(name="vm.device_detach", bind=True, routing_key="run_on")
def vm_device_detach(self, domain=None, xml=None, run_on=None):
    @ZKConnection(config)
    def run_vm_device_detach(zkhandler, self, domain, xml):
        return vm_worker_detach_device(zkhandler, self, domain, xml)

    return run_vm_device_detach(self, domain, xml)


@celery.task(name="osd.add", bind=True, routing_key="run_on")
def osd_add(
    self,
    device=None,
    weight=None,
    ext_db_ratio=None,
    ext_db_size=None,
    split_count=None,
    run_on=None,
):
    @ZKConnection(config)
    def run_osd_add(
        zkhandler,
        self,
        run_on,
        device,
        weight,
        ext_db_ratio=None,
        ext_db_size=None,
        split_count=None,
    ):
        return osd_worker_add_osd(
            zkhandler,
            self,
            run_on,
            device,
            weight,
            ext_db_ratio,
            ext_db_size,
            split_count,
        )

    return run_osd_add(
        self, run_on, device, weight, ext_db_ratio, ext_db_size, split_count
    )


@celery.task(name="osd.replace", bind=True, routing_key="run_on")
def osd_replace(
    self,
    osd_id=None,
    new_device=None,
    old_device=None,
    weight=None,
    ext_db_ratio=None,
    ext_db_size=None,
    run_on=None,
):
    @ZKConnection(config)
    def run_osd_replace(
        zkhandler,
        self,
        run_on,
        osd_id,
        new_device,
        old_device=None,
        weight=None,
        ext_db_ratio=None,
        ext_db_size=None,
    ):
        return osd_worker_replace_osd(
            zkhandler,
            self,
            run_on,
            osd_id,
            new_device,
            old_device,
            weight,
            ext_db_ratio,
            ext_db_size,
        )

    return run_osd_replace(
        self, run_on, osd_id, new_device, old_device, weight, ext_db_ratio, ext_db_size
    )


@celery.task(name="osd.refresh", bind=True, routing_key="run_on")
def osd_refresh(self, osd_id=None, device=None, ext_db_flag=False, run_on=None):
    @ZKConnection(config)
    def run_osd_refresh(zkhandler, self, run_on, osd_id, device, ext_db_flag=False):
        return osd_worker_refresh_osd(
            zkhandler, self, run_on, osd_id, device, ext_db_flag
        )

    return run_osd_refresh(self, run_on, osd_id, device, ext_db_flag)


@celery.task(name="osd.remove", bind=True, routing_key="run_on")
def osd_remove(self, osd_id=None, force_flag=False, skip_zap_flag=False, run_on=None):
    @ZKConnection(config)
    def run_osd_remove(
        zkhandler, self, run_on, osd_id, force_flag=False, skip_zap_flag=False
    ):
        return osd_worker_remove_osd(
            zkhandler, self, run_on, osd_id, force_flag, skip_zap_flag
        )

    return run_osd_remove(self, run_on, osd_id, force_flag, skip_zap_flag)


@celery.task(name="osd.add_db_vg", bind=True, routing_key="run_on")
def osd_add_db_vg(self, device=None, run_on=None):
    @ZKConnection(config)
    def run_osd_add_db_vg(zkhandler, self, run_on, device):
        return osd_worker_add_db_vg(zkhandler, self, run_on, device)

    return run_osd_add_db_vg(self, run_on, device)


def entrypoint():
    pass
