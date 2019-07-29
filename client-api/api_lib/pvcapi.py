#!/usr/bin/env python3

# pvcapi.py - PVC HTTP API functions
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

import flask
import json

import client_lib.common as pvc_common
import client_lib.node as pvc_node
import client_lib.vm as pvc_vm
import client_lib.network as pvc_network
import client_lib.ceph as pvc_ceph

#
# Node functions
#
def node_list(limit=None):
    """
    Return a list of nodes with limit LIMIT.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_node.get_list(zk_conn, limit)
    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {
                'message': 'Node not found.'
            }
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def node_secondary(node):
    """
    Take NODE out of primary router mode.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators']) 
    retflag, retdata = pvc_node.secondary_node(zk_conn, node)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def node_primary(node):
    """
    Set NODE to primary router mode.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators']) 
    retflag, retdata = pvc_node.primary_node(zk_conn, node)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def node_flush(node):
    """
    Flush NODE of running VMs.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_node.flush_node(zk_conn, node, False)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def node_ready(node):
    """
    Restore NODE to active service.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_node.ready_node(zk_conn, node)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

#
# VM functions
#
def vm_is_migrated(vm):
    """
    Determine if a VM is migrated or not
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retdata = pvc_vm.is_migrated(zk_conn, vm)
    return retdata

def vm_list(node=None, state=None, limit=None, is_fuzzy=True):
    """
    Return a list of VMs with limit LIMIT.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.get_list(zk_conn, node, state, limit, is_fuzzy)
    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {
                'message': 'VM not found.'
            }
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

# TODO: #22
#def vm_add():
#    """
#    Add a VM named NAME to the PVC cluster.
#    """
#    return '', 200

def vm_define(name, xml, node, selector):
    """
    Define a VM from Libvirt XML in the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.define_vm(zk_conn, xml, node, selector)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def vm_modify(name, restart, xml):
    """
    Modify a VM Libvirt XML in the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.modify_vm(zk_conn, name, restart, xml)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def vm_undefine(name):
    """
    Undefine a VM from the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.undefine_vm(zk_conn, name)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def vm_remove(name):
    """
    Remove a VM from the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.remove_vm(zk_conn, name)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def vm_start(name):
    """
    Start a VM in the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.start_vm(zk_conn, name)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def vm_restart(name):
    """
    Restart a VM in the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.restart_vm(zk_conn, name)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def vm_shutdown(name):
    """
    Shutdown a VM in the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.shutdown_vm(zk_conn, name)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def vm_stop(name):
    """
    Forcibly stop a VM in the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.stop_vm(zk_conn, name)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def vm_move(name, node, selector):
    """
    Move a VM to another node.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.move_vm(zk_conn, name, node, selector)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def vm_migrate(name, node, selector, flag_force):
    """
    Temporarily migrate a VM to another node.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.migrate_vm(zk_conn, name, node, selector, flag_force)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def vm_unmigrate(name):
    """
    Unmigrate a migrated VM.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.unmigrate_vm(zk_conn, name)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

#
# Network functions
#
def net_list(limit=None):
    """
    Return a list of client networks with limit LIMIT.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.get_list(zk_conn, limit)
    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {
                'message': 'Network not found.'
            }
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def net_add(vni, description, nettype, domain,
            ip4_network, ip4_gateway, ip6_network, ip6_gateway,
            dhcp4_flag, dhcp4_start, dhcp4_end):
    """
    Add a virtual client network to the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.add_network(zk_conn, vni, description, nettype, domain,
                                              ip4_network, ip4_gateway, ip6_network, ip6_gateway,
                                              dhcp4_flag, dhcp4_start, dhcp4_end)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def net_modify(vni, description, domain,
               ip4_network, ip4_gateway,
               ip6_network, ip6_gateway,
               dhcp4_flag, dhcp4_start, dhcp4_end):
    """
    Modify a virtual client network in the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.modify_network(zk_conn, vni, description, domain,
                                              ip4_network, ip4_gateway, ip6_network, ip6_gateway,
                                              dhcp4_flag, dhcp4_start, dhcp4_end)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def net_remove(network):
    """
    Remove a virtual client network from the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.remove_network(zk_conn, network)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def net_dhcp_list(network, limit=None, static=False):
    """
    Return a list of DHCP leases in network NETWORK with limit LIMIT.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.get_list_dhcp(zk_conn, network, limit, static)
    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {
                'message': 'Lease not found.'
            }
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def net_dhcp_add(network, ipaddress, macaddress, hostname):
    """
    Add a static DHCP lease to a virtual client network.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.add_dhcp_reservation(zk_conn, network, ipaddress, macaddress, hostname)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def net_dhcp_remove(network, macaddress):
    """
    Remove a static DHCP lease from a virtual client network.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.remove_dhcp_reservation(zk_conn, network, macaddress)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def net_acl_list(network, limit=None, direction=None):
    """
    Return a list of network ACLs in network NETWORK with limit LIMIT.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.get_list_acl(zk_conn, network, limit, direction)
    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {
                'message': 'ACL not found.'
            }
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def net_acl_add(network, direction, description, rule, order):
    """
    Add an ACL to a virtual client network.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.add_acl(zk_conn, network, direction, description, rule, order)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def net_acl_remove(network, direction, description):
    """
    Remove an ACL from a virtual client network.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.remove_acl(zk_conn, network, description, direction)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

#
# Ceph functions
#
def ceph_status():
    """
    Get the current Ceph cluster status.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.get_status(zk_conn)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def ceph_radosdf():
    """
    Get the current Ceph cluster utilization.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.get_radosdf(zk_conn)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def ceph_osd_list(limit=None):
    """
    Get the list of OSDs in the Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.get_list_osd(zk_conn, limit)
    pvc_common.stopZKConnection(zk_conn)
    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {
                'message': 'OSD not found.'
            }
    else:
        retcode = 400

    return flask.jsonify(retdata), retcode

