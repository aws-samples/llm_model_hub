"""
HyperPod EKS Cluster Management

Provides CRUD operations for HyperPod EKS clusters.
"""

import sys
import uuid
import time
import json
import asyncio
import subprocess
import tempfile
import os
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

sys.path.append('./')

from model.data_model import (
    CreateClusterRequest,
    ClusterInfo,
    ClusterStatus,
    ListClustersRequest,
    ListClustersResponse,
    GetClusterRequest,
    ClusterResponse,
    DeleteClusterRequest,
    UpdateClusterRequest,
    CommonResponse,
    ListClusterNodesRequest,
    ListClusterNodesResponse,
    ClusterNodeInfo,
)
from db_management.database import DatabaseWrapper
from logger_config import setup_logger
from utils.config import boto_sess, DEFAULT_REGION

logger = setup_logger('eks_clusters.py', log_file='eks_clusters.log')
database = DatabaseWrapper()

# Cluster table name
CLUSTER_TABLE = 'CLUSTER_TABLE'


class ClusterJobExecutor:
    """
    Executor for HyperPod EKS cluster operations.

    Handles the actual AWS API calls for cluster creation, deletion, etc.
    """

    def __init__(self, cluster_id: str):
        self.cluster_id = cluster_id
        self.ec2 = boto_sess.client('ec2')
        self.eks = boto_sess.client('eks')
        self.sagemaker = boto_sess.client('sagemaker')
        self.iam = boto_sess.client('iam')
        self.s3 = boto_sess.client('s3')
        self.sts = boto_sess.client('sts')
        self.account_id = self.sts.get_caller_identity()['Account']
        self.region = DEFAULT_REGION

    def create_eks_cluster_role(self, role_name: str) -> str:
        """Create IAM role for EKS cluster."""
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "eks.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }

        try:
            response = self.iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description="EKS Cluster Role for HyperPod"
            )
            role_arn = response['Role']['Arn']

            # Attach required policies
            policies = [
                'arn:aws:iam::aws:policy/AmazonEKSClusterPolicy',
                'arn:aws:iam::aws:policy/AmazonEKSVPCResourceController'
            ]
            for policy in policies:
                self.iam.attach_role_policy(RoleName=role_name, PolicyArn=policy)

            # Wait for role to propagate
            time.sleep(10)
            logger.info(f"Created EKS cluster role: {role_arn}")
            return role_arn
        except self.iam.exceptions.EntityAlreadyExistsException:
            response = self.iam.get_role(RoleName=role_name)
            return response['Role']['Arn']

    def create_hyperpod_execution_role(self, role_name: str, s3_bucket: str = None) -> str:
        """Create IAM role for HyperPod execution."""
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": ["sagemaker.amazonaws.com"]},
                    "Action": "sts:AssumeRole"
                }
            ]
        }

        try:
            response = self.iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description="HyperPod Execution Role"
            )
            role_arn = response['Role']['Arn']

            # Attach required policies
            policies = [
                'arn:aws:iam::aws:policy/AmazonSageMakerFullAccess',
                'arn:aws:iam::aws:policy/AmazonS3FullAccess',
                'arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly',
                'arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy',  # Required for VPC CNI (aws-node) to manage ENIs
            ]
            for policy in policies:
                self.iam.attach_role_policy(RoleName=role_name, PolicyArn=policy)

            time.sleep(10)
            logger.info(f"Created HyperPod execution role: {role_arn}")
            return role_arn
        except self.iam.exceptions.EntityAlreadyExistsException:
            response = self.iam.get_role(RoleName=role_name)
            return response['Role']['Arn']

    def create_security_group(self, vpc_id: str, name: str) -> str:
        """Create security group for EKS/HyperPod."""
        try:
            response = self.ec2.create_security_group(
                GroupName=name,
                Description=f"Security group for HyperPod cluster",
                VpcId=vpc_id,
                TagSpecifications=[{
                    'ResourceType': 'security-group',
                    'Tags': [{'Key': 'Name', 'Value': name}]
                }]
            )
            sg_id = response['GroupId']

            # Add inbound rules
            self.ec2.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[
                    {
                        'IpProtocol': '-1',
                        'UserIdGroupPairs': [{'GroupId': sg_id}]
                    }
                ]
            )
            logger.info(f"Created security group: {sg_id}")
            return sg_id
        except self.ec2.exceptions.ClientError as e:
            if 'InvalidGroup.Duplicate' in str(e):
                # Get existing security group
                response = self.ec2.describe_security_groups(
                    Filters=[
                        {'Name': 'group-name', 'Values': [name]},
                        {'Name': 'vpc-id', 'Values': [vpc_id]}
                    ]
                )
                return response['SecurityGroups'][0]['GroupId']
            raise

    def create_eks_cluster(
        self,
        cluster_name: str,
        role_arn: str,
        subnet_ids: List[str],
        security_group_ids: List[str],
        kubernetes_version: str = "1.31",
        endpoint_public_access: bool = True,
        endpoint_private_access: bool = True,
        authentication_mode: str = "API_AND_CONFIG_MAP"
    ) -> Dict[str, Any]:
        """Create EKS cluster."""
        logger.info(f"Creating EKS cluster: {cluster_name}")

        try:
            response = self.eks.create_cluster(
                name=cluster_name,
                version=kubernetes_version,
                roleArn=role_arn,
                resourcesVpcConfig={
                    'subnetIds': subnet_ids,
                    'securityGroupIds': security_group_ids,
                    'endpointPublicAccess': endpoint_public_access,
                    'endpointPrivateAccess': endpoint_private_access
                },
                accessConfig={
                    'authenticationMode': authentication_mode
                },
                logging={
                    'clusterLogging': [{
                        'types': ['api', 'audit', 'authenticator', 'controllerManager', 'scheduler'],
                        'enabled': True
                    }]
                }
            )

            cluster = response['cluster']
            logger.info(f"EKS cluster creation initiated: {cluster['arn']}")
            return {
                'name': cluster['name'],
                'arn': cluster['arn'],
                'status': cluster['status']
            }
        except self.eks.exceptions.ResourceInUseException:
            # Cluster already exists
            response = self.eks.describe_cluster(name=cluster_name)
            cluster = response['cluster']
            return {
                'name': cluster['name'],
                'arn': cluster['arn'],
                'status': cluster['status']
            }

    def wait_for_eks_cluster(self, cluster_name: str, timeout: int = 1200) -> Dict[str, Any]:
        """Wait for EKS cluster to become active."""
        logger.info(f"Waiting for EKS cluster {cluster_name} to become active...")

        start_time = time.time()
        while time.time() - start_time < timeout:
            response = self.eks.describe_cluster(name=cluster_name)
            status = response['cluster']['status']

            if status == 'ACTIVE':
                logger.info(f"EKS cluster {cluster_name} is now ACTIVE")
                return response['cluster']
            elif status == 'FAILED':
                raise Exception(f"EKS cluster creation failed: {cluster_name}")

            logger.info(f"EKS cluster status: {status}, waiting...")
            time.sleep(30)

        raise TimeoutError(f"Timeout waiting for EKS cluster {cluster_name}")

    def install_hyperpod_dependencies(self, cluster_name: str) -> bool:
        """Install required HyperPod dependencies on EKS cluster using Helm."""
        logger.info(f"Installing HyperPod dependencies on EKS cluster: {cluster_name}")

        try:
            # Update kubeconfig to access the EKS cluster
            logger.info(f"Updating kubeconfig for EKS cluster: {cluster_name}")
            kubeconfig_cmd = [
                'aws', 'eks', 'update-kubeconfig',
                '--name', cluster_name,
                '--region', self.region
            ]
            result = subprocess.run(kubeconfig_cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                logger.error(f"Failed to update kubeconfig: {result.stderr}")
                return False

            logger.info("Kubeconfig updated successfully")

            # Create temporary directory for cloning the repo
            with tempfile.TemporaryDirectory() as tmpdir:
                logger.info("Cloning sagemaker-hyperpod-cli repository...")
                clone_cmd = [
                    'git', 'clone',
                    'https://github.com/aws/sagemaker-hyperpod-cli.git',
                    os.path.join(tmpdir, 'sagemaker-hyperpod-cli')
                ]
                result = subprocess.run(clone_cmd, capture_output=True, text=True, timeout=300)
                if result.returncode != 0:
                    logger.error(f"Failed to clone repository: {result.stderr}")
                    return False

                helm_chart_dir = os.path.join(tmpdir, 'sagemaker-hyperpod-cli', 'helm_chart')

                # Update Helm dependencies
                logger.info("Updating Helm dependencies...")
                helm_dep_cmd = ['helm', 'dependencies', 'update', 'HyperPodHelmChart']
                result = subprocess.run(
                    helm_dep_cmd,
                    cwd=helm_chart_dir,
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                if result.returncode != 0:
                    logger.error(f"Failed to update Helm dependencies: {result.stderr}")
                    return False

                # Install HyperPod Helm chart
                logger.info("Installing HyperPod Helm chart...")
                helm_install_cmd = [
                    'helm', 'install',
                    'hyperpod-dependencies',
                    'HyperPodHelmChart',
                    '--namespace', 'kube-system',
                    '--create-namespace'
                ]
                result = subprocess.run(
                    helm_install_cmd,
                    cwd=helm_chart_dir,
                    capture_output=True,
                    text=True,
                    timeout=600
                )
                if result.returncode != 0:
                    # Check if already installed
                    if 'already exists' in result.stderr or 'already exists' in result.stdout:
                        logger.warning(f"HyperPod dependencies already installed: {result.stderr}")
                        return True
                    logger.error(f"Failed to install HyperPod Helm chart: {result.stderr}")
                    return False

                logger.info("HyperPod dependencies installed successfully")

                # Wait for pods to be ready
                logger.info("Waiting for HyperPod pods to be ready...")
                time.sleep(30)  # Give pods time to start

                return True

        except subprocess.TimeoutExpired as e:
            logger.error(f"Timeout during HyperPod dependencies installation: {e}")
            return False
        except Exception as e:
            logger.error(f"Error installing HyperPod dependencies: {e}")
            return False

    def create_hyperpod_cluster(
        self,
        cluster_name: str,
        eks_cluster_arn: str,
        execution_role_arn: str,
        subnet_ids: List[str],
        security_group_ids: List[str],
        instance_groups: List[Dict[str, Any]],
        lifecycle_script_s3_uri: Optional[str] = None,
        node_recovery: str = "Automatic",
        node_provisioning_mode: str = "Continuous",
        enable_autoscaling: bool = False
    ) -> Dict[str, Any]:
        """Create HyperPod cluster."""
        logger.info(f"Creating HyperPod cluster: {cluster_name}")

        # Build instance groups config
        instance_groups_config = []
        for ig in instance_groups:
            ig_config = {
                'InstanceGroupName': ig['name'],
                'InstanceType': ig['instance_type'],
                'InstanceCount': ig['instance_count'],
                'ExecutionRole': execution_role_arn,
                'ThreadsPerCore': ig.get('threads_per_core', 1),
            }

            # MinInstanceCount is only supported when NodeProvisioningMode is Continuous
            if node_provisioning_mode == 'Continuous' and ig.get('min_instance_count') is not None:
                ig_config['MinInstanceCount'] = ig['min_instance_count']

            # LifeCycleConfig is REQUIRED - must always be set
            if lifecycle_script_s3_uri:
                lifecycle_config = {
                    'SourceS3Uri': lifecycle_script_s3_uri,
                    'OnCreate': 'on_create.sh'
                }

                # Add deep health checks if enabled
                health_checks = []
                if ig.get('enable_instance_stress_check', False):
                    health_checks.append('InstanceStress')
                if ig.get('enable_instance_connectivity_check', False):
                    health_checks.append('InstanceConnectivity')

                if health_checks:
                    lifecycle_config['OnStartDeepHealthChecks'] = health_checks

                ig_config['LifeCycleConfig'] = lifecycle_config
            else:
                raise ValueError("lifecycle_script_s3_uri is required for creating HyperPod cluster")

            # Kubernetes labels
            k8s_labels = ig.get('kubernetes_labels', {})
            if ig.get('use_spot'):
                k8s_labels['sagemaker.amazonaws.com/node-lifecycle'] = 'spot'

            if k8s_labels:
                ig_config['OverrideKubernetesConfig'] = {
                    'Labels': k8s_labels
                }

            # Training Plan ARN for capacity reservation
            training_plan_arn = ig.get('training_plan_arn')
            if training_plan_arn:
                ig_config['TrainingPlanArn'] = training_plan_arn

            # Additional storage volume (EBS) per instance
            storage_volume_size = ig.get('storage_volume_size', 500)
            if storage_volume_size and storage_volume_size > 0:
                ig_config['InstanceStorageConfigs'] = [{
                    'EbsVolumeConfig': {
                        'VolumeSizeInGB': storage_volume_size
                    }
                }]

            instance_groups_config.append(ig_config)

        # Build cluster config
        cluster_config = {
            'ClusterName': cluster_name,
            'Orchestrator': {
                'Eks': {
                    'ClusterArn': eks_cluster_arn
                }
            },
            'InstanceGroups': instance_groups_config,
            'VpcConfig': {
                'SecurityGroupIds': security_group_ids,
                'Subnets': subnet_ids
            },
            'NodeRecovery': node_recovery,
            'NodeProvisioningMode': node_provisioning_mode
        }

        try:
            # First try with AutoScaling if enabled (requires newer boto3)
            if enable_autoscaling:
                cluster_config['AutoScaling'] = {
                    'AutoScalerType': 'Karpenter',
                    'Mode': 'Enabled'
                }

            response = self.sagemaker.create_cluster(**cluster_config)
            logger.info(f"HyperPod cluster creation initiated: {response['ClusterArn']}")
            return response
        except Exception as e:
            # If AutoScaling parameter is not supported (older boto3), retry without it
            error_str = str(e)
            if 'AutoScaling' in error_str and enable_autoscaling:
                logger.warning(f"AutoScaling parameter not supported ({error_str}), retrying without it")
                cluster_config.pop('AutoScaling', None)
                response = self.sagemaker.create_cluster(**cluster_config)
                logger.info(f"HyperPod cluster creation initiated (without AutoScaling): {response['ClusterArn']}")
                return response
            logger.error(f"Failed to create HyperPod cluster: {e}")
            raise

    def get_hyperpod_cluster_status(self, cluster_name: str) -> Tuple[str, Optional[str]]:
        """Get HyperPod cluster status."""
        try:
            response = self.sagemaker.describe_cluster(ClusterName=cluster_name)
            status = response['ClusterStatus']
            failure_message = response.get('FailureMessage')
            return status, failure_message
        except self.sagemaker.exceptions.ResourceNotFound:
            return 'NOTFOUND', None
        except Exception as e:
            logger.error(f"Error getting cluster status: {e}")
            return 'ERROR', str(e)

    def wait_for_hyperpod_cluster(self, cluster_name: str, timeout: int = 3600) -> Dict[str, Any]:
        """Wait for HyperPod cluster to become InService."""
        logger.info(f"Waiting for HyperPod cluster {cluster_name} to become InService...")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = self.sagemaker.describe_cluster(ClusterName=cluster_name)
                status = response['ClusterStatus']

                logger.info(f"HyperPod cluster status: {status}")

                if status == 'InService':
                    logger.info(f"HyperPod cluster {cluster_name} is now InService")
                    return response
                elif status in ['Failed', 'RollbackFailed']:
                    failure_msg = response.get('FailureMessage', 'Unknown error')
                    raise Exception(f"HyperPod cluster creation failed: {failure_msg}")

                time.sleep(60)  # Check every minute

            except self.sagemaker.exceptions.ResourceNotFound:
                logger.warning(f"HyperPod cluster {cluster_name} not found, waiting...")
                time.sleep(60)
            except Exception as e:
                if 'Failed' in str(e) or 'RollbackFailed' in str(e):
                    raise
                logger.error(f"Error checking HyperPod cluster status: {e}")
                time.sleep(60)

        raise TimeoutError(f"Timeout waiting for HyperPod cluster {cluster_name} to become InService")

    def delete_hyperpod_cluster(self, cluster_name: str) -> bool:
        """Delete HyperPod cluster."""
        try:
            self.sagemaker.delete_cluster(ClusterName=cluster_name)
            logger.info(f"HyperPod cluster deletion initiated: {cluster_name}")
            return True
        except self.sagemaker.exceptions.ResourceNotFound:
            logger.warning(f"HyperPod cluster not found: {cluster_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete HyperPod cluster: {e}")
            return False

    def delete_eks_cluster(self, cluster_name: str) -> bool:
        """Delete EKS cluster."""
        try:
            self.eks.delete_cluster(name=cluster_name)
            logger.info(f"EKS cluster deletion initiated: {cluster_name}")
            return True
        except self.eks.exceptions.ResourceNotFoundException:
            logger.warning(f"EKS cluster not found: {cluster_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete EKS cluster: {e}")
            return False

    def update_hyperpod_cluster(
        self,
        cluster_name: str,
        instance_groups: List[Dict[str, Any]],
        execution_role_arn: str,
        lifecycle_script_s3_uri: Optional[str] = None,
        node_provisioning_mode: str = "Continuous",
    ) -> Dict[str, Any]:
        """Update HyperPod cluster instance groups."""
        # Build instance groups config
        instance_groups_config = []
        for ig in instance_groups:
            ig_config = {
                'InstanceGroupName': ig['name'],
                'InstanceType': ig['instance_type'],
                'InstanceCount': ig.get('instance_count', 0),
                'ExecutionRole': execution_role_arn,
                'ThreadsPerCore': ig.get('threads_per_core', 1),
            }

            # MinInstanceCount is only supported when NodeProvisioningMode is Continuous
            if node_provisioning_mode == 'Continuous' and ig.get('min_instance_count') is not None:
                ig_config['MinInstanceCount'] = ig['min_instance_count']

            # LifeCycleConfig is required
            if lifecycle_script_s3_uri:
                lifecycle_config = {
                    'SourceS3Uri': lifecycle_script_s3_uri,
                    'OnCreate': 'on_create.sh'
                }

                # Add deep health checks if enabled
                health_checks = []
                if ig.get('enable_instance_stress_check', False):
                    health_checks.append('InstanceStress')
                if ig.get('enable_instance_connectivity_check', False):
                    health_checks.append('InstanceConnectivity')

                if health_checks:
                    lifecycle_config['OnStartDeepHealthChecks'] = health_checks

                ig_config['LifeCycleConfig'] = lifecycle_config
            else:
                raise ValueError("lifecycle_script_s3_uri is required for updating HyperPod cluster instance groups")

            # Kubernetes labels
            k8s_labels = ig.get('kubernetes_labels', {})
            if ig.get('use_spot'):
                k8s_labels['sagemaker.amazonaws.com/node-lifecycle'] = 'spot'

            if k8s_labels:
                ig_config['OverrideKubernetesConfig'] = {
                    'Labels': k8s_labels
                }

            # Training Plan ARN
            training_plan_arn = ig.get('training_plan_arn')
            if training_plan_arn:
                ig_config['TrainingPlanArn'] = training_plan_arn

            # Storage volume
            storage_volume_size = ig.get('storage_volume_size', 500)
            if storage_volume_size and storage_volume_size > 0:
                ig_config['InstanceStorageConfigs'] = [{
                    'EbsVolumeConfig': {
                        'VolumeSizeInGB': storage_volume_size
                    }
                }]

            instance_groups_config.append(ig_config)

        try:
            response = self.sagemaker.update_cluster(
                ClusterName=cluster_name,
                InstanceGroups=instance_groups_config
            )
            logger.info(f"HyperPod cluster update initiated: {cluster_name}")
            return response
        except Exception as e:
            logger.error(f"Failed to update HyperPod cluster: {e}")
            raise


# ==================== CRUD Operations ====================

async def create_cluster(request: CreateClusterRequest) -> Optional[ClusterInfo]:
    """
    Create a new HyperPod EKS cluster.

    This creates a record in the database and initiates the cluster creation process.
    The actual cluster creation happens asynchronously.
    """
    cluster_id = str(uuid.uuid4().hex)
    cluster_name = request.cluster_name
    eks_cluster_name = request.eks_cluster_name or f"{cluster_name}-eks"

    ts = int(time.time())
    cluster_create_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Prepare config
    cluster_config = {
        'vpc_config': request.vpc_config.dict() if request.vpc_config else None,
        'eks_config': request.eks_config.dict() if request.eks_config else None,
        'hyperpod_config': request.hyperpod_config.dict() if request.hyperpod_config else None,
        'instance_groups': [ig.dict() for ig in request.instance_groups],
        'lifecycle_script_s3_uri': request.lifecycle_script_s3_uri,
        's3_mount_bucket': request.s3_mount_bucket,
        'tags': request.tags
    }

    cluster_detail = ClusterInfo(
        cluster_id=cluster_id,
        cluster_name=cluster_name,
        eks_cluster_name=eks_cluster_name,
        eks_cluster_arn=None,
        hyperpod_cluster_arn=None,
        cluster_status=ClusterStatus.PENDING,
        vpc_id=request.vpc_config.vpc_id if request.vpc_config else None,
        subnet_ids=request.vpc_config.subnet_ids if request.vpc_config else None,
        instance_groups=[ig.dict() for ig in request.instance_groups],
        cluster_create_time=cluster_create_time,
        cluster_update_time=None,
        error_message=None,
        cluster_config=cluster_config,
        ts=ts
    )

    # Save to database
    ret = database.save_cluster(cluster_detail)
    if ret:
        logger.info(f"Created cluster record: {cluster_id}")
        return cluster_detail
    else:
        logger.error(f"Failed to save cluster to database: {cluster_id}")
        return None


async def get_cluster_by_id(request: GetClusterRequest) -> ClusterResponse:
    """Get cluster by ID."""
    cluster = database.get_cluster_by_id(request.cluster_id)

    if cluster:
        return ClusterResponse(
            response_id=str(uuid.uuid4()),
            body=cluster
        )
    else:
        # Return empty response
        return ClusterResponse(
            response_id=str(uuid.uuid4()),
            body=ClusterInfo(
                cluster_id=request.cluster_id,
                cluster_name='',
                eks_cluster_name='',
                cluster_status=ClusterStatus.DELETED,
                ts=0
            )
        )


async def list_clusters(request: ListClustersRequest) -> ListClustersResponse:
    """List clusters with pagination."""
    clusters, total_count = database.list_clusters(
        query_terms=request.query_terms,
        page_size=request.page_size,
        page_index=request.page_index
    )

    return ListClustersResponse(
        response_id=str(uuid.uuid4()),
        clusters=clusters,
        total_count=total_count
    )


async def list_cluster_nodes(request: ListClusterNodesRequest) -> ListClusterNodesResponse:
    """
    List nodes/instances in a HyperPod cluster.

    Uses SageMaker list_cluster_nodes API to get instance details.
    """
    cluster = database.get_cluster_by_id(request.cluster_id)

    if not cluster:
        return ListClusterNodesResponse(
            response_id=str(uuid.uuid4()),
            nodes=[],
            total_count=0
        )

    try:
        executor = ClusterJobExecutor(request.cluster_id)
        cluster_name = cluster.cluster_name

        # Use SageMaker list_cluster_nodes API
        nodes = []
        next_token = None

        while True:
            params = {'ClusterName': cluster_name}
            if next_token:
                params['NextToken'] = next_token

            response = executor.sagemaker.list_cluster_nodes(**params)

            for node in response.get('ClusterNodeSummaries', []):
                node_info = ClusterNodeInfo(
                    instance_id=node.get('InstanceId', ''),
                    instance_status=node.get('InstanceStatus', {}).get('Status', 'Unknown'),
                    instance_group_name=node.get('InstanceGroupName', ''),
                    instance_type=node.get('InstanceType', ''),
                    launch_time=node.get('LaunchTime').isoformat() if node.get('LaunchTime') else None,
                )
                nodes.append(node_info)

            next_token = response.get('NextToken')
            if not next_token:
                break

        return ListClusterNodesResponse(
            response_id=str(uuid.uuid4()),
            nodes=nodes,
            total_count=len(nodes)
        )

    except Exception as e:
        logger.error(f"Failed to list cluster nodes: {e}")
        return ListClusterNodesResponse(
            response_id=str(uuid.uuid4()),
            nodes=[],
            total_count=0
        )


async def get_cluster_instance_types(cluster_id: str) -> List[str]:
    """
    Get available instance types from a HyperPod cluster.

    Returns a list of unique instance types available in the cluster.
    """
    cluster = database.get_cluster_by_id(cluster_id)

    if not cluster:
        return []

    try:
        executor = ClusterJobExecutor(cluster_id)
        cluster_name = cluster.cluster_name

        # Use SageMaker list_cluster_nodes API to get instance types
        instance_types = set()
        next_token = None

        while True:
            params = {'ClusterName': cluster_name}
            if next_token:
                params['NextToken'] = next_token

            response = executor.sagemaker.list_cluster_nodes(**params)

            for node in response.get('ClusterNodeSummaries', []):
                instance_type = node.get('InstanceType', '')
                if instance_type:
                    instance_types.add(instance_type)

            next_token = response.get('NextToken')
            if not next_token:
                break

        return sorted(list(instance_types))

    except Exception as e:
        logger.error(f"Failed to get cluster instance types: {e}")
        return []


async def delete_cluster(request: DeleteClusterRequest) -> CommonResponse:
    """
    Delete a cluster.

    Marks the cluster for deletion in the database.
    Actual deletion happens asynchronously.
    """
    cluster = database.get_cluster_by_id(request.cluster_id)

    if not cluster:
        return CommonResponse(
            response_id=str(uuid.uuid4()),
            response={
                'statusCode': 404,
                'body': f'Cluster not found: {request.cluster_id}'
            }
        )

    # Update status to DELETING
    database.set_cluster_status(request.cluster_id, ClusterStatus.DELETING)

    # Store delete_vpc flag in config
    if request.delete_vpc:
        cluster_config = cluster.cluster_config or {}
        cluster_config['delete_vpc'] = True
        database.update_cluster_config(request.cluster_id, cluster_config)

    return CommonResponse(
        response_id=str(uuid.uuid4()),
        response={
            'statusCode': 200,
            'body': {
                'cluster_id': request.cluster_id,
                'message': 'Cluster deletion initiated'
            }
        }
    )


async def update_cluster(request: UpdateClusterRequest) -> CommonResponse:
    """Update cluster configuration including instance groups."""
    cluster = database.get_cluster_by_id(request.cluster_id)

    if not cluster:
        return CommonResponse(
            response_id=str(uuid.uuid4()),
            response={
                'statusCode': 404,
                'body': f'Cluster not found: {request.cluster_id}'
            }
        )

    # Check if cluster is in a valid state for update
    # Handle both enum and string status values
    cluster_status_str = cluster.cluster_status.value if isinstance(cluster.cluster_status, ClusterStatus) else cluster.cluster_status
    if cluster_status_str in [ClusterStatus.CREATING.value, ClusterStatus.UPDATING.value,
                               ClusterStatus.DELETING.value, ClusterStatus.PENDING.value]:
        return CommonResponse(
            response_id=str(uuid.uuid4()),
            response={
                'statusCode': 400,
                'body': f'Cluster cannot be updated while in {cluster.cluster_status} state'
            }
        )

    # Update config in database
    cluster_config = cluster.cluster_config or {}

    if request.instance_groups is not None:
        instance_groups_dict = [ig.dict() for ig in request.instance_groups]
        cluster_config['instance_groups'] = instance_groups_dict
        # Also update the instance_groups column for proper retrieval
        database.update_cluster_instance_groups(request.cluster_id, instance_groups_dict)

    if request.hyperpod_config:
        cluster_config['hyperpod_config'] = request.hyperpod_config.dict()

    database.update_cluster_config(request.cluster_id, cluster_config)

    # If instance groups are being updated, call AWS API
    # Use 'is not None' to handle empty list case (when all groups are deleted)
    if request.instance_groups is not None and cluster_status_str == ClusterStatus.ACTIVE.value:
        logger.info(f"Calling AWS API to update instance groups for cluster {cluster.cluster_name}, groups: {[ig.dict() for ig in request.instance_groups]}")
        try:
            executor = ClusterJobExecutor(request.cluster_id)

            # Get execution role ARN (should be stored or derived)
            hyperpod_role_name = f'{cluster.cluster_name}-hyperpod-role'
            execution_role_arn = f'arn:aws:iam::{executor.account_id}:role/{hyperpod_role_name}'

            # Get lifecycle script URI - use default if not set
            lifecycle_script_s3_uri = cluster_config.get('lifecycle_script_s3_uri')
            if not lifecycle_script_s3_uri:
                # Create default bucket and script
                bucket_name = f'llm-modelhub-hyperpod-{executor.account_id}-{executor.region}'
                lifecycle_script_s3_uri = f's3://{bucket_name}/hyperpod-scripts/'

            # Convert instance groups to dict format
            instance_groups_dict = [ig.dict() for ig in request.instance_groups]

            # Call AWS API to update cluster
            executor.update_hyperpod_cluster(
                cluster_name=cluster.cluster_name,
                instance_groups=instance_groups_dict,
                execution_role_arn=execution_role_arn,
                lifecycle_script_s3_uri=lifecycle_script_s3_uri
            )

            database.set_cluster_status(request.cluster_id, ClusterStatus.UPDATING)

            return CommonResponse(
                response_id=str(uuid.uuid4()),
                response={
                    'statusCode': 200,
                    'body': {
                        'cluster_id': request.cluster_id,
                        'message': 'Cluster update initiated'
                    }
                }
            )
        except Exception as e:
            logger.error(f"Failed to update cluster: {e}")
            database.update_cluster_error(request.cluster_id, str(e))
            return CommonResponse(
                response_id=str(uuid.uuid4()),
                response={
                    'statusCode': 500,
                    'body': f'Failed to update cluster: {str(e)}'
                }
            )

    # Just update database config (no AWS API call needed)
    if request.instance_groups is not None and cluster_status_str != ClusterStatus.ACTIVE.value:
        logger.warning(f"Cluster {cluster.cluster_name} is not ACTIVE (status: {cluster_status_str}), skipping AWS API call for instance groups update")

    return CommonResponse(
        response_id=str(uuid.uuid4()),
        response={
            'statusCode': 200,
            'body': {
                'cluster_id': request.cluster_id,
                'message': 'Cluster configuration updated'
            }
        }
    )


def get_cluster_status(cluster_id: str) -> ClusterStatus:
    """Get current cluster status from AWS."""
    cluster = database.get_cluster_by_id(cluster_id)
    if not cluster:
        return ClusterStatus.DELETED

    executor = ClusterJobExecutor(cluster_id)

    # Check HyperPod cluster status
    hp_status, error_msg = executor.get_hyperpod_cluster_status(cluster.cluster_name)

    status_mapping = {
        'Creating': ClusterStatus.CREATING,
        'Updating': ClusterStatus.UPDATING,
        'InService': ClusterStatus.ACTIVE,
        'Deleting': ClusterStatus.DELETING,
        'Failed': ClusterStatus.FAILED,
        'NOTFOUND': ClusterStatus.DELETED,
        'ERROR': ClusterStatus.FAILED
    }

    new_status = status_mapping.get(hp_status, ClusterStatus.PENDING)

    # Update database
    database.set_cluster_status(cluster_id, new_status)
    if error_msg:
        database.update_cluster_error(cluster_id, error_msg)

    return new_status
