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
from utils.config import boto_sess,role,sagemaker_session,DEFAULT_REGION,SUPPORTED_MODELS_FILE,default_bucket,VLLM_IMAGE,SGLANG_IMAGE,MODEL_ARTIFACT,instance_gpus_map
from utils.get_factory_config import get_model_path_by_name
from utils.llamafactory.extras.constants import register_model_group,DownloadSource,SUPPORTED_MODELS
from sagemaker import image_uris, Model
import sagemaker
import boto3
import pickle
from logger_config import setup_logger
import threading
import concurrent.futures
database = DatabaseWrapper()
logger = setup_logger('endpoint_management.py', log_file='deployment.log', level=logging.INFO)
DEFAULT_CACHE_DIR = "./model_cache"  # 默认缓存目录
CACHE_EXPIRY_DAYS = 30  # 缓存有效期(天)
sm_client = boto3.client(service_name="sagemaker")
aas_client = sagemaker_session.boto_session.client("application-autoscaling")
cloudwatch_client = sagemaker_session.boto_session.client("cloudwatch")
scalable_dimension = "sagemaker:inference-component:DesiredCopyCount"

endpoints_lock = threading.Lock()
thread_pool = {}
def check_deployment_status(endpoint_name:str):
    logger.info('a check_deployment_status thread start')
    while True:
        status  = get_endpoint_status(endpoint_name)
        if status in [EndpointStatus.CREATING,EndpointStatus.PRECREATING]:
            time.sleep(10)
        else:
            with endpoints_lock:
                thread_pool.pop(endpoint_name)
            logger.info('a check_deployment_status thread exit')
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

def get_inference_component_copies(inference_component_name):
    try:
        response = sm_client.describe_inference_component(
            InferenceComponentName=inference_component_name
        )
        return dict(current_copy_count =response['RuntimeConfig']['CurrentCopyCount'],
                    desired_copy_count =response['RuntimeConfig']['DesiredCopyCount'])
    except Exception as e:
        logger.error(f"Error checking inference component status: {str(e)}")
        return {}  
    
def check_inference_component_status(inference_component_name):
    try:
        response = sm_client.describe_inference_component(
            InferenceComponentName=inference_component_name
        )
        status = response['InferenceComponentStatus']
        
        if status in ['InService']:
            return ICStatus.INSERVICE
        elif status in ['Creating']:
            logger.info(f"Inference component {inference_component_name} is still being deployed...")
            return ICStatus.CREATING
        elif status in [ 'Updating']:
            logger.info(f"Inference component {inference_component_name} is still being updated...")
            return ICStatus.UPDATING
        else:
            logger.error(f"Inference component deployment failed with status: {status}")
            # You might want to check the FailureReason if available
            if 'FailureReason' in response:
                logger.error(f"Failure reason: {response['FailureReason']}")
            return ICStatus.FAILED
            
    except Exception as e:
        logger.error(f"Error checking inference component status: {str(e)}")
        return ICStatus.NOTFOUND
    
