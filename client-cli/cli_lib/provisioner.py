#!/usr/bin/env python3

# provisioner.py - PVC CLI client function library, Provisioner functions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2019 Joshua M. Boniface <joshua@boniface.me>
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

import time
import re
import subprocess
import click
import requests

import cli_lib.ansiprint as ansiprint

def get_request_uri(config, endpoint):
    """
    Return the fully-formed URI for {endpoint}
    """
    uri = '{}://{}{}{}'.format(
        config['api_scheme'],
        config['api_host'],
        config['api_prefix'],
        endpoint
    )
    return uri

#
# Primary functions
#
def template_info(config, template, template_type):
    """
    Get information about template

    API endpoint: GET /api/v1/provisioner/template/{template_type}/{template}
    API arguments:
    API schema: {json_template_object}
    """
    request_uri = get_request_uri(config, '/provisioner/template/{template_type}/{template}'.format(template_type=template_type, template=template))
    response = requests.get(
        request_uri
    )

    if config['debug']:
        print('API endpoint: GET {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']

def template_list(config, limit, template_type=None):
    """
    Get list information about templates (limited by {limit})

    API endpoint: GET /api/v1/provisioner/template/{template_type}
    API arguments: limit={limit}
    API schema: [{json_template_object},{json_template_object},etc.]
    """
    params = dict()
    if limit:
        params['limit'] = limit

    if template_type is not None:
        request_uri = get_request_uri(config, '/provisioner/template/{template_type}'.format(template_type=template_type))
    else:
        request_uri = get_request_uri(config, '/provisioner/template')
    response = requests.get(
        request_uri,
        params=params
    )

    if config['debug']:
        print('API endpoint: GET {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']

