# Getting started - deploying a Parallel Virtual Cluster

PVC aims to be easy to deploy, letting you get on with managing your cluster in just a few hours at most. Once initial setup is complete, the cluster is generally self-managing and can be interfaces with directly from the clients.

This guide will walk you through setting up a simple 3-node PVC cluster from scratch, ending with a fully-usable cluster ready to provision virtual machines. Note that all domains, IP addresses, etc. used are examples - when following this guide, be sure to modify the commands and configurations to suit your needs.

### Part One - Prepararing for bootstrap

0. Download the latest copy of the [`pvc-installer`](https://github.com/parallelvirtualcluster/pvc-installer) and [`pvc-ansible`](https://github.com/parallelvirtualcluster/pvc-ansible) repositories to your local machine.

0. In `pvc-ansible`, create an initial `hosts` inventory, using `hosts.default` as a template. You can manage multiple PVC clusters ("sites") from the Ansible repository easily, however for simplicity you can use the simple name `cluster` for your initial site. Define the 3 hostnames you will use under the site group; usually the provided names of `pvchv1`, `pvchv2`, and `pvchv3` are sufficient, though you may use any hostname pattern you wish. It is *very important* that the names all contain a sequential number, however, as this is used by various components.

0. In `pvc-ansible`, create an initial set of `group_vars`, using the `group_vars/default` as a template. Inside these group vars are two main files:``base.yml` and `pvc.yml`. These example files are well-documented; read them carefully and specify all required options before proceeding.

    `base.yml` configures the `base` role and some common per-cluster configurations such as an upstream domain, a root password, and a set of administrative users, as well as and most importantly, the basic network configuration of the nodes. Make special note of the various items that must be generated such as passwords; these should all be cluster-unique.

    `pvc.yml` configures the `pvc` role, including all the dependent software and PVC itself. Important to note is the `pvc_nodes` list, which contains a list of all the nodes as well as per-node configurations for each. All nodes, both coordinator and not, must be a part of this list.

0. Optionally though strongly recommended, move your new configurations out of the `pvc-ansible` repository. The `.gitignore` file will ignore all non-default data, so it is advisable to move these configurations to a separate, secure, repository or filestore, and symlink to them inside the `pvc-ansible` repository directories. The three important locations to symlink are:  
    * `hosts`: The main Ansible inventory for the various clusters.
    * `group_vars/<cluster_name>`: The `group_vars` for the various clusters.
    * `files/<cluster_name>`: Static files, created during the bootstrap Ansible run, for the various clusters.

0. In `pvc-installer`, run the `buildiso.sh` script to generate an installer ISO. This script requires `debootstrap`, `isolinux`, and `xorriso` to function. The resulting file will, by default, be named `pvc-installer.iso` in the current directory.

### Part Two - Preparing and installing the physical hosts

0. Prepare 3 physical servers with IPMI. These physical servers should have at the least a system disk (a single disk, hardware RAID1, or similar), one or more data (Ceph OSD) disks, and networking/CPU/RAM suitable for the cluster needs. Connect their networking based on the configuration set in the `pvc-ansible` `group_vars/base.yml` file.

0. Configure the IPMI user specified in the `pvc-ansible` `group_vars/base.yml` file with the required permissions; this user will be used to reboot the host if it fails, so it must be able to control system power state.

0. Load the installer ISO generated in step 5 of the previous section onto a USB stick, or using IPMI virtual media, on the physical servers.

0. Boot the physical servers off of the installer ISO, in UEFI mode if available for maximum flexibility.

0. Follow the prompts from the installer ISO. It will ask for a hostname, the system disk device to use, the initial network interface to configure as well as either DHCP or static IP information, and finally either an HTTP URL containing an SSH `authorized_keys` to use for the `deploy` user, or a password for this user if key auth is unavailable.

0. Wait for the installer to complete. It will provide some next steps at the end, and wait for the administrator to acknowledge via an "Enter" keypress. The node will now reboot into the base PVC system.

0. Repeat the above steps for all 3 initial nodes. On boot, they will display their configured IP address to be used in the next steps.

### Part Three - Initial bootstrap with Ansible

0. Make note of the IP addresses of all 3 initial nodes, and configure DNS, `/etc/hosts`, or Ansible `ansible_host=` hostvars to map these IP addresses to the hostnames set in the Ansible `hosts` and `group_vars` files.

0. Verify connectivity from your administrative host to the 3 initial nodes, including SSH access. Accept their host keys as required before proceeding as Ansible does not like those prompts.

0. Verify your `group_vars` setup from part one, as errors here may require a reinstallation and restart of the bootstrap process.

0. Perform the initial bootstrap. From the `pvc-ansible` repository directory, execute the following `ansible-playbook` command, replacing `<cluster_name>` with the Ansible group name from the `hosts` file. Make special note of the additional `bootstrap=yes` variable, which tells the playbook that this is an initial bootstrap run.
    `$ ansible-playbook -v -i hosts pvc.yml -l <cluster_name> -e bootstrap=yes`

0. Wait for the Ansible playbook run to finish. Once completed, the cluster bootstrap will be finished, and all 3 nodes will have rebooted into a working PVC cluster.

0. Install the CLI client on your administrative host, and verify connectivity to the cluster, for instance by running the following command, which should show all 3 nodes as present and running:  
    `$ pvc -z pvchv1:2181,pvchv2:2181,pvchv3:2181 node list`

0. Optionally, verify the API is listening on the `upstream_floating_ip` address configured in the cluster `group_vars`, for instance by running the following command which shows, in JSON format, the same information as in the previous step:  
    `$ curl -X GET http://<upstream_floating_ip>:7370/api/v1/node`

### Part Four - Configuring the Ceph storage cluster

All steps in this section can be performed using either the CLI client or the HTTP API; for clarity, only the CLI commands are shown.

0. Determine the Ceph OSD block devices on each host, via an `ssh` shell. For instance, check `/dev/disk/by-path` to show the block devices by their physical SAS/SATA bus location, and obtain the relevant `/dev/sdX` name for each disk you wish to be a Ceph OSD on each host.

0. Add each OSD device to each host. The general command is:  
    `$ pvc ceph osd add --weight <weight> <node> <device>`

   For example, if each node has two data disks, as `/dev/sdb` and `/dev/sdc`, run the commands as follows:  
    `$ pvc ceph osd add --weight 1.0 pvchv1 /dev/sdb`  
    `$ pvc ceph osd add --weight 1.0 pvchv1 /dev/sdc`  
    `$ pvc ceph osd add --weight 1.0 pvchv2 /dev/sdb`  
    `$ pvc ceph osd add --weight 1.0 pvchv2 /dev/sdc`   
    `$ pvc ceph osd add --weight 1.0 pvchv3 /dev/sdb`  
    `$ pvc ceph osd add --weight 1.0 pvchv3 /dev/sdc`   

   *NOTE:* On the CLI, the `--weight` argument is optional, and defaults to `1.0`. In the API, it must be specified explicitly. OSD weights determine the relative amount of data which can fit onto each OSD. Under normal circumstances, you would want all OSDs to be of identical size, and hence all should have the same weight. If your OSDs are instead different sizes, the weight should be proportial to the size, e.g. `1.0` for a 100GB disk, `2.0` for a 200GB disk, etc. For more details, see the Ceph documentation.

   *NOTE:* OSD commands wait for the action to complete on the node, and can take some time (up to 30s normally). Be cautious of HTTP timeouts when using the API to perform these steps.

0. Verify that the OSDs were added and are functional (`up` and `in`):  
    `$ pvc ceph osd list`

0. Create an RBD pool to store VM images on. The general command is:
    `$ pvc ceph pool add <name> <placement_groups>`

   For example, to create a pool named `vms` with 256 placement groups (a good default with 6 OSD disks), run the command as follows:  
    `$ pvc ceph pool add vms 256`

   *NOTE:* Ceph placement groups are a complex topic; as a general rule it's easier to grow than shrink, so start small and grow as your cluster grows. For more details see the Ceph documentation and the [placement group calculator](https://ceph.com/pgcalc/).

   *NOTE:* All PVC RBD pools use `copies=3` and `mincopies=2` for data storage. This provides, for each object, 3 copies of the data, with writes being accepted with 1 degraded copy. This provides maximum resiliency against single-node outages, but will use 3x the amount of storage for each unit stored inside the image. Take this into account when sizing OSD disks and VM images. This cannot be changed as any less storage will result in a non-HA cluster that could not handle a single node failure.

0. Verify that the pool was added:  
    `$ pvc ceph pool list`

### Part Five - Creating virtual networks

0. Determine a domain name, IPv4, and/or IPv6 network for your first client network, and any other client networks you may wish to create. For this guide we will create a single "managed" virtual client network with DHCP.

0. Create the virtual network. The general command for an IPv4-only network with DHCP is:  
    `$ pvc network add <vni_id> --type <type> --description <spaceless_description> --domain <domain> --ipnet <ipv4_network_in_CIDR> --gateway <ipv4_gateway_address> --dhcp --dhcp-start <first_address> --dhcp-end <last_address>`

   For example, to create the managed (EVPN VXLAN) network `100` with subnet `10.100.0.0/24`,  gateway `.1` and DHCP from `.100` to `.199`, run the command as follows:  
    `$ pvc network add 100 --type managed --description my-managed-network --domain myhosts.local --ipnet 10.100.0.0/24 --gateway 10.100.0.1 --dhcp --dhcp-start 10.100.0.100 --dhcp-end 10.100.0.199`

   For another example, to create the static bridged (switch-configured, tagged VLAN, with no PVC management of IPs) network `200`, run the command as follows:  
    `$ pvc network add 200 --type bridged --description my-bridged-network`

0. Verify that the network(s) were added:  
    `$ pvc network list`

0. On the upstream router, configure one of:

    a) A BGP neighbour relationship with the `upstream_floating_address` to automatically learn routes.

    b) Static routes for the configured client IP networks towards the `upstream_floating_address`.

