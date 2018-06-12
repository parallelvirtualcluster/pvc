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

import kazoo.client, os, socket, time, click, lxml.objectify, pvcf, ansiiprint, configparser

myhostname = socket.gethostname()
zk_host = ''

########################
########################
##                    ##
##  CLICK COMPONENTS  ##
##                    ##
########################
########################

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'], max_content_width=120)

###############################################################################
# pvc node
###############################################################################
@click.group(name='node', short_help='Manage a PVC hypervisor node', context_settings=CONTEXT_SETTINGS)
def node():
    """
    Manage the state of a node in the PVC cluster.
    """
    pass


###############################################################################
# pvc node flush
###############################################################################
@click.command(name='flush', short_help='Take a node out of service')
@click.option(
    '-n', '--name', 'node_name', default=myhostname, show_default=True,
    help='The PVC node to operate on.'
)
def flush_host(node_name):
    """
    Take a node out of active service and migrate away all VMs.

    Notes:

    * The '--name' option defaults to the current host if not set, which is likely not what you want when running this command from a remote host!
    """

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # Verify node is valid
    try:
        zk.get('/nodes/{}'.format(node_name))
    except:
        click.echo('ERROR: No node named {} is present in the cluster.'.format(node_name))
        exit(1)

    click.echo('Flushing hypervisor {} of running VMs.'.format(node_name))

    # Add the new domain to Zookeeper
    transaction = zk.transaction()
    transaction.set_data('/nodes/{}/domainstate'.format(node_name), 'flush'.encode('ascii'))
    results = transaction.commit()

    # Close the Zookeeper connection
    pvcf.stopZKConnection(zk)


###############################################################################
# pvc node ready
###############################################################################
@click.command(name='ready', short_help='Restore node to service')
@click.option(
    '-n', '--name', 'node_name', default=myhostname, show_default=True,
    help='The PVC node to operate on.'
)
def ready_host(node_name):
    """
    Restore a host to active service and migrate back all VMs.

    Notes:

    * The '--name' option defaults to the current host if not set, which is likely not what you want when running this command from a remote host!
    """

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # Verify node is valid
    try:
        zk.get('/nodes/{}'.format(node_name))
    except:
        click.echo('ERROR: No node named {} is present in the cluster.'.format(node_name))
        exit(1)

    click.echo('Restoring hypervisor {} to active service.'.format(node_name))

    # Add the new domain to Zookeeper
    transaction = zk.transaction()
    transaction.set_data('/nodes/{}/domainstate'.format(node_name), 'unflush'.encode('ascii'))
    results = transaction.commit()

    # Close the Zookeeper connection
    pvcf.stopZKConnection(zk)


###############################################################################
# pvc node info
###############################################################################
@click.command(name='info', short_help='Show details of a node object')
@click.option(
    '-n', '--name', 'dom_name',
    help='Search for this name.'
)
@click.option(
    '-l', '--long', 'long_output', is_flag=True, default=False,
    help='Display more detailed information.'
)
def node_info(dom_name, dom_uuid, long_output):
    """
    Search the cluster for a node's information.
    """

    # Verify node is valid
    try:
        zk.get('/nodes/{}'.format(node_name))
    except:
        click.echo('ERROR: No node named {} is present in the cluster.'.format(node_name))
        exit(1)

    pass


