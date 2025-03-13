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

from ast import literal_eval
from click import echo, progressbar
from math import ceil
from os.path import getsize
from time import time
import json
import socket
import ssl

# Define a Response class to mimic requests.Response
class Response:
    def __init__(self, status_code, headers, content):
        self.status_code = status_code
        self.headers = headers
        self.content = content
        self._json = None
        self.text = content.decode('utf-8', errors='replace') if content else ''
        self.ok = 200 <= status_code < 300
        self.url = None  # Will be set by call_api
        self.reason = None  # HTTP reason phrase
        self.encoding = 'utf-8'
        self.elapsed = None  # Time elapsed
        self.request = None  # Original request

    def json(self):
        if self._json is None:
            # Don't catch JSONDecodeError - let it propagate like requests does
            self._json = json.loads(self.content.decode('utf-8'))
        return self._json

    def raise_for_status(self):
        """Raises HTTPError if the status code is 4XX/5XX"""
        if 400 <= self.status_code < 600:
            raise Exception(f"HTTP Error {self.status_code}")

# Define ConnectionError to mimic requests.exceptions.ConnectionError
class ConnectionError(Exception):
    pass

class ErrorResponse(Response):
    def __init__(self, json_data, status_code, headers):
        self.status_code = status_code
        self.headers = headers
        self._json = json_data
        self.content = json.dumps(json_data).encode('utf-8') if json_data else b''

    def json(self):
        return self._json

def _encode_params(params):
    """Simple URL parameter encoder"""
    if not params:
        return ''

    parts = []
    for key, value in params.items():
        if isinstance(value, bool):
            value = str(value).lower()
        elif value is None:
            value = ''
        elif isinstance(value, (list, tuple)):
            # Handle lists and tuples by creating multiple parameters with the same name
            for item in value:
                parts.append(f"{key}={item}")
            continue  # Skip the normal append since we've already added the parts
        else:
            value = str(value)
        parts.append(f"{key}={value}")

    return '?' + '&'.join(parts)

def call_api(
    config,
    operation,
    request_uri,
    headers={},
    params=None,
    data=None,
    files=None,
):
    """
    Make an API call to the PVC API using native Python libraries.
    """
    # Set timeouts - fast connection timeout, longer read timeout
    connect_timeout = 2.05  # Connection timeout in seconds
    read_timeout = 172800.0 # Read timeout in seconds (much longer to allow for slow operations)

    # Import VERSION from cli.py - this is a lightweight import since cli.py is already loaded
    from pvc.cli.cli import VERSION

    # Set User-Agent header if not already set
    if "User-Agent" not in headers:
        headers["User-Agent"] = f"pvc-client-cli/{VERSION}"

    # Craft the URI
    uri = "{}://{}{}{}".format(
        config["api_scheme"], config["api_host"], config["api_prefix"], request_uri
    )

    # Parse the URI without using urllib
    if '://' in uri:
        scheme, rest = uri.split('://', 1)
    else:
        scheme = 'http'
        rest = uri

    if '/' in rest:
        netloc, path = rest.split('/', 1)
        path = '/' + path
    else:
        netloc = rest
        path = '/'

    # Extract host and port
    if ':' in netloc:
        host, port_str = netloc.split(':', 1)
        port = int(port_str)
    else:
        host = netloc
        port = 443 if scheme == 'https' else 80

    # Craft the authentication header if required
    if config["api_key"]:
        headers["X-Api-Key"] = config["api_key"]

    # Add content type if not present
    if "Content-Type" not in headers and data is not None and files is None:
        headers["Content-Type"] = "application/json"

    # Prepare query string
    query_string = _encode_params(params)

    # Prepare path with query string
    full_path = path + query_string

    # Prepare body
    body = None
    if data is not None and files is None:
        if isinstance(data, dict):
            body = json.dumps(data).encode('utf-8')
        else:
            body = data.encode('utf-8') if isinstance(data, str) else data

    # Handle file uploads (multipart/form-data)
    if files:
        boundary = '----WebKitFormBoundary' + str(int(time()))
        headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'

        body = b''
        # Add form fields
        if data:
            for key, value in data.items():
                body += f'--{boundary}\r\n'.encode()
                body += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
                body += f'{value}\r\n'.encode()

        # Add files
        for key, file_tuple in files.items():
            filename, fileobj, content_type = file_tuple
            body += f'--{boundary}\r\n'.encode()
            body += f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'.encode()
            body += f'Content-Type: {content_type}\r\n\r\n'.encode()
            body += fileobj.read()
            body += b'\r\n'

        body += f'--{boundary}--\r\n'.encode()

    # Use http.client instead of raw sockets for better HTTP protocol handling
    try:
        # Special handling for GET with retries
        if operation == "get":
            retry_on_code = [429, 500, 502, 503, 504]
            for i in range(3):
                failed = False
                try:
                    # Create the appropriate connection with separate timeouts
                    if scheme == 'https':
                        import ssl
                        context = None
                        if not config["verify_ssl"]:
                            context = ssl._create_unverified_context()

                        import http.client
                        conn = http.client.HTTPSConnection(
                            host, 
                            port=port,
                            timeout=connect_timeout,  # This is the connection timeout
                            context=context
                        )
                    else:
                        import http.client
                        conn = http.client.HTTPConnection(
                            host,
                            port=port,
                            timeout=connect_timeout  # This is the connection timeout
                        )

                    # Make the request
                    conn.request(operation.upper(), full_path, body=body, headers=headers)

                    # Set a longer timeout for reading the response
                    conn.sock.settimeout(read_timeout)

                    http_response = conn.getresponse()

                    # Read response data
                    status_code = http_response.status
                    response_headers = dict(http_response.getheaders())
                    response_data = http_response.read()

                    conn.close()

                    # Create a Response object
                    response = Response(status_code, response_headers, response_data)

                    if response.status_code in retry_on_code:
                        failed = True
                        continue
                    break
                except Exception as e:
                    failed = True
                    if 'conn' in locals():
                        conn.close()
                    continue

            if failed:
                error = f"Code {response.status_code}" if 'response' in locals() else "Timeout"
                raise ConnectionError(f"Failed to connect after 3 tries ({error})")
        else:
            # Handle other HTTP methods
            if scheme == 'https':
                import ssl
                context = None
                if not config["verify_ssl"]:
                    context = ssl._create_unverified_context()

                import http.client
                conn = http.client.HTTPSConnection(
                    host, 
                    port=port,
                    timeout=connect_timeout,  # This is the connection timeout
                    context=context
                )
            else:
                import http.client
                conn = http.client.HTTPConnection(
                    host,
                    port=port,
                    timeout=connect_timeout  # This is the connection timeout
                )

            # Make the request
            conn.request(operation.upper(), full_path, body=body, headers=headers)

            # Set a longer timeout for reading the response
            conn.sock.settimeout(read_timeout)

            http_response = conn.getresponse()

            # Read response data
            status_code = http_response.status
            response_headers = dict(http_response.getheaders())
            response_data = http_response.read()

            conn.close()

            # Create a Response object
            response = Response(status_code, response_headers, response_data)

    except Exception as e:
        message = f"Failed to connect to the API: {e}"
        code = getattr(response, 'status_code', 504) if 'response' in locals() else 504
        response = ErrorResponse({"message": message}, code, None)

    # Display debug output
    if config["debug"]:
        echo("API endpoint: {}".format(uri), err=True)
        echo("Response code: {}".format(response.status_code), err=True)
        echo("Response headers: {}".format(response.headers), err=True)
        echo(err=True)

    # Always return the response object - no special handling
    return response


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
        formatted_bytes = int(ceil(size_bytes / byte_unit_matrix[unit]))
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
        formatted_integer = int(ceil(integer / integer_unit_matrix[unit]))
        if formatted_integer < 10000:
            human_integer = "{}{}".format(formatted_integer, unit)
            break
    return human_integer


