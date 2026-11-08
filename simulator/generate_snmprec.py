#!/usr/bin/env python3
"""
RAN-Secure Analytics Platform - simulated 4G/5G RAN generator.

Generates one snmpsim data file (.snmprec) per simulated network element.
Each element exposes:
  * SNMPv2-MIB system group (sysDescr, sysObjectID, sysUpTime, sysName ...)
  * IF-MIB interfaces (ifTable + ifXTable, 32/64-bit traffic counters)
  * IP-MIB ipAddrTable (so OpenNMS can map the management IP to an ifIndex)
  * RAN-SECURE-SIM-MIB (gNodeB/eNodeB only): node health and per-cell KPIs

All private OIDs live under enterprise 32473, which RFC 5612 reserves for
documentation and examples, so the simulator never collides with a real
vendor MIB.

Usage:
    python3 generate_snmprec.py            # writes ./data/<device>/public.snmprec
    python3 generate_snmprec.py --out DIR
"""
import argparse
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent

# --- OID roots -----------------------------------------------------------
SYS = "1.3.6.1.2.1.1"
IF_TABLE = "1.3.6.1.2.1.2.2.1"
IF_NUMBER = "1.3.6.1.2.1.2.1.0"
IP_ADDR = "1.3.6.1.2.1.4.20.1"
IFX_TABLE = "1.3.6.1.2.1.31.1.1.1"
ENT = "1.3.6.1.4.1.32473"          # RFC 5612 documentation enterprise
RAN = f"{ENT}.5"                    # ranSecureSim
RAN_NODE = f"{RAN}.1"               # scalars
RAN_CELL = f"{RAN}.2.1.1"           # ranCellTable.ranCellEntry
PRODUCTS = f"{RAN}.100"             # sysObjectID values

# --- snmprec tags ----------------------------------------------------------
INT, STR, OID, IPADDR, C32, G32, TT, C64 = "2", "4", "6", "64", "65", "66", "67", "70"

# Base time unit for sine-wave KPIs: ~1.7 h period (rate in rad/s)
SLOW = 0.001
FAST = 0.004


def gauge_wave(center, amplitude, lo=0, hi=100, rate=SLOW):
    """Gauge that oscillates smoothly around `center` (snmpsim numeric module)."""
    return (f"{G32}:numeric",
            f"function=sin,rate={rate:.6g},scale={amplitude},offset={center},"
            f"initial=0,min={lo},max={hi}")


def counter(rate_per_s, bits=64):
    """Monotonic traffic counter that grows at `rate_per_s` octets/second."""
    if bits == 64:
        return (f"{C64}:numeric", f"rate={rate_per_s},initial=0,wrap=1,max=18446744073709551615")
    return (f"{C32}:numeric", f"rate={rate_per_s},initial=0,wrap=1,max=4294967295")


def mac(device_idx, if_idx):
    # Locally administered MAC (02:...) as hex-encoded OCTET STRING (snmprec tag 4x)
    return "4x", f"02a0c9{device_idx:02x}{if_idx:02x}01"


# --- Topology definition ---------------------------------------------------
# Fictional sites; IPs match docker-compose.yml (network 172.30.0.0/24).
DEVICES = [
    {
        "name": "gnb-site-101", "ip": "172.30.0.11", "kind": "gNodeB",
        "location": "Site 101 - Urban macro (simulated)",
        "cells": [("NR-101-A", "NR", 62, 18), ("NR-101-B", "NR", 48, 15), ("NR-101-C", "NR", 35, 12)],
    },
    {
        "name": "gnb-site-102", "ip": "172.30.0.12", "kind": "gNodeB",
        "location": "Site 102 - Suburban macro (simulated)",
        "cells": [("NR-102-A", "NR", 41, 14), ("NR-102-B", "NR", 55, 20), ("NR-102-C", "NR", 29, 10)],
    },
    {
        "name": "enb-rural-201", "ip": "172.30.0.21", "kind": "eNodeB",
        "location": "Site 201 - Rural coverage (simulated)",
        "cells": [("LTE-201-A", "LTE", 22, 9), ("LTE-201-B", "LTE", 18, 7), ("LTE-201-C", "LTE", 12, 5)],
    },
    {
        "name": "enb-rural-202", "ip": "172.30.0.22", "kind": "eNodeB",
        "location": "Site 202 - Rural coverage (simulated)",
        "cells": [("LTE-202-A", "LTE", 30, 10), ("LTE-202-B", "LTE", 26, 9), ("LTE-202-C", "LTE", 15, 6)],
    },
    {
        "name": "csr-hub-01", "ip": "172.30.0.31", "kind": "CellSiteRouter",
        "location": "Hub 01 - Cell site aggregation (simulated)", "cells": [],
    },
    {
        "name": "agg-core-01", "ip": "172.30.0.41", "kind": "AggregationRouter",
        "location": "Core POP - Backhaul aggregation (simulated)", "cells": [],
    },
]

