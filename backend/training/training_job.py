from sagemaker.estimator import Estimator
from sagemaker.pytorch import PyTorch
from datetime import datetime
import yaml,json
import shortuuid
import logging
from typing import Dict,List, Any
from pydantic import BaseModel
import sys
sys.path.append('./')
from logger_config import setup_logger
from training.helper import prepare_dataset_info,to_datetime_string,list_s3_objects,is_valid_s3_uri
from model.data_model import JobInfo
from utils.get_factory_config import get_model_path_by_name
from utils.llamafactory.extras.constants import DEFAULT_TEMPLATE,DownloadSource
import time
import dotenv
import os
from utils.config import boto_sess,role,default_bucket,sagemaker_session, is_efa, \
LORA_BASE_CONFIG,DEEPSPEED_BASE_CONFIG_MAP,FULL_BASE_CONFIG,DEFAULT_REGION,WANDB_API_KEY, WANDB_BASE_URL, SWANLAB_API_KEY

dotenv.load_dotenv()

logger = setup_logger('training_job.py', log_file='processing_engine.log', level=logging.INFO)


def save_json_to_s3(s3_path,data):
    s3_resource = boto_sess.resource('s3')
    bucket_name,key = s3_path.replace('s3://','').split('/',1)
    s3_resource.Object(bucket_name,key).put(Body=json.dumps(data))
    return s3_path
def get_all_log_streams(logs_client,log_group_name):
    """
    获取指定日志组中的所有日志流
    
    :param log_group_name: 日志组名称
    :return: 日志流列表
    """
    log_streams = []
    next_token = None

    try:
        while True:
            if next_token:
                response = logs_client.describe_log_streams(
                    logGroupName=log_group_name,
                    nextToken=next_token
                )
            else:
                response = logs_client.describe_log_streams(
                    logGroupName=log_group_name
                )
            
            log_streams.extend(response['logStreams'])
            
            if 'nextToken' in response:
                next_token = response['nextToken']
            else:
                break
        
        return log_streams
    
    except Exception as e:
        print(f"An error occurred: {e}")
        return []


def fetch_log(log_group_name:str='/aws/sagemaker/TrainingJobs',log_stream_name:str=None,next_token:str=None):
    # 获取日志组中的所有日志流
    logs_client = boto_sess.client('logs')
    
    log_streams = get_all_log_streams(logs_client,log_group_name)

    results = []
    next_forward_token,next_backward_token = None,None
    # 遍历每个日志流并检索其日志事件
    for log_stream in log_streams:
        stream_name = log_stream['logStreamName']
        if stream_name and stream_name.startswith(log_stream_name):
            print(stream_name)
            if next_token:
                response = logs_client.get_log_events(
                    logGroupName=log_group_name,
                    nextToken=next_token,
                    startFromHead=True,
                    # limit=1000,
                    logStreamName=stream_name
                )
                # print(response)

            else:
                response = logs_client.get_log_events(
                    logGroupName=log_group_name,
                    logStreamName=stream_name,
                    startFromHead=True,
                )
            events = response['events']
            next_forward_token = response['nextForwardToken']
            next_backward_token = response['nextBackwardToken']

            for event in events:
                timestamp = to_datetime_string(event['timestamp']/1000)
                message = event['message']
                results.append(f'{timestamp}: {message}')
                # print(f'{timestamp}: {message}')
    return results,next_forward_token,next_backward_token

                
