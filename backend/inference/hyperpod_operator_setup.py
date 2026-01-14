"""
HyperPod Inference Operator Setup Module

Provides functions to check and install the HyperPod Inference Operator on EKS clusters.
This operator is required for deploying models using InferenceEndpointConfig CRD.

Reference: https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-model-deployment-setup.html
"""

import os
import subprocess
import logging
import boto3
import json
import time
from typing import Optional, Tuple

from logger_config import setup_logger
logger = setup_logger('hyperpod_operator_setup.py', level=logging.INFO)


def check_inference_operator_installed(eks_cluster_name: str, region: str) -> Tuple[bool, str]:
    """
    Check if the HyperPod Inference Operator is installed on the cluster.

    Args:
        eks_cluster_name: EKS cluster name
        region: AWS region

    Returns:
        Tuple of (is_installed, message)
    """
    try:
        # Update kubeconfig
        kubeconfig_path = _get_kubeconfig(eks_cluster_name, region)

        # Check if the CRD exists
        cmd = [
            "kubectl", "--kubeconfig", kubeconfig_path,
            "get", "crd", "inferenceendpointconfigs.inference.sagemaker.aws.amazon.com"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            logger.info("HyperPod Inference Operator CRD is installed")
            return True, "Inference operator is installed"
        else:
            logger.info("HyperPod Inference Operator CRD is not installed")
            return False, "Inference operator is not installed"

    except subprocess.TimeoutExpired:
        return False, "Timeout checking operator status"
    except Exception as e:
        logger.error(f"Error checking operator: {e}")
        return False, f"Error checking operator: {e}"


def check_operator_pods_running(eks_cluster_name: str, region: str) -> Tuple[bool, str]:
    """
    Check if the inference operator pods are running.

    Args:
        eks_cluster_name: EKS cluster name
        region: AWS region

    Returns:
        Tuple of (is_running, message)
    """
    try:
        kubeconfig_path = _get_kubeconfig(eks_cluster_name, region)

        # Check operator pods in hyperpod-inference-system namespace
        cmd = [
            "kubectl", "--kubeconfig", kubeconfig_path,
            "get", "pods", "-n", "hyperpod-inference-system",
            "-l", "app.kubernetes.io/name=hyperpod-inference-operator",
            "-o", "jsonpath={.items[*].status.phase}"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0 and "Running" in result.stdout:
            return True, "Operator pods are running"
        else:
            return False, "Operator pods are not running"

    except Exception as e:
        logger.error(f"Error checking operator pods: {e}")
        return False, f"Error: {e}"


def setup_inference_operator(
    eks_cluster_name: str,
    hyperpod_cluster_name: str,
    hyperpod_cluster_arn: str,
    region: str,
    account_id: str = None,
    s3_bucket_for_certs: str = None,
    s3_mount_bucket: str = None
) -> Tuple[bool, str]:
    """
    Setup the HyperPod Inference Operator on an EKS cluster.

    This function performs the following steps:
    1. Associate OIDC provider
    2. Create IAM roles and policies
    3. Install prerequisites (NVIDIA plugin, cert-manager, KEDA)
    4. Setup S3 Mountpoint PV/PVC
    5. Install the inference operator via Helm

    Args:
        eks_cluster_name: EKS cluster name
        hyperpod_cluster_name: HyperPod cluster name
        hyperpod_cluster_arn: HyperPod cluster ARN
        region: AWS region
        account_id: AWS account ID (auto-detected if not provided)
        s3_bucket_for_certs: S3 bucket for TLS certificates (optional)
        s3_mount_bucket: S3 bucket for mountpoint (defaults to sagemaker-{region}-{account_id})

    Returns:
        Tuple of (success, message)
    """
    logger.info(f"Setting up HyperPod Inference Operator on {eks_cluster_name}")

    try:
        # Get AWS account ID if not provided
        if not account_id:
            sts = boto3.client('sts', region_name=region)
            account_id = sts.get_caller_identity()['Account']

        kubeconfig_path = _get_kubeconfig(eks_cluster_name, region)

        # Step 1: Associate OIDC provider
        logger.info("Step 1: Associating OIDC provider...")
        success, msg = _associate_oidc_provider(eks_cluster_name, region)
        if not success:
            return False, f"Failed to associate OIDC provider: {msg}"

        # Step 1.5: Install EKS Pod Identity Agent (required for pod identity)
        logger.info("Step 1.5: Installing EKS Pod Identity Agent...")
        success, msg = _install_eks_pod_identity_agent(eks_cluster_name, region)
        if not success:
            # Log warning but continue - some features may still work without it
            logger.warning(f"EKS Pod Identity Agent installation failed (continuing): {msg}")

        # Step 2: Get OIDC ID and VPC ID
        eks_client = boto3.client('eks', region_name=region)
        cluster_info = eks_client.describe_cluster(name=eks_cluster_name)['cluster']
        oidc_url = cluster_info['identity']['oidc']['issuer']
        oidc_id = oidc_url.split('/')[-1]
        vpc_id = cluster_info['resourcesVpcConfig']['vpcId']

        # Step 3: Create IAM roles and policies
        logger.info("Step 2: Creating IAM roles and policies...")
        execution_role_arn, msg = _create_inference_operator_role(
            eks_cluster_name, hyperpod_cluster_name, region, account_id, oidc_id
        )
        if not execution_role_arn:
            return False, f"Failed to create IAM role: {msg}"

        # Step 4: Install NVIDIA device plugin (if not installed)
        logger.info("Step 3: Installing NVIDIA device plugin...")
        _install_nvidia_plugin(kubeconfig_path)

        # Step 5: Create namespaces
        logger.info("Step 4: Creating namespaces...")
        _create_namespaces(kubeconfig_path)

        # Step 6: Install AWS Load Balancer Controller
        logger.info("Step 5: Setting up AWS Load Balancer Controller...")
        _setup_alb_controller(eks_cluster_name, region, account_id, oidc_id)

        # Step 7: Create S3 CSI Driver role and install EKS addon
        # Note: The role ARN is no longer passed to Helm since we disable the s3 subchart
        logger.info("Step 6: Creating S3 CSI Driver role...")
        _create_s3_csi_driver_role(eks_cluster_name, region, account_id, oidc_id)

        # Step 7.5: Setup S3 Mountpoint (PV/PVC for SageMaker default bucket)
        logger.info("Step 6.5: Setting up S3 Mountpoint PV/PVC...")
        # Use provided bucket or default to SageMaker default bucket
        actual_s3_mount_bucket = s3_mount_bucket or f"sagemaker-{region}-{account_id}"
        s3_success, s3_msg = _setup_s3_mountpoint(
            kubeconfig_path=kubeconfig_path,
            eks_cluster_name=eks_cluster_name,
            region=region,
            account_id=account_id,
            s3_bucket_name=actual_s3_mount_bucket,
            namespace="default"
        )
        if not s3_success:
            logger.warning(f"S3 Mountpoint setup failed (non-blocking): {s3_msg}")
        else:
            logger.info(f"S3 Mountpoint setup completed: {s3_msg}")

        # Step 8: Create KEDA operator role
        logger.info("Step 7: Creating KEDA operator role...")
        keda_role_arn, _ = _create_keda_operator_role(eks_cluster_name, region, account_id, oidc_id)

        # Step 9: Install cert-manager (required for TLS certificates)
        logger.info("Step 8: Installing cert-manager...")
        cert_success, cert_msg = _install_cert_manager(kubeconfig_path)
        if not cert_success:
            return False, f"Failed to install cert-manager: {cert_msg}"

        # Step 10: Install the inference operator
        logger.info("Step 9: Installing HyperPod Inference Operator...")
        success, msg = _install_inference_operator_helm(
            kubeconfig_path=kubeconfig_path,
            eks_cluster_name=eks_cluster_name,
            hyperpod_cluster_arn=hyperpod_cluster_arn,
            region=region,
            vpc_id=vpc_id,
            execution_role_arn=execution_role_arn,
            account_id=account_id,
            keda_role_arn=keda_role_arn,
            s3_bucket_for_certs=s3_bucket_for_certs
        )

        if not success:
            return False, f"Failed to install inference operator: {msg}"

        logger.info("HyperPod Inference Operator setup completed successfully")
        return True, "Inference operator installed successfully"

    except Exception as e:
        error_msg = f"Failed to setup inference operator: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def _get_kubeconfig(eks_cluster_name: str, region: str) -> str:
    """Generate and return kubeconfig path for the cluster."""
    kubeconfig_dir = os.path.expanduser("~/.kube")
    os.makedirs(kubeconfig_dir, exist_ok=True)
    kubeconfig_path = os.path.join(kubeconfig_dir, f"config-{eks_cluster_name}")

    cmd = [
        "aws", "eks", "update-kubeconfig",
        "--name", eks_cluster_name,
        "--region", region,
        "--kubeconfig", kubeconfig_path
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
    return kubeconfig_path


def _associate_oidc_provider(eks_cluster_name: str, region: str) -> Tuple[bool, str]:
    """Associate IAM OIDC provider with the EKS cluster."""
    try:
        cmd = [
            "eksctl", "utils", "associate-iam-oidc-provider",
            "--region", region,
            "--cluster", eks_cluster_name,
            "--approve"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            # Check if already associated
            if "already associated" in result.stderr.lower() or "already exists" in result.stderr.lower():
                return True, "OIDC provider already associated"
            return False, result.stderr
        return True, "OIDC provider associated"
    except Exception as e:
        return False, str(e)


def _create_inference_operator_role(
    eks_cluster_name: str,
    hyperpod_cluster_name: str,
    region: str,
    account_id: str,
    oidc_id: str
) -> Tuple[Optional[str], str]:
    """Create IAM role for the inference operator."""
    iam = boto3.client('iam', region_name=region)

    role_name = f"HyperpodInferenceRole-{hyperpod_cluster_name}"[:64]
    policy_name = f"HyperpodInferencePolicy-{hyperpod_cluster_name}"[:64]

    # Trust policy
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": ["sagemaker.amazonaws.com"]},
                "Action": "sts:AssumeRole"
            },
            {
                "Effect": "Allow",
                "Principal": {
                    "Federated": f"arn:aws:iam::{account_id}:oidc-provider/oidc.eks.{region}.amazonaws.com/id/{oidc_id}"
                },
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringLike": {
                        f"oidc.eks.{region}.amazonaws.com/id/{oidc_id}:aud": "sts.amazonaws.com",
                        f"oidc.eks.{region}.amazonaws.com/id/{oidc_id}:sub": "system:serviceaccount:*:*"
                    }
                }
            }
        ]
    }

    # Permission policy - complete policy as per AWS documentation
    # Reference: https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-model-deployment-setup.html
    permission_policy = {
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
                    "ecr:GetAuthorizationToken", "ecr:BatchCheckLayerAvailability",
                    "ecr:GetDownloadUrlForLayer", "ecr:GetRepositoryPolicy",
                    "ecr:DescribeRepositories", "ecr:ListImages", "ecr:DescribeImages",
                    "ecr:BatchGetImage", "ecr:GetLifecyclePolicy",
                    "ecr:GetLifecyclePolicyPreview", "ecr:ListTagsForResource",
                    "ecr:DescribeImageScanFindings"
                ],
                "Resource": ["*"]
            },
            {
                "Sid": "EC2Access",
                "Effect": "Allow",
                "Action": [
                    "ec2:AssignPrivateIpAddresses", "ec2:AttachNetworkInterface",
                    "ec2:CreateNetworkInterface", "ec2:DeleteNetworkInterface",
                    "ec2:DescribeInstances", "ec2:DescribeTags",
                    "ec2:DescribeNetworkInterfaces", "ec2:DescribeInstanceTypes",
                    "ec2:DescribeSubnets", "ec2:DetachNetworkInterface",
                    "ec2:ModifyNetworkInterfaceAttribute", "ec2:UnassignPrivateIpAddresses",
                    "ec2:CreateTags", "ec2:DescribeRouteTables", "ec2:DescribeSecurityGroups",
                    "ec2:DescribeVolumes", "ec2:DescribeVolumesModifications", "ec2:DescribeVpcs",
                    "ec2:CreateVpcEndpointServiceConfiguration", "ec2:DeleteVpcEndpointServiceConfigurations",
                    "ec2:DescribeVpcEndpointServiceConfigurations", "ec2:ModifyVpcEndpointServicePermissions"
                ],
                "Resource": ["*"]
            },
            {
                "Sid": "EKSAuthAccess",
                "Effect": "Allow",
                "Action": ["eks-auth:AssumeRoleForPodIdentity"],
                "Resource": ["*"]
            },
            {
                "Sid": "EKSAccess",
                "Effect": "Allow",
                "Action": [
                    "eks:AssociateAccessPolicy", "eks:Describe*", "eks:List*",
                    "eks:AccessKubernetesApi"
                ],
                "Resource": ["*"]
            },
            {
                "Sid": "ApiGatewayAccess",
                "Effect": "Allow",
                "Action": [
                    "apigateway:POST", "apigateway:GET", "apigateway:PUT",
                    "apigateway:PATCH", "apigateway:DELETE", "apigateway:UpdateRestApiPolicy"
                ],
                "Resource": [
                    "arn:aws:apigateway:*::/vpclinks", "arn:aws:apigateway:*::/vpclinks/*",
                    "arn:aws:apigateway:*::/restapis", "arn:aws:apigateway:*::/restapis/*"
                ]
            },
            {
                "Sid": "ElasticLoadBalancingAccess",
                "Effect": "Allow",
                "Action": [
                    "elasticloadbalancing:CreateLoadBalancer", "elasticloadbalancing:DescribeLoadBalancers",
                    "elasticloadbalancing:DescribeLoadBalancerAttributes", "elasticloadbalancing:DescribeListeners",
                    "elasticloadbalancing:DescribeListenerCertificates", "elasticloadbalancing:DescribeSSLPolicies",
                    "elasticloadbalancing:DescribeRules", "elasticloadbalancing:DescribeTargetGroups",
                    "elasticloadbalancing:DescribeTargetGroupAttributes", "elasticloadbalancing:DescribeTargetHealth",
                    "elasticloadbalancing:DescribeTags", "elasticloadbalancing:DescribeTrustStores",
                    "elasticloadbalancing:DescribeListenerAttributes"
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
                "Sid": "AllowPassRoleToSageMaker",
                "Effect": "Allow",
                "Action": ["iam:PassRole"],
                "Resource": "arn:aws:iam::*:role/*",
                "Condition": {
                    "StringEquals": {"iam:PassedToService": "sagemaker.amazonaws.com"}
                }
            },
            {
                "Sid": "AcmAccess",
                "Effect": "Allow",
                "Action": ["acm:ImportCertificate", "acm:DeleteCertificate"],
                "Resource": ["*"]
            }
        ]
    }

    try:
        # Check if role exists
        try:
            role = iam.get_role(RoleName=role_name)
            role_arn = role['Role']['Arn']
            logger.info(f"IAM role already exists: {role_name}")
            return role_arn, "Role already exists"
        except iam.exceptions.NoSuchEntityException:
            pass

        # Create role
        role_response = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="IAM role for HyperPod Inference Operator"
        )
        role_arn = role_response['Role']['Arn']

        # Put inline policy
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName="InferenceOperatorInlinePolicy",
            PolicyDocument=json.dumps(permission_policy)
        )

        logger.info(f"Created IAM role: {role_name}")
        return role_arn, "Role created successfully"

    except Exception as e:
        logger.error(f"Failed to create IAM role: {e}")
        return None, str(e)


