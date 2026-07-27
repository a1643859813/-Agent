# AI Prompt 与问题解决记录

## 1. Agent 框架使用边界

### 问题

题目禁止使用 LangGraph、OpenHands、OpenClaw 完成主流程，不确定是否可以借鉴这些框架的设计思想。

### 使用的 AI Prompt

> 我可以参考现有 Agent 框架的 Agent Loop、Session、Memory 和 Tool Registry 设计，但自行实现代码吗？

### AI 提供的建议

可以借鉴框架思想，但 Agent Loop、工具注册、模型输出解析、Session 和 Context 管理必须自行实现，不能直接调用框架的 Runtime 或预构建 Agent。

### 我的最终决定

不引入任何 Agent 框架依赖，自行实现：

- AgentRuntime
- ToolRegistry
- OutputParser
- SessionManager
- ContextManager
- TraceLogger

使用通用开发库和 HTTP Client 调用真实模型 API。

### 验证方式

检查项目依赖中不存在 LangGraph、OpenHands、OpenClaw 等 Agent 框架，并通过测试验证完整 Agent Loop。

## 2. 跨 Session 长期记忆设计

### 问题

不同 Session 需要保持对话隔离，但希望同一用户的稳定偏好可以跨窗口共享。

### 使用的 AI Prompt

> 我个人比较喜欢公共记忆，这个可以加进 Agent Runtime 吗？

### AI 提供的建议

将其设计为 User Memory，而不是所有用户共享的公共记忆：

- Session Context 按 `sessionId` 隔离；
- User Memory 按 `userId` 共享；
- 不同用户之间严格隔离；
- 只召回与当前输入相关的少量记忆。

### 我的最终决定

实现最小版长期记忆：

1. 只有用户明确说“记住……”时才写入。
2. 同一用户不同 Session 可以召回。
3. 普通 Session 聊天内容不会跨窗口共享。
4. 当前用户指令优先于历史记忆。
5. 暂不引入向量数据库，先使用标签和关键词匹配。

### 验证方式

- 用户 A 在 Session 1 保存 Java 偏好；
- 用户 A 在 Session 2 能召回该偏好；
- 用户 B 无法读取用户 A 的记忆。

## 第一版复盘与改进方向

第一版能跑通核心流程，但后续重点改进如下。

### 测试数量偏少

第一版只有 6 条测试，主要验证主流程。建议补到约 20 条，覆盖非法参数、除零、模型/API 超时、工具多轮调用、记忆冲突、摘要后关键事实保留和真实 DeepSeek 回归等。

### 长期记忆召回比较简单

当前是关键词/字符匹配，不是真正语义检索；演示可用，但复杂表达下不够准。后续可换 embedding + Top-K 检索。

### 工具参数校验不够严格

例如 `todo` 选择 `add` 时应强制要求 `task`。缺参会被 Runtime 捕获，但最好在执行前做 Schema 校验并返回更清晰的错误。

### Context 摘要是基础版

将较早消息压缩截断，无法保证一定保留最重要的信息。后续可让模型生成结构化摘要，保留目标、偏好、已完成步骤、待办等关键状态。

### JSON 存储只适合演示

`data/agent_state.json` 适合单人单进程；多人或并发运行时可能发生写入覆盖。后续应换 SQLite、Redis 或数据库。

### 没有异步任务和忙碌状态管理

第一版所有工具都是同步执行。异步搜索、长时间任务、定时复盘、用户在 busy 时继续发消息，这些可作为第二版加分项。

### 缺少真实模型回归测试

FakeClient 稳定且不花 token，但不能证明 DeepSeek 每次都能选对工具。应额外准备固定的真实 API 测试集，检查 trace 里的工具名和参数。

## 3. Prompt：反向审查我和 AI 共同形成的结论

### 使用的 AI Prompt

> 请抛开鼓励和讨好，从批判角度检查我们刚才关于 Agent 时间记忆和事件分层压缩的讨论。
>
> 重点判断：
>
> 1. 哪些现象是可信观察；
> 2. 哪些因果解释证据不足；
> 3. 哪些设计只是合理假设，尚未证明有效；
> 4. 是否存在“因为讨论得很完整，所以误以为结论已经成立”的问题；
> 5. 应该如何通过竞争假设、对照实验和评价指标验证。
>
> 不要因为方案听起来完整就默认它是正确的。

### 解决的问题

防止在与大模型连续讨论过程中形成“逻辑自洽但事实错误”的方案，明确架构设计中的证据边界。

## 4. Prompt：只解读题目，不提前生成答案

### 使用的 AI Prompt

