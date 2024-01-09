## PVC Changelog

###### [v0.9.89](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.89)

  * [API/Worker Daemons] Fixes a bug with the Celery result backends not being properly initialized on Debian 10/11.
  * [API Daemon] Fixes a bug if VM CPU stats are missing on Debian 10.

###### [v0.9.88](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.88)

  * [API Daemon] Adds an additional Prometheus metrics proxy for Zookeeper stats.
  * [API Daemon] Adds a new configuration to enable or disable metric endpoints if desired, defaulting to enabled.
  * [API Daemon] Alters and adjusts the metrics output for VMs to complement new dashboard.
  * [CLI Client] Adds a "json-prometheus" output format to "pvc connection list" to auto-generate file SD configs.
  * [Monitoring] Adds a new VM dashboard, updates the Cluster dashboard, and adds a README.

###### [v0.9.87](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.87)

  * [API Daemon] Adds cluster Prometheus resource utilization metrics and an updated Grafana dashboard.
  * [Node Daemon] Adds network traffic rate calculation subsystem.
  * [All Daemons] Fixes a printing bug where newlines were not added atomically.
  * [CLI Client] Fixes a bug listing connections if no default is specified.
  * [All Daemons] Simplifies debug logging conditionals by moving into the Logger instance itself.

###### [v0.9.86](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.86)

  * [API Daemon] Significantly improves the performance of several commands via async Zookeeper calls and removal of superfluous backend calls.
  * [Docs] Improves the project README and updates screenshot images to show the current output and more functionality.
  * [API Daemon/CLI] Corrects some bugs in VM metainformation output.
  * [Node Daemon] Fixes resource reporting bugs from 0.9.81 and properly clears node resource numbers on a fence.
  * [Health Daemon] Adds a wait during pvchealthd startup until the node is in run state, to avoid erroneous faults during node bootup.
  * [API Daemon] Fixes an incorrect reference to legacy pvcapid.yaml file in migration script.

###### [v0.9.85](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.85)

  * [Packaging] Fixes a dependency bug introduced in 0.9.84
  * [Node Daemon] Fixes an output bug during keepalives
  * [Node Daemon] Fixes a bug in the example Prometheus Grafana dashboard

###### [v0.9.84](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.84)

  **Breaking Changes:** This release features a major reconfiguration to how monitoring and reporting of the cluster health works. Node health plugins now report "faults", as do several other issues which were previously manually checked for in "cluster" daemon library for the "/status" endpoint, from within the Health daemon. These faults are persistent, and under each given identifier can be triggered once and subsequent triggers simply update the "last reported" time. An additional set of API endpoints and commands are added to manage these faults, either by "ack"(nowledging) them (keeping the alert around to be further updated but setting its health delta to 0%), or "delete"ing them (completely removing the fault unless it retriggers), both individually, to (from the CLI) multiple, or all. Cluster health reporting is now done based on these faults instead of anything else, and the default interval for health checks is reduced to 15 seconds to accomodate this. In addition to this, Promethius metrics have been added, along with an example Grafana dashboard, for the PVC cluster itself, as well as a proxy to the Ceph cluster metrics. This release also fixes some bugs in the VM provisioner that were introduced in 0.9.83; these fixes require a **reimport or reconfiguration of any provisioner scripts**; reference the updated examples for details.

  * [All] Adds persistent fault reporting to clusters, replacing the old cluster health calculations.
  * [API Daemon] Adds cluster-level Prometheus metric exporting as well as a Ceph Prometheus proxy to the API.
  * [CLI Client] Improves formatting output of "pvc cluster status".
  * [Node Daemon] Fixes several bugs and enhances the working of the psql health check plugin.
  * [Worker Daemon] Fixes several bugs in the example provisioner scripts, and moves the libvirt_schema library into the daemon common libraries.

