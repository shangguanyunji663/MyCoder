# MyCoder — 本地 Coding Agent Harness

面向代码仓库长链路任务的本地 Agent 运行底座,解决多轮开发任务中:
- **上下文膨胀** → 上下文治理模块(预算裁剪)
- **重复读文件** → 结构化记忆系统(任务/文件/关联三层)
- **任务状态丢失** → Checkpoint/Resume + 工作区漂移识别
- **结果难复盘** → 三类运行工件(轨迹/检查点/指标报告) + 四层评测审计

## 核心特性

### 1. Agent Harness 主循环
- 统一封装模型调用、工具执行、会话状态、checkpoint、运行日志
- 支持 2 类模型后端:
  - **MockBackend**: 确定性脚本后端(测试/评测,全离线)
  - **LocalOpenAIBackend**: 本地 OpenAI 兼容后端(127.0.0.1:8080)
- 7 类工具: file_read/write/edit/list, grep_search, shell_exec, memory_query
- 3 类运行工件: trajectory.jsonl, checkpoint.json, metrics.json + report.md

### 2. 长上下文治理
- 按「任务目标 / 当前文件 / 历史摘要 / 工具结果」组织上下文
- 预算裁剪机制:软预算(触发折叠) + 硬限额(强制截断)
- 评测指标:
  - 平均压缩率 ~80%
  - 预算内完成率 100%

### 3. 结构化记忆系统
- 三层分层存储:
  - **任务摘要**: 目标/状态/结论/关键决策/涉及文件
  - **文件摘要**: 哈希指纹/摘要/符号(函数类导入)/最近访问
  - **关联记忆**: 任务↔文件、任务↔父任务(follow-up)、文件↔文件(依赖)
- follow-up 任务自动注入父任务摘要,避免重读文件
- 评测指标: follow-up 阶段重复读文件 0 次,正确率 100%

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
- 四层评测(区分模型能力与系统能力):
  1. **Harness 回归**: 运行时稳定性(能完成、工件齐全、断言满足)
  2. **上下文治理**: 预算裁剪收益(治理 vs 不治理的 prompt 长度差)
  3. **记忆收益**: follow-up 重复读文件归零、正确率
  4. **恢复正确性**: checkpoint/resume + 漂移识别边界
- 12 个 benchmark 任务 + 105 项 pytest 自动化测试
- 对照实验: 固定任务、固定数据、仅改变系统开关
- 运行工件聚合: 可复现的评测报告(JSON + Markdown)

## 项目结构

```
mycoder/
├── README.md                    # 本文件
├── pyproject.toml               # 项目元数据与依赖
├── requirements.txt             # pip 依赖清单
├── .gitignore                   # Git 忽略规则
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
│   │   ├── summarizer.py        # 历史摘要器
│   │   └── manager.py           # ContextManager
│   ├── memory/                  # 结构化记忆
│   │   ├── store.py             # StructuredMemory
│   │   └── retriever.py         # MemoryRetriever
│   ├── checkpoint/              # 断点与恢复
│   │   ├── store.py             # CheckpointStore
│   │   └── drift.py             # WorkspaceDriftDetector
│   ├── safety/                  # 安全边界
│   │   ├── guard.py             # SafetyGuard(校验/隔离/HITL/去重)
│   │   └── redact.py            # Redactor(脱敏)
│   ├── agent/                   # 主循环
│   │   └── harness.py           # AgentHarness
│   ├── api/                     # localhost HTTP API
│   │   └── server.py            # 127.0.0.1:8910
│   └── eval/                    # 评测审计
│       ├── benchmark.py         # benchmark 数据加载
│       ├── experiment.py        # 对照实验原语
│       └── runner.py            # 四层评测运行器
├── benchmarks/
│   └── tasks.json               # 12 个 benchmark 任务
├── tests/                       # pytest 测试套件
│   ├── conftest.py
│   ├── test_models.py
│   ├── test_tools.py
│   ├── test_sandbox.py
│   ├── test_safety.py
│   ├── test_context.py
│   ├── test_memory.py
│   ├── test_checkpoint.py
│   ├── test_harness.py
│   └── test_eval.py
├── examples/                    # 使用示例
│   └── demo.py
└── docs/                        # 文档
    ├── ARCHITECTURE.md
    ├── OUTLINE.md
    └── TESTING.md
```

## 快速开始

### 环境要求
- Python 3.10+
- PyYAML (运行时依赖)
- pytest (测试依赖)

### 安装依赖

```bash
# 使用 ML2 环境(已预装 pytest)
conda activate ML2

# 安装项目依赖
cd "D:\DeepSeek Harness\mycoder"
pip install -r requirements.txt
```

### 运行 Demo

```bash
# 使用 ML2 环境运行 demo
& "D:\ANACONDA\envs\ML2\python.exe" examples/demo.py
```

### 运行测试

```bash
# 使用 ML2 环境运行完整测试套件
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest tests/ -v

# 运行特定层测试
& "D:\ANACONDA\envs\ML2\python.exe" -m pytest tests/test_eval.py::TestEvalLayers -v
```

### 运行评测

```bash
# 运行四层评测
& "D:\ANACONDA\envs\ML2\python.exe" -m mycoder eval --suite all --output .mycoder/eval

# 查看评测报告
cat .mycoder/eval/report.md
```

### 启动 localhost API

```bash
# 启动 HTTP API 服务(127.0.0.1:8910)
& "D:\ANACONDA\envs\ML2\python.exe" -m mycoder serve --host 127.0.0.1 --port 8910

# 测试 API
curl http://127.0.0.1:8910/health
```

## 配置说明

配置文件: `config/default.yaml`

关键配置项:
- `workspace.root`: 工作区根目录(工具沙箱边界)
- `model.backend`: 模型后端(mock / local_openai)
- `context.budget_tokens`: 上下文软预算(token 数)
- `context.hard_limit_tokens`: 上下文硬上限
- `memory.enabled`: 是否启用结构化记忆
- `checkpoint.enabled`: 是否启用断点保存
- `safety.hitl_policy`: 高风险审批策略(prompt / allow / deny)
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

### 安全边界
- 回归任务通过率: 100%
- 参数校验拦截: 100%
- 路径逃逸拦截: 100%

## 许可证

MIT License

## 贡献

本项目为学习/研究用途,欢迎提出改进建议。
