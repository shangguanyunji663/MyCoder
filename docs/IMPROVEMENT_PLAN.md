# MyCoder 企业化改造计划（Improvement Plan）

> 目标：把 MyCoder 从「思路良好的个人 demo」升级为「经得起面试官深挖的企业级 Agent Harness」。
> 本文档是改造的单一事实来源（Single Source of Truth）：每个 Phase 完成后更新状态与结论，
> 配合 `CHANGELOG.md`（与 git 提交一一对应）构成完整的工程决策记录。
>
> **状态注记（2026-08-28）**：文中提及的 GitHub Actions CI 已移除（远程质量门暂时下线）；
> 相关表述为历史过程记录。当前质量门以本地 `ruff check` / `mypy` / `pytest` 为准，
> 命令见 `docs/TESTING.md` 的「质量门(本地执行)」一节。

## 0. 背景评估（改造前的差距分析）

改造前项目已有亮点（保留并强化）：

- 分层解耦架构：models / tools / context / memory / checkpoint / safety / eval 七层正交；
- 确定性工程哲学：MockBackend 脚本化 + 五层评测（区分「模型能力」与「系统能力」）；
- 改造前已有 206 项 pytest 基线；本轮扩展后为 258 个收集用例（17 个测试文件；2026-08-27 Web 后端切换迭代后增至 262 项；2026-08-28 Layer 6b 裸基线对照迭代后增至 268 项 / 18 个文件）；安全链完整（schema 校验 → 路径沙箱 → shell 白/黑名单 → 去重 → HITL → 脱敏）。

面试官深挖会暴露的三类问题（本计划要解决）：

| 类别 | 问题 |
| --- | --- |
| 代码硬伤 | CLI 永远用 MockBackend（真实后端跑不起来）、永真条件死代码、跨对象私有访问、git 提交信息无规范、无 CI/lint |
| 真实链路 | README 指标全部来自脚本回放；无重试退避、无流式、token 靠启发式估算、无成本核算；摘要器纯启发式 |
| 生态脱节 | 记忆检索是子串匹配（无向量/语义检索）、API 同步阻塞（无 SSE/异步任务）、无子代理编排、无可观测性 |

## 1. 分期计划与验收标准

### Phase 1 — P0 代码硬伤清理 `[状态: 已完成]`

范围：

1. `mycoder/cli.py`：`cmd_run` 改用 `_make_backend()`（任务文件带 script → Mock，否则走 config 后端）；新增 `--backend` 覆盖参数；删除恒 None 表达式。
2. `mycoder/agent/harness.py`：删除 `or True` 永真条件（console 输出改由 `logging.console` 配置控制）；删除被立即覆盖的死代码；`guard._approver.approve` 改为 SafetyGuard 公有方法。
3. `mycoder/models/local_openai.py`：URL 拼接收敛为单一清晰逻辑。
4. `mycoder/eval/runner.py` 晦涩赋值写法、`mycoder/memory/store.py` 方法内 import 提升至模块顶部。
5. README 去除个人机器路径（`D:\ANACONDA\...`），命令通用化。
6. pyproject 增加 ruff + mypy 配置并修复全部告警；新增 GitHub Actions CI（3.10–3.12 矩阵：lint → typecheck → pytest + coverage）。

验收：206 项既有测试全绿；`ruff check` 与 `mypy` 零告警；`python -m mycoder run --backend local_openai` 能真实发起后端调用（无本地服务时报错清晰）。

### Phase 2 — P1 真实模型链路强化 `[状态: 已完成]`

范围：

1. LocalOpenAIBackend（保持 urllib 零依赖）：连接错误/429/5xx 自动重试 + 指数退避（尊重 Retry-After）；解析 API `usage` 做真实 token 计量（无 usage 回退启发式）；`complete_stream()` 流式输出（SSE 增量解析）。
2. `mycoder/cost.py`：按模型价格表（config `model.pricing`）核算每次运行成本，metrics / report.md / trajectory 全链路携带成本字段。
3. CLI `run`/`resume` 支持 local_openai；`eval --backend` 支持注入后端工厂。
4. `LLMSummarizer`：用模型压缩折叠轮次，失败自动回退确定性摘要器；默认保持 deterministic（不破坏既有确定性测试）；评测 Layer 2 扩展两种摘要器 A/B 对比。
5. README 指标区改双列：MockBackend（可复现回归）+ 真实模型（附复现命令；无本地服务不编造数字）。

验收：新增单测覆盖重试/退避/流式/usage 解析（monkeypatch 假 urlopen，全离线）；A/B 评测报告落盘。

### Phase 3 — P2.4 可观测性 `[状态: 已完成]`

