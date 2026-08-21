"""Benchmark 数据集加载。

任务按评测层打标签(regression / context / memory / resume),数据底座由两部分组成:
  * benchmarks/tasks.json            —— 手写核心任务(含负例/边界/场景标注);
  * benchmarks/tasks.generated.json  —— benchmarks/generators.py 固定 seed 生成后冻结。
默认加载时两者合并(生成的文件不存在则跳过);显式传入单个路径则只加载该文件
(向后兼容)。数据确定性落盘 => 加载后可确定性重放,这是可复现评测的数据底座。
"""
from __future__ import annotations

import json
from pathlib import Path

_BENCH_DIR = Path(__file__).resolve().parent.parent.parent / "benchmarks"
_DEFAULT = _BENCH_DIR / "tasks.json"
_GENERATED = _BENCH_DIR / "tasks.generated.json"


def load_benchmarks(path: str | Path | list[str | Path] | None = None) -> list[dict]:
    if path is None:
        paths = [p for p in (_DEFAULT, _GENERATED) if p.exists()]
    elif isinstance(path, (list, tuple)):
        paths = [Path(p) for p in path]
    else:
        paths = [Path(path)]
    tasks: list[dict] = []
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        tasks.extend(data.get("tasks", []) if isinstance(data, dict) else data)
    return tasks


def by_layer(tasks: list[dict], layer: str) -> list[dict]:
    return [t for t in tasks if t.get("layer") == layer]
