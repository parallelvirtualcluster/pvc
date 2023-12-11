#!/usr/bin/env python3

# fencing.py - Utility functions for pvcnoded fencing
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2022 Joshua M. Boniface <joshua@boniface.me>
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

from daemon_lib.vm import vm_worker_flush_locks


#
# Fence thread entry function
#
def fence_node(node_name, zkhandler, config, logger):
    # We allow exactly 6 saving throws (30 seconds) for the host to come back online or we kill it
    failcount_limit = 6
    failcount = 0
    while failcount < failcount_limit:
        # Wait 5 seconds
        time.sleep(config["keepalive_interval"])
        # Get the state
        node_daemon_state = zkhandler.read(("node.state.daemon", node_name))
        # Is it still 'dead'
        if node_daemon_state == "dead":
            failcount += 1
            logger.out(
                f"Node {node_name} failed {failcount}/{failcount_limit} saving throws",
                state="s",
                prefix=f"fencing {node_name}",
            )
        # It changed back to something else so it must be alive
        else:
            logger.out(
                f"Node {node_name} passed a saving throw; cancelling fance",
                state="o",
                prefix=f"fencing {node_name}",
            )
            return

    logger.out(
        f"Fencing node {node_name} via IPMI reboot signal",
        state="s",
        prefix=f"fencing {node_name}",
    )

    # Get IPMI information
    ipmi_hostname = zkhandler.read(("node.ipmi.hostname", node_name))
    ipmi_username = zkhandler.read(("node.ipmi.username", node_name))
    ipmi_password = zkhandler.read(("node.ipmi.password", node_name))

    # Shoot it in the head
    fence_status = reboot_via_ipmi(
        node_name, ipmi_hostname, ipmi_username, ipmi_password, logger
    )

    # Hold to ensure the fence takes effect and system stabilizes
    logger.out(
        f"Waiting {config['keepalive_interval']}s for fence of node {node_name} to take effect",
        state="i",
        prefix=f"fencing {node_name}",
    )
    time.sleep(config["keepalive_interval"])

    if fence_status:
        logger.out(
            f"Marking node {node_name} as fenced",
            state="i",
            prefix=f"fencing {node_name}",
        )
        while True:
            try:
                zkhandler.write([(("node.state.daemon", node_name), "fenced")])
                break
            except Exception:
                continue

    # Force into secondary network state if needed
    if node_name in config["coordinators"]:
        logger.out(
            f"Forcing secondary coordinator state for node {node_name}",
            state="i",
            prefix=f"fencing {node_name}",
        )
        zkhandler.write([(("node.state.router", node_name), "secondary")])
        if zkhandler.read("base.config.primary_node") == node_name:
            zkhandler.write([("base.config.primary_node", "none")])

    # If the fence succeeded and successful_fence is migrate
    if fence_status and config["successful_fence"] == "migrate":
        migrateFromFencedNode(zkhandler, node_name, config, logger)

    # If the fence failed and failed_fence is migrate
    if (
        not fence_status
        and config["failed_fence"] == "migrate"
        and config["suicide_intervals"] != "0"
    ):
        migrateFromFencedNode(zkhandler, node_name, config, logger)

    # Reset all node resource values
    logger.out(
        f"Resetting all resource values for dead node {node_name} to zero",
        state="i",
        prefix=f"fencing {node_name}",
    )
    zkhandler.write(
        [
            (("node.running_domains", node_name), "0"),
            (("node.count.provisioned_domains", node_name), "0"),
            (("node.cpu.load", node_name), "0"),
            (("node.vcpu.allocated", node_name), "0"),
            (("node.memory.total", node_name), "0"),
            (("node.memory.used", node_name), "0"),
            (("node.memory.free", node_name), "0"),
            (("node.memory.allocated", node_name), "0"),
            (("node.memory.provisioned", node_name), "0"),
            (("node.monitoring.health", node_name), None),
        ]
    )