###############################################################################
# pvc node list
###############################################################################
@click.command(name='list', short_help='List all Node objects')
def node_list():
    """
    List all hypervisor nodes in the cluster.
    """

    node_list_header = ansiiprint.bold() + 'Name                   State: Daemon  Nodes    Resources: VMs   CPUs  RAM [MiB]: Total   Used    Free    Allocated' + ansiiprint.end()
    node_list = []
    zk = pvcf.startZKConnection(zk_host)
    for node_name in zk.get_children('/nodes'):

        node_daemon_state = zk.get('/nodes/{}/daemonstate'.format(node_name))[0].decode('ascii')
        node_domain_state = zk.get('/nodes/{}/domainstate'.format(node_name))[0].decode('ascii')
        node_cpu_count = zk.get('/nodes/{}/cpucount'.format(node_name))[0].decode('ascii')
        node_mem_used = zk.get('/nodes/{}/memused'.format(node_name))[0].decode('ascii')
        node_mem_free = zk.get('/nodes/{}/memfree'.format(node_name))[0].decode('ascii')
        node_mem_total = int(node_mem_used) + int(node_mem_free)
        node_domains_count = zk.get('/nodes/{}/domainscount'.format(node_name))[0].decode('ascii')
        node_running_domains = zk.get('/nodes/{}/runningdomains'.format(node_name))[0].decode('ascii').split()
        node_mem_allocated = 0
        for domain in node_running_domains:
            parsed_xml = pvcf.getDomainXML(zk, domain)
            duuid, dname, dmemory, dvcpu, dvcputopo = pvcf.getDomainMainDetails(parsed_xml)
            node_mem_allocated += int(dmemory)

        if node_daemon_state == 'start':
            daemon_state_colour = ansiiprint.green()
        elif node_daemon_state == 'stop' or node_daemon_state == 'shutdown':
            daemon_state_colour = ansiiprint.red()
        else:
            daemon_state_colour = ansiiprint.yellow()

        if node_domain_state == 'ready':
            domain_state_colour = ansiiprint.green()
        else:
            domain_state_colour = ansiiprint.blue()

        node_output_string = '{3: <28}  {0}{4: <6}{2}  {1}{5: <8}{2}            {6: <4}  {7: <4}             {8: <6}  {9: <6}  {10: <6}  {11: <6}'.format(
            daemon_state_colour,
            domain_state_colour,
            ansiiprint.end(),
            node_name,
            node_daemon_state,
            node_domain_state,
            node_domains_count,
            node_cpu_count,
            node_mem_total,
            node_mem_used,
            node_mem_free,
            node_mem_allocated
        )
        node_list.append(node_output_string)

    click.echo(node_list_header)
    click.echo('\n'.join(sorted(node_list)))



###############################################################################
# pvc vm
###############################################################################
@click.group(name='vm', short_help='Manage a PVC virtual machine', context_settings=CONTEXT_SETTINGS)
def vm():
    """
    Manage the state of a virtual machine in the PVC cluster.
    """
    pass


