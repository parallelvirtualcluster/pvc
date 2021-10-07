# PVC Cluster Architecture considerations

- [PVC Cluster Architecture considerations](#pvc-cluster-architecture-considerations)
  * [Node Specification](#node-specification)
    - [n-1 Redundancy](#n-1-redundancy)
    - [CPU](#cpu)
    - [Memory](#memory)
    - [Disk](#disk)
    - [Network](#network)
  * [PVC architecture](#pvc-architecture)
    - [Operating System](#operating-system)
    - [Ceph Storage Layout](#ceph-storage-layout)
    - [Networks](#networks)
      + [System Networks](#system-networks)
      + [Client Networks](#client-networks)
    - [Fencing and Recovery](#fencing-and-recovery)
  * [Advanced Layouts](#advanced-layouts)
    - [Coordinators versus Hypervisors](#coordinators-versus-hypervisors)
    - [Georedundancy](#georedundancy)
  * [Example System Diagrams](#example-system-diagrams)
    - [Small 3-node cluster](#small-3-node-cluster)
    - [Large 8-node cluster](#large-8-node-cluster)

This document contains considerations the administrator should make when preparing for and building a PVC cluster. It is important that prospective PVC administrators read this document *thoroughly* before deploying a cluster to ensure they understand the requirements, caveats, and important details about how PVC operates.

## Node Specification

PVC nodes, especially coordinator nodes, run a significant number of software applications in addition to the virtual machines (VMs). It is therefore extremely important to size the systems correctly for the expected workload while planning both for redundancy and future capacity. In general, taller nodes are better for performance, providing a more powerful cluster on fewer physical machines, though each workload may be different in this regard.

The following table provides recommended minimum specifications for each component of the cluster nodes. In general, these minimums are the lowest possible for a production-quality cluster that would provide decent performance for up to about a dozen virtual machines. Of course, further upward scaling is recommended and the specific computational and storage needs of the VM workloads should be taken into account.

| Resource | Recommended Minimum |
| -------- | --------------------|
| CPU generation | Intel Sandy Bridge (2011) *or* AMD Naples (2017) |
| CPU cores per node | 8 @ 2.0GHz |
| RAM per node | 32GB |
| System disk (SSD/HDD/USB/SD/eMMC) | 2x 100GB RAID-1 |
| Data disk (SSD only) | 1x 400GB |
| Network interfaces | 2x 10Gbps (LACP LAG) |
| Remote IPMI-over-IP | Available and connected |
| Total CPU cores (healthy) | 24 |
| Total CPU cores (n-1) | 16 |
| Total RAM (healthy) | 96GB |
| Total RAM (n-1) | 64GB |
| Total disk space | 400GB |

For testing, or low-budget homelab applications, some aspects can be further tuned down, however consider the following sections carefully.

### n-1 Redundancy

Care should be taken to examine the "healthy" versus "n-1" total resource availability. Under normal operation, PVC will use all available resources and distribute VMs across all cluster nodes. However, during single-node failure or maintenance conditions, all VMs will be required to run on the remaining hypervisors. Thus, care should be taken during planning to ensure there is sufficient resources for the expected workload of the cluster.

The general values for default resource availability of a 3-node cluster for n-1 availability (1 node offline) are:

  * 1/3 of the total data disk space (3 copies of all data, distributed across all 3 nodes)
  * 2/3 of the total RAM
  * 2/3 of the total CPU cores

For memory provisioning of VMs, PVC will warn the administrator, via a Degraded cluster state, if the "n-1" RAM quantity is exceeded by the total maximum allocation of all running VMs. If nodes are of mismatched sizes, the "n-1" RAM quantity is calculated by removing (one of) the largest node in the cluster and adding the remaining nodes' RAM counts together.

### CPU

CPU resources are a very important part of the overall performance of a PVC cluster. Numerous aspects of the system require high-performance CPU cores, including the VM workloads themselves, the PVC databases, and, especially, the Ceph storage subsystem.

As a general rule, more cores, and faster cores, are always better, and real cores are preferable to SMT virtual cores in most cases.

#### SMT

SMT in particular can be a contentious subject, and performance can vary wildly for different workloads; thus, while they are useful, in terms of performance calculations they should always be considered as an afterthought or "bonus" to assist with many VMs contending for resources, and base specifications should be done based on the number of real CPU cores instead.

#### CPU core counts

The following should be considered recommended minimums for CPU core allocations:

  * PVC system daemons, including Zookeeper and PostgreSQL databases: 2 CPU cores
  * Ceph Monitor and Manager processes: 1 CPU core
  * Ceph OSD processes: 2 CPU cores *per OSD disk*
  * Virtual Machines: 1 CPU core per vCPU in the largest spec'd VM (e.g. 12 vCPUs in a VM = 12 cores here)

To provide an example, consider a cluster that would run 2 OSD disks per node, and want to run several VMs, the largest of which would require 12 vCPUs:

  * PVC system: 2 cores
  * Ceph Mon/Mgr: 1 core
  * Ceph OSDs: 2 * 2 = 4 cores
  * VMs: 12 cores

This gives a total of 19 cores, and thus a 20+ core CPU would be recommended.

Additional CPU cores, as previously mentioned, are always better. For instance, though 2 is the recommended minimum per OSD disk, better performance can be achieved if there are 4 cores available per OSD instead. This trade-off depends heavily on the required workload and VM specifications and should be carefully considered.

#### CPU performance

While CPU frequency is not a tell-all or even particularly useful metric across generations or manufacturers, within a specific generation and manufacturer, faster CPUs will almost always improve performance across the board, especially when considering the Ceph storage subsystem. If a 2.0GHz and a 2.6GHz CPU of the same core count are both available, the 2.6GHz one is almost always the better choice from a pure performance perspective. 

### Memory

Memory is extremely important to PVC clusters, and like CPU resources a not-insignificant amount of memory is required for the baseline cluster before VMs are considered.

#### Memory allocations

The following should be considered recommended minimums for memory allocations:

  * PVC daemons: 1 GB
  * Zookeeper database: 1 GB
  * PostgreSQL database: 1 GB
  * Ceph Monitor and Manager processes: 1 GB
  * Ceph OSD processes: 1 GB *per OSD disk*

All additional memory can be consumed by virtual machines.

To provide an example, in the same cluster as mentioned in the CPU section:

 * PVC system: 1 GB
 * Zookeeper: 1 GB
 * PostgreSQL: 1 GB
 * Ceph Mon/Mgr: 1 GB
 * Ceph OSDs: 2 * 1 GB = 2 GB

This gives a total of 6 GB of memory for the base system, with VMs requiring additional memory.

#### VM Memory Overprovisioning

An important consideration is that the KVM hypervisor used by PVC will only allocate guest memory *as required by the guest*, but PVC tracks memory allocation based on the allocated maximum. Thus, for example, a VM may be allocated 8192 MB of memory in PVC, and thus the PVC system considers 8 GB "allocated" and "provisioned" to this VM, but if the actual guest is only using 500 MB of that memory, the actual memory usage on the hypervisor node will be 500 MB for that VM. Thus it is possible for "all" memory to be allocated on a node but there still be many GB of "free" memory. This is an intentional design decision to avoid excessive overprovisioning of memory and thus situations where non-VM processes become memory starved, as the PVC system itself does *not* track the usage by the aforementioned processes.

#### Memory Performance

Given the recommended CPU requirements, all PVC hypervisors should contain at least DDR3 memory, which is sufficiently performant for all tasks. Memory latency and performance, however, can become important especially in large NUMA systems, and especially with regards to the Ceph storage subsystem. Care should be taken to optimize the memory layout in nodes, for instance making use of all available memory channels in the CPU architecture and preferring 1 DIMM-per-channel (DPC) over 2 DPC.

#### Ceph OSD memory utilization

While the recommended *minimum* is 1 GB per OSD process, in reality, Ceph can allocate between 4 and 6 GB of memory per OSD process, especially for caching metadata and other frequently-used data. Thus, for maximum performance, 4 GB instead of 1 GB should be allocated per-OSD.

#### Memory limit tuning

The PVC Ansible deployment system allows the administrator to specify limits on some aspects of the aforementioned memory requirements, for instance limiting Zookeeper or Ceph OSD processes to lower amounts of memory. This is not recommended except in situations where memory is extremely constrained; in such situations adding additional memory to nodes is always preferable. For details and examples please see the Ansible variable files.

### Disk

#### System Disks

The performance of system disks is of critical importance in the PVC cluster. At least 32GB of space are required, and at least 100GB is recommended to ensure optimal performance. The system disks should be fast SAS HDDs, SSDs, eMMC flash, class-10 SD, or other flash-based mediums, and RAID-1 is critical for reliability purposes, especially for more wear- or failure-sensitive media types.

PVC will store the various databases on these disks, so overall performance can affect the responsiveness of the system. However note that no VM data is ever stored on system disks; this is provided exclusively by the Ceph data disks (OSDs).

#### Ceph OSD disks

All VM block devices are stored on Ceph OSD data disks. The default pool configuration of the Ceph storage subsystem uses a `copies=3` layout with a `host`-level failure domain; thus, in a 3-node cluster, each block of data is stored 3 times, once per node. This ensures that 2 copies of each piece of data are available even if a host is down, at the cost of 1/3 of the total overall storage space. Other configurations are possible, but this is the minimum recommended.

The performance of VM disks will be dictated almost exclusively by the performance of these disks in combination with the CPU resources of the system as discussed previously. Very fast, robust, and resilient storage is highly recommended for OSD disks to maximize performance and longevity. High-performance SATA, SAS, or NVMe SSDs are recommended for this task, sized according to the expected workload. Spinning disks (HDDs) are *not* recommended for this purpose, and their very low random performance will significantly limit the overall storage performance of the cluster.

Initially, it is optimal if all nodes contain the same number and same size of OSD disks, to ensure even distribution of the data across all disks and thus maximize performance. PVC supports adding additional OSDs at a later time, however the administrator should be cautious to always add new disks in parallel on all nodes at the same time, as otherwise the replication ratio will prevent the new space from being utilized. Thus, in a 3-node cluster, disks must be added 3-at-a-time to all 3 nodes, and these disks must be identically sized, in order to increase the total usable storage space by the value of one of these disks.

In addition to the primary data disks, PVC also supports the offloading of the Ceph BlueStore OSD database and WAL functions of the OSDs onto a separate OSD database volume group on a dedicated storage device. In the normal use-case, this would be an extremely fast and endurant Intel Optane or similar extremely-performant NVMe SSD which is significantly faster than the primary data SSDs. This will help accelerate random write I/Os and metadata lookups, especially when using lower-performance SATA or SAS SSDs. Generally speaking this volume should be large enough to support 5% of the capacity of all OSDs on a node, with some room for future expansion. Only one such device and volume group is supported at this time.

### Network

Because PVC makes extensive use of cross-node communications, high-throughput and low-latency networking is critical. At a minimum, 10-gigabit networking is recommended to ensure suitable throughput for the storage subsystem as well as for VM traffic. Higher-speed networking can also improve performance, especially when using extremely fast Ceph OSD disks.

A minimum of 2 network interfaces is recommended. These should then be combined into a logical aggregate (LAG) using 802.3ad (LACP) to provide redundant links and a boost in available bandwidth. Additional NICs can also be used to separate discrete parts of the networking stack, which will be discussed below.

#### Remote IPMI-over-IP

IPMI provides a method to manage the physical chassis' of nodes from outside of their operating system. Common implementations include Dell iDRAC, HP iLO, Cisco CIMC, and others.

PVC nodes in production deployments should always feature an IPMI-over-IP interface of some kind, which is then reachable either in, or via, the Upstream system network (see [System Networks](#system-networks)). This requirement is discussed in more detail during the [Fencing and Recovery](#fencing-and-recovery) section below.

## PVC Architecture

### Operating System

As an underlying OS, only Debian GNU/Linux 10.x "Buster" or 11.x "Bullseye" are supported by PVC. This is the operating system installed by the PVC [node installer](https://github.com/parallelvirtualcluster/pvc-installer) and expected by the PVC [Ansible configuration system](https://github.com/parallelvirtualcluster/pvc-ansible). Ubuntu or other Debian-derived distributions may work, but are not officially supported. PVC also makes use of a custom repository to provide the PVC software and (for Debian Buster) an updated version of Ceph beyond what is available in the base operating system, and this is only compatible officially with Debian 10 or 11. PVC will generally be upgraded regularly to support new Debian versions. As a rule, using the current versions of the official node installer and Ansible repository is the preferred and only supported method for deploying PVC.

Currently, only the `amd64` (Intel 64 or AMD64) architecture is officially supported by PVC. Given the cross-platform nature of Python and the various software components in Debian, it may work on `armhf` or `arm64` systems as well, however this has not been tested by the author and is not officially supported at this time.

### Ceph Storage Layout

PVC makes use of Ceph, a distributed, replicated, self-healing, and self-managing storage system to provide shared VM storage. While a PVC administrator is not required to understand Ceph for day-to-day administration, and PVC provides interfaces to most of the common storage functions required to operate a cluster, at least some knowledge of Ceph is advisable.

The Ceph subsystem of PVC creates a "hyperconverged" cluster whereby storage and VM hypervisor functions are collocated onto the same physical servers; PVC does not differentiate between "storage" and "compute" nodes, and while storage support can be disabled and an external Ceph cluster used, this is not recommended. The performance of the storage must be taken into account when sizing the nodes as mentioned above.

Ceph on PVC is laid out similar to the other daemons. The Ceph Monitor and Manager functions are delegated to the Coordinators over the storage network, with all nodes connecting to these hosts to obtain the CRUSH maps and select OSD disks. OSDs are then distributed on all hosts, potentially including non-coordinator hypervisors if desired, and communicate with clients and each other over the storage network.

Disks must be balanced across all storage-containing nodes. For instance, adding 1 disk to 1 node is not sufficient to increase storage space; 1 disk must be added to all storage-containing nodes, based on the configured replication scheme of the various pools (see below), at the same time for the available space to increase. Ideally, disk sizes should also be identical across all storage disks, though the weight of each disk can be configured when added to the cluster. Generally speaking, fewer larger disks are preferable to many smaller disks to minimize storage resource utilization, however slightly more storage performance can be gained from using many small disks, if the other cluster hardware, and specifically CPUs, are performant enough. The administrator should therefore always aim to choose the biggest disks they can and grow by adding more identical disks as space or performance needs grow.

PVC Ceph pools make use of the replication mechanism of Ceph to store multiple copies of each object, thus ensuring that data is always available even when a host is unavailable. Only "replica"-based Ceph redundancy is supported by PVC; erasure coded pools are not supported due to major performance impacts related to rewrites and random I/O as well as management overhead.

The default replication level for a new pool is `copies=3, mincopies=2`. This will store 3 copies of each object, with a host-level failure domain, and will allow I/O as long as 2 copies are available. Thus, in a cluster of any size, all data is fully available even if a single host becomes unavailable. It will however use 3x the space for each piece of data stored, which must be considered when sizing the disk space for the cluster: a pool in this configuration, running on 3 nodes each with a single 400GB disk, will effectively have 400GB of total space available for use. As mentioned above, new disks must also be added in groups across nodes equal to the total number of `copies` to ensure new space is usable; for instance in a `copies=3` scheme, at least 3 disks must thus be added to different hosts at the same time for the available space to grow.

Non-default values can also be set at pool creation time. For instance, one could create a `copies=3, mincopies=1` pool, which would allow I/O with two hosts down, but leaves the cluster susceptible to a write hole should a disk fail in this state; this configuration is not recommended in most situations. Alternatively, for additional resilience, one could create a `copies=4, mincopies=2` pool, which would also allow 2 hosts to fail, without a write hole, but would consume 4x the space for each piece of data stored and require new disks to be added in groups of 4 instead. Practically any combination of values is possible, however these 3 are the most relevant for most use-cases, and for most, especially small, clusters, the default is sufficient to provide solid redundancy and guard against host failures until the administrator can respond.

Replication levels cannot be changed within PVC once a pool is created, however they can be changed via manual Ceph commands on a coordinator should the administrator require this, though discussion of this process is outside of the scope of this documentation. The administrator should carefully consider sizing, failure domains, and performance when first selecting storage devices and creating pools, to ensure the right level of resiliency versus data usage for their use-case and planned cluster size.

### Networks

At a minimum, a production PVC cluster should use at least two 10Gbps Ethernet interfaces, connected in an LACP or active-backup bond on one or more switches. On top of this bond, the various cluster networks should be configured as 802.3q vLANs. PVC is be able to support configurations without bonding or 802.1q vLAN support, using multiple physical interfaces and no bridged client networks, but this is strongly discouraged due to the added complexity this introduces; the switches chosen for the cluster should include these requirements as a minimum.

More advanced physical network layouts are also possible. For instance, one could have two isolated networks. On the first network, each node has two 10Gbps Ethernet interfaces, which are combined in a bond across two redundant switch fabrics and that handle the upstream and cluster networks. On the second network, each node has an additional two 10Gbps, which are also combined in a bond across the redundant switch fabrics and handle the storage network. This configuration could support up to 10Gbps of aggregate client traffic while also supporting 10Gbps of aggregate storage traffic. Even more complex network configurations are possible if the cluster requires such performance. See the [Example System Diagrams](#example-system-diagrams) section for some basic topology examples.

Only Ethernet networks are supported by PVC. More exotic interconnects such as Infiniband are not supported by default, and must be manually set up with Ethernet (e.g. EoIB) layers on top to be usable with PVC.

Lower-speed networks (e.g. 1Gbps or 100Mbps) should not be used as these will severely bottleneck the performance of the storage subsystem. In an advanced split layout, it may be acceptable to use 1Gbps interfaces for VM guest networks, however the core system networks should always be a minimum of 10Gbps.

PVC manages the IP addressing of all nodes itself and creates the required addresses during node daemon startup; thus, the on-boot network configuration of each interface should be set to "manual" with no IP addresses configured. This can be ignored safely, however, and the addresses specified manually in the networking configurations. PVC nodes use a split (`/etc/network/interfaces.d/<iface>`) network configuration model.

### System Networks

#### Upstream: Connecting the nodes to the wider world

The upstream network functions as the main upstream for the cluster nodes, providing Internet access and a way to route managed client network traffic out of the cluster. In most deployments, this should be an RFC1918 private subnet with an upstream router which can perform NAT translation and firewalling as required, both for the cluster nodes themselves, and also for any RFC1918 managed client networks.

The floating IP address in the cluster network can be used as a single point of communication with the active primary node, for instance to access the DNS aggregator instance or the management API. PVC provides only limited access control mechanisms to the API interface, so the upstream network should always be protected by a firewall; running PVC directly accessible on the Internet is strongly discouraged and may post a serious security risk, and all access should be restricted to the smallest possible set of remote systems.

Nodes in this network are generally assigned static IP addresses which are configured at node install time and in the [Ansible deployment configuration](/manuals/ansible).

The upstream router should be able to handle static routes to the PVC cluster, or form a BGP neighbour relationship with the coordinator nodes and/or floating IP address to learn routes to the managed client networks.

The upstream network should generally be large enough to contain:

0. The upstream router(s)
0. The nodes themselves
0. In most deployments, the node IPMI management interfaces.

For example, for a 3+ node cluster, up to about 90 nodes, the following configuration might be used:

| Description | Address |
|-------------|---------|
| Upstream network | 10.0.0.0/24 |
| Router VIP address | 10.0.0.1 |
| Router 1 address | 10.0.0.2 |
| Router 2 address | 10.0.0.3 |
| PVC floating address | 10.0.0.10 |
| node1 | 10.0.0.11 |
| node2 | 10.0.0.12 |
| etc.  | etc. |
| node1-ipmi | 10.0.0.111 |
| node2-ipmi | 10.0.0.112 |
| etc.  | etc. |

For even larger clusters, a `/23` or even larger network may be used.

#### Cluster: Connecting the nodes with each other

The cluster network is an unrouted private network used by the PVC nodes to communicate with each other for database access and Libvirt migrations. It is also used as the underlying interface for the BGP EVPN VXLAN interfaces used by managed client networks.

The floating IP address in the cluster network can be used as a single point of communication with the active primary node.

Nodes in this network are generally assigned IPs automatically based on their node number (e.g. node1 at `.1`, node2 at `.2`, etc.). The network should be large enough to include all nodes sequentially.

Generally the cluster network should be completely separate from the upstream network, either a separate physical interface (or set of bonded interfaces) or a dedicated vLAN on an underlying physical device, but they can be collocated if required.

#### Storage: Connecting Ceph daemons with each other and with OSDs

The storage network is an unrouted private network used by the PVC node storage OSDs to communicated with each other, for Ceph management functionality, and for QEMU-to-Ceph disk access, without using the main cluster network and introducing potentially large amounts of traffic there.

The floating IP address in the storage network can be used as a single point of communication with the active primary node, though this will generally be of little use.

Nodes in this network are generally assigned IPs automatically based on their node number (e.g. node1 at `.1`, node2 at `.2`, etc.). The network should be large enough to include all nodes sequentially.

The administrator may choose to collocate the storage network on the same physical interface as the cluster network, or on a separate physical interface. This should be decided based on the size of the cluster and the perceived ratios of client network versus storage traffic. In large (>3 node) or storage-intensive clusters, this network should generally be a separate set of fast physical interfaces, separate from both the upstream and cluster networks, in order to maximize and isolate the storage bandwidth. If the administrator does choose to collocate these networks, they may also share the same IP address, thus eliminating any distinction between the Cluster and Storage networks. The PVC software handles this natively when the Cluster and Storage IPs of a node are identical.

### Client Networks

#### Bridged (unmanaged) Client Networks

The first type of client network is the unmanaged bridged network. These networks have a separate vLAN on the device underlying the other networks, which is created when the network is configured. VMs are then bridged into this vLAN.

With this client network type, PVC does no management of the network. This is left entirely to the administrator. It requires switch support and the configuration of the vLANs on the switchports of each node's physical interfaces before enabling the network.

Generally, the same physical network interface will underlay both the cluster networks as well as bridged client networks. PVC does however support specifying a separate physical device for bridged client networks, for instance to separate these networks onto a different physical interface from the main cluster networks.

#### VXLAN (managed) Client Networks

The second type of client network is the managed VXLAN network. These networks make use of BGP EVPN, managed by route reflection on the coordinators, to create virtual layer 2 Ethernet tunnels between all nodes in the cluster. VXLANs are then run on top of these virtual layer 2 tunnels, with the active primary PVC node providing routing, DHCP, and DNS functionality to the network via a single IP address.

With this client network type, PVC is in full control of the network. No vLAN configuration is required on the switchports of each node's physical interfaces, as the virtual layer 2 tunnel travels over the cluster layer 3 network. All client network traffic destined for outside the network will exit via the upstream network interface of the active primary coordinator node.

NOTE: These networks may introduce a bottleneck and tromboning if there is a large amount of external and/or inter-network traffic on the cluster. The administrator should consider this carefully when deciding whether to use managed or bridged networks and properly evaluate the inter-network traffic requirements.

#### SR-IOV Client Networks

The third type of client network is the SR-IOV network. SR-IOV (Single-Root I/O Virtualization) is a technique and feature enabled on modern high-performance NICs (for instance, those from Intel or nVidia) which allows a single physical Ethernet port (a "PF" in SR-IOV terminology) to be split, at a hardware level, into multiple virtual Ethernet ports ("VF"s), which can then be managed separately. Starting with version 0.9.21, PVC support SR-IOV PF and VF configuration at the node level, and these VFs can be passed into VMs in two ways.

SR-IOV's main benefit is to offload bridging and network functions from the hypervisor layer, and direct them onto the hardware itself. This can increase network throughput in some situations, as well as provide near-complete isolation of guest networks from the hypervisors (in contrast with bridges which *can* expose client traffic to the hypervisors, and VXLANs which *do* expose client traffic to the hypervisors). For instance, a VF can have a vLAN specified, and the tagging/untagging of packets is then carried out at the hardware layer.

There are however caveats to working with SR-IOV. At the most basic level, the biggest difference with SR-IOV compared to the other two network types is that SR-IOV must be configured on a per-node basis. That is, each node must have SR-IOV explicitly enabled, it's specific PF devices defined, and a set of VFs created at PVC startup. Generally, with identical PVC nodes, this will not be a problem but is something to consider, especially if the servers are mismatched in any way. It is thus also possible to set some nodes with SR-IOV functionality, and others without, though care must be taken in this situation to set node limits in the VM metadata of any VMs which use SR-IOV VFs to prevent failed migrations.

PFs are defined in the `pvcnoded.yml` configuration of each node, via the `sriov_device` list. Each PF can have an arbitrary number of VFs (`vfcount`) allocated, though each NIC vendor and model has specific limits. Once configured, specifically with Intel NICs, PFs (and specifically, the `vfcount` attribute in the driver) are immutable and cannot be changed easily without completely flushing the node and rebooting it, so care should be taken to select the desired settings as early in the cluster configuration as possible.

Once created, VFs are also managed on a per-node basis. That is, each VF, on each host, even if they have the exact same device names, is managed separately. For instance, the PF `ens1f0` creating a VF `ens1f0v0` on "`hv1`", can have a different configuration from the identically-named VF `ens1f0v0` on "`hv2`". The administrator is responsible for ensuring consistency here, and for ensuring that devices do not overlap (e.g. assigning the same VF name to VMs on two separate nodes which might migrate to each other). PVC will however explicitly prevent two VMs from being assigned to the same VF on the same node, even if this may be technically possible in some cases.

When attaching VFs to VMs, there are two supported modes: `macvtap`, and `hostdev`.

`macvtap`, as the name suggests, uses the Linux `macvtap` driver to connect the VF to the VM. Once attached, the vNIC behaves just like a "bridged" network connection above, and like "bridged" connections, the "mode" of the NIC can be specified, defaulting to "virtio" but supporting various emulated devices instead. Note that in this mode, vLANs cannot be configured on the guest side; they must be specified in the VF configuration (`pvc network sriov vf set`) with one vLAN per VF. VMs with `macvtap` interfaces can be live migrated between nodes without issue, assuming there is a corresponding free VF on the destination node, and the SR-IOV functionality is transparent to the VM.

`hostdev` is a direct PCIe pass-through method. With a VF attached to a VM in `hostdev` mode, the virtual PCIe NIC device itself becomes hidden from the node, and is visible only to the guest, where it appears as a discrete PCIe device. In this mode, vLANs and other attributes can be set on the guest side at will, though setting vLANs and other properties in the VF configuration is still supported. The main caveat to this mode is that VMs with connected `hostdev` SR-IOV VFs *cannot be live migrated between nodes*. Only a `shutdown` migration is supported, and, like `macvtap`, an identical PCIe device at the same bus address must be present on the target node. To prevent unexpected failures, PVC will explicitly set the VM metadata for the "migration method" to "shutdown" the first time that a `hostdev` VF is attached to it; if this changes later, the administrator must change this back explicitly.

Generally speaking, SR-IOV connections are not recommended unless there is a good use-case for them. On modern hardware, software bridges are extremely performant, and are much simpler to manage. The functionality is provided for those rare use-cases where SR-IOV is absolutely required by the administrator, but care must be taken to understand all the requirements and caveats of SR-IOV before using it in production.

#### Other Client Networks

Future PVC versions may support other client network types, such as direct-routing between VMs.

### Fencing and Recovery

Self-management and self-healing are important components of PVC's design, and to accomplish this, PVC contains automated fencing and recovery functions to handle situations where nodes crash or become unreachable. PVC is then able, if properly configured, to directly power-cycle the failed node, and bring up any VMs that were running on it on the remaining hypervisors. This ensures that, while there might be a few minutes of downtime for VMs, they are recovered as quickly as possible without human intervention.

To operate correctly, these functions require each node in the cluster to have a functional IPMI-over-IP setup with a configured user who is able to perform chassis power commands. This differs depending on the chassis manufacturer and model, and should be tested prior to deploying any production cluster. If IPMI is not configured correctly at node startup, the daemon will warn and disable automatic recovery of the node. The IPMI should be present in the Upstream system network (see [System Networks](#system-networks) above), or in another secured network which is reachable from the Upstream system network, whichever is more convenient for the layout of the networks.

The general process is divided into 3 sections: detecting node failures, fencing nodes, and recovering from fenced nodes.

#### Detecting Failed Nodes

Within the PVC configuration, each node has 3 settings which determine the failure detection time. The first is the `keepalive_interval` setting. This is normally set to 5 seconds, and is the interval at which the node daemon of each node sends its keepalives (as well as gathers statistics about running VMs, Ceph components, etc.). This interval should never need to be changed, but is configurable for maximum flexibility in corner cases. During each keepalive, the node updates a specific key in the Zookeeper cluster with the current UNIX timestamp, which determines when the node was last alive. During their own keepalives, the other nodes check their peers' timestamps to confirm if they are updating normally. Note that, due to this happening during the peer keepalives, if all nodes lose contact with the Zookeeper database, they will *not* immediately begin fencing each other, since the keepalives will not complete; they will, however, upon recovery, jump immediately to the next section when they all realize that their last keepalives were over the threshold, and this situation is discussed there.

The second option is the `fence_intervals` setting. This option determines how many keepalive intervals a node can miss before it is marked `dead` and a fencing sequence started. This is normally set to 6 intervals, which combined with the 5 second `keepalive_interval`, gives a total of 30 seconds (+/- up to another 5 second `keepalive_interval` for peers should they not line up) for the node to be without updates before fencing begins.

The third setting is optional, and is best used in situations where the IPMI connectivity of a node is excessively flaky or can be impaired (e.g. georedundant clusters), or where VM uptime is more important than the burden of recovering from a split-brain situation, and is not as extensively tested. This option is `suicide_intervals`, and if set to a non-0 value, is the number of keepalive intervals before a node *itself* determines that it should forcibly power itself off, which should always be equal to or less than the normal `fence_intervals` setting. Naturally, the node must be somewhat functional to do this, and this can go very wrong, so using this option is not normally recommended.

#### Fencing Nodes

Once the cluster, and specifically one node in the cluster, has determined that a given node is `dead` due to a lack of keepalives, the fencing process starts. This spawns a dedicated child thread within the node daemon of the detecting node, which continually monitors the state of the `dead` node and then performs the fence.

During the `dead` process, the failed node has 6 chances, called "saving throws", at `keepalive_interval` second windows, to send another keepalive before it is fenced. This additional, fixed, delay helps ensure that the cluster will gracefully recover from intermittent network failures or loss of Zookeeper contact, by providing nodes up to another 6 keepalive intervals to save themselves once the fence timer actually begins. This bring the total time, with default options, of a node stopping contact to a node being fenced, to between 60 and 65 seconds. This duration is considered by the author an acceptable compromise between speedy recovery and avoiding false positives (and hence larger outages).

Once a node has been marked `dead` and has failed its 6 "saving throws", the fence process triggers an IPMI chassis reset sequence. First, the node is issued the standard IPMI `chassis power reset` command to trigger a cold system reset. Next, it waits a fixed 1 second and then issues a `chassis power on` signal to ensure the node is powered on (just in case it had already shut itself off). The node then waits a fixed 2 seconds, and then checks the current `chassis power status`. Using the results of these 3 commands, PVC is then able to determine with near certainty whether the node has truly been forced offline or not, and it can proceed to the next step.

#### Recovery from Node Fences

Once a node has been fenced, successfully or not, the system waits for one keepalive interval before proceeding.

The cluster then determines what to do based both on the result of the fence (whether the node was determined to have been successfully cold-reset or not) and on two additional configuration values. The first, `successful_fence`, specifies what action to take when the fence was successful, and is either `migrate` (VMs to other nodes), the default, or `None` (no action). The second, `failed_fence`, is an identical choice for when the fence was unsuccessful, and defaults to `None`.

If the fence was successful and `successful_fence` is set to `None`, then no migration takes place and the VMs on the fenced node will remain offline until the node recovers. If instead `successful_fence` is set to the default of `migrate`, the system will then begin migrating (and hence, starting) VMs that were active on the failed node to other nodes in the cluster. During this special `fence-flush` action, any stale RBD locks on the storage volumes are forcibly cleared, and this is considered safe since the fenced node is determined to have successfully been powered off and the VMs thus terminated. Once all VMs are migrated, the fenced node will then be set to a normal `flushed` state, as if it had been cleanly flushed before powering off. If and when the node returns to active, healthy service, either automatically (if the reset cleared the fault condition) or after human intervention, VMs can then migrate back and the cluster can resume normal operation; otherwise the cluster will remain in the degraded state until corrected.

If the fence was unsuccessful and `failed_fence` is set to the default of `None`, no automatic recovery takes place, since the cluster cannot determine that it is safe to do so. This would most commonly occur during network partitions where the `dead` node potentially remains up with VMs running on it, and the cluster is now in a split-brain situation. The `suicide_interval` option mentioned above is provided for this specific situation, and would allow the administrator to set the `failed_fence` action to `migrate` as well, as they could be somewhat confident that the node will have forcibly terminated itself. However due to the inherent potential for danger in this scenario, it is recommended to leave these options at their defaults, and handle such situations manually instead, as well as ensuring proper network design to avoid the potential for such split-brain situations to occur.

## Advanced Layouts

### Coordinators versus Hypervisors

While a normal basic PVC cluster would consist of 3, or perhaps 5, nodes, PVC is able to scale up much further by differentiating between "coordinator" and "hypervisor" nodes. Such a basic cluster would consist only of coordinator nodes. Scaling up however, it is prudent to add new nodes as hypervisor nodes instead to minimize database scaling problems.

#### Coordinators

Coordinators are a special set of 3 or 5 nodes with additional functionality. The coordinator nodes run, in addition to the PVC software itself, a number of databases and additional functions which are required by the whole cluster. An odd number of coordinators is *always* required to maintain quorum, though there are diminishing returns when creating more than 3. As mentioned above, generally for small clusters all nodes are coordinators.

These additional functions are:

0. The Zookeeper database cluster containing the cluster state and configuration
0. The Patroni PostgreSQL database cluster containing DNS records for managed networks and provisioning configurations
0. The FRR EBGP route reflectors and upstream BGP peers

In addition to these functions, coordinators can usually also run all other PVC node functions.

The set of coordinator nodes is generally configured at cluster bootstrap, initially with 3 nodes, which are then bootstrapped together to form a basic 3-node cluster. Additional nodes, either as coordinators or as hypervisors, can then be added to the running cluster to bring it up to its final size, either immediately or as the needs of the cluster change.

##### The Primary Coordinator

Within the set of coordinators, a single primary coordinator is elected at cluster startup and as nodes start and stop, or in response to administrative commands. Once a node becomes primary, it will remain so until it stops or is told not to be. This coordinator is responsible for some additional functionality in addition to the other coordinators. These additional functions are:

0. The floating IPs in the main networks
0. The default gateway IP for each managed client network
0. The DNSMasq instance handling DHCP and DNS for each managed client network
0. The API and provisioner clients and workers

PVC gracefully handles transitioning primary coordinator state, to minimize downtime. Workers will continue to operate on the old coordinator if available after a switchover and the administrator should be aware of any active tasks before switching the active primary coordinator.

#### Hypervisors

Hypervisor nodes do not run any of the database or routing functionality of coordinator nodes, nor can they become the primary coordinator node (for obvious reasons). When scaling a cluster up beyond the initial 3, or perhaps 5, coordinator nodes, or when an even number of nodes (e.g. 4) may be desired, any nodes beyond the 3 coordinators should be added as hypervisors.

Hypervisor nodes are capable of running VMs and Ceph OSD disks, just like coordinator nodes, though the latter is optional.

PVC has no limit to the number of hypervisor nodes that can connect to a set of coordinators, though beyond a dozen or so total nodes, a more scale-focused infrastructure solution may be warranted.

### Georedundancy

PVC supports geographic redundancy of nodes in order to facilitate disaster recovery scenarios when uptime is critical. Functionally, PVC behaves the same regardless of whether the 3 or more coordinators are in the same physical location, or remote physical locations.

When using geographic redundancy, there are several caveats to keep in mind:

* The Ceph storage subsystem is latency-sensitive. With the default replication configuration, at least 2 writes must succeed for the write to return a success, so the total write latency of a write on any system will be equal to the maximum latency between any two nodes. It is recommended to keep all PVC nodes as "close" as possible latency-wise or storage performance may suffer.

* The inter-node PVC networks (see [System Networks](#system-networks)) must be layer-2 networks (broadcast domains). These networks must be spanned to all nodes in all locations.

* The number of sites and positioning of coordinators at those sites is important. A majority (at least 2 in a 3-coordinator cluster, or 3 in a 5-coordinator cluster) of coordinators must be able to reach each other in a failure scenario for the cluster as a whole to remain functional. Thus, configurations such as 2 + 1 or 3 + 2 splits across 2 sites do *not* provide full redundancy, and the whole cluster will be down if the majority site is down. It is thus recommended to always have an odd number of sites to match the odd number of coordinators, for instance a 1 + 1 + 1 or 2 + 2 + 1 configuration. Also note that all hypervisors much be able to reach the majority coordinator group or their storage will be impacted as well.

    This diagram outlines the supported and unsupported/unreliable georedundant configurations for 3 nodes. Care must always be taken to ensure that the cluster can operate with the loss of any given georeundant site.

    ![georeundancy-caveats](/images/georedundancy-caveats.png)

    *Above: Supported and unsupported/unreliable georedundant configurations* 

* Even if the PVC software itself is in an unmanageable state, VMs will continue to run if at all possible. However, since the storage subsystem makes use of the same quorum, losing more than half of the coordinator nodes will very likely result in storage interruption as well, which will affect running VMs.

* Nodes in remote geographic locations might not be able to be fenced by the remaining PVC nodes if the entire site is unreachable. The cluster will thus be unable to automatically recover VMs at the failed site should it go down. If at all possible, redundant links to georedundant sites are recommended to ensure there is always a network path. Note that the `suicide_interval` configuration option, while it might seem to help here, will not, because the remaining nodes will not be able to reliably confirm if the remote site actually *did* shut itself off. Thus automatic failover of georedundant sides is a potential deficiency that must be considered.

If these requirements cannot be fulfilled, it may be best to have separate PVC clusters at each site and handle service redundancy at a higher layer to avoid a major disruption.

## Example System Diagrams

This section provides diagrams of 2 best-practice cluster configurations. These diagrams can be extrapolated out to almost any possible configuration and number of nodes.

#### Small 3-node cluster

![Small 3-node cluster](/images/pvc-3-node-cluster.png)

*Above: A diagram of a simple 3-node cluster with all nodes as coordinators. Dual 10 Gbps network interface per node, unified physical networking with collapsed cluster and storage networks.*

#### Large 8-node cluster

![Large 8-node cluster](/images/pvc-8-node-cluster.png)

*Above: A diagram of a large 8-node cluster with 3 coordinators and 5 hypervisors. Quad 10Gbps network interfaces per node, split physical networking into guest/cluster and storage networks.*
