import time
import uuid
import sys
sys.path.append('./')
import json
import logging
import os
from typing import Annotated, Sequence, TypedDict, Dict, Optional,List, Any,TypedDict
import dotenv
dotenv.load_dotenv('.env')
# assert dotenv.load_dotenv('.env') 
# print(os.environ)
# from backend.model.data_model import CommonResponse,CreateJobsRequest, \
# ListJobsRequest,JobInfo,JobType,ListJobsResponse,GetJobsRequest, \
# JobsResponse,JobStatus,DelJobsRequest
from model.data_model import *
from job_state_machine import JobStateMachine

from db_management.database import DatabaseWrapper
import threading
from logger_config import setup_logger
from training.jobs import get_job_status
logger = setup_logger('main.py', log_file='processing_engine.log', level=logging.INFO)

database = DatabaseWrapper()

def get_submitted_jobs():
    results = database.get_jobs_by_status(JobStatus.SUBMITTED)
    return [ret[0] for ret in results]

def proccessing_job(job_id:str):    
    logger.info(f"creating job:{job_id}")
    job = JobStateMachine.create(job_id)

    if not job.transition(JobStatus.CREATING):
        job.transition(JobStatus.ERROR)
        logger.info(f"CREATING job failed:{job_id}")
        return 
    
    logger.info(f"running job:{job_id}")
    if not job.transition(JobStatus.RUNNING):
        job.transition(JobStatus.ERROR)
        logger.info(f"RUNNING job failed:{job_id}")
        return 

    job_status = get_job_status(job_id)
    logger.info(f"finish running job:{job_id} with status:{job_status}")
    job.transition(job_status)
    # job.transition(JobStatus.SUCCESS)
    return True

def start_processing_engine():
    logger.info("start processing engine...")
    processing_threads = {}
    while True:
        results = get_submitted_jobs()
        if results:
            logger.info(f"scan job list:{results}")
        if results:
            for job_id in results:
                if job_id not in processing_threads:
                    thread = threading.Thread(target=proccessing_job,args=(job_id,))
                    thread.start()
                    processing_threads[job_id]=thread
        time.sleep(10)# 每10s扫描一次
        
if __name__ == '__main__':
    start_processing_engine()
