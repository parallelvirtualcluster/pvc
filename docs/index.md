# PVC - The Parallel Virtual Cluster system

<p align="center">
<img alt="Logo banner" src="https://git.bonifacelabs.ca/uploads/-/system/project/avatar/135/pvc_logo.png"/>
<br/><br/>
<a href="https://github.com/parallelvirtualcluster/pvc"><img alt="License" src="https://img.shields.io/github/license/parallelvirtualcluster/pvc"/></a>
<a href="https://github.com/parallelvirtualcluster/pvc/releases"><img alt="Release" src="https://img.shields.io/github/release-pre/parallelvirtualcluster/pvc"/></a>
<a href="https://git.bonifacelabs.ca/parallelvirtualcluster/pvc/pipelines"><img alt="Pipeline Status" src="https://git.bonifacelabs.ca/parallelvirtualcluster/pvc/badges/master/pipeline.svg"/></a>
<a href="https://parallelvirtualcluster.readthedocs.io/en/latest/?badge=latest"><img alt="Documentation Status" src="https://readthedocs.org/projects/parallelvirtualcluster/badge/?version=latest"/></a>
</p>

PVC is a KVM+Ceph-based, Free Software, scalable, redundant, self-healing, and self-managing private cloud solution designed with administrator simplicity in mind. It is built from the ground-up to be redundant at the host layer, allowing the cluster to gracefully handle the loss of nodes or their components, both due to hardware failure or due to maintenance. It is able to scale from a minimum of 3 nodes up to 12 or more nodes, while retaining performance and flexibility, allowing the administrator to build a small cluster today and grow it as needed.

The major goal of PVC is to be administrator friendly, providing the power of Enterprise-grade private clouds like OpenStack, Nutanix, and VMWare to homelabbers, SMBs, and small ISPs, without the cost or complexity. It believes in picking the best tool for a job and abstracting it behind the cluster as a whole, freeing the administrator from the boring and time-consuming task of selecting the best component, and letting them get on with the things that really matter. Administration can be done from a simple CLI or via a RESTful API capable of building full-featured web frontends or additional applications, taking a self-documenting approach to keep the administrator learning curvet as low as possible. Setup is easy and straightforward with an [ISO-based node installer](https://github.com/parallelvirtualcluster/pvc-installer) and [Ansible role framework](https://github.com/parallelvirtualcluster/pvc-ansible) designed to get a cluster up and running as quickly as possible. Build your cloud in an hour, grow it as you need, and never worry about it: just add physical servers.

## Getting Started

To get started with PVC, read the [Cluster Architecture document](/architecture/cluster), then see [Installing](/installing) for details on setting up the initial PVC nodes, using [`pvc-ansible`](/manuals/ansible) to configure and bootstrap a cluster, and managing it with the [`pvc` cli](/manuals/cli) or [HTTP API](/manuals/api). For details on the project, its motivation, and architectural details, see [the About page](/about).

## Changelog

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