> 请先不要直接回答下面这道架构题，而是帮我拆解它到底在考什么：
>
> “用户给 Agent 下达任务：每天早上 9 点，根据昨天聊天情况做复盘总结。你会怎么设计？”
>
> 请逐句解释题目中的隐藏要求，包括：
>
> - 自然语言任务如何转成结构化任务；
> - 为什么不能在 Session 中一直挂计时器；
> - 时区和“昨天”的时间范围；
> - 多 Session 聊天的读取范围；
> - 调度、持久化、幂等、补跑、失败重试和结果通知；
> - 面试官真正希望看到的架构能力。
>
> 当前阶段不要给完整成稿，先帮助我建立正确的问题模型。

### 解决的问题

避免在没有理解题目核心矛盾前就堆技术方案，先识别题目实际考察的任务生命周期。

## 5. Prompt：将零散技术笔记改写成可提交答案

### 使用的 AI Prompt

> 请阅读《架构题.docx》。文档中的核心技术点已经基本完整，但表达更像技术笔记和素材堆叠，主线不够清楚。
>
> 请在不改变核心方案的前提下，将其重新整理为可以直接提交的架构题答案。不要机械套固定模板，也不要继续无限补充技术名词。
>
> 重点完成：
>
> 1. 每道题先明确核心矛盾，再给总体方案；
> 2. 解释每个关键设计解决的问题和相应代价；
> 3. 保留必要流程、状态和异常情况；
> 4. 删除重复内容和过细实现；
> 5. 将每道题控制在一页左右；
> 6. 表达像能够理解并落地 Agent Runtime 的实习生，而不是专家论文；
> 7. 对外部产品只描述公开能力，不编造厂商内部实现；
> 8. 最终直接输出整理后的答案正文，不输出修改过程。
>
> 允许根据题目难度自行调整结构，不要求所有答案格式完全一致。

### 解决的问题

将 AI 生成但较为零散的内容，进一步转化为逻辑明确、篇幅适中、能够经受追问的正式答案。

## 6. 第二版 Runtime 能力迭代

### 问题

第一版已经能完成基础 Agent Loop，但 Context 压缩、异步工具、Session busy 状态和真实模型验证还不够完整。

### 使用的 AI Prompt

> 用模型生成结构化摘要，保留目标、结论、未完成事项，扩充到约 20 条；加真实 DeepSeek 回归测试，增加异步任务、任务取消、busy 状态队列，这样做第二版给我看。

### AI 提供的建议

- 历史压缩优先生成结构化摘要，保留目标、结论、未完成事项和用户偏好；
- 使用 FakeClient 进行稳定、零成本的离线测试；
- 额外保留少量真实 DeepSeek 回归测试，验证模型是否实际选择正确工具；
- 同一 Session 在 busy 时排队，不允许并发修改同一份 Context；
- 异步工具返回 `taskId`，完成、失败或取消后写入 Session 事件；
- 工具取消采用协作式取消，不强制终止正在运行的线程。

### 我的最终决定

在不改变第一版核心 Agent Loop 的前提下，增加：

- `structured summary`，并在模型摘要失败时降级为基础文本摘要；
- `idle / busy` Session 状态和 FIFO 消息队列；
- `background_search` 和 `task_control` 两个异步工具；
- `taskId`、`sessionId`、`runId`、`toolCallId` 作为异步结果归属的设计原则；
- 离线测试与真实 API 回归测试分离。

### 验证方式

- 历史超过阈值后，验证 Session 中产生结构化摘要；
- Session busy 时，新消息进入 `pending_inputs` 队列；
- 异步任务完成后，验证所属 Session 收到 `task_completed` 事件；
- 取消任务后，验证任务进入 `cancelled`；
- 真实 DeepSeek 回归测试默认跳过，只有显式开启环境变量后才调用 API。

## 7. Context 动态组装，而不是手工拼接 Prompt

### 问题

架构设计中提出了 System Prompt、任务目标、用户记忆、摘要、最近上下文等内容，但不确定这些信息是否应该直接写进一个固定 Prompt。

### 使用的 AI Prompt

> System Prompt、当前任务目标与约束、用户当前问题、最近少量有效上下文、已完成的轻量解析结果，比如这样的一部分，你该怎么做呢，不能直接粘贴到里面。

### AI 提供的建议

固定规则与动态状态应分开：

- 固定规则写入 System Prompt；
- 用户长期记忆、Session 摘要、最近消息由 Runtime 在每轮调用前动态读取；
- 当前用户输入必须保持为最后的 user message；
- 工具结果使用 tool message 回传；
- 不把所有历史都塞入 Prompt，而是在 Token 预算内按优先级组装。

