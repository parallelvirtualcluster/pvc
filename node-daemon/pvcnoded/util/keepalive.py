#!/usr/bin/env python3

# keepalive.py - Utility functions for pvcnoded Keepalives
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2021 Joshua M. Boniface <joshua@boniface.me>
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

import pvcnoded.util.fencing

import daemon_lib.common as common

from apscheduler.schedulers.background import BackgroundScheduler
from rados import Rados
from xml.etree import ElementTree
from queue import Queue
from threading import Thread
from datetime import datetime

import json
import re
import libvirt
import psutil
import os
import time


# State table for pretty stats
libvirt_vm_states = {
    0: "NOSTATE",
    1: "RUNNING",
    2: "BLOCKED",
    3: "PAUSED",
    4: "SHUTDOWN",
    5: "SHUTOFF",
    6: "CRASHED",
    7: "PMSUSPENDED"
}


def start_keepalive_timer(logger, config, zkhandler, this_node):
    keepalive_interval = config['keepalive_interval']
    logger.out(f'Starting keepalive timer ({keepalive_interval} second interval)', state='s')
    keepalive_timer = BackgroundScheduler()
    keepalive_timer.add_job(
        node_keepalive,
        args=(logger, config, zkhandler, this_node),
        trigger='interval',
        seconds=keepalive_interval)
    keepalive_timer.start()
    return keepalive_timer


def stop_keepalive_timer(logger, keepalive_timer):
    try:
        keepalive_timer.shutdown()
        logger.out('Stopping keepalive timer', state='s')
    except Exception:
        logger.out('Failed to stop keepalive timer', state='w')


