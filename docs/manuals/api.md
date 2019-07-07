# PVC HTTP API manual

The PVC HTTP API client is built with Flask, a Python framework for creating API interfaces, and run directly with the PyWSGI framework. It interfaces directly with the Zookeeper cluster to send and receive information about the cluster. It supports authentication configured statically via tokens in the configuration file as well as SSL.

The [`pvc-ansible`](https://github.com/parallelvirtualcluster/pvc-ansible) framework will install and configure the API by default, and enable the node daemon option for an instance of the API to follow the primary node, thus ensuring the API is listening on the upstream floating IP at all times.

## API Details

### SSL

The API accepts SSL certificate and key files via the `pvc-api.yaml` configuration to enable SSL support for the API, which protects the data and query values from snooping or tampering. SSL is strongly recommended if using the API outside of a trusted local area network.

### API authentication

Authentication for the API is available using a static list of tokens. These tokens can be any long string, but UUIDs are typical and simple to use. Within `pvc-ansible`, the list of tokens can be specified in the `pvc.yml` `group_vars` file. Usually, you'd want one token for each user of the API, such as a WebUI, a 3rd-party client, or an administrative user. Within the configuration, each token can have a description; this is mostly for administrative clarity and is not actually used within the API itself.

The API provides session-based login using the `/api/v1/auth/login` and `/api/v1/auth/logout` options. If authentication is not enabled, these endpoints return a JSON `message` of `Authentiation is disabled` and HTTP code 200.

For one-time authentication, the `token` value can be specified to any API endpoint. This is only checked if there is no valid session already established. If authentication is enabled, there is no valid session, and no `token` value is specified, the API will return a JSON `message` of `Authentication required` and HTTP code 401.

### Values

The PVC API consistently accepts values (variables) as either HTTP query string arguments, or as HTTP POST form body arguments, in either GET or POST mode.

Some values are `flag_` values; these do not require a data component, and signal an option by their presence.

### Data formats

The PVC API consistently accepts HTTP POST commands of HTML form documents. However, since all form arguments can also be specified as query parameters, and only the `vm define` endpoint accepts a significant amount of data in one argument, it should generally be compatible with API clients speaking only JSON - these can simply send no data in the body and send all required values as query parameters.

The PCI API consistently returns JSON bodies as its responses, with the one exception of the `vm dump` endpoint which returns an XML body. For all POST endpoints, unless otherwise specified below, this is a `message` value containing a human-readable message about the success or failure of the command. The HTTP return code is always 200 for a success or 510 for a failure. For all GET endpoints except the mentioned `vm dump`, this is a JSON body containing the requested data.

## API endpoint documentation

### General endpoints

#### `/api/v1`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON `message` containing the API description with HTTP return code 209. Useful for determining if the API is listening and responding properly.

#### `/api/v1/auth/login`
 * Methods: `GET`, `POST`
 * Mandatory values: `token`
 * Optional values: N/A

On `GET`, return an HTTP login form accepting a token to authorize a Flask session.

On `POST`, compare the specified token to the database and authorize a session. If this comparison fails to find a match, return a JSON `message` of `Authentication failed` and HTTP code 401.

#### `/api/v1/auth/logout`
 * Methods: `GET`, `POST`
 * Mandatory values: N/A
 * Optional values: N/A

On `GET` or `POST`, deactivate the current Flask session for the active token.

### Node endpoints

These endpoints manage PVC node state and operation.

#### `/api/v1/node`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: `limit`

Return a JSON document containing information about all cluster nodes .

If `limit` is specified, return a JSON document containing information about cluster nodes with names matching `limit` as fuzzy regex.

#### `/api/v1/node/<node>`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about `<node>`. The output is identical to `/api/v1/node?limit=<node>` without fuzzy regex.

If `<node>` is not valid, return an empty JSON document.

#### `/api/v1/node/<node>/secondary`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Set node `<node>` into Secondary coordinator mode.

Attempting to `secondary` a non-primary node will return a failure.

#### `/api/v1/node/<node>/primary`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Set node `<node>` into Primary coordinator mode.

Attempting to `primary` an already-primary node will return a failure.

#### `/api/v1/node/<node>/flush`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Flush node `<node>` of running VMs. This command does not wait for completion of the flush and returns immediately.

Attempting to `flush` an already flushed node will **NOT** return a failure.

#### `/api/v1/node/<node>/unflush`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Unflush (return to ready) node `<node>`, restoring migrated VMs. This command does not wait for completion of the flush and returns immediately.

Attempting to `unflush` a non-flushed node will **NOT** return a failure.

#### `/api/v1/node/<node>/ready`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

This endpoint is an alias for `/api/v1/node/<node>/unflush`.

### VM endpoints

These endpoints manage PVC virtual machine (VM) state and operation.

**NOTE:** The `<vm>` variable in all VM endpoints can be either a `name` or a `uuid`. UUIDs are used internally by PVC to track and identify VMs, but are not human-readable, so the clients treat both as equally valid and will automatically determine the `uuid` for any given `name`.

#### `/api/v1/vm`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: `limit`

Return a JSON document containing information about all cluster VMs .

If `limit` is specified, return a JSON document containing information about VMs with names matching `limit` as fuzzy regex.

#### `/api/v1/vm/<vm>`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about `<vm>`. The output is identical to `/api/v1/vm?limit=<vm>` without fuzzy regex.

If `<vm>` is not valid, return an empty JSON document.

#### `/api/v1/vm/<vm>/define`
 * Methods: `POST`
 * Mandatory values: `xml`
 * Optional values: `node`, `selector`

Define a new VM with name or UUID `<vm>`.

**NOTE:** While included for consistency, the specified `<vm>` value is ignored and the values from the Libvirt XML configuration will be used instead.

`xml` must be a valid Libvirt XML definition; human-readable, multi-line formatted definitions are fully supported.

If `node` is specified and is valid, the VM will be assigned to `node` instead of automatically determining the target node. If `node` is specified and not valid, return a failure. 

If `selector` is specified, the automatic node determination will use `selector` to determine the optimal node instead of the default (`mem`, least allocated VM memory). If `node` is also specified, this value is ignored.

#### `/api/v1/vm/<vm>/modify`
 * Methods: `POST`
 * Mandatory values: `xml`
 * Optional values: `flag_restart`

Replace an existing VM Libvirt XML definition for a VM with name or UUID `<vm>`.

`xml` must be a valid Libvirt XML definition; human-readable, multi-line formatted definitions are fully supported.

By default the cluster will not restart the VM to load the new configuration; the administrator must do so manually.

If `flag_restart` is specified, the cluster will automatically `restart` the VM with the new configuration.

#### `/api/v1/vm/<vm>/undefine`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Forcibly stop and undefine the VM with name or UUID `<vm>`, preserving Ceph volumes.

#### `/api/v1/vm/<vm>/remove`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Forcibly stop, undefine, and remove Ceph volumes of the VM with name or UUID `<vm>`.

#### `/api/v1/vm/<vm>/dump`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Obtain the raw Libvirt XML configuration of the VM with name or UUID `<vm>`.

Return an XML document containing the Libvirt XML and HTTP code 200 on success.

#### `/api/v1/vm/<vm>/start`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Start the VM with name or UUID `<vm>`.

#### `/api/v1/vm/<vm>/restart`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Restart (`shutdown` then `start`) the VM with name or UUID `<vm>`.

#### `/api/v1/vm/<vm>/shutdown`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Gracefully shutdown the VM with name or UUID `<vm>`. The shutdown event will time out after 90s and `stop` the VM.

#### `/api/v1/vm/<vm>/stop`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Forcibly terminate the VM with name or UUID `<vm>` immediately.

#### `/api/v1/vm/<vm>/move`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: `node`, `selector`

Permanently move (do not track previous node) the VM with name or UUID `<vm>`. Use Libvirt live migration if possible; otherwise `shutdown` then `start` on the new node.

If `node` is specified and is valid, the VM will be assigned to `node` instead of automatically determining the target node. If `node` is specified and not valid, return a failure. 

If `selector` is specified, the automatic node determination will use `selector` to determine the optimal node instead of the default (`mem`, least allocated VM memory). If `node` is also specified, this value is ignored.

#### `/api/v1/vm/<vm>/migrate`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: `node`, `selector`, `flag_force`

Temporarily move (track the previous node and migrated state) the VM with name or UUID `<vm>`. Use Libvirt live migration if possible; otherwise `shutdown` then `start` on the new node.

If `node` is specified and is valid, the VM will be assigned to `node` instead of automatically determining the target node. If `node` is specified and not valid, return a failure.

If `selector` is specified, the automatic node determination will use `selector` to determine the optimal node instead of the default (`mem`, least allocated VM memory). If `node` is also specified, this value is ignored.

Attempting to `migrate` an already-migrated VM will return a failure.

If `flag_force` is specified, migrate the VM even if it has already been migrated. The previous node value will not be replaced; e.g. if VM `test` was on `pvchv1`, then `migrate`ed to `pvchv2`, then `flag_force` `migrate`ed to `pvchv3`, the `previous_node` would still be `pvchv1`. This can be repeated indefinitely.

#### `/api/v1/vm/<vm>/unmigrate`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Unmigrate the `migrate`ed VM with name or UUID `<vm>`, returning it to its previous node. Use Libvirt live migration if possible; otherwise `shutdown` then `start` on the previous node.

Attempting to `unmigrate` a non-migrated VM will return a failure.

### Network endpoints

These endpoints manage PVC client virtual network state and operation.

#### `/api/v1/network`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: `limit`

Return a JSON document containing information about all cluster networks.

If `limit` is specified, return a JSON document containing information about cluster VMs with names matching `limit` as fuzzy regex.

#### `/api/v1/network/<network>`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about `<network>`. The output is identical to `/api/v1/network?limit=<network>` without fuzzy regex.

If `<network>` is not valid, return an empty JSON document.

#### `/api/v1/network/<network>/add`
 * Methods: `POST`
 * Mandatory values: `vni`, `nettype`
 * Optional values: `domain`, `ip4_network`, `ip4_gateway`, `ip6_network`, `ip6_gateway`, `flag_dhcp4`, `dhcp4_start`, `dhcp4_end`

Add a new virtual network with (whitespace-free) description `<network>`.

`vni` must be a valid VNI, either a vLAN ID (for `bridged` networks) or VXLAN ID (for `managed`) networks).

