# PVC Node Daemon architecture

The PVC Node Daemon is the heart of the PVC system and runs on each node to manage the state of the node and its configured resources. The daemon connects directly to the Zookeeper cluster for coordination and state.

The node daemon is build using Python 3.X and is packaged in the Debian package `pvc-daemon`.

Configuration of the daemon is documented in [the manual](/manuals/daemon), however it is recommended to use the [Ansible configuration interface](/manuals/ansible) to configure the PVC system for you from scratch.

## Overall architecture

The PVC daemon is object-oriented - each cluster resource is represented by an Object, which is then present on each node in the cluster. This allows state changes to be reflected across the entire cluster should their data change.

During startup, the system scans the Zookeeper database and sets up the required objects. The database is then watched in real-time for additional changes to the database information.

## Startup sequence

The daemon startup sequence is documented below. The main daemon entry-point is `Daemon.py` inside the `pvcnoded` folder, which is called from the `pvcnoded.py` stub file.

0. The configuration is read from `/etc/pvc/pvcnoded.yaml` and the configuration object set up.

0. Any required filesystem directories, mostly dynamic directories, are created.

0. The logger is set up. If file logging is enabled, this is the state when the first log messages are written.

0. Host networking is configured based on the `pvcnoded.yaml` configuration file. In a normal cluster, this is the point where the node will become reachable on the network as all networking is handled by the PVC node daemon.

0. Sysctl tweaks are applied to the host system, to enable routing/forwarding between nodes via the host.

0. The node determines its coordinator state and starts the required daemons if applicable. In a normal cluster, this is the point where the dependent services such as Zookeeper, FRR, and Ceph become available. After this step, the daemon waits 5 seconds before proceeding to give these daemons a chance to start up.

0. The daemon connects to the Zookeeper cluster and starts its listener. If the Zookeeper cluster is unavailable, it will wait some time before abandoning the attempt and starting again from step 1.

0. Termination handling/cleanup is configured.

0. The node checks if it is already present in the Zookeeper cluster; if not, it will add itself to the database. Initial static options are also updated in the database here. The daemon state transitions from `stop` to `init`.

0. The node checks if Libvirt is accessible.

0. The node starts up the NFT firewall if applicable and configures the base rule-set.

0. The node ensures that `dnsmasq` is stopped (legacy check, might be safe to remove eventually).

0. The node begins setting up the object representations of resources, in order:

    a. Node entries

    b. Network entries, creating client networks and starting them as required.

    c. Domain (VM) entries, starting up the VMs as required.

    d. Ceph storage entries (OSDs, Pools, Volumes, Snapshots).

0. The node activates its keepalived timer and begins sending keepalive updates to the cluster. The daemon state transitions from `init` to `run` and the system has started fully.

# PVC Node Daemon manual

The PVC node daemon ins build with Python 3 and is run directly on nodes. For details of the startup sequence and general layout, see the [architecture document](/architecture/daemon).

## Configuration

The Daemon is configured using a YAML configuration file which is passed in to the API process by the environment variable `PVCD_CONFIG_FILE`. When running with the default package and SystemD unit, this file is located at `/etc/pvc/pvcnoded.yaml`.

For most deployments, the management of the configuration file is handled entirely by the [PVC Ansible framework](/manuals/ansible) and should not be modified directly. Many options from the Ansible framework map directly into the configuration options in this file.

### Conventions

* Settings may be `required`, `optional`, or `ignored`.

* Settings may `depends` on other settings. This indicates that, if one setting is enabled, the other setting is very likely `required` by that setting.

### `pvcnoded.yaml`

Example configuration:

```
pvc:
  node: pvchv1
  debug: False
  functions:
    enable_hypervisor: True
    enable_networking: True
    enable_storage: True
    enable_api: True
  cluster:
    coordinators:
      - pvchv1
      - pvchv2
      - pvchv3
    networks:
      upstream:
        domain: "mydomain.net"
        network: "1.1.1.0/24"
        floating_ip: "1.1.1.10/24"
        gateway: "1.1.1.1"
      cluster:
        domain: "pvc.local"
        network: "10.255.0.0/24"
        floating_ip: "10.255.0.254/24"
      storage:
        domain: "pvc.storage"
        network: "10.254.0.0/24"
        floating_ip: "10.254.0.254/24"
  coordinator:
    dns:
      database:
        host: localhost
        port: 5432
        name: pvcdns
        user: pvcdns
        pass: pvcdnsPassw0rd
    metadata:
      database:
        host: localhost
        port: 5432
        name: pvcapi
        user: pvcapi
        pass: pvcapiPassw0rd
  system:
    fencing:
      intervals:
        keepalive_interval: 5
        fence_intervals: 6
        suicide_intervals: 0
      actions:
        successful_fence: migrate
        failed_fence: None
      ipmi:
        host: pvchv1-lom
        user: admin
        pass: Passw0rd
    migration:
      target_selector: mem
    configuration:
      directories:
        dynamic_directory: "/run/pvc"
        log_directory: "/var/log/pvc"
        console_log_directory: "/var/log/libvirt"
      logging:
        file_logging: True
        stdout_logging: True
        log_colours: True
        log_dates: True
        log_keepalives: True
        log_keepalive_cluster_details: True
        log_keepalive_storage_details: True
        console_log_lines: 1000
      networking:
        bridge_device: ens4
        sriov_enable: True
        sriov_device:
          - phy: ens1f0
            mtu: 9000
            vfcount: 7
        upstream:
          device: ens4
          mtu: 1500
          address: None
        cluster:
          device: ens4
          mtu: 1500
          address: by-id
        storage:
          device: ens4
          mtu: 1500
          address: by-id
```

#### `node`

* *required*

The (short) hostname of the node; host-specific.

#### `debug`

* *required*

Whether to enable or disable debug mode. Debug mode enables additional logging of subtasks throughout the system.

#### `functions` → `enable_hypervisor`

* *required*

Whether to enable the hypervisor functionality of the PVC Daemon or not. This should usually be enabled except in advanced deployment scenarios (such as a dedicated quorum-keeping micro-node or dedicated network routing node).

#### `functions` → `enable_networking`

* *required*

Whether to enable the client network functionality of the PVC Daemon or not. This should usually be enabled except in deployment scenarios where networking is completely unmanaged by PVC.

#### `functions` → `enable_storage`

* *required*

Whether to enable the virtual storage functionality of the PVC Daemon or not. This should usually be enabled except in advanced deployment scenarios featuring unmanaged external storage.

#### `functions` → `enable_api`

Whether to enable the PVC API client on the cluster floating IPs or not.

#### `cluster` → `coordinators`

* *required*

A list of coordinator hosts, used to generate the Zookeeper connection string and determine if the current host is a coordinator or not
.

#### `cluster` → `networks`

* *optional*
* *requires* `functions` → `enable_networking`

Contains a dictionary of networks and their configurations for the PVC cluster. Optional only if `enable_networking` is `False`. The three required network types/names are `upstream`, `cluster`, and `storage`. Each network type contains the following entries.

##### `domain`

* *required*

The domain name for the network. Should be a valid domain name, or `None`. Specifically for the `upstream` network, this should match the domain portion of the node hostname.

##### `network`

The CIDR-formatted IPv4 address block for the network.

##### `floating_ip`

The CIDR-formatted IPv4 address for the floating IP within the network. This IP will belong exclusively to the `primary` coordinator node to provide a central entrypoint for functionality on the cluster.

##### `gateway`

The IPv4 address for the gateway of the network. Usually applicable only to the `upstream` network, as the other two are normally unrouted and local to the cluster.

#### `coordinator` 

* *optional*
* *requires* `functions` → `enable_networking`

