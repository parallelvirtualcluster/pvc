#!/usr/bin/env python3

# formatters.py - PVC Click CLI output formatters library
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2024 Joshua M. Boniface <joshua@boniface.me>
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

from pvc.cli.helpers import MAX_CONTENT_WIDTH
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

    total_cpu_total = data.get("resources", {}).get("cpu", {}).get("total", 0)
    total_cpu_load = data.get("resources", {}).get("cpu", {}).get("load", 0)
    total_cpu_utilization = (
        data.get("resources", {}).get("cpu", {}).get("utilization", 0)
    )
    total_cpu_string = (
        f"{total_cpu_utilization:.1f}% ({total_cpu_load:.1f} / {total_cpu_total})"
    )

    total_memory_total = (
        data.get("resources", {}).get("memory", {}).get("total", 0) / 1024
    )
    total_memory_used = (
        data.get("resources", {}).get("memory", {}).get("used", 0) / 1024
    )
    total_memory_utilization = (
        data.get("resources", {}).get("memory", {}).get("utilization", 0)
    )
    total_memory_string = f"{total_memory_utilization:.1f}% ({total_memory_used:.1f} GB / {total_memory_total:.1f} GB)"

    total_disk_total = (
        data.get("resources", {}).get("disk", {}).get("total", 0) / 1024 / 1024
    )
    total_disk_used = (
        data.get("resources", {}).get("disk", {}).get("used", 0) / 1024 / 1024
    )
    total_disk_utilization = round(
        data.get("resources", {}).get("disk", {}).get("utilization", 0)
    )
    total_disk_string = f"{total_disk_utilization:.1f}% ({total_disk_used:.1f} GB / {total_disk_total:.1f} GB)"

    if maintenance == "true" or health == -1:
        health_colour = ansii["blue"]
    elif health > 90:
        health_colour = ansii["green"]
    elif health > 50:
        health_colour = ansii["yellow"]
    else:
        health_colour = ansii["red"]

    output = list()

    output.append(f"{ansii['purple']}Primary node:{ansii['end']}   {primary_node}")
    output.append(f"{ansii['purple']}PVC version:{ansii['end']}    {pvc_version}")
    output.append(f"{ansii['purple']}Upstream IP:{ansii['end']}    {upstream_ip}")
    output.append("")

    if health != "-1":
        health = f"{health}%"
    else:
        health = "N/A"

    if maintenance == "true":
        health = f"{health} (maintenance on)"

    output.append(
        f"{ansii['purple']}Health:{ansii['end']}         {health_colour}{health}{ansii['end']}"
    )

    if messages is not None and len(messages) > 0:
        message_list = list()
        for message in messages:
            if message["health_delta"] >= 50:
                message_colour = ansii["red"]
            elif message["health_delta"] >= 10:
                message_colour = ansii["yellow"]
            else:
                message_colour = ansii["green"]
            message_delta = (
                f"({message_colour}-{message['health_delta']}%{ansii['end']})"
            )
            message_list.append(
                # 15 length due to ANSI colour sequences
                "{id} {delta:<15} {text}".format(
                    id=message["id"],
                    delta=message_delta,
                    text=message["text"],
                )
            )

        messages = "\n                ".join(message_list)
    else:
        messages = "None"
    output.append(f"{ansii['purple']}Active faults:{ansii['end']}  {messages}")

    output.append(f"{ansii['purple']}Total CPU:{ansii['end']}      {total_cpu_string}")

    output.append(
        f"{ansii['purple']}Total memory:{ansii['end']}   {total_memory_string}"
    )

    output.append(f"{ansii['purple']}Total disk:{ansii['end']}     {total_disk_string}")

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
        elif "dead" in state or "fenced" in state or "stop" in state:
            state_colour = ansii["red"]
        else:
            state_colour = ansii["yellow"]

        nodes_strings.append(
            f"{data.get('nodes', {}).get(state)}/{total_nodes} {state_colour}{state}{ansii['end']}"
        )

    nodes_string = ", ".join(nodes_strings)

    output.append(f"{ansii['purple']}Nodes:{ansii['end']}          {nodes_string}")

    vm_states = ["start", "disable", "mirror"]
    vm_states.extend(
        [
            state
            for state in data.get("vms", {}).keys()
            if state not in ["total", "start", "disable", "mirror"]
        ]
    )

    vms_strings = list()
    for state in vm_states:
        if data.get("vms", {}).get(state) is None:
            continue
        if state in ["start"]:
            state_colour = ansii["green"]
        elif state in ["migrate", "disable", "provision", "mirror"]:
            state_colour = ansii["blue"]
        elif state in ["mirror"]:
            state_colour = ansii["purple"]
        elif state in ["stop", "fail"]:
            state_colour = ansii["red"]
        else:
            state_colour = ansii["yellow"]

        vms_strings.append(
            f"{data.get('vms', {}).get(state)}/{total_vms} {state_colour}{state}{ansii['end']}"
        )

    vms_string = ", ".join(vms_strings)

    output.append(f"{ansii['purple']}VMs:{ansii['end']}            {vms_string}")

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

    output.append(f"{ansii['purple']}OSDs:{ansii['end']}           {osds_string}")

    output.append(f"{ansii['purple']}Pools:{ansii['end']}          {total_pools}")

    output.append(f"{ansii['purple']}Volumes:{ansii['end']}        {total_volumes}")

    output.append(f"{ansii['purple']}Snapshots:{ansii['end']}      {total_snapshots}")

    output.append(f"{ansii['purple']}Networks:{ansii['end']}       {total_networks}")

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

    if health != "-1":
        health = f"{health}%"
    else:
        health = "N/A"

    if maintenance == "true":
        health = f"{health} (maintenance on)"

    output.append(
        f"{ansii['purple']}Health:{ansii['end']}         {health_colour}{health}{ansii['end']}"
    )

    if messages is not None and len(messages) > 0:
        message_list = list()
        for message in messages:
            if message["health_delta"] >= 50:
                message_colour = ansii["red"]
            elif message["health_delta"] >= 10:
                message_colour = ansii["yellow"]
            else:
                message_colour = ansii["green"]
            message_delta = (
                f"({message_colour}-{message['health_delta']}%{ansii['end']})"
            )
            message_list.append(
                # 15 length due to ANSI colour sequences
                "{id} {delta:<15} {text}".format(
                    id=message["id"],
                    delta=message_delta,
                    text=message["text"],
                )
            )

        messages = "\n               ".join(message_list)
    else:
        messages = "None"
    output.append(f"{ansii['purple']}Active faults:{ansii['end']}  {messages}")

    total_cpu_total = data.get("resources", {}).get("cpu", {}).get("total", 0)
    total_cpu_load = data.get("resources", {}).get("cpu", {}).get("load", 0)
    total_cpu_utilization = (
        data.get("resources", {}).get("cpu", {}).get("utilization", 0)
    )
    total_cpu_string = (
        f"{total_cpu_utilization:.1f}% ({total_cpu_load:.1f} / {total_cpu_total})"
    )

    total_memory_total = (
        data.get("resources", {}).get("memory", {}).get("total", 0) / 1024
    )
    total_memory_used = (
        data.get("resources", {}).get("memory", {}).get("used", 0) / 1024
    )
    total_memory_utilization = (
        data.get("resources", {}).get("memory", {}).get("utilization", 0)
    )
    total_memory_string = f"{total_memory_utilization:.1f}% ({total_memory_used:.1f} GB / {total_memory_total:.1f} GB)"

    total_disk_total = (
        data.get("resources", {}).get("disk", {}).get("total", 0) / 1024 / 1024
    )
    total_disk_used = (
        data.get("resources", {}).get("disk", {}).get("used", 0) / 1024 / 1024
    )
    total_disk_utilization = round(
        data.get("resources", {}).get("disk", {}).get("utilization", 0)
    )
    total_disk_string = f"{total_disk_utilization:.1f}% ({total_disk_used:.1f} GB / {total_disk_total:.1f} GB)"

    output.append(f"{ansii['purple']}CPU usage:{ansii['end']}      {total_cpu_string}")

    output.append(
        f"{ansii['purple']}Memory usage:{ansii['end']}   {total_memory_string}"
    )

    output.append(f"{ansii['purple']}Disk usage:{ansii['end']}     {total_disk_string}")

    output.append("")

    return "\n".join(output)


