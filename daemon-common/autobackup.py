#!/usr/bin/env python3

# autobackup.py - PVC API Autobackup functions
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

from datetime import datetime
from json import load as jload
from json import dump as jdump
from os import popen, makedirs, path, scandir
from shutil import rmtree
from subprocess import run, PIPE
from time import time

from daemon_lib.common import run_os_command
from daemon_lib.config import get_autobackup_configuration
from daemon_lib.celery import start, fail, log_info, log_err, update, finish

import daemon_lib.ceph as ceph
import daemon_lib.vm as vm


def send_execution_failure_report(
    celery_conf, config, recipients=None, total_time=0, error=None
):
    if recipients is None:
        return

    from email.utils import formatdate
    from socket import gethostname

    log_message = f"Sending email failure report to {', '.join(recipients)}"
    log_info(celery_conf[0], log_message)
    update(
        celery_conf[0],
        log_message,
        current=celery_conf[1] + 1,
        total=celery_conf[2],
    )

    current_datetime = datetime.now()
    email_datetime = formatdate(float(current_datetime.strftime("%s")))

    email = list()
    email.append(f"Date: {email_datetime}")
    email.append(
        f"Subject: PVC Autobackup execution failure for cluster '{config['cluster']}'"
    )

    email_to = list()
    for recipient in recipients:
        email_to.append(f"<{recipient}>")

    email.append(f"To: {', '.join(email_to)}")
    email.append(f"From: PVC Autobackup System <pvc@{gethostname()}>")
    email.append("")

    email.append(
        f"A PVC autobackup has FAILED at {current_datetime} in {total_time}s due to an execution error."
    )
    email.append("")
    email.append("The reported error message is:")
    email.append(f"  {error}")

    try:
        with popen("/usr/sbin/sendmail -t", "w") as p:
            p.write("\n".join(email))
    except Exception as e:
        log_err(f"Failed to send report email: {e}")


def send_execution_summary_report(
    celery_conf, config, recipients=None, total_time=0, summary=dict()
):
    if recipients is None:
        return

    from email.utils import formatdate
    from socket import gethostname

    log_message = f"Sending email summary report to {', '.join(recipients)}"
    log_info(celery_conf[0], log_message)
    update(
        celery_conf[0],
        log_message,
        current=celery_conf[1] + 1,
        total=celery_conf[2],
    )

    current_datetime = datetime.now()
    email_datetime = formatdate(float(current_datetime.strftime("%s")))

    email = list()
    email.append(f"Date: {email_datetime}")
    email.append(f"Subject: PVC Autobackup report for cluster '{config['cluster']}'")

    email_to = list()
    for recipient in recipients:
        email_to.append(f"<{recipient}>")

    email.append(f"To: {', '.join(email_to)}")
    email.append(f"From: PVC Autobackup System <pvc@{gethostname()}>")
    email.append("")

    email.append(
        f"A PVC autobackup has been completed at {current_datetime} in {total_time}s."
    )
    email.append("")
    email.append(
        "The following is a summary of all current VM backups after cleanups, most recent first:"
    )
    email.append("")

    for vm_name in summary.keys():
        email.append(f"VM: {vm_name}:")
        for backup in summary[vm_name]:
            datestring = backup.get("datestring")
            backup_date = datetime.strptime(datestring, "%Y%m%d%H%M%S")
            if backup.get("result", False):
                email.append(
                    f"    {backup_date}: Success in {backup.get('runtime_secs', 0)} seconds, ID {datestring}, type {backup.get('type', 'unknown')}"
                )
                email.append(
                    f"                         Backup contains {len(backup.get('backup_files'))} files totaling {ceph.format_bytes_tohuman(backup.get('backup_size_bytes', 0))} ({backup.get('backup_size_bytes', 0)} bytes)"
                )
            else:
                email.append(
                    f"    {backup_date}: Failure in {backup.get('runtime_secs', 0)} seconds, ID {datestring}, type {backup.get('type', 'unknown')}"
                )
                email.append(f"                         {backup.get('result_message')}")

    try:
        with popen("/usr/sbin/sendmail -t", "w") as p:
            p.write("\n".join(email))
    except Exception as e:
        log_err(f"Failed to send report email: {e}")


