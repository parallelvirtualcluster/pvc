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

Server management and system administration have changed significantly in the last decade. Computing as a resource is here, and software-defined is the norm. Gone are the days of pet servers, of tweaking configuration files by hand, and of painstakingly installing from ISO images in 52x CD-ROM drives. This is a brave new world.

As part of this trend, the rise of IaaS (Infrastructure as a Service) has created an entirely new way for administrators and, increasingly, developers, to interact with servers. They need to be able to provision virtual machines easily and quickly, to ensure those virtual machines are reliable and consistent, and to avoid downtime wherever possible. Even in a world of containers, VMs are still important, and are not going away, so some virtual management solution is a must.

However, the current state of this ecosystem is lacking. At present there are 3 primary categories: the large "Stack" open-source projects, the smaller traditional "VM management" open-source projects, and the entrenched proprietary solutions.

At the high end of the open-source ecosystem, are the "Stacks": OpenStack, CloudStack, and their numerous "vendorware" derivatives. These are large, unwieldy projects with dozens or hundreds of pieces of software to deploy in production, and can often require a large team just to understand and manage them. They're great if you're a large enterprise, building a public cloud, or have a team to get you going. But if you just want to run a small- to medium-sized virtual cluster for your SMB or ISP, they're definitely overkill and will cause you more headaches than they will solve long-term.

At the low end of the open source ecosystem, are what I call the "traditional tools". The biggest name in this space is ProxMox, though other, mostly defunct projects like Ganeti, tangental projects like Corosync/Pacemaker, and even traditional "I just use scripts" methods fit as well. These projecs are great if you want to run a small server or homelab, but they quickly get unwieldy, though for the opposite reason from the Stacks: they're too simplistic, designed around single-host models, and when they provide redundancy at all it is often haphazard and nowhere near production-grade.

Finally, the proprietary solutions like VMWare and Nutanix have entrenched themselves in the industry. They're excellent pieces of software providing just about anything you would need, but this comes at a signficant cost, both in terms of money and also in software freedom and vendor lock-in. The licensing costs of Nutanix for instance can often make even enterprise-grade customers' accountants' heads spin.

PVC seeks to bridge the gaps between these 3 categories. It is fully Free Software like the first two categories, and even more so - PVC is committed to never be "open-core" software and to never hide a single feature behind a paywall; it is able to scale from very small (1 or 3 node) clusters up to a dozen or more nodes, bridging the first two categories as effortlessly as the third does; it makes use of a hyperconverged architecture like ProxMox or Nuntanix to avoid wasting hardware resources on dedicated controller, hypervisor, and storage nodes; it is redundant at every layer from the ground-up, something that is not designed into any other free solution, and is able to tolerate the loss any single disk or entire node with barely a blip, all without administrator intervention; and finally, it is designed to be as simple to use as possible, with an Ansible-based node management framework, a RESTful API client interface, and a consistent, self-documenting CLI administraton tool, allowing an administrator to create and manage their cluster quickly and simply, and then get on with more interesting things.

In short, it is a Free Software, scalable, redundant, self-healing, and self-managing private cloud solution designed with administrator simplicity in mind.

## Building Blocks

PVC is build from a number of other, open source components. The main system itself is a series of software daemons (services) written in Python 3, with the CLI interface also written in Python 3.

Virtual machines themselves are run with the Linux KVM subsystem via the Libvirt virtual machine management library. This provides the maximum flexibility and compatibility for running various guest operating systems in multiple modes (fully-virtualized, para-virtualized, virtio-enabled, etc.).

To manage cluster state, PVC uses Zookeeper. This is an Apache project designed to provide a highly-available and always-consistent key-value database. The various daemons all connect to the distributed Zookeeper database to both obtain details about cluster state, and to manage that state. For instance the node daemon watches Zookeeper for information on what VMs to run, networks to create, etc., while the API writes information to Zookeeper in response to requests.

Additional relational database functionality, specifically for the DNS aggregation subsystem and the VM provisioner, is provided by the PostgreSQL database and the Patroni management tool, which provides automatic clustering and failover for PostgreSQL database instances.

Node network routing for managed networks providing EBGP VXLAN and route-learning is provided by FRRouting, a descendant project of Quaaga and GNU Zebra.

