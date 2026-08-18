"""模型后端包。

对外提供:
  * ModelBackend / ModelResponse 抽象
  * MockBackend       —— 确定性脚本后端(测试/评测,全离线)
  * LocalOpenAIBackend —— 本地 OpenAI 兼容后端(127.0.0.1)
  * create_backend(config) —— 工厂:按配置实例化 2 类后端中的一种
"""
from .base import ModelBackend, ModelResponse, tools_to_openai
from .local_openai import LocalOpenAIBackend
from .mock import MockBackend

__all__ = [
    "LocalOpenAIBackend",
    "MockBackend",
    "ModelBackend",
    "ModelResponse",
    "tools_to_openai",
]


def create_backend(config) -> ModelBackend:
    """根据配置节 model.backend 装配后端。"""
    from ..config import Config
    if isinstance(config, dict):
        config = Config(config)
    kind = config.model_backend
    if kind == "mock":
        return MockBackend(seed=config.get("model.mock.seed", 42))
    if kind == "local_openai":
        o = config.get("model.local_openai", {})
        return LocalOpenAIBackend(
            base_url=o.get("base_url", "http://127.0.0.1:8080/v1"),
            api_key=o.get("api_key", "local"),
            model=o.get("model", "qwen2.5-coder-7b"),
            temperature=o.get("temperature", 0.0),
            timeout_seconds=o.get("timeout_seconds", 60),
        )
    raise ValueError(f"未知模型后端: {kind}(支持 mock / local_openai)")
