# Changelog

本项目的所有显著变更记录于此文件。
格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/spec/v2.0.0.html)。

## [Unreleased]

### Fixed
- `examples/giant_test.py`：修复生成模板转义残留的 `%%` 双百分号（非法 Python 语法），恢复为 `%`。

### Docs
- 新增 `docs/IMPROVEMENT_PLAN.md`：企业化改造整体计划（背景评估、分期范围、验收标准、结果记录）。
- 新增 `CHANGELOG.md`（本文件）：与 conventional commits 提交一一对应。
