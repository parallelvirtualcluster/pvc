# PVC - The Parallel Virtual Cluster tool

PVC is a tool to manage QEMU/KVM virtual machines in a cluster environment using Python, Libvirt, and Zookeeper. The primary motivation for developing PVC was my percieved shortfalls in Pacemaker/Corosync, which would often put my virtual cluster into undefined states and generally cause a lot of headaches.

## How it works

### Zookeeper

Zookeeper is the bedrock on which PVC is built. Before deploying PVC itself, ensure you have a working Zookeeper cluster. By default, each PVC node should also be a Zookeeper node, but with configuration tweaking an external cluster can be used as well.

The Zookeeper cluster handles a set of key/value pairs for each node object and each VM object (usually called a `domain`). These values determine details like the current state, the domain XML configuration, and current free RAM on a node, just to name a few. Each instance of the daemon talks to Zookeeper, by default the local instance, and performs actions based on changes to these values. In this sense, each node is completely independent, and except during live migration nodes do not talk to one another directly.

If the Zookeeper cluster becomes unusable, the individual PVC daemons will cease functioning normally and may trigger fencing. It is very important to keep this in mind before performing major work on the Zookeeper cluster.

### Libvirt and QEMU/KVM

PVC manages VMs using Libvirt, and specifically QEMU/KVM. While Xen or any other hypervisor should work transparently and PVC makes no special assumptions, it has only been tested so far with KVM. A working Libvirt instance listening in TCP mode with no authentication is required for the PVC daemon to start, and for live migration to occur. Note that live migration is an important feature of PVC, so while it is possible to run without this feature enabled, the experience will be suboptimal.

### `pvcd`

The node-side component of PVC is `pvcd`, or the PVC daemon. It is written entirely in Python3 and handles all actions that can occur on a node. This includes updating the nodes state via keepalives to Zookeeper, and managing all parts of a VM lifecycle on the node.

A key concept in PVC is that all node daemon instances are idempotent and talks only to the Zookeeper instance. As such, each node will create a class instance for each node in the cluster (including itself) to track their state, as well as a class instance for each VM in the cluster for the same reason. These instances normally do nothing except monitor for changes, and if they occur fire actions on the local host as required.

### `pvc`

The client command-line interface for PVC is called, simply enough, `pvc`. It is used by an administrator to manage the PVC cluster and perform any actions that might need to be taken. The `pvc` command is built using Click, and is self-documenting - use the `-h` option for help on a given command.

## What can I do with it?

The main goal of PVC is to provide the KVM management layer in a more scalable and extensible way that the tool it was built to replace, Pacemaker/Corosync with the Libvirt resource agent. As such, PVC lets you manage your VM cluster without hassle and in an almost-infinitely scalable manner (based only on the limits of Zookeeper).

## What can't I do with it?

PVC is based on the Unix philosophy of "do one thing and do it well". As such, it has one task: manage KVM VMs. It does not manage:

1. Provisioning of VMs
2. Networking on the hypervisor nodes
3. Alerting of errors/failed VMs (though it will restart failing VMs or mark them `failed`)
4. Resource usage of VMs, beyond basic memory reporting

In short, PVC does not look to replace large projects like OpenStack, only a particular component provided in my original usage by Pacemaker/Corosync. However, it should be possible to build support into any larger project by interfacing directly with the Zookeeper cluster, just as the `pvc` client utility does. I will not rule out integration possiblities but I do not use any of these larger projects.

## Why might you want to use PVC?

1. You have a small (3+ node) KVM cluster and want to efficiently manage your VMs via CLI.
2. You need a very scalable solution to manage dozens of KVM hypervisors.

Really, PVC benefits both the small and large use-cases. If your requirement is for a simple and easy-to-use tool to automatically manage VMs, PVC will work for you.

## Why shouldn't you use PVC?

