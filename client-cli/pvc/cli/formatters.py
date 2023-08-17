#!/usr/bin/env python3

# formatters.py - PVC Click CLI output formatters library
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2023 Joshua M. Boniface <joshua@boniface.me>
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

from pvc.lib.node import format_info as node_format_info
from pvc.lib.node import format_list as node_format_list
from pvc.lib.vm import format_vm_tags as vm_format_tags
from pvc.lib.vm import format_vm_vcpus as vm_format_vcpus
from pvc.lib.vm import format_vm_memory as vm_format_memory
from pvc.lib.vm import format_vm_networks as vm_format_networks
from pvc.lib.vm import format_vm_volumes as vm_format_volumes
from pvc.lib.vm import format_info as vm_format_info
from pvc.lib.vm import format_list as vm_format_list
from pvc.lib.network import format_info as network_format_info
from pvc.lib.network import format_list as network_format_list
from pvc.lib.network import format_list_dhcp as network_format_dhcp_list
from pvc.lib.network import format_list_acl as network_format_acl_list
from pvc.lib.network import format_list_sriov_pf as network_format_sriov_pf_list
from pvc.lib.network import format_info_sriov_vf as network_format_sriov_vf_info
from pvc.lib.network import format_list_sriov_vf as network_format_sriov_vf_list
from pvc.lib.storage import format_raw_output as storage_format_raw
from pvc.lib.storage import format_info_benchmark as storage_format_benchmark_info
from pvc.lib.storage import format_list_benchmark as storage_format_benchmark_list
from pvc.lib.storage import format_list_osd as storage_format_osd_list
from pvc.lib.storage import format_list_pool as storage_format_pool_list
from pvc.lib.storage import format_list_volume as storage_format_volume_list
from pvc.lib.storage import format_list_snapshot as storage_format_snapshot_list
from pvc.lib.provisioner import format_list_template as provisioner_format_template_list
from pvc.lib.provisioner import format_list_userdata as provisioner_format_userdata_list
from pvc.lib.provisioner import format_list_script as provisioner_format_script_list
from pvc.lib.provisioner import format_list_ova as provisioner_format_ova_list
from pvc.lib.provisioner import format_list_profile as provisioner_format_profile_list
from pvc.lib.provisioner import format_list_task as provisioner_format_task_status


