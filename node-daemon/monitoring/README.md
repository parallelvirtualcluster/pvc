# PVC Node Monitoring Resources

This directory contains several monitoring resources that can be used with various monitoring systems to track and alert on a PVC cluster system.

## Munin

The included Munin plugins can be activated by linking to them from `/etc/munin/plugins/`. Two plugins are provided:

* `pvc`: Checks the PVC cluster and node health, providing two graphs, one for each.

* `ceph_utilization`: Checks the Ceph cluster statistics, providing multiple graphs. Note that this plugin is independent of PVC itself, and makes local calls to various Ceph commands itself.

The `pvc` plugin provides no configuration; the status is hardcoded such that <=90% health is warning, <=50% health is critical, and maintenance state forces OK.

The `ceph_utilization` plugin provides no configuration; only the cluster utilization graph alerts such that >80% used is warning and >90% used is critical. Ceph itself begins warning above 80% as well.

## CheckMK

The included CheckMK plugin is divided into two parts: the agent plugin, and the monitoring server plugin. This monitoring server plugin requires CheckMK version 2.0 or higher. The two parts can be installed as follows:

* `pvc`: Place this file in the `/usr/lib/check_mk_agent/plugins/` directory on each node.

* `pvc.py`: Place this file in the `~/local/lib/python3/cmk/base/plugins/agent_based/` directory on the CheckMK monitoring host for each monitoring site.

The plugin provides no configuration: the status is hardcoded such that <=90% health is warning, <=50% health is critical, and maintenance state forces OK.

With both the agent and server plugins installed, you can then run `cmk -II <node>` (or use WATO) to inventory each node, which should produce two new checks:

* `PVC Cluster`: Provides the cluster-wide health. Note that this will be identical for all nodes in the cluster (i.e. if the cluster health drops, all nodes in the cluster will alert this check).

* `PVC Node <shortname>`: Provides the per-node health.

The "Summary" text, shown in the check lists, will be simplistic, only showing the current health percentage.

The "Details" text, found in the specific check details, will show the full list of problem(s) the check finds, as shown by `pvc status` itself.
