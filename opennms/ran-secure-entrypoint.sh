#!/usr/bin/env bash
# RAN-Secure Analytics Platform - wrapper around the stock Horizon entrypoint.
#
# Horizon 36 imports the SNMP data collection XML (datacollection-config.xml and
# datacollection/*.xml) into the database on the first start, then moves the XML
# files to etc_archive/. Copying those files back on every start breaks the
# config tester ("Group MIB2 does not exist"), so the RAN-Secure data collection
# files are applied only on the first start, before the import.
#
# Files placed in /opt/opennms-etc-overlay are copied into /opt/opennms/etc by
# the stock entrypoint (see opennms-container/core/container-fs/entrypoint.sh).
set -euo pipefail

ETC_OVERLAY=/opt/opennms-etc-overlay
FIRST_START=/opt/ran-secure/etc-first-start
CLOUD=/opt/ran-secure/etc-cloud

# Start from an empty etc overlay so nothing stale is re-applied.
find "${ETC_OVERLAY}" -mindepth 1 -delete

if [ ! -f /opt/opennms/etc/configured ]; then
  echo "RAN-Secure: first start - applying data collection config (imported into the database by Horizon)."
  cp -r "${FIRST_START}/." "${ETC_OVERLAY}/"
else
  echo "RAN-Secure: already configured - data collection config lives in the database."
fi

if [ -d "${CLOUD}" ]; then
  echo "RAN-Secure: cloud deployment - applying HTTPS reverse-proxy settings."
  cp -r "${CLOUD}/." "${ETC_OVERLAY}/"
fi

exec /entrypoint.sh "$@"
