import time
import uuid
import os
import sys
sys.path.append('./')
import json
import logging
import asyncio
from typing import Annotated, Sequence, TypedDict, Dict, Optional,List, Any,TypedDict

from model.data_model import CommonResponse,ListModelNamesResponse,GetFactoryConfigRequest
from utils.llamafactory.extras.constants import SUPPORTED_MODELS,DEFAULT_TEMPLATE,TRAINING_STAGES,DATA_CONFIG,STAGES_USE_PAIR_DATA,DownloadSource
DEFAULT_DATA_DIR = 'utils/llamafactory/data'
logger = logging.getLogger()
# print(os.listdir())
class APIException(Exception):
    def __init__(self, message, code: str = None):
        if code:
            super().__init__("[{}] {}".format(code, message))
        else:
            super().__init__(message)
            
def load_dataset_info(dataset_dir: str) -> Dict[str, Dict[str, Any]]:
    r"""
    Loads dataset_info.json.
    """
    if dataset_dir == "ONLINE":
        logger.info("dataset_dir is ONLINE, using online dataset.")
        return {}

    try:
        with open(os.path.join(dataset_dir, DATA_CONFIG), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as err:
        logger.warning("Cannot open {} due to {}.".format(os.path.join(dataset_dir, DATA_CONFIG), str(err)))
        return {}


def list_datasets(dataset_dir: str = None, training_stage: str = list(TRAINING_STAGES.keys())[0]):
    r"""
    Lists all available datasets in the dataset dir for the training stage.
    """
    dataset_info = load_dataset_info(dataset_dir if dataset_dir is not None else DEFAULT_DATA_DIR)
    ranking = TRAINING_STAGES[training_stage] in STAGES_USE_PAIR_DATA
    datasets = [k for k, v in dataset_info.items() if v.get("ranking", False) == ranking]
    return datasets  

def get_model_path_by_name(name:str,repo=DownloadSource.DEFAULT) -> str:
    return SUPPORTED_MODELS[name].get(repo,'not exist')
            
async def get_factory_config(request:GetFactoryConfigRequest,repo=DownloadSource.DEFAULT) ->CommonResponse:
    if request.config_name == 'model_name':
        model_names = [{"model_name":name,"model_path":SUPPORTED_MODELS[name].get(repo,'not exist')} for name in list(SUPPORTED_MODELS.keys()) if SUPPORTED_MODELS[name].get(repo) ]
        return CommonResponse(response_id=str(uuid.uuid4()),response={"body":model_names})
    elif request.config_name == 'prompt_template':
        templates = list(DEFAULT_TEMPLATE.keys())
        return CommonResponse(response_id=str(uuid.uuid4()),response={"body":templates})
    elif request.config_name == 'dataset':
        datasets = list_datasets()
        return CommonResponse(response_id=str(uuid.uuid4()),response={"body":datasets})
    else:
        raise APIException(f"Invalid config_name: {request.config_name}")

if __name__ == '__main__':
    request = GetFactoryConfigRequest(config_name="dataset")
    reply = asyncio.run(get_factory_config(request))
    print(reply)