#!/usr/bin/env python3

# formatters.py - PVC Click CLI output formatters library
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2023 Joshua M. Boniface <joshua@boniface.me>
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

# import colorama


# Define colour values for use in formatters
ansii = {
    "red": "\033[91m",
    "blue": "\033[94m",
    "cyan": "\033[96m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "purple": "\033[95m",
    "bold": "\033[1m",
    "end": "\033[0m",
}


def cli_connection_list_format_pretty(data):
    """
    Pretty format the output of cli_connection_list
    """

    # Set the fields data
    fields = {
        "name": {"header": "Name", "length": len("Name") + 1},
        "description": {"header": "Description", "length": len("Description") + 1},
        "address": {"header": "Address", "length": len("Address") + 1},
        "port": {"header": "Port", "length": len("Port") + 1},
        "scheme": {"header": "Scheme", "length": len("Scheme") + 1},
        "api_key": {"header": "API Key", "length": len("API Key") + 1},
    }

    # Parse each connection and adjust field lengths
    for connection in data:
        for field, length in [(f, fields[f]["length"]) for f in fields]:
            _length = len(str(connection[field]))
            if _length > length:
                length = len(str(connection[field])) + 1

            fields[field]["length"] = length

    # Create the output object and define the line format
    output = list()
    line = "{bold}{name: <{lname}} {desc: <{ldesc}} {addr: <{laddr}} {port: <{lport}} {schm: <{lschm}} {akey: <{lakey}}{end}"

    # Add the header line
    output.append(
        line.format(
            bold=ansii["bold"],
            end=ansii["end"],
            name=fields["name"]["header"],
            lname=fields["name"]["length"],
            desc=fields["description"]["header"],
            ldesc=fields["description"]["length"],
            addr=fields["address"]["header"],
            laddr=fields["address"]["length"],
            port=fields["port"]["header"],
            lport=fields["port"]["length"],
            schm=fields["scheme"]["header"],
            lschm=fields["scheme"]["length"],
            akey=fields["api_key"]["header"],
            lakey=fields["api_key"]["length"],
        )
    )

    # Add a line per connection
    for connection in data:
        output.append(
            line.format(
                bold="",
                end="",
                name=connection["name"],
                lname=fields["name"]["length"],
                desc=connection["description"],
                ldesc=fields["description"]["length"],
                addr=connection["address"],
                laddr=fields["address"]["length"],
                port=connection["port"],
                lport=fields["port"]["length"],
                schm=connection["scheme"],
                lschm=fields["scheme"]["length"],
                akey=connection["api_key"],
                lakey=fields["api_key"]["length"],
            )
        )

    return "\n".join(output)


def cli_connection_detail_format_pretty(data):
    """
    Pretty format the output of cli_connection_detail
    """

    # Set the fields data
    fields = {
        "name": {"header": "Name", "length": len("Name") + 1},
        "description": {"header": "Description", "length": len("Description") + 1},
        "health": {"header": "Health", "length": len("Health") + 1},
        "primary_node": {"header": "Primary", "length": len("Primary") + 1},
        "pvc_version": {"header": "Version", "length": len("Version") + 1},
        "nodes": {"header": "Nodes", "length": len("Nodes") + 1},
        "vms": {"header": "VMs", "length": len("VMs") + 1},
        "networks": {"header": "Networks", "length": len("Networks") + 1},
        "osds": {"header": "OSDs", "length": len("OSDs") + 1},
        "pools": {"header": "Pools", "length": len("Pools") + 1},
        "volumes": {"header": "Volumes", "length": len("Volumes") + 1},
        "snapshots": {"header": "Snapshots", "length": len("Snapshots") + 1},
    }

    # Parse each connection and adjust field lengths
    for connection in data:
        for field, length in [(f, fields[f]["length"]) for f in fields]:
            _length = len(str(connection[field]))
            if _length > length:
                length = len(str(connection[field])) + 1

            fields[field]["length"] = length

    # Create the output object and define the line format
    output = list()
    line = "{bold}{name: <{lname}} {desc: <{ldesc}} {chlth}{hlth: <{lhlth}}{endc} {prin: <{lprin}} {vers: <{lvers}} {nods: <{lnods}} {vms: <{lvms}} {nets: <{lnets}} {osds: <{losds}} {pols: <{lpols}} {vols: <{lvols}} {snts: <{lsnts}}{end}"

    # Add the header line
    output.append(
        line.format(
            bold=ansii["bold"],
            end=ansii["end"],
            chlth="",
            endc="",
            name=fields["name"]["header"],
            lname=fields["name"]["length"],
            desc=fields["description"]["header"],
            ldesc=fields["description"]["length"],
            hlth=fields["health"]["header"],
            lhlth=fields["health"]["length"],
            prin=fields["primary_node"]["header"],
            lprin=fields["primary_node"]["length"],
            vers=fields["pvc_version"]["header"],
            lvers=fields["pvc_version"]["length"],
            nods=fields["nodes"]["header"],
            lnods=fields["nodes"]["length"],
            vms=fields["vms"]["header"],
            lvms=fields["vms"]["length"],
            nets=fields["networks"]["header"],
            lnets=fields["networks"]["length"],
            osds=fields["osds"]["header"],
            losds=fields["osds"]["length"],
            pols=fields["pools"]["header"],
            lpols=fields["pools"]["length"],
            vols=fields["volumes"]["header"],
            lvols=fields["volumes"]["length"],
            snts=fields["snapshots"]["header"],
            lsnts=fields["snapshots"]["length"],
        )
    )

    # Add a line per connection
    for connection in data:
        if connection["health"] == "N/A":
            health_value = "N/A"
            health_colour = ansii["purple"]
        else:
            health_value = f"{connection['health']}%"
            if connection["maintenance"] == "true":
                health_colour = ansii["blue"]
            elif connection["health"] > 90:
                health_colour = ansii["green"]
            elif connection["health"] > 50:
                health_colour = ansii["yellow"]
            else:
                health_colour = ansii["red"]

        output.append(
            line.format(
                bold="",
                end="",
                chlth=health_colour,
                endc=ansii["end"],
                name=connection["name"],
                lname=fields["name"]["length"],
                desc=connection["description"],
                ldesc=fields["description"]["length"],
                hlth=health_value,
                lhlth=fields["health"]["length"],
                prin=connection["primary_node"],
                lprin=fields["primary_node"]["length"],
                vers=connection["pvc_version"],
                lvers=fields["pvc_version"]["length"],
                nods=connection["nodes"],
                lnods=fields["nodes"]["length"],
                vms=connection["vms"],
                lvms=fields["vms"]["length"],
                nets=connection["networks"],
                lnets=fields["networks"]["length"],
                osds=connection["osds"],
                losds=fields["osds"]["length"],
                pols=connection["pools"],
                lpols=fields["pools"]["length"],
                vols=connection["volumes"],
                lvols=fields["volumes"]["length"],
                snts=connection["snapshots"],
                lsnts=fields["snapshots"]["length"],
            )
        )

    return "\n".join(output)
