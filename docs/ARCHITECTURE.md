# MyCoder 架构设计

## 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      AgentHarness (主循环)                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │  Model   │  │  Tools   │  │ Context  │  │  Memory  │        │
│  │ Backend  │  │ Registry │  │ Manager  │  │  Store   │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘        │
│       │              │              │              │              │
│  ┌────┴──────────────┴──────────────┴──────────────┴─────┐      │
│  │                    SafetyGuard                         │      │
│  │  (参数校验 / 工作区隔离 / HITL / 去重 / 脱敏)         │      │
│  └───────────────────────────────────────────────────────┘      │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │ CheckpointStore  │  │ ArtifactManager  │                     │
│  │ (断点保存/恢复)   │  │ (工件导出)        │                     │
│  └──────────────────┘  └──────────────────┘                     │
│                                                                  │
│  ┌─────────────── 横切层(对 Harness 零侵入)─────────────┐      │
│  │ Observability(Tracer/trace.json + on_event 事件总线)  │      │
│  │ API(fastapi_server + event_bus 的 SSE 事件流)         │      │
│  │ Orchestrator(把目标拆为独立子 Harness 并行编排)       │      │
│  └────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

## 核心设计原则

### 1. 分层解耦
- **模型层**: ModelBackend 抽象,MockBackend(测试)与 LocalOpenAIBackend(部署)可互换
- **工具层**: Tool 基类 + Registry,7 类工具独立实现,安全边界由 SafetyGuard 统一处理
- **上下文层**: ContextManager 负责组装与裁剪,与业务逻辑正交
- **记忆层**: StructuredMemory 三层存储,与工具/上下文解耦
- **安全层**: SafetyGuard 独立于工具实现,提供校验/隔离/审批/去重/脱敏

### 2. 确定性优先
- MockBackend 脚本化:同一输入必得同一输出(评测可复现)
- Token 估算:中文按字、英文按 4 字符/token(稳定基准)
- 历史摘要:确定性压缩(不依赖 LLM),保证可复现
- 深拷贝裁剪: ContextManager.assemble() 不污染 raw_turns

### 3. 可观测性
- 三类运行工件:
  - trajectory.jsonl: 逐步追加的完整轨迹(崩溃可恢复)
  - checkpoint.json: 可恢复断点(任务/上下文/工作区指纹/指标)
  - metrics.json + report.md: 聚合指标与人类可读报告(含「耗时时间线与成本」小节)
- **链路追踪**(`observability/tracing.py`):
  - 零依赖 `Span` / `Tracer`,导出 OTLP 风格 `trace.json`(含完整 span 层级与耗时)
  - 安装 `opentelemetry-api` 时自动桥接真实 OTel Tracer(缺失则静默降级)
  - Harness 通过最小侵入的 `on_event` 事件总线埋点:task_start / step_start / model_call / tool_call / checkpoint / task_end
- **结构化日志**: `logging.format: text | json`,JSON 行可被 `json.loads` 解析
- 日志: 关键事件记录到 .mycoder/harness.log

### 4. 安全边界
- 参数校验: JSON Schema 验证(类型/必填/枚举/范围)
- 工作区隔离: Workspace.resolve() 拦截路径逃逸(`../`、绝对路径、符号链接)
- 高风险审批: shell_exec 需 HITL 审批(allow/deny/prompt 策略)
- 重复调用拦截: 读类工具缓存命中,写类工具标记跳过
- 敏感信息脱敏: API Key、密码、私钥等正则替换

## 数据流