###### [v0.9.83](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.83)

  **Breaking Changes:** This release features a breaking change for the daemon config. A new unified "pvc.conf" file is required for all daemons (and the CLI client for Autobackup and API-on-this-host functionality), which will be written by the "pvc" role in the PVC Ansible framework. Using the "update-pvc-daemons" oneshot playbook from PVC Ansible is **required** to update to this release, as it will ensure this file is written to the proper place before deploying the new package versions, and also ensures that the old entires are cleaned up afterwards. In addition, this release fully splits the node worker and health subsystems into discrete daemons ("pvcworkerd" and "pvchealthd") and packages ("pvc-daemon-worker" and "pvc-daemon-health") respectively. The "pvc-daemon-node" package also now depends on both packages, and the "pvc-daemon-api" package can now be reliably used outside of the PVC nodes themselves (for instance, in a VM) without any strange cross-dependency issues.

  * [All] Unifies all daemon (and on-node CLI task) configuration into a "pvc.conf" YAML configuration.
  * [All] Splits the node worker subsystem into a discrete codebase and package ("pvc-daemon-worker"), still named "pvcworkerd".
  * [All] Splits the node health subsystem into a discrete codebase and package ("pvc-daemon-health"), named "pvchealthd".
  * [All] Improves Zookeeper node logging to avoid bugs and to support multiple simultaneous daemon writes.
  * [All] Fixes several bugs in file logging and splits file logs by daemon.
  * [Node Daemon] Improves several log messages to match new standards from Health daemon.
  * [API Daemon] Reworks Celery task routing and handling to move all worker tasks to Worker daemon.

###### [v0.9.82](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.82)

  * [API Daemon] Fixes a bug where the Celery result_backend was not loading properly on Celery <5.2.x (Debian 10/11).

###### [v0.9.81](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.81)

  **Breaking Changes:** This large release features a number of major changes. While these should all be a seamless transition, the behaviour of several commands and the backend system for handling them has changed significantly, along with new dependencies from PVC Ansible. A full cluster configuration update via `pvc.yml` is recommended after installing this version. Redis is replaced with KeyDB on coordinator nodes as a Celery backend; this transition will be handled gracefully by the `pvc-ansible` playbooks, though note that KeyDB will be exposed on the Upstream interface. The Celery worker system is renamed `pvcworkerd`, is now active on all nodes (coordinator and non-coordinator), and is expanded to encompass several commands that previously used a similar, custom setup within the node daemons, including "pvc vm flush-locks" and all "pvc storage osd" tasks. The previously-mentioned CLI commands now all feature "--wait"/"--no-wait" flags, with wait showing a progress bar and status output of the task run. The "pvc cluster task" command can now used for viewing all task types, replacing the previously-custom/specific "pvc provisioner status" command. All example provisioner scripts have been updated to leverage new helper functions in the Celery system; while updating these is optional, an administrator is recommended to do so for optimal log output behaviour.

  * [CLI Client] Fixes "--live" argument handling and duplicate restart prompts.
  * [All] Adds support for multiple OSDs on individual disks (NVMe workloads).
  * [All] Corrects and updates OSD replace, refresh, remove, and add functionality; replace no longer purges.
  * [All] Switches to KeyDB (multi-master) instead of Redis and adds node monitoring plugin.
  * [All] Replaces Zookeeper/Node Daemon-based message passing and task handling with pvcworkerd Celery workers on all nodes; increases worker concurrency to 3 (per node).
  * [All] Moves all task-like functions to Celery and updates existing Celery tasks to use new helpers and ID system.
  * [CLI Client] Adds "--wait/--no-wait" options with progress bars to all Celery-based tasks, "--wait" default; adds a standardized task interface under "pvc cluster task".
  * [Node Daemon] Cleans up the fencing handler and related functions.
  * [Node Daemon] Fixes bugs with VM memory reporting during keepalives.
  * [Node Daemon] Fixes a potential race condition during primary/secondary transition by backgrounding systemctl commands.
  * [API Daemon] Updates example provisioner plugins to use new Celery functions.

