#!/usr/bin/env python3

# Daemon.py - PVC HTTP API daemon
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2022 Joshua M. Boniface <joshua@boniface.me>
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

import flask

from functools import wraps
from flask_restful import Resource, Api, reqparse, abort
from celery import Celery
from kombu import Queue
from lxml.objectify import fromstring as lxml_fromstring
from uuid import uuid4

from daemon_lib.common import getPrimaryNode
from daemon_lib.zkhandler import ZKConnection
from daemon_lib.node import get_list as get_node_list
from daemon_lib.benchmark import list_benchmarks

from pvcapid.Daemon import config, strtobool, API_VERSION

import pvcapid.helper as api_helper
import pvcapid.provisioner as api_provisioner
import pvcapid.ova as api_ova

from flask_sqlalchemy import SQLAlchemy


# Create Flask app and set config values
app = flask.Flask(__name__)

# Set up SQLAlchemy backend
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://{}:{}@{}:{}/{}".format(
    config["api_postgresql_user"],
    config["api_postgresql_password"],
    config["api_postgresql_host"],
    config["api_postgresql_port"],
    config["api_postgresql_dbname"],
)

if config["debug"]:
    app.config["DEBUG"] = True
else:
    app.config["DEBUG"] = False

if config["api_auth_enabled"]:
    app.config["SECRET_KEY"] = config["api_auth_secret_key"]

# Create SQLAlchemy database
db = SQLAlchemy(app)

# Create Flask blueprint
blueprint = flask.Blueprint("api", __name__, url_prefix="/api/v1")

# Create Flask-RESTful definition
api = Api(blueprint)
app.register_blueprint(blueprint)


# Set up Celery queues
@ZKConnection(config)
def get_all_nodes(zkhandler):
    _, all_nodes = get_node_list(zkhandler, None)
    return [n["name"] for n in all_nodes]


@ZKConnection(config)
def get_primary_node(zkhandler):
    return getPrimaryNode(zkhandler)


# Set up Celery task ID generator
# 1. Lets us make our own IDs (first section of UUID)
# 2. Lets us distribute jobs to the required pvcworkerd instances
def run_celery_task(task_name, **kwargs):
    task_id = str(uuid4()).split("-")[0]

    if "run_on" in kwargs and kwargs["run_on"] != "primary":
        run_on = kwargs["run_on"]
    else:
        run_on = get_primary_node()

    print(
        f"Incoming pvcworkerd task: '{task_name}' ({task_id}) assigned to worker {run_on} with args {kwargs}"
    )

    task = celery.send_task(
        task_name,
        task_id=task_id,
        kwargs=kwargs,
        queue=run_on,
    )

    return task


# Create celery definition
celery_task_uri = "redis://{}:{}{}".format(
    config["keydb_host"], config["keydb_port"], config["keydb_path"]
)
celery = Celery(
    app.name,
    broker=celery_task_uri,
    result_backend=celery_task_uri,
    result_extended=True,
)
app.config["broker_url"] = celery_task_uri
app.config["result_backend"] = celery_task_uri
celery.conf.update(app.config)


def celery_startup():
    """
    Runs when the API daemon starts, but not the Celery workers or the API doc generator
    """
    app.config["task_queues"] = tuple(
        [Queue(h, routing_key=f"{h}.#") for h in get_all_nodes()]
    )
    celery.conf.update(app.config)


#
# Custom decorators
#


# Request parser decorator
class RequestParser(object):
    def __init__(self, reqargs):
        self.reqargs = reqargs

    def __call__(self, function):
        if not callable(function):
            return

        @wraps(function)
        def wrapped_function(*args, **kwargs):
            parser = reqparse.RequestParser()
            # Parse and add each argument
            for reqarg in self.reqargs:
                location = reqarg.get("location", None)
                if location is None:
                    location = ["args", "form"]
                parser.add_argument(
                    reqarg.get("name", None),
                    required=reqarg.get("required", False),
                    action=reqarg.get("action", None),
                    choices=reqarg.get("choices", ()),
                    help=reqarg.get("helptext", None),
                    location=location,
                )
            reqargs = parser.parse_args()
            kwargs["reqargs"] = reqargs
            return function(*args, **kwargs)

        return wrapped_function


# Authentication decorator function
def Authenticator(function):
    @wraps(function)
    def authenticate(*args, **kwargs):
        # No authentication required
        if not config["api_auth_enabled"]:
            return function(*args, **kwargs)
        # Session-based authentication
        if "token" in flask.session:
            return function(*args, **kwargs)
        # Key header-based authentication
        if "X-Api-Key" in flask.request.headers:
            if any(
                token
                for token in config["api_auth_tokens"]
                if flask.request.headers.get("X-Api-Key") == token.get("token")
            ):
                return function(*args, **kwargs)
            else:
                return {"message": "X-Api-Key Authentication failed."}, 401
        # All authentications failed
        return {"message": "X-Api-Key Authentication required."}, 401

    return authenticate


##########################################################
# API Root/Authentication
##########################################################


# /
class API_Root(Resource):
    def get(self):
        """
        Return the PVC API version string
        ---
        tags:
          - root
        responses:
          200:
            description: OK
            schema:
              type: object
              id: API-Version
              properties:
                message:
                  type: string
                  description: A text message
                  example: "PVC API version 1.0"
        """
        return {"message": "PVC API version {}".format(API_VERSION)}


api.add_resource(API_Root, "/")


# /doc - NOTE: Until flask_swagger is packaged for Debian this must be disabled
# class API_Doc(Resource):
#     def get(self):
#         """
#         Provide the Swagger API documentation
#         ---
#         tags:
#           - root
#         responses:
#           200:
#             description: OK
#         """
#         swagger_data = swagger(pvc_api.app)
#         swagger_data['info']['version'] = API_VERSION
#         swagger_data['info']['title'] = "PVC Client and Provisioner API"
#         swagger_data['host'] = "{}:{}".format(config['listen_address'], config['listen_port'])
#         return swagger_data
#
#
# api.add_resource(API_Doc, '/doc')


# /login
class API_Login(Resource):
    def post(self):
        """
        Log in to the PVC API with an authentication key
        ---
        tags:
          - root
        parameters:
          - in: query
            name: token
            type: string
            required: true
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
              properties:
                message:
                  type: string
                  description: A text message
          302:
            description: Authentication disabled
          401:
            description: Unauthorized
            schema:
              type: object
              id: Message
        """
        if not config["api_auth_enabled"]:
            return flask.redirect(Api.url_for(api, API_Root))

        if any(
            token
            for token in config["api_auth_tokens"]
            if flask.request.values["token"] in token["token"]
        ):
            flask.session["token"] = flask.request.form["token"]
            return {"message": "Authentication successful"}, 200
        else:
            {"message": "Authentication failed"}, 401


api.add_resource(API_Login, "/login")


# /logout
class API_Logout(Resource):
    def post(self):
        """
        Log out of an existing PVC API session
        ---
        tags:
          - root
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          302:
            description: Authentication disabled
        """
        if not config["api_auth_enabled"]:
            return flask.redirect(Api.url_for(api, API_Root))

        flask.session.pop("token", None)
        return {"message": "Deauthentication successful"}, 200


api.add_resource(API_Logout, "/logout")


