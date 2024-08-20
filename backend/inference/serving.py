from sagemaker import Predictor
from sagemaker import serializers, deserializers
import json
import logging
from typing import Annotated, Sequence, TypedDict, Dict, Optional,List, Any,TypedDict
from utils.config import sagemaker_session,DEFAULT_REGION
from inference.model_utils import *
from utils.get_factory_config import get_model_path_by_name
from utils.llamafactory.extras.constants import DownloadSource
import os 
from logger_config import setup_logger
logger = setup_logger('serving.py', log_file='deployment.log', level=logging.INFO)

#to do, need to remove item once endpoint is deleted
predictor_pool = {}
tokenizer_pool= {}

def clean_output(response:str):
    start_sequence = '{"generated_text": "'
    stop_sequence = '"}'
    if response.startswith(start_sequence):
            response = response.lstrip(start_sequence)
    if response.endswith(stop_sequence):
        response =response.rstrip(stop_sequence)
    return response
    

def output_stream_generator(response_stream,callback = None):
    start_sequence = '{"generated_text": "'
    stop_sequence = '"}'
    for token in response_stream:
        line = token.decode('utf-8')
        if line.startswith(start_sequence):
            line = line.lstrip(start_sequence)
        if line.endswith(stop_sequence):
            line =line.rstrip(stop_sequence)
        if callback:
            callback(line)
        yield line

def get_predictor(endpoint_name:str,params:Dict[str,Any],model_args:Dict[str,Any]):
    
    if endpoint_name not in predictor_pool:
        predictor_pool[endpoint_name] = Predictor(
            endpoint_name=endpoint_name,
            sagemaker_session=sagemaker_session,
            serializer=serializers.JSONSerializer(),
        )
    if endpoint_name not in tokenizer_pool:
        tokenizer_pool[endpoint_name]=load_tokenizer(model_args)
    return predictor_pool[endpoint_name],tokenizer_pool[endpoint_name]

def inference(endpoint_name:str,model_name:str, messages:List[Dict[str,Any]],params:Dict[str,Any],stream=False):
    """
    根据给定的模型名称和端点名称，对消息进行推理。
    
    参数:
    endpoint_name (str): 模型服务的端点名称。
    model_name (str): 模型的名称。
    messages (List[Dict[str,Any]]): 需要进行推理的消息列表。
                messages = [
                {"role": "system", "content":"请始终用中文回答"},
                {"role": "user", "content": "你是谁？你是干嘛的"},
            ]
    params (Dict[str,Any]): 传递给预测器的额外参数。
    stream (bool): 指定是否使用流式推理，默认为False。
    
    返回:
    如果stream为False，返回推理的结果列表。
    如果stream为True，返回处理流式推理输出的函数。
    """
    repo = DownloadSource.MODELSCOPE if DEFAULT_REGION.startswith('cn') else DownloadSource.DEFAULT
    model_path = get_model_path_by_name(model_name,repo)
    model_args = {'cache_dir':'./cache',
                  "revision":None,
                  "model_name_or_path":model_path,
                  "trust_remote_code":True,
                  "token":os.environ['HUGGING_FACE_HUB_TOKEN']}
    predictor, tokenizer = get_predictor(endpoint_name,params,model_args)
    try:
        inputs = tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True
                )
    except ValueError as e:
        logger.error(e)
        inputs = apply_default_chat_template(
                    messages,
                    tokenize=True,
                    add_generation_prompt=True
                )
    if not stream:
        # response = await asyncio.to_thread(predictor.predict, {"inputs": inputs, "parameters": params})
        response = predictor.predict({"inputs": inputs, "parameters": params})
        return clean_output(response.decode('utf-8'))
    else:
        # response_stream = await asyncio.to_thread(predictor.predict_stream, {"inputs": inputs, "parameters": params})
        response_stream = predictor.predict_stream({"inputs": inputs, "parameters": params})
        # return response_stream
        return output_stream_generator(response_stream)
    