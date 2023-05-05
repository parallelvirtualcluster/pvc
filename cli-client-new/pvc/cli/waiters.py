#!/usr/bin/env python3

# waiters.py - PVC Click CLI output waiters library
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2023 Joshua M. Boniface <joshua@boniface.me>
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
