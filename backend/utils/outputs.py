import boto3
from botocore.exceptions import ClientError
from datetime import timedelta, timezone
import re
import dotenv
import os
from .config import boto_sess
dotenv.load_dotenv()

def list_s3_objects(s3_url:str):

    # Parse the S3 URL
    match = re.match(r's3://([^/]+)/?(.*)$', s3_url)
    if not match:
        raise ValueError("Invalid S3 URL format")
    
    bucket_name = match.group(1)
    prefix = match.group(2)

    # Initialize S3 client
    # boto_sess = boto3.Session(
    #     profile_name=os.environ.get('profile'),
    #     region_name=os.environ.get('region')
    # )

    s3_client = boto_sess.client('s3')

    result = []
    paginator = s3_client.get_paginator('list_objects_v2')
    tz_offset = timezone(timedelta(hours=8))
    try:
        for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix, Delimiter='/'):
            # Handle folders
            for common_prefix in page.get('CommonPrefixes', []):
                folder_name = common_prefix['Prefix'].rstrip('/').split('/')[-1].replace('s3://', '')
                result.append({
                    "Key": folder_name+'/',
                    "IsFolder": True
                })
            
            # Handle files
            for obj in page.get('Contents', []):
                # Skip the prefix itself if it's returned as an object
                if obj['Key'] == prefix:
                    continue
                
                file_name = obj['Key'].split('/')[-1].replace('s3://', '')
                result.append({
                    "Key": file_name,
                    "LastModified": obj['LastModified'].astimezone(tz_offset).strftime("%B %d, %Y, %H:%M:%S (UTC+08:00)"),
                    "Size": obj['Size'],
                    "IsFolder": False
                })
    
    except ClientError as e:
        print(f"An error occurred: {e}")
        return []

    return result

if __name__ == '__main__':
    path = 's3://sagemaker-us-west-2-434444145045/Meta-Llama-3-8B-Instruct/'
    print(list_s3_objects(path))