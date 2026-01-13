from sagemaker import Predictor
from sagemaker import serializers, deserializers
import json
import logging
from typing import Annotated, Sequence, TypedDict, Dict, Optional,List, Any,TypedDict
from utils.config import sagemaker_session,DEFAULT_REGION
from inference.model_utils import *
from utils.get_factory_config import get_model_path_by_name
from utils.llamafactory.extras.constants import DownloadSource
from utils.llamafactory.hparams.model_args import ModelArguments

import os 
import time
import uuid
from logger_config import setup_logger
logger = setup_logger('serving.py', level=logging.INFO)

#to do, need to remove item once endpoint is deleted
predictor_pool = {}
tokenizer_pool= {}

def construct_response_messasge(text:str,model_name:str) -> Dict[str,Any]:
    return {
        "model":model_name,
        "usage": None,
        "created":int(time.time()),
        "system_fingerprint": "fp",
        "choices":[
            {
                "index": 0,
                "finish_reason": "stop",
                "logprobs": None,
                "message": {
                    "role": "assistant",
                    "content": text
                }
            }
        ],
        'id':str(uuid.uuid4()),
        }

def construct_chunk_message(id,delta,finish_reason,model):
    return {
        "id": id,
        "model": model,
        "object": "chat.completion.chunk",
        "usage": None,
        "created":int(time.time()),
        "system_fingerprint": "fp",
        "choices":[{
            "index": 0,
            "finish_reason": finish_reason,
            "logprobs": None,
            "delta": delta
        }
        ]}


# 生成一个openai格式的streaming response
def construct_stream_response_messasge(text:str,model_name:str) :
    id = str(uuid.uuid4())
    chunk= construct_chunk_message(id=id,model=model_name,finish_reason=None,delta={ "role": "assistant","content": ""})
    yield f"data: {json.dumps(chunk)}\n\n"

    chunk= construct_chunk_message(id=id,model=model_name,finish_reason=None,delta={"content": text})
    yield f"data: {json.dumps(chunk)}\n\n"

    chunk= construct_chunk_message(id=id,model=model_name,finish_reason="stop",delta={})
    yield f"data: {json.dumps(chunk)}\n\n"
    yield f"data: [DONE]\n\n"

def clean_output(response:str):
    start_sequence = '{"generated_text": "'
    stop_sequence = '"}'
    if response.startswith(start_sequence):
            response = response.lstrip(start_sequence)
    if response.endswith(stop_sequence):
        response =response.rstrip(stop_sequence)
    return response
    
def output_stream_generator_byoc(response_stream,callback = None):
    for token in response_stream:
        line = token.decode('utf-8')
        yield line

def output_stream_generator(response_stream,callback = None):
    start_sequence = '{"generated_text": "'
    stop_sequence = '"}'
    for token in response_stream:
        line = token.decode('utf-8')
        # print(line)
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
    if endpoint_name not in tokenizer_pool and model_args:
        tokenizer_pool[endpoint_name]=load_tokenizer(model_args)
    return predictor_pool[endpoint_name],tokenizer_pool.get(endpoint_name)

def inference_byoc(endpoint_name:str,model_name:str, messages:List[Dict[str,Any]],params:Dict[str,Any],stream=False):
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
    repo_type = DownloadSource.MODELSCOPE  if DEFAULT_REGION.startswith('cn') else DownloadSource.DEFAULT
    #统一处理成repo/modelname格式
    model_name=get_model_path_by_name(model_name,repo_type) if model_name and len(model_name.split('/')) < 2 else model_name
    model_args = {'cache_dir':'./cache',
                  "revision":None,
                  "model_name_or_path":model_name,
                  "trust_remote_code":True,
                  "token":os.environ['HUGGING_FACE_HUB_TOKEN']}

    predictor, tokenizer = get_predictor(endpoint_name,params={},model_args=model_args)
    if tokenizer:
        has_chat_template = hasattr(tokenizer, 'chat_template') and tokenizer.chat_template is not None
        print(f"has_chat_template:{has_chat_template}")
        logger.info(f"has_chat_template:{has_chat_template}")
    else:
        has_chat_template = None
        logger.info(f"tokenizer is None")
    # try:
    #     inputs = tokenizer.apply_chat_template(
    #                 messages,
    #                 tokenize=False,
    #                 add_generation_prompt=True
    #             )
    # except ValueError as e:
    #     logger.error(e)
    #     inputs = apply_default_chat_template(
    #                 messages,
    #                 tokenize=True,
    #                 add_generation_prompt=True
    #             )

    print(f"params:{params}")
    payload = {
        "model":model_name,
        "messages":messages,
        "stream":stream,
        "max_tokens":params.get('max_new_tokens', params.get('max_tokens', 256)),
        "temperature":params.get('temperature', 0.1),
        "top_p":params.get('top_p', 0.9),
    }
    # 如果没有模板，则使用自定义模板
    if not has_chat_template and params.get('chat_template'):
        payload['chat_template'] = params['chat_template']
        logger.info(f"use chat_template:{params['chat_template']}")

    if not stream:
        try:
            response = predictor.predict(payload)
            return json.loads(response)
        except Exception as e:
            logger.error(f"-----predict-error:\n{str(e)}")
            print(f"-----predict-error:{str(e)}")
            return construct_response_messasge(str(e),model_name)

    else:
        try:
            response_stream = predictor.predict_stream(payload)
            # return response_stream
            return output_stream_generator_byoc(response_stream)
        except Exception as e:
            logger.error(f"-----predict-error:\n{str(e)}")
            print(f"-----predict-error:{str(e)}")
            return construct_stream_response_messasge(str(e),model_name)
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
    # repo = DownloadSource.MODELSCOPE if DEFAULT_REGION.startswith('cn') else DownloadSource.DEFAULT
    # # model_path = get_model_path_by_name(model_name,repo)
    # model_args = {'cache_dir':'./cache',
    #               "revision":None,
    #               "model_name_or_path":model_name,
    #               "trust_remote_code":True,
    #               "token":os.environ['HUGGING_FACE_HUB_TOKEN']}
    predictor, tokenizer = get_predictor(endpoint_name,params,model_args={})
    # try:
    #     inputs = tokenizer.apply_chat_template(
    #                 messages,
    #                 tokenize=False,
    #                 add_generation_prompt=True
    #             )
    # except ValueError as e:
    #     logger.error(e)
    #     inputs = apply_default_chat_template(
    #                 messages,
    #                 tokenize=True,
    #                 add_generation_prompt=True
    #             )

    payload = {
        "model":model_name,
        "messages":messages,
        "stream":stream,
        "max_tokens":params.get('max_new_tokens', params.get('max_tokens', 256)),
        "temperature":params.get('temperature', 0.1),
        "top_p":params.get('top_p', 0.9),
    }
    if not stream:
        try:
            response = predictor.predict(payload)
            return json.loads(response)
        except Exception as e:
            logger.error('-----predict-error---')
            logger.error(str(e))
            return construct_response_messasge(str(e),model_name)
            
    else:
        try:
            response_stream = predictor.predict_stream(payload)
            # return response_stream
            return output_stream_generator_byoc(response_stream)
        except Exception as e:
            logger.error(f"-----predict-error:\n{str(e)}")
            print(f"-----predict-error:{str(e)}")
            return construct_stream_response_messasge(str(e),model_name)
    