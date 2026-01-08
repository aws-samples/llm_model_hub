"""
HyperPod Deployment Management Module

This module handles deployment of inference endpoints to HyperPod EKS clusters.
It provides functions for deploying, deleting, and managing HyperPod inference endpoints
with support for advanced features like auto-scaling, KV cache, and intelligent routing.

Separated from endpoint_management.py for better code organization.
"""

import logging
import threading
from datetime import datetime
from typing import Dict, Any

import sagemaker

from db_management.database import DatabaseWrapper
from logger_config import setup_logger
from model.data_model import EndpointStatus, JobStatus, JobType
from training.jobs import sync_get_job_by_id
from utils.config import DEFAULT_REGION, default_bucket

# Initialize database and logger
database = DatabaseWrapper()
logger = setup_logger('hyperpod_deployment.py', log_file='deployment.log', level=logging.INFO)


def _get_hf_download_and_upload_model():
    """
    Lazy import of hf_download_and_upload_model to avoid circular imports.
    """
    from inference.endpoint_management import hf_download_and_upload_model
    return hf_download_and_upload_model


def deploy_hyperpod_with_hf_download_background(
    job_id: str,
    engine: str,
    instance_type: str,
    enable_lora: bool,
    model_name: str,
    hyperpod_cluster_id: str,
    hyperpod_config: dict,
    extra_params: Dict[str, Any],
    cluster_info: Any
):
    """
    Start background thread to download HuggingFace model and deploy to HyperPod.

    This function returns immediately and runs deployment in a daemon thread.

    The background thread:
    1. Creates a database record with PRECREATING status
    2. Downloads model from HuggingFace Hub
    3. Uploads model to S3
    4. Deploys to HyperPod using S3 path

    Args:
        job_id: Training job ID or 'N/A(Not finetuned)' for base models
        engine: Inference engine (vllm, sglang)
        instance_type: Instance type (e.g., ml.g5.xlarge)
        enable_lora: Whether LoRA is enabled
        model_name: HuggingFace model name (e.g., 'Qwen/Qwen2.5-1.5B-Instruct')
        hyperpod_cluster_id: HyperPod cluster ID
        hyperpod_config: HyperPod deployment config
        extra_params: Additional parameters
        cluster_info: Cluster info object from database
    """
    def background_task():
        try:
            deploy_hyperpod_with_hf_download_sync(
                job_id=job_id,
                engine=engine,
                instance_type=instance_type,
                enable_lora=enable_lora,
                model_name=model_name,
                hyperpod_cluster_id=hyperpod_cluster_id,
                hyperpod_config=hyperpod_config,
                extra_params=extra_params,
                cluster_info=cluster_info
            )
        except Exception as e:
            logger.error(f"[HyperPod Deploy Background] Thread exception: {str(e)}")

    thread = threading.Thread(target=background_task, daemon=True)
    thread.start()
    logger.info(f"[HyperPod Deploy Background] Started background thread for {model_name}")


