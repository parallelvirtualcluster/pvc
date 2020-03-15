# PVC Provisioner manual

The PVC provisioner is a subsection of the main PVC API. IT interfaces directly with the Zookeeper database using the common client functions, and with the Patroni PostgreSQL database to store details. The provisioner also interfaces directly with the Ceph storage cluster, for mapping volumes, creating filesystems, and installing guests.

Details of the Provisioner API interface can be found in [the API manual](/manuals/api).

## Overview

The purpose of the Provisioner API is to provide a convenient way for administrators to automate the creation of new virtual machines on the PVC cluster.

The Provisioner allows the administrator to constuct descriptions of VMs, called profiles, which include system resource specifications, network interfaces, disks, cloud-init userdata, and installation scripts. These profiles are highly modular, allowing the administrator to specify arbitrary combinations of the mentioned VM features with which to build new VMs.

The provisioner supports creating VMs based off of installation scripts, by cloning existing volumes, and by uploading OVA image templates to the cluster.

Examples in the following sections use the CLI exclusively for demonstration purposes. For details of the underlying API calls, please see the [API interface reference](/manuals/api-reference.html).

# Deploying VMs from OVA images

PVC supports deploying virtual machines from industry-standard OVA images. OVA images can be uploaded to the cluster with the `pvc provisioner ova` commands, and deployed via the created profile(s) using the `pvc provisioner create` command. Additionally, the profile(s) can be modified to suite your specific needs via the provisioner template system detailed below.

# Deploying VMs from provisioner scripts

PVC supports deploying virtual machines using administrator-provided scripts, using templates, profiles, and Cloud-init userdata to control the deployment process as desired. This deployment method permits the administrator to deploy POSIX-like systems such as Linux or BSD directly from a companion tool such as `debootstrap` on-demand and with maximum flexibility.

## Templates

The PVC Provisioner features three categories of templates to specify the resources allocated to the virtual machine. They are: System Templates, Network Templates, and Disk Templates.

### System Templates

System templates specify the basic resources of the virtual machine: vCPUs, memory, and configuration metadata (e.g. serial/VNC consoles, migration methods, node limits, etc.). Each profile requires a single system template.

The simplest templates will specify a number of vCPUs and the amount of vRAM; additional details can be specified if required.

Serial consoles permit the use of the `pvc vm log` functionality via console logfiles in `/var/log/libvirt`.

VNC consoles permit graphical access to the VM. By default, the VNC interface listens only on 127.0.0.1 on its parent node; the VNC bind configuration can override this to listen on other interfaces, including `0.0.0.0` for all.

```
$ pvc provisioner template system list
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

System templates:

Name        ID  vCPUs  vRAM [MB]  Consoles: Serial  VNC    VNC bind   Metadata: Limit     Selector    Autostart  
ext-lg      80  4      8192                 False   False  None                 None      None        False
ext-lg-ser  81  4      8192                 True    False  None                 None      None        False
ext-lg-vnc  82  4      8192                 False   True   0.0.0.0              None      None        False
ext-sm-lim  83  1      1024                 True    False  None                 pvchv1    mem         True
```

### Network Templates

Network template specify which PVC networks the virtual machine is bound to, as well as the method used to calculate MAC addresses for VM interfaces. Networks are specified by their VNI ID within PVC.

A template requires at least one network VNI to be valid.

```
$ pvc provisioner template network list
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

Network templates:

Name      ID  MAC template  Network VNIs
ext-101   80  None          101
ext-11X   81  None          110,1101
```

In some cases, it may be useful for the administrator to specify a static MAC address pattern for a set of VMs, for instance if they must get consistent DHCP reservations between rebuilds. Such a MAC address template can be specified when adding a new network template, using a standardized layout and set of interpolated variables. For example:

```
$ pvc provisioner template network list
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

Network templates:

Name       ID  MAC template                  Network VNIs
fixed-mac  82  {prefix}:XX:XX:{vmid}{netid}  1000,1001
```

The {prefix} variable is replaced by the provisioner with a standard prefix ("52:54:01"), which is different from the randomly-generated MAC prefix ("52:54:00") to avoid accidental overlap of MAC addresses.

