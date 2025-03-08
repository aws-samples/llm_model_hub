// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React ,{useState} from 'react';
import { Button, Modal, Box,  SpaceBetween, } from '@cloudscape-design/components';
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import gfm from "remark-gfm";
import {Prism, SyntaxHighlighterProps} from 'react-syntax-highlighter';
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
const SyntaxHighlighter = (Prism as any) as React.FC<SyntaxHighlighterProps>;

interface PageHeaderProps {
  extraActions?: React.ReactNode;
  selectedItems:ReadonlyArray<any>,
  visible: boolean;
  setVisible: (value: boolean) => void;
}

const codeSample = `
\`\`\`python
# !pip install boto3
import re
import json
import boto3
from botocore.exceptions import ClientError
import time
max_retries = 8
retry_delay = 10

# 更改成model hub部署的endpoint名称和region name
endpoint_name = "<endpoint>"
inference_component_name = "<inference_component_name>"
region_name = 'us-east-1'
runtime = boto3.client('runtime.sagemaker',region_name=region_name)
payload = {
    "messages": [
    {
        "role": "user",
        "content": "who are you"
    }
    ],
    "max_tokens": 1024,
    "stream": False,
    "model":"any"
}

print("# 指数回退重试 --------------")
def invoke_with_exponential_backoff(endpoint_name, payload,retry_delay):
    for attempt in range(max_retries):
        try:
            response = runtime.invoke_endpoint(
                EndpointName=endpoint_name,
                InferenceComponentName=inference_component_name,
                ContentType='application/json',
                Body=json.dumps(payload)
            )
            return response
        except ClientError as e:
            if e.response['Error']['Code'] == 'ValidationError' and 'Inference Component has no capacity' in e.response['Error']['Message']:
                if attempt < max_retries - 1:
                    print(f"Inference Component has no capacity, retrying in {retry_delay} seconds (attempt {attempt+1}/{max_retries})")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    print("Maximum retries reached, unable to process request")
            else:
                raise
            
response = invoke_with_exponential_backoff(endpoint_name, payload,retry_delay)
print(json.loads(response['Body'].read())["choices"][0]["message"]["content"])


print("# 非流式 --------------")
# 非流式
response = runtime.invoke_endpoint(
    EndpointName=endpoint_name,
    InferenceComponentName=inference_component_name,
    ContentType='application/json',
    Body=json.dumps(payload)
)

print(json.loads(response['Body'].read())["choices"][0]["message"]["content"])


payload = {
    "messages": [
    {
        "role": "user",
        "content": "Write a quick sort in python"
    }
    ],
    "max_tokens": 1024,
    "stream": True,
    "model":"any"
}


# 流式
print("# 流式 --------------")
response = runtime.invoke_endpoint_with_response_stream(
    EndpointName=endpoint_name,
    InferenceComponentName=inference_component_name,
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
\`\`\`
`

const MarkdownToHtml = ({ text }: { text: string }) => {
    return (
      <ReactMarkdown
        children={text}
        remarkPlugins={[gfm]}
        components={{
          code({ node, inline, className, children, ...props }: any) {
            const match = /language-(\w+)/.exec(className || "");
            return !inline && match ? (
              <SyntaxHighlighter
                {...props}
                children={String(children).replace(/\n$/, "")}
                style={vscDarkPlus}
                wrapLongLines
                language={match[1]}
                PreTag="div"
              />
            ) : (
              <code {...props} className={className}>
                {children}
              </code>
            );
          },
          img: (image) => (
            <img
              src={image.src || ""}
              alt={image.alt || ""}
              width={500}
              loading="lazy"
            />
          ),
        }}
      />
    );
  };

export const ViewCodeModal = ({
    extraActions = null,
    selectedItems,
    visible,
    setVisible,
    ...props
  }: PageHeaderProps) => {
    const { t } = useTranslation();
    const endpoint_name = selectedItems[0].endpoint_name
    const inference_component_name = JSON.parse(selectedItems[0].extra_config)?.inference_component_name
    const onConfirm =()=>{
       setVisible(false);
    }
    return (
      <Modal
        onDismiss={() => setVisible(false)}
        visible={visible}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={()=> setVisible(false)}>Cancel</Button>
              <Button variant="primary" onClick={onConfirm}>Confirm</Button>
            </SpaceBetween>
          </Box>
        }
        header="Endpoint Invoke Sample Code"
      >
        <MarkdownToHtml text={codeSample.replace("<endpoint>",endpoint_name).replace("<inference_component_name>",inference_component_name)} 
                key={`markdown-${endpoint_name}`} /> 
      </Modal>
    );
  }