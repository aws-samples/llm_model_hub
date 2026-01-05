#!/usr/bin/env python3
"""
HyperPod EKS Deployment - Complete boto3 SDK Implementation

This module provides a comprehensive solution for creating and managing
Amazon EKS clusters integrated with SageMaker HyperPod using boto3 SDK.

Key Features:
- VPC and networking infrastructure creation
- IAM roles and policies setup
- EKS cluster creation with proper configuration
- HyperPod cluster creation with EKS orchestration
- Lifecycle scripts management
- Support for Spot instances and autoscaling

Usage:
    from hyperpod_eks_deployment import HyperPodEKSDeployment

    deployer = HyperPodEKSDeployment(region='us-west-2')
    deployer.deploy_full_stack(
        cluster_name='my-hyperpod-cluster',
        eks_cluster_name='my-eks-cluster'
    )
"""

import boto3
import json
import time
import logging
from typing import Dict, List, Optional, Any
from botocore.exceptions import ClientError
from dataclasses import dataclass, field

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class VPCConfig:
    """VPC configuration parameters"""
    vpc_cidr: str = "10.0.0.0/16"
    public_subnet_cidrs: List[str] = field(default_factory=lambda: ["10.0.1.0/24", "10.0.2.0/24"])
    private_subnet_cidrs: List[str] = field(default_factory=lambda: ["10.0.10.0/24", "10.0.20.0/24"])
    enable_dns_hostnames: bool = True
    enable_dns_support: bool = True


@dataclass
class EKSConfig:
    """EKS cluster configuration parameters"""
    kubernetes_version: str = "1.34"
    endpoint_public_access: bool = True
    endpoint_private_access: bool = True
    authentication_mode: str = "API_AND_CONFIG_MAP"
    enable_logging: bool = True
    log_types: List[str] = field(default_factory=lambda: ['api', 'audit', 'authenticator', 'controllerManager', 'scheduler'])


@dataclass
class HyperPodConfig:
    """HyperPod cluster configuration parameters"""
    node_recovery: str = "Automatic"
    node_provisioning_mode: str = "Continuous"
    enable_deep_health_checks: bool = True
    deep_health_check_types: List[str] = field(default_factory=lambda: ["InstanceStress", "InstanceConnectivity"])


@dataclass
class InstanceGroupConfig:
    """Instance group configuration for HyperPod"""
    name: str
    instance_type: str
    instance_count: int
    min_instance_count: Optional[int] = None
    threads_per_core: int = 1
    use_spot: bool = False
    kubernetes_labels: Optional[Dict[str, str]] = None
    kubernetes_taints: Optional[List[Dict[str, str]]] = None


