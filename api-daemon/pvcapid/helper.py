#!/usr/bin/env python3

# helper.py - PVC HTTP API helper functions
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

import flask
import json
import lxml.etree as etree

from werkzeug.formparser import parse_form_data

from pvcapid.Daemon import config, strtobool

from daemon_lib.zkhandler import ZKConnection

import daemon_lib.common as pvc_common
import daemon_lib.cluster as pvc_cluster
import daemon_lib.node as pvc_node
import daemon_lib.vm as pvc_vm
import daemon_lib.network as pvc_network
import daemon_lib.ceph as pvc_ceph


#
# Cluster base functions
#
@ZKConnection(config)
def initialize_cluster(zkhandler, overwrite=False):
    """
    Initialize a new cluster
    """
    retflag, retmsg = pvc_cluster.cluster_initialize(zkhandler, overwrite)

    retmsg = {
        'message': retmsg
    }
    if retflag:
        retcode = 200
    else:
        retcode = 400

    return retmsg, retcode


@ZKConnection(config)
def backup_cluster(zkhandler):
    retflag, retdata = pvc_cluster.cluster_backup(zkhandler)

    if retflag:
        retcode = 200
        retdata = json.dumps(retdata)
    else:
        retcode = 400
        retdata = {
            'message': retdata
        }

    return retdata, retcode


@ZKConnection(config)
def restore_cluster(zkhandler, cluster_data_raw):
    try:
        cluster_data = json.loads(cluster_data_raw)
    except Exception as e:
        return {'message': 'ERROR: Failed to parse JSON data: {}'.format(e)}, 400

    retflag, retdata = pvc_cluster.cluster_restore(zkhandler, cluster_data)

    retdata = {
        'message': retdata
    }
    if retflag:
        retcode = 200
    else:
        retcode = 400

    return retdata, retcode


#
# Cluster functions
#
@pvc_common.Profiler(config)
@ZKConnection(config)
def cluster_status(zkhandler):
    """
    Get the overall status of the PVC cluster
    """
    retflag, retdata = pvc_cluster.get_info(zkhandler)

    return retdata, 200


@ZKConnection(config)
def cluster_maintenance(zkhandler, maint_state='false'):
    """
    Set the cluster in or out of maintenance state
    """
    retflag, retdata = pvc_cluster.set_maintenance(zkhandler, maint_state)

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
@pvc_common.Profiler(config)
@ZKConnection(config)
def node_list(zkhandler, limit=None, daemon_state=None, coordinator_state=None, domain_state=None, is_fuzzy=True):
    """
    Return a list of nodes with limit LIMIT.
    """
    retflag, retdata = pvc_node.get_list(zkhandler, limit, daemon_state=daemon_state, coordinator_state=coordinator_state, domain_state=domain_state, is_fuzzy=is_fuzzy)

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

    return retdata, retcode


@ZKConnection(config)
def node_daemon_state(zkhandler, node):
    """
    Return the daemon state of node NODE.
    """
    retflag, retdata = pvc_node.get_list(zkhandler, node, is_fuzzy=False)

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


@ZKConnection(config)
def node_coordinator_state(zkhandler, node):
    """
    Return the coordinator state of node NODE.
    """
    retflag, retdata = pvc_node.get_list(zkhandler, node, is_fuzzy=False)

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


@ZKConnection(config)
def node_domain_state(zkhandler, node):
    """
    Return the domain state of node NODE.
    """
    retflag, retdata = pvc_node.get_list(zkhandler, node, is_fuzzy=False)

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


@ZKConnection(config)
def node_secondary(zkhandler, node):
    """
    Take NODE out of primary router mode.
    """
    retflag, retdata = pvc_node.secondary_node(zkhandler, node)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def node_primary(zkhandler, node):
    """
    Set NODE to primary router mode.
    """
    retflag, retdata = pvc_node.primary_node(zkhandler, node)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def node_flush(zkhandler, node, wait):
    """
    Flush NODE of running VMs.
    """
    retflag, retdata = pvc_node.flush_node(zkhandler, node, wait)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def node_ready(zkhandler, node, wait):
    """
    Restore NODE to active service.
    """
    retflag, retdata = pvc_node.ready_node(zkhandler, node, wait)

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
@ZKConnection(config)
def vm_is_migrated(zkhandler, vm):
    """
    Determine if a VM is migrated or not
    """
    retdata = pvc_vm.is_migrated(zkhandler, vm)

    return retdata