###### [v0.9.80](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.80)

  * [CLI] Improves CLI performance by not loading "pkg_resources" until needed
  * [CLI] Improves the output of the audit log (full command paths)
  * [Node Daemon/API Daemon] Moves the sample YAML configurations to /usr/share/pvc instead of /etc/pvc and cleans up the old locations automatically
  * [CLI] Adds VM autobackup functionality to automate VM backup/retention and scheduling
  * [CLI] Handles the internal store in a better way to ensure CLI can be used as a module properly

###### [v0.9.79](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.79)

  **API Changes**: New endpoints /vm/{vm}/backup, /vm/{vm}/restore

  * [CLI Client] Fixes some storage pool help text messages
  * [Node Daemon] Increases the IPMI monitoring plugin timeout
  * [All] Adds support for VM backups, including creation, removal, and restore
  * [Repository] Fixes shebangs in scripts to be consistent
  * [Daemon Library] Improves the handling of VM list arguments (default None)

###### [v0.9.78](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.78)

  * [API, Client CLI] Fixes several bugs around image uploads; adds a new query parameter for non-raw images
  * [API] Ensures RBD images are created with a raw bytes value to avoid rounding errors

###### [v0.9.77](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.77)

  * [Client CLI] Fixes a bug from a bad library import

###### [v0.9.76](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.76)

  * [API, Client CLI] Corrects some missing node states for fencing in status output

###### [v0.9.75](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.75)

  * [Node Daemon] Adds a startup message about IPMI when succeeding
  * [Node Daemon] Fixes a bug in fencing allowing non-failing VMs to migrate
  * [Node Daemon] Adds rounding to load average in load plugin for consistency

###### [v0.9.74](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.74)

  * [Docs] Removes docs from the main repo
  * [Client CLI] Ensures that "provision" VMs are shown in the right colour
  * [Node Daemon] Separates the node monitoring subsystem into its own thread with a longer, customizable update interval
  * [Node Daemon] Adds checks for PSU input power reundancy (psur) and hardware RAID (hwrd)
  * [Node Daemon] Updates when Keepalive start messages are printed (end of run, with runtime) to align with new monitoring messages

###### [v0.9.73](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.73)

  * [Node Daemon] Fixes a bug creating monitoring instance

###### [v0.9.72](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.72)

  * [CLI] Restores old functionality for default node value

###### [v0.9.71](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.71)

  * [API] Adds API support for Debian Bookworm

###### [v0.9.70](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.70)

  * [Node Daemon] Fixes several compatibility issues for Debian 12 "Bookworm"

###### [v0.9.69](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.69)

  * [Node Daemon] Ensures that system load is always 2 decimal places on Bookworm
  * [Node Daemon] Fixes bug blocking primary takeover at DNS Aggregator start if Patroni is down

###### [v0.9.68](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.68)

  * [CLI] Fixes another bug with network info view

###### [v0.9.67](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.67)

  * [CLI] Fixes several more bugs in the refactored CLI

###### [v0.9.66](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.66)

  * [CLI] Fixes a missing YAML import in CLI

###### [v0.9.65](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.65)

  * [CLI] Fixes a bug in the node list filtering command
  * [CLI] Fixes a bug/default when no connection is specified

###### [v0.9.64](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.64)

  **Breaking Change [CLI]**: The CLI client root commands have been reorganized. The following commands have changed:

   * `pvc cluster` -> `pvc connection` (all subcommands)
   * `pvc task` -> `pvc cluster` (all subcommands)
   * `pvc maintenance` -> `pvc cluster maintenance`
   * `pvc status` -> `pvc cluster status`

