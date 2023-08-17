#!/usr/bin/env python3

# helpers.py - PVC Click CLI helper function library
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

from click import echo as click_echo
from distutils.util import strtobool
from json import load as jload
from json import dump as jdump
from os import chmod, environ, getpid, path
from socket import gethostname
from sys import argv
from syslog import syslog, openlog, closelog, LOG_AUTH
from yaml import load as yload
from yaml import BaseLoader


DEFAULT_STORE_DATA = {"cfgfile": "/etc/pvc/pvcapid.yaml"}
DEFAULT_STORE_FILENAME = "pvc.json"
DEFAULT_API_PREFIX = "/api/v1"
DEFAULT_NODE_HOSTNAME = gethostname().split(".")[0]


def echo(config, message, newline=True, stderr=False):
    """
    Output a message with click.echo respecting our configuration
    """

    if config.get("colour", False):
        colour = True
    else:
        colour = None

    if config.get("silent", False):
        pass
    elif config.get("quiet", False) and stderr:
        pass
    else:
        click_echo(message=message, color=colour, nl=newline, err=stderr)


def audit():
    """
    Log an audit message to the local syslog AUTH facility
    """

    args = argv
    args[0] = "pvc"
    pid = getpid()

    openlog(facility=LOG_AUTH, ident=f"{args[0]}[{pid}]")
    syslog(
        f"""client audit: command "{' '.join(args)}" by user {environ.get('USER', None)}"""
    )
    closelog()


def read_config_from_yaml(cfgfile):
    """
    Read the PVC API configuration from the local API configuration file
    """

    try:
        with open(cfgfile) as fh:
            api_config = yload(fh, Loader=BaseLoader)["pvc"]["api"]

        host = api_config["listen_address"]
        port = api_config["listen_port"]
        scheme = "https" if strtobool(api_config["ssl"]["enabled"]) else "http"
        api_key = (
            api_config["authentication"]["tokens"][0]["token"]
            if strtobool(api_config["authentication"]["enabled"])
            else None
        )
    except KeyError:
        host = None
        port = None
        scheme = None
        api_key = None

    return cfgfile, host, port, scheme, api_key


def get_config(store_data, connection=None):
    """
    Load CLI configuration from store data
    """

    if store_data is None:
        return {"badcfg": True}

    connection_details = store_data.get(connection, None)

    if not connection_details:
        connection = "local"
        connection_details = DEFAULT_STORE_DATA

    if connection_details.get("cfgfile", None) is not None:
        if path.isfile(connection_details.get("cfgfile", None)):
            description, host, port, scheme, api_key = read_config_from_yaml(
                connection_details.get("cfgfile", None)
            )
            if None in [description, host, port, scheme]:
                return {"badcfg": True}
        else:
            return {"badcfg": True}
        # Rewrite a wildcard listener to use localhost instead
        if host == "0.0.0.0":
            host = "127.0.0.1"
    else:
        # This is a static configuration, get the details directly
        description = connection_details["description"]
        host = connection_details["host"]
        port = connection_details["port"]
        scheme = connection_details["scheme"]
        api_key = connection_details["api_key"]

    config = dict()
    config["debug"] = False
    config["connection"] = connection
    config["description"] = description
    config["api_host"] = f"{host}:{port}"
    config["api_scheme"] = scheme
    config["api_key"] = api_key
    config["api_prefix"] = DEFAULT_API_PREFIX
    if connection == "local":
        config["verify_ssl"] = False
    else:
        config["verify_ssl"] = bool(
            strtobool(environ.get("PVC_CLIENT_VERIFY_SSL", "True"))
        )

    return config


def get_store(store_path):
    """
    Load store information from the store path
    """

    store_file = f"{store_path}/{DEFAULT_STORE_FILENAME}"

    with open(store_file) as fh:
        try:
            store_data = jload(fh)
            return store_data
        except Exception:
            return dict()


def update_store(store_path, store_data):
    """
    Update store information to the store path, creating it (with sensible permissions) if needed
    """

    store_file = f"{store_path}/{DEFAULT_STORE_FILENAME}"

    if not path.exists(store_file):
        with open(store_file, "w") as fh:
            fh.write("")
        chmod(store_file, int(environ.get("PVC_CLIENT_DB_PERMS", "600"), 8))

    with open(store_file, "w") as fh:
        jdump(store_data, fh, sort_keys=True, indent=4)
