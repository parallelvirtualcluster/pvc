#!/usr/bin/env python3

# pvc.py - PVC client command-line interface
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

import socket
import click
import tempfile
import os
import subprocess
import difflib
import re
import colorama
import yaml
import json
import lxml.etree as etree
import requests

from distutils.util import strtobool

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
    'cfgfile': '/etc/pvc/pvc-api.yaml' # pvc/api/listen_address, pvc/api/listen_port
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
    return host, port, scheme

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
            host, port, scheme = read_from_yaml(cfgfile)
        else:
            print('No cluster specified and no local pvc-api.yaml configuration found.')
            return { 'badcfg': True }
    else:
        # This is a static configuration, get the raw details
        host = cluster_details['host']
        port = cluster_details['port']
        scheme = cluster_details['scheme']

    config = dict()
    config['debug'] = False
    config['cluster'] = cluster
    config['api_host'] = '{}:{}'.format(host, port)
    config['api_scheme'] = scheme
    config['api_prefix'] = prefix

    return config

def get_store(store_path):
    store_file = '{}/pvc-cli.json'.format(store_path)
    with open(store_file, 'r') as fh:
       store_data = json.loads(fh.read())
    return store_data

def update_store(store_path, store_data):
    store_file = '{}/pvc-cli.json'.format(store_path)
    with open(store_file, 'w') as fh:
        fh.write(json.dumps(store_data, sort_keys=True, indent=4))

home_dir = os.environ.get('HOME', None)
if home_dir:
    store_path = '{}/.config/pvc'.format(home_dir)
else:
    print('No home dir found - not permanently saving any configurations as this user')
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
@click.argument(
    'name'
)
def cluster_add(address, port, ssl, name):
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
        'scheme': scheme
    }
    # Update the store
    update_store(store_path, existing_config)

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
    scheme_length = 5

    for cluster in clusters:
        cluster_details = clusters[cluster]
        if cluster_details.get('cfgfile', None):
            # This is a reference to an API configuration; grab the details from its listen address
            cfgfile = cluster_details.get('cfgfile')
            if os.path.isfile(cfgfile):
                address, port, scheme = read_from_yaml(cfgfile)
        else:
            address = cluster_details.get('host', None)
            port = cluster_details.get('port', None)
            scheme = cluster_details.get('scheme', None)

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

    # Display the data nicely
    click.echo("Available clusters:")
    click.echo()
    click.echo(
        '{bold}{name: <{name_length}} {address: <{address_length}} {port: <{port_length}} {scheme: <{scheme_length}}{end_bold}'.format(
            bold=ansiprint.bold(),
            end_bold=ansiprint.end(),
            name="Name",
            name_length=name_length,
            address="Address",
            address_length=address_length,
            port="Port",
            port_length=port_length,
            scheme="Scheme",
            scheme_length=scheme_length
        )
    )

    for cluster in clusters:
        cluster_details = clusters[cluster]
        if cluster_details.get('cfgfile', None):
            # This is a reference to an API configuration; grab the details from its listen address
            cfgfile = cluster_details.get('cfgfile')
            if os.path.isfile(cfgfile):
                address, port, scheme = read_from_yaml(cfgfile)
        else:
            address = cluster_details.get('host', None)
            port = cluster_details.get('port', None)
            scheme = cluster_details.get('scheme', None)

        click.echo(
            '{bold}{name: <{name_length}} {address: <{address_length}} {port: <{port_length}} {scheme: <{scheme_length}}{end_bold}'.format(
                bold='',
                end_bold='',
                name=cluster,
                name_length=name_length,
                address=address,
                address_length=address_length,
                port=port,
                port_length=port_length,
                scheme=scheme,
                scheme_length=scheme_length
            )
        )


###############################################################################
# pvc node
###############################################################################
@click.group(name='node', short_help='Manage a PVC node.', context_settings=CONTEXT_SETTINGS)
def cli_node():
    """
    Manage the state of a node in the PVC cluster.
    """
    # Abort commands under this group if config is bad
    if config.get('badcfg', None):
        exit(1)

###############################################################################
# pvc node secondary
###############################################################################
@click.command(name='secondary', short_help='Set a node in secondary node status.')
@click.argument(
    'node'
)
def node_secondary(node):
    """
    Take NODE out of primary router mode.
    """

    retcode, retmsg = pvc_node.node_coordinator_state(config, node, 'secondary')
    cleanup(retcode, retmsg)

