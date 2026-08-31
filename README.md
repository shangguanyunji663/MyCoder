# MyCoder — 本地 Coding Agent Harness

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

面向代码仓库长链路任务的本地 Agent 运行底座,解决多轮开发任务中:
- **上下文膨胀** → 上下文治理模块(预算裁剪)
- **重复读文件** → 结构化记忆系统(任务/文件/关联三层)
- **任务状态丢失** → Checkpoint/Resume + 工作区漂移识别
- **结果难复盘** → 三类运行工件(轨迹/检查点/指标报告) + 五层评测审计 + 链路追踪

## 核心特性

### 1. Agent Harness 主循环
- 统一封装模型调用、工具执行、会话状态、checkpoint、运行日志
- 空终答温和重问:模型返回"无工具调用且无内容"的空转回复时,自动注入提醒继续循环(`harness.empty_answer_nudges`,默认 1 次,0 = 关闭),checkpoint 序列化向后兼容
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
- 五层离线系统评测 + Layer 6 真实模型评测 + Layer 6b 裸基线对照(区分系统能力与模型能力):
  1. **Harness 回归**: 运行时稳定性(能完成、工件齐全、断言满足)
  2. **上下文治理**: 预算裁剪收益(治理 vs 不治理的 prompt 长度差)
  3. **记忆收益**: follow-up 重复读文件归零、正确率
  4. **恢复正确性**: checkpoint/resume + 漂移识别边界
  5. **检索召回**: exact/synonym/distractor/empty 四类查询的 recall@1/3/5 + MRR@5
  6. **真实任务 + LLM-as-judge**: Ollama 端到端代码任务、硬断言与独立模型评委
  6b. **裸模型基线对照**: 固定模型与任务集,只改"有没有 harness"——
      single_shot(单次调用,无工具循环)与 naive_loop(朴素 tool-calling 循环,
      无治理/记忆/断点/安全链)两条裸基线臂,复用 Layer 6 同一任务集与硬断言;
      若存在 Layer 6 报告则自动并排成三臂对照,直接度量 harness 的增量价值
- 26 个手写 benchmark 任务(回归17/上下文4/记忆4/恢复1) + 固定 seed 冻结基准 42 个任务 + 82 个检索查询(`retrieval.json` + `retrieval_extra.json`)
- 272 项 pytest 自动化测试(18 个测试文件,含参数化安全边界与 Layer 6/6b 离线用例)
- 对照实验: 固定任务、固定数据、仅改变系统开关
- 运行工件聚合: 可复现的评测报告(JSON + Markdown)

### 7. 可观测性(链路追踪)
- 零依赖 `Span` / `Tracer`(`observability/tracing.py`),导出 OTLP 风格 `trace.json`(含完整 span 层级与耗时)
- 安装 `opentelemetry-api` 时自动桥接真实 OTel Tracer(缺失则静默降级)
- Harness 通过最小侵入的 `on_event` 事件总线埋点:task_start / step_start / model_call / tool_call / step_end / checkpoint / task_end
- `logging.format: text | json` 结构化日志(JSON 行可被 `json.loads` 解析)
- 报告增加「耗时时间线与成本」小节

