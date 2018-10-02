#!/usr/bin/env python3

# pvcd.py - PVC client command-line interface
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

import socket
import click
import tempfile
import os
import subprocess
import difflib
import re
import colorama

import client_lib.common as pvc_common
import client_lib.node as pvc_node
import client_lib.router as pvc_router
import client_lib.vm as pvc_vm
import client_lib.network as pvc_network

myhostname = socket.gethostname()
zk_host = ''

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'], max_content_width=120)

def cleanup(retcode, retmsg, zk_conn):
    pvc_common.stopZKConnection(zk_conn)
    if retcode == True:
        if retmsg != '':
            click.echo(retmsg)
        exit(0)
    else:
        if retmsg != '':
            click.echo(retmsg)
        exit(1)

###############################################################################
# pvc node
###############################################################################
@click.group(name='node', short_help='Manage a PVC hypervisor node.', context_settings=CONTEXT_SETTINGS)
def cli_node():
    """
    Manage the state of a node in the PVC cluster.
    """
    pass


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
    
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_node.flush_node(zk_conn, node, wait)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc node ready/unflush
###############################################################################
@click.command(name='ready', short_help='Restore node to service.')
@click.argument(
    'node', default=myhostname
)
def node_ready(node):
    """
    Restore NODE to active service and migrate back all VMs. If unspecified, defaults to this host.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_node.ready_node(zk_conn, node)
    cleanup(retcode, retmsg, zk_conn)

@click.command(name='unflush', short_help='Restore node to service.')
@click.argument(
    'node', default=myhostname
)
def node_unflush(node):
    """
    Restore NODE to active service and migrate back all VMs. If unspecified, defaults to this host.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_node.ready_node(zk_conn, node)
    cleanup(retcode, retmsg, zk_conn)

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

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_node.get_info(zk_conn, node, long_output)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc node list
###############################################################################
@click.command(name='list', short_help='List all node objects.')
@click.argument(
    'limit', default=None, required=False
)
def node_list(limit):
    """
    List all hypervisor nodes in the cluster; optionally only match names matching regex LIMIT.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_node.get_list(zk_conn, limit)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc router
###############################################################################
@click.group(name='router', short_help='Manage a PVC router.', context_settings=CONTEXT_SETTINGS)
def cli_router():
    """
    Manage the state of a router in the PVC cluster.
    """
    pass


###############################################################################
# pvc router secondary
###############################################################################
@click.command(name='secondary', short_help='Set a router in secondary status.')
@click.argument(
    'router'
)
def router_secondary(router):
    """
    Take ROUTER out of primary mode handling gateways and into secondary mode.
    """
    
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_router.secondary_router(zk_conn, router)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc router primary
###############################################################################
@click.command(name='primary', short_help='Set a router in primary status.')
@click.argument(
    'router'
)
def router_primary(router):
    """
    Put ROUTER into primary mode handling gateways.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_router.primary_router(zk_conn, router)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc router info
###############################################################################
@click.command(name='info', short_help='Show details of a router object.')
@click.argument(
    'router'
)
@click.option(
    '-l', '--long', 'long_output', is_flag=True, default=False,
    help='Display more detailed information.'
)
def router_info(router, long_output):
    """
    Show information about router ROUTER.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_router.get_info(zk_conn, router, long_output)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc router list
###############################################################################
@click.command(name='list', short_help='List all router objects.')
@click.argument(
    'limit', default=None, required=False
)
def router_list(limit):
    """
    List all routers in the cluster; optionally only match names matching regex LIMIT.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_router.get_list(zk_conn, limit)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc vm
###############################################################################
@click.group(name='vm', short_help='Manage a PVC virtual machine.', context_settings=CONTEXT_SETTINGS)
def cli_vm():
    """
    Manage the state of a virtual machine in the PVC cluster.
    """
    pass

