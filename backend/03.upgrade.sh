#!/bin/bash
rm /home/ubuntu/llm_model_hub/backend/LLaMA-Factory/sg_config*
cd /home/ubuntu/llm_model_hub/backend/LLaMA-Factory/
git stash
cd /home/ubuntu/llm_model_hub/backend/
git pull
git submodule update --remote
source ../miniconda3/bin/activate py311
pip install -r requirements.txt
cd /home/ubuntu/llm_model_hub/backend/byoc/
bash build_and_push.sh 
pm2 restart all
echo "upgrade success"