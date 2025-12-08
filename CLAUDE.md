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
# Activate environment first
source miniconda3/bin/activate py311
conda activate py311

# Start backend services (from backend/ directory)
bash 02.start_backend.sh

# Or manually:
pm2 start server.py --name "modelhub-server" --interpreter ../miniconda3/envs/py311/bin/python3 -- --host 0.0.0.0 --port 8000
pm2 start processing_engine/main.py --name "modelhub-engine" --interpreter ../miniconda3/envs/py311/bin/python3

# Service management
pm2 list           # Check running processes
pm2 restart all    # Restart all services
pm2 logs           # View logs
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
cd backend/
bash 03.upgrade.sh         # One-click upgrade (v1.0.6+)
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
- **FastAPI server** (`server.py`) on port 8000 with Bearer token auth
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
