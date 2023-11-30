#!/usr/bin/env python3

# Daemon.py - Health daemon main entrypoing
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

import pvchealthd.util.zookeeper

import pvchealthd.objects.MonitoringInstance as MonitoringInstance
import pvchealthd.objects.NodeInstance as NodeInstance

import daemon_lib.config as cfg
import daemon_lib.log as log

from time import sleep

import os
import signal

# Daemon version
version = "0.9.82"


##########################################################
# Entrypoint
##########################################################


def entrypoint():
    monitoring_instance = None

    # Get our configuration
    config = cfg.get_configuration()
    config["daemon_name"] = "pvchealthd"
    config["daemon_version"] = version

    # Set up the logger instance
    logger = log.Logger(config)

    # Print our startup message
    logger.out("")
    logger.out("|--------------------------------------------------------------|")
    logger.out("|                                                              |")
    logger.out("|             ███████████ ▜█▙      ▟█▛ █████ █ █ █             |")
    logger.out("|                      ██  ▜█▙    ▟█▛  ██                      |")
    logger.out("|             ███████████   ▜█▙  ▟█▛   ██                      |")
    logger.out("|             ██             ▜█▙▟█▛    ███████████             |")
    logger.out("|                                                              |")
    logger.out("|--------------------------------------------------------------|")
    logger.out("| Parallel Virtual Cluster health daemon v{0: <20} |".format(version))
    logger.out("| Debug: {0: <53} |".format(str(config["debug"])))
    logger.out("| FQDN: {0: <54} |".format(config["node_fqdn"]))
    logger.out("| Host: {0: <54} |".format(config["node_hostname"]))
    logger.out("| ID: {0: <56} |".format(config["node_id"]))
    logger.out("| IPMI hostname: {0: <45} |".format(config["ipmi_hostname"]))
    logger.out("| Machine details:                                             |")
    logger.out("|   CPUs: {0: <52} |".format(config["static_data"][0]))
    logger.out("|   Arch: {0: <52} |".format(config["static_data"][3]))
    logger.out("|   OS: {0: <54} |".format(config["static_data"][2]))
    logger.out("|   Kernel: {0: <50} |".format(config["static_data"][1]))
    logger.out("|--------------------------------------------------------------|")
    logger.out("")
    logger.out(f'Starting pvchealthd on host {config["node_fqdn"]}', state="s")

    # Connect to Zookeeper and return our handler and current schema version
    zkhandler, _ = pvchealthd.util.zookeeper.connect(logger, config)

    # Define a cleanup function
    def cleanup(failure=False):
        nonlocal logger, zkhandler, monitoring_instance

        logger.out("Terminating pvchealthd and cleaning up", state="s")

        # Shut down the monitoring system
        try:
            logger.out("Shutting down monitoring subsystem", state="s")
            monitoring_instance.shutdown()
        except Exception:
            pass

        # Close the Zookeeper connection
        try:
            zkhandler.disconnect(persistent=True)
            del zkhandler
        except Exception:
            pass

        logger.out("Terminated health daemon", state="s")
        logger.terminate()

        if failure:
            retcode = 1
        else:
            retcode = 0

        os._exit(retcode)

    # Termination function
    def term(signum="", frame=""):
        cleanup(failure=False)

    # Hangup (logrotate) function
    def hup(signum="", frame=""):
        if config["file_logging"]:
            logger.hup()

    # Handle signals gracefully
    signal.signal(signal.SIGTERM, term)
    signal.signal(signal.SIGINT, term)
    signal.signal(signal.SIGQUIT, term)
    signal.signal(signal.SIGHUP, hup)

    this_node = NodeInstance.NodeInstance(
        config["node_hostname"],
        zkhandler,
        config,
        logger,
    )

    # Set up the node monitoring instance and thread
    monitoring_instance = MonitoringInstance.MonitoringInstance(
        zkhandler, config, logger, this_node
    )

    # Tick loop; does nothing since everything is async
    while True:
        try:
            sleep(1)
        except Exception:
            break
