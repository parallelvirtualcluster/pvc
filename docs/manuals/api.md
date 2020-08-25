# PVC API architecture

The PVC API is a standalone client application for PVC. It interfaces directly with the Zookeeper database to manage state.

The API is built using Flask and is packaged in the Debian package `pvc-client-api`. The API depends on the common client functions of the `pvc-client-common` package as does the CLI client.

Details of the API interface can be found in [the manual](/manuals/api).

# PVC HTTP API manual

The PVC HTTP API client is built with Flask, a Python framework for creating API interfaces, and run directly with the PyWSGI framework. It interfaces directly with the Zookeeper cluster to send and receive information about the cluster. It supports authentication configured statically via tokens in the configuration file as well as SSL. It also includes the provisioner client, an optional section that can be used to create VMs automatically using a set of templates and standardized scripts.

The [`pvc-ansible`](https://github.com/parallelvirtualcluster/pvc-ansible) framework will install and configure the API by default, and enable the node daemon option for an instance of the API to follow the primary node, thus ensuring the API is listening on the upstream floating IP at all times.

## API Details

### SSL

The API accepts SSL certificate and key files via the `pvcapid.yaml` configuration to enable SSL support for the API, which protects the data and query values from snooping or tampering. SSL is strongly recommended if using the API outside of a trusted local area network.

### API authentication

Authentication for the API is available using a static list of tokens. These tokens can be any long string, but UUIDs are typical and simple to use. Within `pvc-ansible`, the list of tokens can be specified in the `pvc.yaml` `group_vars` file. Usually, you'd want one token for each user of the API, such as a WebUI, a 3rd-party client, or an administrative user. Within the configuration, each token can have a description; this is mostly for administrative clarity and is not actually used within the API itself.

The API provides session-based login using the `/api/v1/auth/login` and `/api/v1/auth/logout` options. If authentication is not enabled, these endpoints return a temporary redirect to the root (version) endpoint.

For one-time authentication, the `token` value can be specified to any API endpoint via the `X-Api-Key` header value. This is only checked if there is no valid session already established. If authentication is enabled, there is no valid session, and no `token` value is specified, the API will return a JSON `message` of `Authentication required` and HTTP code 401.

### Data formats

The PVC API consistently accepts HTTP POST commands of HTML form documents.

The PCI API consistently returns JSON bodies as its responses. For (most) POST endpoints and any failures (400, 401, 404, etc.), this body contains a "message" field with a text message indicating the result. For (most) GET endpoints, this body is a JSON representation of the data being provided, subject to the schema outlined in the API endpoint documentation.

## Provisioner

The provisioner subsection (`/api/v1/provisioner`) is used to create new virtual machines on a PVC cluster. By creating templates and scripts, then grouping these into profiles, VMs can be created based on dynamic, declarative configurations via direct installation or templating. Administrators can use this facility to automate the creation of VMs running most UNIX-like operating systems that can be installed in a parent host. It can also create VMs based on existing templates or ISO images to facilitate installing alternate operating systems such as Microsoft Windows.

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
```

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

The API is configured using a YAML configuration file which is passed in to the API process by the environment variable `PVC_CONFIG_FILE`. When running with the default package and SystemD unit, this file is located at `/etc/pvc/pvcapid.yaml`.

### Conventions

* Settings may be `required`, `optional`, or `ignored`.

* Settings may `depends` on other settings. This indicates that, if one setting is enabled, the other setting is very likely `required` by that setting.

### `pvcapid.yaml`

Example configuration:

```
---
pvc:
    debug: True
    coordinators:
      - pvchv1
      - pvchv2
      - pvchv3
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
    provisioner:
        database:
            host: 10.100.0.252
            port: 5432
            name: pvcapi
            user: pvcapi
            pass: pvcapi
        queue:
            host: localhost
            port: 6379
            path: /0
        ceph_cluster:
            storage_hosts:
              - pvchv1
              - pvchv2
              - pvchv3
            storage_domain: "s.bonilan.net"
            ceph_monitor_port: 6789
            ceph_storage_secret_uuid: "c416032b-2ce9-457f-a5c2-18704a3485f4"
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

##### `provisioner` → `database` → `host`

* *required*

The hostname of the PostgreSQL instance for the Provisioner database. Should always be `localhost` except in advanced deployment scenarios.

##### `provisioner` → `database` → `port`

* *required*

The port of the PostgreSQL instance for the Provisioner database. Should always be `5432`.

##### `provisioner` → `database` → `name`

* *required*

The database name for the Provisioner database. Should always be `pvcapi`.

##### `provisioner` → `database` → `user`

* *required*

The username for the PVC API client to access the Provisioner database.

##### `provisioner` → `database` → `pass`

* *required*

The password for the PVC API client to access the Provisioner database.

#### `provisioner` → `queue` → `host`

* *required*

The hostname of the Redis instance for the Provisioner queue. Should always be `localhost` except in advanced deployment scenarios.

#### `provisioner` → `queue` → `port`

* *required*

The port of the Redis innstance for the Provisioner queue. Should always be `6379`.

#### `provisioner` → `queue` → `path`

* *required*

The Redis path for the Provisioner queue. Should always be `/0`.

#### `provisioner` → `ceph_cluster` → `storage_hosts`

* *required*

A list of hosts which run the Ceph monitors for VM disks. Should usually be identical to the list of `coordinators` except in advanced deployments.

#### `provisioner` → `ceph_cluster` → `storage_domain`

* *required*

The storage domain of the cluster, used with the `storage_hosts` entires to form FQDNs for the Ceph monitors. Should usually be identical to the cluster `storage_domain` except in advanced deployments.

#### `provisioner` → `ceph_cluster` → `ceph_monitor_port`

* *required*

The Ceph monitor port. Should always be `6789`.

#### `provisioner` → `ceph_cluster` → `ceph_storage_secret_uuid`

* *required*

The Libvirt storage secret UUID for the Ceph cluster.

## API Endpoint Documentation

The full API endpoint and schema documentation [can be found here](/manuals/api-reference.html).
