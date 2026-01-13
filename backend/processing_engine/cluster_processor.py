"""
Cluster Processing Engine

Processes pending cluster creation/deletion requests.
"""

import os
import time
import sys
import threading
import traceback

sys.path.append('./')

import dotenv
dotenv.load_dotenv('.env')

from model.data_model import ClusterStatus, EndpointStatus
from db_management.database import DatabaseWrapper
from eks_management.clusters import ClusterJobExecutor
from logger_config import setup_logger
from utils.config import DEFAULT_REGION
import json

logger = setup_logger('cluster_processor.py', log_file='cluster_processor.log')
database = DatabaseWrapper()

# Default lifecycle scripts folder path (relative to backend directory)
DEFAULT_LIFECYCLE_SCRIPTS_FOLDER = '../hyperpod_docs/lifecycle_scripts/base-config/'


def get_default_bucket_name(account_id: str, region: str) -> str:
    """Get default bucket name for HyperPod lifecycle scripts."""
    return f'llm-modelhub-hyperpod-{account_id}-{region}'


def ensure_default_bucket_and_script(executor: ClusterJobExecutor, s3_mount_bucket: str = None) -> str:  # type: ignore
    """
    Ensure default bucket exists and contains the default lifecycle scripts.

    Args:
        executor: ClusterJobExecutor instance
        s3_mount_bucket: Optional S3 bucket name for Mountpoint (reserved for future use)

    Returns: S3 URI for the lifecycle scripts directory
    """
    s3 = executor.s3
    account_id = executor.account_id
    region = executor.region or DEFAULT_REGION

    bucket_name = get_default_bucket_name(account_id, region)
    s3_key_prefix = 'LifecycleScripts/base-config/'

    # Check if bucket exists, create if not
    try:
        s3.head_bucket(Bucket=bucket_name)
        logger.info(f"Default bucket exists: {bucket_name}")
    except s3.exceptions.ClientError as e:
        error_code = e.response.get('Error', {}).get('Code')
        if error_code in ('404', 'NoSuchBucket'):
            logger.info(f"Creating default bucket: {bucket_name}")
            if region == 'us-east-1':
                s3.create_bucket(Bucket=bucket_name)
            else:
                s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': region}
                )
            logger.info(f"Created bucket: {bucket_name}")
        else:
            raise

    # Get the local lifecycle scripts folder path
    scripts_folder = os.path.join(os.path.dirname(__file__), '..', DEFAULT_LIFECYCLE_SCRIPTS_FOLDER)
    scripts_folder = os.path.abspath(scripts_folder)

    if os.path.exists(scripts_folder) and os.path.isdir(scripts_folder):
        logger.info(f"Uploading lifecycle scripts from: {scripts_folder}")

        # Upload all files from the base-config folder to S3
        uploaded_count = 0
        for filename in os.listdir(scripts_folder):
            file_path = os.path.join(scripts_folder, filename)
            if os.path.isfile(file_path):
                s3_key = f'{s3_key_prefix}{filename}'
                logger.info(f"Uploading {filename} to s3://{bucket_name}/{s3_key}")

                with open(file_path, 'rb') as f:
                    file_content = f.read()

                s3.put_object(Bucket=bucket_name, Key=s3_key, Body=file_content)
                uploaded_count += 1

        logger.info(f"Uploaded {uploaded_count} lifecycle scripts to s3://{bucket_name}/{s3_key_prefix}")
    else:
        logger.warning(f"Lifecycle scripts folder not found at: {scripts_folder}")
        # Create a minimal default script
        minimal_script = '''#!/bin/bash
set -ex
echo "[start] on_create.sh"
echo "HyperPod node initialization complete"
echo "[stop] on_create.sh"
'''
        s3.put_object(Bucket=bucket_name, Key=f'{s3_key_prefix}on_create.sh', Body=minimal_script.encode('utf-8'))
        logger.info(f"Created minimal lifecycle script at: s3://{bucket_name}/{s3_key_prefix}on_create.sh")

    return f's3://{bucket_name}/{s3_key_prefix}'


def get_pending_clusters():
    """Get clusters with PENDING status."""
    results = database.get_clusters_by_status(ClusterStatus.PENDING)
    return [ret[0] for ret in results]


def get_deleting_clusters():
    """Get clusters with DELETING status."""
    results = database.get_clusters_by_status(ClusterStatus.DELETING)
    return [ret[0] for ret in results]


def get_updating_clusters():
    """Get clusters with UPDATING status."""
    results = database.get_clusters_by_status(ClusterStatus.UPDATING)
    return [ret[0] for ret in results]


def sync_cluster_status_with_aws(cluster_id: str) -> bool:
    """
    Sync a single cluster's status with AWS.

    This function checks the actual cluster status from AWS and updates the database
    if there's a mismatch. This helps recover from scenarios where the database
    status got out of sync with AWS (e.g., update operation failures).

    Returns True if status was synced/updated, False otherwise.
    """
    try:
        cluster = database.get_cluster_by_id(cluster_id)
        if not cluster:
            logger.warning(f"Cluster not found for status sync: {cluster_id}")
            return False

        executor = ClusterJobExecutor(cluster_id)
        cluster_name = cluster.cluster_name
        db_status = cluster.cluster_status

        # Get actual status from AWS
        aws_status, error_msg = executor.get_hyperpod_cluster_status(cluster_name)
        logger.debug(f"Status sync check - Cluster {cluster_name}: DB={db_status.value}, AWS={aws_status}")

        # Map AWS status to database ClusterStatus
        aws_to_db_status = {
            'InService': ClusterStatus.ACTIVE,
            'Creating': ClusterStatus.CREATING,
            'Updating': ClusterStatus.UPDATING,
            'Deleting': ClusterStatus.DELETING,
            'Failed': ClusterStatus.FAILED,
            'RollbackFailed': ClusterStatus.FAILED,
        }

        expected_db_status = aws_to_db_status.get(aws_status)

        if expected_db_status and expected_db_status != db_status:
            logger.info(
                f"Syncing cluster {cluster_name} status: {db_status.value} -> {expected_db_status.value} "
                f"(AWS status: {aws_status})"
            )
            database.set_cluster_status(cluster_id, expected_db_status)

            # Update error message based on new status
            # Note: Don't use update_cluster_error() when clearing errors
            # because it always sets status to FAILED
            if expected_db_status == ClusterStatus.ACTIVE:
                # Clear error message without changing status
                database.clear_cluster_error(cluster_id)
            elif error_msg:
                # Only update error, status already set above
                database.set_cluster_error_message(cluster_id, error_msg)

            return True

        return False

    except Exception as e:
        logger.error(f"Error syncing cluster status for {cluster_id}: {e}")
        return False


def sync_all_cluster_statuses():
    """
    Sync all cluster statuses with AWS.

    This function is called periodically to ensure database stays in sync with AWS.
    It checks ACTIVE and FAILED clusters to catch any status mismatches.
    """
    try:
        # Get all clusters that might have status mismatches
        active_clusters = database.get_clusters_by_status(ClusterStatus.ACTIVE)
        failed_clusters = database.get_clusters_by_status(ClusterStatus.FAILED)

        all_clusters = [(c[0], 'ACTIVE') for c in active_clusters] + [(c[0], 'FAILED') for c in failed_clusters]

        if not all_clusters:
            return

        synced_count = 0
        for cluster_id, _ in all_clusters:
            if sync_cluster_status_with_aws(cluster_id):
                synced_count += 1

        if synced_count > 0:
            logger.info(f"Synced {synced_count} cluster statuses with AWS")

    except Exception as e:
        logger.error(f"Error in sync_all_cluster_statuses: {e}")


