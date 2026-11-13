"""
RAN-Secure Analytics Platform - simulated transport and access network.

The 4G/5G RAN in generate_snmprec.py depends on a transport network to reach the
core and the Internet. This module models that network end to end, so the demo
shows how one platform follows a fault across layers:

    RAN sites -> csr-hub-01 -> agg-core-01 -> pe-core-01 ==(DWDM lambda 1)== p-core-01 -> pe-core-02 -> Internet
                                                  \\________ diverse fiber route ________/        |
                                                                                            sw-agg-01
                                                                         olt-town-01  olt-rural-02  sw-access-01
                                                                         (GPON/FTTH)  (GPON/FTTH)   (enterprise)

    roadm-01 (POP A) --span 1, 62 km-- ila-01 --span 2, 71 km-- roadm-02 (POP B)

Element families (sysObjectID under RAN-SECURE-NET-SIM-MIB, enterprise 32473.7):
  IP/MPLS routers  pe-core-01, p-core-01, pe-core-02     LSPs, BGP peers, chassis health
  Ethernet         sw-agg-01, sw-access-01               broadcast/error counters, STP changes
  DWDM             roadm-01, ila-01, roadm-02            optical power, OSNR, pre-FEC BER
  GPON OLT         olt-town-01, olt-rural-02             ONUs online, ONU Rx power, PON load

Values come from the "rsdyn" snmpsim variation module (simulator/variation/rsdyn.py):
smooth daily-like waves plus noise, and every value a scenario needs to change has a
state key (k=...) that scripts/scenario.sh sets through simulator/simctl.py.
"""

# --- OID roots ---------------------------------------------------------------
NET = "1.3.6.1.4.1.32473.7"             # rsNetSim (RFC 5612 documentation enterprise)
NET_CHASSIS = f"{NET}.1"
NET_LSP = f"{NET}.2.1.1"                # rsLspTable.rsLspEntry
NET_BGP = f"{NET}.2.2.1"                # rsBgpPeerTable.rsBgpPeerEntry
NET_SW = f"{NET}.3"
NET_OPT = f"{NET}.4.1.1"                # rsOptPortTable.rsOptPortEntry
NET_PON = f"{NET}.5.1.1"                # rsPonPortTable.rsPonPortEntry
NET_PRODUCTS = f"{NET}.100"
BGP4 = "1.3.6.1.2.1.15"                 # BGP4-MIB (RFC 4273)
BRIDGE = "1.3.6.1.2.1.17"               # BRIDGE-MIB (RFC 4188)

LOCAL_AS = 65010                        # private AS of the fictional operator

SYS_OBJECT_ID = {
    "PERouter": f"{NET_PRODUCTS}.1.1",
    "PRouter": f"{NET_PRODUCTS}.1.2",
    "AggSwitch": f"{NET_PRODUCTS}.2.1",
    "AccessSwitch": f"{NET_PRODUCTS}.2.2",
    "ROADM": f"{NET_PRODUCTS}.3.1",
    "ILA": f"{NET_PRODUCTS}.3.2",
    "OLT": f"{NET_PRODUCTS}.4.1",
}

SYS_DESCR = {
    "PERouter": "RAN-Secure Simulated Provider Edge Router (IP/MPLS, BGP, RSVP-TE), SW 1.0-sim",
    "PRouter": "RAN-Secure Simulated Provider Core Router (IP/MPLS LSR), SW 1.0-sim",
    "AggSwitch": "RAN-Secure Simulated Aggregation Switch (10GE, 802.1Q, RSTP), SW 1.0-sim",
    "AccessSwitch": "RAN-Secure Simulated Access Switch (1GE/10GE, 802.1Q, RSTP), SW 1.0-sim",
    "ROADM": "RAN-Secure Simulated ROADM (DWDM C-band, 2-degree), SW 1.0-sim",
    "ILA": "RAN-Secure Simulated In-Line Amplifier (DWDM EDFA), SW 1.0-sim",
    "OLT": "RAN-Secure Simulated GPON OLT (ITU-T G.984, class C+ optics), SW 1.0-sim",
}