# Ceph stats update function
def collect_ceph_stats(logger, config, zkhandler, this_node, queue):
    pool_list = zkhandler.children('base.pool')
    osd_list = zkhandler.children('base.osd')

    debug = config['debug']
    if debug:
        logger.out("Thread starting", state='d', prefix='ceph-thread')

    # Connect to the Ceph cluster
    try:
        ceph_conn = Rados(conffile=config['ceph_config_file'], conf=dict(keyring=config['ceph_admin_keyring']))
        if debug:
            logger.out("Connecting to cluster", state='d', prefix='ceph-thread')
        ceph_conn.connect(timeout=1)
    except Exception as e:
        logger.out('Failed to open connection to Ceph cluster: {}'.format(e), state='e')
        return

    if debug:
        logger.out("Getting health stats from monitor", state='d', prefix='ceph-thread')

    # Get Ceph cluster health for local status output
    command = {"prefix": "health", "format": "json"}
    try:
        health_status = json.loads(ceph_conn.mon_command(json.dumps(command), b'', timeout=1)[1])
        ceph_health = health_status['status']
    except Exception as e:
        logger.out('Failed to obtain Ceph health data: {}'.format(e), state='e')
        ceph_health = 'HEALTH_UNKN'

    if ceph_health in ['HEALTH_OK']:
        ceph_health_colour = logger.fmt_green
    elif ceph_health in ['HEALTH_UNKN']:
        ceph_health_colour = logger.fmt_cyan
    elif ceph_health in ['HEALTH_WARN']:
        ceph_health_colour = logger.fmt_yellow
    else:
        ceph_health_colour = logger.fmt_red

    # Primary-only functions
    if this_node.router_state == 'primary':
        if debug:
            logger.out("Set ceph health information in zookeeper (primary only)", state='d', prefix='ceph-thread')

        command = {"prefix": "status", "format": "pretty"}
        ceph_status = ceph_conn.mon_command(json.dumps(command), b'', timeout=1)[1].decode('ascii')
        try:
            zkhandler.write([
                ('base.storage', str(ceph_status))
            ])
        except Exception as e:
            logger.out('Failed to set Ceph status data: {}'.format(e), state='e')

        if debug:
            logger.out("Set ceph rados df information in zookeeper (primary only)", state='d', prefix='ceph-thread')

        # Get rados df info
        command = {"prefix": "df", "format": "pretty"}
        ceph_df = ceph_conn.mon_command(json.dumps(command), b'', timeout=1)[1].decode('ascii')
        try:
            zkhandler.write([
                ('base.storage.util', str(ceph_df))
            ])
        except Exception as e:
            logger.out('Failed to set Ceph utilization data: {}'.format(e), state='e')

        if debug:
            logger.out("Set pool information in zookeeper (primary only)", state='d', prefix='ceph-thread')

        # Get pool info
        command = {"prefix": "df", "format": "json"}
        ceph_df_output = ceph_conn.mon_command(json.dumps(command), b'', timeout=1)[1].decode('ascii')
        try:
            ceph_pool_df_raw = json.loads(ceph_df_output)['pools']
        except Exception as e:
            logger.out('Failed to obtain Pool data (ceph df): {}'.format(e), state='w')
            ceph_pool_df_raw = []

        retcode, stdout, stderr = common.run_os_command('rados df --format json', timeout=1)
        try:
            rados_pool_df_raw = json.loads(stdout)['pools']
        except Exception as e:
            logger.out('Failed to obtain Pool data (rados df): {}'.format(e), state='w')
            rados_pool_df_raw = []

        pool_count = len(ceph_pool_df_raw)
        if debug:
            logger.out("Getting info for {} pools".format(pool_count), state='d', prefix='ceph-thread')
        for pool_idx in range(0, pool_count):
            try:
                # Combine all the data for this pool
                ceph_pool_df = ceph_pool_df_raw[pool_idx]
                rados_pool_df = rados_pool_df_raw[pool_idx]
                pool = ceph_pool_df
                pool.update(rados_pool_df)

                # Ignore any pools that aren't in our pool list
                if pool['name'] not in pool_list:
                    if debug:
                        logger.out("Pool {} not in pool list {}".format(pool['name'], pool_list), state='d', prefix='ceph-thread')
                    continue
                else:
                    if debug:
                        logger.out("Parsing data for pool {}".format(pool['name']), state='d', prefix='ceph-thread')

                # Assemble a useful data structure
                pool_df = {
                    'id': pool['id'],
                    'stored_bytes': pool['stats']['stored'],
                    'free_bytes': pool['stats']['max_avail'],
                    'used_bytes': pool['stats']['bytes_used'],
                    'used_percent': pool['stats']['percent_used'],
                    'num_objects': pool['stats']['objects'],
                    'num_object_clones': pool['num_object_clones'],
                    'num_object_copies': pool['num_object_copies'],
                    'num_objects_missing_on_primary': pool['num_objects_missing_on_primary'],
                    'num_objects_unfound': pool['num_objects_unfound'],
                    'num_objects_degraded': pool['num_objects_degraded'],
                    'read_ops': pool['read_ops'],
                    'read_bytes': pool['read_bytes'],
                    'write_ops': pool['write_ops'],
                    'write_bytes': pool['write_bytes']
                }

                # Write the pool data to Zookeeper
                zkhandler.write([
                    (('pool.stats', pool['name']), str(json.dumps(pool_df)))
                ])
            except Exception as e:
                # One or more of the status commands timed out, just continue
                logger.out('Failed to format and send pool data: {}'.format(e), state='w')
                pass

    # Only grab OSD stats if there are OSDs to grab (otherwise `ceph osd df` hangs)
    osds_this_node = 0
    if len(osd_list) > 0:
        # Get data from Ceph OSDs
        if debug:
            logger.out("Get data from Ceph OSDs", state='d', prefix='ceph-thread')

        # Parse the dump data
        osd_dump = dict()

        command = {"prefix": "osd dump", "format": "json"}
        osd_dump_output = ceph_conn.mon_command(json.dumps(command), b'', timeout=1)[1].decode('ascii')
        try:
            osd_dump_raw = json.loads(osd_dump_output)['osds']
        except Exception as e:
            logger.out('Failed to obtain OSD data: {}'.format(e), state='w')
            osd_dump_raw = []

        if debug:
            logger.out("Loop through OSD dump", state='d', prefix='ceph-thread')
        for osd in osd_dump_raw:
            osd_dump.update({
                str(osd['osd']): {
                    'uuid': osd['uuid'],
                    'up': osd['up'],
                    'in': osd['in'],
                    'primary_affinity': osd['primary_affinity']
                }
            })

        # Parse the df data
        if debug:
            logger.out("Parse the OSD df data", state='d', prefix='ceph-thread')

        osd_df = dict()

        command = {"prefix": "osd df", "format": "json"}
        try:
            osd_df_raw = json.loads(ceph_conn.mon_command(json.dumps(command), b'', timeout=1)[1])['nodes']
        except Exception as e:
            logger.out('Failed to obtain OSD data: {}'.format(e), state='w')
            osd_df_raw = []

        if debug:
            logger.out("Loop through OSD df", state='d', prefix='ceph-thread')
        for osd in osd_df_raw:
            osd_df.update({
                str(osd['id']): {
                    'utilization': osd['utilization'],
                    'var': osd['var'],
                    'pgs': osd['pgs'],
                    'kb': osd['kb'],
                    'weight': osd['crush_weight'],
                    'reweight': osd['reweight'],
                }
            })

        # Parse the status data
        if debug:
            logger.out("Parse the OSD status data", state='d', prefix='ceph-thread')

        osd_status = dict()

        command = {"prefix": "osd status", "format": "pretty"}
        try:
            osd_status_raw = ceph_conn.mon_command(json.dumps(command), b'', timeout=1)[1].decode('ascii')
        except Exception as e:
            logger.out('Failed to obtain OSD status data: {}'.format(e), state='w')
            osd_status_raw = []

        if debug:
            logger.out("Loop through OSD status data", state='d', prefix='ceph-thread')

        for line in osd_status_raw.split('\n'):
            # Strip off colour
            line = re.sub(r'\x1b(\[.*?[@-~]|\].*?(\x07|\x1b\\))', '', line)
            # Split it for parsing
            line = line.split()
            if len(line) > 1 and line[1].isdigit():
                # This is an OSD line so parse it
                osd_id = line[1]
                node = line[3].split('.')[0]
                used = line[5]
                avail = line[7]
                wr_ops = line[9]
                wr_data = line[11]
                rd_ops = line[13]
                rd_data = line[15]
                state = line[17]
                osd_status.update({
                    str(osd_id): {
                        'node': node,
                        'used': used,
                        'avail': avail,
                        'wr_ops': wr_ops,
                        'wr_data': wr_data,
                        'rd_ops': rd_ops,
                        'rd_data': rd_data,
                        'state': state
                    }
                })

        # Merge them together into a single meaningful dict
        if debug:
            logger.out("Merge OSD data together", state='d', prefix='ceph-thread')

        osd_stats = dict()

        for osd in osd_list:
            if zkhandler.read(('osd.node', osd)) == config['node_hostname']:
                osds_this_node += 1
            try:
                this_dump = osd_dump[osd]
                this_dump.update(osd_df[osd])
                this_dump.update(osd_status[osd])
                osd_stats[osd] = this_dump
            except KeyError as e:
                # One or more of the status commands timed out, just continue
                logger.out('Failed to parse OSD stats into dictionary: {}'.format(e), state='w')

        # Upload OSD data for the cluster (primary-only)
        if this_node.router_state == 'primary':
            if debug:
                logger.out("Trigger updates for each OSD", state='d', prefix='ceph-thread')

            for osd in osd_list:
                try:
                    stats = json.dumps(osd_stats[osd])
                    zkhandler.write([
                        (('osd.stats', osd), str(stats))
                    ])
                except KeyError as e:
                    # One or more of the status commands timed out, just continue
                    logger.out('Failed to upload OSD stats from dictionary: {}'.format(e), state='w')

    ceph_conn.shutdown()

    queue.put(ceph_health_colour)
    queue.put(ceph_health)
    queue.put(osds_this_node)

    if debug:
        logger.out("Thread finished", state='d', prefix='ceph-thread')


