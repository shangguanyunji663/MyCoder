# MyCoder 项目大纲

## 项目目标

面向代码仓库长链路任务,构建本地 Coding Agent Harness,解决多轮代码开发任务中的四大痛点:
1. **上下文膨胀** → 长上下文治理模块
2. **重复读文件** → 结构化记忆系统
3. **任务状态丢失** → Checkpoint/Resume 机制
4. **结果难复盘** → 运行工件 + 评测审计

## 技术栈

- **语言**: Python 3.10+
- **运行时依赖**: PyYAML (配置加载)
- **测试依赖**: pytest
- **运行环境**: 全部本地 127.0.0.1,无云端服务

## 模块划分

### 1. 核心基础设施
- `config.py`: 配置加载与合并(YAML/JSON,深合并)
- `state.py`: 会话状态模型(Message, ToolCall, Step, TaskInput, RunResult)
- `util.py`: 通用工具函数(哈希、原子写、时间戳、ID 生成、截断)
- `artifacts.py`: 三类运行工件(Metrics, RunRecorder, ArtifactManager)
- `tasks.py`: 任务文件加载(JSON/Markdown with frontmatter)

### 2. 模型后端 (models/)
- `base.py`: ModelBackend 抽象基类 + ModelResponse
- `mock.py`: MockBackend(确定性脚本后端,支持 state/load_state)
- `local_openai.py`: LocalOpenAIBackend(urllib POST 到 127.0.0.1:8080, arguments 保持 JSON 字符串)

### 3. 工具框架 (tools/)
- `base.py`: Tool 基类 + ToolResult + ToolContext + ToolRegistry
- `sandbox.py`: Workspace 沙箱(路径隔离、指纹快照)
- `file_tools.py`: 5 个文件工具(read/write/edit/list/grep)
- `shell_tool.py`: shell_exec(受控命令执行)
- `memory_tool.py`: memory_query(结构化记忆查询)

### 4. 上下文治理 (context/)
- `tokens.py`: token 估算(中文按字、英文按 4 字符/token)
- `summarizer.py`: 历史摘要器(DeterministicSummarizer, NoopSummarizer)
- `manager.py`: ContextManager(组装 + 裁剪,深拷贝保证可复现)
  - 三层裁剪策略: fold_old_turns → drop_stale_turns → truncate_long_content

### 5. 结构化记忆 (memory/)
- `store.py`: StructuredMemory(三层存储: tasks/files/relations,substring/vector/hybrid 检索)
- `retriever.py`: MemoryRetriever(检索接口)
- `vectors.py`: 向量检索(HashingEmbedder/VectorIndex/BM25/HybridRetriever)

### 6. 断点与恢复 (checkpoint/)
- `store.py`: CheckpointStore(断点保存/加载)
- `drift.py`: WorkspaceDriftDetector(工作区漂移识别)

### 7. 安全边界 (safety/)
- `guard.py`: SafetyGuard(参数校验/工作区隔离/HITL/去重)
- `redact.py`: Redactor(敏感信息脱敏)

### 8. 主循环 (agent/)
- `harness.py`: AgentHarness(主调度循环,run/resume,on_event 埋点)
- `orchestrator.py`: Orchestrator(子代理并行编排,独立子工作区)

### 9. 可观测性 (observability/)
- `tracing.py`: Span / Tracer(零依赖,OTLP 风格 trace.json + 可选 OTel 桥接)

### 10. localhost API (api/)
- `server.py`: HTTP API 服务(127.0.0.1:8910,标准库实现)
- `event_bus.py`: TaskEventBus(进程内事件队列)
- `fastapi_server.py`: FastAPI + SSE 实现(可选依赖)
- `monitor_page.py`: 本地 vendored Vue 3 实时运行监控页

