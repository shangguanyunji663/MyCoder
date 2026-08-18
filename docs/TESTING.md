# MyCoder 测试方法

## 测试架构

MyCoder 采用**五层评测体系** + **性能测试套件**，刻意区分"模型能力"与"系统能力"：

```
Layer 1: Harness 回归测试
  ─── 验证运行稳定性(能完成、工件齐全、断言满足)

Layer 2: 上下文治理评测  ─── 验证预算裁剪收益(治理 vs 不治理的 prompt 长度差)

Layer 3: 记忆收益评测
  ─── 验证 follow-up 阶段重复读文件归零、正确率

Layer 4: 恢复正确性评测  ─── 验证 checkpoint/resume + 工作区漂移识别边界
Layer 5: 检索召回评测   ─── 验证同义改写查询下 substring / vector / hybrid 的 recall@1/3/5

性能测试:
  ─── 使用巨型文件(~4669行)对 8 个维度进行压力测试
```

## 测试数据

### Benchmark 任务 (benchmarks/tasks.json)
12 个固定任务，按评测层打标签：
- **Regression (4)**: t01_create_file, t02_read_file, t03_edit_file, t04_list_grep
- **Context (3)**: t05_long_refactor, t06_long_search, t07_long_multifile
- **Memory (4)**: t08_build_utils, t09_followup_use_utils, t10_build_config, t11_followup_use_config
- **Resume (1)**: t12_resume_scenario

每个任务包含：
- `task_id`: 唯一标识
- `layer`: 所属评测层
- `goal`: 任务目标
- `script`: MockBackend 脚本(确定性轨迹)
- `expect`: 断言(files_created, file_contains, final_contains)
- `setup_files`: 预置文件
- `generate_files`: 生成大文件(用于 context 层)
- `follow_up_of`: 父任务 ID(用于 memory 层)
- `control_script`: 对照组脚本(用于 memory 层)

### 巨型测试文件 (examples/giant_test.py)
用于性能测试和上下文治理演示的自动生成文件：
- **行数**: ~4669 行
- **内容**: 100 个函数 + 排序算法(8类) + 设计模式(10类) + 数据结构(6类) + 8 个通用容器类
- **生成方式**: `python generate_test_file.py`

## 运行测试

### 使用 ML2 环境(推荐)

```bash
# 激活 ML2 环境(已预装 pytest)
# 使用你的 Python 环境(需 pip install -e . 及 pytest)

# 运行完整测试套件(206 项)
python -m pytest tests/ -v

# 运行特定测试文件
python -m pytest tests/test_models.py -v

# 运行特定测试类
python -m pytest tests/test_eval.py::TestEvalLayers -v

# 运行特定测试方法
python -m pytest tests/test_eval.py::TestEvalLayers::test_regression_layer -v

# 运行性能测试
python -m pytest tests/test_performance.py -v
```

## 五层评测详解

### Layer 1: Harness 回归测试

**目标**: 验证运行时稳定性
**测试内容**:
- 任务能完成(status == "completed")
- 三类工件齐全(trajectory.jsonl, metrics.json, report.md)
- 断言满足(files_created, file_contains, final_contains)

**测试用例**:
- `test_completes`: 任务完成
- `test_produces_three_artifacts`: 工件齐全
- `test_metrics_recorded`: 指标记录
- `test_max_steps`: 最大步数终止
- `test_unknown_tool_intercepted`: 未知工具拦截
- `test_invalid_params_intercepted`: 非法参数拦截

**验证方法**:
```bash
python -m pytest tests/test_harness.py::TestRunFlow -v
```

### Layer 2: 上下文治理评测
**目标**: 验证预算裁剪收益

**测试内容**:
- 治理后 prompt 长度 < 不治理 prompt 长度
- 平均压缩率 > 0
- 预算内完成率 == 100%

**测试用例**:
- `test_fold_old_turns`: 折叠旧轮次
- `test_hard_limit_enforced`: 硬限额强制
- `test_ratio_magnitude`: 压缩率幅度
- `test_does_not_mutate_history`: 不污染原始历史
- `test_deterministic_replay`: 确定性重放

**验证方法**:
```bash
python -m pytest tests/test_context.py -v
```

**评测指标**:
- 平均压缩率: ~80%
- 最高压缩率: ~81%
- 预算内完成率: 100%

### Layer 3: 记忆收益评测

