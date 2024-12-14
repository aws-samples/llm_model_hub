
# 定义要添加的内容
MIRROR_LINE="-i https://pypi.tuna.tsinghua.edu.cn/simple"

# 处理 backend/requirements.txt
BACKEND_REQ="/home/ubuntu/llm_model_hub/backend/requirements.txt"
if [ -f "$BACKEND_REQ" ]; then
    sed -i "1i$MIRROR_LINE" "$BACKEND_REQ"
    echo "Added mirror line to $BACKEND_REQ"
else
    echo "File $BACKEND_REQ not found"
fi

# 处理 backend/byoc/requirements.txt
BACKEND2_REQ="/home/ubuntu/llm_model_hub/backend/byoc/requirements.txt"
if [ -f "$BACKEND2_REQ" ]; then
    sed -i "1i$MIRROR_LINE" "$BACKEND2_REQ"
    echo "Added mirror line to $BACKEND2_REQ"
    sed -i 's|https://github.com/|https://gitclone.com/github.com/|' "$BACKEND2_REQ"
else
    echo "File $BACKEND2_REQ not found"
fi



# 处理 backend/LLaMA-Factory/requirements.txt
LLAMA_REQ="/home/ubuntu/llm_model_hub/backend/LLaMA-Factory/requirements.txt"
if [ -f "$LLAMA_REQ" ]; then
    sed -i "1i$MIRROR_LINE" "$LLAMA_REQ"
    sed -i 's|https://github.com/|https://gitclone.com/github.com/|' "$LLAMA_REQ"
    echo "Modified $LLAMA_REQ"
else
    echo "File $LLAMA_REQ not found"
fi

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