### 11. 评测审计 (eval/)
- `benchmark.py`: benchmark 数据加载(26 个手写任务 + 42 个冻结生成任务 + 检索用例)
- `experiment.py`: 对照实验原语(compare_metrics, format_delta)
- `runner.py`: EvalRunner(五层离线评测运行器,Layer 1-5)
- `judge.py`: LLM-as-judge 评委(严格 JSON 结论/解析兜底)
- `real.py`: Layer 6 真实模型端到端评测(Ollama)
- `raw_baseline.py`: Layer 6b 裸基线对照(single_shot / naive_loop 两臂,可与 Layer 6 并排三臂对照)

### 12. 成本核算 (cost.py)
- 按 `model.pricing` 价目表核算每次运行的 token 成本

### 13. 命令行接口
- `cli.py`: argparse 子命令(run/resume/serve/orchestrate/eval/benchmark/artifacts/doctor)
- `__main__.py`: python -m mycoder 入口

## Benchmark 任务设计

26 个固定任务,按评测层打标签(另有固定 seed 冻结基准 tasks.generated.json,42 个任务,加载时合并):

### Regression (17 个)
- t01_create_file: 创建文件
- t02_read_file: 读取文件
- t03_edit_file: 编辑文件
- t04_list_grep: 列出 + 搜索
- (其余 13 个含正例/负例/边界展开,完整清单见 benchmarks/tasks.json 或 docs/TESTING.md)

### Context (4 个)
- t05_long_refactor: 通读大文件(长上下文)
- t06_long_search: 多轮检索(长上下文)
- t07_long_multifile: 多模块文档补齐(长上下文)
- t26c_budget_edge: 贴边预算(紧预算下仍 100% 预算内)

### Memory (4 个)
- t08_build_utils: 父任务(创建 utils.py)
- t09_followup_use_utils: follow-up(利用记忆,不重读)
- t10_build_config: 父任务(创建 config.py)
- t11_followup_use_config: follow-up(利用记忆,不重读)

### Resume (1 个)
- t12_resume_scenario: 分阶段构建(用于中断/恢复/漂移场景)

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
- 平均 recall@1/3/5: substring = 28%/28%/28%, hybrid = 61%/63%/63%
- MRR@5: substring = 0.44, hybrid = 0.98

### Layer 6 真实模型端到端(Ollama qwen3.5:2b)
- 4 个编码任务: 4/4 完成, 3/4 硬断言通过(LLM-as-judge 因评委超时 0/4,如实保留)

### Layer 6b 裸模型基线对照
- 固定模型与任务集,只改"有没有 harness";single_shot / naive_loop 两臂低通过率
  是预期测量结果,与 Layer 6 并排形成三臂对照;具体数字以实际运行为准
  (`eval --suite real_baseline`,需 Ollama)

### 安全边界
- 回归任务通过率: 100%
- 参数校验拦截: 100%
- 路径逃逸拦截: 100%

## 文件清单

### 核心代码 (~35 个 Python 文件)
- mycoder/__init__.py, __main__.py, cli.py, config.py, state.py, util.py, artifacts.py, tasks.py
- mycoder/models/: base.py, mock.py, local_openai.py, __init__.py
- mycoder/tools/: base.py, sandbox.py, file_tools.py, shell_tool.py, memory_tool.py, __init__.py
- mycoder/context/: tokens.py, summarizer.py, manager.py, __init__.py
- mycoder/memory/: store.py, retriever.py, __init__.py
- mycoder/checkpoint/: store.py, drift.py, __init__.py
- mycoder/safety/: guard.py, redact.py, __init__.py
- mycoder/agent/: harness.py, __init__.py
- mycoder/api/: server.py, __init__.py
- mycoder/eval/: benchmark.py, experiment.py, runner.py, judge.py, real.py, raw_baseline.py, __init__.py

