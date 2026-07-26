"""Optional paid regression tests. They run only when RUN_DEEPSEEK_REGRESSION=1."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from main import load_dotenv
from src.llm import DeepSeekClient
from src.runtime import AgentRuntime
from src.store import JsonStore
from src.tools import build_default_registry

load_dotenv()
RUN = os.getenv("RUN_DEEPSEEK_REGRESSION") == "1"


@unittest.skipUnless(RUN, "Set RUN_DEEPSEEK_REGRESSION=1 to call the paid DeepSeek API.")
class DeepSeekRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JsonStore(Path(self.temp.name) / "state.json")
        self.app = AgentRuntime(DeepSeekClient(), self.store, build_default_registry(self.store))

    def tearDown(self):
        self.temp.cleanup()

    def test_01_direct_reply(self):
        result = self.app.run("regression", "direct", "用一句话介绍你自己，不要调用工具。")
        self.assertTrue(result.answer)
        self.assertFalse(any(item["event"] == "tool_success" for item in result.trace))

    def test_02_calculator_selection(self):
        result = self.app.run("regression", "calculator", "必须使用 calculator 工具计算 (12+8)/2。")
        self.assertTrue(any(item.get("tool") == "calculator" and item["event"] == "tool_success" for item in result.trace))

    def test_03_todo_selection(self):
        result = self.app.run("regression", "todo", "必须使用 todo 工具添加待办：准备周报。")
        self.assertTrue(any(item.get("tool") == "todo" and item["event"] == "tool_success" for item in result.trace))
