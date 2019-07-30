# PVC HTTP API manual

The PVC HTTP API client is built with Flask, a Python framework for creating API interfaces, and run directly with the PyWSGI framework. It interfaces directly with the Zookeeper cluster to send and receive information about the cluster. It supports authentication configured statically via tokens in the configuration file as well as SSL.

The [`pvc-ansible`](https://github.com/parallelvirtualcluster/pvc-ansible) framework will install and configure the API by default, and enable the node daemon option for an instance of the API to follow the primary node, thus ensuring the API is listening on the upstream floating IP at all times.

## API Details

### SSL

The API accepts SSL certificate and key files via the `pvc-api.yaml` configuration to enable SSL support for the API, which protects the data and query values from snooping or tampering. SSL is strongly recommended if using the API outside of a trusted local area network.

### API authentication

Authentication for the API is available using a static list of tokens. These tokens can be any long string, but UUIDs are typical and simple to use. Within `pvc-ansible`, the list of tokens can be specified in the `pvc.yaml` `group_vars` file. Usually, you'd want one token for each user of the API, such as a WebUI, a 3rd-party client, or an administrative user. Within the configuration, each token can have a description; this is mostly for administrative clarity and is not actually used within the API itself.

The API provides session-based login using the `/api/v1/auth/login` and `/api/v1/auth/logout` options. If authentication is not enabled, these endpoints return a JSON `message` of `Authentiation is disabled` and HTTP code 200.

For one-time authentication, the `token` value can be specified to any API endpoint via the `X-Api-Key` header value. This is only checked if there is no valid session already established. If authentication is enabled, there is no valid session, and no `token` value is specified, the API will return a JSON `message` of `Authentication required` and HTTP code 401.

### Values

The PVC API consistently accepts values (variables) as either HTTP query string arguments, or as HTTP POST form body arguments, in either GET or POST mode.

Some values are `` values; these do not require a data component, and signal an option by their presence.

### Data formats

The PVC API consistently accepts HTTP POST commands of HTML form documents. However, since all form arguments can also be specified as query parameters, and only the `vm define` endpoint accepts a significant amount of data in one argument, it should generally be compatible with API clients speaking only JSON - these can simply send no data in the body and send all required values as query parameters.

The PCI API consistently returns JSON bodies as its responses, with the one exception of the `vm dump` endpoint which returns an XML body. For all POST endpoints, unless otherwise specified below, this is a `message` value containing a human-readable message about the success or failure of the command. The HTTP return code is always 200 for a success or 510 for a failure. For all GET endpoints except the mentioned `vm dump`, this is a JSON body containing the requested data.

## Configuration

The API is configured using a YAML configuration file which is passed in to the API process by the environment variable `PVC_CONFIG_FILE`. When running with the default package and SystemD unit, this file is located at `/etc/pvc/pvc-api.yaml`.

### Conventions

* Settings may be `required`, `optional`, or `ignored`.

* Settings may `depends` on other settings. This indicates that, if one setting is enabled, the other setting is very likely `required` by that setting.

### `pvc-api.yaml`

Example configuration:

```
---
pvc:
    debug: True
    coordinators:
      - pvc-hv1
      - pvc-hv2
      - pvc-hv3
    api:
        listen_address: "127.0.0.1"
        listen_port: "7370"
        authentication:
            enabled: False
            secret_key: "aSuperLong&SecurePasswordString"
            tokens:
                - description: "testing"
                  token: ""
        ssl:
            enabled: False
            cert_file: ""
            key_file: ""
```

#### `debug`

* *required*

Whether to enable Debug mode or not. If enabled, the API will use the Flask debug runtime instead of the PyWSGI framework and will log additional output. Should not be enabled in production.

#### `coordinators`

* *required*

A list of coordinator hosts, used to generate the Zookeeper connection string.

#### `api` → `listen_address`

* *required*

The IP address for the API to listen on. Use `0.0.0.0` to specify "all interfaces".

#### `api` → `listen_port`

The port for the API to listen on.

#### `api` → `authentication` → `enabled`

* *required*

Whether to enable API authentication or not. Should usually be enabled in production deployments, especially if the API is available on untrusted networks.

#### `api` → `authentication` → `secret_key`

* *optional*
* *requires* `authentication` → `enabled`

The Flask authentication secret key used to salt session credentials. Should be a long (>32-character) random string generated with `pwgen` or a similar tool.

#### `api` → `authentication` → `tokens`

* *optional*
* *requires* `authentication` → `enabled`

A list of API authentication tokens that can be passed via the `X-Api-Key` header to authorize access to the API. Each list element contains the following fields:

##### `description`

* *ignored*

A text description of the token function or use. Not parsed by the API, but used for administrator reference in the configuration file.

##### `token`

* *required*

The token itself, usually a UUID created with `uuidegen` or a similar tool.
        
#### `api` → `ssl` → `enabled`

* *required*

Whether to enable SSL for the API or not. Should usually be enabled in production deployments, especially if the API is available on untrusted networks.

#### `api` → `ssl` → `cert_file`

The path to the SSL certificate file for the API to use.

#### `api` → `ssl` → `key_file`

The path to the SSL private key file for the API to use.

## API endpoint documentation

### General endpoints

#### `/api/v1`
 * Methods: `GET`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON `message` containing the API description with HTTP return code 209. Useful for determining if the API is listening and responding properly.

#### `/api/v1/auth/login`
 * Methods: `GET`, `POST`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return an HTTP login form accepting a token to authorize a Flask session.

###### `POST`
 * Mandatory values: `token`
 * Optional values: N/A

Compare the specified `token` to the database and authorize a Flask session.

#### `/api/v1/auth/logout`
 * Methods: `GET`, `POST`

###### `GET`/`POST`
 * Mandatory values: N/A
 * Optional values: N/A

Deactivate the current Flask session for the active token.

### Node endpoints

These endpoints manage PVC node state and operation.

#### `/api/v1/node`
 * Methods: `GET`

###### `GET`
 * Mandatory values: N/A
 * Optional values: `limit`

Return a JSON document containing information about all cluster nodes. If `limit` is specified, return a JSON document containing information about cluster nodes with names matching `limit` as fuzzy regex.

#### `/api/v1/node/<node>`
 * Methods: `GET`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about `<node>`. The output is identical to `/api/v1/node?limit=<node>` without fuzzy regex matching.

**NOTE:** Nodes are created automatically during daemon startup; they cannot be created by the client tools.

#### `/api/v1/node/<node>/daemon-state`
 * Methods: `GET`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return the daemon state of `<node>`.

#### `/api/v1/node/<node>/coordinator-state`
 * Methods: `GET`, `POST`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return the coordinator state of `<node>`.

###### `POST`
 * Mandatory values: `coordinator-state`
 * Optional values: N/A

Set node `<node>` into the specified coordinator state. Attempting to re-set an existing state has no effect.

Valid `coordinator-state` values are: `primary`, `secondary`.

#### `/api/v1/node/<node>/domain-state`
 * Methods: `GET`, `POST`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return the domain state of `<node>`.

###### `POST`
 * Mandatory values: `domain-state`
 * Optional values: N/A

Set node `<node>` to the specified domain state. Attempting to re-set an existing state has effect only if a previous state change did not complete fully, as this triggers a fresh change of state.

Valid `coordinator-state` values are: `flush`, `ready`.

### VM endpoints

These endpoints manage PVC virtual machine (VM) state and operation.

**NOTE:** The `<vm>` variable in all VM endpoints can be either a `name` or a `uuid`. UUIDs are used internally by PVC to track and identify VMs, but are not human-readable, so the clients treat both as equally valid and will automatically determine the `uuid` for any given `name`.

#### `/api/v1/vm`
 * Methods: `GET`, `POST`

###### `GET`
 * Mandatory values: N/A
 * Optional values: `limit`

Return a JSON document containing information about all cluster VMs. If `limit` is specified, return a JSON document containing information about VMs with names matching `limit` as fuzzy regex.

###### `POST`
 * Mandatory values: `xml`
 * Optional values: `node`, `selector`

Define a new VM with Libvirt XML configuration `xml` (either single-line or human-readable multi-line).

If `node` is specified and is valid, the VM will be assigned to `node` instead of automatically determining the target node. If `node` is specified and not valid, auto-selection occurrs instead.

If `selector` is specified and no specific and valid `node` is specified, the automatic node determination will use `selector` to determine the optimal node instead of the default for the cluster.

Valid `selector` values are: `mem`: the node with the least allocated VM memory; `vcpus`: the node with the least allocated VM vCPUs; `load`: the node with the least current load average; `vms`: the node with the least number of provisioned VMs.

**NOTE:** The `POST` operation assumes that the VM resources (i.e. disks, operating system, etc.) are already created. This is equivalent to the `pvc vm define` command in the PVC CLI client. *[todo v0.6]* Creating a new VM using the provisioner uses the `POST /api/vm/<vm>` endpoint instead.

#### `/api/v1/vm/<vm>`
 * Methods: `GET`, *[todo v0.6]* `POST`, `PUT`, `DELETE`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about `<vm>`. The output is identical to `GET /api/v1/vm?limit=<vm>` without fuzzy regex matching.

###### *[todo v0.6]* `POST`
 * Mandatory values: `vm_template`
 * Optional values: `description`

Create a new virtual machine `<vm>` with the specified VM template `vm_template` and optional text `description`.

###### `PUT`
 * Mandatory values: `xml`
 * Optional values: `restart`

Replace the existing Libvirt XML definition for `<vm>` with the specified Libvirt XML configuration `xml` (either single-line or human-readable multi-line).

If `restart` is specified, the cluster will automatically `restart` the VM with the new configuration; if not, the administrator must do so manually.

###### `DELETE`
 * Mandatory values: N/A
 * Optional values: `delete_disks`

Forcibly stop and undefine `<vm>`.

If `delete_disks` is specified, also remove all Ceph storage volumes for the VM.

#### `/api/v1/vm/<vm>/state`
 * Methods: `GET`, `POST`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return the state of `<vm>`.

###### `POST`
 * Mandatory values: `state`
 * Optional values: N/A

Set `<vm>` to the specified state. Attempting to re-set an existing state has no effect.

Valid `state` values are: `start`, `shutdown`, `stop`, `restart`

**NOTE:** The `shutdown` state will attempt to gracefully shutdown the VM with a 90s timeout, after which it will forcibly `stop` the VM.

#### `/api/v1/vm/<vm>/node`
 * Methods: `GET`, `POST`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return the current host node and previous node, if applicable, for `<vm>`.

###### `POST`
 * Mandatory values: `action`
 * Optional values: `node`, `selector`, `permanent`, `force`

Change the current host node for `<vm>` by `action`, using live migration if possible, and using `shutdown` then `start` if not. `action` must be either `migrate` or `unmigrate`.

If `node` is specified and is valid, the VM will be assigned to `node` instead of automatically determining the target node. If `node` is specified and not valid, auto-selection occurrs instead.

If `selector` is specified and no specific and valid `node` is specified, the automatic node determination will use `selector` to determine the optimal node instead of the default for the cluster.

Valid `selector` values are: `mem`: the node with the least allocated VM memory; `vcpus`: the node with the least allocated VM vCPUs; `load`: the node with the least current load average; `vms`: the node with the least number of provisioned VMs.

If `permanent` is specified, the PVC system will not track the previous node and the VM will not be considered migrated. This is equivalent to the `pvc vm move` CLI command.

If `force` is specified, and the VM has been previously migrated, force through a new migration to the selected target and do not update the previous node value.

### Network endpoints

These endpoints manage PVC client virtual network state and operation.

#### `/api/v1/network`
 * Methods: `GET`, `POST`

###### `GET`
 * Mandatory values: N/A
 * Optional values: `limit`

Return a JSON document containing information about all cluster networks. If `limit` is specified, return a JSON document containing information about cluster networks with descriptions matching `limit` as fuzzy regex.

###### `POST`
 * Mandatory values: `vni`, `description`, `nettype`
 * Optional values: `domain`, `ip4_network`, `ip4_gateway`, `ip6_network`, `ip6_gateway`, `dhcp4`, `dhcp4_start`, `dhcp4_end`

Add a new virtual network to the cluster. `vni` must be a valid VNI, either a vLAN ID (for `bridged` networks) or a VXLAN ID (or `managed` networks). `description` must be a whitespace-free description of the network.

`nettype` must be one of the following network types:

* `bridged` for unmanaged, vLAN-based bridged networks. All additional optional values are ignored by this type

* `managed` for PVC-managed, VXLAN-based networks.

`domain` specifies a DNS domain for hosts in the network. DNS is aggregated and provded for all networks on the primary coordinator node.

`ip4_network` specifies a CIDR-formatted IPv4 netblock, usually RFC1918, for the network.

`ip4_gateway` specifies an IP address from the `ip4_network` for the primary coordinator node to provide gateway services to the network. If `ip4_network` is specified but `ip4_gateway` is not specified or is invalid, return a failure.

`ip6_network` specifies a CIDR-formatted IPv6 netblock for the network.

`ip6_gateway` specifies an IP address from the `ip6_network` for the primary coordinator node to provide gateway services to the network. If `ip6_network` is specified but `ip6_gateway` is not specified or is invalid, default to `<ip6_network>::1`.

`dhcp4` specifies that DHCPv4 should be used for the IPv4 network.

`dhcp4_start` specifies an IP address for the start of the DHCPv4 IP pool. If `dhcp4` is specified but `dhcp4_start` is not specified or is invalid, return a failure.

`dhcp4_end` specifies an IP address for the end of the DHCPv4 IP pool. If `dhcp4` is specified but `dhcp4_end` is not specified or is invalid, return a failure.

#### `/api/v1/network/<network>`
 * Methods: `GET`, `PUT`, `DELETE`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about the virtual network `<network>`. The output is identical to `/api/v1/network?limit=<network>` without fuzzy regex matching.

###### `PUT`
 * Mandatory values: N/A
 * Optional values: `domain`, `ip4_network`, `ip4_gateway`, `ip6_network`, `ip6_gateway`, `dhcp4`, `dhcp4_start`, `dhcp4_end`

Modify the options of an existing virtual network `<network>`.

All values are optional and are identical to the values for `add`. Only those values specified will be updated.

###### `DELETE`

Remove a virtual network `<network>`.

#### `/api/v1/network/<network>/lease`
 * Methods: `GET`, `POST`

###### `GET`
 * Mandatory values: N/A
 * Optional values: `limit`, `static`

Return a JSON document containing information about all active DHCP leases in virtual network `<network>`.

If `limit` is specified, return a JSON document containing information about all active DHCP leases with MAC addresses matching `limit` as fuzzy regex.

If `static` is specified, only return static DHCP leases.

###### `POST`
 * Mandatory values: `macaddress`, `ipaddress`
 * Optional values: `hostname`

Add a new static DHCP lease for MAC address `<macaddress>` in virtual network `<network>`.

`ipaddress` must be a valid IP address in the specified `<network>` IPv4 netblock, and ideally outside of the DHCPv4 range.

`hostname` specifies a static hostname hint for the lease.

#### `/api/v1/network/<network>/dhcp/<lease>`
 * Methods: `GET`, `DELETE`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about DHCP lease with MAC address `<lease>` in virtual network `<network>`. The output is identical to `/api/v1/network/<network>/dhcp?limit=<lease>` without fuzzy regex matching.

###### `DELETE`
 * Mandatory values: N/A
 * Optional values: N/A

Remove a static DHCP lease for MAC address `<lease`> in virtual network `<network>`.

#### `/api/v1/network/<network>/acl`
 * Methods: `GET`, `POST`

###### `GET`
 * Mandatory values: N/A
 * Optional values: `limit`, `direction`

Return a JSON document containing information about all active NFTables ACLs in virtual network `<network>`.

If `limit` is specified, return a JSON document containing information about all active NFTables ACLs with descriptions matching `limit` as fuzzy regex.

If `direction` is specified and is one of `in` or `out`, return a JSON codument listing all active NFTables ACLs in the specified direction only. If `direction` is invalid, return a failure.

###### `POST`
 * Mandatory values: `description`, `direction`, `rule`
 * Optional values: `order`

Add a new NFTables ACL with `description` in virtual network `<network>`.

`direction` must be one of `in` or `out`.

`rule` must be a valid NFTables rule string. PVC does no special replacements or variables beyond what NFTables itself is capable of. For per-host ACLs, it is usually advisable to use a static DHCP lease as well to control the VM's IP address.

`order` specifies the order of the rule in the current chain. If not specified, the rule will be placed at the end of the rule chain.

#### `/api/v1/network/<network>/acl/<acl>`
 * Methods: `GET`, `DELETE`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about NFTables ACL with description `<acl>` in virtual network `<network>`. The output is identical to `/api/v1/network/<network>/acl?limit=<acl>` without fuzzy regex matching.

If `<acl>` is not valid, return an empty JSON document.

###### `DELETE`
 * Mandatory values: `direction`
 * Optional values: N/A

Remove an NFTables ACL with description `<acl>` in direction `direction` from virtual network `<network>`.

### Storage (Ceph) endpoints

These endpoints manage PVC Ceph storage cluster state and operation. This section has the added prefix `/storage`, to allow the future addition of other storage subsystems.

**NOTE:** Unlike the other API endpoints, Ceph endpoints will wait until the command completes successfully before returning. This is a safety measure to prevent the critical storage subsystem from going out-of-sync with the PVC Zookeeper database; the cluster objects are only created after the storage subsystem commands complete. Because of this, *be careful with HTTP timeouts when running Ceph commands via the API*. 30s or longer may be required for some commands, especially OSD addition or removal.

#### `/api/v1/storage/ceph`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about the current Ceph cluster status. The JSON element `ceph_data` contains the raw output of a `ceph status` command.

#### `/api/v1/storage/ceph/status`
 * Methods: `GET`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

This endpoint is an alias for `/api/v1/storage/ceph`.

#### `/api/v1/storage/ceph/df`
 * Methods: `GET`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about the current Ceph cluster utilization. The JSON element `ceph_data` contains the raw output of a `rados df` command.

#### `/api/v1/storage/ceph/cluster-option`
 * Methods: `POST`

###### `POST`
 * Mandatory values: `action`, `option`
 * Optional values: N/A

Perform `action` to a global Ceph OSD `option` on the storage cluster. `action` must be either `set` or `unset`. `option` must be a valid option to the `ceph osd set/unset` commands, e.g. `noout` or `noscrub`.

#### `/api/v1/storage/ceph/osd`
 * Methods: `GET`, `POST`

###### `GET`
 * Mandatory values: N/A
 * Optional values: `limit`

Return a JSON document containing information about all Ceph OSDs in the storage cluster. If `limit` is specified, return a JSON document containing information about all Ceph OSDs with names matching `limit` as fuzzy regex.

###### `POST`
 * Mandatory values: `node`, `device`, `weight`
 * Optional values: N/A

Add a new Ceph OSD to PVC node `<node>`. `device` must be a valid block device on the specified `<node>`, e.g. `/dev/sdb`. `weight` must be a valid Ceph OSD weight, usually `1.0` if all OSD disks are the same size.

#### `/api/v1/storage/ceph/osd/<osd>`
 * Methods: `GET`, `DELETE`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about Ceph OSD with ID `<osd>` in the storage cluster. Unlike other similar endpoints, this is **NOT** equivalent to any limit within the list, since that limit is based off names rather than just the ID.

###### `DELETE`
 * Mandatory values: `yes_i_really_mean_it`
 * Optional values: N/A

Remove a Ceph OSD device with ID `<osd>` from the storage cluster.

**NOTE:** This is a command with potentially dangerous unintended consequences that should not be scripted. To acknowledge the danger, the `yes_i_really_mean_it` must be set or the endpoint will return a failure.

**WARNING:** Removing an OSD without first setting it `out` (and letting it flush) triggers an unclean PG recovery. This could potentially cause data loss if other OSDs were to fail or be removed. OSDs should not normally be removed except in the case of failed OSDs during replacement or during a replacement with a larger disk. For more information please see the Ceph documentation.

#### `/api/v1/storage/ceph/osd/<osd>/state`
 * Methods: `GET`, `POST`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return the state state of OSD `<osd>`.

###### `POST`
 * Mandatory values: `state`
 * Optional values: N/A

Set a Ceph OSD device with ID `<osd>` to `state`. `state` must be either `in` or `out`.

#### `/api/v1/storage/ceph/pool`
 * Methods: `GET`, `POST`

###### `GET`
 * Mandatory values: N/A
 * Optional values: `limit`

Return a JSON document containing information about all Ceph RBD pools in the storage cluster. If `limit` is specified, return a JSON document containing information about all Ceph RBD pools with names matching `limit` as fuzzy regex.

###### `POST`
 * Mandatory values: `pool`, `pgs`
 * Optional values: N/A

Add a new Ceph RBD pool `<pool>` to the storage cluster. `pgs` must be a valid number of Placement Groups for the pool, taking into account the number of OSDs and the replication of the pool (`copies=3`). `256` is a safe and sane number of PGs for 3 nodes and 2 disks per node. This value can be grown later via `ceph` commands as required.

#### `/api/v1/storage/ceph/pool/<pool>`
 * Methods: `GET`, `DELETE`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about Ceph RBD pool `<pool>`. The output is identical to `/api/v1/storage/ceph/pool?limit=<pool>` without fuzzy regex matching.

###### `DELETE`
 * Mandatory values: `yes_i_really_mean_it`
 * Optional values: N/A

Remove a Ceph RBD pool `<pool>` from the storage cluster.

**NOTE:** This is a command with potentially dangerous unintended consequences that should not be scripted. To acknowledge the danger, the `yes_i_really_mean_it` must be set or the endpoint will return a failure.

**WARNING:** Removing an RBD pool will delete all data on that pool, including all Ceph RBD volumes on the pool. Do not run this command lightly and without ensuring the pool is safely removable first.

#### `/api/v1/storage/ceph/volume`
 * Methods: `GET`, `POST`

###### `GET`
 * Mandatory values: N/A
 * Optional values: `pool`, `limit`

Return a JSON document containing information about all Ceph RBD volumes in the storage cluster. If `pool` is specified, return a JSON document containing information about all Ceph RBD volumes in Ceph RBD pool `pool`. If `limit` is specified, return a JSON document containing information about all Ceph RBD volumes with names matching `limit` as fuzzy regex.

###### `POST`
 * Mandatory values: `volume`, `pool`, `size`
 * Optional values: N/A

Add a new Ceph RBD volume `<volume>` to Ceph RBD pool `<pool>`. `size` must be a valid size, in bytes or a single-character metric prefix of bytes, e.g. `1073741824` (1GB), `4096M`, or `20G`.

#### `/api/v1/storage/ceph/volume/<pool>/<volume>`
 * Methods: `GET`, `PUT`, `DELETE`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about Ceph RBD volume `<volume>` in Ceph RBD pool `<pool>`. The output is identical to `/api/v1/storage/ceph/volume?pool=<pool>&limit=<volume>` without fuzzy regex matching.

###### `PUT`
 * Mandatory values: N/A
 * Optional values: `name`, `size`

Change the configuration of the volume `<volume>`. If `name` is specified, rename the volume to the specified name. If `size` is specified, resize the volume to the specified size (see `POST /api/v1/storage/ceph/volume` for restrictions).

**NOTE:** Only one change operation (either `name` or `size`) may be completed in one operation.

###### `DELETE`
 * Mandatory values: N/A
 * Optional values: N/A

Remove a Ceph RBD volume `<volume>` from Ceph RBD pool `<pool>`.

#### `/api/v1/storage/ceph/volume/snapshot`
 * Methods: `GET`, `POST`

###### `GET`
 * Mandatory values: N/A
 * Optional values: `pool`, `volume`, `limit`

Return a JSON document containing information about all Ceph RBD volume snapshots in the storage cluster. If `pool` is specified, return a JSON document containing information about all Ceph RBD volume snapshots in Ceph RBD pool `pool`. If `volume` is specified, return a JSON document containing information about all Ceph RBD volume snapshots of Ceph RBD volume `volume`. If `limit` is specified, return a JSON document containing information about all Ceph RBD volume snapshots with names matching `limit` as fuzzy regex.

The various limit options can be combined freely, e.g. one can specify a `volume` without `pool`, which would match all snapshots of the named volume(s) regardless of pool, or a `pool` and `limit` without a `volume`, which would match all named snapshots on any volume in `pool`.

###### `POST`
 * Mandatory values: `snapshot`, `volume`, `pool`
 * Optional values: N/A

Add a new Ceph RBD volume snapshot `snapshot` of Ceph RBD volume `volume` on Ceph RBD pool `pool`.

#### `/api/v1/storage/ceph/volume/snapshot/<pool>/<volume>/<snapshot>`
 * Methods: `GET`, `DELETE`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about Ceph RBD volume snapshot `<snapshot>` of Ceph RBD volume `<volume>` in Ceph RBD pool `<pool>`. The output is identical to `/api/v1/storage/ceph/volume?pool=<pool>&volume=<volume>&limit=<snapshot>` without fuzzy regex matching.

###### `DELETE`
 * Mandatory values: N/A
 * Optional values: N/A

Remove a Ceph RBD volume snapshot `<snapshot>` of Ceph RBD volume `<volume>` on Ceph RBD pool `<pool>`.