def _install_nvidia_plugin(kubeconfig_path: str) -> bool:
    """Install NVIDIA device plugin if not already installed."""
    try:
        # Check if already installed
        cmd = [
            "kubectl", "--kubeconfig", kubeconfig_path,
            "get", "daemonset", "-n", "kube-system", "nvidia-device-plugin-daemonset"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            logger.info("NVIDIA device plugin already installed")
            return True

        # Install
        cmd = [
            "kubectl", "--kubeconfig", kubeconfig_path,
            "create", "-f",
            "https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.5/nvidia-device-plugin.yml"
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        logger.info("NVIDIA device plugin installed")
        return True
    except Exception as e:
        logger.warning(f"Failed to install NVIDIA plugin: {e}")
        return False


def _create_namespaces(kubeconfig_path: str) -> None:
    """Create required namespaces."""
    namespaces = ["keda", "cert-manager", "hyperpod-inference-system"]
    for ns in namespaces:
        try:
            cmd = [
                "kubectl", "--kubeconfig", kubeconfig_path,
                "create", "namespace", ns
            ]
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except:
            pass  # Namespace might already exist

    # Add Helm ownership labels to hyperpod-inference-system namespace
    # This allows Helm to adopt the namespace if it was created before
    _label_namespace_for_helm(kubeconfig_path, "hyperpod-inference-system",
                               "hyperpod-inference-operator", "kube-system")


def _label_namespace_for_helm(kubeconfig_path: str, namespace: str,
                               release_name: str, release_namespace: str) -> None:
    """Add Helm ownership labels and annotations to a namespace."""
    try:
        # Add label
        cmd = [
            "kubectl", "--kubeconfig", kubeconfig_path,
            "label", "namespace", namespace,
            "app.kubernetes.io/managed-by=Helm",
            "--overwrite"
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        # Add annotations
        cmd = [
            "kubectl", "--kubeconfig", kubeconfig_path,
            "annotate", "namespace", namespace,
            f"meta.helm.sh/release-name={release_name}",
            f"meta.helm.sh/release-namespace={release_namespace}",
            "--overwrite"
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        logger.info(f"Added Helm ownership labels to namespace {namespace}")
    except Exception as e:
        logger.warning(f"Failed to label namespace {namespace} for Helm: {e}")


def _label_cert_manager_for_helm(kubeconfig_path: str, release_name: str = "hyperpod-inference-operator",
                                   release_namespace: str = "kube-system") -> None:
    """
    Add Helm ownership labels to existing cert-manager resources.

    This is needed when cert-manager was installed via kubectl apply but needs to be
    adopted by Helm (e.g., when it's a dependency of the inference operator chart).

    IMPORTANT: When cert-manager is a sub-chart dependency of another chart,
    the release_name must be the PARENT chart's release name, not "cert-manager".

    Args:
        kubeconfig_path: Path to kubeconfig
        release_name: Helm release name (use parent chart name if cert-manager is a sub-chart)
        release_namespace: Namespace where the Helm release is tracked
    """
    # logger.info("Labeling cert-manager resources for Helm adoption...")

    # Resource types to label in cert-manager namespace
    cert_manager_resources = [
        ("deployment", "cert-manager"),
        ("deployment", "cert-manager-cainjector"),
        ("deployment", "cert-manager-webhook"),
        ("service", "cert-manager"),
        ("service", "cert-manager-webhook"),
        ("serviceaccount", "cert-manager"),
        ("serviceaccount", "cert-manager-cainjector"),
        ("serviceaccount", "cert-manager-webhook"),
    ]

    # Label resources in cert-manager namespace
    for resource_type, resource_name in cert_manager_resources:
        try:
            # Check if resource exists
            cmd = [
                "kubectl", "--kubeconfig", kubeconfig_path,
                "get", resource_type, resource_name, "-n", "cert-manager"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                continue

            # Add labels
            cmd = [
                "kubectl", "--kubeconfig", kubeconfig_path,
                "label", resource_type, resource_name, "-n", "cert-manager",
                "app.kubernetes.io/managed-by=Helm",
                "--overwrite"
            ]
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            # Add annotations
            cmd = [
                "kubectl", "--kubeconfig", kubeconfig_path,
                "annotate", resource_type, resource_name, "-n", "cert-manager",
                f"meta.helm.sh/release-name={release_name}",
                f"meta.helm.sh/release-namespace={release_namespace}",
                "--overwrite"
            ]
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except Exception as e:
            logger.debug(f"Could not label {resource_type}/{resource_name}: {e}")

    # Label cert-manager CRDs (these are cluster-scoped)
    cert_manager_crds = [
        "certificaterequests.cert-manager.io",
        "certificates.cert-manager.io",
        "challenges.acme.cert-manager.io",
        "clusterissuers.cert-manager.io",
        "issuers.cert-manager.io",
        "orders.acme.cert-manager.io",
    ]

    for crd_name in cert_manager_crds:
        try:
            # Check if CRD exists
            cmd = [
                "kubectl", "--kubeconfig", kubeconfig_path,
                "get", "crd", crd_name
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                continue

            # Add labels
            cmd = [
                "kubectl", "--kubeconfig", kubeconfig_path,
                "label", "crd", crd_name,
                "app.kubernetes.io/managed-by=Helm",
                "--overwrite"
            ]
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            # Add annotations
            cmd = [
                "kubectl", "--kubeconfig", kubeconfig_path,
                "annotate", "crd", crd_name,
                f"meta.helm.sh/release-name={release_name}",
                f"meta.helm.sh/release-namespace={release_namespace}",
                "--overwrite"
            ]
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except Exception as e:
            logger.debug(f"Could not label CRD {crd_name}: {e}")

    # Label cert-manager namespace
    _label_namespace_for_helm(kubeconfig_path, "cert-manager", release_name, release_namespace)

    logger.info("Finished labeling cert-manager resources for Helm adoption")


def _install_cert_manager(kubeconfig_path: str) -> Tuple[bool, str]:
    """Install cert-manager for TLS certificate management."""
    try:
        # Check if cert-manager is already installed
        cmd = [
            "kubectl", "--kubeconfig", kubeconfig_path,
            "get", "deployment", "-n", "cert-manager", "cert-manager"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            logger.info("cert-manager is already installed")
            return True, "Already installed"

        # Install cert-manager using kubectl apply
        logger.info("Installing cert-manager...")
        cert_manager_version = "v1.14.5"
        cert_manager_url = f"https://github.com/cert-manager/cert-manager/releases/download/{cert_manager_version}/cert-manager.yaml"

        cmd = [
            "kubectl", "--kubeconfig", kubeconfig_path,
            "apply", "-f", cert_manager_url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

        if result.returncode != 0:
            logger.error(f"Failed to install cert-manager: {result.stderr}")
            return False, f"Failed to install cert-manager: {result.stderr}"

        # Wait for cert-manager to be ready
        logger.info("Waiting for cert-manager to be ready...")
        for _ in range(30):  # Wait up to 5 minutes
            cmd = [
                "kubectl", "--kubeconfig", kubeconfig_path,
                "get", "deployment", "-n", "cert-manager", "cert-manager",
                "-o", "jsonpath={.status.readyReplicas}"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip() and int(result.stdout.strip()) > 0:
                logger.info("cert-manager is ready")
                break
            time.sleep(10)

        # Wait a bit more for CRDs to be fully ready
        time.sleep(10)

        logger.info("cert-manager installed successfully")
        return True, "Installed successfully"

    except Exception as e:
        logger.error(f"Failed to install cert-manager: {e}")
        return False, str(e)


def _create_keda_operator_role(
    eks_cluster_name: str,
    region: str,
    account_id: str,
    oidc_id: str
) -> Tuple[Optional[str], str]:
    """Create IAM role for KEDA operator."""
    iam = boto3.client('iam', region_name=region)

    role_name = f"keda-operator-role-{eks_cluster_name}"[:64]

    # Trust policy for the keda-operator service account
    trust_policy = {
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

    # KEDA operator policy - CloudWatch and SQS access for autoscaling
    keda_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CloudWatchAccess",
                "Effect": "Allow",
                "Action": [
                    "cloudwatch:GetMetricData",
                    "cloudwatch:GetMetricStatistics",
                    "cloudwatch:ListMetrics",
                    "cloudwatch:DescribeAlarms"
                ],
                "Resource": ["*"]
            },
            {
                "Sid": "SQSAccess",
                "Effect": "Allow",
                "Action": [
                    "sqs:GetQueueAttributes",
                    "sqs:GetQueueUrl"
                ],
                "Resource": ["*"]
            }
        ]
    }

    try:
        # Check if role exists
        try:
            role = iam.get_role(RoleName=role_name)
            role_arn = role['Role']['Arn']
            logger.info(f"KEDA operator role already exists: {role_name}")
            return role_arn, "Role already exists"
        except iam.exceptions.NoSuchEntityException:
            pass

        # Create role
        role_response = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="IAM role for KEDA operator"
        )
        role_arn = role_response['Role']['Arn']

        # Put inline policy
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName="KedaOperatorPolicy",
            PolicyDocument=json.dumps(keda_policy)
        )

        logger.info(f"Created KEDA operator role: {role_name}")
        return role_arn, "Role created successfully"

    except Exception as e:
        logger.error(f"Failed to create KEDA operator role: {e}")
        return None, str(e)


def _create_s3_csi_driver_role(
    eks_cluster_name: str,
    region: str,
    account_id: str,
    oidc_id: str
) -> Tuple[Optional[str], str]:
    """Create IAM role for S3 CSI Driver (Mountpoint for S3)."""
    iam = boto3.client('iam', region_name=region)

    role_name = f"SM_HP_S3_CSI_ROLE-{eks_cluster_name}"[:64]

    # Trust policy for the s3-csi-driver-sa service account
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Federated": f"arn:aws:iam::{account_id}:oidc-provider/oidc.eks.{region}.amazonaws.com/id/{oidc_id}"
                },
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringLike": {
                        f"oidc.eks.{region}.amazonaws.com/id/{oidc_id}:aud": "sts.amazonaws.com",
                        f"oidc.eks.{region}.amazonaws.com/id/{oidc_id}:sub": "system:serviceaccount:kube-system:s3-csi-driver-sa"
                    }
                }
            }
        ]
    }

    # S3 access policy - allow access to all buckets for model loading
    s3_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "MountpointAccess",
                "Effect": "Allow",
                "Action": [
                    "s3:ListBucket",
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:AbortMultipartUpload",
                    "s3:DeleteObject"
                ],
                "Resource": ["*"]
            }
        ]
    }

    try:
        # Check if role exists
        try:
            role = iam.get_role(RoleName=role_name)
            role_arn = role['Role']['Arn']
            logger.info(f"S3 CSI Driver role already exists: {role_name}")
            # Still need to install the addon
            _install_s3_csi_addon(eks_cluster_name, region, role_arn)
            return role_arn, "Role already exists"
        except iam.exceptions.NoSuchEntityException:
            pass

        # Create role
        role_response = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="IAM role for S3 CSI Driver (Mountpoint for S3)"
        )
        role_arn = role_response['Role']['Arn']

        # Put inline policy
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName="S3MountpointAccessPolicy",
            PolicyDocument=json.dumps(s3_policy)
        )

        logger.info(f"Created S3 CSI Driver role: {role_name}")

        # Create IAM service account and install S3 CSI driver addon
        _install_s3_csi_addon(eks_cluster_name, region, role_arn)

        return role_arn, "Role created successfully"

    except Exception as e:
        logger.error(f"Failed to create S3 CSI Driver role: {e}")
        return None, str(e)