CATEGORIES = {
    "PERouter": ["Transport", "IP-MPLS"],
    "PRouter": ["Transport", "IP-MPLS"],
    "AggSwitch": ["Transport", "Switching"],
    "AccessSwitch": ["Transport", "Switching"],
    "ROADM": ["Transport", "DWDM"],
    "ILA": ["Transport", "DWDM"],
    "OLT": ["Access", "GPON"],
}

# Chassis health: (cpu %, mem %, temperature C)
CHASSIS = {
    "PERouter": (24, 46, 44), "PRouter": (18, 38, 42),
    "AggSwitch": (14, 33, 39), "AccessSwitch": (11, 29, 37),
    "ROADM": (9, 27, 35), "ILA": (6, 21, 33), "OLT": (27, 52, 46),
}

# IANAifType values used below
ETH, OPT_CH, OPT_TRANSPORT, GPON = 6, 195, 196, 250

# Interfaces: (ifName, ifAlias, speed Mbit/s, avg in B/s, avg out B/s, ifType)
# Optical line ports carry no Ethernet traffic counters (rates 0).
# fmt: off
DEVICES = [
    # ---------------- IP/MPLS core ----------------
    {"name": "pe-core-01", "ip": "172.30.0.51", "kind": "PERouter",
     "location": "Core POP A - IP/MPLS provider edge (simulated)",
     "loopback": "10.255.0.1",
     "ifaces": [("mgmt0", "MGMT / out-of-band", 1000, 12_000, 9_000, ETH),
                ("xe-0/0/0", "To agg-core-01 xe-0/1/1 (mobile backhaul)", 10000, 600_000_000, 210_000_000, ETH),
                ("et-0/1/0", "Core to p-core-01 et-0/1/0 via DWDM lambda 1 (roadm-01 > ila-01 > roadm-02)", 100000, 1_450_000_000, 1_900_000_000, ETH),
                ("et-0/1/1", "Core to pe-core-02 et-0/1/1 (diverse fiber route, protection)", 100000, 350_000_000, 420_000_000, ETH)],
     "lsps": [("LSP-PE1-PE2-GOLD", "pe-core-02 (10.255.0.3)", 42, 820),
              ("LSP-PE1-PE2-BE", "pe-core-02 (10.255.0.3)", 61, 835)],
     "bgp": [("iBGP pe-core-02 (route reflector)", "10.255.0.3", LOCAL_AS, 958_000),
             ("IX peering AS64501", "198.51.100.1", 64501, 42_000)]},
    {"name": "p-core-01", "ip": "172.30.0.52", "kind": "PRouter",
     "location": "Core POP B - IP/MPLS core (simulated)",
     "loopback": "10.255.0.2",
     "ifaces": [("mgmt0", "MGMT / out-of-band", 1000, 10_000, 8_000, ETH),
                ("et-0/1/0", "Core to pe-core-01 et-0/1/0 via DWDM lambda 1", 100000, 1_900_000_000, 1_450_000_000, ETH),
                ("et-0/1/1", "Core to pe-core-02 et-0/1/0 (POP B local)", 100000, 1_500_000_000, 2_000_000_000, ETH)]},
    {"name": "pe-core-02", "ip": "172.30.0.53", "kind": "PERouter",
     "location": "Core POP B - IP/MPLS provider edge and Internet gateway (simulated)",
     "loopback": "10.255.0.3",
     "ifaces": [("mgmt0", "MGMT / out-of-band", 1000, 12_000, 9_000, ETH),
                ("et-0/1/0", "Core to p-core-01 et-0/1/1 (POP B local)", 100000, 2_000_000_000, 1_500_000_000, ETH),
                ("et-0/1/1", "Core to pe-core-01 et-0/1/1 (diverse fiber route, protection)", 100000, 420_000_000, 350_000_000, ETH),
                ("xe-0/0/0", "To sw-agg-01 xe-1/1/1 (FTTH and enterprise aggregation)", 10000, 120_000_000, 750_000_000, ETH),
                ("et-0/2/0", "Upstream IP transit - Transit-A AS64500", 100000, 2_200_000_000, 360_000_000, ETH)],
     "lsps": [("LSP-PE2-PE1-GOLD", "pe-core-01 (10.255.0.1)", 38, 825),
              ("LSP-PE2-PE1-BE", "pe-core-01 (10.255.0.1)", 57, 840)],
     "bgp": [("Transit-A AS64500", "203.0.113.1", 64500, 958_000),
             ("iBGP pe-core-01 (route reflector client)", "10.255.0.1", LOCAL_AS, 42_000)]},

    # ---------------- Ethernet aggregation / access ----------------
    {"name": "sw-agg-01", "ip": "172.30.0.61", "kind": "AggSwitch",
     "location": "Core POP B - Metro aggregation (simulated)",
     "ifaces": [("mgmt0", "MGMT", 1000, 8_000, 6_000, ETH),
                ("xe-1/1/1", "Uplink to pe-core-02 xe-0/0/0", 10000, 750_000_000, 120_000_000, ETH),
                ("xe-1/1/2", "To olt-town-01 xgei-0/9/1", 10000, 80_000_000, 550_000_000, ETH),
                ("xe-1/1/3", "To olt-rural-02 xgei-0/9/1", 10000, 25_000_000, 150_000_000, ETH),
                ("xe-1/1/4", "To sw-access-01 xe-0/0/49", 10000, 15_000_000, 50_000_000, ETH)],
     "mac_entries": 2600},
    {"name": "sw-access-01", "ip": "172.30.0.62", "kind": "AccessSwitch",
     "location": "Business park street cabinet - enterprise access (simulated)",
     "ifaces": [("mgmt0", "MGMT", 1000, 6_000, 5_000, ETH),
                ("xe-0/0/49", "Uplink to sw-agg-01 xe-1/1/4", 10000, 50_000_000, 15_000_000, ETH),
                ("ge-0/0/1", "BIZ-1001 Medical clinic (VLAN 2101)", 1000, 4_000_000, 14_000_000, ETH),
                ("ge-0/0/2", "BIZ-1002 Municipal office (VLAN 2102)", 1000, 3_000_000, 11_000_000, ETH),
                ("ge-0/0/3", "BIZ-1003 High school (VLAN 2103)", 1000, 5_000_000, 16_000_000, ETH),
                ("ge-0/0/4", "BIZ-1004 Retail store (VLAN 2104)", 1000, 2_000_000, 8_000_000, ETH)],
     "mac_entries": 380},

    # ---------------- DWDM optical layer ----------------
    {"name": "roadm-01", "ip": "172.30.0.71", "kind": "ROADM",
     "location": "Core POP A - DWDM terminal (simulated)",
     "ifaces": [("mgmt0", "MGMT", 100, 4_000, 3_000, ETH),
                ("LINE-E", "Span 1 to ila-01 LINE-W (62 km, OTS)", 0, 0, 0, OPT_TRANSPORT),
                ("CH-1", "Lambda 1 193.10 THz 100G: pe-core-01 et-0/1/0 <> p-core-01 et-0/1/0", 100000, 1_900_000_000, 1_450_000_000, OPT_CH),
                ("CH-2", "Lambda 2 193.20 THz 100G: wholesale circuit WS-0042 (carrier customer)", 100000, 2_100_000_000, 2_600_000_000, OPT_CH)],
     # optical rows keyed by ifIndex: (role, rx 0.01 dBm, tx 0.01 dBm, channels | osnr 0.01 dB, pre-FEC BER x1e9)
     "optical": {2: ("line", -1100, 400, 2),
                 3: ("client", -240, -120, 2210, 1800),
                 4: ("client", -260, -110, 2150, 2600)}},
    {"name": "ila-01", "ip": "172.30.0.72", "kind": "ILA",
     "location": "In-line amplifier hut, km 62 (simulated)",
     "ifaces": [("mgmt0", "MGMT", 100, 3_000, 2_000, ETH),
                ("LINE-W", "Span 1 to roadm-01 LINE-E (62 km, OTS)", 0, 0, 0, OPT_TRANSPORT),
                ("LINE-E", "Span 2 to roadm-02 LINE-W (71 km, OTS)", 0, 0, 0, OPT_TRANSPORT)],
     "optical": {2: ("line", -1150, 450, 2),
                 3: ("line", -1240, 450, 2)}},
    {"name": "roadm-02", "ip": "172.30.0.73", "kind": "ROADM",
     "location": "Core POP B - DWDM terminal (simulated)",
     "ifaces": [("mgmt0", "MGMT", 100, 4_000, 3_000, ETH),
                ("LINE-W", "Span 2 to ila-01 LINE-E (71 km, OTS)", 0, 0, 0, OPT_TRANSPORT),
                ("CH-1", "Lambda 1 193.10 THz 100G: pe-core-01 et-0/1/0 <> p-core-01 et-0/1/0", 100000, 1_450_000_000, 1_900_000_000, OPT_CH),
                ("CH-2", "Lambda 2 193.20 THz 100G: wholesale circuit WS-0042 (carrier customer)", 100000, 2_600_000_000, 2_100_000_000, OPT_CH)],
     "optical": {2: ("line", -1250, 380, 2),
                 3: ("client", -230, -130, 2080, 3100),
                 4: ("client", -250, -100, 2040, 3900)}},

    # ---------------- GPON / FTTH access ----------------
    {"name": "olt-town-01", "ip": "172.30.0.81", "kind": "OLT",
     "location": "Town central office - FTTH (simulated)",
     "uplink": ("xgei-0/9/1", "Uplink to sw-agg-01 xe-1/1/2", 550_000_000, 80_000_000),
     # PON ports: (zone, ONUs registered)
     "pons": [("Zone A - Downtown", 48), ("Zone B - Riverside", 56), ("Zone C - Hillcrest", 58),
              ("Zone D - Oak Park", 44), ("Zone E - Westgate", 62), ("Zone F - Lakeview", 40),
              ("Zone G - Industrial park", 36), ("Zone H - Northfield", 52)]},
    {"name": "olt-rural-02", "ip": "172.30.0.82", "kind": "OLT",
     "location": "Rural exchange - FTTH (simulated)",
     "uplink": ("xgei-0/9/1", "Uplink to sw-agg-01 xe-1/1/3", 150_000_000, 25_000_000),
     "pons": [("Rural route - Mill Creek", 24), ("Rural route - Pine Valley", 31),
              ("Rural route - Cedar Ridge", 18), ("Rural route - Fox Hollow", 27)]},
]
# fmt: on


