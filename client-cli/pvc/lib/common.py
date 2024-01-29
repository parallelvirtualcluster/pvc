#!/usr/bin/env python3

# common.py - PVC CLI client function library, Common functions
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2024 Joshua M. Boniface <joshua@boniface.me>
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

import os
import math
import time
import requests
import click
from ast import literal_eval
from urllib3 import disable_warnings


def format_bytes(size_bytes):
    byte_unit_matrix = {
        "B": 1,
        "K": 1024,
        "M": 1024 * 1024,
        "G": 1024 * 1024 * 1024,
        "T": 1024 * 1024 * 1024 * 1024,
        "P": 1024 * 1024 * 1024 * 1024 * 1024,
    }
    human_bytes = "0B"
    for unit in sorted(byte_unit_matrix, key=byte_unit_matrix.get):
        formatted_bytes = int(math.ceil(size_bytes / byte_unit_matrix[unit]))
        if formatted_bytes < 10000:
            human_bytes = "{}{}".format(formatted_bytes, unit)
            break
    return human_bytes


def format_metric(integer):
    integer_unit_matrix = {
        "": 1,
        "K": 1000,
        "M": 1000 * 1000,
        "B": 1000 * 1000 * 1000,
        "T": 1000 * 1000 * 1000 * 1000,
        "Q": 1000 * 1000 * 1000 * 1000 * 1000,
    }
    human_integer = "0"
    for unit in sorted(integer_unit_matrix, key=integer_unit_matrix.get):
        formatted_integer = int(math.ceil(integer / integer_unit_matrix[unit]))
        if formatted_integer < 10000:
            human_integer = "{}{}".format(formatted_integer, unit)
            break
    return human_integer


class UploadProgressBar(object):
    def __init__(self, filename, end_message="", end_nl=True):
        file_size = os.path.getsize(filename)
        file_size_human = format_bytes(file_size)
        click.echo("Uploading file (total size {})...".format(file_size_human))

        self.length = file_size
        self.time_last = int(round(time.time() * 1000)) - 1000
        self.bytes_last = 0
        self.bytes_diff = 0
        self.is_end = False

        self.end_message = end_message
        self.end_nl = end_nl
        if not self.end_nl:
            self.end_suffix = " "
        else:
            self.end_suffix = ""

        self.bar = click.progressbar(length=self.length, show_eta=True)

    def update(self, monitor):
        bytes_cur = monitor.bytes_read
        self.bytes_diff += bytes_cur - self.bytes_last
        if self.bytes_last == bytes_cur:
            self.is_end = True
        self.bytes_last = bytes_cur

        time_cur = int(round(time.time() * 1000))
        if (time_cur - 1000) > self.time_last:
            self.time_last = time_cur
            self.bar.update(self.bytes_diff)
            self.bytes_diff = 0

        if self.is_end:
            self.bar.update(self.bytes_diff)
            self.bytes_diff = 0
            click.echo()
            click.echo()
            if self.end_message:
                click.echo(self.end_message + self.end_suffix, nl=self.end_nl)


class ErrorResponse(requests.Response):
    def __init__(self, json_data, status_code):
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        return self.json_data


