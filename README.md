# PVC - The Parallel Virtual Cluster tool

#### NOTICE FOR GITHUB

This software is still incomplete, and should be considered pre-alpha and not suitable for production use! Not all features described below are implemented, and I will be committing directly to master until they are (version 1.0).

[![pipeline status](https://git.bonifacelabs.ca/bonifacelabs/pvc/badges/master/pipeline.svg)](https://git.bonifacelabs.ca/bonifacelabs/pvc/commits/master)

![Logo](https://git.bonifacelabs.ca/uploads/-/system/project/avatar/135/pvc_logo.png)

PVC is a suite of Python 3 tools to manage virtualized clusters. It provides a fully-functional private cloud based on the priciple that "PVC is not hyperscale". It is designed to be administrator-friendly while powerful, but without the feature bloat and complexity of tools like OpenStack that are designed to support public clouds. With PVC, an administrator can provision, manage, and update a cluster of dozens or more hypervisors running thousands of VMs using a simple CLI tool, HTTP API, or web interface. PVC is based entirely on Debian GNU/Linux and Free-and-Open-Source tools, providing the glue to bootstrap, provision and manage the cluster. Just add physical servers.

## Architecture overview

A PVC deployment ("cluster") consists of a cluster of hosts which share duties using a single daemon. The cluster is backed by a Zookeeper instance running on a subset of the machines and which all daemons communicate with to coordinate state.

### Physical infrastructure

The PVC system depends on a cluster of 3 or more physical servers. Each server must have the capability to run storage, client networks, and VMs, and a subset of these servers are configured at install time to also act as routers for the cluster.

The underlying networking is left up to the administrator; the only requirement is that all routers and hypervisors must be reachable by each other. In the simplest deployment, all physical nodes may be connected to a single dumb switch. All inter-VM networking is handled dynamically via software-defined networking within the cluster itself and is handled transparently above the underlying network layer. More advanced configurations may be specified during cluster initalization, including upstream networks, storage networks, and advanced node-level network configuration (vLANs, bonds, etc.)

The coordinator hosts [see below] require an additional upstream network. These hosts advertise BGP routes to the cluster networks on their upstream interface, and accept traffic destined to the clients; they route between themselves to reach VMs out the primary gateway node, so all coordinators are valid route targets. The router components of the daemon makes no effort to perform NAT or Internet gateway functions; an upstream router should be configured for this purpose.

PVC supports fencing of nodes when they do not update the Zookeeper database in a fixed, configurable time, to provide automated recovery from node failures. This feature requires IPMI networked BMC support, and credentials should be specified in in the configuration. Preparing IPMI for PVC's use is left to the administrator.

### Software infrastructure

The PVC server-side infrastructure consists of a single daemon, `pvcd`, which manages each node based on connectivity to the Zookeeper cluster. All nodes are capable of running virtual machines, Ceph storage OSDs, and passing traffic to virtual machines via configured networks.

A subset of the nodes are designated at install time to act as "coordinator" hosts for the cluster. By default, 3 or 5 nodes can be designated as coordinators; 3 is ideal for small deployments (<30 hypervisors) while 5 allow for much larger scaling. These coordinators run additional functions for the cluster beyond VMs and storage, mainly:

* running Zookeeper itself, acting as the central database for the cluster.
* running FRRouting in BGP server mode, performing route reflector and upstream routing functionality.
* running Ceph monitor and manager daemons for the storage cluster.
* acting as client network gateways, DHCP, and DNS servers.
* acting as provisioning servers for nodes and VMs.

A single coordinator elects itself "primary" to perform this duty at startup, and passes it off on shutdown; this can be modified manually by the administrator. The primary coordinator handles provisioning and client network functionality (gateway, DHCP, DNS) for the whole cluster, which the "secondary" coordinators can take over automatically if needed. While this architecture can suffer from tromboning when there is a larger inter-network traffic flow, it preserves a consistent and simple layer-2 model inside each client network for administrative simplicity.

New nodes can be added dynamically; once running, the cluster supports the PXE booting of additional hypervisors which are then self-configured and added to the cluster via the provisioning framework. This framework also allows for the quick deployment of VMs based off Ceph-stored images and templates.

The core external components are:

#### Zookeeper

Zookeeper is the primary database of the cluster, running on the coordinator nodes. All activity in the cluster is mediated by Zookeeper: clients read and write data to it, and daemons determine and update object configuration and state from it. The bootstrap tool initializes the cluster on the initial set of coordinator hosts, and once configured requires manual administrative action to modify; future version using Zookeeper 3.5 may offer self-managing functionality.

Coordinator hosts automatically attempt to start the Zookeeper daemon when they start up, if it has been shut down. If the Zookeeper cluster connection is lost, all clients will pause state update operations while waiting to reconnect. Note that fencing may be triggered if only one node loses Zookeeper connectivity, as the paused operations will prevent keepalives from being sent to the cluster. Take care when rebooting coordinator nodes so that the Zookeeper cluster continues to function normally.

#### FRRouting

FRRouting is used to provide BGP for management of client networks. It makes use of BGP EVPN to allow dynamic, software-defined VXLAN client networks presenting as simple layer-2 networks. VMs inside a particular client network can communicate directly as if they shared a switch. FRRouting also provides upstream BGP, allowing routes to the dynamic client networks to be learned by upstream routers.

#### dnsmasq

dnsmasq is used by the coordinator nodes to provide DHCP and DNS support for client networks. An individual instance is started on the primary coordinator for each network, handling that network specifically.

#### PowerDNS

PowerDNS is used by the coordinator nodes to aggregate client DNS records from the dnsmasq instances and present a complete picture of the cluster DNS to clients and the outside world. An instance runs on the primary coordinator aggregating dnsmasq entries, which can then be sent to other DNS servers via AXFR, including the in-cluster DNS servers usable by clients, which also make use of PowerDNS.

#### Libvirt

Libvirt is used to manage virtual machines in the cluster. It uses the TCP communication mode to perform live migrations between nodes and must be listening on daemon startup.

#### Ceph

Ceph provides the storage infrastructure to the cluster using RBD block devices. OSDs live in each node and VM disks are stored in copies of 3 across the cluster, ensuring a high degree of resiliency. The monitor and manager functions run on the coordinator nodes for scalability.

### Client interfaces

PVC provides three main administrator interfaces and a supplemental option:

* CLI
* HTTP API
* WebUI
* Direct Python bindings

#### CLI

The CLI interface (`pvc`, package `pvc-cli-client`) is used to bootstrap the cluster and is able to perform all administrative tasks. The client requires direct access to the Zookeeper cluster to operate, but is usable on any client machine; initalization however requires a Debian-based GNU/Linux system for optimal administrative ease.

Once the other administrative interfaces are provisioned, the CLI is not required, but is installed by default on all nodes in the cluster to facilitate on-machine troubleshooting and maintenance.

#### HTTP API

The HTTP API interface (`pvcapi`, package `pvc-api-client`) is configured by default on a special set of cluster-aware VMs, and provides a feature-complete implementation of the CLI interface via standard HTTP commands. The API allows building advanced configuration utilities integrating PVC without the overhead of the CLI. The HTTP API is optional and installation can be disabled during cluter initalization.

#### WebUI

The HTTP Web user interface (`pvcweb`, package `pvc-web-client`) is configured by default on the cluster-aware VMs running the HTTP API, and provides a stripped-down web interface for a number of common administrative tasks, as well as reporting and monitoring functionality. Like the HTTP API, the WebUI is optional and installation can be disabled during cluster initalization.

#### Direct Python bindings

While not specifically an interface, the Python functions used by the above interfaces are available via the package `pvc-client-common`, and can be used in custom scripts or programs directly to bypass the CLI or API interfaces.

## Changelog

#### 0.4

* Recombination of daemons and expansion of functionality into client network management and routing.

#### 0.3

* Major revisions to expand functionality.

#### 0.2

* Minor tweaks and stability improvements.

#### 0.1

* Initial release; all basic functionality implemented.

## Building

This repo contains the required elements to build Debian packages for PVC. It is not handled like a normal Python package but instead the debs contain the raw files placed in Debianized places.

1. Run `build-deb.sh`; you will need `dpkg-buildpackage` installed.
2. The output files for each daemon and client will be located in the parent directory.
