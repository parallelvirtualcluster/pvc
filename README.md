<p align="center">
<img alt="Logo banner" src="https://docs.parallelvirtualcluster.org/en/latest/images/pvc_logo_black.png"/>
<br/><br/>
<a href="https://www.parallelvirtualcluster.org"><img alt="Website" src="https://img.shields.io/badge/visit-website-blue"/></a>
<a href="https://github.com/parallelvirtualcluster/pvc/releases"><img alt="Latest Release" src="https://img.shields.io/github/release-pre/parallelvirtualcluster/pvc"/></a>
<a href="https://docs.parallelvirtualcluster.org/en/latest/?badge=latest"><img alt="Documentation Status" src="https://readthedocs.org/projects/parallelvirtualcluster/badge/?version=latest"/></a>
<a href="https://github.com/parallelvirtualcluster/pvc"><img alt="License" src="https://img.shields.io/github/license/parallelvirtualcluster/pvc"/></a>
<a href="https://github.com/psf/black"><img alt="Code style: Black" src="https://img.shields.io/badge/code%20style-black-000000.svg"/></a>
</p>

## What is PVC?

PVC is a Linux KVM-based hyperconverged infrastructure (HCI) virtualization cluster solution that is fully Free Software, scalable, redundant, self-healing, self-managing, and designed for administrator simplicity. It is an alternative to other HCI solutions such as Ganeti, Harvester, Nutanix, and VMWare, as well as to other common virtualization stacks such as ProxMox and OpenStack.

PVC is a complete HCI solution, built from well-known and well-trusted Free Software tools, to assist an administrator in creating and managing a cluster of servers to run virtual machines, as well as self-managing several important aspects including storage failover, node failure and recovery, virtual machine failure and recovery, and network plumbing. It is designed to act consistently, reliably, and unobtrusively, letting the administrator concentrate on more important things.

PVC is highly scalable. From a minimum (production) node count of 3, up to 12 or more, and supporting many dozens of VMs, PVC scales along with your workload and requirements. Deploy a cluster once and grow it as your needs expand.

As a consequence of its features, PVC makes administrating very high-uptime VMs extremely easy, featuring VM live migration, built-in always-enabled shared storage with transparent multi-node replication, and consistent network plumbing throughout the cluster. Nodes can also be seamlessly removed from or added to service, with zero VM downtime, to facilitate maintenance, upgrades, or other work.

PVC also features an optional, fully customizable VM provisioning framework, designed to automate and simplify VM deployments using custom provisioning profiles, scripts, and CloudInit userdata API support.