###############################################################################
# pvc vm define
###############################################################################
@click.command(name='define', short_help='Define a new virtual machine from a Libvirt XML file.')
@click.option(
    '-t', '--hypervisor', 'target_hypervisor',
    help='Home hypervisor for this domain; autodetect if unspecified.'
)
@click.option(
    '-s', '--selector', 'selector', default='mem', show_default=True,
    type=click.Choice(['mem','load','vcpus','vms']),
    help='Method to determine optimal target hypervisor during autodetect.'
)
@click.argument(
    'config', type=click.File()
)
def vm_define(config, target_hypervisor, selector):
    """
    Define a new virtual machine from Libvirt XML configuration file CONFIG.
    """

    # Open the XML file
    config_data = config.read()
    config.close()

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_vm.define_vm(zk_conn, config_data, target_hypervisor, selector)
    cleanup(retcode, retmsg, zk_conn)

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
    'config', type=click.File(), default=None, required=False
)
def vm_modify(domain, config, editor, restart):
    """
    Modify existing virtual machine DOMAIN, either in-editor or with replacement CONFIG. DOMAIN may be a UUID or name.
    """

    if editor == False and config == None:
        cleanup(False, 'Either an XML config file or the "--editor" option must be specified.')

    zk_conn = pvc_common.startZKConnection(zk_host)

    if editor == True:
        dom_uuid = pvc_vm.getDomainUUID(zk_conn, domain)
        if dom_uuid == None:
            cleanup(False, 'ERROR: Could not find VM "{}" in the cluster!'.format(domain))
        dom_name = pvc_vm.getDomainName(zk_conn, dom_uuid)

        # Grab the current config
        current_vm_config = zk_conn.get('/domains/{}/xml'.format(dom_uuid))[0].decode('ascii')

        # Write it to a tempfile
        fd, path = tempfile.mkstemp()
        fw = os.fdopen(fd, 'w')
        fw.write(current_vm_config)
        fw.close()

        # Edit it
        editor = os.getenv('EDITOR', 'vi')
        subprocess.call('%s %s' % (editor, path), shell=True)

        # Open the tempfile to read
        with open(path, 'r') as fr:
            new_vm_config = fr.read()
            fr.close()

        # Delete the tempfile
        os.unlink(path)

        # Show a diff and confirm
        diff = list(difflib.unified_diff(current_vm_config.split('\n'), new_vm_config.split('\n'), fromfile='current', tofile='modified', fromfiledate='', tofiledate='', n=3, lineterm=''))
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
            click.echo('Writing modified config of VM "{}" and restarting.'.format(dom_name))
        else:
            click.echo('Writing modified config of VM "{}".'.format(dom_name))

    # We're operating in replace mode
    else:
        # Open the XML file
        new_vm_config = config.read()
        config.close()

        if restart:
            click.echo('Replacing config of VM "{}" with file "{}" and restarting.'.format(dom_name, config))
        else:
            click.echo('Replacing config of VM "{}" with file "{}".'.format(dom_name, config))

    retcode, retmsg = pvc_vm.modify_vm(zk_conn, domain, restart, new_vm_config)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc vm undefine