SYS_OBJECT_ID = {
    "gNodeB": f"{PRODUCTS}.1",
    "eNodeB": f"{PRODUCTS}.2",
    "CellSiteRouter": f"{ENT}.6.1",
    "AggregationRouter": f"{ENT}.6.2",
}

SYS_DESCR = {
    "gNodeB": "RAN-Secure Simulated gNodeB (5G NR SA/NSA), SW 1.0-sim",
    "eNodeB": "RAN-Secure Simulated eNodeB (4G LTE), SW 1.0-sim",
    "CellSiteRouter": "RAN-Secure Simulated Cell Site Router (IP/MPLS backhaul), SW 1.0-sim",
    "AggregationRouter": "RAN-Secure Simulated Aggregation Router (IP/MPLS core), SW 1.0-sim",
}

# Interfaces per device kind: (name, alias, speed_mbps, avg_in_Bps, avg_out_Bps)
INTERFACES = {
    "gNodeB": [("eth0", "MGMT / OAM", 1000, 20_000, 15_000),
               ("eth1", "Backhaul to csr-hub-01 (N2/N3)", 10000, 90_000_000, 35_000_000),
               ("eth2", "Fronthaul eCPRI to RU", 25000, 120_000_000, 60_000_000)],
    "eNodeB": [("eth0", "MGMT / OAM", 1000, 15_000, 10_000),
               ("eth1", "Backhaul to csr-hub-01 (S1/X2)", 1000, 25_000_000, 9_000_000)],
    "CellSiteRouter": [("ge-0/0/0", "MGMT", 1000, 10_000, 10_000),
                       ("ge-0/0/1", "To gnb-site-101", 10000, 35_000_000, 90_000_000),
                       ("ge-0/0/2", "To gnb-site-102", 10000, 30_000_000, 80_000_000),
                       ("ge-0/0/3", "To enb-rural-201", 1000, 9_000_000, 25_000_000),
                       ("ge-0/0/4", "To enb-rural-202", 1000, 8_000_000, 22_000_000),
                       ("xe-0/1/0", "Uplink to agg-core-01", 10000, 200_000_000, 80_000_000)],
    "AggregationRouter": [("ge-0/0/0", "MGMT", 1000, 10_000, 10_000),
                          ("xe-0/1/0", "Downlink csr-hub-01", 10000, 80_000_000, 200_000_000),
                          ("xe-0/1/1", "Uplink to Internet/Core", 100000, 210_000_000, 600_000_000)],
}


def oid_key(oid):
    return tuple(int(p) for p in oid.split("."))


