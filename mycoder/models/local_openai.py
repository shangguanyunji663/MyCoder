"""本地 OpenAI 兼容后端(第 2 类模型后端)。

面向任何本地部署的 OpenAI-compatible 服务(llama.cpp server / vLLM / Ollama / LM Studio),
base_url 形如 http://127.0.0.1:8080/v1,完全不出本机,满足"全部 localhost 运行"约束。

实现上默认用标准库 urllib(零额外依赖),可选 requests 加速 — 见 _post 里注释。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .base import ModelBackend, ModelResponse, tools_to_openai


class LocalOpenAIBackend(ModelBackend):
    name = "local_openai"

    def __init__(self, base_url: str = "http://127.0.0.1:8080/v1",
                 api_key: str = "local", model: str = "qwen2.5-coder-7b",
                 temperature: float = 0.0, timeout_seconds: int = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds

    # ------------------------------------------------------------------
    def _chat_url(self) -> str:
        """端点解析:base_url 已指向 chat/completions 则原样使用,否则补齐路径。"""
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return self.base_url + "/chat/completions"

    def complete(self, messages: list, tools: list[dict] | None = None,
                 temperature: float | None = None) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_openai() if hasattr(m, "to_openai") else m for m in messages],
            "temperature": self.temperature if temperature is None else temperature,
        }
        if tools:
            payload["tools"] = tools_to_openai(tools)

        url = self._chat_url()

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self.api_key}")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                error_body = e.read().decode("utf-8")
            except:
                error_body = "(could not read error body)"
            raise ConnectionError(
                f"无法连接本地模型服务 {url}。请确认本地 OpenAI 兼容服务已启动。原始错误: {e}"
            ) from e
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"无法连接本地模型服务 {url}。请确认本地 OpenAI 兼容服务已启动。原始错误: {e}"
            ) from e

        return self._parse(body)

    # ------------------------------------------------------------------
    def _parse(self, body: dict) -> ModelResponse:
        choice = (body.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        raw_calls = msg.get("tool_calls") or []
        tool_calls = []
        for tc in raw_calls:
            fn = tc.get("function") or {}
            # 保留 arguments 为 JSON 字符串格式（OpenAI 兼容格式要求）
            # harness 在执行工具时会自行解析
            arguments_str = fn.get("arguments") or "{}"
            tool_calls.append({
                "id": tc.get("id") or f"call_{len(tool_calls)}",
                "name": fn.get("name", ""),
                "arguments": arguments_str,  # 保持字符串格式
            })
        usage = body.get("usage") or {}
        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", "stop"),
            usage={
                "prompt_tokens": usage.get("prompt_tokens", self.tokenize_len("")),
                "completion_tokens": usage.get("completion_tokens", 0),
            },
        )