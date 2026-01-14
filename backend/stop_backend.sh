#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/.backend_pids"

if [ ! -f "${PID_FILE}" ]; then
    echo "No PID file found. Services may not be running."
    exit 0
fi

echo "Stopping backend services..."
while read pid; do
    if kill -0 "$pid" 2>/dev/null; then
        echo "Stopping process $pid..."
        kill "$pid" 2>/dev/null
    fi
done < "${PID_FILE}"

rm -f "${PID_FILE}"
echo "All services stopped."
