# HyperPod EKS 部署指南

本目录包含使用 boto3 SDK 创建完整的 Amazon EKS 和 SageMaker HyperPod EKS 集群的代码和文档。

## 目录结构

```
hyperpod_docs/
├── README.md                           # 本文档
├── hyperpod_eks_deployment.py          # 主要的 boto3 SDK 部署代码
├── hyperpod_inference_manager.py       # Kubernetes Python SDK 推理管理
├── reference.md                        # API 参考文档
├── inference_reference.md              # 模型推理部署指南
├── s3accesspolicy.json                 # S3 Mountpoint 访问策略示例
├── lifecycle_scripts/                  # 生命周期脚本
│   ├── on_create.sh                   # 节点创建时执行的脚本 (支持 S3 Mountpoint)
│   ├── setup_s3_mountpoint_csi.sh     # S3 CSI 驱动安装脚本
│   └── install_rig_dependencies.sh    # RIG 依赖安装脚本
└── config_examples/                    # 配置示例
    ├── cluster_config.json            # 完整集群配置示例
    └── autoscaling_config.json        # 自动扩缩容配置示例
```

## 快速开始

### 前提条件

1. **AWS 账户配置**
   - 具有适当 IAM 权限的 AWS 账户
   - 配置好的 AWS CLI (`aws configure`)
   - Python 3.8+ 和 boto3 库

2. **安装依赖**
   ```bash
   pip install boto3
   ```

3. **验证权限**
   - VPC 创建和管理权限
   - EKS 集群创建权限
   - SageMaker HyperPod 权限
   - IAM 角色创建权限
   - S3 存储桶访问权限

### 基本使用

```python
from hyperpod_eks_deployment import (
    HyperPodEKSDeployment,
    InstanceGroupConfig,
    VPCConfig,
    EKSConfig,
    HyperPodConfig
)

# 初始化部署管理器
deployer = HyperPodEKSDeployment(region='us-west-2')

# 定义实例组
instance_groups = [
    InstanceGroupConfig(
        name='gpu-workers',
        instance_type='ml.g5.xlarge',
        instance_count=2,
        min_instance_count=1,
        use_spot=False,
        kubernetes_labels={
            'workload-type': 'training',
            'gpu-type': 'a10g'
        }
    )
]

# 部署完整堆栈
results = deployer.deploy_full_stack(
    cluster_name='my-hyperpod-cluster',
    eks_cluster_name='my-eks-cluster',
    instance_groups=instance_groups,
    enable_autoscaling=False
)

print(f"EKS Cluster ARN: {results['eks_cluster']['arn']}")
print(f"HyperPod Cluster ARN: {results['hyperpod_cluster']['ClusterArn']}")
```

## 核心功能

### 1. VPC 基础设施创建

自动创建包含以下资源的 VPC：
- VPC (默认 CIDR: 10.0.0.0/16)
- 公有子网 (用于 NAT Gateway 和负载均衡器)
- 私有子网 (用于 EKS 节点和 HyperPod 实例)
- Internet Gateway
- NAT Gateway (每个可用区一个，高可用配置)
- 路由表和路由规则

```python
from hyperpod_eks_deployment import HyperPodEKSDeployment, VPCConfig

deployer = HyperPodEKSDeployment(region='us-west-2')

vpc_config = VPCConfig(
    vpc_cidr="10.0.0.0/16",
    public_subnet_cidrs=["10.0.1.0/24", "10.0.2.0/24"],
    private_subnet_cidrs=["10.0.10.0/24", "10.0.20.0/24"]
)

vpc_info = deployer.create_vpc(vpc_config, 'my-cluster')
```

### 2. IAM 角色创建

创建以下 IAM 角色：

- **EKS 集群角色**: 用于 EKS 控制平面
- **HyperPod 执行角色**: 用于 HyperPod 节点实例
- **自动扩缩容角色**: 用于 Karpenter 自动扩缩容 (可选)

```python
# 创建 EKS 集群角色
eks_role_arn = deployer.create_eks_cluster_role('my-eks-role')

# 创建 HyperPod 执行角色
hyperpod_role_arn = deployer.create_hyperpod_execution_role(
    'my-hyperpod-role',
    s3_bucket_name='my-lifecycle-bucket'
)

# 创建自动扩缩容角色 (可选)
autoscaling_role_arn = deployer.create_cluster_autoscaling_role('my-autoscaling-role')
```

### 3. EKS 集群创建

创建具有以下配置的 EKS 集群：
- Kubernetes 版本 1.28-1.34 (推荐 1.34)
- 认证模式: API_AND_CONFIG_MAP (HyperPod 必需)
- 启用公共和私有端点访问
- CloudWatch 日志记录

```python
from hyperpod_eks_deployment import EKSConfig

eks_config = EKSConfig(
    kubernetes_version='1.34',
    endpoint_public_access=True,
    endpoint_private_access=True,
    authentication_mode='API_AND_CONFIG_MAP',
    enable_logging=True
)

eks_cluster = deployer.create_eks_cluster(
    cluster_name='my-eks-cluster',
    role_arn=eks_role_arn,
    subnet_ids=private_subnet_ids,
    security_group_ids=security_group_ids,
    config=eks_config
)

# 等待集群就绪
eks_cluster = deployer.wait_for_eks_cluster('my-eks-cluster')
```