`nettype` must be one of:

* `bridged` for unmanaged, vLAN-based bridged networks. All optional values are ignored with this type.

* `managed` for PVC-managed, VXLAN-based networks.

`domain` specifies a DNS domain for hosts in the network. DNS is aggregated and provded for all networks on the primary coordinator node.

`ip4_network` specifies a CIDR-formatted IPv4 netblock, usually RFC1918, for the network.

`ip4_gateway` specifies an IP address from the `ip4_network` for the primary coordinator node to provide gateway services to the network. If `ip4_network` is specified but `ip4_gateway` is not specified or is invalid, return a failure.

`ip6_network` specifies a CIDR-formatted IPv6 netblock for the network.

`ip6_gateway` specifies an IP address from the `ip6_network` for the primary coordinator node to provide gateway services to the network. If `ip6_network` is specified but `ip6_gateway` is not specified or is invalid, default to `<ip6_network>::1`.

`flag_dhcp4` specifies that DHCPv4 should be used for the IPv4 network.

`dhcp4_start` specifies an IP address for the start of the DHCPv4 IP pool. If `flag_dhcp4` is specified but `dhcp4_start` is not specified or is invalid, return a failure.

`dhcp4_end` specifies an IP address for the end of the DHCPv4 IP pool. If `flag_dhcp4` is specified but `dhcp4_end` is not specified or is invalid, return a failure.

