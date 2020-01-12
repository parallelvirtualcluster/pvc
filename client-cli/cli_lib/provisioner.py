#!/usr/bin/env python3

# provisioner.py - PVC CLI client function library, Provisioner functions
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

import time
import re
import subprocess
import ast

import cli_lib.ansiprint as ansiprint
from cli_lib.common import call_api

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
    response = call_api(config, 'get', '/provisioner/template/{template_type}/{template}'.format(template_type=template_type, template=template))

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
        response = call_api(config, 'get', '/provisioner/template/{template_type}'.format(template_type=template_type), params=params)
    else:
        response = call_api(config, 'get', '/provisioner/template', params=params)

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
    response = call_api(config, 'post', '/provisioner/template/{template_type}'.format(template_type=template_type), params=params)

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
    response = call_api(config, 'delete', '/provisioner/template/{template_type}/{name}'.format(template_type=template_type, name=name))

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
    response = call_api(config, 'post', '/provisioner/template/{template_type}/{name}/{element_type}/{element_id}'.format(template_type=template_type, name=name, element_type=element_type, element_id=element_id), params=params)

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
    response = call_api(config, 'delete', '/provisioner/template/{template_type}/{name}/{element_type}/{element_id}'.format(template_type=template_type, name=name, element_type=element_type, element_id=element_id))

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
    response = call_api(config, 'get', '/provisioner/userdata/{userdata}'.format(userdata=userdata))

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

    response = call_api(config, 'get', '/provisioner/userdata', params=params)

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
    name = params.get('name')
    userdata_data = params.get('data')

    params = {
        'name': name
    }
    data = {
        'data': userdata_data
    }
    response = call_api(config, 'post', '/provisioner/userdata', params=params, data=data)

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
    userdata_data = params.get('data')

    params = {
        'name': name
    }
    data = {
        'data': userdata_data
    }
    response = call_api(config, 'put', '/provisioner/userdata/{name}'.format(name=name), params=params, data=data)

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
    response = call_api(config, 'delete', '/provisioner/userdata/{name}'.format(name=name))

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
    response = call_api(config, 'get', '/provisioner/script/{script}'.format(script=script))

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

    response = call_api(config, 'get', '/provisioner/script', params=params)

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
    name = params.get('name')
    script_data = params.get('data')

    params = {
        'name': name
    }
    data = {
        'data': script_data
    }
    response = call_api(config, 'post', '/provisioner/script', params=params, data=data)

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
    script_data = params.get('data')

    params = {
        'name': name
    }
    data = {
        'data': script_data
    }
    response = call_api(config, 'put', '/provisioner/script/{name}'.format(name=name), params=params, data=data)

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
    response = call_api(config, 'delete', '/provisioner/script/{name}'.format(name=name))

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
    response = call_api(config, 'get', '/provisioner/profile/{profile}'.format(profile=profile))

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

    response = call_api(config, 'get', '/provisioner/profile', params=params)

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
    response = call_api(config, 'post', '/provisioner/profile', params=params)

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
    response = call_api(config, 'put', '/provisioner/profile/{name}'.format(name=name), params=params)

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
    response = call_api(config, 'delete', '/provisioner/profile/{name}'.format(name=name))

    if response.status_code == 200:
        retvalue = True
    else:
        retvalue = False
        
    return retvalue, response.json()['message']

def vm_create(config, name, profile, wait_flag, define_flag, start_flag):
    """
    Create a new VM named {name} with profile {profile}

    API endpoint: POST /api/v1/provisioner/create
    API_arguments: name={name}, profile={profile}
    API schema: {message}
    """
    params = {
        'name': name,
        'profile': profile,
        'start_vm': start_flag,
        'define_vm': define_flag
    }
    response = call_api(config, 'post', '/provisioner/create', params=params)

    if response.status_code == 202:
        retvalue = True
        if not wait_flag:
            retdata = 'Task ID: {}'.format(response.json()['task_id'])
        else:
            # Just return the task_id raw, instead of formatting it
            retdata = response.json()['task_id']
    else:
        retvalue = False
        retdata = response.json()['message']
        
    return retvalue, retdata

def task_status(config, task_id=None, is_watching=False):
    """
    Get information about provisioner job {task_id} or all tasks if None

    API endpoint: GET /api/v1/provisioner/status
    API arguments:
    API schema: {json_data_object}
    """
    if task_id is not None:
        response = call_api(config, 'get', '/provisioner/status/{task_id}'.format(task_id=task_id))
    else:
        response = call_api(config, 'get', '/provisioner/status')

    if task_id is not None:
        if response.status_code == 200:
            retvalue = True
            respjson = response.json()

            if is_watching:
                # Just return the raw JSON to the watching process instead of formatting it
                return respjson

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
    else:
        retvalue = True
        respjson = response.json()
        retdata = format_list_task(respjson)

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