def ceph_osd_state(osd):
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.get_list_osd(zk_conn, osd)
    pvc_common.stopZKConnection(zk_conn)
    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {
                'message': 'OSD not found.'
            }
    else:
        retcode = 400

    in_state = retdata[0]['stats']['in']
    up_state = retdata[0]['stats']['up']

    return flask.jsonify({ "id": osd, "in": in_state, "up": up_state }), retcode

def ceph_osd_add(node, device, weight):
    """
    Add a Ceph OSD to the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.add_osd(zk_conn, node, device, weight)
    pvc_common.stopZKConnection(zk_conn)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def ceph_osd_remove(osd_id):
    """
    Remove a Ceph OSD from the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.remove_osd(zk_conn, osd_id)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def ceph_osd_in(osd_id):
    """
    Set in a Ceph OSD in the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.in_osd(zk_conn, osd_id)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def ceph_osd_out(osd_id):
    """
    Set out a Ceph OSD in the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.out_osd(zk_conn, osd_id)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def ceph_osd_set(option):
    """
    Set options on a Ceph OSD in the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.set_osd(zk_conn, option)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def ceph_osd_unset(option):
    """
    Unset options on a Ceph OSD in the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.unset_osd(zk_conn, option)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def ceph_pool_list(limit=None):
    """
    Get the list of RBD pools in the Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.get_list_pool(zk_conn, limit)
    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {
                'message': 'Pool not found.'
            }
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def ceph_pool_add(name, pgs):
    """
    Add a Ceph RBD pool to the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.add_pool(zk_conn, name, pgs)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def ceph_pool_remove(name):
    """
    Remove a Ceph RBD pool to the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.remove_pool(zk_conn, name)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def ceph_volume_list(pool=None, limit=None):
    """
    Get the list of RBD volumes in the Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.get_list_volume(zk_conn, pool, limit)
    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {
                'message': 'Volume not found.'
            }
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def ceph_volume_add(pool, name, size):
    """
    Add a Ceph RBD volume to the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.add_volume(zk_conn, pool, name, size)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def ceph_volume_resize(pool, name, size):
    """
    Resize an existing Ceph RBD volume in the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.resize_volume(zk_conn, pool, name, size)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def ceph_volume_rename(pool, name, new_name):
    """
    Rename a Ceph RBD volume in the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.rename_volume(zk_conn, pool, name, new_name)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def ceph_volume_remove(pool, name):
    """
    Remove a Ceph RBD volume to the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.remove_volume(zk_conn, pool, name)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def ceph_volume_snapshot_list(pool=None, volume=None, limit=None):
    """
    Get the list of RBD volume snapshots in the Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.get_list_snapshot(zk_conn, pool, volume, limit)
    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {
                'message': 'Volume snapshot not found.'
            }
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    return flask.jsonify(retdata), retcode

def ceph_volume_snapshot_add(pool, volume, name):
    """
    Add a Ceph RBD volume snapshot to the PVC Ceph storage cluster.
    """
    return '', 200
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.add_snapshot(zk_conn, pool, volume, name)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def ceph_volume_snapshot_rename(pool, volume, name, new_name):
    """
    Rename a Ceph RBD volume snapshot in the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.rename_snapshot(zk_conn, pool, volume, name, new_name)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

def ceph_volume_snapshot_remove(pool, volume, name):
    """
    Remove a Ceph RBD volume snapshot from the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.remove_snapshot(zk_conn, pool, volume, name)
    if retflag:
        retcode = 200
    else:
        retcode = 400

    pvc_common.stopZKConnection(zk_conn)
    output = {
        'message': retdata.replace('\"', '\'')
    }
    return flask.jsonify(output), retcode

