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
logger = setup_logger('main.py', level=logging.INFO)

database = DatabaseWrapper()

def get_submitted_jobs():
    results = database.get_jobs_by_status(JobStatus.SUBMITTED)
    return [ret[0] for ret in results]

def proccessing_job(job_id:str):
    logger.info(f"creating job:{job_id}")
    job = JobStateMachine.create(job_id)

    try:
        # Phase 1: Creating
        if not job.transition(JobStatus.CREATING):
            error_msg = f"CREATING job failed for {job_id}"
            if not job.error_message:
                job.error_message = error_msg
            logger.error(f"{error_msg}. Error: {job.error_message}")
            job.transition(JobStatus.ERROR)
            return

        # Phase 2: Running
        logger.info(f"running job:{job_id}")
        if not job.transition(JobStatus.RUNNING):
            error_msg = f"RUNNING job failed for {job_id}"
            if not job.error_message:
                job.error_message = error_msg
            logger.error(f"{error_msg}. Error: {job.error_message}")
            job.transition(JobStatus.ERROR)
            return

        # Phase 3: Check final status
        job_status = get_job_status(job_id)
        logger.info(f"finish running job:{job_id} with status:{job_status}")
        job.transition(job_status)

    except Exception as e:
        # Capture detailed error information
        import traceback
        error_detail = (
            f"Unexpected error in processing job {job_id}:\n"
            f"Error Type: {type(e).__name__}\n"
            f"Error Message: {str(e)}\n\n"
            f"Full Traceback:\n{traceback.format_exc()}"
        )
        job.error_message = error_detail
        logger.error(f"RUNNING job failed: {error_detail}")

        # Try to save error to database
        try:
            job.transition(JobStatus.ERROR)
        except Exception as db_error:
            logger.error(f"Failed to save error status to database: {db_error}")

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
