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

from mycoder.api import create_app  # noqa: E402
from mycoder.config import Config  # noqa: E402


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
        assert "EventSource" in page.text
        assert "Vue" in page.text
        assert c.get("/vue.global.prod.js").status_code == 200
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
        runs = c.get("/api/runs")
        assert runs.status_code == 200
        assert any(item["task_id"] == tid for item in runs.json())

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


# ---------- 后端按请求切换 + 双跑对照(替身工厂,全程离线) ----------

def _wait_completed(c, task_id, timeout=5.0):
    import time
    body = {}
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = c.get(f"/api/run/{task_id}")
        body = resp.json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    return body


def test_run_rejects_unknown_backend():
    with _client() as c:
        r = c.post("/api/run", json={"goal": "x", "backend": "cloud_llm"})
        assert r.status_code == 400


def test_run_explicit_local_openai_selects_factory(monkeypatch):
    """显式 backend=local_openai 应注入配置副本并经工厂构造(不真连网)。"""
    from mycoder.models import MockBackend
    seen = {}

    def fake_create(cfg):
        seen["model_backend"] = cfg.model_backend
        return MockBackend(script=[{"content": "离线完成"}])

    monkeypatch.setattr("mycoder.models.create_backend", fake_create)
    with _client() as c:
        r = c.post("/api/run", json={"goal": "走真后端", "backend": "local_openai",
                                     "task_id": "bk-local"})
        assert r.status_code == 200
        body = _wait_completed(c, "bk-local")
        assert body["status"] == "completed"
        assert seen["model_backend"] == "local_openai"
        runs = c.get("/api/runs").json()
        rec = next(x for x in runs if x["task_id"] == "bk-local")
        assert rec["backend"] == "local_openai"


def test_run_script_forces_mock_even_with_backend_field(monkeypatch):
    """带 script 的请求无论如何都锁定 mock,工厂不应被触发。"""

    def fake_create(_cfg):  # pragma: no cover - 触发即失败
        raise AssertionError("带 script 时不应经过工厂")

    monkeypatch.setattr("mycoder.models.create_backend", fake_create)
    with _client() as c:
        r = c.post("/api/run", json={"goal": "x", "script": _SCRIPT,
                                     "backend": "local_openai", "task_id": "force-mock"})
        assert r.status_code == 200
        body = _wait_completed(c, "force-mock")
        assert body["status"] == "completed"
        assert c.get("/api/runs").json()[0]["backend"] == "mock"


def test_compare_submits_two_arms(monkeypatch):
    """/api/compare 应生成同组两臂(mock/local_openai)并共享 compare_group。"""
    from mycoder.models import MockBackend

    seen_names = []

    def fake_create(cfg):
        seen_names.append(cfg.model_backend)
        return MockBackend(script=[{"content": "该臂已离线完成"}])

    monkeypatch.setattr("mycoder.models.create_backend", fake_create)
    with _client() as c:
        r = c.post("/api/compare", json={"goal": "同一目标双跑"})
        assert r.status_code == 200
        data = r.json()
        cid = data["compare_id"]
        assert cid.startswith("cmp-")
        assert data["task_ids"] == [f"{cid}-mock", f"{cid}-local_openai"]

        runs = {x["task_id"]: x for x in c.get("/api/runs").json()}
        arm_m = runs[f"{cid}-mock"]
        arm_l = runs[f"{cid}-local_openai"]
        assert arm_m["arm"] == "mock" and arm_m["backend"] == "mock"
        assert arm_l["arm"] == "local_openai"
        assert arm_l["compare_group"] == arm_m["compare_group"] == cid

        done_m = _wait_completed(c, f"{cid}-mock")
        done_l = _wait_completed(c, f"{cid}-local_openai")
        assert done_m["status"] == "completed"
        assert done_l["status"] == "completed"
        assert seen_names == ["local_openai"]  # 仅真实臂经过工厂
