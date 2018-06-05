#!/usr/bin/env python3

import kazoo.client, socket, time, click
import pvcf
from lxml import objectify

zk_host = '127.0.0.1:2181'

this_host = socket.gethostname()

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

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
    transaction.create('/domains/%s/formerhypervisor' % domuuid, ''.encode('ascii'))
    transaction.create('/domains/%s/name' % domuuid, data.encode('ascii'))
    transaction.create('/domains/%s/xml' % domuuid, data.encode('ascii'))
    results = transaction.commit()
    print(results)
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
    transaction.delete('/domains/%s/formerhypervisor' % domuuid)
    transaction.delete('/domains/%s/xml' % domuuid)
    transaction.delete('/domains/%s' % domuuid)
    results = transaction.commit()
    print(results)
    pvcf.stopZKConnection(zk)

# Start up a domain
def start_domain(domuuid):
    zk = pvcf.startZKConnection(zk_host)
    transaction = zk.transaction()
    transaction.set_data('/domains/%s/state' % domuuid, 'start'.encode('ascii'))
    results = transaction.commit()
    print(results)
    pvcf.stopZKConnection(zk)

# Shut down a domain
def shutdown_domain(domuuid):
    zk = pvcf.startZKConnection(zk_host)
    transaction = zk.transaction()
    transaction.set_data('/domains/%s/state' % domuuid, 'shutdown'.encode('ascii'))
    results = transaction.commit()
    print(results)
    pvcf.stopZKConnection(zk)

# Stop a domain
def stop_domain(domuuid):
    zk = pvcf.startZKConnection(zk_host)
    transaction = zk.transaction()
    transaction.set_data('/domains/%s/state' % domuuid, 'stop'.encode('ascii'))
    results = transaction.commit()
    print(results)
    pvcf.stopZKConnection(zk)

# Migrate VM to target_hypervisor
def migrate_domain(domuuid, target_hypervisor):
    zk = pvcf.startZKConnection(zk_host)
    current_hypervisor = zk.get('/domains/%s/hypervisor' % domuuid)[0].decode('ascii')
    former_hypervisor = zk.get('/domains/%s/formerhypervisor' % domuuid)[0].decode('ascii')
    if former_hypervisor != '':
        print('The VM %s has been previously migrated from %s to %s. You must unmigrate it before migrating it again!' % (domuuid, former_hypervisor, current_hypervisor))
        pvcf.stopZKConnection(zk)
        return

    print('Migrating VM with UUID %s from hypervisor %s to hypervisor %s' % (domuuid, current_hypervisor, target_hypervisor))
    transaction = zk.transaction()
    transaction.set_data('/domains/%s/state' % domuuid, 'migrate'.encode('ascii'))
    transaction.set_data('/domains/%s/hypervisor' % domuuid, target_hypervisor.encode('ascii'))
    transaction.set_data('/domains/%s/formerhypervisor' % domuuid, current_hypervisor.encode('ascii'))
    results = transaction.commit()
    print(results)
    pvcf.stopZKConnection(zk)

# Unmigrate VM back from previous hypervisor
def unmigrate_domain(domuuid):
    zk = pvcf.startZKConnection(zk_host)
    target_hypervisor = zk.get('/domains/%s/formerhypervisor' % domuuid)[0].decode('ascii')
    if target_hypervisor == '':
        print('The VM %s has not been previously migrated and cannot be unmigrated.' % domuuid)
        pvcf.stopZKConnection(zk)
        return
    print('Unmigrating VM with UUID %s back to hypervisor %s' % (domuuid, target_hypervisor))
    transaction = zk.transaction()
    transaction.set_data('/domains/%s/state' % domuuid, 'migrate'.encode('ascii'))
    transaction.set_data('/domains/%s/hypervisor' % domuuid, target_hypervisor.encode('ascii'))
    transaction.set_data('/domains/%s/formerhypervisor' % domuuid, ''.encode('ascii'))
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
    mutually_exclusive=["dom_uuid"],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=["dom_name"],
    help='Search for this UUID.'
)
def start_vm(dom_name, dom_uuid):
    """
    Start up a virtual machine on its configured hypervisor.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("You must specify either a '--name' or '--uuid' value.")
        return

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)

    # Set the VM to start
    zk.set('/domains/%s/state' % dom_uuid, 'start'.encode('ascii'))

    # Close the zookeeper connection
    pvcf.stopZKConnection(zk)


###############################################################################
# pvc vm shutdown
###############################################################################
@click.command(name='shutdown', short_help='Gracefully shut down a running virtual machine.')
@click.option(
    '-n', '--name', 'dom_name',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=["dom_uuid"],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=["dom_name"],
    help='Search for this UUID.'
)
def shutdown_vm(dom_name, dom_uuid):
    """
    Gracefully shut down a running virtual machine.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("You must specify either a '--name' or '--uuid' value.")
        return

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)

    # Set the VM to start
    zk.set('/domains/%s/state' % dom_uuid, 'shutdown'.encode('ascii'))

    # Close the zookeeper connection
    pvcf.stopZKConnection(zk)


