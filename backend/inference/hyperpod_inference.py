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
from utils.config import DEFAULT_IMAGES
from logger_config import setup_logger
logger = setup_logger('hyperpod_inference.py', log_file='hyperpod_inference.log', level=logging.INFO)

# Import resource utilities
from inference.utils import (
    GPU_MAPPING,
    INSTANCE_RESOURCES,
    DEFAULT_RESOURCES,
    get_gpu_count,
    get_instance_resources,
    get_per_replica_resources,
)

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


# ==============================================================================
# API Key Authentication Support
# ==============================================================================

def generate_api_key(prefix: str = "sk-") -> str:
    """
    Generate a secure random API key.

    Args:
        prefix: Prefix for the API key (default: "sk-")

    Returns:
        A secure random API key string
    """
    import secrets
    # Generate 32 random bytes and encode as hex (64 chars)
    random_part = secrets.token_hex(32)
    return f"{prefix}{random_part}"


def create_api_key_secret(
    kubeconfig_path: str,
    secret_name: str,
    namespace: str,
    api_key: str,
    labels: Dict[str, str] = None
) -> Dict[str, Any]:
    """
    Create a Kubernetes Secret containing the API key.

    Args:
        kubeconfig_path: Path to kubeconfig file
        secret_name: Name for the Secret
        namespace: Kubernetes namespace
        api_key: The API key value
        labels: Optional labels for the Secret

    Returns:
        Dict with result status
    """
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
    import base64

    config.load_kube_config(config_file=kubeconfig_path)
    core_api = client.CoreV1Api()

    # Create Secret
    secret = client.V1Secret(
        api_version="v1",
        kind="Secret",
        metadata=client.V1ObjectMeta(
            name=secret_name,
            namespace=namespace,
            labels=labels or {}
        ),
        type="Opaque",
        string_data={
            "api-key": api_key
        }
    )

    try:
        # Try to create, or update if exists
        try:
            core_api.create_namespaced_secret(namespace=namespace, body=secret)
            logger.info(f"Created API key secret: {secret_name}")
        except ApiException as e:
            if e.status == 409:  # Already exists, update it
                core_api.replace_namespaced_secret(name=secret_name, namespace=namespace, body=secret)
                logger.info(f"Updated API key secret: {secret_name}")
            else:
                raise

        return {"success": True, "secret_name": secret_name}
    except ApiException as e:
        logger.error(f"Failed to create API key secret: {e}")
        return {"success": False, "error": str(e)}