### 8. FastAPI + SSE API(可选依赖)
- `api/event_bus.py` + `api/fastapi_server.py`:`POST /api/run` 立即返回 `task_id`、任务后台线程执行;可选 `backend` 字段按请求选择执行后端(mock/local_openai,缺省跟随配置;携带 script 时锁定 Mock 回放)
- `POST /api/compare` 一键双跑对照:同一目标自动提交 mock/local_openai 两臂任务(共享 compare_group)
- `GET /api/run/{id}/events` SSE 实时推送语义事件并以 `done` 哨兵结束
- `GET /api/run/{id}` 轮询状态;`GET /api/runs` 返回任务列表(含 backend/arm/compare_group 元数据)
- 根路径返回 Vue 3 运行监控页(本地 vendored,零构建);FastAPI 下通过 SSE 实时展示事件
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
├── pyproject.toml               # 项目元数据与可选依赖组(api/vector/otel/dev)
├── requirements.txt             # 核心运行时依赖(PyYAML)
├── requirements-dev.txt         # 测试与开发工具(pytest/ruff/mypy)
├── requirements-api.txt         # FastAPI + uvicorn + httpx
├── requirements-vector.txt      # fastembed 真实嵌入器
├── requirements-project.txt     # 完整环境 = dev+api+vector+可编辑安装
├── environment.yml              # Conda 环境定义(重建项目内置 .conda 环境)
├── Dockerfile / docker-compose.yml / config/docker.yaml / .dockerignore
├── LICENSE                      # MIT
├── .conda/                      # 项目内置 Conda 环境文件夹(gitignored,env create 重建)
├── generate_test_file.py        # 生成巨型测试文件的脚本
├── config/
│   ├── default.yaml             # 默认配置文件
│   └── docker.yaml              # Docker 部署场景配置
├── kb_lora/                     # 企业知识库 LoRA 微调线(KB 数据集构建/SFT 导出/训练)
├── mycoder/                     # 核心代码包
│   ├── __init__.py
│   ├── __main__.py              # python -m mycoder 入口
│   ├── cli.py                   # 命令行接口(run/resume/serve/eval/benchmark/artifacts/doctor/orchestrate)
│   ├── config.py                # 配置加载与合并
│   ├── state.py                 # 会话状态模型
│   ├── util.py                  # 通用工具函数
│   ├── artifacts.py             # 三类运行工件
│   ├── tasks.py                 # 任务文件加载
│   ├── sft_collector.py         # SFT 微调样本采集(sft_log 开关)
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
│   │   ├── monitor_page.py      # Vue 3 运行监控页(零构建)
│   │   └── static/vue.global.prod.js # vendored Vue 3 运行时
│   ├── eval/                    # 评测审计
│   │   ├── benchmark.py         # benchmark 数据加载(固定 tasks.json + 冻结 generated)
│   │   ├── experiment.py        # 对照实验原语
│   │   ├── runner.py            # 五层离线评测运行器(Layer 1-5)
│   │   ├── judge.py             # LLM-as-judge 评委(JSON 解析/兜底)
│   │   ├── real.py              # Layer 6 真实模型端到端评测(Ollama)
│   │   └── raw_baseline.py      # Layer 6b 裸基线对照(single_shot/naive_loop)
│   └── cost.py                  # 按价目表核算每次运行成本
├── benchmarks/
│   ├── tasks.json               # 26 个 benchmark 任务(回归17/上下文4/记忆4/恢复1)
│   ├── tasks.generated.json     # 固定 seed 生成的冻结基准(42 个任务,提交入库保证可复现)
│   ├── retrieval.json           # 核心检索召回数据(38 条查询)
│   ├── retrieval_extra.json     # 扩展 4 领域 44 条查询(合计 82 条)
│   └── real_tasks.json          # Layer 6 真实编码任务(4 个)
├── tests/                       # pytest 测试套件(18 个文件,272 项)
│   ├── conftest.py
│   ├── test_models.py           # 15 个用例
│   ├── test_tools.py            # 21 个用例
│   ├── test_sandbox.py          # 15 个用例
│   ├── test_safety.py           # 70 个用例(参数化安全边界展开)
│   ├── test_context.py          # 19 个用例
│   ├── test_memory.py           # 19 个用例
│   ├── test_checkpoint.py       # 15 个用例
│   ├── test_harness.py          # 18 个用例(含空终答温和重问)
│   ├── test_backend.py          # 9 个用例(重试/退避/流式/usage)
│   ├── test_cost.py             # 5 个用例(成本核算)
│   ├── test_eval.py             # 18 个用例(五层评测+benchmark 完整性)
│   ├── test_observability.py    # 7 个用例(链路追踪/JSON 日志)
│   ├── test_vectors.py          # 11 个用例(嵌入/BM25/混合检索)
│   ├── test_api.py              # 7 个用例(FastAPI SSE/后端切换/双跑对照)
│   ├── test_orchestrator.py     # 4 个用例(并行/降级/事件)
│   ├── test_real_eval.py        # 4 个用例(LLM-as-judge 解析/真实任务断言)
│   ├── test_real_baseline.py    # 7 个用例(Layer 6b 裸基线两臂/工具白名单/三臂对照)
│   └── test_performance.py      # 8 个用例(性能测试)
├── examples/                    # 使用示例
│   ├── demo.py                  # 综合演示
│   ├── giant_test.py            # 巨型测试文件(~4669行,由 generate_test_file.py 生成)
│   ├── context_demo.py          # 上下文治理演示(15轮模拟)
│   ├── show_folded.py           # 折叠后消息展示工具
│   └── real_model_demo.py       # Layer 6 Ollama 真实模型端到端演示
└── docs/                        # 文档
    ├── ARCHITECTURE.md          # 架构设计
    ├── OUTLINE.md               # 项目大纲
    ├── TESTING.md               # 测试方法
    ├── LEARNING_GUIDE.md        # 学习指南(初学者从这里开始)
    ├── FINAL_SUMMARY.md         # 交付总结
    ├── IMPROVEMENT_PLAN.md      # 改进计划
    ├── EVAL_HARDENING.md        # 评测加固方案
    └── WEB_BACKEND_SWITCH.md    # Web 后端切换与一键双跑对照设计记录
