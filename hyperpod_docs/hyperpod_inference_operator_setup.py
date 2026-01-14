"""
HyperPod Inference Operator Setup

This module provides automated installation and configuration of the HyperPod
inference operator on Amazon EKS clusters. It follows the official AWS documentation:
https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-model-deployment-setup.html

The setup includes:
1. IAM roles and policies configuration
2. AWS Load Balancer Controller installation
3. S3 CSI driver setup
4. FSx CSI driver setup (optional)
5. KEDA and cert-manager installation
6. HyperPod inference operator Helm chart installation

Usage:
    from hyperpod_inference_operator_setup import HyperPodInferenceOperatorSetup

    setup = HyperPodInferenceOperatorSetup(
        hyperpod_cluster_name="my-hyperpod-cluster",
        region="us-west-2",
        s3_bucket_name="my-tls-cert-bucket"
    )

    # Run full setup
    setup.run_full_setup()

    # Or run individual steps
    setup.configure_iam_roles()
    setup.install_load_balancer_controller()
    setup.install_inference_operator()
"""

import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

import boto3
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==============================================================================
# IAM Policy Documents
# ==============================================================================

def get_hyperpod_inference_trust_policy(account_id: str, oidc_id: str, region: str) -> Dict:
    """Generate trust policy for HyperPod inference operator role."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Federated": f"arn:aws:iam::{account_id}:oidc-provider/oidc.eks.{region}.amazonaws.com/id/{oidc_id}"
                },
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        f"oidc.eks.{region}.amazonaws.com/id/{oidc_id}:aud": "sts.amazonaws.com"
                    },
                    "StringLike": {
                        f"oidc.eks.{region}.amazonaws.com/id/{oidc_id}:sub": "system:serviceaccount:*:*"
                    }
                }
            }
        ]
    }


def get_hyperpod_inference_permission_policy(
    account_id: str,
    region: str,
    s3_bucket: str
) -> Dict:
    """Generate permission policy for HyperPod inference operator."""
    return {
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
                    "sagemaker:UpdateEndpointWeightsAndCapacities",
                    "sagemaker:InvokeEndpoint",
                    "sagemaker:InvokeEndpointAsync",
                    "sagemaker:ListEndpoints",
                    "sagemaker:ListEndpointConfigs"
                ],
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": [
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
                    f"arn:aws:s3:::{s3_bucket}",
                    f"arn:aws:s3:::{s3_bucket}/*"
                ]
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogGroups",
                    "logs:DescribeLogStreams"
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
                "Action": [
                    "elasticloadbalancing:*"
                ],
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "ec2:DescribeSubnets",
                    "ec2:DescribeVpcs",
                    "ec2:DescribeSecurityGroups",
                    "ec2:DescribeInstances",
                    "ec2:DescribeNetworkInterfaces",
                    "ec2:CreateSecurityGroup",
                    "ec2:DeleteSecurityGroup",
                    "ec2:AuthorizeSecurityGroupIngress",
                    "ec2:RevokeSecurityGroupIngress",
                    "ec2:CreateTags"
                ],
                "Resource": "*"
            }
        ]
    }


def get_keda_trust_policy(account_id: str, oidc_id: str, region: str) -> Dict:
    """Generate trust policy for KEDA operator role."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Federated": f"arn:aws:iam::{account_id}:oidc-provider/oidc.eks.{region}.amazonaws.com/id/{oidc_id}"
                },
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        f"oidc.eks.{region}.amazonaws.com/id/{oidc_id}:aud": "sts.amazonaws.com",
                        f"oidc.eks.{region}.amazonaws.com/id/{oidc_id}:sub": "system:serviceaccount:keda:keda-operator"
                    }
                }
            }
        ]
    }


def get_keda_permission_policy() -> Dict:
    """Generate permission policy for KEDA operator."""
    return {
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
            },
            {
                "Effect": "Allow",
                "Action": [
                    "sqs:GetQueueAttributes",
                    "sqs:GetQueueUrl"
                ],
                "Resource": "*"
            }
        ]
    }


