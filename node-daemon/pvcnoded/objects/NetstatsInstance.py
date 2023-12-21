#!/usr/bin/env python3

# NetstatsInstance.py - Class implementing a PVC network stats gatherer and run by pvcnoded
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


from apscheduler.schedulers.background import BackgroundScheduler
from collections import deque
from json import dumps
from os import walk
from os.path import exists


class NetstatsIfaceInstance(object):
    """
    NetstatsIfaceInstance

    This class implements a rolling statistics poller for a network interface,
    collecting stats on the bits and packets per second in both directions every
    second.

    Via the get_stats() function, it returns the rolling average of all 4 values,
    as well as totals, over the last 5 seconds (self.avg_samples) as a tuple of:
      (rx_bps, rx_pps, tx_bps, tx_pps, total_bps, total_pps, link_speed, state)
    """

    def __init__(self, logger, iface, avg_samples):
        """
        Initialize the class instance, creating our BackgroundScheduler, setting
        the average sample rate, and creating the deques and average values.
        """
        self.logger = logger
        self.iface = iface

        self.data_valid = False
        self.data_polls = 0

        self.timer = BackgroundScheduler()
        self.timer.add_job(self.gather_stats, trigger="interval", seconds=1)

        self.avg_samples = avg_samples

        self.link_speed = 0
        self.state = "down"

        self.rx_bits_rolling = deque(list(), self.avg_samples + 1)
        self.rx_bps = 0

        self.rx_packets_rolling = deque(list(), self.avg_samples + 1)
        self.rx_pps = 0

        self.tx_bits_rolling = deque(list(), self.avg_samples + 1)
        self.tx_bps = 0

        self.tx_packets_rolling = deque(list(), self.avg_samples + 1)
        self.tx_pps = 0

        self.total_bps = 0
        self.total_pps = 0

    def get_iface_stats(self):
        """
        Reads the interface statistics from the sysfs for the interface.
        """
        iface_state_path = f"/sys/class/net/{self.iface}/operstate"
        with open(iface_state_path) as stfh:
            self.state = stfh.read().strip()

        iface_speed_path = f"/sys/class/net/{self.iface}/speed"
        try:
            with open(iface_speed_path) as spfh:
                # The speed key is always in Mbps so multiply by 1000*1000 to get bps
                self.link_speed = int(spfh.read()) * 1000 * 1000
        except OSError:
            self.link_speed = 0

        iface_stats_path = f"/sys/class/net/{self.iface}/statistics"
        with open(f"{iface_stats_path}/rx_bytes") as rxbfh:
            self.rx_bits_rolling.append(int(rxbfh.read()) * 8)
        with open(f"{iface_stats_path}/tx_bytes") as txbfh:
            self.tx_bits_rolling.append(int(txbfh.read()) * 8)
        with open(f"{iface_stats_path}/rx_packets") as rxpfh:
            self.rx_packets_rolling.append(int(rxpfh.read()) * 8)
        with open(f"{iface_stats_path}/tx_packets") as txpfh:
            self.tx_packets_rolling.append(int(txpfh.read()) * 8)

    def calculate_averages(self):
        """
        Calculates the bps/pps values from the rolling values.
        """

        rx_bits_diffs = list()
        for sample_idx in range(self.avg_samples, 0, -1):
            rx_bits_diffs.append(
                self.rx_bits_rolling[sample_idx] - self.rx_bits_rolling[sample_idx - 1]
            )
        self.rx_bps = int(sum(rx_bits_diffs) / self.avg_samples)

        rx_packets_diffs = list()
        for sample_idx in range(self.avg_samples, 0, -1):
            rx_packets_diffs.append(
                self.rx_packets_rolling[sample_idx]
                - self.rx_packets_rolling[sample_idx - 1]
            )
        self.rx_pps = int(sum(rx_packets_diffs) / self.avg_samples)

        tx_bits_diffs = list()
        for sample_idx in range(self.avg_samples, 0, -1):
            tx_bits_diffs.append(
                self.tx_bits_rolling[sample_idx] - self.tx_bits_rolling[sample_idx - 1]
            )
        self.tx_bps = int(sum(tx_bits_diffs) / self.avg_samples)

        tx_packets_diffs = list()
        for sample_idx in range(self.avg_samples, 0, -1):
            tx_packets_diffs.append(
                self.tx_packets_rolling[sample_idx]
                - self.tx_packets_rolling[sample_idx - 1]
            )
        self.tx_pps = int(sum(tx_packets_diffs) / self.avg_samples)

        self.total_bps = self.rx_bps + self.tx_bps
        self.total_pps = self.rx_pps + self.tx_pps

    def gather_stats(self):
        """
        Gathers the current stats and then calculates the averages.

        Runs via the BackgroundScheduler timer every 1 second.
        """
        self.get_iface_stats()
        if self.data_valid:
            self.calculate_averages()

        # Handle data validity: our data is invalid until we hit enough polls
        # to make a valid average (avg_samples plus 1).
        if not self.data_valid:
            self.data_polls += 1
            if self.data_polls > self.avg_samples:
                self.data_valid = True

    def start(self):
        """
        Starts the timer.
        """
        self.timer.start()

    def stop(self):
        """
        Stops the timer.
        """
        self.timer.shutdown()

    def get_stats(self):
        """
        Returns a tuple of the current statistics.
        """
        if not self.data_valid:
            return None

        return (
            self.rx_bps,
            self.rx_pps,
            self.tx_bps,
            self.tx_pps,
            self.total_bps,
            self.total_pps,
            self.link_speed,
            self.state,
        )


