#!/usr/bin/env python3

# helper.py - PVC HTTP API helper functions
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

import flask
import json
import lxml.etree as etree

from distutils.util import strtobool as dustrtobool

import daemon_lib.common as pvc_common
import daemon_lib.cluster as pvc_cluster
import daemon_lib.node as pvc_node
import daemon_lib.vm as pvc_vm
import daemon_lib.network as pvc_network
import daemon_lib.ceph as pvc_ceph

def strtobool(stringv):
    if stringv is None:
        return False
    if isinstance(stringv, bool):
        return bool(stringv)
    return bool(dustrtobool(stringv))

#
# Initialization function
#
def initialize_cluster():
    # Open a Zookeeper connection
    zk_conn = pvc_common.startZKConnection(config['coordinators'])

    # Abort if we've initialized the cluster before
    if zk_conn.exists('/primary_node'):
        return False

    # Create the root keys
    transaction = zk_conn.transaction()
    transaction.create('/primary_node', 'none'.encode('ascii'))
    transaction.create('/upstream_ip', 'none'.encode('ascii'))
    transaction.create('/maintenance', 'False'.encode('ascii'))
    transaction.create('/nodes', ''.encode('ascii'))
    transaction.create('/domains', ''.encode('ascii'))
    transaction.create('/networks', ''.encode('ascii'))
    transaction.create('/ceph', ''.encode('ascii'))
    transaction.create('/ceph/osds', ''.encode('ascii'))
    transaction.create('/ceph/pools', ''.encode('ascii'))
    transaction.create('/ceph/volumes', ''.encode('ascii'))
    transaction.create('/ceph/snapshots', ''.encode('ascii'))
    transaction.create('/cmd', ''.encode('ascii'))
    transaction.create('/cmd/domains', ''.encode('ascii'))
    transaction.create('/cmd/ceph', ''.encode('ascii'))
    transaction.create('/locks', ''.encode('ascii'))
    transaction.create('/locks/flush_lock', ''.encode('ascii'))
    transaction.create('/locks/primary_node', ''.encode('ascii'))
    transaction.commit()

    # Close the Zookeeper connection
    pvc_common.stopZKConnection(zk_conn)

    return True

#
# Cluster functions
#
def cluster_status():
    """
    Get the overall status of the PVC cluster
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_cluster.get_info(zk_conn)
    pvc_common.stopZKConnection(zk_conn)

    return retdata, 200

def cluster_maintenance(maint_state='false'):
    """
    Set the cluster in or out of maintenance state
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_cluster.set_maintenance(zk_conn, maint_state)
    pvc_common.stopZKConnection(zk_conn)

    retdata = {
        'message': retdata
    }
    if retflag:
        retcode = 200
    else:
        retcode = 400

    return retdata, retcode

#
# Node functions
#
def node_list(limit=None, is_fuzzy=True):
    """
    Return a list of nodes with limit LIMIT.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_node.get_list(zk_conn, limit, is_fuzzy=is_fuzzy)
    pvc_common.stopZKConnection(zk_conn)

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
        retdata = {
            'message': retdata
        }

    # If this is a single element, strip it out of the list
    if isinstance(retdata, list) and len(retdata) == 1:
        retdata = retdata[0]

    return retdata, retcode

def node_daemon_state(node):
    """
    Return the daemon state of node NODE.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_node.get_list(zk_conn, node, is_fuzzy=False)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        if retdata:
            retcode = 200
            retdata = {
                'name': node,
                'daemon_state': retdata[0]['daemon_state']
            }
        else:
            retcode = 404
            retdata = {
                'message': 'Node not found.'
            }
    else:
        retcode = 400
        retdata = {
            'message': retdata
        }

    return retdata, retcode