### 4. HyperPod 集群创建

创建 HyperPod 集群并关联到 EKS：

```python
from hyperpod_eks_deployment import HyperPodConfig, InstanceGroupConfig

hyperpod_config = HyperPodConfig(
    node_recovery='Automatic',
    node_provisioning_mode='Continuous',
    enable_deep_health_checks=True
)

instance_groups = [
    InstanceGroupConfig(
        name='gpu-workers',
        instance_type='ml.p4d.24xlarge',
        instance_count=2,
        min_instance_count=1,
        use_spot=False,
        kubernetes_labels={'workload-type': 'training'}
    ),
    InstanceGroupConfig(
        name='spot-workers',
        instance_type='ml.g5.12xlarge',
        instance_count=4,
        min_instance_count=2,
        use_spot=True,
        kubernetes_labels={'workload-type': 'batch'}
    )
]

hyperpod_response = deployer.create_hyperpod_cluster(
    cluster_name='my-hyperpod-cluster',
    eks_cluster_arn=eks_cluster['arn'],
    execution_role_arn=hyperpod_role_arn,
    subnet_ids=private_subnet_ids,
    security_group_ids=security_group_ids,
    lifecycle_script_s3_uri='s3://my-bucket/lifecycle-scripts/',
    instance_groups=instance_groups,
    config=hyperpod_config
)
```

## 高级配置

### Spot 实例支持

HyperPod 支持使用 Spot 实例以节省成本：

```python
spot_instance_group = InstanceGroupConfig(
    name='spot-gpu-workers',
    instance_type='ml.g5.12xlarge',
    instance_count=4,
    min_instance_count=2,
    use_spot=True,  # 启用 Spot 实例
    kubernetes_labels={
        'node-type': 'spot',
        'gpu-type': 'a10g'
    }
)
```

### Karpenter 自动扩缩容

启用基于 Karpenter 的自动扩缩容：

```python
# 创建自动扩缩容角色
autoscaling_role_arn = deployer.create_cluster_autoscaling_role('my-autoscaling-role')

# 部署时启用自动扩缩容
results = deployer.deploy_full_stack(
    cluster_name='my-cluster',
    eks_cluster_name='my-eks',
    instance_groups=instance_groups,
    enable_autoscaling=True  # 启用 Karpenter
)
```

### GPU 分区 (MIG)

对于支持 MIG 的 GPU 实例 (如 A100)，可以配置 GPU 分区：

```json
{
    "KubernetesConfig": {
        "Labels": {
            "nvidia.com/mig.config": "all-3g.40gb"
        }
    }
}
```

### 深度健康检查

启用深度健康检查以确保节点健康：

```python
hyperpod_config = HyperPodConfig(
    enable_deep_health_checks=True,
    deep_health_check_types=['InstanceStress', 'InstanceConnectivity']
)
```

## 生命周期脚本

### on_create.sh

节点创建时执行的脚本，包含以下配置：
- containerd 数据根目录配置 (支持 AL2 和 AL2023)
- **S3 Mountpoint 自动安装和挂载** (可选，通过环境变量启用)
- 系统性能调优

**启用 S3 Mountpoint:**

```bash
# 设置环境变量后，on_create.sh 会自动安装和挂载 S3
export S3_BUCKET_NAME="my-bucket-name"
export S3_MOUNT_PATH="/mnt/s3"  # 可选，默认 /mnt/s3
```

### setup_s3_mountpoint_csi.sh

用于在 EKS 集群上安装 Mountpoint for Amazon S3 CSI 驱动的脚本。

**使用方法:**

```bash
export EKS_CLUSTER_NAME="my-eks-cluster"
export AWS_REGION="us-west-2"
export S3_BUCKET_NAME="my-bucket-name"

bash setup_s3_mountpoint_csi.sh
```

**功能:**
- 创建 S3 访问 IAM 策略
- 创建 IRSA (IAM Roles for Service Accounts)
- 安装 S3 CSI 驱动 EKS Add-on
- 创建 PersistentVolume 和 PersistentVolumeClaim

**在 Pod 中使用 S3 存储:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: s3-app
spec:
  containers:
    - name: app
      image: my-image
      volumeMounts:
        - name: s3-storage
          mountPath: /mnt/s3
  volumes:
    - name: s3-storage
      persistentVolumeClaim:
        claimName: s3-pvc
