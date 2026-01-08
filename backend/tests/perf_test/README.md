# Endpoint Performance Benchmark

并发推理性能测试工具，用于测试LLM endpoint的吞吐量和延迟。

## 安装依赖

```bash
cd backend
source .venv/bin/activate
uv pip install -r requirements.txt
```

或者使用uv直接安装到虚拟环境：
```bash
cd backend
uv pip install openai httpx
```

## 使用方法

### 快速开始（使用快捷脚本）

使用 `quick_test.sh` 脚本快速运行测试：

```bash
cd backend/tests/perf_test
./quick_test.sh <BASE_URL> <API_KEY> <MODEL_NAME> [CONCURRENCY] [REQUESTS]
```

**示例：**
```bash
# 使用默认并发数(10)和请求数(50)
./quick_test.sh \
  "k8s-hyperpod-alb-xxx.elb.amazonaws.com" \
  "sk-xxxx" \
  "Qwen3-4B-Instruct-2507"

# 自定义并发数和请求数
./quick_test.sh \
  "k8s-hyperpod-alb-xxx.elb.amazonaws.com" \
  "sk-xxxx" \
  "Qwen3-4B-Instruct-2507" \
  20 \
  100
```

**参数说明：**
- `BASE_URL` - Endpoint基础URL（必需）
- `API_KEY` - API认证密钥（必需）
- `MODEL_NAME` - 模型名称（必需）
- `CONCURRENCY` - 并发请求数（可选，默认：10）
- `REQUESTS` - 总请求数（可选，默认：50）

### 基本用法（直接调用）

**选项1：激活虚拟环境后运行**
```bash
cd backend
source .venv/bin/activate
python tests/benchmark_endpoint.py \
  --base-url "..." \
  --api-key "..." \
  --model "..."
```

**选项2：直接使用虚拟环境的python**
```bash
backend/.venv/bin/python3 backend/tests/benchmark_endpoint.py \
  --base-url "k8s-hyperpod-albqwen3-f9376ffb83-1731952361.us-east-1.elb.amazonaws.com" \
  --api-key "sk-c0d76a065a9f9c681067d223e73c83319426120b6bc05660ee6301330bb21539" \
  --model "Qwen3-4B-Instruct-2507" \
  --concurrency 10 \
  --requests 100
```

### 参数说明

- `--base-url`: Endpoint的基础URL（支持ALB地址或完整的https://...）
- `--api-key`: API认证密钥
- `--model`: 模型名称
- `--concurrency`: 并发请求数（默认：10）
- `--requests`: 总请求数（默认：100）
- `--max-tokens`: 每次生成的最大token数（默认：256）
- `--prompt`: 测试使用的prompt（默认：关于AI的短故事）
- `--stream`: 启用流式模式（**默认：启用**，测量TTFT）
- `--no-stream`: 禁用流式模式（使用非流式请求）
- `--show-samples`: 显示样本输出数量（**默认：3**，设为0禁用）
- `--verify-ssl`: 启用SSL证书验证（默认关闭，因为ALB使用自签名证书）
- `--timeout`: 请求超时时间（秒，默认：120）

### 测试场景示例

#### 1. 低并发基准测试（流式模式，测量TTFT）
```bash
python backend/tests/benchmark_endpoint.py \
  --base-url "<your-alb-url>" \
  --api-key "<your-api-key>" \
  --model "<your-model>" \
  --concurrency 5 \
  --requests 50
```

#### 2. 高并发压力测试（流式模式）
```bash
python backend/tests/benchmark_endpoint.py \
  --base-url "<your-alb-url>" \
  --api-key "<your-api-key>" \
  --model "<your-model>" \
  --concurrency 50 \
  --requests 500 \
  --max-tokens 128
```

#### 3. 非流式测试（测量端到端延迟）
```bash
python backend/tests/benchmark_endpoint.py \
  --base-url "<your-alb-url>" \
  --api-key "<your-api-key>" \
  --model "<your-model>" \
  --concurrency 10 \
  --requests 100 \
  --no-stream
```

