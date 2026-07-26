from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any


class JsonStore:
    """Inspectable local persistence. Every session key is scoped by user and session."""

    def __init__(self, path: str | Path = "data/agent_state.json") -> None:
        self.path = Path(path)
        self.lock = RLock()
        self.data: dict[str, Any] = {"sessions": {}, "user_memories": {}, "todos": {}}
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        #先建目录防报错，再把字典变 JSON 字符串，最后写进文件——这就是 Agent 状态的"存档"功能。
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def session(self, user_id: str, session_id: str) -> dict[str, Any]:
        # session 短期上下文的隔离边界：同一 user 的不同窗口也不会串数据。
        key = f"{user_id}:{session_id}"
        with self.lock:
            session = self.data["sessions"].setdefault(key, {"user_id": user_id, "session_id": session_id, "summary": "", "messages": []})
            # Migration defaults for data written by v1.
            session.setdefault("status", "idle")
            session.setdefault("pending_inputs", [])
            session.setdefault("events", [])
            return session

    def save_session(self, session: dict[str, Any]) -> None:
        with self.lock:
            self.data["sessions"][f"{session['user_id']}:{session['session_id']}"] = session
            self._save()

    def claim_session(self, user_id: str, session_id: str, user_input: str) -> bool:
        """Claim an idle session; otherwise persist the new message in its FIFO queue."""
        with self.lock:
            session = self.session(user_id, session_id)
            if session["status"] == "busy":
                # FIFO 队列仅保存用户输入；执行时再按当时最新 Context 调用模型。
                session["pending_inputs"].append(user_input)
                self._save()
                return False
            session["status"] = "busy"
            self._save()
            return True

    def finish_session(self, user_id: str, session_id: str) -> None:
        with self.lock:
            session = self.session(user_id, session_id)
            session["status"] = "idle"
            self._save()

    def claim_next_input(self, user_id: str, session_id: str) -> str | None:
        with self.lock:
            session = self.session(user_id, session_id)
            if session["status"] != "idle" or not session["pending_inputs"]:
                return None
            session["status"] = "busy"
            value = session["pending_inputs"].pop(0)
            self._save()
            return value

    def add_event(self, user_id: str, session_id: str, event: dict[str, Any]) -> None:
        with self.lock:
            self.session(user_id, session_id)["events"].append(event)
            self._save()

    def list_events(self, user_id: str, session_id: str, clear: bool = False) -> list[dict[str, Any]]:
        with self.lock:
            events = list(self.session(user_id, session_id)["events"])
            if clear:
                self.session(user_id, session_id)["events"] = []
                self._save()
            return events

    def remember(self, user_id: str, text: str) -> None:
        # 长期记忆只按 user_id 索引，因此可以跨 session 共享。
        with self.lock:
            memories = self.data["user_memories"].setdefault(user_id, [])
            if text not in memories:
                memories.append(text)
                self._save()

    def recall(self, user_id: str, query: str, top_k: int = 3) -> list[str]:
        # 第一/二版采用可解释的字符匹配；生产版可替换为 embedding 语义检索。
        characters = {ch.lower() for ch in query if not ch.isspace()}
        memories = self.data["user_memories"].get(user_id, [])
        ranked = sorted(memories, key=lambda item: sum(ch.lower() in characters for ch in item), reverse=True)
        return ranked[:top_k]

    def add_todo(self, user_id: str, session_id: str, task: str) -> dict[str, Any]:
        with self.lock:
            key = f"{user_id}:{session_id}"
            todos = self.data["todos"].setdefault(key, [])
            item = {"id": len(todos) + 1, "task": task, "done": False}
            todos.append(item)
            self._save()
            return item

    def list_todos(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        return self.data["todos"].get(f"{user_id}:{session_id}", [])
