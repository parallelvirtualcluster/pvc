#!/usr/bin/env python3

# lazy_imports.py - Lazy module importer library
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

class LazyModule:
    """
    A proxy for a module that is loaded only when actually used
    """
    def __init__(self, name):
        self.name = name
        self._module = None

    def __getattr__(self, attr):
        if self._module is None:
            import importlib
            self._module = importlib.import_module(self.name)
        return getattr(self._module, attr)

# Create lazy module proxies
yaml = LazyModule('yaml')
click_advanced = LazyModule('click')  # For advanced click features not used at startup