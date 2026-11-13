#
# RAN-Secure Analytics Platform - "rsdyn" snmpsim variation module.
#
# Produces realistic, time-varying values for the transport / access simulators
# (IP/MPLS routers, switches, DWDM, GPON OLTs) and lets demo scenarios change
# them at run time through a small JSON state file written by simctl.py.
#
# snmprec syntax:   <oid>|<tag>:rsdyn|<param>=<value>,<param>=<value>,...
#
#   gauge (default)  v=<center>  a=<amplitude>  p=<period s>  ph=<phase rad>
#                    n=<+/- random noise>  lo=<min>  hi=<max>
#   counter          c=<units per second>  a=<relative daily swing 0..1>
#                    p=<period s>  ph=<phase>  bits=32|64
#   any record       k=<state key>   (optional: lets simctl override it)
#
# State file (env RS_STATE, default /tmp/rs-state.json), written by simctl:
#   {"<key>": {"set": 2}}                         absolute value (gauges)
#   {"<key>": {"add": -300}}                      offset (gauges)
#   {"<key>": {"mul": 0.0}}                       factor (gauges and counter rates)
#   {"<key>": {"ramp": [from, to, t0, seconds]}}  linear drift (gauges)
#
# The module is loaded by snmpsim with exec(); snmpsim injects the globals
# moduleContext and recordContext.
#
import json
import math
import os
import random
import time

STATE_FILE = os.environ.get("RS_STATE", "/tmp/rs-state.json")
BOOTED = time.time()
WRAP = {32: 2 ** 32, 64: 2 ** 64}


def init(**context):
    moduleContext["state"] = {}
    moduleContext["stamp"] = None
    moduleContext["counters"] = {}


def _state():
    """Return the scenario state, re-reading the file only when it changes."""
    try:
        st = os.stat(STATE_FILE)
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        moduleContext["state"], moduleContext["stamp"] = {}, None
        return moduleContext["state"]
    if stamp != moduleContext["stamp"]:
        try:
            with open(STATE_FILE) as fh:
                moduleContext["state"] = json.load(fh)
            moduleContext["stamp"] = stamp
        except (OSError, ValueError):
            pass  # keep the previous state if the file is being replaced
    return moduleContext["state"]


def _settings(value):
    if "settings" not in recordContext:
        s = {}
        for item in value.split(","):
            if "=" in item:
                key, val = item.split("=", 1)
                s[key.strip()] = val.strip()
        for key in ("v", "a", "p", "ph", "n", "lo", "hi", "c", "bits"):
            if key in s:
                s[key] = float(s[key])
        s.setdefault("p", 7200.0)
        s.setdefault("ph", 0.0)
        s.setdefault("a", 0.0)
        recordContext["settings"] = s
    return recordContext["settings"]


def _gauge(s, override, now):
    if "set" in override:
        v = float(override["set"])
    elif "ramp" in override:
        start, end, t0, dur = (float(x) for x in override["ramp"])
        frac = min(max((now - t0) / dur, 0.0), 1.0) if dur > 0 else 1.0
        v = start + (end - start) * frac
        if s.get("n"):
            v += random.uniform(-s["n"], s["n"])
    else:
        v = s.get("v", 0.0) + s["a"] * math.sin(2 * math.pi * (now - BOOTED) / s["p"] + s["ph"])
        if s.get("n"):
            v += random.uniform(-s["n"], s["n"])
        v = v * float(override.get("mul", 1.0)) + float(override.get("add", 0.0))
    if "lo" in s:
        v = max(v, s["lo"])
    if "hi" in s:
        v = min(v, s["hi"])
    return int(round(v))


def _counter(oid, s, override, now):
    """Monotonic counter whose rate follows a daily-like wave and the scenario factor."""
    key = str(oid)
    wrap = WRAP[int(s.get("bits", 64))]
    last_t, total = moduleContext["counters"].get(key, (BOOTED, 0.0))
    rate = s["c"] * (1 + s["a"] * math.sin(2 * math.pi * (now - BOOTED) / s["p"] + s["ph"]))
    rate *= float(override.get("mul", 1.0))
    total += max(rate, 0.0) * max(now - last_t, 0.0)
    moduleContext["counters"][key] = (now, total)
    return int(total) % wrap


def variate(oid, tag, value, **context):
    if not context["nextFlag"] and not context["exactMatch"]:
        return context["origOid"], tag, context["errorStatus"]
    if context["setFlag"]:
        return context["origOid"], tag, context["errorStatus"]

    s = _settings(value)
    now = time.time()
    override = _state().get(s.get("k", ""), {}) if "k" in s else {}

    if "c" in s:
        return oid, tag, _counter(oid, s, override, now)
    return oid, tag, _gauge(s, override, now)


def shutdown(**context):
    pass