def create_vpc_and_subnets(executor: ClusterJobExecutor, cluster_name: str):
    """
    Create VPC with subnets for EKS cluster.

    Returns: (vpc_id, subnet_ids, security_group_ids)
    """
    ec2 = executor.ec2

    # Create VPC
    vpc_response = ec2.create_vpc(
        CidrBlock='10.0.0.0/16',
        TagSpecifications=[{
            'ResourceType': 'vpc',
            'Tags': [{'Key': 'Name', 'Value': f'{cluster_name}-vpc'}]
        }]
    )
    vpc_id = vpc_response['Vpc']['VpcId']
    logger.info(f"Created VPC: {vpc_id}")

    # Enable DNS hostnames
    ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={'Value': True})
    ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={'Value': True})

    # Get availability zones
    azs_response = ec2.describe_availability_zones(
        Filters=[{'Name': 'state', 'Values': ['available']}]
    )
    azs = [az['ZoneName'] for az in azs_response['AvailabilityZones'][:3]]

    # Create subnets (2 public, 2 private)
    subnet_ids = []

    for i, az in enumerate(azs[:2]):
        # Public subnet
        public_subnet = ec2.create_subnet(
            VpcId=vpc_id,
            CidrBlock=f'10.0.{i}.0/24',
            AvailabilityZone=az,
            TagSpecifications=[{
                'ResourceType': 'subnet',
                'Tags': [
                    {'Key': 'Name', 'Value': f'{cluster_name}-public-{az}'},
                    {'Key': 'kubernetes.io/role/elb', 'Value': '1'}
                ]
            }]
        )
        subnet_ids.append(public_subnet['Subnet']['SubnetId'])

        # Private subnet
        private_subnet = ec2.create_subnet(
            VpcId=vpc_id,
            CidrBlock=f'10.0.{i + 10}.0/24',
            AvailabilityZone=az,
            TagSpecifications=[{
                'ResourceType': 'subnet',
                'Tags': [
                    {'Key': 'Name', 'Value': f'{cluster_name}-private-{az}'},
                    {'Key': 'kubernetes.io/role/internal-elb', 'Value': '1'}
                ]
            }]
        )
        subnet_ids.append(private_subnet['Subnet']['SubnetId'])

    logger.info(f"Created subnets: {subnet_ids}")

    # Create Internet Gateway
    igw_response = ec2.create_internet_gateway(
        TagSpecifications=[{
            'ResourceType': 'internet-gateway',
            'Tags': [{'Key': 'Name', 'Value': f'{cluster_name}-igw'}]
        }]
    )
    igw_id = igw_response['InternetGateway']['InternetGatewayId']
    ec2.attach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)

    # Create route table for public subnets
    rt_response = ec2.create_route_table(
        VpcId=vpc_id,
        TagSpecifications=[{
            'ResourceType': 'route-table',
            'Tags': [{'Key': 'Name', 'Value': f'{cluster_name}-public-rt'}]
        }]
    )
    rt_id = rt_response['RouteTable']['RouteTableId']

    # Add route to internet gateway
    ec2.create_route(
        RouteTableId=rt_id,
        DestinationCidrBlock='0.0.0.0/0',
        GatewayId=igw_id
    )

    # Associate public subnets with route table
    for subnet_id in subnet_ids[::2]:  # Every other subnet is public
        ec2.associate_route_table(RouteTableId=rt_id, SubnetId=subnet_id)

    # Create security group
    sg_response = ec2.create_security_group(
        GroupName=f'{cluster_name}-eks-sg',
        Description=f'Security group for {cluster_name} EKS cluster',
        VpcId=vpc_id,
        TagSpecifications=[{
            'ResourceType': 'security-group',
            'Tags': [{'Key': 'Name', 'Value': f'{cluster_name}-eks-sg'}]
        }]
    )
    sg_id = sg_response['GroupId']

    # Add inbound rules for cluster communication
    ec2.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {
                'IpProtocol': '-1',
                'UserIdGroupPairs': [{'GroupId': sg_id}]
            }
        ]
    )

    logger.info(f"Created security group: {sg_id}")

    return vpc_id, subnet_ids, [sg_id]