###############################################################################
# pvc node primary
###############################################################################
@click.command(name='primary', short_help='Set a node in primary status.')
@click.argument(
    'node'
)
def node_primary(node):
    """
    Put NODE into primary router mode.
    """

    retcode, retmsg = pvc_node.node_coordinator_state(config, node, 'primary')
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
def node_info(node, long_output):
    """
    Show information about node NODE. If unspecified, defaults to this host.
    """

    retcode, retdata = pvc_node.node_info(config, node)
    if retcode:
        pvc_node.format_info(retdata, long_output)
        retdata = ''
    cleanup(retcode, retdata)

###############################################################################
# pvc node list
###############################################################################
@click.command(name='list', short_help='List all node objects.')
@click.argument(
    'limit', default=None, required=False
)
def node_list(limit):
    """
    List all nodes in the cluster; optionally only match names matching regex LIMIT.
    """

    retcode, retdata = pvc_node.node_list(config, limit)
    if retcode:
        pvc_node.format_list(retdata)
        retdata = ''
    cleanup(retcode, retdata)

###############################################################################
# pvc vm
###############################################################################
@click.group(name='vm', short_help='Manage a PVC virtual machine.', context_settings=CONTEXT_SETTINGS)
def cli_vm():
    """
    Manage the state of a virtual machine in the PVC cluster.
    """
    # Abort commands under this group if config is bad
    if config.get('badcfg', None):
        exit(1)

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
@click.argument(
    'config', type=click.File()
)
def vm_define(config, target_node, node_limit, node_selector, node_autostart):
    """
    Define a new virtual machine from Libvirt XML configuration file CONFIG.
    """

    # Open the XML file
    config_data = config.read()
    config.close()

    retcode, retmsg = pvc_vm.define_vm(config, config_data, target_node, node_limit, node_selector, node_autostart)
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
@click.argument(
    'domain'
)
def vm_meta(domain, node_limit, node_selector, node_autostart):
    """
    Modify the PVC metadata of existing virtual machine DOMAIN. At least one option to update must be specified. DOMAIN may be a UUID or name.
    """

    if node_limit is None and node_selector is None and node_autostart is None:
        cleanup(False, 'At least one metadata option must be specified to update.')

    retcode, retmsg = pvc_vm.vm_metadata(config, domain, node_limit, node_selector, node_autostart)
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
        cleanup(False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain))

    dom_uuid = vm_information.get('uuid')
    dom_name = vm_information.get('name')

    if editor == True:
        # Grab the current config
        current_vm_cfg_raw = vm_information.get('xml')
        xml_data = etree.fromstring(current_vm_cfg_raw)
        current_vm_cfgfile = etree.tostring(xml_data, pretty_print=True).decode('utf8')

        # Write it to a tempfile
        fd, path = tempfile.mkstemp()
        fw = os.fdopen(fd, 'w')
        fw.write(current_vm_cfgfile.strip())
        fw.close()

        # Edit it
        editor = os.getenv('EDITOR', 'vi')
        subprocess.call('%s %s' % (editor, path), shell=True)

        # Open the tempfile to read
        with open(path, 'r') as fr:
            new_vm_cfgfile = fr.read()
            fr.close()

        # Delete the tempfile
        os.unlink(path)

        # Show a diff and confirm
        diff = list(difflib.unified_diff(current_vm_cfgfile.split('\n'), new_vm_cfgfile.split('\n'), fromfile='current', tofile='modified', fromfiledate='', tofiledate='', n=3, lineterm=''))
        if len(diff) < 1:
            click.echo('Aborting with no modifications.')
            exit(0)

        click.echo('Pending modifications:')
        click.echo('')
        for line in diff:
            if re.match('^\+', line) != None:
                click.echo(colorama.Fore.GREEN + line + colorama.Fore.RESET)
            elif re.match('^\-', line) != None:
                click.echo(colorama.Fore.RED + line + colorama.Fore.RESET)
            elif re.match('^\^', line) != None:
                click.echo(colorama.Fore.BLUE + line + colorama.Fore.RESET)
            else:
                click.echo(line)
        click.echo('')

        click.confirm('Write modifications to Zookeeper?', abort=True)

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

    retcode, retmsg = pvc_vm.vm_modify(config, domain, new_vm_config, restart)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm undefine
