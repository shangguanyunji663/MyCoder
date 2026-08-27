# Changelog

本项目的所有显著变更记录于此文件。
格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/spec/v2.0.0.html)。

## [Unreleased]

### Added
- 环境工程化：仓库内置 Conda prefix 独立环境 `.conda/`(Python 3.11,由 Anaconda 管理,`.gitignore` 排除不入库),新增 `environment.yml` 与 `requirements-{dev,api,vector,project}.txt` 分拆清单;一条 `conda env create -p .conda -f environment.yml` 即可在任意机器完整重建。
- 企业化改造：新增 MIT LICENSE、GitHub Actions CI、Docker Compose（Ollama + FastAPI）、82 条检索评测集、Layer 6 Ollama 真实任务 + LLM-as-judge、Hashing/FastEmbed 对照入口，以及本地 vendored Vue 3 运行监控页。
- `LocalOpenAIBackend` 修复内部工具调用到 OpenAI 标准 `type/function` 格式的转换，兼容 Ollama 多轮工具调用。

### Changed
- 文档系统性审计(README/TESTING/OUTLINE/FINAL_SUMMARY/LEARNING_GUIDE):环境说明统一改为项目内置 `.conda` 环境,清除 ML2/base 及机器专属路径(`D:\ANACONDA\...`、`D:\DeepSeek Harness\...`)残留;测试统计修正为 **258 项/17 个文件**并为各文件标注实测用例数(test_safety 27→70、test_eval 14→18、test_models 14→15);benchmark 数据口径修正为手写任务 26 个 + 固定 seed 冻结基准 42 个;检索基准按 82 条查询的实测 recall/MRR 结果更新;LEARNING_GUIDE 新增「环境准备」与「模块关系一览」章节,补齐 Layer 6/7、`--suite real|embedder`、`GET /api/runs` 与 Vue 监控页等此前缺失的能力描述。

### Fixed
- `examples/giant_test.py`：修复生成模板转义残留的 `%%` 双百分号（非法 Python 语法），恢复为 `%`。

### Added
- `feat(observability)`: 新增 `observability/tracing.py`，零依赖 `Span`/`Tracer` 导出 OTLP 风格 `trace.json`；安装 `opentelemetry-api` 时自动桥接；`harness.build` 的 `on_event` 回调同时驱动默认 Tracer 与调用方事件总线；`logging.format: text|json` 结构化日志；`artifacts` 报告增加耗时时间线与成本小节。
- `feat(memory)`: 新增 `memory/vectors.py`，`EmbeddingProvider` + `HashingEmbedder`（零依赖确定性字符 n-gram 哈希，默认）+ `FastEmbedEmbedder`（可选 bge-small）；`VectorIndex`（余弦 + 持久化）+ 纯 Python `BM25`；混合检索 `score = α·cosine + (1-α)·bm25`；`StructuredMemory.search()` 支持 `substring`/`vector`/`hybrid` 三种模式（默认 substring 向后兼容）。
- `feat(eval)`: 评测升级为五层，新增 Layer 5 检索召回（`benchmarks/retrieval.json`，6 条同义改写查询，hybrid recall@3=100% vs substring=0%）；`eval --suite retrieval` 独立可跑。
- `feat(api)`: 新增 FastAPI + SSE 服务 `api/event_bus.py`（`TaskEventBus`）+ `api/fastapi_server.py`（`POST /api/run`、`GET /api/run/{id}`、`GET /api/run/{id}/events` SSE 含 `done` 哨兵 + 15s 心跳、`GET /api/artifacts/{id}/{name}`、`/health`、零构建 vanilla JS 实时轨迹页）；`cli serve --impl stdlib|fastapi`（默认 stdlib 保持零依赖）；`api` 依赖组可选。
- `feat(agent)`: 新增 `agent/orchestrator.py`，`Orchestrator` 由 `Planner`（默认确定性退化分解，可注入 LLM JSON 分解）产出子任务，各子任务由完全隔离根的子 `AgentHarness` 经 `ThreadPoolExecutor` 并行执行，失败降级标记 `failed` 不阻断整体，产出 `orchestration.json`，经 `on_event` 发出 `orchestration_start`/`subtask_end`/`orchestration_end`；`config agent.orchestrator.{enabled,max_workers}`（默认关闭）。
- `feat(cli)`: 新增 `orchestrate` 子命令（`--goal`/`--task-id`/`--config`/`--workspace`/`--hitl-policy`/`--backend`/`--max-workers`），把复杂目标分解为子任务并行编排执行。
- `feat(deps)`: `pyproject` optional-dependencies 分组 `api`/`vector`/`otel`/`dev`，核心保持仅依赖 PyYAML 的零依赖。

### Changed
- `refactor(config)`: `config.py` DEFAULT 补齐 `model.local_openai.*`、`model.pricing`、`context.summarizer`、`memory.retrieval.mode/alpha/embedder`、`logging.format`、`observability.enabled`、`agent.orchestrator.*`。
- `refactor(memory)`: `memory/store.py` 接入 `vectors.py` 检索模式切换，`search()` 新增 `mode` 参数。
- `refactor(eval)`: `eval/runner.py` 扩展 Layer 5 retrieval 评测与 A/B 对照框架；`tests/test_eval.py` 覆盖五层。
- `refactor(agent)`: `agent/harness.py` 注入最小侵入 `on_event`；`agent/__init__.py` 导出 `Orchestrator`；`api/__init__.py` 增加 `impl` 开关。
- `test`: 新增 `tests/test_observability.py`(7)/`test_vectors.py`(11)/`test_api.py`(3)/`test_orchestrator.py`(4)/`test_cost.py`(5)/`test_backend.py`(9)；全量测试升至 **206 项 / 16 个测试文件**。

### Docs
- 新增 `docs/IMPROVEMENT_PLAN.md`：企业化改造整体计划（背景评估、分期范围、验收标准、结果记录）。
- 新增 `CHANGELOG.md`（本文件）：与 conventional commits 提交一一对应。
- `docs/IMPROVEMENT_PLAN.md`：补齐 Phase 3–7 落地状态与结果记录，全部标记已完成；评测口径统一为五层 / 206 项。
- `README.md` / `docs/ARCHITECTURE.md` / `docs/TESTING.md` / `docs/OUTLINE.md` / `docs/FINAL_SUMMARY.md` / `docs/LEARNING_GUIDE.md`：同步可观测性、向量记忆、五层评测、FastAPI+SSE、子代理编排、`orchestrate` CLI、成本计量、依赖分组等新能力；测试计数统一为 206 项 / 16 文件；去除机器专属路径。