def format_list_task(task_data_raw):
    # Format the Celery data into a more useful data structure
    task_data = list()
    for task_type in ['active', 'reserved', 'scheduled']:
        type_data = task_data_raw[task_type]
        if not type_data:
            type_data = dict()
        for task_host in type_data:
            for task_job in task_data_raw[task_type][task_host]:
                task = dict()
                if task_type == 'reserved':
                    task['type'] = 'pending'
                else:
                    task['type'] = task_type
                task['worker'] = task_host
                task['id'] = task_job.get('id')
                task_args = ast.literal_eval(task_job.get('args'))
                task['vm_name'] = task_args[0]
                task['vm_profile'] = task_args[1]
                task_kwargs = ast.literal_eval(task_job.get('kwargs'))
                task['vm_define'] = str(bool(task_kwargs['define_vm']))
                task['vm_start'] = str(bool(task_kwargs['start_vm']))
                task_data.append(task)

    task_list_output = []

    # Determine optimal column widths
    task_id_length = 7
    task_type_length = 7
    task_vm_name_length = 5
    task_vm_profile_length = 8
    task_vm_define_length = 8
    task_vm_start_length = 7
    task_worker_length = 8

    for task in task_data:
        # task_id column
        _task_id_length = len(str(task['id'])) + 1
        if _task_id_length > task_id_length:
            task_id_length = _task_id_length
        # task_type column
        _task_type_length = len(str(task['type'])) + 1
        if _task_type_length > task_type_length:
            task_type_length = _task_type_length
        # task_vm_name column
        _task_vm_name_length = len(str(task['vm_name'])) + 1
        if _task_vm_name_length > task_vm_name_length:
            task_vm_name_length = _task_vm_name_length
        # task_vm_profile column
        _task_vm_profile_length = len(str(task['vm_profile'])) + 1
        if _task_vm_profile_length > task_vm_profile_length:
            task_vm_profile_length = _task_vm_profile_length
        # task_vm_define column
        _task_vm_define_length = len(str(task['vm_define'])) + 1
        if _task_vm_define_length > task_vm_define_length:
            task_vm_define_length = _task_vm_define_length
        # task_vm_start column
        _task_vm_start_length = len(str(task['vm_start'])) + 1
        if _task_vm_start_length > task_vm_start_length:
            task_vm_start_length = _task_vm_start_length
        # task_worker column
        _task_worker_length = len(str(task['worker'])) + 1
        if _task_worker_length > task_worker_length:
            task_worker_length = _task_worker_length

    # Format the string (header)
    task_list_output_header = '{bold}{task_id: <{task_id_length}} {task_type: <{task_type_length}} \
{task_worker: <{task_worker_length}} \
VM: {task_vm_name: <{task_vm_name_length}} \
{task_vm_profile: <{task_vm_profile_length}} \
{task_vm_define: <{task_vm_define_length}} \
{task_vm_start: <{task_vm_start_length}}{end_bold}'.format(
            task_id_length=task_id_length,
            task_type_length=task_type_length,
            task_worker_length=task_worker_length,
            task_vm_name_length=task_vm_name_length,
            task_vm_profile_length=task_vm_profile_length,
            task_vm_define_length=task_vm_define_length,
            task_vm_start_length=task_vm_start_length,
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            task_id='Job ID',
            task_type='Status',
            task_worker='Worker',
            task_vm_name='Name',
            task_vm_profile='Profile',
            task_vm_define='Define?',
            task_vm_start='Start?'
        )

    # Format the string (elements)
    for task in sorted(task_data, key=lambda i: i.get('type', None)):
        task_list_output.append(
            '{bold}{task_id: <{task_id_length}} {task_type: <{task_type_length}} \
{task_worker: <{task_worker_length}} \
    {task_vm_name: <{task_vm_name_length}} \
{task_vm_profile: <{task_vm_profile_length}} \
{task_vm_define: <{task_vm_define_length}} \
{task_vm_start: <{task_vm_start_length}}{end_bold}'.format(
                task_id_length=task_id_length,
                task_type_length=task_type_length,
                task_worker_length=task_worker_length,
                task_vm_name_length=task_vm_name_length,
                task_vm_profile_length=task_vm_profile_length,
                task_vm_define_length=task_vm_define_length,
                task_vm_start_length=task_vm_start_length,
                bold='',
                end_bold='',
                task_id=task['id'],
                task_type=task['type'],
                task_worker=task['worker'],
                task_vm_name=task['vm_name'],
                task_vm_profile=task['vm_profile'],
                task_vm_define=task['vm_define'],
                task_vm_start=task['vm_start']
            )
        )

    return '\n'.join([task_list_output_header] + task_list_output)
