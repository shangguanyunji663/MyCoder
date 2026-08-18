# MyCoder — 本地 Coding Agent Harness

面向代码仓库长链路任务的本地 Agent 运行底座,解决多轮开发任务中:
- **上下文膨胀** → 上下文治理模块(预算裁剪)
- **重复读文件** → 结构化记忆系统(任务/文件/关联三层)
- **任务状态丢失** → Checkpoint/Resume + 工作区漂移识别
- **结果难复盘** → 三类运行工件(轨迹/检查点/指标报告) + 五层评测审计 + 链路追踪

## 核心特性

### 1. Agent Harness 主循环
- 统一封装模型调用、工具执行、会话状态、checkpoint、运行日志
- 支持 2 类模型后端:
  - **MockBackend**: 确定性脚本后端(测试/评测,全离线)
  - **LocalOpenAIBackend**: 本地 OpenAI 兼容后端(127.0.0.1:8080,带重试退避/流式/真实 token 计量)
- 7 类工具: file_read/write/edit/list, grep_search, shell_exec, memory_query
- 3 类运行工件: trajectory.jsonl, checkpoint.json, metrics.json + report.md

### 2. 长上下文治理
- 按「任务目标 / 当前文件 / 历史摘要 / 工具结果」组织上下文
- 预算裁剪机制:软预算(触发折叠) + 硬限额(强制截断)
- 三层裁剪策略: fold_old_turns → drop_stale_turns → truncate_long_content
- 摘要器可切换: 确定性(默认,可复现) / LLM(模型压缩,失败自动回退)
- 评测指标:
  - 平均压缩率 ~80%
  - 预算内完成率 100%

### 3. 结构化记忆系统
- 三层分层存储:
  - **任务摘要**: 目标/状态/结论/关键决策/涉及文件
  - **文件摘要**: 哈希指纹/摘要/符号(函数类导入)/最近访问
  - **关联记忆**: 任务↔文件、任务↔父任务(follow-up)、文件↔文件(依赖)
- follow-up 任务自动注入父任务摘要,避免重读文件
- **混合检索**(`memory.retrieval.mode`):
  - `substring`(默认,向后兼容) / `vector`(稠密) / `hybrid`(稠密+BM25)
  - 零依赖 `HashingEmbedder`(字符 n-gram 哈希)为默认嵌入器;`FastEmbedEmbedder`(bge-small)为可选升级
- 评测指标: follow-up 阶段重复读文件 0 次,正确率 100%;同义改写查询下 hybrid recall@3 = 100% 而 substring = 0%

### 4. Checkpoint / Resume
- 断点保存: 任务定义 + 上下文状态 + 工作区指纹 + 指标
- 中断恢复: 从断点无损恢复,继续执行剩余步骤
- 工作区漂移识别: 文件路径→SHA256 精确比对,识别率 100%
- 评测指标: 10 个恢复场景,漂移识别准确率 100%

### 5. 工具调用与安全边界
- 参数校验: JSON Schema 验证(类型/必填/枚举/范围)
- 工作区隔离: 路径逃逸拦截(`../`、绝对路径、符号链接)
- 高风险审批(HITL): shell 执行需人工确认(allow/deny/prompt 策略)
- 重复调用拦截: 读类工具缓存命中,写类工具标记跳过
- 敏感信息脱敏: API Key、密码、私钥等正则替换
- 评测指标: 回归任务 100% 通过率,100% 预算内完成率

### 6. 评测审计闭环
- 五层评测(区分模型能力与系统能力):
  1. **Harness 回归**: 运行时稳定性(能完成、工件齐全、断言满足)
  2. **上下文治理**: 预算裁剪收益(治理 vs 不治理的 prompt 长度差)
  3. **记忆收益**: follow-up 重复读文件归零、正确率
  4. **恢复正确性**: checkpoint/resume + 漂移识别边界
  5. **检索召回**: 同义改写查询下 substring / vector / hybrid 的 recall@1/3/5 对照