###############################################################################
# pvc vm stop
###############################################################################
@click.command(name='stop', short_help='Forcibly halt a running virtual machine.')
@click.option(
    '-n', '--name', 'dom_name',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=["dom_uuid"],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=["dom_name"],
    help='Search for this UUID.'
)
def stop_vm(dom_name, dom_uuid):
    """
    Forcibly halt (destroy) a running virtual machine.
    """

    # Ensure at least one search method is set
    if dom_name == None and dom_uuid == None:
        click.echo("You must specify either a '--name' or '--uuid' value.")
        return

    # Open a Zookeeper connection
    zk = pvcf.startZKConnection(zk_host)

    # If the --name value was passed, get the UUID
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)

    # Set the VM to start
    zk.set('/domains/%s/state' % dom_uuid, 'stop'.encode('ascii'))

    # Close the zookeeper connection
    pvcf.stopZKConnection(zk)


@click.command(name='migrate', short_help='Migrate a virtual machine to another node.')
def migrate_vm():
    """
    Migrate a running virtual machine, via live migration if possible, to another hypervisor node.
    """
    pass

@click.command(name='unmigrate', short_help='Restore a migrated virtual machine to its original node.')
def unmigrate_vm():
    """
    Restore a previously migrated virtual machine, via live migration if possible, to its original hypervisor node.
    """
    pass

#
# Search-level commands
#
@click.command(name='search', short_help='Search for a VM object')
@click.option(
    '-n', '--name', 'dom_name',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=["dom_uuid"],
    help='Search for this human-readable name.'
)
@click.option(
    '-u', '--uuid', 'dom_uuid',
    cls=pvcf.MutuallyExclusiveOption,
    mutually_exclusive=["dom_name"],
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
    zk = pvcf.startZKConnection(zk_host)
    if dom_name != None:
        dom_uuid = pvcf.searchClusterByName(zk, dom_name)
    if dom_uuid != None:
        dom_name = pvcf.searchClusterByUUID(zk, dom_uuid)

    information = pvcf.getInformationFromXML(zk, dom_uuid, long_output)
    click.echo(information)
    pvcf.stopZKConnection(zk)

#define_domain('/var/home/joshua/debian9.xml')
#start_domain('b1dc4e21-544f-47aa-9bb7-8af0bc443b78')
#stop_domain('b1dc4e21-544f-47aa-9bb7-8af0bc443b78')
#migrate_domain('b1dc4e21-544f-47aa-9bb7-8af0bc443b78', 'test1.i.bonilan.net')
#migrate_domain('b1dc4e21-544f-47aa-9bb7-8af0bc443b78', 'test2.i.bonilan.net')
#unmigrate_domain('b1dc4e21-544f-47aa-9bb7-8af0bc443b78')

@click.command()
def help():
    print('pvc - Parallel Virtual Cluster command-line utility')

@click.group(context_settings=CONTEXT_SETTINGS)
def cli():
	"""Parallel Virtual Cluster CLI management tool"""
	pass

#
# Click command tree
#
node.add_command(flush_host)
node.add_command(ready_host)
#node.add_command(get_details)

vm.add_command(define_vm)
vm.add_command(start_vm)
vm.add_command(shutdown_vm)
vm.add_command(stop_vm)
vm.add_command(migrate_vm)
vm.add_command(unmigrate_vm)
#vm.add_command(get_details)

cli.add_command(node)
cli.add_command(vm)
cli.add_command(search)

#
# Main entry point
#
def main():
    return cli(obj={})

if __name__ == '__main__':
    main()
