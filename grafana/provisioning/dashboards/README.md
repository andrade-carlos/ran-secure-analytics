# Dashboards

Provisioned automatically into the Grafana folder **RAN-Secure** (`ran-secure.yaml`):

| File | Dashboard |
|---|---|
| `ran-secure/overview.json` | Network Overview: key status per domain, active alarms, transit and backhaul traffic |
| `ran-secure/ran.json` | 4G/5G RAN: baseband health and per-sector KPIs, one radio site at a time |
| `ran-secure/core.json` | IP/MPLS (LSP path, latency, BGP), DWDM (power, OSNR, pre-FEC BER), Ethernet (broadcast, CPU, MACs) |
| `ran-secure/ftth.json` | FTTH / GPON: ONUs online, ONU receive power and PON load per OLT |

The JSON files are generated from the simulated topology, so node and resource ids always
match what OpenNMS collects. After changing the topology or a dashboard:

```bash
python3 grafana/generate_dashboards.py
```

Grafana re-reads the folder every 60 seconds. Changes made in the Grafana UI are allowed but
are overwritten when the file changes; to keep a UI change, export the dashboard
(Share > Export) and port it to the generator.