def deploy_hyperpod_with_hf_download_sync(
    job_id: str,
    engine: str,
    instance_type: str,
    enable_lora: bool,
    model_name: str,
    hyperpod_cluster_id: str,
    hyperpod_config: dict,
    extra_params: Dict[str, Any],
    cluster_info: Any
) -> tuple[bool, str]:
    """
    Synchronous function to download HuggingFace model and deploy to HyperPod.
    Called from background thread.

    Args:
        job_id: Training job ID or 'N/A(Not finetuned)' for base models
        engine: Inference engine (vllm, sglang)
        instance_type: Instance type (e.g., ml.g5.xlarge)
        enable_lora: Whether LoRA is enabled
        model_name: HuggingFace model name
        hyperpod_cluster_id: HyperPod cluster ID
        hyperpod_config: HyperPod deployment config
        extra_params: Additional parameters
        cluster_info: Cluster info object from database

    Returns:
        Tuple of (success, endpoint_name or error message)
    """
    from inference.hyperpod_inference import (
        deploy_to_hyperpod,
        deploy_to_hyperpod_advanced,
        AutoScalingConfig,
        KVCacheConfig,
        IntelligentRoutingConfig,
        ApiKeyConfig
    )

    # Get download function
    hf_download_and_upload_model = _get_hf_download_and_upload_model()

    eks_cluster_name = cluster_info.eks_cluster_name
    region = DEFAULT_REGION

    # Get HyperPod config values
    hyperpod_config = hyperpod_config or {}
    replicas = hyperpod_config.get('replicas', 1)
    namespace = hyperpod_config.get('namespace', 'default')
    instance_count = int(extra_params.get("instance_count", 1))

    # Check if advanced features are requested
    enable_autoscaling = hyperpod_config.get('enable_autoscaling', False)
    enable_kv_cache = hyperpod_config.get('enable_kv_cache', False)
    enable_intelligent_routing = hyperpod_config.get('enable_intelligent_routing', False)
    use_public_alb = hyperpod_config.get('use_public_alb', False)
    enable_api_key = hyperpod_config.get('enable_api_key', False)
    use_advanced_deploy = enable_autoscaling or enable_kv_cache or enable_intelligent_routing or enable_api_key

    # Generate endpoint name
    # Kubernetes names have 63 char limit
    # When intelligent routing is enabled, HyperPod operator creates:
    #   - Service: {endpoint_name}-{namespace}-routing-service (adds 24 chars for "-default-routing-service")
    #   - Ingress: alb-{endpoint_name}-{namespace} (adds 12 chars for "alb--default")
    # So for intelligent routing: 63 - 24 = 39 chars max
    # For normal HyperPod: init container name is prefetch-{name}-inf (adds 13 chars: "prefetch-" is 9, "-inf" is 4)
    # So for normal HyperPod: 63 - 13 = 50 chars max
    max_name_len = 39 if enable_intelligent_routing else 50
    pure_model_name = model_name.split('/')[-1] if '/' in model_name else model_name
    create_time = datetime.now().strftime('%Y-%m-%d %H:%M')

    if extra_params.get("endpoint_name"):
        endpoint_name = extra_params.get("endpoint_name")[:max_name_len].rstrip('-')
    else:
        endpoint_name = sagemaker.utils.name_from_base(pure_model_name).replace('.', '-').replace('_', '-') + f"-{engine}-hp"
        endpoint_name = endpoint_name[:max_name_len].rstrip('-')

    # Build extra_config for database record
    extra_config_data = {
        'hyperpod_cluster_id': hyperpod_cluster_id,
        'eks_cluster_name': eks_cluster_name,
        'namespace': namespace,
        'replicas': replicas,
        'enable_autoscaling': enable_autoscaling,
        'enable_kv_cache': enable_kv_cache,
        'enable_intelligent_routing': enable_intelligent_routing,
        'use_public_alb': use_public_alb,
        'enable_api_key': enable_api_key
    }
    if enable_api_key:
        extra_config_data['api_key_source'] = hyperpod_config.get('api_key_source', 'auto')

    # Create database record with PRECREATING status (downloading model)
    logger.info(f"[HyperPod Deploy Background] Creating endpoint record: {endpoint_name}")
    database.create_endpoint(
        job_id=job_id,
        model_name=model_name,
        model_s3_path='',  # Will be updated after upload
        instance_type=instance_type,
        instance_count=instance_count,
        endpoint_name=endpoint_name,
        endpoint_create_time=create_time,
        endpoint_delete_time=None,
        extra_config=extra_config_data,
        engine=engine,
        enable_lora=enable_lora,
        endpoint_status=EndpointStatus.PRECREATING,
        deployment_target='hyperpod',
        hyperpod_cluster_id=hyperpod_cluster_id
    )

    try:
        # Download model from HuggingFace and upload to S3
        logger.info(f"[HyperPod Deploy Background] Downloading model {model_name} from HuggingFace...")
        s3_prefix = f"hyperpod_models/{model_name}"
        model_s3_path = hf_download_and_upload_model(
            model_repo=model_name,
            s3_bucket=default_bucket,
            s3_prefix=s3_prefix
        )
        logger.info(f"[HyperPod Deploy Background] Model uploaded to {model_s3_path}")

        # Update database with S3 path
        extra_config_data['model_s3_path'] = model_s3_path

        # Update status to CREATING
        logger.info(f"[HyperPod Deploy Background] Updating status to CREATING for {endpoint_name}...")
        database.update_endpoint_status(endpoint_name=endpoint_name, endpoint_status=EndpointStatus.CREATING)
        logger.info(f"[HyperPod Deploy Background] Status updated to CREATING for {endpoint_name}")

        logger.info(f"[HyperPod Deploy Background] Deploying to HyperPod cluster {eks_cluster_name}...")

        if use_advanced_deploy:
            # Build advanced configuration objects
            autoscaling_config = None
            if enable_autoscaling:
                autoscaling_config = AutoScalingConfig(
                    min_replicas=hyperpod_config.get('min_replicas', 1),
                    max_replicas=hyperpod_config.get('max_replicas', 10),
                    metric_name=hyperpod_config.get('autoscaling_metric', 'Invocations'),
                    target_value=hyperpod_config.get('autoscaling_target', 100),
                    metric_collection_period=hyperpod_config.get('metric_collection_period', 60),
                    cooldown_period=hyperpod_config.get('cooldown_period', 300)
                )

            kv_cache_config = None
            if enable_kv_cache:
                # KVCacheSpec is only supported for vLLM, not SGLang
                if engine.lower() != 'vllm':
                    logger.warning(f"[HyperPod Deploy] KV cache is only supported for vLLM engine. Engine '{engine}' does not support KV cache. Disabling KV cache.")
                else:
                    kv_cache_backend = hyperpod_config.get('kv_cache_backend', 'tieredstorage')
                    enable_l2 = hyperpod_config.get('enable_l2_cache', True) if kv_cache_backend else False
                    kv_cache_config = KVCacheConfig(
                        enable_l1_cache=hyperpod_config.get('enable_l1_cache', True),
                        enable_l2_cache=enable_l2,
                        l2_cache_backend=kv_cache_backend,
                        l2_cache_url=hyperpod_config.get('l2_cache_url')
                    )

            intelligent_routing_config = None
            if enable_intelligent_routing:
                intelligent_routing_config = IntelligentRoutingConfig(
                    enabled=True,
                    routing_strategy=hyperpod_config.get('routing_strategy', 'prefixaware')
                )

            # Build API key config if enabled
            api_key_config = None
            if enable_api_key:
                api_key_config = ApiKeyConfig(
                    enabled=True,
                    source=hyperpod_config.get('api_key_source', 'auto'),
                    custom_api_key=hyperpod_config.get('custom_api_key', ''),
                    secrets_manager_secret_name=hyperpod_config.get('secrets_manager_secret_name', '')
                )

            # Deploy with advanced configuration
            # Use same default values as SageMaker deployment for consistency
            result = deploy_to_hyperpod_advanced(
                eks_cluster_name=eks_cluster_name,
                endpoint_name=endpoint_name,
                model_name=model_name,
                instance_type=instance_type,
                engine=engine,
                replicas=replicas,
                instance_count=instance_count,  # For per-replica resource allocation
                namespace=namespace,
                region=region,
                model_s3_path=model_s3_path,
                huggingface_model_id=None,  # Using S3 path instead
                autoscaling=autoscaling_config,
                kv_cache=kv_cache_config,
                intelligent_routing=intelligent_routing_config,
                api_key_config=api_key_config,
                tensor_parallel_size=extra_params.get('tensor_parallel_size'),
                max_model_len=extra_params.get('max_model_len', 12288),  # Default 12288 like SageMaker
                enable_prefix_caching=extra_params.get('enable_prefix_caching', False),
                gpu_memory_utilization=extra_params.get('mem_fraction_static', 0.9),  # Default 0.9
                chat_template=extra_params.get('chat_template'),
                tool_call_parser=extra_params.get('tool_call_parser'),
                limit_mm_per_prompt=extra_params.get('limit_mm_per_prompt'),
                enforce_eager=extra_params.get('enforce_eager', False),
                max_num_seqs=extra_params.get('max_num_seqs'),
                dtype=extra_params.get('dtype'),
                trust_remote_code=extra_params.get('trust_remote_code', True)
            )
        else:
            # Deploy with basic configuration
            result = deploy_to_hyperpod(
                eks_cluster_name=eks_cluster_name,
                endpoint_name=endpoint_name,
                model_name=model_name,
                instance_type=instance_type,
                engine=engine,
                replicas=replicas,
                instance_count=instance_count,  # For per-replica resource allocation
                namespace=namespace,
                region=region,
                model_s3_path=model_s3_path,
                huggingface_model_id=None  # Using S3 path instead
            )

        if result.get('success'):
            logger.info(f"[HyperPod Deploy Background] Deployment initiated successfully: {endpoint_name}")

            # Update extra_config with API key if generated
            if enable_api_key and result.get('api_key'):
                extra_config_data['api_key'] = result.get('api_key')
                logger.info(f"[HyperPod Deploy Background] API key stored in endpoint config")
                # Update the endpoint record with the API key (keep status as CREATING)
                import json as json_module
                database.update_endpoint_status(
                    endpoint_name=endpoint_name,
                    endpoint_status=EndpointStatus.CREATING,
                    extra_config=json_module.dumps(extra_config_data)
                )

            # Configure public ALB if requested using recreate approach
            # Note: Public ALB requires intelligent routing to be enabled
            if use_public_alb:
                if not enable_intelligent_routing:
                    logger.warning(f"[HyperPod Deploy Background] Public ALB requested but intelligent routing is disabled. "
                                   f"Ingress is only created when intelligent routing is enabled. "
                                   f"Skipping public ALB configuration for {endpoint_name}. "
                                   f"To use public ALB, please enable intelligent routing.")
                else:
                    logger.info(f"[HyperPod Deploy Background] Scheduling public ALB configuration (recreate approach)...")
                    import time as time_module
                    from inference.hyperpod_inference import recreate_ingress_with_scheme

                    # Retry ALB configuration with exponential backoff
                    # HyperPod operator can take 10-15+ minutes to create Ingress
                    # Use 12 retries with delays up to 120s = ~22 minutes total coverage
                    max_retries = 12
                    retry_delay = 60
                    alb_configured = False

                    for attempt in range(max_retries):
                        logger.info(f"[HyperPod Deploy Background] Waiting {retry_delay}s before ALB configuration (attempt {attempt + 1}/{max_retries})...")
                        time_module.sleep(retry_delay)

                        alb_result = recreate_ingress_with_scheme(
                            eks_cluster_name=eks_cluster_name,
                            endpoint_name=endpoint_name,
                            namespace=namespace,
                            region=region or DEFAULT_REGION,
                            internet_facing=True,
                            wait_for_cleanup=60
                        )

                        if alb_result.get('success'):
                            alb_hostname = alb_result.get('alb_hostname')
                            logger.info(f"[HyperPod Deploy Background] Public ALB configured: {alb_hostname}")
                            alb_configured = True

                            # Update database with the new public ALB URL
                            if alb_hostname:
                                try:
                                    import json as json_module
                                    extra_config_data['alb_url'] = f"https://{alb_hostname}/v1/chat/completions"
                                    extra_config_data['endpoint_url'] = alb_hostname
                                    database.update_endpoint_status(
                                        endpoint_name=endpoint_name,
                                        endpoint_status=EndpointStatus.CREATING,  # Keep current status
                                        extra_config=json_module.dumps(extra_config_data)
                                    )
                                    logger.info(f"[HyperPod Deploy Background] Database updated with public ALB URL: {alb_hostname}")
                                except Exception as db_e:
                                    logger.warning(f"[HyperPod Deploy Background] Failed to update database with ALB URL: {db_e}")
                            break
                        else:
                            error = alb_result.get('error', 'Unknown error')
                            if 'not found' in error.lower() and attempt < max_retries - 1:
                                logger.info(f"[HyperPod Deploy Background] Ingress not ready yet (attempt {attempt + 1}/{max_retries}), will retry...")
                                retry_delay = min(retry_delay * 1.5, 120)  # cap at 120s for ~22min total coverage
                            else:
                                logger.warning(f"[HyperPod Deploy Background] ALB configuration attempt {attempt + 1} failed: {error}")

                    if not alb_configured:
                        logger.warning(f"[HyperPod Deploy Background] Failed to configure public ALB after {max_retries} attempts. HyperPod operator may still be setting up. Check ingress manually.")

            return True, endpoint_name
        else:
            error_msg = result.get('message', 'Unknown error')
            logger.error(f"[HyperPod Deploy Background] Deployment failed: {error_msg}")
            extra_config_data['error'] = f"DeploymentFailed: {error_msg}"
            database.update_endpoint_status(endpoint_name=endpoint_name, endpoint_status=EndpointStatus.FAILED)
            return False, error_msg

    except Exception as e:
        import traceback
        error_msg = str(e)
        logger.error(f"[HyperPod Deploy Background] Exception: {error_msg}")
        logger.error(f"[HyperPod Deploy Background] Traceback: {traceback.format_exc()}")
        database.update_endpoint_status(endpoint_name=endpoint_name, endpoint_status=EndpointStatus.FAILED)
        return False, error_msg


