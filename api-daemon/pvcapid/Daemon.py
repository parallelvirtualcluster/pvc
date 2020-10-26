#!/usr/bin/env python3

# Daemon.py - PVC HTTP API daemon
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

import pvcapid.flaskapi as pvc_api

##########################################################
# Entrypoint
##########################################################

if pvc_api.config['ssl_enabled']:
    context = (pvc_api.config['ssl_cert_file'], pvc_api.config['ssl_key_file'])
else:
    context=None

print('Starting PVC API daemon at {}:{} with SSL={}, Authentication={}'.format(pvc_api.config['listen_address'], pvc_api.config['listen_port'], pvc_api.config['ssl_enabled'], pvc_api.config['auth_enabled']))
pvc_api.app.run(pvc_api.config['listen_address'], pvc_api.config['listen_port'], threaded=True, ssl_context=context)
