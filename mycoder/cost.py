"""Token 成本核算:价格表 + 运行级累加。

设计:
  * 价格表来自 config `model.pricing`,形如:
        {"qwen2.5-coder-7b": {"input_per_1k": 0.0001, "output_per_1k": 0.0002}}
    支持通配键 "*" 作为缺省价目;
  * CostTracker 只做纯函数式累加(输入 prompt/completion token 数,输出美元),
    与模型调用链路正交,便于评测与单测;
  * 未配置 pricing 时全部返回 0,不打扰既有零依赖运行。
"""
from __future__ import annotations

from typing import Any


class CostTracker:
    """按价格表核算单次/累计成本。"""

    def __init__(self, pricing: dict[str, dict[str, float]] | None = None):
        self.pricing: dict[str, dict[str, float]] = dict(pricing or {})

    def cost_of(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """单次调用成本(美元)。未配置该模型时返回 0。"""
        rate = self.pricing.get(model) or self.pricing.get("*")
        if not rate:
            return 0.0
        input_per_1k = float(rate.get("input_per_1k", 0.0))
        output_per_1k = float(rate.get("output_per_1k", 0.0))
        return (prompt_tokens / 1000.0) * input_per_1k + \
            (completion_tokens / 1000.0) * output_per_1k

    def has_pricing(self, model: str) -> bool:
        return bool(self.pricing.get(model) or self.pricing.get("*"))

    @staticmethod
    def from_config(config: Any) -> CostTracker:
        """从 Config 构建(缺省返回零成本跟踪器)。"""
        pricing = config.get("model.pricing", {}) if hasattr(config, "get") else {}
        return CostTracker(pricing)