def configure_router_api_key(
    kubeconfig_path: str,
    endpoint_name: str,
    api_key_secret_name: str,
    source_namespace: str = "default",
    router_namespace: str = "hyperpod-inference-system",
    max_retries: int = 10,
    retry_delay: int = 10,
    patch_verify_retries: int = 5,
    patch_verify_delay: int = 30
) -> Dict[str, Any]:
    """
    Configure the intelligent routing router with API key authentication.

    When API key authentication is enabled for vLLM, the router also needs
    the API key to authenticate with the backend. This function:
    1. Copies the API key secret to the router's namespace
    2. Waits for router deployment and pods to be ready
    3. Patches the router deployment to use the secret
    4. Verifies and re-applies the patch if the operator resets it

    Note: The HyperPod operator continuously reconciles the router deployment,
    which can reset our patches. This function includes retry logic to handle
    operator reconciliation and ensure the API key configuration persists.

    Args:
        kubeconfig_path: Path to kubeconfig file
        endpoint_name: Name of the endpoint
        api_key_secret_name: Name of the API key secret
        source_namespace: Namespace where the secret exists (usually 'default')
        router_namespace: Namespace where the router runs ('hyperpod-inference-system')
        max_retries: Maximum retries waiting for router deployment
        retry_delay: Delay between retries in seconds
        patch_verify_retries: Number of times to verify/re-apply the patch
        patch_verify_delay: Delay between patch verification attempts

    Returns:
        Dict with result status
    """
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
    import time

    config.load_kube_config(config_file=kubeconfig_path)
    core_api = client.CoreV1Api()
    apps_api = client.AppsV1Api()

    resource_name = endpoint_name.lower().replace("_", "-")[:63]
    router_deployment_name = f"{resource_name}-{source_namespace}-router"

    def check_vllm_api_key_configured(deployment) -> bool:
        """Check if VLLM_API_KEY is properly configured with secretKeyRef."""
        containers = deployment.spec.template.spec.containers
        for container in containers:
            if 'router' in container.name.lower():
                if container.env:
                    for env_var in container.env:
                        if env_var.name == "VLLM_API_KEY":
                            # Check if it has the correct secretKeyRef
                            if (env_var.value_from and
                                env_var.value_from.secret_key_ref and
                                env_var.value_from.secret_key_ref.name == api_key_secret_name):
                                return True
                            # Found VLLM_API_KEY but it's empty or wrong secretKeyRef
                            return False
                break
        return False

    def apply_api_key_patch(deployment) -> bool:
        """Apply the API key patch to the router deployment. Returns True if patch applied."""
        containers = deployment.spec.template.spec.containers
        router_container_idx = None
        vllm_api_key_idx = None

        for i, container in enumerate(containers):
            if 'router' in container.name.lower():
                router_container_idx = i
                if container.env:
                    for j, env_var in enumerate(container.env):
                        if env_var.name == "VLLM_API_KEY":
                            vllm_api_key_idx = j
                            break
                break

        if router_container_idx is None:
            logger.warning("Router container not found in deployment")
            return False

        # Build the patch - always use replace if VLLM_API_KEY exists
        if vllm_api_key_idx is not None:
            patch = [{
                "op": "replace",
                "path": f"/spec/template/spec/containers/{router_container_idx}/env/{vllm_api_key_idx}",
                "value": {
                    "name": "VLLM_API_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": api_key_secret_name,
                            "key": "api-key"
                        }
                    }
                }
            }]
        else:
            patch = [{
                "op": "add",
                "path": f"/spec/template/spec/containers/{router_container_idx}/env/-",
                "value": {
                    "name": "VLLM_API_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": api_key_secret_name,
                            "key": "api-key"
                        }
                    }
                }
            }]

        apps_api.patch_namespaced_deployment(
            name=router_deployment_name,
            namespace=router_namespace,
            body=patch
        )
        return True

    try:
        # Step 1: Copy the API key secret to the router's namespace
        logger.info(f"[Router Config] Copying API key secret to {router_namespace} namespace")
        try:
            source_secret = core_api.read_namespaced_secret(
                name=api_key_secret_name,
                namespace=source_namespace
            )

            router_secret = client.V1Secret(
                api_version="v1",
                kind="Secret",
                metadata=client.V1ObjectMeta(
                    name=api_key_secret_name,
                    namespace=router_namespace,
                    labels=source_secret.metadata.labels or {}
                ),
                type="Opaque",
                data=source_secret.data
            )

            try:
                core_api.create_namespaced_secret(namespace=router_namespace, body=router_secret)
                logger.info(f"[Router Config] Created API key secret in {router_namespace}: {api_key_secret_name}")
            except ApiException as e:
                if e.status == 409:  # Already exists
                    core_api.replace_namespaced_secret(
                        name=api_key_secret_name,
                        namespace=router_namespace,
                        body=router_secret
                    )
                    logger.info(f"[Router Config] Updated API key secret in {router_namespace}: {api_key_secret_name}")
                else:
                    raise
        except ApiException as e:
            logger.error(f"[Router Config] Failed to copy API key secret: {e}")
            return {"success": False, "error": f"Failed to copy secret: {e}"}

        # Step 2: Wait for router deployment to be created
        logger.info(f"[Router Config] Waiting for router deployment: {router_deployment_name}")
        router_found = False
        for attempt in range(max_retries):
            try:
                deployment = apps_api.read_namespaced_deployment(
                    name=router_deployment_name,
                    namespace=router_namespace
                )
                router_found = True
                logger.info(f"[Router Config] Found router deployment: {router_deployment_name}")
                break
            except ApiException as e:
                if e.status == 404:
                    logger.info(f"[Router Config] Router deployment not found yet, waiting... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(retry_delay)
                else:
                    raise

        if not router_found:
            logger.warning(f"[Router Config] Router deployment {router_deployment_name} not found after {max_retries} retries")
            return {
                "success": False,
                "error": f"Router deployment not found: {router_deployment_name}",
                "message": "Intelligent routing may not be enabled or deployment is still in progress"
            }

        # Step 3: Wait for router pods to be ready (indicates operator finished initial setup)
        logger.info(f"[Router Config] Waiting for router pods to be ready...")
        pods_ready = False
        for attempt in range(max_retries):
            try:
                pods = core_api.list_namespaced_pod(
                    namespace=router_namespace,
                    label_selector=f"app={router_deployment_name}"
                )
                if pods.items:
                    running_pods = [p for p in pods.items if p.status.phase == "Running"]
                    if running_pods:
                        pods_ready = True
                        logger.info(f"[Router Config] Router pods are running ({len(running_pods)} pods)")
                        break
                logger.info(f"[Router Config] Waiting for router pods... (attempt {attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
            except ApiException as e:
                logger.warning(f"[Router Config] Error checking pods: {e}")
                time.sleep(retry_delay)

        if not pods_ready:
            logger.warning(f"[Router Config] Router pods not ready, proceeding with patch anyway")

        # Step 4: Apply patch and verify with retries
        # The HyperPod operator may reset our patch during reconciliation,
        # so we verify and re-apply multiple times until we see consecutive successes
        patch_successful = False
        consecutive_successes = 0
        required_consecutive_successes = 3  # Require 3 consecutive checks to confirm stability

        for verify_attempt in range(patch_verify_retries):
            try:
                # Re-read deployment to get current state
                deployment = apps_api.read_namespaced_deployment(
                    name=router_deployment_name,
                    namespace=router_namespace
                )

                # Check if already configured correctly
                if check_vllm_api_key_configured(deployment):
                    consecutive_successes += 1
                    logger.info(f"[Router Config] VLLM_API_KEY correctly configured (attempt {verify_attempt + 1}, consecutive: {consecutive_successes}/{required_consecutive_successes})")
                    if consecutive_successes >= required_consecutive_successes:
                        patch_successful = True
                        logger.info(f"[Router Config] Patch stable after {required_consecutive_successes} consecutive checks")
                        break
                    time.sleep(patch_verify_delay)
                    continue
                else:
                    # Reset counter if patch was undone
                    if consecutive_successes > 0:
                        logger.warning(f"[Router Config] Operator reset the patch (was {consecutive_successes} consecutive successes)")
                    consecutive_successes = 0

                # Apply the patch
                logger.info(f"[Router Config] Applying API key patch (attempt {verify_attempt + 1}/{patch_verify_retries})")
                if apply_api_key_patch(deployment):
                    logger.info(f"[Router Config] Patched router deployment with API key")

                    # Wait a bit and verify
                    time.sleep(5)
                    deployment = apps_api.read_namespaced_deployment(
                        name=router_deployment_name,
                        namespace=router_namespace
                    )
                    if check_vllm_api_key_configured(deployment):
                        consecutive_successes = 1  # Start counting consecutive successes
                        logger.info(f"[Router Config] Patch verified (consecutive: {consecutive_successes}/{required_consecutive_successes})")
                    else:
                        logger.warning(f"[Router Config] Patch may have been reset by operator, will retry...")
                else:
                    logger.warning(f"[Router Config] Failed to apply patch")

                # Wait before next verification attempt
                if verify_attempt < patch_verify_retries - 1:
                    time.sleep(patch_verify_delay)

            except ApiException as e:
                logger.error(f"[Router Config] Error during patch attempt {verify_attempt + 1}: {e}")
                if verify_attempt < patch_verify_retries - 1:
                    time.sleep(patch_verify_delay)

        if patch_successful:
            return {
                "success": True,
                "router_deployment": router_deployment_name,
                "message": "Router configured with API key authentication"
            }
        else:
            return {
                "success": False,
                "router_deployment": router_deployment_name,
                "error": "Patch applied but may have been reset by operator",
                "message": "Router API key configuration may need manual verification"
            }

    except ApiException as e:
        logger.error(f"[Router Config] Failed to configure router API key: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"[Router Config] Unexpected error configuring router API key: {e}")
        return {"success": False, "error": str(e)}


def patch_readiness_probe_timeout(
    kubeconfig_path: str,
    endpoint_name: str,
    namespace: str = "default",
    timeout_seconds: int = 5,
    max_retries: int = 30,
    retry_delay: int = 10
) -> Dict[str, Any]:
    """
    Patch the model deployment to increase the readiness probe timeout.

    The HyperPod operator sets a default readiness probe timeout of 1 second,
    which can be too short for some models (especially SGLang). This function
    patches the deployment to use a longer timeout.

    IMPORTANT: The HyperPod operator may reset the timeout during reconciliation.
    This function will:
    1. Wait for deployment to be created
    2. Patch the timeout and verify it persists (retry if operator resets)
    3. Delete existing pods to force rollout
    4. Re-patch after pod deletion to ensure new pods get correct timeout

    Args:
        kubeconfig_path: Path to kubeconfig file
        endpoint_name: Name of the endpoint
        namespace: Kubernetes namespace where deployment exists
        timeout_seconds: New timeout value in seconds (default: 5)
        max_retries: Maximum retries waiting for deployment
        retry_delay: Delay between retries in seconds

    Returns:
        Dict with result status
    """
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
    import time

    config.load_kube_config(config_file=kubeconfig_path)
    apps_api = client.AppsV1Api()
    core_api = client.CoreV1Api()

    resource_name = endpoint_name.lower().replace("_", "-")[:63]

    def get_containers_needing_patch(deployment):
        """Find containers with readiness probe timeout less than target."""
        containers_to_patch = []
        containers = deployment.spec.template.spec.containers
        for i, container in enumerate(containers):
            if container.readiness_probe and container.readiness_probe.timeout_seconds:
                current_timeout = container.readiness_probe.timeout_seconds
                if current_timeout < timeout_seconds:
                    containers_to_patch.append((i, container.name, current_timeout))
        return containers_to_patch

    def patch_container_timeout(container_index, container_name):
        """Patch a container's readiness probe timeout. Returns True on success."""
        try:
            patch = [{
                "op": "replace",
                "path": f"/spec/template/spec/containers/{container_index}/readinessProbe/timeoutSeconds",
                "value": timeout_seconds
            }]
            apps_api.patch_namespaced_deployment(
                name=resource_name,
                namespace=namespace,
                body=patch
            )
            logger.info(f"[Readiness Patch] Patched container {container_name} timeout to {timeout_seconds}s")
            return True
        except ApiException as e:
            logger.warning(f"[Readiness Patch] Failed to patch container {container_name}: {e}")
            return False

    def ensure_timeout_patched(max_attempts=5, wait_between=3):
        """Patch and verify timeout persists. Returns True if successful."""
        for attempt in range(max_attempts):
            # Get current state
            deployment = apps_api.read_namespaced_deployment(
                name=resource_name,
                namespace=namespace
            )
            containers_to_patch = get_containers_needing_patch(deployment)

            if not containers_to_patch:
                logger.info(f"[Readiness Patch] All containers have correct timeout (>= {timeout_seconds}s)")
                return True

            # Patch containers that need it
            for container_index, container_name, current_timeout in containers_to_patch:
                logger.info(f"[Readiness Patch] Container {container_name}: {current_timeout}s -> {timeout_seconds}s (attempt {attempt + 1}/{max_attempts})")
                patch_container_timeout(container_index, container_name)

            # Wait for operator reconciliation
            time.sleep(wait_between)

        # Final check
        deployment = apps_api.read_namespaced_deployment(
            name=resource_name,
            namespace=namespace
        )
        return len(get_containers_needing_patch(deployment)) == 0

    try:
        # Wait for deployment to be created
        logger.info(f"[Readiness Patch] Waiting for deployment: {resource_name}")
        deployment = None
        for attempt in range(max_retries):
            try:
                deployment = apps_api.read_namespaced_deployment(
                    name=resource_name,
                    namespace=namespace
                )
                logger.info(f"[Readiness Patch] Found deployment: {resource_name}")
                break
            except ApiException as e:
                if e.status == 404:
                    logger.info(f"[Readiness Patch] Deployment not found yet, waiting... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(retry_delay)
                else:
                    raise

        if deployment is None:
            logger.warning(f"[Readiness Patch] Deployment {resource_name} not found after {max_retries} retries")
            return {
                "success": False,
                "error": f"Deployment not found: {resource_name}"
            }

        # Check if any containers need patching
        containers_to_patch = get_containers_needing_patch(deployment)
        if not containers_to_patch:
            logger.info(f"[Readiness Patch] No containers need patching, timeout already >= {timeout_seconds}s")
            return {
                "success": True,
                "deployment": resource_name,
                "message": "No patching needed"
            }

        for container_index, container_name, current_timeout in containers_to_patch:
            logger.info(f"[Readiness Patch] Container {container_name} needs patching: {current_timeout}s -> {timeout_seconds}s")

        # CRITICAL: Use "Scale to 0" strategy to avoid resource contention
        # Why: ReplicaSet has self-healing - deleting pods triggers immediate recreation
        # with old config. Patching while pods exist triggers rolling update causing
        # new+old pods to coexist (resource contention on single-node).
        #
        # Solution: Scale to 0 -> Patch -> Scale back
        # This ensures all new pods use the patched configuration from the start.

        original_replicas = deployment.spec.replicas
        logger.info(f"[Readiness Patch] Original replicas: {original_replicas}")

        # Step 1: Scale deployment to 0
        logger.info(f"[Readiness Patch] Scaling deployment to 0 replicas...")
        try:
            scale_patch = {"spec": {"replicas": 0}}
            apps_api.patch_namespaced_deployment(
                name=resource_name,
                namespace=namespace,
                body=scale_patch
            )
            logger.info(f"[Readiness Patch] Deployment scaled to 0")

            # Wait for pods to terminate
            max_wait_attempts = 30  # 30 * 2 = 60 seconds max
            for attempt in range(max_wait_attempts):
                pods = core_api.list_namespaced_pod(
                    namespace=namespace,
                    label_selector=f"app={resource_name}"
                )
                if len(pods.items) == 0:
                    logger.info(f"[Readiness Patch] All pods terminated")
                    break
                logger.info(f"[Readiness Patch] Waiting for {len(pods.items)} pod(s) to terminate (attempt {attempt + 1}/{max_wait_attempts})...")
                time.sleep(2)
            else:
                logger.warning(f"[Readiness Patch] Pods did not terminate after {max_wait_attempts * 2}s, proceeding anyway")

        except Exception as e:
            logger.error(f"[Readiness Patch] Failed to scale deployment to 0: {e}")
            # Continue anyway, worst case we still patch with running pods

        # Step 2: Patch the deployment with new timeout
        logger.info(f"[Readiness Patch] Patching deployment with timeout={timeout_seconds}s...")
        patch_success = ensure_timeout_patched(max_attempts=5, wait_between=3)

        # Step 3: Scale back to original replicas
        logger.info(f"[Readiness Patch] Scaling back to {original_replicas} replicas...")
        try:
            scale_patch = {"spec": {"replicas": original_replicas}}
            apps_api.patch_namespaced_deployment(
                name=resource_name,
                namespace=namespace,
                body=scale_patch
            )
            logger.info(f"[Readiness Patch] Deployment scaled back to {original_replicas}")
        except Exception as e:
            logger.error(f"[Readiness Patch] Failed to scale back to {original_replicas}: {e}")

        # Final verification
        logger.info(f"[Readiness Patch] Final verification of timeout configuration...")
        final_success = ensure_timeout_patched(max_attempts=3, wait_between=2)

        if final_success:
            logger.info(f"[Readiness Patch] Successfully set timeout to {timeout_seconds}s")
        else:
            logger.warning(f"[Readiness Patch] Could not guarantee timeout={timeout_seconds}s, operator may be overriding")

        return {
            "success": True,
            "deployment": resource_name,
            "timeout_seconds": timeout_seconds,
            "message": f"Readiness probe timeout set to {timeout_seconds}s" + ("" if final_success else " (may be reset by operator)")
        }

    except ApiException as e:
        logger.error(f"[Readiness Patch] Failed to patch deployment: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"[Readiness Patch] Unexpected error: {e}")
        return {"success": False, "error": str(e)}


def create_external_secret(
    kubeconfig_path: str,
    external_secret_name: str,
    namespace: str,
    secrets_manager_secret_name: str,
    target_secret_name: str,
    region: str,
    service_account_name: str = "default"
) -> Dict[str, Any]:
    """
    Create an ExternalSecret to fetch API key from AWS Secrets Manager.

    This requires External Secrets Operator to be installed on the cluster.

    Args:
        kubeconfig_path: Path to kubeconfig file
        external_secret_name: Name for the ExternalSecret resource
        namespace: Kubernetes namespace
        secrets_manager_secret_name: Name of the secret in AWS Secrets Manager
        target_secret_name: Name of the K8s Secret to create
        region: AWS region
        service_account_name: Service account for IRSA authentication

    Returns:
        Dict with result status
    """
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException

    config.load_kube_config(config_file=kubeconfig_path)
    custom_api = client.CustomObjectsApi()

    # First, create or ensure SecretStore exists
    secret_store_name = "aws-secrets-manager"
    secret_store = {
        "apiVersion": "external-secrets.io/v1beta1",
        "kind": "SecretStore",
        "metadata": {
            "name": secret_store_name,
            "namespace": namespace
        },
        "spec": {
            "provider": {
                "aws": {
                    "service": "SecretsManager",
                    "region": region,
                    "auth": {
                        "jwt": {
                            "serviceAccountRef": {
                                "name": service_account_name
                            }
                        }
                    }
                }
            }
        }
    }

    try:
        # Create SecretStore if not exists
        try:
            custom_api.create_namespaced_custom_object(
                group="external-secrets.io",
                version="v1beta1",
                namespace=namespace,
                plural="secretstores",
                body=secret_store
            )
            logger.info(f"Created SecretStore: {secret_store_name}")
        except ApiException as e:
            if e.status != 409:  # Ignore if already exists
                logger.warning(f"Failed to create SecretStore: {e}")
    except Exception as e:
        logger.warning(f"External Secrets Operator may not be installed: {e}")

    # Create ExternalSecret
    external_secret = {
        "apiVersion": "external-secrets.io/v1beta1",
        "kind": "ExternalSecret",
        "metadata": {
            "name": external_secret_name,
            "namespace": namespace
        },
        "spec": {
            "refreshInterval": "1h",
            "secretStoreRef": {
                "name": secret_store_name,
                "kind": "SecretStore"
            },
            "target": {
                "name": target_secret_name,
                "creationPolicy": "Owner"
            },
            "data": [
                {
                    "secretKey": "api-key",
                    "remoteRef": {
                        "key": secrets_manager_secret_name
                    }
                }
            ]
        }
    }

    try:
        try:
            custom_api.create_namespaced_custom_object(
                group="external-secrets.io",
                version="v1beta1",
                namespace=namespace,
                plural="externalsecrets",
                body=external_secret
            )
            logger.info(f"Created ExternalSecret: {external_secret_name}")
        except ApiException as e:
            if e.status == 409:  # Already exists, update it
                custom_api.replace_namespaced_custom_object(
                    group="external-secrets.io",
                    version="v1beta1",
                    namespace=namespace,
                    plural="externalsecrets",
                    name=external_secret_name,
                    body=external_secret
                )
                logger.info(f"Updated ExternalSecret: {external_secret_name}")
            else:
                raise

        return {
            "success": True,
            "external_secret_name": external_secret_name,
            "target_secret_name": target_secret_name
        }
    except ApiException as e:
        logger.error(f"Failed to create ExternalSecret: {e}")
        return {"success": False, "error": str(e)}


@dataclass
class ApiKeyConfig:
    """API Key authentication configuration for HyperPod inference endpoints."""
    enabled: bool = False
    source: str = "auto"  # 'auto', 'custom', 'secrets_manager'
    custom_api_key: str = ""
    secrets_manager_secret_name: str = ""

    def get_api_key_or_generate(self) -> str:
        """Get the API key, generating one if source is 'auto'."""
        if self.source == "auto":
            return generate_api_key()
        elif self.source == "custom":
            return self.custom_api_key
        else:
            return ""  # Will be fetched from Secrets Manager


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
    instance_count: int = 1,  # Number of available instances for resource allocation
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

    # Get AWS account ID for TLS certificate S3 bucket
    sts_client = boto3.client('sts')
    account_id = sts_client.get_caller_identity()['Account']

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
            # prefetchEnabled must be False when L2 cache is enabled to avoid lmcache-config volume issue
            "prefetchEnabled": False
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
            # prefetchEnabled must be False when L2 cache is enabled to avoid lmcache-config volume issue
            "prefetchEnabled": False
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

    # vLLM uses port 8000, SGLang DLC uses port 8080
    container_port = 8080 if engine.lower() == "sglang" else 8000

    # Calculate per-replica resources based on replicas and instance count
    replica_resources = get_per_replica_resources(instance_type, replicas, instance_count)
    gpu_count = replica_resources["gpu"]
    instance_resources = {"cpu": replica_resources["cpu"], "memory": replica_resources["memory"]}

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

    # Extract a clean served model name for the inference engine
    # This allows users to reference the model by a friendly name instead of /opt/ml/model
    if "/" in model_name:
        # HuggingFace format: "Qwen/Qwen3-4B-Instruct" -> "Qwen3-4B-Instruct"
        served_model_name = model_name.split("/")[-1]
    else:
        served_model_name = model_name

    # Override container command to include --served-model-name and tensor parallel size
    # The HyperPod DLC containers have a fixed CMD that ignores args, so we must use command
    if engine.lower() == "sglang":
        worker_spec["command"] = ["python3", "-m", "sglang.launch_server"]
        args = [
            "--port", str(container_port),
            "--host", "0.0.0.0",
            "--model-path", "/opt/ml/model",
            "--served-model-name", served_model_name,
            "--enable-metrics"  # Required for vLLM router to scrape metrics and keep backend registered
        ]
        # Add tensor parallel size for multi-GPU instances
        if gpu_count > 1:
            args.extend(["--tp", str(gpu_count)])
        worker_spec["args"] = args
    else:  # vllm
        # Use DLC default entrypoint - first arg is model path, followed by vLLM CLI options
        args = [
            "/opt/ml/model",  # Model path as first argument
            "--served-model-name", served_model_name
        ]
        # Add tensor parallel size for multi-GPU instances
        if gpu_count > 1:
            args.extend(["--tensor-parallel-size", str(gpu_count)])
        worker_spec["args"] = args

    # Build spec
    spec = {
        "modelName": model_name,
        "endpointName": endpoint_name,
        "instanceType": instance_type,
        "invocationEndpoint": "v1/chat/completions",  # Must be valid for intelligent routing
        "replicas": replicas,
        "worker": worker_spec,
        "modelSourceConfig": model_source_config,  # Required for all deployments
        # Metrics configuration
        "metrics": {
            "enabled": True,
            "modelMetrics": {
                "port": container_port
            }
        },
        # Load balancer configuration
        "loadBalancer": {
            "healthCheckPath": "/health"
        },
        # TLS configuration for certificate management
        "tlsConfig": {
            "tlsCertificateOutputS3Uri": f"s3://llm-modelhub-hyperpod-{account_id}-{region}/certs"
        }
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
    instance_count: int = 1,  # Number of available instances for resource allocation
    namespace: str = "default",
    region: str = None,
    model_s3_path: str = None,
    huggingface_model_id: str = None,
    # Advanced configuration
    autoscaling: Optional[AutoScalingConfig] = None,
    kv_cache: Optional[KVCacheConfig] = None,
    intelligent_routing: Optional[IntelligentRoutingConfig] = None,
    api_key_config: Optional[ApiKeyConfig] = None,
    # Extra parameters
    extra_env_vars: Optional[Dict[str, str]] = None,
    tensor_parallel_size: Optional[int] = None,
    max_model_len: Optional[int] = None,
    enable_prefix_caching: bool = False,
    # Additional vLLM/SGLang parameters
    gpu_memory_utilization: Optional[float] = None,  # vLLM: --gpu-memory-utilization, SGLang: --mem-fraction-static
    chat_template: Optional[str] = None,
    tool_call_parser: Optional[str] = None,
    # vLLM-specific parameters
    limit_mm_per_prompt: Optional[str] = None,  # vLLM: --limit-mm-per-prompt (e.g., "image=2,video=1")
    enforce_eager: bool = False,  # vLLM: --enforce-eager (disable CUDA graph)
    max_num_seqs: Optional[int] = None,  # vLLM: --max-num-seqs (max concurrent sequences)
    dtype: Optional[str] = None,  # vLLM/SGLang: --dtype (e.g., "auto", "half", "float16", "bfloat16")
    trust_remote_code: bool = True  # vLLM/SGLang: --trust-remote-code (default True for HuggingFace models)
) -> Dict[str, Any]:
    """
    Deploy a model to HyperPod EKS cluster with advanced configuration options.

    This is an enhanced version of deploy_to_hyperpod that supports:
    - Auto-scaling based on CloudWatch metrics via KEDA
    - KV Cache configuration for optimized inference
    - Intelligent routing for request distribution
    - API Key authentication for vLLM/SGLang endpoints

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
        api_key_config: API Key authentication configuration
        extra_env_vars: Additional environment variables
        tensor_parallel_size: Tensor parallel size (auto-detected if not specified)
        max_model_len: Maximum model length
        enable_prefix_caching: Enable prefix caching (vllm only)
        gpu_memory_utilization: GPU memory utilization (0.0-1.0), maps to --gpu-memory-utilization (vLLM) or --mem-fraction-static (SGLang)
        chat_template: Custom chat template path
        tool_call_parser: Tool call parser (e.g., hermes, llama3_json)

    Returns:
        Dict with deployment result including status
    """
    from kubernetes.client.rest import ApiException

    if region is None:
        session = boto3.Session()
        region = session.region_name or 'us-west-2'

    # Get AWS account ID for TLS certificate S3 bucket
    sts_client = boto3.client('sts')
    account_id = sts_client.get_caller_identity()['Account']

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
            # prefetchEnabled must be False when L2 cache is enabled to avoid lmcache-config volume issue
            "prefetchEnabled": False
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
            # prefetchEnabled must be False when L2 cache is enabled to avoid lmcache-config volume issue
            "prefetchEnabled": False
        }
        model_path_for_env = "/opt/ml/model"
        use_s3_model = False

    # Build environment variables
    env_vars = []
    # Calculate per-replica resources based on replicas and instance count
    # When replicas > instance_count, resources are divided to fit multiple replicas per instance
    replica_resources = get_per_replica_resources(instance_type, replicas, instance_count)
    gpu_count = replica_resources["gpu"]
    instance_resources = {"cpu": replica_resources["cpu"], "memory": replica_resources["memory"]}
    tp_size = tensor_parallel_size or replica_resources["tensor_parallel_size"]

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

    # vLLM uses port 8000, SGLang DLC uses port 8080
    container_port = 8080 if engine.lower() == "sglang" else 8000
    resource_name = endpoint_name.lower().replace("_", "-")[:63]

    # Handle API Key authentication
    api_key_secret_name = None
    generated_api_key = None
    if api_key_config and api_key_config.enabled:
        api_key_secret_name = f"{resource_name}-api-key"

        if api_key_config.source == "secrets_manager":
            # Create ExternalSecret for AWS Secrets Manager
            ext_secret_result = create_external_secret(
                kubeconfig_path=kubeconfig_path,
                external_secret_name=f"{resource_name}-ext-secret",
                namespace=namespace,
                secrets_manager_secret_name=api_key_config.secrets_manager_secret_name,
                target_secret_name=api_key_secret_name,
                region=region
            )
            if not ext_secret_result.get("success"):
                logger.warning(f"Failed to create ExternalSecret: {ext_secret_result.get('error')}")
        else:
            # Generate or use custom API key
            generated_api_key = api_key_config.get_api_key_or_generate()
            secret_result = create_api_key_secret(
                kubeconfig_path=kubeconfig_path,
                secret_name=api_key_secret_name,
                namespace=namespace,
                api_key=generated_api_key,
                labels={"modelhub.aws/endpoint-name": endpoint_name}
            )
            if not secret_result.get("success"):
                logger.warning(f"Failed to create API key secret: {secret_result.get('error')}")

    # Add API key environment variable if enabled
    # vLLM uses VLLM_API_KEY environment variable for --api-key
    # SGLang also supports API key via environment variable
    # NOTE: We use plain value instead of secretKeyRef because the HyperPod operator
    # copies env vars from worker to router but doesn't properly copy secretKeyRef.
    # Using plain value allows the operator to copy the API key to the router.
    if api_key_secret_name and generated_api_key:
        # Use plain value so operator copies it to router
        env_vars.append({
            "name": "VLLM_API_KEY",
            "value": generated_api_key
        })
    elif api_key_secret_name:
        # Fallback to secretKeyRef for secrets_manager case (less common)
        env_vars.append({
            "name": "VLLM_API_KEY",
            "valueFrom": {
                "secretKeyRef": {
                    "name": api_key_secret_name,
                    "key": "api-key"
                }
            }
        })

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

    # Extract a clean served model name for the inference engine
    # This allows users to reference the model by a friendly name instead of /opt/ml/model
    if "/" in model_name:
        # HuggingFace format: "Qwen/Qwen3-4B-Instruct" -> "Qwen3-4B-Instruct"
        served_model_name = model_name.split("/")[-1]
    else:
        served_model_name = model_name

    # Override container command to include --served-model-name and optional parameters
    # The HyperPod DLC containers have a fixed CMD that ignores args, so we must use command
    if engine.lower() == "sglang":
        worker_spec["command"] = ["python3", "-m", "sglang.launch_server"]
        args = [
            "--port", str(container_port),
            "--host", "0.0.0.0",
            "--model-path", "/opt/ml/model",
            "--served-model-name", served_model_name,
            "--enable-metrics"  # Required for vLLM router to scrape metrics and keep backend registered
        ]
        # Add trust-remote-code (default True for HuggingFace models)
        if trust_remote_code:
            args.append("--trust-remote-code")
        # Add optional SGLang parameters
        # Always add tp_size (auto-calculated from instance GPU count if not specified)
        if tp_size and tp_size > 1:
            args.extend(["--tp", str(tp_size)])
        if max_model_len:
            args.extend(["--context-length", str(max_model_len)])
        if dtype:
            args.extend(["--dtype", dtype])
        if gpu_memory_utilization is not None:
            args.extend(["--mem-fraction-static", str(gpu_memory_utilization)])
        if chat_template:
            args.extend(["--chat-template", chat_template])
        if tool_call_parser:
            args.extend(["--tool-call-parser", tool_call_parser])
        worker_spec["args"] = args
    else:  # vllm
        # Use DLC default entrypoint - first arg is model path, followed by vLLM CLI options
        # This avoids the L2 Cache operator bug (lmcache-config volume not created when custom command is set)
        args = [
            "/opt/ml/model",  # Model path as first argument
            "--served-model-name", served_model_name
        ]
        # Add trust-remote-code (default True for HuggingFace models)
        if trust_remote_code:
            args.append("--trust-remote-code")
        # Add optional vLLM parameters
        # Always add tp_size (auto-calculated from instance GPU count if not specified)
        if tp_size and tp_size > 1:
            args.extend(["--tensor-parallel-size", str(tp_size)])
        if max_model_len:
            args.extend(["--max-model-len", str(max_model_len)])
        if dtype:
            args.extend(["--dtype", dtype])
        # Note: --enable-prefix-caching is NOT needed for vLLM on HyperPod
        # The kvCacheSpec handles prefix caching automatically via the operator
        if gpu_memory_utilization is not None:
            args.extend(["--gpu-memory-utilization", str(gpu_memory_utilization)])
        if chat_template:
            args.extend(["--chat-template", chat_template])
        if tool_call_parser:
            args.append("--enable-auto-tool-choice")
            args.extend(["--tool-call-parser", tool_call_parser])
        if limit_mm_per_prompt:
            args.extend(["--limit-mm-per-prompt", limit_mm_per_prompt])
        if enforce_eager:
            args.append("--enforce-eager")
        if max_num_seqs:
            args.extend(["--max-num-seqs", str(max_num_seqs)])
        worker_spec["args"] = args

    # Build spec
    spec = {
        "modelName": model_name,
        "endpointName": endpoint_name,
        "instanceType": instance_type,
        "invocationEndpoint": "v1/chat/completions",  # Must be valid for intelligent routing
        "replicas": replicas,
        "worker": worker_spec,
        "modelSourceConfig": model_source_config,  # Required for all deployments
        # Metrics configuration - required for L2 cache to work properly
        "metrics": {
            "enabled": True,
            "modelMetrics": {
                "port": container_port
            }
        },
        # Load balancer configuration
        "loadBalancer": {
            "healthCheckPath": "/health"
        },
        # TLS configuration for certificate management
        "tlsConfig": {
            "tlsCertificateOutputS3Uri": f"s3://llm-modelhub-hyperpod-{account_id}-{region}/certs"
        }
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
        result = {
            "success": True,
            "resource_name": resource_name,
            "namespace": namespace,
            "message": f"Deployment initiated for {endpoint_name}",
            "features": {
                "autoscaling": autoscaling is not None,
                "kv_cache": kv_cache is not None,
                "intelligent_routing": intelligent_routing is not None,
                "api_key_auth": api_key_config is not None and api_key_config.enabled
            }
        }
        # Include generated API key in response (only for auto-generated keys)
        # This allows the frontend to display it to the user once
        if generated_api_key and api_key_config and api_key_config.source == "auto":
            result["api_key"] = generated_api_key
            result["api_key_warning"] = "Save this API key securely. It will not be shown again."

        # Configure router with API key for secrets_manager case only
        # For auto/custom API key sources, we use plain value in the CRD which the operator
        # automatically copies to the router. For secrets_manager, we need to manually
        # configure the router since the CRD uses secretKeyRef which the operator doesn't copy.
        # This is done in a background thread since the router deployment is created asynchronously.
        needs_router_config = (
            intelligent_routing and
            api_key_config and
            api_key_config.enabled and
            api_key_secret_name and
            not generated_api_key  # Only needed for secrets_manager case (no generated key)
        )
        if needs_router_config:
            import threading
            def configure_router_background():
                try:
                    logger.info(f"[Router Config] Starting background configuration of router API key for {endpoint_name}")
                    router_result = configure_router_api_key(
                        kubeconfig_path=kubeconfig_path,
                        endpoint_name=endpoint_name,
                        api_key_secret_name=api_key_secret_name,
                        source_namespace=namespace,
                        router_namespace="hyperpod-inference-system",
                        max_retries=18,  # Wait up to 3 minutes for router deployment
                        retry_delay=10,
                        patch_verify_retries=15,  # Verify/re-apply patch up to 15 times (~7.5 min)
                        patch_verify_delay=30    # 30 seconds between verifications
                    )
                    if router_result.get("success"):
                        logger.info(f"[Router Config] Successfully configured router with API key for {endpoint_name}")
                    else:
                        logger.warning(f"[Router Config] Failed to configure router API key: {router_result.get('error')}")
                except Exception as e:
                    logger.error(f"[Router Config] Exception configuring router API key: {e}")

            thread = threading.Thread(target=configure_router_background, daemon=True)
            thread.start()
            logger.info(f"[Router Config] Started background thread to configure router API key for {endpoint_name}")
        elif intelligent_routing and api_key_config and api_key_config.enabled and generated_api_key:
            logger.info(f"[Router Config] Using plain value for VLLM_API_KEY - operator will copy to router automatically")

        # Patch readiness probe timeout in background (HyperPod operator defaults to 1s which is too short)
        # SGLang needs longer timeout (10s) as it takes longer to respond to health checks
        import threading
        readiness_timeout = 10 if engine.lower() == "sglang" else 5
        def patch_readiness_background():
            try:
                logger.info(f"[Readiness Patch] Starting background patch for {endpoint_name} (engine={engine}, timeout={readiness_timeout}s)")
                patch_result = patch_readiness_probe_timeout(
                    kubeconfig_path=kubeconfig_path,
                    endpoint_name=endpoint_name,
                    namespace=namespace,
                    timeout_seconds=readiness_timeout
                )
                if patch_result.get("success"):
                    logger.info(f"[Readiness Patch] Successfully patched: {patch_result.get('message')}")
                else:
                    logger.warning(f"[Readiness Patch] Failed: {patch_result.get('error')}")
            except Exception as e:
                logger.error(f"[Readiness Patch] Exception: {e}")

        readiness_thread = threading.Thread(target=patch_readiness_background, daemon=True)
        readiness_thread.start()
        logger.info(f"[Readiness Patch] Started background thread to patch readiness probe for {endpoint_name}")

        return result
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
        ingress_exists = False
        try:
            from kubernetes import client, config
            config.load_kube_config(config_file=kubeconfig_path)
            networking_api = client.NetworkingV1Api()

            # HyperPod creates Ingress in hyperpod-inference-system namespace
            ingress_namespace = "hyperpod-inference-system"
            ingress_name = f"alb-{resource_name}-{namespace}"

            ingress = networking_api.read_namespaced_ingress(name=ingress_name, namespace=ingress_namespace)
            ingress_exists = True
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
                else:
                    # Ingress exists but ALB not provisioned yet - don't fall back to stale CRD data
                    logger.info(f"Ingress {ingress_name} exists but ALB hostname not provisioned yet")
                    return None
            else:
                # Ingress exists but no load_balancer status yet - ALB still provisioning
                logger.info(f"Ingress {ingress_name} exists but load_balancer status not ready yet")
                return None
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
    timeout: int = 120,
    api_key: str = None
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
        api_key: Optional API key for authentication

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

    # Add API key to Authorization header if provided
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        logger.info(f"Using API key authentication for endpoint {endpoint_name}")

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
    timeout: int = 120,
    api_key: str = None
):
    """
    Invoke a HyperPod inference endpoint with streaming response.

    Args:
        eks_cluster_name: EKS cluster name
        endpoint_name: Name of the endpoint
        payload: Request payload (OpenAI-compatible format)
        namespace: Kubernetes namespace
        region: AWS region
        timeout: Request timeout in seconds
        api_key: Optional API key for authentication

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

    # Add API key to Authorization header if provided
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        logger.info(f"Using API key authentication for endpoint {endpoint_name}")

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

        # Remove finalizers first to allow immediate deletion
        # The ALB controller's finalizer (ingress.k8s.aws/resources) blocks deletion until
        # it cleans up AWS resources (ALB, target groups, etc.), which can take a long time
        # or fail entirely. By removing the finalizer first, we allow immediate deletion.
        # The AWS resources will be cleaned up eventually, and a new ALB will be created.
        if existing_ingress.metadata.finalizers:
            logger.info(f"Removing finalizers from Ingress {ingress_name} to allow immediate deletion...")
            try:
                networking_api.patch_namespaced_ingress(
                    name=ingress_name,
                    namespace=ingress_namespace,
                    body={"metadata": {"finalizers": None}}
                )
                logger.info(f"Finalizers removed from Ingress {ingress_name}")
            except Exception as patch_e:
                logger.warning(f"Failed to remove finalizers: {patch_e}, proceeding with deletion anyway")

        # Delete the existing Ingress
        logger.info(f"Deleting existing Ingress {ingress_name} in {ingress_namespace} to recreate with {scheme} scheme...")
        networking_api.delete_namespaced_ingress(name=ingress_name, namespace=ingress_namespace)

        # Wait for the ingress to be fully deleted
        # Since we removed the finalizer, this should be quick
        logger.info(f"Waiting for Ingress {ingress_name} to be fully deleted...")
        max_wait_seconds = max(wait_for_cleanup, 60)  # 1 minute should be enough without finalizers
        poll_interval = 2
        for i in range(max_wait_seconds // poll_interval):
            try:
                ing = networking_api.read_namespaced_ingress(name=ingress_name, namespace=ingress_namespace)
                # Check if it has a deletion timestamp (being deleted)
                if ing.metadata.deletion_timestamp:
                    logger.info(f"Ingress {ingress_name} is terminating, waiting... ({i * poll_interval}s elapsed)")
                else:
                    logger.info(f"Ingress {ingress_name} still exists without deletion timestamp, waiting...")
                time_module.sleep(poll_interval)
            except ApiException as poll_e:
                if poll_e.status == 404:
                    logger.info(f"Ingress {ingress_name} has been fully deleted after {i * poll_interval}s")
                    break
                else:
                    logger.warning(f"Error checking ingress status: {poll_e}")
                    time_module.sleep(poll_interval)
        else:
            logger.warning(f"Ingress {ingress_name} deletion timed out after {max_wait_seconds}s, proceeding anyway...")

        # Additional short wait for any remaining cleanup
        logger.info(f"Waiting additional 5s for cleanup...")
        time_module.sleep(5)

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

        # Create with retry logic for 409 conflicts
        # The old Ingress might still be terminating even after we removed the finalizer
        max_create_retries = 5
        create_retry_delay = 5
        for create_attempt in range(max_create_retries):
            try:
                logger.info(f"Creating new Ingress {ingress_name} in {ingress_namespace} with {scheme} scheme (attempt {create_attempt + 1}/{max_create_retries})...")
                networking_api.create_namespaced_ingress(namespace=ingress_namespace, body=new_ingress)
                logger.info(f"Ingress {ingress_name} created successfully")
                break
            except ApiException as create_e:
                if create_e.status == 409 and create_attempt < max_create_retries - 1:
                    # Conflict - old Ingress still exists, wait and retry
                    logger.warning(f"Ingress creation got 409 conflict, old Ingress may still be terminating. Retrying in {create_retry_delay}s...")
                    time_module.sleep(create_retry_delay)
                    create_retry_delay = min(create_retry_delay * 2, 30)  # Exponential backoff up to 30s
                else:
                    raise create_e
        else:
            # If we exhausted retries, raise an error
            raise Exception(f"Failed to create Ingress after {max_create_retries} attempts due to conflicts")

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
