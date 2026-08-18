"""断点存储(Checkpoint / Resume)。

设计目标:任意一处被中断(人工 Ctrl-C、进程崩溃、上下文超预算裁剪),都能
从上次断点无损恢复。因此断点快照必须"自包含":
  * 任务定义 + 已推进到的步数;
  * 完整上下文(目标/文件提示/记忆块/历史轮次/裁剪状态);
  * 工作区指纹(用于恢复时识别漂移);
  * 已累计的指标(恢复后继续累加)。

快照以 JSON 落盘到 checkpoints/{task_id}.json,可被 Resume 流程直接反序列化。
"""
from __future__ import annotations

import json
from pathlib import Path

from ..util import atomic_write, ensure_dir, now_iso


class CheckpointStore:
    def __init__(self, root: str | Path, enabled: bool = True):
        self.root = Path(root)
        self.enabled = enabled
        if enabled:
            ensure_dir(self.root)

    def path(self, task_id: str) -> Path:
        return self.root / f"{task_id}.json"

    def save(self, task_id: str, snapshot: dict) -> None:
        if not self.enabled:
            return
        snapshot = dict(snapshot)
        snapshot.setdefault("saved_at", now_iso())
        atomic_write(self.path(task_id), json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))

    def load(self, task_id: str) -> dict | None:
        p = self.path(task_id)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def exists(self, task_id: str) -> bool:
        return self.path(task_id).exists()

    def list_all(self) -> list[str]:
        if not self.root.exists():
            return []
        return [p.stem for p in sorted(self.root.glob("*.json"))]
