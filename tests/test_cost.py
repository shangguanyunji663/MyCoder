"""成本核算测试:价格表、通配、未配置回零。"""
from __future__ import annotations

import pytest

from mycoder.config import Config
from mycoder.cost import CostTracker


def test_zero_when_no_pricing():
    tr = CostTracker()
    assert tr.cost_of("any", 1000, 500) == 0.0
    assert tr.has_pricing("any") is False


def test_exact_model_pricing():
    tr = CostTracker({"m1": {"input_per_1k": 1.0, "output_per_1k": 2.0}})
    assert tr.cost_of("m1", 1000, 1000) == 3.0   # 1*1 + 1*2
    assert tr.cost_of("m1", 500, 250) == 1.0     # 0.5*1 + 0.25*2
    assert tr.has_pricing("m1") is True


def test_wildcard_fallback():
    tr = CostTracker({"*": {"input_per_1k": 0.5, "output_per_1k": 1.0}})
    assert tr.cost_of("unknown-model", 1000, 1000) == 1.5


def test_partial_rate_defaults_zero():
    tr = CostTracker({"m1": {"input_per_1k": 1.0}})
    assert tr.cost_of("m1", 1000, 1000) == 1.0   # 输出价缺省为 0


def test_from_config():
    cfg = Config({"model": {"pricing": {"*": {"input_per_1k": 0.1, "output_per_1k": 0.2}}}})
    tr = CostTracker.from_config(cfg)
    assert tr.cost_of("x", 1000, 1000) == pytest.approx(0.3)

    empty = CostTracker.from_config(Config())
    assert empty.cost_of("x", 1000, 1000) == 0.0
