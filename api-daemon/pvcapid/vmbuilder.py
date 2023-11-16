#!/usr/bin/env python3

# vmbuilder.py - pvc api vm builder (provisioner) functions
# part of the parallel virtual cluster (pvc) system
#
#    copyright (c) 2018-2022 joshua m. boniface <joshua@boniface.me>
#
#    this program is free software: you can redistribute it and/or modify
#    it under the terms of the gnu general public license as published by
#    the free software foundation, version 3.
#
#    this program is distributed in the hope that it will be useful,
#    but without any warranty; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
###############################################################################

import json
import psycopg2
import psycopg2.extras
import re
import os

# import sys
import importlib.util
import uuid

from contextlib import contextmanager

from pvcapid.Daemon import config

from daemon_lib.zkhandler import ZKHandler
from daemon_lib.celery import start, fail, log_info, log_warn, log_err, update, finish

import daemon_lib.common as pvc_common
import daemon_lib.node as pvc_node
import daemon_lib.vm as pvc_vm
import daemon_lib.network as pvc_network
import daemon_lib.ceph as pvc_ceph


#
# Exceptions (used by Celery tasks)
#
class ValidationError(Exception):
    """
    An exception that results from some value being un- or mis-defined.
    """

    pass


class ClusterError(Exception):
    """
    An exception that results from the PVC cluster being out of alignment with the action.
    """

    pass


class ProvisioningError(Exception):
    """
    An exception that results from a failure of a provisioning command.
    """

    pass


#
# VMBuilder class - subclassed by install scripts
#
class VMBuilder(object):
    def __init__(
        self,
        vm_name,
        vm_id,
        vm_profile,
        vm_data,
    ):
        self.vm_name = vm_name
        self.vm_id = vm_id
        self.vm_uuid = uuid.uuid4()
        self.vm_profile = vm_profile
        self.vm_data = vm_data

    #
    # Helper class functions; used by the individual scripts
    #
    def log_info(self, msg):
        log_info(None, msg)

    def log_warn(self, msg):
        log_warn(None, msg)

    def log_err(self, msg):
        log_err(None, msg)

    def fail(self, msg, exception=ProvisioningError):
        fail(None, msg, exception=exception)

    #
    # Primary class functions; implemented by the individual scripts
    #
    def setup(self):
        """
        setup(): Perform special setup steps before proceeding
        OPTIONAL
        """
        pass

    def create(self):
        """
        create(): Create the VM libvirt schema definition which is defined afterwards
        """
        pass

    def prepare(self):
        """
        prepare(): Prepare any disks/volumes for the install step
        """
        pass

    def install(self):
        """
        install(): Perform the installation
        """
        pass

    def cleanup(self):
        """
        cleanup(): Perform any cleanup required after the prepare() step or on failure of the install() step
        """
        pass


#
# Helper functions (as context managers)
#
@contextmanager
def chroot(destination):
    """
    Change root directory to a given destination
    """
    try:
        real_root = os.open("/", os.O_RDONLY)
        os.chroot(destination)
        fake_root = os.open("/", os.O_RDONLY)
        os.fchdir(fake_root)
        yield
    except Exception:
        raise
    finally:
        os.fchdir(real_root)
        os.chroot(".")
        os.fchdir(real_root)
        os.close(fake_root)
        os.close(real_root)
        del fake_root
        del real_root


