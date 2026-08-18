"""安全边界测试:参数校验 / 隔离 / HITL / 去重 / 脱敏。"""
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
        ("file_read", {}, False),                       # 缺必填
        ("file_read", {"path": "a.py", "bogus": 1}, False),  # 未知参数
        ("file_read", {"path": "a.py", "offset": "x"}, False),  # 类型错
        ("memory_query", {"query": "q", "kind": "file"}, True),
        ("memory_query", {"query": "q", "kind": "nope"}, False),  # enum 越界
        ("file_read", {"path": "a.py", "offset": -5}, False),  # 范围(minimum)
    ])
    def test_guard_validation(self, guard, tools, tool, params, expect_ok):
        gr = guard.check(tools.get(tool), params)
        assert gr.allowed is expect_ok, gr.reason
        if not expect_ok:
            assert gr.reason  # 有拦截原因

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


class TestShellPolicy:
    def test_not_in_allowlist(self, guard, tools):
        gr = guard.check(tools.get("shell_exec"), {"command": "powershell -c x"})
        assert not gr.allowed and "白名单" in gr.reason

    def test_deny_pattern(self, guard, tools):
        gr = guard.check(tools.get("shell_exec"), {"command": "echo safe; rm -rf /"})
        assert not gr.allowed and "高危" in gr.reason

    def test_allowlist_ok_needs_approval(self, guard, tools):
        gr = guard.check(tools.get("shell_exec"), {"command": "echo hi"})
        assert gr.allowed and gr.needs_approval  # HITL

    def test_empty_command(self, guard, tools):
        gr = guard.check(tools.get("shell_exec"), {"command": "  "})
        assert not gr.allowed


class TestHitl:
    def test_deny_provider_blocks(self, config, workspace, tools):
        g = SafetyGuard(config, workspace, approver=DenyAllProvider())
        gr = g.check(tools.get("shell_exec"), {"command": "echo x"})
        assert gr.allowed and gr.needs_approval
        action = gr.action
        assert not g._approver.approve(action)

    def test_callback_provider(self, config, workspace):
        g = SafetyGuard(config, workspace, approver=CallbackProvider(lambda a: a["tool"] == "shell_exec"))
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
        # 模拟执行成功并登记
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
    def test_api_key(self):
        r = Redactor()
        assert "[REDACTED_API_KEY]" in r.redact("key=sk-abcdefghijklmnopqrstuvwxyz") or \
               "REDACTED" in r.redact("sk-abcdefghijklmnopqrstuvwxyz")

    def test_password_kv(self):
        r = Redactor()
        out = r.redact("password=supersecret123")
        assert "supersecret123" not in out

    def test_private_key(self):
        r = Redactor()
        blob = "-----BEGIN RSA PRIVATE KEY-----\nAAAA\n-----END RSA PRIVATE KEY-----"
        out = r.redact(blob)
        assert "AAAA" not in out

    def test_disabled(self):
        r = Redactor(enabled=False)
        assert r.redact("sk-abcdefghijklmnopqrstuvwxyz") == "sk-abcdefghijklmnopqrstuvwxyz"

    def test_bearer(self):
        r = Redactor()
        assert "SECRETTOKEN" not in r.redact("Authorization: Bearer SECRETTOKEN")
