# Minimal Agent Runtime（Python + DeepSeek）

一个不依赖 LangGraph、OpenHands、OpenClaw 等 Agent 框架的最小可用 Agent。Agent 的主循环、工具注册与执行、session 管理、context 组装、记忆和状态持久化均由本项目代码实现；DeepSeek 仅负责基于上下文和工具 Schema 做模型推理。

## 功能概览

- 真实 DeepSeek OpenAI-compatible Chat Completions API，默认模型为 `deepseek-v4-flash`。
- 自建 Agent Loop：用户输入 → 模型直接回答或请求工具 → 本地执行工具 → 将工具结果回传模型 → 最终回答。
- 工具注册中心：每个工具都有名称、描述和 JSON Schema；内置 `calculator`、离线 mock `search`、会话隔离的 `todo`，并支持异步 `background_search` / `task_control`。
- 用户和会话隔离：以 `(user_id, session_id)` 保存短期会话和待办，用户 A 的两个窗口互不影响。
- 显式长期记忆、最近消息窗口、结构化摘要、最大工具轮次限制和工具/模型异常处理。
- 每次请求提供结构化 trace；同一 session 忙碌时，新输入进入 FIFO 队列。
- 异步任务立即返回 `task_id`，完成、失败或取消后把事件写入所属 session；查询与取消均受 user/session 权限约束。

## 目录结构

```text
main.py                  # 命令行入口
src/
  runtime.py             # Agent Loop、context 组装、压缩和排队
  llm.py                 # DeepSeek 客户端、function-call / JSON 调用解析
  tools.py               # 工具定义、Schema 注册、参数校验与执行
  store.py               # 本地 JSON 持久化、session、memory、todo
  tasks.py               # 异步任务、完成事件和协作式取消
tests/                   # 离线测试、回归矩阵和真实 API 回归测试
data/agent_state.json    # 运行时自动生成的本地状态（不提交）
```

## 运行方式

### 1. 环境要求

- Python 3.10+。
- 可访问 DeepSeek API 的 API Key。
- 主程序只依赖 Python 标准库；如需重新生成 PDF 文档，再安装 `requirements.txt` 中的可选依赖。

### 2. 配置真实 API

复制配置示例：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，填写自己的 Key；不要提交该文件：

```dotenv
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

### 3. 启动

```powershell
python main.py
```

程序会依次询问 `user id` 和 `session id`。例如，在 `user-a/window-1` 中添加待办，在 `user-a/window-2` 中添加另一条待办，两组数据彼此隔离。输入 `/quit` 或 `/exit` 退出。

可尝试：

```text
必须使用 calculator 工具计算 (12+8)/2
添加待办：准备周报
列出我的待办
记住：我偏好 Java 示例
```

## 系统设计

完整流程图见：[Agent Runtime 架构图](docs/架构图.md)。

### Agent Runtime 与工具循环

`AgentRuntime.run()` 先占用目标 session，然后把用户消息写入该 session 的短期历史。每一轮根据当前 context 调用 `DeepSeekClient.chat()`：

1. 模型无 `tool_calls` 时，返回模型文本作为最终回答；
2. 模型有 `tool_calls` 时，Runtime 通过 `ToolRegistry` 查找工具、按 JSON Schema 做必填参数和枚举校验，并在本地执行；
3. 工具结果（或工具异常）以 `role=tool` 追加回 session；Runtime 带着结果进入下一轮，让模型决定继续调用还是回答；
4. 达到 `max_turns`（默认 5）则停止，防止错误调用形成无限循环。

API 客户端优先解析 OpenAI-compatible 原生 `tool_calls`，并兼容模型偶尔返回的 Markdown JSON 工具调用。trace 会记录模型请求、工具成功/失败、摘要策略等事件，便于录屏和排查。

### Session、并发与异步任务

状态持久化在可检查的 `data/agent_state.json` 中。session 的键是 `user_id:session_id`：

- 同一用户的不同窗口使用不同 session，短期消息、摘要和 todo 不串数据；
- session 状态为 `busy` 时，后到的用户输入只进入 `pending_inputs` FIFO 队列，当前请求结束后由 `drain_next()` 顺序处理；
- `background_search` 在后台线程运行并即时返回 `task_id`；完成事件只写入创建它的 session。`task_control` 不能跨 user/session 查询或取消任务，取消采用协作式取消信号。

## Context 与 Memory 设计

### 短期上下文与压缩

每轮模型调用都重新组装 context，顺序固定为：

```text
System Prompt
→ 与当前请求相关的长期记忆
→ 结构化 session 摘要（如有）
→ 当前 session 最近消息与工具结果
```

默认保留最近 10 条消息，因而追问仍可看到原始用户输入、助手回复和工具执行结果。消息超过 `recent_messages * 2` 时，较早部分会被压缩：优先让模型输出 JSON 结构化摘要，字段为 `goals`、`conclusions`、`open_items`、`preferences`；模型不可用或返回非法 JSON 时，降级成确定性的文本摘要。这样保留任务目标、已得结论和未完成事项，同时控制 token 增长。

### 长期 Memory：写入、召回与放置

- **写入时机**：只在用户明确表达“记住……”时写入，避免 Agent 从普通闲聊中错误抽取偏好或敏感信息。
- **隔离范围**：长期记忆以 `user_id` 为键，能跨该用户的多个 session 使用，但不会泄漏到其他用户。
- **召回时机**：每次 Agent 组装模型 context 时，使用当前用户输入对该用户记忆做字符重叠排序，取前 3 条。当前版本以可解释、易测试的关键词 Top-K 实现；生产环境可替换为 embedding 检索、重排和置信度阈值。
- **放置方式**：召回内容作为独立的 system message 放在 system prompt 之后、session 摘要之前，并显式标注“可能过时，当前用户指令优先”。这既让模型可以利用跨窗口偏好，又避免长期记忆覆盖当前请求。

## 测试

### 离线测试

不消耗 API 额度：

```powershell
python -m unittest discover -s tests -v
```

当前覆盖计算器安全性、工具参数校验、工具调用循环、session / todo 隔离、显式记忆及跨 session 召回、摘要及降级、原生和文本工具调用解析、busy 队列、异步任务和状态迁移等。真实 API 测试默认跳过。

### 真实 DeepSeek API 回归测试

会消耗少量 API 额度，仅在确认 `.env` 有有效 Key 后运行：

```powershell
$env:RUN_DEEPSEEK_REGRESSION='1'
python -m unittest discover -s tests -p test_deepseek_regression.py -v
```

该组验证真实模型的直接回答、`calculator` 选择和 `todo` 选择。2026-07-26 已使用 `deepseek-v4-flash` 运行通过 3/3。

## 安全与提交说明

- 不提交 `.env`、API Key、`data/agent_state.json`、`__pycache__` 或临时文件。
- `calculator` 使用 AST 白名单，而非 `eval`，只允许四则运算、括号和负号。
- 搜索工具为 mock 数据，方便离线测试；真实 LLM API 仍用于 Agent 决策与 function calling。