#### `/api/v1/network/<network>/modify`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: `vni`, `nettype` `domain`, `ip4_network`, `ip4_gateway`, `ip6_network`, `ip6_gateway`, `flag_dhcp4`, `dhcp4_start`, `dhcp4_end`

Modify the options of an existing virtual network with description `<network>`.

All values are optional and are identical to the values for `add`. Only those values specified will be updated.

**NOTE:** Changing the `vni` or `nettype` of a virtual network is technically possible, but is not recommended. This would require updating all VMs in the network. It is usually advisable to create a new virtual network with the new VNI and type, move VMs to it, then finally remove the old virtual network.

#### `/api/v1/network/<network>/remove`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Remove a virtual network with description `<network>`.

#### `/api/v1/network/<network>/dhcp`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: `limit`, `flag_static`

Return a JSON document containing information about all active DHCP leases in virtual network with description `<network>`.

If `limit` is specified, return a JSON document containing information about all active DHCP leases with MAC addresses matching `limit` as fuzzy regex.

If `flag_static` is specified, only return static DHCP leases.

#### `/api/v1/network/<network>/dhcp/<lease>`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about DHCP lease with MAC address `<lease>` in virtual network with description `<network>`. The output is identical to `/api/v1/network/<network>/dhcp?limit=<lease>` without fuzzy regex.

If `<lease>` is not valid, return an empty JSON document.

#### `/api/v1/network/<network>/dhcp/<lease>/add`
 * Methods: `POST`
 * Mandatory values: `ipaddress`
 * Optional values: `hostname`

Add a new static DHCP lease for MAC address `<lease>` in virtual network with description `<network>`.

`ipaddress` must be a valid IP address in the specified `<network>` IPv4 netblock, and ideally outside of the DHCPv4 range.

`hostname` specifies a static hostname hint for the lease.

