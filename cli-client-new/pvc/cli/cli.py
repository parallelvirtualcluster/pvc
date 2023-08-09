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
from re import sub

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
                    # Try to interpolate any variables in the message from the kwargs
                    # This is slightly messy but allows for nicer specification of the variables
                    # in the calling {message} string
                    _message = sub(r"{([^{}]*)}", r"\"{kwargs['\1']}\"", message)
                    _message = eval(f"""f'''{_message}'''""")

                    click.confirm(_message, prompt_suffix="? ", abort=True)
                except Exception:
                    print("Aborted.")
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
# > pvc network info TODO:formatter
###############################################################################
@click.command(name="info", short_help="Show details of a network.")
@connection_req
@click.argument("vni")
@click.option(
    "-l",
    "--long",
    "long_output",
    is_flag=True,
    default=False,
    help="Display more detailed information.",
)
def cli_network_info(vni, long_output):
    """
    Show information about virtual network VNI.
    """

    retcode, retdata = pvc.lib.network.net_info(CLI_CONFIG, vni)
    if retcode:
        retdata = pvc.lib.network.format_info(CLI_CONFIG, retdata, long_output)
    finish(retcode, retdata)


###############################################################################
# > pvc network list TODO:formatter
###############################################################################
@click.command(name="list", short_help="List all VM objects.")
@connection_req
@click.argument("limit", default=None, required=False)
def cli_network_list(limit):
    """
    List all virtual networks; optionally only match VNIs or Descriptions matching regex LIMIT.
    """

    retcode, retdata = pvc.lib.network.net_list(CLI_CONFIG, limit)
    if retcode:
        retdata = pvc.lib.network.format_list(CLI_CONFIG, retdata)
    finish(retcode, retdata)


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
# > pvc network dhcp list TODO:formatter
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
def cli_network_dhcp_list(net, limit, only_static):
    """
    List all DHCP leases in virtual network NET; optionally only match elements matching regex LIMIT; NET must be a VNI.
    """

    retcode, retdata = pvc.lib.network.net_dhcp_list(
        CLI_CONFIG, net, limit, only_static
    )
    if retcode:
        retdata = pvc.lib.network.format_list_dhcp(retdata)
    finish(retcode, retdata)


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
# > pvc network acl list TODO:formatter
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
def cli_network_acl_list(net, limit, direction):
    """
    List all NFT firewall rules in network NET; optionally only match elements matching description regex LIMIT; NET can be either a VNI or description.
    """
    if direction is not None:
        if direction:
            direction = "in"
        else:
            direction = "out"

    retcode, retdata = pvc.lib.network.net_acl_list(CLI_CONFIG, net, limit, direction)
    if retcode:
        retdata = pvc.lib.network.format_list_acl(retdata)
    finish(retcode, retdata)


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
# > pvc network sriov pf list TODO:formatter
###############################################################################
@click.command(name="list", short_help="List PF devices.")
@connection_req
@click.argument("node")
def cli_network_sriov_pf_list(node):
    """
    List all SR-IOV PFs on NODE.
    """
    retcode, retdata = pvc.lib.network.net_sriov_pf_list(CLI_CONFIG, node)
    if retcode:
        retdata = pvc.lib.network.format_list_sriov_pf(retdata)
    finish(retcode, retdata)


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
# > pvc network sriov vf info TODO:formatter
###############################################################################
@click.command(name="info", short_help="Show details of VF devices.")
@connection_req
@click.argument("node")
@click.argument("vf")
def cli_network_sriov_vf_info(node, vf):
    """
    Show details of the SR-IOV VF on NODE.
    """
    retcode, retdata = pvc.lib.network.net_sriov_vf_info(CLI_CONFIG, node, vf)
    if retcode:
        retdata = pvc.lib.network.format_info_sriov_vf(CLI_CONFIG, retdata, node)
    finish(retcode, retdata)


###############################################################################
# > pvc network sriov vf list TODO:formatter
###############################################################################
@click.command(name="list", short_help="List VF devices.")
@connection_req
@click.argument("node")
@click.argument("pf", default=None, required=False)
def cli_network_sriov_vf_list(node, pf):
    """
    List all SR-IOV VFs on NODE, optionally limited to device PF.
    """
    retcode, retdata = pvc.lib.network.net_sriov_vf_list(CLI_CONFIG, node, pf)
    if retcode:
        retdata = pvc.lib.network.format_list_sriov_vf(retdata)
    finish(retcode, retdata)


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
# > pvc storage status TODO:formatter
###############################################################################
@click.command(name="status", short_help="Show storage cluster status.")
@connection_req
def cli_storage_status():
    """
    Show detailed status of the storage cluster.
    """

    retcode, retdata = pvc.lib.storage.ceph_status(CLI_CONFIG)
    if retcode:
        retdata = pvc.lib.storage.format_raw_output(retdata)
    finish(retcode, retdata)


