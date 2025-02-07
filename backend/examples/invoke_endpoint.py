# !pip install boto3
import re
import json
import boto3
import time

# 更改成model hub部署的endpoint名称和region name
endpoint_name = "DeepSeek-R1-Distill-Qwen-32B-2025-02-07-05-01-54-000"
region_name = 'us-east-1'
runtime = boto3.client('runtime.sagemaker',region_name=region_name)
payload = {
    "messages": [
    {
        "role": "user",
        "content": "Write a quick sort in python"
    }
    ],
    "max_tokens": 8000,
    "stream": False
}

# 非流式
t1 = time.time()
response = runtime.invoke_endpoint(
    EndpointName=endpoint_name,
    ContentType='application/json',
    Body=json.dumps(payload)
)
t2 = time.time()
body = json.loads(response['Body'].read())
cost = t2-t1
print(f"cost time:{cost} s")
completion_tokens = body['usage']['completion_tokens']
print(f"output tokens per s:{completion_tokens/cost}")
print(body["choices"][0]["message"]["content"])


payload = {
    "messages": [
    {
        "role": "user",
        "content": "Write a quick sort in python"
    }
    ],
    "max_tokens": 8000,
    "stream": True
}

# 流式
response = runtime.invoke_endpoint_with_response_stream(
    EndpointName=endpoint_name,
    ContentType='application/json',
    Body=json.dumps(payload)
)

buffer = ""
for t in response['Body']:
    buffer += t["PayloadPart"]["Bytes"].decode()
    last_idx = 0
    for match in re.finditer(r'^data:\s*(.+?)(\n\n)', buffer):
        try:
            data = json.loads(match.group(1).strip())
            last_idx = match.span()[1]
            print(data["choices"][0]["delta"]["content"], end="",flush=True)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            pass
    buffer = buffer[last_idx:]