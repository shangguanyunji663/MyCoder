"""shell 工具(1 个):shell_exec。

高风险治理由 safety 层负责:白名单命令 + 黑名单模式 + HITL 审批;
本工具只做"受限执行"——工作目录锁定在工作区、超时强制、禁止捕获交互输入。
"""
from __future__ import annotations

import subprocess
import time

from .base import HITL, Tool, ToolContext, ToolResult


class ShellExecTool(Tool):
    name = "shell_exec"
    description = "在工作区内执行一条只读/低风险 shell 命令(白名单+黑名单+人工审批三重管控)。"
    parameters = {  # noqa: RUF012 - 类级 schema 常量(非实例可变状态)
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
            "cwd": {"type": "string", "description": "相对工作区的运行目录(缺省=工作区根)"},
            "timeout": {"type": "integer", "description": "超时秒数,默认 10"},
        },
        "required": ["command"],
    }
    danger = HITL

    def execute(self, ctx: ToolContext, command: str, cwd: str | None = None,
                timeout: int = 10) -> ToolResult:
        workdir = ctx.workspace.resolve(cwd) if cwd else ctx.workspace.root
        if not workdir.is_dir():
            return ToolResult(ok=False, error=f"工作目录不存在: {cwd}")
        t0 = time.time()
        try:
            proc = subprocess.run(
                command, cwd=str(workdir), shell=True,
                capture_output=True, text=True, timeout=min(timeout, 30),
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, error=f"命令超时(>{timeout}s)被终止")
        except Exception as e:
            return ToolResult(ok=False, error=f"命令执行失败: {e}")

        out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        dt_ms = int((time.time() - t0) * 1000)
        return ToolResult(
            output=out or "(无输出)",
            ok=proc.returncode == 0,
            meta={"exit_code": proc.returncode, "latency_ms": dt_ms},
        )
