#!/usr/bin/env python3
"""
Script to cleanup orphaned VPCs created by Model Hub but not properly deleted.
This helps resolve the "maximum number of VPCs has been reached" error.

Usage:
    python3 cleanup_orphaned_vpcs.py --list        # List all Model Hub VPCs
    python3 cleanup_orphaned_vpcs.py --vpc-id <vpc_id>  # Delete specific VPC
    python3 cleanup_orphaned_vpcs.py --cleanup-all      # Delete all orphaned VPCs
"""

import sys
import argparse
import boto3
import time
from botocore.exceptions import ClientError


def cleanup_vpc_resources(ec2, vpc_id: str, region: str = 'us-east-1'):
    """Thoroughly cleanup all VPC resources before deletion."""
    print(f"Starting comprehensive VPC cleanup for {vpc_id}")

    try:
        # 0. Delete Load Balancers first (they create ENIs and security groups)
        print("Cleaning up Load Balancers...")
        try:
            elbv2 = boto3.client('elbv2', region_name=region)

            # Find all load balancers in this VPC
            lbs = elbv2.describe_load_balancers()
            vpc_lbs = [lb for lb in lbs.get('LoadBalancers', []) if lb.get('VpcId') == vpc_id]

            for lb in vpc_lbs:
                try:
                    print(f"  Deleting Load Balancer {lb['LoadBalancerName']}")
                    elbv2.delete_load_balancer(LoadBalancerArn=lb['LoadBalancerArn'])
                except Exception as e:
                    print(f"  Failed to delete Load Balancer: {e}")

            if vpc_lbs:
                print("  Waiting 30s for Load Balancers to delete...")
                time.sleep(30)

            # Delete target groups in this VPC
            tgs = elbv2.describe_target_groups()
            vpc_tgs = [tg for tg in tgs.get('TargetGroups', []) if tg.get('VpcId') == vpc_id]

            for tg in vpc_tgs:
                try:
                    print(f"  Deleting Target Group {tg['TargetGroupName']}")
                    elbv2.delete_target_group(TargetGroupArn=tg['TargetGroupArn'])
                except Exception as e:
                    print(f"  Failed to delete Target Group: {e}")
        except Exception as e:
            print(f"Error cleaning up Load Balancers: {e}")

        # 1. Delete all NAT Gateways first (they take time)
        print("Cleaning up NAT Gateways...")
        try:
            nat_gateways = ec2.describe_nat_gateways(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )
            for nat_gw in nat_gateways.get('NatGateways', []):
                if nat_gw['State'] not in ['deleted', 'deleting']:
                    try:
                        print(f"  Deleting NAT Gateway {nat_gw['NatGatewayId']}")
                        ec2.delete_nat_gateway(NatGatewayId=nat_gw['NatGatewayId'])
                    except Exception as e:
                        print(f"  Failed to delete NAT Gateway: {e}")

            # Wait for NAT Gateways to be deleted
            if nat_gateways.get('NatGateways'):
                print("  Waiting 60s for NAT Gateways to delete...")
                time.sleep(60)
        except Exception as e:
            print(f"Error cleaning up NAT Gateways: {e}")

        # 1.5. Delete VPC Endpoints (S3 Gateway, ECR Interface endpoints, etc.)
        print("Cleaning up VPC Endpoints...")
        try:
            vpc_endpoints = ec2.describe_vpc_endpoints(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )
            interface_endpoints_deleted = False
            for endpoint in vpc_endpoints.get('VpcEndpoints', []):
                if endpoint['State'] not in ['deleted', 'deleting']:
                    try:
                        endpoint_type = endpoint.get('VpcEndpointType', 'Unknown')
                        print(f"  Deleting VPC Endpoint {endpoint['VpcEndpointId']} (type: {endpoint_type})")
                        ec2.delete_vpc_endpoints(VpcEndpointIds=[endpoint['VpcEndpointId']])
                        if endpoint_type == 'Interface':
                            interface_endpoints_deleted = True
                    except Exception as e:
                        print(f"  Failed to delete VPC Endpoint: {e}")

            # Interface endpoints take longer to delete
            if interface_endpoints_deleted:
                print("  Waiting 30s for Interface VPC Endpoints to delete...")
                time.sleep(30)
        except Exception as e:
            print(f"Error cleaning up VPC Endpoints: {e}")

        # 2. Delete all Network Interfaces (ENI) - EKS/HyperPod creates these
        print("Cleaning up Network Interfaces...")
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
                                print(f"  Detaching ENI {eni['NetworkInterfaceId']}")
                                ec2.detach_network_interface(AttachmentId=attachment_id, Force=True)
                                time.sleep(5)
                            except Exception as e:
                                print(f"  Failed to detach ENI: {e}")

                    print(f"  Deleting ENI {eni['NetworkInterfaceId']}")
                    ec2.delete_network_interface(NetworkInterfaceId=eni['NetworkInterfaceId'])
                except Exception as e:
                    print(f"  Failed to delete ENI {eni['NetworkInterfaceId']}: {e}")

            if enis.get('NetworkInterfaces'):
                print("  Waiting 10s for ENIs to delete...")
                time.sleep(10)
        except Exception as e:
            print(f"Error cleaning up ENIs: {e}")

        # 3. Delete all security groups (except default)
        print("Cleaning up Security Groups...")
        try:
            sgs = ec2.describe_security_groups(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )
            # Delete in two passes to handle dependencies
            for sg in sgs.get('SecurityGroups', []):
                if sg['GroupName'] != 'default':
                    try:
                        # First, revoke all ingress rules
                        if sg.get('IpPermissions'):
                            ec2.revoke_security_group_ingress(
                                GroupId=sg['GroupId'],
                                IpPermissions=sg['IpPermissions']
                            )
                        # Revoke all egress rules (parameter is IpPermissions, not IpPermissionsEgress)
                        if sg.get('IpPermissionsEgress'):
                            ec2.revoke_security_group_egress(
                                GroupId=sg['GroupId'],
                                IpPermissions=sg['IpPermissionsEgress']
                            )
                    except Exception as e:
                        print(f"  Failed to revoke SG rules: {e}")

            # Second pass: delete security groups
            for sg in sgs.get('SecurityGroups', []):
                if sg['GroupName'] != 'default':
                    try:
                        print(f"  Deleting Security Group {sg['GroupId']}")
                        ec2.delete_security_group(GroupId=sg['GroupId'])
                    except Exception as e:
                        print(f"  Failed to delete Security Group {sg['GroupId']}: {e}")
        except Exception as e:
            print(f"Error cleaning up Security Groups: {e}")

        # 4. Delete route tables (except main)
        print("Cleaning up Route Tables...")
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
                        print(f"  Deleting Route Table {rt['RouteTableId']}")
                        ec2.delete_route_table(RouteTableId=rt['RouteTableId'])
                    except Exception as e:
                        print(f"  Failed to delete Route Table: {e}")
        except Exception as e:
            print(f"Error cleaning up Route Tables: {e}")

        # 5. Detach and delete internet gateways
        print("Cleaning up Internet Gateways...")
        try:
            igws = ec2.describe_internet_gateways(
                Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc_id]}]
            )
            for igw in igws.get('InternetGateways', []):
                try:
                    print(f"  Detaching/deleting Internet Gateway {igw['InternetGatewayId']}")
                    ec2.detach_internet_gateway(InternetGatewayId=igw['InternetGatewayId'], VpcId=vpc_id)
                    ec2.delete_internet_gateway(InternetGatewayId=igw['InternetGatewayId'])
                except Exception as e:
                    print(f"  Failed to delete Internet Gateway: {e}")
        except Exception as e:
            print(f"Error cleaning up Internet Gateways: {e}")

        # 6. Delete all subnets
        print("Cleaning up Subnets...")
        try:
            subnets = ec2.describe_subnets(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )
            for subnet in subnets.get('Subnets', []):
                try:
                    print(f"  Deleting Subnet {subnet['SubnetId']}")
                    ec2.delete_subnet(SubnetId=subnet['SubnetId'])
                except Exception as e:
                    print(f"  Failed to delete Subnet {subnet['SubnetId']}: {e}")
        except Exception as e:
            print(f"Error cleaning up Subnets: {e}")

        # 7. Finally delete the VPC
        print(f"Deleting VPC {vpc_id}")
        ec2.delete_vpc(VpcId=vpc_id)
        print(f"Successfully deleted VPC {vpc_id}")
        return True

    except Exception as e:
        print(f"Failed to cleanup VPC {vpc_id}: {e}")
        return False


