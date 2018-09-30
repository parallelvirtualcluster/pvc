#!/usr/bin/python3

# DHCPServer.py - PVC router DHCP server with Zookeeper database
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
# 
# Modified from python_dhcp_server
# Source: https://github.com/niccokunzmann/python_dhcp_server
#
#    Copyright (c) 2015 Nicco Kunzmann and released under the MIT license
#
###############################################################################

import time
import threading
import struct
import queue
import collections
import traceback
import random
import base64
import select
import ipaddress
from socket import *

# see https://en.wikipedia.org/wiki/Dynamic_Host_Configuration_Protocol
# section DHCP options

def inet_ntoaX(data):
    return ['.'.join(map(str, data[i:i + 4])) for i in range(0, len(data), 4)]

def inet_atonX(ips):
    return b''.join(map(inet_aton, ips))

dhcp_message_types = {
    1 : 'DHCPDISCOVER',
    2 : 'DHCPOFFER',
    3 : 'DHCPREQUEST',
    4 : 'DHCPDECLINE',
    5 : 'DHCPACK',
    6 : 'DHCPNAK',
    7 : 'DHCPRELEASE',
    8 : 'DHCPINFORM',
}
reversed_dhcp_message_types = dict()
for i, v in dhcp_message_types.items():
    reversed_dhcp_message_types[v] = i

shortunpack = lambda data: (data[0] << 8) + data[1]
shortpack = lambda i: bytes([i >> 8, i & 255])


def macunpack(data):
    s = base64.b16encode(data)
    return ':'.join([s[i:i+2].decode('ascii') for i in range(0, 12, 2)])

def macpack(mac):
    return base64.b16decode(mac.replace(':', '').replace('-', '').encode('ascii'))

def unpackbool(data):
    return data[0]

def packbool(bool):
    return bytes([bool])

