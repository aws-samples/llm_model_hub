import time
import uuid
import sys
sys.path.append('../')
import json
import os
import logging
from typing import  Dict, Optional,List, Any
import shutil
import tempfile
from modelscope.hub.snapshot_download import snapshot_download
from model.data_model import *
from db_management.database import DatabaseWrapper
from datetime import datetime,timedelta
from training.jobs import sync_get_job_by_id
from utils.config import boto_sess,role,sagemaker_session,DEFAULT_REGION,SUPPORTED_MODELS_FILE,default_bucket,VLLM_IMAGE,SGLANG_IMAGE,MODEL_ARTIFACT,DEFAULT_IMAGES,get_auto_tensor_parallel_size
from utils.get_factory_config import get_model_path_by_name
from utils.llamafactory.extras.constants import register_model_group,DownloadSource,SUPPORTED_MODELS
from sagemaker import image_uris, Model
import sagemaker
import pickle
from logger_config import setup_logger
import threading
import concurrent.futures
database = DatabaseWrapper()
logger = setup_logger('endpoint_management.py', level=logging.INFO)
DEFAULT_CACHE_DIR = "./cache"  # 默认缓存目录
CACHE_EXPIRY_DAYS = 30  # 缓存有效期(天)


endpoints_lock = threading.Lock()
thread_pool = {}

def check_hyperpod_deployment_status(endpoint_name: str, hyperpod_cluster_id: str):
    """
    Check HyperPod endpoint deployment status and update database.

    This function polls the HyperPod endpoint status via Kubernetes API
    and updates the database when status changes to INSERVICE or FAILED.
    It also waits for public ALB to be ready if use_public_alb is enabled.
    """
    logger.info(f'[HyperPod Status] Starting status check thread for {endpoint_name}')

    # Import here to avoid circular imports
    from inference.hyperpod_inference import get_hyperpod_endpoint_status, get_hyperpod_endpoint_url

    # Get cluster info to get eks_cluster_name
    cluster = database.get_cluster_by_id(hyperpod_cluster_id)
    if not cluster:
        logger.error(f'[HyperPod Status] Cluster not found: {hyperpod_cluster_id}')
        with endpoints_lock:
            thread_pool.pop(endpoint_name, None)
        return False

    eks_cluster_name = cluster.eks_cluster_name
    max_attempts = 120  # Max 20 minutes (120 * 10s)
    attempt = 0

    while attempt < max_attempts:
        try:
            status, error_msg = get_hyperpod_endpoint_status(
                eks_cluster_name=eks_cluster_name,
                endpoint_name=endpoint_name,
                namespace="default"
            )

            logger.info(f'[HyperPod Status] {endpoint_name}: status={status}, error={error_msg}')

            if status == "INSERVICE":
                # Get endpoint extra_config to check if public ALB is requested
                extra_config_str = database.get_endpoint_extra_config(endpoint_name)
                extra_config = {}
                if extra_config_str:
                    try:
                        extra_config = json.loads(extra_config_str)
                    except:
                        pass

                use_public_alb = extra_config.get('use_public_alb', False)

                # If public ALB is requested, check if it's ready
                if use_public_alb:
                    try:
                        url_info = get_hyperpod_endpoint_url(
                            eks_cluster_name=eks_cluster_name,
                            endpoint_name=endpoint_name,
                            namespace="default"
                        )
                        alb_url = url_info.get('full_url', '') if url_info else ''

                        if not alb_url:
                            logger.info(f'[HyperPod Status] {endpoint_name} is InService but waiting for public ALB (not provisioned yet)')
                            time.sleep(10)
                            attempt += 1
                            continue
                        elif 'internal' in alb_url.lower():
                            logger.info(f'[HyperPod Status] {endpoint_name} is InService but waiting for public ALB (current: {alb_url})')
                            time.sleep(10)
                            attempt += 1
                            continue

                        # Update extra_config with ALB URL
                        extra_config['alb_url'] = alb_url
                        extra_config['endpoint_url'] = url_info.get('endpoint_url', '')
                    except Exception as e:
                        logger.warning(f'[HyperPod Status] Failed to get ALB URL for {endpoint_name}: {e}')
                        time.sleep(10)
                        attempt += 1
                        continue

                # Update status to INSERVICE
                database.update_endpoint_status(
                    endpoint_name=endpoint_name,
                    endpoint_status=EndpointStatus.INSERVICE,
                    extra_config=json.dumps(extra_config) if extra_config else None
                )
                logger.info(f'[HyperPod Status] {endpoint_name} is now INSERVICE')
                with endpoints_lock:
                    thread_pool.pop(endpoint_name, None)
                return True
            elif status == "FAILED":
                database.update_endpoint_status(
                    endpoint_name=endpoint_name,
                    endpoint_status=EndpointStatus.FAILED
                )
                logger.error(f'[HyperPod Status] {endpoint_name} FAILED: {error_msg}')
                with endpoints_lock:
                    thread_pool.pop(endpoint_name, None)
                return False
            elif status == "NOTFOUND":
                logger.warning(f'[HyperPod Status] {endpoint_name} not found in cluster')
                # Don't remove from thread_pool yet, might be creating

            # Still CREATING, wait and retry
            time.sleep(10)
            attempt += 1

        except Exception as e:
            logger.error(f'[HyperPod Status] Error checking {endpoint_name}: {e}')
            time.sleep(10)
            attempt += 1

    # Timeout - keep status as CREATING, stop polling
    logger.warning(f'[HyperPod Status] {endpoint_name} status check timed out after {max_attempts * 10}s')
    with endpoints_lock:
        thread_pool.pop(endpoint_name, None)
    return False


