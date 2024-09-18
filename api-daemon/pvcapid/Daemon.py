#!/usr/bin/env python3

# Daemon.py - PVC HTTP API daemon
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

import subprocess
from ssl import SSLContext, TLSVersion
from distutils.util import strtobool as dustrtobool
import daemon_lib.config as cfg

# Daemon version
version = "0.9.100~git-73c0834f"

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

# Get our configuration
config = cfg.get_configuration()
config["daemon_name"] = "pvcapid"
config["daemon_version"] = version


##########################################################
# Flask App Creation for Gunicorn
##########################################################


def create_app():
    """
    Create and return the Flask app and SSL context if necessary.
    """
    # Import the Flask app from pvcapid.flaskapi after adjusting the path
    import pvcapid.flaskapi as pvc_api

    # Print our startup messages
    print("")
    print("|--------------------------------------------------------------|")
    print("|                                                              |")
    print("|             ███████████ ▜█▙      ▟█▛ █████ █ █ █             |")
    print("|                      ██  ▜█▙    ▟█▛  ██                      |")
    print("|             ███████████   ▜█▙  ▟█▛   ██                      |")
    print("|             ██             ▜█▙▟█▛    ███████████             |")
    print("|                                                              |")
    print("|--------------------------------------------------------------|")
    print("| Parallel Virtual Cluster API daemon v{0: <23} |".format(version))
    print("| Debug: {0: <53} |".format(str(config["debug"])))
    print("| API version: v{0: <46} |".format(API_VERSION))
    print(
        "| Listen: {0: <52} |".format(
            "{}:{}".format(config["api_listen_address"], config["api_listen_port"])
        )
    )
    print("| SSL: {0: <55} |".format(str(config["api_ssl_enabled"])))
    print("| Authentication: {0: <44} |".format(str(config["api_auth_enabled"])))
    print("|--------------------------------------------------------------|")
    print("")

    pvc_api.celery_startup()

    return pvc_api.app


##########################################################
# Entrypoint
##########################################################


def entrypoint():
    if config["debug"]:
        app = create_app()

        if config["api_ssl_enabled"]:
            ssl_context = SSLContext()
            ssl_context.minimum_version = TLSVersion.TLSv1
            ssl_context.get_ca_certs()
            ssl_context.load_cert_chain(
                config["api_ssl_cert_file"], keyfile=config["api_ssl_key_file"]
            )
        else:
            ssl_context = None

        app.run(
            config["api_listen_address"],
            config["api_listen_port"],
            threaded=True,
            ssl_context=ssl_context,
        )
    else:
        # Build the command to run Gunicorn
        gunicorn_cmd = [
            "gunicorn",
            "--workers",
            "1",
            "--threads",
            "8",
            "--timeout",
            "86400",
            "--bind",
            "{}:{}".format(config["api_listen_address"], config["api_listen_port"]),
            "pvcapid.Daemon:create_app()",
            "--log-level",
            "info",
            "--access-logfile",
            "-",
            "--error-logfile",
            "-",
        ]

        if config["api_ssl_enabled"]:
            gunicorn_cmd += [
                "--certfile",
                config["api_ssl_cert_file"],
                "--keyfile",
                config["api_ssl_key_file"],
            ]

        # Run Gunicorn
        try:
            subprocess.run(gunicorn_cmd)
        except KeyboardInterrupt:
            exit(0)
        except Exception as e:
            print(e)
            exit(1)