def cleanup_vpc_resources(ec2, vpc_id: str, region: str = None):
    """
    Thoroughly cleanup all VPC resources before deletion.

    This function handles all resources that might be created by EKS, HyperPod,
    and the AWS Load Balancer Controller, ensuring complete VPC cleanup.
    """
    logger.info(f"Starting comprehensive VPC cleanup for {vpc_id}")

    # Get region from EC2 client if not provided
    if not region:
        region = ec2.meta.region_name if hasattr(ec2, 'meta') else DEFAULT_REGION

    try:
        # 0. Delete Load Balancers first (they create ENIs and security groups)
        logger.info("Cleaning up Load Balancers...")
        try:
            import boto3
            elbv2 = boto3.client('elbv2', region_name=region)

            # Find all load balancers in this VPC
            lbs = elbv2.describe_load_balancers()
            vpc_lbs = [lb for lb in lbs.get('LoadBalancers', []) if lb.get('VpcId') == vpc_id]

            for lb in vpc_lbs:
                lb_arn = lb['LoadBalancerArn']
                try:
                    logger.info(f"Deleting Load Balancer {lb['LoadBalancerName']}")
                    elbv2.delete_load_balancer(LoadBalancerArn=lb_arn)
                except Exception as e:
                    logger.error(f"Failed to delete Load Balancer: {e}")

            if vpc_lbs:
                logger.info("Waiting 30s for Load Balancers to delete...")
                time.sleep(30)

            # Delete target groups in this VPC
            tgs = elbv2.describe_target_groups()
            vpc_tgs = [tg for tg in tgs.get('TargetGroups', []) if tg.get('VpcId') == vpc_id]

            for tg in vpc_tgs:
                try:
                    logger.info(f"Deleting Target Group {tg['TargetGroupName']}")
                    elbv2.delete_target_group(TargetGroupArn=tg['TargetGroupArn'])
                except Exception as e:
                    logger.error(f"Failed to delete Target Group: {e}")
        except Exception as e:
            logger.error(f"Error cleaning up Load Balancers: {e}")

        # 1. Delete all NAT Gateways first (they take time)
        logger.info("Cleaning up NAT Gateways...")
        try:
            nat_gateways = ec2.describe_nat_gateways(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )
            for nat_gw in nat_gateways.get('NatGateways', []):
                if nat_gw['State'] not in ['deleted', 'deleting']:
                    try:
                        logger.info(f"Deleting NAT Gateway {nat_gw['NatGatewayId']}")
                        ec2.delete_nat_gateway(NatGatewayId=nat_gw['NatGatewayId'])
                    except Exception as e:
                        logger.error(f"Failed to delete NAT Gateway: {e}")

            # Wait for NAT Gateways to be deleted
            if nat_gateways.get('NatGateways'):
                logger.info("Waiting 60s for NAT Gateways to delete...")
                time.sleep(60)
        except Exception as e:
            logger.error(f"Error cleaning up NAT Gateways: {e}")

        # 1.5. Delete VPC Endpoints (S3 Gateway, ECR Interface endpoints, etc.)
        logger.info("Cleaning up VPC Endpoints...")
        try:
            vpc_endpoints = ec2.describe_vpc_endpoints(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )
            interface_endpoints_deleted = False
            for endpoint in vpc_endpoints.get('VpcEndpoints', []):
                if endpoint['State'] not in ['deleted', 'deleting']:
                    try:
                        endpoint_type = endpoint.get('VpcEndpointType', 'Unknown')
                        logger.info(f"Deleting VPC Endpoint {endpoint['VpcEndpointId']} (type: {endpoint_type})")
                        ec2.delete_vpc_endpoints(VpcEndpointIds=[endpoint['VpcEndpointId']])
                        if endpoint_type == 'Interface':
                            interface_endpoints_deleted = True
                    except Exception as e:
                        logger.error(f"Failed to delete VPC Endpoint: {e}")

            # Interface endpoints (ECR) take longer to delete - wait for them
            if interface_endpoints_deleted:
                logger.info("Waiting 30s for Interface VPC Endpoints to delete...")
                time.sleep(30)
        except Exception as e:
            logger.error(f"Error cleaning up VPC Endpoints: {e}")

        # 2. Delete all Network Interfaces (ENI) - EKS/HyperPod creates these
        logger.info("Cleaning up Network Interfaces...")
        try:
            enis = ec2.describe_network_interfaces(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )
            for eni in enis.get('NetworkInterfaces', []):
                try:
                    # Skip if in use
                    if eni.get('Attachment') and eni['Attachment'].get('Status') == 'attached':
                        attachment_id = eni['Attachment'].get('AttachmentId')
                        if attachment_id:
                            try:
                                logger.info(f"Detaching ENI {eni['NetworkInterfaceId']}")
                                ec2.detach_network_interface(AttachmentId=attachment_id, Force=True)
                                time.sleep(5)
                            except Exception as e:
                                logger.error(f"Failed to detach ENI: {e}")

                    logger.info(f"Deleting ENI {eni['NetworkInterfaceId']}")
                    ec2.delete_network_interface(NetworkInterfaceId=eni['NetworkInterfaceId'])
                except Exception as e:
                    logger.error(f"Failed to delete ENI {eni['NetworkInterfaceId']}: {e}")

            if enis.get('NetworkInterfaces'):
                logger.info("Waiting 10s for ENIs to delete...")
                time.sleep(10)
        except Exception as e:
            logger.error(f"Error cleaning up ENIs: {e}")

        # 3. Delete all security groups (except default) - with retry logic
        logger.info("Cleaning up Security Groups...")
        max_sg_retries = 3
        for sg_attempt in range(max_sg_retries):
            try:
                sgs = ec2.describe_security_groups(
                    Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
                )
                non_default_sgs = [sg for sg in sgs.get('SecurityGroups', []) if sg['GroupName'] != 'default']

                if not non_default_sgs:
                    logger.info("No non-default security groups remaining")
                    break

                logger.info(f"Security group cleanup attempt {sg_attempt + 1}/{max_sg_retries}, {len(non_default_sgs)} SGs remaining")

                # First pass: revoke all rules to break circular dependencies
                for sg in non_default_sgs:
                    try:
                        if sg.get('IpPermissions'):
                            ec2.revoke_security_group_ingress(
                                GroupId=sg['GroupId'],
                                IpPermissions=sg['IpPermissions']
                            )
                        if sg.get('IpPermissionsEgress'):
                            # Filter out default egress rule (can't be revoked)
                            egress_rules = [r for r in sg['IpPermissionsEgress']
                                          if not (r.get('IpProtocol') == '-1' and
                                                  r.get('IpRanges') == [{'CidrIp': '0.0.0.0/0'}])]
                            if egress_rules:
                                ec2.revoke_security_group_egress(
                                    GroupId=sg['GroupId'],
                                    IpPermissions=egress_rules
                                )
                    except Exception as e:
                        logger.debug(f"Failed to revoke SG rules for {sg['GroupId']}: {e}")

                # Second pass: delete security groups
                deleted_count = 0
                for sg in non_default_sgs:
                    try:
                        logger.info(f"Deleting Security Group {sg['GroupId']} ({sg['GroupName']})")
                        ec2.delete_security_group(GroupId=sg['GroupId'])
                        deleted_count += 1
                    except Exception as e:
                        if 'DependencyViolation' in str(e):
                            logger.debug(f"SG {sg['GroupId']} has dependencies, will retry")
                        else:
                            logger.error(f"Failed to delete Security Group {sg['GroupId']}: {e}")

                if deleted_count > 0 and sg_attempt < max_sg_retries - 1:
                    logger.info(f"Deleted {deleted_count} SGs, waiting before next attempt...")
                    time.sleep(10)
                elif deleted_count == 0 and sg_attempt < max_sg_retries - 1:
                    logger.info("No SGs deleted, waiting before retry...")
                    time.sleep(15)

            except Exception as e:
                logger.error(f"Error cleaning up Security Groups: {e}")

        # 4. Delete route tables (except main)
        logger.info("Cleaning up Route Tables...")
        try:
            rts = ec2.describe_route_tables(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )
            for rt in rts.get('RouteTables', []):
                is_main = any(assoc.get('Main', False) for assoc in rt.get('Associations', []))
                if not is_main:
                    for assoc in rt.get('Associations', []):
                        if not assoc.get('Main', False) and assoc.get('RouteTableAssociationId'):
                            try:
                                ec2.disassociate_route_table(AssociationId=assoc['RouteTableAssociationId'])
                            except Exception:
                                pass
                    try:
                        logger.info(f"Deleting Route Table {rt['RouteTableId']}")
                        ec2.delete_route_table(RouteTableId=rt['RouteTableId'])
                    except Exception as e:
                        logger.error(f"Failed to delete Route Table: {e}")
        except Exception as e:
            logger.error(f"Error cleaning up Route Tables: {e}")

        # 5. Detach and delete internet gateways
        logger.info("Cleaning up Internet Gateways...")
        try:
            igws = ec2.describe_internet_gateways(
                Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc_id]}]
            )
            for igw in igws.get('InternetGateways', []):
                try:
                    logger.info(f"Detaching/deleting Internet Gateway {igw['InternetGatewayId']}")
                    ec2.detach_internet_gateway(InternetGatewayId=igw['InternetGatewayId'], VpcId=vpc_id)
                    ec2.delete_internet_gateway(InternetGatewayId=igw['InternetGatewayId'])
                except Exception as e:
                    logger.error(f"Failed to delete Internet Gateway: {e}")
        except Exception as e:
            logger.error(f"Error cleaning up Internet Gateways: {e}")

        # 6. Delete all subnets - with retry logic
        logger.info("Cleaning up Subnets...")
        max_subnet_retries = 3
        for subnet_attempt in range(max_subnet_retries):
            try:
                subnets = ec2.describe_subnets(
                    Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
                )
                remaining_subnets = subnets.get('Subnets', [])

                if not remaining_subnets:
                    logger.info("All subnets deleted")
                    break

                logger.info(f"Subnet cleanup attempt {subnet_attempt + 1}/{max_subnet_retries}, {len(remaining_subnets)} subnets remaining")

                deleted_count = 0
                for subnet in remaining_subnets:
                    try:
                        logger.info(f"Deleting Subnet {subnet['SubnetId']}")
                        ec2.delete_subnet(SubnetId=subnet['SubnetId'])
                        deleted_count += 1
                    except Exception as e:
                        if 'DependencyViolation' in str(e):
                            logger.debug(f"Subnet {subnet['SubnetId']} has dependencies, will retry")
                        else:
                            logger.error(f"Failed to delete Subnet {subnet['SubnetId']}: {e}")

                if deleted_count == 0 and subnet_attempt < max_subnet_retries - 1:
                    # No progress, wait and retry (ENIs might still be deleting)
                    logger.info("No subnets deleted, waiting 15s before retry...")
                    time.sleep(15)
            except Exception as e:
                logger.error(f"Error cleaning up Subnets: {e}")

        # 7. Release Elastic IPs associated with this VPC's NAT Gateways
        logger.info("Releasing Elastic IPs associated with NAT Gateways...")
        try:
            addresses = ec2.describe_addresses()
            for addr in addresses.get('Addresses', []):
                # Check if this EIP has tags indicating it belongs to this VPC's cluster
                tags = {tag['Key']: tag['Value'] for tag in addr.get('Tags', [])}
                eip_name = tags.get('Name', '')

                # Release EIPs that are unassociated and were created for NAT Gateway
                # (After NAT Gateway deletion, the EIP becomes unassociated)
                if not addr.get('AssociationId') and '-nat-eip' in eip_name:
                    try:
                        logger.info(f"Releasing Elastic IP {addr['AllocationId']} ({eip_name})")
                        ec2.release_address(AllocationId=addr['AllocationId'])
                    except Exception as e:
                        logger.error(f"Failed to release Elastic IP {addr['AllocationId']}: {e}")
        except Exception as e:
            logger.error(f"Error releasing Elastic IPs: {e}")

        # 8. Finally delete the VPC - with retry logic
        logger.info(f"Deleting VPC {vpc_id}")
        max_vpc_retries = 3
        for vpc_attempt in range(max_vpc_retries):
            try:
                ec2.delete_vpc(VpcId=vpc_id)
                logger.info(f"Successfully deleted VPC {vpc_id}")
                return True
            except Exception as e:
                error_str = str(e)
                if 'DependencyViolation' in error_str and vpc_attempt < max_vpc_retries - 1:
                    logger.warning(f"VPC has remaining dependencies, retrying in 30s... (attempt {vpc_attempt + 1}/{max_vpc_retries})")
                    # Try to clean up any remaining resources
                    _cleanup_remaining_vpc_resources(ec2, vpc_id)
                    time.sleep(30)
                else:
                    logger.error(f"Failed to delete VPC {vpc_id}: {e}")
                    return False

        return False

    except Exception as e:
        logger.error(f"Failed to cleanup VPC {vpc_id}: {e}")
        return False


