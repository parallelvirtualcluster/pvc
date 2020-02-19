#!/usr/bin/env python3

# common.py - PVC CLI client function library, Common functions
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

import requests
import click

def call_api(config, operation, request_uri, params=None, data=None, files=None):
    # Craft the URI
    uri = '{}://{}{}{}'.format(
        config['api_scheme'],
        config['api_host'],
        config['api_prefix'],
        request_uri
    )

    # Craft the authentication header if required
    if config['api_key']:
        headers = {'X-Api-Key': config['api_key']}
    else:
        headers = None

    # Determine the request type and hit the API
    try:
        if operation == 'get':
            response = requests.get(
                uri,
                headers=headers,
                params=params,
                data=data
            )
        if operation == 'post':
            response = requests.post(
                uri,
                headers=headers,
                params=params,
                data=data,
                files=files
            )
        if operation == 'put':
            response = requests.put(
                uri,
                headers=headers,
                params=params,
                data=data,
                files=files
            )
        if operation == 'patch':
            response = requests.patch(
                uri,
                headers=headers,
                params=params,
                data=data
            )
        if operation == 'delete':
            response = requests.delete(
                uri,
                headers=headers,
                params=params,
                data=data
            )
    except Exception as e:
        return 'Failed to connect to the API: {}'.format(e)

    # Display debug output
    if config['debug']:
        click.echo('API endpoint: {}'.format(uri), err=True)
        click.echo('Response code: {}'.format(response.status_code), err=True)
        click.echo('Response headers: {}'.format(response.headers), err=True)
        click.echo(err=True)

    # Return the response object
    return response

