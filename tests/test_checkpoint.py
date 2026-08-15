"""断点存储与工作区漂移识别测试。"""
import pytest

from mycoder.checkpoint import CheckpointStore, DriftReport, WorkspaceDriftDetector


@pytest.fixture
def cp(tmp_path):
    return CheckpointStore(tmp_path / "checkpoints", enabled=True)


class TestStore:
    def test_save_load(self, cp):
        cp.save("t1", {"a": 1, "nested": {"b": [1, 2]}})
        data = cp.load("t1")
        assert data["a"] == 1 and data["nested"]["b"] == [1, 2]

    def test_exists_and_list(self, cp):
        cp.save("t1", {})
        cp.save("t2", {})
        assert cp.exists("t1")
        assert cp.list_all() == ["t1", "t2"]

    def test_load_missing_returns_none(self, cp):
        assert cp.load("zz") is None

    def test_disabled_store(self, tmp_path):
        c2 = CheckpointStore(tmp_path / "c2", enabled=False)
        c2.save("t1", {"x": 1})
        assert not c2.exists("t1")

    def test_unicode_roundtrip(self, cp):
        cp.save("t1", {"msg": "中文内容 ✓"})
        assert cp.load("t1")["msg"] == "中文内容 ✓"

    def test_overwrite(self, cp):
        cp.save("t1", {"v": 1})
        cp.save("t1", {"v": 2})
        assert cp.load("t1")["v"] == 2


class TestDrift:
    def _snap(self, **items):
        return {k: "h" * 64 if v == "h" else v for k, v in items.items()}

    def test_no_drift(self):
        a = self._snap(f1="h", f2="h")
        d = WorkspaceDriftDetector.compare(a, dict(a))
        assert not d.is_drift

    def test_modified(self):
        a = self._snap(f1="h1", f2="h2")
        b = self._snap(f1="h1x", f2="h2")
        d = WorkspaceDriftDetector.compare(a, b)
        assert d.is_drift and d.modified == ["f1"]

    def test_added(self):
        a = self._snap(f1="h")
        b = self._snap(f1="h", f2="h")
        d = WorkspaceDriftDetector.compare(a, b)
        assert d.added == ["f2"]

    def test_deleted(self):
        a = self._snap(f1="h", f2="h")
        b = self._snap(f1="h")
        d = WorkspaceDriftDetector.compare(a, b)
        assert d.deleted == ["f2"]

    @pytest.mark.parametrize("mutate", ["modify", "add", "delete"])
    def test_any_change_is_drift(self, mutate):
        before = {"a": ("h1" if mutate == "modify" else "h"),
                  "b": "h"}
        after = dict(before)
        if mutate == "modify":
            after["a"] = "h2"
        elif mutate == "add":
            after["c"] = "h"
        else:
            del after["b"]
        d = WorkspaceDriftDetector.compare(before, after)
        assert d.is_drift

    def test_summary_text(self):
        d = DriftReport(modified=["a"], added=[], deleted=[])
        assert "漂移" in d.summary()
        assert DriftReport().summary() == "(无漂移:工作区与断点时一致)"

    def test_empty_workspaces(self):
        d = WorkspaceDriftDetector.compare({}, {})
        assert not d.is_drift