###############################################################################
@click.command(name='undefine', short_help='Undefine and stop a virtual machine.')
@click.argument(
    'domain'
)
def vm_undefine(domain):
    """
    Stop virtual machine DOMAIN and remove it from the cluster database. DOMAIN may be a UUID or name.
    """

    # Ensure at least one search method is set
    if domain == None:
        click.echo("ERROR: You must specify either a name or UUID value.")
        exit(1)

    # Open a Zookeeper connection
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_vm.undefine_vm(zk_conn, domain)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc vm start
###############################################################################
@click.command(name='start', short_help='Start up a defined virtual machine.')
@click.argument(
    'domain'
)
def vm_start(domain):
    """
    Start virtual machine DOMAIN on its configured hypervisor. DOMAIN may be a UUID or name.
    """

    # Open a Zookeeper connection
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_vm.start_vm(zk_conn, domain)
    cleanup(retcode, retmsg, zk_conn)

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

    # Open a Zookeeper connection
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_vm.restart_vm(zk_conn, domain)
    cleanup(retcode, retmsg, zk_conn)

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

    # Open a Zookeeper connection
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_vm.shutdown_vm(zk_conn, domain)
    cleanup(retcode, retmsg, zk_conn)

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

    # Open a Zookeeper connection
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_vm.stop_vm(zk_conn, domain)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc vm move
###############################################################################
@click.command(name='move', short_help='Permanently move a virtual machine to another node.')
@click.argument(
	'domain'
)
@click.option(
    '-t', '--hypervisor', 'target_hypervisor', default=None,
    help='Target hypervisor to migrate to; autodetect if unspecified.'
)
@click.option(
    '-s', '--selector', 'selector', default='mem', show_default=True,
    type=click.Choice(['mem','load','vcpus','vms']),
    help='Method to determine optimal target hypervisor during autodetect.'
)
def vm_move(domain, target_hypervisor, selector):
    """
    Permanently move virtual machine DOMAIN, via live migration if running and possible, to another hypervisor node. DOMAIN may be a UUID or name.
    """

    # Open a Zookeeper connection
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_vm.move_vm(zk_conn, domain, target_hypervisor, selector)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc vm migrate
###############################################################################
@click.command(name='migrate', short_help='Temporarily migrate a virtual machine to another node.')
@click.argument(
    'domain'
)
@click.option(
    '-t', '--hypervisor', 'target_hypervisor', default=None,
    help='Target hypervisor to migrate to; autodetect if unspecified.'
)
@click.option(
    '-s', '--selector', 'selector', default='mem', show_default=True,
    type=click.Choice(['mem','load','vcpus','vms']),
    help='Method to determine optimal target hypervisor during autodetect.'
)
@click.option(
    '-f', '--force', 'force_migrate', is_flag=True, default=False,
    help='Force migrate an already migrated VM.'
)
def vm_migrate(domain, target_hypervisor, selector, force_migrate):
    """
    Temporarily migrate running virtual machine DOMAIN, via live migration if possible, to another hypervisor node. DOMAIN may be a UUID or name. If DOMAIN is not running, it will be started on the target node.
    """

    # Open a Zookeeper connection
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_vm.migrate_vm(zk_conn, domain, target_hypervisor, selector, force_migrate)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc vm unmigrate
###############################################################################
@click.command(name='unmigrate', short_help='Restore a migrated virtual machine to its original node.')
@click.argument(
    'domain'
)
def vm_unmigrate(domain):
    """
    Restore previously migrated virtual machine DOMAIN, via live migration if possible, to its original hypervisor node. DOMAIN may be a UUID or name. If DOMAIN is not running, it will be started on the target node.
    """

    # Open a Zookeeper connection
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_vm.unmigrate_vm(zk_conn, domain)
    cleanup(retcode, retmsg, zk_conn)

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

	# Open a Zookeeper connection
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_vm.get_info(zk_conn, domain, long_output)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc vm list
###############################################################################
@click.command(name='list', short_help='List all VM objects.')
@click.argument(
    'limit', default=None, required=False
)
@click.option(
    '-t', '--hypervisor', 'hypervisor', default=None,
    help='Limit list to this hypervisor.'
)
def vm_list(hypervisor, limit):
    """
    List all virtual machines in the cluster; optionally only match names matching regex LIMIT.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_vm.get_list(zk_conn, hypervisor, limit)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc network
###############################################################################
@click.group(name='network', short_help='Manage a PVC virtual network.', context_settings=CONTEXT_SETTINGS)
def cli_network():
    """
    Manage the state of a VXLAN network in the PVC cluster.
    """
    pass

###############################################################################
# pvc network add
###############################################################################
@click.command(name='add', short_help='Add a new virtual network to the cluster.')
@click.option(
    '-d', '--description', 'description',
    default="",
    help='Description of the network; should not contain whitespace.'
)
@click.option(
    '-n', '--domain', 'domain',
    required=True,
    help='Domain name of the network.'
)
@click.option(
    '-i', '--ipnet', 'ip_network',
    required=True,
    help='CIDR-format network address for subnet.'
)
@click.option(
    '-g', '--gateway', 'ip_gateway',
    required=True,
    help='Default gateway address for subnet.'
)
@click.option(
    '--dhcp/--no-dhcp', 'dhcp_flag',
    is_flag=True,
    default=False,
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
def net_add(vni, description, domain, ip_network, ip_gateway, dhcp_flag, dhcp_start, dhcp_end):
    """
    Add a new virtual network with VXLAN identifier VNI to the cluster.

    Example:
    pvc network add 1001 --domain test.local --ipnet 10.1.1.0/24 --gateway 10.1.1.1
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_network.add_network(zk_conn, vni, description, domain, ip_network, ip_gateway, dhcp_flag, dhcp_start, dhcp_end)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc network modify
###############################################################################
@click.command(name='modify', short_help='Modify an existing virtual network.')
@click.option(
    '-d', '--description', 'description',
    default=None,
    help='Description of the network; should not contain whitespace.'
)
@click.option(
    '-i', '--ipnet', 'ip_network',
    default=None,
    help='CIDR-format network address for subnet.'
)
@click.option(
    '-g', '--gateway', 'ip_gateway',
    default=None,
    help='Default gateway address for subnet.'
)
@click.option(
    '-r', '--router', 'ip_routers',
    multiple=True,
    help='Router addresses for subnet (specify one or two; mapped to routers in order given).'
)
@click.option(
    '--dhcp/--no-dhcp', 'dhcp_flag',
    default=None,
    is_flag=True,
    help='Enable/disable DHCP for clients on subnet.'
)
@click.argument(
    'vni'
)
def net_modify(vni, description, ip_network, ip_gateway, ip_routers, dhcp_flag):
    """
    Modify details of virtual network VNI. All fields optional; only specified fields will be updated.

    Example:
    pvc network modify 1001 --gateway 10.1.1.255 --router 10.1.1.251 --router 10.1.1.252 --no-dhcp
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_network.modify_network(zk_conn, vni, description=description, ip_network=ip_network, ip_gateway=ip_gateway, ip_routers=ip_routers, dhcp_flag=dhcp_flag)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc network remove
###############################################################################
@click.command(name='remove', short_help='Remove a virtual network from the cluster.')
@click.argument(
    'net'
)
def net_remove(net):
    """
    Remove an existing virtual network NET from the cluster; NET can be either a VNI or description.

    WARNING: PVC does not verify whether clients are still present in this network. Before removing, ensure
    that all client VMs have been removed from the network or undefined behaviour may occur.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_network.remove_network(zk_conn, net)
    cleanup(retcode, retmsg, zk_conn)

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

	# Open a Zookeeper connection
    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_network.get_info(zk_conn, vni, long_output)
    cleanup(retcode, retmsg, zk_conn)

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

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_network.get_list(zk_conn, limit)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc network dhcp
###############################################################################
@click.group(name='dhcp', short_help='Manage a PVC virtual network DHCP reservations.', context_settings=CONTEXT_SETTINGS)
def net_dhcp():
    """
    Manage host DHCP leases of a VXLAN network in the PVC cluster.
    """
    pass


