#!/usr/bin/env python3

# pvcapid.py - API daemon startup stub
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
from os import path

# Ensure current directory (/usr/share/pvc) is in the system path for Gunicorn
current_dir = path.dirname(path.abspath(__file__))
sys.path.append(current_dir)

import pvcapid.Daemon  # noqa: F401

pvcapid.Daemon.entrypoint()
