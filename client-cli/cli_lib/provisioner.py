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
import requests

import cli_lib.ansiprint as ansiprint

def debug_output(config, request_uri, response):
    if config['debug']:
        import click.echo
        click.echo('API endpoint: POST {}'.format(request_uri), err=True)
        click.echo('Response code: {}'.format(response.status_code), err=True)
        click.echo('Response headers: {}'.format(response.headers), err=True)

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

    debug_output(config, request_uri, response)

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

    debug_output(config, request_uri, response)

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

    debug_output(config, request_uri, response)

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

    debug_output(config, request_uri, response)

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

    debug_output(config, request_uri, response)

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

    debug_output(config, request_uri, response)

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

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        return True, response.json()[0]
    else:
        return False, response.json()['message']

def userdata_list(config, limit):
    """
    Get list information about userdatas (limited by {limit})

    API endpoint: GET /api/v1/provisioner/userdata
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

    debug_output(config, request_uri, response)

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

    debug_output(config, request_uri, response)

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

    debug_output(config, request_uri, response)

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

    debug_output(config, request_uri, response)

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

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        return True, response.json()[0]
    else:
        return False, response.json()['message']

def script_list(config, limit):
    """
    Get list information about scripts (limited by {limit})

    API endpoint: GET /api/v1/provisioner/script
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

    debug_output(config, request_uri, response)

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

    debug_output(config, request_uri, response)

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

    debug_output(config, request_uri, response)

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

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retvalue = True
    else:
        retvalue = False
        
    return retvalue, response.json()['message']

