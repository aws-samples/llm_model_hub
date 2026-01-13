#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 安装 uv
echo "Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh

# 添加 uv 到 PATH
export PATH="$HOME/.local/bin:$PATH"

# 创建 Python 3.12 虚拟环境
echo "Creating Python 3.12 virtual environment with uv..."
uv venv --python 3.12 "${SCRIPT_DIR}/.venv"

# 激活虚拟环境
# source .venv/bin/activate

# 安装依赖 (使用 pyproject.toml)
echo "Installing dependencies with uv..."
uv sync

# 安装 Docker
sudo apt-get update
sudo apt install  git -y && uv pip install -U awscli && uv pip install pyyaml==5.3.1
sudo apt install docker.io -y
# Configure components
sudo systemctl enable docker && sudo systemctl start docker && sudo usermod -aG docker $USER

sudo chmod 666 /var/run/docker.sock

# 在 backend 目录下执行以下命令启动 mysql 容器
docker run -d \
  --name hub-mysql \
  -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=1234560 \
  -e MYSQL_DATABASE=llm \
  -e MYSQL_USER=llmdata \
  -e MYSQL_PASSWORD=llmdata \
  -v mysql-data:/var/lib/mysql \
  -v $(pwd)/scripts:/opt/data \
  --restart always \
  mysql:8.0

sleep 60

# 创建数据库并导入数据
echo "Creating database and importing data..."
cd scripts
docker exec hub-mysql sh -c "mysql -u root -p1234560 -D llm  < /opt/data/mysql_setup.sql"
sleep 5
docker exec hub-mysql sh -c "mysql -u root -p1234560 -D llm < /opt/data/init_cluster_table.sql"
