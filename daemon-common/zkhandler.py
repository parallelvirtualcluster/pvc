#!/usr/bin/env python3

# zkhandler.py - Secure versioned ZooKeeper updates
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

import os
import time
import uuid
import json
from functools import wraps
from kazoo.client import KazooClient, KazooState
from kazoo.exceptions import NoNodeError


#
# Function decorators
#
class ZKConnection(object):
    """
    Decorates a function with a Zookeeper connection before and after the main call.

    The decorated function must accept the `zkhandler` argument as its first argument, and
    then use this to access the connection.
    """
    def __init__(self, config):
        self.config = config

    def __call__(self, function):
        if not callable(function):
            return

        @wraps(function)
        def connection(*args, **kwargs):
            zkhandler = ZKHandler(self.config)
            zkhandler.connect()
            zkhandler.schema.load(zkhandler.read(zkhandler.schema.path('base.schema.version')), quiet=True)

            ret = function(zkhandler, *args, **kwargs)

            zkhandler.disconnect()
            del zkhandler

            return ret

        return connection


#
# Exceptions
#
class ZKConnectionException(Exception):
    """
    A exception when connecting to the cluster
    """
    def __init__(self, zkhandler, error=None):
        if error is not None:
            self.message = "Failed to connect to Zookeeper at {}: {}".format(zkhandler.coordinators(), error)
        else:
            self.message = "Failed to connect to Zookeeper at {}".format(zkhandler.coordinators())
        zkhandler.disconnect()

    def __str__(self):
        return str(self.message)


