#!/usr/bin/env python3

# zkhandler.py - Secure versioned ZooKeeper updates
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018  Joshua M. Boniface <joshua@boniface.me>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
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

import kazoo.client
import uuid

#import pvcd.log as log

# Child list function
def listchildren(zk_conn, key):
    children = zk_conn.get_children(key)
    return children

# Key deletion function
def deletekey(zk_conn, key, recursive=True):
    zk_conn.delete(key, recursive=recursive)

# Data read function
def readdata(zk_conn, key):
    data_raw = zk_conn.get(key)
    data = data_raw[0].decode('utf8')
    meta = data_raw[1]
    return data

# Data write function
def writedata(zk_conn, kv):
    # Start up a transaction
    zk_transaction = zk_conn.transaction()

    # Proceed one KV pair at a time
    for key in sorted(kv):
        data = kv[key]
        if not data:
            data = ''

        # Check if this key already exists or not
        if not zk_conn.exists(key):
            # We're creating a new key
            zk_transaction.create(key, str(data).encode('utf8'))
        else:
            # We're updating a key with version validation
            orig_data = zk_conn.get(key)
            version = orig_data[1].version

            # Set what we expect the new version to be
            new_version = version + 1

            # Update the data
            zk_transaction.set_data(key, str(data).encode('utf8'))

            # Set up the check
            try:
                zk_transaction.check(key, new_version)
            except TypeError:
                print('Zookeeper key "{}" does not match expected version'.format(key))
                return False

    # Commit the transaction
    try:
        zk_transaction.commit()
        return True
    except Exception:
        return False

# Key rename function
def renamekey(zk_conn, kv):
    # Start up a transaction
    zk_transaction = zk_conn.transaction()

    # Proceed one KV pair at a time
    for key in sorted(kv):
        old_name = key
        new_name = kv[key]

        old_data = zk_conn.get(old_name)

        # Find the children of old_name recursively
        child_keys = list()
        def get_children(key):
            children = zk_conn.get_children(key)
            if not children:
                child_keys.append(key)
                return
            else:
                for ckey in children:
                    get_children(key)
        get_children(old_name)

        # Get the data out of each of the child keys
        child_data = dict()
        for ckey in child_keys:
            child_data[ckey] = zk_conn.get(ckey)

        # Create the new parent key
        zk_transaction.create(new_name, old_data)

        # For each child key, create the key and add the data
        for ckey in child_keys:
            new_ckey_name = ckey.replace(old_name, new_name)
            zk_transaction.create(new_ckey_name, child_data[ckey])

        # Remove recursively the old key
        zk_transaction.delete(old_name, recursive=True)

    # Commit the transaction
    try:
        zk_transaction.commit()
        return True
    except Exception:
        return False

# Write lock function
def writelock(zk_conn, key):
    lock_id = str(uuid.uuid1())
    lock = zk_conn.WriteLock('{}'.format(key), lock_id)
    return lock

# Read lock function
def readlock(zk_conn, key):
    lock_id = str(uuid.uuid1())
    lock = zk_conn.ReadLock('{}'.format(key), lock_id)
    return lock
