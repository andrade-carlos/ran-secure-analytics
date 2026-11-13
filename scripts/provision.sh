#!/usr/bin/env bash
# RAN-Secure Analytics Platform - provisioning of the demo environment.
# Safe to run again after every update (it only creates or updates configuration).
#
#  1. waits until OpenNMS Horizon is up
#  2. uploads the event definitions (alarms for RAN, transport and access notifications)
#  3. uploads the SNMP data collection groups (RAN KPIs + transport/access metrics)
#  4. uploads the RAN-Sim provisioning policy (collect statistics on every interface)
#  5. creates the "RAN-Sim" requisition and imports the simulated network elements
#
# Usage: ./scripts/provision.sh            (reads credentials from .env)
#
# After the first run on an existing server, restart Horizon once so it reloads the
# graph definitions and the surveillance view:  docker compose restart horizon
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

ONMS_URL="${ONMS_URL:-http://127.0.0.1:8980/opennms}"
AUTH="${OPENNMS_API_USER:-admin}:${OPENNMS_API_PASSWORD:-admin}"
FS="RAN-Sim"
DC_PROFILE="${ONMS_DC_PROFILE:-default}"     # SNMP data collection profile (snmp-collection name)

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

log "Waiting for OpenNMS at ${ONMS_URL} ..."
for i in $(seq 1 90); do
  if curl -sf "${ONMS_URL}/rest/health/probe" | grep -q "Everything is awesome"; then
    log "OpenNMS is up."
    break
  fi
  [ "$i" -eq 90 ] && { log "OpenNMS did not come up in time (check: docker compose logs horizon)"; exit 1; }
  sleep 10
done

for f in opennms/events/*.events.xml; do
  log "Uploading event definitions ($(basename "$f")) ..."
  curl -sf -u "$AUTH" -X POST \
    -F "upload=@${f};type=application/xml" \
    "${ONMS_URL}/api/v2/eventconf/upload" >/dev/null \
    && log "  uploaded." \
    || log "  WARNING: upload failed (already uploaded? check Admin > Manage Event Configuration)."
done

log "Uploading SNMP data collection groups to profile '${DC_PROFILE}' ..."
dc_args=()
for f in opennms/etc-first-start/datacollection/*.xml; do
  dc_args+=(-F "upload=@${f};type=application/xml")
done
if dc_out=$(curl -sS -u "$AUTH" -X POST "${dc_args[@]}" -F "profileNames=${DC_PROFILE}" \
      -w '\nHTTP %{http_code}' "${ONMS_URL}/api/v2/datacollectionconf/upload"); then
  log "  response: $(echo "$dc_out" | tr -s '\n' ' ' | cut -c1-400)"
else
  log "  WARNING: data collection upload failed - add the groups in Admin > Manage SNMP Data Collection Config."
fi

log "Uploading provisioning policy for ${FS} (collect statistics on all interfaces) ..."
curl -sf -u "$AUTH" -X POST -H "Content-Type: application/xml" \
  --data-binary @opennms/requisition/RAN-Sim.foreign-source.xml \
  "${ONMS_URL}/rest/foreignSources" >/dev/null \
  && log "  uploaded." \
  || log "  WARNING: foreign source upload failed (check Admin > Manage Provisioning Requisitions > ${FS} > Edit Definition)."

log "Creating requisition ${FS} ..."
curl -sf -u "$AUTH" -X POST -H "Content-Type: application/xml" \
  --data-binary @opennms/requisition/RAN-Sim.xml \
  "${ONMS_URL}/rest/requisitions" >/dev/null

log "Importing requisition ${FS} ..."
curl -sf -u "$AUTH" -X PUT "${ONMS_URL}/rest/requisitions/${FS}/import?rescanExisting=true" >/dev/null

log "Done. Nodes appear within 1-2 minutes; graphs after 2-3 collection cycles (5 min each)."
log "Topology map (LLDP) is built ~1 minute after Horizon starts: Maps > Topology > Enhanced Linkd."
log "OpenNMS: ${ONMS_URL}   Grafana: http://127.0.0.1:3000"