options = [
# RFC1497 vendor extensions
    ('pad', None, None),
    ('subnet_mask', inet_ntoa, inet_aton),
    ('time_offset', None, None),
    ('router', inet_ntoaX, inet_atonX),
    ('time_server', inet_ntoaX, inet_atonX),
    ('name_server', inet_ntoaX, inet_atonX),
    ('domain_name_server', inet_ntoaX, inet_atonX),
    ('log_server', inet_ntoaX, inet_atonX),
    ('cookie_server', inet_ntoaX, inet_atonX),
    ('lpr_server', inet_ntoaX, inet_atonX),
    ('impress_server', inet_ntoaX, inet_atonX),
    ('resource_location_server', inet_ntoaX, inet_atonX),
    ('host_name', lambda d: d.decode('ASCII'), lambda d: d.encode('ASCII')),
    ('boot_file_size', None, None),
    ('merit_dump_file', None, None),
    ('domain_name', None, None),
    ('swap_server', inet_ntoa, inet_aton),
    ('root_path', None, None),
    ('extensions_path', None, None),
# IP Layer Parameters per Host
    ('ip_forwarding_enabled', unpackbool, packbool),
    ('non_local_source_routing_enabled', unpackbool, packbool),
    ('policy_filer', None, None),
    ('maximum_datagram_reassembly_size', shortunpack, shortpack),
    ('default_ip_time_to_live', lambda data: data[0], lambda i: bytes([i])),
    ('path_mtu_aging_timeout', None, None),
    ('path_mtu_plateau_table', None, None),
# IP Layer Parameters per Interface
    ('interface_mtu', None, None),
    ('all_subnets_are_local', unpackbool, packbool),
    ('broadcast_address', inet_ntoa, inet_aton),
    ('perform_mask_discovery', unpackbool, packbool),
    ('mask_supplier', None, None),
    ('perform_router_discovery', None, None),
    ('router_solicitation_address', inet_ntoa, inet_aton),
    ('static_route', None, None),
# Link Layer Parameters per Interface
    ('trailer_encapsulation_option', None, None),
    ('arp_cache_timeout', None, None),
    ('ethernet_encapsulation', None, None),
# TCP Parameters
    ('tcp_default_ttl', None, None),
    ('tcp_keep_alive_interval', None, None),
    ('tcp_keep_alive_garbage', None, None),
# Application and Service Parameters Part 1
    ('network_information_service_domain', None, None),
    ('network_informtaion_servers', inet_ntoaX, inet_atonX),
    ('network_time_protocol_servers', inet_ntoaX, inet_atonX),
    ('vendor_specific_information', None, None),
    ('netbios_over_tcp_ip_name_server', inet_ntoaX, inet_atonX),
    ('netbios_over_tcp_ip_datagram_distribution_server', inet_ntoaX, inet_atonX),
    ('netbios_over_tcp_ip_node_type', None, None),
    ('netbios_over_tcp_ip_scope', None, None),
    ('x_window_system_font_server', inet_ntoaX, inet_atonX),
    ('x_window_system_display_manager', inet_ntoaX, inet_atonX),
# DHCP Extensions
    ('requested_ip_address', inet_ntoa, inet_aton),
    ('ip_address_lease_time', lambda d: struct.unpack('>I', d)[0], lambda i: struct.pack('>I', i)),
    ('option_overload', None, None),
    ('dhcp_message_type', lambda data: dhcp_message_types.get(data[0], data[0]), (lambda name: bytes([reversed_dhcp_message_types.get(name, name)]))),
    ('server_identifier', inet_ntoa, inet_aton),
    ('parameter_request_list', list, bytes),
    ('message', None, None),
    ('maximum_dhcp_message_size', shortunpack, shortpack),
    ('renewal_time_value', None, None),
    ('rebinding_time_value', None, None),
    ('vendor_class_identifier', None, None),
    ('client_identifier', macunpack, macpack),
    ('tftp_server_name', None, None),
    ('boot_file_name', None, None),
# Application and Service Parameters Part 2
    ('network_information_service_domain', None, None),
    ('network_information_servers', inet_ntoaX, inet_atonX),
    ('', None, None),
    ('', None, None),
    ('mobile_ip_home_agent', inet_ntoaX, inet_atonX),
    ('smtp_server', inet_ntoaX, inet_atonX),
    ('pop_servers', inet_ntoaX, inet_atonX),
    ('nntp_server', inet_ntoaX, inet_atonX),
    ('default_www_server', inet_ntoaX, inet_atonX),
    ('default_finger_server', inet_ntoaX, inet_atonX),
    ('default_irc_server', inet_ntoaX, inet_atonX),
    ('streettalk_server', inet_ntoaX, inet_atonX),
    ('stda_server', inet_ntoaX, inet_atonX),
    ]

assert options[18][0] == 'extensions_path', options[18][0]
assert options[25][0] == 'path_mtu_plateau_table', options[25][0]
assert options[33][0] == 'static_route', options[33][0]
assert options[50][0] == 'requested_ip_address', options[50][0]
assert options[64][0] == 'network_information_service_domain', options[64][0]
assert options[76][0] == 'stda_server', options[76][0]


