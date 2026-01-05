"""
HyperPod EKS Inference Management Module

Provides functions to deploy, delete, and monitor inference endpoints on HyperPod EKS clusters.
Supports deploying custom S3 models and HuggingFace models using the InferenceEndpointConfig CRD.

IMPORTANT: The HyperPod Inference Operator must be installed on the EKS cluster first.
See: https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-model-deployment-setup.html
"""

import os
import subprocess
import logging
import boto3
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import database for cluster info lookup
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables from .env
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(env_path)

# CRD Configuration for HyperPod Inference Operator
INFERENCE_API_GROUP = "inference.sagemaker.aws.amazon.com"
INFERENCE_API_VERSION = "v1"
INFERENCE_ENDPOINT_PLURAL = "inferenceendpointconfigs"
INFERENCE_ENDPOINT_KIND = "InferenceEndpointConfig"

# Get HyperPod inference container images from environment variables
HP_VLLM_IMAGE = os.getenv("hp_vllm_image", "763104351884.dkr.ecr.us-east-1.amazonaws.com/djl-inference:0.32.0-lmi14.0.0-cu124")
HP_SGLANG_IMAGE = os.getenv("hp_sglang_image", "763104351884.dkr.ecr.us-east-1.amazonaws.com/djl-inference:0.32.0-lmi14.0.0-cu124")

# HyperPod inference container images
DEFAULT_IMAGES = {
    "vllm": HP_VLLM_IMAGE,
    "sglang": HP_SGLANG_IMAGE,
}

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
    "ml.p4d.24xlarge": 8,
    "ml.p4de.24xlarge": 8,
    "ml.p5.48xlarge": 8,
    "ml.p5e.48xlarge": 8,
}

# Instance type resource mapping (cpu, memory in Gi)
# Values set to ~80% of instance capacity to leave room for system processes
INSTANCE_RESOURCES = {
    # G5 instances (NVIDIA A10G GPU)
    "ml.g5.xlarge": {"cpu": "3", "memory": "12Gi"},       # 4 vCPU, 16 GB
    "ml.g5.2xlarge": {"cpu": "6", "memory": "24Gi"},      # 8 vCPU, 32 GB
    "ml.g5.4xlarge": {"cpu": "12", "memory": "48Gi"},     # 16 vCPU, 64 GB
    "ml.g5.8xlarge": {"cpu": "24", "memory": "96Gi"},     # 32 vCPU, 128 GB
    "ml.g5.12xlarge": {"cpu": "36", "memory": "144Gi"},   # 48 vCPU, 192 GB
    "ml.g5.16xlarge": {"cpu": "48", "memory": "192Gi"},   # 64 vCPU, 256 GB
    "ml.g5.24xlarge": {"cpu": "72", "memory": "288Gi"},   # 96 vCPU, 384 GB
    "ml.g5.48xlarge": {"cpu": "144", "memory": "576Gi"},  # 192 vCPU, 768 GB
    # G6 instances (NVIDIA L4 GPU)
    "ml.g6.xlarge": {"cpu": "3", "memory": "12Gi"},       # 4 vCPU, 16 GB
    "ml.g6.2xlarge": {"cpu": "6", "memory": "24Gi"},      # 8 vCPU, 32 GB
    "ml.g6.4xlarge": {"cpu": "12", "memory": "48Gi"},     # 16 vCPU, 64 GB
    "ml.g6.8xlarge": {"cpu": "24", "memory": "96Gi"},     # 32 vCPU, 128 GB
    "ml.g6.12xlarge": {"cpu": "36", "memory": "144Gi"},   # 48 vCPU, 192 GB
    "ml.g6.16xlarge": {"cpu": "48", "memory": "192Gi"},   # 64 vCPU, 256 GB
    "ml.g6.24xlarge": {"cpu": "72", "memory": "288Gi"},   # 96 vCPU, 384 GB
    "ml.g6.48xlarge": {"cpu": "144", "memory": "576Gi"},  # 192 vCPU, 768 GB
    # P4d instances (NVIDIA A100 40GB GPU)
    "ml.p4d.24xlarge": {"cpu": "72", "memory": "864Gi"},  # 96 vCPU, 1152 GB
    "ml.p4de.24xlarge": {"cpu": "72", "memory": "864Gi"}, # 96 vCPU, 1152 GB
    # P5 instances (NVIDIA H100 GPU)
    "ml.p5.48xlarge": {"cpu": "144", "memory": "1536Gi"}, # 192 vCPU, 2048 GB
    "ml.p5e.48xlarge": {"cpu": "144", "memory": "1536Gi"},# 192 vCPU, 2048 GB
}

# Default resources for unknown instance types (conservative values)
DEFAULT_RESOURCES = {"cpu": "4", "memory": "16Gi"}


# ==============================================================================
# Data Classes for Advanced Configuration
# ==============================================================================

@dataclass
class AutoScalingConfig:
    """Auto-scaling configuration for HyperPod inference endpoints."""
    min_replicas: int = 1
    max_replicas: int = 10
    metric_name: str = "Invocations"
    target_value: int = 100
    metric_collection_period: int = 60
    cooldown_period: int = 300

    def to_spec(self, endpoint_name: str) -> Dict[str, Any]:
        """Convert to Kubernetes spec format."""
        return {
            "minReplicas": self.min_replicas,
            "maxReplicas": self.max_replicas,
            "pollingInterval": self.metric_collection_period,
            "cooldownPeriod": self.cooldown_period,
            "cloudWatchTrigger": {
                "name": "SageMaker-Invocations",
                "namespace": "AWS/SageMaker",
                "metricName": self.metric_name,
                "targetValue": self.target_value,
                "metricCollectionPeriod": self.metric_collection_period,
                "metricStat": "Sum",
                "dimensions": [
                    {"name": "EndpointName", "value": endpoint_name},
                    {"name": "VariantName", "value": "AllTraffic"}
                ]
            }
        }


@dataclass
class KVCacheConfig:
    """
    KV Cache configuration for optimized inference.

    Supports two-layer cache architecture:
    - L1 cache: Local CPU memory on each inference node
    - L2 cache: Distributed cache layer (redis or tieredstorage)
    """
    enable_l1_cache: bool = True
    enable_l2_cache: bool = False
    l2_cache_backend: str = "tieredstorage"  # tieredstorage (recommended) or redis
    l2_cache_url: Optional[str] = None

    def to_spec(self) -> Dict[str, Any]:
        """Convert to Kubernetes spec format."""
        spec: Dict[str, Any] = {
            "enableL1Cache": self.enable_l1_cache,
            "enableL2Cache": self.enable_l2_cache
        }
        if self.enable_l2_cache:
            l2_spec: Dict[str, str] = {
                "l2CacheBackend": self.l2_cache_backend
            }
            if self.l2_cache_backend == "redis" and self.l2_cache_url:
                l2_spec["l2CacheLocalUrl"] = self.l2_cache_url
            spec["l2CacheSpec"] = l2_spec
        return spec


@dataclass
class IntelligentRoutingConfig:
    """
    Intelligent routing configuration for optimized request distribution.

    Routing strategies:
    - prefixaware: Route based on prompt prefix (default)
    - kvaware: Real-time KV cache tracking for maximum cache hits
    - session: Route based on user session for multi-turn conversations
    - roundrobin: Simple round-robin distribution
    """
    enabled: bool = True
    routing_strategy: str = "prefixaware"

    def to_spec(self) -> Dict[str, Any]:
        """Convert to Kubernetes spec format."""
        return {
            "enabled": self.enabled,
            "routingStrategy": self.routing_strategy
        }


