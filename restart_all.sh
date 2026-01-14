#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 解析参数 - 传递给 start_frontend.sh
FRONTEND_ARGS=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --prod|-p|--port)
            FRONTEND_ARGS="$FRONTEND_ARGS $1"
            if [[ "$1" == "--port" ]]; then
                FRONTEND_ARGS="$FRONTEND_ARGS $2"
                shift
            fi
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--prod|-p] [--port PORT]"
            echo "  --prod, -p    Start frontend in production mode"
            echo "  --port PORT   Frontend port (default: 3000)"
            exit 1
            ;;
    esac
done

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
bash "${SCRIPT_DIR}/start_frontend.sh" $FRONTEND_ARGS

echo ""
echo "=== All Services Restarted ==="
echo ""
echo "Frontend: http://localhost:3000"
echo "Backend:  http://localhost:8000"
echo "Logs:     ${SCRIPT_DIR}/logs/"