class ReadBootProtocolPacket(object):

    for i, o in enumerate(options):
        locals()[o[0]] = None
        locals()['option_{0}'.format(i)] = None

    del i, o

    def __init__(self, data, address = ('0.0.0.0', 0)):
        self.data = data
        self.address = address
        self.host = address[0]
        self.port = address[1]

        # wireshark = wikipedia = data[...]
        
        self.message_type = self.OP =                data[0]
        self.hardware_type = self.HTYPE =            data[1]
        self.hardware_address_length = self.HLEN =   data[2]
        self.hops = self.HOPS =                      data[3]

        self.XID = self.transaction_id = struct.unpack('>I', data[4:8])[0]

        self.seconds_elapsed = self.SECS = shortunpack(data[8:10])
        self.bootp_flags = self.FLAGS =    shortunpack(data[8:10])

        self.client_ip_address = self.CIADDR = inet_ntoa(data[12:16])
        self.your_ip_address   = self.YIADDR = inet_ntoa(data[16:20])
        self.next_server_ip_address = self.SIADDR = inet_ntoa(data[20:24])
        self.relay_agent_ip_address = self.GIADDR = inet_ntoa(data[24:28])

        self.client_mac_address = self.CHADDR = macunpack(data[28: 28 + self.hardware_address_length])
        index = 236
        self.magic_cookie = self.magic_cookie = inet_ntoa(data[index:index + 4]); index += 4
        self.options = dict()
        self.named_options = dict()
        while index < len(data):
            option = data[index]; index += 1
            if option == 0:
                # padding
                # Can be used to pad other options so that they are aligned to the word boundary; is not followed by length byte
                continue
            if option == 255:
                # end
                break
            option_length = data[index]; index += 1
            option_data = data[index: index + option_length]; index += option_length
            self.options[option] = option_data
            if option < len(options):
                option_name, function, _ = options[option]
                if function:
                    option_data = function(option_data)
                if option_name:
                    setattr(self, option_name, option_data)
                    self.named_options[option_name] = option_data
            setattr(self, 'option_{}'.format(option), option_data)

    def __getitem__(self, key):
        print(key, dir(self))
        return getattr(self, key, None)

    def __contains__(self, key):
        return key in self.__dict__

    @property
    def formatted_named_options(self):
        return "\n".join("{}:\t{}".format(name.replace('_', ' '), value) for name, value in sorted(self.named_options.items()))

    def __str__(self):
        return """Message Type: {self.message_type}
client MAC address: {self.client_mac_address}
client IP address: {self.client_ip_address}
your IP address: {self.your_ip_address}
next server IP address: {self.next_server_ip_address}
{self.formatted_named_options}
""".format(self = self)

    def __gt__(self, other):
        return id(self) < id(other)

data = base64.b16decode(b'02010600f7b41ad100000000c0a800640000000000000000000000007c7a914bca6c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000638253633501053604c0a800010104ffffff000304c0a800010604c0a80001ff00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'.upper())
assert data[0] == 2
p = ReadBootProtocolPacket(data)
assert p.message_type == 2
assert p.hardware_type == 1
assert p.hardware_address_length == 6
assert p.hops == 0
assert p.transaction_id == 4155775697
assert p.seconds_elapsed == 0
assert p.bootp_flags == 0
assert p.client_ip_address == '192.168.0.100'
assert p.your_ip_address == '0.0.0.0'
assert p.next_server_ip_address == '0.0.0.0'
assert p.relay_agent_ip_address == '0.0.0.0'
assert p.client_mac_address.lower() == '7c:7a:91:4b:ca:6c'
assert p.magic_cookie == '99.130.83.99'
assert p.dhcp_message_type == 'DHCPACK'
assert p.options[53] == b'\x05'
assert p.server_identifier == '192.168.0.1'
assert p.subnet_mask == '255.255.255.0'
assert p.router == ['192.168.0.1']
assert p.domain_name_server == ['192.168.0.1']
str(p)

if __name__ == '__main__':
    s1 = socket(type = SOCK_DGRAM)
    s1.setsockopt(SOL_IP, SO_REUSEADDR, 1)
    s1.bind(('', 67))
    #s2 = socket(type = SOCK_DGRAM)
    #s2.setsockopt(SOL_IP, SO_REUSEADDR, 1)
    #s2.bind(('', 68))
    while 1:
        reads = select.select([s1], [], [], 1)[0]
        for s in reads:
            packet = ReadBootProtocolPacket(*s.recvfrom(4096))
            print(packet)


def get_host_ip_addresses():
    return gethostbyname_ex(gethostname())[2]


