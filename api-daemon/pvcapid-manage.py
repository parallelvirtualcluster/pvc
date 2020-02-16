#!/usr/bin/env python3

# manage.py - PVC Database management tasks
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
from flask_migrate import Migrate, MigrateCommand
from flask_script import Manager

from pvcapid.flaskapi import app, db, config

migrate = Migrate(app, db)
manager = Manager(app)

manager.add_command('db', MigrateCommand)	

if __name__ == '__main__':
    manager.run()