def _cleanup_remaining_vpc_resources(ec2, vpc_id: str):
    """
    Emergency cleanup of any remaining resources blocking VPC deletion.
    This is called when VPC deletion fails due to dependencies.
    """
    logger.info(f"Running emergency cleanup for VPC {vpc_id}")

    # Try to find and delete any remaining ENIs
    try:
        enis = ec2.describe_network_interfaces(
            Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
        )
        for eni in enis.get('NetworkInterfaces', []):
            try:
                eni_id = eni['NetworkInterfaceId']
                logger.info(f"Emergency: Force deleting ENI {eni_id}")

                # Detach if attached
                if eni.get('Attachment') and eni['Attachment'].get('AttachmentId'):
                    try:
                        ec2.detach_network_interface(
                            AttachmentId=eni['Attachment']['AttachmentId'],
                            Force=True
                        )
                        time.sleep(3)
                    except Exception:
                        pass

                ec2.delete_network_interface(NetworkInterfaceId=eni_id)
            except Exception as e:
                logger.debug(f"Failed to delete ENI {eni_id}: {e}")
    except Exception as e:
        logger.debug(f"Error in emergency ENI cleanup: {e}")

    # Try to find and delete any remaining security groups
    try:
        sgs = ec2.describe_security_groups(
            Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
        )
        for sg in sgs.get('SecurityGroups', []):
            if sg['GroupName'] != 'default':
                try:
                    logger.info(f"Emergency: Deleting SG {sg['GroupId']}")
                    # Clear all rules first
                    if sg.get('IpPermissions'):
                        ec2.revoke_security_group_ingress(
                            GroupId=sg['GroupId'],
                            IpPermissions=sg['IpPermissions']
                        )
                    ec2.delete_security_group(GroupId=sg['GroupId'])
                except Exception as e:
                    logger.debug(f"Failed to delete SG {sg['GroupId']}: {e}")
    except Exception as e:
        logger.debug(f"Error in emergency SG cleanup: {e}")


def rollback_cluster_resources(
    executor: ClusterJobExecutor,
    cluster_name: str,
    eks_cluster_name: str,
    created_resources: dict,
    cluster_config: dict
):
    """
    Rollback and cleanup resources created during failed cluster creation.

    Args:
        executor: ClusterJobExecutor instance
        cluster_name: HyperPod cluster name
        eks_cluster_name: EKS cluster name
        created_resources: Dict tracking which resources were created
        cluster_config: Original cluster configuration
    """
    logger.info(f"Starting rollback for cluster: {cluster_name}")

    # Rollback in reverse order of creation

    # 1. Delete HyperPod cluster if created
    if created_resources.get('hyperpod_cluster'):
        try:
            logger.info(f"Rollback: Deleting HyperPod cluster {cluster_name}")
            executor.delete_hyperpod_cluster(cluster_name)
            # Wait for deletion
            for _ in range(60):  # Max 30 minutes
                status, _ = executor.get_hyperpod_cluster_status(cluster_name)
                if status == 'NOTFOUND':
                    break
                time.sleep(30)
        except Exception as e:
            logger.error(f"Rollback: Failed to delete HyperPod cluster: {e}")

    # 2. Delete EKS cluster if created
    if created_resources.get('eks_cluster'):
        try:
            logger.info(f"Rollback: Deleting EKS cluster {eks_cluster_name}")
            executor.delete_eks_cluster(eks_cluster_name)
            # Wait for deletion
            for _ in range(60):  # Max 30 minutes
                try:
                    executor.eks.describe_cluster(name=eks_cluster_name)
                    time.sleep(30)
                except executor.eks.exceptions.ResourceNotFoundException:
                    break
                except Exception:
                    break
        except Exception as e:
            logger.error(f"Rollback: Failed to delete EKS cluster: {e}")

    # 3. Delete IAM roles if created
    iam = executor.iam
    if created_resources.get('hyperpod_role'):
        try:
            role_name = f'{cluster_name}-hyperpod-role'
            logger.info(f"Rollback: Deleting IAM role {role_name}")
            # Detach policies first
            try:
                policies = iam.list_attached_role_policies(RoleName=role_name)
                for policy in policies.get('AttachedPolicies', []):
                    iam.detach_role_policy(RoleName=role_name, PolicyArn=policy['PolicyArn'])
            except Exception:
                pass
            iam.delete_role(RoleName=role_name)
        except Exception as e:
            logger.error(f"Rollback: Failed to delete HyperPod IAM role: {e}")

    if created_resources.get('eks_role'):
        try:
            role_name = f'{cluster_name}-eks-role'
            logger.info(f"Rollback: Deleting IAM role {role_name}")
            # Detach policies first
            try:
                policies = iam.list_attached_role_policies(RoleName=role_name)
                for policy in policies.get('AttachedPolicies', []):
                    iam.detach_role_policy(RoleName=role_name, PolicyArn=policy['PolicyArn'])
            except Exception:
                pass
            iam.delete_role(RoleName=role_name)
        except Exception as e:
            logger.error(f"Rollback: Failed to delete EKS IAM role: {e}")

    # 4. Delete VPC resources if we created them (not using existing VPC)
    vpc_config = cluster_config.get('vpc_config')
    if not vpc_config or not vpc_config.get('vpc_id'):
        # We created the VPC, need to clean it up
        if created_resources.get('vpc'):
            try:
                vpc_id = created_resources['vpc']
                ec2 = executor.ec2
                logger.info(f"Rollback: Deleting VPC {vpc_id} and all associated resources")

                # Use comprehensive VPC cleanup function
                cleanup_vpc_resources(ec2, vpc_id)

            except Exception as e:
                logger.error(f"Rollback: Failed to cleanup VPC resources: {e}")

    logger.info(f"Rollback completed for cluster: {cluster_name}")


