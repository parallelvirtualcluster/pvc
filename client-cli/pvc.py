#!/usr/bin/env python3

# pvc.py - PVC client command-line interface
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

import socket
import click
import tempfile
import os
import stat
import subprocess
import difflib
import re
import time
import colorama
import yaml
import json
import lxml.etree as etree

from distutils.util import strtobool

from functools import wraps

import cli_lib.ansiprint as ansiprint
import cli_lib.cluster as pvc_cluster
import cli_lib.node as pvc_node
import cli_lib.vm as pvc_vm
import cli_lib.network as pvc_network
import cli_lib.ceph as pvc_ceph
import cli_lib.provisioner as pvc_provisioner

myhostname = socket.gethostname().split('.')[0]
zk_host = ''

default_store_data = {
    'cfgfile': '/etc/pvc/pvcapid.yaml' # pvc/api/listen_address, pvc/api/listen_port
}

#
# Data store handling functions
#
def read_from_yaml(cfgfile):
    with open(cfgfile, 'r') as fh:
        api_config = yaml.load(fh, Loader=yaml.BaseLoader)
    host = api_config['pvc']['api']['listen_address']
    port = api_config['pvc']['api']['listen_port']
    if strtobool(api_config['pvc']['api']['ssl']['enabled']):
        scheme = 'https'
    else:
        scheme = 'http'
    if strtobool(api_config['pvc']['api']['authentication']['enabled']):
        # Always use the first token
        api_key = api_config['pvc']['api']['authentication']['tokens'][0]['token']
    else:
        api_key = 'N/A'
    return host, port, scheme, api_key

def get_config(store_data, cluster=None):
    # This is generally static
    prefix = '/api/v1'

    cluster_details = store_data.get(cluster)

    if not cluster_details:
        cluster_details = default_store_data
        cluster = 'local'

    if cluster_details.get('cfgfile', None):
        # This is a reference to an API configuration; grab the details from its listen address
        cfgfile = cluster_details.get('cfgfile')
        if os.path.isfile(cfgfile):
            host, port, scheme, api_key = read_from_yaml(cfgfile)
        else:
            return { 'badcfg': True }
        # Handle an all-wildcard address
        if host == '0.0.0.0':
            host = '127.0.0.1'
    else:
        # This is a static configuration, get the raw details
        host = cluster_details['host']
        port = cluster_details['port']
        scheme = cluster_details['scheme']
        api_key = cluster_details['api_key']

    config = dict()
    config['debug'] = False
    config['cluster'] = cluster
    config['api_host'] = '{}:{}'.format(host, port)
    config['api_scheme'] = scheme
    config['api_key'] = api_key
    config['api_prefix'] = prefix
    if cluster == 'local':
        config['verify_ssl'] = False
    else:
        config['verify_ssl'] = bool(strtobool(os.environ.get('PVC_CLIENT_VERIFY_SSL', 'True')))

    return config

def get_store(store_path):
    store_file = '{}/pvc-cli.json'.format(store_path)
    with open(store_file, 'r') as fh:
       store_data = json.loads(fh.read())
    return store_data

def update_store(store_path, store_data):
    store_file = '{}/pvc-cli.json'.format(store_path)
    if not os.path.exists(store_file):
        with open(store_file, 'w') as fh:
            fh.write(json.dumps(store_data, sort_keys=True, indent=4))
        # Ensure file has sensible permissions due to API key storage, but only when created!
        os.chmod(store_file, int(os.environ.get('PVC_CLIENT_DB_PERMS', '600'), 8))
    else:
        with open(store_file, 'w') as fh:
            fh.write(json.dumps(store_data, sort_keys=True, indent=4))

pvc_client_dir = os.environ.get('PVC_CLIENT_DIR', None)
home_dir = os.environ.get('HOME', None)
if pvc_client_dir:
    store_path = '{}'.format(pvc_client_dir)
elif home_dir:
    store_path = '{}/.config/pvc'.format(home_dir)
else:
    print('WARNING: No client or home config dir found, using /tmp instead')
    store_path = '/tmp/pvc'

if not os.path.isdir(store_path):
    os.makedirs(store_path)
if not os.path.isfile(store_path + '/pvc-cli.json'):
    update_store(store_path, {"local": default_store_data})

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'], max_content_width=120)

def cleanup(retcode, retmsg):
    if retcode == True:
        if retmsg != '':
            click.echo(retmsg)
        exit(0)
    else:
        if retmsg != '':
            click.echo(retmsg)
        exit(1)

###############################################################################
# pvc cluster
###############################################################################
@click.group(name='cluster', short_help='Manage PVC cluster connections.', context_settings=CONTEXT_SETTINGS)
def cli_cluster():
    """
    Manage the PVC clusters this CLI can connect to.
    """
    pass

###############################################################################
# pvc cluster add
###############################################################################
@click.command(name='add', short_help='Add a new cluster to the client.')
@click.option(
    '-a', '--address', 'address', required=True,
    help='The IP address or hostname of the cluster API client.'
)
@click.option(
    '-p', '--port', 'port', required=False, default=7370, show_default=True,
    help='The cluster API client port.'
)
@click.option(
    '-s/-S', '--ssl/--no-ssl', 'ssl', is_flag=True, default=False, show_default=True,
    help='Whether to use SSL or not.'
)
@click.option(
    '-k', '--api-key', 'api_key', required=False, default=None,
    help='An API key to authenticate against the cluster.'
)
@click.argument(
    'name'
)
def cluster_add(address, port, ssl, name, api_key):
    """
    Add a new PVC cluster NAME, via its API connection details, to the configuration of the local CLI client. Replaces any existing cluster with this name.
    """
    if ssl:
        scheme = 'https'
    else:
        scheme = 'http'

    # Get the existing data
    existing_config = get_store(store_path)
    # Append our new entry to the end
    existing_config[name] = {
        'host': address,
        'port': port,
        'scheme': scheme,
        'api_key': api_key
    }
    # Update the store
    update_store(store_path, existing_config)
    click.echo('Added new cluster "{}" at host "{}" to local database'.format(name, address))

###############################################################################
# pvc cluster remove
###############################################################################
@click.command(name='remove', short_help='Remove a cluster from the client.')
@click.argument(
    'name'
)
def cluster_remove(name):
    """
    Remove a PVC cluster from the configuration of the local CLI client.
    """
    # Get the existing data
    existing_config = get_store(store_path)
    # Remove the entry matching the name
    try:
        existing_config.pop(name)
    except KeyError:
        print('No cluster with name "{}" found'.format(name))
    # Update the store
    update_store(store_path, existing_config)
    click.echo('Removed cluster "{}" from local database'.format(name))

###############################################################################
# pvc cluster list
###############################################################################
@click.command(name='list', short_help='List all available clusters.')
def cluster_list():
    """
    List all the available PVC clusters configured in this CLI instance.
    """
    # Get the existing data
    clusters = get_store(store_path)
    # Find the lengths of each column
    name_length = 5
    address_length = 10
    port_length = 5
    scheme_length = 7
    api_key_length = 8

    for cluster in clusters:
        cluster_details = clusters[cluster]
        if cluster_details.get('cfgfile', None):
            # This is a reference to an API configuration; grab the details from its listen address
            cfgfile = cluster_details.get('cfgfile')
            if os.path.isfile(cfgfile):
                address, port, scheme, api_key = read_from_yaml(cfgfile)
            else:
                address, port, scheme, api_key = 'N/A', 'N/A', 'N/A', 'N/A'
        else:
            address = cluster_details.get('host', 'N/A')
            port = cluster_details.get('port', 'N/A')
            scheme = cluster_details.get('scheme', 'N/A')
            api_key = cluster_details.get('api_key', 'N/A')
            if not api_key:
                api_key = 'N/A'

        _name_length = len(cluster) + 1
        if _name_length > name_length:
            name_length = _name_length
        _address_length = len(address) + 1
        if _address_length > address_length:
            address_length = _address_length
        _port_length = len(str(port)) + 1
        if _port_length > port_length:
            port_length = _port_length
        _scheme_length = len(scheme) + 1
        if _scheme_length > scheme_length:
            scheme_length = _scheme_length
        _api_key_length = len(api_key) + 1
        if _api_key_length > api_key_length:
            api_key_length = _api_key_length

    # Display the data nicely
    click.echo("Available clusters:")
    click.echo()
    click.echo(
        '{bold}{name: <{name_length}} {address: <{address_length}} {port: <{port_length}} {scheme: <{scheme_length}} {api_key: <{api_key_length}}{end_bold}'.format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            name="Name",
            name_length=name_length,
            address="Address",
            address_length=address_length,
            port="Port",
            port_length=port_length,
            scheme="Scheme",
            scheme_length=scheme_length,
            api_key="API Key",
            api_key_length=api_key_length
        )
    )

    for cluster in clusters:
        cluster_details = clusters[cluster]
        if cluster_details.get('cfgfile', None):
            # This is a reference to an API configuration; grab the details from its listen address
            if os.path.isfile(cfgfile):
                address, port, scheme, api_key = read_from_yaml(cfgfile)
            else:
                address = 'N/A'
                port = 'N/A'
                scheme = 'N/A'
                api_key = 'N/A'
        else:
            address = cluster_details.get('host', 'N/A')
            port = cluster_details.get('port', 'N/A')
            scheme = cluster_details.get('scheme', 'N/A')
            api_key = cluster_details.get('api_key', 'N/A')
            if not api_key:
                api_key = 'N/A'

        click.echo(
            '{bold}{name: <{name_length}} {address: <{address_length}} {port: <{port_length}} {scheme: <{scheme_length}} {api_key: <{api_key_length}}{end_bold}'.format(
                bold='',
                end_bold='',
                name=cluster,
                name_length=name_length,
                address=address,
                address_length=address_length,
                port=port,
                port_length=port_length,
                scheme=scheme,
                scheme_length=scheme_length,
                api_key=api_key,
                api_key_length=api_key_length
            )
        )

# Validate that the cluster is set for a given command
def cluster_req(function):
    @wraps(function)
    def validate_cluster(*args, **kwargs):
        if config.get('badcfg', None):
            click.echo('No cluster specified and no local pvcapid.yaml configuration found. Use "pvc cluster" to add a cluster API to connect to.')
            exit(1)
        return function(*args, **kwargs)
    return validate_cluster


###############################################################################
# pvc node
###############################################################################
@click.group(name='node', short_help='Manage a PVC node.', context_settings=CONTEXT_SETTINGS)
def cli_node():
    """
    Manage the state of a node in the PVC cluster.
    """

###############################################################################
# pvc node secondary
###############################################################################
@click.command(name='secondary', short_help='Set a node in secondary node status.')
@click.argument(
    'node'
)
@click.option(
    '-w', '--wait', 'wait', is_flag=True, default=False,
    help='Wait for transition to complete before returning.'
)
@cluster_req
def node_secondary(node, wait):
    """
    Take NODE out of primary router mode.
    """

    task_retcode, task_retdata = pvc_provisioner.task_status(config, None)
    if len(task_retdata) > 0:
        click.echo("Note: There are currently {} active or queued provisioner jobs on the current primary node.".format(len(task_retdata)))
        click.echo("      These jobs will continue executing, but status will not be visible until the current")
        click.echo("      node returns to primary state.")
        click.echo()

    retcode, retmsg = pvc_node.node_coordinator_state(config, node, 'secondary')
    if not retcode:
        cleanup(retcode, retmsg)
    else:
        if wait:
            click.echo(retmsg)
            click.echo("Waiting for state transition... ", nl=False)
            # Every half-second, check if the API is reachable and the node is in secondary state
            while True:
                try:
                    _retcode, _retmsg = pvc_node.node_info(config, node)
                    if _retmsg['coordinator_state'] == 'secondary':
                        retmsg = "done."
                        break
                    else:
                        time.sleep(0.5)
                except Exception:
                    time.sleep(0.5)
        cleanup(retcode, retmsg)

###############################################################################
# pvc node primary
###############################################################################
@click.command(name='primary', short_help='Set a node in primary status.')
@click.argument(
    'node'
)
@click.option(
    '-w', '--wait', 'wait', is_flag=True, default=False,
    help='Wait for transition to complete before returning.'
)
@cluster_req
def node_primary(node, wait):
    """
    Put NODE into primary router mode.
    """

    task_retcode, task_retdata = pvc_provisioner.task_status(config, None)
    if len(task_retdata) > 0:
        click.echo("Note: There are currently {} active or queued provisioner jobs on the current primary node.".format(len(task_retdata)))
        click.echo("      These jobs will continue executing, but status will not be visible until the current")
        click.echo("      node returns to primary state.")
        click.echo()

    retcode, retmsg = pvc_node.node_coordinator_state(config, node, 'primary')
    if not retcode:
        cleanup(retcode, retmsg)
    else:
        if wait:
            click.echo(retmsg)
            click.echo("Waiting for state transition... ", nl=False)
            # Every half-second, check if the API is reachable and the node is in secondary state
            while True:
                try:
                    _retcode, _retmsg = pvc_node.node_info(config, node)
                    if _retmsg['coordinator_state'] == 'primary':
                        retmsg = "done."
                        break
                    else:
                        time.sleep(0.5)
                except Exception:
                    time.sleep(0.5)
        cleanup(retcode, retmsg)

