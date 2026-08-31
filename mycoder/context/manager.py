"""上下文管理器:按「任务目标 / 当前文件 / 历史摘要 / 工具结果」组织并裁剪上下文。

核心算法(纯函数式、可复现):
  1. base      = system 提示 + 任务目标 + 当前处理文件 + 记忆块(结构化记忆注入);
  2. before    = base + 完整历史(对话)的 token —— 代表"不做治理"的 prompt 长度;
  3. 治理      = 只保留最近 keep_last_turns 轮原文,更早的轮折叠成滚动摘要;
  4. 裁剪      = 若仍超硬上限,对超长消息内容做头尾截断;
  5. after     = 治理后实际送入模型的 token。

压缩率 = 1 - after/before。每次都从完整历史重算,避免增量折叠的状态漂移,
保证同一输入必得同一输出(确定性评测的关键)。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from ..state import Message
from ..util import truncate
from .summarizer import DeterministicSummarizer, Summarizer
from .tokens import estimate_messages

SYSTEM_PROMPT = (
    "你是 MyCoder,一个本地编码 Agent,在给定工作区内完成代码任务。\n"
    "你通过工具调用操作文件与执行命令。所有路径必须是工作区内的相对路径。\n"
    "优先使用历史摘要与结构化记忆中的信息,避免重复读取同一文件。\n"
    "当任务完成时,直接给出简洁的最终回答,不要再发起工具调用。"
)


@dataclass
class PruneInfo:
    """一次 assembled prompt 的裁剪信息。"""
    before_tokens: int = 0
    after_tokens: int = 0
    pruned: bool = False
    strategies: list = field(default_factory=list)

    @property
    def ratio(self) -> float:
        if self.before_tokens <= 0:
            return 0.0
        return max(0.0, 1.0 - self.after_tokens / self.before_tokens)


class ContextManager:
    def __init__(self, config, summarizer: Summarizer | None = None):
        self.config = config
        self.summarizer = summarizer or DeterministicSummarizer()
        self.goal = ""
        self.files_hint: list[str] = []
        self.memory_block = ""
        self.raw_turns: list[dict] = []   # 完整历史(每轮 {"assistant": msg, "tool": [msg...]})
        self.last_prune = PruneInfo()

    # ------------------------------------------------------------------
    def set_task(self, goal: str, files_hint: list[str] | None = None,
                 memory_block: str = "") -> None:
        self.goal = goal
        self.files_hint = list(files_hint or [])
        self.memory_block = memory_block

    def append_turn(self, assistant: Message, tool_msgs: list[Message],
                    user: Message | None = None) -> None:
        """追加一轮对话;user 为可选的轮末用户追问(空终答重问提醒)。"""
        turn: dict = {"assistant": assistant, "tool": list(tool_msgs)}
        if user is not None:
            turn["user"] = user
        self.raw_turns.append(turn)

    def set_memory_block(self, memory_block: str) -> None:
        self.memory_block = memory_block

    def set_files_hint(self, files: list[str]) -> None:
        self.files_hint = list(files)

    def _base_messages(self) -> list[Message]:
        msgs = [Message("system", SYSTEM_PROMPT)]
        if self.goal:
            msgs.append(Message("user", "# 任务目标\n" + self.goal))
        if self.files_hint:
            msgs.append(Message("system", "# 当前处理文件\n" +
                                "\n".join("- " + f for f in self.files_hint)))
        if self.memory_block:
            msgs.append(Message("system", self.memory_block))
        return msgs

    @staticmethod
    def _flatten(turns: list[dict]) -> list[Message]:
        out: list[Message] = []
        for t in turns:
            out.append(t["assistant"])
            out.extend(t["tool"])
            if t.get("user") is not None:
                out.append(t["user"])
        return out

    def _fold_summary(self, turns: list[dict]) -> str:
        parts = []
        for i, t in enumerate(turns, 1):
            tool_results = [(m.name or "tool", m.content) for m in t["tool"]]
            parts.append(self.summarizer.summarize_turn(
                i, t["assistant"].content, tool_results))
        return "\n".join(parts)

    # ------------------------------------------------------------------
    def assemble(self) -> list[Message]:
        """组装并裁剪,返回送入模型的消息列表;裁剪刀口记录在 last_prune。

        注意:裁剪在"深拷贝的消息"上进行,绝不改动 raw_turns 里的原始历史,
        保证同一历史可被多轮 assemble 重复、确定性地重放(打底评测可复现)。
        """
        cfg = self.config
        base = self._base_messages()
        all_turns = self._flatten(self.raw_turns)
        before = estimate_messages(base + all_turns)  # 不做治理的 prompt 长度

        keep = max(1, int(cfg.get("context.keep_last_turns", 6)))
        hard = int(cfg.get("context.hard_limit_tokens", 6000))
        strategies: list[str] = []

        visible = self.raw_turns[-keep:] if len(self.raw_turns) > keep else self.raw_turns
        folded = self.raw_turns[:-keep] if len(self.raw_turns) > keep else []
        if folded:
            strategies.append("fold_old_turns")

        msgs = list(base)
        if folded:
            msgs.append(Message("system", "# 历史摘要\n" + self._fold_summary(folded)))
        msgs.extend(copy.deepcopy(self._flatten(visible)))

        # 兜底策略 1:仍超硬限 -> 折叠到只保留最近 1 轮原文
        if estimate_messages(msgs) > hard and len(visible) > 1:
            strategies.append("drop_stale_turns")
            visible = self.raw_turns[-1:]
            folded = self.raw_turns[:-1]
            msgs = list(base)
            msgs.append(Message("system", "# 历史摘要\n" + self._fold_summary(folded)))
            msgs.extend(copy.deepcopy(self._flatten(visible)))

        # 兜底策略 2:硬限额强制收缩,逐级截断最长消息,保证 100% 预算内
        if estimate_messages(msgs) > hard:
            strategies.append("truncate_long_content")
            msgs = self._enforce_budget(msgs, hard)

        after = estimate_messages(msgs)
        self.last_prune = PruneInfo(
            before_tokens=before, after_tokens=after,
            pruned=after < before, strategies=strategies,
        )
        return msgs

    def _enforce_budget(self, msgs: list[Message], hard: int) -> list[Message]:
        """把 prompt 硬压到 hard 以内:先截断超长内容,再收缩最长消息。"""
        cap = int(self.config.get("context.max_file_content_chars", 8000))
        for m in msgs:
            if len(m.content) > cap:
                m.content = truncate(m.content, cap)
        # 确定性收缩:反复把最长的消息缩到 60%,直到达标或无法再缩
        while estimate_messages(msgs) > hard:
            candidates = [m for m in msgs if m.content]
            if not candidates:
                break
            largest = max(candidates, key=lambda m: len(m.content))
            if len(largest.content) <= 40:
                break
            largest.content = truncate(largest.content, max(40, int(len(largest.content) * 0.6)))
        return msgs

    def current_prompt_tokens(self) -> int:
        return self.last_prune.after_tokens
