"""80 additional deterministic regression cases.

Together with test_runtime.py this keeps 100 offline tests.  Each generated
test has a distinct name, so unittest reports every scenario separately.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.llm import StructuredSummary, ToolCallParser
from src.store import JsonStore
from src.tools import _calculate, build_default_registry


class RegressionMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = JsonStore(Path(self.temp.name) / "state.json")
        self.tools = build_default_registry(self.store)

    def tearDown(self) -> None:
        self.temp.cleanup()


def add_test(name, function):
    """Register a separate unittest method so every data row is a test case."""
    setattr(RegressionMatrixTests, name, function)


# 24 calculator success cases: allowed arithmetic and parentheses only.
VALID_EXPRESSIONS = [
    ("1+1", 2), ("2*3", 6), ("10-7", 3), ("8/2", 4),
    ("(2+3)*4", 20), ("-5+8", 3), ("1.5+2.5", 4), ("3*(4-2)", 6),
    ("(1+2)*(3+4)", 21), ("9/4", 2.25), ("-(-3)", 3), ("0*999", 0),
    ("100/25+1", 5), ("7-10", -3), ("(8/2)/2", 2), ("2*(3*(4+1))", 30),
    (".5+0.5", 1), ("12+(3*4)", 24), ("(6-1)*(2+2)", 20), ("20/5-3", 1),
    ("4*(2-5)", -12), ("(9+1)/2", 5), ("1+(2+(3+4))", 10), ("3.0*2", 6),
]

for index, (expression, expected) in enumerate(VALID_EXPRESSIONS, 1):
    def test(self, expression=expression, expected=expected):
        self.assertEqual(_calculate(expression), expected)
    add_test(f"test_21_calculator_valid_{index:02}", test)


# 16 rejected expressions: the calculator must not become a general code executor.
INVALID_EXPRESSIONS = [
    "1//2", "2**3", "abs(1)", "__import__('os')", "x+1", "[1,2]",
    "{'x':1}", "True", "1<2", "lambda: 1", "(1,2)", "'text'",
    "", "1;2", "1 and 2", "~1",
]

for index, expression in enumerate(INVALID_EXPRESSIONS, 1):
    def test(self, expression=expression):
        with self.assertRaises(Exception):
            _calculate(expression)
    add_test(f"test_45_calculator_rejects_{index:02}", test)


# 12 parser cases: native function calling and Markdown JSON fallback.
NATIVE_CALLS = [
    ("calculator", {"expression": "1+1"}), ("search", {"query": "agent"}),
    ("todo", {"action": "list"}), ("todo", {"action": "add", "task": "report"}),
    ("background_search", {"query": "memory"}), ("task_control", {"action": "status", "task_id": "t1"}),
]
for index, (tool, arguments) in enumerate(NATIVE_CALLS, 1):
    def test(self, tool=tool, arguments=arguments):
        reply = ToolCallParser.parse({"content": None, "tool_calls": [{"id": "id1", "function": {"name": tool, "arguments": json.dumps(arguments)}}]})
        self.assertEqual((reply.tool_calls[0].name, reply.tool_calls[0].arguments), (tool, arguments))
    add_test(f"test_61_native_parser_{index:02}", test)

TEXT_CALLS = [
    ("calculator", {"expression": "2+2"}), ("search", {"query": "runtime"}),
    ("todo", {"action": "list"}), ("todo", {"action": "add", "task": "read"}),
    ("background_search", {"query": "context"}), ("task_control", {"action": "cancel", "task_id": "t2"}),
]
for index, (tool, arguments) in enumerate(TEXT_CALLS, 1):
    def test(self, tool=tool, arguments=arguments):
        content = "```json\n" + json.dumps({"tool": tool, "arguments": arguments}) + "\n```"
        reply = ToolCallParser.parse({"content": content})
        self.assertEqual((reply.tool_calls[0].name, reply.tool_calls[0].arguments), (tool, arguments))
    add_test(f"test_67_text_parser_{index:02}", test)


# 8 todo/session isolation cases.
TODO_CASES = [
    ("u1", "s1", "task-1", "u1", "s1", 1), ("u1", "s1", "task-2", "u1", "s2", 0),
    ("u1", "s1", "task-3", "u2", "s1", 0), ("u2", "s2", "task-4", "u2", "s2", 1),
    ("u2", "s2", "task-5", "u2", "s3", 0), ("u3", "s1", "task-6", "u3", "s1", 1),
    ("u3", "s1", "task-7", "u4", "s1", 0), ("u4", "s4", "task-8", "u4", "s4", 1),
]
for index, (owner, session, task, reader, reader_session, expected_count) in enumerate(TODO_CASES, 1):
    def test(self, owner=owner, session=session, task=task, reader=reader, reader_session=reader_session, expected_count=expected_count):
        self.tools.execute("todo", {"action": "add", "task": task}, {"user_id": owner, "session_id": session})
        self.assertEqual(len(self.store.list_todos(reader, reader_session)), expected_count)
    add_test(f"test_73_todo_session_scope_{index:02}", test)


# 8 memory cases: user scope, deduplication and Top K limits.
MEMORY_CASES = [
    ("u1", "Java preference", "u1", "Java", True), ("u1", "Python preference", "u2", "Python", False),
    ("u2", "Agent runtime goal", "u2", "runtime", True), ("u3", "Morning reminder", "u3", "reminder", True),
    ("u3", "Database preference", "u4", "database", False), ("u4", "Use concise answers", "u4", "concise", True),
    ("u5", "Prefer tests first", "u5", "tests", True), ("u6", "Timezone Asia Shanghai", "u6", "timezone", True),
]
for index, (owner, memory, reader, query, should_find) in enumerate(MEMORY_CASES, 1):
    def test(self, owner=owner, memory=memory, reader=reader, query=query, should_find=should_find):
        self.store.remember(owner, memory)
        found = memory in self.store.recall(reader, query)
        self.assertEqual(found, should_find)
    add_test(f"test_81_memory_scope_{index:02}", test)


# 4 schema/validation cases and 4 structured-summary cases complete the 80-case matrix.
VALIDATION_CASES = [
    ("calculator", {}, "missing required"), ("search", {}, "missing required"),
    ("todo", {"action": "wrong"}, "invalid action"), ("todo", {"action": "add"}, "task is required"),
]
for index, (tool, arguments, expected_text) in enumerate(VALIDATION_CASES, 1):
    def test(self, tool=tool, arguments=arguments, expected_text=expected_text):
        with self.assertRaises(ValueError) as error:
            self.tools.execute(tool, arguments, {"user_id": "u", "session_id": "s"})
        self.assertIn(expected_text, str(error.exception))
    add_test(f"test_89_tool_validation_{index:02}", test)

SUMMARY_CASES = [
    ("{}", {"goals": [], "conclusions": [], "open_items": [], "preferences": []}),
    ('{"goals":["g"]}', {"goals": ["g"], "conclusions": [], "open_items": [], "preferences": []}),
    ('{"conclusions":["c"],"open_items":["o"]}', {"goals": [], "conclusions": ["c"], "open_items": ["o"], "preferences": []}),
    ('```json\n{"preferences":["Java"]}\n```', {"goals": [], "conclusions": [], "open_items": [], "preferences": ["Java"]}),
]
for index, (raw, expected) in enumerate(SUMMARY_CASES, 1):
    def test(self, raw=raw, expected=expected):
        self.assertEqual(json.loads(StructuredSummary.normalise(raw)), expected)
    add_test(f"test_93_structured_summary_{index:02}", test)


# Four Store lifecycle cases bring this matrix to 80 new cases / 100 offline cases total.
def test_session_new_defaults(self):
    session = self.store.session("u", "s")
    self.assertEqual((session["status"], session["pending_inputs"], session["events"]), ("idle", [], []))


def test_session_old_data_migration(self):
    self.store.data["sessions"]["u:s"] = {"user_id": "u", "session_id": "s", "summary": "", "messages": []}
    session = self.store.session("u", "s")
    self.assertIn("status", session)


def test_memory_deduplication(self):
    self.store.remember("u", "Java preference")
    self.store.remember("u", "Java preference")
    self.assertEqual(self.store.recall("u", "Java"), ["Java preference"])


def test_events_can_be_cleared_after_reading(self):
    self.store.add_event("u", "s", {"type": "done"})
    self.assertEqual(len(self.store.list_events("u", "s", clear=True)), 1)
    self.assertEqual(self.store.list_events("u", "s"), [])


add_test("test_97_session_new_defaults", test_session_new_defaults)
add_test("test_98_session_old_data_migration", test_session_old_data_migration)
add_test("test_99_memory_deduplication", test_memory_deduplication)
add_test("test_100_events_clear_after_read", test_events_can_be_cleared_after_reading)
