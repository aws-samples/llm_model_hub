# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Model Hub V2 is a no-code visual platform for LLM model fine-tuning, deployment, and debugging. It enables users to quickly experiment with fine-tuning various open-source models on AWS SageMaker.

## Commands

### Frontend (React)
```bash
npm start          # Start development server (port 3000)
npm run build      # Production build
npm test           # Run tests
```

### Backend (Python/FastAPI)
```bash
# Activate environment first (from backend/ directory)
cd backend
source .venv/bin/activate

# Start backend services
bash 02.start_backend.sh

# Or manually:
pm2 start server.py --name "modelhub-server" --interpreter .venv/bin/python3 -- --host 0.0.0.0 --port 8000
pm2 start processing_engine/main.py --name "modelhub-engine" --interpreter .venv/bin/python3

# Service management
pm2 list           # Check running processes
pm2 restart all    # Restart all services
pm2 logs           # View logs

# Install dependencies with uv
uv pip install -r requirements.txt
```

### User Management
```bash
cd backend/
python3 users/add_user.py <username> <password> default
python3 users/delete_user.py <username>
```

### Docker/BYOC Image
```bash
cd backend/byoc
bash build_and_push.sh     # Build and push inference image
python3 startup.py         # Initialize BYOC setup
```

### Upgrade
```bash
bash upgrade.sh            # One-click upgrade (v1.0.6+)
```

## Architecture

### Frontend (`src/`)
- **React 18 + TypeScript** with Cloudscape Design System (AWS UI components)
- Entry: `src/App.tsx` - Main router with protected routes
- **Pages:**
  - `/login` - Authentication
  - `/jobs` - Training job management (list, create, detail views)
  - `/endpoints` - SageMaker endpoint management
  - `/chat` - Chat interface for deployed models
- **Shared:** `src/pages/commons/` - Auth hooks, navigation, reusable components

### Backend (`backend/`)
- **FastAPI server** (`server.py`) on port 8000 with Bearer token auth (Python 3.12, managed by uv)
- **Processing engine** (`processing_engine/main.py`) - Background job management
- **Key modules:**
  - `training/` - SageMaker training job orchestration
  - `inference/` - Endpoint deployment (vLLM, SGLang, LMI engines) and serving
  - `users/` - User authentication
  - `model/data_model.py` - Pydantic models for API requests/responses
  - `utils/` - AWS config, S3 operations, LlamaFactory integration
- **Database:** MySQL via Docker (`hub-mysql` container)
- **Docker images:**
  - `docker/LLaMA-Factory/` - Training container (git submodule)
  - `docker_easyr1/EasyR1/` - R1 training (git submodule)
  - `byoc/` - Inference container builds

### API Flow
1. Frontend calls `/v1/*` endpoints with API key auth
2. Backend proxied via `package.json` proxy to localhost:8000
3. Training jobs submitted to SageMaker via `training/jobs.py`
4. Inference endpoints deployed as SageMaker endpoints via `inference/endpoint_management.py`

### Environment Configuration
- Frontend: `.env` (root) - `REACT_APP_API_ENDPOINT`
- Backend: `backend/.env` - AWS credentials, SageMaker role ARN, DB config, API keys

## Job Types
Training supports: `sft`, `pt`, `ppo`, `dpo`, `kto`, `rm`, `grpo`, `dapo`, `gspo`, `cispo`

## Inference Engines
- `vllm` / `sglang` - BYOC (Bring Your Own Container) deployment
- `auto` - Auto-select engine
- Others - LMI (Large Model Inference) deployment

## SageMaker DLC Environment Variables (IMPORTANT)

**AWS SageMaker vLLM/SGLang DLCs use specific environment variable prefixes.** Generic env vars like `HF_MODEL_ID` will be IGNORED.

### vLLM SageMaker DLC
Uses `SM_VLLM_*` prefix. Entry point: `sagemaker_entrypoint.sh`
- Reference: https://github.com/aws/deep-learning-containers/blob/master/vllm/build_artifacts/sagemaker_entrypoint.sh

| Env Var | CLI Arg |
|---------|---------|
| `SM_VLLM_MODEL` | `--model` |
| `SM_VLLM_SERVED_MODEL_NAME` | `--served-model-name` |
| `SM_VLLM_DTYPE` | `--dtype` |
| `SM_VLLM_MAX_MODEL_LEN` | `--max-model-len` |
| `SM_VLLM_TENSOR_PARALLEL_SIZE` | `--tensor-parallel-size` |
| `SM_VLLM_MAX_NUM_SEQS` | `--max-num-seqs` |
| `SM_VLLM_ENABLE_PREFIX_CACHING` | `--enable-prefix-caching` (flag) |
| `SM_VLLM_ENFORCE_EAGER` | `--enforce-eager` (flag) |

