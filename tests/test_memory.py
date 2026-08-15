"""结构化记忆测试:三层存储、去重、检索、follow-up 上下文、持久化。"""
import pytest

from mycoder.memory import StructuredMemory, summarize_file_content


@pytest.fixture
def mem(tmp_path, memory):
    return memory


class TestTaskLayer:
    def test_remember_task(self, mem):
        mem.remember_task("t1", goal="做 X", status="completed", summary="完成了",
                          files=["a.py"])
        rec = mem.get_task("t1")
        assert rec.goal == "做 X" and rec.status == "completed"

    def test_remember_task_update(self, mem):
        mem.remember_task("t1", goal="g")
        mem.remember_task("t1", status="completed")
        assert mem.get_task("t1").status == "completed"

    def test_parent_link(self, mem):
        mem.remember_task("parent", goal="g")
        mem.remember_task("child", goal="c", parent_task_id="parent")
        assert mem.parent_of("child") == "parent"


class TestFileLayer:
    def test_remember_file_symbols(self, mem):
        updated, rec = mem.remember_file("utils.py",
                                         content="def add(a,b): pass\nclass Foo: pass\n",
                                         task_id="t1")
        assert updated
        assert rec.symbols  # 提取到 def/class 符号

    def test_same_hash_skip(self, mem):
        mem.remember_file("a.py", content="SAME", task_id="t1")
        updated, _ = mem.remember_file("a.py", content="SAME", task_id="t1")
        assert not updated  # 内容未变 => 不重算

    def test_hash_change_updates(self, mem):
        mem.remember_file("a.py", content="v1")
        updated, rec = mem.remember_file("a.py", content="v2")
        assert updated and rec.summary != ""

    def test_has_fresh_summary(self, mem):
        from mycoder.util import sha256_text
        mem.remember_file("a.py", content="v1")
        assert mem.has_fresh_summary("a.py", sha256_text("v1"))
        assert not mem.has_fresh_summary("a.py", sha256_text("v2"))

    def test_summarize_extracts_symbols(self):
        summary, symbols = summarize_file_content("def f(): pass\n# comment\nclass C: pass\nimport os\n")
        assert "def f" in symbols[0] and "class C" in symbols[1]


class TestRelationLayer:
    def test_link_task_file(self, mem):
        mem.link_task_file("t1", "a.py")
        mem.link_task_file("t1", "a.py")  # 重复链接应去重
        assert mem.files_for_task("t1") == ["a.py"]

    def test_remember_file_links(self, mem):
        mem.remember_file("a.py", content="x", task_id="t1")
        assert mem.files_for_task("t1") == ["a.py"]


class TestSearch:
    def test_search_task(self, mem):
        mem.remember_task("t1", goal="实现缓存模块", status="completed", summary="done")
        out = mem.search("缓存", kind="task")
        assert "t1" in out

    def test_search_file(self, mem):
        mem.remember_file("config.py", content="APP_NAME='x'", task_id="t1")
        out = mem.search("config", kind="file")
        assert "config.py" in out

    def test_search_relation(self, mem):
        mem.remember_task("t9", goal="g", files=["utils.py"], parent_task_id="t8")
        out = mem.search("utils", kind="relation")
        assert "t9" in out or "t8" in out

    def test_search_miss(self, mem):
        assert mem.search("zzz") == ""


class TestFollowupContext:
    def test_includes_parent_files(self, mem):
        mem.remember_task("parent", goal="建模块", status="completed", files=["utils.py"])
        mem.remember_file("utils.py", content="def add(a,b): return a+b", task_id="parent")
        block = mem.followup_context(task_id="child", parent_task_id="parent")
        assert "parent" in block and "utils.py" in block

    def test_parent_auto_via_relation(self, mem):
        mem.remember_task("parent", goal="g", files=["c.py"])
        mem.remember_file("c.py", content="x=1", task_id="parent")
        mem.remember_task("child", goal="c", parent_task_id="parent")
        assert mem.followup_context(task_id="child")


class TestPersistence:
    def test_save_load_roundtrip(self, tmp_path):
        m1 = StructuredMemory(tmp_path / "mem", enabled=True)
        m1.remember_task("t1", goal="g", files=["a.py"])
        m1.remember_file("a.py", content="code", task_id="t1")
        m2 = StructuredMemory(tmp_path / "mem", enabled=True)
        assert m2.get_task("t1").goal == "g"
        assert m2.get_file("a.py") is not None

    def test_stats(self, mem):
        mem.remember_task("t1", goal="g", files=["a.py"])
        mem.remember_file("a.py", content="x", task_id="t1")
        st = mem.stats()
        assert st["tasks"] == 1 and st["files"] == 1

    def test_disabled_no_save(self, tmp_path):
        m = StructuredMemory(tmp_path / "mem", enabled=False)
        m.remember_task("t1", goal="g")
        assert not (tmp_path / "mem" / "tasks.json").exists()