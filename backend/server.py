import argparse
import json
import os
from typing import Generator, Optional, Union, Dict, List, Any
from logger_config import setup_logger
import logging
import dotenv
import fastapi
from fastapi import Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security.http import HTTPAuthorizationCredentials, HTTPBearer
# from pydantic_settings import BaseSettings
from fastapi.security import OAuth2PasswordBearer
from fastapi.responses import StreamingResponse
from typing import AsyncIterable
import uvicorn
import time
import uuid
from pydantic import BaseModel,Field
from model.data_model import *
import asyncio
from training.jobs import create_job,list_jobs,get_job_by_id,delete_job_by_id,fetch_training_log,get_job_status
from utils.get_factory_config import get_factory_config
from utils.outputs import list_s3_objects
from inference.endpoint_management import deploy_endpoint,delete_endpoint,get_endpoint_status,list_endpoints,deploy_endpoint_byoc,get_endpoint_engine
from inference.serving import inference,inference_byoc
from users.login import login_auth
from utils.config import DEFAULT_REGION
from utils.llamafactory.extras.constants import DownloadSource


dotenv.load_dotenv()

logger = setup_logger('server.py', log_file='server.log', level=logging.INFO)
api_keys = os.environ['api_keys'].split(',')
print(api_keys)
class AppSettings(BaseModel):
    # The address of the model controller.
    api_keys: Optional[List[str]] = None


app_settings = AppSettings(api_keys=api_keys)
app = fastapi.FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)
headers = {"User-Agent": "Chat Server"}
get_bearer_token = HTTPBearer(auto_error=False)
async def check_api_key(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(get_bearer_token),
) -> str:
    # print(app_settings.api_keys)
    if app_settings.api_keys:
        if auth is None or (token := auth.credentials) not in app_settings.api_keys:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "message": "",
                        "type": "invalid_request_error",
                        "param": None,
                        "code": "invalid_api_key",
                    }
                },
            )
        return token
    else:
        raise HTTPException(
                status_code=403,
                detail={
                    "error": {
                        "message": "",
                        "type": "invalid_request_error",
                        "param": None,
                        "code": "invalid_api_key",
                    }
                },
            )

class ErrorResponse(BaseModel):
    object: str = "error"
    message: str
    code: int


class APIRequestResponse(BaseModel):
    message:str

    
