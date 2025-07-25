import dotenv
import boto3
import os
import sagemaker
import utils.llamafactory.extras.constants as extras
import pickle

dotenv.load_dotenv()
print(os.environ)
QLORA_BASE_CONFIG = './docker/LLaMA-Factory/examples/train_qlora/llama3_lora_sft_awq.yaml'
LORA_BASE_CONFIG = './docker/LLaMA-Factory/examples/train_lora/llama3_lora_sft.yaml'
FULL_BASE_CONFIG = './docker/LLaMA-Factory/examples/train_full/llama3_full_sft.yaml'
DATASET_INFO_FILE = './docker/LLaMA-Factory/data/dataset_info.json'
SUPPORTED_MODELS_FILE = './utils/supported_models.pkl'
DEFAULT_TEMPLATE_FILE = './utils/default_template.pkl'

# HuggingFace Accelerate, use "scheduler" if deploying a text-generation model, and "disable" for other tasks (can also the config omit entirely)
DEFAULT_ENGINE='vllm'#'scheduler'
DEFAULT_REGION = os.environ.get('region')
if os.environ.get('profile'):
    boto_sess = boto3.Session(
        profile_name=os.environ.get('profile'),
        aws_access_key_id=os.environ['AK'],
        aws_secret_access_key=os.environ['SK'],
        region_name=DEFAULT_REGION
    )
else :
    boto_sess = boto3.Session(
         aws_access_key_id=os.environ['AK'],
        aws_secret_access_key=os.environ['SK'],
        region_name=DEFAULT_REGION
    )
    
role = os.environ.get('role')
print(f"sagemaker role:{role}")


sagemaker_session =  sagemaker.session.Session(boto_session=boto_sess) #sagemaker.session.Session()
region = sagemaker_session.boto_region_name
default_bucket = sagemaker_session.default_bucket()
print(f"default_bucket:{default_bucket}")
MYSQL_CONFIG = {
    'host': os.environ['db_host'],
    'user': os.environ['db_user'],
    'password': os.environ['db_password'],
    'database': os.environ['db_name']
}
JOB_TABLE = "JOB_TABLE"
EP_TABLE = 'EP_TABLE'
USER_TABLE= 'USER_TABLE'
DEEPSPEED_BASE_CONFIG_MAP = { "stage_2":'examples/deepspeed/ds_z2_config.json',
                             "stage_3":'examples/deepspeed/ds_z3_config.json'}
WANDB_API_KEY  = os.environ.get('WANDB_API_KEY','')
WANDB_BASE_URL = os.environ.get('WANDB_BASE_URL','')
SWANLAB_API_KEY = os.environ.get('SWANLAB_API_KEY','')

# 加载持久化之后的模型列表，在endpoingt_management.py中支持修改
try:
    with open(SUPPORTED_MODELS_FILE, 'rb') as f:
        supported_models = pickle.load(f)
    
    # merge dict supported_models to extras.SUPPORTED_MODELS
    extras.SUPPORTED_MODELS = {**extras.SUPPORTED_MODELS, **supported_models} 
    # 
    # with open(DEFAULT_TEMPLATE_FILE, 'rb') as f:
    #     extras.DEFAULT_TEMPLATE = pickle.load(f)

except Exception as e:
    print(e) 

VLLM_IMAGE = os.environ.get('vllm_image')
SGLANG_IMAGE = os.environ.get('sglang_image')
MODEL_ARTIFACT = os.environ.get('model_artifact')

# check
if not VLLM_IMAGE:
    raise('vllm_image is not set in .env file')

# if not SGLANG_IMAGE:
#     raise('sglang_image is not set in .env file')

if not MODEL_ARTIFACT:
    raise('model_artifact is not set in .env file')

if not os.environ.get('role'):
    raise('role is not set in .env file')

if MODEL_ARTIFACT and not MODEL_ARTIFACT.endswith('.tar.gz'):
    raise('model_artifact must end with .tar.gz')

instance_gpus_map={
'ml.g4dn.2xlarge':1,
'ml.g4dn.12xlarge':4, 
'ml.g5.xlarge':1,
'ml.g5.2xlarge':1,
'ml.g5.4xlarge':1,
'ml.g5.12xlarge':4,
'ml.g5.48xlarge':8,
'ml.g6.2xlarge':1, 
'ml.g6.12xlarge':4, 
'ml.g6.48xlarge':8,
'ml.g6e.2xlarge':1, 
'ml.g6e.12xlarge':4, 
'ml.g6e.48xlarge':8,
'ml.p4d.24xlarge':8,
'ml.p4de.24xlarge':8,
'ml.p5.48xlarge':8,
'ml.p5e.48xlarge':8,
'ml.p5en.48xlarge':8,
}

def is_efa(instance_type):
    return 'ml.p4' in instance_type or 'ml.p5' in instance_type or 'ml.g6e' in instance_type

def get_auto_tensor_parallel_size(instance_type:str) -> int:
    return instance_gpus_map.get(instance_type, 1)