class WriteBootProtocolPacket(object):

    message_type = 2 # 1 for client -> server 2 for server -> client
    hardware_type = 1
    hardware_address_length = 6
    hops = 0

    transaction_id = None

    seconds_elapsed = 0
    bootp_flags = 0 # unicast

    client_ip_address = '0.0.0.0'
    your_ip_address = '0.0.0.0'
    next_server_ip_address = '0.0.0.0'
    relay_agent_ip_address = '0.0.0.0'

    client_mac_address = None
    magic_cookie = '99.130.83.99'

    parameter_order = []
    
    def __init__(self, configuration):
        for i in range(256):
            names = ['option_{}'.format(i)]
            if i < len(options) and hasattr(configuration, options[i][0]):
                names.append(options[i][0])
            for name in names:
                if hasattr(configuration, name):
                    setattr(self, name, getattr(configuration, name))

    def to_bytes(self):
        result = bytearray(236)
        
        result[0] = self.message_type
        result[1] = self.hardware_type
        result[2] = self.hardware_address_length
        result[3] = self.hops

        result[4:8] = struct.pack('>I', self.transaction_id)

        result[ 8:10] = shortpack(self.seconds_elapsed)
        result[10:12] = shortpack(self.bootp_flags)

        result[12:16] = inet_aton(self.client_ip_address)
        result[16:20] = inet_aton(self.your_ip_address)
        result[20:24] = inet_aton(self.next_server_ip_address)
        result[24:28] = inet_aton(self.relay_agent_ip_address)

        result[28:28 + self.hardware_address_length] = macpack(self.client_mac_address)
        
        result += inet_aton(self.magic_cookie)

        for option in self.options:
            value = self.get_option(option)
            #print(option, value)
            if value is None:
                continue
            result += bytes([option, len(value)]) + value
        result += bytes([255])
        return bytes(result)

    def get_option(self, option):
        if option < len(options) and hasattr(self, options[option][0]):
            value = getattr(self, options[option][0])
        elif hasattr(self, 'option_{}'.format(option)):
            value = getattr(self, 'option_{}'.format(option))
        else:
            return None
        function = options[option][2]
        if function and value is not None:
            value = function(value)
        return value
    
    @property
    def options(self):
        done = list()
        # fulfill wishes
        for option in self.parameter_order:
            if option < len(options) and hasattr(self, options[option][0]) or hasattr(self, 'option_{}'.format(option)):
                # this may break with the specification because we must try to fulfill the wishes
                if option not in done:
                    done.append(option)
        # add my stuff
        for option, o in enumerate(options):
            if o[0] and hasattr(self, o[0]):
                if option not in done:
                    done.append(option)
        for option in range(256):
            if hasattr(self, 'option_{}'.format(option)):
                if option not in done:
                    done.append(option)
        return done

    def __str__(self):
        return str(ReadBootProtocolPacket(self.to_bytes()))

class DelayWorker(object):

    def __init__(self):
        self.closed = False
        self.queue = queue.PriorityQueue()
        self.thread = threading.Thread(target = self._delay_response_thread)
        self.thread.daemon = True
        self.thread.start()

    def _delay_response_thread(self):
        while not self.closed:
            p = self.queue.get()
            if self.closed:
                break
            t, func, args, kw = p
            now = time.time()
            if now < t:
                time.sleep(0.01)
                self.queue.put(p)
            else:
                func(*args, **kw)

    def do_after(self, seconds, func, args = (), kw = {}):
        self.queue.put((time.time() + seconds, func, args, kw))

    def close(self):
        self.closed = True

