#!/usr/bin/env python3

# models.py - PVC Database models
# Part of the Parallel Virtual Cluster (PVC) system
#
#    Copyright (C) 2018-2020 Joshua M. Boniface <joshua@boniface.me>
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

from pvcapid.flaskapi import app, db

class DBSystemTemplate(db.Model):
    __tablename__ = 'system_template'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False, unique=True)
    vcpu_count = db.Column(db.Integer, nullable=False)
    vram_mb = db.Column(db.Integer, nullable=False)
    serial = db.Column(db.Boolean, nullable=False)
    vnc = db.Column(db.Boolean, nullable=False)
    vnc_bind = db.Column(db.Text)
    node_limit = db.Column(db.Text)
    node_selector = db.Column(db.Text)
    node_autostart = db.Column(db.Boolean, nullable=False)
    ova = db.Column(db.Integer, db.ForeignKey("ova.id"), nullable=True)

    def __init__(self, name, vcpu_count, vram_mb, serial, vnc, vnc_bind, node_limit, node_selector, node_autostart, ova=None):
        self.name = name
        self.vcpu_count = vcpu_count
        self.vram_mb = vram_mb
        self.serial = serial
        self.vnc = vnc
        self.vnc_bind = vnc_bind
        self.node_limit = node_limit
        self.node_selector = node_selector
        self.node_autostart = node_autostart
        self.ova = ova

    def __repr__(self):
        return '<id {}>'.format(self.id)

class DBNetworkTemplate(db.Model):
    __tablename__ = 'network_template'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False, unique=True)
    mac_template = db.Column(db.Text)
    ova = db.Column(db.Integer, db.ForeignKey("ova.id"), nullable=True)

    def __init__(self, name, mac_template, ova=None):
        self.name = name
        self.mac_template = mac_template
        self.ova = ova

    def __repr__(self):
        return '<id {}>'.format(self.id)

class DBNetworkElement(db.Model):
    __tablename__ = 'network'

    id = db.Column(db.Integer, primary_key=True)
    network_template = db.Column(db.Integer, db.ForeignKey("network_template.id"), nullable=False)
    vni = db.Column(db.Integer, nullable=False)

    def __init__(self, network_template, vni):
        self.network_template = network_template
        self.vni = vni

    def __repr__(self):
        return '<id {}>'.format(self.id)

class DBStorageTemplate(db.Model):
    __tablename__ = 'storage_template'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False, unique=True)
    ova = db.Column(db.Integer, db.ForeignKey("ova.id"), nullable=True)

    def __init__(self, name, ova=None):
        self.name = name
        self.ova = ova

    def __repr__(self):
        return '<id {}>'.format(self.id)

class DBStorageElement(db.Model):
    __tablename__ = 'storage'

    id = db.Column(db.Integer, primary_key=True)
    storage_template = db.Column(db.Integer, db.ForeignKey("storage_template.id"), nullable=False)
    pool = db.Column(db.Text, nullable=False)
    disk_id = db.Column(db.Text, nullable=False)
    source_volume = db.Column(db.Text)
    disk_size_gb = db.Column(db.Integer)
    mountpoint = db.Column(db.Text)
    filesystem = db.Column(db.Text)
    filesystem_args = db.Column(db.Text)

    def __init__(self, storage_template, pool, disk_id, source_volume, disk_size_gb, mountpoint, filesystem, filesystem_args):
        self.storage_template = storage_template
        self.pool = pool
        self.disk_id = disk_id
        self.source_volume = source_volume
        self.disk_size_gb = disk_size_gb
        self.mountpoint = mountpoint
        self.filesystem = filesystem
        self.filesystem_args = filesystem_args

    def __repr__(self):
        return '<id {}>'.format(self.id)

class DBUserdata(db.Model):
    __tablename__ = 'userdata'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False, unique=True)
    userdata = db.Column(db.Text, nullable=False)

    def __init__(self, name, userdata):
        self.name = name
        self.userdata = userdata

    def __repr__(self):
        return '<id {}>'.format(self.id)

class DBScript(db.Model):
    __tablename__ = 'script'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False, unique=True)
    script = db.Column(db.Text, nullable=False)

    def __init__(self, name, script):
        self.name = name
        self.script = script

    def __repr__(self):
        return '<id {}>'.format(self.id)

class DBOva(db.Model):
    __tablename__ = 'ova'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False, unique=True)
    ovf = db.Column(db.Text, nullable=False)

    def __init__(self, name, ovf):
        self.name = name
        self.ovf = ovf

    def __repr__(self):
        return '<id {}>'.format(self.id)

class DBOvaVolume(db.Model):
    __tablename__ = 'ova_volume'

    id = db.Column(db.Integer, primary_key=True)
    ova = db.Column(db.Integer, db.ForeignKey("ova.id"), nullable=False)
    pool = db.Column(db.Text, nullable=False)
    volume_name = db.Column(db.Text, nullable=False)
    volume_format = db.Column(db.Text, nullable=False)
    disk_id = db.Column(db.Text, nullable=False)
    disk_size_gb = db.Column(db.Integer, nullable=False)

    def __init__(self, ova, pool, volume_name, volume_format, disk_id, disk_size_gb):
        self.ova = ova
        self.pool = pool
        self.volume_name = volume_name
        self.volume_format = volume_format
        self.disk_id = disk_id
        self.disk_size_gb = disk_size_gb

    def __repr__(self):
        return '<id {}>'.format(self.id)

class DBProfile(db.Model):
    __tablename__ = 'profile'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False, unique=True)
    profile_type = db.Column(db.Text, nullable=False)
    system_template = db.Column(db.Integer, db.ForeignKey("system_template.id"))
    network_template = db.Column(db.Integer, db.ForeignKey("network_template.id"))
    storage_template = db.Column(db.Integer, db.ForeignKey("storage_template.id"))
    userdata = db.Column(db.Integer, db.ForeignKey("userdata.id"))
    script = db.Column(db.Integer, db.ForeignKey("script.id"))
    ova = db.Column(db.Integer, db.ForeignKey("ova.id"))
    arguments = db.Column(db.Text)

    def __init__(self, name, profile_type, system_template, network_template, storage_template, userdata, script, ova, arguments):
        self.name = name
        self.profile_type = profile_type
        self.system_template = system_template
        self.network_template = network_template
        self.storage_template = storage_template
        self.userdata = userdata
        self.script = script
        self.ova = ova
        self.arguments = arguments

    def __repr__(self):
        return '<id {}>'.format(self.id)

class DBStorageBenchmarks(db.Model):
    __tablename__ = 'storage_benchmarks'

    id = db.Column(db.Integer, primary_key=True)
    job = db.Column(db.Text, nullable=False)
    result = db.Column(db.Text, nullable=False)

    def __init__(self, job, result):
        self.job = job
        self.result = result

    def __repr__(self):
        return '<id {}>'.format(self.id)