#### `/api/v1/network/<network>/dhcp/<lease>/remove`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Remove a static DHCP lease for MAC address `<lease`> in virtual network with description `<network>`.

#### `/api/v1/network/<network>/acl`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: `limit`, `direction`

Return a JSON document containing information about all active NFTables ACLs in virtual network with description `<network>`.

If `limit` is specified, return a JSON document containing information about all active NFTables ACLs with descriptions matching `limit` as fuzzy regex.

If `direction` is specified and is one of `in` or `out`, return a JSON codument listing all active NFTables ACLs in the specified direction only. If `direction` is invalid, return a failure.

#### `/api/v1/network/<network>/acl/<acl>`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about NFTables ACL with description `<acl>` in virtual network with description `<network>`. The output is identical to `/api/v1/network/<network>/acl?limit=<acl>` without fuzzy regex.

If `<acl>` is not valid, return an empty JSON document.

#### `/api/v1/network/<network>/acl/<acl>/add`
 * Methods: `POST`
 * Mandatory values: `direction`, `rule`
 * Optional values: `order`

Add a new NFTables ACL with description `<acl>` in virtual network with description `<network>`.

`direction` must be one of `in` or `out`.

`rule` must be a valid NFTables rule string. PVC does no special replacements or variables beyond what NFTables itself is capable of. For per-host ACLs, it is usually advisable to use a static DHCP lease as well to control the VM's IP address.

`order` specifies the order of the rule in the current chain. If not specified, the rule will be placed at the end of the rule chain.

#### `/api/v1/network/<network>/acl/<acl>/remove`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Remove an NFTables ACL with description `<acl>` from virtual network with description `<network>`.

### Ceph endpoints

These endpoints manage PVC Ceph storage cluster state and operation.

**NOTE:** Unlike the other API endpoints, Ceph endpoints will wait until the command completes successfully before returning. This is a safety measure to prevent the critical storage subsystem from going out-of-sync with the PVC Zookeeper database; the cluster objects are only created after the storage subsystem commands complete. Because of this, *be careful with HTTP timeouts when running Ceph commands via the API*. 30s or longer may be required for some commands, especially OSD addition or removal.

#### `/api/v1/ceph`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about the current Ceph cluster status.

#### `/api/v1/ceph/osd`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: `limit`

Return a JSON document containing information about all Ceph OSDs in the storage cluster.

If `limit` is specified, return a JSON document containing information about all Ceph OSDs with names matching `limit` as fuzzy regex.

#### `/api/v1/ceph/osd/<osd>`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about Ceph OSD with ID `<osd>` in the storage cluster. Unlike other similar endpoints, this is **NOT** equivalent to any limit within the list, since that limit is based off names rather than just the ID.

#### `/api/v1/ceph/osd/set`
 * Methods: `POST`
 * Mandatory values: `option`
 * Optional values: N/A

Set a global Ceph OSD option on the storage cluster.

`option` must be a valid option to the `ceph osd set` command, e.g. `noout` or `noscrub`.

#### `/api/v1/ceph/osd/unset`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Unset a global Ceph OSD option on the storage cluster.

`option` must be a valid option to the `ceph osd unset` command, e.g. `noout` or `noscrub`.

#### `/api/v1/ceph/osd/<node>/add`
 * Methods: `POST`
 * Mandatory values: `device`, `weight`
 * Optional values: N/A

Add a new Ceph OSD to PVC node with name `<node>`.

`device` must be a valid block device on the specified `<node>`, e.g. `/dev/sdb`.

`weight` must be a valid Ceph OSD weight, usually `1.0` if all OSD disks are the same size.

#### `/api/v1/ceph/osd/<osd>/remove`
 * Methods: `POST`
 * Mandatory values: `flag_yes_i_really_mean_it`
 * Optional values: N/A

Remove a Ceph OSD device with ID `<osd>` from the storage cluster.

**NOTE:** This is a command with potentially dangerous unintended consequences that should not be scripted. To acknowledge the danger, the `flag_yes_i_really_mean_it` must be set or the endpoint will return a failure.

**WARNING:** Removing an OSD without first setting it `out` (and letting it flush) triggers an unclean PG recovery. This could potentially cause data loss if other OSDs were to fail or be removed. OSDs should not normally be removed except in the case of failed OSDs during replacement or during a replacement with a larger disk.

#### `/api/v1/ceph/osd/<osd>/in`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Set in (active) a Ceph OSD device with ID `<osd>` in the storage cluster.

#### `/api/v1/ceph/osd/<osd>/out`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Set out (inactive) a Ceph OSD device with ID `<osd>` in the storage cluster.

#### `/api/v1/ceph/pool`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: `limit`