Installation of PVC is accomplished by two main components: a [Node installer ISO](https://github.com/parallelvirtualcluster/pvc-installer) which creates on-demand installer ISOs, and an [Ansible role framework](https://github.com/parallelvirtualcluster/pvc-ansible) to configure, bootstrap, and administrate the nodes. Installation can also be fully automated with a companion [cluster bootstrapping system](https://github.com/parallelvirtualcluster/pvc-bootstrap). Once up, the cluster is managed via an HTTP REST API, accessible via a Python Click CLI client ~~or WebUI~~ (eventually).

Just give it physical servers, and it will run your VMs without you having to think about it, all in just an hour or two of setup time.

More information about PVC, its motivations, the hardware requirements, and setting up and managing a cluster [can be found over at our docs page](https://docs.parallelvirtualcluster.org).

## Getting Started

To get started with PVC, please see the [About](https://docs.parallelvirtualcluster.org/en/latest/about-pvc/) page for general information about the project, and the [Getting Started](https://docs.parallelvirtualcluster.org/en/latest/deployment/getting-started/) page for details on configuring your first cluster.

## Changelog

View the changelog in [CHANGELOG.md](https://github.com/parallelvirtualcluster/pvc/blob/master/CHANGELOG.md). **Please note that any breaking changes are announced here; ensure you read the changelog before upgrading!**

## Screenshots

These screenshots show some of the available functionality of the PVC system and CLI as of PVC v0.9.85.

<p><img alt="0. Integrated help" src="https://raw.githubusercontent.com/parallelvirtualcluster/pvc/refs/heads/master/images/0-integrated-help.png"/><br/>
<i>The CLI features an integrated, fully-featured help system to show details about every possible command.</i>
</p>

<p><img alt="1. Connection management" src="https://raw.githubusercontent.com/parallelvirtualcluster/pvc/refs/heads/master/images/1-connection-management.png"/><br/>
<i>A single CLI instance can manage multiple clusters, including a quick detail view, and will default to a "local" connection if an "/etc/pvc/pvc.conf" file is found; sensitive API keys are hidden by default.</i>
</p>

<p><img alt="2. Cluster details and output formats" src="https://raw.githubusercontent.com/parallelvirtualcluster/pvc/refs/heads/master/images/2-cluster-details-and-output-formats.png"/><br/>
<i>PVC can show the key details of your cluster at a glance, including health, persistent fault events, and key resources; the CLI can output both in pretty human format and JSON for easier machine parsing in scripts.</i>
</p>

<p><img alt="3. Node information" src="https://raw.githubusercontent.com/parallelvirtualcluster/pvc/refs/heads/master/images/3-node-information.png"/><br/>
<i>PVC can show details about the nodes in the cluster, including their live health and resource utilization.</i>
</p>

<p><img alt="4. VM information" src="https://raw.githubusercontent.com/parallelvirtualcluster/pvc/refs/heads/master/images/4-vm-information.png"/><br/>
<i>PVC can show details about the VMs in the cluster, including their state, resource allocations, current hosting node, and metadata.</i>
</p>

<p><img alt="5. VM details" src="https://raw.githubusercontent.com/parallelvirtualcluster/pvc/refs/heads/master/images/5-vm-details.png"/><br/>
<i>In addition to the above basic details, PVC can also show extensive information about a running VM's devices and other resource utilization.</i>
</p>

<p><img alt="6. Network information" src="https://raw.githubusercontent.com/parallelvirtualcluster/pvc/refs/heads/master/images/6-network-information.png"/><br/>
<i>PVC has two major client network types, and ensures a consistent configuration of client networks across the entire cluster; managed networks can feature DHCP, DNS, firewall, and other functionality including DHCP reservations.</i>
</p>

<p><img alt="7. Storage information" src="https://raw.githubusercontent.com/parallelvirtualcluster/pvc/refs/heads/master/images/7-storage-information.png"/><br/>
<i>PVC provides a convenient abstracted view of the underlying Ceph system and can manage all core aspects of it.</i>
</p>

<p><img alt="8. VM and node logs" src="https://raw.githubusercontent.com/parallelvirtualcluster/pvc/refs/heads/master/images/8-vm-and-node-logs.png"/><br/>
<i>PVC can display logs from VM serial consoles (if properly configured) and nodes in-client to facilitate quick troubleshooting.</i>
</p>

<p><img alt="9. VM and worker tasks" src="https://raw.githubusercontent.com/parallelvirtualcluster/pvc/refs/heads/master/images/9-vm-and-worker-tasks.png"/><br/>
<i>PVC provides full VM lifecycle management, as well as long-running worker-based commands (in this example, clearing a VM's storage locks).</i>
</p>

<p><img alt="10. Provisioner" src="https://raw.githubusercontent.com/parallelvirtualcluster/pvc/refs/heads/master/images/10-provisioner.png"/><br/>
<i>PVC features an extensively customizable and configurable VM provisioner system, including EC2-compatible CloudInit support, allowing you to define flexible VM profiles and provision new VMs with a single command.</i>
</p>

<p><img alt="11. Prometheus and Grafana dashboard" src="https://raw.githubusercontent.com/parallelvirtualcluster/pvc/refs/heads/master/images/11-prometheus-grafana.png"/><br/>
<i>PVC features several monitoring integration examples under "node-daemon/monitoring", including CheckMK, Munin, and, most recently, Prometheus, including an example Grafana dashboard for cluster monitoring and alerting.</i>
</p>
