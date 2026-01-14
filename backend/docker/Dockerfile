# Default use the NVIDIA official image with PyTorch 2.3.0
# https://docs.nvidia.com/deeplearning/frameworks/pytorch-release-notes/index.html
# SageMaker Framework Container Versions
# https://github.com/aws/deep-learning-containers/blob/master/available_images.md
ARG BASE_IMAGE
ARG PIP_INDEX

# Use the BASE_IMAGE argument
FROM ${BASE_IMAGE}

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv - fast Python package manager
ENV UV_LINK_MODE=copy
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/ && \
    mv /root/.local/bin/uvx /usr/local/bin/

# Make PIP_INDEX available after FROM
ARG PIP_INDEX

# Install sagemaker-training toolkit
RUN uv pip install --system sagemaker-training

# Install the requirements
COPY requirements_deps.txt /opt/ml/code/
COPY s5cmd /opt/ml/code/
COPY train.py /opt/ml/code/
COPY LLaMA-Factory/ /opt/ml/code/

# Set the working directory
WORKDIR /opt/ml/code/

# Install unsloth
RUN uv pip install --system unsloth

# Install LLaMA-Factory dependencies
RUN uv pip install --system --index-url "$PIP_INDEX" --extra-index-url https://pypi.org/simple -e. 
RUN uv pip install --system  -r requirements/metrics.txt && \
    uv pip install --system  -r requirements/bitsandbytes.txt && \
    uv pip install --system  -r requirements/deepspeed.txt && \
    uv pip install --system  -r requirements/liger-kernel.txt && \
    uv pip install --system -e ".[awq,qwen,modelscope,swanlab]"

# Remove the requirements.txt in docker to prevent reinstallation
RUN rm pyproject.toml
ENV DISABLE_VERSION_CHECK=1

# Install flash_attn separately with torch already available
RUN uv pip install --system --no-build-isolation flash-attn>=2.7.4.post1

# Install remaining dependencies
RUN uv pip install --system -r requirements_deps.txt

# Uninstall intel-extension-for-pytorch if exists
RUN uv pip uninstall --system intel-extension-for-pytorch || true

# 定义环境变量
ENV PATH="/opt/ml/code:${PATH}"

WORKDIR /
# Defines train.py as script entrypoint
ENV SAGEMAKER_PROGRAM train.py
