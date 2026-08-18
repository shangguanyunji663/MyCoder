"""命令行入口:python -m mycoder <command>。

子命令:
  run         运行一个任务(本地,默认 mock 后端)
  resume      从断点恢复一个任务
  serve       启动 localhost HTTP API(127.0.0.1:{port},--impl stdlib|fastapi)
  orchestrate 把复杂目标分解为子任务并行编排执行
  eval        运行评测(h regression | context | memory | resume | retrieval | all)
  benchmark   列出内置 benchmark 任务
  artifacts   查看/聚合某任务的运行工件
  doctor      打印环境诊断(帮助新手确认配置与依赖)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Config
from .models import MockBackend, create_backend
from .state import TaskInput
from .tasks import load_task_file


def _build_config(args) -> Config:
    cfg = Config.load(getattr(args, "config", None))
    if getattr(args, "hitl_policy", None):
        cfg.set("safety.hitl_policy", args.hitl_policy)
    if getattr(args, "workspace", None):
        cfg.set("workspace.root", args.workspace)
    if getattr(args, "backend", None):
        cfg.set("model.backend", args.backend)
    return cfg


def _make_backend(cfg: Config, task_data: dict):
    """优先用任务文件里的 script 构造 mock;否则按 config 后端装配。"""
    if task_data.get("script"):
        return MockBackend(script=task_data["script"],
                           default_answer=task_data.get("answer", "任务已完成。"))
    return create_backend(cfg)


def cmd_run(args) -> int:
    from .agent import AgentHarness
    from .safety import AllowAllProvider, DenyAllProvider

    cfg = _build_config(args)
    data = load_task_file(args.task_file)
    backend = _make_backend(cfg, data)
    policy = cfg.get("safety.hitl_policy", "prompt")
    approver = {"allow": AllowAllProvider(), "deny": DenyAllProvider()}.get(policy)
    harness = AgentHarness.build(cfg, backend=backend, approver=approver)
    task = TaskInput(task_id=data.get("task_id", Path(args.task_file).stem),
                     goal=data.get("goal", ""),
                     files_hint=data.get("files_hint", []),
                     follow_up_of=data.get("follow_up_of"),
                     extra=data.get("extra", {}))
    # 预置 setup_files(演示/评测用)
    for rel, content in (data.get("setup_files") or {}).items():
        harness.workspace.write_text(rel, content)
    result = harness.run(task)
    print(json.dumps({"task_id": result.task_id, "status": result.status,
                      "metrics": result.metrics,
                      "final_answer": result.final_answer,
                      "artifacts_dir": str(harness.artifacts.task_dir(result.task_id))},
                     ensure_ascii=False, indent=2))
    return 0 if result.status == "completed" else 1


def cmd_resume(args) -> int:
    from .agent import AgentHarness
    cfg = _build_config(args)
    harness = AgentHarness.build(cfg)
    result = harness.resume(args.task_id)
    print(json.dumps({"task_id": result.task_id, "status": result.status,
                      "drift": result.drift, "final_answer": result.final_answer},
                     ensure_ascii=False, indent=2))
    return 0 if result.status == "completed" else 1


def cmd_serve(args) -> int:
    from .api import run_server
    cfg = _build_config(args)
    host = args.host or cfg.get("api.host", "127.0.0.1")
    port = args.port or int(cfg.get("api.port", 8910))
    print(f"MyCoder API 启动(impl={getattr(args, 'impl', 'stdlib')}): http://{host}:{port}/health")
    run_server(cfg, host=host, port=port, impl=getattr(args, "impl", "stdlib"))
    return 0


def cmd_orchestrate(args) -> int:
    from .agent import Orchestrator

    cfg = _build_config(args)
    if getattr(args, "max_workers", None):
        cfg.set("agent.orchestrator.max_workers", args.max_workers)

    def backend_factory(sub):
        # 每个子任务按其配置装配后端(任务文件无 script 时走真实/配置后端)
        return create_backend(cfg)

    orch = Orchestrator(
        cfg,
        backend_factory=backend_factory,
        max_workers=cfg.get("agent.orchestrator.max_workers", 4),
    )
    result = orch.run(args.goal, task_id=getattr(args, "task_id", None))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    failed = (result.get("summary") or {}).get("failed", 0)
    return 0 if failed == 0 else 1


def cmd_eval(args) -> int:
    from .eval.runner import EvalRunner
    cfg = _build_config(args)
    runner = EvalRunner(cfg, output_dir=args.output, benchmark_path=args.benchmarks)
    suite = args.suite or "all"
    reports = runner.run_suite(suite)
    runner.write_report(reports)
    for name, rep in reports.items():
        print(f"[{name}] ok={rep.get('ok')} summary={rep.get('summary')}")
    return 0 if all(r.get("ok") for r in reports.values()) else 1


def cmd_benchmark(args) -> int:
    from .eval.benchmark import load_benchmarks
    tasks = load_benchmarks(args.benchmarks)
    for t in tasks:
        print(f"- {t['task_id']:24s} layer={t.get('layer', 'regression'):12s} "
              f"parent={t.get('follow_up_of') or '-'}")
    print(f"\n共 {len(tasks)} 个 benchmark 任务")
    return 0


def cmd_artifacts(args) -> int:
    cfg = _build_config(args)
    root = Path(cfg.get("artifacts.root", ".mycoder/artifacts"))
    d = root / args.task_id
    if not d.exists():
        print(f"未找到工件目录: {d}")
        return 1
    for f in sorted(d.iterdir()):
        print(f"  {f.name}  ({f.stat().st_size} bytes)")
    return 0


def cmd_doctor(args) -> int:
    print("MyCoder 环境诊断")
    print("=" * 40)
    print(f"Python: {sys.version.split()[0]}")
    import importlib.util
    for mod in ("yaml", "pytest"):
        ok = importlib.util.find_spec(mod) is not None
        print(f"  {mod:10s} {'OK' if ok else '缺失(请安装)'}")
    cfg = _build_config(args)
    print(f"模型后端: {cfg.model_backend}")
    print(f"工作区根: {cfg.workspace_root}")
    print(f"上下文预算: {cfg.get('context.budget_tokens')} tokens")
    print(f"API 地址: 127.0.0.1:{cfg.get('api.port')}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="mycoder", description="MyCoder 本地 Coding Agent Harness")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="运行一个任务")
    r.add_argument("--task-file", required=True, help="任务文件(json/md)")
    r.add_argument("--config", help="配置文件")
    r.add_argument("--workspace", help="覆盖工作区根目录")
    r.add_argument("--hitl-policy", choices=["prompt", "allow", "deny"], help="审批策略")
    r.add_argument("--backend", choices=["mock", "local_openai"],
                   help="覆盖 model.backend(任务文件带 script 时仍优先用 mock)")
    r.set_defaults(func=cmd_run)

    rs = sub.add_parser("resume", help="从断点恢复")
    rs.add_argument("--task-id", required=True)
    rs.add_argument("--config")
    rs.add_argument("--backend", choices=["mock", "local_openai"], help="覆盖 model.backend")
    rs.set_defaults(func=cmd_resume)

    s = sub.add_parser("serve", help="启动 localhost HTTP API")
    s.add_argument("--config")
    s.add_argument("--host", default=None)
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--impl", choices=["stdlib", "fastapi"], default="stdlib",
                   help="HTTP 实现:stdlib(零依赖) 或 fastapi(SSE 实时追踪)")
    s.set_defaults(func=cmd_serve)

    e = sub.add_parser("eval", help="运行评测")
    e.add_argument("--suite", choices=["all", "regression", "context", "memory", "resume", "retrieval"], default="all")
    e.add_argument("--output", default=".mycoder/eval")
    e.add_argument("--benchmarks", default=None)
    e.add_argument("--config")
    e.set_defaults(func=cmd_eval)

    b = sub.add_parser("benchmark", help="列出 benchmark 任务")
    b.add_argument("--benchmarks", default=None)
    b.set_defaults(func=cmd_benchmark)

    a = sub.add_parser("artifacts", help="查看运行工件")
    a.add_argument("--task-id", required=True)
    a.add_argument("--config")
    a.set_defaults(func=cmd_artifacts)

    d = sub.add_parser("doctor", help="环境诊断")
    d.add_argument("--config")
    d.set_defaults(func=cmd_doctor)

    o = sub.add_parser("orchestrate", help="把复杂目标分解为子任务并行编排执行")
    o.add_argument("--goal", required=True, help="复杂目标(将被分解为子任务)")
    o.add_argument("--task-id", default=None, help="编排任务 ID(可选)")
    o.add_argument("--config")
    o.add_argument("--workspace")
    o.add_argument("--hitl-policy", choices=["prompt", "allow", "deny"], help="审批策略")
    o.add_argument("--backend", choices=["mock", "local_openai"],
                   help="覆盖 model.backend(子任务共享此后端)")
    o.add_argument("--max-workers", type=int, default=None,
                   help="并行子任务数(默认 config agent.orchestrator.max_workers)")
    o.set_defaults(func=cmd_orchestrate)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
