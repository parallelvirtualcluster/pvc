#!/usr/bin/env python3

# automirror.py - PVC API Automirror functions
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

import requests

from datetime import datetime
from os import popen

from daemon_lib.config import get_automirror_configuration
from daemon_lib.celery import start, fail, log_info, log_warn, log_err, update, finish

import daemon_lib.vm as vm


def send_execution_failure_report(
    celery, config, recipients=None, total_time=0, error=None
):
    if recipients is None:
        return

    from email.utils import formatdate
    from socket import gethostname

    log_message = f"Sending email failure report to {', '.join(recipients)}"
    log_info(celery, log_message)

    current_datetime = datetime.now()
    email_datetime = formatdate(float(current_datetime.strftime("%s")))

    email = list()
    email.append(f"Date: {email_datetime}")
    email.append(
        f"Subject: PVC Automirror execution failure for cluster '{config['cluster']}'"
    )

    email_to = list()
    for recipient in recipients:
        email_to.append(f"<{recipient}>")

    email.append(f"To: {', '.join(email_to)}")
    email.append(f"From: PVC Automirror System <pvc@{gethostname()}>")
    email.append("")

    email.append(
        f"A PVC automirror has FAILED at {current_datetime} in {total_time}s due to an execution error."
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
    celery,
    config,
    recipients=None,
    total_time=0,
    summary=dict(),
    local_deleted_snapshots=dict(),
):
    if recipients is None:
        return

    from email.utils import formatdate
    from socket import gethostname

    log_message = f"Sending email summary report to {', '.join(recipients)}"
    log_info(celery, log_message)

    current_datetime = datetime.now()
    email_datetime = formatdate(float(current_datetime.strftime("%s")))

    email = list()
    email.append(f"Date: {email_datetime}")
    email.append(f"Subject: PVC Automirror report for cluster '{config['cluster']}'")

    email_to = list()
    for recipient in recipients:
        email_to.append(f"<{recipient}>")

    email.append(f"To: {', '.join(email_to)}")
    email.append(f"From: PVC Automirror System <pvc@{gethostname()}>")
    email.append("")

    email.append(
        f"A PVC automirror has been completed at {current_datetime} in {total_time}."
    )
    email.append("")
    email.append(
        "The following is a summary of all VM mirror jobs executed during this run:"
    )
    email.append("")

    vm_names = {k.split(":")[0] for k in summary.keys()}
    for vm_name in vm_names:
        email.append(f"VM {vm_name}:")
        email.append("  Mirror jobs:")
        for destination_name in {
            k.split(":")[1] for k in summary.keys() if k.split(":")[0] == vm_name
        }:
            mirror = summary[f"{vm_name}:{destination_name}"]
            datestring = mirror.get("snapshot_name").replace("am", "")
            mirror_date = datetime.strptime(datestring, "%Y%m%d%H%M%S")
            if mirror.get("result", False):
                email.append(
                    f"    * {mirror_date}: Success to cluster {destination_name} in {mirror.get('runtime_secs', 0)} seconds, ID {mirror.get('snapshot_name')}"
                )
            else:
                email.append(
                    f"    * {mirror_date}: Failure to cluster {destination_name} in {mirror.get('runtime_secs', 0)} seconds, ID {mirror.get('snapshot_name')}"
                )
                email.append(
                    f"                           {mirror.get('result_message')}"
                )

        email.append(
            "  The following aged-out local snapshots were removed during cleanup:"
        )
        for snapshot in local_deleted_snapshots[vm_name]:
            email.append(f"    * {snapshot}")

    try:
        with popen("/usr/sbin/sendmail -t", "w") as p:
            p.write("\n".join(email))
    except Exception as e:
        log_err(f"Failed to send report email: {e}")


def run_vm_mirror(
    zkhandler, celery, config, vm_detail, snapshot_name, destination_name
):
    vm_name = vm_detail["name"]
    keep_count = config["mirror_keep_snapshots"]

    try:
        destination = config["mirror_destinations"][destination_name]
    except Exception:
        error_message = f"Failed to find valid destination cluster '{destination_name}' for VM '{vm_name}'"
        log_err(celery, error_message)
        return error_message

    destination_api_uri = f"{'https' if destination['ssl'] else 'http'}://{destination['address']}:{destination['port']}{destination['prefix']}"
    destination_api_timeout = (3.05, 172800)
    destination_api_headers = {
        "X-Api-Key": destination["key"],
    }

    session = requests.Session()
    session.headers.update(destination_api_headers)
    session.verify = destination["verify_ssl"]
    session.timeout = destination_api_timeout

    # Get the last snapshot that is on the remote side for incrementals
    response = session.get(
        f"{destination_api_uri}/vm/{vm_name}",
        params=None,
        data=None,
    )
    destination_vm_detail = response.json()
    if type(destination_vm_detail) is list and len(destination_vm_detail) > 0:
        destination_vm_detail = destination_vm_detail[0]
        try:
            last_snapshot_name = [
                s
                for s in destination_vm_detail["snapshots"]
                if s["name"].startswith("am")
            ][0]["name"]
        except Exception:
            last_snapshot_name = None
    else:
        last_snapshot_name = None

    # Send the current snapshot
    result, message = vm.vm_worker_send_snapshot(
        zkhandler,
        None,
        vm_name,
        snapshot_name,
        destination_api_uri,
        destination["key"],
        destination_api_verify_ssl=destination["verify_ssl"],
        incremental_parent=last_snapshot_name,
        destination_storage_pool=destination["pool"],
        return_status=True,
    )

    if not result:
        return False, message

    response = session.get(
        f"{destination_api_uri}/vm/{vm_name}",
        params=None,
        data=None,
    )
    destination_vm_detail = response.json()
    if type(destination_vm_detail) is list and len(destination_vm_detail) > 0:
        destination_vm_detail = destination_vm_detail[0]
    else:
        message = "Remote VM somehow does not exist after successful mirror; skipping snapshot cleanup"
        return False, message

    # Find any mirror snapshots that are expired
    remote_snapshots = [
        s for s in destination_vm_detail["snapshots"] if s["name"].startswith("am")
    ]

    # Snapshots are in dated descending order due to the names
    if len(remote_snapshots) > keep_count:
        remote_marked_for_deletion = [s["name"] for s in remote_snapshots[keep_count:]]
    else:
        remote_marked_for_deletion = list()

    for snapshot in remote_marked_for_deletion:
        log_info(
            celery,
            f"VM {vm_detail['name']} removing stale remote automirror snapshot {snapshot}",
        )
        session.delete(
            f"{destination_api_uri}/vm/{vm_name}/snapshot",
            params={
                "snapshot_name": snapshot,
            },
            data=None,
        )

    session.close()

    return True, remote_marked_for_deletion


def worker_cluster_automirror(
    zkhandler,
    celery,
    force_full=False,
    email_recipients=None,
    email_errors_only=False,
):
    config = get_automirror_configuration()

    mirror_summary = dict()
    local_deleted_snapshots = dict()

    current_stage = 0
    total_stages = 1

    start(
        celery,
        f"Starting cluster '{config['cluster']}' VM automirror",
        current=current_stage,
        total=total_stages,
    )

    if not config["automirror_enabled"]:
        message = "Automirrors are not configured on this cluster."
        log_info(celery, message)
        return finish(
            celery,
            message,
            current=total_stages,
            total=total_stages,
        )

    if email_recipients is not None:
        total_stages += 1

    automirror_start_time = datetime.now()

    retcode, vm_list = vm.get_list(zkhandler)
    if not retcode:
        error_message = f"Failed to fetch VM list: {vm_list}"
        log_err(celery, error_message)
        current_stage += 1
        send_execution_failure_report(
            celery,
            config,
            recipients=email_recipients,
            error=error_message,
        )
        fail(celery, error_message)
        return False

    mirror_vms = list()
    for vm_detail in vm_list:
        mirror_vm = {
            "detail": vm_detail,
            "destinations": list(),
        }
        vm_tag_names = [t["name"] for t in vm_detail["tags"]]
        # Check if any of the mirror tags are present; if they are, then we should mirror
        vm_mirror_tags = list()
        for tag in vm_tag_names:
            if tag.split(":")[0] in config["mirror_tags"]:
                vm_mirror_tags.append(tag)

        # There are no mirror tags, so skip this VM
        if len(vm_mirror_tags) < 1:
            continue

        # Go through each tag to extract the cluster
        target_clusters = set()
        for tag in vm_mirror_tags:
            if len(tag.split(":")) == 1:
                # This is a direct match without any cluster suffix, so use the default
                target_clusters.add(config["mirror_default_destination"])
            if len(tag.split(":")) > 1:
                # This has a cluster suffix, so use that
                target_clusters.add(tag.split(":")[1])

        for cluster in target_clusters:
            mirror_vm["destinations"].append(cluster)

        mirror_vms.append(mirror_vm)

    if len(mirror_vms) < 1:
        message = "Found no VMs tagged for automirror."
        log_info(celery, message)
        return finish(
            celery,
            message,
            current=total_stages,
            total=total_stages,
        )

    total_stages += len(mirror_vms)

    mirror_vm_names = set([b["detail"]["name"] for b in mirror_vms])

    log_info(
        celery,
        f"Found {len(mirror_vm_names)} suitable VM(s) for automirror: {', '.join(mirror_vm_names)}",
    )

    # Execute the backup: take a snapshot, then export the snapshot
    for mirror_vm in mirror_vms:
        vm_detail = mirror_vm["detail"]
        vm_destinations = mirror_vm["destinations"]

        current_stage += 1
        update(
            celery,
            f"Performing automirror of VM {vm_detail['name']}",
            current=current_stage,
            total=total_stages,
        )

        # Automirrors use a custom name to allow them to be properly cleaned up later
        now = datetime.now()
        datestring = now.strftime("%Y%m%d%H%M%S")
        snapshot_name = f"am{datestring}"

        result, message = vm.vm_worker_create_snapshot(
            zkhandler,
            None,
            vm_detail["name"],
            snapshot_name=snapshot_name,
            return_status=True,
        )
        if not result:
            for destination in vm_destinations:
                mirror_summary[f"{vm_detail['name']}:{destination}"] = {
                    "result": result,
                    "snapshot_name": snapshot_name,
                    "runtime_secs": 0,
                    "result_message": message,
                }
            continue

        remote_marked_for_deletion = dict()
        all_results = list()
        for destination in vm_destinations:
            mirror_start = datetime.now()
            result, ret = run_vm_mirror(
                zkhandler,
                celery,
                config,
                vm_detail,
                snapshot_name,
                destination,
            )
            mirror_end = datetime.now()
            runtime_secs = (mirror_end - mirror_start).seconds
            all_results.append(result)
            if result:
                remote_marked_for_deletion[destination] = ret

                mirror_summary[f"{vm_detail['name']}:{destination}"] = {
                    "result": result,
                    "snapshot_name": snapshot_name,
                    "runtime_secs": runtime_secs,
                }
            else:
                log_warn(
                    celery,
                    f"Error in mirror send: {ret}",
                )
                mirror_summary[f"{vm_detail['name']}:{destination}"] = {
                    "result": result,
                    "snapshot_name": snapshot_name,
                    "runtime_secs": runtime_secs,
                    "result_message": ret,
                }

        # If all sends failed, remove the snapshot we created as it will never be needed or automatically cleaned up later
        if not any(all_results):
            vm.vm_worker_remove_snapshot(
                zkhandler,
                None,
                vm_detail["name"],
                snapshot_name,
            )

        # Find all local snapshots that were present in all remote snapshot deletions,
        # then remove them
        # If one of the sends fails, this should result in nothing being removed
        if remote_marked_for_deletion:
            all_lists = [set(lst) for lst in remote_marked_for_deletion.values() if lst]
            if all_lists:
                local_marked_for_deletion = set.intersection(*all_lists)
            else:
                local_marked_for_deletion = set()
        else:
            local_marked_for_deletion = set()

        for snapshot in local_marked_for_deletion:
            log_info(
                celery,
                f"VM {vm_detail['name']} removing stale local automirror snapshot {snapshot}",
            )
            vm.vm_worker_remove_snapshot(
                zkhandler,
                None,
                vm_detail["name"],
                snapshot,
            )

        local_deleted_snapshots[vm_detail["name"]] = local_marked_for_deletion

    automirror_end_time = datetime.now()
    automirror_total_time = automirror_end_time - automirror_start_time

    if email_recipients is not None:
        current_stage += 1
        if email_errors_only and not all(
            [s["result"] for _, s in mirror_summary.items()]
        ):
            # Send report if we're in errors only and at least one send failed
            send_report = True
        elif not email_errors_only:
            # Send report if we're not in errors only
            send_report = True
        else:
            # Otherwise (errors only and all successful) don't send
            send_report = False

        if send_report:
            update(
                celery,
                "Sending automirror results summary email",
                current=current_stage,
                total=total_stages,
            )
            send_execution_summary_report(
                celery,
                config,
                recipients=email_recipients,
                total_time=automirror_total_time,
                summary=mirror_summary,
                local_deleted_snapshots=local_deleted_snapshots,
            )
        else:
            update(
                celery,
                "Skipping automirror results summary email (no failures)",
                current=current_stage,
                total=total_stages,
            )

    current_stage += 1
    return finish(
        celery,
        f"Successfully completed cluster '{config['cluster']}' VM automirror",
        current=current_stage,
        total=total_stages,
    )
