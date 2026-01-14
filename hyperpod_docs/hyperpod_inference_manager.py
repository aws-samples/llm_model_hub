"""
HyperPod EKS 推理资源管理器

使用 Kubernetes Python 客户端库管理 HyperPod EKS 集群上的推理资源。
支持 JumpStartModel 和 InferenceEndpointConfig 自定义资源的 CRUD 操作。

使用示例:
    from hyperpod_inference_manager import HyperPodInferenceManager

    manager = HyperPodInferenceManager()

    # 部署 JumpStart 模型
    manager.deploy_jumpstart_model(
        name="my-model",
        model_id="deepseek-llm-r1-distill-qwen-1-5b",
        model_version="2.0.4",
        instance_type="ml.g5.xlarge"
    )

    # 部署自定义模型
    manager.deploy_custom_model(
        name="my-custom-model",
        model_name="llama-3-8b-instruct",
        instance_type="ml.g5.24xlarge",
        s3_bucket="my-bucket",
        model_location="models/llama-3-8b"
    )
"""

import time
import logging
from typing import Dict, List, Optional, Any, Generator
from dataclasses import dataclass, field

from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# 数据类定义
# ============================================================================

@dataclass
class AutoScalingConfig:
    """自动扩缩容配置"""
    min_replicas: int = 1
    max_replicas: int = 10
    metric_name: str = "Invocations"
    target_value: int = 100
    metric_collection_period: int = 60
    cooldown_period: int = 300

    def to_spec(self, endpoint_name: str) -> Dict[str, Any]:
        """转换为 Kubernetes spec 格式"""
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
    KV 缓存配置

    支持两层缓存架构:
    - L1 缓存: 本地 CPU 内存，位于每个推理节点上
    - L2 缓存: 分布式缓存层，支持 redis 或 tieredstorage (AWS 托管分层存储)

    Args:
        enable_l1_cache: 是否启用 L1 缓存 (本地 CPU 内存)
        enable_l2_cache: 是否启用 L2 缓存 (分布式缓存)
        l2_cache_backend: L2 缓存后端类型
            - "tieredstorage": AWS 托管分层存储 (推荐)，提供 TB 级容量
            - "redis": Redis 集群
        l2_cache_url: Redis 集群 URL (仅当 l2_cache_backend="redis" 时需要)
    """
    enable_l1_cache: bool = True
    enable_l2_cache: bool = False
    l2_cache_backend: str = "tieredstorage"  # tieredstorage (推荐) 或 redis
    l2_cache_url: Optional[str] = None

    def to_spec(self) -> Dict[str, Any]:
        """转换为 Kubernetes spec 格式"""
        spec: Dict[str, Any] = {
            "enableL1Cache": self.enable_l1_cache,
            "enableL2Cache": self.enable_l2_cache
        }
        if self.enable_l2_cache:
            l2_spec: Dict[str, str] = {
                "l2CacheBackend": self.l2_cache_backend
            }
            # tieredstorage 不需要 URL，只有 redis 需要
            if self.l2_cache_backend == "redis" and self.l2_cache_url:
                l2_spec["l2CacheLocalUrl"] = self.l2_cache_url
            spec["l2CacheSpec"] = l2_spec
        return spec


@dataclass
class IntelligentRoutingConfig:
    """
    智能路由配置

    智能路由通过将请求定向到具有相关缓存数据的实例来最大化缓存利用率。

    Args:
        enabled: 是否启用智能路由
        routing_strategy: 路由策略
            - "prefixaware": 基于提示前缀路由 (默认)
            - "kvaware": 实时 KV 缓存跟踪，最大化缓存命中 (与 tieredstorage 配合效果最佳)
            - "session": 基于用户会话路由，适合多轮对话
            - "roundrobin": 轮询分发，适合无状态工作负载
    """
    enabled: bool = True
    routing_strategy: str = "prefixaware"  # prefixaware, kvaware, session, roundrobin

    def to_spec(self) -> Dict[str, Any]:
        """转换为 Kubernetes spec 格式"""
        return {
            "enabled": self.enabled,
            "routingStrategy": self.routing_strategy
        }


@dataclass
class WorkerConfig:
    """Worker 容器配置"""
    image: str
    gpu_count: int = 1
    cpu_request: str = "8"
    memory_request: str = "32Gi"
    container_port: int = 8000
    environment_variables: Dict[str, str] = field(default_factory=dict)

    def to_spec(self) -> Dict[str, Any]:
        """转换为 Kubernetes spec 格式"""
        return {
            "image": self.image,
            "resources": {
                "limits": {
                    "nvidia.com/gpu": str(self.gpu_count)
                },
                "requests": {
                    "cpu": self.cpu_request,
                    "memory": self.memory_request,
                    "nvidia.com/gpu": str(self.gpu_count)
                }
            },
            "modelInvocationPort": {
                "containerPort": self.container_port,
                "name": "http"
            },
            "modelVolumeMount": {
                "name": "model-weights",
                "mountPath": "/opt/ml/model"
            },
            "environmentVariables": [
                {"name": k, "value": v} for k, v in self.environment_variables.items()
            ]
        }


# ============================================================================
# HyperPod 推理资源管理器
# ============================================================================

class HyperPodInferenceManager:
    """
    HyperPod EKS 推理资源管理器

    管理 JumpStartModel 和 InferenceEndpointConfig 自定义资源。
    """

    # CRD 配置
    INFERENCE_API_GROUP = "inference.sagemaker.aws.amazon.com"
    INFERENCE_API_VERSION = "v1"

    # JumpStartModel CRD
    JUMPSTART_MODEL_PLURAL = "jumpstartmodels"
    JUMPSTART_MODEL_KIND = "JumpStartModel"

    # InferenceEndpointConfig CRD
    INFERENCE_ENDPOINT_PLURAL = "inferenceendpointconfigs"
    INFERENCE_ENDPOINT_KIND = "InferenceEndpointConfig"

    # 默认推理容器镜像
    DEFAULT_IMAGES = {
        "vllm": "763104351884.dkr.ecr.{region}.amazonaws.com/djl-inference:0.32.0-lmi14.0.0-cu124",
        "tgi": "763104351884.dkr.ecr.{region}.amazonaws.com/huggingface-pytorch-tgi-inference:2.4.0-tgi2.3.1-gpu-py311-cu124-ubuntu22.04-v2.0"
    }

    def __init__(
        self,
        kubeconfig_path: Optional[str] = None,
        in_cluster: bool = False,
        context: Optional[str] = None
    ):
        """
        初始化推理管理器

        Args:
            kubeconfig_path: kubeconfig 文件路径，默认使用 ~/.kube/config
            in_cluster: 是否在集群内部运行
            context: kubeconfig 中的 context 名称
        """
        self._load_config(kubeconfig_path, in_cluster, context)
        self.custom_api = client.CustomObjectsApi()
        self.core_api = client.CoreV1Api()
        self.apps_api = client.AppsV1Api()

    def _load_config(
        self,
        kubeconfig_path: Optional[str],
        in_cluster: bool,
        context: Optional[str]
    ) -> None:
        """加载 Kubernetes 配置"""
        try:
            if in_cluster:
                config.load_incluster_config()
                logger.info("已加载集群内配置")
            else:
                config.load_kube_config(
                    config_file=kubeconfig_path,
                    context=context
                )
                logger.info(f"已加载 kubeconfig: {kubeconfig_path or '~/.kube/config'}")
        except Exception as e:
            logger.error(f"加载 Kubernetes 配置失败: {e}")
            raise

    # ========================================================================
    # JumpStart 模型部署
    # ========================================================================

    def deploy_jumpstart_model(
        self,
        name: str,
        model_id: str,
        model_version: str,
        instance_type: str,
        namespace: str = "default",
        endpoint_name: Optional[str] = None,
        model_hub_name: str = "SageMakerPublicHub",
        enable_metrics: bool = True,
        max_deploy_time_seconds: int = 1800,
        autoscaling: Optional[AutoScalingConfig] = None,
        labels: Optional[Dict[str, str]] = None,
        annotations: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        部署 JumpStart 模型

        Args:
            name: 资源名称
            model_id: JumpStart 模型 ID
            model_version: 模型版本
            instance_type: 实例类型 (如 ml.g5.xlarge)
            namespace: Kubernetes 命名空间
            endpoint_name: SageMaker 端点名称，默认使用 name
            model_hub_name: 模型中心名称
            enable_metrics: 是否启用指标收集
            max_deploy_time_seconds: 最大部署时间
            autoscaling: 自动扩缩容配置
            labels: Kubernetes 标签
            annotations: Kubernetes 注解

        Returns:
            创建的资源对象
        """
        endpoint_name = endpoint_name or name

        # 构建资源定义
        body = {
            "apiVersion": f"{self.INFERENCE_API_GROUP}/{self.INFERENCE_API_VERSION}",
            "kind": self.JUMPSTART_MODEL_KIND,
            "metadata": {
                "name": name,
                "namespace": namespace,
                "labels": labels or {},
                "annotations": annotations or {}
            },
            "spec": {
                "sageMakerEndpoint": {
                    "name": endpoint_name
                },
                "model": {
                    "modelHubName": model_hub_name,
                    "modelId": model_id,
                    "modelVersion": model_version
                },
                "server": {
                    "instanceType": instance_type
                },
                "metrics": {
                    "enabled": enable_metrics
                },
                "maxDeployTimeInSeconds": max_deploy_time_seconds
            }
        }

        # 添加自动扩缩容配置
        if autoscaling:
            body["spec"]["autoScalingSpec"] = autoscaling.to_spec(endpoint_name)

        try:
            result = self.custom_api.create_namespaced_custom_object(
                group=self.INFERENCE_API_GROUP,
                version=self.INFERENCE_API_VERSION,
                namespace=namespace,
                plural=self.JUMPSTART_MODEL_PLURAL,
                body=body
            )
            logger.info(f"已创建 JumpStartModel: {name}")
            return result
        except ApiException as e:
            logger.error(f"创建 JumpStartModel 失败: {e}")
            raise

    def get_jumpstart_model(
        self,
        name: str,
        namespace: str = "default"
    ) -> Optional[Dict[str, Any]]:
        """
        获取 JumpStart 模型

        Args:
            name: 资源名称
            namespace: Kubernetes 命名空间

        Returns:
            资源对象，不存在时返回 None
        """
        try:
            return self.custom_api.get_namespaced_custom_object(
                group=self.INFERENCE_API_GROUP,
                version=self.INFERENCE_API_VERSION,
                namespace=namespace,
                plural=self.JUMPSTART_MODEL_PLURAL,
                name=name
            )
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"JumpStartModel 不存在: {name}")
                return None
            raise

    def list_jumpstart_models(
        self,
        namespace: str = "default",
        label_selector: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        列出 JumpStart 模型

        Args:
            namespace: Kubernetes 命名空间，使用 "" 表示所有命名空间
            label_selector: 标签选择器

        Returns:
            资源对象列表
        """
        try:
            if namespace:
                result = self.custom_api.list_namespaced_custom_object(
                    group=self.INFERENCE_API_GROUP,
                    version=self.INFERENCE_API_VERSION,
                    namespace=namespace,
                    plural=self.JUMPSTART_MODEL_PLURAL,
                    label_selector=label_selector
                )
            else:
                result = self.custom_api.list_cluster_custom_object(
                    group=self.INFERENCE_API_GROUP,
                    version=self.INFERENCE_API_VERSION,
                    plural=self.JUMPSTART_MODEL_PLURAL,
                    label_selector=label_selector
                )
            return result.get("items", [])
        except ApiException as e:
            logger.error(f"列出 JumpStartModel 失败: {e}")
            raise

    def delete_jumpstart_model(
        self,
        name: str,
        namespace: str = "default",
        grace_period_seconds: int = 30
    ) -> bool:
        """
        删除 JumpStart 模型

        Args:
            name: 资源名称
            namespace: Kubernetes 命名空间
            grace_period_seconds: 优雅删除等待时间

        Returns:
            是否删除成功
        """
        try:
            self.custom_api.delete_namespaced_custom_object(
                group=self.INFERENCE_API_GROUP,
                version=self.INFERENCE_API_VERSION,
                namespace=namespace,
                plural=self.JUMPSTART_MODEL_PLURAL,
                name=name,
                grace_period_seconds=grace_period_seconds
            )
            logger.info(f"已删除 JumpStartModel: {name}")
            return True
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"JumpStartModel 不存在: {name}")
                return False
            raise

    def update_jumpstart_model(
        self,
        name: str,
        namespace: str = "default",
        instance_type: Optional[str] = None,
        autoscaling: Optional[AutoScalingConfig] = None
    ) -> Dict[str, Any]:
        """
        更新 JumpStart 模型配置

        Args:
            name: 资源名称
            namespace: Kubernetes 命名空间
            instance_type: 新的实例类型
            autoscaling: 新的自动扩缩容配置

        Returns:
            更新后的资源对象
        """
        # 获取当前资源
        current = self.get_jumpstart_model(name, namespace)
        if not current:
            raise ValueError(f"JumpStartModel 不存在: {name}")

        # 构建补丁
        patch = {"spec": {}}

        if instance_type:
            patch["spec"]["server"] = {"instanceType": instance_type}

        if autoscaling:
            endpoint_name = current["spec"]["sageMakerEndpoint"]["name"]
            patch["spec"]["autoScalingSpec"] = autoscaling.to_spec(endpoint_name)

        if not patch["spec"]:
            logger.info("无需更新")
            return current

        try:
            result = self.custom_api.patch_namespaced_custom_object(
                group=self.INFERENCE_API_GROUP,
                version=self.INFERENCE_API_VERSION,
                namespace=namespace,
                plural=self.JUMPSTART_MODEL_PLURAL,
                name=name,
                body=patch
            )
            logger.info(f"已更新 JumpStartModel: {name}")
            return result
        except ApiException as e:
            logger.error(f"更新 JumpStartModel 失败: {e}")
            raise

    # ========================================================================
    # 自定义模型部署
    # ========================================================================

    def deploy_custom_model(
        self,
        name: str,
        model_name: str,
        instance_type: str,
        namespace: str = "default",
        endpoint_name: Optional[str] = None,
        invocation_endpoint: str = "v1/chat/completions",
        replicas: int = 1,
        # S3 配置
        s3_bucket: Optional[str] = None,
        s3_region: Optional[str] = None,
        model_location: Optional[str] = None,
        prefetch_enabled: bool = True,
        # FSx 配置
        fsx_file_system_id: Optional[str] = None,
        # Worker 配置
        worker_config: Optional[WorkerConfig] = None,
        inference_engine: str = "vllm",  # vllm 或 tgi
        region: str = "us-west-2",
        # 高级配置
        kv_cache: Optional[KVCacheConfig] = None,
        intelligent_routing: Optional[IntelligentRoutingConfig] = None,
        autoscaling: Optional[AutoScalingConfig] = None,
        labels: Optional[Dict[str, str]] = None,
        annotations: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        部署自定义模型

        Args:
            name: 资源名称
            model_name: 模型名称
            instance_type: 实例类型
            namespace: Kubernetes 命名空间
            endpoint_name: SageMaker 端点名称
            invocation_endpoint: 调用端点路径
            replicas: 副本数
            s3_bucket: S3 存储桶名称
            s3_region: S3 区域
            model_location: 模型在存储中的位置
            prefetch_enabled: 是否启用预取
            fsx_file_system_id: FSx 文件系统 ID
            worker_config: Worker 容器配置
            inference_engine: 推理引擎 (vllm 或 tgi)
            region: AWS 区域
            kv_cache: KV 缓存配置
            intelligent_routing: 智能路由配置
            autoscaling: 自动扩缩容配置
            labels: Kubernetes 标签
            annotations: Kubernetes 注解

        Returns:
            创建的资源对象
        """
        endpoint_name = endpoint_name or f"{name}-endpoint"

        # 验证模型来源配置
        if not s3_bucket and not fsx_file_system_id:
            raise ValueError("必须指定 s3_bucket 或 fsx_file_system_id")

        # 构建模型来源配置
        model_source_config = {}
        if s3_bucket:
            model_source_config = {
                "modelSourceType": "s3",
                "s3Storage": {
                    "bucketName": s3_bucket,
                    "region": s3_region or region
                },
                "modelLocation": model_location or f"models/{model_name}",
                "prefetchEnabled": prefetch_enabled
            }
        elif fsx_file_system_id:
            model_source_config = {
                "modelSourceType": "fsx",
                "fsxStorage": {
                    "fileSystemId": fsx_file_system_id
                },
                "modelLocation": model_location or f"models/{model_name}"
            }

        # 构建 Worker 配置
        if not worker_config:
            # 使用默认配置
            image = self.DEFAULT_IMAGES.get(inference_engine, self.DEFAULT_IMAGES["vllm"])
            image = image.format(region=region)

            env_vars = {
                "SAGEMAKER_ENV": "1",
                "MODEL_CACHE_ROOT": "/opt/ml/model"
            }

            if inference_engine == "vllm":
                env_vars.update({
                    "OPTION_ROLLING_BATCH": "vllm",
                    "OPTION_TRUST_REMOTE_CODE": "true"
                })
            elif inference_engine == "tgi":
                env_vars["HF_MODEL_ID"] = "/opt/ml/model"

            worker_config = WorkerConfig(
                image=image,
                gpu_count=self._get_gpu_count(instance_type),
                cpu_request="30",
                memory_request="100Gi",
                container_port=8000 if inference_engine == "vllm" else 8080,
                environment_variables=env_vars
            )

        # 构建资源定义
        body = {
            "apiVersion": f"{self.INFERENCE_API_GROUP}/{self.INFERENCE_API_VERSION}",
            "kind": self.INFERENCE_ENDPOINT_KIND,
            "metadata": {
                "name": name,
                "namespace": namespace,
                "labels": labels or {},
                "annotations": annotations or {}
            },
            "spec": {
                "modelName": model_name,
                "endpointName": endpoint_name,
                "instanceType": instance_type,
                "invocationEndpoint": invocation_endpoint,
                "replicas": replicas,
                "modelSourceConfig": model_source_config,
                "worker": worker_config.to_spec()
            }
        }

        # 添加可选配置
        if kv_cache:
            body["spec"]["kvCacheSpec"] = kv_cache.to_spec()

        if intelligent_routing:
            body["spec"]["intelligentRoutingSpec"] = intelligent_routing.to_spec()

        if autoscaling:
            body["spec"]["autoScalingSpec"] = autoscaling.to_spec(endpoint_name)

        try:
            result = self.custom_api.create_namespaced_custom_object(
                group=self.INFERENCE_API_GROUP,
                version=self.INFERENCE_API_VERSION,
                namespace=namespace,
                plural=self.INFERENCE_ENDPOINT_PLURAL,
                body=body
            )
            logger.info(f"已创建 InferenceEndpointConfig: {name}")
            return result
        except ApiException as e:
            logger.error(f"创建 InferenceEndpointConfig 失败: {e}")
            raise

    def get_custom_model(
        self,
        name: str,
        namespace: str = "default"
    ) -> Optional[Dict[str, Any]]:
        """
        获取自定义模型

        Args:
            name: 资源名称
            namespace: Kubernetes 命名空间

        Returns:
            资源对象，不存在时返回 None
        """
        try:
            return self.custom_api.get_namespaced_custom_object(
                group=self.INFERENCE_API_GROUP,
                version=self.INFERENCE_API_VERSION,
                namespace=namespace,
                plural=self.INFERENCE_ENDPOINT_PLURAL,
                name=name
            )
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"InferenceEndpointConfig 不存在: {name}")
                return None
            raise

    def list_custom_models(
        self,
        namespace: str = "default",
        label_selector: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        列出自定义模型

        Args:
            namespace: Kubernetes 命名空间，使用 "" 表示所有命名空间
            label_selector: 标签选择器

        Returns:
            资源对象列表
        """
        try:
            if namespace:
                result = self.custom_api.list_namespaced_custom_object(
                    group=self.INFERENCE_API_GROUP,
                    version=self.INFERENCE_API_VERSION,
                    namespace=namespace,
                    plural=self.INFERENCE_ENDPOINT_PLURAL,
                    label_selector=label_selector
                )
            else:
                result = self.custom_api.list_cluster_custom_object(
                    group=self.INFERENCE_API_GROUP,
                    version=self.INFERENCE_API_VERSION,
                    plural=self.INFERENCE_ENDPOINT_PLURAL,
                    label_selector=label_selector
                )
            return result.get("items", [])
        except ApiException as e:
            logger.error(f"列出 InferenceEndpointConfig 失败: {e}")
            raise

    def delete_custom_model(
        self,
        name: str,
        namespace: str = "default",
        grace_period_seconds: int = 30
    ) -> bool:
        """
        删除自定义模型

        Args:
            name: 资源名称
            namespace: Kubernetes 命名空间
            grace_period_seconds: 优雅删除等待时间

        Returns:
            是否删除成功
        """
        try:
            self.custom_api.delete_namespaced_custom_object(
                group=self.INFERENCE_API_GROUP,
                version=self.INFERENCE_API_VERSION,
                namespace=namespace,
                plural=self.INFERENCE_ENDPOINT_PLURAL,
                name=name,
                grace_period_seconds=grace_period_seconds
            )
            logger.info(f"已删除 InferenceEndpointConfig: {name}")
            return True
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"InferenceEndpointConfig 不存在: {name}")
                return False
            raise

    def update_custom_model(
        self,
        name: str,
        namespace: str = "default",
        replicas: Optional[int] = None,
        instance_type: Optional[str] = None,
        autoscaling: Optional[AutoScalingConfig] = None
    ) -> Dict[str, Any]:
        """
        更新自定义模型配置

        Args:
            name: 资源名称
            namespace: Kubernetes 命名空间
            replicas: 新的副本数
            instance_type: 新的实例类型
            autoscaling: 新的自动扩缩容配置

        Returns:
            更新后的资源对象
        """
        # 获取当前资源
        current = self.get_custom_model(name, namespace)
        if not current:
            raise ValueError(f"InferenceEndpointConfig 不存在: {name}")

        # 构建补丁
        patch = {"spec": {}}

        if replicas is not None:
            patch["spec"]["replicas"] = replicas

        if instance_type:
            patch["spec"]["instanceType"] = instance_type

        if autoscaling:
            endpoint_name = current["spec"]["endpointName"]
            patch["spec"]["autoScalingSpec"] = autoscaling.to_spec(endpoint_name)

        if not patch["spec"]:
            logger.info("无需更新")
            return current

        try:
            result = self.custom_api.patch_namespaced_custom_object(
                group=self.INFERENCE_API_GROUP,
                version=self.INFERENCE_API_VERSION,
                namespace=namespace,
                plural=self.INFERENCE_ENDPOINT_PLURAL,
                name=name,
                body=patch
            )
            logger.info(f"已更新 InferenceEndpointConfig: {name}")
            return result
        except ApiException as e:
            logger.error(f"更新 InferenceEndpointConfig 失败: {e}")
            raise

    def scale_custom_model(
        self,
        name: str,
        replicas: int,
        namespace: str = "default"
    ) -> Dict[str, Any]:
        """
        扩缩容自定义模型

        Args:
            name: 资源名称
            replicas: 目标副本数
            namespace: Kubernetes 命名空间

        Returns:
            更新后的资源对象
        """
        return self.update_custom_model(name, namespace, replicas=replicas)

    # ========================================================================
    # Watch 和状态监控
    # ========================================================================

    def watch_jumpstart_models(
        self,
        namespace: str = "default",
        timeout_seconds: int = 300,
        label_selector: Optional[str] = None
    ) -> Generator[Dict[str, Any], None, None]:
        """
        监听 JumpStart 模型变更事件

        Args:
            namespace: Kubernetes 命名空间
            timeout_seconds: 超时时间
            label_selector: 标签选择器

        Yields:
            事件字典，包含 type (ADDED/MODIFIED/DELETED) 和 object
        """
        w = watch.Watch()
        try:
            for event in w.stream(
                self.custom_api.list_namespaced_custom_object,
                group=self.INFERENCE_API_GROUP,
                version=self.INFERENCE_API_VERSION,
                namespace=namespace,
                plural=self.JUMPSTART_MODEL_PLURAL,
                label_selector=label_selector,
                timeout_seconds=timeout_seconds
            ):
                yield {
                    "type": event["type"],
                    "object": event["object"]
                }
        except ApiException as e:
            logger.error(f"Watch JumpStartModel 失败: {e}")
            raise
        finally:
            w.stop()

    def watch_custom_models(
        self,
        namespace: str = "default",
        timeout_seconds: int = 300,
        label_selector: Optional[str] = None
    ) -> Generator[Dict[str, Any], None, None]:
        """
        监听自定义模型变更事件

        Args:
            namespace: Kubernetes 命名空间
            timeout_seconds: 超时时间
            label_selector: 标签选择器

        Yields:
            事件字典，包含 type (ADDED/MODIFIED/DELETED) 和 object
        """
        w = watch.Watch()
        try:
            for event in w.stream(
                self.custom_api.list_namespaced_custom_object,
                group=self.INFERENCE_API_GROUP,
                version=self.INFERENCE_API_VERSION,
                namespace=namespace,
                plural=self.INFERENCE_ENDPOINT_PLURAL,
                label_selector=label_selector,
                timeout_seconds=timeout_seconds
            ):
                yield {
                    "type": event["type"],
                    "object": event["object"]
                }
        except ApiException as e:
            logger.error(f"Watch InferenceEndpointConfig 失败: {e}")
            raise
        finally:
            w.stop()

    def wait_for_deployment(
        self,
        name: str,
        namespace: str = "default",
        resource_type: str = "jumpstart",  # jumpstart 或 custom
        timeout_seconds: int = 1800,
        poll_interval: int = 30
    ) -> bool:
        """
        等待部署完成

        Args:
            name: 资源名称
            namespace: Kubernetes 命名空间
            resource_type: 资源类型 (jumpstart 或 custom)
            timeout_seconds: 超时时间
            poll_interval: 轮询间隔

        Returns:
            是否部署成功
        """
        start_time = time.time()

        get_func = (
            self.get_jumpstart_model if resource_type == "jumpstart"
            else self.get_custom_model
        )

        while time.time() - start_time < timeout_seconds:
            resource = get_func(name, namespace)

            if not resource:
                logger.warning(f"资源不存在: {name}")
                return False

            status = resource.get("status", {})
            conditions = status.get("conditions", [])

            # 检查部署状态
            for condition in conditions:
                if condition.get("type") == "Ready":
                    if condition.get("status") == "True":
                        logger.info(f"部署完成: {name}")
                        return True
                    elif condition.get("status") == "False":
                        reason = condition.get("reason", "Unknown")
                        message = condition.get("message", "")
                        logger.error(f"部署失败: {name}, 原因: {reason}, 消息: {message}")
                        return False

            logger.info(f"等待部署中: {name}")
            time.sleep(poll_interval)

        logger.error(f"部署超时: {name}")
        return False

    # ========================================================================
    # 辅助方法
    # ========================================================================

    def get_pods_for_model(
        self,
        name: str,
        namespace: str = "default"
    ) -> List[Any]:
        """
        获取模型关联的 Pod

        Args:
            name: 资源名称
            namespace: Kubernetes 命名空间

        Returns:
            Pod 列表
        """
        try:
            pods = self.core_api.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"app={name}"
            )
            return pods.items
        except ApiException as e:
            logger.error(f"获取 Pod 列表失败: {e}")
            raise

    def get_pod_logs(
        self,
        name: str,
        namespace: str = "default",
        tail_lines: int = 100
    ) -> Dict[str, str]:
        """
        获取模型 Pod 日志

        Args:
            name: 资源名称
            namespace: Kubernetes 命名空间
            tail_lines: 获取最后多少行日志

        Returns:
            Pod 名称到日志的映射
        """
        pods = self.get_pods_for_model(name, namespace)
        logs = {}

        for pod in pods:
            pod_name = pod.metadata.name
            try:
                log = self.core_api.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    tail_lines=tail_lines
                )
                logs[pod_name] = log
            except ApiException as e:
                logs[pod_name] = f"获取日志失败: {e}"

        return logs

    def get_model_status(
        self,
        name: str,
        namespace: str = "default",
        resource_type: str = "jumpstart"
    ) -> Dict[str, Any]:
        """
        获取模型状态摘要

        Args:
            name: 资源名称
            namespace: Kubernetes 命名空间
            resource_type: 资源类型

        Returns:
            状态摘要字典
        """
        get_func = (
            self.get_jumpstart_model if resource_type == "jumpstart"
            else self.get_custom_model
        )

        resource = get_func(name, namespace)
        if not resource:
            return {"exists": False}

        status = resource.get("status", {})
        spec = resource.get("spec", {})

        # 获取 Pod 状态
        pods = self.get_pods_for_model(name, namespace)
        pod_statuses = []
        for pod in pods:
            pod_statuses.append({
                "name": pod.metadata.name,
                "phase": pod.status.phase,
                "ready": all(
                    c.ready for c in (pod.status.container_statuses or [])
                )
            })

        return {
            "exists": True,
            "name": name,
            "namespace": namespace,
            "resource_type": resource_type,
            "endpoint_name": (
                spec.get("sageMakerEndpoint", {}).get("name") or
                spec.get("endpointName")
            ),
            "instance_type": (
                spec.get("server", {}).get("instanceType") or
                spec.get("instanceType")
            ),
            "conditions": status.get("conditions", []),
            "pods": pod_statuses,
            "replicas": spec.get("replicas", 1)
        }

    def _get_gpu_count(self, instance_type: str) -> int:
        """根据实例类型获取 GPU 数量"""
        gpu_mapping = {
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
        }
        return gpu_mapping.get(instance_type, 1)


# ============================================================================
# 命令行接口
# ============================================================================

def main():
    """命令行入口点"""
    import argparse

    parser = argparse.ArgumentParser(description="HyperPod 推理资源管理器")
    parser.add_argument("--kubeconfig", help="kubeconfig 文件路径")
    parser.add_argument("--context", help="Kubernetes context")
    parser.add_argument("--namespace", default="default", help="命名空间")

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # list 命令
    list_parser = subparsers.add_parser("list", help="列出推理资源")
    list_parser.add_argument(
        "--type",
        choices=["jumpstart", "custom", "all"],
        default="all",
        help="资源类型"
    )

    # get 命令
    get_parser = subparsers.add_parser("get", help="获取推理资源详情")
    get_parser.add_argument("name", help="资源名称")
    get_parser.add_argument(
        "--type",
        choices=["jumpstart", "custom"],
        required=True,
        help="资源类型"
    )

    # delete 命令
    delete_parser = subparsers.add_parser("delete", help="删除推理资源")
    delete_parser.add_argument("name", help="资源名称")
    delete_parser.add_argument(
        "--type",
        choices=["jumpstart", "custom"],
        required=True,
        help="资源类型"
    )

    # deploy-jumpstart 命令
    deploy_js_parser = subparsers.add_parser(
        "deploy-jumpstart",
        help="部署 JumpStart 模型"
    )
    deploy_js_parser.add_argument("name", help="资源名称")
    deploy_js_parser.add_argument("--model-id", required=True, help="模型 ID")
    deploy_js_parser.add_argument("--model-version", required=True, help="模型版本")
    deploy_js_parser.add_argument(
        "--instance-type",
        default="ml.g5.xlarge",
        help="实例类型"
    )

    # deploy-custom 命令
    deploy_custom_parser = subparsers.add_parser(
        "deploy-custom",
        help="部署自定义模型"
    )
    deploy_custom_parser.add_argument("name", help="资源名称")
    deploy_custom_parser.add_argument("--model-name", required=True, help="模型名称")
    deploy_custom_parser.add_argument(
        "--instance-type",
        default="ml.g5.24xlarge",
        help="实例类型"
    )
    deploy_custom_parser.add_argument("--s3-bucket", help="S3 存储桶")
    deploy_custom_parser.add_argument("--model-location", help="模型位置")
    deploy_custom_parser.add_argument(
        "--engine",
        choices=["vllm", "tgi"],
        default="vllm",
        help="推理引擎"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 初始化管理器
    manager = HyperPodInferenceManager(
        kubeconfig_path=args.kubeconfig,
        context=args.context
    )

    # 执行命令
    if args.command == "list":
        if args.type in ["jumpstart", "all"]:
            print("\n=== JumpStart 模型 ===")
            models = manager.list_jumpstart_models(args.namespace)
            for m in models:
                print(f"  - {m['metadata']['name']}")

        if args.type in ["custom", "all"]:
            print("\n=== 自定义模型 ===")
            models = manager.list_custom_models(args.namespace)
            for m in models:
                print(f"  - {m['metadata']['name']}")

    elif args.command == "get":
        if args.type == "jumpstart":
            resource = manager.get_jumpstart_model(args.name, args.namespace)
        else:
            resource = manager.get_custom_model(args.name, args.namespace)

        if resource:
            import json
            print(json.dumps(resource, indent=2, default=str))
        else:
            print(f"资源不存在: {args.name}")

    elif args.command == "delete":
        if args.type == "jumpstart":
            success = manager.delete_jumpstart_model(args.name, args.namespace)
        else:
            success = manager.delete_custom_model(args.name, args.namespace)

        if success:
            print(f"已删除: {args.name}")
        else:
            print(f"删除失败或资源不存在: {args.name}")

    elif args.command == "deploy-jumpstart":
        result = manager.deploy_jumpstart_model(
            name=args.name,
            model_id=args.model_id,
            model_version=args.model_version,
            instance_type=args.instance_type,
            namespace=args.namespace
        )
        print(f"已创建 JumpStartModel: {result['metadata']['name']}")

    elif args.command == "deploy-custom":
        if not args.s3_bucket:
            print("错误: 必须指定 --s3-bucket")
            return

        result = manager.deploy_custom_model(
            name=args.name,
            model_name=args.model_name,
            instance_type=args.instance_type,
            s3_bucket=args.s3_bucket,
            model_location=args.model_location,
            inference_engine=args.engine,
            namespace=args.namespace
        )
        print(f"已创建 InferenceEndpointConfig: {result['metadata']['name']}")


if __name__ == "__main__":
    main()
