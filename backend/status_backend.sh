#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/.backend_pids"

echo "=== Backend Services Status ==="
echo ""

if [ ! -f "${PID_FILE}" ]; then
    echo "No PID file found. Services may not be running."
    exit 0
fi

services=("modelhub-server" "modelhub-engine" "modelhub-cluster")
i=0

while read pid; do
    service_name="${services[$i]}"
    if kill -0 "$pid" 2>/dev/null; then
        echo "[RUNNING] ${service_name} (PID: $pid)"
    else
        echo "[STOPPED] ${service_name} (PID: $pid was not found)"
    fi
    ((i++))
done < "${PID_FILE}"

echo ""
echo "Log files: ${SCRIPT_DIR}/../logs/"
