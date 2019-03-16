# About the Parallel Virtual Cluster suite

## Changelog

#### v0.4

Full implementation of virtual management and virtual networking functionality. Partial implementation of storage functionality.

#### v0.3

Basic implementation of virtual management functionality.

## Philosophical Overview

The current state of the private cloud as of 2019 is very weak. On the one hand are the traditional tools, which let you manage a KVM cluster using scripts but requiring large amounts of administrator work and manual configuration based off very rough best practices. On the other hand are the "cloud infrastructure" tools, which are either massive and unwieldy, complex, and in some cases costly, or simply don't fit the traditional niche of virtualized servers.

PVC aims to be a middle option - all the features of a modern cloud, such as software-defined storage and networking, full high-availability at every layer, and software-based management via APIs, combined with a very shallow learning curve and minimal complexity for the administrator on the CLI or WebUI, all while being completely Free Software-based. It adheres to four main principles, which we will outline in some detail below.

#### Be Free Software Forever (or Bust)

Free Software is important. Without the ability to study, modify, and change our software, we are beholden to other, often corporate, actors and their motives. PVC commits to being Free Software in the strictest sense, licensed under the GNU GPL 3.0 (or later), and promising now and forever to not charge a cent for a single feature - no "open core paid addons" philosophy, and no tricks. What you see is always what you get, and you are always free to modify PVC to fit your needs and contribute back to the community.

#### Be Opinionated and Efficient and Pick The Best Software

Choice is good, until we become paralyzed by it, so don't try to be everything for everyone at the expense of good design. PVC aims to make a lot of decisions on software components, as well as how components interact and the overall architecture, for you, based on current best practices, so you can get on with your life. PVC aims to make good design choices based on solid, modern technologies, not held back by legacy debt, while still providing enough configuration flexibility to support almost any administrators' workload.

#### Be Scalable and Redundant but Not Hyperscale

A cluster that can only scale to two nodes is not scalable. PVC aims to be scalable to any reasonable size from 1 to 100+ hypervisors and thousands of VMs. However, PVC is *not* "hyperscale" - it knows where it stands, and isn't afraid to have an upper bound after which another more complex cluster suite is better suited. But it also isn't limited to a 2- or 3- node cluster forcing you to make such a decision just a short time in the future. PVC aims to bridge the gap between "unscalable" and "hyperscale", and provide administrators with a cluster they can use for years to come and grow beyond what they expect, and is perfect for anything from a homelab to a small datacenter without compromising today.

#### Be Simple To Use, Configure, and Maintain

Administrator time is valuable, and every minute you spend babysitting pets or learning the intricacies of an overly-complex "Cloud" platform is time you could better spend learning, growing, and evolving your other systems. PVC aims to always be simple for an administrator to use, at every stage from bootstrapping, scaling, and day-to-day administration. At the same time, it aims to be extremely powerful, backed by solid infrastructure design that gives you the best possible system without compromising flexibility. Set up your cluster in a day; grow it for years; manage it in seconds.

## Architecture overview

PVC is based on a semi-decentralized design with a dynamic number of fully-functional nodes. Each node in the cluster is capable, based on the configuration, of handling any cluster tasks if needed. However in a normal deployment, the first 3 or 5 servers act as cluster "coordinators", taking on a number of management roles, while other nodes connect to the coordinators for state and information. One coordinator provides additional "primary" functionality, such as DHCP services, DNS aggregation, and client network gateways/routing, and this role can pass dynamically between coordinators based on administrator intervention or automated cluster events.

The coordinator nodes host a number of services, configured at bootstrap time, that are not infinitely scalable across all nodes. These include a Zookeeper cluster for state management, MariaDB+Galera SQL cluster for DNS, and various processes supporting the primary node. Coordinators can be replaced, added, or removed by the administrator, though by default any additional nodes are configured as non-coordinators, allowing the cluster to scale out to 100 or more hypervisors while still keeping the databases manageable. Noticeably compared to other cloud cluster products, these functions do not require ever more additional servers to support, and are all built in to the main PVC daemon functionality or a small set of "cluster" VMs which are installed by default at bootstrap.

The primary database is Zookeeper, which is used to provide the distributed and coordinated state used by the PVC cluster to determine what resources exist, where they live, and when they should run. The Zookeeper cluster is created on the initial coordinators at bootstrap time, and can scale out onto more coordinators later as required.