###############################################################################
@click.command(name='undefine', short_help='Undefine a virtual machine.')
@click.argument(
    'domain'
)
def vm_undefine(domain):
    """
    Stop virtual machine DOMAIN and remove it from the cluster database, preserving disks. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc_vm.vm_remove(config, domain, delete_disks=False)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm remove
###############################################################################
@click.command(name='remove', short_help='Remove a virtual machine.')
@click.argument(
    'domain'
)
def vm_remove(domain):
    """
    Stop virtual machine DOMAIN and remove it, along with all disks, from the cluster. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc_vm.vm_remove(config, domain, delete_disks=True)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm start
###############################################################################
@click.command(name='start', short_help='Start up a defined virtual machine.')
@click.argument(
    'domain'
)
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
def vm_restart(domain):
    """
    Restart running virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc_vm.vm_state(config, domain, 'restart')
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm shutdown
###############################################################################
@click.command(name='shutdown', short_help='Gracefully shut down a running virtual machine.')
@click.argument(
	'domain'
)
def vm_shutdown(domain):
    """
    Gracefully shut down virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc_vm.vm_state(config, domain, 'shutdown')
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm stop
###############################################################################
@click.command(name='stop', short_help='Forcibly halt a running virtual machine.')
@click.argument(
    'domain'
)
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
def vm_move(domain, target_node):
    """
    Permanently move virtual machine DOMAIN, via live migration if running and possible, to another node. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc_vm.vm_node(config, domain, target_node, 'move', force=False)
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
def vm_migrate(domain, target_node, force_migrate):
    """
    Temporarily migrate running virtual machine DOMAIN, via live migration if possible, to another node. DOMAIN may be a UUID or name. If DOMAIN is not running, it will be started on the target node.
    """

    retcode, retmsg = pvc_vm.vm_node(config, domain, target_node, 'migrate', force=force_migrate)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm unmigrate
###############################################################################
@click.command(name='unmigrate', short_help='Restore a migrated virtual machine to its original node.')
@click.argument(
    'domain'
)
def vm_unmigrate(domain):
    """
    Restore previously migrated virtual machine DOMAIN, via live migration if possible, to its original node. DOMAIN may be a UUID or name. If DOMAIN is not running, it will be started on the target node.
    """

    retcode, retmsg = pvc_vm.vm_node(config, domain, None, 'unmigrate', force=False)
    cleanup(retcode, retmsg)

###############################################################################
# pvc vm flush-locks
###############################################################################
@click.command(name='flush-locks', short_help='Flush stale RBD locks for a virtual machine.')
@click.argument(
    'domain'
)
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
    '-l', '--lines', 'lines', default=100, show_default=True,
    help='Display this many log lines from the end of the log buffer.'
)
@click.option(
    '-f', '--follow', 'follow', is_flag=True, default=False,
    help='Follow the log buffer; output may be delayed by a few seconds relative to the live system. The --lines value defaults to 10 for the initial output.'
)
def vm_log(domain, lines, follow):
    """
	Show console logs of virtual machine DOMAIN on its current node in the 'less' pager or continuously. DOMAIN may be a UUID or name. Note that migrating a VM to a different node will cause the log buffer to be overwritten by entries from the new node.
    """

    if follow:
        retcode, retmsg = pvc_vm.follow_console_log(config, domain, lines)
    else:
        retcode, retmsg = pvc_vm.view_console_log(config, domain, lines)
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
def vm_info(domain, long_output):
    """
	Show information about virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    retcode, retdata = pvc_vm.vm_info(config, domain)
    if retcode:
        pvc_vm.format_info(config, retdata, long_output)
        retdata = ''
    cleanup(retcode, retdata)

###############################################################################
# pvc vm dump
###############################################################################
@click.command(name='dump', short_help='Dump a virtual machine XML to stdout.')
@click.argument(
    'domain'
)
def vm_dump(domain):
    """
    Dump the Libvirt XML definition of virtual machine DOMAIN to stdout. DOMAIN may be a UUID or name.
    """

    retcode, vm_information = pvc_vm.vm_info(config, domain)
    if not retcode and not vm_information.get('name', None):
        cleanup(False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain))

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
def vm_list(target_node, target_state, limit, raw):
    """
    List all virtual machines in the cluster; optionally only match names matching regex LIMIT.

    NOTE: Red-coloured network lists indicate one or more configured networks are missing/invalid.
    """

    retcode, retdata = pvc_vm.vm_list(config, limit, target_node, target_state)
    if retcode:
        pvc_vm.format_list(config, retdata, raw)
        retdata = ''
    cleanup(retcode, retdata)