### SGLang SageMaker DLC
Uses `SM_SGLANG_*` prefix. Entry point: `sagemaker_entrypoint.sh`
- Reference: https://github.com/aws/deep-learning-containers/blob/master/sglang/build_artifacts/sagemaker_entrypoint.sh
- Default model-path is `/opt/ml/model` if not set

| Env Var | CLI Arg |
|---------|---------|
| `SM_SGLANG_MODEL_PATH` | `--model-path` |
| `SM_SGLANG_SERVED_MODEL_NAME` | `--served-model-name` |
| `SM_SGLANG_TP_SIZE` | `--tp-size` |
| `SM_SGLANG_MEM_FRACTION_STATIC` | `--mem-fraction-static` |
| `SM_SGLANG_CONTEXT_LENGTH` | `--context-length` |

### S3 Model Loading
When deploying finetuned models from S3:
1. Use `model_data` with `S3DataSource` dict (not plain S3 path)
2. SageMaker downloads S3 files to `/opt/ml/model`
3. Set `SM_VLLM_MODEL=/opt/ml/model` or let SGLang use default

```python
model_data_config = {
    "S3DataSource": {
        "S3Uri": "s3://bucket/path/to/model/",
        "S3DataType": "S3Prefix",
        "CompressionType": "None"
    }
}
```

## HyperPod Inference (EKS-based Deployment)

### Overview
HyperPod inference deploys models to Amazon EKS clusters using the HyperPod Inference Operator. Key files:
- `backend/inference/hyperpod_inference.py` - Core deployment logic
- `backend/inference/endpoint_management.py` - Endpoint lifecycle management

### Kubeconfig Files
Located at `~/.kube/config-<cluster-name>-eks`, e.g.:
```bash
export KUBECONFIG=/home/ubuntu/.kube/config-modelhub14-eks
```

### Debugging Commands
```bash
# Check pods status
KUBECONFIG=/home/ubuntu/.kube/config-modelhub14-eks kubectl get pods -A

# Check specific endpoint pod
KUBECONFIG=/home/ubuntu/.kube/config-modelhub14-eks kubectl describe pod <pod-name>

# View model container logs
KUBECONFIG=/home/ubuntu/.kube/config-modelhub14-eks kubectl logs <pod-name> -c model

# View router logs (for intelligent routing)
KUBECONFIG=/home/ubuntu/.kube/config-modelhub14-eks kubectl logs -n hyperpod-inference-system -l app=router

# Check ingress/ALB status
KUBECONFIG=/home/ubuntu/.kube/config-modelhub14-eks kubectl get ingress

# Test ALB connectivity
curl -X POST "http://<alb-url>/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model": "<model-name>", "messages": [{"role": "user", "content": "Hello"}]}'
```

### Key Features
- **Intelligent Routing**: Load balances across multiple model replicas via vLLM router
- **Public ALB**: Exposes endpoint via AWS Application Load Balancer (requires intelligent routing)
- **API Key Auth**: Optional authentication for vLLM endpoints
- **KV Cache**: Distributed KV cache support (vLLM only)

### Port Configuration
- vLLM DLC: port **8000**
- SGLang DLC: port **8080**

## Known Issues & Solutions
See `hyperpod_docs/ISSUES_FIXED.md` for documented issues and fixes:
1. API Key + Intelligent Routing 401/400 errors
2. KVCacheSpec error for SGLang engine
3. Endpoint name exceeds 63 characters
4. Public ALB requires intelligent routing
5. SGLang port mismatch (8000 vs 8080)
6. Readiness probe timeout too short (1 second)
7. Model name not recognized by router (missing --served-model-name)
8. Playground 400 error (model name mismatch in API payload)
9. Network shows "Private" despite public ALB (extra_config overwritten)

## Database Access
```bash
# Access MySQL CLI
docker exec -it hub-mysql mysql -ullmdata -pllmdata

# Query examples
use llm;
show tables;
select * from USER_TABLE;
select * from ENDPOINT_TABLE;
```

## Testing Endpoints
```bash
# Via backend API
curl -s -X POST "http://localhost:8000/v1/chat" \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"endpoint_name": "<name>", "messages": [{"role": "user", "content": "Hello"}]}'

# Direct to SageMaker endpoint
aws sagemaker-runtime invoke-endpoint \
  --endpoint-name <endpoint-name> \
  --body '{"messages": [...]}' \
  --content-type application/json \
  output.json
```
