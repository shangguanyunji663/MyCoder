"""模型后端抽象。

设计思路:K 通过统一 ModelBackend 接口解耦"模型如何回答"与"Harness 如何调度",
使得评测时用确定性 mock 后端(验证系统能力),部署时换成本地 OpenAI 兼容后端
(验证真实模型能力),两者互不污染 —— 这正是评测体系里"区分模型能力与系统能力"的落点。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ModelResponse:
    """一次模型补全的统一返回。"""
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})


class ModelBackend(ABC):
    """所有模型后端的抽象基类。"""

    name: str = "base"

    @abstractmethod
    def complete(self, messages: list, tools: list[dict] | None = None,
                 temperature: float = 0.0) -> ModelResponse:
        """给定对话消息列表,返回补全结果(文本或工具调用)。"""

    def supports_tool_calls(self) -> bool:
        """是否原生支持工具调用(本地 OpenAI 兼容为 True,mock 脚本化亦返回 True)。"""
        return True

    def state(self) -> dict:
        """可 checkpoint 的后端状态(如脚本化后端的游标),默认空。"""
        return {}

    def load_state(self, state: dict) -> None:  # noqa: B027
        """恢复后端状态(Resume 用),默认无操作。子类按需覆盖。"""
        pass

    def tokenize_len(self, text: str) -> int:
        """粗粒度 token 估算,供后端记录 usage(重估策略见 context.tokens)。"""
        from ..context.tokens import estimate_tokens
        return estimate_tokens(text)


def tools_to_openai(tools: list) -> list[dict]:
    """把内部工具描述转为 OpenAI tools 参数格式。"""
    result = []
    for t in tools:
        if hasattr(t, 'as_openai_schema'):
            # Tool 对象
            result.append({"type": "function", "function": t.as_openai_schema()})
        elif isinstance(t, dict):
            # 已经是字典格式（来自 registry.schemas()）
            result.append({"type": "function", "function": t})
    return result
