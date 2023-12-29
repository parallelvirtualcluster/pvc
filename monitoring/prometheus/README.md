# Prometheus Monitoring for PVC

This example contains a Prometheus config snippit, an example `file_sd_configs` file, and a Grafana dashboard for monitoring a PVC cluster using the inbuilt metrics (`/api/v1/metrics`).

## `prometheus.yml`

This snippit shows how to set up a scrape config leveraging the `file_sd_configs` file.

This example uses `http` transport; if you use HTTPS for PVC API traffic (e.g. if it traverses the Internet), use `https` here. You can optionally disable certificate checking like so:

```
[...]
scheme: "https"
tls_config:
  insecure_skip_verify: true
file_sd_configs:
[...]
```

## `targets-pvc_cluster.json`

This JSON-based config shows two example clusters as two discrete entries. This is required for proper labeling.

Each entry must contain:

* A single `targets` entry, pointing at the API address and port of the PVC cluster.

* Two `labels` which are leveraged by the Grafana dashboard:

   * `pvc_cluster_id`: An identifier for the cluster. Likely, the `Name` in your `pvc connection list` entry for the cluster.

   * `pvc_cluster_name`: A nicer, more human-readable description of the cluster. Likely, the `Description` in your `pvc connection list` entry for the cluster.

## `grafana-pvc-cluster-dashboard.json`

This JSON-based Grafana dashboard allows for a nice presentation of the metrics collected by the above Prometheus pollers. The cluster can be selected (based on the `pvc_cluster_name` value) and useful information about the cluster is then displayed.