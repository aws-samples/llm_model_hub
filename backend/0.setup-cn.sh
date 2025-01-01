
# 定义要添加的内容
PIP_INDEX="http://mirrors.aliyun.com/pypi/simple/"

pip config set global.index-url "$PIP_INDEX" &&     pip config set global.extra-index-url "$PIP_INDEX" 

# 删除flash-attn，中国区安装超时
sed -i '/^flash_attn==/d' /home/ubuntu/llm_model_hub/backend/docker/requirements_deps.txt

##设置默认aws region
sudo apt install awscli
aws configure set region cn-northwest-1

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

echo "Script execution completed."