@pvc_common.Profiler(config)
@ZKConnection(config)
def vm_state(zkhandler, vm):
    """
    Return the state of virtual machine VM.
    """
    retflag, retdata = pvc_vm.get_list(zkhandler, None, None, vm, is_fuzzy=False)

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


@pvc_common.Profiler(config)
@ZKConnection(config)
def vm_node(zkhandler, vm):
    """
    Return the current node of virtual machine VM.
    """
    retflag, retdata = pvc_vm.get_list(zkhandler, None, None, vm, is_fuzzy=False)

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


@ZKConnection(config)
def vm_console(zkhandler, vm, lines=None):
    """
    Return the current console log for VM.
    """
    # Default to 10 lines of log if not set
    try:
        lines = int(lines)
    except TypeError:
        lines = 10

    retflag, retdata = pvc_vm.get_console_log(zkhandler, vm, lines)

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


@pvc_common.Profiler(config)
@ZKConnection(config)
def vm_list(zkhandler, node=None, state=None, limit=None, is_fuzzy=True):
    """
    Return a list of VMs with limit LIMIT.
    """
    retflag, retdata = pvc_vm.get_list(zkhandler, node, state, limit, is_fuzzy)

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


@ZKConnection(config)
def vm_define(zkhandler, xml, node, limit, selector, autostart, migration_method, tags=[]):
    """
    Define a VM from Libvirt XML in the PVC cluster.
    """
    # Verify our XML is sensible
    try:
        xml_data = etree.fromstring(xml)
        new_cfg = etree.tostring(xml_data, pretty_print=True).decode('utf8')
    except Exception as e:
        return {'message': 'XML is malformed or incorrect: {}'.format(e)}, 400

    retflag, retdata = pvc_vm.define_vm(zkhandler, new_cfg, node, limit, selector, autostart, migration_method, profile=None, tags=tags)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def get_vm_meta(zkhandler, vm):
    """
    Get metadata of a VM.
    """
    dom_uuid = pvc_vm.getDomainUUID(zkhandler, vm)
    if not dom_uuid:
        return {"message": "VM not found."}, 404

    domain_node_limit, domain_node_selector, domain_node_autostart, domain_migrate_method = pvc_common.getDomainMetadata(zkhandler, dom_uuid)

    retcode = 200
    retdata = {
        'name': vm,
        'node_limit': domain_node_limit,
        'node_selector': domain_node_selector,
        'node_autostart': domain_node_autostart,
        'migration_method': domain_migrate_method
    }

    return retdata, retcode


@ZKConnection(config)
def update_vm_meta(zkhandler, vm, limit, selector, autostart, provisioner_profile, migration_method):
    """
    Update metadata of a VM.
    """
    dom_uuid = pvc_vm.getDomainUUID(zkhandler, vm)
    if not dom_uuid:
        return {"message": "VM not found."}, 404

    if autostart is not None:
        try:
            autostart = bool(strtobool(autostart))
        except Exception:
            autostart = False

    retflag, retdata = pvc_vm.modify_vm_metadata(zkhandler, vm, limit, selector, autostart, provisioner_profile, migration_method)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def get_vm_tags(zkhandler, vm):
    """
    Get the tags of a VM.
    """
    dom_uuid = pvc_vm.getDomainUUID(zkhandler, vm)
    if not dom_uuid:
        return {"message": "VM not found."}, 404

    tags = pvc_common.getDomainTags(zkhandler, dom_uuid)

    retcode = 200
    retdata = {
        'name': vm,
        'tags': tags
    }

    return retdata, retcode


