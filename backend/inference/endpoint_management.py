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
from utils.config import boto_sess,role,sagemaker_session,DEFAULT_REGION,SUPPORTED_MODELS_FILE,default_bucket,VLLM_IMAGE,SGLANG_IMAGE,MODEL_ARTIFACT,get_auto_tensor_parallel_size
from utils.get_factory_config import get_model_path_by_name
from utils.llamafactory.extras.constants import register_model_group,DownloadSource,SUPPORTED_MODELS
from sagemaker import image_uris, Model
import sagemaker
import pickle
from logger_config import setup_logger
import threading
import concurrent.futures
database = DatabaseWrapper()
logger = setup_logger('endpoint_management.py', log_file='deployment.log', level=logging.INFO)
DEFAULT_CACHE_DIR = "./model_cache"  # 默认缓存目录
CACHE_EXPIRY_DAYS = 30  # 缓存有效期(天)


endpoints_lock = threading.Lock()
thread_pool = {}
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
    Download model from HuggingFace Hub and upload to S3.

    Args:
        model_repo: HuggingFace model repository (e.g., 'Qwen/Qwen2.5-1.5B-Instruct')
        s3_bucket: S3 bucket name
        s3_prefix: S3 path prefix
        cache_dir: Local cache directory

    Returns:
        S3 URL where model was uploaded
    """
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

        logger.info(f"Model downloaded to {local_dir}, uploading to S3...")
        s3_client = boto_sess.client('s3')

        # Upload model files to S3
        file_count = 0
        for root, _, files in os.walk(local_dir):
            for file in files:
                local_path = os.path.join(root, file)
                relative_path = os.path.relpath(local_path, local_dir)
                s3_key = os.path.join(s3_prefix, relative_path)
                s3_client.upload_file(local_path, s3_bucket, s3_key)
                file_count += 1
                if file_count % 10 == 0:
                    logger.info(f"Uploaded {file_count} files...")

        # Return S3 URL
        s3_url = f"s3://{s3_bucket}/{s3_prefix}"
        logger.info(f"Successfully downloaded {model_repo} and uploaded to {s3_url} ({file_count} files)")
        return s3_url

    except Exception as e:
        logger.error(f"Error downloading/uploading model {model_repo}: {str(e)}")
        raise


def ms_download_and_upload_model(model_repo, s3_bucket, s3_prefix, cache_dir=DEFAULT_CACHE_DIR):
    """
    从ModelScope下载模型并上传到S3

    Args:
        model_repo: ModelScope模型仓库名
        s3_bucket: S3存储桶名
        s3_prefix: S3路径前缀
        cache_dir: 缓存目录路径,默认为DEFAULT_CACHE_DIR
    """
    try:
        # 创建缓存目录(如果不存在)
        os.makedirs(cache_dir, exist_ok=True)
        
        # 清理过期缓存
        cleanup_expired_cache(cache_dir)
        
        # 从ModelScope下载模型到缓存目录
        local_dir = snapshot_download(model_repo, cache_dir=cache_dir)
        
        s3_client = boto_sess.client('s3')
        
        # 上传模型文件到S3
        for root, _, files in os.walk(local_dir):
            for file in files:
                local_path = os.path.join(root, file)
                relative_path = os.path.relpath(local_path, local_dir)
                s3_key = os.path.join(s3_prefix, relative_path)
                s3_client.upload_file(local_path, s3_bucket, s3_key)
        
        # 构建并返回S3 URL
        s3_url = f"s3://{s3_bucket}/{s3_prefix}"
        logger.info(f"Successfully downloaded {model_repo} and uploaded to {s3_url}")
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
    if engine in ['auto','vllm']:
        lmi_image_uri = VLLM_IMAGE
        dtype = 'half' if instance_type.startswith('ml.g4dn') else 'auto' # g4dn does not support bf16, need to use fp16
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
        if DEFAULT_REGION.startswith('cn'):
            env['VLLM_USE_MODELSCOPE']='1'

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
            "CONTEXT_LENGTH":extra_params.get("context_length",""),
        }
    
    else:
        return False,f"Not supported: {engine}"

    logger.info(env)
    pure_model_name = model_name.split('/')[1]

    create_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    if not extra_params.get("endpoint_name"):
        endpoint_name = sagemaker.utils.name_from_base(pure_model_name).replace('.','-').replace('_','-')+f"-{engine}-endpoint"
        endpoint_name = endpoint_name[:63] #must have length less than or equal to 63
    else:
        endpoint_name = extra_params.get("endpoint_name")[:63]
    instance_count = int(extra_params.get("instance_count",1))

    # Create the SageMaker Model object. In this example we let LMI configure the deployment settings based on the model architecture  
    model = Model(
            image_uri=lmi_image_uri,
            role=role,
            name=endpoint_name,
            sagemaker_session=sagemaker_session,
            env=env,
            model_data=MODEL_ARTIFACT,
    )
    try:
        model.deploy(
            instance_type= instance_type,
            initial_instance_count= instance_count,
            endpoint_name=endpoint_name,
            wait=False,
            accept_eula=True,
            container_startup_health_check_timeout=900
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
            "CONTEXT_LENGTH":extra_params.get("context_length",""),
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
    """
    import threading

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
    """
    from inference.hyperpod_inference import (
        deploy_to_hyperpod,
        deploy_to_hyperpod_advanced,
        AutoScalingConfig,
        KVCacheConfig,
        IntelligentRoutingConfig
    )

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
    use_advanced_deploy = enable_autoscaling or enable_kv_cache or enable_intelligent_routing

    # Generate endpoint name
    # Kubernetes names have 63 char limit
    # When intelligent routing is enabled, HyperPod operator creates:
    #   - Service: {endpoint_name}-{namespace}-routing-service (adds 24 chars for "-default-routing-service")
    #   - Ingress: alb-{endpoint_name}-{namespace} (adds 12 chars for "alb--default")
    # So for intelligent routing: 63 - 24 = 39 chars max
    # For normal HyperPod: 63 - 12 = 51 chars max (for prefetch-{name}-inf container)
    max_name_len = 39 if enable_intelligent_routing else 51
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
        'use_public_alb': use_public_alb
    }

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
        # Note: We need to add a method to update model_s3_path, for now update via extra_config
        extra_config_data['model_s3_path'] = model_s3_path

        # Update status to CREATING
        database.update_endpoint_status(endpoint_name=endpoint_name, endpoint_status=EndpointStatus.CREATING)

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

            # Deploy with advanced configuration
            result = deploy_to_hyperpod_advanced(
                eks_cluster_name=eks_cluster_name,
                endpoint_name=endpoint_name,
                model_name=model_name,
                instance_type=instance_type,
                engine=engine,
                replicas=replicas,
                namespace=namespace,
                region=region,
                model_s3_path=model_s3_path,
                huggingface_model_id=None,  # Using S3 path instead
                autoscaling=autoscaling_config,
                kv_cache=kv_cache_config,
                intelligent_routing=intelligent_routing_config,
                tensor_parallel_size=extra_params.get('tensor_parallel_size'),
                max_model_len=extra_params.get('max_model_len'),
                enable_prefix_caching=extra_params.get('enable_prefix_caching', False)
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
                namespace=namespace,
                region=region,
                model_s3_path=model_s3_path,
                huggingface_model_id=None  # Using S3 path instead
            )

        if result.get('success'):
            logger.info(f"[HyperPod Deploy Background] Deployment initiated successfully: {endpoint_name}")

            # Configure public ALB if requested using recreate approach
            if use_public_alb:
                logger.info(f"[HyperPod Deploy Background] Scheduling public ALB configuration (recreate approach)...")
                import time as time_module
                from inference.hyperpod_inference import recreate_ingress_with_scheme

                # Retry ALB configuration with exponential backoff
                # Need to wait for HyperPod operator to create the Ingress first
                max_retries = 5
                retry_delay = 60  # Initial delay - Ingress creation takes time
                alb_configured = False

                for attempt in range(max_retries):
                    logger.info(f"[HyperPod Deploy Background] Waiting {retry_delay}s before ALB configuration (attempt {attempt + 1}/{max_retries})...")
                    time_module.sleep(retry_delay)

                    # Use recreate_ingress_with_scheme to delete internal ALB and recreate with internet-facing
                    alb_result = recreate_ingress_with_scheme(
                        eks_cluster_name=eks_cluster_name,
                        endpoint_name=endpoint_name,
                        namespace=namespace,
                        region=region or DEFAULT_REGION,
                        internet_facing=True,
                        wait_for_cleanup=60  # Wait for ALB cleanup before recreating
                    )

                    if alb_result.get('success'):
                        logger.info(f"[HyperPod Deploy Background] Public ALB configured: {alb_result.get('alb_hostname')}")
                        alb_configured = True
                        break
                    else:
                        error = alb_result.get('error', 'Unknown error')
                        if 'not found' in error.lower() and attempt < max_retries - 1:
                            logger.info(f"[HyperPod Deploy Background] Ingress not ready yet, will retry...")
                            retry_delay = min(retry_delay * 1.5, 90)  # Increase delay, max 90s
                        else:
                            logger.warning(f"[HyperPod Deploy Background] ALB configuration attempt {attempt + 1} failed: {error}")

                if not alb_configured:
                    logger.warning(f"[HyperPod Deploy Background] Failed to configure public ALB after {max_retries} attempts. The endpoint is still accessible via internal service.")

            return True, endpoint_name
        else:
            error_msg = result.get('message', 'Unknown error')
            logger.error(f"[HyperPod Deploy Background] Deployment failed: {error_msg}")
            # Update endpoint status with error
            extra_config_data['error'] = f"DeploymentFailed: {error_msg}"
            database.update_endpoint_status(endpoint_name=endpoint_name, endpoint_status=EndpointStatus.FAILED)
            return False, error_msg

    except Exception as e:
        import traceback
        error_msg = str(e)
        logger.error(f"[HyperPod Deploy Background] Exception: {error_msg}")
        logger.error(f"[HyperPod Deploy Background] Traceback: {traceback.format_exc()}")
        # Update endpoint status with error
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
        IntelligentRoutingConfig
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
    # Get the number of instances of the requested type in the cluster
    instance_groups = cluster_info.instance_groups or []
    available_instance_count = 0
    for ig in instance_groups:
        if isinstance(ig, dict) and ig.get('instance_type') == instance_type:
            available_instance_count += ig.get('instance_count', 0)

    if available_instance_count == 0:
        # Instance type not found in cluster
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
        # All instances are occupied
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
        # HyperPod Inference Operator only supports S3 and FSx, not HuggingFace directly
        logger.info(f"[HyperPod Deploy] HuggingFace model detected: {model_name}")
        logger.info(f"[HyperPod Deploy] Starting background download and deployment...")

        # Start background deployment with HuggingFace model download
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

    # Get HyperPod config values first (needed to determine endpoint name length)
    hyperpod_config = hyperpod_config or {}
    replicas = hyperpod_config.get('replicas', 1)
    namespace = hyperpod_config.get('namespace', 'default')
    instance_count = int(extra_params.get("instance_count", 1))

    # Check if advanced features are requested
    enable_autoscaling = hyperpod_config.get('enable_autoscaling', False)
    enable_kv_cache = hyperpod_config.get('enable_kv_cache', False)
    enable_intelligent_routing = hyperpod_config.get('enable_intelligent_routing', False)

    # Generate endpoint name
    # Kubernetes names have 63 char limit
    # When intelligent routing is enabled, HyperPod operator creates:
    #   - Service: {endpoint_name}-{namespace}-routing-service (adds 24 chars for "-default-routing-service")
    #   - Ingress: alb-{endpoint_name}-{namespace} (adds 12 chars for "alb--default")
    # So for intelligent routing: 63 - 24 = 39 chars max
    # For normal HyperPod: 63 - 12 = 51 chars max (for prefetch-{name}-inf container)
    max_name_len = 39 if enable_intelligent_routing else 51
    pure_model_name = model_name.split('/')[-1] if '/' in model_name else model_name
    create_time = datetime.now().strftime('%Y-%m-%d %H:%M')

    if extra_params.get("endpoint_name"):
        endpoint_name = extra_params.get("endpoint_name")[:max_name_len].rstrip('-')
    else:
        endpoint_name = sagemaker.utils.name_from_base(pure_model_name).replace('.', '-').replace('_', '-') + f"-{engine}-hp"
        endpoint_name = endpoint_name[:max_name_len].rstrip('-')

    use_public_alb = hyperpod_config.get('use_public_alb', False)
    use_advanced_deploy = enable_autoscaling or enable_kv_cache or enable_intelligent_routing

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
                # When KV cache is enabled with a backend, L2 cache should be enabled
                kv_cache_backend = hyperpod_config.get('kv_cache_backend', 'tieredstorage')
                # Enable L2 cache if a backend is specified (tieredstorage or redis)
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

            # Deploy with advanced configuration
            result = deploy_to_hyperpod_advanced(
                eks_cluster_name=eks_cluster_name,
                endpoint_name=endpoint_name,
                model_name=model_name,
                instance_type=instance_type,
                engine=engine,
                replicas=replicas,
                namespace=namespace,
                region=region,
                model_s3_path=model_path,
                huggingface_model_id=huggingface_model_id,
                autoscaling=autoscaling_config,
                kv_cache=kv_cache_config,
                intelligent_routing=intelligent_routing_config,
                tensor_parallel_size=extra_params.get('tensor_parallel_size'),
                max_model_len=extra_params.get('max_model_len'),
                enable_prefix_caching=extra_params.get('enable_prefix_caching', False)
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
                namespace=namespace,
                region=region,
                model_s3_path=model_path,
                huggingface_model_id=huggingface_model_id
            )

        # Log the full deployment result for debugging
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

            # Create database record
            # Note: create_endpoint handles JSON encoding of extra_config internally
            database.create_endpoint(
                job_id=job_id,
                model_name=model_name,
                model_s3_path=model_path,
                instance_type=instance_type,
                instance_count=instance_count,
                endpoint_name=endpoint_name,
                endpoint_create_time=create_time,
                endpoint_delete_time=None,
                extra_config=extra_config_data,  # Pass dict directly, not JSON string
                engine=engine,
                enable_lora=enable_lora,
                endpoint_status=EndpointStatus.CREATING,
                deployment_target='hyperpod',
                hyperpod_cluster_id=hyperpod_cluster_id
            )

            # Configure public ALB if requested using recreate approach in background
            if use_public_alb:
                logger.info(f"[HyperPod Deploy] Scheduling public ALB configuration for {endpoint_name} (recreate approach)")
                import threading
                from inference.hyperpod_inference import recreate_ingress_with_scheme
                import time as time_module

                def configure_public_alb_background():
                    """Configure public ALB in background after Ingress is created with retry logic."""
                    try:
                        # Retry ALB configuration with exponential backoff
                        # Need to wait for HyperPod operator to create the Ingress first
                        max_retries = 5
                        retry_delay = 60  # Initial delay - Ingress creation takes time
                        alb_configured = False

                        for attempt in range(max_retries):
                            logger.info(f"[Background ALB] Waiting {retry_delay}s before ALB configuration (attempt {attempt + 1}/{max_retries})...")
                            time_module.sleep(retry_delay)

                            # Use recreate_ingress_with_scheme to delete internal ALB and recreate with internet-facing
                            alb_result = recreate_ingress_with_scheme(
                                eks_cluster_name=eks_cluster_name,
                                endpoint_name=endpoint_name,
                                namespace=namespace,
                                region=region or DEFAULT_REGION,
                                internet_facing=True,
                                wait_for_cleanup=60  # Wait for ALB cleanup before recreating
                            )

                            if alb_result.get('success'):
                                logger.info(f"[Background ALB] Public ALB configured successfully: {alb_result.get('alb_hostname')}")
                                alb_configured = True
                                break
                            else:
                                error = alb_result.get('error', 'Unknown error')
                                if 'not found' in error.lower() and attempt < max_retries - 1:
                                    logger.info(f"[Background ALB] Ingress not ready yet, will retry...")
                                    retry_delay = min(retry_delay * 1.5, 90)  # Increase delay, max 90s
                                else:
                                    logger.warning(f"[Background ALB] ALB configuration attempt {attempt + 1} failed: {error}")

                        if not alb_configured:
                            logger.warning(f"[Background ALB] Failed to configure public ALB after {max_retries} attempts. The endpoint is still accessible via internal service.")
                    except Exception as e:
                        logger.error(f"[Background ALB] Error configuring public ALB: {e}")

                alb_thread = threading.Thread(target=configure_public_alb_background, daemon=True)
                alb_thread.start()

            return True, endpoint_name
        elif result.get('error') == 'CRD_NOT_FOUND':
            # Auto-setup the inference operator in background if CRD is not found
            logger.info(f"CRD not found on cluster {eks_cluster_name}, starting background operator setup...")
            try:
                import threading
                from inference.hyperpod_operator_setup import setup_inference_operator

                # Get HyperPod cluster ARN
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
                            account_id=None  # Auto-detect
                        )
                        if setup_success:
                            logger.info(f"[Background] HyperPod Inference Operator setup completed: {setup_msg}")
                        else:
                            logger.error(f"[Background] HyperPod Inference Operator setup failed: {setup_msg}")
                    except Exception as e:
                        logger.error(f"[Background] HyperPod Inference Operator setup error: {e}")

                # Start background thread
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
            # Log detailed error information
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
    

def list_endpoints(request:ListEndpointsRequest) -> Dict[EndpointInfo,int]:
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

    #启动一个线程来更新状态 (only for SageMaker endpoints)
    for endpoint_info in info:
        if endpoint_info.endpoint_status == EndpointStatus.CREATING and endpoint_info.endpoint_name not in thread_pool:
            if endpoint_info.deployment_target != 'hyperpod':
                thread = threading.Thread(target=check_deployment_status, args=(endpoint_info.endpoint_name,))
                logger.info(endpoint_info.endpoint_name )
                with endpoints_lock:
                    thread_pool[endpoint_info.endpoint_name] = 1
                    thread.start()


    return info,count