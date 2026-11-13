#!/usr/bin/env python3
"""
RAN-Secure Analytics Platform - change a simulated element's live values.

Runs inside a simulator container and edits the state file read by the
"rsdyn" snmpsim variation module (simulator/variation/rsdyn.py). Values change
on the very next SNMP request, so OpenNMS graphs and polls reflect the scenario.

    simctl.py <key>=set:<value> ...          absolute value  (e.g. if3.oper=set:2)
    simctl.py <key>=mul:<factor> ...         scale a value / counter rate (if3.t=mul:0)
    simctl.py <key>=add:<delta> ...          offset a value
    simctl.py <key>=ramp:<from>:<to>:<sec>   linear drift starting now
    simctl.py clear [<key> ...]              back to normal (all keys if none given)
    simctl.py show                           print the current state
"""
import json
import os
import sys
import tempfile
import time

STATE_FILE = os.environ.get("RS_STATE", "/tmp/rs-state.json")


def load():
    try:
        with open(STATE_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save(state):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(STATE_FILE) or ".", prefix=".rs-state.")
    with os.fdopen(fd, "w") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)
    os.chmod(tmp, 0o644)
    os.replace(tmp, STATE_FILE)


def parse(token):
    key, _, spec = token.partition("=")
    op, _, args = spec.partition(":")
    if not key or op not in ("set", "mul", "add", "ramp") or not args:
        raise ValueError(f"bad argument '{token}'")
    if op == "ramp":
        start, end, seconds = (float(x) for x in args.split(":"))
        return key, {"ramp": [start, end, time.time(), seconds]}
    return key, {op: float(args)}


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv else 2
    state = load()
    if argv[0] == "show":
        print(json.dumps(state, indent=1, sort_keys=True))
        return 0
    if argv[0] == "clear":
        for key in argv[1:] or list(state):
            state.pop(key, None)
    else:
        try:
            for token in argv:
                key, override = parse(token)
                state[key] = override
        except ValueError as exc:
            print(f"simctl: {exc}", file=sys.stderr)
            return 2
    save(state)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
