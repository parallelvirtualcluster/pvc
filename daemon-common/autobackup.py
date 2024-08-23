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
from os import popen, makedirs, path
from shutil import rmtree
from subprocess import run, PIPE

from daemon_lib.config import get_autobackup_configuration
from daemon_lib.celery import start, fail, log_info, log_err, update, finish

import daemon_lib.ceph as pvc_ceph
import daemon_lib.vm as pvc_vm


def send_execution_failure_report(
    celery_conf, config, recipients=None, total_time=0, error=None
):
    if recipients is None:
        return

    from email.utils import formatdate
    from socket import gethostname

    log_message = f"Sending email failure report to {', '.join(recipients)}"
    log_info(log_message)
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
    log_info(log_message)
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

    for vm in summary.keys():
        email.append(f"VM: {vm}:")
        for backup in summary[vm]:
            datestring = backup.get("datestring")
            backup_date = datetime.strptime(datestring, "%Y%m%d%H%M%S")
            if backup.get("result", False):
                email.append(
                    f"    {backup_date}: Success in {backup.get('runtime_secs', 0)} seconds, ID {datestring}, type {backup.get('type', 'unknown')}"
                )
                email.append(
                    f"                         Backup contains {len(backup.get('backup_files'))} files totaling {pvc_ceph.format_bytes_tohuman(backup.get('backup_size_bytes', 0))} ({backup.get('backup_size_bytes', 0)} bytes)"
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

    retcode, vm_list = pvc_vm.get_list(zkhandler)
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

    backup_vms = list()
    for vm in vm_list:
        vm_tag_names = [t["name"] for t in vm["tags"]]
        matching_tags = (
            True
            if len(set(vm_tag_names).intersection(set(config["backup_tags"]))) > 0
            else False
        )
        if matching_tags:
            backup_vms.append(vm)

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
    for vm in backup_vms:
        total_disks = len([d for d in vm["disks"] if d["type"] == "rbd"])
        total_stages += 2 + 1 + 2 + 2 + 3 * total_disks

    log_info(
        celery,
        f"Found {len(backup_vms)} suitable VM(s) for autobackup: {', '.join(vm_list)}",
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
    backup_suffixed_path = (
        f"{config['backup_root_path']}/{config['backup_root_suffix']}"
    )
    if not path.exists(backup_suffixed_path):
        makedirs(backup_suffixed_path)

    full_interval = config["backup_schedule"]["full_interval"]
    full_retention = config["backup_schedule"]["full_retention"]

    for vm in backup_vms:
        vm_name = vm["name"]
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
        snapshot_name = f"autobackup_{datestring}"

        # Take the snapshot
        ret = pvc_vm.vm_worker_create_snapshot(
            zkhandler,
            celery,
            vm_name,
            snapshot_name=snapshot_name,
            override_current_stage=current_stage,
            override_total_stages=total_stages,
        )
        if ret is False:
            error_message = f"Failed to create backup snapshot '{snapshot_name}'"
            log_err(celery, error_message)
            send_execution_failure_report(
                (celery, current_stage, total_stages),
                config,
                recipients=email_recipients,
                error=error_message,
            )
            return False

        # Export the snapshot
        ret = pvc_vm.vm_worker_export_snapshot(
            zkhandler,
            celery,
            vm_name,
            snapshot_name,
            backup_suffixed_path,
            incremental_parent=this_backup_incremental_parent,
            override_current_stage=current_stage,
            override_total_stages=total_stages,
        )
        if ret is False:
            error_message = f"Failed to export backup snapshot '{snapshot_name}'"
            log_err(celery, error_message)
            send_execution_failure_report(
                (celery, current_stage, total_stages),
                config,
                recipients=email_recipients,
                error=error_message,
            )
            return False

        # Clean up the snapshot
        if not this_backup_retain_snapshot:
            ret = pvc_vm.vm_worker_remove_snapshot(
                zkhandler,
                celery,
                vm_name,
                snapshot_name,
                override_current_stage=current_stage,
                override_total_stages=total_stages,
            )
            if ret is False:
                error_message = f"Failed to remove backup snapshot '{snapshot_name}'"
                log_err(celery, error_message)
                send_execution_failure_report(
                    (celery, current_stage, total_stages),
                    config,
                    recipients=email_recipients,
                    error=error_message,
                )
                return False
        else:
            total_disks = len([d for d in vm["disks"] if d["type"] == "rbd"])
            current_stage += 2 + total_disks

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
                ret = pvc_vm.vm_worker_remove_snapshot(
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

        backup_summary[vm] = tracked_backups

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

    send_execution_summary_report(
        (celery, current_stage, total_stages),
        config,
        recipients=email_recipients,
        total_time=autobackup_total_time,
        summary=backup_summary,
    )

    current_stage += 1
    return finish(
        celery,
        f"Successfully completed cluster '{config['cluster']}' VM autobackup",
        current=current_stage,
        total=total_stages,
    )
