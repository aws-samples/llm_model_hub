# HyperPod EKS 模型推理部署指南

本文档详细介绍如何在 Amazon SageMaker HyperPod EKS 集群上部署和管理机器学习模型推理。

## 目录

1. [概述](#概述)
2. [架构](#架构)
3. [前提条件](#前提条件)
4. [安装推理操作符](#安装推理操作符)
5. [部署 JumpStart 模型](#部署-jumpstart-模型)
6. [部署自定义模型](#部署自定义模型)
7. [自动扩缩容配置](#自动扩缩容配置)
8. [KV 缓存和智能路由](#kv-缓存和智能路由)
9. [监控和可观测性](#监控和可观测性)
10. [故障排除](#故障排除)

---

## 概述

Amazon SageMaker HyperPod 提供了一个综合的推理平台，结合了 Kubernetes 的灵活性和 AWS 托管服务的运维能力。

### 核心功能

- **多种部署接口**: kubectl、Python SDK、SageMaker Studio UI、HyperPod CLI
- **高级自动扩缩容**: 基于 CloudWatch、Prometheus 和 KEDA 的动态资源分配
- **GPU 分区**: Multi-Instance GPU (MIG) 技术提高 GPU 利用率
- **统一基础设施**: 训练和推理使用相同的 HyperPod 计算资源
- **KV 缓存**: 分层缓存和智能路由优化 LLM 推理性能
- **企业级部署**: 支持 JumpStart 模型和自定义模型 (S3/FSx)

### 模型来源

| 来源 | 描述 | 部署方式 |
|------|------|----------|
| SageMaker JumpStart | 预训练的基础模型 | Studio UI、kubectl、SDK、CLI |
| Amazon S3 | 自定义/微调模型 | kubectl、SDK、CLI |
| Amazon FSx | 高性能文件系统模型 | kubectl、SDK、CLI |

---

## 架构

### HyperPod 推理操作符

推理操作符 (Inference Operator) 是一个 Kubernetes 操作符，负责：

1. 识别合适的实例类型
2. 下载模型文件
3. 配置 Application Load Balancer (ALB)
4. 生成 TLS 证书
5. 注册 SageMaker 端点

### 架构图

```
+-------------------------------------------------------------+
|                    HyperPod EKS 集群                         |
+-------------------------------------------------------------+
|  +-------------------+    +-------------------+              |
|  | 推理操作符         |    | 模型 Pod          |              |
|  | Inference         |--->| (vLLM/TGI/DJL)    |              |
|  | Operator          |    |                   |              |
|  +-------------------+    +-------------------+              |
|           |                        |                         |
|           v                        v                         |
|  +-------------------+    +-------------------+              |
|  | AWS 负载均衡器     |    | SageMaker         |              |
|  | Load Balancer     |    | 端点              |              |
|  +-------------------+    +-------------------+              |
|           |                        |                         |
|           v                        v                         |
|  +---------------------------------------------+            |
|  |           模型存储 (S3/FSx)                  |            |
|  +---------------------------------------------+            |
+-------------------------------------------------------------+
```

---

## 前提条件

### 基本要求

1. 已创建的 HyperPod EKS 集群
2. 具有集群管理员权限的 IAM 主体
3. 已安装 kubectl、helm、eksctl、jq 工具
4. AWS CLI 已配置

### 环境变量设置

```bash
# 设置基本环境变量
export HYPERPOD_CLUSTER_NAME=<hyperpod-cluster-name>
export REGION=<region>
export BUCKET_NAME=<your-s3-bucket-name>

# 获取 EKS 集群名称
export EKS_CLUSTER_NAME=$(aws --region $REGION sagemaker describe-cluster \
    --cluster-name $HYPERPOD_CLUSTER_NAME \
    --query 'Orchestrator.Eks.ClusterArn' --output text | cut -d'/' -f2)

# 配置 kubectl
aws eks update-kubeconfig --name $EKS_CLUSTER_NAME --region $REGION

# 验证连接
kubectl get pods --all-namespaces
```

### 获取账户信息

```bash
export ACCOUNT_ID=$(aws sts get-caller-identity --query 'Account' --output text)
export OIDC_ID=$(aws eks describe-cluster --name $EKS_CLUSTER_NAME \
    --query "cluster.identity.oidc.issuer" --output text | cut -d '/' -f 5)
```

---

## 安装推理操作符

### 步骤 1: 关联 OIDC 提供商

```bash
eksctl utils associate-iam-oidc-provider \
    --region=$REGION \
    --cluster=$EKS_CLUSTER_NAME \
    --approve
```

### 步骤 2: 创建推理操作符 IAM 角色

```bash
# 创建信任策略
cat << 'EOF' > trust-policy.json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": ["sagemaker.amazonaws.com"]
            },
            "Action": "sts:AssumeRole"
        },
        {
            "Effect": "Allow",
            "Principal": {
                "Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}"
            },
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringLike": {
                    "oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}:aud": "sts.amazonaws.com",
                    "oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}:sub": "system:serviceaccount:*:*"
                }
            }
        }
    ]
}
EOF

# 创建权限策略
cat << 'EOF' > permission-policy.json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "S3Access",
            "Effect": "Allow",
            "Action": ["s3:Get*", "s3:List*", "s3:Describe*", "s3:PutObject"],
            "Resource": ["*"]
        },
        {
            "Sid": "ECRAccess",
            "Effect": "Allow",
            "Action": [
                "ecr:GetAuthorizationToken",
                "ecr:BatchCheckLayerAvailability",
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage"
            ],
            "Resource": ["*"]
        },
        {
            "Sid": "SageMakerAccess",
            "Effect": "Allow",
            "Action": ["sagemaker:*"],
            "Resource": ["*"]
        },
        {
            "Sid": "EC2Access",
            "Effect": "Allow",
            "Action": [
                "ec2:CreateNetworkInterface",
                "ec2:DeleteNetworkInterface",
                "ec2:DescribeNetworkInterfaces",
                "ec2:DescribeSubnets",
                "ec2:DescribeSecurityGroups"
            ],
            "Resource": ["*"]
        },
        {
            "Sid": "ELBAccess",
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:CreateLoadBalancer",
                "elasticloadbalancing:DescribeLoadBalancers",
                "elasticloadbalancing:DescribeTargetGroups"
            ],
            "Resource": ["*"]
        }
    ]
}
EOF

# 创建 IAM 角色
HYPERPOD_INFERENCE_ROLE_NAME="HyperpodInferenceRole-$HYPERPOD_CLUSTER_NAME"
aws iam create-role --role-name $HYPERPOD_INFERENCE_ROLE_NAME \
    --assume-role-policy-document file://trust-policy.json

aws iam put-role-policy --role-name $HYPERPOD_INFERENCE_ROLE_NAME \
    --policy-name InferenceOperatorInlinePolicy \
    --policy-document file://permission-policy.json
```

### 步骤 3: 安装 AWS Load Balancer Controller

```bash
# 下载 IAM 策略
curl -o AWSLoadBalancerControllerIAMPolicy.json \
    https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.13.0/docs/install/iam_policy.json

# 创建策略
aws iam create-policy \
    --policy-name HyperPodInferenceALBControllerIAMPolicy \
    --policy-document file://AWSLoadBalancerControllerIAMPolicy.json

# 创建服务账户
eksctl create iamserviceaccount \
    --approve \
    --override-existing-serviceaccounts \
    --name=aws-load-balancer-controller \
    --namespace=kube-system \
    --cluster=$EKS_CLUSTER_NAME \
    --attach-policy-arn=arn:aws:iam::$ACCOUNT_ID:policy/HyperPodInferenceALBControllerIAMPolicy \
    --region=$REGION
```

### 步骤 4: 安装 NVIDIA 设备插件

```bash
kubectl create -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.5/nvidia-device-plugin.yml

# 验证 GPU 可见性
kubectl get nodes -o=custom-columns=NAME:.metadata.name,GPU:.status.allocatable.nvidia.com/gpu
```

---

## 部署 JumpStart 模型

### 方式一: 使用 kubectl

#### 1. 查看可用模型

```bash
# 列出 JumpStart 公共中心的模型
aws sagemaker list-hub-contents \
    --hub-name SageMakerPublicHub \
    --hub-content-type Model \
    --query '{Models: HubContentSummaries[].{ModelId:HubContentName,Version:HubContentVersion}}' \
    --output json
```

#### 2. 选择模型并配置

```bash
export MODEL_ID="deepseek-llm-r1-distill-qwen-1-5b"
export MODEL_VERSION="2.0.4"
export SAGEMAKER_ENDPOINT_NAME="deepseek-qwen-1-5b-endpoint"
export CLUSTER_NAMESPACE="default"
export INSTANCE_TYPE="ml.g5.xlarge"
```

#### 3. 创建部署 YAML

```yaml
# jumpstart_model.yaml
apiVersion: inference.sagemaker.aws.amazon.com/v1
kind: JumpStartModel
metadata:
  name: deepseek-qwen-1-5b-endpoint
  namespace: default
spec:
  sageMakerEndpoint:
    name: deepseek-qwen-1-5b-endpoint
  model:
    modelHubName: SageMakerPublicHub
    modelId: deepseek-llm-r1-distill-qwen-1-5b
    modelVersion: "2.0.4"
  server:
    instanceType: ml.g5.xlarge
  metrics:
    enabled: true
  maxDeployTimeInSeconds: 1800
  autoScalingSpec:
    cloudWatchTrigger:
      name: "SageMaker-Invocations"
      namespace: "AWS/SageMaker"
      metricName: "Invocations"
      targetValue: 10
      metricCollectionPeriod: 30
      metricStat: "Sum"
      dimensions:
        - name: "EndpointName"
          value: "deepseek-qwen-1-5b-endpoint"
        - name: "VariantName"
          value: "AllTraffic"
```

#### 4. 部署模型

```bash
kubectl apply -f jumpstart_model.yaml

# 监控部署状态
kubectl describe JumpStartModel $SAGEMAKER_ENDPOINT_NAME -n $CLUSTER_NAMESPACE

# 验证端点创建
aws sagemaker describe-endpoint --endpoint-name=$SAGEMAKER_ENDPOINT_NAME --output table
```

#### 5. 调用模型

```bash
aws sagemaker-runtime invoke-endpoint \
    --endpoint-name $SAGEMAKER_ENDPOINT_NAME \
    --content-type "application/json" \
    --body '{"inputs": "What is AWS SageMaker?"}' \
    --region $REGION \
    --cli-binary-format raw-in-base64-out \
    /dev/stdout
```

### 方式二: 使用 HyperPod CLI

```bash
# 部署 JumpStart 模型
hyperpod deploy jumpstart \
    --model-id deepseek-llm-r1-distill-qwen-1-5b \
    --model-version 2.0.4 \
    --instance-type ml.g5.xlarge \
    --endpoint-name my-endpoint \
    --cluster-name $HYPERPOD_CLUSTER_NAME

# 调用模型
hyperpod invoke \
    --endpoint-name my-endpoint \
    --body '{"inputs": "Hello, how are you?"}'
```

### 方式三: 使用 Python SDK

```python
from sagemaker.hyperpod import HPJumpStartEndpoint

# 创建端点
endpoint = HPJumpStartEndpoint(
    model_id="deepseek-llm-r1-distill-qwen-1-5b",
    model_version="2.0.4",
    instance_type="ml.g5.xlarge",
    endpoint_name="my-jumpstart-endpoint"
)

# 部署
endpoint.deploy()

# 调用
response = endpoint.invoke(
    body={"inputs": "What is machine learning?"}
)
print(response)

# 删除
endpoint.delete()
```

---

## 部署自定义模型

### 从 Amazon S3 部署

```yaml
# deploy_s3_inference.yaml
apiVersion: inference.sagemaker.aws.amazon.com/v1
kind: InferenceEndpointConfig
metadata:
  name: my-custom-model
  namespace: default
spec:
  modelName: llama-3-8b-instruct
  endpointName: my-custom-model-endpoint
  instanceType: ml.g5.24xlarge
  invocationEndpoint: v1/chat/completions
  replicas: 2
  modelSourceConfig:
    modelSourceType: s3
    s3Storage:
      bucketName: my-model-bucket
      region: us-west-2
    modelLocation: models/llama-3-8b-instruct
    prefetchEnabled: true
  worker:
    image: 763104351884.dkr.ecr.us-west-2.amazonaws.com/djl-inference:0.32.0-lmi14.0.0-cu124
    resources:
      limits:
        nvidia.com/gpu: "4"
      requests:
        cpu: "30"
        memory: 100Gi
        nvidia.com/gpu: "4"
    modelInvocationPort:
      containerPort: 8000
      name: http
    modelVolumeMount:
      name: model-weights
      mountPath: /opt/ml/model
    environmentVariables:
      - name: OPTION_ROLLING_BATCH
        value: "vllm"
      - name: OPTION_TRUST_REMOTE_CODE
        value: "true"
      - name: MODEL_CACHE_ROOT
        value: "/opt/ml/model"
      - name: SAGEMAKER_ENV
        value: "1"
```

### 从 Amazon FSx 部署

```yaml
# deploy_fsx_inference.yaml
apiVersion: inference.sagemaker.aws.amazon.com/v1
kind: InferenceEndpointConfig
metadata:
  name: fsx-model-deployment
  namespace: default
spec:
  modelName: my-finetuned-model
  instanceType: ml.g5.24xlarge
  invocationEndpoint: v1/chat/completions
  replicas: 2
  modelSourceConfig:
    modelSourceType: fsx
    fsxStorage:
      fileSystemId: fs-0123456789abcdef0
    modelLocation: models/my-finetuned-model
  worker:
    image: 763104351884.dkr.ecr.us-west-2.amazonaws.com/huggingface-pytorch-tgi-inference:2.4.0-tgi2.3.1-gpu-py311-cu124-ubuntu22.04-v2.0
    resources:
      limits:
        nvidia.com/gpu: "4"
      requests:
        cpu: 30000m
        memory: 100Gi
        nvidia.com/gpu: "4"
    modelInvocationPort:
      containerPort: 8080
      name: http
    modelVolumeMount:
      mountPath: /opt/ml/model
      name: model-weights
    environmentVariables:
      - name: HF_MODEL_ID
        value: /opt/ml/model
      - name: SAGEMAKER_ENV
        value: "1"
```

### 部署和验证

```bash
# 部署
kubectl apply -f deploy_s3_inference.yaml

# 检查部署状态
kubectl describe InferenceEndpointConfig my-custom-model -n default

# 检查端点注册
kubectl describe SageMakerEndpointRegistration my-custom-model-endpoint -n default

# 测试端点
aws sagemaker-runtime invoke-endpoint \
    --endpoint-name my-custom-model-endpoint \
    --content-type "application/json" \
    --body '{"inputs": "Hello world"}' \
    --region $REGION \
    /dev/stdout
```

---

## 自动扩缩容配置

### 内置自动扩缩容 (autoScalingSpec)

```yaml
autoScalingSpec:
  minReplicas: 1
  maxReplicas: 10
  pollingInterval: 30
  cooldownPeriod: 300
  cloudWatchTrigger:
    name: "SageMaker-Invocations"
    namespace: "AWS/SageMaker"
    metricName: "Invocations"
    targetValue: 100
    metricCollectionPeriod: 60
    metricStat: "Sum"
    dimensions:
      - name: "EndpointName"
        value: "my-endpoint"
      - name: "VariantName"
        value: "AllTraffic"
```

### KEDA ScaledObject 配置

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: my-model-scaler
  namespace: default
spec:
  scaleTargetRef:
    name: my-model-deployment
  pollingInterval: 30
  cooldownPeriod: 300
  minReplicaCount: 1
  maxReplicaCount: 10
  triggers:
    - type: aws-cloudwatch
      metadata:
        namespace: AWS/SageMaker
        dimensionName: EndpointName
        dimensionValue: my-endpoint
        metricName: Invocations
        targetMetricValue: "100"
        awsRegion: us-west-2
```

---

## KV 缓存和智能路由

### 启用 KV 缓存

```yaml
spec:
  kvCacheSpec:
    enableL1Cache: true
    enableL2Cache: true
    l2CacheSpec:
      l2CacheBackend: redis  # 或 tieredstorage
      l2CacheLocalUrl: redis://redis.redis-system.svc.cluster.local:6379
```

### 智能路由配置

```yaml
spec:
  intelligentRoutingSpec:
    enabled: true
    routingStrategy: prefixaware  # 可选: prefixaware, session, roundrobin
```

---

## 监控和可观测性

### 启用指标收集

```yaml
spec:
  metrics:
    enabled: true
    modelMetrics:
      port: 8000
```

### 常用监控命令

```bash
# 查看 Pod 状态
kubectl get pods -n $CLUSTER_NAMESPACE -l app=$SAGEMAKER_ENDPOINT_NAME

# 查看 Pod 日志
kubectl logs -n $CLUSTER_NAMESPACE -l app=$SAGEMAKER_ENDPOINT_NAME

# 查看资源使用情况
kubectl top pods -n $CLUSTER_NAMESPACE
```

---

## 故障排除

### 常见问题

#### 1. 模型部署卡在 Pending 状态

```bash
# 检查推理操作符状态
kubectl get pods -n hyperpod-inference-system

# 查看操作符日志
kubectl logs -n hyperpod-inference-system -l app=hyperpod-inference-operator
```

#### 2. GPU 设备未找到

```bash
# 安装 NVIDIA 设备插件
kubectl create -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.5/nvidia-device-plugin.yml

# 验证 GPU 可见性
kubectl get nodes -o=custom-columns=NAME:.metadata.name,GPU:.status.allocatable.nvidia.com/gpu
```

### 调试命令

```bash
# 检查所有相关资源状态
kubectl get pods,svc,deployment,JumpStartModel,InferenceEndpointConfig -n $CLUSTER_NAMESPACE

# 查看事件
kubectl get events -n $CLUSTER_NAMESPACE --sort-by='.lastTimestamp'
```

### 清理资源

```bash
# 删除部署
kubectl delete JumpStartModel $SAGEMAKER_ENDPOINT_NAME -n $CLUSTER_NAMESPACE
kubectl delete InferenceEndpointConfig $SAGEMAKER_ENDPOINT_NAME -n $CLUSTER_NAMESPACE
```

---

## 常用推理容器镜像

| 框架 | 镜像 |
|------|------|
| vLLM/LMI | `763104351884.dkr.ecr.<region>.amazonaws.com/djl-inference:0.32.0-lmi14.0.0-cu124` |
| TGI | `763104351884.dkr.ecr.<region>.amazonaws.com/huggingface-pytorch-tgi-inference:2.4.0-tgi2.3.1-gpu-py311-cu124-ubuntu22.04-v2.0` |

---

## Python SDK 推理资源管理

本项目提供了 `hyperpod_inference_manager.py` 模块，使用 Kubernetes Python 客户端库管理 HyperPod 推理资源。

### 安装依赖

```bash
pip install kubernetes
```

### 基本用法

```python
from hyperpod_inference_manager import (
    HyperPodInferenceManager,
    AutoScalingConfig,
    KVCacheConfig,  
    WorkerConfig
)

# 初始化管理器
manager = HyperPodInferenceManager()

# 或指定 kubeconfig
manager = HyperPodInferenceManager(
    kubeconfig_path="/path/to/kubeconfig",
    context="my-context"
)

# 在集群内部运行时
manager = HyperPodInferenceManager(in_cluster=True)
```

### 部署 JumpStart 模型

```python
# 基本部署
result = manager.deploy_jumpstart_model(
    name="deepseek-qwen-endpoint",
    model_id="deepseek-llm-r1-distill-qwen-1-5b",
    model_version="2.0.4",
    instance_type="ml.g5.xlarge",
    namespace="default"
)

# 带自动扩缩容配置
autoscaling = AutoScalingConfig(
    min_replicas=1,
    max_replicas=5,
    metric_name="Invocations",
    target_value=100
)

result = manager.deploy_jumpstart_model(
    name="scalable-model",
    model_id="deepseek-llm-r1-distill-qwen-1-5b",
    model_version="2.0.4",
    instance_type="ml.g5.xlarge",
    autoscaling=autoscaling
)
```

### 部署自定义模型

```python
# 从 S3 部署
result = manager.deploy_custom_model(
    name="my-llama-model",
    model_name="llama-3-8b-instruct",
    instance_type="ml.g5.24xlarge",
    s3_bucket="my-model-bucket",
    s3_region="us-west-2",
    model_location="models/llama-3-8b-instruct",
    inference_engine="vllm",  # 或 "tgi"
    replicas=2
)

# 带 KV 缓存和智能路由
from hyperpod_inference_manager import KVCacheConfig, IntelligentRoutingConfig

kv_cache = KVCacheConfig(
    enable_l1_cache=True,
    enable_l2_cache=True,
    l2_cache_backend="redis",
    l2_cache_url="redis://redis.redis-system.svc.cluster.local:6379"
)

routing = IntelligentRoutingConfig(
    enabled=True,
    routing_strategy="prefixaware"
)

result = manager.deploy_custom_model(
    name="optimized-model",
    model_name="llama-3-8b-instruct",
    instance_type="ml.g5.24xlarge",
    s3_bucket="my-bucket",
    model_location="models/llama-3-8b",
    kv_cache=kv_cache,
    intelligent_routing=routing
)
```

### 查询和管理资源

```python
# 列出所有 JumpStart 模型
models = manager.list_jumpstart_models(namespace="default")
for model in models:
    print(f"模型: {model['metadata']['name']}")

# 列出所有自定义模型
custom_models = manager.list_custom_models(namespace="default")

# 获取特定模型详情
model = manager.get_jumpstart_model("my-model", namespace="default")
custom_model = manager.get_custom_model("my-custom-model")

# 获取模型状态摘要
status = manager.get_model_status(
    name="my-model",
    namespace="default",
    resource_type="jumpstart"
)
print(f"端点名称: {status['endpoint_name']}")
print(f"实例类型: {status['instance_type']}")
print(f"Pod 状态: {status['pods']}")
```

### 更新和扩缩容

```python
# 更新实例类型
manager.update_jumpstart_model(
    name="my-model",
    instance_type="ml.g5.2xlarge"
)

# 更新自动扩缩容配置
new_autoscaling = AutoScalingConfig(
    min_replicas=2,
    max_replicas=10,
    target_value=50
)
manager.update_jumpstart_model(
    name="my-model",
    autoscaling=new_autoscaling
)

# 扩缩容自定义模型
manager.scale_custom_model(
    name="my-custom-model",
    replicas=3
)
```

### 删除资源

```python
# 删除 JumpStart 模型
manager.delete_jumpstart_model("my-model", namespace="default")

# 删除自定义模型
manager.delete_custom_model("my-custom-model", namespace="default")
```

### 监听资源变更

```python
# 监听 JumpStart 模型变更
for event in manager.watch_jumpstart_models(
    namespace="default",
    timeout_seconds=300
):
    event_type = event["type"]  # ADDED, MODIFIED, DELETED
    model = event["object"]
    print(f"事件: {event_type}, 模型: {model['metadata']['name']}")

# 等待部署完成
success = manager.wait_for_deployment(
    name="my-model",
    namespace="default",
    resource_type="jumpstart",
    timeout_seconds=1800
)
if success:
    print("部署成功!")
```

### 获取 Pod 日志

```python
# 获取模型关联的 Pod
pods = manager.get_pods_for_model("my-model", namespace="default")
for pod in pods:
    print(f"Pod: {pod.metadata.name}, 状态: {pod.status.phase}")

# 获取 Pod 日志
logs = manager.get_pod_logs("my-model", namespace="default", tail_lines=100)
for pod_name, log in logs.items():
    print(f"=== {pod_name} ===")
    print(log)
```

### 命令行使用

```bash
# 列出所有推理资源
python hyperpod_inference_manager.py list --namespace default

# 获取资源详情
python hyperpod_inference_manager.py get my-model --type jumpstart

# 部署 JumpStart 模型
python hyperpod_inference_manager.py deploy-jumpstart my-model \
    --model-id deepseek-llm-r1-distill-qwen-1-5b \
    --model-version 2.0.4 \
    --instance-type ml.g5.xlarge

# 部署自定义模型
python hyperpod_inference_manager.py deploy-custom my-custom-model \
    --model-name llama-3-8b-instruct \
    --instance-type ml.g5.24xlarge \
    --s3-bucket my-bucket \
    --model-location models/llama-3-8b \
    --engine vllm

# 删除资源
python hyperpod_inference_manager.py delete my-model --type jumpstart
```

### API 参考

#### HyperPodInferenceManager

| 方法 | 描述 |
|------|------|
| `deploy_jumpstart_model()` | 部署 JumpStart 模型 |
| `get_jumpstart_model()` | 获取 JumpStart 模型 |
| `list_jumpstart_models()` | 列出 JumpStart 模型 |
| `update_jumpstart_model()` | 更新 JumpStart 模型 |
| `delete_jumpstart_model()` | 删除 JumpStart 模型 |
| `deploy_custom_model()` | 部署自定义模型 |
| `get_custom_model()` | 获取自定义模型 |
| `list_custom_models()` | 列出自定义模型 |
| `update_custom_model()` | 更新自定义模型 |
| `delete_custom_model()` | 删除自定义模型 |
| `scale_custom_model()` | 扩缩容自定义模型 |
| `watch_jumpstart_models()` | 监听 JumpStart 模型变更 |
| `watch_custom_models()` | 监听自定义模型变更 |
| `wait_for_deployment()` | 等待部署完成 |
| `get_pods_for_model()` | 获取模型关联的 Pod |
| `get_pod_logs()` | 获取 Pod 日志 |
| `get_model_status()` | 获取模型状态摘要 |

#### 配置类

| 类 | 描述 |
|------|------|
| `AutoScalingConfig` | 自动扩缩容配置 |
| `KVCacheConfig` | KV 缓存配置 |
| `IntelligentRoutingConfig` | 智能路由配置 |
| `WorkerConfig` | Worker 容器配置 |

---

## 参考链接

- [SageMaker HyperPod 模型部署文档](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-model-deployment.html)
- [HyperPod 推理设置指南](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-model-deployment-setup.html)
- [自动扩缩容配置](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-model-deployment-autoscaling.html)
- [Kubernetes Python 客户端](https://github.com/kubernetes-client/python)
