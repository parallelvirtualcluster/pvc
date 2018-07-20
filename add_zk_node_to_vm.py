#!/usr/bin/env python3

# add_zk_node_to_vm.py - Debugging tool to add a new ZK node to all existing
#                        cluster entries.
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
import kazoo.client


#
# Connect and disconnect from Zookeeper
#
def startZKConnection(zk_host):
    zk_conn = kazoo.client.KazooClient(hosts=zk_host)
    zk_conn.start()
    return zk_conn

def stopZKConnection(zk_conn):
    zk_conn.stop()
    zk_conn.close()
    return 0


########################
########################
##                    ##
##  CLICK COMPONENTS  ##
##                    ##
########################
########################

zk_host = ''
myhostname = socket.gethostname()

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'], max_content_width=120)

###############################################################################
# node
###############################################################################
@click.command(name='node', short_help='Add field to all node configs.')
@click.argument(
    'field', default=None
)
@click.argument(
    'data', default='', required=False
)
def node(field, data):
    """
    Add FIELD to all node configs with optional DATA.

    For example, 'foo [bar]` creates Zookeeper node '/domains/*/foo' with contents 'bar'.
    """

    # Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    full_node_list = zk_conn.get_children('/nodes')
    transaction = zk_conn.transaction()
    for node in full_node_list:
        transaction.create('/nodes/{}/{}'.format(node, field), data.encode('ascii'))
    results = transaction.commit()

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)


###############################################################################
# vm
###############################################################################
@click.command(name='vm', short_help='Add field to all node configs.')
@click.argument(
    'field', default=None
)
@click.argument(
    'data', default='', required=False
)
def vm(field, data):
    """
    Add FIELD to all VM configs with optional DATA.

    For example, 'foo [bar]` creates Zookeeper node '/nodes/*/foo' with contents 'bar'.
    """

    # Open a Zookeeper connection
    zk_conn = startZKConnection(zk_host)

    full_vm_list = zk_conn.get_children('/domains')
    transaction = zk_conn.transaction()
    for vm in full_vm_list:
        transaction.create('/domains/{}/{}'.format(vm, field), data.encode('ascii'))
    results = transaction.commit()

    # Close the Zookeeper connection
    stopZKConnection(zk_conn)


@click.group(context_settings=CONTEXT_SETTINGS)
@click.option(
    '-z', '--zookeeper', '_zk_host', envvar='PVC_ZOOKEEPER', default='{}:2181'.format(myhostname), show_default=True,
    help='Zookeeper connection string.'
)
def cli(_zk_host):
    """
    Parallel Virtual Cluster CLI management tool
    """

    global zk_host
    zk_host = _zk_host

cli.add_command(node)
cli.add_command(vm)

#
# Main entry point
#
def main():
    return cli(obj={})

if __name__ == '__main__':
    main()

