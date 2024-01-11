#!/usr/bin/env python3

# pvcapid-manage_flask.py - PVC Database management tasks (via Flask CLI)
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

from pvcapid.flaskapi import app, db
from pvcapid.models import *  # noqa F401,F403

from flask_migrate import Migrate

migrate = Migrate(app, db)

# Call flask --app /usr/share/pvc/pvcapid-manage_flask.py db upgrade
