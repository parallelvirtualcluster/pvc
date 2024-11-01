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
    vm_worker_create_snapshot,
    vm_worker_remove_snapshot,
    vm_worker_rollback_snapshot,
    vm_worker_export_snapshot,
    vm_worker_import_snapshot,
    vm_worker_send_snapshot,
    vm_worker_create_mirror,
    vm_worker_promote_mirror,
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
from daemon_lib.autobackup import (
    worker_cluster_autobackup,
)

# Daemon version
version = "0.9.103"


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
def storage_benchmark(self, pool=None, name=None, run_on="primary"):
    @ZKConnection(config)
    def run_storage_benchmark(zkhandler, self, pool, name):
        return worker_run_benchmark(zkhandler, self, config, pool, name)

    return run_storage_benchmark(self, pool, name)


@celery.task(name="cluster.autobackup", bind=True, routing_key="run_on")
def cluster_autobackup(self, force_full=False, email_recipients=None, run_on="primary"):
    @ZKConnection(config)
    def run_cluster_autobackup(
        zkhandler, self, force_full=False, email_recipients=None
    ):
        return worker_cluster_autobackup(
            zkhandler, self, force_full=force_full, email_recipients=email_recipients
        )

    return run_cluster_autobackup(
        self, force_full=force_full, email_recipients=email_recipients
    )


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


@celery.task(name="vm.create_snapshot", bind=True, routing_key="run_on")
def vm_create_snapshot(self, domain=None, snapshot_name=None, run_on="primary"):
    @ZKConnection(config)
    def run_vm_create_snapshot(zkhandler, self, domain, snapshot_name):
        return vm_worker_create_snapshot(zkhandler, self, domain, snapshot_name)

    return run_vm_create_snapshot(self, domain, snapshot_name)


@celery.task(name="vm.remove_snapshot", bind=True, routing_key="run_on")
def vm_remove_snapshot(self, domain=None, snapshot_name=None, run_on="primary"):
    @ZKConnection(config)
    def run_vm_remove_snapshot(zkhandler, self, domain, snapshot_name):
        return vm_worker_remove_snapshot(zkhandler, self, domain, snapshot_name)

    return run_vm_remove_snapshot(self, domain, snapshot_name)


@celery.task(name="vm.rollback_snapshot", bind=True, routing_key="run_on")
def vm_rollback_snapshot(self, domain=None, snapshot_name=None, run_on="primary"):
    @ZKConnection(config)
    def run_vm_rollback_snapshot(zkhandler, self, domain, snapshot_name):
        return vm_worker_rollback_snapshot(zkhandler, self, domain, snapshot_name)

    return run_vm_rollback_snapshot(self, domain, snapshot_name)


@celery.task(name="vm.export_snapshot", bind=True, routing_key="run_on")
def vm_export_snapshot(
    self,
    domain=None,
    snapshot_name=None,
    export_path=None,
    incremental_parent=None,
    run_on="primary",
):
    @ZKConnection(config)
    def run_vm_export_snapshot(
        zkhandler, self, domain, snapshot_name, export_path, incremental_parent=None
    ):
        return vm_worker_export_snapshot(
            zkhandler,
            self,
            domain,
            snapshot_name,
            export_path,
            incremental_parent=incremental_parent,
        )

    return run_vm_export_snapshot(
        self, domain, snapshot_name, export_path, incremental_parent=incremental_parent
    )


@celery.task(name="vm.import_snapshot", bind=True, routing_key="run_on")
def vm_import_snapshot(
    self,
    domain=None,
    snapshot_name=None,
    import_path=None,
    retain_snapshot=True,
    run_on="primary",
):
    @ZKConnection(config)
    def run_vm_import_snapshot(
        zkhandler, self, domain, snapshot_name, import_path, retain_snapshot=True
    ):
        return vm_worker_import_snapshot(
            zkhandler,
            self,
            domain,
            snapshot_name,
            import_path,
            retain_snapshot=retain_snapshot,
        )

    return run_vm_import_snapshot(
        self, domain, snapshot_name, import_path, retain_snapshot=retain_snapshot
    )


@celery.task(name="vm.send_snapshot", bind=True, routing_key="run_on")
def vm_send_snapshot(
    self,
    domain=None,
    snapshot_name=None,
    destination_api_uri="",
    destination_api_key="",
    destination_api_verify_ssl=True,
    incremental_parent=None,
    destination_storage_pool=None,
    run_on="primary",
):
    @ZKConnection(config)
    def run_vm_send_snapshot(
        zkhandler,
        self,
        domain,
        snapshot_name,
        destination_api_uri,
        destination_api_key,
        destination_api_verify_ssl=True,
        incremental_parent=None,
        destination_storage_pool=None,
    ):
        return vm_worker_send_snapshot(
            zkhandler,
            self,
            domain,
            snapshot_name,
            destination_api_uri,
            destination_api_key,
            destination_api_verify_ssl=destination_api_verify_ssl,
            incremental_parent=incremental_parent,
            destination_storage_pool=destination_storage_pool,
        )

    return run_vm_send_snapshot(
        self,
        domain,
        snapshot_name,
        destination_api_uri,
        destination_api_key,
        destination_api_verify_ssl=destination_api_verify_ssl,
        incremental_parent=incremental_parent,
        destination_storage_pool=destination_storage_pool,
    )


@celery.task(name="vm.create_mirror", bind=True, routing_key="run_on")
def vm_create_mirror(
    self,
    domain=None,
    destination_api_uri="",
    destination_api_key="",
    destination_api_verify_ssl=True,
    destination_storage_pool=None,
    run_on="primary",
):
    @ZKConnection(config)
    def run_vm_create_mirror(
        zkhandler,
        self,
        domain,
        destination_api_uri,
        destination_api_key,
        destination_api_verify_ssl=True,
        destination_storage_pool=None,
    ):
        return vm_worker_create_mirror(
            zkhandler,
            self,
            domain,
            destination_api_uri,
            destination_api_key,
            destination_api_verify_ssl=destination_api_verify_ssl,
            destination_storage_pool=destination_storage_pool,
        )

    return run_vm_create_mirror(
        self,
        domain,
        destination_api_uri,
        destination_api_key,
        destination_api_verify_ssl=destination_api_verify_ssl,
        destination_storage_pool=destination_storage_pool,
    )


@celery.task(name="vm.promote_mirror", bind=True, routing_key="run_on")
def vm_promote_mirror(
    self,
    domain=None,
    destination_api_uri="",
    destination_api_key="",
    destination_api_verify_ssl=True,
    destination_storage_pool=None,
    remove_on_source=False,
    run_on="primary",
):
    @ZKConnection(config)
    def run_vm_promote_mirror(
        zkhandler,
        self,
        domain,
        destination_api_uri,
        destination_api_key,
        destination_api_verify_ssl=True,
        destination_storage_pool=None,
        remove_on_source=False,
    ):
        return vm_worker_promote_mirror(
            zkhandler,
            self,
            domain,
            destination_api_uri,
            destination_api_key,
            destination_api_verify_ssl=destination_api_verify_ssl,
            destination_storage_pool=destination_storage_pool,
            remove_on_source=remove_on_source,
        )

    return run_vm_promote_mirror(
        self,
        domain,
        destination_api_uri,
        destination_api_key,
        destination_api_verify_ssl=destination_api_verify_ssl,
        destination_storage_pool=destination_storage_pool,
        remove_on_source=remove_on_source,
    )


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