def register_as_policy(inference_component_name,min_copy_count,max_copy_count,target_tps,in_cooldown=300,out_cooldown=300):  
    # 先注册resource_id  
    resource_id = f"inference-component/{inference_component_name}"
    service_namespace = "sagemaker"
    aas_client.register_scalable_target(
        ServiceNamespace=service_namespace,
        ResourceId=resource_id,
        ScalableDimension=scalable_dimension,
        MinCapacity=min_copy_count,
        MaxCapacity=max_copy_count,
    )
    
    # The policy name for the target traking policy
    target_tracking_policy_name = f"Target-tracking-policy-{inference_component_name}"

    # Configure Target Tracking Scaling Policy  
    aas_client.put_scaling_policy(
        PolicyName=target_tracking_policy_name,
        PolicyType="TargetTrackingScaling",
        ServiceNamespace=service_namespace,
        ResourceId=resource_id,
        ScalableDimension=scalable_dimension,
        TargetTrackingScalingPolicyConfiguration={
            "PredefinedMetricSpecification": {
                "PredefinedMetricType": "SageMakerInferenceComponentConcurrentRequestsPerCopyHighResolution",
            },
            # Low TPS + load TPS
            "TargetValue": target_tps,  # you need to adjust this value based on your use case
            "ScaleInCooldown": in_cooldown,  # default 300
            "ScaleOutCooldown": out_cooldown,  # default 300
        },
    )
    # Scale out from zero policy (step scaling policy )
    step_scaling_policy_name = f"Step-scaling-policy-{inference_component_name}"
    aas_client.put_scaling_policy(
        PolicyName=step_scaling_policy_name,
        PolicyType="StepScaling",
        ServiceNamespace=service_namespace,
        ResourceId=resource_id,
        ScalableDimension=scalable_dimension,
        StepScalingPolicyConfiguration={
            "AdjustmentType": "ChangeInCapacity",
            "MetricAggregationType": "Maximum",
            "Cooldown": 60,
            "StepAdjustments":
            [
                {
                "MetricIntervalLowerBound": 0,
                "ScalingAdjustment": 1
                }
            ]
        },
    )
    resp = aas_client.describe_scaling_policies(
        PolicyNames=[step_scaling_policy_name],
        ServiceNamespace=service_namespace,
        ResourceId=resource_id,
        ScalableDimension=scalable_dimension,
    )
    step_scaling_policy_arn = resp['ScalingPolicies'][0]['PolicyARN']

    
    # Create the CloudWatch alarm that will trigger our policy
    # The alarm name for the step scaling alarm
    step_scaling_alarm_name = f"step-scaling-alarm-scale-to-zero-aas-{inference_component_name}"

    cloudwatch_client.put_metric_alarm(
        AlarmName=step_scaling_alarm_name,
        AlarmActions=[step_scaling_policy_arn],  # Replace with your actual ARN
        MetricName='NoCapacityInvocationFailures',
        Namespace='AWS/SageMaker',
        Statistic='Maximum',
        Dimensions=[
            {
                'Name': 'InferenceComponentName',
                'Value': inference_component_name  
            }
        ],
        Period=30, # 定义了 CloudWatch 收集和聚合指标数据的时间间隔，CloudWatch 支持的最小 Period 值通常为 10 或 60 秒，取决于指标类型和监控级别
        EvaluationPeriods=1, #定义了在多少个连续的数据点中需要满足条件才会触发警报，=1 表示只需要评估 1 个时间段（即 30 秒，由 Period 定义）
        DatapointsToAlarm=1, #表示在 EvaluationPeriods 中需要满足阈值条件的数据点数量，=1 表示在评估的 1 个时间段内，只要有 1 个数据点满足条件就触发警报
        Threshold=1, #表示当 NoCapacityInvocationFailures 指标值大于或等于 1 时触发警报
        ComparisonOperator='GreaterThanOrEqualToThreshold',
        TreatMissingData='missing' #缺失的数据点不会触发警报状态的任何变化，notBreaching将缺失的数据点视为"良好"或"未违反阈值"，breaching将缺失的数据点视为"违反阈值"，ignore保持当前警报状态不变，直到有新数据点出现
    )
    
    
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
        return False
       
def get_endpoint_instance_count(endpoint_name:str):
    try:
        response = sm_client.describe_endpoint(
            EndpointName=endpoint_name
        )
        current_instance_count = response['ProductionVariants'][0]['CurrentInstanceCount']
        desired_instance_count = response['ProductionVariants'][0]['DesiredInstanceCount']
        return dict(current_instance_count=current_instance_count,desired_instance_count=desired_instance_count)
    except Exception as e:
        # logger.info(f"Error getting endpoint instance: {str(e)}")
        return {}


