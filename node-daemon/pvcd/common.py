#!/usr/bin/env python3

# common.py - PVC daemon function library, common fuctions
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

import subprocess
import threading
import signal
import os
import time
import shlex

import pvcd.log as log
import pvcd.zkhandler as zkhandler

class OSDaemon(object):
    def __init__(self, command_string, environment, logfile):
        command = shlex.split(command_string)
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
    command = shlex.split(command_string)
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
        thread = threading.Thread(target=runcmd, args=())
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
        except:
            stdout = ''
        try:
            stderr = command_output.stderr.decode('ascii')
        except:
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
        'arping -A -c3 -I {dev} -P -U -S {ip} {ip}'.format(
            dev=dev,
            ip=ipaddr
        ),
        background=True
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
def findTargetNode(zk_conn, config, dom_uuid):
    # Determine VM node limits; set config value if read fails
    try:
        node_limit = zkhandler.readdata(zk_conn, '/domains/{}/node_limit'.format(dom_uuid)).split(',')
    except:
        node_limit = None
        zkhandler.writedata(zk_conn, { '/domains/{}/node_limit'.format(dom_uuid): 'None' })

    # Determine VM search field or use default; set config value if read fails
    try:
        search_field = zkhandler.readdata(zk_conn, '/domains/{}/node_selector'.format(dom_uuid))
    except:
        search_field = config.migration_target_selector
        zkhandler.writedata(zk_conn, { '/domains/{}/node_selector'.format(dom_uuid): config.migration_target_selector })

    # Execute the search
    if search_field == 'mem':
        return findTargetNodeMem(zk_conn, node_limit, dom_uuid)
    if search_field == 'load':
        return findTargetNodeLoad(zk_conn, node_limit, dom_uuid)
    if search_field == 'vcpus':
        return findTargetNodeVCPUs(zk_conn, node_limit, dom_uuid)
    if search_field == 'vms':
        return findTargetNodeVMs(zk_conn, node_limit, dom_uuid)

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
def findTargetNodeMem(zk_conn, node_limit, dom_uuid):
    most_allocfree = 0
    target_node = None

    node_list = getNodes(zk_conn, node_limit, dom_uuid)
    for node in node_list:
        memalloc = int(zkhandler.readdata(zk_conn, '/nodes/{}/memalloc'.format(node)))
        memused = int(zkhandler.readdata(zk_conn, '/nodes/{}/memused'.format(node)))
        memfree = int(zkhandler.readdata(zk_conn, '/nodes/{}/memfree'.format(node)))
        memtotal = memused + memfree
        allocfree = memtotal - memalloc

        if allocfree > most_allocfree:
            most_allocfree = allocfree
            target_node = node

    return target_node

# via load average
def findTargetNodeLoad(zk_conn, node_limit, dom_uuid):
    least_load = 9999
    target_node = None

    node_list = getNodes(zk_conn, node_limit, dom_uuid)
    for node in node_list:
        load = int(zkhandler.readdata(zk_conn, '/nodes/{}/load'.format(node)))

        if load < least_load:
            least_load = load
            target_hypevisor = node

    return target_node

# via total vCPUs
def findTargetNodeVCPUs(zk_conn, node_limit, dom_uuid):
    least_vcpus = 9999
    target_node = None

    node_list = getNodes(zk_conn, node_limit, dom_uuid)
    for node in node_list:
        vcpus = int(zkhandler.readdata(zk_conn, '/nodes/{}/vcpualloc'.format(node)))

        if vcpus < least_vcpus:
            least_vcpus = vcpus
            target_node = node

    return target_node

# via total VMs
def findTargetNodeVMs(zk_conn, node_limit, dom_uuid):
    least_vms = 9999
    target_node = None

    node_list = getNodes(zk_conn, node_limit, dom_uuid)
    for node in node_list:
        vms = int(zkhandler.readdata(zk_conn, '/nodes/{}/domainscount'.format(node)))

        if vms < least_vms:
            least_vms = vms
            target_node = node

    return target_node
