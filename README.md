# PVC - The Parallel Virtual Cluster tool

[![pipeline status](https://git.bonifacelabs.ca/bonifacelabs/pvc/badges/master/pipeline.svg)](https://git.bonifacelabs.ca/bonifacelabs/pvc/commits/master)

![Logo](./pvc_logo.svg)
<img src="./pvc_logo.svg">

PVC is a suite of Python 3 tools to manage virtualized clusters. It provides a fully-functional private cloud based on the priciple that "PVC is not hyperscale". It is designed to be administrator-friendly while powerful, but without the feature bloat and complexity of tools like OpenStack that are designed to support public clouds. With PVC, an administrator can provision, manage, and update a cluster of dozens or more hypervisors running thousands of VMs using a simple CLI tool, HTTP API, or web interface. PVC is based entirely on Debian GNU/Linux and Free-and-Open-Source tools, providing the glue to provision and manage the cluster.

## Architecture overview

A PVC deployment ("cluster") consists of a standard physical layout and suite of daemons to manage the physical elements. The cluster is backed by a Zookeeper instance running on a subset of the machines and which all daemons communicate with to coordinate state.

### Physical infrastructure

A cluster consists of two main kinds of physical servers - routers and hypervisors. A cluster will normally have two routers in a failover pair, and at least three hypervisors.

Router nodes may be less powerful than full hypervisors; they act primarily as the gateway for VM networks and handles inter-network ACLs. While they are not strictly required, a proper deployment with all functionality will require them.

Hypervisor nodes should be scaled at the administrator's discretion; they may be low-power and scaled out, or high-power and scaled up. PVC provides a straightforward automated provisioning system to expand the cluster as required.

The underlying networking is left up to the administrator; the only requirement is that all routers and hypervisors must be reachable by each other. In the simplest deployment, all physical nodes may be connected to a single dumb switch. All inter-VM networking is handled dynamically via software-defined networking within the cluster itself and is handled transparently above the underlying network layer. More advanced configurations may be specified during cluster initalization.

### Software infrastructure

The core functionality of PVC is obtained via Zookeeper. During cluster initalization, the administrator must set either 3 or 5 hypervisors to act as the Zookeeper coordination subcluster. These hypervisors are special in the cluster and should not be removed after creation. This configuration prevents Zookeeper cluster size bloat as the cluster grows while still providing adequate redundancy for Zookeeper.

All daemons communicate with Zookeeper to obtain state, and update Zookeper as required, providing a high degree of self-management. Most major failure conditions are handled transparently by the cluster.

FRRouting is used to manage virtual networking via BGP EVPN, and Libvirt is used to manage virtual machines.

PVC itself is composed of four daemons:

* Virtualization
* Network
* Router
* Provisioning

#### Virtualization

The virtualization daemon (`pvcvd`, package `pvc-virtualization-daemon`) manages QEMU/KVM virtual machines on hypervisor nodes. Domain configurations are stored in Zookeeper and VMs are dynamically created on hypervisor nodes based on Zookeeper configuration values. The virtualization daemon handles all stages of the VM lifecycle, including triggering startup, restart, graceful ACPI shutdown, and forceful termination.

By default, each VM lives on a particular "home" node, and can be live migrated away either temporarily (`migrate`) or permanently (`move`). During provisioning and normal `migrate`/`move` commands, the selection of the target hypervisor is dynamic, based on administator-configurable variables.

#### Network

The network daemon (`pvcnd`, package `pvc-network-daemon`) manages the hypervisor-side virtual networking for the cluster. It is responsible for provisioning VXLAN devices on hypervisor nodes for VM network access.

#### Router

The router daemon (`pvcrd`, package `pvc-router-daemon`) manages the router-side virtual networking for the cluster. It includes functionality for managing the gateways of each virtual network, as well as providing network ACLs and IP forwarding to an upsteam, and DHCP for client networks.

#### Provisioning

The provisioning daemon (`pvcpd`, package `pvc-provisioning-daemon`) manages the setup and creation of new physical nodes, new virtual machines, as well as handling updates of the cluster. The provisioning daemon can be run on any nodes, but is normally run on the routers to simplify administration.


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