- 12 个 benchmark 任务(回归/上下文/记忆/恢复) + 6 个检索用例(`benchmarks/retrieval.json`)
- 206 项 pytest 自动化测试(16 个测试文件)
- 对照实验: 固定任务、固定数据、仅改变系统开关
- 运行工件聚合: 可复现的评测报告(JSON + Markdown)

### 7. 可观测性(链路追踪)
- 零依赖 `Span` / `Tracer`(`observability/tracing.py`),导出 OTLP 风格 `trace.json`(含完整 span 层级与耗时)
- 安装 `opentelemetry-api` 时自动桥接真实 OTel Tracer(缺失则静默降级)
- Harness 通过最小侵入的 `on_event` 事件总线埋点:task_start / step_start / model_call / tool_call / checkpoint / task_end
- `logging.format: text | json` 结构化日志(JSON 行可被 `json.loads` 解析)
- 报告增加「耗时时间线与成本」小节

### 8. FastAPI + SSE API(可选依赖)
- `api/event_bus.py` + `api/fastapi_server.py`:`POST /api/run` 立即返回 `task_id`、任务后台线程执行
- `GET /api/run/{id}/events` SSE 实时推送语义事件并以 `done` 哨兵结束
- `GET /api/run/{id}` 轮询状态;根路径返回零构建 vanilla JS 实时追踪页
- CLI `serve --impl stdlib | fastapi`(默认 stdlib 保持零依赖);`api` 依赖组为可选

### 9. 子代理编排(可选增强,默认关闭)
- `agent/orchestrator.py`:把目标交给 Planner 分解为子任务,各子任务由**完全独立工作区/记忆/断点/工件根**的子 `AgentHarness` 经 `ThreadPoolExecutor` 并行执行
- 单个子任务失败标记 `failed` 不阻断整体(部分降级);汇总产出 `orchestration.json`
- 通过 `on_event` 发出 orchestration_start / subtask_end / orchestration_end
- CLI `orchestrate --goal "..."`;配置 `agent.orchestrator.{enabled, max_workers}`

### 10. 性能测试套件
- 8 大性能测试维度: 文件读写、列目录、Grep 搜索、记忆存储、上下文管理、断点I/O、工作区操作、工具注册
- 使用真实大文件(~4669 行,包含算法/数据结构/设计模式)进行压力测试
- 每项测试进行 3 轮取平均,输出 avg/min/max 耗时

## 项目结构

