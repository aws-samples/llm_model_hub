# HyperPod Issues and Solutions

## 1. API Key + Intelligent Routing Returns 401/400

### Issue
Deploying HyperPod endpoint with both **API key authentication** and **intelligent routing** enabled causes:
- Router logs: `401 Unauthorized` when scraping metrics from vLLM backends
- Chat playground: `400 Bad Request` when invoking endpoint

### Root Cause
Two separate issues:

1. **Backend not passing API key to vLLM endpoint:**
   - `invoke_hyperpod_endpoint_stream()` in `server.py` missing `Authorization: Bearer <api_key>` header
   - API key not stored in database `extra_config` during deployment

2. **Router cannot access API key:**
   - Router runs in `hyperpod-inference-system` namespace
   - API key secret created in `default` namespace (Kubernetes secrets are namespace-scoped)
   - Router's `VLLM_API_KEY` env var was empty, causing auth failures when calling `/v1/models`

### Solution

1. **`backend/inference/endpoint_management.py`:**
   - Store API key in `extra_config` when deployment completes

2. **`backend/inference/hyperpod_inference.py`:**
   - Add `api_key` parameter to invoke functions with `Authorization: Bearer` header
   - Add `configure_router_api_key()` function that:
     - Copies API key secret from `default` to `hyperpod-inference-system` namespace
     - Patches router deployment to mount secret and set `VLLM_API_KEY` env var
   - Run router configuration in background thread after deployment

3. **`backend/server.py`:**
   - Extract API key from endpoint's `extra_config` and pass to invoke functions


## 2. KVCacheSpec Error for SGLang Engine

### Issue
Deploying HyperPod endpoint with SGLang engine and KV cache enabled fails with:
```
KVCacheSpec can only be configured for vLLM model server at this moment
```

### Root Cause
KVCacheSpec is only supported by vLLM in the HyperPod inference operator. SGLang doesn't support distributed KV cache.

### Solution
- **`backend/inference/endpoint_management.py`**: Added engine check before enabling KV cache
- **`src/common/i18n.js`**: Updated KV cache description to indicate "Only works with vLLM"

```python
if enable_kv_cache:
    if engine.lower() != 'vllm':
        logger.warning(f"KV cache only supported for vLLM, not {engine}")
    else:
        # Configure KV cache...
```


## 3. Endpoint Name Exceeds 63 Characters

### Issue
Init container name `prefetch-{endpoint_name}-inf` exceeds Kubernetes 63-character limit:
```
prefetch-qwen3-4b-instruct-2507-2026-01-06-04-30-58-238-sgla-inf (64 chars)
```

### Root Cause
Wrong calculation: "prefetch-" is 9 chars + "-inf" is 4 chars = 13 chars overhead, but code used 51 (63-12).

### Solution
**`backend/inference/endpoint_management.py`**: Changed `max_name_len` from 51 to 50.


## 4. Public ALB Requires Intelligent Routing

### Issue
Endpoint shows "InService" but logs show infinite ALB configuration retry:
```
[Background ALB] ALB configuration attempt N failed: Ingress not found
```

### Root Cause
HyperPod operator only creates Ingress (which provisions ALB) when `intelligentRoutingSpec` is configured. Without intelligent routing, no Ingress is created, so ALB configuration loop never completes.

### Solution
1. **Backend** (`endpoint_management.py`): Skip ALB configuration when intelligent routing is disabled
2. **Frontend** (`create-ed.tsx`):
   - Disable Public ALB toggle when Intelligent Routing is off
   - Show info alert explaining the dependency
   - Auto-disable Public ALB if user disables Intelligent Routing
3. **i18n.js**: Added warning messages in English and Chinese


## 5. SGLang Endpoint Readiness Probe Fails (Port Mismatch)

### Issue
SGLang endpoint pod shows `2/3` containers ready, readiness probe fails:
```
Readiness probe failed: Get "http://10.0.11.113:8000/health": connection refused
```
But SGLang logs show server running successfully on port 8080.

### Root Cause
- Code assumed both vLLM and SGLang use port 8000
- vLLM DLC uses port **8000**
- SGLang DLC uses port **8080**
- Readiness probe configured for 8000, but SGLang listens on 8080

### Solution
**`backend/inference/hyperpod_inference.py`**: Set port based on engine type:
```python
# vLLM uses port 8000, SGLang DLC uses port 8080
container_port = 8080 if engine.lower() == "sglang" else 8000
```
Fixed in both `deploy_to_hyperpod()` and `deploy_to_hyperpod_advanced()` functions.


## 6. Readiness Probe Timeout Too Short (1 second)

### Issue
Model pod shows `2/3` containers ready with readiness probe failures:
```
Readiness probe failed: Get "http://10.0.11.253:8080/health": context deadline exceeded (Client.Timeout exceeded while awaiting headers)
```
The model is running fine internally, but the router shows "0 serving engines" and returns "Model not found" errors.

### Root Cause
- HyperPod Inference operator sets a default readiness probe timeout of **1 second**
- SGLang health endpoint response time is approximately **1.007 seconds**
- The 1-second timeout causes consistent probe failures
- Kubernetes marks the pod as "Not Ready", so the router doesn't discover it

### Explanation: What is a Readiness Probe?
A **Readiness Probe** is a Kubernetes health check that determines if a pod is ready to receive traffic:
- **Kubelet** executes the probe periodically (every 10 seconds by default)
- If probe **succeeds**: Pod is added to Service endpoints, traffic is routed to it
- If probe **fails**: Pod is removed from endpoints, no traffic is sent

The HyperPod operator creates deployments with this default probe configuration:
```yaml
readinessProbe:
  httpGet:
    path: /health
    port: 8080
  timeoutSeconds: 1      # Too short!
  periodSeconds: 10
  failureThreshold: 3
```

### Solution
**`backend/inference/hyperpod_inference.py`**:

