# PVC Ansible architecture

The PVC Ansible setup and management framework is written in Ansible. It consists of two roles: `base` and `pvc`.

## Base role

The Base role configures a node to a specific, standard base Debian system, with a number of PVC-specific tweaks. Some examples include:

* Installing the custom PVC repository hosted at Boniface Labs.

* Removing several unnecessary packages and installing numerous additional packages.

* Automatically configuring network interfaces based on the `group_vars` configuration.

* Configuring several general `sysctl` settings for optimal performance.

* Installing and configuring rsyslog, postfix, ntpd, ssh, and fail2ban.

* Creating the users specified in the `group_vars` configuration.

* Installing custom MOTDs, bashrc files, vimrc files, and other useful configurations for each user.

The end result is a standardized "PVC node" system ready to have the daemons installed by the PVC role.

The Base role is optional: if an administrator so chooses, they can bypass this role and configure things manually. That said, for the proper functioning of the PVC role, the Base role should always be applied first.

## PVC role

The PVC role configures all the dependencies of PVC, including storage, networking, and databases, then installs the PVC daemon itself. Specifically, it will, in order:

* Install Ceph, configure and bootstrap a new cluster if `bootstrap=yes` is set, configure the monitor and manager daemons, and start up the cluster ready for the addition of OSDs via the client interface (coordinators only).

* Install, configure, and if `bootstrap=yes` is set, bootstrap a Zookeeper cluster (coordinators only).

* Install, configure, and if `bootstrap=yes` is set, bootstrap a Patroni PostgreSQL cluster for the PowerDNS aggregator (coordinators only).

* Install and configure Libvirt.

* Install and configure FRRouting.

* Install and configure the main PVC daemon and API client.

* If `bootstrap=yes` is set, initialize the PVC cluster (`pvc task init`).

## Completion

Once the entire playbook has run for the first time against a given host, the host will be rebooted to apply all the configured services. On startup, the system should immediately launch the PVC daemon, check in to the Zookeeper cluster, and become ready. The node will be in `flushed` state on its first boot; the administrator will need to run `pvc node unflush <node>` to set the node into active state ready to handle virtual machines. On the first bootstrap run, the administrator will also have to configure storage block devices (OSDs), networks, etc. For full details, see [the main getting started page](/getting-started).

## General usage

### Initial setup

After cloning the `pvc-ansible` repo, set up a set of configurations for your cluster. One copy of the `pvc-ansible` repository can manage an unlimited number of clusters with differing configurations.

All files created during initial setup should be stored outside the `pvc-ansible` repository, as they will be ignored by the main Git repository by default. It is recommended to set up a separate folder, either standalone or as its own Git repository, to contain your files, then symlink them back into the main repository at the appropriate places outlined below.

Create a `hosts` file containing the clusters as groups, then the list of hosts within each cluster group. The `hosts.default` file can be used as a template.

Create a `files/<cluster>` folder to hold the cluster-created static configuration files. Until the first bootstrap run, this directory will be empty.

Create a `group_vars/<cluster>` folder to hold the cluster configuration variables. The `group_vars/default` directory can be used as an example.

### Bootstrapping a cluster