@contextmanager
def open_db(config):
    try:
        conn = psycopg2.connect(
            host=config["database_host"],
            port=config["database_port"],
            dbname=config["database_name"],
            user=config["database_user"],
            password=config["database_password"],
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    except Exception:
        fail(
            None,
            "Failed to connect to Postgres",
            exception=ClusterError,
        )

    try:
        yield cur
    except Exception:
        raise
    finally:
        conn.commit()
        cur.close()
        conn.close()
        del conn


@contextmanager
def open_zk(config):
    try:
        zkhandler = ZKHandler(config)
        zkhandler.connect()
    except Exception:
        fail(
            None,
            "Failed to connect to Zookeeper",
            exception=ClusterError,
        )

    try:
        yield zkhandler
    except Exception:
        raise
    finally:
        zkhandler.disconnect()
        del zkhandler


#
# Main VM provisioning function - executed by the Celery worker
#
def create_vm(
    celery, vm_name, vm_profile, define_vm=True, start_vm=True, script_run_args=[]
):
    current_stage = 0
    total_stages = 10
    start(
        celery,
        f"Provisioning new VM '{vm_name}' with profile '{vm_profile}'",
        current=current_stage,
        total=total_stages,
    )

    # Phase 1 - setup
    #  * Get the profile elements
    #  * Get the details from these elements
    #  * Assemble a VM configuration dictionary
    current_stage += 1
    update(
        celery,
        "Collecting configuration details",
        current=current_stage,
        total=total_stages,
    )

    vm_id = re.findall(r"/(\d+)$/", vm_name)
    if not vm_id:
        vm_id = 0
    else:
        vm_id = vm_id[0]

    vm_data = dict()

    with open_db(config) as db_cur:
        # Get the profile information
        query = "SELECT * FROM profile WHERE name = %s"
        args = (vm_profile,)
        db_cur.execute(query, args)
        profile_data = db_cur.fetchone()
        if profile_data.get("arguments"):
            vm_data["script_arguments"] = profile_data.get("arguments").split("|")
        else:
            vm_data["script_arguments"] = []

        # Get the system details
        query = "SELECT * FROM system_template WHERE id = %s"
        args = (profile_data["system_template"],)
        db_cur.execute(query, args)
        vm_data["system_details"] = db_cur.fetchone()

        # Get the MAC template
        query = "SELECT mac_template FROM network_template WHERE id = %s"
        args = (profile_data["network_template"],)
        db_cur.execute(query, args)
        db_row = db_cur.fetchone()
        if db_row:
            vm_data["mac_template"] = db_row.get("mac_template")
        else:
            vm_data["mac_template"] = None

        # Get the networks
        query = "SELECT * FROM network WHERE network_template = %s"
        args = (profile_data["network_template"],)
        db_cur.execute(query, args)
        _vm_networks = db_cur.fetchall()
        vm_networks = list()

        # Set the eth_bridge for each network
        for network in _vm_networks:
            vni = network["vni"]
            if vni in ["upstream", "cluster", "storage"]:
                eth_bridge = "br{}".format(vni)
            else:
                eth_bridge = "vmbr{}".format(vni)
            network["eth_bridge"] = eth_bridge
            vm_networks.append(network)
        vm_data["networks"] = vm_networks

        # Get the storage volumes
        # ORDER BY ensures disks are always in the sdX/vdX order, regardless of add order
        query = "SELECT * FROM storage WHERE storage_template = %s ORDER BY disk_id"
        args = (profile_data["storage_template"],)
        db_cur.execute(query, args)
        vm_data["volumes"] = db_cur.fetchall()

        # Get the script
        query = "SELECT script FROM script WHERE id = %s"
        args = (profile_data["script"],)
        db_cur.execute(query, args)
        db_row = db_cur.fetchone()
        if db_row:
            vm_data["script"] = db_row.get("script")
        else:
            vm_data["script"] = None

        if profile_data.get("profile_type") == "ova":
            query = "SELECT * FROM ova WHERE id = %s"
            args = (profile_data["ova"],)
            db_cur.execute(query, args)
            vm_data["ova_details"] = db_cur.fetchone()

            query = "SELECT * FROM ova_volume WHERE ova = %s"
            args = (profile_data["ova"],)
            db_cur.execute(query, args)
            # Replace the existing volumes list with our OVA volume list
            vm_data["volumes"] = db_cur.fetchall()

    retcode, stdout, stderr = pvc_common.run_os_command("uname -m")
    vm_data["system_architecture"] = stdout.strip()

    monitor_list = list()
    coordinator_names = config["storage_hosts"]
    for coordinator in coordinator_names:
        monitor_list.append("{}.{}".format(coordinator, config["storage_domain"]))
    vm_data["ceph_monitor_list"] = monitor_list
    vm_data["ceph_monitor_port"] = config["ceph_monitor_port"]
    vm_data["ceph_monitor_secret"] = config["ceph_storage_secret_uuid"]

    # Parse the script arguments
    script_arguments = dict()
    for argument in vm_data["script_arguments"]:
        argument_name, argument_data = argument.split("=")
        script_arguments[argument_name] = argument_data

    # Parse the runtime arguments
    if script_run_args is not None:
        for argument in script_run_args:
            argument_name, argument_data = argument.split("=")
            script_arguments[argument_name] = argument_data

    log_info(celery, f"Script arguments: {script_arguments}")
    vm_data["script_arguments"] = script_arguments

    log_info(
        celery,
        "VM configuration data:\n{}".format(
            json.dumps(vm_data, sort_keys=True, indent=2)
        ),
    )

    # Phase 2 - verification
    #  * Ensure that at least one node has enough free RAM to hold the VM (becomes main host)
    #  * Ensure that all networks are valid
    #  * Ensure that there is enough disk space in the Ceph cluster for the disks
    # This is the "safe fail" step when an invalid configuration will be caught
    current_stage += 1
    update(
        celery,
        "Verifying configuration against cluster",
        current=current_stage,
        total=total_stages,
    )

    with open_zk(config) as zkhandler:
        # Verify that a VM with this name does not already exist
        if pvc_vm.searchClusterByName(zkhandler, vm_name):
            fail(
                celery,
                f"A VM with the name '{vm_name}' already exists in the cluster.",
                exception=ClusterError,
            )

        # Verify that at least one host has enough free RAM to run the VM
        _discard, nodes = pvc_node.get_list(zkhandler, None)
        target_node = None
        last_free = 0
        for node in nodes:
            # Skip the node if it is not ready to run VMs
            if node["daemon_state"] != "run" or node["domain_state"] != "ready":
                continue
            # Skip the node if its free memory is less than the new VM's size, plus a 512MB buffer
            if node["memory"]["free"] < (vm_data["system_details"]["vram_mb"] + 512):
                continue
            # If this node has the most free, use it
            if node["memory"]["free"] > last_free:
                last_free = node["memory"]["free"]
                target_node = node["name"]
        # Raise if no node was found
        if not target_node:
            fail(
                celery,
                f"No ready cluster node contains at least {vm_data['system_details']['vram_mb']}+512 MB of free RAM",
                exception=ClusterError,
            )

        log_info(
            celery,
            f'Selecting target node "{target_node}" with "{last_free}" MB free RAM',
        )

        # Verify that all configured networks are present on the cluster
        cluster_networks, _discard = pvc_network.getClusterNetworkList(zkhandler)
        for network in vm_data["networks"]:
            vni = str(network["vni"])
            if vni not in cluster_networks and vni not in [
                "upstream",
                "cluster",
                "storage",
            ]:
                fail(
                    celery,
                    f'The network VNI "{vni}" is not present on the cluster.',
                    exception=ClusterError,
                )

        log_info(celery, "All configured networks for VM are valid")

        # Verify that there is enough disk space free to provision all VM disks
        pools = dict()
        for volume in vm_data["volumes"]:
            if volume.get("source_volume") is not None:
                volume_data = pvc_ceph.getVolumeInformation(
                    zkhandler, volume["pool"], volume["source_volume"]
                )
                if not volume_data:
                    fail(
                        celery,
                        f"The source volume {volume['pool']}/{volume['source_volume']} could not be found.",
                        exception=ClusterError,
                    )
                if not volume["pool"] in pools:
                    pools[volume["pool"]] = int(
                        pvc_ceph.format_bytes_fromhuman(volume_data["stats"]["size"])
                        / 1024
                        / 1024
                        / 1024
                    )
                else:
                    pools[volume["pool"]] += int(
                        pvc_ceph.format_bytes_fromhuman(volume_data["stats"]["size"])
                        / 1024
                        / 1024
                        / 1024
                    )
            else:
                if not volume["pool"] in pools:
                    pools[volume["pool"]] = volume["disk_size_gb"]
                else:
                    pools[volume["pool"]] += volume["disk_size_gb"]

        for pool in pools:
            try:
                pool_information = pvc_ceph.getPoolInformation(zkhandler, pool)
                if not pool_information:
                    raise
            except Exception:
                fail(
                    celery,
                    f'Pool "{pool}" is not present on the cluster.',
                    exception=ClusterError,
                )
            pool_free_space_gb = int(
                pool_information["stats"]["free_bytes"] / 1024 / 1024 / 1024
            )
            pool_vm_usage_gb = int(pools[pool])

            if pool_vm_usage_gb >= pool_free_space_gb:
                fail(
                    celery,
                    f'Pool "{pool}" has only {pool_free_space_gb} GB free but VM requires {pool_vm_usage_gb} GB.',
                    exception=ClusterError,
                )

        log_info(celery, "There is enough space on cluster to store VM volumes")

    # Verify that every specified filesystem is valid
    used_filesystems = list()
    for volume in vm_data["volumes"]:
        if volume.get("source_volume") is not None:
            continue
        if (
            volume.get("filesystem") is not None
            and volume["filesystem"] not in used_filesystems
        ):
            used_filesystems.append(volume["filesystem"])

    for filesystem in used_filesystems:
        if filesystem is None or filesystem == "None":
            continue
        elif filesystem == "swap":
            retcode, stdout, stderr = pvc_common.run_os_command("which mkswap")
            if retcode:
                fail(
                    celery,
                    f"Failed to find binary for mkswap: {stderr}",
                    exception=ProvisioningError,
                )
        else:
            retcode, stdout, stderr = pvc_common.run_os_command(
                "which mkfs.{}".format(filesystem)
            )
            if retcode:
                fail(
                    celery,
                    f"Failed to find binary for mkfs.{filesystem}: {stderr}",
                    exception=ProvisioningError,
                )

        log_info(celery, "All selected filesystems are valid")

    # Phase 3 - provisioning script preparation
    #  * Import the provisioning script as a library with importlib
    #  * Ensure the required function(s) are present
    current_stage += 1
    update(
        celery,
        "Preparing provisioning script",
        current=current_stage,
        total=total_stages,
    )

    # Write the script out to a temporary file
    retcode, stdout, stderr = pvc_common.run_os_command("mktemp")
    if retcode:
        fail(
            celery,
            f"Failed to create a temporary file: {stderr}",
            exception=ProvisioningError,
        )

    script_file = stdout.strip()
    with open(script_file, "w") as fh:
        fh.write(vm_data["script"])
        fh.write("\n")

    # Import the script file
    loader = importlib.machinery.SourceFileLoader("installer_script", script_file)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    installer_script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer_script)

    # Set up the VMBuilderScript object
    vm_builder = installer_script.VMBuilderScript(
        vm_name=vm_name,
        vm_id=vm_id,
        vm_profile=vm_profile,
        vm_data=vm_data,
    )

    log_info(celery, "Provisioning script imported successfully")

    # Create temporary directory for external chroot
    retcode, stdout, stderr = pvc_common.run_os_command("mktemp -d")
    if retcode:
        fail(
            celery,
            f"Failed to create a temporary directory: {stderr}",
            exception=ProvisioningError,
        )

    temp_dir = stdout.strip()

    # Bind mount / to the chroot location /
    retcode, stdout, stderr = pvc_common.run_os_command(
        f"mount --bind --options ro / {temp_dir}"
    )
    if retcode:
        fail(
            celery,
            f"Failed to mount rootfs into {temp_dir} for chroot: {stderr}",
            exception=ProvisioningError,
        )

    # Mount tmpfs to the chroot location /tmp
    retcode, stdout, stderr = pvc_common.run_os_command(
        f"mount --type tmpfs tmpfs {temp_dir}/tmp"
    )
    if retcode:
        fail(
            celery,
            f"Failed to mount tmpfs onto {temp_dir}/tmp for chroot: {stderr}",
            exception=ProvisioningError,
        )

    # Bind mount /dev to the chroot location /dev
    retcode, stdout, stderr = pvc_common.run_os_command(
        f"mount --bind --options ro /dev {temp_dir}/dev"
    )
    if retcode:
        fail(
            celery,
            f"Failed to mount devfs onto {temp_dir}/dev for chroot: {stderr}",
            exception=ProvisioningError,
        )

    # Bind mount /run to the chroot location /run
    retcode, stdout, stderr = pvc_common.run_os_command(
        f"mount --bind --options rw /run {temp_dir}/run"
    )
    if retcode:
        fail(
            celery,
            f"Failed to mount runfs onto {temp_dir}/run for chroot: {stderr}",
            exception=ProvisioningError,
        )

    # Bind mount /sys to the chroot location /sys
    retcode, stdout, stderr = pvc_common.run_os_command(
        f"mount --bind --options rw /sys {temp_dir}/sys"
    )
    if retcode:
        fail(
            celery,
            f"Failed to mount sysfs onto {temp_dir}/sys for chroot: {stderr}",
            exception=ProvisioningError,
        )

    # Bind mount /proc to the chroot location /proc
    retcode, stdout, stderr = pvc_common.run_os_command(
        f"mount --bind --options rw /proc {temp_dir}/proc"
    )
    if retcode:
        fail(
            celery,
            f"Failed to mount procfs onto {temp_dir}/proc for chroot: {stderr}",
            exception=ProvisioningError,
        )

    log_info(celery, "Chroot environment prepared successfully")

    def general_cleanup():
        log_info(celery, "Running upper cleanup steps")

        try:
            # Unmount bind-mounted devfs on the chroot
            retcode, stdout, stderr = pvc_common.run_os_command(
                f"umount {temp_dir}/dev"
            )
            # Unmount bind-mounted runfs on the chroot
            retcode, stdout, stderr = pvc_common.run_os_command(
                f"umount {temp_dir}/run"
            )
            # Unmount bind-mounted sysfs on the chroot
            retcode, stdout, stderr = pvc_common.run_os_command(
                f"umount {temp_dir}/sys"
            )
            # Unmount bind-mounted procfs on the chroot
            retcode, stdout, stderr = pvc_common.run_os_command(
                f"umount {temp_dir}/proc"
            )
            # Unmount bind-mounted tmpfs on the chroot
            retcode, stdout, stderr = pvc_common.run_os_command(
                f"umount {temp_dir}/tmp"
            )
            # Unmount bind-mounted rootfs on the chroot
            retcode, stdout, stderr = pvc_common.run_os_command(f"umount {temp_dir}")
        except Exception as e:
            # We don't care about fails during cleanup, log and continue
            log_warn(celery, f"Suberror during general cleanup unmounts: {e}")

        try:
            # Remove the temp_dir
            os.rmdir(temp_dir)
        except Exception as e:
            # We don't care about fails during cleanup, log and continue
            log_warn(celery, f"Suberror during general cleanup directory removal: {e}")

        try:
            # Remote temporary script (don't fail if not removed)
            os.remove(script_file)
        except Exception as e:
            # We don't care about fails during cleanup, log and continue
            log_warn(celery, f"Suberror during general cleanup script removal: {e}")

    def fail_clean(celery, msg, exception=ProvisioningError):
        try:
            vm_builder.cleanup()
            general_cleanup()
        except Exception:
            pass
        fail(celery, msg, exception=exception)

    # Phase 4 - script: setup()
    #  * Run pre-setup steps
    current_stage += 1
    update(
        celery, "Running script setup() step", current=current_stage, total=total_stages
    )

    try:
        with chroot(temp_dir):
            vm_builder.setup()
    except Exception as e:
        fail_clean(
            celery,
            f"Error in script setup() step: {e}",
            exception=ProvisioningError,
        )

    # Phase 5 - script: create()
    #  * Prepare the libvirt XML defintion for the VM
    current_stage += 1
    update(
        celery,
        "Running script create() step",
        current=current_stage,
        total=total_stages,
    )

    if define_vm:
        try:
            with chroot(temp_dir):
                vm_schema = vm_builder.create()
        except Exception as e:
            fail_clean(
                celery,
                f"Error in script create() step: {e}",
                exception=ProvisioningError,
            )

        log_info(celery, "Generated VM schema:\n{}\n".format(vm_schema))

        log_info(celery, "Defining VM on cluster")
        node_limit = vm_data["system_details"]["node_limit"]
        if node_limit:
            node_limit = node_limit.split(",")
        node_selector = vm_data["system_details"]["node_selector"]
        node_autostart = vm_data["system_details"]["node_autostart"]
        migration_method = vm_data["system_details"]["migration_method"]
        with open_zk(config) as zkhandler:
            retcode, retmsg = pvc_vm.define_vm(
                zkhandler,
                vm_schema.strip(),
                target_node,
                node_limit,
                node_selector,
                node_autostart,
                migration_method,
                vm_profile,
                initial_state="provision",
            )
        log_info(celery, retmsg)
    else:
        log_info("Skipping VM definition due to define_vm=False")

    # Phase 6 - script: prepare()
    #  * Run preparation steps (e.g. disk creation and mapping, filesystem creation, etc.)
    current_stage += 1
    update(
        celery,
        "Running script prepare() step",
        current=current_stage,
        total=total_stages,
    )

    try:
        with chroot(temp_dir):
            vm_builder.prepare()
    except Exception as e:
        fail_clean(
            celery,
            f"Error in script prepare() step: {e}",
            exception=ProvisioningError,
        )

    # Phase 7 - script: install()
    #  * Run installation with arguments
    current_stage += 1
    update(
        celery,
        "Running script install() step",
        current=current_stage,
        total=total_stages,
    )

    try:
        with chroot(temp_dir):
            vm_builder.install()
    except Exception as e:
        fail_clean(
            celery,
            f"Error in script install() step: {e}",
            exception=ProvisioningError,
        )

    # Phase 8 - script: cleanup()
    #  * Run cleanup steps
    current_stage += 1
    update(
        celery,
        "Running script cleanup() step",
        current=current_stage,
        total=total_stages,
    )

    try:
        with chroot(temp_dir):
            vm_builder.cleanup()
    except Exception as e:
        fail(
            celery,
            f"Error in script cleanup() step: {e}",
            exception=ProvisioningError,
        )

    # Phase 9 - general cleanup
    #  * Clean up the chroot from earlier
    current_stage += 1
    update(
        celery,
        "Running general cleanup steps",
        current=current_stage,
        total=total_stages,
    )

    general_cleanup()

    # Phase 10 - startup
    #  * Start the VM in the PVC cluster
    current_stage += 1
    update(celery, "Starting VM", current=current_stage, total=total_stages)

    if start_vm:
        with open_zk(config) as zkhandler:
            success, message = pvc_vm.start_vm(zkhandler, vm_name)
        log_info(celery, message)

        end_message = f'VM "{vm_name}" with profile "{vm_profile}" has been provisioned and started successfully'
    else:
        end_message = f'VM "{vm_name}" with profile "{vm_profile}" has been provisioned successfully'

    current_stage += 1
    return finish(
        celery,
        end_message,
        current=current_stage,
        total=total_stages,
    )
