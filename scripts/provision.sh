#!/usr/bin/env bash
# RAN-Secure Analytics Platform - first-time provisioning of the demo environment.
#
#  1. waits until OpenNMS Horizon is up
#  2. uploads the RAN-SECURE-SIM-MIB event definitions (alarms for cell outage / security)
#  3. creates the "RAN-Sim" requisition and imports the simulated network elements
#
# Usage: ./scripts/provision.sh            (reads credentials from .env)
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

ONMS_URL="${ONMS_URL:-http://127.0.0.1:8980/opennms}"
AUTH="${OPENNMS_API_USER:-admin}:${OPENNMS_API_PASSWORD:-admin}"
FS="RAN-Sim"

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

log "Uploading event definitions (RAN-Secure-Sim.events.xml) ..."
curl -sf -u "$AUTH" -X POST \
  -F "upload=@opennms/events/RAN-Secure-Sim.events.xml;type=application/xml" \
  "${ONMS_URL}/api/v2/eventconf/upload" >/dev/null \
  && log "Event definitions uploaded." \
  || log "WARNING: event upload failed (already uploaded? check Admin > Manage Event Configuration)."

log "Creating requisition ${FS} ..."
curl -sf -u "$AUTH" -X POST -H "Content-Type: application/xml" \
  --data-binary @opennms/requisition/RAN-Sim.xml \
  "${ONMS_URL}/rest/requisitions" >/dev/null

log "Importing requisition ${FS} ..."
curl -sf -u "$AUTH" -X PUT "${ONMS_URL}/rest/requisitions/${FS}/import?rescanExisting=true" >/dev/null

log "Done. Nodes appear within 1-2 minutes; KPI graphs after 2-3 collection cycles (5 min each)."
log "OpenNMS: ${ONMS_URL}   Grafana: http://127.0.0.1:3000"
