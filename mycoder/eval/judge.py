"""真实任务的 LLM-as-judge 评委。

评委只负责对任务目标、工作区快照和 rubric 做独立复核;文件是否存在/包含
关键内容仍由 deterministic assertions 判定,避免模型评委掩盖硬性失败。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ..models import ModelBackend


@dataclass
class JudgeVerdict:
    passed: bool
    score: float
    reasoning: str
    model: str = "unknown"
    raw: str = ""
    parse_ok: bool = True


class LLMJudge:
    """调用一个 OpenAI-compatible backend,输出严格 JSON 的代码评审结论。"""

    def __init__(self, backend: ModelBackend, model_name: str | None = None,
                 temperature: float = 0.0):
        self.backend = backend
        self.model_name = str(model_name or getattr(backend, "model", "unknown") or "unknown")
        self.temperature = temperature

    def judge(self, goal: str, file_snapshot: dict[str, str], rubric: str = "") -> JudgeVerdict:
        snapshot = "\n\n".join(
            f"### {path}\n```text\n{text}\n```" for path, text in sorted(file_snapshot.items())
        ) or "(工作区没有可读取文件)"
        prompt = (
            "你是严格、客观的代码评审员。请根据任务目标、工作区文件和评分标准判断实现是否完成。\n"
            "只输出一个 JSON 对象,不要 Markdown,格式为 "
            '{"pass":true或false,"score":0到5,"reasoning":"简短理由"}。\n\n'
            f"任务目标:\n{goal}\n\n评分标准:\n{rubric or '功能正确、边界处理合理、代码可维护。'}\n\n"
            f"工作区快照:\n{snapshot}"
        )
        try:
            response = self.backend.complete([
                {"role": "system", "content": "你是一个只返回 JSON 的代码评审员。"},
                {"role": "user", "content": prompt},
            ], temperature=self.temperature)
            raw = response.content or ""
        except Exception as exc:
            return JudgeVerdict(False, 0.0, f"评委调用失败: {exc}", self.model_name, "", False)
        return self._parse(raw)

    def _parse(self, raw: str) -> JudgeVerdict:
        text = raw.strip()
        obj: dict[str, Any] | None = None
        try:
            candidate = json.loads(text)
            if isinstance(candidate, dict):
                obj = candidate
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    candidate = json.loads(match.group(0))
                    if isinstance(candidate, dict):
                        obj = candidate
                except json.JSONDecodeError:
                    obj = None
        if obj is None:
            return JudgeVerdict(False, 0.0, f"评委输出无法解析为 JSON: {text[:240]}",
                                self.model_name, raw, False)
        passed = obj.get("pass", obj.get("passed", False))
        score = obj.get("score", 0)
        try:
            score = max(0.0, min(5.0, float(score)))
        except (TypeError, ValueError):
            score = 0.0
        reasoning = str(obj.get("reasoning", obj.get("reason", "无评语")))
        return JudgeVerdict(bool(passed), score, reasoning, self.model_name, raw, True)