```

## 快速开始

### 内置 Conda 环境(推荐,开箱即用)

项目自带独立 Conda 环境文件夹 `.conda/`(由 Anaconda 以路径方式管理,Python 3.11),已预装全部依赖(含可选增强)并完成 `pip install -e .` 可编辑安装,**无需再执行任何安装步骤**:

```bash
# 方式一:不激活直接用项目内解释器
.conda/python.exe -m pytest tests/          # Git Bash / 前缀写法
.conda\python.exe -m pytest tests/          # PowerShell / cmd

# 方式二:激活后使用 python 命令
conda activate D:\PythonProject\mycoder\.conda
python -m pytest tests/
```

> 注意:`.conda/` 已加入 .gitignore,不会进入版本控制。换机器或删除该文件夹后,用一条命令完整重建:
> `conda env create -p .conda -f environment.yml`

### 手动搭建环境(可选,适用于新机器)

若不想使用内置环境,也可以自行创建(Python 3.10+;核心运行时唯一强制依赖是 PyYAML):

```bash
# 一键重建与内置环境等价的完整环境
conda env create -p .conda -f environment.yml

# 或纯 pip 方式安装核心 + 按需的可选增强
python -m pip install -e .                        # 核心(零依赖,只需 PyYAML)
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
# 完整测试套件(单元 + 性能,272 项)
python -m pytest tests/

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

# Layer 6: Ollama 真实模型任务(qwen3.5:2b)
python examples/real_model_demo.py

# Layer 6b: 裸模型基线对照(需 model.backend=local_openai;
# 先跑 Layer 6 可在同目录获得 harness 参考臂,形成三臂对照)
python -m mycoder eval --suite real --output .mycoder/real
python -m mycoder eval --suite real_baseline --output .mycoder/real

# Layer 7: 可选真实嵌入器对照(首次运行会下载 bge-small)
python -m mycoder eval --suite embedder --output .mycoder/embedder
```

### Docker 快速开始

```bash
docker compose up -d
# 首次启动会由 ollama-init 拉取 qwen3.5:2b
curl http://127.0.0.1:8910/health
# 浏览器打开 Vue 3 运行监控页
# http://127.0.0.1:8910/
```

### 启动 localhost API

```bash
# 标准库实现(零依赖,默认)
python -m mycoder serve --host 127.0.0.1 --port 8910

# FastAPI + SSE 实现(需安装 api 依赖组,提供实时轨迹页/事件流/后端切换)
python -m mycoder serve --impl fastapi --config config/default.yaml --port 8910