#### 4. 长文本生成测试（流式模式）
```bash
python backend/tests/benchmark_endpoint.py \
  --base-url "<your-alb-url>" \
  --api-key "<your-api-key>" \
  --model "<your-model>" \
  --concurrency 5 \
  --requests 20 \
  --max-tokens 2048 \
  --prompt "Write a detailed technical article about distributed systems."
```

#### 5. 禁用样本输出（仅显示统计数据）
```bash
python backend/tests/benchmark_endpoint.py \
  --base-url "<your-alb-url>" \
  --api-key "<your-api-key>" \
  --model "<your-model>" \
  --concurrency 10 \
  --requests 100 \
  --show-samples 0
```

#### 6. 显示更多样本输出（调试用）
```bash
python backend/tests/benchmark_endpoint.py \
  --base-url "<your-alb-url>" \
  --api-key "<your-api-key>" \
  --model "<your-model>" \
  --concurrency 10 \
  --requests 50 \
  --show-samples 5
```

## 输出指标

测试完成后会输出以下性能指标：

### 基础指标
- **Total Requests**: 总请求数
- **Successful/Failed**: 成功/失败请求数
- **Success Rate**: 成功率
- **Total Duration**: 总测试时长
- **Requests/sec**: 每秒请求数（吞吐量）
- **Tokens/sec**: 每秒处理的token数（input + output）

### Token 统计
- **Total Input**: 总输入token数（所有请求的prompt tokens总和）
- **Total Output**: 总输出token数（所有请求的completion tokens总和）
- **Total**: 总token数（input + output）
- **Avg Input/req**: 平均每个请求的输入token数
- **Avg Output/req**: 平均每个请求的输出token数
- **Input tokens/sec**: 每秒输入token数（整体吞吐量）
- **Output tokens/sec**: 每秒输出token数（整体吞吐量）
- **Avg output speed**: 平均每个请求的输出速度（tokens/sec/request），衡量单个请求的生成速度

### 延迟统计（Latency Statistics）
- **Average**: 平均延迟
- **Median (P50)**: 中位数延迟
- **P90/P95/P99**: 90/95/99百分位延迟
- **Min/Max**: 最小/最大延迟

### 流式模式指标（默认启用）
- **TTFT (Time to First Token)**: 首token延迟，衡量用户感知延迟的关键指标
  - Average: 平均TTFT
  - Median (P50): 中位数TTFT
  - P90: 90百分位TTFT

**注意**: 使用 `--no-stream` 禁用流式模式时，将不显示TTFT统计

## 示例输出

### 样本输出示例

测试过程中会实时显示样本输出（默认显示3个）：

```
Starting benchmark:
  Endpoint: k8s-hyperpod-albqwen3-xxx.elb.amazonaws.com
  Model: Qwen3-4B-Instruct-2507
  Concurrency: 10
  Total Requests: 100
  Max Tokens: 256
  Stream: True
  Show Samples: 3
  Prompt: Write a short story about artificial intelligence.

============================================================
Sample Output #1
============================================================
Latency: 4.32s | Output tokens: 248 | Speed: 57.4 tokens/sec
TTFT: 0.198s
------------------------------------------------------------
Once upon a time, in a world where technology had advanced
beyond imagination, there lived an AI named Nova. Nova was
not just any ordinary artificial intelligence; she possessed
consciousness and emotions...
[Content continues...]
============================================================

Progress: 10/100 requests completed

============================================================
Sample Output #2
============================================================
Latency: 4.18s | Output tokens: 256 | Speed: 61.2 tokens/sec
TTFT: 0.212s
------------------------------------------------------------
In the year 2157, artificial intelligence had become an
integral part of human society...
[Content continues...]
============================================================

Progress: 20/100 requests completed
...
Progress: 100/100 requests completed
```

### 最终统计结果

