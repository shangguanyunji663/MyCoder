"""运行工件:轨迹(trajectory.jsonl)、检查点(checkpoint.json)、指标报告(metrics.json / report.md)。

三类工件对应"结果可复盘"诉求:
  1. trajectory.jsonl —— 逐步追加的完整轨迹,任何时刻崩溃都能复盘已发生的事;
  2. checkpoint.json  —— 可恢复断点(由 checkpoint 模块落盘,此处聚合到工件目录);
  3. metrics.json + report.md —— 聚合指标与人类可读报告(压缩率/工具统计/预算合规等)。

所有工件导出前统一过 Redactor 脱敏。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config
from .util import atomic_write, ensure_dir, json_dump, now_iso


@dataclass
class Metrics:
    """运行期指标累加器(线程不安全,单进程顺序使用)。"""

    steps: int = 0
    tool_calls: int = 0
    read_calls: int = 0
    read_cache_hits: int = 0          # 去重/记忆短路命中的读次数
    write_calls: int = 0
    prompt_tokens_total: int = 0
    completion_tokens_total: int = 0
    cost_usd: float = 0.0            # 若配置了 model.pricing 则累计,否则为 0
    prompt_budget_tokens: int = 0
    latency_ms_total: int = 0
    prunes: int = 0
    compression_ratios: list = field(default_factory=list)
    files_remembered: int = 0
    memory_queries: int = 0
    denied_actions: int = 0
    skipped_repeats: int = 0

    def avg_compression_ratio(self) -> float:
        if not self.compression_ratios:
            return 0.0
        return sum(self.compression_ratios) / len(self.compression_ratios)

    def max_compression_ratio(self) -> float:
        return max(self.compression_ratios, default=0.0)

    def prompt_under_budget(self, budget_tokens: int) -> bool:
        # 每一步均未超出软预算的合规率近似:此处以累计平均判断
        if self.steps == 0:
            return True
        return (self.prompt_tokens_total / self.steps) <= budget_tokens

    def snapshot(self) -> dict:
        return {
            "steps": self.steps,
            "tool_calls": self.tool_calls,
            "read_calls": self.read_calls,
            "read_cache_hits": self.read_cache_hits,
            "write_calls": self.write_calls,
            "prompt_tokens_total": self.prompt_tokens_total,
            "completion_tokens_total": self.completion_tokens_total,
            "cost_usd": round(self.cost_usd, 6),
            "avg_prompt_tokens": round(self.prompt_tokens_total / self.steps, 2) if self.steps else 0,
            "avg_completion_tokens": (round(self.completion_tokens_total / self.steps, 2)
                                      if self.steps else 0),
            "avg_latency_ms": round(self.latency_ms_total / self.steps, 1) if self.steps else 0,
            "prunes": self.prunes,
            "avg_compression_ratio": round(self.avg_compression_ratio(), 4),
            "max_compression_ratio": round(self.max_compression_ratio(), 4),
            "files_remembered": self.files_remembered,
            "memory_queries": self.memory_queries,
            "denied_actions": self.denied_actions,
            "skipped_repeats": self.skipped_repeats,
        }


class RunRecorder:
    """轨迹记录器:逐行追加写 trajectory.jsonl,崩溃可恢复。"""

    def __init__(self, path: Path, redactor=None):
        self.path = Path(path)
        ensure_dir(self.path.parent)
        self.redactor = redactor
        self._count = 0

    def record(self, obj: dict) -> None:
        import json

        text = json.dumps(obj, ensure_ascii=False, default=str)
        if self.redactor is not None:
            text = self.redactor.redact(text)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
        self._count += 1


class ArtifactManager:
    """统一工件目录管理与导出。

    目录结构:
      artifacts/
        {task_id}/
          trajectory.jsonl
          checkpoint.json
          metrics.json
          report.md
    """

    def __init__(self, root: str | Path, config: Config, redactor=None):
        self.root = Path(root)
        self.config = config
        self.redactor = redactor

    def task_dir(self, task_id: str) -> Path:
        return ensure_dir(self.root / task_id)

    def export(self, task_id: str, metrics: Metrics, result: dict,
               checkpoint_obj: Any = None) -> dict[str, str]:
        """导出三类工件,返回 工件名->绝对路径 映射。"""
        d = self.task_dir(task_id)
        paths: dict[str, str] = {}

        # 1. 检查点(如有)
        if checkpoint_obj is not None:
            cp = d / "checkpoint.json"
            json_dump(checkpoint_obj, cp, redactor=self.redactor)
            paths["checkpoint"] = str(cp)

        # 2. 指标
        m = d / "metrics.json"
        json_dump(metrics.snapshot(), m, redactor=self.redactor)
        paths["metrics"] = str(m)

        # 3. 人类可读报告
        report = self._render_report(task_id, metrics, result, task_dir=d)
        if self.redactor is not None:
            report = self.redactor.redact(report)
        r = d / "report.md"
        atomic_write(r, report)
        paths["report"] = str(r)

        # 轨迹文件由 RunRecorder 持续写入,这里确认其路径并在导出清单中标出
        tr = d / "trajectory.jsonl"
        if tr.exists():
            paths["trajectory"] = str(tr)
        return paths

    @staticmethod
    def _render_report(task_id: str, metrics: Metrics, result: dict,
                       task_dir: Path | None = None) -> str:
        m = metrics.snapshot()
        lines = [
            f"# MyCoder 运行报告 — {task_id}",
            "",
            f"- 生成时间: {now_iso()}",
            f"- 任务状态: {result.get('status', 'unknown')}",
            f"- 步数: {m['steps']} / 工具调用: {m['tool_calls']}",
            f"- Token 用量: prompt={m['prompt_tokens_total']}, completion={m['completion_tokens_total']}"
            + (f", 估计成本=${m['cost_usd']:.5f}" if m['cost_usd'] > 0 else ""),
            f"- 平均延迟: {m['avg_latency_ms']:.0f}ms/步",
            "",
            "## 上下文治理",
            f"- 平均压缩率: {m['avg_compression_ratio']*100:.2f}%",
            f"- 最高压缩率: {m['max_compression_ratio']*100:.2f}%",
            f"- 裁剪次数: {m['prunes']}",
            "",
            "## 工具与记忆",
            f"- 读文件: {m['read_calls']} / 缓存命中: {m['read_cache_hits']}",
            f"- 写文件: {m['write_calls']}",
            f"- 沉淀文件摘要: {m['files_remembered']} / 记忆查询: {m['memory_queries']}",
            f"- 拦截动作: {m['denied_actions']} / 重复跳过: {m['skipped_repeats']}",
            "",
            "## 耗时时间线与成本",
        ]
        # 从 trajectory.jsonl 重建逐步时间线(零额外存储,仅读取既有工件)
        timeline = _build_timeline(task_dir)
        if timeline:
            lines.append("")
            lines.append("| 步 | 事件 | 延迟(ms) | prompt tokens | completion tokens |")
            lines.append("| --- | --- | ---: | ---: | ---: |")
            for row in timeline:
                lines.append(f"| {row['index']} | {row['kind']} | {row['latency_ms']} "
                             f"| {row['prompt_tokens']} | {row['completion_tokens']} |")
            lines.append("")
            lines.append(f"- 总工具/模型调用延迟: {sum(r['latency_ms'] for r in timeline)}ms")
        else:
            lines.append("")
            lines.append("> (无可用的轨迹时间线数据)")
        if m['cost_usd'] > 0:
            lines.append(f"- 本次运行估计成本: ${m['cost_usd']:.5f}")
        lines += [
            "",
            "## 最终回答",
            "",
            _quote(result.get("final_answer", "")),
        ]
        return "\n".join(lines)


def _quote(text: str) -> str:
    text = (text or "").strip() or "(无)"
    return "\n".join("> " + ln for ln in text.splitlines()) if text else "> " + text


def _build_timeline(task_dir: Path | None) -> list[dict]:
    """从 trajectory.jsonl 重建逐步耗时时间线(零额外存储,只读既有工件)。"""
    if task_dir is None:
        return []
    p = Path(task_dir) / "trajectory.jsonl"
    if not p.exists():
        return []
    rows: list[dict] = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            t = ev.get("type")
            if t == "model_call":
                rows.append({"index": ev.get("index"), "kind": "model_call",
                             "latency_ms": ev.get("latency_ms", 0),
                             "prompt_tokens": ev.get("prompt_tokens", 0),
                             "completion_tokens": ev.get("completion_tokens", 0)})
            elif t == "tool_call":
                rows.append({"index": ev.get("step_index"), "kind": f"tool:{ev.get('name')}",
                             "latency_ms": ev.get("latency_ms", 0),
                             "prompt_tokens": 0, "completion_tokens": 0})
    except Exception:
        return []
    return rows
