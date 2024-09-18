ARG VLLM_VERSION
FROM vllm/vllm-openai:$VLLM_VERSION

# 设置工作目录
WORKDIR /app

# 复制当前目录下的内容到容器内的/app
COPY app/ /app

# 安装新的依赖
COPY requirements.txt /app
RUN pip install -r requirements.txt  

# 修改restapi
RUN \
export PYTHON_SITEPACKAGES=`python3 -c "import site; print(site.getsitepackages()[0])"`; \
sed -i '/if __name__ == "__main__":/i\
\@router.get("/ping")\n\
async def ping() -> Response:\n\
\    return await health()\n\
\n\
from typing import Union\n\
@router.post("/invocations")\n\
async def invocations(request: Union[ChatCompletionRequest, CompletionRequest],\n\
\                                 raw_request: Request):\n\
\    if isinstance(request, ChatCompletionRequest):\n\
\        return await create_chat_completion(request, raw_request)\n\
\    elif isinstance(request, CompletionRequest):\n\
\        return await create_completion(request, raw_request)\n\
\    else:\n\
\        return JSONResponse("unknow request paras",\n\
\                            status_code=HTTPStatus.BAD_REQUEST)\n\
' ${PYTHON_SITEPACKAGES}/vllm/entrypoints/openai/api_server.py; \
sed -i 's/model: str/model: Optional[str] = None/' ${PYTHON_SITEPACKAGES}/vllm/entrypoints/openai/protocol.py ; \
sed -i 's/extra="forbid"//1' ${PYTHON_SITEPACKAGES}/vllm/entrypoints/openai/protocol.py ; \
sed -i '/async def _check_model/,/:$/!b;/:$/a\
\        if 1 == 1:\n\
\            return None\n\
' ${PYTHON_SITEPACKAGES}/vllm/entrypoints/openai/serving_engine.py; \
sed -i '/def _maybe_get_adapters/,/:$/!b;/:$/a\
\        if 1 == 1:\n\
\            return None, None\n\
' ${PYTHON_SITEPACKAGES}/vllm/entrypoints/openai/serving_engine.py; \
chmod +x /app/serve

# 让端口8080在容器外可用
EXPOSE 8080

# 定义环境变量
ENV PATH="/app:${PATH}"

# 运行serve
ENTRYPOINT []
CMD ["serve"]