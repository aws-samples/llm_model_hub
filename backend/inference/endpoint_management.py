import time
import uuid
import sys
sys.path.append('../')
import json
import os
import logging
from typing import Annotated, Sequence, TypedDict, Dict, Optional,List, Any,TypedDict
import shutil
import tempfile
from modelscope.hub.snapshot_download import snapshot_download
from model.data_model import *
from db_management.database import DatabaseWrapper
from datetime import datetime
from training.jobs import sync_get_job_by_id
from utils.config import boto_sess,role,sagemaker_session,DEFAULT_REGION,SUPPORTED_MODELS_FILE,DEFAULT_TEMPLATE_FILE,default_bucket,VLLM_IMAGE,MODEL_ARTIFACT,instance_gpus_map
from utils.get_factory_config import get_model_path_by_name
from utils.llamafactory.extras.constants import register_model_group,DownloadSource,DEFAULT_TEMPLATE,SUPPORTED_MODELS
from collections import OrderedDict, defaultdict
from sagemaker import image_uris, Model
import sagemaker
import pickle
from logger_config import setup_logger
import threading
database = DatabaseWrapper()
logger = setup_logger('endpoint_management.py', log_file='deployment.log', level=logging.INFO)



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


def ms_download_and_upload_model(model_repo, s3_bucket, s3_prefix):
    # 创建临时目录作为缓存
    with tempfile.TemporaryDirectory() as cache_dir:
        try:
            # 从 ModelScope 下载模型到缓存目录
            local_dir = snapshot_download(model_repo, cache_dir=cache_dir)
            
            # 配置 S3 客户端
            s3_client = boto_sess.client('s3')
            
            # 上传模型文件到 S3
            for root, _, files in os.walk(local_dir):
                for file in files:
                    local_path = os.path.join(root, file)
                    relative_path = os.path.relpath(local_path, local_dir)
                    s3_key = os.path.join(s3_prefix, relative_path)
                    s3_client.upload_file(local_path, s3_bucket, s3_key)
            
            # 构建并返回 S3 URL
            s3_url = f"s3://{s3_bucket}/{s3_prefix}"
            return s3_url
        
        finally:
            # 清理临时目录（这步可以省略，因为使用了 with tempfile.TemporaryDirectory()）
            if os.path.exists(cache_dir):
                shutil.rmtree(cache_dir)
                

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
        
def delete_endpoint(endpoint_name:str) ->bool:
    client = boto_sess.client('sagemaker')
    try:
        # database.update_endpoint_status(
        #         endpoint_name=endpoint_name,
        #         endpoint_status=EndpointStatus.TERMINATED,
        #         endpoint_delete_time= datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        #     )
        database.delete_endpoint(endpoint_name=endpoint_name)
        client.delete_endpoint(EndpointName=endpoint_name)
        client.delete_endpoint_config(EndpointConfigName=endpoint_name)
        client.delete_model(ModelName=endpoint_name)
        return True
    except Exception as e:
        logger.error(e)
        return True

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
    with open(DEFAULT_TEMPLATE_FILE, 'wb') as f:
        pickle.dump(DEFAULT_TEMPLATE, f)

def get_auto_tensor_parallel_size(instance_type:str) -> int:
    return instance_gpus_map.get(instance_type, 1)
