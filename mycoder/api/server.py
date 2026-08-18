"""localhost HTTP API(标准库实现,零依赖)。

提供与 harness 交互的薄壳,便于脚本 / 前端通过 127.0.0.1 调用:
  GET  /health                  -> 服务与配置概览
  POST /run                     -> 提交任务同步执行,返回 resizable 工件的路径
  GET  /tasks/<task_id>         -> 任务状态 + 指标摘要
  GET  /artifacts/<id>/<name>   -> 下载某工件(metrics.json / report.md / trajectory.jsonl)
  GET  /memory                  -> 结构化记忆统计
  GET  /checkpoints             -> 断点列表
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from ..config import Config
from ..models import MockBackend
from ..state import TaskInput


class _HarnessPool:
    """按需装配 harness;每个 run 使用独立工作区视角(线程安全)。"""

    def __init__(self, config: Config):
        self.config = config

    def run_task(self, task_data: dict) -> dict:
        from ..agent import AgentHarness
        from ..safety import AllowAllProvider
        cfg = Config(self.config.to_dict())
        backend = MockBackend(script=task_data.get("script", []),
                              default_answer=task_data.get("answer", "任务已完成。"))
        harness = AgentHarness.build(cfg, backend=backend, approver=AllowAllProvider())
        for rel, content in (task_data.get("setup_files") or {}).items():
            harness.workspace.write_text(rel, content)
        task = TaskInput(task_id=task_data.get("task_id", "api-task"),
                         goal=task_data.get("goal", ""),
                         files_hint=task_data.get("files_hint", []),
                         follow_up_of=task_data.get("follow_up_of"))
        result = harness.run(task)
        artifacts = harness.artifacts.export(result.task_id, harness.metrics,
                                             {"status": result.status,
                                              "final_answer": result.final_answer},
                                             checkpoint_obj=harness.checkpoint.load(result.task_id))
        return {"task_id": result.task_id, "status": result.status,
                "final_answer": result.final_answer, "metrics": result.metrics,
                "artifacts": artifacts}


def make_handler(pool: _HarnessPool, config: Config):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MyCoder/0.1"

        def _send(self, code: int, obj, raw: str | None = None) -> None:
            self.send_response(code)
            body = raw if raw is not None else json.dumps(obj, ensure_ascii=False, indent=2,
                                                          default=str)
            if raw is not None:
                self.send_header("Content-Type", "application/octet-stream")
            else:
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def _json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            if not length:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def do_GET(self):
            parts = urlparse(self.path)
            seg = [s for s in parts.path.split("/") if s]
            if not seg:
                return self._send(200, {"service": "mycoder", "version": "0.1"})
            if seg[0] == "health":
                return self._send(200, {
                    "status": "ok", "model": config.model_backend,
                    "workspace": config.workspace_root,
                    "budget_tokens": config.get("context.budget_tokens"),
                })
            if seg[0] == "tasks" and len(seg) == 2:
                return self._task_status(seg[1])
            if seg[0] == "artifacts" and len(seg) == 3:
                return self._artifact(seg[1], seg[2])
            if seg[0] == "memory":
                return self._memory()
            if seg[0] == "checkpoints":
                from ..checkpoint import CheckpointStore
                cp = CheckpointStore(config.get("checkpoint.root", ".mycoder/checkpoints"),
                                     enabled=True)
                return self._send(200, {"checkpoints": cp.list_all()})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            parts = urlparse(self.path)
            seg = [s for s in parts.path.split("/") if s]
            if seg and seg[0] == "run":
                body = self._json_body()
                try:
                    out = pool.run_task(body.get("task", body))
                    out["http"] = {"history": "见 GET /artifacts/<id>/report.md"}
                    return self._send(200, out)
                except Exception as e:
                    return self._send(500, {"error": str(e)})
            return self._send(404, {"error": "not found"})

        def _task_status(self, task_id: str):
            root = Path(config.get("artifacts.root", ".mycoder/artifacts")) / task_id
            if not root.exists():
                return self._send(404, {"error": "no such task"})
            mf = root / "metrics.json"
            metrics = json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else {}
            return self._send(200, {"task_id": task_id, "metrics": metrics,
                                    "artifacts": [f.name for f in root.iterdir()]})

        def _artifact(self, task_id: str, name: str):
            root = Path(config.get("artifacts.root", ".mycoder/artifacts")) / task_id
            f = root / name
            if not f.exists():
                return self._send(404, {"error": "no such artifact"})
            return self._send(200, {}, raw=f.read_text(encoding="utf-8", errors="replace"))

        def _memory(self):
            from ..memory import StructuredMemory
            mem = StructuredMemory(config.get("memory.root", ".mycoder/memory"),
                                   enabled=config.get("memory.enabled", True))
            return self._send(200, {"stats": mem.stats(),
                                    "tasks": list(mem.tasks.keys()),
                                    "files": list(mem.files.keys())})

        def log_message(self, fmt, *args):  # 静默,避免刷屏
            pass

    return Handler


def run_server(config: Config, host: str = "127.0.0.1", port: int = 8910) -> None:
    pool = _HarnessPool(config)
    handler = make_handler(pool, config)
    srv = ThreadingHTTPServer((host, port), handler)
    print(f"[MyCoder API] listening on http://{host}:{port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[MyCoder API] stopped")
