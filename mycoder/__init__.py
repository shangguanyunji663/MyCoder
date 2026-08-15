"""MyCoder — 本地 Coding Agent Harness。

一个面向代码仓库长链路任务的本地 Agent 运行底座,单仓库内解决:
  * 上下文膨胀    -> context 模块(预算裁剪)
  * 重复读文件    -> memory 模块(结构化分层记忆)+ safety 去重
  * 任务状态丢失  -> checkpoint 模块(断点/恢复 + 工作区漂移识别)
  * 结果难复盘    -> artifacts 模块(轨迹/检查点/指标报告)+ eval 评测审计

核心约束:全部本地运行,不依赖云端服务。
"""

from .version import __version__

__all__ = ["__version__"]