1. Added `patch_readiness_probe_timeout()` function that patches the deployment after creation to increase the timeout:
```python
def patch_readiness_probe_timeout(
    kubeconfig_path: str,
    endpoint_name: str,
    namespace: str = "default",
    timeout_seconds: int = 5,  # Increased from 1s to 5s
    ...
) -> Dict[str, Any]:
    # Waits for deployment, finds containers with readiness probes,
    # and patches timeoutSeconds to 5
```

2. Called the function in a background thread after deployment in `deploy_to_hyperpod_advanced()`:
```python
# Patch readiness probe timeout in background
import threading
def patch_readiness_background():
    patch_result = patch_readiness_probe_timeout(
        kubeconfig_path=kubeconfig_path,
        endpoint_name=endpoint_name,
        namespace=namespace,
        timeout_seconds=5
    )
    ...

readiness_thread = threading.Thread(target=patch_readiness_background, daemon=True)
readiness_thread.start()
```

This ensures the readiness probe timeout is automatically increased to 5 seconds for all new deployments.


## 7. Model Name Not Recognized by Router (ALB Returns "Model not found")

### Issue
ALB is working (returns responses), but requests fail with:
```json
{"error":"Model Qwen3-4B-Instruct-2507 not found or vLLM engine is sleeping."}
```
The model is running and accessible internally using `/opt/ml/model` as the model name.

### Root Cause
- SGLang/vLLM serve the model using the path where weights are mounted: `/opt/ml/model`
- Users expect to call the model by its friendly name (e.g., `Qwen3-4B-Instruct-2507`)
- The router discovers models by their served name, not by a user-defined alias
- Without `--served-model-name` argument, the engine serves as `/opt/ml/model`

Router logs show:
```
Discovered new serving engine ... running models: ['/opt/ml/model']
```

### Solution
**`backend/inference/hyperpod_inference.py`**:

Override the container command entirely using both `command` and `args` fields. The HyperPod DLC containers have a fixed CMD that ignores additional args, so we must specify the full command:

```python
# Extract a clean served model name for the inference engine
if "/" in model_name:
    served_model_name = model_name.split("/")[-1]
else:
    served_model_name = model_name

# Override container command to include --served-model-name
if engine.lower() == "sglang":
    worker_spec["command"] = ["python3", "-m", "sglang.launch_server"]
    worker_spec["args"] = [
        "--port", str(container_port),
        "--host", "0.0.0.0",
        "--model-path", "/opt/ml/model",
        "--served-model-name", served_model_name
    ]
else:  # vllm
    worker_spec["command"] = ["python3", "-m", "vllm.entrypoints.openai.api_server"]
    worker_spec["args"] = [
        "--port", str(container_port),
        "--host", "0.0.0.0",
        "--model", "/opt/ml/model",
        "--served-model-name", served_model_name
    ]
```

This change was applied to both `deploy_to_hyperpod()` and `deploy_to_hyperpod_advanced()` functions.

### Workaround for Existing Endpoints
For endpoints deployed before this fix, use `/opt/ml/model` as the model name in API calls:
```bash
curl -sk -X POST "https://<alb-url>/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model": "/opt/ml/model", "messages": [{"role": "user", "content": "Hello"}]}'
```


## 8. Playground Returns 400 Bad Request (Model Name Mismatch in API Payload)

### Issue
Playground test fails with `400 Bad Request` even though direct ALB curl works:
```
ERROR:inference.hyperpod_inference:Failed to invoke HyperPod endpoint (streaming): 400 Client Error: Bad Request for url: https://<alb-url>/v1/chat/completions
```

Direct curl with correct model name works fine.

### Root Cause
The backend `server.py` sends the raw model name from the database (`Qwen/Qwen3-4B-Instruct-2507`) in the API payload, but the inference engine serves the model with the short name (`Qwen3-4B-Instruct-2507`) due to the `--served-model-name` argument added in Issue #7.

The payload was built with:
```python
payload = {
    "model": request.model_name or endpoint_info.get('model_name', ''),  # Returns "Qwen/Qwen3-4B-Instruct-2507"
    ...
}
```

But the model is served as `Qwen3-4B-Instruct-2507`, causing the router to return "Model not found" with a 400 error.

### Solution
**`backend/server.py`**: Extract the served model name when building the payload for HyperPod inference:

```python
# Build payload
# For HyperPod endpoints, extract served model name (last part after '/')
# This matches the --served-model-name argument passed to the inference engine
raw_model_name = request.model_name or endpoint_info.get('model_name', '')
if "/" in raw_model_name:
    served_model_name = raw_model_name.split("/")[-1]
else:
    served_model_name = raw_model_name

payload = {
    "model": served_model_name,  # Now uses "Qwen3-4B-Instruct-2507"
    ...
}
```

This ensures consistency between:
1. The model name in the deployment (`--served-model-name Qwen3-4B-Instruct-2507`)
2. The model name in API requests (`"model": "Qwen3-4B-Instruct-2507"`)


## 9. Network Shows "Private" Despite Public ALB Being Configured

### Issue
Endpoint is deployed with public ALB enabled and working, but the frontend shows "Private" in the Network column. The ALB is functional and accessible, but the UI doesn't reflect the correct network status.

### Root Cause
The `extra_config` field (which stores `use_public_alb`, `enable_intelligent_routing`, API key, etc.) is being overwritten to NULL when the `cluster_processor` updates the endpoint status to `INSERVICE`.

The bug is in `database.update_endpoint_status()`:
```python
def update_endpoint_status(self, endpoint_name, endpoint_status, extra_config=None, ...):
    cursor.execute("UPDATE EP_TABLE SET endpoint_status=%s, endpoint_delete_time=%s, extra_config=%s WHERE ...",
                   (endpoint_status.value, endpoint_delete_time, extra_config, endpoint_name))
```

When `cluster_processor` calls `update_endpoint_status(endpoint_name, EndpointStatus.INSERVICE)` without passing `extra_config`, the default `None` value overwrites the existing `extra_config` in the database.