def get_kubeconfig_for_cluster(eks_cluster_name: str, region: str = None) -> str:
    """
    Generate kubeconfig for an EKS cluster and return the path.

    Args:
        eks_cluster_name: The EKS cluster name
        region: AWS region (uses default if not specified)

    Returns:
        Path to the kubeconfig file
    """
    if region is None:
        session = boto3.Session()
        region = session.region_name or 'us-west-2'

    # Create a temporary kubeconfig file
    kubeconfig_dir = os.path.expanduser("~/.kube")
    os.makedirs(kubeconfig_dir, exist_ok=True)
    kubeconfig_path = os.path.join(kubeconfig_dir, f"config-{eks_cluster_name}")

    # Generate kubeconfig using AWS CLI
    cmd = [
        "aws", "eks", "update-kubeconfig",
        "--name", eks_cluster_name,
        "--region", region,
        "--kubeconfig", kubeconfig_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            logger.error(f"Failed to generate kubeconfig: {result.stderr}")
            raise RuntimeError(f"Failed to generate kubeconfig for {eks_cluster_name}: {result.stderr}")
        logger.info(f"Generated kubeconfig at {kubeconfig_path}")
        return kubeconfig_path
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Timeout generating kubeconfig for {eks_cluster_name}")


def get_kubernetes_client(kubeconfig_path: str):
    """
    Get Kubernetes client with the specified kubeconfig.

    Args:
        kubeconfig_path: Path to kubeconfig file

    Returns:
        Tuple of (CustomObjectsApi, CoreV1Api)
    """
    from kubernetes import client, config
    config.load_kube_config(config_file=kubeconfig_path)
    return client.CustomObjectsApi(), client.CoreV1Api()


def _get_gpu_count(instance_type: str) -> int:
    """Get GPU count for an instance type"""
    return GPU_MAPPING.get(instance_type, 1)


def _get_instance_resources(instance_type: str) -> Dict[str, str]:
    """
    Get CPU and memory resources for an instance type.

    Args:
        instance_type: AWS instance type (e.g., ml.g5.4xlarge)

    Returns:
        Dict with 'cpu' and 'memory' keys
    """
    return INSTANCE_RESOURCES.get(instance_type, DEFAULT_RESOURCES)


def _parse_s3_path(s3_path: str) -> Tuple[str, str]:
    """
    Parse S3 path into bucket and key.

    Args:
        s3_path: S3 path like s3://bucket/path/to/model

    Returns:
        Tuple of (bucket_name, model_location)
    """
    if s3_path.startswith("s3://"):
        path = s3_path[5:]  # Remove "s3://"
    else:
        path = s3_path

    parts = path.split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""

    return bucket, key


def deploy_to_hyperpod(
    eks_cluster_name: str,
    endpoint_name: str,
    model_name: str,
    instance_type: str,
    engine: str = "vllm",
    replicas: int = 1,
    namespace: str = "default",
    region: str = None,
    model_s3_path: str = None,
    huggingface_model_id: str = None
) -> Dict[str, Any]:
    """
    Deploy a model to HyperPod EKS cluster using InferenceEndpointConfig CRD.

    IMPORTANT: Requires HyperPod Inference Operator to be installed on the cluster.
    See: https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-model-deployment-setup.html

    Args:
        eks_cluster_name: EKS cluster name for the HyperPod cluster
        endpoint_name: Name for the endpoint (also used as CRD resource name)
        model_name: Model name identifier
        instance_type: Instance type (e.g., ml.g5.xlarge)
        engine: Inference engine (vllm, sglang)
        replicas: Number of replicas
        namespace: Kubernetes namespace
        region: AWS region
        model_s3_path: S3 path to the model (s3://bucket/path) - optional
        huggingface_model_id: HuggingFace model ID (e.g., meta-llama/Llama-3-8B) - optional

    Returns:
        Dict with deployment result including status
    """
    from kubernetes.client.rest import ApiException

    if region is None:
        session = boto3.Session()
        region = session.region_name or 'us-west-2'

    # Get kubeconfig for the cluster
    kubeconfig_path = get_kubeconfig_for_cluster(eks_cluster_name, region)
    custom_api, _ = get_kubernetes_client(kubeconfig_path)

    # Get container image from environment
    image = DEFAULT_IMAGES.get(engine, DEFAULT_IMAGES["vllm"])

    # Determine model source
    if model_s3_path:
        # S3 model source
        s3_bucket, model_location = _parse_s3_path(model_s3_path)
        model_source_config = {
            "modelSourceType": "s3",
            "s3Storage": {
                "bucketName": s3_bucket,
                "region": region
            },
            "modelLocation": model_location,
            "prefetchEnabled": True
        }
        # For S3 models, use local path
        model_path_for_env = "/opt/ml/model"
        use_s3_model = True
    else:
        # HuggingFace model - use huggingface model source type
        # The HyperPod Inference Operator requires modelSourceConfig and modelVolumeMount
        # For HuggingFace models, we configure the model to be downloaded at runtime
        hf_model_id = huggingface_model_id or model_name
        model_source_config = {
            "modelSourceType": "huggingface",
            "huggingfaceHub": {
                "modelId": hf_model_id
            },
            "modelLocation": hf_model_id,
            "prefetchEnabled": True
        }
        model_path_for_env = "/opt/ml/model"
        use_s3_model = False

    # Build environment variables based on engine
    env_vars = []

    if engine == "vllm":
        env_vars = [
            {"name": "OPTION_ROLLING_BATCH", "value": "vllm"},
            {"name": "OPTION_TRUST_REMOTE_CODE", "value": "true"},
            {"name": "OPTION_MODEL_ID", "value": model_path_for_env},
        ]
    elif engine == "sglang":
        env_vars = [
            {"name": "OPTION_ROLLING_BATCH", "value": "scheduler"},
            {"name": "OPTION_TRUST_REMOTE_CODE", "value": "true"},
            {"name": "OPTION_MODEL_ID", "value": model_path_for_env},
        ]

    # Add HuggingFace token if available
    hf_token = os.getenv("HUGGING_FACE_HUB_TOKEN")
    if hf_token:
        env_vars.append({"name": "HUGGING_FACE_HUB_TOKEN", "value": hf_token})
        env_vars.append({"name": "HF_TOKEN", "value": hf_token})

    container_port = 8000  # vLLM/SGLang default port
    gpu_count = _get_gpu_count(instance_type)
    instance_resources = _get_instance_resources(instance_type)

    # Build the InferenceEndpointConfig resource
    resource_name = endpoint_name.lower().replace("_", "-")[:63]  # K8s name restrictions

    # Build worker spec
    worker_spec = {
        "image": image,
        "resources": {
            "limits": {
                "nvidia.com/gpu": str(gpu_count)
            },
            "requests": {
                "cpu": instance_resources["cpu"],
                "memory": instance_resources["memory"],
                "nvidia.com/gpu": str(gpu_count)
            }
        },
        "modelInvocationPort": {
            "containerPort": container_port,
            "name": "http"
        },
        "environmentVariables": env_vars
    }

    # Add model volume mount - required for all model sources
    worker_spec["modelVolumeMount"] = {
        "name": "model-weights",
        "mountPath": "/opt/ml/model"
    }

    # Build spec
    spec = {
        "modelName": model_name,
        "endpointName": endpoint_name,
        "instanceType": instance_type,
        "invocationEndpoint": "v1/chat/completions",  # Must be valid for intelligent routing
        "replicas": replicas,
        "worker": worker_spec,
        "modelSourceConfig": model_source_config  # Required for all deployments
    }

    body = {
        "apiVersion": f"{INFERENCE_API_GROUP}/{INFERENCE_API_VERSION}",
        "kind": INFERENCE_ENDPOINT_KIND,
        "metadata": {
            "name": resource_name,
            "namespace": namespace,
            "labels": {
                "modelhub.aws/endpoint-name": endpoint_name,
                "modelhub.aws/engine": engine,
                "modelhub.aws/model-source": "s3" if use_s3_model else "huggingface"
            }
        },
        "spec": spec
    }

    try:
        # Log the full CRD body for debugging
        import json
        logger.info(f"Creating InferenceEndpointConfig with body:\n{json.dumps(body, indent=2, default=str)}")

        custom_api.create_namespaced_custom_object(
            group=INFERENCE_API_GROUP,
            version=INFERENCE_API_VERSION,
            namespace=namespace,
            plural=INFERENCE_ENDPOINT_PLURAL,
            body=body
        )
        logger.info(f"Created InferenceEndpointConfig: {resource_name}")
        return {
            "success": True,
            "resource_name": resource_name,
            "namespace": namespace,
            "message": f"Deployment initiated for {endpoint_name}"
        }
    except ApiException as e:
        # Log detailed error information for debugging
        logger.error(f"Failed to create InferenceEndpointConfig: status={e.status}, reason={e.reason}")
        logger.error(f"API Exception body: {e.body}")
        logger.error(f"API Exception headers: {e.headers}")

        # Check if the CRD is not installed (404 Not Found)
        if e.status == 404:
            error_msg = (
                "HyperPod Inference Operator is not installed on this cluster. "
                "Please install the operator first using: "
                "helm install hyperpod-inference-operator charts/inference-operator ... "
                "See: https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-model-deployment-setup.html"
            )
            return {
                "success": False,
                "error": "CRD_NOT_FOUND",
                "message": error_msg,
                "eks_cluster_name": eks_cluster_name,
                "region": region
            }

        # Parse error body for more details (422 Unprocessable Entity)
        error_details = ""
        if e.status == 422:
            try:
                import json
                error_body = json.loads(e.body) if isinstance(e.body, str) else e.body
                error_details = f" Details: {error_body.get('message', '')} - {error_body.get('details', '')}"
                logger.error(f"422 Unprocessable Entity - Full error: {json.dumps(error_body, indent=2)}")
            except Exception:
                error_details = f" Raw body: {e.body}"

        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to deploy {endpoint_name}: {e.reason}{error_details}",
            "status_code": e.status
        }


