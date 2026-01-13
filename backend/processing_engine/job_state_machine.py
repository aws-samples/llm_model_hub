import time
import uuid
import sys
sys.path.append('./')
import json
import logging
import asyncio
from typing import Annotated, Sequence, TypedDict, Dict, Optional,List, Any,TypedDict

from model.data_model import JobInfo,JobType, JobStatus
from pydantic import BaseModel,Field
from db_management.database import DatabaseWrapper
from logger_config import setup_logger
from training.training_job import TrainingJobExcutor
from datetime import datetime
logger = logging.getLogger()

logger = setup_logger('job_state_machine.py', level=logging.INFO)

dummy_datasetinfo = {'ruozhiba':{
                        'file_name':'ruozhiba.json',
                        "columns": {
                        "prompt": "instruction",
                        "query": "input",
                        "response": "output",
                }   
}}
    
class JobStateMachine(BaseModel):
    job_status: JobStatus = JobStatus.SUBMITTED
    job_id: str = ""
    handlers : Dict[JobStatus,Any] = None
    database : Any = None
    train_job_exe : TrainingJobExcutor = None
    error_message: Optional[str] = None  # Store error message for later use
    
    
    @classmethod
    def create(cls, job_id: str):
        return cls(job_id=job_id,
                   database = DatabaseWrapper(),
                   handlers={
            JobStatus.SUBMITTED: cls.submit_handler,
            JobStatus.RUNNING: cls.run_handler,
            JobStatus.CREATING: cls.creating_handler,
            JobStatus.ERROR: cls.error_handler,
            JobStatus.SUCCESS: cls.success_handler,
            JobStatus.STOPPED: cls.stop_handler,
            JobStatus.PENDING: cls.pending_handler,
            JobStatus.TERMINATED: cls.terminated_handler,
            JobStatus.TERMINATING: cls.terminated_handler            
        })
    
    def submit_handler(self) ->bool:
        logger.info(f"Job {self.job_id} submitted.")
        return True

    def run_handler(self) ->bool:
        logger.info(f"Job {self.job_id} running.")
        self.database.update_job_start_time(self.job_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        if self.train_job_exe is None:
            error_msg = f"Job {self.job_id} has no training job executor."
            logger.error(error_msg)
            self.error_message = error_msg
            return False
        try:
            self.train_job_exe.run()
        except Exception as e:
            import traceback
            error_detail = f"Job {self.job_id} failed to run: {str(e)}"
            logger.error(error_detail)
            self.error_message = error_detail
            return False
        return True

    def success_handler(self) ->bool:
        logger.info(f"Job {self.job_id} success.")
        self.database.update_job_end_time(self.job_id,datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        return True
        
    # create training job
    def creating_handler(self) ->bool:
        logger.info(f"Job {self.job_id} creating.")
        self.train_job_exe = TrainingJobExcutor(job_id=self.job_id)
        ret = self.train_job_exe.create()
        return ret

    def error_handler(self) ->bool:
        logger.info(f"Job {self.job_id} error.")
        # Save error message to database if available
        if self.error_message:
            self.database.update_job_error(self.job_id, self.error_message)
            logger.error(f"Job {self.job_id} error saved to database: {self.error_message[:500]}...")
        else:
            # Fallback if no error message was set
            self.database.update_job_end_time(self.job_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        return True

    def stop_handler(self) ->bool:
        logger.info(f"Job {self.job_id} stopped.")
        self.database.update_job_end_time(self.job_id,datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        return True
        
    def pending_handler(self) ->bool:
        logger.info(f"Job {self.job_id} pending.")
        return True
        
    def terminated_handler(self) ->bool:
        logger.info(f"Job {self.job_id} terminated.")
        self.database.update_job_end_time(self.job_id,datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        return True
        
    def terminating_handler(self) ->bool:
        logger.info(f"Job {self.job_id} terminating.")
        self.database.update_job_end_time(self.job_id,datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        return True
        
        
    def transition(self, new_status: JobStatus, rollback=True):
        old_status = self.job_status
        self.job_status = new_status
        #change status in database
        self.database.set_job_status(self.job_id, new_status)
        ret = self.handlers[new_status](self)
        # rollback to previous status
        if not ret and rollback:
            logger.info('rolling back to previous state')
            self.job_status = old_status
            self.database.set_job_status(self.job_id, old_status)
        return ret
        

        
if __name__ == '__main__':
    job = JobStateMachine.create("job-123")
    job.transition(JobStatus.CREATING)
    # job.transition(JobStatus.SUCCESS)
    # job.transition(JobStatus.TERMINATED)