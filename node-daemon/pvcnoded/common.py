#!/usr/bin/env python3

# common.py - PVC daemon function library, common fuctions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2020 Joshua M. Boniface <joshua@boniface.me>
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

import subprocess
import signal

from threading import Thread
from shlex import split as shlex_split

import pvcnoded.zkhandler as zkhandler


class OSDaemon(object):
    def __init__(self, command_string, environment, logfile):
        command = shlex_split(command_string)
        # Set stdout to be a logfile if set
        if logfile:
            stdout = open(logfile, 'a')
        else:
            stdout = subprocess.PIPE

        # Invoke the process
        self.proc = subprocess.Popen(
            command,
            env=environment,
            stdout=stdout,
            stderr=stdout,
        )

    # Signal the process
    def signal(self, sent_signal):
        signal_map = {
            'hup': signal.SIGHUP,
            'int': signal.SIGINT,
            'term': signal.SIGTERM,
            'kill': signal.SIGKILL
        }
        self.proc.send_signal(signal_map[sent_signal])


def run_os_daemon(command_string, environment=None, logfile=None):
    daemon = OSDaemon(command_string, environment, logfile)
    return daemon


# Run a oneshot command, optionally without blocking
def run_os_command(command_string, background=False, environment=None, timeout=None):
    command = shlex_split(command_string)
    if background:
        def runcmd():
            try:
                subprocess.run(
                    command,
                    env=environment,
                    timeout=timeout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except subprocess.TimeoutExpired:
                pass
        thread = Thread(target=runcmd, args=())
        thread.start()
        return 0, None, None
    else:
        try:
            command_output = subprocess.run(
                command,
                env=environment,
                timeout=timeout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            retcode = command_output.returncode
        except subprocess.TimeoutExpired:
            retcode = 128

        try:
            stdout = command_output.stdout.decode('ascii')
        except Exception:
            stdout = ''
        try:
            stderr = command_output.stderr.decode('ascii')
        except Exception:
            stderr = ''
        return retcode, stdout, stderr


# Reload the firewall rules of the system
def reload_firewall_rules(logger, rules_file):
    logger.out('Reloading firewall configuration', state='o')
    retcode, stdout, stderr = run_os_command('/usr/sbin/nft -f {}'.format(rules_file))
    if retcode != 0:
        logger.out('Failed to reload configuration: {}'.format(stderr), state='e')


# Create IP address
def createIPAddress(ipaddr, cidrnetmask, dev):
    run_os_command(
        'ip address add {}/{} dev {}'.format(
            ipaddr,
            cidrnetmask,
            dev
        )
    )
    run_os_command(
        'arping -P -U -W 0.02 -c 2 -i {dev} -S {ip} {ip}'.format(
            dev=dev,
            ip=ipaddr
        )
    )


# Remove IP address
def removeIPAddress(ipaddr, cidrnetmask, dev):
    run_os_command(
        'ip address delete {}/{} dev {}'.format(
            ipaddr,
            cidrnetmask,
            dev
        )
    )


#
# Find a migration target
#
def findTargetNode(zk_conn, config, logger, dom_uuid):
    # Determine VM node limits; set config value if read fails
    try:
        node_limit = zkhandler.readdata(zk_conn, '/domains/{}/node_limit'.format(dom_uuid)).split(',')
        if not any(node_limit):
            node_limit = ''
    except Exception:
        node_limit = ''
        zkhandler.writedata(zk_conn, {'/domains/{}/node_limit'.format(dom_uuid): ''})

    # Determine VM search field
    try:
        search_field = zkhandler.readdata(zk_conn, '/domains/{}/node_selector'.format(dom_uuid))
    except Exception:
        search_field = None

    # If our search field is invalid, use and set the default (for next time)
    if search_field is None or search_field == 'None':
        search_field = config['migration_target_selector']
        zkhandler.writedata(zk_conn, {'/domains/{}/node_selector'.format(dom_uuid): config['migration_target_selector']})

    if config['debug']:
        logger.out('Migrating VM {} with selector {}'.format(dom_uuid, search_field), state='d', prefix='node-flush')

    # Execute the search
    if search_field == 'mem':
        return findTargetNodeMem(zk_conn, config, logger, node_limit, dom_uuid)
    if search_field == 'load':
        return findTargetNodeLoad(zk_conn, config, logger, node_limit, dom_uuid)
    if search_field == 'vcpus':
        return findTargetNodeVCPUs(zk_conn, config, logger, node_limit, dom_uuid)
    if search_field == 'vms':
        return findTargetNodeVMs(zk_conn, config, logger, node_limit, dom_uuid)

    # Nothing was found
    return None


# Get the list of valid target nodes
def getNodes(zk_conn, node_limit, dom_uuid):
    valid_node_list = []
    full_node_list = zkhandler.listchildren(zk_conn, '/nodes')
    current_node = zkhandler.readdata(zk_conn, '/domains/{}/node'.format(dom_uuid))

    for node in full_node_list:
        if node_limit and node not in node_limit:
            continue

        daemon_state = zkhandler.readdata(zk_conn, '/nodes/{}/daemonstate'.format(node))
        domain_state = zkhandler.readdata(zk_conn, '/nodes/{}/domainstate'.format(node))

        if node == current_node:
            continue

        if daemon_state != 'run' or domain_state != 'ready':
            continue

        valid_node_list.append(node)

    return valid_node_list


# via free memory (relative to allocated memory)
def findTargetNodeMem(zk_conn, config, logger, node_limit, dom_uuid):
    most_provfree = 0
    target_node = None

    node_list = getNodes(zk_conn, node_limit, dom_uuid)
    if config['debug']:
        logger.out('Found nodes: {}'.format(node_list), state='d', prefix='node-flush')

    for node in node_list:
        memprov = int(zkhandler.readdata(zk_conn, '/nodes/{}/memprov'.format(node)))
        memused = int(zkhandler.readdata(zk_conn, '/nodes/{}/memused'.format(node)))
        memfree = int(zkhandler.readdata(zk_conn, '/nodes/{}/memfree'.format(node)))
        memtotal = memused + memfree
        provfree = memtotal - memprov

        if config['debug']:
            logger.out('Evaluating node {} with {} provfree'.format(node, provfree), state='d', prefix='node-flush')
        if provfree > most_provfree:
            most_provfree = provfree
            target_node = node

    if config['debug']:
        logger.out('Selected node {}'.format(target_node), state='d', prefix='node-flush')
    return target_node


# via load average
def findTargetNodeLoad(zk_conn, config, logger, node_limit, dom_uuid):
    least_load = 9999.0
    target_node = None

    node_list = getNodes(zk_conn, node_limit, dom_uuid)
    if config['debug']:
        logger.out('Found nodes: {}'.format(node_list), state='d', prefix='node-flush')

    for node in node_list:
        load = float(zkhandler.readdata(zk_conn, '/nodes/{}/cpuload'.format(node)))

        if config['debug']:
            logger.out('Evaluating node {} with load {}'.format(node, load), state='d', prefix='node-flush')
        if load < least_load:
            least_load = load
            target_node = node

    if config['debug']:
        logger.out('Selected node {}'.format(target_node), state='d', prefix='node-flush')
    return target_node


# via total vCPUs
def findTargetNodeVCPUs(zk_conn, config, logger, node_limit, dom_uuid):
    least_vcpus = 9999
    target_node = None

    node_list = getNodes(zk_conn, node_limit, dom_uuid)
    if config['debug']:
        logger.out('Found nodes: {}'.format(node_list), state='d', prefix='node-flush')

    for node in node_list:
        vcpus = int(zkhandler.readdata(zk_conn, '/nodes/{}/vcpualloc'.format(node)))

        if config['debug']:
            logger.out('Evaluating node {} with vcpualloc {}'.format(node, vcpus), state='d', prefix='node-flush')
        if vcpus < least_vcpus:
            least_vcpus = vcpus
            target_node = node

    if config['debug']:
        logger.out('Selected node {}'.format(target_node), state='d', prefix='node-flush')
    return target_node


# via total VMs
def findTargetNodeVMs(zk_conn, config, logger, node_limit, dom_uuid):
    least_vms = 9999
    target_node = None

    node_list = getNodes(zk_conn, node_limit, dom_uuid)
    if config['debug']:
        logger.out('Found nodes: {}'.format(node_list), state='d', prefix='node-flush')

    for node in node_list:
        vms = int(zkhandler.readdata(zk_conn, '/nodes/{}/domainscount'.format(node)))

        if config['debug']:
            logger.out('Evaluating node {} with VM count {}'.format(node, vms), state='d', prefix='node-flush')
        if vms < least_vms:
            least_vms = vms
            target_node = node

    if config['debug']:
        logger.out('Selected node {}'.format(target_node), state='d', prefix='node-flush')
    return target_node
