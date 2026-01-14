#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
PID_FILE="${SCRIPT_DIR}/.frontend_pid"

# 创建日志目录
mkdir -p "${LOG_DIR}"

cd "${SCRIPT_DIR}"

# 停止已有进程
if [ -f "${PID_FILE}" ]; then
    pid=$(cat "${PID_FILE}")
    if kill -0 "$pid" 2>/dev/null; then
        echo "Stopping existing frontend process (PID: $pid)..."
        kill "$pid" 2>/dev/null
        sleep 2
    fi
    rm -f "${PID_FILE}"
fi

# 启动前端
echo "Starting frontend..."
nohup npm start > "${LOG_DIR}/frontend.log" 2>&1 &
echo $! > "${PID_FILE}"

echo ""
echo "Frontend started. PID: $(cat ${PID_FILE})"
echo "Log: ${LOG_DIR}/frontend.log"
echo ""
echo "To view logs: tail -f ${LOG_DIR}/frontend.log"
echo "To stop: bash ${SCRIPT_DIR}/stop_frontend.sh"
