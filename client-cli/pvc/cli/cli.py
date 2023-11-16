#!/usr/bin/env python3

# cli.py - PVC Click CLI main library
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

from colorama import Fore
from difflib import unified_diff
from functools import wraps
from json import dump as jdump
from json import dumps as jdumps
from json import loads as jloads
from lxml.etree import fromstring, tostring
from os import environ, makedirs, path
from re import sub, match
from yaml import load as yload
from yaml import SafeLoader as SafeYAMLLoader

from pvc.cli.helpers import *
from pvc.cli.waiters import *
from pvc.cli.parsers import *
from pvc.cli.formatters import *

import pvc.lib.cluster
import pvc.lib.node
import pvc.lib.vm
import pvc.lib.network
import pvc.lib.storage
import pvc.lib.provisioner

import click


###############################################################################
# Context and completion handler, globals
###############################################################################


CONTEXT_SETTINGS = dict(
    help_option_names=["-h", "--help"], max_content_width=MAX_CONTENT_WIDTH
)
IS_COMPLETION = True if environ.get("_PVC_COMPLETE", "") == "complete" else False

CLI_CONFIG = dict()


###############################################################################
# Local helper functions
###############################################################################


def finish(success=True, data=None, formatter=None):
    """
    Output data to the terminal and exit based on code (T/F or integer code)
    """

    if data is not None:
        if formatter is not None and success:
            if formatter.__name__ == "<lambda>":
                # We don't pass CLI_CONFIG into lambdas
                echo(CLI_CONFIG, formatter(data))
            else:
                echo(CLI_CONFIG, formatter(CLI_CONFIG, data))
        else:
            echo(CLI_CONFIG, data)

    # Allow passing raw values if not a bool
    if isinstance(success, bool):
        if success:
            exit(0)
        else:
            exit(1)
    else:
        exit(success)


def version(ctx, param, value):
    """
    Show the version of the CLI client
    """

    if not value or ctx.resilient_parsing:
        return

    from pkg_resources import get_distribution

    version = get_distribution("pvc").version
    echo(CLI_CONFIG, f"Parallel Virtual Cluster CLI client version {version}")
    ctx.exit()


###############################################################################
# Click command decorators
###############################################################################


def connection_req(function):
    """
    General Decorator:
    Wraps a Click command which requires a connection to be set and validates that it is present
    """

    @wraps(function)
    def validate_connection(*args, **kwargs):
        if CLI_CONFIG.get("badcfg", None) and CLI_CONFIG.get("connection"):
            echo(
                CLI_CONFIG,
                f"""Invalid connection "{CLI_CONFIG.get('connection')}" specified; set a valid connection and try again.""",
            )
            exit(1)
        elif CLI_CONFIG.get("badcfg", None):
            echo(
                CLI_CONFIG,
                'No connection specified and no local API configuration found. Use "pvc connection" to add a connection.',
            )
            exit(1)

        if CLI_CONFIG.get("api_scheme") == "https" and not CLI_CONFIG.get("verify_ssl"):
            ssl_verify_msg = " (unverified)"
        else:
            ssl_verify_msg = ""

        echo(
            CLI_CONFIG,
            f'''Using connection "{CLI_CONFIG.get('connection')}" - Host: "{CLI_CONFIG.get('api_host')}"  Scheme: "{CLI_CONFIG.get('api_scheme')}{ssl_verify_msg}"  Prefix: "{CLI_CONFIG.get('api_prefix')}"''',
            stderr=True,
        )
        echo(
            CLI_CONFIG,
            "",
            stderr=True,
        )

        return function(*args, **kwargs)

    return validate_connection


def restart_opt(function):
    """
    Click Option Decorator:
    Wraps a Click command which requires a VM domain restart, to provide options for/against restart or prompt
    """

    @click.option(
        "-r/-R",
        "--restart/--no-restart",
        "restart_flag",
        is_flag=True,
        default=None,
        show_default=False,
        help="Immediately restart VM to apply changes or do not restart VM, or prompt if unspecified.",
    )
    @wraps(function)
    def confirm_action(*args, **kwargs):
        restart_state = kwargs.get("restart_flag", None)
        live_state = kwargs.get("live_flag", False)

        if restart_state is None and not live_state:
            # Neither "--restart" or "--no-restart" was passed, and "--no-live" was passed: prompt for restart or restart if "--unsafe"
            try:
                click.confirm(
                    f"Restart VM {kwargs.get('domain')} to apply changes",
                    prompt_suffix="? ",
                    abort=True,
                )
                kwargs["restart_flag"] = True
                kwargs["confirm_flag"] = True
            except Exception:
                echo(CLI_CONFIG, "Changes will be applied on next VM start/restart.")
                kwargs["restart_flag"] = False
        elif restart_state is True:
            # "--restart" was passed: allow restart without confirming
            kwargs["restart_flag"] = True
        elif restart_state is False:
            # "--no-restart" was passed: skip confirming and skip restart
            kwargs["restart_flag"] = False

        return function(*args, **kwargs)

    return confirm_action


def confirm_opt(message):
    """
    Click Option Decorator with argument:
    Wraps a Click command which requires confirm_flag or unsafe option or asks for confirmation with message
    """

    def confirm_decorator(function):
        @click.option(
            "-y",
            "--yes",
            "confirm_flag",
            is_flag=True,
            default=False,
            help="Pre-confirm any unsafe operations.",
        )
        @wraps(function)
        def confirm_action(*args, **kwargs):
            confirm_action = True
            if "confirm_flag" in kwargs:
                if not kwargs.get("confirm_flag", False):
                    if not CLI_CONFIG.get("unsafe", False):
                        confirm_action = True
                    else:
                        confirm_action = False
                else:
                    confirm_action = False
            else:
                confirm_action = False

            # Handle cases where the confirmation is only for a restart_flag
            # We do not want to confirm if we're not doing the restart
            if (
                "restart_flag" in kwargs
                and confirm_action
                and not kwargs["restart_flag"]
            ):
                confirm_action = False

            if confirm_action:
                try:
                    # Try to interpolate any variables in the message from the kwargs
                    # This is slightly messy but allows for nicer specification of the variables
                    # in the calling {message} string
                    _message = sub(r"{([^{}]*)}", r"\"{kwargs['\1']}\"", message)
                    _message = eval(f"""f'''{_message}'''""")

                    click.confirm(_message, prompt_suffix="? ", abort=True)
                except Exception:
                    print("Aborted.")
                    exit(0)

                click.echo()

            del kwargs["confirm_flag"]

            return function(*args, **kwargs)

        return confirm_action

    return confirm_decorator


def format_opt(formats, default_format="pretty"):
    """
    Click Option Decorator with argument:
    Wraps a Click command that can output in multiple formats; {formats} defines a dictionary of
    formatting functions for the command with keys as valid format types.
    e.g. { "json": lambda d: json.dumps(d), "pretty": format_function_pretty, ... }
    Injects a "format_function" argument into the function for this purpose.
    """

    if default_format not in formats.keys():
        echo(CLI_CONFIG, f"Fatal code error: {default_format} not in {formats.keys()}")
        exit(255)

    def format_decorator(function):
        @click.option(
            "-f",
            "--format",
            "output_format",
            default=default_format,
            show_default=True,
            type=click.Choice(formats.keys()),
            help="Output information in this format.",
        )
        @wraps(function)
        def format_action(*args, **kwargs):
            kwargs["format_function"] = formats[kwargs["output_format"]]

            del kwargs["output_format"]

            return function(*args, **kwargs)

        return format_action

    return format_decorator


# Decorators example
@click.command(name="testing", short_help="Testing")  # Click command
@connection_req  # Require a connection to be set
@click.argument("vm")  # A Click argument
@confirm_opt("Confirm this very dangerous task")  # A "--yes" confirmation option
@restart_opt  # A "--restart" confirmation option (adds 'restart_flag')
@format_opt(  # A "--format" output option (adds 'format_function')
    {
        "pretty": lambda d: d,  # This dictionary is of "type":"callable" entries, where each
        "json": lambda d: jdumps(
            d
        ),  # key is the nice name for the user to specify, and the value
        "json-pretty": lambda d: jdumps(
            d, indent=2
        ),  # is a callable that takes in the provided data to format
    },
    default_format="json-pretty",  # Can also set a default if "pretty" shouldn't be the default
)
# Always in format {arguments}, {options}, {flags}, {format_function}
def testing(vm, restart_flag, format_function):
    echo(CLI_CONFIG, vm)
    echo(CLI_CONFIG, restart_flag)
    echo(CLI_CONFIG, format_function)

    data = {
        "athing": "value",
        "anotherthing": 1234,
        "thelist": ["a", "b", "c"],
    }

    finish(True, data, format_function)


###############################################################################
# Click command definitions
###############################################################################


