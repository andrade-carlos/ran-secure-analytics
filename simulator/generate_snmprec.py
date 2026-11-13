#!/usr/bin/env python3
"""
RAN-Secure Analytics Platform - simulated network generator.

Generates one snmpsim data file (.snmprec) per simulated network element:
the 4G/5G RAN defined here, plus the transport and access network that carries
its traffic (IP/MPLS, Ethernet, DWDM, GPON), defined in transport_model.py.

Every element exposes:
  * SNMPv2-MIB system group (sysDescr, sysObjectID, sysUpTime, sysName ...)
  * IF-MIB interfaces (ifTable + ifXTable, 32/64-bit traffic counters)
  * IP-MIB ipAddrTable (so OpenNMS can map the management IP to an ifIndex)
  * LLDP-MIB local and remote tables, so OpenNMS (Enlinkd) draws the topology
  * RAN-SECURE-SIM-MIB (gNodeB/eNodeB): node health and per-cell KPIs
  * RAN-SECURE-NET-SIM-MIB (transport/access): chassis health, LSPs, BGP peers,
    optical power/OSNR/pre-FEC BER, GPON ONUs and ONU optical levels;
    routers also expose BGP4-MIB, switches BRIDGE-MIB

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

import transport_model as tm

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
                          ("xe-0/1/1", "Uplink to pe-core-01 xe-0/0/0 (IP/MPLS core)", 10000, 210_000_000, 600_000_000)],
}


def oid_key(oid):
    return tuple(int(p) for p in oid.split("."))


def build_records(dev_idx, dev):
    """RAN elements (gNodeB, eNodeB, cell-site and aggregation routers)."""
    recs = {}

    def put(oid, tag, value):
        recs[oid] = (tag, value)

    kind = dev["kind"]
    # system group
    put(f"{SYS}.1.0", STR, sys_descr(kind))
    put(f"{SYS}.2.0", OID, sys_object_id(kind))
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


# --- Transport / access elements (transport_model.py) ----------------------
IF_SUFFIX_MGMT = ("mgmt0",)


def sys_descr(kind):
    return SYS_DESCR.get(kind) or tm.SYS_DESCR[kind]


def sys_object_id(kind):
    return SYS_OBJECT_ID.get(kind) or tm.SYS_OBJECT_ID[kind]


def build_transport_records(dev_idx, dev):
    """IP/MPLS routers, switches, DWDM and GPON OLTs (values from the rsdyn module)."""
    recs = {}

    def put(oid, tag, value):
        recs[oid] = (tag, value)

    kind = dev["kind"]
    ph0 = round(dev_idx * 0.7, 2)
    put(f"{SYS}.1.0", STR, sys_descr(kind))
    put(f"{SYS}.2.0", OID, sys_object_id(kind))
    put(f"{SYS}.3.0", f"{TT}:numeric", "rate=100,initial=0")
    put(f"{SYS}.4.0", STR, "noc@ran-secure.example")
    put(f"{SYS}.5.0", STR, dev["name"])
    put(f"{SYS}.6.0", STR, dev["location"])
    put(f"{SYS}.7.0", INT, "78")

    # interfaces: status and counters carry state keys if<N>.oper / if<N>.t / if<N>.bc / if<N>.err
    ifs = dev["ifaces"]
    put(IF_NUMBER, INT, str(len(ifs)))
    for i, (name, alias, speed, rx, tx, iftype) in enumerate(ifs, start=1):
        ph = round(ph0 + 0.3 * i, 2)
        put(f"{IF_TABLE}.1.{i}", INT, str(i))
        put(f"{IF_TABLE}.2.{i}", STR, name)
        put(f"{IF_TABLE}.3.{i}", INT, str(iftype))
        put(f"{IF_TABLE}.4.{i}", INT, "1500" if name in IF_SUFFIX_MGMT else "9216")
        put(f"{IF_TABLE}.5.{i}", G32, str(min(speed * 1_000_000, 4294967295)))
        put(f"{IF_TABLE}.6.{i}", *mac(dev_idx, i))
        put(f"{IF_TABLE}.7.{i}", INT, "1")
        put(f"{IF_TABLE}.8.{i}", *tm.gauge(1, lo=1, hi=7, k=f"if{i}.oper", tag=INT))
        put(f"{IFX_TABLE}.1.{i}", STR, name)
        put(f"{IFX_TABLE}.15.{i}", G32, str(speed))
        put(f"{IFX_TABLE}.18.{i}", STR, alias)
        if not (rx or tx):
            continue                                   # optical line port: no Ethernet counters
        t = f"if{i}.t"
        bcast = 0.5 if name in IF_SUFFIX_MGMT else {"AggSwitch": 45, "AccessSwitch": 30}.get(kind, 2)
        put(f"{IF_TABLE}.10.{i}", *tm.counter(rx, k=t, ph=ph, bits=32))
        put(f"{IF_TABLE}.11.{i}", *tm.counter(rx / 850, k=t, ph=ph, bits=32))
        put(f"{IF_TABLE}.14.{i}", *tm.counter(0.002, k=f"if{i}.err", a=0, bits=32))
        put(f"{IF_TABLE}.16.{i}", *tm.counter(tx, k=t, ph=ph, bits=32))
        put(f"{IF_TABLE}.17.{i}", *tm.counter(tx / 850, k=t, ph=ph, bits=32))
        put(f"{IFX_TABLE}.6.{i}", *tm.counter(rx, k=t, ph=ph))
        put(f"{IFX_TABLE}.7.{i}", *tm.counter(rx / 850, k=t, ph=ph))
        put(f"{IFX_TABLE}.8.{i}", *tm.counter(3, a=0.2, ph=ph))
        put(f"{IFX_TABLE}.9.{i}", *tm.counter(bcast, k=f"if{i}.bc", a=0.2, ph=ph))
        put(f"{IFX_TABLE}.10.{i}", *tm.counter(tx, k=t, ph=ph))
        put(f"{IFX_TABLE}.11.{i}", *tm.counter(tx / 850, k=t, ph=ph))

    ip = dev["ip"]
    put(f"{IP_ADDR}.1.{ip}", IPADDR, ip)
    put(f"{IP_ADDR}.2.{ip}", INT, "1")
    put(f"{IP_ADDR}.3.{ip}", IPADDR, "255.255.255.0")

    # RAN-SECURE-NET-SIM-MIB: chassis health (state keys cpu / mem / temp)
    cpu, mem, temp = tm.CHASSIS[kind]
    put(f"{tm.NET_CHASSIS}.1.0", STR, kind)
    put(f"{tm.NET_CHASSIS}.2.0", *tm.gauge(cpu, a=cpu * 0.35, n=2, hi=100, k="cpu", ph=ph0))
    put(f"{tm.NET_CHASSIS}.3.0", *tm.gauge(mem, a=3, n=1, hi=100, k="mem", ph=ph0))
    put(f"{tm.NET_CHASSIS}.4.0", *tm.gauge(temp, a=3, n=0.5, hi=120, k="temp", ph=ph0))

    # MPLS LSPs (state keys lsp<N>.oper / .path / .util / .lat)
    for n, (lsp, dest, util, lat) in enumerate(dev.get("lsps", []), start=1):
        put(f"{tm.NET_LSP}.1.{n}", INT, str(n))
        put(f"{tm.NET_LSP}.2.{n}", STR, lsp)
        put(f"{tm.NET_LSP}.3.{n}", STR, dest)
        put(f"{tm.NET_LSP}.4.{n}", *tm.gauge(1, lo=1, hi=2, k=f"lsp{n}.oper", tag=INT))
        put(f"{tm.NET_LSP}.5.{n}", *tm.gauge(1, lo=0, hi=2, k=f"lsp{n}.path", tag=INT))
        put(f"{tm.NET_LSP}.6.{n}", *tm.gauge(util, a=util * 0.3, n=2, hi=100, k=f"lsp{n}.util", ph=ph0 + n))
        put(f"{tm.NET_LSP}.7.{n}", *tm.gauge(lat, n=12, k=f"lsp{n}.lat"))

    # BGP peers: summary table in the private MIB + standard BGP4-MIB (state keys bgp<N>.state / .pfx)
    if dev.get("bgp"):
        put(f"{BGP4_ROOT}.1.0", "4x", "10")                        # bgpVersion: version 4
        put(f"{BGP4_ROOT}.2.0", INT, str(tm.LOCAL_AS))
        put(f"{BGP4_ROOT}.4.0", IPADDR, dev["loopback"])
    for n, (peer, addr, asn, pfx) in enumerate(dev.get("bgp", []), start=1):
        put(f"{tm.NET_BGP}.1.{n}", INT, str(n))
        put(f"{tm.NET_BGP}.2.{n}", STR, peer)
        put(f"{tm.NET_BGP}.3.{n}", STR, addr)
        put(f"{tm.NET_BGP}.4.{n}", G32, str(asn))
        put(f"{tm.NET_BGP}.5.{n}", *tm.gauge(6, lo=1, hi=6, k=f"bgp{n}.state", tag=INT))
        put(f"{tm.NET_BGP}.6.{n}", *tm.gauge(pfx, a=pfx * 0.0008, n=pfx * 0.0002 + 2, k=f"bgp{n}.pfx"))
        peer_row = f"{BGP4_ROOT}.3.1"
        put(f"{peer_row}.1.{addr}", IPADDR, addr)
        put(f"{peer_row}.2.{addr}", *tm.gauge(6, lo=1, hi=6, k=f"bgp{n}.state", tag=INT))
        put(f"{peer_row}.3.{addr}", INT, "2")                      # adminStatus start
        put(f"{peer_row}.4.{addr}", INT, "4")
        put(f"{peer_row}.5.{addr}", IPADDR, dev["loopback"])
        put(f"{peer_row}.7.{addr}", IPADDR, addr)
        put(f"{peer_row}.9.{addr}", INT, str(asn))

    # Ethernet switches: MAC table size, BRIDGE-MIB base and STP topology changes
    if "mac_entries" in dev:
        macs = dev["mac_entries"]
        put(f"{tm.NET_SW}.1.0", *tm.gauge(macs, a=macs * 0.05, n=macs * 0.01, k="macs", ph=ph0))
        put(f"{BRIDGE_ROOT}.1.1.0", *mac(dev_idx, 0))
        put(f"{BRIDGE_ROOT}.1.2.0", INT, str(len(ifs) - 1))
        put(f"{BRIDGE_ROOT}.1.3.0", INT, "2")
        for port in range(1, len(ifs)):
            put(f"{BRIDGE_ROOT}.1.4.1.1.{port}", INT, str(port))
            put(f"{BRIDGE_ROOT}.1.4.1.2.{port}", INT, str(port + 1))
        put(f"{BRIDGE_ROOT}.2.1.0", INT, "3")                      # ieee8021d
        put(f"{BRIDGE_ROOT}.2.4.0", *tm.counter(0.0003, k="stp", a=0, bits=32))

    # DWDM: per-port optical levels (state keys opt<ifIndex>.rx / .tx / .ch / .osnr / .ber)
    for idx, row in sorted(dev.get("optical", {}).items()):
        name, alias = ifs[idx - 1][0], ifs[idx - 1][1]
        role, rx, tx = row[:3]
        put(f"{tm.NET_OPT}.1.{idx}", INT, str(idx))
        put(f"{tm.NET_OPT}.2.{idx}", STR, name)
        put(f"{tm.NET_OPT}.3.{idx}", STR, alias)
        put(f"{tm.NET_OPT}.4.{idx}", INT, "1" if role == "line" else "2")
        put(f"{tm.NET_OPT}.5.{idx}", *tm.signed(rx, a=8, n=4, k=f"opt{idx}.rx", ph=ph0 + idx))
        put(f"{tm.NET_OPT}.6.{idx}", *tm.signed(tx, a=5, n=3, k=f"opt{idx}.tx", ph=ph0 + idx))
        if role == "line":
            put(f"{tm.NET_OPT}.7.{idx}", *tm.gauge(row[3], k=f"opt{idx}.ch"))
        else:
            osnr, ber = row[3], row[4]
            put(f"{tm.NET_OPT}.8.{idx}", *tm.gauge(osnr, a=25, n=10, k=f"opt{idx}.osnr", ph=ph0 + idx))
            put(f"{tm.NET_OPT}.9.{idx}", *tm.gauge(ber, a=ber * 0.2, n=ber * 0.08, k=f"opt{idx}.ber",
                                                   ph=ph0 + idx))

    # GPON: per-PON ONU counts, ONU optical levels and PON load
    # (state keys pon<ifIndex>.on / .rxavg / .rxworst / .tx / .dl / .ul)
    for n, (zone, onus) in enumerate(dev.get("pons", []), start=1):
        idx = n + 2                                                 # after mgmt0 and the uplink
        _, _, _, pon_in, pon_out, _ = ifs[idx - 1]
        dl = pon_out * 8 / 2.488e9 * 100
        ul = pon_in * 8 / 1.244e9 * 100
        php = ph0 + 0.4 * n
        put(f"{tm.NET_PON}.1.{idx}", INT, str(idx))
        put(f"{tm.NET_PON}.2.{idx}", STR, ifs[idx - 1][0])
        put(f"{tm.NET_PON}.3.{idx}", G32, str(onus))
        put(f"{tm.NET_PON}.4.{idx}", *tm.gauge(onus - 1.5, a=0.8, n=1, hi=onus, k=f"pon{idx}.on", ph=php))
        put(f"{tm.NET_PON}.5.{idx}", *tm.signed(-1950 - (n % 3) * 40, a=12, n=6, k=f"pon{idx}.rxavg", ph=php))
        put(f"{tm.NET_PON}.6.{idx}", *tm.signed(-2450 - (n % 4) * 30, a=10, n=8, k=f"pon{idx}.rxworst",
                                                 ph=php))
        put(f"{tm.NET_PON}.7.{idx}", *tm.signed(480 + 5 * n, a=3, n=2, k=f"pon{idx}.tx", ph=php))
        put(f"{tm.NET_PON}.8.{idx}", *tm.gauge(round(dl, 1), a=round(dl * 0.45, 1), n=1.5, hi=100,
                                               k=f"pon{idx}.dl", ph=php))
        put(f"{tm.NET_PON}.9.{idx}", *tm.gauge(round(ul, 1), a=round(ul * 0.4, 1), n=1, hi=100,
                                               k=f"pon{idx}.ul", ph=php))
    return recs


# --- LLDP topology (OpenNMS Enlinkd builds the topology map from it) ----------
LLDP = "1.0.8802.1.1.2.1"
BGP4_ROOT = tm.BGP4
BRIDGE_ROOT = tm.BRIDGE

# Physical links: (element A, port A, element B, port B). Both ends advertise LLDP.
LINKS = [
    ("gnb-site-101", "eth1", "csr-hub-01", "ge-0/0/1"),
    ("gnb-site-102", "eth1", "csr-hub-01", "ge-0/0/2"),
    ("enb-rural-201", "eth1", "csr-hub-01", "ge-0/0/3"),
    ("enb-rural-202", "eth1", "csr-hub-01", "ge-0/0/4"),
    ("csr-hub-01", "xe-0/1/0", "agg-core-01", "xe-0/1/0"),
    ("agg-core-01", "xe-0/1/1", "pe-core-01", "xe-0/0/0"),
    ("pe-core-01", "et-0/1/0", "p-core-01", "et-0/1/0"),        # carried by DWDM lambda 1
    ("pe-core-01", "et-0/1/1", "pe-core-02", "et-0/1/1"),       # diverse fiber route
    ("p-core-01", "et-0/1/1", "pe-core-02", "et-0/1/0"),
    ("pe-core-02", "xe-0/0/0", "sw-agg-01", "xe-1/1/1"),
    ("sw-agg-01", "xe-1/1/2", "olt-town-01", "xgei-0/9/1"),
    ("sw-agg-01", "xe-1/1/3", "olt-rural-02", "xgei-0/9/1"),
    ("sw-agg-01", "xe-1/1/4", "sw-access-01", "xe-0/0/49"),
    ("roadm-01", "LINE-E", "ila-01", "LINE-W"),                  # optical spans (via the OSC)
    ("ila-01", "LINE-E", "roadm-02", "LINE-W"),
]


def all_devices():
    """[(index, device, builder)] in a stable order: RAN first, then transport/access."""
    devs = [(d, build_records) for d in DEVICES] + [(d, build_transport_records) for d in tm.DEVICES]
    return [(i, d, b) for i, (d, b) in enumerate(devs, start=1)]


def ports(dev):
    """[(ifIndex, ifName, ifAlias)] of any simulated element."""
    rows = dev["ifaces"] if "ifaces" in dev else INTERFACES[dev["kind"]]
    return [(i, r[0], r[1]) for i, r in enumerate(rows, start=1)]


def add_lldp(recs, dev_idx, dev, by_name):
    def put(oid, tag, value):
        recs[oid] = (tag, value)

    put(f"{LLDP}.3.1.0", INT, "4")                                  # chassis id subtype: macAddress
    put(f"{LLDP}.3.2.0", *mac(dev_idx, 1))
    put(f"{LLDP}.3.3.0", STR, dev["name"])
    put(f"{LLDP}.3.4.0", STR, sys_descr(dev["kind"]))
    local = {name: (idx, alias) for idx, name, alias in ports(dev)}
    for idx, name, alias in ports(dev):
        put(f"{LLDP}.3.7.1.2.{idx}", INT, "5")                      # port id subtype: interfaceName
        put(f"{LLDP}.3.7.1.3.{idx}", STR, name)
        put(f"{LLDP}.3.7.1.4.{idx}", STR, alias)
    for a, pa, b, pb in LINKS:
        for me, my_port, peer, peer_port in ((a, pa, b, pb), (b, pb, a, pa)):
            if me != dev["name"]:
                continue
            port_num = local[my_port][0]
            peer_idx, peer_dev = by_name[peer]
            peer_alias = {n: al for _, n, al in ports(peer_dev)}[peer_port]
            row = f"0.{port_num}.1"                                 # timeMark.localPortNum.remIndex
            put(f"{LLDP}.4.1.1.4.{row}", INT, "4")
            put(f"{LLDP}.4.1.1.5.{row}", *mac(peer_idx, 1))
            put(f"{LLDP}.4.1.1.6.{row}", INT, "5")
            put(f"{LLDP}.4.1.1.7.{row}", STR, peer_port)
            put(f"{LLDP}.4.1.1.8.{row}", STR, peer_alias)
            put(f"{LLDP}.4.1.1.9.{row}", STR, peer)
            put(f"{LLDP}.4.1.1.10.{row}", STR, sys_descr(peer_dev["kind"]))


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
} | tm.CATEGORIES


def write_requisition(path, devices, foreign_source="RAN-Sim"):
    """OpenNMS requisition (model-import) for the simulated elements."""
    from xml.sax.saxutils import quoteattr
    out = [f'<model-import xmlns="http://xmlns.opennms.org/xsd/config/model-import" '
           f'foreign-source="{foreign_source}">']
    for dev in devices:
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
    devices = all_devices()
    by_name = {d["name"]: (i, d) for i, d, _ in devices}
    for a, pa, b, pb in LINKS:                                      # catch typos in the topology
        for el, port in ((a, pa), (b, pb)):
            assert port in [n for _, n, _ in ports(by_name[el][1])], f"unknown port {el}:{port}"
    inventory = []
    for idx, dev, builder in devices:
        recs = builder(idx, dev)
        add_lldp(recs, idx, dev, by_name)
        n = write_snmprec(recs, out / dev["name"] / "public.snmprec")
        inventory.append({k: dev[k] for k in ("name", "ip", "kind", "location")} |
                         {"categories": CATEGORIES[dev["kind"]],
                          "cells": [c[0] for c in dev.get("cells", [])], "oids": n})
        print(f"{dev['name']:<15} {dev['ip']:<13} {dev['kind']:<18} {n:>4} OIDs")
    (out / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    req = HERE.parent / "opennms" / "requisition" / "RAN-Sim.xml"
    write_requisition(req, [d for _, d, _ in devices])
    print(f"requisition -> {req.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