def cli_cluster_fault_list_format_short(CLI_CONFIG, fault_data):
    """
    Short pretty format the output of cli_cluster_fault_list
    """

    fault_list_output = []

    # Determine optimal column widths
    fault_id_length = 3  # "ID"
    fault_status_length = 7  # "Status"
    fault_last_reported_length = 14  # "Last Reported"
    fault_health_delta_length = 7  # "Health"
    fault_message_length = 8  # "Message"

    for fault in fault_data:
        # fault_id column
        _fault_id_length = len(str(fault["id"])) + 1
        if _fault_id_length > fault_id_length:
            fault_id_length = _fault_id_length

        # status column
        _fault_status_length = len(str(fault["status"])) + 1
        if _fault_status_length > fault_status_length:
            fault_status_length = _fault_status_length

        # health_delta column
        _fault_health_delta_length = len(str(fault["health_delta"])) + 1
        if _fault_health_delta_length > fault_health_delta_length:
            fault_health_delta_length = _fault_health_delta_length

        # last_reported column
        _fault_last_reported_length = len(str(fault["last_reported"])) + 1
        if _fault_last_reported_length > fault_last_reported_length:
            fault_last_reported_length = _fault_last_reported_length

    message_prefix_len = (
        fault_id_length
        + 1
        + fault_status_length
        + 1
        + fault_health_delta_length
        + 1
        + fault_last_reported_length
        + 1
    )
    message_length = MAX_CONTENT_WIDTH - message_prefix_len

    if fault_message_length > message_length:
        fault_message_length = message_length + 1

    # Handle splitting fault messages into separate lines based on width
    formatted_messages = dict()
    for fault in fault_data:
        split_message = list()
        if len(fault["message"]) > message_length:
            words = fault["message"].split()
            current_line = words[0]
            for word in words[1:]:
                if len(current_line) + len(word) + 1 < message_length:
                    current_line = f"{current_line} {word}"
                else:
                    split_message.append(current_line)
                    current_line = word
            split_message.append(current_line)

            for line in split_message:
                # message column
                _fault_message_length = len(line) + 1
                if _fault_message_length > fault_message_length:
                    fault_message_length = _fault_message_length

            message = f"\n{' ' * message_prefix_len}".join(split_message)
        else:
            message = fault["message"]

            # message column
            _fault_message_length = len(message) + 1
            if _fault_message_length > fault_message_length:
                fault_message_length = _fault_message_length

        formatted_messages[fault["id"]] = message

    meta_header_length = (
        fault_id_length + fault_status_length + fault_health_delta_length + 2
    )
    detail_header_length = (
        fault_id_length
        + fault_health_delta_length
        + fault_status_length
        + fault_last_reported_length
        + fault_message_length
        + 3
        - meta_header_length
    )

    # Format the string (header)
    fault_list_output.append(
        "{bold}Meta {meta_dashes}  Fault {detail_dashes}{end_bold}".format(
            bold=ansii["bold"],
            end_bold=ansii["end"],
            meta_dashes="-" * (meta_header_length - len("Meta  ")),
            detail_dashes="-" * (detail_header_length - len("Fault  ")),
        )
    )

    fault_list_output.append(
        "{bold}{fault_id: <{fault_id_length}} {fault_status: <{fault_status_length}} {fault_health_delta: <{fault_health_delta_length}} {fault_last_reported: <{fault_last_reported_length}} {fault_message}{end_bold}".format(
            bold=ansii["bold"],
            end_bold=ansii["end"],
            fault_id_length=fault_id_length,
            fault_status_length=fault_status_length,
            fault_health_delta_length=fault_health_delta_length,
            fault_last_reported_length=fault_last_reported_length,
            fault_id="ID",
            fault_status="Status",
            fault_health_delta="Health",
            fault_last_reported="Last Reported",
            fault_message="Message",
        )
    )

    for fault in sorted(
        fault_data,
        key=lambda x: (x["health_delta"], x["last_reported"]),
        reverse=True,
    ):
        health_delta = fault["health_delta"]
        if fault["acknowledged_at"] != "":
            health_colour = ansii["blue"]
        elif health_delta >= 50:
            health_colour = ansii["red"]
        elif health_delta >= 10:
            health_colour = ansii["yellow"]
        else:
            health_colour = ansii["green"]

        if len(fault["message"]) > message_length:
            words = fault["message"].split()
            split_message = list()
            current_line = words[0]
            for word in words:
                if len(current_line) + len(word) + 1 < message_length:
                    current_line = f"{current_line} {word}"
                else:
                    split_message.append(current_line)
                    current_line = word
            split_message.append(current_line)

            message = f"\n{' ' * message_prefix_len}".join(split_message)
        else:
            message = fault["message"]

        fault_list_output.append(
            "{bold}{fault_id: <{fault_id_length}} {fault_status: <{fault_status_length}} {health_colour}{fault_health_delta: <{fault_health_delta_length}}{end_colour} {fault_last_reported: <{fault_last_reported_length}} {fault_message}{end_bold}".format(
                bold="",
                end_bold="",
                health_colour=health_colour,
                end_colour=ansii["end"],
                fault_id_length=fault_id_length,
                fault_status_length=fault_status_length,
                fault_health_delta_length=fault_health_delta_length,
                fault_last_reported_length=fault_last_reported_length,
                fault_id=fault["id"],
                fault_status=fault["status"],
                fault_health_delta=f"-{fault['health_delta']}%",
                fault_last_reported=fault["last_reported"],
                fault_message=formatted_messages[fault["id"]],
            )
        )

    return "\n".join(fault_list_output)


