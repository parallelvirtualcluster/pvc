# PVC API architecture

The PVC API is a standalone client application for PVC. It interfaces directly with the Zookeeper database to manage state.

The API is built using Flask and is packaged in the Debian package `pvc-client-api`. The API depends on the common client functions of the `pvc-client-common` package as does the CLI client.

Details of the API interface can be found in [the manual](/manuals/api).