def _setup_s3_mountpoint(
    kubeconfig_path: str,
    eks_cluster_name: str,
    region: str,
    account_id: str,
    s3_bucket_name: str = None,
    namespace: str = "default"
) -> Tuple[bool, str]:
    """
    Setup S3 Mountpoint with PersistentVolume and PersistentVolumeClaim.

    This creates the PV and PVC for S3 bucket access using the Mountpoint CSI driver.

    Args:
        kubeconfig_path: Path to kubeconfig file
        eks_cluster_name: EKS cluster name
        region: AWS region
        account_id: AWS account ID
        s3_bucket_name: S3 bucket name (defaults to SageMaker default bucket)
        namespace: Kubernetes namespace for PVC (default: "default")

    Returns:
        Tuple of (success, message)
    """
    try:
        # Use SageMaker default bucket if not specified
        if not s3_bucket_name:
            s3_bucket_name = f"sagemaker-{region}-{account_id}"
            logger.info(f"Using SageMaker default bucket: {s3_bucket_name}")

        # Sanitize bucket name for Kubernetes resource names (replace dots with dashes)
        safe_bucket_name = s3_bucket_name.replace(".", "-")

        pv_name = f"s3-pv-{safe_bucket_name}"
        pvc_name = "s3-pvc"
        volume_handle = f"s3-csi-driver-volume-{safe_bucket_name}"

        # Check if PV already exists
        cmd = [
            "kubectl", "--kubeconfig", kubeconfig_path,
            "get", "pv", pv_name
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            logger.info(f"PersistentVolume {pv_name} already exists")
        else:
            # Create PersistentVolume
            logger.info(f"Creating PersistentVolume for S3 bucket: {s3_bucket_name}")
            pv_yaml = f"""apiVersion: v1
kind: PersistentVolume
metadata:
  name: {pv_name}
spec:
  capacity:
    storage: 1200Gi
  accessModes:
    - ReadWriteMany
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  claimRef:
    namespace: {namespace}
    name: {pvc_name}
  mountOptions:
    - allow-delete
    - region {region}
  csi:
    driver: s3.csi.aws.com
    volumeHandle: {volume_handle}
    volumeAttributes:
      bucketName: {s3_bucket_name}
"""
            cmd = [
                "kubectl", "--kubeconfig", kubeconfig_path,
                "apply", "-f", "-"
            ]
            result = subprocess.run(
                cmd, input=pv_yaml, capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                logger.error(f"Failed to create PersistentVolume: {result.stderr}")
                return False, f"Failed to create PV: {result.stderr}"
            logger.info(f"PersistentVolume {pv_name} created")

        # Check if PVC already exists
        cmd = [
            "kubectl", "--kubeconfig", kubeconfig_path,
            "get", "pvc", pvc_name, "-n", namespace
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            logger.info(f"PersistentVolumeClaim {pvc_name} already exists in namespace {namespace}")
        else:
            # Create PersistentVolumeClaim
            logger.info(f"Creating PersistentVolumeClaim in namespace {namespace}")
            pvc_yaml = f"""apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {pvc_name}
  namespace: {namespace}
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: ""
  resources:
    requests:
      storage: 1200Gi
  volumeName: {pv_name}
"""
            cmd = [
                "kubectl", "--kubeconfig", kubeconfig_path,
                "apply", "-f", "-"
            ]
            result = subprocess.run(
                cmd, input=pvc_yaml, capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                logger.error(f"Failed to create PersistentVolumeClaim: {result.stderr}")
                return False, f"Failed to create PVC: {result.stderr}"
            logger.info(f"PersistentVolumeClaim {pvc_name} created in namespace {namespace}")

        # Wait for PVC to be bound
        logger.info("Waiting for PVC to be bound...")
        for _ in range(12):  # Wait up to 2 minutes
            cmd = [
                "kubectl", "--kubeconfig", kubeconfig_path,
                "get", "pvc", pvc_name, "-n", namespace,
                "-o", "jsonpath={.status.phase}"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip() == "Bound":
                logger.info(f"PVC {pvc_name} is Bound")
                break
            time.sleep(10)

        logger.info(f"S3 Mountpoint setup completed for bucket: {s3_bucket_name}")
        logger.info(f"  PV: {pv_name}")
        logger.info(f"  PVC: {pvc_name} (namespace: {namespace})")
        logger.info(f"  Mount path in pods: /mnt/s3")

        return True, f"S3 Mountpoint configured for bucket {s3_bucket_name}"

    except Exception as e:
        logger.error(f"Failed to setup S3 Mountpoint: {e}")
        return False, str(e)


def _wait_for_nodes_ready(kubeconfig_path: str, timeout: int = 300) -> bool:
    """Wait for at least one node to be Ready in the cluster."""
    logger.info("Waiting for nodes to be Ready...")
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            cmd = [
                "kubectl", "--kubeconfig", kubeconfig_path,
                "get", "nodes", "-o",
                "jsonpath={.items[*].status.conditions[?(@.type=='Ready')].status}"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and "True" in result.stdout:
                logger.info("At least one node is Ready")
                return True
        except Exception as e:
            logger.debug(f"Error checking node status: {e}")

        time.sleep(10)

    logger.warning(f"No nodes became Ready within {timeout} seconds")
    return False


def _install_eks_pod_identity_agent(eks_cluster_name: str, region: str) -> Tuple[bool, str]:
    """
    Install the EKS Pod Identity Agent addon.

    This addon is required for pods to assume IAM roles using EKS Pod Identity.
    It must be installed before other components that rely on pod identity.

    Args:
        eks_cluster_name: EKS cluster name
        region: AWS region

    Returns:
        Tuple of (success, message)
    """
    logger.info("Installing EKS Pod Identity Agent addon...")
    eks = boto3.client('eks', region_name=region)
    addon_name = 'eks-pod-identity-agent'

    try:
        # Check if addon already exists
        try:
            response = eks.describe_addon(
                clusterName=eks_cluster_name,
                addonName=addon_name
            )
            status = response['addon']['status']
            if status in ['ACTIVE', 'CREATING', 'UPDATING']:
                logger.info(f"EKS Pod Identity Agent addon already exists with status: {status}")
                if status == 'ACTIVE':
                    return True, "Addon already installed and active"
                # Wait for it to become active
                return _wait_for_addon_active(eks_cluster_name, region, addon_name, timeout=300)
        except eks.exceptions.ResourceNotFoundException:
            logger.info("EKS Pod Identity Agent addon not found, will install it")

        # Create the addon
        logger.info("Creating EKS Pod Identity Agent addon...")
        eks.create_addon(
            clusterName=eks_cluster_name,
            addonName=addon_name,
            resolveConflicts='OVERWRITE'
        )

        # Wait for addon to become active
        success, msg = _wait_for_addon_active(eks_cluster_name, region, addon_name, timeout=300)
        if success:
            logger.info("EKS Pod Identity Agent addon installed successfully")
        else:
            logger.warning(f"EKS Pod Identity Agent addon installation issue: {msg}")

        return success, msg

    except Exception as e:
        error_msg = f"Failed to install EKS Pod Identity Agent: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def _wait_for_addon_active(eks_cluster_name: str, region: str, addon_name: str, timeout: int = 300) -> Tuple[bool, str]:
    """Wait for an EKS addon to become ACTIVE."""
    logger.info(f"Waiting for addon {addon_name} to become ACTIVE...")
    eks = boto3.client('eks', region_name=region)
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            response = eks.describe_addon(
                clusterName=eks_cluster_name,
                addonName=addon_name
            )
            status = response['addon']['status']
            logger.info(f"Addon {addon_name} status: {status}")

            if status == 'ACTIVE':
                return True, "Addon is ACTIVE"
            elif status == 'CREATE_FAILED':
                return False, f"Addon creation failed: {response['addon'].get('health', {})}"
            elif status == 'DEGRADED':
                # Get more details about why it's degraded
                health_issues = response['addon'].get('health', {}).get('issues', [])
                if health_issues:
                    issues_str = "; ".join([f"{i.get('code')}: {i.get('message')}" for i in health_issues])
                    logger.warning(f"Addon is DEGRADED: {issues_str}")
                # Continue waiting - DEGRADED can transition to ACTIVE once nodes are ready
        except eks.exceptions.ResourceNotFoundException:
            logger.warning(f"Addon {addon_name} not found")
            return False, "Addon not found"
        except Exception as e:
            logger.debug(f"Error checking addon status: {e}")

        time.sleep(15)

    return False, f"Addon did not become ACTIVE within {timeout} seconds"


def _install_s3_csi_addon(eks_cluster_name: str, region: str, role_arn: str) -> bool:
    """Install the S3 CSI driver addon on EKS cluster with retry logic."""
    try:
        kubeconfig_path = os.path.expanduser(f"~/.kube/config-{eks_cluster_name}")

        # Wait for IAM role to propagate
        logger.info("Waiting 15 seconds for IAM role to propagate...")
        time.sleep(15)

        # Wait for nodes to be ready (CSI driver is a DaemonSet that needs nodes)
        if os.path.exists(kubeconfig_path):
            _wait_for_nodes_ready(kubeconfig_path, timeout=180)

        # Create IAM service account for S3 CSI driver
        logger.info("Creating IAM service account for S3 CSI driver...")
        cmd = [
            "eksctl", "create", "iamserviceaccount",
            "--name", "s3-csi-driver-sa",
            "--namespace", "kube-system",
            "--cluster", eks_cluster_name,
            "--attach-role-arn", role_arn,
            "--approve",
            "--override-existing-serviceaccounts",
            "--region", region
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0 and "already exists" not in result.stderr.lower():
            logger.warning(f"Failed to create service account: {result.stderr}")

        # Label the service account
        if os.path.exists(kubeconfig_path):
            cmd = [
                "kubectl", "--kubeconfig", kubeconfig_path,
                "label", "serviceaccount", "s3-csi-driver-sa",
                "-n", "kube-system",
                "app.kubernetes.io/component=csi-driver",
                "app.kubernetes.io/instance=aws-mountpoint-s3-csi-driver",
                "app.kubernetes.io/managed-by=EKS",
                "app.kubernetes.io/name=aws-mountpoint-s3-csi-driver",
                "--overwrite"
            ]
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        # Install S3 CSI driver addon with retry
        max_retries = 3
        for attempt in range(max_retries):
            logger.info(f"Installing S3 CSI driver addon (attempt {attempt + 1}/{max_retries})...")

            # Check if addon already exists
            eks = boto3.client('eks', region_name=region)
            try:
                response = eks.describe_addon(
                    clusterName=eks_cluster_name,
                    addonName='aws-mountpoint-s3-csi-driver'
                )
                status = response['addon']['status']
                if status == 'ACTIVE':
                    logger.info("S3 CSI driver addon already installed and ACTIVE")
                    return True
                elif status in ['CREATING', 'UPDATING']:
                    logger.info(f"S3 CSI driver addon is {status}, waiting...")
                    success, msg = _wait_for_addon_active(eks_cluster_name, region, 'aws-mountpoint-s3-csi-driver', timeout=300)
                    if success:
                        return True
                    continue
                elif status == 'DEGRADED':
                    # Delete and recreate
                    logger.warning("S3 CSI driver addon is DEGRADED, deleting and recreating...")
                    try:
                        eks.delete_addon(
                            clusterName=eks_cluster_name,
                            addonName='aws-mountpoint-s3-csi-driver'
                        )
                        time.sleep(30)  # Wait for deletion
                    except Exception as e:
                        logger.warning(f"Failed to delete degraded addon: {e}")
            except eks.exceptions.ResourceNotFoundException:
                pass  # Addon doesn't exist, proceed to create

            # Create the addon using boto3 (more reliable than eksctl which can timeout)
            try:
                logger.info("Creating S3 CSI driver addon via AWS API...")
                eks.create_addon(
                    clusterName=eks_cluster_name,
                    addonName='aws-mountpoint-s3-csi-driver',
                    serviceAccountRoleArn=role_arn,
                    resolveConflicts='OVERWRITE'
                )
                logger.info("S3 CSI driver addon creation initiated")
            except eks.exceptions.ResourceInUseException:
                logger.info("S3 CSI driver addon already exists, updating...")
                try:
                    eks.update_addon(
                        clusterName=eks_cluster_name,
                        addonName='aws-mountpoint-s3-csi-driver',
                        serviceAccountRoleArn=role_arn,
                        resolveConflicts='OVERWRITE'
                    )
                except Exception as update_err:
                    logger.warning(f"Failed to update addon: {update_err}")
            except Exception as create_err:
                logger.warning(f"Failed to create S3 CSI addon: {create_err}")
                if attempt < max_retries - 1:
                    logger.info("Retrying after 30 seconds...")
                    time.sleep(30)
                    continue
                return False

            # Wait for addon to become ACTIVE
            success, msg = _wait_for_addon_active(eks_cluster_name, region, 'aws-mountpoint-s3-csi-driver', timeout=300)
            if success:
                logger.info("S3 CSI driver addon installed successfully")
                return True
            else:
                logger.warning(f"S3 CSI driver addon failed to become ACTIVE: {msg}")
                if attempt < max_retries - 1:
                    logger.info("Retrying...")
                    continue

        logger.warning("S3 CSI driver addon installation failed after all retries")
        return False

    except Exception as e:
        logger.warning(f"Failed to install S3 CSI addon: {e}")
        return False


def _create_alb_controller_policy(account_id: str, region: str, policy_name: str) -> Optional[str]:
    """Create IAM policy for AWS Load Balancer Controller."""
    iam = boto3.client('iam', region_name=region)

    # Check if policy already exists
    policy_arn = f"arn:aws:iam::{account_id}:policy/{policy_name}"
    try:
        iam.get_policy(PolicyArn=policy_arn)
        logger.info(f"ALB Controller IAM policy already exists: {policy_name}")
        return policy_arn
    except iam.exceptions.NoSuchEntityException:
        pass

    # AWS Load Balancer Controller IAM Policy
    # Reference: https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.10.0/docs/install/iam_policy.json
    alb_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "iam:CreateServiceLinkedRole"
            ],
            "Resource": "*",
            "Condition": {
                "StringEquals": {
                    "iam:AWSServiceName": "elasticloadbalancing.amazonaws.com"
                }
            }
        },
        {
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeAccountAttributes",
                "ec2:DescribeAddresses",
                "ec2:DescribeAvailabilityZones",
                "ec2:DescribeInternetGateways",
                "ec2:DescribeVpcs",
                "ec2:DescribeVpcPeeringConnections",
                "ec2:DescribeSubnets",
                "ec2:DescribeSecurityGroups",
                "ec2:DescribeInstances",
                "ec2:DescribeNetworkInterfaces",
                "ec2:DescribeTags",
                "ec2:GetCoipPoolUsage",
                "ec2:DescribeCoipPools",
                "ec2:GetSecurityGroupsForVpc",
                "elasticloadbalancing:DescribeLoadBalancers",
                "elasticloadbalancing:DescribeLoadBalancerAttributes",
                "elasticloadbalancing:DescribeListeners",
                "elasticloadbalancing:DescribeListenerCertificates",
                "elasticloadbalancing:DescribeSSLPolicies",
                "elasticloadbalancing:DescribeRules",
                "elasticloadbalancing:DescribeTargetGroups",
                "elasticloadbalancing:DescribeTargetGroupAttributes",
                "elasticloadbalancing:DescribeTargetHealth",
                "elasticloadbalancing:DescribeTags",
                "elasticloadbalancing:DescribeTrustStores",
                "elasticloadbalancing:DescribeListenerAttributes"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "cognito-idp:DescribeUserPoolClient",
                "acm:ListCertificates",
                "acm:DescribeCertificate",
                "iam:ListServerCertificates",
                "iam:GetServerCertificate",
                "waf-regional:GetWebACL",
                "waf-regional:GetWebACLForResource",
                "waf-regional:AssociateWebACL",
                "waf-regional:DisassociateWebACL",
                "wafv2:GetWebACL",
                "wafv2:GetWebACLForResource",
                "wafv2:AssociateWebACL",
                "wafv2:DisassociateWebACL",
                "shield:GetSubscriptionState",
                "shield:DescribeProtection",
                "shield:CreateProtection",
                "shield:DeleteProtection"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "ec2:AuthorizeSecurityGroupIngress",
                "ec2:RevokeSecurityGroupIngress"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "ec2:CreateSecurityGroup"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "ec2:CreateTags"
            ],
            "Resource": "arn:aws:ec2:*:*:security-group/*",
            "Condition": {
                "StringEquals": {
                    "ec2:CreateAction": "CreateSecurityGroup"
                },
                "Null": {
                    "aws:RequestTag/elbv2.k8s.aws/cluster": "false"
                }
            }
        },
        {
            "Effect": "Allow",
            "Action": [
                "ec2:CreateTags",
                "ec2:DeleteTags"
            ],
            "Resource": "arn:aws:ec2:*:*:security-group/*",
            "Condition": {
                "Null": {
                    "aws:RequestTag/elbv2.k8s.aws/cluster": "true",
                    "aws:ResourceTag/elbv2.k8s.aws/cluster": "false"
                }
            }
        },
        {
            "Effect": "Allow",
            "Action": [
                "ec2:AuthorizeSecurityGroupIngress",
                "ec2:RevokeSecurityGroupIngress",
                "ec2:DeleteSecurityGroup"
            ],
            "Resource": "*",
            "Condition": {
                "Null": {
                    "aws:ResourceTag/elbv2.k8s.aws/cluster": "false"
                }
            }
        },
        {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:CreateLoadBalancer",
                "elasticloadbalancing:CreateTargetGroup"
            ],
            "Resource": "*",
            "Condition": {
                "Null": {
                    "aws:RequestTag/elbv2.k8s.aws/cluster": "false"
                }
            }
        },
        {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:CreateListener",
                "elasticloadbalancing:DeleteListener",
                "elasticloadbalancing:CreateRule",
                "elasticloadbalancing:DeleteRule"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:AddTags",
                "elasticloadbalancing:RemoveTags"
            ],
            "Resource": [
                "arn:aws:elasticloadbalancing:*:*:targetgroup/*/*",
                "arn:aws:elasticloadbalancing:*:*:loadbalancer/net/*/*",
                "arn:aws:elasticloadbalancing:*:*:loadbalancer/app/*/*"
            ],
            "Condition": {
                "Null": {
                    "aws:RequestTag/elbv2.k8s.aws/cluster": "true",
                    "aws:ResourceTag/elbv2.k8s.aws/cluster": "false"
                }
            }
        },
        {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:AddTags",
                "elasticloadbalancing:RemoveTags"
            ],
            "Resource": [
                "arn:aws:elasticloadbalancing:*:*:listener/net/*/*/*",
                "arn:aws:elasticloadbalancing:*:*:listener/app/*/*/*",
                "arn:aws:elasticloadbalancing:*:*:listener-rule/net/*/*/*",
                "arn:aws:elasticloadbalancing:*:*:listener-rule/app/*/*/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:ModifyLoadBalancerAttributes",
                "elasticloadbalancing:SetIpAddressType",
                "elasticloadbalancing:SetSecurityGroups",
                "elasticloadbalancing:SetSubnets",
                "elasticloadbalancing:DeleteLoadBalancer",
                "elasticloadbalancing:ModifyTargetGroup",
                "elasticloadbalancing:ModifyTargetGroupAttributes",
                "elasticloadbalancing:DeleteTargetGroup",
                "elasticloadbalancing:ModifyListenerAttributes"
            ],
            "Resource": "*",
            "Condition": {
                "Null": {
                    "aws:ResourceTag/elbv2.k8s.aws/cluster": "false"
                }
            }
        },
        {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:AddTags"
            ],
            "Resource": [
                "arn:aws:elasticloadbalancing:*:*:targetgroup/*/*",
                "arn:aws:elasticloadbalancing:*:*:loadbalancer/net/*/*",
                "arn:aws:elasticloadbalancing:*:*:loadbalancer/app/*/*"
            ],
            "Condition": {
                "StringEquals": {
                    "elasticloadbalancing:CreateAction": [
                        "CreateTargetGroup",
                        "CreateLoadBalancer"
                    ]
                },
                "Null": {
                    "aws:RequestTag/elbv2.k8s.aws/cluster": "false"
                }
            }
        },
        {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:RegisterTargets",
                "elasticloadbalancing:DeregisterTargets"
            ],
            "Resource": "arn:aws:elasticloadbalancing:*:*:targetgroup/*/*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:SetWebAcl",
                "elasticloadbalancing:ModifyListener",
                "elasticloadbalancing:AddListenerCertificates",
                "elasticloadbalancing:RemoveListenerCertificates",
                "elasticloadbalancing:ModifyRule"
            ],
            "Resource": "*"
        }
    ]
}


    try:
        logger.info(f"Creating ALB Controller IAM policy: {policy_name}")
        response = iam.create_policy(
            PolicyName=policy_name,
            PolicyDocument=json.dumps(alb_policy),
            Description="IAM policy for AWS Load Balancer Controller"
        )
        policy_arn = response['Policy']['Arn']
        logger.info(f"Created ALB Controller IAM policy: {policy_arn}")
        return policy_arn
    except Exception as e:
        logger.error(f"Failed to create ALB Controller IAM policy: {e}")
        return None


