#!/bin/bash
echo "########################注意#####################"
echo "请确认下载代码时用了--recurse-submodule，检查下backend/docker/LLaMA-Factory/文件下是否不为空"
#中国区事先手动下载
#git clone --recurse-submodule https://github.com/aws-samples/llm_model_hub.git
# 设置日志文件
LOG_FILE="/home/ubuntu/setup.log"

touch "$LOG_FILE"
# 函数：记录日志
log() {
echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG_FILE"
}

log "Starting UserData script execution"
sudo apt update
sudo apt install -y git

if ! command -v aws &> /dev/null; then
    #安装awscli
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
    unzip awscliv2.zip
    sudo ./aws/install
fi

#install nodejs 
log "Installing nodejs"
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs
npm config set registry https://registry.npmmirror.com
sudo npm config set registry https://registry.npmmirror.com
sudo npm install --global yarn
yarn config set registry https://registry.npmmirror.com
sudo yarn config set registry https://registry.npmmirror.com

rm /home/ubuntu/llm_model_hub/yarn.lock

# download file
cd /home/ubuntu/
#中国区事先手动下载
#git clone --recurse-submodule https://github.com/aws-samples/llm_model_hub.git
cd /home/ubuntu/llm_model_hub
yarn install
#install pm2
sudo yarn global add pm2

# 等待一段时间以确保实例已完全启动
sleep 30

# 尝试使用 IMDSv2 获取 token
TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")

# Get the EC2 instance's public IP
EC2_IP=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -s http://169.254.169.254/latest/meta-data/public-ipv4)
# Get the current region and write it to the backend .env file
REGION=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -s http://169.254.169.254/latest/meta-data/placement/region)

echo "Get IP:$EC2_IP and Region:$REGION " >> "$LOG_FILE"
# Generate a random string key
RANDOM_KEY=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
# Write the EC2_IP to frontend .env file
rm /home/ubuntu/llm_model_hub/.env
rm /home/ubuntu/llm_model_hub/backend/.env
echo "REACT_APP_API_ENDPOINT=http://$EC2_IP:8000/v1" > /home/ubuntu/llm_model_hub/.env
echo "REACT_APP_API_KEY=$RANDOM_KEY" >> /home/ubuntu/llm_model_hub/.env
echo "REACT_APP_CALCULATOR=https://aws-gpu-memory-caculator.streamlit.app/" >> /home/ubuntu/llm_model_hub/.env

## write sagemaker role
echo "AK=" >> /home/ubuntu/llm_model_hub/backend/.env
echo "SK=" >> /home/ubuntu/llm_model_hub/backend/.env
echo "role=${SageMakerRoleArn}" >> /home/ubuntu/llm_model_hub/backend/.env
echo "region=$REGION" >> /home/ubuntu/llm_model_hub/backend/.env
echo "db_host=127.0.0.1" >> /home/ubuntu/llm_model_hub/backend/.env
echo "db_name=llm" >> /home/ubuntu/llm_model_hub/backend/.env
echo "db_user=llmdata" >> /home/ubuntu/llm_model_hub/backend/.env
echo "db_password=llmdata" >> /home/ubuntu/llm_model_hub/backend/.env
echo "api_keys=$RANDOM_KEY" >> /home/ubuntu/llm_model_hub/backend/.env
echo "HUGGING_FACE_HUB_TOKEN=${HuggingFaceHubToken}" >> /home/ubuntu/llm_model_hub/backend/.env
echo "WANDB_API_KEY=${WANDB_API_KEY}" >> /home/ubuntu/llm_model_hub/backend/.env
echo "WANDB_BASE_URL=${WANDB_BASE_URL}" >> /home/ubuntu/llm_model_hub/backend/.env
echo "SWANLAB_API_KEY=${SWANLAB_API_KEY}" >> /home/ubuntu/llm_model_hub/backend/.env
# Set proper permissions 
sudo chown -R ubuntu:ubuntu /home/ubuntu/
RANDOM_PASSWORD=$(openssl rand -base64 12 | tr -dc 'a-zA-Z0-9' | fold -w 8 | head -n 1) 
aws ssm put-parameter --name "/modelhub/RandomPassword" --value "$RANDOM_PASSWORD" --type "SecureString" --overwrite --region "$REGION"
log "Run CN setup script"
cd /home/ubuntu/llm_model_hub/backend
bash 0.setup-cn.sh
sleep 30
#add user in db
source ../miniconda3/bin/activate py311
conda activate py311
python3 users/add_user.py demo_user $RANDOM_PASSWORD default

#build vllm image
cd /home/ubuntu/llm_model_hub/backend/byoc
bash build_and_push.sh
sleep 5

# 构建llamafactory镜像
log "Building and pushing llamafactory image"
cd /home/ubuntu/llm_model_hub/backend/docker
bash build_and_push.sh || { log "Failed to build and push llamafactory image"; exit 1; }
sleep 5

#upload dummy tar.gz
cd /home/ubuntu/llm_model_hub/backend/byoc
../../miniconda3/envs/py311/bin/python startup.py 

#start backend
cd /home/ubuntu/llm_model_hub/backend/
bash 02.start_backend.sh
sleep 15

#start frontend
cd /home/ubuntu/llm_model_hub/
pm2 start pm2run.config.js 
echo "Webui=http://$EC2_IP:3000" 
echo "username=demo_user"
echo "RandomPassword=$RANDOM_PASSWORD" 
echo "Run User Data Script Done! "
echo "Webui=http://$EC2_IP:3000" >> "$LOG_FILE"
echo "username=demo_user" >> "$LOG_FILE"
echo "RandomPassword=$RANDOM_PASSWORD" >> "$LOG_FILE"
echo "Run User Data Script Done! " >>  "$LOG_FILE"