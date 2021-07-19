#!/usr/bin/env python3

# log.py - PVC daemon logger functions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2021 Joshua M. Boniface <joshua@boniface.me>
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

from collections import deque
from threading import Thread
from queue import Queue
from datetime import datetime
from time import sleep

from daemon_lib.zkhandler import ZKHandler


class Logger(object):
    # Define a logger class for a daemon instance
    # Keeps record of where to log, and is passed messages which are
    # formatted in various ways based off secondary characteristics.

    # ANSII colours for output
    fmt_red = '\033[91m'
    fmt_green = '\033[92m'
    fmt_yellow = '\033[93m'
    fmt_blue = '\033[94m'
    fmt_purple = '\033[95m'
    fmt_cyan = '\033[96m'
    fmt_white = '\033[97m'
    fmt_bold = '\033[1m'
    fmt_end = '\033[0m'

    last_colour = ''
    last_prompt = ''

    # Format maps
    format_map_colourized = {
        # Colourized formatting with chevron prompts (log_colours = True)
        'o': {'colour': fmt_green, 'prompt': '>>> '},
        'e': {'colour': fmt_red, 'prompt': '>>> '},
        'w': {'colour': fmt_yellow, 'prompt': '>>> '},
        't': {'colour': fmt_purple, 'prompt': '>>> '},
        'i': {'colour': fmt_blue, 'prompt': '>>> '},
        's': {'colour': fmt_cyan, 'prompt': '>>> '},
        'd': {'colour': fmt_white, 'prompt': '>>> '},
        'x': {'colour': last_colour, 'prompt': last_prompt}
    }
    format_map_textual = {
        # Uncolourized formatting with text prompts (log_colours = False)
        'o': {'colour': '', 'prompt': 'ok: '},
        'e': {'colour': '', 'prompt': 'failed: '},
        'w': {'colour': '', 'prompt': 'warning: '},
        't': {'colour': '', 'prompt': 'tick: '},
        'i': {'colour': '', 'prompt': 'info: '},
        's': {'colour': '', 'prompt': 'system: '},
        'd': {'colour': '', 'prompt': 'debug: '},
        'x': {'colour': '', 'prompt': last_prompt}
    }

    # Initialization of instance
    def __init__(self, config):
        self.config = config

        if self.config['file_logging']:
            self.logfile = self.config['log_directory'] + '/pvc.log'
            # We open the logfile for the duration of our session, but have a hup function
            self.writer = open(self.logfile, 'a', buffering=0)

        self.last_colour = ''
        self.last_prompt = ''

        if self.config['zookeeper_logging']:
            self.zookeeper_queue = Queue()
            self.zookeeper_logger = ZookeeperLogger(self.config, self.zookeeper_queue)
            self.zookeeper_logger.start()

    # Provide a hup function to close and reopen the writer
    def hup(self):
        self.writer.close()
        self.writer = open(self.logfile, 'a', buffering=0)

    # Provide a termination function so all messages are flushed before terminating the main daemon
    def terminate(self):
        if self.config['file_logging']:
            self.writer.close()
        if self.config['zookeeper_logging']:
            self.out("Waiting 15s for Zookeeper message queue to drain", state='s')

            tick_count = 0
            while not self.zookeeper_queue.empty():
                sleep(0.5)
                tick_count += 1
                if tick_count > 30:
                    break

            self.zookeeper_logger.stop()
            self.zookeeper_logger.join()

    # Output function
    def out(self, message, state=None, prefix=''):

        # Get the date
        if self.config['log_dates']:
            date = '{} '.format(datetime.now().strftime('%Y/%m/%d %H:%M:%S.%f'))
        else:
            date = ''

        # Get the format map
        if self.config['log_colours']:
            format_map = self.format_map_colourized
            endc = Logger.fmt_end
        else:
            format_map = self.format_map_textual
            endc = ''

        # Define an undefined state as 'x'; no date in these prompts
        if not state:
            state = 'x'
            date = ''

        # Get colour and prompt from the map
        colour = format_map[state]['colour']
        prompt = format_map[state]['prompt']

        # Append space and separator to prefix
        if prefix != '':
            prefix = prefix + ' - '

        # Assemble message string
        message = colour + prompt + endc + date + prefix + message

        # Log to stdout
        if self.config['stdout_logging']:
            print(message)

        # Log to file
        if self.config['file_logging']:
            self.writer.write(message + '\n')

        # Log to Zookeeper
        if self.config['zookeeper_logging']:
            self.zookeeper_queue.put(message)

        # Set last message variables
        self.last_colour = colour
        self.last_prompt = prompt


class ZookeeperLogger(Thread):
    """
    Defines a threaded writer for Zookeeper locks. Threading prevents the blocking of other
    daemon events while the records are written. They will be eventually-consistent
    """
    def __init__(self, config, zookeeper_queue):
        self.config = config
        self.node = self.config['node']
        self.max_lines = self.config['node_log_lines']
        self.zookeeper_queue = zookeeper_queue
        self.connected = False
        self.running = False
        self.zkhandler = None
        Thread.__init__(self, args=(), kwargs=None)

    def start_zkhandler(self):
        # We must open our own dedicated Zookeeper instance because we can't guarantee one already exists when this starts
        if self.zkhandler is not None:
            try:
                self.zkhandler.disconnect()
            except Exception:
                pass

        while True:
            try:
                self.zkhandler = ZKHandler(self.config, logger=None)
                self.zkhandler.connect(persistent=True)
                break
            except Exception:
                sleep(0.5)
                continue

        self.connected = True

        # Ensure the root keys for this are instantiated
        self.zkhandler.write([
            ('base.logs', ''),
            (('logs', self.node), '')
        ])

    def run(self):
        while not self.connected:
            self.start_zkhandler()
            sleep(1)

        self.running = True
        # Get the logs that are currently in Zookeeper and populate our deque
        raw_logs = self.zkhandler.read(('logs.messages', self.node))
        if raw_logs is None:
            raw_logs = ''
        logs = deque(raw_logs.split('\n'), self.max_lines)
        while self.running:
            # Get a new message
            try:
                message = self.zookeeper_queue.get(timeout=1)
                if not message:
                    continue
            except Exception:
                continue

            if not self.config['log_dates']:
                # We want to log dates here, even if the log_dates config is not set
                date = '{} '.format(datetime.now().strftime('%Y/%m/%d %H:%M:%S.%f'))
            else:
                date = ''
            # Add the message to the deque
            logs.append(f'{date}{message}')

            tick_count = 0
            while True:
                try:
                    # Write the updated messages into Zookeeper
                    self.zkhandler.write([(('logs.messages', self.node), '\n'.join(logs))])
                    break
                except Exception:
                    # The write failed (connection loss, etc.) so retry for 15 seconds
                    sleep(0.5)
                    tick_count += 1
                    if tick_count > 30:
                        break
                    else:
                        continue
        return

    def stop(self):
        self.running = False