范围：`mycoder/observability/tracing.py` 轻量 Span/Tracer（零依赖 JSON 导出，格式对齐 OTLP 风格；安装 opentelemetry-api 时自动桥接）；埋点覆盖 run / step / model 调用 / tool 调用 / checkpoint；`logging.format: text|json` 结构化日志；report.md 增加耗时时间线与成本小节。

验收：一次运行产出 trace.json（含完整 span 层级与耗时）；JSON 日志可被 `json.loads` 解析。

### Phase 4 — P2.1 向量记忆检索 `[状态: 已完成]`

范围：`mycoder/memory/vectors.py` — EmbeddingProvider 接口 + HashingEmbedder（零依赖、确定性、字符 n-gram 哈希，默认）+ FastEmbedEmbedder（可选依赖，bge-small，README 注明升级路径）；VectorIndex（余弦相似度、增量更新、持久化）+ 纯 Python BM25；混合检索 `score = α·cosine + (1-α)·bm25`；`StructuredMemory.search()` 接入（substring 模式保留向后兼容）；评测新增 Layer 5（retrieval）：同义改写查询用例 + recall@1/3/5 两种模式对照。

验收：同义查询场景下 hybrid recall@3 显著优于 substring；既有记忆测试不回归；CI 保持离线。

### Phase 5 — P2.2 FastAPI + SSE `[状态: 已完成]`

范围：`mycoder/api/fastapi_server.py`（可选依赖组 `api`）：`POST /api/run` 立即返回 task_id、任务后台线程执行（harness 增加最小侵入的 `on_event` 回调 + 进程内 EventBus）；`GET /api/run/{id}/events` SSE 实时推送 step/tool/完成事件；对齐既有路由并自带 OpenAPI；根路径提供本地 vendored Vue 3 零构建运行监控页；CLI `serve --impl stdlib|fastapi`（默认 stdlib 保持零依赖）。

验收：TestClient 测试「提交 → 读 SSE 流 → 断言完成事件」通过；fastapi 未安装时给出友好报错。

### Phase 6 — P2.3 子代理编排 `[状态: 已完成]`

范围：`mycoder/agent/orchestrator.py` — Planner（一次 LLM 调用产出 JSON 子任务列表）→ 各子任务由独立 AgentHarness 执行（独立 context/记忆作用域、共享工作区）→ 汇总裁决最终答案；无依赖子任务经 ThreadPoolExecutor 并行（`orchestrator.max_workers`）；子任务轨迹聚合进父任务工件 + `orchestration.json`；失败子任务降级标记 partial 不阻断整体；Planner/Executor 均可用 Mock 驱动，全离线可测。

验收：pytest 覆盖编排正确性、并行执行、失败降级；现有 harness 测试不回归。

### Phase 7 — 收尾 `[状态: 已完成]`

范围：全量测试 + ruff + mypy 通过、性能测试不回归；README / ARCHITECTURE / TESTING 同步新能力；pyproject optional-dependencies 分组（`api` / `vector` / `otel` / `dev`），核心保持零依赖；本文档标记各期完成状态并记录结论。

## 2. 提交约定

- 每个功能单元一个 conventional commit（见 CHANGELOG.md）；
- 不 push，提交保留在本地由作者审阅后推送；
- 所有新能力默认关闭或零依赖实现，保证既有测试与离线 CI 不受影响。

## 3. 结果记录（各 Phase 完成后回填）

> 说明：原计划文档在 Phase 1/2 实际落地后未及时回填，本次（2026-08-19）按既定架构方向
> 补齐了 Phase 3–7 的落地，并把全部状态校正为真实情况。所有新能力均默认关闭 / 零依赖，
> 既有 206 项测试与离线 CI 不受影响（全量 `pytest` 仍全绿）。

### Phase 1（P0 代码硬伤清理）—— 已完成
- CLI `cmd_run` 改用 `_make_backend()`，任务文件带 `script` 走 Mock、否则走 config 真实后端；
  新增 `--backend` 覆盖；删除恒 `None` 表达式与 `or True` 永真条件。
- `local_openai.py` URL 拼接收敛；`pyproject` 增加 ruff + mypy 配置并接入 GitHub Actions
  CI（3.10–3.12 矩阵：lint → typecheck → pytest + coverage）。
- 验收：206 项既有测试全绿；`ruff` / `mypy` 零告警。

### Phase 2（P1 真实模型链路强化）—— 已完成
- `LocalOpenAIBackend` 增加连接错误 / 429 / 5xx 自动重试 + 指数退避（尊重 `Retry-After`）；
  解析 API `usage` 做真实 token 计量（无 usage 回退启发式）；`complete_stream()` 流式输出。
