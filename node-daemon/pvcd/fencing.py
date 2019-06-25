#!/usr/bin/env python3

# fencing.py - PVC daemon function library, node fencing functions
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

import time
import threading

import pvcd.zkhandler as zkhandler
import pvcd.common as common

#
# Fence thread entry function
#
def fenceNode(node_name, zk_conn, config, logger):
    failcount = 0
    # We allow exactly 3 saving throws for the host to come back online
    while failcount < 3:
        # Wait 5 seconds
        time.sleep(5)
        # Get the state
        node_daemon_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(node_name))
        # Is it still 'dead'
        if node_daemon_state == 'dead':
            failcount += 1
            logger.out('Node "{}" failed {} saving throws'.format(node_name, failcount), state='w')
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
    # Hold to ensure the fence takes effect
    time.sleep(3)

    # Force into secondary network state if needed
    if node_name in config['coordinators']:
        zkhandler.writedata(zk_conn, { '/nodes/{}/routerstate'.format(node_name): 'secondary' })
        if zkhandler.readdata(zk_conn, '/primary_node') == node_name:
            zkhandler.writedata(zk_conn, { '/primary_node': 'none' })
        
    # If the fence succeeded and successful_fence is migrate
    if fence_status == True and config['successful_fence'] == 'migrate':
        migrateFromFencedNode(zk_conn, node_name, logger)

    # If the fence failed and failed_fence is migrate
    if fence_status == False and config['failed_fence'] == 'migrate' and config['suicide_intervals'] != '0':
        migrateFromFencedNode(zk_conn, node_name, logger)

# Migrate hosts away from a fenced node
def migrateFromFencedNode(zk_conn, node_name, logger):
    logger.out('Moving VMs from dead node "{}" to new hosts'.format(node_name), state='i')
    dead_node_running_domains = zkhandler.readdata(zk_conn, '/nodes/{}/runningdomains'.format(node_name)).split()
    for dom_uuid in dead_node_running_domains:
        target_node = findTargetHypervisor(zk_conn, 'mem', dom_uuid)

        logger.out('Flushing RBD locks for VM "{}"'.format(dom_uuid), state='i')
        # TO BE IMPLEMENTED once RBD pools are integrated properly

        logger.out('Moving VM "{}" to node "{}"'.format(dom_uuid, target_node), state='i')
        zkhandler.writedata(zk_conn, {
            '/domains/{}/state'.format(dom_uuid): 'start',
            '/domains/{}/node'.format(dom_uuid): target_node,
            '/domains/{}/lastnode'.format(dom_uuid): node_name
        })

    # Set node in flushed state for easy remigrating when it comes back
    zkhandler.writedata(zk_conn, { '/nodes/{}/domainstate'.format(node_name): 'flushed' })

#
# Perform an IPMI fence
#
def rebootViaIPMI(ipmi_hostname, ipmi_user, ipmi_password, logger):
    # Forcibly reboot the node
    ipmi_command_reset = '/usr/bin/ipmitool -I lanplus -H {} -U {} -P {} chassis power reset'.format(
        ipmi_hostname, ipmi_user, ipmi_password
    )
    ipmi_reset_retcode, ipmi_reset_stdout, ipmi_reset_stderr = common.run_os_command(ipmi_command_reset)

    time.sleep(0.5)

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
        return False