# VM stats update function
def collect_vm_stats(logger, config, zkhandler, this_node, queue):
    debug = config['debug']
    if debug:
        logger.out("Thread starting", state='d', prefix='vm-thread')

    # Connect to libvirt
    libvirt_name = "qemu:///system"
    if debug:
        logger.out("Connecting to libvirt", state='d', prefix='vm-thread')
    lv_conn = libvirt.open(libvirt_name)
    if lv_conn is None:
        logger.out('Failed to open connection to "{}"'.format(libvirt_name), state='e')

    memalloc = 0
    memprov = 0
    vcpualloc = 0
    # Toggle state management of dead VMs to restart them
    if debug:
        logger.out("Toggle state management of dead VMs to restart them", state='d', prefix='vm-thread')
    # Make a copy of the d_domain; if not, and it changes in flight, this can fail
    fixed_d_domain = this_node.d_domain.copy()
    for domain, instance in fixed_d_domain.items():
        if domain in this_node.domain_list:
            # Add the allocated memory to our memalloc value
            memalloc += instance.getmemory()
            memprov += instance.getmemory()
            vcpualloc += instance.getvcpus()
            if instance.getstate() == 'start' and instance.getnode() == this_node.name:
                if instance.getdom() is not None:
                    try:
                        if instance.getdom().state()[0] != libvirt.VIR_DOMAIN_RUNNING:
                            logger.out("VM {} has failed".format(instance.domname), state='w', prefix='vm-thread')
                            raise
                    except Exception:
                        # Toggle a state "change"
                        logger.out("Resetting state to {} for VM {}".format(instance.getstate(), instance.domname), state='i', prefix='vm-thread')
                        zkhandler.write([
                            (('domain.state', domain), instance.getstate())
                        ])
        elif instance.getnode() == this_node.name:
            memprov += instance.getmemory()

    # Get list of running domains from Libvirt
    running_domains = lv_conn.listAllDomains(libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE)

    # Get statistics from any running VMs
    for domain in running_domains:
        try:
            # Get basic information about the VM
            tree = ElementTree.fromstring(domain.XMLDesc())
            domain_uuid = domain.UUIDString()
            domain_name = domain.name()

            # Get all the raw information about the VM
            if debug:
                logger.out("Getting general statistics for VM {}".format(domain_name), state='d', prefix='vm-thread')
            domain_state, domain_maxmem, domain_mem, domain_vcpus, domain_cputime = domain.info()
            # We can't properly gather stats from a non-running VMs so continue
            if domain_state != libvirt.VIR_DOMAIN_RUNNING:
                continue
            domain_memory_stats = domain.memoryStats()
            domain_cpu_stats = domain.getCPUStats(True)[0]
        except Exception as e:
            if debug:
                try:
                    logger.out("Failed getting VM information for {}: {}".format(domain.name(), e), state='d', prefix='vm-thread')
                except Exception:
                    pass
            continue

        # Ensure VM is present in the domain_list
        if domain_uuid not in this_node.domain_list:
            this_node.domain_list.append(domain_uuid)

        if debug:
            logger.out("Getting disk statistics for VM {}".format(domain_name), state='d', prefix='vm-thread')
        domain_disk_stats = []
        for disk in tree.findall('devices/disk'):
            disk_name = disk.find('source').get('name')
            if not disk_name:
                disk_name = disk.find('source').get('file')
            disk_stats = domain.blockStats(disk.find('target').get('dev'))
            domain_disk_stats.append({
                "name": disk_name,
                "rd_req": disk_stats[0],
                "rd_bytes": disk_stats[1],
                "wr_req": disk_stats[2],
                "wr_bytes": disk_stats[3],
                "err": disk_stats[4]
            })

        if debug:
            logger.out("Getting network statistics for VM {}".format(domain_name), state='d', prefix='vm-thread')
        domain_network_stats = []
        for interface in tree.findall('devices/interface'):
            interface_type = interface.get('type')
            if interface_type not in ['bridge']:
                continue
            interface_name = interface.find('target').get('dev')
            interface_bridge = interface.find('source').get('bridge')
            interface_stats = domain.interfaceStats(interface_name)
            domain_network_stats.append({
                "name": interface_name,
                "bridge": interface_bridge,
                "rd_bytes": interface_stats[0],
                "rd_packets": interface_stats[1],
                "rd_errors": interface_stats[2],
                "rd_drops": interface_stats[3],
                "wr_bytes": interface_stats[4],
                "wr_packets": interface_stats[5],
                "wr_errors": interface_stats[6],
                "wr_drops": interface_stats[7]
            })

        # Create the final dictionary
        domain_stats = {
            "state": libvirt_vm_states[domain_state],
            "maxmem": domain_maxmem,
            "livemem": domain_mem,
            "cpus": domain_vcpus,
            "cputime": domain_cputime,
            "mem_stats": domain_memory_stats,
            "cpu_stats": domain_cpu_stats,
            "disk_stats": domain_disk_stats,
            "net_stats": domain_network_stats
        }

        if debug:
            logger.out("Writing statistics for VM {} to Zookeeper".format(domain_name), state='d', prefix='vm-thread')

        try:
            zkhandler.write([
                (('domain.stats', domain_uuid), str(json.dumps(domain_stats)))
            ])
        except Exception as e:
            if debug:
                logger.out("{}".format(e), state='d', prefix='vm-thread')

    # Close the Libvirt connection
    lv_conn.close()

    queue.put(len(running_domains))
    queue.put(memalloc)
    queue.put(memprov)
    queue.put(vcpualloc)

    if debug:
        logger.out("Thread finished", state='d', prefix='vm-thread')


