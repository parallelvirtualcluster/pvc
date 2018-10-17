#!/usr/bin/env python3

# common.py - PVC daemon function library, common fuctions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018  Joshua M. Boniface <joshua@boniface.me>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
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

import subprocess
import threading
import signal
import os
import time

import pvcd.log as log

class OSDaemon(object):
    def __init__(self, command_string, environment, logfile):
        command = command_string.split()
        # Set stdout to be a logfile if set
        if logfile:
            stdout = open(logfile, 'a')
        else:
            stdout = subprocess.PIPE

        # Invoke the process
        self.proc = subprocess.Popen(
            command,
            env=environment,
            stdout=stdout,
            stderr=stdout,
        )

    # Signal the process
    def signal(self, sent_signal):
        signal_map = {
            'hup': signal.SIGHUP,
            'int': signal.SIGINT,
            'term': signal.SIGTERM,
            'kill': signal.SIGKILL
        }
        self.proc.send_signal(signal_map[sent_signal])

def run_os_daemon(command_string, environment=None, logfile=None):
    daemon = OSDaemon(command_string, environment, logfile)
    return daemon

# Run a oneshot command, optionally without blocking
def run_os_command(command_string, background=False, environment=None):
    command = command_string.split()
    if background:
        def runcmd():
            subprocess.run(
                command,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        thread = threading.Thread(target=runcmd, args=())
        thread.start()
        return 0, None, None
    else:
        command_output = subprocess.run(
            command,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return command_output.returncode, command_output.stdout.decode('ascii'), command_output.stderr.decode('ascii')

# Reload the firewall rules of the system
def reload_firewall_rules(rules_dir):
    log.echo('Updating firewall rules', '', 'o')
    rules_file = '{}/base.nft'.format(rules_dir)
    retcode, stdout, stderr = run_os_command('/usr/sbin/nft -f {}'.format(rules_file))
    if retcode != 0:
        log.echo('Failed to reload rules: {}'.format(stderr), '', 'e')