###############################################################################
# pvc vm define
###############################################################################
@click.command(name='define', short_help='Define a new virtual machine from a Libvirt XML file.')
@click.option(
    '-x', '--xml', 'xml_config_file',
    help='The XML config file to define the domain from.'
)
@click.option(
    '-t', '--hypervisor', 'target_hypervisor', default=myhostname, show_default=True,
    help='The home hypervisor for this domain.'
)
def define_vm(xml_config_file, target_hypervisor):
    """
    Define a new virtual machine from a Libvirt XML configuration file.

    Notes:

    * The '--hypervisor' option defaults to the current host if not set, which is likely not what you want when running this command from a remote host!
    """

    # Open the XML file
    with open(xml_config_file, 'r') as f_domxmlfile:
        data = f_domxmlfile.read()
        f_domxmlfile.close()

    # Parse the XML data
    parsed_xml = lxml.objectify.fromstring(data)
    dom_uuid = parsed_xml.uuid.text
    dom_name = parsed_xml.name.text
    click.echo('Adding new VM with Name "{}" and UUID "{}" to database.'.format(dom_name, dom_uuid))

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # Add the new domain to Zookeeper
    transaction = zk.transaction()
    transaction.create('/domains/{}'.format(dom_uuid), dom_name.encode('ascii'))
    transaction.create('/domains/{}/state'.format(dom_uuid), 'stop'.encode('ascii'))
    transaction.create('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
    transaction.create('/domains/{}/lasthypervisor'.format(dom_uuid), ''.encode('ascii'))
    transaction.create('/domains/{}/xml'.format(dom_uuid), data.encode('ascii'))
    results = transaction.commit()

    # Close the Zookeeper connection
    pvcf.stopZKConnection(zk)


###############################################################################
# pvc vm undefine
###############################################################################
@click.command(name='undefine', short_help='Undefine and stop a virtual machine.')
@click.option(
    '-n', '--name', 'dom_name',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_uuid', 'argument': '--uuid' }],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_name', 'argument': '--name' }],
    help='Search for this UUID.'
)
def undefine_vm(dom_name, dom_uuid):
    """
    Stop a virtual machine and remove it from the cluster database.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("ERROR: You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)

    # Verify we got a result or abort
    if not pvcf.validateUUID(dom_uuid):
        if dom_name != None:
            message_name = dom_name
        else:
            message_name = dom_uuid
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(message_name))
        return

    current_vm_state = zk.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_vm_state != 'stop':
        click.echo('Forcibly stopping VM "{}".'.format(dom_uuid))
        # Set the domain into stop mode
        transaction = zk.transaction()
        transaction.set_data('/domains/{}/state'.format(dom_uuid), 'stop'.encode('ascii'))
        transaction.commit()

        # Wait for 3 seconds to allow state to flow to all hypervisors
        click.echo('Waiting for cluster to update.')
        time.sleep(3)

    # Delete the configurations
    click.echo('Undefining VM "{}".'.format(dom_uuid))
    transaction = zk.transaction()
    transaction.delete('/domains/{}/state'.format(dom_uuid))
    transaction.delete('/domains/{}/hypervisor'.format(dom_uuid))
    transaction.delete('/domains/{}/lasthypervisor'.format(dom_uuid))
    transaction.delete('/domains/{}/xml'.format(dom_uuid))
    transaction.delete('/domains/{}'.format(dom_uuid))
    transaction.commit()

    # Close the Zookeeper connection
    pvcf.stopZKConnection(zk)


###############################################################################
# pvc vm start
###############################################################################
@click.command(name='start', short_help='Start up a defined virtual machine.')
@click.option(
    '-n', '--name', 'dom_name',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_uuid', 'argument': '--uuid' }],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_name', 'argument': '--name' }],
    help='Search for this UUID.'
)
def start_vm(dom_name, dom_uuid):
    """
    Start up a virtual machine on its configured hypervisor.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("ERROR: You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)

    # Verify we got a result or abort
    if not pvcf.validateUUID(dom_uuid):
        if dom_name != None:
            message_name = dom_name
        else:
            message_name = dom_uuid
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(message_name))
        return

    # Set the VM to start
    click.echo('Starting VM "{}".'.format(dom_uuid))
    zk.set('/domains/%s/state' % dom_uuid, 'start'.encode('ascii'))

    # Close the Zookeeper connection
    pvcf.stopZKConnection(zk)


###############################################################################
# pvc vm shutdown
###############################################################################
@click.command(name='shutdown', short_help='Gracefully shut down a running virtual machine.')
@click.option(
    '-n', '--name', 'dom_name',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_uuid', 'argument': '--uuid' }],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_name', 'argument': '--name' }],
    help='Search for this UUID.'
)
def shutdown_vm(dom_name, dom_uuid):
    """
    Gracefully shut down a running virtual machine.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("ERROR: You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)

    # Verify we got a result or abort
    if not pvcf.validateUUID(dom_uuid):
        if dom_name != None:
            message_name = dom_name
        else:
            message_name = dom_uuid
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(message_name))
        return

    # Set the VM to shutdown
    click.echo('Shutting down VM "{}".'.format(dom_uuid))
    zk.set('/domains/%s/state' % dom_uuid, 'shutdown'.encode('ascii'))

    # Close the Zookeeper connection
    pvcf.stopZKConnection(zk)


###############################################################################
# pvc vm stop
###############################################################################
@click.command(name='stop', short_help='Forcibly halt a running virtual machine.')
@click.option(
    '-n', '--name', 'dom_name',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_uuid', 'argument': '--uuid' }],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_name', 'argument': '--name' }],
    help='Search for this UUID.'
)
def stop_vm(dom_name, dom_uuid):
    """
    Forcibly halt (destroy) a running virtual machine.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("ERROR: You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)

    # Verify we got a result or abort
    if not pvcf.validateUUID(dom_uuid):
        if dom_name != None:
            message_name = dom_name
        else:
            message_name = dom_uuid
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(message_name))
        return

    # Set the VM to start
    click.echo('Forcibly stopping VM "{}".'.format(dom_uuid))
    zk.set('/domains/%s/state' % dom_uuid, 'stop'.encode('ascii'))

    # Close the Zookeeper connection
    pvcf.stopZKConnection(zk)