```
mycoder/
├── README.md                    # 本文件
├── pyproject.toml               # 项目元数据与依赖
├── requirements.txt             # pip 依赖清单
├── .gitignore                   # Git 忽略规则
├── generate_test_file.py        # 生成巨型测试文件的脚本
├── config/
│   └── default.yaml             # 默认配置文件
├── mycoder/                     # 核心代码包
│   ├── __init__.py
│   ├── __main__.py              # python -m mycoder 入口
│   ├── cli.py                   # 命令行接口
│   ├── config.py                # 配置加载与合并
│   ├── state.py                 # 会话状态模型
│   ├── util.py                  # 通用工具函数
│   ├── artifacts.py             # 三类运行工件
│   ├── tasks.py                 # 任务文件加载
│   ├── models/                  # 模型后端
│   │   ├── base.py              # 抽象基类
│   │   ├── mock.py              # MockBackend(脚本化)
│   │   └── local_openai.py      # LocalOpenAIBackend(127.0.0.1)
│   ├── tools/                   # 7 类工具
│   │   ├── base.py              # Tool 基类 + Registry
│   │   ├── sandbox.py           # Workspace 沙箱
│   │   ├── file_tools.py        # 5 个文件工具
│   │   ├── shell_tool.py        # shell_exec
│   │   └── memory_tool.py       # memory_query
│   ├── context/                 # 上下文治理
│   │   ├── tokens.py            # token 估算
│   │   ├── summarizer.py        # 历史摘要器(确定性 / LLM)
│   │   └── manager.py           # ContextManager
│   ├── memory/                  # 结构化记忆
│   │   ├── store.py             # StructuredMemory(substring/vector/hybrid)
│   │   ├── retriever.py         # MemoryRetriever
│   │   └── vectors.py           # 向量检索(HashingEmbedder/BM25/HybridRetriever)
│   ├── checkpoint/              # 断点与恢复
│   │   ├── store.py             # CheckpointStore
│   │   └── drift.py             # WorkspaceDriftDetector
│   ├── safety/                  # 安全边界
│   │   ├── guard.py             # SafetyGuard(校验/隔离/HITL/去重)
│   │   └── redact.py            # Redactor(脱敏)
│   ├── agent/                   # 主循环 + 编排
│   │   ├── harness.py           # AgentHarness(主循环,on_event 埋点)
│   │   └── orchestrator.py      # Orchestrator(子代理并行编排)
│   ├── observability/           # 可观测性(链路追踪)
│   │   └── tracing.py           # Span / Tracer(零依赖,OTLP 风格)
│   ├── api/                     # localhost HTTP API
│   │   ├── server.py            # 标准库实现(零依赖,127.0.0.1:8910)
│   │   ├── event_bus.py         # TaskEventBus(进程内事件队列)
│   │   ├── fastapi_server.py    # FastAPI + SSE 实现(可选依赖)
│   │   └── trace_page.py        # vanilla JS 实时追踪页
│   ├── eval/                    # 评测审计
│   │   ├── benchmark.py         # benchmark 数据加载
│   │   ├── experiment.py        # 对照实验原语
│   │   └── runner.py            # 五层评测运行器
│   └── cost.py                  # 按价目表核算每次运行成本
├── benchmarks/
│   ├── tasks.json               # 12 个 benchmark 任务
│   └── retrieval.json           # 6 个检索召回用例(同义改写)
├── tests/                       # pytest 测试套件(16 个文件,206 项)
│   ├── conftest.py
│   ├── test_models.py           # 14 个用例
│   ├── test_tools.py            # 21 个用例
│   ├── test_sandbox.py          # 15 个用例
│   ├── test_safety.py           # 27 个用例
│   ├── test_context.py          # 19 个用例
│   ├── test_memory.py           # 19 个用例
│   ├── test_checkpoint.py       # 15 个用例
│   ├── test_harness.py          # 15 个用例
│   ├── test_backend.py          # 9 个用例(重试/退避/流式/usage)
│   ├── test_cost.py             # 5 个用例(成本核算)
│   ├── test_eval.py             # 14 个用例(五层评测)
│   ├── test_observability.py    # 7 个用例(链路追踪/JSON 日志)
│   ├── test_vectors.py          # 11 个用例(嵌入/BM25/混合检索)
│   ├── test_api.py              # 3 个用例(FastAPI SSE)
│   ├── test_orchestrator.py     # 4 个用例(并行/降级/事件)
│   └── test_performance.py      # 8 个用例(性能测试)
├── examples/                    # 使用示例
│   ├── demo.py                  # 综合演示
│   ├── giant_test.py            # 巨型测试文件(~4669行)
│   ├── context_demo.py          # 上下文治理演示(15轮模拟)
│   └── show_folded.py           # 折叠后消息展示工具
└── docs/                        # 文档
    ├── ARCHITECTURE.md
    ├── OUTLINE.md
    ├── TESTING.md
    ├── FINAL_SUMMARY.md
    ├── LEARNING_GUIDE.md
    └── IMPROVEMENT_PLAN.md
```

## 快速开始

### 环境要求
- Python 3.10+
- PyYAML (核心运行时依赖,**唯一强制依赖**)
- pytest (测试依赖,`pip install 'mycoder-harness[test]'`)

### 安装依赖

```bash
# 核心(零依赖,只需 PyYAML)
python -m pip install -e .

# 可选增强(按需安装)
python -m pip install 'mycoder-harness[api]'      # FastAPI + SSE API
python -m pip install 'mycoder-harness[vector]'   # 真实语义向量检索(fastembed)
python -m pip install 'mycoder-harness[otel]'     # OpenTelemetry 桥接
python -m pip install 'mycoder-harness[dev]'      # ruff + mypy 等开发工具
```

