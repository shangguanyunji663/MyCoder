"""FastAPI + SSE 实现(可选依赖 fastapi/uvicorn)。

接口契约与标准库 server.py 基本一致,额外提供:
  POST /api/run                  -> 异步提交任务,返回 {task_id}(后台线程执行 harness);
                                    可选字段 backend="mock"|"local_openai" 按请求选择执行后端
  POST /api/compare              -> 一键双跑对照:同一目标自动提交 mock/local_openai 两臂任务,
                                    返回 {compare_id, task_ids}
  GET  /api/run/{id}             -> 任务状态 + 指标摘要(轮询替代)
  GET  /api/runs                 -> 任务列表(含 backend/arm/compare_group 元数据)
  GET  /api/run/{id}/events     -> SSE 实时推送该任务的语义事件(可观测性事件总线)
  GET  /api/artifacts/{id}/{name}-> 下载某工件(metrics.json / report.md / trajectory.jsonl)
  GET  /health                  -> 服务与配置概览
  GET  /                         -> Vue 3 运行监控页
  GET  /docs , /openapi.json    -> OpenAPI(自动)

零依赖核心不受影响:本模块仅在安装 fastapi 时才被导入,CLI 通过
`serve --impl fastapi` 显式启用;缺依赖时优雅降级(CLI 给出清晰提示)。
"""
from __future__ import annotations

import asyncio
import json
import threading
import uuid
from pathlib import Path
from queue import Empty

from ..config import Config
from ..state import TaskInput
from . import _MONITOR_PAGE
from .event_bus import TaskEventBus

# 任务状态内存表:task_id -> {status, result, error, events, backend, arm, compare_group}
_RUNS: dict[str, dict] = {}

_VALID_BACKENDS = ("mock", "local_openai")


def _decide_backend(config: Config, task_data: dict) -> str:
    """决定本任务用哪个后端(纯决策不构造实例)。

    优先级:存在 script 一律锁定 mock(离线回放,历史行为);
           其次请求显式指定的 backend 字段;
           缺省则跟随服务端配置的 model.backend。
    """
    if task_data.get("script") is not None:
        return "mock"
    choice = task_data.get("backend")
    if choice in _VALID_BACKENDS:
        return choice
    return config.model_backend


def _build_backend(config: Config, task_data: dict, backend_name: str):
    """按已决策的后端名构造实例(local_openai 通过配置副本注入工厂)。"""
    if backend_name == "mock":
        from ..models import MockBackend
        return MockBackend(script=task_data.get("script") or [],
                           default_answer=task_data.get("answer", "任务已完成。"))
    cfg = Config(config.to_dict())
    cfg.set("model.backend", backend_name)
    from ..models import create_backend
    return create_backend(cfg)


def _worker(task_id: str, task_data: dict, config: Config, bus: TaskEventBus) -> None:
    """后台线程:跑真实的 harness 并把语义事件推给事件总线。"""
    from ..agent import AgentHarness
    from ..safety import AllowAllProvider

    cfg = Config(config.to_dict())
    # SSE 已经是实时追踪,不必再写 trace.json(保持 API 运行目录干净)
    cfg.set("observability.enabled", False)

    def _on_event(event: dict) -> None:
        event = dict(event)
        event.setdefault("task_id", task_id)  # harness 部分事件不带 task_id,这里补全
        bus.on_event(event)
        _RUNS[task_id]["events"].append(event)

    try:
        backend_name = _decide_backend(config, task_data)
        _RUNS[task_id]["backend"] = backend_name  # 尽早回填,列表立即可见
        backend = _build_backend(cfg, task_data, backend_name)
        harness = AgentHarness.build(cfg, backend=backend,
                                     approver=AllowAllProvider(), on_event=_on_event)
        for rel, content in (task_data.get("setup_files") or {}).items():
            harness.workspace.write_text(rel, content)
        task = TaskInput(task_id=task_id, goal=task_data.get("goal", ""),
                         files_hint=task_data.get("files_hint", []),
                         follow_up_of=task_data.get("follow_up_of"))
        result = harness.run(task)
        _RUNS[task_id]["status"] = result.status
        _RUNS[task_id]["result"] = {
            "status": result.status,
            "final_answer": result.final_answer,
            "metrics": result.metrics,
        }
    except Exception as exc:  # 后台线程异常不能冒泡到事件循环,需记录下来
        _RUNS[task_id]["status"] = "error"
        _RUNS[task_id]["error"] = str(exc)
    finally:
        bus.done(task_id)


