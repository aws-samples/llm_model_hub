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
import ast
from utils.config import boto_sess,role,default_bucket,sagemaker_session, is_efa,get_auto_tensor_parallel_size, \
LORA_BASE_CONFIG,DEEPSPEED_BASE_CONFIG_MAP,FULL_BASE_CONFIG,DEFAULT_REGION,WANDB_API_KEY, WANDB_BASE_URL, SWANLAB_API_KEY

dotenv.load_dotenv()

logger = setup_logger('training_job.py', log_file='processing_engine.log', level=logging.INFO)


def check_syntax_with_ast(code_str):
    try:
        ast.parse(code_str)
        return True, "语法正确"
    except SyntaxError as e:
        return False, f"语法错误: 第 {e.lineno} 行, 列 {e.offset}: {e.text}\n{e.msg}"
    
def save_json_to_s3(s3_path,data):
    s3_resource = boto_sess.resource('s3')
    bucket_name,key = s3_path.replace('s3://','').split('/',1)
    s3_resource.Object(bucket_name,key).put(Body=json.dumps(data))
    return s3_path

def save_text_to_s3(s3_path,data):
    s3_resource = boto_sess.resource('s3')
    bucket_name,key = s3_path.replace('s3://','').split('/',1)
    s3_resource.Object(bucket_name,key).put(Body=data)
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
        
        doc.pop('resume_from_checkpoint',None)
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
            doc['eval_steps'] = int(job_payload['logging_steps'])
            doc['eval_strategy'] = 'steps'
            doc['per_device_eval_batch_size'] = 2
        else:
            if 'val_size' in doc:
                doc.pop('val_size', None)
                doc.pop('eval_strategy', None)
                doc.pop('per_device_eval_batch_size', None)
                doc.pop('eval_steps', None)
                    
        if job_payload['booster_option'] == 'fa2':
            doc['flash_attn'] = 'fa2'
        elif job_payload['booster_option']  == 'use_unsloth':
            doc['flash_attn'] = 'auto'
            doc['use_unsloth'] = True
        elif job_payload['booster_option']  == 'liger_kernel':
            doc['flash_attn'] = 'auto'
            doc['enable_liger_kernel'] = True
        else:
            doc['flash_attn'] = 'auto'
            
        #WANDB
        if WANDB_API_KEY:
            doc['report_to'] = "wandb"
            timestp = to_datetime_string(time.time()).replace(' ', '_')
            doc['run_name'] = f"modelhub_run_{timestp}"
        else:
            doc['report_to'] = "none"

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


    def create_grpo_training(self,
                            job_payload:Dict[str,Any],
                            dataset_info_path:str,
                            data_keys:List[str],
                            model_id:str,
                            use_spot:bool,
                            max_spot_wait:int,
                            max_job_run_hour:int,
                            s3_model_path:str,
                            instance_type:str,
                            s3_checkpoint:str = '',
                            training_input_path:str=None
                            ):
        base_model_name = model_id.split('/')[-1]
        base_job_name = base_model_name.replace('.','-')
        instance_type = job_payload['instance_type']
        n_gpus_per_node = get_auto_tensor_parallel_size(instance_type)
        max_steps = int(job_payload.get('max_steps',0))
        instance_num = int(job_payload['instance_num'])
        save_freq = int(job_payload.get('save_freq',50))  
        val_freq = int(job_payload.get('val_freq',save_freq))
        project_name = job_payload.get('project_name',"easyr1_grpo")
        train_files = job_payload.get('train_files',None)
        val_files = job_payload.get('val_files',None)
        max_prompt_length = int(job_payload.get('max_prompt_length',2048))  
        max_response_length = int(job_payload.get('max_response_length',2048))  
        rollout_tensor_parallel_size = int(job_payload.get('rollout_tensor_parallel_size',1))  
        format_prompt = job_payload.get('format_prompt')
        total_epochs = int(job_payload.get('total_epochs',1))  
        offload_params ='true' if job_payload.get('offload_params') else 'false'
        offload_optimizer = 'true' if job_payload.get('offload_optimizer') else 'false'
        rollout_batch_size = int(job_payload.get('rollout_batch_size',512))
        global_batch_size = int(job_payload.get('global_batch_size',128))
        if WANDB_API_KEY:
            train_logger = "['console','wandb']"
        elif SWANLAB_API_KEY:
            train_logger = "['console','swanlab']"
        else:
            train_logger = "['console']"
        
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

        suffix = ''
        if s3_checkpoint:
            suffix = s3_checkpoint.split('/')[-1]
            if not suffix.startswith('global_step'):
                return False, 's3_checkpoint f{s3_checkpoint} must ends with global_step_'
            
        configs = {
            "config":"examples/config.yaml",
            "data.max_prompt_length":max_prompt_length,
            "data.max_response_length":max_response_length,
            "data.rollout_batch_size":rollout_batch_size,
            "worker.actor.model.model_path":model_id,
            "worker.actor.global_batch_size":global_batch_size,
            "worker.actor.model.trust_remote_code":"true",
            "worker.actor.offload.offload_params":offload_params,
            "worker.actor.offload.offload_optimizer":offload_optimizer,
            "worker.rollout.tensor_parallel_size":rollout_tensor_parallel_size,
            "trainer.experiment_name":f'{base_job_name}_{timestamp}', 
            "trainer.project_name":project_name,
            "trainer.logger":train_logger,
            "trainer.n_gpus_per_node":n_gpus_per_node,
            "trainer.nnodes":instance_num,
            "trainer.save_checkpoint_path":"/tmp/checkpoints",
            "trainer.save_freq":save_freq,
            "trainer.val_freq":val_freq,
            "trainer.total_epochs":total_epochs
        }
        logger.info(configs)
        
        # 注意：需要跟https://github.com/hiyouga/EasyR1/tree/main/examples/reward_function里的对应
        reward_function_path = ''
        if job_payload.get('reward_function') == 'math:compute_score':
            configs['worker.reward.reward_function'] = './examples/reward_function/math.py:compute_score'
        elif job_payload.get('reward_function') == 'r1v:computer_score':
            configs['worker.reward.reward_function'] = './examples/reward_function/r1v.py:compute_score'
        elif job_payload.get('reward_function') == 'customize':
            customize_reward_function  = job_payload.get('customize_reward_function')
            configs['worker.reward.reward_function'] = 'placeholder'
            if not customize_reward_function:
                logger.error('Reward function code cannot be empty')
                return False, 'Reward function code cannot be empty'
            
            # Check code syntax
            syntax_check,msg = check_syntax_with_ast(customize_reward_function)
            if not syntax_check:
                logger.error( f'Reward function code syntax error,{msg}')
                return False, f'Reward function code syntax error,{msg}'
                
            # upload code to s3
            uuid = shortuuid.uuid()
            reward_function_path = f's3://{default_bucket}/llm_modelhub/reward_function/reward_function_{timestamp}_{uuid}.py'
            save_text_to_s3(reward_function_path,customize_reward_function)
        
        format_prompt_path = ''
        if format_prompt:
            # upload code to s3
            uuid = shortuuid.uuid()
            format_prompt_path = f's3://{default_bucket}/llm_modelhub/format_prompt/format_prompt_{timestamp}_{uuid}.jinja'
            save_text_to_s3(format_prompt_path,format_prompt)
        
        logger.info(f"data_keys:{data_keys}")
       
        if data_keys:
            public_data = data_keys[0]
            data_splits = public_data.split(',')
            train_files = data_splits[0]
            val_files = data_splits[1]
        if max_steps >0 :
            configs['trainer.max_steps'] = max_steps
        if train_files:
            configs['data.train_files'] = train_files
        if val_files:
            configs['data.val_files'] = val_files
            
        logger.info(f"{configs}")
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        uuid = shortuuid.uuid()
        train_args_path = f's3://{default_bucket}/llm_modelhub/args/train_args_{timestamp}_{uuid}.json'
        save_json_to_s3(train_args_path, configs)
        
        output_s3_path = f's3://{default_bucket}/{base_job_name}/{self.job_id}/'
        environment = {
            "s3_data_paths":f"{training_input_path}",
            "s3_checkpoint":s3_checkpoint,
            "s3_model_path":s3_model_path,
            "reward_function_path":reward_function_path,
            "format_prompt_path":format_prompt_path,
            # "USE_EFA": "1" if is_efa(instance_type) else "0", # nccl in ray
            "HUGGING_FACE_HUB_TOKEN":os.environ.get('HUGGING_FACE_HUB_TOKEN'),
            "train_args_path":train_args_path,
            'OUTPUT_MODEL_S3_PATH': output_s3_path, # destination 
            "REGION": DEFAULT_REGION,            
            "dataset_info_path":dataset_info_path
        }
        if SWANLAB_API_KEY:
            environment['SWANLAB_API_KEY'] = SWANLAB_API_KEY
        if WANDB_API_KEY:
            environment["WANDB_API_KEY"] = WANDB_API_KEY
        
        self.output_s3_path = output_s3_path
        self.estimator = Estimator(image_uri=os.environ['easyr1_training_image'],
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
        return True, 'create success'
        
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
                            enable_remote_debug=True,
                            # checkpoint_local_path='/tmp/finetuned_model',
                            # checkpoint_s3_uri=output_s3_path[:-1]
                            )
        
        
    def create(self):
        from training.jobs import sync_get_job_by_id
        jobinfo=sync_get_job_by_id(self.job_id)
        logger.info(f"jobinfo of {self.job_id}:{jobinfo}")
        job_payload = jobinfo.job_payload
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        uuid = shortuuid.uuid()
        
        logger.info(f"job_payload:{job_payload}")
        
        s3_data_path=job_payload.get('s3_data_path','')

        dataset_info = {}
        dataset_info2_path = ''
        s3_datakeys=[]
        # 如果指定了s3路径
        if s3_data_path:
            # For LLamaFactory
            dataset_info_str = job_payload.get('dataset_info','')
            dataset_info = json.loads(dataset_info_str)
            s3_datakeys = list(dataset_info.keys()) if dataset_info else []
            
            # Optional for easyr1
            dataset_info_str2 = job_payload.get('dataset_info2','')
            if dataset_info_str2:
                dataset_info2 = json.loads(dataset_info_str2)
                # Save dataset for easyr1
                if dataset_info2:
                    dataset_info2_path = f's3://{default_bucket}/llm_modelhub/dataset_info_easyr1/dataset_info_{timestamp}_{uuid}.json'
                    save_json_to_s3(dataset_info2_path, dataset_info2)
            
            # 去掉末尾的反斜杠，因为training script 里会添加
            s3_data_path = s3_data_path[:-1] if s3_data_path[-1] == '/' else s3_data_path
        
        data_keys = job_payload.get('dataset',[])+s3_datakeys
        #validate checkpoint地址
        s3_checkpoint = job_payload['s3_checkpoint']
        if s3_checkpoint:
            if not is_valid_s3_uri(s3_checkpoint):
                logger.warning(f"s3_checkpoint path is invalid:{s3_checkpoint}")
                s3_checkpoint = ''
            # 去掉末尾/
            else:
                s3_checkpoint = s3_checkpoint[:-1] if s3_checkpoint.endswith('/') else s3_checkpoint


        # add to dataset_info
        dataset_info = prepare_dataset_info(dataset_info)
        # upload to s3
        dataset_info_path = f's3://{default_bucket}/llm_modelhub/dataset_info/dataset_info_{timestamp}_{uuid}.json'
        save_json_to_s3(dataset_info_path, dataset_info)
        
        #model_id参数
        repo = DownloadSource.MODELSCOPE if DEFAULT_REGION.startswith('cn') else DownloadSource.DEFAULT

        # 判断是否使用repo/model格式
        model_id=get_model_path_by_name(job_payload['model_name'],repo) if len(job_payload['model_name'].split('/')) < 2 else job_payload['model_name']
        logger.info(f"model_id:{model_id},repo type:{repo}")
        
        #validate s3_model_path
        s3_model_path = job_payload['s3_model_path']
        if s3_model_path:
            if not is_valid_s3_uri(s3_model_path):
                logger.warning(f"s3_model_path is invalid:{s3_model_path}")
                s3_model_path = ''
        
        if job_payload['stage'] in ['sft','dpo','kto','pt']:
            sg_config,sg_lora_merge_config= self.create_training_args(
                    stage=job_payload['stage'],
                    data_keys=data_keys,
                    job_payload=job_payload,
                    model_id = model_id,
                    base_config =LORA_BASE_CONFIG if job_payload['finetuning_method'] == 'lora' else FULL_BASE_CONFIG)
            
            # Lora和没有设置量化时，merge lora
            merge_lora = '1' if job_payload['finetuning_method'] == 'lora' and job_payload['quantization_bit'] == 'none' else '0'

                    
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
        elif job_payload['stage'] in ['grpo']:
            
            ret,msg = self.create_grpo_training(
                job_payload = job_payload,
                dataset_info_path=dataset_info2_path,
                data_keys = job_payload.get('dataset',[]),
                model_id=model_id,
                use_spot = job_payload.get("use_spot",False),
                max_spot_wait = int(job_payload.get("max_spot_wait",72)),
                max_job_run_hour = int(job_payload.get("max_job_run_hour",48)),
                training_input_path= s3_data_path,
                s3_model_path = s3_model_path,
                s3_checkpoint = s3_checkpoint,
                instance_type=job_payload['instance_type']
            )
            return ret,msg 
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
            
    
    

