#!/usr/bin/env python3

# common.py - PVC client function library, common fuctions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2022 Joshua M. Boniface <joshua@boniface.me>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
###############################################################################

import time
import uuid
import lxml
import subprocess
import signal
from json import loads
from re import match as re_match
from re import split as re_split
from re import sub as re_sub
from distutils.util import strtobool
from threading import Thread
from shlex import split as shlex_split
from functools import wraps


###############################################################################
# Global Variables
###############################################################################


# State lists
fault_state_combinations = [
    "new",
    "ack",
]
node_state_combinations = [
    "run,ready",
    "run,flush",
    "run,flushed",
    "run,unflush",
    "init,ready",
    "init,flush",
    "init,flushed",
    "init,unflush",
    "stop,ready",
    "stop,flush",
    "stop,flushed",
    "stop,unflush",
    "dead,ready",
    "dead,flush",
    "dead,fence-flush",
    "dead,flushed",
    "dead,unflush",
    "fenced,ready",
    "fenced,flush",
    "fenced,flushed",
    "fenced,unflush",
]
vm_state_combinations = [
    "start",
    "restart",
    "shutdown",
    "stop",
    "disable",
    "fail",
    "migrate",
    "unmigrate",
    "provision",
]
ceph_osd_state_combinations = [
    "up,in",
    "up,out",
    "down,in",
    "down,out",
]


###############################################################################
# Performance Profiler decorator
###############################################################################


# Get performance statistics on a function or class
class Profiler(object):
    def __init__(self, config):
        self.is_debug = config["debug"]
        self.pvc_logdir = "/var/log/pvc"

    def __call__(self, function):
        if not callable(function):
            return

        if not self.is_debug:
            return function

        @wraps(function)
        def profiler_wrapper(*args, **kwargs):
            import cProfile
            import pstats
            from os import path, makedirs
            from datetime import datetime

            if not path.exists(self.pvc_logdir):
                print(
                    "Profiler: Requested profiling of {} but no log dir present; printing instead.".format(
                        str(function.__name__)
                    )
                )
                log_result = False
            else:
                log_result = True
                profiler_logdir = "{}/profiler".format(self.pvc_logdir)
                if not path.exists(profiler_logdir):
                    makedirs(profiler_logdir)

            pr = cProfile.Profile()
            pr.enable()

            ret = function(*args, **kwargs)

            pr.disable()
            stats = pstats.Stats(pr)
            stats.sort_stats(pstats.SortKey.TIME)

            if log_result:
                stats.dump_stats(
                    filename="{}/{}_{}.log".format(
                        profiler_logdir,
                        str(function.__name__),
                        str(datetime.now()).replace(" ", "_"),
                    )
                )
            else:
                print(
                    "Profiler stats for function {} at {}:".format(
                        str(function.__name__), str(datetime.now())
                    )
                )
                stats.print_stats()

            return ret

        return profiler_wrapper


###############################################################################
# Supplemental functions
###############################################################################


#
# Run a local OS daemon in the background
#
class OSDaemon(object):
    def __init__(self, command_string, environment, logfile):
        command = shlex_split(command_string)
        # Set stdout to be a logfile if set
        if logfile:
            stdout = open(logfile, "a")
        else:
            stdout = subprocess.PIPE

        # Invoke the process
        self.proc = subprocess.Popen(
            command,
            env=environment,
            stdout=stdout,
            stderr=stdout,
        )

    # Signal the process
    def signal(self, sent_signal):
        signal_map = {
            "hup": signal.SIGHUP,
            "int": signal.SIGINT,
            "term": signal.SIGTERM,
            "kill": signal.SIGKILL,
        }
        self.proc.send_signal(signal_map[sent_signal])


def run_os_daemon(command_string, environment=None, logfile=None):
    daemon = OSDaemon(command_string, environment, logfile)
    return daemon