def expand_olt(dev):
    """OLT interfaces: mgmt0, the 10G uplink, then one gpon-0/1/N port per PON."""
    up_name, up_alias, up_in, up_out = dev["uplink"]
    total = sum(onus for _, onus in dev["pons"])
    ifaces = [("mgmt0", "MGMT", 1000, 6_000, 5_000, ETH),
              (up_name, up_alias, 10000, up_in, up_out, ETH)]
    for n, (zone, onus) in enumerate(dev["pons"], start=1):
        share = onus / total
        # PON in = upstream from ONUs, out = downstream to ONUs
        ifaces.append((f"gpon-0/1/{n}", f"PON 0/1/{n} - {zone} (splitter 1:64)", 2488,
                       int(up_out * share), int(up_in * share), GPON))
    return ifaces


for _dev in DEVICES:
    if _dev["kind"] == "OLT":
        _dev["ifaces"] = expand_olt(_dev)


def fmt(x):
    x = float(x)
    return str(int(x)) if x.is_integer() else f"{x:.6g}"


def dyn(tag, k=None, **params):
    """snmprec (tag, value) for an rsdyn record."""
    parts = [f"{name}={fmt(val)}" for name, val in params.items() if val is not None]
    if k:
        parts.append(f"k={k}")
    return f"{tag}:rsdyn", ",".join(parts)


def gauge(v, a=0, n=0, lo=0, hi=None, k=None, ph=0, p=None, tag="66"):
    return dyn(tag, k=k, v=v, a=a or None, n=n or None, lo=lo, hi=hi, ph=ph or None, p=p)


def signed(v, a=0, n=0, lo=None, hi=None, k=None, ph=0):
    """Integer32 that may go negative (optical power in 0.01 dBm)."""
    return gauge(v, a=a, n=n, lo=lo, hi=hi, k=k, ph=ph, tag="2")


def counter(rate, k=None, a=0.35, ph=0, bits=64):
    return dyn("70" if bits == 64 else "65", k=k, c=rate, a=a or None, ph=ph or None, bits=bits)
