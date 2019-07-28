# PVC CLI architecture

The PVC CLI is a standalone client application for PVC. It interfaces directly with the Zookeeper database to manage state.

The CLI is build using Click and is packaged in the Debian package `pvc-client-cli`. The CLI depends on the common client functions of the `pvc-client-common` package.

The CLI is self-documenting, however [the manual](/manuals/cli) details the required configuration.
