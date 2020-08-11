#!/usr/bin/env python3

# VMConsoleWatcherInstance.py - Class implementing a console log watcher for PVC domains
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2020 Joshua M. Boniface <joshua@boniface.me>
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

import os
import uuid
import time
import libvirt

from threading import Thread, Event
from collections import deque

import pvcnoded.log as log
import pvcnoded.zkhandler as zkhandler

class VMConsoleWatcherInstance(object):
    # Initialization function
    def __init__(self, domuuid, domname, zk_conn, config, logger, this_node):
        self.domuuid = domuuid
        self.domname = domname
        self.zk_conn = zk_conn
        self.config = config
        self.logfile = '{}/{}.log'.format(config['console_log_directory'], self.domname)
        self.console_log_lines = config['console_log_lines']
        self.logger = logger
        self.this_node = this_node

        # Try to append (create) the logfile and set its permissions
        open(self.logfile, 'a').close()
        os.chmod(self.logfile, 0o600)

        self.logdeque = deque(open(self.logfile), self.console_log_lines)

        self.stamp = None
        self.cached_stamp = None

        # Set up the deque with the current contents of the log
        self.last_loglines = None
        self.loglines = None

        # Thread options
        self.thread = None
        self.thread_stopper = Event()

    # Start execution thread
    def start(self):
        self.thread_stopper.clear()
        self.thread = Thread(target=self.run, args=(), kwargs={})
        self.logger.out('Starting VM log parser', state='i', prefix='Domain {}:'.format(self.domuuid))
        self.thread.start()

    # Stop execution thread
    def stop(self):
        if self.thread and self.thread.isAlive():
            self.logger.out('Stopping VM log parser', state='i', prefix='Domain {}:'.format(self.domuuid))
            self.thread_stopper.set()
            # Do one final flush
            self.update()

    # Main entrypoint
    def run(self):
        # Main loop
        while not self.thread_stopper.is_set():
            self.update()
            time.sleep(0.5)

    def update(self):
        self.stamp = os.stat(self.logfile).st_mtime
        if self.stamp != self.cached_stamp:
            self.cached_stamp = self.stamp
            self.fetch_lines()
        # Update Zookeeper with the new loglines if they changed
        if self.loglines != self.last_loglines:
            zkhandler.writedata(self.zk_conn, { '/domains/{}/consolelog'.format(self.domuuid): self.loglines })
            self.last_loglines = self.loglines

    def fetch_lines(self):
        self.logdeque = deque(open(self.logfile), self.console_log_lines)
        self.loglines = ''.join(self.logdeque)
