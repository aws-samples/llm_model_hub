
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

# 处理 .gitmodules
# gitmoddules_REQ="/home/ubuntu/llm_model_hub/.gitmodules"
# if [ -f "$gitmoddules_REQ" ]; then
#     sed -i "1i$MIRROR_LINE" "$gitmoddules_REQ"
#     sed -i 's|https://github.com/|https://gitclone.com/github.com/|' "$gitmoddules_REQ"
#     echo "Modified $gitmoddules_REQ"
# else
#     echo "File $gitmoddules_REQ not found"
# fi

# 添加 Docker 配置
DOCKER_CONFIG="/etc/docker/daemon.json"
sudo mkdir -p /etc/docker
sudo tee "$DOCKER_CONFIG" > /dev/null <<EOT
{ 
  "registry-mirrors" : 
    [ 
        "https://docker.m.daocloud.io",
        "https://dockerproxy.com",
        "https://docker.nju.edu.cn",
        "https://docker.mirrors.ustc.edu.cn"
    ] 
}
EOT
echo "Docker configuration added to $DOCKER_CONFIG"

# 重启 Docker 服务
sudo systemctl restart docker
echo "Docker service restarted"

echo "Script execution completed."