def get_endpoint_status(endpoint_name:str) ->EndpointStatus:
    client = boto_sess.client('sagemaker')
    try:
        resp = client.describe_endpoint(EndpointName=endpoint_name)
        # logger.info(resp)
        status = resp['EndpointStatus']
        if status == 'InService':
            # logger.info("Deployment completed successfully.")
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
        elif status in ['Updating']:
            database.update_endpoint_status(
                endpoint_name=endpoint_name,
                endpoint_status=EndpointStatus.UPDATING
            )
            return EndpointStatus.UPDATING
        else:
            return EndpointStatus.NOTFOUND
    except Exception as e:
        logger.error(e)
        return EndpointStatus.NOTFOUND
        
def delete_endpoint(endpoint_name:str) ->bool:
    try:
        record = database.get_endpoint(endpoint_name=endpoint_name)
        logger.info(f"record:{record}")
        if record:
            extra_dict = json.loads(record[12])
            inference_component_name = extra_dict.get("inference_component_name")
            endpoint_config_name = extra_dict.get("endpoint_config_name")
            resource_id = extra_dict.get("resource_id")
            sagemaker_model_name = extra_dict.get("sagemaker_model_name")
            step_scaling_policy_name=extra_dict.get("step_scaling_policy_name")
            step_scaling_alarm_name=extra_dict.get("step_scaling_alarm_name")
            
        #to do delete scaling policy,
        #to do delete delete_inference_component
        try:
            # Deregister the scalable target for AAS
            aas_client.deregister_scalable_target(
                ServiceNamespace="sagemaker",
                ResourceId=resource_id,
                ScalableDimension=scalable_dimension,
            )
            logger.info(f"Scalable target for [b]{resource_id}[/b] deregistered.")
        except aas_client.exceptions.ObjectNotFoundException:
            logger.info(f"Scalable target for [b]{resource_id}[/b] not found!.")
        
        # Delete CloudWatch alarms created for Step scaling policy
        try:
            cloudwatch_client.delete_alarms(AlarmNames=[step_scaling_alarm_name])
            logger.info(f"Deleted CloudWatch step scaling scale-out alarm [b]{step_scaling_alarm_name} ")
        except cloudwatch_client.exceptions.ResourceNotFoundException:
            logger.info(f"CloudWatch scale-out alarm [b]{step_scaling_alarm_name}[/b] not found.")
    
        # Delete step scaling policies
        try:
            aas_client.delete_scaling_policy(
                PolicyName=step_scaling_policy_name,
                ServiceNamespace="sagemaker",
                ResourceId=resource_id,
                ScalableDimension="sagemaker:variant:DesiredInstanceCount",
            )
            logger.info(f"Deleted scaling policy [i green]{step_scaling_policy_name} ")
        except aas_client.exceptions.ObjectNotFoundException:
            logger.info(f"Scaling policy [i]{step_scaling_policy_name}[/i] not found.")
            
        try:
            sm_client.delete_inference_component(InferenceComponentName=inference_component_name)
            logger.info(f"Deleted inference component [i green]{inference_component_name} ")
        except Exception as e:
            logger.info(f"Inference component [i]{inference_component_name}[/i] failed. error:{str(e)}")
            
        try:
            sm_client.delete_endpoint(EndpointName=endpoint_name)
            logger.info(f"Deleted endpoint [i green]{endpoint_name} ") 
        except Exception as e:
            logger.info(f"Endpoint [i]{endpoint_name}[/i] failed. error: {str(e)}")
            
        try:
            sm_client.delete_endpoint_config(EndpointConfigName=endpoint_config_name)
            logger.info(f"Deleted endpoint config [i green]{endpoint_config_name} ")
        except Exception as e:
            logger.info(f"Endpoint config [i]{endpoint_config_name}[/i] failed. error: {str(e)}")
            
        try:
            sm_client.delete_model(ModelName=sagemaker_model_name)
            logger.info(f"Deleted model [i green]{endpoint_name} ")
        except Exception as e:
            logger.info(f"Model [i]{endpoint_name}[/i] failed. error:{str(e)}")
        
        database.delete_endpoint(endpoint_name=endpoint_name)
        return True
    except Exception as e:
        # database.delete_endpoint(endpoint_name=endpoint_name)
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


