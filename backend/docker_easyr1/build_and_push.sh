#!/bin/bash
set -v
set -e

# This script shows how to build the Docker image and push it to ECR to be ready for use
# by SageMaker.

# The argument to this script is the region name. 
# 尝试使用 IMDSv2 获取 token
TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")

# Get the current region and write it to the backend .env file
region=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -s http://169.254.169.254/latest/meta-data/placement/region)
# region=$(aws configure get region)
suffix="com"

if [[ $region =~ ^cn ]]; then
    suffix="com.cn"
fi

# Get the account number associated with the current IAM credentials
account=$(aws sts  get-caller-identity --query Account --output text)

VERSION=0.3.1
BASE_IMAGE=hiyouga/verl:ngc-th2.6.0-cu126-vllm0.8.3-flashinfer0.2.2-cxx11abi0
inference_image=sagemaker/easyr1
inference_fullname=${account}.dkr.ecr.${region}.amazonaws.${suffix}/${inference_image}:${VERSION}

# If the repository doesn't exist in ECR, create it.
aws  ecr describe-repositories --repository-names "${inference_image}" --region ${region} || aws ecr create-repository --repository-name "${inference_image}" --region ${region}

if [ $? -ne 0 ]
then
    aws  ecr create-repository --repository-name "${inference_image}" --region ${region}
fi

# Get the login command from ECR and execute it directly
aws  ecr get-login-password --region $region | docker login --username AWS --password-stdin $account.dkr.ecr.$region.amazonaws.${suffix}

# First, authenticate with AWS ECR
# Run these commands in your terminal before building:

if [[ $region =~ ^cn ]]; then
    aws ecr get-login-password --region $region | docker login --username AWS --password-stdin 727897471807.dkr.ecr.$region.amazonaws.${suffix}
else
    aws ecr get-login-password --region $region | docker login --username AWS --password-stdin 763104351884.dkr.ecr.$region.amazonaws.${suffix}
fi

aws ecr set-repository-policy \
    --repository-name "${inference_image}" \
    --policy-text "file://ecr-policy.json" \
    --region ${region}

# Build the docker image locally with the image name and then push it to ECR
# with the full name.

# Add variables for build arguments pytorch-training:2.5.1-gpu-py311-cu124-ubuntu22.04-sagemaker
# https://github.com/aws/deep-learning-containers/blob/master/available_images.md
if [[ $region =~ ^cn ]]; then
    BASE_IMAGE="727897471807.dkr.ecr.${region}.amazonaws.${suffix}/pytorch-training:2.4.0-gpu-py311"
    PIP_INDEX="https://mirrors.aliyun.com/pypi/simple"

else
    BASE_IMAGE="${BASE_IMAGE}"
    PIP_INDEX="https://pypi.org/simple"
fi


docker build \
    --build-arg BASE_IMAGE="${BASE_IMAGE}" \
    --build-arg PIP_INDEX="${PIP_INDEX}" \
    -t ${inference_image}:${VERSION} .

docker tag ${inference_image}:${VERSION} ${inference_fullname}

docker push ${inference_fullname}
# 删除 .env 文件中的 easyr1_training_image= 这一行
sed -i '/^easyr1_training_image=/d' /home/ubuntu/llm_model_hub/backend/.env
echo "" >> /home/ubuntu/llm_model_hub/backend/.env
echo "easyr1_training_image=${inference_fullname}" >> /home/ubuntu/llm_model_hub/backend/.env