#!/bin/bash
set -v
set -e

# This script shows how to build the Docker image and push it to AWS Public ECR to be ready for use
# by SageMaker.

# Get the current region
TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
region=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -s http://169.254.169.254/latest/meta-data/placement/region)

VLLM_VERSION=v0.11.0
inference_image=llm-modelhub-byoc-vllm
public_ecr_uri=public.ecr.aws/f8g1z3n8
inference_fullname=${public_ecr_uri}/${inference_image}:${VLLM_VERSION}

# Login to AWS Public ECR
aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws

# Build the docker image locally with the image name and then push it to Public ECR
# with the full name.

docker build  --build-arg VLLM_VERSION=${VLLM_VERSION} -t ${inference_image}:${VLLM_VERSION}  -f Dockerfile .

docker tag ${inference_image}:${VLLM_VERSION} ${inference_fullname}

docker push ${inference_fullname}
