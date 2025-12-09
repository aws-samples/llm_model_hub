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

# Install systemctl
RUN apt-get update && \
    apt-get install -y -o Dpkg::Options::="--force-confdef" systemd && \
    apt-get clean

# Install tini
RUN apt-get update && \
    apt-get install -y tini && \
    apt-get clean


# Make PIP_INDEX available after FROM
ARG PIP_INDEX
# Install sagemaker-training toolkit that contains the common functionality necessary to create a container compatible with SageMaker and the Python SDK.
# RUN pip3 install sagemaker-training boto3


# Uninstall nv-pytorch fork
RUN pip uninstall -y torch torchvision torchaudio \
    pytorch-quantization pytorch-triton torch-tensorrt \
    transformer-engine flash-attn apex megatron-core \
    xgboost opencv grpcio

# Remove nv file
RUN rm -rf /workspace

# Fix cv2
RUN rm -rf /usr/local/lib/python3.10/dist-packages/cv2

# Install torch-2.8.0+cu128 + vllm-0.11.0
RUN pip install --no-cache-dir "vllm==0.11.0" "torch==2.8.0" "torchvision==0.23.0" "torchaudio==2.8.0" tensordict torchdata \
    "transformers[hf_xet]>=4.51.0" accelerate datasets peft hf-transfer \
    "numpy<2.0.0" "pyarrow>=15.0.0" "grpcio>=1.62.1" "optree>=0.13.0" pandas \
    ray[default] codetiming hydra-core pylatexenc qwen-vl-utils wandb liger-kernel mathruler \
    pytest yapf py-spy pre-commit ruff

# Install flash-attn-2.8.3
RUN ABI_FLAG=$(python -c "import torch; print('TRUE' if torch._C._GLIBCXX_USE_CXX11_ABI else 'FALSE')") && \
    URL="https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.3/flash_attn-2.8.3+cu12torch2.8cxx11abi${ABI_FLAG}-cp312-cp312-linux_x86_64.whl" && \
    wget -nv -P /opt/tiger "${URL}" && \
    pip install --no-cache-dir "/opt/tiger/$(basename ${URL})"

# Install the requirements
COPY requirements_deps.txt /opt/ml/code/
COPY train.py /opt/ml/code/
COPY s5cmd /opt/ml/code/
COPY EasyR1/ /opt/ml/code/

# Set the working directory
WORKDIR /opt/ml/code/
RUN pip config set global.index-url "$PIP_INDEX" && \
    pip config set global.extra-index-url "$PIP_INDEX" && \
    python -m pip install --upgrade pip && \
    pip install boto3 &&\
    pip install -e . && \
    pip install -r requirements_deps.txt 
RUN pip install sagemaker-training>=5.0.0
# remove the requirements.txt in docker to prevent reinstallation
RUN rm requirements.txt setup.py


# 定义环境变量
ENV PATH "/opt/ml/code:${PATH}"

WORKDIR /
# Defines train.py as script entrypoint
ENV SAGEMAKER_PROGRAM train.py
