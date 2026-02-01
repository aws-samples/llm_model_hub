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
from eks_management.utils import get_occupied_nodes

logger = setup_logger('eks_clusters.py')
database = DatabaseWrapper()

# Cluster table name
CLUSTER_TABLE = 'CLUSTER_TABLE'

# HyperPod status mapping: AWS status -> internal ClusterStatus
HYPERPOD_STATUS_MAPPING = {
    'Creating': ClusterStatus.CREATING,
    'Updating': ClusterStatus.UPDATING,
    'InService': ClusterStatus.ACTIVE,
    'Deleting': ClusterStatus.DELETING,
    'Failed': ClusterStatus.FAILED,
    'RollingBack': ClusterStatus.UPDATING,
    'NOTFOUND': ClusterStatus.DELETED,
    'ERROR': ClusterStatus.FAILED
}


def sync_cluster_status_on_error(
    cluster_id: str,
    cluster_name: str,
    original_error: Exception
) -> None:
    """
    Sync database status with actual AWS cluster status when an operation fails.

    Instead of blindly setting status to FAILED, this function queries AWS
    for the real cluster status and updates the database accordingly.
    The error message is recorded separately without affecting the status.
    """
    try:
        executor = ClusterJobExecutor(cluster_id)
        aws_status, _ = executor.get_hyperpod_cluster_status(cluster_name)
        real_status = HYPERPOD_STATUS_MAPPING.get(aws_status, ClusterStatus.PENDING)
        database.set_cluster_status(cluster_id, real_status)
        database.set_cluster_error_message(cluster_id, str(original_error))
        logger.info(f"Synced cluster status to {real_status.value} (AWS: {aws_status}), recorded error: {original_error}")
    except Exception as sync_error:
        logger.error(f"Failed to sync cluster status from AWS: {sync_error}")
        database.update_cluster_error(cluster_id, str(original_error))


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

    def _build_instance_group_config(
        self,
        ig: Dict[str, Any],
        execution_role_arn: str,
        lifecycle_script_s3_uri: Optional[str],
        node_provisioning_mode: str = "Continuous",
        is_new_group: bool = True,
        default_security_group_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Build instance group configuration for HyperPod API calls.

        This helper method consolidates the instance group config building logic
        used by both create_hyperpod_cluster and update_hyperpod_cluster.

        Args:
            is_new_group: If True, sets CapacityRequirements. If False (existing group),
                         only sets CapacityRequirements if use_spot is explicitly True.
                         This is because AWS doesn't allow changing CapacityType for existing groups.
            default_security_group_ids: Default security group IDs from cluster config,
                         used when override_subnet_id is set but override_security_group_ids is not.
        """
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

        # LifeCycleConfig is REQUIRED
        if not lifecycle_script_s3_uri:
            raise ValueError("lifecycle_script_s3_uri is required for HyperPod cluster operations")

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

        # Capacity requirements for Spot or On-Demand instances
        # Note: AWS doesn't allow changing CapacityType for existing instance groups
        # So we only set this for new groups, or if user explicitly wants spot for existing group
        if is_new_group:
            # New group - always set CapacityRequirements
            if ig.get('use_spot'):
                ig_config['CapacityRequirements'] = {'Spot': {}}
            else:
                ig_config['CapacityRequirements'] = {'OnDemand': {}}
        elif ig.get('use_spot'):
            # Existing group with use_spot=True - try to set Spot (may fail if group was OnDemand)
            ig_config['CapacityRequirements'] = {'Spot': {}}

        # Kubernetes labels
        k8s_labels = ig.get('kubernetes_labels') or {}
        if ig.get('use_spot'):
            k8s_labels['node-lifecycle'] = 'spot'
        if k8s_labels:
            ig_config['KubernetesConfig'] = {'Labels': k8s_labels}

        # Training Plan ARN for capacity reservation
        if ig.get('training_plan_arn'):
            ig_config['TrainingPlanArn'] = ig['training_plan_arn']

        # Additional storage volume (EBS) per instance
        storage_volume_size = ig.get('storage_volume_size', 500)
        if storage_volume_size and storage_volume_size > 0:
            ig_config['InstanceStorageConfigs'] = [{
                'EbsVolumeConfig': {'VolumeSizeInGB': storage_volume_size}
            }]

        # Override VPC config for this instance group (useful for spot instances in specific AZs)
        override_subnet_id = ig.get('override_subnet_id')
        if override_subnet_id:
            # Use override security groups if provided, otherwise fall back to cluster default
            override_sg_ids = ig.get('override_security_group_ids') or default_security_group_ids
            if override_sg_ids:
                ig_config['OverrideVpcConfig'] = {
                    'Subnets': [override_subnet_id],
                    'SecurityGroupIds': override_sg_ids
                }
                logger.info(f"Instance group {ig['name']} using OverrideVpcConfig: subnet={override_subnet_id}")
            else:
                logger.warning(f"Instance group {ig['name']} has override_subnet_id but no security groups available")

        return ig_config

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
        enable_autoscaling: bool = False,
        enable_tiered_storage: bool = False,
        tiered_storage_memory_percentage: int = 20
    ) -> Dict[str, Any]:
        """Create HyperPod cluster."""
        logger.info(f"Creating HyperPod cluster: {cluster_name}")

        # Build instance groups config using helper method
        instance_groups_config = [
            self._build_instance_group_config(
                ig=ig,
                execution_role_arn=execution_role_arn,
                lifecycle_script_s3_uri=lifecycle_script_s3_uri,
                node_provisioning_mode=node_provisioning_mode,
                default_security_group_ids=security_group_ids
            )
            for ig in instance_groups
        ]

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

        # Add TieredStorageConfig if enabled (for L2 KV Cache with managed daemon)
        if enable_tiered_storage:
            cluster_config['TieredStorageConfig'] = {
                'Mode': 'Enabled',
                'InstanceMemoryAllocationPercentage': tiered_storage_memory_percentage
            }
            logger.info(f"Tiered storage enabled with {tiered_storage_memory_percentage}% memory allocation")

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

    def get_hyperpod_instance_groups(self, cluster_name: str) -> Dict[str, str]:
        """
        Get current instance groups from AWS HyperPod cluster.

        Returns a dict mapping instance group name to instance type.
        """
        try:
            response = self.sagemaker.describe_cluster(ClusterName=cluster_name)
            instance_groups = response.get('InstanceGroups', [])
            return {
                ig['InstanceGroupName']: ig['InstanceType']
                for ig in instance_groups
            }
        except Exception as e:
            logger.error(f"Error getting instance groups: {e}")
            return {}

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
        node_recovery: Optional[str] = None,
        enable_tiered_storage: Optional[bool] = None,
        tiered_storage_memory_percentage: Optional[int] = None,
        instance_groups_to_delete: Optional[List[str]] = None,
        existing_group_names: Optional[List[str]] = None,
        default_security_group_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Update HyperPod cluster instance groups and/or tiered storage config."""
        # Validate: HyperPod clusters require at least 1 instance group
        if not instance_groups or len(instance_groups) == 0:
            raise ValueError("HyperPod clusters require at least 1 instance group. Cannot delete all instance groups.")

        existing_names_set = set(existing_group_names) if existing_group_names else set()

        # Build instance groups config using helper method
        instance_groups_config = [
            self._build_instance_group_config(
                ig=ig,
                execution_role_arn=execution_role_arn,
                lifecycle_script_s3_uri=lifecycle_script_s3_uri,
                node_provisioning_mode=node_provisioning_mode,
                is_new_group=(ig['name'] not in existing_names_set),
                default_security_group_ids=default_security_group_ids
            )
            for ig in instance_groups
        ]

        try:
            # Build update params
            update_params = {
                'ClusterName': cluster_name,
                'InstanceGroups': instance_groups_config
            }

            # Add InstanceGroupsToDelete if specified
            if instance_groups_to_delete:
                update_params['InstanceGroupsToDelete'] = instance_groups_to_delete
                logger.info(f"Deleting instance groups: {instance_groups_to_delete}")

            # Add NodeRecovery if specified
            if node_recovery:
                update_params['NodeRecovery'] = node_recovery

            # Add TieredStorageConfig if specified
            if enable_tiered_storage is not None:
                if enable_tiered_storage:
                    update_params['TieredStorageConfig'] = {
                        'Mode': 'Enabled',
                        'InstanceMemoryAllocationPercentage': tiered_storage_memory_percentage or 20
                    }
                    logger.info(f"Updating tiered storage: enabled with {tiered_storage_memory_percentage or 20}% memory allocation")
                else:
                    update_params['TieredStorageConfig'] = {
                        'Mode': 'Disabled'
                    }
                    logger.info("Updating tiered storage: disabled")

            response = self.sagemaker.update_cluster(**update_params)
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
    Also checks kubernetes to determine if nodes are occupied by inference workloads.
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
        eks_cluster_name = cluster.eks_cluster_name

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

        # Get occupied nodes from kubernetes (nodes running inference pods)
        _, node_occupancy = get_occupied_nodes(eks_cluster_name)

        # Update nodes with occupancy info
        for node in nodes:
            k8s_node_name = f'hyperpod-{node.instance_id}'
            if k8s_node_name in node_occupancy:
                node.is_occupied = True
                node.occupied_by = node_occupancy[k8s_node_name]

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


async def get_cluster_instance_types(cluster_id: str) -> Dict[str, Any]:
    """
    Get available instance types from a HyperPod cluster with instance group info.

    Returns a dict with:
    - instance_types: list of unique instance type strings (for backward compatibility)
    - instance_type_details: list of dicts with instance_type, instance_groups, and availability info
    """
    cluster = database.get_cluster_by_id(cluster_id)

    if not cluster:
        return {'instance_types': [], 'instance_type_details': []}

    try:
        executor = ClusterJobExecutor(cluster_id)
        cluster_name = cluster.cluster_name
        eks_cluster_name = cluster.eks_cluster_name

        # Track instance group info: {group_name: {instance_type, total_count, node_names}}
        instance_group_info: Dict[str, Dict[str, Any]] = {}
        next_token = None

        while True:
            params = {'ClusterName': cluster_name}
            if next_token:
                params['NextToken'] = next_token

            response = executor.sagemaker.list_cluster_nodes(**params)

            for node in response.get('ClusterNodeSummaries', []):
                instance_type = node.get('InstanceType', '')
                instance_group_name = node.get('InstanceGroupName', '')
                instance_id = node.get('InstanceId', '')
                instance_status = node.get('InstanceStatus', {}).get('Status', 'Unknown')

                if instance_group_name and instance_type:
                    if instance_group_name not in instance_group_info:
                        instance_group_info[instance_group_name] = {
                            'instance_type': instance_type,
                            'total_count': 0,
                            'running_count': 0,  # Only count Running instances
                            'node_names': []
                        }
                    instance_group_info[instance_group_name]['total_count'] += 1
                    # Only count instances that are Running as available
                    if instance_status == 'Running':
                        instance_group_info[instance_group_name]['running_count'] += 1
                        # Node name in k8s is typically hyperpod-<instance_id>
                        instance_group_info[instance_group_name]['node_names'].append(f'hyperpod-{instance_id}')

            next_token = response.get('NextToken')
            if not next_token:
                break

        # Get occupied nodes from kubernetes (nodes running inference pods)
        occupied_nodes, _ = get_occupied_nodes(eks_cluster_name)

        # Build detailed list with availability info
        instance_type_details = []
        available_instance_types = set()

        for group_name, info in instance_group_info.items():
            instance_type = info['instance_type']
            total_count = info['total_count']
            running_count = info['running_count']  # Only Running instances
            node_names = info['node_names']  # Only contains Running instance node names

            # Calculate available count (running nodes not occupied by inference pods)
            occupied_count = sum(1 for n in node_names if n in occupied_nodes)
            available_count = running_count - occupied_count

            instance_type_details.append({
                'instance_type': instance_type,
                'instance_groups': [group_name],
                'total_count': total_count,
                'running_count': running_count,  # Running instances count
                'available_count': available_count,  # Running and not occupied
                'is_available': available_count > 0
            })

            if available_count > 0:
                available_instance_types.add(instance_type)

        # Sort by instance_type
        instance_type_details.sort(key=lambda x: x['instance_type'])

        return {
            'instance_types': sorted(list(available_instance_types)),  # Only available types
            'instance_type_details': instance_type_details  # All details including unavailable
        }

    except Exception as e:
        logger.error(f"Failed to get cluster instance types: {e}")
        return {'instance_types': [], 'instance_type_details': []}


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

    # Get current cluster config
    cluster_config = cluster.cluster_config or {}

    # If instance groups are being updated and cluster is ACTIVE, call AWS API first
    # Database update happens AFTER successful AWS validation and API call
    if request.instance_groups is not None and cluster_status_str == ClusterStatus.ACTIVE.value:
        # Validate: HyperPod clusters require at least 1 instance group
        if len(request.instance_groups) == 0:
            return CommonResponse(
                response_id=str(uuid.uuid4()),
                response={
                    'statusCode': 400,
                    'body': 'Cannot delete all instance groups. HyperPod clusters require at least 1 instance group.'
                }
            )

        try:
            executor = ClusterJobExecutor(request.cluster_id)

            # Validate and compute instance group changes
            current_instance_groups = executor.get_hyperpod_instance_groups(cluster.cluster_name)
            instance_groups_to_delete = []

            if current_instance_groups:
                requested_group_names = {ig.name for ig in request.instance_groups}
                current_group_names = set(current_instance_groups.keys())

                # Compute instance groups to delete (using InstanceGroupsToDelete API parameter)
                groups_to_delete = current_group_names - requested_group_names
                if groups_to_delete:
                    instance_groups_to_delete = list(groups_to_delete)
                    logger.info(f"Instance groups to delete: {instance_groups_to_delete}")

                # Check: Attempting to change instance type (not supported by AWS)
                instance_type_changes = []
                for ig in request.instance_groups:
                    if ig.name in current_instance_groups:
                        current_type = current_instance_groups[ig.name]
                        if ig.instance_type != current_type:
                            instance_type_changes.append(
                                f"{ig.name}: {current_type} -> {ig.instance_type}"
                            )
                if instance_type_changes:
                    error_msg = (
                        f"Cannot change instance type for existing instance groups. "
                        f"AWS HyperPod does not support this operation. "
                        f"Attempted changes: {', '.join(instance_type_changes)}. "
                        f"To use a different instance type, create a new instance group."
                    )
                    logger.warning(error_msg)
                    return CommonResponse(
                        response_id=str(uuid.uuid4()),
                        response={
                            'statusCode': 400,
                            'body': error_msg
                        }
                    )

            # Get execution role ARN (should be stored or derived)
            hyperpod_role_name = f'{cluster.cluster_name}-hyperpod-role'
            execution_role_arn = f'arn:aws:iam::{executor.account_id}:role/{hyperpod_role_name}'

            # Get lifecycle script URI - use default if not set
            lifecycle_script_s3_uri = cluster_config.get('lifecycle_script_s3_uri')
            if not lifecycle_script_s3_uri:
                # Create default bucket and script
                bucket_name = f'llm-modelhub-hyperpod-{executor.account_id}-{executor.region}'
                lifecycle_script_s3_uri = f's3://{bucket_name}/LifecycleScripts/base-config/'

            # Convert instance groups to dict format
            instance_groups_dict = [ig.dict() for ig in request.instance_groups]

            # Get tiered storage config from hyperpod_config if provided
            enable_tiered_storage = None
            tiered_storage_memory_percentage = None
            if request.hyperpod_config:
                enable_tiered_storage = request.hyperpod_config.enable_tiered_storage
                tiered_storage_memory_percentage = request.hyperpod_config.tiered_storage_memory_percentage

            # Get list of existing group names for proper handling of CapacityRequirements
            existing_group_names = list(current_instance_groups.keys()) if current_instance_groups else []

            # Get security group IDs for OverrideVpcConfig
            # Check both vpc_config.security_group_ids and cluster_config.security_group_ids
            vpc_config = cluster_config.get('vpc_config', {})
            default_security_group_ids = vpc_config.get('security_group_ids', []) if vpc_config else []
            if not default_security_group_ids:
                default_security_group_ids = cluster_config.get('security_group_ids', [])

            logger.info(f"Calling AWS API to update instance groups for cluster {cluster.cluster_name}, groups: {instance_groups_dict}, delete: {instance_groups_to_delete or []}, existing: {existing_group_names}")

            # Call AWS API to update cluster
            executor.update_hyperpod_cluster(
                cluster_name=cluster.cluster_name,
                instance_groups=instance_groups_dict,
                execution_role_arn=execution_role_arn,
                lifecycle_script_s3_uri=lifecycle_script_s3_uri,
                enable_tiered_storage=enable_tiered_storage,
                tiered_storage_memory_percentage=tiered_storage_memory_percentage,
                instance_groups_to_delete=instance_groups_to_delete if instance_groups_to_delete else None,
                existing_group_names=existing_group_names,
                default_security_group_ids=default_security_group_ids
            )

            # AWS call succeeded - now update database
            cluster_config['instance_groups'] = instance_groups_dict
            if request.hyperpod_config:
                cluster_config['hyperpod_config'] = request.hyperpod_config.dict()
            database.update_cluster_config(request.cluster_id, cluster_config)
            database.update_cluster_instance_groups(request.cluster_id, instance_groups_dict)
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
            sync_cluster_status_on_error(request.cluster_id, cluster.cluster_name, e)
            return CommonResponse(
                response_id=str(uuid.uuid4()),
                response={
                    'statusCode': 500,
                    'body': f'Failed to update cluster: {str(e)}'
                }
            )

    # Just update database config (no AWS API call needed when cluster is not ACTIVE)
    if request.instance_groups is not None and cluster_status_str != ClusterStatus.ACTIVE.value:
        logger.warning(f"Cluster {cluster.cluster_name} is not ACTIVE (status: {cluster_status_str}), updating database only")
        instance_groups_dict = [ig.dict() for ig in request.instance_groups]
        cluster_config['instance_groups'] = instance_groups_dict
        if request.hyperpod_config:
            cluster_config['hyperpod_config'] = request.hyperpod_config.dict()
        database.update_cluster_config(request.cluster_id, cluster_config)
        database.update_cluster_instance_groups(request.cluster_id, instance_groups_dict)

    # Handle case where only hyperpod_config is being updated (without instance groups, when not ACTIVE)
    elif request.instance_groups is None and request.hyperpod_config and cluster_status_str != ClusterStatus.ACTIVE.value:
        logger.warning(f"Cluster {cluster.cluster_name} is not ACTIVE (status: {cluster_status_str}), updating database only")
        cluster_config['hyperpod_config'] = request.hyperpod_config.dict()
        database.update_cluster_config(request.cluster_id, cluster_config)

    # Handle case where only tiered storage config is being updated (without instance groups)
    if request.instance_groups is None and request.hyperpod_config and cluster_status_str == ClusterStatus.ACTIVE.value:
        # Check if tiered storage is being updated
        if request.hyperpod_config.enable_tiered_storage is not None:
            logger.info(f"Updating tiered storage config only for cluster {cluster.cluster_name}")
            try:
                executor = ClusterJobExecutor(request.cluster_id)

                # Get execution role ARN
                hyperpod_role_name = f'{cluster.cluster_name}-hyperpod-role'
                execution_role_arn = f'arn:aws:iam::{executor.account_id}:role/{hyperpod_role_name}'

                # Get lifecycle script URI
                lifecycle_script_s3_uri = cluster_config.get('lifecycle_script_s3_uri')
                if not lifecycle_script_s3_uri:
                    bucket_name = f'llm-modelhub-hyperpod-{executor.account_id}-{executor.region}'
                    lifecycle_script_s3_uri = f's3://{bucket_name}/LifecycleScripts/base-config/'

                # Get current instance groups from database (required by AWS API)
                current_instance_groups = cluster_config.get('instance_groups', [])
                if not current_instance_groups:
                    return CommonResponse(
                        response_id=str(uuid.uuid4()),
                        response={
                            'statusCode': 400,
                            'body': 'Cannot update tiered storage: no instance groups found in cluster config'
                        }
                    )

                # Call AWS API with current instance groups and new tiered storage config
                # All groups are existing since we're only updating tiered storage
                existing_group_names = [ig.get('name') for ig in current_instance_groups if ig.get('name')]

                # Get security group IDs for OverrideVpcConfig
                # Check both vpc_config.security_group_ids and cluster_config.security_group_ids
                vpc_config = cluster_config.get('vpc_config', {})
                default_security_group_ids = vpc_config.get('security_group_ids', []) if vpc_config else []
                if not default_security_group_ids:
                    default_security_group_ids = cluster_config.get('security_group_ids', [])

                executor.update_hyperpod_cluster(
                    cluster_name=cluster.cluster_name,
                    instance_groups=current_instance_groups,
                    execution_role_arn=execution_role_arn,
                    lifecycle_script_s3_uri=lifecycle_script_s3_uri,
                    enable_tiered_storage=request.hyperpod_config.enable_tiered_storage,
                    tiered_storage_memory_percentage=request.hyperpod_config.tiered_storage_memory_percentage,
                    existing_group_names=existing_group_names,
                    default_security_group_ids=default_security_group_ids
                )

                database.set_cluster_status(request.cluster_id, ClusterStatus.UPDATING)

                return CommonResponse(
                    response_id=str(uuid.uuid4()),
                    response={
                        'statusCode': 200,
                        'body': {
                            'cluster_id': request.cluster_id,
                            'message': 'Cluster tiered storage update initiated'
                        }
                    }
                )
            except Exception as e:
                logger.error(f"Failed to update cluster tiered storage: {e}")
                sync_cluster_status_on_error(request.cluster_id, cluster.cluster_name, e)
                return CommonResponse(
                    response_id=str(uuid.uuid4()),
                    response={
                        'statusCode': 500,
                        'body': f'Failed to update cluster tiered storage: {str(e)}'
                    }
                )

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

    # Use global status mapping constant
    new_status = HYPERPOD_STATUS_MAPPING.get(hp_status, ClusterStatus.PENDING)

    # Update database
    database.set_cluster_status(cluster_id, new_status)
    if error_msg:
        # Only set error message, don't change status (status already set above)
        database.set_cluster_error_message(cluster_id, error_msg)

    return new_status


async def get_cluster_subnets(cluster_id: str) -> Dict[str, Any]:
    """
    Get subnet information for a cluster with availability zone details.

    Returns a dict with:
    - subnets: list of SubnetInfo dicts containing subnet_id, availability_zone, etc.
    - security_group_ids: list of security group IDs from cluster config
    """
    cluster = database.get_cluster_by_id(cluster_id)

    if not cluster:
        return {'subnets': [], 'security_group_ids': []}

    # Get subnet IDs from cluster config
    subnet_ids = cluster.subnet_ids or []
    if not subnet_ids:
        # Try to get from cluster_config.vpc_config
        cluster_config = cluster.cluster_config or {}
        vpc_config = cluster_config.get('vpc_config', {})
        if vpc_config:
            subnet_ids = vpc_config.get('subnet_ids', [])

    if not subnet_ids:
        return {'subnets': [], 'security_group_ids': []}

    try:
        executor = ClusterJobExecutor(cluster_id)

        # Describe subnets using EC2 API
        response = executor.ec2.describe_subnets(SubnetIds=subnet_ids)

        subnets = []
        for subnet in response.get('Subnets', []):
            # Extract Name tag
            name = None
            for tag in subnet.get('Tags', []):
                if tag['Key'] == 'Name':
                    name = tag['Value']
                    break

            # Determine if public (has route to IGW - approximation based on MapPublicIpOnLaunch)
            is_public = subnet.get('MapPublicIpOnLaunch', False)

            subnet_info = {
                'subnet_id': subnet['SubnetId'],
                'availability_zone': subnet['AvailabilityZone'],
                'availability_zone_id': subnet['AvailabilityZoneId'],
                'cidr_block': subnet.get('CidrBlock'),
                'name': name,
                'is_public': is_public
            }
            subnets.append(subnet_info)

        # Sort by availability zone
        subnets.sort(key=lambda x: x['availability_zone'])

        # Get security group IDs from cluster config
        # Check both vpc_config.security_group_ids and cluster_config.security_group_ids
        security_group_ids = []
        cluster_config = cluster.cluster_config or {}
        vpc_config = cluster_config.get('vpc_config', {})
        if vpc_config:
            security_group_ids = vpc_config.get('security_group_ids', [])
        # Also check top-level security_group_ids in cluster_config
        if not security_group_ids:
            security_group_ids = cluster_config.get('security_group_ids', [])

        return {
            'subnets': subnets,
            'security_group_ids': security_group_ids
        }

    except Exception as e:
        logger.error(f"Failed to get cluster subnets: {e}")
        return {'subnets': [], 'security_group_ids': []}