Ensure you have updated to the latest version of the PVC Ansible repository before deploying this version or using PVC Ansible oneshot playbooks for management.

  **Breaking Change [CLI]**: The `--restart` option for VM configuration changes now has an explicit `--no-restart` to disable restarting, or a prompt if neither is specified; `--unsafe` no longer bypasses this prompt which was a bug. Applies to most `vm <cmd> set` commands like `vm vcpu set`, `vm memory set`, etc. All instances also feature restart confirmation afterwards, which, if `--restart` is provided, will prompt for confirmation unless `--yes` or `--unsafe` is specified.

  **Breaking Change [CLI]**: The `--long` option previously on some `info` commands no longer exists; use `-f long`/`--format long` instead.

  * [CLI] Significantly refactors the CLI client code for consistency and cleanliness
  * [CLI] Implements `-f`/`--format` options for all `list` and `info` commands in a consistent way
  * [CLI] Changes the behaviour of VM modification options with "--restart" to provide a "--no-restart"; defaults to a prompt if neither is specified and ignores the "--unsafe" global entirely
  * [API] Fixes several bugs in the 3-debootstrap.py provisioner example script
  * [Node] Fixes some bugs around VM shutdown on node flush
  * [Documentation] Adds mentions of Ganeti and Harvester

###### [v0.9.63](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.63)

  * Mentions Ganeti in the docs
  * Increases API timeout back to 2s
  * Adds .update-* configs to dpkg plugin
  * Adds full/nearfull OSD warnings
  * Improves size value handling for volumes

###### [v0.9.62](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.62)

  * [all] Adds an enhanced health checking, monitoring, and reporting system for nodes and clusters
  * [cli] Adds a cluster detail command

###### [v0.9.61](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.61)

  * [provisioner] Fixes a bug in network comparison
  * [api] Fixes a bug being unable to rename disabled VMs

###### [v0.9.60](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.60)

  * [Provisioner] Cleans up several remaining bugs in the example scripts; they should all be valid now
  * [Provisioner] Adjust default libvirt schema to disable RBD caching for a 2x+ performance boost

###### [v0.9.59](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.59)

  * [API] Flips the mem(prov) and mem(free) selectors making mem(free) the default for "mem" and "memprov" explicit

###### [v0.9.58](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.58)

  * [API] Fixes a bug where migration selector could have case-sensitive operational faults

###### [v0.9.57](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.57)

  * [CLI] Removes an invalid reference to VXLAN
  * [CLI] Improves the handling of invalid networks in VM lists and on attach
  * [API] Modularizes the benchmarking library so it can be used externally too
  * [Daemon Library] Adds a module tag file so it can be used externally too

###### [v0.9.56](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.56)

  **Breaking Change**: Existing provisioner scripts are no longer valid; new example scripts are provided.
  **Breaking Change**: OVA profiles now require an `ova` or `default_ova` provisioner script (use example) to function.

  * [API/Provisioner] Fundamentally revamps the provisioner script framework to provide more extensibility
  * [API/Provisioner] Adds example provisioner scripts for noop, ova, debootstrap, rinse, and pfsense
  * [API/Provisioner] Enforces the use of the ova provisioner script during new OVA uploads; existing uploads will not work
  * [Documentation] Updates the documentation around provisioner scripts and OVAs to reflect the above changes
  * [Node] Adds a new pvcautoready.service oneshot unit to replicate the on-boot-ready functionality of old pvc-flush.service unit

###### [v0.9.55](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.55)

  * Fixes a problem with the literal eval handler in the provisioner (again)
  * Fixes a potential log deadlock in Zookeeper-lost situations when doing keepalives

###### [v0.9.54](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.54)

[CLI Client] Fixes a bad variable reference from the previous change
[API Daemon] Enables TLSv1 with an SSLContext object for maximum compatibility

###### [v0.9.53](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.53)

  * [API] Fixes sort order of VM list (for real this time)

###### [v0.9.52](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.52)

  * [CLI] Fixes a bug with vm modify not requiring a cluster
  * [Docs] Adds a reference to the bootstrap daemon
  * [API] Adds sorting to node and VM lists for consistency
  * [Node Daemon/API] Adds kb_ stats values for OSD stats

###### [v0.9.51](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.51)

  * [CLI Client] Fixes a faulty literal_eval when viewing task status
  * [CLI Client] Adds a confirmation flag to the vm disable command
  * [Node Daemon] Removes the pvc-flush service

###### [v0.9.50](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.50)

  * [Node Daemon/API/CLI] Adds free memory node selector
  * [Node Daemon] Fixes bug sending space-containing detect disk strings