def call_api(
    config,
    operation,
    request_uri,
    headers={},
    params=None,
    data=None,
    files=None,
):
    # Set the connect timeout to 2 seconds but extremely long (48 hour) data timeout
    timeout = (2.05, 172800)

    # Craft the URI
    uri = "{}://{}{}{}".format(
        config["api_scheme"], config["api_host"], config["api_prefix"], request_uri
    )

    # Craft the authentication header if required
    if config["api_key"]:
        headers["X-Api-Key"] = config["api_key"]

    # Determine the request type and hit the API
    disable_warnings()
    try:
        response = None
        if operation == "get":
            retry_on_code = [429, 500, 502, 503, 504]
            for i in range(3):
                failed = False
                try:
                    response = requests.get(
                        uri,
                        timeout=timeout,
                        headers=headers,
                        params=params,
                        data=data,
                        verify=config["verify_ssl"],
                    )
                    if response.status_code in retry_on_code:
                        failed = True
                        continue
                except requests.exceptions.ConnectionError:
                    failed = True
                    pass
            if failed:
                error = f"Code {response.status_code}" if response else "Timeout"
                raise requests.exceptions.ConnectionError(
                    f"Failed to connect after 3 tries ({error})"
                )
        if operation == "post":
            response = requests.post(
                uri,
                timeout=timeout,
                headers=headers,
                params=params,
                data=data,
                files=files,
                verify=config["verify_ssl"],
            )
        if operation == "put":
            response = requests.put(
                uri,
                timeout=timeout,
                headers=headers,
                params=params,
                data=data,
                files=files,
                verify=config["verify_ssl"],
            )
        if operation == "patch":
            response = requests.patch(
                uri,
                timeout=timeout,
                headers=headers,
                params=params,
                data=data,
                verify=config["verify_ssl"],
            )
        if operation == "delete":
            response = requests.delete(
                uri,
                timeout=timeout,
                headers=headers,
                params=params,
                data=data,
                verify=config["verify_ssl"],
            )
    except Exception as e:
        message = "Failed to connect to the API: {}".format(e)
        code = response.status_code if response else 504
        response = ErrorResponse({"message": message}, code)

    # Display debug output
    if config["debug"]:
        click.echo("API endpoint: {}".format(uri), err=True)
        click.echo("Response code: {}".format(response.status_code), err=True)
        click.echo("Response headers: {}".format(response.headers), err=True)
        click.echo(err=True)

    # Return the response object
    return response


def get_wait_retdata(response, wait_flag):
    if response.status_code == 202:
        retvalue = True
        retjson = response.json()
        if not wait_flag:
            retdata = (
                f"Task ID: {retjson['task_id']} assigned to node {retjson['run_on']}"
            )
        else:
            # Just return the task JSON without formatting
            retdata = response.json()
    else:
        retvalue = False
        retdata = response.json().get("message", "")

    return retvalue, retdata


def task_status(config, task_id=None, is_watching=False):
    """
    Get information about Celery job {task_id}, or all tasks if None

    API endpoint: GET /api/v1/tasks/{task_id}
    API arguments:
    API schema: {json_data_object}
    """
    if task_id is not None:
        response = call_api(config, "get", f"/tasks/{task_id}")
    else:
        response = call_api(config, "get", "/tasks")

    if task_id is not None:
        if response.status_code == 200:
            retvalue = True
            respjson = response.json()
            if is_watching:
                # Just return the raw JSON to the watching process instead of including value
                return respjson
            else:
                return retvalue, respjson
        else:
            retvalue = False
            retdata = response.json().get("message", "")
    else:
        retvalue = True
        task_data_raw = response.json()
        # Format the Celery data into a more useful data structure
        task_data = list()
        for task_type in ["active", "reserved", "scheduled"]:
            try:
                type_data = task_data_raw[task_type]
            except Exception:
                type_data = None

            if not type_data:
                type_data = dict()
            for task_host in type_data:
                for task_job in task_data_raw[task_type][task_host]:
                    task = dict()
                    if task_type == "reserved":
                        task["type"] = "pending"
                    else:
                        task["type"] = task_type
                    task["worker"] = task_host
                    task["id"] = task_job.get("id")
                    task["name"] = task_job.get("name")
                    try:
                        task["args"] = literal_eval(task_job.get("args"))
                    except Exception:
                        task["args"] = task_job.get("args")
                    try:
                        task["kwargs"] = literal_eval(task_job.get("kwargs"))
                    except Exception:
                        task["kwargs"] = task_job.get("kwargs")
                    task_data.append(task)
        retdata = task_data

    return retvalue, retdata