The {vmid} variable is replaced by a single hexidecimal digit representing the VM's ID, the numerical suffix portion of its name; VMs without a suffix numeral have ID 0. VMs with IDs greater than 15 (hexidecimal "f") will wrap back to 0.

The {netid} variable is replaced by the sequential identifier, starting at 0, of the network VNI of the interface; for example, the first interface is 0, the second is 1, etc. Like te VM ID, network IDs greater than 15 (hexidecimal "f") will wrap back to 0.

The four X digits are use-configurable. Use these digits to uniquely define the MAC address.

The location of the two per-VM variables can be adjusted at the administrator's discretion, or removed if not required (e.g. a single-network template, or template for a single VM). In such situations, be careful to avoid accidental overlap with other templates' variable portions.

### Disk Templates

Disk templates specify the disk layout, including filesystem and mountpoint for scripted deployments, for the VM. Disks are specified by their virtual disk ID in Libvirt, and sizes are always specified in GB. Disks may also reference other storage volumes, which will then be cloned during provisioning.

For additional flexibility, the volume filesystem and mountpoint are optional; such volumes will be created and attached to the VM but will not be modified during provisioning.

```
$ pvc provisioner template storage list
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

Storage templates:

Name           ID  Disk ID  Pool     Source Volume  Size [GB]  Filesystem  Arguments  Mountpoint
standard-ext4  21
                   sda      blsevm   None           2          ext4        -L=root    /
                   sdb      blsevm   None           4          ext4        -L=var     /var
                   sdc      blsevm   None           4          ext4        -L=log     /var/log
large-cloned   22
                   sda      blsevm   template_sda   None       None        None       None
                   sdb      blsevm   None           40         None        None       None
```

## Cloud-Init Userdata

PVC allows the sending of arbitrary cloud-init userdata to VMs on bootup. It uses an Amazon AWS EC2-style metadata service to delivery basic VM information and this userdata to the VMs, based dynamically on the assigned profile of the VM at boot time.

Both single-function and multipart cloud-init userdata is supported. Examples can be found at `/usr/share/pvc/provisioner/examples` on a PVC node.

The default userdata document "empty" can be used to skip userdata for a profile.

```
$ pvc provisioner userdata list
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

Name        ID  Document
empty       10
basic-ssh   11  Content-Type: text/cloud-config; charset="us-ascii"
                MIME-Version: 1.0

                #cloud-config
                [...]
```

## Provisioning Scripts

The PVC provisioner provides a scripting framework in order to automate VM installation. This is generally the most useful with UNIX-like systems which can be installed over the network via shell scripts. For instance, the script might install a Debian VM using `debootstrap`.

Provisioner scripts are written in Python 3 and are called in a standardized way during the provisioning sequence. A single function called `install` is called during the provisioning sequence to perform OS installation and basic configuration.

*A WARNING*: It's important to remember that these provisioning scripts will run with the same privileges as the provisioner API daemon (usually root) on the system running the daemon. THIS MAY POSE A SECURITY RISK. However, the intent is that administrators of the cluster are the only ones allowed to specify these scripts, and that they check them thoroughly when adding them to the system as well as limit access to the provisioning API to trusted sources. If neither of these conditions are possible, for instance if arbitrary users must specify custom scripts without administrator oversight, then the PVC provisoner may not be ideal.

The default script "empty" can be used to skip scripted installation for a profile. Additionally, profiles with no valid disk mountpoints skip scripted installation.

```
$ pvc provisioner script list
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

Name         ID  Script
empty        1
debootstrap  2   #!/usr/bin/env python3

                 # debootstrap_script.py - PVC Provisioner example script for Debootstrap
                 # Part of the Parallel Virtual Cluster (PVC) system
                 [...]
```

### `install` function

The `install` function is the main entrypoing for a provisioning script, and is the only part of the script that is explicitly called. The provisioner calls this function after setting up the temporary install directory and mounting the volumes. Thus, this script can then perform any sort of tasks required in the VM to install it, and then finishes.

This function is passed a number of keyword arguments that it can then use during installation. These include those specified by the administrator in the profile, as well as a number of default arguments:

###### `vm_name`

The `vm_name` keyword argument contains the full name of the new VM from PVC's perspective.

###### `vm_id`

The `vm_id` keyword argument contains the VM identifier (the last numeral of the VM name, or `0` for a VM that does not end in a numeral).

###### `temporary_directory`

The `temporary_directory` keyword argument contains the path to the temporary directory on which the new VM's disks are mounted. The function *must* perform any installation steps to/under this directory.

###### `disks`

The `disks` keyword argument contains a Python list of the configured disks, as dictionaries of values as specified in the Disk template. The function *may* use these values as appropriate, for instance to specify an `/etc/fstab`.

###### `networks`

The `networks` keyword argument contains a Python list of the configured networks, as dictionaries of values as specified in the Network template. The function *may* use these values as appropriate, for instance to write an `/etc/network/interfaces` file.

## Profiles

Provisioner profiles combine the templates, userdata, and scripts together into dynamic configurations which are then applied to the VM when provisioned. The VM retains the record of this profile name in its configuration for the full lifetime of the VM on the cluster, most generally for cloud-init functionality.

Additional arguments to the installation script can be specified along with the profile, to allow further customization of the installation if required.

```
$ pvc provisioner profile list
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

Name        ID  Templates: System      Network  Storage        Data: Userdata   Script       Script Arguments
std-large   41             ext-lg-ser  ext-101  standard-ext4        basic-ssh  debootstrap  deb_release=buster
```

## Creating VMs with the Provisioner

Creating VMs with the provisioner requires specifying a VM name and a profile to use.

```
$ pvc provisioner create test1 std-large
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

Task ID: af1d0682-53e8-4141-982f-f672e2f23261
```

This will create a worker job on the current primary node, and status can be queried by providing the job ID.

```
 $ pvc provisioner status af1d0682-53e8-4141-982f-f672e2f23261
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

Job state: RUNNING
Stage: 7/10
Status: Mapping, formatting, and mounting storage volumes locally
```

A list of all running and queued jobs can be obtained by requesting the provisioner status without an ID.

```
$ pvc provisioner status
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

Job ID                                Status   Worker         VM: Name   Profile    Define?  Start?
af1d0682-53e8-4141-982f-f672e2f23261  active   celery@pvchv1      test1  std-large  True     True
94abb7fe-41f5-42be-b984-de92854f4b3f  pending  celery@pvchv1      test2  std-large  True     True
43d57a2d-8d0d-42f6-90df-cc39956825a9  pending  celery@pvchv1      testX  std-large  False    False
```

Additionally, the `--wait` option can be given to the create command. This will cause the command to block and providing a visual progress indicator while the provisioning occurs.

```
$ pvc provisioner create test2 std-large
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

Task ID: 94abb7fe-41f5-42be-b984-de92854f4b3f

Waiting for task to start..... done.

  [####################################]  100%  Starting VM

SUCCESS: VM "test2" with profile "std-large" has been provisioned and started successfully
```

The administrator can also specify whether or not to automatically define and start the VM when launching a provisioner job, using the `--define`/`--no-define` and `--start`/`--no-start` options. The default is to define and start a VM. `--no-define` implies `--no-start` as there would be no VM to start.

```
$ pvc provisioner create test3 std-large --no-define
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

Task ID: 43d57a2d-8d0d-42f6-90df-cc39956825a9
```

A VM set to do so will be defined on the cluster early in the provisioning process, before creating disks or executing the provisioning script, and with the special status "provision". Once completed, if the VM is not set to start automatically, the state will remain "provision" (with the VM not running) until its state is explicitly changed wit the client (or via autostart when its node returns to ready state).

Provisioning jobs are tied to the node that spawned them. If the primary node changes, provisioning jobs will continue to run against that node until they are completed or interrupted, but the active API (now on the new primary node) will not have access to any status data from these jobs, until the primary node status is returned to the original host. The CLI will warn the administrator of this if there are active jobs while running node primary or secondary commands.

Provisioning jobs cannot be cancelled, either before they start or during execution. The administrator should always let an invalid job either complete or fail out automatically, then remove the erroneous VM with the vm remove command.