###### [v0.9.49](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.49)

  * [Node Daemon] Fixes bugs with OSD stat population on creation
  * [Node Daemon/API] Adds additional information to Zookeeper about OSDs
  * [Node Daemon] Refactors OSD removal for improved safety
  * [Node Daemon/API/CLI] Adds explicit support for replacing and refreshing (reimporting) OSDs
  * [API/CLI] Fixes a language inconsistency about "router mode"

###### [v0.9.48](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.48)

  * [CLI] Fixes situation where only a single cluster is available
  * [CLI/API/Daemon] Allows forcing of OSD removal ignoring errors
  * [CLI] Fixes bug where down OSDs are not displayed

###### [v0.9.47](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.47)

  * [Node Daemon/API/CLI] Adds Ceph pool device class/tier support
  * [API] Fixes a bug returning values if a Ceph pool has not yet reported stats
  * [API/CLI] Adds PGs count to the pool list output
  * [API/CLI] Adds Ceph pool PGs count adjustment support

###### [v0.9.46](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.46)

  * [API] Fixes bugs with legacy benchmark display
  * [API] Fixes a bug around cloned image sizes
  * [API] Removes extraneous message text in provisioner create command
  * [API] Corrects bugs around fuzzy matching
  * [CLI] Adds auditing for PVC CLI to local syslog
  * [CLI] Adds --yes bypass for benchmark command
  * [Node Daemon/API/CLI] Adds support for "detect" strings when specifying OSD or OSDDB devices
  * [Node Daemon] Fixes a bug when removing OSDs
  * [Node Daemon] Fixes a single-node cluster shutdown deadlock

###### [v0.9.45](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.45)

  * [Node Daemon] Fixes an ordering issue with pvcnoded.service
  * [CLI Client] Fixes bad calls to echo() without argument

###### [v0.9.44](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.44)

  * [Node Daemon] Adds a Munin plugin for Ceph utilization
  * [CLI] Fixes timeouts for long-running API commands

###### [v0.9.44](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.44)

  * [CLI] Fixes timeout issues with long-running API commands

###### [v0.9.43](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.43)

  * [Packaging] Fixes a bad test in postinst            
  * [CLI] Adds support for removing VM interfaces by MAC address                                                         
  * [CLI] Modifies the default restart + live behaviour to prefer the explicit restart                                   
  * [CLI] Adds support for adding additional VM interfaces in the same network                                           
  * [CLI] Various ordering and message fixes                                                                             
  * [Node Daemon] Adds additional delays and retries to fencing actions                                                  
  * [All] Adds Black formatting for Python code and various script/hook cleanups                                         
  * [CLI/API] Adds automatic shutdown or stop when disabling a VM                                                        
  * [CLI] Adds support for forcing colourized output                                                                     
  * [Docs] Remove obsolete Ansible and Testing manuals  

###### [v0.9.42](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.42)

  * [Documentation] Reworks and updates various documentation sections
  * [Node Daemon] Adjusts the fencing process to use a power off rather than a power reset for maximum certainty
  * [Node Daemon] Ensures that MTU values are validated during the first read too
  * [Node Daemon] Corrects the loading of the bridge_mtu value to use the current active setting rather than a fixed default to prevent unintended surprises

###### [v0.9.41](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.41)

  * Fixes a bad conditional check in IPMI verification
  * Implements per-network MTU configuration; NOTE: Requires new keys in pvcnoded.yaml (`bridge_mtu`) and Ansible group_vars (`pvc_bridge_mtu`)

###### [v0.9.40](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.40)

  * [Docs] Documentation updates for new Changelog file
  * [Node Daemon] Fixes bug with schema updates

###### [v0.9.39](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.39)

  * [Documentation] Update several documentation sections
  * [API Daemon/CLI Client] Add negate flag for VM option limits (node, tag, state)
  * [Build] Add linting check to build-and-deploy.sh

###### [v0.9.38](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.38)

  * [All] Significantly improve storage benchmark format and reporting

