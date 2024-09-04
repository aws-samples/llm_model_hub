import sys
from typing import Annotated, Sequence, TypedDict, Dict, Optional,List, Any,TypedDict,Literal
from enum import Enum
from datetime import datetime
from pydantic import BaseModel,Field


sys.path.append('./')

#create an enum for job_type, with [sft,pt]

class JobType(Enum):
    sft = 'sft'
    pt = 'pt'
    ppo = 'ppo'
    dpo = 'dpo'
    kto = 'kto'
    rm = 'rm'

class EndpointStatus(Enum):
    CREATING = "CREATING"
    INSERVICE = "INSERVICE"
    FAILED = "FAILED"
    DELETING = "DELETING"
    TERMINATED = "TERMINATED"
    NOTFOUND = 'NOTFOUND'

class JobStatus(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    CREATING = "CREATING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    TERMINATED = "TERMINATED"
    TERMINATING = "TERMINATING"
    STOPPED = "STOPPED"
    
class FetchLogRequest(BaseModel):
    # job_run_name:str
    job_id:str
    next_token:Optional[str] = None
    
class FetchLogResponse(BaseModel):
    response_id:str
    log_events:List[str]
    next_backward_token:Optional[str] = None
    next_forward_token:Optional[str] = None
    
class CreateJobsRequest(BaseModel):
    request_id:Optional[str]
    # job_type : Literal["sft","pt"] = Field(default="sft")
    job_type : JobType  = Field(default=JobType.sft)
    job_name: str
    job_payload: Dict[str,Any]
    
class JobInfo(BaseModel):
    job_id:str
    job_name: str
    job_run_name:str
    output_s3_path: str
    job_type : JobType 
    job_status : JobStatus 
    job_payload : Dict[str,Any]
    job_create_time: Optional[datetime] = None 
    job_start_time:Optional[datetime] = None
    job_end_time:Optional[datetime] = None 
    ts:int

class JobStatusResponse(BaseModel):
    response_id:str
    job_status:JobStatus
    
class ListJobsRequest(BaseModel):
    page_size : int = 20
    page_index : Optional[int] = Field(default=1)
    query_terms : Optional[Dict[str,Any]] =  Field(default=None)
    
class GetJobsRequest(BaseModel):
    job_id:str
    
class DelJobsRequest(BaseModel):
    job_id:str

class JobsResponse(BaseModel):
    response_id:str
    body:JobInfo

class ListJobsResponse(BaseModel):
    response_id:str
    jobs :List[JobInfo]
    total_count:int
    
class CommonResponse(BaseModel):
    response_id:str
    response:Dict[str,Any]
    
class GetFactoryConfigRequest(BaseModel):
    config_name:Literal["model_name","prompt_template","dataset"] 
    
class ListModelNamesResponse(BaseModel):
    response_id:str
    model_names:List[str]
    
class ListS3ObjectsRequest(BaseModel):
    output_s3_path:str
    
class S3ObjectsResponse(BaseModel):
    response_id:str
    objects:List[Dict[str,Any]]
    
class DeployModelRequest(BaseModel):
    job_id:str
    model_name:Optional[str] = ''
    engine:Literal["vllm","scheduler","auto","lmi-dist","trt-llm"]
    instance_type:str
    quantize:Optional[str] = ''
    enable_lora:Optional[bool] = False
    cust_repo_type:Optional[str] = ''
    cust_repo_addr:Optional[str] = ''
    
class EndpointRequest(BaseModel):
    endpoint_name:str


class ListEndpointsRequest(BaseModel):
    page_size : int = 20
    page_index : Optional[int] = Field(default=1)
    query_terms : Optional[Dict[str,Any]] =  Field(default=None)

class EndpointInfo(BaseModel):
    job_id:str
    endpoint_name:str
    model_name:str
    engine:str
    enable_lora:bool
    instance_type:str
    instance_count:int
    model_s3_path:str
    endpoint_status:EndpointStatus
    endpoint_create_time: Optional[datetime] = None
    endpoint_delete_time:Optional[datetime] = None
    extra_config:Optional[str]= None
    
    
class ListEndpointsResponse(BaseModel):
    response_id:str
    endpoints :List[EndpointInfo]
    total_count:int
    
class InferenceRequest(BaseModel):
    endpoint_name:str
    model_name:str
    id:Optional[str] = None
    messages:List[Dict[str,Any]]
    params:Dict[str,Any]
    stream: Optional[bool]= False
    mode: Optional[Literal["webui","api"]] = "webui"
    
class LoginRequest(BaseModel):
    username:str
    password:str