Configuration for coordinator functions on the node. Optional only if `enable_networking` is `False`. Not optional on non-coordinator hosts, though unused. Contains the following sub-entries.

##### `dns` → `database` → `host`

* *required*

The hostname of the PostgreSQL instance for the DNS aggregator database. Should always be `localhost` except in advanced deployment scenarios.

##### `dns` → `database` → `port`

* *required*

The port of the PostgreSQL instance for the DNS aggregator database. Should always be `5432`.

##### `dns` → `database` → `name`

* *required*

The database name for the DNS aggregator database. Should always be `pvcdns`.

##### `dns` → `database` → `user`

* *required*

The username for the PVC node daemon to access the DNS aggregator database.

##### `dns` → `database` → `pass`

* *required*

The password for the PVC node daemon to access the DNS aggregator database.

##### `metadata` → `database` → `host`

* *required*

The hostname of the PostgreSQL instance for the Provisioner database. Should always be `localhost` except in advanced deployment scenarios.

##### `metadata` → `database` → `port`

* *required*

The port of the PostgreSQL instance for the Provisioner database. Should always be `5432`.

##### `metadata` → `database` → `name`

* *required*

The database name for the Provisioner database. Should always be `pvcapi`.

##### `metadata` → `database` → `user`

* *required*

The username for the PVC node daemon to access the Provisioner database.

##### `metadata` → `database` → `pass`

* *required*

The password for the PVC node daemon to access the Provisioner database.

#### `system` → `intervals` → `keepalive_interval`

* *required*

The number of seconds between keepalive messages to the cluster. The default is 5 seconds; for slow cluster nodes, 10-30 seconds may be more appropriate however this will result in slower responses to changes in the cluster and less accurate/up-to-date information in the clients.

#### `system` → `intervals` → `fence_intervals`

* *required*

The number of keepalive messages that can be missed before a node is considered dead and the fencing cycle triggered on it. The default is 6, or 30 seconds of inactivity with a 5 second `keepalive_interval`. Can be set to 0 to disable fencing as the timeout will never trigger.

#### `system` → `intervals` → `suicide_intervals`

* *required*

The number of keepalive message that can be missed before a node considers itself dead and forcibly resets itself. Note that, due to the large number of reasons a node could become unresponsive, the suicide interval alone should not be relied upon. The default is 0, which disables this functionality. If set, should usually be equal to or less than `fence_intervals` for maximum safety.

#### `system` → `fencing` → `actions` → `successful_fence`

* *required*

The action to take regarding VMs once a node is *successfully* fenced, i.e. the IPMI command to restart the node reports a success. Can be one of `migrate`, to migrate and start all failed VMs on other nodes and the default, or `None` to perform no action.

#### `system` → `fencing` → `actions` → `failed_fence`

* *required*

The action to take regarding VMs once a node fencing *fails*, i.e. the IPMI command to restart the node reports a failure. Can be one of `None`, to perform no action and the default, or `migrate` to migrate and start all failed VMs on other nodes.

**WARNING:** This functionality is potentially **dangerous** and can result in data loss or corruption in the VM disks; the post-fence migration process *explicitly clears RBD locks on the disk volumes*. It is designed only for specific and advanced use-cases, such as servers that do not reliably report IPMI responses or servers without IPMI (not recommended; see the [cluster architecture documentation](/architecture/cluster)). If this is set to `migrate`, the `suicide_intervals` **must** be set to provide at least some guarantee that the VMs on the node will actually be terminated before this condition triggers. The administrator should think very carefully about their setup and potential failure modes before enabling this option.

#### `system` → `fencing` → `ipmi` → `host`

* *required*

The hostname or IP address of this node's IPMI interface. Must be reachable from the nodes.

#### `system` → `fencing` → `ipmi` → `user`

* *required*

The username for the PVC node daemon to log in to the IPMI interface. Must have permission to reboot the host (command `ipmitool chassis power reset`).

