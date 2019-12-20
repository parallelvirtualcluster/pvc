# PVC HTTP API manual

The PVC HTTP API client is built with Flask, a Python framework for creating API interfaces, and run directly with the PyWSGI framework. It interfaces directly with the Zookeeper cluster to send and receive information about the cluster. It supports authentication configured statically via tokens in the configuration file as well as SSL. It also includes the provisioner client, an optional section that can be used to create VMs automatically using a set of templates and standardized scripts.

The [`pvc-ansible`](https://github.com/parallelvirtualcluster/pvc-ansible) framework will install and configure the API by default, and enable the node daemon option for an instance of the API to follow the primary node, thus ensuring the API is listening on the upstream floating IP at all times.

## API Details

### SSL

The API accepts SSL certificate and key files via the `pvc-api.yaml` configuration to enable SSL support for the API, which protects the data and query values from snooping or tampering. SSL is strongly recommended if using the API outside of a trusted local area network.

### API authentication

Authentication for the API is available using a static list of tokens. These tokens can be any long string, but UUIDs are typical and simple to use. Within `pvc-ansible`, the list of tokens can be specified in the `pvc.yaml` `group_vars` file. Usually, you'd want one token for each user of the API, such as a WebUI, a 3rd-party client, or an administrative user. Within the configuration, each token can have a description; this is mostly for administrative clarity and is not actually used within the API itself.

The API provides session-based login using the `/api/v1/auth/login` and `/api/v1/auth/logout` options. If authentication is not enabled, these endpoints return a JSON `message` of `Authentication is disabled` and HTTP code 200.

For one-time authentication, the `token` value can be specified to any API endpoint via the `X-Api-Key` header value. This is only checked if there is no valid session already established. If authentication is enabled, there is no valid session, and no `token` value is specified, the API will return a JSON `message` of `Authentication required` and HTTP code 401.

### Values

The PVC API consistently accepts values (variables) as either HTTP query string arguments, or as HTTP POST form body arguments, in either GET or POST mode.

Some values are `` values; these do not require a data component, and signal an option by their presence.

### Data formats

The PVC API consistently accepts HTTP POST commands of HTML form documents. However, since all form arguments can also be specified as query parameters, and only the `vm define` endpoint accepts a significant amount of data in one argument, it should generally be compatible with API clients speaking only JSON - these can simply send no data in the body and send all required values as query parameters.

The PCI API consistently returns JSON bodies as its responses, with the one exception of the `vm dump` endpoint which returns an XML body. For all POST endpoints, unless otherwise specified below, this is a `message` value containing a human-readable message about the success or failure of the command. The HTTP return code is always 200 for a success or 510 for a failure. For all GET endpoints except the mentioned `vm dump`, this is a JSON body containing the requested data.

## Provisioner

The provisioner subsection (`/api/v1/provisioner`) is used to create new virtual machines on a PVC cluster. By creating templates and scripts, then grouping these into profiles, VMs can be created based on dynamic, declarative configurations via direct installation or templating. Administrators can use this facility to automate the creation VMs running most *NIX instances that can be installed in a parent host, or by using templates as a base for new VMs. It can also create VMs based on existing templates or ISO images to facilitate installing alternate operating systems such as Microsoft Windows.

### Templates

Templates are used to configure the four components that define a VM configuration. Templates can be created and managed via the API, then grouped into profiles.

#### System Templates

System templates define the basic configuration of a VM. This includes the number of vCPUs and amount vRAM, as well as console access (either VNC or serial) and several pieces of PVC metadata.

Generally, a system template is usable across multiple VM profiles, so there will generally be a small number of system templates defining several standard resource profiles that can then be reused.

Some elements of the system template are mandatory, but most are optional.

###### Example: Creating a system template

* Note: vRAM sizes are always specified in MB.

```
curl -X POST http://localhost:7370/api/v1/provisioner/template/system?name=2cpu-1gb-serial\&vcpus=2\&vram=1024\&serial=true\&vnc=false\&node_limit='pvchv1,pvchv2'\&node_selector=mem\&start_with_node=false
curl -X GET http://localhost:7370/api/v1/provisioner/template/system/2cpu-1gb-serial
```

#### Network Templates

Network templates define the network configuration of a VM. These are tied into the PVC networking facility, and are quite simple. A MAC template is assigned to each template, which defines how MAC addresses are generated (either randomly, or via a simple templating system for static MAC addresses).

With a network template, various "nets" can be configured. A "net" defines a PVC virtual network VNI, which must be valid on the PVC cluster. The first net is assigned to the first Ethernet device (usually eth0 or ens2 in Linux), with each subsequent network being added as an additional interface in order.

###### Example: Creating a network template with two networks

```
curl -X POST http://localhost:7370/api/v1/provisioner/template/network?name=net200+net300
curl -X POST http://localhost:7370/api/v1/provisioner/template/network/net200+net300/net?vni=200
curl -X POST http://localhost:7370/api/v1/provisioner/template/network/net200+net300/net/300
curl -X GET http://localhost:7370/api/v1/provisioner/template/net200+net300

#### Storage Templates

Storage templates define the Ceph RBD disks, as well as optional filesystems and mountpoints for Linux-based guests, of a VM. The template itself consists only of a name; disk or image entries are configured as additional elements similar to network templates.

Each disk in a storage template is identified by a sequential ID, usually "sda"/"vda", "sdb"/"vdb", etc., a size, and a Ceph RBD pool within the PVC cluster. These alone are all that are required, and will create raw, unformatted images of the specified size, on the specified pool, and attached to the VM at the ID value. In addition to these basics, filesystems (with argument support) and mountpoints can also be specified. Filesystems specified here will be used to format the volume during the provisioning process, and mountpoints will mount the volume at the specified mountpoint during provisioning, so that a guest operating system can be installed on them during the process with a provisioning script.

In addition to disks, storage templates can also contain image entries. Like disk entries, they are identified by a sequential ID, as well as a source Ceph RBD pool and volume name. The specified volume may belong to a (shutdown) VM or be a dedicated template uploaded to the Ceph cluster.

###### Example: Creating a storage template with three mounted disks

* Note: You can also include the template name during creation.
* Note: Disk sizes are always specified in GB.
* Note: Filesystem arguments are passed as-is to the `mkfs` command and must use an `--opt=val` format to prevent splitting.

```
curl -X POST http://localhost:7370/api/v1/provisioner/template/storage/ext4-root-var-log
curl -X POST http://localhost:7370/api/v1/provisioner/template/storage/ext4-root-var-log/disk?disk_id=sda\&disk_size=4\&filesystem=ext4\&mountpoint=/\&pool=vms\&filesystem_arg='-L=root'
curl -X POST http://localhost:7370/api/v1/provisioner/template/storage/ext4-root-var-log/disk/sdb?disk_size=4\&filesystem=ext4\&mountpoint=/var\&pool=vms\&filesystem_arg='-L=var'
curl -X POST http://localhost:7370/api/v1/provisioner/template/storage/ext4-root-var-log/disk/sdc -d "disk_size=4\&filesystem=ext4\&mountpoint=/var/log\&pool=vms\&filesystem_arg='-L=log'\&filesystem_arg='-m=1'"
curl -X GET http://localhost:7370/api/v1/provisioner/template/storage/ext4-root-var-log
```

#### Userdata Templates

Userdata templates contain cloud-init metadata that can be provided to VMs on their first boot. It is accessible via an EC2-compatible API running on the PVC cluster to VMs. A userdata template contains the full text of the userdata, including optional multi-part sections if desired.

A default userdata template called "empty" is created by default, and this can be used for any profile which does not require cloud-init userdata, since a template must always be specified.

Examples of userdata templates can be found in `/usr/share/pvc/provisioner/examples` when the API is installed.

###### Example: Creating a userdata template from the `userdata.yaml` example file

* Note: For the block text commands (userdata and scripts), using the HTTP POST body for the data is always better than a URL argument.

```
curl -X POST http://localhost:7370/api/v1/provisioner/template/userdata?name=example-userdata -d "data=$( cat /usr/share/pvc/provisioner/examples/userdata.yaml )"
curl -X GET http://localhost:7370/api/v1/provisioner/template/userdata?name=example-userdata
```

### Scripts

Scripts automate the installation of VMs with Python. To make use of a script, at least one disk volume must be both formatted with a Linux-compatible filesyste, and have a mountpoint (very likely `/`) configured. The specified disk is then mounted in a temporary directory on the active coordinator, and the script run against it. This script can then do any task required to set up and configure the VM, such as installing a Debian or Ubuntu system with debootstrap, obtaining a chroot and configuring GRUB, or almost any other task that the administrator may wish. All scripts are written in Python 3, which is then integrated into the provisioner's worker during VM creation and executed at the appropriate point.

Each script must contain a function called `install()` which accepts `**kwargs` and no other arguments. A number of default arguments are provided, including `vm_name`, the `temporary_directory`, and dictionaries of the `disks` and `networks`. Additional arguments can be specified in VM profiles to facilitate advanced configurations specific to particular VM types.

Examples of scripts can be found in `/usr/share/pvc/provisioner/examples` when the API is installed.

###### Example: Creating a script from the `debootstrap_script.py` example file

* Note: For the block text commands (userdata and scripts), using the HTTP POST body for the data is always better than a URL argument.

```
curl -X POST http://localhost:7370/api/v1/provisioner/script/debootstrap-example -d "data=$( cat /usr/share/pvc/provisioner/examples/userdata.yaml )"
curl -X GET http://localhost:7370/api/v1/provisioner/script/debootstrap-example
```

### Profiles

Profiles group together the four template types and scripts, as well as optional script arguments, into a named profile which can be assigned to VMs on creation. When creating a VM, templates and scripts themselves are not explicitly specified; rather a profile is specified which then maps to these other values. This allows maximum flexibility, allowing a VM profile to combine the various templates and scripts in an arbitrary way. One potential usecase is to create a profile for a particular VM role, for instance a webserver, which will have a specific system, disk, network, and userdata configuration; multiple VMs can then be created with this profile to ensure they all contain the same resources and configuration.

###### Example: Creating a profile with the previously-created templates and some script arguments

* Note: Script arguments are specified as `name=value` pairs after the `arg=` argument.

```
curl -X POST http://localhost:7370/api/v1/provisioner/profile/test-profile?system_template=2cpu-1gb-serial\&network_template=net200+net300\&disk_template=ext4-root-var-log\&userdata_template=example-userdata\&script=debootstrap-example\&arg=deb_release=buster\&arg=deb_mirror=http://deb.debian.org/debian\&arg=deb_packages=linux-image-amd64,grub-pc,cloud-init,python3-cffi-backend,wget
curl -X GET http://localhost:7370/api/v1/provisioner/profile/test-profile
```

### Creating VMs

VMs are created by specifying a name and a profile value. The provisioner API will then collect the details of the profile, and trigger the Celery worker (`pvc-provisioner-worker.service`) to begin creating the VM. The administrator can, at any point, obtain the status of the process via the Task ID, which is returned in the JSON body of the creation command. Once completed, by default, the resulting VM will be defined and started on the cluster, ready to use. If the VM uses cloud-init, it will then hit the Metadata API on startup to obtain the details of the VM as well as the userdata specified in the profile.

Additional options can also be specified at install time. Automatic definition of the VM and automatic startup of the VM can both be disabled via options to the creation command. The former is most useful when creating disk images from an installed set of VM disks, and the latter provides flexibility for the administrator to edit or review the final VM before starting it for the first time.

###### Example: Creating a VM and viewing its status

```
curl -X POST http://localhost:7370/api/v1/provisioner/create?name=test1\&profile=test-profile
curl -X GET http://localhost:7370/api/v1/provisioner/status/<task-id>
```

## API Daemon Configuration

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

## Primary Client API endpoint documentation

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
 * Optional values: `node`, `limit`, `selector`, `autostart`

Define a new VM with Libvirt XML configuration `xml` (either single-line or human-readable multi-line).

If `node` is specified and is valid, the VM will be assigned to `node` instead of automatically determining the target node. If `node` is specified and not valid, auto-selection occurs instead.

If `limit` is speficied, the node will not be allowed to run on nodes not specified in the limit.

The `limit` value must be a comma-separated list of nodes; invalid nodes are ignored.

If `selector` is specified and no specific and valid `node` is specified, the automatic node determination will use `selector` to determine the optimal node instead of the default for the cluster. This value is stored as PVC metadata for this VM and is used in subsequent migrate (including node flush) and fence recovery operations.

Valid `selector` values are: `mem`: the node with the least allocated VM memory; `vcpus`: the node with the least allocated VM vCPUs; `load`: the node with the least current load average; `vms`: the node with the least number of provisioned VMs.

If `autostart` is specified, the VM will be set to autostart on the next node unflush/ready operation of the home node. This metadata value is reset to False by the node daemon on each successful use.

**NOTE:** The `POST` operation assumes that the VM resources (i.e. disks, operating system, etc.) are already created. This is equivalent to the `pvc vm define` command in the PVC CLI client. *[todo v0.6]* Creating a new VM using the provisioner uses the `POST /api/vm/<vm>` endpoint instead.

#### `/api/v1/vm/<vm>`
 * Methods: `GET`, `POST`, `PUT`, `DELETE`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Return a JSON document containing information about `<vm>`. The output is identical to `GET /api/v1/vm?limit=<vm>` without fuzzy regex matching.

###### `POST`
 * Mandatory values: At least one of optional values must be specified
 * Optional values: `limit`, `selector`, `autostart`/`no-autostart`

Update the PVC metadata of `<vm>` with the specified values.

If `limit` is speficied, the node will not be allowed to run on nodes not specified in the limit.

The `limit` value must be a comma-separated list of nodes; invalid nodes are ignored.

If `selector` is specified and no specific and valid `node` is specified, the automatic node determination will use `selector` to determine the optimal node instead of the default for the cluster. This value is stored as PVC metadata for this VM and is used in subsequent migrate (including node flush) and fence recovery operations.

Valid `selector` values are: `mem`: the node with the least allocated VM memory; `vcpus`: the node with the least allocated VM vCPUs; `load`: the node with the least current load average; `vms`: the node with the least number of provisioned VMs.

If `autostart` is specified, the VM will be set to autostart on the next node unflush/ready operation of the home node. This metadata value is reset to False by the node daemon on each successful use.

If `no-autostart` is specified, an existing autostart will be disabled if applicable.

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

Return the current host node, and last host node if applicable, for `<vm>`.

###### `POST`
 * Mandatory values: `action`
 * Optional values: `node`, `selector`, `permanent`, `force`

Change the current host node for `<vm>` by `action`, using live migration if possible, and using `shutdown` then `start` if not. `action` must be either `migrate` or `unmigrate`.

If `node` is specified and is valid, the VM will be assigned to `node` instead of automatically determining the target node. If `node` is specified and not valid, auto-selection occurs instead.

If `selector` is specified and no specific and valid `node` is specified, the automatic node determination will use `selector` to determine the optimal node instead of the default for the cluster.

Valid `selector` values are: `mem`: the node with the least allocated VM memory; `vcpus`: the node with the least allocated VM vCPUs; `load`: the node with the least current load average; `vms`: the node with the least number of provisioned VMs.

If `permanent` is specified, the PVC system will not track the previous node and the VM will not be considered migrated. This is equivalent to the `pvc vm move` CLI command.

If `force` is specified, and the VM has been previously migrated, force through a new migration to the selected target and do not update the previous node value.

#### `/api/v1/vm/<vm>/locks`
 * Methods: `GET`, `POST`

###### `GET`
 * Mandatory values: N/A
 * Optional values: N/A

Not yet implemented and not planned. Return the list of RBD locks for the VM.

###### `POST`
 * Mandatory values: N/A
 * Optional values: N/A

Clear all RBD locks for volumes attached to `<vm>`.

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

`domain` specifies a DNS domain for hosts in the network. DNS is aggregated and provided for all networks on the primary coordinator node.

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

If `direction` is specified and is one of `in` or `out`, return a JSON document listing all active NFTables ACLs in the specified direction only. If `direction` is invalid, return a failure.

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
 * Mandatory values: `volume`, `pool`
 * Optional values: `size`, `source_volume`

Add a new Ceph RBD volume `<volume>` to Ceph RBD pool `<pool>`.

If `source_volume` is specified, clone the specified source volume into the new volume; when using this option, `size` is ignored.

The value for `size` is mandatory if not cloning from a `source_volume`, and must be a valid storage size, in bytes or a single-character metric prefix of bytes, e.g. `1073741824` (1GB), `4096M`, or `20G`. PVC uses multiples of 1024 (MiB, GiB, etc.) consistently.

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

## Provisioner API endpoint documentation

### Node endpoints

These endpoints manage PVC node state and operation.

#### `/api/v1/node`
 * Methods: `GET`

###### `GET`
 * Mandatory values: N/A
 * Optional values: `limit`

Return a JSON document containing information about all cluster nodes. If `limit` is specified, return a JSON document containing information about cluster nodes with names matching `limit` as fuzzy regex.

