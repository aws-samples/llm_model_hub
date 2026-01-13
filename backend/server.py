import argparse
import json
import os
from typing import Generator, Optional, Union, Dict, List, Any
from logger_config import setup_logger
import logging
import dotenv
import fastapi
from fastapi import Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security.http import HTTPAuthorizationCredentials, HTTPBearer
# from pydantic_settings import BaseSettings
from fastapi.security import OAuth2PasswordBearer
from fastapi.responses import StreamingResponse
from typing import AsyncIterable
import uvicorn
import time
import uuid
from pydantic import BaseModel,Field
from model.data_model import *
import asyncio
from training.jobs import create_job,list_jobs,get_job_by_id,delete_job_by_id,fetch_training_log,get_job_status,stop_and_delete_job
from training.spot_price_history import get_spot_price_history, get_spot_interruption_rate
from eks_management.clusters import (
    create_cluster as create_eks_cluster,
    list_clusters as list_eks_clusters,
    get_cluster_by_id as get_eks_cluster_by_id,
    delete_cluster as delete_eks_cluster,
    update_cluster as update_eks_cluster,
    get_cluster_status as get_eks_cluster_status,
    list_cluster_nodes as list_eks_cluster_nodes,
    get_cluster_instance_types as get_eks_cluster_instance_types,
)
from processing_engine.cluster_processor import sync_cluster_status_with_aws, sync_all_cluster_statuses
from utils.get_factory_config import get_factory_config
from utils.outputs import list_s3_objects
from inference.endpoint_management import deploy_endpoint,delete_endpoint,get_endpoint_status,list_endpoints,deploy_endpoint_byoc,get_endpoint_engine,get_endpoint_info,deploy_endpoint_hyperpod,delete_endpoint_hyperpod
from inference.serving import inference,inference_byoc
from users.login import login_auth
from utils.config import DEFAULT_REGION
from utils.llamafactory.extras.constants import DownloadSource


dotenv.load_dotenv()

logger = setup_logger('server.py', log_file='server.log', level=logging.INFO)
api_keys = os.environ['api_keys'].split(',')
print(api_keys)
class AppSettings(BaseModel):
    # The address of the model controller.
    api_keys: Optional[List[str]] = None


app_settings = AppSettings(api_keys=api_keys)
app = fastapi.FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)
headers = {"User-Agent": "Chat Server"}
get_bearer_token = HTTPBearer(auto_error=False)
async def check_api_key(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(get_bearer_token),
) -> str:
    # print(app_settings.api_keys)
    if app_settings.api_keys:
        if auth is None or (token := auth.credentials) not in app_settings.api_keys:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "message": "",
                        "type": "invalid_request_error",
                        "param": None,
                        "code": "invalid_api_key",
                    }
                },
            )
        return token
    else:
        raise HTTPException(
                status_code=403,
                detail={
                    "error": {
                        "message": "",
                        "type": "invalid_request_error",
                        "param": None,
                        "code": "invalid_api_key",
                    }
                },
            )

class ErrorResponse(BaseModel):
    object: str = "error"
    message: str
    code: int


class APIRequestResponse(BaseModel):
    message:str

    
