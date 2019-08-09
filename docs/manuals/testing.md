# Testing procedures

This manual documents the standard procedures used to test PVC before release. This is a living document and will change frequently as new features are added and new corner cases are found.

As PVC does not currently feature any sort of automated tests, this is the primary way of ensuring functionality is as expected and the various components are operating correctly.

## Basic Tests

### Hypervisors

0. Stop then start all PVC node daemons sequentially, ensure they start up successfully.

0. Observe primary coordinator migration between nodes during startup sequence.

0. Verify reachability of floating IPs on each node across primary coordinator migrations.

0. Manually shuffle primary coordinator between nodes and verify as above (`pvc node primary`).

0. Automatically shuffle primary coordinator between nodes and verify as above (`pvc node secondary`).

### Virtual Machines

0. Deploy a new virtual machine using `vminstall` using managed networking and storage.

0. Start the VM on the first node, verify reachability over managed network (`pvc vm start`).

0. Verify console logs are operating (`pvc vm log -f`).

0. Migrate VM to another node via auto-selection and back again (`pvc vm migrate` and `pvc vm unmigrate`).

0. Manually shuffle VM between nodes and verify reachability on each node (`pvc vm move`).

0. Kill the VM and ensure restart occurs (`virsh destroy`).

0. Restart the VM (`pvc vm restart`).

0. Shutdown the VM (`pvc vm shutdown`).

0. Forcibly stop the VM (`pvc vm stop`).

### Virtual Networking

0. Create a new managed virtual network (`pvc network add`).

0. Verify network is present on all nodes.

0. Verify network gateway is reachable across all nodes (`pvc node primary`).

## Advanced Tests

### Fencing

0. Trigger node kernel panic and observe fencing behaviour (`echo c | sudo tee /proc/sysrq-trigger`).

0. Verify node is fenced successfully.

0. Verify primary coordinator status transfers successfully.

0. Verify VMs are migrated away from node successfully.

### Ceph Storage

0. Create an RBD volume.

0. Create an RBD snapshot.

0. Remove an RBD snapshot.

0. Remove an RBD volume.
