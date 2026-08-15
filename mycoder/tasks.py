"""任务文件加载。

支持两种任务描述格式:
  * JSON:直接给出完整 spec(goal / files_hint / script / answer / 断言);
  * Markdown:可选 YAML frontmatter(--- 包裹)里放任务元信息,正文作为 goal。

统一返回 dict,由 CLI / eval 各自解释。"""
from __future__ import annotations

import json
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def load_task_file(path: str | Path) -> dict:
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        return json.loads(raw)
    # markdown
    data: dict = {}
    body = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            if yaml is None:
                raise RuntimeError("解析 Markdown frontmatter 需要 PyYAML")
            data = yaml.safe_load(parts[1]) or {}
            body = parts[2]
    data.setdefault("goal", body.strip())
    data.setdefault("task_id", p.stem)
    return data