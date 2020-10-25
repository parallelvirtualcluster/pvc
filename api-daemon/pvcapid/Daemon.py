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

from gevent import monkey
monkey.patch_all()

import gevent.pywsgi
import pvcapid.flaskapi as pvc_api

##########################################################
# Entrypoint
##########################################################
if pvc_api.config['debug']:
    # Run in Flask standard mode
    pvc_api.app.run(pvc_api.config['listen_address'], pvc_api.config['listen_port'], threaded=True)
else:
    if pvc_api.config['ssl_enabled']:
        # Run the WSGI server with SSL
        http_server = gevent.pywsgi.WSGIServer(
            (pvc_api.config['listen_address'], pvc_api.config['listen_port']),
            pvc_api.app,
            keyfile=pvc_api.config['ssl_key_file'],
            certfile=pvc_api.config['ssl_cert_file']
        )
    else:
        # Run the ?WSGI server without SSL
        http_server = gevent.pywsgi.WSGIServer(
            (pvc_api.config['listen_address'], pvc_api.config['listen_port']),
            pvc_api.app
        )

    print('Starting PyWSGI server at {}:{} with SSL={}, Authentication={}'.format(pvc_api.config['listen_address'], pvc_api.config['listen_port'], pvc_api.config['ssl_enabled'], pvc_api.config['auth_enabled']))
    http_server.serve_forever()
