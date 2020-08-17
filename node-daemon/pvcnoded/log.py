#!/usr/bin/env python3

# log.py - Output (stdout + logfile) functions
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

import datetime

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
    fmt_bold =  '\033[1m'
    fmt_end = '\033[0m'

    last_colour = ''
    last_prompt = ''

    # Format maps
    format_map_colourized = {
         # Colourized formatting with chevron prompts (log_colours = True)
        'o': { 'colour': fmt_green,   'prompt': '>>> '      },
        'e': { 'colour': fmt_red,     'prompt': '>>> '      },
        'w': { 'colour': fmt_yellow,  'prompt': '>>> '      },
        't': { 'colour': fmt_purple,  'prompt': '>>> '      },
        'i': { 'colour': fmt_blue,    'prompt': '>>> '      },
        's': { 'colour': fmt_cyan,    'prompt': '>>> '      },
        'd': { 'colour': fmt_white,   'prompt': '>>> '      },
        'x': { 'colour': last_colour, 'prompt': last_prompt }
    }
    format_map_textual = {
         # Uncolourized formatting with text prompts (log_colours = False)
        'o': { 'colour': '', 'prompt': 'ok: '      },
        'e': { 'colour': '', 'prompt': 'failed: '  },
        'w': { 'colour': '', 'prompt': 'warning: ' },
        't': { 'colour': '', 'prompt': 'tick: '    },
        'i': { 'colour': '', 'prompt': 'info: '    },
        's': { 'colour': '', 'prompt': 'system: '  },
        'd': { 'colour': '', 'prompt': 'debug: '   },
        'x': { 'colour': '', 'prompt': last_prompt }
    }

    # Initialization of instance
    def __init__(self, config):
        self.config = config

        if self.config['file_logging']:
            self.logfile = self.config['log_directory'] + '/pvc.log'
            # We open the logfile for the duration of our session, but have a hup function
            self.writer = open(self.logfile, 'a', buffering=1)

        self.last_colour = ''
        self.last_prompt = ''

    # Provide a hup function to close and reopen the writer
    def hup(self):
        self.writer.close()
        self.writer = open(self.logfile, 'a', buffering=0)

    # Output function
    def out(self, message, state=None, prefix=''):

        # Get the date
        if self.config['log_dates']:
            date = '{} - '.format(datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S.%f'))
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

        # Set last message variables
        self.last_colour = colour
        self.last_prompt = prompt
