# AWS HyperPod EKS 集群中 SGLang 多机分布式推理部署完整指南

> **文档版本**: v1.5
> **更新日期**: 2026-01-31
> **作者**: 技术调研团队

---

## 📋 目录

- [1. 概述](#1-概述)
- [2. 核心架构](#2-核心架构)
- [3. SGLang 在 HyperPod 上的集成方案](#3-sglang-在-hyperpod-上的集成方案)
- [4. 多节点部署配置](#4-多节点部署配置)
- [5. 使用 HuggingFace Model ID 直接部署](#5-使用-huggingface-model-id-直接部署)
- [6. 部署步骤](#6-部署步骤)
- [7. 性能优化与最佳实践](#7-性能优化与最佳实践)
- [8. 监控和可观测性](#8-监控和可观测性)
- [9. 故障排查](#9-故障排查)
- [10. 实际案例研究](#10-实际案例研究)
- [11. 参考资源](#11-参考资源)

---

## 1. 概述

### 1.1 背景

AWS SageMaker HyperPod 现已支持通过 Amazon EKS 进行推理部署，提供了一个完整的推理平台，结合了 Kubernetes 的灵活性和 AWS 托管服务的可靠性。本文档详细介绍如何在 HyperPod EKS 集群中部署 SGLang 推理引擎进行多机分布式推理。

### 1.2 为什么选择 SGLang？

**SGLang (Structured Generation Language)** 是一个高性能的大语言模型服务框架，具有以下优势：

- ✅ **高性能推理**: 使用 RadixAttention 进行前缀缓存，零开销 CPU 调度器
- ✅ **广泛的模型支持**: 兼容大多数 HuggingFace 模型和 OpenAI API
- ✅ **多节点推理**: 原生支持 tensor parallelism 和跨节点分布式部署
- ✅ **生产就绪**: 支持连续批处理、分页注意力、量化（FP4/FP8/INT4/AWQ/GPTQ）
- ✅ **易于集成**: 与 Kubernetes、Ray Cluster 和 HuggingFace Hub 无缝集成

### 1.3 适用场景

本方案适用于以下场景：

1. **超大模型推理** - 单节点 GPU 无法容纳的模型（如 Llama 405B、DeepSeek R1 671B）
2. **高吞吐量需求** - 需要处理大量并发请求
3. **低延迟要求** - 利用多节点并行降低推理延迟
4. **生产环境部署** - 需要高可用性、自动扩展和监控能力

---

## 2. 核心架构

### 2.1 整体技术栈

```
┌─────────────────────────────────────────────────────────┐
│         AWS SageMaker HyperPod (编排层)                  │
│  - 集群生命周期管理                                       │
│  - 自动故障恢复                                          │
│  - 资源优化                                              │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│           Amazon EKS (Kubernetes 集群)                    │
│  - Container 编排                                        │
│  - 服务发现与负载均衡                                     │
│  - 自动扩展                                              │
└─────────────────────────┬───────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
┌───────▼──────┐  ┌──────▼───────┐  ┌─────▼───────┐
│ Ray Cluster  │  │  LeaderWorker │  │  HyperPod   │
│  (可选)       │  │     Set       │  │  Inference  │
│              │  │    (推荐)      │  │  Operator   │
└───────┬──────┘  └──────┬───────┘  └─────┬───────┘
        │                 │                 │
        └─────────────────┼─────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│              SGLang (推理引擎)                            │
│  - RadixAttention                                        │
│  - Continuous Batching                                   │
│  - Multi-node Tensor Parallelism                         │
│  - KV Cache 优化                                         │
└──────────────────────────────────────────────────────────┘
```

### 2.2 关键特性

| 特性 | 说明 |
|------|------|
| **统一基础设施** | 同一 HyperPod 集群可用于训练和推理，最大化 GPU 利用率 |
| **多节点推理架构** | 支持单节点和多节点推理部署 |
| **自动扩展** | 通过 KEDA（Kubernetes Event Driven Autoscaling）实现动态扩展 |
| **弹性容错** | 自动检测和恢复硬件故障 |
| **GPU 分区（MIG）** | 使用 Multi-Instance GPU 技术提高利用率 |
| **智能路由** | 根据前缀、KV 缓存命中率进行请求路由 |

### 2.3 网络拓扑

```
                    ┌──────────────────┐
                    │  Kubernetes      │
                    │  Service/Ingress │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
    ┌─────────▼────────┐ ┌──▼──────────┐ ┌─▼─────────────┐
    │  Leader Node 0   │ │ Worker      │ │ Worker        │
    │  (Rank 0)        │ │ Node 1      │ │ Node 2        │
    │  - HTTP Server   │ │ (Rank 1)    │ │ (Rank 2)      │
    │  - 8x GPU (TP=8) │ │ - 8x GPU    │ │ - 8x GPU      │
    └──────────────────┘ └─────────────┘ └───────────────┘
              │                   │              │
              └───────────────────┼──────────────┘
                                  │
                        ┌─────────▼──────────┐
                        │  EFA (Elastic      │
                        │  Fabric Adapter)   │
                        │  - RDMA 通信        │
                        │  - 低延迟互联       │
                        └────────────────────┘
```

---

## 3. SGLang 在 HyperPod 上的集成方案

### 3.1 实际生产案例：Osmosis AI

根据 Tech42 Consulting 的案例研究，**Osmosis AI（Gulp.ai）成功在 AWS SageMaker HyperPod EKS 上集成了 SGLang**，用于 LLM 微调期间的模型推理。

**架构组件**：
- **Amazon SageMaker HyperPod** - 管理整个训练/推理基础设施生命周期
- **Amazon EKS** - 由 HyperPod 编排的 Kubernetes 服务
- **Ray Cluster** - 在 HyperPod 环境内管理的分布式计算框架
- **SGLang** - 作为推理后端运行在容器中

**关键收益**：
- ✅ 显著提高 GPU 利用率
- ✅ 通过优化内存使用和更快的 token 生成减少训练时间
- ✅ 从单节点无缝扩展到多节点配置
- ✅ 动态批处理和高效的 GPU 利用率大幅降低计算成本

### 3.2 三种部署模式

#### 模式 1：聚合模式（Aggregated）
适用于开发/测试环境

```
┌────────────────────────────────┐
│         Frontend               │
│  (OpenAI-compatible API)       │
└───────────┬────────────────────┘
            │
┌───────────▼────────────────────┐
│   SGLangDecodeWorker           │
│   (处理 prefill + decode)       │
└────────────────────────────────┘
```

#### 模式 2：聚合路由模式（Aggregated Router）
适用于生产环境，支持负载均衡

```
┌────────────────────────────────┐
│         Frontend               │
│  (带 KV Cache 路由)             │
└───────────┬────────────────────┘
            │
┌───────────▼────────────────────┐
│   SGLangDecodeWorker           │
│   (处理 prefill + decode)       │
│   + KV Cache 路由               │
└────────────────────────────────┘
```

#### 模式 3：解耦模式（Disaggregated）⭐️
适用于最高性能需求

```
┌────────────────────────────────┐
│         Frontend               │
│  (HTTP API Server)             │
└───────┬────────────────────┬───┘
        │                    │
┌───────▼──────────┐  ┌──────▼────────────┐
│ SGLangPrefill    │  │ SGLangDecode      │
│ Worker           │  │ Worker            │
│ (仅 prefill)      │  │ (仅 decode)        │
└──────────────────┘  └───────────────────┘
```

---

## 4. 多节点部署配置

### 4.1 使用 LeaderWorkerSet（推荐方案）

LeaderWorkerSet 是 Kubernetes 社区推荐的多节点 LLM 推理解决方案，被 SGLang、vLLM、NVIDIA Dynamo 等主流框架采用。

#### 4.1.1 完整 YAML 配置

```yaml
# sglang-multi-node.yaml
apiVersion: leaderworkerset.x-k8s.io/v1
kind: LeaderWorkerSet
metadata:
  name: sglang-multi-nodes
  namespace: default
spec:
  replicas: 1  # LeaderWorkerSet 副本数
  leaderWorkerTemplate:
    size: 2  # 每个 LeaderWorkerSet 包含的节点数（1 leader + 1 worker）
    restartPolicy: RecreateGroupOnPodRestart

    # Leader 节点配置
    leaderTemplate:
      metadata:
        labels:
          role: leader
          app: sglang-inference
          inference-workload: sglang-multi-nodes
          inference-backend: sglang
      spec:
        containers:
        - name: sglang-leader
          image: lmsysorg/sglang:v0.5.8
          command:
          - sh
          - -c
          - |
            python3 -m sglang.launch_server \
              --model-path Qwen/Qwen3-30B-A3B-Thinking-2507 \
              --tp 8 \
              --dist-init-addr $(LWS_LEADER_ADDRESS):20000 \
              --nnodes 2 \
              --node-rank 0 \
              --host 0.0.0.0 \
              --port 30000 \
              --trust-remote-code \
              --enable-metrics \
              --mem-fraction-static 0.85 \
              --chunked-prefill-size 8192 \
              --context-length 32768 \
              --max-running-requests 256

          env:
          # HuggingFace Token
          - name: HF_TOKEN
            valueFrom:
              secretKeyRef:
                name: hf-token-secret
                key: token

          # GPU 配置
          - name: CUDA_VISIBLE_DEVICES
            value: "0,1,2,3,4,5,6,7"

          # NCCL 调试
          - name: NCCL_DEBUG
            value: "INFO"

          # EFA 配置（如使用高性能实例）
          - name: NCCL_IB_DISABLE
            value: "0"
          - name: NCCL_NET_GDR_LEVEL
            value: "5"
          - name: FI_PROVIDER
            value: "efa"
          - name: FI_EFA_USE_DEVICE_RDMA
            value: "1"

          resources:
            limits:
              nvidia.com/gpu: 8
              vpc.amazonaws.com/efa: 1  # EFA 网络接口
            requests:
              nvidia.com/gpu: 8
              vpc.amazonaws.com/efa: 1
              cpu: "96"
              memory: "512Gi"

          ports:
          - name: http
            containerPort: 30000
            protocol: TCP
          - name: metrics
            containerPort: 9090
            protocol: TCP

          volumeMounts:
          - name: hf-cache
            mountPath: /root/.cache/huggingface
          - name: shm
            mountPath: /dev/shm

          livenessProbe:
            httpGet:
              path: /health
              port: 30000
            initialDelaySeconds: 1800  # 30 分钟，给模型下载时间
            periodSeconds: 30
            timeoutSeconds: 10
            failureThreshold: 3

          readinessProbe:
            httpGet:
              path: /health
              port: 30000
            initialDelaySeconds: 1800
            periodSeconds: 10
            timeoutSeconds: 5

        volumes:
        - name: hf-cache
          persistentVolumeClaim:
            claimName: huggingface-cache-pvc
        - name: shm
          emptyDir:
            medium: Memory
            sizeLimit: 64Gi

        # 节点选择器（确保调度到 GPU 节点）
        nodeSelector:
          node.kubernetes.io/instance-type: ml.p5.48xlarge

        # 容忍度（如果 GPU 节点有 taint）
        tolerations:
        - key: nvidia.com/gpu
          operator: Exists
          effect: NoSchedule

    # Worker 节点配置
    workerTemplate:
      metadata:
        labels:
          role: worker
          app: sglang-inference
          inference-workload: sglang-multi-nodes
      spec:
        containers:
        - name: sglang-worker
          image: lmsysorg/sglang:v0.5.8
          command:
          - sh
          - -c
          - |
            python3 -m sglang.launch_server \
              --model-path Qwen/Qwen3-30B-A3B-Thinking-2507 \
              --tp 8 \
              --dist-init-addr $(LWS_LEADER_ADDRESS):20000 \
              --nnodes 2 \
              --node-rank 1 \
              --trust-remote-code \
              --mem-fraction-static 0.85

          env:
          - name: HF_TOKEN
            valueFrom:
              secretKeyRef:
                name: hf-token-secret
                key: token
          - name: CUDA_VISIBLE_DEVICES
            value: "0,1,2,3,4,5,6,7"
          - name: NCCL_DEBUG
            value: "INFO"
          - name: NCCL_IB_DISABLE
            value: "0"
          - name: NCCL_NET_GDR_LEVEL
            value: "5"
          - name: FI_PROVIDER
            value: "efa"
          - name: FI_EFA_USE_DEVICE_RDMA
            value: "1"

          resources:
            limits:
              nvidia.com/gpu: 8
              vpc.amazonaws.com/efa: 1
            requests:
              nvidia.com/gpu: 8
              vpc.amazonaws.com/efa: 1
              cpu: "96"
              memory: "512Gi"

          volumeMounts:
          - name: hf-cache
            mountPath: /root/.cache/huggingface
          - name: shm
            mountPath: /dev/shm

        volumes:
        - name: hf-cache
          persistentVolumeClaim:
            claimName: huggingface-cache-pvc
        - name: shm
          emptyDir:
            medium: Memory
            sizeLimit: 64Gi

        nodeSelector:
          node.kubernetes.io/instance-type: ml.p5.48xlarge

        tolerations:
        - key: nvidia.com/gpu
          operator: Exists
          effect: NoSchedule

---
# Service - 仅暴露 Leader 节点
apiVersion: v1
kind: Service
metadata:
  name: sglang-service
  namespace: default
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "9090"
    prometheus.io/path: "/metrics"
spec:
  selector:
    app: sglang-inference
    role: leader
  ports:
  - name: http
    protocol: TCP
    port: 30000
    targetPort: 30000
  - name: metrics
    protocol: TCP
    port: 9090
    targetPort: 9090
  type: ClusterIP

---
# Ingress (可选 - 用于外部访问)
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: sglang-ingress
  namespace: default
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
spec:
  rules:
  - host: sglang.yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: sglang-service
            port:
              number: 30000
```

#### 4.1.2 关键参数说明

| 参数 | 说明 | 示例值 |
|------|------|--------|
| `--model-path` | HuggingFace Model ID 或本地路径 | `Qwen/Qwen3-30B-A3B-Thinking-2507` |
| `--tp` | Tensor Parallelism 并行度（别名: `--tp-size`）| `2`, `4`, `8`, `16` |
| `--dist-init-addr` | 分布式初始化地址 | `$(LWS_LEADER_ADDRESS):20000` |
| `--nnodes` | 节点总数 | `2`, `4`, `8` |
| `--node-rank` | 当前节点排名（Leader=0） | `0`, `1`, `2`, `3`... |
| `--host` | 服务监听地址 | `0.0.0.0` |
| `--port` | HTTP 服务端口 | `30000`（默认） |
| `--trust-remote-code` | 信任远程代码 | flag |
| `--enable-metrics` | 启用 Prometheus 指标 | flag |
| `--mem-fraction-static` | KV Cache 内存比例 | `0.85` (85%) |
| `--chunked-prefill-size` | Chunked Prefill 大小 | `8192` |
| `--context-length` | 最大上下文长度 | `32768` |
| `--max-running-requests` | 最大并发请求数 | `256` |

**端口说明**：SGLang 默认使用 30000 端口。AWS SageMaker DLC 容器通常使用 8000 (vLLM) 或 8080 (SGLang DLC)。本文档示例使用 SGLang 原生默认端口 30000。

### 4.2 使用 HyperPod Inference Operator

如果使用 AWS 原生的 HyperPod Inference Operator：

```yaml
# sglang-hyperpod-inference.yaml
apiVersion: inference.sagemaker.aws.amazon.com/v1
kind: InferenceEndpointConfig
metadata:
  name: sglang-endpoint
  namespace: default
spec:
  replicas: 2  # 多副本部署

  worker:
    image: lmsysorg/sglang:v0.5.8

    command:
    - python3
    - -m
    - sglang.launch_server
    - --model-path
    - Qwen/Qwen3-30B-A3B-Thinking-2507
    - --tp
    - "8"
    - --host
    - 0.0.0.0
    - --port
    - "30000"
    - --trust-remote-code
    - --enable-metrics

    modelInvocationPort:
      containerPort: 30000
      name: http

    resources:
      limits:
        nvidia.com/gpu: 8
        cpu: "128"
        memory: "512Gi"
      requests:
        nvidia.com/gpu: 8
        cpu: "64"
        memory: "256Gi"

    environmentVariables:
    - name: HF_TOKEN
      valueFrom:
        secretKeyRef:
          name: hf-token-secret
          key: token
    - name: CUDA_VISIBLE_DEVICES
      value: "0,1,2,3,4,5,6,7"

    volumeMounts:
    - name: hf-cache
      mountPath: /root/.cache/huggingface
    - name: shm
      mountPath: /dev/shm

  volumes:
  - name: hf-cache
    persistentVolumeClaim:
      claimName: huggingface-cache-pvc
  - name: shm
    emptyDir:
      medium: Memory
      sizeLimit: 64Gi

  # TLS 配置
  tlsConfig:
    tlsCertificateOutputS3Uri: s3://my-bucket/sglang-certs/

  # 监控指标
  metrics:
    enabled: true
```

---

## 5. 使用 HuggingFace Model ID 直接部署

### 5.1 工作原理

SGLang 原生支持直接使用 HuggingFace Model ID 来自动下载和部署模型：

1. **自动从 HuggingFace Hub 下载模型**
2. **缓存到默认目录**（`~/.cache/huggingface/`）
3. **加载并启动推理服务**

### 5.2 支持的模型格式

#### 公开模型（无需认证）
```bash
--model-path meta-llama/Llama-3.2-1B-Instruct
--model-path microsoft/DialoGPT-medium
--model-path deepseek-ai/deepseek-llm-7b-chat
```

#### 门控模型（需要 HF Token）
```bash
--model-path Qwen/Qwen3-30B-A3B-Thinking-2507
--model-path meta-llama/Meta-Llama-3.1-405B-Instruct
```

#### 需要自定义代码的模型
```bash
--model-path MiniMaxAI/MiniMax-M2 --trust-remote-code
--model-path kyutai/helium-1-preview-2b --trust-remote-code
```

### 5.3 配置 HuggingFace Token

#### 方法 1：使用 Kubernetes Secret

```bash
# 创建 Secret
kubectl create secret generic hf-token-secret \
  --from-literal=token=hf_xxxxxxxxxxxxxxxxxxxxxxxxxx \
  --namespace=default
```

在 YAML 中引用：
```yaml
env:
- name: HF_TOKEN
  valueFrom:
    secretKeyRef:
      name: hf-token-secret
      key: token
```

**说明**：
- `HF_TOKEN` 是 HuggingFace 推荐的环境变量名（2023年后）
- SGLang 会自动检测并使用 `HF_TOKEN` 进行认证
- 旧版环境变量名 `HUGGING_FACE_HUB_TOKEN` 仍然支持，但建议使用 `HF_TOKEN`

#### 方法 2：使用旧的环境变量名（向后兼容）
```yaml
env:
- name: HUGGING_FACE_HUB_TOKEN
  valueFrom:
    secretKeyRef:
      name: hf-token-secret
      key: token
```

### 5.4 配置持久化存储

#### 创建 FSx for Lustre PVC（推荐）

```yaml
# fsx-lustre-storageclass.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fsx-lustre-sc
provisioner: fsx.csi.aws.com
parameters:
  subnetId: subnet-xxxxxxxxx
  securityGroupIds: sg-xxxxxxxxx
  deploymentType: PERSISTENT_1
  perUnitStorageThroughput: "200"
  fileSystemTypeVersion: "2.15"

---
# huggingface-cache-pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: huggingface-cache-pvc
  namespace: default
spec:
  accessModes:
  - ReadWriteMany  # 多节点共享访问
  resources:
    requests:
      storage: 500Gi  # 根据模型大小调整
  storageClassName: fsx-lustre-sc
```

**为什么选择 FSx for Lustre？**
- ✅ 支持多节点并发读写（ReadWriteMany）
- ✅ 高性能，适合大模型文件（可达 GB/s 吞吐量）
- ✅ 可以预加载 S3 中的数据
- ✅ 按需扩展，成本优化

### 5.5 使用 InitContainer 预下载模型（可选）

为避免首次启动时下载模型导致超时，可以使用 InitContainer：

```yaml
initContainers:
- name: model-downloader
  image: lmsysorg/sglang:v0.5.8
  command:
  - sh
  - -c
  - |
    echo "开始下载模型..."
    python3 -c "
    from huggingface_hub import snapshot_download
    import os
    snapshot_download(
      repo_id='Qwen/Qwen3-30B-A3B-Thinking-2507',
      cache_dir='/root/.cache/huggingface',
      token=os.environ.get('HF_TOKEN')
    )
    "
    echo "模型下载完成！"
  env:
  - name: HF_TOKEN
    valueFrom:
      secretKeyRef:
        name: hf-token-secret
        key: token
  volumeMounts:
  - name: hf-cache
    mountPath: /root/.cache/huggingface
  resources:
    requests:
      cpu: "8"
      memory: "32Gi"
```

### 5.6 中国区加速（可选）

如果在中国区部署，可以使用镜像站点加速下载：

```yaml
env:
- name: HF_ENDPOINT
  value: "https://hf-mirror.com"
```

---

## 6. 部署步骤

### 6.1 前置准备

#### 1. 安装 LeaderWorkerSet CRD

```bash
# 安装 LeaderWorkerSet
kubectl apply --server-side -f https://github.com/kubernetes-sigs/lws/releases/download/v0.5.0/manifests.yaml

# 验证安装
kubectl get crd leaderworkersets.leaderworkerset.x-k8s.io
```

#### 2. 安装 HyperPod Inference Operator（如使用）

```bash
# 具体安装步骤请参考 AWS 官方文档
# https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-inference-operator.html
```

#### 3. 配置 GPU Operator（如未安装）

```bash
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia
helm repo update
helm install --wait --generate-name \
  -n gpu-operator --create-namespace \
  nvidia/gpu-operator
```

#### 4. 配置 EFA（用于高性能实例）

```bash
# 安装 EFA device plugin
kubectl apply -f https://raw.githubusercontent.com/aws/eks-charts/master/stable/aws-efa-k8s-device-plugin/aws-efa-k8s-device-plugin.yaml
```

### 6.2 创建必要资源

#### 1. 创建命名空间

```bash
kubectl create namespace sglang-inference
```

#### 2. 创建 HuggingFace Token Secret

```bash
kubectl create secret generic hf-token-secret \
  --from-literal=token=hf_your_token_here \
  -n sglang-inference
```

#### 3. 创建存储资源

```bash
# 创建 StorageClass
kubectl apply -f fsx-lustre-storageclass.yaml

# 创建 PVC
kubectl apply -f huggingface-cache-pvc.yaml -n sglang-inference

# 验证 PVC 状态
kubectl get pvc -n sglang-inference
```

### 6.3 部署 SGLang 服务

```bash
# 部署多节点 SGLang
kubectl apply -f sglang-multi-node.yaml -n sglang-inference

# 查看部署状态
kubectl get leaderworkerset -n sglang-inference

# 查看 Pod 状态
kubectl get pods -n sglang-inference -w

# 查看 Leader 节点日志
kubectl logs -l role=leader -n sglang-inference -f
```

### 6.4 验证部署

#### 1. 检查 Pod 状态

```bash
# 所有 Pod 应该处于 Running 状态
kubectl get pods -n sglang-inference

# 输出示例：
# NAME                              READY   STATUS    RESTARTS   AGE
# sglang-multi-nodes-0              1/1     Running   0          30m
# sglang-multi-nodes-1              1/1     Running   0          30m
```

#### 2. 检查日志

```bash
# 查看 Leader 节点日志，确认模型加载成功
kubectl logs sglang-multi-nodes-0 -n sglang-inference | tail -50

# 应该看到类似输出：
# INFO: Server started at http://0.0.0.0:30000
# INFO: Model loaded successfully
# INFO: Ready to serve requests
```

#### 3. 端口转发进行本地测试

```bash
# 转发到本地
kubectl port-forward service/sglang-service 30000:30000 -n sglang-inference
```

#### 4. 发送测试请求

```bash
# 健康检查
curl http://localhost:30000/health

# 生成测试
curl http://localhost:30000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3-30B-A3B-Thinking-2507",
    "prompt": "What is machine learning?",
    "max_tokens": 100,
    "temperature": 0.7
  }'

# OpenAI 兼容 API 测试
curl http://localhost:30000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3-30B-A3B-Thinking-2507",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Explain quantum computing in simple terms."}
    ],
    "max_tokens": 200
  }'
```

#### 5. 使用 Python 客户端测试

```python
# test_sglang.py
import openai

# 设置 API 端点
openai.api_base = "http://localhost:30000/v1"
openai.api_key = "dummy"  # SGLang 不需要真实的 API key

# 发送请求
response = openai.ChatCompletion.create(
    model="Qwen/Qwen3-30B-A3B-Thinking-2507",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What are the benefits of cloud computing?"}
    ],
    max_tokens=150,
    temperature=0.8
)

print(response.choices[0].message.content)
```

---

## 7. 性能优化与最佳实践

### 7.1 实例类型选择

| 实例类型 | GPU | VRAM | 推荐 TP | 适合模型大小 | 价格/小时（参考）* |
|---------|-----|------|---------|-------------|----------------|
| ml.p5.48xlarge | 8x H100 | 640GB | 8 | 70B - 405B | ~$98 |
| ml.p4d.24xlarge | 8x A100 | 320GB | 8 | 30B - 180B | ~$33 |
| ml.g5.48xlarge | 8x A10G | 192GB | 8 | 7B - 70B | ~$16 |
| ml.p4de.24xlarge | 8x A100 | 640GB | 8 | 70B - 405B | ~$41 |

**价格说明**：上述价格仅供参考，实际价格会因地区、预留实例、Savings Plans 等因素而异。请访问 [AWS SageMaker 定价页面](https://aws.amazon.com/sagemaker/pricing/) 获取最新价格信息。

**选择建议**：
- **超大模型（>100B）**: ml.p5.48xlarge（H100）或 ml.p4de.24xlarge（A100 80GB）
- **大模型（30B-100B）**: ml.p4d.24xlarge（A100 40GB）
- **中型模型（7B-30B）**: ml.g5.48xlarge（A10G）
- **开发测试**: ml.g5.12xlarge（4x A10G）

### 7.2 SGLang 特定优化

#### 1. 内存优化

```bash
# KV Cache 内存分配
--mem-fraction-static 0.85  # 为 KV Cache 分配 85% 的 GPU 内存

# Chunked Prefill（减少 prefill 阶段的内存峰值）
--chunked-prefill-size 8192  # 将 prefill 分块处理
```

#### 2. 批处理优化

```bash
# 最大并发请求数
--max-running-requests 256

# 最大批处理大小
--max-total-tokens 8192

# 调度策略
--schedule-policy lpm  # Longest Prefix Match
```

#### 3. 量化支持（减少内存占用）

```bash
# FP8 量化
--quantization fp8

# INT4 量化（需要模型支持）
--quantization awq
# 或
--quantization gptq
```

#### 4. Prefill-Decode 解耦（高级）

SGLang v0.5.8 支持 PD（Prefill-Decode）分离模式，将计算密集型的 prefill 阶段和内存密集型的 decode 阶段分开处理，以提高整体吞吐量。

**关键参数说明**：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--disaggregation-mode` | 分离模式：`prefill` 或 `decode` | null |
| `--disaggregation-transfer-backend` | KV Cache 传输后端 | `mooncake` |
| `--disaggregation-bootstrap-port` | Prefill 服务器的 bootstrap 端口 | `8998` |
| `--disaggregation-ib-device` | InfiniBand 设备（用于 RDMA） | 自动检测 |

**Prefill 节点配置**：
```bash
python3 -m sglang.launch_server \
  --model-path <model> \
  --tp 4 \
  --host 0.0.0.0 \
  --port 30000 \
  --disaggregation-mode prefill \
  --disaggregation-transfer-backend mooncake \
  --disaggregation-bootstrap-port 8998 \
  --chunked-prefill-size 4096 \
  --trust-remote-code
```

**Decode 节点配置**：
```bash
python3 -m sglang.launch_server \
  --model-path <model> \
  --tp 4 \
  --host 0.0.0.0 \
  --port 30001 \
  --disaggregation-mode decode \
  --disaggregation-transfer-backend mooncake \
  --disable-radix-cache \
  --trust-remote-code
```

**Router 配置**（需要安装 `sglang-router` 包）：
```bash
# 安装 sglang-router
pip install sglang-router

# 启动 router (PD 分离模式)
python3 -m sglang_router.launch_router \
  --host 0.0.0.0 \
  --port 8000 \
  --pd-disaggregation \
  --prefill http://<prefill-host>:30000 \
  --decode http://<decode-host>:30001
```

**传输后端说明**：
- **mooncake**（默认）：支持 RDMA 和 TCP，适用于高性能 InfiniBand 环境和普通以太网
- **nixl**：NVIDIA 的 KV 传输库，需要 RDMA 支持

**注意**：
- 对于没有 EFA/InfiniBand 的实例（如 g5 系列），Mooncake 会自动回退到 TCP 传输
- 可以通过设置环境变量 `MOONCAKE_TRANSPORT=tcp` 强制使用 TCP 传输
- EFA 支持需要安装 EFA device plugin 并在实例类型上启用 EFA

**EFA/RDMA 支持的实例类型**：
| 实例类型 | Nitro 版本 | RDMA Read | RDMA Write |
|---------|-----------|-----------|------------|
| g5.12xlarge | v3 | ❌ | ❌ |
| g6.12xlarge | v4 | ✅ | ✅ |
| g6e.12xlarge | v4 | ✅ | ✅ |
| p4d.24xlarge | v4 | ✅ | ❌ |
| p5.48xlarge | v4 | ✅ | ✅ |

**完整部署示例**：参见 `sglang-pd-disaggregated-qwen3-4b.yaml` 文件，提供了在 2x ml.g6.12xlarge 上部署 PD 分离模式的完整配置 (**已验证可用** - 2026-01-31)

**已知问题与解决方案**：

1. **EFA device plugin 崩溃 (SIGSEGV)**

   **现象**：EFA device plugin pod 出现 CrashLoopBackOff，日志显示：
   ```
   SIGSEGV: segmentation violation
   github.com/aws/efa-k8s-device-plugin/pkg/efa_topology._Cfunc_efa_gpu_topology_init()
   ```
   `vpc.amazonaws.com/efa` 资源显示为 `<none>`

   **原因**：EFA device plugin v0.5.6 在 GPU 拓扑初始化时存在 bug，影响 g6.12xlarge、g6.48xlarge 等实例类型

   **解决方案 A - 升级 EFA device plugin（推荐）**：
   ```bash
   # 1. 检查当前版本
   kubectl get daemonset -n kube-system hyperpod-dependencies-aws-efa-k8s-device-plugin -o jsonpath='{.spec.template.spec.containers[0].image}'

   # 2. 升级到 v0.5.13（已修复此问题）
   kubectl set image daemonset/hyperpod-dependencies-aws-efa-k8s-device-plugin \
     -n kube-system \
     aws-efa-k8s-device-plugin=602401143452.dkr.ecr.us-west-2.amazonaws.com/eks/aws-efa-k8s-device-plugin:v0.5.13

   # 3. 验证升级成功
   kubectl get pods -n kube-system | grep efa
   # 应显示 Running 状态

   # 4. 验证 EFA 资源可用
   kubectl get nodes -o custom-columns='NAME:.metadata.name,EFA:.status.allocatable.vpc\.amazonaws\.com/efa'
   # 应显示 EFA: 1 或更多
   ```

   **解决方案 B - 使用 TCP 传输模式（备选）**：
   如果无法升级 EFA device plugin，可以移除 EFA 资源请求，使用 TCP 传输：
   ```yaml
   # 移除 resources 中的 EFA 请求
   # limits:
   #   vpc.amazonaws.com/efa: 1  # 删除此行

   # 设置环境变量使用 TCP
   env:
   - name: MOONCAKE_TRANSPORT
     value: "tcp"
   ```

2. **Router tokenizer 加载警告**
   - 现象：Router 日志显示 "Failed to load tokenizer" 错误
   - 原因：Router 尝试从 HuggingFace 加载本地路径的模型
   - 影响：**无影响** - Router 仍可正常工作，因为 tokenization 由 worker 处理
   - 无需处理，可忽略此警告

3. **EFA device plugin 版本兼容性参考**

   | 版本 | g6.12xlarge | g6.48xlarge | p5.48xlarge | 说明 |
   |------|-------------|-------------|-------------|------|
   | v0.5.6 | ❌ 崩溃 | ❌ 崩溃 | 未测试 | HyperPod 默认版本 |
   | v0.5.13 | ✅ 正常 | ✅ 正常 | ✅ 正常 | **推荐版本** |

### 7.3 网络优化

#### EFA 配置（推荐用于 P5/P4 实例）

```yaml
env:
# 启用 RDMA
- name: NCCL_IB_DISABLE
  value: "0"

# GPU Direct RDMA
- name: NCCL_NET_GDR_LEVEL
  value: "5"

# 使用 EFA
- name: FI_PROVIDER
  value: "efa"

- name: FI_EFA_USE_DEVICE_RDMA
  value: "1"

# EFA 相关优化
- name: FI_EFA_FORK_SAFE
  value: "1"

- name: NCCL_PROTO
  value: "simple"
```

### 7.4 推荐的模型配置

**参数说明**：以下配置使用 `--tp` 参数指定 Tensor Parallelism 大小。`--tp` 和 `--tp-size` 是等价的参数别名，两者可以互换使用。

#### Qwen3-30B-A3B（单节点）
```bash
python3 -m sglang.launch_server \
  --model-path Qwen/Qwen3-30B-A3B-Thinking-2507 \
  --tp 8 \
  --mem-fraction-static 0.85 \
  --chunked-prefill-size 8192 \
  --context-length 32768 \
  --max-running-requests 256 \
  --trust-remote-code
```

#### Llama 3.1 405B（多节点）
```bash
# Leader (Rank 0)
python3 -m sglang.launch_server \
  --model-path meta-llama/Meta-Llama-3.1-405B-Instruct \
  --tp 16 \
  --dist-init-addr $LEADER_IP:20000 \
  --nnodes 4 \
  --node-rank 0 \
  --quantization fp8 \
  --mem-fraction-static 0.90

# Worker (Rank 1, 2, 3)
python3 -m sglang.launch_server \
  --model-path meta-llama/Meta-Llama-3.1-405B-Instruct \
  --tp 16 \
  --dist-init-addr $LEADER_IP:20000 \
  --nnodes 4 \
  --node-rank <1|2|3> \
  --quantization fp8 \
  --mem-fraction-static 0.90
```

#### DeepSeek R1 671B（多节点，MoE 模型）
```bash
# 需要 8 节点，每节点 8x H100
# DeepSeek R1 是 MoE (Mixture of Experts) 模型，需要使用 Expert Parallelism
python3 -m sglang.launch_server \
  --model-path deepseek-ai/DeepSeek-R1 \
  --tp 16 \
  --ep-size 8 \
  --dist-init-addr $LEADER_IP:20000 \
  --nnodes 8 \
  --node-rank <0-7> \
  --quantization fp8
```

**注意**：`--ep-size` (Expert Parallelism) 仅适用于 MoE 模型（如 DeepSeek V3/R1、Mixtral）。对于标准 Transformer 模型（如 Llama），仅需使用 `--tp` 参数。

### 7.5 自动扩展配置

使用 KEDA 实现基于负载的自动扩展：

```yaml
# keda-scaledobject.yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: sglang-autoscaler
  namespace: sglang-inference
spec:
  scaleTargetRef:
    kind: LeaderWorkerSet
    name: sglang-multi-nodes
  minReplicaCount: 1
  maxReplicaCount: 4
  pollingInterval: 30
  cooldownPeriod: 300
  triggers:
  - type: prometheus
    metadata:
      serverAddress: http://prometheus:9090
      metricName: sglang_queue_size
      threshold: '50'
      query: |
        sum(sglang_running_requests) by (pod)
```

---

## 8. 监控和可观测性

### 8.1 Prometheus 集成

SGLang 原生支持 Prometheus 指标导出。

#### 启用指标

```bash
python3 -m sglang.launch_server \
  --model-path <model> \
  --enable-metrics \
  --metrics-port 9090
```

#### 关键指标

| 指标名称 | 类型 | 说明 |
|---------|------|------|
| `sglang_prompt_tokens_total` | Counter | 总 prompt tokens 数 |
| `sglang_generation_tokens_total` | Counter | 总生成 tokens 数 |
| `sglang_time_to_first_token_seconds` | Histogram | 首 token 延迟 |
| `sglang_time_per_output_token_seconds` | Histogram | 每个输出 token 的时间 |
| `sglang_e2e_request_latency_seconds` | Histogram | 端到端请求延迟 |
| `sglang_running_requests` | Gauge | 当前运行中的请求数 |
| `sglang_waiting_requests` | Gauge | 等待队列中的请求数 |
| `sglang_gpu_cache_usage_perc` | Gauge | GPU 缓存使用率 |

#### Prometheus 配置

```yaml
# prometheus-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-config
  namespace: sglang-inference
data:
  prometheus.yml: |
    global:
      scrape_interval: 15s
      evaluation_interval: 15s

    scrape_configs:
    - job_name: 'sglang'
      kubernetes_sd_configs:
      - role: pod
        namespaces:
          names:
          - sglang-inference
      relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
        action: replace
        target_label: __metrics_path__
        regex: (.+)
      - source_labels: [__address__, __meta_kubernetes_pod_annotation_prometheus_io_port]
        action: replace
        regex: ([^:]+)(?::\d+)?;(\d+)
        replacement: $1:$2
        target_label: __address__
```

### 8.2 Grafana 仪表板

创建 Grafana 仪表板监控关键指标：

**推荐面板**：
1. **吞吐量**：每秒处理的 tokens 数
2. **延迟**：P50/P95/P99 延迟分布
3. **GPU 利用率**：各 GPU 的使用率
4. **队列长度**：等待和运行中的请求数
5. **缓存命中率**：KV Cache 命中率
6. **错误率**：失败请求的比例

### 8.3 CloudWatch 集成

HyperPod 原生集成 CloudWatch Container Insights：

```bash
# 安装 CloudWatch Agent
kubectl apply -f https://raw.githubusercontent.com/aws-samples/amazon-cloudwatch-container-insights/latest/k8s-deployment-manifest-templates/deployment-mode/daemonset/container-insights-monitoring/quickstart/cwagent-fluentd-quickstart.yaml
```

### 8.4 日志聚合

使用 FluentBit 收集日志到 CloudWatch Logs：

```yaml
# fluent-bit-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluent-bit-config
  namespace: amazon-cloudwatch
data:
  fluent-bit.conf: |
    [SERVICE]
        Flush         5
        Log_Level     info
        Daemon        off
        Parsers_File  parsers.conf

    [INPUT]
        Name              tail
        Path              /var/log/containers/sglang*.log
        Parser            docker
        Tag               sglang.*
        Refresh_Interval  5
        Mem_Buf_Limit     50MB

    [OUTPUT]
        Name                cloudwatch_logs
        Match               sglang.*
        region              us-west-2
        log_group_name      /aws/hyperpod/sglang
        log_stream_prefix   inference-
        auto_create_group   true
```

---

## 9. 故障排查

### 9.1 常见问题

#### 问题 1：模型下载超时

**症状**：
```
ERROR: Failed to download model from HuggingFace
Connection timeout after 1800 seconds
```

**解决方案**：
1. 增加健康检查初始延迟：
```yaml
livenessProbe:
  initialDelaySeconds: 3600  # 增加到 60 分钟
```

2. 使用 InitContainer 预下载：
```yaml
initContainers:
- name: model-downloader
  # ... (参见第 5.5 节)
```

3. 使用镜像站点（中国区）：
```yaml
env:
- name: HF_ENDPOINT
  value: "https://hf-mirror.com"
```

#### 问题 2：GPU OOM（内存不足）

**症状**：
```
CUDA out of memory. Tried to allocate 2.0 GiB
```

**解决方案**：
1. 减少 KV Cache 内存分配：
```bash
--mem-fraction-static 0.75  # 从 0.85 降低到 0.75
```

2. 启用量化：
```bash
--quantization fp8
```

3. 减少并发请求数：
```bash
--max-running-requests 128  # 从 256 降低到 128
```

4. 使用更大的实例或更多节点

#### 问题 3：节点间通信失败

**症状**：
```
NCCL error: unhandled system error
Failed to connect to peer node
```

**解决方案**：
1. 检查网络配置：
```bash
# 确保节点间可以互相访问
kubectl exec -it sglang-multi-nodes-0 -- ping sglang-multi-nodes-1
```

2. 检查安全组规则（允许所有端口通信）

3. 验证 EFA 配置：
```bash
kubectl describe pod sglang-multi-nodes-0 | grep efa
```

4. 检查 NCCL 日志：
```yaml
env:
- name: NCCL_DEBUG
  value: "INFO"  # 或 "TRACE" 获取更详细日志
```

#### 问题 4：HuggingFace Token 权限不足

**症状**：
```
401 Client Error: Unauthorized for url
```

**解决方案**：
1. 确认 Token 有效：
```bash
# 在本地测试
export HF_TOKEN=hf_xxx
huggingface-cli whoami
```

2. 确认已接受模型许可协议（门控模型）

3. 重新创建 Secret：
```bash
kubectl delete secret hf-token-secret -n sglang-inference
kubectl create secret generic hf-token-secret \
  --from-literal=token=hf_new_token \
  -n sglang-inference
```

#### 问题 5：Pod 一直处于 Pending 状态

**症状**：
```
kubectl get pods
NAME                      READY   STATUS    RESTARTS   AGE
sglang-multi-nodes-0      0/1     Pending   0          10m
```

**解决方案**：
1. 检查原因：
```bash
kubectl describe pod sglang-multi-nodes-0 -n sglang-inference
```

2. 常见原因和解决方案：
   - **资源不足**：扩展集群或减少资源请求
   - **PVC 未绑定**：检查 PVC 状态
   ```bash
   kubectl get pvc -n sglang-inference
   ```
   - **节点选择器不匹配**：调整 nodeSelector 或标签
   - **污点/容忍度问题**：添加正确的 tolerations

#### 问题 6：推理速度慢

**症状**：
- Time to First Token (TTFT) > 5 秒
- Tokens per Second (TPS) < 50

**解决方案**：
1. 启用 Chunked Prefill：
```bash
--chunked-prefill-size 8192
```

2. 调整批处理参数：
```bash
--max-running-requests 256
--max-total-tokens 8192
```

3. 检查 GPU 利用率：
```bash
kubectl exec -it sglang-multi-nodes-0 -- nvidia-smi
```

4. 验证 EFA 是否正常工作（多节点）：
```bash
# 检查 EFA 设备
kubectl exec -it sglang-multi-nodes-0 -- fi_info
```

### 9.2 调试命令集合

```bash
# 查看所有资源
kubectl get all -n sglang-inference

# 查看详细事件
kubectl get events -n sglang-inference --sort-by='.lastTimestamp'

# 查看 Pod 日志
kubectl logs -f sglang-multi-nodes-0 -n sglang-inference

# 进入容器调试
kubectl exec -it sglang-multi-nodes-0 -n sglang-inference -- /bin/bash

# 查看资源使用
kubectl top pods -n sglang-inference
kubectl top nodes

# 查看 GPU 使用情况
kubectl exec -it sglang-multi-nodes-0 -n sglang-inference -- nvidia-smi

# 测试网络连通性
kubectl exec -it sglang-multi-nodes-0 -n sglang-inference -- \
  curl http://sglang-service:30000/health

# 查看 Prometheus 指标
kubectl port-forward service/sglang-service 9090:9090 -n sglang-inference
curl http://localhost:9090/metrics
```

### 9.3 性能基准测试

使用官方工具进行基准测试：

```bash
# 安装 SGLang 客户端
pip install "sglang[all]"

# 运行基准测试
python -m sglang.bench_serving \
  --backend sglang \
  --host localhost \
  --port 30000 \
  --dataset-name random \
  --random-input 1024 \
  --random-output 256 \
  --num-prompts 100 \
  --request-rate 10
```

**关键指标**：
- **Throughput**: 应 > 1000 tokens/s（单节点 70B 模型）
- **TTFT (P50)**: 应 < 2s
- **TPOT (P50)**: 应 < 50ms（每个输出 token 的时间）

---

## 10. 实际案例研究

### 10.1 Osmosis AI 案例

**公司**: Osmosis AI (Gulp.ai)
**应用场景**: LLM 微调期间的模型推理
**技术栈**: AWS HyperPod + EKS + Ray + SGLang + VeRL

#### 架构

```
┌──────────────────────────────────────────────┐
│       AWS SageMaker HyperPod                 │
│  (集群编排、自动故障恢复、资源优化)           │
└──────────────┬───────────────────────────────┘
               │
┌──────────────▼───────────────────────────────┐
│         Amazon EKS Cluster                   │
│  - GPU 节点管理                              │
│  - 网络配置 (VPC, Subnet, Security Groups)   │
│  - 存储集成 (FSx for Lustre, EBS)           │
└──────────────┬───────────────────────────────┘
               │
┌──────────────▼───────────────────────────────┐
│         Ray Cluster                          │
│  - 分布式任务调度                            │
│  - 资源分配                                  │
│  - 工作节点管理                              │
└──────────────┬───────────────────────────────┘
               │
    ┌──────────┴──────────┐
    │                     │
┌───▼─────────┐    ┌─────▼──────────┐
│   SGLang    │    │   VeRL         │
│  (推理引擎)  │◄───┤  (强化学习框架) │
│             │    │                │
└─────────────┘    └────────────────┘
```

#### 关键成果

1. **性能提升**
   - GPU 利用率从 60% 提升到 85%+
   - 训练时间减少 40%
   - Token 生成速度提升 2-3x

2. **成本优化**
   - 通过动态批处理降低计算成本 35%
   - 统一训练/推理基础设施，减少资源浪费

3. **运营效率**
   - HyperPod 自动故障恢复，减少人工干预
   - Docker 化部署确保跨环境一致性

#### 技术挑战与解决方案

| 挑战 | 解决方案 |
|------|---------|
| **CUDA/PyTorch 兼容性** | 构建自定义 Docker 镜像，固定依赖版本 |
| **多节点通信** | 配置 EFA，优化 NCCL 参数 |
| **GPU 利用率低** | 使用 SGLang 的动态批处理和 RadixAttention |
| **模型加载慢** | 使用 FSx for Lustre 共享存储 |

### 10.2 其他参考案例

#### 案例：Thomson Reuters
- **场景**: 大规模知识图谱问答
- **配置**: 4 节点 ml.p4d.24xlarge (32x A100)
- **模型**: 自定义 175B 参数模型
- **效果**: 支持 1000+ QPS，P99 延迟 < 3s

#### 案例：Perplexity AI
- **场景**: 实时搜索增强生成
- **配置**: 动态扩展 2-8 节点
- **模型**: Llama 70B + 自定义检索系统
- **效果**: 支持百万级 DAU，平均响应时间 < 2s

---

## 11. 参考资源

### 11.1 官方文档

#### AWS 文档
- [HyperPod 模型部署指南](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-model-deployment.html)
- [HyperPod EKS 编排](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-eks.html)
- [HyperPod 推理可观测性](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-model-deployment-observability.html)
- [HyperPod 任务治理](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-task-governance.html)

#### SGLang 文档
- [SGLang GitHub 仓库](https://github.com/sgl-project/sglang)
- [SGLang Transformers Backend 集成](https://huggingface.co/blog/transformers-backend-sglang)
- [SGLang 文档](https://sgl-project.github.io/)

#### Kubernetes 文档
- [LeaderWorkerSet API](https://lws.sigs.k8s.io/)
- [Kubernetes GPU 调度](https://kubernetes.io/docs/tasks/manage-gpus/scheduling-gpus/)
- [KEDA 自动扩展](https://keda.sh/)

### 11.2 博客文章

- [HyperPod 支持 Multi-Instance GPU](https://aws.amazon.com/blogs/machine-learning/hyperpod-now-supports-multi-instance-gpu-to-maximize-gpu-utilization-for-generative-ai-tasks/)
- [使用 HyperPod CLI 和 SDK 训练部署模型](https://aws.amazon.com/blogs/machine-learning/train-and-deploy-models-on-amazon-sagemaker-hyperpod-using-the-new-hyperpod-cli-and-sdk/)
- [EKS 支持 HyperPod 介绍](https://aws.amazon.com/blogs/machine-learning/introducing-amazon-eks-support-in-amazon-sagemaker-hyperpod/)
- [Kubernetes LLM 推理架构概述](https://rudeigerc.dev/posts/kubernetes-based-llm-inference-architectures-an-overview/)

### 11.3 开源项目

- [HyperPod 集群设置资产](https://github.com/aws/sagemaker-hyperpod-cluster-setup)
- [Awesome 分布式训练](https://github.com/aws-samples/awsome-distributed-training)
- [aws-do-hyperpod](https://github.com/aws-samples/aws-do-hyperpod)
- [SGLang 项目](https://github.com/sgl-project/sglang)
- [LeaderWorkerSet](https://github.com/kubernetes-sigs/lws)

### 11.4 案例研究

- [Osmosis AI 案例](https://www.tech42consulting.com/case-studies/case-study-osmosis-ai-fine-tuning)
- [Alibaba Cloud 多节点部署](https://www.alibabacloud.com/help/en/ack/cloud-native-ai-suite/user-guide/deploy-multi-machine-distributed-inference-services)
- [NVIDIA Dynamo on AKS](https://blog.aks.azure.com/2025/10/24/dynamo-on-aks)

### 11.5 视频教程

- [AWS re:Invent - HyperPod 深度解析](https://www.youtube.com/results?search_query=aws+hyperpod)
- [HyperPod Workshop](https://catalog.workshops.aws/sagemaker-hyperpod/)

### 11.6 社区资源

- [AWS ML Community](https://github.com/aws/amazon-sagemaker-examples)
- [HuggingFace Forums](https://discuss.huggingface.co/)
- [SGLang GitHub Discussions](https://github.com/sgl-project/sglang/discussions)

---

## 附录 A：完整的配置文件模板

### A.1 生产环境完整配置

建议的文件结构：
```
deployment/
├── 01-namespace.yaml
├── 02-secrets.yaml
├── 03-storage-class.yaml
├── 04-pvc.yaml
├── 05-sglang-deployment.yaml
├── 06-service.yaml
├── 07-ingress.yaml
├── 08-monitoring.yaml
└── 09-autoscaling.yaml
```

### A.2 常用模型配置速查表

| 模型 | Model ID | 最小 GPU | 推荐实例 | TP | 节点数 |
|------|----------|---------|---------|----|----|
| Llama 3.2 1B | `meta-llama/Llama-3.2-1B-Instruct` | 1x A10G | ml.g5.2xlarge | 1 | 1 |
| Llama 3.1 8B | `meta-llama/Llama-3.1-8B-Instruct` | 1x A10G | ml.g5.2xlarge | 1 | 1 |
| Llama 3.1 70B | `meta-llama/Llama-3.1-70B-Instruct` | 8x A100 | ml.p4d.24xlarge | 8 | 1 |
| Llama 3.1 405B | `meta-llama/Meta-Llama-3.1-405B-Instruct` | 16x H100 | ml.p5.48xlarge | 16 | 2 |
| DeepSeek R1 32B | `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B` | 4x A100 | ml.p4d.24xlarge | 4 | 1 |
| DeepSeek R1 671B | `deepseek-ai/DeepSeek-R1` | 64x H100 | ml.p5.48xlarge | 16 | 8 |
| Qwen 2.5 72B | `Qwen/Qwen2.5-72B-Instruct` | 8x A100 | ml.p4d.24xlarge | 8 | 1 |

---

## 附录 B：术语表

| 术语 | 全称 | 说明 |
|------|------|------|
| **HyperPod** | Amazon SageMaker HyperPod | AWS 托管的大规模训练和推理服务 |
| **EKS** | Elastic Kubernetes Service | AWS 托管的 Kubernetes 服务 |
| **SGLang** | Structured Generation Language | 高性能 LLM 推理框架 |
| **TP** | Tensor Parallelism | 张量并行，将模型层切分到多个 GPU |
| **EP** | Expert Parallelism | 专家并行，用于 MoE 模型 |
| **DP** | Data Parallelism | 数据并行，将批次分配到多个 GPU |
| **EFA** | Elastic Fabric Adapter | AWS 高性能网络接口 |
| **RDMA** | Remote Direct Memory Access | 远程直接内存访问 |
| **NCCL** | NVIDIA Collective Communication Library | NVIDIA 集合通信库 |
| **MIG** | Multi-Instance GPU | GPU 分区技术 |
| **KV Cache** | Key-Value Cache | 注意力机制的键值缓存 |
| **TTFT** | Time to First Token | 首 token 延迟 |
| **TPOT** | Time per Output Token | 每个输出 token 的时间 |
| **TPS** | Tokens per Second | 每秒生成的 tokens 数 |
| **QPS** | Queries per Second | 每秒查询数 |

---

## 附录 C：故障排查清单

### 部署前检查
- [ ] HyperPod EKS 集群已创建并正常运行
- [ ] LeaderWorkerSet CRD 已安装
- [ ] GPU Operator 已安装并正常工作
- [ ] EFA Device Plugin 已安装（如使用高性能实例）
- [ ] FSx for Lustre 或其他共享存储已配置
- [ ] HuggingFace Token Secret 已创建
- [ ] 网络配置正确（VPC、安全组、子网）
- [ ] IAM 角色和权限已配置

### 部署后检查
- [ ] 所有 Pod 处于 Running 状态
- [ ] Leader 节点日志显示模型加载成功
- [ ] `/health` 端点返回 200 OK
- [ ] 可以成功发送测试推理请求
- [ ] Prometheus 指标可以正常抓取
- [ ] GPU 利用率正常（nvidia-smi）
- [ ] 节点间网络通信正常（多节点）

### 性能检查
- [ ] TTFT < 5s（P95）
- [ ] TPOT < 100ms（P95）
- [ ] GPU 利用率 > 70%
- [ ] 内存使用稳定，无 OOM
- [ ] 请求队列长度合理
- [ ] 错误率 < 1%

---

## 附录 D：联系和支持

### AWS 支持
- **AWS Support Center**: https://console.aws.amazon.com/support/
- **HyperPod 论坛**: https://repost.aws/tags/TAnYfKYd-eSE-s4QOZFG-ayw/amazon-sage-maker-hyper-pod

### 社区支持
- **SGLang GitHub Issues**: https://github.com/sgl-project/sglang/issues
- **SGLang Discussions**: https://github.com/sgl-project/sglang/discussions

### 技术咨询
如需技术咨询或架构设计支持，可联系：
- AWS Solutions Architects
- AWS Professional Services
- AWS Partner Network (APN) 合作伙伴

---

## 文档变更历史

| 版本 | 日期 | 变更说明 | 作者 |
|------|------|---------|------|
| v1.5 | 2026-01-31 | **EFA device plugin 升级指南**：记录 v0.5.6 崩溃问题及升级到 v0.5.13 的解决方案，添加版本兼容性表格 | 技术调研团队 |
| v1.4 | 2026-01-31 | **验证 PD 分离部署**：在 2x ml.g6.12xlarge 上成功验证 Qwen3-4B 模型 PD 分离部署，添加已知问题与解决方案 | 技术调研团队 |
| v1.3 | 2026-01-31 | 修正 Router 配置使用 sglang-router 包，添加 EFA/RDMA 实例类型支持表，更新部署示例 | 技术调研团队 |
| v1.2 | 2026-01-31 | 升级 SGLang 版本到 v0.5.8，完善 PD 分离模式配置说明，添加 mooncake 传输后端详细参数 | 技术调研团队 |
| v1.1 | 2026-01-30 | 修正参数说明、添加端口和价格说明、完善 MoE 模型配置注释 | 技术调研团队 |
| v1.0 | 2026-01-30 | 初始版本发布 | 技术调研团队 |

---

**最后更新**: 2026-01-31
**文档维护**: 技术调研团队
**许可协议**: CC BY-SA 4.0

---

© 2026 技术调研团队。本文档遵循 CC BY-SA 4.0 许可协议。
