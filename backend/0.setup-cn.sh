
#!/bin/bash
#安装miniconda
echo "install miniconda...."
wget  https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
chmod +x  Miniconda3-latest-Linux-x86_64.sh
./Miniconda3-latest-Linux-x86_64.sh  -b -f -p ../miniconda3
source  ../miniconda3/bin/activate
conda create -n py311 python=3.11 -y
conda activate py311

# 定义要添加的内容
PIP_INDEX="http://mirrors.aliyun.com/pypi/simple"

pip config set global.index-url "$PIP_INDEX" &&     pip config set global.extra-index-url "$PIP_INDEX" 
# 安装 requirements
echo "install requirements....."
pip install -r requirements.txt

##设置默认aws region
sudo apt install awscli
aws configure set region cn-northwest-1


# 安装Docker
sudo apt-get update
sudo apt install python3-pip git -y && pip3 install -U awscli && pip install pyyaml==5.3.1
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
    ] 
}
EOT
echo "Docker configuration added to $DOCKER_CONFIG"

# 重启 Docker 服务
sudo systemctl restart docker
echo "Docker service restarted"

#在backend目录下执行以下命令启动mysql容器
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

sleep 30

# 创建数据库并导入数据
echo "create database and import data....."
cd scripts 
docker exec hub-mysql sh -c "mysql -u root -p1234560 -D llm  < /opt/data/mysql_setup.sql"

# 删除flash-attn，中国区安装超时
sed -i '/^flash_attn==/d' /home/ubuntu/llm_model_hub/backend/docker/requirements_deps.txt