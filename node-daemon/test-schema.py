#!/usr/bin/env python3

# flake8: noqa

import sys
import datetime
from daemon_lib.zkhandler import ZKHandler, ZKSchema

ZKSchema.write()

sys.exit(0)

print(datetime.datetime.now())
zkhandler = ZKHandler({'coordinators': ['hv1.tc', 'hv2.tc', 'hv3.tc']})
zkhandler.connect()
print(datetime.datetime.now())

zkschema = ZKSchema.load_current(zkhandler)

#print(zkschema.path('base.schema.version'))
#print(zkschema.path('node.state.daemon', 'hv1'))
#print(zkschema.path('domain.state', 'test1'))
#print(zkschema.keys('base'))
#print(zkschema.keys('node'))


zkschema.validate(zkhandler)
zkschema.apply(zkhandler)

zkschema_latest = ZKSchema()
#if zkschema < zkschema_latest:
#    print("I'm older")
#elif zkschema == zkschema_latest:
#    print("I'm the same")
#elif zkschema > zkschema_latest:
#    print("I'm newer")

#diff = ZKSchema.key_diff(zkschema, zkschema_latest)
zkschema.migrate(zkhandler, zkschema_latest.version)

#zkschema_earliest = ZKSchema()
#zkschema_earliest.load(0)
#zkschema.rollback(zkhandler, zkschema_earliest.version)