1. You need something to provision your VMs and Networking for you - PVC explicitly does not handle this.
2. You need more advanced reporting or management of VM resources.
3. You hate Python.

## How the daemon works

The daemon is the main piece of machinery. It consists of 4 main files - one entry point, 2 classes, and a supplemental function:

* `pvcd.py` - The main daemon entry point.
* `pvcd/NodeInstance.py` - A class definition for a hypervisor node object.
* `pvcd/VMInstance.py` - A class definition for a virtual machine object.
* `pvcd/ansiiprint.py` - A supplemental function to output log lines.

The following sections walk through the steps the daemon takes from startup through to running VMs.

#### 1. Preflight checks

* The daemon starts up and verifies that the `PVCD_CONFIG_FILE` environment variable was specified. Terminates if it is not.
* The daemon reads its config file and parses the values into its configuration dictionary. Terminates if any required configuration field is missing.
* The daemon verifies that there is a running Libvirt instance at `qemu+tcp://127.0.0.1:16509/system`. Terminates if the connection fails.
* The daemon opens a connection to Zookeeper at the address specified in the config file. Terminates if the connection fails.
* The daemon creates a Zookeeper listener against the connection to monitor for disconnects.
* The daemon traps the `SIGTERM`, `SIGINT`, and `SIGQUIT` signals to ensure this connection is cleaned up and the node state updated on exit.

#### 2. Initialization

* The daemon obtains some static information about the current node, including CPU count, OS, kernel version, and architecture.
* The daemon outputs this information to the log console for administrator reference.
* The daemon verifies that a node with its name exists in Zookeeper at `/domains/system.host.name`.
    * If it does, it updates the static data and continues.
    * If it does not, it adds the required keys for the new node with some default/empty values.
* The daemon sets its state to `init`.

#### 3. Class object initalization

* The daemon reads the list of domains in the cluster (children of `/domains` in Zookeeper) and initalizes an instance of the `NodeInstance` class for each one. This read is a Zookeeper ChildrenWatch function, and is called again each time the list of children changes.
* The daemon performs a similar action for the list of VMs (`/domains`) in the cluster using a similar watch function.
* The daemon creates a thread to send keepalives to Zookeeper.
* The thread starts and the node sets its daemon status to `run`.

#### 4. Normal operation

* Once started, the daemon sends keepalives every few seconds (configurable, defaults to 5) to Zookeper.
* The daemon watches for these keepalives from all other nodes in the cluster; if one is not sent for 6 ticks, the remote node is considered dead and fencing is triggered.
* The daemon watches for VM state changes and, in response, performs actions based on the target VM state and hypervisor.

#### 5. Termination

* On shutdown, the daemon performs a cleaup, sets its daemon state to `stop`, and terminates the Zookeeper connection. It does NOT flush or otherwise modify running VMs by design; an administrator must flush the node first if this is required.

## Changelog

#### 0.1

* Initial release; all basic functionality implemented.

## Building

This repo contains the required elements to build Debian packages for PVC. It is not handled like a normal Python package but instead the debs contain the raw files placed in Debianized places.

1. Run `build-deb.sh`; you will need `dpkg-buildpackage` installed.
2. The output files, `pvc-daemon_vvv.deb` and `pvc-client_vvv.deb`, will be located in the parent directory.

## Installing

1. Ensure a Zookeeper cluster is installed and configured, ideally on the nodes themselves.
2. Install the `pvc-daemon_vvv.deb` package and, optionally, the `pvc-client_vvv.deb` (the client is not required and the cluster can be managed remotely).
3. Configure your `/etc/pvc/pvcd.conf` file for the node. A sample can be found at `/etc/pvc/pvcd.conf.sample` listing the available options.
4. Start up the PVC daemon with `systemctl start pvcd.service`
5. Check the output of the process; using the `-o cat` option to `journalctl` provides nicer output: `journalctl -u pvcd.service -f -o cat`
6. Use the `pvc` command-line tool to manage the cluster.