Return a JSON document containing information about all Ceph RBD pools in the storage cluster.

If `limit` is specified, return a JSON document containing information about all Ceph RBD pools with names matching `limit` as fuzzy regex.

#### `/api/v1/ceph/pool/<pool>`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about Ceph RBD pool with name `<pool>`. The output is identical to `/api/v1/ceph/pool?limit=<pool>` without fuzzy regex.

#### `/api/v1/ceph/pool/<pool>/add`
 * Methods: `POST`
 * Mandatory values: `pgs`
 * Optional values: N/A

Add a new Ceph RBD pool with name `<pool>` to the storage cluster.

`pgs` must be a valid number of Placement Groups for the pool, taking into account the number of OSDs and the replication of the pool (`copies=3`). `256` is a safe number for 3 nodes and 2 disks per node. This value can be grown later via `ceph` commands as required.

#### `/api/v1/ceph/pool/<pool>/remove`
 * Methods: `POST`
 * Mandatory values: `flag_yes_i_really_mean_it`
 * Optional values: N/A

Remove a Ceph RBD pool with name `<pool>` from the storage cluster.

**NOTE:** This is a command with potentially dangerous unintended consequences that should not be scripted. To acknowledge the danger, the `flag_yes_i_really_mean_it` must be set or the endpoint will return a failure.

**WARNING:** Removing an RBD pool will delete all data on that pool, including all Ceph RBD volumes on the pool. Do not run this command lightly and without ensuring the pool is safely removable first.

#### `/api/v1/ceph/volume`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: `pool`, `limit`

Return a JSON document containing information about all Ceph RBD volumes in the storage cluster.

If `pool` is specified, return a JSON document containing information about all Ceph RBD volumes in Ceph RBD pool with name `pool`.

If `limit` is specified, return a JSON document containing information about all Ceph RBD volumes with names matching `limit` as fuzzy regex.

#### `/api/v1/ceph/volume/<pool>/<volume>`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about Ceph RBD volume with name `<volume>` in Ceph RBD pool with name `<pool>`. The output is identical to `/api/v1/ceph/volume?pool=<pool>&limit=<volume>` without fuzzy regex.

#### `/api/v1/ceph/volume/<pool>/<volume>/add`
 * Methods: `POST`
 * Mandatory values: `size`
 * Optional values: N/A

Add a new Ceph RBD volume with name `<volume>` to Ceph RBD pool with name `<pool>`.

`size` must be a valid size, in bytes or a single-character metric prefix of bytes, e.g. `1073741824` (1GB), `4096M`, or `2G`.

#### `/api/v1/ceph/volume/<pool>/<volume>/remove`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Remove a Ceph RBD volume with name `<volume>` from Ceph RBD pool `<pool>`.

#### `/api/v1/ceph/volume/snapshot`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: `pool`, `volume`, `limit`

Return a JSON document containing information about all Ceph RBD volume snapshots in the storage cluster.

If `pool` is specified, return a JSON document containing information about all Ceph RBD volume snapshots in Ceph RBD pool with name `pool`.

If `volume` is specified, return a JSON document containing information about all Ceph RBD volume snapshots of Ceph RBD volume with name `volume`.

If `limit` is specified, return a JSON document containing information about all Ceph RBD volume snapshots with names matching `limit` as fuzzy regex.

The various limit options can be combined freely, e.g. one can specify a `volume` without `pool`, which would match all snapshots of the named volume(s) regardless of pool, or a `pool` and `limit` without a `volume`, which would match all named snapshots on any volume in `pool`.

#### `/api/v1/ceph/volume/snapshot/<pool>/<volume>/<snapshot>`
 * Methods: `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about Ceph RBD volume snapshot with name `<snapshot>` of Ceph RBD volume with name `<volume>` in Ceph RBD pool with name `<pool>`. The output is identical to `/api/v1/ceph/volume?pool=<pool>&volume=<volume>&limit=<snapshot>` without fuzzy regex.

#### `/api/v1/ceph/volume/snapshot/<pool>/<volume>/<snapshot>/add`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Add a new Ceph RBD volume snapshot with name `<volume>` of Ceph RBD volume with name `<volume>` on Ceph RBD pool with name `<pool>`.

#### `/api/v1/ceph/volume/snapshot/<pool>/<volume>/<snapshot>/remove`
 * Methods: `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Remove a Ceph RBD volume snapshot with name `<volume>` of Ceph RBD volume with name `<volume>` on Ceph RBD pool with name `<pool>`.

Return a JSON `message` indicating either success and HTTP code 200, or failure and HTTP code 510.
