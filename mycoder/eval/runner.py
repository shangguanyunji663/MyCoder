"""五层评测运行器(评测加固版)。

五层职责(刻意分离,避免混淆"模型能力"与"系统能力"):
  1. harness 回归   —— 正例 + 负例(应拦截/应失败)+ 边界用例,度量 X/Y 通过率;
  2. 上下文治理     —— 治理 vs 不治理 的压缩收益 + 折叠后的"信息保留率"探针
                        + 贴边预算与多层折叠边界;
  3. 记忆收益       —— 按 fresh_hit / stale / wrong_hit / missing 场景矩阵分别判定;
  4. 恢复正确性     —— 多任务 x 停点 x 漂移类型(content/whitespace/reformat/large-scale)
                        矩阵,漂移识别与恢复后内容正确性双指标;
  5. 检索召回       —— 四类查询(exact/synonym/distractor/empty)分别判定 + MRR@5。

所有层仍用【同一个确定性 mock 轨迹】驱动,唯一变化的是 harness 系统开关,
因此测到的是系统能力而非模型能力。指标以 X/Y 通过率呈现(ok 为阈值判定而非
二值 100%),运行工件聚合在 output_dir 下可复现,并追加 eval_history.jsonl
供跨次退化对比。
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from ..config import Config
from ..memory import StructuredMemory
from ..memory.vectors import (
    BM25,
    EmbeddingProvider,
    FastEmbedEmbedder,
    HashingEmbedder,
    HybridRetriever,
    VectorIndex,
    tokenize,
)
from ..models import MockBackend
from ..safety import AllowAllProvider
from ..state import RunResult, TaskInput
from ..util import now_iso, sha256_file
from .benchmark import by_layer, load_benchmarks

_BENCH_DIR = Path(__file__).resolve().parent.parent.parent / "benchmarks"
# 检索评测集分两份:手写核心(retrieval.json)+ 扩样领域(retrieval_extra.json),
# 加载时合并;缺失的文件自动跳过,保持可复现。
_RETRIEVAL_PATHS = [
    _BENCH_DIR / "retrieval.json",
    _BENCH_DIR / "retrieval_extra.json",
]

# 各层 ok 判定阈值:通过率达到该值才判 ok(而非二值 100%),指标退化可被察觉
_PASS_THRESHOLD = 0.9


def _generate_file(spec: dict) -> str:
    kind = spec.get("kind", "text")
    count = int(spec.get("count", 100))
    # 探针写入文件头部:折叠摘要按头部截断保留,据此度量上下文信息保留率
    header = "".join(f"# {p}\n" for p in spec.get("probes", []))
    if kind == "functions":
        return header + "\n".join(
            f"def func_{i}(x):  # 函数 {i} 的实现,用于制造长上下文\n    return x * {i} + 1\n"
            for i in range(count))
    if kind == "logs":
        levels = ("INFO", "WARN", "ERROR", "DEBUG")
        return header + "\n".join(
            f"{levels[i % 4]} [task{i}] 处理第 {i} 条记录,耗时 {i % 97}ms,状态 normal,payload_size={i % 512}"
            for i in range(count))
    return str(spec.get("content", ""))


class EvalRunner:
    def __init__(self, config: Config, output_dir: str | Path = ".mycoder/eval",
                 benchmark_path: str | Path | None = None,
                 summarizer=None):
        self.base_config = config
        self.output_dir = Path(output_dir)
        self.benchmark_path = str(benchmark_path) if benchmark_path else None
        # 可注入摘要器工厂用于 Layer-2 A/B(缺省 None = 只跑确定性摘要)
        self.summarizer = summarizer

    # ------------------------------------------------------------------
    def run_suite(self, suite: str = "all") -> dict[str, dict]:
        self._reset()
        tasks = load_benchmarks(self.benchmark_path)
        reports: dict[str, dict] = {}
        if suite in ("all", "regression"):
            reports["regression"] = self.layer_regression(tasks)
        if suite in ("all", "context"):
            reports["context"] = self.layer_context(tasks)
        if suite in ("all", "memory"):
            reports["memory"] = self.layer_memory(tasks)
        if suite in ("all", "resume"):
            reports["resume"] = self.layer_resume(tasks)
        if suite in ("all", "retrieval"):
            reports["retrieval"] = self.layer_retrieval()
        if suite == "embedder":
            reports["embedder"] = self.layer_embedder_ab()
        if suite == "real":
            from .real import RealTaskRunner
            reports["real"] = RealTaskRunner(
                self.base_config, output_dir=self.output_dir,
                tasks_path=self.base_config.get("eval.real.tasks")
            ).run()
        if suite == "real_baseline":
            from .raw_baseline import RawBaselineRunner
            reports["real_baseline"] = RawBaselineRunner(
                self.base_config, output_dir=self.output_dir,
                tasks_path=self.base_config.get("eval.real_baseline.tasks")
            ).run()
        self._append_history(reports)
        return reports

    def write_report(self, reports: dict[str, dict]) -> None:
        ensure = self.output_dir
        ensure.mkdir(parents=True, exist_ok=True)
        (ensure / "report.json").write_text(
            json.dumps(reports, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        md = ["# MyCoder 评测报告", ""]
        for name, rep in reports.items():
            md += [f"## Layer: {name}",
                   f"- ok: {rep.get('ok')}",
                   f"- 通过率: {rep.get('passed')}/{rep.get('total')}"
                   f"(pass_rate={rep.get('pass_rate')})",
                   f"- {rep.get('summary', '')}", ""]
            for d in rep.get("details", []):
                md.append("- " + str(d))
            md.append("")
        (ensure / "report.md").write_text("\n".join(md), encoding="utf-8")

    def _append_history(self, reports: dict[str, dict]) -> None:
        """评测历史落盘:每次运行追加一行,供跨次指标退化对比(失败不影响评测)。"""
        try:
            rec = {"ts": now_iso(), "layers": {
                k: {"ok": v.get("ok"), "passed": v.get("passed"),
                    "total": v.get("total"), "pass_rate": v.get("pass_rate")}
                for k, v in reports.items()}}
            with open(self.output_dir / "eval_history.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 基础设施
    def _reset(self) -> None:
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _cfg_for(self, workdir: Path, budget: int | None = None,
                 keep_turns: int | None = None, memory_enabled: bool | None = None) -> Config:
        cfg = Config(self.base_config.to_dict())
        cfg.set("workspace.root", str(workdir / "ws"))
        cfg.set("memory.root", str(workdir / "memory"))
        if memory_enabled is not None:
            cfg.set("memory.enabled", memory_enabled)
        cfg.set("checkpoint.root", str(workdir / "checkpoints"))
        cfg.set("artifacts.root", str(workdir / "artifacts"))
        if budget is not None:
            cfg.set("context.budget_tokens", budget)
            cfg.set("context.hard_limit_tokens", int(budget * 1.5))
        if keep_turns is not None:
            cfg.set("context.keep_last_turns", keep_turns)
        return cfg

    def _setup_files(self, harness, task: dict) -> None:
        for rel, content in (task.get("setup_files") or {}).items():
            harness.workspace.write_text(rel, content)
        for rel, spec in (task.get("generate_files") or {}).items():
            harness.workspace.write_text(rel, _generate_file(spec))

    def _run(self, task: dict, workdir: Path, script_field: str = "script",
             memory_enabled: bool | None = None, budget: int | None = None,
             keep_turns: int | None = None, stop_after: int | None = None,
             summarizer=None):
        from ..agent import AgentHarness
        cfg = self._cfg_for(workdir, budget=budget, keep_turns=keep_turns,
                            memory_enabled=memory_enabled)
        backend = MockBackend(script=task.get(script_field) or [],
                              default_answer=task.get("answer", "任务已完成。"))
        harness = AgentHarness.build(cfg, backend=backend, approver=AllowAllProvider())
        if summarizer is not None:
            harness.context.summarizer = summarizer
        self._setup_files(harness, task)
        task_input = TaskInput(task_id=task["task_id"], goal=task.get("goal", ""),
                               files_hint=task.get("files_hint", []),
                               follow_up_of=task.get("follow_up_of"),
                               extra=task.get("extra", {}))
        result = harness.run(task_input, stop_after_steps=stop_after)
        return result, harness

    def _resume(self, task: dict, workdir: Path):
        from ..agent import AgentHarness
        cfg = self._cfg_for(workdir)
        # 使用与原任务相同的脚本;harness.resume 会从 checkpoint 恢复后端游标,
        # 因此会从被中断处继续,而不是从头重放。
        backend = MockBackend(script=task.get("script") or [],
                              default_answer=task.get("answer", "任务已完成。"))
        harness = AgentHarness.build(cfg, backend=backend, approver=AllowAllProvider())
        return harness.resume(task["task_id"]), harness

    # ------------------------------------------------------------------
    # 期望断言(正例/负例/边界统一入口)
    @staticmethod
    def _check_expect(result: RunResult, harness, task: dict) -> tuple[bool, list[str]]:
        msgs: list[str] = []
        ok = True
        exp = task.get("expect", {})

        # 1) 运行状态白名单:负例同样要求 mock 轨迹优雅走到终答(不崩溃)
        allowed = exp.get("status_in", ["completed"])
        if result.status not in allowed:
            ok = False
            msgs.append(f"状态不在 {allowed}: {result.status}")

        calls = [c for s in result.steps for c in s.tool_calls]

        # 2) 负例:指定工具必须被拦截/报错,且拦截原因非空
        sfc = exp.get("should_fail_call")
        if sfc:
            for name in ([sfc] if isinstance(sfc, str) else sfc):
                bad = [c for c in calls
                       if c.name == name and c.status in ("denied", "error")]
                if not bad:
                    ok = False
                    msgs.append(f"负例未拦截: {name}")
                elif not any(c.error for c in bad):
                    ok = False
                    msgs.append(f"拦截缺少原因: {name}")

        # 3) 边界:去重缓存命中(重复调用被短路)
        chc = exp.get("cache_hit_call")
        if chc and not any(c.name == chc and c.meta.get("cache_hit") for c in calls):
            ok = False
            msgs.append(f"未观察到缓存命中: {chc}")

        # 4) 文件断言
        for f in exp.get("files_created", []):
            if not harness.workspace.resolve(f).exists():
                ok = False
                msgs.append(f"文件未创建: {f}")
        for f in exp.get("no_files_created", []):
            try:
                exists = harness.workspace.resolve(f).exists()
            except Exception:
                # 路径本就指向工作区之外(如 ../evil.txt):检查其外部落点
                exists = (harness.workspace.root / f).resolve().exists()
            if exists:
                ok = False
                msgs.append(f"不应存在的文件被创建: {f}")
        for f, sub in (exp.get("file_contains") or {}).items():
            content = harness.workspace.read_text(f) or ""
            if sub not in content:
                ok = False
                msgs.append(f"文件内容不含 {sub!r}: {f}")
        for f, sub in (exp.get("file_not_contains") or {}).items():
            content = harness.workspace.read_text(f) or ""
            if sub in content:
                ok = False
                msgs.append(f"文件内容不应含 {sub!r}: {f}")
        for f, exact in (exp.get("file_equals") or {}).items():
            content = harness.workspace.read_text(f)
            if content != exact:
                ok = False
                msgs.append(f"文件内容与预期不一致: {f}")
        # 编辑精确性:除目标变更外,保留区域标记必须原样存在
        for f, marker in (exp.get("file_unchanged_except") or {}).items():
            content = harness.workspace.read_text(f) or ""
            if marker not in content:
                ok = False
                msgs.append(f"编辑破坏了未涉及区域: {f} 缺 {marker!r}")

        # 5) 终答断言
        fc = exp.get("final_contains")
        if fc and fc not in result.final_answer:
            ok = False
            msgs.append(f"终答不含 {fc!r}")
        fn = exp.get("final_not_contains")
        if fn and fn in result.final_answer:
            ok = False
            msgs.append(f"终答不应含 {fn!r}")
        return ok, msgs

    @staticmethod
    def _count_reads(result: RunResult) -> int:
        return sum(1 for s in result.steps for c in s.tool_calls if c.name == "file_read")

    @staticmethod
    def _report(ok: bool, passed: int, total: int, summary: str,
                details: list, **extra) -> dict:
        rate = (passed / total) if total else 0.0
        rep = {"ok": bool(ok), "passed": passed, "total": total,
               "pass_rate": round(rate, 4), "summary": summary, "details": details}
        rep.update(extra)
        return rep

    # ------------------------------------------------------------------
    # Layer 1: harness 回归(正例 + 负例 + 边界)
    def layer_regression(self, tasks: list[dict]) -> dict:
        reg = by_layer(tasks, "regression")
        details, passed = [], 0
        for t in reg:
            wd = self.output_dir / "workspaces" / t["task_id"]
            result, harness = self._run(t, wd)
            ok, msgs = self._check_expect(result, harness, t)
            # 三类工件齐全性
            art_dir = wd / "artifacts" / t["task_id"]
            artifacts_ok = all((art_dir / f).exists() for f in
                               ("trajectory.jsonl", "report.md", "metrics.json"))
            ok = ok and artifacts_ok
            passed += int(ok)
            kind = t.get("kind", "positive")
            details.append(f"{t['task_id']}[{kind}]: {'通过' if ok else '失败'} {msgs} "
                           f"工件齐全={artifacts_ok}")
        return self._report(
            ok=bool(reg) and passed / len(reg) >= _PASS_THRESHOLD,
            passed=passed, total=len(reg),
            summary=f"{passed}/{len(reg)} 通过(含负例/边界)",
            details=details)

    # ------------------------------------------------------------------
    # Layer 2: 上下文治理(压缩收益 + 信息保留率 + 贴边预算)
    def layer_context(self, tasks: list[dict]) -> dict:
        ct = by_layer(tasks, "context")
        stats, details = [], []
        budget = 1500        # 压低预算,强制触发折叠裁剪
        keep = 3             # 只保留最近 3 轮原文,确定性触发折叠
        passed = probe_hits = probe_total = 0
        for t in ct:
            wdg = self.output_dir / "workspaces" / (t["task_id"] + "_governed")
            rg, hg = self._run(t, wdg, budget=budget, keep_turns=keep)
            wdb = self.output_dir / "workspaces" / (t["task_id"] + "_baseline")
            rb, _ = self._run(t, wdb, budget=10_000_000, keep_turns=1000)  # 不治理基线
            gov_total = sum(s.prompt_tokens for s in rg.steps)
            base_total = sum(s.prompt_tokens for s in rb.steps)
            ratio = (1 - gov_total / base_total) if base_total else 0.0
            hard = budget * 1.5
            within_hard = sum(1 for s in rg.steps if s.prompt_tokens <= hard)
            compliance = (within_hard / len(rg.steps)) if rg.steps else 1.0

            # 信息保留率探针:折叠+截断后,早期关键信息仍在最终送模型的上下文里
            probes = (t.get("expect") or {}).get("probe_contains") or []
            retained: list[str] = []
            if probes:
                blob = "\n".join(m.content for m in hg.context.assemble())
                retained = [p for p in probes if p in blob]
                probe_hits += len(retained)
                probe_total += len(probes)
            retention = (len(retained) / len(probes)) if probes else None

            folds = sum(1 for s in rg.steps
                        if "fold_old_turns" in (s.prune_strategies or []))
            fold_min = (t.get("expect") or {}).get("fold_min")

            # 贴边预算:极紧预算下仍须 100% 预算内(兜底截断生效)
            tight_ok = True
            if t.get("budget_edge"):
                wdt = self.output_dir / "workspaces" / (t["task_id"] + "_tight")
                rt2, _ = self._run(t, wdt, budget=600, keep_turns=2)
                hard2 = 600 * 1.5
                tight_ok = bool(rt2.steps) and all(s.prompt_tokens <= hard2
                                                   for s in rt2.steps)

            task_ok = (ratio > 0 and compliance >= 1.0 and tight_ok
                       and (retention in (None, 1.0))
                       and (fold_min is None or folds >= fold_min))
            passed += int(task_ok)
            stats.append({"task": t["task_id"], "baseline": base_total,
                          "governed": gov_total, "ratio": ratio,
                          "compliance": compliance, "retention": retention,
                          "folds": folds, "ok": task_ok})
            details.append(f"{t['task_id']}: 基线 {base_total} -> 治理 {gov_total} "
                           f"(压缩 {ratio:.2%}, 预算内 {compliance:.0%}, "
                           f"保留率 {retention if retention is None else format(retention, '.0%')}, "
                           f"折叠 {folds} 次{', 贴边OK' if tight_ok else ', 贴边失败'})")
            # A/B:注入可选的 LLM 摘要器,对比压缩率(确定性 vs 模型摘要)
            if self.summarizer is not None:
                wdl = self.output_dir / "workspaces" / (t["task_id"] + "_governed_llm")
                rl, _ = self._run(t, wdl, budget=budget, keep_turns=keep,
                                  summarizer=self.summarizer)
                gov_llm = sum(s.prompt_tokens for s in rl.steps)
                ratio_llm = (1 - gov_llm / base_total) if base_total else 0.0
                stats[-1]["governed_llm"] = gov_llm
                stats[-1]["ratio_llm"] = ratio_llm
                llm_within = sum(1 for s in rl.steps if s.prompt_tokens <= hard)
                llm_compliance = llm_within / len(rl.steps) if rl.steps else 1.0
                details.append(f"  ├ LLM摘要: {base_total} -> {gov_llm} "
                               f"(压缩 {ratio_llm:.2%}, 预算内 {llm_compliance:.0%})")
        ratios = [s["ratio"] for s in stats if s["ratio"] > 0]
        avg = sum(ratios) / len(ratios) if ratios else 0.0
        mx = max(ratios, default=0.0)
        compliance_all = min((s["compliance"] for s in stats), default=0.0)
        retention_all = (probe_hits / probe_total) if probe_total else None
        summary = (f"平均压缩率 {avg:.2%},最高 {mx:.2%},预算内完成率 {compliance_all:.0%}"
                   + (f",信息保留率 {retention_all:.0%}" if retention_all is not None else ""))
        ok = (bool(ct) and bool(ratios) and compliance_all >= 1.0
              and retention_all in (None, 1.0)
              and passed / len(ct) >= _PASS_THRESHOLD)
        return self._report(ok=ok, passed=passed, total=len(ct),
                            summary=summary, details=details, stats=stats,
                            retention_rate=retention_all)

    # ------------------------------------------------------------------
    # Layer 3: 记忆收益(场景矩阵:fresh_hit / stale / wrong_hit / missing)
    def layer_memory(self, tasks: list[dict]) -> dict:
        mt = by_layer(tasks, "memory")
        parents = [t for t in mt if not t.get("follow_up_of")]
        details, results = [], []
        re_read_with, re_read_without = 0, 0
        scenario_stats: dict[str, dict] = {}
        for parent in parents:
            wd = self.output_dir / "workspaces" / parent["task_id"]
            self._run(parent, wd)  # 父任务:沉淀文件摘要
            follows = [t for t in mt if t.get("follow_up_of") == parent["task_id"]]
            for fo in follows:  # 顺序敏感:missing 清记忆,生成器已排在同父末尾
                scenario = fo.get("memory_scenario", "fresh_hit")
                # 场景动作(在 follow-up 运行前注入)
                if scenario == "stale":
                    for rel, content in (fo.get("scenario_mutate") or {}).items():
                        p = wd / "ws" / rel
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_text(content, encoding="utf-8")
                elif scenario == "missing":
                    shutil.rmtree(wd / "memory", ignore_errors=True)
                elif scenario == "wrong_hit":
                    mem = StructuredMemory(str(wd / "memory"), enabled=True)
                    for rel, content in (fo.get("scenario_seed_memory_files") or {}).items():
                        mem.remember_file(path=rel, content=content)
                rt, ht = self._run(fo, wd, script_field="script")
                base_ok, msgs = self._check_expect(rt, ht, fo)
                reads = self._count_reads(rt)
                # 没有记忆对象时,所有依赖记忆的场景都应判失败;这使关
                # memory.enabled 的灵敏度测试真正度量到能力退化。
                memory_available = bool(ht.memory is not None and ht.memory.enabled)
                if scenario == "fresh_hit":
                    sc_ok = memory_available and reads == 0
                    why = "应复用记忆不重读"
                elif scenario == "stale":
                    mutate = fo.get("scenario_mutate") or {}
                    marker = next((next(iter(c.splitlines()), "") for c in mutate.values()), "")
                    read_outputs = [c.output or "" for s in rt.steps
                                    for c in s.tool_calls if c.name == "file_read"]
                    read_new = any(marker and marker[:30] in o for o in read_outputs)
                    fresh_after = all(
                        ht.memory.has_fresh_summary(rel, sha256_file(wd / "ws" / rel))
                        for rel in mutate) if ht.memory else False
                    sc_ok = memory_available and reads >= 1 and read_new and fresh_after
                    why = f"应检测过期并重读新内容(重读{reads}次," \
                          f"读到新内容={read_new},记忆已更新={fresh_after})"
                elif scenario == "missing":
                    sc_ok = reads >= 1
                    why = "记忆缺失应优雅降级重读"
                else:  # wrong_hit:正确性由 file_contains/file_not_contains 断言
                    sc_ok = True
                    why = "命中干扰项也不误用"
                ok = base_ok and sc_ok
                st = scenario_stats.setdefault(scenario, {"passed": 0, "total": 0})
                st["total"] += 1
                st["passed"] += int(ok)
                # 对照组:关闭记忆重放(仅统计聚合重读差)
                if fo.get("control_script"):
                    rc, _hc = self._run(fo, wd, script_field="control_script",
                                        memory_enabled=False)
                    re_read_without += self._count_reads(rc)
                re_read_with += reads
                details.append(f"{fo['task_id']}[{scenario}]: {'通过' if ok else '失败'}"
                               f"({why}) {msgs}")
                results.append({"task": fo["task_id"], "scenario": scenario,
                                "re_read": reads, "ok": ok})
        total = sum(v["total"] for v in scenario_stats.values())
        passed = sum(v["passed"] for v in scenario_stats.values())
        sc_txt = ", ".join(f"{k} {v['passed']}/{v['total']}"
                           for k, v in scenario_stats.items())
        return self._report(
            ok=bool(total) and passed / total >= _PASS_THRESHOLD,
            passed=passed, total=total,
            summary=f"follow-up 重读 {re_read_without} -> {re_read_with} 次;总计 {passed}/{total}; {sc_txt}",
            details=details, results=results, scenario_stats=scenario_stats)

    # ------------------------------------------------------------------
    # Layer 4: 恢复正确性(多任务 x 停点 x 漂移类型矩阵)
    @staticmethod
    def _written_files(task: dict, upto: int | None = None) -> list[str]:
        out: list[str] = []
        for entry in (task.get("script") or [])[:upto]:
            for c in entry.get("tool_calls", []) or []:
                if c.get("name") == "file_write":
                    out.append(c["arguments"]["path"])
        return out

    @staticmethod
    def _apply_drift(workdir: Path, task: dict, k: int, dtype: str) -> None:
        """按漂移类型突变工作区(数据驱动:目标文件取自前 k 轮的 file_write)。

        whitespace_only / reformat 属"语义不变内容变":现检测按哈希精确比对,
        必然检出 —— 这是有意的设计取舍(宁可误报不可漏报),矩阵中显式测之。
        """
        ws = workdir / "ws"
        existing = [f for f in EvalRunner._written_files(task, k)
                    if (ws / f).exists()]
        if dtype == "content_change":
            if existing:
                (ws / existing[0]).write_text("外部篡改:该文件内容已失效\n",
                                              encoding="utf-8")
            (ws / "drift_external.txt").write_text("external change\n", encoding="utf-8")
            if len(existing) > 1:
                (ws / existing[1]).unlink()
        elif dtype in ("whitespace_only", "reformat"):
            if existing:
                text = (ws / existing[0]).read_text(encoding="utf-8")
                if dtype == "whitespace_only":
                    new = "\n".join(line + "  " for line in text.splitlines()) + "\n"
                else:
                    new = "\n".join(("    " + ln if ln.strip() else ln)
                                    for ln in text.splitlines()) + "\n"
                (ws / existing[0]).write_text(new, encoding="utf-8")
        elif dtype == "large_scale":
            bulk = ws / "drift_bulk"
            bulk.mkdir(parents=True, exist_ok=True)
            for i in range(300):
                (bulk / f"bulk_{i:03d}.txt").write_text(f"bulk drift {i}\n",
                                                        encoding="utf-8")

    def layer_resume(self, tasks: list[dict]) -> dict:
        rtasks = by_layer(tasks, "resume")
        if not rtasks:
            return self._report(ok=True, passed=0, total=0, summary="无 resume 任务",
                                details=[])
        details, scenarios = [], []
        passed = drift_detected = drift_expected = clean_correct = completed_count = 0
        total = 0
        for t in rtasks:
            meta = t.get("resume") or {}
            script_len = len(t.get("script") or [])
            stop_points = [k for k in (meta.get("stop_points") or [1, 2, 3])
                           if 0 < k < script_len]
            drift_types = meta.get("drift_types") or [
                "content_change", "whitespace_only", "reformat", "large_scale"]
            final_files = meta.get("final_files") or [self._written_files(t)[-1]]
            ans = (meta.get("final_answer_contains")
                   or (t.get("expect") or {}).get("final_contains") or "")
            content_spec = dict(meta.get("file_contains") or {})
            if not content_spec:  # 从 script 最后一次 file_write 推导内容基准
                for entry in reversed(t["script"]):
                    ws = [c for c in entry.get("tool_calls", [])
                          if c.get("name") == "file_write"]
                    if ws:
                        content_spec = {ws[-1]["arguments"]["path"]:
                                        ws[-1]["arguments"]["content"]}
                        break
            for k in stop_points:
                for dtype in ["clean", *drift_types]:
                    total += 1
                    tag = f"{t['task_id']}_k{k}_{dtype}"
                    wd = self.output_dir / "workspaces" / tag
                    rg, _hg = self._run(t, wd, stop_after=k)
                    interrupted = rg.status == "interrupted"
                    if dtype != "clean":
                        self._apply_drift(wd, t, k, dtype)
                    t0 = time.monotonic()
                    rc, hr = self._resume(t, wd)
                    elapsed = time.monotonic() - t0
                    drift = rc.drift or {}
                    got_drift = bool(drift.get("is_drift"))
                    detect_ok = interrupted and (got_drift == (dtype != "clean"))
                    files_ok = all(hr.workspace.resolve(f).exists() for f in final_files)
                    content_ok = all(sub in (hr.workspace.read_text(f) or "")
                                     for f, sub in content_spec.items())
                    completed = (rc.status == "completed" and files_ok and content_ok
                                 and (not ans or ans in rc.final_answer))
                    perf_ok = (elapsed <= 10.0) if dtype == "large_scale" else True
                    ok = detect_ok and completed and perf_ok
                    passed += int(ok)
                    completed_count += int(completed)
                    if dtype == "clean":
                        clean_correct += int(not got_drift)
                    else:
                        drift_expected += 1
                        drift_detected += int(got_drift)
                    note = {"whitespace_only": "(设计取舍:语义不变哈希变,按设计检出)",
                            "reformat": "(设计取舍:格式化误报,按设计检出)"}.get(dtype, "")
                    details.append(f"scenario {tag}: 漂移={'检出' if got_drift else '无'}"
                                   f"(期望 {'漂移' if dtype != 'clean' else '无'}){note}, "
                                   f"恢复后={rc.status}, 内容正确={content_ok}, "
                                   f"耗时{elapsed:.2f}s -> {'通过' if ok else '失败'}")
                    scenarios.append({"task": t["task_id"], "k": k, "drift_type": dtype,
                                      "detected": got_drift, "completed": completed,
                                      "content_ok": content_ok, "ok": ok,
                                      "elapsed_s": round(elapsed, 3)})
        accuracy = (drift_detected + clean_correct) / total if total else 0.0
        completion = completed_count / total if total else 0.0
        return self._report(
            ok=bool(total) and passed / total >= _PASS_THRESHOLD and accuracy >= _PASS_THRESHOLD,
            passed=passed, total=total,
            summary=(f"漂移识别 {accuracy:.0%}, 恢复完成(含内容正确) {completion:.0%}, "
                     f"场景通过 {passed}/{total}"),
            details=details, scenarios=scenarios,
            drift_accuracy=round(accuracy, 4), resume_completion=round(completion, 4))

    # ------------------------------------------------------------------
    # Layer 5: 检索召回(四类查询分别判定 + MRR)
    def layer_retrieval(self, tasks: list[dict] | None = None) -> dict:
        """Layer 5:检索召回评测。对比 substring(子串) 与 hybrid(向量+BM25) 两种模式。

        四类查询分别判定(区别于旧的"hybrid 必须每条全胜"的二值逻辑):
          exact      查询含原文子串 => substring 应能命中(证明其本身可用);
          synonym    同义改写       => hybrid 应严格优于 substring(语义增益);
          distractor 语料无对应能力 => 强干扰项(avoid)不得进 top-3;
          empty      完全无关       => 不误召回(avoid 不进 top-3)。
        另报告 MRR@5(hybrid/substring)度量排序质量,替代纯 recall 的单一视角。
        """
        if tasks is None:
            tasks = load_benchmarks([p for p in _RETRIEVAL_PATHS if p.exists()])
        rt = by_layer(tasks, "retrieval")
        details: list[str] = []
        per_query: list[dict] = []
        type_stats: dict[str, dict] = {}
        total_q = 0
        sum_recall = {"substring": {1: 0.0, 3: 0.0, 5: 0.0},
                      "hybrid": {1: 0.0, 3: 0.0, 5: 0.0}}
        mrr_sum = {"substring": 0.0, "hybrid": 0.0}
        mrr_n = 0
        for t in rt:
            mem = StructuredMemory(
                str(self.output_dir / "retrieval_ws" / t["task_id"] / "memory"),
                enabled=True)
            for doc in t.get("corpus", []):
                mem.remember_file(path=doc["id"], content=doc["text"])
            for q in t.get("queries", []):
                total_q += 1
                qtype = q.get("type", "synonym")
                relevant = {"file:" + r for r in q["relevant"]}
                avoid = {"file:" + a for a in q.get("avoid", [])}
                row = {"task": t["task_id"], "query": q["q"], "type": qtype,
                       "relevant": sorted(relevant)}
                ranked: dict[str, list] = {}
                for mode in ("substring", "hybrid"):
                    r = mem.rank(q["q"], mode=mode, top_k=5, kind="file")
                    ranked[mode] = r
                    for k in (1, 3, 5):
                        topk = {i for i, _ in r[:k]}
                        rec = (len(relevant & topk) / len(relevant)) if relevant else 0.0
                        sum_recall[mode][k] += rec
                        if k == 3:
                            row[f"{mode}@3"] = round(rec, 3)
                    if relevant:
                        mrr_sum[mode] += next(
                            (1.0 / (idx + 1) for idx, (i, _) in enumerate(r[:5])
                             if i in relevant), 0.0)
                if relevant:
                    mrr_n += 1
                top3_h = {i for i, _ in ranked["hybrid"][:3]}
                # 分类判定
                if qtype == "exact":
                    ok_q = row["substring@3"] > 0 and row["hybrid@3"] >= row["substring@3"]
                elif qtype == "synonym":
                    ok_q = row["hybrid@3"] > row["substring@3"]
                else:  # distractor / empty:不误召回
                    ok_q = not (avoid & top3_h) and row["substring@3"] == 0
                ts = type_stats.setdefault(qtype, {"passed": 0, "total": 0})
                ts["total"] += 1
                ts["passed"] += int(ok_q)
                row["ok"] = ok_q
                row["top3_hybrid"] = sorted(top3_h)
                per_query.append(row)
                details.append(f"{t['task_id']}[{qtype}] q={q['q'][:18]!r}: "
                               f"substring@3={row['substring@3']:.0%}, "
                               f"hybrid@3={row['hybrid@3']:.0%} "
                               f"{'通过' if ok_q else '失败'}")
        n = total_q or 1
        avg = {m: {k: sum_recall[m][k] / n for k in (1, 3, 5)}
               for m in ("substring", "hybrid")}
        mrr = {m: (mrr_sum[m] / mrr_n if mrr_n else 0.0)
               for m in ("substring", "hybrid")}
        type_txt = ", ".join(f"{k} {v['passed']}/{v['total']}"
                             for k, v in type_stats.items())
        summary = (f"查询 {total_q} 个,总计 {sum(v['passed'] for v in type_stats.values())}/{total_q}; "
                   f"类型({type_txt}); "
                   f"substring 平均 recall@1/3/5="
                   f"{avg['substring'][1]:.0%}/{avg['substring'][3]:.0%}/{avg['substring'][5]:.0%}, "
                   f"hybrid={avg['hybrid'][1]:.0%}/{avg['hybrid'][3]:.0%}/{avg['hybrid'][5]:.0%}; "
                   f"MRR@5 substring={mrr['substring']:.2f}, hybrid={mrr['hybrid']:.2f}")
        ratios = {k: v["passed"] / v["total"] for k, v in type_stats.items() if v["total"]}
        ok = (bool(per_query)
              and all(r >= _PASS_THRESHOLD for r in ratios.values())
              and avg["hybrid"][3] > avg["substring"][3]
              and mrr["hybrid"] > 0)
        return self._report(ok=ok, passed=sum(v["passed"] for v in type_stats.values()),
                            total=total_q, summary=summary, details=details,
                            per_query=per_query, avg_recall=avg, mrr=mrr,
                            type_stats=type_stats)

    # ------------------------------------------------------------------
    # Layer 7: 嵌入器对照(hash 索引 vs bge-small)
    def layer_embedder_ab(self) -> dict:
        """在同一检索集上对比零依赖哈希嵌入与 FastEmbed bge-small。

        该层显式独立于默认套件,避免 CI 或离线用户被迫下载模型。
        """
        paths = [p for p in _RETRIEVAL_PATHS if p.exists()]
        tasks = load_benchmarks([str(p) for p in paths])
        try:
            embedders: dict[str, EmbeddingProvider] = {
                "hashing": HashingEmbedder(),
                "bge-small": FastEmbedEmbedder(
                    model_name="BAAI/bge-small-zh-v1.5",
                    cache_dir=str(self.output_dir / "embed_cache"),
                ),
            }
            # 提前触发可选依赖加载,缺失时给出可操作的 skip 报告。
            embedders["bge-small"].embed("依赖探测")
        except Exception as exc:
            # 可选模型可能因未安装、首次下载超时或本地缓存损坏而不可用;
            # 不让默认的离线评测因此失败,同时把原因写入报告。
            return {"ok": True, "skipped": True, "passed": 0, "total": 0,
                    "pass_rate": 1.0,
                    "summary": f"跳过嵌入器对照: {type(exc).__name__}: {exc}",
                    "details": []}

        stats: dict[str, dict[str, Any]] = {
            name: {"recall": {1: 0.0, 3: 0.0, 5: 0.0}, "mrr": 0.0}
            for name in embedders
        }
        total = 0
        mrr_total = 0
        details: list[str] = []
        for task in by_layer(tasks, "retrieval"):
            for query in task.get("queries", []):
                total += 1
                relevant = {"file:" + item for item in query.get("relevant", [])}
                for name, embedder in embedders.items():
                    index = VectorIndex(embedder)
                    bm25 = BM25()
                    for doc in task.get("corpus", []):
                        doc_id = "file:" + doc["id"]
                        index.add(doc_id, doc["text"])
                        bm25.add(doc_id, tokenize(doc["text"]))
                    ranked = HybridRetriever(index, bm25, embedder).rank(
                        query["q"], top_k=5)
                    for k in (1, 3, 5):
                        topk = {item for item, _ in ranked[:k]}
                        stats[name]["recall"][k] += (
                            len(relevant & topk) / len(relevant) if relevant else 0.0
                        )
                    if relevant:
                        stats[name]["mrr"] += next(
                            (1.0 / (idx + 1) for idx, (item, _) in enumerate(ranked)
                             if item in relevant), 0.0)
                if relevant:
                    mrr_total += 1
        n = total or 1
        result: dict[str, dict[str, Any]] = {}
        for name, values in stats.items():
            result[name] = {
                "recall": {k: round(values["recall"][k] / n, 4) for k in (1, 3, 5)},
                "mrr@5": round(values["mrr"] / (mrr_total or 1), 4),
            }
            details.append(
                f"{name}: recall@1/3/5="
                f"{result[name]['recall'][1]:.0%}/"
                f"{result[name]['recall'][3]:.0%}/"
                f"{result[name]['recall'][5]:.0%}, "
                f"MRR@5={result[name]['mrr@5']:.2f}"
            )
        better = result["bge-small"]["recall"][3] >= result["hashing"]["recall"][3]
        return self._report(
            ok=better, passed=int(better), total=1,
            summary=f"{total} 个查询的 hashing / bge-small 对照", details=details,
            embedders=result, query_count=total,
        )