**Timeline:**
1. `deploy_endpoint_hyperpod()` creates endpoint with `extra_config={use_public_alb: true, ...}` and status `CREATING`
2. `cluster_processor` detects the pod is running and calls `update_endpoint_status(name, INSERVICE)`
3. The SQL UPDATE sets `extra_config=NULL` because parameter default is `None`
4. Frontend reads `extra_config` as NULL, assumes `use_public_alb=false`, shows "Private"

### Solution
**`backend/db_management/database.py`**: Modified `update_endpoint_status()` to only update `extra_config` when it's explicitly provided:

```python
def update_endpoint_status(self, endpoint_name, endpoint_status, extra_config=None, endpoint_delete_time=None):
    with self.connection_pool.get_connection() as connection:
        with connection.cursor() as cursor:
            # Only update extra_config if it's explicitly provided (not None)
            # This prevents overwriting existing extra_config when just updating status
            if extra_config is not None:
                cursor.execute("UPDATE EP_TABLE SET endpoint_status=%s, endpoint_delete_time=%s, extra_config=%s WHERE endpoint_name=%s",
                               (endpoint_status.value, endpoint_delete_time, extra_config, endpoint_name))
            else:
                cursor.execute("UPDATE EP_TABLE SET endpoint_status=%s, endpoint_delete_time=%s WHERE endpoint_name=%s",
                               (endpoint_status.value, endpoint_delete_time, endpoint_name))
            connection.commit()
```

### Workaround for Existing Endpoints
Manually update the `extra_config` in the database:
```sql
UPDATE llm.EP_TABLE SET extra_config = '{"hyperpod_cluster_id": "...", "use_public_alb": true, ...}' WHERE endpoint_name = '...';
```


## 10. vLLM/SGLang Parameters Not Passed to HyperPod Deployment

### Issue
Frontend parameters for vLLM/SGLang (like `max-model-len`, `tensor-parallel-size`, `enable-prefix-caching`, `mem-fraction-static`, `chat-template`, `tool-call-parser`) were not being applied to HyperPod deployments.

For example, deploying a model with `max-model-len: 12288` still caused OOM errors because the model tried to use its full context length (e.g., 131072 tokens for Llama 3.2).

### Root Cause
Two issues:

1. **Backend only passed 3 parameters to `deploy_to_hyperpod_advanced()`:**
   ```python
   # endpoint_management.py only passed these:
   tensor_parallel_size=extra_params.get('tensor_parallel_size'),
   max_model_len=extra_params.get('max_model_len'),
   enable_prefix_caching=extra_params.get('enable_prefix_caching', False)
   ```
   Missing: `gpu_memory_utilization`, `chat_template`, `tool_call_parser`

2. **Container args were hardcoded without optional parameters:**
   The `args` list in `hyperpod_inference.py` only included basic parameters:
   ```python
   worker_spec["args"] = [
       "--port", str(container_port),
       "--host", "0.0.0.0",
       "--model", "/opt/ml/model",
       "--served-model-name", served_model_name
   ]
   # Missing: --max-model-len, --tensor-parallel-size, --enable-prefix-caching, etc.
   ```

### Solution

1. **`backend/inference/hyperpod_inference.py`**: Updated `deploy_to_hyperpod_advanced()` to add optional parameters to the container args:

   ```python
   # For vLLM:
   args = ["--port", str(container_port), "--host", "0.0.0.0", ...]
   if tensor_parallel_size:
       args.extend(["--tensor-parallel-size", str(tensor_parallel_size)])
   if max_model_len:
       args.extend(["--max-model-len", str(max_model_len)])
   if enable_prefix_caching:
       args.append("--enable-prefix-caching")
   if gpu_memory_utilization is not None:
       args.extend(["--gpu-memory-utilization", str(gpu_memory_utilization)])
   if chat_template:
       args.extend(["--chat-template", chat_template])
   if tool_call_parser:
       args.extend(["--tool-call-parser", tool_call_parser])

   # For SGLang (uses different parameter names):
   if tensor_parallel_size:
       args.extend(["--tp-size", str(tensor_parallel_size)])
   if max_model_len:
       args.extend(["--context-length", str(max_model_len)])
   if gpu_memory_utilization is not None:
       args.extend(["--mem-fraction-static", str(gpu_memory_utilization)])
   if chat_template:
       args.extend(["--chat-template", chat_template])
   ```

2. **`backend/inference/endpoint_management.py`**: Added missing parameters to the function call:

   ```python
   result = deploy_to_hyperpod_advanced(
       ...
       tensor_parallel_size=extra_params.get('tensor_parallel_size'),
       max_model_len=extra_params.get('max_model_len'),
       enable_prefix_caching=extra_params.get('enable_prefix_caching', False),
       gpu_memory_utilization=extra_params.get('mem_fraction_static'),  # Added
       chat_template=extra_params.get('chat_template'),                 # Added
       tool_call_parser=extra_params.get('tool_call_parser')            # Added
   )
   ```

### Parameter Mapping Reference

| Frontend Field | vLLM Arg | SGLang Arg |
|---------------|----------|------------|
| `max_model_len` | `--max-model-len` | `--context-length` |
| `tensor_parallel_size` | `--tensor-parallel-size` | `--tp-size` |
| `enable_prefix_caching` | `--enable-prefix-caching` | N/A |
| `mem_fraction_static` | `--gpu-memory-utilization` | `--mem-fraction-static` |
| `chat_template` | `--chat-template` | `--chat-template` |
| `tool_call_parser` | `--tool-call-parser` | N/A |

### Additional Frontend Fixes

1. **Default `max_model_len` not sent**: The input field was initialized with empty string and only set `extra_params.max_model_len` on user change. Fixed by:
   - Initialize `value1` with default `'12288'`
   - Add `useEffect` to set default value on component mount

2. **Typo in parameter name**: `tensor_paralle_size` → `tensor_parallel_size`


## 11. Router API Key Configuration Reset by Operator Reconciliation

### Issue
When deploying a HyperPod endpoint with both **API key authentication** and **intelligent routing** enabled, the router shows "0 serving engines" and returns "Model not found" errors. The model pod is running correctly with the API key, but the router cannot authenticate.