def get_s3_mountpoint_policy(s3_bucket: str) -> Dict:
    """Generate S3 mountpoint access policy."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "MountpointFullBucketAccess",
                "Effect": "Allow",
                "Action": [
                    "s3:ListBucket"
                ],
                "Resource": [
                    f"arn:aws:s3:::{s3_bucket}"
                ]
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
                "Resource": [
                    f"arn:aws:s3:::{s3_bucket}/*"
                ]
            }
        ]
    }


def get_jumpstart_gated_policy(account_id: str, region: str) -> Dict:
    """Generate policy for JumpStart gated model access."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "sagemaker:DescribeModel",
                    "sagemaker:DescribeModelPackage",
                    "sagemaker:DescribeModelPackageGroup"
                ],
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:ListBucket"
                ],
                "Resource": [
                    "arn:aws:s3:::jumpstart-cache-prod-*",
                    "arn:aws:s3:::jumpstart-cache-prod-*/*"
                ]
            }
        ]
    }


# ==============================================================================
# Configuration Classes
# ==============================================================================

@dataclass
class SetupConfig:
    """Configuration for HyperPod inference operator setup."""
    hyperpod_cluster_name: str
    region: str
    s3_bucket_name: str

    # Derived names (auto-generated from cluster name)
    lb_controller_policy_name: str = ""
    lb_controller_role_name: str = ""
    s3_mount_policy_name: str = ""
    s3_csi_role_name: str = ""
    keda_policy_name: str = ""
    keda_role_name: str = ""
    hyperpod_inference_policy_name: str = ""
    hyperpod_inference_role_name: str = ""
    jumpstart_gated_role_name: str = ""
    fsx_csi_role_name: str = ""

    # Service account configuration
    inference_sa_name: str = "hyperpod-inference-operator-controller"
    inference_sa_namespace: str = "hyperpod-inference-system"

    # Optional features
    install_nvidia_plugin: bool = True
    install_s3_csi: bool = True
    install_fsx_csi: bool = False
    enable_jumpstart_gated: bool = False

    # Helm chart configuration
    helm_chart_repo: str = "https://github.com/aws/sagemaker-hyperpod-cli"
    helm_chart_path: str = "helm_chart/HyperPodHelmChart/charts/inference-operator"

    def __post_init__(self):
        """Auto-generate resource names based on cluster name."""
        cluster = self.hyperpod_cluster_name

        if not self.lb_controller_policy_name:
            self.lb_controller_policy_name = f"AWSLoadBalancerControllerIAMPolicy-{cluster}"
        if not self.lb_controller_role_name:
            self.lb_controller_role_name = f"aws-load-balancer-controller-{cluster}"
        if not self.s3_mount_policy_name:
            self.s3_mount_policy_name = f"S3MountpointAccessPolicy-{cluster}"
        if not self.s3_csi_role_name:
            self.s3_csi_role_name = f"SM_HP_S3_CSI_ROLE-{cluster}"
        if not self.keda_policy_name:
            self.keda_policy_name = f"KedaOperatorPolicy-{cluster}"
        if not self.keda_role_name:
            self.keda_role_name = f"keda-operator-role-{cluster}"
        if not self.hyperpod_inference_policy_name:
            self.hyperpod_inference_policy_name = f"HyperpodInferenceAccessPolicy-{cluster}"
        if not self.hyperpod_inference_role_name:
            self.hyperpod_inference_role_name = f"HyperpodInferenceRole-{cluster}"
        if not self.jumpstart_gated_role_name:
            self.jumpstart_gated_role_name = f"JumpstartGatedRole-{cluster}"
        if not self.fsx_csi_role_name:
            self.fsx_csi_role_name = f"AmazonEKSFSxLustreCSIDriverFullAccess-{cluster}"


# ==============================================================================
# Main Setup Class
# ==============================================================================

