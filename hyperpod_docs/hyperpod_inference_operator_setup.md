# HyperPod Inference Operator Setup Guide

This guide provides comprehensive instructions for setting up the HyperPod Inference Operator on Amazon EKS clusters. The setup enables deployment and management of machine learning inference endpoints on SageMaker HyperPod clusters.

## Overview

The HyperPod Inference Operator is a Kubernetes operator that enables:
- Deployment of JumpStart models from SageMaker Model Hub
- Deployment of custom models from S3 or FSx storage
- Auto-scaling based on CloudWatch metrics via KEDA
- Integration with AWS Load Balancer Controller for ingress management
- KV cache and intelligent routing for optimized inference

## Prerequisites

Before starting the setup, ensure you have:

1. **AWS Account** with Administrator privileges
2. **HyperPod Cluster** created with EKS orchestration
3. **Command Line Tools** installed:
   - `kubectl` - Kubernetes CLI
   - `helm` - Kubernetes package manager
   - `eksctl` - EKS CLI tool
   - `aws` - AWS CLI (configured with credentials)

4. **EKS Cluster Admin Access**:
   - Go to Amazon EKS Console
   - Select your cluster
   - Under **Access** tab, verify IAM Access Entries
   - Ensure your IAM principal has `AmazonEKSClusterAdminPolicy`

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     HyperPod EKS Cluster                            │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                  hyperpod-inference-system                    │   │
│  │  ┌─────────────────────┐  ┌─────────────────────────────┐    │   │
│  │  │ Inference Operator  │  │ KEDA (Auto-scaler)          │    │   │
│  │  │ Controller          │  │                             │    │   │
│  │  └─────────────────────┘  └─────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                  kube-system                                  │   │
│  │  ┌─────────────────────┐  ┌─────────────────────────────┐    │   │
│  │  │ AWS Load Balancer   │  │ S3 CSI Driver               │    │   │
│  │  │ Controller          │  │                             │    │   │
│  │  └─────────────────────┘  └─────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                  Model Deployments (default/custom ns)        │   │
│  │  ┌─────────────────────┐  ┌─────────────────────────────┐    │   │
│  │  │ JumpStartModel      │  │ InferenceEndpointConfig     │    │   │
│  │  │ (Pre-trained)       │  │ (Custom Models)             │    │   │
│  │  └─────────────────────┘  └─────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Using Python Script

```python
from hyperpod_inference_operator_setup import HyperPodInferenceOperatorSetup

# Initialize setup manager
setup = HyperPodInferenceOperatorSetup(
    hyperpod_cluster_name="my-hyperpod-cluster",
    region="us-west-2",
    s3_bucket_name="my-tls-cert-bucket"
)

# Run full setup
results = setup.run_full_setup()

print(f"Setup completed: {results['success']}")
print(f"Roles created: {results['roles']}")
```

### Using Command Line

```bash
# Full setup
python hyperpod_inference_operator_setup.py \
    --hyperpod-cluster my-hyperpod-cluster \
    --region us-west-2 \
    --s3-bucket my-tls-cert-bucket

# IAM-only setup (for restricted environments)
python hyperpod_inference_operator_setup.py \
    --hyperpod-cluster my-hyperpod-cluster \
    --region us-west-2 \
    --s3-bucket my-tls-cert-bucket \
    --iam-only

# With additional options
python hyperpod_inference_operator_setup.py \
    --hyperpod-cluster my-hyperpod-cluster \
    --region us-west-2 \
    --s3-bucket my-tls-cert-bucket \
    --install-fsx-csi \
    --enable-jumpstart-gated \
    --skip-test-deployment
```

## Step-by-Step Manual Setup

If you prefer to run the setup steps manually, follow this guide.

### Step 1: Configure Environment Variables