###############################################################################
# > pvc cluster
###############################################################################
@click.group(
    name="cluster",
    short_help="Manage PVC clusters.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_cluster():
    """
    Manage and view the status of a PVC cluster.
    """
    pass


###############################################################################
# > pvc cluster status
###############################################################################
@click.command(
    name="status",
    short_help="Show cluster status.",
)
@connection_req
@format_opt(
    {
        "pretty": cli_cluster_status_format_pretty,
        "short": cli_cluster_status_format_short,
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_cluster_status(
    format_function,
):
    """
    Show information and health about a PVC cluster.

    \b
    Format options:
        "pretty": Output all details in a nice colourful format.
        "short" Output only details about cluster health in a nice colourful format.
        "json": Output in unformatted JSON.
        "json-pretty": Output in formatted JSON.
    """

    retcode, retdata = pvc.lib.cluster.get_info(CLI_CONFIG)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc cluster init
###############################################################################
@click.command(
    name="init",
    short_help="Initialize a new cluster.",
)
@connection_req
@click.option(
    "-o",
    "--overwrite",
    "overwrite_flag",
    is_flag=True,
    default=False,
    help="Remove and overwrite any existing data (DANGEROUS)",
)
@confirm_opt("Initialize the cluster and delete all data")
def cli_cluster_init(
    overwrite_flag,
):
    """
    Perform initialization of a new PVC cluster.

    If the "-o"/"--overwrite" option is specified, all existing data in the cluster will be deleted
    before new, empty data is written. THIS IS DANGEROUS. YOU WILL LOSE ALL DATA ON THE CLUSTER. Do
    not "--overwrite" to an existing cluster unless you are absolutely sure what you are doing.

    It is not advisable to initialize a running cluster as this can cause undefined behaviour.
    Instead, stop all node daemons first and start the API daemon manually before running this
    command.
    """

    echo(CLI_CONFIG, "Some music while we're Layin' Pipe? https://youtu.be/sw8S_Kv89IU")

    retcode, retmsg = pvc.lib.cluster.initialize(CLI_CONFIG, overwrite_flag)
    finish(retcode, retmsg)


###############################################################################
# > pvc cluster backup
###############################################################################
@click.command(
    name="backup",
    short_help="Create JSON backup of cluster.",
)
@connection_req
@click.option(
    "-f",
    "--file",
    "filename",
    default=None,
    type=click.File(mode="w"),
    help="Write backup data to this file.",
)
def cli_cluster_backup(
    filename,
):
    """
    Create a JSON-format backup of the cluster Zookeeper state database.
    """

    retcode, retdata = pvc.lib.cluster.backup(CLI_CONFIG)
    json_data = jloads(retdata)
    if retcode and filename is not None:
        jdump(json_data, filename)
        finish(retcode, f'''Backup written to file "{filename.name}"''')
    else:
        finish(retcode, json_data)


###############################################################################
# > pvc cluster restore
###############################################################################
@click.command(
    name="restore",
    short_help="Restore JSON backup to cluster.",
)
@connection_req
@click.option(
    "-f",
    "--filename",
    "filename",
    required=True,
    default=None,
    type=click.File(),
    help="Read backup data from this file.",
)
@confirm_opt("Restore backup and overwrite all cluster data")
def cli_cluster_restore(
    filename,
):
    """
    Restore a JSON-format backup to the cluster Zookeeper state database.

    All existing data in the cluster will be deleted before the restored data is written. THIS IS
    DANGEROUS. YOU WILL LOSE ALL (CURRENT) DATA ON THE CLUSTER. Do not restore to an existing
    cluster unless you are absolutely sure what you are doing.

    It is not advisable to restore to a running cluster as this can cause undefined behaviour.
    Instead, stop all node daemons first and start the API daemon manually before running this
    command.
    """


###############################################################################
# > pvc cluster maintenance
###############################################################################
@click.group(
    name="maintenance",
    short_help="Manage PVC cluster maintenance state.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_cluster_maintenance():
    """
    Manage the maintenance mode of a PVC cluster.
    """
    pass


###############################################################################
# > pvc cluster maintenance on
###############################################################################
@click.command(
    name="on",
    short_help="Enable cluster maintenance mode.",
)
@connection_req
def cli_cluster_maintenance_on():
    """
    Enable maintenance mode on a PVC cluster.
    """

    retcode, retdata = pvc.lib.cluster.maintenance_mode(CLI_CONFIG, "true")
    finish(retcode, retdata)


###############################################################################
# > pvc cluster maintenance off
###############################################################################
@click.command(
    name="off",
    short_help="Disable cluster maintenance mode.",
)
@connection_req
def cli_cluster_maintenance_off():
    """
    Disable maintenance mode on a PVC cluster.
    """

    retcode, retdata = pvc.lib.cluster.maintenance_mode(CLI_CONFIG, "false")
    finish(retcode, retdata)


###############################################################################
# > pvc node
###############################################################################
@click.group(
    name="node",
    short_help="Manage PVC nodes.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_node():
    """
    Manage and view the status of nodes in a PVC cluster.
    """
    pass


###############################################################################
# > pvc node primary
###############################################################################
@click.command(
    name="primary",
    short_help="Set node as primary coordinator.",
)
@connection_req
@click.argument("node", default=DEFAULT_NODE_HOSTNAME)
@click.option(
    "-w",
    "--wait",
    "wait_flag",
    default=False,
    show_default=True,
    is_flag=True,
    help="Block waiting for state transition",
)
def cli_node_primary(
    node,
    wait_flag,
):
    """
    Set NODE in primary coordinator state, making it the primary coordinator for the cluster.
    """

    # Handle active provisioner task warnings
    _, tasks_retdata = pvc.lib.provisioner.task_status(CLI_CONFIG, None)
    if len(tasks_retdata) > 0:
        echo(
            CLI_CONFIG,
            f"""\
NOTE: There are currently {len(tasks_retdata)} active or queued provisioner tasks.
      These jobs will continue executing, but their status visibility will be lost until
      the current primary node returns to primary state.
        """,
        )

    retcode, retdata = pvc.lib.node.node_coordinator_state(CLI_CONFIG, node, "primary")
    if not retcode or "already" in retdata:
        finish(retcode, retdata)

    if wait_flag:
        echo(CLI_CONFIG, retdata)
        cli_node_waiter(CLI_CONFIG, node, "coordinator_state", "takeover")
        retdata = f"Set node {node} in primary coordinator state."

    finish(retcode, retdata)


###############################################################################
# > pvc node secondary
###############################################################################
@click.command(
    name="secondary",
    short_help="Set node as secondary coordinator.",
)
@connection_req
@click.argument("node", default=DEFAULT_NODE_HOSTNAME)
@click.option(
    "-w",
    "--wait",
    "wait_flag",
    default=False,
    show_default=True,
    is_flag=True,
    help="Block waiting for state transition",
)
def cli_node_secondary(
    node,
    wait_flag,
):
    """
    Set NODE in secondary coordinator state, making another active node the primary node for the cluster.
    """

    # Handle active provisioner task warnings
    _, tasks_retdata = pvc.lib.provisioner.task_status(CLI_CONFIG, None)
    if len(tasks_retdata) > 0:
        echo(
            CLI_CONFIG,
            f"""\
NOTE: There are currently {len(tasks_retdata)} active or queued provisioner tasks.
      These jobs will continue executing, but their status visibility will be lost until
      the current primary node returns to primary state.
        """,
        )

    retcode, retdata = pvc.lib.node.node_coordinator_state(
        CLI_CONFIG, node, "secondary"
    )
    if not retcode or "already" in retdata:
        finish(retcode, retdata)

    if wait_flag:
        echo(CLI_CONFIG, retdata)
        cli_node_waiter(CLI_CONFIG, node, "coordinator_state", "relinquish")
        retdata = f"Set node {node} in secondary coordinator state."

    finish(retcode, retdata)


###############################################################################
# > pvc node flush
###############################################################################
@click.command(
    name="flush",
    short_help="Take node out of service.",
)
@connection_req
@click.argument("node", default=DEFAULT_NODE_HOSTNAME)
@click.option(
    "-w",
    "--wait",
    "wait_flag",
    default=False,
    show_default=True,
    is_flag=True,
    help="Block waiting for state transition",
)
def cli_node_flush(
    node,
    wait_flag,
):
    """
    Take NODE out of service, migrating all VMs on it to other nodes.
    """

    retcode, retdata = pvc.lib.node.node_domain_state(CLI_CONFIG, node, "flush")
    if not retcode or "already" in retdata:
        finish(retcode, retdata)

    if wait_flag:
        echo(CLI_CONFIG, retdata)
        cli_node_waiter(CLI_CONFIG, node, "domain_state", "flush")
        retdata = f"Removed node {node} from active service."

    finish(retcode, retdata)


###############################################################################
# > pvc node ready
###############################################################################
@click.command(
    name="ready",
    short_help="Restore node to service.",
)
@connection_req
@click.argument("node", default=DEFAULT_NODE_HOSTNAME)
@click.option(
    "-w",
    "--wait",
    "wait_flag",
    default=False,
    show_default=True,
    is_flag=True,
    help="Block waiting for state transition",
)
def cli_node_ready(
    node,
    wait_flag,
):
    """
    Restore NODE to service, returning all previous VMs to it from other nodes.
    """

    retcode, retdata = pvc.lib.node.node_domain_state(CLI_CONFIG, node, "ready")
    if not retcode or "already" in retdata:
        finish(retcode, retdata)

    if wait_flag:
        echo(CLI_CONFIG, retdata)
        cli_node_waiter(CLI_CONFIG, node, "domain_state", "unflush")
        retdata = f"Restored node {node} to active service."

    finish(retcode, retdata)


###############################################################################
# > pvc node log
###############################################################################
@click.command(
    name="log",
    short_help="View node daemon logs.",
)
@connection_req
@click.argument("node", default=DEFAULT_NODE_HOSTNAME)
@click.option(
    "-l",
    "--lines",
    "lines",
    default=None,
    show_default=False,
    help="Display this many log lines from the end of the log buffer.  [default: 1000; with follow: 10]",
)
@click.option(
    "-f",
    "--follow",
    "follow_flag",
    is_flag=True,
    default=False,
    help="Follow the live changes of the log buffer.",
)
def cli_node_log(
    node,
    lines,
    follow_flag,
):
    """
    Show daemon logs of NODE, either in the local $PAGER tool or following the current output.

    If "-f"/"--follow" is used, log output may be delayed by up to 1-2 seconds relative to the
    live system due to API refresh delays. Logs will display in batches with each API refresh.

    With "--follow", the default "--lines" value is 10, otherwise it is 1000 unless "--lines" is
    specified with another value.

    The maximum number of lines is limited only by the systemd journal of the node, though values
    above ~5000 may cause performance problems.
    """

    # Set the default lines value based on the follow option
    if lines is None:
        if follow_flag:
            lines = 10
        else:
            lines = 1000

    if follow_flag:
        # This command blocks following the logs until cancelled
        retcode, retmsg = pvc.lib.node.follow_node_log(CLI_CONFIG, node, lines)
        retmsg = ""
    else:
        retcode, retmsg = pvc.lib.node.view_node_log(CLI_CONFIG, node, lines)
        click.echo_via_pager(retmsg)
        retmsg = ""

    finish(retcode, retmsg)


###############################################################################
# > pvc node info
###############################################################################
@click.command(
    name="info",
    short_help="Show details of node.",
)
@connection_req
@click.argument("node", default=DEFAULT_NODE_HOSTNAME)
@format_opt(
    {
        "pretty": cli_node_info_format_pretty,
        "long": cli_node_info_format_long,
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_node_info(
    node,
    format_function,
):
    """
    Show information about NODE. If a node is not specified, defaults to this host.

    \b
    Format options:
        "pretty": Output basic details in a nice colourful format.
        "long" Output full details including all health plugins in a nice colourful format.
        "json": Output in unformatted JSON.
        "json-pretty": Output in formatted JSON.
    """

    retcode, retdata = pvc.lib.node.node_info(CLI_CONFIG, node)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc node list
###############################################################################
@click.command(
    name="list",
    short_help="List all nodes.",
)
@connection_req
@click.argument("limit", default=None, required=False)
@click.option(
    "-ds",
    "--daemon-state",
    "daemon_state_filter",
    default=None,
    help="Limit list to nodes in the specified daemon state.",
)
@click.option(
    "-cs",
    "--coordinator-state",
    "coordinator_state_filter",
    default=None,
    help="Limit list to nodes in the specified coordinator state.",
)
@click.option(
    "-vs",
    "--domain-state",
    "domain_state_filter",
    default=None,
    help="Limit list to nodes in the specified domain state.",
)
@format_opt(
    {
        "pretty": cli_node_list_format_pretty,
        "raw": lambda d: "\n".join([c["name"] for c in d]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_node_list(
    limit,
    daemon_state_filter,
    coordinator_state_filter,
    domain_state_filter,
    format_function,
):
    """
    List all nodes, optionally only nodes matching regex LIMIT.

    \b
    Format options:
        "pretty": Output all details in a nice tabular list format.
        "raw": Output node names one per line.
        "json": Output in unformatted JSON.
        "json-pretty": Output in formatted JSON.
    """

    retcode, retdata = pvc.lib.node.node_list(
        CLI_CONFIG,
        limit,
        daemon_state_filter,
        coordinator_state_filter,
        domain_state_filter,
    )
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc vm
###############################################################################
@click.group(
    name="vm",
    short_help="Manage PVC VMs.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_vm():
    """
    Manage and view the status of VMs in a PVC cluster.
    """
    pass


###############################################################################
# > pvc vm define
###############################################################################
@click.command(
    name="define", short_help="Define a new virtual machine from a Libvirt XML file."
)
@connection_req
@click.option(
    "-t",
    "--target",
    "target_node",
    help="Home node for this domain; autoselect if unspecified.",
)
@click.option(
    "-l",
    "--limit",
    "node_limit",
    default=None,
    show_default=False,
    help="Comma-separated list of nodes to limit VM operation to; saved with VM.",
)
@click.option(
    "-s",
    "--node-selector",
    "node_selector",
    default="none",
    show_default=True,
    type=click.Choice(["mem", "memprov", "load", "vcpus", "vms", "none"]),
    help='Method to determine optimal target node during autoselect; "none" will use the default for the cluster.',
)
@click.option(
    "-a/-A",
    "--autostart/--no-autostart",
    "node_autostart",
    is_flag=True,
    default=False,
    help="Start VM automatically on next unflush/ready state of home node; unset by daemon once used.",
)
@click.option(
    "-m",
    "--method",
    "migration_method",
    default="none",
    show_default=True,
    type=click.Choice(["none", "live", "shutdown"]),
    help="The preferred migration method of the VM between nodes; saved with VM.",
)
@click.option(
    "-g",
    "--tag",
    "user_tags",
    default=[],
    multiple=True,
    help="User tag for the VM; can be specified multiple times, once per tag.",
)
@click.option(
    "-G",
    "--protected-tag",
    "protected_tags",
    default=[],
    multiple=True,
    help="Protected user tag for the VM; can be specified multiple times, once per tag.",
)
@click.argument("vmconfig", type=click.File())
def cli_vm_define(
    vmconfig,
    target_node,
    node_limit,
    node_selector,
    node_autostart,
    migration_method,
    user_tags,
    protected_tags,
):
    """
    Define a new virtual machine from Libvirt XML configuration file VMCONFIG.

    The target node selector ("--node-selector"/"-s") can be "none" to use the cluster default, or one of the following values:
      * "mem": choose the node with the most (real) free memory
      * "memprov": choose the node with the least provisioned VM memory
      * "vcpus": choose the node with the least allocated VM vCPUs
      * "load": choose the node with the lowest current load average
      * "vms": choose the node with the least number of provisioned VMs

    For most clusters, "mem" should be sufficient, but others may be used based on the cluster workload and available resources. The following caveats should be considered:
      * "mem" looks at the free memory of the node in general, ignoring the amount provisioned to VMs; if any VM's internal memory usage changes, this value would be affected.
      * "memprov" looks at the provisioned memory, not the allocated memory; thus, stopped or disabled VMs are counted towards a node's memory for this selector, even though their memory is not actively in use.
      * "load" looks at the system load of the node in general, ignoring load in any particular VMs; if any VM's CPU usage changes, this value would be affected. This might be preferable on clusters with some very CPU intensive VMs.
    """

    # Open the XML file
    vmconfig_data = vmconfig.read()
    vmconfig.close()

    # Verify our XML is sensible
    try:
        xml_data = fromstring(vmconfig_data)
        new_cfg = tostring(xml_data, pretty_print=True).decode("utf8")
    except Exception:
        finish(False, "Error: XML is malformed or invalid")

    retcode, retmsg = pvc.lib.vm.vm_define(
        CLI_CONFIG,
        new_cfg,
        target_node,
        node_limit,
        node_selector,
        node_autostart,
        migration_method,
        user_tags,
        protected_tags,
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc vm meta
###############################################################################
@click.command(name="meta", short_help="Modify PVC metadata of an existing VM.")
@connection_req
@click.option(
    "-l",
    "--limit",
    "node_limit",
    default=None,
    show_default=False,
    help="Comma-separated list of nodes to limit VM operation to; set to an empty string to remove.",
)
@click.option(
    "-s",
    "--node-selector",
    "node_selector",
    default=None,
    show_default=False,
    type=click.Choice(["mem", "memprov", "load", "vcpus", "vms", "none"]),
    help='Method to determine optimal target node during autoselect; "none" will use the default for the cluster.',
)
@click.option(
    "-a/-A",
    "--autostart/--no-autostart",
    "node_autostart",
    is_flag=True,
    default=None,
    help="Start VM automatically on next unflush/ready state of home node; unset by daemon once used.",
)
@click.option(
    "-m",
    "--method",
    "migration_method",
    default="none",
    show_default=True,
    type=click.Choice(["none", "live", "shutdown"]),
    help="The preferred migration method of the VM between nodes.",
)
@click.option(
    "-p",
    "--profile",
    "provisioner_profile",
    default=None,
    show_default=False,
    help="PVC provisioner profile name for VM.",
)
@click.argument("domain")
def cli_vm_meta(
    domain,
    node_limit,
    node_selector,
    node_autostart,
    migration_method,
    provisioner_profile,
):
    """
    Modify the PVC metadata of existing virtual machine DOMAIN. At least one option to update must be specified. DOMAIN may be a UUID or name.

    For details on the "--node-selector"/"-s" values, please see help for the command "pvc vm define".
    """

    if (
        node_limit is None
        and node_selector is None
        and node_autostart is None
        and migration_method is None
        and provisioner_profile is None
    ):
        finish(False, "At least one metadata option must be specified to update.")

    retcode, retmsg = pvc.lib.vm.vm_metadata(
        CLI_CONFIG,
        domain,
        node_limit,
        node_selector,
        node_autostart,
        migration_method,
        provisioner_profile,
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc vm modify
###############################################################################
@click.command(name="modify", short_help="Modify an existing VM configuration.")
@connection_req
@click.option(
    "-e",
    "--editor",
    "editor",
    is_flag=True,
    help="Use local editor to modify existing config.",
)
@click.option(
    "-r",
    "--restart",
    "restart",
    is_flag=True,
    help="Immediately restart VM to apply new config.",
)
@click.option(
    "-d",
    "--confirm-diff",
    "confirm_diff_flag",
    is_flag=True,
    default=False,
    help="Confirm the diff.",
)
@click.option(
    "-c",
    "--confirm-restart",
    "confirm_restart_flag",
    is_flag=True,
    default=False,
    help="Confirm the restart.",
)
@click.option(
    "-y",
    "--yes",
    "confirm_all_flag",
    is_flag=True,
    default=False,
    help="Confirm the diff and the restart.",
)
@click.argument("domain")
@click.argument("cfgfile", type=click.File(), default=None, required=False)
def cli_vm_modify(
    domain,
    cfgfile,
    editor,
    restart,
    confirm_diff_flag,
    confirm_restart_flag,
    confirm_all_flag,
):
    """
    Modify existing virtual machine DOMAIN, either in-editor or with replacement CONFIG. DOMAIN may be a UUID or name.
    """

    if editor is False and cfgfile is None:
        finish(
            False,
            'Either an XML config file or the "--editor" option must be specified.',
        )

    retcode, vm_information = pvc.lib.vm.vm_info(CLI_CONFIG, domain)
    if not retcode or not vm_information.get("name", None):
        finish(False, 'ERROR: Could not find VM "{}"!'.format(domain))

    dom_name = vm_information.get("name")

    # Grab the current config
    current_vm_cfg_raw = vm_information.get("xml")
    xml_data = fromstring(current_vm_cfg_raw)
    current_vm_cfgfile = tostring(xml_data, pretty_print=True).decode("utf8").strip()

    if editor is True:
        new_vm_cfgfile = click.edit(
            text=current_vm_cfgfile, require_save=True, extension=".xml"
        )
        if new_vm_cfgfile is None:
            echo(CLI_CONFIG, "Aborting with no modifications.")
            exit(0)
        else:
            new_vm_cfgfile = new_vm_cfgfile.strip()

    # We're operating in replace mode
    else:
        # Open the XML file
        new_vm_cfgfile = cfgfile.read()
        cfgfile.close()

        echo(
            CLI_CONFIG,
            'Replacing configuration of VM "{}" with file "{}".'.format(
                dom_name, cfgfile.name
            ),
        )

    diff = list(
        unified_diff(
            current_vm_cfgfile.split("\n"),
            new_vm_cfgfile.split("\n"),
            fromfile="current",
            tofile="modified",
            fromfiledate="",
            tofiledate="",
            n=3,
            lineterm="",
        )
    )
    if len(diff) < 1:
        echo(CLI_CONFIG, "Aborting with no modifications.")
        exit(0)

    # Show a diff and confirm
    echo(CLI_CONFIG, "Pending modifications:")
    echo(CLI_CONFIG, "")
    for line in diff:
        if match(r"^\+", line) is not None:
            echo(CLI_CONFIG, Fore.GREEN + line + Fore.RESET)
        elif match(r"^\-", line) is not None:
            echo(CLI_CONFIG, Fore.RED + line + Fore.RESET)
        elif match(r"^\^", line) is not None:
            echo(CLI_CONFIG, Fore.BLUE + line + Fore.RESET)
        else:
            echo(CLI_CONFIG, line)
    echo(CLI_CONFIG, "")

    # Verify our XML is sensible
    try:
        xml_data = fromstring(new_vm_cfgfile)
        new_cfg = tostring(xml_data, pretty_print=True).decode("utf8")
    except Exception as e:
        finish(False, "Error: XML is malformed or invalid: {}".format(e))

    if not confirm_diff_flag and not confirm_all_flag and not CLI_CONFIG["unsafe"]:
        click.confirm("Write modifications to cluster?", abort=True)

    if (
        restart
        and not confirm_restart_flag
        and not confirm_all_flag
        and not CLI_CONFIG["unsafe"]
    ):
        try:
            click.confirm(
                "Restart VM {}".format(domain), prompt_suffix="? ", abort=True
            )
        except Exception:
            restart = False

    retcode, retmsg = pvc.lib.vm.vm_modify(CLI_CONFIG, domain, new_cfg, restart)
    if retcode and not restart:
        retmsg = retmsg + " Changes will be applied on next VM start/restart."
    finish(retcode, retmsg)


###############################################################################
# > pvc vm rename
###############################################################################
@click.command(name="rename", short_help="Rename a virtual machine.")
@connection_req
@click.argument("domain")
@click.argument("new_name")
@confirm_opt("Rename virtual machine {domain} to {new_name}")
def cli_vm_rename(domain, new_name):
    """
    Rename virtual machine DOMAIN, and all its connected disk volumes, to NEW_NAME. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc.lib.vm.vm_rename(CLI_CONFIG, domain, new_name)
    finish(retcode, retmsg)


###############################################################################
# > pvc vm undefine
###############################################################################
@click.command(name="undefine", short_help="Undefine a virtual machine.")
@connection_req
@click.argument("domain")
@confirm_opt("Remove definition of virtual machine {domain}")
def cli_vm_undefine(domain):
    """
    Stop virtual machine DOMAIN and remove it database, preserving disks. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc.lib.vm.vm_remove(CLI_CONFIG, domain, delete_disks=False)
    finish(retcode, retmsg)


###############################################################################
# > pvc vm remove
###############################################################################
@click.command(name="remove", short_help="Remove a virtual machine.")
@connection_req
@click.argument("domain")
@confirm_opt("Remove virtual machine {domain} and all disks")
def cli_vm_remove(domain):
    """
    Stop virtual machine DOMAIN and remove it, along with all disks,. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc.lib.vm.vm_remove(CLI_CONFIG, domain, delete_disks=True)
    finish(retcode, retmsg)


###############################################################################
# > pvc vm start
###############################################################################
@click.command(name="start", short_help="Start up a defined virtual machine.")
@connection_req
@click.argument("domain")
def cli_vm_start(domain):
    """
    Start virtual machine DOMAIN on its configured node. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc.lib.vm.vm_state(CLI_CONFIG, domain, "start")
    finish(retcode, retmsg)


###############################################################################
# > pvc vm restart
###############################################################################
@click.command(name="restart", short_help="Restart a running virtual machine.")
@connection_req
@click.argument("domain")
@click.option(
    "-w",
    "--wait",
    "wait",
    is_flag=True,
    default=False,
    help="Wait for restart to complete before returning.",
)
@confirm_opt("Restart virtual machine {domain}")
def cli_vm_restart(domain, wait):
    """
    Restart running virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc.lib.vm.vm_state(CLI_CONFIG, domain, "restart", wait=wait)
    finish(retcode, retmsg)


###############################################################################
# > pvc vm shutdown
###############################################################################
@click.command(
    name="shutdown", short_help="Gracefully shut down a running virtual machine."
)
@connection_req
@click.argument("domain")
@click.option(
    "-w",
    "--wait",
    "wait",
    is_flag=True,
    default=False,
    help="Wait for shutdown to complete before returning.",
)
@confirm_opt("Shut down virtual machine {domain}")
def cli_vm_shutdown(domain, wait):
    """
    Gracefully shut down virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc.lib.vm.vm_state(CLI_CONFIG, domain, "shutdown", wait=wait)
    finish(retcode, retmsg)


###############################################################################
# > pvc vm stop
###############################################################################
@click.command(name="stop", short_help="Forcibly halt a running virtual machine.")
@connection_req
@click.argument("domain")
@confirm_opt("Forcibly stop virtual machine {domain}")
def cli_vm_stop(domain):
    """
    Forcibly halt (destroy) running virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc.lib.vm.vm_state(CLI_CONFIG, domain, "stop")
    finish(retcode, retmsg)


###############################################################################
# > pvc vm disable
###############################################################################
@click.command(name="disable", short_help="Mark a virtual machine as disabled.")
@connection_req
@click.argument("domain")
@click.option(
    "--force",
    "force_flag",
    is_flag=True,
    default=False,
    help="Forcibly stop the VM instead of waiting for shutdown.",
)
@confirm_opt("Shut down and disable virtual machine {domain}")
def cli_vm_disable(domain, force_flag):
    """
    Shut down virtual machine DOMAIN and mark it as disabled. DOMAIN may be a UUID or name.

    Disabled VMs will not be counted towards a degraded cluster health status, unlike stopped VMs. Use this option for a VM that will remain off for an extended period.
    """

    retcode, retmsg = pvc.lib.vm.vm_state(
        CLI_CONFIG, domain, "disable", force=force_flag
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc vm move
###############################################################################
@click.command(
    name="move", short_help="Permanently move a virtual machine to another node."
)
@connection_req
@click.argument("domain")
@click.option(
    "-t",
    "--target",
    "target_node",
    default=None,
    help="Target node to migrate to; autodetect if unspecified.",
)
@click.option(
    "-w",
    "--wait",
    "wait",
    is_flag=True,
    default=False,
    help="Wait for migration to complete before returning.",
)
@click.option(
    "--force-live",
    "force_live",
    is_flag=True,
    default=False,
    help="Do not fall back to shutdown-based migration if live migration fails.",
)
def cli_vm_move(domain, target_node, wait, force_live):
    """
    Permanently move virtual machine DOMAIN, via live migration if running and possible, to another node. DOMAIN may be a UUID or name.
    """

    retcode, retmsg = pvc.lib.vm.vm_node(
        CLI_CONFIG,
        domain,
        target_node,
        "move",
        force=False,
        wait=wait,
        force_live=force_live,
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc vm migrate
###############################################################################
@click.command(
    name="migrate", short_help="Temporarily migrate a virtual machine to another node."
)
@connection_req
@click.argument("domain")
@click.option(
    "-t",
    "--target",
    "target_node",
    default=None,
    help="Target node to migrate to; autodetect if unspecified.",
)
@click.option(
    "-f",
    "--force",
    "force_migrate",
    is_flag=True,
    default=False,
    help="Force migrate an already migrated VM; does not replace an existing previous node value.",
)
@click.option(
    "-w",
    "--wait",
    "wait",
    is_flag=True,
    default=False,
    help="Wait for migration to complete before returning.",
)
@click.option(
    "--force-live",
    "force_live",
    is_flag=True,
    default=False,
    help="Do not fall back to shutdown-based migration if live migration fails.",
)
def cli_vm_migrate(domain, target_node, force_migrate, wait, force_live):
    """
    Temporarily migrate running virtual machine DOMAIN, via live migration if possible, to another node. DOMAIN may be a UUID or name. If DOMAIN is not running, it will be started on the target node.
    """

    retcode, retmsg = pvc.lib.vm.vm_node(
        CLI_CONFIG,
        domain,
        target_node,
        "migrate",
        force=force_migrate,
        wait=wait,
        force_live=force_live,
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc vm unmigrate
###############################################################################
@click.command(
    name="unmigrate",
    short_help="Restore a migrated virtual machine to its original node.",
)
@connection_req
@click.argument("domain")
@click.option(
    "-w",
    "--wait",
    "wait",
    is_flag=True,
    default=False,
    help="Wait for migration to complete before returning.",
)
@click.option(
    "--force-live",
    "force_live",
    is_flag=True,
    default=False,
    help="Do not fall back to shutdown-based migration if live migration fails.",
)
def cli_vm_unmigrate(domain, wait, force_live):
    """
    Restore previously migrated virtual machine DOMAIN, via live migration if possible, to its original node. DOMAIN may be a UUID or name. If DOMAIN is not running, it will be started on the target node.
    """

    retcode, retmsg = pvc.lib.vm.vm_node(
        CLI_CONFIG,
        domain,
        None,
        "unmigrate",
        force=False,
        wait=wait,
        force_live=force_live,
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc vm flush-locks
###############################################################################
@click.command(
    name="flush-locks", short_help="Flush stale RBD locks for a virtual machine."
)
@connection_req
@click.argument("domain")
@click.option(
    "--wait/--no-wait",
    "wait_flag",
    is_flag=True,
    default=True,
    show_default=True,
    help="Wait or don't wait for task to complete, showing progress",
)
def cli_vm_flush_locks(domain, wait_flag):
    """
    Flush stale RBD locks for virtual machine DOMAIN. DOMAIN may be a UUID or name. DOMAIN must be in the stop, disable, or fail state before flushing locks.

    NOTE: This is a task-based command. The "--wait" flag (default) will block and show progress. Specifying the "--no-wait" flag will return immediately with a job ID instead, which can be queried externally later.
    """

    retcode, retmsg = pvc.lib.vm.vm_locks(CLI_CONFIG, domain, wait_flag)

    if retcode and wait_flag:
        retmsg = wait_for_celery_task(CLI_CONFIG, retmsg)
    finish(retcode, retmsg)


###############################################################################
# > pvc vm backup
###############################################################################
@click.group(
    name="backup",
    short_help="Manage backups for PVC VMs.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_vm_backup():
    """
    Manage backups of VMs in a PVC cluster.
    """
    pass


###############################################################################
# > pvc vm backup create
###############################################################################
@click.command(name="create", short_help="Create a backup of a virtual machine.")
@connection_req
@click.argument("domain")
@click.argument("backup_path")
@click.option(
    "-i",
    "--incremental",
    "incremental_parent",
    default=None,
    help="Perform an incremental volume backup from this parent backup datestring.",
)
@click.option(
    "-r",
    "--retain-snapshot",
    "retain_snapshot",
    is_flag=True,
    default=False,
    help="Retain volume snapshot for future incremental use (full only).",
)
def cli_vm_backup_create(domain, backup_path, incremental_parent, retain_snapshot):
    """
    Create a backup of virtual machine DOMAIN to BACKUP_PATH on the cluster primary coordinator. DOMAIN may be a UUID or name.

    BACKUP_PATH must be a valid absolute directory path on the cluster "primary" coordinator (see "pvc node list") allowing writes from the API daemon (normally running as "root"). The BACKUP_PATH should be a large storage volume, ideally a remotely mounted filesystem (e.g. NFS, SSHFS, etc.) or non-Ceph-backed disk; PVC does not handle this path, that is up to the administrator to configure and manage.

    The backup will export the VM configuration, metainfo, and a point-in-time snapshot of all attached RBD volumes, using a datestring formatted backup name (i.e. YYYYMMDDHHMMSS).

    The virtual machine DOMAIN may be running, and due to snapshots the backup should be crash-consistent, but will be in an unclean state and this must be considered when restoring from backups.

    Incremental snapshots are possible by specifying the "-i"/"--incremental" option along with a source backup datestring. The snapshots from that source backup must have been retained using the "-r"/"--retain-snapshots" option. Retaining snapshots of incremental backups is not supported as incremental backups cannot be chained.

    Full backup volume images are sparse-allocated, however it is recommended for safety to consider their maximum allocated size when allocated space for the BACKUP_PATH. Incremental volume images are generally small but are dependent entirely on the rate of data change in each volume.
    """

    echo(
        CLI_CONFIG,
        f"Backing up VM '{domain}'... ",
        newline=False,
    )
    retcode, retmsg = pvc.lib.vm.vm_backup(
        CLI_CONFIG, domain, backup_path, incremental_parent, retain_snapshot
    )
    if retcode:
        echo(CLI_CONFIG, "done.")
    else:
        echo(CLI_CONFIG, "failed.")
    finish(retcode, retmsg)


###############################################################################
# > pvc vm backup restore
###############################################################################
@click.command(name="restore", short_help="Restore a backup of a virtual machine.")
@connection_req
@click.argument("domain")
@click.argument("backup_datestring")
@click.argument("backup_path")
@click.option(
    "-r/-R",
    "--retain-snapshot/--remove-snapshot",
    "retain_snapshot",
    is_flag=True,
    default=True,
    help="Retain or remove restored (parent, if incremental) snapshot.",
)
def cli_vm_backup_restore(domain, backup_datestring, backup_path, retain_snapshot):
    """
    Restore the backup BACKUP_DATESTRING of virtual machine DOMAIN stored in BACKUP_PATH on the cluster primary coordinator. DOMAIN may be a UUID or name.

    BACKUP_PATH must be a valid absolute directory path on the cluster "primary" coordinator (see "pvc node list") allowing reads from the API daemon (normally running as "root"). The BACKUP_PATH should be a large storage volume, ideally a remotely mounted filesystem (e.g. NFS, SSHFS, etc.) or non-Ceph-backed disk; PVC does not handle this path, that is up to the administrator to configure and manage.

    The restore will import the VM configuration, metainfo, and the point-in-time snapshot of all attached RBD volumes. Incremental backups will be automatically handled.

    A VM named DOMAIN or with the same UUID must not exist; if a VM with the same name or UUID already exists, it must be removed, or renamed and then undefined (to preserve volumes), before restoring.

    If the "-r"/"--retain-snapshot" option is specified (the default), for incremental restores, only the parent snapshot is kept; for full restores, the restored snapshot is kept. If the "-R"/"--remove-snapshot" option is specified, the imported snapshot is removed.

    WARNING: The "-R"/"--remove-snapshot" option will invalidate any existing incremental backups based on the same incremental parent for the restored VM.
    """

    echo(
        CLI_CONFIG,
        f"Restoring backup {backup_datestring} of VM '{domain}'... ",
        newline=False,
    )
    retcode, retmsg = pvc.lib.vm.vm_restore(
        CLI_CONFIG, domain, backup_path, backup_datestring, retain_snapshot
    )
    if retcode:
        echo(CLI_CONFIG, "done.")
    else:
        echo(CLI_CONFIG, "failed.")
    finish(retcode, retmsg)


###############################################################################
# > pvc vm backup remove
###############################################################################
@click.command(name="remove", short_help="Remove a backup of a virtual machine.")
@connection_req
@click.argument("domain")
@click.argument("backup_datestring")
@click.argument("backup_path")
def cli_vm_backup_remove(domain, backup_datestring, backup_path):
    """
    Remove the backup BACKUP_DATESTRING, including snapshots, of virtual machine DOMAIN stored in BACKUP_PATH on the cluster primary coordinator. DOMAIN may be a UUID or name.

    WARNING: Removing an incremental parent will invalidate any existing incremental backups based on that backup.
    """

    echo(
        CLI_CONFIG,
        f"Removing backup {backup_datestring} of VM '{domain}'... ",
        newline=False,
    )
    retcode, retmsg = pvc.lib.vm.vm_remove_backup(
        CLI_CONFIG, domain, backup_path, backup_datestring
    )
    if retcode:
        echo(CLI_CONFIG, "done.")
    else:
        echo(CLI_CONFIG, "failed.")
    finish(retcode, retmsg)


###############################################################################
# > pvc vm autobackup
###############################################################################
@click.command(
    name="autobackup", short_help="Perform automatic virtual machine backups."
)
@connection_req
@click.option(
    "-f",
    "--configuration",
    "autobackup_cfgfile",
    envvar="PVC_AUTOBACKUP_CFGFILE",
    default=DEFAULT_AUTOBACKUP_FILENAME,
    show_default=True,
    help="Override default config file location.",
)
@click.option(
    "--force-full",
    "force_full_flag",
    default=False,
    is_flag=True,
    help="Force all backups to be full backups this run.",
)
@click.option(
    "--cron",
    "cron_flag",
    default=False,
    is_flag=True,
    help="Cron mode; don't error exit if this isn't the primary coordinator.",
)
def cli_vm_autobackup(autobackup_cfgfile, force_full_flag, cron_flag):
    """
    Perform automated backups of VMs, with integrated cleanup and full/incremental scheduling.

    This command enables automatic backup of PVC VMs at the block level, leveraging the various "pvc vm backup"
    functions with an internal rentention and cleanup system as well as determination of full vs. incremental
    backups at different intervals. VMs are selected based on configured VM tags. The destination storage
    may either be local, or provided by a remote filesystem which is automatically mounted and unmounted during
    the backup run via a set of configured commands before and after the backup run.

    NOTE: This command performs its tasks in a local context. It MUST be run from the cluster's active primary
    coordinator using the "local" connection only; if either is not correct, the command will error.

    NOTE: This command should be run as the same user as the API daemon, usually "root" with "sudo -E" or in
    a cronjob as "root", to ensure permissions are correct on the backup files. Failure to do so will still take
    the backup, but the state update write will likely fail and the backup will become untracked. The command
    will prompt for confirmation if it is found not to be running as "root" and this cannot be bypassed.

    This command should be run from cron or a timer at a regular interval (e.g. daily, hourly, etc.) which defines
    how often backups are taken. Backup format (full/incremental) and retention is based only on the number of
    recorded backups, not on the time interval between them. Backups taken manually outside of the "autobackup"
    command are not counted towards the format or retention of autobackups.

    The PVC_AUTOBACKUP_CFGFILE envvar or "-f"/"--configuration" option can be used to override the default
    configuration file path if required by a particular run. For full details of the possible options, please
    see the example configuration file at "/usr/share/pvc/autobackup.sample.yaml".

    The "--force-full" option can be used to force all configured VMs to perform a "full" level backup this run,
    which can help synchronize the backups of existing VMs with new ones.
    """

    # All work here is done in the helper function for portability; we don't even use "finish"
    vm_autobackup(CLI_CONFIG, autobackup_cfgfile, force_full_flag, cron_flag)


###############################################################################
# > pvc vm tag
###############################################################################
@click.group(
    name="tag",
    short_help="Manage tags for PVC VMs.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_vm_tag():
    """
    Manage and view the tags of VMs in a PVC cluster.
    """
    pass


###############################################################################
# > pvc vm tag get
###############################################################################
@click.command(name="get", short_help="Get the current tags of a virtual machine.")
@connection_req
@click.argument("domain")
@format_opt(
    {
        "pretty": cli_vm_tag_get_format_pretty,
        "raw": lambda d: "\n".join([t["name"] for t in d["tags"]]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_vm_tag_get(domain, format_function):
    """
    Get the current tags of the virtual machine DOMAIN.
    """

    retcode, retdata = pvc.lib.vm.vm_tags_get(CLI_CONFIG, domain)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc vm tag add
###############################################################################
@click.command(name="add", short_help="Add new tags to a virtual machine.")
@connection_req
@click.argument("domain")
@click.argument("tag")
@click.option(
    "-p",
    "--protected",
    "protected",
    is_flag=True,
    required=False,
    default=False,
    help="Set this tag as protected; protected tags cannot be removed.",
)
def cli_vm_tag_add(domain, tag, protected):
    """
    Add TAG to the virtual machine DOMAIN.
    """

    retcode, retmsg = pvc.lib.vm.vm_tag_set(CLI_CONFIG, domain, "add", tag, protected)
    finish(retcode, retmsg)


###############################################################################
# > pvc vm tag remove
###############################################################################
@click.command(name="remove", short_help="Remove tags from a virtual machine.")
@connection_req
@click.argument("domain")
@click.argument("tag")
def cli_vm_tag_remove(domain, tag):
    """
    Remove TAG from the virtual machine DOMAIN.
    """

    retcode, retmsg = pvc.lib.vm.vm_tag_set(CLI_CONFIG, domain, "remove", tag)
    finish(retcode, retmsg)


###############################################################################
# > pvc vm vcpu
###############################################################################
@click.group(
    name="vcpu",
    short_help="Manage vCPUs for PVC VMs.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_vm_vcpu():
    """
    Manage and view the vCPUs of VMs in a PVC cluster.
    """
    pass


###############################################################################
# > pvc vm vcpu get
###############################################################################
@click.command(
    name="get", short_help="Get the current vCPU count of a virtual machine."
)
@connection_req
@click.argument("domain")
@format_opt(
    {
        "pretty": cli_vm_vcpu_get_format_pretty,
        "raw": lambda d: d["vcpus"],
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_vm_vcpu_get(domain, format_function):
    """
    Get the current vCPU count of the virtual machine DOMAIN.
    """

    retcode, retmsg = pvc.lib.vm.vm_vcpus_get(CLI_CONFIG, domain)
    finish(retcode, retmsg, format_function)


###############################################################################
# > pvc vm vcpu set TODO:fix return message to show what happened
###############################################################################
@click.command(name="set", short_help="Set the vCPU count of a virtual machine.")
@connection_req
@click.argument("domain")
@click.argument("vcpus")
@click.option(
    "-t",
    "--topology",
    "topology",
    default=None,
    help="Use an alternative topology for the vCPUs in the CSV form <sockets>,<cores>,<threads>. SxCxT must equal VCPUS.",
)
@restart_opt
@confirm_opt("Restart virtual machine {domain}")
def cli_vm_vcpu_set(domain, vcpus, topology, restart_flag):
    """
    Set the vCPU count of the virtual machine DOMAIN to VCPUS.

    By default, the topology of the vCPus is 1 socket, VCPUS cores per socket, 1 thread per core.
    """
    if topology is not None:
        try:
            sockets, cores, threads = topology.split(",")
            if sockets * cores * threads != vcpus:
                raise
        except Exception:
            cleanup(False, "The specified topology is not valid.")
        topology = (sockets, cores, threads)
    else:
        topology = (1, vcpus, 1)

    retcode, retmsg = pvc.lib.vm.vm_vcpus_set(
        CLI_CONFIG, domain, vcpus, topology, restart_flag
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc vm memory
###############################################################################
@click.group(
    name="memory",
    short_help="Manage memory for PVC VMs.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_vm_memory():
    """
    Manage and view the memory of VMs in a PVC cluster.
    """
    pass


###############################################################################
# > pvc vm memory get
###############################################################################
@click.command(
    name="get", short_help="Get the current provisioned memory of a virtual machine."
)
@connection_req
@click.argument("domain")
@format_opt(
    {
        "pretty": cli_vm_memory_get_format_pretty,
        "raw": lambda d: d["memory"],
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_vm_memory_get(domain, format_function):
    """
    Get the current provisioned memory of the virtual machine DOMAIN.
    """

    retcode, retmsg = pvc.lib.vm.vm_memory_get(CLI_CONFIG, domain)
    finish(retcode, retmsg, format_function)


###############################################################################
# > pvc vm memory set TODO:fix return message to show what happened
###############################################################################
@click.command(
    name="set", short_help="Set the provisioned memory of a virtual machine."
)
@connection_req
@click.argument("domain")
@click.argument("memory")
@restart_opt
@confirm_opt("Restart virtual machine {domain}")
def cli_vm_memory_set(domain, memory, restart_flag):
    """
    Set the provisioned memory of the virtual machine DOMAIN to MEMORY; MEMORY must be an integer in MB.
    """

    retcode, retmsg = pvc.lib.vm.vm_memory_set(CLI_CONFIG, domain, memory, restart_flag)
    finish(retcode, retmsg)


###############################################################################
# > pvc vm network
###############################################################################
@click.group(
    name="network",
    short_help="Manage networks for PVC VMs.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_vm_network():
    """
    Manage and view the networks of VMs in a PVC cluster.
    """
    pass


###############################################################################
# > pvc vm network get
###############################################################################
@click.command(name="get", short_help="Get the networks of a virtual machine.")
@connection_req
@click.argument("domain")
@format_opt(
    {
        "pretty": cli_vm_network_get_format_pretty,
        "raw": lambda d: ",".join([t["network"] for t in d["networks"]]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_vm_network_get(domain, format_function):
    """
    Get the networks of the virtual machine DOMAIN.
    """

    retcode, retdata = pvc.lib.vm.vm_networks_get(CLI_CONFIG, domain)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc vm network add
###############################################################################
@click.command(name="add", short_help="Add network to a virtual machine.")
@connection_req
@click.argument("domain")
@click.argument("net")
@click.option(
    "-a",
    "--macaddr",
    "macaddr",
    default=None,
    help="Use this MAC address instead of random generation; must be a valid MAC address in colon-delimited format.",
)
@click.option(
    "-m",
    "--model",
    "model",
    default="virtio",
    show_default=True,
    help='The model for the interface; must be a valid libvirt model. Not used for "netdev" SR-IOV NETs.',
)
@click.option(
    "-s",
    "--sriov",
    "sriov_flag",
    is_flag=True,
    default=False,
    help="Identify that NET is an SR-IOV device name and not a VNI. Required for adding SR-IOV NETs.",
)
@click.option(
    "-d",
    "--sriov-mode",
    "sriov_mode",
    default="macvtap",
    show_default=True,
    type=click.Choice(["hostdev", "macvtap"]),
    help="For SR-IOV NETs, the SR-IOV network device mode.",
)
@click.option(
    "-l/-L",
    "--live/--no-live",
    "live_flag",
    is_flag=True,
    default=True,
    help="Immediately live-attach device to VM [default] or disable this behaviour.",
)
@restart_opt
@confirm_opt("Restart virtual machine {domain}")
def cli_vm_network_add(
    domain,
    net,
    macaddr,
    model,
    sriov_flag,
    sriov_mode,
    live_flag,
    restart_flag,
):
    """
    Add the network NET to the virtual machine DOMAIN. Networks are always addded to the end of the current list of networks in the virtual machine.

    NET may be a PVC network VNI, which is added as a bridged device, or a SR-IOV VF device connected in the given mode.

    NOTE: Adding a SR-IOV network device in the "hostdev" mode has the following caveats:

      1. The VM will not be able to be live migrated; it must be shut down to migrate between nodes. The VM metadata will be updated to force this.

      2. If an identical SR-IOV VF device is not present on the target node, post-migration startup will fail. It may be prudent to use a node limit here.

    """
    if restart_flag and live_flag:
        live_flag = False

    retcode, retmsg = pvc.lib.vm.vm_networks_add(
        CLI_CONFIG,
        domain,
        net,
        macaddr,
        model,
        sriov_flag,
        sriov_mode,
        live_flag,
        restart_flag,
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc vm network remove
###############################################################################
@click.command(name="remove", short_help="Remove network from a virtual machine.")
@connection_req
@click.argument("domain")
@click.argument("net", required=False, default=None)
@click.option(
    "-m",
    "--mac-address",
    "macaddr",
    default=None,
    help="Remove an interface with this MAC address; required if NET is unspecified.",
)
@click.option(
    "-s",
    "--sriov",
    "sriov_flag",
    is_flag=True,
    default=False,
    help="Identify that NET is an SR-IOV device name and not a VNI. Required for removing SR-IOV NETs.",
)
@click.option(
    "-l/-L",
    "--live/--no-live",
    "live_flag",
    is_flag=True,
    default=True,
    help="Immediately live-detach device to VM [default] or disable this behaviour.",
)
@restart_opt
@confirm_opt("Restart virtual machine {domain}")
def cli_vm_network_remove(domain, net, macaddr, sriov_flag, live_flag, restart_flag):
    """
    Remove the network NET from the virtual machine DOMAIN.

    NET may be a PVC network VNI, which is added as a bridged device, or a SR-IOV VF device connected in the given mode.

    NET is optional if the '-m'/'--mac-address' option is specified. If it is, then the specific device with that MAC address is removed instead.

    If multiple interfaces are present on the VM in network NET, and '-m'/'--mac-address' is not specified, then all interfaces in that network will be removed.
    """
    if restart_flag and live_flag:
        live_flag = False

    retcode, retmsg = pvc.lib.vm.vm_networks_remove(
        CLI_CONFIG, domain, net, macaddr, sriov_flag, live_flag, restart_flag
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc vm volume
###############################################################################
@click.group(
    name="volume",
    short_help="Manage volumes for PVC VMs.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_vm_volume():
    """
    Manage and view the volumes of VMs in a PVC cluster.
    """
    pass


###############################################################################
# > pvc vm volume get
###############################################################################
@click.command(name="get", short_help="Get the volumes of a virtual machine.")
@connection_req
@click.argument("domain")
@format_opt(
    {
        "pretty": cli_vm_volume_get_format_pretty,
        "raw": lambda d: ",".join(
            [f"{v['protocol']}:{v['volume']}" for v in d["volumes"]]
        ),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_vm_volume_get(domain, format_function):
    """
    Get the volumes of the virtual machine DOMAIN.
    """

    retcode, retdata = pvc.lib.vm.vm_volumes_get(CLI_CONFIG, domain)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc vm volume add
###############################################################################
@click.command(name="add", short_help="Add volume to a virtual machine.")
@connection_req
@click.argument("domain")
@click.argument("volume")
@click.option(
    "-d",
    "--disk-id",
    "disk_id",
    default=None,
    help="The disk ID in sdX/vdX/hdX format; if not specified, the next available will be used.",
)
@click.option(
    "-b",
    "--bus",
    "bus",
    default="scsi",
    show_default=True,
    type=click.Choice(["scsi", "ide", "usb", "virtio"]),
    help="The bus to attach the disk to; must be present in the VM.",
)
@click.option(
    "-t",
    "--type",
    "disk_type",
    default="rbd",
    show_default=True,
    type=click.Choice(["rbd", "file"]),
    help="The type of volume to add.",
)
@click.option(
    "-l/-L",
    "--live/--no-live",
    "live_flag",
    is_flag=True,
    default=True,
    help="Immediately live-attach device to VM [default] or disable this behaviour.",
)
@restart_opt
@confirm_opt("Restart virtual machine {domain}")
def cli_vm_volume_add(domain, volume, disk_id, bus, disk_type, live_flag, restart_flag):
    """
    Add the volume VOLUME to the virtual machine DOMAIN.

    VOLUME may be either an absolute file path (for type 'file') or an RBD volume in the form "pool/volume" (for type 'rbd'). RBD volumes are verified against the cluster before adding and must exist.
    """
    if restart_flag and live_flag:
        live_flag = False

    retcode, retmsg = pvc.lib.vm.vm_volumes_add(
        CLI_CONFIG, domain, volume, disk_id, bus, disk_type, live_flag, restart_flag
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc vm volume remove
###############################################################################
@click.command(name="remove", short_help="Remove volume from a virtual machine.")
@connection_req
@click.argument("domain")
@click.argument("volume")
@click.option(
    "-l/-L",
    "--live/--no-live",
    "live_flag",
    is_flag=True,
    default=True,
    help="Immediately live-detach device to VM [default] or disable this behaviour.",
)
@restart_opt
@confirm_opt("Restart virtual machine {domain}")
def cli_vm_volume_remove(domain, volume, live_flag, restart_flag):
    """
    Remove VOLUME from the virtual machine DOMAIN; VOLUME must be a file path or RBD path in 'pool/volume' format.
    """
    if restart_flag and live_flag:
        live_flag = False

    retcode, retmsg = pvc.lib.vm.vm_volumes_remove(
        CLI_CONFIG, domain, volume, live_flag, restart_flag
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc vm log
###############################################################################
@click.command(name="log", short_help="Show console logs of a VM object.")
@connection_req
@click.argument("domain")
@click.option(
    "-l",
    "--lines",
    "lines",
    default=None,
    show_default=False,
    help="Display this many log lines from the end of the log buffer.  [default: 1000; with follow: 10]",
)
@click.option(
    "-f",
    "--follow",
    "follow",
    is_flag=True,
    default=False,
    help="Follow the log buffer; output may be delayed by a few seconds relative to the live system. The --lines value defaults to 10 for the initial output.",
)
def cli_vm_log(domain, lines, follow):
    """
    Show console logs of virtual machine DOMAIN on its current node in a pager or continuously. DOMAIN may be a UUID or name. Note that migrating a VM to a different node will cause the log buffer to be overwritten by entries from the new node.
    """

    # Set the default here so we can handle it
    if lines is None:
        if follow:
            lines = 10
        else:
            lines = 1000

    if follow:
        retcode, retmsg = pvc.lib.vm.follow_console_log(CLI_CONFIG, domain, lines)
    else:
        retcode, retmsg = pvc.lib.vm.view_console_log(CLI_CONFIG, domain, lines)
        click.echo_via_pager(retmsg)
        retmsg = ""
    finish(retcode, retmsg)


###############################################################################
# > pvc vm dump
###############################################################################
@click.command(name="dump", short_help="Dump a virtual machine XML to stdout.")
@connection_req
@click.option(
    "-f",
    "--file",
    "filename",
    default=None,
    type=click.File(mode="w"),
    help="Write VM XML to this file.",
)
@click.argument("domain")
def cli_vm_dump(filename, domain):
    """
    Dump the Libvirt XML definition of virtual machine DOMAIN to stdout. DOMAIN may be a UUID or name.
    """

    retcode, retdata = pvc.lib.vm.vm_info(CLI_CONFIG, domain)
    if not retcode or not retdata.get("name", None):
        finish(False, 'ERROR: Could not find VM "{}"!'.format(domain))

    current_vm_cfg_raw = retdata.get("xml")
    xml_data = fromstring(current_vm_cfg_raw)
    current_vm_cfgfile = tostring(xml_data, pretty_print=True).decode("utf8")
    xml = current_vm_cfgfile.strip()

    if filename is not None:
        filename.write(xml)
        finish(retcode, 'VM XML written to "{}".'.format(filename.name))
    else:
        finish(retcode, xml)


###############################################################################
# > pvc vm info
###############################################################################
@click.command(name="info", short_help="Show details of a VM object.")
@connection_req
@click.argument("domain")
@format_opt(
    {
        "pretty": cli_vm_info_format_pretty,
        "long": cli_vm_info_format_long,
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_vm_info(domain, format_function):
    """
    Show information about virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    retcode, retdata = pvc.lib.vm.vm_info(CLI_CONFIG, domain)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc vm list
###############################################################################
@click.command(name="list", short_help="List all VM objects.")
@connection_req
@click.argument("limit", default=None, required=False)
@click.option(
    "-t",
    "--target",
    "target_node",
    default=None,
    help="Limit list to VMs on the specified node.",
)
@click.option(
    "-s",
    "--state",
    "target_state",
    default=None,
    help="Limit list to VMs in the specified state.",
)
@click.option(
    "-g",
    "--tag",
    "target_tag",
    default=None,
    help="Limit list to VMs with the specified tag.",
)
@click.option(
    "-n",
    "--negate",
    "negate",
    is_flag=True,
    default=False,
    help="Negate the specified node, state, or tag limit(s).",
)
@format_opt(
    {
        "pretty": cli_vm_list_format_pretty,
        "raw": lambda d: "\n".join([v["name"] for v in d]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_vm_list(target_node, target_state, target_tag, limit, negate, format_function):
    """
    List all virtual machines; optionally only match names or full UUIDs matching regex LIMIT.

    NOTE: Red-coloured network lists indicate one or more configured networks are missing/invalid.
    """

    retcode, retdata = pvc.lib.vm.vm_list(
        CLI_CONFIG, limit, target_node, target_state, target_tag, negate
    )
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc network
###############################################################################
@click.group(
    name="network",
    short_help="Manage PVC networks.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_network():
    """
    Manage and view the networks in a PVC cluster.
    """
    pass


###############################################################################
# > pvc network add
###############################################################################
@click.command(name="add", short_help="Add a new virtual network.")
@connection_req
@click.option(
    "-d",
    "--description",
    "description",
    required=True,
    help="Description of the network; must be unique and not contain whitespace.",
)
@click.option(
    "-p",
    "--type",
    "nettype",
    required=True,
    type=click.Choice(["managed", "bridged"]),
    help="Network type; managed networks control IP addressing; bridged networks are simple vLAN bridges. All subsequent options are unused for bridged networks.",
)
@click.option("-m", "--mtu", "mtu", default="", help="MTU of the network interfaces.")
@click.option(
    "-n", "--domain", "domain", default=None, help="Domain name of the network."
)
@click.option(
    "--dns-server",
    "name_servers",
    multiple=True,
    help="DNS nameserver for network; multiple entries may be specified.",
)
@click.option(
    "-i",
    "--ipnet",
    "ip_network",
    default=None,
    help="CIDR-format IPv4 network address for subnet.",
)
@click.option(
    "-i6",
    "--ipnet6",
    "ip6_network",
    default=None,
    help='CIDR-format IPv6 network address for subnet; should be /64 or larger ending "::/YY".',
)
@click.option(
    "-g",
    "--gateway",
    "ip_gateway",
    default=None,
    help="Default IPv4 gateway address for subnet.",
)
@click.option(
    "-g6",
    "--gateway6",
    "ip6_gateway",
    default=None,
    help='Default IPv6 gateway address for subnet.  [default: "X::1"]',
)
@click.option(
    "--dhcp/--no-dhcp",
    "dhcp_flag",
    is_flag=True,
    default=False,
    help="Enable/disable IPv4 DHCP for clients on subnet.",
)
@click.option(
    "--dhcp-start", "dhcp_start", default=None, help="IPv4 DHCP range start address."
)
@click.option(
    "--dhcp-end", "dhcp_end", default=None, help="IPv4 DHCP range end address."
)
@click.argument("vni")
def cli_network_add(
    vni,
    description,
    nettype,
    mtu,
    domain,
    ip_network,
    ip_gateway,
    ip6_network,
    ip6_gateway,
    dhcp_flag,
    dhcp_start,
    dhcp_end,
    name_servers,
):
    """
    Add a new virtual network with VXLAN identifier VNI.

    NOTE: The MTU must be equal to, or less than, the underlying device MTU (either the node 'bridge_mtu' for bridged networks, or the node 'cluster_mtu' minus 50 for managed networks). Is only required if the device MTU should be lower than the underlying physical device MTU for compatibility. If unset, defaults to the underlying device MTU which will be set explcitly when the network is added to the nodes.

    Examples:

    pvc network add 101 --description my-bridged-net --type bridged

      > Creates vLAN 101 and a simple bridge on the VNI dev interface.

    pvc network add 1001 --description my-managed-net --type managed --domain test.local --ipnet 10.1.1.0/24 --gateway 10.1.1.1

      > Creates a VXLAN with ID 1001 on the VNI dev interface, with IPv4 managed networking.

    IPv6 is fully supported with --ipnet6 and --gateway6 in addition to or instead of IPv4. PVC will configure DHCPv6 in a semi-managed configuration for the network if set.
    """

    retcode, retmsg = pvc.lib.network.net_add(
        CLI_CONFIG,
        vni,
        description,
        nettype,
        mtu,
        domain,
        name_servers,
        ip_network,
        ip_gateway,
        ip6_network,
        ip6_gateway,
        dhcp_flag,
        dhcp_start,
        dhcp_end,
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc network modify
###############################################################################
@click.command(name="modify", short_help="Modify an existing virtual network.")
@connection_req
@click.option(
    "-d",
    "--description",
    "description",
    default=None,
    help="Description of the network; must be unique and not contain whitespace.",
)
@click.option("-m", "--mtu", "mtu", default=None, help="MTU of the network interfaces.")
@click.option(
    "-n", "--domain", "domain", default=None, help="Domain name of the network."
)
@click.option(
    "--dns-server",
    "name_servers",
    multiple=True,
    help="DNS nameserver for network; multiple entries may be specified (will overwrite all previous entries).",
)
@click.option(
    "-i",
    "--ipnet",
    "ip4_network",
    default=None,
    help='CIDR-format IPv4 network address for subnet; disable with "".',
)
@click.option(
    "-i6",
    "--ipnet6",
    "ip6_network",
    default=None,
    help='CIDR-format IPv6 network address for subnet; disable with "".',
)
@click.option(
    "-g",
    "--gateway",
    "ip4_gateway",
    default=None,
    help='Default IPv4 gateway address for subnet; disable with "".',
)
@click.option(
    "-g6",
    "--gateway6",
    "ip6_gateway",
    default=None,
    help='Default IPv6 gateway address for subnet; disable with "".',
)
@click.option(
    "--dhcp/--no-dhcp",
    "dhcp_flag",
    is_flag=True,
    default=None,
    help="Enable/disable DHCPv4 for clients on subnet (DHCPv6 is always enabled if DHCPv6 network is set).",
)
@click.option(
    "--dhcp-start", "dhcp_start", default=None, help="DHCPvr range start address."
)
@click.option("--dhcp-end", "dhcp_end", default=None, help="DHCPv4 range end address.")
@click.argument("vni")
def cli_network_modify(
    vni,
    description,
    mtu,
    domain,
    name_servers,
    ip6_network,
    ip6_gateway,
    ip4_network,
    ip4_gateway,
    dhcp_flag,
    dhcp_start,
    dhcp_end,
):
    """
    Modify details of virtual network VNI. All fields optional; only specified fields will be updated.

    NOTE: The MTU must be equal to, or less than, the underlying device MTU (either the node 'bridge_mtu' for bridged networks, or the node 'cluster_mtu' minus 50 for managed networks). Is only required if the device MTU should be lower than the underlying physical device MTU for compatibility. To reset an explicit MTU to the default underlying device MTU, specify '--mtu' with a quoted empty string argument.

    Example:

    pvc network modify 1001 --gateway 10.1.1.1 --dhcp
    """

    retcode, retmsg = pvc.lib.network.net_modify(
        CLI_CONFIG,
        vni,
        description,
        mtu,
        domain,
        name_servers,
        ip4_network,
        ip4_gateway,
        ip6_network,
        ip6_gateway,
        dhcp_flag,
        dhcp_start,
        dhcp_end,
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc network remove
###############################################################################
@click.command(name="remove", short_help="Remove a virtual network.")
@connection_req
@click.argument("net")
@confirm_opt("Remove network {net}")
def cli_network_remove(net):
    """
    Remove an existing virtual network NET; NET must be a VNI.

    WARNING: PVC does not verify whether clients are still present in this network. Before removing, ensure
    that all client VMs have been removed from the network or undefined behaviour may occur.
    """

    retcode, retmsg = pvc.lib.network.net_remove(CLI_CONFIG, net)
    finish(retcode, retmsg)


###############################################################################
# > pvc network info
###############################################################################
@click.command(name="info", short_help="Show details of a network.")
@connection_req
@click.argument("vni")
@format_opt(
    {
        "pretty": cli_network_info_format_pretty,
        "long": cli_network_info_format_long,
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_network_info(vni, format_function):
    """
    Show information about virtual network VNI.
    """

    retcode, retdata = pvc.lib.network.net_info(CLI_CONFIG, vni)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc network list
###############################################################################
@click.command(name="list", short_help="List all VM objects.")
@connection_req
@click.argument("limit", default=None, required=False)
@format_opt(
    {
        "pretty": cli_network_list_format_pretty,
        "raw": lambda d: "\n".join([f"{n['vni']}" for n in d]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_network_list(limit, format_function):
    """
    List all virtual networks; optionally only match VNIs or Descriptions matching regex LIMIT.
    """

    retcode, retdata = pvc.lib.network.net_list(CLI_CONFIG, limit)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc network dhcp
###############################################################################
@click.group(
    name="dhcp",
    short_help="Manage IPv4 DHCP leases in a PVC virtual network.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_network_dhcp():
    """
    Manage host IPv4 DHCP leases of a VXLAN network.
    """
    pass


###############################################################################
# > pvc network dhcp add
###############################################################################
@click.command(name="add", short_help="Add a DHCP static reservation.")
@connection_req
@click.argument("net")
@click.argument("ipaddr")
@click.argument("hostname")
@click.argument("macaddr")
def cli_network_dhcp_add(net, ipaddr, macaddr, hostname):
    """
    Add a new DHCP static reservation of IP address IPADDR with hostname HOSTNAME for MAC address MACADDR to virtual network NET; NET must be a VNI.
    """

    retcode, retmsg = pvc.lib.network.net_dhcp_add(
        CLI_CONFIG, net, ipaddr, macaddr, hostname
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc network dhcp remove
###############################################################################
@click.command(name="remove", short_help="Remove a DHCP static reservation.")
@connection_req
@click.argument("net")
@click.argument("macaddr")
@confirm_opt("Remove DHCP reservation {macaddr} from network {net}")
def cli_network_dhcp_remove(net, macaddr):
    """
    Remove a DHCP lease for MACADDR from virtual network NET; NET must be a VNI.
    """

    retcode, retmsg = pvc.lib.network.net_dhcp_remove(CLI_CONFIG, net, macaddr)
    finish(retcode, retmsg)


###############################################################################
# > pvc network dhcp list
###############################################################################
@click.command(name="list", short_help="List active DHCP leases.")
@connection_req
@click.argument("net")
@click.argument("limit", default=None, required=False)
@click.option(
    "-s",
    "--static",
    "only_static",
    is_flag=True,
    default=False,
    help="Show only static leases.",
)
@format_opt(
    {
        "pretty": cli_network_dhcp_list_format_pretty,
        "raw": lambda d: "\n".join(
            [f"{n['mac_address']}|{n['ip4_address']}|{n['hostname']}" for n in d]
        ),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_network_dhcp_list(net, limit, only_static, format_function):
    """
    List all DHCP leases in virtual network NET; optionally only match elements matching regex LIMIT; NET must be a VNI.
    """

    retcode, retdata = pvc.lib.network.net_dhcp_list(
        CLI_CONFIG, net, limit, only_static
    )
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc network acl
###############################################################################
@click.group(
    name="acl",
    short_help="Manage a PVC virtual network firewall ACL rule.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_network_acl():
    """
    Manage firewall ACLs of a VXLAN network.
    """
    pass


###############################################################################
# > pvc network acl add
###############################################################################
@click.command(name="add", short_help="Add firewall ACL.")
@connection_req
@click.option(
    "--in/--out",
    "direction",
    is_flag=True,
    default=True,  # inbound
    help="Inbound or outbound ruleset.",
)
@click.option(
    "-d",
    "--description",
    "description",
    required=True,
    help="Description of the ACL; must be unique and not contain whitespace.",
)
@click.option("-r", "--rule", "rule", required=True, help="NFT firewall rule.")
@click.option(
    "-o",
    "--order",
    "order",
    default=None,
    help='Order of rule in the chain (see "list"); defaults to last.',
)
@click.argument("net")
def cli_network_acl_add(net, direction, description, rule, order):
    """
    Add a new NFT firewall rule to network NET; the rule is a literal NFT rule belonging to the forward table for the client network; NET must be a VNI.

    NOTE: All client networks are default-allow in both directions; deny rules MUST be added here at the end of the sequence for a default-deny setup.

    NOTE: Ordering places the rule at the specified ID, not before it; the old rule of that ID and all subsequent rules will be moved down.

    NOTE: Descriptions are used as names, and must be unique within a network (both directions).

    Example:

    pvc network acl add 1001 --in --rule "tcp dport 22 ct state new accept" --description "ssh-in" --order 3
    """
    if direction:
        direction = "in"
    else:
        direction = "out"

    retcode, retmsg = pvc.lib.network.net_acl_add(
        CLI_CONFIG, net, direction, description, rule, order
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc network acl remove
###############################################################################
@click.command(name="remove", short_help="Remove firewall ACL.")
@connection_req
@click.argument("net")
@click.argument(
    "rule",
)
@confirm_opt("Remove firewall rule {rule} from network {net}")
def cli_network_acl_remove(net, rule):
    """
    Remove an NFT firewall rule RULE from network NET; RULE must be a description; NET must be a VNI.
    """

    retcode, retmsg = pvc.lib.network.net_acl_remove(CLI_CONFIG, net, rule)
    finish(retcode, retmsg)


###############################################################################
# > pvc network acl list
###############################################################################
@click.command(name="list", short_help="List firewall ACLs.")
@connection_req
@click.option(
    "--in/--out",
    "direction",
    is_flag=True,
    required=False,
    default=None,
    help="Inbound or outbound rule set only.",
)
@click.argument("net")
@click.argument("limit", default=None, required=False)
@format_opt(
    {
        "pretty": cli_network_acl_list_format_pretty,
        "raw": lambda d: "\n".join(
            [f"{n['direction']}|{n['order']}|{n['rule']}" for n in d]
        ),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_network_acl_list(net, limit, direction, format_function):
    """
    List all NFT firewall rules in network NET; optionally only match elements matching description regex LIMIT; NET can be either a VNI or description.
    """
    if direction is not None:
        if direction:
            direction = "in"
        else:
            direction = "out"

    retcode, retdata = pvc.lib.network.net_acl_list(CLI_CONFIG, net, limit, direction)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc network sriov
###############################################################################
@click.group(
    name="sriov",
    short_help="Manage SR-IOV network resources.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_network_sriov():
    """
    Manage SR-IOV network resources on nodes (PFs and VFs).
    """
    pass


###############################################################################
# > pvc network sriov pf
###############################################################################
@click.group(
    name="pf", short_help="Manage PF devices.", context_settings=CONTEXT_SETTINGS
)
def cli_network_sriov_pf():
    """
    Manage SR-IOV PF devices on nodes.
    """
    pass


###############################################################################
# > pvc network sriov pf list TODO:formatter-raw
###############################################################################
@click.command(name="list", short_help="List PF devices.")
@connection_req
@click.argument("node")
@format_opt(
    {
        "pretty": cli_network_sriov_pf_list_format_pretty,
        #        "raw": lambda d: "\n".join([f"{n['mac_address']}|{n['ip4_address']}|{n['hostname']}" for n in d]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_network_sriov_pf_list(node, format_function):
    """
    List all SR-IOV PFs on NODE.
    """
    retcode, retdata = pvc.lib.network.net_sriov_pf_list(CLI_CONFIG, node)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc network sriov vf
###############################################################################
@click.group(
    name="vf", short_help="Manage VF devices.", context_settings=CONTEXT_SETTINGS
)
def cli_network_sriov_vf():
    """
    Manage SR-IOV VF devices on nodes.
    """
    pass


###############################################################################
# > pvc network sriov vf set
###############################################################################
@click.command(name="set", short_help="Set VF device properties.")
@connection_req
@click.option(
    "--vlan-id",
    "vlan_id",
    default=None,
    show_default=False,
    help="The vLAN ID for vLAN tagging.",
)
@click.option(
    "--qos-prio",
    "vlan_qos",
    default=None,
    show_default=False,
    help="The vLAN QOS priority.",
)
@click.option(
    "--tx-min",
    "tx_rate_min",
    default=None,
    show_default=False,
    help="The minimum TX rate.",
)
@click.option(
    "--tx-max",
    "tx_rate_max",
    default=None,
    show_default=False,
    help="The maximum TX rate.",
)
@click.option(
    "--link-state",
    "link_state",
    default=None,
    show_default=False,
    type=click.Choice(["auto", "enable", "disable"]),
    help="The administrative link state.",
)
@click.option(
    "--spoof-check/--no-spoof-check",
    "spoof_check",
    is_flag=True,
    default=None,
    show_default=False,
    help="Enable or disable spoof checking.",
)
@click.option(
    "--trust/--no-trust",
    "trust",
    is_flag=True,
    default=None,
    show_default=False,
    help="Enable or disable VF user trust.",
)
@click.option(
    "--query-rss/--no-query-rss",
    "query_rss",
    is_flag=True,
    default=None,
    show_default=False,
    help="Enable or disable query RSS support.",
)
@click.argument("node")
@click.argument("vf")
def net_sriov_vf_set(
    node,
    vf,
    vlan_id,
    vlan_qos,
    tx_rate_min,
    tx_rate_max,
    link_state,
    spoof_check,
    trust,
    query_rss,
):
    """
    Set a property of SR-IOV VF on NODE.
    """
    if (
        vlan_id is None
        and vlan_qos is None
        and tx_rate_min is None
        and tx_rate_max is None
        and link_state is None
        and spoof_check is None
        and trust is None
        and query_rss is None
    ):
        finish(
            False, "At least one configuration property must be specified to update."
        )

    retcode, retmsg = pvc.lib.network.net_sriov_vf_set(
        CLI_CONFIG,
        node,
        vf,
        vlan_id,
        vlan_qos,
        tx_rate_min,
        tx_rate_max,
        link_state,
        spoof_check,
        trust,
        query_rss,
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc network sriov vf info
###############################################################################
@click.command(name="info", short_help="Show details of VF devices.")
@connection_req
@click.argument("node")
@click.argument("vf")
@format_opt(
    {
        "pretty": cli_network_sriov_vf_info_format_pretty,
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_network_sriov_vf_info(node, vf, format_function):
    """
    Show details of the SR-IOV VF on NODE.
    """
    retcode, retdata = pvc.lib.network.net_sriov_vf_info(CLI_CONFIG, node, vf)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc network sriov vf list TODO:formatter-raw
###############################################################################
@click.command(name="list", short_help="List VF devices.")
@connection_req
@click.argument("node")
@click.argument("pf", default=None, required=False)
@format_opt(
    {
        "pretty": cli_network_sriov_vf_list_format_pretty,
        #        "raw": lambda d: "\n".join([f"{n['mac_address']}|{n['ip4_address']}|{n['hostname']}" for n in d]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_network_sriov_vf_list(node, pf, format_function):
    """
    List all SR-IOV VFs on NODE, optionally limited to device PF.
    """
    retcode, retdata = pvc.lib.network.net_sriov_vf_list(CLI_CONFIG, node, pf)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc storage
###############################################################################
@click.group(
    name="storage",
    short_help="Manage PVC storage.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_storage():
    """
    Manage and view the storage system in a PVC cluster.
    """
    pass


###############################################################################
# > pvc storage status TODO:send JSON instead of raw
###############################################################################
@click.command(name="status", short_help="Show storage cluster status.")
@connection_req
@format_opt(
    {
        "pretty": cli_storage_status_format_raw,
        #        "raw": lambda d: "\n".join([f"{n['mac_address']}|{n['ip4_address']}|{n['hostname']}" for n in d]),
        #        "json": lambda d: jdumps(d),
        #        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_storage_status(format_function):
    """
    Show detailed status of the storage cluster.
    """

    retcode, retdata = pvc.lib.storage.ceph_status(CLI_CONFIG)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc storage util TODO:send JSON instead of raw
###############################################################################
@click.command(name="util", short_help="Show storage cluster utilization.")
@connection_req
@format_opt(
    {
        "pretty": cli_storage_util_format_raw,
        #        "raw": lambda d: "\n".join([f"{n['mac_address']}|{n['ip4_address']}|{n['hostname']}" for n in d]),
        #        "json": lambda d: jdumps(d),
        #        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_storage_util(format_function):
    """
    Show utilization of the storage cluster.
    """

    retcode, retdata = pvc.lib.storage.ceph_util(CLI_CONFIG)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc storage benchmark
###############################################################################
@click.group(name="benchmark", short_help="Run or view cluster storage benchmarks.")
def cli_storage_benchmark():
    """
    Run or view benchmarks of the storage cluster.
    """
    pass


###############################################################################
# > pvc storage benchmark run
###############################################################################
@click.command(name="run", short_help="Run a storage benchmark.")
@connection_req
@click.argument("pool")
@click.option(
    "--wait/--no-wait",
    "wait_flag",
    is_flag=True,
    default=True,
    show_default=True,
    help="Wait or don't wait for task to complete, showing progress",
)
@confirm_opt(
    "Storage benchmarks take approximately 10 minutes to run and generate significant load on the cluster; they should be run sparingly. Continue"
)
def cli_storage_benchmark_run(pool, wait_flag):
    """
    Run a storage benchmark on POOL in the background.
    """

    retcode, retmsg = pvc.lib.storage.ceph_benchmark_run(CLI_CONFIG, pool, wait_flag)

    if retcode and wait_flag:
        retmsg = wait_for_celery_task(CLI_CONFIG, retmsg)
    finish(retcode, retmsg)


###############################################################################
# > pvc storage benchmark info
###############################################################################
@click.command(name="info", short_help="Show detailed storage benchmark results.")
@connection_req
@click.argument("job", required=True)
@format_opt(
    {
        "pretty": cli_storage_benchmark_info_format_pretty,
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_storage_benchmark_info(job, format_function):
    """
    Show full details of storage benchmark JOB.
    """

    retcode, retdata = pvc.lib.storage.ceph_benchmark_list(CLI_CONFIG, job)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc storage benchmark list
###############################################################################
@click.command(name="list", short_help="List storage benchmark results.")
@connection_req
@click.argument("job", default=None, required=False)
@format_opt(
    {
        "pretty": cli_storage_benchmark_list_format_pretty,
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_storage_benchmark_list(job, format_function):
    """
    List all Ceph storage benchmarks; optionally only match JOB.
    """

    retcode, retdata = pvc.lib.storage.ceph_benchmark_list(CLI_CONFIG, job)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc storage osd
###############################################################################
@click.group(
    name="osd",
    short_help="Manage OSDs in the PVC storage cluster.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_storage_osd():
    """
    Manage the Ceph OSDs of the PVC cluster.
    """
    pass


###############################################################################
# > pvc storage osd create-db-vg
###############################################################################
@click.command(name="create-db-vg", short_help="Create new OSD database volume group.")
@connection_req
@click.argument("node")
@click.argument("device")
@click.option(
    "--wait/--no-wait",
    "wait_flag",
    is_flag=True,
    default=True,
    show_default=True,
    help="Wait or don't wait for task to complete, showing progress",
)
@confirm_opt(
    "Destroy all data on and create a new OSD database volume group on node {node} device {device}"
)
def cli_storage_osd_create_db_vg(node, device, wait_flag):
    """
    Create a new Ceph OSD database volume group on node NODE with block device DEVICE.

    DEVICE must be a valid block device path (e.g. '/dev/nvme0n1', '/dev/disk/by-path/...') or a "detect" string. Partitions are NOT supported. A "detect" string is a string in the form "detect:<NAME>:<HUMAN-SIZE>:<ID>". For details, see 'pvc storage osd add --help'. The path or detect string must be valid on the current node housing the OSD.

    This volume group will be used for Ceph OSD database and WAL functionality if an'--ext-db-*' flag is passed to newly-created OSDs during 'pvc storage osd add'. DEVICE should be an extremely fast SSD device (NVMe, Intel Optane, etc.) which is significantly faster than the normal OSD disks and with very high write endurance. For mor edetails, see the "pvc storage osd add" command help.

    Only one OSD database volume group on a single physical device, named "osd-db", is supported per node, so it must be fast and large enough to act as an effective OSD database device for all OSDs on the node. Attempting to add additional database volume groups after the first will result in an error.

    WARNING: If the OSD database device fails, all OSDs on the node using it will be lost and must be recreated.

    A "detect" string is a string in the form "detect:<NAME>:<HUMAN-SIZE>:<ID>". Detect strings allow for automatic determination of Linux block device paths from known basic information about disks by leveraging "lsscsi" on the target host. The "NAME" should be some descriptive identifier, for instance the manufacturer (e.g. "INTEL"), the "HUMAN-SIZE" should be the labeled human-readable size of the device (e.g. "480GB", "1.92TB"), and "ID" specifies the Nth 0-indexed device which matches the "NAME" and "HUMAN-SIZE" values (e.g. "2" would match the third device with the corresponding "NAME" and "HUMAN-SIZE"). When matching against sizes, there is +/- 3% flexibility to account for base-1000 vs. base-1024 differences and rounding errors. The "NAME" may contain whitespace but if so the entire detect string should be quoted, and is case-insensitive. More information about detect strings can be found in the manual.
    """

    retcode, retmsg = pvc.lib.storage.ceph_osd_db_vg_add(
        CLI_CONFIG, node, device, wait_flag
    )

    if retcode and wait_flag:
        retmsg = wait_for_celery_task(CLI_CONFIG, retmsg)
    finish(retcode, retmsg)


###############################################################################
# > pvc storage osd add
###############################################################################
@click.command(name="add", short_help="Add new OSD.")
@connection_req
@click.argument("node")
@click.argument("device")
@click.option(
    "-w",
    "--weight",
    "weight",
    default=1.0,
    show_default=True,
    help="Weight of the OSD(s) within the CRUSH map.",
)
@click.option(
    "-r",
    "--ext-db-ratio",
    "ext_db_ratio",
    default=None,
    type=float,
    help="Create an external database logical volume for the OSD(s) with this decimal ratio of the DB LV to the OSD size.",
)
@click.option(
    "-s",
    "--ext-db-size",
    "ext_db_size",
    default=None,
    show_default=True,
    help="Create an external database logical volume for the OSD(s) with this human-unit size.",
)
@click.option(
    "-c",
    "--osd-count",
    "osd_count",
    default=None,
    show_default=False,
    type=int,
    help="Split (an NVMe) disk into this many OSDs.",
)
@click.option(
    "--wait/--no-wait",
    "wait_flag",
    is_flag=True,
    default=True,
    show_default=True,
    help="Wait or don't wait for task to complete, showing progress",
)
@confirm_opt("Destroy all data on and create new OSD(s) on node {node} device {device}")
def cli_storage_osd_add(
    node, device, weight, ext_db_ratio, ext_db_size, osd_count, wait_flag
):
    """
    Add a new Ceph OSD on node NODE with block device DEVICE.

    DEVICE must be a valid block device path (e.g. '/dev/nvme0n1', '/dev/disk/by-path/...') or a "detect" string. Partitions are NOT supported. A "detect" string is a string in the form "detect:<NAME>:<HUMAN-SIZE>:<ID>". The path or detect string must be valid on the current node housing the OSD.

    A "detect" string is a string in the form "detect:<NAME>:<HUMAN-SIZE>:<ID>". Detect strings allow for automatic determination of Linux block device paths from known basic information about disks by leveraging "lsscsi" on the target host. The "NAME" should be some descriptive identifier, for instance the manufacturer (e.g. "INTEL"), the "HUMAN-SIZE" should be the labeled human-readable size of the device (e.g. "480GB", "1.92TB"), and "ID" specifies the Nth 0-indexed device which matches the "NAME" and "HUMAN-SIZE" values (e.g. "2" would match the third device with the corresponding "NAME" and "HUMAN-SIZE"). When matching against sizes, there is +/- 3% flexibility to account for base-1000 vs. base-1024 differences and rounding errors. The "NAME" may contain whitespace but if so the entire detect string should be quoted, and is case-insensitive. More information about detect strings can be found in the pvcbootstrapd manual.

    The weight of an OSD should reflect the ratio of the size of the OSD to the other OSDs in the storage cluster. For example, with a 200GB disk and a 400GB disk in each node, the 400GB disk should have twice the weight as the 200GB disk. For more information about CRUSH weights, please see the Ceph documentation.

    The "-r"/"--ext-db-ratio" or "-s"/"--ext-db-size" options, if specified, and if a OSD DB VG exists on the node (see "pvc storage osd create-db-vg"), will instruct the OSD to locate its RocksDB database and WAL on a new logical volume on that OSD DB VG. If "-r"/"--ext-db-ratio" is specified, the sizing of this DB LV will be the given ratio (specified as a decimal percentage e.g. 0.05 for 5%) of the size of the OSD (e.g. 0.05 on a 1TB SSD will create a 50GB LV). If "-s"/"--ext-db-size" is specified, the sizing of this DB LV will be the given human-unit size (e.g. 1024M, 20GB, etc.). An 0.05 ratio is recommended; at least 0.02 is required, and more than 0.05 can potentially increase performance in write-heavy workloads.

    WARNING: An external DB carries important caveats. An external DB is only suggested for relatively slow OSD devices (e.g. SATA SSDs) when there is also a much faster, more robust, but smaller storage device in the system (e.g. an NVMe or 3DXPoint SSD) which can accelerate the OSD. An external DB is NOT recommended for NVMe OSDs as this will hamper performance and reliability. Additionally, it is important to note that the OSD will depend entirely on this external DB device; they cannot be separated without destroying the OSD, and the OSD cannot function without the external DB device, thus introducting a single point of failure. Use this feature with extreme care.

    The "-c"/"--osd-count" option allows the splitting of a single block device into multiple logical OSDs. This is recommended in the Ceph literature for extremely fast OSD block devices (i.e. NVMe or 3DXPoint) which can saturate a single OSD process. Usually, 2 or 4 OSDs is recommended, based on the size and performance of the OSD disk; more than 4 OSDs per volume is not recommended, and this option is not recommended for SATA SSDs.

    Note that, if "-c"/"--osd-count" is specified, the provided "-w"/"--weight" will be the weight of EACH created OSD, not the block device as a whole. Ensure you take this into account if mixing and matching OSD block devices. Additionally, if "-r"/"--ext-db-ratio" or "-s"/"--ext-db-size" is specified, one DB LV will be created for EACH created OSD, of the given ratio/size per OSD; ratios are calculated from the OSD size, not the underlying device.

    NOTE: This command may take a long time to complete. Observe the node logs of the hosting OSD node for detailed status.
    """

    retcode, retmsg = pvc.lib.storage.ceph_osd_add(
        CLI_CONFIG,
        node,
        device,
        weight,
        ext_db_ratio,
        ext_db_size,
        osd_count,
        wait_flag,
    )

    if retcode and wait_flag:
        retmsg = wait_for_celery_task(CLI_CONFIG, retmsg)
    finish(retcode, retmsg)


###############################################################################
# > pvc storage osd replace
###############################################################################
@click.command(name="replace", short_help="Replace OSD block device.")
@connection_req
@click.argument("osdid")
@click.argument("new_device")
@click.option(
    "-o",
    "--old-device",
    "old_device",
    default=None,
    help="The old OSD block device, if known and valid",
)
@click.option(
    "-w",
    "--weight",
    "weight",
    default=None,
    help="New weight of the OSD(s) within the CRUSH map; if unset, old weight is used",
)
@click.option(
    "-r",
    "--ext-db-ratio",
    "ext_db_ratio",
    default=None,
    help="Create a new external database logical volume for the OSD(s) with this decimal ratio of the DB LV to the OSD size; if unset, old ext_db_size is used",
)
@click.option(
    "-s",
    "--ext-db-size",
    "ext_db_size",
    default=None,
    help="Create a new external database logical volume for the OSD(s) with this human-unit size; if unset, old ext_db_size is used",
)
@click.option(
    "--wait/--no-wait",
    "wait_flag",
    is_flag=True,
    default=True,
    show_default=True,
    help="Wait or don't wait for task to complete, showing progress",
)
@confirm_opt(
    "Destroy all data on and replace OSD {osdid} (and peer split OSDs) with new device {new_device}"
)
def cli_storage_osd_replace(
    osdid, new_device, old_device, weight, ext_db_ratio, ext_db_size, wait_flag
):
    """
    Replace the block device of an existing OSD with ID OSDID, and any peer split OSDs with the same block device, with NEW_DEVICE. Use this command to replace a failed or smaller OSD block device with a new one in one command.

    DEVICE must be a valid block device path (e.g. '/dev/nvme0n1', '/dev/disk/by-path/...') or a "detect" string. Partitions are NOT supported. A "detect" string is a string in the form "detect:<NAME>:<HUMAN-SIZE>:<ID>". For details, see 'pvc storage osd add --help'. The path or detect string must be valid on the current node housing the OSD.

    If OSDID is part of a split OSD set, any peer split OSDs with the same configured block device will be replaced as well. The split count will be retained and cannot be changed with this command; to do so, all OSDs in the split OSD set must be removed and new OSD(s) created.

    WARNING: This operation entails (and is functionally equivalent to) a removal and recreation of the specified OSD and, if applicable, all peer split OSDs. This is an intensive and potentially destructive action. Ensure that the cluster is otherwise healthy before proceeding, and ensure the subsequent rebuild completes successfully. Do not attempt this operation on a severely degraded cluster without first considering the possible data loss implications.

    If the "-o"/"--old-device" option is specified, is a valid block device on the node, is readable/accessible, and contains the metadata for the specified OSD, it will be zapped. If this option is not specified, the system will try to find the old block device automatically to zap it. If it can't be found, the OSD will simply be removed from the CRUSH map and PVC database before recreating. This option can provide a cleaner deletion when replacing a working device that has a different block path, but is otherwise unnecessary.

    The "-w"/"--weight", "-r"/"--ext-db-ratio", and "-s"/"--ext-db-size" allow overriding the existing weight and external DB LV for the OSD(s), if desired. If unset, the existing weight and external DB LV size (if applicable) will be used for the replacement OSD(s) instead.

    NOTE: If neither the "-r"/"--ext-db-ratio" or "-s"/"--ext-db-size" option is specified, and the OSD(s) had an external DB LV, it cannot be removed a new DB LV will be created for the replacement OSD(s); this cannot be avoided. However, if the OSD(s) did not have an external DB LV, and one of these options is specified, a new DB LV will be added to the new OSD.

    NOTE: This command may take a long time to complete. Observe the node logs of the hosting OSD node for detailed status.
    """

    retcode, retmsg = pvc.lib.storage.ceph_osd_replace(
        CLI_CONFIG,
        osdid,
        new_device,
        old_device,
        weight,
        ext_db_ratio,
        ext_db_size,
        wait_flag,
    )

    if retcode and wait_flag:
        retmsg = wait_for_celery_task(CLI_CONFIG, retmsg)
    finish(retcode, retmsg)


###############################################################################
# > pvc storage osd refresh
###############################################################################
@click.command(name="refresh", short_help="Refresh (reimport) OSD device.")
@connection_req
@click.argument("osdid")
@click.argument("device")
@click.option(
    "--wait/--no-wait",
    "wait_flag",
    is_flag=True,
    default=True,
    show_default=True,
    help="Wait or don't wait for task to complete, showing progress",
)
@confirm_opt("Refresh OSD {osdid} (and peer split OSDs) on device {device}")
def cli_storage_osd_refresh(osdid, device, wait_flag):
    """
    Refresh (reimport) the block DEVICE of an existing OSD with ID OSDID. Use this command to reimport a working OSD into a rebuilt/replaced node.

    DEVICE must be a valid block device path (e.g. '/dev/nvme0n1', '/dev/disk/by-path/...') or a "detect" string. Partitions are NOT supported. A "detect" string is a string in the form "detect:<NAME>:<HUMAN-SIZE>:<ID>". For details, see 'pvc storage osd add --help'. The path or detect string must be valid on the current node housing the OSD.

    Existing data, IDs, weights, DB LVs, etc. of the OSD will be preserved. Any split peer OSD(s) on the same block device will also be automatically refreshed.

    NOTE: If the OSD(s) had an external DB device, it must exist before refreshing the OSD. If it can't be found, the OSD cannot be reimported and must be recreated.

    NOTE: This command may take a long time to complete. Observe the node logs of the hosting OSD node for detailed status.
    """

    retcode, retmsg = pvc.lib.storage.ceph_osd_refresh(
        CLI_CONFIG, osdid, device, wait_flag
    )

    if retcode and wait_flag:
        retmsg = wait_for_celery_task(CLI_CONFIG, retmsg)
    finish(retcode, retmsg)


###############################################################################
# > pvc storage osd remove
###############################################################################
@click.command(name="remove", short_help="Remove OSD.")
@connection_req
@click.argument("osdid")
@click.option(
    "-f",
    "--force",
    "force_flag",
    is_flag=True,
    default=False,
    help="Force removal even if steps fail",
)
@click.option(
    "--wait/--no-wait",
    "wait_flag",
    is_flag=True,
    default=True,
    show_default=True,
    help="Wait or don't wait for task to complete, showing progress",
)
@confirm_opt("Remove and destroy data on OSD {osdid}")
def cli_storage_osd_remove(osdid, force_flag, wait_flag):
    """
    Remove a Ceph OSD with ID OSDID.

    DANGER: This will completely remove the OSD from the cluster. OSDs will rebalance which will negatively affect performance and available space. It is STRONGLY RECOMMENDED to set an OSD out (using 'pvc storage osd out') and allow the cluster to fully rebalance, verified with 'pvc storage status', before removing an OSD.

    NOTE: The "-f"/"--force" option is useful after replacing a failed node, to ensure the OSD is removed even if the OSD in question does not properly exist on the node after a rebuild.

    NOTE: This command may take a long time to complete. Observe the node logs of the hosting OSD node for detailed status.
    """

    retcode, retmsg = pvc.lib.storage.ceph_osd_remove(
        CLI_CONFIG, osdid, force_flag, wait_flag
    )

    if retcode and wait_flag:
        retmsg = wait_for_celery_task(CLI_CONFIG, retmsg)
    finish(retcode, retmsg)


###############################################################################
# > pvc storage osd in
###############################################################################
@click.command(name="in", short_help="Online OSD.")
@connection_req
@click.argument("osdid")
def cli_storage_osd_in(osdid):
    """
    Set a Ceph OSD with ID OSDID online.
    """

    retcode, retmsg = pvc.lib.storage.ceph_osd_state(CLI_CONFIG, osdid, "in")
    finish(retcode, retmsg)


###############################################################################
# > pvc storage osd out
###############################################################################
@click.command(name="out", short_help="Offline OSD.")
@connection_req
@click.argument("osdid")
def cli_storage_osd_out(osdid):
    """
    Set a Ceph OSD with ID OSDID offline.
    """

    retcode, retmsg = pvc.lib.storage.ceph_osd_state(CLI_CONFIG, osdid, "out")
    finish(retcode, retmsg)


###############################################################################
# > pvc storage osd set
###############################################################################
@click.command(name="set", short_help="Set OSD property.")
@connection_req
@click.argument("osd_property")
def cli_storage_osd_set(osd_property):
    """
    Set (enable) a Ceph OSD property OSD_PROPERTY on the cluster.

    Valid properties are:

      full|pause|noup|nodown|noout|noin|nobackfill|norebalance|norecover|noscrub|nodeep-scrub|notieragent|sortbitwise|recovery_deletes|require_jewel_osds|require_kraken_osds
    """

    retcode, retmsg = pvc.lib.storage.ceph_osd_option(CLI_CONFIG, osd_property, "set")
    finish(retcode, retmsg)


###############################################################################
# > pvc storage osd unset
###############################################################################
@click.command(name="unset", short_help="Unset OSD property.")
@connection_req
@click.argument("osd_property")
def cli_storage_osd_unset(osd_property):
    """
    Unset (disable) a Ceph OSD property OSD_PROPERTY on the cluster.

    Valid properties are:

      full|pause|noup|nodown|noout|noin|nobackfill|norebalance|norecover|noscrub|nodeep-scrub|notieragent|sortbitwise|recovery_deletes|require_jewel_osds|require_kraken_osds
    """

    retcode, retmsg = pvc.lib.storage.ceph_osd_option(CLI_CONFIG, osd_property, "unset")
    finish(retcode, retmsg)


###############################################################################
# > pvc storage osd info
###############################################################################
# Not implemented


###############################################################################
# > pvc storage osd list
###############################################################################
@click.command(name="list", short_help="List cluster OSDs.")
@connection_req
@click.argument("limit", default=None, required=False)
@format_opt(
    {
        "pretty": cli_storage_osd_list_format_pretty,
        "raw": lambda d: "\n".join([f"{o['id']}:{o['node']}:{o['device']}" for o in d]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_storage_osd_list(limit, format_function):
    """
    List all Ceph OSDs; optionally only match elements matching ID regex LIMIT.
    """

    retcode, retdata = pvc.lib.storage.ceph_osd_list(CLI_CONFIG, limit)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc storage pool
###############################################################################
@click.group(
    name="pool",
    short_help="Manage RBD pools in the PVC storage cluster.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_storage_pool():
    """
    Manage the Ceph RBD pools of the PVC cluster.
    """
    pass


###############################################################################
# > pvc storage pool add
###############################################################################
@click.command(name="add", short_help="Add new RBD pool.")
@connection_req
@click.argument("name")
@click.argument("pgs")
@click.option(
    "-t",
    "--tier",
    "tier",
    default="default",
    show_default=True,
    type=click.Choice(["default", "hdd", "ssd", "nvme"]),
    help="""
    The device tier to limit the pool to. Default is all OSD tiers, and specific tiers can be specified instead. At least one full set of OSDs for a given tier must be present for the tier to be specified, or the pool creation will fail.
    """,
)
@click.option(
    "--replcfg",
    "replcfg",
    default="copies=3,mincopies=2",
    show_default=True,
    required=False,
    help="""
    The replication configuration, specifying both a "copies" and "mincopies" value, separated by a comma, e.g. "copies=3,mincopies=2". The "copies" value specifies the total number of replicas and the "mincopies" value specifies the minimum number of active replicas to allow I/O. For additional details please see the documentation.
    """,
)
def cli_storage_pool_add(name, pgs, tier, replcfg):
    """
    Add a new Ceph RBD pool with name NAME and PGS placement groups.

    The placement group count must be a non-zero power of 2. Generally you should choose a PGS number such that there will be 50-150 PGs on each OSD in a single node (before replicas); 64, 128, or 256 are good values for small clusters (1-5 OSDs per node); higher values are recommended for higher node or OSD counts. For additional details please see the documentation.
    """

    retcode, retmsg = pvc.lib.storage.ceph_pool_add(
        CLI_CONFIG, name, pgs, replcfg, tier
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc storage pool remove
###############################################################################
@click.command(name="remove", short_help="Remove RBD pool.")
@connection_req
@click.argument("name")
@confirm_opt("Remove and destroy all data in RBD pool {name}")
def cli_storage_pool_remove(name):
    """
    Remove a Ceph RBD pool with name NAME and all volumes on it.

    DANGER: This will completely remove the pool and all volumes contained in it from the cluster.
    """

    retcode, retmsg = pvc.lib.storage.ceph_pool_remove(CLI_CONFIG, name)
    finish(retcode, retmsg)


###############################################################################
# > pvc storage pool set-pgs
###############################################################################
@click.command(name="set-pgs", short_help="Set PGs of an RBD pool.")
@connection_req
@click.argument("name")
@click.argument("pgs")
@confirm_opt("Adjust PG count of pool {name} to {pgs}")
def cli_storage_pool_set_pgs(name, pgs):
    """
    Set the placement groups (PGs) count for the pool NAME to PGS.

    The placement group count must be a non-zero power of 2. Generally you should choose a PGS number such that there will be 50-150 PGs on each OSD in a single node (before replicas); 64, 128, or 256 are good values for small clusters (1-5 OSDs per node); higher values are recommended for higher node or OSD counts. For additional details please see the documentation.

    Placement group counts may be increased or decreased as required though frequent alteration is not recommended. Placement group alterations are intensive operations on the storage cluster.
    """

    retcode, retmsg = pvc.lib.storage.ceph_pool_set_pgs(CLI_CONFIG, name, pgs)
    finish(retcode, retmsg)


###############################################################################
# > pvc storage pool info
###############################################################################
# Not implemented


###############################################################################
# > pvc storage pool list
###############################################################################
@click.command(name="list", short_help="List cluster RBD pools.")
@connection_req
@click.argument("limit", default=None, required=False)
@format_opt(
    {
        "pretty": cli_storage_pool_list_format_pretty,
        "raw": lambda d: "\n".join([p["name"] for p in d]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_storage_pool_list(limit, format_function):
    """
    List all Ceph RBD pools; optionally only match elements matching name regex LIMIT.
    """

    retcode, retdata = pvc.lib.storage.ceph_pool_list(CLI_CONFIG, limit)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc storage volume
###############################################################################
@click.group(
    name="volume",
    short_help="Manage RBD volumes in the PVC storage cluster.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_storage_volume():
    """
    Manage the Ceph RBD volumes of the PVC cluster.
    """
    pass


###############################################################################
# > pvc storage volume add
###############################################################################
@click.command(name="add", short_help="Add new RBD volume.")
@connection_req
@click.argument("pool")
@click.argument("name")
@click.argument("size")
def cli_storage_volume_add(pool, name, size):
    """
    Add a new Ceph RBD volume in pool POOL with name NAME and size SIZE (in human units, e.g. 1024M, 20G, etc.).
    """

    retcode, retmsg = pvc.lib.storage.ceph_volume_add(CLI_CONFIG, pool, name, size)
    finish(retcode, retmsg)


###############################################################################
# > pvc storage volume upload
###############################################################################
@click.command(name="upload", short_help="Upload a local image file to RBD volume.")
@connection_req
@click.argument("pool")
@click.argument("name")
@click.argument("image_file")
@click.option(
    "-f",
    "--format",
    "image_format",
    default="raw",
    show_default=True,
    help="The format of the source image.",
)
def cli_storage_volume_upload(pool, name, image_format, image_file):
    """
    Upload a disk image file IMAGE_FILE to the RBD volume NAME in pool POOL.

    The volume NAME must exist in the pool before uploading to it, and must be large enough to fit the disk image in raw format.

    If the image format is "raw", the image is uploaded directly to the target volume without modification. Otherwise, it will be converted into raw format by "qemu-img convert" on the remote side before writing using a temporary volume. The image format must be a valid format recognized by "qemu-img", such as "vmdk" or "qcow2".
    """

    if not path.exists(image_file):
        echo(CLI_CONFIG, "ERROR: File '{}' does not exist!".format(image_file))
        exit(1)

    retcode, retmsg = pvc.lib.storage.ceph_volume_upload(
        CLI_CONFIG, pool, name, image_format, image_file
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc storage volume remove
###############################################################################
@click.command(name="remove", short_help="Remove RBD volume.")
@connection_req
@click.argument("pool")
@click.argument("name")
@confirm_opt("Remove and delete data of RBD volume {name} in pool {pool}")
def cli_storage_volume_remove(pool, name):
    """
    Remove a Ceph RBD volume with name NAME from pool POOL.

    DANGER: This will completely remove the volume and all data contained in it.
    """

    retcode, retmsg = pvc.lib.storage.ceph_volume_remove(CLI_CONFIG, pool, name)
    finish(retcode, retmsg)


###############################################################################
# > pvc storage volume resize
###############################################################################
@click.command(name="resize", short_help="Resize RBD volume.")
@connection_req
@click.argument("pool")
@click.argument("name")
@click.argument("size")
@confirm_opt("Resize volume {name} in pool {pool} to size {size}")
def cli_storage_volume_resize(pool, name, size):
    """
    Resize an existing Ceph RBD volume with name NAME in pool POOL to size SIZE (in human units, e.g. 1024M, 20G, etc.).
    """

    retcode, retmsg = pvc.lib.storage.ceph_volume_modify(
        CLI_CONFIG, pool, name, new_size=size
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc storage volume rename
###############################################################################
@click.command(name="rename", short_help="Rename RBD volume.")
@connection_req
@click.argument("pool")
@click.argument("name")
@click.argument("new_name")
@confirm_opt("Rename volume {name} in pool {pool} to {new_name}")
def cli_storage_volume_rename(pool, name, new_name):
    """
    Rename an existing Ceph RBD volume with name NAME in pool POOL to name NEW_NAME.
    """

    retcode, retmsg = pvc.lib.storage.ceph_volume_modify(
        CLI_CONFIG, pool, name, new_name=new_name
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc storage volume clone
###############################################################################
@click.command(name="clone", short_help="Clone RBD volume.")
@connection_req
@click.argument("pool")
@click.argument("name")
@click.argument("new_name")
def cli_storage_volume_clone(pool, name, new_name):
    """
    Clone a Ceph RBD volume with name NAME in pool POOL to name NEW_NAME in pool POOL.
    """

    retcode, retmsg = pvc.lib.storage.ceph_volume_clone(
        CLI_CONFIG, pool, name, new_name
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc storage volume info
###############################################################################
# Not implemented


###############################################################################
# > pvc storage volume list
###############################################################################
@click.command(name="list", short_help="List cluster RBD volumes.")
@connection_req
@click.argument("limit", default=None, required=False)
@click.option(
    "-p",
    "--pool",
    "pool",
    default=None,
    show_default=True,
    help="Show volumes from this pool only.",
)
@format_opt(
    {
        "pretty": cli_storage_volume_list_format_pretty,
        "raw": lambda d: "\n".join([f"{v['pool']}/{v['name']}" for v in d]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_storage_volume_list(limit, pool, format_function):
    """
    List all Ceph RBD volumes; optionally only match elements matching name regex LIMIT.
    """

    retcode, retdata = pvc.lib.storage.ceph_volume_list(CLI_CONFIG, limit, pool)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc storage volume snapshot
###############################################################################
@click.group(
    name="snapshot",
    short_help="Manage RBD volume snapshots in the PVC storage cluster.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_storage_volume_snapshot():
    """
    Manage the Ceph RBD volume snapshots of the PVC cluster.
    """
    pass


###############################################################################
# > pvc storage volume snapshot add
###############################################################################
@click.command(name="add", short_help="Add new RBD volume snapshot.")
@connection_req
@click.argument("pool")
@click.argument("volume")
@click.argument("name")
def cli_storage_volume_snapshot_add(pool, volume, name):
    """
    Add a snapshot with name NAME of Ceph RBD volume VOLUME in pool POOL.
    """

    retcode, retmsg = pvc.lib.storage.ceph_snapshot_add(CLI_CONFIG, pool, volume, name)
    finish(retcode, retmsg)


###############################################################################
# > pvc storage volume snapshot rename
###############################################################################
@click.command(name="rename", short_help="Rename RBD volume snapshot.")
@connection_req
@click.argument("pool")
@click.argument("volume")
@click.argument("name")
@click.argument("new_name")
def cli_storage_volume_snapshot_rename(pool, volume, name, new_name):
    """
    Rename an existing Ceph RBD volume snapshot with name NAME to name NEW_NAME for volume VOLUME in pool POOL.
    """
    retcode, retmsg = pvc.lib.storage.ceph_snapshot_modify(
        CLI_CONFIG, pool, volume, name, new_name=new_name
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc storage volume snapshot remove
###############################################################################
@click.command(name="remove", short_help="Remove RBD volume snapshot.")
@connection_req
@click.argument("pool")
@click.argument("volume")
@click.argument("name")
@confirm_opt("Remove snapshot {name} for volume {pool}/{volume}")
def cli_storage_volume_snapshot_remove(pool, volume, name):
    """
    Remove a Ceph RBD volume snapshot with name NAME from volume VOLUME in pool POOL.

    DANGER: This will completely remove the snapshot.
    """

    retcode, retmsg = pvc.lib.storage.ceph_snapshot_remove(
        CLI_CONFIG, pool, volume, name
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc storage volume snapshot list
###############################################################################
@click.command(name="list", short_help="List cluster RBD volume shapshots.")
@connection_req
@click.argument("limit", default=None, required=False)
@click.option(
    "-p",
    "--pool",
    "pool",
    default=None,
    show_default=True,
    help="Show snapshots from this pool only.",
)
@click.option(
    "-o",
    "--volume",
    "volume",
    default=None,
    show_default=True,
    help="Show snapshots from this volume only.",
)
@format_opt(
    {
        "pretty": cli_storage_snapshot_list_format_pretty,
        "raw": lambda d: " ".join(
            [f"{s['pool']}/{s['volume']}@{s['snapshot']}" for s in d]
        ),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_storage_volume_snapshot_list(pool, volume, limit, format_function):
    """
    List all Ceph RBD volume snapshots; optionally only match elements matching name regex LIMIT.
    """

    retcode, retdata = pvc.lib.storage.ceph_snapshot_list(
        CLI_CONFIG, limit, volume, pool
    )
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc provisioner
###############################################################################
@click.group(
    name="provisioner",
    short_help="Manage PVC provisioners.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_provisioner():
    """
    Manage and view the provisioner for a PVC cluster.
    """
    pass


###############################################################################
# > pvc provisioner template
###############################################################################
@click.group(
    name="template",
    short_help="Manage PVC provisioner templates.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_provisioner_template():
    """
    Manage the PVC provisioner template system.
    """
    pass


###############################################################################
# > pvc provisioner template system
###############################################################################
@click.group(
    name="system",
    short_help="Manage PVC provisioner system templates.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_provisioner_template_system():
    """
    Manage the PVC provisioner system templates.
    """
    pass


###############################################################################
# > pvc provisioner template system add
###############################################################################
@click.command(name="add", short_help="Add new system template.")
@connection_req
@click.argument("name")
@click.option(
    "-u", "--vcpus", "vcpus", required=True, type=int, help="The number of vCPUs."
)
@click.option(
    "-m", "--vram", "vram", required=True, type=int, help="The amount of vRAM (in MB)."
)
@click.option(
    "-s/-S",
    "--serial/--no-serial",
    "serial",
    is_flag=True,
    default=False,
    help="Enable the virtual serial console.",
)
@click.option(
    "-n/-N",
    "--vnc/--no-vnc",
    "vnc",
    is_flag=True,
    default=False,
    help="Enable/disable the VNC console.",
)
@click.option(
    "-b",
    "--vnc-bind",
    "vnc_bind",
    default=None,
    help="Bind VNC to this IP address instead of localhost.",
)
@click.option(
    "--node-limit",
    "node_limit",
    default=None,
    help="Limit VM operation to this CSV list of node(s).",
)
@click.option(
    "--node-selector",
    "node_selector",
    type=click.Choice(
        ["mem", "memprov", "vcpus", "vms", "load", "none"], case_sensitive=False
    ),
    default="none",
    help='Method to determine optimal target node during autoselect; "none" will use the default for the cluster.',
)
@click.option(
    "--node-autostart",
    "node_autostart",
    is_flag=True,
    default=False,
    help="Autostart VM with their parent Node on first/next boot.",
)
@click.option(
    "--migration-method",
    "migration_method",
    type=click.Choice(["none", "live", "shutdown"], case_sensitive=False),
    default=None,  # Use cluster default
    help="The preferred migration method of the VM between nodes",
)
def cli_provisioner_template_system_add(
    name,
    vcpus,
    vram,
    serial,
    vnc,
    vnc_bind,
    node_limit,
    node_selector,
    node_autostart,
    migration_method,
):
    """
    Add a new system template NAME to the PVC cluster provisioner.

    For details on the possible "--node-selector" values, please see help for the command "pvc vm define".
    """
    params = dict()
    params["name"] = name
    params["vcpus"] = vcpus
    params["vram"] = vram
    params["serial"] = serial
    params["vnc"] = vnc
    if vnc:
        params["vnc_bind"] = vnc_bind
    if node_limit:
        params["node_limit"] = node_limit
    if node_selector:
        params["node_selector"] = node_selector
    if node_autostart:
        params["node_autostart"] = node_autostart
    if migration_method:
        params["migration_method"] = migration_method

    retcode, retdata = pvc.lib.provisioner.template_add(
        CLI_CONFIG, params, template_type="system"
    )
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner template system modify
###############################################################################
@click.command(name="modify", short_help="Modify an existing system template.")
@connection_req
@click.argument("name")
@click.option("-u", "--vcpus", "vcpus", type=int, help="The number of vCPUs.")
@click.option("-m", "--vram", "vram", type=int, help="The amount of vRAM (in MB).")
@click.option(
    "-s/-S",
    "--serial/--no-serial",
    "serial",
    is_flag=True,
    default=None,
    help="Enable the virtual serial console.",
)
@click.option(
    "-n/-N",
    "--vnc/--no-vnc",
    "vnc",
    is_flag=True,
    default=None,
    help="Enable/disable the VNC console.",
)
@click.option(
    "-b",
    "--vnc-bind",
    "vnc_bind",
    help="Bind VNC to this IP address instead of localhost.",
)
@click.option(
    "--node-limit", "node_limit", help="Limit VM operation to this CSV list of node(s)."
)
@click.option(
    "--node-selector",
    "node_selector",
    type=click.Choice(
        ["mem", "memprov", "vcpus", "vms", "load", "none"], case_sensitive=False
    ),
    help='Method to determine optimal target node during autoselect; "none" will use the default for the cluster.',
)
@click.option(
    "--node-autostart",
    "node_autostart",
    is_flag=True,
    default=None,
    help="Autostart VM with their parent Node on first/next boot.",
)
@click.option(
    "--migration-method",
    "migration_method",
    type=click.Choice(["none", "live", "shutdown"], case_sensitive=False),
    default=None,  # Use cluster default
    help="The preferred migration method of the VM between nodes",
)
def cli_provisioner_template_system_modify(
    name,
    vcpus,
    vram,
    serial,
    vnc,
    vnc_bind,
    node_limit,
    node_selector,
    node_autostart,
    migration_method,
):
    """
    Add a new system template NAME to the PVC cluster provisioner.

    For details on the possible "--node-selector" values, please see help for the command "pvc vm define".
    """
    params = dict()
    params["vcpus"] = vcpus
    params["vram"] = vram
    params["serial"] = serial
    params["vnc"] = vnc
    params["vnc_bind"] = vnc_bind
    params["node_limit"] = node_limit
    params["node_selector"] = node_selector
    params["node_autostart"] = node_autostart
    params["migration_method"] = migration_method

    retcode, retdata = pvc.lib.provisioner.template_modify(
        CLI_CONFIG, params, name, template_type="system"
    )
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner template system remove
###############################################################################
@click.command(name="remove", short_help="Remove system template.")
@connection_req
@click.argument("name")
@confirm_opt("Remove system template {name}")
def cli_provisioner_template_system_remove(name):
    """
    Remove system template NAME from the PVC cluster provisioner.
    """

    retcode, retdata = pvc.lib.provisioner.template_remove(
        CLI_CONFIG, name, template_type="system"
    )
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner template system list
###############################################################################
@click.command(name="list", short_help="List all system templates.")
@connection_req
@click.argument("limit", default=None, required=False)
@format_opt(
    {
        "pretty": cli_provisioner_template_system_list_format_pretty,
        "raw": lambda d: "\n".join([t["name"] for t in d]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_provisioner_template_system_list(limit, format_function):
    """
    List all system templates in the PVC cluster provisioner.
    """
    retcode, retdata = pvc.lib.provisioner.template_list(
        CLI_CONFIG, limit, template_type="system"
    )
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc provisioner template network
###############################################################################
@click.group(
    name="network",
    short_help="Manage PVC provisioner network templates.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_provisioner_template_network():
    """
    Manage the PVC provisioner network templates.
    """
    pass


###############################################################################
# > pvc provisioner template network add
###############################################################################
@click.command(name="add", short_help="Add new network template.")
@connection_req
@click.argument("name")
@click.option(
    "-m",
    "--mac-template",
    "mac_template",
    default=None,
    help="Use this template for MAC addresses.",
)
def cli_provisioner_template_network_add(name, mac_template):
    """
    Add a new network template to the PVC cluster provisioner.

    MAC address templates are used to provide predictable MAC addresses for provisioned VMs.
    The normal format of a MAC template is:

      {prefix}:XX:XX:{vmid}{netid}

    The {prefix} variable is replaced by the provisioner with a standard prefix ("52:54:01"),
    which is different from the randomly-generated MAC prefix ("52:54:00") to avoid accidental
    overlap of MAC addresses.

    The {vmid} variable is replaced by a single hexidecimal digit representing the VM's ID,
    the numerical suffix portion of its name; VMs without a suffix numeral have ID 0. VMs with
    IDs greater than 15 (hexidecimal "f") will wrap back to 0.

    The {netid} variable is replaced by the sequential identifier, starting at 0, of the
    network VNI of the interface; for example, the first interface is 0, the second is 1, etc.

    The four X digits are use-configurable. Use these digits to uniquely define the MAC
    address.

    Example: pvc provisioner template network add --mac-template "{prefix}:2f:1f:{vmid}{netid}" test-template

    The location of the two per-VM variables can be adjusted at the administrator's discretion,
    or removed if not required (e.g. a single-network template, or template for a single VM).
    In such situations, be careful to avoid accidental overlap with other templates' variable
    portions.
    """
    params = dict()
    params["name"] = name
    params["mac_template"] = mac_template

    retcode, retdata = pvc.lib.provisioner.template_add(
        CLI_CONFIG, params, template_type="network"
    )
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner template network modify
###############################################################################
# Not implemented


###############################################################################
# > pvc provisioner template network remove
###############################################################################
@click.command(name="remove", short_help="Remove network template.")
@connection_req
@click.argument("name")
@confirm_opt("Remove network template {name}")
def cli_provisioner_template_network_remove(name):
    """
    Remove network template MAME from the PVC cluster provisioner.
    """

    retcode, retdata = pvc.lib.provisioner.template_remove(
        CLI_CONFIG, name, template_type="network"
    )
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner template network list
###############################################################################
@click.command(name="list", short_help="List all network templates.")
@connection_req
@click.argument("limit", default=None, required=False)
@format_opt(
    {
        "pretty": cli_provisioner_template_network_list_format_pretty,
        "raw": lambda d: "\n".join([t["name"] for t in d]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_provisioner_template_network_list(limit, format_function):
    """
    List all network templates in the PVC cluster provisioner.
    """
    retcode, retdata = pvc.lib.provisioner.template_list(
        CLI_CONFIG, limit, template_type="network"
    )
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc provisioner template network vni
###############################################################################
@click.group(
    name="vni",
    short_help="Manage PVC provisioner network template VNIs.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_provisioner_template_network_vni():
    """
    Manage the network VNIs in PVC provisioner network templates.
    """
    pass


###############################################################################
# > pvc provisioner template network vni add
###############################################################################
@click.command(name="add", short_help="Add network VNI to network template.")
@connection_req
@click.argument("name")
@click.argument("vni")
def cli_provisioner_template_network_vni_add(name, vni):
    """
    Add a new network VNI to network template NAME.

    Networks will be added to VMs in the order they are added and displayed within the template.
    """
    params = dict()

    retcode, retdata = pvc.lib.provisioner.template_element_add(
        CLI_CONFIG, name, vni, params, element_type="net", template_type="network"
    )
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner template network vni remove
###############################################################################
@click.command(name="remove", short_help="Remove network VNI from network template.")
@connection_req
@click.argument("name")
@click.argument("vni")
@confirm_opt("Remove VNI {vni} from network template {name}")
def cli_provisioner_template_network_vni_remove(name, vni):
    """
    Remove network VNI from network template NAME.
    """

    retcode, retdata = pvc.lib.provisioner.template_element_remove(
        CLI_CONFIG, name, vni, element_type="net", template_type="network"
    )
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner template storage
###############################################################################
@click.group(
    name="storage",
    short_help="Manage PVC provisioner storage templates.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_provisioner_template_storage():
    """
    Manage the PVC provisioner storage templates.
    """
    pass


###############################################################################
# > pvc provisioner template storage add
###############################################################################
@click.command(name="add", short_help="Add new storage template.")
@connection_req
@click.argument("name")
def cli_provisioner_template_storage_add(name):
    """
    Add a new storage template to the PVC cluster provisioner.
    """
    params = dict()
    params["name"] = name

    retcode, retdata = pvc.lib.provisioner.template_add(
        CLI_CONFIG, params, template_type="storage"
    )
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner template storage modify
###############################################################################
# Not implemented


###############################################################################
# > pvc provisioner template storage remove
###############################################################################
@click.command(name="remove", short_help="Remove storage template.")
@connection_req
@click.argument("name")
@confirm_opt("Remove storage template {name}")
def cli_provisioner_template_storage_remove(name):
    """
    Remove storage template NAME from the PVC cluster provisioner.
    """

    retcode, retdata = pvc.lib.provisioner.template_remove(
        CLI_CONFIG, name, template_type="storage"
    )
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner template storage list
###############################################################################
@click.command(name="list", short_help="List all storage templates.")
@connection_req
@click.argument("limit", default=None, required=False)
@format_opt(
    {
        "pretty": cli_provisioner_template_storage_list_format_pretty,
        "raw": lambda d: "\n".join([t["name"] for t in d]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_provisioner_template_storage_list(limit, format_function):
    """
    List all storage templates in the PVC cluster provisioner.
    """
    retcode, retdata = pvc.lib.provisioner.template_list(
        CLI_CONFIG, limit, template_type="storage"
    )
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc provisioner template storage disk
###############################################################################
@click.group(
    name="disk",
    short_help="Manage PVC provisioner storage template disks.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_provisioner_template_storage_disk():
    """
    Manage the disks in PVC provisioner storage templates.
    """
    pass


###############################################################################
# > pvc provisioner template storage disk add
###############################################################################
@click.command(name="add", short_help="Add disk to storage template.")
@connection_req
@click.argument("name")
@click.argument("disk")
@click.option(
    "-p", "--pool", "pool", required=True, help="The storage pool for the disk."
)
@click.option(
    "-i",
    "--source-volume",
    "source_volume",
    default=None,
    help="The source volume to clone",
)
@click.option(
    "-s", "--size", "size", type=int, default=None, help="The size of the disk (in GB)."
)
@click.option(
    "-f", "--filesystem", "filesystem", default=None, help="The filesystem of the disk."
)
@click.option(
    "--fsarg",
    "fsargs",
    default=None,
    multiple=True,
    help="Additional argument for filesystem creation, in arg=value format without leading dashes.",
)
@click.option(
    "-m",
    "--mountpoint",
    "mountpoint",
    default=None,
    help="The target Linux mountpoint of the disk; requires a filesystem.",
)
def cli_provisioner_template_storage_disk_add(
    name, disk, pool, source_volume, size, filesystem, fsargs, mountpoint
):
    """
    Add a new DISK to storage template NAME.

    DISK must be a Linux-style sdX/vdX disk identifier, such as "sda" or "vdb". All disks in a template must use the same identifier format.

    Disks will be added to VMs in sdX/vdX order. For disks with mountpoints, ensure this order is sensible.
    """

    if source_volume and (size or filesystem or mountpoint):
        echo(
            CLI_CONFIG,
            'The "--source-volume" option is not compatible with the "--size", "--filesystem", or "--mountpoint" options.',
        )
        exit(1)

    params = dict()
    params["pool"] = pool
    params["source_volume"] = source_volume
    params["disk_size"] = size
    if filesystem:
        params["filesystem"] = filesystem
    if filesystem and fsargs:
        dash_fsargs = list()
        for arg in fsargs:
            arg_len = len(arg.split("=")[0])
            if arg_len == 1:
                dash_fsargs.append("-" + arg)
            else:
                dash_fsargs.append("--" + arg)
        params["filesystem_arg"] = dash_fsargs
    if filesystem and mountpoint:
        params["mountpoint"] = mountpoint

    retcode, retdata = pvc.lib.provisioner.template_element_add(
        CLI_CONFIG, name, disk, params, element_type="disk", template_type="storage"
    )
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner template storage disk remove
###############################################################################
@click.command(name="remove", short_help="Remove disk from storage template.")
@connection_req
@click.argument("name")
@click.argument("disk")
@confirm_opt("Remove disk {disk} from storage template {name}")
def cli_provisioner_template_storage_disk_remove(name, disk):
    """
    Remove DISK from storage template NAME.

    DISK must be a Linux-style disk identifier such as "sda" or "vdb".
    """

    retcode, retdata = pvc.lib.provisioner.template_element_remove(
        CLI_CONFIG, name, disk, element_type="disk", template_type="storage"
    )
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner userdata
###############################################################################
@click.group(
    name="userdata",
    short_help="Manage PVC provisioner userdata documents.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_provisioner_userdata():
    """
    Manage userdata documents in the PVC provisioner.
    """
    pass


###############################################################################
# > pvc provisioner userdata add
###############################################################################
@click.command(name="add", short_help="Define userdata document from file.")
@connection_req
@click.argument("name")
@click.argument("filename", type=click.File())
def cli_provisioner_userdata_add(name, filename):
    """
    Add a new userdata document NAME from file FILENAME.
    """

    # Open the YAML file
    userdata = filename.read()
    filename.close()
    try:
        yload(userdata, Loader=SafeYAMLLoader)
    except Exception as e:
        echo(CLI_CONFIG, "Error: Userdata document is malformed")
        cleanup(False, e)

    params = dict()
    params["name"] = name
    params["data"] = userdata.strip()

    retcode, retmsg = pvc.lib.provisioner.userdata_add(CLI_CONFIG, params)
    finish(retcode, retmsg)


###############################################################################
# > pvc provisioner userdata modify
###############################################################################
@click.command(name="modify", short_help="Modify existing userdata document.")
@connection_req
@click.option(
    "-e",
    "--editor",
    "editor",
    is_flag=True,
    help="Use local editor to modify existing document.",
)
@click.argument("name")
@click.argument("filename", type=click.File(), default=None, required=False)
def cli_provisioner_userdata_modify(name, filename, editor):
    """
    Modify existing userdata document NAME, either in-editor or with replacement FILE.
    """

    if editor is False and filename is None:
        finish(False, 'Either a file or the "--editor" option must be specified.')

    if editor is True:
        # Grab the current config
        retcode, retdata = pvc.lib.provisioner.userdata_info(CLI_CONFIG, name)
        if not retcode:
            echo(CLI_CONFIG, retdata)
            exit(1)
        current_userdata = retdata["userdata"].strip()

        new_userdata = click.edit(
            text=current_userdata, require_save=True, extension=".yaml"
        )
        if new_userdata is None:
            echo(CLI_CONFIG, "Aborting with no modifications.")
            exit(0)
        else:
            new_userdata = new_userdata.strip()

        # Show a diff and confirm
        diff = list(
            unified_diff(
                current_userdata.split("\n"),
                new_userdata.split("\n"),
                fromfile="current",
                tofile="modified",
                fromfiledate="",
                tofiledate="",
                n=3,
                lineterm="",
            )
        )
        if len(diff) < 1:
            echo(CLI_CONFIG, "Aborting with no modifications.")
            exit(0)

        echo(CLI_CONFIG, "Pending modifications:")
        echo(CLI_CONFIG, "")
        for line in diff:
            if match(r"^\+", line) is not None:
                echo(CLI_CONFIG, Fore.GREEN + line + Fore.RESET)
            elif match(r"^\-", line) is not None:
                echo(CLI_CONFIG, Fore.RED + line + Fore.RESET)
            elif match(r"^\^", line) is not None:
                echo(CLI_CONFIG, Fore.BLUE + line + Fore.RESET)
            else:
                echo(CLI_CONFIG, line)
        echo(CLI_CONFIG, "")

        click.confirm("Write modifications to cluster?", abort=True)

        userdata = new_userdata

    # We're operating in replace mode
    else:
        # Open the new file
        userdata = filename.read().strip()
        filename.close()

    try:
        yload(userdata, Loader=SafeYAMLLoader)
    except Exception as e:
        echo(CLI_CONFIG, "Error: Userdata document is malformed")
        cleanup(False, e)

    params = dict()
    params["data"] = userdata

    retcode, retmsg = pvc.lib.provisioner.userdata_modify(CLI_CONFIG, name, params)
    finish(retcode, retmsg)


###############################################################################
# > pvc provisioner userdata remove
###############################################################################
@click.command(name="remove", short_help="Remove userdata document.")
@connection_req
@click.argument("name")
@confirm_opt("Remove userdata document {name}")
def cli_provisioner_userdata_remove(name):
    """
    Remove userdata document NAME from the PVC cluster provisioner.
    """

    retcode, retdata = pvc.lib.provisioner.userdata_remove(CLI_CONFIG, name)
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner userdata show
###############################################################################
@click.command(name="show", short_help="Show contents of userdata documents.")
@connection_req
@click.argument("name")
def cli_provisioner_userdata_show(name):
    """
    Show the full contents of userdata document NAME.
    """

    retcode, retdata = pvc.lib.provisioner.userdata_show(CLI_CONFIG, name)
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner userdata list
###############################################################################
@click.command(name="list", short_help="List all userdata documents.")
@connection_req
@click.argument("limit", default=None, required=False)
@click.option(
    "-l",
    "--long",
    "long_output",
    is_flag=True,
    default=False,
    help="Show all lines of the document instead of first 4 ('pretty' format only).",
)
@format_opt(
    {
        "pretty": cli_provisioner_userdata_list_format_pretty,
        "raw": lambda d: "\n".join([u["name"] for u in d]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_provisioner_userdata_list(limit, long_output, format_function):
    """
    List all userdata documents in the PVC cluster provisioner.
    """

    retcode, retdata = pvc.lib.provisioner.userdata_list(CLI_CONFIG, limit)
    CLI_CONFIG["long_output"] = long_output
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc provisioner script
###############################################################################
@click.group(
    name="script",
    short_help="Manage PVC provisioner scripts.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_provisioner_script():
    """
    Manage scripts in the PVC provisioner.
    """
    pass


###############################################################################
# > pvc provisioner script add
###############################################################################
@click.command(name="add", short_help="Define script from file.")
@connection_req
@click.argument("name")
@click.argument("filename", type=click.File())
def cli_provisioner_script_add(name, filename):
    """
    Add a new script NAME from file FILENAME.
    """

    # Open the XML file
    script = filename.read()
    filename.close()

    params = dict()
    params["name"] = name
    params["data"] = script.strip()

    retcode, retmsg = pvc.lib.provisioner.script_add(CLI_CONFIG, params)
    finish(retcode, retmsg)


###############################################################################
# > pvc provisioner script modify
###############################################################################
@click.command(name="modify", short_help="Modify existing script.")
@connection_req
@click.option(
    "-e",
    "--editor",
    "editor",
    is_flag=True,
    help="Use local editor to modify existing document.",
)
@click.argument("name")
@click.argument("filename", type=click.File(), default=None, required=False)
def cli_provisioner_script_modify(name, filename, editor):
    """
    Modify existing script NAME, either in-editor or with replacement FILE.
    """

    if editor is False and filename is None:
        finish(False, 'Either a file or the "--editor" option must be specified.')

    if editor is True:
        # Grab the current config
        retcode, retdata = pvc.lib.provisioner.script_info(CLI_CONFIG, name)
        if not retcode:
            echo(CLI_CONFIG, retdata)
            exit(1)
        current_script = retdata["script"].strip()

        new_script = click.edit(text=current_script, require_save=True, extension=".py")
        if new_script is None:
            echo(CLI_CONFIG, "Aborting with no modifications.")
            exit(0)
        else:
            new_script = new_script.strip()

        # Show a diff and confirm
        diff = list(
            unified_diff(
                current_script.split("\n"),
                new_script.split("\n"),
                fromfile="current",
                tofile="modified",
                fromfiledate="",
                tofiledate="",
                n=3,
                lineterm="",
            )
        )
        if len(diff) < 1:
            echo(CLI_CONFIG, "Aborting with no modifications.")
            exit(0)

        echo(CLI_CONFIG, "Pending modifications:")
        echo(CLI_CONFIG, "")
        for line in diff:
            if match(r"^\+", line) is not None:
                echo(CLI_CONFIG, Fore.GREEN + line + Fore.RESET)
            elif match(r"^\-", line) is not None:
                echo(CLI_CONFIG, Fore.RED + line + Fore.RESET)
            elif match(r"^\^", line) is not None:
                echo(CLI_CONFIG, Fore.BLUE + line + Fore.RESET)
            else:
                echo(CLI_CONFIG, line)
        echo(CLI_CONFIG, "")

        click.confirm("Write modifications to cluster?", abort=True)

        script = new_script

    # We're operating in replace mode
    else:
        # Open the new file
        script = filename.read().strip()
        filename.close()

    params = dict()
    params["data"] = script

    retcode, retmsg = pvc.lib.provisioner.script_modify(CLI_CONFIG, name, params)
    finish(retcode, retmsg)


###############################################################################
# > pvc provisioner script remove
###############################################################################
@click.command(name="remove", short_help="Remove script.")
@connection_req
@click.argument("name")
@confirm_opt("Remove provisioning script {name}")
def cli_provisioner_script_remove(name):
    """
    Remove script NAME from the PVC cluster provisioner.
    """

    retcode, retdata = pvc.lib.provisioner.script_remove(CLI_CONFIG, name)
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner script show
###############################################################################
@click.command(name="show", short_help="Show contents of script documents.")
@connection_req
@click.argument("name")
def cli_provisioner_script_show(name):
    """
    Show the full contents of script document NAME.
    """

    retcode, retdata = pvc.lib.provisioner.script_show(CLI_CONFIG, name)
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner script list
###############################################################################
@click.command(name="list", short_help="List all scripts.")
@connection_req
@click.argument("limit", default=None, required=False)
@click.option(
    "-l",
    "--long",
    "long_output",
    is_flag=True,
    default=False,
    help="Show all lines of the document instead of first 4 ('pretty' format only).",
)
@format_opt(
    {
        "pretty": cli_provisioner_script_list_format_pretty,
        "raw": lambda d: "\n".join([s["name"] for s in d]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_provisioner_script_list(limit, long_output, format_function):
    """
    List all scripts in the PVC cluster provisioner.
    """

    retcode, retdata = pvc.lib.provisioner.script_list(CLI_CONFIG, limit)
    CLI_CONFIG["long_output"] = long_output
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc provisioner ova
###############################################################################
@click.group(
    name="ova",
    short_help="Manage PVC provisioner OVA images.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_provisioner_ova():
    """
    Manage ovas in the PVC provisioner.
    """
    pass


###############################################################################
# > pvc provisioner ova upload
###############################################################################
@click.command(name="upload", short_help="Upload OVA file.")
@connection_req
@click.argument("name")
@click.argument("filename")
@click.option(
    "-p", "--pool", "pool", required=True, help="The storage pool for the OVA images."
)
def cli_provisioner_ova_upload(name, filename, pool):
    """
    Upload a new OVA image NAME from FILENAME.

    Only single-file (.ova) OVA/OVF images are supported. For multi-file (.ovf + .vmdk) OVF images, concatenate them with "tar" then upload the resulting file.

    Once uploaded, a provisioner system template and OVA-type profile, each named NAME, will be created to store the configuration of the OVA.

    Note that the provisioner profile for the OVA will not contain any network template definitions, and will ignore network definitions from the OVA itself. The administrator must modify the profile's network template as appropriate to set the desired network configuration.

    Storage templates, provisioning scripts, and arguments for OVA-type profiles will be ignored and should not be set.
    """

    if not path.exists(filename):
        echo(CLI_CONFIG, "ERROR: File '{}' does not exist!".format(filename))
        exit(1)

    params = dict()
    params["pool"] = pool
    params["ova_size"] = path.getsize(filename)

    retcode, retdata = pvc.lib.provisioner.ova_upload(
        CLI_CONFIG, name, filename, params
    )
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner ova remove
###############################################################################
@click.command(name="remove", short_help="Remove OVA image.")
@connection_req
@click.argument("name")
@confirm_opt("Remove OVA image {name}")
def cli_provisioner_ova_remove(name):
    """
    Remove OVA image NAME from the PVC cluster provisioner.
    """

    retcode, retdata = pvc.lib.provisioner.ova_remove(CLI_CONFIG, name)
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner ova info
###############################################################################
# Not implemented


###############################################################################
# > pvc provisioner ova list
###############################################################################
@click.command(name="list", short_help="List all OVA images.")
@connection_req
@click.argument("limit", default=None, required=False)
@format_opt(
    {
        "pretty": cli_provisioner_ova_list_format_pretty,
        "raw": lambda d: "\n".join([o["name"] for o in d]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_provisioner_ova_list(limit, format_function):
    """
    List all OVA images in the PVC cluster provisioner.
    """

    retcode, retdata = pvc.lib.provisioner.ova_list(CLI_CONFIG, limit)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc provisioner profile
###############################################################################
@click.group(
    name="profile",
    short_help="Manage PVC provisioner profiless.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_provisioner_profile():
    """
    Manage profiles in the PVC provisioner.
    """
    pass


###############################################################################
# > pvc provisioner profile add
###############################################################################
@click.command(name="add", short_help="Add provisioner profile.")
@connection_req
@click.argument("name")
@click.option(
    "-p",
    "--profile-type",
    "profile_type",
    default="provisioner",
    show_default=True,
    type=click.Choice(["provisioner", "ova"], case_sensitive=False),
    help="The type of profile.",
)
@click.option(
    "-s",
    "--system-template",
    "system_template",
    required=True,
    help="The system template for the profile (required).",
)
@click.option(
    "-n",
    "--network-template",
    "network_template",
    help="The network template for the profile.",
)
@click.option(
    "-t",
    "--storage-template",
    "storage_template",
    help="The storage template for the profile.",
)
@click.option(
    "-u",
    "--userdata",
    "userdata",
    help="The userdata document for the profile.",
)
@click.option(
    "-x",
    "--script",
    "script",
    required=True,
    help="The script for the profile (required).",
)
@click.option(
    "-o",
    "--ova",
    "ova",
    help="The OVA image for the profile; set automatically with 'provisioner ova upload'.",
)
@click.option(
    "-a",
    "--script-arg",
    "script_args",
    default=[],
    multiple=True,
    help="Additional argument to the script install() function in key=value format.",
)
def cli_provisioner_profile_add(
    name,
    profile_type,
    system_template,
    network_template,
    storage_template,
    userdata,
    script,
    ova,
    script_args,
):
    """
    Add a new provisioner profile NAME.
    """

    params = dict()
    params["name"] = name
    params["profile_type"] = profile_type
    params["system_template"] = system_template
    params["network_template"] = network_template
    params["storage_template"] = storage_template
    params["userdata"] = userdata
    params["script"] = script
    params["ova"] = ova
    params["arg"] = script_args

    retcode, retdata = pvc.lib.provisioner.profile_add(CLI_CONFIG, params)
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner profile modify
###############################################################################
@click.command(name="modify", short_help="Modify provisioner profile.")
@connection_req
@click.argument("name")
@click.option(
    "-s",
    "--system-template",
    "system_template",
    default=None,
    help="The system template for the profile.",
)
@click.option(
    "-n",
    "--network-template",
    "network_template",
    default=None,
    help="The network template for the profile.",
)
@click.option(
    "-t",
    "--storage-template",
    "storage_template",
    default=None,
    help="The storage template for the profile.",
)
@click.option(
    "-u",
    "--userdata",
    "userdata",
    default=None,
    help="The userdata document for the profile.",
)
@click.option(
    "-x", "--script", "script", default=None, help="The script for the profile."
)
@click.option(
    "-d",
    "--delete-script-args",
    "delete_script_args",
    default=False,
    is_flag=True,
    help="Delete any existing script arguments.",
)
@click.option(
    "-a",
    "--script-arg",
    "script_args",
    default=None,
    multiple=True,
    help="Additional argument to the script install() function in key=value format.",
)
def cli_provisioner_profile_modify(
    name,
    system_template,
    network_template,
    storage_template,
    userdata,
    script,
    delete_script_args,
    script_args,
):
    """
    Modify existing provisioner profile NAME.
    """

    params = dict()
    if system_template is not None:
        params["system_template"] = system_template
    if network_template is not None:
        params["network_template"] = network_template
    if storage_template is not None:
        params["storage_template"] = storage_template
    if userdata is not None:
        params["userdata"] = userdata
    if script is not None:
        params["script"] = script
    if delete_script_args:
        params["arg"] = []
    if script_args is not None:
        params["arg"] = script_args

    retcode, retdata = pvc.lib.provisioner.profile_modify(CLI_CONFIG, name, params)
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner profile remove
###############################################################################
@click.command(name="remove", short_help="Remove profile.")
@connection_req
@click.argument("name")
@confirm_opt("Remove provisioner profile {name}")
def cli_provisioner_profile_remove(name):
    """
    Remove profile NAME from the PVC cluster provisioner.
    """

    retcode, retdata = pvc.lib.provisioner.profile_remove(CLI_CONFIG, name)
    finish(retcode, retdata)


###############################################################################
# > pvc provisioner profile info
###############################################################################
# Not implemented


###############################################################################
# > pvc provisioner profile list
###############################################################################
@click.command(name="list", short_help="List all profiles.")
@connection_req
@click.argument("limit", default=None, required=False)
@format_opt(
    {
        "pretty": cli_provisioner_profile_list_format_pretty,
        "raw": lambda d: "\n".join([o["name"] for o in d]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_provisioner_profile_list(limit, format_function):
    """
    List all profiles in the PVC cluster provisioner.
    """
    retcode, retdata = pvc.lib.provisioner.profile_list(CLI_CONFIG, limit)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc provisioner create
###############################################################################
@click.command(name="create", short_help="Create new VM.")
@connection_req
@click.argument("name")
@click.argument("profile")
@click.option(
    "-a",
    "--script-arg",
    "script_args",
    default=[],
    multiple=True,
    help="Additional argument to the script install() function in key=value format.",
)
@click.option(
    "-d/-D",
    "--define/--no-define",
    "define_flag",
    is_flag=True,
    default=True,
    show_default=True,
    help="Define the VM automatically during provisioning.",
)
@click.option(
    "-s/-S",
    "--start/--no-start",
    "start_flag",
    is_flag=True,
    default=True,
    show_default=True,
    help="Start the VM automatically upon completion of provisioning.",
)
@click.option(
    "--wait/--no-wait",
    "wait_flag",
    is_flag=True,
    default=True,
    show_default=True,
    help="Wait or don't wait for task to complete, showing progress",
)
def cli_provisioner_create(
    name, profile, define_flag, start_flag, script_args, wait_flag
):
    """
    Create a new VM NAME with profile PROFILE.

    The "--no-start" flag can be used to prevent automatic startup of the VM once provisioning
    is completed. This can be useful for the administrator to preform additional actions to
    the VM after provisioning is completed. Note that the VM will remain in "provision" state
    until its state is explicitly changed (e.g. with "pvc vm start").

    The "--no-define" flag implies "--no-start", and can be used to prevent definition of the
    created VM on the PVC cluster. This can be useful for the administrator to create a "template"
    set of VM disks via the normal provisioner, but without ever starting the resulting VM. The
    resulting disk(s) can then be used as source volumes in other disk templates.

    The "--script-arg" option can be specified as many times as required to pass additional,
    VM-specific arguments to the provisioner install() function, beyond those set by the profile.
    """
    if not define_flag:
        start_flag = False

    retcode, retmsg = pvc.lib.provisioner.vm_create(
        CLI_CONFIG, name, profile, define_flag, start_flag, script_args, wait_flag
    )

    if retcode and wait_flag:
        retmsg = wait_for_celery_task(CLI_CONFIG, retmsg)
    finish(retcode, retmsg)


###############################################################################
# > pvc provisioner status
###############################################################################
@click.command(name="status", short_help="Show status of provisioner job.")
@connection_req
@click.argument("job", required=False, default=None)
@format_opt(
    {
        "pretty": cli_provisioner_status_format_pretty,
        "raw": lambda d: "\n".join([t["id"] for t in d])
        if isinstance(d, list)
        else d["state"],
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_provisioner_status(job, format_function):
    """
    Show status of provisioner job JOB or a list of jobs.
    """
    retcode, retdata = pvc.lib.provisioner.task_status(CLI_CONFIG, job)
    finish(retcode, retdata, format_function)


###############################################################################
# > pvc connection
###############################################################################
@click.group(
    name="connection",
    short_help="Manage PVC API connections.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_connection():
    """
    Manage the PVC clusters this CLI client can connect to.
    """
    pass


###############################################################################
# > pvc connection add
###############################################################################
@click.command(
    name="add",
    short_help="Add connections to the client database.",
)
@click.argument("name")
@click.option(
    "-d",
    "--description",
    "description",
    required=False,
    default="N/A",
    help="A text description of the connection.",
)
@click.option(
    "-a",
    "--address",
    "address",
    required=True,
    help="The IP address/hostname of the connection API.",
)
@click.option(
    "-p",
    "--port",
    "port",
    required=False,
    default=7370,
    show_default=True,
    help="The port of the connection API.",
)
@click.option(
    "-k",
    "--api-key",
    "api_key",
    required=False,
    default=None,
    help="An API key to use for authentication, if required.",
)
@click.option(
    "-s/-S",
    "--ssl/--no-ssl",
    "ssl_flag",
    is_flag=True,
    default=False,
    help="Whether or not to use SSL for the API connection.  [default: False]",
)
def cli_connection_add(
    name,
    description,
    address,
    port,
    api_key,
    ssl_flag,
):
    """
    Add the PVC connection NAME to the database of the local CLI client.

    Adding a connection with an existing NAME will replace the existing connection.
    """

    # Set the scheme based on {ssl_flag}
    scheme = "https" if ssl_flag else "http"

    # Get the store data
    connections_config = get_store(CLI_CONFIG["store_path"])

    # Add (or update) the new connection details
    connections_config[name] = {
        "description": description,
        "host": address,
        "port": port,
        "scheme": scheme,
        "api_key": api_key,
    }

    # Update the store data
    update_store(CLI_CONFIG["store_path"], connections_config)

    finish(
        True,
        f"""Added connection "{name}" ({scheme}://{address}:{port}) to client database""",
    )


###############################################################################
# > pvc connection remove
###############################################################################
@click.command(
    name="remove",
    short_help="Remove connections from the client database.",
)
@click.argument("name")
def cli_connection_remove(
    name,
):
    """
    Remove the PVC connection NAME from the database of the local CLI client.
    """

    # Get the store data
    connections_config = get_store(CLI_CONFIG["store_path"])

    # Remove the entry matching the name
    try:
        connections_config.pop(name)
    except KeyError:
        finish(False, f"""No connection found with name "{name}" in local database""")

    # Update the store data
    update_store(CLI_CONFIG["store_path"], connections_config)

    finish(True, f"""Removed connection "{name}" from client database""")


###############################################################################
# > pvc connection list
###############################################################################
@click.command(
    name="list",
    short_help="List connections in the client database.",
)
@click.option(
    "-k",
    "--show-keys",
    "show_keys_flag",
    is_flag=True,
    default=False,
    help="Show secure API keys.",
)
@format_opt(
    {
        "pretty": cli_connection_list_format_pretty,
        "raw": lambda d: "\n".join([c["name"] for c in d]),
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_connection_list(
    show_keys_flag,
    format_function,
):
    """
    List all PVC connections in the database of the local CLI client.

    \b
    Format options:
        "pretty": Output all details in a nice tabular list format.
        "raw": Output connection names one per line.
        "json": Output in unformatted JSON.
        "json-pretty": Output in formatted JSON.
    """

    connections_config = get_store(CLI_CONFIG["store_path"])
    connections_data = cli_connection_list_parser(connections_config, show_keys_flag)
    finish(True, connections_data, format_function)


###############################################################################
# > pvc connection detail
###############################################################################
@click.command(
    name="detail",
    short_help="List status of all connections in the client database.",
)
@format_opt(
    {
        "pretty": cli_connection_detail_format_pretty,
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
def cli_connection_detail(
    format_function,
):
    """
    List the status and information of all PVC cluster in the database of the local CLI client.

    \b
    Format options:
        "pretty": Output a nice tabular list of all details.
        "json": Output in unformatted JSON.
        "json-pretty": Output in formatted JSON.
    """

    echo(
        CLI_CONFIG,
        "Gathering information from all clusters... ",
        newline=False,
        stderr=True,
    )
    connections_config = get_store(CLI_CONFIG["store_path"])
    connections_data = cli_connection_detail_parser(connections_config)
    echo(CLI_CONFIG, "done.", stderr=True)
    echo(CLI_CONFIG, "", stderr=True)
    finish(True, connections_data, format_function)


###############################################################################
# > pvc
###############################################################################
@click.group(context_settings=CONTEXT_SETTINGS)
@click.option(
    "-c",
    "--connection",
    "_connection",
    envvar="PVC_CONNECTION",
    default=None,
    help="Cluster to connect to.",
)
@click.option(
    "-v",
    "--debug",
    "_debug",
    envvar="PVC_DEBUG",
    is_flag=True,
    default=False,
    help="Additional debug details.",
)
@click.option(
    "-q",
    "--quiet",
    "_quiet",
    envvar="PVC_QUIET",
    is_flag=True,
    default=False,
    help="Suppress information sent to stderr.",
)
@click.option(
    "-s",
    "--silent",
    "_silent",
    envvar="PVC_SILENT",
    is_flag=True,
    default=False,
    help="Suppress information sent to stdout and stderr.",
)
@click.option(
    "-u",
    "--unsafe",
    "_unsafe",
    envvar="PVC_UNSAFE",
    is_flag=True,
    default=False,
    help='Perform unsafe operations without confirmation/"--yes" argument.',
)
@click.option(
    "--colour",
    "--color",
    "_colour",
    envvar="PVC_COLOUR",
    is_flag=True,
    default=False,
    help="Force colourized output.",
)
@click.option(
    "--version",
    is_flag=True,
    callback=version,
    expose_value=False,
    is_eager=True,
    help="Show CLI version and exit.",
)
def cli(
    _connection,
    _debug,
    _quiet,
    _silent,
    _unsafe,
    _colour,
):
    """
    Parallel Virtual Cluster CLI management tool

    Environment variables:

      "PVC_CONNECTION": Set the connection to access instead of using --connection/-c

      "PVC_DEBUG": Enable additional debugging details instead of using --debug/-v

      "PVC_QUIET": Suppress stderr output from client instead of using --quiet/-q

      "PVC_SILENT": Suppress stdout and stderr output from client instead of using --silent/-s

      "PVC_UNSAFE": Always suppress confirmations instead of needing --unsafe/-u or --yes/-y; USE WITH EXTREME CARE

      "PVC_COLOUR": Force colour on the output even if Click determines it is not a console (e.g. with 'watch')

    If a "-c"/"--connection"/"PVC_CONNECTION" is not specified, the CLI will attempt to read a "local" connection
    from the API configuration at "/etc/pvc/pvcapid.yaml". If no such configuration is found, the command will
    abort with an error. This applies to all commands except those under "connection".
    """

    global CLI_CONFIG
    CLI_CONFIG["quiet"] = _quiet
    CLI_CONFIG["silent"] = _silent

    cli_client_dir = environ.get("PVC_CLIENT_DIR", None)
    home_dir = environ.get("HOME", None)
    if cli_client_dir:
        store_path = cli_client_dir
    elif home_dir:
        store_path = f"{home_dir}/.config/pvc"
    else:
        echo(
            CLI_CONFIG,
            "WARNING: No client or home configuration directory found; using /tmp instead",
            stderr=True,
        )
        store_path = "/tmp/pvc"

    if not path.isdir(store_path):
        makedirs(store_path)

    if not path.isfile(f"{store_path}/{DEFAULT_STORE_FILENAME}"):
        update_store(store_path, {"local": DEFAULT_STORE_DATA})

    store_data = get_store(store_path)

    # If the connection isn't in the store, mark it bad but pass the value
    if _connection is not None and _connection not in store_data.keys():
        CLI_CONFIG = {"badcfg": True, "connection": _connection}
    else:
        CLI_CONFIG = get_config(store_data, _connection)

    if not CLI_CONFIG.get("badcfg", None):
        CLI_CONFIG["debug"] = _debug
        CLI_CONFIG["unsafe"] = _unsafe
        CLI_CONFIG["colour"] = _colour
        CLI_CONFIG["quiet"] = _quiet
        CLI_CONFIG["silent"] = _silent
        CLI_CONFIG["store_path"] = store_path

    audit()


###############################################################################
# Click command tree
###############################################################################

cli_node.add_command(cli_node_primary)
cli_node.add_command(cli_node_secondary)
cli_node.add_command(cli_node_flush)
cli_node.add_command(cli_node_ready)
cli_node.add_command(cli_node_log)
cli_node.add_command(cli_node_info)
cli_node.add_command(cli_node_list)
cli.add_command(cli_node)
cli_vm.add_command(cli_vm_define)
cli_vm.add_command(cli_vm_meta)
cli_vm.add_command(cli_vm_modify)
cli_vm.add_command(cli_vm_rename)
cli_vm.add_command(cli_vm_undefine)
cli_vm.add_command(cli_vm_remove)
cli_vm.add_command(cli_vm_start)
cli_vm.add_command(cli_vm_restart)
cli_vm.add_command(cli_vm_shutdown)
cli_vm.add_command(cli_vm_stop)
cli_vm.add_command(cli_vm_disable)
cli_vm.add_command(cli_vm_move)
cli_vm.add_command(cli_vm_migrate)
cli_vm.add_command(cli_vm_unmigrate)
cli_vm.add_command(cli_vm_flush_locks)
cli_vm_backup.add_command(cli_vm_backup_create)
cli_vm_backup.add_command(cli_vm_backup_restore)
cli_vm_backup.add_command(cli_vm_backup_remove)
cli_vm.add_command(cli_vm_backup)
cli_vm.add_command(cli_vm_autobackup)
cli_vm_tag.add_command(cli_vm_tag_get)
cli_vm_tag.add_command(cli_vm_tag_add)
cli_vm_tag.add_command(cli_vm_tag_remove)
cli_vm.add_command(cli_vm_tag)
cli_vm_vcpu.add_command(cli_vm_vcpu_get)
cli_vm_vcpu.add_command(cli_vm_vcpu_set)
cli_vm.add_command(cli_vm_vcpu)
cli_vm_memory.add_command(cli_vm_memory_get)
cli_vm_memory.add_command(cli_vm_memory_set)
cli_vm.add_command(cli_vm_memory)
cli_vm_network.add_command(cli_vm_network_get)
cli_vm_network.add_command(cli_vm_network_add)
cli_vm_network.add_command(cli_vm_network_remove)
cli_vm.add_command(cli_vm_network)
cli_vm_volume.add_command(cli_vm_volume_get)
cli_vm_volume.add_command(cli_vm_volume_add)
cli_vm_volume.add_command(cli_vm_volume_remove)
cli_vm.add_command(cli_vm_volume)
cli_vm.add_command(cli_vm_log)
cli_vm.add_command(cli_vm_dump)
cli_vm.add_command(cli_vm_info)
cli_vm.add_command(cli_vm_list)
cli.add_command(cli_vm)
cli_network.add_command(cli_network_add)
cli_network.add_command(cli_network_modify)
cli_network.add_command(cli_network_remove)
cli_network.add_command(cli_network_info)
cli_network.add_command(cli_network_list)
cli_network_dhcp.add_command(cli_network_dhcp_add)
cli_network_dhcp.add_command(cli_network_dhcp_remove)
cli_network_dhcp.add_command(cli_network_dhcp_list)
cli_network.add_command(cli_network_dhcp)
cli_network_acl.add_command(cli_network_acl_add)
cli_network_acl.add_command(cli_network_acl_remove)
cli_network_acl.add_command(cli_network_acl_list)
cli_network.add_command(cli_network_acl)
cli_network_sriov_pf.add_command(cli_network_sriov_pf_list)
cli_network_sriov.add_command(cli_network_sriov_pf)
cli_network_sriov_vf.add_command(cli_network_sriov_vf_info)
cli_network_sriov_vf.add_command(cli_network_sriov_vf_list)
cli_network_sriov.add_command(cli_network_sriov_vf)
cli_network.add_command(cli_network_sriov)
cli.add_command(cli_network)
cli_storage.add_command(cli_storage_status)
cli_storage.add_command(cli_storage_util)
cli_storage_benchmark.add_command(cli_storage_benchmark_run)
cli_storage_benchmark.add_command(cli_storage_benchmark_info)
cli_storage_benchmark.add_command(cli_storage_benchmark_list)
cli_storage.add_command(cli_storage_benchmark)
cli_storage.add_command(cli_storage_osd_create_db_vg)
cli_storage_osd.add_command(cli_storage_osd_create_db_vg)
cli_storage_osd.add_command(cli_storage_osd_add)
cli_storage_osd.add_command(cli_storage_osd_replace)
cli_storage_osd.add_command(cli_storage_osd_refresh)
cli_storage_osd.add_command(cli_storage_osd_remove)
cli_storage_osd.add_command(cli_storage_osd_in)
cli_storage_osd.add_command(cli_storage_osd_out)
cli_storage_osd.add_command(cli_storage_osd_set)
cli_storage_osd.add_command(cli_storage_osd_unset)
cli_storage_osd.add_command(cli_storage_osd_list)
cli_storage.add_command(cli_storage_osd)
cli_storage_pool.add_command(cli_storage_pool_add)
cli_storage_pool.add_command(cli_storage_pool_remove)
cli_storage_pool.add_command(cli_storage_pool_set_pgs)
cli_storage_pool.add_command(cli_storage_pool_list)
cli_storage.add_command(cli_storage_pool)
cli_storage_volume.add_command(cli_storage_volume_add)
cli_storage_volume.add_command(cli_storage_volume_upload)
cli_storage_volume.add_command(cli_storage_volume_remove)
cli_storage_volume.add_command(cli_storage_volume_resize)
cli_storage_volume.add_command(cli_storage_volume_rename)
cli_storage_volume.add_command(cli_storage_volume_clone)
cli_storage_volume.add_command(cli_storage_volume_list)
cli_storage_volume_snapshot.add_command(cli_storage_volume_snapshot_add)
cli_storage_volume_snapshot.add_command(cli_storage_volume_snapshot_rename)
cli_storage_volume_snapshot.add_command(cli_storage_volume_snapshot_remove)
cli_storage_volume_snapshot.add_command(cli_storage_volume_snapshot_list)
cli_storage_volume.add_command(cli_storage_volume_snapshot)
cli_storage.add_command(cli_storage_volume)
cli.add_command(cli_storage)
cli_provisioner_template_system.add_command(cli_provisioner_template_system_add)
cli_provisioner_template_system.add_command(cli_provisioner_template_system_modify)
cli_provisioner_template_system.add_command(cli_provisioner_template_system_remove)
cli_provisioner_template_system.add_command(cli_provisioner_template_system_list)
cli_provisioner_template.add_command(cli_provisioner_template_system)
cli_provisioner_template_network.add_command(cli_provisioner_template_network_add)
cli_provisioner_template_network.add_command(cli_provisioner_template_network_remove)
cli_provisioner_template_network.add_command(cli_provisioner_template_network_list)
cli_provisioner_template_network_vni.add_command(
    cli_provisioner_template_network_vni_add
)
cli_provisioner_template_network_vni.add_command(
    cli_provisioner_template_network_vni_remove
)
cli_provisioner_template_network.add_command(cli_provisioner_template_network_vni)
cli_provisioner_template.add_command(cli_provisioner_template_network)
cli_provisioner_template_storage.add_command(cli_provisioner_template_storage_add)
cli_provisioner_template_storage.add_command(cli_provisioner_template_storage_remove)
cli_provisioner_template_storage.add_command(cli_provisioner_template_storage_list)
cli_provisioner_template_storage_disk.add_command(
    cli_provisioner_template_storage_disk_add
)
cli_provisioner_template_storage_disk.add_command(
    cli_provisioner_template_storage_disk_remove
)
cli_provisioner_template_storage.add_command(cli_provisioner_template_storage_disk)
cli_provisioner_template.add_command(cli_provisioner_template_storage)
cli_provisioner.add_command(cli_provisioner_template)
cli_provisioner_userdata.add_command(cli_provisioner_userdata_add)
cli_provisioner_userdata.add_command(cli_provisioner_userdata_modify)
cli_provisioner_userdata.add_command(cli_provisioner_userdata_remove)
cli_provisioner_userdata.add_command(cli_provisioner_userdata_show)
cli_provisioner_userdata.add_command(cli_provisioner_userdata_list)
cli_provisioner.add_command(cli_provisioner_userdata)
cli_provisioner_script.add_command(cli_provisioner_script_add)
cli_provisioner_script.add_command(cli_provisioner_script_modify)
cli_provisioner_script.add_command(cli_provisioner_script_remove)
cli_provisioner_script.add_command(cli_provisioner_script_show)
cli_provisioner_script.add_command(cli_provisioner_script_list)
cli_provisioner.add_command(cli_provisioner_script)
cli_provisioner_ova.add_command(cli_provisioner_ova_upload)
cli_provisioner_ova.add_command(cli_provisioner_ova_remove)
cli_provisioner_ova.add_command(cli_provisioner_ova_list)
cli_provisioner.add_command(cli_provisioner_ova)
cli_provisioner_profile.add_command(cli_provisioner_profile_add)
cli_provisioner_profile.add_command(cli_provisioner_profile_modify)
cli_provisioner_profile.add_command(cli_provisioner_profile_remove)
cli_provisioner_profile.add_command(cli_provisioner_profile_list)
cli_provisioner.add_command(cli_provisioner_profile)
cli_provisioner.add_command(cli_provisioner_create)
cli_provisioner.add_command(cli_provisioner_status)
cli.add_command(cli_provisioner)
cli_cluster.add_command(cli_cluster_status)
cli_cluster.add_command(cli_cluster_init)
cli_cluster.add_command(cli_cluster_backup)
cli_cluster.add_command(cli_cluster_restore)
cli_cluster_maintenance.add_command(cli_cluster_maintenance_on)
cli_cluster_maintenance.add_command(cli_cluster_maintenance_off)
cli_cluster.add_command(cli_cluster_maintenance)
cli.add_command(cli_cluster)
cli_connection.add_command(cli_connection_add)
cli_connection.add_command(cli_connection_remove)
cli_connection.add_command(cli_connection_list)
cli_connection.add_command(cli_connection_detail)
cli.add_command(cli_connection)
