# import argparse
import os
import boto3
import json
import socket
import re
import subprocess
import sys
import time
from urllib.parse import urlparse
from multiprocessing import Process
import tempfile
import logging
import shlex
import threading

os.environ["RAY_BACKEND_LOG_LEVEL"] = "debug"
# Force Python to run in unbuffered mode
os.environ['PYTHONUNBUFFERED'] = '1'

# Force stdout and stderr to be unbuffered
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def get_latest_checkpoint(output_s3_path,num_machines, ckpt_type='llamafactory'):
    """
    检查S3路径下是否有checkpoint-xx/ 或 global_step_xx/子目录，如果有多个，则返回step数最大的完整路径。
    会检查checkpoint目录中是否存在sync_completed_xx.flag文件，其中xx是从0到num_machines-1的数字，
    只有当所有这些标记文件都存在时，才认为该checkpoint是完整的。
    
    Args:
        output_s3_path (str): S3路径，格式为's3://bucket_name/path/to/directory/'
        num_machines: 总共的计算节点数量
        ckpt_type (str): checkpoint类型，'llamafactory'或'easyr1'
    
    Returns:
        str: 有效的checkpoint完整路径，如果没有找到任何有效checkpoint，则返回None
    """
    # 解析S3 URL
    parsed_url = urlparse(output_s3_path)
    bucket_name = parsed_url.netloc
    prefix = parsed_url.path.lstrip('/')
    
    # 确保prefix以斜杠结尾
    if not prefix.endswith('/'):
        prefix += '/'
    
    # 初始化S3客户端
    s3_client = boto3.client('s3')
    
    # 列出指定路径下的所有"目录"
    checkpoints = []
    paginator = s3_client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix, Delimiter='/'):
        if 'CommonPrefixes' in page:
            for obj in page['CommonPrefixes']:
                key = obj['Prefix']
                # 提取目录名（最后一个斜杠前的部分）
                dirname = key.rstrip('/').split('/')[-1]
                match = None
                if ckpt_type == 'llamafactory':
                    match = re.match(r'checkpoint-(\d+)$', dirname)
                elif ckpt_type == 'easyr1':
                    match = re.match(r'global_step_(\d+)$', dirname) 
                
                if match:
                    step = int(match.group(1))
                    checkpoints.append((step, key))
    
    # 如果没有找到任何checkpoint
    if not checkpoints:
        return None
    
    # 按步数降序排序
    checkpoints.sort(key=lambda x: x[0], reverse=True)
    
    # 检查checkpoints中是否包含所有必要的标记文件
    for step, checkpoint_key in checkpoints:
        # 检查该checkpoint目录中是否存在所有必要的sync_completed_xx.flag文件
        all_flags_exist = True
        for rank in range(num_machines):
            flag_key = f"{checkpoint_key}sync_completed_{rank}.flag"
            try:
                # 尝试获取flag文件的元数据，如果文件存在则不会抛出异常
                s3_client.head_object(Bucket=bucket_name, Key=flag_key)
            except Exception:
                # 文件不存在，标记为不完整
                all_flags_exist = False
                break
                
        if all_flags_exist:
            # 如果所有标记文件都存在，返回该checkpoint路径
            return f's3://{bucket_name}/{checkpoint_key}'
    
    # 如果所有checkpoint都没有完整的标记文件，返回None
    return None


def load_s3_json(s3_path,region_name):
    s3_client = boto3.client('s3',region_name)
    parsed = urlparse(s3_path)
    bucket = parsed.netloc
    key = parsed.path.lstrip('/')
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return json.loads(response['Body'].read().decode('utf-8'))

def dict_to_cmd_args(doc: dict) -> str:
    cmd_parts = [f"--{key} {value}" for key, value in doc.items()]
    return " ".join(cmd_parts)

# delete arg from cmd args
def delete_arg(args_string, arg_name):
    parts = args_string.split()
    for i,part in enumerate(parts):
        if part.startswith(f"--{arg_name}"):
            next_part = parts[i+1]
            parts.remove(part)
            parts.remove(next_part)
            break
    return " ".join(parts)

