# Node health plugins

The PVC node daemon includes a node health plugin system. These plugins are run during keepalives to check various aspects of node health and adjust the overall node and cluster health accordingly. For example, a plugin might check that all configured network interfaces are online and operating at their correct speed, or that all operating system packages are up-to-date.

## Configuration

### Plugin Directory

The PVC node configuration includes a configuration option at `system` → `configuration` → `directories` → `plugin_directory` to configure the location of health plugin files on the system. By default if unset, this directory is `/usr/share/pvc/plugins`. An administrator can override this directory if they wish, though custom plugins can be installed to this directory without problems, and thus it is not recommended that it be changed.

### Plugin Logging

Plugin output is logged by default during keepalive messages. This is controlled by the node configuration option at `system` → `configuration` → `logging` → `log_keepalive_plugin_details`. Regardless of this setting, the overall node health is logged at the end of the plugin run.

### Disabling Node Plugins

Node plugins cannot be disabled; at best, a suite of zero plugins can be specified by pointing the above plugin directory to an empty folder. This will effectively render the node at a permanent 100% health. Note however that overall cluster health will still be affected by cluster-wide events (e.g. nodes or VMs being stopped, OSDs going out, etc.).

## Health Plugin Architecture

### Node and Cluster Health

A core concept leveraged by the PVC system is that of node and cluster health. Starting with PVC version 0.9.61, these two health statistics are represented as percentages, with 100% representing optimal health, 51-90% representing a "warning" degraded state, and 0-50% representing a "critical" degraded state.

While a cluster is in maintenance mode (set via `pvc maintenance on` and unset via `pvc maintenance off`), the health values continue to aggregate, but the value is ignored for the purposes of "health" output, i.e. its output colour will not change, and the reference monitoring plugins (for CheckMK and Munin) will not trigger alerting. This allows the administrator to specify that abnormal conditions are OK for some amount of time without triggering upstream alerting. Additionally, while a node is not in `run` Daemon state, its health will be reported as `N/A`, which is treated as 100% but displayed as such to make clear that the node has not initialized and run its health check plugins (yet).

The node health is affected primarily by health plugins as discussed in this manual. Any plugin that adjusts node health lowers the node's health by its `health_delta` value, as well as the cluster health by its `health_delta` value. For example, a plugin might have a `health_delta` in a current state of `10`, which reduces its own node's health value to 90%, and the overall cluster health value to 90%.

In addition, cluster health is affected by several fixed states within the PVC system. These are:

* A node in `flushed` Domain state lowers the cluster health by 10; a node in `stop` Daemon state lowers the cluster health by 50.

* A VM in `stop` state lowers the cluster health by 10 (hint: use `disable` state to avoid this).

* An OSD in `down` state lowers the cluster health by 10; an OSD in `out` state lowers the cluster health by 50.

* Memory overprovisioning (total provisioned and running guest memory allocation exceeds the total N-1 cluster memory availability) lowers the cluster health by 50.