def check_deployment_status(endpoint_name:str):
    logger.info('a thread start')
    while True:
        status  = get_endpoint_status(endpoint_name)
        if status == EndpointStatus.CREATING:
            time.sleep(10)
        else:
            with endpoints_lock:
                thread_pool.pop(endpoint_name)
            logger.info('a thread exit')
            return True

def cleanup_expired_cache(cache_dir):
    """清理过期的缓存文件"""
    if not os.path.exists(cache_dir):
        return
        
    expiry_time = time.time() - (CACHE_EXPIRY_DAYS * 24 * 60 * 60)
    
    for item in os.listdir(cache_dir):
        item_path = os.path.join(cache_dir, item)
        if os.path.getctime(item_path) < expiry_time:
            try:
                if os.path.isfile(item_path):
                    os.remove(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                logger.info(f"Cleaned up expired cache: {item_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up {item_path}: {str(e)}")


def hf_download_and_upload_model(model_repo: str, s3_bucket: str, s3_prefix: str, cache_dir: str = DEFAULT_CACHE_DIR) -> str:
    """
    Download model from HuggingFace Hub and sync to S3.
    Uses 'aws s3 sync' to avoid re-uploading existing files.

    Args:
        model_repo: HuggingFace model repository (e.g., 'Qwen/Qwen2.5-1.5B-Instruct')
        s3_bucket: S3 bucket name
        s3_prefix: S3 path prefix
        cache_dir: Local cache directory

    Returns:
        S3 URL where model was uploaded
    """
    import subprocess
    from huggingface_hub import snapshot_download as hf_snapshot_download

    try:
        # Create cache directory
        os.makedirs(cache_dir, exist_ok=True)

        # Clean up expired cache
        cleanup_expired_cache(cache_dir)

        # Download model from HuggingFace
        logger.info(f"Downloading model {model_repo} from HuggingFace Hub...")
        hf_token = os.environ.get('HUGGING_FACE_HUB_TOKEN')
        local_dir = hf_snapshot_download(
            repo_id=model_repo,
            cache_dir=cache_dir,
            token=hf_token
        )

        # Sync model files to S3 (only uploads new/changed files)
        s3_url = f"s3://{s3_bucket}/{s3_prefix}"
        logger.info(f"Model downloaded to {local_dir}, syncing to {s3_url}...")

        sync_cmd = ["aws", "s3", "sync", local_dir, s3_url, "--only-show-errors"]
        result = subprocess.run(sync_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"S3 sync failed: {result.stderr}")
            raise Exception(f"S3 sync failed: {result.stderr}")

        logger.info(f"Successfully synced {model_repo} to {s3_url}")
        return s3_url

    except Exception as e:
        logger.error(f"Error downloading/uploading model {model_repo}: {str(e)}")
        raise


def ms_download_and_upload_model(model_repo, s3_bucket, s3_prefix, cache_dir=DEFAULT_CACHE_DIR):
    """
    从ModelScope下载模型并同步到S3
    使用 'aws s3 sync' 避免重复上传已存在的文件

    Args:
        model_repo: ModelScope模型仓库名
        s3_bucket: S3存储桶名
        s3_prefix: S3路径前缀
        cache_dir: 缓存目录路径,默认为DEFAULT_CACHE_DIR
    """
    import subprocess

    try:
        # 创建缓存目录(如果不存在)
        os.makedirs(cache_dir, exist_ok=True)

        # 清理过期缓存
        cleanup_expired_cache(cache_dir)

        # 从ModelScope下载模型到缓存目录
        local_dir = snapshot_download(model_repo, cache_dir=cache_dir)

        # 同步模型文件到S3 (只上传新增或修改的文件)
        s3_url = f"s3://{s3_bucket}/{s3_prefix}"
        logger.info(f"Model downloaded to {local_dir}, syncing to {s3_url}...")

        sync_cmd = ["aws", "s3", "sync", local_dir, s3_url, "--only-show-errors"]
        result = subprocess.run(sync_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"S3 sync failed: {result.stderr}")
            raise Exception(f"S3 sync failed: {result.stderr}")

        logger.info(f"Successfully synced {model_repo} to {s3_url}")
        return s3_url

    except Exception as e:
        logger.error(f"Error processing model {model_repo}: {str(e)}")
        raise
       

def get_endpoint_status(endpoint_name:str) ->EndpointStatus:
    client = boto_sess.client('sagemaker')
    try:
        resp = client.describe_endpoint(EndpointName=endpoint_name)
        # logger.info(resp)
        status = resp['EndpointStatus']
        if status == 'InService':
            logger.info("Deployment completed successfully.")
            print("Deployment completed successfully.")
            database.update_endpoint_status(
                endpoint_name=endpoint_name,
                endpoint_status=EndpointStatus.INSERVICE
            )
            return EndpointStatus.INSERVICE
        elif status in ['Failed']:
            logger.info("Deployment failed or is being deleted.")
            database.update_endpoint_status(
                endpoint_name=endpoint_name,
                endpoint_status=EndpointStatus.FAILED
            )
            return EndpointStatus.FAILED
        elif status in ['Creating']:
            database.update_endpoint_status(
                endpoint_name=endpoint_name,
                endpoint_status=EndpointStatus.CREATING
            )
            return EndpointStatus.CREATING
            
        else:
            return EndpointStatus.NOTFOUND
    except Exception as e:
        logger.error(e)
        return EndpointStatus.NOTFOUND
        
def delete_endpoint(endpoint_name:str) -> tuple[bool,str]:
    client = boto_sess.client('sagemaker')
    endpoint_not_found = False

    try:
        client.delete_endpoint(EndpointName=endpoint_name)
    except client.exceptions.ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        error_message = str(e)
        # If endpoint not found, mark it and continue to clean up other resources
        if 'ValidationException' in error_code or 'Could not find endpoint' in error_message:
            logger.warning(f"Endpoint not found in SageMaker: {endpoint_name}, will delete from database")
            endpoint_not_found = True
        else:
            logger.error(e)
            return False, f"Delete failed: {str(e)}"
    except Exception as e:
        logger.error(e)
        return False, f"Delete failed: {str(e)}"

    # Try to delete endpoint config (may not exist)
    try:
        client.delete_endpoint_config(EndpointConfigName=endpoint_name)
    except Exception as e:
        logger.warning(f"Failed to delete endpoint config (may not exist): {e}")

    # Try to delete model (may not exist)
    try:
        client.delete_model(ModelName=endpoint_name)
    except Exception as e:
        logger.warning(f"Failed to delete model (may not exist): {e}")

    # Always delete from database
    database.delete_endpoint(endpoint_name=endpoint_name)

    if endpoint_not_found:
        return True, 'Endpoint not found in SageMaker, deleted from database'
    return True, 'Delete endpoint success'

def register_cust_model(cust_repo_type:DownloadSource,cust_repo_addr:str):
    model_name = cust_repo_addr.split('/')[1]
    
    register_model_group(
        models={
            model_name: {
                cust_repo_type : cust_repo_addr,
            }
        },
    )
    #register_model_group会改变以下2个对象，需要持久化保存，服务器重启之后仍然能加载
    with open(SUPPORTED_MODELS_FILE, 'wb') as f:
        pickle.dump(SUPPORTED_MODELS, f)
    

def deploy_engine(job_id:str,engine:str,instance_type:str,enable_lora:bool,model_name:str,model_path:str,extra_params:Dict[str,Any]) -> tuple[bool,str]:
    # Determine the model ID for vLLM/SGLang
    # If model_path is provided (finetuned model from S3), SageMaker will download it to /opt/ml/model
    # via ModelDataSource, and we set model path to /opt/ml/model
    # If model_path is empty, use HuggingFace model name directly
    if model_path:
        # When using S3 model, point to where SageMaker extracts model files
        vllm_model_id = "/opt/ml/model"
    else:
        vllm_model_id = model_name

    if engine in ['auto','vllm']:
        lmi_image_uri = VLLM_IMAGE
        dtype = 'half' if instance_type.startswith('ml.g4dn') else 'auto' # g4dn does not support bf16, need to use fp16
        # SageMaker vLLM DLC uses SM_VLLM_* prefix for environment variables
        # The entry point script converts SM_VLLM_MODEL to --model, SM_VLLM_SERVED_MODEL_NAME to --served-model-name, etc.
        # Reference: https://github.com/aws/deep-learning-containers/blob/master/vllm/build_artifacts/sagemaker_entrypoint.sh
        env={
            "SM_VLLM_MODEL": vllm_model_id,
            "SM_VLLM_SERVED_MODEL_NAME": model_name,  # Tell vLLM to serve under the original model name
            "SM_VLLM_DTYPE": dtype,
            "SM_VLLM_MAX_MODEL_LEN": extra_params.get('max_model_len', "12288"),
            "SM_VLLM_TENSOR_PARALLEL_SIZE": extra_params.get('tensor_parallel_size', str(get_auto_tensor_parallel_size(instance_type))),
            "SM_VLLM_MAX_NUM_SEQS": extra_params.get('max_num_seqs', '256'),
            "HF_TOKEN": os.environ.get('HUGGING_FACE_HUB_TOKEN'),
        }
        # Optional parameters - only add if specified
        if extra_params.get('limit_mm_per_prompt'):
            env["SM_VLLM_LIMIT_MM_PER_PROMPT"] = extra_params.get('limit_mm_per_prompt')
        if extra_params.get('enable_prefix_caching'):
            env["SM_VLLM_ENABLE_PREFIX_CACHING"] = ""  # flag without value
        if extra_params.get('enforce_eager'):
            env["SM_VLLM_ENFORCE_EAGER"] = ""  # flag without value
        if extra_params.get("tool_call_parser"):
            env["SM_VLLM_TOOL_CALL_PARSER"] = extra_params.get("tool_call_parser")
        if DEFAULT_REGION.startswith('cn'):
            env['SM_VLLM_USE_MODELSCOPE'] = '1'

    elif engine in ['sglang']:
        lmi_image_uri = SGLANG_IMAGE
        # SageMaker SGLang DLC uses SM_SGLANG_* prefix for environment variables
        # The entry point script converts SM_SGLANG_MODEL_PATH to --model-path, SM_SGLANG_TP_SIZE to --tp-size, etc.
        # Reference: https://github.com/aws/deep-learning-containers/blob/master/sglang/build_artifacts/sagemaker_entrypoint.sh
        # Note: Default model-path is /opt/ml/model if not set
        env={
            "SM_SGLANG_SERVED_MODEL_NAME": model_name,  # Tell SGLang to serve under the original model name
            "SM_SGLANG_TP_SIZE": extra_params.get('tensor_parallel_size', str(get_auto_tensor_parallel_size(instance_type))),
            "SM_SGLANG_MEM_FRACTION_STATIC": extra_params.get("mem_fraction_static", "0.9"),
            "HF_TOKEN": os.environ.get('HUGGING_FACE_HUB_TOKEN'),
        }
        # Only set model-path if using S3 model (non-default), otherwise let it use HF model
        if model_path:
            env["SM_SGLANG_MODEL_PATH"] = vllm_model_id  # /opt/ml/model
        else:
            env["SM_SGLANG_MODEL_PATH"] = model_name  # HuggingFace model name
        # Optional parameters
        if extra_params.get('chat_template'):
            env["SM_SGLANG_CHAT_TEMPLATE"] = extra_params.get('chat_template')
        if extra_params.get("tool_call_parser"):
            env["SM_SGLANG_TOOL_CALL_PARSER"] = extra_params.get("tool_call_parser")
        if extra_params.get("max_model_len"):
            env["SM_SGLANG_CONTEXT_LENGTH"] = extra_params.get("max_model_len")

    else:
        return False,f"Not supported: {engine}"

    logger.info(env)
    pure_model_name = model_name.split('/')[1]

    create_time = datetime.now().strftime('%Y-%m-%d %H:%M')

    if not extra_params.get("endpoint_name"):
        endpoint_name = sagemaker.utils.name_from_base(pure_model_name).replace('.','-').replace('_','-')+f"-{engine}-endpoint"
        endpoint_name = endpoint_name[:63] #must have length less than or equal to 63
    else:
        endpoint_name = extra_params.get("endpoint_name")[:60]
    instance_count = int(extra_params.get("instance_count",1))

    # Create the SageMaker Model object
    # For vLLM/SGLang SageMaker DLC with S3 model files:
    # - Use ModelDataSource dict with S3Prefix for uncompressed model files
    # - SageMaker downloads S3 files to /opt/ml/model
    # - Set HF_MODEL_ID to /opt/ml/model to load from there
    # For HuggingFace models (no model_path):
    # - Set HF_MODEL_ID to the HF model name, DLC downloads from HF Hub
    model_data_config = None
    if model_path:
        # Use S3DataSource dict for uncompressed model files in S3
        # Reference: https://docs.aws.amazon.com/sagemaker/latest/dg/large-model-inference-uncompressed.html
        model_data_config = {
            "S3DataSource": {
                "S3Uri": model_path.rstrip('/') + '/',
                "S3DataType": "S3Prefix",
                "CompressionType": "None"
            }
        }

    model = Model(
            image_uri=lmi_image_uri,
            role=role,
            name=endpoint_name,
            sagemaker_session=sagemaker_session,
            env=env,
            model_data=model_data_config,
    )
    try:
        model.deploy(
            instance_type= instance_type,
            initial_instance_count= instance_count,
            endpoint_name=endpoint_name,
            wait=False,
            accept_eula=True,
            container_startup_health_check_timeout=900,
            inference_ami_version = 'al2-ami-sagemaker-inference-gpu-3-1'
        )
        database.create_endpoint(job_id= job_id,
                                 model_name= model_name,
                                 model_s3_path= model_path,
                                 instance_type= instance_type,
                                 instance_count = instance_count,
                                 endpoint_name= endpoint_name,
                                 endpoint_create_time= create_time,
                                 endpoint_delete_time= None,
                                 extra_config= None,
                                 engine=engine,
                                 enable_lora=enable_lora,
                                 endpoint_status = EndpointStatus.CREATING
                                 )
        return True,endpoint_name
    except Exception as e:
        logger.error(f"failed to create_endpoint:{e}")
        print(e)
        return False,str(e)
    
def deploy_endpoint_byoc(job_id:str,engine:str,instance_type:str,quantize:str,enable_lora:bool,model_name:str,cust_repo_type:str,cust_repo_addr:str,extra_params:Dict[str,Any]) -> tuple[bool,str]:
    repo_type = DownloadSource.MODELSCOPE  if DEFAULT_REGION.startswith('cn') else DownloadSource.DEFAULT
    #统一处理成repo/modelname格式
    model_name=get_model_path_by_name(model_name,repo_type) if model_name and len(model_name.split('/')) < 2 else model_name
    model_path = ''
    #如果是部署微调后的模型
    if not job_id == 'N/A(Not finetuned)':
        jobinfo = sync_get_job_by_id(job_id)
        if not jobinfo.job_status == JobStatus.SUCCESS:
            return CommonResponse(response_id=job_id,response={"error": "job is not ready to deploy"})
        
        if jobinfo.job_type in [JobType.grpo,JobType.dapo,JobType.gspo,JobType.cispo]:
            model_path = jobinfo.output_s3_path + 'huggingface/'
        else:
            # 如果是lora模型，则使用merge之后的路径
            if jobinfo.job_payload['finetuning_method'] == 'lora':
                model_path = jobinfo.output_s3_path + 'finetuned_model_merged/'
            else:
                model_path = jobinfo.output_s3_path + 'finetuned_model/'
    #如果是使用自定义模型
    elif not cust_repo_addr == '' and model_name == '' :
        model_name = cust_repo_addr
        #注册到supported_model中
        register_cust_model(cust_repo_type=repo_type,cust_repo_addr=cust_repo_addr)
        # 仅仅针对中国区需要从模型中心下载上传到s3，在deploy endpint，所以改成后台执行。
        if repo_type == DownloadSource.MODELSCOPE:
            deploy_endpoint_background(job_id=job_id,engine=engine,instance_type=instance_type,quantize=quantize,
                                        enable_lora=enable_lora,model_name=model_name,cust_repo_type=cust_repo_type, 
                                        cust_repo_addr=cust_repo_addr,extra_params=extra_params)
            return True,"Creating endpoint in background"
    #如果是使用原始模型
    elif model_name and job_id == 'N/A(Not finetuned)':
        # 仅仅针对中国区需要从模型中心下载上传到s3，在deploy endpint，所以改成后台执行。
        if repo_type == DownloadSource.MODELSCOPE:
            deploy_endpoint_background(job_id=job_id,engine=engine,instance_type=instance_type,quantize=quantize,
                                        enable_lora=enable_lora,model_name=model_name,cust_repo_type=cust_repo_type, 
                                        cust_repo_addr=cust_repo_addr,extra_params=extra_params)
            return True,"Creating endpoint in background"
    #如果是直接从s3 path加载模型
    elif extra_params.get("s3_model_path"):
        model_path = extra_params.get("s3_model_path")
        model_name = 'custom/custom_model_in_s3' if not model_name else model_name


    logger.info(f"deploy endpoint with engine:{engine},model_name:{model_name},model_path:{model_path}")
    

    return deploy_engine(job_id=job_id,engine=engine,instance_type=instance_type,enable_lora=enable_lora,
                           model_name=model_name,model_path=model_path,extra_params=extra_params)






def deploy_endpoint_background(job_id:str,engine:str,instance_type:str,quantize:str,enable_lora:bool,model_name:str,cust_repo_type:str,cust_repo_addr:str,extra_params:Dict[str,Any]):
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(deploy_endpoint_ms,
                                 job_id=job_id,
                                 engine=engine,
                                 instance_type=instance_type,
                                 quantize=quantize,
                                 enable_lora=enable_lora,
                                 model_name=model_name,
                                 cust_repo_type=cust_repo_type,
                                 cust_repo_addr=cust_repo_addr,
                                 extra_params=extra_params
                                )

def deploy_endpoint_ms(job_id:str,engine:str,instance_type:str,quantize:str,enable_lora:bool,model_name:str,cust_repo_type:str,cust_repo_addr:str,extra_params:Dict[str,Any]) -> tuple[bool,str]:
    pure_model_name = model_name.split('/')[1]
    create_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if not extra_params.get("endpoint_name"):
        endpoint_name = sagemaker.utils.name_from_base(pure_model_name).replace('.','-').replace('_','-')+f"-{engine}-endpoint"
        endpoint_name = endpoint_name[:63] 
    else:
        endpoint_name = extra_params.get("endpoint_name")[:63]
    instance_count = int(extra_params.get("instance_count",1))
    model_path = f"s3://{default_bucket}/original_model_file/{model_name}"
    if engine in ['auto','vllm']:
        lmi_image_uri = VLLM_IMAGE
        # g4dn does not support bf16, need to use fp16
        dtype = 'half' if instance_type.startswith('ml.g4dn') else 'auto'
        env={
            "HF_MODEL_ID": model_name,
            "DTYPE": dtype,
            "LIMIT_MM_PER_PROMPT":extra_params.get('limit_mm_per_prompt',''),
            "S3_MODEL_PATH":model_path,
            "VLLM_ALLOW_LONG_MAX_MODEL_LEN":"1",
            "HF_TOKEN":os.environ.get('HUGGING_FACE_HUB_TOKEN'),
            "MAX_MODEL_LEN":extra_params.get('max_model_len', "12288"), 
            "ENABLE_PREFIX_CACHING": "1" if extra_params.get('enable_prefix_caching') else "0",
            "TENSOR_PARALLEL_SIZE": extra_params.get('tensor_parallel_size',str(get_auto_tensor_parallel_size(instance_type))),
            "MAX_NUM_SEQS": extra_params.get('max_num_seqs','256'),
            "ENFORCE_EAGER": "1" if extra_params.get('enforce_eager') else "0",
            "TOOL_CALL_PARSER": extra_params.get("tool_call_parser","")
        }   
    elif engine in ['sglang']:
        lmi_image_uri = SGLANG_IMAGE
        env={
            "HF_MODEL_ID": model_name,
            "S3_MODEL_PATH":model_path,
            "HF_TOKEN":os.environ.get('HUGGING_FACE_HUB_TOKEN'),
            "TENSOR_PARALLEL_SIZE": extra_params.get('tensor_parallel_size',str(get_auto_tensor_parallel_size(instance_type))),
            "CHAT_TEMPLATE": extra_params.get('chat_template',""),
            "TOOL_CALL_PARSER": extra_params.get("tool_call_parser",""),
            "MEM_FRACTION":extra_params.get("mem_fraction_static","0.7"),
            "CONTEXT_LENGTH":extra_params.get("max_model_len",""),
        }
    else:
        return False,f"Not supported: {engine}"
    logger.info(env)
    # Create the SageMaker Model object. In this example we let LMI configure the deployment settings based on the model architecture  
    model = Model(
            image_uri=lmi_image_uri,
            role=role,
            name=endpoint_name,
            sagemaker_session=sagemaker_session,
            env=env,
            model_data=MODEL_ARTIFACT,
    )
    # 先创建数据库记录，初始端点状态为precreating
    database.create_endpoint(job_id= job_id,
                                model_name= model_name,
                                model_s3_path= '',
                                instance_type= instance_type,
                                instance_count = instance_count,
                                endpoint_name= endpoint_name,
                                endpoint_create_time= create_time,
                                endpoint_delete_time= None,
                                extra_config= None,
                                engine=engine,
                                enable_lora=enable_lora,
                                endpoint_status = EndpointStatus.PRECREATING
                                )
    logger.info(f"pre creating endpoint with model_name:{model_name}")
    #如果是modelscope，则需要下载到本地再上传到S3
    # 构建并返回 S3 URL
    ms_download_and_upload_model(model_repo=model_name,s3_bucket=default_bucket,s3_prefix=f"original_model_file/{model_name}")
    logger.info(f"deploy endpoint with model_name:{model_name},model_path:{model_path}")
    try:
        model.deploy(
            instance_type= instance_type,
            initial_instance_count= instance_count,
            endpoint_name=endpoint_name,
            wait=False,
            accept_eula=True,
            container_startup_health_check_timeout=1800
        )
        #更新端点状态为creating
        database.update_endpoint_status(
                endpoint_name=endpoint_name,
                endpoint_status=EndpointStatus.CREATING
            )
    except Exception as e:
        logger.error(f"create_endpoint:{e}")
        print(e)
        return False,str(e)
    return True,endpoint_name

# 如果使用lmi-dist，trtllm engine则使用这个函数
def deploy_endpoint(job_id:str,engine:str,instance_type:str,quantize:str,enable_lora:bool,model_name:str,cust_repo_type:str,cust_repo_addr:str,extra_params:Dict[str,Any]):
     #统一处理成repo/modelname格式
    repo_type = DownloadSource.MODELSCOPE  if DEFAULT_REGION.startswith('cn') else DownloadSource.DEFAULT
    model_name=get_model_path_by_name(model_name,repo_type) if model_name and len(model_name.split('/')) < 2 else model_name
    #如果是部署微调后的模型
    if not job_id == 'N/A(Not finetuned)':
        jobinfo = sync_get_job_by_id(job_id)
        if not jobinfo.job_status == JobStatus.SUCCESS:
            return CommonResponse(response_id=job_id,response={"error": "job is not ready to deploy"})
        # 如果是lora模型，则使用merge之后的路径
        if jobinfo.job_payload['finetuning_method'] == 'lora':
            model_path = jobinfo.output_s3_path + 'finetuned_model_merged/'
        else:
            model_path = jobinfo.output_s3_path + 'finetuned_model/'
    #如果是使用原始模型
    elif not model_name == '':
        #判断是否是中国区
        repo_type = DownloadSource.MODELSCOPE  if DEFAULT_REGION.startswith('cn') else DownloadSource.DEFAULT
        if repo_type == DownloadSource.DEFAULT:
            model_path = model_name
        else:
            #如果是模型scope，则需要下载到本地
            model_path = ms_download_and_upload_model(model_repo=model_name,s3_bucket=default_bucket,s3_prefix=f"original_model_file/{model_name}")
    #如果是使用自定义模型
    elif not cust_repo_addr == '' and model_name == '' :
        model_name = cust_repo_addr
        #判断是否是中国区
        repo_type = DownloadSource.MODELSCOPE  if DEFAULT_REGION.startswith('cn') else DownloadSource.DEFAULT
        #注册到supported_model中
        register_cust_model(cust_repo_type=repo_type,cust_repo_addr=cust_repo_addr)
        #如果使用hf，则直接用hf repo
        if repo_type == DownloadSource.DEFAULT:
            model_path = cust_repo_addr
        else:
            #如果是模型scope，则需要下载到本地
            model_path = ms_download_and_upload_model(model_repo=cust_repo_addr,s3_bucket=default_bucket,s3_prefix=f"original_model_file/{model_name}")
        
    else:
        return CommonResponse(response_id=job_id,response={"error": "no model_name is provided"})
    logger.info(f"deploy endpoint with model_path:{model_path}")
    
    # Fetch the uri of the LMI container that supports vLLM, LMI-Dist, HuggingFace Accelerate backends
    if engine == 'trt-llm':
        lmi_image_uri = image_uris.retrieve(framework="djl-tensorrtllm", version="0.29.0", region=DEFAULT_REGION)
    else:
        lmi_image_uri = image_uris.retrieve(framework="djl-lmi", version="0.29.0", region=DEFAULT_REGION)

    env={
        "HF_MODEL_ID": model_path,
        "OPTION_ROLLING_BATCH":  engine,
        "TENSOR_PARALLEL_DEGREE": "max",
        "OPTION_TRUST_REMOTE_CODE": "true",
         "HUGGING_FACE_HUB_TOKEN":os.environ.get('HUGGING_FACE_HUB_TOKEN'),
    }
    if enable_lora:
        env['OPTION_ENABLE_LORA'] = True
        
    if engine == 'trt-llm':
        env['OPTION_MAX_NUM_TOKENS'] = '50000'
        env['OPTION_ENABLE_KV_CACHE_REUSE'] = "true"
        
    #量化设置
    if engine == 'scheduler' and quantize in ['bitsandbytes8','bitsandbytes4']:
        env['OPTION_QUANTIZE'] = quantize
    elif engine == 'llm-dist' and  quantize in ['awq','gptq']:
        env['OPTION_QUANTIZE'] = quantize
    elif engine == 'trt-llm' and  quantize in ['awq','smoothquant']:
        env['OPTION_QUANTIZE'] = quantize
    
    
    create_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    pure_model_name = model_name.split('/')[1]
    endpoint_name = sagemaker.utils.name_from_base(pure_model_name).replace('.','-').replace('_','-')
    instance_count = int(extra_params.get("instance_count",1))
    # Create the SageMaker Model object. In this example we let LMI configure the deployment settings based on the model architecture  
    model = Model(
            image_uri=lmi_image_uri,
            role=role,
            name=endpoint_name,
            sagemaker_session=sagemaker_session,
            env=env,
    )
    try:
        model.deploy(
            instance_type= instance_type,
            initial_instance_count=instance_count,
            endpoint_name=endpoint_name,
            wait=False,
            accept_eula=True,
            container_startup_health_check_timeout=1800
        )
        database.create_endpoint(job_id= job_id,
                                 model_name= model_name,
                                 model_s3_path= model_path,
                                 instance_type= instance_type,
                                 instance_count = instance_count,
                                 endpoint_name= endpoint_name,
                                 endpoint_create_time= create_time,
                                 endpoint_delete_time= None,
                                 extra_config= None,
                                 engine=engine,
                                 enable_lora=enable_lora,
                                 endpoint_status = EndpointStatus.CREATING
                                 )
    except Exception as e:
        logger.error(f"create_endpoint:{e}")
        return False,str(e)
    
    return True,endpoint_name

def get_endpoint_engine(endpoint_name:str) -> str:
    ret =  database.get_endpoint(endpoint_name)
    return ret[0] if ret else ''


def get_endpoint_info(endpoint_name: str) -> dict:
    """
    Get full endpoint info including deployment target and HyperPod cluster info.

    Returns:
        Dict with endpoint info or None if not found.
        Keys: engine, deployment_target, hyperpod_cluster_id, extra_config, etc.
    """
    ret = database.get_endpoint_full(endpoint_name)
    if not ret:
        return None

    # Parse the result based on column order
    # Columns: id, job_id, endpoint_name, model_name, engine, enable_lora, instance_type,
    #          instance_count, model_s3_path, endpoint_status, endpoint_create_time,
    #          endpoint_delete_time, extra_config, deployment_target, hyperpod_cluster_id
    if len(ret) >= 15:
        return {
            'job_id': ret[1],
            'endpoint_name': ret[2],
            'model_name': ret[3],
            'engine': ret[4],
            'enable_lora': ret[5],
            'instance_type': ret[6],
            'instance_count': ret[7],
            'model_s3_path': ret[8],
            'endpoint_status': ret[9],
            'extra_config': ret[12],
            'deployment_target': ret[13] or 'sagemaker',
            'hyperpod_cluster_id': ret[14]
        }
    else:
        # Old format without deployment_target
        return {
            'endpoint_name': ret[2] if len(ret) > 2 else None,
            'engine': ret[4] if len(ret) > 4 else None,
            'deployment_target': 'sagemaker',
            'hyperpod_cluster_id': None,
            'extra_config': ret[12] if len(ret) > 12 else None
        }


# =============================================================================
# Endpoint List Function
# =============================================================================

def list_endpoints(request:ListEndpointsRequest) -> Dict[EndpointInfo,int]:
    if thread_pool:
        logger.info(f"thread pool:{thread_pool}")
    results = database.list_endpoints(query_terms=request.query_terms,page_size=request.page_size,page_index=request.page_index)

    info = []
    for row in results:
        # Handle both old format (13 columns) and new format (15 columns with deployment_target, hyperpod_cluster_id)
        if len(row) >= 15:
            _, job_id, endpoint_name, model_name, engine, enable_lora, instance_type, instance_count, model_s3_path, endpoint_status, endpoint_create_time, endpoint_delete_time, extra_config, deployment_target, hyperpod_cluster_id = row[:15]
        else:
            _, job_id, endpoint_name, model_name, engine, enable_lora, instance_type, instance_count, model_s3_path, endpoint_status, endpoint_create_time, endpoint_delete_time, extra_config = row[:13]
            deployment_target = 'sagemaker'
            hyperpod_cluster_id = None

        info.append(EndpointInfo(
            job_id=job_id,
            endpoint_name=endpoint_name,
            model_name=model_name,
            engine=engine,
            enable_lora=enable_lora,
            instance_type=instance_type,
            instance_count=instance_count,
            model_s3_path=model_s3_path,
            endpoint_status=endpoint_status,
            endpoint_create_time=endpoint_create_time,
            endpoint_delete_time=endpoint_delete_time,
            extra_config=extra_config,
            deployment_target=deployment_target or 'sagemaker',
            hyperpod_cluster_id=hyperpod_cluster_id
        ))

    count = database.count_endpoints(query_terms=request.query_terms)

    # Start background threads to poll and update endpoint status
    for endpoint_info in info:
        if endpoint_info.endpoint_status == EndpointStatus.CREATING and endpoint_info.endpoint_name not in thread_pool:
            if endpoint_info.deployment_target == 'hyperpod':
                # HyperPod endpoint - use Kubernetes API to check status
                if endpoint_info.hyperpod_cluster_id:
                    thread = threading.Thread(
                        target=check_hyperpod_deployment_status,
                        args=(endpoint_info.endpoint_name, endpoint_info.hyperpod_cluster_id),
                        daemon=True
                    )
                    logger.info(f'[HyperPod Status] Starting polling thread for {endpoint_info.endpoint_name}')
                    with endpoints_lock:
                        thread_pool[endpoint_info.endpoint_name] = 1
                        thread.start()
                else:
                    logger.warning(f'[HyperPod Status] No cluster_id for endpoint {endpoint_info.endpoint_name}, skipping status polling')
            else:
                # SageMaker endpoint - use SageMaker API to check status
                thread = threading.Thread(target=check_deployment_status, args=(endpoint_info.endpoint_name,))
                logger.info(endpoint_info.endpoint_name)
                with endpoints_lock:
                    thread_pool[endpoint_info.endpoint_name] = 1
                    thread.start()


    return info,count