Before bootstrapping a cluster, see the section on [PVC Ansible configuration variables](/manuals/ansible/#pvc-ansible-configuration-variables) to configure the cluster.

Bootstrapping a cluster can be done using the main `pvc.yml` playbook. Generally, a bootstrap run should be limited to the coordinators of the cluster to avoid potential race conditions or strange bootstrap behaviour. The special variable `bootstrap=yes` must be set to indicate that a cluster bootstrap is to be requested.

**WARNING:** Do not run the playbook with `bootstrap=yes` *except during the very first run against a freshly-installed set of coordinator nodes*. Running it against an existing cluster will result in the complete failure of the cluster, the destruction of all data, or worse.

### Adding new nodes

Adding new nodes to an existing cluster can be done using the main `pvc.yml` playbook. The new node(s) should be added to the `group_vars` configuration `node_list`, then the playbook run against all hosts in the cluster with no special flags or limits. This will ensure the entire cluster is updated with the new information, while simultaneously configuring the new node.

### Reconfiguration and software updates

For general, day-to-day software updates such as base system updates or upgrading to newer PVC versions, a special playbook, `oneshot/update-pvc-cluster.yml`, is provided. This playbook will gracefully update and upgrade all PVC nodes in the cluster, flush them, reboot them, and then unflush them. This operation should be completely transparent to VMs on the cluster.

For more advanced updates, such as changing configurations in the `group_vars`, the main `pvc.yml` playbook can be used to deploy the changes across all hosts. Note that this may cause downtime due to node reboots if certain configurations change, and it is not recommended to use this process frequently.

# PVC Ansible configuration manual

This manual documents the various `group_vars` configuration options for the `pvc-ansible` framework. We assume that the administrator is generally familiar with Ansible and its operation.

## PVC Ansible configuration variables

The `group_vars` folder contains configuration variables for all clusters managed by your local copy of `pvc-ansible`. Each cluster has a distinct set of `group_vars` to allow different configurations for each cluster.

This section outlines the various configuration options available in the `group_vars` configuration; the `group_vars/default` directory contains an example set of variables, split into two files (`base.yml` and `pvc.yml`), that set every listed configuration option. 

### Conventions

* Settings may be `required`, `optional`, or `ignored`. Ignored settings are used for human-readability in the configuration but are ignored by the actual role.

* Settings may `depends` on other settings. This indicates that, if one setting is enabled, the other setting is very likely `required` by that setting.

* If a particular `<setting>` is marked `optional`, and a latter setting is marked `depends on <setting>`, the latter is ignored unless the `<setting>` is specified.

### `base.yml`

Example configuration:

```
---
cluster_group: mycluster
timezone_location: Canada/Eastern
local_domain: upstream.local
recursive_dns_servers:
  - 8.8.8.8
  - 8.8.4.4
recursive_dns_search_domains:
  - "{{ local_domain }}"

username_ipmi_host: "pvc"
passwd_ipmi_host: "MyPassword2019"

passwd_root: MySuperSecretPassword   # Not actually used by the playbook, but good for reference
passwdhash_root: "$6$shadowencryptedpassword"

logrotate_keepcount: 7
logrotate_interval: daily

username_email_root: root

hosts:
  - name: testhost
    ip: 127.0.0.1

admin_users:
  - name: "myuser"
    uid: 500
    keys:
      - "ssh-ed25519 MyKey 2019-06"

networks:
  "bondU":
    device: "bondU"
    type: "bond"
    bond_mode: "802.3ad"
    bond_devices:
      - "enp1s0f0"
      - "enp1s0f1"
    mtu: 9000

  "upstream":
    device: "vlan1000"
    type: "vlan"
    raw_device: "bondU"
    mtu: 1500
    domain: "{{ local_domain }}"
    subnet: "192.168.100.0/24"
    floating_ip: "192.168.100.10/24"
    gateway_ip: "192.168.100.1"

  "cluster":
    device: "vlan1001"
    type: "vlan"
    raw_device: "bondU"
    mtu: 1500
    domain: "pvc-cluster.local"
    subnet: "10.0.0.0/24"
    floating_ip: "10.0.0.254/24"

  "storage":
    device: "vlan1002"
    type: "vlan"
    raw_device: "bondU"
    mtu: 9000
    domain: "pvc-storage.local"
    subnet: "10.0.1.0/24"
    floating_ip: "10.0.1.254/24"
```

#### `cluster_group`

* *required*

The name of the Ansible PVC cluster group in the `hosts` inventory.

#### `timezone_location`

* *required*

The TZ database format name of the local timezone, e.g. `America/Toronto` or `Canada/Eastern`.

#### `local_domain`

* *required*

The domain name of the PVC cluster nodes. This is the domain portion of the FQDN of each node, and should usually be the domain of the `upstream` network.

#### `recursive_dns_servers`

* *optional*

A list of recursive DNS servers to be used by cluster nodes. Defaults to Google Public DNS if unspecified.

#### `recursive_dns_search_domains`

* *optional*

A list of domain names (must explicitly include `local_domain` if desired) to be used for shortname DNS lookups.

#### `username_ipmi_host`

* *optional*
* *requires* `passwd_ipmi_host`

The IPMI username used by PVC to communicate with the node management controllers. This user should be created on each node's IPMI before deploying the cluster, and should have, at minimum, permission to read and alter the node's power state.

#### `passwd_ipmi_host`

* *optional*
* *requires* `username_ipmi_host`

The IPMI password, in plain text, used by PVC to communicate with the node management controllers.

Generate using `pwgen -s 16` and adjusting length as required.

#### `passwd_root`

* *ignored*

Used only for reference, the plain-text root password for `passwdhash_root`.

#### `passwdhash_root`

* *required*

The `/etc/shadow`-encoded root password for all nodes.

Generate using `pwgen -s 16`, adjusting length as required, and encrypt using `mkpasswd -m sha-512 <password> $( pwgen -s 8 )`.

#### `logrotate_keepcount`

* *required*

The number of `logrotate_interval` to keep system logs.

#### `logrotate_interval`

* *required*

The interval for rotating system logs. Must be one of: `hourly`, `daily`, `weekly`, `monthly`.

#### `username_email_root`

* *required*

The email address of the root user, at the `local_domain`. Usually `root`, but can be something like `admin` if needed.

#### `hosts`

* *optional*

A list of additional entries for the `/etc/hosts` files on the nodes. Each list element contains the following sub-elements:

##### `name`

The hostname of the entry.

##### `ip`

The IP address of the entry.

#### `admin_users`

* *required*

A list of non-root users, their UIDs, and SSH public keys, that are able to access the server. At least one non-root user should be specified to administer the nodes. These users will not have a password set; only key-based login is supported. Each list element contains the following sub-elements:

##### `name`

* *required*

The name of the user.

##### `uid`

* *required*

The Linux UID of the user. Should usually start at 500 and increment for each user.

##### `keys`

* *required*

A list of SSH public key strings, in `authorized_keys` line format, for the user.

#### `networks`

* *required*

A dictionary of networks to configure on the nodes.

The key will be used to "name" the interface file under `/etc/network/interfaces.d`, but otherwise the `device` is the real name of the device (e.g. `iface [device] inet ...`.

The three required networks are: `upstream`, `cluster`, `storage`. If `storage` is configured identically to `cluster`, the two networks will be collapsed into one; for details on this, please see the [documentation about the storage network](/cluster-architecture/#storage-connecting-ceph-daemons-with-each-other-and-with-osds).

Additional networks can also be specified here to automate their configuration. In the above example, a "bondU" interface is configured, which the remaining required networks use as their `raw_device`.

Within each `network` element, the following options may be specified:

##### `device`

* *required*

The real network device name.

##### `type`

* *required*

The type of network device. Must be one of: `nic`, `bond`, `vlan`.

##### `bond_mode`

* *required* if `type` is `bond`

The Linux bonding/`ifenslave` mode for the cluster. Must be a valid Linux bonding mode.

##### `bond_devices`

* *required* if `type` is `bond`

The list of physical (`nic`) interfaces to bond.

##### `raw_device`

* *required* if `type` is `vlan`

The underlying interface for the vLAN.

##### `mtu`

* *required*

The MTU of the interface. Ensure that the underlying network infrastructure can support the configured MTU.

##### `domain`

* *required*

The domain name for the network. For the "upstream" network, should usually be `local_domain`. 

##### `subnet`

* *required*

The CIDR-formatted subnet of the network. Individual nodes will be configured with specific IPs in this network in a later setting.

##### `floating_ip`

* *required*

A CIDR-formatted IP address in the network to act as the cluster floating IP address. This IP address will follow the primary coordinator.

##### `gateway_ip`

* *optional*

A non-CIDR gateway IP address for the network.

### `pvc.yml`

Example configuration:

```
---
pvc_log_to_file: False
pvc_log_to_stdout: True
pvc_log_colours: False
pvc_log_dates: False
pvc_log_keepalives: True
pvc_log_keepalive_cluster_details: True
pvc_log_keepalive_storage_details: True
pvc_log_console_lines: 1000

pvc_vm_shutdown_timeout: 180
pvc_keepalive_interval: 5
pvc_fence_intervals: 6
pvc_suicide_intervals: 0
pvc_fence_successful_action: migrate
pvc_fence_failed_action: None

pvc_osd_memory_limit: 4294967296
pvc_zookeeper_heap_limit: 256M
pvc_zookeeper_stack_limit: 512M

pvc_api_listen_address: "0.0.0.0"
pvc_api_listen_port: "7370"
pvc_api_secret_key: ""

pvc_api_enable_authentication: False
pvc_api_tokens:
  - description: "myuser"
    token: ""

pvc_api_enable_ssl: False
pvc_api_ssl_cert_path: /etc/ssl/pvc/cert.pem
pvc_api_ssl_cert: >
  -----BEGIN CERTIFICATE-----
  MIIxxx
  -----END CERTIFICATE-----
pvc_api_ssl_key_path: /etc/ssl/pvc/key.pem
pvc_api_ssl_key: >
  -----BEGIN PRIVATE KEY-----
  MIIxxx
  -----END PRIVATE KEY-----

pvc_ceph_storage_secret_uuid: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

pvc_dns_database_name: "pvcdns"
pvc_dns_database_user: "pvcdns"
pvc_dns_database_password: "xxxxxxxx"
pvc_api_database_name: "pvcapi"
pvc_api_database_user: "pcapi"
pvc_api_database_password: "xxxxxxxx"
pvc_replication_database_user: "replicator"
pvc_replication_database_password: "xxxxxxxx"
pvc_superuser_database_user: "postgres"
pvc_superuser_database_password: "xxxxxxxx"

pvc_asn: "65500"
pvc_routers:
  - "192.168.100.1"

pvc_nodes:
  - hostname: "pvchv1"
    is_coordinator: yes
    node_id: 1
    router_id: "192.168.100.11"
    upstream_ip: "192.168.100.11"
    upstream_cidr: 24
    cluster_ip: "10.0.0.1"
    cluster_cidr: 24
    storage_ip: "10.0.1.1"
    storage_cidr: 24
    ipmi_host: "pvchv1-lom.{{ local_domain }}"
    ipmi_user: "{{ username_ipmi_host }}"
    ipmi_password: "{{ passwd_ipmi_host }}"
  - hostname: "pvchv2"
    is_coordinator: yes
    node_id: 2
    router_id: "192.168.100.12"
    upstream_ip: "192.168.100.12"
    upstream_cidr: 24
    cluster_ip: "10.0.0.2"
    cluster_cidr: 24
    storage_ip: "10.0.1.2"
    storage_cidr: 24
    ipmi_host: "pvchv2-lom.{{ local_domain }}"
    ipmi_user: "{{ username_ipmi_host }}"
    ipmi_password: "{{ passwd_ipmi_host }}"
  - hostname: "pvchv3"
    is_coordinator: yes
    node_id: 3
    router_id: "192.168.100.13"
    upstream_ip: "192.168.100.13"
    upstream_cidr: 24
    cluster_ip: "10.0.0.3"
    cluster_cidr: 24
    storage_ip: "10.0.1.3"
    storage_cidr: 24
    ipmi_host: "pvchv3-lom.{{ local_domain }}"
    ipmi_user: "{{ username_ipmi_host }}"
    ipmi_password: "{{ passwd_ipmi_host }}"

pvc_bridge_device: bondU
pvc_bridge_mtu: 1500

pvc_sriov_enable: True
pvc_sriov_device:
  - phy: ens1f0
    mtu: 9000
    vfcount: 6

pvc_upstream_device: "{{ networks['upstream']['device'] }}"
pvc_upstream_mtu: "{{ networks['upstream']['mtu'] }}"
pvc_upstream_domain: "{{ networks['upstream']['domain'] }}"
pvc_upstream_subnet: "{{ networks['upstream']['subnet'] }}"
pvc_upstream_floatingip: "{{ networks['upstream']['floating_ip'] }}"
pvc_upstream_gatewayip: "{{ networks['upstream']['gateway_ip'] }}"
pvc_cluster_device: "{{ networks['cluster']['device'] }}"
pvc_cluster_mtu: "{{ networks['cluster']['mtu'] }}"
pvc_cluster_domain: "{{ networks['cluster']['domain'] }}"
pvc_cluster_subnet: "{{ networks['cluster']['subnet'] }}"
pvc_cluster_floatingip: "{{ networks['cluster']['floating_ip'] }}"
pvc_storage_device: "{{ networks['storage']['device'] }}"
pvc_storage_mtu: "{{ networks['storage']['mtu'] }}"
pvc_storage_domain: "{{ networks['storage']['domain'] }}"
pvc_storage_subnet: "{{ networks['storage']['subnet'] }}"
pvc_storage_floatingip: "{{ networks['storage']['floating_ip'] }}"
```

#### `pvc_log_to_file`

* *optional*

Whether to log PVC output to the file `/var/log/pvc/pvc.log`. Must be one of, unquoted: `True`, `False`.

If unset, a default value of "False" is set in the role defaults.

#### `pvc_log_to_stdout`

* *optional*

Whether to log PVC output to stdout, i.e. `journald`. Must be one of, unquoted: `True`, `False`.

If unset, a default value of "True" is set in the role defaults.

#### `pvc_log_colours`

* *optional*

Whether to include ANSI coloured prompts (`>>>`) for status in the log output. Must be one of, unquoted: `True`, `False`.

Requires `journalctl -o cat` or file logging in order to be visible and useful.

If set to False, the prompts will instead be text values.

If unset, a default value of "True" is set in the role defaults.

#### `pvc_log_dates`

* *optional*

Whether to include dates in the log output. Must be one of, unquoted: `True`, `False`.

Requires `journalctl -o cat` or file logging in order to be visible and useful (and not clutter the logs with duplicate dates).

If unset, a default value of "False" is set in the role defaults.

#### `pvc_log_keepalives`

* *optional*

Whether to log the regular keepalive messages. Must be one of, unquoted: `True`, `False`.

If unset, a default value of "True" is set in the role defaults.

#### `pvc_log_keepalive_cluster_details`

* *optional*
* *ignored* if `pvc_log_keepalives` is `False`

Whether to log cluster and node details during keepalive messages. Must be one of, unquoted: `True`, `False`.

If unset, a default value of "True" is set in the role defaults.

#### `pvc_log_keepalive_storage_details`

* *optional*
* *ignored* if `pvc_log_keepalives` is `False`

Whether to log storage cluster details during keepalive messages. Must be one of, unquoted: `True`, `False`.

If unset, a default value of "True" is set in the role defaults.

#### `pvc_log_console_lines`

* *optional*

The number of output console lines to log for each VM, to be used by the console log endpoints (`pvc vm log`).

If unset, a default value of "1000" is set in the role defaults.

#### `pvc_vm_shutdown_timeout`

* *optional*

The number of seconds to wait for a VM to `shutdown` before it is forced off.

A value of "0" disables this functionality.

If unset, a default value of "180" is set in the role defaults.

#### `pvc_keepalive_interval`

* *optional*

The number of seconds between node keepalives.

If unset, a default value of "5" is set in the role defaults.

**WARNING**: Changing this value is not recommended except in exceptional circumstances.

#### `pvc_fence_intervals`

* *optional*

The number of keepalive intervals to be missed before other nodes consider a node `dead` and trigger the fencing process. The total time elapsed will be `pvc_keepalive_interval * pvc_fence_intervals`.

If unset, a default value of "6" is set in the role defaults.

**NOTE**: This is not the total time until a node is fenced. A node has a further 6 (hardcoded) `pvc_keepalive_interval`s ("saving throw" attepmts) to try to send a keepalive before it is actually fenced. Thus, with the default values, this works out to a total of 60 +/- 5 seconds between a node crashing, and it being fenced. An administrator of a very important cluster may want to set this lower, perhaps to 2, or even 1, leaving only the "saving throws", though this is not recommended for most clusters, due to timing overhead from various other subsystems.

#### `pvc_suicide intervals`

* *optional*

The number of keepalive intervals without the ability to send a keepalive before a node considers *itself* to be dead and reboots itself.

A value of "0" disables this functionality.

If unset, a default value of "0" is set in the role defaults.

**WARNING**: This option is provided to allow additional flexibility in fencing behaviour. Normally, it is not safe to set a `pvc_fence_failed_action` of `migrate`, since if the other nodes cannot fence a node its VMs cannot be safely started on other nodes. This would also apply to nodes without IPMI-over-LAN which could not be fenced normally. This option provides an alternative way to guarantee this safety, at least in situations where the node can still reliably shut itself down (i.e. it is not hard-locked). The administrator should however take special care and thoroughly test their system before using these alternative fencing options in production, as the results could be disasterous.

#### `pvc_fence_successful_action`

* *optional*

The action the cluster should take upon a successful node fence with respect to running VMs.  Must be one of, unquoted: `migrate`, `None`.

If unset, a default value of "migrate" is set in the role defaults.

An administrator can set the value "None" to disable automatic VM recovery migrations after a node fence.

#### `pvc_fence_failed_action`

* *optional*

The action the cluster should take upon a failed node fence with respect to running VMs. Must be one of, unquoted: `migrate`, `None`.

If unset, a default value of "None" is set in the role defaults.

**WARNING**: See the warning in the above `pvc_suicide_intervals` section for details on the purpose of this option. Do not set this option to "migrate" unless you have also set `pvc_suicide_intervals` to a non-"0" value and understand the caveats and risks.

#### `pvc_fence_migrate_target_selector`

* *optional*

The migration selector to use when running a `migrate` command after a node fence. Must be one of, unquoted: `mem`, `load`, `vcpu`, `vms`.

If unset, a default value of "mem" is set in the role defaults.

**NOTE**: These values map to the standard VM meta `selector` options, and determine how nodes select where to run the migrated VMs.

#### `pvc_osd_memory_limit`

* *optional*

The memory limit, in bytes, to pass to the Ceph OSD processes. Only set once, during cluster bootstrap; subsequent changes to this value must be manually made in the `files/*/ceph.conf` static configuration for the cluster in question.

If unset, a default value of "4294967296" (i.e. 4GB) is set in the role defaults.

As per Ceph documentation, the minimum value possible is "939524096" (i.e. ~1GB), and the default matches the Ceph system default. Setting a lower value is only recommended for systems with relatively low memory availability, where the default of 4GB per OSD is too large; it is recommended to increase the total system memory first before tweaking this setting to ensure optimal storage performance across all workloads.

#### `pvc_zookeeper_heap_limit`

* *optional*

The memory limit to pass to the Zookeeper Java process for its heap.

If unset, a default vlue of "256M" is set in the role defaults.

The administrator may set this to a lower value on memory-constrained systems or if the memory usage of the Zookeeper process becomes excessive.

#### `pvc_zookeeper_stack_limit`

* *optional*

The memory limit to pass to the Zookeeper Java process for its stack.

If unset, a defautl value of "512M" is set in the role defaults.

The administrator may set this to a lower value on memory-constrained systems or if the memory usage of the Zookeeper process becomes excessive.

#### `pvc_api_listen_address`

* *required*

Address for the API to listen on; `0.0.0.0` indicates all interfaces.

#### `pvc_api_listen_port`

* *required*

Port for the API to listen on.

#### `pvc_api_enable_authentication`

* *required*

Whether to enable authentication on the API. Must be one of, unquoted: `True`, `False`.

#### `pvc_api_secret_key`

* *required*

A secret key used to sign and encrypt API Flask cookies.

Generate using `uuidgen` or `pwgen -s 32` and adjusting length as required.

#### `pvc_api_tokens`

* *required*

A list of API tokens that are allowed to access the PVC API. At least one should be specified. Each list element contains the following sub-elements:

##### `description`

* *required*

A human-readable description of the token. Not parsed anywhere, but used to make this list human-readable and identify individual tokens by their use.

##### `token`

* *required*

The API token.

Generate using `uuidgen` or `pwgen -s 32` and adjusting length as required.

#### `pvc_api_enable_ssl`

* *required*

Whether to enable SSL for the PVC API. Must be one of, unquoted: `True`, `False`.

#### `pvc_api_ssl_cert_path`

* *optional* 
* *required* if `pvc_api_enable_ssl` is `True` and `pvc_api_ssl_cert` is not set.

The path to an (existing) SSL certificate on the node system for the PVC API to use.

#### `pvc_api_ssl_cert`

* *optional*
* *required* if `pvc_api_enable_ssl` is `True` and `pvc_api_ssl_cert_path` is not set.

The SSL certificate, in text form, for the PVC API to use. Will be installed to `/etc/pvc/api-cert.pem` on the node system.

#### `pc_api_ssl_key_path`

* *optional*
* *required* if `pvc_api_enable_ssl` is `True` and `pvc_api_ssl_key` is not set.

The path to an (existing) SSL private key on the node system for the PVC API to use.

#### `pvc_api_ssl_key`

* *optional*
* *required* if `pvc_api_enable_ssl` is `True` and `pvc_api_ssl_key_path` is not set.

The SSL private key, in text form, for the PVC API to use. Will be installed to `/etc/pvc/api-key.pem` on the node system.

#### `pvc_ceph_storage_secret_uuid`

* *required*

The UUID for Libvirt to communicate with the Ceph storage cluster. This UUID will be used in all VM configurations for the block device.

Generate using `uuidgen`.

#### `pvc_dns_database_name`

* *required*

The name of the PVC DNS aggregator database.

#### `pvc_dns_database_user`

* *required*

The username of the PVC DNS aggregator database user.

#### `pvc_dns_database_password`

* *required*

The password of the PVC DNS aggregator database user.

Generate using `pwgen -s 16` and adjusting length as required.

#### `pvc_api_database_name`

* *required*

The name of the PVC API database.

#### `pvc_api_database_user`

* *required*

The username of the PVC API database user.

#### `pvc_api_database_password`

* *required*

The password of the PVC API database user.

Generate using `pwgen -s 16` and adjusting length as required.

#### `pvc_replication_database_user`

* *required*

The username of the PVC DNS aggregator database replication user.

#### `pvc_replication_database_password`

* *required*

The password of the PVC DNS aggregator database replication user.

Generate using `pwgen -s 16` and adjusting length as required.

#### `pvc_superuser_database_user`

* *required*

The username of the PVC DNS aggregator database superuser.

#### `pvc_superuser_database_password`

* *required*

The password of the PVC DNS aggregator database superuser.

Generate using `pwgen -s 16` and adjusting length as required.

#### `pvc_asn`

* *optional*

The private autonomous system number used for BGP updates to upstream routers.

A default value of "65001" is set in the role defaults if left unset.

#### `pvc_routers`

A list of upstream routers to communicate BGP routes to.

#### `pvc_nodes`

* *required*

A list of all nodes in the PVC cluster and their node-specific configurations. Each node must be present in this list. Each list element contains the following sub-elements:

##### `hostname`

* *required*

The (short) hostname of the node.

##### `is_coordinator`

* *required*

Whether the node is a coordinator. Must be one of, unquoted: `yes`, `no`.

##### `node_id`

* *required*

The ID number of the node. Should normally match the number suffix of the `hostname`.

##### `router_id`

* *required*

The BGP router-id value for upstream route exchange. Should normally match the `upstream_ip`.

##### `upstream_ip`

* *required*

The non-CIDR IP address of the node in the `upstream` network.

##### `upstream_cidr`

* *required*

The CIDR bit mask of the node `upstream_ip` address. Must match the `upstream` network.

##### `cluster_ip`

* *required*

The non-CIDR IP address of the node in the `cluster` network.

##### `cluster_cidr`

* *required*

The CIDR bit mask of the node `cluster_ip` address. Must match the `cluster` network.

##### `storage_ip`

* *required*

The non-CIDR IP address of the node in the `storage` network.

##### `storage_cidr`

* *required*

The CIDR bit mask of the node `storage_ip` address. Must match the `storage` network.

##### `ipmi_host`

* *required*

The IPMI hostname or non-CIDR IP address of the node management controller. Must be reachable by all nodes.

##### `ipmi_user`

* *required*

The IPMI username for the node management controller. Unless a per-host override is required, should usually use the previously-configured global `username_ipmi_host`. All notes from that entry apply.

##### `ipmi_password`

* *required*

The IPMI password for the node management controller. Unless a per-host override is required, should usually use the previously-configured global `passwordname_ipmi_host`. All notes from that entry apply.

#### `pvc_bridge_device`

* *required*

The device name of the underlying network interface to be used for "bridged"-type client networks. For each "bridged"-type network, an IEEE 802.3q vLAN and bridge will be created on top of this device to pass these networks. In most cases, using the reflexive `networks['cluster']['raw_device']` or `networks['upstream']['raw_device']` from the Base role is sufficient.

#### `pvc_bridge_mtu`

* *required*

The MTU of the underlying network interface to be used for "bridged"-type client networks. This is the maximum MTU such networks can use.

#### `pvc_sriov_enable`

* *optional*

Whether to enable or disable SR-IOV functionality.

#### `pvc_sriov_device`

* *optional*

A list of SR-IOV devices. See the Daemon manual for details.

#### `pvc_<network>_*`

The next set of entries is hard-coded to use the values from the global `networks` list. It should not need to be changed under most circumstances. Refer to the previous sections for specific notes about each entry.