###############################################################################
# pvc vm move
###############################################################################
@click.command(name='move', short_help='Permanently move a virtual machine to another node.')
@click.option(
    '-n', '--name', 'dom_name',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_uuid', 'argument': '--uuid' }],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_name', 'argument': '--name' }],
    help='Search for this UUID.'
)
@click.option(
    '-t', '--target', 'target_hypervisor', default=None,
    help='The target hypervisor to migrate to.'
)
def move_vm(dom_name, dom_uuid, target_hypervisor):
    """
    Permanently move a virtual machine, via live migration if running and possible, to another hypervisor node.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("ERROR: You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)

    # Verify we got a result or abort
    if not pvcf.validateUUID(dom_uuid):
        if dom_name != None:
            message_name = dom_name
        else:
            message_name = dom_uuid
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(message_name))
        return

    current_hypervisor = zk.get('/domains/{}/hypervisor'.format(dom_uuid))[0].decode('ascii')

    if target_hypervisor == None:
        # Determine the best hypervisor to migrate the VM to based on active memory usage
        hypervisor_list = zk.get_children('/nodes')
        most_memfree = 0
        for hypervisor in hypervisor_list:
            state = zk.get('/nodes/{}/state'.format(hypervisor))[0].decode('ascii')
            if state != 'start' or hypervisor == current_hypervisor:
                continue

            memfree = int(zk.get('/nodes/{}/memfree'.format(hypervisor))[0].decode('ascii'))
            if memfree > most_memfree:
                most_memfree = memfree
                target_hypervisor = hypervisor
    else:
        if target_hypervisor == current_hypervisor:
            click.echo('ERROR: The VM "{}" is already running on hypervisor "{}".'.format(dom_uuid, current_hypervisor))
            return

    current_vm_state = zk.get('/domains/{}/state'.format(dom_uuid))[0].decode('ascii')
    if current_vm_state == 'start':
        click.echo('Permanently migrating VM "{}" to hypervisor "{}".'.format(dom_uuid, target_hypervisor))
        transaction = zk.transaction()
        transaction.set_data('/domains/{}/state'.format(dom_uuid), 'migrate'.encode('ascii'))
        transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
        transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), ''.encode('ascii'))
        transaction.commit()
    else:
        click.echo('Permanently moving VM "{}" to hypervisor "{}".'.format(dom_uuid, target_hypervisor))
        transaction = zk.transaction()
        transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
        transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), ''.encode('ascii'))
        transaction.commit()

    # Close the Zookeeper connection
    pvcf.stopZKConnection(zk)


###############################################################################
# pvc vm migrate
###############################################################################
@click.command(name='migrate', short_help='Migrate a virtual machine to another node.')
@click.option(
    '-n', '--name', 'dom_name',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_uuid', 'argument': '--uuid' }],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_name', 'argument': '--name' }],
    help='Search for this UUID.'
)
@click.option(
    '-t', '--target', 'target_hypervisor', default=None,
    help='The target hypervisor to migrate to.'
)
@click.option(
    '-f', '--force', 'force_migrate', is_flag=True, default=False,
    help='Force migrate an already migrated VM.'
)
def migrate_vm(dom_name, dom_uuid, target_hypervisor, force_migrate):
    """
    Migrate a running virtual machine, via live migration if possible, to another hypervisor node.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("ERROR: You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)

    # Verify we got a result or abort
    if not pvcf.validateUUID(dom_uuid):
        if dom_name != None:
            message_name = dom_name
        else:
            message_name = dom_uuid
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(message_name))
        return

    current_hypervisor = zk.get('/domains/{}/hypervisor'.format(dom_uuid))[0].decode('ascii')
    last_hypervisor = zk.get('/domains/{}/lasthypervisor'.format(dom_uuid))[0].decode('ascii')

    if last_hypervisor != '' and force_migrate != True:
        click.echo('ERROR: The VM "{}" has been previously migrated.'.format(dom_uuid))
        click.echo('> Last hypervisor: {}'.format(last_hypervisor))
        click.echo('> Current hypervisor: {}'.format(current_hypervisor))
        click.echo('Run `vm unmigrate` to restore the VM to its previous hypervisor, or use `--force` to override this check.')
        return

    if target_hypervisor == None:
        # Determine the best hypervisor to migrate the VM to based on active memory usage
        hypervisor_list = zk.get_children('/nodes')
        most_memfree = 0
        for hypervisor in hypervisor_list:
            daemon_state = zk.get('/nodes/{}/daemonstate'.format(hypervisor))[0].decode('ascii')
            domain_state = zk.get('/nodes/{}/domainstate'.format(hypervisor))[0].decode('ascii')
            if daemon_state != 'start' or domain_state != 'ready' or hypervisor == current_hypervisor:
                continue

            memfree = int(zk.get('/nodes/{}/memfree'.format(hypervisor))[0].decode('ascii'))
            if memfree > most_memfree:
                most_memfree = memfree
                target_hypervisor = hypervisor
    else:
        if target_hypervisor == current_hypervisor:
            click.echo('ERROR: The VM "{}" is already running on hypervisor "{}".'.format(dom_uuid, current_hypervisor))
            return

    click.echo('Migrating VM "{}" to hypervisor "{}".'.format(dom_uuid, target_hypervisor))
    transaction = zk.transaction()
    transaction.set_data('/domains/{}/state'.format(dom_uuid), 'migrate'.encode('ascii'))
    transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
    transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), current_hypervisor.encode('ascii'))
    transaction.commit()

    # Close the Zookeeper connection
    pvcf.stopZKConnection(zk)


