import sys
sys.path.append('./')
import logging
import json
from typing import Annotated, Sequence, TypedDict, Dict, Optional,List, Any,TypedDict
import threading
from datetime import datetime
import boto3 
import os
from utils.config import DATASET_INFO_FILE



# from logger_config import setup_logger

# logger = setup_logger('helper.py', log_file='training_helper.log', level=logging.INFO)
file_lock = threading.Lock()
def prepare_dataset_info(data_info:Dict[str,Any]):
    file_name = DATASET_INFO_FILE   
    with file_lock:
        try:
            with open(file_name, 'r') as f:
                datainfo = json.load(f)
            for key in list(data_info.keys()):
                datainfo[key] = data_info[key]
            with open(file_name, 'w') as f:
                json.dump(datainfo, f)
            # logger.info('Successfully saved dataset_info.json')
        except Exception as e:
            print(f'Error in prepare_dataset_info: {str(e)}')
            

def to_datetime_string(unix_timestamp, format_string="%Y-%m-%d %H:%M:%S.%f"):
    # Convert Unix timestamp to datetime object
    dt_object = datetime.fromtimestamp(unix_timestamp)
    
    return dt_object.strftime(format_string)

# list all s3 objects from given s3 path
def list_s3_objects(s3_url:str) -> List[str]:
    if not s3_url:
        return []
    boto_sess = boto3.Session(
        profile_name=os.environ.get('profile','default'),
        region_name=os.environ.get('region')
    )
    try:
        s3 = boto_sess.client('s3')
        bucket, prefix = s3_url.replace("s3://", "").split("/", 1)
        response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
        objects = response.get("Contents", [])
        return [obj['Key'].split("/")[-1] for obj in objects]
    except Exception as e:
        print(f'Error in list_s3_objects: {str(e)}')
        raise e

import re

def is_valid_s3_uri(uri):
    """
    Validate if the given URI is a valid S3 URI.
    
    Args:
    uri (str): The URI to validate.
    
    Returns:
    bool: True if the URI is a valid S3 URI, False otherwise.
    """
    # Regular expression pattern for S3 URI
    s3_uri_pattern = r'^s3://([^/]+)(/.*)?$'
    
    # Check if the URI matches the pattern
    match = re.match(s3_uri_pattern, uri)
    
    if match:
        bucket_name = match.group(1)
        
        # Additional checks for bucket name validity
        if len(bucket_name) < 3 or len(bucket_name) > 63:
            return False
        
        if not bucket_name[0].isalnum():
            return False
        
        if not all(c.isalnum() or c in '-.' for c in bucket_name):
            return False
        
        if '..' in bucket_name:
            return False
        
        if bucket_name.endswith('-') or bucket_name.startswith('-'):
            return False
        
        if bucket_name.lower().startswith('xn--'):
            return False
        
        return True
    
    return False

if __name__ == "__main__":
#    print(list_s3_objects('s3://sagemaker-us-west-2-434444145045/dataset-for-training/train/'))
    # Test the function
    print(is_valid_s3_uri("s3://sagemaker-us-west-2-434444145045/dataset-for-training/train/"))  # True
    print(is_valid_s3_uri("s3://my-bucket"))  # True
    print(is_valid_s3_uri("s3://My-Bucket"))  # False (uppercase not allowed)
    print(is_valid_s3_uri("s3://my_bucket"))  # False (underscore not allowed)
    print(is_valid_s3_uri("https://my-bucket.s3.amazonaws.com"))  # False (not s3:// protocol)
    print(is_valid_s3_uri("s3://a"))  # False (bucket name too short)
   
   