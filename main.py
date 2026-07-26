from __future__ import annotations

import os
from pathlib import Path

from src.llm import DeepSeekClient
from src.runtime import AgentRuntime
from src.store import JsonStore
from src.tasks import AsyncTaskManager
from src.tools import build_default_registry


def load_dotenv(path: str = ".env") -> None:
    # 不依赖第三方 dotenv 包，直接把 .env 的键值写入当前进程环境。
    if not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


if __name__ == "__main__":
    # 1) 读取 DeepSeek 配置；2) 装配存储、异步任务、工具和 Runtime。
    load_dotenv()
    store = JsonStore()
    task_manager = AsyncTaskManager(store)
    runtime = AgentRuntime(DeepSeekClient(), store, build_default_registry(store, task_manager))
    print("Minimal Agent. Type /quit to exit. Sessions are independent by ID.")
    user_id = input("user id [user-a]: ").strip() or "user-a"
    session_id = input("session id [window-1]: ").strip() or "window-1"
    while True:
        # CLI 只负责收发消息；真正的 Agent 决策都在 runtime.run() 中。
        query = input("you> ").strip()
        if query in {"/quit", "/exit"}:
            break
        result = runtime.run(user_id, session_id, query)
        print("agent>", result.answer)
        print("trace>", result.trace)
        events = store.list_events(user_id, session_id, clear=True)
        if events:
            print("events>", events)
        while True:
            # 当前请求完成后，按 FIFO 顺序处理该 session 在 busy 状态下收到的消息。
            queued = runtime.drain_next(user_id, session_id)
            if queued is None:
                break
            print("agent (queued)>", queued.answer)
    task_manager.shutdown()
