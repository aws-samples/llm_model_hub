# HyperPod EKS API 参考文档

本文档提供 HyperPod EKS 集群创建的完整 API 参考和 boto3 代码示例。

## 目录

1. [架构概述](#架构概述)
2. [前提条件](#前提条件)
3. [EKS 集群创建 API](#eks-集群创建-api)
4. [HyperPod 集群创建 API](#hyperpod-集群创建-api)
5. [完整代码示例](#完整代码示例)
6. [高级配置](#高级配置)

---

## 架构概述

HyperPod EKS 架构包含三个主要 VPC：

1. **Amazon EKS VPC** - 托管 EKS 控制平面
2. **HyperPod VPC** - 托管 HyperPod 计算节点
3. **用户 VPC** - 托管 FSx for Lustre、S3 等资源

跨账户 ENI 桥接 HyperPod 计算实例与其他 AWS 服务之间的通信。

### 关键特性

- **深度健康检查**: GPU 和 Trainium 实例的压力测试
- **自动节点恢复**: 轻量级健康检查和自动替换/重启
- **作业自动恢复**: 节点替换后自动重启训练作业
- **连续供应**: 后台自动配置剩余容量
- **Spot 实例支持**: 节省高达 90% 的成本

---

## 前提条件

### Kubernetes 版本要求

支持的版本: **1.28 - 1.33** (推荐 1.33)

### EKS 集群认证模式

必须设置为以下之一:
- `API`
- `API_AND_CONFIG_MAP` (推荐)

### VPC CNI 插件版本

需要 **1.18.3** 或更高版本

### 必需的 IAM 角色

1. EKS 集群角色
2. HyperPod 执行角色
3. 集群自动扩缩容角色 (可选)

---

## EKS 集群创建 API

### boto3 创建 EKS 集群

```python
import boto3

eks_client = boto3.client('eks', region_name='us-west-2')

response = eks_client.create_cluster(
    name='my-eks-cluster',
    version='1.3',
    roleArn='arn:aws:iam::123456789012:role/eks-cluster-role',
    resourcesVpcConfig={
        'subnetIds': [
            'subnet-0123456789abcdef0',
            'subnet-0123456789abcdef1'
        ],
        'securityGroupIds': [
            'sg-0123456789abcdef0'
        ],
        'endpointPublicAccess': True,
        'endpointPrivateAccess': True
    },
    accessConfig={
        'authenticationMode': 'API_AND_CONFIG_MAP',
        'bootstrapClusterCreatorAdminPermissions': True
    },
    logging={
        'clusterLogging': [
            {
                'types': ['api', 'audit', 'authenticator', 'controllerManager', 'scheduler'],
                'enabled': True
            }
        ]
    },
    tags={
        'Purpose': 'HyperPod',
        'ManagedBy': 'boto3'
    }
)

print(f"Cluster ARN: {response['cluster']['arn']}")
```

### EKS CreateCluster API 参数

| 参数 | 类型 | 必需 | 说明 |
|-----|------|------|-----|
| name | string | 是 | 集群名称 (1-100字符) |
| version | string | 否 | Kubernetes 版本 |
| roleArn | string | 是 | EKS 集群 IAM 角色 ARN |
| resourcesVpcConfig | object | 是 | VPC 配置 |
| accessConfig | object | 否 | 访问配置 |
| logging | object | 否 | 日志配置 |
| encryptionConfig | array | 否 | 加密配置 |
| tags | object | 否 | 标签 |

### resourcesVpcConfig 参数

| 参数 | 类型 | 说明 |
|-----|------|-----|
| subnetIds | array | 子网 ID 列表 (至少2个) |
| securityGroupIds | array | 安全组 ID 列表 |
| endpointPublicAccess | boolean | 启用公共端点访问 |
| endpointPrivateAccess | boolean | 启用私有端点访问 |
| publicAccessCidrs | array | 允许公共访问的 CIDR |

---

## HyperPod 集群创建 API

### boto3 创建 HyperPod 集群

```python
import boto3

sagemaker_client = boto3.client('sagemaker', region_name='us-west-2')

response = sagemaker_client.create_cluster(
    ClusterName='my-hyperpod-cluster',
    Orchestrator={
        'Eks': {
            'ClusterArn': 'arn:aws:eks:us-west-2:123456789012:cluster/my-eks-cluster',
            'KubernetesConfig': {
                'Labels': {
                    'environment': 'production'
                }
            }
        }
    },
    InstanceGroups=[
        {
            'InstanceGroupName': 'gpu-workers',
            'InstanceType': 'ml.p4d.24xlarge',
            'InstanceCount': 2,
            'MinInstanceCount': 1,
            'LifeCycleConfig': {
                'SourceS3Uri': 's3://my-bucket/lifecycle-scripts/',
                'OnCreate': 'on_create.sh'
            },
            'ExecutionRole': 'arn:aws:iam::123456789012:role/hyperpod-role',
            'ThreadsPerCore': 1,
            'CapacityRequirements': {
                'OnDemand': {}
            },
            'OnStartDeepHealthChecks': [
                'InstanceStress',
                'InstanceConnectivity'
            ],
            'KubernetesConfig': {
                'Labels': {
                    'workload-type': 'training',
                    'gpu-type': 'a100'
                },
                'Taints': [
                    {
                        'Key': 'nvidia.com/gpu',
                        'Value': 'true',
                        'Effect': 'NoSchedule'
                    }
                ]
            }
        }
    ],
    VpcConfig={
        'SecurityGroupIds': ['sg-xxx'],
        'Subnets': ['subnet-xxx', 'subnet-yyy']
    },
    NodeRecovery='Automatic',
    NodeProvisioningMode='Continuous',
    Tags=[
        {'Key': 'Environment', 'Value': 'Production'}
    ]
)

print(f"Cluster ARN: {response['ClusterArn']}")
```

### HyperPod CreateCluster API 参数

| 参数 | 类型 | 必需 | 说明 |
|-----|------|------|-----|
| ClusterName | string | 是 | 集群名称 |
| Orchestrator | object | 是 | 编排器配置 (EKS) |
| InstanceGroups | array | 是 | 实例组配置列表 |
| VpcConfig | object | 是 | VPC 配置 |
| NodeRecovery | string | 否 | 节点恢复模式 |
| NodeProvisioningMode | string | 否 | 节点供应模式 |
| Tags | array | 否 | 标签列表 |

### InstanceGroups 参数

| 参数 | 类型 | 必需 | 说明 |
|-----|------|------|-----|
| InstanceGroupName | string | 是 | 实例组名称 |
| InstanceType | string | 是 | ML 实例类型 |
| InstanceCount | integer | 是 | 实例数量 |
| MinInstanceCount | integer | 否 | 最小实例数 (连续供应) |
| LifeCycleConfig | object | 是 | 生命周期配置 |
| ExecutionRole | string | 是 | 执行角色 ARN |
| ThreadsPerCore | integer | 否 | 每核心线程数 |
| CapacityRequirements | object | 否 | 容量要求 (OnDemand/Spot) |
| OnStartDeepHealthChecks | array | 否 | 深度健康检查类型 |
| KubernetesConfig | object | 否 | Kubernetes 标签和污点 |

---

## 完整代码示例

### 从零创建完整堆栈

```python
import boto3
import time
import json
from botocore.exceptions import ClientError

class HyperPodEKSDeployment:
    def __init__(self, region='us-west-2'):
        self.region = region
        self.eks_client = boto3.client('eks', region_name=region)
        self.sagemaker_client = boto3.client('sagemaker', region_name=region)
        self.iam_client = boto3.client('iam', region_name=region)
        self.ec2_client = boto3.client('ec2', region_name=region)
        self.s3_client = boto3.client('s3', region_name=region)

    # ===== 步骤 1: 创建 IAM 角色 =====

    def create_eks_cluster_role(self, role_name='MyEKSClusterRole'):
        """创建 EKS 集群 IAM 角色"""
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {
                    "Service": "eks.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }]
        }

        try:
            # 创建角色
            response = self.iam_client.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description='EKS Cluster Role for HyperPod'
            )

            # 附加必需的策略
            self.iam_client.attach_role_policy(
                RoleName=role_name,
                PolicyArn='arn:aws:iam::aws:policy/AmazonEKSClusterPolicy'
            )

            print(f"✓ EKS 集群角色已创建: {response['Role']['Arn']}")
            return response['Role']['Arn']

        except ClientError as e:
            if e.response['Error']['Code'] == 'EntityAlreadyExists':
                role = self.iam_client.get_role(RoleName=role_name)
                print(f"✓ EKS 集群角色已存在: {role['Role']['Arn']}")
                return role['Role']['Arn']
            raise

    def create_hyperpod_execution_role(self, role_name='MyHyperPodExecutionRole'):
        """创建 HyperPod 执行角色"""
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {
                    "Service": "sagemaker.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }]
        }

        try:
            # 创建角色
            response = self.iam_client.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description='SageMaker HyperPod Execution Role'
            )

            # 附加必需的策略
            self.iam_client.attach_role_policy(
                RoleName=role_name,
                PolicyArn='arn:aws:iam::aws:policy/AmazonSageMakerClusterInstanceRolePolicy'
            )

            print(f"✓ HyperPod 执行角色已创建: {response['Role']['Arn']}")

            # 等待角色传播
            time.sleep(10)

            return response['Role']['Arn']

        except ClientError as e:
            if e.response['Error']['Code'] == 'EntityAlreadyExists':
                role = self.iam_client.get_role(RoleName=role_name)
                print(f"✓ HyperPod 执行角色已存在: {role['Role']['Arn']}")
                return role['Role']['Arn']
            raise

    # ===== 步骤 2: 创建 EKS 集群 =====

    def create_eks_cluster(
        self,
        cluster_name,
        role_arn,
        subnet_ids,
        security_group_ids=None,
        kubernetes_version='1.31'
    ):
        """创建 Amazon EKS 集群"""

        cluster_config = {
            'name': cluster_name,
            'version': kubernetes_version,
            'roleArn': role_arn,
            'resourcesVpcConfig': {
                'subnetIds': subnet_ids,
                'endpointPublicAccess': True,
                'endpointPrivateAccess': True
            },
            # 集群认证模式 - HyperPod 需要 API 或 API_AND_CONFIG_MAP
            'accessConfig': {
                'authenticationMode': 'API_AND_CONFIG_MAP',
                'bootstrapClusterCreatorAdminPermissions': True
            },
            # 启用日志
            'logging': {
                'clusterLogging': [{
                    'types': ['api', 'audit', 'authenticator', 'controllerManager', 'scheduler'],
                    'enabled': True
                }]
            },
            'tags': {
                'Purpose': 'HyperPod',
                'ManagedBy': 'Boto3'
            }
        }

        # 如果提供了安全组，则添加
        if security_group_ids:
            cluster_config['resourcesVpcConfig']['securityGroupIds'] = security_group_ids

        try:
            print(f"开始创建 EKS 集群: {cluster_name}")
            response = self.eks_client.create_cluster(**cluster_config)

            print(f"✓ EKS 集群创建请求已提交")
            print(f"  集群名称: {response['cluster']['name']}")
            print(f"  集群 ARN: {response['cluster']['arn']}")

            return response['cluster']

        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceInUseException':
                print(f"✓ EKS 集群已存在: {cluster_name}")
                return self.eks_client.describe_cluster(name=cluster_name)['cluster']
            raise

    def wait_for_eks_cluster_active(self, cluster_name, max_wait_time=1800):
        """等待 EKS 集群变为 ACTIVE 状态"""
        print(f"等待 EKS 集群 '{cluster_name}' 变为 ACTIVE 状态...")
        start_time = time.time()

        while time.time() - start_time < max_wait_time:
            try:
                response = self.eks_client.describe_cluster(name=cluster_name)
                status = response['cluster']['status']

                print(f"  当前状态: {status}")

                if status == 'ACTIVE':
                    print(f"✓ EKS 集群已就绪！")
                    return response['cluster']
                elif status in ['FAILED', 'DELETING']:
                    raise Exception(f"EKS 集群创建失败，状态: {status}")

                time.sleep(30)

            except ClientError as e:
                print(f"检查集群状态时出错: {e}")
                time.sleep(30)

        raise TimeoutError(f"等待 EKS 集群就绪超时")

    # ===== 步骤 3: 准备生命周期脚本 =====

    def upload_lifecycle_script(self, bucket_name, script_content=None):
        """上传生命周期脚本到 S3"""

        # 默认的生命周期脚本
        if script_content is None:
            script_content = """#!/bin/bash
set -ex

# 更新系统包
echo "Updating system packages..."
sudo yum update -y || sudo apt-get update -y

# 安装必要的工具
echo "Installing required tools..."
sudo yum install -y jq wget || sudo apt-get install -y jq wget

# 配置 EFA（Elastic Fabric Adapter）
echo "Configuring EFA..."
# EFA 配置命令...

# 配置 kubectl
echo "Configuring kubectl..."
# kubectl 配置命令...

echo "Lifecycle script completed successfully!"
"""

        script_key = 'lifecycle-scripts/on_create.sh'

        try:
            self.s3_client.put_object(
                Bucket=bucket_name,
                Key=script_key,
                Body=script_content.encode('utf-8'),
                ContentType='text/x-shellscript'
            )

            s3_uri = f"s3://{bucket_name}/lifecycle-scripts/"
            print(f"✓ 生命周期脚本已上传到: {s3_uri}")
            return s3_uri

        except ClientError as e:
            print(f"上传脚本失败: {e}")
            raise

    # ===== 步骤 4: 创建 HyperPod 集群 =====

    def create_hyperpod_cluster(
        self,
        cluster_name,
        eks_cluster_arn,
        execution_role_arn,
        subnet_ids,
        security_group_ids,
        lifecycle_script_s3_uri,
        instance_groups_config
    ):
        """创建 SageMaker HyperPod 集群"""

        config = {
            'ClusterName': cluster_name,

            # 指定 EKS 编排器
            'Orchestrator': {
                'Eks': {
                    'ClusterArn': eks_cluster_arn
                }
            },

            # 实例组配置
            'InstanceGroups': instance_groups_config,

            # VPC 配置（必须与 EKS 集群在同一 VPC）
            'VpcConfig': {
                'SecurityGroupIds': security_group_ids,
                'Subnets': subnet_ids
            },

            # 启用自动节点恢复
            'NodeRecovery': 'Automatic',

            # 连续供应模式（仅 EKS 支持）
            'NodeProvisioningMode': 'Continuous',

            # 标签
            'Tags': [
                {'Key': 'Environment', 'Value': 'Production'},
                {'Key': 'ManagedBy', 'Value': 'Boto3'}
            ]
        }

        try:
            print(f"开始创建 HyperPod 集群: {cluster_name}")
            response = self.sagemaker_client.create_cluster(**config)

            print(f"✓ HyperPod 集群创建请求已提交")
            print(f"  集群 ARN: {response['ClusterArn']}")

            return response

        except ClientError as e:
            print(f"创建 HyperPod 集群失败: {e}")
            raise

    def wait_for_hyperpod_cluster_ready(self, cluster_name, max_wait_time=3600):
        """等待 HyperPod 集群就绪"""
        print(f"等待 HyperPod 集群 '{cluster_name}' 变为 InService 状态...")
        start_time = time.time()

        while time.time() - start_time < max_wait_time:
            try:
                response = self.sagemaker_client.describe_cluster(
                    ClusterName=cluster_name
                )

                status = response['ClusterStatus']
                print(f"  当前状态: {status}")

                if status == 'InService':
                    print(f"✓ HyperPod 集群已就绪！")
                    return response
                elif status in ['Failed', 'RollbackFailed']:
                    failure_msg = response.get('FailureMessage', 'Unknown error')
                    raise Exception(f"HyperPod 集群创建失败: {failure_msg}")

                time.sleep(60)

            except ClientError as e:
                print(f"检查集群状态时出错: {e}")
                time.sleep(60)

        raise TimeoutError("等待 HyperPod 集群就绪超时")


# ===== 使用示例 =====

def main():
    # 配置参数
    REGION = 'us-west-2'
    EKS_CLUSTER_NAME = 'my-hyperpod-eks-cluster'
    HYPERPOD_CLUSTER_NAME = 'my-hyperpod-cluster'

    # 替换为您的实际子网 ID（必须是私有子网）
    SUBNET_IDS = [
        'subnet-0123456789abcdef0',
        'subnet-0123456789abcdef1'
    ]

    # 替换为您的安全组 ID
    SECURITY_GROUP_IDS = ['sg-0123456789abcdef0']

    # S3 存储桶（用于生命周期脚本）
    S3_BUCKET = 'my-hyperpod-scripts-bucket'

    # 初始化部署器
    deployer = HyperPodEKSDeployment(region=REGION)

    try:
        # 步骤 1: 创建 IAM 角色
        print("\n===== 步骤 1: 创建 IAM 角色 =====")
        eks_role_arn = deployer.create_eks_cluster_role()
        hyperpod_role_arn = deployer.create_hyperpod_execution_role()

        # 步骤 2: 创建 EKS 集群
        print("\n===== 步骤 2: 创建 EKS 集群 =====")
        eks_cluster = deployer.create_eks_cluster(
            cluster_name=EKS_CLUSTER_NAME,
            role_arn=eks_role_arn,
            subnet_ids=SUBNET_IDS,
            security_group_ids=SECURITY_GROUP_IDS,
            kubernetes_version='1.34'
        )

        # 等待 EKS 集群就绪
        eks_cluster = deployer.wait_for_eks_cluster_active(EKS_CLUSTER_NAME)
        eks_cluster_arn = eks_cluster['arn']

        # 步骤 3: 上传生命周期脚本
        print("\n===== 步骤 3: 上传生命周期脚本 =====")
        lifecycle_script_uri = deployer.upload_lifecycle_script(S3_BUCKET)

        # 步骤 4: 创建 HyperPod 集群
        print("\n===== 步骤 4: 创建 HyperPod 集群 =====")

        # 定义实例组配置
        instance_groups = [
            {
                'InstanceGroupName': 'worker-group-gpu',
                'InstanceType': 'ml.p4d.24xlarge',
                'InstanceCount': 2,
                'LifeCycleConfig': {
                    'SourceS3Uri': lifecycle_script_uri,
                    'OnCreate': 'on_create.sh'
                },
                'ExecutionRole': hyperpod_role_arn,
                'ThreadsPerCore': 1,
                'OnStartDeepHealthChecks': [
                    'InstanceStress',
                    'InstanceConnectivity'
                ],
                'KubernetesConfig': {
                    'Labels': {
                        'workload-type': 'training',
                        'gpu-type': 'a100'
                    }
                }
            }
        ]

        hyperpod_response = deployer.create_hyperpod_cluster(
            cluster_name=HYPERPOD_CLUSTER_NAME,
            eks_cluster_arn=eks_cluster_arn,
            execution_role_arn=hyperpod_role_arn,
            subnet_ids=SUBNET_IDS,
            security_group_ids=SECURITY_GROUP_IDS,
            lifecycle_script_s3_uri=lifecycle_script_uri,
            instance_groups_config=instance_groups
        )

        # 等待 HyperPod 集群就绪
        hyperpod_cluster = deployer.wait_for_hyperpod_cluster_ready(HYPERPOD_CLUSTER_NAME)

        print("\n===== 部署完成！=====")
        print(f"EKS 集群 ARN: {eks_cluster_arn}")
        print(f"HyperPod 集群 ARN: {hyperpod_response['ClusterArn']}")

    except Exception as e:
        print(f"\n❌ 部署失败: {str(e)}")
        raise


if __name__ == "__main__":
    main()
```

---

## 高级配置

### 1. Spot 实例配置

```python
instance_group_spot = {
    'InstanceGroupName': 'spot-gpu-group',
    'InstanceType': 'ml.g5.12xlarge',
    'InstanceCount': 4,
    'MinInstanceCount': 2,
    'CapacityRequirements': {
        'Spot': {}
    },
    # ... 其他配置
}
```

### 2. GPU 分区 (MIG) 配置

```python
instance_group_mig = {
    'InstanceGroupName': 'mig-gpu-group',
    'InstanceType': 'ml.p4d.24xlarge',
    'InstanceCount': 2,
    'KubernetesConfig': {
        'Labels': {
            'nvidia.com/mig.config': 'all-3g.40gb'
        }
    },
    # ... 其他配置
}
```

### 3. Karpenter 自动扩缩容配置

```python
cluster_config = {
    'ClusterName': 'my-autoscaling-cluster',
    # ... 基本配置
    'AutoScaling': {
        'AutoScalerType': 'Karpenter',
        'Mode': 'Enabled'
    },
    'ClusterRole': 'arn:aws:iam::xxx:role/autoscaling-role'
}
```

### 4. Restricted Instance Group (RIG) 配置

```python
rig_config = {
    'RestrictedInstanceGroups': [{
        'InstanceGroupName': 'rig-group',
        'InstanceType': 'ml.p4d.24xlarge',
        'InstanceCount': 4,
        'EnvironmentConfig': {
            'FSxLustreConfig': {
                'PerUnitStorageThroughput': 250,
                'SizeInGiB': 14400
            }
        },
        'ExecutionRole': execution_role_arn
    }]
}
```

---

## Mountpoint for Amazon S3 配置

HyperPod EKS 集群支持通过 Mountpoint for Amazon S3 CSI 驱动将 S3 存储桶挂载为文件系统。

### 方法一: 使用 S3 CSI 驱动 (推荐用于 EKS)

```bash
# 安装 S3 CSI 驱动
export EKS_CLUSTER_NAME="my-eks-cluster"
export AWS_REGION="us-west-2"
export S3_BUCKET_NAME="my-bucket-name"

bash lifecycle_scripts/setup_s3_mountpoint_csi.sh
```

### 方法二: 使用生命周期脚本直接挂载

在创建 HyperPod 集群时，设置环境变量启用 S3 Mountpoint：

```python
instance_group = {
    'InstanceGroupName': 'gpu-workers',
    'InstanceType': 'ml.g5.xlarge',
    'InstanceCount': 2,
    'LifeCycleConfig': {
        'SourceS3Uri': 's3://my-bucket/lifecycle-scripts/',
        'OnCreate': 'on_create.sh'
    },
    'ExecutionRole': execution_role_arn,
    # S3 Mountpoint 通过环境变量配置
    # 在 on_create.sh 中设置:
    # export S3_BUCKET_NAME="my-data-bucket"
    # export S3_MOUNT_PATH="/mnt/s3"
}
```

### S3 CSI 驱动 PersistentVolume 配置

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: s3-pv
spec:
  capacity:
    storage: 1200Gi  # S3 忽略此值，但 K8s 需要
  accessModes:
    - ReadWriteMany
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  csi:
    driver: s3.csi.aws.com
    volumeHandle: s3-csi-driver-volume
    volumeAttributes:
      bucketName: my-bucket-name
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: s3-pvc
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: ""
  resources:
    requests:
      storage: 1200Gi
  volumeName: s3-pv
```

### S3 访问 IAM 策略

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "MountpointFullBucketAccess",
            "Effect": "Allow",
            "Action": ["s3:ListBucket"],
            "Resource": ["arn:aws:s3:::<BUCKET_NAME>"]
        },
        {
            "Sid": "MountpointFullObjectAccess",
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:AbortMultipartUpload",
                "s3:DeleteObject"
            ],
            "Resource": ["arn:aws:s3:::<BUCKET_NAME>/*"]
        }
    ]
}
```

### 参考链接

- [Mountpoint for Amazon S3 CSI Driver](https://docs.aws.amazon.com/eks/latest/userguide/s3-csi.html)
- [HyperPod EKS Storage Workshop](https://catalog.workshops.aws/sagemaker-hyperpod-eks/en-US/01-cluster/09-s3-mountpoint)

---

## 常用 AWS CLI 命令

```bash
# 列出所有 HyperPod 集群
aws sagemaker list-clusters

# 描述特定集群
aws sagemaker describe-cluster --cluster-name my-cluster

# 列出集群节点
aws sagemaker list-cluster-nodes --cluster-name my-cluster

# 删除集群
aws sagemaker delete-cluster --cluster-name my-cluster

# 更新集群
aws sagemaker update-cluster --cluster-name my-cluster --cli-input-json file://update_config.json
```

---

## 错误处理

| 错误代码 | 原因 | 解决方案 |
|---------|------|---------|
| ResourceInUseException | 资源已存在 | 使用现有资源或删除后重试 |
| InvalidParameterException | 参数无效 | 检查参数格式和值 |
| ResourceLimitExceededException | 达到配额限制 | 申请增加配额 |
| ValidationException | 验证失败 | 检查配置是否符合要求 |

---

## 参考链接

- [SageMaker HyperPod 文档](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod.html)
- [EKS 用户指南](https://docs.aws.amazon.com/eks/latest/userguide/)
- [boto3 SageMaker API](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sagemaker.html)
- [boto3 EKS API](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/eks.html)