Investigation shows the router deployment has an **empty** `VLLM_API_KEY` environment variable:
```yaml
env:
- name: VLLM_API_KEY   # Empty - no value or secretKeyRef
```

Even though our code patches the deployment to add the secretKeyRef, the patch gets overwritten by operator reconciliation.

### Root Cause
The HyperPod Inference Operator copies environment variables from the **worker spec** (in the CRD) to the **router deployment**. However, there's a critical bug/limitation:

**The operator only copies env vars with plain `value`, NOT `valueFrom.secretKeyRef`.**

When we configured the CRD with:
```yaml
environmentVariables:
- name: VLLM_API_KEY
  valueFrom:
    secretKeyRef:
      name: endpoint-api-key
      key: api-key
```

The operator copied the env var name (`VLLM_API_KEY`) to the router but left the value **empty** because it doesn't support `secretKeyRef` propagation.

### Solution
**`backend/inference/hyperpod_inference.py`**: Use plain `value` instead of `secretKeyRef` for the `VLLM_API_KEY` environment variable in the CRD:

```python
# Add API key environment variable if enabled
# NOTE: We use plain value instead of secretKeyRef because the HyperPod operator
# copies env vars from worker to router but doesn't properly copy secretKeyRef.
# Using plain value allows the operator to copy the API key to the router.
if api_key_secret_name and generated_api_key:
    # Use plain value so operator copies it to router
    env_vars.append({
        "name": "VLLM_API_KEY",
        "value": generated_api_key  # Plain value, not secretKeyRef
    })
elif api_key_secret_name:
    # Fallback to secretKeyRef for secrets_manager case (less common)
    env_vars.append({
        "name": "VLLM_API_KEY",
        "valueFrom": {
            "secretKeyRef": {
                "name": api_key_secret_name,
                "key": "api-key"
            }
        }
    })
```

The Kubernetes secret is still created (for reference), but the CRD uses the plain value to ensure the operator copies it to the router.

### Verification
After the fix, the router deployment correctly shows the API key:
```yaml
env:
- name: VLLM_API_KEY
  value: sk-7dc063a19f009218890bedc37c3e335587f3e839f709a0137320f34ae8ee0dde
```

And router logs show successful model discovery:
```
Scraping metrics from 1 serving engine(s)
```

### Workaround for Existing Endpoints
For endpoints deployed before this fix, manually patch the CRD to use plain value:
```bash
kubectl patch inferenceendpointconfig <endpoint-name> --type='merge' \
  -p='{"spec":{"worker":{"environmentVariables":[..., {"name":"VLLM_API_KEY","value":"<your-api-key>"}]}}}'
```

The operator will detect the change and update the router deployment with the correct API key.


## 12. SGLang Backend Removed by vLLM Router After ~1 Minute

### Issue
SGLang endpoint with intelligent routing shows the model running correctly, but router logs show:
```
Scraping metrics from 1 serving engine(s)
```
Then after ~1 minute:
```
Scraping metrics from 0 serving engine(s)
```
The router discovers the SGLang backend but then removes it, causing "Model not found" errors.

### Root Cause
The vLLM router scrapes metrics from backends via the `/metrics` endpoint (Prometheus format). By default, SGLang does **not** expose the `/metrics` endpoint - it returns 404:

```bash
curl http://localhost:8080/metrics
# Returns 404 Not Found
```

The router discovery flow:
1. Router discovers backend via `/v1/models` endpoint ✓
2. Router adds backend to serving pool ✓
3. Router attempts to scrape `/metrics` for load balancing ✗ (404)
4. After repeated failures, router removes "unhealthy" backend ✗

### Solution
**`backend/inference/hyperpod_inference.py`**: Add `--enable-metrics` flag to SGLang container args:

```python
if engine.lower() == "sglang":
    worker_spec["command"] = ["python3", "-m", "sglang.launch_server"]
    worker_spec["args"] = [
        "--port", str(container_port),
        "--host", "0.0.0.0",
        "--model-path", "/opt/ml/model",
        "--served-model-name", served_model_name,
        "--enable-metrics"  # Required for vLLM router to scrape metrics and keep backend registered
    ]
```

Applied to both `deploy_to_hyperpod()` and `deploy_to_hyperpod_advanced()` functions.

### Verification
After the fix, SGLang exposes metrics:
```bash
curl http://localhost:8080/metrics
# Returns Prometheus metrics
```

And router logs consistently show:
```
Scraping metrics from 1 serving engine(s)
```

### Workaround for Existing Endpoints
Redeploy the endpoint with the updated code. There is no way to add the `--enable-metrics` flag to an existing deployment without recreating it.


## 13. Readiness Probe Patch Race Condition (Pod Not Ready, Router Shows 0 Engines)

### Issue
After deploying a HyperPod endpoint, the model container becomes `Ready: False` and the router shows "Scraping metrics from 0 serving engine(s)", causing 400 Bad Request errors in the playground.

Symptoms:
- Deployment shows `timeoutSeconds: 5` (patched correctly)
- Running pod shows `timeout=1s` (old value)
- Pod status: `2/3 Running` (model container not ready)
- Router logs: `Serving engine ... is deleted`

### Root Cause
A race condition occurs between the HyperPod operator creating resources and our background patch:

```
Timeline:
1. InferenceEndpointConfig CRD created
2. HyperPod Operator creates:
   - Deployment (readinessProbe.timeoutSeconds=1, hardcoded by operator)
   - ReplicaSet-A (timeout=1s)
   - Pod-A starts with timeout=1s
3. Background thread patches Deployment (timeout=5s)
4. Kubernetes rolling update creates ReplicaSet-B (timeout=5s)
5. Pod-B created but PENDING (GPU occupied by Pod-A)
6. Pod-A continues running with timeout=1s
7. Pod-A readiness probe times out → Ready=False
8. Router loses backend → 400 errors
```

The patch triggers a Kubernetes rolling update, but:
- New pods can't start because GPU is used by old pods
- Old pods continue with wrong timeout (1s) and eventually fail readiness
- Deadlock: new pods need GPU resources, old pods won't release until replaced