def profile_info(config, profile):
    """
    Get information about profile

    API endpoint: GET /api/v1/provisioner/profile/{profile}
    API arguments:
    API schema: {json_data_object}
    """
    request_uri = get_request_uri(config, '/provisioner/profile/{profile}'.format(profile=profile))
    response = requests.get(
        request_uri
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        return True, response.json()[0]
    else:
        return False, response.json()['message']

def profile_list(config, limit):
    """
    Get list information about profiles (limited by {limit})

    API endpoint: GET /api/v1/provisioner/profile/{profile_type}
    API arguments: limit={limit}
    API schema: [{json_data_object},{json_data_object},etc.]
    """
    params = dict()
    if limit:
        params['limit'] = limit

    request_uri = get_request_uri(config, '/provisioner/profile')
    response = requests.get(
        request_uri,
        params=params
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        return True, response.json()
    else:
        return False, response.json()['message']

def profile_add(config, params):
    """
    Add a new profile with {params}

    API endpoint: POST /api/v1/provisioner/profile
    API_arguments: args
    API schema: {message}
    """
    request_uri = get_request_uri(config, '/provisioner/profile')
    response = requests.post(
        request_uri,
        params=params
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retvalue = True
    else:
        retvalue = False
        
    return retvalue, response.json()['message']

def profile_modify(config, name, params):
    """
    Modify profile {name} with {params}

    API endpoint: PUT /api/v1/provisioner/profile/{name}
    API_arguments: args
    API schema: {message}
    """
    request_uri = get_request_uri(config, '/provisioner/profile/{name}'.format(name=name))
    response = requests.put(
        request_uri,
        params=params
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retvalue = True
    else:
        retvalue = False
        
    return retvalue, response.json()['message']

def profile_remove(config, name):
    """
    Remove profile {name}

    API endpoint: DELETE /api/v1/provisioner/profile/{name}
    API_arguments:
    API schema: {message}
    """
    request_uri = get_request_uri(config, '/provisioner/profile/{name}'.format(name=name))
    response = requests.delete(
        request_uri
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retvalue = True
    else:
        retvalue = False
        
    return retvalue, response.json()['message']

def vm_create(config, name, profile):
    """
    Create a new VM named {name} with profile {profile}

    API endpoint: POST /api/v1/provisioner/create
    API_arguments: name={name}, profile={profile}
    API schema: {message}
    """
    request_uri = get_request_uri(config, '/provisioner/create')
    response = requests.post(
        request_uri,
        params={
            'name': name,
            'profile': profile
        }
    )

    debug_output(config, request_uri, response)

    if response.status_code == 202:
        retvalue = True
        retdata = 'Task ID: {}'.format(response.json()['task_id'])
    else:
        retvalue = False
        retdata = response.json()['message']
        
    return retvalue, retdata

def task_status(config, task_id):
    """
    Get information about provisioner job {task_id}

    API endpoint: GET /api/v1/provisioner/status
    API arguments:
    API schema: {json_data_object}
    """
    request_uri = get_request_uri(config, '/provisioner/status/{task_id}'.format(task_id=task_id))
    response = requests.get(
        request_uri
    )

    debug_output(config, request_uri, response)

    if response.status_code == 200:
        retvalue = True
        respjson = response.json()
        job_state = respjson['state']
        if job_state == 'RUNNING':
            retdata = 'Job state: RUNNING\nStage: {}/{}\nStatus: {}'.format(
                respjson['current'],
                respjson['total'],
                respjson['status']
            )
        elif job_state == 'FAILED':
            retdata = 'Job state: FAILED\nStatus: {}'.format(
                respjson['status']
            )
        elif job_state == 'COMPLETED':
            retdata = 'Job state: COMPLETED\nStatus: {}'.format(
                respjson['status']
            )
        else:
            retdata = 'Job state: {}\nStatus: {}'.format(
                respjson['state'],
                respjson['status']
            )
    else:
        retvalue = False
        retdata = response.json()['message']

    return retvalue, retdata

#
# Format functions
#
def format_list_template(template_data, template_type=None):
    """
    Format the returned template template

    template_type can be used to only display part of the full list, allowing function
    reuse with more limited output options.
    """
    template_types = [ 'system', 'network', 'storage' ]
    normalized_template_data = dict()
    ainformation = list()

    if template_type in template_types:
        template_types = [ template_type ]
        template_data_type = '{}_templates'.format(template_type)
        normalized_template_data[template_data_type] = template_data
    else:
        normalized_template_data = template_data

    if 'system' in template_types:
        ainformation.append('System templates:')
        ainformation.append('')
        ainformation.append(format_list_template_system(normalized_template_data['system_templates']))
        if len(template_types) > 1:
            ainformation.append('')

    if 'network' in template_types:
        ainformation.append('Network templates:')
        ainformation.append('')
        ainformation.append(format_list_template_network(normalized_template_data['network_templates']))
        if len(template_types) > 1:
            ainformation.append('')

    if 'storage' in template_types:
        ainformation.append('Storage templates:')
        ainformation.append('')
        ainformation.append(format_list_template_storage(normalized_template_data['storage_templates']))

    return '\n'.join(ainformation)

def format_list_template_system(template_data):
    if isinstance(template_data, dict):
        template_data = [ template_data ]

    template_list_output = []

    # Determine optimal column widths
    template_name_length = 5
    template_id_length = 3
    template_vcpu_length = 6
    template_vram_length = 10
    template_serial_length = 7
    template_vnc_length = 4
    template_vnc_bind_length = 10
    template_node_limit_length = 9
    template_node_selector_length = 11
    template_node_autostart_length = 11

    for template in template_data:
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
Metadata: {template_node_limit: <{template_node_limit_length}} \
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

    for template in sorted(template_data, key=lambda i: i.get('name', None)):
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

    return '\n'.join([template_list_output_header] + template_list_output)

    return True, ''

def format_list_template_network(template_template):
    if isinstance(template_template, dict):
        template_template = [ template_template ]

    template_list_output = []

    # Determine optimal column widths
    template_name_length = 5
    template_id_length = 3
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

    return '\n'.join([template_list_output_header] + template_list_output)

def format_list_template_storage(template_template):
    if isinstance(template_template, dict):
        template_template = [ template_template ]

    template_list_output = []

    # Determine optimal column widths
    template_name_length = 5
    template_id_length = 3
    template_disk_id_length = 8
    template_disk_pool_length = 8
    template_disk_source_length = 14
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
            # template_disk_source column
            _template_disk_source_length = len(str(disk['source_volume'])) + 1
            if _template_disk_source_length > template_disk_source_length:
                template_disk_source_length = _template_disk_source_length
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
{template_disk_source: <{template_disk_source_length}} \
{template_disk_size: <{template_disk_size_length}} \
{template_disk_filesystem: <{template_disk_filesystem_length}} \
{template_disk_fsargs: <{template_disk_fsargs_length}} \
{template_disk_mountpoint: <{template_disk_mountpoint_length}}{end_bold}'.format(
            template_name_length=template_name_length,
            template_id_length=template_id_length,
            template_disk_id_length=template_disk_id_length,
            template_disk_pool_length=template_disk_pool_length,
            template_disk_source_length=template_disk_source_length,
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
            template_disk_source='Source Volume',
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
{template_disk_source: <{template_disk_source_length}} \
{template_disk_size: <{template_disk_size_length}} \
{template_disk_filesystem: <{template_disk_filesystem_length}} \
{template_disk_fsargs: <{template_disk_fsargs_length}} \
{template_disk_mountpoint: <{template_disk_mountpoint_length}}{end_bold}'.format(
                    template_name_length=template_name_length,
                    template_id_length=template_id_length,
                    template_disk_id_length=template_disk_id_length,
                    template_disk_pool_length=template_disk_pool_length,
                    template_disk_source_length=template_disk_source_length,
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
                    template_disk_source=str(disk['source_volume']),
                    template_disk_size=str(disk['disk_size_gb']),
                    template_disk_filesystem=str(disk['filesystem']),
                    template_disk_fsargs=str(disk['filesystem_args']),
                    template_disk_mountpoint=str(disk['mountpoint'])
                )
            )

    return '\n'.join([template_list_output_header] + template_list_output)

def format_list_userdata(userdata_data, lines=None):
    if isinstance(userdata_data, dict):
        userdata_data = [ userdata_data ]

    userdata_list_output = []

    # Determine optimal column widths
    userdata_name_length = 5
    userdata_id_length = 3
    userdata_useruserdata_length = 8

    for userdata in userdata_data:
        # userdata_name column
        _userdata_name_length = len(str(userdata['name'])) + 1
        if _userdata_name_length > userdata_name_length:
            userdata_name_length = _userdata_name_length
        # userdata_id column
        _userdata_id_length = len(str(userdata['id'])) + 1
        if _userdata_id_length > userdata_id_length:
            userdata_id_length = _userdata_id_length

    # Format the string (header)
    userdata_list_output_header = '{bold}{userdata_name: <{userdata_name_length}} {userdata_id: <{userdata_id_length}} \
{userdata_data}{end_bold}'.format(
            userdata_name_length=userdata_name_length,
            userdata_id_length=userdata_id_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            userdata_name='Name',
            userdata_id='ID',
            userdata_data='Document'
        )

    # Format the string (elements)
    for data in sorted(userdata_data, key=lambda i: i.get('name', None)):
        line_count = 0
        for line in data['userdata'].split('\n'):
            if line_count < 1:
                userdata_name = data['name']
                userdata_id = data['id']
            else:
                userdata_name = ''
                userdata_id = ''
            line_count += 1

            if lines and line_count > lines:
                userdata_list_output.append(
                    '{bold}{userdata_name: <{userdata_name_length}} {userdata_id: <{userdata_id_length}} \
{userdata_data}{end_bold}'.format(
                        userdata_name_length=userdata_name_length,
                        userdata_id_length=userdata_id_length,
                        bold='',
                        end_bold='',
                        userdata_name=userdata_name,
                        userdata_id=userdata_id,
                        userdata_data='[...]'
                    )
                )
                break

            userdata_list_output.append(
                '{bold}{userdata_name: <{userdata_name_length}} {userdata_id: <{userdata_id_length}} \
{userdata_data}{end_bold}'.format(
                    userdata_name_length=userdata_name_length,
                    userdata_id_length=userdata_id_length,
                    bold='',
                    end_bold='',
                    userdata_name=userdata_name,
                    userdata_id=userdata_id,
                    userdata_data=str(line)
                )
            )

    return '\n'.join([userdata_list_output_header] + userdata_list_output)

def format_list_script(script_data, lines=None):
    if isinstance(script_data, dict):
        script_data = [ script_data ]

    script_list_output = []

    # Determine optimal column widths
    script_name_length = 5
    script_id_length = 3
    script_script_length = 8

    for script in script_data:
        # script_name column
        _script_name_length = len(str(script['name'])) + 1
        if _script_name_length > script_name_length:
            script_name_length = _script_name_length
        # script_id column
        _script_id_length = len(str(script['id'])) + 1
        if _script_id_length > script_id_length:
            script_id_length = _script_id_length

    # Format the string (header)
    script_list_output_header = '{bold}{script_name: <{script_name_length}} {script_id: <{script_id_length}} \
{script_data}{end_bold}'.format(
            script_name_length=script_name_length,
            script_id_length=script_id_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            script_name='Name',
            script_id='ID',
            script_data='Script'
        )

    # Format the string (elements)
    for script in sorted(script_data, key=lambda i: i.get('name', None)):
        line_count = 0
        for line in script['script'].split('\n'):
            if line_count < 1:
                script_name = script['name']
                script_id = script['id']
            else:
                script_name = ''
                script_id = ''
            line_count += 1

            if lines and line_count > lines:
                script_list_output.append(
                    '{bold}{script_name: <{script_name_length}} {script_id: <{script_id_length}} \
{script_data}{end_bold}'.format(
                        script_name_length=script_name_length,
                        script_id_length=script_id_length,
                        bold='',
                        end_bold='',
                        script_name=script_name,
                        script_id=script_id,
                        script_data='[...]'
                    )
                )
                break

            script_list_output.append(
                '{bold}{script_name: <{script_name_length}} {script_id: <{script_id_length}} \
{script_data}{end_bold}'.format(
                    script_name_length=script_name_length,
                    script_id_length=script_id_length,
                    bold='',
                    end_bold='',
                    script_name=script_name,
                    script_id=script_id,
                    script_data=str(line)
                )
            )

    return '\n'.join([script_list_output_header] + script_list_output)

def format_list_profile(profile_data):
    if isinstance(profile_data, dict):
        profile_data = [ profile_data ]

    profile_list_output = []

    # Determine optimal column widths
    profile_name_length = 5
    profile_id_length = 3

    profile_system_template_length = 7
    profile_network_template_length = 8
    profile_storage_template_length = 8
    profile_userdata_length = 9
    profile_script_length = 7

    for profile in profile_data:
        # profile_name column
        _profile_name_length = len(str(profile['name'])) + 1
        if _profile_name_length > profile_name_length:
            profile_name_length = _profile_name_length
        # profile_id column
        _profile_id_length = len(str(profile['id'])) + 1
        if _profile_id_length > profile_id_length:
            profile_id_length = _profile_id_length
        # profile_system_template column
        _profile_system_template_length = len(str(profile['system_template'])) + 1
        if _profile_system_template_length > profile_system_template_length:
            profile_system_template_length = _profile_system_template_length
        # profile_network_template column
        _profile_network_template_length = len(str(profile['network_template'])) + 1
        if _profile_network_template_length > profile_network_template_length:
            profile_network_template_length = _profile_network_template_length
        # profile_storage_template column
        _profile_storage_template_length = len(str(profile['storage_template'])) + 1
        if _profile_storage_template_length > profile_storage_template_length:
            profile_storage_template_length = _profile_storage_template_length
        # profile_userdata column
        _profile_userdata_length = len(str(profile['userdata'])) + 1
        if _profile_userdata_length > profile_userdata_length:
            profile_userdata_length = _profile_userdata_length
        # profile_script column
        _profile_script_length = len(str(profile['script'])) + 1
        if _profile_script_length > profile_script_length:
            profile_script_length = _profile_script_length

    # Format the string (header)
    profile_list_output_header = '{bold}{profile_name: <{profile_name_length}} {profile_id: <{profile_id_length}} \
Templates: {profile_system_template: <{profile_system_template_length}} \
{profile_network_template: <{profile_network_template_length}} \
{profile_storage_template: <{profile_storage_template_length}} \
Data: {profile_userdata: <{profile_userdata_length}} \
{profile_script: <{profile_script_length}} \
{profile_arguments}{end_bold}'.format(
            profile_name_length=profile_name_length,
            profile_id_length=profile_id_length,
            profile_system_template_length=profile_system_template_length,
            profile_network_template_length=profile_network_template_length,
            profile_storage_template_length=profile_storage_template_length,
            profile_userdata_length=profile_userdata_length,
            profile_script_length=profile_script_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            profile_name='Name',
            profile_id='ID',
            profile_system_template='System',
            profile_network_template='Network',
            profile_storage_template='Storage',
            profile_userdata='Userdata',
            profile_script='Script',
            profile_arguments='Script Arguments'
        )

    # Format the string (elements)
    for profile in sorted(profile_data, key=lambda i: i.get('name', None)):
        profile_list_output.append(
            '{bold}{profile_name: <{profile_name_length}} {profile_id: <{profile_id_length}} \
           {profile_system_template: <{profile_system_template_length}} \
{profile_network_template: <{profile_network_template_length}} \
{profile_storage_template: <{profile_storage_template_length}} \
      {profile_userdata: <{profile_userdata_length}} \
{profile_script: <{profile_script_length}} \
{profile_arguments}{end_bold}'.format(
                profile_name_length=profile_name_length,
                profile_id_length=profile_id_length,
                profile_system_template_length=profile_system_template_length,
                profile_network_template_length=profile_network_template_length,
                profile_storage_template_length=profile_storage_template_length,
                profile_userdata_length=profile_userdata_length,
                profile_script_length=profile_script_length,
                bold='',
                end_bold='',
                profile_name=profile['name'],
                profile_id=profile['id'],
                profile_system_template=profile['system_template'],
                profile_network_template=profile['network_template'],
                profile_storage_template=profile['storage_template'],
                profile_userdata=profile['userdata'],
                profile_script=profile['script'],
                profile_arguments=', '.join(profile['arguments'])
            )
        )

    return '\n'.join([profile_list_output_header] + profile_list_output)