###############################################################################
# > pvc storage util TODO:formatter
###############################################################################
@click.command(name="util", short_help="Show storage cluster utilization.")
@connection_req
def cli_storage_util():
    """
    Show utilization of the storage cluster.
    """

    retcode, retdata = pvc.lib.storage.ceph_util(CLI_CONFIG)
    if retcode:
        retdata = pvc.lib.storage.format_raw_output(retdata)
    finish(retcode, retdata)


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
@confirm_opt(
    "Storage benchmarks take approximately 10 minutes to run and generate significant load on the cluster; they should be run sparingly. Continue"
)
def cli_storage_benchmark_run(pool):
    """
    Run a storage benchmark on POOL in the background.
    """

    retcode, retmsg = pvc.lib.storage.ceph_benchmark_run(CLI_CONFIG, pool)
    finish(retcode, retmsg)


###############################################################################
# > pvc storage benchmark info TODO:formatter
###############################################################################
@click.command(name="info", short_help="Show detailed storage benchmark results.")
@connection_req
@click.argument("job", required=True)
@click.option(
    "-f",
    "--format",
    "oformat",
    default="summary",
    show_default=True,
    type=click.Choice(["summary", "json", "json-pretty"]),
    help="Output format of benchmark information.",
)
def cli_storage_benchmark_info(job, oformat):
    """
    Show full details of storage benchmark JOB.
    """

    retcode, retdata = pvc.lib.storage.ceph_benchmark_list(CLI_CONFIG, job)
    if retcode:
        retdata = pvc.lib.storage.format_info_benchmark(CLI_CONFIG, oformat, retdata)
    finish(retcode, retdata)


