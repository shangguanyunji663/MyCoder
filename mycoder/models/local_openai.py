"""本地 OpenAI 兼容后端(第 2 类模型后端)。

面向任何本地部署的 OpenAI-compatible 服务(llama.cpp server / vLLM / Ollama / LM Studio),
base_url 形如 http://127.0.0.1:8080/v1,完全不出本机,满足"全部 localhost 运行"约束。

生产级增强:
  * 重试 + 指数退避:连接错误 / 429 / 5xx 自动重试,尊重 Retry-After 头;
  * 真实 usage 透传:API 返回的 usage.prompt_tokens/completion_tokens 直接进入
    ModelResponse.usage;若服务未返回,退化到启发式估算(tokenize_len);
  * 流式输出:complete_stream() 以生成器形式按 SSE 行增量 yield,最后合成完整
    ModelResponse,便于上层做"打字机"式展示;
  * 超时可配置;URL 端点逻辑清晰,不再靠多级 if 兜。

实现上默认用标准库 urllib(零额外依赖),可选 requests 加速。
"""
from __future__ import annotations

import contextlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

from .base import ModelBackend, ModelResponse, tools_to_openai

# 默认重试策略:指数退避 base=0.5s,cap=8s,最多 3 次(不含首次)
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BACKOFF_BASE = 0.5
_DEFAULT_BACKOFF_CAP = 8.0
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LocalOpenAIBackend(ModelBackend):
    name = "local_openai"

    def __init__(self, base_url: str = "http://127.0.0.1:8080/v1",
                 api_key: str = "local", model: str = "qwen2.5-coder-7b",
                 temperature: float = 0.0, timeout_seconds: int = 60,
                 max_retries: int = _DEFAULT_MAX_RETRIES,
                 backoff_base: float = _DEFAULT_BACKOFF_BASE,
                 backoff_cap: float = _DEFAULT_BACKOFF_CAP,
                 stream: bool = False):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.stream = stream

    # ------------------------------------------------------------------
    def _chat_url(self) -> str:
        """端点解析:base_url 已指向 chat/completions 则原样使用,否则补齐路径。"""
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return self.base_url + "/chat/completions"

    # ------------------------------------------------------------------
    def complete(self, messages: list, tools: list[dict] | None = None,
                 temperature: float | None = None) -> ModelResponse:
        """同步调用(带重试/退避)。stream=True 时内部收集流式片段后返回汇总结果。"""
        if self.stream:
            last: ModelResponse | None = None
            for partial in self.complete_stream(messages, tools=tools, temperature=temperature):
                last = partial
            return last if last is not None else ModelResponse(
                content="", finish_reason="stop",
                usage={"prompt_tokens": 0, "completion_tokens": 0})
        payload = self._build_payload(messages, tools, temperature, stream=False)
        body = self._post_with_retries(payload)
        return self._parse(body)

    def complete_stream(self, messages: list, tools: list[dict] | None = None,
                        temperature: float | None = None) -> Iterator[ModelResponse]:
        """流式调用:按 SSE 事件 yield 增量 ModelResponse(delta 模式)。

        每一次 yield 都是"到目前为止"的累积响应:content 是拼接后的全文、
        tool_calls 是累积的调用片段,便于上层直接渲染。最后一次 yield 带
        finish_reason 与 usage,表示完成。
        """
        payload = self._build_payload(messages, tools, temperature, stream=True)
        acc_content = ""
        acc_calls: dict[int, dict[str, Any]] = {}
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        finish_reason = None
        for event in self._post_sse(payload):
            choices = (event.get("choices") or [{}])
            delta = (choices[0] or {}).get("delta") or {}
            if delta.get("content"):
                acc_content += delta["content"]
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = acc_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["arguments"] += fn["arguments"]
            if event.get("usage"):
                usage = {
                    "prompt_tokens": event["usage"].get("prompt_tokens", usage["prompt_tokens"]),
                    "completion_tokens": event["usage"].get(
                        "completion_tokens", usage["completion_tokens"]),
                }
            fr = (choices[0] or {}).get("finish_reason")
            if fr:
                finish_reason = fr
            yield ModelResponse(
                content=acc_content,
                tool_calls=self._assemble_tool_calls(acc_calls),
                finish_reason="",
                usage=dict(usage),
            )
        # 最后一次:补全 finish_reason;若服务器未返回 usage,回退启发式
        if not usage["completion_tokens"]:
            usage["completion_tokens"] = self.tokenize_len(acc_content)
        yield ModelResponse(
            content=acc_content,
            tool_calls=self._assemble_tool_calls(acc_calls),
            finish_reason=finish_reason or "stop",
            usage=dict(usage),
        )

    # ------------------------------------------------------------------
    def _build_payload(self, messages: list, tools: list[dict] | None,
                       temperature: float | None, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_openai() if hasattr(m, "to_openai") else m for m in messages],
            "temperature": self.temperature if temperature is None else temperature,
        }
        if tools:
            payload["tools"] = tools_to_openai(tools)
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _post_with_retries(self, payload: dict[str, Any]) -> dict:
        """带指数退避的 POST,返回解析后的 JSON 体。"""
        url = self._chat_url()
        data = json.dumps(payload).encode("utf-8")
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._do_post(url, data)
            except RetryableError as e:
                last_exc = e
                if attempt >= self.max_retries:
                    break
                wait = min(self.backoff_cap, self.backoff_base * (2 ** attempt))
                if e.retry_after is not None:
                    wait = max(wait, e.retry_after)
                time.sleep(wait)
            except urllib.error.HTTPError as e:
                if e.code not in _RETRYABLE_STATUS:
                    self._raise_http_error(url, e)
                last_exc = e
                if attempt >= self.max_retries:
                    break
                wait = min(self.backoff_cap, self.backoff_base * (2 ** attempt))
                retry_after = e.headers.get("Retry-After") if e.headers else None
                if retry_after:
                    with contextlib.suppress(ValueError):
                        wait = max(wait, float(retry_after))
                time.sleep(wait)
            except urllib.error.URLError as e:
                # 连接失败/拒绝/重置视为可重试
                last_exc = e
                if attempt >= self.max_retries:
                    break
                wait = min(self.backoff_cap, self.backoff_base * (2 ** attempt))
                time.sleep(wait)
        raise ConnectionError(
            f"多次重试后仍无法连接本地模型服务 {url}。"
            f"请确认本地 OpenAI 兼容服务已启动。原始错误: {last_exc}"
        )

    def _post_sse(self, payload: dict[str, Any]) -> Iterator[dict]:
        """SSE 流式 POST,逐行 yield 解析后的 JSON 事件体。"""
        url = self._chat_url()
        data = json.dumps(payload).encode("utf-8")
        # 流式不做重试(已开始发送无法安全重放)
        try:
            yield from self._do_post_sse(url, data)
        except urllib.error.HTTPError as e:
            self._raise_http_error(url, e)
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"无法连接本地模型服务 {url}。请确认本地 OpenAI 兼容服务已启动。原始错误: {e}"
            ) from e

    # ------------------------------------------------------------------
    def _do_post(self, url: str, data: bytes) -> dict:
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return body
        except urllib.error.URLError as e:
            # timeout / connection reset 等 -> 交给外层判定是否重试
            raise e

    def _do_post_sse(self, url: str, data: bytes) -> Iterator[dict]:
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Accept", "text/event-stream")
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].lstrip()
                if chunk == "[DONE]":
                    return
                try:
                    obj = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                yield obj

    @staticmethod
    def _raise_http_error(url: str, e: urllib.error.HTTPError) -> None:
        try:
            error_body = e.read().decode("utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            error_body = "(could not read error body)"
        raise ConnectionError(
            f"本地模型服务 {url} 返回 HTTP {e.code}。原始错误: {e} body={error_body}"
        ) from e

    @staticmethod
    def _assemble_tool_calls(acc_calls: dict[int, dict[str, Any]]) -> list[dict]:
        out: list[dict] = []
        for idx in sorted(acc_calls.keys()):
            slot = acc_calls[idx]
            out.append({
                "id": slot.get("id") or f"call_{idx}",
                "name": slot.get("name", ""),
                "arguments": slot.get("arguments", "{}"),
            })
        return out

    # ------------------------------------------------------------------
    def _parse(self, body: dict) -> ModelResponse:
        choice = (body.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        raw_calls = msg.get("tool_calls") or []
        tool_calls: list[dict[str, Any]] = []
        for i, tc in enumerate(raw_calls):
            fn = tc.get("function") or {}
            arguments_val = fn.get("arguments") or "{}"
            tool_calls.append({
                "id": tc.get("id") or f"call_{i}",
                "name": fn.get("name", ""),
                # 保持字符串格式(OpenAI 规范);harness 在执行工具时会自行 json.loads
                "arguments": arguments_val if isinstance(arguments_val, str) else json.dumps(arguments_val),
            })
        usage = body.get("usage") or {}
        # 若服务未返回 usage,退化到启发式(用 ModelResponse 文本粗估)
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or self.tokenize_len(content))
        if prompt_tokens == 0:
            # 无法获取原始 prompt 文本,提示为 0(上层 metrics 累加时可忽略)
            prompt_tokens = 0
        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", "stop"),
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": int(usage.get("total_tokens") or prompt_tokens + completion_tokens),
            },
        )


class RetryableError(Exception):
    """内部标记:可重试的网络层异常。"""

    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after
