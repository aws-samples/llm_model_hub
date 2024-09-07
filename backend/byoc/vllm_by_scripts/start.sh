#!/bin/bash

# port needs to be 8080

python3 -m vllm.entrypoints.openai.api_server \
    --port 8080 \
    --trust-remote-code \
    --model deepseek-ai/deepseek-coder-1.3b-instruct