"""用 Ollama 跑 MyCoder Layer 6 真实任务评测。

示例:
    python examples/real_model_demo.py
    MYCODER_MODEL=qwen3.5:2b python examples/real_model_demo.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mycoder.config import Config
from mycoder.eval.real import RealTaskRunner


def main() -> int:
    cfg = Config.load(os.getenv("MYCODER_CONFIG")) if os.getenv("MYCODER_CONFIG") else Config()
    cfg.set("model.backend", "local_openai")
    cfg.set("model.local_openai.base_url", os.getenv("MYCODER_BASE_URL", "http://127.0.0.1:11434/v1"))
    cfg.set("model.local_openai.api_key", os.getenv("MYCODER_API_KEY", "ollama"))
    cfg.set("model.local_openai.model", os.getenv("MYCODER_MODEL", "qwen3.5:2b"))
    cfg.set("model.local_openai.timeout_seconds", int(os.getenv("MYCODER_TIMEOUT", "300")))
    cfg.set("eval.real.tasks", os.getenv("MYCODER_REAL_TASKS", "benchmarks/real_tasks.json"))
    report = RealTaskRunner(cfg, output_dir=os.getenv("MYCODER_REAL_OUTPUT", ".mycoder/real")).run()
    print(report["summary"])
    for detail in report.get("details", []):
        print("-", detail)
    print("报告:", Path(os.getenv("MYCODER_REAL_OUTPUT", ".mycoder/real")) / "real_report.json")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