def _setup_alb_controller(
    eks_cluster_name: str,
    region: str,
    account_id: str,
    oidc_id: str
) -> Optional[str]:
    """Setup AWS Load Balancer Controller service account."""
    try:
        policy_name = f"HyperPodInferenceALBControllerIAMPolicy-{eks_cluster_name}"[:64]

        # Step 1: Create the IAM policy if it doesn't exist
        policy_arn = _create_alb_controller_policy(account_id, region, policy_name)
        if not policy_arn:
            logger.warning("Failed to create ALB Controller IAM policy, continuing anyway...")
            policy_arn = f"arn:aws:iam::{account_id}:policy/{policy_name}"

        # Step 2: Check if service account exists
        cmd = [
            "eksctl", "get", "iamserviceaccount",
            "--cluster", eks_cluster_name,
            "--region", region,
            "--name", "aws-load-balancer-controller",
            "--namespace", "kube-system"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0 and "aws-load-balancer-controller" in result.stdout:
            logger.info("ALB controller service account already exists")
            return f"arn:aws:iam::{account_id}:role/aws-load-balancer-controller-{eks_cluster_name}"

        # Step 3: Create service account with the policy
        logger.info("Creating ALB controller service account...")
        cmd = [
            "eksctl", "create", "iamserviceaccount",
            "--approve",
            "--override-existing-serviceaccounts",
            "--name", "aws-load-balancer-controller",
            "--namespace", "kube-system",
            "--cluster", eks_cluster_name,
            "--attach-policy-arn", policy_arn,
            "--region", region
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            logger.warning(f"Failed to create ALB controller service account: {result.stderr}")
        else:
            logger.info("ALB controller service account created successfully")

        return f"arn:aws:iam::{account_id}:role/aws-load-balancer-controller-{eks_cluster_name}"

    except Exception as e:
        logger.warning(f"Failed to setup ALB controller: {e}")
        return None


def _install_inference_operator_helm(
    kubeconfig_path: str,
    eks_cluster_name: str,
    hyperpod_cluster_arn: str,
    region: str,
    vpc_id: str,
    execution_role_arn: str,
    account_id: str,
    keda_role_arn: Optional[str] = None,
    s3_bucket_for_certs: Optional[str] = None
) -> Tuple[bool, str]:
    """Install the HyperPod Inference Operator using Helm."""
    try:
        # Check if already installed
        cmd = [
            "helm", "--kubeconfig", kubeconfig_path,
            "list", "-n", "kube-system", "-q"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if "hyperpod-inference-operator" in result.stdout:
            logger.info("HyperPod Inference Operator already installed")
            return True, "Already installed"

        # Clone helm chart if not exists
        helm_chart_dir = "/tmp/sagemaker-hyperpod-cli"
        if not os.path.exists(helm_chart_dir):
            cmd = ["git", "clone", "https://github.com/aws/sagemaker-hyperpod-cli", helm_chart_dir]
            subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        chart_path = os.path.join(helm_chart_dir, "helm_chart/HyperPodHelmChart/charts/inference-operator")

        if not os.path.exists(chart_path):
            return False, f"Helm chart not found at {chart_path}"

        # Check if dependencies are already downloaded
        charts_dir = os.path.join(chart_path, "charts")
        deps_downloaded = os.path.exists(charts_dir) and len(os.listdir(charts_dir)) >= 5

        if not deps_downloaded:
            # Update dependencies only if not already downloaded
            logger.info("Downloading helm chart dependencies (this may take a few minutes)...")
            cmd = ["helm", "dependency", "update", chart_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=chart_path)
            if result.returncode != 0:
                logger.error(f"Failed to update helm dependencies: {result.stderr}")
                return False, f"Failed to update helm dependencies: {result.stderr}"
            logger.info("Helm dependencies downloaded successfully")
        else:
            logger.info("Helm chart dependencies already downloaded, skipping update")

        # Ensure hyperpod-inference-system namespace has Helm ownership labels
        # This is needed in case the namespace was created externally or from a previous failed attempt
        _label_namespace_for_helm(kubeconfig_path, "hyperpod-inference-system",
                                   "hyperpod-inference-operator", "kube-system")

        # Note: S3 CSI driver labeling is no longer needed since we disable the s3 subchart
        # The S3 CSI driver is managed entirely via EKS addon, not Helm

        # Label cert-manager resources for Helm adoption
        # cert-manager is installed via kubectl apply but the inference operator chart
        # includes it as a dependency, so we need to add Helm ownership labels
        # IMPORTANT: Use the PARENT chart's release name (hyperpod-inference-operator),
        # not "cert-manager", since cert-manager is a sub-chart dependency
        logger.info("Labeling cert-manager resources for Helm adoption...")
        _label_cert_manager_for_helm(kubeconfig_path, "hyperpod-inference-operator", "kube-system")

        # Use default SageMaker bucket for certificates if not provided
        if not s3_bucket_for_certs:
            s3_bucket_for_certs = f"sagemaker-{region}-{account_id}"
            logger.info(f"Using default bucket for TLS certificates: {s3_bucket_for_certs}")

        # Ensure the bucket path includes the hyperpod-inference prefix
        cert_s3_path = f"s3://{s3_bucket_for_certs}/hyperpod-inference-certs/{eks_cluster_name}"

        # Install the operator
        # NOTE: We disable cert-manager subchart because it's already installed via kubectl apply
        # The Helm subchart would prefix resources with release name causing webhook conflicts
        # NOTE: We disable s3 (aws-mountpoint-s3-csi-driver) subchart because it's already
        # installed via EKS addon. Installing it again via Helm causes resource conflicts
        # with EKS-managed resources (ServiceAccount, ClusterRole, DaemonSet, CSIDriver).
        helm_cmd = [
            "helm", "--kubeconfig", kubeconfig_path,
            "install", "hyperpod-inference-operator", chart_path,
            "-n", "kube-system",
            "--set", f"region={region}",
            "--set", f"eksClusterName={eks_cluster_name}",
            "--set", f"hyperpodClusterArn={hyperpod_cluster_arn}",
            "--set", f"executionRoleArn={execution_role_arn}",
            "--set", f"alb.region={region}",
            "--set", f"alb.clusterName={eks_cluster_name}",
            "--set", f"alb.vpcId={vpc_id}",
            "--set", f"tlsCertificateS3Bucket={cert_s3_path}",
            # Disable cert-manager subchart - already installed via kubectl apply
            "--set", "cert-manager.enabled=false",
            "--set", "cert-manager.installCRDs=false",
            # Disable S3 CSI driver subchart - already installed via EKS addon
            "--set", "s3.enabled=false",
        ]

        # Note: S3 CSI Driver role ARN is not passed to Helm since we disable the s3 subchart
        # The S3 CSI driver is already configured via EKS addon with the proper role

        # Add KEDA operator role ARN if provided
        if keda_role_arn:
            helm_cmd.extend(["--set", f"keda.podIdentity.aws.irsa.roleArn={keda_role_arn}"])
        
        logger.info(f"Running helm install (this may take several minutes)...")
        logger.info(f"helm cmd: {' '.join(helm_cmd)}")
        result = subprocess.run(helm_cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            return False, f"Helm install failed: {result.stderr}"

        logger.info("HyperPod Inference Operator installed successfully")
        return True, "Installed successfully"

    except Exception as e:
        return False, str(e)


def uninstall_inference_operator(eks_cluster_name: str, region: str) -> Tuple[bool, str]:
    """Uninstall the HyperPod Inference Operator."""
    try:
        kubeconfig_path = _get_kubeconfig(eks_cluster_name, region)

        cmd = [
            "helm", "--kubeconfig", kubeconfig_path,
            "uninstall", "hyperpod-inference-operator",
            "-n", "kube-system"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            return False, result.stderr

        return True, "Operator uninstalled"

    except Exception as e:
        return False, str(e)