def template_add(config, params, template_type=None):
    """
    Add a new template of {template_type} with {params}

    API endpoint: POST /api/v1/provisioner/template/{template_type}
    API_arguments: args
    API schema: {message}
    """
    request_uri = get_request_uri(config, '/provisioner/template/{template_type}'.format(template_type=template_type))
    response = requests.post(
        request_uri,
        params=params
    )

    if config['debug']:
        print('API endpoint: POST {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        retvalue = True
    else:
        retvalue = False
        
    return retvalue, response.json()['message']

def template_remove(config, name, template_type=None):
    """
    Remove template {name} of {template_type}

    API endpoint: DELETE /api/v1/provisioner/template/{template_type}/{name}
    API_arguments:
    API schema: {message}
    """
    request_uri = get_request_uri(config, '/provisioner/template/{template_type}/{name}'.format(template_type=template_type, name=name))
    response = requests.delete(
        request_uri
    )

    if config['debug']:
        print('API endpoint: DELETE {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        retvalue = True
    else:
        retvalue = False
        
    return retvalue, response.json()['message']

def template_element_add(config, name, element_id, params, element_type=None, template_type=None):
    """
    Add a new template element of {element_type} with {params} to template {name} of {template_type}

    API endpoint: POST /api/v1/provisioner/template/{template_type}/{name}/{element_type}/{element_id}
    API_arguments: args
    API schema: {message}
    """
    request_uri = get_request_uri(config, '/provisioner/template/{template_type}/{name}/{element_type}/{element_id}'.format(template_type=template_type, name=name, element_type=element_type, element_id=element_id))
    response = requests.post(
        request_uri,
        params=params
    )

    if config['debug']:
        print('API endpoint: POST {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        retvalue = True
    else:
        retvalue = False
        
    return retvalue, response.json()['message']

def template_element_remove(config, name, element_id, element_type=None, template_type=None):
    """
    Remove template element {element_id} of {element_type} from template {name} of {template_type}

    API endpoint: DELETE /api/v1/provisioner/template/{template_type}/{name}/{element_type}/{element_id}
    API_arguments:
    API schema: {message}
    """
    request_uri = get_request_uri(config, '/provisioner/template/{template_type}/{name}/{element_type}/{element_id}'.format(template_type=template_type, name=name, element_type=element_type, element_id=element_id))
    response = requests.delete(
        request_uri
    )

    if config['debug']:
        print('API endpoint: DELETE {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        retvalue = True
    else:
        retvalue = False
        
    return retvalue, response.json()['message']

def userdata_info(config, userdata):
    """
    Get information about userdata

    API endpoint: GET /api/v1/provisioner/userdata/{userdata}
    API arguments:
    API schema: {json_data_object}
    """
    request_uri = get_request_uri(config, '/provisioner/userdata/{userdata}'.format(userdata=userdata))
    response = requests.get(
        request_uri
    )

    if config['debug']:
        print('API endpoint: GET {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        return True, response.json()[0]
    else:
        return False, response.json()['message']

def userdata_list(config, limit):
    """
    Get list information about userdatas (limited by {limit})

    API endpoint: GET /api/v1/provisioner/userdata/{userdata_type}
    API arguments: limit={limit}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    if limit:
        params['limit'] = limit

    request_uri = get_request_uri(config, '/provisioner/userdata')
    response = requests.get(
        request_uri,
        params=params
    )

    if config['debug']:
        print('API endpoint: GET {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']

def userdata_add(config, params):
    """
    Add a new userdata with {params}

    API endpoint: POST /api/v1/provisioner/userdata
    API_arguments: args
    API schema: {message}
    """
    request_uri = get_request_uri(config, '/provisioner/userdata')
    response = requests.post(
        request_uri,
        params=params
    )

    if config['debug']:
        print('API endpoint: POST {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        retvalue = True
    else:
        retvalue = False
        
    return retvalue, response.json()['message']

def userdata_modify(config, name, params):
    """
    Modify userdata {name} with {params}

    API endpoint: PUT /api/v1/provisioner/userdata/{name}
    API_arguments: args
    API schema: {message}
    """
    request_uri = get_request_uri(config, '/provisioner/userdata/{name}'.format(name=name))
    response = requests.put(
        request_uri,
        params=params
    )

    if config['debug']:
        print('API endpoint: PUT {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        retvalue = True
    else:
        retvalue = False
        
    return retvalue, response.json()['message']

def userdata_remove(config, name):
    """
    Remove userdata {name}

    API endpoint: DELETE /api/v1/provisioner/userdata/{name}
    API_arguments:
    API schema: {message}
    """
    request_uri = get_request_uri(config, '/provisioner/userdata/{name}'.format(name=name))
    response = requests.delete(
        request_uri
    )

    if config['debug']:
        print('API endpoint: DELETE {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        retvalue = True
    else:
        retvalue = False
        
    return retvalue, response.json()['message']

def script_info(config, script):
    """
    Get information about script

    API endpoint: GET /api/v1/provisioner/script/{script}
    API arguments:
    API schema: {json_data_object}
    """
    request_uri = get_request_uri(config, '/provisioner/script/{script}'.format(script=script))
    response = requests.get(
        request_uri
    )

    if config['debug']:
        print('API endpoint: GET {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        return True, response.json()[0]
    else:
        return False, response.json()['message']

def script_list(config, limit):
    """
    Get list information about scripts (limited by {limit})

    API endpoint: GET /api/v1/provisioner/script/{script_type}
    API arguments: limit={limit}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    if limit:
        params['limit'] = limit

    request_uri = get_request_uri(config, '/provisioner/script')
    response = requests.get(
        request_uri,
        params=params
    )

    if config['debug']:
        print('API endpoint: GET {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']

def script_add(config, params):
    """
    Add a new script with {params}

    API endpoint: POST /api/v1/provisioner/script
    API_arguments: args
    API schema: {message}
    """
    request_uri = get_request_uri(config, '/provisioner/script')
    response = requests.post(
        request_uri,
        params=params
    )

    if config['debug']:
        print('API endpoint: POST {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        retvalue = True
    else:
        retvalue = False
        
    return retvalue, response.json()['message']

def script_modify(config, name, params):
    """
    Modify script {name} with {params}

    API endpoint: PUT /api/v1/provisioner/script/{name}
    API_arguments: args
    API schema: {message}
    """
    request_uri = get_request_uri(config, '/provisioner/script/{name}'.format(name=name))
    response = requests.put(
        request_uri,
        params=params
    )

    if config['debug']:
        print('API endpoint: PUT {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        retvalue = True
    else:
        retvalue = False
        
    return retvalue, response.json()['message']

def script_remove(config, name):
    """
    Remove script {name}

    API endpoint: DELETE /api/v1/provisioner/script/{name}
    API_arguments:
    API schema: {message}
    """
    request_uri = get_request_uri(config, '/provisioner/script/{name}'.format(name=name))
    response = requests.delete(
        request_uri
    )

    if config['debug']:
        print('API endpoint: DELETE {}'.format(request_uri))
        print('Response code: {}'.format(response.status_code))
        print('Response headers: {}'.format(response.headers))

    if response.status_code == 200:
        retvalue = True
    else:
        retvalue = False
        
    return retvalue, response.json()['message']

#
# Format functions
#
def format_list_template(template_template, template_type=None):
    """
    Format the returned template template

    template_type can be used to only display part of the full list, allowing function
    reuse with more limited output options.
    """
    template_types = [ 'system', 'network', 'storage' ]
    normalized_template_template = dict()

    if template_type in template_types:
        template_types = [ template_type ]
        template_template_type = '{}_templates'.format(template_type)
        normalized_template_template[template_template_type] = template_template
    else:
        normalized_template_template = template_template

    if 'system' in template_types:
        click.echo('System templates:')
        click.echo()
        format_list_template_system(normalized_template_template['system_templates'])
        if len(template_types) > 1:
            click.echo()

    if 'network' in template_types:
        click.echo('Network templates:')
        click.echo()
        format_list_template_network(normalized_template_template['network_templates'])
        if len(template_types) > 1:
            click.echo()

    if 'storage' in template_types:
        click.echo('Storage templates:')
        click.echo()
        format_list_template_storage(normalized_template_template['storage_templates'])

def format_list_template_system(template_template):
    if isinstance(template_template, dict):
        template_template = [ template_template ]

    template_list_output = []

    # Determine optimal column widths
    template_name_length = 5
    template_id_length = 4
    template_vcpu_length = 6
    template_vram_length = 10
    template_serial_length = 7
    template_vnc_length = 4
    template_vnc_bind_length = 10
    template_node_limit_length = 9
    template_node_selector_length = 11
    template_node_autostart_length = 11

    for template in template_template:
        # template_name column
        _template_name_length = len(str(template['name'])) + 1
        if _template_name_length > template_name_length:
            template_name_length = _template_name_length
        # template_id column
        _template_id_length = len(str(template['id'])) + 1
        if _template_id_length > template_id_length:
            template_id_length = _template_id_length
        # template_vcpu column
        _template_vcpu_length = len(str(template['vcpu_count'])) + 1
        if _template_vcpu_length > template_vcpu_length:
            template_vcpu_length = _template_vcpu_length
        # template_vram column
        _template_vram_length = len(str(template['vram_mb'])) + 1
        if _template_vram_length > template_vram_length:
            template_vram_length = _template_vram_length
        # template_serial column
        _template_serial_length = len(str(template['serial'])) + 1
        if _template_serial_length > template_serial_length:
            template_serial_length = _template_serial_length
        # template_vnc column
        _template_vnc_length = len(str(template['vnc'])) + 1
        if _template_vnc_length > template_vnc_length:
            template_vnc_length = _template_vnc_length
        # template_vnc_bind column
        _template_vnc_bind_length = len(str(template['vnc_bind'])) + 1
        if _template_vnc_bind_length > template_vnc_bind_length:
            template_vnc_bind_length = _template_vnc_bind_length
        # template_node_limit column
        _template_node_limit_length = len(str(template['node_limit'])) + 1
        if _template_node_limit_length > template_node_limit_length:
            template_node_limit_length = _template_node_limit_length
        # template_node_selector column
        _template_node_selector_length = len(str(template['node_selector'])) + 1
        if _template_node_selector_length > template_node_selector_length:
            template_node_selector_length = _template_node_selector_length
        # template_node_autostart column
        _template_node_autostart_length = len(str(template['node_autostart'])) + 1
        if _template_node_autostart_length > template_node_autostart_length:
            template_node_autostart_length = _template_node_autostart_length

    # Format the string (header)
    template_list_output_header = '{bold}{template_name: <{template_name_length}} {template_id: <{template_id_length}} \
{template_vcpu: <{template_vcpu_length}} \
{template_vram: <{template_vram_length}} \
Consoles: {template_serial: <{template_serial_length}} \
{template_vnc: <{template_vnc_length}} \
{template_vnc_bind: <{template_vnc_bind_length}} \
Metatemplate: {template_node_limit: <{template_node_limit_length}} \
{template_node_selector: <{template_node_selector_length}} \
{template_node_autostart: <{template_node_autostart_length}}{end_bold}'.format(
            template_name_length=template_name_length,
            template_id_length=template_id_length,
            template_vcpu_length=template_vcpu_length,
            template_vram_length=template_vram_length,
            template_serial_length=template_serial_length,
            template_vnc_length=template_vnc_length,
            template_vnc_bind_length=template_vnc_bind_length,
            template_node_limit_length=template_node_limit_length,
            template_node_selector_length=template_node_selector_length,
            template_node_autostart_length=template_node_autostart_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            template_state_colour='',
            end_colour='',
            template_name='Name',
            template_id='ID',
            template_vcpu='vCPUs',
            template_vram='vRAM [MB]',
            template_serial='Serial',
            template_vnc='VNC',
            template_vnc_bind='VNC bind',
            template_node_limit='Limit',
            template_node_selector='Selector',
            template_node_autostart='Autostart'
        )

    # Keep track of nets we found to be valid to cut down on duplicate API hits
    valid_net_list = []
    # Format the string (elements)

    for template in sorted(template_template, key=lambda i: i.get('name', None)):
        template_list_output.append(
            '{bold}{template_name: <{template_name_length}} {template_id: <{template_id_length}} \
{template_vcpu: <{template_vcpu_length}} \
{template_vram: <{template_vram_length}} \
          {template_serial: <{template_serial_length}} \
{template_vnc: <{template_vnc_length}} \
{template_vnc_bind: <{template_vnc_bind_length}} \
          {template_node_limit: <{template_node_limit_length}} \
{template_node_selector: <{template_node_selector_length}} \
{template_node_autostart: <{template_node_autostart_length}}{end_bold}'.format(
                template_name_length=template_name_length,
                template_id_length=template_id_length,
                template_vcpu_length=template_vcpu_length,
                template_vram_length=template_vram_length,
                template_serial_length=template_serial_length,
                template_vnc_length=template_vnc_length,
                template_vnc_bind_length=template_vnc_bind_length,
                template_node_limit_length=template_node_limit_length,
                template_node_selector_length=template_node_selector_length,
                template_node_autostart_length=template_node_autostart_length,
                bold='',
                end_bold='',
                template_name=str(template['name']),
                template_id=str(template['id']),
                template_vcpu=str(template['vcpu_count']),
                template_vram=str(template['vram_mb']),
                template_serial=str(template['serial']),
                template_vnc=str(template['vnc']),
                template_vnc_bind=str(template['vnc_bind']),
                template_node_limit=str(template['node_limit']),
                template_node_selector=str(template['node_selector']),
                template_node_autostart=str(template['node_autostart'])
            )
        )

    click.echo('\n'.join([template_list_output_header] + template_list_output))

    return True, ''

def format_list_template_network(template_template):
    if isinstance(template_template, dict):
        template_template = [ template_template ]

    template_list_output = []

    # Determine optimal column widths
    template_name_length = 5
    template_id_length = 4
    template_mac_template_length = 13
    template_networks_length = 10

    for template in template_template:
        # Join the networks elements into a single list of VNIs
        network_list = list()
        for network in template['networks']:
            network_list.append(str(network['vni']))
        template['networks_csv'] = ','.join(network_list)

    for template in template_template:
        # template_name column
        _template_name_length = len(str(template['name'])) + 1
        if _template_name_length > template_name_length:
            template_name_length = _template_name_length
        # template_id column
        _template_id_length = len(str(template['id'])) + 1
        if _template_id_length > template_id_length:
            template_id_length = _template_id_length
        # template_mac_template column
        _template_mac_template_length = len(str(template['mac_template'])) + 1
        if _template_mac_template_length > template_mac_template_length:
            template_mac_template_length = _template_mac_template_length
        # template_networks column
        _template_networks_length = len(str(template['networks_csv'])) + 1
        if _template_networks_length > template_networks_length:
            template_networks_length = _template_networks_length

    # Format the string (header)
    template_list_output_header = '{bold}{template_name: <{template_name_length}} {template_id: <{template_id_length}} \
{template_mac_template: <{template_mac_template_length}} \
{template_networks: <{template_networks_length}}{end_bold}'.format(
            template_name_length=template_name_length,
            template_id_length=template_id_length,
            template_mac_template_length=template_mac_template_length,
            template_networks_length=template_networks_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            template_name='Name',
            template_id='ID',
            template_mac_template='MAC template',
            template_networks='Network VNIs'
        )

    # Format the string (elements)
    for template in sorted(template_template, key=lambda i: i.get('name', None)):
        template_list_output.append(
            '{bold}{template_name: <{template_name_length}} {template_id: <{template_id_length}} \
{template_mac_template: <{template_mac_template_length}} \
{template_networks: <{template_networks_length}}{end_bold}'.format(
                template_name_length=template_name_length,
                template_id_length=template_id_length,
                template_mac_template_length=template_mac_template_length,
                template_networks_length=template_networks_length,
                bold='',
                end_bold='',
                template_name=str(template['name']),
                template_id=str(template['id']),
                template_mac_template=str(template['mac_template']),
                template_networks=str(template['networks_csv'])
            )
        )

    click.echo('\n'.join([template_list_output_header] + template_list_output))

    return True, ''

def format_list_template_storage(template_template):
    if isinstance(template_template, dict):
        template_template = [ template_template ]

    template_list_output = []

    # Determine optimal column widths
    template_name_length = 5
    template_id_length = 4
    template_disk_id_length = 8
    template_disk_pool_length = 8
    template_disk_size_length = 10
    template_disk_filesystem_length = 11
    template_disk_fsargs_length = 10
    template_disk_mountpoint_length = 10

    for template in template_template:
        # template_name column
        _template_name_length = len(str(template['name'])) + 1
        if _template_name_length > template_name_length:
            template_name_length = _template_name_length
        # template_id column
        _template_id_length = len(str(template['id'])) + 1
        if _template_id_length > template_id_length:
            template_id_length = _template_id_length

        for disk in template['disks']:
            # template_disk_id column
            _template_disk_id_length = len(str(disk['disk_id'])) + 1
            if _template_disk_id_length > template_disk_id_length:
                template_disk_id_length = _template_disk_id_length
            # template_disk_pool column
            _template_disk_pool_length = len(str(disk['pool'])) + 1
            if _template_disk_pool_length > template_disk_pool_length:
                template_disk_pool_length = _template_disk_pool_length
            # template_disk_size column
            _template_disk_size_length = len(str(disk['disk_size_gb'])) + 1
            if _template_disk_size_length > template_disk_size_length:
                template_disk_size_length = _template_disk_size_length
            # template_disk_filesystem column
            _template_disk_filesystem_length = len(str(disk['filesystem'])) + 1
            if _template_disk_filesystem_length > template_disk_filesystem_length:
                template_disk_filesystem_length = _template_disk_filesystem_length
            # template_disk_fsargs column
            _template_disk_fsargs_length = len(str(disk['filesystem_args'])) + 1
            if _template_disk_fsargs_length > template_disk_fsargs_length:
                template_disk_fsargs_length = _template_disk_fsargs_length
            # template_disk_mountpoint column
            _template_disk_mountpoint_length = len(str(disk['mountpoint'])) + 1
            if _template_disk_mountpoint_length > template_disk_mountpoint_length:
                template_disk_mountpoint_length = _template_disk_mountpoint_length

    # Format the string (header)
    template_list_output_header = '{bold}{template_name: <{template_name_length}} {template_id: <{template_id_length}} \
{template_disk_id: <{template_disk_id_length}} \
{template_disk_pool: <{template_disk_pool_length}} \
{template_disk_size: <{template_disk_size_length}} \
{template_disk_filesystem: <{template_disk_filesystem_length}} \
{template_disk_fsargs: <{template_disk_fsargs_length}} \
{template_disk_mountpoint: <{template_disk_mountpoint_length}}{end_bold}'.format(
            template_name_length=template_name_length,
            template_id_length=template_id_length,
            template_disk_id_length=template_disk_id_length,
            template_disk_pool_length=template_disk_pool_length,
            template_disk_size_length=template_disk_size_length,
            template_disk_filesystem_length=template_disk_filesystem_length,
            template_disk_fsargs_length=template_disk_fsargs_length,
            template_disk_mountpoint_length=template_disk_mountpoint_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            template_name='Name',
            template_id='ID',
            template_disk_id='Disk ID',
            template_disk_pool='Pool',
            template_disk_size='Size [GB]',
            template_disk_filesystem='Filesystem',
            template_disk_fsargs='Arguments',
            template_disk_mountpoint='Mountpoint'
        )

    # Format the string (elements)
    for template in sorted(template_template, key=lambda i: i.get('name', None)):
        template_list_output.append(
            '{bold}{template_name: <{template_name_length}} {template_id: <{template_id_length}}{end_bold}'.format(
                template_name_length=template_name_length,
                template_id_length=template_id_length,
                template_disk_id_length=template_disk_id_length,
                template_disk_pool_length=template_disk_pool_length,
                template_disk_size_length=template_disk_size_length,
                template_disk_filesystem_length=template_disk_filesystem_length,
                template_disk_fsargs_length=template_disk_fsargs_length,
                template_disk_mountpoint_length=template_disk_mountpoint_length,
                bold='',
                end_bold='',
                template_name=str(template['name']),
                template_id=str(template['id'])
            )
        )
        for disk in sorted(template['disks'], key=lambda i: i.get('disk_id', None)):
            template_list_output.append(
                '{bold}{template_name: <{template_name_length}} {template_id: <{template_id_length}} \
{template_disk_id: <{template_disk_id_length}} \
{template_disk_pool: <{template_disk_pool_length}} \
{template_disk_size: <{template_disk_size_length}} \
{template_disk_filesystem: <{template_disk_filesystem_length}} \
{template_disk_fsargs: <{template_disk_fsargs_length}} \
{template_disk_mountpoint: <{template_disk_mountpoint_length}}{end_bold}'.format(
                    template_name_length=template_name_length,
                    template_id_length=template_id_length,
                    template_disk_id_length=template_disk_id_length,
                    template_disk_pool_length=template_disk_pool_length,
                    template_disk_size_length=template_disk_size_length,
                    template_disk_filesystem_length=template_disk_filesystem_length,
                    template_disk_fsargs_length=template_disk_fsargs_length,
                    template_disk_mountpoint_length=template_disk_mountpoint_length,
                    bold='',
                    end_bold='',
                    template_name='',
                    template_id='',
                    template_disk_id=str(disk['disk_id']),
                    template_disk_pool=str(disk['pool']),
                    template_disk_size=str(disk['disk_size_gb']),
                    template_disk_filesystem=str(disk['filesystem']),
                    template_disk_fsargs=str(disk['filesystem_args']),
                    template_disk_mountpoint=str(disk['mountpoint'])
                )
            )

    click.echo('\n'.join([template_list_output_header] + template_list_output))

    return True, ''

def format_list_userdata(userdata, lines=None):
    if isinstance(userdata, dict):
        userdata = [ userdata ]

    data_list_output = []

    # Determine optimal column widths
    data_name_length = 5
    data_id_length = 4
    data_userdata_length = 8

    for data in userdata:
        # data_name column
        _data_name_length = len(str(data['name'])) + 1
        if _data_name_length > data_name_length:
            data_name_length = _data_name_length
        # data_id column
        _data_id_length = len(str(data['id'])) + 1
        if _data_id_length > data_id_length:
            data_id_length = _data_id_length

    # Format the string (header)
    data_list_output_header = '{bold}{data_name: <{data_name_length}} {data_id: <{data_id_length}} \
{data_userdata}{end_bold}'.format(
            data_name_length=data_name_length,
            data_id_length=data_id_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            data_name='Name',
            data_id='ID',
            data_userdata='Document'
        )

    # Format the string (elements)
    for data in sorted(userdata, key=lambda i: i.get('name', None)):
        line_count = 0
        for line in data['userdata'].split('\n'):
            if line_count < 1:
                data_name = data['name']
                data_id = data['id']
            else:
                data_name = ''
                data_id = ''
            line_count += 1

            if lines and line_count > lines:
                data_list_output.append(
                    '{bold}{data_name: <{data_name_length}} {data_id: <{data_id_length}} \
{data_script}{end_bold}'.format(
                        data_name_length=data_name_length,
                        data_id_length=data_id_length,
                        bold='',
                        end_bold='',
                        data_name=data_name,
                        data_id=data_id,
                        data_script='[...]'
                    )
                )
                break

            data_list_output.append(
                '{bold}{data_name: <{data_name_length}} {data_id: <{data_id_length}} \
{data_userdata}{end_bold}'.format(
                    data_name_length=data_name_length,
                    data_id_length=data_id_length,
                    bold='',
                    end_bold='',
                    data_name=data_name,
                    data_id=data_id,
                    data_userdata=str(line)
                )
            )

    click.echo('\n'.join([data_list_output_header] + data_list_output))

    return True, ''

def format_list_script(script, lines=None):
    if isinstance(script, dict):
        script = [ script ]

    data_list_output = []

    # Determine optimal column widths
    data_name_length = 5
    data_id_length = 4
    data_script_length = 8

    for data in script:
        # data_name column
        _data_name_length = len(str(data['name'])) + 1
        if _data_name_length > data_name_length:
            data_name_length = _data_name_length
        # data_id column
        _data_id_length = len(str(data['id'])) + 1
        if _data_id_length > data_id_length:
            data_id_length = _data_id_length

    # Format the string (header)
    data_list_output_header = '{bold}{data_name: <{data_name_length}} {data_id: <{data_id_length}} \
{data_script}{end_bold}'.format(
            data_name_length=data_name_length,
            data_id_length=data_id_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            data_name='Name',
            data_id='ID',
            data_script='Script'
        )

    # Format the string (elements)
    for data in sorted(script, key=lambda i: i.get('name', None)):
        line_count = 0
        for line in data['script'].split('\n'):
            if line_count < 1:
                data_name = data['name']
                data_id = data['id']
            else:
                data_name = ''
                data_id = ''
            line_count += 1

            if lines and line_count > lines:
                data_list_output.append(
                    '{bold}{data_name: <{data_name_length}} {data_id: <{data_id_length}} \
{data_script}{end_bold}'.format(
                        data_name_length=data_name_length,
                        data_id_length=data_id_length,
                        bold='',
                        end_bold='',
                        data_name=data_name,
                        data_id=data_id,
                        data_script='[...]'
                    )
                )
                break

            data_list_output.append(
                '{bold}{data_name: <{data_name_length}} {data_id: <{data_id_length}} \
{data_script}{end_bold}'.format(
                    data_name_length=data_name_length,
                    data_id_length=data_id_length,
                    bold='',
                    end_bold='',
                    data_name=data_name,
                    data_id=data_id,
                    data_script=str(line)
                )
            )

    click.echo('\n'.join([data_list_output_header] + data_list_output))

    return True, ''