def deploy_endpoint_hyperpod(
    job_id: str,
    engine: str,
    instance_type: str,
    enable_lora: bool,
    model_name: str,
    hyperpod_cluster_id: str,
    hyperpod_config: dict,
    extra_params: Dict[str, Any]
) -> tuple[bool, str]:
    """
    Deploy model to HyperPod EKS cluster.

    Supports advanced features from the HyperPod Inference Operator:
    - Auto-scaling based on CloudWatch metrics via KEDA
    - KV Cache for optimized inference
    - Intelligent routing for request distribution

    Args:
        job_id: Job ID for finetuned model, or 'N/A(Not finetuned)' for base models
        engine: Inference engine (vllm, sglang)
        instance_type: Instance type (e.g., ml.g5.xlarge)
        enable_lora: Whether LoRA is enabled
        model_name: Model name
        hyperpod_cluster_id: HyperPod cluster ID
        hyperpod_config: HyperPod deployment config containing:
            - replicas: Number of replicas
            - namespace: Kubernetes namespace
            - enable_autoscaling: Enable auto-scaling
            - min_replicas: Min replicas for autoscaling
            - max_replicas: Max replicas for autoscaling
            - enable_kv_cache: Enable KV cache
            - kv_cache_backend: KV cache backend (tieredstorage, redis)
            - enable_intelligent_routing: Enable intelligent routing
            - routing_strategy: Routing strategy (prefixaware, kvaware, session, roundrobin)
        extra_params: Additional parameters

    Returns:
        Tuple of (success, message/endpoint_name)
    """
    from inference.hyperpod_inference import (
        deploy_to_hyperpod,
        deploy_to_hyperpod_advanced,
        AutoScalingConfig,
        KVCacheConfig,
        IntelligentRoutingConfig,
        ApiKeyConfig
    )

    logger.info(f"[HyperPod Deploy] Starting deployment - job_id={job_id}, model_name={model_name}, "
                f"engine={engine}, instance_type={instance_type}, enable_lora={enable_lora}")
    logger.info(f"[HyperPod Deploy] hyperpod_cluster_id={hyperpod_cluster_id}")
    logger.info(f"[HyperPod Deploy] hyperpod_config={hyperpod_config}")
    logger.info(f"[HyperPod Deploy] extra_params={extra_params}")

    # Get cluster info from database
    cluster_info = database.get_cluster_by_id(hyperpod_cluster_id)
    if not cluster_info:
        logger.error(f"[HyperPod Deploy] Cluster not found: {hyperpod_cluster_id}")
        return False, f"Cluster not found: {hyperpod_cluster_id}"

    eks_cluster_name = cluster_info.eks_cluster_name
    region = DEFAULT_REGION
    logger.info(f"[HyperPod Deploy] Found cluster - eks_cluster_name={eks_cluster_name}, region={region}")

    # Check instance availability before deployment
    instance_groups = cluster_info.instance_groups or []
    available_instance_count = 0
    for ig in instance_groups:
        if isinstance(ig, dict) and ig.get('instance_type') == instance_type:
            available_instance_count += ig.get('instance_count', 0)

    if available_instance_count == 0:
        available_types = [ig.get('instance_type') for ig in instance_groups if isinstance(ig, dict)]
        error_msg = (
            f"Instance type '{instance_type}' is not available in cluster '{cluster_info.cluster_name}'. "
            f"Available instance types: {available_types}. "
            f"Please select an available instance type or add a new instance group to the cluster."
        )
        logger.error(f"[HyperPod Deploy] {error_msg}")
        return False, error_msg

    # Count currently deployed endpoints using this instance type on this cluster
    deployed_endpoint_count = database.count_hyperpod_endpoints_by_cluster_and_instance(
        hyperpod_cluster_id, instance_type
    )
    logger.info(f"[HyperPod Deploy] Instance availability check: "
                f"instance_type={instance_type}, available={available_instance_count}, deployed={deployed_endpoint_count}")

    if deployed_endpoint_count >= available_instance_count:
        existing_endpoints = database.get_hyperpod_endpoints_by_cluster(hyperpod_cluster_id)
        existing_endpoints_on_type = [ep[0] for ep in existing_endpoints if ep[1] == instance_type]
        error_msg = (
            f"No available instances of type '{instance_type}' in cluster '{cluster_info.cluster_name}'. "
            f"All {available_instance_count} instance(s) are currently in use by: {existing_endpoints_on_type}. "
            f"Please either: (1) Delete an existing endpoint, or (2) Add more instances of type '{instance_type}' to the cluster."
        )
        logger.error(f"[HyperPod Deploy] {error_msg}")
        return False, error_msg

    # Determine model path (S3 or HuggingFace)
    model_path = ''
    huggingface_model_id = None

    if job_id != 'N/A(Not finetuned)':
        # Finetuned model from S3
        jobinfo = sync_get_job_by_id(job_id)
        if not jobinfo.job_status == JobStatus.SUCCESS:
            return False, "Job is not ready to deploy"

        if jobinfo.job_type in [JobType.grpo, JobType.dapo, JobType.gspo, JobType.cispo]:
            model_path = jobinfo.output_s3_path + 'huggingface/'
        else:
            if jobinfo.job_payload.get('finetuning_method') == 'lora':
                model_path = jobinfo.output_s3_path + 'finetuned_model_merged/'
            else:
                model_path = jobinfo.output_s3_path + 'finetuned_model/'
    elif extra_params.get("s3_model_path"):
        # Custom S3 model path
        model_path = extra_params.get("s3_model_path")
        model_name = model_name or 'custom/custom_model_in_s3'
    elif model_name:
        # HuggingFace model - need to download and upload to S3 first
        logger.info(f"[HyperPod Deploy] HuggingFace model detected: {model_name}")
        logger.info(f"[HyperPod Deploy] Starting background download and deployment...")

        deploy_hyperpod_with_hf_download_background(
            job_id=job_id,
            engine=engine,
            instance_type=instance_type,
            enable_lora=enable_lora,
            model_name=model_name,
            hyperpod_cluster_id=hyperpod_cluster_id,
            hyperpod_config=hyperpod_config,
            extra_params=extra_params,
            cluster_info=cluster_info
        )
        return True, "Downloading model from HuggingFace and deploying in background. Check endpoint status for progress."
    else:
        return False, "No model specified. Please provide a model name or S3 model path."

    # Get HyperPod config values
    hyperpod_config = hyperpod_config or {}
    replicas = hyperpod_config.get('replicas', 1)
    namespace = hyperpod_config.get('namespace', 'default')
    instance_count = int(extra_params.get("instance_count", 1))

    # Check if advanced features are requested
    enable_autoscaling = hyperpod_config.get('enable_autoscaling', False)
    enable_kv_cache = hyperpod_config.get('enable_kv_cache', False)
    enable_intelligent_routing = hyperpod_config.get('enable_intelligent_routing', False)
    enable_api_key = hyperpod_config.get('enable_api_key', False)

    # Generate endpoint name
    max_name_len = 39 if enable_intelligent_routing else 50
    pure_model_name = model_name.split('/')[-1] if '/' in model_name else model_name
    create_time = datetime.now().strftime('%Y-%m-%d %H:%M')

    if extra_params.get("endpoint_name"):
        endpoint_name = extra_params.get("endpoint_name")[:max_name_len].rstrip('-')
    else:
        endpoint_name = sagemaker.utils.name_from_base(pure_model_name).replace('.', '-').replace('_', '-') + f"-{engine}-hp"
        endpoint_name = endpoint_name[:max_name_len].rstrip('-')

    use_public_alb = hyperpod_config.get('use_public_alb', False)
    use_advanced_deploy = enable_autoscaling or enable_kv_cache or enable_intelligent_routing or enable_api_key

    logger.info(f"[HyperPod Deploy] Deploying to HyperPod cluster {eks_cluster_name}: "
                f"endpoint={endpoint_name}, model={model_name}, s3_path={model_path}, "
                f"hf_model={huggingface_model_id}, replicas={replicas}, namespace={namespace}, "
                f"use_advanced_deploy={use_advanced_deploy}, use_public_alb={use_public_alb}")

    try:
        if use_advanced_deploy:
            # Build advanced configuration objects
            autoscaling_config = None
            if enable_autoscaling:
                autoscaling_config = AutoScalingConfig(
                    min_replicas=hyperpod_config.get('min_replicas', 1),
                    max_replicas=hyperpod_config.get('max_replicas', 10),
                    metric_name=hyperpod_config.get('autoscaling_metric', 'Invocations'),
                    target_value=hyperpod_config.get('autoscaling_target', 100),
                    metric_collection_period=hyperpod_config.get('metric_collection_period', 60),
                    cooldown_period=hyperpod_config.get('cooldown_period', 300)
                )
                logger.info(f"Autoscaling enabled: min={autoscaling_config.min_replicas}, max={autoscaling_config.max_replicas}")

            kv_cache_config = None
            if enable_kv_cache:
                # KVCacheSpec is only supported for vLLM, not SGLang
                if engine.lower() not in ['vllm', 'auto']:
                    logger.warning(f"[HyperPod Deploy] KV cache is only supported for vLLM engine. Engine '{engine}' does not support KV cache. Disabling KV cache.")
                else:
                    kv_cache_backend = hyperpod_config.get('kv_cache_backend', 'tieredstorage')
                    enable_l2 = hyperpod_config.get('enable_l2_cache', True) if kv_cache_backend else False
                    kv_cache_config = KVCacheConfig(
                        enable_l1_cache=hyperpod_config.get('enable_l1_cache', True),
                        enable_l2_cache=enable_l2,
                        l2_cache_backend=kv_cache_backend,
                        l2_cache_url=hyperpod_config.get('l2_cache_url')
                    )
                    logger.info(f"KV Cache enabled: L1={kv_cache_config.enable_l1_cache}, L2={kv_cache_config.enable_l2_cache}, backend={kv_cache_backend}")

            intelligent_routing_config = None
            if enable_intelligent_routing:
                intelligent_routing_config = IntelligentRoutingConfig(
                    enabled=True,
                    routing_strategy=hyperpod_config.get('routing_strategy', 'prefixaware')
                )
                logger.info(f"Intelligent routing enabled: strategy={intelligent_routing_config.routing_strategy}")

            api_key_config = None
            if enable_api_key:
                api_key_config = ApiKeyConfig(
                    enabled=True,
                    source=hyperpod_config.get('api_key_source', 'auto'),
                    custom_api_key=hyperpod_config.get('custom_api_key', ''),
                    secrets_manager_secret_name=hyperpod_config.get('secrets_manager_secret_name', '')
                )
                logger.info(f"API key authentication enabled: source={api_key_config.source}")

            # Deploy with advanced configuration
            # Use same default values as SageMaker deployment for consistency
            result = deploy_to_hyperpod_advanced(
                eks_cluster_name=eks_cluster_name,
                endpoint_name=endpoint_name,
                model_name=model_name,
                instance_type=instance_type,
                engine=engine,
                replicas=replicas,
                instance_count=instance_count,  # For per-replica resource allocation
                namespace=namespace,
                region=region,
                model_s3_path=model_path,
                huggingface_model_id=huggingface_model_id,
                autoscaling=autoscaling_config,
                kv_cache=kv_cache_config,
                intelligent_routing=intelligent_routing_config,
                api_key_config=api_key_config,
                tensor_parallel_size=extra_params.get('tensor_parallel_size'),
                max_model_len=extra_params.get('max_model_len', 12288),  # Default 12288 like SageMaker
                enable_prefix_caching=extra_params.get('enable_prefix_caching', False),
                gpu_memory_utilization=extra_params.get('mem_fraction_static', 0.9),  # Default 0.9
                chat_template=extra_params.get('chat_template'),
                tool_call_parser=extra_params.get('tool_call_parser'),
                limit_mm_per_prompt=extra_params.get('limit_mm_per_prompt'),
                enforce_eager=extra_params.get('enforce_eager', False),
                max_num_seqs=extra_params.get('max_num_seqs'),
                dtype=extra_params.get('dtype'),
                trust_remote_code=extra_params.get('trust_remote_code', True)
            )
        else:
            # Deploy with basic configuration
            result = deploy_to_hyperpod(
                eks_cluster_name=eks_cluster_name,
                endpoint_name=endpoint_name,
                model_name=model_name,
                instance_type=instance_type,
                engine=engine,
                replicas=replicas,
                instance_count=instance_count,  # For per-replica resource allocation
                namespace=namespace,
                region=region,
                model_s3_path=model_path,
                huggingface_model_id=huggingface_model_id
            )

        logger.info(f"[HyperPod Deploy] Deployment result: {result}")

        if result.get('success'):
            # Build extra_config with all settings
            extra_config_data = {
                'hyperpod_cluster_id': hyperpod_cluster_id,
                'eks_cluster_name': eks_cluster_name,
                'namespace': namespace,
                'replicas': replicas,
                'enable_autoscaling': enable_autoscaling,
                'enable_kv_cache': enable_kv_cache,
                'enable_intelligent_routing': enable_intelligent_routing,
                'use_public_alb': use_public_alb
            }
            if enable_autoscaling:
                extra_config_data['min_replicas'] = hyperpod_config.get('min_replicas', 1)
                extra_config_data['max_replicas'] = hyperpod_config.get('max_replicas', 10)
            if enable_kv_cache:
                extra_config_data['kv_cache_backend'] = hyperpod_config.get('kv_cache_backend', 'tieredstorage')
            if enable_intelligent_routing:
                extra_config_data['routing_strategy'] = hyperpod_config.get('routing_strategy', 'prefixaware')
            if enable_api_key:
                extra_config_data['enable_api_key'] = True
                extra_config_data['api_key_source'] = hyperpod_config.get('api_key_source', 'auto')
                if result.get('api_key'):
                    extra_config_data['api_key'] = result.get('api_key')
                    logger.info(f"[HyperPod Deploy] API key stored in endpoint config")

            # Create database record
            database.create_endpoint(
                job_id=job_id,
                model_name=model_name,
                model_s3_path=model_path,
                instance_type=instance_type,
                instance_count=instance_count,
                endpoint_name=endpoint_name,
                endpoint_create_time=create_time,
                endpoint_delete_time=None,
                extra_config=extra_config_data,
                engine=engine,
                enable_lora=enable_lora,
                endpoint_status=EndpointStatus.CREATING,
                deployment_target='hyperpod',
                hyperpod_cluster_id=hyperpod_cluster_id
            )

            # Configure public ALB if requested
            if use_public_alb:
                if not enable_intelligent_routing:
                    logger.warning(f"[HyperPod Deploy] Public ALB requested but intelligent routing is disabled. "
                                   f"Ingress is only created when intelligent routing is enabled. "
                                   f"Skipping public ALB configuration for {endpoint_name}. "
                                   f"To use public ALB, please enable intelligent routing.")
                else:
                    logger.info(f"[HyperPod Deploy] Scheduling public ALB configuration for {endpoint_name} (recreate approach)")
                    from inference.hyperpod_inference import recreate_ingress_with_scheme
                    import time as time_module

                    def configure_public_alb_background():
                        """Configure public ALB in background after Ingress is created."""
                        try:
                            # HyperPod operator can take 10-15+ minutes to create Ingress
                            # Use 12 retries with delays up to 120s = ~22 minutes total coverage
                            max_retries = 12
                            retry_delay = 60
                            alb_configured = False

                            for attempt in range(max_retries):
                                logger.info(f"[Background ALB] Waiting {retry_delay}s before ALB configuration (attempt {attempt + 1}/{max_retries})...")
                                time_module.sleep(retry_delay)

                                alb_result = recreate_ingress_with_scheme(
                                    eks_cluster_name=eks_cluster_name,
                                    endpoint_name=endpoint_name,
                                    namespace=namespace,
                                    region=region or DEFAULT_REGION,
                                    internet_facing=True,
                                    wait_for_cleanup=60
                                )

                                if alb_result.get('success'):
                                    alb_hostname = alb_result.get('alb_hostname')
                                    logger.info(f"[Background ALB] Public ALB configured successfully: {alb_hostname}")
                                    alb_configured = True

                                    # Update database with the new public ALB URL
                                    if alb_hostname:
                                        try:
                                            import json as json_module
                                            extra_config_data['alb_url'] = f"https://{alb_hostname}/v1/chat/completions"
                                            extra_config_data['endpoint_url'] = alb_hostname
                                            database.update_endpoint_status(
                                                endpoint_name=endpoint_name,
                                                endpoint_status=EndpointStatus.CREATING,  # Keep current status
                                                extra_config=json_module.dumps(extra_config_data)
                                            )
                                            logger.info(f"[Background ALB] Database updated with public ALB URL: {alb_hostname}")
                                        except Exception as db_e:
                                            logger.warning(f"[Background ALB] Failed to update database with ALB URL: {db_e}")
                                    break
                                else:
                                    error = alb_result.get('error', 'Unknown error')
                                    if 'not found' in error.lower() and attempt < max_retries - 1:
                                        logger.info(f"[Background ALB] Ingress not ready yet (attempt {attempt + 1}/{max_retries}), will retry...")
                                        retry_delay = min(retry_delay * 1.5, 120)  # cap at 120s for ~22min total coverage
                                    else:
                                        logger.warning(f"[Background ALB] ALB configuration attempt {attempt + 1} failed: {error}")

                            if not alb_configured:
                                logger.warning(f"[Background ALB] Failed to configure public ALB after {max_retries} attempts. HyperPod operator may still be setting up. Check ingress manually.")
                        except Exception as e:
                            logger.error(f"[Background ALB] Error configuring public ALB: {e}")

                    alb_thread = threading.Thread(target=configure_public_alb_background, daemon=True)
                    alb_thread.start()

            return True, endpoint_name
        elif result.get('error') == 'CRD_NOT_FOUND':
            # Auto-setup the inference operator in background
            logger.info(f"CRD not found on cluster {eks_cluster_name}, starting background operator setup...")
            try:
                from inference.hyperpod_operator_setup import setup_inference_operator

                hyperpod_cluster_arn = cluster_info.hyperpod_cluster_arn

                def background_setup():
                    """Run operator setup in background thread."""
                    try:
                        logger.info(f"[Background] Starting HyperPod Inference Operator setup for {eks_cluster_name}...")
                        setup_success, setup_msg = setup_inference_operator(
                            eks_cluster_name=eks_cluster_name,
                            hyperpod_cluster_name=cluster_info.cluster_name,
                            hyperpod_cluster_arn=hyperpod_cluster_arn,
                            region=region,
                            account_id=None
                        )
                        if setup_success:
                            logger.info(f"[Background] HyperPod Inference Operator setup completed: {setup_msg}")
                        else:
                            logger.error(f"[Background] HyperPod Inference Operator setup failed: {setup_msg}")
                    except Exception as e:
                        logger.error(f"[Background] HyperPod Inference Operator setup error: {e}")

                setup_thread = threading.Thread(target=background_setup, daemon=True)
                setup_thread.start()

                return False, (
                    "HyperPod Inference Operator is being installed in the background. "
                    "This process takes 5-10 minutes. Please check the logs at backend/logs/hyperpod_operator_setup.log "
                    "and retry deployment after the setup completes."
                )
            except Exception as setup_error:
                logger.error(f"Failed to start background operator setup: {setup_error}")
                return False, f"CRD not found and auto-setup failed: {setup_error}. Please install the HyperPod Inference Operator manually."
        else:
            error_msg = result.get('message', 'Unknown error')
            status_code = result.get('status_code', 'N/A')
            logger.error(f"[HyperPod Deploy] Deployment failed - status_code={status_code}, message={error_msg}")
            logger.error(f"[HyperPod Deploy] Full error result: {result}")
            return False, error_msg

    except Exception as e:
        import traceback
        logger.error(f"[HyperPod Deploy] Exception during deployment: {e}")
        logger.error(f"[HyperPod Deploy] Traceback: {traceback.format_exc()}")
        return False, str(e)


