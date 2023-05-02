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
from json import dumps as jdumps
from os import environ, makedirs, path
from pkg_resources import get_distribution

from pvc.cli.helpers import *
from pvc.cli.parsers import *
from pvc.cli.formatters import *

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


def echo(message, newline=True, err=False):
    """
    Output a message with click.echo respecting our configuration
    """

    if CLI_CONFIG.get("colour", False):
        colour = True
    else:
        colour = None

    click.echo(message=message, color=colour, nl=newline, err=err)


def finish(success=True, data=None, formatter=None):
    """
    Output data to the terminal and exit based on code (T/F or integer code)
    """

    if data is not None:
        if formatter is not None:
            echo(formatter(data))
        else:
            echo(data)

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
    echo(f"Parallel Virtual Cluster CLI client version {version}")
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
        if CLI_CONFIG.get("badcfg", None):
            echo(
                'No connection specified and no local API configuration found. Use "pvc connection" to add a connection.'
            )
            exit(1)

        if not CLI_CONFIG.get("quiet", False):
            if CLI_CONFIG.get("api_scheme") == "https" and not CLI_CONFIG.get(
                "verify_ssl"
            ):
                ssl_verify_msg = " (unverified)"
            else:
                ssl_verify_msg = ""

            echo(
                f'''Using connection "{CLI_CONFIG.get('connection')}" - Host: "{CLI_CONFIG.get('api_host')}"  Scheme: "{CLI_CONFIG.get('api_scheme')}{ssl_verify_msg}"  Prefix: "{CLI_CONFIG.get('api_prefix')}"''',
                stderr=True,
            )
            echo(
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
                echo("Changes will be applied on next VM start/restart.")
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
    formatting functions for the command with keys as valid format types
    e.g. { "json": lambda d: json.dumps(d), "pretty": format_function_pretty, ... }
    """

    if default_format not in formats.keys():
        echo(f"Fatal code error: {default_format} not in {formats.keys()}")
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
    echo(vm)
    echo(restart_flag)
    echo(format_function)

    data = {
        "athing": "value",
        "anotherthing": 1234,
        "thelist": ["a", "b", "c"],
    }

    finish(True, data, format_function)


###############################################################################
# pvc connection
###############################################################################
@click.group(
    name="connection",
    short_help="Manage PVC cluster connections.",
    context_settings=CONTEXT_SETTINGS,
)
def cli_connection():
    """
    Manage the PVC clusters this CLI client can connect to.
    """
    pass


###############################################################################
# pvc connection add
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
def cli_connection_add(name, description, address, port, api_key, ssl_flag):
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
# pvc connection remove
###############################################################################
@click.command(
    name="remove",
    short_help="Remove connections from the client database.",
)
@click.argument("name")
def cli_connection_remove(name):
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
# pvc connection list
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
def cli_connection_list(show_keys_flag, format_function):
    """
    List all PVC connections in the database of the local CLI client.

    \b
    Format options:
        "pretty": Output a nice tabular list of all details.
        "raw": Output connection names one per line.
        "json": Output in unformatted JSON.
        "json-pretty": Output in formatted JSON.
    """

    connections_config = get_store(store_path)
    connections_data = cli_connection_list_parser(connections_config, show_keys_flag)
    finish(True, connections_data, format_function)


###############################################################################
# pvc connection detail
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
def cli_connection_detail(format_function):
    """
    List the status and information of all PVC cluster in the database of the local CLI client.

    \b
    Format options:
        "pretty": Output a nice tabular list of all details.
        "json": Output in unformatted JSON.
        "json-pretty": Output in formatted JSON.
    """

    echo("Gathering information from all clusters... ", newline=False, err=True)
    connections_config = get_store(store_path)
    connections_data = cli_connection_detail_parser(connections_config)
    echo("done.", err=True)
    echo("", err=True)
    finish(True, connections_data, format_function)


###############################################################################
# pvc
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
    help="Suppress connection connection information.",
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
def cli(_connection, _debug, _quiet, _unsafe, _colour):
    """
    Parallel Virtual Cluster CLI management tool

    Environment variables:

      "PVC_CONNECTION": Set the connection to access instead of using --connection/-c

      "PVC_DEBUG": Enable additional debugging details instead of using --debug/-v

      "PVC_QUIET": Suppress stderr connection output from client instead of using --quiet/-q

      "PVC_UNSAFE": Always suppress confirmations instead of needing --unsafe/-u or --yes/-y; USE WITH EXTREME CARE

      "PVC_COLOUR": Force colour on the output even if Click determines it is not a console (e.g. with 'watch')

    If a "-c"/"--connection"/"PVC_CONNECTION" is not specified, the CLI will attempt to read a "local" connection
    from the API configuration at "/etc/pvc/pvcapid.yaml". If no such configuration is found, the command will
    abort with an error. This applies to all commands except those under "connection".
    """

    global CLI_CONFIG
    store_data = get_store(store_path)
    CLI_CONFIG = get_config(store_data, _connection)

    # There is only one connection and no local connection, so even if nothing was passed, use it
    if len(store_data) == 1 and _connection is None and CLI_CONFIG.get("badcfg", None):
        CLI_CONFIG = get_config(store_data, list(store_data.keys())[0])

    if not CLI_CONFIG.get("badcfg", None):
        CLI_CONFIG["debug"] = _debug
        CLI_CONFIG["unsafe"] = _unsafe
        CLI_CONFIG["colour"] = _colour
        CLI_CONFIG["quiet"] = _quiet

    audit()


###############################################################################
# Click command tree
###############################################################################

cli_connection.add_command(cli_connection_add)
cli_connection.add_command(cli_connection_remove)
cli_connection.add_command(cli_connection_list)
cli_connection.add_command(cli_connection_detail)
cli.add_command(cli_connection)
# cli.add_command(testing)