###############################################################################
# pvc node flush
###############################################################################
@click.command(name='flush', short_help='Take a node out of service.')
@click.option(
    '-w', '--wait', 'wait', is_flag=True, default=False,
    help='Wait for migrations to complete before returning.'
)
@click.argument(
    'node', default=myhostname
)
@cluster_req
def node_flush(node, wait):
    """
    Take NODE out of active service and migrate away all VMs. If unspecified, defaults to this host.
    """

    retcode, retmsg = pvc_node.node_domain_state(config, node, 'flush', wait)
    cleanup(retcode, retmsg)

###############################################################################
# pvc node ready/unflush
###############################################################################
@click.command(name='ready', short_help='Restore node to service.')
@click.argument(
    'node', default=myhostname
)
@click.option(
    '-w', '--wait', 'wait', is_flag=True, default=False,
    help='Wait for migrations to complete before returning.'
)
@cluster_req
def node_ready(node, wait):
    """
    Restore NODE to active service and migrate back all VMs. If unspecified, defaults to this host.
    """

    retcode, retmsg = pvc_node.node_domain_state(config, node, 'ready', wait)
    cleanup(retcode, retmsg)

@click.command(name='unflush', short_help='Restore node to service.')
@click.argument(
    'node', default=myhostname
)
@click.option(
    '-w', '--wait', 'wait', is_flag=True, default=False,
    help='Wait for migrations to complete before returning.'
)
def node_unflush(node, wait):
    """
    Restore NODE to active service and migrate back all VMs. If unspecified, defaults to this host.
    """

    retcode, retmsg = pvc_node.node_domain_state(config, node, 'ready', wait)
    cleanup(retcode, retmsg)

###############################################################################
# pvc node info
###############################################################################
@click.command(name='info', short_help='Show details of a node object.')
@click.argument(
    'node', default=myhostname
)
@click.option(
    '-l', '--long', 'long_output', is_flag=True, default=False,
    help='Display more detailed information.'
)
@cluster_req
def node_info(node, long_output):
    """
    Show information about node NODE. If unspecified, defaults to this host.
    """

    retcode, retdata = pvc_node.node_info(config, node)
    if retcode:
        retdata = pvc_node.format_info(retdata, long_output)
    cleanup(retcode, retdata)

###############################################################################
# pvc node list
###############################################################################
@click.command(name='list', short_help='List all node objects.')
@click.argument(
    'limit', default=None, required=False
)
@click.option(
    '-ds', '--daemon-state', 'target_daemon_state', default=None,
    help='Limit list to nodes in the specified daemon state.'
)
@click.option(
    '-cs', '--coordinator-state', 'target_coordinator_state', default=None,
    help='Limit list to nodes in the specified coordinator state.'
)
@click.option(
    '-vs', '--domain-state', 'target_domain_state', default=None,
    help='Limit list to nodes in the specified domain state.'
)
@click.option(
    '-r', '--raw', 'raw', is_flag=True, default=False,
    help='Display the raw list of node names only.'
)
@cluster_req
def node_list(limit, target_daemon_state, target_coordinator_state, target_domain_state, raw):
    """
    List all nodes; optionally only match names matching regex LIMIT.
    """

    retcode, retdata = pvc_node.node_list(config, limit, target_daemon_state, target_coordinator_state, target_domain_state)
    if retcode:
        retdata = pvc_node.format_list(retdata, raw)
    else:
        if raw:
            retdata = ""
    cleanup(retcode, retdata)

###############################################################################
# pvc vm
###############################################################################
@click.group(name='vm', short_help='Manage a PVC virtual machine.', context_settings=CONTEXT_SETTINGS)
def cli_vm():
    """
    Manage the state of a virtual machine in the PVC cluster.
    """

###############################################################################
# pvc vm define
###############################################################################
@click.command(name='define', short_help='Define a new virtual machine from a Libvirt XML file.')
@click.option(
    '-t', '--target', 'target_node',
    help='Home node for this domain; autoselect if unspecified.'
)
@click.option(
    '-l', '--limit', 'node_limit', default=None, show_default=False,
    help='Comma-separated list of nodes to limit VM operation to; saved with VM.'
)
@click.option(
    '-s', '--selector', 'node_selector', default='mem', show_default=True,
    type=click.Choice(['mem','load','vcpus','vms']),
    help='Method to determine optimal target node during autoselect; saved with VM.'
)
@click.option(
    '-a/-A', '--autostart/--no-autostart', 'node_autostart', is_flag=True, default=False,
    help='Start VM automatically on next unflush/ready state of home node; unset by daemon once used.'
)
@click.option(
    '-m', '--method', 'migration_method', default='none', show_default=True,
    type=click.Choice(['none','live','shutdown']),
    help='The preferred migration method of the VM between nodes; saved with VM.'
)
@click.argument(
    'vmconfig', type=click.File()
)
@cluster_req
def vm_define(vmconfig, target_node, node_limit, node_selector, node_autostart, migration_method):
    """
    Define a new virtual machine from Libvirt XML configuration file VMCONFIG.
    """

    # Open the XML file
    vmconfig_data = vmconfig.read()
    vmconfig.close()

    # Verify our XML is sensible
    try:
        xml_data = etree.fromstring(vmconfig_data)
        new_cfg = etree.tostring(xml_data, pretty_print=True).decode('utf8')
    except Exception:
        cleanup(False, 'Error: XML is malformed or invalid')

    retcode, retmsg = pvc_vm.vm_define(config, new_cfg, target_node, node_limit, node_selector, node_autostart, migration_method)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm meta
###############################################################################
@click.command(name='meta', short_help='Modify PVC metadata of an existing VM.')
@click.option(
    '-l', '--limit', 'node_limit', default=None, show_default=False,
    help='Comma-separated list of nodes to limit VM operation to; set to an empty string to remove.'
)
@click.option(
    '-s', '--selector', 'node_selector', default=None, show_default=False,
    type=click.Choice(['mem','load','vcpus','vms']),
    help='Method to determine optimal target node during autoselect.'
)
@click.option(
    '-a/-A', '--autostart/--no-autostart', 'node_autostart', is_flag=True, default=None,
    help='Start VM automatically on next unflush/ready state of home node; unset by daemon once used.'
)
@click.option(
    '-m', '--method', 'migration_method', default='none', show_default=True,
    type=click.Choice(['none','live','shutdown']),
    help='The preferred migration method of the VM between nodes; saved with VM.'
)
@click.option(
    '-p', '--profile', 'provisioner_profile', default=None, show_default=False,
    help='PVC provisioner profile name for VM.'
)
@click.argument(
    'domain'
)
@cluster_req
def vm_meta(domain, node_limit, node_selector, node_autostart, migration_method, provisioner_profile):
    """
    Modify the PVC metadata of existing virtual machine DOMAIN. At least one option to update must be specified. DOMAIN may be a UUID or name.
    """

    if node_limit is None and node_selector is None and node_autostart is None and migration_method is None and provisioner_profile is None:
        cleanup(False, 'At least one metadata option must be specified to update.')

    retcode, retmsg = pvc_vm.vm_metadata(config, domain, node_limit, node_selector, node_autostart, migration_method, provisioner_profile)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm modify
###############################################################################
@click.command(name='modify', short_help='Modify an existing VM configuration.')
@click.option(
    '-e', '--editor', 'editor', is_flag=True,
    help='Use local editor to modify existing config.'
)
@click.option(
    '-r', '--restart', 'restart', is_flag=True,
    help='Immediately restart VM to apply new config.'
)
@click.argument(
    'domain'
)
@click.argument(
    'cfgfile', type=click.File(), default=None, required=False
)
def vm_modify(domain, cfgfile, editor, restart):
    """
    Modify existing virtual machine DOMAIN, either in-editor or with replacement CONFIG. DOMAIN may be a UUID or name.
    """

    if editor == False and cfgfile == None:
        cleanup(False, 'Either an XML config file or the "--editor" option must be specified.')

    retcode, vm_information = pvc_vm.vm_info(config, domain)
    if not retcode and not vm_information.get('name', None):
        cleanup(False, 'ERROR: Could not find VM "{}"!'.format(domain))

    dom_uuid = vm_information.get('uuid')
    dom_name = vm_information.get('name')

    if editor == True:
        # Grab the current config
        current_vm_cfg_raw = vm_information.get('xml')
        xml_data = etree.fromstring(current_vm_cfg_raw)
        current_vm_cfgfile = etree.tostring(xml_data, pretty_print=True).decode('utf8').strip()

        new_vm_cfgfile = click.edit(text=current_vm_cfgfile, require_save=True, extension='.xml')
        if new_vm_cfgfile is None:
            click.echo('Aborting with no modifications.')
            exit(0)
        else:
            new_vm_cfgfile = new_vm_cfgfile.strip()

        # Show a diff and confirm
        click.echo('Pending modifications:')
        click.echo('')
        diff = list(difflib.unified_diff(current_vm_cfgfile.split('\n'), new_vm_cfgfile.split('\n'), fromfile='current', tofile='modified', fromfiledate='', tofiledate='', n=3, lineterm=''))
        for line in diff:
            if re.match('^\+', line) != None:
                click.echo(colorama.Fore.GREEN + line + colorama.Fore.RESET)
            elif re.match('^\-', line) != None:
                click.echo(colorama.Fore.RED + line + colorama.Fore.RESET)
            elif re.match('^[^]', line) != None:
                click.echo(colorama.Fore.BLUE + line + colorama.Fore.RESET)
            else:
                click.echo(line)
        click.echo('')

        click.confirm('Write modifications to cluster?', abort=True)

        if restart:
            click.echo('Writing modified configuration of VM "{}" and restarting.'.format(dom_name))
        else:
            click.echo('Writing modified configuration of VM "{}".'.format(dom_name))

    # We're operating in replace mode
    else:
        # Open the XML file
        new_vm_cfgfile = cfgfile.read()
        cfgfile.close()

        if restart:
            click.echo('Replacing configuration of VM "{}" with file "{}" and restarting.'.format(dom_name, cfgfile.name))
        else:
            click.echo('Replacing configuration of VM "{}" with file "{}".'.format(dom_name, cfgfile.name))

    # Verify our XML is sensible
    try:
        xml_data = etree.fromstring(new_vm_cfgfile)
        new_cfg = etree.tostring(xml_data, pretty_print=True).decode('utf8')
    except Exception as e:
        cleanup(False, 'Error: XML is malformed or invalid: {}'.format(e))

    retcode, retmsg = pvc_vm.vm_modify(config, domain, new_cfg, restart)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm undefine
