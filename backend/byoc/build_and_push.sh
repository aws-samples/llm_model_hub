#!/bin/bash
set -v
set -e

# This script pulls the image from AWS Public ECR and copies it to private ECR for use by SageMaker.
# SageMaker does not support Public ECR directly, so we need to copy to private ECR.

# Get the current region
TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
region=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -s http://169.254.169.254/latest/meta-data/placement/region)

suffix="com"

if [[ $region =~ ^cn ]]; then
    suffix="com.cn"
fi

# Get the account number associated with the current IAM credentials
account=$(aws sts  get-caller-identity --query Account --output text)
partition=$(aws sts get-caller-identity --query 'Arn' --output text | cut -d: -f2)

VLLM_VERSION=v0.11.0
# Public ECR image
public_ecr_image=public.ecr.aws/f8g1z3n8/llm-modelhub-byoc-vllm:${VLLM_VERSION}

# Private ECR configuration
inference_image=sagemaker_endpoint/vllm
inference_fullname=${account}.dkr.ecr.${region}.amazonaws.${suffix}/${inference_image}:${VLLM_VERSION}

# If the repository doesn't exist in ECR, create it.
aws  ecr describe-repositories --repository-names "${inference_image}" --region ${region} || aws ecr create-repository --repository-name "${inference_image}" --region ${region}

if [ $? -ne 0 ]
then
    aws  ecr create-repository --repository-name "${inference_image}" --region ${region}
fi

# Login to AWS Public ECR
aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws

# Login to private ECR
aws  ecr get-login-password --region $region | docker login --username AWS --password-stdin $account.dkr.ecr.$region.amazonaws.${suffix}

# Substitute the AWS account ID into the ECR policy
sed "s/\${AWS_ACCOUNT_ID}/${account}/g" ecr-policy.json > ecr-policy-temp.json
sed -i "s/\${AWS_PARTITION}/${partition}/g" ecr-policy-temp.json
#print file content of ecr-policy-temp
cat ecr-policy-temp.json

aws ecr set-repository-policy \
    --repository-name "${inference_image}" \
    --policy-text "file://ecr-policy-temp.json" \
    --region ${region}

# Clean up temporary policy file
rm -f ecr-policy-temp.json

# Pull image from Public ECR
docker pull ${public_ecr_image}

# Tag the image for private ECR
docker tag ${public_ecr_image} ${inference_fullname}

# Push to private ECR
docker push ${inference_fullname}
echo ${inference_fullname}
# 删除 .env 文件中的 vllm_image= 这一行
sed -i '/^vllm_image=/d' /home/ubuntu/llm_model_hub/backend/.env
echo "" >> /home/ubuntu/llm_model_hub/backend/.env
echo "vllm_image=${inference_fullname}" >> /home/ubuntu/llm_model_hub/backend/.env