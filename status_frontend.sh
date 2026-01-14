#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/.frontend_pid"

echo "=== Frontend Status ==="
echo ""

if [ ! -f "${PID_FILE}" ]; then
    echo "[STOPPED] Frontend (no PID file)"
    exit 0
fi

pid=$(cat "${PID_FILE}")
if kill -0 "$pid" 2>/dev/null; then
    echo "[RUNNING] Frontend (PID: $pid)"
    echo "URL: http://localhost:3000"
else
    echo "[STOPPED] Frontend (PID: $pid was not found)"
fi

echo ""
echo "Log file: ${SCRIPT_DIR}/logs/frontend.log"
