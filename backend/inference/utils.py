"""
Utility functions and constants for HyperPod inference.

This module contains:
- Instance type resource mappings (GPU, CPU, memory)
- Helper functions for resource calculations
"""

import math
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# GPU count mapping for instance types
GPU_MAPPING = {
    "ml.g5.xlarge": 1,
    "ml.g5.2xlarge": 1,
    "ml.g5.4xlarge": 1,
    "ml.g5.8xlarge": 1,
    "ml.g5.12xlarge": 4,
    "ml.g5.16xlarge": 1,
    "ml.g5.24xlarge": 4,
    "ml.g5.48xlarge": 8,
    "ml.g6.xlarge": 1,
    "ml.g6.2xlarge": 1,
    "ml.g6.4xlarge": 1,
    "ml.g6.8xlarge": 1,
    "ml.g6.12xlarge": 4,
    "ml.g6.16xlarge": 1,
    "ml.g6.24xlarge": 4,
    "ml.g6.48xlarge": 8,
    "ml.g6e.xlarge": 1,
    "ml.g6e.2xlarge": 1,
    "ml.g6e.4xlarge": 1,
    "ml.g6e.8xlarge": 1,
    "ml.g6e.12xlarge": 4,
    "ml.g6e.16xlarge": 1,
    "ml.g6e.24xlarge": 4,
    "ml.g6e.48xlarge": 8,
    "ml.p4d.24xlarge": 8,
    "ml.p4de.24xlarge": 8,
    "ml.p5.48xlarge": 8,
    "ml.p5e.48xlarge": 8,
    "ml.p5en.48xlarge": 8,
}

# Instance type resource mapping (cpu, memory in Gi)
# Values set to 50% of instance capacity to leave room for system processes
INSTANCE_RESOURCES = {
    # G5 instances (NVIDIA A10G GPU)
    "ml.g5.xlarge": {"cpu": "2", "memory": "8Gi"},        # 4 vCPU, 16 GB
    "ml.g5.2xlarge": {"cpu": "4", "memory": "16Gi"},      # 8 vCPU, 32 GB
    "ml.g5.4xlarge": {"cpu": "8", "memory": "32Gi"},      # 16 vCPU, 64 GB
    "ml.g5.8xlarge": {"cpu": "16", "memory": "64Gi"},     # 32 vCPU, 128 GB
    "ml.g5.12xlarge": {"cpu": "24", "memory": "96Gi"},    # 48 vCPU, 192 GB
    "ml.g5.16xlarge": {"cpu": "32", "memory": "128Gi"},   # 64 vCPU, 256 GB
    "ml.g5.24xlarge": {"cpu": "48", "memory": "192Gi"},   # 96 vCPU, 384 GB
    "ml.g5.48xlarge": {"cpu": "96", "memory": "384Gi"},   # 192 vCPU, 768 GB
    # G6 instances (NVIDIA L4 GPU)
    "ml.g6.xlarge": {"cpu": "2", "memory": "8Gi"},        # 4 vCPU, 16 GB
    "ml.g6.2xlarge": {"cpu": "4", "memory": "16Gi"},      # 8 vCPU, 32 GB
    "ml.g6.4xlarge": {"cpu": "8", "memory": "32Gi"},      # 16 vCPU, 64 GB
    "ml.g6.8xlarge": {"cpu": "16", "memory": "64Gi"},     # 32 vCPU, 128 GB
    "ml.g6.12xlarge": {"cpu": "24", "memory": "96Gi"},    # 48 vCPU, 192 GB
    "ml.g6.16xlarge": {"cpu": "32", "memory": "128Gi"},   # 64 vCPU, 256 GB
    "ml.g6.24xlarge": {"cpu": "48", "memory": "192Gi"},   # 96 vCPU, 384 GB
    "ml.g6.48xlarge": {"cpu": "96", "memory": "384Gi"},   # 192 vCPU, 768 GB
    # G6e instances (NVIDIA L40s GPU)
    "ml.g6e.xlarge": {"cpu": "2", "memory": "8Gi"},       # 4 vCPU, 16 GB
    "ml.g6e.2xlarge": {"cpu": "4", "memory": "16Gi"},     # 8 vCPU, 32 GB
    "ml.g6e.4xlarge": {"cpu": "8", "memory": "32Gi"},     # 16 vCPU, 64 GB
    "ml.g6e.8xlarge": {"cpu": "16", "memory": "64Gi"},    # 32 vCPU, 128 GB
    "ml.g6e.12xlarge": {"cpu": "24", "memory": "96Gi"},   # 48 vCPU, 192 GB
    "ml.g6e.16xlarge": {"cpu": "32", "memory": "128Gi"},  # 64 vCPU, 256 GB
    "ml.g6e.24xlarge": {"cpu": "48", "memory": "192Gi"},  # 96 vCPU, 384 GB
    "ml.g6e.48xlarge": {"cpu": "96", "memory": "384Gi"},  # 192 vCPU, 768 GB
    # P4d instances (NVIDIA A100 40GB GPU)
    "ml.p4d.24xlarge": {"cpu": "48", "memory": "576Gi"},  # 96 vCPU, 1152 GB
    "ml.p4de.24xlarge": {"cpu": "48", "memory": "576Gi"}, # 96 vCPU, 1152 GB
    # P5 instances (NVIDIA H100 GPU)
    "ml.p5.48xlarge": {"cpu": "96", "memory": "1024Gi"},  # 192 vCPU, 2048 GB
    "ml.p5e.48xlarge": {"cpu": "96", "memory": "1024Gi"}, # 192 vCPU, 2048 GB
    "ml.p5en.48xlarge": {"cpu": "96", "memory": "1024Gi"},# 192 vCPU, 2048 GB
}

