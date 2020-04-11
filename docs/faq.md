# Frequently Asked Questions about Parallel Virtual Cluster

## General Questions

### What is it?

PVC is a virtual machine management suite designed around high-availability. It can be considered an alternative to ProxMox, VMWare, Nutanix, and other similar solutions that manage not just the VMs, but the surrounding infrastructure as well.

### Why would you make this?

The full story can be found in the [about page](https://parallelvirtualcluster.readthedocs.io/en/latest/about), but after becoming frustrated by numerous other management tools, I discovered that what I wanted didn't exist as FLOSS software, so I built it myself.

### Is PVC right for me?

PVC might be right for you if your requirements are:

1. You need KVM-based VMs.
2. You want management of storage and networking (a.k.a. "batteries-included") in the same tool.
3. You want hypervisor-level redundancy, able to tolerate hypervisor downtime seamlessly, for all elements of the stack.

I built PVC for my homelab first, found a perfect usecase with my employer, and think it might be useful to you too.

### Is 3 hypervisors really the minimum?

For a redundant cluster, yes. PVC requires a majority quorum for several subsystems, and the smallest possible majority quorum is 2/3. That said, you can run PVC on a single node for testing/lab purposes without host-level reundancy, should you wish to do so.

## Feature Questions

### Does PVC support Docker/Kubernetes/LXC/etc.

No. PVC supports only KVM VMs. To run Docker containers, etc., you would need to run a VM which then runs your containers.

### Does PVC have a WebUI?

Not yet. Right now, PVC management is done almost exclusively with an API and the included CLI interface to that API. A WebUI could and likely will be built in the future, but I'm not a frontend developer.

## Storage Questions

### Can I use RAID-5 with PVC?

The short answer is no. The long answer is: Ceph, the storage backend used by PVC, does support "erasure coded" pools which implement a RAID-5-like functionality. PVC does not support this for several reasons. If you use PVC, you must accept at the very least a 2x storage penalty, and for true safety and resiliency a 3x storage penalty, for VM storage. This is a trade-off of the architecture.

### Can I use spinning HDDs with PVC?

You can, but you won't like the results. SSDs are effectively required to obtain any sort of reasonable performance when running multiple VMs. Ideally, datacentre-grade SSDs as well, due to their significantly increased write endurance.

### What Ceph version does PVC use?

PVC requires Ceph 14.x (Nautilus). The official PVC repository includes Ceph 14.2.8. Debian Buster by default includes only 12.x (Luminous).