def create_vpc_and_subnets_with_tracking(executor: ClusterJobExecutor, cluster_name: str) -> tuple:
    """
    Create VPC with subnets for EKS cluster, tracking created resources for rollback.

    Returns: (vpc_id, all_subnet_ids, private_subnet_ids, security_group_ids, created_resources)

    Note: Returns both all_subnet_ids (for EKS) and private_subnet_ids (for HyperPod nodes).
    HyperPod nodes MUST be placed in private subnets with NAT Gateway access because:
    - Public subnets require public IPs for internet access via IGW
    - HyperPod nodes don't get public IPs by default
    - Private subnets route through NAT Gateway which doesn't require public IPs
    """
    ec2 = executor.ec2
    created_resources = {}

    # Create VPC
    vpc_response = ec2.create_vpc(
        CidrBlock='10.0.0.0/16',
        TagSpecifications=[{
            'ResourceType': 'vpc',
            'Tags': [{'Key': 'Name', 'Value': f'{cluster_name}-vpc'}]
        }]
    )
    vpc_id = vpc_response['Vpc']['VpcId']
    created_resources['vpc'] = vpc_id
    logger.info(f"Created VPC: {vpc_id}")

    # Enable DNS hostnames
    ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={'Value': True})
    ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={'Value': True})

    # Get availability zones
    azs_response = ec2.describe_availability_zones(
        Filters=[{'Name': 'state', 'Values': ['available']}]
    )
    azs = [az['ZoneName'] for az in azs_response['AvailabilityZones'][:3]]

    # Create subnets (2 public, 2 private)
    # Track public and private separately for proper routing
    public_subnet_ids = []
    private_subnet_ids = []
    created_resources['subnets'] = []

    for i, az in enumerate(azs[:2]):
        # Public subnet - for load balancers and NAT Gateway
        public_subnet = ec2.create_subnet(
            VpcId=vpc_id,
            CidrBlock=f'10.0.{i}.0/24',
            AvailabilityZone=az,
            TagSpecifications=[{
                'ResourceType': 'subnet',
                'Tags': [
                    {'Key': 'Name', 'Value': f'{cluster_name}-public-{az}'},
                    {'Key': 'kubernetes.io/role/elb', 'Value': '1'}
                ]
            }]
        )
        public_subnet_ids.append(public_subnet['Subnet']['SubnetId'])
        created_resources['subnets'].append(public_subnet['Subnet']['SubnetId'])

        # Private subnet - for HyperPod nodes (routes through NAT Gateway)
        private_subnet = ec2.create_subnet(
            VpcId=vpc_id,
            CidrBlock=f'10.0.{i + 10}.0/24',
            AvailabilityZone=az,
            TagSpecifications=[{
                'ResourceType': 'subnet',
                'Tags': [
                    {'Key': 'Name', 'Value': f'{cluster_name}-private-{az}'},
                    {'Key': 'kubernetes.io/role/internal-elb', 'Value': '1'}
                ]
            }]
        )
        private_subnet_ids.append(private_subnet['Subnet']['SubnetId'])
        created_resources['subnets'].append(private_subnet['Subnet']['SubnetId'])

    # All subnets for EKS (needs both public and private for load balancer placement)
    all_subnet_ids = public_subnet_ids + private_subnet_ids
    created_resources['public_subnets'] = public_subnet_ids
    created_resources['private_subnets'] = private_subnet_ids

    logger.info(f"Created public subnets: {public_subnet_ids}")
    logger.info(f"Created private subnets: {private_subnet_ids}")

    # Create Internet Gateway
    igw_response = ec2.create_internet_gateway(
        TagSpecifications=[{
            'ResourceType': 'internet-gateway',
            'Tags': [{'Key': 'Name', 'Value': f'{cluster_name}-igw'}]
        }]
    )
    igw_id = igw_response['InternetGateway']['InternetGatewayId']
    created_resources['internet_gateway'] = igw_id
    ec2.attach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)

    # Create route table for public subnets
    rt_response = ec2.create_route_table(
        VpcId=vpc_id,
        TagSpecifications=[{
            'ResourceType': 'route-table',
            'Tags': [{'Key': 'Name', 'Value': f'{cluster_name}-public-rt'}]
        }]
    )
    rt_id = rt_response['RouteTable']['RouteTableId']

    # Add route to internet gateway
    ec2.create_route(
        RouteTableId=rt_id,
        DestinationCidrBlock='0.0.0.0/0',
        GatewayId=igw_id
    )

    # Associate public subnets with route table
    for subnet_id in public_subnet_ids:
        ec2.associate_route_table(RouteTableId=rt_id, SubnetId=subnet_id)

    # Create security group
    sg_response = ec2.create_security_group(
        GroupName=f'{cluster_name}-eks-sg',
        Description=f'Security group for {cluster_name} EKS cluster',
        VpcId=vpc_id,
        TagSpecifications=[{
            'ResourceType': 'security-group',
            'Tags': [{'Key': 'Name', 'Value': f'{cluster_name}-eks-sg'}]
        }]
    )
    sg_id = sg_response['GroupId']
    created_resources['security_groups'] = [sg_id]

    # Add inbound rules for cluster communication
    ec2.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {
                'IpProtocol': '-1',
                'UserIdGroupPairs': [{'GroupId': sg_id}]
            }
        ]
    )

    logger.info(f"Created security group: {sg_id}")

    # Create private route table for private subnets
    private_rt_response = ec2.create_route_table(
        VpcId=vpc_id,
        TagSpecifications=[{
            'ResourceType': 'route-table',
            'Tags': [{'Key': 'Name', 'Value': f'{cluster_name}-private-rt'}]
        }]
    )
    private_rt_id = private_rt_response['RouteTable']['RouteTableId']
    created_resources['private_route_table'] = private_rt_id

    # Associate private subnets with private route table
    for subnet_id in private_subnet_ids:
        ec2.associate_route_table(RouteTableId=private_rt_id, SubnetId=subnet_id)

    logger.info(f"Created private route table: {private_rt_id}")

    # Create NAT Gateway for private subnets (required for HyperPod lifecycle scripts)
    # First, allocate an Elastic IP for the NAT Gateway
    logger.info("Creating Elastic IP for NAT Gateway...")
    eip_response = ec2.allocate_address(
        Domain='vpc',
        TagSpecifications=[{
            'ResourceType': 'elastic-ip',
            'Tags': [{'Key': 'Name', 'Value': f'{cluster_name}-nat-eip'}]
        }]
    )
    eip_allocation_id = eip_response['AllocationId']
    created_resources['nat_eip'] = eip_allocation_id
    logger.info(f"Created Elastic IP: {eip_allocation_id}")

    # Wait for EIP to be fully available (avoid InvalidAllocationID.NotFound)
    logger.info("Waiting for Elastic IP to propagate...")
    time.sleep(5)

    # Verify EIP exists before proceeding
    for attempt in range(3):
        try:
            ec2.describe_addresses(AllocationIds=[eip_allocation_id])
            logger.info(f"Elastic IP {eip_allocation_id} verified")
            break
        except Exception as e:
            if attempt < 2:
                logger.warning(f"EIP not ready yet, retrying... ({e})")
                time.sleep(5)
            else:
                raise Exception(f"Elastic IP {eip_allocation_id} not available after retries: {e}")

    # Create NAT Gateway in the first public subnet
    first_public_subnet = public_subnet_ids[0]
    logger.info(f"Creating NAT Gateway in public subnet {first_public_subnet}...")
    nat_gw_response = ec2.create_nat_gateway(
        SubnetId=first_public_subnet,
        AllocationId=eip_allocation_id,
        TagSpecifications=[{
            'ResourceType': 'natgateway',
            'Tags': [{'Key': 'Name', 'Value': f'{cluster_name}-nat-gw'}]
        }]
    )
    nat_gw_id = nat_gw_response['NatGateway']['NatGatewayId']
    created_resources['nat_gateway'] = nat_gw_id
    logger.info(f"Created NAT Gateway: {nat_gw_id}")

    # Wait for NAT Gateway to become available with better error handling
    logger.info("Waiting for NAT Gateway to become available...")
    max_attempts = 40
    for attempt in range(max_attempts):
        try:
            nat_status = ec2.describe_nat_gateways(NatGatewayIds=[nat_gw_id])
            state = nat_status['NatGateways'][0]['State']
            logger.info(f"NAT Gateway {nat_gw_id} state: {state} (attempt {attempt + 1}/{max_attempts})")

            if state == 'available':
                logger.info(f"NAT Gateway {nat_gw_id} is now available")
                break
            elif state == 'failed':
                failure_code = nat_status['NatGateways'][0].get('FailureCode', 'Unknown')
                failure_msg = nat_status['NatGateways'][0].get('FailureMessage', 'Unknown error')
                raise Exception(f"NAT Gateway creation failed: {failure_code} - {failure_msg}")
            elif state in ['pending', 'deleting']:
                time.sleep(15)
            else:
                raise Exception(f"Unexpected NAT Gateway state: {state}")
        except Exception as e:
            if 'NAT Gateway creation failed' in str(e) or 'Unexpected NAT Gateway state' in str(e):
                raise
            if attempt >= max_attempts - 1:
                raise Exception(f"NAT Gateway did not become available: {e}")
            time.sleep(15)

    # Add route to NAT Gateway in private route table
    ec2.create_route(
        RouteTableId=private_rt_id,
        DestinationCidrBlock='0.0.0.0/0',
        NatGatewayId=nat_gw_id
    )
    logger.info(f"Added route to NAT Gateway in private route table")

    # Create S3 VPC Gateway Endpoint (required for HyperPod to access S3)
    region = executor.region or DEFAULT_REGION
    try:
        s3_endpoint_response = ec2.create_vpc_endpoint(
            VpcId=vpc_id,
            ServiceName=f'com.amazonaws.{region}.s3',
            VpcEndpointType='Gateway',
            RouteTableIds=[rt_id, private_rt_id],  # Both public and private route tables
            TagSpecifications=[{
                'ResourceType': 'vpc-endpoint',
                'Tags': [{'Key': 'Name', 'Value': f'{cluster_name}-s3-endpoint'}]
            }]
        )
        s3_endpoint_id = s3_endpoint_response['VpcEndpoint']['VpcEndpointId']
        created_resources['s3_endpoint'] = s3_endpoint_id
        logger.info(f"Created S3 VPC Endpoint: {s3_endpoint_id}")
    except Exception as e:
        logger.error(f"Failed to create S3 VPC Endpoint: {e}")
        raise

    # Create ECR VPC Endpoints (required for private ECR access)
    # HyperPod nodes in private subnets need these to pull container images
    ecr_endpoints_created = []
    ecr_services = [
        ('ecr.api', 'Interface'),      # ECR API endpoint
        ('ecr.dkr', 'Interface'),      # ECR Docker registry endpoint
    ]

    for service_suffix, endpoint_type in ecr_services:
        try:
            endpoint_response = ec2.create_vpc_endpoint(
                VpcId=vpc_id,
                ServiceName=f'com.amazonaws.{region}.{service_suffix}',
                VpcEndpointType=endpoint_type,
                SubnetIds=private_subnet_ids,  # Interface endpoints go in private subnets
                SecurityGroupIds=[sg_id],
                PrivateDnsEnabled=True,
                TagSpecifications=[{
                    'ResourceType': 'vpc-endpoint',
                    'Tags': [{'Key': 'Name', 'Value': f'{cluster_name}-{service_suffix.replace(".", "-")}-endpoint'}]
                }]
            )
            endpoint_id = endpoint_response['VpcEndpoint']['VpcEndpointId']
            ecr_endpoints_created.append(endpoint_id)
            logger.info(f"Created {service_suffix} VPC Endpoint: {endpoint_id}")
        except Exception as e:
            logger.error(f"Failed to create {service_suffix} VPC Endpoint: {e}")
            # Continue - ECR endpoints are important but cluster may still work via NAT
            logger.warning(f"Cluster will rely on NAT Gateway for ECR access")

    if ecr_endpoints_created:
        created_resources['ecr_endpoints'] = ecr_endpoints_created

    # Return: vpc_id, all_subnet_ids (for EKS), private_subnet_ids (for HyperPod), security_groups, resources
    return vpc_id, all_subnet_ids, private_subnet_ids, [sg_id], created_resources