def node_coordinator_state(node):
    """
    Return the coordinator state of node NODE.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_node.get_list(zk_conn, node, is_fuzzy=False)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        if retdata:
            retcode = 200
            retdata = {
                'name': node,
                'coordinator_state': retdata[0]['coordinator_state']
            }
        else:
            retcode = 404
            retdata = {
                'message': 'Node not found.'
            }
    else:
        retcode = 400
        retdata = {
            'message': retdata
        }

    return retdata, retcode

def node_domain_state(node):
    """
    Return the domain state of node NODE.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_node.get_list(zk_conn, node, is_fuzzy=False)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        if retdata:
            retcode = 200
            retdata = {
                'name': node,
                'domain_state': retdata[0]['domain_state']
            }
        else:
            retcode = 404
            retdata = {
                'message': 'Node not found.'
            }
    else:
        retcode = 400

    return retdata, retcode

def node_secondary(node):
    """
    Take NODE out of primary router mode.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators']) 
    retflag, retdata = pvc_node.secondary_node(zk_conn, node)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def node_primary(node):
    """
    Set NODE to primary router mode.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators']) 
    retflag, retdata = pvc_node.primary_node(zk_conn, node)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def node_flush(node, wait):
    """
    Flush NODE of running VMs.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_node.flush_node(zk_conn, node, wait)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def node_ready(node, wait):
    """
    Restore NODE to active service.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_node.ready_node(zk_conn, node, wait)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

#
# VM functions
#
def vm_is_migrated(vm):
    """
    Determine if a VM is migrated or not
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retdata = pvc_vm.is_migrated(zk_conn, vm)
    pvc_common.stopZKConnection(zk_conn)

    return retdata

def vm_state(vm):
    """
    Return the state of virtual machine VM.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.get_list(zk_conn, None, None, vm, is_fuzzy=False)
    pvc_common.stopZKConnection(zk_conn)

    # If this is a single element, strip it out of the list
    if isinstance(retdata, list) and len(retdata) == 1:
        retdata = retdata[0]

    if retflag:
        if retdata:
            retcode = 200
            retdata = {
                'name': vm,
                'state': retdata['state']
            }
        else:
            retcode = 404
            retdata = {
                'message': 'VM not found.'
            }
    else:
        retcode = 400
        retdata = {
            'message': retdata
        }

    return retdata, retcode

def vm_node(vm):
    """
    Return the current node of virtual machine VM.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.get_list(zk_conn, None, None, vm, is_fuzzy=False)
    pvc_common.stopZKConnection(zk_conn)

    # If this is a single element, strip it out of the list
    if isinstance(retdata, list) and len(retdata) == 1:
        retdata = retdata[0]

    if retflag:
        if retdata:
            retcode = 200
            retdata = {
                'name': vm,
                'node': retdata['node'],
                'last_node': retdata['last_node']
            }
        else:
            retcode = 404
            retdata = {
                'message': 'VM not found.'
            }
    else:
        retcode = 400
        retdata = {
            'message': retdata
        }

    return retdata, retcode

def vm_console(vm, lines=None):
    """
    Return the current console log for VM.
    """
    # Default to 10 lines of log if not set
    try:
        lines = int(lines)
    except TypeError:
        lines = 10

    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.get_console_log(zk_conn, vm, lines)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
        retdata = {
            'name': vm,
            'data': retdata
        }
    else:
        retcode = 400
        retdata = {
            'message': retdata
        }

    return retdata, retcode

def vm_list(node=None, state=None, limit=None, is_fuzzy=True):
    """
    Return a list of VMs with limit LIMIT.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.get_list(zk_conn, node, state, limit, is_fuzzy)
    pvc_common.stopZKConnection(zk_conn)

    # If this is a single element, strip it out of the list
    if isinstance(retdata, list) and len(retdata) == 1:
        retdata = retdata[0]

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
        retdata = {
            'message': retdata
        }

    return retdata, retcode

