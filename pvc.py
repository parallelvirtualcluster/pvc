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
    zk.start()
    transaction = zk.transaction()
    transaction.create('/domains/%s' % domuuid, "".encode('ascii'))
    transaction.create('/domains/%s/state' % domuuid, "stop".encode('ascii'))
    transaction.create('/domains/%s/hypervisor' % domuuid, socket.gethostname().encode('ascii'))
    transaction.create('/domains/%s/xml' % domuuid, data.encode('ascii'))
    results = transaction.commit()
    zk.stop()
    zk.close()

def migrate_domain(domuuid, target):
    zk = kazoo.client.KazooClient(hosts='127.0.0.1:2181')
    zk.start()
    transaction = zk.transaction()
    transaction.set_data('/domains/%s/state' % domuuid, 'migrate'.encode('ascii'))
    transaction.set_data('/domains/%s/hypervisor' % domuuid, target.encode('ascii'))
    results = transaction.commit()
    zk.stop()
    zk.close()
    

#define_domain('/var/home/joshua/debian9.xml')
migrate_domain('b1dc4e21-544f-47aa-9bb7-8af0bc443b78', 'test1.i.bonilan.net')
#migrate_domain('b1dc4e21-544f-47aa-9bb7-8af0bc443b78', 'test2.i.bonilan.net')