def delete_hyperpod_endpoint(
    eks_cluster_name: str,
    endpoint_name: str,
    namespace: str = "default",
    region: str = None
) -> bool:
    """
    Delete a HyperPod inference endpoint.

    Args:
        eks_cluster_name: EKS cluster name
        endpoint_name: Name of the endpoint to delete
        namespace: Kubernetes namespace
        region: AWS region

    Returns:
        True if deleted successfully, False otherwise
    """
    from kubernetes.client.rest import ApiException

    if region is None:
        session = boto3.Session()
        region = session.region_name or 'us-west-2'

    kubeconfig_path = get_kubeconfig_for_cluster(eks_cluster_name, region)
    custom_api, _ = get_kubernetes_client(kubeconfig_path)

    resource_name = endpoint_name.lower().replace("_", "-")[:63]

    try:
        custom_api.delete_namespaced_custom_object(
            group=INFERENCE_API_GROUP,
            version=INFERENCE_API_VERSION,
            namespace=namespace,
            plural=INFERENCE_ENDPOINT_PLURAL,
            name=resource_name,
            grace_period_seconds=30
        )
        logger.info(f"Deleted InferenceEndpointConfig: {resource_name}")
        return True
    except ApiException as e:
        if e.status == 404:
            logger.warning(f"InferenceEndpointConfig not found: {resource_name}")
            return True  # Already deleted
        logger.error(f"Failed to delete InferenceEndpointConfig: {e}")
        return False


def get_hyperpod_endpoint_status(
    eks_cluster_name: str,
    endpoint_name: str,
    namespace: str = "default",
    region: str = None
) -> Tuple[str, Optional[str]]:
    """
    Get the status of a HyperPod inference endpoint.

    Args:
        eks_cluster_name: EKS cluster name
        endpoint_name: Name of the endpoint
        namespace: Kubernetes namespace
        region: AWS region

    Returns:
        Tuple of (status, error_message)
        Status can be: CREATING, INSERVICE, FAILED, NOTFOUND
    """
    from kubernetes.client.rest import ApiException

    if region is None:
        session = boto3.Session()
        region = session.region_name or 'us-west-2'

    try:
        kubeconfig_path = get_kubeconfig_for_cluster(eks_cluster_name, region)
        custom_api, _ = get_kubernetes_client(kubeconfig_path)
    except Exception as e:
        logger.error(f"Failed to connect to cluster: {e}")
        return "FAILED", f"Failed to connect to cluster: {e}"

    resource_name = endpoint_name.lower().replace("_", "-")[:63]

    try:
        resource = custom_api.get_namespaced_custom_object(
            group=INFERENCE_API_GROUP,
            version=INFERENCE_API_VERSION,
            namespace=namespace,
            plural=INFERENCE_ENDPOINT_PLURAL,
            name=resource_name
        )

        # Check status - the HyperPod InferenceEndpointConfig has a nested status structure
        status = resource.get("status", {})

        # Check overall state first
        state = status.get("state", "")
        deployment_status = status.get("deploymentStatus", {})
        deployment_state = deployment_status.get("deploymentObjectOverallState", "")

        # Log for debugging
        logger.debug(f"Endpoint {resource_name} - state: {state}, deploymentState: {deployment_state}")

        # Check if deployment is complete and available
        if deployment_state == "DeploymentComplete":
            # Verify the deployment is actually available
            nested_status = deployment_status.get("status", {})
            available_replicas = nested_status.get("availableReplicas", 0)
            ready_replicas = nested_status.get("readyReplicas", 0)

            if available_replicas > 0 and ready_replicas > 0:
                return "INSERVICE", None

            # Check conditions for more details
            conditions = nested_status.get("conditions", [])
            for condition in conditions:
                if condition.get("type") == "Available" and condition.get("status") == "True":
                    return "INSERVICE", None

        # Check for failure states
        if "fail" in state.lower() or "error" in state.lower():
            reason = deployment_status.get("reason", "Unknown")
            return "FAILED", f"{state}: {reason}"

        if deployment_state and "fail" in deployment_state.lower():
            reason = deployment_status.get("reason", "Unknown")
            return "FAILED", f"{deployment_state}: {reason}"

        # Check top-level conditions if present (for older CRD versions)
        conditions = status.get("conditions", [])
        for condition in conditions:
            if condition.get("type") == "Ready":
                if condition.get("status") == "True":
                    return "INSERVICE", None
                elif condition.get("status") == "False":
                    reason = condition.get("reason", "Unknown")
                    message = condition.get("message", "")
                    if "fail" in reason.lower() or "error" in message.lower():
                        return "FAILED", f"{reason}: {message}"

        # Still creating if no clear completion signal
        return "CREATING", None

    except ApiException as e:
        if e.status == 404:
            return "NOTFOUND", None
        logger.error(f"Failed to get endpoint status: {e}")
        return "FAILED", str(e)


