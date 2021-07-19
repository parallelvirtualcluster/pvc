<p align="center">
<img alt="Logo banner" src="images/pvc_logo_black.png"/>
<br/><br/>
<a href="https://github.com/parallelvirtualcluster/pvc"><img alt="License" src="https://img.shields.io/github/license/parallelvirtualcluster/pvc"/></a>
<a href="https://github.com/parallelvirtualcluster/pvc/releases"><img alt="Release" src="https://img.shields.io/github/release-pre/parallelvirtualcluster/pvc"/></a>
<a href="https://parallelvirtualcluster.readthedocs.io/en/latest/?badge=latest"><img alt="Documentation Status" src="https://readthedocs.org/projects/parallelvirtualcluster/badge/?version=latest"/></a>
</p>

## What is PVC?

PVC is a virtual machine-based hyperconverged infrastructure (HCI) virtualization cluster solution that is fully Free Software, scalable, redundant, self-healing, self-managing, and designed for administrator simplicity. It is an alternative to other HCI solutions such as Harvester, Nutanix, and VMWare, as well as to other common virtualization stacks such as ProxMox and OpenStack.

PVC is a complete HCI solution, built from well-known and well-trusted Free Software tools, to assist an administrator in creating and managing a cluster of servers to run virtual machines, as well as self-managing several important aspects including storage failover, node failure and recovery, virtual machine failure and recovery, and network plumbing. It is designed to act consistently, reliably, and unobtrusively, letting the administrator concentrate on more important things.

PVC is highly scalable. From a minimum (production) node count of 3, up to 12 or more, and supporting many dozens of VMs, PVC scales along with your workload and requirements. Deploy a cluster once and grow it as your needs expand.

As a consequence of its features, PVC makes administrating very high-uptime VMs extremely easy, featuring VM live migration, built-in always-enabled shared storage with transparent multi-node replication, and consistent network plumbing throughout the cluster. Nodes can also be seamlessly removed from or added to service, with zero VM downtime, to facilitate maintenance, upgrades, or other work.

PVC also features an optional, fully customizable VM provisioning framework, designed to automate and simplify VM deployments using custom provisioning profiles, scripts, and CloudInit userdata API support.