The storage subsystem is provided by Ceph, a distributed object-based storage subsystem with extensive scalability, self-managing, and self-healing functionality. The Ceph RBD (Rados Block Device) subsystem is used to provide VM block devices similar to traditional LVM or ZFS zvols, but in a distributed, shared-storage manner.

All the components are designed to be run on top of Debian GNU/Linux, specifically Debian 10.X "Buster", with the SystemD system service manager. This OS provides a stable base to run the various other subsystems while remaining truly Free Software, while SystemD provides functionality such as automatic daemon restarting and complex startup/shutdown ordering.

## Cluster Architecture

A PVC cluster is based around "nodes", which are physical servers on which the various daemons, storage, networks, and virtual machines run. Each node is self-contained and is able to perform any and all cluster functions if needed; there is no segmentation of function between different types of physical hosts.

A limited number of nodes, called "coordinators", are statically configured to provide additional services for the cluster. For instance, all databases, FRRouting instances, and Ceph management daemons run only on the set of cluster coordinators. At cluster bootstrap, 1 (testing-only), 3 (small clusters), or 5 (large clusters) nodes may be chosen as the coordinators. Other nodes can then be added as "hypervisor" nodes, which then provide only block device (storage) and VM (compute) functionality by connecting to the set of coordinators. This limits the scaling problem of the databases while ensuring there is still maximum redundancy and resiliency for the core cluster services. Which nodes are designated as coordinators can be changed should the administrator so desire, simply by installing the required software on additional nodes, though this is not recommended (the Ceph system in particular is cumbersome to reconfigure).

During runtime, one coordinator is elected the "primary" for the cluster. This designation can shift dynamically in response to cluster events, or be manually migrated by an administrator. The coordinator takes on a number of roles for which only one host may be active at once, for instance to provide DHCP services to managed client networks or to interface with the API.

Nodes are networked together via a set of statically-configured networks. At a minimum, 2 discrete networks are required, with an optional 3rd. The "upstream" network is the primary network for the nodes, and provides functions such as upstream Internet access, routing to and from the cluster nodes, and management via the API; it may be either a firewalled public or NAT'd RFC1918 network, but should never be exposed directly to the Internet. The "cluster" network provides inter-node communication for managed client network traffic (VXLANs), cross-node routing, VM migration and failover, and database replication and access. Finally, though optionally collapsed with the "cluster" network, the "storage" network provides a dedicated logical or physical link between the nodes for storage traffic, including VM block device storage traffic, inter-OSD replication traffic, and Ceph heartbeat traffic, thus allowing it to be completely isolated from the other networks for maximum performance. With each network is a single "floating" IP address which follows the primary coordinator. Once configured, the cluster is then able to create additional networks of two kinds, "bridged" traditional vLANs and "managed" VXLANs, to provide network access to VMs.

Further information about the general cluster architecture, including important considerations for node specifications/sizing and network configuration, can be found at the [cluster architecture page](/cluster-architecture).

## Clients

### API Client

The API client is a Flask-based RESTful API and is the core interface to PVC. By default the API will run on the primary coordinator, listening on TCP port 7370 on the "upstream" network floating IP address. All other clients communicate with this API to perform actions against the cluster. The API features basic authentication using UUID-based API keys to prevent unauthorized access, and can optionally be configured with full TLS encryption to provide integrity and confidentiality across public networks.

The API generally accepts all requests as HTTP form requests following standard RESTful guidelines, supporting arguments in the URI string or in the message body. The API returns JSON response bodies to all requests consisting either of the information requested, or a `{ "message": "text" }` construct to pass informational status messages back to the client.

The API client manual can be found at the [API manual page](/manuals/api), and the full API documentation can be found at the [API reference page](/manuals/api-reference.html).

### Direct Bindings

The API client uses a dedicated set of Python libraries, packaged as the `pvc-daemon-common` Debian package, to communicate with the cluster. It is thus possible to build custom Python clients that directly interface with the PVC cluster, without having to get "into the weeds" of the Zookeeper or PostgreSQL databases.

### CLI Client

The CLI client is a Python Click application, which provides a convenient CLI interface to the API client. It supports connecting to multiple clusters from a single instance, with or without authentication and over both HTTP or HTTPS, including a special "local" cluster if the client determines that an API configuration exists on the local host. Information about the configured clusters is stored in a local JSON document, and a default cluster can be set with an environment variable.

