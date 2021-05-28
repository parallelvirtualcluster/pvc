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

import time
import uuid
from kazoo.client import KazooClient


class ZKHandler(object):
    def __init__(self, hosts):
        """
        Initialize an instance of the ZKHandler class with config

        A zk_conn object will be created but not started
        """
        self.encoding = 'utf8'
        self.zk_conn = KazooClient(hosts=hosts)

    #
    # State/connection management
    #
    def connect(self):
        """
        Start the zk_conn object and connect to the cluster
        """
        self.zk_conn.start()

    def disconnect(self):
        """
        Stop and close the zk_conn object and disconnect from the cluster

        The class instance may be reused later (avoids persistent connections)
        """
        self.zk_conn.stop()
        self.zk_conn.close()

    #
    # Key Actions
    #
    def exists(self, key):
        """
        Check if a key exists
        """
        stat = self.zk_conn.exists(key)
        if stat:
            return True
        else:
            return False

    def read(self, key):
        """
        Read data from a key
        """
        return self.zk_conn.get(key)[0].decode(self.encoding)

    def write(self, kvpairs):
        """
        Create or update one or more keys' data
        """
        if type(kvpairs) is not list:
            print("ZKHandler error: Key-value sequence is not a list")
            return False

        transaction = self.zk_conn.transaction()

        for kvpair in (kvpairs):
            if type(kvpair) is not tuple:
                print("ZKHandler error: Key-value pair '{}' is not a tuple".format(kvpair))
                return False

            key = kvpair[0]
            value = kvpair[1]

            if not self.exists(key):
                # Creating a new key
                transaction.create(key, str(value).encode(self.encoding))

            else:
                # Updating an existing key
                data = self.zk_conn.get(key)
                version = data[1].version

                # Validate the expected version after the execution
                new_version = version + 1

                # Update the data
                transaction.set_data(key, str(value).encode(self.encoding))

                # Check the data
                try:
                    transaction.check(key, new_version)
                except TypeError:
                    print("ZKHandler error: Key '{}' does not match expected version".format(key))
                    return False

        try:
            transaction.commit()
            return True
        except Exception as e:
            print("ZKHandler error: Failed to commit transaction: {}".format(e))
            return False

    def delete(self, key, recursive=True):
        """
        Delete a key (defaults to recursive)
        """
        if self.zk_conn.delete(key, recursive=recursive):
            return True
        else:
            return False

    def children(self, key):
        """
        Lists all children of a key
        """
        return self.zk_conn.get_children(key)

    def rename(self, kkpairs):
        """
        Rename one or more keys to a new value
        """
        if type(kkpairs) is not list:
            print("ZKHandler error: Key-key sequence is not a list")
            return False

        transaction = self.zk_conn.transaction()

        def rename_element(transaction, source_key, destnation_key):
            data = self.zk_conn.get(source_key)[0]
            transaction.create(destination_key, data)

            if self.children(source_key):
                for child_key in self.children(source_key):
                    child_source_key = "{}/{}".format(source_key, child_key)
                    child_destination_key = "{}/{}".format(destination_key, child_key)
                    rename_element(transaction, child_source_key, child_destination_key)

            transaction.delete(source_key, recursive=True)

        for kkpair in (kkpairs):
            if type(kkpair) is not tuple:
                print("ZKHandler error: Key-key pair '{}' is not a tuple".format(kkpair))
                return False

            source_key = kkpair[0]
            destination_key = kkpair[1]

            if not self.exists(source_key):
                print("ZKHander error: Source key '{}' does not exist".format(source_key))
                return False
            if self.exists(destination_key):
                print("ZKHander error: Destination key '{}' already exists".format(destination_key))
                return False

            rename_element(transaction, source_key, destination_key)

        try:
            transaction.commit()
            return True
        except Exception as e:
            print("ZKHandler error: Failed to commit transaction: {}".format(e))
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

        while True:
            try:
                lock_id = str(uuid.uuid1())
                lock = self.zk_conn.ReadLock(key, lock_id)
                break
            except Exception as e:
                if count > 5:
                    print("ZKHandler warning: Failed to acquire read lock after 5 tries: {}".format(e))
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

        while True:
            try:
                lock_id = str(uuid.uuid1())
                lock = self.zk_conn.WriteLock(key, lock_id)
                break
            except Exception as e:
                if count > 5:
                    print("ZKHandler warning: Failed to acquire write lock after 5 tries: {}".format(e))
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

        while True:
            try:
                lock_id = str(uuid.uuid1())
                lock = self.zk_conn.Lock(key, lock_id)
                break
            except Exception as e:
                if count > 5:
                    print("ZKHandler warning: Failed to acquire exclusive lock after 5 tries: {}".format(e))
                    break
                else:
                    time.sleep(0.5)
                    count += 1
                    continue

        return lock