def vm_define(xml, node, limit, selector, autostart):
    """
    Define a VM from Libvirt XML in the PVC cluster.
    """
    # Verify our XML is sensible
    try:
        xml_data = etree.fromstring(xml)
        new_cfg = etree.tostring(xml_data, pretty_print=True).decode('utf8')
    except Exception as e:
        return { 'message': 'XML is malformed or incorrect: {}'.format(e) }, 400

    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.define_vm(zk_conn, new_cfg, node, limit, selector, autostart, profile=None)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def get_vm_meta(vm):
    """
    Get metadata of a VM.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.get_list(zk_conn, None, None, vm, is_fuzzy=False)
    pvc_common.stopZKConnection(zk_conn)

    # If this is a single element, strip it out of the list
    if isinstance(retdata, list) and len(retdata) == 1:
        retdata = retdata[0]

    if retflag:
        if retdata:
            retcode = 200
            retdata = {
                'name': vm,
                'node_limit': retdata['node_limit'],
                'node_selector': retdata['node_selector'],
                'node_autostart': retdata['node_autostart']
            }
        else:
            retcode = 404
            retdata = {
                'message': 'VM not found.'
            }
    else:
        retcode = 400
        retdata = {
            'message': retdata
        }

    return retdata, retcode

def update_vm_meta(vm, limit, selector, autostart, provisioner_profile):
    """
    Update metadata of a VM.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    if autostart is not None:
        try:
            autostart = bool(strtobool(autostart))
        except:
            autostart = False
    retflag, retdata = pvc_vm.modify_vm_metadata(zk_conn, vm, limit, selector, autostart, provisioner_profile)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def vm_modify(name, restart, xml):
    """
    Modify a VM Libvirt XML in the PVC cluster.
    """
    # Verify our XML is sensible
    try:
        xml_data = etree.fromstring(xml)
        new_cfg = etree.tostring(xml_data, pretty_print=True).decode('utf8')
    except Exception as e:
        return { 'message': 'XML is malformed or incorrect: {}'.format(e) }, 400
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.modify_vm(zk_conn, name, restart, new_cfg)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def vm_undefine(name):
    """
    Undefine a VM from the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.undefine_vm(zk_conn, name)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def vm_remove(name):
    """
    Remove a VM from the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.remove_vm(zk_conn, name)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def vm_start(name):
    """
    Start a VM in the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.start_vm(zk_conn, name)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def vm_restart(name, wait):
    """
    Restart a VM in the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.restart_vm(zk_conn, name, wait)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def vm_shutdown(name, wait):
    """
    Shutdown a VM in the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.shutdown_vm(zk_conn, name, wait)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def vm_stop(name):
    """
    Forcibly stop a VM in the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.stop_vm(zk_conn, name)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def vm_disable(name):
    """
    Disable a (stopped) VM in the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.disable_vm(zk_conn, name)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def vm_move(name, node, wait):
    """
    Move a VM to another node.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.move_vm(zk_conn, name, node, wait)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def vm_migrate(name, node, flag_force, wait):
    """
    Temporarily migrate a VM to another node.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.migrate_vm(zk_conn, name, node, flag_force, wait)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def vm_unmigrate(name, wait):
    """
    Unmigrate a migrated VM.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.unmigrate_vm(zk_conn, name, wait)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def vm_flush_locks(vm):
    """
    Flush locks of a (stopped) VM.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.get_list(zk_conn, None, None, vm, is_fuzzy=False)
    pvc_common.stopZKConnection(zk_conn)

    # If this is a single element, strip it out of the list
    if isinstance(retdata, list) and len(retdata) == 1:
        retdata = retdata[0]

    if retdata['state'] not in ['stop', 'disable']:
        return {"message":"VM must be stopped to flush locks"}, 400

    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_vm.flush_locks(zk_conn, vm)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

#
# Network functions
#
def net_list(limit=None, is_fuzzy=True):
    """
    Return a list of client networks with limit LIMIT.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.get_list(zk_conn, limit, is_fuzzy)
    pvc_common.stopZKConnection(zk_conn)

    # If this is a single element, strip it out of the list
    if isinstance(retdata, list) and len(retdata) == 1:
        retdata = retdata[0]

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
        retdata = {
            'message': retdata
        }

    return retdata, retcode

