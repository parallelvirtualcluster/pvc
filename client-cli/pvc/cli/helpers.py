#!/usr/bin/env python3

# helpers.py - PVC Click CLI helper function library
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

from click import echo as click_echo
from click import confirm
from datetime import datetime
from distutils.util import strtobool
from getpass import getuser
from json import load as jload
from json import dump as jdump
from os import chmod, environ, getpid, path, popen, makedirs, get_terminal_size
from re import findall
from socket import gethostname
from subprocess import run, PIPE
from sys import argv
from syslog import syslog, openlog, closelog, LOG_AUTH
from yaml import load as yload
from yaml import SafeLoader

import pvc.lib.provisioner
import pvc.lib.vm
import pvc.lib.node
import pvc.lib.storage


DEFAULT_STORE_DATA = {"cfgfile": "/etc/pvc/pvc.conf"}
DEFAULT_STORE_FILENAME = "pvc.json"
DEFAULT_API_PREFIX = "/api/v1"
DEFAULT_NODE_HOSTNAME = gethostname().split(".")[0]
DEFAULT_AUTOBACKUP_FILENAME = "/etc/pvc/pvc.conf"

try:
    # Define the content width to be the maximum terminal size
    MAX_CONTENT_WIDTH = get_terminal_size().columns - 1
except OSError:
    # Fall back to 80 columns if "Inappropriate ioctl for device"
    MAX_CONTENT_WIDTH = 80


def echo(config, message, newline=True, stderr=False):
    """
    Output a message with click.echo respecting our configuration
    """

    if config.get("colour", False):
        colour = True
    else:
        colour = None

    if config.get("silent", False):
        pass
    elif config.get("quiet", False) and stderr:
        pass
    else:
        click_echo(message=message, color=colour, nl=newline, err=stderr)


def audit():
    """
    Log an audit message to the local syslog AUTH facility
    """

    args = argv
    pid = getpid()

    openlog(facility=LOG_AUTH, ident=f"{args[0].split('/')[-1]}[{pid}]")
    syslog(
        f"""client audit: command "{' '.join(args)}" by user {environ.get('USER', None)}"""
    )
    closelog()


def read_config_from_yaml(cfgfile):
    """
    Read the PVC API configuration from the local API configuration file
    """

    try:
        with open(cfgfile) as fh:
            api_config = yload(fh, Loader=SafeLoader)["api"]

        host = api_config["listen"]["address"]
        port = api_config["listen"]["port"]
        scheme = "https" if api_config["ssl"]["enabled"] else "http"
        api_key = (
            api_config["token"][0]["token"]
            if api_config["authentication"]["enabled"]
            and api_config["authentication"]["source"] == "token"
            else None
        )
    except KeyError:
        host = None
        port = None
        scheme = None
        api_key = None

    return cfgfile, host, port, scheme, api_key


def get_config(store_data, connection=None):
    """
    Load CLI configuration from store data
    """

    if store_data is None:
        return {"badcfg": True}

    connection_details = store_data.get(connection, None)

    if not connection_details:
        connection = "local"
        connection_details = DEFAULT_STORE_DATA

    if connection_details.get("cfgfile", None) is not None:
        if path.isfile(connection_details.get("cfgfile", None)):
            description, host, port, scheme, api_key = read_config_from_yaml(
                connection_details.get("cfgfile", None)
            )
            if None in [description, host, port, scheme]:
                return {"badcfg": True}
        else:
            return {"badcfg": True}
        # Rewrite a wildcard listener to use localhost instead
        if host == "0.0.0.0":
            host = "127.0.0.1"
    else:
        # This is a static configuration, get the details directly
        description = connection_details["description"]
        host = connection_details["host"]
        port = connection_details["port"]
        scheme = connection_details["scheme"]
        api_key = connection_details["api_key"]

    config = dict()
    config["debug"] = False
    config["connection"] = connection
    config["description"] = description
    config["api_host"] = f"{host}:{port}"
    config["api_scheme"] = scheme
    config["api_key"] = api_key
    config["api_prefix"] = DEFAULT_API_PREFIX
    if connection == "local":
        config["verify_ssl"] = False
    else:
        config["verify_ssl"] = bool(
            strtobool(environ.get("PVC_CLIENT_VERIFY_SSL", "True"))
        )

    return config


