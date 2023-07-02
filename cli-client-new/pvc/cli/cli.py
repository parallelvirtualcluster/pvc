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

from functools import wraps
from json import dump as jdump
from json import dumps as jdumps
from json import loads as jloads
from os import environ, makedirs, path
from pkg_resources import get_distribution

from pvc.cli.helpers import *
from pvc.cli.waiters import *
from pvc.cli.parsers import *
from pvc.cli.formatters import *

import pvc.lib.cluster
import pvc.lib.node
import pvc.lib.provisioner

import click


###############################################################################
# Context and completion handler
###############################################################################


CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"], max_content_width=120)
IS_COMPLETION = True if environ.get("_PVC_COMPLETE", "") == "complete" else False

CLI_CONFIG = dict()

if not IS_COMPLETION:
    cli_client_dir = environ.get("PVC_CLIENT_DIR", None)
    home_dir = environ.get("HOME", None)
    if cli_client_dir:
        store_path = cli_client_dir
    elif home_dir:
        store_path = f"{home_dir}/.config/pvc"
    else:
        print(
            "WARNING: No client or home configuration directory found; using /tmp instead"
        )
        store_path = "/tmp/pvc"

    if not path.isdir(store_path):
        makedirs(store_path)

    if not path.isfile(f"{store_path}/{DEFAULT_STORE_FILENAME}"):
        update_store(store_path, {"local": DEFAULT_STORE_DATA})


###############################################################################
# Local helper functions
###############################################################################


def finish(success=True, data=None, formatter=None):
    """
    Output data to the terminal and exit based on code (T/F or integer code)
    """

    if data is not None:
        if formatter is not None:
            echo(CLI_CONFIG, formatter(data))
        else:
            echo(CLI_CONFIG, data)

    # Allow passing
    if isinstance(success, int):
        exit(success)

    if success:
        exit(0)
    else:
        exit(1)