def create_error_response(code: int, message: str) -> JSONResponse:
    return JSONResponse(
        ErrorResponse(message=message, code=code).json(), status_code=400
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    # Log detailed validation errors for debugging
    logger.error(f"Request validation error on {request.url.path}")
    logger.error(f"Validation errors: {exc.errors()}")
    try:
        body = await request.body()
        logger.error(f"Request body: {body.decode('utf-8')[:2000]}")  # Log first 2000 chars
    except Exception:
        pass
    return create_error_response(400, str(exc))

@app.get("/")
async def ping():
    return APIRequestResponse(message='ok')

@app.post("/v1/login",dependencies=[Depends(check_api_key)])
async def handel_login(request:LoginRequest):
    response = login_auth(username = request.username,password = request.password)
    return CommonResponse(response=response,response_id=str(uuid.uuid4()))


@app.post("/v1/list_jobs",dependencies=[Depends(check_api_key)])
async def handel_list_jobs(request:ListJobsRequest):
    # logger.info(request.json())
    resp = await list_jobs(request)
    return resp

@app.post("/v1/get_factory_config",dependencies=[Depends(check_api_key)])
async def get_llama_factory_config(request:GetFactoryConfigRequest):
    # 中国区从modelscope下载模型
    repo = DownloadSource.MODELSCOPE if DEFAULT_REGION.startswith('cn') else DownloadSource.DEFAULT
    resp = await get_factory_config(request,repo)
    return resp

@app.post("/v1/get_job",dependencies=[Depends(check_api_key)])
async def get_job(request:GetJobsRequest):
    resp = await get_job_by_id(request)
    return resp

@app.post("/v1/delete_job",dependencies=[Depends(check_api_key)])
async def delete_job(request:DelJobsRequest):
    resp = await delete_job_by_id(request)
    return resp

@app.post("/v1/stop_and_delete_job",dependencies=[Depends(check_api_key)])
async def stop_delete_job(request:DelJobsRequest):
    resp = await stop_and_delete_job(request.job_id)
    return resp

@app.post("/v1/create_job",dependencies=[Depends(check_api_key)])
async def handle_create_job(request: CreateJobsRequest):
    request_timestamp = time.time()  
    logger.info(request.json())
    job_detail = await create_job(request)
    if job_detail:
        body = {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': job_detail
        }
        return CommonResponse(response=body,response_id=str(uuid.uuid4()))
    else:
        body = {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': 'create job failed'
        }
        return CommonResponse(response=body,response_id=str(uuid.uuid4()))
    
@app.post("/v1/fetch_training_log",dependencies=[Depends(check_api_key)])
async def handle_fetch_training_log(request:FetchLogRequest):
    # logger.info(request.json())
    resp = await fetch_training_log(request)
    return resp


@app.post("/v1/get_job_status",dependencies=[Depends(check_api_key)])
async def handle_get_job_status(request:GetJobsRequest):
    # logger.info(request.json())
    job_status = get_job_status(request.job_id)
    resp = JobStatusResponse(response_id=str(uuid.uuid4()), job_status=JobStatus(job_status))
    return resp

@app.post("/v1/list_s3_path",dependencies=[Depends(check_api_key)])
async def handle_list_s3_path(request:ListS3ObjectsRequest):
    ret = list_s3_objects(request.output_s3_path)
    return S3ObjectsResponse(response_id=str(uuid.uuid4()),objects=ret)

@app.post("/v1/spot_price_history",dependencies=[Depends(check_api_key)])
async def handle_spot_price_history(request:SpotPriceHistoryRequest):
    """
    Query EC2 Spot Price History for specified instance types.
    Returns price statistics and availability zones to help users assess spot instance viability.
    """
    result = await asyncio.to_thread(
        get_spot_price_history,
        instance_types=request.instance_types,
        region=request.region,
        days=request.days
    )
    return CommonResponse(response_id=str(uuid.uuid4()), response=result)

@app.post("/v1/spot_interruption_rate",dependencies=[Depends(check_api_key)])
async def handle_spot_interruption_rate(request:SpotInterruptionRateRequest):
    """
    Get estimated spot interruption rate for an instance type.
    Returns risk assessment based on price volatility.
    """
    result = await asyncio.to_thread(
        get_spot_interruption_rate,
        instance_type=request.instance_type,
        region=request.region
    )
    return CommonResponse(response_id=str(uuid.uuid4()), response=result)
    
@app.post('/v1/deploy_endpoint',dependencies=[Depends(check_api_key)])
async def handle_deploy_endpoint(request:DeployModelRequest):
    logger.info(f"Deploy endpoint request received: {request}")

    # Route to HyperPod deployment if deployment_target is "hyperpod"
    if request.deployment_target == "hyperpod":
        logger.info(f"HyperPod deployment requested - cluster_id: {request.hyperpod_cluster_id}, "
                   f"model_name: {request.model_name}, engine: {request.engine}, "
                   f"instance_type: {request.instance_type}")
        if not request.hyperpod_cluster_id:
            logger.error("HyperPod deployment failed: hyperpod_cluster_id is required")
            return CommonResponse(response_id=str(uuid.uuid4()),response={"result":False, "endpoint_name": "hyperpod_cluster_id is required for HyperPod deployment"})
        try:
            hyperpod_config = request.hyperpod_config.model_dump() if request.hyperpod_config else {}
            logger.info(f"HyperPod config: {hyperpod_config}")
            logger.info(f"Extra params: {request.extra_params}")
            ret, msg = await asyncio.wait_for(
                asyncio.to_thread(deploy_endpoint_hyperpod,
                                job_id=request.job_id,
                                engine=request.engine,
                                instance_type=request.instance_type,
                                enable_lora=request.enable_lora,
                                model_name=request.model_name,
                                hyperpod_cluster_id=request.hyperpod_cluster_id,
                                hyperpod_config=hyperpod_config,
                                extra_params=request.extra_params or {}
                                ),
                                timeout=120)
            logger.info(f"HyperPod deployment result: success={ret}, message={msg}")
            return CommonResponse(response_id=str(uuid.uuid4()),response={"result":ret, "endpoint_name": msg})
        except asyncio.TimeoutError:
            logger.error("HyperPod deployment timed out after 120 seconds")
            return CommonResponse(response_id=str(uuid.uuid4()),response={"result":False, "endpoint_name": "Operation timed out"})
        except Exception as e:
            import traceback
            logger.error(f"HyperPod deployment error: {e}\n{traceback.format_exc()}")
            return CommonResponse(response_id=str(uuid.uuid4()),response={"result":False, "endpoint_name": str(e)})

    # Original SageMaker deployment logic
    #engine不是'auto','vllm'，则使用lmi
    if request.engine in ['auto','vllm','sglang'] :
        try:
            ret,msg =  await asyncio.wait_for(
                asyncio.to_thread(deploy_endpoint_byoc,
                                job_id=request.job_id,
                                engine=request.engine,
                                instance_type=request.instance_type,
                                quantize=request.quantize,
                                enable_lora=request.enable_lora,
                                cust_repo_type=request.cust_repo_type,
                                cust_repo_addr=request.cust_repo_addr,
                                model_name=request.model_name,
                                extra_params=request.extra_params
                                ),
                                timeout=10)
            return CommonResponse(response_id=str(uuid.uuid4()),response={"result":ret, "endpoint_name": msg})
        except asyncio.TimeoutError:
            return CommonResponse(response_id=str(uuid.uuid4()),response={"result":True, "endpoint_name": "Too long,swithing to background process"})
    else:
        try:
            ret,msg =  await asyncio.wait_for(
                asyncio.to_thread(deploy_endpoint,
                                job_id=request.job_id,
                                engine=request.engine,
                                instance_type=request.instance_type,
                                quantize=request.quantize,
                                enable_lora=request.enable_lora,
                                cust_repo_type=request.cust_repo_type,
                                cust_repo_addr=request.cust_repo_addr,
                                model_name=request.model_name,
                                extra_params=request.extra_params
                                ),
                                timeout=600)
            return CommonResponse(response_id=str(uuid.uuid4()),response={"result":ret, "endpoint_name": msg})
        except asyncio.TimeoutError:
            return CommonResponse(response_id=str(uuid.uuid4()),response={"result":False, "endpoint_name": "Operation timed out"}) 
    

@app.post('/v1/delete_endpoint',dependencies=[Depends(check_api_key)])
async def handle_delete_endpoint(request:EndpointRequest):
    logger.info(request)
    endpoint_name = request.endpoint_name

    # Check if this is a HyperPod endpoint
    endpoint_info = get_endpoint_info(endpoint_name)
    if endpoint_info and endpoint_info.get('deployment_target') == 'hyperpod':
        # HyperPod endpoint - delete from Kubernetes cluster
        hyperpod_cluster_id = endpoint_info.get('hyperpod_cluster_id')
        if not hyperpod_cluster_id:
            # No cluster ID, just delete from database
            from db_management.database import DatabaseWrapper
            db = DatabaseWrapper()
            db.delete_endpoint(endpoint_name=endpoint_name)
            return CommonResponse(response_id=str(uuid.uuid4()), response={"result": True, "msg": "Endpoint deleted from database (no cluster ID)"})

        extra_config = endpoint_info.get('extra_config')

        # Parse extra_config to get namespace
        namespace = 'default'
        if extra_config:
            if isinstance(extra_config, str):
                try:
                    extra_config = json.loads(extra_config)
                except:
                    pass
            if isinstance(extra_config, dict):
                namespace = extra_config.get('namespace', 'default')

        logger.info(f"Deleting HyperPod endpoint: {endpoint_name}, cluster_id: {hyperpod_cluster_id}, namespace: {namespace}")
        result, msg = delete_endpoint_hyperpod(endpoint_name, hyperpod_cluster_id, namespace)
        return CommonResponse(response_id=str(uuid.uuid4()), response={"result": result, "msg": msg})

    # SageMaker endpoint - use standard deletion
    result,msg = delete_endpoint(endpoint_name)
    return CommonResponse(response_id=str(uuid.uuid4()),response={"result": result,"msg":msg}) 

@app.post('/v1/get_endpoint_status',dependencies=[Depends(check_api_key)])
async def handle_get_endpoint_status(request:EndpointRequest):
    # logger.info(request)
    status = get_endpoint_status(endpoint_name=request.endpoint_name)
    return CommonResponse(response_id=str(uuid.uuid4()),response={"status": status.value})

@app.post('/v1/list_endpoints',dependencies=[Depends(check_api_key)])
async def handle_list_endpoints(request:ListEndpointsRequest):
    # logger.info(request)
    endpoints,count = list_endpoints(request)
    return ListEndpointsResponse(response_id=str(uuid.uuid4()),endpoints=endpoints,total_count=count)
    
    
def stream_generator(inference_request:InferenceRequest) -> AsyncIterable[bytes]:
    id = inference_request.id if inference_request.id else str(uuid.uuid4())
    logger.info('--stream_generator---')
    response_stream = inference(inference_request.endpoint_name, inference_request.model_name, 
                                      inference_request.messages, inference_request.params, True)
    for chunk in response_stream:
        yield f"data: {chunk}\n\n"
    yield f"data: [DONE]\n\n"
    
def stream_generator_byoc(inference_request:InferenceRequest) -> AsyncIterable[bytes]:
    id = inference_request.id if inference_request.id else str(uuid.uuid4())
    logger.info('--stream_generator_byoc---')
    response_stream = inference_byoc(inference_request.endpoint_name, inference_request.model_name, 
                                      inference_request.messages, inference_request.params, True)
    for chunk in response_stream:
        yield chunk
    
# ==================== HyperPod EKS Cluster APIs ====================

@app.post('/v1/create_cluster', dependencies=[Depends(check_api_key)])
async def handle_create_cluster(request: CreateClusterRequest):
    """Create a new HyperPod EKS cluster."""
    logger.info(f"Creating cluster: {request.model_dump_json(indent=2)}")
    cluster_detail = await create_eks_cluster(request)
    if cluster_detail:
        body = {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': cluster_detail.dict()
        }
        return CommonResponse(response=body, response_id=str(uuid.uuid4()))
    else:
        body = {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': 'create cluster failed'
        }
        return CommonResponse(response=body, response_id=str(uuid.uuid4()))


@app.post('/v1/list_clusters', dependencies=[Depends(check_api_key)])
async def handle_list_clusters(request: ListClustersRequest):
    """List HyperPod EKS clusters."""
    # logger.info(f"Listing clusters, page_size={request.page_size}, page_index={request.page_index}")
    resp = await list_eks_clusters(request)
    return resp


@app.post('/v1/get_cluster', dependencies=[Depends(check_api_key)])
async def handle_get_cluster(request: GetClusterRequest):
    """Get HyperPod EKS cluster by ID."""
    logger.info(f"Getting cluster: {request.cluster_id}")
    resp = await get_eks_cluster_by_id(request)
    return resp


@app.post('/v1/delete_cluster', dependencies=[Depends(check_api_key)])
async def handle_delete_cluster(request: DeleteClusterRequest):
    """Delete a HyperPod EKS cluster."""
    logger.info(f"Deleting cluster: {request.cluster_id}")
    resp = await delete_eks_cluster(request)
    return resp


@app.post('/v1/update_cluster', dependencies=[Depends(check_api_key)])
async def handle_update_cluster(request: UpdateClusterRequest):
    """Update a HyperPod EKS cluster."""
    logger.info(f"Updating cluster: {request.model_dump_json(indent=2)}")
    resp = await update_eks_cluster(request)
    return resp


@app.post('/v1/update_cluster_instance_groups', dependencies=[Depends(check_api_key)])
async def handle_update_cluster_instance_groups(request: UpdateClusterRequest):
    """Update cluster instance groups only."""
    logger.info(f"Updating instance groups for cluster: {request.model_dump_json(indent=2)}")
    resp = await update_eks_cluster(request)
    return resp


@app.get('/v1/cluster_status/{cluster_id}', dependencies=[Depends(check_api_key)])
async def handle_get_cluster_status(cluster_id: str):
    """Get current cluster status from AWS."""
    logger.info(f"Getting cluster status: {cluster_id}")
    status = get_eks_cluster_status(cluster_id)
    return CommonResponse(
        response_id=str(uuid.uuid4()),
        response={
            'statusCode': 200,
            'body': {
                'cluster_id': cluster_id,
                'status': status.value
            }
        }
    )


@app.post('/v1/list_cluster_nodes', dependencies=[Depends(check_api_key)])
async def handle_list_cluster_nodes(request: ListClusterNodesRequest):
    """List nodes/instances in a HyperPod cluster."""
    logger.info(f"Listing cluster nodes for cluster: {request.cluster_id}")
    resp = await list_eks_cluster_nodes(request)
    return resp


@app.get('/v1/cluster_instance_types/{cluster_id}', dependencies=[Depends(check_api_key)])
async def handle_get_cluster_instance_types(cluster_id: str):
    """Get available instance types from a HyperPod cluster."""
    logger.info(f"Getting cluster instance types for cluster: {cluster_id}")
    result = await get_eks_cluster_instance_types(cluster_id)
    # result is a dict with 'instance_types' and 'instance_type_details' keys
    return CommonResponse(
        response_id=str(uuid.uuid4()),
        response={
            'statusCode': 200,
            'body': {
                'cluster_id': cluster_id,
                'instance_types': result.get('instance_types', []),
                'instance_type_details': result.get('instance_type_details', [])
            }
        }
    )


@app.post('/v1/sync_cluster_status/{cluster_id}', dependencies=[Depends(check_api_key)])
async def handle_sync_cluster_status(cluster_id: str):
    """
    Sync a single cluster's status with AWS.

    This endpoint allows manually triggering a status sync for a specific cluster,
    useful when database status is out of sync with AWS console.
    """
    logger.info(f"Syncing cluster status for: {cluster_id}")
    try:
        synced = sync_cluster_status_with_aws(cluster_id)
        return CommonResponse(
            response_id=str(uuid.uuid4()),
            response={
                'statusCode': 200,
                'body': {
                    'cluster_id': cluster_id,
                    'synced': synced,
                    'message': 'Cluster status synced with AWS' if synced else 'No status change needed'
                }
            }
        )
    except Exception as e:
        logger.error(f"Error syncing cluster status: {e}")
        return CommonResponse(
            response_id=str(uuid.uuid4()),
            response={
                'statusCode': 500,
                'body': {
                    'error': str(e)
                }
            }
        )


@app.post('/v1/sync_all_cluster_statuses', dependencies=[Depends(check_api_key)])
async def handle_sync_all_cluster_statuses():
    """
    Sync all cluster statuses with AWS.

    This endpoint allows manually triggering a status sync for all clusters,
    useful for bulk recovery from status mismatches.
    """
    logger.info("Syncing all cluster statuses with AWS")
    try:
        sync_all_cluster_statuses()
        return CommonResponse(
            response_id=str(uuid.uuid4()),
            response={
                'statusCode': 200,
                'body': {
                    'message': 'All cluster statuses synced with AWS'
                }
            }
        )
    except Exception as e:
        logger.error(f"Error syncing all cluster statuses: {e}")
        return CommonResponse(
            response_id=str(uuid.uuid4()),
            response={
                'statusCode': 500,
                'body': {
                    'error': str(e)
                }
            }
        )


# ==================== Dashboard Statistics API ====================

@app.post('/v1/dashboard_stats', dependencies=[Depends(check_api_key)])
async def handle_dashboard_stats(request: DashboardStatsRequest):
    """
    Get aggregated statistics for the dashboard.
    Returns job, endpoint, and cluster statistics.
    """
    from db_management.database import DatabaseWrapper
    db = DatabaseWrapper()

    try:
        job_stats = db.get_job_stats()
        endpoint_stats = db.get_endpoint_stats()
        cluster_stats = db.get_cluster_stats()

        # Get daily job counts for the last 7 days
        daily_job_data = db.get_jobs_by_date_and_status(days=7)
        daily_counts = [DailyJobCount(**item) for item in daily_job_data]
        job_stats['daily_counts'] = daily_counts

        return DashboardStatsResponse(
            response_id=str(uuid.uuid4()),
            job_stats=JobStats(**job_stats),
            endpoint_stats=EndpointStats(**endpoint_stats),
            cluster_stats=ClusterStats(**cluster_stats)
        )
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "message": str(e),
                    "type": "internal_error",
                    "param": None,
                    "code": "dashboard_stats_error",
                }
            },
        )