class NetstatsInstance(object):
    """
    NetstatsInstance

    This class implements a rolling statistics poller for all PHYSICAL network interfaces,
    on the system, initializing a NetstatsIfaceInstance for each, as well as handling
    value updates into Zookeeper.
    """

    def __init__(self, logger, config, zkhandler, this_node):
        """
        Initialize the class instance.
        """
        self.logger = logger
        self.config = config
        self.zkhandler = zkhandler
        self.node_name = this_node.name

        self.interfaces = dict()

        self.logger.out(
            f"Starting netstats collector ({self.config['keepalive_interval']} second interval)",
            state="s",
        )

        self.set_interfaces()

    def shutdown(self):
        """
        Stop all pollers and delete the NetstatsIfaceInstance objects
        """
        # Empty the network stats object
        self.zkhandler.write([(("node.network.stats", self.node_name), dumps({}))])

        for iface in self.interfaces.keys():
            self.interfaces[iface].stop()

    def set_interfaces(self):
        """
        Sets the list of interfaces on the system, and then ensures that each
        interface has a NetstatsIfaceInstance assigned to it and polling.
        """
        # Get a list of all active interfaces
        net_root_path = "/sys/class/net"
        all_ifaces = list()
        for (_, dirnames, _) in walk(net_root_path):
            all_ifaces.extend(dirnames)
        all_ifaces.sort()

        self.logger.out(
            f"Parsing network list: {all_ifaces}", state="d", prefix="netstats-thread"
        )

        # Add any missing interfaces
        for iface in all_ifaces:
            if not exists(f"{net_root_path}/{iface}/device"):
                # This is not a physical interface; skip it
                continue

            if iface not in self.interfaces.keys():
                # Set the number of samples to be equal to the keepalive interval, so that each
                # keepalive has a fresh set of data from the last keepalive_interval seconds.
                self.interfaces[iface] = NetstatsIfaceInstance(
                    self.logger, iface, self.config["keepalive_interval"]
                )
                self.interfaces[iface].start()
        # Remove any superfluous interfaces
        for iface in self.interfaces.keys():
            if iface not in all_ifaces:
                self.interfaces[iface].stop()
                del self.interfaces[iface]

    def set_data(self):
        data = dict()
        for iface in self.interfaces.keys():
            self.logger.out(
                f"Getting data for interface {iface}",
                state="d",
                prefix="netstats-thread",
            )
            iface_stats = self.interfaces[iface].get_stats()
            if iface_stats is None:
                continue
            (
                iface_rx_bps,
                iface_rx_pps,
                iface_tx_bps,
                iface_tx_pps,
                iface_total_bps,
                iface_total_pps,
                iface_link_speed,
                iface_state,
            ) = iface_stats
            data[iface] = {
                "rx_bps": iface_rx_bps,
                "rx_pps": iface_rx_pps,
                "tx_bps": iface_tx_bps,
                "tx_pps": iface_tx_pps,
                "total_bps": iface_total_bps,
                "total_pps": iface_total_pps,
                "link_speed": iface_link_speed,
                "state": iface_state,
            }

        self.zkhandler.write([(("node.network.stats", self.node_name), dumps(data))])
