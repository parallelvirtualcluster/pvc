#!/usr/bin/env python3

# MonitoringInstance.py - Class implementing a PVC monitor in pvchealthd
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

import concurrent.futures
import time
import importlib.util

from os import walk
from datetime import datetime
from json import dumps
from apscheduler.schedulers.background import BackgroundScheduler


class PluginError(Exception):
    """
    An exception that results from a plugin failing setup
    """

    pass


class PluginResult(object):
    def __init__(self, zkhandler, config, logger, this_node, plugin_name):
        self.zkhandler = zkhandler
        self.config = config
        self.logger = logger
        self.this_node = this_node
        self.plugin_name = plugin_name
        self.current_time = int(time.time())
        self.health_delta = 0
        self.message = "N/A"
        self.data = {}
        self.runtime = "0.00"

    def set_health_delta(self, new_delta):
        self.health_delta = new_delta

    def set_message(self, new_message):
        self.message = new_message

    def set_data(self, new_data):
        self.data = new_data

    def set_runtime(self, new_runtime):
        self.runtime = new_runtime

    def to_zookeeper(self):
        self.zkhandler.write(
            [
                (
                    (
                        "node.monitoring.data",
                        self.this_node.name,
                        "monitoring_plugin.name",
                        self.plugin_name,
                    ),
                    self.plugin_name,
                ),
                (
                    (
                        "node.monitoring.data",
                        self.this_node.name,
                        "monitoring_plugin.last_run",
                        self.plugin_name,
                    ),
                    self.current_time,
                ),
                (
                    (
                        "node.monitoring.data",
                        self.this_node.name,
                        "monitoring_plugin.health_delta",
                        self.plugin_name,
                    ),
                    self.health_delta,
                ),
                (
                    (
                        "node.monitoring.data",
                        self.this_node.name,
                        "monitoring_plugin.message",
                        self.plugin_name,
                    ),
                    self.message,
                ),
                (
                    (
                        "node.monitoring.data",
                        self.this_node.name,
                        "monitoring_plugin.data",
                        self.plugin_name,
                    ),
                    dumps(self.data),
                ),
                (
                    (
                        "node.monitoring.data",
                        self.this_node.name,
                        "monitoring_plugin.runtime",
                        self.plugin_name,
                    ),
                    self.runtime,
                ),
            ]
        )


class MonitoringPlugin(object):
    def __init__(self, zkhandler, config, logger, this_node, plugin_name):
        self.zkhandler = zkhandler
        self.config = config
        self.logger = logger
        self.this_node = this_node
        self.plugin_name = plugin_name

        self.plugin_result = PluginResult(
            self.zkhandler,
            self.config,
            self.logger,
            self.this_node,
            self.plugin_name,
        )

    def __str__(self):
        return self.plugin_name

    #
    # Helper functions; exposed to child MonitoringPluginScript instances
    #
    def log(self, message, state="d"):
        """
        Log a message to the PVC logger instance using the plugin name as a prefix
        Takes "state" values as defined by the PVC logger instance, defaulting to debug:
            "d": debug
            "i": informational
            "t": tick/keepalive
            "w": warning
            "e": error
        """
        if state == "d" and not self.config["debug"]:
            return

        self.logger.out(message, state=state, prefix=self.plugin_name)

    #
    # Primary class functions; implemented by the individual plugins
    #
    def setup(self):
        """
        setup(): Perform setup of the plugin; run once during daemon startup

        This step is optional and should be used sparingly.

        If you wish for the plugin to not load in certain conditions, do any checks here
        and return a non-None failure message to indicate the error.
        """
        pass

    def run(self, coordinator_state=None):
        """
        run(): Run the plugin, returning a PluginResult object

        The {coordinator_state} can be used to check if this is a "primary" coordinator, "secondary" coordinator, or "client" (non-coordinator)
        """
        return self.plugin_result

    def cleanup(self):
        """
        cleanup(): Clean up after the plugin; run once during daemon shutdown
        OPTIONAL
        """
        pass


