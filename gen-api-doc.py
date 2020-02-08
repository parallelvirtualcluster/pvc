#!/usr/bin/env python3

# gen-doc.py - Generate a Swagger JSON document for the API
# Part of the Parallel Virtual Cluster (PVC) system

from flask_swagger import swagger
import os
import sys
import json

os.environ['PVC_CONFIG_FILE'] = "./api-daemon/pvc-api.sample.yaml"

sys.path.append('api-daemon')

pvc_api = __import__('pvc-api')

swagger_file = "docs/manuals/swagger.json"

swagger_data = swagger(pvc_api.app)
swagger_data['info']['version'] = "1.0"
swagger_data['info']['title'] = "PVC Client and Provisioner API"
swagger_data['host'] = "pvc.local:7370"

with open(swagger_file, 'w') as fd:
    fd.write(json.dumps(swagger_data, sort_keys=True, indent=4))