#
# Handler class
#
class ZKHandler(object):
    def __init__(self, config, logger=None):
        """
        Initialize an instance of the ZKHandler class with config

        A zk_conn object will be created but not started

        A ZKSchema instance will be created
        """
        self.encoding = 'utf8'
        self.coordinators = config['coordinators']
        self.logger = logger
        self.zk_conn = KazooClient(hosts=self.coordinators)
        self._schema = ZKSchema()

    #
    # Class meta-functions
    #
    def coordinators(self):
        return str(self.coordinators)

    def log(self, message, state=''):
        if self.logger is not None:
            self.logger.out(message, state)
        else:
            print(message)

    #
    # Properties
    #
    @property
    def schema(self):
        return self._schema

    #
    # State/connection management
    #
    def listener(self, state):
        if state == KazooState.CONNECTED:
            self.log('Connection to Zookeeper started', state='o')
        else:
            self.log('Connection to Zookeeper lost', state='w')

            while True:
                time.sleep(0.5)

                _zk_conn = KazooClient(hosts=self.coordinators)
                try:
                    _zk_conn.start()
                except Exception:
                    del _zk_conn
                    continue

                self.zk_conn = _zk_conn
                self.zk_conn.add_listener(self.listener)
                break

    def connect(self, persistent=False):
        """
        Start the zk_conn object and connect to the cluster, then load the current schema version
        """
        try:
            self.zk_conn.start()
            if persistent:
                self.zk_conn.add_listener(self.listener)
        except Exception as e:
            raise ZKConnectionException(self, e)

    def disconnect(self):
        """
        Stop and close the zk_conn object and disconnect from the cluster

        The class instance may be reused later (avoids persistent connections)
        """
        self.zk_conn.stop()
        self.zk_conn.close()

    #
    # Schema helper actions
    #
    def get_schema_path(self, key):
        if isinstance(key, tuple):
            # This is a key tuple with both an ipath and an item
            ipath, item = key
        elif isinstance(key, str):
            # This is a key string with just an ipath
            ipath = key
            item = None
        else:
            # This is an invalid key
            return None

        return self.schema.path(ipath, item=item)

    #
    # Key Actions
    #
    def exists(self, key):
        """
        Check if a key exists
        """
        path = self.get_schema_path(key)
        stat = self.zk_conn.exists(path)
        if stat:
            return True
        else:
            return False

    def read(self, key):
        """
        Read data from a key
        """
        path = self.get_schema_path(key)
        return self.zk_conn.get(path)[0].decode(self.encoding)

    def write(self, kvpairs):
        """
        Create or update one or more keys' data
        """
        if type(kvpairs) is not list:
            self.log("ZKHandler error: Key-value sequence is not a list", state='e')
            return False

        transaction = self.zk_conn.transaction()

        for kvpair in (kvpairs):
            if type(kvpair) is not tuple:
                self.log("ZKHandler error: Key-value pair '{}' is not a tuple".format(kvpair), state='e')
                return False

            key = kvpair[0]
            value = kvpair[1]

            path = self.get_schema_path(key)

            if not self.exists(path):
                # Creating a new key
                transaction.create(path, str(value).encode(self.encoding))

            else:
                # Updating an existing key
                data = self.zk_conn.get(path)
                version = data[1].version

                # Validate the expected version after the execution
                new_version = version + 1

                # Update the data
                transaction.set_data(path, str(value).encode(self.encoding))

                # Check the data
                try:
                    transaction.check(path, new_version)
                except TypeError:
                    self.log("ZKHandler error: Key '{}' does not match expected version".format(path), state='e')
                    return False

        try:
            transaction.commit()
            return True
        except Exception as e:
            self.log("ZKHandler error: Failed to commit transaction: {}".format(e), state='e')
            return False

    def delete(self, keys, recursive=True):
        """
        Delete a key or list of keys (defaults to recursive)
        """
        if type(keys) is not list:
            keys = [keys]

        for key in keys:
            path = self.get_schema_path(key)
            if self.exists(path):
                try:
                    self.zk_conn.delete(path, recursive=recursive)
                except Exception as e:
                    self.log("ZKHandler error: Failed to delete key {}: {}".format(path, e), state='e')
                    return False

        return True

    def children(self, key):
        """
        Lists all children of a key
        """
        path = self.get_schema_path(key)
        return self.zk_conn.get_children(path)

    def rename(self, kkpairs):
        """
        Rename one or more keys to a new value
        """
        if type(kkpairs) is not list:
            self.log("ZKHandler error: Key-key sequence is not a list", state='e')
            return False

        transaction = self.zk_conn.transaction()

        def rename_element(transaction, source_path, destnation_path):
            data = self.zk_conn.get(source_path)[0]
            transaction.create(destination_path, data)

            if self.children(source_path):
                for child_path in self.children(source_path):
                    child_source_path = "{}/{}".format(source_path, child_path)
                    child_destination_path = "{}/{}".format(destination_path, child_path)
                    rename_element(transaction, child_source_path, child_destination_path)

            transaction.delete(source_path)

        for kkpair in (kkpairs):
            if type(kkpair) is not tuple:
                self.log("ZKHandler error: Key-key pair '{}' is not a tuple".format(kkpair), state='e')
                return False

            source_key = kkpair[0]
            source_path = self.get_schema_path(source_key)

            destination_key = kkpair[1]
            destination_path = self.get_schema_path(destination_key)

            if not self.exists(source_path):
                self.log("ZKHander error: Source key '{}' does not exist".format(source_path), state='e')
                return False
            if self.exists(destination_path):
                self.log("ZKHander error: Destination key '{}' already exists".format(destination_path), state='e')
                return False

            rename_element(transaction, source_path, destination_path)

        try:
            transaction.commit()
            return True
        except Exception as e:
            self.log("ZKHandler error: Failed to commit transaction: {}".format(e), state='e')
            return False

    #
    # Lock actions
    #
    def readlock(self, key):
        """
        Acquires a read lock on a key
        """
        count = 1
        lock = None

        path = self.get_schema_path(key)

        while True:
            try:
                lock_id = str(uuid.uuid1())
                lock = self.zk_conn.ReadLock(path, lock_id)
                break
            except Exception as e:
                if count > 5:
                    self.log("ZKHandler warning: Failed to acquire read lock after 5 tries: {}".format(e), state='e')
                    break
                else:
                    time.sleep(0.5)
                    count += 1
                    continue

        return lock

    def writelock(self, key):
        """
        Acquires a write lock on a key
        """
        count = 1
        lock = None

        path = self.get_schema_path(key)

        while True:
            try:
                lock_id = str(uuid.uuid1())
                lock = self.zk_conn.WriteLock(path, lock_id)
                break
            except Exception as e:
                if count > 5:
                    self.log("ZKHandler warning: Failed to acquire write lock after 5 tries: {}".format(e), state='e')
                    break
                else:
                    time.sleep(0.5)
                    count += 1
                    continue

        return lock

    def exclusivelock(self, key):
        """
        Acquires an exclusive lock on a key
        """
        count = 1
        lock = None

        path = self.get_schema_path(key)

        while True:
            try:
                lock_id = str(uuid.uuid1())
                lock = self.zk_conn.Lock(path, lock_id)
                break
            except Exception as e:
                if count > 5:
                    self.log("ZKHandler warning: Failed to acquire exclusive lock after 5 tries: {}".format(e), state='e')
                    break
                else:
                    time.sleep(0.5)
                    count += 1
                    continue

        return lock


