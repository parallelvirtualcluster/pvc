# PVC - The Parallel Virtual Cluster suite

<p align="center">
<img alt="Logo banner" src="https://git.bonifacelabs.ca/uploads/-/system/project/avatar/135/pvc_logo.png"/>
<br/><br/>
<a href="https://github.com/joshuaboniface/pvc"><img alt="Release" src="https://img.shields.io/github/release/joshuaboniface/pvc.svg"/></a>
<a href="https://git.bonifacelabs.ca/bonifacelabs/pvc/pipelines"><img alt="Pipeline Status" src="https://git.bonifacelabs.ca/bonifacelabs/pvc/badges/master/pipeline.svg"/></a>
<a href="https://parallelvirtualcluster.readthedocs.io/en/latest/?badge=latest"><img alt="Documentation Status" src="https://readthedocs.org/projects/parallelvirtualcluster/badge/?version=latest"/></a>
</p>

PVC is a suite of Python 3 tools to manage virtualized clusters. It provides a fully-functional private cloud based on four key principles:

1. Be Free Software Forever (or Bust)
2. Be Opinionated and Efficient and Pick The Best Software
3. Be Scalable and Redundant but Not Hyperscale
4. Be Simple To Use, Configure, and Maintain

It is designed to be an administrator-friendly but extremely powerful and rich modern private cloud system, but without the feature bloat and complexity of tools like OpenStack. With PVC, an administrator can provision, manage, and update a cluster of dozens or more hypervisors running thousands of VMs using a simple CLI tool, HTTP API, or web interface. PVC is based entirely on Debian GNU/Linux and Free-and-Open-Source tools, providing the glue to bootstrap, provision and manage the cluster, then getting out of the administrators' way.

Your cloud, the best way; just add physical servers.

To get started with PVC, see [Installing](/installing) for details on setting up a set of PVC nodes, using [`pvc-ansible`](/manuals/ansible) to configure and bootstrap a cluster, and managing it with the [`pvc` cli](/manuals/cli) or [HTTP API](/manuals/api). For details on the project, its motivation, and architectural details, see [the About page](/about).
