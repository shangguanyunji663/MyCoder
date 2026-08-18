"""配置加载与合并。

设计思路:
  * 内置 DEFAULT 字典保证任何缺失字段都有安全默认值;
  * 支持 YAML / JSON 配置文件,深合并覆盖默认值;
  * Config 对象提供属性式访问(get/set),便于全项目统一读写。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - 保底:无 PyYAML 也能跑 JSON
    yaml = None


DEFAULT: dict[str, Any] = {
    "workspace": {"root": ".", "allow_absolute": False},
    "model": {
        "backend": "mock",
        "mock": {"seed": 42},
        "local_openai": {
            "base_url": "http://127.0.0.1:8080/v1",
            "api_key": "local",
            "model": "qwen2.5-coder-7b",
            "temperature": 0.0,
            "timeout_seconds": 60,
        },
    },
    "harness": {"max_steps": 30, "max_tool_calls_per_turn": 8},
    "context": {
        "budget_tokens": 4000,
        "hard_limit_tokens": 6000,
        "keep_last_turns": 6,
        "keep_last_tool_results": 8,
        "max_file_content_chars": 8000,
        "compressible_age": 3,
    },
    "memory": {
        "enabled": True,
        "root": ".mycoder/memory",
        "auto_remember_files": True,
        "followup_inject_summaries": True,
    },
    "checkpoint": {
        "enabled": True,
        "root": ".mycoder/checkpoints",
        "interval_steps": 4,
        "on_prune": True,
        "detect_drift": True,
    },
    "safety": {
        "hitl_policy": "prompt",
        "dedup_enabled": True,
        "redaction_enabled": True,
        "shell": {
            "allow_commands": [
                "echo", "ls", "dir", "pwd", "cat", "type", "find", "grep",
                "findstr", "git", "python", "python3", "mkdir", "touch",
            ],
            "deny_patterns": [
                r"rm\s+-rf", r"del\s+/[sq]", "format", "shutdown", "reboot",
                "curl", "wget", r"chmod\s+777", ":(){", r">\s*/dev",
            ],
        },
        "allow_write_outside_ext": [],
    },
    "artifacts": {"root": ".mycoder/artifacts", "redact_artifacts": True},
    "logging": {"level": "INFO", "file": ".mycoder/harness.log", "console": True},
    "api": {"host": "127.0.0.1", "port": 8910},
}


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并 override 到 base(返回新字典)。"""
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class Config:
    """可属性访问的配置对象。"""

    def __init__(self, data: dict | None = None):
        self._data: dict[str, Any] = _deep_merge(DEFAULT, data or {})

    @classmethod
    def load(cls, path: str | Path | None) -> "Config":
        """从文件加载;path 不存在时返回默认配置。"""
        if not path:
            return cls()
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"配置文件不存在: {p}")
        raw = p.read_text(encoding="utf-8")
        if p.suffix.lower() in (".yaml", ".yml"):
            if yaml is None:
                raise RuntimeError("读取 YAML 需要 PyYAML: pip install pyyaml")
            data = yaml.safe_load(raw) or {}
        else:
            data = json.loads(raw)
        return cls(data)

    # ---- 属性式访问 ----
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def to_dict(self) -> dict:
        return copy.deepcopy(self._data)

    # 常用快捷访问
    @property
    def workspace_root(self) -> str:
        return str(self.get("workspace.root", "."))

    @property
    def model_backend(self) -> str:
        return str(self.get("model.backend", "mock"))

    def __repr__(self) -> str:  # pragma: no cover
        return f"Config(model={self.model_backend!r})"