def cli_cluster_fault_list_format_long(CLI_CONFIG, fault_data):
    """
    Pretty format the output of cli_cluster_fault_list
    """

    fault_list_output = []

    # Determine optimal column widths
    fault_id_length = 3  # "ID"
    fault_status_length = 7  # "Status"
    fault_health_delta_length = 7  # "Health"
    fault_acknowledged_at_length = 9  # "Ack'd On"
    fault_last_reported_length = 14  # "Last Reported"
    fault_first_reported_length = 15  # "First Reported"
    # Message goes on its own line

    for fault in fault_data:
        # fault_id column
        _fault_id_length = len(str(fault["id"])) + 1
        if _fault_id_length > fault_id_length:
            fault_id_length = _fault_id_length

        # status column
        _fault_status_length = len(str(fault["status"])) + 1
        if _fault_status_length > fault_status_length:
            fault_status_length = _fault_status_length

        # health_delta column
        _fault_health_delta_length = len(str(fault["health_delta"])) + 1
        if _fault_health_delta_length > fault_health_delta_length:
            fault_health_delta_length = _fault_health_delta_length

        # acknowledged_at column
        _fault_acknowledged_at_length = len(str(fault["acknowledged_at"])) + 1
        if _fault_acknowledged_at_length > fault_acknowledged_at_length:
            fault_acknowledged_at_length = _fault_acknowledged_at_length

        # last_reported column
        _fault_last_reported_length = len(str(fault["last_reported"])) + 1
        if _fault_last_reported_length > fault_last_reported_length:
            fault_last_reported_length = _fault_last_reported_length

        # first_reported column
        _fault_first_reported_length = len(str(fault["first_reported"])) + 1
        if _fault_first_reported_length > fault_first_reported_length:
            fault_first_reported_length = _fault_first_reported_length

    # Format the string (header)
    fault_list_output.append(
        "{bold}{fault_id: <{fault_id_length}} {fault_status: <{fault_status_length}} {fault_health_delta: <{fault_health_delta_length}} {fault_acknowledged_at: <{fault_acknowledged_at_length}} {fault_last_reported: <{fault_last_reported_length}} {fault_first_reported: <{fault_first_reported_length}}{end_bold}".format(
            bold=ansii["bold"],
            end_bold=ansii["end"],
            fault_id_length=fault_id_length,
            fault_status_length=fault_status_length,
            fault_health_delta_length=fault_health_delta_length,
            fault_acknowledged_at_length=fault_acknowledged_at_length,
            fault_last_reported_length=fault_last_reported_length,
            fault_first_reported_length=fault_first_reported_length,
            fault_id="ID",
            fault_status="Status",
            fault_health_delta="Health",
            fault_acknowledged_at="Ack'd On",
            fault_last_reported="Last Reported",
            fault_first_reported="First Reported",
        )
    )
    fault_list_output.append(
        "{bold}> {fault_message}{end_bold}".format(
            bold=ansii["bold"],
            end_bold=ansii["end"],
            fault_message="Message",
        )
    )

    for fault in sorted(
        fault_data,
        key=lambda x: (x["status"], x["health_delta"], x["last_reported"]),
        reverse=True,
    ):
        health_delta = fault["health_delta"]
        if fault["acknowledged_at"] != "":
            health_colour = ansii["blue"]
        elif health_delta >= 50:
            health_colour = ansii["red"]
        elif health_delta >= 10:
            health_colour = ansii["yellow"]
        else:
            health_colour = ansii["green"]

        fault_list_output.append("")
        fault_list_output.append(
            "{bold}{fault_id: <{fault_id_length}} {health_colour}{fault_status: <{fault_status_length}} {fault_health_delta: <{fault_health_delta_length}}{end_colour} {fault_acknowledged_at: <{fault_acknowledged_at_length}} {fault_last_reported: <{fault_last_reported_length}} {fault_first_reported: <{fault_first_reported_length}}{end_bold}".format(
                bold="",
                end_bold="",
                health_colour=health_colour,
                end_colour=ansii["end"],
                fault_id_length=fault_id_length,
                fault_status_length=fault_status_length,
                fault_health_delta_length=fault_health_delta_length,
                fault_acknowledged_at_length=fault_acknowledged_at_length,
                fault_last_reported_length=fault_last_reported_length,
                fault_first_reported_length=fault_first_reported_length,
                fault_id=fault["id"],
                fault_status=fault["status"].title(),
                fault_health_delta=f"-{fault['health_delta']}%",
                fault_acknowledged_at=(
                    fault["acknowledged_at"]
                    if fault["acknowledged_at"] != ""
                    else "N/A"
                ),
                fault_last_reported=fault["last_reported"],
                fault_first_reported=fault["first_reported"],
            )
        )
        fault_list_output.append(
            "> {fault_message}".format(
                fault_message=fault["message"],
            )
        )

    return "\n".join(fault_list_output)