**目标**: 验证 follow-up 阶段重复读文件归零
**测试内容**:
- 父任务创建文件，沉淀摘要
- follow-up 任务使用 memory_query(不重读文件)
- 对照组使用 file_read(重读文件)
- 比较: 重读次数、正确率

**测试用例**:
- `test_remember_file_symbols`: 文件摘要提取
- `test_same_hash_skip`: 内容哈希一致跳过
- `test_followup_injects_memory`: follow-up 注入记忆
- `test_includes_parent_files`: 包含父任务文件

**验证方法**:
```bash
python -m pytest tests/test_memory.py -v
```

**评测指标**:
- follow-up 重复读文件: 2 → 0 次
- 任务正确率: 100%

### Layer 4: 恢复正确性评测
**目标**: 验证 checkpoint/resume + 工作区漂移识别
**测试内容**:
- 中断任务(stop_after_steps)
- 可选外部修改工作区(模拟漂移)
- 恢复任务(resume)
- 验证: 漂移检测、续跑完成、文件存在

**测试用例**:
- `test_interrupt_resume_continues`: 中断恢复续跑
- `test_resume_detects_drift`: 恢复检测漂移
- `test_resume_missing_checkpoint`: 缺失断点

**验证方法**:
```bash
python -m pytest tests/test_harness.py::TestResumeFlow -v
```

**评测指标**:
- 漂移识别准确率: 100%(5/5 漂移检出，5/5 无漂移正确)
- 恢复后完成率: 100%

## 性能测试 (Layer 5)

### 概述

`tests/test_performance.py` 使用 `examples/giant_test.py` (~4669 行) 对 MyCoder 各组件进行压力测试。每项测试进行 3 轮取平均，输出 avg/min/max 耗时。

### 巨型测试文件

`examples/giant_test.py` 由 `generate_test_file.py` 自动生成，包含：
- **100 个函数**: func_0001 到 func_0100，每个执行模乘计算
- **排序算法 (8 种)**: bubble/quick/merge/heap/insertion/selection/counting/radix sort
- **设计模式 (10 种)**: Singleton/Factory/Builder/Observer/Strategy/Decorator/Adapter/Proxy/Command/StateMachine
- **数据结构 (6 种)**: ListNode/LinkedList/TreeNode/BinaryTree/TrieNode/Trie/Graph (含 BFS/DFS/Dijkstra/环检测)
- **8 个通用容器类**: 带数据存储/历史记录/统计/__repr__

```bash
# 生成巨型测试文件
python generate_test_file.py

# 生成后约 4669 行, ~200KB
```

### 性能测试模块详解

| 测试模块 | 测试函数 | 说明 | 测量指标 |
|----------|----------|------|----------|
| [1] 文件读取 | `test_file_read_performance()` | 读取完整巨型文件、部分读取(100行)、10次重复读取(50行) | 大文件 I/O 吞吐 |
| [2] 文件列表 | `test_file_list_performance()` | 列出 examples 目录、列出项目根目录 | 目录遍历效率 |
| [3] Grep 搜索 | `test_grep_performance()` | 搜索 class 定义、func_ 函数、排序算法、设计模式、数据结构 | 正则匹配 + 大文件搜索 |
| [4] 记忆存储 | `test_memory_performance()` | 存储巨型文件记录、搜索 func/class/sort 关键词 | 摘要生成 + 检索速度 |
| [5] 上下文管理 | `test_context_performance()` | 巨型内容 token 估算、5 个大消息估算、大上下文组装 | token 估算 + 裁剪效率 |
| [6] 断点 I/O | `test_checkpoint_performance()` | 保存大型状态(含 10000 字符消息)、加载大型断点 | JSON 序列化/反序列化 |
| [7] 工作区操作 | `test_workspace_operations()` | 写入大文件、读取大文件、100 个小文件写入、列出 100+ 文件 | 沙箱文件操作效率 |
| [8] 工具注册 | `test_tool_registry_performance()` | 100 次构建 registry、获取全部 7 个工具、获取工具 schema | 注册表构建 + 查询 |

### 运行性能测试

```bash
# 运行性能测试(需要先先生成 giant_test.py)
python -m pytest tests/test_performance.py -v -s

# 运行性能测试(不显示 print 输出)
python -m pytest tests/test_performance.py -v
```

### 性能测试预期输出

