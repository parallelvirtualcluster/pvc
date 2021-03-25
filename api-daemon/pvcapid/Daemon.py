#!/usr/bin/env python3

# Daemon.py - PVC HTTP API daemon
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

import pvcapid.flaskapi as pvc_api

##########################################################
# Entrypoint
##########################################################

# Version string for startup output
version = '0.9.11'

if pvc_api.config['ssl_enabled']:
    context = (pvc_api.config['ssl_cert_file'], pvc_api.config['ssl_key_file'])
else:
    context = None

# Print our startup messages
print('')
print('|--------------------------------------------------|')
print('|           ########  ##     ##  ######            |')
print('|           ##     ## ##     ## ##    ##           |')
print('|           ##     ## ##     ## ##                 |')
print('|           ########  ##     ## ##                 |')
print('|           ##         ##   ##  ##                 |')
print('|           ##          ## ##   ##    ##           |')
print('|           ##           ###     ######            |')
print('|--------------------------------------------------|')
print('| Parallel Virtual Cluster API daemon v{0: <11} |'.format(version))
print('| API version: v{0: <34} |'.format(pvc_api.API_VERSION))
print('| Listen: {0: <40} |'.format('{}:{}'.format(pvc_api.config['listen_address'], pvc_api.config['listen_port'])))
print('| SSL: {0: <43} |'.format(str(pvc_api.config['ssl_enabled'])))
print('| Authentication: {0: <32} |'.format(str(pvc_api.config['auth_enabled'])))
print('|--------------------------------------------------|')
print('')

pvc_api.app.run(pvc_api.config['listen_address'], pvc_api.config['listen_port'], threaded=True, ssl_context=context)