@app.post('/v1/chat/completions',dependencies=[Depends(check_api_key)])
async def handle_inference(request:InferenceRequest):
    # logger.info(request)

    # Get endpoint info to check if it's HyperPod
    endpoint_info = get_endpoint_info(request.endpoint_name)

    if endpoint_info and endpoint_info.get('deployment_target') == 'hyperpod':
        # HyperPod endpoint - use HTTP invocation
        return await handle_hyperpod_inference(request, endpoint_info)

    engine = get_endpoint_engine(request.endpoint_name)
    # logger.info(f"engine:{engine}")
    #engine不是'auto','vllm'，则使用lmi
    if  engine in ['auto','vllm','sglang'] :
        if not request.stream:
            response = inference_byoc(request.endpoint_name,request.model_name,request.messages,request.params,False)
            id = request.id if request.id else str(uuid.uuid4())
            return CommonResponse(response_id=id,response=response)
        else:
            return StreamingResponse(stream_generator_byoc(request), media_type="text/event-stream")
    else:

        if not request.stream:
            response = inference(request.endpoint_name,request.model_name,request.messages,request.params,False)
            id = request.id if request.id else str(uuid.uuid4())
            return CommonResponse(response_id=id,response=response)
        else:
            return StreamingResponse(stream_generator(request), media_type="text/event-stream")


