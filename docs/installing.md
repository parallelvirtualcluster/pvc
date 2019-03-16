## Installing and using the Parallel Virtual Cluster suite

Note: This document describes PVC v0.4. This version of PVC implements the core functionality, with the virtual machine manager and virtual networking being fully implemented and functional. Future versions will finish implementation of virtual storage, bootstrapping, provisioning, and the API interface.

## Building

The repository contains the required elements to build Debian packages for PVC. It is not handled like a normal Python package but instead the debs contain the raw files placed in Debianized places. Only Debian Buster (10.X) is supported as the cluster base operating system.

1. Run `build-deb.sh`; you will need `dpkg-buildpackage` installed.

1. The output files for each daemon and client will be located in the parent directory.

1. Copy the `.deb` files to the target systems.

## Installing

### Virtual Manager only

PVC v0.4 requires manual setup of the base OS and Zookeeper cluster on the target systems. Future versions will include full bootstrapping support. This set of instructions covers setting up a virtual manager only system, requiring all networking and storage to be configured by the administrator. Future versions will enable these functions by default.

A single-host cluster is possible for testing, however it is not recommended for production deployments due to the lack of redundancy. For a single-host cluster, follow the steps below but only on a single machine.

1. Deploy Debian Buster to 3, or more, physical servers. Ensure the servers are configured and connected based on the [documentation](/about.md#physical-infrastructure).

1. On the first 3 physical servers, deploy Zookeeper (Debian packages `zookeeper` and `zookeeperd`) in a cluster configuration. After this, Zookeeper should be available on port `2181` on all 3 nodes.

1. Set up virtual storage and networking as required.

1. Install the PVC packages generated in the previous section. Use `apt -f install` to correct dependency issues. The `pvcd` service will fail to start; this is expected.

1. Create the `/etc/pvc/pvcd.yaml` daemon configuration file, using the template available at `/etc/pvc/pvcd.sample.yaml`. An example configuration for a virtual manager only cluster's first host would be:

        ---
        pvc:
          node: node1
          functions:
            enable_hypervisor: True
            enable_networking: False
            enable_storage: False
          cluster:
            coordinators:
              - node1
              - node2
              - node3
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
                host: node1-lom # Ensure this is reachable from the nodes
                user: myipmiuser
                pass: myipmiPassw0rd
            migration:
              target_selector: mem
            configuration:
              directories:
                dynamic_directory: "/run/pvc"
                log_directory: "/var/log/pvc"
              logging:
                file_logging: True
                stdout_logging: True

1. Start the PVC daemon (`systemctl start pvcd`) on the first node. On startup, the daemon will connect to the Zookeeper cluster and automatically add itself to the configuration. Verify it is running with `journalctl -u pvcd -o cat` and that it is sending keepalives to the cluster.

1. Use the client CLI on the first node to verify the node is up and running:

        $ pvc node list
        Name  St: Daemon  Coordinator  Domain   Res: VMs  CPUs  Load   Mem (M): Total  Used   Free   VMs
        node1     run     primary      flushed       0    24    0.41            91508  2620   88888  0

    The `Daemon` mode should be `run`, and on initial startup the `Domain` mode will be `flushed` to prevent VMs being immediately provisioned or migrated to the new node.

1. Start the PVC daemon on the other nodes as well, verifying their status in the same way as the first node.

1. Use the client CLI on the first node to set the first node into ready state:

        $ pvc node ready node1
        Restoring hypervisor node1 to active service.

    The `Domain` state for the node will now be `ready`.

1. Repeat the previous step for the other two nodes. The cluster is now ready to handle virtual machines.

1. Provision a KVM virtual machine using whatever tools or methods you choose, and obtain the Libvirt `.xml` domain definition file. Note that virtual network bridges should use the form `vmbrXXX`, where `XXX` is the vLAN ID or another numeric identifier.

1. Define the VM in the cluster using the CLI tool:

        $ pvc vm define --target node1 path/to/test1.xml
        Adding new VM with Name "test1" and UUID "5115d00f-9f11-4899-9edf-5a35bf76d6b4" to database.

1. Verify that the new VM is present:

        $ pvc vm list
        Name     UUID                                  State  Networks  RAM (M)  vCPUs  Node     Migrated
        test1    5115d00f-9f11-4899-9edf-5a35bf76d6b4  stop   101       1024     1      node1    no

1. Start the new VM and verify it is running:

        $ pvc vm start test1
        Starting VM "5115d00f-9f11-4899-9edf-5a35bf76d6b4".
        $ pvc vm info test1
        Virtual machine information:

        UUID:               5115d00f-9f11-4899-9edf-5a35bf76d6b4
        Name:               test1
        Description:        Testing host
        Memory (M):         1024
        vCPUs:              1
        Topology (S/C/T):   1/1/1

        State:              start
        Current Node:       node1
        Previous Node:      N/A

        Networks:           101 [invalid]

Congratulations, you have deployed a simple PVC cluster! Add any further VMs or nodes you require using the same procedure, though additional nodes do not need to be in the `coordinators:` list.

### With virtual networking support

In addition to a virtual manager only setup, PVC v0.4 supports a setup with virtual networking support as well. This configuration enables management of both simple bridged and managed networking within the cluster, and requires additional setup steps.

1. Perform the first 4 steps of the previous section.

1. Deploy a MariaDB Galera cluster among the coordinators. Follow the [PowerDNS guide](https://doc.powerdns.com/md/authoritative/backend-generic-mysql/#default-schema) to create a PowerDNS authoritative database schema on the cluster.

1. Configure the `/etc/pvc/pvcd.yaml` file based on the `/etc/pvc/pvcd.sample.yaml` file, this time not removing any major sections. Fill in the required values for the MySQL DNS database, the various interfaces and networks, and set `enable_networking: True`.

1. Proceed with the remainder of the previous section.

1. Configure networks with the `pvc network` CLI utility:

        $ pvc network add 1001 -p bridged -d test-net-1
        Network "test-net-1" added successfully!
        $ pvc network add 1002 -p managed -d test-net-2 -i 10.200.0.0/24 -g 10.200.0.1
        Network "test-net-2" added successfully!
        $ pvc network list
        VNI   Description  Type     Domain  IPv6   DHCPv6  IPv4   DHCPv4  
        1001  test1        bridged  None    False  False   False  False  
        1002  test2        managed  test2   False  False   True   False  

1. Configure any static ACLs, enable DHCP, or perform other network management functions using the CLI utility. See `pvc network -h` for the high-level commands available.
