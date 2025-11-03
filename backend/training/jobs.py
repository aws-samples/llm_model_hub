import time
import uuid
import sys
sys.path.append('../')
import json
import logging
import asyncio
from typing import Annotated, Sequence, TypedDict, Dict, Optional,List, Any,TypedDict
from utils.config import boto_sess
from model.data_model import CommonResponse,CreateJobsRequest, \
ListJobsRequest,JobInfo,JobType,ListJobsResponse,GetJobsRequest, \
JobsResponse,JobStatus,DelJobsRequest,FetchLogRequest,FetchLogResponse,JobStatusResponse
from training.training_job import fetch_log
from db_management.database import DatabaseWrapper
from datetime import datetime
database = DatabaseWrapper()
sagemaker_client = boto_sess.client('sagemaker')

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sm_status_mapping = {
    'Pending': JobStatus.PENDING,
    'InProgress': JobStatus.RUNNING,
    'Completed': JobStatus.SUCCESS,
    'Failed': JobStatus.ERROR,
    'Stopping': JobStatus.TERMINATING,
    'Stopped': JobStatus.STOPPED
}


class APIException(Exception):
    def __init__(self, message, code: str = None):
        if code:
            super().__init__("[{}] {}".format(code, message))
        else:
            super().__init__(message)


async def create_job(request:CreateJobsRequest) -> JobInfo: 
    job_id = str(uuid.uuid4().hex)
    job_name = request.job_name
    job_type = request.job_type
    job_status = JobStatus.SUBMITTED.value
    job_detail = {'job_name': job_name}
    job_create_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    #format job_create_time to '2024-04-29 08:20:03'

    job_start_time = None
    job_end_time = None
    ts = int(time.time())
    job_detail = JobInfo(job_id=job_id,
                        job_name=job_name,
                        job_run_name = '',
                        output_s3_path = '',
                        job_type=job_type,
                        job_status=job_status,
                        job_create_time=job_create_time,
                        job_start_time=job_start_time,
                        job_end_time=job_end_time,
                        job_payload = request.job_payload,
                        ts=ts)
    ret = job_detail if database.save_job(job_detail) else None
    return ret
    
async def get_job_by_id(request:GetJobsRequest) -> JobsResponse:
    results = database.get_job_by_id(request.job_id)
    # print(f"database.get_job_by_id:{results}")
    job_info=None
    if results:
        # Note: error_message was added via ALTER TABLE, so it's at the end after ts
        _,job_id,job_name,job_run_name,output_s3_path,job_type,job_status,job_create_time,job_start_time,job_end_time,job_payload,ts,error_message = results[0]
        job_info= JobInfo(job_id=job_id,
                        job_name=job_name,
                        job_run_name=job_run_name,
                        output_s3_path=output_s3_path,
                        job_type=job_type,
                        job_status=job_status,
                        job_create_time=job_create_time,
                        job_start_time=job_start_time,
                        job_end_time=job_end_time,
                        job_payload=json.loads(job_payload),
                        error_message=error_message,
                        ts=ts)
        print(job_info.json())
    else:
        raise APIException(f"Job {request.job_id} not found")
    return JobsResponse(response_id=str(uuid.uuid4()), body=job_info)


async def delete_job_by_id(request:DelJobsRequest) -> CommonResponse:
    ret = database.delete_job_by_id(request.job_id)
    return CommonResponse(response_id=str(uuid.uuid4()), response={"code":"SUCCESS" if ret else "FAILED","message":"" if ret else "Job already started"})
 
async def list_jobs(request:ListJobsRequest) ->ListJobsResponse:
    results = database.list_jobs(query_terms=request.query_terms,page_size=request.page_size,page_index=request.page_index)
    count = database.count_jobs(query_terms=request.query_terms)
    # print(f"list_jobs:{results}")
    # Note: error_message was added via ALTER TABLE, so it's at the end after ts
    jobs = [JobInfo(job_id=job_id,
                     job_name=job_name,
                     job_run_name=job_run_name,
                     output_s3_path=output_s3_path,
                        job_type=job_type,
                        job_status=job_status,
                        job_payload=json.loads(job_payload),
                        job_create_time=job_create_time,
                        job_start_time=job_start_time,
                        job_end_time=job_end_time,
                        error_message=error_message,
                        ts=ts
                    )
            for _,job_id,job_name,job_run_name,output_s3_path,job_type,job_status,job_create_time,job_start_time,job_end_time,job_payload,ts,error_message in results]
    return ListJobsResponse(response_id= str(uuid.uuid4()), jobs=jobs,total_count=count)



