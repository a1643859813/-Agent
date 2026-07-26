from __future__ import annotations

import json
import re
from threading import RLock
from typing import Any

from .store import JsonStore
from .tools import ToolRegistry
from .types import AgentResult

SYSTEM_PROMPT = """You are a concise helpful assistant. Use a tool whenever it is needed. Do not invent tool results. If a tool result answers the request, explain it to the user."""


class AgentRuntime:
    def __init__(self, client: Any, store: JsonStore, tools: ToolRegistry, max_turns: int = 5, recent_messages: int = 10) -> None:
        self.client, self.store, self.tools = client, store, tools
        self.max_turns, self.recent_messages = max_turns, recent_messages
        self.lock = RLock()

    def run(self, user_id: str, session_id: str, user_input: str) -> AgentResult:
        # 先占用 session。若已被另一个请求占用，则只入队，不并发修改上下文。
        if not self.store.claim_session(user_id, session_id, user_input):
            return AgentResult(session_id, "当前 session 正在处理上一条消息，新消息已进入队列。", [{"event": "input_queued", "input": user_input}])
        return self._run_claimed(user_id, session_id, user_input)

    def drain_next(self, user_id: str, session_id: str) -> AgentResult | None:
        """Process one queued user input after the active request has completed."""
        queued = self.store.claim_next_input(user_id, session_id)
        return self._run_claimed(user_id, session_id, queued) if queued is not None else None

    def _run_claimed(self, user_id: str, session_id: str, user_input: str) -> AgentResult:
        session = self.store.session(user_id, session_id)
        trace: list[dict[str, Any]] = []
        try:
            # “记住……”属于显式写入长期记忆，避免自动提取造成错误记忆。
            remembered = self._explicit_memory(user_id, user_input)
            session["messages"].append({"role": "user", "content": user_input})
            self._compress(session, trace)

            for turn in range(1, self.max_turns + 1):
                # 每轮都重新组装 Context：记忆/摘要/最近消息会影响模型下一步决策。
                messages = self._context(session, user_id, user_input)
                trace.append({"event": "llm_request", "turn": turn, "message_count": len(messages)})
                try:
                    reply = self.client.chat(messages, self.tools.schemas())
                except Exception as exc:
                    return AgentResult(session_id, f"模型调用失败：{exc}", trace + [{"event": "llm_error", "error": str(exc)}])

                if not reply.tool_calls:
                    # 没有工具调用即为最终回答，结束本轮 Agent Loop。
                    answer = reply.content or (f"我已记住：{remembered}" if remembered else "已完成。")
                    session["messages"].append({"role": "assistant", "content": answer})
                    return AgentResult(session_id, answer, trace)

                session["messages"].append({"role": "assistant", "content": reply.content or "", "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)}} for c in reply.tool_calls]})
                for call in reply.tool_calls:
                    try:
                        # 工具异常会转成 tool result 回传给模型，而不是让整个 Agent 崩溃。
                        result: Any = self.tools.execute(call.name, call.arguments, {"user_id": user_id, "session_id": session_id})
                        trace.append({"event": "tool_success", "tool": call.name, "arguments": call.arguments, "result": result})
                    except Exception as exc:
                        result = {"error": str(exc)}
                        trace.append({"event": "tool_error", "tool": call.name, "error": str(exc)})
                    session["messages"].append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})
                self._compress(session, trace)

            return AgentResult(session_id, "工具调用轮次已达到上限，请缩小问题后重试。", trace, stopped_by_limit=True)
        finally:
            # 无论成功、失败还是达到轮次上限，都释放 session，保证排队消息可继续执行。
            self.store.save_session(session)
            self.store.finish_session(user_id, session_id)

    def _context(self, session: dict[str, Any], user_id: str, query: str) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        memories = self.store.recall(user_id, query)
        if memories:
            messages.append({"role": "system", "content": "Relevant user memory (may be stale; current user instruction wins):\n- " + "\n- ".join(memories)})
        if session["summary"]:
            # 摘要是旧历史的压缩表示，最近消息仍保留原文以支持自然追问。
            messages.append({"role": "system", "content": "Structured session summary:\n" + session["summary"]})
        messages.extend(session["messages"][-self.recent_messages:])
        return messages

    def _compress(self, session: dict[str, Any], trace: list[dict[str, Any]]) -> None:
        messages = session["messages"]
        if len(messages) <= self.recent_messages * 2:
            return
        old, session["messages"] = messages[:-self.recent_messages], messages[-self.recent_messages:]
        try:
            # 第二版优先让模型输出四类结构化状态，避免普通摘要遗漏“未完成事项”。
            session["summary"] = self.client.summarize(session["summary"], old)
            trace.append({"event": "structured_summary", "strategy": "llm_json"})
        except Exception as exc:
            # API 不可用或 JSON 不合法时，使用确定性文本摘要作为兜底。
            facts = [f"{item['role']}: {item['content'][:160]}" for item in old if item["role"] in {"user", "assistant"} and item.get("content")]
            session["summary"] = (session["summary"] + "\n" + "\n".join(facts))[-2000:]
            trace.append({"event": "structured_summary", "strategy": "fallback", "error": str(exc)})

    def _explicit_memory(self, user_id: str, text: str) -> str | None:
        match = re.search(r"(?:请)?记住[：:,，\s]*(.+)", text)
        if match:
            memory = match.group(1).strip("。！! ")
            if memory:
                self.store.remember(user_id, memory)
                return memory
        return None