###### [v0.9.37](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.37)

  * [All] Adds support for configurable OSD DB size ratios
  * [Node Daemon] Fixes bugs with OSD creation
  * [Node Daemon] Fixes exception bugs in CephInstance
  * [CLI Client] Adjusts descriptions around Ceph OSDs
  * [Node Daemon] Fixes ordering of pvc-flush unit
  * [Node Daemon] Fixes bugs in fence handling and libvirt keepalive
  * [Node Daemon] Simplifies locking for and speeds up VM migrations
  * [Node Daemon] Fixes bugs in queue get timeouts
  * [API Daemon] Adjusts benchmark test jobs configuration and naming

###### [v0.9.36](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.36)

  * [Node Daemon] Fixes a bug during early cleanup
  * [All] Adds support for OSD database/WAL block devices to improve Ceph performance; NOTE: Applies only to new OSDs

###### [v0.9.35](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.35)

  * [Node Daemon] Fixes several bugs and crashes in node daemon
  * [General] Updates linting rules for newer Flake8 linter
  * [Daemons/CLI client] Adds VM network and disk hot attach/detach support; NOTE: Changes the default behaviour of `pvc vm network add`/`remove` and `pvc vm volume add`/`remove`
  * [API Daemon] Adds checks for pool size when resizing volumes
  * [API Daemon] Adds checks for RAM and vCPU sizes when defining or modifying VMs

###### [v0.9.34](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.34)

  * [Provisioner] Adds support for filesystem arguments containing =
  * [CLI Client] Fixes bug with pvc provisioner status output formatting
  * [Node Daemon] Fixes minor typo in startup message

###### [v0.9.33](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.33)

  * [Node Daemon] A major refactoring of the node daemon
  * [CLI Client] Fixes output errors if a node has no provisioner data
  * [Packages] Fixes issues with including __pycache__ directories in .deb files

###### [v0.9.32](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.32)

  * [CLI Client] Fixes some incorrect colours in network lists
  * [Documentation] Adds documentation screenshots of CLI client
  * [Node Daemon] Fixes a bug if VM stats gathering fails

###### [v0.9.31](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.31)

  * [Packages] Cleans up obsolete Suggests lines
  * [Node Daemon] Adjusts log text of VM migrations to show the correct source node
  * [API Daemon] Adjusts the OVA importer to support floppy RASD types for compatability
  * [API Daemon] Ensures that volume resize commands without a suffix get B appended
  * [API Daemon] Removes the explicit setting of image-features in PVC; defaulting to the limited set has been moved to the ceph.conf configuration on nodes via PVC Ansible

###### [v0.9.30](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.30)

  * [Node Daemon] Fixes bug with schema validation

###### [v0.9.29](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.29)

  * [Node Daemon] Corrects numerous bugs with node logging framework

###### [v0.9.28](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.28)

  * [CLI Client] Revamp confirmation options for "vm modify" command

###### [v0.9.27](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.27)

  * [CLI Client] Fixes a bug with vm modify command when passed a file

###### [v0.9.26](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.26)

  * [Node Daemon] Corrects some bad assumptions about fencing results during hardware failures
  * [All] Implements VM tagging functionality
  * [All] Implements Node log access via PVC functionality

###### [v0.9.25](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.25)

  * [Node Daemon] Returns to Rados library calls for Ceph due to performance problems
  * [Node Daemon] Adds a date output to keepalive messages
  * [Daemons] Configures ZK connection logging only for persistent connections
  * [API Provisioner] Add context manager-based chroot to Debootstrap example script
  * [Node Daemon] Fixes a bug where shutdown daemon state was overwritten

###### [v0.9.24](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.24)

  * [Node Daemon] Removes Rados module polling of Ceph cluster and returns to command-based polling for timeout purposes, and removes some flaky return statements
  * [Node Daemon] Removes flaky Zookeeper connection renewals that caused problems
  * [CLI Client] Allow raw lists of clusters from `pvc cluster list`
  * [API Daemon] Fixes several issues when getting VM data without stats
  * [API Daemon] Fixes issues with removing VMs while disks are still in use (failed provisioning, etc.)