The secondary database is MariaDB with the Galera multi-master functionality. This database primarily supports DNS aggregation services, providing a unified view of the cluster and its clients in DNS without additional administrator intervention. Some additional information about the provisioning state is kept in the database as an intermediate to being stored in Zookeeper.

PVC handles both storage and networking as software configurations defined dynamically based on data in the Zookeeper database. It makes use of BGP EVPN to provide limitless, virtual layer 2 networks for clients in the cluster, and networks are isolated by NFT firewalls, with optional DHCP and IPv6 support in client networks. Storage is provided by Ceph for redundant, replicated block devices, which scales along with the cluster in both performance and size.

### Physical Infrastructure

PVC requires only a very simple physical infrastructure: 1, 3, or more physical servers connected via Ethernet on two flat L2 networks. More complicated topologies are supported during the bootstrapping phase but the simplest configuration should be sufficient for most simple, basic clusters or for learning.

Each node requires a single L2 network which provides the client and storage interconnections for the cluster. These roles are separated into two distinct L3 networks, allowing them to be split onto different L2 networks if desired. These networks live entirely within the cluster and must not be shared outside the cluster or with other systems. The standard configuration is an RFC1918 /24 network for each role to provide plenty of room for nodes and the supporting cluster VMs, while being scalable up to ~100 hypervisors. A special floating IP is designated in the cluster network to provide a single point of interface to the primary coordinator.

Each coordinator node, but optionally all nodes, requires a second L2 network which provides upstream routing into the cluster. In the simplest configuration, only the coordinators are present in this network and share routes to client networks and receive outside traffic to the client networks through it. PVC provides no NAT support and no explicit firewalling in from this network, so any external gateway interfaces should connect into the PVC cluster via this intermediate network for security purposes. A special floating IP is designated in the upstream network to provide a single point of interface to the primary coordinator, most importantly for static routing.

The physical hardware of the nodes depends on the target workload. Generally, at least 32GB RAM and 8 CPU cores (excluding SMT threads) is the minimum for a single node, but extremely small configurations are possible, if very limited. Note that the Ceph storage disks, PVC daemons, and, on coordinator nodes, databases and Ceph monitors, all require additional RAM and CPU power on top of the requirements of virtualized guests, so ensure that each node is tall enough for your workload and then scale out for redundancy.

All Ceph storage disks should be SSDs for optimal performance and scalability. Even small clusters generate a large amount of storage activity, so consider baseline performance carefully when selecting drives.

Network traffic can be small to extremely high depending especially on storage requirements and cluster size. As mentioned above, the storage network is separate from the cluster network in L3, allowing it to be isolated onto a faster L2 network if required. 1GbE is the bare minimum for small clusters, or the client network on midsize clusters, but 10GbE is recommended for any clusters larger than 3 nodes for at least the storage network. Larger clusters may require separate 10GbE client and storage networks, LCAP, or more advanced configurations to provide optimal throughput for storage, all of which can be configured at bootstrap or reconfigured as the cluster grows with minimal interruption.

PVC features fencing of nodes, and they should be accessible via an IPMI lights-out management interface to allow broken nodes to be removed from service automatically by the cluster. Running without fencing is not inherently dangerous, but has a higher chance of stalling services if nodes fail and do not properly take themselves out of service. The IPMI interfaces can be in the cluster network, or in another network reachable by the nodes via the upstream network.

### Software infrastructure

The PVC server-side infrastructure consists of a single daemon, `pvcd`, which manages each node based on state information from the Zookeeper database. All nodes are capable of running virtual machines, Ceph storage OSDs, and passing traffic to virtual machines via client L2 networks.

A subset of the nodes are designated to act as "coordinator" hosts for the cluster. Usually, 3 or 5 nodes are designated as coordinators; 3 is ideal for small deployments (<30 hypervisors) while 5 allow for much larger scaling, and larger odd numbers of coordinators are possible for very large clusters. These coordinators run additional functions for the cluster beyond VMs and storage, mainly:

* running Zookeeper itself, acting as the central database for the cluster.
* running FRRouting in BGP server mode, performing route reflector and upstream routing functionality.
* running Ceph monitor and manager daemons for the storage cluster.
* acting as cluster network gateways, DHCP, and DNS servers.
* acting as provisioning servers for nodes and VMs.