#### `system` → `fencing` → `ipmi` → `pass`

* *required*

The password for the PVC node daemon to log in to the IPMI interface.

#### `system` → `migration` → `target_selector`

* *required*

The selector algorithm to use when migrating hosts away from the node. Valid `selector` values are: `mem`: the node with the least allocated VM memory; `vcpus`: the node with the least allocated VM vCPUs; `load`: the node with the least current load average; `vms`: the node with the least number of provisioned VMs.

#### `system` → `configuration` → `directories` → `dynamic_directory`

* *required*

The directory to store ephemeral configuration files. Usually `/run/pvc` or a similar temporary directory.

#### `system` → `configuration` → `directories` → `log_directory`

* *required*

The directory to store log files for `file_logging`. Usually `/var/log/pvc` or a similar directory. Must be specified even if `file_logging` is `False`, though ignored.

#### `system` → `configuration` → `directories` → `console_log_directory`

* *required*

The directory to store VM console logs. Usually `/var/log/libvirt` or a similar directory.

#### `system` → `configuration` → `logging` → `file_logging`

* *required*

Whether to enable direct logging to a file in `log_directory` or not.

#### `system` → `configuration` → `logging` → `stdout_logging`

* *required*

Whether to enable logging to stdout or not; captured by SystemD and JournalD by default.

#### `system` → `configuration` → `logging` → `log_colours`

* *required*

Whether to log ANSI colour sequences in the log output or not.

#### `system` → `configuration` → `logging` → `log_dates`

* *required*

Whether to log the current date and time in the log output or not.

#### `system` → `configuration` → `logging` → `log_keepalives`

* *required*

Whether to log keepalive messages or not.

#### `system` → `configuration` → `logging` → `log_keepalive_cluster_details`

* *required*

Whether to log node status information during keepalives or not.

#### `system` → `configuration` → `logging` → `log_keepalive_storage_details`

* *required*

Whether to log storage cluster status information during keepalives or not.

#### `system` → `configuration` → `logging` → `console_log_lines`

* *required*

How many lines of VM console logs to keep in the Zookeeper database for each VM.

#### `system` → `configuration` → `networking` → `bridge_device`

* *optional*
* *requires* `functions` → `enable_networking`

The network interface device used to create Bridged client network vLANs on. For most clusters, should match the underlying device of the various static networks (e.g. `ens4` or `bond0`), though may also use a separate network interface.

#### `system` → `configuration` → `networking` → `sriov_enable`

* *optional*, defaults to `False`
* *requires* `functions` → `enable_networking`

Enables (or disables) SR-IOV functionality in PVC. If enabled, at least one `sriov_device` entry should be specified.

#### `system` → `configuration` → `networking` → `sriov_device`

* *optional*
* *requires* `functions` → `enable_networking`

Contains a list of SR-IOV PF (physical function) devices and their basic configuration. Each element contains the following entries:

##### `phy`:

* *required*

The raw Linux network device with SR-IOV PF functionality.

##### `mtu`

The MTU of the PF device, set on daemon startup.

##### `vfcount`

The number of VF devices to create on this PF. VF devices are then managed via PVC on a per-node basis.

#### `system` → `configuration` → `networking`

* *optional*
* *requires* `functions` → `enable_networking`

Contains a dictionary of networks and their configurations on this node. Optional only if `enable_networking` is `False`. The three required network types/names are `upstream`, `cluster`, and `storage`. Each network type contains the following entries.

##### `device`

* *required*

The raw Linux network device that the network exists on.

##### `mtu`

* *required*

The MTU of the network device.

##### `address`

* *required*

The IPv4 address of the interface. Can be one of: `None`, for no IP address; `by-id`, to automatically select an address in the relevant `networks` section via the host ID (e.g. node1 will get `.1`, node2 will get `.2`, etc.); or a static CIDR-formatted IP address.
