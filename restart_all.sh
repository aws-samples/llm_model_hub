#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Restarting All Services ==="
echo ""

# 停止前端
echo "Stopping frontend..."
bash "${SCRIPT_DIR}/stop_frontend.sh"

# 停止后端
echo "Stopping backend..."
bash "${SCRIPT_DIR}/backend/stop_backend.sh"

sleep 2

# 启动后端
echo ""
echo "Starting backend..."
bash "${SCRIPT_DIR}/backend/02.start_backend.sh"

# 启动前端
echo ""
echo "Starting frontend..."
bash "${SCRIPT_DIR}/start_frontend.sh"

echo ""
echo "=== All Services Restarted ==="
echo ""
echo "Frontend: http://localhost:3000"
echo "Backend:  http://localhost:8000"
echo "Logs:     ${SCRIPT_DIR}/logs/"
