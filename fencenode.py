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

import os, sys, libvirt, uuid, kazoo.client, time

# ANSII colours for output
class bcolours:
    PURPLE = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

#
# Trigger function
#
def fence(node_name, zk):
    time.sleep(3)
    print(bcolours.YELLOW + '>>> ' + bcolours.ENDC + 'Fencing node {} via IPMI reboot signal.'.format(node_name))

    # DO IPMI FENCE HERE

    print(bcolours.BLUE + '>>> ' + bcolours.ENDC + 'Moving VMs from dead hypervisor {} to new hosts.'.format(node_name))
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

        print(bcolours.BLUE + '>>> ' + bcolours.ENDC + 'Moving VM "{}" to hypervisor "{}".'.format(dom_uuid, target_hypervisor))
        transaction = zk.transaction()
        transaction.set_data('/domains/{}/state'.format(dom_uuid), 'start'.encode('ascii'))
        transaction.set_data('/domains/{}/hypervisor'.format(dom_uuid), target_hypervisor.encode('ascii'))
        transaction.set_data('/domains/{}/lasthypervisor'.format(dom_uuid), current_hypervisor.encode('ascii'))
        transaction.commit()