def update_arg_value(args_string, arg_name, new_value):
    parts = args_string.split()
    for i, part in enumerate(parts):
        if part == f"--{arg_name}":
            parts[i + 1] = new_value
            break
    return " ".join(parts)

def run_command(command):
    logger.info(f"run:{command}")
    try:
        cmd_parts = shlex.split(command)
        process = subprocess.Popen(
            cmd_parts,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        
        def log_output(pipe, is_error=False):
            for line in iter(pipe.readline, ''):
                if is_error and line.rstrip():
                    logger.warning(f"{line.rstrip()}")
                elif line.rstrip():
                    logger.info(f"{line.rstrip()}")
                    
        # 创建线程处理输出
        stdout_thread = threading.Thread(target=log_output, args=(process.stdout,))
        stderr_thread = threading.Thread(target=log_output, args=(process.stderr, True))
        
        stdout_thread.daemon = True
        stderr_thread.daemon = True
        stdout_thread.start()
        stderr_thread.start()
        
        # 等待进程结束
        returncode = process.wait()
        stdout_thread.join()
        stderr_thread.join()
        
        if returncode != 0:
            logger.error(f"run_command failed: errno:{returncode}")
            return False
        else:
            return True
    except Exception as e:
        logger.error(f"run_command exception: {str(e)}")
        return False

def flush_checkpoint_dir():
    print('flush checkpoint dir')
    if os.path.exists('/tmp/finetuned_model/'):
        for folder in os.listdir('/tmp/finetuned_model/'):
            if folder.startswith('checkpoint-') :
                # 同步到 S3 路径
                os.system(f'./s5cmd sync /tmp/finetuned_model/{folder} {os.environ["OUTPUT_MODEL_S3_PATH"]}')
                # 创建同步完成标记文件
                with tempfile.NamedTemporaryFile(prefix="sync_completed_", suffix=".flag", delete=False) as tmp_file:
                    tmp_file_path = tmp_file.name
                    # 写入同步时间
                    tmp_file.write(f"Sync completed at {time.strftime('%Y-%m-%d %H:%M:%S')}".encode())
                
                # 上传标记文件到S3 - 正确设置目标路径
                flag_s3_path = f"{os.environ['OUTPUT_MODEL_S3_PATH']}/{folder}/sync_completed_{os.environ['NODE_INDEX']}.flag"
                os.system(f'./s5cmd cp {tmp_file_path} {flag_s3_path}')
                
                # 删除临时文件
                os.remove(tmp_file_path)
                
                logger.info(f'Sync checkpoint completed: {folder} ')
                # 删除checkkpoint文件
                os.system(f'rm -rf /tmp/finetuned_model/{folder}')
                logger.info(f'Delete checkpoint:{folder} ')
                
def monitor_and_sync():
    """
    监控检查点的同步。
    此函数通过检查 /tmp/finetuned_model/ 目录，并检查是否有新的检查点。
    如果有，则同步到 S3 路径。
    """
    while True:
        # 检查 /tmp/finetuned_model/ 目录
        if os.path.exists('/tmp/finetuned_model/'):
            checkpoints = sorted([folder for folder in os.listdir('/tmp/finetuned_model/') if folder.startswith('checkpoint-')])
            for folder in checkpoints:
                # 同步到 S3 路径
                os.system(f'./s5cmd sync /tmp/finetuned_model/{folder} {os.environ["OUTPUT_MODEL_S3_PATH"]}')
                # 创建同步完成标记文件
                with tempfile.NamedTemporaryFile(prefix="sync_completed_", suffix=".flag", delete=False) as tmp_file:
                    tmp_file_path = tmp_file.name
                    # 写入同步时间
                    tmp_file.write(f"Sync completed at {time.strftime('%Y-%m-%d %H:%M:%S')}".encode())
                
                # 上传标记文件到S3 - 正确设置目标路径
                flag_s3_path = f"{os.environ['OUTPUT_MODEL_S3_PATH']}/{folder}/sync_completed_{os.environ['NODE_INDEX']}.flag"
                os.system(f'./s5cmd cp {tmp_file_path} {flag_s3_path}')
                
                # 删除临时文件
                os.remove(tmp_file_path)
            
                logger.info(f'Sync checkpoint completed: {folder} ')
                # 删除checkkpoint文件
                # os.system(f'rm -rf /tmp/finetuned_model/{folder}')
                # print(f'Delete checkpoint:{folder} ')
        time.sleep(10) 
        
def start_monitoring():
    """
    启动监控进程。
    此函数通过创建一个进程来启动检查点的监控，并在退出前打印一条消息。
    """
    global monitoring_process
    monitoring_process = Process(target=monitor_and_sync,daemon=True)
    monitoring_process.start()
    logger.info('Checkpoint monitoring process started.')

def stop_monitoring():
    """
    结束监控进程。
    此函数通过终止监控进程来停止检查点的监控，并在退出前再扫描一次检查点目录，以确保所有检查点都被同步。
    """
    monitoring_process.terminate()
    flush_checkpoint_dir()
    logger.info('Checkpoint monitoring process stopped.')


if __name__ == "__main__":

    regin_name = os.environ['REGION'] 
    train_args_json = load_s3_json(os.environ['train_args_path'],regin_name)
    merge_args_json = load_s3_json(os.environ['merge_args_path'],regin_name)
    datainfo = load_s3_json(os.environ['dataset_info_path'],regin_name)

    #save to data folder
    with open('/opt/ml/code/data/dataset_info.json', 'w') as f:
        json.dump(datainfo, f)

    train_args = dict_to_cmd_args(train_args_json)
    merge_args = dict_to_cmd_args(merge_args_json)

    hosts = json.loads(os.environ['SM_HOSTS'])
    current_host = os.environ['SM_CURRENT_HOST']
    host_rank = int(hosts.index(current_host))

    #Parse the IP address of the master node in the multiple nodes cluster of SageMaker training.
    master = json.loads(os.environ['SM_TRAINING_ENV'])['master_hostname']
    master_addr = socket.gethostbyname(master)

    os.environ['DS_BUILD_FUSED_ADAM'] = '1'
    os.environ['NODE_INDEX'] = str(host_rank)
    os.environ['SM_MASTER'] = str(master)
    os.environ['SM_MASTER_ADDR'] = str(master_addr)
    

    # backend env config
    # os.environ['CUDA_LAUNCH_BLOCKING'] = '1'
    if os.environ.get('USE_EFA') == '1':
        os.environ['FI_PROVIDER'] = 'efa'
        os.environ['FI_EFA_USE_DEVICE_RDMA'] = '1'
    else:
        os.environ['NCCL_SOCKET_IFNAME'] = os.environ["SM_NETWORK_INTERFACE_NAME"]


    os.environ['NCCL_DEBUG'] = 'ERROR'
    # os.environ['NCCL_OVER_OFI'] = '1'
    os.environ["NCCL_IGNORE_DISABLED_P2P"] = "1"
 
    # override deepspeed auto-detect pitfall
    os.environ["DS_ACCELERATOR"] = "cuda"

    s3_data_paths = os.environ.get('s3_data_paths')

    # num_machines = int(os.environ["NODE_NUMBER"])
    num_machines = len(hosts)
    num_processes = int(os.environ["SM_NUM_GPUS"]) * num_machines
    GPUS_PER_NODE = int(os.environ["SM_NUM_GPUS"])
    DEVICES = ','.join([str(i) for i in range(GPUS_PER_NODE)])

    
    os.system("chmod +x ./s5cmd")
    
    output_s3_path = os.environ["OUTPUT_MODEL_S3_PATH"]
    
    #检查是否有checkpoint文件存在,用于spot训练中断后恢复
    new_s3_checkpoint = get_latest_checkpoint(output_s3_path,num_machines)
    
    if s3_data_paths:
        paths = s3_data_paths.split(',')
        for s3_path in paths:
            # 同步S3数据到本地
            s3_path = s3_path[:-1] if s3_path.endswith('/') else s3_path
            s3_sync_command = f"./s5cmd sync {s3_path}/* /opt/ml/code/data/"
            run_command(s3_sync_command)
    
    #优先从new_s3_checkpoint恢复训练
    s3_checkpoint = new_s3_checkpoint if new_s3_checkpoint else os.environ.get('s3_checkpoint') 
    if s3_checkpoint:
        s3_checkpoint = s3_checkpoint[:-1] if s3_checkpoint.endswith('/') else s3_checkpoint
        # download to local
        run_command(f'./s5cmd sync --exclude "checkpoint-*" {s3_checkpoint}/* /tmp/checkpoint/')
        if not train_args_json.get('finetuning_type') == 'lora':
            # if not lora change the model path to local
            train_args = update_arg_value(train_args,"model_name_or_path","/tmp/checkpoint/")
        #add resume_from_checkpoint arg
        train_args += " --resume_from_checkpoint /tmp/checkpoint/"
        logger.info(f"resume_from_checkpoint {s3_checkpoint}")
    
    #s3 uri for model path 
    s3_model_path = os.environ.get('s3_model_path')
    if s3_model_path:
        s3_model_path = s3_model_path[:-1] if s3_model_path.endswith('/') else s3_model_path
        # download to local
        run_command(f'./s5cmd sync --exclude "checkpoint-*" {s3_model_path}/* /tmp/model_path/')
        
        # change the model path to local
        train_args = update_arg_value(train_args,"model_name_or_path","/tmp/model_path/")
        logger.info(f"s3 model_name_or_path {s3_model_path}")

    # if host_rank == 0:
    # 启动checkpoint监控进程，ckpt分布在各个节点保存
    start_monitoring()

    logger.info(f'------envs------\nnum_machines:{num_machines}\nnum_processes:{num_processes}\nnode_rank:{host_rank}\n')
    if num_machines > 1: 
        train_command = f"FORCE_TORCHRUN=1  NNODES={num_machines} NODE_RANK={host_rank} MASTER_ADDR={master_addr} MASTER_PORT=29500 llamafactory-cli train {train_args}"
    else:
        train_command = f"CUDA_VISIBLE_DEVICES={DEVICES} llamafactory-cli train {train_args}"

    exit_code = os.system(train_command)
    if exit_code != 0:
        logger.info(f"Train failed with exit code: {exit_code}")
        # if host_rank == 0:
        # 停止checkpoint监控
        stop_monitoring()
        sys.exit(1)

    # if host_rank == 0:
    # 停止checkpoint监控
    stop_monitoring()
        
    if os.environ.get("merge_lora") == '1' and host_rank == 0:
        ## update model path as local folder as s3 provided
        if s3_model_path:
            merge_args = update_arg_value(merge_args,"model_name_or_path","/tmp/model_path/")
        logger.info(f'-----start merge lora-------')
        merge_command = f'llamafactory-cli export {merge_args}'
        run_command(merge_command)

        logger.info(f'-----end merge lora-------')
        sync_merged_command = f'./s5cmd sync --exclude "checkpoint-*" /tmp/finetuned_model_merged {os.environ["OUTPUT_MODEL_S3_PATH"]}'
        run_command(sync_merged_command)

          
    if host_rank == 0:
        logger.info("*****************finished training, start cp finetuned model*****************************")
        sync_final_command = f'./s5cmd sync --exclude "checkpoint-*" /tmp/finetuned_model {os.environ["OUTPUT_MODEL_S3_PATH"]}'
        run_command(sync_final_command)
        logger.info(f'-----finished cp-------')


    # if os.environ.get("MMLU_EVAL") == '1':
    #     print(f'-----start model eval-------')
    #     model_path = "/tmp/finetuned_model_merged" if  os.environ.get("merge_lora") == '1' else "/tmp/finetuned_model"
    #     eval_command = f"llamafactory-cli eval --model_name_or_path {model_path} --task mmlu_test --template fewshot --lang en --n_shot 5 --batch_size 4"
    #     os.system(eval_command)