from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from src.llm import StructuredSummary, ToolCallParser
from src.runtime import AgentRuntime
from src.store import JsonStore
from src.tasks import AsyncTaskManager
from src.tools import _calculate, build_default_registry
from src.types import LLMReply, ToolCall


class FakeClient:
    def __init__(self, replies, summary: str | None = None):
        self.replies, self.requests, self.summary = list(replies), [], summary

    def chat(self, messages, tools):
        self.requests.append(messages)
        return self.replies.pop(0)

    def summarize(self, previous_summary, old_messages):
        if self.summary is None:
            raise RuntimeError("summary unavailable")
        return self.summary


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.json"

    def tearDown(self):
        self.temp.cleanup()

    def app(self, replies, *, recent_messages=10, max_turns=5, summary=None, tasks=False):
        store = JsonStore(self.path)
        manager = AsyncTaskManager(store) if tasks else None
        client = FakeClient(replies, summary)
        return AgentRuntime(client, store, build_default_registry(store, manager), max_turns=max_turns, recent_messages=recent_messages), store, client, manager

    def test_01_calculator_tool_loop(self):
        app, _, _, _ = self.app([LLMReply(tool_calls=[ToolCall("c1", "calculator", {"expression": "(2+3)*4"})]), LLMReply(content="20")])
        result = app.run("a", "s1", "calculate")
        self.assertEqual(result.answer, "20")
        self.assertEqual(result.trace[1]["result"], {"result": 20})

    def test_02_calculator_rejects_unsafe_expression(self):
        with self.assertRaises(ValueError):
            _calculate("__import__('os').system('x')")

    def test_03_calculator_divide_by_zero(self):
        with self.assertRaises(ZeroDivisionError):
            _calculate("1/0")

    def test_04_unknown_tool_becomes_error(self):
        app, _, _, _ = self.app([LLMReply(tool_calls=[ToolCall("x", "missing", {})]), LLMReply(content="handled")])
        self.assertEqual(app.run("a", "s", "bad tool").trace[1]["event"], "tool_error")

    def test_05_tool_missing_required_argument(self):
        app, _, _, _ = self.app([LLMReply(tool_calls=[ToolCall("x", "calculator", {})]), LLMReply(content="handled")])
        self.assertIn("missing required", app.run("a", "s", "calculate").trace[1]["error"])

    def test_06_todo_add_requires_task(self):
        app, _, _, _ = self.app([])
        with self.assertRaises(ValueError):
            app.tools.execute("todo", {"action": "add"}, {"user_id": "a", "session_id": "s"})

    def test_07_sessions_keep_todos_isolated(self):
        app, store, _, _ = self.app([])
        app.tools.execute("todo", {"action": "add", "task": "one"}, {"user_id": "a", "session_id": "one"})
        self.assertEqual(store.list_todos("a", "two"), [])

    def test_08_session_persists_after_restart(self):
        store = JsonStore(self.path)
        store.add_todo("a", "s", "persist")
        self.assertEqual(JsonStore(self.path).list_todos("a", "s")[0]["task"], "persist")

    def test_09_explicit_memory_crosses_sessions(self):
        app, store, client, _ = self.app([LLMReply(content="saved"), LLMReply(content="answer")])
        app.run("a", "s1", "记住我喜欢 Java 示例")
        app.run("a", "s2", "给我代码示例")
        self.assertIn("Java", client.requests[1][1]["content"])
        self.assertEqual(store.recall("b", "代码"), [])

    def test_10_non_explicit_message_is_not_memory(self):
        app, store, _, _ = self.app([LLMReply(content="ok")])
        app.run("a", "s", "我喜欢 Python")
        self.assertEqual(store.recall("a", "Python"), [])

    def test_11_memory_returns_top_k(self):
        store = JsonStore(self.path)
        for item in ["Java preference", "Python preference", "Go preference", "Rust preference"]:
            store.remember("a", item)
        self.assertEqual(len(store.recall("a", "preference", top_k=3)), 3)

    def test_12_max_turn_limit(self):
        replies = [LLMReply(tool_calls=[ToolCall(str(i), "search", {"query": "x"})]) for i in range(3)]
        app, _, _, _ = self.app(replies, max_turns=2)
        self.assertTrue(app.run("a", "s", "loop").stopped_by_limit)

    def test_13_fallback_summary_when_model_fails(self):
        app, store, _, _ = self.app([LLMReply(content="ok")] * 6, recent_messages=2)
        for i in range(6):
            app.run("a", "s", f"message {i}")
        self.assertIn("user:", store.session("a", "s")["summary"])

    def test_14_llm_structured_summary(self):
        summary = json.dumps({"goals": ["finish report"], "conclusions": [], "open_items": ["review"], "preferences": []})
        app, store, _, _ = self.app([LLMReply(content="ok")] * 6, recent_messages=2, summary=summary)
        for i in range(6):
            app.run("a", "s", f"message {i}")
        self.assertEqual(json.loads(store.session("a", "s")["summary"])["goals"], ["finish report"])

    def test_15_summary_normalises_missing_keys(self):
        value = json.loads(StructuredSummary.normalise('{"goals":["x"]}'))
        self.assertEqual(value["open_items"], [])

    def test_16_native_tool_call_parser(self):
        reply = ToolCallParser.parse({"content": None, "tool_calls": [{"id": "x", "function": {"name": "search", "arguments": '{"query":"q"}'}}]})
        self.assertEqual(reply.tool_calls[0].arguments, {"query": "q"})

    def test_17_text_tool_call_parser(self):
        reply = ToolCallParser.parse({"content": '```json\n{"tool":"search","arguments":{"query":"q"}}\n```'})
        self.assertEqual(reply.tool_calls[0].name, "search")

    def test_18_busy_session_queues_input_and_drains(self):
        app, store, _, _ = self.app([LLMReply(content="queued answer")])
        self.assertTrue(store.claim_session("a", "s", "first"))
        queued = app.run("a", "s", "second")
        self.assertEqual(queued.trace[0]["event"], "input_queued")
        store.finish_session("a", "s")
        self.assertEqual(app.drain_next("a", "s").answer, "queued answer")

    def test_19_async_task_completion_creates_event(self):
        app, store, _, manager = self.app([], tasks=True)
        item = app.tools.execute("background_search", {"query": "agent", "delay_seconds": 0.05}, {"user_id": "a", "session_id": "s"})
        time.sleep(0.12)
        self.assertEqual(store.list_events("a", "s")[0]["type"], "task_completed")
        manager.shutdown()

    def test_20_async_task_cancel_is_session_scoped(self):
        app, store, _, manager = self.app([], tasks=True)
        item = app.tools.execute("background_search", {"query": "agent", "delay_seconds": 1}, {"user_id": "a", "session_id": "s"})
        app.tools.execute("task_control", {"action": "cancel", "task_id": item["task_id"]}, {"user_id": "a", "session_id": "s"})
        time.sleep(0.12)
        self.assertEqual(store.list_events("a", "s")[0]["type"], "task_cancelled")
        with self.assertRaises(ValueError):
            app.tools.execute("task_control", {"action": "status", "task_id": item["task_id"]}, {"user_id": "b", "session_id": "s"})
        manager.shutdown()
