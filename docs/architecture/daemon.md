# PVC Node Daemon architecture

The PVC Node Daemon is the heart of the PVC system and runs on each node to manage the state of the node and its configured resources. The daemon connects directly to the Zookeeper cluster for coordination and state.

The node daemon is build using Python 3.X and is packaged in the Debian package `pvc-daemon`.

Configuration of the daemon is documented in [the manual](/manuals/daemon), however it is recommended to use the [Ansible configuration interface](/manuals/ansible) to configure the PVC system for you from scratch.

## Overall architecture

The PVC daemon is object-oriented - each cluster resource is represented by an Object, which is then present on each node in the cluster. This allows state changes to be reflected across the entire cluster should their data change.

During startup, the system scans the Zookeeper database and sets up the required objects. The database is then watched in real-time for additional changes to the database information.

## Startup sequence

The daemon startup sequence is documented below. The main daemon entrypoint is `Daemon.py` inside the `pvcd` folder, which is called from the `pvcd.py` stub file.

0. The configuration is read from `/etc/pvc/pvcd.yaml` and the configuration object set up.

0. Any required filesystem directories, mostly dynamic directories, are created.

0. The logger is set up. If file logging is enabled, this is the state when the first log messages are written.

0. Host networking is configured based on the `pvcd.yaml` configuration file. In a normal cluster, this is the point where the node will become reachable on the network as all networking is handled by the PVC node daemon.

0. Sysctl tweaks are applied to the host system, to enable routing/forwarding between nodes via the host.

0. The node determines its coordinator state and starts the required daemons if applicable. In a normal cluster, this is the point where the dependent services such as Zookeeper, FRR, and Ceph become available. After this step, the daemon waits 5 seconds before proceeding to give these daemons a chance to start up.

0. The daemon connects to the Zookeeper cluster and starts its listener. If the Zookeeper cluster is unavailable, it will wait some time before abandoning the attempt and starting again from step 1.

0. Termination handling/cleanup is configured.

0. The node checks if it is already present in the Zookeeper cluster; if not, it will add itself to the database. Initial static options are also updated in the database here. The daemon state transitions from `stop` to `init`.

0. The node checks if Libvirt is accessible.

0. The node starts up the NFT firewall if applicable and configures the base ruleset.

0. The node ensures that `dnsmasq` is stopped (legacy check, might be safe to remove eventually).

0. The node begins setting up the object representations of resources, in order:

    a. Node entries

    b. Network entries, creating client networks and starting them as required.

    c. Domain (VM) entries, starting up the VMs as required.

    d. Ceph storage entries (OSDs, Pools, Volumes, Snapshots).

0. The node activates its keepalived timer and begins sending keepalive updates to the cluster. The daemon state transitions from `init` to `run` and the system has started fully.