###############################################################################
# pvc vm unmigrate
###############################################################################
@click.command(name='unmigrate', short_help='Restore a migrated virtual machine to its original node.')
@click.option(
    '-n', '--name', 'dom_name',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_uuid', 'argument': '--uuid' }],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_name', 'argument': '--name' }],
    help='Search for this UUID.'
)
def unmigrate_vm(dom_name, dom_uuid):
    """
    Restore a previously migrated virtual machine, via live migration if possible, to its original hypervisor node.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("ERROR: You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)

    # Verify we got a result or abort
    if not pvcf.validateUUID(dom_uuid):
        if dom_name != None:
            message_name = dom_name
        else:
            message_name = dom_uuid
        click.echo('ERROR: Could not find VM "{}" in the cluster!'.format(message_name))
        return

    target_hypervisor = zk.get('/domains/{}/lasthypervisor'.format(dom_uuid))[0].decode('ascii')

    if target_hypervisor == '':
        click.echo('ERROR: The VM "{}" has not been previously migrated.'.format(dom_uuid))
        return

    click.echo('Unmigrating VM "{}" back to hypervisor "{}".'.format(dom_uuid, target_hypervisor))
    transaction = zk.transaction()
    transaction.set_data('/domains/{}/state'.format(dom_uuid), 'migrate'.encode('ascii'))
    transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
    transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), ''.encode('ascii'))
    transaction.commit()

    # Close the Zookeeper connection
    pvcf.stopZKConnection(zk)


###############################################################################
# pvc vm info
###############################################################################
@click.command(name='info', short_help='Show details of a VM object')
@click.option(
    '-n', '--name', 'dom_name',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_uuid', 'argument': '--uuid' }],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=[{ 'function': 'dom_name', 'argument': '--name' }],
    help='Search for this UUID.'
)
@click.option(
    '-l', '--long', 'long_output', is_flag=True, default=False,
    help='Display more detailed information.'
)
def vm_info(dom_name, dom_uuid, long_output):
    """
    Search the cluster for a virtual machine's information.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("ERROR: You must specify either a `--name` or `--uuid` value.")
        return

    zk = pvcf.startZKConnection(zk_host)
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)
    if dom_uuid != None:
        dom_name = pvcf.searchClusterByUUID(zk, dom_uuid)

    information = pvcf.getInformationFromXML(zk, dom_uuid, long_output)

    if information == None:
        click.echo('ERROR: Could not find a domain matching that name or UUID.')
        return

    click.echo(information)
    pvcf.stopZKConnection(zk)


