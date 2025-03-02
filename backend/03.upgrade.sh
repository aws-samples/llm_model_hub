#!/bin/bash
git stash
git pull
git submodule update 
cd /home/ubuntu/llm_model_hub/backend/docker/
sh build_and_push.sh
cd /home/ubuntu/llm_model_hub/backend/
source ../miniconda3/bin/activate py311
pip install -r requirements.txt
cd /home/ubuntu/llm_model_hub/backend/byoc/
bash build_and_push.sh 
bash build_and_push_sglang.sh 
pm2 restart all
echo "upgrade success"