###############################################################################
# pvc network
###############################################################################
@click.group(name='network', short_help='Manage a PVC virtual network.', context_settings=CONTEXT_SETTINGS)
def cli_network():
    """
    Manage the state of a VXLAN network in the PVC cluster.
    """
    # Abort commands under this group if config is bad
    if config.get('badcfg', None):
        exit(1)

###############################################################################
# pvc network add
###############################################################################
@click.command(name='add', short_help='Add a new virtual network to the cluster.')
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
def net_add(vni, description, nettype, domain, ip_network, ip_gateway, ip6_network, ip6_gateway, dhcp_flag, dhcp_start, dhcp_end, name_servers):
    """
    Add a new virtual network with VXLAN identifier VNI to the cluster.

    Examples:

    pvc network add 101 --type bridged

      > Creates vLAN 101 and a simple bridge on the VNI dev interface.

    pvc network add 1001 --type managed --domain test.local --ipnet 10.1.1.0/24 --gateway 10.1.1.1

      > Creates a VXLAN with ID 1001 on the VNI dev interface, with IPv4 managed networking.

    IPv6 is fully supported with --ipnet6 and --gateway6 in addition to or instead of IPv4. PVC will configure DHCPv6 in a semi-managed configuration for the network if set.
    """

    if nettype == 'managed' and not ip_network and not ip6_network:
        click.echo('Error: At least one of "-i" / "--ipnet" or "-i6" / "--ipnet6" must be specified.')
        exit(1)

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
@click.command(name='remove', short_help='Remove a virtual network from the cluster.')
@click.argument(
    'net'
)
def net_remove(net):
    """
    Remove an existing virtual network NET from the cluster; NET must be a VNI.

    WARNING: PVC does not verify whether clients are still present in this network. Before removing, ensure
    that all client VMs have been removed from the network or undefined behaviour may occur.
    """

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
def net_info(vni, long_output):
    """
	Show information about virtual network VNI.
    """

    retcode, retdata = pvc_network.net_info(config, vni)
    if retcode:
        pvc_network.format_info(config, retdata, long_output)
        retdata = ''
    cleanup(retcode, retdata)

###############################################################################
# pvc network list
###############################################################################
@click.command(name='list', short_help='List all VM objects.')
@click.argument(
    'limit', default=None, required=False
)
def net_list(limit):
    """
    List all virtual networks in the cluster; optionally only match VNIs or Descriptions matching regex LIMIT.
    """

    retcode, retdata = pvc_network.net_list(config, limit)
    if retcode:
        pvc_network.format_list(config, retdata)
        retdata = ''
    cleanup(retcode, retdata)

###############################################################################
# pvc network dhcp
###############################################################################
@click.group(name='dhcp', short_help='Manage IPv4 DHCP leases in a PVC virtual network.', context_settings=CONTEXT_SETTINGS)
def net_dhcp():
    """
    Manage host IPv4 DHCP leases of a VXLAN network in the PVC cluster.
    """
    # Abort commands under this group if config is bad
    if config.get('badcfg', None):
        exit(1)

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
def net_dhcp_remove(net, reservation):
    """
    Remove a DHCP static reservation for MACADDR from virtual network NET; NET must be a VNI.
    """

    retcode, retmsg = pvc_network.net_dhcp_remove(config, net, reservation)
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
def net_dhcp_list(net, limit, only_static):
    """
    List all DHCP leases in virtual network NET; optionally only match elements matching regex LIMIT; NET must be a VNI.
    """

    retcode, retdata = pvc_network.net_dhcp_list(config, net, limit, only_static)
    if retcode:
        pvc_network.format_list_dhcp(retdata)
        retdata = ''
    cleanup(retcode, retdata)

###############################################################################
# pvc network acl
###############################################################################
@click.group(name='acl', short_help='Manage a PVC virtual network firewall ACL rule.', context_settings=CONTEXT_SETTINGS)
def net_acl():
    """
    Manage firewall ACLs of a VXLAN network in the PVC cluster.
    """
    # Abort commands under this group if config is bad
    if config.get('badcfg', None):
        exit(1)

