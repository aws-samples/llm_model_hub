#!/bin/bash
# Quick benchmark test script with command-line parameters
#
# Usage:
#   ./quick_test.sh <BASE_URL> <API_KEY> <MODEL_NAME> [CONCURRENCY] [REQUESTS]
#
# Example:
#   ./quick_test.sh \
#     "k8s-hyperpod-alb-xxx.elb.amazonaws.com" \
#     "sk-xxxx" \
#     "Qwen3-4B-Instruct-2507" \
#     10 \
#     50

# Check required parameters
if [ $# -lt 3 ]; then
    echo "Error: Missing required parameters"
    echo ""
    echo "Usage: $0 <BASE_URL> <API_KEY> <MODEL_NAME> [CONCURRENCY] [REQUESTS]"
    echo ""
    echo "Parameters:"
    echo "  BASE_URL      - Endpoint base URL (required)"
    echo "  API_KEY       - API authentication key (required)"
    echo "  MODEL_NAME    - Model name (required)"
    echo "  CONCURRENCY   - Number of concurrent requests (optional, default: 10)"
    echo "  REQUESTS      - Total number of requests (optional, default: 50)"
    echo ""
    echo "Example:"
    echo "  $0 'https://k8s-hyperpod-alb-xxx.elb.amazonaws.com' 'sk-xxxx' 'Qwen3-4B-Instruct-2507'"
    echo "  $0 'https://k8s-hyperpod-alb-xxx.elb.amazonaws.com' 'sk-xxxx' 'Qwen3-4B-Instruct-2507' 20 100"
    exit 1
fi

BASE_URL="$1"
API_KEY="$2"
MODEL_NAME="$3"
CONCURRENCY="${4:-10}"  # Default: 10
REQUESTS="${5:-50}"     # Default: 50

echo "Running quick benchmark test..."
echo "Endpoint: $BASE_URL"
echo "Model: $MODEL_NAME"
echo "Concurrency: $CONCURRENCY"
echo "Requests: $REQUESTS"
echo ""

# Use virtual environment python
uv run benchmark_endpoint.py \
  --base-url "$BASE_URL" \
  --api-key "$API_KEY" \
  --model "$MODEL_NAME" \
  --concurrency "$CONCURRENCY" \
  --requests "$REQUESTS" \
  --max-tokens 1024 \
  --show-samples 5   \
  --prompt "Hi, translate to Chinese versions: 
  The Amazon SageMaker HyperPod training operator  helps you accelerate generative AI model development by efficiently managing distributed training across large GPU clusters. It introduces intelligent fault recovery, hang job detection, and process-level management capabilities that minimize training disruptions and reduce costs. Unlike traditional training infrastructure that requires complete job restarts when failures occur, this operator implements surgical process recovery to keep your training jobs running smoothly.
The operator also works with HyperPod's health monitoring and observability functions, providing real-time visibility into training execution and automatic monitoring of critical metrics like loss spikes and throughput degradation. You can define recovery policies through simple YAML configurations without code changes, allowing you to quickly respond to and recover from unrecoverable training states. These monitoring and recovery capabilities work together to maintain optimal training performance while minimizing operational overhead.
The HyperPod Inference Operator extends functionality to provide a deployment method for models on HyperPod using kubectl, HyperPod CLI, SageMaker Studio UI and the SageMaker Python SDK. The service provides advanced autoscaling capabilities with dynamic resource allocation that automatically adjusts based on demand. Additionally, it includes comprehensive observability and monitoring features that track critical metrics such as time-to-first-token, latency, and GPU utilization to help you optimize performance.
Unified infrastructure for training and inference
Maximize your GPU utilization by seamlessly transitioning compute resources between training and inference workloads. This reduces the total cost of ownership while maintaining operational continuity.
Enterprise-ready deployment options
Deploy models from multiple sources including open-weights and gated models from Amazon SageMaker JumpStart and custom models from Amazon S3 and Amazon FSx with support for both single-node and multi-node inference architectures."
