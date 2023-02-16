# PVC Node Monitoring Resources

This directory contains several monitoring resources that can be used with various monitoring systems to track and alert on a PVC cluster system.

## Munin

The included Munin plugin can be activated by linking to it from `/etc/munin/plugins/pvc`. By default, this plugin triggers a CRITICAL state when either the PVC or Storage cluster becomes Degraded, and is otherwise OK. The overall health is graphed numerically (Optimal is 0, Maintenance is 1, Degraded is 2) so that the cluster health can be tracked over time.

When using this plugin, it might be useful to adjust the thresholds with a plugin configuration. For instance, one could adjust the Degraded value from CRITICAL to WARNING by adjusting the critical threshold to a value higher than 1.99 (e.g. 3, 10, etc.) so that only the WARNING threshold will be hit. Alternatively one could instead make Maintenance mode trigger a WARNING by lowering the threshold to 0.99.

Example plugin configuration:

```
[pvc]
# Make cluster warn on maintenance
env.pvc_cluster_warning 0.99
# Disable critical threshold (>2)
env.pvc_cluster_critical 3
# Make storage warn on maintenance, crit on degraded (latter is default)
env.pvc_storage_warning 0.99
env.pvc_storage_critical 1.99
```

## CheckMK

The included CheckMK plugin is divided into two parts: the agent plugin, and the monitoring server plugin, and can be activated as follows:

### Agent plugin: `pvc`

Place this file in the `/usr/lib/check_mk_agent/plugins/` directory on each node.

### Server plugin: `pvc.py`

This monitoring server plugin requires CheckMK version 2.0 or higher.

Place this file in the `~/local/lib/python3/cmk/base/plugins/agent_based/` directory for each monitoring site.

### Output

With both the agent and server plugins installed, you can then run `cmk -II <node>` (or use WATO) to inventory each node, which should produce two new checks:

* `PVC Cluster`: Provides the cluster-wide health. Note that this will be identical for all nodes in the cluster (i.e. if the cluster health drops, all nodes in the cluster will alert this check).

* `PVC Node <shortname>`: Provides the per-node health.

The "Summary" text, shown in the check lists, will be simplistic, only showing the current health percentage.

The "Details" text, found in the specific check details, will show the full list of problem(s) the check finds, as shown by `pvc status` itself.