def version(ctx, param, value):
    """
    Show the version of the CLI client
    """

    if not value or ctx.resilient_parsing:
        return

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
    Wraps a Click command which requires confirm_flag or unsafe option or asks for VM restart confirmation
    """

    @click.option(
        "-r",
        "--restart",
        "restart_flag",
        is_flag=True,
        default=False,
        help="Immediately restart VM to apply changes.",
    )
    @wraps(function)
    def confirm_action(*args, **kwargs):
        confirm_action = True
        if "restart_flag" in kwargs:
            if not kwargs.get("restart_flag", False):
                if not CLI_CONFIG.get("unsafe", False):
                    confirm_action = True
                else:
                    confirm_action = False
            else:
                confirm_action = False
        else:
            confirm_action = False

        if confirm_action:
            try:
                click.confirm(
                    f"Restart VM {kwargs.get('vm')}", prompt_suffix="? ", abort=True
                )
            except Exception:
                echo(CLI_CONFIG, "Changes will be applied on next VM start/restart.")
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

            if confirm_action:
                try:
                    click.confirm(message, prompt_suffix="? ", abort=True)
                except Exception:
                    exit(0)

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
@format_opt(
    {
        "pretty": cli_cluster_status_format_pretty,
        "short": cli_cluster_status_format_short,
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
@connection_req
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
@click.option(
    "-o",
    "--overwrite",
    "overwrite_flag",
    is_flag=True,
    default=False,
    help="Remove and overwrite any existing data (DANGEROUS)",
)
@confirm_opt
@connection_req
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
@click.option(
    "-f",
    "--file",
    "filename",
    default=None,
    type=click.File(mode="w"),
    help="Write backup data to this file.",
)
@connection_req
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
@click.option(
    "-f",
    "--filename",
    "filename",
    required=True,
    default=None,
    type=click.File(),
    help="Read backup data from this file.",
)
@confirm_opt
@connection_req
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
@click.argument("node")
@click.option(
    "-w",
    "--wait",
    "wait_flag",
    default=False,
    show_default=True,
    is_flag=True,
    help="Block waiting for state transition",
)
@connection_req
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
@click.argument("node")
@click.option(
    "-w",
    "--wait",
    "wait_flag",
    default=False,
    show_default=True,
    is_flag=True,
    help="Block waiting for state transition",
)
@connection_req
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
@click.argument("node")
@click.option(
    "-w",
    "--wait",
    "wait_flag",
    default=False,
    show_default=True,
    is_flag=True,
    help="Block waiting for state transition",
)
@connection_req
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
@click.argument("node")
@click.option(
    "-w",
    "--wait",
    "wait_flag",
    default=False,
    show_default=True,
    is_flag=True,
    help="Block waiting for state transition",
)
@connection_req
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
@click.argument("node")
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
@connection_req
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
@click.argument("node", default=DEFAULT_NODE_HOSTNAME)
@format_opt(
    {
        "pretty": cli_node_info_format_pretty,
        "long": cli_node_info_format_long,
        "json": lambda d: jdumps(d),
        "json-pretty": lambda d: jdumps(d, indent=2),
    }
)
@connection_req
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
@click.argument("limit", default=None, required=False)
@click.option(
    "-ds",
    "--daemon-state",
    "daemon_state_filter",
    default=None,
    help="Limit list to nodes in the specified daemon state.",
)
@click.option(
    "-ds",
    "--coordinator-state",
    "coordinator_state_filter",
    default=None,
    help="Limit list to nodes in the specified coordinator state.",
)
@click.option(
    "-ds",
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
@connection_req
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


###############################################################################
# > pvc vm meta
###############################################################################


###############################################################################
# > pvc vm modify
###############################################################################


###############################################################################
# > pvc vm rename
###############################################################################


###############################################################################
# > pvc vm undefine
###############################################################################


###############################################################################
# > pvc vm remove
###############################################################################


###############################################################################
# > pvc vm start
###############################################################################


###############################################################################
# > pvc vm restart
###############################################################################


###############################################################################
# > pvc vm shutdown
###############################################################################


###############################################################################
# > pvc vm stop
###############################################################################


###############################################################################
# > pvc vm disable
###############################################################################


###############################################################################
# > pvc vm move
###############################################################################


###############################################################################
# > pvc vm migrate
###############################################################################


###############################################################################
# > pvc vm unmigrate
###############################################################################


###############################################################################
# > pvc vm flush-locks
###############################################################################


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


###############################################################################
# > pvc vm tag add
###############################################################################


###############################################################################
# > pvc vm tag remove
###############################################################################


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


###############################################################################
# > pvc vm vcpu set
###############################################################################


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


###############################################################################
# > pvc vm memory set
###############################################################################


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


###############################################################################
# > pvc vm network add
###############################################################################


###############################################################################
# > pvc vm network remove
###############################################################################


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


###############################################################################
# > pvc vm volume add
###############################################################################


###############################################################################
# > pvc vm volume remove
###############################################################################


###############################################################################
# > pvc vm log
###############################################################################


###############################################################################
# > pvc vm dump
###############################################################################


###############################################################################
# > pvc vm info
###############################################################################


###############################################################################
# > pvc vm list
###############################################################################


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


###############################################################################
# > pvc network modify
###############################################################################


###############################################################################
# > pvc network remove
###############################################################################


###############################################################################
# > pvc network info
###############################################################################


###############################################################################
# > pvc network list
###############################################################################


###############################################################################
# > pvc network dhcp
###############################################################################


###############################################################################
# > pvc network dhcp add
###############################################################################


###############################################################################
# > pvc network dhcp remove
###############################################################################


###############################################################################
# > pvc network dhcp list
###############################################################################


###############################################################################
# > pvc network acl
###############################################################################


###############################################################################
# > pvc network acl add
###############################################################################


###############################################################################
# > pvc network acl remove
###############################################################################


###############################################################################
# > pvc network acl list
###############################################################################


###############################################################################
# > pvc network sriov
###############################################################################


###############################################################################
# > pvc network sriov pf
###############################################################################


###############################################################################
# > pvc network sriov pf list
###############################################################################


###############################################################################
# > pvc network sriov vf
###############################################################################


###############################################################################
# > pvc network sriov vf set
###############################################################################


###############################################################################
# > pvc network sriov vf info
###############################################################################


###############################################################################
# > pvc network sriov vf list
###############################################################################


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
# > pvc storage status
###############################################################################


###############################################################################
# > pvc storage util
###############################################################################


###############################################################################
# > pvc storage benchmark
###############################################################################


###############################################################################
# > pvc storage benchmark run
###############################################################################


###############################################################################
# > pvc storage benchmark info
###############################################################################


###############################################################################
# > pvc storage benchmark list
###############################################################################


###############################################################################
# > pvc storage osd
###############################################################################


###############################################################################
# > pvc storage osd create-db-vg
###############################################################################


###############################################################################
# > pvc storage osd add
###############################################################################


###############################################################################
# > pvc storage osd replace
###############################################################################


###############################################################################
# > pvc storage osd refresh
###############################################################################


###############################################################################
# > pvc storage osd remove
###############################################################################


###############################################################################
# > pvc storage osd in
###############################################################################


###############################################################################
# > pvc storage osd out
###############################################################################


###############################################################################
# > pvc storage osd set
###############################################################################


###############################################################################
# > pvc storage osd unset
###############################################################################


###############################################################################
# > pvc storage ods info
###############################################################################


###############################################################################
# > pvc storage osd list
###############################################################################


###############################################################################
# > pvc storage pool
###############################################################################


###############################################################################
# > pvc storage pool add
###############################################################################


###############################################################################
# > pvc storage pool remove
###############################################################################


###############################################################################
# > pvc storage pool set-pgs
###############################################################################


###############################################################################
# > pvc storage pool info
###############################################################################


###############################################################################
# > pvc storage pool list
###############################################################################


###############################################################################
# > pvc storage volume
###############################################################################


###############################################################################
# > pvc storage volume add
###############################################################################


###############################################################################
# > pvc storage volume upload
###############################################################################


###############################################################################
# > pvc storage volume remove
###############################################################################


###############################################################################
# > pvc storage volume resize
###############################################################################


###############################################################################
# > pvc storage volume rename
###############################################################################


###############################################################################
# > pvc storage volume clone
###############################################################################


###############################################################################
# > pvc storage volume info
###############################################################################


###############################################################################
# > pvc storage volume list
###############################################################################


###############################################################################
# > pvc storage volume snapshot
###############################################################################


###############################################################################
# > pvc storage volume snapshot add
###############################################################################


###############################################################################
# > pvc storage volume snapshot rename
###############################################################################


###############################################################################
# > pvc storage volume snapshot remove
###############################################################################


###############################################################################
# > pvc storage volume snapshot list
###############################################################################


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


###############################################################################
# > pvc provisioner template system
###############################################################################


###############################################################################
# > pvc provisioner template system add
###############################################################################


###############################################################################
# > pvc provisioner template system modify
###############################################################################


###############################################################################
# > pvc provisioner template system remove
###############################################################################


###############################################################################
# > pvc provisioner template system list
###############################################################################


###############################################################################
# > pvc provisioner template network
###############################################################################


###############################################################################
# > pvc provisioner template network add
###############################################################################


###############################################################################
# > pvc provisioner template network modify
###############################################################################


###############################################################################
# > pvc provisioner template network remove
###############################################################################


###############################################################################
# > pvc provisioner template network list
###############################################################################


###############################################################################
# > pvc provisioner template network vni
###############################################################################


###############################################################################
# > pvc provisioner template network vni add
###############################################################################


###############################################################################
# > pvc provisioner template network vni remove
###############################################################################


###############################################################################
# > pvc provisioner template storage
###############################################################################


###############################################################################
# > pvc provisioner template storage add
###############################################################################


###############################################################################
# > pvc provisioner template storage modify
###############################################################################


###############################################################################
# > pvc provisioner template storage remove
###############################################################################


###############################################################################
# > pvc provisioner template storage list
###############################################################################


###############################################################################
# > pvc provisioner template storage disk
###############################################################################


###############################################################################
# > pvc provisioner template storage disk add
###############################################################################


###############################################################################
# > pvc provisioner template storage disk remove
###############################################################################


###############################################################################
# > pvc provisioner userdata
###############################################################################


###############################################################################
# > pvc provisioner userdata add
###############################################################################


###############################################################################
# > pvc provisioner userdata modify
###############################################################################


###############################################################################
# > pvc provisioner userdata remove
###############################################################################


###############################################################################
# > pvc provisioner userdata dump (was show)
###############################################################################


###############################################################################
# > pvc provisioner userdata list
###############################################################################


###############################################################################
# > pvc provisioner script
###############################################################################


###############################################################################
# > pvc provisioner script add
###############################################################################


###############################################################################
# > pvc provisioner script modify
###############################################################################


###############################################################################
# > pvc provisioner script remove
###############################################################################


###############################################################################
# > pvc provisioner script dump (was show)
###############################################################################


###############################################################################
# > pvc provisioner script list
###############################################################################


###############################################################################
# > pvc provisioner ova
###############################################################################


###############################################################################
# > pvc provisioner ova add (was upload)
###############################################################################


###############################################################################
# > pvc provisioner ova remove
###############################################################################


###############################################################################
# > pvc provisioner ova info
###############################################################################


###############################################################################
# > pvc provisioner ova list
###############################################################################


###############################################################################
# > pvc provisioner profile
###############################################################################


###############################################################################
# > pvc provisioner profile add
###############################################################################


###############################################################################
# > pvc provisioner profile modify
###############################################################################


###############################################################################
# > pvc provisioner profile remove
###############################################################################


###############################################################################
# > pvc provisioner create
###############################################################################


###############################################################################
# > pvc provisioner status
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


###############################################################################
# > pvc
###############################################################################


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
    connections_config = get_store(store_path)

    # Add (or update) the new connection details
    connections_config[name] = {
        "description": description,
        "host": address,
        "port": port,
        "scheme": scheme,
        "api_key": api_key,
    }

    # Update the store data
    update_store(store_path, connections_config)

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
    connections_config = get_store(store_path)

    # Remove the entry matching the name
    try:
        connections_config.pop(name)
    except KeyError:
        finish(False, f"""No connection found with name "{name}" in local database""")

    # Update the store data
    update_store(store_path, connections_config)

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

    connections_config = get_store(store_path)
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
    connections_config = get_store(store_path)
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
    help='Allow unsafe operations without confirmation/"--yes" argument.',
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
    store_data = get_store(store_path)

    # If no connection is specified, use the first connection in the store
    if _connection is None:
        CLI_CONFIG = get_config(store_data, list(store_data.keys())[0])
    # If the connection isn't in the store, mark it bad but pass the value
    elif _connection not in store_data.keys():
        CLI_CONFIG = {"badcfg": True, "connection": _connection}
    else:
        CLI_CONFIG = get_config(store_data, _connection)

    if not CLI_CONFIG.get("badcfg", None):
        CLI_CONFIG["debug"] = _debug
        CLI_CONFIG["unsafe"] = _unsafe
        CLI_CONFIG["colour"] = _colour
        CLI_CONFIG["quiet"] = _quiet
        CLI_CONFIG["silent"] = _silent

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
cli.add_command(cli_vm)
cli.add_command(cli_network)
cli.add_command(cli_storage)
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
# cli.add_command(testing)
