"""任务级事件总线:把 harness 的 on_event 语义事件桥接到 SSE 流。

设计要点:
  * 零依赖,仅用标准库 threading.Queue;
  * harness 在后台线程执行,通过 on_event 回调把语义事件推入【该任务】的队列;
  * SSE 端点(运行在事件循环里)用 run_in_executor 读取队列,实现实时流式追踪;
  * 事件必须带 task_id 才能正确路由;调用方(见 fastapi_server)会在注入的回调里
    补全 task_id,因此即使 harness 某些事件本身不带 task_id 也能正确归队。
"""
from __future__ import annotations

import queue
import threading

_DONE = {"type": "__done__"}


class TaskEventBus:
    """每任务一个队列的事件总线,供 SSE / 轮询消费。"""

    def __init__(self) -> None:
        self._queues: dict[str, "queue.Queue"] = {}
        self._lock = threading.Lock()

    def register(self, task_id: str) -> "queue.Queue":
        """为某任务创建事件队列;需在后台 worker 启动之前调用。"""
        with self._lock:
            q: "queue.Queue" = queue.Queue()
            self._queues[task_id] = q
            return q

    def get(self, task_id: str):
        """返回该任务的队列(若已结束/不存在则返回 None)。"""
        return self._queues.get(task_id)

    def on_event(self, event: dict) -> None:
        """harness 事件回调:按 task_id 推入对应队列。"""
        tid = event.get("task_id")
        if not tid:
            return
        q = self._queues.get(tid)
        if q is not None:
            q.put_nowait(event)

    def done(self, task_id: str) -> None:
        """worker 结束时推送哨兵事件,通知 SSE 流关闭。"""
        q = self._queues.get(task_id)
        if q is not None:
            q.put_nowait(_DONE)

    def drop(self, task_id: str) -> None:
        """移除某任务的队列(释放内存)。"""
        with self._lock:
            self._queues.pop(task_id, None)