def delete_endpoint_hyperpod(endpoint_name: str, hyperpod_cluster_id: str, namespace: str = "default") -> tuple[bool, str]:
    """
    Delete a HyperPod inference endpoint.

    Args:
        endpoint_name: Name of the endpoint to delete
        hyperpod_cluster_id: HyperPod cluster ID
        namespace: Kubernetes namespace

    Returns:
        Tuple of (success, message)
    """
    from inference.hyperpod_inference import delete_hyperpod_endpoint

    # Get cluster info
    cluster_info = database.get_cluster_by_id(hyperpod_cluster_id)
    if not cluster_info:
        # Cluster deleted, just remove DB record
        database.delete_endpoint(endpoint_name=endpoint_name)
        return True, "Endpoint record deleted (cluster not found)"

    eks_cluster_name = cluster_info.eks_cluster_name

    try:
        success = delete_hyperpod_endpoint(
            eks_cluster_name=eks_cluster_name,
            endpoint_name=endpoint_name,
            namespace=namespace,
            region=DEFAULT_REGION
        )

        if success:
            database.delete_endpoint(endpoint_name=endpoint_name)
            return True, "Endpoint deleted successfully"
        else:
            return False, "Failed to delete endpoint from cluster"

    except Exception as e:
        logger.error(f"Failed to delete HyperPod endpoint: {e}")
        return False, str(e)