async def handle_hyperpod_inference(request: InferenceRequest, endpoint_info: dict):
    """Handle inference for HyperPod endpoints via HTTP."""
    import json as json_module
    from inference.hyperpod_inference import invoke_hyperpod_endpoint, invoke_hyperpod_endpoint_stream, get_hyperpod_endpoint_url

    logger.info(f"[HyperPod Inference] Starting inference for endpoint: {request.endpoint_name}")
    logger.info(f"[HyperPod Inference] Endpoint info: deployment_target={endpoint_info.get('deployment_target')}, "
                f"hyperpod_cluster_id={endpoint_info.get('hyperpod_cluster_id')}")

    # Parse extra_config to get cluster info
    extra_config = endpoint_info.get('extra_config')
    if isinstance(extra_config, str):
        try:
            extra_config = json_module.loads(extra_config)
            # Handle potential double-encoding
            if isinstance(extra_config, str):
                extra_config = json_module.loads(extra_config)
        except:
            extra_config = {}
    extra_config = extra_config or {}

    eks_cluster_name = extra_config.get('eks_cluster_name')
    namespace = extra_config.get('namespace', 'default')

    if not eks_cluster_name:
        # Try to get from cluster database
        from db_management.database import DatabaseWrapper
        db = DatabaseWrapper()
        hyperpod_cluster_id = endpoint_info.get('hyperpod_cluster_id')
        if hyperpod_cluster_id:
            cluster_info = db.get_cluster_by_id(hyperpod_cluster_id)
            if cluster_info:
                eks_cluster_name = cluster_info.eks_cluster_name

    if not eks_cluster_name:
        logger.error(f"[HyperPod Inference] Could not determine EKS cluster name for endpoint {request.endpoint_name}")
        return CommonResponse(
            response_id=request.id or str(uuid.uuid4()),
            response={"error": "Could not determine EKS cluster name for endpoint"}
        )

    logger.info(f"[HyperPod Inference] Using EKS cluster: {eks_cluster_name}, namespace: {namespace}")

    # Get API key from extra_config if API key authentication is enabled
    api_key = None
    if extra_config.get('enable_api_key'):
        api_key = extra_config.get('api_key')
        if api_key:
            logger.info(f"[HyperPod Inference] API key authentication enabled for endpoint {request.endpoint_name}")
        else:
            logger.warning(f"[HyperPod Inference] API key authentication is enabled but no API key found in config for endpoint {request.endpoint_name}")

    # Get and log the endpoint URL
    try:
        url_info = get_hyperpod_endpoint_url(
            eks_cluster_name=eks_cluster_name,
            endpoint_name=request.endpoint_name,
            namespace=namespace
        )
        if url_info:
            logger.info(f"[HyperPod Inference] Endpoint URL: {url_info.get('full_url')}")
            logger.info(f"[HyperPod Inference] ALB Host: {url_info.get('endpoint_url')}")
        else:
            logger.warning(f"[HyperPod Inference] Could not get URL info for endpoint {request.endpoint_name}")
    except Exception as e:
        logger.warning(f"[HyperPod Inference] Error getting URL info: {e}")

    # Build payload
    # For HyperPod endpoints, extract served model name (last part after '/')
    # This matches the --served-model-name argument passed to the inference engine
    raw_model_name = request.model_name or endpoint_info.get('model_name', '')
    if "/" in raw_model_name:
        served_model_name = raw_model_name.split("/")[-1]
    else:
        served_model_name = raw_model_name

    payload = {
        "model": served_model_name,
        "messages": [{"role": m.get('role', 'user'), "content": m.get('content', '')} for m in request.messages],
        "stream": request.stream,
        "max_tokens": request.params.get('max_new_tokens', request.params.get('max_tokens', 256)),
        "temperature": request.params.get('temperature', 0.1),
        "top_p": request.params.get('top_p', 0.9),
    }

    try:
        if not request.stream:
            response = invoke_hyperpod_endpoint(
                eks_cluster_name=eks_cluster_name,
                endpoint_name=request.endpoint_name,
                payload=payload,
                namespace=namespace,
                stream=False,
                api_key=api_key
            )
            return CommonResponse(
                response_id=request.id or str(uuid.uuid4()),
                response=response
            )
        else:
            # Streaming response
            async def hyperpod_stream_generator():
                try:
                    for line in invoke_hyperpod_endpoint_stream(
                        eks_cluster_name=eks_cluster_name,
                        endpoint_name=request.endpoint_name,
                        payload=payload,
                        namespace=namespace,
                        api_key=api_key
                    ):
                        # SSE spec requires double newline (\n\n) to separate events
                        if line.startswith('data: '):
                            yield line + '\n\n'
                        else:
                            yield f"data: {line}\n\n"
                except Exception as e:
                    logger.error(f"HyperPod streaming error: {e}")
                    yield f"data: {json_module.dumps({'error': str(e)})}\n\n"

            return StreamingResponse(hyperpod_stream_generator(), media_type="text/event-stream")

    except Exception as e:
        logger.error(f"HyperPod inference error: {e}")
        return CommonResponse(
            response_id=request.id or str(uuid.uuid4()),
            response={"error": str(e)}
        )


