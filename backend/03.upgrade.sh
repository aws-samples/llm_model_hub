#!/bin/bash
git stash
git pull
git submodule update

# Update backend .env file with public ECR images
echo "Updating backend .env with public ECR images"
ENV_FILE="/home/ubuntu/llm_model_hub/backend/.env"

# Remove existing image variables if they exist
sed -i '/^vllm_image=/d' "$ENV_FILE"
sed -i '/^training_image=/d' "$ENV_FILE"
sed -i '/^easyr1_training_image=/d' "$ENV_FILE"
sed -i '/^sglang_image=/d' "$ENV_FILE"

# Append new public ECR image URLs
echo "vllm_image=public.ecr.aws/f8g1z3n8/llm-modelhub-byoc-vllm:latest" >> "$ENV_FILE"
echo "training_image=public.ecr.aws/f8g1z3n8/llm-modelhub-llamafactory:latest" >> "$ENV_FILE"
echo "easyr1_training_image=public.ecr.aws/f8g1z3n8/llm-modelhub-easyr1:latest" >> "$ENV_FILE"
echo "sglang_image=public.ecr.aws/f8g1z3n8/llm-modelhub-byoc-sglang:latest" >> "$ENV_FILE"

cd /home/ubuntu/llm_model_hub/backend/
source ../miniconda3/bin/activate py311
pip install -r requirements.txt
pm2 restart all
echo "upgrade success"