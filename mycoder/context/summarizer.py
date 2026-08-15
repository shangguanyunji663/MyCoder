"""历史摘要器。

为什么要有摘要器:裁剪"旧历史"时不能简单丢弃 —— 那会丢信息。我们用确定性
摘要把被折叠的历史压缩成要点文本,既降 token 又保留关键事实,且不引入模型
随机性(可复现)。

DeterministicSummarizer 是默认实现,接口留作扩展(真实场景可换成 LLM 摘要)。
"""
from __future__ import annotations

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


class NoopSummarizer(Summarizer):
    """对照实验用:折叠时直接丢弃(用于评测摘要收益)。"""

    def summarize_turn(self, step_index: int, assistant_content: str,
                       tool_results: list[tuple[str, str]]) -> str:
        return f"[步骤 {step_index} 已折叠]"