### 测试 (18 个测试文件,268 个测试用例)
- tests/conftest.py
- tests/test_models.py (15 个用例)
- tests/test_tools.py (21 个用例)
- tests/test_sandbox.py (15 个用例)
- tests/test_safety.py (70 个用例)
- tests/test_context.py (19 个用例)
- tests/test_memory.py (19 个用例)
- tests/test_checkpoint.py (15 个用例)
- tests/test_harness.py (15 个用例)
- tests/test_backend.py (9 个用例 — 重试/退避/流式/usage)
- tests/test_cost.py (5 个用例 — 成本核算)
- tests/test_eval.py (18 个用例 — 五层评测)
- tests/test_observability.py (7 个用例 — 链路追踪/JSON 日志)
- tests/test_vectors.py (11 个用例 — 嵌入/BM25/混合检索)
- tests/test_api.py (7 个用例 — FastAPI SSE/后端切换/双跑对照)
- tests/test_orchestrator.py (4 个用例 — 并行/降级/事件)
- tests/test_real_eval.py (4 个用例 — LLM-as-judge/真实任务断言)
- tests/test_real_baseline.py (6 个用例 — Layer 6b 裸基线两臂/工具白名单/三臂对照)
- tests/test_performance.py (8 个用例 — 性能测试)

### 配置与文档
- config/default.yaml
- benchmarks/tasks.json
- CHANGELOG.md
- README.md
- docs/ARCHITECTURE.md
- docs/OUTLINE.md (本文件)
- docs/TESTING.md
- docs/FINAL_SUMMARY.md
- docs/LEARNING_GUIDE.md
- docs/EVAL_HARDENING.md
- docs/IMPROVEMENT_PLAN.md
- docs/WEB_BACKEND_SWITCH.md

### 示例与工具
- examples/demo.py (综合演示)
- examples/giant_test.py (巨型测试文件, ~4669 行)
- examples/context_demo.py (上下文治理演示, 15 轮模拟)
- examples/show_folded.py (折叠后消息展示)
- examples/real_model_demo.py (Layer 6 Ollama 真实模型端到端演示)
- generate_test_file.py (生成 giant_test.py 的脚本)

## 运行方式

```bash
# 使用项目内置 Conda 环境 .conda/(Python 3.11,已预装全部依赖,无需安装)
conda activate D:\PythonProject\mycoder\.conda
# 或不激活直接用: .conda/python.exe <...>

# 运行 demo
python examples/demo.py

# 运行上下文治理 Demo
python examples/context_demo.py

# 运行测试
python -m pytest tests/

# 运行性能测试
python -m pytest tests/test_performance.py -v

# 运行评测
python -m mycoder eval --suite all

# 运行 Layer 6b 裸基线对照(需 model.backend=local_openai,即本地 Ollama)
python -m mycoder eval --suite real_baseline --output .mycoder/real

# 启动 API(标准库,零依赖)
python -m mycoder serve

# 启动 API(FastAPI + SSE 实时追踪,需 api 依赖组)
python -m mycoder serve --impl fastapi

# 子代理编排
python -m mycoder orchestrate --goal "实现用户认证模块并补齐单元测试"
```

## 扩展建议

1. **添加新工具**: 继承 Tool 基类,注册到 ToolRegistry
2. **添加新模型后端**: 继承 ModelBackend,实现 complete()
3. **添加新安全策略**: 实现 ApprovalProvider 接口
4. **添加新评测层**: 在 EvalRunner 中添加 layer_xxx() 方法
5. **增强检索**: 接入 `FastEmbedEmbedder`(pip install 'mycoder-harness[vector]')提升语义召回

## 已知限制

1. Token 估算为启发式(非精确),但稳定可复现
2. MockBackend 脚本化,无法模拟真实 LLM 的不确定性
3. LocalOpenAIBackend 需要本地部署 OpenAI 兼容服务
4. 工作区沙箱基于路径解析,未处理并发访问
5. 默认 HashingEmbedder 为字符 n-gram 哈希,语义召回弱于真实嵌入器(可切换 fastembed)

## 未来工作

1. 支持更多模型后端(Anthropic, 本地 GGUF 等)
2. 支持并发工具执行
3. 支持可视化轨迹回放(已具备 trace.json + SSE 追踪页基础)
4. 支持更精细的 token 估算(集成真实 tokenizer)
5. Orchestrator 接入 LLM Planner 做智能子任务分解