"""历史摘要器。

为什么要有摘要器:裁剪"旧历史"时不能简单丢弃 —— 那会丢信息。我们用确定性
摘要把被折叠的历史压缩成要点文本,既降 token 又保留关键事实,且不引入模型
随机性(可复现)。

DeterministicSummarizer 是默认实现,LLMSummarizer 提供真实模型压缩路径:
  * 一次性把折叠轮次压成要点摘要(单次模型调用);
  * 模型调用失败/返回空文本时自动回退确定性摘要,保证裁剪链不中断;
  * 评测时可用 MockBackend(固定返回)驱动,保持可复现。
"""
from __future__ import annotations

from typing import Any

from ..util import truncate


class Summarizer:
    def summarize_turn(self, step_index: int, assistant_content: str,
                       tool_results: list[tuple[str, str]]) -> str:
        raise NotImplementedError

    def summarize_text(self, text: str, max_chars: int = 240) -> str:
        return truncate(text, max_chars)


class DeterministicSummarizer(Summarizer):
    """确定性压缩:保留助手结论首句 + 每步工具名与结果首片段。"""

    def summarize_turn(self, step_index: int, assistant_content: str,
                       tool_results: list[tuple[str, str]]) -> str:
        parts = [f"[步骤 {step_index}]"]
        if assistant_content:
            parts.append("助手结论: " + self.summarize_text(assistant_content, 160))
        for name, out in tool_results:
            parts.append(f"- {name}: {self.summarize_text(out, 120)}")
        return "\n".join(parts)


class LLMSummarizer(Summarizer):
    """用模型后端压缩折叠轮次;失败回退确定性摘要。

    backend.complete() 返回的 content 作为摘要文本;若模型未就绪或返回空,
    自动落到 DeterministicSummarizer,保证上下文裁剪永不因摘要失败而中断。
    """

    PROMPT = (
        "你是代码任务的对话摘要器。把下面这段多轮 助手-工具 交互压缩成要点摘要,"
        "保留:每步做了什么(工具名与参数要点)、产生了什么结论、涉及哪些文件。"
        "输出纯文本,不要编号,不要评价,总长控制在 300 字以内。\n\n"
    )

    def __init__(self, backend: Any = None, max_chars: int = 240,
                 fallback: Summarizer | None = None):
        self.backend = backend
        self.max_chars = max_chars
        self.fallback = fallback or DeterministicSummarizer()

    def summarize_turn(self, step_index: int, assistant_content: str,
                       tool_results: list[tuple[str, str]]) -> str:
        if self.backend is None:
            return self.fallback.summarize_turn(step_index, assistant_content, tool_results)
        lines = [f"[步骤 {step_index}]"]
        if assistant_content:
            lines.append("助手: " + truncate(assistant_content, 400))
        for name, out in tool_results:
            lines.append(f"工具 {name}: " + truncate(out, 300))
        source = "\n".join(lines)
        messages = [
            {"role": "system", "content": self.PROMPT},
            {"role": "user", "content": source},
        ]
        try:
            resp = self.backend.complete(messages, tools=None, temperature=0.0)
            text = (resp.content or "").strip()
        except Exception:
            text = ""
        if not text:
            return self.fallback.summarize_turn(step_index, assistant_content, tool_results)
        return truncate(text, self.max_chars)


class NoopSummarizer(Summarizer):
    """对照实验用:折叠时直接丢弃(用于评测摘要收益)。"""

    def summarize_turn(self, step_index: int, assistant_content: str,
                       tool_results: list[tuple[str, str]]) -> str:
        return f"[步骤 {step_index} 已折叠]"