# /initialize
class API_Initialize(Resource):
    @RequestParser(
        [
            {"name": "overwrite", "required": False},
            {
                "name": "yes-i-really-mean-it",
                "required": True,
                "helptext": "Initialization is destructive; please confirm with the argument 'yes-i-really-mean-it'.",
            },
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Initialize a new PVC cluster

        If the 'overwrite' option is not True, the cluster will return 400 if the `/config/primary_node` key is found. If 'overwrite' is True, the existing cluster
        data will be erased and new, empty data written in its place.

        All node daemons should be stopped before running this command, and the API daemon started manually to avoid undefined behavior.
        ---
        tags:
          - root
        parameters:
          - in: query
            name: overwrite
            type: bool
            required: false
            description: A flag to enable or disable (default) overwriting existing data
          - in: query
            name: yes-i-really-mean-it
            type: string
            required: true
            description: A confirmation string to ensure that the API consumer really means it
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
              properties:
                message:
                  type: string
                  description: A text message
          400:
            description: Bad request
        """
        if reqargs.get("overwrite", "False") == "True":
            overwrite_flag = True
        else:
            overwrite_flag = False

        return api_helper.initialize_cluster(overwrite=overwrite_flag)


api.add_resource(API_Initialize, "/initialize")


# /backup
class API_Backup(Resource):
    @Authenticator
    def get(self):
        """
        Back up the Zookeeper data of a cluster in JSON format
        ---
        tags:
          - root
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Cluster Data
          400:
            description: Bad request
        """
        return api_helper.backup_cluster()


api.add_resource(API_Backup, "/backup")


# /restore
class API_Restore(Resource):
    @RequestParser(
        [
            {
                "name": "yes-i-really-mean-it",
                "required": True,
                "helptext": "Restore is destructive; please confirm with the argument 'yes-i-really-mean-it'.",
            },
            {
                "name": "cluster_data",
                "required": True,
                "helptext": "A cluster JSON backup must be provided.",
            },
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Restore a backup over the cluster; destroys the existing data
        ---
        tags:
          - root
        parameters:
          - in: query
            name: yes-i-really-mean-it
            type: string
            required: true
            description: A confirmation string to ensure that the API consumer really means it
          - in: query
            name: cluster_data
            type: string
            required: true
            description: The raw JSON cluster backup data
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
          500:
            description: Restore error or code failure
            schema:
              type: object
              id: Message
        """
        try:
            cluster_data = reqargs.get("cluster_data")
        except Exception as e:
            return {"message": "Failed to load JSON backup: {}.".format(e)}, 400

        return api_helper.restore_cluster(cluster_data)


api.add_resource(API_Restore, "/restore")


# /status
class API_Status(Resource):
    @Authenticator
    def get(self):
        """
        Return the current PVC cluster status
        ---
        tags:
          - root
        responses:
          200:
            description: OK
            schema:
              type: object
              id: ClusterStatus
              properties:
                cluster_health:
                  type: object
                  properties:
                    health:
                      type: integer
                      description: The overall health (%) of the cluster
                      example: 100
                    messages:
                      type: array
                      description: A list of health event strings
                      items:
                        type: string
                        example: "hv1: plugin 'nics': bond0 DEGRADED with 1 active slaves, bond0 OK at 10000 Mbps"
                node_health:
                  type: object
                  properties:
                    hvX:
                      type: object
                      description: A node entry for per-node health details, one per node in the cluster
                      properties:
                        health:
                          type: integer
                          description: The health (%) of the node
                          example: 100
                        messages:
                          type: array
                          description: A list of health event strings
                          items:
                            type: string
                            example: "'nics': bond0 DEGRADED with 1 active slaves, bond0 OK at 10000 Mbps"
                maintenance:
                  type: string
                  description: Whether the cluster is in maintenance mode or not (string boolean)
                  example: true
                primary_node:
                  type: string
                  description: The current primary coordinator node
                  example: pvchv1
                pvc_version:
                  type: string
                  description: The PVC version of the current primary coordinator node
                  example: 0.9.61
                upstream_ip:
                  type: string
                  description: The cluster upstream IP address in CIDR format
                  example: 10.0.0.254/24
                nodes:
                  type: object
                  properties:
                    total:
                      type: integer
                      description: The total number of nodes in the cluster
                      example: 3
                    state-combination:
                      type: integer
                      description: The total number of nodes in {state-combination} state, where {state-combination} is the node daemon and domain states in CSV format, e.g. "run,ready", "stop,flushed", etc.
                vms:
                  type: object
                  properties:
                    total:
                      type: integer
                      description: The total number of VMs in the cluster
                      example: 6
                    state:
                      type: integer
                      description: The total number of VMs in {state} state, e.g. "start", "stop", etc.
                networks:
                  type: integer
                  description: The total number of networks in the cluster
                osds:
                  type: object
                  properties:
                    total:
                      type: integer
                      description: The total number of OSDs in the storage cluster
                      example: 3
                    state-combination:
                      type: integer
                      description: The total number of OSDs in {state-combination} state, where {state-combination} is the OSD up and in states in CSV format, e.g. "up,in", "down,out", etc.
                pools:
                  type: integer
                  description: The total number of pools in the storage cluster
                volumes:
                  type: integer
                  description: The total number of volumes in the storage cluster
                snapshots:
                  type: integer
                  description: The total number of snapshots in the storage cluster
          400:
            description: Bad request
        """
        return api_helper.cluster_status()

    @RequestParser(
        [
            {
                "name": "state",
                "choices": ("true", "false"),
                "required": True,
                "helptext": "A valid state must be specified.",
            }
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Set the cluster maintenance mode
        ---
        tags:
          - node
        parameters:
          - in: query
            name: state
            type: boolean
            required: true
            description: The cluster maintenance state
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_helper.cluster_maintenance(reqargs.get("state", "false"))


api.add_resource(API_Status, "/status")


# /metrics
class API_Metrics(Resource):
    def get(self):
        """
        Return the current PVC cluster status in Prometheus-compatible metrics format and
        the Ceph cluster metrics as one document.

        Endpoint is unauthenticated to allow metrics exfiltration without having to deal
        with the Prometheus compatibility later.
        ---
        tags:
          - root
        responses:
          200:
            description: OK
          400:
            description: Bad request
        """
        cluster_output, cluster_retcode = api_helper.cluster_metrics()
        ceph_output, ceph_retcode = api_helper.ceph_metrics()

        if cluster_retcode != 200 or ceph_retcode != 200:
            output = "Error: Failed to obtain data"
            retcode = 400
        else:
            output = cluster_output + ceph_output
            retcode = 200

        response = flask.make_response(output, retcode)
        response.mimetype = "text/plain"
        return response


api.add_resource(API_Metrics, "/metrics")


# /metrics/pvc
class API_Metrics_PVC(Resource):
    def get(self):
        """
        Return the current PVC cluster status in Prometheus-compatible metrics format

        Endpoint is unauthenticated to allow metrics exfiltration without having to deal
        with the Prometheus compatibility later.
        ---
        tags:
          - root
        responses:
          200:
            description: OK
          400:
            description: Bad request
        """
        cluster_output, cluster_retcode = api_helper.cluster_metrics()

        if cluster_retcode != 200:
            output = "Error: Failed to obtain data"
            retcode = 400
        else:
            output = cluster_output
            retcode = 200

        response = flask.make_response(output, retcode)
        response.mimetype = "text/plain"
        return response


api.add_resource(API_Metrics_PVC, "/metrics/pvc")


# /metrics/ceph
class API_Metrics_Ceph(Resource):
    def get(self):
        """
        Return the current PVC Ceph Prometheus metrics

        Proxies a metrics request to the current active MGR, since this is dynamic
        and can't be controlled by PVC easily.
        ---
        tags:
          - root
        responses:
          200:
            description: OK
          400:
            description: Bad request
        """
        ceph_output, ceph_retcode = api_helper.ceph_metrics()

        if ceph_retcode != 200:
            output = "Error: Failed to obtain data"
            retcode = 400
        else:
            output = ceph_output
            retcode = 200

        response = flask.make_response(output, retcode)
        response.mimetype = "text/plain"
        return response


api.add_resource(API_Metrics_Ceph, "/metrics/ceph")


# /faults
class API_Faults(Resource):
    @RequestParser(
        [
            {
                "name": "sort_key",
                "choices": (
                    "first_reported",
                    "last_reported",
                    "acknowledged_at",
                    "status",
                    "health_delta",
                    "message",
                ),
                "helptext": "A valid sort key must be specified",
                "required": False,
            },
        ]
    )
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of cluster faults
        ---
        tags:
          - faults
        parameters:
          - in: query
            name: sort_key
            type: string
            required: false
            description: The fault object key to sort results by
            enum:
              - first_reported
              - last_reported
              - acknowledged_at
              - status
              - health_delta
              - message
        responses:
          200:
            description: OK
            schema:
              type: array
              items:
                type: object
                id: fault
                properties:
                  id:
                    type: string
                    description: The ID of the fault
                    example: "10ae144b78b4cc5fdf09e2ebbac51235"
                  first_reported:
                    type: date
                    description: The first time the fault was reported
                    example: "2023-12-01 16:47:59.849742"
                  last_reported:
                    type: date
                    description: The last time the fault was reported
                    example: "2023-12-01 17:39:45.188398"
                  acknowledged_at:
                    type: date
                    description: The time the fault was acknowledged, or empty if not acknowledged
                    example: "2023-12-01 17:50:00.000000"
                  status:
                    type: string
                    description: The current state of the fault, either "new" or "ack" (acknowledged)
                    example: "new"
                  health_delta:
                    type: integer
                    description: The health delta (amount it reduces cluster health from 100%) of the fault
                    example: 25
                  message:
                    type: string
                    description: The textual description of the fault
                    example: "Node hv1 was at 40% (psur@-10%, psql@-50%) <= 50% health"
        """
        return api_helper.fault_list(sort_key=reqargs.get("sort_key", "last_reported"))

    @Authenticator
    def put(self):
        """
        Acknowledge all cluster faults
        ---
        tags:
          - faults
        responses:
          200:
            description: OK
            schema:
              type: object
              properties:
                message:
                  type: string
                  description: A text message
        """
        return api_helper.fault_acknowledge_all()

    @Authenticator
    def delete(self):
        """
        Delete all cluster faults
        ---
        tags:
          - faults
        responses:
          200:
            description: OK
            schema:
              type: object
              properties:
                message:
                  type: string
                  description: A text message
        """
        return api_helper.fault_delete_all()


api.add_resource(API_Faults, "/faults")


# /faults/<fault_id>
class API_Faults_Element(Resource):
    @Authenticator
    def get(self, fault_id):
        """
        Return a single cluster fault
        ---
        tags:
          - faults
        responses:
          200:
            description: OK
            schema:
              type: array
              items:
                type: object
                id: fault
                $ref: '#/definitions/fault'
        """
        return api_helper.fault_list(limit=fault_id)

    @Authenticator
    def put(self, fault_id):
        """
        Acknowledge a cluster fault
        ---
        tags:
          - faults
        responses:
          200:
            description: OK
            schema:
              type: object
              properties:
                message:
                  type: string
                  description: A text message
        """
        return api_helper.fault_acknowledge(fault_id)

    @Authenticator
    def delete(self, fault_id):
        """
        Delete a cluster fault
        ---
        tags:
          - faults
        responses:
          200:
            description: OK
            schema:
              type: object
              properties:
                message:
                  type: string
                  description: A text message
        """
        return api_helper.fault_delete(fault_id)


api.add_resource(API_Faults_Element, "/faults/<fault_id>")


# /tasks
class API_Tasks(Resource):
    @Authenticator
    def get(self):
        """
        Return a list of active Celery worker tasks
        ---
        tags:
          - root
        responses:
          200:
            description: OK
            schema:
              type: object
              properties:
                active:
                  type: object
                  description: Celery app.control.inspect active tasks
                reserved:
                  type: object
                  description: Celery app.control.inspect reserved tasks
                scheduled:
                  type: object
                  description: Celery app.control.inspect scheduled tasks
        """
        queue = celery.control.inspect()
        response = {
            "scheduled": queue.scheduled(),
            "active": queue.active(),
            "reserved": queue.reserved(),
        }
        return response


api.add_resource(API_Tasks, "/tasks")


# /tasks/<task_id>
class API_Tasks_Element(Resource):
    @Authenticator
    def get(self, task_id):
        """
        View status of a Celery worker task {task_id}
        ---
        tags:
          - provisioner
        responses:
          200:
            description: OK
            schema:
              type: object
              properties:
                total:
                  type: integer
                  description: Total number of steps
                current:
                  type: integer
                  description: Current steps completed
                state:
                  type: string
                  description: Current job state
                status:
                  type: string
                  description: Status details about job
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        task = celery.AsyncResult(task_id)
        if task.state == "PENDING":
            response = {
                "state": task.state,
                "current": 0,
                "total": 1,
                "status": "Pending job start",
            }
        elif task.state == "FAILURE":
            response = {
                "state": task.state,
                "current": 1,
                "total": 1,
                "status": str(task.info),
            }
        else:
            response = {
                "state": task.state,
                "current": task.info.get("current", 0),
                "total": task.info.get("total", 1),
                "status": task.info.get("status", ""),
            }
            if "result" in task.info:
                response["result"] = task.info["result"]
        return response


api.add_resource(API_Tasks_Element, "/tasks/<task_id>")


##########################################################
# Client API - Node
##########################################################


# /node
class API_Node_Root(Resource):
    @RequestParser(
        [
            {"name": "limit"},
            {"name": "daemon_state"},
            {"name": "coordinator_state"},
            {"name": "domain_state"},
        ]
    )
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of nodes in the cluster
        ---
        tags:
          - node
        definitions:
          - schema:
              type: object
              id: node
              properties:
                name:
                  type: string
                  description: The name of the node
                daemon_state:
                  type: string
                  description: The current daemon state
                coordinator_state:
                  type: string
                  description: The current coordinator state
                domain_state:
                  type: string
                  description: The current domain (VM) state
                pvc_version:
                  type: string
                  description: The current running PVC node daemon version
                cpu_count:
                  type: integer
                  description: The number of available CPU cores
                kernel:
                  type: string
                  desription: The running kernel version from uname
                os:
                  type: string
                  description: The current operating system type
                arch:
                  type: string
                  description: The architecture of the CPU
                health:
                  type: integer
                  description: The overall health (%) of the node
                  example: 100
                health_plugins:
                  type: array
                  description: A list of health plugin names currently loaded on the node
                  items:
                    type: string
                    example: "nics"
                health_details:
                  type: array
                  description: A list of health plugin results
                  items:
                    type: object
                    properties:
                      name:
                        type: string
                        description: The name of the health plugin
                        example: nics
                      last_run:
                        type: integer
                        description: The UNIX timestamp (s) of the last plugin run
                        example: 1676786078
                      health_delta:
                        type: integer
                        description: The health delta (negatively applied to the health percentage) of the plugin's current state
                        example: 10
                      message:
                        type: string
                        description: The output message of the plugin
                        example: "bond0 DEGRADED with 1 active slaves, bond0 OK at 10000 Mbps"
                load:
                  type: number
                  format: float
                  description: The current 5-minute CPU load
                domains_count:
                  type: integer
                  description: The number of running domains (VMs)
                running_domains:
                  type: string
                  description: The list of running domains (VMs) by UUID
                vcpu:
                  type: object
                  properties:
                    total:
                      type: integer
                      description: The total number of real CPU cores available
                    allocated:
                      type: integer
                      description: The total number of allocated vCPU cores
                memory:
                  type: object
                  properties:
                    total:
                      type: integer
                      description: The total amount of node RAM in MB
                    used:
                      type: integer
                      description: The total used RAM on the node in MB
                    free:
                      type: integer
                      description: The total free RAM on the node in MB
                    allocated:
                      type: integer
                      description: The total amount of RAM allocated to running domains in MB
                    provisioned:
                      type: integer
                      description: The total amount of RAM provisioned to all domains (regardless of state) on this node in MB
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: A search limit in the name, tags, or an exact UUID; fuzzy by default, use ^/$ to force exact matches
          - in: query
            name: daemon_state
            type: string
            required: false
            description: Limit results to nodes in the specified daemon state
          - in: query
            name: coordinator_state
            type: string
            required: false
            description: Limit results to nodes in the specified coordinator state
          - in: query
            name: domain_state
            type: string
            required: false
            description: Limit results to nodes in the specified domain state
        responses:
          200:
            description: OK
            schema:
              type: array
              items:
                $ref: '#/definitions/node'
        """
        return api_helper.node_list(
            limit=reqargs.get("limit", None),
            daemon_state=reqargs.get("daemon_state", None),
            coordinator_state=reqargs.get("coordinator_state", None),
            domain_state=reqargs.get("domain_state", None),
        )


api.add_resource(API_Node_Root, "/node")


# /node/<node>
class API_Node_Element(Resource):
    @Authenticator
    def get(self, node):
        """
        Return information about {node}
        ---
        tags:
          - node
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/node'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.node_list(node, is_fuzzy=False)


api.add_resource(API_Node_Element, "/node/<node>")


# /node/<node>/daemon-state
class API_Node_DaemonState(Resource):
    @Authenticator
    def get(self, node):
        """
        Return the daemon state of {node}
        ---
        tags:
          - node
        responses:
          200:
            description: OK
            schema:
              type: object
              id: NodeDaemonState
              properties:
                name:
                  type: string
                  description: The name of the node
                daemon_state:
                  type: string
                  description: The current daemon state
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.node_daemon_state(node)


api.add_resource(API_Node_DaemonState, "/node/<node>/daemon-state")


# /node/<node>/coordinator-state
class API_Node_CoordinatorState(Resource):
    @Authenticator
    def get(self, node):
        """
        Return the coordinator state of {node}
        ---
        tags:
          - node
        responses:
          200:
            description: OK
            schema:
              type: object
              id: NodeCoordinatorState
              properties:
                name:
                  type: string
                  description: The name of the node
                coordinator_state:
                  type: string
                  description: The current coordinator state
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.node_coordinator_state(node)

    @RequestParser(
        [
            {
                "name": "state",
                "choices": ("primary", "secondary"),
                "helptext": "A valid state must be specified",
                "required": True,
            }
        ]
    )
    @Authenticator
    def post(self, node, reqargs):
        """
        Set the coordinator state of {node}
        ---
        tags:
          - node
        parameters:
          - in: query
            name: action
            type: string
            required: true
            description: The new coordinator state of the node
            enum:
              - primary
              - secondary
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        if reqargs["state"] == "primary":
            return api_helper.node_primary(node)
        if reqargs["state"] == "secondary":
            return api_helper.node_secondary(node)
        abort(400)


api.add_resource(API_Node_CoordinatorState, "/node/<node>/coordinator-state")


# /node/<node>/domain-state
class API_Node_DomainState(Resource):
    @Authenticator
    def get(self, node):
        """
        Return the domain state of {node}
        ---
        tags:
          - node
        responses:
          200:
            description: OK
            schema:
              type: object
              id: NodeDomainState
              properties:
                name:
                  type: string
                  description: The name of the node
                domain_state:
                  type: string
                  description: The current domain state
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.node_domain_state(node)

    @RequestParser(
        [
            {
                "name": "state",
                "choices": ("ready", "flush"),
                "helptext": "A valid state must be specified",
                "required": True,
            },
            {"name": "wait"},
        ]
    )
    @Authenticator
    def post(self, node, reqargs):
        """
        Set the domain state of {node}
        ---
        tags:
          - node
        parameters:
          - in: query
            name: action
            type: string
            required: true
            description: The new domain state of the node
            enum:
              - flush
              - ready
          - in: query
            name: wait
            type: boolean
            description: Whether to block waiting for the full flush/ready state
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        if reqargs["state"] == "flush":
            return api_helper.node_flush(
                node, bool(strtobool(reqargs.get("wait", "false")))
            )
        if reqargs["state"] == "ready":
            return api_helper.node_ready(
                node, bool(strtobool(reqargs.get("wait", "false")))
            )
        abort(400)


api.add_resource(API_Node_DomainState, "/node/<node>/domain-state")


# /node/<node</log
class API_Node_Log(Resource):
    @RequestParser([{"name": "lines"}])
    @Authenticator
    def get(self, node, reqargs):
        """
        Return the recent logs of {node}
        ---
        tags:
          - node
        parameters:
          - in: query
            name: lines
            type: integer
            required: false
            description: The number of lines to retrieve
        responses:
          200:
            description: OK
            schema:
              type: object
              id: NodeLog
              properties:
                name:
                  type: string
                  description: The name of the Node
                data:
                  type: string
                  description: The recent log text
          404:
            description: Node not found
            schema:
              type: object
              id: Message
        """
        return api_helper.node_log(node, reqargs.get("lines", None))


api.add_resource(API_Node_Log, "/node/<node>/log")


##########################################################
# Client API - VM
##########################################################


# /vm
class API_VM_Root(Resource):
    @RequestParser(
        [
            {"name": "limit"},
            {"name": "node"},
            {"name": "state"},
            {"name": "tag"},
            {"name": "negate"},
        ]
    )
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of VMs in the cluster
        ---
        tags:
          - vm
        definitions:
          - schema:
              type: object
              id: vm
              properties:
                name:
                  type: string
                  description: The name of the VM
                uuid:
                  type: string
                  description: The UUID of the VM
                state:
                  type: string
                  description: The current state of the VM
                node:
                  type: string
                  description: The node the VM is currently assigned to
                last_node:
                  type: string
                  description: The last node the VM was assigned to before migrating
                migrated:
                  type: string
                  description: Whether the VM has been migrated, either "no" or "from <last_node>"
                failed_reason:
                  type: string
                  description: Information about why the VM failed to start
                node_limit:
                  type: array
                  description: The node(s) the VM is permitted to be assigned to
                  items:
                    type: string
                node_selector:
                  type: string
                  description: The selector used to determine candidate nodes during migration; see 'target_selector' in the node daemon configuration reference
                node_autostart:
                  type: boolean
                  description: Whether to autostart the VM when its node returns to ready domain state
                migration_method:
                  type: string
                  description: The preferred migration method (live, shutdown, none)
                tags:
                  type: array
                  description: The tag(s) of the VM
                  items:
                    type: object
                    id: VMTag
                    properties:
                      name:
                        type: string
                        description: The name of the tag
                      type:
                        type: string
                        description: The type of the tag (user, system)
                      protected:
                        type: boolean
                        description: Whether the tag is protected or not
                description:
                  type: string
                  description: The description of the VM
                profile:
                  type: string
                  description: The provisioner profile used to create the VM
                memory:
                  type: integer
                  description: The assigned RAM of the VM in MB
                memory_stats:
                  type: object
                  properties:
                    actual:
                      type: integer
                      description: The total active memory of the VM in kB
                    swap_in:
                      type: integer
                      description: The amount of swapped in data in kB
                    swap_out:
                      type: integer
                      description: The amount of swapped out data in kB
                    major_fault:
                      type: integer
                      description: The number of major page faults
                    minor_fault:
                      type: integer
                      description: The number of minor page faults
                    unused:
                      type: integer
                      description: The amount of memory left completely unused by the system in kB
                    available:
                      type: integer
                      description: The total amount of usable memory as seen by the domain in kB
                    usable:
                      type: integer
                      description: How much the balloon can be inflated without pushing the guest system to swap in kB
                    last_update:
                      type: integer
                      description: Timestamp of the last update of statistics, in seconds
                    rss:
                      type: integer
                      description: The Resident Set Size of the process running the domain in kB
                vcpu:
                  type: integer
                  description: The assigned vCPUs of the VM
                vcpu_topology:
                  type: string
                  description: The topology of the assigned vCPUs in Sockets/Cores/Threads format
                vcpu_stats:
                  type: object
                  properties:
                    cpu_time:
                      type: integer
                      description: The active CPU time for all vCPUs
                    user_time:
                      type: integer
                      description: vCPU user time
                    system_time:
                      type: integer
                      description: vCPU system time
                type:
                  type: string
                  description: The type of the VM
                arch:
                  type: string
                  description: The architecture of the VM
                machine:
                  type: string
                  description: The QEMU machine type of the VM
                console:
                  type: string
                  descritpion: The serial console type of the VM
                vnc:
                  type: object
                  properties:
                    listen:
                      type: string
                      description: The active VNC listen address or 'None'
                    port:
                      type: string
                      description: The active VNC port or 'None'
                emulator:
                  type: string
                  description: The binary emulator of the VM
                features:
                  type: array
                  description: The available features of the VM
                  items:
                    type: string
                networks:
                  type: array
                  description: The PVC networks attached to the VM
                  items:
                    type: object
                    properties:
                      type:
                        type: string
                        description: The PVC network type
                      mac:
                        type: string
                        description: The MAC address of the VM network interface
                      source:
                        type: string
                        description: The parent network bridge on the node
                      vni:
                        type: integer
                        description: The VNI (PVC network) of the network bridge
                      model:
                        type: string
                        description: The virtual network device model
                      rd_bytes:
                        type: integer
                        description: The number of read bytes on the interface
                      rd_packets:
                        type: integer
                        description: The number of read packets on the interface
                      rd_errors:
                        type: integer
                        description: The number of read errors on the interface
                      rd_drops:
                        type: integer
                        description: The number of read drops on the interface
                      wr_bytes:
                        type: integer
                        description: The number of write bytes on the interface
                      wr_packets:
                        type: integer
                        description: The number of write packets on the interface
                      wr_errors:
                        type: integer
                        description: The number of write errors on the interface
                      wr_drops:
                        type: integer
                        description: The number of write drops on the interface
                disks:
                  type: array
                  description: The PVC storage volumes attached to the VM
                  items:
                    type: object
                    properties:
                      type:
                        type: string
                        description: The type of volume
                      name:
                        type: string
                        description: The full name of the volume in "pool/volume" format
                      dev:
                        type: string
                        description: The device ID of the volume in the VM
                      bus:
                        type: string
                        description: The virtual bus of the volume in the VM
                      rd_req:
                        type: integer
                        description: The number of read requests from the volume
                      rd_bytes:
                        type: integer
                        description: The number of read bytes from the volume
                      wr_req:
                        type: integer
                        description: The number of write requests to the volume
                      wr_bytes:
                        type: integer
                        description: The number of write bytes to the volume
                controllers:
                  type: array
                  description: The device controllers attached to the VM
                  items:
                    type: object
                    properties:
                      type:
                        type: string
                        description: The type of the controller
                      model:
                        type: string
                        description: The model of the controller
                xml:
                  type: string
                  description: The raw Libvirt XML definition of the VM
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: A search limit in the name, tags, or an exact UUID; fuzzy by default, use ^/$ to force exact matches
          - in: query
            name: node
            type: string
            required: false
            description: Limit list to VMs assigned to this node
          - in: query
            name: state
            type: string
            required: false
            description: Limit list to VMs in this state
          - in: query
            name: tag
            type: string
            required: false
            description: Limit list to VMs with this tag
          - in: query
            name: negate
            type: boolean
            required: false
            description: Negate the specified node, state, or tag limit(s)
        responses:
          200:
            description: OK
            schema:
              type: array
              items:
                $ref: '#/definitions/vm'
        """
        return api_helper.vm_list(
            node=reqargs.get("node", None),
            state=reqargs.get("state", None),
            tag=reqargs.get("tag", None),
            limit=reqargs.get("limit", None),
            negate=bool(strtobool(reqargs.get("negate", "False"))),
        )

    @RequestParser(
        [
            {"name": "limit"},
            {"name": "node"},
            {
                "name": "selector",
                "choices": ("mem", "memprov", "vcpus", "load", "vms", "none"),
                "helptext": "A valid selector must be specified",
            },
            {"name": "autostart"},
            {
                "name": "migration_method",
                "choices": ("live", "shutdown", "none"),
                "helptext": "A valid migration_method must be specified",
            },
            {"name": "user_tags", "action": "append"},
            {"name": "protected_tags", "action": "append"},
            {
                "name": "xml",
                "required": True,
                "helptext": "A Libvirt XML document must be specified",
            },
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Create a new virtual machine
        ---
        tags:
          - vm
        parameters:
          - in: query
            name: xml
            type: string
            required: true
            description: The raw Libvirt XML definition of the VM
          - in: query
            name: node
            type: string
            required: false
            description: The node the VM should be assigned to; autoselect if empty or invalid
          - in: query
            name: limit
            type: string
            required: false
            description: The CSV list of node(s) the VM is permitted to be assigned to; should include "node" and any other valid target nodes; this limit will be used for autoselection on definition and migration
          - in: query
            name: selector
            type: string
            required: false
            description: The selector used to determine candidate nodes during migration; see 'target_selector' in the node daemon configuration reference
            default: none
            enum:
              - mem
              - memprov
              - vcpus
              - load
              - vms
              - none (cluster default)
          - in: query
            name: autostart
            type: boolean
            required: false
            description: Whether to autostart the VM when its node returns to ready domain state
          - in: query
            name: migration_method
            type: string
            required: false
            description: The preferred migration method (live, shutdown, none)
            default: none
            enum:
              - live
              - shutdown
              - none
          - in: query
            name: user_tags
            type: array
            required: false
            description: The user tag(s) of the VM
            items:
              type: string
          - in: query
            name: protected_tags
            type: array
            required: false
            description: The protected user tag(s) of the VM
            items:
              type: string
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        user_tags = reqargs.get("user_tags", None)
        if user_tags is None:
            user_tags = []
        protected_tags = reqargs.get("protected_tags", None)
        if protected_tags is None:
            protected_tags = []

        return api_helper.vm_define(
            reqargs.get("xml"),
            reqargs.get("node", None),
            reqargs.get("limit", None),
            reqargs.get("selector", "none"),
            bool(strtobool(reqargs.get("autostart", "false"))),
            reqargs.get("migration_method", "none"),
            user_tags,
            protected_tags,
        )


api.add_resource(API_VM_Root, "/vm")


# /vm/<vm>
class API_VM_Element(Resource):
    @Authenticator
    def get(self, vm):
        """
        Return information about {vm}
        ---
        tags:
          - vm
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/vm'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.vm_list(
            node=None, state=None, tag=None, limit=vm, is_fuzzy=False, negate=False
        )

    @RequestParser(
        [
            {"name": "limit"},
            {"name": "node"},
            {
                "name": "selector",
                "choices": ("mem", "memprov", "vcpus", "load", "vms", "none"),
                "helptext": "A valid selector must be specified",
            },
            {"name": "autostart"},
            {
                "name": "migration_method",
                "choices": ("live", "shutdown", "none"),
                "helptext": "A valid migration_method must be specified",
            },
            {"name": "user_tags", "action": "append"},
            {"name": "protected_tags", "action": "append"},
            {
                "name": "xml",
                "required": True,
                "helptext": "A Libvirt XML document must be specified",
            },
        ]
    )
    @Authenticator
    def post(self, vm, reqargs):
        """
        Create new {vm}
        Note: The name {vm} is ignored; only the "name" value from the Libvirt XML is used
        This endpoint is identical to "POST /api/v1/vm"
        ---
        tags:
          - vm
        parameters:
          - in: query
            name: xml
            type: string
            required: true
            description: The raw Libvirt XML definition of the VM
          - in: query
            name: node
            type: string
            required: false
            description: The node the VM should be assigned to; autoselect if empty or invalid
          - in: query
            name: limit
            type: string
            required: false
            description: The CSV list of node(s) the VM is permitted to be assigned to; should include "node" and any other valid target nodes; this limit will be used for autoselection on definition and migration
          - in: query
            name: selector
            type: string
            required: false
            description: The selector used to determine candidate nodes during migration; see 'target_selector' in the node daemon configuration reference
            default: none
            enum:
              - mem
              - memprov
              - vcpus
              - load
              - vms
              - none (cluster default)
          - in: query
            name: autostart
            type: boolean
            required: false
            description: Whether to autostart the VM when its node returns to ready domain state
          - in: query
            name: migration_method
            type: string
            required: false
            description: The preferred migration method (live, shutdown, none)
            default: none
            enum:
              - live
              - shutdown
              - none
          - in: query
            name: user_tags
            type: array
            required: false
            description: The user tag(s) of the VM
            items:
              type: string
          - in: query
            name: protected_tags
            type: array
            required: false
            description: The protected user tag(s) of the VM
            items:
              type: string
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        user_tags = reqargs.get("user_tags", None)
        if user_tags is None:
            user_tags = []
        protected_tags = reqargs.get("protected_tags", None)
        if protected_tags is None:
            protected_tags = []

        return api_helper.vm_define(
            reqargs.get("xml"),
            reqargs.get("node", None),
            reqargs.get("limit", None),
            reqargs.get("selector", "none"),
            bool(strtobool(reqargs.get("autostart", "false"))),
            reqargs.get("migration_method", "none"),
            user_tags,
            protected_tags,
        )

    @RequestParser(
        [
            {"name": "restart"},
            {
                "name": "xml",
                "required": True,
                "helptext": "A Libvirt XML document must be specified",
            },
        ]
    )
    @Authenticator
    def put(self, vm, reqargs):
        """
        Update the Libvirt XML of {vm}
        ---
        tags:
          - vm
        parameters:
          - in: query
            name: xml
            type: string
            required: true
            description: The raw Libvirt XML definition of the VM
          - in: query
            name: restart
            type: boolean
            description: Whether to automatically restart the VM to apply the new configuration
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.vm_modify(
            vm,
            bool(strtobool(reqargs.get("restart", "false"))),
            reqargs.get("xml", None),
        )

    @RequestParser(
        [
            {"name": "delete_disks"},
        ]
    )
    @Authenticator
    def delete(self, vm, reqargs):
        """
        Remove {vm}
        ---
        tags:
          - vm
        parameters:
          - in: query
            name: delete_disks
            type: boolean
            default: false
            description: Whether to automatically delete all VM disk volumes
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
          404:
            description: VM not found
            schema:
              type: object
              id: Message
        """
        if bool(strtobool(reqargs.get("delete_disks", "false"))):
            return api_helper.vm_remove(vm)
        else:
            return api_helper.vm_undefine(vm)


api.add_resource(API_VM_Element, "/vm/<vm>")


# /vm/<vm>/meta
class API_VM_Metadata(Resource):
    @Authenticator
    def get(self, vm):
        """
        Return the metadata of {vm}
        ---
        tags:
          - vm
        responses:
          200:
            description: OK
            schema:
              type: object
              id: VMMetadata
              properties:
                name:
                  type: string
                  description: The name of the VM
                node_limit:
                  type: array
                  description: The node(s) the VM is permitted to be assigned to
                  items:
                    type: string
                node_selector:
                  type: string
                  description: The selector used to determine candidate nodes during migration; see 'target_selector' in the node daemon configuration reference
                node_autostart:
                  type: string
                  description: Whether to autostart the VM when its node returns to ready domain state
                migration_method:
                  type: string
                  description: The preferred migration method (live, shutdown, none)
          404:
            description: VM not found
            schema:
              type: object
              id: Message
        """
        return api_helper.get_vm_meta(vm)

    @RequestParser(
        [
            {"name": "limit"},
            {
                "name": "selector",
                "choices": ("mem", "memprov", "vcpus", "load", "vms", "none"),
                "helptext": "A valid selector must be specified",
            },
            {"name": "autostart"},
            {"name": "profile"},
            {
                "name": "migration_method",
                "choices": ("live", "shutdown", "none"),
                "helptext": "A valid migration_method must be specified",
            },
        ]
    )
    @Authenticator
    def post(self, vm, reqargs):
        """
        Set the metadata of {vm}
        ---
        tags:
          - vm
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: The CSV list of node(s) the VM is permitted to be assigned to; should include "node" and any other valid target nodes; this limit will be used for autoselection on definition and migration
          - in: query
            name: selector
            type: string
            required: false
            description: The selector used to determine candidate nodes during migration; see 'target_selector' in the node daemon configuration reference
            enum:
              - mem
              - memprov
              - vcpus
              - load
              - vms
              - none (cluster default)
          - in: query
            name: autostart
            type: boolean
            required: false
            description: Whether to autostart the VM when its node returns to ready domain state
          - in: query
            name: profile
            type: string
            required: false
            description: The PVC provisioner profile for the VM
          - in: query
            name: migration_method
            type: string
            required: false
            description: The preferred migration method (live, shutdown, none)
            default: none
            enum:
              - live
              - shutdown
              - none
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
          404:
            description: VM not found
            schema:
              type: object
              id: Message
        """
        return api_helper.update_vm_meta(
            vm,
            reqargs.get("limit", None),
            reqargs.get("selector", None),
            reqargs.get("autostart", None),
            reqargs.get("profile", None),
            reqargs.get("migration_method", None),
        )


api.add_resource(API_VM_Metadata, "/vm/<vm>/meta")


# /vm/<vm>/tags
class API_VM_Tags(Resource):
    @Authenticator
    def get(self, vm):
        """
        Return the tags of {vm}
        ---
        tags:
          - vm
        responses:
          200:
            description: OK
            schema:
              type: object
              id: VMTags
              properties:
                name:
                  type: string
                  description: The name of the VM
                tags:
                  type: array
                  description: The tag(s) of the VM
                  items:
                    type: object
                    id: VMTag
          404:
            description: VM not found
            schema:
              type: object
              id: Message
        """
        return api_helper.get_vm_tags(vm)

    @RequestParser(
        [
            {
                "name": "action",
                "choices": ("add", "remove"),
                "helptext": "A valid action must be specified",
            },
            {"name": "tag"},
            {"name": "protected"},
        ]
    )
    @Authenticator
    def post(self, vm, reqargs):
        """
        Set the tags of {vm}
        ---
        tags:
          - vm
        parameters:
          - in: query
            name: action
            type: string
            required: true
            description: The action to perform with the tag
            enum:
              - add
              - remove
          - in: query
            name: tag
            type: string
            required: true
            description: The text value of the tag
          - in: query
            name: protected
            type: boolean
            required: false
            default: false
            description: Set the protected state of the tag
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
          404:
            description: VM not found
            schema:
              type: object
              id: Message
        """
        return api_helper.update_vm_tag(
            vm,
            reqargs.get("action"),
            reqargs.get("tag"),
            reqargs.get("protected", False),
        )


api.add_resource(API_VM_Tags, "/vm/<vm>/tags")


# /vm/<vm</state
class API_VM_State(Resource):
    @Authenticator
    def get(self, vm):
        """
        Return the state information of {vm}
        ---
        tags:
          - vm
        responses:
          200:
            description: OK
            schema:
              type: object
              id: VMState
              properties:
                name:
                  type: string
                  description: The name of the VM
                state:
                  type: string
                  description: The current state of the VM
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.vm_state(vm)

    @RequestParser(
        [
            {
                "name": "state",
                "choices": ("start", "shutdown", "stop", "restart", "disable"),
                "helptext": "A valid state must be specified",
                "required": True,
            },
            {"name": "force"},
            {"name": "wait"},
        ]
    )
    @Authenticator
    def post(self, vm, reqargs):
        """
        Set the state of {vm}
        ---
        tags:
          - vm
        parameters:
          - in: query
            name: state
            type: string
            required: true
            description: The new state of the VM
            enum:
              - start
              - shutdown
              - stop
              - restart
              - disable
          - in: query
            name: force
            type: boolean
            description: Whether to force stop instead of shutdown VM during disable
          - in: query
            name: wait
            type: boolean
            description: Whether to block waiting for the state change to complete
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        state = reqargs.get("state", None)
        force = bool(strtobool(reqargs.get("force", "false")))
        wait = bool(strtobool(reqargs.get("wait", "false")))

        if state == "start":
            return api_helper.vm_start(vm)
        if state == "shutdown":
            return api_helper.vm_shutdown(vm, wait)
        if state == "stop":
            return api_helper.vm_stop(vm)
        if state == "restart":
            return api_helper.vm_restart(vm, wait)
        if state == "disable":
            return api_helper.vm_disable(vm, force)
        abort(400)


api.add_resource(API_VM_State, "/vm/<vm>/state")


# /vm/<vm>/node
class API_VM_Node(Resource):
    @Authenticator
    def get(self, vm):
        """
        Return the node information of {vm}
        ---
        tags:
          - vm
        responses:
          200:
            description: OK
            schema:
              type: object
              id: VMNode
              properties:
                name:
                  type: string
                  description: The name of the VM
                node:
                  type: string
                  description: The node the VM is currently assigned to
                last_node:
                  type: string
                  description: The last node the VM was assigned to before migrating
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.vm_node(vm)

    @RequestParser(
        [
            {
                "name": "action",
                "choices": ("migrate", "unmigrate", "move"),
                "helptext": "A valid action must be specified",
                "required": True,
            },
            {"name": "node"},
            {"name": "force"},
            {"name": "wait"},
            {"name": "force_live"},
        ]
    )
    @Authenticator
    def post(self, vm, reqargs):
        """
        Set the node of {vm}
        ---
        tags:
          - vm
        parameters:
          - in: query
            name: action
            type: string
            required: true
            description: The action to take to change nodes
            enum:
              - migrate
              - unmigrate
              - move
          - in: query
            name: node
            type: string
            description: The node the VM should be assigned to; autoselect if empty or invalid
          - in: query
            name: force
            type: boolean
            description: Whether to force an already-migrated VM to a new node
          - in: query
            name: wait
            type: boolean
            description: Whether to block waiting for the migration to complete
          - in: query
            name: force_live
            type: boolean
            description: Whether to enforce live migration and disable shutdown-based fallback migration
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        action = reqargs.get("action", None)
        node = reqargs.get("node", None)
        force = bool(strtobool(reqargs.get("force", "false")))
        wait = bool(strtobool(reqargs.get("wait", "false")))
        force_live = bool(strtobool(reqargs.get("force_live", "false")))

        if action == "move":
            return api_helper.vm_move(vm, node, wait, force_live)
        if action == "migrate":
            return api_helper.vm_migrate(vm, node, force, wait, force_live)
        if action == "unmigrate":
            return api_helper.vm_unmigrate(vm, wait, force_live)
        abort(400)


api.add_resource(API_VM_Node, "/vm/<vm>/node")


# /vm/<vm>/locks
class API_VM_Locks(Resource):
    @Authenticator
    def post(self, vm):
        """
        Flush disk locks of {vm}
        ---
        tags:
          - vm
        responses:
          202:
            description: OK
            schema:
                type: string
                description: The Celery job ID of the task
        """
        vm_node_detail, retcode = api_helper.vm_node(vm)
        if retcode == 200:
            vm_node = vm_node_detail["node"]
        else:
            return vm_node_detail, retcode

        task = run_celery_task("vm.flush_locks", domain=vm, run_on=vm_node)

        return (
            {"task_id": task.id, "task_name": "vm.flush_locks", "run_on": vm_node},
            202,
            {"Location": Api.url_for(api, API_Tasks_Element, task_id=task.id)},
        )


api.add_resource(API_VM_Locks, "/vm/<vm>/locks")


# /vm/<vm>/console
class API_VM_Console(Resource):
    @RequestParser([{"name": "lines"}])
    @Authenticator
    def get(self, vm, reqargs):
        """
        Return the recent console log of {vm}
        ---
        tags:
          - vm
        parameters:
          - in: query
            name: lines
            type: integer
            required: false
            description: The number of lines to retrieve
        responses:
          200:
            description: OK
            schema:
              type: object
              id: VMLog
              properties:
                name:
                  type: string
                  description: The name of the VM
                data:
                  type: string
                  description: The recent console log text
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.vm_console(vm, reqargs.get("lines", None))


api.add_resource(API_VM_Console, "/vm/<vm>/console")


# /vm/<vm>/rename
class API_VM_Rename(Resource):
    @RequestParser([{"name": "new_name"}])
    @Authenticator
    def post(self, vm, reqargs):
        """
        Rename VM {vm}, and all connected disk volumes which include this name, to {new_name}
        ---
        tags:
          - vm
        parameters:
          - in: query
            name: new_name
            type: string
            required: true
            description: The new name of the VM
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_helper.vm_rename(vm, reqargs.get("new_name", None))


api.add_resource(API_VM_Rename, "/vm/<vm>/rename")


# /vm/<vm>/device
class API_VM_Device(Resource):
    @RequestParser(
        [
            {
                "name": "xml",
                "required": True,
                "helptext": "A Libvirt XML device document must be specified",
            },
        ]
    )
    @Authenticator
    def post(self, vm, reqargs):
        """
        Hot-attach device XML to {vm}
        ---
        tags:
          - vm
        parameters:
          - in: query
            name: xml
            type: string
            required: true
            description: The raw Libvirt XML definition of the device to attach
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        try:
            xml = reqargs.get("xml", None)
            lxml_fromstring(xml)
        except Exception:
            return {"message": "Specified XML document is not valid"}, 400

        vm_node_detail, retcode = api_helper.vm_node(vm)
        if retcode == 200:
            vm_node = vm_node_detail["node"]
        else:
            return vm_node_detail, retcode

        task = run_celery_task("vm.device_attach", domain=vm, xml=xml, run_on=vm_node)

        return (
            {"task_id": task.id, "task_name": "vm.device_attach", "run_on": vm_node},
            202,
            {"Location": Api.url_for(api, API_Tasks_Element, task_id=task.id)},
        )

    @RequestParser(
        [
            {
                "name": "xml",
                "required": True,
                "helptext": "A Libvirt XML device document must be specified",
            },
        ]
    )
    @Authenticator
    def delete(self, vm, reqargs):
        """
        Hot-detach device XML to {vm}
        ---
        tags:
          - vm
        parameters:
          - in: query
            name: xml
            type: string
            required: true
            description: The raw Libvirt XML definition of the device to detach
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        try:
            xml = reqargs.get("xml", None)
            lxml_fromstring(xml)
        except Exception:
            return {"message": "Specified XML document is not valid"}, 400

        vm_node_detail, retcode = api_helper.vm_node(vm)
        if retcode == 200:
            vm_node = vm_node_detail["node"]
        else:
            return vm_node_detail, retcode

        task = run_celery_task("vm.device_detach", domain=vm, xml=xml, run_on=vm_node)

        return (
            {"task_id": task.id, "task_name": "vm.device_detach", "run_on": vm_node},
            202,
            {"Location": Api.url_for(api, API_Tasks_Element, task_id=task.id)},
        )


api.add_resource(API_VM_Device, "/vm/<vm>/device")


# /vm/<vm>/backup
class API_VM_Backup(Resource):
    @RequestParser(
        [
            {
                "name": "backup_path",
                "required": True,
                "helptext": "A local filesystem path on the primary coordinator must be specified",
            },
            {
                "name": "incremental_parent",
                "required": False,
            },
            {
                "name": "retain_snapshot",
                "required": False,
            },
        ]
    )
    @Authenticator
    def post(self, vm, reqargs):
        """
        Create a backup of {vm} and its volumes to a local primary coordinator filesystem path
        ---
        tags:
          - vm
        parameters:
          - in: query
            name: backup_path
            type: string
            required: true
            description: A local filesystem path on the primary coordinator to store the backup
          - in: query
            name: incremental_parent
            type: string
            required: false
            description: A previous backup datestamp to use as an incremental parent; if unspecified a full backup is taken
          - in: query
            name: retain_snapshot
            type: boolean
            required: false
            default: false
            description: Whether or not to retain this backup's volume snapshots to use as a future incremental parent; full backups only
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Execution error
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        backup_path = reqargs.get("backup_path", None)
        incremental_parent = reqargs.get("incremental_parent", None)
        retain_snapshot = bool(strtobool(reqargs.get("retain_snapshot", "false")))
        return api_helper.vm_backup(
            vm, backup_path, incremental_parent, retain_snapshot
        )

    @RequestParser(
        [
            {
                "name": "backup_path",
                "required": True,
                "helptext": "A local filesystem path on the primary coordinator must be specified",
            },
            {
                "name": "backup_datestring",
                "required": True,
                "helptext": "A backup datestring must be specified",
            },
        ]
    )
    @Authenticator
    def delete(self, vm, reqargs):
        """
        Remove a backup of {vm}, including snapshots, from a local primary coordinator filesystem path
        ---
        tags:
          - vm
        parameters:
          - in: query
            name: backup_path
            type: string
            required: true
            description: A local filesystem path on the primary coordinator where the backup is stored
          - in: query
            name: backup_datestring
            type: string
            required: true
            description: The backup datestring identifier (e.g. 20230102030405)
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Execution error
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        backup_path = reqargs.get("backup_path", None)
        backup_datestring = reqargs.get("backup_datestring", None)
        return api_helper.vm_remove_backup(vm, backup_path, backup_datestring)


api.add_resource(API_VM_Backup, "/vm/<vm>/backup")


# /vm/<vm>/restore
class API_VM_Restore(Resource):
    @RequestParser(
        [
            {
                "name": "backup_path",
                "required": True,
                "helptext": "A local filesystem path on the primary coordinator must be specified",
            },
            {
                "name": "backup_datestring",
                "required": True,
                "helptext": "A backup datestring must be specified",
            },
            {
                "name": "retain_snapshot",
                "required": False,
            },
        ]
    )
    @Authenticator
    def post(self, vm, reqargs):
        """
        Restore a backup of {vm} and its volumes from a local primary coordinator filesystem path
        ---
        tags:
          - vm
        parameters:
          - in: query
            name: backup_path
            type: string
            required: true
            description: A local filesystem path on the primary coordinator where the backup is stored
          - in: query
            name: backup_datestring
            type: string
            required: true
            description: The backup datestring identifier (e.g. 20230102030405)
          - in: query
            name: retain_snapshot
            type: boolean
            required: false
            default: true
            description: Whether or not to retain the (parent, if incremental) volume snapshot after restore
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Execution error
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        backup_path = reqargs.get("backup_path", None)
        backup_datestring = reqargs.get("backup_datestring", None)
        retain_snapshot = bool(strtobool(reqargs.get("retain_snapshot", "true")))
        return api_helper.vm_restore(
            vm, backup_path, backup_datestring, retain_snapshot
        )


api.add_resource(API_VM_Restore, "/vm/<vm>/restore")


##########################################################
# Client API - Network
##########################################################


# /network
class API_Network_Root(Resource):
    @RequestParser([{"name": "limit"}])
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of networks in the cluster
        ---
        tags:
          - network
        definitions:
          - schema:
              type: object
              id: network
              properties:
                vni:
                  type: integer
                  description: The VNI of the network
                description:
                  type: string
                  description: The description of the network
                type:
                  type: string
                  description: The type of network
                  enum:
                    - managed
                    - bridged
                mtu:
                  type: integer
                  description: The MTU of the network, if set; empty otherwise
                domain:
                  type: string
                  description: The DNS domain of the network ("managed" networks only)
                name_servers:
                  type: array
                  description: The configured DNS nameservers of the network for NS records ("managed" networks only)
                  items:
                    type: string
                ip4:
                  type: object
                  description: The IPv4 details of the network ("managed" networks only)
                  properties:
                    network:
                      type: string
                      description: The IPv4 network subnet in CIDR format
                    gateway:
                      type: string
                      description: The IPv4 default gateway address
                    dhcp_flag:
                      type: boolean
                      description: Whether DHCP is enabled
                    dhcp_start:
                      type: string
                      description: The IPv4 DHCP pool start address
                    dhcp_end:
                      type: string
                      description: The IPv4 DHCP pool end address
                ip6:
                  type: object
                  description: The IPv6 details of the network ("managed" networks only)
                  properties:
                    network:
                      type: string
                      description: The IPv6 network subnet in CIDR format
                    gateway:
                      type: string
                      description: The IPv6 default gateway address
                    dhcp_flag:
                      type: boolean
                      description: Whether DHCPv6 is enabled
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: A VNI or description search limit; fuzzy by default, use ^/$ to force exact matches
        responses:
          200:
            description: OK
            schema:
              type: array
              items:
                $ref: '#/definitions/network'
        """
        return api_helper.net_list(reqargs.get("limit", None))

    @RequestParser(
        [
            {"name": "vni", "required": True},
            {"name": "description", "required": True},
            {
                "name": "nettype",
                "choices": ("managed", "bridged"),
                "helptext": "A valid nettype must be specified",
                "required": True,
            },
            {"name": "mtu"},
            {"name": "domain"},
            {"name": "name_servers"},
            {"name": "ip4_network"},
            {"name": "ip4_gateway"},
            {"name": "ip6_network"},
            {"name": "ip6_gateway"},
            {"name": "dhcp4"},
            {"name": "dhcp4_start"},
            {"name": "dhcp4_end"},
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Create a new network
        ---
        tags:
          - network
        parameters:
          - in: query
            name: vni
            type: integer
            required: true
            description: The VNI of the network
          - in: query
            name: description
            type: string
            required: true
            description: The description of the network
          - in: query
            name: nettype
            type: string
            required: true
            description: The type of network
            enum:
              - managed
              - bridged
          - in: query
            name: mtu
            type: integer
            description: The MTU of the network; defaults to the underlying interface MTU if not set
          - in: query
            name: domain
            type: string
            description: The DNS domain of the network ("managed" networks only)
          - in: query
            name: name_servers
            type: string
            description: The CSV list of DNS nameservers for network NS records ("managed" networks only)
          - in: query
            name: ip4_network
            type: string
            description: The IPv4 network subnet of the network in CIDR format; IPv4 disabled if unspecified ("managed" networks only)
          - in: query
            name: ip4_gateway
            type: string
            description: The IPv4 default gateway address of the network ("managed" networks only)
          - in: query
            name: dhcp4
            type: boolean
            description: Whether to enable DHCPv4 for the network ("managed" networks only)
          - in: query
            name: dhcp4_start
            type: string
            description: The DHCPv4 pool start address of the network ("managed" networks only)
          - in: query
            name: dhcp4_end
            type: string
            description: The DHCPv4 pool end address of the network ("managed" networks only)
          - in: query
            name: ip6_network
            type: string
            description: The IPv6 network subnet of the network in CIDR format; IPv6 disabled if unspecified; DHCPv6 is always used in IPv6 managed networks ("managed" networks only)
          - in: query
            name: ip6_gateway
            type: string
            description: The IPv6 default gateway address of the network ("managed" networks only)
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        if reqargs.get("name_servers", None):
            name_servers = ",".join(reqargs.get("name_servers", None))
        else:
            name_servers = ""
        return api_helper.net_add(
            reqargs.get("vni", None),
            reqargs.get("description", None),
            reqargs.get("nettype", None),
            reqargs.get("mtu", ""),
            reqargs.get("domain", None),
            name_servers,
            reqargs.get("ip4_network", None),
            reqargs.get("ip4_gateway", None),
            reqargs.get("ip6_network", None),
            reqargs.get("ip6_gateway", None),
            bool(strtobool(reqargs.get("dhcp4", "false"))),
            reqargs.get("dhcp4_start", None),
            reqargs.get("dhcp4_end", None),
        )


api.add_resource(API_Network_Root, "/network")


# /network/<vni>
class API_Network_Element(Resource):
    @Authenticator
    def get(self, vni):
        """
        Return information about network {vni}
        ---
        tags:
          - network
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/network'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.net_list(vni, is_fuzzy=False)

    @RequestParser(
        [
            {"name": "description", "required": True},
            {
                "name": "nettype",
                "choices": ("managed", "bridged"),
                "helptext": "A valid nettype must be specified",
                "required": True,
            },
            {"name": "mtu"},
            {"name": "domain"},
            {"name": "name_servers"},
            {"name": "ip4_network"},
            {"name": "ip4_gateway"},
            {"name": "ip6_network"},
            {"name": "ip6_gateway"},
            {"name": "dhcp4"},
            {"name": "dhcp4_start"},
            {"name": "dhcp4_end"},
        ]
    )
    @Authenticator
    def post(self, vni, reqargs):
        """
        Create a new network {vni}
        ---
        tags:
          - network
        parameters:
          - in: query
            name: description
            type: string
            required: true
            description: The description of the network
          - in: query
            name: nettype
            type: string
            required: true
            description: The type of network
            enum:
              - managed
              - bridged
          - in: query
            name: mtu
            type: integer
            description: The MTU of the network; defaults to the underlying interface MTU if not set
          - in: query
            name: domain
            type: string
            description: The DNS domain of the network ("managed" networks only)
          - in: query
            name: name_servers
            type: string
            description: The CSV list of DNS nameservers for network NS records ("managed" networks only)
          - in: query
            name: ip4_network
            type: string
            description: The IPv4 network subnet of the network in CIDR format; IPv4 disabled if unspecified ("managed" networks only)
          - in: query
            name: ip4_gateway
            type: string
            description: The IPv4 default gateway address of the network ("managed" networks only)
          - in: query
            name: dhcp4
            type: boolean
            description: Whether to enable DHCPv4 for the network ("managed" networks only)
          - in: query
            name: dhcp4_start
            type: string
            description: The DHCPv4 pool start address of the network ("managed" networks only)
          - in: query
            name: dhcp4_end
            type: string
            description: The DHCPv4 pool end address of the network ("managed" networks only)
          - in: query
            name: ip6_network
            type: string
            description: The IPv6 network subnet of the network in CIDR format; IPv6 disabled if unspecified; DHCPv6 is always used in IPv6 managed networks ("managed" networks only)
          - in: query
            name: ip6_gateway
            type: string
            description: The IPv6 default gateway address of the network ("managed" networks only)
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        if reqargs.get("name_servers", None):
            name_servers = ",".join(reqargs.get("name_servers", None))
        else:
            name_servers = ""
        return api_helper.net_add(
            reqargs.get("vni", None),
            reqargs.get("description", None),
            reqargs.get("nettype", None),
            reqargs.get("mtu", ""),
            reqargs.get("domain", None),
            name_servers,
            reqargs.get("ip4_network", None),
            reqargs.get("ip4_gateway", None),
            reqargs.get("ip6_network", None),
            reqargs.get("ip6_gateway", None),
            bool(strtobool(reqargs.get("dhcp4", "false"))),
            reqargs.get("dhcp4_start", None),
            reqargs.get("dhcp4_end", None),
        )

    @RequestParser(
        [
            {"name": "description"},
            {"name": "mtu"},
            {"name": "domain"},
            {"name": "name_servers"},
            {"name": "ip4_network"},
            {"name": "ip4_gateway"},
            {"name": "ip6_network"},
            {"name": "ip6_gateway"},
            {"name": "dhcp4"},
            {"name": "dhcp4_start"},
            {"name": "dhcp4_end"},
        ]
    )
    @Authenticator
    def put(self, vni, reqargs):
        """
        Update details of network {vni}
        Note: A network's type cannot be changed; the network must be removed and recreated as the new type
        ---
        tags:
          - network
        parameters:
          - in: query
            name: description
            type: string
            description: The description of the network
          - in: query
            name: mtu
            type: integer
            description: The MTU of the network
          - in: query
            name: domain
            type: string
            description: The DNS domain of the network ("managed" networks only)
          - in: query
            name: name_servers
            type: string
            description: The CSV list of DNS nameservers for network NS records ("managed" networks only)
          - in: query
            name: ip4_network
            type: string
            description: The IPv4 network subnet of the network in CIDR format; IPv4 disabled if unspecified ("managed" networks only)
          - in: query
            name: ip4_gateway
            type: string
            description: The IPv4 default gateway address of the network ("managed" networks only)
          - in: query
            name: dhcp4
            type: boolean
            description: Whether to enable DHCPv4 for the network ("managed" networks only)
          - in: query
            name: dhcp4_start
            type: string
            description: The DHCPv4 pool start address of the network ("managed" networks only)
          - in: query
            name: dhcp4_end
            type: string
            description: The DHCPv4 pool end address of the network ("managed" networks only)
          - in: query
            name: ip6_network
            type: string
            description: The IPv6 network subnet of the network in CIDR format; IPv6 disabled if unspecified; DHCPv6 is always used in IPv6 managed networks ("managed" networks only)
          - in: query
            name: ip6_gateway
            type: string
            description: The IPv6 default gateway address of the network ("managed" networks only)
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        if reqargs.get("name_servers", None):
            name_servers = ",".join(reqargs.get("name_servers", None))
        else:
            name_servers = ""
        return api_helper.net_modify(
            vni,
            reqargs.get("description", None),
            reqargs.get("mtu", None),
            reqargs.get("domain", None),
            name_servers,
            reqargs.get("ip4_network", None),
            reqargs.get("ip4_gateway", None),
            reqargs.get("ip6_network", None),
            reqargs.get("ip6_gateway", None),
            reqargs.get("dhcp4", None),
            reqargs.get("dhcp4_start", None),
            reqargs.get("dhcp4_end", None),
        )

    @Authenticator
    def delete(self, vni):
        """
        Remove network {vni}
        ---
        tags:
          - network
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.net_remove(vni)


api.add_resource(API_Network_Element, "/network/<vni>")


# /network/<vni>/lease
class API_Network_Lease_Root(Resource):
    @RequestParser([{"name": "limit"}, {"name": "static"}])
    @Authenticator
    def get(self, vni, reqargs):
        """
        Return a list of DHCP leases in network {vni}
        ---
        tags:
          - network
        definitions:
          - schema:
              type: object
              id: lease
              properties:
                hostname:
                  type: string
                  description: The (short) hostname of the lease
                ip4_address:
                  type: string
                  description: The IPv4 address of the lease
                mac_address:
                  type: string
                  description: The MAC address of the lease
                timestamp:
                  type: integer
                  description: The UNIX timestamp of the lease creation
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: A MAC address search limit; fuzzy by default, use ^/$ to force exact matches
          - in: query
            name: static
            type: boolean
            required: false
            default: false
            description: Whether to show only static leases
        responses:
          200:
            description: OK
            schema:
              type: array
              items:
                $ref: '#/definitions/lease'
          400:
            description: Bad request
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.net_dhcp_list(
            vni,
            reqargs.get("limit", None),
            bool(strtobool(reqargs.get("static", "false"))),
        )

    @RequestParser(
        [
            {"name": "macaddress", "required": True},
            {"name": "ipaddress", "required": True},
            {"name": "hostname"},
        ]
    )
    @Authenticator
    def post(self, vni, reqargs):
        """
        Create a new static DHCP lease in network {vni}
        ---
        tags:
          - network
        parameters:
          - in: query
            name: macaddress
            type: string
            required: false
            description: A MAC address for the lease
          - in: query
            name: ipaddress
            type: string
            required: false
            description: An IPv4 address for the lease
          - in: query
            name: hostname
            type: string
            required: false
            description: An optional hostname for the lease
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.net_dhcp_add(
            vni,
            reqargs.get("ipaddress", None),
            reqargs.get("macaddress", None),
            reqargs.get("hostname", None),
        )


api.add_resource(API_Network_Lease_Root, "/network/<vni>/lease")


# /network/<vni>/lease/{mac}
class API_Network_Lease_Element(Resource):
    @Authenticator
    def get(self, vni, mac):
        """
        Return information about DHCP lease {mac} in network {vni}
        ---
        tags:
          - network
        definitions:
          - schema:
              type: object
              id: lease
              properties:
                hostname:
                  type: string
                  description: The (short) hostname of the lease
                ip4_address:
                  type: string
                  description: The IPv4 address of the lease
                mac_address:
                  type: string
                  description: The MAC address of the lease
                timestamp:
                  type: integer
                  description: The UNIX timestamp of the lease creation
        responses:
          200:
            description: OK
            schema:
              type: array
              items:
                $ref: '#/definitions/lease'
          400:
            description: Bad request
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.net_dhcp_list(vni, mac, False)

    @RequestParser([{"name": "ipaddress", "required": True}, {"name": "hostname"}])
    @Authenticator
    def post(self, vni, mac, reqargs):
        """
        Create a new static DHCP lease {mac} in network {vni}
        ---
        tags:
          - network
        parameters:
          - in: query
            name: macaddress
            type: string
            required: false
            description: A MAC address for the lease
          - in: query
            name: ipaddress
            type: string
            required: false
            description: An IPv4 address for the lease
          - in: query
            name: hostname
            type: string
            required: false
            description: An optional hostname for the lease
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.net_dhcp_add(
            vni, reqargs.get("ipaddress", None), mac, reqargs.get("hostname", None)
        )

    @Authenticator
    def delete(self, vni, mac):
        """
        Delete static DHCP lease {mac}
        ---
        tags:
          - network
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.net_dhcp_remove(vni, mac)


api.add_resource(API_Network_Lease_Element, "/network/<vni>/lease/<mac>")


# /network/<vni>/acl
class API_Network_ACL_Root(Resource):
    @RequestParser(
        [
            {"name": "limit"},
            {
                "name": "direction",
                "choices": ("in", "out"),
                "helptext": "A valid direction must be specified.",
            },
        ]
    )
    @Authenticator
    def get(self, vni, reqargs):
        """
        Return a list of ACLs in network {vni}
        ---
        tags:
          - network
        definitions:
          - schema:
              type: object
              id: acl
              properties:
                description:
                  type: string
                  description: The description of the rule
                direction:
                  type: string
                  description: The direction the rule applies in
                order:
                  type: integer
                  description: The order of the rule in the chain
                rule:
                  type: string
                  description: The NFT-format rule string
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: A description search limit; fuzzy by default, use ^/$ to force exact matches
          - in: query
            name: direction
            type: string
            required: false
            description: The direction of rules to display; both directions shown if unspecified
        responses:
          200:
            description: OK
            schema:
              type: array
              items:
                $ref: '#/definitions/acl'
          400:
            description: Bad request
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.net_acl_list(
            vni, reqargs.get("limit", None), reqargs.get("direction", None)
        )

    @RequestParser(
        [
            {
                "name": "description",
                "required": True,
                "helptext": "A whitespace-free description must be specified.",
            },
            {"name": "rule", "required": True, "helptext": "A rule must be specified."},
            {
                "name": "direction",
                "choices": ("in", "out"),
                "helptext": "A valid direction must be specified.",
            },
            {"name": "order"},
        ]
    )
    @Authenticator
    def post(self, vni, reqargs):
        """
        Create a new ACL in network {vni}
        ---
        tags:
          - network
        parameters:
          - in: query
            name: description
            type: string
            required: true
            description: A whitespace-free description/name for the ACL
          - in: query
            name: direction
            type: string
            required: false
            description: The direction of the ACL; defaults to "in" if unspecified
            enum:
              - in
              - out
          - in: query
            name: order
            type: integer
            description: The order of the ACL in the chain; defaults to the end
          - in: query
            name: rule
            type: string
            required: true
            description: The raw NFT firewall rule string
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_helper.net_acl_add(
            vni,
            reqargs.get("direction", "in"),
            reqargs.get("description", None),
            reqargs.get("rule", None),
            reqargs.get("order", None),
        )


api.add_resource(API_Network_ACL_Root, "/network/<vni>/acl")


# /network/<vni>/acl/<description>
class API_Network_ACL_Element(Resource):
    @Authenticator
    def get(self, vni, description):
        """
        Return information about ACL {description} in network {vni}
        ---
        tags:
          - network
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/acl'
          400:
            description: Bad request
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.net_acl_list(vni, description, None, is_fuzzy=False)

    @RequestParser(
        [
            {"name": "rule", "required": True, "helptext": "A rule must be specified."},
            {
                "name": "direction",
                "choices": ("in", "out"),
                "helptext": "A valid direction must be specified.",
            },
            {"name": "order"},
        ]
    )
    @Authenticator
    def post(self, vni, description, reqargs):
        """
        Create a new ACL {description} in network {vni}
        ---
        tags:
          - network
        parameters:
          - in: query
            name: direction
            type: string
            required: false
            description: The direction of the ACL; defaults to "in" if unspecified
            enum:
              - in
              - out
          - in: query
            name: order
            type: integer
            description: The order of the ACL in the chain; defaults to the end
          - in: query
            name: rule
            type: string
            required: true
            description: The raw NFT firewall rule string
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_helper.net_acl_add(
            vni,
            reqargs.get("direction", "in"),
            description,
            reqargs.get("rule", None),
            reqargs.get("order", None),
        )

    @Authenticator
    def delete(self, vni, description):
        """
        Delete ACL {description} in network {vni}
        ---
        tags:
          - network
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.net_acl_remove(vni, description)


api.add_resource(API_Network_ACL_Element, "/network/<vni>/acl/<description>")


##########################################################
# Client API - SR-IOV
##########################################################


# /sriov
class API_SRIOV_Root(Resource):
    @Authenticator
    def get(self):
        pass


api.add_resource(API_SRIOV_Root, "/sriov")


# /sriov/pf
class API_SRIOV_PF_Root(Resource):
    @RequestParser(
        [
            {
                "name": "node",
                "required": True,
                "helptext": "A valid node must be specified.",
            },
        ]
    )
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of SR-IOV PFs on a given node
        ---
        tags:
          - network / sriov
        responses:
          200:
            description: OK
            schema:
              type: object
              id: sriov_pf
              properties:
                phy:
                  type: string
                  description: The name of the SR-IOV PF device
                mtu:
                  type: string
                  description: The MTU of the SR-IOV PF device
                vfs:
                  type: list
                  items:
                    type: string
                    description: The PHY name of a VF of this PF
        """
        return api_helper.sriov_pf_list(reqargs.get("node"))


api.add_resource(API_SRIOV_PF_Root, "/sriov/pf")


# /sriov/pf/<node>
class API_SRIOV_PF_Node(Resource):
    @Authenticator
    def get(self, node):
        """
        Return a list of SR-IOV PFs on node {node}
        ---
        tags:
          - network / sriov
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/sriov_pf'
        """
        return api_helper.sriov_pf_list(node)


api.add_resource(API_SRIOV_PF_Node, "/sriov/pf/<node>")


# /sriov/vf
class API_SRIOV_VF_Root(Resource):
    @RequestParser(
        [
            {
                "name": "node",
                "required": True,
                "helptext": "A valid node must be specified.",
            },
            {
                "name": "pf",
                "required": False,
                "helptext": "A PF parent may be specified.",
            },
        ]
    )
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of SR-IOV VFs on a given node, optionally limited to those in the specified PF
        ---
        tags:
          - network / sriov
        responses:
          200:
            description: OK
            schema:
              type: object
              id: sriov_vf
              properties:
                phy:
                  type: string
                  description: The name of the SR-IOV VF device
                pf:
                  type: string
                  description: The name of the SR-IOV PF parent of this VF device
                mtu:
                  type: integer
                  description: The current MTU of the VF device
                mac:
                  type: string
                  description: The current MAC address of the VF device
                config:
                  type: object
                  id: sriov_vf_config
                  properties:
                    vlan_id:
                      type: string
                      description: The tagged vLAN ID of the SR-IOV VF device
                    vlan_qos:
                      type: string
                      description: The QOS group of the tagged vLAN
                    tx_rate_min:
                      type: string
                      description: The minimum TX rate of the SR-IOV VF device
                    tx_rate_max:
                      type: string
                      description: The maximum TX rate of the SR-IOV VF device
                    spoof_check:
                      type: boolean
                      description: Whether device spoof checking is enabled or disabled
                    link_state:
                      type: string
                      description: The current SR-IOV VF link state (either enabled, disabled, or auto)
                    trust:
                      type: boolean
                      description: Whether guest device trust is enabled or disabled
                    query_rss:
                      type: boolean
                      description: Whether VF RSS querying is enabled or disabled
                usage:
                  type: object
                  id: sriov_vf_usage
                  properties:
                    used:
                      type: boolean
                      description: Whether the SR-IOV VF is currently used by a VM or not
                    domain:
                      type: boolean
                      description: The UUID of the domain the SR-IOV VF is currently used by
        """
        return api_helper.sriov_vf_list(reqargs.get("node"), reqargs.get("pf", None))


api.add_resource(API_SRIOV_VF_Root, "/sriov/vf")


# /sriov/vf/<node>
class API_SRIOV_VF_Node(Resource):
    @RequestParser(
        [
            {
                "name": "pf",
                "required": False,
                "helptext": "A PF parent may be specified.",
            },
        ]
    )
    @Authenticator
    def get(self, node, reqargs):
        """
        Return a list of SR-IOV VFs on node {node}, optionally limited to those in the specified PF
        ---
        tags:
          - network / sriov
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/sriov_vf'
        """
        return api_helper.sriov_vf_list(node, reqargs.get("pf", None))


api.add_resource(API_SRIOV_VF_Node, "/sriov/vf/<node>")


# /sriov/vf/<node>/<vf>
class API_SRIOV_VF_Element(Resource):
    @Authenticator
    def get(self, node, vf):
        """
        Return information about {vf} on {node}
        ---
        tags:
          - network / sriov
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/sriov_vf'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        vf_list = list()
        full_vf_list, _ = api_helper.sriov_vf_list(node)
        for vf_element in full_vf_list:
            if vf_element["phy"] == vf:
                vf_list.append(vf_element)

        if len(vf_list) == 1:
            return vf_list, 200
        else:
            return {"message": "No VF '{}' found on node '{}'".format(vf, node)}, 404

    @RequestParser(
        [
            {"name": "vlan_id"},
            {"name": "vlan_qos"},
            {"name": "tx_rate_min"},
            {"name": "tx_rate_max"},
            {
                "name": "link_state",
                "choices": ("auto", "enable", "disable"),
                "helptext": "A valid state must be specified",
            },
            {"name": "spoof_check"},
            {"name": "trust"},
            {"name": "query_rss"},
        ]
    )
    @Authenticator
    def put(self, node, vf, reqargs):
        """
        Set the configuration of {vf} on {node}
        ---
        tags:
          - network / sriov
        parameters:
          - in: query
            name: vlan_id
            type: integer
            required: false
            description: The vLAN ID for vLAN tagging (0 is disabled)
          - in: query
            name: vlan_qos
            type: integer
            required: false
            description: The vLAN QOS priority (0 is disabled)
          - in: query
            name: tx_rate_min
            type: integer
            required: false
            description: The minimum TX rate (0 is disabled)
          - in: query
            name: tx_rate_max
            type: integer
            required: false
            description: The maximum TX rate (0 is disabled)
          - in: query
            name: link_state
            type: string
            required: false
            description: The administrative link state
            enum:
              - auto
              - enable
              - disable
          - in: query
            name: spoof_check
            type: boolean
            required: false
            description: Enable or disable spoof checking
          - in: query
            name: trust
            type: boolean
            required: false
            description: Enable or disable VF user trust
          - in: query
            name: query_rss
            type: boolean
            required: false
            description: Enable or disable query RSS support
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_helper.update_sriov_vf_config(
            node,
            vf,
            reqargs.get("vlan_id", None),
            reqargs.get("vlan_qos", None),
            reqargs.get("tx_rate_min", None),
            reqargs.get("tx_rate_max", None),
            reqargs.get("link_state", None),
            reqargs.get("spoof_check", None),
            reqargs.get("trust", None),
            reqargs.get("query_rss", None),
        )


api.add_resource(API_SRIOV_VF_Element, "/sriov/vf/<node>/<vf>")


##########################################################
# Client API - Storage
##########################################################
# Note: The prefix `/storage` allows future potential storage subsystems.
#       Since Ceph is the only section not abstracted by PVC directly
#       (i.e. it references Ceph-specific concepts), this makes more
#       sense in the long-term.#


# /storage
class API_Storage_Root(Resource):
    @Authenticator
    def get(self):
        pass


api.add_resource(API_Storage_Root, "/storage")


# /storage/ceph
class API_Storage_Ceph_Root(Resource):
    @Authenticator
    def get(self):
        pass


api.add_resource(API_Storage_Ceph_Root, "/storage/ceph")


# /storage/ceph/status
class API_Storage_Ceph_Status(Resource):
    @Authenticator
    def get(self):
        """
        Return status data for the PVC Ceph cluster
        ---
        tags:
          - storage / ceph
        responses:
          200:
            description: OK
            schema:
              type: object
              properties:
                type:
                  type: string
                  description: The type of Ceph data returned
                primary_node:
                  type: string
                  description: The curent primary node in the cluster
                ceph_data:
                  type: string
                  description: The raw output data
        """
        return api_helper.ceph_status()


api.add_resource(API_Storage_Ceph_Status, "/storage/ceph/status")


# /storage/ceph/utilization
class API_Storage_Ceph_Utilization(Resource):
    @Authenticator
    def get(self):
        """
        Return utilization data for the PVC Ceph cluster
        ---
        tags:
          - storage / ceph
        responses:
          200:
            description: OK
            schema:
              type: object
              properties:
                type:
                  type: string
                  description: The type of Ceph data returned
                primary_node:
                  type: string
                  description: The curent primary node in the cluster
                ceph_data:
                  type: string
                  description: The raw output data
        """
        return api_helper.ceph_util()


api.add_resource(API_Storage_Ceph_Utilization, "/storage/ceph/utilization")


# /storage/ceph/benchmark
class API_Storage_Ceph_Benchmark(Resource):
    @RequestParser([{"name": "job"}])
    @Authenticator
    def get(self, reqargs):
        """
        List results from benchmark jobs
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: job
            type: string
            required: false
            description: A single job name to limit results to
        responses:
          200:
            description: OK
            schema:
              type: object
              id: storagebenchmark
              properties:
                id:
                  type: string (containing integer)
                  description: The database ID of the test result
                job:
                  type: string
                  description: The job name (an ISO date) of the test result
                test_format:
                  type: integer
                  description: The PVC benchmark format of the results
                benchmark_result:
                  type: object
                  description: A format 0 test result
                  properties:
                    test_name:
                      type: object
                      properties:
                        overall:
                          type: object
                          properties:
                            iosize:
                              type: string (integer)
                              description: The total size of the benchmark data
                            bandwidth:
                              type: string (integer)
                              description: The average bandwidth (KiB/s)
                            iops:
                              type: string (integer)
                              description: The average IOPS
                            runtime:
                              type: string (integer)
                              description: The total test time in milliseconds
                        latency:
                          type: object
                          properties:
                            min:
                              type: string (integer)
                              description: The minimum latency measurement
                            max:
                              type: string (integer)
                              description: The maximum latency measurement
                            mean:
                              type: string (float)
                              description: The mean latency measurement
                            stdev:
                              type: string (float)
                              description: The standard deviation of latency
                        bandwidth:
                          type: object
                          properties:
                            min:
                              type: string (integer)
                              description: The minimum bandwidth (KiB/s) measurement
                            max:
                              type: string (integer)
                              description: The maximum bandwidth (KiB/s) measurement
                            mean:
                              type: string (float)
                              description: The mean bandwidth (KiB/s) measurement
                            stdev:
                              type: string (float)
                              description: The standard deviation of bandwidth
                            numsamples:
                              type: string (integer)
                              description: The number of samples taken during the test
                        iops:
                          type: object
                          properties:
                            min:
                              type: string (integer)
                              description: The minimum IOPS measurement
                            max:
                              type: string (integer)
                              description: The maximum IOPS measurement
                            mean:
                              type: string (float)
                              description: The mean IOPS measurement
                            stdev:
                              type: string (float)
                              description: The standard deviation of IOPS
                            numsamples:
                              type: string (integer)
                              description: The number of samples taken during the test
                        cpu:
                          type: object
                          properties:
                            user:
                              type: string (float percentage)
                              description: The percentage of test time spent in user space
                            system:
                              type: string (float percentage)
                              description: The percentage of test time spent in system (kernel) space
                            ctxsw:
                              type: string (integer)
                              description: The number of context switches during the test
                            majfault:
                              type: string (integer)
                              description: The number of major page faults during the test
                            minfault:
                              type: string (integer)
                              description: The number of minor page faults during the test
        """
        return list_benchmarks(config, reqargs.get("job", None))

    @RequestParser(
        [
            {
                "name": "pool",
                "required": True,
                "helptext": "A valid pool must be specified.",
            },
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Execute a storage benchmark against a storage pool
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: pool
            type: string
            required: true
            description: The PVC storage pool to benchmark
        responses:
          200:
            description: OK
            schema:
                type: string
                description: The Celery job ID of the benchmark (unused elsewhere)
        """
        # Verify that the pool is valid
        _list, code = api_helper.ceph_pool_list(
            reqargs.get("pool", None), is_fuzzy=False
        )
        if code != 200:
            return {
                "message": 'Pool "{}" is not valid.'.format(reqargs.get("pool"))
            }, 400

        task = run_celery_task(
            "storage.benchmark", pool=reqargs.get("pool", None), run_on="primary"
        )
        return (
            {
                "task_id": task.id,
                "task_name": "storage.benchmark",
                "run_on": get_primary_node(),
            },
            202,
            {"Location": Api.url_for(api, API_Tasks_Element, task_id=task.id)},
        )


api.add_resource(API_Storage_Ceph_Benchmark, "/storage/ceph/benchmark")


# /storage/ceph/option
class API_Storage_Ceph_Option(Resource):
    @RequestParser(
        [
            {
                "name": "option",
                "required": True,
                "helptext": "A valid option must be specified.",
            },
            {
                "name": "action",
                "required": True,
                "choices": ("set", "unset"),
                "helptext": "A valid action must be specified.",
            },
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Set or unset OSD options on the Ceph cluster
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: option
            type: string
            required: true
            description: The Ceph OSD option to act on; must be valid to "ceph osd set/unset"
          - in: query
            name: action
            type: string
            required: true
            description: The action to take
            enum:
              - set
              - unset
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        if reqargs.get("action") == "set":
            return api_helper.ceph_osd_set(reqargs.get("option"))
        if reqargs.get("action") == "unset":
            return api_helper.ceph_osd_unset(reqargs.get("option"))
        abort(400)


api.add_resource(API_Storage_Ceph_Option, "/storage/ceph/option")


# /storage/ceph/osddb
class API_Storage_Ceph_OSDDB_Root(Resource):
    @RequestParser(
        [
            {
                "name": "node",
                "required": True,
                "helptext": "A valid node must be specified.",
            },
            {
                "name": "device",
                "required": True,
                "helptext": "A valid device or detect string must be specified.",
            },
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Add a Ceph OSD database volume group to the cluster
        Note: This task may take up to 30s to complete and return
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: node
            type: string
            required: true
            description: The PVC node to create the OSD DB volume group on
          - in: query
            name: device
            type: string
            required: true
            description: The block device (e.g. "/dev/sdb", "/dev/disk/by-path/...", etc.) or detect string ("detect:NAME:SIZE:ID") to create the OSD DB volume group on
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        node = reqargs.get("node", None)

        task = run_celery_task(
            "osd.add_db_vg", device=reqargs.get("device", None), run_on=node
        )

        return (
            {"task_id": task.id, "task_name": "osd.add_db_vg", "run_on": node},
            202,
            {"Location": Api.url_for(api, API_Tasks_Element, task_id=task.id)},
        )


api.add_resource(API_Storage_Ceph_OSDDB_Root, "/storage/ceph/osddb")


# /storage/ceph/osd
class API_Storage_Ceph_OSD_Root(Resource):
    @RequestParser(
        [
            {"name": "limit"},
        ]
    )
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of Ceph OSDs in the cluster
        ---
        tags:
          - storage / ceph
        definitions:
          - schema:
              type: object
              id: osd
              properties:
                id:
                  type: string (containing integer)
                  description: The Ceph ID of the OSD
                device:
                  type: string
                  description: The OSD data block device
                db_device:
                  type: string
                  description: The OSD database/WAL block device (logical volume); empty if not applicable
                stats:
                  type: object
                  properties:
                    uuid:
                      type: string
                      description: The Ceph OSD UUID
                    up:
                      type: boolean integer
                      description: Whether OSD is in "up" state
                    in:
                      type: boolean integer
                      description: Whether OSD is in "in" state
                    primary_affinity:
                      type: integer
                      description: The Ceph primary affinity of the OSD
                    utilization:
                      type: number
                      description: The utilization percentage of the OSD
                    var:
                      type: number
                      description: The usage variability among OSDs
                    pgs:
                      type: integer
                      description: The number of placement groups on this OSD
                    kb:
                      type: integer
                      description: Size of the OSD in KB
                    weight:
                      type: number
                      description: The weight of the OSD in the CRUSH map
                    reweight:
                      type: number
                      description: The active cluster weight of the OSD
                    node:
                      type: string
                      description: The PVC node the OSD resides on
                    used:
                      type: string
                      description: The used space on the OSD in human-readable format
                    avail:
                      type: string
                      description: The free space on the OSD in human-readable format
                    wr_ops:
                      type: integer
                      description: Cluster-lifetime write operations to OSD
                    rd_ops:
                      type: integer
                      description: Cluster-lifetime read operations from OSD
                    wr_data:
                      type: integer
                      description: Cluster-lifetime write size to OSD
                    rd_data:
                      type: integer
                      description: Cluster-lifetime read size from OSD
                    state:
                      type: string
                      description: CSV of the current state of the OSD
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: A OSD ID search limit; fuzzy by default, use ^/$ to force exact matches
        responses:
          200:
            description: OK
            schema:
              type: array
              items:
                $ref: '#/definitions/osd'
        """
        return api_helper.ceph_osd_list(reqargs.get("limit", None))

    @RequestParser(
        [
            {
                "name": "node",
                "required": True,
                "helptext": "A valid node must be specified.",
            },
            {
                "name": "device",
                "required": True,
                "helptext": "A valid device or detect string must be specified.",
            },
            {
                "name": "weight",
                "required": True,
                "helptext": "An OSD weight must be specified.",
            },
            {
                "name": "ext_db_ratio",
                "required": False,
            },
            {
                "name": "ext_db_size",
                "required": False,
            },
            {
                "name": "osd_count",
                "required": False,
            },
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Add a Ceph OSD to the cluster
        Note: This task may take up to 60s to complete and return
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: node
            type: string
            required: true
            description: The PVC node to create the OSD on
          - in: query
            name: device
            type: string
            required: true
            description: The block device (e.g. "/dev/sdb", "/dev/disk/by-path/...", etc.) or detect string ("detect:NAME:SIZE:ID") to create the OSD on
          - in: query
            name: weight
            type: number
            required: true
            description: The Ceph CRUSH weight for the OSD
          - in: query
            name: ext_db_ratio
            type: float
            required: false
            description: If set, creates an OSD DB LV with this decimal ratio of DB to total OSD size (usually 0.05 i.e. 5%); mutually exclusive with ext_db_size
          - in: query
            name: ext_db_size
            type: float
            required: false
            description: If set, creates an OSD DB LV with this explicit size in human units (e.g. 1024M, 20G); mutually exclusive with ext_db_ratio
          - in: query
            name: osd_count
            type: integer
            required: false
            description: If set, create this many OSDs on the block device instead of 1; usually 2 or 4 depending on size
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        node = reqargs.get("node", None)

        task = run_celery_task(
            "osd.add",
            device=reqargs.get("device", None),
            weight=reqargs.get("weight", None),
            ext_db_ratio=reqargs.get("ext_db_ratio", None),
            ext_db_size=reqargs.get("ext_db_size", None),
            split_count=reqargs.get("osd_count", None),
            run_on=node,
        )

        return (
            {"task_id": task.id, "task_name": "osd.add", "run_on": node},
            202,
            {"Location": Api.url_for(api, API_Tasks_Element, task_id=task.id)},
        )


api.add_resource(API_Storage_Ceph_OSD_Root, "/storage/ceph/osd")


# /storage/ceph/osd/<osdid>
class API_Storage_Ceph_OSD_Element(Resource):
    @Authenticator
    def get(self, osdid):
        """
        Return information about Ceph OSD {osdid}
        ---
        tags:
          - storage / ceph
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/osd'
        """
        return api_helper.ceph_osd_list(osdid)

    @RequestParser(
        [
            {
                "name": "new_device",
                "required": True,
                "helptext": "A valid device or detect string must be specified.",
            },
            {
                "name": "old_device",
                "required": False,
            },
            {
                "name": "weight",
                "required": False,
            },
            {
                "name": "ext_db_ratio",
                "required": False,
            },
            {
                "name": "ext_db_size",
                "required": False,
            },
            {
                "name": "yes-i-really-mean-it",
                "required": True,
                "helptext": "Please confirm that 'yes-i-really-mean-it'.",
            },
        ]
    )
    @Authenticator
    def post(self, osdid, reqargs):
        """
        Replace a Ceph OSD in the cluster
        Note: This task may take up to 30s to complete and return
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: new_device
            type: string
            required: true
            description: The block device (e.g. "/dev/sdb", "/dev/disk/by-path/...", etc.) or detect string ("detect:NAME:SIZE:ID") to replace the OSD onto
          - in: query
            name: old_device
            type: string
            required: false
            description: The block device (e.g. "/dev/sdb", "/dev/disk/by-path/...", etc.) or detect string ("detect:NAME:SIZE:ID") of the original OSD
          - in: query
            name: weight
            type: number
            required: false
            description: The Ceph CRUSH weight for the replacement OSD
          - in: query
            name: ext_db_ratio
            type: float
            required: false
            description: If set, creates an OSD DB LV for the replcement OSD with this decimal ratio of DB to total OSD size (usually 0.05 i.e. 5%); if unset, use existing ext_db_size
          - in: query
            name: ext_db_size
            type: float
            required: false
            description: If set, creates an OSD DB LV for the replacement OSD with this explicit size in human units (e.g. 1024M, 20G); if unset, use existing ext_db_size
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        osd_node_detail, retcode = api_helper.ceph_osd_node(osdid)
        if retcode == 200:
            node = osd_node_detail["node"]
        else:
            return osd_node_detail, retcode

        task = run_celery_task(
            "osd.replace",
            osd_id=osdid,
            new_device=reqargs.get("new_device"),
            old_device=reqargs.get("old_device", None),
            weight=reqargs.get("weight", None),
            ext_db_ratio=reqargs.get("ext_db_ratio", None),
            ext_db_size=reqargs.get("ext_db_size", None),
            run_on=node,
        )

        return (
            {"task_id": task.id, "task_name": "osd.replace", "run_on": node},
            202,
            {"Location": Api.url_for(api, API_Tasks_Element, task_id=task.id)},
        )

    @RequestParser(
        [
            {
                "name": "device",
                "required": True,
                "helptext": "A valid device or detect string must be specified.",
            },
        ]
    )
    @Authenticator
    def put(self, osdid, reqargs):
        """
        Refresh (reimport) a Ceph OSD in the cluster
        Note: This task may take up to 30s to complete and return
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: device
            type: string
            required: true
            description: The block device (e.g. "/dev/sdb", "/dev/disk/by-path/...", etc.) or detect string ("detect:NAME:SIZE:ID") that the OSD should be using
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        osd_node_detail, retcode = api_helper.ceph_osd_node(osdid)
        if retcode == 200:
            node = osd_node_detail["node"]
        else:
            return osd_node_detail, retcode

        task = run_celery_task(
            "osd.refresh",
            osd_id=osdid,
            device=reqargs.get("device", None),
            ext_db_flag=False,
            run_on=node,
        )

        return (
            {"task_id": task.id, "task_name": "osd.refresh", "run_on": node},
            202,
            {"Location": Api.url_for(api, API_Tasks_Element, task_id=task.id)},
        )

    @RequestParser(
        [
            {
                "name": "force",
                "required": False,
                "helptext": "Force removal even if steps fail.",
            },
            {
                "name": "yes-i-really-mean-it",
                "required": True,
                "helptext": "Please confirm that 'yes-i-really-mean-it'.",
            },
        ]
    )
    @Authenticator
    def delete(self, osdid, reqargs):
        """
        Remove Ceph OSD {osdid}
        Note: This task may take up to 30s to complete and return
        Warning: This operation may have unintended consequences for the storage cluster; ensure the cluster can support removing the OSD before proceeding
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: force
            type: boolean
            required: flase
            description: Force removal even if some step(s) fail
          - in: query
            name: yes-i-really-mean-it
            type: string
            required: true
            description: A confirmation string to ensure that the API consumer really means it
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        osd_node_detail, retcode = api_helper.ceph_osd_node(osdid)
        if retcode == 200:
            node = osd_node_detail["node"]
        else:
            return osd_node_detail, retcode

        task = run_celery_task(
            "osd.remove",
            osd_id=osdid,
            force_flag=reqargs.get("force", False),
            run_on=node,
        )

        return (
            {"task_id": task.id, "task_name": "osd.remove", "run_on": node},
            202,
            {"Location": Api.url_for(api, API_Tasks_Element, task_id=task.id)},
        )


api.add_resource(API_Storage_Ceph_OSD_Element, "/storage/ceph/osd/<osdid>")


# /storage/ceph/osd/<osdid>/state
class API_Storage_Ceph_OSD_State(Resource):
    @Authenticator
    def get(self, osdid):
        """
        Return the current state of OSD {osdid}
        ---
        tags:
          - storage / ceph
        responses:
          200:
            description: OK
            schema:
              type: object
              properties:
                state:
                  type: string
                  description: The current OSD state
        """
        return api_helper.ceph_osd_state(osdid)

    @RequestParser(
        [
            {
                "name": "state",
                "choices": ("in", "out"),
                "required": True,
                "helptext": "A valid state must be specified.",
            },
        ]
    )
    @Authenticator
    def post(self, osdid, reqargs):
        """
        Set the current state of OSD {osdid}
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: state
            type: string
            required: true
            description: Set the OSD to this state
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
        """
        if reqargs.get("state", None) == "in":
            return api_helper.ceph_osd_in(osdid)
        if reqargs.get("state", None) == "out":
            return api_helper.ceph_osd_out(osdid)
        abort(400)


api.add_resource(API_Storage_Ceph_OSD_State, "/storage/ceph/osd/<osdid>/state")


# /storage/ceph/pool
class API_Storage_Ceph_Pool_Root(Resource):
    @RequestParser([{"name": "limit"}])
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of pools in the cluster
        ---
        tags:
          - storage / ceph
        definitions:
          - schema:
              type: object
              id: pool
              properties:
                name:
                  type: string
                  description: The name of the pool
                volume_count:
                  type: integer
                  description: The number of volumes in the pool
                tier:
                  type: string
                  description: The device class/tier of the pool
                pgs:
                  type: integer
                  description: The number of PGs (placement groups) for the pool
                stats:
                  type: object
                  properties:
                    id:
                      type: integer
                      description: The Ceph pool ID
                    stored_bytes:
                      type: integer
                      description: The stored data size (in bytes, post-replicas)
                    free_bytes:
                      type: integer
                      description: The total free space (in bytes. post-replicas)
                    used_bytes:
                      type: integer
                      description: The total used space (in bytes, pre-replicas)
                    used_percent:
                      type: number
                      description: The ratio of used space to free space
                    num_objects:
                      type: integer
                      description: The number of Ceph objects before replication
                    num_object_clones:
                      type: integer
                      description: The total number of cloned Ceph objects
                    num_object_copies:
                      type: integer
                      description: The total number of Ceph objects after replication
                    num_objects_missing_on_primary:
                      type: integer
                      description: The total number of missing-on-primary Ceph objects
                    num_objects_unfound:
                      type: integer
                      description: The total number of unfound Ceph objects
                    num_objects_degraded:
                      type: integer
                      description: The total number of degraded Ceph objects
                    read_ops:
                      type: integer
                      description: The total read operations on the pool (pool-lifetime)
                    read_bytes:
                      type: integer
                      description: The total read bytes on the pool (pool-lifetime)
                    write_ops:
                      type: integer
                      description: The total write operations on the pool (pool-lifetime)
                    write_bytes:
                      type: integer
                      description: The total write bytes on the pool (pool-lifetime)
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: A pool name search limit; fuzzy by default, use ^/$ to force exact matches
        responses:
          200:
            description: OK
            schema:
              type: array
              items:
                $ref: '#/definitions/pool'
        """
        return api_helper.ceph_pool_list(reqargs.get("limit", None))

    @RequestParser(
        [
            {
                "name": "pool",
                "required": True,
                "helptext": "A pool name must be specified.",
            },
            {
                "name": "pgs",
                "required": True,
                "helptext": "A placement group count must be specified.",
            },
            {
                "name": "replcfg",
                "required": True,
                "helptext": "A valid replication configuration must be specified.",
            },
            {
                "name": "tier",
                "required": False,
                "choices": ("hdd", "ssd", "nvme", "default"),
                "helptext": "A valid tier must be specified",
            },
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Create a new Ceph pool
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: pool
            type: string
            required: true
            description: The name of the pool
          - in: query
            name: pgs
            type: integer
            required: true
            description: The number of placement groups (PGs) for the pool
          - in: query
            name: replcfg
            type: string
            required: true
            description: The replication configuration (e.g. "copies=3,mincopies=2") for the pool
          - in: query
            name: tier
            required: false
            description: The device tier for the pool (hdd, ssd, nvme, or default)
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_helper.ceph_pool_add(
            reqargs.get("pool", None),
            reqargs.get("pgs", None),
            reqargs.get("replcfg", None),
            reqargs.get("tier", None),
        )


api.add_resource(API_Storage_Ceph_Pool_Root, "/storage/ceph/pool")


# /storage/ceph/pool/<pool>
class API_Storage_Ceph_Pool_Element(Resource):
    @Authenticator
    def get(self, pool):
        """
        Return information about {pool}
        ---
        tags:
          - storage / ceph
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/pool'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.ceph_pool_list(pool, is_fuzzy=False)

    @RequestParser(
        [
            {
                "name": "pgs",
                "required": True,
                "helptext": "A placement group count must be specified.",
            },
            {
                "name": "replcfg",
                "required": True,
                "helptext": "A valid replication configuration must be specified.",
            },
            {
                "name": "tier",
                "required": False,
                "choices": ("hdd", "ssd", "nvme", "default"),
                "helptext": "A valid tier must be specified",
            },
        ]
    )
    @Authenticator
    def post(self, pool, reqargs):
        """
        Create a new Ceph pool {pool}
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: pgs
            type: integer
            required: true
            description: The number of placement groups (PGs) for the pool
          - in: query
            name: replcfg
            type: string
            required: true
            description: The replication configuration (e.g. "copies=3,mincopies=2") for the pool
          - in: query
            name: tier
            required: false
            description: The device tier for the pool (hdd, ssd, nvme, or default)
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_helper.ceph_pool_add(
            pool,
            reqargs.get("pgs", None),
            reqargs.get("replcfg", None),
            reqargs.get("tier", None),
        )

    @RequestParser(
        [
            {
                "name": "pgs",
                "required": True,
                "helptext": "A placement group count must be specified.",
            },
        ]
    )
    @Authenticator
    def put(self, pool, reqargs):
        """
        Adjust Ceph pool {pool}'s placement group count
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: pgs
            type: integer
            required: true
            description: The new number of placement groups (PGs) for the pool
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_helper.ceph_pool_set_pgs(
            pool,
            reqargs.get("pgs", 0),
        )

    @RequestParser(
        [
            {
                "name": "yes-i-really-mean-it",
                "required": True,
                "helptext": "Please confirm that 'yes-i-really-mean-it'.",
            }
        ]
    )
    @Authenticator
    def delete(self, pool, reqargs):
        """
        Remove Ceph pool {pool}
        Note: This task may take up to 30s to complete and return
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: yes-i-really-mean-it
            type: string
            required: true
            description: A confirmation string to ensure that the API consumer really means it
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_helper.ceph_pool_remove(pool)


api.add_resource(API_Storage_Ceph_Pool_Element, "/storage/ceph/pool/<pool>")


# /storage/ceph/volume
class API_Storage_Ceph_Volume_Root(Resource):
    @RequestParser([{"name": "limit"}, {"name": "pool"}])
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of volumes in the cluster
        ---
        tags:
          - storage / ceph
        definitions:
          - schema:
              type: object
              id: volume
              properties:
                name:
                  type: string
                  description: The name of the volume
                pool:
                  type: string
                  description: The name of the pool containing the volume
                stats:
                  type: object
                  properties:
                    name:
                      type: string
                      description: The name of the volume
                    id:
                      type: string
                      description: The Ceph volume ID
                    size:
                      type: string
                      description: The size of the volume (human-readable values)
                    objects:
                      type: integer
                      description: The number of Ceph objects making up the volume
                    order:
                      type: integer
                      description: The Ceph volume order ID
                    object_size:
                      type: integer
                      description: The size of each object in bytes
                    snapshot_count:
                      type: integer
                      description: The number of snapshots of the volume
                    block_name_prefix:
                      type: string
                      description: The Ceph-internal block name prefix
                    format:
                      type: integer
                      description: The Ceph RBD volume format
                    features:
                      type: array
                      items:
                        type: string
                        description: The Ceph RBD feature
                    op_features:
                      type: array
                      items:
                        type: string
                        description: The Ceph RBD operational features
                    flags:
                      type: array
                      items:
                        type: string
                        description: The Ceph RBD volume flags
                    create_timestamp:
                      type: string
                      description: The volume creation timestamp
                    access_timestamp:
                      type: string
                      description: The volume access timestamp
                    modify_timestamp:
                      type: string
                      description: The volume modification timestamp
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: A volume name search limit; fuzzy by default, use ^/$ to force exact matches
          - in: query
            name: pool
            type: string
            required: false
            description: A pool to limit the search to
        responses:
          200:
            description: OK
            schema:
              type: array
              items:
                $ref: '#/definitions/volume'
        """
        return api_helper.ceph_volume_list(
            reqargs.get("pool", None), reqargs.get("limit", None)
        )

    @RequestParser(
        [
            {
                "name": "volume",
                "required": True,
                "helptext": "A volume name must be specified.",
            },
            {
                "name": "pool",
                "required": True,
                "helptext": "A valid pool name must be specified.",
            },
            {
                "name": "size",
                "required": True,
                "helptext": "A volume size in bytes (B implied or with SI suffix k/M/G/T) must be specified.",
            },
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Create a new Ceph volume
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: volume
            type: string
            required: true
            description: The name of the volume
          - in: query
            name: pool
            type: integer
            required: true
            description: The name of the pool to contain the volume
          - in: query
            name: size
            type: string
            required: true
            description: The volume size, in bytes (B implied) or with a single-character SI suffix (k/M/G/T)
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_helper.ceph_volume_add(
            reqargs.get("pool", None),
            reqargs.get("volume", None),
            reqargs.get("size", None),
        )


api.add_resource(API_Storage_Ceph_Volume_Root, "/storage/ceph/volume")


# /storage/ceph/volume/<pool>/<volume>
class API_Storage_Ceph_Volume_Element(Resource):
    @Authenticator
    def get(self, pool, volume):
        """
        Return information about volume {volume} in pool {pool}
        ---
        tags:
          - storage / ceph
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/volume'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.ceph_volume_list(pool, volume, is_fuzzy=False)

    @RequestParser(
        [
            {
                "name": "size",
                "required": True,
                "helptext": "A volume size in bytes (or with k/M/G/T suffix) must be specified.",
            }
        ]
    )
    @Authenticator
    def post(self, pool, volume, reqargs):
        """
        Create a new Ceph volume {volume} in pool {pool}
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: size
            type: string
            required: true
            description: The volume size in bytes (or with a metric suffix, i.e. k/M/G/T)
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_helper.ceph_volume_add(pool, volume, reqargs.get("size", None))

    @RequestParser([{"name": "new_size"}, {"name": "new_name"}])
    @Authenticator
    def put(self, pool, volume, reqargs):
        """
        Update the size or name of Ceph volume {volume} in pool {pool}
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: size
            type: string
            required: false
            description: The new volume size in bytes (or with a metric suffix, i.e. k/M/G/T); must be greater than the previous size (shrinking not supported)
          - in: query
            name: new_name
            type: string
            required: false
            description: The new volume name
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        if reqargs.get("new_size", None) and reqargs.get("new_name", None):
            return {"message": "Can only perform one modification at once"}, 400

        if reqargs.get("new_size", None):
            return api_helper.ceph_volume_resize(pool, volume, reqargs.get("new_size"))
        if reqargs.get("new_name", None):
            return api_helper.ceph_volume_rename(pool, volume, reqargs.get("new_name"))
        return {"message": "At least one modification must be specified"}, 400

    @Authenticator
    def delete(self, pool, volume):
        """
        Remove Ceph volume {volume} from pool {pool}
        Note: This task may take up to 30s to complete and return depending on the size of the volume
        ---
        tags:
          - storage / ceph
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.ceph_volume_remove(pool, volume)


api.add_resource(
    API_Storage_Ceph_Volume_Element, "/storage/ceph/volume/<pool>/<volume>"
)


# /storage/ceph/volume/<pool>/<volume>/clone
class API_Storage_Ceph_Volume_Element_Clone(Resource):
    @RequestParser(
        [
            {
                "name": "new_volume",
                "required": True,
                "helptext": "A new volume name must be specified.",
            }
        ]
    )
    @Authenticator
    def post(self, pool, volume, reqargs):
        """
        Clone Ceph volume {volume} in pool {pool}
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: new_volume
            type: string
            required: true
            description: The name of the new cloned volume
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_helper.ceph_volume_clone(
            pool, reqargs.get("new_volume", None), volume
        )


api.add_resource(
    API_Storage_Ceph_Volume_Element_Clone, "/storage/ceph/volume/<pool>/<volume>/clone"
)


# /storage/ceph/volume/<pool>/<volume>/upload
class API_Storage_Ceph_Volume_Element_Upload(Resource):
    @RequestParser(
        [
            {
                "name": "image_format",
                "required": True,
                "location": ["args"],
                "helptext": "A source image format must be specified.",
            },
            {
                "name": "file_size",
                "required": False,
                "location": ["args"],
            },
        ]
    )
    @Authenticator
    def post(self, pool, volume, reqargs):
        """
        Upload a disk image to Ceph volume {volume} in pool {pool}

        The body must be a form body containing a file that is the binary contents of the image.
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: image_format
            type: string
            required: true
            description: The type of source image file
            enum:
              - raw
              - vmdk
              - qcow2
              - qed
              - vdi
              - vpc
          - in: query
            name: file_size
            type: integer
            required: false
            description: The size of the image file, in bytes, if {image_format} is not "raw"
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_helper.ceph_volume_upload(
            pool,
            volume,
            reqargs.get("image_format", None),
            reqargs.get("file_size", None),
        )


api.add_resource(
    API_Storage_Ceph_Volume_Element_Upload,
    "/storage/ceph/volume/<pool>/<volume>/upload",
)


# /storage/ceph/snapshot
class API_Storage_Ceph_Snapshot_Root(Resource):
    @RequestParser(
        [
            {"name": "pool"},
            {"name": "volume"},
            {"name": "limit"},
        ]
    )
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of snapshots in the cluster
        ---
        tags:
          - storage / ceph
        definitions:
          - schema:
              type: object
              id: snapshot
              properties:
                snapshot:
                  type: string
                  description: The name of the snapshot
                volume:
                  type: string
                  description: The name of the volume
                pool:
                  type: string
                  description: The name of the pool
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: A volume name search limit; fuzzy by default, use ^/$ to force exact matches
          - in: query
            name: pool
            type: string
            required: false
            description: A pool to limit the search to
          - in: query
            name: volume
            type: string
            required: false
            description: A volume to limit the search to
        responses:
          200:
            description: OK
            schema:
              type: array
              items:
                $ref: '#/definitions/snapshot'
        """
        return api_helper.ceph_volume_snapshot_list(
            reqargs.get("pool", None),
            reqargs.get("volume", None),
            reqargs.get("limit", None),
        )

    @RequestParser(
        [
            {
                "name": "snapshot",
                "required": True,
                "helptext": "A snapshot name must be specified.",
            },
            {
                "name": "volume",
                "required": True,
                "helptext": "A volume name must be specified.",
            },
            {
                "name": "pool",
                "required": True,
                "helptext": "A pool name must be specified.",
            },
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Create a new Ceph snapshot
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: snapshot
            type: string
            required: true
            description: The name of the snapshot
          - in: query
            name: volume
            type: string
            required: true
            description: The name of the volume
          - in: query
            name: pool
            type: integer
            required: true
            description: The name of the pool
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_helper.ceph_volume_snapshot_add(
            reqargs.get("pool", None),
            reqargs.get("volume", None),
            reqargs.get("snapshot", None),
        )


api.add_resource(API_Storage_Ceph_Snapshot_Root, "/storage/ceph/snapshot")


# /storage/ceph/snapshot/<pool>/<volume>/<snapshot>
class API_Storage_Ceph_Snapshot_Element(Resource):
    @Authenticator
    def get(self, pool, volume, snapshot):
        """
        Return information about snapshot {snapshot} of volume {volume} in pool {pool}
        ---
        tags:
          - storage / ceph
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/snapshot'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.ceph_volume_snapshot_list(
            pool, volume, snapshot, is_fuzzy=False
        )

    @Authenticator
    def post(self, pool, volume, snapshot):
        """
        Create a new Ceph snapshot {snapshot} of volume {volume} in pool {pool}
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: snapshot
            type: string
            required: true
            description: The name of the snapshot
          - in: query
            name: volume
            type: string
            required: true
            description: The name of the volume
          - in: query
            name: pool
            type: integer
            required: true
            description: The name of the pool
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_helper.ceph_volume_snapshot_add(pool, volume, snapshot)

    @RequestParser(
        [
            {
                "name": "new_name",
                "required": True,
                "helptext": "A new name must be specified.",
            }
        ]
    )
    @Authenticator
    def put(self, pool, volume, snapshot, reqargs):
        """
        Update the name of Ceph snapshot {snapshot} of volume {volume} in pool {pool}
        ---
        tags:
          - storage / ceph
        parameters:
          - in: query
            name: new_name
            type: string
            required: false
            description: The new snaoshot name
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_helper.ceph_volume_snapshot_rename(
            pool, volume, snapshot, reqargs.get("new_name", None)
        )

    @Authenticator
    def delete(self, pool, volume, snapshot):
        """
        Remove Ceph snapshot {snapshot} of volume {volume} from pool {pool}
        Note: This task may take up to 30s to complete and return depending on the size of the snapshot
        ---
        tags:
          - storage / ceph
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_helper.ceph_volume_snapshot_remove(pool, volume, snapshot)


api.add_resource(
    API_Storage_Ceph_Snapshot_Element,
    "/storage/ceph/snapshot/<pool>/<volume>/<snapshot>",
)


##########################################################
# Provisioner API
##########################################################


# /provisioner
class API_Provisioner_Root(Resource):
    @Authenticator
    def get(self):
        """
        Unused endpoint
        """
        abort(404)


api.add_resource(API_Provisioner_Root, "/provisioner")


# /provisioner/template
class API_Provisioner_Template_Root(Resource):
    @RequestParser([{"name": "limit"}])
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of all templates
        ---
        tags:
          - provisioner / template
        definitions:
          - schema:
              type: object
              id: all-templates
              properties:
                system-templates:
                  type: array
                  items:
                    $ref: '#/definitions/system-template'
                network-templates:
                  type: array
                  items:
                    $ref: '#/definitions/network-template'
                storage-templates:
                  type: array
                  items:
                    $ref: '#/definitions/storage-template'
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: A template name search limit; fuzzy by default, use ^/$ to force exact matches
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/all-templates'
        """
        return api_provisioner.template_list(reqargs.get("limit", None))


api.add_resource(API_Provisioner_Template_Root, "/provisioner/template")


# /provisioner/template/system
class API_Provisioner_Template_System_Root(Resource):
    @RequestParser([{"name": "limit"}])
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of system templates
        ---
        tags:
          - provisioner / template
        definitions:
          - schema:
              type: object
              id: system-template
              properties:
                id:
                  type: integer
                  description: Internal provisioner template ID
                name:
                  type: string
                  description: Template name
                vcpu_count:
                  type: integer
                  description: vCPU count for VM
                vram_mb:
                  type: integer
                  description: vRAM size in MB for VM
                serial:
                  type: boolean
                  description: Whether to enable serial console for VM
                vnc:
                  type: boolean
                  description: Whether to enable VNC console for VM
                vnc_bind:
                  type: string
                  description: VNC bind address when VNC console is enabled
                node_limit:
                  type: string
                  description: CSV list of node(s) to limit VM assignment to
                node_selector:
                  type: string
                  description: Selector to use for VM node assignment on migration/move
                node_autostart:
                  type: boolean
                  description: Whether to start VM with node ready state (one-time)
                migration_method:
                  type: string
                  description: The preferred migration method (live, shutdown, none)
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: A template name search limit; fuzzy by default, use ^/$ to force exact matches
        responses:
          200:
            description: OK
            schema:
              type: list
              items:
                $ref: '#/definitions/system-template'
        """
        return api_provisioner.list_template_system(reqargs.get("limit", None))

    @RequestParser(
        [
            {"name": "name", "required": True, "helptext": "A name must be specified."},
            {
                "name": "vcpus",
                "required": True,
                "helptext": "A vcpus value must be specified.",
            },
            {
                "name": "vram",
                "required": True,
                "helptext": "A vram value in MB must be specified.",
            },
            {
                "name": "serial",
                "required": True,
                "helptext": "A serial value must be specified.",
            },
            {
                "name": "vnc",
                "required": True,
                "helptext": "A vnc value must be specified.",
            },
            {"name": "vnc_bind"},
            {"name": "node_limit"},
            {"name": "node_selector"},
            {"name": "node_autostart"},
            {"name": "migration_method"},
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Create a new system template
        ---
        tags:
          - provisioner / template
        parameters:
          - in: query
            name: name
            type: string
            required: true
            description: Template name
          - in: query
            name: vcpus
            type: integer
            required: true
            description: vCPU count for VM
          - in: query
            name: vram
            type: integer
            required: true
            description: vRAM size in MB for VM
          - in: query
            name: serial
            type: boolean
            required: true
            description: Whether to enable serial console for VM
          - in: query
            name: vnc
            type: boolean
            required: true
            description: Whether to enable VNC console for VM
          - in: query
            name: vnc_bind
            type: string
            required: false
            description: VNC bind address when VNC console is enabled
          - in: query
            name: node_limit
            type: string
            required: false
            description: CSV list of node(s) to limit VM assignment to
          - in: query
            name: node_selector
            type: string
            required: false
            description: Selector to use for VM node assignment on migration/move
          - in: query
            name: node_autostart
            type: boolean
            required: false
            description: Whether to start VM with node ready state (one-time)
          - in: query
            name: migration_method
            type: string
            required: false
            description: The preferred migration method (live, shutdown, none)
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        # Validate arguments
        try:
            vcpus = int(reqargs.get("vcpus"))
        except Exception:
            return {"message": "A vcpus value must be an integer"}, 400
        try:
            vram = int(reqargs.get("vram"))
        except Exception:
            return {"message": "A vram value must be an integer"}, 400
        # Cast boolean arguments
        if bool(strtobool(reqargs.get("serial", "false"))):
            serial = True
        else:
            serial = False
        if bool(strtobool(reqargs.get("vnc", "false"))):
            vnc = True
            vnc_bind = reqargs.get("vnc_bind", None)
        else:
            vnc = False
            vnc_bind = None
        if reqargs.get("node_autostart", None) and bool(
            strtobool(reqargs.get("node_autostart", "false"))
        ):
            node_autostart = True
        else:
            node_autostart = False

        return api_provisioner.create_template_system(
            reqargs.get("name"),
            vcpus,
            vram,
            serial,
            vnc,
            vnc_bind,
            reqargs.get("node_limit", None),
            reqargs.get("node_selector", None),
            node_autostart,
            reqargs.get("migration_method", None),
        )


api.add_resource(API_Provisioner_Template_System_Root, "/provisioner/template/system")


# /provisioner/template/system/<template>
class API_Provisioner_Template_System_Element(Resource):
    @Authenticator
    def get(self, template):
        """
        Return information about system template {template}
        ---
        tags:
          - provisioner / template
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/system-template'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_provisioner.list_template_system(template, is_fuzzy=False)

    @RequestParser(
        [
            {
                "name": "vcpus",
                "required": True,
                "helptext": "A vcpus value must be specified.",
            },
            {
                "name": "vram",
                "required": True,
                "helptext": "A vram value in MB must be specified.",
            },
            {
                "name": "serial",
                "required": True,
                "helptext": "A serial value must be specified.",
            },
            {
                "name": "vnc",
                "required": True,
                "helptext": "A vnc value must be specified.",
            },
            {"name": "vnc_bind"},
            {"name": "node_limit"},
            {"name": "node_selector"},
            {"name": "node_autostart"},
            {"name": "migration_method"},
        ]
    )
    @Authenticator
    def post(self, template, reqargs):
        """
        Create a new system template {template}
        ---
        tags:
          - provisioner / template
        parameters:
          - in: query
            name: vcpus
            type: integer
            required: true
            description: vCPU count for VM
          - in: query
            name: vram
            type: integer
            required: true
            description: vRAM size in MB for VM
          - in: query
            name: serial
            type: boolean
            required: true
            description: Whether to enable serial console for VM
          - in: query
            name: vnc
            type: boolean
            required: true
            description: Whether to enable VNC console for VM
          - in: query
            name: vnc_bind
            type: string
            required: false
            description: VNC bind address when VNC console is enabled
          - in: query
            name: node_limit
            type: string
            required: false
            description: CSV list of node(s) to limit VM assignment to
          - in: query
            name: node_selector
            type: string
            required: false
            description: Selector to use for VM node assignment on migration/move
          - in: query
            name: node_autostart
            type: boolean
            required: false
            description: Whether to start VM with node ready state (one-time)
          - in: query
            name: migration_method
            type: string
            required: false
            description: The preferred migration method (live, shutdown, none)
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        # Validate arguments
        try:
            vcpus = int(reqargs.get("vcpus"))
        except Exception:
            return {"message": "A vcpus value must be an integer"}, 400
        try:
            vram = int(reqargs.get("vram"))
        except Exception:
            return {"message": "A vram value must be an integer"}, 400
        # Cast boolean arguments
        if bool(strtobool(reqargs.get("serial", False))):
            serial = True
        else:
            serial = False
        if bool(strtobool(reqargs.get("vnc", False))):
            vnc = True
            vnc_bind = reqargs.get("vnc_bind", None)
        else:
            vnc = False
            vnc_bind = None
        if reqargs.get("node_autostart", None) and bool(
            strtobool(reqargs.get("node_autostart", False))
        ):
            node_autostart = True
        else:
            node_autostart = False

        return api_provisioner.create_template_system(
            template,
            vcpus,
            vram,
            serial,
            vnc,
            vnc_bind,
            reqargs.get("node_limit", None),
            reqargs.get("node_selector", None),
            node_autostart,
            reqargs.get("migration_method", None),
        )

    @RequestParser(
        [
            {"name": "vcpus"},
            {"name": "vram"},
            {"name": "serial"},
            {"name": "vnc"},
            {"name": "vnc_bind"},
            {"name": "node_limit"},
            {"name": "node_selector"},
            {"name": "node_autostart"},
            {"name": "migration_method"},
        ]
    )
    @Authenticator
    def put(self, template, reqargs):
        """
        Modify an existing system template {template}
        ---
        tags:
          - provisioner / template
        parameters:
          - in: query
            name: vcpus
            type: integer
            description: vCPU count for VM
          - in: query
            name: vram
            type: integer
            description: vRAM size in MB for VM
          - in: query
            name: serial
            type: boolean
            description: Whether to enable serial console for VM
          - in: query
            name: vnc
            type: boolean
            description: Whether to enable VNC console for VM
          - in: query
            name: vnc_bind
            type: string
            description: VNC bind address when VNC console is enabled
          - in: query
            name: node_limit
            type: string
            description: CSV list of node(s) to limit VM assignment to
          - in: query
            name: node_selector
            type: string
            description: Selector to use for VM node assignment on migration/move
          - in: query
            name: node_autostart
            type: boolean
            description: Whether to start VM with node ready state (one-time)
          - in: query
            name: migration_method
            type: string
            description: The preferred migration method (live, shutdown, none)
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.modify_template_system(
            template,
            reqargs.get("vcpus", None),
            reqargs.get("vram", None),
            reqargs.get("serial", None),
            reqargs.get("vnc", None),
            reqargs.get("vnc_bind"),
            reqargs.get("node_limit", None),
            reqargs.get("node_selector", None),
            reqargs.get("node_autostart", None),
            reqargs.get("migration_method", None),
        )

    @Authenticator
    def delete(self, template):
        """
        Remove system template {template}
        ---
        tags:
          - provisioner / template
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_provisioner.delete_template_system(template)


api.add_resource(
    API_Provisioner_Template_System_Element, "/provisioner/template/system/<template>"
)


# /provisioner/template/network
class API_Provisioner_Template_Network_Root(Resource):
    @RequestParser([{"name": "limit"}])
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of network templates
        ---
        tags:
          - provisioner / template
        definitions:
          - schema:
              type: object
              id: network-template-net
              properties:
                id:
                  type: integer
                  description: Internal provisioner template ID
                network_template:
                  type: integer
                  description: Internal provisioner network template ID
                vni:
                  type: integer
                  description: PVC network VNI
          - schema:
              type: object
              id: network-template
              properties:
                id:
                  type: integer
                  description: Internal provisioner template ID
                name:
                  type: string
                  description: Template name
                mac_template:
                  type: string
                  description: MAC address template for VM
                networks:
                  type: array
                  items:
                    $ref: '#/definitions/network-template-net'
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: A template name search limit; fuzzy by default, use ^/$ to force exact matches
        responses:
          200:
            description: OK
            schema:
              type: list
              items:
                $ref: '#/definitions/network-template'
        """
        return api_provisioner.list_template_network(reqargs.get("limit", None))

    @RequestParser(
        [
            {
                "name": "name",
                "required": True,
                "helptext": "A template name must be specified.",
            },
            {"name": "mac_template"},
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Create a new network template
        ---
        tags:
          - provisioner / template
        parameters:
          - in: query
            name: name
            type: string
            required: true
            description: Template name
          - in: query
            name: mac_template
            type: string
            required: false
            description: MAC address template
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.create_template_network(
            reqargs.get("name", None), reqargs.get("mac_template", None)
        )


api.add_resource(API_Provisioner_Template_Network_Root, "/provisioner/template/network")


# /provisioner/template/network/<template>
class API_Provisioner_Template_Network_Element(Resource):
    @Authenticator
    def get(self, template):
        """
        Return information about network template {template}
        ---
        tags:
          - provisioner / template
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/network-template'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_provisioner.list_template_network(template, is_fuzzy=False)

    @RequestParser([{"name": "mac_template"}])
    @Authenticator
    def post(self, template, reqargs):
        """
        Create a new network template {template}
        ---
        tags:
          - provisioner / template
        parameters:
          - in: query
            name: mac_template
            type: string
            required: false
            description: MAC address template
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.create_template_network(
            template, reqargs.get("mac_template", None)
        )

    @Authenticator
    def delete(self, template):
        """
        Remove network template {template}
        ---
        tags:
          - provisioner / template
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_provisioner.delete_template_network(template)


api.add_resource(
    API_Provisioner_Template_Network_Element, "/provisioner/template/network/<template>"
)


# /provisioner/template/network/<template>/net
class API_Provisioner_Template_Network_Net_Root(Resource):
    @Authenticator
    def get(self, template):
        """
        Return a list of networks in network template {template}
        ---
        tags:
          - provisioner / template
        responses:
          200:
            description: OK
            schema:
              type: list
              items:
                $ref: '#/definitions/network-template-net'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        templates = api_provisioner.list_template_network(template, is_fuzzy=False)
        if templates:
            return templates["networks"]
        else:
            return {"message": "Template not found."}, 404

    @RequestParser(
        [
            {
                "name": "vni",
                "required": True,
                "helptext": "A valid VNI must be specified.",
            }
        ]
    )
    @Authenticator
    def post(self, template, reqargs):
        """
        Create a new network in network template {template}
        ---
        tags:
          - provisioner / template
        parameters:
          - in: query
            name: vni
            type: integer
            required: false
            description: PVC network VNI
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.create_template_network_element(
            template, reqargs.get("vni", None)
        )


api.add_resource(
    API_Provisioner_Template_Network_Net_Root,
    "/provisioner/template/network/<template>/net",
)


# /provisioner/template/network/<template>/net/<vni>
class API_Provisioner_Template_Network_Net_Element(Resource):
    @Authenticator
    def get(self, template, vni):
        """
        Return information about network {vni} in network template {template}
        ---
        tags:
          - provisioner / template
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/network-template-net'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        vni_list = api_provisioner.list_template_network(template, is_fuzzy=False)[
            "networks"
        ]
        for _vni in vni_list:
            if int(_vni["vni"]) == int(vni):
                return _vni, 200
        abort(404)

    @Authenticator
    def post(self, template, vni):
        """
        Create a new network {vni} in network template {template}
        ---
        tags:
          - provisioner / template
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.create_template_network_element(template, vni)

    @Authenticator
    def delete(self, template, vni):
        """
        Remove network {vni} from network template {template}
        ---
        tags:
          - provisioner / template
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_provisioner.delete_template_network_element(template, vni)


api.add_resource(
    API_Provisioner_Template_Network_Net_Element,
    "/provisioner/template/network/<template>/net/<vni>",
)


# /provisioner/template/storage
class API_Provisioner_Template_Storage_Root(Resource):
    @RequestParser([{"name": "limit"}])
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of storage templates
        ---
        tags:
          - provisioner / template
        definitions:
          - schema:
              type: object
              id: storage-template-disk
              properties:
                id:
                  type: integer
                  description: Internal provisioner disk ID
                storage_template:
                  type: integer
                  description: Internal provisioner storage template ID
                pool:
                  type: string
                  description: Ceph storage pool for disk
                disk_id:
                  type: string
                  description: Disk identifier
                disk_size_gb:
                  type: string
                  description: Disk size in GB
                mountpoint:
                  type: string
                  description: In-VM mountpoint for disk
                filesystem:
                  type: string
                  description: Filesystem for disk
                filesystem_args:
                  type: array
                  items:
                    type: string
                    description: Filesystem mkfs arguments
          - schema:
              type: object
              id: storage-template
              properties:
                id:
                  type: integer
                  description: Internal provisioner template ID
                name:
                  type: string
                  description: Template name
                disks:
                  type: array
                  items:
                    $ref: '#/definitions/storage-template-disk'
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: A template name search limit; fuzzy by default, use ^/$ to force exact matches
        responses:
          200:
            description: OK
            schema:
              type: list
              items:
                $ref: '#/definitions/storage-template'
        """
        return api_provisioner.list_template_storage(reqargs.get("limit", None))

    @RequestParser(
        [
            {
                "name": "name",
                "required": True,
                "helptext": "A template name must be specified.",
            }
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Create a new storage template
        ---
        tags:
          - provisioner / template
        parameters:
          - in: query
            name: name
            type: string
            required: true
            description: Template name
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.create_template_storage(reqargs.get("name", None))


api.add_resource(API_Provisioner_Template_Storage_Root, "/provisioner/template/storage")


# /provisioner/template/storage/<template>
class API_Provisioner_Template_Storage_Element(Resource):
    @Authenticator
    def get(self, template):
        """
        Return information about storage template {template}
        ---
        tags:
          - provisioner / template
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/storage-template'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_provisioner.list_template_storage(template, is_fuzzy=False)

    @Authenticator
    def post(self, template):
        """
        Create a new storage template {template}
        ---
        tags:
          - provisioner / template
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.create_template_storage(template)

    @Authenticator
    def delete(self, template):
        """
        Remove storage template {template}
        ---
        tags:
          - provisioner / template
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_provisioner.delete_template_storage(template)


api.add_resource(
    API_Provisioner_Template_Storage_Element, "/provisioner/template/storage/<template>"
)


# /provisioner/template/storage/<template>/disk
class API_Provisioner_Template_Storage_Disk_Root(Resource):
    @RequestParser([{"name": "limit"}])
    @Authenticator
    def get(self, template, reqargs):
        """
        Return a list of disks in network template {template}
        ---
        tags:
          - provisioner / template
        responses:
          200:
            description: OK
            schema:
              type: list
              items:
                $ref: '#/definitions/storage-template-disk'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        templates = api_provisioner.list_template_storage(template, is_fuzzy=False)
        if templates:
            return templates["disks"]
        else:
            return {"message": "Template not found."}, 404

    @RequestParser(
        [
            {
                "name": "disk_id",
                "required": True,
                "helptext": "A disk identifier in sdX or vdX format must be specified.",
            },
            {
                "name": "pool",
                "required": True,
                "helptext": "A storage pool must be specified.",
            },
            {"name": "source_volume"},
            {"name": "disk_size"},
            {"name": "filesystem"},
            {"name": "filesystem_arg", "action": "append"},
            {"name": "mountpoint"},
        ]
    )
    @Authenticator
    def post(self, template, reqargs):
        """
        Create a new disk in storage template {template}
        ---
        tags:
          - provisioner / template
        parameters:
          - in: query
            name: disk_id
            type: string
            required: true
            description: Disk identifier in "sdX"/"vdX" format (e.g. "sda", "vdb", etc.)
          - in: query
            name: pool
            type: string
            required: true
            description: ceph storage pool for disk
          - in: query
            name: source_volume
            type: string
            required: false
            description: Source storage volume; not compatible with other options
          - in: query
            name: disk_size
            type: integer
            required: false
            description: Disk size in GB; not compatible with source_volume
          - in: query
            name: filesystem
            type: string
            required: false
            description: Filesystem for disk; not compatible with source_volume
          - in: query
            name: filesystem_arg
            type: string
            required: false
            description: Filesystem mkfs argument in "-X=foo" format; may be specified multiple times to add multiple arguments
          - in: query
            name: mountpoint
            type: string
            required: false
            description: In-VM mountpoint for disk; not compatible with source_volume
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.create_template_storage_element(
            template,
            reqargs.get("disk_id", None),
            reqargs.get("pool", None),
            reqargs.get("source_volume", None),
            reqargs.get("disk_size", None),
            reqargs.get("filesystem", None),
            reqargs.get("filesystem_arg", []),
            reqargs.get("mountpoint", None),
        )


api.add_resource(
    API_Provisioner_Template_Storage_Disk_Root,
    "/provisioner/template/storage/<template>/disk",
)


# /provisioner/template/storage/<template>/disk/<disk_id>
class API_Provisioner_Template_Storage_Disk_Element(Resource):
    @Authenticator
    def get(self, template, disk_id):
        """
        Return information about disk {disk_id} in storage template {template}
        ---
        tags:
          - provisioner / template
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/storage-template-disk'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        disk_list = api_provisioner.list_template_storage(template, is_fuzzy=False)[
            "disks"
        ]
        for _disk in disk_list:
            if _disk["disk_id"] == disk_id:
                return _disk, 200
        abort(404)

    @RequestParser(
        [
            {
                "name": "pool",
                "required": True,
                "helptext": "A storage pool must be specified.",
            },
            {"name": "source_volume"},
            {"name": "disk_size"},
            {"name": "filesystem"},
            {"name": "filesystem_arg", "action": "append"},
            {"name": "mountpoint"},
        ]
    )
    @Authenticator
    def post(self, template, disk_id, reqargs):
        """
        Create a new disk {disk_id} in storage template {template}
        Alternative to "POST /provisioner/template/storage/<template>/disk?disk_id=<disk_id>"
        ---
        tags:
          - provisioner / template
        parameters:
          - in: query
            name: pool
            type: string
            required: true
            description: ceph storage pool for disk
          - in: query
            name: source_volume
            type: string
            required: false
            description: Source storage volume; not compatible with other options
          - in: query
            name: disk_size
            type: integer
            required: false
            description: Disk size in GB; not compatible with source_volume
          - in: query
            name: filesystem
            type: string
            required: false
            description: Filesystem for disk; not compatible with source_volume
          - in: query
            name: filesystem_arg
            type: string
            required: false
            description: Filesystem mkfs argument in "-X=foo" format; may be specified multiple times to add multiple arguments
          - in: query
            name: mountpoint
            type: string
            required: false
            description: In-VM mountpoint for disk; not compatible with source_volume
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.create_template_storage_element(
            template,
            disk_id,
            reqargs.get("pool", None),
            reqargs.get("source_volume", None),
            reqargs.get("disk_size", None),
            reqargs.get("filesystem", None),
            reqargs.get("filesystem_arg", []),
            reqargs.get("mountpoint", None),
        )

    @Authenticator
    def delete(self, template, disk_id):
        """
        Remove disk {disk_id} from storage template {template}
        ---
        tags:
          - provisioner / template
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_provisioner.delete_template_storage_element(template, disk_id)


api.add_resource(
    API_Provisioner_Template_Storage_Disk_Element,
    "/provisioner/template/storage/<template>/disk/<disk_id>",
)


# /provisioner/userdata
class API_Provisioner_Userdata_Root(Resource):
    @RequestParser([{"name": "limit"}])
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of userdata documents
        ---
        tags:
          - provisioner
        definitions:
          - schema:
              type: object
              id: userdata
              properties:
                id:
                  type: integer
                  description: Internal provisioner ID
                name:
                  type: string
                  description: Userdata name
                userdata:
                  type: string
                  description: Raw userdata configuration document
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: A userdata name search limit; fuzzy by default, use ^/$ to force exact matches
        responses:
          200:
            description: OK
            schema:
              type: list
              items:
                $ref: '#/definitions/userdata'
        """
        return api_provisioner.list_userdata(reqargs.get("limit", None))

    @RequestParser(
        [
            {"name": "name", "required": True, "helptext": "A name must be specified."},
            {
                "name": "data",
                "required": True,
                "helptext": "A userdata document must be specified.",
            },
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Create a new userdata document
        ---
        tags:
          - provisioner
        parameters:
          - in: query
            name: name
            type: string
            required: true
            description: Userdata name
          - in: query
            name: data
            type: string
            required: true
            description: Raw userdata configuration document
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.create_userdata(
            reqargs.get("name", None), reqargs.get("data", None)
        )


api.add_resource(API_Provisioner_Userdata_Root, "/provisioner/userdata")


# /provisioner/userdata/<userdata>
class API_Provisioner_Userdata_Element(Resource):
    @Authenticator
    def get(self, userdata):
        """
        Return information about userdata document {userdata}
        ---
        tags:
          - provisioner
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/userdata'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_provisioner.list_userdata(userdata, is_fuzzy=False)

    @RequestParser(
        [
            {
                "name": "data",
                "required": True,
                "helptext": "A userdata document must be specified.",
            }
        ]
    )
    @Authenticator
    def post(self, userdata, reqargs):
        """
        Create a new userdata document {userdata}
        ---
        tags:
          - provisioner
        parameters:
          - in: query
            name: data
            type: string
            required: true
            description: Raw userdata configuration document
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.create_userdata(userdata, reqargs.get("data", None))

    @RequestParser(
        [
            {
                "name": "data",
                "required": True,
                "helptext": "A userdata document must be specified.",
            }
        ]
    )
    @Authenticator
    def put(self, userdata, reqargs):
        """
        Update userdata document {userdata}
        ---
        tags:
          - provisioner
        parameters:
          - in: query
            name: data
            type: string
            required: true
            description: Raw userdata configuration document
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.update_userdata(userdata, reqargs.get("data", None))

    @Authenticator
    def delete(self, userdata):
        """
        Remove userdata document {userdata}
        ---
        tags:
          - provisioner
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_provisioner.delete_userdata(userdata)


api.add_resource(API_Provisioner_Userdata_Element, "/provisioner/userdata/<userdata>")


# /provisioner/script
class API_Provisioner_Script_Root(Resource):
    @RequestParser([{"name": "limit"}])
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of scripts
        ---
        tags:
          - provisioner
        definitions:
          - schema:
              type: object
              id: script
              properties:
                id:
                  type: integer
                  description: Internal provisioner script ID
                name:
                  type: string
                  description: Script name
                script:
                  type: string
                  description: Raw Python script document
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: A script name search limit; fuzzy by default, use ^/$ to force exact matches
        responses:
          200:
            description: OK
            schema:
              type: list
              items:
                $ref: '#/definitions/script'
        """
        return api_provisioner.list_script(reqargs.get("limit", None))

    @RequestParser(
        [
            {
                "name": "name",
                "required": True,
                "helptext": "A script name must be specified.",
            },
            {
                "name": "data",
                "required": True,
                "helptext": "A script document must be specified.",
            },
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Create a new script
        ---
        tags:
          - provisioner
        parameters:
          - in: query
            name: name
            type: string
            required: true
            description: Script name
          - in: query
            name: data
            type: string
            required: true
            description: Raw Python script document
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.create_script(
            reqargs.get("name", None), reqargs.get("data", None)
        )


api.add_resource(API_Provisioner_Script_Root, "/provisioner/script")


# /provisioner/script/<script>
class API_Provisioner_Script_Element(Resource):
    @Authenticator
    def get(self, script):
        """
        Return information about script {script}
        ---
        tags:
          - provisioner
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/script'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_provisioner.list_script(script, is_fuzzy=False)

    @RequestParser(
        [
            {
                "name": "data",
                "required": True,
                "helptext": "A script document must be specified.",
            }
        ]
    )
    @Authenticator
    def post(self, script, reqargs):
        """
        Create a new script {script}
        ---
        tags:
          - provisioner
        parameters:
          - in: query
            name: data
            type: string
            required: true
            description: Raw Python script document
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.create_script(script, reqargs.get("data", None))

    @RequestParser(
        [
            {
                "name": "data",
                "required": True,
                "helptext": "A script document must be specified.",
            }
        ]
    )
    @Authenticator
    def put(self, script, reqargs):
        """
        Update script {script}
        ---
        tags:
          - provisioner
        parameters:
          - in: query
            name: data
            type: string
            required: true
            description: Raw Python script document
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.update_script(script, reqargs.get("data", None))

    @Authenticator
    def delete(self, script):
        """
        Remove script {script}
        ---
        tags:
          - provisioner
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_provisioner.delete_script(script)


api.add_resource(API_Provisioner_Script_Element, "/provisioner/script/<script>")


# /provisioner/profile
class API_Provisioner_OVA_Root(Resource):
    @RequestParser([{"name": "limit"}])
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of OVA sources
        ---
        tags:
          - provisioner
        definitions:
          - schema:
              type: object
              id: ova
              properties:
                id:
                  type: integer
                  description: Internal provisioner OVA ID
                name:
                  type: string
                  description: OVA name
                volumes:
                  type: list
                  items:
                    type: object
                    id: ova_volume
                    properties:
                      disk_id:
                        type: string
                        description: Disk identifier
                      disk_size_gb:
                        type: string
                        description: Disk size in GB
                      pool:
                        type: string
                        description: Pool containing the OVA volume
                      volume_name:
                        type: string
                        description: Storage volume containing the OVA image
                      volume_format:
                        type: string
                        description: OVA image format
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: An OVA name search limit; fuzzy by default, use ^/$ to force exact matches
        responses:
          200:
            description: OK
            schema:
              type: list
              items:
                $ref: '#/definitions/ova'
        """
        return api_ova.list_ova(reqargs.get("limit", None))

    @RequestParser(
        [
            {
                "name": "pool",
                "required": True,
                "location": ["args"],
                "helptext": "A storage pool must be specified.",
            },
            {
                "name": "name",
                "required": True,
                "location": ["args"],
                "helptext": "A VM name must be specified.",
            },
            {
                "name": "ova_size",
                "required": True,
                "location": ["args"],
                "helptext": "An OVA size must be specified.",
            },
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Upload an OVA image to the cluster

        The API client is responsible for determining and setting the ova_size value, as this value cannot be determined dynamically before the upload proceeds.
        ---
        tags:
          - provisioner
        parameters:
          - in: query
            name: pool
            type: string
            required: true
            description: Storage pool name
          - in: query
            name: name
            type: string
            required: true
            description: OVA name on the cluster (usually identical to the OVA file name)
          - in: query
            name: ova_size
            type: string
            required: true
            description: Size of the OVA file in bytes
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_ova.upload_ova(
            reqargs.get("pool", None),
            reqargs.get("name", None),
            reqargs.get("ova_size", None),
        )


api.add_resource(API_Provisioner_OVA_Root, "/provisioner/ova")


# /provisioner/ova/<ova>
class API_Provisioner_OVA_Element(Resource):
    @Authenticator
    def get(self, ova):
        """
        Return information about OVA image {ova}
        ---
        tags:
          - provisioner
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/ova'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_ova.list_ova(ova, is_fuzzy=False)

    @RequestParser(
        [
            {
                "name": "pool",
                "required": True,
                "location": ["args"],
                "helptext": "A storage pool must be specified.",
            },
            {
                "name": "ova_size",
                "required": True,
                "location": ["args"],
                "helptext": "An OVA size must be specified.",
            },
        ]
    )
    @Authenticator
    def post(self, ova, reqargs):
        """
        Upload an OVA image to the cluster

        The API client is responsible for determining and setting the ova_size value, as this value cannot be determined dynamically before the upload proceeds.
        ---
        tags:
          - provisioner
        parameters:
          - in: query
            name: pool
            type: string
            required: true
            description: Storage pool name
          - in: query
            name: ova_size
            type: string
            required: true
            description: Size of the OVA file in bytes
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_ova.upload_ova(
            reqargs.get("pool", None),
            ova,
            reqargs.get("ova_size", None),
        )

    @Authenticator
    def delete(self, ova):
        """
        Remove ova {ova}
        ---
        tags:
          - provisioner
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_ova.delete_ova(ova)


api.add_resource(API_Provisioner_OVA_Element, "/provisioner/ova/<ova>")


# /provisioner/profile
class API_Provisioner_Profile_Root(Resource):
    @RequestParser([{"name": "limit"}])
    @Authenticator
    def get(self, reqargs):
        """
        Return a list of profiles
        ---
        tags:
          - provisioner
        definitions:
          - schema:
              type: object
              id: profile
              properties:
                id:
                  type: integer
                  description: Internal provisioner profile ID
                name:
                  type: string
                  description: Profile name
                script:
                  type: string
                  description: Script name
                system_template:
                  type: string
                  description: System template name
                network_template:
                  type: string
                  description: Network template name
                storage_template:
                  type: string
                  description: Storage template name
                userdata:
                  type: string
                  description: Userdata template name
                arguments:
                  type: array
                  items:
                    type: string
                    description: Script install() function keyword arguments in "arg=data" format
        parameters:
          - in: query
            name: limit
            type: string
            required: false
            description: A profile name search limit; fuzzy by default, use ^/$ to force exact matches
        responses:
          200:
            description: OK
            schema:
              type: list
              items:
                $ref: '#/definitions/profile'
        """
        return api_provisioner.list_profile(reqargs.get("limit", None))

    @RequestParser(
        [
            {
                "name": "name",
                "required": True,
                "helptext": "A profile name must be specified.",
            },
            {
                "name": "profile_type",
                "required": True,
                "helptext": "A profile type must be specified.",
            },
            {
                "name": "system_template",
                "required": True,
                "helptext": "A system_template must be specified.",
            },
            {"name": "network_template"},
            {"name": "storage_template"},
            {"name": "userdata"},
            {
                "name": "script",
                "required": True,
                "helptext": "A script must be specified.",
            },
            {"name": "ova"},
            {"name": "arg", "action": "append"},
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Create a new profile
        ---
        tags:
          - provisioner
        parameters:
          - in: query
            name: name
            type: string
            required: true
            description: Profile name
          - in: query
            name: profile_type
            type: string
            required: true
            description: Profile type
            enum:
              - provisioner
              - ova
          - in: query
            name: script
            type: string
            required: true
            description: Script name
          - in: query
            name: system_template
            type: string
            required: true
            description: System template name
          - in: query
            name: network_template
            type: string
            required: false
            description: Network template name
          - in: query
            name: storage_template
            type: string
            required: false
            description: Storage template name
          - in: query
            name: userdata
            type: string
            required: false
            description: Userdata template name
          - in: query
            name: ova
            type: string
            required: false
            description: OVA image source
          - in: query
            name: arg
            type: string
            description: Script install() function keywork argument in "arg=data" format; may be specified multiple times to add multiple arguments
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.create_profile(
            reqargs.get("name", None),
            reqargs.get("profile_type", None),
            reqargs.get("system_template", None),
            reqargs.get("network_template", None),
            reqargs.get("storage_template", None),
            reqargs.get("userdata", None),
            reqargs.get("script", None),
            reqargs.get("ova", None),
            reqargs.get("arg", []),
        )


api.add_resource(API_Provisioner_Profile_Root, "/provisioner/profile")


# /provisioner/profile/<profile>
class API_Provisioner_Profile_Element(Resource):
    @Authenticator
    def get(self, profile):
        """
        Return information about profile {profile}
        ---
        tags:
          - provisioner
        responses:
          200:
            description: OK
            schema:
              $ref: '#/definitions/profile'
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_provisioner.list_profile(profile, is_fuzzy=False)

    @RequestParser(
        [
            {
                "name": "profile_type",
                "required": True,
                "helptext": "A profile type must be specified.",
            },
            {
                "name": "system_template",
                "required": True,
                "helptext": "A system_template must be specified.",
            },
            {"name": "network_template"},
            {"name": "storage_template"},
            {"name": "userdata"},
            {
                "name": "script",
                "required": True,
                "helptext": "A script must be specified.",
            },
            {"name": "ova"},
            {"name": "arg", "action": "append"},
        ]
    )
    @Authenticator
    def post(self, profile, reqargs):
        """
        Create a new profile {profile}
        ---
        tags:
          - provisioner
        parameters:
          - in: query
            name: profile_type
            type: string
            required: true
            description: Profile type
            enum:
              - provisioner
              - ova
          - in: query
            name: script
            type: string
            required: true
            description: Script name
          - in: query
            name: system_template
            type: string
            required: true
            description: System template name
          - in: query
            name: network_template
            type: string
            required: false
            description: Network template name
          - in: query
            name: storage_template
            type: string
            required: false
            description: Storage template name
          - in: query
            name: userdata
            type: string
            required: false
            description: Userdata template name
          - in: query
            name: ova
            type: string
            required: false
            description: OVA image source
          - in: query
            name: arg
            type: string
            description: Script install() function keywork argument in "arg=data" format; may be specified multiple times to add multiple arguments
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.create_profile(
            profile,
            reqargs.get("profile_type", None),
            reqargs.get("system_template", None),
            reqargs.get("network_template", None),
            reqargs.get("storage_template", None),
            reqargs.get("userdata", None),
            reqargs.get("script", None),
            reqargs.get("ova", None),
            reqargs.get("arg", []),
        )

    @RequestParser(
        [
            {"name": "system_template"},
            {"name": "network_template"},
            {"name": "storage_template"},
            {"name": "userdata"},
            {"name": "script"},
            {"name": "arg", "action": "append"},
        ]
    )
    @Authenticator
    def put(self, profile, reqargs):
        """
        Modify profile {profile}
        ---
        tags:
          - provisioner
        parameters:
          - in: query
            name: script
            type: string
            required: false
            description: Script name
          - in: query
            name: system_template
            type: string
            required: false
            description: System template name
          - in: query
            name: network_template
            type: string
            required: false
            description: Network template name
          - in: query
            name: storage_template
            type: string
            required: false
            description: Storage template name
          - in: query
            name: userdata
            type: string
            required: false
            description: Userdata template name
          - in: query
            name: arg
            type: string
            description: Script install() function keywork argument in "arg=data" format; may be specified multiple times to add multiple arguments
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        return api_provisioner.modify_profile(
            profile,
            None,  # Can't modify the profile type
            reqargs.get("system_template", None),
            reqargs.get("network_template", None),
            reqargs.get("storage_template", None),
            reqargs.get("userdata", None),
            reqargs.get("script", None),
            None,  # Can't modify the OVA
            reqargs.get("arg", []),
        )

    @Authenticator
    def delete(self, profile):
        """
        Remove profile {profile}
        ---
        tags:
          - provisioner
        responses:
          200:
            description: OK
            schema:
              type: object
              id: Message
          404:
            description: Not found
            schema:
              type: object
              id: Message
        """
        return api_provisioner.delete_profile(profile)


api.add_resource(API_Provisioner_Profile_Element, "/provisioner/profile/<profile>")


# /provisioner/create
class API_Provisioner_Create_Root(Resource):
    @RequestParser(
        [
            {
                "name": "name",
                "required": True,
                "helptext": "A VM name must be specified.",
            },
            {
                "name": "profile",
                "required": True,
                "helptext": "A profile name must be specified.",
            },
            {"name": "define_vm"},
            {"name": "start_vm"},
            {"name": "arg", "action": "append"},
        ]
    )
    @Authenticator
    def post(self, reqargs):
        """
        Create a new virtual machine
        Note: Starts a background job in the pvc-provisioner-worker Celery worker while returning a task ID; the task ID can be used to query the "GET /provisioner/status/<task_id>" endpoint for the job status
        ---
        tags:
          - provisioner
        parameters:
          - in: query
            name: name
            type: string
            required: true
            description: Virtual machine name
          - in: query
            name: profile
            type: string
            required: true
            description: Profile name
          - in: query
            name: define_vm
            type: boolean
            required: false
            description: Whether to define the VM on the cluster during provisioning
          - in: query
            name: start_vm
            type: boolean
            required: false
            description: Whether to start the VM after provisioning
          - in: query
            name: arg
            type: string
            description: Script install() function keywork argument in "arg=data" format; may be specified multiple times to add multiple arguments
        responses:
          200:
            description: OK
            schema:
              type: object
              properties:
                task_id:
                  type: string
                  description: Task ID for the provisioner Celery worker
          400:
            description: Bad request
            schema:
              type: object
              id: Message
        """
        # Verify that the profile is valid
        _list, code = api_provisioner.list_profile(
            reqargs.get("profile", None), is_fuzzy=False
        )
        if code != 200:
            return {
                "message": 'Profile "{}" is not valid.'.format(reqargs.get("profile"))
            }, 400

        if bool(strtobool(reqargs.get("define_vm", "true"))):
            define_vm = True
        else:
            define_vm = False

        if bool(strtobool(reqargs.get("start_vm", "true"))):
            start_vm = True
        else:
            start_vm = False

        task = run_celery_task(
            "provisioner.create",
            vm_name=reqargs.get("name", None),
            profile_name=reqargs.get("profile", None),
            define_vm=define_vm,
            start_vm=start_vm,
            script_run_args=reqargs.get("arg", []),
            run_on="primary",
        )
        return (
            {
                "task_id": task.id,
                "task_name": "provisioner.create",
                "run_on": get_primary_node(),
            },
            202,
            {"Location": Api.url_for(api, API_Tasks_Element, task_id=task.id)},
        )


api.add_resource(API_Provisioner_Create_Root, "/provisioner/create")
