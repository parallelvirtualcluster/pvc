# PVC CLI architecture

The PVC CLI is a standalone client application for PVC. It interfaces with the PVC API, via a configurable list of clusters with customizable hosts, ports, addresses, and authentication.

The CLI is build using Click and is packaged in the Debian package `pvc-client-cli`. The CLI does not depend on any other PVC components and can be used independently on arbitrary systems.

The CLI is self-documenting, however [the manual](/manuals/cli) details the required configuration.