0. On the upstream router, if required, configure NAT for the configured client IP networks.

0. Verify the client networks are reachable by pinging the managed gateway from outside the cluster.

### Part Six - Setting nodes ready and deploying a VM

This section walks through deploying a simple Debian VM to the cluster with Debootstrap. Note that as of PVC version `0.5`, this is still a manual process, though automated deployment of VMs based on configuration templates and image snapshots is planned for version `0.6`. This section can be used as a basis for a scripted installer, or a manual process as the administrator sees fit.

0. Set all 3 nodes to `ready` state, allowing them to run virtual machines. The general command is:  
    `$ pvc node ready <node>`

0. Create an RBD image for the VM. The general command is:  
    `$ pvc ceph volume add <pool> <name> <size>

   For example, to create a 20GB disk for a VM called `test1` in the previously-configured pool `vms`, run the command as follows:  
    `$ pvc ceph volume add vms test1_disk0 20G`

0. Verify the RBD image was created:  
    `$ pvc ceph volume list`

0. On one of the PVC nodes, for example `pvchv1`, map the RBD volume to the local system:  
    `$ ceph rbd map vms/test1_disk0`

   The resulting disk device will be available at `/dev/rbd/vms/test1_disk0` or `/dev/rbd0`.

0. Create a filesystem on the block device, for example `ext4`:  
    `$ mkfs -t ext4 /dev/rbd/vms/test1_disk0`

0. Create a temporary directory and mount the block device to it, using `mount` to find the directory:  
    `$ mount /dev/rbd/vms/test1_disk0 $( mktemp -d )`  
    `$ mount | grep rbd`

0. Run a `debootstrap` installation to the volume:
    `$ debootstrap buster <temporary_mountpoint> http://ftp.mirror.debian.org/debian`

