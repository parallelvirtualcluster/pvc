#!/usr/bin/env python3

# waiters.py - PVC Click CLI output waiters library
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

import sys

from click import progressbar
from time import sleep, time

from pvc.cli.helpers import echo

import pvc.lib.node


def cli_node_waiter(config, node, state_field, state_value):
    """
    Wait for state transitions for cli_node tasks

    {node} is the name of the node
    {state_field} is the node_info field to check for {state_value}
    {state_value} is the TRANSITIONAL value that, when no longer set, will terminate waiting
    """

    # Sleep for this long between API polls
    sleep_time = 1

    # Print a dot after this many {sleep_time}s
    dot_time = 5

    t_start = time()

    echo(config, "Waiting...", newline=False)
    sleep(sleep_time)

    count = 0
    while True:
        count += 1
        try:
            _retcode, _retdata = pvc.lib.node.node_info(config, node)
            if _retdata[state_field] != state_value:
                break
            else:
                raise ValueError
        except Exception:
            sleep(sleep_time)
            if count % dot_time == 0:
                echo(config, ".", newline=False)

    t_end = time()
    echo(config, f" done. [{int(t_end - t_start)}s]")


def wait_for_celery_task(CLI_CONFIG, task_detail, start_late=False):
    """
    Wait for a Celery task to complete
    """

    task_id = task_detail["task_id"]
    task_name = task_detail["task_name"]

    if not start_late:
        run_on = task_detail["run_on"]

        echo(CLI_CONFIG, f"Task ID: {task_id} ({task_name}) assigned to node {run_on}")
        echo(CLI_CONFIG, "")

        # Wait for the task to start
        echo(CLI_CONFIG, "Waiting for task to start...", newline=False)
        while True:
            sleep(0.5)
            task_status = pvc.lib.common.task_status(
                CLI_CONFIG, task_id=task_id, is_watching=True
            )
            if task_status.get("state") != "PENDING":
                break
            echo(CLI_CONFIG, ".", newline=False)
        echo(CLI_CONFIG, " done.")
        echo(CLI_CONFIG, "")

        echo(
            CLI_CONFIG,
            task_status.get("status") + ":",
        )
    else:
        task_status = pvc.lib.common.task_status(
            CLI_CONFIG, task_id=task_id, is_watching=True
        )

        echo(CLI_CONFIG, f"Watching existing task {task_id} ({task_name}):")

    # Start following the task state, updating progress as we go
    total_task = task_status.get("total")
    with progressbar(length=total_task, show_eta=False) as bar:
        last_task = 0
        maxlen = 21
        echo(
            CLI_CONFIG,
            "  " + "Gathering information",
            newline=False,
        )
        while True:
            sleep(0.5)

            task_status = pvc.lib.common.task_status(
                CLI_CONFIG, task_id=task_id, is_watching=True
            )

            if isinstance(task_status, tuple):
                continue
            if task_status.get("state") != "RUNNING":
                break
            if task_status.get("current") == 0:
                continue

            current_task = int(task_status.get("current"))
            total_task = int(task_status.get("total"))
            bar.length = total_task

            if current_task > last_task:
                bar.update(current_task - last_task)
                last_task = current_task

            curlen = len(str(task_status.get("status")))
            if curlen > maxlen:
                maxlen = curlen
            lendiff = maxlen - curlen
            overwrite_whitespace = " " * lendiff

            percent_complete = (current_task / total_task) * 100
            bar_output = f"[{bar.format_bar()}]  {percent_complete:3.0f}%"
            sys.stdout.write(
                f"\r  {bar_output}  {task_status['status']}{overwrite_whitespace}"
            )
            sys.stdout.flush()

        if task_status.get("state") == "SUCCESS":
            bar.update(total_task - last_task)

    echo(CLI_CONFIG, "")
    retdata = task_status.get("state") + ": " + task_status.get("status")

    return retdata