- `cost.py` 按价格表核算每次运行成本，metrics / report.md / trajectory 全链路携带成本字段。
- `LLMSummarizer` 用模型压缩折叠轮次，失败自动回退确定性摘要器，默认保持 deterministic。
- 验收：新增单测覆盖重试 / 退避 / 流式 / usage 解析（monkeypatch 假 urlopen，全离线）。

### Phase 3（P2.4 可观测性）—— 已完成
- 新增 `observability/tracing.py`：零依赖 `Span` / `Tracer`，导出 OTLP 风格 `trace.json`
  （含完整 span 层级与耗时）；安装 `opentelemetry-api` 时自动桥接。
- `harness.py` 注入最小侵入的 `on_event` 事件总线，埋点覆盖 task_start / step_start /
  model_call / tool_call / checkpoint / task_end；`logging.format: text|json` 结构化日志
  （JSON 行可被 `json.loads` 解析）；`artifacts.py` 报告增加「耗时时间线与成本」小节。
- 验收：一次运行产出 `trace.json`；JSON 日志可解析。**已通过 `tests/test_observability.py`。**

### Phase 4（P2.1 向量记忆检索）—— 已完成
- 新增 `memory/vectors.py`：`EmbeddingProvider` 接口 + `HashingEmbedder`（零依赖、确定性、
  字符 n-gram 哈希，默认）+ `FastEmbedEmbedder`（可选依赖 bge-small）；`VectorIndex`（余弦 +
  增量 + 持久化）+ 纯 Python `BM25`；混合检索 `score = α·cosine + (1-α)·bm25`。
- `StructuredMemory` 增加 `substring / vector / hybrid` 三种检索模式（默认 substring 向后兼容，
  hybrid 在同义改写查询上召回显著更好）；评测新增 Layer 5 `retrieval`（`benchmarks/retrieval.json`）。
- 验收：同义查询 6 个，hybrid recall@3 = 100% 而 substring = 0%，hybrid 全面胜出；既有记忆测试
  不回归；CI 保持离线。**已通过 `tests/test_vectors.py` 与 `layer_retrieval` 评测。**

### Phase 5（P2.2 FastAPI + SSE）—— 已完成
- 新增 `api/event_bus.py`（`TaskEventBus`）+ `api/fastapi_server.py`：
  `POST /api/run` 立即返回 `task_id`、任务后台线程执行；`GET /api/run/{id}/events` SSE 实时
  推送语义事件并以 `done` 哨兵结束；`GET /api/run/{id}` 轮询状态；对标既有路由并提供 OpenAPI；
  根路径返回零构建 vanilla JS 实时追踪页。
- `api/__init__.py` 增加 `impl` 开关，`cli serve --impl stdlib|fastapi`（默认 stdlib 保持零依赖）；
  `api` 依赖组为可选（`fastapi>=0.115` / `uvicorn` / `httpx`）。
- 验收：TestClient 覆盖「提交 → 读 SSE 流 → 断言完成事件」；fastapi 未安装时 CLI 友好报错。
  **已通过 `tests/test_api.py`。**

### Phase 6（P2.3 子代理编排）—— 已完成
- 新增 `agent/orchestrator.py`：`Orchestrator` 由 `Planner`（默认确定性退化分解，可注入 LLM JSON
  分解）产出子任务；各子任务由**完全独立工作区 / 记忆 / 断点 / 工件根**的子 `AgentHarness`
  经 `ThreadPoolExecutor` 并行执行（互不污染）；汇总 `aggregate()`；单个子任务失败标记 `failed`
  不阻断整体（部分降级）；产出 `orchestration.json`；通过 `on_event` 发出
  `orchestration_start / subtask_end / orchestration_end`。
- `config` 增加 `agent.orchestrator.{enabled,max_workers}`（默认关闭）。
- 验收：pytest 覆盖编排正确性、并行执行、失败降级、事件发射；现有 harness 测试不回归。
  **已通过 `tests/test_orchestrator.py`。**

### Phase 7（收尾）—— 已完成
- 全量 `pytest` 仍全绿（共 **206 项 / 16 个测试文件**：原 162 既有 + 本轮新增 observability / vectors / api / orchestrator / cost / backendeval 共 44 项）；
- `pyproject` optional-dependencies 分组：`api` / `vector` / `otel` / `dev`，核心保持零依赖；
- README / ARCHITECTURE / TESTING / OUTLINE / FINAL_SUMMARY / LEARNING_GUIDE 同步新能力；CHANGELOG 追加本轮 conventional commits；
- 性能测试不回归；
- CLI 新增 `orchestrate` 子命令（复杂目标分解并行编排）。

