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

import kazoo.client, ansiiprint

# Child list function
def listchildren(zk_conn, key):
    children = zk_conn.get_children(key)
    return children

# Data read function
def readdata(zk_conn, key):
    data_raw = zk_conn.get(key)
    data = data_raw[0].decode('ascii')
    meta = data_raw[1]
    return data

# Data write function
def writedata(zk_conn, key, data):
    # Get the current version
    orig_data_raw = zk_conn.get(key)
    meta = orig_data_raw[1]
    if meta == None:
        ansiiprint.echo('Zookeeper key "{}" does not exist'.format(key), '', 'e')
        return 1

    version = meta.version
    new_version = version + 1
    zk_transaction = zk_conn.transaction()
    for line in data:
        zk_transaction.set_data(key, line.encode('ascii'))
    try:
        zk_transaction.check(key, new_version)
    except TypeError:
        ansiiprint.echo('Zookeeper key "{}" does not match expected version'.format(key), '', 'e')
        return 1
    zk_transaction.commit()
    return 0

# Key create function
def createkey(zk_conn, key, data):
    zk_transaction = zk_conn.transaction()
    for line in data:
        zk_transaction.create(key, line.encode('ascii'))
    zk_transaction.commit()