def build_records(dev_idx, dev):
    recs = {}

    def put(oid, tag, value):
        recs[oid] = (tag, value)

    kind = dev["kind"]
    # system group
    put(f"{SYS}.1.0", STR, SYS_DESCR[kind])
    put(f"{SYS}.2.0", OID, SYS_OBJECT_ID[kind])
    put(f"{SYS}.3.0", f"{TT}:numeric", "rate=100,initial=0")
    put(f"{SYS}.4.0", STR, "noc@ran-secure.example")
    put(f"{SYS}.5.0", STR, dev["name"])
    put(f"{SYS}.6.0", STR, dev["location"])
    put(f"{SYS}.7.0", INT, "78")

    # interfaces
    ifs = INTERFACES[kind]
    put(IF_NUMBER, INT, str(len(ifs)))
    for i, (name, alias, speed, rx, tx) in enumerate(ifs, start=1):
        put(f"{IF_TABLE}.1.{i}", INT, str(i))
        put(f"{IF_TABLE}.2.{i}", STR, name)
        put(f"{IF_TABLE}.3.{i}", INT, "6")                                 # ethernetCsmacd
        put(f"{IF_TABLE}.4.{i}", INT, "9000" if i > 1 else "1500")
        put(f"{IF_TABLE}.5.{i}", G32, str(min(speed * 1_000_000, 4294967295)))
        put(f"{IF_TABLE}.6.{i}", *mac(dev_idx, i))
        put(f"{IF_TABLE}.7.{i}", INT, "1")                                 # up
        put(f"{IF_TABLE}.8.{i}", INT, "1")                                 # up
        put(f"{IF_TABLE}.10.{i}", *counter(rx, bits=32))
        put(f"{IF_TABLE}.16.{i}", *counter(tx, bits=32))
        put(f"{IFX_TABLE}.1.{i}", STR, name)
        put(f"{IFX_TABLE}.6.{i}", *counter(rx))
        put(f"{IFX_TABLE}.10.{i}", *counter(tx))
        put(f"{IFX_TABLE}.15.{i}", G32, str(speed))
        put(f"{IFX_TABLE}.18.{i}", STR, alias)

    # management IP lives on ifIndex 1
    ip = dev["ip"]
    put(f"{IP_ADDR}.1.{ip}", IPADDR, ip)
    put(f"{IP_ADDR}.2.{ip}", INT, "1")
    put(f"{IP_ADDR}.3.{ip}", IPADDR, "255.255.255.0")

    # RAN-SECURE-SIM-MIB
    if dev["cells"]:
        total_ues = sum(ue for _, _, _, ue in dev["cells"]) * 10
        put(f"{RAN_NODE}.1.0", STR, kind)
        # Each element/cell gets a slightly different period so the waves don't move in lockstep
        put(f"{RAN_NODE}.2.0", *gauge_wave(38, 14, rate=FAST * (1 + 0.1 * dev_idx)))  # CPU %
        put(f"{RAN_NODE}.3.0", *gauge_wave(47, 6, lo=0, hi=120))         # temperature C
        put(f"{RAN_NODE}.4.0", G32, "0")                                  # active alarms
        put(f"{RAN_NODE}.5.0", *gauge_wave(total_ues, total_ues // 3, hi=100000))
        for c, (cell, rat, prb, ue) in enumerate(dev["cells"], start=1):
            r = round(SLOW * (1 + 0.13 * c + 0.09 * dev_idx), 6)
            put(f"{RAN_CELL}.1.{c}", INT, str(c))
            put(f"{RAN_CELL}.2.{c}", STR, cell)
            put(f"{RAN_CELL}.3.{c}", STR, rat)
            put(f"{RAN_CELL}.4.{c}", *gauge_wave(prb, prb // 3, rate=r))                       # PRB DL %
            put(f"{RAN_CELL}.5.{c}", *gauge_wave(prb // 2, prb // 5, rate=r))                  # PRB UL %
            put(f"{RAN_CELL}.6.{c}", *gauge_wave(9940, 40, lo=9000, hi=10000, rate=r * 2))         # RRC succ x100
            put(f"{RAN_CELL}.7.{c}", *gauge_wave(ue * 10, ue * 3, hi=5000, rate=r))            # active UEs
            mbps = 900 if rat == "NR" else 150
            put(f"{RAN_CELL}.8.{c}", *gauge_wave(mbps * prb * 10, mbps * prb * 3,
                                                 hi=10_000_000, rate=r))                       # DL kbps
            put(f"{RAN_CELL}.9.{c}", *gauge_wave(35, 15, hi=10000, rate=FAST * (1 + 0.2 * c)))         # drop x10000
            put(f"{RAN_CELL}.10.{c}", G32, "10000")                                     # avail x100
    return recs


def write_snmprec(recs, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{oid}|{tag}|{val}" for oid, (tag, val) in
             sorted(recs.items(), key=lambda kv: oid_key(kv[0]))]
    path.write_text("\n".join(lines) + "\n")
    return len(lines)


CATEGORIES = {
    "gNodeB": ["RAN", "5G-NR"],
    "eNodeB": ["RAN", "4G-LTE"],
    "CellSiteRouter": ["Transport", "Backhaul"],
    "AggregationRouter": ["Transport", "Core"],
}


def write_requisition(path, foreign_source="RAN-Sim"):
    """OpenNMS requisition (model-import) for the simulated elements."""
    from xml.sax.saxutils import quoteattr
    out = [f'<model-import xmlns="http://xmlns.opennms.org/xsd/config/model-import" '
           f'foreign-source="{foreign_source}">']
    for dev in DEVICES:
        out.append(f'   <node foreign-id={quoteattr(dev["name"])} node-label={quoteattr(dev["name"])} '
                   f'building={quoteattr(dev["location"])}>')
        out.append(f'      <interface ip-addr="{dev["ip"]}" status="1" snmp-primary="P">')
        out.append('         <monitored-service service-name="ICMP"/>')
        out.append('         <monitored-service service-name="SNMP"/>')
        out.append('      </interface>')
        for cat in CATEGORIES[dev["kind"]]:
            out.append(f'      <category name="{cat}"/>')
        out.append('   </node>')
    out.append('</model-import>')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(HERE / "data"), help="output directory")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    inventory = []
    for idx, dev in enumerate(DEVICES, start=1):
        n = write_snmprec(build_records(idx, dev), out / dev["name"] / "public.snmprec")
        inventory.append({k: dev[k] for k in ("name", "ip", "kind", "location")} |
                         {"cells": [c[0] for c in dev["cells"]], "oids": n})
        print(f"{dev['name']:<15} {dev['ip']:<13} {dev['kind']:<18} {n:>4} OIDs")
    (out / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    req = HERE.parent / "opennms" / "requisition" / "RAN-Sim.xml"
    write_requisition(req)
    print(f"requisition -> {req.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
