#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/.frontend_pid"

if [ ! -f "${PID_FILE}" ]; then
    echo "No PID file found. Frontend may not be running."
    exit 0
fi

pid=$(cat "${PID_FILE}")
if kill -0 "$pid" 2>/dev/null; then
    echo "Stopping frontend (PID: $pid)..."
    kill "$pid" 2>/dev/null
    # 同时杀掉子进程 (node)
    pkill -P "$pid" 2>/dev/null
    echo "Frontend stopped."
else
    echo "Frontend process not found."
fi

rm -f "${PID_FILE}"