def net_add(vni, description, nettype, domain, name_servers,
            ip4_network, ip4_gateway, ip6_network, ip6_gateway,
            dhcp4_flag, dhcp4_start, dhcp4_end):
    """
    Add a virtual client network to the PVC cluster.
    """
    if dhcp4_flag:
        dhcp4_flag = bool(strtobool(dhcp4_flag))
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.add_network(zk_conn, vni, description, nettype, domain, name_servers,
                                              ip4_network, ip4_gateway, ip6_network, ip6_gateway,
                                              dhcp4_flag, dhcp4_start, dhcp4_end)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def net_modify(vni, description, domain, name_servers,
               ip4_network, ip4_gateway,
               ip6_network, ip6_gateway,
               dhcp4_flag, dhcp4_start, dhcp4_end):
    """
    Modify a virtual client network in the PVC cluster.
    """
    if dhcp4_flag is not None:
        dhcp4_flag = bool(strtobool(dhcp4_flag))
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.modify_network(zk_conn, vni, description, domain, name_servers,
                                              ip4_network, ip4_gateway, ip6_network, ip6_gateway,
                                              dhcp4_flag, dhcp4_start, dhcp4_end)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def net_remove(network):
    """
    Remove a virtual client network from the PVC cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.remove_network(zk_conn, network)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def net_dhcp_list(network, limit=None, static=False):
    """
    Return a list of DHCP leases in network NETWORK with limit LIMIT.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.get_list_dhcp(zk_conn, network, limit, static)
    pvc_common.stopZKConnection(zk_conn)

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
        retdata = {
            'message': retdata
        }

    return retdata, retcode

def net_dhcp_add(network, ipaddress, macaddress, hostname):
    """
    Add a static DHCP lease to a virtual client network.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.add_dhcp_reservation(zk_conn, network, ipaddress, macaddress, hostname)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def net_dhcp_remove(network, macaddress):
    """
    Remove a static DHCP lease from a virtual client network.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.remove_dhcp_reservation(zk_conn, network, macaddress)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def net_acl_list(network, limit=None, direction=None, is_fuzzy=True):
    """
    Return a list of network ACLs in network NETWORK with limit LIMIT.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.get_list_acl(zk_conn, network, limit, direction, is_fuzzy=True)
    pvc_common.stopZKConnection(zk_conn)

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
        retdata = {
            'message': retdata
        }

    # If this is a single element, strip it out of the list
    if isinstance(retdata, list) and len(retdata) == 1:
        retdata = retdata[0]

    return retdata, retcode

def net_acl_add(network, direction, description, rule, order):
    """
    Add an ACL to a virtual client network.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.add_acl(zk_conn, network, direction, description, rule, order)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def net_acl_remove(network, description):
    """
    Remove an ACL from a virtual client network.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_network.remove_acl(zk_conn, network, description)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

#
# Ceph functions
#
def ceph_status():
    """
    Get the current Ceph cluster status.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.get_status(zk_conn)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    return retdata, retcode

def ceph_radosdf():
    """
    Get the current Ceph cluster utilization.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.get_radosdf(zk_conn)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    return retdata, retcode

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
        retdata = {
            'message': retdata
        }

    return retdata, retcode

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
        retdata = {
            'message': retdata
        }

    in_state = retdata[0]['stats']['in']
    up_state = retdata[0]['stats']['up']

    return { "id": osd, "in": in_state, "up": up_state }, retcode

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
    return output, retcode

def ceph_osd_remove(osd_id):
    """
    Remove a Ceph OSD from the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.remove_osd(zk_conn, osd_id)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def ceph_osd_in(osd_id):
    """
    Set in a Ceph OSD in the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.in_osd(zk_conn, osd_id)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def ceph_osd_out(osd_id):
    """
    Set out a Ceph OSD in the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.out_osd(zk_conn, osd_id)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def ceph_osd_set(option):
    """
    Set options on a Ceph OSD in the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.set_osd(zk_conn, option)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def ceph_osd_unset(option):
    """
    Unset options on a Ceph OSD in the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.unset_osd(zk_conn, option)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def ceph_pool_list(limit=None, is_fuzzy=True):
    """
    Get the list of RBD pools in the Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.get_list_pool(zk_conn, limit, is_fuzzy)
    pvc_common.stopZKConnection(zk_conn)

    # If this is a single element, strip it out of the list
    if isinstance(retdata, list) and len(retdata) == 1:
        retdata = retdata[0]

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
        retdata = {
            'message': retdata
        }

    return retdata, retcode

def ceph_pool_add(name, pgs, replcfg):
    """
    Add a Ceph RBD pool to the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.add_pool(zk_conn, name, pgs, replcfg)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata
    }
    return output, retcode

