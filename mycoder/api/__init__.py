"""localhost API 包。

提供两种实现:
  * 标准库实现(server.run_server,零依赖) —— 默认;
  * FastAPI + SSE 实现(fastapi_server.create_app,可选依赖 fastapi/uvicorn)。

run_server(config, host, port, impl) 统一入口,impl ∈ {stdlib, fastapi}。
"""
from .event_bus import TaskEventBus
from .server import run_server as _stdlib_run_server
from .trace_page import _TRACE_PAGE  # noqa: F401  (供 fastapi_server 的 GET / 使用)

__all__ = ["run_server", "TaskEventBus", "create_app"]


def create_app(config):
    """构建 FastAPI 应用(延迟导入 fastapi)。"""
    from .fastapi_server import create_app as _create
    return _create(config)


def run_server(config, host: str = "127.0.0.1", port: int = 8910,
               impl: str = "stdlib") -> None:
    if impl == "fastapi":
        try:
            import uvicorn  # noqa: F401
        except ImportError:  # pragma: no cover - 依赖缺失时给清晰提示
            raise SystemExit(
                "FastAPI 实现需要安装可选依赖: pip install 'mycoder-harness[api]'")
        app = create_app(config)
        print(f"[MyCoder API] FastAPI 服务已启动: http://{host}:{port}")
        uvicorn.run(app, host=host, port=port)
    else:
        _stdlib_run_server(config, host=host, port=port)
