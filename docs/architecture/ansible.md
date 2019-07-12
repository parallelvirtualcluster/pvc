# PVC Ansible architecture

The PVC Ansible setup and management framework is written in Ansible. It consists of two roles: `base` and `pvc`.

## Base role

The Base role configures a node to a specific, standard base Debian system, with a number of PVC-specific tweaks. Some examples include:

* Installing the custom PVC repository at Boniface Labs.

* Removing several unneccessary packages and instaling numerous additional packages.

* Automatically configuring network interfaces based on the `group_vars` configuration.

* Configuring several general `sysctl` settings for optimal performance.

* Installing and configuring rsyslog, postfix, ntpd, ssh, and fail2ban.

* Creating the users sepecified in the `group_vars` configuration.

* Installing custom MOTDs, bashrc files, vimrc files, and other useful configurations for each user.

The end result is a standardized "PVC node" system ready to have the daemons installed by the PVC role.

## PVC role

The PVC role configures all the dependencies of PVC, including storage, networking, and databases, then installs the PVC daemon itself. Specifically, it will, in order:

* Install Ceph, configure and bootstrap a new cluster if `bootstrap=yes` is set, configure the monitor and manager daemons, and start up the cluster ready for the addition of OSDs via the client interface (coordinators only).

* Install, configure, and if `bootstrap=yes` is set, bootstrap a Zookeeper cluster (coordinators only).

* Install, configure, and if `bootstrap=yes` is set`, bootstrap a Patroni Postgresql cluster for the PowerDNS aggregator (coordinators only).

* Install and configure Libvirt.

* Install and configure FRRouting.

* Install and configure the main PVC daemon and API client, including initializing the PVC cluster (`pvc init`).

## Completion

Once the entire playbook has run for the first time against a given host, the host will be rebooted to apply all the configured services. On startup, the system should immediately launch the PVC daemon, check in to the Zookeeper cluster, and become ready. The node will be in `flushed` state on its first boot; the administrator will need to run `pvc node unflush <node>` to set the node into active state ready to handle virtual machines.
