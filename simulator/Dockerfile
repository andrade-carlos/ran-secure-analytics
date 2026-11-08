# RAN-Secure Analytics Platform - simulated RAN network element
# One container = one network element (own IP, own SNMP agent, own data file).
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends snmp iputils-ping \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir snmpsim==1.2.2 pysnmp==7.1.32 pysmi==2.0.0 \
 && useradd --system --uid 10010 --home /app sim

WORKDIR /app
COPY send_trap.sh /app/send_trap.sh
RUN chmod 0755 /app/send_trap.sh && mkdir -p /tmp/snmpsim && chown sim /tmp/snmpsim

USER sim
ENV MIBS=""
# The element's data file is mounted at /data/public.snmprec (community "public").
EXPOSE 1161/udp
CMD ["snmpsim-command-responder", \
     "--data-dir=/data", \
     "--cache-dir=/tmp/snmpsim", \
     "--agent-udpv4-endpoint=0.0.0.0:1161"]