def process_cluster_creation(cluster_id: str):
    """Process a pending cluster creation request with rollback on failure."""
    logger.info(f"Processing cluster creation: {cluster_id}")

    cluster = database.get_cluster_by_id(cluster_id)
    if not cluster:
        logger.error(f"Cluster not found: {cluster_id}")
        return False

    # Track created resources for rollback
    created_resources = {}
    executor = None
    cluster_name = cluster.cluster_name
    eks_cluster_name = cluster.eks_cluster_name
    cluster_config = cluster.cluster_config or {}

    try:
        # Update status to CREATING
        database.set_cluster_status(cluster_id, ClusterStatus.CREATING)

        executor = ClusterJobExecutor(cluster_id)

        # Get VPC configuration
        vpc_config = cluster_config.get('vpc_config')

        if vpc_config and vpc_config.get('vpc_id'):
            # Use existing VPC - user must provide private subnets for HyperPod nodes
            vpc_id = vpc_config['vpc_id']
            all_subnet_ids = vpc_config.get('subnet_ids', [])
            # For existing VPCs, assume all provided subnets are suitable for HyperPod
            # User should provide private subnets with NAT Gateway access
            hyperpod_subnet_ids = vpc_config.get('private_subnet_ids') or all_subnet_ids
            security_group_ids = vpc_config.get('security_group_ids', [])

            if not security_group_ids:
                # Create security group in existing VPC
                sg_id = executor.create_security_group(vpc_id, f'{cluster_name}-eks-sg')
                security_group_ids = [sg_id]
                created_resources['security_groups'] = [sg_id]

            logger.info(f"Using existing VPC: {vpc_id}")
            logger.info(f"All subnets for EKS: {all_subnet_ids}")
            logger.info(f"Private subnets for HyperPod nodes: {hyperpod_subnet_ids}")
        else:
            # Create new VPC with tracking
            # Returns: (vpc_id, all_subnet_ids, private_subnet_ids, security_group_ids, created_resources)
            logger.info(f"Creating new VPC for cluster: {cluster_name}")
            vpc_id, all_subnet_ids, hyperpod_subnet_ids, security_group_ids, vpc_resources = create_vpc_and_subnets_with_tracking(executor, cluster_name)
            created_resources.update(vpc_resources)
            logger.info(f"All subnets for EKS: {all_subnet_ids}")
            logger.info(f"Private subnets for HyperPod nodes: {hyperpod_subnet_ids}")

        # Update database with VPC info (store all subnets)
        database.update_cluster_vpc_info(cluster_id, vpc_id, all_subnet_ids, security_group_ids)

        # Create IAM roles
        eks_role_name = f'{cluster_name}-eks-role'
        hyperpod_role_name = f'{cluster_name}-hyperpod-role'

        eks_role_arn = executor.create_eks_cluster_role(eks_role_name)
        created_resources['eks_role'] = True

        hyperpod_role_arn = executor.create_hyperpod_execution_role(hyperpod_role_name)
        created_resources['hyperpod_role'] = True

        # Get EKS configuration
        eks_config = cluster_config.get('eks_config', {})
        k8s_version = eks_config.get('kubernetes_version', '1.31')

        # Create EKS cluster (uses all subnets for load balancer placement)
        eks_result = executor.create_eks_cluster(
            cluster_name=eks_cluster_name,
            role_arn=eks_role_arn,
            subnet_ids=all_subnet_ids,
            security_group_ids=security_group_ids,
            kubernetes_version=k8s_version
        )
        created_resources['eks_cluster'] = True

        # Update EKS ARN
        database.update_cluster_arns(cluster_id, eks_cluster_arn=eks_result['arn'])

        # Wait for EKS cluster to be ready
        eks_cluster = executor.wait_for_eks_cluster(eks_cluster_name)

        # Install HyperPod dependencies on EKS cluster
        logger.info("Installing HyperPod dependencies on EKS cluster...")
        dependencies_installed = executor.install_hyperpod_dependencies(eks_cluster_name)
        if not dependencies_installed:
            raise Exception("Failed to install HyperPod dependencies on EKS cluster")
        logger.info("HyperPod dependencies installed successfully")

        # Get HyperPod configuration
        hyperpod_config = cluster_config.get('hyperpod_config', {})
        instance_groups = cluster_config.get('instance_groups', [])
        lifecycle_script_s3_uri = cluster_config.get('lifecycle_script_s3_uri')
        s3_mount_bucket = cluster_config.get('s3_mount_bucket')

        # If no lifecycle script is specified, use default bucket and script
        # Pass s3_mount_bucket to configure S3 Mountpoint in lifecycle script
        if not lifecycle_script_s3_uri:
            logger.info("No lifecycle script specified, ensuring default bucket and script...")
            if s3_mount_bucket:
                logger.info(f"S3 Mountpoint bucket specified: {s3_mount_bucket}")
            else:
                logger.info("No S3 Mountpoint bucket specified, will use default lifecycle bucket")
            lifecycle_script_s3_uri = ensure_default_bucket_and_script(executor, s3_mount_bucket)
            logger.info(f"Using default lifecycle script: {lifecycle_script_s3_uri}")

        # Create HyperPod cluster (uses ONLY private subnets for nodes)
        # IMPORTANT: HyperPod nodes must be in private subnets with NAT Gateway access
        # because nodes don't get public IPs and need NAT for internet/ECR access
        logger.info(f"Creating HyperPod cluster with private subnets: {hyperpod_subnet_ids}")
        hyperpod_result = executor.create_hyperpod_cluster(
            cluster_name=cluster_name,
            eks_cluster_arn=eks_cluster['arn'],
            execution_role_arn=hyperpod_role_arn,
            subnet_ids=hyperpod_subnet_ids,  # Private subnets only!
            security_group_ids=security_group_ids,
            instance_groups=instance_groups,
            lifecycle_script_s3_uri=lifecycle_script_s3_uri,
            node_recovery=hyperpod_config.get('node_recovery', 'Automatic'),
            node_provisioning_mode=hyperpod_config.get('node_provisioning_mode', 'Continuous'),
            enable_autoscaling=hyperpod_config.get('enable_autoscaling', False)
        )
        created_resources['hyperpod_cluster'] = True

        # Update HyperPod ARN
        database.update_cluster_arns(cluster_id, hyperpod_cluster_arn=hyperpod_result['ClusterArn'])

        # Wait for HyperPod cluster to become InService
        logger.info("Waiting for HyperPod cluster to become InService...")
        database.set_cluster_status(cluster_id, ClusterStatus.CREATING)
        hyperpod_cluster = executor.wait_for_hyperpod_cluster(cluster_name)
        logger.info("HyperPod cluster is now InService")

        # Setup HyperPod Inference Operator
        logger.info("Setting up HyperPod Inference Operator...")
        try:
            from inference.hyperpod_operator_setup import setup_inference_operator

            # Get region and account_id from executor
            cluster_region = executor.region or DEFAULT_REGION
            account_id = executor.account_id

            success, msg = setup_inference_operator(
                eks_cluster_name=eks_cluster_name,
                hyperpod_cluster_name=cluster_name,
                hyperpod_cluster_arn=hyperpod_result['ClusterArn'],
                region=cluster_region,
                account_id=account_id
            )

            if success:
                logger.info(f"HyperPod Inference Operator setup completed: {msg}")
            else:
                logger.warning(f"HyperPod Inference Operator setup failed: {msg}. "
                              "Inference deployments may not work until operator is installed manually.")
        except Exception as operator_error:
            logger.warning(f"Failed to setup HyperPod Inference Operator: {operator_error}. "
                          "Inference deployments may not work until operator is installed manually.")

        # Set status to ACTIVE
        database.set_cluster_status(cluster_id, ClusterStatus.ACTIVE)

        logger.info(f"Cluster creation completed: {cluster_id}")
        return True

    except Exception as e:
        error_detail = (
            f"Cluster creation failed for {cluster_id}:\n"
            f"Error Type: {type(e).__name__}\n"
            f"Error Message: {str(e)}\n\n"
            f"Full Traceback:\n{traceback.format_exc()}"
        )
        logger.error(error_detail)
        database.update_cluster_error(cluster_id, error_detail)

        # Perform rollback
        if executor and created_resources:
            logger.info(f"Starting rollback due to error: {str(e)}")
            try:
                rollback_cluster_resources(
                    executor=executor,
                    cluster_name=cluster_name,
                    eks_cluster_name=eks_cluster_name,
                    created_resources=created_resources,
                    cluster_config=cluster_config
                )
                database.update_cluster_error(
                    cluster_id,
                    error_detail + "\n\n[Rollback completed - resources cleaned up]"
                )
            except Exception as rollback_error:
                logger.error(f"Rollback failed: {rollback_error}")
                database.update_cluster_error(
                    cluster_id,
                    error_detail + f"\n\n[Rollback failed: {rollback_error}]"
                )

        return False