class TrainingJobExcutor(BaseModel):
    estimator:Any = None
    job_run_name:str = None #SageMaker Training job name
    job_id:str = None
    output_s3_path:str = None
    def __init__(self,*args, **kwargs):
        super().__init__(*args, **kwargs)

        
    def create_training_args(self,
                             stage:str,
                             job_payload:Dict[str,Any],
                             data_keys:List[str],
                             model_id:str,
                             base_config:str):
        
        with open(base_config) as f:
            doc = yaml.safe_load(f)
        doc['output_dir'] ='/tmp/finetuned_model'
        doc['per_device_train_batch_size'] =int(job_payload['per_device_train_batch_size'])
        doc['gradient_accumulation_steps'] =int(job_payload['gradient_accumulation_steps'])
        doc['template'] =  DEFAULT_TEMPLATE[job_payload['prompt_template']]

        #如果使用lora微调
        if job_payload['finetuning_method'] == 'lora':
            doc['finetuning_type'] = 'lora'
            doc['lora_target'] = job_payload.get('lora_target_modules','all')
            doc['lora_rank'] = int(job_payload['lora_rank'])
            doc['lora_alpha'] = int(job_payload['lora_alpha'])
            
            ## temp test `ddp_find_unused_parameters` needs to be set as False for LoRA in DDP training.
            doc['ddp_find_unused_parameters'] = False
        else:
            doc['finetuning_type'] = 'full'
        
        #如果是dpo或者kto, 暂时固定值
        if stage == 'dpo':
            doc['pref_beta'] = float(job_payload.get("pref_beta",0.1))
            doc['pref_loss'] = job_payload.get("pref_loss",'sigmoid')
            doc['pref_ftx'] = float(job_payload.get("pref_ftx",0))
            doc['stage'] = 'dpo'
        elif stage == 'kto':
            doc['pref_beta'] = float(job_payload.get("pref_beta",0.1))
            doc['pref_loss'] = float(job_payload.get("pref_loss",'sigmoid'))
            doc['pref_ftx'] = float(job_payload.get("pref_ftx",0))
            doc['stage'] = 'kto'
        elif stage == 'pt':
            doc['stage'] = 'pt'
            doc['template'] = 'default'

        doc['model_name_or_path'] = model_id    
        doc['learning_rate']=  float(job_payload['learning_rate'])
        doc['cutoff_len'] = int(job_payload['cutoff_len'])
        doc['num_train_epochs'] = float(job_payload['num_train_epochs'])
        doc['warmup_steps'] = int(job_payload['warmup_steps'])
        doc['logging_steps'] = int(job_payload['logging_steps'])
        doc['save_steps'] = int(job_payload['save_steps'])
        
        if val_size:=float(job_payload['val_size']):
            doc['val_size'] = val_size
                    
        if job_payload['booster_option'] == 'fa2':
            doc['flash_attn'] = 'fa2'
        elif job_payload['booster_option']  == 'use_unsloth':
            doc['flash_attn'] = 'auto'
            doc['use_unsloth'] = True
        else:
            doc['flash_attn'] = 'auto'
            
        #WANDB
        if WANDB_API_KEY:
            doc['report_to'] = "wandb"
            timestp = to_datetime_string(time.time()).replace(' ', '_')
            doc['run_name'] = f"modelhub_run_{timestp}"

        if SWANLAB_API_KEY:
            doc['use_swanlab'] = True
            timestp = to_datetime_string(time.time()).replace(' ', '_')
            doc['swanlab_run_name'] = f"sagemaker_modelhub_run_{timestp}"
            doc['swanlab_project'] = f"sagemaker_modelhub"
            doc['swanlab_api_key'] = SWANLAB_API_KEY
            
        #训练精度
        if job_payload['training_precision'] == 'bf16':
            doc.pop('fp16', None)
            doc.pop('pure_bf16', None)
            doc['bf16'] = True
        elif job_payload['training_precision'] == 'fp16':
            doc.pop('bf16', None)
            doc.pop('pure_bf16', None)
            doc['fp16'] = True
        elif job_payload['training_precision'] == 'pure_bf16':
            doc.pop('bf16', None)
            doc.pop('bf16', None)
            doc['pure_bf16'] = True
        elif job_payload['training_precision'] == 'fp32':
            doc.pop('bf16', None)
            doc.pop('bf16', None)
            doc.pop('pure_bf16', None)
            
        doc['optim'] = job_payload['optimizer']
        
        deepspeed_config = DEEPSPEED_BASE_CONFIG_MAP.get(job_payload["deepspeed"])
        if deepspeed_config:
            doc['deepspeed'] = deepspeed_config

        #using bitandbytes to quantize 
        if job_payload['quantization_bit'] in ['4','8']:
            doc['quantization_bit'] = int(job_payload['quantization_bit'])

        #实验时间，只选取前max_samples条数据做训练
        doc['max_samples'] = int(job_payload['max_samples'])
        #数据集
        doc['dataset'] = ','.join(data_keys)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        uuid = shortuuid.uuid()
        train_args_path = f's3://{default_bucket}/llm_modelhub/args/train_args_{timestamp}_{uuid}.json'
        save_json_to_s3(train_args_path, doc)
        logger.info(f'training args:\n{doc}')
        logger.info(f'save training args:\n{train_args_path}')

        doc_merge = {}
        doc_merge['model_name_or_path'] = model_id
        doc_merge['adapter_name_or_path'] ='/tmp/finetuned_model'
        doc_merge['export_dir'] ='/tmp/finetuned_model_merged'
        doc_merge['template'] =  DEFAULT_TEMPLATE[job_payload['prompt_template']]
        doc_merge['export_size'] = 5
        doc_merge['export_device'] = 'auto'
        doc_merge['export_legacy_format'] = False

        
        merge_args_path = f's3://{default_bucket}/llm_modelhub/args/merge_args_{timestamp}_{uuid}.json'
        save_json_to_s3(merge_args_path, doc_merge)
        logger.info(f'merge args:\n{doc}')
        logger.info(f'save merge args:\n{merge_args_path}')

        return train_args_path,merge_args_path



        
    def create_training(self,
                        model_id:str,
                        dataset_info_path:str,
                        sg_config:str,
                        use_spot:bool,
                        max_spot_wait:int,
                        max_job_run_hour:int,
                        sg_lora_merge_config:str,
                        instance_type:str ,
                        instance_num:int,
                        s3_checkpoint:str,
                        s3_model_path:str,
                        merge_lora:str = '1',
                        training_input_path:str=None):

        base_model_name = model_id.split('/')[-1]
        base_job_name = base_model_name.replace('.','-')
        
        output_s3_path = f's3://{default_bucket}/{base_job_name}/{self.job_id}/'
        environment = {
            'NODE_NUMBER':str(instance_num),
            "s3_data_paths":f"{training_input_path}",
            "dataset_info_path":dataset_info_path,
            "s3_checkpoint":s3_checkpoint,
            "s3_model_path":s3_model_path,
            "USE_EFA": "1" if is_efa(instance_type) else "0",
            "HUGGING_FACE_HUB_TOKEN":os.environ.get('HUGGING_FACE_HUB_TOKEN'),
            "merge_lora":merge_lora,
            "merge_args_path":sg_lora_merge_config,
            "train_args_path":sg_config,
            'OUTPUT_MODEL_S3_PATH': output_s3_path, # destination 
            "REGION": DEFAULT_REGION,
            # "PIP_INDEX":'https://mirrors.aliyun.com/pypi/simple' if DEFAULT_REGION.startswith('cn') else '',
            "USE_MODELSCOPE_HUB": "1" if DEFAULT_REGION.startswith('cn') else '0'
            
        }
        if WANDB_BASE_URL:
            environment["WANDB_BASE_URL"] = WANDB_BASE_URL
        if WANDB_API_KEY:
            environment["WANDB_API_KEY"] = WANDB_API_KEY
        else:
            environment["WANDB_DISABLED"] = "true"
        # entry_point = 'entry_single_lora.py' if instance_num == 1 else 'entry-multi-nodes.py'
        self.output_s3_path = output_s3_path
        # self.estimator = PyTorch(entry_point=entry_point,
        #                             source_dir='./LLaMA-Factory/',
        #                             role=role,
        #                             use_spot_instances=use_spot,
        #                             sagemaker_session=sagemaker_session,
        #                             base_job_name=base_job_name,
        #                             environment=environment,
        #                             framework_version='2.3.0',
        #                             py_version='py311',
        #                             script_mode=True,
        #                             instance_count=instance_num,
        #                             instance_type=instance_type,
        #                             max_wait= 3600*max_spot_wait if use_spot else None,
        #                             enable_remote_debug=True,
        #                             # keep_alive_period_in_seconds=600,
        #                             max_run=3600*max_job_run_hour)
        self.estimator = Estimator(image_uri=os.environ['training_image'],
                            role=role,
                            use_spot_instances=use_spot,
                            sagemaker_session=sagemaker_session,
                            base_job_name=base_job_name,
                            environment=environment,
                            instance_count=instance_num,
                            instance_type=instance_type,
                            max_wait= 3600*max_spot_wait if use_spot else None,
                            max_run=3600*max_job_run_hour,
                            enable_remote_debug=True
                            )
        
        
    def create(self):
        from training.jobs import sync_get_job_by_id
        jobinfo=sync_get_job_by_id(self.job_id)
        logger.info(f"jobinfo of {self.job_id}:{jobinfo}")
        job_payload = jobinfo.job_payload
        
        
        logger.info(f"job_payload:{job_payload}")
        
        s3_data_path=job_payload.get('s3_data_path','')

        dataset_info = {}
        s3_datakeys=[]
        # 如果指定了s3路径
        if s3_data_path:
            dataset_info_str = job_payload.get('dataset_info')
            dataset_info = json.loads(dataset_info_str)
            s3_datakeys = list(dataset_info.keys()) if dataset_info else []
            
            # 去掉末尾的反斜杠，因为training script 里会添加
            s3_data_path = s3_data_path[:-1] if s3_data_path[-1] == '/' else s3_data_path
        
        data_keys = job_payload.get('dataset',[])+s3_datakeys

        # add to dataset_info
        dataset_info = prepare_dataset_info(dataset_info)
        # upload to s3
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        uuid = shortuuid.uuid()
        dataset_info_path = f's3://{default_bucket}/llm_modelhub/dataset_info/dataset_info_{timestamp}_{uuid}.json'
        save_json_to_s3(dataset_info_path, dataset_info)

        
        #model_id参数
        repo = DownloadSource.MODELSCOPE if DEFAULT_REGION.startswith('cn') else DownloadSource.DEFAULT

        # 判断是否使用repo/model格式
        model_id=get_model_path_by_name(job_payload['model_name'],repo) if len(job_payload['model_name'].split('/')) < 2 else job_payload['model_name']
        logger.info(f"model_id:{model_id},repo type:{repo}")
        
        if job_payload['stage'] in ['sft','dpo','kto','pt']:
            sg_config,sg_lora_merge_config= self.create_training_args(
                    stage=job_payload['stage'],
                    data_keys=data_keys,
                    job_payload=job_payload,
                    model_id = model_id,
                    base_config =LORA_BASE_CONFIG if job_payload['finetuning_method'] == 'lora' else FULL_BASE_CONFIG)
            
            # Lora和没有设置量化时，merge lora
            merge_lora = '1' if job_payload['finetuning_method'] == 'lora' and job_payload['quantization_bit'] == 'none' else '0'
            
            #validate checkpoint地址
            s3_checkpoint = job_payload['s3_checkpoint']
            if s3_checkpoint:
                if not is_valid_s3_uri(s3_checkpoint):
                    logger.error(f"s3_checkpoint path is invalid:{s3_checkpoint}")
                    s3_checkpoint = ''
            #validate s3_model_path
            s3_model_path = job_payload['s3_model_path']
            if s3_model_path:
                if not is_valid_s3_uri(s3_model_path):
                    logger.error(f"s3_model_path is invalid:{s3_model_path}")
                    s3_model_path = ''
                    
            print('use_spot:',job_payload.get("use_spot",False))
            self.create_training(sg_config=sg_config,
                                    dataset_info_path=dataset_info_path,
                                    use_spot = job_payload.get("use_spot",False),
                                    max_spot_wait = int(job_payload.get("max_spot_wait",72)),
                                    max_job_run_hour = int(job_payload.get("max_job_run_hour",48)),
                                    instance_num = int(job_payload['instance_num']),
                                    model_id=model_id,
                                    sg_lora_merge_config=sg_lora_merge_config,
                                    training_input_path= s3_data_path,
                                    merge_lora=merge_lora,
                                    s3_checkpoint=s3_checkpoint,
                                    s3_model_path=s3_model_path,
                                    instance_type=job_payload['instance_type'])

            return True,'create job success'
        else:
            logger.info('not supported yet')
            return False, 'type of job not supported yet'
        
    def run(self) -> bool:
        from training.jobs import update_job_run_name_by_id

        if not self.estimator:
            logger.error('estimator is None')
            return False
        self.estimator.fit(wait=False)
        logger.info('---fit----')
        self.job_run_name = self.estimator.latest_training_job.job_name
        
        # save the training job name to db
        update_job_run_name_by_id(self.job_id,self.job_run_name,self.output_s3_path)
        print(f"Training job name: {self.job_run_name},output_s3_path:{self.output_s3_path}")
        self.estimator.logs()
    
    def stop(self) -> bool:
        if not self.estimator:
            logger.error('estimator is None')
            return False
        self.estimator.stop()
        return True
            
    
    