0. Bind mount the various required directories to the new system:  
    `$ mount --bind /dev <temporary_mountpoint>/dev`  
    `$ mount --bind /dev/pts <temporary_mountpoint>/dev/pts`  
    `$ mount --bind /proc <temporary_mountpoint>/proc`  
    `$ mount --bind /sys <temporary_mountpoint>/sys`  
    `$ mount --bind /run <temporary_mountpoint>/run`  

0. Using `chroot`, configure the VM system as required, for instance installing packages or adding users:  
    `$ chroot <temporary_mountpoint>`  
    `[chroot]$ ...`

0. Install the GRUB bootloader in the VM system, and install Grub to the RBD device:  
    `[chroot]$ apt install grub-pc`  
    `[chroot]$ grub-install /dev/rbd/vms/test1_disk0`

0. Exit the `chroot` environment, unmount the temporary mountpoint, and unmap the RBD device:  
    `[chroot]$ exit`  
    `$ umount <temporary_mountpoint>`
    `$ rbd unmap /dev/rd0`

0. Prepare a Libvirt XML configuration, obtaining the required Ceph storage secret and a new random VM UUID first. This example provides a very simple VM with 1 vCPU, 1GB RAM, the previously-configured network `100`, and the previously-configured disk `vms/test1_disk0`:  
    `$ virsh secret-list`
	`$ uuidgen`
    `$ $EDITOR /tmp/test1.xml`

    ```
<domain type='kvm'>
  <name>test1</name>
  <uuid>[INSERT GENERATED UUID]</uuid>
  <description>Testing VM</description>
  <memory unit='MiB'>1024</memory>
  <vcpu>1</vcpu>
  <os>
    <type arch='x86_64' machine='pc-i440fx-2.7'>hvm</type>
    <boot dev='hd'/>
  </os>
  <features>
    <acpi/>
    <apic/>
    <pae/>
  </features>
  <clock offset='utc'/>
  <on_poweroff>destroy</on_poweroff>
  <on_reboot>restart</on_reboot>
  <on_crash>restart</on_crash>
  <devices>
    <emulator>/usr/bin/kvm</emulator>
    <controller type='usb' index='0'/>
    <controller type='pci' index='0' model='pci-root'/>
    <serial type='pty'/>
    <console type='pty'/>
    <disk type='network' device='disk'>
      <driver name='qemu' discard='unmap'/>
      <auth username='libvirt'>
         <secret type='ceph' uuid='[INSERT CEPH STORAGE SECRET]'/>
      </auth>
      <source protocol='rbd' name='vms/test1_disk0'>
        <host name='[INSERT FIRST COORDINATOR CLUSTER NETWORK FQDN' port='6789'/>
        <host name='[INSERT FIRST COORDINATOR CLUSTER NETWORK FQDN' port='6789'/>
        <host name='[INSERT FIRST COORDINATOR CLUSTER NETWORK FQDN' port='6789'/>
      </source>
      <target dev='sda' bus='scsi'/>
    </disk>
    <interface type='bridge'>
      <mac address='52:54:00:12:34:56'/>
      <source bridge='vmbr100'/>
      <model type='virtio'/>
    </interface>
    <controller type='scsi' index='0' model='virtio-scsi'/>
  </devices>
</domain>
    ```

    *NOTE:* This Libvirt XML is only a sample; it should be modified to fit the specifics of the VM. Alternatively to manual configuration, one can use a tool like `virt-manager` to generate valid Libvirt XML configurations for PVC to use.

0. Define the VM in the PVC cluster:  
    `$ pvc vm define /tmp/test1.xml`

0. Verify the VM is present in the cluster:
    `$ pvc vm info test1`

0. Start the VM and watch the console log:
    `$ pvc vm start test1`  
    `$ pvc vm log -f test1`

If all has gone well until this point, you should now be able to watch your new VM boot on the cluster, grab DHCP from the managed network, and run away doing its thing. You could now, for instance, move it permanently to another node with the `pvc vm move -t <node> test1` command, or temporarily with the `pvc vm migrate -t <node> test1` command and back again with the `pvc vm unmigrate test` command.

For more details on what to do next, see the [CLI manual](/manuals/cli) for a full list of management functions, SSH into your new VM, and start provisioning more. Your new private cloud is now here!
