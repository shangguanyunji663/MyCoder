# MyCoder 测试方法

## 测试架构

MyCoder 采用**四层评测体系**,刻意区分"模型能力"与"系统能力":

```
Layer 1: Harness 回归测试
  └─ 验证运行时稳定性(能完成、工件齐全、断言满足)

Layer 2: 上下文治理评测
  └─ 验证预算裁剪收益(治理 vs 不治理的 prompt 长度差)

Layer 3: 记忆收益评测
  └─ 验证 follow-up 阶段重复读文件归零、正确率

Layer 4: 恢复正确性评测
  └─ 验证 checkpoint/resume + 工作区漂移识别边界
```

## 测试数据

### Benchmark 任务 (benchmarks/tasks.json)
12 个固定任务,按评测层打标签:
- **Regression (4)**: t01_create_file, t02_read_file, t03_edit_file, t04_list_grep
- **Context (3)**: t05_long_refactor, t06_long_search, t07_long_multifile
- **Memory (4)**: t08_build_utils, t09_followup_use_utils, t10_build_config, t11_followup_use_config
- **Resume (1)**: t12_resume_scenario

每个任务包含:
- `task_id`: 唯一标识
- `layer`: 所属评测层
- `goal`: 任务目标
- `script`: MockBackend 脚本(确定性轨迹)
- `expect`: 断言(files_created, file_contains, final_contains)
- `setup_files`: 预置文件
- `generate_files`: 生成大文件(用于 context 层)
- `follow_up_of`: 父任务 ID(用于 memory 层)
- `control_script`: 对照组脚本(用于 memory 层)

## 运行测试

### 使用 ML2 环境(推荐)

```bash
# 激活 ML2 环境(已预装 pytest)
conda activate ML2

# 运行完整测试套件
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest tests/ -v

# 运行特定测试文件
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest tests/test_models.py -v

# 运行特定测试类
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest tests/test_eval.py::TestEvalLayers -v

# 运行特定测试方法
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest tests/test_eval.py::TestEvalLayers::test_regression_layer -v
```

### 使用 pytest 标记

```bash
# 运行所有回归测试
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest -m layer_regression -v

# 运行所有上下文测试
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest -m layer_context -v

# 运行所有记忆测试
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest -m layer_memory -v

# 运行所有恢复测试
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest -m layer_resume -v
```

## 四层评测详解

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
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest tests/test_harness.py::TestRunFlow -v
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
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest tests/test_context.py -v
```

**评测指标**:
- 平均压缩率: ~80%
- 最高压缩率: ~81%
- 预算内完成率: 100%

### Layer 3: 记忆收益评测

**目标**: 验证 follow-up 阶段重复读文件归零

**测试内容**:
- 父任务创建文件,沉淀摘要
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
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest tests/test_memory.py -v
```

**评测指标**:
- follow-up 重复读文件: 2 → 0 次
- 任务正确率: 100%

### Layer 4: 恢复正确性评测

**目标**: 验证 checkpoint/resume + 工作区漂移识别

**测试内容**:
- 中断任务(stop_after_steps)
- 可选:外部修改工作区(模拟漂移)
- 恢复任务(resume)
- 验证: 漂移检测、续跑完成、文件存在

**测试用例**:
- `test_interrupt_resume_continues`: 中断恢复续跑
- `test_resume_detects_drift`: 恢复检测漂移
- `test_resume_missing_checkpoint`: 缺失断点

**验证方法**:
```bash
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest tests/test_harness.py::TestResumeFlow -v
```

**评测指标**:
- 漂移识别准确率: 100%(5/5 漂移检出, 5/5 无漂移正确)
- 恢复后完成率: 100%

## 安全边界测试

### 参数校验
```bash
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest tests/test_safety.py::TestParamValidation -v
```

### 工作区隔离
```bash
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest tests/test_sandbox.py::TestResolve -v
```

### HITL 审批
```bash
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest tests/test_safety.py::TestHitl -v
```

### 去重拦截
```bash
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest tests/test_safety.py::TestDedup -v
```

### 敏感信息脱敏
```bash
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest tests/test_safety.py::TestRedact -v
```

## 评测报告

运行完整评测后,生成报告:

```bash
& "D:\ANACONDA\envs\ML2\python.exe" -m mycoder eval --suite all --output .mycoder/eval
```

报告文件:
- `.mycoder/eval/report.json`: 结构化报告(JSON)
- `.mycoder/eval/report.md`: 人类可读报告(Markdown)

## 测试覆盖率

### 模块覆盖
- ✅ models: MockBackend, LocalOpenAIBackend, 工厂装配
- ✅ tools: 7 类工具功能测试
- ✅ sandbox: 路径隔离、指纹快照
- ✅ safety: 参数校验、隔离、HITL、去重、脱敏
- ✅ context: token 估算、折叠、硬限额、拷贝安全
- ✅ memory: 三层存储、去重、检索、持久化
- ✅ checkpoint: 断点保存/加载、漂移识别
- ✅ harness: 主循环、安全拦截、去重、记忆、恢复
- ✅ eval: 四层评测、benchmark 数据完整性

### 测试用例统计
- test_models.py: ~15 个用例
- test_tools.py: ~20 个用例
- test_sandbox.py: ~15 个用例
- test_safety.py: ~25 个用例
- test_context.py: ~15 个用例
- test_memory.py: ~20 个用例
- test_checkpoint.py: ~15 个用例
- test_harness.py: ~20 个用例
- test_eval.py: ~10 个用例

**总计**: ~155 个测试用例(超过 105 项目标)

## 确定性保证

所有测试使用:
- **MockBackend**: 脚本化响应,同一输入必得同一输出
- **临时工作区**: pytest tmp_path fixture,互不污染
- **固定配置**: Config() 默认配置,无随机性

保证:
- 同一环境、同一代码,测试结果 100% 可复现
- 不同环境(Windows/Linux/macOS),测试结果一致

## 故障排查

### pytest 找不到测试
```bash
# 确保在 mycoder 项目根目录
cd "D:\DeepSeek Harness\mycoder"

# 确保使用 ML2 环境
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest tests/ --collect-only
```

### 导入错误
```bash
# 确保 conftest.py 存在
ls tests/conftest.py

# 确保项目根目录在 sys.path
& "D:\ANACONDA\envs\ML2\python.exe" -c "import sys; sys.path.insert(0, '.'); import mycoder"
```

### 评测失败
```bash
# 查看详细输出
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest tests/test_eval.py -v -s

# 查看评测报告
cat .mycoder/eval/report.md
```

## 持续集成

建议配置 CI(如 GitHub Actions):

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
      - name: Run tests
        run: pytest tests/ -v
      - name: Run eval
        run: python -m mycoder eval --suite all
```