class HyperPodEKSDeployment:
    """
    Complete deployment solution for HyperPod with EKS orchestration.

    This class provides methods to create all necessary AWS resources
    for running HyperPod clusters with EKS orchestration.
    """

    def __init__(self, region: str = 'us-west-2', profile: Optional[str] = None):
        """
        Initialize the deployment manager.

        Args:
            region: AWS region for deployment
            profile: Optional AWS profile name
        """
        self.region = region
        session_kwargs = {'region_name': region}
        if profile:
            session_kwargs['profile_name'] = profile

        self.session = boto3.Session(**session_kwargs)
        self.ec2 = self.session.client('ec2')
        self.eks = self.session.client('eks')
        self.sagemaker = self.session.client('sagemaker')
        self.iam = self.session.client('iam')
        self.s3 = self.session.client('s3')
        self.sts = self.session.client('sts')

        # Get account ID
        self.account_id = self.sts.get_caller_identity()['Account']
        logger.info(f"Initialized HyperPodEKSDeployment for account {self.account_id} in {region}")

    # ==================== VPC Infrastructure ====================

    def create_vpc(self, vpc_config: VPCConfig, name_prefix: str) -> Dict[str, Any]:
        """
        Create a VPC with public and private subnets for EKS/HyperPod.

        Args:
            vpc_config: VPC configuration parameters
            name_prefix: Prefix for resource naming

        Returns:
            Dictionary containing VPC and subnet IDs
        """
        logger.info(f"Creating VPC with CIDR {vpc_config.vpc_cidr}")

        # Create VPC
        vpc_response = self.ec2.create_vpc(
            CidrBlock=vpc_config.vpc_cidr,
            TagSpecifications=[{
                'ResourceType': 'vpc',
                'Tags': [
                    {'Key': 'Name', 'Value': f'{name_prefix}-vpc'},
                    {'Key': 'Purpose', 'Value': 'HyperPod-EKS'}
                ]
            }]
        )
        vpc_id = vpc_response['Vpc']['VpcId']
        logger.info(f"Created VPC: {vpc_id}")

        # Enable DNS hostnames and support
        self.ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={'Value': vpc_config.enable_dns_hostnames})
        self.ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={'Value': vpc_config.enable_dns_support})

        # Get available AZs
        azs_response = self.ec2.describe_availability_zones(
            Filters=[{'Name': 'state', 'Values': ['available']}]
        )
        available_azs = [az['ZoneName'] for az in azs_response['AvailabilityZones'][:len(vpc_config.private_subnet_cidrs)]]

        # Create Internet Gateway
        igw_response = self.ec2.create_internet_gateway(
            TagSpecifications=[{
                'ResourceType': 'internet-gateway',
                'Tags': [{'Key': 'Name', 'Value': f'{name_prefix}-igw'}]
            }]
        )
        igw_id = igw_response['InternetGateway']['InternetGatewayId']
        self.ec2.attach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
        logger.info(f"Created and attached Internet Gateway: {igw_id}")

        # Create public subnets
        public_subnet_ids = []
        for i, (cidr, az) in enumerate(zip(vpc_config.public_subnet_cidrs, available_azs)):
            subnet_response = self.ec2.create_subnet(
                VpcId=vpc_id,
                CidrBlock=cidr,
                AvailabilityZone=az,
                TagSpecifications=[{
                    'ResourceType': 'subnet',
                    'Tags': [
                        {'Key': 'Name', 'Value': f'{name_prefix}-public-{i+1}'},
                        {'Key': 'kubernetes.io/role/elb', 'Value': '1'}
                    ]
                }]
            )
            subnet_id = subnet_response['Subnet']['SubnetId']
            public_subnet_ids.append(subnet_id)

            # Enable auto-assign public IP
            self.ec2.modify_subnet_attribute(
                SubnetId=subnet_id,
                MapPublicIpOnLaunch={'Value': True}
            )
        logger.info(f"Created public subnets: {public_subnet_ids}")

        # Create public route table
        public_rt_response = self.ec2.create_route_table(
            VpcId=vpc_id,
            TagSpecifications=[{
                'ResourceType': 'route-table',
                'Tags': [{'Key': 'Name', 'Value': f'{name_prefix}-public-rt'}]
            }]
        )
        public_rt_id = public_rt_response['RouteTable']['RouteTableId']

        # Add route to Internet Gateway
        self.ec2.create_route(
            RouteTableId=public_rt_id,
            DestinationCidrBlock='0.0.0.0/0',
            GatewayId=igw_id
        )

        # Associate public subnets with public route table
        for subnet_id in public_subnet_ids:
            self.ec2.associate_route_table(RouteTableId=public_rt_id, SubnetId=subnet_id)

        # Create NAT Gateways (one per AZ for high availability)
        nat_gateway_ids = []
        for i, (public_subnet_id, az) in enumerate(zip(public_subnet_ids, available_azs)):
            # Allocate Elastic IP for NAT Gateway
            eip_response = self.ec2.allocate_address(
                Domain='vpc',
                TagSpecifications=[{
                    'ResourceType': 'elastic-ip',
                    'Tags': [{'Key': 'Name', 'Value': f'{name_prefix}-nat-eip-{i+1}'}]
                }]
            )

            # Create NAT Gateway
            nat_response = self.ec2.create_nat_gateway(
                SubnetId=public_subnet_id,
                AllocationId=eip_response['AllocationId'],
                TagSpecifications=[{
                    'ResourceType': 'natgateway',
                    'Tags': [{'Key': 'Name', 'Value': f'{name_prefix}-nat-{i+1}'}]
                }]
            )
            nat_gateway_ids.append(nat_response['NatGateway']['NatGatewayId'])

        logger.info(f"Created NAT Gateways: {nat_gateway_ids}")

        # Wait for NAT Gateways to become available
        logger.info("Waiting for NAT Gateways to become available...")
        for nat_id in nat_gateway_ids:
            waiter = self.ec2.get_waiter('nat_gateway_available')
            waiter.wait(NatGatewayIds=[nat_id])

        # Create private subnets
        private_subnet_ids = []
        for i, (cidr, az, nat_id) in enumerate(zip(vpc_config.private_subnet_cidrs, available_azs, nat_gateway_ids)):
            subnet_response = self.ec2.create_subnet(
                VpcId=vpc_id,
                CidrBlock=cidr,
                AvailabilityZone=az,
                TagSpecifications=[{
                    'ResourceType': 'subnet',
                    'Tags': [
                        {'Key': 'Name', 'Value': f'{name_prefix}-private-{i+1}'},
                        {'Key': 'kubernetes.io/role/internal-elb', 'Value': '1'}
                    ]
                }]
            )
            subnet_id = subnet_response['Subnet']['SubnetId']
            private_subnet_ids.append(subnet_id)

            # Create private route table for this subnet
            private_rt_response = self.ec2.create_route_table(
                VpcId=vpc_id,
                TagSpecifications=[{
                    'ResourceType': 'route-table',
                    'Tags': [{'Key': 'Name', 'Value': f'{name_prefix}-private-rt-{i+1}'}]
                }]
            )
            private_rt_id = private_rt_response['RouteTable']['RouteTableId']

            # Add route to NAT Gateway
            self.ec2.create_route(
                RouteTableId=private_rt_id,
                DestinationCidrBlock='0.0.0.0/0',
                NatGatewayId=nat_id
            )

            # Associate private subnet with its route table
            self.ec2.associate_route_table(RouteTableId=private_rt_id, SubnetId=subnet_id)

        logger.info(f"Created private subnets: {private_subnet_ids}")

        return {
            'vpc_id': vpc_id,
            'public_subnet_ids': public_subnet_ids,
            'private_subnet_ids': private_subnet_ids,
            'internet_gateway_id': igw_id,
            'nat_gateway_ids': nat_gateway_ids,
            'availability_zones': available_azs
        }

    def create_security_groups(self, vpc_id: str, name_prefix: str) -> Dict[str, str]:
        """
        Create security groups for EKS cluster and HyperPod nodes.

        Args:
            vpc_id: VPC ID where security groups will be created
            name_prefix: Prefix for resource naming

        Returns:
            Dictionary containing security group IDs
        """
        logger.info("Creating security groups...")

        # EKS Cluster Security Group
        eks_sg_response = self.ec2.create_security_group(
            GroupName=f'{name_prefix}-eks-cluster-sg',
            Description='Security group for EKS cluster',
            VpcId=vpc_id,
            TagSpecifications=[{
                'ResourceType': 'security-group',
                'Tags': [{'Key': 'Name', 'Value': f'{name_prefix}-eks-cluster-sg'}]
            }]
        )
        eks_cluster_sg_id = eks_sg_response['GroupId']

        # HyperPod Node Security Group
        hyperpod_sg_response = self.ec2.create_security_group(
            GroupName=f'{name_prefix}-hyperpod-node-sg',
            Description='Security group for HyperPod nodes',
            VpcId=vpc_id,
            TagSpecifications=[{
                'ResourceType': 'security-group',
                'Tags': [{'Key': 'Name', 'Value': f'{name_prefix}-hyperpod-node-sg'}]
            }]
        )
        hyperpod_sg_id = hyperpod_sg_response['GroupId']

        # Add rules for EKS cluster security group
        # Allow all traffic from HyperPod nodes
        self.ec2.authorize_security_group_ingress(
            GroupId=eks_cluster_sg_id,
            IpPermissions=[{
                'IpProtocol': '-1',
                'FromPort': -1,
                'ToPort': -1,
                'UserIdGroupPairs': [{'GroupId': hyperpod_sg_id}]
            }]
        )

        # Add rules for HyperPod node security group
        # Allow all traffic within the security group (node-to-node communication)
        self.ec2.authorize_security_group_ingress(
            GroupId=hyperpod_sg_id,
            IpPermissions=[{
                'IpProtocol': '-1',
                'FromPort': -1,
                'ToPort': -1,
                'UserIdGroupPairs': [{'GroupId': hyperpod_sg_id}]
            }]
        )

        # Allow all traffic from EKS cluster
        self.ec2.authorize_security_group_ingress(
            GroupId=hyperpod_sg_id,
            IpPermissions=[{
                'IpProtocol': '-1',
                'FromPort': -1,
                'ToPort': -1,
                'UserIdGroupPairs': [{'GroupId': eks_cluster_sg_id}]
            }]
        )

        # Allow HTTPS from anywhere (for API server access)
        self.ec2.authorize_security_group_ingress(
            GroupId=eks_cluster_sg_id,
            IpPermissions=[{
                'IpProtocol': 'tcp',
                'FromPort': 443,
                'ToPort': 443,
                'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'HTTPS access'}]
            }]
        )

        logger.info(f"Created security groups - EKS: {eks_cluster_sg_id}, HyperPod: {hyperpod_sg_id}")

        return {
            'eks_cluster_sg_id': eks_cluster_sg_id,
            'hyperpod_sg_id': hyperpod_sg_id
        }

    # ==================== IAM Roles and Policies ====================

    def create_eks_cluster_role(self, role_name: str) -> str:
        """
        Create IAM role for EKS cluster.

        Args:
            role_name: Name for the IAM role

        Returns:
            Role ARN
        """
        logger.info(f"Creating EKS cluster role: {role_name}")

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
                Description='IAM role for EKS cluster control plane',
                Tags=[
                    {'Key': 'Purpose', 'Value': 'HyperPod-EKS'},
                    {'Key': 'ManagedBy', 'Value': 'boto3'}
                ]
            )
            role_arn = response['Role']['Arn']

            # Attach required managed policies
            managed_policies = [
                'arn:aws:iam::aws:policy/AmazonEKSClusterPolicy',
                'arn:aws:iam::aws:policy/AmazonEKSVPCResourceController'
            ]

            for policy_arn in managed_policies:
                self.iam.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)

            logger.info(f"Created EKS cluster role: {role_arn}")
            return role_arn

        except ClientError as e:
            if e.response['Error']['Code'] == 'EntityAlreadyExists':
                role = self.iam.get_role(RoleName=role_name)
                logger.info(f"EKS cluster role already exists: {role['Role']['Arn']}")
                return role['Role']['Arn']
            raise

    def create_hyperpod_execution_role(self, role_name: str, s3_bucket_name: Optional[str] = None) -> str:
        """
        Create IAM role for HyperPod cluster instances.

        Args:
            role_name: Name for the IAM role
            s3_bucket_name: Optional S3 bucket name for additional access

        Returns:
            Role ARN
        """
        logger.info(f"Creating HyperPod execution role: {role_name}")

        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "sagemaker.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }

        try:
            response = self.iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description='IAM role for SageMaker HyperPod cluster instances',
                Tags=[
                    {'Key': 'Purpose', 'Value': 'HyperPod-EKS'},
                    {'Key': 'ManagedBy', 'Value': 'boto3'}
                ]
            )
            role_arn = response['Role']['Arn']

            # Attach required managed policy
            self.iam.attach_role_policy(
                RoleName=role_name,
                PolicyArn='arn:aws:iam::aws:policy/AmazonSageMakerClusterInstanceRolePolicy'
            )

            # Add S3 access policy if bucket specified
            if s3_bucket_name:
                s3_policy = {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "S3BucketAccess",
                            "Effect": "Allow",
                            "Action": [
                                "s3:GetObject",
                                "s3:PutObject",
                                "s3:DeleteObject",
                                "s3:ListBucket",
                                "s3:AbortMultipartUpload"
                            ],
                            "Resource": [
                                f"arn:aws:s3:::{s3_bucket_name}",
                                f"arn:aws:s3:::{s3_bucket_name}/*"
                            ]
                        }
                    ]
                }

                self.iam.put_role_policy(
                    RoleName=role_name,
                    PolicyName='HyperPodS3Access',
                    PolicyDocument=json.dumps(s3_policy)
                )

            # Add ECR access for container images
            ecr_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "ECRAccess",
                        "Effect": "Allow",
                        "Action": [
                            "ecr:GetDownloadUrlForLayer",
                            "ecr:BatchGetImage",
                            "ecr:BatchCheckLayerAvailability",
                            "ecr:GetAuthorizationToken"
                        ],
                        "Resource": "*"
                    }
                ]
            }

            self.iam.put_role_policy(
                RoleName=role_name,
                PolicyName='HyperPodECRAccess',
                PolicyDocument=json.dumps(ecr_policy)
            )

            logger.info(f"Created HyperPod execution role: {role_arn}")

            # Wait for role propagation
            time.sleep(10)

            return role_arn

        except ClientError as e:
            if e.response['Error']['Code'] == 'EntityAlreadyExists':
                role = self.iam.get_role(RoleName=role_name)
                logger.info(f"HyperPod execution role already exists: {role['Role']['Arn']}")
                return role['Role']['Arn']
            raise

    def create_cluster_autoscaling_role(self, role_name: str) -> str:
        """
        Create IAM role for HyperPod cluster autoscaling (Karpenter).

        Args:
            role_name: Name for the IAM role

        Returns:
            Role ARN
        """
        logger.info(f"Creating cluster autoscaling role: {role_name}")

        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "sagemaker.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }

        autoscaling_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Action": [
                    "sagemaker:BatchAddClusterNodes",
                    "sagemaker:BatchDeleteClusterNodes"
                ],
                "Resource": "*"
            }]
        }

        try:
            response = self.iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description='IAM role for HyperPod cluster autoscaling',
                Tags=[
                    {'Key': 'Purpose', 'Value': 'HyperPod-Autoscaling'},
                    {'Key': 'ManagedBy', 'Value': 'boto3'}
                ]
            )
            role_arn = response['Role']['Arn']

            # Create and attach autoscaling policy
            policy_response = self.iam.create_policy(
                PolicyName=f'{role_name}-policy',
                PolicyDocument=json.dumps(autoscaling_policy),
                Description='Policy for HyperPod autoscaling operations'
            )

            self.iam.attach_role_policy(
                RoleName=role_name,
                PolicyArn=policy_response['Policy']['Arn']
            )

            logger.info(f"Created cluster autoscaling role: {role_arn}")
            return role_arn

        except ClientError as e:
            if e.response['Error']['Code'] == 'EntityAlreadyExists':
                role = self.iam.get_role(RoleName=role_name)
                logger.info(f"Cluster autoscaling role already exists: {role['Role']['Arn']}")
                return role['Role']['Arn']
            raise

    # ==================== EKS Cluster ====================

    def create_eks_cluster(
        self,
        cluster_name: str,
        role_arn: str,
        subnet_ids: List[str],
        security_group_ids: List[str],
        config: EKSConfig = None
    ) -> Dict[str, Any]:
        """
        Create an Amazon EKS cluster.

        Args:
            cluster_name: Name for the EKS cluster
            role_arn: IAM role ARN for the cluster
            subnet_ids: List of subnet IDs
            security_group_ids: List of security group IDs
            config: EKS configuration parameters

        Returns:
            Cluster information dictionary
        """
        if config is None:
            config = EKSConfig()

        logger.info(f"Creating EKS cluster: {cluster_name}")

        cluster_config = {
            'name': cluster_name,
            'version': config.kubernetes_version,
            'roleArn': role_arn,
            'resourcesVpcConfig': {
                'subnetIds': subnet_ids,
                'securityGroupIds': security_group_ids,
                'endpointPublicAccess': config.endpoint_public_access,
                'endpointPrivateAccess': config.endpoint_private_access
            },
            'accessConfig': {
                'authenticationMode': config.authentication_mode,
                'bootstrapClusterCreatorAdminPermissions': True
            },
            'tags': {
                'Purpose': 'HyperPod',
                'ManagedBy': 'boto3'
            }
        }

        # Add logging configuration
        if config.enable_logging:
            cluster_config['logging'] = {
                'clusterLogging': [{
                    'types': config.log_types,
                    'enabled': True
                }]
            }

        try:
            response = self.eks.create_cluster(**cluster_config)
            cluster = response['cluster']

            logger.info(f"EKS cluster creation initiated")
            logger.info(f"  Name: {cluster['name']}")
            logger.info(f"  ARN: {cluster['arn']}")
            logger.info(f"  Status: {cluster['status']}")

            return cluster

        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceInUseException':
                logger.info(f"EKS cluster already exists: {cluster_name}")
                return self.eks.describe_cluster(name=cluster_name)['cluster']
            raise

    def wait_for_eks_cluster(self, cluster_name: str, timeout: int = 1800) -> Dict[str, Any]:
        """
        Wait for EKS cluster to become active.

        Args:
            cluster_name: Name of the EKS cluster
            timeout: Maximum wait time in seconds

        Returns:
            Cluster information dictionary
        """
        logger.info(f"Waiting for EKS cluster '{cluster_name}' to become active...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            response = self.eks.describe_cluster(name=cluster_name)
            cluster = response['cluster']
            status = cluster['status']

            logger.info(f"  Current status: {status}")

            if status == 'ACTIVE':
                logger.info(f"EKS cluster is now active!")
                return cluster
            elif status in ['FAILED', 'DELETING']:
                raise Exception(f"EKS cluster creation failed with status: {status}")

            time.sleep(30)

        raise TimeoutError(f"Timeout waiting for EKS cluster to become active")

    # ==================== S3 and Lifecycle Scripts ====================

    def create_lifecycle_bucket(self, bucket_name: str) -> str:
        """
        Create S3 bucket for lifecycle scripts.

        Args:
            bucket_name: Name for the S3 bucket

        Returns:
            Bucket name
        """
        logger.info(f"Creating S3 bucket for lifecycle scripts: {bucket_name}")

        try:
            if self.region == 'us-east-1':
                self.s3.create_bucket(Bucket=bucket_name)
            else:
                self.s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': self.region}
                )

            # Enable versioning
            self.s3.put_bucket_versioning(
                Bucket=bucket_name,
                VersioningConfiguration={'Status': 'Enabled'}
            )

            # Block public access
            self.s3.put_public_access_block(
                Bucket=bucket_name,
                PublicAccessBlockConfiguration={
                    'BlockPublicAcls': True,
                    'IgnorePublicAcls': True,
                    'BlockPublicPolicy': True,
                    'RestrictPublicBuckets': True
                }
            )

            logger.info(f"Created S3 bucket: {bucket_name}")
            return bucket_name

        except ClientError as e:
            if e.response['Error']['Code'] in ['BucketAlreadyExists', 'BucketAlreadyOwnedByYou']:
                logger.info(f"S3 bucket already exists: {bucket_name}")
                return bucket_name
            raise

    def upload_lifecycle_scripts(self, bucket_name: str, scripts_prefix: str = 'lifecycle-scripts/') -> str:
        """
        Upload lifecycle scripts to S3.

        Args:
            bucket_name: S3 bucket name
            scripts_prefix: S3 prefix for scripts

        Returns:
            S3 URI for lifecycle scripts
        """
        logger.info(f"Uploading lifecycle scripts to s3://{bucket_name}/{scripts_prefix}")

        # Default on_create.sh script for HyperPod EKS
        on_create_script = '''#!/bin/bash
set -ex

# HyperPod EKS Lifecycle Script
# This script runs during node creation

echo "=== Starting HyperPod EKS Node Setup ==="

# Update system packages
echo "Updating system packages..."
if command -v yum &> /dev/null; then
    sudo yum update -y
    sudo yum install -y jq wget curl git
elif command -v apt-get &> /dev/null; then
    sudo apt-get update -y
    sudo apt-get install -y jq wget curl git
fi

# Install AWS CLI v2 if not present
if ! command -v aws &> /dev/null; then
    echo "Installing AWS CLI v2..."
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
    unzip awscliv2.zip
    sudo ./aws/install
    rm -rf aws awscliv2.zip
fi

# Configure EFA (Elastic Fabric Adapter) if available
if [ -d "/opt/amazon/efa" ]; then
    echo "Configuring EFA..."
    export PATH=$PATH:/opt/amazon/efa/bin
    echo 'export PATH=$PATH:/opt/amazon/efa/bin' >> ~/.bashrc
fi

# Configure NCCL for multi-node training
echo "Configuring NCCL..."
export NCCL_DEBUG=INFO
export NCCL_SOCKET_IFNAME=eth0

# Set up shared storage mount point
echo "Setting up shared storage..."
sudo mkdir -p /fsx
sudo chmod 755 /fsx

# Configure kubectl if available
if command -v kubectl &> /dev/null; then
    echo "kubectl is available"
fi

# System optimizations for ML workloads
echo "Applying system optimizations..."
sudo sysctl -w net.core.rmem_max=67108864
sudo sysctl -w net.core.wmem_max=67108864
sudo sysctl -w net.ipv4.tcp_rmem="4096 87380 67108864"
sudo sysctl -w net.ipv4.tcp_wmem="4096 65536 67108864"

# GPU optimizations (if NVIDIA GPU is present)
if command -v nvidia-smi &> /dev/null; then
    echo "Configuring NVIDIA GPU settings..."
    sudo nvidia-smi -pm 1  # Enable persistence mode
    nvidia-smi  # Display GPU info
fi

echo "=== HyperPod EKS Node Setup Complete ==="
'''

        # Upload on_create.sh
        self.s3.put_object(
            Bucket=bucket_name,
            Key=f'{scripts_prefix}on_create.sh',
            Body=on_create_script.encode('utf-8'),
            ContentType='text/x-shellscript'
        )

        s3_uri = f's3://{bucket_name}/{scripts_prefix}'
        logger.info(f"Uploaded lifecycle scripts to: {s3_uri}")

        return s3_uri

    # ==================== HyperPod Cluster ====================

    def create_hyperpod_cluster(
        self,
        cluster_name: str,
        eks_cluster_arn: str,
        execution_role_arn: str,
        subnet_ids: List[str],
        security_group_ids: List[str],
        lifecycle_script_s3_uri: str,
        instance_groups: List[InstanceGroupConfig],
        config: HyperPodConfig = None,
        cluster_role_arn: Optional[str] = None,
        enable_autoscaling: bool = False
    ) -> Dict[str, Any]:
        """
        Create a SageMaker HyperPod cluster with EKS orchestration.

        Args:
            cluster_name: Name for the HyperPod cluster
            eks_cluster_arn: ARN of the EKS cluster
            execution_role_arn: IAM role ARN for HyperPod instances
            subnet_ids: List of private subnet IDs
            security_group_ids: List of security group IDs
            lifecycle_script_s3_uri: S3 URI for lifecycle scripts
            instance_groups: List of instance group configurations
            config: HyperPod configuration parameters
            cluster_role_arn: Optional IAM role for cluster operations (autoscaling)
            enable_autoscaling: Whether to enable Karpenter autoscaling

        Returns:
            HyperPod cluster creation response
        """
        if config is None:
            config = HyperPodConfig()

        logger.info(f"Creating HyperPod cluster: {cluster_name}")

        # Build instance groups configuration
        instance_groups_config = []
        for ig in instance_groups:
            ig_config = {
                'InstanceGroupName': ig.name,
                'InstanceType': ig.instance_type,
                'InstanceCount': ig.instance_count,
                'LifeCycleConfig': {
                    'SourceS3Uri': lifecycle_script_s3_uri,
                    'OnCreate': 'on_create.sh'
                },
                'ExecutionRole': execution_role_arn,
                'ThreadsPerCore': ig.threads_per_core
            }

            # Add min instance count for continuous provisioning
            if ig.min_instance_count is not None:
                ig_config['MinInstanceCount'] = ig.min_instance_count

            # Add Spot capacity requirements
            if ig.use_spot:
                ig_config['CapacityRequirements'] = {'Spot': {}}
            else:
                ig_config['CapacityRequirements'] = {'OnDemand': {}}

            # Add deep health checks
            if config.enable_deep_health_checks:
                ig_config['OnStartDeepHealthChecks'] = config.deep_health_check_types

            # Add Kubernetes configuration
            k8s_config = {}
            if ig.kubernetes_labels:
                k8s_config['Labels'] = ig.kubernetes_labels
            if ig.kubernetes_taints:
                k8s_config['Taints'] = ig.kubernetes_taints
            if k8s_config:
                ig_config['KubernetesConfig'] = k8s_config

            instance_groups_config.append(ig_config)

        # Build cluster configuration
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
            'NodeRecovery': config.node_recovery,
            'NodeProvisioningMode': config.node_provisioning_mode,
            'Tags': [
                {'Key': 'Purpose', 'Value': 'MLTraining'},
                {'Key': 'ManagedBy', 'Value': 'boto3'}
            ]
        }

        # Add autoscaling configuration
        if enable_autoscaling and cluster_role_arn:
            cluster_config['AutoScaling'] = {
                'AutoScalerType': 'Karpenter',
                'Mode': 'Enabled'
            }
            cluster_config['ClusterRole'] = cluster_role_arn

        try:
            response = self.sagemaker.create_cluster(**cluster_config)

            logger.info(f"HyperPod cluster creation initiated")
            logger.info(f"  Cluster ARN: {response['ClusterArn']}")

            return response

        except ClientError as e:
            logger.error(f"Failed to create HyperPod cluster: {e}")
            raise

    def wait_for_hyperpod_cluster(self, cluster_name: str, timeout: int = 3600) -> Dict[str, Any]:
        """
        Wait for HyperPod cluster to become InService.

        Args:
            cluster_name: Name of the HyperPod cluster
            timeout: Maximum wait time in seconds

        Returns:
            Cluster information dictionary
        """
        logger.info(f"Waiting for HyperPod cluster '{cluster_name}' to become InService...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            response = self.sagemaker.describe_cluster(ClusterName=cluster_name)
            status = response['ClusterStatus']

            logger.info(f"  Current status: {status}")

            if status == 'InService':
                logger.info(f"HyperPod cluster is now InService!")
                return response
            elif status in ['Failed', 'RollbackFailed']:
                failure_msg = response.get('FailureMessage', 'Unknown error')
                raise Exception(f"HyperPod cluster creation failed: {failure_msg}")

            time.sleep(60)

        raise TimeoutError(f"Timeout waiting for HyperPod cluster to become InService")

    # ==================== Full Stack Deployment ====================

    def deploy_full_stack(
        self,
        cluster_name: str,
        eks_cluster_name: str,
        instance_groups: List[InstanceGroupConfig],
        vpc_config: VPCConfig = None,
        eks_config: EKSConfig = None,
        hyperpod_config: HyperPodConfig = None,
        enable_autoscaling: bool = False,
        use_existing_vpc: bool = False,
        existing_vpc_id: Optional[str] = None,
        existing_subnet_ids: Optional[List[str]] = None,
        existing_security_group_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Deploy complete HyperPod EKS stack from scratch.

        Args:
            cluster_name: Base name for resources
            eks_cluster_name: Name for the EKS cluster
            instance_groups: List of instance group configurations
            vpc_config: Optional VPC configuration
            eks_config: Optional EKS configuration
            hyperpod_config: Optional HyperPod configuration
            enable_autoscaling: Whether to enable Karpenter autoscaling
            use_existing_vpc: Whether to use existing VPC
            existing_vpc_id: Existing VPC ID (if use_existing_vpc is True)
            existing_subnet_ids: Existing subnet IDs
            existing_security_group_ids: Existing security group IDs

        Returns:
            Dictionary containing all created resource information
        """
        logger.info("=" * 60)
        logger.info("Starting HyperPod EKS Full Stack Deployment")
        logger.info("=" * 60)

        results = {
            'region': self.region,
            'account_id': self.account_id
        }

        try:
            # Step 1: VPC and Networking
            if use_existing_vpc:
                logger.info("\n=== Step 1: Using Existing VPC ===")
                results['vpc'] = {
                    'vpc_id': existing_vpc_id,
                    'private_subnet_ids': existing_subnet_ids
                }
                subnet_ids = existing_subnet_ids
                security_group_ids = existing_security_group_ids
            else:
                logger.info("\n=== Step 1: Creating VPC Infrastructure ===")
                if vpc_config is None:
                    vpc_config = VPCConfig()
                vpc_info = self.create_vpc(vpc_config, cluster_name)
                results['vpc'] = vpc_info

                # Create security groups
                sg_info = self.create_security_groups(vpc_info['vpc_id'], cluster_name)
                results['security_groups'] = sg_info

                subnet_ids = vpc_info['private_subnet_ids']
                security_group_ids = [sg_info['eks_cluster_sg_id'], sg_info['hyperpod_sg_id']]

            # Step 2: IAM Roles
            logger.info("\n=== Step 2: Creating IAM Roles ===")
            eks_role_arn = self.create_eks_cluster_role(f'{cluster_name}-eks-role')
            results['eks_role_arn'] = eks_role_arn

            s3_bucket_name = f'sagemaker-{cluster_name}-{self.account_id}'
            hyperpod_role_arn = self.create_hyperpod_execution_role(
                f'{cluster_name}-hyperpod-role',
                s3_bucket_name
            )
            results['hyperpod_role_arn'] = hyperpod_role_arn

            cluster_autoscaling_role_arn = None
            if enable_autoscaling:
                cluster_autoscaling_role_arn = self.create_cluster_autoscaling_role(
                    f'{cluster_name}-autoscaling-role'
                )
                results['autoscaling_role_arn'] = cluster_autoscaling_role_arn

            # Wait for IAM role propagation
            logger.info("Waiting for IAM role propagation...")
            time.sleep(15)

            # Step 3: EKS Cluster
            logger.info("\n=== Step 3: Creating EKS Cluster ===")
            if eks_config is None:
                eks_config = EKSConfig()

            eks_cluster = self.create_eks_cluster(
                cluster_name=eks_cluster_name,
                role_arn=eks_role_arn,
                subnet_ids=subnet_ids,
                security_group_ids=security_group_ids,
                config=eks_config
            )
            results['eks_cluster'] = eks_cluster

            # Wait for EKS cluster to be active
            eks_cluster = self.wait_for_eks_cluster(eks_cluster_name)
            results['eks_cluster'] = eks_cluster

            # Step 4: S3 and Lifecycle Scripts
            logger.info("\n=== Step 4: Setting Up Lifecycle Scripts ===")
            self.create_lifecycle_bucket(s3_bucket_name)
            lifecycle_s3_uri = self.upload_lifecycle_scripts(s3_bucket_name)
            results['lifecycle_s3_uri'] = lifecycle_s3_uri
            results['s3_bucket'] = s3_bucket_name

            # Step 5: HyperPod Cluster
            logger.info("\n=== Step 5: Creating HyperPod Cluster ===")
            if hyperpod_config is None:
                hyperpod_config = HyperPodConfig()

            hyperpod_response = self.create_hyperpod_cluster(
                cluster_name=cluster_name,
                eks_cluster_arn=eks_cluster['arn'],
                execution_role_arn=hyperpod_role_arn,
                subnet_ids=subnet_ids,
                security_group_ids=security_group_ids,
                lifecycle_script_s3_uri=lifecycle_s3_uri,
                instance_groups=instance_groups,
                config=hyperpod_config,
                cluster_role_arn=cluster_autoscaling_role_arn,
                enable_autoscaling=enable_autoscaling
            )
            results['hyperpod_cluster'] = hyperpod_response

            # Wait for HyperPod cluster to be ready
            hyperpod_cluster = self.wait_for_hyperpod_cluster(cluster_name)
            results['hyperpod_cluster'] = hyperpod_cluster

            logger.info("\n" + "=" * 60)
            logger.info("HyperPod EKS Full Stack Deployment Complete!")
            logger.info("=" * 60)
            logger.info(f"EKS Cluster ARN: {eks_cluster['arn']}")
            logger.info(f"HyperPod Cluster ARN: {hyperpod_response['ClusterArn']}")

            return results

        except Exception as e:
            logger.error(f"Deployment failed: {e}")
            raise


# ==================== Utility Functions ====================

def get_available_instance_types(region: str = 'us-west-2') -> List[str]:
    """
    Get list of commonly used ML instance types for HyperPod.

    Args:
        region: AWS region

    Returns:
        List of instance type names
    """
    return [
        # GPU instances
        'ml.p4d.24xlarge',      # 8x A100 40GB
        'ml.p4de.24xlarge',     # 8x A100 80GB
        'ml.p5.48xlarge',       # 8x H100 80GB
        'ml.p3.16xlarge',       # 8x V100 16GB
        'ml.p3dn.24xlarge',     # 8x V100 32GB
        'ml.g5.48xlarge',       # 8x A10G
        'ml.g5.12xlarge',       # 4x A10G
        'ml.g5.xlarge',         # 1x A10G
        # CPU instances
        'ml.c5.18xlarge',
        'ml.c5n.18xlarge',
        'ml.m5.24xlarge',
        # Trainium instances
        'ml.trn1.32xlarge',
        'ml.trn1n.32xlarge',
    ]


# ==================== Main Entry Point ====================

if __name__ == '__main__':
    # Example usage
    deployer = HyperPodEKSDeployment(region='us-west-2')

    # Define instance groups
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

    # Deploy full stack (uncomment to run)
    # results = deployer.deploy_full_stack(
    #     cluster_name='my-hyperpod-cluster',
    #     eks_cluster_name='my-eks-cluster',
    #     instance_groups=instance_groups,
    #     enable_autoscaling=False
    # )

    print("HyperPod EKS Deployment module loaded successfully!")
    print("Available instance types:", get_available_instance_types())