```bash
# Set your cluster and region
export HYPERPOD_CLUSTER_NAME="my-hyperpod-cluster"
export REGION="us-west-2"
export BUCKET_NAME="my-tls-cert-bucket"

# Get EKS cluster name from HyperPod cluster
export EKS_CLUSTER_NAME=$(aws --region $REGION sagemaker describe-cluster \
    --cluster-name $HYPERPOD_CLUSTER_NAME \
    --query 'Orchestrator.Eks.ClusterArn' --output text | cut -d'/' -f2)

# Get account ID and OIDC ID
export ACCOUNT_ID=$(aws --region $REGION sts get-caller-identity --query 'Account' --output text)
export OIDC_ID=$(aws --region $REGION eks describe-cluster --name $EKS_CLUSTER_NAME \
    --query "cluster.identity.oidc.issuer" --output text | cut -d '/' -f 5)

# Derived resource names
export LB_CONTROLLER_POLICY_NAME="AWSLoadBalancerControllerIAMPolicy-$HYPERPOD_CLUSTER_NAME"
export LB_CONTROLLER_ROLE_NAME="aws-load-balancer-controller-$HYPERPOD_CLUSTER_NAME"
export S3_MOUNT_ACCESS_POLICY_NAME="S3MountpointAccessPolicy-$HYPERPOD_CLUSTER_NAME"
export S3_CSI_ROLE_NAME="SM_HP_S3_CSI_ROLE-$HYPERPOD_CLUSTER_NAME"
export KEDA_OPERATOR_POLICY_NAME="KedaOperatorPolicy-$HYPERPOD_CLUSTER_NAME"
export KEDA_OPERATOR_ROLE_NAME="keda-operator-role-$HYPERPOD_CLUSTER_NAME"
export HYPERPOD_INFERENCE_ROLE_NAME="HyperpodInferenceRole-$HYPERPOD_CLUSTER_NAME"
export HYPERPOD_INFERENCE_SA_NAME="hyperpod-inference-operator-controller"
export HYPERPOD_INFERENCE_SA_NAMESPACE="hyperpod-inference-system"
```

### Step 2: Update Kubeconfig

```bash
# Update kubeconfig for EKS cluster
aws eks update-kubeconfig --name $EKS_CLUSTER_NAME --region $REGION

# Verify connectivity
kubectl get pods --all-namespaces
```

### Step 3: Associate OIDC Provider

```bash
eksctl utils associate-iam-oidc-provider \
    --region=$REGION \
    --cluster=$EKS_CLUSTER_NAME \
    --approve
```

### Step 4: Create Inference Operator IAM Role

```bash
# Create trust policy
cat > trust-policy.json << EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}"
            },
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {
                    "oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}:aud": "sts.amazonaws.com"
                },
                "StringLike": {
                    "oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}:sub": "system:serviceaccount:*:*"
                }
            }
        }
    ]
}
EOF

# Create permission policy
cat > permission-policy.json << EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "sagemaker:CreateEndpoint",
                "sagemaker:CreateEndpointConfig",
                "sagemaker:DeleteEndpoint",
                "sagemaker:DeleteEndpointConfig",
                "sagemaker:DescribeEndpoint",
                "sagemaker:DescribeEndpointConfig",
                "sagemaker:UpdateEndpoint",
                "sagemaker:InvokeEndpoint",
                "sagemaker:ListEndpoints",
                "sagemaker:ListEndpointConfigs",
                "sagemaker:DescribeCluster",
                "sagemaker:DescribeClusterNode",
                "sagemaker:ListClusterNodes"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::${BUCKET_NAME}",
                "arn:aws:s3:::${BUCKET_NAME}/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "ecr:GetAuthorizationToken",
                "ecr:BatchCheckLayerAvailability",
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "cloudwatch:PutMetricData",
                "cloudwatch:GetMetricData",
                "cloudwatch:GetMetricStatistics",
                "cloudwatch:ListMetrics"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": ["elasticloadbalancing:*"],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeSubnets",
                "ec2:DescribeVpcs",
                "ec2:DescribeSecurityGroups",
                "ec2:CreateTags"
            ],
            "Resource": "*"
        }
    ]
}
EOF

# Create IAM role
aws iam create-role \
    --role-name $HYPERPOD_INFERENCE_ROLE_NAME \
    --assume-role-policy-document file://trust-policy.json

aws iam put-role-policy \
    --role-name $HYPERPOD_INFERENCE_ROLE_NAME \
    --policy-name InferenceOperatorInlinePolicy \
    --policy-document file://permission-policy.json

# Attach SageMaker Full Access
aws iam attach-role-policy \
    --role-name $HYPERPOD_INFERENCE_ROLE_NAME \
    --policy-arn arn:aws:iam::aws:policy/AmazonSageMakerFullAccess
```

### Step 5: Install AWS Load Balancer Controller