# 测试 API
curl http://127.0.0.1:8910/health
```

监控页(Vue 3)支持按请求选择执行后端:

- `POST /api/run` 可选字段 `backend:"mock"|"local_openai"`(缺省跟随服务端配置;携带 script 时锁定 Mock 回放);
- `POST /api/compare` 一键双跑对照:同一目标自动提交 mock/local_openai 两臂任务(共享 compare_group),返回 `{compare_id, task_ids}`,页面「最新对比」并排展示两臂 状态/步骤/工具调用/Token/成本;
- 任务列表(`GET /api/runs`)透出每任务 `backend/arm/compare_group` 元数据。

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
- `model.backend`: 模型后端(mock 默认 / local_openai);网页「执行后端」与 `/api/run` 的 `backend` 字段可按请求覆盖
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
- `harness.max_steps` / `harness.empty_answer_nudges`: 单任务最大步数 / 空终答温和重问次数(默认 1,0 = 关闭)
- `api.host` / `api.port`: localhost API 地址

## 核心模块详解

详见:
- [学习指南(初学者推荐起点)](docs/LEARNING_GUIDE.md)
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

### 检索召回(Layer 5, n=82)
- 四个新领域(安全、前端、分布式、数据与 ML)扩展后共 82 条查询。
- 分类通过率: exact 23/23、synonym 29/29、distractor 11/11、empty 19/19。
- 平均 recall@1/3/5: substring = 28%/28%/28%, hybrid = 61%/63%/63%。
- MRR@5: substring = 0.44, hybrid = 0.98。
- 默认 HashingEmbedder 保持零依赖；`--suite embedder` 可对比 FastEmbed bge-small（首次运行需下载模型）。

### Layer 6 真实模型端到端结果(Ollama qwen3.5:2b)
- 实测运行 4 个编码任务：4/4 完成，4/4 硬断言通过；总耗时约 278 秒。
- 跨运行波动提示:上一轮实测 rt02 曾因模型返回空终答而失败(模型什么都没写就结束),
  本轮模型正常完成 file_edit —— 2b 模型方差大,单次运行胜负仅供参考;为此 harness
  新增空终答温和重问(见特性 1),把"交白卷"从静默完成变为可补救路径。
- LLM-as-judge 通过率 0/4(评委为 2b 小模型,本轮全部给 0 分,不可靠);结果如实保留在
  `.mycoder/real/real_report.json`,不把硬断言通过伪装成模型评委通过。
- 运行命令:`python -m mycoder eval --suite real --output .mycoder/real`(或
  `python examples/real_model_demo.py`);更大模型或更长评委超时配置可获得更稳定的 judge 结果。

### Layer 6b 裸模型基线对照(需 Ollama)
- 回答"harness 比不用它好多少":固定模型与 `benchmarks/real_tasks.json` 任务集,
  跑 single_shot(单次调用,无工具循环)与 naive_loop(朴素 tool-calling 循环,
  无上下文治理/记忆/断点/安全链)两条裸基线臂,并与 Layer 6 的 harness 结果并排三臂对照。
- 首次三臂实测(硬断言口径,同一 qwen3.5:2b):single_shot **1/4**(rt04 单次请求直接超时)、
  naive_loop **3/4**、harness **4/4** —— 工具循环是本任务集成功率的主要跃升来源,
  完整 harness 借助治理/记忆/容错机制拿下全部任务。prompt token 对比:
  single_shot 529 / naive_loop 14564 / harness 115919(多步循环与系统提示的固有成本)。
- 三臂共用同一套硬断言(`EvalRunner._check_expect`)与指标口径(token/成本/耗时),
  报告落盘 `real_baseline_report.json`,`comparison` 字段逐任务并排三臂通过情况。
- 运行:`python -m mycoder eval --suite real_baseline --output .mycoder/real`
  (real / real_baseline 不清空输出目录,两份报告可共存)。

### 安全边界
- 回归任务: 由离线 benchmark 持续验证(含正例、负例、边界)
- 参数校验拦截: 通过率 100%(回归样本)
- 路径逃逸拦截: 通过率 100%(回归样本)

## 许可证

MIT License

## 贡献

本项目为学习/研究用途,欢迎提出改进建议。