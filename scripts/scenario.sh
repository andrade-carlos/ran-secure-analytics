#!/usr/bin/env bash
# RAN-Secure Analytics Platform - fault & security scenarios for live demos.
#
#   ./scripts/scenario.sh cell-outage      # gNodeB cell NR-102-B goes out of service  -> Major alarm
#   ./scripts/scenario.sh cell-restore     # cell back in service                     -> alarm cleared
#   ./scripts/scenario.sh site-down        # power loss at rural site enb-rural-202   -> nodeDown / outage
#   ./scripts/scenario.sh site-up          # power restored                           -> nodeUp
#   ./scripts/scenario.sh backhaul-flap    # csr-hub-01 port to gnb-site-101 down/up  -> linkDown / linkUp
#   ./scripts/scenario.sh brute-force      # repeated failed OAM logins on gnb-site-101 -> Critical security alarm
#   ./scripts/scenario.sh restore-all      # put everything back to normal
#
# Every scenario is logged to docs/demo-runs.log (UTC) so each demo run leaves a record.
set -euo pipefail

cd "$(dirname "$0")/.."
LOG=docs/demo-runs.log
dc() { docker compose "$@"; }
trap_from() { local el="$1"; shift; dc exec -T "$el" /app/send_trap.sh "$@"; }
record() { printf '%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; echo "$*"; }

case "${1:-}" in
  cell-outage)
    trap_from gnb-site-102 cell-outage 2 NR-102-B NR
    record "cell-outage: NR-102-B on gnb-site-102 out of service" ;;
  cell-restore)
    trap_from gnb-site-102 cell-restored 2 NR-102-B NR
    record "cell-restore: NR-102-B on gnb-site-102 back in service" ;;
  site-down)
    dc stop enb-rural-202
    record "site-down: enb-rural-202 stopped (simulated power loss); expect nodeDown within ~5 min" ;;
  site-up)
    dc start enb-rural-202
    record "site-up: enb-rural-202 started (power restored)" ;;
  backhaul-flap)
    trap_from csr-hub-01 link-down 2
    sleep "${FLAP_SECONDS:-60}"
    trap_from csr-hub-01 link-up 2
    record "backhaul-flap: csr-hub-01 ge-0/0/1 (to gnb-site-101) down/up" ;;
  brute-force)
    for _ in 1 2 3; do trap_from gnb-site-101 auth-failure gNodeB; sleep 2; done
    record "brute-force: 3x ranSecurityAuthFailure from gnb-site-101" ;;
  restore-all)
    dc start enb-rural-202 >/dev/null 2>&1 || true
    trap_from gnb-site-102 cell-restored 2 NR-102-B NR
    trap_from csr-hub-01 link-up 2
    record "restore-all: all simulated faults cleared" ;;
  *)
    sed -n '2,12p' "$0"; exit 2 ;;
esac