###############################################################################
# pvc network acl add
###############################################################################
@click.command(name='add', short_help='Add firewall ACL.')
@click.option(
    '--in/--out', 'direction',
    is_flag=True,
    default=True, #inbound
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
def net_acl_remove(net, rule):
    """
    Remove an NFT firewall rule RULE from network NET; RULE must be a description; NET must be a VNI.
    """

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
        pvc_network.format_list_acl(retdata)
        retdata = ''
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
    # Abort commands under this group if config is bad
    if config.get('badcfg', None):
        exit(1)

###############################################################################
# pvc storage ceph
###############################################################################
@click.group(name='ceph', short_help='Manage the PVC Ceph storage cluster.', context_settings=CONTEXT_SETTINGS)
def cli_ceph():
    """
    Manage the Ceph storage of the PVC cluster.

    NOTE: The PVC Ceph interface is limited to the most common tasks. Any other administrative tasks must be performed on a node directly.
    """
    # Abort commands under this group if config is bad
    if config.get('badcfg', None):
        exit(1)

###############################################################################
# pvc storage ceph status
###############################################################################
@click.command(name='status', short_help='Show storage cluster status.')
def ceph_status():
    """
    Show detailed status of the storage cluster.
    """

    retcode, retdata = pvc_ceph.ceph_status(config)
    if retcode:
        pvc_ceph.format_raw_output(retdata)
        retdata = ''
    cleanup(retcode, retdata)

###############################################################################
# pvc storage ceph util
###############################################################################
@click.command(name='util', short_help='Show storage cluster utilization.')
def ceph_util():
    """
    Show utilization of the storage cluster.
    """

    retcode, retdata = pvc_ceph.ceph_util(config)
    if retcode:
        pvc_ceph.format_raw_output(retdata)
        retdata = ''
    cleanup(retcode, retdata)

###############################################################################
# pvc storage ceph osd
###############################################################################
@click.group(name='osd', short_help='Manage OSDs in the PVC storage cluster.', context_settings=CONTEXT_SETTINGS)
def ceph_osd():
    """
    Manage the Ceph OSDs of the PVC cluster.
    """
    # Abort commands under this group if config is bad
    if config.get('badcfg', None):
        exit(1)

###############################################################################
# pvc storage ceph osd add
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
    '--yes', 'yes',
    is_flag=True, default=False,
    help='Pre-confirm the disk destruction.'
)
def ceph_osd_add(node, device, weight, yes):
    """
    Add a new Ceph OSD on node NODE with block device DEVICE to the cluster.
    """

    if not yes:
        click.echo('DANGER: This will completely destroy all data on {} disk {}.'.format(node, device))
        choice = input('Are you sure you want to do this? (y/N) ')
        if choice != 'y' and choice != 'Y':
            exit(0)

    retcode, retmsg = pvc_ceph.ceph_osd_add(config, node, device, weight)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage ceph osd remove
###############################################################################
@click.command(name='remove', short_help='Remove OSD.')
@click.argument(
    'osdid'
)
@click.option(
    '--yes', 'yes',
    is_flag=True, default=False,
    help='Pre-confirm the removal.'
)
def ceph_osd_remove(osdid, yes):
    """
    Remove a Ceph OSD with ID OSDID from the cluster.
    """

    if not yes:
        click.echo('DANGER: This will completely remove OSD {} from cluster. OSDs will rebalance.'.format(osdid))
        choice = input('Are you sure you want to do this? (y/N) ')
        if choice != 'y' and choice != 'Y':
            exit(0)

    retcode, retmsg = pvc_ceph.ceph_osd_remove(config, osdid)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage ceph osd in