```

### install_rig_dependencies.sh

用于 Restricted Instance Group (RIG) 的依赖安装脚本。

## 常用实例类型

| 实例类型 | GPU | 显存 | 用途 |
|---------|-----|------|------|
| ml.p5.48xlarge | 8x H100 | 80GB | 最大规模训练 |
| ml.p4d.24xlarge | 8x A100 | 40GB | 大规模训练 |
| ml.p4de.24xlarge | 8x A100 | 80GB | 大模型训练 |
| ml.g5.48xlarge | 8x A10G | 24GB | 中等规模训练 |
| ml.g5.12xlarge | 4x A10G | 24GB | 通用训练 |
| ml.g5.xlarge | 1x A10G | 24GB | 开发测试 |
| ml.trn1.32xlarge | 16x Trainium | - | Trainium 训练 |
| ml.c5.18xlarge | - | - | CPU 计算 |

## 故障排除

### 常见问题

1. **EKS 集群创建失败**
   - 检查 VPC 子网配置
   - 确保 IAM 角色权限正确
   - 验证安全组规则

2. **HyperPod 集群无法连接到 EKS**
   - 确保 HyperPod 集群与 EKS 集群在同一 VPC
   - 检查安全组是否允许必要的通信
   - 验证 EKS 认证模式为 API_AND_CONFIG_MAP

3. **节点健康检查失败**
   - 查看 CloudWatch 日志
   - 检查生命周期脚本执行状态
   - 验证网络连接

### 日志查看

```bash
# 查看 HyperPod 集群状态
aws sagemaker describe-cluster --cluster-name my-cluster

# 查看集群节点
aws sagemaker list-cluster-nodes --cluster-name my-cluster

# 查看 CloudWatch 日志
aws logs get-log-events --log-group-name /aws/sagemaker/Clusters/my-cluster
```

## 清理资源

```python
# 删除 HyperPod 集群
aws sagemaker delete-cluster --cluster-name my-cluster

# 删除 EKS 集群
aws eks delete-cluster --name my-eks-cluster

# 删除 VPC 及相关资源 (需要按依赖顺序删除)
```

## 模型推理部署

HyperPod EKS 集群支持部署机器学习模型进行推理。详细指南请参阅 [inference_reference.md](inference_reference.md)。

### 快速概览

HyperPod 推理平台支持：

- **多种部署接口**: kubectl、Python SDK、SageMaker Studio UI、HyperPod CLI
- **JumpStart 模型**: 一键部署 SageMaker JumpStart 预训练模型
- **自定义模型**: 从 S3 或 FSx 部署微调模型
- **自动扩缩容**: 基于 CloudWatch、Prometheus 和 KEDA 的动态资源分配
- **KV 缓存**: 分层缓存和智能路由优化 LLM 推理性能

### 部署 JumpStart 模型示例

```yaml
apiVersion: inference.sagemaker.aws.amazon.com/v1
kind: JumpStartModel
metadata:
  name: deepseek-qwen-endpoint
  namespace: default
spec:
  sageMakerEndpoint:
    name: deepseek-qwen-endpoint
  model:
    modelHubName: SageMakerPublicHub
    modelId: deepseek-llm-r1-distill-qwen-1-5b
    modelVersion: "2.0.4"
  server:
    instanceType: ml.g5.xlarge
  metrics:
    enabled: true
```

### 部署自定义模型示例

```yaml
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
```

更多详细内容请参阅 [模型推理部署指南](inference_reference.md)。

### Python SDK 推理管理

使用 `hyperpod_inference_manager.py` 模块通过 Kubernetes Python 客户端管理推理资源：

```python
from hyperpod_inference_manager import HyperPodInferenceManager

manager = HyperPodInferenceManager()

# 部署 JumpStart 模型
manager.deploy_jumpstart_model(
    name="my-model",
    model_id="deepseek-llm-r1-distill-qwen-1-5b",
    model_version="2.0.4",
    instance_type="ml.g5.xlarge"
)

# 部署自定义模型
manager.deploy_custom_model(
    name="my-custom-model",
    model_name="llama-3-8b",
    instance_type="ml.g5.24xlarge",
    s3_bucket="my-bucket",
    model_location="models/llama-3-8b"
)

# 列出模型
models = manager.list_jumpstart_models()

# 监听变更
for event in manager.watch_jumpstart_models():
    print(f"{event['type']}: {event['object']['metadata']['name']}")
```

命令行使用：

```bash
# 列出推理资源
python hyperpod_inference_manager.py list

# 部署模型
python hyperpod_inference_manager.py deploy-jumpstart my-model \
    --model-id deepseek-llm-r1-distill-qwen-1-5b \
    --model-version 2.0.4

# 删除模型
python hyperpod_inference_manager.py delete my-model --type jumpstart
```

详细 API 文档请参阅 [inference_reference.md](inference_reference.md#python-sdk-推理资源管理)。

## 参考文档

- [Amazon SageMaker HyperPod 官方文档](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod.html)
- [Amazon EKS 用户指南](https://docs.aws.amazon.com/eks/latest/userguide/)
- [HyperPod EKS 入门](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-eks-prerequisites.html)
- [HyperPod 模型部署文档](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-model-deployment.html)
- [AWSome Distributed Training GitHub](https://github.com/aws-samples/awsome-distributed-training)

## 版本兼容性

- Python: 3.8+
- boto3: 1.28+
- Kubernetes: 1.28-1.34
- AWS CLI: 2.x
