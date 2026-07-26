from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMReply:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class AgentResult:
    session_id: str
    answer: str
    trace: list[dict[str, Any]]
    stopped_by_limit: bool = False

