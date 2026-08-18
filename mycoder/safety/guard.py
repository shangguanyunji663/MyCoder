"""工具安全边界:参数校验 / 工作区隔离 / 高风险审批(HITL)/ 重复调用拦截。

设计原则:安全层与业务层正交。工具 execute 不关心安全,所有调用在进入
execute 之前都必须通过 SafetyGuard 的检查链:

    schema 校验 -> 路径隔离 -> shell 白/黑名单 -> 重复调用 -> HITL 审批

其中"重复调用拦截"专门打击长任务里的重复读文件:读类工具(key 相同)第二次
调用直接返回缓存,不再读盘。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..tools.base import HITL, Tool
from ..tools.sandbox import PathEscapeError


# --------------------------------------------------------------------------
# 参数校验(轻量 JSON Schema 子集)
# --------------------------------------------------------------------------
_TYPE_MAP = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
             "array": list, "object": dict}


def validate_params(schema: dict, params: dict) -> list[str]:
    """返回错误列表;为空表示通过。"""
    errors: list[str] = []
    props = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in params:
            errors.append(f"缺少必填参数: {key}")
    for key, value in params.items():
        if key not in props:
            errors.append(f"未知参数: {key}")
            continue
        spec = props[key]
        expect_type = spec.get("type")
        if expect_type and not _type_ok(expect_type, value):
            errors.append(f"参数 {key} 类型应为 {expect_type},实际 {type(value).__name__}")
        if "enum" in spec and value not in spec["enum"]:
            errors.append(f"参数 {key} 取值非法: {value!r}(允许 {spec['enum']})")
        if expect_type == "integer" and isinstance(value, int):
            if "minimum" in spec and value < spec["minimum"]:
                errors.append(f"参数 {key} 低于下限 {spec['minimum']}")
            if "maximum" in spec and value > spec["maximum"]:
                errors.append(f"参数 {key} 超过上限 {spec['maximum']}")
    return errors


def _type_ok(expect: str, value: Any) -> bool:
    t = _TYPE_MAP.get(expect)
    if t is None:
        return True
    return isinstance(value, t)


# --------------------------------------------------------------------------
# 审批提供方(HITL)
# --------------------------------------------------------------------------
class ApprovalProvider:
    """HITL 审批接口;不同策略注入不同实现。"""
    def approve(self, action: dict) -> bool:
        raise NotImplementedError


class AllowAllProvider(ApprovalProvider):
    def approve(self, action: dict) -> bool:
        return True


class DenyAllProvider(ApprovalProvider):
    def approve(self, action: dict) -> bool:
        return False


class CallbackProvider(ApprovalProvider):
    """测试/脚本用:把审批决定委托给一个回调。"""
    def __init__(self, fn):
        self.fn = fn
    def approve(self, action: dict) -> bool:
        return bool(self.fn(action))


class PromptProvider(ApprovalProvider):
    """交互式审批:stdin 输入 y/n(本地 CLI 使用)。"""
    def approve(self, action: dict) -> bool:
        print("\n⚠ 需要人工审批的高风险操作:")
        print("  " + json.dumps(action, ensure_ascii=False, indent=2))
        ans = input("  是否允许?[y/N] ").strip().lower()
        return ans in ("y", "yes")


# --------------------------------------------------------------------------
# 检查结果
# --------------------------------------------------------------------------
@dataclass
class GuardResult:
    allowed: bool
    needs_approval: bool = False
    reason: str = ""
    cached_output: str | None = None   # 去重短路时回填缓存结果
    danger: str = "safe"
    action: dict = field(default_factory=dict)


class SafetyGuard:
    _PATH_TOOLS = {"file_read", "file_write", "file_edit", "grep_search", "shell_exec"}

    def __init__(self, config, workspace, approver: ApprovalProvider | None = None,
                 redactor=None):
        self.config = config
        self.workspace = workspace
        self.redactor = redactor
        # 去重缓存: (tool.name, canonical_params) -> (count, last_output)
        self._dedup: dict[str, tuple[int, str]] = {}
        self.read_cache_hits = 0
        self.skipped_repeats = 0
        self.denied = 0
        self._approver = approver or self._default_approver()

    def _default_approver(self) -> ApprovalProvider:
        policy = self.config.get("safety.hitl_policy", "prompt")
        return {"allow": AllowAllProvider(), "deny": DenyAllProvider(),
                "prompt": PromptProvider()}.get(policy, PromptProvider())

    def approve(self, action: dict) -> bool:
        """公有审批入口:委托给当前 ApprovalProvider,拒绝时计入 denied 指标。"""
        ok = self._approver.approve(action)
        if not ok:
            self.denied += 1
        return ok

    # ------------------------------------------------------------------
    def check(self, tool: Tool, params: dict) -> GuardResult:
        # 1. 参数校验
        errors = validate_params(tool.parameters, params)
        if errors:
            self.denied += 1
            return GuardResult(False, reason="参数校验失败: " + "; ".join(errors))

        # 2. 路径隔离(含 shell.cwd)
        if tool.name in self._PATH_TOOLS:
            for key in ("path", "cwd"):
                if key in params and params[key]:
                    try:
                        self.workspace.resolve(params[key])
                    except PathEscapeError as e:
                        self.denied += 1
                        return GuardResult(False, reason=str(e))

        # 3. shell 白名单/黑名单
        if tool.name == "shell_exec":
            reason = self._check_shell(params.get("command", ""))
            if reason:
                self.denied += 1
                return GuardResult(False, reason=reason)

        # 4. 重复调用拦截
        if self.config.get("safety.dedup_enabled", True):
            key = self._dedup_key(tool.name, params)
            if key in self._dedup:
                count, last_output = self._dedup[key]
                if tool.danger == HITL or tool.name in ("file_write", "file_edit"):
                    self.skipped_repeats += 1
                else:
                    self.read_cache_hits += 1
                # 更新计数,返回缓存输出(短路由,不再执行)
                self._dedup[key] = (count + 1, last_output)
                return GuardResult(True, cached_output=last_output,
                                   reason="重复调用被拦截,复用缓存结果", danger=tool.danger,
                                   action={"tool": tool.name, "params": params, "repeat": count + 1})

        # 5. HITL 审批
        needs = tool.danger == HITL
        action = {"tool": tool.name, "params": params, "danger": tool.danger}
        return GuardResult(True, needs_approval=needs, reason="", danger=tool.danger, action=action)

    def record_executed(self, tool: Tool, params: dict, output: str) -> None:
        """执行成功后登记到去重缓存。"""
        if not self.config.get("safety.dedup_enabled", True):
            return
        key = self._dedup_key(tool.name, params)
        count = self._dedup[key][0] if key in self._dedup else 0
        self._dedup[key] = (count + 1, output)

    # ------------------------------------------------------------------
    @staticmethod
    def _dedup_key(name: str, params: dict) -> str:
        return name + "|" + json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)

    def _check_shell(self, command: str) -> str | None:
        allow = set(self.config.get("safety.shell.allow_commands", []))
        deny = self.config.get("safety.shell.deny_patterns", [])
        tokens = command.strip().split()
        if not tokens:
            return "空命令"
        base = tokens[0].lower()
        # 去掉可能的前导路径,如 ./script.py、python3 -> python 不在这里处理
        if base not in {a.lower() for a in allow}:
            return f"命令不在白名单: {tokens[0]}(白名单={sorted(allow)})"
        for pat in deny:
            if re.search(pat, command):
                return f"命中高危模式 {pat!r},已拦截"
        return None