# PVC Ansible configuration manual

This manual documents the various `group_vars` configuration options for the `pvc-ansible` framework. We assume that the administrator is generally familiar with Ansible and its operation.

## General usage

### Initial setup

After cloning the `pvc-ansible` repo, set up a set of configurations for your cluster. One copy of the `pvc-ansible` repository can manage an unlimited number of clusters with differing configurations.

All files created during initial setup should be stored outside the `pvc-ansible` repository, as they will be ignored by the main Git repository by default. It is recommended to set up a separate folder, either standalone or as its own Git repository, to contain your files, then symlink them back into the main repository at the appropriate places outlined below.

Create a `hosts` file containing the clusters as groups, then the list of hosts within each cluster group. The `hosts.default` file can be used as a template.

Create a `files/<cluster>` folder to hold the cluster-created static configuration files. Until the first bootstrap run, this directory will be empty.

Create a `group_vars/<cluster>` folder to hold the cluster configuration variables. The `group_vars/default` directory can be used as an example.

### Bootstrapping a cluster

Before bootstrapping a cluster, see the section on [PVC Ansible configuration variables](/manuals/ansible#pvc-ansible-configuration-variables) to configure the cluster.

Bootstrapping a cluster can be done using the main `pvc.yml` playbook. Generally, a bootstrap run should be limited to the coordinators of the cluster to avoid potential race conditions or strange bootstrap behaviour. The special variable `bootstrap=yes` must be set to indicate that a cluster bootstrap is to be requested.

**WARNING:** Do not run the playbook with `bootstrap=yes` *except during the very first run against a freshly-installed set of coordinator nodes*. Running it against an existing cluster will result in the complete failure of the cluster, the destruction of all data, or worse.

### Adding new nodes

Adding new nodes to an existing cluster can be done using the main `pvc.yml` playbook. The new node(s) should be added to the `group_vars` configuration `node_list`, then the playbook run against all hosts in the cluster with no special flags or limits. This will ensure the entire cluster is updated with the new information, while simultaneously configuring the new node.

### Reconfiguration and software updates

After modifying configuration settings in the `group_vars`, or to update PVC to the latest version on a release, deployment of updated cluster can be done using the main `pvc.yml` playbook. The configuration should be updated if required, then the playbook run against all hosts in the cluster with no special flags or limits.

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
local_domain: upstream.local
username_ipmi_host: "pvc"
passwd_ipmi_host: "MyPassword2019"

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
  "upstream":
    device: "bondU"
    type: "bond"
    bond_mode: "802.3ad"
    bond_devices:
      - "enp1s0f0"
      - "enp1s0f1"
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
    mtu: 1500
    domain: "pvc-storage.local"
    subnet: "10.0.1.0/24"
    floating_ip: "10.0.1.254/24"
```

#### `local_domain`

* *required*

The domain name of the PVC cluster nodes. This is the domain portion of the FQDN of each node, and should usually be the domain of the `upstream` network.

#### `username_ipmi_host`

* *optional*
* *requires* `passwd_ipmi_host`

The IPMI username used by PVC to communicate with the node management controllers. This user should be created on each node's IPMI before deploying the cluster, and should have, at minimum, permission to read and alter the node's power state.

#### `passwd_ipmi_host`

* *optional*
* *requires* `username_ipmi_host`

The IPMI password, in plain text, used by PVC to communicate with the node management controllers.

Generate using `pwgen -s 16` and adjusting length as required.

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

A list of additional entries for the `/etc/hosts` files on the nodes. Each list element contains the following subelements:

##### `name`

The hostname of the entry.

##### `ip`

The IP address of the entry.

#### `admin_users`

* *required*

A list of non-root users, their UIDs, and SSH public keys, that are able to access the server. At least one non-root user should be specified to administer the nodes. These users will not have a password set; only key-based login is supported. Each list element contains the following subelements:

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

A dictionary of networks to configure on the nodes. Three networks are required by all PVC clusters, though additional networks may be configured here as well.

The three required networks are: `upstream`, `cluster`, `storage`.

Within each `network` element, the following options may be specified:

##### `device`

* *required*

The network device name.

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

The CIDR-formated subnet of the network. Individual nodes will be configured with specific IPs in this network in a later setting.

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

pvc_api_listen_address: "0.0.0.0"
pvc_api_listen_port: "7370"
pvc_api_enable_authentication: False
pvc_api_secret_key: ""
pvc_api_tokens:
  - description: "myuser"
    token: ""
pvc_api_enable_ssl: False
pvc_api_ssl_cert: >
  -----BEGIN CERTIFICATE-----
  MIIxxx
  -----END CERTIFICATE-----
pvc_api_ssl_key: >
  -----BEGIN PRIVATE KEY-----
  MIIxxx
  -----END PRIVATE KEY-----

pvc_ceph_storage_secret_uuid: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

pvc_dns_database_name: "pvcdns"
pvc_dns_database_user: "pvcdns"
pvc_dns_database_password: "xxxxxxxx"
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

* *required*

Whether to log PVC output to the file `/var/log/pvc/pvc.log`. Must be one of, unquoted: `True`, `False`.

#### `pvc_log_to_stdout`

* *required*

Whether to log PVC output to stdout, i.e. `journald`. Must be one of, unquoted: `True`, `False`.

#### `pvc_log_colours`

* *required*

Whether to include ANSI coloured prompts (`>>>`) for status in the log output. Must be one of, unquoted: `True`, `False`.

Requires `journalctl -o cat` or file logging in order to be visible and useful.

If set to False, the prompts will instead be text values.

#### `pvc_log_dates`

* *required*

Whether to include dates in the log output. Must be one of, unquoted: `True`, `False`.

Requires `journalctl -o cat` or file logging in order to be visible and useful (and not clutter the logs with duplicate dates).

#### `pvc_log_keepalives`

* *required*

Whether to log keepalive messages. Must be one of, unquoted: `True`, `False`.

#### `pvc_log_keepalive_cluster_details`

* *required*
* *ignored* if `pvc_log_keepalives` is `False`

Whether to log cluster and node details during keepalive messages. Must be one of, unquoted: `True`, `False`.

#### `pvc_log_keepalive_storage_details`

* *required*
* *ignored* if `pvc_log_keepalives` is `False`

Whether to log storage cluster details during keepalive messages. Must be one of, unquoted: `True`, `False`.

#### `pvc_log_console_lines`

* *required*

The number of output console lines to log for each VM.

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

A list of API tokens that are allowed to access the PVC API. At least one should be specified. Each list element contains the following subelements:

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

#### `pvc_api_ssl_cert`

* *required* if `pvc_api_enable_ssl` is `True`

The SSL certificate, in text form, for the PVC API to use.

#### `pvc_api_ssl_key`

* *required* if `pvc_api_enable_ssl` is `True`

The SSL private key, in text form, for the PVC API to use.

#### `pvc_ceph_storage_secret_uuid`

* *required*

The UUIS for Libvirt to communicate with the Ceph storage cluster. This UUID will be used in all VM configurations for the block device.

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

#### `pvc_replication_database_user`

* *required*

The username of the PVC DNS aggregator database replication user.

#### `pvc_repliation_database_password`

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

* *required*

The private autonomous system number used for BGP updates to upstream routers.

#### `pvc_routers`

A list of upstream routers to communicate BGP routes to.

#### `pvc_nodes`

* *required*

A list of all nodes in the PVC cluster and their node-specific configurations. Each node must be present in this list. Each list element contains the following subelements:

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

#### `pvc_<network>_*`

The next set of entries is hardcoded to use the values from the global `networks` list. It should not need to be changed under most circumstances. Refer to the previous sections for specific notes about each entry.