```bash
# Download IAM policy
curl -o AWSLoadBalancerControllerIAMPolicy.json \
    https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.13.0/docs/install/iam_policy.json

# Create IAM policy
aws iam create-policy \
    --policy-name $LB_CONTROLLER_POLICY_NAME \
    --policy-document file://AWSLoadBalancerControllerIAMPolicy.json

# Get policy ARN
export ALB_POLICY_ARN="arn:aws:iam::$ACCOUNT_ID:policy/$LB_CONTROLLER_POLICY_NAME"

# Create IAM service account
eksctl create iamserviceaccount \
    --approve \
    --override-existing-serviceaccounts \
    --name=aws-load-balancer-controller \
    --namespace=kube-system \
    --cluster=$EKS_CLUSTER_NAME \
    --attach-policy-arn=$ALB_POLICY_ARN \
    --region=$REGION
```

### Step 6: Create Namespaces

```bash
kubectl create namespace keda
kubectl create namespace cert-manager
kubectl create namespace hyperpod-inference-system
```

### Step 7: Setup S3 CSI Driver

```bash
# Create S3 mountpoint policy
cat > s3-policy.json << EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "MountpointFullBucketAccess",
            "Effect": "Allow",
            "Action": ["s3:ListBucket"],
            "Resource": ["arn:aws:s3:::${BUCKET_NAME}"]
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
            "Resource": ["arn:aws:s3:::${BUCKET_NAME}/*"]
        }
    ]
}
EOF

aws iam create-policy \
    --policy-name $S3_MOUNT_ACCESS_POLICY_NAME \
    --policy-document file://s3-policy.json

export S3_CSI_POLICY_ARN="arn:aws:iam::$ACCOUNT_ID:policy/$S3_MOUNT_ACCESS_POLICY_NAME"

# Create IAM service account
eksctl create iamserviceaccount \
    --name s3-csi-driver-sa \
    --namespace kube-system \
    --cluster $EKS_CLUSTER_NAME \
    --attach-policy-arn $S3_CSI_POLICY_ARN \
    --approve \
    --role-name $S3_CSI_ROLE_NAME \
    --region $REGION
    --override-existing-serviceaccounts

# Label the service account
kubectl label serviceaccount s3-csi-driver-sa \
    app.kubernetes.io/component=csi-driver \
    app.kubernetes.io/instance=aws-mountpoint-s3-csi-driver \
    app.kubernetes.io/managed-by=EKS \
    app.kubernetes.io/name=aws-mountpoint-s3-csi-driver \
    -n kube-system --overwrite

# Install CSI driver addon
export S3_CSI_ROLE_ARN=$(aws iam get-role --role-name $S3_CSI_ROLE_NAME \
    --query 'Role.Arn' --output text)

eksctl create addon \
    --name aws-mountpoint-s3-csi-driver \
    --cluster $EKS_CLUSTER_NAME \
    --service-account-role-arn $S3_CSI_ROLE_ARN \
    --force
```

### Step 8: Create KEDA Role

```bash
# Create KEDA trust policy
cat > keda-trust-policy.json << EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}"
            },
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {
                    "oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}:aud": "sts.amazonaws.com",
                    "oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}:sub": "system:serviceaccount:keda:keda-operator"
                }
            }
        }
    ]
}
EOF

# Create KEDA permission policy
cat > keda-permission-policy.json << EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "cloudwatch:GetMetricData",
                "cloudwatch:GetMetricStatistics",
                "cloudwatch:ListMetrics"
            ],
            "Resource": "*"
        }
    ]
}
EOF

# Create KEDA role
aws iam create-role \
    --role-name $KEDA_OPERATOR_ROLE_NAME \
    --assume-role-policy-document file://keda-trust-policy.json

aws iam put-role-policy \
    --role-name $KEDA_OPERATOR_ROLE_NAME \
    --policy-name KedaOperatorInlinePolicy \
    --policy-document file://keda-permission-policy.json
```

### Step 9: Install NVIDIA Device Plugin (Optional)

```bash
# Install NVIDIA device plugin
kubectl create -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.5/nvidia-device-plugin.yml

# Verify GPUs are visible
kubectl get nodes -o=custom-columns=NAME:.metadata.name,GPU:.status.allocatable.nvidia.com/gpu
```

### Step 10: Install Inference Operator

