#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
PID_FILE="${SCRIPT_DIR}/.frontend_pid"

# 解析参数
PROD_MODE=false
PORT=3000

while [[ $# -gt 0 ]]; do
    case $1 in
        --prod|-p)
            PROD_MODE=true
            shift
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--prod|-p] [--port PORT]"
            echo "  --prod, -p    Start production build (faster startup)"
            echo "  --port PORT   Specify port (default: 3000)"
            exit 1
            ;;
    esac
done

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
if [ "$PROD_MODE" = true ]; then
    echo "Starting frontend in production mode (port: $PORT)..."

    # 检查 build 目录是否存在
    if [ ! -d "${SCRIPT_DIR}/build" ]; then
        echo "Build directory not found. Building production version..."
        npm run build
    fi

    # 使用 serve 启动生产版本（如果没有安装，先安装）
    if ! command -v serve &> /dev/null; then
        echo "Installing serve package..."
        sudo npm install -g serve
    fi

    nohup serve -s build -l $PORT > "${LOG_DIR}/frontend.log" 2>&1 &
    echo $! > "${PID_FILE}"

    echo ""
    echo "Frontend started in production mode. PID: $(cat ${PID_FILE})"
    echo "URL: http://localhost:$PORT"
else
    echo "Starting frontend in development mode..."
    nohup yarn start > "${LOG_DIR}/frontend.log" 2>&1 &
    echo $! > "${PID_FILE}"

    echo ""
    echo "Frontend started in development mode. PID: $(cat ${PID_FILE})"
fi

echo "Log: ${LOG_DIR}/frontend.log"
echo ""
echo "To view logs: tail -f ${LOG_DIR}/frontend.log"
echo "To stop: bash ${SCRIPT_DIR}/stop_frontend.sh"
