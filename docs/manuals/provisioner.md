# PVC Provisioner Manual

The PVC provisioner is a subsection of the main PVC API. It interfaces directly with the Zookeeper database using the common client functions, and with the Patroni PostgreSQL database to store details. The provisioner also interfaces directly with the Ceph storage cluster, for mapping volumes, creating filesystems, and installing guests.

Details of the Provisioner API interface can be found in [the API manual](/manuals/api).

- [PVC Provisioner Manual](#pvc-provisioner-manual)
  * [Overview](#overview)
  * [PVC Provisioner concepts](#pvc-provisioner-concepts)
    + [Templates](#templates)
    + [Userdata](#cloud-init-userdata)
    + [Scripts](#provisioning-scripts)
    + [Profiles](#profiles)
  * [Deploying VMs from provisioner scripts](#deploying-vms-from-provisioner-scripts)
  * [Deploying VMs from OVA images](#deploying-vms-from-ova-images)
    + [Uploading an OVA](#uploading-an-ova)
    + [The OVA Provisioning Script](#the-ova-provisioning-script)
    + [OVA limitations](#ova-limitations)

## Overview

The purpose of the Provisioner API is to provide a convenient way for administrators to automate the creation of new virtual machines on the PVC cluster.

The Provisioner allows the administrator to construct descriptions of VMs, called profiles, which include system resource specifications, network interfaces, disks, cloud-init userdata, and installation scripts. These profiles are highly modular, allowing the administrator to specify arbitrary combinations of the mentioned VM features with which to build new VMs.

The provisioner supports creating VMs based off of installation scripts, by cloning existing volumes, and by uploading OVA image templates to the cluster.

Examples in the following sections use the CLI exclusively for demonstration purposes. For details of the underlying API calls, please see the [API interface reference](/manuals/api-reference.html).

Use of the PVC Provisioner is not required. Administrators can always perform their own installation tasks, and the provisioner is not specially integrated, calling various other API commands as though they were run from the CLI or API.

# PVC Provisioner concepts

Before explaining how to create VMs using either OVA images or installer scripts, we must discuss the concepts used to construct the PVC provisioner system.

## Templates

Templates are the building blocks of VMs. Each template type specifies part of the configuration of a VM, and when combined together later into profiles, provide a full description of the VM resources.

Templates are used to provide flexibility for the administrator. For instance, one could specify some standard core resources for different VMs, but then specify a different set of storage devices and networks for each one. This flexibility is at the heart of this system, allowing the administrator to construct a complex set of VM configurations from a few basic templates.

The PVC Provisioner features three types of templates: System Templates, Network Templates, and Disk Templates.

### System Templates

System templates specify the basic resources of the virtual machine: vCPUs, memory, serial/VNC consoles, and PVC configuration metadata (migration methods, node limits, etc.). Each profile requires a single system template.

The simplest valid template will specify a number of vCPUs and an amount of vRAM; additional details are optional and can be specified if required.

Serial consoles are required to make use of the `pvc vm log` functionality, via console logfiles in `/var/log/libvirt` on the nodes. VMs without a serial console show an empty log. Note that the guest operating system must also be configured to provide output to this serial console for this functionality to work as expected.

VNC consoles permit graphical access to the VM. By default, the VNC interface listens only on 127.0.0.1 on its parent node; the VNC bind configuration can override this to listen on other interfaces, including `0.0.0.0` for all.

PVC does not currently support SPICE or any other non-VNC consoles.

#### Examples

```
$ pvc provisioner template system list
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

System templates:

Name        ID  vCPUs  vRAM [MB]  Consoles: Serial  VNC    VNC bind   Metadata: Limit           Selector    Autostart  Migration
ext-lg      80  4      8192                 False   False  None                 None            None        False      None
ext-lg-ser  81  4      8192                 True    False  None                 None            None        False      None
ext-lg-vnc  82  4      8192                 False   True   0.0.0.0              None            None        False      None
ext-sm-lim  83  1      1024                 True    False  None                 pvchv1,pvchv2   mem         True       live
```

* The first example specifies a template with 4 vCPUs and 8GB of RAM. It has no serial or VNC consoles, and no non-default metadata, forming the most basic possible system template.

* The second example specifies a template with the same vCPU and RAM quantities as the first, but with a serial console as well. VMs using this template will be able to make use of `pvc vm log` as long as their guest operating system is configured to use it.

* The third example specifies a template with an alternate console to the second, in this case a VNC console bound to `0.0.0.0` (all interfaces). VNC ports are always auto-selected due to the dynamic nature of PVC, and the administrator can connect to them once the VM is running by determining the port on the hosting hypervisor (e.g. with `netstat -tl`).

* The fourth example shows the ability to set PVC cluster metadata in a system template. VMs with this template will be forcibly limited to running on the hypervisors `pvchv1` and `pvchv2`, but no others, will explicitly use the `mem` (free memory) selector when choosing migration or deployment targets, will be set to automatically start on reboot of its hypervisor, and will be limited to live migration between nodes. For full details on what these options mean, see `pvc vm meta -h`.

### Network Templates

Network template specify which PVC networks the virtual machine will be bound to, as well as the method used to calculate MAC addresses for VM interfaces. Networks are specified by their VNI ID within PVC.

A network template requires at least one network VNI to be valid, and is created in two stages. First, `pvc provisioner template network add` adds the template itself, along with the optional MAC template. Second, `pvc provisioner template network vni add` adds a VNI into the network template. VNIs are always shown and created in the order added; to move networks around they must be removed then re-added in the proper order; this will not affect existing VMs provisioned with the template.

In some cases, it may be useful for the administrator to specify a static MAC address pattern for a set of VMs, for instance if they must get consistent DHCP reservations between rebuilds. Such a MAC address template can be specified when adding a new network template, using a standardized layout and set of interpolated variables. This is an optional feature; if no MAC template is specified, VMs will be configured with random MAC addresses for each interface at deploy time.

#### Examples

```
$ pvc provisioner template network list
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

Network templates:

Name       ID  MAC template                  Network VNIs
ext-101    80  None                          101
ext-11X    81  None                          110,1101
fixed-mac  82  {prefix}:ff:ff:{vmid}{netid}  1000,1001,1002
```

* The first example shows a simple single-VNI network with no MAC template.

* The second example shows a dual-VNI network with no MAC template. Note the ordering; as mentioned, the first VNI will be provisioned on `eth0`, the second VNI on `eth1`, etc.

* The third example shows a triple-VNI network with a MAC template. The variable names shown are literal, while the `f` values are user-configurable and must be set to valid hexadecimal values by the administrator to uniquely identify the MAC address (in this case, using `ff:ff` for that segment). The variables are interpolated at deploy time as follows:

    * The `{prefix}` variable is replaced by the provisioner with a standard prefix (`52:54:01`), which is different from the randomly-generated MAC prefix (`52:54:00`) to avoid accidental overlap of MAC addresses. These OUI prefixes are not assigned to any vendor by the IEEE and thus should not conflict with any (real, standards-compliant) devices on the network.

    * The `{vmid}` variable is replaced by a single hexadecimal digit representing the VM's ID, the numerical suffix portion of its name (e.g. `myvm2` will have ID 2); VMs without a suffix numeral in their names have ID 0. VMs with IDs greater than 15 (hexadecimal `f`) will wrap back to 0, so a single MAC template should never be used by more than 16 VMs (numbered 0-15).

    * The `{netid}` variable is replaced by a single hexadecimal digit representing the sequential identifier, starting at 0, of the interface within the template (i.e. the first interface is 0, the second is 1, etc.). Like the VM ID, network IDs greater than 15 (hexadecimal `f`) will wrap back to 0, so a single VM should never have more than 16 interfaces.

    * The location of the two per-VM variables can be adjusted at the administrator's discretion, or removed if not required (e.g. a single-network template, or template for a single VM). In such situations, be careful to avoid accidental overlap with other templates' variable portions.

### Disk Templates

Disk templates specify the disk layout, including filesystem and mountpoint for scripted deployments, for the VM. Disks are specified by their virtual disk ID in Libvirt, in either `sdX` or `vdX` format, and sizes are always specified in GB. Disks may also reference other storage volumes, which will then be cloned during provisioning.

For additional flexibility, the volume filesystem and mountpoint are optional; such volumes will be created and attached to the VM but will not be modified during provisioning.

All storage volumes created by the provisioner at deploy time, regardless of source or type, will be named in the format `<vmname>_<id>`, for instance `myvm_sda`.

#### Examples

```
$ pvc provisioner template storage list
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

Storage templates:

Name           ID  Disk ID  Pool  Source Volume  Size [GB]  Filesystem  Arguments  Mountpoint
standard-ext4  21
                   sda      vms   None           2          ext4        -L=root    /
                   sdb      vms   None           4          ext4        -L=var     /var
                   sdc      vms   None           4          ext4        -L=log     /var/log
large-cloned   22
                   sda      vms   template_sda   None       None        None       None
                   sdb      vms   None           40         None        None       None
```

* The first example shows a volume with a simple 3-disk layout suitable for most Linux distributions. Each volume is in pool `vms`, with an `ext4` filesystem, an argument specifying a disk label, and a mountpoint to which the volume will be mounted when deploying the VM. All 3 volumes will be created at deploy time. When deploying VMs using Scripts detailed below, this is the normal format that storage templates should take to ensure that all block devices are formatted and mounted in the proper place for the script to take over and install the operating system to them.

* The second example shows both a cloned volume and a blank volume. At deploy time, the Source Volume for the `sda` device will be cloned and attached to the VM at `sda`. The second volume will be created at deploy time, but will not be formatted or mounted, and will thus show as an empty block device inside the VM. This type of storage template is more suited to devices that do not use the Script install method, and are instead cloned from a source volume, either another running VM, or a manually-uploaded disk image.

* Unformatted block devices as shown in the second example can be used in any type of storage template, though care should be taken to consider their purpose; unformatted block devices are completely ignored by the Script at deploy time.

## Cloud-Init Userdata

PVC allows the sending of arbitrary cloud-init userdata to VMs on boot-up. It uses an Amazon AWS EC2-style metadata service, listening at the link-local IP `169.254.169.254` on port `80`, to delivery basic VM information and this userdata to the VMs. The metadata to be sent is based dynamically on the assigned profile of the VM at boot time.

Both single-function and multipart cloud-init userdata is supported. Full examples can be found under `/usr/share/pvc/provisioner/examples` on any PVC coordinator node.

The default userdata document "empty" can be used to skip userdata for a profile.

#### Examples

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

* The first example is the default, always-present `empty` document, which is sent to invalid VMs if requested, or can be configured explicitly for profiles that do not require cloud-init userdata, instead of leaving that section of the profile as `None`.

* The second, truncated, example is the start of a normal single-function userdata document. For full details on the contents of these documents, see the cloud-init documentation.

## Provisioning Scripts

The PVC provisioner provides a scripting framework in order to automate VM installation. This is generally the most useful with UNIX-like systems which can be installed over the network via shell scripts. For instance, the script might install a Debian VM using `debootstrap`, which is automatically installed by default. However all deployment profiles require some provisioning script, minimally to craft their Libvirt configuration.

Several example scripts are provided in the `/usr/share/pvc/provisioner/examples/scripts` directory of all PVC hypervisors. These can be imported into the provisioner system as-is to help get you started, or you are of course free to modify or extend these as you wish, or write your own based on them to suit your needs.

Provisioner scripts are written in Python 3 and are implemented as a class, `VMBuilderScript`, which extends the built-in `VMBuilder` class, for example:

```python
#!/usr/bin/env python3
# I am an example provisioner script

from pvcapid.vmbuilder import VMBuilder

class VMBuilderScript(VMBuilder):
    def setup(self):
        ...
```

Each `VMBuilderScript` class instance should provide the 5 functions defined by the VMBuilder class (or they will be noops). All 5 functions should take no arguments except `self`; data is passed to them from the parent `VMBuilder` class as outlined below. Each function provides a specific part of the installation process to automate each step with maximum flexibility:

* `setup()`: Performs any special initial setup (e.g. fetching scripts or configs from the Internet) and validation of the environment (e.g. checking if particular binaries are available) before proceeding with the install.

* `create()`: Creates the VM libvirt XML definition based on the information provided by the VM profile and arguments. This is the only function that returns data (namely, the string representation of the XML config).

* `prepare()`: Creates and prepares any RBD storage volumes, filesystems, and mountpoints for the next step.

* `install()`: Performs any install steps required; note that the lines between `prepare()` and `install()` are fuzzy; the main point is that these are delineated in the sequence as discrete steps.

* `cleanup()`: Performs any "inner" cleanup of things done in the `prepare()` or `install()` steps (e.g. unmounting and unmapping RBD volumes, removing temporary files, etc.); also called on any *failure* of those steps.

Each step is described in more detail in the various examples, and those should be consulted to get a full understanding of how the steps work.

Note that no `__init__` should be provided by a script: doing so could result in failing scripts and should not be required.

As mentioned above, the `VMBuilderScript` instance includes several instance variables inherited from the parent `VMBuilder` definition. These consist of:

* `self.vm_name`: The name of the VM as provided to `pvc provisioner create`.

* `self.vm_id`: The numeral at the end of the `vm_name` (e.g. 2 for `web2`), or `0` if no numeral is present. Mostly useful when combined with network MAC address templates or preseeding clustered hosts.

* `self.vm_uuid`: An automatically, randomly-generated universal unique ID for the VM to use in its Libvirt XML definition (or elsewhere, if required).

* `self.vm_profile`: The name of the PVC provisioner profile used to create the VM. Mostly useful for VM descriptions.

* `self.vm_data`: A full dictionary representation of the data provided by the PVC provisioner about the VM. Includes many useful details for crafting the VM configuration and setting up disks and networks. An example, in JSON format:

   ```
   {
     "ceph_monitor_list": [
       "hv1.pvcstorage.tld",
       "hv2.pvcstorage.tld",
       "hv3.pvcstorage.tld"
     ],
     "ceph_monitor_port": "6789",
     "ceph_monitor_secret": "96721723-8650-4a72-b8f6-a93cd1a20f0c",
     "mac_template": null,
     "networks": [
       {
         "eth_bridge": "vmbr1001",
         "id": 72,
         "network_template": 69,
         "vni": "1001"
       },
       {
         "eth_bridge": "vmbr101",
         "id": 73,
         "network_template": 69,
         "vni": "101"
       }
     ],
     "script": [contents of this file]
     "script_arguments": {
       "deb_mirror": "http://ftp.debian.org/debian",
       "deb_release": "bullseye"
     },
     "system_architecture": "x86_64",
     "system_details": {
       "id": 78,
       "migration_method": "live",
       "name": "small",
       "node_autostart": false,
       "node_limit": null,
       "node_selector": null,
       "ova": null,
       "serial": true,
       "vcpu_count": 2,
       "vnc": false,
       "vnc_bind": null,
       "vram_mb": 2048
     },
     "volumes": [
       {
         "disk_id": "sda",
         "disk_size_gb": 4,
         "filesystem": "ext4",
         "filesystem_args": "-L=root",
         "id": 9,
         "mountpoint": "/",
         "pool": "vms",
         "source_volume": null,
         "storage_template": 67
       },
       {
         "disk_id": "sdb",
         "disk_size_gb": 4,
         "filesystem": "ext4",
         "filesystem_args": "-L=var",
         "id": 10,
         "mountpoint": "/var",
         "pool": "vms",
         "source_volume": null,
         "storage_template": 67
       },
       {
         "disk_id": "sdc",
         "disk_size_gb": 4,
         "filesystem": "ext4",
         "filesystem_args": "-L=log",
         "id": 11,
         "mountpoint": "/var/log",
         "pool": "vms",
         "source_volume": null,
         "storage_template": 67
       }
     ]
   }
   ```

Since the `VMBuilderScript` runs within its own context but within the PVC Provisioner/API system, it is possible to use many helper libraries from the PVC system itself, including both the built-in daemon libraries (used by the API itself) and several explicit provisioning script helpers. The following are commonly-used (in the examples) imports that can be leveraged:

* `pvcapid.vmbuilder.VMBuilder`: Required, provides the parent class for the `VMBuilderScript` class.
* `pvcapid.vmbuilder.ProvisioningError`: An exception that should be used within the `VMBuilderScript` to raise exceptions (though you can of course raise any other exception you wish or define your own).
* `pvcapid.vmbuilder.open_zk`: A context manager that can be used to open a Zookeeper connection, providing a `zkhandler` that can be passed to other PVC daemon library functions below.
* `pvcapid.vmbuilder.chroot`: A context manager that can be used to easily `chroot` into a given directory.
* `pvcapid.Daemon.config`: A configuration variable that *must* be passed to `open_zk` if it is used.
* `pvcapid.libvirt_schema`: A library providing a number of helpful Libvirt XML snippits that can be used to aid in building a working VM config for PVC. See the examples for a full usecase.
* `daemon_lib.common`: Part of the PVC daemon libraries, provides several common functions, including, most usefully, `run_os_command` which provides a wrapped, convenient method to call arbitrary shell/OS commands while returning a POSIX returncode, stdout, and stderr (a tuple of the 3 in that order).
* `daemon_lib.ceph`: Part of the PVC daemon libraries, provides several commands for managing Ceph RBD volumes, including, but not limited to, `clone_volume`, `add_volume`, `map_volume`, and `unmap_volume`. See the `debootstrap` example for a detailed usage example.

For safety reasons, the script runs in a modified chroot environment on the hypervisor. It will have full access to the entire / (root partition) of the hypervisor, but read-only. In addition it has read-write access to /dev, /sys, /run, and a fresh /tmp to write to; use /tmp/target (as convention) as the destination for any mounting of volumes and installation. Thus it is not possible to do things like `apt-get install`ing additional programs within a script; any such requirements must be set up before running the script (e.g. via `pvc-ansible`).

**WARNING**: Of course, despite this "safety" mechanism, it is VERY IMPORTANT to be cognizant that this script runs AS ROOT ON THE HYPERVISOR SYSTEM with FULL ACCESS to the cluster. You should NEVER allow arbitrary, untrusted users the ability to add or modify provisioning scripts. It is trivially easy to write scripts which will do destructive things - for example writing to arbitrary /dev objects, running arbitrary root-level commands, or importing PVC library functions to delete VMs, RBD volumes, or pools. Thus, ensure you vett and understand every script on the system, audit them regularly for both intentional and accidental malicious activity, and of course (to reiterate), do not allow untrusted script creation!

## Profiles

Provisioner profiles combine the templates, userdata, and scripts together into dynamic configurations which are then applied to the VM when provisioned. The VM retains the record of this profile name in its configuration for the full lifetime of the VM on the cluster; this is primarily used for cloud-init functionality, but may also serve as a convenient administrator reference.

Additional arguments to the installation script can be specified along with the profile, to allow further customization of the installation if required.

#### Examples

```
$ pvc provisioner profile list
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

Name        ID  Templates: System      Network  Storage        Data: Userdata   Script       Script Arguments
std-large   41             ext-lg-ser  ext-101  standard-ext4        basic-ssh  debootstrap  deb_release=buster
```

# Deploying VMs from provisioner scripts

Once a profile with a Script value is defined, creating VMs with the provisioner is as simple as specifying a VM name and a profile to use.

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
Stage: 4/10
Status: Running script setup() step
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

The `--wait` option can be given to the create command. This will cause the command to block and providing a visual progress indicator while the provisioning occurs.

```
$ pvc provisioner create --wait test2 std-large
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

Task ID: 94abb7fe-41f5-42be-b984-de92854f4b3f

Waiting for task to start..... done.

  [####################################]  100%  Starting VM

SUCCESS: VM "test2" with profile "std-large" has been provisioned and started successfully
```

The administrator can also specify whether or not to automatically define and start the VM when launching a provisioner job, using the `--define`/`--no-define` and `--start`/`--no-start` options. The default is to define and start a VM. `--no-define` implies `--no-start` as there would be no VM to start. Using `--no-start` can be useful if other tasks must be performed before starting the VM for the first time, and `--no-define` can be useful for creating "template" VMs which would then be cloned by other profiles.

```
$ pvc provisioner create test3 std-large --no-define
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

Task ID: 43d57a2d-8d0d-42f6-90df-cc39956825a9
```

Finally, the administrator may specify further, one-time script arguments at install time, to further tune the VM installation (e.g. setting an FQDN or some conditional to trigger additional steps in the script).

```
$ pvc provisioner create test4 std-large --script-arg vm_fqdn=testhost.example.tld --script-arg my_foo=True
Using cluster "local" - Host: "10.0.0.1:7370"  Scheme: "http"  Prefix: "/api/v1"

Task ID: 39639f8c-4866-49de-8c51-4179edec0194
```

**NOTE**: A VM that is set to do so will be defined on the cluster early in the provisioning process, before creating disks or executing the provisioning script, with the special status `provision`. Once completed, if the VM is not set to start automatically, the state will remain `provision`, with the VM not running, until its state is explicitly changed with the client (or via autostart when its node returns to `ready` state).

**NOTE**: Provisioning jobs are tied to the node that spawned them. If the primary node changes, provisioning jobs will continue to run against that node until they are completed, interrupted, or fail, but the active API (now on the new primary node) will not have access to any status data from these jobs, until the primary node status is returned to the original host. The CLI will warn the administrator of this if there are active jobs while running `node primary` or `node secondary` commands.

**NOTE**: Provisioning jobs cannot be cancelled, either before they start or during execution. The administrator should always let an invalid job either complete or fail out automatically, then remove the erroneous VM with the `vm remove` command.

# Deploying VMs from OVA images

PVC supports deploying virtual machines from industry-standard OVA images. OVA images can be uploaded to the cluster with the `pvc provisioner ova` commands, and deployed via the created profile(s) using the `pvc provisioner create` command detailed above for scripted installs; the process is the same in both cases. Additionally, the profile(s) can be modified to suite your specific needs after creation.

## Uploading an OVA

Once the OVA is uploaded to the cluster with the `pvc provisioner ova upload` command, it will be visible in two different places:

* In `pvc provisioner ova list`, one can see all uploaded OVA images as well as details on their disk configurations.

* In `pvc profile list`, a new profile will be visible which matches the OVA `NAME` from the upload. This profile will have a "Source" of `OVA <NAME>`, and a system template of the same name. This system template will contain the basic configuration of the VM. You may notice that the other templates and data are set to `N/A`. For full details on this, see the next section.

## The OVA Provisioner Script

OVA installs leverage a special provisioner script to handle the VM creation, identical to any other provisioner profile type. This (example) script, or a replacement, must be installed prior to uploading an OVA, and handles the actual VM configuration creation and cloning of the OVA volumes.

## OVA limitations

PVC does not implement a *complete* OVA framework. While all basic elements of the OVA are included, the following areas require special attention.

### Networks

Because the PVC provisioner has its own conception of networks separate from the OVA profiles, the administrator must perform this mapping themselves, by first creating a network template, and the required networks on the PVC cluster, and then modifying the profile of the resulting OVA.

The provisioner profile for the OVA can be safely modified to include this new network template at any time, and the resulting VM will be provisioned with these networks.

This setup was chosen specifically to eliminate corner cases. Most OVA images include a single, "default" network interface, and expect the administrator of the hypervisor to modify this later. You can of course do this, but since PVC has its own conception of networks already in the provisioner, it makes more sense to ignore what the OVA specifies, and allow the administrator full control over this portion of the VM config, before deployment. It is thus always important to be aware of the network requirements of your OVA images, especially if they require specific network configurations, and then create a network template to match.

### Storage

During import, PVC splits the OVA into its constituent parts, including any disk images (usually VMDK-formatted). It will then create a separate PVC storage volume for each disk image. These storage volumes are then converted at deployment time from the VMDK format to the PVC native raw format based on their included size in the OVA. Once the storage volume for an actual VM deployment is created, it can then be resized as needed.

Because of this, OVA profiles do not include storage templates like other PVC profiles. A storage template can still be added to such a profile, and the block devices will be added after the main block devices. However, this is generally not recommended; it is far better to modify the OVA to add additional volume(s) before uploading it instead.

**WARNING**: Never adjust the sizes of the OVA VMDK-formatted storage volumes (named `ova_<NAME>_sdX`) or remove them without removing the OVA itself in the provisioner; doing so will prevent the deployment of the OVA, specifically the conversion of the images to raw format at deploy time, and render the OVA profile useless.