**Note:** The InferenceEndpointConfig CRD does not support configuring readiness probe timeout. The HyperPod operator hardcodes it to 1 second.

### Solution
**`backend/inference/hyperpod_inference.py`**: After patching the deployment, immediately delete existing pods to force the rollout:

```python
def patch_readiness_probe_timeout(...):
    ...
    if patched:
        # Delete existing pods to force rollout with new timeout
        # This is necessary because:
        # 1. New pods can't start (GPU occupied by old pods)
        # 2. Old pods have wrong timeout and will eventually fail readiness
        logger.info(f"[Readiness Patch] Deleting existing pods to force rollout...")
        try:
            pods = core_api.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"app={resource_name}"
            )
            for pod in pods.items:
                logger.info(f"[Readiness Patch] Deleting pod {pod.metadata.name} to force rollout")
                core_api.delete_namespaced_pod(
                    name=pod.metadata.name,
                    namespace=namespace,
                    grace_period_seconds=0  # Force immediate termination
                )
            logger.info(f"[Readiness Patch] Deleted {len(pods.items)} pod(s), new pods will start with timeout={timeout_seconds}s")
        except Exception as e:
            logger.warning(f"[Readiness Patch] Failed to delete pods (rollout may be delayed): {e}")
```

This ensures:
1. Old pods are immediately terminated
2. GPU resources are released
3. New pods with correct timeout=5s can start
4. No race condition, router discovers backend properly

### New Deployment Flow
```
1. CRD created → Operator creates Deployment (timeout=1s)
2. Pod-A starts with timeout=1s
3. Background thread patches Deployment to timeout=5s
4. OLD PODS ARE DELETED IMMEDIATELY (new behavior)
5. New pod starts with correct timeout=5s
6. Router discovers backend, endpoint works
```

### Workaround for Existing Endpoints
If an endpoint is stuck with `Ready: False`, manually trigger a rollout:
```bash
KUBECONFIG=/home/ubuntu/.kube/config-<cluster>-eks kubectl rollout restart deployment <endpoint-name>
```


## 14. HyperPod Missing Default Values for extra_params (Model OOM)

### Issue
Deploying VL (Vision-Language) models like Qwen3-VL to HyperPod fails with OOM error:
```
ValueError: To serve at least one request with the models's max seq len (262144),
28.00 GiB KV cache is needed, which is larger than the available KV cache memory (13.69 GiB).
The estimated maximum model length is 128128.
```

The model container keeps crashing and restarting because vLLM tries to allocate KV cache for the full context length (262144 tokens) which exceeds GPU memory.

### Root Cause
Comparing `deploy_engine()` (SageMaker) vs `deploy_hyperpod_with_hf_download_sync()` (HyperPod):

**SageMaker deployment has defaults:**
```python
"SM_VLLM_MAX_MODEL_LEN": extra_params.get('max_model_len', "12288"),  # ✅ Default 12288
"SM_VLLM_TENSOR_PARALLEL_SIZE": extra_params.get('tensor_parallel_size', str(get_auto_tensor_parallel_size(instance_type))),
"SM_VLLM_MAX_NUM_SEQS": extra_params.get('max_num_seqs', '256'),  # ✅ Default 256
"SM_SGLANG_MEM_FRACTION_STATIC": extra_params.get("mem_fraction_static", "0.8"),  # ✅ Default 0.8
```

**HyperPod deployment had NO defaults:**
```python
max_model_len=extra_params.get('max_model_len'),  # ❌ No default!
gpu_memory_utilization=extra_params.get('mem_fraction_static'),  # ❌ No default!
```

Without `max_model_len`, vLLM uses the model's full context length (262144 for Qwen3-VL), causing OOM on smaller GPUs.

### Solution

**1. `backend/inference/hyperpod_deployment.py`**: Add default values matching SageMaker deployment:

```python
result = deploy_to_hyperpod_advanced(
    ...
    max_model_len=extra_params.get('max_model_len', 12288),  # Default 12288 like SageMaker
    enable_prefix_caching=extra_params.get('enable_prefix_caching', False),
    gpu_memory_utilization=extra_params.get('mem_fraction_static', 0.9),  # Default 0.9
    chat_template=extra_params.get('chat_template'),
    tool_call_parser=extra_params.get('tool_call_parser'),
    # New parameters added:
    limit_mm_per_prompt=extra_params.get('limit_mm_per_prompt'),
    enforce_eager=extra_params.get('enforce_eager', False),
    max_num_seqs=extra_params.get('max_num_seqs')
)
```

**2. `backend/inference/hyperpod_inference.py`**: Add new function parameters:

```python
def deploy_to_hyperpod_advanced(
    ...
    # vLLM-specific parameters (added)
    limit_mm_per_prompt: Optional[str] = None,  # vLLM: --limit-mm-per-prompt
    enforce_eager: bool = False,                 # vLLM: --enforce-eager
    max_num_seqs: Optional[int] = None          # vLLM: --max-num-seqs
) -> Dict[str, Any]:
```

And use them in container args:
```python
if limit_mm_per_prompt:
    args.extend(["--limit-mm-per-prompt", limit_mm_per_prompt])
if enforce_eager:
    args.append("--enforce-eager")
if max_num_seqs:
    args.extend(["--max-num-seqs", str(max_num_seqs)])
```

### Parameter Comparison Table

| Parameter | SageMaker Default | HyperPod Default (Fixed) |
|-----------|-------------------|-------------------------|
| `max_model_len` | 12288 | 12288 |
| `tensor_parallel_size` | auto | auto |
| `max_num_seqs` | 256 | (no default) |
| `mem_fraction_static` | 0.8 | 0.9 |
| `enable_prefix_caching` | false | false |
| `enforce_eager` | false | false |
| `limit_mm_per_prompt` | (no default) | (no default) |
| `chat_template` | (no default) | (no default) |
| `tool_call_parser` | (no default) | (no default) |

