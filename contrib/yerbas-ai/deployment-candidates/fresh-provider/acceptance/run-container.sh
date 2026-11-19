#!/bin/bash
set -euo pipefail
base=$(cd "$(dirname "$0")/.." && pwd)
: "${YERBAS_OFFLINE_WHEELS:?Set the absolute pinned offline wheel directory}"
docker run --name yerbas-clean-install-20261118-c --network none --cap-drop ALL --cap-add CHOWN --cap-add FOWNER --cap-add SETUID --cap-add SETGID --cap-add DAC_OVERRIDE \
 --mount "type=bind,src=$base,dst=/candidate,readonly" \
 --mount "type=bind,src=$YERBAS_OFFLINE_WHEELS,dst=/wheels,readonly" \
 --mount "type=bind,src=$base/acceptance,dst=/evidence" \
 yerbas-clean-install:20261118 /bin/sh -c 'touch /CLEAN_INSTALL_CONTAINER; exec /usr/bin/python3 -I -B /evidence/container_probe.py'
