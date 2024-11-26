# import argparse
import os
import boto3
import json
import socket
# import yaml
import subprocess
import sys
import time
from urllib.parse import urlparse
from multiprocessing import Process


def load_s3_json(s3_path):
    s3_client = boto3.client('s3')
    parsed = urlparse(s3_path)
    bucket = parsed.netloc
    key = parsed.path.lstrip('/')
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return json.loads(response['Body'].read().decode('utf-8'))

def dict_to_cmd_args(doc: dict) -> str:
    cmd_parts = [f"--{key} {value}" for key, value in doc.items()]
    return " ".join(cmd_parts)

def update_arg_value(args_string, arg_name, new_value):
    parts = args_string.split()
    for i, part in enumerate(parts):
        if part == f"--{arg_name}":
            parts[i + 1] = new_value
            break
    return " ".join(parts)

def run_command(command):
    try:
        result = subprocess.run(command, check=True, shell=True, text=True, capture_output=True)
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Command failed with error: {e}", file=sys.stderr)
        print(f"Error output: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)

def flush_checkpoint_dir():
    print('flush checkpoint dir')
    if os.path.exists('/tmp/finetuned_model/'):
        for folder in os.listdir('/tmp/finetuned_model/'):
            if folder.startswith('checkpoint-') :
                # 同步到 S3 路径
                os.system(f'./s5cmd sync /tmp/finetuned_model/{folder} {os.environ["OUTPUT_MODEL_S3_PATH"]}')
                print(f'Sync checkpoint completed: {folder} ')
                # 删除checkkpoint文件
                os.system(f'rm -rf /tmp/finetuned_model/{folder}')
                print(f'Delete checkpoint:{folder} ')
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
                print(f'Sync checkpoint completed: {folder} ')
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
    monitoring_process = Process(target=monitor_and_sync)
    monitoring_process.start()
    print('Checkpoint monitoring process started.')

def stop_monitoring():
    """
    结束监控进程。
    此函数通过终止监控进程来停止检查点的监控，并在退出前再扫描一次检查点目录，以确保所有检查点都被同步。
    """
    monitoring_process.terminate()
    flush_checkpoint_dir()
    print('Checkpoint monitoring process stopped.')


if __name__ == "__main__":

    train_args_json = load_s3_json(os.environ['train_args_path'])
    merge_args_json = load_s3_json(os.environ['merge_args_path'])
    datainfo = load_s3_json(os.environ['dataset_info_path'])

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

    num_machines = int(os.environ["NODE_NUMBER"])
    num_processes = int(os.environ["SM_NUM_GPUS"]) * num_machines
    GPUS_PER_NODE = int(os.environ["SM_NUM_GPUS"])
    DEVICES = ','.join([str(i) for i in range(GPUS_PER_NODE)])

    # index_path = os.environ.get('PIP_INDEX')
    # if index_path:
    #     os.system(f"pip config set global.index-url {index_path}")
    #     os.system(f"pip config set global.extra-index-url  {index_path}")
    #     os.system(f"pip install -r requirements_deps.txt")
    # else:
    #     os.system(f"pip install -r requirements_deps.txt")

    
    os.system("chmod +x ./s5cmd")

    if s3_data_paths:
        paths = s3_data_paths.split(',')
        for s3_path in paths:
            # 同步S3数据到本地
            s3_path = s3_path[:-1] if s3_path.endswith('/') else s3_path
            s3_sync_command = f"./s5cmd sync {s3_path}/* /opt/ml/code/data/"
            run_command(s3_sync_command)
    
    #s3 uri for checkpoint 
    s3_checkpoint = os.environ.get('s3_checkpoint')
    if s3_checkpoint:
        s3_checkpoint = s3_checkpoint[:-1] if s3_checkpoint.endswith('/') else s3_checkpoint
        # download to local
        run_command(f'./s5cmd sync --exclude "checkpoint-*" {s3_checkpoint}/* /tmp/checkpoint/')
        train_args += " --resume_from_checkpoint /tmp/checkpoint/"
        print(f"resume_from_checkpoint {s3_checkpoint}")
    
    #s3 uri for model path 
    s3_model_path = os.environ.get('s3_model_path')
    if s3_model_path:
        s3_model_path = s3_model_path[:-1] if s3_model_path.endswith('/') else s3_model_path
        # download to local
        run_command(f'./s5cmd sync --exclude "checkpoint-*" {s3_model_path}/* /tmp/model_path/')
        
        # change the model path to local
        train_args = update_arg_value(train_args,"model_name_or_path","/tmp/model_path/")
        print(f"s3 model_name_or_path {s3_model_path}")

    if host_rank == 0:
        # 启动checkpoint监控进程
        start_monitoring()

    print(f'------envs------\nnum_machines:{num_machines}\nnum_processes:{num_processes}\nnode_rank:{host_rank}\n')
    if num_machines > 1: 
        train_command = f"FORCE_TORCHRUN=1  NNODES={num_machines} NODE_RANK={host_rank} MASTER_ADDR={master_addr} MASTER_PORT=29500 llamafactory-cli train {train_args}"
    else:
        train_command = f"CUDA_VISIBLE_DEVICES={DEVICES} llamafactory-cli train {train_args}"

    exit_code = os.system(train_command)
    if exit_code != 0:
        print(f"Train failed with exit code: {exit_code}")
        if host_rank == 0:
            # 停止checkpoint监控
            stop_monitoring()
        sys.exit(1)

    if host_rank == 0:
        # 停止checkpoint监控
        stop_monitoring()
        
    if os.environ.get("merge_lora") == '1' and host_rank == 0:
        print(f'-----start merge lora-------')
        merge_command = f'CUDA_VISIBLE_DEVICES=0 llamafactory-cli export {merge_args}'
        run_command(merge_command)

        print(f'-----end merge lora-------')
        sync_merged_command = f'./s5cmd sync --exclude "checkpoint-*" /tmp/finetuned_model_merged {os.environ["OUTPUT_MODEL_S3_PATH"]}'
        run_command(sync_merged_command)

          
    if host_rank == 0:
        print("*****************finished training, start cp finetuned model*****************************")
        sync_final_command = f'./s5cmd sync --exclude "checkpoint-*" /tmp/finetuned_model {os.environ["OUTPUT_MODEL_S3_PATH"]}'
        run_command(sync_final_command)
        print(f'-----finished cp-------')


    # if os.environ.get("MMLU_EVAL") == '1':
    #     print(f'-----start model eval-------')
    #     model_path = "/tmp/finetuned_model_merged" if  os.environ.get("merge_lora") == '1' else "/tmp/finetuned_model"
    #     eval_command = f"llamafactory-cli eval --model_name_or_path {model_path} --task mmlu_test --template fewshot --lang en --n_shot 5 --batch_size 4"
    #     os.system(eval_command)