def cli_cluster_task_format_pretty(CLI_CONFIG, task_data):
    """
    Pretty format the output of cli_cluster_task
    """
    if not isinstance(task_data, list):
        job_state = task_data["state"]
        if job_state == "RUNNING":
            retdata = "Job state: RUNNING\nStage: {}/{}\nStatus: {}".format(
                task_data["current"], task_data["total"], task_data["status"]
            )
        elif job_state == "FAILED":
            retdata = "Job state: FAILED\nStatus: {}".format(task_data["status"])
        elif job_state == "COMPLETED":
            retdata = "Job state: COMPLETED\nStatus: {}".format(task_data["status"])
        else:
            retdata = "Job state: {}\nStatus: {}".format(
                task_data["state"], task_data["status"]
            )
        return retdata

    task_list_output = []

    # Determine optimal column widths
    task_id_length = 3
    task_name_length = 5
    task_type_length = 7
    task_worker_length = 7
    task_arg_name_length = 5
    task_arg_data_length = 10

    tasks = list()
    for task in task_data:
        # task_id column
        _task_id_length = len(str(task["id"])) + 1
        if _task_id_length > task_id_length:
            task_id_length = _task_id_length
        # task_name column
        _task_name_length = len(str(task["name"])) + 1
        if _task_name_length > task_name_length:
            task_name_length = _task_name_length
        # task_worker column
        _task_worker_length = len(str(task["worker"])) + 1
        if _task_worker_length > task_worker_length:
            task_worker_length = _task_worker_length
        # task_type column
        _task_type_length = len(str(task["type"])) + 1
        if _task_type_length > task_type_length:
            task_type_length = _task_type_length

        for arg_name, arg_data in task["kwargs"].items():
            # Skip the "run_on" argument
            if arg_name == "run_on":
                continue

            # task_arg_name column
            _task_arg_name_length = len(str(arg_name)) + 1
            if _task_arg_name_length > task_arg_name_length:
                task_arg_name_length = _task_arg_name_length

    task_header_length = (
        task_id_length + task_name_length + task_type_length + task_worker_length + 3
    )
    max_task_data_length = (
        MAX_CONTENT_WIDTH - task_header_length - task_arg_name_length - 2
    )

    for task in task_data:
        updated_kwargs = list()
        for arg_name, arg_data in task["kwargs"].items():
            # Skip the "run_on" argument
            if arg_name == "run_on":
                continue

            # task_arg_name column
            _task_arg_name_length = len(str(arg_name)) + 1
            if _task_arg_name_length > task_arg_name_length:
                task_arg_name_length = _task_arg_name_length

            if isinstance(arg_data, list):
                for subarg_data in arg_data:
                    if len(subarg_data) > max_task_data_length:
                        subarg_data = (
                            str(subarg_data[: max_task_data_length - 4]) + " ..."
                        )

                    # task_arg_data column
                    _task_arg_data_length = len(str(subarg_data)) + 1
                    if _task_arg_data_length > task_arg_data_length:
                        task_arg_data_length = _task_arg_data_length

                    updated_kwargs.append({"name": arg_name, "data": subarg_data})
            else:
                if len(str(arg_data)) > 24:
                    arg_data = str(arg_data[:24]) + " ..."

                    # task_arg_data column
                    _task_arg_data_length = len(str(arg_data)) + 1
                    if _task_arg_data_length > task_arg_data_length:
                        task_arg_data_length = _task_arg_data_length

                updated_kwargs.append({"name": arg_name, "data": arg_data})

        task["kwargs"] = updated_kwargs
        tasks.append(task)

    # Format the string (header)
    task_list_output.append(
        "{bold}{task_header: <{task_header_length}} {arg_header: <{arg_header_length}}{end_bold}".format(
            bold=ansii["bold"],
            end_bold=ansii["end"],
            task_header_length=task_id_length
            + task_name_length
            + task_type_length
            + task_worker_length
            + 3,
            arg_header_length=task_arg_name_length + task_arg_data_length,
            task_header="Tasks "
            + "".join(
                [
                    "-"
                    for _ in range(
                        6,
                        task_id_length
                        + task_name_length
                        + task_type_length
                        + task_worker_length
                        + 2,
                    )
                ]
            ),
            arg_header="Arguments "
            + "".join(
                [
                    "-"
                    for _ in range(11, task_arg_name_length + task_arg_data_length + 1)
                ]
            ),
        )
    )

    task_list_output.append(
        "{bold}{task_id: <{task_id_length}} {task_name: <{task_name_length}} {task_type: <{task_type_length}} \
{task_worker: <{task_worker_length}} \
{task_arg_name: <{task_arg_name_length}} \
{task_arg_data: <{task_arg_data_length}}{end_bold}".format(
            task_id_length=task_id_length,
            task_name_length=task_name_length,
            task_type_length=task_type_length,
            task_worker_length=task_worker_length,
            task_arg_name_length=task_arg_name_length,
            task_arg_data_length=task_arg_data_length,
            bold=ansii["bold"],
            end_bold=ansii["end"],
            task_id="ID",
            task_name="Name",
            task_type="Status",
            task_worker="Worker",
            task_arg_name="Name",
            task_arg_data="Data",
        )
    )

    # Format the string (elements)
    for task in sorted(tasks, key=lambda i: i.get("type", None)):
        task_list_output.append(
            "{bold}{task_id: <{task_id_length}} {task_name: <{task_name_length}} {task_type: <{task_type_length}} \
{task_worker: <{task_worker_length}} \
{task_arg_name: <{task_arg_name_length}} \
{task_arg_data: <{task_arg_data_length}}{end_bold}".format(
                task_id_length=task_id_length,
                task_name_length=task_name_length,
                task_type_length=task_type_length,
                task_worker_length=task_worker_length,
                task_arg_name_length=task_arg_name_length,
                task_arg_data_length=task_arg_data_length,
                bold="",
                end_bold="",
                task_id=task["id"],
                task_name=task["name"],
                task_type=task["type"],
                task_worker=task["worker"],
                task_arg_name=str(task["kwargs"][0]["name"]),
                task_arg_data=str(task["kwargs"][0]["data"]),
            )
        )
        for arg in task["kwargs"][1:]:
            task_list_output.append(
                "{bold}{task_id: <{task_id_length}} {task_name: <{task_name_length}} {task_type: <{task_type_length}} \
{task_worker: <{task_worker_length}} \
{task_arg_name: <{task_arg_name_length}} \
{task_arg_data: <{task_arg_data_length}}{end_bold}".format(
                    task_id_length=task_id_length,
                    task_name_length=task_name_length,
                    task_type_length=task_type_length,
                    task_worker_length=task_worker_length,
                    task_arg_name_length=task_arg_name_length,
                    task_arg_data_length=task_arg_data_length,
                    bold="",
                    end_bold="",
                    task_id="",
                    task_name="",
                    task_type="",
                    task_worker="",
                    task_arg_name=str(arg["name"]),
                    task_arg_data=str(arg["data"]),
                )
            )

    return "\n".join(task_list_output)


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


def cli_connection_list_format_prometheus_json(CLI_CONFIG, data):
    """
    Format the output of cli_connection_list as Prometheus file service discovery JSON
    """

    from json import dumps

    output = list()
    for connection in data:
        output_obj = {
            "targets": [f"{connection['address']}:{connection['port']}"],
            "labels": {
                "job": "pvc",
                "pvc_cluster_name": f"{connection['name']}: {connection['description']}",
                "pvc_cluster_id": connection["name"],
            },
        }
        output.append(output_obj)

    return dumps(output, indent=2)


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
