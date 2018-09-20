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
import client_lib.ansiiprint as ansiiprint

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
def writedata(zk_conn, kv):
    # Get the current version; we base this off the first key (ordering in multi-key calls is irrelevant)
    first_key = list(kv.keys())[0]
    orig_data_raw = zk_conn.get(first_key)
    meta = orig_data_raw[1]
    if meta == None:
        ansiiprint.echo('Zookeeper key "{}" does not exist'.format(first_key), '', 'e')
        return 1

    version = meta.version
    new_version = version + 1
    zk_transaction = zk_conn.transaction()
    for key, data in kv.items():
        zk_transaction.set_data(key, data.encode('ascii'))
    try:
        zk_transaction.check(first_key, new_version)
    except TypeError:
        ansiiprint.echo('Zookeeper key "{}" does not match expected version'.format(first_key), '', 'e')
        return 1
    zk_transaction.commit()
    return 0