class Transaction(object):

    def __init__(self, server):
        self.server = server
        self.configuration = server.configuration
        self.packets = []
        self.done_time = time.time() + self.configuration.length_of_transaction
        self.done = False
        self.do_after = self.server.delay_worker.do_after

    def is_done(self):
        return self.done or self.done_time < time.time()

    def close(self):
        self.done = True

    def receive(self, packet):
        # packet from client <-> packet.message_type == 1
        if packet.message_type == 1 and packet.dhcp_message_type == 'DHCPDISCOVER':
            self.do_after(self.configuration.dhcp_offer_after_seconds,
                          self.received_dhcp_discover, (packet,), )
        elif packet.message_type == 1 and packet.dhcp_message_type == 'DHCPREQUEST':
            self.do_after(self.configuration.dhcp_acknowledge_after_seconds,
                          self.received_dhcp_request, (packet,), )
        elif packet.message_type == 1 and packet.dhcp_message_type == 'DHCPINFORM':
            self.received_dhcp_inform(packet)
        else:
            return False
        return True

    def received_dhcp_discover(self, discovery):
        if self.is_done(): return
        self.configuration.debug('discover:\n {}'.format(str(discovery).replace('\n', '\n\t')))
        self.send_offer(discovery)

    def send_offer(self, discovery):
        # https://tools.ietf.org/html/rfc2131
        offer = WriteBootProtocolPacket(self.configuration)
        offer.parameter_order = discovery.parameter_request_list
        mac = discovery.client_mac_address
        ip = offer.your_ip_address = self.server.get_ip_address(discovery)
        # offer.client_ip_address = 
        offer.transaction_id = discovery.transaction_id
        # offer.next_server_ip_address =
        offer.relay_agent_ip_address = discovery.relay_agent_ip_address
        offer.client_mac_address = mac
        offer.client_ip_address = discovery.client_ip_address or '0.0.0.0'
        offer.bootp_flags = discovery.bootp_flags
        offer.dhcp_message_type = 'DHCPOFFER'
        offer.client_identifier = mac
        self.server.broadcast(offer)
    
    def received_dhcp_request(self, request):
        if self.is_done(): return 
        self.server.client_has_chosen(request)
        self.acknowledge(request)
        self.close()

    def acknowledge(self, request):
        ack = WriteBootProtocolPacket(self.configuration)
        ack.parameter_order = request.parameter_request_list
        ack.transaction_id = request.transaction_id
        # ack.next_server_ip_address =
        ack.bootp_flags = request.bootp_flags
        ack.relay_agent_ip_address = request.relay_agent_ip_address
        mac = request.client_mac_address
        ack.client_mac_address = mac
        requested_ip_address = request.requested_ip_address
        ack.client_ip_address = request.client_ip_address or '0.0.0.0'
        ack.your_ip_address = self.server.get_ip_address(request)
        ack.dhcp_message_type = 'DHCPACK'
        self.server.broadcast(ack)

    def received_dhcp_inform(self, inform):
        self.close()
        self.server.client_has_chosen(inform)

class DHCPServerConfiguration(object):
    def __init__(self, configuration):
        self.dhcp_offer_after_seconds = 1
        self.dhcp_acknowledge_after_seconds = 1
        self.length_of_transaction = 60

        print(configuration)
        if not configuration:
            print('ERROR: Invalid DHCP configuration!')
            exit(1)

        self.ipaddr = configuration['ipaddr']
        self.iface = configuration['iface']

        network_cidr = ipaddress.IPv4Network(configuration['network'], False)
        self.network = network_cidr.network_address
        self.broadcast_address = network_cidr.broadcast_address
        self.subnet_mask = network_cidr.netmask

        self.router = configuration['router']
        self.domain_name_server = configuration['dns_servers']

        # 1 day is 86400
        self.ip_address_lease_time = 300 # seconds

        self.host_file = 'hosts.csv'

        self.debug = lambda *args, **kw: None

    def all_ip_addresses(self):
        ips = ip_addresses(self.network, self.subnet_mask)
        for i in range(5):
            next(ips)
        return ips

    def network_filter(self):
        return NETWORK(self.network, self.subnet_mask)

def ip_addresses(network, subnet_mask):
    subnet_mask = struct.unpack('>I', inet_aton(subnet_mask))[0]
    network = struct.unpack('>I', inet_aton(network))[0]
    network = network & subnet_mask
    start = network + 1
    end = (network | (~subnet_mask & 0xffffffff))
    return (inet_ntoa(struct.pack('>I', i)) for i in range(start, end))

class ALL(object):
    def __eq__(self, other):
        return True
    def __repr__(self):
        return self.__class__.__name__
ALL = ALL()

class GREATER(object):
    def __init__(self, value):
        self.value = value
    def __eq__(self, other):
        return type(self.value)(other) > self.value