def ceph_pool_remove(name):
    """
    Remove a Ceph RBD pool to the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.remove_pool(zk_conn, name)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def ceph_volume_list(pool=None, limit=None, is_fuzzy=True):
    """
    Get the list of RBD volumes in the Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.get_list_volume(zk_conn, pool, limit, is_fuzzy)
    pvc_common.stopZKConnection(zk_conn)

    # If this is a single element, strip it out of the list
    if isinstance(retdata, list) and len(retdata) == 1:
        retdata = retdata[0]

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
        retdata = {
            'message': retdata
        }

    return retdata, retcode

def ceph_volume_add(pool, name, size):
    """
    Add a Ceph RBD volume to the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.add_volume(zk_conn, pool, name, size)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def ceph_volume_clone(pool, name, source_volume):
    """
    Clone a Ceph RBD volume to a new volume on the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.clone_volume(zk_conn, pool, source_volume, name)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def ceph_volume_resize(pool, name, size):
    """
    Resize an existing Ceph RBD volume in the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.resize_volume(zk_conn, pool, name, size)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def ceph_volume_rename(pool, name, new_name):
    """
    Rename a Ceph RBD volume in the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.rename_volume(zk_conn, pool, name, new_name)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def ceph_volume_remove(pool, name):
    """
    Remove a Ceph RBD volume to the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.remove_volume(zk_conn, pool, name)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def ceph_volume_upload(pool, volume, data, img_type):
    """
    Upload a raw file via HTTP post to a PVC Ceph volume
    """
    # Determine the image conversion options
    if img_type not in ['raw', 'vmdk', 'qcow2', 'qed', 'vdi', 'vpc']:
        output = {
            "message": "Image type '{}' is not valid.".format(img_type)
        }
        retcode = 400
        return output, retcode

    # Get the size of the target block device
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retcode, retdata = pvc_ceph.get_list_volume(zk_conn, pool, volume, is_fuzzy=False)
    pvc_common.stopZKConnection(zk_conn)
    # If there's no target, return failure
    if not retcode or len(retdata) < 1:
        output = {
            "message": "Target volume '{}' does not exist in pool '{}'.".format(volume, pool)
        }
        retcode = 400
        return output, retcode
    dev_size = retdata[0]['stats']['size']

    def cleanup_maps_and_volumes():
        zk_conn = pvc_common.startZKConnection(config['coordinators'])
        # Unmap the target blockdev
        retflag, retdata = pvc_ceph.unmap_volume(zk_conn, pool, volume)
        # Unmap the temporary blockdev
        retflag, retdata = pvc_ceph.unmap_volume(zk_conn, pool, "{}_tmp".format(volume))
        # Remove the temporary blockdev
        retflag, retdata = pvc_ceph.remove_volume(zk_conn, pool, "{}_tmp".format(volume))
        pvc_common.stopZKConnection(zk_conn)

    # Create a temporary block device to store non-raw images
    if img_type == 'raw':
        # Map the target blockdev
        zk_conn = pvc_common.startZKConnection(config['coordinators'])
        retflag, retdata = pvc_ceph.map_volume(zk_conn, pool, volume)
        pvc_common.stopZKConnection(zk_conn)
        if not retflag:
            output = {
                'message': retdata.replace('\"', '\'')
            }
            retcode = 400
            cleanup_maps_and_volumes()
            return output, retcode
        dest_blockdev = retdata

        # Save the data to the blockdev directly
        try:
            data.save(dest_blockdev)
        except:
            output = {
                'message': "Failed to write image file to volume."
            }
            retcode = 400
            cleanup_maps_and_volumes()
            return output, retcode

        output = {
            'message': "Wrote uploaded file to volume '{}' in pool '{}'.".format(volume, pool)
        }
        retcode = 200
        cleanup_maps_and_volumes()
        return output, retcode

    # Write the image directly to the blockdev
    else:
        # Create a temporary blockdev
        zk_conn = pvc_common.startZKConnection(config['coordinators'])
        retflag, retdata = pvc_ceph.add_volume(zk_conn, pool, "{}_tmp".format(volume), dev_size)
        pvc_common.stopZKConnection(zk_conn)
        if not retflag:
            output = {
                'message': retdata.replace('\"', '\'')
            }
            retcode = 400
            cleanup_maps_and_volumes()
            return output, retcode

        # Map the temporary target blockdev
        zk_conn = pvc_common.startZKConnection(config['coordinators'])
        retflag, retdata = pvc_ceph.map_volume(zk_conn, pool, "{}_tmp".format(volume))
        pvc_common.stopZKConnection(zk_conn)
        if not retflag:
            output = {
                'message': retdata.replace('\"', '\'')
            }
            retcode = 400
            cleanup_maps_and_volumes()
            return output, retcode
        temp_blockdev = retdata

        # Map the target blockdev
        zk_conn = pvc_common.startZKConnection(config['coordinators'])
        retflag, retdata = pvc_ceph.map_volume(zk_conn, pool, volume)
        pvc_common.stopZKConnection(zk_conn)
        if not retflag:
            output = {
                'message': retdata.replace('\"', '\'')
            }
            retcode = 400
            cleanup_maps_and_volumes()
            return output, retcode
        dest_blockdev = retdata

        # Save the data to the temporary blockdev directly
        try:
            data.save(temp_blockdev)
        except:
            output = {
                'message': "Failed to write image file to temporary volume."
            }
            retcode = 400
            cleanup_maps_and_volumes()
            return output, retcode

        # Convert from the temporary to destination format on the blockdevs
        retcode, stdout, stderr = pvc_common.run_os_command(
            'qemu-img convert -C -f {} -O raw {} {}'.format(img_type, temp_blockdev, dest_blockdev)
        )
        if retcode:
            output = {
                'message': "Failed to convert image format from '{}' to 'raw': {}".format(img_type, stderr)
            }
            retcode = 400
            cleanup_maps_and_volumes()
            return output, retcode

        output = {
            'message': "Converted and wrote uploaded file to volume '{}' in pool '{}'.".format(volume, pool)
        }
        retcode = 200
        cleanup_maps_and_volumes()
        return output, retcode

def ceph_volume_snapshot_list(pool=None, volume=None, limit=None, is_fuzzy=True):
    """
    Get the list of RBD volume snapshots in the Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.get_list_snapshot(zk_conn, pool, volume, limit, is_fuzzy)
    pvc_common.stopZKConnection(zk_conn)

    # If this is a single element, strip it out of the list
    if isinstance(retdata, list) and len(retdata) == 1:
        retdata = retdata[0]

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
        retdata = {
            'message': retdata
        }

    return retdata, retcode

def ceph_volume_snapshot_add(pool, volume, name):
    """
    Add a Ceph RBD volume snapshot to the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.add_snapshot(zk_conn, pool, volume, name)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def ceph_volume_snapshot_rename(pool, volume, name, new_name):
    """
    Rename a Ceph RBD volume snapshot in the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.rename_snapshot(zk_conn, pool, volume, name, new_name)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

def ceph_volume_snapshot_remove(pool, volume, name):
    """
    Remove a Ceph RBD volume snapshot from the PVC Ceph storage cluster.
    """
    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    retflag, retdata = pvc_ceph.remove_snapshot(zk_conn, pool, volume, name)
    pvc_common.stopZKConnection(zk_conn)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode

