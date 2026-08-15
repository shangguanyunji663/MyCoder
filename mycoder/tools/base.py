"""工具调用框架基类。

统一抽象 + 注册表:
  * Tool 定义 name / description / parameters(JSON Schema)/ danger 等级;
  * ToolResult 定义统一返回(ok / output / error / meta);
  * ToolContext 注入运行期依赖(工作区、记忆、配置),保持工具本身无副作用依赖;
  * ToolRegistry 负责注册、查表、以及 as_openai_schema 的批量导出。

安全边界(参数校验/隔离/审批/去重/脱敏)在 safety 模块统一处理,
工具 execute 只做"纯业务",保证 安全层 与 业务层 正交。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# 危险等级:决定 HITL 是否需要人工审批
SAFE = "safe"     # 只读,无需审批
WARN = "warn"     # 写/执行,按策略告警
HITL = "hitl"     # 高风险,必须人工审批


@dataclass
class ToolResult:
    """工具统一返回。"""
    output: str = ""
    ok: bool = True
    error: str = ""
    meta: dict = field(default_factory=dict)  # 缓存命中/文件哈希/是否脱敏等

    def to_message_content(self) -> str:
        if self.ok:
            return self.output
        return f"[工具执行失败] {self.error or self.output}"


@dataclass
class ToolContext:
    """注入到每个工具的运行期依赖。"""
    workspace: Any = None      # 沙箱工作区
    memory: Any = None         # 结构化记忆(可空)
    config: Any = None         # 全局 Config


class Tool(ABC):
    name: str = "tool"
    description: str = ""
    parameters: dict = {"type": "object", "properties": {}, "required": []}
    danger: str = SAFE

    def as_openai_schema(self) -> dict:
        return {"name": self.name, "description": self.description,
                "parameters": self.parameters}

    @abstractmethod
    def execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        """执行业务逻辑(参数已经过安全层校验)。"""


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        if tools:
            for t in tools:
                self.register(t)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重名: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"未知工具: {name}")
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict]:
        return [t.as_openai_schema() for t in self.all()]

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)