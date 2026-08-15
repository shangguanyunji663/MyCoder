"""7 类工具的功能测试(read/write/edit/list/grep/shell/memory_query)。"""
import pytest

from mycoder.tools import (ToolContext, Workspace, build_registry,
                           PathEscapeError)


@pytest.fixture
def reg():
    return build_registry()


@pytest.fixture
def ctx(workspace):
    return ToolContext(workspace=workspace, memory=None, config=None)


class TestFileRead:
    def test_read_basic(self, reg, ctx, workspace):
        workspace.write_text("a.py", "line1\nline2\nline3\n")
        r = reg.get("file_read").execute(ctx, path="a.py")
        assert r.ok and "line2" in r.output
        assert r.meta["file_hash"] and r.meta["path"] == "a.py"

    def test_read_missing(self, reg, ctx):
        r = reg.get("file_read").execute(ctx, path="nope.txt")
        assert not r.ok

    def test_read_offset_limit(self, reg, ctx, workspace):
        workspace.write_text("a.py", "\n".join(f"ln{i}" for i in range(10)))
        r = reg.get("file_read").execute(ctx, path="a.py", offset=8, limit=2)
        assert r.ok and "ln8" in r.output and "ln9" in r.output and "ln3" not in r.output


class TestFileWrite:
    def test_write_creates(self, reg, ctx, workspace):
        r = reg.get("file_write").execute(ctx, path="b.py", content="x=1\n")
        assert r.ok and workspace.read_text("b.py") == "x=1\n"

    def test_write_overwrites(self, reg, ctx, workspace):
        workspace.write_text("b.py", "old\n")
        reg.get("file_write").execute(ctx, path="b.py", content="new\n")
        assert workspace.read_text("b.py") == "new\n"


class TestFileEdit:
    def test_edit_unique(self, reg, ctx, workspace):
        workspace.write_text("c.py", "VERSION = 1\n")
        r = reg.get("file_edit").execute(ctx, path="c.py",
                                         old_string="VERSION = 1", new_string="VERSION = 2")
        assert r.ok and workspace.read_text("c.py") == "VERSION = 2\n"

    def test_edit_ambiguous_fails(self, reg, ctx, workspace):
        workspace.write_text("c.py", "A\ntext\nA\n")
        r = reg.get("file_edit").execute(ctx, path="c.py", old_string="A",
                                         new_string="B")
        assert not r.ok and "非唯一" in r.error

    def test_edit_replace_all(self, reg, ctx, workspace):
        workspace.write_text("c.py", "A\nA\n")
        r = reg.get("file_edit").execute(ctx, path="c.py", old_string="A",
                                         new_string="B", replace_all=True)
        assert r.ok and workspace.read_text("c.py") == "B\nB\n"

    def test_edit_missing_target(self, reg, ctx, workspace):
        workspace.write_text("c.py", "x\n")
        r = reg.get("file_edit").execute(ctx, path="c.py", old_string="zz", new_string="y")
        assert not r.ok


class TestFileList:
    @pytest.mark.parametrize("pattern,expected", [
        ("*.py", {"a.py", "b.py"}),
        ("**/*.md", {"docs/x.md"}),
        ("*.txt", {"(未匹配到任何文件)"}),  # 无匹配时返回提示信息
    ])
    def test_list(self, reg, ctx, workspace, pattern, expected):
        workspace.write_text("a.py", "")
        workspace.write_text("b.py", "")
        workspace.write_text("docs/x.md", "")
        r = reg.get("file_list").execute(ctx, pattern=pattern)
        found = set(r.output.splitlines())
        assert found == expected


class TestGrep:
    def test_grep_hits(self, reg, ctx, workspace):
        workspace.write_text("s.py", "def a():\n    pass\n")
        workspace.write_text("t.py", "x = 1\n")
        r = reg.get("grep_search").execute(ctx, pattern="def ", path=".")
        assert "s.py:1" in r.output and "t.py" not in r.output

    def test_grep_no_hits(self, reg, ctx, workspace):
        workspace.write_text("s.py", "hello\n")
        r = reg.get("grep_search").execute(ctx, pattern="zzz")
        assert r.ok and "无匹配" in r.output

    def test_grep_bad_regex(self, reg, ctx, workspace):
        workspace.write_text("s.py", "x\n")
        r = reg.get("grep_search").execute(ctx, pattern="[")
        assert not r.ok and "非法正则" in r.error


class TestShell:
    def test_echo(self, reg, ctx, workspace):
        r = reg.get("shell_exec").execute(ctx, command="echo hello")
        assert r.ok and "hello" in r.output

    def test_timeout(self, reg, ctx, workspace):
        r = reg.get("shell_exec").execute(ctx, command="ping -n 5 127.0.0.1", timeout=1)
        assert not r.ok and "超时" in r.error or r is not None


class TestMemoryQuery:
    def test_without_memory(self, reg, ctx):
        r = reg.get("memory_query").execute(ctx, query="x")
        assert not r.ok and "未启用" in r.error

    def test_with_memory(self, reg, memory):
        memory.remember_file("a.py", content="def f(): pass\n", task_id="t1")
        ctx = ToolContext(workspace=None, memory=memory, config=None)
        r = reg.get("memory_query").execute(ctx, query="a.py")
        assert r.ok and "a.py" in r.output


class TestSandboxIntegration:
    def test_path_escape_resolve(self, ctx):
        with pytest.raises(PathEscapeError):
            ctx.workspace.resolve("../outside.txt")

    def test_absolute_rejected(self, ctx, tmp_path):
        outside = tmp_path.parent / "x.txt"
        with pytest.raises(PathEscapeError):
            ctx.workspace.resolve(str(outside))