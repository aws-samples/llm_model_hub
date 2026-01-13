#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${SCRIPT_DIR}/backend"

cd "${SCRIPT_DIR}"

git stash
git pull
git submodule update

cd "${BACKEND_DIR}/docker/"
bash build_and_push.sh

cd "${BACKEND_DIR}/docker_easyr1/"
bash build_and_push.sh

cd "${BACKEND_DIR}"
uv sync

cd "${BACKEND_DIR}/byoc/"
bash build_and_push.sh
bash build_and_push_sglang.sh

cd "${SCRIPT_DIR}"
bash restart_all.sh
echo "upgrade success"
