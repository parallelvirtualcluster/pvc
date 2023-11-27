#!/usr/bin/env python3

# Daemon.py - PVC HTTP API daemon
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2022 Joshua M. Boniface <joshua@boniface.me>
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

import os
import yaml

from ssl import SSLContext, TLSVersion

from distutils.util import strtobool as dustrtobool

# Daemon version
version = "0.9.82"

# API version
API_VERSION = 1.0


##########################################################
# Helper Functions
##########################################################


def strtobool(stringv):
    if stringv is None:
        return False
    if isinstance(stringv, bool):
        return bool(stringv)
    try:
        return bool(dustrtobool(stringv))
    except Exception:
        return False


##########################################################
# Configuration Parsing
##########################################################

# Parse the configuration file
config_file = None
try:
    _config_file = "/etc/pvc/pvcapid.yaml"
    if not os.path.exists(_config_file):
        raise
    config_file = _config_file
    config_type = "legacy"
except Exception:
    pass
try:
    _config_file = os.environ["PVC_CONFIG_FILE"]
    if not os.path.exists(_config_file):
        raise
    config_file = _config_file
    config_type = "current"
except Exception:
    pass

if not config_file:
    print(
        'Error: The "PVC_CONFIG_FILE" environment variable must be set before starting pvcapid.'
    )
    exit(1)


def load_configuration_file(config_file):
    print('Loading configuration from file "{}"'.format(config_file))

    # Read in the config
    try:
        with open(config_file, "r") as cfgfile:
            o_config = yaml.load(cfgfile, Loader=yaml.BaseLoader)
    except Exception as e:
        print("ERROR: Failed to parse configuration file: {}".format(e))
        exit(1)

    return o_config


def get_configuration_current(config_file):
    o_config = load_configuration_file(config_file)
    try:
        # Create the config object
        config = {
            "debug": strtobool(o_config["logging"].get("debug_logging", "False")),
            "coordinators": o_config["cluster"]["all_coordinators"],
            "listen_address": o_config["api"]["listen"]["address"],
            "listen_port": int(o_config["api"]["listen"]["port"]),
            "auth_enabled": strtobool(
                o_config["api"]["authentication"].get("enabled", "False")
            ),
            "auth_secret_key": o_config["api"]["authentication"]["secret_key"],
            "auth_source": o_config["api"]["authentication"]["source"],
            "ssl_enabled": strtobool(o_config["api"]["ssl"].get("enabled", "False")),
            "ssl_cert_file": o_config["api"]["ssl"]["certificate"],
            "ssl_key_file": o_config["api"]["ssl"]["private_key"],
            "database_port": o_config["database"]["postgres"]["port"],
            "database_host": o_config["database"]["postgres"]["hostname"],
            "database_name": o_config["database"]["postgres"]["credentials"]["api"][
                "database"
            ],
            "database_user": o_config["database"]["postgres"]["credentials"]["api"][
                "username"
            ],
            "database_password": o_config["database"]["postgres"]["credentials"]["api"][
                "password"
            ],
            "queue_port": o_config["database"]["keydb"]["port"],
            "queue_host": o_config["database"]["keydb"]["hostname"],
            "queue_path": o_config["database"]["keydb"]["path"],
            "storage_domain": o_config["cluster"]["networks"]["storage"]["domain"],
            "storage_hosts": o_config["ceph"].get("monitor_hosts", None),
            "ceph_monitor_port": o_config["ceph"]["monitor_port"],
            "ceph_storage_secret_uuid": o_config["ceph"]["secret_uuid"],
        }

        # Use coordinators as storage hosts if not explicitly specified
        if not config["storage_hosts"] or len(config["storage_hosts"]) < 1:
            config["storage_hosts"] = config["coordinators"]

        # Set up our token list if specified
        if config["auth_source"] == "token":
            config["auth_tokens"] = o_config["api"]["token"]
        else:
            if config["auth_enabled"]:
                print(
                    "WARNING: No authentication method provided; disabling authentication."
                )
                config["auth_enabled"] = False

    except Exception as e:
        print(f"ERROR: Failed to load configuration: {e}")
        exit(1)

    return config


