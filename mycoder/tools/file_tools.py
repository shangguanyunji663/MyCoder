"""文件类工具(5 个):file_read / file_write / file_edit / file_list / grep_search。

每个工具只负责纯业务,路径安全交给 Workspace.resolve 拦截,参数校验/审批/去重
交给 safety 层。返回 meta 里携带 path / file_hash,便于记忆模块与去重层复用,
避免二次读取。
"""
from __future__ import annotations

import re
from typing import Any

from ..util import sha256_file, truncate
from .base import SAFE, WARN, Tool, ToolContext, ToolResult


class ReadFileTool(Tool):
    name = "file_read"
    description = "读取工作区内文本文件内容(可用 offset/limit 分页),返回内容与文件哈希。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对工作区的文件路径"},
            "offset": {"type": "integer", "description": "从第几行开始(0 起),默认 0", "minimum": 0},
            "limit": {"type": "integer", "description": "最多读多少行,缺省读全文", "minimum": 1},
        },
        "required": ["path"],
    }
    danger = SAFE

    def execute(self, ctx: ToolContext, path: str, offset: int = 0, limit: int | None = None) -> ToolResult:
        p = ctx.workspace.resolve(path)
        if not p.exists():
            return ToolResult(ok=False, error=f"文件不存在: {path}")
        if p.is_dir():
            return ToolResult(ok=False, error=f"目标是目录而非文件: {path}")
        if offset < 0:
            return ToolResult(ok=False, error=f"offset 不能为负数: {offset}")
        raw = p.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()
        selected = lines[offset:] if limit is None else lines[offset:offset + limit]
        content = "\n".join(selected)
        max_chars = int(getattr(ctx.config, "get", lambda *a: 8000)("context.max_file_content_chars", 8000))
        content = truncate(content, max_chars)
        lineno = f"(行 {offset}..{offset + len(selected) - 1})" if selected else "(空)"
        return ToolResult(
            output=f"# {path} 共 {len(lines)} 行 {lineno}\n\n{content}",
            meta={"path": ctx.workspace.rel(p), "file_hash": sha256_file(p), "total_lines": len(lines)},
        )


class WriteFileTool(Tool):
    name = "file_write"
    description = "在工作区内创建或覆盖文件(content 为完整新内容)。覆盖已存在文件属于状态变更,按告警级别处理。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对工作区的文件路径"},
            "content": {"type": "string", "description": "要写入的完整内容"},
        },
        "required": ["path", "content"],
    }
    danger = WARN

    def execute(self, ctx: ToolContext, path: str, content: str) -> ToolResult:
        p = ctx.workspace.write_text(path, content)
        return ToolResult(
            output=f"已写入 {ctx.workspace.rel(p)}({len(content)} 字符)。",
            meta={"path": ctx.workspace.rel(p), "file_hash": sha256_file(p), "size": len(content)},
        )


class EditFileTool(Tool):
    name = "file_edit"
    description = "在工作区内对文件做针对性字符串替换(old_string -> new_string),避免整文件覆盖。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对工作区的文件路径"},
            "old_string": {"type": "string", "description": "要被替换的原字符串(需唯一)"},
            "new_string": {"type": "string", "description": "替换后的新字符串"},
            "replace_all": {"type": "boolean", "description": "是否替换所有出现,默认仅允许唯一匹配"},
        },
        "required": ["path", "old_string", "new_string"],
    }
    danger = WARN

    def execute(self, ctx: ToolContext, path: str, old_string: str, new_string: str,
                replace_all: bool = False) -> ToolResult:
        p = ctx.workspace.resolve(path)
        if not p.exists():
            return ToolResult(ok=False, error=f"文件不存在: {path}")
        text = p.read_text(encoding="utf-8", errors="replace")
        count = text.count(old_string)
        if count == 0:
            return ToolResult(ok=False, error=f"未找到待替换字符串(长度 {len(old_string)})")
        if count > 1 and not replace_all:
            return ToolResult(
                ok=False,
                error=f"待替换串出现 {count} 次,非唯一;请加长 old_string 或设置 replace_all=true",
            )
        text = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
        ctx.workspace.write_text(path, text)
        return ToolResult(
            output=f"已替换 {count} 处 → {ctx.workspace.rel(p)}",
            meta={"path": ctx.workspace.rel(p), "file_hash": sha256_file(p), "replacements": count},
        )


class ListFilesTool(Tool):
    name = "file_list"
    description = "按 glob 模式列出工作区文件(相对路径),排除隐藏目录与缓存。"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "glob 模式,如 *.py 或 **/*.md,默认 *"},
        },
        "required": [],
    }
    danger = SAFE

    def execute(self, ctx: ToolContext, pattern: str = "*") -> ToolResult:
        files = ctx.workspace.list_files(pattern)
        if not files:
            return ToolResult(output="(未匹配到任何文件)", meta={"count": 0})
        return ToolResult(output="\n".join(files), meta={"count": len(files)})


class GrepTool(Tool):
    name = "grep_search"
    description = "在工作区内正则搜索文件内容,返回 文件:行号:内容 列表。"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "正则表达式"},
            "path": {"type": "string", "description": "限定目录或文件(可空=全工作区)"},
            "include": {"type": "string", "description": "文件名 glob 过滤,如 *.py"},
        },
        "required": ["pattern"],
    }
    danger = SAFE

    def execute(self, ctx: ToolContext, pattern: str, path: str | None = None,
                include: str | None = None) -> ToolResult:
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return ToolResult(ok=False, error=f"非法正则: {e}")

        base = ctx.workspace.resolve(path) if path else ctx.workspace.root
        hits: list[str] = []
        scanned = 0
        for f in base.rglob("*") if base.is_dir() else [base]:
            if not f.is_file():
                continue
            rel = str(f.relative_to(ctx.workspace.root))
            if any(part.startswith(".") or part == "__pycache__" for part in f.relative_to(ctx.workspace.root).parts):
                continue
            if include and not f.match(include):
                continue
            scanned += 1
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if regex.search(line):
                        hits.append(f"{rel}:{i}:{line.strip()[:200]}")
            except OSError:
                continue
        if not hits:
            return ToolResult(output=f"(在 {scanned} 个文件中无匹配)", meta={"scanned": scanned, "hits": 0})
        out = "\n".join(hits)
        return ToolResult(output=truncate(out, 8000), meta={"scanned": scanned, "hits": len(hits)})