### Verification
After the fix, deploying Qwen3-VL-2B shows:
```
non-default args: {..., 'max_model_len': 12288, ...}
```

Instead of the model's full context length (262144).


## 15. Public ALB Ingress Recreation Stuck with 409 Conflict

### Issue
When enabling public ALB for a HyperPod endpoint, the `recreate_ingress_with_scheme()` function gets stuck:
1. Ingress deletion times out after 180 seconds
2. New Ingress creation fails with `409 Conflict: object is being deleted`
3. HyperPod operator recreates the Ingress with original `internal` scheme
4. Endpoint remains with internal ALB despite requesting public ALB

Logs show:
```
Ingress alb-xxx is terminating, waiting... (175s elapsed)
Ingress alb-xxx deletion timed out after 180s, proceeding anyway...
Creating new Ingress alb-xxx with internet-facing scheme...
HTTP response: 409 "object is being deleted: ingresses already exists"
```

### Root Cause
The ALB Ingress Controller uses a **finalizer** (`ingress.k8s.aws/resources`) to ensure AWS resources are cleaned up before the Kubernetes Ingress object is deleted. The cleanup process involves:

1. Deleting the ALB load balancer
2. Deleting listener rules
3. Deleting target groups
4. Deleting security groups

If target group deletion times out (e.g., targets still draining), the finalizer blocks the Ingress deletion indefinitely. Our code times out and tries to create a new Ingress, which fails with 409 because the old one still exists (marked for deletion but not removed due to the finalizer).

### Solution
**`backend/inference/hyperpod_inference.py`**: Modified `recreate_ingress_with_scheme()` to:

1. **Remove the finalizer before deletion** - This allows immediate deletion without waiting for AWS resource cleanup:
```python
if existing_ingress.metadata.finalizers:
    logger.info(f"Removing finalizers from Ingress {ingress_name} to allow immediate deletion...")
    try:
        networking_api.patch_namespaced_ingress(
            name=ingress_name,
            namespace=ingress_namespace,
            body={"metadata": {"finalizers": None}}
        )
        logger.info(f"Finalizers removed from Ingress {ingress_name}")
    except Exception as patch_e:
        logger.warning(f"Failed to remove finalizers: {patch_e}, proceeding with deletion anyway")
```

2. **Add retry logic for 409 conflicts** - In case the Ingress is still terminating:
```python
max_create_retries = 5
create_retry_delay = 5
for create_attempt in range(max_create_retries):
    try:
        logger.info(f"Creating new Ingress... (attempt {create_attempt + 1}/{max_create_retries})")
        networking_api.create_namespaced_ingress(namespace=ingress_namespace, body=new_ingress)
        break
    except ApiException as create_e:
        if create_e.status == 409 and create_attempt < max_create_retries - 1:
            logger.warning(f"409 conflict, retrying in {create_retry_delay}s...")
            time_module.sleep(create_retry_delay)
            create_retry_delay = min(create_retry_delay * 2, 30)  # Exponential backoff
        else:
            raise create_e
```

3. **Reduced wait timeouts** - Since finalizers are removed, deletion is much faster (60s vs 180s)

### Note on AWS Resource Cleanup
By removing the finalizer, we skip the ALB controller's AWS resource cleanup. This is safe because:
- A new ALB with different resources will be created for the new Ingress
- Orphaned AWS resources (old ALB, target groups) will be cleaned up by AWS or manually

### Workaround for Stuck Ingresses
If an Ingress is stuck in `Terminating` state, manually remove the finalizer:
```bash
KUBECONFIG=/home/ubuntu/.kube/config-<cluster>-eks kubectl patch ingress <ingress-name> \
  -n hyperpod-inference-system --type=json \
  -p='[{"op": "remove", "path": "/metadata/finalizers"}]'
```


## 16. Database Shows Internal ALB URL After Public ALB Recreation

### Issue
Endpoint is deployed with public ALB enabled. The public ALB is successfully provisioned and working, but the playground shows an error:
```
Failed to resolve 'internal-k8s-hyperpod-albqwen3-d8ad7ac4de-852231201-1767773231.us-east-1.elb.amazonaws.com'
```

The database contains the **internal** ALB URL despite public ALB being configured and functional.

### Root Cause
A timing issue between the cluster processor and the public ALB recreation:

**Timeline:**
1. HyperPod operator creates deployment with **internal** ALB (default scheme)
2. Model pod becomes Ready, endpoint transitions to `INSERVICE`
3. `cluster_processor.py` detects `INSERVICE` and updates database with current ALB URL (internal)
4. Background thread in `hyperpod_deployment.py` recreates Ingress with **public** (internet-facing) scheme
5. Public ALB is provisioned successfully
6. **Database still has old internal ALB URL** (never updated after step 5)

```python
# cluster_processor.py (line ~1512) - updates DB when endpoint becomes INSERVICE
extra_config['alb_url'] = url_info.get('full_url', '')       # Gets internal ALB
extra_config['endpoint_url'] = url_info.get('endpoint_url', '')
database.update_endpoint_status(endpoint_name, EndpointStatus.INSERVICE, json.dumps(extra_config))
```

The public ALB recreation in `hyperpod_deployment.py` happens **after** the endpoint is already `INSERVICE`, so the database URL is never updated with the correct public ALB hostname.

### Solution
**`backend/inference/hyperpod_deployment.py`**: Update the database with the new public ALB URL after successful ALB configuration:

```python
if alb_result.get('success'):
    alb_hostname = alb_result.get('alb_hostname')
    logger.info(f"[HyperPod Deploy Background] Public ALB configured: {alb_hostname}")
    alb_configured = True

    # Update database with the new public ALB URL
    if alb_hostname:
        try:
            import json as json_module
            extra_config_data['alb_url'] = f"https://{alb_hostname}/v1/chat/completions"
            extra_config_data['endpoint_url'] = alb_hostname
            database.update_endpoint_status(
                endpoint_name=endpoint_name,
                endpoint_status=EndpointStatus.CREATING,  # Keep current status
                extra_config=json_module.dumps(extra_config_data)
            )
            logger.info(f"[HyperPod Deploy Background] Database updated with public ALB URL: {alb_hostname}")
        except Exception as db_e:
            logger.warning(f"[HyperPod Deploy Background] Failed to update database with ALB URL: {db_e}")
    break
```

