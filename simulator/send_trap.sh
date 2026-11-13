#!/bin/sh
# Sends an SNMPv2c notification from this simulated element to OpenNMS (trapd).
# Runs inside a simulator container so the trap source IP is the element's own IP.
#
#   send_trap.sh cell-outage   <cellIndex> <cellName> <rat>
#   send_trap.sh cell-restored <cellIndex> <cellName> <rat>
#   send_trap.sh auth-failure  <nodeType>
#   send_trap.sh link-down     <ifIndex>
#   send_trap.sh link-up       <ifIndex>
#
# Transport / access elements (RAN-SECURE-NET-SIM-MIB). Names, services and current
# values are read from the element's own agent, so the trap matches what OpenNMS polls:
#   send_trap.sh lsp-protected|lsp-restored      <lspIndex>
#   send_trap.sh bgp-down|bgp-up                 <peerIndex>
#   send_trap.sh opt-los|opt-los-clear           <ifIndex>
#   send_trap.sh pon-los|pon-los-clear           <ifIndex>
#   send_trap.sh pon-dying-gasp                  <ifIndex> <onusThatLostPower>
#   send_trap.sh pon-dying-gasp-clear            <ifIndex>
#   send_trap.sh pon-rx-low|pon-rx-normal        <ifIndex>
#   send_trap.sh bcast-storm|bcast-storm-clear   <ifIndex> <broadcastPps>
set -eu

TRAP_HOST="${TRAP_HOST:-horizon}"
TRAP_PORT="${TRAP_PORT:-1162}"
COMMUNITY="${TRAP_COMMUNITY:-public}"
TARGET="${TRAP_HOST}:${TRAP_PORT}"

RAN_CELL=".1.3.6.1.4.1.32473.5.2.1.1"
RAN_NOTIF=".1.3.6.1.4.1.32473.5.3.0"
IF_ENTRY=".1.3.6.1.2.1.2.2.1"
IFX_ENTRY=".1.3.6.1.2.1.31.1.1.1"
NET=".1.3.6.1.4.1.32473.7"
NET_NOTIF="${NET}.9.0"
LSP="${NET}.2.1.1"
BGP="${NET}.2.2.1"
OPT="${NET}.4.1.1"
PON="${NET}.5.1.1"
SW="${NET}.3"

trap_v2() { snmptrap -v 2c -c "$COMMUNITY" "$TARGET" '' "$@"; }
# Value of one object from this element's own simulated agent (quotes stripped).
get() { snmpget -v 2c -c public -Oqv "${SNMP_AGENT:-127.0.0.1:1161}" "$1" | tr -d '"'; }

case "${1:-}" in
  cell-outage)
    trap_v2 "${RAN_NOTIF}.1" "${RAN_CELL}.2.$2" s "$3" "${RAN_CELL}.3.$2" s "$4" ;;
  cell-restored)
    trap_v2 "${RAN_NOTIF}.2" "${RAN_CELL}.2.$2" s "$3" "${RAN_CELL}.3.$2" s "$4" ;;
  auth-failure)
    trap_v2 "${RAN_NOTIF}.3" ".1.3.6.1.4.1.32473.5.1.1.0" s "$2" ;;
  link-down)   # IF-MIB::linkDown  (ifIndex, ifAdminStatus=up, ifOperStatus=down)
    trap_v2 ".1.3.6.1.6.3.1.1.5.3" "${IF_ENTRY}.1.$2" i "$2" "${IF_ENTRY}.7.$2" i 1 "${IF_ENTRY}.8.$2" i 2 ;;
  link-up)     # IF-MIB::linkUp
    trap_v2 ".1.3.6.1.6.3.1.1.5.4" "${IF_ENTRY}.1.$2" i "$2" "${IF_ENTRY}.7.$2" i 1 "${IF_ENTRY}.8.$2" i 1 ;;
  lsp-protected|lsp-restored)
    n=1; [ "$1" = lsp-restored ] && n=2
    trap_v2 "${NET_NOTIF}.$n" "${LSP}.2.$2" s "$(get "${LSP}.2.$2")" "${LSP}.3.$2" s "$(get "${LSP}.3.$2")" ;;
  bgp-down|bgp-up)
    n=3; [ "$1" = bgp-up ] && n=4
    trap_v2 "${NET_NOTIF}.$n" "${BGP}.2.$2" s "$(get "${BGP}.2.$2")" "${BGP}.3.$2" s "$(get "${BGP}.3.$2")" ;;
  opt-los|opt-los-clear)
    n=5; [ "$1" = opt-los-clear ] && n=6
    trap_v2 "${NET_NOTIF}.$n" "${OPT}.2.$2" s "$(get "${OPT}.2.$2")" "${OPT}.3.$2" s "$(get "${OPT}.3.$2")" ;;
  pon-los|pon-los-clear)
    n=7; [ "$1" = pon-los-clear ] && n=8
    trap_v2 "${NET_NOTIF}.$n" "${PON}.2.$2" s "$(get "${PON}.2.$2")" "${PON}.4.$2" u "$(get "${PON}.4.$2")" ;;
  pon-dying-gasp)
    trap_v2 "${NET_NOTIF}.9" "${PON}.2.$2" s "$(get "${PON}.2.$2")" "${NET}.5.2.0" u "$3" \
            "${PON}.4.$2" u "$(get "${PON}.4.$2")" ;;
  pon-dying-gasp-clear)
    trap_v2 "${NET_NOTIF}.10" "${PON}.2.$2" s "$(get "${PON}.2.$2")" "${PON}.4.$2" u "$(get "${PON}.4.$2")" ;;
  pon-rx-low|pon-rx-normal)
    n=11; [ "$1" = pon-rx-normal ] && n=12
    trap_v2 "${NET_NOTIF}.$n" "${PON}.2.$2" s "$(get "${PON}.2.$2")" "${PON}.6.$2" i "$(get "${PON}.6.$2")" ;;
  bcast-storm|bcast-storm-clear)
    n=13; [ "$1" = bcast-storm-clear ] && n=14
    trap_v2 "${NET_NOTIF}.$n" "${SW}.3.0" s "$(get "${IFX_ENTRY}.1.$2")" "${SW}.4.0" s "$(get "${IFX_ENTRY}.18.$2")" \
            "${SW}.2.0" u "$3" ;;
  *)
    sed -n '2,24p' "$0" >&2
    exit 2 ;;
esac
echo "trap '$1' sent to ${TARGET}"
