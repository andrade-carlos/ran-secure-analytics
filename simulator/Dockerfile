# RAN-Secure Analytics Platform - simulated network element (RAN, IP/MPLS, switch, DWDM, GPON)
# One container = one network element (own IP, own SNMP agent, own data file).
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends snmp iputils-ping \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir snmpsim==1.2.2 pysnmp==7.1.32 pysmi==2.0.0 \
 && useradd --system --uid 10010 --home /app sim

WORKDIR /app
# rsdyn: time-varying values that demo scenarios can change at run time (simctl.py)
COPY variation/rsdyn.py /tmp/rsdyn.py
RUN python -c "import os, shutil, snmpsim; shutil.move('/tmp/rsdyn.py', os.path.join(os.path.dirname(snmpsim.__file__), 'variation', 'rsdyn.py'))"
COPY send_trap.sh /app/send_trap.sh
COPY simctl.py /app/simctl.py
RUN chmod 0755 /app/send_trap.sh /app/simctl.py && mkdir -p /tmp/snmpsim && chown sim /tmp/snmpsim

USER sim
ENV MIBS=""
ENV RS_STATE=/tmp/rs-state.json
# The element's data file is mounted at /data/public.snmprec (community "public").
EXPOSE 1161/udp
CMD ["snmpsim-command-responder", \
     "--data-dir=/data", \
     "--cache-dir=/tmp/snmpsim", \
     "--agent-udpv4-endpoint=0.0.0.0:1161"]