###############################################################################
# pvc network dhcp add
###############################################################################
@click.command(name='add', short_help='Add a static DHCP lease to a virtual network.')
@click.argument(
    'net'
)
@click.argument(
    'ipaddr'
)
@click.argument(
    'macaddr'
)
@click.argument(
    'hostname'
)
def net_dhcp_add(net, ipaddr, macaddr, hostname):
    """
    Add a new static DHCP lease of IP address IPADDR with hostname HOSTNAME for MAC address MACADDR to virtual network NET; NET can be either a VNI or description.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_network.add_dhcp_reservation(zk_conn, net, ipaddr, macaddr, hostname)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc network dhcp remove
###############################################################################
@click.command(name='remove', short_help='Remove a DHCP lease from a virtual network.')
@click.argument(
    'net'
)
@click.argument(
    'lease'
)
def net_dhcp_remove(net, lease):
    """
    Remove a DHCP lease LEASE from virtual network NET; LEASE can be either a MAC address, an IP address, or a hostname; NET can be either a VNI or description.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_network.remove_dhcp_lease(zk_conn, net, lease)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc network dhcp list
###############################################################################
@click.command(name='list', short_help='List DHCP lease objects.')
@click.option(
    '-r', '--reservations', 'only_reservations', is_flag=True, default=False,
    help='Show only static reservations instead of all leases.'
)
@click.argument(
    'net'
)
@click.argument(
    'limit', default=None, required=False
)
def net_dhcp_list(net, limit, only_reservations):
    """
    List all DHCP leases in virtual network NET; optionally only match elements matching regex LIMIT; NET can be either a VNI or description.
    """

    zk_conn = pvc_common.startZKConnection(zk_host)
    retcode, retmsg = pvc_network.get_list_dhcp_leases(zk_conn, net, limit, only_reservations=only_reservations)
    cleanup(retcode, retmsg, zk_conn)

