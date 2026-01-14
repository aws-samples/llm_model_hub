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
# source "${SCRIPT_DIR}/.venv/bin/activate"

# 配置 pip 使用清华镜像源
PIP_INDEX="https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"
uv pip config set global.index-url "$PIP_INDEX"

# 安装 requirements
echo "Installing requirements with uv..."
uv pip install -r requirements.txt --index-url "$PIP_INDEX"

# 设置默认 aws region
sudo apt install awscli -y
aws configure set region cn-northwest-1

# 安装 Docker
sudo apt-get update
sudo apt install git -y && uv pip install -U awscli && uv pip install pyyaml==5.3.1
sudo apt install docker.io -y
# Configure components
sudo systemctl enable docker && sudo systemctl start docker && sudo usermod -aG docker $USER
sudo chmod 666 /var/run/docker.sock

# 添加 Docker 配置
DOCKER_CONFIG="/etc/docker/daemon.json"
sudo mkdir -p /etc/docker
sudo tee "$DOCKER_CONFIG" > /dev/null <<EOT
{
  "registry-mirrors" :
    [
        "https://mirror-docker.bosicloud.com",
        "https://docker.registry.cyou",
        "https://docker-cf.registry.cyou",
        "https://dockerpull.com",
        "https://dockerproxy.cn",
        "https://docker.1panel.live",
        "https://hub.rat.dev",
        "https://docker.anyhub.us.kg",
        "https://docker.chenby.cn",
        "https://dockerhub.icu",
        "https://docker.awsl9527.cn",
        "https://dhub.kubesre.xyz",
        "https://docker.hlyun.org",
        "https://docker.m.daocloud.io"
    ] ,
    "insecure-registries":["mirror-docker.bosicloud.com"]
}
EOT
echo "Docker configuration added to $DOCKER_CONFIG"

# 重启 Docker 服务
sudo systemctl restart docker
echo "Docker service restarted"

# 在 backend 目录下执行以下命令启动 mysql 容器
docker run -d \
  --name hub-mysql \
  -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=1234560 \
  -e MYSQL_DATABASE=llm \
  -e MYSQL_USER=llmdata \
  -e MYSQL_PASSWORD=llmdata \
  -v mysql-data:/var/lib/mysql \
  -v "${SCRIPT_DIR}/scripts:/opt/data" \
  --restart always \
  mysql:8.0

sleep 30

# 创建数据库并导入数据
echo "Creating database and importing data..."
cd "${SCRIPT_DIR}/scripts"
docker exec hub-mysql sh -c "mysql -u root -p1234560 -D llm  < /opt/data/mysql_setup.sql"
sleep 5
docker exec hub-mysql sh -c "mysql -u root -p1234560 -D llm < /opt/data/init_cluster_table.sql"

# 删除 flash-attn，中国区安装超时
sed -i '/^flash_attn==/d' "${SCRIPT_DIR}/docker/requirements_deps.txt"
