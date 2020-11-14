# Getting started - deploying a Parallel Virtual Cluster

PVC aims to be easy to deploy, letting you get on with managing your cluster in just a few hours at most. Once initial setup is complete, the cluster is managed via the clients, though the Ansible framework is used to add, remove, or modify nodes as required.

This guide will walk you through setting up a simple 3-node PVC cluster from scratch, ending with a fully-usable cluster ready to provision virtual machines. Note that all domains, IP addresses, etc. used are examples - when following this guide, be sure to modify the commands and configurations to suit your needs.

### Part One - Preparing for bootstrap

0. Read through the [Cluster Architecture documentation](/architecture/cluster). This documentation details the requirements and conventions of a PVC cluster, and is important to understand before proceeding.

0. Download the latest copy of the [`pvc-installer`](https://github.com/parallelvirtualcluster/pvc-installer) and [`pvc-ansible`](https://github.com/parallelvirtualcluster/pvc-ansible) repositories to your local machine.

0. In `pvc-ansible`, create an initial `hosts` inventory, using `hosts.default` as a template. You can manage multiple PVC clusters ("sites") from the Ansible repository easily, however for simplicity you can use the simple name `cluster` for your initial site. Define the 3 hostnames you will use under the site group; usually the provided names of `pvchv1`, `pvchv2`, and `pvchv3` are sufficient, though you may use any hostname pattern you wish. It is *very important* that the names all contain a sequential number, however, as this is used by various components.

0. In `pvc-ansible`, create an initial set of `group_vars`, using the `group_vars/default` as a template. Inside these group vars are two main files: `base.yml` and `pvc.yml`. These example files are well-documented; read them carefully and specify all required options before proceeding.

    `base.yml` configures the `base` role and some common per-cluster configurations such as an upstream domain, a root password, and a set of administrative users, as well as and most importantly, the basic network configuration of the nodes. Make special note of the various items that must be generated such as passwords; these should all be cluster-unique.

    `pvc.yml` configures the `pvc` role, including all the dependent software and PVC itself. Important to note is the `pvc_nodes` list, which contains a list of all the nodes as well as per-node configurations for each. All nodes, both coordinator and not, must be a part of this list.

0. Optionally though strongly recommended, move your new configurations out of the `pvc-ansible` repository. The `.gitignore` file will ignore all non-default data, so it is advisable to move these configurations to a separate, secure, repository or filestore, and symlink to them inside the `pvc-ansible` repository directories. The three important locations to symlink are:  
    * `hosts`: The main Ansible inventory for the various clusters.
    * `group_vars/<cluster_name>`: The `group_vars` for the various clusters.
    * `files/<cluster_name>`: Static files, created during the bootstrap Ansible run, for the various clusters.

0. In `pvc-installer`, run the `buildiso.sh` script to generate an installer ISO. This script requires `debootstrap`, `isolinux`, and `xorriso` to function. The resulting file will, by default, be named `pvc-installer_<date>.iso` in the current directory. For additional options, use the `-h` flag to show help information for the script.

### Part Two - Preparing and installing the physical hosts

0. Prepare 3 physical servers with IPMI. These physical servers should have at the least a system disk (a single disk, hardware RAID1, or similar), one or more data (Ceph OSD) disks, and networking/CPU/RAM suitable for the cluster needs. Connect their networking based on the configuration set in the `pvc-ansible` `group_vars/base.yml` file.

0. Configure the IPMI user specified in the `pvc-ansible` `group_vars/base.yml` file with the required permissions; this user will be used to reboot the host if it fails, so it must be able to control system power state.

0. Configure IPMI to enable IPMI over LAN. Use the default (all-zero) encryption key; this is needed for fencing to work. Verify that IPMI over LAN is operating by using the following command from a machine able to reach the IPMI interface:  
    `/usr/bin/ipmitool -I lanplus -H <IPMI_host> -U <user> -P <password> chassis power status`

0. Load the installer ISO generated in step 5 of the previous section onto a USB stick, or using IPMI virtual media, on the physical servers.

0. Boot the physical servers off of the installer ISO, in UEFI mode if available for maximum flexibility.

0. Follow the prompts from the installer ISO. It will ask for a hostname, the system disk device to use, the initial network interface to configure as well as either DHCP or static IP information, and finally either an HTTP URL containing an SSH `authorized_keys` to use for the `deploy` user, or a password for this user if key auth is unavailable.

0. Wait for the installer to complete. It will provide some next steps at the end, and wait for the administrator to acknowledge via an "Enter" key-press. The node will now reboot into the base PVC system.

0. Repeat the above steps for all 3 initial nodes. On boot, they will display their configured IP address to be used in the next steps.

### Part Three - Initial bootstrap with Ansible

0. Make note of the IP addresses of all 3 initial nodes, and configure DNS, `/etc/hosts`, or Ansible `ansible_host=` hostvars to map these IP addresses to the hostnames set in the Ansible `hosts` and `group_vars` files.

0. Verify connectivity from your administrative host to the 3 initial nodes, including SSH access. Accept their host keys as required before proceeding as Ansible does not like those prompts.

0. Verify your `group_vars` setup from part one, as errors here may require a re-installation and restart of the bootstrap process.

0. Perform the initial bootstrap. From the `pvc-ansible` repository directory, execute the following `ansible-playbook` command, replacing `<cluster_name>` with the Ansible group name from the `hosts` file. Make special note of the additional `bootstrap=yes` variable, which tells the playbook that this is an initial bootstrap run.  
    `$ ansible-playbook -v -i hosts pvc.yml -l <cluster_name> -e bootstrap=yes`

    **WARNING:** Never rerun this playbook with the `-e bootstrap=yes` option against an active cluster. This will have unintended, disastrous consequences.

0. Wait for the Ansible playbook run to finish. Once completed, the cluster bootstrap will be finished, and all 3 nodes will have rebooted into a working PVC cluster.

0. Install the CLI client on your administrative host, and add and verify connectivity to the cluster; this will also verify that the API is working. You will need to know the cluster upstream floating IP address here, and if you configured SSL or authentication for the API in your `group_vars`, adjust the first command as needed (see `pvc cluster add -h` for details).  
    `$ pvc cluster add -a <upstream_floating_ip> mycluster`
    `$ pvc -c mycluster node list`
    We can also set a default cluster by exporting the `PVC_CLUSTER` environment variable to avoid requiring `-c cluster` with every subsequent command:  
    `$ export PVC_CLUSTER="mycluster"`

### Part Four - Configuring the Ceph storage cluster

0. Determine the Ceph OSD block devices on each host, via an `ssh` shell. For instance, use `lsblk` or check `/dev/disk/by-path` to show the block devices by their physical SAS/SATA bus location, and obtain the relevant `/dev/sdX` name for each disk you wish to be a Ceph OSD on each host.

0. Add each OSD device to each host. The general command is:  
    `$ pvc storage osd add --weight <weight> <node> <device>`

    For example, if each node has two data disks, as `/dev/sdb` and `/dev/sdc`, run the commands as follows:  
    `$ pvc storage osd add --weight 1.0 pvchv1 /dev/sdb`  
    `$ pvc storage osd add --weight 1.0 pvchv1 /dev/sdc`  
    `$ pvc storage osd add --weight 1.0 pvchv2 /dev/sdb`  
    `$ pvc storage osd add --weight 1.0 pvchv2 /dev/sdc`   
    `$ pvc storage osd add --weight 1.0 pvchv3 /dev/sdb`  
    `$ pvc storage osd add --weight 1.0 pvchv3 /dev/sdc`   

    **NOTE:** On the CLI, the `--weight` argument is optional, and defaults to `1.0`. In the API, it must be specified explicitly, but the CLI sets a default value. OSD weights determine the relative amount of data which can fit onto each OSD. Under normal circumstances, you would want all OSDs to be of identical size, and hence all should have the same weight. If your OSDs are instead different sizes, the weight should be proportional to the size, e.g. `1.0` for a 100GB disk, `2.0` for a 200GB disk, etc. For more details, see the Ceph documentation.

    **NOTE:** OSD commands wait for the action to complete on the node, and can take some time.

    **NOTE:** You can add OSDs in any order you wish, for instance you can add the first OSD to each node and then add the second to each node, or you can add all nodes' OSDs together at once like the example. This ordering does not affect the cluster in any way.

0. Verify that the OSDs were added and are functional (`up` and `in`):  
    `$ pvc storage osd list`

0. Create an RBD pool to store VM images on. The general command is:  
    `$ pvc storage pool add <name> <placement_groups>`

    For example, to create a pool named `vms` with 256 placement groups (a good default with 6 OSD disks), run the command as follows:  
    `$ pvc storage pool add vms 256`

    **NOTE:** Ceph placement groups are a complex topic; as a general rule it's easier to grow than shrink, so start small and grow as your cluster grows. The general formula is to calculate the ideal number of PGs is `pgs * maxcopies / osds = ~250`, then round `pgs` down to the closest power of 2; generally, you want as close to 250 PGs per OSD as possible, but no more than 250. With 3-6 OSDs, 256 is a good number, and with 9+ OSDs, 512 is a good number. Ceph will error if the total number exceeds the limit. For more details see the Ceph documentation and the [placement group calculator](https://ceph.com/pgcalc/).

    **NOTE:** As detailed in the [cluster architecture documentation](/cluster-architecture), you can also set a custom replica configuration for each pool if the default of 3 replica copies with 2 minimum copies is not acceptable. See `pvc storage pool add -h` or that document for full details.

0. Verify that the pool was added:  
    `$ pvc storage pool list`

### Part Five - Creating virtual networks

0. Determine a domain name and IPv4, and/or IPv6 network for your first client network, and any other client networks you may wish to create. These networks should never overlap with the cluster networks. For full details on the client network types, see the [cluster architecture documentation](/cluster-architecture).

0. Create the virtual network. There are many options here, so see `pvc network add -h` for details.  

    For example, to create the managed (EVPN VXLAN) network `100` with subnet `10.100.0.0/24`,  gateway `.1` and DHCP from `.100` to `.199`, run the command as follows:  
    `$ pvc network add 100 --type managed --description my-managed-network --domain myhosts.local --ipnet 10.100.0.0/24 --gateway 10.100.0.1 --dhcp --dhcp-start 10.100.0.100 --dhcp-end 10.100.0.199`

    For another example, to create the static bridged (switch-configured, tagged VLAN, with no PVC management of IPs) network `200`, run the command as follows:  
    `$ pvc network add 200 --type bridged --description my-bridged-network`

    **NOTE:** Network descriptions cannot contain spaces or special characters; keep them short, sweet, and dash or underscore delimited.

0. Verify that the network(s) were added:  
    `$ pvc network list`

0. On the upstream router, configure one of:

    a) A BGP neighbour relationship with the cluster upstream floating address to automatically learn routes.

    b) Static routes for the configured client IP networks towards the cluster upstream floating address.

0. On the upstream router, if required, configure NAT for the configured client IP networks.

0. Verify the client networks are reachable by pinging the managed gateway from outside the cluster.


### You're Done!

0. Set all 3 nodes to `ready` state, allowing them to run virtual machines. The general command is:  
    `$ pvc node ready <node>`

Congratulations, you now have a basic PVC storage cluster, ready to run your VMs.

For next steps, see the [Provisioner manual](/manuals/provisioner) for details on how to use the PVC provisioner to create new Virtual Machines, as well as the [CLI manual](/manuals/cli) and [API manual](/manuals/api) for details on day-to-day usage of PVC.
