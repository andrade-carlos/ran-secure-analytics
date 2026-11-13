#!/usr/bin/env bash
# RAN-Secure Analytics Platform - fault & security scenarios for live demos.
#
#  RAN
#   ./scripts/scenario.sh cell-outage            # gNodeB cell NR-102-B out of service       -> Major alarm
#   ./scripts/scenario.sh cell-restore           # cell back in service                     -> alarm cleared
#   ./scripts/scenario.sh site-down              # power loss at rural site enb-rural-202   -> nodeDown / outage
#   ./scripts/scenario.sh site-up                # power restored                           -> nodeUp
#   ./scripts/scenario.sh backhaul-flap          # csr-hub-01 port to gnb-site-101 down/up  -> linkDown / linkUp
#   ./scripts/scenario.sh brute-force            # failed OAM logins on gnb-site-101        -> Critical security alarm
#  Transport (DWDM + IP/MPLS)
#   ./scripts/scenario.sh fiber-cut              # DWDM span 2 cut: optical LOS, core link down, LSPs on secondary path
#   ./scripts/scenario.sh fiber-repair           # span spliced: everything back on the primary path
#   ./scripts/scenario.sh bgp-down               # upstream transit session lost on pe-core-02  -> Major alarm
#   ./scripts/scenario.sh bgp-up                 # session re-established                      -> alarm cleared
#   ./scripts/scenario.sh l2-storm               # layer-2 loop at a business customer (sw-access-01) -> broadcast storm
#   ./scripts/scenario.sh l2-storm-clear         # loop removed
#  GPON / FTTH access
#   ./scripts/scenario.sh ftth-power-outage      # mains power cut in Zone C: 49 ONUs dying gasp (no fiber fault)
#   ./scripts/scenario.sh ftth-power-restore     # power back, ONUs online again
#   ./scripts/scenario.sh pon-fiber-cut          # feeder fiber of Zone E cut: all ONUs lost without dying gasp
#   ./scripts/scenario.sh pon-fiber-repair       # feeder repaired
#   ./scripts/scenario.sh pon-degradation        # ONU Rx power on a rural PON drifts down; alarm at -27 dBm
#   ./scripts/scenario.sh pon-degradation-repair # connector cleaned, levels back to normal
#  General
#   ./scripts/scenario.sh status                 # show which simulated faults are active
#   ./scripts/scenario.sh restore-all            # put everything back to normal
#
# Every scenario is logged to docs/demo-runs.log (UTC) so each demo run leaves a record.
# Tunables (environment): FLAP_SECONDS (backhaul-flap, default 60),
#                         DEGRADE_SECONDS (pon-degradation drift duration, default 1200)
set -euo pipefail