def get_store(store_path):
    """
    Load store information from the store path
    """

    store_file = f"{store_path}/{DEFAULT_STORE_FILENAME}"

    with open(store_file) as fh:
        try:
            store_data = jload(fh)
            return store_data
        except Exception:
            return dict()


def update_store(store_path, store_data):
    """
    Update store information to the store path, creating it (with sensible permissions) if needed
    """

    store_file = f"{store_path}/{DEFAULT_STORE_FILENAME}"

    if not path.exists(store_file):
        with open(store_file, "w") as fh:
            fh.write("")
        chmod(store_file, int(environ.get("PVC_CLIENT_DB_PERMS", "600"), 8))

    with open(store_file, "w") as fh:
        jdump(store_data, fh, sort_keys=True, indent=4)


def get_autobackup_config(CLI_CONFIG, cfgfile):
    try:
        config = dict()
        with open(cfgfile) as fh:
            full_config = yload(fh, Loader=SafeLoader)
        backup_config = full_config["autobackup"]
        config["backup_root_path"] = backup_config["backup_root_path"]
        config["backup_root_suffix"] = backup_config["backup_root_suffix"]
        config["backup_tags"] = backup_config["backup_tags"]
        config["backup_schedule"] = backup_config["backup_schedule"]
        config["auto_mount_enabled"] = backup_config["auto_mount"]["enabled"]
        if config["auto_mount_enabled"]:
            config["mount_cmds"] = list()
            _mount_cmds = backup_config["auto_mount"]["mount_cmds"]
            for _mount_cmd in _mount_cmds:
                if "{backup_root_path}" in _mount_cmd:
                    _mount_cmd = _mount_cmd.format(
                        backup_root_path=backup_config["backup_root_path"]
                    )
                config["mount_cmds"].append(_mount_cmd)

            config["unmount_cmds"] = list()
            _unmount_cmds = backup_config["auto_mount"]["unmount_cmds"]
            for _unmount_cmd in _unmount_cmds:
                if "{backup_root_path}" in _unmount_cmd:
                    _unmount_cmd = _unmount_cmd.format(
                        backup_root_path=backup_config["backup_root_path"]
                    )
                config["unmount_cmds"].append(_unmount_cmd)
    except FileNotFoundError:
        return "Backup configuration does not exist!"
    except KeyError as e:
        return f"Backup configuration is invalid: {e}"

    return config


