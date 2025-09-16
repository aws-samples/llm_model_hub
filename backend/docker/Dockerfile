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
    && rm -rf /var/lib/apt/lists/*


# Make PIP_INDEX available after FROM
ARG PIP_INDEX
# Install sagemaker-training toolkit that contains the common functionality necessary to create a container compatible with SageMaker and the Python SDK.
RUN pip3 install sagemaker-training



# Install the requirements
COPY requirements_deps.txt /opt/ml/code/
COPY s5cmd /opt/ml/code/
COPY train.py /opt/ml/code/
COPY LLaMA-Factory/ /opt/ml/code/


# Set the working directory
WORKDIR /opt/ml/code/
RUN pip install "unsloth[cu126-torch260]"
RUN pip config set global.index-url "$PIP_INDEX" && \
    pip config set global.extra-index-url "$PIP_INDEX" && \
    python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt && pip install -e ".[metrics,bitsandbytes,deepspeed,liger-kernel,awq,qwen,modelscope,swanlab]"
# remove the requirements.txt in docker to prevent reinstallation
RUN rm requirements.txt setup.py
ENV DISABLE_VERSION_CHECK=1
# Instal extral dependencies
RUN python -m pip install -r requirements_deps.txt 
RUN pip uninstall -y intel-extension-for-pytorch



# 定义环境变量
ENV PATH="/opt/ml/code:${PATH}"

WORKDIR /
# Defines train.py as script entrypoint
ENV SAGEMAKER_PROGRAM train.py
