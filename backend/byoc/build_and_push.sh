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

if [[ "$region" == cn*  ]]; then
    suffix="com.cn"
fi

# Get the account number associated with the current IAM credentials
account=$(aws sts  get-caller-identity --query Account --output text)

VLLM_VERSION=v0.6.1.post2
inference_image=sagemaker_endpoint/vllm
inference_fullname=${account}.dkr.ecr.${region}.amazonaws.${suffix}/${inference_image}:${VLLM_VERSION}

# If the repository doesn't exist in ECR, create it.
aws  ecr describe-repositories --repository-names "${inference_image}" --region ${region} || aws ecr create-repository --repository-name "${inference_image}" --region ${region}

if [ $? -ne 0 ]
then
    aws  ecr create-repository --repository-name "${inference_image}" --region ${region}
fi

# Get the login command from ECR and execute it directly
aws  ecr get-login-password --region $region | docker login --username AWS --password-stdin $account.dkr.ecr.$region.amazonaws.${suffix}

aws ecr set-repository-policy \
    --repository-name "${inference_image}" \
    --policy-text "file://ecr-policy.json" \
    --region ${region}

# Build the docker image locally with the image name and then push it to ECR
# with the full name.

docker build  --build-arg VLLM_VERSION=${VLLM_VERSION} -t ${inference_image}:${VLLM_VERSION}  -f Dockerfile . 

docker tag ${inference_image}:${VLLM_VERSION} ${inference_fullname}

docker push ${inference_fullname}

echo "vllm_image=${inference_fullname}" >> /home/ubuntu/llm_model_hub/backend/.env