class NETWORK(object):
    def __init__(self, network, subnet_mask):
        self.subnet_mask = struct.unpack('>I', inet_aton(subnet_mask))[0]
        print(self.subnet_mask)
        self.network = struct.unpack('>I', inet_aton(network))[0]
    def __eq__(self, other):
        ip = struct.unpack('>I', inet_aton(other))[0]
        return ip & self.subnet_mask == self.network and \
               ip - self.network and \
               ip - self.network != ~self.subnet_mask & 0xffffffff
        
class CASEINSENSITIVE(object):
    def __init__(self, s):
        self.s = s.lower()
    def __eq__(self, other):
        return self.s == other.lower()

class CSVDatabase(object):

    delimiter = ';'

    def __init__(self, file_name):
        self.file_name = file_name
        self.file('a').close() # create file

    def file(self, mode = 'r'):
        return open(self.file_name, mode)

    def get(self, pattern):
        pattern = list(pattern)
        return [line for line in self.all() if pattern == line]

    def add(self, line):
        with self.file('a') as f:
            f.write(self.delimiter.join(line) + '\n')

    def delete(self, pattern):
        lines = self.all()
        lines_to_delete = self.get(pattern)
        self.file('w').close() # empty file
        for line in lines:
            if line not in lines_to_delete:
                self.add(line)

    def all(self):
        with self.file() as f:
            return [list(line.strip().split(self.delimiter)) for line in f]

class Host(object):

    def __init__(self, mac, ip, hostname, last_used):
        self.mac = mac.upper()
        self.ip = ip
        self.hostname = hostname
        self.last_used = int(last_used)

    @classmethod
    def from_tuple(cls, line):
        mac, ip, hostname, last_used = line
        last_used = int(last_used)
        return cls(mac, ip, hostname, last_used)

    @classmethod
    def from_packet(cls, packet):
        return cls(packet.client_mac_address,
                   packet.requested_ip_address or packet.client_ip_address,
                   packet.host_name or '',
                   int(time.time()))

    @staticmethod
    def get_pattern(mac = ALL, ip = ALL, hostname = ALL, last_used = ALL):
        return [mac, ip, hostname, last_used]

    def to_tuple(self):
        return [self.mac, self.ip, self.hostname, str(int(self.last_used))]

    def to_pattern(self):
        return self.get_pattern(ip = self.ip, mac = self.mac)

    def __hash__(self):
        return hash(self.key)

    def __eq__(self, other):
        return self.to_tuple() == other.to_tuple()

    def has_valid_ip(self):
        return self.ip and self.ip != '0.0.0.0'
        

class HostDatabase(object):
    def __init__(self, file_name):
        self.db = CSVDatabase(file_name)

    def get(self, **kw):
        pattern = Host.get_pattern(**kw)
        return list(map(Host.from_tuple, self.db.get(pattern)))

    def add(self, host):
        self.db.add(host.to_tuple())

    def delete(self, host = None, **kw):
        if host is None:
            pattern = Host.get_pattern(**kw)
        else:
            pattern = host.to_pattern()
        self.db.delete(pattern)

    def all(self):
        return list(map(Host.from_tuple, self.db.all()))

    def replace(self, host):
        self.delete(host)
        self.add(host)
        
def sorted_hosts(hosts):
    hosts = list(hosts)
    hosts.sort(key = lambda host: (host.hostname.lower(), host.mac.lower(), host.ip.lower()))
    return hosts

