// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React ,{useState} from 'react';
import { Button, Modal, Box,  SpaceBetween, Tabs } from '@cloudscape-design/components';
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

// Helper function to parse extra_config
const parseExtraConfig = (item: any) => {
  if (!item.extra_config) return {};
  try {
    return typeof item.extra_config === 'string'
      ? JSON.parse(item.extra_config)
      : item.extra_config;
  } catch {
    return {};
  }
};

// Helper to normalize URL (remove protocol and path, keep only hostname)
const normalizeUrl = (url: string): string => {
  // Remove protocol
  let cleanUrl = url.replace(/^https?:\/\//, '');
  // Remove path (keep only hostname)
  const slashIndex = cleanUrl.indexOf('/');
  if (slashIndex !== -1) {
    cleanUrl = cleanUrl.substring(0, slashIndex);
  }
  return cleanUrl;
};

// HyperPod OpenAI SDK code sample
const getHyperPodCodeSample = (baseUrl: string, apiKey: string, modelName: string) => {
  const cleanUrl = normalizeUrl(baseUrl);
  return `
\`\`\`python
# pip install openai
from openai import OpenAI

# HyperPod Inference Endpoint Configuration
BASE_URL = "${cleanUrl}"
API_KEY = "${apiKey}"
MODEL_NAME = "${modelName}"

# Note: ALB uses self-signed certificate, disable SSL verification
client = OpenAI(
    base_url=f"https://{BASE_URL}/v1",
    api_key=API_KEY
)

#******** 示例1 非流式 ************
response = client.chat.completions.create(
    model=MODEL_NAME,
    messages=[
        {"role": "user", "content": "Hi, who are you?"}
    ],
    max_tokens=1024,
    stream=False
)
print(response.choices[0].message.content)


#******** 示例2 流式 ************
stream = client.chat.completions.create(
    model=MODEL_NAME,
    messages=[
        {"role": "user", "content": "Write a quick sort in python"}
    ],
    max_tokens=4096,
    stream=True
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
print()


#******** 示例3 流式 reasoning (QwQ/DeepSeek-R1等推理模型) ************
stream = client.chat.completions.create(
    model=MODEL_NAME,
    messages=[
        {"role": "user", "content": "Solve: What is 25 * 37?"}
    ],
    max_tokens=8000,
    stream=True,
    extra_body={"reasoning_effort": "high"}  # 可选: low, medium, high
)

for chunk in stream:
    delta = chunk.choices[0].delta
    # 推理内容 (思考过程)
    if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
        print(f"[思考] {delta.reasoning_content}", end="", flush=True)
    # 最终回答
    if delta.content:
        print(delta.content, end="", flush=True)
print()


#******** 示例4 Tool Use / Function Calling ************
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather in a given city",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"}
                },
                "required": ["city"]
            },
        },
    }
]

response = client.chat.completions.create(
    model=MODEL_NAME,
    messages=[
        {"role": "user", "content": "What's the weather in Beijing?"}
    ],
    tools=tools,
    tool_choice="auto",
    max_tokens=1024
)

message = response.choices[0].message
if message.tool_calls:
    for tool_call in message.tool_calls:
        print(f"Function: {tool_call.function.name}")
        print(f"Arguments: {tool_call.function.arguments}")
else:
    print(message.content)


#******** 示例5 Vision (多模态模型) ************
# 需要模型支持视觉输入，如 Qwen-VL, LLaVA 等
response = client.chat.completions.create(
    model=MODEL_NAME,
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What's in this image?"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/300px-PNG_transparency_demonstration_1.png"
                    }
                }
            ]
        }
    ],
    max_tokens=1024
)
print(response.choices[0].message.content)


#******** 示例6 Embeddings (需要部署embedding模型) ************
# response = client.embeddings.create(
#     model=MODEL_NAME,
#     input="Hello, world!"
# )
# print(response.data[0].embedding[:10])  # 打印前10维
\`\`\`
`;
};

// cURL code sample for HyperPod
const getHyperPodCurlSample = (baseUrl: string, apiKey: string, modelName: string) => {
  const cleanUrl = normalizeUrl(baseUrl);
  return `
\`\`\`bash
# Note: -k flag skips SSL certificate verification (self-signed cert)

# 非流式请求
curl -k -X POST "https://${cleanUrl}/v1/chat/completions" \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${apiKey}" \\
  -d '{
    "model": "${modelName}",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 1024
  }'

# 流式请求
curl -k -X POST "https://${cleanUrl}/v1/chat/completions" \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${apiKey}" \\
  -d '{
    "model": "${modelName}",
    "messages": [{"role": "user", "content": "Write a quick sort in python"}],
    "max_tokens": 4096,
    "stream": true
  }'

# 查看可用模型
curl -k "https://${cleanUrl}/v1/models" \\
  -H "Authorization: Bearer ${apiKey}"
\`\`\`
`;
};

const codeSample = `
\`\`\`python
# !pip install boto3
import re
import json
import boto3

# 更改成model hub部署的endpoint名称和region name
endpoint_name = "<endpoint>"
region_name = 'us-east-1'
runtime = boto3.client('runtime.sagemaker',region_name=region_name)

#******** 示例1 非流式 ************
payload = {
    "messages": [
    {
        "role": "user",
        "content": "Hi, who are you"
    }
    ],
    "max_tokens": 1024,
    "stream": False,
    "model":"any"
}

response = runtime.invoke_endpoint(
    EndpointName=endpoint_name,
    ContentType='application/json',
    Body=json.dumps(payload)
)

print(json.loads(response['Body'].read())["choices"][0]["message"]["content"])


#******** 示例2 流式 ************
payload = {
    "messages": [
    {
        "role": "user",
        "content": "Write a quick sort in python"
    }
    ],
    "max_tokens": 4096,
    "stream": True,
    "model":"any"
}

response = runtime.invoke_endpoint_with_response_stream(
    EndpointName=endpoint_name,
    ContentType='application/json',
    Body=json.dumps(payload)
)

buffer = ""
for t in response['Body']:
    buffer += t["PayloadPart"]["Bytes"].decode()
    last_idx = 0
    for match in re.finditer(r'^data:\\s*(.+?)(\\n\\n)', buffer):
        try:
            data = json.loads(match.group(1).strip())
            last_idx = match.span()[1]
            print(data["choices"][0]["delta"]["content"], end="",flush=True)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            pass
    buffer = buffer[last_idx:]

#******** 示例3 流式 reasoning ************
payload = {
    "messages": [
    {
        "role": "user",
        "content": "Solve: What is 25 * 37?"
    }
    ],
    "max_tokens": 8000,
    "stream": True,
    "model":"any",
    "reasoning_effort":"high"
}
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
            if data["choices"][0]["delta"].get("content"):
                print(data["choices"][0]["delta"]["content"], end="",flush=True)
            if data["choices"][0]["delta"].get("reasoning_content"):
                print(data["choices"][0]["delta"]["reasoning_content"], end="",flush=True)
            if data["choices"][0]["delta"].get("tool_calls"):
                print(data["choices"][0]["delta"]["tool_calls"], end="",flush=True)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            pass
    buffer = buffer[last_idx:]


#******** 示例4 流式 tool use ************
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather in a given city",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"]
            },
        },
    }
]

payload = {
    "messages": [
    {
        "role": "user",
        "content": """get weather of beijing"""
    }
    ],
    "max_tokens": 8000,
    "temperature":0.5,
    "stream": True,
    "model":"any",
    "reasoning_effort":"low",
    "tools":tools
}

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
            if data["choices"][0]["delta"].get("content"):
                print(data["choices"][0]["delta"]["content"], end="",flush=True)
            if data["choices"][0]["delta"].get("reasoning_content"):
                print(data["choices"][0]["delta"]["reasoning_content"], end="",flush=True)
            if data["choices"][0]["delta"].get("tool_calls"):
                print(data["choices"][0]["delta"]["tool_calls"], end="",flush=True)
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
    selectedItems,
    visible,
    setVisible,
  }: PageHeaderProps) => {
    const [activeTabId, setActiveTabId] = useState("python");
    const item = selectedItems[0];
    const endpoint_name = item.endpoint_name;
    const isHyperPod = item.deployment_target === 'hyperpod';

    // Get HyperPod specific config
    const extraConfig = parseExtraConfig(item);
    const albUrl = extraConfig.alb_url || extraConfig.endpoint_url || '<ALB_URL>';
    const apiKey = extraConfig.api_key || '<API_KEY>';
    // Use the served model name (short name without org prefix)
    // vLLM/SGLang use --served-model-name which extracts just the model name part
    const rawModelName = item.model_name || '<MODEL_NAME>';
    const modelName = rawModelName.includes('/') ? rawModelName.split('/').pop() : rawModelName;

    const onConfirm = () => {
       setVisible(false);
    }

    // Render HyperPod code samples with tabs
    const renderHyperPodSamples = () => (
      <Tabs
        activeTabId={activeTabId}
        onChange={({ detail }) => setActiveTabId(detail.activeTabId)}
        tabs={[
          {
            id: "python",
            label: "Python (OpenAI SDK)",
            content: <MarkdownToHtml text={getHyperPodCodeSample(albUrl, apiKey, modelName)} key={`python-${endpoint_name}`} />
          },
          {
            id: "curl",
            label: "cURL",
            content: <MarkdownToHtml text={getHyperPodCurlSample(albUrl, apiKey, modelName)} key={`curl-${endpoint_name}`} />
          }
        ]}
      />
    );

    // Render SageMaker code sample
    const renderSageMakerSample = () => (
      <MarkdownToHtml text={codeSample.replace("<endpoint>", endpoint_name)} key={`markdown-${endpoint_name}`} />
    );

    return (
      <Modal
        onDismiss={() => setVisible(false)}
        visible={visible}
        size={isHyperPod ? "large" : "medium"}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setVisible(false)}>Cancel</Button>
              <Button variant="primary" onClick={onConfirm}>Confirm</Button>
            </SpaceBetween>
          </Box>
        }
        header={isHyperPod ? "HyperPod Endpoint - OpenAI Compatible API" : "SageMaker Endpoint Invoke Sample Code"}
      >
        {isHyperPod ? renderHyperPodSamples() : renderSageMakerSample()}
      </Modal>
    );
  }