#
# Schema classes
#
class ZKSchema(object):
    # Current version
    _version = 0

    # Root for doing nested keys
    _schema_root = ''

    # Primary schema definition for the current version
    _schema = {
        'version': f'{_version}',
        'root': f'{_schema_root}',
        # Base schema defining core keys; this is all that is initialized on cluster init()
        'base': {
            'schema': f'{_schema_root}/schema',
            'schema.version': f'{_schema_root}/schema/version',
            'config': f'{_schema_root}/config',
            'config.maintenance': f'{_schema_root}/config/maintenance',
            'config.primary_node': f'{_schema_root}/config/primary_node',
            'config.primary_node.sync_lock': f'{_schema_root}/config/primary_node/sync_lock',
            'config.upstream_ip': f'{_schema_root}/config/upstream_ip',
            'config.migration_target_selector': f'{_schema_root}/config/migration_target_selector',
            'cmd': f'{_schema_root}/cmd',
            'cmd.node': f'{_schema_root}/cmd/nodes',
            'cmd.domain': f'{_schema_root}/cmd/domains',
            'cmd.ceph': f'{_schema_root}/cmd/ceph',
            'node': f'{_schema_root}/nodes',
            'domain': f'{_schema_root}/domains',
            'network': f'{_schema_root}/networks',
            'storage': f'{_schema_root}/ceph',
            'storage.util': f'{_schema_root}/ceph/util',
            'osd': f'{_schema_root}/ceph/osds',
            'pool': f'{_schema_root}/ceph/pools',
            'volume': f'{_schema_root}/ceph/volumes',
            'snapshot': f'{_schema_root}/ceph/snapshots',
        },
        # The schema of an individual node entry (/nodes/{node_name})
        'node': {
            'keepalive': '/keepalive',
            'mode': '/daemonmode',
            'data.active_schema': '/activeschema',
            'data.latest_schema': '/latestschema',
            'data.static': '/staticdata',
            'running_domains': '/runningdomains',
            'count.provisioned_domains': '/domainscount',
            'count.networks': '/networkscount',
            'state.daemon': '/daemonstate',
            'state.router': '/routerstate',
            'state.domain': '/domainstate',
            'cpu.load': '/cpuload',
            'vcpu.allocated': '/vcpualloc',
            'memory.total': '/memtotal',
            'memory.used': '/memused',
            'memory.free': '/memfree',
            'memory.allocated': '/memalloc',
            'memory.provisioned': '/memprov',
            'ipmi.hostname': '/ipmihostname',
            'ipmi.username': '/ipmiusername',
            'ipmi.password': '/ipmipassword'
        },
        # The schema of an individual domain entry (/domains/{domain_uuid})
        'domain': {
            'name': '',  # The root key
            'xml': '/xml',
            'state': '/state',
            'profile': '/profile',
            'stats': '/stats',
            'node': '/node',
            'last_node': '/lastnode',
            'failed_reason': '/failedreason',
            'storage.volumes': '/rbdlist',
            'console.log': '/consolelog',
            'console.vnc': '/vnc',
            'meta.autostart': '/node_autostart',
            'meta.migrate_method': '/migration_method',
            'meta.node_selector': '/node_selector',
            'meta.node_limit': '/node_limit',
            'migrate.sync_lock': '/migrate_sync_lock'
        },
        # The schema of an individual network entry (/networks/{vni})
        'network': {
            'type': '/nettype',
            'rules': '/firewall_rules',
            'nameservers': '/name_servers',
            'domain': '/domain',
            'ip4.gateway': '/ip4_gateway',
            'ip4.network': '/ip4_network',
            'ip4.dhcp': '/dhcp4_flag',
            'ip4.reservations': '/dhcp4_reservations',
            'ip4.dhcp_start': '/dhcp4_start',
            'ip4.dhcp_end': '/dhcp4_end',
            'ip6.gateway': '/ip6_gateway',
            'ip6.network': '/ip6_network',
            'ip6.dhcp': '/dhcp6_flag'
        },
        # The schema of an individual OSD entry (/ceph/osds/{osd_id})
        'osd': {
            'node': '/node',
            'device': '/device',
            'stats': '/stats'
        },
        # The schema of an individual pool entry (/ceph/pools/{pool_name})
        'pool': {
            'pgs': '/pgs',
            'stats': '/stats'
        },
        # The schema of an individual volume entry (/ceph/volumes/{pool_name}/{volume_name})
        'volume': {
            'stats': '/stats'
        },
        # The schema of an individual snapshot entry (/ceph/volumes/{pool_name}/{volume_name}/{snapshot_name})
        'snapshot': {
            'stats': '/stats'
        }
    }

    # Properties
    @property
    def schema_root(self):
        return self._schema_root

    @schema_root.setter
    def schema_root(self, schema_root):
        self._schema_root = schema_root

    @property
    def version(self):
        return int(self._version)

    @version.setter
    def version(self, version):
        self._version = int(version)

    @property
    def schema(self):
        return self._schema

    @schema.setter
    def schema(self, schema):
        self._schema = schema

    def __init__(self):
        pass

    def __repr__(self):
        return f'ZKSchema({self.version})'

    def __lt__(self, other):
        if self.version < other.version:
            return True
        else:
            return False

    def __le__(self, other):
        if self.version <= other.version:
            return True
        else:
            return False

    def __gt__(self, other):
        if self.version > other.version:
            return True
        else:
            return False

    def __ge__(self, other):
        if self.version >= other.version:
            return True
        else:
            return False

    def __eq__(self, other):
        if self.version == other.version:
            return True
        else:
            return False

    # Load the schema of a given version from a file
    def load(self, version, quiet=False):
        if not quiet:
            print(f'Loading schema version {version}')

        with open(f'daemon_lib/migrations/versions/{version}.json', 'r') as sfh:
            self.schema = json.load(sfh)
            self.version = self.schema.get('version')

    # Get key paths
    def path(self, ipath, item=None):
        itype, *ipath = ipath.split('.')

        if item is None:
            return self.schema.get(itype).get('.'.join(ipath))
        else:
            base_path = self.schema.get('base').get(itype)
            sub_path = self.schema.get(itype).get('.'.join(ipath))
            if sub_path is None:
                sub_path = ''
            return f'{base_path}/{item}{sub_path}'

    # Get keys of a schema location
    def keys(self, itype=None):
        if itype is None:
            return list(self.schema.get('base').keys())
        else:
            return list(self.schema.get(itype).keys())

    # Get the active version of a cluster's schema
    def get_version(self, zkhandler):
        try:
            current_version = zkhandler.read(self.path('base.schema.version'))
        except NoNodeError:
            current_version = 0
        return current_version

    # Validate an active schema against a Zookeeper cluster
    def validate(self, zkhandler, logger=None):
        result = True

        # Walk the entire tree checking our schema
        for elem in ['base']:
            for key in self.keys(elem):
                kpath = f'{elem}.{key}'
                if not zkhandler.exists(self.path(kpath)):
                    if logger is not None:
                        logger.out(f'Key not found: {self.path(kpath)}', state='w')
                    result = False

        for elem in ['node', 'domain', 'network', 'osd', 'pool']:
            # First read all the subelements of the key class
            for child in zkhandler.children(self.path(f'base.{elem}')):
                # For each key in the schema for that particular elem
                for ikey in self.keys(elem):
                    kpath = f'{elem}.{ikey}'
                    # Validate that the key exists for that child
                    if not zkhandler.exists(self.path(kpath, child)):
                        if logger is not None:
                            logger.out(f'Key not found: {self.path(kpath, child)}', state='w')
                        result = False

        # These two have several children layers that must be parsed through
        for elem in ['volume']:
            # First read all the subelements of the key class (pool layer)
            for pchild in zkhandler.children(self.path(f'base.{elem}')):
                # Finally read all the subelements of the key class (volume layer)
                for vchild in zkhandler.children(self.path(f'base.{elem}') + f'/{pchild}'):
                    child = f'{pchild}/{vchild}'
                    # For each key in the schema for that particular elem
                    for ikey in self.keys(elem):
                        kpath = f'{elem}.{ikey}'
                        # Validate that the key exists for that child
                        if not zkhandler.exists(self.path(kpath, child)):
                            if logger is not None:
                                logger.out(f'Key not found: {self.path(kpath, child)}', state='w')
                            result = False

        for elem in ['snapshot']:
            # First read all the subelements of the key class (pool layer)
            for pchild in zkhandler.children(self.path(f'base.{elem}')):
                # Next read all the subelements of the key class (volume layer)
                for vchild in zkhandler.children(self.path(f'base.{elem}') + f'/{pchild}'):
                    # Finally read all the subelements of the key class (volume layer)
                    for schild in zkhandler.children(self.path(f'base.{elem}') + f'/{pchild}/{vchild}'):
                        child = f'{pchild}/{vchild}/{schild}'
                        # For each key in the schema for that particular elem
                        for ikey in self.keys(elem):
                            kpath = f'{elem}.{ikey}'
                            # Validate that the key exists for that child
                            if not zkhandler.exists(self.path(kpath, child)):
                                if logger is not None:
                                    logger.out(f'Key not found: {self.path(kpath, child)}', state='w')
                                result = False

        return result

    # Apply the current schema to the cluster
    def apply(self, zkhandler):
        # Walk the entire tree checking our schema
        for elem in ['base']:
            for key in self.keys(elem):
                kpath = f'{elem}.{key}'
                if not zkhandler.exists(self.path(kpath)):
                    zkhandler.write([
                        (self.path(kpath), '')
                    ])

        for elem in ['node', 'domain', 'network', 'osd', 'pool']:
            # First read all the subelements of the key class
            for child in zkhandler.children(self.path(f'base.{elem}')):
                # For each key in the schema for that particular elem
                for ikey in self.keys(elem):
                    kpath = f'{elem}.{ikey}'
                    # Validate that the key exists for that child
                    if not zkhandler.exists(self.path(kpath, child)):
                        zkhandler.write([
                            (self.path(kpath), '')
                        ])

        # These two have several children layers that must be parsed through
        for elem in ['volume']:
            # First read all the subelements of the key class (pool layer)
            for pchild in zkhandler.children(self.path(f'base.{elem}')):
                # Finally read all the subelements of the key class (volume layer)
                for vchild in zkhandler.children(self.path(f'base.{elem}') + f'/{pchild}'):
                    child = f'{pchild}/{vchild}'
                    # For each key in the schema for that particular elem
                    for ikey in self.keys(elem):
                        kpath = f'{elem}.{ikey}'
                        # Validate that the key exists for that child
                        if not zkhandler.exists(self.path(kpath, child)):
                            zkhandler.write([
                                (self.path(kpath), '')
                            ])

        for elem in ['snapshot']:
            # First read all the subelements of the key class (pool layer)
            for pchild in zkhandler.children(self.path(f'base.{elem}')):
                # Next read all the subelements of the key class (volume layer)
                for vchild in zkhandler.children(self.path(f'base.{elem}') + f'/{pchild}'):
                    # Finally read all the subelements of the key class (volume layer)
                    for schild in zkhandler.children(self.path(f'base.{elem}') + f'/{pchild}/{vchild}'):
                        child = f'{pchild}/{vchild}/{schild}'
                        # For each key in the schema for that particular elem
                        for ikey in self.keys(elem):
                            kpath = f'{elem}.{ikey}'
                            # Validate that the key exists for that child
                            if not zkhandler.exists(self.path(kpath, child)):
                                zkhandler.write([
                                    (self.path(kpath), '')
                                ])

        zkhandler.write([
            (self.path('base.schema.version'), self.version)
        ])

    # Migrate key diffs
    def run_migrate(self, zkhandler, changes):
        diff_add = changes['add']
        diff_remove = changes['remove']
        diff_rename = changes['rename']
        add_tasks = list()
        for key in diff_add.keys():
            add_tasks.append((diff_add[key], ''))
        remove_tasks = list()
        for key in diff_remove.keys():
            remove_tasks.append(diff_remove[key])
        rename_tasks = list()
        for key in diff_rename.keys():
            rename_tasks.append((diff_rename[key]['from'], diff_rename[key]['to']))

        zkhandler.write(add_tasks)
        zkhandler.delete(remove_tasks)
        zkhandler.rename(rename_tasks)

    # Migrate from older to newer schema
    def migrate(self, zkhandler, new_version):
        # Determine the versions in between
        versions = ZKSchema.find_all(start=self.version, end=new_version)
        if versions is None:
            return

        for version in versions:
            # Create a new schema at that version
            zkschema_new = ZKSchema()
            zkschema_new.load(version)
            # Get a list of changes
            changes = ZKSchema.key_diff(self, zkschema_new)
            # Apply those changes
            self.run_migrate(zkhandler, changes)

    # Rollback from newer to older schema
    def rollback(self, zkhandler, old_version):
        # Determine the versions in between
        versions = ZKSchema.find_all(start=old_version - 1, end=self.version - 1)
        if versions is None:
            return

        versions.reverse()

        for version in versions:
            # Create a new schema at that version
            zkschema_old = ZKSchema()
            zkschema_old.load(version)
            # Get a list of changes
            changes = ZKSchema.key_diff(self, zkschema_old)
            # Apply those changes
            self.run_migrate(zkhandler, changes)

    @classmethod
    def key_diff(cls, schema_a, schema_b):
        # schema_a = current
        # schema_b = new

        diff_add = dict()
        diff_remove = dict()
        diff_rename = dict()

        # Parse through each core element
        for elem in ['base', 'node', 'domain', 'network', 'osd', 'pool', 'volume', 'snapshot']:
            set_a = set(schema_a.keys(elem))
            set_b = set(schema_b.keys(elem))
            diff_keys = set_a ^ set_b

            for item in diff_keys:
                elem_item = f'{elem}.{item}'
                if item not in schema_a.keys(elem) and item in schema_b.keys(elem):
                    diff_add[elem_item] = schema_b.path(elem_item)
                if item in schema_a.keys(elem) and item not in schema_b.keys(elem):
                    diff_remove[elem_item] = schema_a.path(elem_item)

            for item in set_b:
                elem_item = f'{elem}.{item}'
                if schema_a.path(elem_item) is not None and \
                   schema_b.path(elem_item) is not None and \
                   schema_a.path(elem_item) != schema_b.path(elem_item):
                    diff_rename[elem_item] = {'from': schema_a.path(elem_item), 'to': schema_b.path(elem_item)}

        return {'add': diff_add, 'remove': diff_remove, 'rename': diff_rename}

    # Load in the schemal of the current cluster
    @classmethod
    def load_current(cls, zkhandler):
        new_instance = cls()
        version = new_instance.get_version(zkhandler)
        new_instance.load(version)
        return new_instance

    # Write the latest schema to a file
    @classmethod
    def write(cls):
        schema_file = 'daemon_lib/migrations/versions/{}.json'.format(cls._version)
        with open(schema_file, 'w') as sfh:
            json.dump(cls._schema, sfh)

    # Static methods for reading information from the files
    @staticmethod
    def find_all(start=0, end=None):
        versions = list()
        for version in os.listdir('daemon_lib/migrations/versions'):
            sequence_id = int(version.split('.')[0])
            if end is None:
                if sequence_id > start:
                    versions.append(sequence_id)
            else:
                if sequence_id > start and sequence_id <= end:
                    versions.append(sequence_id)
        if len(versions) > 0:
            return versions
        else:
            return None

    @staticmethod
    def find_latest():
        latest_version = 0
        for version in os.listdir('daemon_lib/migrations/versions'):
            sequence_id = int(version.split('.')[0])
            if sequence_id > latest_version:
                latest_version = sequence_id
        return latest_version
