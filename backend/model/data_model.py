import sys
import warnings
from typing import Annotated, Sequence, TypedDict, Dict, Optional,List, Any,TypedDict,Literal
from enum import Enum
from datetime import datetime
from pydantic import BaseModel,Field, field_validator


sys.path.append('./')

# HyperPod Instance Type Pod Limits
# Instances with single ENI have very limited pod capacity (~14 pods max)
# Base HyperPod components + inference operator + KEDA require 15+ pods
# These instance types are NOT recommended for HyperPod EKS clusters
HYPERPOD_LOW_POD_CAPACITY_INSTANCES = {
    # ml.g5 family - xlarge and 2xlarge have single ENI (14 pods max)
    'ml.g5.xlarge': 14,
    'ml.g5.2xlarge': 14,
    # ml.g4dn family - xlarge and 2xlarge have single ENI
    'ml.g4dn.xlarge': 14,
    'ml.g4dn.2xlarge': 14,
    # ml.p3 family - 2xlarge has limited capacity
    'ml.p3.2xlarge': 14,
}

# Minimum recommended instance types for HyperPod (4xlarge or larger recommended)
HYPERPOD_RECOMMENDED_MIN_INSTANCES = [
    'ml.g5.4xlarge',    # 29 pods max, 1 GPU
    'ml.g5.8xlarge',    # 58 pods max, 1 GPU
    'ml.g5.12xlarge',   # 58 pods max, 4 GPUs
    'ml.g5.24xlarge',   # 234 pods max, 4 GPUs
    'ml.g5.48xlarge',   # 234 pods max, 8 GPUs
    'ml.p4d.24xlarge',  # 234 pods max, 8 GPUs
    'ml.p4de.24xlarge', # 234 pods max, 8 GPUs
    'ml.p5.48xlarge',   # 234 pods max, 8 GPUs
]

#create an enum for job_type, with [sft,pt]

class JobType(Enum):
    sft = 'sft'
    pt = 'pt'
    ppo = 'ppo'
    dpo = 'dpo'
    kto = 'kto'
    rm = 'rm'
    grpo = 'grpo'
    dapo = 'dapo'
    gspo = 'gspo'
    cispo = 'cispo'

class EndpointStatus(Enum):
    PRECREATING = "PRECREATING"
    CREATING = "CREATING"
    INSERVICE = "INSERVICE"
    FAILED = "FAILED"
    DELETING = "DELETING"
    TERMINATED = "TERMINATED"
    NOTFOUND = 'NOTFOUND'