### 运行 Demo

```bash
# 综合 Demo
python examples/demo.py

# 上下文治理 Demo (模拟 15 轮上下文膨胀)
python examples/context_demo.py

# 查看折叠后消息
python examples/show_folded.py
```

### 运行测试

```bash
# 完整测试套件(单元 + 性能)
python -m pytest tests/ -v

# 仅运行性能测试
python -m pytest tests/test_performance.py -v

# 仅运行特定层测试
python -m pytest tests/test_eval.py::TestEvalLayers -v
```

### 运行评测

```bash
# 运行五层评测
python -m mycoder eval --suite all --output .mycoder/eval

# 仅运行 Layer 5 检索召回评测
python -m mycoder eval --suite retrieval --output .mycoder/eval

# 查看评测报告
cat .mycoder/eval/report.md
```

### 启动 localhost API

```bash
# 标准库实现(零依赖,默认)
python -m mycoder serve --host 127.0.0.1 --port 8910

# FastAPI + SSE 实现(需安装 api 依赖组,提供实时轨迹页与事件流)
python -m mycoder serve --impl fastapi --port 8910

# 测试 API
curl http://127.0.0.1:8910/health
```

### 子代理编排

```bash
# 把复杂目标分解为子任务并行执行(默认确定性退化分解:整体作为一个子任务)
python -m mycoder orchestrate --goal "实现用户认证模块,并补齐单元测试"

# 指定并行度
python -m mycoder orchestrate --goal "..." --max-workers 4
```

## 配置说明

配置文件: `config/default.yaml`

关键配置项:
- `workspace.root`: 工作区根目录(工具沙箱边界)
- `model.backend`: 模型后端(mock / local_openai)
- `model.local_openai.*`: base_url / 重试次数 / 退避 / 流式开关
- `model.pricing`: 成本核算价目表(每 1k token 美元,按 model 名匹配)
- `context.budget_tokens`: 上下文软预算(token 数)
- `context.hard_limit_tokens`: 上下文硬上限
- `context.keep_last_turns`: 保留最近 N 轮原文
- `context.summarizer`: 历史摘要器(deterministic / llm)
- `memory.enabled`: 是否启用结构化记忆
- `memory.retrieval.mode`: 检索模式(substring / vector / hybrid)
- `memory.retrieval.alpha`: hybrid 中向量权重(0~1)
- `memory.retrieval.embedder`: 嵌入器(hashing / fastembed)
- `checkpoint.enabled`: 是否启用断点保存
- `safety.hitl_policy`: 高风险审批策略(prompt / allow / deny)
- `logging.format`: 日志格式(text / json 结构化)
- `observability.enabled`: 是否导出 trace.json 链路追踪
- `agent.orchestrator.enabled`: 子代理编排开关(默认关闭)
- `agent.orchestrator.max_workers`: 并行子任务数(默认 4)
- `api.host` / `api.port`: localhost API 地址

## 核心模块详解

详见:
- [架构设计](docs/ARCHITECTURE.md)
- [项目大纲](docs/OUTLINE.md)
- [测试方法](docs/TESTING.md)

## 评测指标

### 上下文治理
- 平均压缩率: ~80%
- 最高压缩率: ~81%
- 预算内完成率: 100%

### 结构化记忆
- follow-up 重复读文件: 2 → 0 次
- 任务正确率: 100%

### 任务恢复
- 漂移识别准确率: 100%(5/5 漂移检出, 5/5 无漂移正确)
- 恢复后完成率: 100%

### 检索召回(Layer 5)
- 同义改写查询 6 例: hybrid recall@3 = 100%,substring = 0%,hybrid 全面胜出
- vector / hybrid 路径默认零依赖(HashingEmbedder),接入 fastembed 后语义召回进一步增强

### 安全边界
- 回归任务通过率: 100%
- 参数校验拦截: 100%
- 路径逃逸拦截: 100%

## 许可证

MIT License

## 贡献

本项目为学习/研究用途,欢迎提出改进建议。