def deploy_endpoint_byoc(job_id:str,engine:str,instance_type:str,quantize:str,enable_lora:bool,model_name:str,cust_repo_type:str,cust_repo_addr:str,extra_params:Dict[str,Any]) -> Dict[bool,str]:
    repo_type = DownloadSource.MODELSCOPE  if DEFAULT_REGION.startswith('cn') else DownloadSource.DEFAULT
    #统一处理成repo/modelname格式
    model_name=get_model_path_by_name(model_name,repo_type) if model_name and len(model_name.split('/')) < 2 else model_name
    model_path = ''
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
    # elif not model_name == '':
        #判断是否是中国区
        # model_path = ''
        # if not repo_type == DownloadSource.DEFAULT:
        #     #如果是模型scope，则需要下载到本地
        #     model_path = ms_download_and_upload_model(model_repo=model_name,s3_bucket=default_bucket,s3_prefix=f"original_model_file/{model_name}")
    #如果是使用自定义模型
    elif not cust_repo_addr == '' and model_name == '' :
        # model_name = cust_repo_addr.split('/')[1]
        model_name = cust_repo_addr
        #判断是否是中国区
        # repo_type = DownloadSource.MODELSCOPE  if DEFAULT_REGION.startswith('cn') else DownloadSource.DEFAULT
        #注册到supported_model中
        register_cust_model(cust_repo_type=repo_type,cust_repo_addr=cust_repo_addr)
        #如果使用hf，则直接用hf repo
        # if repo_type == DownloadSource.DEFAULT:
        #     model_path = ''
        # else:
        #     #如果是模型scope，则需要下载到本地
        #     model_path = ms_download_and_upload_model(model_repo=cust_repo_addr,s3_bucket=default_bucket,s3_prefix=f"original_model_file/{model_name}")
        
    # else:
    #     return CommonResponse(response_id=job_id,response={"error": "no model_name is provided"})
    logger.info(f"deploy endpoint with model_name:{model_name},model_path:{model_path}")
    
    lmi_image_uri = VLLM_IMAGE

    env={
        "HF_MODEL_ID": model_name,
        "S3_MODEL_PATH":model_path,
         "HF_TOKEN":os.environ.get('HUGGING_FACE_HUB_TOKEN'),
         "MAX_MODEL_LEN":extra_params.get('max_model_len', os.environ.get('MAX_MODEL_LEN',"12288")), 
         "TENSOR_PARALLEL_SIZE": extra_params.get('tensor_parallel_size',str(get_auto_tensor_parallel_size(instance_type)))
    }
    if DEFAULT_REGION.startswith('cn'):
        env['VLLM_USE_MODELSCOPE']='1'

    print(env)
    pure_model_name = model_name.split('/')[1]

    create_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    endpoint_name = sagemaker.utils.name_from_base(pure_model_name).replace('.','-').replace('_','-')

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
            initial_instance_count=1,
            endpoint_name=endpoint_name,
            wait=False,
            accept_eula=True,
            container_startup_health_check_timeout=900
        )
        database.create_endpoint(job_id= job_id,
                                 model_name= model_name,
                                 model_s3_path= model_path,
                                 instance_type= instance_type,
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
        print(e)
        return False,str(e)
    
    return True,endpoint_name

# 如果job_id="",则使用model_name原始模型
def deploy_endpoint(job_id:str,engine:str,instance_type:str,quantize:str,enable_lora:bool,model_name:str,cust_repo_type:str,cust_repo_addr:str) -> Dict[bool,str]:
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
        # model_name = jobinfo.job_payload["model_name"]
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
    
    #patches   
    ##Mistral-7B 在g5.2x下kv cache不能超过12k，否则会报错  
    if engine == 'vllm' and instance_type.endswith('2xlarge'):
        env['OPTION_MAX_MODEL_LEN'] = '12288'
    
    
    create_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    pure_model_name = model_name.split('/')[1]
    endpoint_name = sagemaker.utils.name_from_base(pure_model_name).replace('.','-').replace('_','-')

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
            initial_instance_count=1,
            endpoint_name=endpoint_name,
            wait=False,
            accept_eula=True,
            container_startup_health_check_timeout=1800
        )
        database.create_endpoint(job_id= job_id,
                                 model_name= model_name,
                                 model_s3_path= model_path,
                                 instance_type= instance_type,
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
    

def list_endpoints(request:ListEndpointsRequest) -> Dict[EndpointInfo,int]:
    logger.info(f"thread pool:{thread_pool}")
    results = database.list_endpoints(query_terms=request.query_terms,page_size=request.page_size,page_index=request.page_index)
    info =  [EndpointInfo(job_id=job_id,
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
                            extra_config=extra_config
                    ) 
            for _,job_id,endpoint_name,model_name,engine,enable_lora,instance_type,instance_count,model_s3_path,endpoint_status,endpoint_create_time,endpoint_delete_time,extra_config in results]
    
    count = database.count_endpoints(query_terms=request.query_terms)
    
    #启动一个线程来更新状态
    for endpoint_info in info:
        if endpoint_info.endpoint_status == EndpointStatus.CREATING and endpoint_info.endpoint_name not in thread_pool :
            thread = threading.Thread(target=check_deployment_status, args=(endpoint_info.endpoint_name,))
            logger.info(endpoint_info.endpoint_name )
            with endpoints_lock:
                thread_pool[endpoint_info.endpoint_name] = 1
                thread.start()
            
        
    return info,count