from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event, RLock
from time import sleep, time
from typing import Any, Callable
from uuid import uuid4

from .store import JsonStore


class TaskCancelled(Exception):
    pass


@dataclass
class AsyncTask:
    task_id: str
    user_id: str
    session_id: str
    name: str
    status: str
    cancel_event: Event
    future: Future | None = None
    result: Any = None


class AsyncTaskManager:
    """In-process async task demo with completion events and cooperative cancellation."""

    def __init__(self, store: JsonStore) -> None:
        self.store, self.lock = store, RLock()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="agent-task")
        self.tasks: dict[str, AsyncTask] = {}

    def submit(self, user_id: str, session_id: str, name: str, work: Callable[[Event], Any]) -> dict[str, Any]:
        # 任务立即返回 task_id，耗时 work 在线程池执行，不阻塞主 Agent Loop。
        task = AsyncTask(uuid4().hex[:10], user_id, session_id, name, "queued", Event())
        with self.lock:
            self.tasks[task.task_id] = task

        def runner() -> Any:
            task.status = "running"
            if task.cancel_event.is_set():
                raise TaskCancelled()
            return work(task.cancel_event)

        def complete(future: Future) -> None:
            # 后台任务结束后写入所属 session 的事件；下次交互可读取并通知用户。
            try:
                task.result = future.result()
                task.status = "completed"
                event = {"type": "task_completed", "task_id": task.task_id, "name": name, "result": task.result}
            except (TaskCancelled, Exception) as exc:
                task.status = "cancelled" if isinstance(exc, TaskCancelled) or task.cancel_event.is_set() else "failed"
                event = {"type": f"task_{task.status}", "task_id": task.task_id, "name": name, "error": str(exc)}
            self.store.add_event(user_id, session_id, event)

        task.future = self.executor.submit(runner)
        task.future.add_done_callback(complete)
        return {"task_id": task.task_id, "status": "queued", "message": "Task started in background; check task_control later."}

    def cancel(self, task_id: str, user_id: str, session_id: str) -> dict[str, Any]:
        # Python 不能安全强杀运行中的线程，所以采用 cancel_event 的协作式取消。
        task = self._owned(task_id, user_id, session_id)
        task.cancel_event.set()
        if task.future:
            task.future.cancel()
        return {"task_id": task_id, "status": "cancel_requested"}

    def status(self, task_id: str, user_id: str, session_id: str) -> dict[str, Any]:
        task = self._owned(task_id, user_id, session_id)
        return {"task_id": task.task_id, "name": task.name, "status": task.status, "result": task.result}

    def _owned(self, task_id: str, user_id: str, session_id: str) -> AsyncTask:
        # task_id 即使猜中，也不能跨 user/session 查询或取消。
        task = self.tasks.get(task_id)
        if not task or (task.user_id, task.session_id) != (user_id, session_id):
            raise ValueError("task not found in current session")
        return task

    def shutdown(self) -> None:
        self.executor.shutdown(wait=True)


def delayed_search(query: str, delay_seconds: float, cancel_event: Event) -> dict[str, Any]:
    # 用可取消的 mock 延迟模拟真实的长耗时网络工具。
    deadline = time() + max(0.05, min(delay_seconds, 2.0))
    while time() < deadline:
        if cancel_event.is_set():
            raise TaskCancelled()
        sleep(0.02)
    return {"query": query, "results": [f"Background mock result for: {query}"]}
