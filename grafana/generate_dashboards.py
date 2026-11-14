#!/usr/bin/env python3
"""
RAN-Secure Analytics Platform - Grafana dashboards as code.

Builds the provisioned dashboards from the same topology definition the simulator
uses (simulator/generate_snmprec.py + transport_model.py), so node, resource and
interface ids always match what OpenNMS collects:

    grafana/provisioning/dashboards/ran-secure/*.json

Queries use the OpenNMS Plugin for Grafana (performance + entity datasources):
  * node ids are "RAN-Sim:<foreign-id>" (requisition RAN-Sim)
  * resource ids follow OpenNMS: nodeSnmp[], <resourceType>[<index>],
    interfaceSnmp[<ifName sanitized>-<MAC>]
  * values stored in engineering units (0.01 dBm, octets/s ...) are converted with
    measurement-API expressions on hidden attribute queries

Usage:  python3 grafana/generate_dashboards.py
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "simulator"))

import generate_snmprec as gen  # noqa: E402
import transport_model as tm    # noqa: E402

OUT = HERE / "provisioning" / "dashboards" / "ran-secure"
FS = "RAN-Sim"
TAGS = ["ran-secure"]
PERF = {"type": "opennms-performance-datasource", "uid": "${ds_perf}"}
ENTITY = {"type": "opennms-entity-datasource", "uid": "${ds_entity}"}

DEV_INDEX = {d["name"]: i for i, d, _ in gen.all_devices()}
DEV = {d["name"]: d for _, d, _ in gen.all_devices()}

# Severity-like palette used across dashboards
GREEN, ORANGE, RED, BLUE = "green", "orange", "red", "blue"


# --------------------------------------------------------------------------- ids
def iface_resource(dev, ifname):
    """interfaceSnmp resource id, as OpenNMS names the RRD directory."""
    idx = [n for _, n, _ in gen.ports(DEV[dev])].index(ifname) + 1
    mac = gen.mac(DEV_INDEX[dev], idx)[1]
    return f"interfaceSnmp[{re.sub(r'[^A-Za-z0-9]', '_', ifname)}-{mac}]"


def if_index(dev, ifname):
    return [n for _, n, _ in gen.ports(DEV[dev])].index(ifname) + 1


# ------------------------------------------------------------------- queries
class Q:
    """Collects the targets of one panel and hands out refIds."""

    def __init__(self):
        self.targets = []
        self.n = 0

    def _ref(self):
        self.n += 1
        n, ref = self.n, ""
        while n:
            n, r = divmod(n - 1, 26)
            ref = chr(65 + r) + ref
        return ref

    def attr(self, node, resource, attribute, label, hide=False, agg="AVERAGE"):
        self.targets.append({
            "refId": self._ref(), "datasource": PERF, "hide": hide,
            "performanceType": {"label": "Attribute", "value": 1},
            "attribute": {
                "node": {"id": f"{FS}:{node}", "label": node},
                "resource": {"id": resource, "label": resource},
                "attribute": {"name": attribute},
                "aggregation": {"label": agg},
                "label": label,
            },
        })
        return label

    def expr(self, label, expression):
        self.targets.append({
            "refId": self._ref(), "datasource": PERF,
            "performanceType": {"label": "Expression", "value": 2},
            "label": label, "expression": expression,
        })

    def scaled(self, node, resource, attribute, label, factor):
        """Series = attribute * factor (hidden source + visible expression)."""
        if factor == 1:
            return self.attr(node, resource, attribute, label)
        src = f"v{self.n + 1}"
        self.attr(node, resource, attribute, src, hide=True)
        # plain decimal literal (JEXL does not need to parse exponents)
        self.expr(label, f"{src} * {f'{factor:.12f}'.rstrip('0').rstrip('.') if factor < 1 else factor}")

    def total(self, label, parts):
        """Visible sum of several hidden sources: parts = [(node, resource, attribute)]."""
        names = [self.attr(n, r, a, f"t{self.n + 1}", hide=True) for n, r, a in parts]
        self.expr(label, " + ".join(names))

    def traffic(self, node, ifname, label):
        res = iface_resource(node, ifname)
        self.scaled(node, res, "ifHCInOctets", f"{label} in", 8)
        self.scaled(node, res, "ifHCOutOctets", f"{label} out", 8)


# -------------------------------------------------------------------- panels
class Layout:
    def __init__(self):
        self.panels, self.y, self.x, self.row_h, self.pid = [], 0, 0, 0, 0

    def _id(self):
        self.pid += 1
        return self.pid

    def row(self, title):
        if self.x:
            self.y += self.row_h
            self.x, self.row_h = 0, 0
        self.panels.append({"type": "row", "title": title, "id": self._id(), "collapsed": False,
                            "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.y}, "panels": []})
        self.y += 1

    def add(self, panel, w, h):
        if self.x + w > 24:
            self.y += self.row_h
            self.x, self.row_h = 0, 0
        panel["id"] = self._id()
        panel["gridPos"] = {"h": h, "w": w, "x": self.x, "y": self.y}
        self.panels.append(panel)
        self.x += w
        self.row_h = max(self.row_h, h)


def thresholds(steps):
    """steps = [(None, color), (value, color), ...]"""
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for v, c in steps]}


def timeseries(title, q, unit="short", desc="", steps=None, lo=None, hi=None, log=False,
               fill=10, decimals=None, stack=False):
    custom = {"lineWidth": 2, "fillOpacity": fill, "showPoints": "never", "spanNulls": True,
              "thresholdsStyle": {"mode": "line+area" if steps else "off"}}
    if log:
        custom["scaleDistribution"] = {"type": "log", "log": 10}
    if stack:
        custom["stacking"] = {"mode": "normal", "group": "A"}
    defaults = {"unit": unit, "custom": custom, "color": {"mode": "palette-classic"},
                "thresholds": thresholds(steps or [(None, "transparent")])}
    if lo is not None:
        defaults["min"] = lo
    if hi is not None:
        defaults["max"] = hi
    if decimals is not None:
        defaults["decimals"] = decimals
    return {"type": "timeseries", "title": title, "description": desc, "datasource": PERF,
            "targets": q.targets, "fieldConfig": {"defaults": defaults, "overrides": []},
            "options": {"legend": {"displayMode": "table", "placement": "bottom",
                                   "calcs": ["lastNotNull", "min", "max"]},
                        "tooltip": {"mode": "multi", "sort": "none"}}}


def stat(title, q, unit="short", desc="", steps=None, mappings=None, decimals=None, graph=True):
    defaults = {"unit": unit, "color": {"mode": "thresholds"},
                "thresholds": thresholds(steps or [(None, BLUE)]),
                "mappings": mappings or []}
    if decimals is not None:
        defaults["decimals"] = decimals
    return {"type": "stat", "title": title, "description": desc, "datasource": PERF,
            "targets": q.targets, "fieldConfig": {"defaults": defaults, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "colorMode": "background", "graphMode": "area" if graph else "none",
                        "textMode": "auto", "justifyMode": "auto", "orientation": "auto"}}


def value_map(pairs):
    return [{"type": "value", "options": {str(v): {"text": t, "color": c, "index": i}
                                          for i, (v, t, c) in enumerate(pairs)}}]


ALARM_COLUMNS = [
    {"label": "Severity", "value": 5}, {"label": "Is Acknowledged", "value": 20},
    {"label": "Count", "value": 1}, {"label": "Last Event Time", "value": 23},
    {"label": "Node Label", "value": 14}, {"label": "Log Message", "value": 9},
]


def alarm_table(title, desc=""):
    return {
        "type": "opennms-alarm-table-panel", "title": title, "description": desc, "datasource": ENTITY,
        "targets": [{
            "refId": "A", "datasource": ENTITY, "selectType": {"label": "Alarms"},
            "filter": {"limit": 100,
                       "clauses": [{"restriction": {"attribute": "severity", "comparator": {"label": "NE"},
                                                    "value": "CLEARED"},
                                    "operator": {"label": "AND"}}],
                       "orderBy": [{"attribute": "lastEventTime", "order": {"label": "DESC"}}]},
        }],
        "fieldConfig": {"defaults": {}, "overrides": []},
        "options": {"alarmTable": {
            "alarmTableAdditional": {"displayActionNotice": True, "useGrafanaUser": False},
            "alarmTableAlarms": {"styleWithSeverity": {"label": "Column", "value": 1},
                                 "severityTheme": {"label": "Default", "value": 0}},
            "alarmTableData": {"columns": ALARM_COLUMNS},
            "alarmTablePaging": {"pauseRefresh": False, "scroll": True, "rowsPerPage": 10,
                                 "fontSize": {"label": "100%", "value": 2}},
            "alarmTableColumnSizes": {"active": False, "columnSizes": []},
        }},
    }


def text(title, content):
    return {"type": "text", "title": title, "options": {"mode": "markdown", "content": content}}


def dashboard(uid, title, description, layout, extra_vars=None, time_from="now-6h"):
    variables = [
        {"name": "ds_perf", "label": "Performance datasource", "type": "datasource",
         "query": "opennms-performance-datasource", "hide": 2, "current": {}, "options": [],
         "refresh": 1, "regex": "", "includeAll": False, "multi": False},
        {"name": "ds_entity", "label": "Entity datasource", "type": "datasource",
         "query": "opennms-entity-datasource", "hide": 2, "current": {}, "options": [],
         "refresh": 1, "regex": "", "includeAll": False, "multi": False},
    ] + (extra_vars or [])
    return {
        "uid": uid, "title": title, "description": description, "tags": TAGS,
        "editable": True, "graphTooltip": 1, "refresh": "1m", "schemaVersion": 39,
        "time": {"from": time_from, "to": "now"}, "timezone": "browser",
        "templating": {"list": variables},
        "links": [{"type": "dashboards", "tags": TAGS, "asDropdown": False, "includeVars": False,
                   "keepTime": True, "title": "RAN-Secure", "icon": "external link"}],
        "panels": layout.panels, "annotations": {"list": []},
    }


# ---------------------------------------------------------------- dashboards
DBM, DB = "suffix: dBm", "suffix: dB"
OLTS = [d for d in tm.DEVICES if d["kind"] == "OLT"]
PEERS = [("pe-core-02", 1, "Transit-A AS64500"), ("pe-core-02", 2, "iBGP from pe-core-01"),
         ("pe-core-01", 1, "iBGP from pe-core-02"), ("pe-core-01", 2, "IX peering AS64501")]
LSPS = [("pe-core-01", n, name) for n, (name, *_r) in enumerate(DEV["pe-core-01"]["lsps"], 1)] + \
       [("pe-core-02", n, name) for n, (name, *_r) in enumerate(DEV["pe-core-02"]["lsps"], 1)]
LINE_PORTS = [("roadm-01", "LINE-E", "roadm-01 LINE-E (span 1)"), ("ila-01", "LINE-W", "ila-01 LINE-W (span 1)"),
              ("ila-01", "LINE-E", "ila-01 LINE-E (span 2)"), ("roadm-02", "LINE-W", "roadm-02 LINE-W (span 2)")]
CH_PORTS = [(r, ch, f"{r} {ch}") for r in ("roadm-01", "roadm-02") for ch in ("CH-1", "CH-2")]


def pon_ports(olt):
    """[(ifIndex, ifName, zone, onus)] of an OLT."""
    return [(n + 2, f"gpon-0/1/{n}", zone, onus) for n, (zone, onus) in enumerate(olt["pons"], start=1)]


def overview():
    L = Layout()
    L.add(text("RAN-Secure Analytics Platform", (
        "**Simulated end-to-end network of a small operator** monitored with open-source tools "
        "(OpenNMS Horizon + Grafana): 4G/5G RAN, IP/MPLS core, DWDM optical transport, Ethernet "
        "aggregation and GPON/FTTH access. Use the links at the top for each domain. "
        "All elements are simulated; no customer network is involved.")), 24, 3)

    q = Q()
    q.total("ONUs online", [(o["name"], f"rsPonPortEntry[{i}]", "rsPonOnusOnline")
                            for o in OLTS for i, *_ in pon_ports(o)])
    L.add(stat("FTTH subscribers online", q, decimals=0, desc="ONUs in operation on all PONs of both OLTs."), 4, 5)

    q = Q()
    q.attr("pe-core-02", "rsBgpPeerEntry[1]", "rsBgpPeerState", "Transit-A")
    L.add(stat("Internet transit (BGP)", q, graph=False, steps=[(None, RED), (6, GREEN)],
               mappings=value_map([(6, "Established", GREEN), (1, "Down (idle)", RED), (3, "Active", ORANGE)]),
               desc="BGP session to the upstream transit provider on pe-core-02."), 4, 5)

    q = Q()
    q.attr("pe-core-01", "rsLspEntry[1]", "rsLspActivePath", "LSP-PE1-PE2-GOLD")
    L.add(stat("Core LSP path", q, graph=False, steps=[(None, GREEN), (2, ORANGE)],
               mappings=value_map([(1, "Primary", GREEN), (2, "Protected (secondary)", ORANGE)]),
               desc="Active path of the GOLD LSP between the two core POPs."), 4, 5)

    q = Q()
    q.scaled("roadm-02", f"rsOptPortEntry[{if_index('roadm-02', 'LINE-W')}]", "rsOptRxPower", "Rx", 0.01)
    L.add(stat("DWDM span 2 Rx power", q, unit=DBM, decimals=2, steps=[(None, RED), (-30, GREEN)],
               desc="Received power at roadm-02 LINE-W. Below -30 dBm = loss of signal."), 4, 5)

    q = Q()
    q.attr("sw-access-01", "nodeSnmp[]", "rsChassisCpuLoad", "CPU")
    L.add(stat("Enterprise access switch CPU", q, unit="percent", decimals=0,
               steps=[(None, GREEN), (70, ORANGE), (85, RED)], desc="sw-access-01 control-plane CPU."), 4, 5)

    q = Q()
    q.total("UEs", [(d["name"], "nodeSnmp[]", "ranNodeUEs") for d in gen.DEVICES if d["cells"]])
    L.add(stat("Mobile users connected", q, decimals=0, desc="RRC-connected UEs on all 4G/5G sites."), 4, 5)

    L.add(alarm_table("Active alarms - all domains",
                      "Alarms that are not cleared, newest first. Acknowledge or clear from the row menu."), 24, 9)

    q = Q()
    q.traffic("pe-core-02", "et-0/2/0", "Transit-A")
    L.add(timeseries("Internet transit traffic (pe-core-02 et-0/2/0)", q, unit="bps"), 12, 8)
    q = Q()
    q.traffic("pe-core-01", "xe-0/0/0", "Mobile backhaul")
    L.add(timeseries("Mobile backhaul into the core (pe-core-01 xe-0/0/0)", q, unit="bps"), 12, 8)
    return dashboard("rs-overview", "RAN-Secure - Network Overview",
                     "End-to-end status of the simulated operator network", L)


def ran():
    L = Layout()
    nodes = [d["name"] for d in gen.DEVICES if d["cells"]]
    var = {"name": "site", "label": "Radio site", "type": "custom", "query": ",".join(nodes),
           "current": {"text": nodes[0], "value": nodes[0]},
           "options": [{"text": n, "value": n, "selected": n == nodes[0]} for n in nodes],
           "hide": 0, "includeAll": False, "multi": False}
    sectors = ["A", "B", "C"]

    L.row("Site $site - baseband")
    q = Q()
    q.attr("$site", "nodeSnmp[]", "ranNodeCpuLoad", "CPU")
    L.add(timeseries("Baseband CPU load", q, unit="percent", lo=0, hi=100,
                     steps=[(None, "transparent"), (80, RED)]), 8, 8)
    q = Q()
    q.attr("$site", "nodeSnmp[]", "ranNodeTemp", "Temperature")
    L.add(timeseries("Board temperature", q, unit="celsius", steps=[(None, "transparent"), (70, RED)]), 8, 8)
    q = Q()
    q.attr("$site", "nodeSnmp[]", "ranNodeUEs", "Connected UEs")
    L.add(timeseries("RRC-connected UEs", q, fill=25), 8, 8)

    L.row("Site $site - cells (sectors A, B, C)")
    panels = [
        ("PRB utilization (downlink)", "ranPrbDlUtil", 1, "percent", [(None, "transparent"), (80, RED)], 0, 100),
        ("RRC setup success rate", "ranRrcSuccRate", 0.01, "percent", [(None, RED), (99, "transparent")], None, None),
        ("Session drop rate", "ranDropRate", 0.01, "percent", [(None, "transparent"), (0.5, RED)], 0, None),
        ("Downlink throughput", "ranDlThroughput", 1000, "bps", None, 0, None),
        ("Active UEs per cell", "ranActiveUEs", 1, "short", None, 0, None),
        ("Cell availability", "ranAvailability", 0.01, "percent", [(None, RED), (99.9, "transparent")], None, 100),
    ]
    for title, attribute, factor, unit, steps, lo, hi in panels:
        q = Q()
        for c, s in enumerate(sectors, start=1):
            q.scaled("$site", f"ranCellEntry[{c}]", attribute, f"Sector {s}", factor)
        L.add(timeseries(title, q, unit=unit, steps=steps, lo=lo, hi=hi, fill=5), 8, 8)
    return dashboard("rs-ran", "RAN-Secure - 4G/5G RAN", "Baseband health and cell KPIs per radio site",
                     L, extra_vars=[var])


def core():
    L = Layout()
    L.row("IP/MPLS core")
    for node, n, name in LSPS:
        q = Q()
        q.attr(node, f"rsLspEntry[{n}]", "rsLspActivePath", name)
        L.add(stat(f"{name}", q, graph=False, steps=[(None, GREEN), (2, ORANGE)],
                   mappings=value_map([(1, "Primary", GREEN), (2, "Secondary (protected)", ORANGE)]),
                   desc=f"Active path of {name} on {node}."), 6, 4)
    q = Q()
    for node, n, name in LSPS:
        q.scaled(node, f"rsLspEntry[{n}]", "rsLspLatency", name, 0.001)
    L.add(timeseries("LSP one-way latency", q, unit="ms", fill=0, decimals=2,
                     desc="Rises when the LSPs move to the longer diverse route."), 12, 8)
    q = Q()
    for node, n, name in LSPS:
        q.attr(node, f"rsLspEntry[{n}]", "rsLspBwUtil", name)
    L.add(timeseries("LSP utilization (of reserved bandwidth)", q, unit="percent", lo=0, hi=100, fill=0,
                     steps=[(None, "transparent"), (85, RED)]), 12, 8)

    q = Q()
    q.traffic("pe-core-01", "et-0/1/0", "Primary (DWDM lambda 1)")
    q.traffic("pe-core-01", "et-0/1/1", "Diverse route")
    L.add(timeseries("Core links of pe-core-01: primary vs. diverse route", q, unit="bps", fill=5,
                     desc="During a fiber cut the primary drops to zero and the diverse route takes the load."),
          12, 8)
    q = Q()
    for node, n, name in PEERS:
        q.attr(node, f"rsBgpPeerEntry[{n}]", "rsBgpPfxRx", f"{node}: {name}")
    L.add(timeseries("BGP prefixes received", q, fill=0, lo=0), 12, 8)

    L.row("DWDM optical transport")
    q = Q()
    for node, port, label in LINE_PORTS:
        q.scaled(node, f"rsOptPortEntry[{if_index(node, port)}]", "rsOptRxPower", label, 0.01)
    L.add(timeseries("Line receive power per span", q, unit=DBM, fill=0, decimals=2,
                     steps=[(None, RED), (-30, "transparent")],
                     desc="Red area = loss of signal (below -30 dBm)."), 12, 8)
    q = Q()
    for node, port, label in CH_PORTS:
        q.scaled(node, f"rsOptPortEntry[{if_index(node, port)}]", "rsOptOsnr", label, 0.01)
    L.add(timeseries("Channel OSNR", q, unit=DB, fill=0, decimals=1, lo=0,
                     steps=[(None, RED), (15, "transparent")], desc="Minimum margin 15 dB."), 12, 8)
    q = Q()
    for node, port, label in CH_PORTS:
        q.scaled(node, f"rsOptPortEntry[{if_index(node, port)}]", "rsOptPreFecBer", label, 1e-9)
    L.add(timeseries("Channel pre-FEC bit error ratio", q, unit="sci", fill=0, log=True,
                     steps=[(None, "transparent"), (0.0038, RED)], desc="HD-FEC limit 3.8E-3."), 12, 8)
    q = Q()
    q.traffic("roadm-01", "CH-2", "WS-0042")
    L.add(timeseries("Wholesale circuit WS-0042 (lambda 2) traffic", q, unit="bps", fill=5,
                     desc="Carrier customer on wavelength 2: the customer impact of a DWDM fiber cut."), 12, 8)

    L.row("Ethernet aggregation and enterprise access")
    q = Q()
    for port in ("ge-0/0/1", "ge-0/0/2", "ge-0/0/3", "ge-0/0/4"):
        alias = DEV["sw-access-01"]["ifaces"][if_index("sw-access-01", port) - 1][1].split(" (")[0]
        q.attr("sw-access-01", iface_resource("sw-access-01", port), "rsIfInBcastPkts", f"{port} {alias}")
    L.add(timeseries("Broadcast packets per customer port (sw-access-01)", q, unit="pps", fill=0, log=True,
                     steps=[(None, "transparent"), (1000, RED)], desc="Storm-control threshold 1000 pps."), 12, 8)
    q = Q()
    q.attr("sw-access-01", "nodeSnmp[]", "rsChassisCpuLoad", "sw-access-01 CPU")
    q.attr("sw-agg-01", "nodeSnmp[]", "rsChassisCpuLoad", "sw-agg-01 CPU")
    L.add(timeseries("Switch CPU", q, unit="percent", lo=0, hi=100, fill=0,
                     steps=[(None, "transparent"), (85, RED)]), 6, 8)
    q = Q()
    q.attr("sw-access-01", "nodeSnmp[]", "rsSwMacEntries", "sw-access-01")
    q.attr("sw-agg-01", "nodeSnmp[]", "rsSwMacEntries", "sw-agg-01")
    L.add(timeseries("Learned MAC addresses", q, fill=0, lo=0), 6, 8)
    return dashboard("rs-core", "RAN-Secure - IP/MPLS, DWDM and Ethernet",
                     "Core transport: MPLS LSPs and BGP, DWDM optical layer, Ethernet aggregation", L)


def ftth():
    L = Layout()
    for olt in OLTS:
        q = Q()
        q.total("Online", [(olt["name"], f"rsPonPortEntry[{i}]", "rsPonOnusOnline") for i, *_ in pon_ports(olt)])
        registered = sum(o for *_, o in pon_ports(olt))
        L.add(stat(f"{olt['name']}: ONUs online (of {registered})", q, decimals=0,
                   steps=[(None, RED), (registered * 0.9, ORANGE), (registered * 0.97, GREEN)]), 6, 5)
        q = Q()
        q.traffic(olt["name"], olt["uplink"][0], "Uplink")
        L.add(timeseries(f"{olt['name']} uplink traffic", q, unit="bps", fill=5), 6, 5)

    for olt in OLTS:
        L.row(f"{olt['name']} - {olt['location'].split(' (')[0]}")
        q = Q()
        for i, name, zone, _ in pon_ports(olt):
            q.attr(olt["name"], f"rsPonPortEntry[{i}]", "rsPonOnusOnline", f"{name} {zone}")
        L.add(timeseries("ONUs online per PON", q, fill=0, lo=0,
                         desc="A sudden drop with dying gasp = power outage; without = fiber cut."), 12, 9)
        q = Q()
        for i, name, zone, _ in pon_ports(olt):
            q.scaled(olt["name"], f"rsPonPortEntry[{i}]", "rsPonRxWorst", f"{name} {zone}", 0.01)
        L.add(timeseries("Worst ONU receive power per PON", q, unit=DBM, fill=0, decimals=2, lo=-32, hi=-15,
                         steps=[(None, RED), (-28, ORANGE), (-27, "transparent")],
                         desc="Alarm threshold -27 dBm; class B+ ONUs stop working near -28 dBm."), 12, 9)
        q = Q()
        for i, name, zone, _ in pon_ports(olt):
            q.attr(olt["name"], f"rsPonPortEntry[{i}]", "rsPonDlUtil", f"{name} {zone}")
        L.add(timeseries("Downstream PON utilization", q, unit="percent", fill=0, lo=0, hi=100,
                         steps=[(None, "transparent"), (70, ORANGE)], desc="Capacity planning threshold 70 %."),
              12, 8)
        q = Q()
        for i, name, zone, _ in pon_ports(olt):
            q.scaled(olt["name"], f"rsPonPortEntry[{i}]", "rsPonRxAvg", f"{name} {zone}", 0.01)
        L.add(timeseries("Average ONU receive power per PON", q, unit=DBM, fill=0, decimals=2), 12, 8)
    return dashboard("rs-ftth", "RAN-Secure - FTTH / GPON Access",
                     "ONUs online, ONU optical levels and PON load per OLT", L)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in (("overview", overview), ("ran", ran), ("core", core), ("ftth", ftth)):
        dash = build()
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(dash, indent=2) + "\n")
        n = sum(1 for p in dash["panels"] if p["type"] != "row")
        print(f"{path.relative_to(HERE.parent)}: {n} panels")


if __name__ == "__main__":
    main()