# Default resources for unknown instance types (conservative values)
DEFAULT_RESOURCES = {"cpu": "8", "memory": "32Gi"}


def get_gpu_count(instance_type: str) -> int:
    """Get GPU count for an instance type."""
    return GPU_MAPPING.get(instance_type, 1)


def get_instance_resources(instance_type: str) -> Dict[str, str]:
    """
    Get CPU and memory resources for an instance type.

    Args:
        instance_type: AWS instance type (e.g., ml.g5.4xlarge)

    Returns:
        Dict with 'cpu' and 'memory' keys
    """
    return INSTANCE_RESOURCES.get(instance_type, DEFAULT_RESOURCES)


def get_per_replica_resources(
    instance_type: str,
    replicas: int = 1,
    instance_count: int = 1
) -> Dict[str, Any]:
    """
    Calculate per-replica resources based on replicas and instance count.

    When replicas > instance_count, resources are divided so multiple replicas
    can run on a single instance.

    Args:
        instance_type: AWS instance type (e.g., ml.g5.12xlarge)
        replicas: Number of deployment replicas
        instance_count: Number of available instances/nodes

    Returns:
        Dict with 'cpu', 'memory', 'gpu', and 'tensor_parallel_size' keys
    """
    base_resources = INSTANCE_RESOURCES.get(instance_type, DEFAULT_RESOURCES)
    base_gpu = GPU_MAPPING.get(instance_type, 1)

    # Calculate how many replicas need to fit on each instance
    replicas_per_instance = max(1, math.ceil(replicas / max(1, instance_count)))

    if replicas_per_instance > 1:
        # Divide resources among replicas on the same instance
        base_cpu = int(base_resources["cpu"])
        base_memory = int(base_resources["memory"].replace("Gi", ""))

        per_replica_cpu = max(1, base_cpu // replicas_per_instance)
        per_replica_memory = max(1, base_memory // replicas_per_instance)
        per_replica_gpu = max(1, base_gpu // replicas_per_instance)

        # Validate GPU division
        if base_gpu % replicas_per_instance != 0:
            logger.warning(
                f"GPU count ({base_gpu}) is not evenly divisible by replicas_per_instance ({replicas_per_instance}). "
                f"Each replica will get {per_replica_gpu} GPU(s). Consider adjusting replicas or instance_count."
            )

        logger.info(
            f"Resource allocation: {replicas} replicas on {instance_count} instance(s) = "
            f"{replicas_per_instance} replicas/instance. "
            f"Per replica: CPU={per_replica_cpu}, Memory={per_replica_memory}Gi, GPU={per_replica_gpu}"
        )

        return {
            "cpu": str(per_replica_cpu),
            "memory": f"{per_replica_memory}Gi",
            "gpu": per_replica_gpu,
            "tensor_parallel_size": per_replica_gpu,
            "replicas_per_instance": replicas_per_instance
        }
    else:
        # Each replica gets full instance resources
        return {
            "cpu": base_resources["cpu"],
            "memory": base_resources["memory"],
            "gpu": base_gpu,
            "tensor_parallel_size": base_gpu,
            "replicas_per_instance": 1
        }
