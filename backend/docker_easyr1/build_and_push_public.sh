#!/bin/bash
set -v
set -e

# This script shows how to build the Docker image and push it to AWS Public ECR to be ready for use
# by SageMaker.

# Get the current region
TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
region=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -s http://169.254.169.254/latest/meta-data/placement/region)

suffix="com"

if [[ $region =~ ^cn ]]; then
    suffix="com.cn"
fi

VERSION=0.3.2
# BASE_IMAGE=hiyouga/verl:ngc-th2.8.0-cu12.9-vllm0.11.0
if [[ $region =~ ^cn ]]; then
    # BASE_IMAGE="727897471807.dkr.ecr.${region}.amazonaws.${suffix}/pytorch-training:2.8.0-gpu-py312-cu129-ubuntu22.04-sagemaker"

    BASE_IMAGE="727897471807.dkr.ecr.${region}.amazonaws.${suffix}/pytorch-training:pytorch-training:2.8.0-gpu-py312-cu129-ubuntu22.04-sagemaker"
    PIP_INDEX="https://mirrors.aliyun.com/pypi/simple"
else
    BASE_IMAGE="763104351884.dkr.ecr.${region}.amazonaws.${suffix}/pytorch-training:2.8.0-gpu-py312-cu129-ubuntu22.04-sagemaker"
    PIP_INDEX="https://pypi.org/simple"
fi

inference_image=llm-modelhub-easyr1
public_ecr_uri=public.ecr.aws/f8g1z3n8
inference_fullname=${public_ecr_uri}/${inference_image}:latest

# Login to AWS Public ECR
aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws

# Authenticate with AWS ECR for base images
if [[ $region =~ ^cn ]]; then
    aws ecr get-login-password --region $region | docker login --username AWS --password-stdin 727897471807.dkr.ecr.$region.amazonaws.${suffix}
else
    aws ecr get-login-password --region $region | docker login --username AWS --password-stdin 763104351884.dkr.ecr.$region.amazonaws.${suffix}
fi

# Build the docker image locally with the image name and then push it to Public ECR
# with the full name.

docker build \
    --build-arg BASE_IMAGE="${BASE_IMAGE}" \
    --build-arg PIP_INDEX="${PIP_INDEX}" \
    -t ${inference_image}:latest .

docker tag ${inference_image}:latest ${inference_fullname}

docker push ${inference_fullname}
# 删除 .env 文件中的 easyr1_training_image= 这一行
sed -i '/^easyr1_training_image=/d' /home/ubuntu/llm_model_hub/backend/.env
echo "" >> /home/ubuntu/llm_model_hub/backend/.env
echo "easyr1_training_image=${inference_fullname}" >> /home/ubuntu/llm_model_hub/backend/.env