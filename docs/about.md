# About the Parallel Virtual Cluster suite

## Project Goals and Philosophy

Server management and system administration have changed significantly in the last decade. Computing as a resource is here, and software-defined is the norm. Gone are the days of pet servers, of tweaking configuration files by hand, and of painstakingly installing from ISO images in 52x CD-ROM drives. This is a brave new world.

As part of this trend, the rise of IaaS (Infrastructure as a Service) has created an entirely new way for administrators and, increasingly, developers, to interact with servers. They need to be able to provision virtual machines easily and quickly, to ensure those virtual machines are reliable and consistent, and to avoid downtime wherever possible.

However, the state of the Free Software, virtual management ecosystem at the start of 2020 is quite disappointing. On the one hand are the giant, IaaS products like OpenStack and CloudStack. These are massive pieces of software, featuring dozens of interlocking parts, designed for massive clusters and public cloud deployments. They're great for a "hyperscale" provider, a large-scale SaaS/IaaS provider, or an enterprise. But they're not designed for small teams or small clusters. On the other hand, tools like Proxmox, oVirt, and even good old fashioned shell scripts are barely scalable, are showing their age, and have become increasingly unwieldy for advanced use-cases - great for one server, not so great for 9 in a highly-available cluster. Not to mention the constant attempts to monetize by throwing features behind Enterprise subscriptions. In short, there is a massive gap between the old-style, pet-based virtualization and the modern, large-scale, IaaS-type virtualization. This is not to mention the well-entrenched, proprietary solutions like VMWare and Nutanix which provide many of the features a small cluster administrator requires, but can be prohibitively expensive for small organizations.

PVC aims to bridge these gaps. As a Python 3-based, fully-Free Software, scalable, and redundant private "cloud" that isn't afraid to say it's for small clusters, PVC is able to provide the simple, easy-to-use, small cluster you need today, with minimal administrator work, while being able to scale as your system grows, supporting hundreds or thousands of VMs across dozens of nodes. High availability is baked right into the core software at every layer, giving you piece of mind about your cluster, and ensuring that your systems keep running no matter what happens. And the interface couldn't be easier - a straightforward Click-based CLI and a Flask-based HTTP API provide access to the cluster for you to manage, either directly or though scripts or WebUIs. And since everything is Free Software, you can always inspect it, customize it to your use-case, add features, and contribute back to the community if you so choose.

PVC provides all the features you'd expect of a "cloud" system - easy management of VMs, including live migration between nodes for maximum uptime; virtual networking support using either vLANs or EVPN-based VXLAN; shared, redundant, object-based storage using Ceph, and a Python function library and convenient API interface for building your own interfaces. It is able to do this without being excessively complex, and without making sacrifices for legacy ideas.

If you need to run virtual machines, and don't have the time to learn the Stacks, the patience to deal with the old-style FOSS tools, or the money to spend on proprietary solutions, PVC might be just what you're looking for.

## Cluster Architecture

A PVC cluster is based around "nodes", which are physical servers on which the various daemons, storage, networks, and virtual machines run. Each node is self-contained; it is able to perform any and all cluster functions if needed, and there is no segmentation of function between different types of physical hosts.

A limited number of nodes, called "coordinators", are statically configured to provide additional services for the cluster. All databases for instance run on the coordinators, but not other nodes. This prevents any issues with scaling database clusters across dozens of hosts, while still retaining maximum redundancy. In a standard configuration, 3 or 5 nodes are designated as coordinators, and additional nodes connect to the coordinators for database access where required. For quorum purposes, there should always be an odd number of coordinators, and exceeding 5 is likely not required even for large clusters. PVC also supports a single node cluster format for extremely small clusters, homelabs, or testing where redundancy is not required.

The primary database for PVC is Zookeeper, a highly-available key-value store designed with consistency in mind. Each node connects to the Zookeeper cluster running on the coordinators to send and receive data from the rest of the cluster. The API client (and Python function library) interface with this Zookeeper cluster directly to configure and obtain state about the various objects in the cluster. This database is the central authority for all nodes.

Nodes are networked together via at least 3 different networks, set during bootstrap. The first is the "upstream" network, which provides upstream access for the nodes, for instance Internet connectivity, sending routes to client networks to upstream routers, etc. This should usually be a private/firewalled network to prevent unauthorized access to the cluster. The second is the "cluster" network, which is a private RFC1918 network that is unrouted and that nodes use to communicate between one another for Zookeeper access, Libvirt migrations, EVPN VXLAN tunnels, etc. The third is the "storage" network, which is used by the Ceph storage cluster for inter-OSD communication, allowing it to be separate from the main cluster network for maximum performance flexibility.

Further information about the general cluster architecture can be found at the [cluster architecture page](/architecture/cluster).

## Node Architecture

Within each node, the PVC daemon is a single Python 3 program which handles all node functionality, including networking, starting cluster services, managing creation/removal of VMs, networks, and storage, and providing utilization statistics and information to the cluster.

The daemon uses an object-oriented approach, with most cluster objects being represented by class objects of a specific type. Each node has a full view of all cluster objects and can interact with them based on events from the cluster as needed.

Further information about the node daemon manual can be found at the [daemon manual page](/manuals/daemon).

## Client Architecture

### API client

The API client is the core interface to PVC. It is a Flask RESTful API interface capable of performing all functions, and by default runs on the primary coordinator listening on port 7370 at the upstream floating IP address. Other clients, such as the CLI client, connect to the API to perform actions against the cluster. The API features a basic key-based authentication mechanism to prevent unauthorized access to the cluster if desired, and can also provide TLS-encrypted access for maximum security over public networks.

The API accepts all requests as HTTP form requests, supporting arguments both in the URI string as well as in the POST/PUT body. The API returns JSON response bodies to all requests.

The API client manual can be found at the [API manual page](/manuals/api), and the [API documentation page](/manuals/api-reference.html).

### Direct bindings

The API client uses a dedicated, independent set of functions to perform the actual communication with the cluster, which is packaged separately as the `pvc-client-common` package. These functions can be used directly by 3rd-party Python interfaces for PVC if desired.

### CLI client

The CLI client interface is a Click application, which provides a convenient CLI interface to the API client. It supports connecting to multiple clusters, over both HTTP and HTTPS and with authentication, including a special "local" cluster if the client determines that an `/etc/pvc/pvcapid.yaml` configuration exists on the host.

The CLI client is self-documenting using the `-h`/`--help` arguments, though a short manual can be found at the [CLI manual page](/manuals/cli).

## Deployment architecture

The overall management, deployment, bootstrapping, and configuring of nodes is accomplished via a set of Ansible roles, found in the [`pvc-ansible` repository](https://github.com/parallelvirtualcluster/pvc-ansible), and nodes are installed via a custom installer ISO generated by the [`pvc-installer` repository](https://github.com/parallelvirtualcluster/pvc-installer). Once the cluster is set up, nodes can be added, replaced, or updated using this Ansible framework.

The Ansible configuration and architecture manual can be found at the [Ansible manual page](/manuals/ansible).

## About the author

PVC is written by [Joshua](https://www.boniface.me) [M.](https://bonifacelabs.ca) [Boniface](https://github.com/joshuaboniface). A Linux system administrator by trade, Joshua is always looking for the best solutions to his user's problems, be they developers or end users. PVC grew out of his frustration with the various FOSS virtualization tools, as well as and specifically, the constant failures of Pacemaker/Corosync to gracefully manage a virtualization cluster. He started work on PVC at the end of May 2018 as a simple alternative to a Corosync/Pacemaker-managed virtualization cluster, and has been growing the feature set in starts and stops ever since.
