#!/usr/bin/env python3

# fencing.py - Utility functions for pvcnoded fencing
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2021 Joshua M. Boniface <joshua@boniface.me>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, version 3.
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

import daemon_lib.common as common

from pvcnoded.objects.VMInstance import VMInstance


#
# Fence thread entry function
#
def fence_node(node_name, zkhandler, config, logger):
    # We allow exactly 6 saving throws (30 seconds) for the host to come back online or we kill it
    failcount_limit = 6
    failcount = 0
    while failcount < failcount_limit:
        # Wait 5 seconds
        time.sleep(config['keepalive_interval'])
        # Get the state
        node_daemon_state = zkhandler.read(('node.state.daemon', node_name))
        # Is it still 'dead'
        if node_daemon_state == 'dead':
            failcount += 1
            logger.out('Node "{}" failed {}/{} saving throws'.format(node_name, failcount, failcount_limit), state='s')
        # It changed back to something else so it must be alive
        else:
            logger.out('Node "{}" passed a saving throw; canceling fence'.format(node_name), state='o')
            return

    logger.out('Fencing node "{}" via IPMI reboot signal'.format(node_name), state='s')

    # Get IPMI information
    ipmi_hostname = zkhandler.read(('node.ipmi.hostname', node_name))
    ipmi_username = zkhandler.read(('node.ipmi.username', node_name))
    ipmi_password = zkhandler.read(('node.ipmi.password', node_name))

    # Shoot it in the head
    fence_status = reboot_via_ipmi(ipmi_hostname, ipmi_username, ipmi_password, logger)
    # Hold to ensure the fence takes effect and system stabilizes
    time.sleep(config['keepalive_interval'] * 2)

    # Force into secondary network state if needed
    if node_name in config['coordinators']:
        logger.out('Forcing secondary status for node "{}"'.format(node_name), state='i')
        zkhandler.write([
            (('node.state.router', node_name), 'secondary')
        ])
        if zkhandler.read('base.config.primary_node') == node_name:
            zkhandler.write([
                ('base.config.primary_node', 'none')
            ])

    # If the fence succeeded and successful_fence is migrate
    if fence_status and config['successful_fence'] == 'migrate':
        migrateFromFencedNode(zkhandler, node_name, config, logger)

    # If the fence failed and failed_fence is migrate
    if not fence_status and config['failed_fence'] == 'migrate' and config['suicide_intervals'] != '0':
        migrateFromFencedNode(zkhandler, node_name, config, logger)


# Migrate hosts away from a fenced node
def migrateFromFencedNode(zkhandler, node_name, config, logger):
    logger.out('Migrating VMs from dead node "{}" to new hosts'.format(node_name), state='i')

    # Get the list of VMs
    dead_node_running_domains = zkhandler.read(('node.running_domains', node_name)).split()

    # Set the node to a custom domainstate so we know what's happening
    zkhandler.write([
        (('node.state.domain', node_name), 'fence-flush')
    ])

    # Migrate a VM after a flush
    def fence_migrate_vm(dom_uuid):
        VMInstance.flush_locks(zkhandler, logger, dom_uuid)

        target_node = common.findTargetNode(zkhandler, dom_uuid)

        if target_node is not None:
            logger.out('Migrating VM "{}" to node "{}"'.format(dom_uuid, target_node), state='i')
            zkhandler.write([
                (('domain.state', dom_uuid), 'start'),
                (('domain.node', dom_uuid), target_node),
                (('domain.last_node', dom_uuid), node_name),
            ])
        else:
            logger.out('No target node found for VM "{}"; VM will autostart on next unflush/ready of current node'.format(dom_uuid), state='i')
            zkhandler.write({
                (('domain.state', dom_uuid), 'stopped'),
                (('domain.meta.autostart', dom_uuid), 'True'),
            })

    # Loop through the VMs
    for dom_uuid in dead_node_running_domains:
        fence_migrate_vm(dom_uuid)

    # Set node in flushed state for easy remigrating when it comes back
    zkhandler.write([
        (('node.state.domain', node_name), 'flushed')
    ])


#
# Perform an IPMI fence
#
def reboot_via_ipmi(ipmi_hostname, ipmi_user, ipmi_password, logger):
    # Forcibly reboot the node
    ipmi_command_reset = '/usr/bin/ipmitool -I lanplus -H {} -U {} -P {} chassis power reset'.format(
        ipmi_hostname, ipmi_user, ipmi_password
    )
    ipmi_reset_retcode, ipmi_reset_stdout, ipmi_reset_stderr = common.run_os_command(ipmi_command_reset)

    if ipmi_reset_retcode != 0:
        logger.out(f'Failed to reboot dead node: {ipmi_reset_stderr}', state='e')

    time.sleep(1)

    # Power on the node (just in case it is offline)
    ipmi_command_start = '/usr/bin/ipmitool -I lanplus -H {} -U {} -P {} chassis power on'.format(
        ipmi_hostname, ipmi_user, ipmi_password
    )
    ipmi_start_retcode, ipmi_start_stdout, ipmi_start_stderr = common.run_os_command(ipmi_command_start)

    time.sleep(2)

    # Check the chassis power state
    logger.out('Checking power state of dead node', state='i')
    ipmi_command_status = '/usr/bin/ipmitool -I lanplus -H {} -U {} -P {} chassis power status'.format(
        ipmi_hostname, ipmi_user, ipmi_password
    )
    ipmi_status_retcode, ipmi_status_stdout, ipmi_status_stderr = common.run_os_command(ipmi_command_status)

    if ipmi_reset_retcode == 0:
        if ipmi_status_stdout == "Chassis Power is on":
            # We successfully rebooted the node and it is powered on; this is a succeessful fence
            logger.out('Successfully rebooted dead node', state='o')
            return True
        elif ipmi_status_stdout == "Chassis Power is off":
            # We successfully rebooted the node but it is powered off; this might be expected or not, but the node is confirmed off so we can call it a successful fence
            logger.out('Chassis power is in confirmed off state after successfuly IPMI reboot; proceeding with fence-flush', state='o')
            return True
        else:
            # We successfully rebooted the node but it is in some unknown power state; since this might indicate a silent failure, we must call it a failed fence
            logger.out('Chassis power is in an unknown state after successful IPMI reboot; not performing fence-flush', state='e')
            return False
    else:
        if ipmi_status_stdout == "Chassis Power is off":
            # We failed to reboot the node but it is powered off; it has probably suffered a serious hardware failure, but the node is confirmed off so we can call it a successful fence
            logger.out('Chassis power is in confirmed off state after failed IPMI reboot; proceeding with fence-flush', state='o')
            return True
        else:
            # We failed to reboot the node but it is in some unknown power state (including "on"); since this might indicate a silent failure, we must call it a failed fence
            logger.out('Chassis power is not in confirmed off state after failed IPMI reboot; not performing fence-flush', state='e')
            return False


#
# Verify that IPMI connectivity to this host exists (used during node init)
#
def verify_ipmi(ipmi_hostname, ipmi_user, ipmi_password):
    ipmi_command = f'/usr/bin/ipmitool -I lanplus -H {ipmi_hostname} -U {ipmi_user} -P {ipmi_password} chassis power status'
    retcode, stdout, stderr = common.run_os_command(ipmi_command, timeout=2)
    if retcode == 0 and stdout != "Chassis Power is on":
        return True
    else:
        return False