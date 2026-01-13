#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}/.."

git stash
git pull
git submodule update

cd "${SCRIPT_DIR}/docker/"
bash build_and_push.sh

cd "${SCRIPT_DIR}/docker_easyr1/"
bash build_and_push.sh

cd "${SCRIPT_DIR}"
uv sync

cd "${SCRIPT_DIR}/byoc/"
bash build_and_push.sh
bash build_and_push_sglang.sh

pm2 restart all
echo "upgrade success"
