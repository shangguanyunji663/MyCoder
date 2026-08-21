"""MyCoder 轨迹 -> 监督微调(SFT)数据集 导出与清洗。

用途
----
把 MyCoder 运行产出的工件转换为可用于 LoRA/全参微调的训练数据:

  1. 从 .mycoder/artifacts/**/sft_samples.jsonl 读取 (instruction, output[, context])
     —— 这是 artifacts.sft_log=true 时由 harness 顺带产出的"干净"样本;
  2. 从 .mycoder/artifacts/**/trajectory.jsonl 读取 agentic 骨架(可选,用于
     "agent" 模式:保留工具调用轨迹,训练会调用工具的 agent 模型);
  3. 清洗:丢弃未完成任务、去重(按内容哈希)、长度越界过滤、敏感信息脱敏;
  4. 输出两种格式:ChatML(jsonl, 推荐给 TRL)+ Alpaca(jsonl, 兼容旧管线)。

设计
----
零依赖(仅标准库),可在没有 torch/transformers 的环境直接跑清洗与预览。

用法
----
  # 基础:扫描默认工件目录,输出到 kb_lora/data/
  python export_sft.py

  # 指定工件根目录与输出目录
  python export_sft.py --artifacts-root .mycoder/artifacts --out kb_lora/data

  # KB 问答模式:把 context 作为系统提示前缀,训练"带检索上下文作答"的模型
  python export_sft.py --mode kb

  # agent 模式:把 trajectory 的工具调用轨迹转为多轮对话 SFT
  python export_sft.py --mode agent

  # 仅预览统计,不写文件
  python export_sft.py --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# 敏感信息脱敏(与 harness 的 Redactor 思路一致,这里用轻量正则)
# --------------------------------------------------------------------------
_RE_SECRET = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|pwd)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def redact(text: str) -> str:
    for rx in _RE_SECRET:
        text = rx.sub("[REDACTED]", text)
    return text


# --------------------------------------------------------------------------
# 读取
# --------------------------------------------------------------------------

def iter_jsonl(p: Path):
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def load_sft_samples(artifacts_root: Path) -> list[dict]:
    out = []
    for p in sorted(artifacts_root.rglob("sft_samples.jsonl")):
        for rec in iter_jsonl(p):
            out.append(rec)
    return out


def load_trajectories(artifacts_root: Path) -> list[list[dict]]:
    """返回若干条轨迹(每条是 event 列表)。"""
    out = []
    for p in sorted(artifacts_root.rglob("trajectory.jsonl")):
        evs = list(iter_jsonl(p))
        if evs:
            out.append(evs)
    return out


# --------------------------------------------------------------------------
# 清洗
# --------------------------------------------------------------------------

# 过短/过长阈值(字符)。KB 答案通常 50~2000 字;指令至少 5 字。
MIN_INSTRUCTION = 5
MIN_OUTPUT = 10
MAX_OUTPUT = 6000
MAX_INSTRUCTION = 4000


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def clean_samples(raw: list[dict]) -> tuple[list[dict], dict]:
    """清洗 sft_samples,返回 (清洗后样本, 统计)。"""
    stats = {"in": len(raw), "dropped_status": 0, "dropped_empty": 0,
             "dropped_short": 0, "dropped_long": 0, "dup": 0, "out": 0}
    seen = set()
    out = []
    for rec in raw:
        if rec.get("status") != "completed":
            stats["dropped_status"] += 1
            continue
        instr = _norm(rec.get("instruction", ""))
        output = _norm(rec.get("output", ""))
        ctx = _norm(rec.get("context", ""))
        if not instr or not output:
            stats["dropped_empty"] += 1
            continue
        if len(instr) < MIN_INSTRUCTION or len(output) < MIN_OUTPUT:
            stats["dropped_short"] += 1
            continue
        if len(output) > MAX_OUTPUT or len(instr) > MAX_INSTRUCTION:
            stats["dropped_long"] += 1
            continue
        # 去重:基于 (instruction, output, context) 归一化后的哈希
        key = hashlib.sha1(f"{instr}|||{output}|||{ctx}".encode("utf-8")).hexdigest()
        if key in seen:
            stats["dup"] += 1
            continue
        seen.add(key)
        out.append({
            "instruction": redact(instr),
            "output": redact(output),
            "context": redact(ctx),
            "task_id": rec.get("task_id", ""),
        })
    stats["out"] = len(out)
    return out, stats


# --------------------------------------------------------------------------
# 格式转换
# --------------------------------------------------------------------------

def to_chatml(sample: dict, mode: str) -> dict:
    """转 ChatML。mode='kb' 时把 context 放进 system;mode='plain' 直接问答。"""
    ctx = sample.get("context", "")
    if mode == "kb" and ctx:
        system = ("你是一个企业知识库助手。请仅依据下面提供的资料回答问题,"
                  "资料中没有的信息请如实说明不知道。\n\n【资料】\n" + ctx)
    else:
        system = "你是一个严谨、乐于助人的企业知识库助手。"
    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": sample["instruction"]},
            {"role": "assistant", "content": sample["output"]},
        ]
    }


def to_alpaca(sample: dict, mode: str) -> dict:
    ctx = sample.get("context", "")
    if mode == "kb" and ctx:
        return {
            "instruction": sample["instruction"],
            "input": "【资料】\n" + ctx,
            "output": sample["output"],
        }
    return {
        "instruction": sample["instruction"],
        "input": "",
        "output": sample["output"],
    }


def trajectory_to_agent_samples(trajectories: list[list[dict]]) -> list[dict]:
    """把 agentic 轨迹转为多轮(工具调用)SFT 样本。

    仅取成功终答的轨迹:把每个 step 的 assistant 文本 + 工具调用拼成
    assistant 消息,工具结果作为 user 消息,最终步作为终答。适合训练
    "会调用工具的 agent" 而非纯 KB 问答。
    """
    out = []
    for evs in trajectories:
        steps = [e for e in evs if e.get("type") == "step"]
        if not steps:
            continue
        last = steps[-1]
        if last.get("assistant", {}).get("tool_calls"):
            continue  # 末步仍有工具调用 => 未终答,跳过
        final_out = _norm(last.get("assistant", {}).get("content", ""))
        if len(final_out) < MIN_OUTPUT:
            continue
        messages = [{"role": "system",
                     "content": "你是一个会调用工具完成任务的编程助手。"}]
        for s in steps:
            a = s.get("assistant", {})
            content = a.get("content", "") or ""
            tcs = a.get("tool_calls") or []
            if content or tcs:
                messages.append({"role": "assistant",
                                 "content": content,
                                 "tool_calls": tcs})
            # 工具结果作为 user 回传
            for tc in s.get("tool_calls", []):
                if tc.get("status") == "ok":
                    messages.append({"role": "user",
                                     "content": f"[工具 {tc.get('name')} 返回] "
                                                f"{str(tc.get('meta', ''))[:2000]}"})
        if len(messages) >= 3:
            out.append({"messages": messages})
    return out


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MyCoder 轨迹 -> SFT 数据集导出")
    ap.add_argument("--artifacts-root", default=".mycoder/artifacts",
                    help="MyCoder 工件根目录(含各 task_id 子目录)")
    ap.add_argument("--out", default="kb_lora/data", help="输出目录")
    ap.add_argument("--mode", choices=["kb", "plain", "agent"], default="kb",
                    help="kb=知识库问答(带上下文);plain=纯指令问答;"
                         "agent=从轨迹生成工具调用样本")
    ap.add_argument("--format", choices=["chatml", "alpaca", "both"], default="both")
    ap.add_argument("--dry-run", action="store_true", help="只打印统计,不写文件")
    args = ap.parse_args(argv)

    root = Path(args.artifacts_root)
    if not root.exists():
        print(f"[ERROR] 工件目录不存在: {root}", file=sys.stderr)
        return 2

    # 1) sft_samples(主数据源)
    raw = load_sft_samples(root)
    clean, stats = clean_samples(raw)

    # 2) agent 模式额外从轨迹生成
    agent_samples = []
    if args.mode == "agent":
        trajs = load_trajectories(root)
        agent_samples = trajectory_to_agent_samples(trajs)
        stats["agent_from_trajectory"] = len(agent_samples)

    # 输出内容
    if args.mode == "agent":
        records = agent_samples
    else:
        fmt_fn = to_chatml if args.format == "chatml" else to_alpaca
        if args.format == "both":
            records_chatml = [to_chatml(s, args.mode) for s in clean]
            records_alpaca = [to_alpaca(s, args.mode) for s in clean]
        else:
            records = [fmt_fn(s, args.mode) for s in clean]

    print("=" * 56)
    print("清洗统计(sft_samples.jsonl)")
    for k, v in stats.items():
        print(f"  {k:22s}: {v}")
    if args.mode == "agent":
        print(f"  agent 样本数       : {len(agent_samples)}")
    else:
        print(f"  -> 可用 SFT 样本   : {len(clean)}")
    print("=" * 56)

    if args.dry_run:
        print("[dry-run] 未写入任何文件。")
        return 0

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "agent":
        _write_jsonl(out_dir / "sft_agent_chatml.jsonl", agent_samples)
        print(f"已写出: {out_dir / 'sft_agent_chatml.jsonl'}")
    elif args.format == "both":
        _write_jsonl(out_dir / "sft_chatml.jsonl", records_chatml)
        _write_jsonl(out_dir / "sft_alpaca.jsonl", records_alpaca)
        print(f"已写出: {out_dir / 'sft_chatml.jsonl'}")
        print(f"已写出: {out_dir / 'sft_alpaca.jsonl'}")
    else:
        suffix = "chatml" if args.format == "chatml" else "alpaca"
        _write_jsonl(out_dir / f"sft_{suffix}.jsonl", records)
        print(f"已写出: {out_dir / f'sft_{suffix}.jsonl'}")
    return 0


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