def format_age(age_secs):
    human_age = f"{age_secs} seconds"

    age_minutes = int(age_secs / 60)
    age_minutes_rounded = int(round(age_secs / 60))
    if age_minutes > 0:
        if age_minutes_rounded > 1:
            s = "s"
        else:
            s = ""
        human_age = f"{age_minutes_rounded} minute{s}"
    age_hours = int(age_secs / 3600)
    age_hours_rounded = int(round(age_secs / 3600))
    if age_hours > 0:
        if age_hours_rounded > 1:
            s = "s"
        else:
            s = ""
        human_age = f"{age_hours_rounded} hour{s}"
    age_days = int(age_secs / 86400)
    age_days_rounded = int(round(age_secs / 86400))
    if age_days > 0:
        if age_days_rounded > 1:
            s = "s"
        else:
            s = ""
        human_age = f"{age_days_rounded} day{s}"

    return human_age


class UploadProgressBar(object):
    def __init__(self, filename, end_message="", end_nl=True):
        file_size = getsize(filename)
        file_size_human = format_bytes(file_size)
        echo("Uploading file (total size {})...".format(file_size_human))

        self.length = file_size
        self.time_last = int(round(time() * 1000)) - 1000
        self.bytes_last = 0
        self.bytes_diff = 0
        self.is_end = False

        self.end_message = end_message
        self.end_nl = end_nl
        if not self.end_nl:
            self.end_suffix = " "
        else:
            self.end_suffix = ""

        self.bar = progressbar(length=self.length, width=20, show_eta=True)

    def update(self, monitor):
        bytes_cur = monitor.bytes_read
        self.bytes_diff += bytes_cur - self.bytes_last
        if self.bytes_last == bytes_cur:
            self.is_end = True
        self.bytes_last = bytes_cur

        time_cur = int(round(time() * 1000))
        if (time_cur - 1000) > self.time_last:
            self.time_last = time_cur
            self.bar.update(self.bytes_diff)
            self.bytes_diff = 0

        if self.is_end:
            self.bar.update(self.bytes_diff)
            self.bytes_diff = 0
            echo()
            echo()
            if self.end_message:
                echo(self.end_message + self.end_suffix, nl=self.end_nl)


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
