"""LocalOpenAIBackend 生产级能力测试:重试/退避、真实 usage、流式输出。

全部通过 monkeypatch 假 urlopen 实现,完全离线、确定性强。
"""
from __future__ import annotations

import io
import json
import urllib.error
from http.client import HTTPMessage
from typing import Any

import pytest

from mycoder.models.local_openai import LocalOpenAIBackend


def _empty_headers() -> HTTPMessage:
    return HTTPMessage()

SAMPLE = {
    "choices": [{
        "message": {"role": "assistant", "content": "你好"},
        "finish_reason": "stop",
    }],
    "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
}


class _FakeResponse:
    """可上下文管理、可迭代的伪 urlopen 响应。"""

    def __init__(self, body: bytes | list[bytes], status: int = 200):
        self._body = body
        self.status = status
        if isinstance(body, bytes):
            self._lines: list[bytes] | None = None
        else:
            self._lines = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body if isinstance(self._body, bytes) else b"".join(self._body)

    def __iter__(self):
        if self._lines is None:
            raise TypeError("non-stream response is not iterable")
        return iter(self._lines)


def _sse_body(events: list[dict], done: bool = True) -> list[bytes]:
    lines: list[bytes] = []
    for ev in events:
        lines.append(b"data: " + json.dumps(ev, ensure_ascii=False).encode("utf-8") + b"\n\n")
    if done:
        lines.append(b"data: [DONE]\n\n")
    return lines


@pytest.fixture
def backend():
    return LocalOpenAIBackend(max_retries=2, backoff_base=0.0, backoff_cap=0.0)


def _patch_urlopen(monkeypatch, fake):
    monkeypatch.setattr("mycoder.models.local_openai.urllib.request.urlopen", fake)


class TestRetry:
    def test_retries_then_succeeds(self, monkeypatch, backend):
        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.HTTPError(req.full_url, 503, "unavailable",
                                             _empty_headers(), io.BytesIO(b"error"))
            return _FakeResponse(json.dumps(SAMPLE).encode("utf-8"))

        _patch_urlopen(monkeypatch, fake_urlopen)
        resp = backend.complete([{"role": "user", "content": "hi"}])
        assert calls["n"] == 3          # 2 次重试后成功
        assert resp.content == "你好"
        assert resp.usage["prompt_tokens"] == 120

    def test_no_retry_on_4xx(self, monkeypatch, backend):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 404, "not found",
                                         _empty_headers(), io.BytesIO(b"nope"))

        _patch_urlopen(monkeypatch, fake_urlopen)
        with pytest.raises(ConnectionError, match="404"):
            backend.complete([{"role": "user", "content": "hi"}])

    def test_urlerror_retried(self, monkeypatch, backend):
        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            if calls["n"] < 2:
                raise urllib.error.URLError("connection refused")
            return _FakeResponse(json.dumps(SAMPLE).encode("utf-8"))

        _patch_urlopen(monkeypatch, fake_urlopen)
        resp = backend.complete([{"role": "user", "content": "hi"}])
        assert calls["n"] == 2 and resp.content == "你好"

    def test_exhausts_retries(self, monkeypatch, backend):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.URLError("down")

        _patch_urlopen(monkeypatch, fake_urlopen)
        with pytest.raises(ConnectionError, match="多次重试"):
            backend.complete([{"role": "user", "content": "hi"}])


class TestUsage:
    def test_usage_from_api(self, backend):
        body = dict(SAMPLE)
        body["usage"] = {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}
        resp = backend._parse(body)
        assert resp.usage["prompt_tokens"] == 5
        assert resp.usage["completion_tokens"] == 7
        assert resp.usage["total_tokens"] == 12

    def test_usage_fallback_heuristic(self, backend):
        body = dict(SAMPLE)
        body.pop("usage")
        resp = backend._parse(body)
        # completion 回退到启发式估算(非零);prompt 无法回溯原文,置 0
        assert resp.usage["completion_tokens"] > 0

    def test_arguments_kept_as_json_string(self, backend):
        body = {"choices": [{"message": {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "c1", "function": {"name": "file_read",
                                                     "arguments": {"path": "a.py"}}}],
        }, "finish_reason": "tool_calls"}]}
        resp = backend._parse(body)
        assert json.loads(resp.tool_calls[0]["arguments"])["path"] == "a.py"


class TestStream:
    def test_stream_accumulates_content_and_calls(self, monkeypatch, backend):
        events: list[dict[str, Any]] = [
            {"choices": [{"delta": {"role": "assistant", "content": "你"}}]},
            {"choices": [{"delta": {"content": "好"}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "c1", "function": {"name": "file_read",
                                                      "arguments": "{\"pat"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": "h\":\"a.py\"}"}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}],
             "usage": {"prompt_tokens": 10, "completion_tokens": 8}},
        ]

        def fake_urlopen(req, timeout=None):
            return _FakeResponse(_sse_body(events))

        _patch_urlopen(monkeypatch, fake_urlopen)
        results = list(backend.complete_stream([{"role": "user", "content": "hi"}]))
        final = results[-1]
        assert final.content == "你好"
        assert final.tool_calls[0]["name"] == "file_read"
        assert json.loads(final.tool_calls[0]["arguments"])["path"] == "a.py"
        assert final.finish_reason == "tool_calls"
        assert final.usage["completion_tokens"] == 8

    def test_stream_fallback_usage(self, monkeypatch, backend):
        events: list[dict[str, Any]] = [
            {"choices": [{"delta": {"content": "答"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ]

        def fake_urlopen(req, timeout=None):
            return _FakeResponse(_sse_body(events))

        _patch_urlopen(monkeypatch, fake_urlopen)
        final = list(backend.complete_stream([{"role": "user", "content": "q"}]))[-1]
        # 服务未返回 usage -> completion 回退启发式(非零)
        assert final.usage["completion_tokens"] > 0