cd "$(dirname "$0")/.."
LOG=docs/demo-runs.log
dc() { docker compose "$@"; }
trap_from() { local el="$1"; shift; dc exec -T "$el" /app/send_trap.sh "$@"; }
# Change live values of a simulated element (see simulator/simctl.py)
sim() { local el="$1"; shift; dc exec -T "$el" /app/simctl.py "$@"; }
# True if a simulated element has a scenario override for <key>
active() { local st; st=$(dc exec -T "$1" /app/simctl.py show 2>/dev/null) || return 1; grep -qF "\"$2\"" <<< "$st"; }
record() { printf '%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; echo "$*"; }

TRANSPORT_ELEMENTS="pe-core-01 p-core-01 pe-core-02 sw-agg-01 sw-access-01 roadm-01 ila-01 roadm-02 olt-town-01 olt-rural-02"
LOS=-4000            # 0.01 dBm: -40 dBm = no light
BER_FAIL=500000000   # errored bits per 1e9 = 0.5 (no usable signal)

fiber_cut() {
  # Span 2 (ila-01 LINE-E <-> roadm-02 LINE-W) is cut. The in-line amplifier loses its
  # input from roadm-02 and shuts its westbound output (automatic power reduction),
  # so roadm-01 also sees loss of signal on span 1 although that fiber is intact.
  sim roadm-02 opt2.rx=set:$LOS opt2.ch=set:0 if2.oper=set:2 \
               opt3.osnr=set:0 opt3.ber=set:$BER_FAIL opt3.tx=set:$LOS if3.oper=set:2 if3.t=mul:0 \
               opt4.osnr=set:0 opt4.ber=set:$BER_FAIL opt4.tx=set:$LOS if4.oper=set:2 if4.t=mul:0
  sim ila-01   opt3.rx=set:$LOS opt3.ch=set:0 if3.oper=set:2 opt2.tx=set:$LOS opt2.ch=set:0
  sim roadm-01 opt2.rx=set:$LOS opt2.ch=set:0 if2.oper=set:2 \
               opt3.osnr=set:0 opt3.ber=set:$BER_FAIL opt3.tx=set:$LOS if3.oper=set:2 if3.t=mul:0 \
               opt4.osnr=set:0 opt4.ber=set:$BER_FAIL opt4.tx=set:$LOS if4.oper=set:2 if4.t=mul:0
  # IP/MPLS: the 100G link carried by lambda 1 goes down; RSVP-TE moves the LSPs to the
  # secondary path over the diverse fiber route (more traffic there, higher latency).
  sim pe-core-01 if3.oper=set:2 if3.t=mul:0 if4.t=mul:4.5 \
                 lsp1.path=set:2 lsp2.path=set:2 lsp1.lat=set:1460 lsp2.lat=set:1475
  sim p-core-01  if2.oper=set:2 if2.t=mul:0 if3.t=mul:0.15
  sim pe-core-02 if2.t=mul:0.15 if3.t=mul:4.5 \
                 lsp1.path=set:2 lsp2.path=set:2 lsp1.lat=set:1465 lsp2.lat=set:1480
  # Notifications, in the order the equipment would raise them
  trap_from roadm-02 opt-los 2
  trap_from ila-01 opt-los 3
  trap_from roadm-01 opt-los 2
  for el in roadm-02 roadm-01; do trap_from "$el" opt-los 3; trap_from "$el" opt-los 4; done
  trap_from pe-core-01 link-down 3
  trap_from p-core-01 link-down 2
  for el in pe-core-01 pe-core-02; do trap_from "$el" lsp-protected 1; trap_from "$el" lsp-protected 2; done
}

fiber_repair() {
  local roadm_keys="opt2.rx opt2.ch if2.oper opt3.osnr opt3.ber opt3.tx if3.oper if3.t opt4.osnr opt4.ber opt4.tx if4.oper if4.t"
  sim roadm-02 clear $roadm_keys
  sim ila-01   clear opt3.rx opt3.ch if3.oper opt2.tx opt2.ch
  sim roadm-01 clear $roadm_keys
  sim pe-core-01 clear if3.oper if3.t if4.t lsp1.path lsp2.path lsp1.lat lsp2.lat
  sim p-core-01  clear if2.oper if2.t if3.t
  sim pe-core-02 clear if2.t if3.t lsp1.path lsp2.path lsp1.lat lsp2.lat
  trap_from roadm-02 opt-los-clear 2
  trap_from ila-01 opt-los-clear 3
  trap_from roadm-01 opt-los-clear 2
  for el in roadm-02 roadm-01; do trap_from "$el" opt-los-clear 3; trap_from "$el" opt-los-clear 4; done
  trap_from pe-core-01 link-up 3
  trap_from p-core-01 link-up 2
  for el in pe-core-01 pe-core-02; do trap_from "$el" lsp-restored 1; trap_from "$el" lsp-restored 2; done
}

bgp_down() {
  # Transit-A drops: full Internet table withdrawn on pe-core-02 and, through iBGP, on pe-core-01
  sim pe-core-02 bgp1.state=set:1 bgp1.pfx=set:0 if5.t=mul:0.05
  sim pe-core-01 bgp1.pfx=set:150
  trap_from pe-core-02 bgp-down 1
}

bgp_up() {
  sim pe-core-02 clear bgp1.state bgp1.pfx if5.t
  sim pe-core-01 clear bgp1.pfx
  trap_from pe-core-02 bgp-up 1
}

l2_storm() {
  # Loop at BIZ-1003 (sw-access-01 ge-0/0/3, ifIndex 5): broadcast explodes, MAC table
  # flaps, STP topology changes, switch CPU saturates; the storm leaks to the aggregation.
  sim sw-access-01 if5.bc=mul:1500 if5.t=mul:8 if2.t=mul:3 cpu=set:91 macs=set:7400 stp=mul:1500
  sim sw-agg-01 if5.bc=mul:300 if5.t=mul:2
  trap_from sw-access-01 bcast-storm 5 45000
}

l2_storm_clear() {
  sim sw-access-01 clear if5.bc if5.t if2.t cpu macs stp
  sim sw-agg-01 clear if5.bc if5.t
  trap_from sw-access-01 bcast-storm-clear 5 30
}

ftth_power_outage() {
  # Zone C (olt-town-01 gpon-0/1/3, ifIndex 5, 58 ONUs): 49 ONUs lose mains power
  sim olt-town-01 pon5.on=set:9 pon5.dl=mul:0.15 pon5.ul=mul:0.15 if5.t=mul:0.15
  trap_from olt-town-01 pon-dying-gasp 5 49
}

ftth_power_restore() {
  sim olt-town-01 clear pon5.on pon5.dl pon5.ul if5.t
  trap_from olt-town-01 pon-dying-gasp-clear 5
}

pon_fiber_cut() {
  # Zone E (olt-town-01 gpon-0/1/5, ifIndex 7, 62 ONUs): feeder cut, no dying gasp
  sim olt-town-01 pon7.on=set:0 pon7.rxavg=set:$LOS pon7.rxworst=set:$LOS pon7.dl=set:0 pon7.ul=set:0 \
                  if7.t=mul:0 if7.oper=set:2
  trap_from olt-town-01 pon-los 7
}

pon_fiber_repair() {
  sim olt-town-01 clear pon7.on pon7.rxavg pon7.rxworst pon7.dl pon7.ul if7.t if7.oper
  trap_from olt-town-01 pon-los-clear 7
}

pon_degradation() {
  # Rural PON 0/1/2 (olt-rural-02, ifIndex 4): a dirty connector at the splitter makes the
  # ONU receive power drift down. The OLT raises its alarm when the worst ONU crosses
  # -27 dBm, before subscribers (class B+, -28 dBm) lose service.
  local secs="${DEGRADE_SECONDS:-1200}"
  local alarm_after=$(( secs * (2720 - 2510) / (2860 - 2510) ))
  sim olt-rural-02 pon4.rxworst=ramp:-2510:-2860:"$secs" pon4.rxavg=ramp:-2030:-2330:"$secs"
  dc exec -d olt-rural-02 sh -c \
    "sleep ${alarm_after}; /app/simctl.py show | grep -q pon4.rxworst && /app/send_trap.sh pon-rx-low 4"
  echo "ONU Rx power drifting over ${secs}s; the OLT alarm (pon-rx-low) fires in ~${alarm_after}s."
}

pon_degradation_repair() {
  sim olt-rural-02 clear pon4.rxworst pon4.rxavg
  trap_from olt-rural-02 pon-rx-normal 4
}

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
  fiber-cut)
    fiber_cut
    record "fiber-cut: DWDM span 2 (ila-01 <> roadm-02) cut; lambda 1 and WS-0042 down; LSPs on secondary path" ;;
  fiber-repair)
    fiber_repair
    record "fiber-repair: DWDM span 2 restored; LSPs back on primary path" ;;
  bgp-down)
    bgp_down
    record "bgp-down: Transit-A AS64500 session on pe-core-02 down" ;;
  bgp-up)
    bgp_up
    record "bgp-up: Transit-A AS64500 session on pe-core-02 established" ;;
  l2-storm)
    l2_storm
    record "l2-storm: broadcast storm on sw-access-01 ge-0/0/3 (BIZ-1003)" ;;
  l2-storm-clear)
    l2_storm_clear
    record "l2-storm-clear: broadcast storm on sw-access-01 ge-0/0/3 cleared" ;;
  ftth-power-outage)
    ftth_power_outage
    record "ftth-power-outage: 49 ONUs dying gasp on olt-town-01 gpon-0/1/3 (Zone C)" ;;
  ftth-power-restore)
    ftth_power_restore
    record "ftth-power-restore: ONUs back online on olt-town-01 gpon-0/1/3" ;;
  pon-fiber-cut)
    pon_fiber_cut
    record "pon-fiber-cut: feeder cut on olt-town-01 gpon-0/1/5 (Zone E), all ONUs lost" ;;
  pon-fiber-repair)
    pon_fiber_repair
    record "pon-fiber-repair: feeder repaired on olt-town-01 gpon-0/1/5" ;;
  pon-degradation)
    pon_degradation
    record "pon-degradation: ONU Rx power drifting down on olt-rural-02 gpon-0/1/2" ;;
  pon-degradation-repair)
    pon_degradation_repair
    record "pon-degradation-repair: olt-rural-02 gpon-0/1/2 levels back to normal" ;;
  status)
    for el in $TRANSPORT_ELEMENTS; do
      state=$(dc exec -T "$el" /app/simctl.py show 2>/dev/null | tr -d ' \n' || echo '?')
      [ "$state" = "{}" ] && state="normal"
      printf '%-14s %s\n' "$el" "$state"
    done ;;
  restore-all)
    dc start enb-rural-202 >/dev/null 2>&1 || true
    trap_from gnb-site-102 cell-restored 2 NR-102-B NR || true
    trap_from csr-hub-01 link-up 2 || true
    active roadm-02 opt2.rx && fiber_repair
    active pe-core-02 bgp1.state && bgp_up
    active sw-access-01 if5.bc && l2_storm_clear
    active olt-town-01 pon5.on && ftth_power_restore
    active olt-town-01 pon7.on && pon_fiber_repair
    active olt-rural-02 pon4.rxworst && pon_degradation_repair
    for el in $TRANSPORT_ELEMENTS; do sim "$el" clear; done
    record "restore-all: all simulated faults cleared" ;;
  *)
    sed -n '2,29p' "$0"; exit 2 ;;
esac
