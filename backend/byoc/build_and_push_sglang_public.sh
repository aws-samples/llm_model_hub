#!/bin/bash
set -v
set -e

# This script shows how to build the Docker image and push it to AWS Public ECR to be ready for use
# by SageMaker.

# Get the current region
TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
region=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -s http://169.254.169.254/latest/meta-data/placement/region)

SGL_VERSION=v0.5.6.post1-cu129-amd64
inference_image=llm-modelhub-byoc-sglang
public_ecr_uri=public.ecr.aws/f8g1z3n8
inference_fullname=${public_ecr_uri}/${inference_image}:${SGL_VERSION}

# Login to AWS Public ECR
aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws

# Build the docker image locally with the image name and then push it to Public ECR
# with the full name.

docker build  --build-arg SGL_VERSION=${SGL_VERSION} -t ${inference_image}:${SGL_VERSION}  -f Dockerfile.sglang .

docker tag ${inference_image}:${SGL_VERSION} ${inference_fullname}

docker push ${inference_fullname}
