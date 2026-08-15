"""工作区沙箱:路径隔离、rel 兼容、指纹快照。"""
import pytest

from mycoder.tools import PathEscapeError, Workspace


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path / "ws")


class TestResolve:
    @pytest.mark.parametrize("bad", [
        "../x.txt", "../../etc/passwd", "a/../../b.txt", "..\\evil",
    ])
    def test_traversal_blocked(self, ws, bad):
        with pytest.raises(PathEscapeError):
            ws.resolve(bad)

    def test_normalize_inside(self, ws):
        ws.write_text("a/b.txt", "x")
        p = ws.resolve("a/../a/b.txt")
        assert p == (ws.root / "a/b.txt").resolve()

    def test_absolute_allowed_when_cfg(self, tmp_path):
        w = Workspace(tmp_path / "ws", allow_absolute=True)
        w.write_text("z.txt", "x")
        p = w.resolve(str(w.root / "z.txt"))
        assert p.exists()

    def test_absolute_rejected_default(self, ws, tmp_path):
        with pytest.raises(PathEscapeError):
            ws.resolve(str(tmp_path / "elsewhere" / "f.txt"))


class TestRel:
    def test_rel_relative(self, ws):
        ws.write_text("a.txt", "x")
        assert ws.rel("a.txt") == "a.txt"

    def test_rel_accepts_resolved_abs(self, ws):
        ws.write_text("a.txt", "x")
        abs_p = ws.resolve("a.txt")
        assert ws.rel(abs_p) == "a.txt"

    def test_rel_escape(self, ws, tmp_path):
        with pytest.raises(PathEscapeError):
            ws.rel(str(tmp_path.parent / "out.txt"))


class TestSnapshot:
    def test_snapshot_hashes(self, ws):
        ws.write_text("a.py", "one")
        ws.write_text("b.py", "two")
        snap = ws.snapshot()
        assert set(snap) == {"a.py", "b.py"}
        assert len(snap["a.py"]) == 64

    def test_snapshot_excludes_hidden_and_pycache(self, ws):
        ws.write_text(".hidden", "x")
        ws.write_text("__pycache__/c.pyc", "y")
        ws.write_text("visible.py", "z")
        snap = ws.snapshot()
        assert snap == {"visible.py": snap["visible.py"]}

    def test_snapshot_detects_change(self, ws):
        ws.write_text("f.txt", "v1")
        a = ws.snapshot()
        ws.write_text("f.txt", "v2")
        b = ws.snapshot()
        assert a["f.txt"] != b["f.txt"]


class TestListFiles:
    def test_list_ignores_hidden(self, ws):
        ws.write_text(".env", "x")
        ws.write_text("ok.py", "y")
        assert ws.list_files("*") == ["ok.py"]

    def test_list_posix_sep(self, ws):
        ws.write_text("sub/x.py", "y")
        assert ws.list_files("**/*.py") == ["sub/x.py"]