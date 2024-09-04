ARG VLLM_VERSION
FROM vllm/vllm-openai:$VLLM_VERSION

# 设置工作目录
WORKDIR /app

# 复制当前目录下的内容到容器内的/app
COPY app/ /app

# 修改restapi
RUN sed -i '/if __name__ == "__main__":/i\
@router.get("/ping")\n\
async def ping() -> Response:\n\
    return await health()\n\
\n\
from typing import Union\n\
@router.post("/invocations")\n\
async def invocations(request: Union[ChatCompletionRequest, CompletionRequest],\n\
                                 raw_request: Request):\n\
    if isinstance(request, ChatCompletionRequest):\n\
        return await create_chat_completion(request, raw_request)\n\
    elif isinstance(request, CompletionRequest):\n\
        return await create_completion(request, raw_request)\n\
    else:\n\
        return JSONResponse("unknow request paras",\n\
                            status_code=HTTPStatus.BAD_REQUEST)\n\
' /usr/local/lib/python3.10/dist-packages/vllm/entrypoints/openai/api_server.py; \
chmod +x /app/serve

# 让端口8080在容器外可用
EXPOSE 8080

# 定义环境变量
ENV PATH="/app:${PATH}"

# 运行serve
ENTRYPOINT []
CMD ["serve"]