class JobStatus(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    CREATING = "CREATING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    TERMINATED = "TERMINATED"
    TERMINATING = "TERMINATING"
    STOPPED = "STOPPED"
    
class FetchLogRequest(BaseModel):
    # job_run_name:str
    job_id:str
    next_token:Optional[str] = None
    
class FetchLogResponse(BaseModel):
    response_id:str
    log_events:List[str]
    next_backward_token:Optional[str] = None
    next_forward_token:Optional[str] = None
    
class CreateJobsRequest(BaseModel):
    request_id:Optional[str] = ''
    # job_type : Literal["sft","pt"] = Field(default="sft")
    job_type : JobType  = Field(default=JobType.sft)
    job_name: str
    job_payload: Dict[str,Any]
    
class JobInfo(BaseModel):
    job_id:str
    job_name: str
    job_run_name:str
    output_s3_path: str
    job_type : JobType
    job_status : JobStatus
    job_payload : Dict[str,Any]
    job_create_time: Optional[datetime] = None
    job_start_time:Optional[datetime] = None
    job_end_time:Optional[datetime] = None
    error_message: Optional[str] = None  # Detailed error message when job fails
    ts:int

class JobStatusResponse(BaseModel):
    response_id:str
    job_status:JobStatus
    
class ListJobsRequest(BaseModel):
    page_size : int = 20
    page_index : Optional[int] = Field(default=1)
    query_terms : Optional[Dict[str,Any]] =  Field(default=None)
    
class GetJobsRequest(BaseModel):
    job_id:str
    
class DelJobsRequest(BaseModel):
    job_id:str

class JobsResponse(BaseModel):
    response_id:str
    body:JobInfo

class ListJobsResponse(BaseModel):
    response_id:str
    jobs :List[JobInfo]
    total_count:int
    
class CommonResponse(BaseModel):
    response_id:str
    response:Dict[str,Any]
    
class GetFactoryConfigRequest(BaseModel):
    config_name:Literal["model_name","prompt_template","dataset"] 
    stage:Optional[str] = Literal["sft","ppo","dpo","kto","grpo","dapo","gspo","cispo"] 
    
class ListModelNamesResponse(BaseModel):
    response_id:str
    model_names:List[str]
    
class ListS3ObjectsRequest(BaseModel):
    output_s3_path:str
    
class S3ObjectsResponse(BaseModel):
    response_id:str
    objects:List[Dict[str,Any]]
    
class HyperPodDeployConfig(BaseModel):
    """Configuration for HyperPod deployment with advanced features"""
    # Basic configuration
    replicas: int = 1
    namespace: str = "default"

    # Auto-scaling configuration (KEDA-based)
    enable_autoscaling: bool = False
    min_replicas: int = 1
    max_replicas: int = 10
    autoscaling_metric: str = "Invocations"  # CloudWatch metric name
    autoscaling_target: int = 100  # Target value for metric
    metric_collection_period: int = 60  # seconds
    cooldown_period: int = 300  # seconds

    # KV Cache configuration
    enable_kv_cache: bool = False
    enable_l1_cache: bool = True  # Local CPU memory cache
    enable_l2_cache: bool = True  # Distributed cache (enabled by default when KV cache is on)
    kv_cache_backend: str = "tieredstorage"  # "tieredstorage" or "redis"
    l2_cache_url: Optional[str] = None  # Required for redis backend

    # Intelligent Routing configuration
    enable_intelligent_routing: bool = False
    routing_strategy: str = "prefixaware"  # "prefixaware", "kvaware", "session", "roundrobin"

    # ALB configuration
    use_public_alb: bool = False  # If True, configure ALB as internet-facing

    # API Key authentication (required for public ALB)
    enable_api_key: bool = False  # Enable API key authentication for vLLM/SGLang
    api_key_source: str = "auto"  # "auto" (generate), "custom", "secrets_manager"
    custom_api_key: Optional[str] = None  # Used when api_key_source is "custom"
    secrets_manager_secret_name: Optional[str] = None  # Used when api_key_source is "secrets_manager"

class DeployModelRequest(BaseModel):
    job_id:str
    model_name:Optional[str] = ''
    engine:Literal["vllm","sglang","scheduler","auto","lmi-dist","trt-llm"]
    instance_type:str
    quantize:Optional[str] = ''
    enable_lora:Optional[bool] = False
    cust_repo_type:Optional[str] = ''
    cust_repo_addr:Optional[str] = ''
    extra_params:Optional[Dict[str,Any]] = None
    # HyperPod deployment options
    deployment_target: Literal["sagemaker", "hyperpod"] = "sagemaker"
    hyperpod_cluster_id: Optional[str] = None  # Required when deployment_target="hyperpod"
    hyperpod_config: Optional[HyperPodDeployConfig] = None
    
class EndpointRequest(BaseModel):
    endpoint_name:str


class ListEndpointsRequest(BaseModel):
    page_size : int = 20
    page_index : Optional[int] = Field(default=1)
    query_terms : Optional[Dict[str,Any]] =  Field(default=None)

class EndpointInfo(BaseModel):
    job_id:str
    endpoint_name:str
    model_name:str
    engine:str
    enable_lora:bool
    instance_type:str
    instance_count:int
    model_s3_path:str
    endpoint_status:EndpointStatus
    endpoint_create_time: Optional[datetime] = None
    endpoint_delete_time:Optional[datetime] = None
    extra_config:Optional[str]= None
    # HyperPod deployment info
    deployment_target: str = "sagemaker"  # "sagemaker" or "hyperpod"
    hyperpod_cluster_id: Optional[str] = None
    
    
class ListEndpointsResponse(BaseModel):
    response_id:str
    endpoints :List[EndpointInfo]
    total_count:int
    
class InferenceRequest(BaseModel):
    endpoint_name:str
    model_name:str
    id:Optional[str] = None
    messages:List[Dict[str,Any]]
    params:Dict[str,Any]
    stream: Optional[bool]= False
    mode: Optional[Literal["webui","api"]] = "webui"
    
class LoginRequest(BaseModel):
    username:str
    password:str

class SpotPriceHistoryRequest(BaseModel):
    instance_types: List[str]
    region: Optional[str] = None
    days: int = Field(default=7, ge=1, le=90)

class SpotInterruptionRateRequest(BaseModel):
    instance_type: str
    region: Optional[str] = None

# ==================== HyperPod EKS Cluster Models ====================

class ClusterStatus(Enum):
    """HyperPod/EKS Cluster status"""
    PENDING = "PENDING"
    CREATING = "CREATING"
    UPDATING = "UPDATING"
    ACTIVE = "ACTIVE"
    DELETING = "DELETING"
    FAILED = "FAILED"
    DELETED = "DELETED"

class InstanceGroupConfig(BaseModel):
    """Instance group configuration for HyperPod cluster"""
    name: str
    instance_type: str
    instance_count: int = 0
    min_instance_count: Optional[int] = None
    threads_per_core: int = 1
    use_spot: bool = False
    kubernetes_labels: Optional[Dict[str, str]] = None
    training_plan_arn: Optional[str] = None
    storage_volume_size: int = 500  # Additional EBS volume size in GB
    enable_instance_stress_check: bool = False  # Enable InstanceStress deep health check
    enable_instance_connectivity_check: bool = False  # Enable InstanceConnectivity deep health check

    @field_validator('instance_type')
    @classmethod
    def validate_instance_type_pod_capacity(cls, v: str) -> str:
        """
        Validate instance type has sufficient pod capacity for HyperPod.

        HyperPod EKS clusters require at least 15+ pods for base components:
        - kube-system pods (coredns, aws-node, kube-proxy, etc.)
        - cert-manager
        - KEDA
        - HyperPod inference operator
        - Your actual workload pods

        Instances with single ENI (xlarge, 2xlarge) have max ~14 pods which is insufficient.
        """
        if v in HYPERPOD_LOW_POD_CAPACITY_INSTANCES:
            max_pods = HYPERPOD_LOW_POD_CAPACITY_INSTANCES[v]
            raise ValueError(
                f"Instance type '{v}' has insufficient pod capacity ({max_pods} max) for HyperPod EKS. "
                f"HyperPod requires 15+ pods for base components. "
                f"Please use ml.g5.4xlarge or larger. "
                f"Recommended: {', '.join(HYPERPOD_RECOMMENDED_MIN_INSTANCES[:3])}"
            )
        return v

class VPCConfigModel(BaseModel):
    """VPC configuration for cluster deployment"""
    vpc_id: Optional[str] = None  # Use existing VPC
    vpc_cidr: str = "10.0.0.0/16"
    public_subnet_cidrs: List[str] = ["10.0.1.0/24", "10.0.2.0/24"]
    private_subnet_cidrs: List[str] = ["10.0.10.0/24", "10.0.20.0/24"]
    subnet_ids: Optional[List[str]] = None  # Use existing subnets
    security_group_ids: Optional[List[str]] = None  # Use existing SGs

class EKSConfigModel(BaseModel):
    """EKS cluster configuration"""
    kubernetes_version: str = "1.31"
    endpoint_public_access: bool = True
    endpoint_private_access: bool = True
    authentication_mode: str = "API_AND_CONFIG_MAP"
    enable_logging: bool = True

class HyperPodConfigModel(BaseModel):
    """HyperPod cluster configuration"""
    node_recovery: str = "Automatic"
    node_provisioning_mode: str = "Continuous"  # "Continuous" or "OnDemand"
    enable_deep_health_checks: bool = True
    enable_autoscaling: bool = False
    # Tiered Storage for L2 KV Cache (requires AWS managed daemon on nodes)
    enable_tiered_storage: bool = False
    tiered_storage_memory_percentage: int = 20  # 20-100, percentage of instance memory for tiered storage

class CreateClusterRequest(BaseModel):
    """Request to create HyperPod EKS cluster"""
    cluster_name: str
    eks_cluster_name: Optional[str] = None  # Defaults to cluster_name-eks
    instance_groups: List[InstanceGroupConfig]
    vpc_config: Optional[VPCConfigModel] = None
    eks_config: Optional[EKSConfigModel] = None
    hyperpod_config: Optional[HyperPodConfigModel] = None
    lifecycle_script_s3_uri: Optional[str] = None
    s3_mount_bucket: Optional[str] = None  # S3 bucket for Mountpoint, defaults to lifecycle bucket if not specified
    tags: Optional[Dict[str, str]] = None

class ClusterInfo(BaseModel):
    """HyperPod EKS cluster information"""
    cluster_id: str
    cluster_name: str
    eks_cluster_name: str
    eks_cluster_arn: Optional[str] = None
    hyperpod_cluster_arn: Optional[str] = None
    cluster_status: ClusterStatus
    vpc_id: Optional[str] = None
    subnet_ids: Optional[List[str]] = None
    instance_groups: Optional[List[Dict[str, Any]]] = None
    cluster_create_time: Optional[datetime] = None
    cluster_update_time: Optional[datetime] = None
    error_message: Optional[str] = None
    cluster_config: Optional[Dict[str, Any]] = None
    ts: int

class ListClustersRequest(BaseModel):
    """Request to list clusters"""
    page_size: int = 20
    page_index: Optional[int] = Field(default=1)
    query_terms: Optional[Dict[str, Any]] = Field(default=None)

class ListClustersResponse(BaseModel):
    """Response for listing clusters"""
    response_id: str
    clusters: List[ClusterInfo]
    total_count: int

class GetClusterRequest(BaseModel):
    """Request to get cluster by ID"""
    cluster_id: str

class ClusterResponse(BaseModel):
    """Single cluster response"""
    response_id: str
    body: ClusterInfo

class DeleteClusterRequest(BaseModel):
    """Request to delete cluster"""
    cluster_id: str
    delete_vpc: bool = False  # Whether to delete associated VPC resources

class UpdateClusterRequest(BaseModel):
    """Request to update cluster"""
    cluster_id: str
    instance_groups: Optional[List[InstanceGroupConfig]] = None
    hyperpod_config: Optional[HyperPodConfigModel] = None

class ListClusterNodesRequest(BaseModel):
    """Request to list cluster nodes/instances"""
    cluster_id: str

class ClusterNodeInfo(BaseModel):
    """Information about a single cluster node/instance"""
    instance_id: str
    instance_status: str
    instance_group_name: str
    instance_type: Optional[str] = None
    launch_time: Optional[str] = None
    private_dns_name: Optional[str] = None
    private_ip_address: Optional[str] = None
    threads_per_core: Optional[int] = None
    placement: Optional[Dict[str, Any]] = None
    is_occupied: Optional[bool] = False  # Whether the node is occupied by an inference workload
    occupied_by: Optional[str] = None  # Name of the endpoint/workload occupying this node

class ListClusterNodesResponse(BaseModel):
    """Response for listing cluster nodes"""
    response_id: str
    nodes: List[ClusterNodeInfo]
    total_count: int


# ==================== Dashboard Statistics Models ====================

class DashboardStatsRequest(BaseModel):
    """Request for dashboard statistics - no parameters needed"""
    pass

class DailyJobCount(BaseModel):
    """Daily job count by status"""
    date: str                  # YYYY-MM-DD format
    status: str                # Job status
    count: int                 # Count for this date and status

class JobStats(BaseModel):
    """Job statistics for dashboard"""
    total_count: int
    by_status: Dict[str, int]  # {PENDING: 5, RUNNING: 3, SUCCESS: 100, ...}
    by_type: Dict[str, int]    # {sft: 50, pt: 30, dpo: 20, ...}
    daily_counts: List[DailyJobCount] = []  # Last 7 days by date and status

class EndpointStats(BaseModel):
    """Endpoint statistics for dashboard"""
    total_count: int
    by_deployment_target: Dict[str, int]  # {sagemaker: 10, hyperpod: 5}
    by_status: Dict[str, int]             # {CREATING: 2, INSERVICE: 8, ...}
    by_engine: Dict[str, int]             # {vllm: 5, sglang: 3, ...}

class ClusterStats(BaseModel):
    """Cluster statistics for dashboard"""
    total_count: int
    active_count: int
    by_status: Dict[str, int]                    # {ACTIVE: 3, CREATING: 1, ...}
    total_instance_count: int                    # Sum of all instances across clusters
    instance_type_distribution: Dict[str, int]  # {ml.g5.xlarge: 10, ...}

class DashboardStatsResponse(BaseModel):
    """Response for dashboard statistics"""
    response_id: str
    job_stats: JobStats
    endpoint_stats: EndpointStats
    cluster_stats: ClusterStats
