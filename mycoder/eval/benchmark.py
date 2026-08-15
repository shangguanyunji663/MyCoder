"""Benchmark 数据集加载。

12 个固定任务按评测层打标签:regression(4)/ context(3)/ memory(4)/ resume(1)。
数据集以 JSON 落盘于 benchmarks/tasks.json,加载后可确定性重放 —— 这是
"确定性、可复现评测"的数据底座。
"""
from __future__ import annotations

import json
from pathlib import Path

_DEFAULT = Path(__file__).resolve().parent.parent.parent / "benchmarks" / "tasks.json"


def load_benchmarks(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else _DEFAULT
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return list(data.get("tasks", []))
    return list(data)


def by_layer(tasks: list[dict], layer: str) -> list[dict]:
    return [t for t in tasks if t.get("layer") == layer]