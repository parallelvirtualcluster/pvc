# About the Parallel Virtual Cluster system

- [About the Parallel Virtual Cluster system](#about-the-parallel-virtual-cluster-system)
  * [Project Motivation](#project-motivation)
  * [Building Blocks](#building-blocks)
  * [Cluster Architecture](#cluster-architecture)
  * [Clients](#clients)
    + [API Client](#api-client)
    + [Direct Bindings](#direct-bindings)
    + [CLI Client](#cli-client)
  * [Deployment](#deployment)
  * [Frequently Asked Questions](#frequently-asked-questions)
    + [General Questions](#general-questions)
    + [Feature Questions](#feature-questions)
    + [Storage Questions](#storage-questions)
  * [About The Author](#about-the-author)

This document contains information about the project itself, the software stack, its motivations, and a number of frequently-asked questions.

## Project Motivation

Server administration has changed significantly in recent decades. Computing-as-a-resource and software-defined infrastructure is now the norm, and the days of pet servers, painstaking manual configurations, and installing from CR-ROM ISOs is long gone. This is a brave new world.

As part of these trends, Infrastructure-as-a-Service (IaaS) has become a critical component of server administration. Administrators and developers are increasingly interfacing with their infrastructure via programmable APIs and software tools, and automation is a hard requirement. While Container infrastructure like Docker and Kubernetes has become more and more popular in this space, Virtual Machines (VMs) are still a very common feature and do not seem to be going anywhere any time soon.

However, the current state of the free and open source virtualization ecosystem is lacking.

At the lower end, projects like ProxMox provide an easy way to administer small virtualization clusters, but these projects tend to lack advanced redundancy facilities that are built-in by default. While there are some new contenders in this space, such as Harvester, the options are limited and their feature-sets and tool stacks can be cumbersome or unproven.

At the higher end, very large projects like OpenStack and CloudStack provide very advanced functionality, but these project are sprawling and complicated for Administrators to use, and are very focused on large enterprise deployments, not suitable for smaller clusters and teams.

Finally, proprietary solutions dominate this space. VMWare and Nutanix are the two largest names, with these products providing functionality for both small and large clusters, but proprietary software limits both flexibility and freedom, and the costs associated with these solutions is immense.

PVC aims to bridge the gaps between these three categories. Like the larger FLOSS and proprietary projects, PVC can scale up to very large cluster sizes, while remaining usable even for small clusters as well. Like the smaller FLOSS and proprietary projects, PVC aims to be very simple to use, with a fully programmable API, allowing administrators to get on with more important things. Like the other FLOSS solutions, PVC is free, both as in beer and as in speech, allowing the administrator to inspect, modify, and tailor it to their needs. And finally, PVC is built from the ground-up to support host-level redundancy at every layer, rather than this being an expensive, optional, or tacked on feature.

In short, it is a Free Software, scalable, redundant, self-healing, and self-managing private cloud solution designed with administrator simplicity in mind. 

## Building Blocks

PVC is build from a number of other, open source components. The main system itself is a series of software daemons (services) written in Python 3, with the CLI interface also written in Python 3.

Virtual machines themselves are run with the Linux KVM subsystem via the Libvirt virtual machine management library. This provides the maximum flexibility and compatibility for running various guest operating systems in multiple modes (fully-virtualized, para-virtualized, virtio-enabled, etc.).

To manage cluster state, PVC uses Zookeeper. This is an Apache project designed to provide a highly-available and always-consistent key-value database. The various daemons all connect to the distributed Zookeeper database to both obtain details about cluster state, and to manage that state. For instance the node daemon watches Zookeeper for information on what VMs to run, networks to create, etc., while the API writes to or reads information from Zookeeper in response to requests. The Zookeeper database is the glue which holds the cluster together.

Additional relational database functionality, specifically for the managed network DNS aggregation subsystem and the VM provisioner, is provided by the PostgreSQL database system and the Patroni management tool, which provides automatic clustering and failover for PostgreSQL database instances.

Node network routing for managed networks providing EBGP VXLAN and route-learning is provided by FRRouting, a descendant project of Quaaga and GNU Zebra. Upstream routers can use this interface to learn routes to cluster networks as well. PVC also makes extensive use of the standard Linux `iprouting` stack.

The storage subsystem is provided by Ceph, a distributed object-based storage subsystem with proven stability, extensive scalability, self-managing, and self-healing functionality. The Ceph RBD (RADOS Block Device) subsystem is used to provide VM block devices similar to traditional LVM or ZFS zvols, but in a distributed, shared-storage manner.

All the components are designed to be run on top of Debian GNU/Linux, specifically Debian 10.x "Buster" or 11.x "Bullseye", with the SystemD system service manager. This OS provides a stable base to run the various other subsystems while remaining truly Free Software, while SystemD provides functionality such as automatic daemon restarting and complex startup/shutdown ordering.

## Cluster Architecture

A PVC cluster is based around "nodes", which are physical servers on which the various daemons, storage, networks, and virtual machines run. Each node is self-contained and is able to perform any and all cluster functions if needed and configured to do so; there is no strict segmentation of function between different "types" of physical hosts. Ideally, all nodes in a cluster will be identical in specifications, but in some situations mismatched nodes are acceptable, with limitations.

A subset of the nodes, called "coordinators", are statically configured to provide services for the cluster. For instance, all databases, FRRouting instances, and Ceph management daemons run only on the set of cluster coordinators. At cluster bootstrap, 1 (testing-only), 3 (small clusters), or 5 (large clusters) nodes may be chosen as the coordinators. Other nodes can then be added as "hypervisor" nodes, which then provide only block device (storage) and VM (compute) functionality by connecting to the set of coordinators. This limits the scaling problem of the databases while ensuring there is still maximum redundancy and resiliency for the core cluster services. 

Additional nodes can be added to the cluster either as coordinators, or as hypervisors, by adding them to the Ansible configuration and running it against the full set of nodes. Note that the number of coordinators must always be odd, and more than 5 coordinators are normally unnecessary and can cause issues with the database; it is thus normally advisable to add any nodes beyond the initial set as hypervisors instead of coordinators. Nodes can be removed from service, but this is a manual process and should not be attempted unless absolutely required; the Ceph subsystem in particular is sensitive to changes in the coordinator nodes. Nodes can also be upgraded or replaced dynamically and without interrupting the cluster, allowing for seamless hardware maintenance, upgrades, and even replacement, as cluster state configuration is held cluster-wide.

During runtime, one coordinator is elected the "primary" for the cluster. This designation can shift dynamically in response to cluster events, or be manually migrated by an administrator. The coordinator takes on a number of roles for which only one host may be active at once, for instance to provide DHCP services to managed client networks or to interface with the API.

Nodes are networked together via a set of statically-configured, simple layer-2 networks. At a minimum, 2 discrete networks are required, with an optional 3rd.

 * The "upstream" network is the primary network for the nodes, and provides functions such as upstream Internet access, routing to and from the cluster nodes, and management via the API; it may be either a firewalled public or NAT'd RFC1918 network, but should never be exposed directly to the Internet. It should also contain, or be able to route to, the IPMI BMC management interfaces of the node chassis'.
 * The "cluster" network is an unrouted RFC1918 network which provides inter-node communication for managed client network traffic (VXLANs), cross-node routing, VM migration and failover, and database replication and access.
 * The "storage" network is another unrouted RFC1918 network which provides a dedicated logical and/or physical link between the nodes for storage traffic, including VM block device storage traffic, inter-OSD replication traffic, and Ceph heartbeat traffic, thus allowing it to be completely isolated from the other networks for maximum performance. This network can be optionally colocated with the "cluster" network, by specifying the same device for both, and can be further combined by specifying the same IP for both to completely collapse the "cluster" and "storage" networks. A collapsed cluster+storage configuration may be ideal to simplify management of small clusters, or a split configuration can be used to provide flexibility for large or demanding high-performance clusters - this choice is left to the administrator based on their needs.
 
 Within each network is a single "floating" IP address which follows the primary coordinator, providing a single interface to the cluster. Once configured, the cluster is then able to create additional networks of two kinds, "bridged" traditional vLANs and "managed" routed VXLANs, to provide network access to VMs.

Further information about the general cluster architecture, including important considerations for node specifications/sizing and network configuration, [can be found at the cluster architecture page](/cluster-architecture). It is imperative that potential PVC administrators read this document thoroughly to understand the specific requirements of PVC and avoid potential missteps in obtaining and deploying their cluster.

## Clients

### API Client

The API client is a Flask-based RESTful API and is the core interface to PVC. By default the API will run on the primary coordinator, listening on TCP port 7370 on the "upstream" network floating IP address. All other clients communicate with this API to perform actions against the cluster. The API features basic authentication using UUID-based API keys to prevent unauthorized access, and can optionally be configured with full TLS encryption to provide integrity and confidentiality across public networks.

The API generally accepts all requests as HTTP form requests following standard RESTful guidelines, supporting arguments in the URI string or, with limited exceptions, in the message body. The API returns JSON response bodies to all requests consisting either of the information requested, or a `{ "message": "text" }` construct to pass informational status messages back to the client.

The API client manual can be found at the [API manual page](/manuals/api), and the full API details can be found in the [API reference specification](/manuals/api-reference.html).

### Direct Bindings

The API client uses a dedicated set of Python libraries, packaged as the `pvc-daemon-common` Debian package, to communicate with the cluster. One can thus use these libraries to build custom Python clients that directly interface with the PVC cluster, without having to get "into the weeds" of the Zookeeper or PostgreSQL databases.

### CLI Client

The CLI client is a Python Click application, which provides a convenient CLI interface to the API client. It supports connecting to multiple clusters from a single instance, with or without authentication and over both HTTP or HTTPS, including a special "local" cluster if the client determines that an API configuration exists on the local host. Information about the configured clusters is stored in a local JSON document, and a default cluster can be set with an environment variable. The CLI client can thus be run either on PVC nodes themselves, or on other, remote systems which can then interface with cluster(s) over the network.

The CLI client is self-documenting using the `-h`/`--help` arguments throughout, easing the administrator learning curve and providing easy access to command details. A short manual can also be found at the [CLI manual page](/manuals/cli).

## Deployment

The overall management, deployment, bootstrapping, and configuring of nodes is accomplished via a set of Ansible roles and playbooks, found in the [`pvc-ansible` repository](https://github.com/parallelvirtualcluster/pvc-ansible), and nodes are installed via a custom installer ISO generated by the [`pvc-installer` repository](https://github.com/parallelvirtualcluster/pvc-installer). Once the cluster is set up, nodes can be added, replaced, updated, or reconfigured using this Ansible framework.

Details about the Ansible setup and node installer can be found in those repositories.

The [getting started documentation](/getting-started) provides a walk-through of using these tools to bootstrap a new cluster.

## Frequently Asked Questions

### General Questions

#### What is it?

PVC is a virtual machine management suite designed around high-availability and ease-of-use. It can be considered an alternative to OpenStack, ProxMox, Nutanix, and other similar solutions that manage not just the VMs, but the surrounding infrastructure as well.

#### Why would you make this?

After becoming frustrated by numerous other management tools, I discovered that what I wanted didn't exist as FLOSS software, so I built it myself. Since then, I have also been able to leverage PVC both for my own purposes as well as for my employer, a win-win for the project.

#### Is PVC right for me?

PVC might be right for you if:

1. You need KVM-based VMs.
2. You want management of storage and networking (a.k.a. "batteries-included") in the same tool.
3. You want hypervisor-level redundancy, able to tolerate hypervisor downtime seamlessly, for all elements of the stack.
4. You have a requirement of at least 3 nodes' worth of compute and storage.

If all you want is a simple home server solution, or you demand scalability beyond a few dozen compute nodes, PVC is likely not what you're looking for. Its sweet spot is specifically in the 3-9 node range, for instance in an advanced homelab, for SMBs or small ISPs with a relatively small server stack, or for MSPs looking to deploy small on-premises clusters at low cost.

#### Is 3 hypervisors really the minimum?

For a redundant cluster, yes. PVC requires a majority quorum for proper operation at various levels, and the smallest possible majority quorum is 2-of-3; thus 3 nodes is the smallest safe minimum. That said, you can run PVC on a single node for testing/lab purposes without host-level redundancy, should you wish to do so, and it might also be possible to run 2 "main" systems with a 3rd "quorum observer" hosting only the management tools but no VMs; however these options are not officially supported, as PVC is designed primarily for 3+ node operation.

### Feature Questions

#### Does PVC support containers (Docker/Kubernetes/LXC/etc.)?

No, not directly. PVC supports only KVM VMs. To run containers, you would need to run a VM which then runs your containers. For instance PVC makes an excellent underlying layer for a virtual Kubernetes cluster, instead of bare hardware.

#### Does PVC have a WebUI?

Not yet. Right now, PVC management is done exclusively with the CLI interface to the API. A WebUI can and likely will be built in the future, but I'm not a frontend developer and I do not consider this a personal priority. As of late 2020 the API is generally stable, so I would welcome 3rd party assistance here.

#### I want feature X, does it fit with PVC?

That depends on the specific feature. I will limit features to those that align with the overall goals of PVC, that is to say, to provide an easy-to-use hyperconverged virtualization system focused on redundancy. If a feature suits this goal it is likely to be considered; if it does not, it will not. PVC is rapidly approaching the completion of its 1.0 road-map, which I consider feature-complete for the primary use-case, and future versions may expand in scope.

### Storage Questions

#### Can I use RAID-5/RAID-6 with PVC?

The short answer is no. The long answer is: Ceph, the storage backend used by PVC, does support "erasure coded" pools which implement a RAID-5-like (striped with distributed parity) functionality, but PVC does not support this for several reasons, mostly related to ease of management and performance. If you use PVC, you must accept at the very least a 2x storage penalty, and for true multi-node safety and resiliency, a 3x storage penalty for VM storage. This is a trade-off of the architecture and should be taken into account when sizing storage in nodes.

#### Can I use spinning HDDs with PVC?

You can, but you won't like the results. SSDs, and specifically datacentre-grade SSDs for resiliency, are required to obtain any sort of reasonable performance when running multiple VMs. The higher-performance the drives, the faster the storage.

#### What network speed does PVC require?

For optimal performance, nodes should use at least 10-Gigabit Ethernet network interfaces wherever possible, and on large clusters a dedicated 10-Gigabit "storage" network, separate from the "upstream"/"cluster" networks, is strongly recommended. The storage system performance, especially for writes, is more heavily bottlenecked by the network speed than the actual storage device speed when speaking of high-performance disks. 1-Gigabit Ethernet will be sufficient for some use-cases and is sufficient for the non-storage networks (VM traffic notwithstanding), but storage performance will become severely limited as the cluster grows. Even slower network speeds (e.g. 100-Megabit) are not sufficient for PVC to operate properly except in very limited testing scenarios.

#### What Ceph version does PVC use?

PVC requires Ceph 14.x (Nautilus). The official PVC repository at https://repo.bonifacelabs.ca includes Ceph 14.2.x for Debian Buster (updated regularly), since by default it only includes 12.x (Luminous).

## About The Author

PVC is written by [Joshua](https://www.boniface.me) [M.](https://bonifacelabs.ca) [Boniface](https://github.com/joshuaboniface). A Linux system administrator by trade, Joshua is always looking for the best solutions to his user's problems, be they developers or end users. PVC grew out of his frustration with the various FOSS virtualization tools, as well as and specifically, the constant failures of Pacemaker/Corosync to gracefully manage a virtualization cluster. He started work on PVC at the end of May 2018 as a simple alternative to a Corosync/Pacemaker-managed virtualization cluster, and has been growing the feature set and stability of the system ever since.