def list_hyperpod_endpoints(
    eks_cluster_name: str,
    namespace: str = "default",
    region: str = None
) -> list:
    """
    List all HyperPod inference endpoints in a cluster.

    Args:
        eks_cluster_name: EKS cluster name
        namespace: Kubernetes namespace (empty string for all namespaces)
        region: AWS region

    Returns:
        List of endpoint info dicts
    """
    from kubernetes.client.rest import ApiException

    if region is None:
        session = boto3.Session()
        region = session.region_name or 'us-west-2'

    try:
        kubeconfig_path = get_kubeconfig_for_cluster(eks_cluster_name, region)
        custom_api, _ = get_kubernetes_client(kubeconfig_path)
    except Exception as e:
        logger.error(f"Failed to connect to cluster: {e}")
        return []

    try:
        if namespace:
            result = custom_api.list_namespaced_custom_object(
                group=INFERENCE_API_GROUP,
                version=INFERENCE_API_VERSION,
                namespace=namespace,
                plural=INFERENCE_ENDPOINT_PLURAL
            )
        else:
            result = custom_api.list_cluster_custom_object(
                group=INFERENCE_API_GROUP,
                version=INFERENCE_API_VERSION,
                plural=INFERENCE_ENDPOINT_PLURAL
            )

        endpoints = []
        for item in result.get("items", []):
            metadata = item.get("metadata", {})
            spec = item.get("spec", {})
            status = item.get("status", {})

            # Determine status from nested status structure
            endpoint_status = "CREATING"
            state = status.get("state", "")
            deployment_status = status.get("deploymentStatus", {})
            deployment_state = deployment_status.get("deploymentObjectOverallState", "")

            # Check if deployment is complete
            if deployment_state == "DeploymentComplete":
                nested_status = deployment_status.get("status", {})
                available_replicas = nested_status.get("availableReplicas", 0)
                ready_replicas = nested_status.get("readyReplicas", 0)
                if available_replicas > 0 and ready_replicas > 0:
                    endpoint_status = "INSERVICE"
                else:
                    # Check conditions
                    for cond in nested_status.get("conditions", []):
                        if cond.get("type") == "Available" and cond.get("status") == "True":
                            endpoint_status = "INSERVICE"
                            break

            # Check for failure states
            if "fail" in state.lower() or "error" in state.lower():
                endpoint_status = "FAILED"
            elif deployment_state and "fail" in deployment_state.lower():
                endpoint_status = "FAILED"
            else:
                # Fallback to top-level conditions for older CRD versions
                for cond in status.get("conditions", []):
                    if cond.get("type") == "Ready":
                        if cond.get("status") == "True":
                            endpoint_status = "INSERVICE"
                        elif cond.get("status") == "False" and "fail" in cond.get("reason", "").lower():
                            endpoint_status = "FAILED"

            endpoints.append({
                "name": metadata.get("name"),
                "endpoint_name": spec.get("endpointName"),
                "model_name": spec.get("modelName"),
                "instance_type": spec.get("instanceType"),
                "replicas": spec.get("replicas", 1),
                "status": endpoint_status,
                "namespace": metadata.get("namespace")
            })

        return endpoints

    except ApiException as e:
        logger.error(f"Failed to list endpoints: {e}")
        return []


def deploy_to_hyperpod_advanced(
    eks_cluster_name: str,
    endpoint_name: str,
    model_name: str,
    instance_type: str,
    engine: str = "vllm",
    replicas: int = 1,
    namespace: str = "default",
    region: str = None,
    model_s3_path: str = None,
    huggingface_model_id: str = None,
    # Advanced configuration
    autoscaling: Optional[AutoScalingConfig] = None,
    kv_cache: Optional[KVCacheConfig] = None,
    intelligent_routing: Optional[IntelligentRoutingConfig] = None,
    # Extra parameters
    extra_env_vars: Optional[Dict[str, str]] = None,
    tensor_parallel_size: Optional[int] = None,
    max_model_len: Optional[int] = None,
    enable_prefix_caching: bool = False
) -> Dict[str, Any]:
    """
    Deploy a model to HyperPod EKS cluster with advanced configuration options.

    This is an enhanced version of deploy_to_hyperpod that supports:
    - Auto-scaling based on CloudWatch metrics via KEDA
    - KV Cache configuration for optimized inference
    - Intelligent routing for request distribution

    Args:
        eks_cluster_name: EKS cluster name for the HyperPod cluster
        endpoint_name: Name for the endpoint
        model_name: Model name identifier
        instance_type: Instance type (e.g., ml.g5.xlarge)
        engine: Inference engine (vllm, sglang)
        replicas: Number of replicas (ignored if autoscaling is enabled)
        namespace: Kubernetes namespace
        region: AWS region
        model_s3_path: S3 path to the model (s3://bucket/path)
        huggingface_model_id: HuggingFace model ID
        autoscaling: Auto-scaling configuration
        kv_cache: KV Cache configuration
        intelligent_routing: Intelligent routing configuration
        extra_env_vars: Additional environment variables
        tensor_parallel_size: Tensor parallel size (auto-detected if not specified)
        max_model_len: Maximum model length
        enable_prefix_caching: Enable prefix caching (vllm only)

    Returns:
        Dict with deployment result including status
    """
    from kubernetes.client.rest import ApiException

    if region is None:
        session = boto3.Session()
        region = session.region_name or 'us-west-2'

    # Get kubeconfig for the cluster
    kubeconfig_path = get_kubeconfig_for_cluster(eks_cluster_name, region)
    custom_api, _ = get_kubernetes_client(kubeconfig_path)

    # Get container image from environment
    image = DEFAULT_IMAGES.get(engine, DEFAULT_IMAGES["vllm"])

    # Determine model source
    if model_s3_path:
        s3_bucket, model_location = _parse_s3_path(model_s3_path)
        model_source_config = {
            "modelSourceType": "s3",
            "s3Storage": {
                "bucketName": s3_bucket,
                "region": region
            },
            "modelLocation": model_location,
            "prefetchEnabled": True
        }
        model_path_for_env = "/opt/ml/model"
        use_s3_model = True
    else:
        # HuggingFace model - use huggingface model source type
        # The HyperPod Inference Operator requires modelSourceConfig and modelVolumeMount
        hf_model_id = huggingface_model_id or model_name
        model_source_config = {
            "modelSourceType": "huggingface",
            "huggingfaceHub": {
                "modelId": hf_model_id
            },
            "modelLocation": hf_model_id,
            "prefetchEnabled": True
        }
        model_path_for_env = "/opt/ml/model"
        use_s3_model = False

    # Build environment variables
    env_vars = []
    gpu_count = _get_gpu_count(instance_type)
    instance_resources = _get_instance_resources(instance_type)
    tp_size = tensor_parallel_size or gpu_count

    if engine == "vllm":
        env_vars = [
            {"name": "OPTION_ROLLING_BATCH", "value": "vllm"},
            {"name": "OPTION_TRUST_REMOTE_CODE", "value": "true"},
            {"name": "OPTION_MODEL_ID", "value": model_path_for_env},
            {"name": "TENSOR_PARALLEL_SIZE", "value": str(tp_size)},
        ]
        if max_model_len:
            env_vars.append({"name": "MAX_MODEL_LEN", "value": str(max_model_len)})
        if enable_prefix_caching:
            env_vars.append({"name": "ENABLE_PREFIX_CACHING", "value": "1"})
    elif engine == "sglang":
        env_vars = [
            {"name": "OPTION_ROLLING_BATCH", "value": "scheduler"},
            {"name": "OPTION_TRUST_REMOTE_CODE", "value": "true"},
            {"name": "OPTION_MODEL_ID", "value": model_path_for_env},
            {"name": "TENSOR_PARALLEL_SIZE", "value": str(tp_size)},
        ]

    # Add HuggingFace token if available
    hf_token = os.getenv("HUGGING_FACE_HUB_TOKEN")
    if hf_token:
        env_vars.append({"name": "HUGGING_FACE_HUB_TOKEN", "value": hf_token})
        env_vars.append({"name": "HF_TOKEN", "value": hf_token})

    # Add extra environment variables
    if extra_env_vars:
        for key, value in extra_env_vars.items():
            env_vars.append({"name": key, "value": str(value)})

    container_port = 8000  # vLLM/SGLang default port
    resource_name = endpoint_name.lower().replace("_", "-")[:63]

    # Build worker spec with instance-appropriate resources
    worker_spec = {
        "image": image,
        "resources": {
            "limits": {
                "nvidia.com/gpu": str(gpu_count)
            },
            "requests": {
                "cpu": instance_resources["cpu"],
                "memory": instance_resources["memory"],
                "nvidia.com/gpu": str(gpu_count)
            }
        },
        "modelInvocationPort": {
            "containerPort": container_port,
            "name": "http"
        },
        "environmentVariables": env_vars
    }

    # Add model volume mount - required for all model sources
    worker_spec["modelVolumeMount"] = {
        "name": "model-weights",
        "mountPath": "/opt/ml/model"
    }

    # Build spec
    spec = {
        "modelName": model_name,
        "endpointName": endpoint_name,
        "instanceType": instance_type,
        "invocationEndpoint": "v1/chat/completions",  # Must be valid for intelligent routing
        "replicas": replicas,
        "worker": worker_spec,
        "modelSourceConfig": model_source_config  # Required for all deployments
    }

    # Add advanced configuration
    if autoscaling:
        spec["autoScalingSpec"] = autoscaling.to_spec(endpoint_name)

    if kv_cache:
        spec["kvCacheSpec"] = kv_cache.to_spec()

    if intelligent_routing:
        spec["intelligentRoutingSpec"] = intelligent_routing.to_spec()

    body = {
        "apiVersion": f"{INFERENCE_API_GROUP}/{INFERENCE_API_VERSION}",
        "kind": INFERENCE_ENDPOINT_KIND,
        "metadata": {
            "name": resource_name,
            "namespace": namespace,
            "labels": {
                "modelhub.aws/endpoint-name": endpoint_name,
                "modelhub.aws/engine": engine,
                "modelhub.aws/model-source": "s3" if use_s3_model else "huggingface"
            }
        },
        "spec": spec
    }

    try:
        # Log the full CRD body for debugging
        import json
        logger.info(f"Creating InferenceEndpointConfig (advanced) with body:\n{json.dumps(body, indent=2, default=str)}")

        custom_api.create_namespaced_custom_object(
            group=INFERENCE_API_GROUP,
            version=INFERENCE_API_VERSION,
            namespace=namespace,
            plural=INFERENCE_ENDPOINT_PLURAL,
            body=body
        )
        logger.info(f"Created InferenceEndpointConfig with advanced config: {resource_name}")
        return {
            "success": True,
            "resource_name": resource_name,
            "namespace": namespace,
            "message": f"Deployment initiated for {endpoint_name}",
            "features": {
                "autoscaling": autoscaling is not None,
                "kv_cache": kv_cache is not None,
                "intelligent_routing": intelligent_routing is not None
            }
        }
    except ApiException as e:
        # Log detailed error information for debugging
        logger.error(f"Failed to create InferenceEndpointConfig (advanced): status={e.status}, reason={e.reason}")
        logger.error(f"API Exception body: {e.body}")
        logger.error(f"API Exception headers: {e.headers}")

        if e.status == 404:
            return {
                "success": False,
                "error": "CRD_NOT_FOUND",
                "message": "HyperPod Inference Operator is not installed on this cluster.",
                "eks_cluster_name": eks_cluster_name,
                "region": region
            }

        # Parse error body for more details (422 Unprocessable Entity)
        error_details = ""
        if e.status == 422:
            try:
                import json
                error_body = json.loads(e.body) if isinstance(e.body, str) else e.body
                error_details = f" Details: {error_body.get('message', '')} - {error_body.get('details', '')}"
                logger.error(f"422 Unprocessable Entity - Full error: {json.dumps(error_body, indent=2)}")
            except Exception:
                error_details = f" Raw body: {e.body}"

        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to deploy {endpoint_name}: {e.reason}{error_details}",
            "status_code": e.status
        }


