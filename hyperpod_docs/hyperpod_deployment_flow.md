# HyperPod 推理部署流程详解

本文档详细说明了用户选择 "Deploy to HyperPod Cluster" 时的完整部署流程。

## 目录

1. [前端表单提交](#1-前端表单提交)
2. [API 路由](#2-api-路由)
3. [HyperPod 部署逻辑](#3-hyperpod-部署逻辑)
4. [Kubernetes 资源创建](#4-kubernetes-资源创建)
5. [后台状态监控](#5-后台状态监控)
6. [状态流转图](#6-状态流转图)
7. [数据库记录示例](#7-数据库记录示例)
8. [SageMaker vs HyperPod 对比](#8-sagemaker-vs-hyperpod-对比)

---

## 1. 前端表单提交

**文件位置:** `src/pages/endpoints/create-ed.tsx`

用户在部署表单中:
1. 选择 **Deployment Target** = "HyperPod Cluster"
2. 从下拉框选择一个 **ACTIVE** 状态的 HyperPod 集群
3. 设置 **Replicas** (副本数)
4. 选择模型、实例类型、引擎等

```javascript
// 表单数据结构
const formData = {
  deployment_target: 'hyperpod',
  hyperpod_cluster_id: 'cluster-xxx',
  hyperpod_config: { replicas: 1, namespace: 'default' },
  model_name: 'meta-llama/Llama-3-8B',
  instance_type: 'ml.g5.xlarge',
  engine: 'vllm',
  extra_params: { s3_model_path: 's3://bucket/model' },
  job_id: 'N/A(Not finetuned)'
}
```

---

## 2. API 路由

**文件位置:** `backend/server.py`

**API 端点:** `POST /v1/deploy_endpoint`

```python
@app.post('/v1/deploy_endpoint')
async def handle_deploy_endpoint(request: DeployModelRequest):
    # 检查 deployment_target
    if request.deployment_target == "hyperpod":
        # 验证必须提供 cluster_id
        if not request.hyperpod_cluster_id:
            return error...

        # 调用 HyperPod 部署函数
        ret, msg = deploy_endpoint_hyperpod(
            job_id=request.job_id,
            engine=request.engine,
            instance_type=request.instance_type,
            hyperpod_cluster_id=request.hyperpod_cluster_id,
            hyperpod_config=hyperpod_config,
            extra_params=request.extra_params
        )
    else:
        # SageMaker 部署流程
        ...
```

---

## 3. HyperPod 部署逻辑

**文件位置:** `backend/inference/endpoint_management.py`

```python
def deploy_endpoint_hyperpod(...):
    # 1. 从数据库获取集群信息
    cluster_info = database.get_cluster(hyperpod_cluster_id)
    eks_cluster_name = cluster_info.eks_cluster_name  # 例如: "my-cluster-eks"

    # 2. 确定模型路径 (S3)
    if job_id != 'N/A(Not finetuned)':
        # 微调后的模型
        model_path = jobinfo.output_s3_path + 'finetuned_model_merged/'
    else:
        # S3 上的原始模型
        model_path = extra_params.get("s3_model_path")

    # 3. 生成 endpoint 名称
    endpoint_name = "llama-3-8b-vllm-hp"  # 最多63字符

    # 4. 调用 HyperPod 部署
    result = deploy_to_hyperpod(
        eks_cluster_name=eks_cluster_name,
        endpoint_name=endpoint_name,
        model_s3_path=model_path,
        instance_type=instance_type,
        engine=engine,
        replicas=replicas,
        namespace=namespace
    )

    # 5. 创建数据库记录
    database.create_endpoint(
        endpoint_name=endpoint_name,
        endpoint_status=EndpointStatus.CREATING,
        deployment_target='hyperpod',
        hyperpod_cluster_id=hyperpod_cluster_id,
        extra_config={'eks_cluster_name': eks_cluster_name, 'namespace': namespace}
    )
```

---

## 4. Kubernetes 资源创建

**文件位置:** `backend/inference/hyperpod_inference.py`

```python
def deploy_to_hyperpod(eks_cluster_name, endpoint_name, model_s3_path, ...):
    # 1. 生成 kubeconfig
    kubeconfig_path = get_kubeconfig_for_cluster(eks_cluster_name, region)
    # 执行: aws eks update-kubeconfig --name my-cluster-eks --region us-west-2

    # 2. 获取 Kubernetes 客户端
    custom_api, _ = get_kubernetes_client(kubeconfig_path)

    # 3. 解析 S3 路径
    s3_bucket, model_location = _parse_s3_path(model_s3_path)
    # s3://my-bucket/models/llama -> bucket="my-bucket", location="models/llama"

    # 4. 构建 InferenceEndpointConfig CRD
    body = {
        "apiVersion": "inference.sagemaker.aws.amazon.com/v1",
        "kind": "InferenceEndpointConfig",
        "metadata": {
            "name": "llama-3-8b-vllm-hp",
            "namespace": "default"
        },
        "spec": {
            "modelName": "meta-llama/Llama-3-8B",
            "endpointName": "llama-3-8b-vllm-hp",
            "instanceType": "ml.g5.xlarge",
            "replicas": 1,
            "modelSourceConfig": {
                "modelSourceType": "s3",
                "s3Storage": {
                    "bucketName": "my-bucket",
                    "region": "us-west-2"
                },
                "modelLocation": "models/llama"
            },
            "worker": {
                "image": "763104351884.dkr.ecr.us-west-2.amazonaws.com/djl-inference:...",
                "resources": {
                    "requests": {"nvidia.com/gpu": "1"}
                },
                "environmentVariables": [
                    {"name": "OPTION_ROLLING_BATCH", "value": "vllm"}
                ]
            }
        }
    }

    # 5. 在 Kubernetes 中创建资源
    custom_api.create_namespaced_custom_object(
        group="inference.sagemaker.aws.amazon.com",
        version="v1",
        namespace="default",
        plural="inferenceendpointconfigs",
        body=body
    )
```

### InferenceEndpointConfig CRD 说明

| 字段 | 说明 |
|------|------|
| `modelName` | 模型标识名称 |
| `endpointName` | 端点名称，用于访问 |
| `instanceType` | 实例类型 (ml.g5.xlarge 等) |
| `replicas` | Pod 副本数 |
| `modelSourceConfig` | S3 模型源配置 |
| `worker` | 推理容器配置 |

---

## 5. 后台状态监控

**文件位置:** `backend/processing_engine/cluster_processor.py`

```python
# 主循环每 10 秒扫描一次
while True:
    # ... 其他集群处理 ...

    # 获取所有 CREATING 状态的 HyperPod endpoints
    hyperpod_endpoints = database.get_hyperpod_endpoints_creating()

    for endpoint_name, cluster_id, extra_config in hyperpod_endpoints:
        # 启动线程检查状态
        thread = Thread(target=process_hyperpod_endpoint_status, args=(...))
        thread.start()

    time.sleep(10)

def process_hyperpod_endpoint_status(endpoint_name, cluster_id, extra_config):
    # 1. 获取 EKS 集群名称
    eks_cluster_name = extra_config.get('eks_cluster_name')
    namespace = extra_config.get('namespace', 'default')

    # 2. 查询 Kubernetes 状态
    status, error_msg = get_hyperpod_endpoint_status(
        eks_cluster_name=eks_cluster_name,
        endpoint_name=endpoint_name,
        namespace=namespace
    )

    # 3. 更新数据库状态
    if status == 'INSERVICE':
        database.update_endpoint_status(endpoint_name, EndpointStatus.INSERVICE)
        logger.info(f"HyperPod endpoint {endpoint_name} is now InService")
    elif status == 'FAILED':
        database.update_endpoint_status(endpoint_name, EndpointStatus.FAILED)
        logger.error(f"HyperPod endpoint {endpoint_name} failed: {error_msg}")
    elif status == 'NOTFOUND':
        database.update_endpoint_status(endpoint_name, EndpointStatus.FAILED)
    # status == 'CREATING' 时不做任何操作，等待下一次轮询
```

### 状态判断逻辑

通过查询 Kubernetes CRD 的 `status.conditions` 字段:

```python
def get_hyperpod_endpoint_status(...):
    resource = custom_api.get_namespaced_custom_object(...)
    conditions = resource.get("status", {}).get("conditions", [])

    for condition in conditions:
        if condition.get("type") == "Ready":
            if condition.get("status") == "True":
                return "INSERVICE", None
            elif condition.get("status") == "False":
                return "FAILED", condition.get("message")

    return "CREATING", None  # 还在创建中
```

---

## 6. 状态流转图

```
┌─────────────┐     POST /deploy_endpoint      ┌──────────────────┐
│   Frontend  │ ──────────────────────────────▶│  Backend Server  │
│  (React)    │                                │   (FastAPI)      │
└─────────────┘                                └────────┬─────────┘
                                                        │
                                                        ▼
                                               ┌──────────────────┐
                                               │ endpoint_mgmt.py │
                                               │ deploy_hyperpod()│
                                               └────────┬─────────┘
                                                        │
                    ┌───────────────────────────────────┼───────────────────────────────────┐
                    │                                   │                                   │
                    ▼                                   ▼                                   ▼
           ┌──────────────┐                   ┌──────────────────┐               ┌──────────────┐
           │   Database   │                   │ hyperpod_infer.py│               │  Kubernetes  │
           │  (MySQL)     │                   │ deploy_to_hp()   │──────────────▶│  (EKS)       │
           └──────────────┘                   └──────────────────┘               └──────┬───────┘
                    │                                                                    │
                    │  status=CREATING                                                   │
                    │                                                                    │
                    │                         ┌──────────────────┐                       │
                    │                         │ cluster_processor│                       │
                    │◀────────────────────────│ (Background)     │◀──────────────────────┘
                    │  status=INSERVICE       │ 每10秒轮询        │   查询 CRD 状态
                    │                         └──────────────────┘
```

### 简化时序图

```
User          Frontend         Server          K8s API         Database
 │               │                │                │                │
 │──Deploy──────▶│                │                │                │
 │               │──POST /deploy─▶│                │                │
 │               │                │──Create CRD──▶│                │
 │               │                │                │                │
 │               │                │──────────────────────────────▶│ INSERT (CREATING)
 │               │◀──Success──────│                │                │
 │◀──Notify──────│                │                │                │
 │               │                │                │                │
 │               │                │   [Background Processor]       │
 │               │                │       │                        │
 │               │                │       │──Get Status──▶│        │
 │               │                │       │◀──Ready=True──│        │
 │               │                │       │────────────────────────▶│ UPDATE (INSERVICE)
 │               │                │                │                │
```

---

## 7. 数据库记录示例

### EP_TABLE 表结构 (新增字段)

```sql
-- 新增的 HyperPod 相关字段
ALTER TABLE EP_TABLE ADD COLUMN deployment_target VARCHAR(20) DEFAULT 'sagemaker';
ALTER TABLE EP_TABLE ADD COLUMN hyperpod_cluster_id VARCHAR(64) DEFAULT NULL;
```

### 查询示例

```sql
-- 查询所有 HyperPod 端点
SELECT
    endpoint_name,
    model_name,
    engine,
    instance_type,
    endpoint_status,
    deployment_target,
    hyperpod_cluster_id,
    extra_config
FROM EP_TABLE
WHERE deployment_target = 'hyperpod';
```

### 示例数据

| endpoint_name | model_name | engine | instance_type | endpoint_status | deployment_target | hyperpod_cluster_id |
|---------------|------------|--------|---------------|-----------------|-------------------|---------------------|
| llama-3-8b-vllm-hp | meta-llama/Llama-3-8B | vllm | ml.g5.xlarge | INSERVICE | hyperpod | cluster-abc-123 |
| qwen-7b-sglang-hp | Qwen/Qwen-7B | sglang | ml.g5.2xlarge | CREATING | hyperpod | cluster-abc-123 |

### extra_config 字段内容

```json
{
    "hyperpod_cluster_id": "cluster-abc-123",
    "eks_cluster_name": "my-cluster-eks",
    "namespace": "default",
    "replicas": 2
}
```

---

## 8. SageMaker vs HyperPod 对比

| 方面 | SageMaker Endpoint | HyperPod Cluster |
|------|-------------------|------------------|
| **部署方式** | SageMaker API (`create_endpoint`) | Kubernetes CRD (`InferenceEndpointConfig`) |
| **状态检查** | `describe_endpoint()` API | Kubernetes API 查询 CRD status |
| **资源管理** | AWS 完全托管 | 用户管理的 EKS 集群 |
| **扩缩容** | SageMaker Auto Scaling | Kubernetes Replicas / HPA |
| **网络访问** | SageMaker Endpoint URL | Kubernetes Service / Ingress |
| **成本模式** | 按端点实例时间计费 | 按 EC2 实例计费 (更灵活) |
| **适用场景** | 快速部署、无需管理基础设施 | 需要更多控制、多租户、成本优化 |
| **GPU 共享** | 不支持 | 支持 (通过 HyperPod) |
| **KV Cache** | 不支持 | 支持 (L1/L2 缓存) |
| **智能路由** | 不支持 | 支持 (prefix-aware, session-based) |

---

## 相关文件列表

| 文件路径 | 说明 |
|----------|------|
| `src/pages/endpoints/create-ed.tsx` | 前端部署表单 |
| `backend/server.py` | API 路由入口 |
| `backend/model/data_model.py` | 数据模型定义 |
| `backend/inference/endpoint_management.py` | 端点管理逻辑 |
| `backend/inference/hyperpod_inference.py` | HyperPod 推理部署实现 |
| `backend/db_management/database.py` | 数据库操作 |
| `backend/processing_engine/cluster_processor.py` | 后台状态监控 |
| `backend/scripts/mysql_setup.sql` | 数据库表结构 |
