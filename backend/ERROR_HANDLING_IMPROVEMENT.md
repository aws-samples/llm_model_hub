# 错误处理改进方案

## 📋 问题概述

之前的系统中，当训练任务 (`processing_job`) 发生错误时，具体的错误信息只记录在服务器日志中，前端无法获取到详细的错误原因，导致用户难以排查问题。

## ✅ 解决方案

我们实施了完整的错误信息追踪和传递机制，确保前端能够获取到详细的错误信息。

### 改进内容

#### 1. **数据库层面**

##### a. 添加错误信息字段

**文件**: `backend/scripts/mysql_setup.sql`
- 在 `JOB_TABLE` 表中添加了 `error_message` 字段（TEXT类型）
- 添加了索引以提高查询性能

```sql
error_message TEXT DEFAULT NULL
INDEX idx_job_status (job_status)
INDEX idx_job_id (job_id)
```

##### b. 数据库迁移脚本

**文件**: `backend/scripts/add_error_message_field.sql`
- 为现有数据库添加 `error_message` 字段的迁移脚本
- 自动更新现有 ERROR 状态的任务

**执行方法**:
```bash
docker exec -it hub-mysql mysql -uroot -p1234560
```

切换到database llm.   
执行：  
```sql
SET @col_exists = (
    SELECT COUNT(*) 
    FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = DATABASE() 
    AND TABLE_NAME = 'JOB_TABLE' 
    AND COLUMN_NAME = 'error_message'
);
SET @query = IF(@col_exists = 0, 
    'ALTER TABLE JOB_TABLE ADD COLUMN error_message TEXT DEFAULT NULL', 
    'SELECT "Column already exists" AS message'
);
PREPARE stmt FROM @query;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
```

#### 2. **数据访问层 (Database Layer)**

**文件**: `backend/db_management/database.py`

新增了两个方法：

##### `update_job_error(job_id, error_message, status=JobStatus.ERROR)`
- 更新任务错误信息和状态
- 自动设置任务结束时间
- 参数：
  - `job_id`: 任务ID
  - `error_message`: 详细错误信息（支持多行）
  - `status`: 任务状态（默认为ERROR）

##### `get_job_error(job_id)`
- 获取任务的错误信息
- 返回错误消息字符串，如果无错误则返回 None

#### 3. **业务逻辑层**

##### a. 作业状态机 (Job State Machine)

**文件**: `backend/processing_engine/job_state_machine.py`

**主要改进**:
1. 添加了 `error_message` 属性用于存储错误信息
2. 增强了 `run_handler()`:
   - 捕获详细的异常堆栈
   - 保存错误信息到 `error_message` 属性
3. 改进了 `error_handler()`:
   - 自动将错误信息保存到数据库
   - 记录前200个字符到日志以便快速诊断

##### b. 任务处理引擎

**文件**: `backend/processing_engine/main.py`

**主要改进**:
1. **三阶段错误处理**:
   - Phase 1 (CREATING): 创建任务失败时记录详细错误
   - Phase 2 (RUNNING): 运行任务失败时记录详细错误
   - Phase 3 (Check Status): 检查最终状态

2. **全局异常捕获**:
   ```python
   - 捕获所有未预期的异常
   - 记录异常类型、消息和完整堆栈跟踪
   - 安全地保存错误到数据库（即使数据库操作失败也会记录）
   ```

3. **错误信息格式**:
   ```
   Unexpected error in processing job {job_id}:
   Error Type: {exception_type}
   Error Message: {error_message}

   Full Traceback:
   {full_stacktrace}
   ```

#### 4. **数据模型层**

**文件**: `backend/model/data_model.py`

在 `JobInfo` 类中添加了:
```python
error_message: Optional[str] = None  # Detailed error message when job fails
```

#### 5. **API 层**

**文件**: `backend/training/jobs.py`

修改了以下函数以返回错误信息:
1. `get_job_by_id()` - 单个任务查询
2. `list_jobs()` - 任务列表查询
3. `sync_get_job_by_id()` - 同步任务查询

所有这些函数现在都会从数据库读取并返回 `error_message` 字段。

## 🎯 使用方法

### 1. 数据库迁移

如果你的数据库已存在，需要先执行迁移脚本：

```bash
# 连接到MySQL数据库
mysql -u root -p

# 选择数据库
USE your_database_name;

# 执行迁移脚本
SOURCE /home/ubuntu/workspace/llm_model_hub/backend/scripts/add_error_message_field.sql;

# 验证字段是否添加成功
DESCRIBE JOB_TABLE;
```

### 2. 重启后端服务

```bash
cd /home/ubuntu/workspace/llm_model_hub/backend
python server.py
```

### 3. 前端获取错误信息