```

============================================================
BENCHMARK RESULTS
============================================================
Total Requests:      100
Successful:          98
Failed:              2
Success Rate:        98.00%
Total Duration:      45.32s

Requests/sec:        2.16
Tokens/sec:          553.47

Token Statistics:
  Total Input:       12,450 tokens
  Total Output:      25,080 tokens
  Total:             37,530 tokens
  Avg Input/req:     127.0 tokens
  Avg Output/req:    256.0 tokens
  Input tokens/sec:  274.73 (overall throughput)
  Output tokens/sec: 553.47 (overall throughput)
  Avg output speed:  56.89 tokens/sec/request

Latency Statistics (seconds):
  Average:           4.521
  Median (P50):      4.312
  P90:               5.678
  P95:               6.234
  P99:               7.891
  Min:               2.134
  Max:               8.234

Time to First Token (TTFT) - seconds:
  Average:           0.234
  Median (P50):      0.198
  P90:               0.312

Errors (2 unique):
  - Request timeout after 120s
============================================================
```

## 样本输出功能

### 功能说明

测试工具默认会在测试过程中显示前3个成功请求的实际输出内容，帮助你：
1. **验证输出质量**: 确认模型输出是否符合预期
2. **调试问题**: 快速发现格式错误或内容异常
3. **性能分析**: 查看每个样本的延迟、token数和生成速度

### 样本信息包含

每个样本输出显示：
- **Latency**: 该请求的总延迟时间
- **Output tokens**: 输出的token数量
- **Speed**: 该请求的生成速度（tokens/sec）
- **TTFT**: 首token延迟（仅流式模式）
- **Content**: 实际生成的文本内容（超过500字符会截断）

### 使用场景

**默认模式（显示3个样本）**
```bash
./quick_test.sh "..." "..." "..." 10 50
# 适合大多数测试场景，既能看到输出质量，又不会过多干扰
```

**禁用样本输出（大规模压测）**
```bash
python benchmark_endpoint.py ... --show-samples 0
# 适合高并发压力测试，专注于性能指标
```

**显示更多样本（质量验证）**
```bash
python benchmark_endpoint.py ... --show-samples 10
# 适合验证模型输出质量和一致性
```

## 指标说明

### 吞吐量 vs 单请求速度

理解两个关键指标的区别：

**Output tokens/sec（整体吞吐量）**
- 计算方式：总输出tokens / 总测试时间
- 衡量：整个系统的并发处理能力
- 受并发数影响：并发越高，整体吞吐量通常越高
- 用途：评估系统容量和资源利用率

**Avg output speed（单请求速度）**
- 计算方式：平均(每个请求的输出tokens / 该请求的延迟)
- 衡量：单个请求的生成速度
- 不受并发数影响：反映模型本身的生成速度
- 用途：评估模型性能和用户体验

**示例说明：**
```
并发10，每个请求生成256 tokens，每个请求耗时4.5秒
- Output tokens/sec: 570 tokens/sec（10个请求并发，总吞吐量）
- Avg output speed: 57 tokens/sec/request（单个请求的生成速度）
```

## 性能调优建议

1. **并发数选择**
   - 从低并发（5-10）开始测试baseline
   - 逐步增加并发数找到最佳吞吐量
   - 监控P99延迟和P90 TTFT，避免过高并发导致服务降级

2. **请求数**
   - 建议至少100个请求以获得稳定的统计数据
   - 压力测试可以使用500-1000个请求

3. **Max Tokens**
   - 较小的max_tokens（128-256）适合吞吐量测试
   - 较大的max_tokens（1024-2048）适合延迟测试

4. **流式 vs 非流式（默认流式）**
   - **流式模式（默认）**:
     - 测试用户体验（TTFT - 首token延迟）
     - 衡量实际感知性能
     - TTFT 是评估用户体验的关键指标
   - **非流式模式（--no-stream）**:
     - 测试总体吞吐量和端到端延迟
     - 适合批处理场景

5. **TTFT 优化目标**
   - **优秀**: P90 TTFT < 200ms
   - **良好**: P90 TTFT < 500ms
   - **可接受**: P90 TTFT < 1s
   - 如果 TTFT 过高，考虑减少并发或增加资源