class DHCPServer(object):

    def __init__(self, configuration):
        self.configuration = configuration
        self.socket = socket(type=SOCK_DGRAM)
        self.socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        self.socket.setsockopt(SOL_SOCKET, 25, self.configuration.iface.encode('ascii'))
        self.socket.bind(('<broadcast>', 67))
        print(self.socket)
        self.delay_worker = DelayWorker()
        self.closed = False
        self.transactions = collections.defaultdict(lambda: Transaction(self)) # id: transaction
        self.hosts = HostDatabase(self.configuration.host_file)
        self.time_started = time.time()

    def close(self):
        self.socket.close()
        self.closed = True
        self.delay_worker.close()
        for transaction in list(self.transactions.values()):
            transaction.close()

    def update(self, timeout = 0):
        try:
            reads = select.select([self.socket], [], [], timeout)[0]
        except ValueError:
            # ValueError: file descriptor cannot be a negative integer (-1)
            return
        for socket in reads:
            try:
                packet = ReadBootProtocolPacket(*socket.recvfrom(4096))
            except OSError:
                # OSError: [WinError 10038] An operation was attempted on something that is not a socket
                pass
            else:
                self.received(packet)
        for transaction_id, transaction in list(self.transactions.items()):
            if transaction.is_done():
                transaction.close()
                self.transactions.pop(transaction_id)

    def received(self, packet):
        if not self.transactions[packet.transaction_id].receive(packet):
            self.configuration.debug('received:\n {}'.format(str(packet).replace('\n', '\n\t')))
            
    def client_has_chosen(self, packet):
        self.configuration.debug('client_has_chosen:\n {}'.format(str(packet).replace('\n', '\n\t')))
        host = Host.from_packet(packet)
        if not host.has_valid_ip():
            return
        self.hosts.replace(host)

    def is_valid_client_address(self, address):
        if address is None:
            return False
        a = address.split('.')
        s = self.configuration.subnet_mask.split('.')
        n = self.configuration.network.split('.')
        return all(s[i] == '0' or a[i] == n[i] for i in range(4))

    def get_ip_address(self, packet):
        mac_address = packet.client_mac_address
        requested_ip_address = packet.requested_ip_address
        known_hosts = self.hosts.get(mac = CASEINSENSITIVE(mac_address))
        ip = None
        if known_hosts:
            # 1. choose known ip address
            for host in known_hosts:
                if self.is_valid_client_address(host.ip):
                    ip = host.ip
            print('known ip:', ip)
        if ip is None and self.is_valid_client_address(requested_ip_address):
            # 2. choose valid requested ip address
            ip = requested_ip_address
            print('valid ip:', ip)
        if ip is None:
            # 3. choose new, free ip address
            chosen = False
            network_hosts = self.hosts.get(ip = self.configuration.network_filter())
            for ip in self.configuration.all_ip_addresses():
                if not any(host.ip == ip for host in network_hosts):
                    chosen = True
                    break
            if not chosen:
                # 4. reuse old valid ip address
                network_hosts.sort(key = lambda host: host.last_used)
                ip = network_hosts[0].ip
                assert self.is_valid_client_address(ip)
            print('new ip:', ip)
        if not any([host.ip == ip for host in known_hosts]):
            print('add', mac_address, ip, packet.host_name)
            self.hosts.replace(Host(mac_address, ip, packet.host_name or '', time.time()))
        return ip

    @property
    def server_identifiers(self):
        return get_host_ip_addresses()

    def broadcast(self, packet):
        self.configuration.debug('broadcasting:\n {}'.format(str(packet).replace('\n', '\n\t')))
        for addr in self.server_identifiers:
            broadcast_socket = socket(type = SOCK_DGRAM)
            broadcast_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
            broadcast_socket.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
            packet.server_identifier = addr
            broadcast_socket.bind((self.configuration.ipaddr, 67))
            try:
                data = packet.to_bytes()
                broadcast_socket.sendto(data, ('255.255.255.255', 68))
                broadcast_socket.sendto(data, (addr, 68))
            finally:
                broadcast_socket.close()

    def run(self):
        while not self.closed:
            try:
                self.update(1)
            except KeyboardInterrupt:
                break
            except:
                traceback.print_exc()

    def start(self):
        self.thread = threading.Thread(target = self.run)
        self.thread.daemon = True
        self.thread.start()

    def debug_clients(self):
        for line in self.ips.all():
            line = '\t'.join(line)
            if line:
                self.configuration.debug(line)

    def get_all_hosts(self):
        return sorted_hosts(self.hosts.get())

    def get_current_hosts(self):
        return sorted_hosts(self.hosts.get(last_used = GREATER(self.time_started)))