# Migrate hosts away from a fenced node
def migrateFromFencedNode(zkhandler, node_name, config, logger):
    logger.out(
        f"Migrating VMs from dead node {node_name} to new hosts",
        state="i",
        prefix=f"fencing {node_name}",
    )

    # Get the list of VMs
    dead_node_running_domains = zkhandler.read(
        ("node.running_domains", node_name)
    ).split()

    # Set the node to a custom domainstate so we know what's happening
    zkhandler.write([(("node.state.domain", node_name), "fence-flush")])

    # Migrate a VM after a flush
    def fence_migrate_vm(dom_uuid):
        logger.out(
            f"Flushing locks of VM {dom_uuid} due to fence",
            state="i",
            prefix=f"fencing {node_name}",
        )
        vm_worker_flush_locks(zkhandler, None, dom_uuid, force_unlock=True)

        target_node = common.findTargetNode(zkhandler, dom_uuid)

        if target_node is not None:
            logger.out(
                f"Migrating VM {dom_uuid} to node {target_node}",
                state="i",
                prefix=f"fencing {node_name}",
            )
            zkhandler.write(
                [
                    (("domain.state", dom_uuid), "start"),
                    (("domain.node", dom_uuid), target_node),
                    (("domain.last_node", dom_uuid), node_name),
                ]
            )
            logger.out(
                f"Successfully migrated running VM {dom_uuid} to node {target_node}",
                state="o",
                prefix=f"fencing {node_name}",
            )
        else:
            logger.out(
                f"No target node found for VM {dom_uuid}; marking autostart=True on current node",
                state="i",
                prefix=f"fencing {node_name}",
            )
            zkhandler.write(
                {
                    (("domain.state", dom_uuid), "stopped"),
                    (("domain.meta.autostart", dom_uuid), "True"),
                }
            )
            logger.out(
                f"Successfully marked autostart for running VM {dom_uuid} on current node",
                state="o",
                prefix=f"fencing {node_name}",
            )

    # Loop through the VMs
    for dom_uuid in dead_node_running_domains:
        try:
            fence_migrate_vm(dom_uuid)
        except Exception as e:
            logger.out(
                f"Failed to migrate VM {dom_uuid}, continuing: {e}",
                state="w",
                prefix=f"fencing {node_name}",
            )

    # Set node in flushed state for easy remigrating when it comes back
    zkhandler.write([(("node.state.domain", node_name), "flushed")])
    logger.out(
        f"All VMs flushed from dead node {node_name} to other nodes",
        state="i",
        prefix=f"fencing {node_name}",
    )