def get_configuration_legacy(config_file):
    o_config = load_configuration_file(config_file)
    try:
        # Create the config object
        config = {
            "debug": strtobool(o_config["pvc"]["debug"]),
            "coordinators": o_config["pvc"]["coordinators"],
            "listen_address": o_config["pvc"]["api"]["listen_address"],
            "listen_port": int(o_config["pvc"]["api"]["listen_port"]),
            "auth_enabled": strtobool(
                o_config["pvc"]["api"]["authentication"]["enabled"]
            ),
            "auth_secret_key": o_config["pvc"]["api"]["authentication"]["secret_key"],
            "auth_tokens": o_config["pvc"]["api"]["authentication"]["tokens"],
            "ssl_enabled": strtobool(o_config["pvc"]["api"]["ssl"]["enabled"]),
            "ssl_key_file": o_config["pvc"]["api"]["ssl"]["key_file"],
            "ssl_cert_file": o_config["pvc"]["api"]["ssl"]["cert_file"],
            "database_host": o_config["pvc"]["provisioner"]["database"]["host"],
            "database_port": int(o_config["pvc"]["provisioner"]["database"]["port"]),
            "database_name": o_config["pvc"]["provisioner"]["database"]["name"],
            "database_user": o_config["pvc"]["provisioner"]["database"]["user"],
            "database_password": o_config["pvc"]["provisioner"]["database"]["pass"],
            "queue_host": o_config["pvc"]["provisioner"]["queue"]["host"],
            "queue_port": o_config["pvc"]["provisioner"]["queue"]["port"],
            "queue_path": o_config["pvc"]["provisioner"]["queue"]["path"],
            "storage_hosts": o_config["pvc"]["provisioner"]["ceph_cluster"][
                "storage_hosts"
            ],
            "storage_domain": o_config["pvc"]["provisioner"]["ceph_cluster"][
                "storage_domain"
            ],
            "ceph_monitor_port": o_config["pvc"]["provisioner"]["ceph_cluster"][
                "ceph_monitor_port"
            ],
            "ceph_storage_secret_uuid": o_config["pvc"]["provisioner"]["ceph_cluster"][
                "ceph_storage_secret_uuid"
            ],
        }

        # Use coordinators as storage hosts if not explicitly specified
        if not config["storage_hosts"]:
            config["storage_hosts"] = config["coordinators"]

    except Exception as e:
        print("ERROR: Failed to load configuration: {}".format(e))
        exit(1)

    return config


if config_type == "legacy":
    config = get_configuration_legacy(config_file)
else:
    config = get_configuration_current(config_file)

##########################################################
# Entrypoint
##########################################################


def entrypoint():
    import pvcapid.flaskapi as pvc_api  # noqa: E402

    if config["ssl_enabled"]:
        context = SSLContext()
        context.minimum_version = TLSVersion.TLSv1
        context.get_ca_certs()
        context.load_cert_chain(config["ssl_cert_file"], keyfile=config["ssl_key_file"])
    else:
        context = None

    # Print our startup messages
    print("")
    print("|------------------------------------------------------------|")
    print("|                                                            |")
    print("|            ███████████ ▜█▙      ▟█▛ █████ █ █ █            |")
    print("|                     ██  ▜█▙    ▟█▛  ██                     |")
    print("|            ███████████   ▜█▙  ▟█▛   ██                     |")
    print("|            ██             ▜█▙▟█▛    ███████████            |")
    print("|                                                            |")
    print("|------------------------------------------------------------|")
    print("| Parallel Virtual Cluster API daemon v{0: <21} |".format(version))
    print("| Debug: {0: <51} |".format(str(config["debug"])))
    print("| API version: v{0: <44} |".format(API_VERSION))
    print(
        "| Listen: {0: <50} |".format(
            "{}:{}".format(config["listen_address"], config["listen_port"])
        )
    )
    print("| SSL: {0: <53} |".format(str(config["ssl_enabled"])))
    print("| Authentication: {0: <42} |".format(str(config["auth_enabled"])))
    print("|------------------------------------------------------------|")
    print("")

    pvc_api.celery_startup()
    pvc_api.app.run(
        config["listen_address"],
        config["listen_port"],
        threaded=True,
        ssl_context=context,
    )
