"""记忆查询工具(1 个):memory_query。

把结构化记忆对外开放成工具,使 agent 能在 follow-up 阶段直接检索
任务摘要 / 文件摘要 / 关联记忆,而不是重复读文件 —— 这是"重复读文件降到 0"的关键。
"""
from __future__ import annotations

from .base import SAFE, Tool, ToolContext, ToolResult


class MemoryQueryTool(Tool):
    name = "memory_query"
    description = "查询结构化记忆(任务摘要/文件摘要/关联记忆),返回相关片段,避免重复读取文件。"
    parameters = {  # noqa: RUF012 - 类级 schema 常量(非实例可变状态)
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "查询关键词或任务 ID"},
            "kind": {"type": "string", "enum": ["task", "file", "relation", "all"],
                     "description": "记忆类型,默认 all"},
        },
        "required": ["query"],
    }
    danger = SAFE

    def execute(self, ctx: ToolContext, query: str, kind: str = "all") -> ToolResult:
        mem = ctx.memory
        if mem is None:
            return ToolResult(ok=False, error="记忆系统未启用(context 未注入 memory)。")
        text = mem.search(query=query, kind=kind)
        return ToolResult(output=text or "(无相关记忆)", meta={"kind": kind, "hit": bool(text)})
