"""四层评测运行器。

四层职责(刻意分离,避免混淆"模型能力"与"系统能力"):
  1. harness 回归   —— 验证运行时稳定性(能完成、三类工件齐全、断言满足);
  2. 上下文治理     —— 验证预算裁剪收益(治理 vs 不治理 的 prompt 长度差);
  3. 记忆收益       —— 验证 follow-up 阶段重复读文件是否归零、正确率;
  4. 恢复正确性     —— 验证 checkpoint/resume + 工作区漂移识别边界。

所有层都用【同一个确定性 mock 轨迹】驱动,唯一变化的是 harness 系统开关,
因此测到的是系统能力,而非模型能力。运行工件聚合在 output_dir 下可复现。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..config import Config
from ..models import MockBackend
from ..safety import AllowAllProvider
from ..state import TaskInput, RunResult
from .benchmark import by_layer, load_benchmarks
from .experiment import compare_metrics, format_delta


def _generate_file(spec: dict) -> str:
    kind = spec.get("kind", "text")
    count = int(spec.get("count", 100))
    if kind == "functions":
        return "\n".join(
            f"def func_{i}(x):  # 函数 {i} 的实现,用于制造长上下文\n    return x * {i} + 1\n"
            for i in range(count))
    if kind == "logs":
        levels = ("INFO", "WARN", "ERROR", "DEBUG")
        return "\n".join(
            f"{levels[i % 4]} [task{i}] 处理第 {i} 条记录,耗时 {i % 97}ms,状态 normal,payload_size={i % 512}"
            for i in range(count))
    return str(spec.get("content", ""))


class EvalRunner:
    def __init__(self, config: Config, output_dir: str = ".mycoder/eval",
                 benchmark_path: str | None = None):
        self.base_config = config
        self.output_dir = Path(output_dir)
        self.benchmark_path = benchmark_path

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
        return reports

    def write_report(self, reports: dict[str, dict]) -> None:
        ensure = self.output_dir
        ensure.mkdir(parents=True, exist_ok=True)
        (ensure / "report.json").write_text(
            json.dumps(reports, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        md = ["# MyCoder 评测报告", ""]
        for name, rep in reports.items():
            md += [f"## Layer: {name}", f"- ok: {rep.get('ok')}", f"- {rep.get('summary', '')}", ""]
            for d in rep.get("details", []):
                md.append("- " + str(d))
            md.append("")
        (ensure / "report.md").write_text("\n".join(md), encoding="utf-8")

    # ------------------------------------------------------------------
    # 基础设施
    def _reset(self) -> None:
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _cfg_for(self, workdir: Path, budget: int | None = None,
                 keep_turns: int | None = None, memory_enabled: bool = True) -> Config:
        cfg = Config(self.base_config.to_dict())
        cfg.set("workspace.root", str(workdir / "ws"))
        cfg.set("memory.root", str(workdir / "memory"))
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
             memory_enabled: bool = True, budget: int | None = None,
             keep_turns: int | None = None, stop_after: int | None = None):
        from ..agent import AgentHarness
        cfg = self._cfg_for(workdir, budget=budget, keep_turns=keep_turns,
                            memory_enabled=memory_enabled)
        backend = MockBackend(script=task.get(script_field) or [],
                              default_answer=task.get("answer", "任务已完成。"))
        harness = AgentHarness.build(cfg, backend=backend, approver=AllowAllProvider())
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

    @staticmethod
    def _check_expect(result: RunResult, harness, task: dict) -> tuple[bool, list[str]]:
        msgs: list[str] = []
        ok = True
        exp = task.get("expect", {})
        for f in exp.get("files_created", []):
            p = harness.workspace.resolve(f)
            if not p.exists():
                ok = False
                msgs.append(f"文件未创建: {f}")
        for f, sub in (exp.get("file_contains") or {}).items():
            content = harness.workspace.read_text(f) or ""
            if sub not in content:
                ok = False
                msgs.append(f"文件内容不含 {sub!r}: {f}")
        fc = exp.get("final_contains")
        if fc and fc not in result.final_answer:
            ok = False
            msgs.append(f"终答不含 {fc!r}")
        if result.status != "completed":
            ok, _ = False, msgs.append(f"状态非 completed: {result.status}")
        return ok, msgs

    @staticmethod
    def _count_reads(result: RunResult) -> int:
        return sum(1 for s in result.steps for c in s.tool_calls if c.name == "file_read")

    # ------------------------------------------------------------------
    # Layer 1: harness 回归
    def layer_regression(self, tasks: list[dict]) -> dict:
        details, passed = [], 0
        for t in by_layer(tasks, "regression"):
            wd = self.output_dir / "workspaces" / t["task_id"]
            result, harness = self._run(t, wd)
            ok, msgs = self._check_expect(result, harness, t)
            # 三类工件齐全性
            art_dir = wd / "artifacts" / t["task_id"]
            artifacts_ok = all((art_dir / f).exists() for f in
                               ("trajectory.jsonl", "report.md", "metrics.json"))
            ok = ok and artifacts_ok
            passed += int(ok)
            details.append(f"{t['task_id']}: {'通过' if ok else '失败'} {msgs} 工件齐全={artifacts_ok}")
        return {"ok": passed == len(by_layer(tasks, "regression")),
                "summary": f"{passed}/{len(by_layer(tasks, 'regression'))} 通过",
                "details": details}

    # ------------------------------------------------------------------
    # Layer 2: 上下文治理
    def layer_context(self, tasks: list[dict]) -> dict:
        ct = by_layer(tasks, "context")
        stats, details = [], []
        budget = 1500  # 压低预算,强制触发折叠裁剪
        for t in ct:
            wdg = self.output_dir / "workspaces" / (t["task_id"] + "_governed")
            rg, _ = self._run(t, wdg, budget=budget)
            wdb = self.output_dir / "workspaces" / (t["task_id"] + "_baseline")
            rb, _ = self._run(t, wdb, budget=10_000_000, keep_turns=1000)  # 不治理基线
            gov_total = sum(s.prompt_tokens for s in rg.steps)
            base_total = sum(s.prompt_tokens for s in rb.steps)
            ratio = (1 - gov_total / base_total) if base_total else 0.0
            hard = 1500 * 1.5
            within_hard = sum(1 for s in rg.steps if s.prompt_tokens <= hard)
            compliance = (within_hard / len(rg.steps)) if rg.steps else 1.0
            stats.append({"task": t["task_id"], "baseline": base_total,
                          "governed": gov_total, "ratio": ratio, "compliance": compliance})
            details.append(f"{t['task_id']}: 基线 {base_total} -> 治理 {gov_total} "
                           f"(压缩 {ratio:.2%}, 预算内 {compliance:.0%})")
        ratios = [s["ratio"] for s in stats if s["ratio"] > 0]
        avg = sum(ratios) / len(ratios) if ratios else 0.0
        mx = max(ratios, default=0.0)
        compliance_all = min((s["compliance"] for s in stats), default=0.0)
        return {"ok": bool(ratios) and compliance_all >= 1.0,
                "summary": f"平均压缩率 {avg:.2%},最高 {mx:.2%},预算内完成率 {compliance_all:.0%}",
                "details": details, "stats": stats}

    # ------------------------------------------------------------------
    # Layer 3: 记忆收益
    def layer_memory(self, tasks: list[dict]) -> dict:
        mt = by_layer(tasks, "memory")
        parents = [t for t in mt if not t.get("follow_up_of")]
        details, results = [], []
        re_read_with, re_read_without, correct, total = 0, 0, 0, 0
        for parent in parents:
            wd = self.output_dir / "workspaces" / parent["task_id"]
            self._run(parent, wd)  # 父任务:沉淀文件摘要
            follows = [t for t in mt if t.get("follow_up_of") == parent["task_id"]]
            for fo in follows:
                total += 1
                rt, ht = self._run(fo, wd, script_field="script", memory_enabled=True)
                rc, hc = self._run(fo, wd, script_field="control_script", memory_enabled=False)
                wt = self._count_reads(rt)
                wc = self._count_reads(rc)
                ok, msgs = self._check_expect(rt, ht, fo)
                correct += int(ok)
                re_read_with += wt
                re_read_without += wc
                details.append(f"{fo['task_id']}: 记忆开启重读 {wt} 次 / 关闭重读 {wc} 次;"
                               f"正确={ok}")
                results.append({"task": fo["task_id"], "re_read_with": wt,
                                "re_read_without": wc, "correct": ok})
        accuracy = correct / total if total else 0.0
        re_read_reduced_to_zero = (re_read_with == 0)
        return {"ok": accuracy >= 1.0 and re_read_reduced_to_zero,
                "summary": (f"follow-up 重读 {re_read_without} -> {re_read_with} 次,"
                            f"正确率 {accuracy:.0%}"),
                "details": details, "results": results}

    # ------------------------------------------------------------------
    # Layer 4: 恢复正确性
    def layer_resume(self, tasks: list[dict]) -> dict:
        rtasks = by_layer(tasks, "resume")
        if not rtasks:
            return {"ok": True, "summary": "无 resume 任务", "details": []}
        t = rtasks[0]
        details = []
        drift_detected = drift_expected = clean_correct = 0
        scenarios = []
        for k in (1, 2, 3, 4, 5):
            for want_drift in (False, True):
                tag = f"k{k}_{'drift' if want_drift else 'clean'}"
                wd = self.output_dir / "workspaces" / (t["task_id"] + "_" + tag)
                rg, hg = self._run(t, wd, stop_after=k)
                assert rg.status == "interrupted", f"step{k} 未按预期中断: {rg.status}"
                if want_drift:
                    self._mutate_workspace(wd, k)
                rc, hr = self._resume(t, wd)
                drift = rc.drift or {}
                got_drift = bool(drift.get("is_drift"))
                if want_drift:
                    drift_expected += 1
                    drift_detected += int(got_drift)
                else:
                    clean_correct += int(not got_drift)
                # 恢复必须真正续跑完剩余步骤:末步文件已生成 + 终答正确
                step4 = hr.workspace.resolve("mod/step4.txt")
                completed = (rc.status == "completed"
                             and step4.exists()
                             and "构建完成" in rc.final_answer)
                details.append(f"scenario {tag}: 漂移={'检出' if got_drift else '无'} "
                               f"(期望 {'漂移' if want_drift else '无'}), 恢复后={rc.status},"
                               f"续跑完成={completed}")
                scenarios.append({"k": k, "drift": want_drift, "detected": got_drift,
                                  "completed": completed})
        # 共 10 个场景:5 个漂移 + 5 个无漂移,全部识别正确 => 100%
        accuracy = (drift_detected + clean_correct) / 10
        return {"ok": accuracy >= 1.0,
                "summary": f"漂移识别准确率 {accuracy:.0%}({drift_detected}/5 漂移检出, {clean_correct}/5 无漂移正确)",
                "details": details, "scenarios": scenarios, "accuracy": accuracy}

    @staticmethod
    def _mutate_workspace(workdir: Path, k: int) -> None:
        ws = workdir / "ws"
        (ws / "mod").mkdir(parents=True, exist_ok=True)
        # 1) 修改文件(漂移: modified)
        step1 = ws / "mod" / "step1.txt"
        if step1.exists():
            step1.write_text("step1 done (被外部修改)\n", encoding="utf-8")
        # 2) 新增文件(漂移: added)
        (ws / "mod" / "external.txt").write_text("external change\n", encoding="utf-8")
        # 3) 删除文件(漂移: deleted),仅当该步已产生 step2
        step2 = ws / "mod" / "step2.txt"
        if k >= 2 and step2.exists():
            step2.unlink()