"""Token 估算。

采用"中文按字、其余按 4 字符/token"的混合启发式 —— 无需模型分词器即可
得到一个稳定、可复现的预算控制基准(评测确定性诉求)。估算只需具备
单调性与稳定性,不需要与真实 tokenizer 分毫不差。
"""
from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    # 分段避免单个超长 ASCII 块被 4 整除后低估;+1 保证非空文本至少 1 token
    return cjk + (other + 3) // 4


def estimate_messages(messages: list) -> int:
    """估算一组消息的总 token(含角色字段的固定开销)。"""
    total = 0
    for m in messages:
        if isinstance(m, dict):
            content = str(m.get("content", ""))
            tool_calls = m.get("tool_calls")
            total += 4 + estimate_tokens(content)  # 角色/结构约 4 token
            if tool_calls:
                total += estimate_tokens(str(tool_calls))
        else:
            total += 4 + estimate_tokens(getattr(m, "content", "") or "")
            if getattr(m, "tool_calls", None):
                total += estimate_tokens(str(m.tool_calls))
    return total
