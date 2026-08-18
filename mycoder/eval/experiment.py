"""对照实验(A/B)原语与指标差分。

评测闭环要求"对照实验":固定任务、固定数据、仅改变一个系统开关
(如 上下文治理开/关、记忆开/关),对比指标变化,从而把"系统能力增益"
与"模型能力"拆开 —— 因为两边用的是同一个 mock 轨迹,唯一变量是 harness 系统开关。
"""
from __future__ import annotations

from typing import Any


def compare_metrics(a: dict, b: dict) -> dict:
    """对比两个指标快照,返回 {指标: {a, b, diff}}。diff = b - a(数值型)。"""
    keys = sorted(set(a) | set(b))
    out: dict[str, dict] = {}
    for k in keys:
        va, vb = a.get(k), b.get(k)
        entry: dict[str, Any] = {"a": va, "b": vb}
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            entry["diff"] = round(vb - va, 4)
        out[k] = entry
    return out


def format_delta(delta: dict, label_a: str, label_b: str) -> str:
    lines = [f"对照({label_a} -> {label_b}):"]
    for k, v in delta.items():
        if "diff" in v:
            lines.append(f"  {k}: {v['a']} -> {v['b']}  (Δ {v['diff']:+})")
        else:
            lines.append(f"  {k}: {v['a']} -> {v['b']}")
    return "\n".join(lines)