def create_price_api_server():
    global app_settings
    parser = argparse.ArgumentParser(
        description="Chat RESTful API server."
    )
    parser.add_argument("--host", type=str, default="0.0.0.0", help="host name")
    parser.add_argument("--port", type=int, default=8000, help="port number")
    parser.add_argument(
        "--allow-credentials", action="store_true", help="allow credentials"
    )
    parser.add_argument(
        "--allowed-origins", type=json.loads, default=["*"], help="allowed origins"
    )
    parser.add_argument(
        "--allowed-methods", type=json.loads, default=["*"], help="allowed methods"
    )
    parser.add_argument(
        "--allowed-headers", type=json.loads, default=["*"], help="allowed headers"
    )
    parser.add_argument(
        "--ssl",
        action="store_true",
        required=False,
        default=False,
        help="Enable SSL. Requires OS Environment variables 'SSL_KEYFILE' and 'SSL_CERTFILE'.",
    )
    args = parser.parse_args()

    
    return args

if __name__ == "__main__":
    logger.info('server start')
    args = create_price_api_server()
    logger.info(f"{args}")
    if args.ssl:
        uvicorn.run(
            "server:app",
            host=args.host,
            port=args.port,
            log_level="info",
            ssl_keyfile=os.environ["SSL_KEYFILE"],
            ssl_certfile=os.environ["SSL_CERTFILE"],
        )
    else:
        uvicorn.run("server:app", host=args.host, port=args.port, log_level="info",reload=True,workers=1)