# Define colour values for use in formatters
ansii = {
    "red": "\033[91m",
    "blue": "\033[94m",
    "cyan": "\033[96m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "purple": "\033[95m",
    "bold": "\033[1m",
    "end": "\033[0m",
}


def cli_cluster_status_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the full output of cli_cluster_status
    """

    # Normalize data to local variables
    health = data.get("cluster_health", {}).get("health", -1)
    messages = data.get("cluster_health", {}).get("messages", None)
    maintenance = data.get("maintenance", "N/A")
    primary_node = data.get("primary_node", "N/A")
    pvc_version = data.get("pvc_version", "N/A")
    upstream_ip = data.get("upstream_ip", "N/A")
    total_nodes = data.get("nodes", {}).get("total", 0)
    total_vms = data.get("vms", {}).get("total", 0)
    total_networks = data.get("networks", 0)
    total_osds = data.get("osds", {}).get("total", 0)
    total_pools = data.get("pools", 0)
    total_volumes = data.get("volumes", 0)
    total_snapshots = data.get("snapshots", 0)

    if maintenance == "true" or health == -1:
        health_colour = ansii["blue"]
    elif health > 90:
        health_colour = ansii["green"]
    elif health > 50:
        health_colour = ansii["yellow"]
    else:
        health_colour = ansii["red"]

    output = list()

    output.append(f"{ansii['bold']}PVC cluster status:{ansii['end']}")
    output.append("")

    if health != "-1":
        health = f"{health}%"
    else:
        health = "N/A"

    if maintenance == "true":
        health = f"{health} (maintenance on)"

    output.append(
        f"{ansii['purple']}Cluster health:{ansii['end']}   {health_colour}{health}{ansii['end']}"
    )

    if messages is not None and len(messages) > 0:
        messages = "\n                  ".join(sorted(messages))
        output.append(f"{ansii['purple']}Health messages:{ansii['end']}  {messages}")

    output.append("")

    output.append(f"{ansii['purple']}Primary node:{ansii['end']}     {primary_node}")
    output.append(f"{ansii['purple']}PVC version:{ansii['end']}      {pvc_version}")
    output.append(f"{ansii['purple']}Upstream IP:{ansii['end']}      {upstream_ip}")
    output.append("")

    node_states = ["run,ready"]
    node_states.extend(
        [
            state
            for state in data.get("nodes", {}).keys()
            if state not in ["total", "run,ready"]
        ]
    )

    nodes_strings = list()
    for state in node_states:
        if state in ["run,ready"]:
            state_colour = ansii["green"]
        elif state in ["run,flush", "run,unflush", "run,flushed"]:
            state_colour = ansii["blue"]
        elif "dead" in state or "stop" in state:
            state_colour = ansii["red"]
        else:
            state_colour = ansii["yellow"]

        nodes_strings.append(
            f"{data.get('nodes', {}).get(state)}/{total_nodes} {state_colour}{state}{ansii['end']}"
        )

    nodes_string = ", ".join(nodes_strings)

    output.append(f"{ansii['purple']}Nodes:{ansii['end']}            {nodes_string}")

    vm_states = ["start", "disable"]
    vm_states.extend(
        [
            state
            for state in data.get("vms", {}).keys()
            if state not in ["total", "start", "disable"]
        ]
    )

    vms_strings = list()
    for state in vm_states:
        if state in ["start"]:
            state_colour = ansii["green"]
        elif state in ["migrate", "disable"]:
            state_colour = ansii["blue"]
        elif state in ["stop", "fail"]:
            state_colour = ansii["red"]
        else:
            state_colour = ansii["yellow"]

        vms_strings.append(
            f"{data.get('vms', {}).get(state)}/{total_vms} {state_colour}{state}{ansii['end']}"
        )

    vms_string = ", ".join(vms_strings)

    output.append(f"{ansii['purple']}VMs:{ansii['end']}              {vms_string}")

    osd_states = ["up,in"]
    osd_states.extend(
        [
            state
            for state in data.get("osds", {}).keys()
            if state not in ["total", "up,in"]
        ]
    )

    osds_strings = list()
    for state in osd_states:
        if state in ["up,in"]:
            state_colour = ansii["green"]
        elif state in ["down,out"]:
            state_colour = ansii["red"]
        else:
            state_colour = ansii["yellow"]

        osds_strings.append(
            f"{data.get('osds', {}).get(state)}/{total_osds} {state_colour}{state}{ansii['end']}"
        )

    osds_string = " ".join(osds_strings)

    output.append(f"{ansii['purple']}OSDs:{ansii['end']}             {osds_string}")

    output.append(f"{ansii['purple']}Pools:{ansii['end']}            {total_pools}")

    output.append(f"{ansii['purple']}Volumes:{ansii['end']}          {total_volumes}")

    output.append(f"{ansii['purple']}Snapshots:{ansii['end']}        {total_snapshots}")

    output.append(f"{ansii['purple']}Networks:{ansii['end']}         {total_networks}")

    output.append("")

    return "\n".join(output)


def cli_cluster_status_format_short(CLI_CONFIG, data):
    """
    Pretty format the health-only output of cli_cluster_status
    """

    # Normalize data to local variables
    health = data.get("cluster_health", {}).get("health", -1)
    messages = data.get("cluster_health", {}).get("messages", None)
    maintenance = data.get("maintenance", "N/A")

    if maintenance == "true" or health == -1:
        health_colour = ansii["blue"]
    elif health > 90:
        health_colour = ansii["green"]
    elif health > 50:
        health_colour = ansii["yellow"]
    else:
        health_colour = ansii["red"]

    output = list()

    output.append(f"{ansii['bold']}PVC cluster status:{ansii['end']}")
    output.append("")

    if health != "-1":
        health = f"{health}%"
    else:
        health = "N/A"

    if maintenance == "true":
        health = f"{health} (maintenance on)"

    output.append(
        f"{ansii['purple']}Cluster health:{ansii['end']}   {health_colour}{health}{ansii['end']}"
    )

    if messages is not None and len(messages) > 0:
        messages = "\n                  ".join(sorted(messages))
        output.append(f"{ansii['purple']}Health messages:{ansii['end']}  {messages}")

    output.append("")

    return "\n".join(output)


def cli_connection_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_connection_list
    """

    # Set the fields data
    fields = {
        "name": {"header": "Name", "length": len("Name") + 1},
        "description": {"header": "Description", "length": len("Description") + 1},
        "address": {"header": "Address", "length": len("Address") + 1},
        "port": {"header": "Port", "length": len("Port") + 1},
        "scheme": {"header": "Scheme", "length": len("Scheme") + 1},
        "api_key": {"header": "API Key", "length": len("API Key") + 1},
    }

    # Parse each connection and adjust field lengths
    for connection in data:
        for field, length in [(f, fields[f]["length"]) for f in fields]:
            _length = len(str(connection[field]))
            if _length > length:
                length = len(str(connection[field])) + 1

            fields[field]["length"] = length

    # Create the output object and define the line format
    output = list()
    line = "{bold}{name: <{lname}} {desc: <{ldesc}} {addr: <{laddr}} {port: <{lport}} {schm: <{lschm}} {akey: <{lakey}}{end}"

    # Add the header line
    output.append(
        line.format(
            bold=ansii["bold"],
            end=ansii["end"],
            name=fields["name"]["header"],
            lname=fields["name"]["length"],
            desc=fields["description"]["header"],
            ldesc=fields["description"]["length"],
            addr=fields["address"]["header"],
            laddr=fields["address"]["length"],
            port=fields["port"]["header"],
            lport=fields["port"]["length"],
            schm=fields["scheme"]["header"],
            lschm=fields["scheme"]["length"],
            akey=fields["api_key"]["header"],
            lakey=fields["api_key"]["length"],
        )
    )

    # Add a line per connection
    for connection in data:
        output.append(
            line.format(
                bold="",
                end="",
                name=connection["name"],
                lname=fields["name"]["length"],
                desc=connection["description"],
                ldesc=fields["description"]["length"],
                addr=connection["address"],
                laddr=fields["address"]["length"],
                port=connection["port"],
                lport=fields["port"]["length"],
                schm=connection["scheme"],
                lschm=fields["scheme"]["length"],
                akey=connection["api_key"],
                lakey=fields["api_key"]["length"],
            )
        )

    return "\n".join(output)


def cli_connection_detail_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_connection_detail
    """

    # Set the fields data
    fields = {
        "name": {"header": "Name", "length": len("Name") + 1},
        "description": {"header": "Description", "length": len("Description") + 1},
        "health": {"header": "Health", "length": len("Health") + 1},
        "primary_node": {"header": "Primary", "length": len("Primary") + 1},
        "pvc_version": {"header": "Version", "length": len("Version") + 1},
        "nodes": {"header": "Nodes", "length": len("Nodes") + 1},
        "vms": {"header": "VMs", "length": len("VMs") + 1},
        "networks": {"header": "Networks", "length": len("Networks") + 1},
        "osds": {"header": "OSDs", "length": len("OSDs") + 1},
        "pools": {"header": "Pools", "length": len("Pools") + 1},
        "volumes": {"header": "Volumes", "length": len("Volumes") + 1},
        "snapshots": {"header": "Snapshots", "length": len("Snapshots") + 1},
    }

    # Parse each connection and adjust field lengths
    for connection in data:
        for field, length in [(f, fields[f]["length"]) for f in fields]:
            _length = len(str(connection[field]))
            if _length > length:
                length = len(str(connection[field])) + 1

            fields[field]["length"] = length

    # Create the output object and define the line format
    output = list()
    line = "{bold}{name: <{lname}} {desc: <{ldesc}} {chlth}{hlth: <{lhlth}}{endc} {prin: <{lprin}} {vers: <{lvers}} {nods: <{lnods}} {vms: <{lvms}} {nets: <{lnets}} {osds: <{losds}} {pols: <{lpols}} {vols: <{lvols}} {snts: <{lsnts}}{end}"

    # Add the header line
    output.append(
        line.format(
            bold=ansii["bold"],
            end=ansii["end"],
            chlth="",
            endc="",
            name=fields["name"]["header"],
            lname=fields["name"]["length"],
            desc=fields["description"]["header"],
            ldesc=fields["description"]["length"],
            hlth=fields["health"]["header"],
            lhlth=fields["health"]["length"],
            prin=fields["primary_node"]["header"],
            lprin=fields["primary_node"]["length"],
            vers=fields["pvc_version"]["header"],
            lvers=fields["pvc_version"]["length"],
            nods=fields["nodes"]["header"],
            lnods=fields["nodes"]["length"],
            vms=fields["vms"]["header"],
            lvms=fields["vms"]["length"],
            nets=fields["networks"]["header"],
            lnets=fields["networks"]["length"],
            osds=fields["osds"]["header"],
            losds=fields["osds"]["length"],
            pols=fields["pools"]["header"],
            lpols=fields["pools"]["length"],
            vols=fields["volumes"]["header"],
            lvols=fields["volumes"]["length"],
            snts=fields["snapshots"]["header"],
            lsnts=fields["snapshots"]["length"],
        )
    )

    # Add a line per connection
    for connection in data:
        if connection["health"] == "N/A":
            health_value = "N/A"
            health_colour = ansii["purple"]
        else:
            health_value = f"{connection['health']}%"
            if connection["maintenance"] == "true":
                health_colour = ansii["blue"]
            elif connection["health"] > 90:
                health_colour = ansii["green"]
            elif connection["health"] > 50:
                health_colour = ansii["yellow"]
            else:
                health_colour = ansii["red"]

        output.append(
            line.format(
                bold="",
                end="",
                chlth=health_colour,
                endc=ansii["end"],
                name=connection["name"],
                lname=fields["name"]["length"],
                desc=connection["description"],
                ldesc=fields["description"]["length"],
                hlth=health_value,
                lhlth=fields["health"]["length"],
                prin=connection["primary_node"],
                lprin=fields["primary_node"]["length"],
                vers=connection["pvc_version"],
                lvers=fields["pvc_version"]["length"],
                nods=connection["nodes"],
                lnods=fields["nodes"]["length"],
                vms=connection["vms"],
                lvms=fields["vms"]["length"],
                nets=connection["networks"],
                lnets=fields["networks"]["length"],
                osds=connection["osds"],
                losds=fields["osds"]["length"],
                pols=connection["pools"],
                lpols=fields["pools"]["length"],
                vols=connection["volumes"],
                lvols=fields["volumes"]["length"],
                snts=connection["snapshots"],
                lsnts=fields["snapshots"]["length"],
            )
        )

    return "\n".join(output)


def cli_node_info_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the basic output of cli_node_info
    """

    return node_format_info(CLI_CONFIG, data, long_output=False)


def cli_node_info_format_long(CLI_CONFIG, data):
    """
    Pretty format the full output of cli_node_info
    """

    return node_format_info(CLI_CONFIG, data, long_output=True)


def cli_node_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_node_list
    """

    return node_format_list(CLI_CONFIG, data)


def cli_vm_tag_get_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_vm_tag_get
    """

    return vm_format_tags(CLI_CONFIG, data)


def cli_vm_vcpu_get_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_vm_vcpu_get
    """

    return vm_format_vcpus(CLI_CONFIG, data)


def cli_vm_memory_get_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_vm_memory_get
    """

    return vm_format_memory(CLI_CONFIG, data)


def cli_vm_network_get_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_vm_network_get
    """

    return vm_format_networks(CLI_CONFIG, data)


def cli_vm_volume_get_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_vm_volume_get
    """

    return vm_format_volumes(CLI_CONFIG, data)


def cli_vm_info_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the basic output of cli_vm_info
    """

    return vm_format_info(CLI_CONFIG, data, long_output=False)


def cli_vm_info_format_long(CLI_CONFIG, data):
    """
    Pretty format the full output of cli_vm_info
    """

    return vm_format_info(CLI_CONFIG, data, long_output=True)


def cli_vm_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_vm_list
    """

    return vm_format_list(CLI_CONFIG, data)


def cli_network_info_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the full output of cli_network_info
    """

    return network_format_info(CLI_CONFIG, data, long_output=True)


def cli_network_info_format_long(CLI_CONFIG, data):
    """
    Pretty format the full output of cli_network_info
    """

    return network_format_info(CLI_CONFIG, data, long_output=True)


def cli_network_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_network_list
    """

    return network_format_list(CLI_CONFIG, data)


def cli_network_dhcp_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_network_dhcp_list
    """

    return network_format_dhcp_list(CLI_CONFIG, data)


def cli_network_acl_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_network_acl_list
    """

    return network_format_acl_list(CLI_CONFIG, data)


def cli_network_sriov_pf_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_network_sriov_pf_list
    """

    return network_format_sriov_pf_list(CLI_CONFIG, data)


def cli_network_sriov_vf_info_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_network_sriov_vf_info
    """

    return network_format_sriov_vf_info(CLI_CONFIG, data)


def cli_network_sriov_vf_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_network_sriov_vf_list
    """

    return network_format_sriov_vf_list(CLI_CONFIG, data)


def cli_storage_status_format_raw(CLI_CONFIG, data):
    """
    Direct format the output of cli_storage_status
    """

    return storage_format_raw(CLI_CONFIG, data)


def cli_storage_util_format_raw(CLI_CONFIG, data):
    """
    Direct format the output of cli_storage_util
    """

    return storage_format_raw(CLI_CONFIG, data)


def cli_storage_benchmark_info_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_storage_benchmark_info
    """

    return storage_format_benchmark_info(CLI_CONFIG, data)


def cli_storage_benchmark_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_storage_benchmark_list
    """

    return storage_format_benchmark_list(CLI_CONFIG, data)


def cli_storage_osd_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_storage_osd_list
    """

    return storage_format_osd_list(CLI_CONFIG, data)


def cli_storage_pool_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_storage_pool_list
    """

    return storage_format_pool_list(CLI_CONFIG, data)


def cli_storage_volume_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_storage_volume_list
    """

    return storage_format_volume_list(CLI_CONFIG, data)


def cli_storage_snapshot_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_storage_snapshot_list
    """

    return storage_format_snapshot_list(CLI_CONFIG, data)


def cli_provisioner_template_system_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_provisioner_template_system_list
    """

    return provisioner_format_template_list(CLI_CONFIG, data, template_type="system")


def cli_provisioner_template_network_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_provisioner_template_network_list
    """

    return provisioner_format_template_list(CLI_CONFIG, data, template_type="network")


def cli_provisioner_template_storage_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_provisioner_template_storage_list
    """

    return provisioner_format_template_list(CLI_CONFIG, data, template_type="storage")


def cli_provisioner_userdata_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_provisioner_userdata_list
    """

    return provisioner_format_userdata_list(CLI_CONFIG, data)


def cli_provisioner_script_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_provisioner_script_list
    """

    return provisioner_format_script_list(CLI_CONFIG, data)


def cli_provisioner_ova_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_provisioner_ova_list
    """

    return provisioner_format_ova_list(CLI_CONFIG, data)


def cli_provisioner_profile_list_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_provisioner_profile_list
    """

    return provisioner_format_profile_list(CLI_CONFIG, data)


def cli_provisioner_status_format_pretty(CLI_CONFIG, data):
    """
    Pretty format the output of cli_provisioner_status
    """

    return provisioner_format_task_status(CLI_CONFIG, data)
