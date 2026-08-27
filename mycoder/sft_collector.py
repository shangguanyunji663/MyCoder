"""SFT 样本采集器(可选增强,默认关闭)。

定位:让 MyCoder 在跑真实任务时,顺带产出可微调用的监督数据。
当前 trajectory.jsonl 只记录"agentic 骨架"(task_id / 每步 assistant 推理 /
工具调用元信息 / token),**不含原始指令文本、不含检索上下文、不含最终答案**,
因此无法直接当作 SFT 样本。本模块弥补这一点:在任务成功结束时,把
(instruction=goal, output=final_answer, context=可选检索上下文) 写成独立的
sft_samples.jsonl,与 trajectory.jsonl 并存于同一工件目录。

设计原则:
- 零依赖,只用到标准库 + 已存在的 Redactor(脱敏复用现有能力)。
- 通过 artifacts.sft_log 配置开关控制,默认关闭,绝不破坏既有行为。
- 与 trajectory.jsonl 解耦:即使关闭本采集器,轨迹与评测照常工作。
"""
from __future__ import annotations

import json
from pathlib import Path

from .util import ensure_dir, now_iso


def write_sft_sample(task_dir: Path, *, task_id: str, instruction: str,
                      output: str, context: str | None = None,
                      status: str = "completed", redactor=None) -> str | None:
    """向 {task_dir}/sft_samples.jsonl 追加一条 SFT 样本。

    返回写入的文件路径;若 instruction / output 为空则跳过并返回 None。
    """
    instruction = (instruction or "").strip()
    output = (output or "").strip()
    if not instruction or not output:
        return None

    sample = {
        "task_id": task_id,
        "status": status,
        "instruction": instruction,
        "output": output,
        "context": (context or "").strip(),
        "ts": now_iso(),
    }
    text = json.dumps(sample, ensure_ascii=False, default=str)
    if redactor is not None:
        text = redactor.redact(text)

    p = ensure_dir(task_dir) / "sft_samples.jsonl"
    with open(p, "a", encoding="utf-8") as f:
        f.write(text + "\n")
    return str(p)


def finalize_index(artifacts_root: str | Path) -> dict:
    """汇总所有 sft_samples.jsonl,返回一个轻量索引(计数 / 状态分布)。

    便于训练前快速了解数据规模,不读取完整内容。
    """
    root = Path(artifacts_root)
    counts: dict[str, int] = {}
    total = 0
    for p in root.rglob("sft_samples.jsonl"):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                total += 1
                st = rec.get("status", "unknown")
                counts[st] = counts.get(st, 0) + 1
        except Exception:
            continue
    return {"total": total, "by_status": counts}
