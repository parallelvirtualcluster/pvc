# PVC - The Parallel Virtual Cluster system

<p align="center">
<img alt="Logo banner" src="https://git.bonifacelabs.ca/uploads/-/system/project/avatar/135/pvc_logo.png"/>
<br/><br/>
<a href="https://github.com/parallelvirtualcluster/pvc"><img alt="License" src="https://img.shields.io/github/license/parallelvirtualcluster/pvc"/></a>
<a href="https://github.com/parallelvirtualcluster/pvc/releases"><img alt="Release" src="https://img.shields.io/github/release-pre/parallelvirtualcluster/pvc"/></a>
<a href="https://parallelvirtualcluster.readthedocs.io/en/latest/?badge=latest"><img alt="Documentation Status" src="https://readthedocs.org/projects/parallelvirtualcluster/badge/?version=latest"/></a>
</p>

**NOTICE FOR GITHUB**: This repository is a read-only mirror of the PVC repositories from my personal GitLab instance. Pull requests submitted here will not be merged. Issues submitted here will however be treated as authoritative.

PVC is a KVM+Ceph+Zookeeper-based, Free Software, scalable, redundant, self-healing, and self-managing private cloud solution designed with administrator simplicity in mind. It is built from the ground-up to be redundant at the host layer, allowing the cluster to gracefully handle the loss of nodes or their components, both due to hardware failure or due to maintenance. It is able to scale from a minimum of 3 nodes up to 12 or more nodes, while retaining performance and flexibility, allowing the administrator to build a small cluster today and grow it as needed.

The major goal of PVC is to be administrator friendly, providing the power of Enterprise-grade private clouds like OpenStack, Nutanix, and VMWare to homelabbers, SMBs, and small ISPs, without the cost or complexity. It believes in picking the best tool for a job and abstracting it behind the cluster as a whole, freeing the administrator from the boring and time-consuming task of selecting the best component, and letting them get on with the things that really matter. Administration can be done from a simple CLI or via a RESTful API capable of building full-featured web frontends or additional applications, taking a self-documenting approach to keep the administrator learning curvet as low as possible. Setup is easy and straightforward with an [ISO-based node installer](https://git.bonifacelabs.ca/parallelvirtualcluster/pvc-installer) and [Ansible role framework](https://git.bonifacelabs.ca/parallelvirtualcluster/pvc-ansible) designed to get a cluster up and running as quickly as possible. Build your cloud in an hour, grow it as you need, and never worry about it: just add physical servers.

## Getting Started

To get started with PVC, please see the [About](https://parallelvirtualcluster.readthedocs.io/en/latest/about/) page for general information about the project, and the [Getting Started](https://parallelvirtualcluster.readthedocs.io/en/latest/getting-started/) page for details on configuring your cluster.

## Changelog

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

