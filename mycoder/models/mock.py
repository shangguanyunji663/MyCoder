"""确定性 Mock 后端(第 1 类模型后端)。

用途:
  * 单元测试 / 基准评测:用脚本精确控制每轮输出,得到可复现的确定性结果;
  * 无任何外部依赖,真正全离线,符合"不需要云端服务"约束;
  * 也可作为"golden 参考轨迹",用于对拍真实模型后端的行为偏差。

脚本语义:script 是一个 list,每个元素是"一轮补全":
    {"tool_calls": [{"name": ..., "arguments": {...}}, ...]}   -> 该轮发起工具调用
    {"content": "最终回答文本"}                                  -> 该轮给出终答(终止)

轮次用尽后,若还没有终答,则返回一条兜底终答,避免 Harness 空转。
"""
from __future__ import annotations

import copy
from typing import Any

from .base import ModelBackend, ModelResponse


class MockBackend(ModelBackend):
    name = "mock"

    def __init__(self, script: list[dict] | None = None, seed: int = 42,
                 default_answer: str = "任务已完成。"):
        self.script: list[dict] = list(script or [])
        self.seed = seed
        self.default_answer = default_answer
        self._turn = 0
        self._call_seq = 0

    # ------------------------------------------------------------------
    @classmethod
    def from_recipe(cls, steps: list[dict], answer: str = "任务已完成。") -> MockBackend:
        """从"配方"构建脚本:steps 里每个 dict 是一次工具调用,逐个对应一轮。

        例:
          steps = [
            {"name": "file_list", "arguments": {"pattern": "*.py"}},
            {"name": "file_read", "arguments": {"path": "a.py"}},
          ]
        会先生成第 1 轮 file_list,收到结果后再生成第 2 轮 file_read,最后给出 answer。
        """
        script: list[dict[str, Any]] = [{"tool_calls": [dict(s)]} for s in steps]
        script.append({"content": answer})
        return cls(script=script)

    # ------------------------------------------------------------------
    def state(self) -> dict:
        """脚本游标:Resume 时据此从正确位置继续,而不是从头重放。"""
        return {"turn": self._turn, "call_seq": self._call_seq}

    def load_state(self, state: dict) -> None:
        self._turn = int(state.get("turn", self._turn))
        self._call_seq = int(state.get("call_seq", self._call_seq))

    # ------------------------------------------------------------------
    def complete(self, messages: list, tools: list[dict] | None = None,
                 temperature: float = 0.0) -> ModelResponse:
        entry = (self.script[self._turn]
                 if self._turn < len(self.script)
                 else {"content": self.default_answer})
        self._turn += 1

        entry = copy.deepcopy(entry)
        prompt_tokens = self.tokenize_len(_join_for_estimate(messages))
        if "tool_calls" in entry:
            calls = []
            for c in entry["tool_calls"]:
                c = dict(c)  # type: ignore[arg-type]  # 脚本元素按约定恒为 dict,宽类型来自 JSON 入口
                c.setdefault("id", f"call_{self._call_seq}")
                self._call_seq += 1
                calls.append(c)
            return ModelResponse(
                content=entry.get("content", ""),
                tool_calls=calls,
                finish_reason="tool_calls",
                usage={"prompt_tokens": prompt_tokens, "completion_tokens": 10},
            )
        content = entry.get("content", self.default_answer)
        return ModelResponse(
            content=content,
            finish_reason="stop",
            usage={"prompt_tokens": prompt_tokens, "completion_tokens": self.tokenize_len(content)},
        )


def _join_for_estimate(messages: list) -> str:
    parts = []
    for m in messages:
        if isinstance(m, dict):
            parts.append(str(m.get("content", "")))
        else:
            parts.append(str(getattr(m, "content", "")))
    return "\n".join(parts)