###############################################################################
@click.command(name='undefine', short_help='Undefine a virtual machine.')
@click.argument(
    'domain'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def vm_undefine(domain, confirm_flag):
    """
    Stop virtual machine DOMAIN and remove it database, preserving disks. DOMAIN may be a UUID or name.
    """
    if not confirm_flag:
        try:
            click.confirm('Undefine VM {}'.format(domain), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retmsg = pvc_vm.vm_remove(config, domain, delete_disks=False)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm remove
###############################################################################
@click.command(name='remove', short_help='Remove a virtual machine.')
@click.argument(
    'domain'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def vm_remove(domain, confirm_flag):
    """
    Stop virtual machine DOMAIN and remove it, along with all disks,. DOMAIN may be a UUID or name.
    """
    if not confirm_flag:
        try:
            click.confirm('Undefine VM {} and remove all disks'.format(domain), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retmsg = pvc_vm.vm_remove(config, domain, delete_disks=True)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm start
###############################################################################
@click.command(name='start', short_help='Start up a defined virtual machine.')
@click.argument(
    'domain'
)
@cluster_req
def vm_start(domain):
    """
    Start virtual machine DOMAIN on its configured node. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc_vm.vm_state(config, domain, 'start')
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm restart
###############################################################################
@click.command(name='restart', short_help='Restart a running virtual machine.')
@click.argument(
    'domain'
)
@click.option(
    '-w', '--wait', 'wait', is_flag=True, default=False,
    help='Wait for restart to complete before returning.'
)
@cluster_req
def vm_restart(domain, wait):
    """
    Restart running virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc_vm.vm_state(config, domain, 'restart', wait=wait)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm shutdown
###############################################################################
@click.command(name='shutdown', short_help='Gracefully shut down a running virtual machine.')
@click.argument(
    'domain'
)
@click.option(
    '-w', '--wait', 'wait', is_flag=True, default=False,
    help='Wait for shutdown to complete before returning.'
)
@cluster_req
def vm_shutdown(domain, wait):
    """
    Gracefully shut down virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc_vm.vm_state(config, domain, 'shutdown', wait=wait)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm stop
###############################################################################
@click.command(name='stop', short_help='Forcibly halt a running virtual machine.')
@click.argument(
    'domain'
)
@cluster_req
def vm_stop(domain):
    """
    Forcibly halt (destroy) running virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc_vm.vm_state(config, domain, 'stop')
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm disable
###############################################################################
@click.command(name='disable', short_help='Mark a virtual machine as disabled.')
@click.argument(
    'domain'
)
@cluster_req
def vm_disable(domain):
    """
    Prevent stopped virtual machine DOMAIN from being counted towards cluster health status. DOMAIN may be a UUID or name.

    Use this option for VM that are stopped intentionally or long-term and which should not impact cluster health if stopped. A VM can be started directly from disable state.
    """

    retcode, retmsg = pvc_vm.vm_state(config, domain, 'disable')
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm move
###############################################################################
@click.command(name='move', short_help='Permanently move a virtual machine to another node.')
@click.argument(
    'domain'
)
@click.option(
    '-t', '--target', 'target_node', default=None,
    help='Target node to migrate to; autodetect if unspecified.'
)
@click.option(
    '-w', '--wait', 'wait', is_flag=True, default=False,
    help='Wait for migration to complete before returning.'
)
@click.option(
    '--force-live', 'force_live', is_flag=True, default=False,
    help='Do not fall back to shutdown-based migration if live migration fails.'
)
@cluster_req
def vm_move(domain, target_node, wait, force_live):
    """
    Permanently move virtual machine DOMAIN, via live migration if running and possible, to another node. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc_vm.vm_node(config, domain, target_node, 'move', force=False, wait=wait, force_live=force_live)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm migrate
###############################################################################
@click.command(name='migrate', short_help='Temporarily migrate a virtual machine to another node.')
@click.argument(
    'domain'
)
@click.option(
    '-t', '--target', 'target_node', default=None,
    help='Target node to migrate to; autodetect if unspecified.'
)
@click.option(
    '-f', '--force', 'force_migrate', is_flag=True, default=False,
    help='Force migrate an already migrated VM; does not replace an existing previous node value.'
)
@click.option(
    '-w', '--wait', 'wait', is_flag=True, default=False,
    help='Wait for migration to complete before returning.'
)
@click.option(
    '--force-live', 'force_live', is_flag=True, default=False,
    help='Do not fall back to shutdown-based migration if live migration fails.'
)
@cluster_req
def vm_migrate(domain, target_node, force_migrate, wait, force_live):
    """
    Temporarily migrate running virtual machine DOMAIN, via live migration if possible, to another node. DOMAIN may be a UUID or name. If DOMAIN is not running, it will be started on the target node.
    """

    retcode, retmsg = pvc_vm.vm_node(config, domain, target_node, 'migrate', force=force_migrate, wait=wait, force_live=force_live)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm unmigrate
###############################################################################
@click.command(name='unmigrate', short_help='Restore a migrated virtual machine to its original node.')
@click.argument(
    'domain'
)
@click.option(
    '-w', '--wait', 'wait', is_flag=True, default=False,
    help='Wait for migration to complete before returning.'
)
@click.option(
    '--force-live', 'force_live', is_flag=True, default=False,
    help='Do not fall back to shutdown-based migration if live migration fails.'
)
@cluster_req
def vm_unmigrate(domain, wait, force_live):
    """
    Restore previously migrated virtual machine DOMAIN, via live migration if possible, to its original node. DOMAIN may be a UUID or name. If DOMAIN is not running, it will be started on the target node.
    """

    retcode, retmsg = pvc_vm.vm_node(config, domain, None, 'unmigrate', force=False, wait=wait, force_live=force_live)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm flush-locks
###############################################################################
@click.command(name='flush-locks', short_help='Flush stale RBD locks for a virtual machine.')
@click.argument(
    'domain'
)
@cluster_req
def vm_flush_locks(domain):
    """
    Flush stale RBD locks for virtual machine DOMAIN. DOMAIN may be a UUID or name. DOMAIN must be in a stopped state before flushing locks.
    """

    retcode, retmsg = pvc_vm.vm_locks(config, domain)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm log
###############################################################################
@click.command(name='log', short_help='Show console logs of a VM object.')
@click.argument(
    'domain'
)
@click.option(
    '-l', '--lines', 'lines', default=None, show_default=False,
    help='Display this many log lines from the end of the log buffer.  [default: 1000; with follow: 10]'
)
@click.option(
    '-f', '--follow', 'follow', is_flag=True, default=False,
    help='Follow the log buffer; output may be delayed by a few seconds relative to the live system. The --lines value defaults to 10 for the initial output.'
)
@cluster_req
def vm_log(domain, lines, follow):
    """
    Show console logs of virtual machine DOMAIN on its current node in a pager or continuously. DOMAIN may be a UUID or name. Note that migrating a VM to a different node will cause the log buffer to be overwritten by entries from the new node.
    """

    # Set the default here so we can handle it
    if lines is None:
        if follow:
            lines = 10
        else:
            lines = 1000

    if follow:
        retcode, retmsg = pvc_vm.follow_console_log(config, domain, lines)
    else:
        retcode, retmsg = pvc_vm.view_console_log(config, domain, lines)
        click.echo_via_pager(retmsg)
        retmsg = ''
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm info
###############################################################################
@click.command(name='info', short_help='Show details of a VM object.')
@click.argument(
    'domain'
)
@click.option(
    '-l', '--long', 'long_output', is_flag=True, default=False,
    help='Display more detailed information.'
)
@cluster_req
def vm_info(domain, long_output):
    """
    Show information about virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    retcode, retdata = pvc_vm.vm_info(config, domain)
    if retcode:
        retdata = pvc_vm.format_info(config, retdata, long_output)
    cleanup(retcode, retdata)

###############################################################################
# pvc vm dump
###############################################################################
@click.command(name='dump', short_help='Dump a virtual machine XML to stdout.')
@click.argument(
    'domain'
)
@cluster_req
def vm_dump(domain):
    """
    Dump the Libvirt XML definition of virtual machine DOMAIN to stdout. DOMAIN may be a UUID or name.
    """

    retcode, vm_information = pvc_vm.vm_info(config, domain)
    if not retcode and not vm_information.get('name', None):
        cleanup(False, 'ERROR: Could not find VM "{}"!'.format(domain))

    # Grab the current config
    current_vm_cfg_raw = vm_information.get('xml')
    xml_data = etree.fromstring(current_vm_cfg_raw)
    current_vm_cfgfile = etree.tostring(xml_data, pretty_print=True).decode('utf8')
    click.echo(current_vm_cfgfile.strip())

###############################################################################
# pvc vm list
###############################################################################
@click.command(name='list', short_help='List all VM objects.')
@click.argument(
    'limit', default=None, required=False
)
@click.option(
    '-t', '--target', 'target_node', default=None,
    help='Limit list to VMs on the specified node.'
)
@click.option(
    '-s', '--state', 'target_state', default=None,
    help='Limit list to VMs in the specified state.'
)
@click.option(
    '-r', '--raw', 'raw', is_flag=True, default=False,
    help='Display the raw list of VM names only.'
)
@cluster_req
def vm_list(target_node, target_state, limit, raw):
    """
    List all virtual machines; optionally only match names matching regex LIMIT.

    NOTE: Red-coloured network lists indicate one or more configured networks are missing/invalid.
    """

    retcode, retdata = pvc_vm.vm_list(config, limit, target_node, target_state)
    if retcode:
        retdata = pvc_vm.format_list(config, retdata, raw)
    else:
        if raw:
            retdata = ""
    cleanup(retcode, retdata)

###############################################################################
# pvc network
###############################################################################
@click.group(name='network', short_help='Manage a PVC virtual network.', context_settings=CONTEXT_SETTINGS)
def cli_network():
    """
    Manage the state of a VXLAN network in the PVC cluster.
    """

###############################################################################
# pvc network add
###############################################################################
@click.command(name='add', short_help='Add a new virtual network.')
@click.option(
    '-d', '--description', 'description',
    required=True,
    help='Description of the network; must be unique and not contain whitespace.'
)
@click.option(
    '-p', '--type', 'nettype',
    required=True,
    type=click.Choice(['managed', 'bridged']),
    help='Network type; managed networks control IP addressing; bridged networks are simple vLAN bridges. All subsequent options are unused for bridged networks.'
)
@click.option(
    '-n', '--domain', 'domain',
    default=None,
    help='Domain name of the network.'
)
@click.option(
    '--dns-server', 'name_servers',
    multiple=True,
    help='DNS nameserver for network; multiple entries may be specified.'
)
@click.option(
    '-i', '--ipnet', 'ip_network',
    default=None,
    help='CIDR-format IPv4 network address for subnet.'
)
@click.option(
    '-i6', '--ipnet6', 'ip6_network',
    default=None,
    help='CIDR-format IPv6 network address for subnet; should be /64 or larger ending "::/YY".'
)
@click.option(
    '-g', '--gateway', 'ip_gateway',
    default=None,
    help='Default IPv4 gateway address for subnet.'
)
@click.option(
    '-g6', '--gateway6', 'ip6_gateway',
    default=None,
    help='Default IPv6 gateway address for subnet.  [default: "X::1"]'
)
@click.option(
    '--dhcp/--no-dhcp', 'dhcp_flag',
    is_flag=True,
    default=False,
    help='Enable/disable IPv4 DHCP for clients on subnet.'
)
@click.option(
    '--dhcp-start', 'dhcp_start',
    default=None,
    help='IPv4 DHCP range start address.'
)
@click.option(
    '--dhcp-end', 'dhcp_end',
    default=None,
    help='IPv4 DHCP range end address.'
)
@click.argument(
    'vni'
)
@cluster_req
def net_add(vni, description, nettype, domain, ip_network, ip_gateway, ip6_network, ip6_gateway, dhcp_flag, dhcp_start, dhcp_end, name_servers):
    """
    Add a new virtual network with VXLAN identifier VNI.

    Examples:

    pvc network add 101 --description my-bridged-net --type bridged

      > Creates vLAN 101 and a simple bridge on the VNI dev interface.

    pvc network add 1001 --description my-managed-net --type managed --domain test.local --ipnet 10.1.1.0/24 --gateway 10.1.1.1

      > Creates a VXLAN with ID 1001 on the VNI dev interface, with IPv4 managed networking.

    IPv6 is fully supported with --ipnet6 and --gateway6 in addition to or instead of IPv4. PVC will configure DHCPv6 in a semi-managed configuration for the network if set.
    """

    retcode, retmsg = pvc_network.net_add(config, vni, description, nettype, domain, name_servers, ip_network, ip_gateway, ip6_network, ip6_gateway, dhcp_flag, dhcp_start, dhcp_end)
    cleanup(retcode, retmsg)

###############################################################################
# pvc network modify
###############################################################################
@click.command(name='modify', short_help='Modify an existing virtual network.')
@click.option(
    '-d', '--description', 'description',
    default=None,
    help='Description of the network; must be unique and not contain whitespace.'
)
@click.option(
    '-n', '--domain', 'domain',
    default=None,
    help='Domain name of the network.'
)
@click.option(
    '--dns-server', 'name_servers',
    multiple=True,
    help='DNS nameserver for network; multiple entries may be specified (will overwrite all previous entries).'
)
@click.option(
    '-i', '--ipnet', 'ip4_network',
    default=None,
    help='CIDR-format IPv4 network address for subnet.'
)
@click.option(
    '-i6', '--ipnet6', 'ip6_network',
    default=None,
    help='CIDR-format IPv6 network address for subnet.'
)
@click.option(
    '-g', '--gateway', 'ip4_gateway',
    default=None,
    help='Default IPv4 gateway address for subnet.'
)
@click.option(
    '-g6', '--gateway6', 'ip6_gateway',
    default=None,
    help='Default IPv6 gateway address for subnet.'
)
@click.option(
    '--dhcp/--no-dhcp', 'dhcp_flag',
    is_flag=True,
    default=None,
    help='Enable/disable DHCP for clients on subnet.'
)
@click.option(
    '--dhcp-start', 'dhcp_start',
    default=None,
    help='DHCP range start address.'
)
@click.option(
    '--dhcp-end', 'dhcp_end',
    default=None,
    help='DHCP range end address.'
)
@click.argument(
    'vni'
)
@cluster_req
def net_modify(vni, description, domain, name_servers, ip6_network, ip6_gateway, ip4_network, ip4_gateway, dhcp_flag, dhcp_start, dhcp_end):
    """
    Modify details of virtual network VNI. All fields optional; only specified fields will be updated.

    Example:
    pvc network modify 1001 --gateway 10.1.1.1 --dhcp
    """

    retcode, retmsg = pvc_network.net_modify(config, vni, description, domain, name_servers, ip4_network, ip4_gateway, ip6_network, ip6_gateway, dhcp_flag, dhcp_start, dhcp_end)
    cleanup(retcode, retmsg)

###############################################################################
# pvc network remove
###############################################################################
@click.command(name='remove', short_help='Remove a virtual network.')
@click.argument(
    'net'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def net_remove(net, confirm_flag):
    """
    Remove an existing virtual network NET; NET must be a VNI.

    WARNING: PVC does not verify whether clients are still present in this network. Before removing, ensure
    that all client VMs have been removed from the network or undefined behaviour may occur.
    """
    if not confirm_flag:
        try:
            click.confirm('Remove network {}'.format(net), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retmsg = pvc_network.net_remove(config, net)
    cleanup(retcode, retmsg)

###############################################################################
# pvc network info
###############################################################################
@click.command(name='info', short_help='Show details of a network.')
@click.argument(
    'vni'
)
@click.option(
    '-l', '--long', 'long_output', is_flag=True, default=False,
    help='Display more detailed information.'
)
@cluster_req
def net_info(vni, long_output):
    """
    Show information about virtual network VNI.
    """

    retcode, retdata = pvc_network.net_info(config, vni)
    if retcode:
        retdata = pvc_network.format_info(config, retdata, long_output)
    cleanup(retcode, retdata)

###############################################################################
# pvc network list
###############################################################################
@click.command(name='list', short_help='List all VM objects.')
@click.argument(
    'limit', default=None, required=False
)
@cluster_req
def net_list(limit):
    """
    List all virtual networks; optionally only match VNIs or Descriptions matching regex LIMIT.
    """

    retcode, retdata = pvc_network.net_list(config, limit)
    if retcode:
        retdata = pvc_network.format_list(config, retdata)
    cleanup(retcode, retdata)

###############################################################################
# pvc network dhcp
###############################################################################
@click.group(name='dhcp', short_help='Manage IPv4 DHCP leases in a PVC virtual network.', context_settings=CONTEXT_SETTINGS)
def net_dhcp():
    """
    Manage host IPv4 DHCP leases of a VXLAN network in the PVC cluster.
    """

###############################################################################
# pvc network dhcp add
###############################################################################
@click.command(name='add', short_help='Add a DHCP static reservation.')
@click.argument(
    'net'
)
@click.argument(
    'ipaddr'
)
@click.argument(
    'hostname'
)
@click.argument(
    'macaddr'
)
@cluster_req
def net_dhcp_add(net, ipaddr, macaddr, hostname):
    """
    Add a new DHCP static reservation of IP address IPADDR with hostname HOSTNAME for MAC address MACADDR to virtual network NET; NET must be a VNI.
    """

    retcode, retmsg = pvc_network.net_dhcp_add(config, net, ipaddr, macaddr, hostname)
    cleanup(retcode, retmsg)

###############################################################################
# pvc network dhcp remove
###############################################################################
@click.command(name='remove', short_help='Remove a DHCP static reservation.')
@click.argument(
    'net'
)
@click.argument(
    'macaddr'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def net_dhcp_remove(net, macaddr, confirm_flag):
    """
    Remove a DHCP lease for MACADDR from virtual network NET; NET must be a VNI.
    """
    if not confirm_flag:
        try:
            click.confirm('Remove DHCP lease for {} in network {}'.format(macaddr, net), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retmsg = pvc_network.net_dhcp_remove(config, net, macaddr)
    cleanup(retcode, retmsg)

###############################################################################
# pvc network dhcp list
###############################################################################
@click.command(name='list', short_help='List active DHCP leases.')
@click.argument(
    'net'
)
@click.argument(
    'limit', default=None, required=False
)
@click.option(
    '-s', '--static', 'only_static', is_flag=True, default=False,
    help='Show only static leases.'
)
@cluster_req
def net_dhcp_list(net, limit, only_static):
    """
    List all DHCP leases in virtual network NET; optionally only match elements matching regex LIMIT; NET must be a VNI.
    """

    retcode, retdata = pvc_network.net_dhcp_list(config, net, limit, only_static)
    if retcode:
        retdata = pvc_network.format_list_dhcp(retdata)
    cleanup(retcode, retdata)

###############################################################################
# pvc network acl
###############################################################################
@click.group(name='acl', short_help='Manage a PVC virtual network firewall ACL rule.', context_settings=CONTEXT_SETTINGS)
def net_acl():
    """
    Manage firewall ACLs of a VXLAN network in the PVC cluster.
    """

###############################################################################
# pvc network acl add
###############################################################################
@click.command(name='add', short_help='Add firewall ACL.')
@click.option(
    '--in/--out', 'direction',
    is_flag=True,
    default=True, # inbound
    help='Inbound or outbound ruleset.'
)
@click.option(
    '-d', '--description', 'description',
    required=True,
    help='Description of the ACL; must be unique and not contain whitespace.'
)
@click.option(
    '-r', '--rule', 'rule',
    required=True,
    help='NFT firewall rule.'
)
@click.option(
    '-o', '--order', 'order',
    default=None,
    help='Order of rule in the chain (see "list"); defaults to last.'
)
@click.argument(
    'net'
)
@cluster_req
def net_acl_add(net, direction, description, rule, order):
    """
    Add a new NFT firewall rule to network NET; the rule is a literal NFT rule belonging to the forward table for the client network; NET must be a VNI.

    NOTE: All client networks are default-allow in both directions; deny rules MUST be added here at the end of the sequence for a default-deny setup.

    NOTE: Ordering places the rule at the specified ID, not before it; the old rule of that ID and all subsequent rules will be moved down.

    NOTE: Descriptions are used as names, and must be unique within a network (both directions).

    Example:

    pvc network acl add 1001 --in --rule "tcp dport 22 ct state new accept" --description "ssh-in" --order 3
    """
    if direction:
        direction = 'in'
    else:
        direction = 'out'

    retcode, retmsg = pvc_network.net_acl_add(config, net, direction, description, rule, order)
    cleanup(retcode, retmsg)

###############################################################################
# pvc network acl remove
###############################################################################
@click.command(name='remove', short_help='Remove firewall ACL.')
@click.argument(
    'net'
)
@click.argument(
    'rule',
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def net_acl_remove(net, rule, confirm_flag):
    """
    Remove an NFT firewall rule RULE from network NET; RULE must be a description; NET must be a VNI.
    """
    if not confirm_flag:
        try:
            click.confirm('Remove ACL {} in network {}'.format(rule, net), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retmsg = pvc_network.net_acl_remove(config, net, rule)
    cleanup(retcode, retmsg)


###############################################################################
# pvc network acl list
###############################################################################
@click.command(name='list', short_help='List firewall ACLs.')
@click.option(
    '--in/--out', 'direction',
    is_flag=True,
    required=False,
    default=None,
    help='Inbound or outbound rule set only.'
)
@click.argument(
    'net'
)
@click.argument(
    'limit', default=None, required=False
)
@cluster_req
def net_acl_list(net, limit, direction):
    """
    List all NFT firewall rules in network NET; optionally only match elements matching description regex LIMIT; NET can be either a VNI or description.
    """
    if direction is not None:
        if direction:
            direction = 'in'
        else:
            direction = 'out'

    retcode, retdata = pvc_network.net_acl_list(config, net, limit, direction)
    if retcode:
        retdata = pvc_network.format_list_acl(retdata)
    cleanup(retcode, retdata)

###############################################################################
# pvc storage
###############################################################################
# Note: The prefix `storage` allows future potential storage subsystems.
#       Since Ceph is the only section not abstracted by PVC directly
#       (i.e. it references Ceph-specific concepts), this makes more
#       sense in the long-term.
###############################################################################
@click.group(name='storage', short_help='Manage the PVC storage cluster.', context_settings=CONTEXT_SETTINGS)
def cli_storage():
    """
    Manage the storage of the PVC cluster.
    """

###############################################################################
# pvc storage status
###############################################################################
@click.command(name='status', short_help='Show storage cluster status.')
@cluster_req
def ceph_status():
    """
    Show detailed status of the storage cluster.
    """

    retcode, retdata = pvc_ceph.ceph_status(config)
    if retcode:
        retdata = pvc_ceph.format_raw_output(retdata)
    cleanup(retcode, retdata)

###############################################################################
# pvc storage util
###############################################################################
@click.command(name='util', short_help='Show storage cluster utilization.')
@cluster_req
def ceph_util():
    """
    Show utilization of the storage cluster.
    """

    retcode, retdata = pvc_ceph.ceph_util(config)
    if retcode:
        retdata = pvc_ceph.format_raw_output(retdata)
    cleanup(retcode, retdata)

###############################################################################
# pvc storage benchmark
###############################################################################
@click.group(name='benchmark', short_help='Run or view cluster storage benchmarks.')
@cluster_req
def ceph_benchmark():
    """
    Run or view benchmarks of the storage cluster.
    """

###############################################################################
# pvc storage benchmark run
###############################################################################
@click.command(name='run', short_help='Run a storage benchmark.')
@click.argument(
    'pool'
)
@cluster_req
def ceph_benchmark_run(pool):
    """
    Run a storage benchmark on POOL in the background.
    """
    try:
        click.confirm('NOTE: Storage benchmarks generate significant load on the cluster and can take a very long time to complete on slow storage. They should be run sparingly. Continue', prompt_suffix='? ', abort=True)
    except Exception:
        exit(0)

    retcode, retmsg = pvc_ceph.ceph_benchmark_run(config, pool)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage benchmark info
###############################################################################
@click.command(name='info', short_help='Show detailed storage benchmark results.')
@click.argument(
    'job', required=True
)
@cluster_req
def ceph_benchmark_info(job):
    """
    Show full details of storage benchmark JOB.
    """

    retcode, retdata = pvc_ceph.ceph_benchmark_list(config, job)
    if retcode:
        retdata = pvc_ceph.format_info_benchmark(config, retdata)
    cleanup(retcode, retdata)

###############################################################################
# pvc storage benchmark list
###############################################################################
@click.command(name='list', short_help='List storage benchmark results.')
@click.argument(
    'job', default=None, required=False
)
@cluster_req
def ceph_benchmark_list(job):
    """
    List all Ceph storage benchmarks; optionally only match JOB.
    """

    retcode, retdata = pvc_ceph.ceph_benchmark_list(config, job)
    if retcode:
        retdata = pvc_ceph.format_list_benchmark(config, retdata)
    cleanup(retcode, retdata)

###############################################################################
# pvc storage osd
###############################################################################
@click.group(name='osd', short_help='Manage OSDs in the PVC storage cluster.', context_settings=CONTEXT_SETTINGS)
def ceph_osd():
    """
    Manage the Ceph OSDs of the PVC cluster.
    """

###############################################################################
# pvc storage osd add
###############################################################################
@click.command(name='add', short_help='Add new OSD.')
@click.argument(
    'node'
)
@click.argument(
    'device'
)
@click.option(
    '-w', '--weight', 'weight',
    default=1.0, show_default=True,
    help='Weight of the OSD within the CRUSH map.'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def ceph_osd_add(node, device, weight, confirm_flag):
    """
    Add a new Ceph OSD on node NODE with block device DEVICE.
    """
    if not confirm_flag:
        try:
            click.confirm('Destroy all data and create a new OSD on {}:{}'.format(node, device), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retmsg = pvc_ceph.ceph_osd_add(config, node, device, weight)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage osd remove
###############################################################################
@click.command(name='remove', short_help='Remove OSD.')
@click.argument(
    'osdid'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def ceph_osd_remove(osdid, confirm_flag):
    """
    Remove a Ceph OSD with ID OSDID.

    DANGER: This will completely remove the OSD from the cluster. OSDs will rebalance which may negatively affect performance or available space.
    """
    if not confirm_flag:
        try:
            click.confirm('Remove OSD {}'.format(osdid), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retmsg = pvc_ceph.ceph_osd_remove(config, osdid)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage osd in
###############################################################################
@click.command(name='in', short_help='Online OSD.')
@click.argument(
    'osdid'
)
@cluster_req
def ceph_osd_in(osdid):
    """
    Set a Ceph OSD with ID OSDID online.
    """

    retcode, retmsg = pvc_ceph.ceph_osd_state(config, osdid, 'in')
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage osd out
###############################################################################
@click.command(name='out', short_help='Offline OSD.')
@click.argument(
    'osdid'
)
@cluster_req
def ceph_osd_out(osdid):
    """
    Set a Ceph OSD with ID OSDID offline.
    """

    retcode, retmsg = pvc_ceph.ceph_osd_state(config, osdid, 'out')
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage osd set
###############################################################################
@click.command(name='set', short_help='Set property.')
@click.argument(
    'osd_property'
)
@cluster_req
def ceph_osd_set(osd_property):
    """
    Set a Ceph OSD property OSD_PROPERTY on the cluster.

    Valid properties are:

      full|pause|noup|nodown|noout|noin|nobackfill|norebalance|norecover|noscrub|nodeep-scrub|notieragent|sortbitwise|recovery_deletes|require_jewel_osds|require_kraken_osds 
    """

    retcode, retmsg = pvc_ceph.ceph_osd_option(config, osd_property, 'set')
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage osd unset
###############################################################################
@click.command(name='unset', short_help='Unset property.')
@click.argument(
    'osd_property'
)
@cluster_req
def ceph_osd_unset(osd_property):
    """
    Unset a Ceph OSD property OSD_PROPERTY on the cluster.

    Valid properties are:

      full|pause|noup|nodown|noout|noin|nobackfill|norebalance|norecover|noscrub|nodeep-scrub|notieragent|sortbitwise|recovery_deletes|require_jewel_osds|require_kraken_osds 
    """

    retcode, retmsg = pvc_ceph.ceph_osd_option(config, osd_property, 'unset')
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage osd list
###############################################################################
@click.command(name='list', short_help='List cluster OSDs.')
@click.argument(
    'limit', default=None, required=False
)
@cluster_req
def ceph_osd_list(limit):
    """
    List all Ceph OSDs; optionally only match elements matching ID regex LIMIT.
    """

    retcode, retdata = pvc_ceph.ceph_osd_list(config, limit)
    if retcode:
        retdata = pvc_ceph.format_list_osd(retdata)
    cleanup(retcode, retdata)

###############################################################################
# pvc storage pool
###############################################################################
@click.group(name='pool', short_help='Manage RBD pools in the PVC storage cluster.', context_settings=CONTEXT_SETTINGS)
def ceph_pool():
    """
    Manage the Ceph RBD pools of the PVC cluster.
    """

###############################################################################
# pvc storage pool add
###############################################################################
@click.command(name='add', short_help='Add new RBD pool.')
@click.argument(
    'name'
)
@click.argument(
    'pgs'
)
@click.option(
    '--replcfg', 'replcfg',
    default='copies=3,mincopies=2', show_default=True, required=False,
    help="""
    The replication configuration, specifying both a "copies" and "mincopies" value, separated by a
    comma, e.g. "copies=3,mincopies=2". The "copies" value specifies the total number of replicas and should not exceed the total number of nodes; the "mincopies" value specifies the minimum number of available copies to allow writes. For additional details please see the Cluster Architecture documentation.
    """
)
@cluster_req
def ceph_pool_add(name, pgs, replcfg):
    """
    Add a new Ceph RBD pool with name NAME and PGS placement groups.

    """

    retcode, retmsg = pvc_ceph.ceph_pool_add(config, name, pgs, replcfg)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage pool remove
###############################################################################
@click.command(name='remove', short_help='Remove RBD pool.')
@click.argument(
    'name'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def ceph_pool_remove(name, confirm_flag):
    """
    Remove a Ceph RBD pool with name NAME and all volumes on it.

    DANGER: This will completely remove the pool and all volumes contained in it from the cluster.
    """
    if not confirm_flag:
        try:
            click.confirm('Remove RBD pool {}'.format(name), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retmsg = pvc_ceph.ceph_pool_remove(config, name)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage pool list
###############################################################################
@click.command(name='list', short_help='List cluster RBD pools.')
@click.argument(
    'limit', default=None, required=False
)
@cluster_req
def ceph_pool_list(limit):
    """
    List all Ceph RBD pools; optionally only match elements matching name regex LIMIT.
    """

    retcode, retdata = pvc_ceph.ceph_pool_list(config, limit)
    if retcode:
        retdata = pvc_ceph.format_list_pool(retdata)
    cleanup(retcode, retdata)

###############################################################################
# pvc storage volume
###############################################################################
@click.group(name='volume', short_help='Manage RBD volumes in the PVC storage cluster.', context_settings=CONTEXT_SETTINGS)
def ceph_volume():
    """
    Manage the Ceph RBD volumes of the PVC cluster.
    """

###############################################################################
# pvc storage volume add
###############################################################################
@click.command(name='add', short_help='Add new RBD volume.')
@click.argument(
    'pool'
)
@click.argument(
    'name'
)
@click.argument(
    'size'
)
@cluster_req
def ceph_volume_add(pool, name, size):
    """
    Add a new Ceph RBD volume with name NAME and size SIZE [in human units, e.g. 1024M, 20G, etc.] to pool POOL.
    """

    retcode, retmsg = pvc_ceph.ceph_volume_add(config, pool, name, size)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage volume upload
###############################################################################
@click.command(name='upload', short_help='Upload a local image file to RBD volume.')
@click.argument(
    'pool'
)
@click.argument(
    'name'
)
@click.argument(
    'image_file'
)
@click.option(
    '-f', '--format', 'image_format',
    default='raw', show_default=True,
    help='The format of the source image.'
)
@cluster_req
def ceph_volume_upload(pool, name, image_format, image_file):
    """
    Upload a disk image file IMAGE_FILE to the RBD volume NAME in pool POOL.

    The volume NAME must exist in the pool before uploading to it, and must be large enough to fit the disk image in raw format.

    If the image format is "raw", the image is uploaded directly to the target volume without modification. Otherwise, it will be converted into raw format by "qemu-img convert" on the remote side before writing using a temporary volume. The image format must be a valid format recognized by "qemu-img", such as "vmdk" or "qcow2".
    """

    if not os.path.exists(image_file):
        click.echo("ERROR: File '{}' does not exist!".format(image_file))
        exit(1)

    retcode, retmsg = pvc_ceph.ceph_volume_upload(config, pool, name, image_format, image_file)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage volume remove
###############################################################################
@click.command(name='remove', short_help='Remove RBD volume.')
@click.argument(
    'pool'
)
@click.argument(
    'name'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def ceph_volume_remove(pool, name, confirm_flag):
    """
    Remove a Ceph RBD volume with name NAME from pool POOL.

    DANGER: This will completely remove the volume and all data contained in it.
    """
    if not confirm_flag:
        try:
            click.confirm('Remove volume {}/{}'.format(pool, name), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retmsg = pvc_ceph.ceph_volume_remove(config, pool, name)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage volume resize
###############################################################################
@click.command(name='resize', short_help='Resize RBD volume.')
@click.argument(
    'pool'
)
@click.argument(
    'name'
)
@click.argument(
    'size'
)
@cluster_req
def ceph_volume_resize(pool, name, size):
    """
    Resize an existing Ceph RBD volume with name NAME in pool POOL to size SIZE [in human units, e.g. 1024M, 20G, etc.].
    """
    retcode, retmsg = pvc_ceph.ceph_volume_modify(config, pool, name, new_size=size)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage volume rename
###############################################################################
@click.command(name='rename', short_help='Rename RBD volume.')
@click.argument(
    'pool'
)
@click.argument(
    'name'
)
@click.argument(
    'new_name'
)
@cluster_req
def ceph_volume_rename(pool, name, new_name):
    """
    Rename an existing Ceph RBD volume with name NAME in pool POOL to name NEW_NAME.
    """
    retcode, retmsg = pvc_ceph.ceph_volume_modify(config, pool, name, new_name=new_name)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage volume clone
###############################################################################
@click.command(name='clone', short_help='Clone RBD volume.')
@click.argument(
    'pool'
)
@click.argument(
    'name'
)
@click.argument(
    'new_name'
)
@cluster_req
def ceph_volume_clone(pool, name, new_name):
    """
    Clone a Ceph RBD volume with name NAME in pool POOL to name NEW_NAME in pool POOL.
    """
    retcode, retmsg = pvc_ceph.ceph_volume_clone(config, pool, name, new_name)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage volume list
###############################################################################
@click.command(name='list', short_help='List cluster RBD volumes.')
@click.argument(
    'limit', default=None, required=False
)
@click.option(
    '-p', '--pool', 'pool',
    default=None, show_default=True,
    help='Show volumes from this pool only.'
)
@cluster_req
def ceph_volume_list(limit, pool):
    """
    List all Ceph RBD volumes; optionally only match elements matching name regex LIMIT.
    """

    retcode, retdata = pvc_ceph.ceph_volume_list(config, limit, pool)
    if retcode:
        retdata = pvc_ceph.format_list_volume(retdata)
    cleanup(retcode, retdata)

###############################################################################
# pvc storage volume snapshot
###############################################################################
@click.group(name='snapshot', short_help='Manage RBD volume snapshots in the PVC storage cluster.', context_settings=CONTEXT_SETTINGS)
def ceph_volume_snapshot():
    """
    Manage the Ceph RBD volume snapshots of the PVC cluster.
    """

###############################################################################
# pvc storage volume snapshot add
###############################################################################
@click.command(name='add', short_help='Add new RBD volume snapshot.')
@click.argument(
    'pool'
)
@click.argument(
    'volume'
)
@click.argument(
    'name'
)
@cluster_req
def ceph_volume_snapshot_add(pool, volume, name):
    """
    Add a snapshot with name NAME of Ceph RBD volume VOLUME in pool POOL.
    """

    retcode, retmsg = pvc_ceph.ceph_snapshot_add(config, pool, volume, name)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage volume snapshot rename
###############################################################################
@click.command(name='rename', short_help='Rename RBD volume snapshot.')
@click.argument(
    'pool'
)
@click.argument(
    'volume'
)
@click.argument(
    'name'
)
@click.argument(
    'new_name'
)
@cluster_req
def ceph_volume_snapshot_rename(pool, volume, name, new_name):
    """
    Rename an existing Ceph RBD volume snapshot with name NAME to name NEW_NAME for volume VOLUME in pool POOL.
    """
    retcode, retmsg = pvc_ceph.ceph_snapshot_modify(config, pool, volume, name, new_name=new_name)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage volume snapshot remove
###############################################################################
@click.command(name='remove', short_help='Remove RBD volume snapshot.')
@click.argument(
    'pool'
)
@click.argument(
    'volume'
)
@click.argument(
    'name'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def ceph_volume_snapshot_remove(pool, volume, name, confirm_flag):
    """
    Remove a Ceph RBD volume snapshot with name NAME from volume VOLUME in pool POOL.

    DANGER: This will completely remove the snapshot.
    """
    if not confirm_flag:
        try:
            click.confirm('Remove snapshot {} for volume {}/{}'.format(name, pool, volume), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retmsg = pvc_ceph.ceph_snapshot_remove(config, pool, volume, name)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage volume snapshot list
###############################################################################
@click.command(name='list', short_help='List cluster RBD volume shapshots.')
@click.argument(
    'limit', default=None, required=False
)
@click.option(
    '-p', '--pool', 'pool',
    default=None, show_default=True,
    help='Show snapshots from this pool only.'
)
@click.option(
    '-o', '--volume', 'volume',
    default=None, show_default=True,
    help='Show snapshots from this volume only.'
)
@cluster_req
def ceph_volume_snapshot_list(pool, volume, limit):
    """
    List all Ceph RBD volume snapshots; optionally only match elements matching name regex LIMIT.
    """

    retcode, retdata = pvc_ceph.ceph_snapshot_list(config, limit, volume, pool)
    if retcode:
        retdata = pvc_ceph.format_list_snapshot(retdata)
    cleanup(retcode, retdata)


###############################################################################
# pvc provisioner
###############################################################################
@click.group(name='provisioner', short_help='Manage PVC provisioner.', context_settings=CONTEXT_SETTINGS)
def cli_provisioner():
    """
    Manage the PVC provisioner.
    """

###############################################################################
# pvc provisioner template
###############################################################################
@click.group(name='template', short_help='Manage PVC provisioner templates.', context_settings=CONTEXT_SETTINGS)
def provisioner_template():
    """
    Manage the PVC provisioner template system.
    """


###############################################################################
# pvc provisioner template list
###############################################################################
@click.command(name='list', short_help='List all templates.')
@click.argument(
    'limit', default=None, required=False
)
@cluster_req
def provisioner_template_list(limit):
    """
    List all templates in the PVC cluster provisioner.
    """
    retcode, retdata = pvc_provisioner.template_list(config, limit)
    if retcode:
        retdata = pvc_provisioner.format_list_template(retdata)
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner template system
###############################################################################
@click.group(name='system', short_help='Manage PVC provisioner system templates.', context_settings=CONTEXT_SETTINGS)
def provisioner_template_system():
    """
    Manage the PVC provisioner system templates.
    """

###############################################################################
# pvc provisioner template system list
###############################################################################
@click.command(name='list', short_help='List all system templates.')
@click.argument(
    'limit', default=None, required=False
)
@cluster_req
def provisioner_template_system_list(limit):
    """
    List all system templates in the PVC cluster provisioner.
    """
    retcode, retdata = pvc_provisioner.template_list(config, limit, template_type='system')
    if retcode:
        retdata = pvc_provisioner.format_list_template(retdata, template_type='system')
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner template system add
###############################################################################
@click.command(name='add', short_help='Add new system template.')
@click.argument(
    'name'
)
@click.option(
    '-u', '--vcpus', 'vcpus',
    required=True, type=int,
    help='The number of vCPUs.'
)
@click.option(
    '-m', '--vram', 'vram',
    required=True, type=int,
    help='The amount of vRAM (in MB).'
)
@click.option(
    '-s', '--serial', 'serial',
    is_flag=True, default=False,
    help='Enable the virtual serial console.'
)
@click.option(
    '-n', '--vnc', 'vnc',
    is_flag=True, default=False,
    help='Enable the VNC console.'
)
@click.option(
    '-b', '--vnc-bind', 'vnc_bind',
    default=None,
    help='Bind VNC to this IP address instead of localhost.'
)
@click.option(
    '--node-limit', 'node_limit',
    default=None,
    help='Limit VM operation to this CSV list of node(s).'
)
@click.option(
    '--node-selector', 'node_selector',
    type=click.Choice(['mem', 'vcpus', 'vms', 'load'], case_sensitive=False),
    default=None, # Use cluster default
    help='Use this selector to determine the optimal node during migrations.'
)
@click.option(
    '--node-autostart', 'node_autostart',
    is_flag=True, default=False,
    help='Autostart VM with their parent Node on first/next boot.'
)
@click.option(
    '--migration-method', 'migration_method',
    type=click.Choice(['none','live','shutdown'], case_sensitive=False),
    default=None, # Use cluster default
    help='The preferred migration method of the VM between nodes'
)
@cluster_req
def provisioner_template_system_add(name, vcpus, vram, serial, vnc, vnc_bind, node_limit, node_selector, node_autostart, migration_method):
    """
    Add a new system template NAME to the PVC cluster provisioner.
    """
    params = dict()
    params['name'] = name
    params['vcpus'] = vcpus
    params['vram']  = vram
    params['serial'] = serial
    params['vnc'] = vnc
    if vnc:
        params['vnc_bind'] = vnc_bind
    if node_limit:
        params['node_limit'] = node_limit
    if node_selector:
        params['node_selector'] = node_selector
    if node_autostart:
        params['node_autostart'] = node_autostart
    if migration_method:
        params['migration_method'] = migration_method

    retcode, retdata = pvc_provisioner.template_add(config, params, template_type='system')
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner template system modify
###############################################################################
@click.command(name='modify', short_help='Modify an existing system template.')
@click.argument(
    'name'
)
@click.option(
    '-u', '--vcpus', 'vcpus',
    type=int,
    help='The number of vCPUs.'
)
@click.option(
    '-m', '--vram', 'vram',
    type=int,
    help='The amount of vRAM (in MB).'
)
@click.option(
    '-s', '--serial', 'serial',
    is_flag=True, default=None,
    help='Enable the virtual serial console.'
)
@click.option(
    '-n', '--vnc', 'vnc',
    is_flag=True, default=None,
    help='Enable the VNC console.'
)
@click.option(
    '-b', '--vnc-bind', 'vnc_bind',
    help='Bind VNC to this IP address instead of localhost.'
)
@click.option(
    '--node-limit', 'node_limit',
    help='Limit VM operation to this CSV list of node(s).'
)
@click.option(
    '--node-selector', 'node_selector',
    type=click.Choice(['mem', 'vcpus', 'vms', 'load'], case_sensitive=False),
    help='Use this selector to determine the optimal node during migrations.'
)
@click.option(
    '--node-autostart', 'node_autostart',
    is_flag=True, default=None,
    help='Autostart VM with their parent Node on first/next boot.'
)
@click.option(
    '--migration-method', 'migration_method',
    type=click.Choice(['none','live','shutdown'], case_sensitive=False),
    default=None, # Use cluster default
    help='The preferred migration method of the VM between nodes'
)
@cluster_req
def provisioner_template_system_modify(name, vcpus, vram, serial, vnc, vnc_bind, node_limit, node_selector, node_autostart, migration_method):
    """
    Add a new system template NAME to the PVC cluster provisioner.
    """
    params = dict()
    params['vcpus'] = vcpus
    params['vram']  = vram
    params['serial'] = serial
    params['vnc'] = vnc
    params['vnc_bind'] = vnc_bind
    params['node_limit'] = node_limit
    params['node_selector'] = node_selector
    params['node_autostart'] = node_autostart
    params['migration_method'] = migration_method

    retcode, retdata = pvc_provisioner.template_modify(config, params, name, template_type='system')
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner template system remove
###############################################################################
@click.command(name='remove', short_help='Remove system template.')
@click.argument(
    'name'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def provisioner_template_system_remove(name, confirm_flag):
    """
    Remove system template NAME from the PVC cluster provisioner.
    """
    if not confirm_flag:
        try:
            click.confirm('Remove system template {}'.format(name), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retdata = pvc_provisioner.template_remove(config, name, template_type='system')
    cleanup(retcode, retdata)


###############################################################################
# pvc provisioner template network
###############################################################################
@click.group(name='network', short_help='Manage PVC provisioner network templates.', context_settings=CONTEXT_SETTINGS)
def provisioner_template_network():
    """
    Manage the PVC provisioner network templates.
    """

###############################################################################
# pvc provisioner template network list
###############################################################################
@click.command(name='list', short_help='List all network templates.')
@click.argument(
    'limit', default=None, required=False
)
@cluster_req
def provisioner_template_network_list(limit):
    """
    List all network templates in the PVC cluster provisioner.
    """
    retcode, retdata = pvc_provisioner.template_list(config, limit, template_type='network')
    if retcode:
        retdata = pvc_provisioner.format_list_template(retdata, template_type='network')
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner template network add
###############################################################################
@click.command(name='add', short_help='Add new network template.')
@click.argument(
    'name'
)
@click.option(
    '-m', '--mac-template', 'mac_template',
    default=None,
    help='Use this template for MAC addresses.'
)
@cluster_req
def provisioner_template_network_add(name, mac_template):
    """
    Add a new network template to the PVC cluster provisioner.

    MAC address templates are used to provide predictable MAC addresses for provisioned VMs.
    The normal format of a MAC template is:

      {prefix}:XX:XX:{vmid}{netid}

    The {prefix} variable is replaced by the provisioner with a standard prefix ("52:54:01"),
    which is different from the randomly-generated MAC prefix ("52:54:00") to avoid accidental
    overlap of MAC addresses.

    The {vmid} variable is replaced by a single hexidecimal digit representing the VM's ID,
    the numerical suffix portion of its name; VMs without a suffix numeral have ID 0. VMs with
    IDs greater than 15 (hexidecimal "f") will wrap back to 0.

    The {netid} variable is replaced by the sequential identifier, starting at 0, of the
    network VNI of the interface; for example, the first interface is 0, the second is 1, etc.

    The four X digits are use-configurable. Use these digits to uniquely define the MAC
    address.

    Example: pvc provisioner template network add --mac-template "{prefix}:2f:1f:{vmid}{netid}" test-template

    The location of the two per-VM variables can be adjusted at the administrator's discretion,
    or removed if not required (e.g. a single-network template, or template for a single VM).
    In such situations, be careful to avoid accidental overlap with other templates' variable
    portions.
    """
    params = dict()
    params['name'] = name
    params['mac_template'] = mac_template

    retcode, retdata = pvc_provisioner.template_add(config, params, template_type='network')
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner template network remove
###############################################################################
@click.command(name='remove', short_help='Remove network template.')
@click.argument(
    'name'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def provisioner_template_network_remove(name, confirm_flag):
    """
    Remove network template MAME from the PVC cluster provisioner.
    """
    if not confirm_flag:
        try:
            click.confirm('Remove network template {}'.format(name), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retdata = pvc_provisioner.template_remove(config, name, template_type='network')
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner template network vni
###############################################################################
@click.group(name='vni', short_help='Manage PVC provisioner network template VNIs.', context_settings=CONTEXT_SETTINGS)
def provisioner_template_network_vni():
    """
    Manage the network VNIs in PVC provisioner network templates.
    """

###############################################################################
# pvc provisioner template network vni add
###############################################################################
@click.command(name='add', short_help='Add network VNI to network template.')
@click.argument(
    'name'
)
@click.argument(
    'vni'
)
@cluster_req
def provisioner_template_network_vni_add(name, vni):
    """
    Add a new network VNI to network template NAME.

    Networks will be added to VMs in the order they are added and displayed within the template.
    """
    params = dict()

    retcode, retdata = pvc_provisioner.template_element_add(config, name, vni, params, element_type='net', template_type='network')
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner template network vni remove
###############################################################################
@click.command(name='remove', short_help='Remove network VNI from network template.')
@click.argument(
    'name'
)
@click.argument(
    'vni'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def provisioner_template_network_vni_remove(name, vni, confirm_flag):
    """
    Remove network VNI from network template NAME.
    """
    if not confirm_flag:
        try:
            click.confirm('Remove VNI {} from network template {}'.format(vni, name), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retdata = pvc_provisioner.template_element_remove(config, name, vni, element_type='net', template_type='network')
    cleanup(retcode, retdata)


###############################################################################
# pvc provisioner template storage
###############################################################################
@click.group(name='storage', short_help='Manage PVC provisioner storage templates.', context_settings=CONTEXT_SETTINGS)
def provisioner_template_storage():
    """
    Manage the PVC provisioner storage templates.
    """

###############################################################################
# pvc provisioner template storage list
###############################################################################
@click.command(name='list', short_help='List all storage templates.')
@click.argument(
    'limit', default=None, required=False
)
@cluster_req
def provisioner_template_storage_list(limit):
    """
    List all storage templates in the PVC cluster provisioner.
    """
    retcode, retdata = pvc_provisioner.template_list(config, limit, template_type='storage')
    if retcode:
        retdata = pvc_provisioner.format_list_template(retdata, template_type='storage')
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner template storage add
###############################################################################
@click.command(name='add', short_help='Add new storage template.')
@click.argument(
    'name'
)
@cluster_req
def provisioner_template_storage_add(name):
    """
    Add a new storage template to the PVC cluster provisioner.
    """
    params = dict()
    params['name'] = name

    retcode, retdata = pvc_provisioner.template_add(config, params, template_type='storage')
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner template storage remove
###############################################################################
@click.command(name='remove', short_help='Remove storage template.')
@click.argument(
    'name'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def provisioner_template_storage_remove(name, confirm_flag):
    """
    Remove storage template NAME from the PVC cluster provisioner.
    """
    if not confirm_flag:
        try:
            click.confirm('Remove storage template {}'.format(name), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retdata = pvc_provisioner.template_remove(config, name, template_type='storage')
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner template storage disk
###############################################################################
@click.group(name='disk', short_help='Manage PVC provisioner storage template disks.', context_settings=CONTEXT_SETTINGS)
def provisioner_template_storage_disk():
    """
    Manage the disks in PVC provisioner storage templates.
    """

###############################################################################
# pvc provisioner template storage disk add
###############################################################################
@click.command(name='add', short_help='Add disk to storage template.')
@click.argument(
    'name'
)
@click.argument(
    'disk'
)
@click.option(
    '-p', '--pool', 'pool',
    required=True,
    help='The storage pool for the disk.'
)
@click.option(
    '-i', '--source-volume', 'source_volume',
    default=None,
    help='The source volume to clone'
)
@click.option(
    '-s', '--size', 'size', type=int,
    default=None,
    help='The size of the disk (in GB).'
)
@click.option(
    '-f', '--filesystem', 'filesystem',
    default=None,
    help='The filesystem of the disk.'
)
@click.option(
    '--fsarg', 'fsargs',
    default=None, multiple=True,
    help='Additional argument for filesystem creation, in arg=value format without leading dashes.'
)
@click.option(
    '-m', '--mountpoint', 'mountpoint',
    default=None,
    help='The target Linux mountpoint of the disk; requires a filesystem.'
)
@cluster_req
def provisioner_template_storage_disk_add(name, disk, pool, source_volume, size, filesystem, fsargs, mountpoint):
    """
    Add a new DISK to storage template NAME.

    DISK must be a Linux-style sdX/vdX disk identifier, such as "sda" or "vdb". All disks in a template must use the same identifier format.

    Disks will be added to VMs in sdX/vdX order. For disks with mountpoints, ensure this order is sensible.
    """

    if source_volume and (size or filesystem or mountpoint):
        click.echo('The "--source-volume" option is not compatible with the "--size", "--filesystem", or "--mountpoint" options.')
        exit(1)

    params = dict()
    params['pool'] = pool
    params['source_volume'] = source_volume
    params['disk_size'] = size
    if filesystem:
        params['filesystem'] = filesystem
    if filesystem and fsargs:
        dash_fsargs = list()
        for arg in fsargs:
            arg_len = len(arg.split('=')[0])
            if arg_len == 1:
                dash_fsargs.append('-' + arg)
            else:
                dash_fsargs.append('--' + arg)
        params['filesystem_arg'] = dash_fsargs
    if filesystem and mountpoint:
        params['mountpoint'] = mountpoint

    retcode, retdata = pvc_provisioner.template_element_add(config, name, disk, params, element_type='disk', template_type='storage')
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner template storage disk remove
###############################################################################
@click.command(name='remove', short_help='Remove disk from storage template.')
@click.argument(
    'name'
)
@click.argument(
    'disk'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def provisioner_template_storage_disk_remove(name, disk, confirm_flag):
    """
    Remove DISK from storage template NAME.

    DISK must be a Linux-style disk identifier such as "sda" or "vdb".
    """
    if not confirm_flag:
        try:
            click.confirm('Remove disk {} from storage template {}'.format(disk, name), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retdata = pvc_provisioner.template_element_remove(config, name, disk, element_type='disk', template_type='storage')
    cleanup(retcode, retdata)


###############################################################################
# pvc provisioner userdata
###############################################################################
@click.group(name='userdata', short_help='Manage PVC provisioner userdata documents.', context_settings=CONTEXT_SETTINGS)
def provisioner_userdata():
    """
    Manage userdata documents in the PVC provisioner.
    """

###############################################################################
# pvc provisioner userdata list
###############################################################################
@click.command(name='list', short_help='List all userdata documents.')
@click.argument(
    'limit', default=None, required=False
)
@click.option(
    '-f', '--full', 'full',
    is_flag=True, default=False,
    help='Show all lines of the document instead of first 4.'
)
@cluster_req
def provisioner_userdata_list(limit, full):
    """
    List all userdata documents in the PVC cluster provisioner.
    """
    retcode, retdata = pvc_provisioner.userdata_list(config, limit)
    if retcode:
        if not full:
            lines = 4
        else:
            lines = None
        retdata = pvc_provisioner.format_list_userdata(retdata, lines)
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner userdata show
###############################################################################
@click.command(name='show', short_help='Show contents of userdata documents.')
@click.argument(
    'name'
)
@cluster_req
def provisioner_userdata_show(name):
    """
    Show the full contents of userdata document NAME.
    """
    retcode, retdata = pvc_provisioner.userdata_show(config, name)
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner userdata add
###############################################################################
@click.command(name='add', short_help='Define userdata document from file.')
@click.argument(
    'name'
)
@click.argument(
    'filename', type=click.File()
)
@cluster_req
def provisioner_userdata_add(name, filename):
    """
    Add a new userdata document NAME from file FILENAME.
    """

    # Open the YAML file
    userdata = filename.read()
    filename.close()
    try:
        yaml.load(userdata, Loader=yaml.FullLoader)
    except Exception as e:
        click.echo("Error: Userdata document is malformed")
        cleanup(False, e)

    params = dict()
    params['name'] = name
    params['data'] = userdata.strip()

    retcode, retmsg = pvc_provisioner.userdata_add(config, params)
    cleanup(retcode, retmsg)

###############################################################################
# pvc provisioner userdata modify
###############################################################################
@click.command(name='modify', short_help='Modify existing userdata document.')
@click.option(
    '-e', '--editor', 'editor', is_flag=True,
    help='Use local editor to modify existing document.'
)
@click.argument(
    'name'
)
@click.argument(
    'filename', type=click.File(), default=None, required=False
)
@cluster_req
def provisioner_userdata_modify(name, filename, editor):
    """
    Modify existing userdata document NAME, either in-editor or with replacement FILE.
    """

    if editor == False and filename == None:
        cleanup(False, 'Either a file or the "--editor" option must be specified.')

    if editor == True:
        # Grab the current config
        retcode, retdata = pvc_provisioner.userdata_info(config, name)
        if not retcode:
            click.echo(retdata)
            exit(1)
        current_userdata = retdata['userdata'].strip()

        new_userdata = click.edit(text=current_userdata, require_save=True, extension='.yaml')
        if new_userdata is None:
            click.echo('Aborting with no modifications.')
            exit(0)
        else:
            new_userdata = new_userdata.strip()

        # Show a diff and confirm
        click.echo('Pending modifications:')
        click.echo('')
        diff = list(difflib.unified_diff(current_userdata.split('\n'), new_userdata.split('\n'), fromfile='current', tofile='modified', fromfiledate='', tofiledate='', n=3, lineterm=''))
        for line in diff:
            if re.match('^\+', line) != None:
                click.echo(colorama.Fore.GREEN + line + colorama.Fore.RESET)
            elif re.match('^\-', line) != None:
                click.echo(colorama.Fore.RED + line + colorama.Fore.RESET)
            elif re.match('^[^]', line) != None:
                click.echo(colorama.Fore.BLUE + line + colorama.Fore.RESET)
            else:
                click.echo(line)
        click.echo('')

        click.confirm('Write modifications to cluster?', abort=True)

        userdata = new_userdata

    # We're operating in replace mode
    else:
        # Open the new file
        userdata = filename.read().strip()
        filename.close()

    try:
        yaml.load(userdata, Loader=yaml.FullLoader)
    except Exception as e:
        click.echo("Error: Userdata document is malformed")
        cleanup(False, e)

    params = dict()
    params['data'] = userdata

    retcode, retmsg = pvc_provisioner.userdata_modify(config, name, params)
    cleanup(retcode, retmsg)

###############################################################################
# pvc provisioner userdata remove
###############################################################################
@click.command(name='remove', short_help='Remove userdata document.')
@click.argument(
    'name'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def provisioner_userdata_remove(name, confirm_flag):
    """
    Remove userdata document NAME from the PVC cluster provisioner.
    """
    if not confirm_flag:
        try:
            click.confirm('Remove userdata document {}'.format(name), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retdata = pvc_provisioner.userdata_remove(config, name)
    cleanup(retcode, retdata)


###############################################################################
# pvc provisioner script
###############################################################################
@click.group(name='script', short_help='Manage PVC provisioner scripts.', context_settings=CONTEXT_SETTINGS)
def provisioner_script():
    """
    Manage scripts in the PVC provisioner.
    """

###############################################################################
# pvc provisioner script list
###############################################################################
@click.command(name='list', short_help='List all scripts.')
@click.argument(
    'limit', default=None, required=False
)
@click.option(
    '-f', '--full', 'full',
    is_flag=True, default=False,
    help='Show all lines of the document instead of first 4.'
)
@cluster_req
def provisioner_script_list(limit, full):
    """
    List all scripts in the PVC cluster provisioner.
    """
    retcode, retdata = pvc_provisioner.script_list(config, limit)
    if retcode:
        if not full:
            lines = 4
        else:
            lines = None
        retdata = pvc_provisioner.format_list_script(retdata, lines)
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner script show
###############################################################################
@click.command(name='show', short_help='Show contents of script documents.')
@click.argument(
    'name'
)
@cluster_req
def provisioner_script_show(name):
    """
    Show the full contents of script document NAME.
    """
    retcode, retdata = pvc_provisioner.script_show(config, name)
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner script add
###############################################################################
@click.command(name='add', short_help='Define script from file.')
@click.argument(
    'name'
)
@click.argument(
    'filename', type=click.File()
)
@cluster_req
def provisioner_script_add(name, filename):
    """
    Add a new script NAME from file FILENAME.
    """

    # Open the XML file
    script = filename.read()
    filename.close()

    params = dict()
    params['name'] = name
    params['data'] = script.strip()

    retcode, retmsg = pvc_provisioner.script_add(config, params)
    cleanup(retcode, retmsg)

###############################################################################
# pvc provisioner script modify
###############################################################################
@click.command(name='modify', short_help='Modify existing script.')
@click.option(
    '-e', '--editor', 'editor', is_flag=True,
    help='Use local editor to modify existing document.'
)
@click.argument(
    'name'
)
@click.argument(
    'filename', type=click.File(), default=None, required=False
)
@cluster_req
def provisioner_script_modify(name, filename, editor):
    """
    Modify existing script NAME, either in-editor or with replacement FILE.
    """

    if editor == False and filename == None:
        cleanup(False, 'Either a file or the "--editor" option must be specified.')

    if editor == True:
        # Grab the current config
        retcode, retdata = pvc_provisioner.script_info(config, name)
        if not retcode:
            click.echo(retdata)
            exit(1)
        current_script = retdata['script'].strip()

        new_script = click.edit(text=current_script, require_save=True, extension='.py')
        if new_script is None:
            click.echo('Aborting with no modifications.')
            exit(0)
        else:
            new_script = new_script.strip()

        # Show a diff and confirm
        click.echo('Pending modifications:')
        click.echo('')
        diff = list(difflib.unified_diff(current_script.split('\n'), new_script.split('\n'), fromfile='current', tofile='modified', fromfiledate='', tofiledate='', n=3, lineterm=''))
        for line in diff:
            if re.match('^\+', line) != None:
                click.echo(colorama.Fore.GREEN + line + colorama.Fore.RESET)
            elif re.match('^\-', line) != None:
                click.echo(colorama.Fore.RED + line + colorama.Fore.RESET)
            elif re.match('^[^]', line) != None:
                click.echo(colorama.Fore.BLUE + line + colorama.Fore.RESET)
            else:
                click.echo(line)
        click.echo('')

        click.confirm('Write modifications to cluster?', abort=True)

        script = new_script

    # We're operating in replace mode
    else:
        # Open the new file
        script = filename.read().strip()
        filename.close()

    params = dict()
    params['data'] = script

    retcode, retmsg = pvc_provisioner.script_modify(config, name, params)
    cleanup(retcode, retmsg)

###############################################################################
# pvc provisioner script remove
###############################################################################
@click.command(name='remove', short_help='Remove script.')
@click.argument(
    'name'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def provisioner_script_remove(name, confirm_flag):
    """
    Remove script NAME from the PVC cluster provisioner.
    """
    if not confirm_flag:
        try:
            click.confirm('Remove provisioning script {}'.format(name), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)
    params = dict()

    retcode, retdata = pvc_provisioner.script_remove(config, name)
    cleanup(retcode, retdata)


###############################################################################
# pvc provisioner ova
###############################################################################
@click.group(name='ova', short_help='Manage PVC provisioner OVA images.', context_settings=CONTEXT_SETTINGS)
def provisioner_ova():
    """
    Manage ovas in the PVC provisioner.
    """

###############################################################################
# pvc provisioner ova list
###############################################################################
@click.command(name='list', short_help='List all OVA images.')
@click.argument(
    'limit', default=None, required=False
)
@cluster_req
def provisioner_ova_list(limit):
    """
    List all OVA images in the PVC cluster provisioner.
    """
    retcode, retdata = pvc_provisioner.ova_list(config, limit)
    if retcode:
        retdata = pvc_provisioner.format_list_ova(retdata)
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner ova upload
###############################################################################
@click.command(name='upload', short_help='Upload OVA file.')
@click.argument(
    'name'
)
@click.argument(
    'filename'
)
@click.option(
    '-p', '--pool', 'pool',
    required=True,
    help='The storage pool for the OVA images.'
)
@cluster_req
def provisioner_ova_upload(name, filename, pool):
    """
    Upload a new OVA image NAME from FILENAME.

    Only single-file (.ova) OVA/OVF images are supported. For multi-file (.ovf + .vmdk) OVF images, concatenate them with "tar" then upload the resulting file.

    Once uploaded, a provisioner system template and OVA-type profile, each named NAME, will be created to store the configuration of the OVA.

    Note that the provisioner profile for the OVA will not contain any network template definitions, and will ignore network definitions from the OVA itself. The administrator must modify the profile's network template as appropriate to set the desired network configuration.

    Storage templates, provisioning scripts, and arguments for OVA-type profiles will be ignored and should not be set.
    """
    if not os.path.exists(filename):
        click.echo("ERROR: File '{}' does not exist!".format(filename))
        exit(1)

    params = dict()
    params['pool'] = pool
    params['ova_size'] = os.path.getsize(filename)

    retcode, retdata = pvc_provisioner.ova_upload(config, name, filename, params)
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner ova remove
###############################################################################
@click.command(name='remove', short_help='Remove OVA image.')
@click.argument(
    'name'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def provisioner_ova_remove(name, confirm_flag):
    """
    Remove OVA image NAME from the PVC cluster provisioner.
    """
    if not confirm_flag:
        try:
            click.confirm('Remove OVA image {}'.format(name), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retdata = pvc_provisioner.ova_remove(config, name)
    cleanup(retcode, retdata)


###############################################################################
# pvc provisioner profile
###############################################################################
@click.group(name='profile', short_help='Manage PVC provisioner profiless.', context_settings=CONTEXT_SETTINGS)
def provisioner_profile():
    """
    Manage profiles in the PVC provisioner.
    """

###############################################################################
# pvc provisioner profile list
###############################################################################
@click.command(name='list', short_help='List all profiles.')
@click.argument(
    'limit', default=None, required=False
)
@cluster_req
def provisioner_profile_list(limit):
    """
    List all profiles in the PVC cluster provisioner.
    """
    retcode, retdata = pvc_provisioner.profile_list(config, limit)
    if retcode:
        retdata = pvc_provisioner.format_list_profile(retdata)
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner profile add
###############################################################################
@click.command(name='add', short_help='Add provisioner profile.')
@click.argument(
    'name'
)
@click.option(
    '-p', '--profile-type', 'profile_type',
    default='provisioner', show_default=True,
    type=click.Choice(['provisioner', 'ova'], case_sensitive=False),
    help='The type of profile.'
)
@click.option(
    '-s', '--system-template', 'system_template',
    help='The system template for the profile.'
)
@click.option(
    '-n', '--network-template', 'network_template',
    help='The network template for the profile.'
)
@click.option(
    '-t', '--storage-template', 'storage_template',
    help='The storage template for the profile.'
)
@click.option(
    '-u', '--userdata', 'userdata',
    help='The userdata document for the profile.'
)
@click.option(
    '-x', '--script', 'script',
    help='The script for the profile.'
)
@click.option(
    '-o', '--ova', 'ova',
    help='The OVA image for the profile.'
)
@click.option(
    '-a', '--script-arg', 'script_args',
    default=[], multiple=True,
    help='Additional argument to the script install() function in key=value format.'
)
@cluster_req
def provisioner_profile_add(name, profile_type, system_template, network_template, storage_template, userdata, script, ova, script_args):
    """
    Add a new provisioner profile NAME.
    """
    params = dict()
    params['name'] = name
    params['profile_type'] = profile_type
    params['system_template'] = system_template
    params['network_template'] = network_template
    params['storage_template'] = storage_template
    params['userdata'] = userdata
    params['script'] = script
    params['ova'] = ova
    params['arg'] = script_args

    retcode, retdata = pvc_provisioner.profile_add(config, params)
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner profile modify
###############################################################################
@click.command(name='modify', short_help='Modify provisioner profile.')
@click.argument(
    'name'
)
@click.option(
    '-s', '--system-template', 'system_template',
    default=None,
    help='The system template for the profile.'
)
@click.option(
    '-n', '--network-template', 'network_template',
    default=None,
    help='The network template for the profile.'
)
@click.option(
    '-t', '--storage-template', 'storage_template',
    default=None,
    help='The storage template for the profile.'
)
@click.option(
    '-u', '--userdata', 'userdata',
    default=None,
    help='The userdata document for the profile.'
)
@click.option(
    '-x', '--script', 'script',
    default=None,
    help='The script for the profile.'
)
@click.option(
    '-d', '--delete-script-args', 'delete_script_args',
    default=False, is_flag=True,
    help="Delete any existing script arguments."
)
@click.option(
    '-a', '--script-arg', 'script_args',
    default=None, multiple=True,
    help='Additional argument to the script install() function in key=value format.'
)
@cluster_req
def provisioner_profile_modify(name, system_template, network_template, storage_template, userdata, script, delete_script_args, script_args):
    """
    Modify existing provisioner profile NAME.
    """
    params = dict()
    if system_template is not None:
        params['system_template'] = system_template
    if network_template is not None:
        params['network_template'] = network_template
    if storage_template is not None:
        params['storage_template'] = storage_template
    if userdata is not None:
        params['userdata'] = userdata
    if script is not None:
        params['script'] = script
    if delete_script_args:
        params['arg'] = []
    if script_args is not None:
        params['arg'] = script_args

    retcode, retdata = pvc_provisioner.profile_modify(config, name, params)
    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner profile remove
###############################################################################
@click.command(name='remove', short_help='Remove profile.')
@click.argument(
    'name'
)
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def provisioner_profile_remove(name, confirm_flag):
    """
    Remove profile NAME from the PVC cluster provisioner.
    """
    if not confirm_flag:
        try:
            click.confirm('Remove profile {}'.format(name), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    retcode, retdata = pvc_provisioner.profile_remove(config, name)
    cleanup(retcode, retdata)


###############################################################################
# pvc provisioner create
###############################################################################
@click.command(name='create', short_help='Create new VM.')
@click.argument(
    'name'
)
@click.argument(
    'profile'
)
@click.option(
    '-a', '--script-arg', 'script_args',
    default=[], multiple=True,
    help='Additional argument to the script install() function in key=value format.'
)
@click.option(
    '-d/-D', '--define/--no-define', 'define_flag',
    is_flag=True, default=True, show_default=True,
    help='Define the VM automatically during provisioning.'
)
@click.option(
    '-s/-S', '--start/--no-start', 'start_flag',
    is_flag=True, default=True, show_default=True,
    help='Start the VM automatically upon completion of provisioning.'
)
@click.option(
    '-w', '--wait', 'wait_flag',
    is_flag=True, default=False,
    help='Wait for provisioning to complete, showing progress'
)
@cluster_req
def provisioner_create(name, profile, wait_flag, define_flag, start_flag, script_args):
    """
    Create a new VM NAME with profile PROFILE.

    The "--no-start" flag can be used to prevent automatic startup of the VM once provisioning
    is completed. This can be useful for the administrator to preform additional actions to
    the VM after provisioning is completed. Note that the VM will remain in "provision" state
    until its state is explicitly changed (e.g. with "pvc vm start").

    The "--no-define" flag implies "--no-start", and can be used to prevent definition of the
    created VM on the PVC cluster. This can be useful for the administrator to create a "template"
    set of VM disks via the normal provisioner, but without ever starting the resulting VM. The
    resulting disk(s) can then be used as source volumes in other disk templates.

    The "--script-arg" option can be specified as many times as required to pass additional,
    VM-specific arguments to the provisioner install() function, beyond those set by the profile.
    """
    if not define_flag:
        start_flag = False

    retcode, retdata = pvc_provisioner.vm_create(config, name, profile, wait_flag, define_flag, start_flag, script_args)

    if retcode and wait_flag:
        task_id = retdata

        click.echo("Task ID: {}".format(task_id))
        click.echo()

        # Wait for the task to start
        click.echo("Waiting for task to start...", nl=False)
        while True:
            time.sleep(1)
            task_status = pvc_provisioner.task_status(config, task_id, is_watching=True)
            if task_status.get('state') != 'PENDING':
                break
            click.echo(".", nl=False)
        click.echo(" done.")
        click.echo()

        # Start following the task state, updating progress as we go
        total_task = task_status.get('total')
        with click.progressbar(length=total_task, show_eta=False) as bar:
            last_task = 0
            maxlen = 0
            while True:
                time.sleep(1)
                if task_status.get('state') != 'RUNNING':
                    break
                if task_status.get('current') > last_task:
                    current_task = int(task_status.get('current'))
                    bar.update(current_task - last_task)
                    last_task = current_task
                    # The extensive spaces at the end cause this to overwrite longer previous messages
                    curlen = len(str(task_status.get('status')))
                    if curlen > maxlen:
                        maxlen = curlen
                    lendiff = maxlen - curlen
                    overwrite_whitespace = " " * lendiff
                    click.echo("  " + task_status.get('status') + overwrite_whitespace, nl=False)
                task_status = pvc_provisioner.task_status(config, task_id, is_watching=True)
            if task_status.get('state') == 'SUCCESS':
                bar.update(total_task - last_task)

        click.echo()
        retdata = task_status.get('state') + ": " + task_status.get('status')

    cleanup(retcode, retdata)

###############################################################################
# pvc provisioner status
###############################################################################
@click.command(name='status', short_help='Show status of provisioner job.')
@click.argument(
    'job', required=False, default=None
)
@cluster_req
def provisioner_status(job):
    """
    Show status of provisioner job JOB or a list of jobs.
    """
    retcode, retdata = pvc_provisioner.task_status(config, job)
    if job is None and retcode:
        retdata = pvc_provisioner.format_list_task(retdata)
    cleanup(retcode, retdata)


###############################################################################
# pvc maintenance
###############################################################################
@click.group(name='maintenance', short_help='Manage PVC cluster maintenance state.', context_settings=CONTEXT_SETTINGS)
def cli_maintenance():
    """
    Manage the maintenance mode of the PVC cluster.
    """

###############################################################################
# pvc maintenance on
###############################################################################
@click.command(name='on', short_help='Enable cluster maintenance mode.')
@cluster_req
def maintenance_on():
    """
    Enable maintenance mode on the PVC cluster.
    """
    retcode, retdata = pvc_cluster.maintenance_mode(config, 'true')
    cleanup(retcode, retdata)

###############################################################################
# pvc maintenance off
###############################################################################
@click.command(name='off', short_help='Disable cluster maintenance mode.')
@cluster_req
def maintenance_off():
    """
    Disable maintenance mode on the PVC cluster.
    """
    retcode, retdata = pvc_cluster.maintenance_mode(config, 'false')
    cleanup(retcode, retdata)


###############################################################################
# pvc status
###############################################################################
@click.command(name='status', short_help='Show current cluster status.')
@click.option(
    '-f', '--format', 'oformat', default='plain', show_default=True,
    type=click.Choice(['plain', 'json', 'json-pretty']),
    help='Output format of cluster status information.'
)
@cluster_req
def status_cluster(oformat):
    """
    Show basic information and health for the active PVC cluster.
    """

    retcode, retdata = pvc_cluster.get_info(config)
    if retcode:
        retdata = pvc_cluster.format_info(retdata, oformat)
    cleanup(retcode, retdata)

###############################################################################
# pvc init
###############################################################################
@click.command(name='init', short_help='Initialize a new cluster.')
@click.option(
    '-y', '--yes', 'confirm_flag',
    is_flag=True, default=False,
    help='Confirm the removal'
)
@cluster_req
def init_cluster(confirm_flag):
    """
    Perform initialization of a new PVC cluster.
    """

    if not confirm_flag:
        try:
            click.confirm('Remove all existing cluster data from coordinators and initialize a new cluster'.format(name), prompt_suffix='? ', abort=True)
        except Exception:
            exit(0)

    # Easter-egg
    click.echo("Some music while we're Layin' Pipe? https://youtu.be/sw8S_Kv89IU")

    retcode, retmsg = pvc_cluster.initialize(config)
    cleanup(retcode, retmsg)

###############################################################################
# pvc
###############################################################################
@click.group(context_settings=CONTEXT_SETTINGS)
@click.option(
    '-c', '--cluster', '_cluster', envvar='PVC_CLUSTER', default=None,
    help='Zookeeper connection string.'
)
@click.option(
    '-v', '--debug', '_debug', envvar='PVC_DEBUG', is_flag=True, default=False,
    help='Additional debug details.'
)
@click.option(
    '-q', '--quiet', '_quiet', envvar='PVC_QUIET', is_flag=True, default=False,
    help='Suppress cluster connection information.'
)
def cli(_cluster, _debug, _quiet):
    """
    Parallel Virtual Cluster CLI management tool

    Environment variables:

      "PVC_CLUSTER": Set the cluster to access instead of using --cluster/-c

    If no PVC_CLUSTER/--cluster is specified, attempts first to load the "local" cluster, checking
    for an API configuration in "/etc/pvc/pvcapid.yaml". If this is also not found, abort.
    """

    global config
    store_data = get_store(store_path)
    config = get_config(store_data, _cluster)
    if not config.get('badcfg', None):
        config['debug'] = _debug

        if not _quiet:
            if config['api_scheme'] == 'https' and not config['verify_ssl']:
                ssl_unverified_msg=' (unverified)'
            else:
                ssl_unverified_msg=''
            click.echo(
                'Using cluster "{}" - Host: "{}"  Scheme: "{}{}"  Prefix: "{}"'.format(
                    config['cluster'],
                    config['api_host'],
                    config['api_scheme'],
                    ssl_unverified_msg,
                    config['api_prefix']
                ),
                err=True
            )
            click.echo('', err=True)

config = dict()

#
# Click command tree
#
cli_cluster.add_command(cluster_add)
cli_cluster.add_command(cluster_remove)
cli_cluster.add_command(cluster_list)

cli_node.add_command(node_secondary)
cli_node.add_command(node_primary)
cli_node.add_command(node_flush)
cli_node.add_command(node_ready)
cli_node.add_command(node_unflush)
cli_node.add_command(node_info)
cli_node.add_command(node_list)

cli_vm.add_command(vm_define)
cli_vm.add_command(vm_meta)
cli_vm.add_command(vm_modify)
cli_vm.add_command(vm_undefine)
cli_vm.add_command(vm_remove)
cli_vm.add_command(vm_dump)
cli_vm.add_command(vm_start)
cli_vm.add_command(vm_restart)
cli_vm.add_command(vm_shutdown)
cli_vm.add_command(vm_stop)
cli_vm.add_command(vm_disable)
cli_vm.add_command(vm_move)
cli_vm.add_command(vm_migrate)
cli_vm.add_command(vm_unmigrate)
cli_vm.add_command(vm_flush_locks)
cli_vm.add_command(vm_info)
cli_vm.add_command(vm_log)
cli_vm.add_command(vm_list)

cli_network.add_command(net_add)
cli_network.add_command(net_modify)
cli_network.add_command(net_remove)
cli_network.add_command(net_info)
cli_network.add_command(net_list)
cli_network.add_command(net_dhcp)
cli_network.add_command(net_acl)

net_dhcp.add_command(net_dhcp_list)
net_dhcp.add_command(net_dhcp_add)
net_dhcp.add_command(net_dhcp_remove)

net_acl.add_command(net_acl_add)
net_acl.add_command(net_acl_remove)
net_acl.add_command(net_acl_list)

ceph_benchmark.add_command(ceph_benchmark_run)
ceph_benchmark.add_command(ceph_benchmark_info)
ceph_benchmark.add_command(ceph_benchmark_list)

ceph_osd.add_command(ceph_osd_add)
ceph_osd.add_command(ceph_osd_remove)
ceph_osd.add_command(ceph_osd_in)
ceph_osd.add_command(ceph_osd_out)
ceph_osd.add_command(ceph_osd_set)
ceph_osd.add_command(ceph_osd_unset)
ceph_osd.add_command(ceph_osd_list)

ceph_pool.add_command(ceph_pool_add)
ceph_pool.add_command(ceph_pool_remove)
ceph_pool.add_command(ceph_pool_list)

ceph_volume.add_command(ceph_volume_add)
ceph_volume.add_command(ceph_volume_upload)
ceph_volume.add_command(ceph_volume_resize)
ceph_volume.add_command(ceph_volume_rename)
ceph_volume.add_command(ceph_volume_clone)
ceph_volume.add_command(ceph_volume_remove)
ceph_volume.add_command(ceph_volume_list)
ceph_volume.add_command(ceph_volume_snapshot)

ceph_volume_snapshot.add_command(ceph_volume_snapshot_add)
ceph_volume_snapshot.add_command(ceph_volume_snapshot_rename)
ceph_volume_snapshot.add_command(ceph_volume_snapshot_remove)
ceph_volume_snapshot.add_command(ceph_volume_snapshot_list)

cli_storage.add_command(ceph_status)
cli_storage.add_command(ceph_util)
cli_storage.add_command(ceph_benchmark)
cli_storage.add_command(ceph_osd)
cli_storage.add_command(ceph_pool)
cli_storage.add_command(ceph_volume)

provisioner_template_system.add_command(provisioner_template_system_list)
provisioner_template_system.add_command(provisioner_template_system_add)
provisioner_template_system.add_command(provisioner_template_system_modify)
provisioner_template_system.add_command(provisioner_template_system_remove)

provisioner_template_network.add_command(provisioner_template_network_list)
provisioner_template_network.add_command(provisioner_template_network_add)
provisioner_template_network.add_command(provisioner_template_network_remove)
provisioner_template_network.add_command(provisioner_template_network_vni)

provisioner_template_network_vni.add_command(provisioner_template_network_vni_add)
provisioner_template_network_vni.add_command(provisioner_template_network_vni_remove)

provisioner_template_storage.add_command(provisioner_template_storage_list)
provisioner_template_storage.add_command(provisioner_template_storage_add)
provisioner_template_storage.add_command(provisioner_template_storage_remove)
provisioner_template_storage.add_command(provisioner_template_storage_disk)

provisioner_template_storage_disk.add_command(provisioner_template_storage_disk_add)
provisioner_template_storage_disk.add_command(provisioner_template_storage_disk_remove)

provisioner_template.add_command(provisioner_template_system)
provisioner_template.add_command(provisioner_template_network)
provisioner_template.add_command(provisioner_template_storage)
provisioner_template.add_command(provisioner_template_list)

provisioner_userdata.add_command(provisioner_userdata_list)
provisioner_userdata.add_command(provisioner_userdata_show)
provisioner_userdata.add_command(provisioner_userdata_add)
provisioner_userdata.add_command(provisioner_userdata_modify)
provisioner_userdata.add_command(provisioner_userdata_remove)

provisioner_script.add_command(provisioner_script_list)
provisioner_script.add_command(provisioner_script_show)
provisioner_script.add_command(provisioner_script_add)
provisioner_script.add_command(provisioner_script_modify)
provisioner_script.add_command(provisioner_script_remove)

provisioner_ova.add_command(provisioner_ova_list)
provisioner_ova.add_command(provisioner_ova_upload)
provisioner_ova.add_command(provisioner_ova_remove)

provisioner_profile.add_command(provisioner_profile_list)
provisioner_profile.add_command(provisioner_profile_add)
provisioner_profile.add_command(provisioner_profile_modify)
provisioner_profile.add_command(provisioner_profile_remove)

cli_provisioner.add_command(provisioner_template)
cli_provisioner.add_command(provisioner_userdata)
cli_provisioner.add_command(provisioner_script)
cli_provisioner.add_command(provisioner_ova)
cli_provisioner.add_command(provisioner_profile)
cli_provisioner.add_command(provisioner_create)
cli_provisioner.add_command(provisioner_status)

cli_maintenance.add_command(maintenance_on)
cli_maintenance.add_command(maintenance_off)

cli.add_command(cli_cluster)
cli.add_command(cli_node)
cli.add_command(cli_vm)
cli.add_command(cli_network)
cli.add_command(cli_storage)
cli.add_command(cli_provisioner)
cli.add_command(cli_maintenance)
cli.add_command(status_cluster)
cli.add_command(init_cluster)


#
# Main entry point
#
def main():
    return cli(obj={})

if __name__ == '__main__':
    main()