This ensures the database is updated with the correct public ALB URL regardless of whether the cluster processor already updated it with the internal URL.

### Workaround for Existing Endpoints
Manually update the database with the correct public ALB URL:

1. Get the current public ALB hostname:
```bash
KUBECONFIG=/home/ubuntu/.kube/config-<cluster>-eks kubectl get ingress -n hyperpod-inference-system -o jsonpath='{.items[*].status.loadBalancer.ingress[0].hostname}'
```

2. Update the database:
```sql
UPDATE llm.EP_TABLE
SET extra_config = JSON_SET(
    extra_config,
    '$.alb_url', 'https://<public-alb-hostname>/v1/chat/completions',
    '$.endpoint_url', '<public-alb-hostname>'
)
WHERE endpoint_name = '<endpoint-name>';
```

Or using Python:
```python
import json
# Get current extra_config
extra_config = json.loads(endpoint.extra_config)
extra_config['alb_url'] = f'https://{public_alb_hostname}/v1/chat/completions'
extra_config['endpoint_url'] = public_alb_hostname
database.update_endpoint_status(endpoint_name, EndpointStatus.INSERVICE, json.dumps(extra_config))
```


## 17. KV Cache Enabled Causes "lmcache-config" Volume Mount Error

**Status: ✅ FIXED**

### Issue
Deploying HyperPod endpoint with **KV cache enabled** (L1 or L2 cache) fails with:
```
ERROR: Deployment.apps "endpoint-name" is invalid:
spec.template.spec.containers[0].volumeMounts[2].name: Not found: "lmcache-config"
```

The deployment is never created. Only the router pod runs, but no model pod is scheduled.

### Root Cause
After comparing a working deployment (manual YAML with L2 cache enabled) vs. failing deployments from the backend, the root cause was identified:

**Two configuration issues triggered the operator bug:**

1. **`prefetchEnabled: true`** in `modelSourceConfig`:
   - Working deployment: `prefetchEnabled: false`
   - Failing deployment: `prefetchEnabled: true`

2. **`--enable-prefix-caching`** in container args:
   - Working deployment: No `--enable-prefix-caching` flag
   - Failing deployment: Had `--enable-prefix-caching` in args

The operator handles prefix caching automatically via `kvCacheSpec`. When these additional flags are present, the operator attempts to create an `lmcache-config` volumeMount but fails to define the corresponding volume.

**Working Configuration (demo endpoint):**
```yaml
modelSourceConfig:
  modelSourceType: s3
  s3Storage:
    bucketName: sagemaker-us-east-1-xxx
    region: us-east-1
  modelLocation: path/to/model/
  prefetchEnabled: false  # <-- Must be false
kvCacheSpec:
  enableL1Cache: true
  enableL2Cache: true
  l2CacheSpec:
    l2CacheBackend: tieredstorage
worker:
  args:
    - /opt/ml/model
    - --max-model-len
    - "20000"
    # Note: NO --enable-prefix-caching flag
```

### Solution

**`backend/inference/hyperpod_inference.py`**:

1. **Set `prefetchEnabled: false`** in modelSourceConfig:
```python
model_source_config = {
    "modelSourceType": "s3",
    "s3Storage": {
        "bucketName": s3_bucket,
        "region": region
    },
    "modelLocation": model_location,
    # prefetchEnabled must be False when L2 cache is enabled to avoid lmcache-config volume issue
    "prefetchEnabled": False
}
```

2. **Remove `--enable-prefix-caching`** from vLLM args:
```python
# Note: --enable-prefix-caching is NOT needed for vLLM on HyperPod
# The kvCacheSpec handles prefix caching automatically via the operator
# if enable_prefix_caching:
#     args.append("--enable-prefix-caching")  # REMOVED
```

### Why This Works
- `prefetchEnabled` controls model pre-fetching to RAM before loading to GPU. When `true` with L2 cache, it conflicts with the operator's cache management.
- `--enable-prefix-caching` is a vLLM CLI flag for prefix caching. On HyperPod, the operator handles this via `kvCacheSpec`, so passing it explicitly causes conflicts.

### Frontend Update
**`src/pages/endpoints/create-ed.tsx`**: Re-enabled L2 Cache toggle (was disabled due to this bug):

```typescript
<Toggle
  readOnly={readOnly}
  disabled={data.engine === 'sglang'}  // L2 cache only works with vLLM
  checked={enableL2}
  onChange={({ detail }) => {
    setEnableL2(detail.checked);
    setData((pre: any) => ({
      ...pre,
      hyperpod_config: { ...pre.hyperpod_config, enable_l2_cache: detail.checked }
    }))
  }}
>
  {t("enable_l2_cache")} {data.engine === 'sglang' ? '(vLLM only)' : ''}
</Toggle>
```

### Verification
After the fix, deployment with L2 cache succeeds:
```bash
# Check pod is running
KUBECONFIG=/home/ubuntu/.kube/config-<cluster>-eks kubectl get pods -A | grep <endpoint-name>

# Should show 3/3 Running (model + sidecar + otel) plus router 2/2 Running
```

### Key Learnings
1. When using `kvCacheSpec` for L2 cache, let the operator handle prefix caching configuration
2. `prefetchEnabled` should be `false` when L2 cache is enabled
3. Do NOT add `--enable-prefix-caching` to vLLM args on HyperPod - operator manages this

### Last Updated
- **Fixed**: 2026-01-12
- **Root Cause**: `prefetchEnabled: true` + `--enable-prefix-caching` flag conflict with operator's L2 cache management


## 18. L2 Cache Shared Memory Initialization Failure (tieredstorage backend)

**Status: ⚠️ UNFIXED - Needs Further Investigation**

