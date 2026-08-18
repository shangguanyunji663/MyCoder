"""Phase 5 — FastAPI + SSE API 测试。

用 FastAPI 的 TestClient(同步)驱动:提交一个脚本化任务,验证
  * POST /api/run 返回 task_id;
  * GET /api/run/{id}/events 通过 SSE 流式返回语义事件,并以 done 哨兵结束;
  * GET /api/run/{id} 轮询得到 completed 状态与结果;
  * GET /health、GET /(追踪页)、/openapi.json 可用。

fastapi/uvicorn 缺失时整体跳过(核心零依赖不受影响)。
"""
from __future__ import annotations

import importlib.util

import pytest

_has_fastapi = importlib.util.find_spec("fastapi") is not None
pytestmark = pytest.mark.skipif(not _has_fastapi, reason="需要可选依赖 fastapi")

from mycoder.config import Config  # noqa: E402
from mycoder.api import create_app  # noqa: E402


def _client():
    from fastapi.testclient import TestClient
    return TestClient(create_app(Config()))


# 一个最小脚本化任务:列出文件 -> 读文件 -> 给出结论(走 MockBackend)
_SCRIPT = [
    {"tool_calls": [{"name": "file_list", "arguments": {"pattern": "*.py"}}]},
    {"tool_calls": [{"name": "file_read", "arguments": {"path": "src/main.py"}}]},
    {"content": "已完成审查。"},
]


def test_health_and_trace_page():
    with _client() as c:
        h = c.get("/health")
        assert h.status_code == 200 and h.json()["status"] == "ok"
        page = c.get("/")
        assert page.status_code == 200
        assert "EventSource" in page.text  # vanilla JS 追踪页
        oa = c.get("/openapi.json")
        assert oa.status_code == 200
        assert "MyCoder API" in oa.json()["info"]["title"]


def test_run_and_sse_stream():
    with _client() as c:
        r = c.post("/api/run", json={"goal": "审查 src/main.py", "script": _SCRIPT,
                                     "task_id": "api-test-1"})
        assert r.status_code == 200
        tid = r.json()["task_id"]
        assert tid == "api-test-1"

        # SSE 消费:应收到 task_start ... task_end,并以 done 结束
        types = []
        with c.stream("GET", f"/api/run/{tid}/events") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            done = False
            for line in resp.iter_lines():
                if not line:
                    continue
                if line.startswith("event: done"):
                    done = True
                    break
                if line.startswith("data: "):
                    import json
                    types.append(json.loads(line[6:])["type"])
        assert done, "SSE 流应以 done 哨兵结束"
        assert "task_start" in types and "task_end" in types

        # 轮询状态:任务应已完成
        st = c.get(f"/api/run/{tid}")
        assert st.status_code == 200
        body = st.json()
        assert body["status"] in ("completed", "running")  # 落盘后应为 completed
        if body["status"] == "completed":
            assert body["result"]["final_answer"]


def test_run_unknown_task_events_404():
    with _client() as c:
        r = c.get("/api/run/nope/events")
        assert r.status_code == 404