def sync_get_job_by_id(job_id:str) -> JobInfo:
    results = database.get_job_by_id(job_id)
    job_info=None
    if results:
        # Note: error_message was added via ALTER TABLE, so it's at the end after ts
        _,job_id,job_name,job_run_name,output_s3_path,job_type,job_status,job_create_time,job_start_time,job_end_time,job_payload,ts,error_message = results[0]
        job_info= JobInfo(job_id=job_id,
                        job_name=job_name,
                        job_run_name=job_run_name,
                        output_s3_path=output_s3_path,
                        job_type=job_type,
                        job_status=job_status,
                        job_create_time=job_create_time,
                        job_start_time=job_start_time,
                        job_end_time=job_end_time,
                        job_payload=json.loads(job_payload),
                        error_message=error_message,
                        ts=ts)
    else:
        raise Exception(f"Job {job_id} not found")
    return job_info

def update_job_run_name_by_id(job_id:str,job_run_name:str,output_s3_path:str):
    database.update_job_run_name(job_id,job_run_name,output_s3_path)


def get_sagemaker_training_job_status(job_name):
    try:
        response = sagemaker_client.describe_training_job(TrainingJobName=job_name)
        return response['TrainingJobStatus']
    except Exception as e:
        logger.info(f"Error getting training job status: {str(e)}")
        return None
    
def get_job_status(job_id:str):
    results = database.get_jobs_status_by_id(job_id)
    job_status = None
    if results:
        job_status = JobStatus[results[0][0]]
        logger.info(f"job_status:{job_status}")
        job_name = results[0][1]
        sm_resp = get_sagemaker_training_job_status(job_name)
        sm_status = sm_status_mapping.get(sm_resp)
        logger.info(f"sm_job_status:{sm_status}")
        if sm_status and not sm_status == job_status :
            logger.info(f"set_job_status:{sm_status}")
            database.set_job_status(job_id,sm_status)
            job_status = sm_status
    else:
        raise Exception(f"Job {job_id} not found")

    return job_status


def stop_sagemaker_training_job(job_name:str):
    """
    Stop a SageMaker training job

    Args:
        job_name: SageMaker training job name

    Returns:
        bool: True if stop request was successful
    """
    try:
        response = sagemaker_client.stop_training_job(TrainingJobName=job_name)
        logger.info(f"Successfully requested stop for training job: {job_name}")
        return True
    except Exception as e:
        logger.error(f"Error stopping training job {job_name}: {str(e)}")
        return False


async def stop_and_delete_job(job_id: str) -> CommonResponse:
    """
    Stop SageMaker training job and delete job record

    Args:
        job_id: Job ID

    Returns:
        CommonResponse with success or error message
    """
    try:
        # Get job information
        job_info = sync_get_job_by_id(job_id)

        # Check if job can be stopped
        if job_info.job_status not in [JobStatus.SUBMITTED, JobStatus.CREATING, JobStatus.RUNNING, JobStatus.PENDING]:
            return CommonResponse(
                response_id=str(uuid.uuid4()),
                response={
                    "code": "FAILED",
                    "message": f"Job cannot be stopped. Current status: {job_info.job_status.value}"
                }
            )

        # Stop SageMaker training job if it exists
        if job_info.job_run_name:
            stop_success = stop_sagemaker_training_job(job_info.job_run_name)
            if not stop_success:
                logger.warning(f"Failed to stop SageMaker job {job_info.job_run_name}, but will continue with deletion")

        # Update job status to TERMINATED
        database.set_job_status(job_id, JobStatus.TERMINATED)
        database.update_job_end_time(job_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

        # Delete job from database
        database.delete_job_by_id(job_id)

        return CommonResponse(
            response_id=str(uuid.uuid4()),
            response={
                "code": "SUCCESS",
                "message": f"Job {job_id} has been stopped and deleted successfully"
            }
        )

    except Exception as e:
        logger.error(f"Error in stop_and_delete_job for {job_id}: {str(e)}")
        return CommonResponse(
            response_id=str(uuid.uuid4()),
            response={
                "code": "FAILED",
                "message": f"Failed to stop and delete job: {str(e)}"
            }
        )


    
async def fetch_training_log(request:FetchLogRequest):
    #get job run name
    job_info = sync_get_job_by_id(request.job_id)
    # print(f"get job run name {job_info}")
    job_run_name = job_info.job_run_name
    if job_run_name :
        logs,next_forward_token,next_backward_token = fetch_log(log_stream_name=job_run_name,next_token=request.next_token)
    else:
        logs,next_forward_token,next_backward_token = ['No logs exists, SageMaker Training Job might not exist'],None,None
    return  FetchLogResponse(response_id= str(uuid.uuid4()), 
                             log_events=logs,
                             next_backward_token=next_backward_token,
                             next_forward_token=next_forward_token)
    
    
if __name__ == '__main__':
    request = CreateJobsRequest(request_id='12231',
        job_type='sft',
        job_name='testmmm',
        job_payload={"model":"llama3","dataset":"ruizhiba"})

    reply = asyncio.run(create_job(request))
    
    request = ListJobsRequest()

    reply = asyncio.run(list_jobs(request))
    print(reply)