```bash
# Clone Helm chart repository
git clone https://github.com/aws/sagemaker-hyperpod-cli
cd sagemaker-hyperpod-cli/helm_chart/HyperPodHelmChart

# Update dependencies
helm dependencies update charts/inference-operator

# Get required ARNs
export HYPERPOD_INFERENCE_ROLE_ARN=$(aws iam get-role \
    --role-name $HYPERPOD_INFERENCE_ROLE_NAME \
    --query "Role.Arn" --output text)

export HYPERPOD_CLUSTER_ARN=$(aws sagemaker describe-cluster \
    --cluster-name $HYPERPOD_CLUSTER_NAME \
    --query "ClusterArn" --output text)

export VPC_ID=$(aws eks describe-cluster --name $EKS_CLUSTER_NAME \
    --query 'cluster.resourcesVpcConfig.vpcId' --output text)

export KEDA_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${KEDA_OPERATOR_ROLE_NAME}"

# Install the operator
helm install hyperpod-inference-operator charts/inference-operator \
    -n kube-system \
    --set region=$REGION \
    --set eksClusterName=$EKS_CLUSTER_NAME \
    --set hyperpodClusterArn=$HYPERPOD_CLUSTER_ARN \
    --set executionRoleArn=$HYPERPOD_INFERENCE_ROLE_ARN \
    --set s3.serviceAccountRoleArn=$S3_CSI_ROLE_ARN \
    --set s3.node.serviceAccount.create=false \
    --set keda.podIdentity.aws.irsa.roleArn=$KEDA_ROLE_ARN \
    --set tlsCertificateS3Bucket="s3://$BUCKET_NAME" \
    --set alb.region=$REGION \
    --set alb.clusterName=$EKS_CLUSTER_NAME \
    --set alb.vpcId=$VPC_ID
```

### Step 11: Annotate Service Account

```bash
kubectl annotate serviceaccount $HYPERPOD_INFERENCE_SA_NAME \
    -n $HYPERPOD_INFERENCE_SA_NAMESPACE \
    eks.amazonaws.com/role-arn=$HYPERPOD_INFERENCE_ROLE_ARN \
    --overwrite
```

### Step 12: Verify Installation

```bash
# Check service accounts
kubectl get serviceaccount -n hyperpod-inference-system

# Check operator deployment
kubectl get deployment -n hyperpod-inference-system

# Check CRDs
kubectl get crds | grep sagemaker

# Check operator logs
kubectl logs -n hyperpod-inference-system -l app=hyperpod-inference-operator
```

## Deploying Models

### Deploy JumpStart Model

```yaml
apiVersion: inference.sagemaker.aws.amazon.com/v1
kind: JumpStartModel
metadata:
  name: my-bert-model
  namespace: default
spec:
  model:
    modelId: "huggingface-eqa-bert-base-cased"
  sageMakerEndpoint:
    name: "my-bert-endpoint"
  server:
    instanceType: "ml.c5.2xlarge"
    environmentVariables:
    - name: SAMPLE_ENV_VAR
      value: "sample_value"
  maxDeployTimeInSeconds: 1800
```

```bash
kubectl apply -f jumpstart-model.yaml
```

### Deploy Custom Model

```yaml
apiVersion: inference.sagemaker.aws.amazon.com/v1
kind: InferenceEndpointConfig
metadata:
  name: my-custom-model
  namespace: default
spec:
  modelName: "llama-3-8b-instruct"
  endpointName: "my-custom-endpoint"
  instanceType: "ml.g5.24xlarge"
  invocationEndpoint: "v1/chat/completions"
  replicas: 1
  modelSourceConfig:
    modelSourceType: "s3"
    s3Storage:
      bucketName: "my-model-bucket"
      region: "us-west-2"
    modelLocation: "models/llama-3-8b"
    prefetchEnabled: true
  worker:
    image: "763104351884.dkr.ecr.us-west-2.amazonaws.com/djl-inference:0.32.0-lmi14.0.0-cu124"
    resources:
      limits:
        nvidia.com/gpu: "4"
      requests:
        cpu: "30"
        memory: "100Gi"
        nvidia.com/gpu: "4"
    modelInvocationPort:
      containerPort: 8000
      name: "http"
    environmentVariables:
    - name: SAGEMAKER_ENV
      value: "1"
    - name: MODEL_CACHE_ROOT
      value: "/opt/ml/model"
    - name: OPTION_ROLLING_BATCH
      value: "vllm"
```

```bash
kubectl apply -f custom-model.yaml
```

### Check Model Status

```bash
# List all JumpStart models
kubectl get jumpstartmodels

# List all custom models
kubectl get inferenceendpointconfigs

# Get detailed status
kubectl describe jumpstartmodel my-bert-model
kubectl describe inferenceendpointconfig my-custom-model
```

## Troubleshooting

### Common Issues