* Each Ceph health check message lowers the cluster health by 10 for a `HEALTH_WARN` severity or by 50 for a `HEALTH_ERR` severity. For example, the `OSDMAP_FLAGS` check (reporting, e.g. `noout` state) reports as a `HEALTH_WARN` severity and will thus decrease the cluster health by 10; if an additional `PG_DEGRADED` check fires (also reporting as `HEALTH_WARN` severity), this will decrease the cluster health by a further 10, or 20 total for both. This cumulative effect ensures that multiple simultaneous Ceph issues escalate in severity. For a full list of possible Ceph health check messages, [please see the Ceph documentation](https://docs.ceph.com/en/nautilus/rados/operations/health-checks/).

### Built-in Health Plugins

PVC ships with several node health plugins installed and loaded by default, to ensure several common aspects of node operation are validated and checked. The following plugins are included:

#### `disk`

This plugin checks all SATA/SAS and NVMe block devices for SMART health, if available, and reports any errors.

For SATA/SAS disks reporting standard ATA SMART attributes, a health delta of 10 is raised for each SMART error on each disk, based on the `when_failed` value being set to true. Note that due to this design, several disks with multiple errors can quickly escalate to a critical condition, quickly alerting the administrator of possible major faults.

For NVMe disks, only 3 specific NVMe health information messages are checked: `critical_warning`, `media_errors`, and `percentage_used` at > 90. Each check can only be reported once per disk and each raises a health delta of 10.

#### `dpkg`

This plugin checks for Debian package updates, invalid package states (i.e. not `ii` state), and obsolete configuration files that require cleanup. It will raise a health delta of 1 for each type of inconsistency, for a maximum of 3. It will thus never, on its own, trigger a node or cluster to be in a warning or critical state, but will show the errors for administrator analysis, as an example of a more "configuration anomaly"-type plugin.

#### `edac`

This plugin checks the EDAC utility for messages about errors, primarily in the ECC memory subsystem. It will raise a health delta of 50 if any `Uncorrected` EDAC errors are detected, possibly indicating failing memory.

#### `ipmi`

This plugin checks whether the daemon can reach its own IPMI address and connect. If it cannot, it raises a health delta of 10.

#### `lbvt`

This plugin checks whether the daemon can connect to the local Libvirt daemon instance. If it cannot, it raises a health delta of 50.

#### `load`

This plugin checks the current 1-minute system load (as reported during keepalives) against the number of total CPU threads available on the node. If the load average is greater, i.e. the node is overloaded, it raises a health delta of 50.

#### `nics`

This plugin checks that all NICs underlying PVC networks and bridges are operating correctly, specifically that bond interfaces have at least 2 active slaves and that all physical NICs are operating at their maximum possible speed. It takes into account several possible options to determine this.

* For each device defined (`bridge_dev`, `upstream_dev`, `cluster_dev`, and `storage_dev`), it determines the type of device. If it is a vLAN, it obtains the underlying device; otherwise, it uses the specified device. It then adds this device to a list of core NICs. Ideally, this list will contain either bonding interfaces or actual ethernet NICs.

* For each core NIC, it checks its type. If it is a `bond` device, it checks the bonding state to ensure that at least 2 slave interfaces are up and operating. If there are not, it raises a health delta of 10.

* For each core NIC, it checks its maximum possible speed as reported by `ethtool` as well as the current active speed. If the NIC is operating at less than its maximum possible speed, it raises a health delta of 10.

Note that this check may pose problems in some deployment scenarios (e.g. running 25GbE NICs at 10GbE by design). Currently the plugin logic cannot handle this and manual modifications may be required. This is left to the administrator if applicable.

#### `psql`

This plugin checks whether the daemon can connect to the local PostgreSQL/Patroni daemon instance. If it cannot, it raises a health delta of 50.

#### `zkpr`

This plugin checks whether the daemon can connect to the local Zookeeper daemon instance. If it cannot, it raises a health delta of 50.

### Custom Health Plugins

In addition to the included health plugins, the plugin architecture allows administrators to write their own plugins as required to check specific node details that might not be checked by the default plugins. While the author has endeavoured to cover as many important aspects as possible with the default plugins, there is always the possibility that some other condition becomes important and thus the system is flexible to this need. That said, we would welcome pull requests of new plugins to future version of PVC should they be widely applicable.

As a warning, health plugins are run in a `root` context by PVC. They must therefore be carefully vetted to avoid damaging the system. DO NOT run untrusted health plugins.

To create a health plugin, first reference the existing health plugins and create a base template.

Each health plugin consists of three main parts:

* An import, which must at least include the `MonitoringPlugin` class from the `pvcnoded.objects.MonitoringInstance` library. You can also load additional imports here, or import them within the functions (which is recommended for namespace simplicity).

```
# This import is always required here, as MonitoringPlugin is used by the MonitoringPluginScript class
from pvcnoded.objects.MonitoringInstance import MonitoringPlugin
```


* A `PLUGIN_NAME` variable which defines the name of the plugin. This must match the filename. Generally, a plugin name will be 4 characters, but this is purely a convention and not a requirement.

```
# A monitoring plugin script must always expose its nice name, which must be identical to the file name
PLUGIN_NAME = "nics"
```

* An instance of a `MonitoringPluginScript` class which extends the `MonitoringPlugin` class.

```
# The MonitoringPluginScript class must be named as such, and extend MonitoringPlugin.
class MonitoringPluginScript(MonitoringPlugin):
    ...
```

Within the `MonitoringPluginScript` class must be 3 primary functions as detailed below. While it is possible to do nothing except `pass` in these functions, or even exclude them (the parent includes empty defaults), all 3 should be included for consistency.

#### `def setup(self):`

This function is run once during the node daemon startup, when the plugin is loaded. It can be used to get one-time setup information, populate plugin instance variables, etc.

The function must take no arguments except `self` and anything returned is ignored.

A plugin can also be disabled live in the setup function by throwing any `Exception`. Such exceptions will be caught and the plugin will not be loaded in such a case.

#### `def cleanup(self):`

This function mirrors the setup function, and is run once during the node daemon shutdown process. It can be used to clean up any lingering items (e.g. temporary files) created by the setup or run functions, if required; generally plugins do not need to do any cleanup.

#### `def run(self):`

This function is run each time the plugin is called during a keepalive. It performs the main work of the plugin before returning the end result in a specific format.

Note that this function runs once for each keepalive, which by default is every 5 seconds. It is thus important to keep the runtime as short as possible and avoid doing complex calculations, file I/O, etc. during the plugin run. Do as much as possible in the setup function to keep the run function as quick as possible. A good safe maximum time for any plugin (e.g. if implementing an internal timeout) is 2 seconds.

What happens during the run function is of course completely up to the plugin, but it must return a standardized set of details upon completing the run.

An instance of the `PluginResult` object is helpfully created by the caller and passed in via `self.plugin_result`. This can be used to set the results as follows:

* The `self.plugin_result.set_health_delta()` function can be used to set the current health delta of the result. This should be `0` unless the plugin detects a fault, at which point it can be any integer value below 100, and affects the node and cluster health as detailed above.

* The `self.plugin_result.set_message()` function can be used to set the message text of the result, explaining in a short but human-readable way what the plugin result is. This will be shown in several places, including the node logs (if enabled), the node info output, and for results that have a health delta above 0, in the cluster status output.

Finally, the `PluginResult` instance stored as `self.plugin_result` must be returned by the run function to the caller upon completion so that it can be added to the node state.

### Logging

The MonitoringPlugin class provides a helper logging method (usable as `self.log()`) to assist a plugin author in logging messages to the node daemon console log. This function takes one primary argument, a string message, and an optional `state` keyword argument for alternate states.

The default state is `d` for debug, e.g. `state="d"`. The possible states for log messages are:

* `"d"`: Debug, only printed when the administrator has debug logging enabled. Useful for detailed analysis of the plugin run state.
* `"i"`: Informational, printed at all times but with no intrinsic severity. Use these very sparingly if at all.
* `"t"`: Tick, matches the output of the keepalive itself. Use these very sparingly if at all.
* `"w"`: Warning, prints a warning message. Use these for non-fatal error conditions within the plugin.
* `"e"`: Error, prints an error message. Use these for fatal error conditions within the plugin.

None of the example plugins make use of the logging interface, but it is available for custom plugins should it be required.

The final output message of each plugin is automatically logged to the node daemon console log with `"t"` state at the completion of all plugins, if the `log_keepalive_plugin_details` configuration option is true. Otherwise, no final output is displayed. This setting does not affect messages printed from within a plugin.

### Example Health Plugin

This is a terse example of the `load` plugin, which is an extremely simple example that shows all the above requirements clearly. Comments are omitted here for simplicity, but these can be seen in the actual plugin file (at `/usr/share/pvc/plugins/load` on any node).

```
#!/usr/bin/env python3

# load.py: PVC monitoring plugin example

from pvcnoded.objects.MonitoringInstance import MonitoringPlugin

PLUGIN_NAME = "load"

class MonitoringPluginScript(MonitoringPlugin):
    def setup(self):
        pass

    def cleanup(self):
        pass

    def run(self):
        from os import getloadavg
        from psutil import cpu_count

        load_average = getloadavg()[0]
        cpu_cores = cpu_count()

        if load_average > float(cpu_cores):
            health_delta = 50
        else:
            health_delta = 0

        message = f"Current load is {load_average} out pf {cpu_cores} CPU cores"

        self.plugin_result.set_health_delta(health_delta)
        self.plugin_result.set_message(message)

        return self.plugin_result
```