A single coordinator elects itself "primary" to perform this duty at startup, and passes it off on shutdown; this can be modified manually by the administrator. The primary coordinator handles provisioning and cluster network functionality (gateway, DHCP, DNS) for the whole cluster, which the "secondary" coordinators can take over automatically if needed. While this architecture can suffer from tromboning when there is a large inter-network traffic flow, it preserves a consistent and simple layer-2 model inside each client network for administrative simplicity.

New nodes can be added dynamically; once running, the cluster supports the PXE booting of additional hypervisors which are then self-configured and added to the cluster via the provisioning framework. This framework also allows for the quick deployment of VMs based off Ceph-stored images and templates.

The core external components are:

#### Zookeeper

Zookeeper is the primary database of the cluster, running on the coordinator nodes. All activity in the cluster is mediated by Zookeeper: clients read and write data to it, and daemons determine and update object configuration and state from it. The bootstrap tool initializes the cluster on the initial set of coordinator hosts, and once configured requires manual administrative action to modify; future version using Zookeeper 3.5 may offer self-managing functionality.

Coordinator hosts automatically attempt to start the Zookeeper daemon when they start up, if it has been shut down. If the Zookeeper cluster connection is lost, all clients will pause state update operations while waiting to reconnect. Note that fencing may be triggered if only one node loses Zookeeper connectivity, as the paused operations will prevent keepalives from being sent to the cluster. Take care when rebooting coordinator nodes so that the Zookeeper cluster continues to function normally.

#### FRRouting

FRRouting is used to provide BGP for management of cluster networks. It makes use of BGP EVPN to allow dynamic, software-defined VXLAN client networks presenting as simple layer-2 networks. VMs inside a particular client network can communicate directly as if they shared a switch. FRRouting also provides upstream BGP, allowing routes to the dynamic client networks to be learned by upstream routers.

#### dnsmasq

dnsmasq is used by the coordinator nodes to provide DHCP and DNS support for cluster networks. An individual instance is started on the primary coordinator for each network, handling that network specifically.

#### PowerDNS

PowerDNS is used by the coordinator nodes to aggregate client DNS records from the dnsmasq instances and present a complete picture of the cluster DNS to clients and the outside world. An instance runs on the primary coordinator aggregating dnsmasq entries, which can then be sent to other DNS servers via AXFR, including the in-cluster DNS servers usable by clients, which also make use of PowerDNS.

#### Libvirt

Libvirt is used to manage virtual machines in the cluster. It uses the TCP communication mode to perform live migrations between nodes and must be listening on daemon startup.

#### Ceph

Ceph provides the storage infrastructure to the cluster using RBD block devices. OSDs live in each node and VM disks are stored in copies of 3 across the cluster, ensuring a high degree of resiliency. The monitor and manager functions run on the coordinator nodes for scalability.

## Client interfaces

PVC provides three main administrator interfaces and a supplemental option:

* CLI
* HTTP API
* WebUI
* Direct Python bindings

### CLI

The CLI interface (`pvc`, package `pvc-cli-client`) is used to bootstrap the cluster and is able to perform all administrative tasks. The client requires direct access to the Zookeeper cluster to operate, but is usable on any client machine; initialization however requires a Debian-based GNU/Linux system for optimal administrative ease.

Once the other administrative interfaces are provisioned, the CLI is not required, but is installed by default on all nodes in the cluster to facilitate on-machine troubleshooting and maintenance.

### HTTP API

The HTTP API interface (`pvcapi`, package `pvc-api-client`) is configured by default on a special set of cluster-aware VMs, and provides a feature-complete implementation of the CLI interface via standard HTTP commands. The API allows building advanced configuration utilities integrating PVC without the overhead of the CLI. The HTTP API is optional and installation can be disabled during clutter initialization.

### WebUI

The HTTP Web user interface (`pvcweb`, package `pvc-web-client`) is configured by default on the cluster-aware VMs running the HTTP API, and provides a stripped-down web interface for a number of common administrative tasks, as well as reporting and monitoring functionality. Like the HTTP API, the WebUI is optional and installation can be disabled during cluster initialization.

### Direct Python bindings

While not specifically an interface, the Python functions used by the above interfaces are available via the package `pvc-client-common`, and can be used in custom scripts or programs directly to bypass the CLI or API interfaces.