```
TaskInput
    ↓
AgentHarness.run()
    ↓
┌─────────────────────────────────────────┐
│  Loop (max_steps):                       │
│   1. ContextManager.assemble()           │
│      - 组织: system + goal + files +     │
│              memory + history_summary +  │
│              recent turns                │
│      - 裁剪: fold_old_turns /            │
│              drop_stale_turns /          │
│              truncate_long_content       │
│   2. ModelBackend.complete()             │
│      - MockBackend: 脚本化响应           │
│      - LocalOpenAIBackend: HTTP POST     │
│   3. SafetyGuard.check()                 │
│      - validate_params()                 │
│      - workspace.resolve() (隔离)        │
│      - shell allowlist/denylist          │
│      - dedup cache                       │
│      - HITL approve                      │
│   4. Tool.execute()                      │
│      - 业务逻辑                          │
│   5. StructuredMemory.remember_file()    │
│      - 自动沉淀文件摘要                  │
│   6. CheckpointStore.save()              │
│      - 周期性/裁剪前/中断时              │
│   7. RunRecorder.record()                │
│      - 追加 trajectory.jsonl             │
└─────────────────────────────────────────┘
    ↓
RunResult + Artifacts
```

## 关键模块详解

### ModelBackend
- **MockBackend**: 脚本化响应,支持 state()/load_state() 以支持 resume
- **LocalOpenAIBackend**: urllib POST 到 127.0.0.1:8080/v1/chat/completions, arguments 保持 JSON 字符串格式

### ToolRegistry
- 7 类工具: file_read/write/edit/list, grep_search, shell_exec, memory_query
- 每个工具定义: name, description, parameters (JSON Schema), danger (safe/warn/hitl)
- 构建方式: `build_registry(memory=None)` 工厂函数

### Workspace (沙箱)
- resolve(path): 安全解析路径,拦截逃逸
- snapshot(): 返回 {相对路径: SHA256} 指纹(供漂移识别)
- read_text/write_text/list_files: 受控文件操作

### SafetyGuard
- validate_params(schema, params): 参数校验
- check(tool, params): 完整安全链(校验→隔离→shell策略→去重→HITL)
- record_executed(tool, params, output): 登记到去重缓存
- Redactor: 敏感信息脱敏

### ContextManager
- set_task(goal, files_hint, memory_block): 设置任务上下文
- append_turn(assistant, tool_msgs): 追加一轮对话
- assemble(): 组装并裁剪,返回送入模型的消息列表
  - 深拷贝裁剪,不污染 raw_turns
  - 硬限额强制:逐级截断最长消息,保证 100% 预算内
- 三层裁剪策略:
  1. **fold_old_turns**: 折叠超出 keep_last_turns 的旧轮次为滚动摘要
  2. **drop_stale_turns**: 仍超硬限时折叠到仅保留最近 1 轮原文
  3. **truncate_long_content**: 逐级截断最长消息直至达标

### StructuredMemory
- 三层存储:
  - tasks: {task_id: TaskRecord}
  - files: {path: FileRecord}
  - relations: {task_files, task_parent}
- remember_file(): 内容哈希一致则跳过(去重关键)
- followup_context(): 生成注入 follow-up 任务的记忆块
- search(query, kind="all", mode=None): 检索记忆,`mode` 可覆盖配置:
  - `substring`(默认,向后兼容): 子串/关键词匹配
  - `vector`: 稠密向量检索(`HashingEmbedder` 零依赖 / `FastEmbedEmbedder` 可选)
  - `hybrid`: `score = α·cosine + (1-α)·bm25`,结合 `VectorIndex` 与纯 Python `BM25`
- `memory/vectors.py`:
  - `EmbeddingProvider` 接口 + `HashingEmbedder`(字符 n-gram 哈希,确定性,默认)+ `FastEmbedEmbedder`(bge-small,可选依赖)
  - `VectorIndex`:余弦相似度 + 增量更新 + 持久化
  - `BM25`:纯 Python 实现(词/字级分词,兼容中英文)
  - `HybridRetriever`:稠密 + 稀疏混合打分

### CheckpointStore
- save(task_id, snapshot): 落盘断点(JSON)
- load(task_id): 加载断点
- snapshot 包含: 任务定义 + 上下文状态 + 工作区指纹 + 指标 + 后端状态

### WorkspaceDriftDetector
- compare(before, after): 对比工作区指纹
  - modified: 路径相同但哈希不同
  - added: 新增文件
  - deleted: 删除文件
- 精确比对,识别率 100%

