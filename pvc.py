#!/usr/bin/env python3

import kazoo.client, socket, time
from lxml import objectify

def help():
    print("pvc - Parallel Virtual Cluster command-line utility")

def define_domain(domxmlfile):
    with open(domxmlfile, 'r') as f_domxmlfile:
        data = f_domxmlfile.read()
        f_domxmlfile.close()

    parsed_xml = objectify.fromstring(data)
    domuuid = parsed_xml.uuid
    print('Adding domain %s to database' % domuuid)

    zk = kazoo.client.KazooClient(hosts='127.0.0.1:2181')
    try:
        zk.start()
        transaction = zk.transaction()
        transaction.create('/domains/%s' % domuuid, "".encode('ascii'))
        transaction.create('/domains/%s/state' % domuuid, "stop".encode('ascii'))
        transaction.create('/domains/%s/hypervisor' % domuuid, socket.gethostname().encode('ascii'))
        transaction.create('/domains/%s/xml' % domuuid, data.encode('ascii'))
        results = transaction.commit()
        zk.stop()
        zk.close()
    except:
        print('Failed to connect to local Zookeeper instance')

define_domain('/var/home/joshua/debian9.xml')