def worker_cluster_autobackup(
    zkhandler, celery, force_full=False, email_recipients=None
):
    config = get_autobackup_configuration()

    backup_summary = dict()

    current_stage = 0
    total_stages = 1
    if email_recipients is not None:
        total_stages += 1

    start(
        celery,
        f"Starting cluster '{config['cluster']}' VM autobackup",
        current=current_stage,
        total=total_stages,
    )

    if not config["autobackup_enabled"]:
        message = "Autobackups are not configured on this cluster."
        log_info(celery, message)
        return finish(
            celery,
            message,
            current=total_stages,
            total=total_stages,
        )

    autobackup_start_time = datetime.now()

    retcode, vm_list = vm.get_list(zkhandler)
    if not retcode:
        error_message = f"Failed to fetch VM list: {vm_list}"
        log_err(celery, error_message)
        send_execution_failure_report(
            (celery, current_stage, total_stages),
            config,
            recipients=email_recipients,
            error=error_message,
        )
        fail(celery, error_message)
        return False

    backup_suffixed_path = (
        f"{config['backup_root_path']}/{config['backup_root_suffix']}"
    )
    if not path.exists(backup_suffixed_path):
        makedirs(backup_suffixed_path)

    full_interval = config["backup_schedule"]["full_interval"]
    full_retention = config["backup_schedule"]["full_retention"]

    backup_vms = list()
    for vm_detail in vm_list:
        vm_tag_names = [t["name"] for t in vm_detail["tags"]]
        matching_tags = (
            True
            if len(set(vm_tag_names).intersection(set(config["backup_tags"]))) > 0
            else False
        )
        if matching_tags:
            backup_vms.append(vm_detail)

    if len(backup_vms) < 1:
        message = "Found no VMs tagged for autobackup."
        log_info(celery, message)
        return finish(
            celery,
            message,
            current=total_stages,
            total=total_stages,
        )

    if config["auto_mount_enabled"]:
        total_stages += len(config["mount_cmds"])
        total_stages += len(config["unmount_cmds"])

    for vm_detail in backup_vms:
        total_disks = len([d for d in vm_detail["disks"] if d["type"] == "rbd"])
        total_stages += 2 + (2 * total_disks)

        vm_name = vm_detail["name"]
        vm_backup_path = f"{backup_suffixed_path}/{vm_name}"
        autobackup_state_file = f"{vm_backup_path}/.autobackup.json"
        if not path.exists(vm_backup_path) or not path.exists(autobackup_state_file):
            # There are no existing backups so the list is empty
            state_data = dict()
            tracked_backups = list()
        else:
            with open(autobackup_state_file) as fh:
                state_data = jload(fh)
            tracked_backups = state_data["tracked_backups"]

        full_backups = [b for b in tracked_backups if b["type"] == "full"]
        if len(full_backups) > 0:
            last_full_backup = full_backups[0]
            last_full_backup_idx = tracked_backups.index(last_full_backup)
            if force_full or last_full_backup_idx >= full_interval - 1:
                this_backup_retain_snapshot = True
            else:
                this_backup_retain_snapshot = False
        else:
            # The very first ackup must be full to start the tree
            this_backup_retain_snapshot = True
        if this_backup_retain_snapshot:
            total_stages += total_disks

    log_info(
        celery,
        f"Found {len(backup_vms)} suitable VM(s) for autobackup: {', '.join([b['name'] for b in backup_vms])}",
    )

    # Handle automount mount commands
    if config["auto_mount_enabled"]:
        for cmd in config["mount_cmds"]:
            current_stage += 1
            update(
                celery,
                f"Executing mount command '{cmd.split()[0]}'",
                current=current_stage,
                total=total_stages,
            )

            ret = run(
                cmd.split(),
                stdout=PIPE,
                stderr=PIPE,
            )

            if ret.returncode != 0:
                error_message = f"Failed to execute mount command '{cmd.split()[0]}': {ret.stderr.decode().strip()}"
                log_err(celery, error_message)
                send_execution_failure_report(
                    (celery, current_stage, total_stages),
                    config,
                    recipients=email_recipients,
                    total_time=datetime.now() - autobackup_start_time,
                    error=error_message,
                )
                fail(celery, error_message)
                return False

    # Execute the backup: take a snapshot, then export the snapshot
    for vm_detail in backup_vms:
        vm_name = vm_detail["name"]
        dom_uuid = vm_detail["uuid"]
        vm_backup_path = f"{backup_suffixed_path}/{vm_name}"
        autobackup_state_file = f"{vm_backup_path}/.autobackup.json"
        if not path.exists(vm_backup_path) or not path.exists(autobackup_state_file):
            # There are no existing backups so the list is empty
            state_data = dict()
            tracked_backups = list()
        else:
            with open(autobackup_state_file) as fh:
                state_data = jload(fh)
            tracked_backups = state_data["tracked_backups"]

        full_backups = [b for b in tracked_backups if b["type"] == "full"]
        if len(full_backups) > 0:
            last_full_backup = full_backups[0]
            last_full_backup_idx = tracked_backups.index(last_full_backup)
            if force_full:
                this_backup_incremental_parent = None
                this_backup_retain_snapshot = True
            elif last_full_backup_idx >= full_interval - 1:
                this_backup_incremental_parent = None
                this_backup_retain_snapshot = True
            else:
                this_backup_incremental_parent = last_full_backup["datestring"]
                this_backup_retain_snapshot = False
        else:
            # The very first ackup must be full to start the tree
            this_backup_incremental_parent = None
            this_backup_retain_snapshot = True

        now = datetime.now()
        datestring = now.strftime("%Y%m%d%H%M%S")
        snapshot_name = f"ab{datestring}"

        # Take the VM snapshot (vm.vm_worker_create_snapshot)
        snap_list = list()

        def cleanup_failure():
            for snapshot in snap_list:
                rbd, snapshot_name = snapshot.split("@")
                pool, volume = rbd.split("/")
                # We capture no output here, because if this fails too we're in a deep
                # error chain and will just ignore it
                ceph.remove_snapshot(zkhandler, pool, volume, snapshot_name)

        rbd_list = zkhandler.read(("domain.storage.volumes", dom_uuid)).split(",")

        for rbd in rbd_list:
            current_stage += 1
            update(
                celery,
                f"[{vm_name}] Creating RBD snapshot of {rbd}",
                current=current_stage,
                total=total_stages,
            )

            pool, volume = rbd.split("/")
            ret, msg = ceph.add_snapshot(
                zkhandler, pool, volume, snapshot_name, zk_only=False
            )
            if not ret:
                cleanup_failure()
                error_message = msg.replace("ERROR: ", "")
                log_err(celery, error_message)
                send_execution_failure_report(
                    (celery, current_stage, total_stages),
                    config,
                    recipients=email_recipients,
                    error=error_message,
                )
                fail(celery, error_message)
                return False
            else:
                snap_list.append(f"{pool}/{volume}@{snapshot_name}")

        current_stage += 1
        update(
            celery,
            f"[{vm_name}] Creating VM configuration snapshot",
            current=current_stage,
            total=total_stages,
        )

        # Get the current timestamp
        tstart = time()

        # Get the current domain XML
        vm_config = zkhandler.read(("domain.xml", dom_uuid))

        # Add the snapshot entry to Zookeeper
        zkhandler.write(
            [
                (
                    (
                        "domain.snapshots",
                        dom_uuid,
                        "domain_snapshot.name",
                        snapshot_name,
                    ),
                    snapshot_name,
                ),
                (
                    (
                        "domain.snapshots",
                        dom_uuid,
                        "domain_snapshot.timestamp",
                        snapshot_name,
                    ),
                    tstart,
                ),
                (
                    (
                        "domain.snapshots",
                        dom_uuid,
                        "domain_snapshot.xml",
                        snapshot_name,
                    ),
                    vm_config,
                ),
                (
                    (
                        "domain.snapshots",
                        dom_uuid,
                        "domain_snapshot.rbd_snapshots",
                        snapshot_name,
                    ),
                    ",".join(snap_list),
                ),
            ]
        )

        # Export the snapshot (vm.vm_worker_export_snapshot)
        export_target_path = f"{backup_suffixed_path}/{vm_name}/{snapshot_name}/images"

        try:
            makedirs(export_target_path)
        except Exception as e:
            error_message = (
                f"[{vm_name}] Failed to create target directory '{export_target_path}': {e}",
            )
            log_err(celery, error_message)
            send_execution_failure_report(
                (celery, current_stage, total_stages),
                config,
                recipients=email_recipients,
                error=error_message,
            )
            fail(celery, error_message)
            return False

        def export_cleanup():
            from shutil import rmtree

            rmtree(f"{backup_suffixed_path}/{vm_name}/{snapshot_name}")

        export_type = (
            "incremental" if this_backup_incremental_parent is not None else "full"
        )

        # Set the export filetype
        if this_backup_incremental_parent is not None:
            export_fileext = "rbddiff"
        else:
            export_fileext = "rbdimg"

        snapshot_volumes = list()
        for rbdsnap in snap_list:
            pool, _volume = rbdsnap.split("/")
            volume, name = _volume.split("@")
            ret, snapshots = ceph.get_list_snapshot(
                zkhandler, pool, volume, limit=name, is_fuzzy=False
            )
            if ret:
                snapshot_volumes += snapshots

        export_files = list()
        for snapshot_volume in snapshot_volumes:
            snap_pool = snapshot_volume["pool"]
            snap_volume = snapshot_volume["volume"]
            snap_snapshot_name = snapshot_volume["snapshot"]
            snap_size = snapshot_volume["stats"]["size"]
            snap_str = f"{snap_pool}/{snap_volume}@{snap_snapshot_name}"

            current_stage += 1
            update(
                celery,
                f"[{vm_name}] Exporting RBD snapshot {snap_str}",
                current=current_stage,
                total=total_stages,
            )

            if this_backup_incremental_parent is not None:
                retcode, stdout, stderr = run_os_command(
                    f"rbd export-diff --from-snap {this_backup_incremental_parent} {snap_pool}/{snap_volume}@{snap_snapshot_name} {export_target_path}/{snap_pool}.{snap_volume}.{export_fileext}"
                )
                if retcode:
                    error_message = (
                        f"[{vm_name}] Failed to export snapshot for volume(s) '{snap_pool}/{snap_volume}'",
                    )
                    log_err(celery, error_message)
                    send_execution_failure_report(
                        (celery, current_stage, total_stages),
                        config,
                        recipients=email_recipients,
                        error=error_message,
                    )
                    fail(celery, error_message)
                    return False
                else:
                    export_files.append(
                        (
                            f"images/{snap_pool}.{snap_volume}.{export_fileext}",
                            snap_size,
                        )
                    )
            else:
                retcode, stdout, stderr = run_os_command(
                    f"rbd export --export-format 2 {snap_pool}/{snap_volume}@{snap_snapshot_name} {export_target_path}/{snap_pool}.{snap_volume}.{export_fileext}"
                )
                if retcode:
                    error_message = (
                        f"[{vm_name}] Failed to export snapshot for volume(s) '{snap_pool}/{snap_volume}'",
                    )
                    log_err(celery, error_message)
                    send_execution_failure_report(
                        (celery, current_stage, total_stages),
                        config,
                        recipients=email_recipients,
                        error=error_message,
                    )
                    fail(celery, error_message)
                    return False
                else:
                    export_files.append(
                        (
                            f"images/{snap_pool}.{snap_volume}.{export_fileext}",
                            snap_size,
                        )
                    )

        current_stage += 1
        update(
            celery,
            f"[{vm_name}] Writing snapshot details",
            current=current_stage,
            total=total_stages,
        )

        def get_dir_size(pathname):
            total = 0
            with scandir(pathname) as it:
                for entry in it:
                    if entry.is_file():
                        total += entry.stat().st_size
                    elif entry.is_dir():
                        total += get_dir_size(entry.path)
            return total

        export_files_size = get_dir_size(export_target_path)

        export_details = {
            "type": export_type,
            "datestring": datestring,
            "snapshot_name": snapshot_name,
            "incremental_parent": this_backup_incremental_parent,
            "vm_detail": vm_detail,
            "export_files": export_files,
            "export_size_bytes": export_files_size,
        }
        try:
            with open(
                f"{backup_suffixed_path}/{vm_name}/{snapshot_name}/snapshot.json", "w"
            ) as fh:
                jdump(export_details, fh)
        except Exception as e:
            error_message = (
                f"[{vm_name}] Failed to export configuration snapshot: {e}",
            )
            log_err(celery, error_message)
            send_execution_failure_report(
                (celery, current_stage, total_stages),
                config,
                recipients=email_recipients,
                error=error_message,
            )
            fail(celery, error_message)
            return False

        # Clean up the snapshot (vm.vm_worker_remove_snapshot)
        if not this_backup_retain_snapshot:
            for snap in snap_list:
                current_stage += 1
                update(
                    celery,
                    f"[{vm_name}] Removing RBD snapshot {snap}",
                    current=current_stage,
                    total=total_stages,
                )

                rbd, name = snap.split("@")
                pool, volume = rbd.split("/")
                ret, msg = ceph.remove_snapshot(zkhandler, pool, volume, name)
                if not ret:
                    error_message = msg.replace("ERROR: ", "")
                    log_err(celery, error_message)
                    send_execution_failure_report(
                        (celery, current_stage, total_stages),
                        config,
                        recipients=email_recipients,
                        error=error_message,
                    )
                    fail(celery, error_message)
                    return False

            current_stage += 1
            update(
                celery,
                f"[{vm_name}] Removing VM configuration snapshot",
                current=current_stage,
                total=total_stages,
            )

            ret = zkhandler.delete(
                ("domain.snapshots", dom_uuid, "domain_snapshot.name", snapshot_name)
            )
            if not ret:
                error_message = (
                    f"[{vm_name}] Failed to remove snapshot from Zookeeper",
                )
                log_err(celery, error_message)
                send_execution_failure_report(
                    (celery, current_stage, total_stages),
                    config,
                    recipients=email_recipients,
                    error=error_message,
                )
                fail(celery, error_message)
                return False

        current_stage += 1
        update(
            celery,
            f"Finding obsolete incremental backups for '{vm_name}'",
            current=current_stage,
            total=total_stages,
        )

        # Read export file to get details
        backup_json_file = f"{vm_backup_path}/{snapshot_name}/snapshot.json"
        with open(backup_json_file) as fh:
            backup_json = jload(fh)
        tracked_backups.insert(0, backup_json)

        marked_for_deletion = list()
        # Find any full backups that are expired
        found_full_count = 0
        for backup in tracked_backups:
            if backup["type"] == "full":
                found_full_count += 1
                if found_full_count > full_retention:
                    marked_for_deletion.append(backup)
        # Find any incremental backups that depend on marked parents
        for backup in tracked_backups:
            if backup["type"] == "incremental" and backup["incremental_parent"] in [
                b["datestring"] for b in marked_for_deletion
            ]:
                marked_for_deletion.append(backup)

        current_stage += 1
        if len(marked_for_deletion) > 0:
            update(
                celery,
                f"Cleaning up aged out backups for '{vm_name}'",
                current=current_stage,
                total=total_stages,
            )

            for backup_to_delete in marked_for_deletion:
                ret = vm.vm_worker_remove_snapshot(
                    zkhandler, None, vm_name, backup_to_delete["snapshot_name"]
                )
                if ret is False:
                    error_message = f"Failed to remove obsolete backup snapshot '{backup_to_delete['snapshot_name']}', leaving in tracked backups"
                    log_err(celery, error_message)
                else:
                    rmtree(f"{vm_backup_path}/{backup_to_delete['snapshot_name']}")
                    tracked_backups.remove(backup_to_delete)

        current_stage += 1
        update(
            celery,
            "Updating tracked backups",
            current=current_stage,
            total=total_stages,
        )
        state_data["tracked_backups"] = tracked_backups
        with open(autobackup_state_file, "w") as fh:
            jdump(state_data, fh)

        backup_summary[vm_detail["name"]] = tracked_backups

    # Handle automount unmount commands
    if config["auto_mount_enabled"]:
        for cmd in config["unmount_cmds"]:
            current_stage += 1
            update(
                celery,
                f"Executing unmount command '{cmd.split()[0]}'",
                current=current_stage,
                total=total_stages,
            )

            ret = run(
                cmd.split(),
                stdout=PIPE,
                stderr=PIPE,
            )

            if ret.returncode != 0:
                error_message = f"Failed to execute unmount command '{cmd.split()[0]}': {ret.stderr.decode().strip()}"
                log_err(celery, error_message)
                send_execution_failure_report(
                    (celery, current_stage, total_stages),
                    config,
                    recipients=email_recipients,
                    total_time=datetime.now() - autobackup_start_time,
                    error=error_message,
                )
                fail(celery, error_message)
                return False

    autobackup_end_time = datetime.now()
    autobackup_total_time = autobackup_end_time - autobackup_start_time

    if email_recipients is not None:
        send_execution_summary_report(
            (celery, current_stage, total_stages),
            config,
            recipients=email_recipients,
            total_time=autobackup_total_time,
            summary=backup_summary,
        )
        current_stage += 1

    current_stage += 1
    return finish(
        celery,
        f"Successfully completed cluster '{config['cluster']}' VM autobackup",
        current=current_stage,
        total=total_stages,
    )
