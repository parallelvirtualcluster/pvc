#!/usr/bin/env python3

import kazoo.client, socket, time, click
import pvcf
from lxml import objectify

this_host = socket.gethostname()
zk_host = ''

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'], max_content_width=120)

# Creates a new domain based on an XML file
def define_domain(domxmlfile, target_hypervisor):
    with open(domxmlfile, 'r') as f_domxmlfile:
        data = f_domxmlfile.read()
        f_domxmlfile.close()

    parsed_xml = objectify.fromstring(data)
    domuuid = parsed_xml.uuid.text
    domname = parsed_xml.name.text
    print('Adding new VM with Name %s and UUID %s to database' % (domname, domuuid))

    zk = pvcf.startZKConnection(zk_host)
    transaction = zk.transaction()
    transaction.create('/domains/%s' % domuuid, domname.encode('ascii'))
    transaction.create('/domains/%s/state' % domuuid, 'stop'.encode('ascii'))
    transaction.create('/domains/%s/hypervisor' % domuuid, target_hypervisor.encode('ascii'))
    transaction.create('/domains/%s/lasthypervisor' % domuuid, ''.encode('ascii'))
    transaction.create('/domains/%s/name' % domuuid, data.encode('ascii'))
    transaction.create('/domains/%s/xml' % domuuid, data.encode('ascii'))
    results = transaction.commit()
    pvcf.stopZKConnection(zk)

def delete_domain(domuuid):
    zk = pvcf.startZKConnection(zk_host)

    # Set the domain into delete mode
    transaction = zk.transaction()
    transaction.set_data('/domains/%s/state' % domuuid, 'delete'.encode('ascii'))
    results = transaction.commit()
    print(results)

    # Wait for 3 seconds to allow state to flow to all hypervisors
    time.sleep(3)

    # Delete the configurations
    transaction = zk.transaction()
    transaction.delete('/domains/%s/state' % domuuid)
    transaction.delete('/domains/%s/hypervisor' % domuuid)
    transaction.delete('/domains/%s/lasthypervisor' % domuuid)
    transaction.delete('/domains/%s/xml' % domuuid)
    transaction.delete('/domains/%s' % domuuid)
    results = transaction.commit()
    print(results)
    pvcf.stopZKConnection(zk)

# Migrate VM to target_hypervisor
def migrate_domain(domuuid, target_hypervisor):
    zk = pvcf.startZKConnection(zk_host)
    current_hypervisor = zk.get('/domains/%s/hypervisor' % domuuid)[0].decode('ascii')
    last_hypervisor = zk.get('/domains/%s/lasthypervisor' % domuuid)[0].decode('ascii')
    if last_hypervisor != '':
        print('The VM %s has been previously migrated from %s to %s. You must unmigrate it before migrating it again!' % (domuuid, last_hypervisor, current_hypervisor))
        pvcf.stopZKConnection(zk)
        return

    print('Migrating VM with UUID %s from hypervisor %s to hypervisor %s' % (domuuid, current_hypervisor, target_hypervisor))
    transaction = zk.transaction()
    transaction.set_data('/domains/%s/state' % domuuid, 'migrate'.encode('ascii'))
    transaction.set_data('/domains/%s/hypervisor' % domuuid, target_hypervisor.encode('ascii'))
    transaction.set_data('/domains/%s/lasthypervisor' % domuuid, current_hypervisor.encode('ascii'))
    results = transaction.commit()
    print(results)
    pvcf.stopZKConnection(zk)

# Unmigrate VM back from previous hypervisor
def unmigrate_domain(domuuid):
    zk = pvcf.startZKConnection(zk_host)
    target_hypervisor = zk.get('/domains/%s/lasthypervisor' % domuuid)[0].decode('ascii')
    if target_hypervisor == '':
        print('The VM %s has not been previously migrated and cannot be unmigrated.' % domuuid)
        pvcf.stopZKConnection(zk)
        return
    print('Unmigrating VM with UUID %s back to hypervisor %s' % (domuuid, target_hypervisor))
    transaction = zk.transaction()
    transaction.set_data('/domains/%s/state' % domuuid, 'migrate'.encode('ascii'))
    transaction.set_data('/domains/%s/hypervisor' % domuuid, target_hypervisor.encode('ascii'))
    transaction.set_data('/domains/%s/lasthypervisor' % domuuid, ''.encode('ascii'))
    results = transaction.commit()
    print(results)
    pvcf.stopZKConnection(zk)
    

