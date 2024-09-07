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
    s3_code_prefix = f"sagemaker_endpoint/vllm"
    os.system("tar czvf model.tar.gz model_tar/")
    model_artifact = sess.upload_data("model.tar.gz", bucket, s3_code_prefix)
    print(f"S3 Code or Model tar ball uploaded to --- > {model_artifact}")
    
    #write code_artifact to .env file 
    with open("/home/ubuntu/llm_model_hub/backend/.env", "a") as f:
        f.write(f"model_artifact={model_artifact}")

if __name__ == "__main__":
    init()