def get_auto_tensor_parallel_size(instance_type:str) -> int:
    return instance_gpus_map.get(instance_type, 1)

def deploy_engine(job_id:str,engine:str,instance_type:str,enable_lora:bool,model_name:str,model_path:str,extra_params:Dict[str,Any]) -> Dict[bool,str]:
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
            "TENSOR_PARALLEL_SIZE": str(extra_params.get('tensor_parallel_size',get_auto_tensor_parallel_size(instance_type))),
            "MAX_NUM_SEQS": extra_params.get('max_num_seqs','256'),
            "ENFORCE_EAGER": "1" if extra_params.get('enforce_eager') else "0",

        }
        if DEFAULT_REGION.startswith('cn'):
            env['VLLM_USE_MODELSCOPE']='1'

    elif engine in ['sglang']:
        lmi_image_uri = SGLANG_IMAGE
        env={
            "HF_MODEL_ID": model_name,
            "S3_MODEL_PATH":model_path,
            "HF_TOKEN":os.environ.get('HUGGING_FACE_HUB_TOKEN'),
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
    
def deploy_endpoint_byoc(job_id:str,engine:str,instance_type:str,quantize:str,enable_lora:bool,model_name:str,cust_repo_type:str,cust_repo_addr:str,extra_params:Dict[str,Any]) -> Dict[bool,str]:
    repo_type = DownloadSource.MODELSCOPE  if DEFAULT_REGION.startswith('cn') else DownloadSource.DEFAULT
    #统一处理成repo/modelname格式
    model_name=get_model_path_by_name(model_name,repo_type) if model_name and len(model_name.split('/')) < 2 else model_name
    model_path = ''
    need_download = False
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
    #如果是使用自定义模型
    elif not cust_repo_addr == '' and model_name == '' :
        model_name = cust_repo_addr
        #注册到supported_model中
        register_cust_model(cust_repo_type=repo_type,cust_repo_addr=cust_repo_addr)
        # 仅仅针对中国区需要从模型中心下载上传到s3
        if repo_type == DownloadSource.MODELSCOPE:
            need_download = True
    #如果是使用原始模型
    elif model_name and job_id == 'N/A(Not finetuned)':
        # 仅仅针对中国区需要从模型中心下载上传到s3，在deploy endpint，所以改成后台执行。
        if repo_type == DownloadSource.MODELSCOPE:
            need_download = True
    #如果是直接从s3 path加载模型
    elif extra_params.get("s3_model_path"):
        model_path = extra_params.get("s3_model_path")
        model_name = 'custom/custom_model_in_s3' if not model_name else model_name

    logger.info(f"deploy endpoint with engine:{engine},model_name:{model_name},model_path:{model_path}")
    

    deploy_inference_component_endpoint_background(job_id=job_id,engine=engine,instance_type=instance_type,
                                                   enable_lora=enable_lora,need_download=need_download,
                                        model_name=model_name,model_path=model_path,extra_params=extra_params)
    return True,"Creating endpoint in background"

def deploy_inference_component_endpoint_background(job_id:str,engine:str,instance_type:str,enable_lora:bool,need_download:bool,model_name:str,model_path:str,extra_params:Dict[str,Any]):
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(deploy_inference_component_endpoint,
                                 job_id=job_id,
                                 engine=engine,
                                 instance_type=instance_type,
                                 enable_lora=enable_lora,
                                 need_download =need_download,
                                 model_name=model_name,
                                 model_path= model_path,
                                 extra_params=extra_params
                                )

def deploy_inference_component_endpoint(job_id:str,engine:str,instance_type:str,enable_lora:bool,need_download:bool,model_name:str,model_path:str,extra_params:Dict[str,Any]) -> Dict[bool,str]:
    
    instance_count = int(extra_params.get("instance_count",1))
    max_instance_count = int(extra_params.get("max_instance_count",1))
    min_instance_count = int(extra_params.get("min_instance_count",0))
    
    if need_download:
        model_path = f"s3://{default_bucket}/original_model_file/{model_name}"
    
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
            "TENSOR_PARALLEL_SIZE": str(extra_params.get('tensor_parallel_size',get_auto_tensor_parallel_size(instance_type))),
            "MAX_NUM_SEQS": extra_params.get('max_num_seqs','256'),
            "ENFORCE_EAGER": "1" if extra_params.get('enforce_eager') else "0",

        }
        if DEFAULT_REGION.startswith('cn'):
            env['VLLM_USE_MODELSCOPE']='1'

    elif engine in ['sglang']:
        lmi_image_uri = SGLANG_IMAGE
        env={
            "HF_MODEL_ID": model_name,
            "S3_MODEL_PATH":model_path,
            "HF_TOKEN":os.environ.get('HUGGING_FACE_HUB_TOKEN'),
        }
    
    else:
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
                    endpoint_status = EndpointStatus.FAILED
                    )
        return False,f"Not supported: {engine}"

    container_config = {
        'Image': lmi_image_uri,
        'ModelDataUrl': MODEL_ARTIFACT,
        'Environment': env
    }
    logger.info(f"env:{env}")
    logger.info(f"extra_params:{extra_params}")
    pure_model_name = model_name.split('/')[1]

    create_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    if not extra_params.get("endpoint_name"):
        base_name = f"{pure_model_name}-{create_time}".replace('.','-').replace(':','-').replace(' ','-').replace('_','-')+f"-{engine}"
        endpoint_name = base_name+"-endpoint"
        endpoint_name = endpoint_name[:63] #must have length less than or equal to 63
        endpoint_config_name = str(base_name+"-config")[:63]
        inference_component_name = str(base_name+"-component")[:63]
        sagemaker_model_name = str(base_name+"-model")[:63]
    else:
        endpoint_name = extra_params.get("endpoint_name")[:63]
        endpoint_config_name = str(endpoint_name+"-config")[:63]
        inference_component_name = str(endpoint_name+"-component")[:63]
        sagemaker_model_name = str(endpoint_name+"-model")[:63]

    resource_id = f"inference-component/{inference_component_name}"
    target_tracking_policy_name = f"Target-tracking-policy-{inference_component_name}"
    step_scaling_policy_name = f"Step-scaling-policy-{inference_component_name}"
    step_scaling_alarm_name = f"step-scaling-alarm-scale-to-zero-aas-{inference_component_name}"

    max_copy_count = int(extra_params.get('max_copy_count', max_instance_count))
    min_copy_count = int(extra_params.get('min_copy_count', min_instance_count))
    target_tps = int(extra_params.get('target_tps', 5))
    in_cooldown = int(extra_params.get('in_cooldown', 300))
    out_cooldown = int(extra_params.get('out_cooldown', 300))
    extra_config= dict(inference_component_name=inference_component_name,
                                endpoint_config_name=endpoint_config_name,
                                resource_id=resource_id,
                                sagemaker_model_name=sagemaker_model_name,
                                target_tracking_policy_name=target_tracking_policy_name,
                                step_scaling_policy_name=step_scaling_policy_name,
                                target_tps=target_tps,
                                in_cooldown=in_cooldown,
                                out_cooldown=out_cooldown,
                                step_scaling_alarm_name=step_scaling_alarm_name,
                                instance_count=instance_count,
                                max_copy_count=max_copy_count,
                                min_copy_count=min_copy_count,
                                min_instance_count=min_instance_count,
                                max_instance_count=max_instance_count)

    # 创建endpoint_config
    try:
        sm_client.create_endpoint_config(
            EndpointConfigName=endpoint_config_name,
            ExecutionRoleArn=role,
            ProductionVariants=[
                {
                    "VariantName": "AllTraffic",
                    "InstanceType": instance_type,
                    "InitialInstanceCount": instance_count,
                    "ModelDataDownloadTimeoutInSeconds": 3600,
                    "ContainerStartupHealthCheckTimeoutInSeconds": 1800,
                    "ManagedInstanceScaling": {
                        "Status": "ENABLED",
                        "MinInstanceCount": min_instance_count,
                        "MaxInstanceCount": max_instance_count,
                    },
                    "RoutingConfig": {"RoutingStrategy": "LEAST_OUTSTANDING_REQUESTS"},
                }
            ],
        )
    except Exception as e:
        logger.error(f"failed to create_endpoint_config:{e}")
        database.create_endpoint(job_id= job_id,
                            model_name= model_name,
                            model_s3_path= model_path,
                            instance_type= instance_type,
                            instance_count = instance_count,
                            endpoint_name= endpoint_name,
                            endpoint_create_time= create_time,
                            endpoint_delete_time= None,
                            extra_config= extra_config,
                            engine=engine,
                            enable_lora=enable_lora,
                            endpoint_status = EndpointStatus.FAILED
                            )
        return False,str(e)
    
    # 创建endpoint
    start_time = time.time()
    try:
        sm_client.create_endpoint(
            EndpointName=endpoint_name,
            EndpointConfigName=endpoint_config_name,
        )
    except Exception as e:
        logger.error(f"failed to create_endpoint:{e}")
        database.create_endpoint(job_id= job_id,
                    model_name= model_name,
                    model_s3_path= model_path,
                    instance_type= instance_type,
                    instance_count = instance_count,
                    endpoint_name= endpoint_name,
                    endpoint_create_time= create_time,
                    endpoint_delete_time= None,
                    extra_config= extra_config,
                    engine=engine,
                    enable_lora=enable_lora,
                    endpoint_status = EndpointStatus.FAILED
                    )
        return False,f"failed to create_endpoint:{e}"
    
    # 数据库中添加CREATING记录
    database.create_endpoint(job_id= job_id,
                            model_name= model_name,
                            model_s3_path= model_path,
                            instance_type= instance_type,
                            instance_count = instance_count,
                            endpoint_name= endpoint_name,
                            endpoint_create_time= create_time,
                            endpoint_delete_time= None,
                            extra_config= extra_config,
                            engine=engine,
                            enable_lora=enable_lora,
                            endpoint_status = EndpointStatus.CREATING
                            )
    #如果是modelscope，则需要下载到本地再上传到S3
    if need_download:
        executor = concurrent.futures.ThreadPoolExecutor()
        future = executor.submit(ms_download_and_upload_model,model_repo=model_name,s3_bucket=default_bucket,s3_prefix=f"original_model_file/{model_name}")
    # wait for endpoint go InService
    while True:
        desc = sm_client.describe_endpoint(EndpointName=endpoint_name)
        status = desc["EndpointStatus"]
        if status in ["InService", "Failed"]:
            break
        time.sleep(10)
        
    if status == "InService":
        total_time = time.time() - start_time
        logger.info(f"\ncreate endpoint time taken: {total_time:.2f} seconds ({total_time/60:.2f} minutes)")
    else:
        logger.error(f"failed to create_endpoint:{endpoint_name}")
        database.update_endpoint_status(
                endpoint_name=endpoint_name,
                endpoint_status=EndpointStatus.FAILED
            )
        if need_download:
            executor.shutdown()
        return False,f"failed to create_endpoint:{endpoint_name}"
    
    # 阻塞直到下载完成
    if need_download:
        download_result = future.result()
        executor.shutdown()
        if not download_result:
            database.update_endpoint_status(
                endpoint_name=endpoint_name,
                endpoint_status=EndpointStatus.FAILED
            )
            return False,f"failed to create_endpoint:{endpoint_name}"
        
    #更新端点状态为Deloying
    database.update_endpoint_status(
            endpoint_name=endpoint_name,
            endpoint_status=EndpointStatus.DEPLOYING
        )
    # create model
    try:
        response = sm_client.create_model(
            ModelName=sagemaker_model_name,
            ExecutionRoleArn=role,
            PrimaryContainer=container_config
        )
        logger.info(f"Model created: {response['ModelArn']}")
    except Exception as e:
        database.update_endpoint_status(
                endpoint_name=endpoint_name,
                endpoint_status=EndpointStatus.FAILED
            )
        logger.error(f"failed to create_model:{e}")
        return False,f"failed to create_model:{e}"
    
    
    # create inference component
    try:
        t1 = time.time()
        sm_client.create_inference_component(
            InferenceComponentName=inference_component_name,
            EndpointName=endpoint_name,
            VariantName="AllTraffic",
            Specification={
                "ModelName": sagemaker_model_name,
                "ComputeResourceRequirements": {
                    "NumberOfAcceleratorDevicesRequired": extra_params.get('tensor_parallel_size',get_auto_tensor_parallel_size(instance_type)), # 默认使用tp size
                    "MinMemoryRequiredInMb": 1024*8
                }
            },
            RuntimeConfig={"CopyCount": 1},
        )
    except Exception as e:
        database.update_endpoint_status(
                endpoint_name=endpoint_name,
                endpoint_status=EndpointStatus.FAILED
            )
        logger.error(f"failed to create inference component:{e}")
        return False,f"failed to create inference component:{e}"
    
    # wait for inference componet 
    while True:
        status = check_inference_component_status(inference_component_name)
        if status in [ICStatus.FAILED,ICStatus.INSERVICE]:
            if status == ICStatus.FAILED:
                logger.error(f"failed to create inference component:{inference_component_name}")
                database.update_endpoint_status(
                        endpoint_name=endpoint_name,
                        endpoint_status=EndpointStatus.FAILED
                    )
                return False,f"failed to create inference component:{inference_component_name}"
            else:
                total_time = time.time() - start_time
                logger.info(f"success to create inference component time taken: {total_time:.2f} seconds ({total_time/60:.2f} minutes)")
                break
        time.sleep(10)
    
    try:
        register_as_policy(inference_component_name,min_copy_count,max_copy_count,target_tps,in_cooldown=in_cooldown,out_cooldown=out_cooldown)
    except Exception as e:
        logger.error(f"failed to register_as_policy:{e}")
        database.update_endpoint_status(
                endpoint_name=endpoint_name,
                endpoint_status=EndpointStatus.FAILED
            )
        return False,f"failed to register_as_policy:{e}"
    #更新端点状态为inservice
    database.update_endpoint_status(
            endpoint_name=endpoint_name,
            endpoint_status=EndpointStatus.INSERVICE
        )
    return True,f"success to create inference component:{inference_component_name}"


def get_endpoint_engine(endpoint_name:str) -> str:
    ret =  database.get_endpoint_engine(endpoint_name)
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
    
    for endpoint in info:
        extra_config = json.loads(endpoint.extra_config) if endpoint.extra_config else {}
        endpoint.endpoint_status = get_endpoint_status(endpoint.endpoint_name)

        inference_component_name = extra_config.get("inference_component_name")
        if inference_component_name:
            extra_config["inference_component_copies"] = get_inference_component_copies(inference_component_name)
            extra_config["inference_component_status"] = check_inference_component_status(inference_component_name).value
            extra_config["endpoint_instance_count"] = get_endpoint_instance_count(endpoint.endpoint_name)
        # logger.info(f"extra_config:{extra_config}")
        endpoint.extra_config = json.dumps(extra_config)

    return info,count