def create_error_response(code: int, message: str) -> JSONResponse:
    return JSONResponse(
        ErrorResponse(message=message, code=code).json(), status_code=400
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return create_error_response(400, str(exc))

@app.get("/")
async def ping():
    return APIRequestResponse(message='ok')

@app.post("/v1/login",dependencies=[Depends(check_api_key)])
async def handel_login(request:LoginRequest):
    response = login_auth(username = request.username,password = request.password)
    return CommonResponse(response=response,response_id=str(uuid.uuid4()))


@app.post("/v1/list_jobs",dependencies=[Depends(check_api_key)])
async def handel_list_jobs(request:ListJobsRequest):
    logger.info(request.json())
    resp = await list_jobs(request)
    return resp

@app.post("/v1/get_factory_config",dependencies=[Depends(check_api_key)])
async def get_llama_factory_config(request:GetFactoryConfigRequest):
    # 中国区从modelscope下载模型
    repo = DownloadSource.MODELSCOPE if DEFAULT_REGION.startswith('cn') else DownloadSource.DEFAULT
    resp = await get_factory_config(request,repo)
    return resp

@app.post("/v1/get_job",dependencies=[Depends(check_api_key)])
async def get_job(request:GetJobsRequest):
    resp = await get_job_by_id(request)
    return resp

@app.post("/v1/delete_job",dependencies=[Depends(check_api_key)])
async def delete_job(request:DelJobsRequest):
    resp = await delete_job_by_id(request)
    return resp


@app.post("/v1/create_job",dependencies=[Depends(check_api_key)])
async def handle_create_job(request: CreateJobsRequest):
    request_timestamp = time.time()  
    logger.info(request.json())
    job_detail = await create_job(request)
    if job_detail:
        body = {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': job_detail
        }
        return CommonResponse(response=body,response_id=str(uuid.uuid4()))
    else:
        body = {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': 'create job failed'
        }
        return CommonResponse(response=body,response_id=str(uuid.uuid4()))
    
@app.post("/v1/fetch_training_log",dependencies=[Depends(check_api_key)])
async def handle_fetch_training_log(request:FetchLogRequest):
    logger.info(request.json())
    resp = await fetch_training_log(request)
    return resp


@app.post("/v1/get_job_status",dependencies=[Depends(check_api_key)])
async def handle_get_job_status(request:GetJobsRequest):
    # logger.info(request.json())
    job_status = get_job_status(request.job_id)
    resp = JobStatusResponse(response_id=str(uuid.uuid4()), job_status=JobStatus(job_status))
    return resp

@app.post("/v1/list_s3_path",dependencies=[Depends(check_api_key)])
async def handle_list_s3_path(request:ListS3ObjectsRequest):
    ret = list_s3_objects(request.output_s3_path)
    return S3ObjectsResponse(response_id=str(uuid.uuid4()),objects=ret)
    
@app.post('/v1/deploy_endpoint',dependencies=[Depends(check_api_key)])
async def handle_deploy_endpoint(request:DeployModelRequest):
    logger.info(request)
    #engine不是'auto','vllm'，则使用lmi
    if request.engine in ['auto','vllm','sglang'] :
        try:
            ret,msg =  await asyncio.wait_for(
                asyncio.to_thread(deploy_endpoint_byoc,
                                job_id=request.job_id,
                                engine=request.engine,
                                instance_type=request.instance_type,
                                quantize=request.quantize,
                                enable_lora=request.enable_lora,
                                cust_repo_type=request.cust_repo_type,
                                cust_repo_addr=request.cust_repo_addr,
                                model_name=request.model_name,
                                extra_params=request.extra_params
                                ),
                                timeout=10)
            return CommonResponse(response_id=str(uuid.uuid4()),response={"result":ret, "endpoint_name": msg})
        except asyncio.TimeoutError:
            return CommonResponse(response_id=str(uuid.uuid4()),response={"result":True, "endpoint_name": "Too long,swithing to background process"}) 
    else:
        try:
            ret,msg =  await asyncio.wait_for(
                asyncio.to_thread(deploy_endpoint,
                                job_id=request.job_id,
                                engine=request.engine,
                                instance_type=request.instance_type,
                                quantize=request.quantize,
                                enable_lora=request.enable_lora,
                                cust_repo_type=request.cust_repo_type,
                                cust_repo_addr=request.cust_repo_addr,
                                model_name=request.model_name,
                                extra_params=request.extra_params
                                ),
                                timeout=600)
            return CommonResponse(response_id=str(uuid.uuid4()),response={"result":ret, "endpoint_name": msg})
        except asyncio.TimeoutError:
            return CommonResponse(response_id=str(uuid.uuid4()),response={"result":False, "endpoint_name": "Operation timed out"}) 
    

@app.post('/v1/delete_endpoint',dependencies=[Depends(check_api_key)])
async def handle_delete_endpoint(request:EndpointRequest):
    logger.info(request)
    endpoint_name = request.endpoint_name
    result = delete_endpoint(endpoint_name)
    return CommonResponse(response_id=str(uuid.uuid4()),response={"result": result})

@app.post('/v1/get_endpoint_status',dependencies=[Depends(check_api_key)])
async def handle_get_endpoint_status(request:EndpointRequest):
    logger.info(request)
    status = get_endpoint_status(endpoint_name=request.endpoint_name)
    return CommonResponse(response_id=str(uuid.uuid4()),response={"status": status.value})

@app.post('/v1/list_endpoints',dependencies=[Depends(check_api_key)])
async def handle_list_endpoints(request:ListEndpointsRequest):
    # logger.info(request)
    endpoints,count = list_endpoints(request)
    return ListEndpointsResponse(response_id=str(uuid.uuid4()),endpoints=endpoints,total_count=count)
    
    
def stream_generator(inference_request:InferenceRequest) -> AsyncIterable[bytes]:
    id = inference_request.id if inference_request.id else str(uuid.uuid4())
    logger.info('--stream_generator---')
    response_stream = inference(inference_request.endpoint_name, inference_request.model_name, 
                                      inference_request.messages, inference_request.params, True)
    for chunk in response_stream:
        yield f"data: {chunk}\n\n"
    yield f"data: [DONE]\n\n"
    
def stream_generator_byoc(inference_request:InferenceRequest) -> AsyncIterable[bytes]:
    id = inference_request.id if inference_request.id else str(uuid.uuid4())
    logger.info('--stream_generator_byoc---')
    response_stream = inference_byoc(inference_request.endpoint_name, inference_request.model_name, 
                                      inference_request.messages, inference_request.params, True)
    for chunk in response_stream:
        yield chunk
    
@app.post('/v1/chat/completions',dependencies=[Depends(check_api_key)])
async def handle_inference(request:InferenceRequest):
    # logger.info(request)
    engine = get_endpoint_engine(request.endpoint_name)
    # logger.info(f"engine:{engine}")
    #engine不是'auto','vllm'，则使用lmi
    if  engine in ['auto','vllm','sglang'] :
        if not request.stream:
            response = inference_byoc(request.endpoint_name,request.model_name,request.messages,request.params,False)
            id = request.id if request.id else str(uuid.uuid4())
            return CommonResponse(response_id=id,response=response)
        else:
            return StreamingResponse(stream_generator_byoc(request), media_type="text/event-stream")
    else:

        if not request.stream:
            response = inference(request.endpoint_name,request.model_name,request.messages,request.params,False)
            id = request.id if request.id else str(uuid.uuid4())
            return CommonResponse(response_id=id,response=response)
        else:
            return StreamingResponse(stream_generator(request), media_type="text/event-stream")


def create_price_api_server():
    global app_settings
    parser = argparse.ArgumentParser(
        description="Chat RESTful API server."
    )
    parser.add_argument("--host", type=str, default="0.0.0.0", help="host name")
    parser.add_argument("--port", type=int, default=8000, help="port number")
    parser.add_argument(
        "--allow-credentials", action="store_true", help="allow credentials"
    )
    parser.add_argument(
        "--allowed-origins", type=json.loads, default=["*"], help="allowed origins"
    )
    parser.add_argument(
        "--allowed-methods", type=json.loads, default=["*"], help="allowed methods"
    )
    parser.add_argument(
        "--allowed-headers", type=json.loads, default=["*"], help="allowed headers"
    )
    parser.add_argument(
        "--ssl",
        action="store_true",
        required=False,
        default=False,
        help="Enable SSL. Requires OS Environment variables 'SSL_KEYFILE' and 'SSL_CERTFILE'.",
    )
    args = parser.parse_args()

    
    return args

if __name__ == "__main__":
    logger.info('server start')
    args = create_price_api_server()
    logger.info(f"{args}")
    if args.ssl:
        uvicorn.run(
            "server:app",
            host=args.host,
            port=args.port,
            log_level="info",
            ssl_keyfile=os.environ["SSL_KEYFILE"],
            ssl_certfile=os.environ["SSL_CERTFILE"],
        )
    else:
        uvicorn.run("server:app", host=args.host, port=args.port, log_level="info",reload=True,workers=1)