# Keepalive update function
def node_keepalive(logger, config, zkhandler, this_node):
    debug = config['debug']
    if debug:
        logger.out("Keepalive starting", state='d', prefix='main-thread')

    # Set the migration selector in Zookeeper for clients to read
    if config['enable_hypervisor']:
        if this_node.router_state == 'primary':
            try:
                if zkhandler.read('base.config.migration_target_selector') != config['migration_target_selector']:
                    raise
            except Exception:
                zkhandler.write([
                    ('base.config.migration_target_selector', config['migration_target_selector'])
                ])

    # Set the upstream IP in Zookeeper for clients to read
    if config['enable_networking']:
        if this_node.router_state == 'primary':
            try:
                if zkhandler.read('base.config.upstream_ip') != config['upstream_floating_ip']:
                    raise
            except Exception:
                zkhandler.write([
                    ('base.config.upstream_ip', config['upstream_floating_ip'])
                ])

    # Get past state and update if needed
    if debug:
        logger.out("Get past state and update if needed", state='d', prefix='main-thread')

    past_state = zkhandler.read(('node.state.daemon', this_node.name))
    if past_state != 'run' and past_state != 'shutdown':
        this_node.daemon_state = 'run'
        zkhandler.write([
            (('node.state.daemon', this_node.name), 'run')
        ])
    else:
        this_node.daemon_state = 'run'

    # Ensure the primary key is properly set
    if debug:
        logger.out("Ensure the primary key is properly set", state='d', prefix='main-thread')
    if this_node.router_state == 'primary':
        if zkhandler.read('base.config.primary_node') != this_node.name:
            zkhandler.write([
                ('base.config.primary_node', this_node.name)
            ])

    # Run VM statistics collection in separate thread for parallelization
    if config['enable_hypervisor']:
        vm_thread_queue = Queue()
        vm_stats_thread = Thread(target=collect_vm_stats, args=(logger, config, zkhandler, this_node, vm_thread_queue), kwargs={})
        vm_stats_thread.start()

    # Run Ceph status collection in separate thread for parallelization
    if config['enable_storage']:
        ceph_thread_queue = Queue()
        ceph_stats_thread = Thread(target=collect_ceph_stats, args=(logger, config, zkhandler, this_node, ceph_thread_queue), kwargs={})
        ceph_stats_thread.start()

    # Get node performance statistics
    this_node.memtotal = int(psutil.virtual_memory().total / 1024 / 1024)
    this_node.memused = int(psutil.virtual_memory().used / 1024 / 1024)
    this_node.memfree = int(psutil.virtual_memory().free / 1024 / 1024)
    this_node.cpuload = os.getloadavg()[0]

    # Join against running threads
    if config['enable_hypervisor']:
        vm_stats_thread.join(timeout=4.0)
        if vm_stats_thread.is_alive():
            logger.out('VM stats gathering exceeded 4s timeout, continuing', state='w')
    if config['enable_storage']:
        ceph_stats_thread.join(timeout=4.0)
        if ceph_stats_thread.is_alive():
            logger.out('Ceph stats gathering exceeded 4s timeout, continuing', state='w')

    # Get information from thread queues
    if config['enable_hypervisor']:
        try:
            this_node.domains_count = vm_thread_queue.get()
            this_node.memalloc = vm_thread_queue.get()
            this_node.memprov = vm_thread_queue.get()
            this_node.vcpualloc = vm_thread_queue.get()
        except Exception:
            pass
    else:
        this_node.domains_count = 0
        this_node.memalloc = 0
        this_node.memprov = 0
        this_node.vcpualloc = 0

    if config['enable_storage']:
        try:
            ceph_health_colour = ceph_thread_queue.get()
            ceph_health = ceph_thread_queue.get()
            osds_this_node = ceph_thread_queue.get()
        except Exception:
            ceph_health_colour = logger.fmt_cyan
            ceph_health = 'UNKNOWN'
            osds_this_node = '?'

    # Set our information in zookeeper
    keepalive_time = int(time.time())
    if debug:
        logger.out("Set our information in zookeeper", state='d', prefix='main-thread')
    try:
        zkhandler.write([
            (('node.memory.total', this_node.name), str(this_node.memtotal)),
            (('node.memory.used', this_node.name), str(this_node.memused)),
            (('node.memory.free', this_node.name), str(this_node.memfree)),
            (('node.memory.allocated', this_node.name), str(this_node.memalloc)),
            (('node.memory.provisioned', this_node.name), str(this_node.memprov)),
            (('node.vcpu.allocated', this_node.name), str(this_node.vcpualloc)),
            (('node.cpu.load', this_node.name), str(this_node.cpuload)),
            (('node.count.provisioned_domains', this_node.name), str(this_node.domains_count)),
            (('node.running_domains', this_node.name), ' '.join(this_node.domain_list)),
            (('node.keepalive', this_node.name), str(keepalive_time)),
        ])
    except Exception:
        logger.out('Failed to set keepalive data', state='e')

    # Display node information to the terminal
    if config['log_keepalives']:
        if this_node.router_state == 'primary':
            cst_colour = logger.fmt_green
        elif this_node.router_state == 'secondary':
            cst_colour = logger.fmt_blue
        else:
            cst_colour = logger.fmt_cyan
        logger.out(
            '{}{} keepalive @ {}{} [{}{}{}]'.format(
                logger.fmt_purple,
                config['node_hostname'],
                datetime.now(),
                logger.fmt_end,
                logger.fmt_bold + cst_colour,
                this_node.router_state,
                logger.fmt_end
            ),
            state='t'
        )
        if config['log_keepalive_cluster_details']:
            logger.out(
                '{bold}Maintenance:{nofmt} {maint}  '
                '{bold}Active VMs:{nofmt} {domcount}  '
                '{bold}Networks:{nofmt} {netcount}  '
                '{bold}Load:{nofmt} {load}  '
                '{bold}Memory [MiB]: VMs:{nofmt} {allocmem}  '
                '{bold}Used:{nofmt} {usedmem}  '
                '{bold}Free:{nofmt} {freemem}'.format(
                    bold=logger.fmt_bold,
                    nofmt=logger.fmt_end,
                    maint=this_node.maintenance,
                    domcount=this_node.domains_count,
                    netcount=len(zkhandler.children('base.network')),
                    load=this_node.cpuload,
                    freemem=this_node.memfree,
                    usedmem=this_node.memused,
                    allocmem=this_node.memalloc,
                ),
                state='t'
            )
        if config['enable_storage'] and config['log_keepalive_storage_details']:
            logger.out(
                '{bold}Ceph cluster status:{nofmt} {health_colour}{health}{nofmt}  '
                '{bold}Total OSDs:{nofmt} {total_osds}  '
                '{bold}Node OSDs:{nofmt} {node_osds}  '
                '{bold}Pools:{nofmt} {total_pools}  '.format(
                    bold=logger.fmt_bold,
                    health_colour=ceph_health_colour,
                    nofmt=logger.fmt_end,
                    health=ceph_health,
                    total_osds=len(zkhandler.children('base.osd')),
                    node_osds=osds_this_node,
                    total_pools=len(zkhandler.children('base.pool'))
                ),
                state='t'
            )

    # Look for dead nodes and fence them
    if not this_node.maintenance:
        if debug:
            logger.out("Look for dead nodes and fence them", state='d', prefix='main-thread')
        if config['daemon_mode'] == 'coordinator':
            for node_name in zkhandler.children('base.node'):
                try:
                    node_daemon_state = zkhandler.read(('node.state.daemon', node_name))
                    node_keepalive = int(zkhandler.read(('node.keepalive', node_name)))
                except Exception:
                    node_daemon_state = 'unknown'
                    node_keepalive = 0

                # Handle deadtime and fencng if needed
                # (A node is considered dead when its keepalive timer is >6*keepalive_interval seconds
                # out-of-date while in 'start' state)
                node_deadtime = int(time.time()) - (int(config['keepalive_interval']) * int(config['fence_intervals']))
                if node_keepalive < node_deadtime and node_daemon_state == 'run':
                    logger.out('Node {} seems dead - starting monitor for fencing'.format(node_name), state='w')
                    zk_lock = zkhandler.writelock(('node.state.daemon', node_name))
                    with zk_lock:
                        # Ensures that, if we lost the lock race and come out of waiting,
                        # we won't try to trigger our own fence thread.
                        if zkhandler.read(('node.state.daemon', node_name)) != 'dead':
                            fence_thread = Thread(target=pvcnoded.util.fencing.fence_node, args=(node_name, zkhandler, config, logger), kwargs={})
                            fence_thread.start()
                            # Write the updated data after we start the fence thread
                            zkhandler.write([
                                (('node.state.daemon', node_name), 'dead')
                            ])

    if debug:
        logger.out("Keepalive finished", state='d', prefix='main-thread')