```
[1] File Read Performance
  [read_giant_file] avg=0.0xxx s
  [read_partial_file] avg=0.0xxx s
  [10x_partial_reads] avg=0.0xxx s

[2] File List Performance
  [list_examples_dir] avg=0.0xxx s
  [list_project_root] avg=0.0xxx s

[3] Grep Search Performance
  [grep_class_def] avg=0.0xxx s
  [grep_func_def] avg=0.0xxx s
  [grep_sort_algo] avg=0.0xxx s
  [grep_design_pattern] avg=0.0xxx s
  [grep_data_structure] avg=0.0xxx s

[4] Memory Store Performance
  [store_giant_file_record] avg=0.0xxx s
  [memory_search_func] avg=0.0xxx s
  [memory_search_sort] avg=0.0xxx s

[5] Context Management Performance
  [estimate_giant_tokens] avg=0.0xxx s
  [estimate_5x_large_messages] avg=0.0xxx s
  [assemble_large_context] avg=0.0xxx s

[6] Checkpoint Performance
  [save_large_checkpoint] avg=0.0xxx s
  [load_large_checkpoint] avg=0.0xxx s

[7] Workspace Operations Performance
  [write_large_file] avg=0.0xxx s
  [read_large_file] avg=0.0xxx s
  [write_100_small_files] avg=0.0xxx s
  [list_100_plus_files] avg=0.0xxx s

[8] Tool Registry Performance
  [build_registry_100x] avg=0.0xxx s
  [get_all_7_tools] avg=0.0xxx s
  [get_all_tool_schemas] avg=0.0xxx s

============================================================
PERFORMANCE SUMMARY
============================================================
Test                                Avg(s)     Min(s)     Max(s)
-----------------------------------------------------------------
...
Total tests: 24
Total time: x.xx s
============================================================
```

## 安全边界测试

### 参数校验
```bash
python -m pytest tests/test_safety.py::TestParamValidation -v
```

### 工作区隔离
```bash
python -m pytest tests/test_sandbox.py::TestResolve -v
```

### HITL 审批
```bash
python -m pytest tests/test_safety.py::TestHitl -v
```

### 去重拦截
```bash
python -m pytest tests/test_safety.py::TestDedup -v
```

### 敏感信息脱敏
```bash
python -m pytest tests/test_safety.py::TestRedact -v
```

## 上下文治理演示
`examples/context_demo.py` 使用 `giant_test.py` 模拟 15 轮上下文膨胀：

```bash
# 运行上下文治理演示
python examples/context_demo.py
```

**预期输出**:
```
Giant file: 4669 lines, ~200000 chars, ~50000 tokens

Simulating 15 turns (each reads ~300 lines of giant file)

  Turn  1 | Raw:  xxxx tokens -> After:  xxxx tokens | Strategies: []
  Turn  3 | Raw:  xxxx tokens -> After:  xxxx tokens | Ratio:  xx%
  Turn  6 | Raw:  xxxx tokens -> After:  xxxx tokens | Strategies: ['fold_old_turns']
  Turn  9 | Raw:  xxxx tokens -> After:  xxxx tokens | Strategies: ['fold_old_turns', 'drop_stale_turns']
  Turn 12 | Raw:  xxxx tokens -> After:  xxxx tokens | Strategies: ['fold_old_turns', 'drop_stale_turns', 'truncate_long_content']
  Turn 15 | Raw:  xxxx tokens -> After:  xxxx tokens | Ratio: ~80%

Final Summary
  Total turns:        15
  Without governance:  ~xxxxx tokens (exceeds hard limit by xx)
  With governance:     ~xxxx tokens (within budget!)
  Compression ratio:   ~80%
  Strategies used:     ['fold_old_turns', 'drop_stale_turns', 'truncate_long_content']
```

## 评测报告

运行完整评测后生成报告：

```bash
python -m mycoder eval --suite all --output .mycoder/eval
# 单独运行某一层: regression | context | memory | resume | retrieval
python -m mycoder eval --suite retrieval
```

报告文件：
- `.mycoder/eval/report.json`: 结构化报告(JSON)
- `.mycoder/eval/report.md`: 人类可读报告(Markdown)