def process_cluster_deletion(cluster_id: str):
    """Process a cluster deletion request."""
    logger.info(f"Processing cluster deletion: {cluster_id}")

    cluster = database.get_cluster_by_id(cluster_id)
    if not cluster:
        logger.error(f"Cluster not found: {cluster_id}")
        return False

    try:
        executor = ClusterJobExecutor(cluster_id)
        cluster_name = cluster.cluster_name
        eks_cluster_name = cluster.eks_cluster_name

        # Delete HyperPod cluster first
        executor.delete_hyperpod_cluster(cluster_name)

        # Wait for HyperPod to be deleted
        max_wait = 600  # 10 minutes
        start_time = time.time()
        while time.time() - start_time < max_wait:
            status, _ = executor.get_hyperpod_cluster_status(cluster_name)
            if status == 'NOTFOUND':
                break
            logger.info(f"Waiting for HyperPod cluster deletion, status: {status}")
            time.sleep(30)

        # Delete EKS cluster
        executor.delete_eks_cluster(eks_cluster_name)

        # Wait for EKS to be deleted
        max_wait = 600  # 10 minutes
        start_time = time.time()
        while time.time() - start_time < max_wait:
            try:
                executor.eks.describe_cluster(name=eks_cluster_name)
                logger.info("Waiting for EKS cluster deletion...")
                time.sleep(30)
            except executor.eks.exceptions.ResourceNotFoundException:
                logger.info("EKS cluster deleted")
                break
            except Exception:
                break

        # Delete IAM roles
        iam = executor.iam
        for role_suffix in ['hyperpod-role', 'eks-role']:
            role_name = f'{cluster_name}-{role_suffix}'
            try:
                logger.info(f"Deleting IAM role {role_name}")
                # Detach policies first
                try:
                    policies = iam.list_attached_role_policies(RoleName=role_name)
                    for policy in policies.get('AttachedPolicies', []):
                        iam.detach_role_policy(RoleName=role_name, PolicyArn=policy['PolicyArn'])
                except Exception:
                    pass
                iam.delete_role(RoleName=role_name)
            except iam.exceptions.NoSuchEntityException:
                logger.info(f"IAM role {role_name} not found, skipping")
            except Exception as e:
                logger.error(f"Failed to delete IAM role {role_name}: {e}")

        # Delete VPC if it was auto-created
        cluster_config = cluster.cluster_config or {}
        vpc_config = cluster_config.get('vpc_config') or {}

        # If no VPC ID was provided in config, we created it and should delete it
        if cluster.vpc_id and not vpc_config.get('vpc_id'):
            try:
                logger.info(f"Deleting auto-created VPC {cluster.vpc_id}")
                cleanup_vpc_resources(executor.ec2, cluster.vpc_id)
            except Exception as e:
                logger.error(f"Failed to delete VPC {cluster.vpc_id}: {e}")
                logger.warning(f"VPC {cluster.vpc_id} may need manual deletion")

        # Mark cluster as deleted
        database.delete_cluster_by_id(cluster_id)

        logger.info(f"Cluster deletion completed: {cluster_id}")
        return True

    except Exception as e:
        error_detail = (
            f"Cluster deletion failed for {cluster_id}:\n"
            f"Error Type: {type(e).__name__}\n"
            f"Error Message: {str(e)}\n\n"
            f"Full Traceback:\n{traceback.format_exc()}"
        )
        logger.error(error_detail)
        database.update_cluster_error(cluster_id, error_detail)
        return False


def process_cluster_update(cluster_id: str) -> bool:
    """
    Process cluster update - monitor AWS status and update database when complete.

    This function checks the HyperPod cluster status in AWS and updates the database
    when the cluster transitions from Updating to InService.
    """
    try:
        cluster = database.get_cluster_by_id(cluster_id)
        if not cluster:
            logger.warning(f"Cluster not found for update monitoring: {cluster_id}")
            return False

        logger.info(f"Monitoring cluster update status: {cluster_id} ({cluster.cluster_name})")

        executor = ClusterJobExecutor(cluster_id)
        cluster_name = cluster.cluster_name

        # Check HyperPod cluster status from AWS
        hp_status, error_msg = executor.get_hyperpod_cluster_status(cluster_name)
        logger.info(f"HyperPod cluster {cluster_name} AWS status: {hp_status}")

        if hp_status == 'InService':
            # Update completed successfully
            logger.info(f"Cluster {cluster_name} update completed, status is now InService")
            database.set_cluster_status(cluster_id, ClusterStatus.ACTIVE)
            return True
        elif hp_status == 'Failed':
            # Update operation reported as failed - but cluster may recover
            # Wait and re-check AWS status to see if cluster recovers to InService
            logger.warning(f"Cluster {cluster_name} update reported as failed: {error_msg}")
            logger.info(f"Waiting 30 seconds to re-check cluster status...")
            time.sleep(30)

            # Re-check the actual cluster status from AWS
            final_status, final_error = executor.get_hyperpod_cluster_status(cluster_name)
            logger.info(f"Re-checked cluster {cluster_name} AWS status: {final_status}")

            if final_status == 'InService':
                # Cluster recovered! Update operation failed but cluster is still working
                logger.info(f"Cluster {cluster_name} recovered to InService after update failure")
                database.set_cluster_status(cluster_id, ClusterStatus.ACTIVE)
                # Record the update failure as a warning, not a fatal error
                update_error_msg = f"[Update Failed] {error_msg or 'Cluster update operation failed but cluster recovered to InService'}"
                database.update_cluster_error(cluster_id, update_error_msg)
                return True
            else:
                # Cluster is truly failed
                logger.error(f"Cluster {cluster_name} confirmed failed after re-check: {final_status}")
                database.set_cluster_status(cluster_id, ClusterStatus.FAILED)
                database.update_cluster_error(cluster_id, final_error or error_msg or "Cluster update failed")
                return False
        elif hp_status in ['Updating', 'Creating']:
            # Still updating, keep monitoring
            logger.info(f"Cluster {cluster_name} is still {hp_status}, continuing to monitor...")
            return False
        else:
            # Unexpected status
            logger.warning(f"Cluster {cluster_name} has unexpected status: {hp_status}")
            return False

    except Exception as e:
        error_detail = (
            f"Cluster update monitoring failed for {cluster_id}:\n"
            f"Error Type: {type(e).__name__}\n"
            f"Error Message: {str(e)}\n\n"
            f"Full Traceback:\n{traceback.format_exc()}"
        )
        logger.error(error_detail)
        return False


