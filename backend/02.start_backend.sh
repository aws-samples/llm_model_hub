#!/bin/bash
source ../miniconda3/bin/activate py311
conda activate py311
cd /home/ubuntu/llm_model_hub/backend/
pm2 start server.py --name "modelhub-server" --interpreter ../miniconda3/envs/py311/bin/python3 -- --host 0.0.0.0 --port 8000
pm2 start processing_engine/main.py --name "modelhub-engine" --interpreter ../miniconda3/envs/py311/bin/python3
pm2 start processing_engine/cluster_processor.py --name "modelhub-cluster" --interpreter ../miniconda3/envs/py311/bin/python3