## 测试覆盖率
### 模块覆盖
- ✅ models: MockBackend, LocalOpenAIBackend(重试/退避/流式/usage), 工厂装配
- ✅ tools: 7 类工具功能测试
- ✅ sandbox: 路径隔离、指纹快照
- ✅ safety: 参数校验、隔离、HITL、去重、脱敏
- ✅ context: token 估算、折叠、硬限额、拷贝安全、摘要器切换
- ✅ memory: 三层存储、去重、检索(substring/vector/hybrid)、持久化
- ✅ vectors: HashingEmbedder/BM25/HybridRetriever 检索与打分
- ✅ checkpoint: 断点保存/加载、漂移识别
- ✅ harness: 主循环、安全拦截、去重、记忆、恢复
- ✅ observability: Tracer/trace.json、on_event 埋点、JSON 结构化日志
- ✅ api: FastAPI + SSE 事件流、EventBus、实时追踪页
- ✅ orchestrator: 并行编排、失败降级、事件发射
- ✅ cost: 按价目表核算运行成本
- ✅ eval: 五层评测、benchmark 数据完整性
- ✅ performance: 8 维度性能压力测试

### 测试用例统计

| 测试文件 | 用例数 | 测试内容 |
|----------|--------|----------|
| test_models.py | 14 | Mock 脚本 progression/state恢复, LocalOpenAI parse, 工具schema格式 |
| test_tools.py | 21 | 每种工具的 execute + error case + meta 字段 |
| test_sandbox.py | 15 | PathEscapeError 拦截, rel兼容, snapshot指纹, list过滤隐藏 |
| test_safety.py | 27 | validate_params(11组合)/escape(4场景)/shell(4场景)/HITL(3策略)/dedup(3)/redact(5) |
| test_context.py | 19 | CJK/ASCII token估算, fold/fold_to_1/enforce_budget, 深拷贝安全 deterministic replay, 摘要器 |
| test_memory.py | 19 | remember_task/update/parent_link, file_symbols/same_hash_skip, relation/link, search(3kind), followup_context, save_load_roundtrip, stats, disabled_no_save |
| test_checkpoint.py | 15 | save_load_unicode/overwrite, exists/list_all, drift_compare(modified/added/deleted/empty), summary_text |
| test_harness.py | 15 | run_flow(complete/artifacts/metrics/max_steps/unknown_tool/invalid_params), safety_intercept, dedup, resume_flow |
| test_backend.py | 9 | 重试/指数退避(429/5xx/Retry-After), usage 解析, 流式 complete_stream |
| test_cost.py | 5 | 按价目表核算 token 成本, 缺价目不计费 |
| test_eval.py | 14 | benchmark_data, eval_layers(回归/上下文/记忆/恢复/检索), report_writing |
| test_observability.py | 7 | Tracer span 层级/耗时, on_event 重建, JSON 日志可解析, trace.json 导出 |
| test_vectors.py | 11 | HashingEmbedder 确定性/归一化/余弦, BM25 排序, HybridRetriever α 加权, FastEmbed 可选 |
| test_api.py | 3 | health/追踪页, 提交→SSE→完成事件, 未知任务 404 |
| test_orchestrator.py | 4 | 并行编排, 失败降级(partial), 默认 planner 单子任务, 事件发射 |
| test_performance.py | 8 | 文件读取/列表/Grep/记忆/上下文/断点/工作区/工具注册 性能测试 |

**总计**: 206 个测试用例，16 个测试文件

## 确定性保证
所有测试使用：
- **MockBackend**: 脚本化响应(同一输入必得同一输出)
- **临时工作区**: pytest tmp_path fixture，互不污染
- **固定配置**: Config() 默认配置，无随机性
保证：
- 同一环境、同一代码，测试结果 100% 可复现
- 不同环境(Windows/Linux/macOS)，测试结果一致

## 故障排查

### pytest 找不到测试
```bash
# 确保在 mycoder 项目根目录
cd "D:\DeepSeek Harness\mycoder"

# 确保使用 ML2 环境
python -m pytest tests/ --collect-only
```

### 导入错误
```bash
# 确保 conftest.py 存在
ls tests/conftest.py

# 确保项目根目录在 sys.path
python -c "import sys; sys.path.insert(0, '.'); import mycoder"
```

### 性能测试失败
```bash
# 确保 giant_test.py 已生成
python generate_test_file.py

# 查看详细输出
python -m pytest tests/test_performance.py -v -s
```

### 评测失败
```bash
# 查看详细输出
python -m pytest tests/test_eval.py -v -s

# 查看评测报告
cat .mycoder/eval/report.md
```

## 持续集成

建议配置 CI(如 GitHub Actions)：

```yaml
name: Test MyCoder
on: [push, pull_request]
jobs:
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest
      - name: Generate test file
        run: python generate_test_file.py
      - name: Run tests
        run: pytest tests/ -v
      - name: Run eval
        run: python -m mycoder eval --suite all
```