1. **OIDC Provider Not Associated**
   ```bash
   eksctl utils associate-iam-oidc-provider \
       --region=$REGION \
       --cluster=$EKS_CLUSTER_NAME \
       --approve
   ```

2. **Service Account Missing IAM Annotation**
   ```bash
   kubectl annotate serviceaccount hyperpod-inference-operator-controller \
       -n hyperpod-inference-system \
       eks.amazonaws.com/role-arn=arn:aws:iam::$ACCOUNT_ID:role/$HYPERPOD_INFERENCE_ROLE_NAME \
       --overwrite
   ```

3. **Operator Pods Not Starting**
   ```bash
   # Check pod status
   kubectl get pods -n hyperpod-inference-system

   # Check pod events
   kubectl describe pod -n hyperpod-inference-system -l app=hyperpod-inference-operator

   # Check operator logs
   kubectl logs -n hyperpod-inference-system -l app=hyperpod-inference-operator
   ```

4. **Model Deployment Stuck**
   ```bash
   # Check model status
   kubectl describe jumpstartmodel <model-name>

   # Check associated pods
   kubectl get pods -l app=<model-name>
   ```

5. **GPU Not Detected**
   ```bash
   # Verify NVIDIA device plugin
   kubectl get pods -n kube-system | grep nvidia

   # Check node GPU allocation
   kubectl get nodes -o=custom-columns=NAME:.metadata.name,GPU:.status.allocatable.nvidia.com/gpu
   ```

### Cleanup

```bash
# Delete test model
kubectl delete jumpstartmodel testing-deployment-bert

# Uninstall operator
helm uninstall hyperpod-inference-operator -n kube-system

# Delete IAM roles (optional)
aws iam delete-role-policy --role-name $HYPERPOD_INFERENCE_ROLE_NAME --policy-name InferenceOperatorInlinePolicy
aws iam detach-role-policy --role-name $HYPERPOD_INFERENCE_ROLE_NAME --policy-arn arn:aws:iam::aws:policy/AmazonSageMakerFullAccess
aws iam delete-role --role-name $HYPERPOD_INFERENCE_ROLE_NAME
```

## API Reference

### HyperPodInferenceOperatorSetup Class

```python
class HyperPodInferenceOperatorSetup:
    """Main setup class for HyperPod inference operator."""

    def __init__(
        self,
        hyperpod_cluster_name: str,
        region: str,
        s3_bucket_name: str,
        config: Optional[SetupConfig] = None,
        kubeconfig_path: Optional[str] = None
    ):
        """Initialize setup manager."""

    def run_full_setup(
        self,
        skip_test_deployment: bool = False
    ) -> Dict[str, Any]:
        """Run complete setup process."""

    def configure_iam_only(self) -> Dict[str, str]:
        """Configure only IAM roles and policies."""

    def update_kubeconfig(self) -> None:
        """Update kubeconfig for EKS cluster."""

    def associate_oidc_provider(self) -> None:
        """Associate IAM OIDC provider."""

    def create_inference_operator_role(self) -> str:
        """Create inference operator IAM role."""

    def create_keda_role(self) -> str:
        """Create KEDA operator IAM role."""

    def install_load_balancer_controller(self) -> None:
        """Install AWS Load Balancer Controller."""

    def setup_s3_csi_driver(self) -> str:
        """Setup S3 CSI driver."""

    def install_inference_operator(
        self,
        inference_role_arn: Optional[str] = None,
        s3_csi_role_arn: Optional[str] = None,
        jumpstart_gated_role_arn: Optional[str] = None
    ) -> None:
        """Install HyperPod inference operator via Helm."""

    def verify_installation(self) -> bool:
        """Verify operator installation."""
```

### SetupConfig Class

```python
@dataclass
class SetupConfig:
    """Configuration for setup process."""

    hyperpod_cluster_name: str      # HyperPod cluster name
    region: str                      # AWS region
    s3_bucket_name: str              # S3 bucket for TLS certs

    # Optional features
    install_nvidia_plugin: bool = True
    install_s3_csi: bool = True
    install_fsx_csi: bool = False
    enable_jumpstart_gated: bool = False
```

## References

- [AWS Documentation: Setting up HyperPod clusters for model deployment](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-model-deployment-setup.html)
- [SageMaker HyperPod CLI GitHub](https://github.com/aws/sagemaker-hyperpod-cli)
- [AWS Load Balancer Controller](https://kubernetes-sigs.github.io/aws-load-balancer-controller/)
- [KEDA - Kubernetes Event-driven Autoscaling](https://keda.sh/)
