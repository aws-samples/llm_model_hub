#!/usr/bin/env python3
"""
Add NAT Gateway to an existing VPC for HyperPod clusters.

This script adds a NAT Gateway to enable private subnets to access the internet,
which is required for HyperPod lifecycle scripts to run successfully.

Usage:
    python3 add_nat_gateway.py --vpc-id vpc-xxx --cluster-name modelhub1
"""

import argparse
import boto3
import sys
import time


def get_vpc_info(ec2, vpc_id: str) -> dict:
    """Get VPC information including subnets and route tables."""
    vpc_info = {
        'vpc_id': vpc_id,
        'public_subnets': [],
        'private_subnets': [],
        'public_route_table': None,
        'private_route_table': None,
    }

    # Get all subnets in the VPC
    subnets = ec2.describe_subnets(
        Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
    )['Subnets']

    # Get all route tables in the VPC
    route_tables = ec2.describe_route_tables(
        Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
    )['RouteTables']

    # Identify public vs private route tables based on IGW route
    for rt in route_tables:
        has_igw = any(
            route.get('GatewayId', '').startswith('igw-')
            for route in rt.get('Routes', [])
        )

        # Get associated subnets
        associated_subnets = [
            assoc['SubnetId']
            for assoc in rt.get('Associations', [])
            if assoc.get('SubnetId')
        ]

        if has_igw:
            vpc_info['public_route_table'] = rt['RouteTableId']
            vpc_info['public_subnets'].extend(associated_subnets)
        elif associated_subnets:  # Has associated subnets but no IGW
            vpc_info['private_route_table'] = rt['RouteTableId']
            vpc_info['private_subnets'].extend(associated_subnets)

    return vpc_info


def check_nat_gateway_exists(ec2, vpc_id: str) -> bool:
    """Check if a NAT Gateway already exists in the VPC."""
    nat_gateways = ec2.describe_nat_gateways(
        Filters=[
            {'Name': 'vpc-id', 'Values': [vpc_id]},
            {'Name': 'state', 'Values': ['available', 'pending']}
        ]
    )['NatGateways']
    return len(nat_gateways) > 0


def add_nat_gateway(ec2, vpc_id: str, cluster_name: str, public_subnet_id: str, private_route_table_id: str) -> str:
    """Add NAT Gateway to the VPC."""

    # Allocate Elastic IP
    print(f"Allocating Elastic IP for NAT Gateway...")
    eip_response = ec2.allocate_address(
        Domain='vpc',
        TagSpecifications=[{
            'ResourceType': 'elastic-ip',
            'Tags': [{'Key': 'Name', 'Value': f'{cluster_name}-nat-eip'}]
        }]
    )
    eip_allocation_id = eip_response['AllocationId']
    print(f"  Created Elastic IP: {eip_allocation_id}")

    # Create NAT Gateway
    print(f"Creating NAT Gateway in subnet {public_subnet_id}...")
    nat_gw_response = ec2.create_nat_gateway(
        SubnetId=public_subnet_id,
        AllocationId=eip_allocation_id,
        TagSpecifications=[{
            'ResourceType': 'natgateway',
            'Tags': [{'Key': 'Name', 'Value': f'{cluster_name}-nat-gw'}]
        }]
    )
    nat_gw_id = nat_gw_response['NatGateway']['NatGatewayId']
    print(f"  Created NAT Gateway: {nat_gw_id}")

    # Wait for NAT Gateway to become available
    print("Waiting for NAT Gateway to become available (this may take a few minutes)...")
    waiter = ec2.get_waiter('nat_gateway_available')
    waiter.wait(
        NatGatewayIds=[nat_gw_id],
        WaiterConfig={'Delay': 15, 'MaxAttempts': 40}
    )
    print(f"  NAT Gateway {nat_gw_id} is now available")

    # Add route to NAT Gateway in private route table
    print(f"Adding route to NAT Gateway in private route table {private_route_table_id}...")
    try:
        ec2.create_route(
            RouteTableId=private_route_table_id,
            DestinationCidrBlock='0.0.0.0/0',
            NatGatewayId=nat_gw_id
        )
        print(f"  Added route 0.0.0.0/0 -> {nat_gw_id}")
    except ec2.exceptions.ClientError as e:
        if 'RouteAlreadyExists' in str(e):
            print(f"  Route already exists, replacing...")
            ec2.replace_route(
                RouteTableId=private_route_table_id,
                DestinationCidrBlock='0.0.0.0/0',
                NatGatewayId=nat_gw_id
            )
            print(f"  Replaced route 0.0.0.0/0 -> {nat_gw_id}")
        else:
            raise

    return nat_gw_id


