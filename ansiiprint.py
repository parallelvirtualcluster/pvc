#!/usr/bin/env python3

# ansiprint.py - Printing function for formatted daemon messages
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

import os, sys, socket, time, libvirt, kazoo.client, threading, fencenode, ansiiprint

# Print function
def echo(message, prefix, state):
    date = '{} - '.format(time.strftime('%Y/%m/%d %H:%M:%S'))
    # Continuation
    if state == 'c':
        date = ''
        colour = ''
        prompt = '    '
    # OK
    elif state == 'o':
        colour = '\033[92m' # Green
        prompt = '>>> '
    # Error
    elif state == 'e':
        colour = '\033[91m' # Red
        prompt = '>>> '
    # Warning
    elif state == 'w':
        colour = '\033[93m' # Yellow
        prompt = '>>> '
    # Tick
    elif state == 't':
        colour = '\033[95m' # Purple
        prompt = '>>> '
    # Information
    elif state == 'i':
        colour = '\033[94m' # Blue
        prompt = '>>> '
    else:
        colour = '\033[1m' # Bold
        prompt = '>>> '
    end = '\033[0m'
    print(colour + prompt + end + date + prefix + '{}'.format(message))
