"""记忆检索器:包装 StructuredMemory,提供面向 harness/eval 的便捷查询。"""
from __future__ import annotations

from .store import StructuredMemory


class MemoryRetriever:
    def __init__(self, memory: StructuredMemory):
        self.memory = memory

    def should_re_read(self, path: str, digest: str) -> bool:
        """是否需要真正重读:当已有与 digest 一致的摘要时返回 False。"""
        return not self.memory.has_fresh_summary(path, digest)

    def relevant_files(self, task_id: str | None = None, parent_task_id: str | None = None) -> list[str]:
        pid = parent_task_id or (self.memory.parent_of(task_id) if task_id else None)
        if pid:
            return self.memory.files_for_task(pid)
        return []