def main():
    parser = argparse.ArgumentParser(description='Add NAT Gateway to existing VPC')
    parser.add_argument('--vpc-id', required=True, help='VPC ID')
    parser.add_argument('--cluster-name', required=True, help='Cluster name for tagging')
    parser.add_argument('--region', default='us-east-1', help='AWS region')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')

    args = parser.parse_args()

    ec2 = boto3.client('ec2', region_name=args.region)

    print(f"\n=== Adding NAT Gateway to VPC {args.vpc_id} ===\n")

    # Check if NAT Gateway already exists
    if check_nat_gateway_exists(ec2, args.vpc_id):
        print("NAT Gateway already exists in this VPC. Checking routes...")

        # Get VPC info to check if private route table has NAT route
        vpc_info = get_vpc_info(ec2, args.vpc_id)
        if vpc_info['private_route_table']:
            rt = ec2.describe_route_tables(
                RouteTableIds=[vpc_info['private_route_table']]
            )['RouteTables'][0]

            has_nat_route = any(
                route.get('NatGatewayId')
                for route in rt.get('Routes', [])
                if route.get('DestinationCidrBlock') == '0.0.0.0/0'
            )

            if has_nat_route:
                print("Private route table already has NAT Gateway route. Nothing to do.")
                return 0
            else:
                print("Private route table missing NAT Gateway route. Adding...")
                nat_gateways = ec2.describe_nat_gateways(
                    Filters=[
                        {'Name': 'vpc-id', 'Values': [args.vpc_id]},
                        {'Name': 'state', 'Values': ['available']}
                    ]
                )['NatGateways']

                if nat_gateways:
                    nat_gw_id = nat_gateways[0]['NatGatewayId']
                    if not args.dry_run:
                        ec2.create_route(
                            RouteTableId=vpc_info['private_route_table'],
                            DestinationCidrBlock='0.0.0.0/0',
                            NatGatewayId=nat_gw_id
                        )
                        print(f"Added route 0.0.0.0/0 -> {nat_gw_id}")
                    else:
                        print(f"[DRY RUN] Would add route 0.0.0.0/0 -> {nat_gw_id}")
        return 0

    # Get VPC information
    vpc_info = get_vpc_info(ec2, args.vpc_id)

    print(f"VPC Information:")
    print(f"  Public subnets: {vpc_info['public_subnets']}")
    print(f"  Private subnets: {vpc_info['private_subnets']}")
    print(f"  Public route table: {vpc_info['public_route_table']}")
    print(f"  Private route table: {vpc_info['private_route_table']}")
    print()

    if not vpc_info['public_subnets']:
        print("ERROR: No public subnets found in VPC. Cannot create NAT Gateway.")
        return 1

    if not vpc_info['private_route_table']:
        print("ERROR: No private route table found in VPC.")
        return 1

    if args.dry_run:
        print("[DRY RUN] Would create:")
        print(f"  - Elastic IP with tag: {args.cluster_name}-nat-eip")
        print(f"  - NAT Gateway in subnet: {vpc_info['public_subnets'][0]}")
        print(f"  - Route 0.0.0.0/0 -> NAT Gateway in route table: {vpc_info['private_route_table']}")
        return 0

    # Create NAT Gateway
    nat_gw_id = add_nat_gateway(
        ec2=ec2,
        vpc_id=args.vpc_id,
        cluster_name=args.cluster_name,
        public_subnet_id=vpc_info['public_subnets'][0],
        private_route_table_id=vpc_info['private_route_table']
    )

    print(f"\n=== NAT Gateway setup complete ===")
    print(f"NAT Gateway ID: {nat_gw_id}")
    print(f"\nPrivate subnets now have internet access through the NAT Gateway.")
    print("HyperPod lifecycle scripts should now run successfully.")

    return 0


if __name__ == '__main__':
    sys.exit(main())