###### [v0.9.23](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.23)

  * [Daemons] Fixes a critical overwriting bug in zkhandler when schema paths are not yet valid
  * [Node Daemon] Ensures the daemon mode is updated on every startup (fixes the side effect of the above bug in 0.9.22)

###### [v0.9.22](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.22)

  * [API Daemon] Drastically improves performance when getting large lists (e.g. VMs)
  * [Daemons] Adds profiler functions for use in debug mode
  * [Daemons] Improves reliability of ZK locking
  * [Daemons] Adds the new logo in ASCII form to the Daemon startup message
  * [Node Daemon] Fixes bug where VMs would sometimes not stop
  * [Node Daemon] Code cleanups in various classes
  * [Node Daemon] Fixes a bug when reading node schema data
  * [All] Adds node PVC version information to the list output
  * [CLI Client] Improves the style and formatting of list output including a new header line
  * [API Worker] Fixes a bug that prevented the storage benchmark job from running

###### [v0.9.21](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.21)

  * [API Daemon] Ensures VMs stop before removing them
  * [Node Daemon] Fixes a bug with VM shutdowns not timing out
  * [Documentation] Adds information about georedundancy caveats
  * [All] Adds support for SR-IOV NICs (hostdev and macvtap) and surrounding documentation
  * [Node Daemon] Fixes a bug where shutdown aborted migrations unexpectedly
  * [Node Daemon] Fixes a bug where the migration method was not updated realtime
  * [Node Daemon] Adjusts the Patroni commands to remove reference to Zookeeper path
  * [CLI Client] Adjusts several help messages and fixes some typos
  * [CLI Client] Converts the CLI client to a proper Python module
  * [API Daemon] Improves VM list performance
  * [API Daemon] Adjusts VM list matching critera (only matches against the UUID if it's a full UUID)
  * [API Worker] Fixes incompatibility between Deb 10 and 11 in launching Celery worker
  * [API Daemon] Corrects several bugs with initialization command
  * [Documentation] Adds a shiny new logo and revamps introduction text

###### [v0.9.20](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.20)

  * [Daemons] Implemented a Zookeeper schema handler and version 0 schema
  * [Daemons] Completes major refactoring of codebase to make use of the schema handler
  * [Daemons] Adds support for dynamic chema changges and "hot reloading" of pvcnoded processes
  * [Daemons] Adds a functional testing script for verifying operation against a test cluster
  * [Daemons, CLI] Fixes several minor bugs found by the above script
  * [Daemons, CLI] Add support for Debian 11 "Bullseye"

###### [v0.9.19](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.19)

  * [CLI] Corrects some flawed conditionals
  * [API] Disables SQLAlchemy modification tracking functionality (not used by us)
  * [Daemons] Implements new zkhandler module for improved reliability and reusability
  * [Daemons] Refactors some code to use new zkhandler module
  * [API, CLI] Adds support for "none" migration selector (uses cluster default instead)
  * [Daemons] Moves some configuration keys to new /config tree
  * [Node Daemon] Increases initial lock timeout for VM migrations to avoid out-of-sync potential
  * [Provisioner] Support storing and using textual cluster network labels ("upstream", "storage", "cluster") in templates
  * [API] Avoid duplicating existing node states

###### [v0.9.18](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.18)

  * Adds VM rename functionality to API and CLI client

###### [v0.9.17](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.17)

  * [CLI] Fixes bugs in log follow output

###### [v0.9.16](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.16)

  * Improves some CLI help messages
  * Skips empty local cluster in CLI
  * Adjusts how confirmations happen during VM modify restarts
  * Fixes bug around corrupted VM log files
  * Fixes bug around subprocess pipe exceptions

###### [v0.9.15](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.15)

  * [CLI] Adds additional verification (--yes) to several VM management commands
  * [CLI] Adds a method to override --yes/confirmation requirements via envvar (PVC_UNSAFE)
  * [CLI] Adds description fields to PVC clusters in CLI

###### [v0.9.14](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.14)

  * Fixes bugs around cloned volume provisioning
  * Fixes some minor visual bugs
  * Minor license update (from GPL3+ to GPL3)
  * Adds qemu-guest-agent support to provisioner-created VMs by default

###### [v0.9.13](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.13)

  * Adds nicer startup messages for daemons
  * Adds additional API field for stored_bytes to pool stats
  * Fixes sorting issues with snapshot lists
  * Fixes missing increment/decrement of snapshot_count on volumes
  * Fixes bad calls in pool element API endpoints
  * Fixes inconsistent bytes_tohuman behaviour in daemons
  * Adds validation and maximum volume size on creation (must be smaller than the pool free space)

###### [v0.9.12](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.12)

  * Fixes a bug in the pvcnoded service unit file causing a Zookeeper startup race condition

###### [v0.9.11](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.11)

  * Documentation updates
  * Adds VNC information to VM info
  * Goes back to external Ceph commands for disk usage

###### [v0.9.10](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.10)

  * Moves OSD stats uploading to primary, eliminating reporting failures while hosts are down
  * Documentation updates
  * Significantly improves RBD locking behaviour in several situations, eliminating cold-cluster start issues and failed VM boot-ups after crashes
  * Fixes some timeout delays with fencing
  * Fixes bug in validating YAML provisioner userdata

###### [v0.9.9](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.9)

  * Adds documentation updates
  * Removes single-element list stripping and fixes surrounding bugs
  * Adds additional fields to some API endpoints for ease of parsing by clients
  * Fixes bugs with network configuration

###### [v0.9.8](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.8)

  * Adds support for cluster backup/restore
  * Moves location of `init` command in CLI to make room for the above
  * Cleans up some invalid help messages from the API

###### [v0.9.7](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.7)

  * Fixes bug with provisioner system template modifications

###### [v0.9.6](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.6)

  * Fixes bug with migrations

###### [v0.9.5](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.5)

  * Fixes bug with line count in log follow
  * Fixes bug with disk stat output being None
  * Adds short pretty health output
  * Documentation updates

###### [v0.9.4](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.4)

  * Fixes major bug in OVA parser

###### [v0.9.3](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.3)

  * Fixes bugs with image & OVA upload parsing

###### [v0.9.2](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.2)

  * Major linting of the codebase with flake8; adds linting tools
  * Implements CLI-based modification of VM vCPUs, memory, networks, and disks without directly editing XML
  * Fixes bug where `pvc vm log -f` would show all 1000 lines before starting
  * Fixes bug in default provisioner libvirt schema (`drive` -> `driver` typo)

###### [v0.9.1](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.1)

  * Added per-VM migration method feature
  * Fixed bug with provisioner system template listing

###### [v0.9.0](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.9.0)

Numerous small improvements and bugfixes. This release is suitable for general use and is pre-release-quality software.

This release introduces an updated version scheme; all future stable releases until 1.0.0 is ready will be made under this 0.9.z naming. This does not represent semantic versioning and all changes (feature, improvement, or bugfix) will be considered for inclusion in this release train.

###### [v0.8](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.8)

Numerous improvements and bugfixes. This release is suitable for general use and is pre-release-quality software.

###### [v0.7](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.7)

Numerous improvements and bugfixes, revamped documentation. This release is suitable for general use and is beta-quality software.

###### [v0.6](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.6)

Numerous improvements and bugfixes, full implementation of the provisioner, full implementation of the API CLI client (versus direct CLI client). This release is suitable for general use and is beta-quality software.

###### [v0.5](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.5)

First public release; fully implements the VM, network, and storage managers, the HTTP API, and the pvc-ansible framework for deploying and bootstrapping a cluster. This release is suitable for general use, though it is still alpha-quality software and should be expected to change significantly until 1.0 is released.

###### [v0.4](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.4)

Full implementation of virtual management and virtual networking functionality. Partial implementation of storage functionality.

###### [v0.3](https://github.com/parallelvirtualcluster/pvc/releases/tag/v0.3)

Basic implementation of virtual management functionality.