###############################################################################
# pvc network acl
###############################################################################
@click.group(name='acl', short_help='Manage a PVC virtual network firewall ACL rule.', context_settings=CONTEXT_SETTINGS)
def net_acl():
    """
    Manage firewall ACLs of a VXLAN network in the PVC cluster.
    """
    pass





###############################################################################
# pvc init
###############################################################################
@click.command(name='init', short_help='Initialize a new cluster.')
@click.option('--yes', is_flag=True,
              expose_value=False,
              prompt='DANGER: This command will destroy any existing cluster data. Do you want to continue?')
def init_cluster():
    """
    Perform initialization of Zookeeper to act as a PVC cluster.

    DANGER: This command will overwrite any existing cluster data and provision a new cluster at the specified Zookeeper connection string. Do not run this against a cluster unless you are sure this is what you want.
    """

    click.echo('Initializing a new cluster with Zookeeper address "{}".'.format(zk_host))

    # Open a Zookeeper connection
    zk_conn = pvc_common.startZKConnection(zk_host)

    # Destroy the existing data
    try:
        zk_conn.delete('/domains', recursive=True)
        zk_conn.delete('nodes', recursive=True)
    except:
        pass

    # Create the root keys
    transaction = zk_conn.transaction()
    transaction.create('/domains', ''.encode('ascii'))
    transaction.create('/nodes', ''.encode('ascii'))
    transaction.create('/routers', ''.encode('ascii'))
    transaction.create('/networks', ''.encode('ascii'))
    transaction.commit()

    # Close the Zookeeper connection
    pvc_common.stopZKConnection(zk_conn)

    click.echo('Successfully initialized new cluster. Any running PVC daemons will need to be restarted.')


###############################################################################
# pvc
###############################################################################
@click.group(context_settings=CONTEXT_SETTINGS)
@click.option(
    '-z', '--zookeeper', '_zk_host', envvar='PVC_ZOOKEEPER', default='{}:2181'.format(myhostname), show_default=True,
    help='Zookeeper connection string.'
)
def cli(_zk_host):
    """
    Parallel Virtual Cluster CLI management tool

    Environment variables:

      "PVC_ZOOKEEPER": Set the cluster Zookeeper address instead of using "--zookeeper".
    """

    global zk_host
    zk_host = _zk_host


#
# Click command tree
#
cli_node.add_command(node_flush)
cli_node.add_command(node_ready)
cli_node.add_command(node_unflush)
cli_node.add_command(node_info)
cli_node.add_command(node_list)

cli_router.add_command(router_secondary)
cli_router.add_command(router_primary)
cli_router.add_command(router_info)
cli_router.add_command(router_list)

cli_vm.add_command(vm_define)
cli_vm.add_command(vm_modify)
cli_vm.add_command(vm_undefine)
cli_vm.add_command(vm_start)
cli_vm.add_command(vm_restart)
cli_vm.add_command(vm_shutdown)
cli_vm.add_command(vm_stop)
cli_vm.add_command(vm_move)
cli_vm.add_command(vm_migrate)
cli_vm.add_command(vm_unmigrate)
cli_vm.add_command(vm_info)
cli_vm.add_command(vm_list)

cli_network.add_command(net_add)
cli_network.add_command(net_modify)
cli_network.add_command(net_remove)
cli_network.add_command(net_info)
cli_network.add_command(net_list)
cli_network.add_command(net_dhcp)
cli_network.add_command(net_acl)

net_dhcp.add_command(net_dhcp_add)
net_dhcp.add_command(net_dhcp_remove)
net_dhcp.add_command(net_dhcp_list)

cli.add_command(cli_node)
cli.add_command(cli_router)
cli.add_command(cli_vm)
cli.add_command(cli_network)
cli.add_command(init_cluster)

#
# Main entry point
#
def main():
    return cli(obj={})

if __name__ == '__main__':
    main()

