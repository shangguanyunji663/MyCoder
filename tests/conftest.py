"""pytest 公共夹具。

先确保项目根目录可被 import(未安装包时也能跑测试),
再提供 config/workspace/memory/make_harness 等常用夹具。
"""
from __future__ import annotations

import sys
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mycoder.config import Config  # noqa: E402


# Override pytest's tmp_path to use local directory (avoids Windows permission issues)
_tmp_base = ROOT / ".pytest_tmp"


class LocalTmpPathFactory:
    """Custom tmp_path_factory that uses local .pytest_tmp directory."""
    
    def __init__(self):
        self._basetemp = _tmp_base
        _tmp_base.mkdir(exist_ok=True)
    
    def mktemp(self, basename: str, numbered: bool = True) -> Path:
        """Create a temporary directory."""
        import uuid
        if numbered:
            tmp_dir = self._basetemp / f"{basename}_{uuid.uuid4().hex[:8]}"
        else:
            tmp_dir = self._basetemp / basename
        tmp_dir.mkdir(exist_ok=True)
        return tmp_dir
    
    def getbasetemp(self) -> Path:
        """Return the base temporary directory."""
        return self._basetemp


@pytest.fixture(scope="session")
def tmp_path_factory():
    """Override pytest's tmp_path_factory to use local directory."""
    factory = LocalTmpPathFactory()
    yield factory
    # Cleanup at session end
    try:
        import shutil
        if _tmp_base.exists():
            shutil.rmtree(_tmp_base, ignore_errors=True)
    except Exception:
        pass


@pytest.fixture(scope="session", autouse=True)
def setup_tmp_base():
    """Create the base tmp directory once at session start."""
    _tmp_base.mkdir(exist_ok=True)
    yield
    # Cleanup at session end
    try:
        import shutil
        if _tmp_base.exists():
            shutil.rmtree(_tmp_base, ignore_errors=True)
    except Exception:
        pass


@pytest.fixture
def tmp_path(setup_tmp_base):
    """Provide a temporary directory within the project (Windows-friendly)."""
    import uuid
    tmp_dir = _tmp_base / f"test_{uuid.uuid4().hex[:8]}"
    tmp_dir.mkdir(exist_ok=True)
    yield tmp_dir


@pytest.fixture
def config() -> Config:
    return Config()


@pytest.fixture
def workspace(tmp_path):
    from mycoder.tools import Workspace
    return Workspace(tmp_path / "ws")


@pytest.fixture
def memory(tmp_path):
    from mycoder.memory import StructuredMemory
    return StructuredMemory(tmp_path / "memory", enabled=True)


@pytest.fixture
def make_harness(tmp_path, config):
    """构建隔离的 harness 工厂:所有产物都落在 tmp_path 内,互不污染。"""
    from mycoder.agent import AgentHarness
    from mycoder.models import MockBackend
    from mycoder.safety import AllowAllProvider

    def _make(script=None, approver=None, memory_enabled=True, **cfg_overrides):
        cfg = Config(config.to_dict())
        cfg.set("workspace.root", str(tmp_path / "ws"))
        cfg.set("memory.root", str(tmp_path / "memory"))
        cfg.set("memory.enabled", memory_enabled)
        cfg.set("checkpoint.root", str(tmp_path / "checkpoints"))
        cfg.set("artifacts.root", str(tmp_path / "artifacts"))
        for k, v in cfg_overrides.items():
            cfg.set(k, v)
        backend = MockBackend(script=script or [], default_answer="任务完成。")
        return AgentHarness.build(cfg, backend=backend,
                                  approver=approver or AllowAllProvider())
    return _make