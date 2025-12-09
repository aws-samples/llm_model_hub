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

VERSION=0.9.4.cb4cdb4
inference_image=llm-modelhub-llamafactory
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

# Build the docker image locally with the image name and then push it to ECR
# with the full name.

# Add variables for build arguments pytorch-training:2.5.1-gpu-py311-cu124-ubuntu22.04-sagemaker
# https://github.com/aws/deep-learning-containers/blob/master/available_images.md
if [[ $region =~ ^cn ]]; then
    BASE_IMAGE="727897471807.dkr.ecr.${region}.amazonaws.${suffix}/pytorch-training:2.6.0-gpu-py312-cu126-ubuntu22.04-sagemaker"
    PIP_INDEX="https://mirrors.aliyun.com/pypi/simple"
    sed -i '/^RUN pip install "unsloth[cu126-torch260]/d' /home/ubuntu/llm_model_hub/backend/docker/Dockerfile

else
    BASE_IMAGE="763104351884.dkr.ecr.${region}.amazonaws.${suffix}/pytorch-training:2.6.0-gpu-py312-cu126-ubuntu22.04-sagemaker"
    PIP_INDEX="https://pypi.org/simple"
fi


docker build \
    --build-arg BASE_IMAGE="${BASE_IMAGE}" \
    --build-arg PIP_INDEX="${PIP_INDEX}" \
    -t ${inference_image}:latest .

docker tag ${inference_image}:latest ${inference_fullname}

docker push ${inference_fullname}