def create_app(config: Config):
    """构建 FastAPI 应用(延迟导入 fastapi,避免核心零依赖被污染)。"""
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

    app = FastAPI(title="MyCoder API", version="0.1")
    bus = TaskEventBus()

    def _launch(task_data: dict, *, arm: str | None = None,
                compare_group: str | None = None) -> dict:
        """公共提交通道:/api/run 与 /api/compare 都经由这里入队。"""
        task_id = task_data.get("task_id") or ("api-" + uuid.uuid4().hex[:8])
        _RUNS[task_id] = {"status": "running", "result": None, "error": None,
                          "events": [], "backend": None,
                          "arm": arm, "compare_group": compare_group}
        bus.register(task_id)
        t = threading.Thread(target=_worker, args=(task_id, task_data, config, bus),
                             daemon=True)
        t.start()
        return {"task_id": task_id, "status": "submitted"}

    @app.post("/api/run")
    def api_run(task: dict):
        choice = task.get("backend")
        if choice is not None and choice not in _VALID_BACKENDS:
            return JSONResponse({"error": f"backend 仅支持 {_VALID_BACKENDS}"},
                                status_code=400)
        return _launch(task)

    @app.post("/api/compare")
    def api_compare(task: dict):
        goal = (task.get("goal") or "").strip()
        if not goal:
            return JSONResponse({"error": "双跑对比需要非空 goal"}, status_code=400)
        compare_id = "cmp-" + uuid.uuid4().hex[:8]
        common = {"goal": goal}
        if task.get("follow_up_of"):
            common["follow_up_of"] = task["follow_up_of"]
        if task.get("setup_files"):
            common["setup_files"] = task["setup_files"]
        mock_arm = dict(common, task_id=f"{compare_id}-mock",
                        backend="mock", answer=task.get("answer", "任务已完成。"))
        if task.get("script"):
            mock_arm["script"] = task["script"]
        real_arm = dict(common, task_id=f"{compare_id}-local_openai",
                        backend="local_openai")
        ids = [_launch(mock_arm, arm="mock", compare_group=compare_id)["task_id"],
               _launch(real_arm, arm="local_openai", compare_group=compare_id)["task_id"]]
        return {"compare_id": compare_id, "task_ids": ids}

    @app.get("/api/runs")
    def api_runs():
        return [
            {"task_id": task_id, "status": rec["status"],
             "backend": rec["backend"], "arm": rec["arm"],
             "compare_group": rec["compare_group"],
             "event_count": len(rec["events"])}
            for task_id, rec in _RUNS.items()
        ]

    @app.get("/api/run/{task_id}")
    def api_status(task_id: str):
        rec = _RUNS.get(task_id)
        if rec is None:
            return JSONResponse({"error": "no such task"}, status_code=404)
        return {"task_id": task_id, "status": rec["status"],
                "result": rec["result"], "error": rec["error"],
                "backend": rec["backend"], "arm": rec["arm"],
                "compare_group": rec["compare_group"],
                "event_count": len(rec["events"])}

    @app.get("/api/run/{task_id}/events")
    async def api_events(task_id: str):
        q = bus.get(task_id)
        if q is None:
            return JSONResponse({"error": "no such task or stream already ended"},
                                status_code=404)
        loop = asyncio.get_event_loop()

        async def gen():
            # 不用 Request 注入(规避部分 pydantic 版本的 TypeAdapter 重建问题);
            # 以队列哨兵(__done__)结束流,并以心跳保活。客户端断开时队列不再被消费,
            # 但 sentinel 仍会触发正常结束,不会泄漏事件循环。
            while True:
                try:
                    evt = await loop.run_in_executor(None, lambda: q.get(timeout=15))
                except Empty:
                    yield ": keep-alive\n\n"
                    continue
                if evt.get("type") == "__done__":
                    yield "event: done\ndata: {\"type\":\"done\"}\n\n"
                    break
                yield f"data: {json.dumps(evt, ensure_ascii=False, default=str)}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/artifacts/{task_id}/{name}")
    def api_artifact(task_id: str, name: str):
        root = Path(config.get("artifacts.root", ".mycoder/artifacts")) / task_id
        f = root / name
        if not f.exists():
            return JSONResponse({"error": "no such artifact"}, status_code=404)
        media_type = "application/json" if name.endswith(".json") else "text/plain"
        return HTMLResponse(f.read_text(encoding="utf-8", errors="replace"),
                            media_type=media_type)

    @app.get("/health")
    def api_health():
        return {"status": "ok", "model": config.model_backend,
                "workspace": config.workspace_root,
                "budget_tokens": config.get("context.budget_tokens")}

    @app.get("/vue.global.prod.js")
    def vue_runtime():
        from .monitor_page import VUE_RUNTIME
        if not VUE_RUNTIME.exists():
            return JSONResponse({"error": "vendored Vue runtime missing"}, status_code=404)
        return FileResponse(VUE_RUNTIME, media_type="application/javascript")

    @app.get("/")
    def index():
        return HTMLResponse(_MONITOR_PAGE)

    return app
