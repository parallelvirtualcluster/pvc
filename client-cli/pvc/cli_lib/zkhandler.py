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

import uuid


# Exists function
def exists(zk_conn, key):
    stat = zk_conn.exists(key)
    if stat:
        return True
    else:
        return False


# Child list function
def listchildren(zk_conn, key):
    children = zk_conn.get_children(key)
    return children


# Delete key function
def deletekey(zk_conn, key, recursive=True):
    zk_conn.delete(key, recursive=recursive)


# Data read function
def readdata(zk_conn, key):
    data_raw = zk_conn.get(key)
    data = data_raw[0].decode('utf8')
    return data


# Data write function
def writedata(zk_conn, kv):
    # Start up a transaction
    zk_transaction = zk_conn.transaction()

    # Proceed one KV pair at a time
    for key in sorted(kv):
        data = kv[key]

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
