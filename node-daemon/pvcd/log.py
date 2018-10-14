#!/usr/bin/env python3

# log.py - Output (stdout + logfile) functions
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

import datetime

class Logger(object):
    # Define a logger class for a daemon instance
    # Keeps record of where to log, and is passed messages which are
    # formatted in various ways based off secondary characteristics.

    # ANSII colours for output
    fmt_red = '\033[91m'
    fmt_blue = '\033[94m'
    fmt_cyan = '\033[96m'
    fmt_green = '\033[92m'
    fmt_yellow = '\033[93m'
    fmt_purple = '\033[95m'
    fmt_bold =  '\033[1m'
    fmt_end = '\033[0m'

    # Initialization of instance
    def __init__(self, config):
        self.config = config
        if self.config['file_logging'] == 'True':
            self.logfile = self.config['log_directory'] + '/pvc.log'
            # We open the logfile for the duration of our session, but have a hup function
            self.writer = open(self.logfile, 'a', buffering=1)
            self.last_colour = self.fmt_cyan
    
    # Provide a hup function to close and reopen the writer
    def hup(self):
        self.writer.close()
        self.writer = open(self.logfile, 'a', buffering=0)

    # Output function
    def out(self, message, state='', prefix=''):

        # Get the date
        date = '{} - '.format(datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S.%f'))
        endc = Logger.fmt_end

        # Determine the formatting
        # OK
        if state == 'o':
            colour = Logger.fmt_green
            prompt = '>>> '
        # Error
        elif state == 'e':
            colour = Logger.fmt_red
            prompt = '>>> '
        # Warning
        elif state == 'w':
            colour = Logger.fmt_yellow
            prompt = '>>> '
        # Tick
        elif state == 't':
            colour = Logger.fmt_purple
            prompt = '>>> '
        # Information
        elif state == 'i':
            colour = Logger.fmt_blue
            prompt = '>>> '
        # Startup
        elif state == 's':
            colour = Logger.fmt_cyan
            prompt = '>>> '
        # Continuation
        else:
            date = ''
            colour = self.last_colour
            prompt = '>>> '
    
        # Append space to prefix
        if prefix != '':
            prefix = prefix + ' - '
    
        message = colour + prompt + endc + date + prefix + message
        print(message)
        if self.config['file_logging'] == 'True':
            self.writer.write(message + '\n')
        self.last_colour = colour