def scale_hyperpod_endpoint(
    eks_cluster_name: str,
    endpoint_name: str,
    replicas: int,
    namespace: str = "default",
    region: str = None
) -> Dict[str, Any]:
    """
    Scale a HyperPod inference endpoint to the specified number of replicas.

    Args:
        eks_cluster_name: EKS cluster name
        endpoint_name: Name of the endpoint to scale
        replicas: Target number of replicas
        namespace: Kubernetes namespace
        region: AWS region

    Returns:
        Dict with scale result
    """
    from kubernetes.client.rest import ApiException

    if region is None:
        session = boto3.Session()
        region = session.region_name or 'us-west-2'

    kubeconfig_path = get_kubeconfig_for_cluster(eks_cluster_name, region)
    custom_api, _ = get_kubernetes_client(kubeconfig_path)

    resource_name = endpoint_name.lower().replace("_", "-")[:63]

    try:
        # Patch the replicas field
        patch = {"spec": {"replicas": replicas}}
        custom_api.patch_namespaced_custom_object(
            group=INFERENCE_API_GROUP,
            version=INFERENCE_API_VERSION,
            namespace=namespace,
            plural=INFERENCE_ENDPOINT_PLURAL,
            name=resource_name,
            body=patch
        )
        logger.info(f"Scaled endpoint {resource_name} to {replicas} replicas")
        return {
            "success": True,
            "resource_name": resource_name,
            "replicas": replicas,
            "message": f"Scaled {endpoint_name} to {replicas} replicas"
        }
    except ApiException as e:
        logger.error(f"Failed to scale endpoint: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to scale {endpoint_name}: {e.reason}"
        }


def get_hyperpod_endpoint_details(
    eks_cluster_name: str,
    endpoint_name: str,
    namespace: str = "default",
    region: str = None
) -> Optional[Dict[str, Any]]:
    """
    Get detailed information about a HyperPod inference endpoint.

    Args:
        eks_cluster_name: EKS cluster name
        endpoint_name: Name of the endpoint
        namespace: Kubernetes namespace
        region: AWS region

    Returns:
        Dict with endpoint details or None if not found
    """
    from kubernetes.client.rest import ApiException

    if region is None:
        session = boto3.Session()
        region = session.region_name or 'us-west-2'

    try:
        kubeconfig_path = get_kubeconfig_for_cluster(eks_cluster_name, region)
        custom_api, core_api = get_kubernetes_client(kubeconfig_path)
    except Exception as e:
        logger.error(f"Failed to connect to cluster: {e}")
        return None

    resource_name = endpoint_name.lower().replace("_", "-")[:63]

    try:
        resource = custom_api.get_namespaced_custom_object(
            group=INFERENCE_API_GROUP,
            version=INFERENCE_API_VERSION,
            namespace=namespace,
            plural=INFERENCE_ENDPOINT_PLURAL,
            name=resource_name
        )

        metadata = resource.get("metadata", {})
        spec = resource.get("spec", {})
        status = resource.get("status", {})

        # Determine status from conditions
        endpoint_status = "CREATING"
        status_message = None
        for cond in status.get("conditions", []):
            if cond.get("type") == "Ready":
                if cond.get("status") == "True":
                    endpoint_status = "INSERVICE"
                elif cond.get("status") == "False":
                    reason = cond.get("reason", "")
                    if "fail" in reason.lower():
                        endpoint_status = "FAILED"
                    status_message = cond.get("message")

        # Get pods for this endpoint
        pods = []
        try:
            pod_list = core_api.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"app={resource_name}"
            )
            for pod in pod_list.items:
                pods.append({
                    "name": pod.metadata.name,
                    "phase": pod.status.phase,
                    "ready": all(c.ready for c in (pod.status.container_statuses or []))
                })
        except Exception as e:
            logger.warning(f"Failed to get pods: {e}")

        return {
            "name": metadata.get("name"),
            "namespace": metadata.get("namespace"),
            "endpoint_name": spec.get("endpointName"),
            "model_name": spec.get("modelName"),
            "instance_type": spec.get("instanceType"),
            "replicas": spec.get("replicas", 1),
            "status": endpoint_status,
            "status_message": status_message,
            "invocation_endpoint": spec.get("invocationEndpoint"),
            "creation_timestamp": metadata.get("creationTimestamp"),
            "pods": pods,
            "autoscaling_enabled": "autoScalingSpec" in spec,
            "kv_cache_enabled": "kvCacheSpec" in spec,
            "intelligent_routing_enabled": "intelligentRoutingSpec" in spec
        }

    except ApiException as e:
        if e.status == 404:
            return None
        logger.error(f"Failed to get endpoint details: {e}")
        return None