#
# Perform an IPMI fence
#
def reboot_via_ipmi(node_name, ipmi_hostname, ipmi_user, ipmi_password, logger):
    # Power off the node the node
    logger.out(
        "Sending power off to dead node",
        state="i",
        prefix=f"fencing {node_name}",
    )
    ipmi_stop_retcode, ipmi_stop_stdout, ipmi_stop_stderr = common.run_os_command(
        f"/usr/bin/ipmitool -I lanplus -H {ipmi_hostname} -U {ipmi_user} -P {ipmi_password} chassis power off"
    )
    if ipmi_stop_retcode != 0:
        logger.out(
            f"Failed to power off dead node: {ipmi_stop_stderr}",
            state="e",
            prefix=f"fencing {node_name}",
        )

    logger.out(
        "Waiting 5s for power off to take effect",
        state="i",
        prefix=f"fencing {node_name}",
    )
    time.sleep(5)

    # Check the chassis power state
    logger.out(
        "Checking power state of dead node",
        state="i",
        prefix=f"fencing {node_name}",
    )
    ipmi_status_retcode, ipmi_status_stdout, ipmi_status_stderr = common.run_os_command(
        f"/usr/bin/ipmitool -I lanplus -H {ipmi_hostname} -U {ipmi_user} -P {ipmi_password} chassis power status"
    )
    if ipmi_status_retcode == 0:
        logger.out(
            f"Current chassis power state is: {ipmi_status_stdout.strip()}",
            state="i",
            prefix=f"fencing {node_name}",
        )
    else:
        logger.out(
            "Current chassis power state is: Unknown",
            state="w",
            prefix=f"fencing {node_name}",
        )

    # Power on the node
    logger.out(
        "Sending power on to dead node",
        state="i",
        prefix=f"fencing {node_name}",
    )
    ipmi_start_retcode, ipmi_start_stdout, ipmi_start_stderr = common.run_os_command(
        f"/usr/bin/ipmitool -I lanplus -H {ipmi_hostname} -U {ipmi_user} -P {ipmi_password} chassis power on"
    )

    if ipmi_start_retcode != 0:
        logger.out(
            f"Failed to power on dead node: {ipmi_start_stderr}",
            state="w",
            prefix=f"fencing {node_name}",
        )

    logger.out(
        "Waiting 2s for power on to take effect",
        state="i",
        prefix=f"fencing {node_name}",
    )
    time.sleep(2)

    # Check the chassis power state
    logger.out(
        "Checking power state of dead node",
        state="i",
        prefix=f"fencing {node_name}",
    )
    ipmi_status_retcode, ipmi_status_stdout, ipmi_status_stderr = common.run_os_command(
        f"/usr/bin/ipmitool -I lanplus -H {ipmi_hostname} -U {ipmi_user} -P {ipmi_password} chassis power status"
    )

    if ipmi_stop_retcode == 0:
        if ipmi_status_stdout.strip() == "Chassis Power is on":
            # We successfully rebooted the node and it is powered on; this is a succeessful fence
            logger.out(
                "Successfully rebooted dead node; proceeding with fence recovery action",
                state="o",
                prefix=f"fencing {node_name}",
            )
            return True
        elif ipmi_status_stdout.strip() == "Chassis Power is off":
            # We successfully rebooted the node but it is powered off; this might be expected or not, but the node is confirmed off so we can call it a successful fence
            logger.out(
                "Chassis power is in confirmed off state after successfuly IPMI reboot; proceeding with fence recovery action",
                state="o",
                prefix=f"fencing {node_name}",
            )
            return True
        else:
            # We successfully rebooted the node but it is in some unknown power state; since this might indicate a silent failure, we must call it a failed fence
            logger.out(
                f"Chassis power is in an unknown state ({ipmi_status_stdout.strip()}) after successful IPMI reboot; NOT proceeding fence recovery action",
                state="e",
                prefix=f"fencing {node_name}",
            )
            return False
    else:
        if ipmi_status_stdout.strip() == "Chassis Power is off":
            # We failed to reboot the node but it is powered off; it has probably suffered a serious hardware failure, but the node is confirmed off so we can call it a successful fence
            logger.out(
                "Chassis power is in confirmed off state after failed IPMI reboot; proceeding with fence recovery action",
                state="o",
                prefix=f"fencing {node_name}",
            )
            return True
        else:
            # We failed to reboot the node but it is in some unknown power state (including "on"); since this might indicate a silent failure, we must call it a failed fence
            logger.out(
                "Chassis power is not in confirmed off state after failed IPMI reboot; NOT proceeding wiht fence recovery action",
                state="e",
                prefix=f"fencing {node_name}",
            )
            return False


#
# Verify that IPMI connectivity to this host exists (used during node init)
#
def verify_ipmi(ipmi_hostname, ipmi_user, ipmi_password):
    ipmi_command = f"/usr/bin/ipmitool -I lanplus -H {ipmi_hostname} -U {ipmi_user} -P {ipmi_password} chassis power status"
    retcode, stdout, stderr = common.run_os_command(ipmi_command, timeout=2)
    if retcode == 0 and stdout.strip() == "Chassis Power is on":
        return True
    else:
        return False
