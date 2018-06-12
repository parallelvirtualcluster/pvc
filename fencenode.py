#!/usr/bin/env python3

# fencenode.py - Supplemental functions to handle fencing of dead nodes
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

import os, sys, libvirt, uuid, kazoo.client, time, subprocess, re, ansiiprint

#
# Trigger function
#
def fence(node_name, zk):
    failcount = 0
    while failcount < 3
        # Wait 5 seconds
        time.sleep(5)
        # Get the state
        node_daemon_state = self.zk.get('/nodes/{}/daemonstate'.format(node_name))[0].decode('ascii')
        # Is it still 'dead'
        if node_daemon_state == 'dead':
            failcount += 1
            ansiiprint.echo('Node "{}" failed {} saving throw'.format(node_name, failcount), '', 'w')
        # It changed back to something else so it must be alive
        else:
            ansiiprint.echo('Node "{}" passed a saving throw; canceling fence'.format(node_name), '', 'o')
            return

    ansiiprint.echo('Fencing node "{}" via IPMI reboot signal'.format(node_name), '', 'e')

    ipmi_hostname = zk.get('/nodes/{}/ipmihostname'.format(node_name))[0].decode('ascii')
    ipmi_username = zk.get('/nodes/{}/ipmiusername'.format(node_name))[0].decode('ascii')
    ipmi_password = zk.get('/nodes/{}/ipmipassword'.format(node_name))[0].decode('ascii')
    rebootViaIPMI(ipmi_hostname, ipmi_user, ipmi_password)

    ansiiprint.echo('Moving VMs from dead hypervisor "{}" to new hosts'.format(node_name), '', 'i')
    dead_node_running_domains = zk.get('/nodes/{}/runningdomains'.format(node_name))[0].decode('ascii').split()
    for dom_uuid in dead_node_running_domains:
        most_memfree = 0
        hypervisor_list = zk.get_children('/nodes')
        current_hypervisor = zk.get('/domains/{}/hypervisor'.format(dom_uuid))[0].decode('ascii')
        for hypervisor in hypervisor_list:
            state = zk.get('/nodes/{}/state'.format(hypervisor))[0].decode('ascii')
            if state != 'start' or hypervisor == current_hypervisor:
                continue

            memfree = int(zk.get('/nodes/{}/memfree'.format(hypervisor))[0].decode('ascii'))
            if memfree > most_memfree:
                most_memfree = memfree
                target_hypervisor = hypervisor

        ansiiprint.echo('Moving VM "{}" to hypervisor "{}"'.format(dom_uuid, target_hypervisor), '', 'i')
        transaction = zk.transaction()
        transaction.set_data('/domains/{}/state'.format(dom_uuid), 'start'.encode('ascii'))
        transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
        transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), current_hypervisor.encode('ascii'))
        transaction.commit()

#def getIPMIAddress():
#    ipmi_command = ['bash', '/fakeipmi.sh']
#
#    # Get the IPMI address
#    ipmi_lan_output = subprocess.run(ipmi_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#    ipmi_lan_parsed = ipmi_lan_output.stdout.decode('ascii').split('\n')
#    ipmi_lan_address = [s for s in ipmi_lan_parsed if re.search('IP Address[ ]*:', s)][0].split(':')[-1].strip()
#    return ipmi_lan_address

def rebootViaIPMI(ipmi_hostname, ipmi_user, ipmi_password):
    ipmi_command = ['ipmitool', '-H', ipmi_hostname, '-U', ipmi_user, '-P', ipmi_password, 'chassis', 'power', 'reset']
    ipmi_command_output = subprocess.run(ipmi_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if ipmi_command_output == 0:
        ansiiprint.echo('Successfully rebooted dead node', '', 'o')
    else:
        ansiiprint.echo('Failed to reboot dead node', '', 'e')
