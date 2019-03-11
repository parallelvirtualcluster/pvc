#!/usr/bin/env python3

# bootstrap_http_server.py - PVC bootstrap HTTP server class
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

import http.server
import socketserver
import atexit
import json

LISTEN_PORT = 10080

next_nodeid = 0

def get_next_nodeid():
    global next_nodeid
    new_nodeid = next_nodeid + 1
    next_nodeid = new_nodeid
    return str(new_nodeid)

class CheckinHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/node_checkin':
            # A node is checking in
            print('Node checking in...')
            # Get the next available ID
            node_id = get_next_nodeid()
            print('Assigned new node ID {}'.format(node_id))
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            pvcd_conf = 'test'
            install_script = """#!/bin/bash
echo "Hello, world!"
"""
            body = { 'node_id': node_id, 'pvcd_conf': pvcd_conf, 'install_script': install_script }
            self.wfile.write(json.dumps(body).encode('ascii'))
        else:
            self.send_error(404)

httpd = socketserver.TCPServer(("", LISTEN_PORT), CheckinHandler, bind_and_activate=False)
httpd.allow_reuse_address = True
httpd.server_bind()
httpd.server_activate()

def cleanup():
    httpd.shutdown()
atexit.register(cleanup)

print("serving at port", LISTEN_PORT)
httpd.serve_forever()
