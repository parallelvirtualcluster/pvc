# PVC CLI client manual

The PVC CLI client is built with Click, a Python framework for creating self-documenting CLI applications. It interfaces with the PVC API.

Use the `-h` option at any level of the `pvc` CLI command to receive help about the available commands and options.

Before using the CLI on a non-PVC node system, at least one cluster must be added using the `pvc cluster` subcommands. Running the CLI on hosts which also run the PVC API (via its configuration at `/etc/pvc/pvc-api.yaml`) uses the special `local` cluster, reading information from the API configuration, by default.

## Configuration

The CLI client requires no configuration file. The only optional external environment variable is `PVC_CLUSTER`, which can be used to specify a cluster to connect to.