### Issue
When L2 Cache is enabled with `tieredstorage` backend, LMCache fails to initialize shared memory and logs repeated errors:
```
[LMCache ERROR] Failed to initialize shared memory: [Errno 22] Invalid argument: '/ai_toolkit_cache'
[LMCache ERROR] Failed to initialize SageMaker HyperPod connector: [Errno 22] Invalid argument: '/ai_toolkit_cache'
[LMCache WARNING] Failed to initialize/re-establish remote connection: SageMaker HyperPod connector initialization failed
```

The error repeats every 30 seconds as LMCache retries the connection.

### Impact
- ⚠️ L2 remote cache (tieredstorage) does NOT work
- ✅ L1 local CPU cache still works
- ✅ Inference service works normally (falls back to no remote cache)
- ✅ Endpoint is functional, just without L2 cache optimization

### Observed Configuration
Both endpoints with L2 cache enabled show the same error:

**InferenceEndpointConfig:**
```yaml
kvCacheSpec:
  enableL1Cache: true
  enableL2Cache: true
  l2CacheSpec:
    l2CacheBackend: tieredstorage
```

**LMCache config (from logs):**
```python
{
  'remote_url': 'sagemaker-hyperpod://10.0.11.177:9200',
  'extra_config': {'sagemaker_hyperpod_shared_memory_name': 'ai_toolkit_cache'}
}
```

### Pod Volume Configuration
```yaml
volumes:
- hostPath:
    path: /dev/shm
  name: host-shm

volumeMounts:
- mountPath: /dev/shm/ai_toolkit_cache
  name: host-shm
  subPath: ai_toolkit_cache
```

### Analysis
LMCache expects a **POSIX shared memory segment** at `/ai_toolkit_cache`, but:
1. The pod mounts a **directory** at `/dev/shm/ai_toolkit_cache` via hostPath
2. This is NOT the same as a POSIX shm object accessible via `shm_open("/ai_toolkit_cache")`
3. The `[Errno 22] Invalid argument` suggests the shm segment doesn't exist or can't be created

### Possible Root Causes
1. **Missing shared memory segment on host**: The HyperPod node may need pre-configured POSIX shared memory
2. **Operator bug**: The operator mounts a directory but LMCache expects a shm object
3. **Permission issue**: Container may lack permissions to create POSIX shared memory
4. **Cluster configuration**: tieredstorage backend may require additional cluster-level setup

### Verification Commands
```bash
# Check LMCache errors
KUBECONFIG=/home/ubuntu/.kube/config-<cluster>-eks kubectl logs <pod-name> -c <container-name> | grep -i "lmcache.*error\|shared memory"

# Check pod volume mounts
KUBECONFIG=/home/ubuntu/.kube/config-<cluster>-eks kubectl get pod <pod-name> -o jsonpath='{.spec.containers[0].volumeMounts}' | jq .

# Check if shm exists on host (requires node access)
ls -la /dev/shm/
```

### Workaround
None currently. The endpoint works without L2 cache optimization. To disable L2 cache and avoid the error logs:

```yaml
kvCacheSpec:
  enableL1Cache: true
  enableL2Cache: false  # Disable L2 cache
```

### Next Steps
1. Investigate HyperPod node configuration for POSIX shared memory
2. Check if tieredstorage backend requires additional cluster setup
3. Contact AWS support for guidance on L2 cache configuration
4. Consider testing alternative l2CacheBackend options (redis, etc.)

### Affected Endpoints
- All endpoints with `enableL2Cache: true` and `l2CacheBackend: tieredstorage`
- Tested on cluster: modelhub16-eks

### Last Updated
- **Reported**: 2026-01-12
- **Status**: Needs further investigation - cluster infrastructure issue


## 19. SageMakerEndpointRegistration CR Creation Fails Due to Uppercase endpointName

**Status: ✅ FIXED**

### Issue
HyperPod endpoint deployment fails with operator error:
```
Failed to create new sageMakerEndpointRegistration CR
metadata.name: Invalid value: "Qwen3-4B-Instruct-2507-2026-01-13-01-12": a lowercase RFC 1123 subdomain must consist of lower case alphanumeric characters, '-' or '.', and must start and end with an alphanumeric character
```

The deployment shows:
- Router pod running (2/2)
- Model deployment with 0/0 replicas
- Operator reconciliation loop failing

### Root Cause
The backend code was using lowercase for `metadata.name` (CRD resource name) but NOT for `spec.endpointName`:

```python
resource_name = endpoint_name.lower().replace("_", "-")[:63]  # Lowercase CRD name

spec = {
    "modelName": model_name,
    "endpointName": endpoint_name,  # BUG: Not lowercased!
    ...
}
```

The HyperPod operator uses `spec.endpointName` to create `SageMakerEndpointRegistration` CR, which requires Kubernetes-compliant lowercase names (RFC 1123).

### Solution

**`backend/inference/hyperpod_inference.py`**: Use `resource_name` (already lowercase) for `endpointName` in both functions:

```python
# deploy_to_hyperpod() - line ~1148
spec = {
    "modelName": model_name,
    # endpointName must be lowercase for K8s resource naming (RFC 1123)
    "endpointName": resource_name,
    ...
}

# deploy_to_hyperpod_advanced() - line ~1812
spec = {
    "modelName": model_name,
    # endpointName must be lowercase for K8s resource naming (RFC 1123)
    "endpointName": resource_name,
    ...
}
```

### Verification
After the fix, deploy a new endpoint and check:
```bash
# Check operator logs - no RFC 1123 errors
KUBECONFIG=/home/ubuntu/.kube/config-<cluster>-eks kubectl logs -n hyperpod-inference-system -l app.kubernetes.io/name=hyperpod-inference-operator --tail=100 | grep -i "rfc 1123\|invalid"

# Check model pods are scheduled (not 0/0)
KUBECONFIG=/home/ubuntu/.kube/config-<cluster>-eks kubectl get deployment -A | grep <endpoint-name>
```

### Last Updated
- **Fixed**: 2026-01-13
- **Root Cause**: `spec.endpointName` had uppercase letters, operator uses it for K8s resource names
