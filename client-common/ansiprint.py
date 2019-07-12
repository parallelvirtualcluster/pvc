#!/usr/bin/env python3

# ansiprint.py - Printing function for formatted messages
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

# ANSII colours for output
def red():
    return '\033[91m'
def blue():
    return '\033[94m'
def cyan():
    return '\033[96m'
def green():
    return '\033[92m'
def yellow():
    return '\033[93m'
def purple():
    return '\033[95m'
def bold():
    return '\033[1m'
def end():
    return '\033[0m'

# Print function
def echo(message, prefix, state):
    # Get the date
    date = '{} - '.format(datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S.%f'))
    endc = end()

    # Continuation
    if state == 'c':
        date = ''
        colour = ''
        prompt = '    '
    # OK
    elif state == 'o':
        colour = green()
        prompt = '>>> '
    # Error
    elif state == 'e':
        colour = red()
        prompt = '>>> '
    # Warning
    elif state == 'w':
        colour = yellow()
        prompt = '>>> '
    # Tick
    elif state == 't':
        colour = purple()
        prompt = '>>> '
    # Information
    elif state == 'i':
        colour = blue()
        prompt = '>>> '
    else:
        colour = bold()
        prompt = '>>> '

    # Append space to prefix
    if prefix != '':
        prefix = prefix + ' '

    print(colour + prompt + endc + date + prefix + message)