class HyperPodInferenceOperatorSetup:
    """
    HyperPod Inference Operator Setup Manager.

    Automates the installation and configuration of the HyperPod inference
    operator on Amazon EKS clusters.
    """

    def __init__(
        self,
        hyperpod_cluster_name: str,
        region: str,
        s3_bucket_name: str,
        config: Optional[SetupConfig] = None,
        kubeconfig_path: Optional[str] = None
    ):
        """
        Initialize the setup manager.

        Args:
            hyperpod_cluster_name: Name of the HyperPod cluster
            region: AWS region
            s3_bucket_name: S3 bucket for TLS certificates and model storage
            config: Optional custom configuration
            kubeconfig_path: Optional path to kubeconfig file
        """
        self.config = config or SetupConfig(
            hyperpod_cluster_name=hyperpod_cluster_name,
            region=region,
            s3_bucket_name=s3_bucket_name
        )
        self.kubeconfig_path = kubeconfig_path

        # Initialize AWS clients
        self.iam_client = boto3.client('iam', region_name=region)
        self.sts_client = boto3.client('sts', region_name=region)
        self.sagemaker_client = boto3.client('sagemaker', region_name=region)
        self.eks_client = boto3.client('eks', region_name=region)
        self.ec2_client = boto3.client('ec2', region_name=region)

        # Cache for computed values
        self._account_id: Optional[str] = None
        self._eks_cluster_name: Optional[str] = None
        self._oidc_id: Optional[str] = None
        self._vpc_id: Optional[str] = None
        self._hyperpod_cluster_arn: Optional[str] = None

    # ==========================================================================
    # Properties
    # ==========================================================================

    @property
    def account_id(self) -> str:
        """Get AWS account ID."""
        if not self._account_id:
            self._account_id = self.sts_client.get_caller_identity()['Account']
        return self._account_id

    @property
    def eks_cluster_name(self) -> str:
        """Get EKS cluster name from HyperPod cluster."""
        if not self._eks_cluster_name:
            response = self.sagemaker_client.describe_cluster(
                ClusterName=self.config.hyperpod_cluster_name
            )
            cluster_arn = response['Orchestrator']['Eks']['ClusterArn']
            self._eks_cluster_name = cluster_arn.split('/')[-1]
            self._hyperpod_cluster_arn = response['ClusterArn']
        return self._eks_cluster_name

    @property
    def hyperpod_cluster_arn(self) -> str:
        """Get HyperPod cluster ARN."""
        if not self._hyperpod_cluster_arn:
            _ = self.eks_cluster_name  # This populates both values
        return self._hyperpod_cluster_arn

    @property
    def oidc_id(self) -> str:
        """Get OIDC provider ID for EKS cluster."""
        if not self._oidc_id:
            response = self.eks_client.describe_cluster(name=self.eks_cluster_name)
            issuer = response['cluster']['identity']['oidc']['issuer']
            self._oidc_id = issuer.split('/')[-1]
        return self._oidc_id

    @property
    def vpc_id(self) -> str:
        """Get VPC ID for EKS cluster."""
        if not self._vpc_id:
            response = self.eks_client.describe_cluster(name=self.eks_cluster_name)
            self._vpc_id = response['cluster']['resourcesVpcConfig']['vpcId']
        return self._vpc_id

    # ==========================================================================
    # Helper Methods
    # ==========================================================================

    def _run_command(
        self,
        command: List[str],
        check: bool = True,
        capture_output: bool = True
    ) -> subprocess.CompletedProcess:
        """Run a shell command."""
        env = os.environ.copy()
        if self.kubeconfig_path:
            env['KUBECONFIG'] = self.kubeconfig_path

        logger.info(f"Running: {' '.join(command)}")
        result = subprocess.run(
            command,
            env=env,
            check=check,
            capture_output=capture_output,
            text=True
        )
        if result.stdout:
            logger.debug(f"stdout: {result.stdout}")
        if result.stderr:
            logger.debug(f"stderr: {result.stderr}")
        return result

    def _kubectl(self, *args: str) -> subprocess.CompletedProcess:
        """Run kubectl command."""
        cmd = ['kubectl'] + list(args)
        return self._run_command(cmd)

    def _helm(self, *args: str) -> subprocess.CompletedProcess:
        """Run helm command."""
        cmd = ['helm'] + list(args)
        return self._run_command(cmd)

    def _eksctl(self, *args: str) -> subprocess.CompletedProcess:
        """Run eksctl command."""
        cmd = ['eksctl'] + list(args)
        return self._run_command(cmd)

    def _create_or_update_iam_role(
        self,
        role_name: str,
        trust_policy: Dict,
        permission_policy: Optional[Dict] = None,
        policy_name: Optional[str] = None,
        managed_policy_arns: Optional[List[str]] = None
    ) -> str:
        """Create or update an IAM role with policies."""
        try:
            # Try to create the role
            response = self.iam_client.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description=f"Role for HyperPod inference operator - {self.config.hyperpod_cluster_name}"
            )
            role_arn = response['Role']['Arn']
            logger.info(f"Created IAM role: {role_name}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'EntityAlreadyExists':
                # Update existing role's trust policy
                self.iam_client.update_assume_role_policy(
                    RoleName=role_name,
                    PolicyDocument=json.dumps(trust_policy)
                )
                role_arn = f"arn:aws:iam::{self.account_id}:role/{role_name}"
                logger.info(f"Updated existing IAM role: {role_name}")
            else:
                raise

        # Attach inline policy if provided
        if permission_policy and policy_name:
            self.iam_client.put_role_policy(
                RoleName=role_name,
                PolicyName=policy_name,
                PolicyDocument=json.dumps(permission_policy)
            )
            logger.info(f"Attached inline policy: {policy_name}")

        # Attach managed policies if provided
        if managed_policy_arns:
            for policy_arn in managed_policy_arns:
                try:
                    self.iam_client.attach_role_policy(
                        RoleName=role_name,
                        PolicyArn=policy_arn
                    )
                    logger.info(f"Attached managed policy: {policy_arn}")
                except ClientError as e:
                    if e.response['Error']['Code'] != 'EntityAlreadyExists':
                        raise

        return role_arn

    def _create_iam_policy(
        self,
        policy_name: str,
        policy_document: Dict
    ) -> str:
        """Create IAM policy if it doesn't exist."""
        try:
            response = self.iam_client.create_policy(
                PolicyName=policy_name,
                PolicyDocument=json.dumps(policy_document)
            )
            policy_arn = response['Policy']['Arn']
            logger.info(f"Created IAM policy: {policy_name}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'EntityAlreadyExists':
                policy_arn = f"arn:aws:iam::{self.account_id}:policy/{policy_name}"
                logger.info(f"IAM policy already exists: {policy_name}")
            else:
                raise
        return policy_arn

    def _write_temp_file(self, content: str, suffix: str = '.yaml') -> str:
        """Write content to a temporary file and return path."""
        fd, path = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(content)
        except:
            os.close(fd)
            raise
        return path

    # ==========================================================================
    # Setup Steps
    # ==========================================================================

    def update_kubeconfig(self) -> None:
        """Update kubeconfig to connect to the EKS cluster."""
        logger.info("Updating kubeconfig...")
        self._run_command([
            'aws', 'eks', 'update-kubeconfig',
            '--name', self.eks_cluster_name,
            '--region', self.config.region
        ])

        # Verify connectivity
        self._kubectl('get', 'pods', '--all-namespaces')
        logger.info("Successfully connected to EKS cluster")

    def associate_oidc_provider(self) -> None:
        """Associate IAM OIDC provider with EKS cluster."""
        logger.info("Associating IAM OIDC provider...")
        self._eksctl(
            'utils', 'associate-iam-oidc-provider',
            f'--region={self.config.region}',
            f'--cluster={self.eks_cluster_name}',
            '--approve'
        )
        logger.info("OIDC provider associated")

    def create_inference_operator_role(self) -> str:
        """Create IAM role for inference operator."""
        logger.info("Creating inference operator IAM role...")

        trust_policy = get_hyperpod_inference_trust_policy(
            self.account_id,
            self.oidc_id,
            self.config.region
        )

        permission_policy = get_hyperpod_inference_permission_policy(
            self.account_id,
            self.config.region,
            self.config.s3_bucket_name
        )

        role_arn = self._create_or_update_iam_role(
            role_name=self.config.hyperpod_inference_role_name,
            trust_policy=trust_policy,
            permission_policy=permission_policy,
            policy_name="InferenceOperatorInlinePolicy",
            managed_policy_arns=[
                "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
            ]
        )

        logger.info(f"Inference operator role ARN: {role_arn}")
        return role_arn

    def create_keda_role(self) -> str:
        """Create IAM role for KEDA operator."""
        logger.info("Creating KEDA operator IAM role...")

        trust_policy = get_keda_trust_policy(
            self.account_id,
            self.oidc_id,
            self.config.region
        )

        permission_policy = get_keda_permission_policy()

        role_arn = self._create_or_update_iam_role(
            role_name=self.config.keda_role_name,
            trust_policy=trust_policy,
            permission_policy=permission_policy,
            policy_name="KedaOperatorInlinePolicy"
        )

        logger.info(f"KEDA operator role ARN: {role_arn}")
        return role_arn

    def install_load_balancer_controller(self) -> None:
        """Install AWS Load Balancer Controller."""
        logger.info("Installing AWS Load Balancer Controller...")

        # Download IAM policy
        policy_url = "https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.13.0/docs/install/iam_policy.json"
        result = self._run_command(['curl', '-o', '/tmp/alb_policy.json', policy_url])

        with open('/tmp/alb_policy.json', 'r') as f:
            policy_doc = json.load(f)

        # Create IAM policy
        alb_policy_name = f"HyperPodInferenceALBControllerIAMPolicy-{self.config.hyperpod_cluster_name}"
        policy_arn = self._create_iam_policy(alb_policy_name, policy_doc)

        # Create IAM service account
        self._eksctl(
            'create', 'iamserviceaccount',
            '--approve',
            '--override-existing-serviceaccounts',
            '--name=aws-load-balancer-controller',
            '--namespace=kube-system',
            f'--cluster={self.eks_cluster_name}',
            f'--attach-policy-arn={policy_arn}',
            f'--region={self.config.region}'
        )

        logger.info("AWS Load Balancer Controller IAM service account created")

    def tag_subnets(self) -> None:
        """Tag subnets for load balancer discovery."""
        logger.info("Tagging subnets for load balancer discovery...")

        # Get all subnets in the VPC
        response = self.ec2_client.describe_subnets(
            Filters=[{'Name': 'vpc-id', 'Values': [self.vpc_id]}]
        )

        for subnet in response['Subnets']:
            subnet_id = subnet['SubnetId']

            # Tag for internal ELB
            self.ec2_client.create_tags(
                Resources=[subnet_id],
                Tags=[
                    {'Key': 'kubernetes.io/role/elb', 'Value': '1'},
                    {'Key': 'kubernetes.io/role/internal-elb', 'Value': '1'}
                ]
            )
            logger.info(f"Tagged subnet: {subnet_id}")

    def create_namespaces(self) -> None:
        """Create required Kubernetes namespaces."""
        logger.info("Creating Kubernetes namespaces...")

        namespaces = ['keda', 'cert-manager', 'hyperpod-inference-system']
        for ns in namespaces:
            try:
                self._kubectl('create', 'namespace', ns)
                logger.info(f"Created namespace: {ns}")
            except subprocess.CalledProcessError:
                logger.info(f"Namespace already exists: {ns}")

    def create_s3_vpc_endpoint(self) -> None:
        """Create S3 VPC endpoint if not exists."""
        logger.info("Checking S3 VPC endpoint...")

        # Check if endpoint already exists
        response = self.ec2_client.describe_vpc_endpoints(
            Filters=[
                {'Name': 'vpc-id', 'Values': [self.vpc_id]},
                {'Name': 'service-name', 'Values': [f'com.amazonaws.{self.config.region}.s3']}
            ]
        )

        if response['VpcEndpoints']:
            logger.info("S3 VPC endpoint already exists")
            return

        # Get route tables
        response = self.ec2_client.describe_route_tables(
            Filters=[{'Name': 'vpc-id', 'Values': [self.vpc_id]}]
        )
        route_table_ids = [rt['RouteTableId'] for rt in response['RouteTables']]

        # Create endpoint
        self.ec2_client.create_vpc_endpoint(
            VpcId=self.vpc_id,
            ServiceName=f'com.amazonaws.{self.config.region}.s3',
            RouteTableIds=route_table_ids,
            VpcEndpointType='Gateway'
        )
        logger.info("Created S3 VPC endpoint")

    def setup_s3_csi_driver(self) -> str:
        """Setup S3 CSI driver for model storage."""
        logger.info("Setting up S3 CSI driver...")

        # Create S3 mountpoint policy
        policy_doc = get_s3_mountpoint_policy(self.config.s3_bucket_name)
        policy_arn = self._create_iam_policy(
            self.config.s3_mount_policy_name,
            policy_doc
        )

        # Create IAM service account
        self._eksctl(
            'create', 'iamserviceaccount',
            '--name=s3-csi-driver-sa',
            '--namespace=kube-system',
            f'--cluster={self.eks_cluster_name}',
            f'--attach-policy-arn={policy_arn}',
            '--approve',
            f'--role-name={self.config.s3_csi_role_name}',
            f'--region={self.config.region}'
        )

        # Label the service account
        self._kubectl(
            'label', 'serviceaccount', 's3-csi-driver-sa',
            'app.kubernetes.io/component=csi-driver',
            'app.kubernetes.io/instance=aws-mountpoint-s3-csi-driver',
            'app.kubernetes.io/managed-by=EKS',
            'app.kubernetes.io/name=aws-mountpoint-s3-csi-driver',
            '-n', 'kube-system',
            '--overwrite'
        )

        # Get role ARN
        response = self.iam_client.get_role(RoleName=self.config.s3_csi_role_name)
        role_arn = response['Role']['Arn']

        # Install CSI driver addon
        self._eksctl(
            'create', 'addon',
            '--name=aws-mountpoint-s3-csi-driver',
            f'--cluster={self.eks_cluster_name}',
            f'--service-account-role-arn={role_arn}',
            '--force'
        )

        logger.info("S3 CSI driver installed")
        return role_arn

    def setup_fsx_csi_driver(self) -> str:
        """Setup FSx CSI driver (optional)."""
        logger.info("Setting up FSx CSI driver...")

        # Create IAM service account with FSx policy
        self._eksctl(
            'create', 'iamserviceaccount',
            '--name=fsx-csi-controller-sa',
            '--namespace=kube-system',
            f'--cluster={self.eks_cluster_name}',
            '--attach-policy-arn=arn:aws:iam::aws:policy/AmazonFSxFullAccess',
            '--approve',
            f'--role-name={self.config.fsx_csi_role_name}',
            f'--region={self.config.region}'
        )

        # Get role ARN
        response = self.iam_client.get_role(RoleName=self.config.fsx_csi_role_name)
        role_arn = response['Role']['Arn']

        # Install FSx CSI driver addon
        self._eksctl(
            'create', 'addon',
            '--name=aws-fsx-csi-driver',
            f'--cluster={self.eks_cluster_name}',
            f'--service-account-role-arn={role_arn}',
            '--force'
        )

        logger.info("FSx CSI driver installed")
        return role_arn

    def install_nvidia_device_plugin(self) -> None:
        """Install NVIDIA device plugin for GPU support."""
        logger.info("Installing NVIDIA device plugin...")

        self._kubectl(
            'create', '-f',
            'https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.5/nvidia-device-plugin.yml'
        )

        # Verify GPUs are visible
        result = self._kubectl(
            'get', 'nodes',
            '-o=custom-columns=NAME:.metadata.name,GPU:.status.allocatable.nvidia.com/gpu'
        )
        logger.info(f"GPU nodes:\n{result.stdout}")

    def create_jumpstart_gated_role(self) -> str:
        """Create role for JumpStart gated model access."""
        logger.info("Creating JumpStart gated model role...")

        trust_policy = get_hyperpod_inference_trust_policy(
            self.account_id,
            self.oidc_id,
            self.config.region
        )

        permission_policy = get_jumpstart_gated_policy(
            self.account_id,
            self.config.region
        )

        role_arn = self._create_or_update_iam_role(
            role_name=self.config.jumpstart_gated_role_name,
            trust_policy=trust_policy,
            permission_policy=permission_policy,
            policy_name="JumpStartGatedModelPolicy"
        )

        logger.info(f"JumpStart gated role ARN: {role_arn}")
        return role_arn

    def install_inference_operator(
        self,
        inference_role_arn: Optional[str] = None,
        s3_csi_role_arn: Optional[str] = None,
        jumpstart_gated_role_arn: Optional[str] = None
    ) -> None:
        """Install HyperPod inference operator using Helm."""
        logger.info("Installing HyperPod inference operator...")

        # Get role ARNs if not provided
        if not inference_role_arn:
            response = self.iam_client.get_role(
                RoleName=self.config.hyperpod_inference_role_name
            )
            inference_role_arn = response['Role']['Arn']

        if not s3_csi_role_arn and self.config.install_s3_csi:
            response = self.iam_client.get_role(
                RoleName=self.config.s3_csi_role_name
            )
            s3_csi_role_arn = response['Role']['Arn']

        keda_role_arn = f"arn:aws:iam::{self.account_id}:role/{self.config.keda_role_name}"

        # Clone the Helm chart repo
        import shutil
        helm_dir = '/tmp/sagemaker-hyperpod-cli'
        if os.path.exists(helm_dir):
            shutil.rmtree(helm_dir)

        self._run_command([
            'git', 'clone', '--depth', '1',
            'https://github.com/aws/sagemaker-hyperpod-cli',
            helm_dir
        ])

        # Update Helm dependencies
        chart_path = f'{helm_dir}/helm_chart/HyperPodHelmChart/charts/inference-operator'
        self._helm('dependencies', 'update', chart_path)

        # Build Helm install command
        helm_args = [
            'install', 'hyperpod-inference-operator', chart_path,
            '-n', 'kube-system',
            '--set', f'region={self.config.region}',
            '--set', f'eksClusterName={self.eks_cluster_name}',
            '--set', f'hyperpodClusterArn={self.hyperpod_cluster_arn}',
            '--set', f'executionRoleArn={inference_role_arn}',
            '--set', f'tlsCertificateS3Bucket=s3://{self.config.s3_bucket_name}',
            '--set', f'alb.region={self.config.region}',
            '--set', f'alb.clusterName={self.eks_cluster_name}',
            '--set', f'alb.vpcId={self.vpc_id}',
            '--set', f'keda.podIdentity.aws.irsa.roleArn={keda_role_arn}'
        ]

        if s3_csi_role_arn:
            helm_args.extend([
                '--set', f's3.serviceAccountRoleArn={s3_csi_role_arn}',
                '--set', 's3.node.serviceAccount.create=false'
            ])

        if jumpstart_gated_role_arn:
            helm_args.extend([
                '--set', f'jumpstartGatedModelDownloadRoleArn={jumpstart_gated_role_arn}'
            ])

        self._helm(*helm_args)
        logger.info("HyperPod inference operator installed")

    def annotate_service_account(self, inference_role_arn: str) -> None:
        """Annotate service account for IAM integration."""
        logger.info("Annotating service account...")

        self._kubectl(
            'annotate', 'serviceaccount',
            self.config.inference_sa_name,
            '-n', self.config.inference_sa_namespace,
            f'eks.amazonaws.com/role-arn={inference_role_arn}',
            '--overwrite'
        )
        logger.info("Service account annotated")

    def verify_installation(self) -> bool:
        """Verify the inference operator is working."""
        logger.info("Verifying installation...")

        # Check service accounts
        result = self._kubectl(
            'get', 'serviceaccount',
            '-n', 'hyperpod-inference-system'
        )
        logger.info(f"Service accounts:\n{result.stdout}")

        # Check operator deployment
        result = self._kubectl(
            'get', 'deployment',
            '-n', 'hyperpod-inference-system'
        )
        logger.info(f"Deployments:\n{result.stdout}")

        # Check CRDs
        result = self._kubectl('get', 'crds')
        if 'jumpstartmodels' in result.stdout and 'inferenceendpointconfigs' in result.stdout:
            logger.info("CRDs installed successfully")
            return True
        else:
            logger.warning("CRDs may not be fully installed")
            return False

    def deploy_test_model(self) -> None:
        """Deploy a test model to verify the setup."""
        logger.info("Deploying test model...")

        test_manifest = """
apiVersion: inference.sagemaker.aws.amazon.com/v1
kind: JumpStartModel
metadata:
  name: testing-deployment-bert
  namespace: default
spec:
  model:
    modelId: "huggingface-eqa-bert-base-cased"
  sageMakerEndpoint:
    name: "hp-inf-ep-for-testing"
  server:
    instanceType: "ml.c5.2xlarge"
    environmentVariables:
    - name: SAMPLE_ENV_VAR
      value: "sample_value"
  maxDeployTimeInSeconds: 1800
"""

        manifest_path = self._write_temp_file(test_manifest)
        try:
            self._kubectl('apply', '-f', manifest_path)
            logger.info("Test model deployment created")
        finally:
            os.unlink(manifest_path)

    # ==========================================================================
    # Main Setup Methods
    # ==========================================================================

    def run_full_setup(
        self,
        skip_test_deployment: bool = False
    ) -> Dict[str, Any]:
        """
        Run the complete setup process.

        Args:
            skip_test_deployment: Skip test model deployment

        Returns:
            Dictionary with setup results and resource ARNs
        """
        results = {
            'hyperpod_cluster': self.config.hyperpod_cluster_name,
            'eks_cluster': None,
            'region': self.config.region,
            'roles': {},
            'success': False
        }

        try:
            # Step 1: Update kubeconfig
            self.update_kubeconfig()
            results['eks_cluster'] = self.eks_cluster_name

            # Step 2: Associate OIDC provider
            self.associate_oidc_provider()

            # Step 3: Create IAM roles
            inference_role_arn = self.create_inference_operator_role()
            results['roles']['inference'] = inference_role_arn

            keda_role_arn = self.create_keda_role()
            results['roles']['keda'] = keda_role_arn

            # Step 4: Install Load Balancer Controller
            self.install_load_balancer_controller()

            # Step 5: Tag subnets
            self.tag_subnets()

            # Step 6: Create namespaces
            self.create_namespaces()

            # Step 7: Create S3 VPC endpoint
            self.create_s3_vpc_endpoint()

            # Step 8: Setup S3 CSI driver
            s3_csi_role_arn = None
            if self.config.install_s3_csi:
                s3_csi_role_arn = self.setup_s3_csi_driver()
                results['roles']['s3_csi'] = s3_csi_role_arn

            # Step 9: Setup FSx CSI driver (optional)
            if self.config.install_fsx_csi:
                fsx_role_arn = self.setup_fsx_csi_driver()
                results['roles']['fsx_csi'] = fsx_role_arn

            # Step 10: Install NVIDIA device plugin (optional)
            if self.config.install_nvidia_plugin:
                try:
                    self.install_nvidia_device_plugin()
                except subprocess.CalledProcessError:
                    logger.warning("NVIDIA device plugin may already be installed")

            # Step 11: Create JumpStart gated role (optional)
            jumpstart_role_arn = None
            if self.config.enable_jumpstart_gated:
                jumpstart_role_arn = self.create_jumpstart_gated_role()
                results['roles']['jumpstart_gated'] = jumpstart_role_arn

            # Step 12: Install inference operator
            self.install_inference_operator(
                inference_role_arn=inference_role_arn,
                s3_csi_role_arn=s3_csi_role_arn,
                jumpstart_gated_role_arn=jumpstart_role_arn
            )

            # Step 13: Annotate service account
            self.annotate_service_account(inference_role_arn)

            # Step 14: Verify installation
            results['verified'] = self.verify_installation()

            # Step 15: Deploy test model (optional)
            if not skip_test_deployment:
                self.deploy_test_model()

            results['success'] = True
            logger.info("Setup completed successfully!")

        except Exception as e:
            logger.error(f"Setup failed: {e}")
            results['error'] = str(e)
            raise

        return results

    def configure_iam_only(self) -> Dict[str, str]:
        """
        Configure only IAM roles and policies.

        Returns:
            Dictionary mapping role names to ARNs
        """
        roles = {}

        # Associate OIDC first (required for trust policies)
        self.update_kubeconfig()
        self.associate_oidc_provider()

        # Create roles
        roles['inference'] = self.create_inference_operator_role()
        roles['keda'] = self.create_keda_role()

        if self.config.enable_jumpstart_gated:
            roles['jumpstart_gated'] = self.create_jumpstart_gated_role()

        return roles


# ==============================================================================
# CLI Interface
# ==============================================================================

def main():
    """Command-line interface for HyperPod inference operator setup."""
    import argparse

    parser = argparse.ArgumentParser(
        description="HyperPod Inference Operator Setup"
    )

    parser.add_argument(
        '--hyperpod-cluster',
        required=True,
        help='Name of the HyperPod cluster'
    )
    parser.add_argument(
        '--region',
        required=True,
        help='AWS region'
    )
    parser.add_argument(
        '--s3-bucket',
        required=True,
        help='S3 bucket for TLS certificates'
    )
    parser.add_argument(
        '--kubeconfig',
        help='Path to kubeconfig file'
    )
    parser.add_argument(
        '--skip-nvidia',
        action='store_true',
        help='Skip NVIDIA device plugin installation'
    )
    parser.add_argument(
        '--skip-s3-csi',
        action='store_true',
        help='Skip S3 CSI driver installation'
    )
    parser.add_argument(
        '--install-fsx-csi',
        action='store_true',
        help='Install FSx CSI driver'
    )
    parser.add_argument(
        '--enable-jumpstart-gated',
        action='store_true',
        help='Enable JumpStart gated model access'
    )
    parser.add_argument(
        '--skip-test-deployment',
        action='store_true',
        help='Skip test model deployment'
    )
    parser.add_argument(
        '--iam-only',
        action='store_true',
        help='Configure only IAM roles and policies'
    )

    args = parser.parse_args()

    # Create configuration
    config = SetupConfig(
        hyperpod_cluster_name=args.hyperpod_cluster,
        region=args.region,
        s3_bucket_name=args.s3_bucket,
        install_nvidia_plugin=not args.skip_nvidia,
        install_s3_csi=not args.skip_s3_csi,
        install_fsx_csi=args.install_fsx_csi,
        enable_jumpstart_gated=args.enable_jumpstart_gated
    )

    # Create setup manager
    setup = HyperPodInferenceOperatorSetup(
        hyperpod_cluster_name=args.hyperpod_cluster,
        region=args.region,
        s3_bucket_name=args.s3_bucket,
        config=config,
        kubeconfig_path=args.kubeconfig
    )

    # Run setup
    if args.iam_only:
        roles = setup.configure_iam_only()
        print("\nIAM Roles Created:")
        for name, arn in roles.items():
            print(f"  {name}: {arn}")
    else:
        results = setup.run_full_setup(
            skip_test_deployment=args.skip_test_deployment
        )
        print("\nSetup Results:")
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
