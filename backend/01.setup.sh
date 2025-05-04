#!/bin/bash
#安装miniconda
echo "install miniconda...."
wget  https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
chmod +x  Miniconda3-latest-Linux-x86_64.sh
./Miniconda3-latest-Linux-x86_64.sh  -b -f -p ../miniconda3
source  ../miniconda3/bin/activate
conda create -n py311 python=3.11 -y
conda activate py311

# 安装 requirements
# sudo apt install -y python3-numpy
echo "install requirements....."
pip install -r requirements.txt

# 安装Docker
sudo apt-get update
sudo apt install python3-pip git -y && pip3 install -U awscli && pip install pyyaml==5.3.1
sudo apt install docker.io -y
# Configure components
sudo systemctl enable docker && sudo systemctl start docker && sudo usermod -aG docker $USER

sudo chmod 666 /var/run/docker.sock

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

sleep 60

# 创建数据库并导入数据
echo "create database and import data....."
cd scripts 
docker exec hub-mysql sh -c "mysql -u root -p1234560 -D llm  < /opt/data/mysql_setup.sql"