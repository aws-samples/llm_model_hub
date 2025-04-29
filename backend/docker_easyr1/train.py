import os
import json
import socket
import yaml
import subprocess
import sys
import boto3
import time
from urllib.parse import urlparse
from multiprocessing import Process
import ray
import logging
import shlex
import threading

os.environ["RAY_BACKEND_LOG_LEVEL"] = "debug"
# Force Python to run in unbuffered mode
os.environ['PYTHONUNBUFFERED'] = '1'

# Force stdout and stderr to be unbuffered
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
monitoring_process = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


@ray.remote
class TrainingStatus:
    def __init__(self):
        self.status = {"training_complete": False}
        
    def set_status(self, status):
        self.status = status
        return True
        
    def get_status(self):
        return self.status

    
    

def connect_to_ray_with_retry(head_ip, max_retries=30, wait_time=10):
    """Connect to Ray head with exponential backoff"""
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Attempt {attempt+1} to connect to Ray head at {head_ip}:6379")
            os.system(f"ray start --address={head_ip}:6379")
            ray.init(address="auto")  
            logger.info("Successfully connected to Ray head node!")
            return True
        except Exception as e:
            logger.info(f"Connection failed: {e}")
            logger.info(f"Waiting {wait_time} seconds before retrying...")
            time.sleep(wait_time)
    logger.info("Maximum retries reached. Could not connect to Ray head node.")
    return False