def list_modelhub_vpcs(ec2):
    """List all VPCs that appear to be created by Model Hub."""
    vpcs = ec2.describe_vpcs()

    modelhub_vpcs = []
    for vpc in vpcs.get('Vpcs', []):
        vpc_id = vpc['VpcId']
        vpc_name = ''

        # Get VPC name from tags
        for tag in vpc.get('Tags', []):
            if tag['Key'] == 'Name':
                vpc_name = tag['Value']
                break

        # Check if it's a Model Hub VPC
        if 'modelhub' in vpc_name.lower() or 'llm-modelhub' in vpc_name.lower():
            modelhub_vpcs.append({
                'VpcId': vpc_id,
                'Name': vpc_name,
                'CidrBlock': vpc.get('CidrBlock', ''),
                'IsDefault': vpc.get('IsDefault', False)
            })

    return modelhub_vpcs


def main():
    parser = argparse.ArgumentParser(description='Cleanup orphaned VPCs')
    parser.add_argument('--list', action='store_true', help='List all Model Hub VPCs')
    parser.add_argument('--vpc-id', type=str, help='Delete specific VPC by ID')
    parser.add_argument('--cleanup-all', action='store_true', help='Delete all orphaned Model Hub VPCs')
    parser.add_argument('--region', type=str, default='us-east-1', help='AWS region')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without deleting')

    args = parser.parse_args()

    if not any([args.list, args.vpc_id, args.cleanup_all]):
        parser.print_help()
        return

    ec2 = boto3.client('ec2', region_name=args.region)

    if args.list:
        print(f"\n=== Model Hub VPCs in {args.region} ===\n")
        vpcs = list_modelhub_vpcs(ec2)

        if not vpcs:
            print("No Model Hub VPCs found.")
            return

        for vpc in vpcs:
            print(f"VPC ID:     {vpc['VpcId']}")
            print(f"Name:       {vpc['Name']}")
            print(f"CIDR Block: {vpc['CidrBlock']}")
            print(f"Default:    {vpc['IsDefault']}")
            print("-" * 60)

        print(f"\nTotal: {len(vpcs)} VPC(s) found")
        print("\nTo delete a specific VPC:")
        print(f"  python3 {sys.argv[0]} --vpc-id <vpc_id>")
        print("\nTo delete all orphaned VPCs:")
        print(f"  python3 {sys.argv[0]} --cleanup-all")

    elif args.vpc_id:
        if args.dry_run:
            print(f"[DRY RUN] Would delete VPC: {args.vpc_id}")
            return

        print(f"Deleting VPC {args.vpc_id}...")
        try:
            success = cleanup_vpc_resources(ec2, args.vpc_id, args.region)
            if success:
                print(f"✓ Successfully deleted VPC {args.vpc_id}")
            else:
                print(f"✗ Failed to delete VPC {args.vpc_id}")
        except Exception as e:
            print(f"✗ Error deleting VPC: {e}")

    elif args.cleanup_all:
        vpcs = list_modelhub_vpcs(ec2)

        if not vpcs:
            print("No Model Hub VPCs found to cleanup.")
            return

        print(f"\nFound {len(vpcs)} Model Hub VPC(s) to cleanup:")
        for vpc in vpcs:
            print(f"  - {vpc['VpcId']} ({vpc['Name']})")

        if args.dry_run:
            print("\n[DRY RUN] Would delete all the above VPCs.")
            return

        print("\nWARNING: This will delete all listed VPCs!")
        response = input("Are you sure you want to continue? (yes/no): ")

        if response.lower() != 'yes':
            print("Operation cancelled.")
            return

        print("\nStarting cleanup...")
        for vpc in vpcs:
            vpc_id = vpc['VpcId']
            print(f"\nDeleting {vpc_id} ({vpc['Name']})...")
            try:
                success = cleanup_vpc_resources(ec2, vpc_id, args.region)
                if success:
                    print(f"  ✓ Successfully deleted {vpc_id}")
                else:
                    print(f"  ✗ Failed to delete {vpc_id}")
            except Exception as e:
                print(f"  ✗ Error: {e}")

        print("\nCleanup completed.")


if __name__ == '__main__':
    main()