#
# Run a local OS command via shell
#
def run_os_command(command_string, background=False, environment=None, timeout=None):
    if not isinstance(command_string, list):
        command = shlex_split(command_string)
    else:
        command = command_string

    if background:

        def runcmd():
            try:
                subprocess.run(
                    command,
                    env=environment,
                    timeout=timeout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except subprocess.TimeoutExpired:
                pass

        thread = Thread(target=runcmd, args=())
        thread.start()
        return 0, None, None
    else:
        try:
            command_output = subprocess.run(
                command,
                env=environment,
                timeout=timeout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            retcode = command_output.returncode
        except subprocess.TimeoutExpired:
            retcode = 128
        except Exception:
            retcode = 255

        try:
            stdout = command_output.stdout.decode("ascii")
        except Exception:
            stdout = ""
        try:
            stderr = command_output.stderr.decode("ascii")
        except Exception:
            stderr = ""
        return retcode, stdout, stderr


#
# Validate a UUID
#
def validateUUID(dom_uuid):
    try:
        uuid.UUID(dom_uuid)
        return True
    except Exception:
        return False


#
# Parse a Domain XML object
#
def getDomainXML(zkhandler, dom_uuid):
    try:
        xml = zkhandler.read(("domain.xml", dom_uuid))
    except Exception:
        return None

    # Parse XML using lxml.objectify
    parsed_xml = lxml.objectify.fromstring(xml)
    return parsed_xml


#
# Get the main details for a VM object from XML
#
def getDomainMainDetails(parsed_xml):
    # Get the information we want from it
    duuid = str(parsed_xml.uuid)
    try:
        ddescription = str(parsed_xml.description)
    except AttributeError:
        ddescription = "N/A"
    dname = str(parsed_xml.name)
    dmemory = str(parsed_xml.memory)
    dmemory_unit = str(parsed_xml.memory.attrib.get("unit"))
    if dmemory_unit == "KiB":
        dmemory = int(int(dmemory) / 1024)
    elif dmemory_unit == "GiB":
        dmemory = int(int(dmemory) * 1024)
    dvcpu = str(parsed_xml.vcpu)
    try:
        dvcputopo = "{}/{}/{}".format(
            parsed_xml.cpu.topology.attrib.get("sockets"),
            parsed_xml.cpu.topology.attrib.get("cores"),
            parsed_xml.cpu.topology.attrib.get("threads"),
        )
    except Exception:
        dvcputopo = "N/A"

    return duuid, dname, ddescription, dmemory, dvcpu, dvcputopo


#
# Get long-format details
#
def getDomainExtraDetails(parsed_xml):
    dtype = str(parsed_xml.os.type)
    darch = str(parsed_xml.os.type.attrib["arch"])
    dmachine = str(parsed_xml.os.type.attrib["machine"])
    dconsole = str(parsed_xml.devices.console.attrib["type"])
    demulator = str(parsed_xml.devices.emulator)

    return dtype, darch, dmachine, dconsole, demulator


#
# Get CPU features
#
def getDomainCPUFeatures(parsed_xml):
    dfeatures = []
    try:
        for feature in parsed_xml.features.getchildren():
            dfeatures.append(feature.tag)
    except Exception:
        pass

    return dfeatures


#
# Get disk devices
#
def getDomainDisks(parsed_xml, stats_data):
    ddisks = []
    for device in parsed_xml.devices.getchildren():
        if device.tag == "disk":
            disk_attrib = device.source.attrib
            disk_target = device.target.attrib
            disk_type = device.attrib.get("type")
            disk_stats_list = [
                x
                for x in stats_data.get("disk_stats", [])
                if x.get("name") == disk_attrib.get("name")
            ]
            try:
                disk_stats = disk_stats_list[0]
            except Exception:
                disk_stats = {}

            if disk_type == "network":
                disk_obj = {
                    "type": disk_attrib.get("protocol"),
                    "name": disk_attrib.get("name"),
                    "dev": disk_target.get("dev"),
                    "bus": disk_target.get("bus"),
                    "rd_req": disk_stats.get("rd_req", 0),
                    "rd_bytes": disk_stats.get("rd_bytes", 0),
                    "wr_req": disk_stats.get("wr_req", 0),
                    "wr_bytes": disk_stats.get("wr_bytes", 0),
                }
            elif disk_type == "file":
                disk_obj = {
                    "type": "file",
                    "name": disk_attrib.get("file"),
                    "dev": disk_target.get("dev"),
                    "bus": disk_target.get("bus"),
                    "rd_req": disk_stats.get("rd_req", 0),
                    "rd_bytes": disk_stats.get("rd_bytes", 0),
                    "wr_req": disk_stats.get("wr_req", 0),
                    "wr_bytes": disk_stats.get("wr_bytes", 0),
                }
            else:
                disk_obj = {}
            ddisks.append(disk_obj)

    return ddisks


#
# Get a list of disk devices
#
def getDomainDiskList(zkhandler, dom_uuid):
    domain_information = getInformationFromXML(zkhandler, dom_uuid)
    disk_list = []
    for disk in domain_information["disks"]:
        disk_list.append(disk["name"])

    return disk_list


#
# Get a list of domain tags
#
def getDomainTags(zkhandler, dom_uuid):
    """
    Get a list of tags for domain dom_uuid

    The UUID must be validated before calling this function!
    """
    tags = list()

    for tag in zkhandler.children(("domain.meta.tags", dom_uuid)):
        tag_type = zkhandler.read(("domain.meta.tags", dom_uuid, "tag.type", tag))
        protected = bool(
            strtobool(
                zkhandler.read(("domain.meta.tags", dom_uuid, "tag.protected", tag))
            )
        )
        tags.append({"name": tag, "type": tag_type, "protected": protected})

    return tags


#
# Get a set of domain metadata
#
def getDomainMetadata(zkhandler, dom_uuid):
    """
    Get the domain metadata for domain dom_uuid

    The UUID must be validated before calling this function!
    """
    (
        domain_node_limit,
        domain_node_selector,
        domain_node_autostart,
        domain_migration_method,
    ) = zkhandler.read_many(
        [
            ("domain.meta.node_limit", dom_uuid),
            ("domain.meta.node_selector", dom_uuid),
            ("domain.meta.autostart", dom_uuid),
            ("domain.meta.migrate_method", dom_uuid),
        ]
    )

    if not domain_node_limit:
        domain_node_limit = None
    else:
        domain_node_limit = domain_node_limit.split(",")

    if not domain_node_selector or domain_node_selector == "none":
        domain_node_selector = None

    if not domain_node_autostart:
        domain_node_autostart = None

    if not domain_migration_method or domain_migration_method == "none":
        domain_migration_method = None

    return (
        domain_node_limit,
        domain_node_selector,
        domain_node_autostart,
        domain_migration_method,
    )


#
# Get domain information from XML
#
def getInformationFromXML(zkhandler, uuid):
    """
    Gather information about a VM from the Libvirt XML configuration in the Zookeper database
    and return a dict() containing it.
    """
    domain_state = zkhandler.read(("domain.state", uuid))
    domain_node = zkhandler.read(("domain.node", uuid))
    domain_lastnode = zkhandler.read(("domain.last_node", uuid))
    domain_failedreason = zkhandler.read(("domain.failed_reason", uuid))

    (
        domain_node_limit,
        domain_node_selector,
        domain_node_autostart,
        domain_migration_method,
    ) = getDomainMetadata(zkhandler, uuid)
    domain_tags = getDomainTags(zkhandler, uuid)
    domain_profile = zkhandler.read(("domain.profile", uuid))

    domain_vnc = zkhandler.read(("domain.console.vnc", uuid))
    if domain_vnc:
        domain_vnc_listen, domain_vnc_port = domain_vnc.split(":")
    else:
        domain_vnc_listen = "None"
        domain_vnc_port = "None"

    parsed_xml = getDomainXML(zkhandler, uuid)

    stats_data = zkhandler.read(("domain.stats", uuid))
    if stats_data is not None:
        try:
            stats_data = loads(stats_data)
        except Exception:
            stats_data = {}
    else:
        stats_data = {}

    (
        domain_uuid,
        domain_name,
        domain_description,
        domain_memory,
        domain_vcpu,
        domain_vcputopo,
    ) = getDomainMainDetails(parsed_xml)
    domain_networks = getDomainNetworks(parsed_xml, stats_data)

    (
        domain_type,
        domain_arch,
        domain_machine,
        domain_console,
        domain_emulator,
    ) = getDomainExtraDetails(parsed_xml)

    domain_features = getDomainCPUFeatures(parsed_xml)
    domain_disks = getDomainDisks(parsed_xml, stats_data)
    domain_controllers = getDomainControllers(parsed_xml)

    if domain_lastnode:
        domain_migrated = "from {}".format(domain_lastnode)
    else:
        domain_migrated = "no"

    domain_information = {
        "name": domain_name,
        "uuid": domain_uuid,
        "state": domain_state,
        "node": domain_node,
        "last_node": domain_lastnode,
        "migrated": domain_migrated,
        "failed_reason": domain_failedreason,
        "node_limit": domain_node_limit,
        "node_selector": domain_node_selector,
        "node_autostart": bool(strtobool(domain_node_autostart)),
        "migration_method": domain_migration_method,
        "tags": domain_tags,
        "description": domain_description,
        "profile": domain_profile,
        "memory": int(domain_memory),
        "memory_stats": stats_data.get("mem_stats", {}),
        "vcpu": int(domain_vcpu),
        "vcpu_topology": domain_vcputopo,
        "vcpu_stats": stats_data.get("cpu_stats", {}),
        "networks": domain_networks,
        "type": domain_type,
        "arch": domain_arch,
        "machine": domain_machine,
        "console": domain_console,
        "vnc": {"listen": domain_vnc_listen, "port": domain_vnc_port},
        "emulator": domain_emulator,
        "features": domain_features,
        "disks": domain_disks,
        "controllers": domain_controllers,
        "xml": lxml.etree.tostring(parsed_xml, encoding="ascii", method="xml")
        .decode()
        .replace('"', "'"),
    }

    return domain_information


#
# Get network devices
#
def getDomainNetworks(parsed_xml, stats_data):
    dnets = []
    for device in parsed_xml.devices.getchildren():
        if device.tag == "interface":
            try:
                net_type = device.attrib.get("type")
            except Exception:
                net_type = None

            try:
                net_mac = device.mac.attrib.get("address")
            except Exception:
                net_mac = None

            try:
                net_bridge = device.source.attrib.get(net_type)
            except Exception:
                net_bridge = None

            try:
                net_model = device.model.attrib.get("type")
            except Exception:
                net_model = None

            try:
                net_stats_list = [
                    x
                    for x in stats_data.get("net_stats", [])
                    if x.get("bridge") == net_bridge
                ]
                net_stats = net_stats_list[0]
            except Exception:
                net_stats = {}

            net_rd_bytes = net_stats.get("rd_bytes", 0)
            net_rd_packets = net_stats.get("rd_packets", 0)
            net_rd_errors = net_stats.get("rd_errors", 0)
            net_rd_drops = net_stats.get("rd_drops", 0)
            net_wr_bytes = net_stats.get("wr_bytes", 0)
            net_wr_packets = net_stats.get("wr_packets", 0)
            net_wr_errors = net_stats.get("wr_errors", 0)
            net_wr_drops = net_stats.get("wr_drops", 0)

            if net_type == "direct":
                net_vni = "macvtap:" + device.source.attrib.get("dev")
                net_bridge = device.source.attrib.get("dev")
            elif net_type == "hostdev":
                net_vni = "hostdev:" + str(device.sriov_device)
                net_bridge = str(device.sriov_device)
            else:
                net_vni = re_match(r"[vm]*br([0-9a-z]+)", net_bridge).group(1)

            net_obj = {
                "type": net_type,
                "vni": net_vni,
                "mac": net_mac,
                "source": net_bridge,
                "model": net_model,
                "rd_bytes": net_rd_bytes,
                "rd_packets": net_rd_packets,
                "rd_errors": net_rd_errors,
                "rd_drops": net_rd_drops,
                "wr_bytes": net_wr_bytes,
                "wr_packets": net_wr_packets,
                "wr_errors": net_wr_errors,
                "wr_drops": net_wr_drops,
            }
            dnets.append(net_obj)

    return dnets


#
# Get controller devices
#
def getDomainControllers(parsed_xml):
    dcontrollers = []
    for device in parsed_xml.devices.getchildren():
        if device.tag == "controller":
            controller_type = device.attrib.get("type")
            try:
                controller_model = device.attrib.get("model")
            except KeyError:
                controller_model = "none"
            controller_obj = {"type": controller_type, "model": controller_model}
            dcontrollers.append(controller_obj)

    return dcontrollers


#
# Verify node is valid in cluster
#
def verifyNode(zkhandler, node):
    return zkhandler.exists(("node", node))


#
# Get the primary coordinator node
#
def getPrimaryNode(zkhandler):
    failcount = 0
    while True:
        try:
            primary_node = zkhandler.read("base.config.primary_node")
        except Exception:
            primary_node == "none"

        if primary_node == "none":
            raise
            time.sleep(1)
            failcount += 1
            continue
        else:
            break

        if failcount > 2:
            return None

    return primary_node


#
# Find a migration target
#
def findTargetNode(zkhandler, dom_uuid):
    # Determine VM node limits; set config value if read fails
    try:
        node_limit = zkhandler.read(("domain.meta.node_limit", dom_uuid)).split(",")
        if not any(node_limit):
            node_limit = None
    except Exception:
        node_limit = None

    # Determine VM search field or use default; set config value if read fails
    try:
        search_field = zkhandler.read(("domain.meta.node_selector", dom_uuid))
    except Exception:
        search_field = None

    # If our search field is invalid, use the default
    if search_field is None or search_field in ["None", "none"]:
        search_field = zkhandler.read("base.config.migration_target_selector")

    # Execute the search
    if search_field == "mem":
        return findTargetNodeMemFree(zkhandler, node_limit, dom_uuid)
    if search_field == "memprov":
        return findTargetNodeMemProv(zkhandler, node_limit, dom_uuid)
    if search_field == "load":
        return findTargetNodeLoad(zkhandler, node_limit, dom_uuid)
    if search_field == "vcpus":
        return findTargetNodeVCPUs(zkhandler, node_limit, dom_uuid)
    if search_field == "vms":
        return findTargetNodeVMs(zkhandler, node_limit, dom_uuid)

    # Nothing was found
    return None


#
# Get the list of valid target nodes
#
def getNodes(zkhandler, node_limit, dom_uuid):
    valid_node_list = []
    full_node_list = zkhandler.children("base.node")
    current_node = zkhandler.read(("domain.node", dom_uuid))

    for node in full_node_list:
        if node_limit and node not in node_limit:
            continue

        daemon_state = zkhandler.read(("node.state.daemon", node))
        domain_state = zkhandler.read(("node.state.domain", node))

        if node == current_node:
            continue

        if daemon_state != "run" or domain_state != "ready":
            continue

        valid_node_list.append(node)

    return valid_node_list


#
# via free memory
#
def findTargetNodeMemFree(zkhandler, node_limit, dom_uuid):
    most_memfree = 0
    target_node = None

    node_list = getNodes(zkhandler, node_limit, dom_uuid)
    for node in node_list:
        memfree = int(zkhandler.read(("node.memory.free", node)))

        if memfree > most_memfree:
            most_memfree = memfree
            target_node = node

    return target_node


#
# via provisioned memory
#
def findTargetNodeMemProv(zkhandler, node_limit, dom_uuid):
    most_provfree = 0
    target_node = None

    node_list = getNodes(zkhandler, node_limit, dom_uuid)
    for node in node_list:
        memprov = int(zkhandler.read(("node.memory.provisioned", node)))
        memused = int(zkhandler.read(("node.memory.used", node)))
        memfree = int(zkhandler.read(("node.memory.free", node)))
        memtotal = memused + memfree
        provfree = memtotal - memprov

        if provfree > most_provfree:
            most_provfree = provfree
            target_node = node

    return target_node


#
# via load average
#
def findTargetNodeLoad(zkhandler, node_limit, dom_uuid):
    least_load = 9999.0
    target_node = None

    node_list = getNodes(zkhandler, node_limit, dom_uuid)
    for node in node_list:
        load = float(zkhandler.read(("node.cpu.load", node)))

        if load < least_load:
            least_load = load
            target_node = node

    return target_node


#
# via total vCPUs
#
def findTargetNodeVCPUs(zkhandler, node_limit, dom_uuid):
    least_vcpus = 9999
    target_node = None

    node_list = getNodes(zkhandler, node_limit, dom_uuid)
    for node in node_list:
        vcpus = int(zkhandler.read(("node.vcpu.allocated", node)))

        if vcpus < least_vcpus:
            least_vcpus = vcpus
            target_node = node

    return target_node


#
# via total VMs
#
def findTargetNodeVMs(zkhandler, node_limit, dom_uuid):
    least_vms = 9999
    target_node = None

    node_list = getNodes(zkhandler, node_limit, dom_uuid)
    for node in node_list:
        vms = int(zkhandler.read(("node.count.provisioned_domains", node)))

        if vms < least_vms:
            least_vms = vms
            target_node = node

    return target_node


#
# Connect to the primary node and run a command
#
def runRemoteCommand(node, command, become=False):
    import paramiko
    import hashlib
    import dns.resolver
    import dns.flags

    # Support doing SSHFP checks
    class DnssecPolicy(paramiko.client.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            sshfp_expect = hashlib.sha1(key.asbytes()).hexdigest()
            ans = dns.resolver.query(hostname, "SSHFP")
            if not ans.response.flags & dns.flags.DO:
                raise AssertionError("Answer is not DNSSEC signed")
            for answer in ans.response.answer:
                for item in answer.items:
                    if sshfp_expect in item.to_text():
                        client._log(
                            paramiko.common.DEBUG,
                            "Found {} in SSHFP for host {}".format(
                                key.get_name(), hostname
                            ),
                        )
                        return
            raise AssertionError("SSHFP not published in DNS")

    if become:
        command = "sudo " + command

    ssh_client = paramiko.client.SSHClient()
    ssh_client.load_system_host_keys()
    ssh_client.set_missing_host_key_policy(DnssecPolicy())
    ssh_client.connect(node)
    stdin, stdout, stderr = ssh_client.exec_command(command)
    return (
        stdout.read().decode("ascii").rstrip(),
        stderr.read().decode("ascii").rstrip(),
    )


#
# Reload the firewall rules of the system
#
def reload_firewall_rules(rules_file, logger=None):
    if logger is not None:
        logger.out("Reloading firewall configuration", state="o")

    retcode, stdout, stderr = run_os_command("/usr/sbin/nft -f {}".format(rules_file))
    if retcode != 0 and logger is not None:
        logger.out("Failed to reload configuration: {}".format(stderr), state="e")


#
# Create an IP address
#
def createIPAddress(ipaddr, cidrnetmask, dev):
    run_os_command("ip address add {}/{} dev {}".format(ipaddr, cidrnetmask, dev))
    run_os_command(
        "arping -P -U -W 0.02 -c 2 -i {dev} -S {ip} {ip}".format(dev=dev, ip=ipaddr)
    )


#
# Remove an IP address
#
def removeIPAddress(ipaddr, cidrnetmask, dev):
    run_os_command("ip address delete {}/{} dev {}".format(ipaddr, cidrnetmask, dev))


#
# Sort a set of interface names (e.g. ens1f1v10)
#
def sortInterfaceNames(interface_names):
    # We can't handle non-list inputs
    if not isinstance(interface_names, list):
        return interface_names

    def atoi(text):
        return int(text) if text.isdigit() else text

    def natural_keys(text):
        """
        alist.sort(key=natural_keys) sorts in human order
        http://nedbatchelder.com/blog/200712/human_sorting.html
        (See Toothy's implementation in the comments)
        """
        return [atoi(c) for c in re_split(r"(\d+)", text)]

    return sorted(interface_names, key=natural_keys)


#
# Parse a "detect" device into a real block device name
#
def get_detect_device(detect_string):
    """
    Parses a "detect:" string into a normalized block device path using lsscsi.

    A detect string is formatted "detect:<NAME>:<SIZE>:<ID>", where
    NAME is some unique identifier in lsscsi, SIZE is a human-readable
    size value to within +/- 3% of the real size of the device, and
    ID is the Nth (0-indexed) matching entry of that NAME and SIZE.
    """
    _, name, size, idd = detect_string.split(":")
    if _ != "detect":
        return None

    retcode, stdout, stderr = run_os_command("lsscsi -s")
    if retcode:
        print(f"Failed to run lsscsi: {stderr}")
        return None

    # Get valid lines
    lsscsi_lines_raw = stdout.split("\n")
    lsscsi_lines = list()
    for line in lsscsi_lines_raw:
        if not line:
            continue
        split_line = line.split()
        if split_line[1] != "disk":
            continue
        lsscsi_lines.append(line)

    # Handle size determination (+/- 3%)
    lsscsi_sizes = set()
    for line in lsscsi_lines:
        lsscsi_sizes.add(split_line[-1])
    for l_size in lsscsi_sizes:
        b_size = float(re_sub(r"\D.", "", size))
        t_size = float(re_sub(r"\D.", "", l_size))

        plusthreepct = t_size * 1.03
        minusthreepct = t_size * 0.97

        if b_size > minusthreepct and b_size < plusthreepct:
            size = l_size
            break

    blockdev = None
    matches = list()
    for idx, line in enumerate(lsscsi_lines):
        # Skip non-disk entries
        if line.split()[1] != "disk":
            continue
        # Skip if name is not contained in the line (case-insensitive)
        if name.lower() not in line.lower():
            continue
        # Skip if the size does not match
        if size != line.split()[-1]:
            continue
        # Get our blockdev and append to the list
        matches.append(line.split()[-2])

    blockdev = None
    # Find the blockdev at index {idd}
    for idx, _blockdev in enumerate(matches):
        if int(idx) == int(idd):
            blockdev = _blockdev
            break

    return blockdev