def get_hyperpod_endpoint_url(
    eks_cluster_name: str,
    endpoint_name: str,
    namespace: str = "default",
    region: str = None,
    override_url: str = None
) -> Optional[Dict[str, Any]]:
    """
    Get the HyperPod endpoint URL and invocation path from the InferenceEndpointConfig CRD.

    Args:
        eks_cluster_name: EKS cluster name
        endpoint_name: Name of the endpoint
        namespace: Kubernetes namespace
        region: AWS region
        override_url: Optional URL override (for when ALB is not directly accessible)

    Returns:
        Dict with endpoint_url, invocation_path, and use_https, or None if not found
    """
    from kubernetes.client.rest import ApiException

    # Check for environment variable override first
    env_override = os.environ.get('HYPERPOD_ENDPOINT_URL_OVERRIDE')
    if env_override:
        logger.info(f"Using HYPERPOD_ENDPOINT_URL_OVERRIDE: {env_override}")
        return {
            "endpoint_url": env_override.replace("https://", "").replace("http://", "").split("/")[0],
            "invocation_path": "invocations",
            "use_https": env_override.startswith("https"),
            "full_url": env_override if "/invocations" in env_override else f"{env_override}/invocations"
        }

    if override_url:
        logger.info(f"Using override URL: {override_url}")
        return {
            "endpoint_url": override_url.replace("https://", "").replace("http://", "").split("/")[0],
            "invocation_path": "invocations",
            "use_https": override_url.startswith("https"),
            "full_url": override_url if "/invocations" in override_url else f"{override_url}/invocations"
        }

    if region is None:
        session = boto3.Session()
        region = session.region_name or 'us-west-2'

    try:
        kubeconfig_path = get_kubeconfig_for_cluster(eks_cluster_name, region)
        custom_api, _ = get_kubernetes_client(kubeconfig_path)
    except Exception as e:
        logger.error(f"Failed to connect to cluster: {e}")
        return None

    resource_name = endpoint_name.lower().replace("_", "-")[:63]

    try:
        resource = custom_api.get_namespaced_custom_object(
            group=INFERENCE_API_GROUP,
            version=INFERENCE_API_VERSION,
            namespace=namespace,
            plural=INFERENCE_ENDPOINT_PLURAL,
            name=resource_name
        )

        spec = resource.get("spec", {})
        status = resource.get("status", {})

        # Get the invocation endpoint path from spec
        invocation_path = spec.get("invocationEndpoint", "v1/chat/completions")

        # Get the ALB URL from the TLS certificate status
        tls_status = status.get("tlsCertificate", {})
        domain_names = tls_status.get("certificateDomainNames", [])

        # Also check the Ingress directly for the ALB hostname
        # This is important because when we recreate the Ingress with internet-facing scheme,
        # the CRD status doesn't get updated automatically
        try:
            from kubernetes import client, config
            config.load_kube_config(config_file=kubeconfig_path)
            networking_api = client.NetworkingV1Api()

            # HyperPod creates Ingress in hyperpod-inference-system namespace
            ingress_namespace = "hyperpod-inference-system"
            ingress_name = f"alb-{resource_name}-{namespace}"

            ingress = networking_api.read_namespaced_ingress(name=ingress_name, namespace=ingress_namespace)
            if ingress.status.load_balancer and ingress.status.load_balancer.ingress:
                ingress_hostname = ingress.status.load_balancer.ingress[0].hostname
                if ingress_hostname:
                    # Prefer the Ingress hostname - it will have the updated ALB URL after recreation
                    logger.info(f"Using Ingress hostname: {ingress_hostname}")
                    endpoint_url = ingress_hostname
                    use_https = True  # ALB with HTTPS listener
                    return {
                        "endpoint_url": endpoint_url,
                        "invocation_path": invocation_path,
                        "use_https": use_https,
                        "full_url": f"https://{endpoint_url}/{invocation_path}"
                    }
        except Exception as e:
            logger.debug(f"Could not get Ingress hostname: {e}")

        if domain_names:
            # Use the first domain name as the endpoint URL
            endpoint_url = domain_names[0]
            use_https = True  # TLS certificate means HTTPS
        else:
            # Fallback: try to get from service/ingress
            # This is a simplified approach - in production, you might need to
            # get the service ClusterIP or LoadBalancer IP
            logger.warning(f"No TLS domain names found for {endpoint_name}, endpoint may not be accessible")
            return None

        return {
            "endpoint_url": endpoint_url,
            "invocation_path": invocation_path,
            "use_https": use_https,
            "full_url": f"https://{endpoint_url}/{invocation_path}" if use_https else f"http://{endpoint_url}/{invocation_path}"
        }

    except ApiException as e:
        if e.status == 404:
            logger.warning(f"Endpoint {endpoint_name} not found")
            return None
        logger.error(f"Failed to get endpoint URL: {e}")
        return None


def invoke_hyperpod_endpoint(
    eks_cluster_name: str,
    endpoint_name: str,
    payload: Dict[str, Any],
    namespace: str = "default",
    region: str = None,
    stream: bool = False,
    timeout: int = 120
) -> Dict[str, Any]:
    """
    Invoke a HyperPod inference endpoint via HTTP.

    Args:
        eks_cluster_name: EKS cluster name
        endpoint_name: Name of the endpoint
        payload: Request payload (OpenAI-compatible format)
        namespace: Kubernetes namespace
        region: AWS region
        stream: Whether to use streaming response
        timeout: Request timeout in seconds

    Returns:
        Response from the endpoint
    """
    import requests
    import urllib3

    # Disable SSL warnings for internal ALB with self-signed cert
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Get endpoint URL
    url_info = get_hyperpod_endpoint_url(
        eks_cluster_name=eks_cluster_name,
        endpoint_name=endpoint_name,
        namespace=namespace,
        region=region
    )

    if not url_info:
        raise ValueError(f"Could not get URL for endpoint {endpoint_name}")

    full_url = url_info["full_url"]
    logger.info(f"Invoking HyperPod endpoint at {full_url}")

    headers = {
        "Content-Type": "application/json"
    }

    try:
        if stream:
            # Streaming response
            response = requests.post(
                full_url,
                json=payload,
                headers=headers,
                stream=True,
                verify=False,  # Self-signed cert
                timeout=timeout
            )
            response.raise_for_status()
            return response  # Return the response object for streaming
        else:
            # Non-streaming response
            response = requests.post(
                full_url,
                json=payload,
                headers=headers,
                verify=False,  # Self-signed cert
                timeout=timeout
            )
            response.raise_for_status()
            return response.json()

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to invoke HyperPod endpoint: {e}")
        raise


def invoke_hyperpod_endpoint_stream(
    eks_cluster_name: str,
    endpoint_name: str,
    payload: Dict[str, Any],
    namespace: str = "default",
    region: str = None,
    timeout: int = 120
):
    """
    Invoke a HyperPod inference endpoint with streaming response.

    Yields:
        Chunks of the streaming response
    """
    import requests
    import urllib3

    # Disable SSL warnings for internal ALB with self-signed cert
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Get endpoint URL
    url_info = get_hyperpod_endpoint_url(
        eks_cluster_name=eks_cluster_name,
        endpoint_name=endpoint_name,
        namespace=namespace,
        region=region
    )

    if not url_info:
        raise ValueError(f"Could not get URL for endpoint {endpoint_name}")

    full_url = url_info["full_url"]
    logger.info(f"Invoking HyperPod endpoint (streaming) at {full_url}")

    headers = {
        "Content-Type": "application/json"
    }

    # Ensure stream is enabled in payload
    payload["stream"] = True

    try:
        response = requests.post(
            full_url,
            json=payload,
            headers=headers,
            stream=True,
            verify=False,  # Self-signed cert
            timeout=timeout
        )
        response.raise_for_status()

        for line in response.iter_lines():
            if line:
                yield line.decode('utf-8')

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to invoke HyperPod endpoint (streaming): {e}")
        raise


