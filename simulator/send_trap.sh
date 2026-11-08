#!/bin/sh
# Sends an SNMPv2c notification from this simulated element to OpenNMS (trapd).
# Runs inside a simulator container so the trap source IP is the element's own IP.
#
#   send_trap.sh cell-outage   <cellIndex> <cellName> <rat>
#   send_trap.sh cell-restored <cellIndex> <cellName> <rat>
#   send_trap.sh auth-failure  <nodeType>
#   send_trap.sh link-down     <ifIndex>
#   send_trap.sh link-up       <ifIndex>
set -eu

TRAP_HOST="${TRAP_HOST:-horizon}"
TRAP_PORT="${TRAP_PORT:-1162}"
COMMUNITY="${TRAP_COMMUNITY:-public}"
TARGET="${TRAP_HOST}:${TRAP_PORT}"

RAN_CELL=".1.3.6.1.4.1.32473.5.2.1.1"
RAN_NOTIF=".1.3.6.1.4.1.32473.5.3.0"
IF_ENTRY=".1.3.6.1.2.1.2.2.1"

trap_v2() { snmptrap -v 2c -c "$COMMUNITY" "$TARGET" '' "$@"; }

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
  *)
    echo "usage: $0 {cell-outage|cell-restored} <idx> <name> <rat> | auth-failure <type> | {link-down|link-up} <ifIndex>" >&2
    exit 2 ;;
esac
echo "trap '$1' sent to ${TARGET}"