def wait_for_complete_cluster(expected_nodes, timeout_seconds=300):
    """
    Wait until all expected nodes have joined the Ray cluster.
    
    Args:
        expected_nodes: Total number of nodes (including head node)
        timeout_seconds: Maximum waiting time
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout_seconds:
        logger.info('---waite for other nodes-----')
        # Get current cluster nodes
        current_nodes = len(ray.nodes())
        logger.info(f"Connected nodes: {current_nodes}/{expected_nodes}")
        
        if current_nodes >= expected_nodes:
            logger.info("✓ Complete cluster formed!")
            return True
            
        time.sleep(10)  # Check every 10 seconds
        
    logger.info(f"✗ Timeout after {timeout_seconds}s. Only {len(ray.nodes())}/{expected_nodes} nodes connected.")
    return False


def load_s3_json(s3_path,region_name):
    s3_client = boto3.client('s3',region_name)
    parsed = urlparse(s3_path)
    bucket = parsed.netloc
    key = parsed.path.lstrip('/')
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return json.loads(response['Body'].read().decode('utf-8'))

def load_s3_and_save_text(s3_path,local_folder,region_name):
    s3_client = boto3.client('s3',region_name)
    parsed = urlparse(s3_path)
    bucket = parsed.netloc
    key = parsed.path.lstrip('/')
    response = s3_client.get_object(Bucket=bucket, Key=key)
    filename = key.split('/')[-1]
    text = response['Body'].read().decode('utf-8')
    output_file = f"{local_folder}/{filename}"
    with open(output_file,'w') as f:
        f.write(text)
    return output_file

def dict_to_cmd_args(doc: dict) -> str:
    cmd_parts = [f"{key}={value}" for key, value in doc.items()]
    return " ".join(cmd_parts)

def delete_arg(args_string, arg_name):
    parts = args_string.split()
    for i,part in enumerate(parts):
        if part.startswith(f"{arg_name}"):
            parts.remove(part)
            break
    return " ".join(parts)

def update_arg_value(args_string, arg_name, new_value):
    parts = args_string.split()
    is_exist = False
    for i, part in enumerate(parts):
        if part.startswith(f"{arg_name}"):
            is_exist = True
            key,val = part.split('=')
            parts[i] = f'{key}={new_value}'
            break
    
    #如何不存在，则添加
    if not is_exist:
        parts.append(f"{arg_name}={new_value}")
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


def get_last_checkpoint():
    if os.path.exists('/tmp/checkpoints/'):
        checkpoints = sorted([folder for folder in os.listdir('/tmp/checkpoints/') if folder.startswith('global_step')])
        return checkpoints[-1] if checkpoints else []
    
def flush_checkpoint_dir():
    logger.info('flush checkpoint dir')
    if os.path.exists('/tmp/checkpoints/'):
        checkpoints = sorted([folder for folder in os.listdir('/tmp/checkpoints/') if folder.startswith('global_step')])
        for folder in checkpoints:
            # 同步到 S3 路径
            os.system(f'./s5cmd sync /tmp/checkpoints/{folder} {os.environ["OUTPUT_MODEL_S3_PATH"]}')
            logger.info(f'Sync checkpoint completed: {folder} ')

                
                
def monitor_and_sync():
    """
    监控检查点的同步。
    此函数通过检查 /tmp/checkpoints/ 目录，并检查是否有新的检查点。
    如果有，则同步到 S3 路径。
    """
    while True:
        # 检查 /tmp/checkpoints/ 目录
        if os.path.exists('/tmp/checkpoints/'):
            checkpoints = sorted([folder for folder in os.listdir('/tmp/checkpoints/') if folder.startswith('global_step')])
            for folder in checkpoints:
                # 同步到 S3 路径
                os.system(f'./s5cmd sync /tmp/checkpoints/{folder} {os.environ["OUTPUT_MODEL_S3_PATH"]}')
                logger.info(f'Sync checkpoint completed: {folder} ')
            # 删除历史的checkpoints
            # EasyR1 会只保留最近的n个checkpoint
            # if checkpoints:
            #     for folder in checkpoints[:-1]:
            #         # 删除checkkpoint文件
            #         os.system(f'rm -rf /tmp/checkpoints/{folder}')
            #         logger.info(f'Delete checkpoint:{folder} ')
        time.sleep(10) 
        

        
def start_monitoring():
    """
    启动监控进程。
    此函数通过创建一个进程来启动检查点的监控，并在退出前打印一条消息。
    """
    global monitoring_process
    if not monitoring_process:
        monitoring_process = Process(target=monitor_and_sync)
        monitoring_process.start()
        logger.info('Checkpoint monitoring process started.')

def stop_monitoring():
    """
    结束监控进程。
    此函数通过终止监控进程来停止检查点的监控，并在退出前打印一条消息。
    """
    global monitoring_process
    if monitoring_process:
        monitoring_process.terminate()
        flush_checkpoint_dir()
        logger.info('Checkpoint monitoring process stopped.')

    
def stop_and_exit(code):
    stop_monitoring()
    sys.exit(code)
    
if __name__ == "__main__":
    regin_name = os.environ['REGION']
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
    if os.environ.get('USE_EFA') == '1':
        os.environ['FI_PROVIDER'] = 'efa'
        os.environ['FI_EFA_USE_DEVICE_RDMA'] = '1'
    else:
        os.environ['NCCL_SOCKET_IFNAME'] = os.environ["SM_NETWORK_INTERFACE_NAME"]
    
    os.environ['NCCL_DEBUG'] = 'ERROR'
    os.environ["NCCL_IGNORE_DISABLED_P2P"] = "1"
    
    # num_machines = int(os.environ["NODE_NUMBER"])
    if not os.environ["OUTPUT_MODEL_S3_PATH"].endswith('/'):
        os.environ["OUTPUT_MODEL_S3_PATH"] += '/'
    num_machines = len(hosts)
    num_processes = int(os.environ["SM_NUM_GPUS"]) * num_machines
    dataset_info_path = os.environ.get('dataset_info_path','')
    datainfo = {}
    if dataset_info_path:
        datainfo = load_s3_json(dataset_info_path,regin_name)
    s3_data_paths = os.environ.get('s3_data_paths')
    GPUS_PER_NODE = int(os.environ["SM_NUM_GPUS"])
    DEVICES = ','.join([str(i) for i in range(GPUS_PER_NODE)])
    
    train_args_json = load_s3_json(os.environ['train_args_path'],regin_name)  
    train_args = dict_to_cmd_args(train_args_json)
    
    if os.environ.get('reward_function_path'):
        reward_function_file = load_s3_and_save_text(os.environ['reward_function_path'],
                                                     './examples/reward_function',
                                                     regin_name)
        train_args = update_arg_value(train_args,"worker.reward.reward_function",f"{reward_function_file}:compute_score")
        
    if os.environ.get('format_prompt_path'):
        format_prompt_file = load_s3_and_save_text(os.environ['format_prompt_path'],
                                                     './examples/format_prompt',
                                                     regin_name)
        train_args = update_arg_value(train_args,"data.format_prompt",f"{format_prompt_file}")
        
    
    os.system("chmod +x ./s5cmd")

    if s3_data_paths and datainfo:
        paths = s3_data_paths.split(',')
        for s3_path in paths:
            # 同步S3数据到本地
            s3_sync_command = f"./s5cmd sync {s3_path}/* /opt/ml/code/data/"
            ret = run_command(s3_sync_command)
            if not ret:
                stop_and_exit(1)
        train_file = datainfo.get('train_file','')
        val_file = datainfo.get('val_file','')
        train_args = update_arg_value(train_args,"data.train_files",f"/opt/ml/code/data/{train_file}")
        train_args = update_arg_value(train_args,"data.val_files",f"/opt/ml/code/data/{val_file}")

            
        

    #s3 uri for checkpoint 
    s3_checkpoint = os.environ.get('s3_checkpoint')
    if s3_checkpoint:
        s3_checkpoint = s3_checkpoint[:-1] if s3_checkpoint.endswith('/') else s3_checkpoint
        suffix = s3_checkpoint.split('/')[-1]
        target = f"/tmp/checkpoints/{suffix}/"
        # download to local
        run_command(f'./s5cmd sync --exclude "huggingface" {s3_checkpoint}/*  {target}')
        train_args = update_arg_value(train_args,"trainer.load_checkpoint_path",target)
        logger.info(f"load_checkpoint_path {s3_checkpoint} to {target}")
        
    #s3 uri for model path 
    s3_model_path = os.environ.get('s3_model_path')
    if s3_model_path:
        s3_model_path = s3_model_path[:-1] if s3_model_path.endswith('/') else s3_model_path
        # download to local
        run_command(f'./s5cmd sync --exclude "global_step*" {s3_model_path}/* /tmp/model_path/')
        if not ret:
            stop_and_exit(1)
        
        # change the model path to local
        train_args = update_arg_value(train_args,"worker.actor.model.model_path","/tmp/model_path/")
        logger.info(f"s3 model_name_or_path {s3_model_path}")
    
    # 启动checkpoint监控进程
    start_monitoring()
    
    use_ray = True if num_machines > 1 else False
    logger.info(f'------envs------\nnum_machines:{num_machines}\nnum_processes:{num_processes}\nhost_rank:{host_rank}\nuse_ray:{use_ray}')

    if host_rank == 0:
        if use_ray:
            # Start the Ray head node.
            logger.info("ray start --head --port=6379")
            os.system(f"ray start --head --port=6379")
            # 给系统一点时间启动Ray服务
            time.sleep(5)
            # Initialize Ray in the Python process
            ray.init(address="auto")  # 自动连接到已有的节点
            logger.info(f'rank:{host_rank} ray status')
            os.system('ray status')
            
             # Create the status actor
            status_actor = TrainingStatus.options(name="training_status", namespace="distributed_training").remote()
            
            if not wait_for_complete_cluster(expected_nodes=num_machines):
                logger.info(f'wait for cluster timeout')
                stop_and_exit(1)
            
            # Create a flag in Ray's object store to signal training status
            status_ref = {"training_complete": False}
            status_actor.set_status.remote(status_ref)
            
            # Run training as before
            train_command = f"python3 -m verl.trainer.main {train_args}"
            ret = run_command(train_command)
            if not ret:
                logger.info(f"Train failed")
                status_actor.set_status.remote({"training_complete": True})
                time.sleep(5)
                ray.shutdown()
                stop_and_exit(1)
                
            logger.info("Train completed!")
            # 更新状态
            status_actor.set_status.remote({"training_complete": True})
            # 确保状态更新被执行
            time.sleep(5)
            
        else:
            # Not use ray
            train_command = f"python3 -m verl.trainer.main {train_args}"
            ret = run_command(train_command)
            if not ret:
                stop_and_exit(1)
    else:
        if use_ray:# For Worker Node 
            # 增加连接重试次数和间隔
            if not connect_to_ray_with_retry(master_addr, max_retries=60, wait_time=20):
                logger.info(f'failed to connect to head node {master_addr}:6379')
                stop_and_exit(1)
            time.sleep(5)
            logger.info(f'rank:{host_rank} ray status')
            os.system('ray status')

            # 等待确保集群稳定
            time.sleep(10)

            # 工作节点等待循环
            logger.info("Worker node connected to Ray. Entering wait loop...")
            err_attempts = 0
            while True:
                try:
                    # 检查训练是否完成
                    try:
                        # 增加重试机制获取actor
                        retry_count = 0
                        status_actor = None
                        while retry_count < 5:
                            try:
                                status_actor = ray.get_actor("training_status", namespace="distributed_training")
                                break
                            except Exception:
                                logger.info(f"Retry {retry_count+1} getting actor...")
                                time.sleep(5)
                                retry_count += 1

                        if status_actor:
                            status = ray.get(status_actor.get_status.remote())
                            if status.get("training_complete", False):
                                logger.info("Training complete signal received. Worker exiting.")
                                break
                    except Exception as e:
                        logger.info(f"Could not get training status: {str(e)}")

                    logger.info("Worker node still active.")
                    time.sleep(30)
                except Exception as e:
                    logger.info(f"Worker encountered exception: {str(e)}")
                    time.sleep(30)
                    err_attempts += 1
                    if err_attempts > 10:
                        logger.info("Max error retry times reached, exit")
                        stop_and_exit(1)

    # 停止checkpoint监控
    stop_monitoring()
    
    if  host_rank == 0:
        logger.info(f'-----start merge -------')
        os.system("ls /tmp/checkpoints/")
        last_folder = get_last_checkpoint()
        logger.info(f'last checkpoint folder:{last_folder}')
        
        # 如果是分布式的，需要先从s3 sync回完整的checkpoint文件再merge
        if use_ray:
            os.system(f'./s5cmd sync {os.environ["OUTPUT_MODEL_S3_PATH"]}{last_folder}/* /tmp/checkpoints/{last_folder}')
            
        merge_command = f'python3 scripts/model_merger.py --local_dir /tmp/checkpoints/{last_folder}/actor'
        ret = run_command(merge_command)
        if not ret:
            logger.warning(f"merge checkpoint failed, but you can still find it in s3 bucket")
        
        logger.info("*****************finished training, start cp finetuned model*****************************")
        sync_final_command = f"./s5cmd sync /tmp/checkpoints/{last_folder}/actor/huggingface {os.environ['OUTPUT_MODEL_S3_PATH']}"
        ret = run_command(sync_final_command)
        if not ret:
            logger.warning(f"merge checkpoint failed, but you can still find it in s3 bucket")
        logger.info(f'-----finished cp-------')
  