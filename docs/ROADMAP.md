# Roadmap

Aligned with the *Action Plan for the RAN-Secure Analytics Platform*.
Status legend: ✅ done · 🔄 in progress · ⏳ planned

## Phase 1 – Cloud deployment and demo environment (months 1–6)

| # | Deliverable | Status |
|---|---|---|
| 1.1 | Simulated 4G/5G RAN (gNodeB, eNodeB, cell-site and aggregation routers) | ✅ |
| 1.2 | RAN-SECURE-SIM-MIB KPI model (PRB, RRC SR, drops, throughput, availability) | ✅ |
| 1.3 | OpenNMS + PostgreSQL + Grafana stack as code (docker compose) | ✅ |
| 1.4 | KPI collection and graphs for the simulated RAN | ✅ |
| 1.5 | Fault scenarios: cell outage/restore, site power loss, backhaul flap | ✅ |
| 1.6 | Security scenario: brute-force on OAM interface → critical alarm | ✅ |
| 1.7 | First end-to-end run on a local Docker host, screenshots in `docs/screenshots/` | ⏳ |
| 1.8 | Grafana dashboards as code (`grafana/generate_dashboards.py`): Network Overview and 4G/5G RAN | ✅ |
| 1.9 | Deployment on a public cloud VM behind a TLS reverse proxy (deploy kit ready: `deploy/`) | 🔄 |
| 1.10 | Thresholds (PRB > 80 %, RRC SR < 99 %, drop rate > 0.5 %) generating alarms | ⏳ |
| 1.11 | Project website / landing page with demo request form | ⏳ |
| 1.12 | Time-limited demo accounts (14–30 days) for prospective operators | ⏳ |
| 1.13 | Simulated transport and access network: IP/MPLS core, Ethernet aggregation/access, DWDM optical layer, GPON OLTs (`RAN-SECURE-NET-SIM-MIB`) | ✅ |
| 1.14 | End-to-end topology map from LLDP (radio site to Internet gateway) — verify on the cloud server | 🔄 |
| 1.15 | Transport/access scenarios: DWDM fiber cut with MPLS protection, BGP transit loss, broadcast storm, FTTH power outage vs. PON fiber cut, ONU power degradation — verify alarms on the cloud server | 🔄 |
| 1.16 | Grafana dashboards for transport and access ("IP/MPLS, DWDM and Ethernet", "FTTH / GPON Access") as code | ✅ |

## Phase 2 – Client outreach and pilot testing (months 6–12)

* Outreach to U.S. WISPs, rural cooperatives and municipal networks (WISPA, NTCA, LinkedIn groups).
* Tailored demos with each prospect's element types and KPIs (RAN, IP/MPLS, DWDM, GPON or a mix).
* Letters of Interest from participating providers (target: 3–5).
* Minion-based collection from a pilot network (outbound-only connectivity).
* Measured sizing and performance figures replacing the planning estimates.

## Phase 3 – Optimization and AI integration (months 12–24)

* Anomaly detection on KPI time series (baseline per cell and hour-of-week).
* Cyber-threat indicators on dashboards (auth failures, config changes, unexpected reboots).
* Multi-tenant isolation (locations, Minions, Grafana orgs, per-tenant data).
* Controls mapped to the NIST Cybersecurity Framework 2.0.

## Phase 4 – Commercialization and scaling (years 3–5)

* U.S. entity (LLC), tiered SaaS subscriptions, on-premises option.
* Partnerships with system integrators and rural ISPs.
