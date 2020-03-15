# PVC CLI architecture

The PVC CLI is a standalone client application for PVC. It interfaces with the PVC API, via a configurable list of clusters with customizable hosts, ports, addresses, and authentication.

The CLI is build using Click and is packaged in the Debian package `pvc-client-cli`. The CLI does not depend on any other PVC components and can be used independently on arbitrary systems.

The CLI is self-documenting, however [the manual](/manuals/cli) details the required configuration.

# PVC CLI client manual

The PVC CLI client is built with Click, a Python framework for creating self-documenting CLI applications. It interfaces with the PVC API.

Use the `-h` option at any level of the `pvc` CLI command to receive help about the available commands and options.

Before using the CLI on a non-PVC node system, at least one cluster must be added using the `pvc cluster` subcommands. Running the CLI on hosts which also run the PVC API (via its configuration at `/etc/pvc/pvcapid.yaml`) uses the special `local` cluster, reading information from the API configuration, by default.

## Configuration

The CLI client requires no configuration file. The only optional external environment variable is `PVC_CLUSTER`, which can be used to specify a cluster to connect to.