###############################################################################
@click.command(name='in', short_help='Online OSD.')
@click.argument(
    'osdid'
)
def ceph_osd_in(osdid):
    """
    Set a Ceph OSD with ID OSDID online in the cluster.
    """

    retcode, retmsg = pvc_ceph.ceph_osd_state(config, osdid, 'in')
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage ceph osd out
###############################################################################
@click.command(name='out', short_help='Offline OSD.')
@click.argument(
    'osdid'
)
def ceph_osd_out(osdid):
    """
    Set a Ceph OSD with ID OSDID offline in the cluster.
    """

    retcode, retmsg = pvc_ceph.ceph_osd_state(config, osdid, 'out')
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage ceph osd set
###############################################################################
@click.command(name='set', short_help='Set property.')
@click.argument(
    'osd_property'
)
def ceph_osd_set(osd_property):
    """
    Set a Ceph OSD property OSD_PROPERTY on the cluster.

    Valid properties are:

      full|pause|noup|nodown|noout|noin|nobackfill|norebalance|norecover|noscrub|nodeep-scrub|notieragent|sortbitwise|recovery_deletes|require_jewel_osds|require_kraken_osds 
    """

    retcode, retmsg = pvc_ceph.ceph_osd_option(config, osd_property, 'set')
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage ceph osd unset
###############################################################################
@click.command(name='unset', short_help='Unset property.')
@click.argument(
    'osd_property'
)
def ceph_osd_unset(osd_property):
    """
    Unset a Ceph OSD property OSD_PROPERTY on the cluster.

    Valid properties are:

      full|pause|noup|nodown|noout|noin|nobackfill|norebalance|norecover|noscrub|nodeep-scrub|notieragent|sortbitwise|recovery_deletes|require_jewel_osds|require_kraken_osds 
    """

    retcode, retmsg = pvc_ceph.ceph_osd_option(config, osd_property, 'unset')
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage ceph osd list
###############################################################################
@click.command(name='list', short_help='List cluster OSDs.')
@click.argument(
    'limit', default=None, required=False
)
def ceph_osd_list(limit):
    """
    List all Ceph OSDs in the cluster; optionally only match elements matching ID regex LIMIT.
    """

    retcode, retdata = pvc_ceph.ceph_osd_list(config, limit)
    if retcode:
        pvc_ceph.format_list_osd(retdata)
        retdata = ''
    cleanup(retcode, retdata)

###############################################################################
# pvc storage ceph pool
###############################################################################
@click.group(name='pool', short_help='Manage RBD pools in the PVC storage cluster.', context_settings=CONTEXT_SETTINGS)
def ceph_pool():
    """
    Manage the Ceph RBD pools of the PVC cluster.
    """
    # Abort commands under this group if config is bad
    if config.get('badcfg', None):
        exit(1)

###############################################################################
# pvc storage ceph pool add
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
def ceph_pool_add(name, pgs, replcfg):
    """
    Add a new Ceph RBD pool with name NAME and PGS placement groups.

    """

    retcode, retmsg = pvc_ceph.ceph_pool_add(config, name, pgs, replcfg)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage ceph pool remove
###############################################################################
@click.command(name='remove', short_help='Remove RBD pool.')
@click.argument(
    'name'
)
@click.option(
    '--yes', 'yes',
    is_flag=True, default=False,
    help='Pre-confirm the removal.'
)
def ceph_pool_remove(name, yes):
    """
    Remove a Ceph RBD pool with name NAME and all volumes on it.
    """

    if not yes:
        click.echo('DANGER: This will completely remove pool {} and all data contained in it.'.format(name))
        choice = input('Are you sure you want to do this? (y/N) ')
        if choice != 'y' and choice != 'Y':
            pool_name_check = input('Please enter the pool name to confirm: ')
            if pool_name_check != name:
                exit(0)

    retcode, retmsg = pvc_ceph.ceph_pool_remove(config, name)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage ceph pool list
###############################################################################
@click.command(name='list', short_help='List cluster RBD pools.')
@click.argument(
    'limit', default=None, required=False
)
def ceph_pool_list(limit):
    """
    List all Ceph RBD pools in the cluster; optionally only match elements matching name regex LIMIT.
    """

    retcode, retdata = pvc_ceph.ceph_pool_list(config, limit)
    if retcode:
        pvc_ceph.format_list_pool(retdata)
        retdata = ''
    cleanup(retcode, retdata)

###############################################################################
# pvc storage ceph volume
###############################################################################
@click.group(name='volume', short_help='Manage RBD volumes in the PVC storage cluster.', context_settings=CONTEXT_SETTINGS)
def ceph_volume():
    """
    Manage the Ceph RBD volumes of the PVC cluster.
    """
    # Abort commands under this group if config is bad
    if config.get('badcfg', None):
        exit(1)