### 我的最终决定

当前实现由 `runtime._context()` 在每轮模型调用前动态构造 Context：

```text
System Prompt
+ Relevant User Memory
+ Structured Session Summary
+ Recent Messages
```

原始聊天历史仍保存在 Session 中，不直接等同于模型 Context。当前任务状态、输入解析结果等属于后续可扩展的动态 Context 字段，但不为了笔试 Demo 过早加入复杂任务系统。

### 验证方式

- 用户明确写入的长期记忆能在同一 `userId` 的其他 Session 中召回；
- 历史过长后，旧消息被压缩为摘要，最近消息仍保留原文；
- Trace 中记录每轮 `message_count`，可观察实际发送给模型的 Context 规模；
- 测试验证摘要生成和降级逻辑。

## 8. 将测试从“能跑通”扩展为回归测试矩阵

### 问题

第一版只有 6 条测试，主要覆盖主流程，无法证明工具安全、参数校验、Memory 隔离和异步边界都可靠。

### 使用的 AI Prompt

> 测试用例能再帮我补 80 条吗，凑够 100 条。

### AI 提供的建议

- calculator 的合法表达式和非法表达式；
- 工具参数缺失、未知工具、非法枚举值；
- 原生 function calling 与文本 JSON 工具调用解析；
- Todo 在不同 `userId`、`sessionId` 下的隔离；
- 长期记忆跨 Session 召回、跨用户隔离、去重；
- 结构化摘要 JSON 的补全和异常降级；
- Session 默认字段和旧数据迁移；
- 异步任务完成、取消和事件清理。

### 我的最终决定

保留原有 20 条核心 Runtime 测试，新增 80 条确定性回归测试，使离线测试达到 100 条；另外保留 3 条默认跳过的真实 DeepSeek 回归测试。

真实 API 测试仅验证：

- 不需要工具时模型直接回答；
- 计算问题选择 `calculator`；
- 待办问题选择 `todo`。

### 验证方式

运行：

```powershell
D:\anaconda3\python.exe -m unittest discover -s tests -v
```

结果为：

```text
Ran 103 tests
OK (skipped=3)
```

其中 100 条为离线测试，3 条为默认跳过的真实 DeepSeek 回归测试。

## 9. 通过测试发现并修复 Python 类型边界问题

### 问题

`calculator` 工具只允许数学数字，但需要确认 Python 的类型判断是否会接受不应该被当作数字的值。

### 使用的 AI Prompt

> 测试用例能再帮我补 80 条吗，凑够 100 条。

### AI 提供的建议

在增加非法表达式测试时，加入 `True`、函数调用、变量引用、列表、字典、比较表达式等非预期输入，验证 AST 白名单是否真正安全。

### 我的最终决定

测试发现 Python 中 `bool` 是 `int` 的子类。因此原先的：

```python
isinstance(value, (int, float))
```

会把 `True` 当作数字接受。我在 calculator 的 AST 常量判断中增加：

```python
and not isinstance(value, bool)
```

明确拒绝 `True` 和 `False`。

### 验证方式

新增非法表达式测试：

```text
True
1//2
2**3
abs(1)
__import__('os')
x+1
[1, 2]
{'x': 1}
```

验证 calculator 只允许加、减、乘、除、括号和真正的 `int` / `float` 常量。

## 10. Session 数据版本兼容与懒迁移

### 问题

第二版新增了 `status`、`pending_inputs`、`events` 字段，但第一版已经保存到 JSON 中的旧 Session 没有这些字段。

### 使用的 AI Prompt

> 那为什么不直接写到 `session = self.data['sessions'].setdefault(key, {...})` 这个里面呢。

### AI 提供的建议

新建 Session 时，应直接使用完整默认结构；但外层 `setdefault(key, {...})` 只决定整个 Session 是否存在，不会自动给已经存在的旧 Session 深度补齐字段。

因此需要两层处理：

- 新 Session：创建时直接包含完整字段；
- 旧 Session：读取时使用内部 `setdefault` 补齐缺失字段。

### 我的最终决定

采用读取时的懒迁移策略：

```python
session.setdefault("status", "idle")
session.setdefault("pending_inputs", [])
session.setdefault("events", [])
```

已有字段保持原值，不覆盖；缺失字段补上默认值。补齐后的 Session 会在正常保存流程中写回本地 JSON。

### 验证方式

构造第一版旧 Session 数据：

```json
{
  "user_id": "u",
  "session_id": "s",
  "summary": "",
  "messages": []
}
```

读取后验证自动补齐：

- `status`
- `pending_inputs`
- `events`

同时验证已有字段不会被覆盖。