前端通过 API 获取任务详情时，会自动包含 `error_message` 字段：

**API 请求示例**:
```javascript
// 获取单个任务
const response = await fetch('/v1/get_training_job', {
  method: 'POST',
  body: JSON.stringify({ job_id: 'xxx' })
});

const data = await response.json();
console.log(data.body.error_message);  // 错误信息
```

**响应示例**:
```json
{
  "response_id": "...",
  "body": {
    "job_id": "abc123",
    "job_name": "my-training-job",
    "job_status": "ERROR",
    "error_message": "Unexpected error in processing job abc123:\nError Type: ValueError\nError Message: Invalid parameter...\n\nFull Traceback:\n..."
  }
}
```

## 📊 错误信息内容

错误信息包含以下内容：

1. **错误类型**: 异常的类名（如 ValueError, RuntimeError）
2. **错误消息**: 异常的具体描述
3. **完整堆栈**: 包含文件名、行号、函数调用链

**示例**:
```
Unexpected error in processing job 12345abc:
Error Type: RuntimeError
Error Message: CUDA out of memory

Full Traceback:
  File "/backend/processing_engine/main.py", line 47, in proccessing_job
    if not job.transition(JobStatus.RUNNING):
  File "/backend/processing_engine/job_state_machine.py", line 67, in run_handler
    self.train_job_exe.run()
  File "/backend/training/training_job.py", line 123, in run
    model.train()
RuntimeError: CUDA out of memory
```

## 🔍 前端展示建议

### 1. 在任务详情页显示错误信息

```jsx
{job.job_status === 'ERROR' && job.error_message && (
  <Alert type="error">
    <h3>任务失败</h3>
    <pre style={{
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
      backgroundColor: '#f5f5f5',
      padding: '12px',
      borderRadius: '4px',
      maxHeight: '400px',
      overflow: 'auto'
    }}>
      {job.error_message}
    </pre>
  </Alert>
)}
```

### 2. 在任务列表中显示错误摘要

```jsx
{job.job_status === 'ERROR' && (
  <Tooltip content={job.error_message}>
    <Badge color="red">
      {job.error_message?.split('\n')[0].substring(0, 50)}...
    </Badge>
  </Tooltip>
)}
```

## 🧪 测试

### 1. 测试数据库迁移

```sql
-- 检查字段是否存在
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'JOB_TABLE'
AND COLUMN_NAME = 'error_message';

-- 测试更新错误信息
UPDATE JOB_TABLE
SET error_message = 'Test error message'
WHERE job_id = 'test-job-id';

-- 查询错误信息
SELECT job_id, job_status, error_message
FROM JOB_TABLE
WHERE job_status = 'ERROR'
LIMIT 5;
```

### 2. 测试后端 API

```bash
# 创建一个会失败的任务（用于测试）
curl -X POST http://localhost:8000/v1/create_training_job \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-key" \
  -d '{
    "job_name": "test-error-job",
    "job_type": "sft",
    "job_payload": {
      "invalid_param": "this will cause error"
    }
  }'

# 等待任务失败后，查询任务详情
curl -X POST http://localhost:8000/v1/get_training_job \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-key" \
  -d '{
    "job_id": "the-failed-job-id"
  }'
```

## 📝 注意事项

1. **字段顺序问题（重要！）**:
   - ⚠️ 使用 `ALTER TABLE ADD COLUMN` 添加的字段会在表的**末尾**
   - 实际数据库字段顺序：`..., job_payload, ts, error_message`
   - 代码中必须按照这个顺序解构：
     ```python
     _,job_id,...,job_payload,ts,error_message = results[0]
     # 注意：ts 在 error_message 之前！
     ```

2. **错误信息长度**: 错误信息字段为 TEXT 类型，最大 65,535 字节（约 64KB），足够存储详细的堆栈信息

3. **性能影响**:
   - 添加了索引，查询性能影响很小
   - 错误信息只在任务失败时写入，正常流程无影响

4. **隐私和安全**:
   - 错误信息可能包含敏感的文件路径和配置信息
   - 建议在前端展示时进行适当的过滤或只向管理员显示完整信息

5. **向后兼容**:
   - 旧的任务记录 `error_message` 将为 NULL
   - 前端应该处理 NULL 值的情况

## 🎉 效果

实施后的效果：

✅ **用户可以直接在前端看到任务失败的具体原因**
✅ **包含完整的错误堆栈，方便调试**
✅ **减少查看服务器日志的需求**
✅ **提升用户体验和问题排查效率**

## 📞 支持

如有问题，请检查：
1. 数据库是否成功添加了 `error_message` 字段
2. 后端服务是否已重启
3. API 响应中是否包含 `error_message` 字段
