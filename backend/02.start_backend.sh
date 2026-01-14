#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="${SCRIPT_DIR}/.venv/bin/python3"
LOG_DIR="${SCRIPT_DIR}/../logs"
PID_FILE="${SCRIPT_DIR}/.backend_pids"

# 创建日志目录
mkdir -p "${LOG_DIR}"


cd "${SCRIPT_DIR}"

# 停止已有进程
if [ -f "${PID_FILE}" ]; then
    echo "Stopping existing processes..."
    while read pid; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
        fi
    done < "${PID_FILE}"
    rm -f "${PID_FILE}"
    sleep 2
fi

# 启动 modelhub-server
echo "Starting modelhub-server..."
nohup "${VENV_PYTHON}" server.py --host 0.0.0.0 --port 8000 > "${LOG_DIR}/modelhub-server.log" 2>&1 &
echo $! >> "${PID_FILE}"

# 启动 modelhub-engine
echo "Starting modelhub-engine..."
nohup "${VENV_PYTHON}" processing_engine/main.py > "${LOG_DIR}/modelhub-engine.log" 2>&1 &
echo $! >> "${PID_FILE}"

# 启动 modelhub-cluster
echo "Starting modelhub-cluster..."
nohup "${VENV_PYTHON}" processing_engine/cluster_processor.py > "${LOG_DIR}/modelhub-cluster.log" 2>&1 &
echo $! >> "${PID_FILE}"

echo ""
echo "All services started. PIDs saved to ${PID_FILE}"
echo "Logs available at:"
echo "  - ${LOG_DIR}/modelhub-server.log"
echo "  - ${LOG_DIR}/modelhub-engine.log"
echo "  - ${LOG_DIR}/modelhub-cluster.log"
echo ""
echo "To view logs: tail -f ${LOG_DIR}/*.log"
echo "To stop all: bash ${SCRIPT_DIR}/stop_backend.sh"
