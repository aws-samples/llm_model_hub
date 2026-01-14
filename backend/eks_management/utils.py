"""
Utility functions for EKS management.
"""
import os
import logging
from typing import Dict, Set, Tuple, Optional

logger = logging.getLogger(__name__)


def get_occupied_nodes(eks_cluster_name: str) -> Tuple[Set[str], Dict[str, str]]:
    """
    Get nodes that are occupied by inference workloads in an EKS cluster.

    Args:
        eks_cluster_name: Name of the EKS cluster (used to find kubeconfig)

    Returns:
        Tuple of:
        - Set of occupied node names
        - Dict mapping node_name -> endpoint_name (occupied_by)
    """
    occupied_nodes: Set[str] = set()
    node_occupancy: Dict[str, str] = {}  # node_name -> occupied_by

    try:
        kubeconfig_path = os.path.expanduser(f'~/.kube/config-{eks_cluster_name}')
        if not os.path.exists(kubeconfig_path):
            logger.warning(f"Kubeconfig not found: {kubeconfig_path}")
            return occupied_nodes, node_occupancy

        from kubernetes import client, config
        config.load_kube_config(config_file=kubeconfig_path)
        core_api = client.CoreV1Api()

        # List all pods with hyperpod-inference label (actual label used by HyperPod)
        pods = core_api.list_pod_for_all_namespaces(
            label_selector='deploying-service=hyperpod-inference'
        )

        for pod in pods.items:
            if pod.spec.node_name and pod.status.phase in ['Running', 'Pending']:
                node_name = pod.spec.node_name
                occupied_nodes.add(node_name)
                # Get the app name (endpoint name) from labels
                app_name = pod.metadata.labels.get('app', 'unknown')
                node_occupancy[node_name] = app_name

        logger.info(f"Occupied nodes for cluster {eks_cluster_name}: {occupied_nodes}")

    except Exception as k8s_error:
        logger.warning(f"Failed to get k8s pod info: {k8s_error}")

    return occupied_nodes, node_occupancy


def get_kubeconfig_path(eks_cluster_name: str) -> Optional[str]:
    """
    Get the kubeconfig path for an EKS cluster.

    Args:
        eks_cluster_name: Name of the EKS cluster

    Returns:
        Path to kubeconfig file if it exists, None otherwise
    """
    kubeconfig_path = os.path.expanduser(f'~/.kube/config-{eks_cluster_name}')
    if os.path.exists(kubeconfig_path):
        return kubeconfig_path
    return None