Installation of PVC is accomplished by two main components: a [Node installer ISO](https://github.com/parallelvirtualcluster/pvc-installer) which creates on-demand installer ISOs, and an [Ansible role framework](https://github.com/parallelvirtualcluster/pvc-ansible) to configure, bootstrap, and administrate the nodes. Once up, the cluster is managed via an HTTP REST API, accessible via a Python Click CLI client or WebUI.

Just give it physical servers, and it will run your VMs without you having to think about it, all in just an hour or two of setup time.


## What is it based on?

The core node and API daemons, as well as the CLI API client, are written in Python 3 and are fully Free Software (GNU GPL v3). In addition to these, PVC makes use of the following software tools to provide a holistic hyperconverged infrastructure solution:

  * Debian GNU/Linux as the base OS.
  * Linux KVM, QEMU, and Libvirt for VM management.
  * Linux `ip`, FRRouting, NFTables, DNSMasq, and PowerDNS for network management.
  * Ceph for storage management.
  * Apache Zookeeper for the primary cluster state database.
  * Patroni PostgreSQL manager for the secondary relation databases (DNS aggregation, Provisioner configuration).


## Getting Started

To get started with PVC, please see the [About](https://parallelvirtualcluster.readthedocs.io/en/latest/about/) page for general information about the project, and the [Getting Started](https://parallelvirtualcluster.readthedocs.io/en/latest/getting-started/) page for details on configuring your first cluster.


## Changelog

#### v0.9.27

  * [CLI Client] Fixes a bug with vm modify command when passed a file

#### v0.9.26

  * [Node Daemon] Corrects some bad assumptions about fencing results during hardware failures
  * [All] Implements VM tagging functionality
  * [All] Implements Node log access via PVC functionality

#### v0.9.25

  * [Node Daemon] Returns to Rados library calls for Ceph due to performance problems
  * [Node Daemon] Adds a date output to keepalive messages
  * [Daemons] Configures ZK connection logging only for persistent connections
  * [API Provisioner] Add context manager-based chroot to Debootstrap example script
  * [Node Daemon] Fixes a bug where shutdown daemon state was overwritten

#### v0.9.24

  * [Node Daemon] Removes Rados module polling of Ceph cluster and returns to command-based polling for timeout purposes, and removes some flaky return statements
  * [Node Daemon] Removes flaky Zookeeper connection renewals that caused problems
  * [CLI Client] Allow raw lists of clusters from `pvc cluster list`
  * [API Daemon] Fixes several issues when getting VM data without stats
  * [API Daemon] Fixes issues with removing VMs while disks are still in use (failed provisioning, etc.)

#### v0.9.23

  * [Daemons] Fixes a critical overwriting bug in zkhandler when schema paths are not yet valid
  * [Node Daemon] Ensures the daemon mode is updated on every startup (fixes the side effect of the above bug in 0.9.22)

#### v0.9.22

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

#### v0.9.21

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

#### v0.9.20

  * [Daemons] Implemented a Zookeeper schema handler and version 0 schema
  * [Daemons] Completes major refactoring of codebase to make use of the schema handler
  * [Daemons] Adds support for dynamic chema changges and "hot reloading" of pvcnoded processes
  * [Daemons] Adds a functional testing script for verifying operation against a test cluster
  * [Daemons, CLI] Fixes several minor bugs found by the above script
  * [Daemons, CLI] Add support for Debian 11 "Bullseye"

#### v0.9.19

  * [CLI] Corrects some flawed conditionals
  * [API] Disables SQLAlchemy modification tracking functionality (not used by us)
  * [Daemons] Implements new zkhandler module for improved reliability and reusability
  * [Daemons] Refactors some code to use new zkhandler module
  * [API, CLI] Adds support for "none" migration selector (uses cluster default instead)
  * [Daemons] Moves some configuration keys to new /config tree
  * [Node Daemon] Increases initial lock timeout for VM migrations to avoid out-of-sync potential
  * [Provisioner] Support storing and using textual cluster network labels ("upstream", "storage", "cluster") in templates
  * [API] Avoid duplicating existing node states

#### v0.9.18

  * Adds VM rename functionality to API and CLI client

#### v0.9.17

  * [CLI] Fixes bugs in log follow output

#### v0.9.16

  * Improves some CLI help messages
  * Skips empty local cluster in CLI
  * Adjusts how confirmations happen during VM modify restarts
  * Fixes bug around corrupted VM log files
  * Fixes bug around subprocess pipe exceptions

#### v0.9.15

  * [CLI] Adds additional verification (--yes) to several VM management commands
  * [CLI] Adds a method to override --yes/confirmation requirements via envvar (PVC_UNSAFE)
  * [CLI] Adds description fields to PVC clusters in CLI

#### v0.9.14

  * Fixes bugs around cloned volume provisioning
  * Fixes some minor visual bugs
  * Minor license update (from GPL3+ to GPL3)
  * Adds qemu-guest-agent support to provisioner-created VMs by default

#### v0.9.13

  * Adds nicer startup messages for daemons
  * Adds additional API field for stored_bytes to pool stats
  * Fixes sorting issues with snapshot lists
  * Fixes missing increment/decrement of snapshot_count on volumes
  * Fixes bad calls in pool element API endpoints
  * Fixes inconsistent bytes_tohuman behaviour in daemons
  * Adds validation and maximum volume size on creation (must be smaller than the pool free space)

#### v0.9.12

  * Fixes a bug in the pvcnoded service unit file causing a Zookeeper startup race condition

#### v0.9.11

  * Documentation updates
  * Adds VNC information to VM info
  * Goes back to external Ceph commands for disk usage

#### v0.9.10

  * Moves OSD stats uploading to primary, eliminating reporting failures while hosts are down
  * Documentation updates
  * Significantly improves RBD locking behaviour in several situations, eliminating cold-cluster start issues and failed VM boot-ups after crashes
  * Fixes some timeout delays with fencing
  * Fixes bug in validating YAML provisioner userdata

#### v0.9.9

  * Adds documentation updates
  * Removes single-element list stripping and fixes surrounding bugs
  * Adds additional fields to some API endpoints for ease of parsing by clients
  * Fixes bugs with network configuration

#### v0.9.8

  * Adds support for cluster backup/restore
  * Moves location of `init` command in CLI to make room for the above
  * Cleans up some invalid help messages from the API

#### v0.9.7

  * Fixes bug with provisioner system template modifications

#### v0.9.6

  * Fixes bug with migrations

#### v0.9.5

  * Fixes bug with line count in log follow
  * Fixes bug with disk stat output being None
  * Adds short pretty health output
  * Documentation updates

#### v0.9.4

  * Fixes major bug in OVA parser

#### v0.9.3

  * Fixes bugs with image & OVA upload parsing

#### v0.9.2

  * Major linting of the codebase with flake8; adds linting tools
  * Implements CLI-based modification of VM vCPUs, memory, networks, and disks without directly editing XML
  * Fixes bug where `pvc vm log -f` would show all 1000 lines before starting
  * Fixes bug in default provisioner libvirt schema (`drive` -> `driver` typo)

#### v0.9.1

  * Added per-VM migration method feature
  * Fixed bug with provisioner system template listing

#### v0.9.0

Numerous small improvements and bugfixes. This release is suitable for general use and is pre-release-quality software.

This release introduces an updated version scheme; all future stable releases until 1.0.0 is ready will be made under this 0.9.z naming. This does not represent semantic versioning and all changes (feature, improvement, or bugfix) will be considered for inclusion in this release train.

#### v0.8

Numerous improvements and bugfixes. This release is suitable for general use and is pre-release-quality software.

#### v0.7

Numerous improvements and bugfixes, revamped documentation. This release is suitable for general use and is beta-quality software.

#### v0.6

Numerous improvements and bugfixes, full implementation of the provisioner, full implementation of the API CLI client (versus direct CLI client). This release is suitable for general use and is beta-quality software.

#### v0.5

First public release; fully implements the VM, network, and storage managers, the HTTP API, and the pvc-ansible framework for deploying and bootstrapping a cluster. This release is suitable for general use, though it is still alpha-quality software and should be expected to change significantly until 1.0 is released.

#### v0.4

Full implementation of virtual management and virtual networking functionality. Partial implementation of storage functionality.

#### v0.3

Basic implementation of virtual management functionality.

