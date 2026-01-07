#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="${SCRIPT_DIR}/.venv/bin/python3"

# 激活虚拟环境
source "${SCRIPT_DIR}/.venv/bin/activate"

cd "${SCRIPT_DIR}"
pm2 start server.py --name "modelhub-server" --interpreter "${VENV_PYTHON}" -- --host 0.0.0.0 --port 8000
pm2 start processing_engine/main.py --name "modelhub-engine" --interpreter "${VENV_PYTHON}"
pm2 start processing_engine/cluster_processor.py --name "modelhub-cluster" --interpreter "${VENV_PYTHON}"

