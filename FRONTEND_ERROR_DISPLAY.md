# 前端错误信息展示

## 📋 概述

在任务详情页面添加了 Flashbar 组件，用于显示任务执行失败时的详细错误信息。

## ✨ 功能特性

### 1. **自动显示错误信息**

当满足以下条件时，会自动显示错误 Flashbar：
- 任务状态为 `ERROR`
- `error_message` 字段不为空
- 在只读模式下（查看任务详情时）

### 2. **可展开的错误详情**

错误信息使用 ExpandableSection 组件包裹，用户可以：
- 默认看到错误摘要标题："Job Execution Failed"
- 点击展开查看完整的错误信息
- 错误信息以代码格式显示，保留原始格式

### 3. **样式特性**

- ❌ **红色错误 Flashbar**：醒目的错误提示
- 📝 **代码格式显示**：使用等宽字体，保留换行和空格
- 📏 **最大高度限制**：400px，超出部分可滚动
- 🔍 **自动换行**：长文本自动换行，不会横向溢出

## 🎨 显示效果

### 正常任务
```
[任务配置信息面板]
[输出路径]
[日志面板]
```

### 失败任务
```
┌─────────────────────────────────────────┐
│ ❌ Job Execution Failed                │
│ ▶ View detailed error information       │  ← 可点击展开
└─────────────────────────────────────────┘

[任务配置信息面板]
[输出路径]
[日志面板]
```

### 展开后
```
┌─────────────────────────────────────────┐
│ ❌ Job Execution Failed                │
│ ▼ View detailed error information       │
│ ┌─────────────────────────────────────┐ │
│ │ Unexpected error in processing job: │ │
│ │ Error Type: RuntimeError            │ │
│ │ Error Message: CUDA out of memory   │ │
│ │                                     │ │
│ │ Full Traceback:                     │ │
│ │   File "main.py", line 37          │ │
│ │     job.transition(...)             │ │
│ │   ...                               │ │
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

## 📝 代码实现

### 修改的文件

**文件**: `src/pages/jobs/create-job/components/form.jsx`

### 关键代码

```jsx
{/* Display error message if job status is ERROR and error_message exists */}
{readOnly && data?.job_status === 'ERROR' && data?.error_message && (
  <Flashbar
    items={[
      {
        type: "error",
        dismissible: false,
        header: "Job Execution Failed",
        content: (
          <ExpandableSection
            headerText="View detailed error information"
            variant="footer"
          >
            <pre style={{
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              backgroundColor: '#fff',
              padding: '12px',
              borderRadius: '4px',
              border: '1px solid #d5dbdb',
              maxHeight: '400px',
              overflow: 'auto',
              fontSize: '12px',
              fontFamily: 'Monaco, Menlo, "Courier New", monospace',
              margin: 0
            }}>
              {data.error_message}
            </pre>
          </ExpandableSection>
        ),
        id: "error-message"
      }
    ]}
  />
)}
```

## 🔍 错误信息格式

后端返回的错误信息格式：

```
Unexpected error in processing job {job_id}:
Error Type: {exception_class_name}
Error Message: {exception_message}

Full Traceback:
{complete_stack_trace}
```

**示例**：
```
Unexpected error in processing job abc123:
Error Type: ValueError
Error Message: Invalid parameter 'model_name'

Full Traceback:
Traceback (most recent call last):
  File "/backend/processing_engine/main.py", line 47, in proccessing_job
    if not job.transition(JobStatus.RUNNING):
  File "/backend/processing_engine/job_state_machine.py", line 67, in run_handler
    self.train_job_exe.run()
ValueError: Invalid parameter 'model_name'
```

## 🎯 用户体验

### 优势

1. ✅ **即时反馈**：任务失败时立即在页面顶部显示错误
2. ✅ **详细信息**：完整的错误堆栈，便于调试
3. ✅ **可折叠**：默认折叠，不占用太多空间
4. ✅ **易于复制**：格式化的文本便于复制分享
5. ✅ **无需跳转**：不需要查看服务器日志

### 使用场景

**场景 1：任务配置错误**
```
Error Type: ValidationError
Error Message: Invalid instance type 'ml.g4dn.2xlarge'
```
用户可以立即知道实例类型配置错误。

**场景 2：资源不足**
```
Error Type: RuntimeError
Error Message: CUDA out of memory
```
用户可以知道需要更大的实例或调整批次大小。

**场景 3：代码错误**
```
Error Type: AttributeError
Error Message: 'NoneType' object has no attribute 'train'
```
用户可以根据堆栈跟踪定位代码问题。

## 🧪 测试

### 测试步骤

1. **创建一个会失败的任务**
   ```bash
   # 例如：使用无效的配置参数
   ```

2. **等待任务失败**
   - 任务状态变为 `ERROR`

3. **查看任务详情**
   ```
   访问：/jobs/{job_id}
   ```

4. **验证 Flashbar 显示**
   - ✅ 页面顶部显示红色错误提示
   - ✅ 点击可展开查看详细错误
   - ✅ 错误信息格式正确，可读性好

### 检查点

- [ ] Flashbar 在失败任务详情页正确显示
- [ ] 点击展开可以看到完整错误信息
- [ ] 错误信息使用等宽字体，保留格式
- [ ] 长文本自动换行，不会横向溢出
- [ ] 超过 400px 高度时出现滚动条
- [ ] 成功或运行中的任务不显示 Flashbar

## 💡 未来改进

可能的增强方向：

1. **错误分类**
   - 根据错误类型显示不同的图标和颜色
   - 配置错误 vs 运行时错误 vs 系统错误

2. **快速操作**
   - 添加"重试"按钮
   - 添加"编辑并重新提交"按钮
   - 添加"复制错误信息"按钮

3. **错误建议**
   - 根据常见错误提供解决建议
   - 链接到文档或 FAQ

4. **多语言支持**
   - 错误标题和提示的国际化

## 📞 相关文档

- 后端错误处理：`backend/ERROR_HANDLING_IMPROVEMENT.md`
- API 文档：查看 `error_message` 字段说明
- Cloudscape Design System: [Flashbar Component](https://cloudscape.design/components/flashbar/)