### AgentHarness
- run(task): 主循环
- resume(task_id): 从断点恢复
- _execute_tools(): 安全链 + 执行 + 脱敏 + 记忆沉淀
- _checkpoint(): 周期性/裁剪前/中断时保存断点
- `build(config, backend, approver, on_event)`: 工厂装配;若传入 `on_event`(如 API 的 SSE EventBus),则默认 Tracer 与调用方回调**同时**收到语义事件

### Observability / Tracer
- `Tracer(artifacts_root, enabled)`: 作为 `on_event` 消费者重建 span 生命周期
- `handle(event)`: 按事件类型 task_start / step_start / model_call / tool_call / checkpoint / task_end 维护 span 树
- `export()`: 任务结束写出 `{artifacts_root}/{task_id}/trace.json`

### API 层(fastapi_server + event_bus)
- `TaskEventBus`: 进程内队列桥,按 `task_id` 路由语义事件;`done(task_id)` 推入 `__done__` 哨兵
- `create_app(config)`: 构建 FastAPI 应用,路由:
  - `POST /api/run` → 立即返回 `task_id`,后台线程执行 harness
  - `GET /api/run/{id}` → 轮询状态 + 指标摘要
  - `GET /api/run/{id}/events` → SSE 实时推送事件(`done` 哨兵结束)
  - `GET /api/artifacts/{id}/{name}` → 下载工件
  - `GET /api/runs` → 任务列表与事件计数
  - `GET /health` / `GET /`(本地 vendored Vue 3 运行监控页)
  - `/vue.global.prod.js` → 离线 Vue 运行时
- 监控页通过 EventSource 订阅 SSE;标准库实现不提供 SSE 时,前端退化为状态轮询。
- 标准库 `server.py` 保持零依赖实现;`serve --impl stdlib|fastapi` 切换

### Orchestrator(子代理编排)
- `Orchestrator(config, planner, backend_factory, max_workers, on_event)`
- `decompose(goal)`: Planner 产出子任务列表(默认确定性退化:整体作为一个子任务;可注入 LLM planner 做智能分解)
- `run(goal)`: 各子任务由**完全独立工作区/记忆/断点/工件根**的子 `AgentHarness` 经 `ThreadPoolExecutor` 并行执行
- 单个子任务失败标记 `failed` 不阻断整体(部分降级);汇总 `aggregate()`;产出 `orchestration.json`
- 通过 `on_event` 发出 orchestration_start / subtask_end / orchestration_end

## 巨型测试文件

`examples/giant_test.py` 是一个自动生成的约 4669 行测试文件,用于压力测试和上下文治理演示:

- **100 个函数**: func_0001 到 func_0100
- **排序算法**: bubble/quick/merge/heap/insertion/selection/counting/radix sort
- **设计模式**: Singleton/Factory/Builder/Observer/Strategy/Decorator/Adapter/Proxy/Command/StateMachine/Chain of Responsibility
- **数据结构**: ListNode/LinkedList/TreeNode/BinaryTree/TrieNode/Trie/Graph (含 BFS/DFS/最短路径/环检测)
- **8 个类**: 带数据存储/统计/__repr__ 的通用容器类

生成方式: `python generate_test_file.py`

## 扩展点

### 添加新工具
1. 继承 Tool 基类
2. 定义 name, description, parameters, danger
3. 实现 execute(ctx, **kwargs)
4. 注册到 ToolRegistry

### 添加新模型后端
1. 继承 ModelBackend
2. 实现 complete(messages, tools, temperature)
3. 可选: 实现 state()/load_state() 以支持 resume

### 添加新安全策略
1. 实现 ApprovalProvider 接口
2. 在 SafetyGuard 中注入

## 性能考量

- Token 估算: 启发式(中文按字、英文按 4 字符/token),无需模型分词器
- 历史摘要: 确定性压缩,不依赖 LLM
- 去重缓存: 内存级,避免重复读盘
- 深拷贝裁剪: 保证可复现,但增加内存开销(可接受,单任务 ~30 步)
- 巨型文件测试: `examples/giant_test.py` (~4669 行) 用于压力测试

## 测试策略

详见 [TESTING.md](TESTING.md)