###############################################################################
# pvc storage ceph volume add
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
def ceph_volume_add(pool, name, size):
    """
    Add a new Ceph RBD volume with name NAME and size SIZE [in human units, e.g. 1024M, 20G, etc.] to pool POOL.
    """

    retcode, retmsg = pvc_ceph.ceph_volume_add(config, pool, name, size)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage ceph volume remove
###############################################################################
@click.command(name='remove', short_help='Remove RBD volume.')
@click.argument(
    'pool'
)
@click.argument(
    'name'
)
@click.option(
    '--yes', 'yes',
    is_flag=True, default=False,
    help='Pre-confirm the removal.'
)
def ceph_volume_remove(pool, name, yes):
    """
    Remove a Ceph RBD volume with name NAME from pool POOL.
    """

    if not yes:
        click.echo('DANGER: This will completely remove volume {} from pool {} and all data contained in it.'.format(name, pool))
        choice = input('Are you sure you want to do this? (y/N) ')
        if choice != 'y' and choice != 'Y':
            exit(0)

    retcode, retmsg = pvc_ceph.ceph_volume_remove(config, pool, name)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage ceph volume resize
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
def ceph_volume_resize(pool, name, size):
    """
    Resize an existing Ceph RBD volume with name NAME in pool POOL to size SIZE [in human units, e.g. 1024M, 20G, etc.].
    """
    retcode, retmsg = pvc_ceph.ceph_volume_modify(config, pool, name, new_size=size)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage ceph volume rename
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
def ceph_volume_rename(pool, name, new_name):
    """
    Rename an existing Ceph RBD volume with name NAME in pool POOL to name NEW_NAME.
    """
    retcode, retmsg = pvc_ceph.ceph_volume_modify(config, pool, name, new_name=new_name)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage ceph volume clone
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
def ceph_volume_clone(pool, name, new_name):
    """
    Clone a Ceph RBD volume with name NAME in pool POOL to name NEW_NAME in pool POOL.
    """
    retcode, retmsg = pvc_ceph.ceph_volume_clone(config, pool, name, new_name)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage ceph volume list
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
def ceph_volume_list(limit, pool):
    """
    List all Ceph RBD volumes in the cluster; optionally only match elements matching name regex LIMIT.
    """

    retcode, retdata = pvc_ceph.ceph_volume_list(config, limit, pool)
    if retcode:
        pvc_ceph.format_list_volume(retdata)
        retdata = ''
    cleanup(retcode, retdata)

###############################################################################
# pvc storage ceph volume snapshot
###############################################################################
@click.group(name='snapshot', short_help='Manage RBD volume snapshots in the PVC storage cluster.', context_settings=CONTEXT_SETTINGS)
def ceph_volume_snapshot():
    """
    Manage the Ceph RBD volume snapshots of the PVC cluster.
    """
    # Abort commands under this group if config is bad
    if config.get('badcfg', None):
        exit(1)

###############################################################################
# pvc storage ceph volume snapshot add
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
def ceph_volume_snapshot_add(pool, volume, name):
    """
    Add a snapshot with name NAME of Ceph RBD volume VOLUME in pool POOL.
    """

    retcode, retmsg = pvc_ceph.ceph_snapshot_add(config, pool, volume, name)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage ceph volume snapshot rename
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
def ceph_volume_snapshot_rename(pool, volume, name, new_name):
    """
    Rename an existing Ceph RBD volume snapshot with name NAME to name NEW_NAME for volume VOLUME in pool POOL.
    """
    retcode, retmsg = pvc_ceph.ceph_snapshot_modify(config, pool, volume, name, new_name=new_name)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage ceph volume snapshot remove
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
    '--yes', 'yes',
    is_flag=True, default=False,
    help='Pre-confirm the removal.'
)
def ceph_volume_snapshot_remove(pool, volume, name, yes):
    """
    Remove a Ceph RBD volume snapshot with name NAME from volume VOLUME in pool POOL.
    """

    if not yes:
        click.echo('DANGER: This will completely remove snapshot {} from volume {}/{} and all data contained in it.'.format(name, pool, volume))
        choice = input('Are you sure you want to do this? (y/N) ')
        if choice != 'y' and choice != 'Y':
            exit(0)

    retcode, retmsg = pvc_ceph.ceph_snapshot_remove(config, pool, volume, name)
    cleanup(retcode, retmsg)

