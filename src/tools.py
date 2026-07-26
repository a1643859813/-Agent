from __future__ import annotations

import ast
import operator
from dataclasses import dataclass
from typing import Any, Callable

from .store import JsonStore
from .tasks import AsyncTaskManager, delayed_search


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any], dict[str, str]], Any]

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}

    def validate(self, args: dict[str, Any]) -> None:
        # 在执行函数前拦截缺少必填项和 enum 非法值，错误可回传给模型修正。
        if not isinstance(args, dict):
            raise ValueError("tool arguments must be an object")
        for field in self.parameters.get("required", []):
            if field not in args or args[field] in (None, ""):
                raise ValueError(f"missing required argument: {field}")
        for field, spec in self.parameters.get("properties", {}).items():
            if field in args and "enum" in spec and args[field] not in spec["enum"]:
                raise ValueError(f"invalid {field}: {args[field]}")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def execute(self, name: str, args: dict[str, Any], context: dict[str, str]) -> Any:
        if name not in self._tools:
            raise ValueError(f"unknown tool: {name}")
        tool = self._tools[name]
        tool.validate(args)
        return tool.handler(args, context)


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.USub: operator.neg}


def _calculate(expression: str) -> float:
    # AST 白名单代替 eval，禁止导入模块、属性访问和任意代码执行。
    def visit(node: ast.AST) -> float:
        # bool is a subclass of int in Python, but True/False are not valid calculator numbers.
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](visit(node.operand))
        raise ValueError("only +, -, *, / and parentheses are allowed")
    return visit(ast.parse(expression, mode="eval").body)


def build_default_registry(store: JsonStore, task_manager: AsyncTaskManager | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(Tool("calculator", "Evaluate a basic arithmetic expression.", {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}, lambda a, _: {"result": _calculate(a["expression"]) }))
    registry.register(Tool("search", "Search a mock knowledge base.", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}, lambda a, _: {"query": a["query"], "results": [f"Mock result for: {a['query']}"]}))

    def todo(args: dict[str, Any], ctx: dict[str, str]) -> Any:
        if args["action"] == "add":
            if not args.get("task"):
                raise ValueError("task is required when action is add")
            return store.add_todo(ctx["user_id"], ctx["session_id"], args["task"])
        return store.list_todos(ctx["user_id"], ctx["session_id"])
    registry.register(Tool("todo", "Add or list todos belonging to the current session.", {"type": "object", "properties": {"action": {"type": "string", "enum": ["add", "list"]}, "task": {"type": "string"}}, "required": ["action"]}, todo))

    if task_manager:
        # 只有传入任务管理器时才暴露异步工具，保持第一版核心的最小性。
        def background_search(args: dict[str, Any], ctx: dict[str, str]) -> Any:
            delay = float(args.get("delay_seconds", 0.2))
            return task_manager.submit(ctx["user_id"], ctx["session_id"], "background_search", lambda cancel: delayed_search(args["query"], delay, cancel))
        registry.register(Tool("background_search", "Start an asynchronous mock search; it returns a task id immediately.", {"type": "object", "properties": {"query": {"type": "string"}, "delay_seconds": {"type": "number"}}, "required": ["query"]}, background_search))

        def task_control(args: dict[str, Any], ctx: dict[str, str]) -> Any:
            if args["action"] == "cancel":
                return task_manager.cancel(args["task_id"], ctx["user_id"], ctx["session_id"])
            return task_manager.status(args["task_id"], ctx["user_id"], ctx["session_id"])
        registry.register(Tool("task_control", "Check or cancel an asynchronous task in the current session.", {"type": "object", "properties": {"action": {"type": "string", "enum": ["status", "cancel"]}, "task_id": {"type": "string"}}, "required": ["action", "task_id"]}, task_control))
    return registry
