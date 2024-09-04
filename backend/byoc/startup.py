import re
import json
import os,dotenv
import boto3
import sagemaker

dotenv.load_dotenv()
print(os.environ)
def init():
    boto_sess = boto3.Session(
        region_name=os.environ.get('region')
    )
    sess = sagemaker.session.Session(boto_session=boto_sess)
    role = os.environ.get('role')
    bucket = sess.default_bucket() 
    s3_code_prefix = f"sagemaker_endpoint/vllm/"
    os.system("tar czvf vllm_by_scripts.tar.gz vllm_by_scripts/")
    code_artifact = sess.upload_data("vllm_by_scripts.tar.gz", bucket, s3_code_prefix)
    print(f"S3 Code or Model tar ball uploaded to --- > {code_artifact}")
    
    #write code_artifact to .env file 
    with open("/home/ubuntu/llm_model_hub/backend/.env", "a") as f:
        f.write(f"code_artifact={code_artifact}")

if __name__ == "__main__":
    init()