########################
########################
##                    ##
##  CLICK COMPONENTS  ##
##                    ##
########################
########################

###############################################################################
# pvc node
###############################################################################
@click.group(name='node', short_help='Manage a PVC hypervisor node', context_settings=CONTEXT_SETTINGS)
@click.option(
    '-n', '--name', 'node_name', default=this_host, show_default=True,
    help='The PVC node to operate on.'
)
def node():
    """
    Manage the state of a node in the PVC cluster.

    Notes:

    * The '--name' option defaults to the current host if not set, which is likely not what you want when running this command from a remote host!
    """
    pass


###############################################################################
# pvc node flush
###############################################################################
@click.command(name='flush', short_help='Take a node out of service')
def flush_host():
    """
    Take a node out of active service and migrate away all VMs.
    """
    pass


###############################################################################
# pvc node ready
###############################################################################
@click.command(name='ready', short_help='Restore node to service')
def ready_host():
    """
    Restore a host to active service and migrate back all VMs.
    """
    pass


###############################################################################
# pvc vm
###############################################################################
@click.group(name='vm', short_help='Manage a PVC virtual machine', context_settings=CONTEXT_SETTINGS)
def vm():
    """
    Manage the state of a virtual machine in the PVC cluster.

    Notes:
    
    * PVC virtual machines are always managed by UUID. To find a name-to-UUID mapping, use the 'search' command.
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
    '-v', '--hypervisor', 'target_hypervisor', default=this_host, show_default=True,
    help='The home hypervisor for this domain.'
)
def define_vm(xml_config_file, target_hypervisor):
    """
    Define a new virtual machine from a Libvirt XML configuration file.

    Notes:

    * The '--hypervisor' option defaults to the current host if not set, which is likely not what you want when running this command from a remote host!
    """
    define_domain(xml_config_file, target_hypervisor)


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
        click.echo("You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)

    # Set the VM to start
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
        click.echo("You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)

    # Set the VM to start
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
        click.echo("You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)

    # Set the VM to start
    zk.set('/domains/%s/state' % dom_uuid, 'stop'.encode('ascii'))

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
        click.echo("You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)

    current_hypervisor = zk.get('/domains/{}/hypervisor'.format(dom_uuid))[0].decode('ascii')
    last_hypervisor = zk.get('/domains/{}/lasthypervisor'.format(dom_uuid))[0].decode('ascii')

    if last_hypervisor != '' and force_migrate != True:
        click.echo('The VM "{}" has been previously migrated.'.format(dom_uuid))
        click.echo('> Last hypervisor: {}'.format(last_hypervisor))
        click.echo('> Current hypervisor: {}'.format(current_hypervisor))
        click.echo('Run `vm unmigrate` to restore the VM to its previous hypervisor, or use `--force` to override this check.')
        return

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
            click.echo('The VM "{}" is already running on hypervisor "{}".'.format(dom_uuid, current_hypervisor))
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
        click.echo("You must specify either a `--name` or `--uuid` value.")
        return

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)

    target_hypervisor = zk.get('/domains/{}/lasthypervisor'.format(dom_uuid))[0].decode('ascii')

    if target_hypervisor == '':
        click.echo('The VM "{}" has not been previously migrated.'.format(dom_uuid))
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
# pvc search
###############################################################################
@click.command(name='search', short_help='Search for a VM object')
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
def search(dom_name, dom_uuid, long_output):
    """
    Search the cluster for a virtual machine's information.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("You must specify either a `--name` or `--uuid` value.")
        return

    zk = pvcf.startZKConnection(zk_host)
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)
    if dom_uuid != None:
        dom_name = pvcf.searchClusterByUUID(zk, dom_uuid)

    information = pvcf.getInformationFromXML(zk, dom_uuid, long_output)

    if information == None:
        click.echo('Could not find a domain matching that name or UUID.')
        return

    click.echo(information)
    pvcf.stopZKConnection(zk)


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
    '-z', '--zookeeper', '_zk_host', envvar='PVC_ZOOKEEPER', default='{}:2181'.format(this_host), show_default=True,
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

vm.add_command(define_vm)
vm.add_command(start_vm)
vm.add_command(shutdown_vm)
vm.add_command(stop_vm)
vm.add_command(migrate_vm)
vm.add_command(unmigrate_vm)

cli.add_command(node)
cli.add_command(vm)
cli.add_command(search)
cli.add_command(init_cluster)

#
# Main entry point
#
def main():
    return cli(obj={})

if __name__ == '__main__':
    main()