class MonitoringInstance(object):
    def __init__(self, zkhandler, config, logger, this_node):
        self.zkhandler = zkhandler
        self.config = config
        self.logger = logger
        self.this_node = this_node

        # Get a list of plugins from the plugin_directory
        plugin_files = next(walk(self.config["plugin_directory"]), (None, None, []))[
            2
        ]  # [] if no file

        self.all_plugins = list()
        self.all_plugin_names = list()

        successful_plugins = 0

        # Load each plugin file into the all_plugins list
        for plugin_file in sorted(plugin_files):
            try:
                self.logger.out(
                    f"Loading monitoring plugin from {self.config['plugin_directory']}/{plugin_file}",
                    state="i",
                )
                loader = importlib.machinery.SourceFileLoader(
                    "plugin_script", f"{self.config['plugin_directory']}/{plugin_file}"
                )
                spec = importlib.util.spec_from_loader(loader.name, loader)
                plugin_script = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(plugin_script)

                plugin = plugin_script.MonitoringPluginScript(
                    self.zkhandler,
                    self.config,
                    self.logger,
                    self.this_node,
                    plugin_script.PLUGIN_NAME,
                )

                failed_setup = plugin.setup()
                if failed_setup is not None:
                    raise PluginError(f"{failed_setup}")

                # Create plugin key
                self.zkhandler.write(
                    [
                        (
                            (
                                "node.monitoring.data",
                                self.this_node.name,
                                "monitoring_plugin.name",
                                plugin.plugin_name,
                            ),
                            plugin.plugin_name,
                        ),
                        (
                            (
                                "node.monitoring.data",
                                self.this_node.name,
                                "monitoring_plugin.last_run",
                                plugin.plugin_name,
                            ),
                            "0",
                        ),
                        (
                            (
                                "node.monitoring.data",
                                self.this_node.name,
                                "monitoring_plugin.health_delta",
                                plugin.plugin_name,
                            ),
                            "0",
                        ),
                        (
                            (
                                "node.monitoring.data",
                                self.this_node.name,
                                "monitoring_plugin.message",
                                plugin.plugin_name,
                            ),
                            "Initializing",
                        ),
                        (
                            (
                                "node.monitoring.data",
                                self.this_node.name,
                                "monitoring_plugin.data",
                                plugin.plugin_name,
                            ),
                            dumps({}),
                        ),
                        (
                            (
                                "node.monitoring.data",
                                self.this_node.name,
                                "monitoring_plugin.runtime",
                                plugin.plugin_name,
                            ),
                            "0.00",
                        ),
                    ]
                )

                self.all_plugins.append(plugin)
                self.all_plugin_names.append(plugin.plugin_name)
                successful_plugins += 1

                self.logger.out(
                    f"Successfully loaded monitoring plugin '{plugin.plugin_name}'",
                    state="o",
                )
            except Exception as e:
                self.logger.out(
                    f"Failed to load monitoring plugin: {e}",
                    state="w",
                )

        self.zkhandler.write(
            [
                (
                    ("node.monitoring.plugins", self.this_node.name),
                    " ".join(self.all_plugin_names),
                ),
            ]
        )

        if successful_plugins < 1:
            self.logger.out(
                "No plugins loaded; pvchealthd going into noop loop. Incorrect plugin directory? Fix and restart pvchealthd.",
                state="e",
            )
            return

        self.logger.out(
            f'{self.logger.fmt_cyan}Plugin list:{self.logger.fmt_end} {" ".join(self.all_plugin_names)}',
            state="s",
        )

        # Clean up any old plugin data for which a plugin file no longer exists
        plugins_data = self.zkhandler.children(
            ("node.monitoring.data", self.this_node.name)
        )
        if plugins_data is not None:
            for plugin_key in plugins_data:
                if plugin_key not in self.all_plugin_names:
                    self.zkhandler.delete(
                        (
                            "node.monitoring.data",
                            self.this_node.name,
                            "monitoring_plugin",
                            plugin_key,
                        )
                    )

        self.run_plugins()
        self.start_check_timer()

    def __del__(self):
        self.shutdown()

    def shutdown(self):
        self.stop_check_timer()
        self.run_cleanups()
        return

    def start_check_timer(self):
        check_interval = self.config["monitoring_interval"]
        self.logger.out(
            f"Starting monitoring check timer ({check_interval} second interval)",
            state="s",
        )
        self.check_timer = BackgroundScheduler()
        self.check_timer.add_job(
            self.run_plugins,
            trigger="interval",
            seconds=check_interval,
        )
        self.check_timer.start()

    def stop_check_timer(self):
        try:
            self.check_timer.shutdown()
            self.logger.out("Stopping monitoring check timer", state="s")
        except Exception:
            self.logger.out("Failed to stop monitoring check timer", state="w")

    def run_plugin(self, plugin):
        time_start = datetime.now()
        try:
            result = plugin.run(coordinator_state=self.this_node.coordinator_state)
        except Exception as e:
            self.logger.out(
                f"Monitoring plugin {plugin.plugin_name} failed: {type(e).__name__}: {e}",
                state="e",
            )
            # Whatever it had, we try to return
            return plugin.plugin_result
        time_end = datetime.now()
        time_delta = time_end - time_start
        runtime = "{:0.02f}".format(time_delta.total_seconds())
        result.set_runtime(runtime)
        result.to_zookeeper()
        return result

    def run_plugins(self):
        if self.this_node.coordinator_state == "primary":
            cst_colour = self.logger.fmt_green
        elif self.this_node.coordinator_state == "secondary":
            cst_colour = self.logger.fmt_blue
        else:
            cst_colour = self.logger.fmt_cyan

        active_coordinator_state = self.this_node.coordinator_state

        runtime_start = datetime.now()
        total_health = 100
        plugin_results = list()
        with concurrent.futures.ThreadPoolExecutor(max_workers=99) as executor:
            to_future_plugin_results = {
                executor.submit(self.run_plugin, plugin): plugin
                for plugin in self.all_plugins
            }
            for future in concurrent.futures.as_completed(to_future_plugin_results):
                plugin_results.append(future.result())

        for result in sorted(plugin_results, key=lambda x: x.plugin_name):
            if (
                self.config["log_keepalives"]
                and self.config["log_keepalive_plugin_details"]
            ):
                self.logger.out(
                    result.message + f" [-{result.health_delta}]",
                    state="t",
                    prefix=f"{result.plugin_name} ({result.runtime}s)",
                )
            total_health -= result.health_delta

        if total_health < 0:
            total_health = 0

        self.zkhandler.write(
            [
                (
                    ("node.monitoring.health", self.this_node.name),
                    total_health,
                ),
            ]
        )

        runtime_end = datetime.now()
        runtime_delta = runtime_end - runtime_start
        runtime = "{:0.02f}".format(runtime_delta.total_seconds())
        time.sleep(0.2)

        if isinstance(self.this_node.health, int):
            if self.this_node.health > 90:
                health_colour = self.logger.fmt_green
            elif self.this_node.health > 50:
                health_colour = self.logger.fmt_yellow
            else:
                health_colour = self.logger.fmt_red
            health_text = str(self.this_node.health) + "%"
        else:
            health_colour = self.logger.fmt_blue
            health_text = "N/A"

        self.logger.out(
            "{start_colour}{hostname} healthcheck @ {starttime}{nofmt} [{cst_colour}{costate}{nofmt}] result is {health_colour}{health}{nofmt} in {runtime} seconds".format(
                start_colour=self.logger.fmt_purple,
                cst_colour=self.logger.fmt_bold + cst_colour,
                health_colour=health_colour,
                nofmt=self.logger.fmt_end,
                hostname=self.config["node_hostname"],
                starttime=runtime_start,
                costate=active_coordinator_state,
                health=health_text,
                runtime=runtime,
            ),
            state="t",
        )

    def run_cleanup(self, plugin):
        return plugin.cleanup()

    def run_cleanups(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=99) as executor:
            to_future_plugin_results = {
                executor.submit(self.run_cleanup, plugin): plugin
                for plugin in self.all_plugins
            }
            for future in concurrent.futures.as_completed(to_future_plugin_results):
                # This doesn't do anything, just lets us wait for them all to complete
                pass
        # Set the node health to None as no previous checks are now valid
        self.zkhandler.write(
            [
                (
                    ("node.monitoring.health", self.this_node.name),
                    None,
                ),
            ]
        )