def configure_alb_scheme(
    eks_cluster_name: str,
    endpoint_name: str,
    namespace: str = "default",
    region: str = None,
    internet_facing: bool = True
) -> Dict[str, Any]:
    """
    Configure the ALB scheme for a HyperPod inference endpoint.

    This patches the Ingress resource to change the ALB scheme from internal to internet-facing
    or vice versa. Note: Changing the scheme requires recreating the ALB.

    Args:
        eks_cluster_name: EKS cluster name
        endpoint_name: Name of the endpoint
        namespace: Kubernetes namespace
        region: AWS region
        internet_facing: True for internet-facing, False for internal

    Returns:
        Dict with result including status and ALB URL
    """
    from kubernetes.client.rest import ApiException
    from kubernetes import client, config

    if region is None:
        session = boto3.Session()
        region = session.region_name or 'us-west-2'

    try:
        kubeconfig_path = get_kubeconfig_for_cluster(eks_cluster_name, region)
        config.load_kube_config(config_file=kubeconfig_path)
        networking_api = client.NetworkingV1Api()
    except Exception as e:
        logger.error(f"Failed to connect to cluster: {e}")
        return {"success": False, "error": str(e)}

    resource_name = endpoint_name.lower().replace("_", "-")[:63]
    ingress_name = f"alb-{resource_name}"
    scheme = "internet-facing" if internet_facing else "internal"

    try:
        # Get existing ingress
        ingress = networking_api.read_namespaced_ingress(name=ingress_name, namespace=namespace)

        # Patch the annotation
        patch = {
            "metadata": {
                "annotations": {
                    "alb.ingress.kubernetes.io/scheme": scheme
                }
            }
        }

        networking_api.patch_namespaced_ingress(
            name=ingress_name,
            namespace=namespace,
            body=patch
        )

        logger.info(f"Patched Ingress {ingress_name} scheme to {scheme}")

        # Wait for ALB to be updated
        import time
        time.sleep(10)

        # Get updated ingress to get new ALB URL
        updated_ingress = networking_api.read_namespaced_ingress(name=ingress_name, namespace=namespace)
        alb_hostname = None
        if updated_ingress.status.load_balancer and updated_ingress.status.load_balancer.ingress:
            alb_hostname = updated_ingress.status.load_balancer.ingress[0].hostname

        return {
            "success": True,
            "scheme": scheme,
            "ingress_name": ingress_name,
            "alb_hostname": alb_hostname,
            "message": f"ALB scheme changed to {scheme}. Note: ALB recreation may take a few minutes."
        }

    except ApiException as e:
        if e.status == 404:
            return {"success": False, "error": f"Ingress {ingress_name} not found"}
        logger.error(f"Failed to patch Ingress: {e}")
        return {"success": False, "error": str(e)}