###############################################################################
# pvc storage ceph volume snapshot list
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
    '-p', '--volume', 'volume',
    default=None, show_default=True,
    help='Show snapshots from this volume only.'
)
def ceph_volume_snapshot_list(pool, volume, limit):
    """
    List all Ceph RBD volume snapshots; optionally only match elements matching name regex LIMIT.
    """

    retcode, retdata = pvc_ceph.ceph_snapshot_list(config, limit, volume, pool)
    if retcode:
        pvc_ceph.format_list_snapshot(retdata)
        retdata = ''
    cleanup(retcode, retdata)


###############################################################################
# pvc provisioner
###############################################################################
@click.group(name='provisioner', short_help='Manage PVC provisioner.', context_settings=CONTEXT_SETTINGS)
def cli_provisioner():
    """
    Manage the PVC provisioner.
    """
    # Abort commands under this group if config is bad
    if config.get('badcfg', None):
        exit(1)

###############################################################################
# pvc provisioner template
###############################################################################
@click.group(name='template', short_help='Manage PVC provisioner templates.', context_settings=CONTEXT_SETTINGS)
def provisioner_template():
    """
    Manage the PVC provisioner template system.
    """
    # Abort commands under this group if config is bad
    if config.get('badcfg', None):
        exit(1)


###############################################################################
# pvc provisioner template list
###############################################################################
@click.command(name='list', short_help='List all templates in the cluster.')
@click.argument(
    'limit', default=None, required=False
)
def template_list(limit):
    """
    List all templates in the PVC cluster provisioner.
    """
    retcode, retdata = pvc_provisioner.template_list(config, limit)
    if retcode:
        pvc_provisioner.format_list_template(retdata)
        retdata = ''
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
def status_cluster(oformat):
    """
    Show basic information and health for the active PVC cluster.
    """
    retcode, retdata = pvc_cluster.get_info(config)
    if retcode:
        pvc_cluster.format_info(retdata, oformat)
        retdata = ''
    cleanup(retcode, retdata)

###############################################################################
# pvc init
###############################################################################
@click.command(name='init', short_help='Initialize a new cluster.')
@click.option(
    '--yes', 'yes',
    is_flag=True, default=False,
    help='Pre-confirm the initialization.'
)
def init_cluster(yes):
    """
    Perform initialization of a new PVC cluster.
    """

    if not yes:
        click.echo('DANGER: This will remove any existing cluster on these coordinators and create a new cluster. Any existing resources on the old cluster will be left abandoned.')
        choice = input('Are you sure you want to do this? (y/N) ')
        if choice != 'y' and choice != 'Y':
            exit(0)

    click.echo('Initializing a new cluster with Zookeeper address "{}".'.format(zk_host))

    # Easter-egg
    click.echo("Some music while we're Layin' Pipe? https://youtu.be/sw8S_Kv89IU")

    retcode, retmsg = pvc_cluster.initialize()
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
def cli(_cluster, _debug):
    """
    Parallel Virtual Cluster CLI management tool

    Environment variables:

      "PVC_CLUSTER": Set the cluster to access instead of using --cluster/-c

    If no PVC_CLUSTER/--cluster is specified, attempts first to load the "local" cluster, checking
    for an API configuration in "/etc/pvc/pvc-api.yaml". If this is also not found, connection defaults
    to "http://localhost:7370" as a last restort.
    """

    global config
    store_data = get_store(store_path)
    config = get_config(store_data, _cluster)
    if not config.get('badcfg', None):
        config['debug'] = _debug
        click.echo('Using cluster "{}" - Host: "{}"  Scheme: "{}"  Prefix: "{}"'.format(config['cluster'], config['api_host'], config['api_scheme'], config['api_prefix']))
    click.echo()

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

cli_ceph.add_command(ceph_status)
cli_ceph.add_command(ceph_util)
cli_ceph.add_command(ceph_osd)
cli_ceph.add_command(ceph_pool)
cli_ceph.add_command(ceph_volume)

cli_storage.add_command(cli_ceph)

provisioner_template.add_command(template_list)

cli_provisioner.add_command(provisioner_template)

cli.add_command(cli_cluster)
cli.add_command(cli_node)
cli.add_command(cli_vm)
cli.add_command(cli_network)
cli.add_command(cli_storage)
cli.add_command(cli_provisioner)
cli.add_command(status_cluster)
cli.add_command(init_cluster)


#
# Main entry point
#
def main():
    return cli(obj={})

if __name__ == '__main__':
    main()