###############################################################################
# > pvc storage benchmark list TODO:formatter
###############################################################################
@click.command(name="list", short_help="List storage benchmark results.")
@connection_req
@click.argument("job", default=None, required=False)
def cli_storage_benchmark_list(job):
    """
    List all Ceph storage benchmarks; optionally only match JOB.
    """

    retcode, retdata = pvc.lib.storage.ceph_benchmark_list(CLI_CONFIG, job)
    if retcode:
        retdata = pvc.lib.storage.format_list_benchmark(CLI_CONFIG, retdata)
    finish(retcode, retdata)


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
@confirm_opt(
    "Destroy all data on and create a new OSD database volume group on node {node} device {device}"
)
def cli_storage_osd_create_db_vg(node, device):
    """
    Create a new Ceph OSD database volume group on node NODE with block device DEVICE. DEVICE must be a valid block device path (e.g. '/dev/nvme0n1', '/dev/disk/by-path/...') or a "detect" string. Using partitions is not supported.

    This volume group will be used for Ceph OSD database and WAL functionality if the '--ext-db' flag is passed to newly-created OSDs during 'pvc storage osd add'. DEVICE should be an extremely fast SSD device (NVMe, Intel Optane, etc.) which is significantly faster than the normal OSD disks and with very high write endurance.

    Only one OSD database volume group on a single physical device, named "osd-db", is supported per node, so it must be fast and large enough to act as an effective OSD database device for all OSDs on the node. Attempting to add additional database volume groups after the first will result in an error.

    WARNING: If the OSD database device fails, all OSDs on the node using it will be lost and must be recreated.

    A "detect" string is a string in the form "detect:<NAME>:<HUMAN-SIZE>:<ID>". Detect strings allow for automatic determination of Linux block device paths from known basic information about disks by leveraging "lsscsi" on the target host. The "NAME" should be some descriptive identifier, for instance the manufacturer (e.g. "INTEL"), the "HUMAN-SIZE" should be the labeled human-readable size of the device (e.g. "480GB", "1.92TB"), and "ID" specifies the Nth 0-indexed device which matches the "NAME" and "HUMAN-SIZE" values (e.g. "2" would match the third device with the corresponding "NAME" and "HUMAN-SIZE"). When matching against sizes, there is +/- 3% flexibility to account for base-1000 vs. base-1024 differences and rounding errors. The "NAME" may contain whitespace but if so the entire detect string should be quoted, and is case-insensitive. More information about detect strings can be found in the manual.
    """

    retcode, retmsg = pvc.lib.storage.ceph_osd_db_vg_add(CLI_CONFIG, node, device)
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
    help="Weight of the OSD within the CRUSH map.",
)
@click.option(
    "-d",
    "--ext-db",
    "ext_db_flag",
    is_flag=True,
    default=False,
    help="Use an external database logical volume for this OSD.",
)
@click.option(
    "-r",
    "--ext-db-ratio",
    "ext_db_ratio",
    default=0.05,
    show_default=True,
    type=float,
    help="Decimal ratio of the external database logical volume to the OSD size.",
)
@confirm_opt("Destroy all data on and create new OSD on node {node} device {device}")
def cli_storage_osd_add(node, device, weight, ext_db_flag, ext_db_ratio):
    """
    Add a new Ceph OSD on node NODE with block device DEVICE. DEVICE must be a valid block device path (e.g. '/dev/sda', '/dev/nvme0n1', '/dev/disk/by-path/...', '/dev/disk/by-id/...') or a "detect" string. Using partitions is not supported.

    A "detect" string is a string in the form "detect:<NAME>:<HUMAN-SIZE>:<ID>". Detect strings allow for automatic determination of Linux block device paths from known basic information about disks by leveraging "lsscsi" on the target host. The "NAME" should be some descriptive identifier, for instance the manufacturer (e.g. "INTEL"), the "HUMAN-SIZE" should be the labeled human-readable size of the device (e.g. "480GB", "1.92TB"), and "ID" specifies the Nth 0-indexed device which matches the "NAME" and "HUMAN-SIZE" values (e.g. "2" would match the third device with the corresponding "NAME" and "HUMAN-SIZE"). When matching against sizes, there is +/- 3% flexibility to account for base-1000 vs. base-1024 differences and rounding errors. The "NAME" may contain whitespace but if so the entire detect string should be quoted, and is case-insensitive. More information about detect strings can be found in the pvcbootstrapd manual.

    The weight of an OSD should reflect the ratio of the OSD to other OSDs in the storage cluster. For example, if all OSDs are the same size as recommended for PVC, 1 (the default) is a valid weight so that all are treated identically. If a new OSD is added later which is 4x the size of the existing OSDs, the new OSD's weight should then be 4 to tell the cluster that 4x the data can be stored on the OSD. Weights can also be tweaked for performance reasons, since OSDs with more data will incur more I/O load. For more information about CRUSH weights, please see the Ceph documentation.

    If '--ext-db' is specified, the OSD database and WAL will be placed on a new logical volume in NODE's OSD database volume group. An OSD database volume group must exist on the node or the OSD creation will fail. See the 'pvc storage osd create-db-vg' command for more details.

    The default '--ext-db-ratio' of 0.05 (5%) is sufficient for most RBD workloads and OSD sizes, though this can be adjusted based on the sizes of the OSD(s) and the underlying database device. Ceph documentation recommends at least 0.02 (2%) for RBD use-cases, and higher values may improve WAL performance under write-heavy workloads with fewer OSDs per node.
    """

    retcode, retmsg = pvc.lib.storage.ceph_osd_add(
        CLI_CONFIG, node, device, weight, ext_db_flag, ext_db_ratio
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc storage osd replace
###############################################################################
@click.command(name="replace", short_help="Replace OSD block device.")
@connection_req
@click.argument("osdid")
@click.argument("device")
@click.option(
    "-w",
    "--weight",
    "weight",
    default=1.0,
    show_default=True,
    help="New weight of the OSD within the CRUSH map.",
)
@confirm_opt("Replace OSD {osdid} with block device {device} weight {weight}")
def cli_storage_osd_replace(osdid, device, weight):
    """
    Replace the block device of an existing OSD with ID OSDID with DEVICE. Use this command to replace a failed or smaller OSD block device with a new one.

    DEVICE must be a valid block device path (e.g. '/dev/sda', '/dev/nvme0n1', '/dev/disk/by-path/...', '/dev/disk/by-id/...') or a "detect" string. Using partitions is not supported. A "detect" string is a string in the form "detect:<NAME>:<HUMAN-SIZE>:<ID>". For details, see 'pvc storage osd add --help'.

    The weight of an OSD should reflect the ratio of the OSD to other OSDs in the storage cluster. For details, see 'pvc storage osd add --help'. Note that the current weight must be explicitly specified if it differs from the default.

    Existing IDs, external DB devices, etc. of the OSD will be preserved; data will be lost and rebuilt from the remaining healthy OSDs.
    """

    retcode, retmsg = pvc.lib.storage.ceph_osd_replace(
        CLI_CONFIG, osdid, device, weight
    )
    finish(retcode, retmsg)


###############################################################################
# > pvc storage osd refresh
###############################################################################
@click.command(name="refresh", short_help="Refresh (reimport) OSD device.")
@connection_req
@click.argument("osdid")
@click.argument("device")
@confirm_opt("Refresh OSD {osdid} on device {device}")
def cli_storage_osd_refresh(osdid, device):
    """
    Refresh (reimport) the block DEVICE of an existing OSD with ID OSDID. Use this command to reimport a working OSD into a rebuilt/replaced node.

    DEVICE must be a valid block device path (e.g. '/dev/sda', '/dev/nvme0n1', '/dev/disk/by-path/...', '/dev/disk/by-id/...') or a "detect" string. Using partitions is not supported. A "detect" string is a string in the form "detect:<NAME>:<HUMAN-SIZE>:<ID>". For details, see 'pvc storage osd add --help'.

    Existing data, IDs, weights, etc. of the OSD will be preserved.

    NOTE: If a device had an external DB device, this is not automatically handled at this time. It is best to remove and re-add the OSD instead.
    """
    retcode, retmsg = pvc.lib.storage.ceph_osd_refresh(CLI_CONFIG, osdid, device)
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
@confirm_opt("Remove and destroy data on OSD {osdid}")
def cli_storage_osd_remove(osdid, force_flag):
    """
    Remove a Ceph OSD with ID OSDID.

    DANGER: This will completely remove the OSD from the cluster. OSDs will rebalance which will negatively affect performance and available space. It is STRONGLY RECOMMENDED to set an OSD out (using 'pvc storage osd out') and allow the cluster to fully rebalance, verified with 'pvc storage status', before removing an OSD.

    NOTE: The "-f"/"--force" option is useful after replacing a failed node, to ensure the OSD is removed even if the OSD in question does not properly exist on the node after a rebuild.
    """

    retcode, retmsg = pvc.lib.storage.ceph_osd_remove(CLI_CONFIG, osdid, force_flag)
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
@click.argument("osd_property")
@cluster_req
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
# > pvc storage osd list TODO:formatter
###############################################################################
@click.command(name="list", short_help="List cluster OSDs.")
@connection_req
@click.argument("limit", default=None, required=False)
def cli_storage_osd_list(limit):
    """
    List all Ceph OSDs; optionally only match elements matching ID regex LIMIT.
    """

    retcode, retdata = pvc.lib.storage.ceph_osd_list(CLI_CONFIG, limit)
    if retcode:
        retdata = pvc.lib.storage.format_list_osd(retdata)
    finish(retcode, retdata)


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
    The replication configuration, specifying both a "copies" and "mincopies" value, separated by a comma, e.g. "copies=3,mincopies=2". The "copies" value specifies the total number of replicas and should not exceed the total number of nodes; the "mincopies" value specifies the minimum number of available copies to allow writes. For additional details please see the Cluster Architecture documentation.
    """,
)
def cli_storage_pool_add(name, pgs, tier, replcfg):
    """
    Add a new Ceph RBD pool with name NAME and PGS placement groups.

    The placement group count must be a non-zero power of 2.
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

    The placement group count must be a non-zero power of 2.

    Placement group counts may be increased or decreased as required though frequent alteration is not recommended.
    """

    retcode, retmsg = pvc.lib.storage.ceph_pool_set_pgs(CLI_CONFIG, name, pgs)
    finish(retcode, retmsg)


###############################################################################
# > pvc storage pool info
###############################################################################
# Not implemented


###############################################################################
# > pvc storage pool list TODO:formatter
###############################################################################
@click.command(name="list", short_help="List cluster RBD pools.")
@connection_req
@click.argument("limit", default=None, required=False)
def cli_storage_pool_list(limit):
    """
    List all Ceph RBD pools; optionally only match elements matching name regex LIMIT.
    """

    retcode, retdata = pvc.lib.storage.ceph_pool_list(CLI_CONFIG, limit)
    if retcode:
        retdata = pvc.lib.storage.format_list_pool(retdata)
    finish(retcode, retdata)


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

    if not os.path.exists(image_file):
        echo("ERROR: File '{}' does not exist!".format(image_file))
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
# > pvc storage volume list TODO:formatter
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
def cli_storage_volume_list(limit, pool):
    """
    List all Ceph RBD volumes; optionally only match elements matching name regex LIMIT.
    """

    retcode, retdata = pvc.lib.storage.ceph_volume_list(CLI_CONFIG, limit, pool)
    if retcode:
        retdata = pvc.lib.storage.format_list_volume(retdata)
    finish(retcode, retdata)


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
# > pvc storage volume snapshot list TODO:formatter
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
def cli_storage_volume_snapshot_list(pool, volume, limit):
    """
    List all Ceph RBD volume snapshots; optionally only match elements matching name regex LIMIT.
    """

    retcode, retdata = pvc.lib.storage.ceph_snapshot_list(
        CLI_CONFIG, limit, volume, pool
    )
    if retcode:
        retdata = pvc.lib.storage.format_list_snapshot(retdata)
    finish(retcode, retdata)


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
cli_storage_volume.add_command(cli_storage_volume_snapshot)
cli_storage.add_command(cli_storage_volume)
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