def recreate_ingress_with_scheme(
    eks_cluster_name: str,
    endpoint_name: str,
    namespace: str = "default",
    region: str = None,
    internet_facing: bool = True,
    wait_for_cleanup: int = 60
) -> Dict[str, Any]:
    """
    Recreate Ingress with the correct ALB scheme.

    This function deletes the existing Ingress and recreates it with the correct
    scheme annotation. This is necessary because AWS ALB target groups cannot
    be associated with multiple load balancers.

    Note: HyperPod Operator creates Ingress in 'hyperpod-inference-system' namespace
    with name pattern: alb-{resource_name}-{original_namespace}

    Args:
        eks_cluster_name: EKS cluster name
        endpoint_name: Name of the endpoint
        namespace: Original Kubernetes namespace where InferenceEndpointConfig was created
        region: AWS region
        internet_facing: True for internet-facing, False for internal
        wait_for_cleanup: Seconds to wait for ALB cleanup before recreating

    Returns:
        Dict with result including status and ALB URL
    """
    from kubernetes.client.rest import ApiException
    from kubernetes import client, config
    import time as time_module
    import copy

    if region is None:
        session = boto3.Session()
        region = session.region_name or 'us-west-2'

    try:
        kubeconfig_path = get_kubeconfig_for_cluster(eks_cluster_name, region)
        config.load_kube_config(config_file=kubeconfig_path)
        networking_api = client.NetworkingV1Api()
    except Exception as e:
        logger.error(f"Failed to connect to cluster: {e}")
        return {"success": False, "error": str(e)}

    # HyperPod Operator creates Ingress in 'hyperpod-inference-system' namespace
    # with name pattern: alb-{resource_name}-{original_namespace}
    ingress_namespace = "hyperpod-inference-system"
    resource_name = endpoint_name.lower().replace("_", "-")[:63]
    ingress_name = f"alb-{resource_name}-{namespace}"
    scheme = "internet-facing" if internet_facing else "internal"

    logger.info(f"Looking for Ingress {ingress_name} in namespace {ingress_namespace}...")

    try:
        # Get existing ingress to preserve its spec
        logger.info(f"Getting existing Ingress {ingress_name} in namespace {ingress_namespace}...")
        existing_ingress = networking_api.read_namespaced_ingress(name=ingress_name, namespace=ingress_namespace)

        # Check if already has the correct scheme
        current_scheme = existing_ingress.metadata.annotations.get("alb.ingress.kubernetes.io/scheme", "internal")
        if current_scheme == scheme:
            logger.info(f"Ingress {ingress_name} already has scheme {scheme}")
            alb_hostname = ""
            if existing_ingress.status.load_balancer and existing_ingress.status.load_balancer.ingress:
                alb_hostname = existing_ingress.status.load_balancer.ingress[0].hostname
            return {
                "success": True,
                "alb_hostname": alb_hostname,
                "message": f"Ingress already configured as {scheme}"
            }

        # Copy the spec and annotations for recreation
        new_annotations = copy.deepcopy(existing_ingress.metadata.annotations) or {}
        new_annotations["alb.ingress.kubernetes.io/scheme"] = scheme

        ingress_spec = existing_ingress.spec

        # Delete the existing Ingress
        logger.info(f"Deleting existing Ingress {ingress_name} in {ingress_namespace} to recreate with {scheme} scheme...")
        networking_api.delete_namespaced_ingress(name=ingress_name, namespace=ingress_namespace)

        # Wait for the ALB and target group to be cleaned up
        logger.info(f"Waiting {wait_for_cleanup}s for ALB cleanup...")
        time_module.sleep(wait_for_cleanup)

        # Recreate the Ingress with the correct scheme
        new_ingress = client.V1Ingress(
            api_version="networking.k8s.io/v1",
            kind="Ingress",
            metadata=client.V1ObjectMeta(
                name=ingress_name,
                namespace=ingress_namespace,
                annotations=new_annotations,
                labels=existing_ingress.metadata.labels
            ),
            spec=ingress_spec
        )

        logger.info(f"Creating new Ingress {ingress_name} in {ingress_namespace} with {scheme} scheme...")
        networking_api.create_namespaced_ingress(namespace=ingress_namespace, body=new_ingress)

        # Wait for the new ALB to be provisioned
        logger.info(f"Waiting for new ALB to be provisioned...")
        alb_hostname = ""
        for i in range(30):  # Wait up to 5 minutes
            time_module.sleep(10)
            try:
                updated_ingress = networking_api.read_namespaced_ingress(name=ingress_name, namespace=ingress_namespace)
                if updated_ingress.status.load_balancer and updated_ingress.status.load_balancer.ingress:
                    alb_hostname = updated_ingress.status.load_balancer.ingress[0].hostname
                    if alb_hostname and "internal" not in alb_hostname.lower() if internet_facing else "internal" in alb_hostname.lower():
                        logger.info(f"New ALB provisioned: {alb_hostname}")
                        break
            except Exception:
                pass

        return {
            "success": True,
            "alb_hostname": alb_hostname,
            "ingress_name": ingress_name,
            "namespace": ingress_namespace,
            "scheme": scheme,
            "message": f"Ingress recreated with {scheme} scheme"
        }

    except ApiException as e:
        if e.status == 404:
            return {"success": False, "error": f"Ingress {ingress_name} not found in namespace {ingress_namespace}"}
        logger.error(f"Failed to recreate Ingress: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"Failed to recreate Ingress: {e}")
        return {"success": False, "error": str(e)}


def deploy_to_hyperpod_with_public_alb(
    eks_cluster_name: str,
    endpoint_name: str,
    model_name: str,
    instance_type: str,
    engine: str = "vllm",
    replicas: int = 1,
    namespace: str = "default",
    region: str = None,
    model_s3_path: str = None,
    huggingface_model_id: str = None,
    use_public_alb: bool = False
) -> Dict[str, Any]:
    """
    Deploy a model to HyperPod EKS cluster with optional public ALB.

    This is a wrapper around deploy_to_hyperpod that optionally configures the ALB
    to be internet-facing after deployment.

    Args:
        eks_cluster_name: EKS cluster name for the HyperPod cluster
        endpoint_name: Name for the endpoint
        model_name: Model name identifier
        instance_type: Instance type (e.g., ml.g5.xlarge)
        engine: Inference engine (vllm, sglang)
        replicas: Number of replicas
        namespace: Kubernetes namespace
        region: AWS region
        model_s3_path: S3 path to the model (s3://bucket/path)
        huggingface_model_id: HuggingFace model ID
        use_public_alb: If True, configure ALB to be internet-facing

    Returns:
        Dict with deployment result including status
    """
    # First, deploy normally
    result = deploy_to_hyperpod(
        eks_cluster_name=eks_cluster_name,
        endpoint_name=endpoint_name,
        model_name=model_name,
        instance_type=instance_type,
        engine=engine,
        replicas=replicas,
        namespace=namespace,
        region=region,
        model_s3_path=model_s3_path,
        huggingface_model_id=huggingface_model_id
    )

    if not result.get('success'):
        return result

    # If public ALB is requested, patch the Ingress
    if use_public_alb:
        logger.info(f"Configuring ALB as internet-facing for {endpoint_name}")
        # Wait a few seconds for the Ingress to be created
        import time
        time.sleep(5)

        alb_result = configure_alb_scheme(
            eks_cluster_name=eks_cluster_name,
            endpoint_name=endpoint_name,
            namespace=namespace,
            region=region,
            internet_facing=True
        )

        if alb_result.get('success'):
            result['alb_scheme'] = 'internet-facing'
            result['alb_hostname'] = alb_result.get('alb_hostname')
            result['message'] = f"{result['message']}. ALB configured as internet-facing."
        else:
            # Don't fail the deployment, just log the warning
            logger.warning(f"Failed to configure public ALB: {alb_result.get('error')}")
            result['alb_scheme'] = 'internal'
            result['alb_warning'] = alb_result.get('error')

    return result


def precreate_public_ingress(
    eks_cluster_name: str,
    endpoint_name: str,
    namespace: str = "default",
    region: str = None,
    container_port: int = 8000
) -> Dict[str, Any]:
    """
    Pre-create an internet-facing Ingress BEFORE creating InferenceEndpointConfig.

    This allows the ALB to be created as internet-facing from the start,
    avoiding the need to recreate it later (which is slow and error-prone).

    The HyperPod operator will create a Service that this Ingress will route to.
    The Service name follows the pattern: {resource_name}

    Args:
        eks_cluster_name: EKS cluster name
        endpoint_name: Name of the endpoint
        namespace: Kubernetes namespace
        region: AWS region
        container_port: Container port (default 8000 for vLLM/SGLang)

    Returns:
        Dict with result including success status
    """
    from kubernetes.client.rest import ApiException
    from kubernetes import client, config

    if region is None:
        session = boto3.Session()
        region = session.region_name or 'us-west-2'

    try:
        kubeconfig_path = get_kubeconfig_for_cluster(eks_cluster_name, region)
        config.load_kube_config(config_file=kubeconfig_path)
        networking_api = client.NetworkingV1Api()
    except Exception as e:
        logger.error(f"Failed to connect to cluster: {e}")
        return {"success": False, "error": str(e)}

    resource_name = endpoint_name.lower().replace("_", "-")[:63]
    ingress_name = f"alb-{resource_name}"
    service_name = resource_name  # HyperPod operator creates service with this name

    # Check if Ingress already exists
    try:
        existing = networking_api.read_namespaced_ingress(name=ingress_name, namespace=namespace)
        logger.info(f"Ingress {ingress_name} already exists, checking scheme...")
        current_scheme = existing.metadata.annotations.get("alb.ingress.kubernetes.io/scheme", "internal")
        if current_scheme == "internet-facing":
            logger.info(f"Ingress {ingress_name} already has internet-facing scheme")
            return {"success": True, "message": "Ingress already exists with correct scheme"}
        else:
            # Delete and recreate with correct scheme
            logger.info(f"Deleting existing internal Ingress {ingress_name}...")
            networking_api.delete_namespaced_ingress(name=ingress_name, namespace=namespace)
            import time
            time.sleep(5)  # Brief wait for deletion
    except ApiException as e:
        if e.status != 404:
            logger.error(f"Error checking existing Ingress: {e}")
            return {"success": False, "error": str(e)}
        # 404 means Ingress doesn't exist, which is expected

    # Create internet-facing Ingress
    ingress = client.V1Ingress(
        api_version="networking.k8s.io/v1",
        kind="Ingress",
        metadata=client.V1ObjectMeta(
            name=ingress_name,
            namespace=namespace,
            annotations={
                "kubernetes.io/ingress.class": "alb",
                "alb.ingress.kubernetes.io/scheme": "internet-facing",
                "alb.ingress.kubernetes.io/target-type": "ip",
                "alb.ingress.kubernetes.io/healthcheck-path": "/ping",
                "alb.ingress.kubernetes.io/healthcheck-interval-seconds": "15",
                "alb.ingress.kubernetes.io/healthcheck-timeout-seconds": "5",
                "alb.ingress.kubernetes.io/healthy-threshold-count": "2",
                "alb.ingress.kubernetes.io/unhealthy-threshold-count": "3",
                "alb.ingress.kubernetes.io/listen-ports": '[{"HTTPS": 443}]',
                "alb.ingress.kubernetes.io/backend-protocol": "HTTP",
                "alb.ingress.kubernetes.io/ssl-redirect": "443",
            },
            labels={
                "modelhub.aws/endpoint-name": endpoint_name,
                "modelhub.aws/precreated": "true"
            }
        ),
        spec=client.V1IngressSpec(
            ingress_class_name="alb",
            rules=[
                client.V1IngressRule(
                    http=client.V1HTTPIngressRuleValue(
                        paths=[
                            client.V1HTTPIngressPath(
                                path="/",
                                path_type="Prefix",
                                backend=client.V1IngressBackend(
                                    service=client.V1IngressServiceBackend(
                                        name=service_name,
                                        port=client.V1ServiceBackendPort(
                                            number=container_port
                                        )
                                    )
                                )
                            )
                        ]
                    )
                )
            ]
        )
    )

    try:
        networking_api.create_namespaced_ingress(namespace=namespace, body=ingress)
        logger.info(f"Pre-created internet-facing Ingress: {ingress_name}")
        return {
            "success": True,
            "ingress_name": ingress_name,
            "message": f"Pre-created internet-facing Ingress {ingress_name}"
        }
    except ApiException as e:
        logger.error(f"Failed to create Ingress: {e}")
        return {"success": False, "error": str(e)}