@ZKConnection(config)
def update_vm_tags(zkhandler, vm, action, tags):
    """
    Update the tags of a VM.
    """
    if action not in ['add', 'remove', 'replace']:
        return {"message": "Tag action must be one of 'add', 'remove', 'replace'."}, 400

    dom_uuid = pvc_vm.getDomainUUID(zkhandler, vm)
    if not dom_uuid:
        return {"message": "VM not found."}, 404

    retflag, retdata = pvc_vm.modify_vm_tags(zkhandler, vm, action, tags)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def vm_modify(zkhandler, name, restart, xml):
    """
    Modify a VM Libvirt XML in the PVC cluster.
    """
    # Verify our XML is sensible
    try:
        xml_data = etree.fromstring(xml)
        new_cfg = etree.tostring(xml_data, pretty_print=True).decode('utf8')
    except Exception as e:
        return {'message': 'XML is malformed or incorrect: {}'.format(e)}, 400

    retflag, retdata = pvc_vm.modify_vm(zkhandler, name, restart, new_cfg)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def vm_rename(zkhandler, name, new_name):
    """
    Rename a VM in the PVC cluster.
    """
    if new_name is None:
        output = {
            'message': 'A new VM name must be specified'
        }
        return 400, output

    if pvc_vm.searchClusterByName(zkhandler, new_name) is not None:
        output = {
            'message': 'A VM named \'{}\' is already present in the cluster'.format(new_name)
        }
        return 400, output

    retflag, retdata = pvc_vm.rename_vm(zkhandler, name, new_name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def vm_undefine(zkhandler, name):
    """
    Undefine a VM from the PVC cluster.
    """
    retflag, retdata = pvc_vm.undefine_vm(zkhandler, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def vm_remove(zkhandler, name):
    """
    Remove a VM from the PVC cluster.
    """
    retflag, retdata = pvc_vm.remove_vm(zkhandler, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def vm_start(zkhandler, name):
    """
    Start a VM in the PVC cluster.
    """
    retflag, retdata = pvc_vm.start_vm(zkhandler, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def vm_restart(zkhandler, name, wait):
    """
    Restart a VM in the PVC cluster.
    """
    retflag, retdata = pvc_vm.restart_vm(zkhandler, name, wait)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def vm_shutdown(zkhandler, name, wait):
    """
    Shutdown a VM in the PVC cluster.
    """
    retflag, retdata = pvc_vm.shutdown_vm(zkhandler, name, wait)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def vm_stop(zkhandler, name):
    """
    Forcibly stop a VM in the PVC cluster.
    """
    retflag, retdata = pvc_vm.stop_vm(zkhandler, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def vm_disable(zkhandler, name):
    """
    Disable a (stopped) VM in the PVC cluster.
    """
    retflag, retdata = pvc_vm.disable_vm(zkhandler, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def vm_move(zkhandler, name, node, wait, force_live):
    """
    Move a VM to another node.
    """
    retflag, retdata = pvc_vm.move_vm(zkhandler, name, node, wait, force_live)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def vm_migrate(zkhandler, name, node, flag_force, wait, force_live):
    """
    Temporarily migrate a VM to another node.
    """
    retflag, retdata = pvc_vm.migrate_vm(zkhandler, name, node, flag_force, wait, force_live)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def vm_unmigrate(zkhandler, name, wait, force_live):
    """
    Unmigrate a migrated VM.
    """
    retflag, retdata = pvc_vm.unmigrate_vm(zkhandler, name, wait, force_live)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def vm_flush_locks(zkhandler, vm):
    """
    Flush locks of a (stopped) VM.
    """
    retflag, retdata = pvc_vm.get_list(zkhandler, None, None, vm, is_fuzzy=False)

    if retdata[0].get('state') not in ['stop', 'disable']:
        return {"message": "VM must be stopped to flush locks"}, 400

    retflag, retdata = pvc_vm.flush_locks(zkhandler, vm)

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
@pvc_common.Profiler(config)
@ZKConnection(config)
def net_list(zkhandler, limit=None, is_fuzzy=True):
    """
    Return a list of client networks with limit LIMIT.
    """
    retflag, retdata = pvc_network.get_list(zkhandler, limit, is_fuzzy)

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


@ZKConnection(config)
def net_add(zkhandler, vni, description, nettype, domain, name_servers,
            ip4_network, ip4_gateway, ip6_network, ip6_gateway,
            dhcp4_flag, dhcp4_start, dhcp4_end):
    """
    Add a virtual client network to the PVC cluster.
    """
    if dhcp4_flag:
        dhcp4_flag = bool(strtobool(dhcp4_flag))
    retflag, retdata = pvc_network.add_network(zkhandler, vni, description, nettype, domain, name_servers,
                                               ip4_network, ip4_gateway, ip6_network, ip6_gateway,
                                               dhcp4_flag, dhcp4_start, dhcp4_end)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def net_modify(zkhandler, vni, description, domain, name_servers,
               ip4_network, ip4_gateway,
               ip6_network, ip6_gateway,
               dhcp4_flag, dhcp4_start, dhcp4_end):
    """
    Modify a virtual client network in the PVC cluster.
    """
    if dhcp4_flag is not None:
        dhcp4_flag = bool(strtobool(dhcp4_flag))
    retflag, retdata = pvc_network.modify_network(zkhandler, vni, description, domain, name_servers,
                                                  ip4_network, ip4_gateway, ip6_network, ip6_gateway,
                                                  dhcp4_flag, dhcp4_start, dhcp4_end)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def net_remove(zkhandler, network):
    """
    Remove a virtual client network from the PVC cluster.
    """
    retflag, retdata = pvc_network.remove_network(zkhandler, network)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def net_dhcp_list(zkhandler, network, limit=None, static=False):
    """
    Return a list of DHCP leases in network NETWORK with limit LIMIT.
    """
    retflag, retdata = pvc_network.get_list_dhcp(zkhandler, network, limit, static)

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


@ZKConnection(config)
def net_dhcp_add(zkhandler, network, ipaddress, macaddress, hostname):
    """
    Add a static DHCP lease to a virtual client network.
    """
    retflag, retdata = pvc_network.add_dhcp_reservation(zkhandler, network, ipaddress, macaddress, hostname)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def net_dhcp_remove(zkhandler, network, macaddress):
    """
    Remove a static DHCP lease from a virtual client network.
    """
    retflag, retdata = pvc_network.remove_dhcp_reservation(zkhandler, network, macaddress)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def net_acl_list(zkhandler, network, limit=None, direction=None, is_fuzzy=True):
    """
    Return a list of network ACLs in network NETWORK with limit LIMIT.
    """
    retflag, retdata = pvc_network.get_list_acl(zkhandler, network, limit, direction, is_fuzzy=True)

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

    return retdata, retcode


@ZKConnection(config)
def net_acl_add(zkhandler, network, direction, description, rule, order):
    """
    Add an ACL to a virtual client network.
    """
    retflag, retdata = pvc_network.add_acl(zkhandler, network, direction, description, rule, order)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def net_acl_remove(zkhandler, network, description):
    """
    Remove an ACL from a virtual client network.
    """
    retflag, retdata = pvc_network.remove_acl(zkhandler, network, description)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


#
# SR-IOV functions
#
@pvc_common.Profiler(config)
@ZKConnection(config)
def sriov_pf_list(zkhandler, node):
    """
    List all PFs on a given node.
    """
    retflag, retdata = pvc_network.get_list_sriov_pf(zkhandler, node)

    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {
                'message': 'PF not found.'
            }
    else:
        retcode = 400
        retdata = {
            'message': retdata
        }

    return retdata, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def sriov_vf_list(zkhandler, node, pf=None):
    """
    List all VFs on a given node, optionally limited to PF.
    """
    retflag, retdata = pvc_network.get_list_sriov_vf(zkhandler, node, pf)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    if retflag:
        if retdata:
            retcode = 200
        else:
            retcode = 404
            retdata = {
                'message': 'VF not found.'
            }
    else:
        retcode = 400
        retdata = {
            'message': retdata
        }

    return retdata, retcode


@ZKConnection(config)
def update_sriov_vf_config(zkhandler, node, vf, vlan_id, vlan_qos, tx_rate_min, tx_rate_max, link_state, spoof_check, trust, query_rss):
    """
    Update configuration of a VF on NODE.
    """
    retflag, retdata = pvc_network.set_sriov_vf_config(zkhandler, node, vf, vlan_id, vlan_qos, tx_rate_min, tx_rate_max, link_state, spoof_check, trust, query_rss)

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
@ZKConnection(config)
def ceph_status(zkhandler):
    """
    Get the current Ceph cluster status.
    """
    retflag, retdata = pvc_ceph.get_status(zkhandler)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    return retdata, retcode


@ZKConnection(config)
def ceph_util(zkhandler):
    """
    Get the current Ceph cluster utilization.
    """
    retflag, retdata = pvc_ceph.get_util(zkhandler)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    return retdata, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def ceph_osd_list(zkhandler, limit=None):
    """
    Get the list of OSDs in the Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.get_list_osd(zkhandler, limit)

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


@ZKConnection(config)
def ceph_osd_state(zkhandler, osd):
    retflag, retdata = pvc_ceph.get_list_osd(zkhandler, osd)

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

    return {"id": osd, "in": in_state, "up": up_state}, retcode


@ZKConnection(config)
def ceph_osd_add(zkhandler, node, device, weight):
    """
    Add a Ceph OSD to the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.add_osd(zkhandler, node, device, weight)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def ceph_osd_remove(zkhandler, osd_id):
    """
    Remove a Ceph OSD from the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.remove_osd(zkhandler, osd_id)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def ceph_osd_in(zkhandler, osd_id):
    """
    Set in a Ceph OSD in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.in_osd(zkhandler, osd_id)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def ceph_osd_out(zkhandler, osd_id):
    """
    Set out a Ceph OSD in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.out_osd(zkhandler, osd_id)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def ceph_osd_set(zkhandler, option):
    """
    Set options on a Ceph OSD in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.set_osd(zkhandler, option)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def ceph_osd_unset(zkhandler, option):
    """
    Unset options on a Ceph OSD in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.unset_osd(zkhandler, option)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def ceph_pool_list(zkhandler, limit=None, is_fuzzy=True):
    """
    Get the list of RBD pools in the Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.get_list_pool(zkhandler, limit, is_fuzzy)

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


@ZKConnection(config)
def ceph_pool_add(zkhandler, name, pgs, replcfg):
    """
    Add a Ceph RBD pool to the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.add_pool(zkhandler, name, pgs, replcfg)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata
    }
    return output, retcode


@ZKConnection(config)
def ceph_pool_remove(zkhandler, name):
    """
    Remove a Ceph RBD pool to the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.remove_pool(zkhandler, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@pvc_common.Profiler(config)
@ZKConnection(config)
def ceph_volume_list(zkhandler, pool=None, limit=None, is_fuzzy=True):
    """
    Get the list of RBD volumes in the Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.get_list_volume(zkhandler, pool, limit, is_fuzzy)

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


@ZKConnection(config)
def ceph_volume_add(zkhandler, pool, name, size):
    """
    Add a Ceph RBD volume to the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.add_volume(zkhandler, pool, name, size)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def ceph_volume_clone(zkhandler, pool, name, source_volume):
    """
    Clone a Ceph RBD volume to a new volume on the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.clone_volume(zkhandler, pool, source_volume, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def ceph_volume_resize(zkhandler, pool, name, size):
    """
    Resize an existing Ceph RBD volume in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.resize_volume(zkhandler, pool, name, size)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def ceph_volume_rename(zkhandler, pool, name, new_name):
    """
    Rename a Ceph RBD volume in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.rename_volume(zkhandler, pool, name, new_name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def ceph_volume_remove(zkhandler, pool, name):
    """
    Remove a Ceph RBD volume to the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.remove_volume(zkhandler, pool, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def ceph_volume_upload(zkhandler, pool, volume, img_type):
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
    retcode, retdata = pvc_ceph.get_list_volume(zkhandler, pool, volume, is_fuzzy=False)
    # If there's no target, return failure
    if not retcode or len(retdata) < 1:
        output = {
            "message": "Target volume '{}' does not exist in pool '{}'.".format(volume, pool)
        }
        retcode = 400
        return output, retcode
    dev_size = retdata[0]['stats']['size']

    def cleanup_maps_and_volumes():
        # Unmap the target blockdev
        retflag, retdata = pvc_ceph.unmap_volume(zkhandler, pool, volume)
        # Unmap the temporary blockdev
        retflag, retdata = pvc_ceph.unmap_volume(zkhandler, pool, "{}_tmp".format(volume))
        # Remove the temporary blockdev
        retflag, retdata = pvc_ceph.remove_volume(zkhandler, pool, "{}_tmp".format(volume))

    # Create a temporary block device to store non-raw images
    if img_type == 'raw':
        # Map the target blockdev
        retflag, retdata = pvc_ceph.map_volume(zkhandler, pool, volume)
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
            # This sets up a custom stream_factory that writes directly into the ova_blockdev,
            # rather than the standard stream_factory which writes to a temporary file waiting
            # on a save() call. This will break if the API ever uploaded multiple files, but
            # this is an acceptable workaround.
            def image_stream_factory(total_content_length, filename, content_type, content_length=None):
                return open(dest_blockdev, 'wb')
            parse_form_data(flask.request.environ, stream_factory=image_stream_factory)
        except Exception:
            output = {
                'message': "Failed to upload or write image file to temporary volume."
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
        retflag, retdata = pvc_ceph.add_volume(zkhandler, pool, "{}_tmp".format(volume), dev_size)
        if not retflag:
            output = {
                'message': retdata.replace('\"', '\'')
            }
            retcode = 400
            cleanup_maps_and_volumes()
            return output, retcode

        # Map the temporary target blockdev
        retflag, retdata = pvc_ceph.map_volume(zkhandler, pool, "{}_tmp".format(volume))
        if not retflag:
            output = {
                'message': retdata.replace('\"', '\'')
            }
            retcode = 400
            cleanup_maps_and_volumes()
            return output, retcode
        temp_blockdev = retdata

        # Map the target blockdev
        retflag, retdata = pvc_ceph.map_volume(zkhandler, pool, volume)
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
            # This sets up a custom stream_factory that writes directly into the ova_blockdev,
            # rather than the standard stream_factory which writes to a temporary file waiting
            # on a save() call. This will break if the API ever uploaded multiple files, but
            # this is an acceptable workaround.
            def image_stream_factory(total_content_length, filename, content_type, content_length=None):
                return open(temp_blockdev, 'wb')
            parse_form_data(flask.request.environ, stream_factory=image_stream_factory)
        except Exception:
            output = {
                'message': "Failed to upload or write image file to temporary volume."
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


@pvc_common.Profiler(config)
@ZKConnection(config)
def ceph_volume_snapshot_list(zkhandler, pool=None, volume=None, limit=None, is_fuzzy=True):
    """
    Get the list of RBD volume snapshots in the Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.get_list_snapshot(zkhandler, pool, volume, limit, is_fuzzy)

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


@ZKConnection(config)
def ceph_volume_snapshot_add(zkhandler, pool, volume, name):
    """
    Add a Ceph RBD volume snapshot to the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.add_snapshot(zkhandler, pool, volume, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def ceph_volume_snapshot_rename(zkhandler, pool, volume, name, new_name):
    """
    Rename a Ceph RBD volume snapshot in the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.rename_snapshot(zkhandler, pool, volume, name, new_name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode


@ZKConnection(config)
def ceph_volume_snapshot_remove(zkhandler, pool, volume, name):
    """
    Remove a Ceph RBD volume snapshot from the PVC Ceph storage cluster.
    """
    retflag, retdata = pvc_ceph.remove_snapshot(zkhandler, pool, volume, name)

    if retflag:
        retcode = 200
    else:
        retcode = 400

    output = {
        'message': retdata.replace('\"', '\'')
    }
    return output, retcode