def vm_autobackup(
    CLI_CONFIG,
    autobackup_cfgfile=DEFAULT_AUTOBACKUP_FILENAME,
    email_report=None,
    force_full_flag=False,
    cron_flag=False,
):
    """
    Perform automatic backups of VMs based on an external config file.
    """

    backup_summary = dict()

    if email_report is not None:
        from email.utils import formatdate
        from socket import gethostname

        try:
            with open(autobackup_cfgfile) as fh:
                tmp_config = yload(fh, Loader=SafeLoader)
            cluster = tmp_config["cluster"]["name"]
        except Exception:
            cluster = "unknown"

    def send_execution_failure_report(error=None):
        echo(CLI_CONFIG, f"Sending email failure report to {email_report}")

        current_datetime = datetime.now()
        email_datetime = formatdate(float(current_datetime.strftime("%s")))

        email = list()
        email.append(f"Date: {email_datetime}")
        email.append(f"Subject: PVC Autobackup execution failure for cluster {cluster}")

        recipients = list()
        for recipient in email_report.split(","):
            recipients.append(f"<{recipient}>")
        email.append(f"To: {', '.join(recipients)}")
        email.append(f"From: PVC Autobackup System <pvc@{gethostname()}>")
        email.append("")

        email.append(
            f"A PVC autobackup has FAILED at {current_datetime} due to an execution error."
        )
        email.append("")
        email.append("The reported error message is:")
        email.append(f"    {error}")

        try:
            p = popen("/usr/sbin/sendmail -t", "w")
            p.write("\n".join(email))
            p.close()
        except Exception as e:
            echo(CLI_CONFIG, f"Failed to send report email: {e}")

    # Validate that we are running on the current primary coordinator of the 'local' cluster connection
    real_connection = CLI_CONFIG["connection"]
    CLI_CONFIG["connection"] = "local"
    retcode, retdata = pvc.lib.node.node_info(CLI_CONFIG, DEFAULT_NODE_HOSTNAME)
    if not retcode or retdata.get("coordinator_state") != "primary":
        if cron_flag:
            echo(
                CLI_CONFIG,
                "Current host is not the primary coordinator of the local cluster and running in cron mode. Exiting cleanly.",
            )
            exit(0)
        else:
            echo(
                CLI_CONFIG,
                f"ERROR: Current host is not the primary coordinator of the local cluster; got connection '{real_connection}', host '{DEFAULT_NODE_HOSTNAME}'.",
            )
            echo(
                CLI_CONFIG,
                "Autobackup MUST be run from the cluster active primary coordinator using the 'local' connection. See '-h'/'--help' for details.",
            )
            if email_report is not None:
                send_execution_failure_report(
                    error=f"Autobackup run attempted from non-local connection or non-primary coordinator; got connection '{real_connection}', host '{DEFAULT_NODE_HOSTNAME}'."
                )
            exit(1)

    # Ensure we're running as root, or show a warning & confirmation
    if getuser() != "root":
        confirm(
            "WARNING: You are not running this command as 'root'. This command should be run under the same user as the API daemon, which is usually 'root'. Are you sure you want to continue?",
            prompt_suffix=" ",
            abort=True,
        )

    # Load our YAML config
    autobackup_config = get_autobackup_config(CLI_CONFIG, autobackup_cfgfile)
    if not isinstance(autobackup_config, dict):
        echo(CLI_CONFIG, f"ERROR: {autobackup_config}")
        if email_report is not None:
            send_execution_failure_report(error=f"{autobackup_config}")
        exit(1)

    # Get the start time of this run
    autobackup_start_time = datetime.now()

    # Get a list of all VMs on the cluster
    # We don't do tag filtering here, because we could match an arbitrary number of tags; instead, we
    # parse the list after
    retcode, retdata = pvc.lib.vm.vm_list(CLI_CONFIG, None, None, None, None, None)
    if not retcode:
        echo(CLI_CONFIG, f"ERROR: Failed to fetch VM list: {retdata}")
        if email_report is not None:
            send_execution_failure_report(error=f"Failed to fetch VM list: {retdata}")
        exit(1)
    cluster_vms = retdata

    # Parse the list to match tags; too complex for list comprehension alas
    backup_vms = list()
    for vm in cluster_vms:
        vm_tag_names = [t["name"] for t in vm["tags"]]
        matching_tags = (
            True
            if len(
                set(vm_tag_names).intersection(set(autobackup_config["backup_tags"]))
            )
            > 0
            else False
        )
        if matching_tags:
            backup_vms.append(vm["name"])

    if len(backup_vms) < 1:
        echo(CLI_CONFIG, "Found no suitable VMs for autobackup.")
        exit(0)

    # Pretty print the names of the VMs we'll back up (to stderr)
    maxnamelen = max([len(n) for n in backup_vms]) + 2
    cols = 1
    while (cols * maxnamelen + maxnamelen + 2) <= MAX_CONTENT_WIDTH:
        cols += 1
    rows = len(backup_vms) // cols
    vm_list_rows = list()
    for row in range(0, rows + 1):
        row_start = row * cols
        row_end = (row * cols) + cols
        row_str = ""
        for x in range(row_start, row_end):
            if x < len(backup_vms):
                row_str += "{:<{}}".format(backup_vms[x], maxnamelen)
        vm_list_rows.append(row_str)

    echo(CLI_CONFIG, f"Found {len(backup_vms)} suitable VM(s) for autobackup.")
    echo(CLI_CONFIG, "Full VM list:", stderr=True)
    echo(CLI_CONFIG, "  {}".format("\n  ".join(vm_list_rows)), stderr=True)
    echo(CLI_CONFIG, "", stderr=True)

    if autobackup_config["auto_mount_enabled"]:
        # Execute each mount_cmds command in sequence
        for cmd in autobackup_config["mount_cmds"]:
            echo(
                CLI_CONFIG,
                f"Executing mount command '{cmd.split()[0]}'... ",
                newline=False,
            )
            tstart = datetime.now()
            ret = run(
                cmd.split(),
                stdout=PIPE,
                stderr=PIPE,
            )
            tend = datetime.now()
            ttot = tend - tstart
            if ret.returncode != 0:
                echo(
                    CLI_CONFIG,
                    f"failed. [{ttot.seconds}s]",
                )
                echo(
                    CLI_CONFIG,
                    f"Exiting; command reports: {ret.stderr.decode().strip()}",
                )
                if email_report is not None:
                    send_execution_failure_report(error=ret.stderr.decode().strip())
                exit(1)
            else:
                echo(CLI_CONFIG, f"done. [{ttot.seconds}s]")

    # For each VM, perform the backup
    for vm in backup_vms:
        backup_suffixed_path = f"{autobackup_config['backup_root_path']}{autobackup_config['backup_root_suffix']}"
        if not path.exists(backup_suffixed_path):
            makedirs(backup_suffixed_path)

        backup_path = f"{backup_suffixed_path}/{vm}"
        autobackup_state_file = f"{backup_path}/.autobackup.json"
        if not path.exists(backup_path) or not path.exists(autobackup_state_file):
            # There are no new backups so the list is empty
            state_data = dict()
            tracked_backups = list()
        else:
            with open(autobackup_state_file) as fh:
                state_data = jload(fh)
            tracked_backups = state_data["tracked_backups"]

        full_interval = autobackup_config["backup_schedule"]["full_interval"]
        full_retention = autobackup_config["backup_schedule"]["full_retention"]

        full_backups = [b for b in tracked_backups if b["type"] == "full"]
        if len(full_backups) > 0:
            last_full_backup = full_backups[0]
            last_full_backup_idx = tracked_backups.index(last_full_backup)
            if force_full_flag:
                this_backup_type = "forced-full"
                this_backup_incremental_parent = None
                this_backup_retain_snapshot = True
            elif last_full_backup_idx >= full_interval - 1:
                this_backup_type = "full"
                this_backup_incremental_parent = None
                this_backup_retain_snapshot = True
            else:
                this_backup_type = "incremental"
                this_backup_incremental_parent = last_full_backup["datestring"]
                this_backup_retain_snapshot = False
        else:
            # The very first backup must be full to start the tree
            this_backup_type = "full"
            this_backup_incremental_parent = None
            this_backup_retain_snapshot = True

        # Perform the backup
        echo(
            CLI_CONFIG,
            f"Backing up VM '{vm}' ({this_backup_type})... ",
            newline=False,
        )
        tstart = datetime.now()
        retcode, retdata = pvc.lib.vm.vm_backup(
            CLI_CONFIG,
            vm,
            backup_suffixed_path,
            incremental_parent=this_backup_incremental_parent,
            retain_snapshot=this_backup_retain_snapshot,
        )
        tend = datetime.now()
        ttot = tend - tstart
        if not retcode:
            backup_datestring = findall(r"[0-9]{14}", retdata)[0]
            echo(CLI_CONFIG, f"failed. [{ttot.seconds}s]")
            echo(
                CLI_CONFIG,
                retdata.strip().replace(f"ERROR in backup {backup_datestring}: ", ""),
            )
            skip_cleanup = True
        else:
            backup_datestring = findall(r"[0-9]{14}", retdata)[0]
            echo(
                CLI_CONFIG,
                f"done. Backup '{backup_datestring}' created. [{ttot.seconds}s]",
            )
            skip_cleanup = False

        # Read backup file to get details
        backup_json_file = f"{backup_path}/{backup_datestring}/pvcbackup.json"
        with open(backup_json_file) as fh:
            backup_json = jload(fh)
        tracked_backups.insert(0, backup_json)

        # Delete any full backups that are expired
        marked_for_deletion = list()
        found_full_count = 0
        for backup in tracked_backups:
            if backup["type"] == "full":
                found_full_count += 1
                if found_full_count > full_retention:
                    marked_for_deletion.append(backup)

        # Depete any incremental backups that depend on marked parents
        for backup in tracked_backups:
            if backup["type"] == "incremental" and backup["incremental_parent"] in [
                b["datestring"] for b in marked_for_deletion
            ]:
                marked_for_deletion.append(backup)

        if len(marked_for_deletion) > 0:
            if skip_cleanup:
                echo(
                    CLI_CONFIG,
                    f"Skipping cleanups for {len(marked_for_deletion)} aged-out backups due to backup failure.",
                )
            else:
                echo(
                    CLI_CONFIG,
                    f"Running cleanups for {len(marked_for_deletion)} aged-out backups...",
                )
                # Execute deletes
                for backup_to_delete in marked_for_deletion:
                    echo(
                        CLI_CONFIG,
                        f"Removing old VM '{vm}' backup '{backup_to_delete['datestring']}' ({backup_to_delete['type']})... ",
                        newline=False,
                    )
                    tstart = datetime.now()
                    retcode, retdata = pvc.lib.vm.vm_remove_backup(
                        CLI_CONFIG,
                        vm,
                        backup_suffixed_path,
                        backup_to_delete["datestring"],
                    )
                    tend = datetime.now()
                    ttot = tend - tstart
                    if not retcode:
                        echo(CLI_CONFIG, f"failed. [{ttot.seconds}s]")
                        echo(
                            CLI_CONFIG,
                            f"Skipping removal from tracked backups; command reports: {retdata}",
                        )
                    else:
                        tracked_backups.remove(backup_to_delete)
                        echo(CLI_CONFIG, f"done. [{ttot.seconds}s]")

        # Update tracked state information
        state_data["tracked_backups"] = tracked_backups
        with open(autobackup_state_file, "w") as fh:
            jdump(state_data, fh)

        backup_summary[vm] = tracked_backups

    if autobackup_config["auto_mount_enabled"]:
        # Execute each unmount_cmds command in sequence
        for cmd in autobackup_config["unmount_cmds"]:
            echo(
                CLI_CONFIG,
                f"Executing unmount command '{cmd.split()[0]}'... ",
                newline=False,
            )
            tstart = datetime.now()
            ret = run(
                cmd.split(),
                stdout=PIPE,
                stderr=PIPE,
            )
            tend = datetime.now()
            ttot = tend - tstart
            if ret.returncode != 0:
                echo(
                    CLI_CONFIG,
                    f"failed. [{ttot.seconds}s]",
                )
                echo(
                    CLI_CONFIG,
                    f"Continuing; command reports: {ret.stderr.decode().strip()}",
                )
            else:
                echo(CLI_CONFIG, f"done. [{ttot.seconds}s]")

    autobackup_end_time = datetime.now()
    autobackup_total_time = autobackup_end_time - autobackup_start_time

    # Handle report emailing
    if email_report is not None:
        echo(CLI_CONFIG, "")
        echo(CLI_CONFIG, f"Sending email summary report to {email_report}")

        current_datetime = datetime.now()
        email_datetime = formatdate(float(current_datetime.strftime("%s")))

        email = list()
        email.append(f"Date: {email_datetime}")
        email.append(f"Subject: PVC Autobackup report for cluster {cluster}")

        recipients = list()
        for recipient in email_report.split(","):
            recipients.append(f"<{recipient}>")
        email.append(f"To: {', '.join(recipients)}")
        email.append(f"From: PVC Autobackup System <pvc@{gethostname()}>")
        email.append("")

        email.append(
            f"A PVC autobackup has been completed at {current_datetime} in {autobackup_total_time}."
        )
        email.append("")
        email.append(
            "The following is a summary of all current VM backups after cleanups, most recent first:"
        )
        email.append("")

        for vm in backup_vms:
            email.append(f"VM {vm}:")
            for backup in backup_summary[vm]:
                datestring = backup.get("datestring")
                backup_date = datetime.strptime(datestring, "%Y%m%d%H%M%S")
                if backup.get("result", False):
                    email.append(
                        f"    {backup_date}: Success in {backup.get('runtime_secs', 0)} seconds, ID {datestring}, type {backup.get('type', 'unknown')}"
                    )
                    email.append(
                        f"                         Backup contains {len(backup.get('backup_files'))} files totaling {pvc.lib.storage.format_bytes_tohuman(backup.get('backup_size_bytes', 0))} ({backup.get('backup_size_bytes', 0)} bytes)"
                    )
                else:
                    email.append(
                        f"    {backup_date}: Failure in {backup.get('runtime_secs', 0)} seconds, ID {datestring}, type {backup.get('type', 'unknown')}"
                    )
                    email.append(
                        f"                         {backup.get('result_message')}"
                    )

        try:
            p = popen("/usr/sbin/sendmail -t", "w")
            p.write("\n".join(email))
            p.close()
        except Exception as e:
            echo(CLI_CONFIG, f"Failed to send report email: {e}")

    echo(CLI_CONFIG, "")
    echo(CLI_CONFIG, f"Autobackup completed in {autobackup_total_time}.")
