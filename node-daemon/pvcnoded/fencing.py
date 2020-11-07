#!/usr/bin/env python3

# fencing.py - PVC daemon function library, node fencing functions
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

import pvcnoded.zkhandler as zkhandler
import pvcnoded.common as common
import pvcnoded.VMInstance as VMInstance


#
# Fence thread entry function
#
def fenceNode(node_name, zk_conn, config, logger):
    # We allow exactly 6 saving throws (30 seconds) for the host to come back online or we kill it
    failcount_limit = 6
    failcount = 0
    while failcount < failcount_limit:
        # Wait 5 seconds
        time.sleep(config['keepalive_interval'])
        # Get the state
        node_daemon_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(node_name))
        # Is it still 'dead'
        if node_daemon_state == 'dead':
            failcount += 1
            logger.out('Node "{}" failed {}/{} saving throws'.format(node_name, failcount, failcount_limit), state='w')
        # It changed back to something else so it must be alive
        else:
            logger.out('Node "{}" passed a saving throw; canceling fence'.format(node_name), state='o')
            return

    logger.out('Fencing node "{}" via IPMI reboot signal'.format(node_name), state='w')

    # Get IPMI information
    ipmi_hostname = zkhandler.readdata(zk_conn, '/nodes/{}/ipmihostname'.format(node_name))
    ipmi_username = zkhandler.readdata(zk_conn, '/nodes/{}/ipmiusername'.format(node_name))
    ipmi_password = zkhandler.readdata(zk_conn, '/nodes/{}/ipmipassword'.format(node_name))

    # Shoot it in the head
    fence_status = rebootViaIPMI(ipmi_hostname, ipmi_username, ipmi_password, logger)
    # Hold to ensure the fence takes effect and system stabilizes
    time.sleep(config['keepalive_interval'] * 2)

    # Force into secondary network state if needed
    if node_name in config['coordinators']:
        logger.out('Forcing secondary status for node "{}"'.format(node_name), state='i')
        zkhandler.writedata(zk_conn, {'/nodes/{}/routerstate'.format(node_name): 'secondary'})
        if zkhandler.readdata(zk_conn, '/primary_node') == node_name:
            zkhandler.writedata(zk_conn, {'/primary_node': 'none'})

    # If the fence succeeded and successful_fence is migrate
    if fence_status and config['successful_fence'] == 'migrate':
        migrateFromFencedNode(zk_conn, node_name, config, logger)

    # If the fence failed and failed_fence is migrate
    if not fence_status and config['failed_fence'] == 'migrate' and config['suicide_intervals'] != '0':
        migrateFromFencedNode(zk_conn, node_name, config, logger)


# Migrate hosts away from a fenced node
def migrateFromFencedNode(zk_conn, node_name, config, logger):
    logger.out('Migrating VMs from dead node "{}" to new hosts'.format(node_name), state='i')

    # Get the list of VMs
    dead_node_running_domains = zkhandler.readdata(zk_conn, '/nodes/{}/runningdomains'.format(node_name)).split()

    # Set the node to a custom domainstate so we know what's happening
    zkhandler.writedata(zk_conn, {'/nodes/{}/domainstate'.format(node_name): 'fence-flush'})

    # Migrate a VM after a flush
    def fence_migrate_vm(dom_uuid):
        VMInstance.flush_locks(zk_conn, logger, dom_uuid)

        target_node = common.findTargetNode(zk_conn, config, logger, dom_uuid)

        if target_node is not None:
            logger.out('Migrating VM "{}" to node "{}"'.format(dom_uuid, target_node), state='i')
            zkhandler.writedata(zk_conn, {
                '/domains/{}/state'.format(dom_uuid): 'start',
                '/domains/{}/node'.format(dom_uuid): target_node,
                '/domains/{}/lastnode'.format(dom_uuid): node_name
            })
        else:
            logger.out('No target node found for VM "{}"; VM will autostart on next unflush/ready of current node'.format(dom_uuid), state='i')
            zkhandler.writedata(zk_conn, {
                '/domains/{}/state'.format(dom_uuid): 'stopped',
                '/domains/{}/node_autostart'.format(dom_uuid): 'True'
            })

    # Loop through the VMs
    for dom_uuid in dead_node_running_domains:
        fence_migrate_vm(dom_uuid)

    # Set node in flushed state for easy remigrating when it comes back
    zkhandler.writedata(zk_conn, {'/nodes/{}/domainstate'.format(node_name): 'flushed'})


#
# Perform an IPMI fence
#
def rebootViaIPMI(ipmi_hostname, ipmi_user, ipmi_password, logger):
    # Forcibly reboot the node
    ipmi_command_reset = '/usr/bin/ipmitool -I lanplus -H {} -U {} -P {} chassis power reset'.format(
        ipmi_hostname, ipmi_user, ipmi_password
    )
    ipmi_reset_retcode, ipmi_reset_stdout, ipmi_reset_stderr = common.run_os_command(ipmi_command_reset)

    time.sleep(2)

    # Ensure the node is powered on
    ipmi_command_status = '/usr/bin/ipmitool -I lanplus -H {} -U {} -P {} chassis power status'.format(
        ipmi_hostname, ipmi_user, ipmi_password
    )
    ipmi_status_retcode, ipmi_status_stdout, ipmi_status_stderr = common.run_os_command(ipmi_command_status)

    # Trigger a power start if needed
    if ipmi_status_stdout != "Chassis Power is on":
        ipmi_command_start = '/usr/bin/ipmitool -I lanplus -H {} -U {} -P {} chassis power on'.format(
            ipmi_hostname, ipmi_user, ipmi_password
        )
        ipmi_start_retcode, ipmi_start_stdout, ipmi_start_stderr = common.run_os_command(ipmi_command_start)

    # Declare success or failure
    if ipmi_reset_retcode == 0:
        logger.out('Successfully rebooted dead node', state='o')
        return True
    else:
        logger.out('Failed to reboot dead node', state='e')
        print(ipmi_reset_stderr)
        return False


#
# Verify that IPMI connectivity to this host exists (used during node init)
#
def verifyIPMI(ipmi_hostname, ipmi_user, ipmi_password):
    ipmi_command_status = '/usr/bin/ipmitool -I lanplus -H {} -U {} -P {} chassis power status'.format(
        ipmi_hostname, ipmi_user, ipmi_password
    )
    ipmi_status_retcode, ipmi_status_stdout, ipmi_status_stderr = common.run_os_command(ipmi_command_status, timeout=2)
    if ipmi_status_retcode == 0 and ipmi_status_stdout != "Chassis Power is on":
        return True
    else:
        return False
