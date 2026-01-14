import boto3
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


def get_spot_price_history(
    instance_types: List[str],
    region: Optional[str] = None,
    days: int = 7
) -> Dict[str, Any]:
    """
    Query EC2 Spot Price History for the specified instance types.

    Args:
        instance_types: List of EC2 instance types (e.g., ['ml.g5.xlarge', 'ml.p4d.24xlarge'])
        region: AWS region (optional, uses default if not specified)
        days: Number of days to look back for price history (default: 7)

    Returns:
        Dictionary containing spot price history and availability statistics
    """
    try:
        # Create EC2 client
        if region:
            ec2_client = boto3.client('ec2', region_name=region)
        else:
            ec2_client = boto3.client('ec2')

        # Convert SageMaker instance types to EC2 instance types
        # SageMaker uses 'ml.' prefix, EC2 does not
        ec2_instance_types = []
        instance_type_mapping = {}
        for inst_type in instance_types:
            if inst_type.startswith('ml.'):
                ec2_type = inst_type[3:]  # Remove 'ml.' prefix
            else:
                ec2_type = inst_type
            ec2_instance_types.append(ec2_type)
            instance_type_mapping[ec2_type] = inst_type

        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=days)

        # Query spot price history
        paginator = ec2_client.get_paginator('describe_spot_price_history')

        price_data = defaultdict(lambda: defaultdict(list))

        for page in paginator.paginate(
            InstanceTypes=ec2_instance_types,
            StartTime=start_time,
            EndTime=end_time,
            ProductDescriptions=['Linux/UNIX']
        ):
            for price_record in page['SpotPriceHistory']:
                instance_type = price_record['InstanceType']
                az = price_record['AvailabilityZone']
                price = float(price_record['SpotPrice'])
                timestamp = price_record['Timestamp'].isoformat()

                # Map back to SageMaker instance type if applicable
                sagemaker_type = instance_type_mapping.get(instance_type, instance_type)

                price_data[sagemaker_type][az].append({
                    'price': price,
                    'timestamp': timestamp
                })

        # Calculate statistics for each instance type
        result = {
            'instance_types': {},
            'query_info': {
                'region': region or boto3.Session().region_name,
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat(),
                'days': days
            }
        }

        for inst_type in instance_types:
            az_data = price_data.get(inst_type, {})

            if not az_data:
                result['instance_types'][inst_type] = {
                    'available': False,
                    'message': 'No spot price history found. Instance type may not support spot or not available in this region.',
                    'availability_zones': []
                }
                continue

            az_stats = []
            all_prices = []

            for az, prices in az_data.items():
                if prices:
                    price_values = [p['price'] for p in prices]
                    all_prices.extend(price_values)

                    # Apply 15% SageMaker markup to all prices for consistency
                    az_stats.append({
                        'availability_zone': az,
                        'current_price': prices[0]['price'] * 1.15,  # Most recent with SageMaker markup
                        'min_price': min(price_values) * 1.15,
                        'max_price': max(price_values) * 1.15,
                        'avg_price': round(sum(price_values) / len(price_values) * 1.15, 4),
                        'price_count': len(prices),
                        'price_history': sorted(prices, key=lambda x: x['timestamp'], reverse=True)[:10]  # Last 10 records
                    })

            # Sort by current price (ascending)
            az_stats.sort(key=lambda x: x['current_price'])

            # Calculate overall statistics
            # Sagemaker price add 15% markup 
            if all_prices:
                overall_stats = {
                    'available': True,
                    'min_price': min(all_prices)*1.15,
                    'max_price': max(all_prices)*1.15,
                    'avg_price': round(sum(all_prices) / len(all_prices), 4)*1.15,
                    'price_volatility': round((max(all_prices) - min(all_prices)) / min(all_prices) * 100, 2) if min(all_prices) > 0 else 0,
                    'recommended_az': az_stats[0]['availability_zone'] if az_stats else None,
                    'availability_zones': az_stats
                }
            else:
                overall_stats = {
                    'available': False,
                    'message': 'No price data available',
                    'availability_zones': []
                }

            result['instance_types'][inst_type] = overall_stats

        return result

    except Exception as e:
        logger.error(f"Error querying spot price history: {str(e)}")
        return {
            'error': str(e),
            'instance_types': {},
            'query_info': {
                'region': region,
                'days': days
            }
        }


def get_spot_interruption_rate(
    instance_type: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get estimated spot interruption rate for an instance type.
    Note: AWS doesn't provide direct interruption rate API,
    this is based on price stability as a proxy.

    Args:
        instance_type: EC2/SageMaker instance type
        region: AWS region

    Returns:
        Dictionary with interruption risk assessment
    """
    price_history = get_spot_price_history([instance_type], region, days=30)

    if 'error' in price_history:
        return price_history

    inst_data = price_history.get('instance_types', {}).get(instance_type, {})

    if not inst_data.get('available'):
        return {
            'instance_type': instance_type,
            'risk_level': 'unknown',
            'message': 'No spot data available for this instance type'
        }

    # Assess risk based on price volatility
    volatility = inst_data.get('price_volatility', 0)

    if volatility < 10:
        risk_level = 'low'
        risk_description = 'Prices are stable. Low chance of interruption.'
    elif volatility < 30:
        risk_level = 'medium'
        risk_description = 'Moderate price volatility. Some risk of interruption during peak demand.'
    else:
        risk_level = 'high'
        risk_description = 'High price volatility. Higher chance of interruption. Consider using checkpointing.'

    return {
        'instance_type': instance_type,
        'risk_level': risk_level,
        'risk_description': risk_description,
        'price_volatility_percent': volatility,
        'avg_price': inst_data.get('avg_price'),
        'min_price': inst_data.get('min_price'),
        'max_price': inst_data.get('max_price'),
        'recommended_az': inst_data.get('recommended_az'),
        'num_availability_zones': len(inst_data.get('availability_zones', []))
    }