###############################################################################
# pvc vm list
###############################################################################
@click.command(name='list', short_help='List all VM objects')
@click.option(
    '-t', '--hypervisor', 'hypervisor', default=None,
    help='Limit list to this hypervisor.'
)
def vm_list(hypervisor):
    """
    List all virtual machines in the cluster.
    """

    vm_list_header = ansiiprint.bold() + 'Name             UUID                                  State     RAM [MiB]  vCPUs  Hypervisor            Migrated?' + ansiiprint.end()
    vm_list = []
    zk = pvcf.startZKConnection(zk_host)
    for vm in zk.get_children('/domains'):
        # Check hypervisor to avoid unneeded ZK calls
        vm_hypervisor = zk.get('/domains/{}/hypervisor'.format(vm))[0].decode('ascii')
        if hypervisor != None and vm_hypervisor != hypervisor:
            continue

        vm_state = zk.get('/domains/{}/state'.format(vm))[0].decode('ascii')
        vm_lasthypervisor = zk.get('/domains/{}/lasthypervisor'.format(vm))[0].decode('ascii')
        if vm_lasthypervisor != '':
            vm_migrated = 'from {}'.format(vm_lasthypervisor)
        else:
            vm_migrated = 'no'

        vm_xml = pvcf.getDomainXML(zk, vm)
        vm_uuid, vm_name, vm_memory, vm_vcpu, vm_vcputopo = pvcf.getDomainMainDetails(vm_xml)

        if vm_state == 'start':
            state_colour = ansiiprint.green()
        elif vm_state == 'stop' or vm_state == 'shutdown':
            state_colour = ansiiprint.red()
        else:
            state_colour = ansiiprint.yellow()

        vm_output_string = '{2: <16} {3: <32}  {0}{4: <8}{1}  {5: <6}     {6: <5}  {7: <20}  {8: <25}'.format(
            state_colour,
            ansiiprint.end(),
            vm_name,
            vm_uuid,
            vm_state,
            vm_memory,
            vm_vcpu,
            vm_hypervisor,
            vm_migrated
        )
        vm_list.append(vm_output_string)

    click.echo(vm_list_header)
    click.echo('\n'.join(sorted(vm_list)))


###############################################################################
# pvc init
###############################################################################
@click.command(name='init', short_help='Initialize a new cluster')
@click.option('--yes', is_flag=True,
              expose_value=False,
              prompt='DANGER: This command will destroy any existing cluster data. Do you want to continue?')
def init_cluster():
    """
    Perform initialization of Zookeeper to act as a PVC cluster
    """

    click.echo('Initializing a new cluster with Zookeeper address "{}".'.format(zk_host))

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # Destroy the existing data
    try:
        zk.delete('/domains', recursive=True)
        zk.delete('nodes', recursive=True)
    except:
        pass

    # Create the root keys
    transaction = zk.transaction()
    transaction.create('/domains', ''.encode('ascii'))
    transaction.create('/nodes', ''.encode('ascii'))
    transaction.commit()

    # Close the Zookeeper connection
    pvcf.stopZKConnection(zk)

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
    """

    global zk_host
    zk_host = _zk_host


#
# Click command tree
#
node.add_command(flush_host)
node.add_command(ready_host)
node.add_command(node_info)
node.add_command(node_list)

vm.add_command(define_vm)
vm.add_command(undefine_vm)
vm.add_command(start_vm)
vm.add_command(shutdown_vm)
vm.add_command(stop_vm)
vm.add_command(move_vm)
vm.add_command(migrate_vm)
vm.add_command(unmigrate_vm)
vm.add_command(vm_info)
vm.add_command(vm_list)

cli.add_command(node)
cli.add_command(vm)
cli.add_command(init_cluster)

#
# Main entry point
#
def main():
    return cli(obj={})

if __name__ == '__main__':
    main()
