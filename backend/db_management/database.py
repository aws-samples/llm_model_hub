import mysql.connector
from mysql.connector import pooling
from typing import Annotated, Sequence, TypedDict, Dict, Optional, List, Any, Literal
import json
import sys
import os
sys.path.append('./')
from pydantic import BaseModel
from model.data_model import JobInfo, JobStatus, EndpointStatus, ClusterInfo, ClusterStatus
from utils.config import MYSQL_CONFIG, JOB_TABLE, EP_TABLE, USER_TABLE

# Cluster table name
CLUSTER_TABLE = 'CLUSTER_TABLE'
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
                        f"INSERT INTO {JOB_TABLE} (job_id, job_name, job_run_name, output_s3_path, job_type, job_status, job_create_time, job_start_time, job_end_time, job_payload, ts, error_message) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
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
                         job_detail.ts,
                         job_detail.error_message)  # Add error_message field
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

    def update_job_error(self, job_id: str, error_message: str, status: JobStatus = JobStatus.ERROR):
        """
        Update job with error message and set status to ERROR

        Args:
            job_id: Job ID
            error_message: Detailed error message
            status: Job status (default: ERROR)
        """
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {JOB_TABLE} SET job_status = %s, error_message = %s, job_end_time = %s WHERE job_id = %s",
                    (status.value, error_message, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), job_id)
                )
                connection.commit()

    def get_job_error(self, job_id: str) -> Optional[str]:
        """
        Get error message for a job

        Args:
            job_id: Job ID

        Returns:
            Error message string or None if no error
        """
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT error_message FROM {JOB_TABLE} WHERE job_id = %s", (job_id,))
                result = cursor.fetchone()
                return result[0] if result and result[0] else None
                
    def update_endpoint_status(self,
                               endpoint_name:str,
                               endpoint_status:EndpointStatus,
                               extra_config:str = None,
                               endpoint_delete_time:str = None,
                              ):
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                # Only update extra_config if it's explicitly provided (not None)
                # This prevents overwriting existing extra_config when just updating status
                if extra_config is not None:
                    cursor.execute(f"UPDATE {EP_TABLE} SET endpoint_status = %s, endpoint_delete_time = %s, extra_config = %s WHERE endpoint_name = %s",
                                   (endpoint_status.value, endpoint_delete_time, extra_config, endpoint_name))
                else:
                    cursor.execute(f"UPDATE {EP_TABLE} SET endpoint_status = %s, endpoint_delete_time = %s WHERE endpoint_name = %s",
                                   (endpoint_status.value, endpoint_delete_time, endpoint_name))
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
                               endpoint_status:EndpointStatus,
                               deployment_target:str = 'sagemaker',
                               hyperpod_cluster_id:str = None):
        ret = True
        try:
            with self.connection_pool.get_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO {EP_TABLE} (job_id, endpoint_name, model_name, engine, enable_lora, instance_type, instance_count, model_s3_path, endpoint_status, endpoint_create_time, endpoint_delete_time, extra_config, deployment_target, hyperpod_cluster_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (job_id, endpoint_name, model_name, engine, enable_lora, instance_type, instance_count, model_s3_path, endpoint_status.value, endpoint_create_time, endpoint_delete_time,
                         json.dumps(extra_config, ensure_ascii=False) if extra_config else None,
                         deployment_target,
                         hyperpod_cluster_id
                         )
                    )
                    connection.commit()
        except Exception as e:
            print(f"Error saving endpoint: {e}")
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

    def get_endpoint_full(self, endpoint_name:str):
        """Get full endpoint details including deployment_target and hyperpod_cluster_id."""
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT * FROM {EP_TABLE} WHERE endpoint_name = %s",(endpoint_name,))
                return cursor.fetchone()

    def get_hyperpod_endpoints_creating(self):
        """Get all HyperPod endpoints in CREATING status for background monitoring."""
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT endpoint_name, hyperpod_cluster_id, extra_config FROM {EP_TABLE} WHERE deployment_target = 'hyperpod' AND endpoint_status = 'CREATING'"
                )
                return cursor.fetchall()

    def count_hyperpod_endpoints_by_cluster_and_instance(self, hyperpod_cluster_id: str, instance_type: str) -> int:
        """
        Count active HyperPod endpoints for a given cluster and instance type.

        Returns the count of endpoints that are not FAILED or DELETED.
        """
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) FROM {EP_TABLE} WHERE hyperpod_cluster_id = %s AND instance_type = %s AND endpoint_status NOT IN ('FAILED', 'NOTFOUND')",
                    (hyperpod_cluster_id, instance_type)
                )
                result = cursor.fetchone()
                return result[0] if result else 0

    def get_hyperpod_endpoints_by_cluster(self, hyperpod_cluster_id: str) -> list:
        """
        Get all active HyperPod endpoints for a given cluster.

        Returns list of (endpoint_name, instance_type, endpoint_status) tuples.
        """
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT endpoint_name, instance_type, endpoint_status FROM {EP_TABLE} WHERE hyperpod_cluster_id = %s AND endpoint_status NOT IN ('FAILED', 'NOTFOUND')",
                    (hyperpod_cluster_id,)
                )
                return cursor.fetchall()

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

    # ==================== Cluster Operations ====================

    def save_cluster(self, cluster_detail: ClusterInfo) -> bool:
        """Save a new cluster record."""
        ret = True
        try:
            with self.connection_pool.get_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""INSERT INTO {CLUSTER_TABLE}
                        (cluster_id, cluster_name, eks_cluster_name, eks_cluster_arn, hyperpod_cluster_arn,
                         cluster_status, vpc_id, subnet_ids, instance_groups, cluster_create_time,
                         cluster_update_time, error_message, cluster_config, ts)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (cluster_detail.cluster_id,
                         cluster_detail.cluster_name,
                         cluster_detail.eks_cluster_name,
                         cluster_detail.eks_cluster_arn,
                         cluster_detail.hyperpod_cluster_arn,
                         cluster_detail.cluster_status.value,
                         cluster_detail.vpc_id,
                         json.dumps(cluster_detail.subnet_ids) if cluster_detail.subnet_ids else None,
                         json.dumps(cluster_detail.instance_groups) if cluster_detail.instance_groups else None,
                         cluster_detail.cluster_create_time,
                         cluster_detail.cluster_update_time,
                         cluster_detail.error_message,
                         json.dumps(cluster_detail.cluster_config, ensure_ascii=False) if cluster_detail.cluster_config else None,
                         cluster_detail.ts)
                    )
                    connection.commit()
        except Exception as e:
            print(f"Error saving cluster: {e}")
            ret = False
        return ret

    def get_cluster_by_id(self, cluster_id: str) -> Optional[ClusterInfo]:
        """Get cluster by ID."""
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT * FROM {CLUSTER_TABLE} WHERE cluster_id = %s", (cluster_id,))
                row = cursor.fetchone()
                if row:
                    return self._row_to_cluster_info(row)
                return None

    def _row_to_cluster_info(self, row) -> ClusterInfo:
        """Convert database row to ClusterInfo object."""
        # Parse cluster_config first to check for instance_groups
        cluster_config = json.loads(row[12]) if row[12] else None
        # Prefer instance_groups from cluster_config (more up-to-date) over the column
        instance_groups_from_column = json.loads(row[8]) if row[8] else None
        instance_groups_from_config = cluster_config.get('instance_groups') if cluster_config else None
        instance_groups = instance_groups_from_config or instance_groups_from_column

        return ClusterInfo(
            cluster_id=row[0],
            cluster_name=row[1],
            eks_cluster_name=row[2],
            eks_cluster_arn=row[3],
            hyperpod_cluster_arn=row[4],
            cluster_status=ClusterStatus(row[5]),
            vpc_id=row[6],
            subnet_ids=json.loads(row[7]) if row[7] else None,
            instance_groups=instance_groups,
            cluster_create_time=row[9],
            cluster_update_time=row[10],
            error_message=row[11],
            cluster_config=cluster_config,
            ts=row[13]
        )

    def list_clusters(self, query_terms: Dict[str, Any] = None, page_size: int = 20, page_index: int = 1):
        """List clusters with pagination."""
        offset = (page_index - 1) * page_size
        clusters = []
        total_count = 0

        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                # Get total count
                cursor.execute(f"SELECT COUNT(*) FROM {CLUSTER_TABLE} WHERE cluster_status <> 'DELETED'")
                total_count = cursor.fetchone()[0]

                # Get clusters
                if query_terms:
                    query_string = f"SELECT * FROM {CLUSTER_TABLE} WHERE cluster_status <> 'DELETED' AND "
                    query_params = []
                    for key, value in query_terms.items():
                        query_string += f"{key} = %s AND "
                        query_params.append(value)
                    query_string = query_string[:-4] + " ORDER BY ts DESC LIMIT %s OFFSET %s"
                    query_params.extend([page_size, offset])
                    cursor.execute(query_string, tuple(query_params))
                else:
                    cursor.execute(
                        f"SELECT * FROM {CLUSTER_TABLE} WHERE cluster_status <> 'DELETED' ORDER BY ts DESC LIMIT %s OFFSET %s",
                        (page_size, offset)
                    )

                rows = cursor.fetchall()
                for row in rows:
                    clusters.append(self._row_to_cluster_info(row))

        return clusters, total_count

    def set_cluster_status(self, cluster_id: str, status: ClusterStatus):
        """Update cluster status."""
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {CLUSTER_TABLE} SET cluster_status = %s, cluster_update_time = %s WHERE cluster_id = %s",
                    (status.value, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), cluster_id)
                )
                connection.commit()

    def update_cluster_error(self, cluster_id: str, error_message: str):
        """Update cluster with error message and set status to FAILED."""
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {CLUSTER_TABLE} SET error_message = %s, cluster_status = %s, cluster_update_time = %s WHERE cluster_id = %s",
                    (error_message, ClusterStatus.FAILED.value, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), cluster_id)
                )
                connection.commit()

    def clear_cluster_error(self, cluster_id: str):
        """Clear cluster error message without changing status."""
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {CLUSTER_TABLE} SET error_message = NULL, cluster_update_time = %s WHERE cluster_id = %s",
                    (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), cluster_id)
                )
                connection.commit()

    def set_cluster_error_message(self, cluster_id: str, error_message: str):
        """Set cluster error message without changing status."""
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {CLUSTER_TABLE} SET error_message = %s, cluster_update_time = %s WHERE cluster_id = %s",
                    (error_message, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), cluster_id)
                )
                connection.commit()

    def update_cluster_config(self, cluster_id: str, cluster_config: Dict[str, Any]):
        """Update cluster configuration."""
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {CLUSTER_TABLE} SET cluster_config = %s, cluster_update_time = %s WHERE cluster_id = %s",
                    (json.dumps(cluster_config, ensure_ascii=False), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), cluster_id)
                )
                connection.commit()

    def update_cluster_instance_groups(self, cluster_id: str, instance_groups: List[Dict[str, Any]]):
        """Update cluster instance groups column."""
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {CLUSTER_TABLE} SET instance_groups = %s, cluster_update_time = %s WHERE cluster_id = %s",
                    (json.dumps(instance_groups) if instance_groups else None, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), cluster_id)
                )
                connection.commit()

    def update_cluster_arns(self, cluster_id: str, eks_cluster_arn: str = None, hyperpod_cluster_arn: str = None):
        """Update cluster ARNs."""
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                updates = []
                params = []
                if eks_cluster_arn:
                    updates.append("eks_cluster_arn = %s")
                    params.append(eks_cluster_arn)
                if hyperpod_cluster_arn:
                    updates.append("hyperpod_cluster_arn = %s")
                    params.append(hyperpod_cluster_arn)

                if updates:
                    updates.append("cluster_update_time = %s")
                    params.append(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                    params.append(cluster_id)

                    query = f"UPDATE {CLUSTER_TABLE} SET {', '.join(updates)} WHERE cluster_id = %s"
                    cursor.execute(query, tuple(params))
                    connection.commit()

    def get_clusters_by_status(self, status: ClusterStatus):
        """Get clusters by status."""
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT cluster_id FROM {CLUSTER_TABLE} WHERE cluster_status = %s", (status.value,))
                return cursor.fetchall()

    def delete_cluster_by_id(self, cluster_id: str) -> bool:
        """Delete cluster record (soft delete by setting status to DELETED)."""
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {CLUSTER_TABLE} SET cluster_status = %s, cluster_update_time = %s WHERE cluster_id = %s",
                    (ClusterStatus.DELETED.value, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), cluster_id)
                )
                connection.commit()
                return True

    def update_cluster_vpc_info(self, cluster_id: str, vpc_id: str, subnet_ids: List[str], security_group_ids: Optional[List[str]] = None):
        """Update cluster VPC information."""
        with self.connection_pool.get_connection() as connection:
            with connection.cursor() as cursor:
                # Also update cluster_config with security_group_ids
                if security_group_ids:
                    cursor.execute(f"SELECT cluster_config FROM {CLUSTER_TABLE} WHERE cluster_id = %s", (cluster_id,))
                    row = cursor.fetchone()
                    config = json.loads(row[0]) if row and row[0] else {}
                    config['security_group_ids'] = security_group_ids
                    cursor.execute(
                        f"UPDATE {CLUSTER_TABLE} SET vpc_id = %s, subnet_ids = %s, cluster_config = %s, cluster_update_time = %s WHERE cluster_id = %s",
                        (vpc_id, json.dumps(subnet_ids), json.dumps(config, ensure_ascii=False), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), cluster_id)
                    )
                else:
                    cursor.execute(
                        f"UPDATE {CLUSTER_TABLE} SET vpc_id = %s, subnet_ids = %s, cluster_update_time = %s WHERE cluster_id = %s",
                        (vpc_id, json.dumps(subnet_ids), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), cluster_id)
                    )
                connection.commit()

    def close(self):
        self.connection_pool.close()