The CLI client is self-documenting using the `-h`/`--help` arguments thoughout, easing the administrator learning curve and providing easy access to command details. A short manual can also be found at the [CLI manual page](/manuals/cli).

## Deployment

The overall management, deployment, bootstrapping, and configuring of nodes is accomplished via a set of Ansible roles and playbooks, found in the [`pvc-ansible` repository](https://github.com/parallelvirtualcluster/pvc-ansible), and nodes are installed via a custom installer ISO generated by the [`pvc-installer` repository](https://github.com/parallelvirtualcluster/pvc-installer). Once the cluster is set up, nodes can be added, replaced, updated, or reconfigured using this Ansible framework.

The Ansible configuration and architecture manual can be found at the [Ansible manual page](/manuals/ansible).

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

I built PVC for my homelab first, found a perfect usecase with my employer, and think it might be useful to you too.

#### Is 3 hypervisors really the minimum?

For a redundant cluster, yes. PVC requires a majority quorum for proper operation at various levels, and the smallest possible majority quorum is 2-of-3; thus 3 nodes is the safe minimum. That said, you can run PVC on a single node for testing/lab purposes without host-level reundancy, should you wish to do so, and it might also be possible to run 2 "main" systems with a 3rd "quorum observer" hosting only the management tools but no VMs, however this is not officially supported.

### Feature Questions

#### Does PVC support containers (Docker/Kubernetes/LXC/etc.)?

No, not directly. PVC supports only KVM VMs. To run containers, you would need to run a VM which then runs your containers. For instance PVC makes an excellent underlying layer for a virtual Kubernetes cluster, instead of bare hardware.

#### Does PVC have a WebUI?

Not yet. Right now, PVC management is done exclusively with the CLI interface to the API. A WebUI can and likely will be built in the future, but I'm not a frontend developer and I do not consider this a personal priority. As of late 2020 the API is generally stable, so I would welcome 3rd party assistance here.

### Storage Questions

#### Can I use RAID-5/RAID-6 with PVC?

The short answer is no. The long answer is: Ceph, the storage backend used by PVC, does support "erasure coded" pools which implement a RAID-5-like (striped with distributed parity) functionality, but PVC does not support this for several reasons, mostly related to ease of management and performance. If you use PVC, you must accept at the very least a 2x storage penalty, and for true multi-node safety and resiliency, a 3x storage penalty for VM storage. This is a trade-off of the architecture and should be taken into account when sizing storage in nodes.

#### Can I use spinning HDDs with PVC?

You can, but you won't like the results. SSDs, and specifically datacentre-grade SSDs for resiliency, are required to obtain any sort of reasonable performance when running multiple VMs. The higher-performance the drives, the faster the storage.

#### What network speed does PVC require?

For optimal performance, nodes should use at least 10-Gigabit Ethernet network interfaces wherever possible, and on large clusters a dedicated 10-Gigabit "storage" network, separate from the "upstream"/"cluster" networks, is strongly recommended. The storage system performance, especially for writes, is more heavily bottlenecked by the network speed than the actual storage device speed when speaking of high-performance disks. 1-Gigabit Ethernet will be sufficient for some usecases and is sufficient for the non-storage networks (VM traffic notwithstanding), but storage performance will become severly limited as the cluster grows. Even slower network speeds (e.g. 100-Megabit) are not sufficient for PVC to operate properly except in very limited testing scenarios.

#### What Ceph version does PVC use?

PVC requires Ceph 14.x (Nautilus). The official PVC repository at https://repo.bonifacelabs.ca includes Ceph 14.2.x (updated regularly), since Debian Buster by default includes only 12.x (Luminous).

## About The Author

PVC is written by [Joshua](https://www.boniface.me) [M.](https://bonifacelabs.ca) [Boniface](https://github.com/joshuaboniface). A Linux system administrator by trade, Joshua is always looking for the best solutions to his user's problems, be they developers or end users. PVC grew out of his frustration with the various FOSS virtualization tools, as well as and specifically, the constant failures of Pacemaker/Corosync to gracefully manage a virtualization cluster. He started work on PVC at the end of May 2018 as a simple alternative to a Corosync/Pacemaker-managed virtualization cluster, and has been growing the feature set and stability of the system ever since.