def start_cluster_processor():
    """Start the cluster processing engine."""
    logger.info("Starting cluster processing engine...")

    processing_threads = {}
    sync_counter = 0  # Counter for periodic status sync
    SYNC_INTERVAL = 30  # Sync every 30 iterations (5 minutes with 10s sleep)

    while True:
        # Periodic status sync with AWS (every 5 minutes)
        sync_counter += 1
        if sync_counter >= SYNC_INTERVAL:
            sync_counter = 0
            try:
                sync_all_cluster_statuses()
            except Exception as e:
                logger.error(f"Error in periodic status sync: {e}")
        # Process pending cluster creations
        pending_clusters = get_pending_clusters()
        if pending_clusters:
            logger.info(f"Found pending clusters: {pending_clusters}")

        for cluster_id in pending_clusters:
            if cluster_id not in processing_threads:
                thread = threading.Thread(
                    target=process_cluster_creation,
                    args=(cluster_id,)
                )
                thread.start()
                processing_threads[cluster_id] = thread

        # Process cluster deletions
        deleting_clusters = get_deleting_clusters()
        if deleting_clusters:
            logger.info(f"Found deleting clusters: {deleting_clusters}")

        for cluster_id in deleting_clusters:
            thread_key = f"delete_{cluster_id}"
            if thread_key not in processing_threads:
                thread = threading.Thread(
                    target=process_cluster_deletion,
                    args=(cluster_id,)
                )
                thread.start()
                processing_threads[thread_key] = thread

        # Process cluster updates (monitor UPDATING clusters)
        updating_clusters = get_updating_clusters()
        if updating_clusters:
            logger.info(f"Found updating clusters: {updating_clusters}")

        for cluster_id in updating_clusters:
            thread_key = f"update_{cluster_id}"
            if thread_key not in processing_threads:
                thread = threading.Thread(
                    target=process_cluster_update,
                    args=(cluster_id,)
                )
                thread.start()
                processing_threads[thread_key] = thread

        # Process HyperPod endpoints in CREATING status
        hyperpod_endpoints = get_hyperpod_endpoints_creating()
        if hyperpod_endpoints:
            logger.info(f"Found {len(hyperpod_endpoints)} HyperPod endpoints to monitor")

        for endpoint_name, cluster_id, extra_config in hyperpod_endpoints:
            thread_key = f"hp_endpoint_{endpoint_name}"
            if thread_key not in processing_threads:
                thread = threading.Thread(
                    target=process_hyperpod_endpoint_status,
                    args=(endpoint_name, cluster_id, extra_config)
                )
                thread.start()
                processing_threads[thread_key] = thread

        # Clean up completed threads
        completed = [k for k, t in processing_threads.items() if not t.is_alive()]
        for k in completed:
            del processing_threads[k]

        time.sleep(10)  # Scan every 10 seconds


def get_hyperpod_endpoints_creating():
    """Get all HyperPod endpoints in CREATING status."""
    try:
        return database.get_hyperpod_endpoints_creating()
    except Exception as e:
        logger.error(f"Error getting HyperPod endpoints: {e}")
        return []


def process_hyperpod_endpoint_status(endpoint_name: str, cluster_id: str, extra_config_str: str):
    """
    Process HyperPod endpoint status - monitor Kubernetes and update database.

    Args:
        endpoint_name: Name of the endpoint
        cluster_id: HyperPod cluster ID
        extra_config_str: Extra config JSON string containing namespace, eks_cluster_name
    """
    logger.info(f"Processing HyperPod endpoint status: {endpoint_name}")

    try:
        # Parse extra config to get namespace and EKS cluster name
        # Handle potential double-encoded JSON strings from older records
        extra_config = {}
        if extra_config_str:
            try:
                parsed = json.loads(extra_config_str)
                # If the result is still a string (double-encoded), decode again
                if isinstance(parsed, str):
                    extra_config = json.loads(parsed)
                elif isinstance(parsed, dict):
                    extra_config = parsed
                else:
                    logger.warning(f"Unexpected extra_config type: {type(parsed)}")
                    extra_config = {}
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse extra_config JSON: {e}")
                extra_config = {}

        namespace = extra_config.get('namespace', 'default')
        eks_cluster_name = extra_config.get('eks_cluster_name')

        if not eks_cluster_name:
            # Get from cluster record
            cluster = database.get_cluster_by_id(cluster_id)
            if not cluster:
                logger.error(f"Cluster not found: {cluster_id}")
                return
            eks_cluster_name = cluster.eks_cluster_name

        # Import here to avoid circular imports
        from inference.hyperpod_inference import get_hyperpod_endpoint_status

        # Get status from Kubernetes
        status, error_msg = get_hyperpod_endpoint_status(
            eks_cluster_name=eks_cluster_name,
            endpoint_name=endpoint_name,
            namespace=namespace,
            region=DEFAULT_REGION
        )

        logger.info(f"HyperPod endpoint {endpoint_name} status: {status}")

        # Update database based on status
        if status == 'INSERVICE':
            # Check if public ALB is requested
            use_public_alb = extra_config.get('use_public_alb', False)

            # Fetch ALB URL and store in extra_config
            alb_url = ''
            try:
                from inference.hyperpod_inference import get_hyperpod_endpoint_url
                url_info = get_hyperpod_endpoint_url(
                    eks_cluster_name=eks_cluster_name,
                    endpoint_name=endpoint_name,
                    namespace=namespace,
                    region=DEFAULT_REGION
                )
                if url_info:
                    alb_url = url_info.get('full_url', '')
                    extra_config['alb_url'] = alb_url
                    extra_config['endpoint_url'] = url_info.get('endpoint_url', '')
                    logger.info(f"HyperPod endpoint {endpoint_name} ALB URL: {alb_url}")
            except Exception as e:
                logger.warning(f"Failed to get ALB URL for {endpoint_name}: {e}")

            # If public ALB is requested but current ALB is internal, wait for public ALB
            if use_public_alb and alb_url and 'internal' in alb_url.lower():
                logger.info(f"HyperPod endpoint {endpoint_name} is InService but waiting for public ALB "
                           f"(current ALB is internal: {alb_url})")
                # Don't update status to INSERVICE yet, will check again next loop
                return

            database.update_endpoint_status(
                endpoint_name=endpoint_name,
                endpoint_status=EndpointStatus.INSERVICE,
                extra_config=json.dumps(extra_config) if extra_config else None
            )
            logger.info(f"HyperPod endpoint {endpoint_name} is now InService")
        elif status == 'FAILED':
            database.update_endpoint_status(
                endpoint_name=endpoint_name,
                endpoint_status=EndpointStatus.FAILED,
                extra_config=json.dumps({**extra_config, 'error': error_msg}) if error_msg else None
            )
            logger.error(f"HyperPod endpoint {endpoint_name} failed: {error_msg}")
        elif status == 'NOTFOUND':
            database.update_endpoint_status(
                endpoint_name=endpoint_name,
                endpoint_status=EndpointStatus.FAILED,
                extra_config=json.dumps({**extra_config, 'error': 'Endpoint not found in cluster'})
            )
            logger.error(f"HyperPod endpoint {endpoint_name} not found in cluster")
        # Status is CREATING - do nothing, will check again next loop

    except Exception as e:
        logger.error(f"Error processing HyperPod endpoint status: {e}")
        traceback.print_exc()


if __name__ == '__main__':
    start_cluster_processor()
