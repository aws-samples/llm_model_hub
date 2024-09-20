import mysql.connector
from mysql.connector import pooling
from typing import Annotated, Sequence, TypedDict, Dict, Optional, List, Any, Literal
import json
import sys
import os
sys.path.append('./')
from pydantic import BaseModel
from model.data_model import JobInfo, JobStatus,EndpointStatus
from utils.config import MYSQL_CONFIG,JOB_TABLE,EP_TABLE,USER_TABLE
from datetime import datetime

def singleton(cls):
    instances = {}

    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance

@singleton
class DatabaseWrapper(BaseModel):
    connection_pool: Any = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connection_pool = mysql.connector.pooling.MySQLConnectionPool(pool_name="mypool", pool_size=5, **MYSQL_CONFIG)
    

    def save_job(self, job_detail: JobInfo):
        ret = True
        try:
            with self.connection_pool.get_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO {JOB_TABLE} (job_id, job_name, job_run_name, output_s3_path, job_type, job_status, job_create_time, job_start_time, job_end_time, job_payload, ts) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                        (job_detail.job_id,
                         job_detail.job_name,
                         job_detail.job_run_name,
                         job_detail.output_s3_path,
                         job_detail.job_type.value,
                         job_detail.job_status.value,
                         job_detail.job_create_time,
                         job_detail.job_start_time, 
                         job_detail.job_end_time,
                         json.dumps(job_detail.job_payload, ensure_ascii=False),
                         job_detail.ts)
                    )
                    connection.commit()
        except Exception as e:
            print(f"Error saving job: {e}")
            ret = False
        return ret

    def count_jobs(self, query_terms: Dict[str, Any] = None):
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM {JOB_TABLE}")
                return cursor.fetchone()[0]

    def get_job_by_id(self, id: str):
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT * FROM {JOB_TABLE} WHERE job_id = %s", (id,))
                return cursor.fetchall()

    def update_job_run_name(self, job_id: str, job_run_name: str, output_s3_path: str):
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"UPDATE {JOB_TABLE} SET job_run_name = %s, output_s3_path = %s WHERE job_id = %s", 
                               (job_run_name, output_s3_path, job_id))
                connection.commit()

    def update_job_start_time(self, job_id: str, job_start_time: int):
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"UPDATE {JOB_TABLE} SET job_start_time = %s WHERE job_id = %s", 
                               (job_start_time, job_id))
                connection.commit()

    def update_job_end_time(self, job_id: str, job_end_time: int):
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"UPDATE {JOB_TABLE} SET job_end_time = %s WHERE job_id = %s", 
                               (job_end_time, job_id))
                connection.commit()

    def delete_job_by_id(self, id: str) -> bool:
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:  
                ## 临时修改成job_status判断条件，可以从api删除，方便调试              
                cursor.execute(f"DELETE FROM {JOB_TABLE} WHERE job_id = %s", (id,))
                connection.commit()
                return True

    def list_jobs(self, query_terms: Dict[str, Any] = None, page_size=20, page_index=1):
        offset = (page_index - 1) * page_size
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT * FROM {JOB_TABLE} LIMIT %s OFFSET %s", (page_size, offset))
                return cursor.fetchall()

    def get_jobs_by_status(self, status: JobStatus):
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT job_id FROM {JOB_TABLE} WHERE job_status = %s", (status.value,))
                return cursor.fetchall()

    def get_jobs_status_by_id(self, id: str):
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT job_status,job_run_name FROM {JOB_TABLE} WHERE job_id = %s", (id,))
                return cursor.fetchall()

    def set_job_status(self, job_id: str, status: JobStatus):
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"UPDATE {JOB_TABLE} SET job_status = %s WHERE job_id = %s", 
                               (status.value, job_id))
                connection.commit()
                
    def update_endpoint_status(self,
                               endpoint_name:str,
                               endpoint_status:EndpointStatus,
                               extra_config:str = None,
                               endpoint_delete_time:str = None,
                              ):
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"UPDATE {EP_TABLE} SET endpoint_status = %s,endpoint_delete_time = %s, extra_config = %s WHERE endpoint_name = %s", 
                               (endpoint_status.value,endpoint_delete_time,extra_config,endpoint_name))
                connection.commit()
    def delete_endpoint(self,  endpoint_name:str,) -> bool:
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:  
                cursor.execute(f"DELETE FROM {EP_TABLE} WHERE endpoint_name = %s", (endpoint_name,))
                connection.commit()
                return True

    def create_endpoint(self,  
                        job_id:str,
                                model_name:str,
                               model_s3_path:str,
                               endpoint_name:str,
                               instance_type:str,
                               instance_count:int,
                               endpoint_create_time:str,
                               endpoint_delete_time:str,
                               extra_config:str,
                               engine:str,
                               enable_lora:bool,
                               endpoint_status:EndpointStatus):
        ret = True
        try:
            with self.connection_pool.get_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO {EP_TABLE} (job_id, endpoint_name, model_name, engine,enable_lora, instance_type, instance_count, model_s3_path, endpoint_status, endpoint_create_time, endpoint_delete_time, extra_config) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                        (job_id,endpoint_name,model_name,engine,enable_lora,instance_type,instance_count,model_s3_path,endpoint_status.value,endpoint_create_time,endpoint_delete_time,
                         json.dumps(extra_config, ensure_ascii=False),
                         )
                    )
                    connection.commit()
        except Exception as e:
            print(f"Error saving job: {e}")
            ret = False
        return ret
    
    def list_endpoints(self, query_terms: Dict[str, Any] = None, page_size=20, page_index=1):
        offset = (page_index - 1) * page_size
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                if query_terms:
                    query_string = f"SELECT * FROM {EP_TABLE} WHERE endpoint_status <> 'TERMINATED' AND "
                    query_params = []
                    for key, value in query_terms.items():
                        query_string += f"{key} = %s AND "
                        query_params.append(value)
                    query_string = query_string[:-4]
                    cursor.execute(query_string, tuple(query_params))
                else:
                    cursor.execute(f"SELECT * FROM {EP_TABLE} WHERE endpoint_status <> 'TERMINATED' LIMIT %s OFFSET %s", (page_size, offset))
                return cursor.fetchall()
            
    def count_endpoints(self, query_terms: Dict[str, Any] = None):
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM {EP_TABLE}")
                return cursor.fetchone()[0]
    
    def get_endpoint(self, endpoint_name:str):
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT engine FROM {EP_TABLE} WHERE endpoint_name = %s",(endpoint_name,))
                return cursor.fetchone()
                
    def query_users(self, username:str):
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT userpwd, groupname FROM {USER_TABLE} WHERE username = %s",(username,))
                return cursor.fetchone()
            
    def delete_user(self, username:str):
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM {USER_TABLE} WHERE username = %s",(username,))
                connection.commit()
            
    def add_user(self, username:str,password:str,groupname:str,extra_config = {"create_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')}):
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                        f"INSERT INTO {USER_TABLE} (username, userpwd,groupname, extra_config ) VALUES (%s, %s, %s,%s )", 
                        (username, password, groupname,json.dumps(extra_config, ensure_ascii=False),)
                    )
                connection.commit()
        
    def close(self):
        self.connection_pool.close()
