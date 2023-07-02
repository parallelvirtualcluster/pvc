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
from lxml.etree import fromstring, tostring

from pvc.cli.helpers import *
from pvc.cli.waiters import *
from pvc.cli.parsers import *
from pvc.cli.formatters import *

import pvc.lib.cluster
import pvc.lib.node
import pvc.lib.vm
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
                    f"Restart VM {kwargs.get('domain')} to apply changes",
                    prompt_suffix="? ",
                    abort=True,
                )
                kwargs["restart_flag"] = True
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
@confirm_opt
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
@confirm_opt
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
    xml_data = etree.fromstring(current_vm_cfg_raw)
    current_vm_cfgfile = (
        etree.tostring(xml_data, pretty_print=True).decode("utf8").strip()
    )

    if editor is True:
        new_vm_cfgfile = click.edit(
            text=current_vm_cfgfile, require_save=True, extension=".xml"
        )
        if new_vm_cfgfile is None:
            echo("Aborting with no modifications.")
            exit(0)
        else:
            new_vm_cfgfile = new_vm_cfgfile.strip()

    # We're operating in replace mode
    else:
        # Open the XML file
        new_vm_cfgfile = cfgfile.read()
        cfgfile.close()

        echo(
            'Replacing configuration of VM "{}" with file "{}".'.format(
                dom_name, cfgfile.name
            )
        )

    # Show a diff and confirm
    echo("Pending modifications:")
    echo("")
    diff = list(
        difflib.unified_diff(
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
    for line in diff:
        if re.match(r"^\+", line) is not None:
            echo(colorama.Fore.GREEN + line + colorama.Fore.RESET)
        elif re.match(r"^\-", line) is not None:
            echo(colorama.Fore.RED + line + colorama.Fore.RESET)
        elif re.match(r"^\^", line) is not None:
            echo(colorama.Fore.BLUE + line + colorama.Fore.RESET)
        else:
            echo(line)
    echo("")

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
@confirm_opt
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
@confirm_opt
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
@confirm_opt
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
@confirm_opt
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
@confirm_opt
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
@confirm_opt
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
@confirm_opt
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
def cli_vm_flush_locks(domain):
    """
    Flush stale RBD locks for virtual machine DOMAIN. DOMAIN may be a UUID or name. DOMAIN must be in a stopped state before flushing locks.
    """

    retcode, retmsg = pvc.lib.vm.vm_locks(CLI_CONFIG, domain)
    finish(retcode, retmsg)


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
# > pvc vm tag get TODO:formatter
###############################################################################
@click.command(name="get", short_help="Get the current tags of a virtual machine.")
@connection_req
@click.argument("domain")
@click.option(
    "-r",
    "--raw",
    "raw",
    is_flag=True,
    default=False,
    help="Display the raw value only without formatting.",
)
def cli_vm_tag_get(domain, raw):
    """
    Get the current tags of the virtual machine DOMAIN.
    """

    retcode, retdata = pvc.lib.vm.vm_tags_get(CLI_CONFIG, domain)
    if retcode:
        if not raw:
            retdata = pvc.lib.vm.format_vm_tags(CLI_CONFIG, domain, retdata["tags"])
        else:
            if len(retdata["tags"]) > 0:
                retdata = "\n".join([tag["name"] for tag in retdata["tags"]])
            else:
                retdata = "No tags found."
    finish(retcode, retdata)


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
# > pvc vm vcpu get TODO:formatter
###############################################################################
@click.command(
    name="get", short_help="Get the current vCPU count of a virtual machine."
)
@connection_req
@click.argument("domain")
@click.option(
    "-r",
    "--raw",
    "raw",
    is_flag=True,
    default=False,
    help="Display the raw value only without formatting.",
)
def cli_vm_vcpu_get(domain, raw):
    """
    Get the current vCPU count of the virtual machine DOMAIN.
    """

    retcode, retmsg = pvc.lib.vm.vm_vcpus_get(CLI_CONFIG, domain)
    if not raw:
        retmsg = pvc.lib.vm.format_vm_vcpus(CLI_CONFIG, domain, retmsg)
    else:
        retmsg = retmsg[0]  # Get only the first part of the tuple (vm_vcpus)
    finish(retcode, retmsg)


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
@confirm_opt("Confirm VM restart?")
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
# > pvc vm memory get TODO:formatter
###############################################################################
@click.command(
    name="get", short_help="Get the current provisioned memory of a virtual machine."
)
@connection_req
@click.argument("domain")
@click.option(
    "-r",
    "--raw",
    "raw",
    is_flag=True,
    default=False,
    help="Display the raw value only without formatting.",
)
def cli_vm_memory_get(domain, raw):
    """
    Get the current provisioned memory of the virtual machine DOMAIN.
    """

    retcode, retmsg = pvc.lib.vm.vm_memory_get(CLI_CONFIG, domain)
    if not raw:
        retmsg = pvc.lib.vm.format_vm_memory(CLI_CONFIG, domain, retmsg)
    finish(retcode, retmsg)


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
@confirm_opt("Confirm VM restart?")
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
# > pvc vm network get TODO:formatter
###############################################################################
@click.command(name="get", short_help="Get the networks of a virtual machine.")
@connection_req
@click.argument("domain")
@click.option(
    "-r",
    "--raw",
    "raw",
    is_flag=True,
    default=False,
    help="Display the raw values only without formatting.",
)
def cli_vm_network_get(domain, raw):
    """
    Get the networks of the virtual machine DOMAIN.
    """

    retcode, retdata = pvc.lib.vm.vm_networks_get(CLI_CONFIG, domain)
    if not raw:
        retmsg = pvc.lib.vm.format_vm_networks(CLI_CONFIG, domain, retdata)
    else:
        network_vnis = list()
        for network in retdata:
            network_vnis.append(network[0])
        retmsg = ",".join(network_vnis)
    finish(retcode, retmsg)


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
@confirm_opt("Confirm VM restart?")
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
@confirm_opt("Confirm VM restart?")
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
# > pvc vm volume get TODO:formatter
###############################################################################
@click.command(name="get", short_help="Get the volumes of a virtual machine.")
@connection_req
@click.argument("domain")
@click.option(
    "-r",
    "--raw",
    "raw",
    is_flag=True,
    default=False,
    help="Display the raw values only without formatting.",
)
def cli_vm_volume_get(domain, raw):
    """
    Get the volumes of the virtual machine DOMAIN.
    """

    retcode, retdata = pvc.lib.vm.vm_volumes_get(CLI_CONFIG, domain)
    if not raw:
        retmsg = pvc.lib.vm.format_vm_volumes(CLI_CONFIG, domain, retdata)
    else:
        volume_paths = list()
        for volume in retdata:
            volume_paths.append("{}:{}".format(volume[2], volume[0]))
        retmsg = ",".join(volume_paths)
    finish(retcode, retmsg)


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
@confirm_opt("Confirm VM restart?")
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
@confirm_opt("Confirm VM restart?")
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
# > pvc vm info TODO:formatter
###############################################################################
@click.command(name="info", short_help="Show details of a VM object.")
@connection_req
@click.argument("domain")
@click.option(
    "-l",
    "--long",
    "long_output",
    is_flag=True,
    default=False,
    help="Display more detailed information.",
)
def cli_vm_info(domain, long_output):
    """
    Show information about virtual machine DOMAIN. DOMAIN may be a UUID or name.
    """

    retcode, retdata = pvc.lib.vm.vm_info(CLI_CONFIG, domain)
    if retcode:
        retdata = pvc.lib.vm.format_info(CLI_CONFIG, retdata, long_output)
    finish(retcode, retdata)


###############################################################################
# > pvc vm list TODO:formatter
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
    "-r",
    "--raw",
    "raw",
    is_flag=True,
    default=False,
    help="Display the raw list of VM names only.",
)
@click.option(
    "-n",
    "--negate",
    "negate",
    is_flag=True,
    default=False,
    help="Negate the specified node, state, or tag limit(s).",
)
def cli_vm_list(target_node, target_state, target_tag, limit, raw, negate):
    """
    List all virtual machines; optionally only match names or full UUIDs matching regex LIMIT.

    NOTE: Red-coloured network lists indicate one or more configured networks are missing/invalid.
    """

    retcode, retdata = pvc.lib.vm.vm_list(
        CLI_CONFIG, limit, target_node, target_state, target_tag, negate
    )
    if retcode:
        retdata = pvc.lib.vm.format_list(CLI_CONFIG, retdata, raw)
    else:
        if raw:
            retdata = ""
    finish(retcode, retdata)


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
