"""会话状态与消息模型。

设计思路:
  * 把"消息/工具调用/工具结果/步/任务输入/运行结果"做成纯数据类(Python dataclass),
    它们不包含任何 I/O,便于序列化到 checkpoint、轨迹 JSONL 与评测比对;
  * text 而非二进制,保证任何中间态都能被 JSON 表示与脱敏。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# --------------------------------------------------------------------------
# 消息
# --------------------------------------------------------------------------
@dataclass
class Message:
    """一条对话消息。role ∈ {system, user, assistant, tool}。"""
    role: str
    content: str
    name: str | None = None          # role == "tool" 时的工具名
    tool_call_id: str | None = None  # role == "tool" 时对应调用 ID
    tool_calls: list[dict] | None = None  # assistant 发起的工具调用(OpenAI 风格)
    meta: dict = field(default_factory=dict)

    def to_openai(self) -> dict:
        """转为 OpenAI 兼容格式(供本地 OpenAI 后端使用)。"""
        msg: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.role == "tool":
            # Tool 消息只需要 tool_call_id，不需要 name
            if self.tool_call_id:
                msg["tool_call_id"] = self.tool_call_id
        else:
            if self.name:
                msg["name"] = self.name
            if self.tool_call_id:
                msg["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        return msg


@dataclass
class ToolCall:
    """一次工具调用请求。"""
    id: str
    name: str
    arguments: dict
    status: str = "pending"     # pending | ok | error | denied | skipped
    output: str | None = None
    error: str | None = None
    meta: dict = field(default_factory=dict)  # cache_hit / redacted / danger / ...


@dataclass
class Step:
    """Harness 的一步(一轮 模型→工具 往返)。"""
    index: int
    assistant: Message | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0       # 本轮实际送入模型的 prompt token 数(裁剪后)
    prompt_before_tokens: int = 0  # 裁剪前 token 数(评测压缩率用)
    pruned: bool = False
    prune_strategies: list[str] = field(default_factory=list)
    latency_ms: int = 0


@dataclass
class TaskInput:
    """一次任务输入的封装。"""
    task_id: str
    goal: str
    files_hint: list[str] = field(default_factory=list)   # 任务相关文件的提示
    follow_up_of: str | None = None                    # follow-up 的父任务 ID
    extra: dict = field(default_factory=dict)             # 自由扩展(评测断言等)


@dataclass
class RunResult:
    """一次运行的最终结果。"""
    task_id: str
    status: str                     # completed | max_steps | error | interrupted
    final_answer: str = ""
    steps: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    drift: dict | None = None    # resume 场景下的漂移报告
    error: str | None = None
