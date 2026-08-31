# MyCoder 项目学习指南(完整版)— 从零构建并吃透一个本地 Coding Agent Harness

> 本文档按照"如果你要从头写这个项目,你会怎么思考和编码"的顺序,逐模块拆解每一行代码的设计意图与实现细节。它同时具备四种特性:**详细**(完整覆盖核心概念与背景知识,不跳步)、**深入**(讲清每个设计背后的"为什么")、**易上手**(零基础视角,每章配可运行示例与练习)、**易检索**(结构统一、术语一致、附录速查)。建议按顺序阅读,每个模块读完后对照源码走一遍。
>
> 本指南基于仓库当前状态:26 项手写 benchmark + 42 项冻结基准、82 条检索查询、**272 项 pytest 测试**(18 个测试文件)。文中所有"动手示例"均在项目内置 `.conda` 环境中实际运行验证过,标注的输出为真实输出。

---

## 目录

| 部分 | 章节 | 内容 | 适合谁 |
|------|------|------|--------|
| 一、如何使用本文档 | — | 学习路径 / 阅读约定 | 所有人,**必读** |
| 二、预备知识 | 第 0 章 | 背景知识与核心术语 | 零基础读者 |
| 三、环境与上手 | 第 1 章 | 环境准备(.conda) | 所有人,**必读** |
| | 第 2 章 | 快速上手:20 分钟跑通全流程 | 所有人 |
| 四、总览 | 第 3 章 | 学习路线总览(原第〇章) | 所有人 |
| 五、十站源码走读 | 第 4 章 | 第 1 站 地基:config / state / util / artifacts | L1+ |
| | 第 5 章 | 第 2 站 模型后端:models/ | L1+ |
| | 第 6 章 | 第 3 站 工具框架:tools/ | L1+ |
| | 第 7 章 | 第 4 站 安全边界:safety/ | L1+ |
| | 第 8 章 | 第 5 站 上下文治理:context/ | L1+ |
| | 第 9 章 | 第 6 站 结构化记忆:memory/ | L2 |
| | 第 10 章 | 第 7 站 断点恢复:checkpoint/ | L2 |
| | 第 11 章 | 第 8 站 主循环:agent/harness | L2,**核心** |
| | 第 12 章 | 第 9 站 评测闭环:eval/ | L2 |
| | 第 13 章 | 第 10 站 收尾:cli / api / examples / tests | L1+ |
| 六、总结 | 第 14 章 | 设计模式回顾与核心数据流 | L2 |
| | 第 15 章 | 读完之后:实操进阶路线 | 所有人 |
| 七、附录(检索区) | A~G | 术语表 / 配置速查 / CLI 速查 / 测试索引 / FAQ / 易错点大全 / 自测清单 | 所有人 |

> **检索提示**:遇到不认识的词,先查[附录 A 术语表](#附录-a-完整术语表按主题分组);配置项含义查[附录 B](#附录-b-配置项速查表);命令用法查[附录 C](#附录-c-cli--api-命令速查);"为什么跑不起来/结果不对"查[附录 E FAQ](#附录-e-faq常见问题解答)与[附录 F 易错点大全](#附录-f-易错点与调试技巧大全)。

---

# 第一部分 如何使用本文档

## 你将学到什么

读完本文档(并完成练习)后,你应当能够:

1. **说清楚**一个 Coding Agent Harness 是什么、解决什么问题、由哪些模块组成;
2. **跑通**项目的全部测试、Demo 与五层评测,并读懂评测报告;
3. **逐行理解**每个模块的实现:配置合并、模型后端、工具沙箱、安全链、上下文裁剪、结构化记忆、断点恢复、主循环、评测闭环;
4. **回答"为什么"**:为什么用启发式 token 估算?为什么裁剪要在深拷贝上做?为什么读去重返回缓存而写去重不返回?为什么 Mock 后端是评测体系的基石?
5. **动手扩展**:添加一个新工具、换一种摘要策略、跑一次三臂对照实验。

## 学习路径:你处于哪个水平?

请对号入座,选择一条路径。每条路径都从"必读"开始,后续按需展开。

| 路径 | 你是谁 | 目标 | 推荐章节(按序) | 预计投入 | 完成的标志 |
|------|--------|------|------------------|----------|------------|
| **P0 跑起来** | 完全零基础,只想看到它能运行 | 跑通测试/Demo/评测,建立直观感受 | 第 0.1~0.3 节 → 第 1 章 → 第 2 章 | ~1 小时 | 浏览器里看到监控页出现一次任务运行 |
| **P1 会使用** | 会 Python,想理解系统怎么工作 | 能解释每个模块"做什么、为什么" | P0 + 第 3 章 → 第 1/5/8 站精读(第 4/5/8、11 章)→ 附录 B/C | ~半天 | 能向别人画出主循环流程图 |
| **P2 懂设计** | 想吃透设计思路 | 十站全部走读,完成每站练习 | P1 + 十站全序(第 4~13 章)→ 第 14 章 | 2~3 天 | 完成全部"进阶练习" |
| **P3 能贡献** | 要改源码/做扩展/做研究 | 能安全地修改并通过全部测试 | P2 + 附录 D 测试索引 → 每站测试文件对照 → 第 15 章进阶任务 | ~1 周 | 独立完成第 15 章的任一扩展任务且 272 项测试全绿 |

> **P0 读者注意**:你不需要读完整个文档。第 0 章只读 0.1~0.3 节即可上手;其余章节可以在你产生"这是怎么做到的?"疑问时再回来按站查阅——本文档同时是一份**按模块组织的参考手册**。

## 阅读约定

- **【为什么】** 小节:解释设计动机与原理,对应"深度"要求;赶时间的读者可跳过,不影响照着做。
- **▶ 动手示例**:可直接复制运行的代码,均已在项目环境中验证;缩进下方给出**真实输出**。
- **✍ 练习**:分"基础"(巩固概念)与"进阶"(动手改造)两档。
- **⚠ 易错点**:真实容易踩的坑,与[附录 F](#附录-f-易错点与调试技巧大全)汇总索引互相引用。
- **☑ 自测清单**:每站末尾,能全部答"是"再进入下一站。
- 代码引用格式 `mycoder/agent/harness.py:287` 表示仓库内文件与行号(行号基于当前版本,可能随代码演进而漂移,以函数名为准)。
- 术语首次出现时用粗体并给出定义;统一译法见[附录 A](#附录-a-完整术语表按主题分组),例如 checkpoint 统一译"断点"、artifact 统一译"工件"、prune 统一译"裁剪"。

---

# 第二部分 预备知识

## 第 0 章 背景知识与核心术语

> 本章为**零基础读者**准备:先把"看懂后面十站"所需的最小背景补齐。有 Agent 开发经验的读者可以快速滑过,但建议读一遍 0.4 节的观念误区——它们正是本项目的立意所在。

### 0.1 什么是 Coding Agent?什么是 Harness?

**LLM(大语言模型)本质上只会一件事:给定一段文本,预测下一段文本。** 它天生不会读你磁盘上的文件、不会执行命令、也不会记住上一件事。所谓 **Coding Agent(编码智能体)**,是这样一个程序:把 LLM 包在一个循环里,让它能够**调用工具**(读文件、改代码、跑命令),根据工具返回的**观察结果**决定下一步,直到完成任务。这个"推理 → 行动 → 观察 → 再推理"的循环,就是业界常说的 ReAct 模式。

**Harness(运行底座/主循环)** 则是围绕这个循环的全部工程设施。打个比方:LLM 是发动机,Harness 是整辆车——油门刹车(安全边界)、油箱仪表(上下文治理与指标)、导航记录(轨迹与断点)、后视镜(记忆)。发动机再好,没有车你也上不了路。

MyCoder 的定位:**不训练模型、不调用云端 API**,而是围绕任意一个"OpenAI 兼容"的本地模型(或确定性 Mock)搭建一个**可复现、可恢复、可审计**的 Agent 运行底座。

### 0.2 单次调用 vs 工具循环 vs 完整 Harness

理解 Harness 价值的最好方式,是看三个层次的对比。这不是理论假设——项目的 Layer 6b 评测(**裸模型基线对照**)用同一个本地模型(qwen3.5:2b)、同一组 4 个真实编码任务实测过:

| 层次 | 做法 | 有无工具循环 | 有无治理/记忆/断点/安全 | 硬断言通过率 |
|------|------|--------------|--------------------------|--------------|
| single_shot | 一次请求把任务全问完 | 无 | 无 | **1/4** |
| naive_loop | 朴素 tool-calling 循环 | 有 | 无 | **3/4** |
| full harness | MyCoder 完整主循环 | 有 | 有 | **4/4** |

三点结论,也是贯穿全文档的主线:

1. **工具循环是最大的一次跃升**(1/4 → 3/4):模型必须能"边看边做",单次问答做不了多步编码任务;
2. **Harness 的增量价值真实存在**(3/4 → 4/4):上下文治理、记忆、容错(空终答温和重问)在真实小模型上救回了 naive_loop 完不成的任务;
3. **Harness 有固有成本**:prompt token 三臂对比为 single_shot 529 / naive_loop 14564 / harness 115919——多步循环与系统提示天然更贵,这正是第 5 站"上下文治理"要优化的对象。

### 0.3 必懂的 10 个基础概念

每个概念按"是什么 → 在 MyCoder 里的对应物 → 为什么重要"三段展开。深入实现见对应"站"。

**① Token(词元)。** LLM 处理文本的最小单位,一个英文单词约 1~2 个 token,一个汉字通常恰好 1 个 token。模型按 token 计费、按 token 限制上下文。→ MyCoder 用启发式估算(中文按字、英文 4 字符≈1 token),见第 5 站 tokens.py。

**② 上下文窗口(context window)与预算。** 模型一次能"看见"的全部文本上限。超窗直接报错;接近上限时质量也会劣化。→ MyCoder 用两个配置表达:`context.budget_tokens`(软预算,4000,超了就触发折叠)与 `context.hard_limit_tokens`(硬上限,6000,任何情况下不得越过),见第 5 站。

**③ System Prompt(系统提示)。** 放在消息列表最前面、定义 Agent 身份与规则的消息。→ `ContextManager` 内置 `SYSTEM_PROMPT`,规定"路径必须是工作区相对路径""优先用记忆避免重复读文件"等行为准则。

**④ Tool Calling(工具调用 / 函数调用)。** 模型不直接做事,而是输出一个结构化请求:工具名 + 参数(JSON Schema 描述)。程序执行后把结果作为 `tool` 角色消息回传。**关键细节:OpenAI 兼容协议里 `arguments` 是 JSON 字符串而非字典**,程序要自己 `json.loads`——这是新手最常踩的坑之一(见第 2 站/第 8 站易错点)。

**⑤ Temperature 与确定性。** 采样温度,越高越随机。→ 评测要求"同一输入必得同一输出",所以本地后端默认 `temperature: 0.0`,测试/评测干脆用**脚本化的 MockBackend**(第 2 站)。

**⑥ Usage(用量)。** 模型 API 返回的 `prompt_tokens` / `completion_tokens`,是成本核算与压缩率指标的数据源。→ `Step.prompt_tokens` 记裁剪后、`prompt_before_tokens` 记裁剪前,两者之差就是治理收益。

**⑦ 序列化与原子写。** 把内存对象转成可存储文本(JSON / JSONL)的过程;**原子写**指"先写临时文件再 `os.replace`",保证崩溃时不留半截文件。→ checkpoint、trajectory.jsonl 都依赖它,见第 1 站 util.py。

**⑧ 沙箱与路径逃逸。** 把 Agent 的文件访问限制在一个根目录内。**路径逃逸**指用 `../`、绝对路径、符号链接等手段越过边界。→ `Workspace.resolve()` 的四层防护,见第 3 站 sandbox.py。

**⑨ HITL(Human-In-The-Loop,人在回路审批)。** 高风险操作(如执行 shell 命令)先停下来,让人确认。→ `danger` 等级 + `ApprovalProvider` 策略,见第 4 站。

**⑩ 对照实验(A/B)。** 固定一切变量,只改一个开关,比较结果——这是把"系统收益"从"感觉良好"变成"可量化数字"的唯一方法。→ 五层评测全部采用此思想,见第 9 站。

### 0.4 新手常见的 5 个观念误区

1. **"Agent 强不强,取决于模型强不强。"** 部分正确但有误导。Layer 6b 实测显示:同一个 2b 小模型,套上不同系统(单次调用/朴素循环/完整 Harness),通过率从 1/4 到 4/4。**系统能力与模型能力是两个正交的变量**,MyCoder 的整个评测设计(用 Mock 固定模型能力、只测系统能力)就是建立在这个区分上。
2. **"上下文窗口够大(128k+)就不需要治理。"** 三个反驳:成本随 token 线性增长;窗口里塞满无关历史会稀释关键信息(信噪比下降);评测需要可复现的 prompt 长度。治理不是为了"塞得下",而是为了"又小又准又稳"。
3. **"Mock 后端没意义,我要直接测真模型。"** 反了。真模型有随机性,跑两次结果不同,你无法判断改动是好是坏。Mock 是**确定性的**,它把"模型能力"这个变量冻结,让评测只度量系统能力;真模型评测(Layer 6/6b)是在 Mock 证明系统正确之后的补充。
4. **"安全可以最后再补。"** 安全必须与业务**正交**(分离):工具只管做事,安全链在进入工具前统一拦截。事后补安全意味着每个工具都要自己记得防逃逸、防注入,迟早漏一处。
5. **"评测就是找几个例子跑跑,看感觉。"** 没有对照就没有结论。"压缩率高"没有意义,"同一任务下治理臂比不治理臂 prompt 短 80%"才有意义。第 9 站的全部评测都是对照式的。

### 0.5 本章自测

- ☑ 我能用"发动机/整车"的比喻说清 Harness 与 LLM 的关系;
- ☑ 我能说出工具循环相比单次调用多了什么(single_shot → naive_loop 的跃升);
- ☑ 我知道 OpenAI 协议里工具参数 `arguments` 的类型是**字符串**;
- ☑ 我能解释为什么评测需要 Mock 后端(关键词:确定性、冻结变量)。

---

# 第三部分 环境与快速上手

## 第 1 章 环境准备:项目内置 `.conda` 环境(动手前必读)

本项目所有代码、测试、评测均基于**仓库内自带的 Conda 独立环境**,不再依赖系统 Python 或全局 Anaconda 的 base/命名环境。

| 项目 | 说明 |
|------|------|
| 环境位置 | `D:\PythonProject\mycoder\.conda\`(相对仓库即 `<repo>\.conda`) |
| 管理方式 | Anaconda 以**路径(prefix)**方式管理,环境名显示为完整路径 |
| Python 版本 | 3.11(pyproject 声明兼容 3.10+) |
| 预装内容 | 全部运行时依赖 + dev/api/vector 可选组 + 项目本体可编辑安装(`pip install -e .`) |
| 版本控制 | `.conda/` 已加入 .gitignore,**不入库** |

### 1.1 日常使用(三选一)

```bash
# 1) 激活后使用 python(PowerShell/cmd)
conda activate D:\PythonProject\mycoder\.conda

# 2) Git Bash 中激活
source .conda/Scripts/activate

# 3) 不激活,直接调用项目内解释器(最不容易出错,本文档默认用它)
.conda/python.exe -m pytest tests/       # cmd/PowerShell 写法: .conda\python.exe ...
```

**三种 shell 写法速查**(Windows 下最容易混):

| 操作 | Git Bash | PowerShell / cmd |
|------|----------|------------------|
| 直接跑 | `.conda/python.exe -m pytest tests/` | `.conda\python.exe -m pytest tests/` |
| 激活 | `source .conda/Scripts/activate` | `conda activate D:\PythonProject\mycoder\.conda` |
| 路径分隔 | `/`(正斜杠) | `\`(反斜杠) |

### 1.2 验证环境可用

```bash
.conda/python.exe --version                       # 应输出 Python 3.11.x
.conda/python.exe -m pytest tests/ --collect-only -q | tail -3   # 应列出 272 个用例
.conda/python.exe -m mycoder doctor               # 内置环境自检:打印配置/依赖诊断
```

### 1.3 环境坏了/换机器怎么重建(一条命令,全部依赖自动就位)

```bash
conda env create -p .conda -f environment.yml
```

> `environment.yml` 使用 conda-forge 渠道的 python 3.11 + pip,再由 pip 安装 `requirements-project.txt`(其内部聚合 requirements-dev/api/vector 并执行 `-e .`)。IDE(VS Code/PyCharm)把解释器指向 `.conda/python.exe` 即可识别为 Conda 环境。

### 1.4 常见环境问题排查

| 症状 | 原因 | 解法 |
|------|------|------|
| `conda: command not found` | conda 不在 PATH | 用完整路径,如 `D:\miniconda3\Scripts\conda.exe`;或干脆用方式 3 直接调 `.conda/python.exe` |
| `ModuleNotFoundError: mycoder` | 用了别的 Python,或不在仓库根目录 | 确认用 `.conda/python.exe`,且 `cd` 到仓库根再执行 |
| `pytest: command not found` | 未激活环境 | 用 `.conda/python.exe -m pytest` 形式 |
| 中文输出乱码 | Windows 控制台默认 GBK | 设置环境变量 `PYTHONIOENCODING=utf-8`,或用 Git Bash / Windows Terminal |
| 路径含中文/空格导致奇怪报错 | 部分工具链对非 ASCII 路径不友好 | 把仓库放到纯英文路径(如 `D:\PythonProject\mycoder`) |
| pytest 收集数不是 272 | 环境不完整或收集到旧缓存 | 删除 `tests/__pycache__`、`.pytest_cache` 后重试;必要时重建环境 |
| `.conda` 目录被杀毒软件锁定导致安装失败 | 实时防护拦截 | 将仓库目录加入白名单后重建 |

**⚠ 易错点**:CLI(`python -m mycoder ...`)**默认只加载内置默认值,不会自动读 `config/default.yaml`**;要用本文件的配置,必须显式传 `--config config/default.yaml`(见 `mycoder/cli.py` 的 `_build_config`)。这是"我明明改了配置怎么没生效"的头号原因。

**✍ 练习(基础)**
1. 用方式 3 跑通 1.2 节的三条验证命令,把输出贴到你的笔记里;
2. 运行 `.conda/python.exe -m mycoder doctor`,逐行理解它打印了什么。

**☑ 自测清单**:我能不假思索地写出"在 Git Bash 里用项目内解释器跑 pytest"的命令。

---

## 第 2 章 快速上手:20 分钟跑通全流程

> 本章面向所有人:先用 5 步建立"它能干什么"的直观感受,后面十站再解释"它是怎么做到的"。所有命令在**仓库根目录**执行;每步都给出你应当看到的输出。

### 第 1 步:确认环境(~1 分钟)

```bash
.conda/python.exe --version          # Python 3.11.x
```

### 第 2 步:跑全部测试(~2 分钟,建立"改动前基线")

```bash
.conda/python.exe -m pytest tests/
```

预期:全部通过(272 项,含 8 项性能测试),末尾形如 `===== 272 passed in XXs =====`。**习惯:以后任何改动之前先跑一遍,留下绿色基线;改动之后再跑,红了就是你改坏的。**

只想快速验证某个模块?指定文件即可:

```bash
.conda/python.exe -m pytest tests/test_sandbox.py -v        # 只跑沙箱 15 项
.conda/python.exe -m pytest tests/test_eval.py::TestEvalLayers -v
```

### 第 3 步:跑上下文治理 Demo(~10 秒,直观看"治理")

```bash
.conda/python.exe examples/context_demo.py
```

真实输出(节选):

```
Giant file: 4669 lines, 143599 chars, 35900 tokens

  Turn  6 | Raw:  6377 tokens -> After:  1503 tokens | Ratio: 76% | Strategies: ['drop_stale_turns'] !! PRUNED!
  Turn  9 | Raw:  9488 tokens -> After:  1685 tokens | Ratio: 82% | Strategies: ['fold_old_turns', 'drop_stale_turns'] !! PRUNED!
  Turn 15 | Raw: 15710 tokens -> After:  2050 tokens | Ratio: 87% | Strategies: ['fold_old_turns', 'drop_stale_turns'] !! PRUNED!

  Without governance:  15710 tokens  (exceeds hard limit 6000 by 2x)
  With governance:     2050 tokens  (within budget!)
  Compression ratio:   87%
```

它模拟了 15 轮对话、每轮读 300 行巨型文件:不做治理 prompt 会膨胀到 15710 token,治理后稳定在 2000 上下文。这就是第 5 站"上下文治理"的全部意义。

### 第 4 步:跑五层离线评测(~1 分钟,拿到量化报告)

```bash
.conda/python.exe -m mycoder eval --suite all --output .mycoder/eval
cat .mycoder/eval/report.md        # Windows 记事本/VS Code 打开亦可
```

预期:report.md 依次给出 Layer 1 回归 / Layer 2 上下文(压缩率 ~80%)/ Layer 3 记忆(follow-up 重读 2→0)/ Layer 4 恢复(10 场景漂移识别 100%)/ Layer 5 检索(recall@3:substring 28% vs hybrid 63%)五段结果。报告怎么读,见第 12 章。

### 第 5 步:启动 API + 浏览器监控页(~1 分钟)

```bash
.conda/python.exe -m mycoder serve --impl fastapi
# 另开一个终端:
curl http://127.0.0.1:8910/health        # {"service":"mycoder","version":"0.1"}
```

浏览器打开 `http://127.0.0.1:8910/`:这是零构建的 Vue 3 监控页。提交一个任务(mock 后端默认离线可跑),SSE 会实时推送 task_start → step_start → model_call → tool_call → step_end → task_end 事件流。

### 你刚才看到了什么:现象 → 机制 → 深入章节

| 你看到的现象 | 背后的机制 | 深入阅读 |
|--------------|------------|----------|
| 272 项测试全绿 | 每个模块都有独立单测,安全边界参数化展开到 70 项 | 附录 D |
| Turn 15 时 prompt 被压到 87% | 三层递进裁剪:折叠旧轮→丢弃陈旧轮→截断超长内容 | 第 5 站 |
| 评测报告里"重读 2→0" | 结构化记忆 + follow-up 摘要注入 | 第 6 站 |
| 恢复场景 10/10 漂移识别正确 | SHA-256 文件指纹逐文件精确比对 | 第 7 站 |
| 监控页实时事件流 | harness 的 `on_event` 埋点 → SSE EventBus | 第 10 站 |

**✍ 练习(基础)**
1. 把第 3 步 demo 的 `context.hard_limit_tokens` 从 6000 改成 3000(直接改 `examples/context_demo.py` 里的 `config.set(...)`),重跑,观察裁剪策略何时出现第三档 `truncate_long_content`;
2. 在监控页连续提交两个任务,对比两条轨迹的 step 数与 token 数。

**⚠ 易错点**
- 所有命令都要在**仓库根目录**执行;`examples/context_demo.py` 依赖 `examples/giant_test.py` 的相对路径。
- 第 4 步评测会在仓库里生成 `.mycoder/` 目录(工件/记忆/断点),这是正常的,已入 .gitignore;评测 runner 每次运行前会自行重置该目录(但 `real`/`real_baseline` 两个 suite 例外,**不清空**输出目录以便三臂对照共存)。

**☑ 自测清单**:四条命令(pytest / context_demo / eval / serve)我都能独立跑出正确输出。

---

# 第四部分 总览

## 第 3 章 学习路线总览(原第〇章)

### 3.1 阶段自测:你应该怎么读这一部分?

- **只想把它跑起来**:读完第一、二部分即可,本章可跳过;
- **想理解为什么这样设计**:精读本章 + [ARCHITECTURE.md](ARCHITECTURE.md) 的「核心设计原则」,再进入第 8 站主循环;
- **想逐行吃透源码甚至做贡献**:按下面 10 站顺序完整走读,每站读完跑对应单测(`tests/test_<模块>.py`)验证理解。

### 3.2 十站源码走读路线

```
第 1 站  地基        config / state / util / artifacts    — 先把"骨架数据结构"立起来
第 2 站  模型后端    models/base + mock + local_openai    — 让"大脑"可替换
第 3 站  工具框架    tools/base + sandbox + 7 个工具      — 让"手脚"可扩展
第 4 站  安全边界    safety/guard + redact                — 在手脚上加"护栏"
第 5 站  上下文治理  context/tokens + summarizer + manager — 让"记忆容量"不爆
第 6 站  结构化记忆  memory/store + retriever             — 让"经验"可复用
第 7 站  断点恢复    checkpoint/store + drift             — 让"中断"可续跑
第 8 站  主循环      agent/harness                         — 把一切编排起来
第 9 站  评测闭环    eval/benchmark + experiment + runner  — 用数据证明系统有效
第 10 站 收尾        cli / api / examples / tests          — 对外接口与质量保障
```

**为什么是这个顺序?** 这是一条**依赖驱动**的阅读顺序:每一站只依赖它之前讲过的东西。先立数据结构(没有数据就没有逻辑),再接大脑(模型)和手脚(工具),随后给手脚加护栏(安全),然后解决"大脑记忆有限"(上下文)和"项目会遗忘"(记忆)两个问题,补上"中断可续"(断点),最后把一切编排进主循环,并用评测证明整个系统有效。**如果你只有时间精读两站,选第 5 站(上下文治理)和第 8 站(主循环)**——前者是本项目最有原创性的算法,后者是所有模块的交汇点。

### 3.3 模块关系一览(谁依赖谁)

```
                    config.py(配置,被一切依赖)
                          │
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
  state.py(纯数据)   util.py(原子写/哈希)   artifacts.py(工件落盘)
        │
        ▼
 models/ ──▶ agent/harness(主循环,中枢) ◀── checkpoint/(断点+漂移)
                │   │   │
   tools/ ──────┘   │   └────── memory/ (三层记忆+检索)
   safety/ ─────────┘  context/ (上下文组装与裁剪)
        │
        ├─▶ observability/ (on_event → trace.json)
        ├─▶ api/ (event_bus + fastapi_server,SSE)
        ├─▶ eval/ (benchmark 数据 + runner 对照实验)
        └─▶ agent/orchestrator.py (多子任务并行)
```

阅读时把握两条主线:**纵向**是"一次 run 调用穿过哪些层"(config→harness→context→model→safety→tool→memory),**横向**是"哪些机制横切所有步骤"(工件/追踪/断点/安全)。

### 3.4 核心设计哲学(贯穿全程)——以及它们各自的"为什么"

**哲学一:确定性优先。** 同一输入必得同一输出。
- *为什么?* 评测的本质是"改动前后对比"。如果系统本身有随机性,跑两次结果不同,你就永远无法判断指标变化是你的改动造成的还是运气。因此:Mock 后端脚本化(第 2 站)、temperature 默认 0(第 2 站)、摘要器确定性实现(第 5 站)、裁剪每次从完整历史全量重算(第 5 站)、基准数据冻结入库(第 9 站)——全链路都在消灭随机性。

**哲学二:安全与业务正交。** 工具只管做事,安全在进入工具前拦截。
- *为什么?* 如果每个工具自己校验路径、自己防注入,"新增一个工具 = 新增一摞安全责任",迟早漏一处。把五步安全链(校验/隔离/白名单/去重/审批)放在统一入口(第 4 站),新工具**天然**获得全部保护,只需声明自己的 `danger` 等级。

**哲学三:深拷贝不可变。** 裁剪不污染原始历史,保证可重放。
- *为什么?* `assemble()` 每一步都可能截断消息。如果直接在原始历史上改,历史就被破坏了:下一次 assemble 的"裁剪前长度"会失真,checkpoint 存的历史不完整,评测的 `before_tokens` 也无从算起。深拷贝让"完整历史"始终是唯一可信数据源,裁剪只是它的一个**投影**(第 5 站)。

**✍ 练习(基础)**:把 3.3 的模块图画在纸上,标出你自己预测的"一次 file_read 工具调用会经过哪些模块",读完第 8 站后回头对照。

---

# 第五部分 十站源码走读

> 从本章起进入源码。每站结构统一:**学习目标 → 为什么需要它 → 设计思路与逐行拆解 → 动手示例 → 练习 → 易错点 → 自测清单**。建议对照源码双屏阅读。

## 第 4 章 · 第 1 站 地基:config / state / util / artifacts

> **本站学习目标**:理解配置如何加载合并、会话数据如何建模、通用工具函数为何这样写、三类工件各自承担什么职责。
> **前置知识**:Python `@dataclass`;JSON 概念(第 0 章 ⑦)。

### 为什么先写"地基"?

整个项目所有模块都需要读配置(budget、max_steps、白名单……),主循环每一步都产生数据(消息、工具调用、步),所有落盘都依赖原子写与哈希。**配置层与数据模型必须最先就位**——它们是被一切依赖、而不依赖任何人的"骨架"。这也是一次真实的工程决策演练:动手写主循环之前,先把数据结构立起来,后面每个模块只是在骨架上挂肉。

### 4.1 config.py — 配置加载与合并

**设计思路**:
```
DEFAULT 字典(硬编码安全默认值)
       ↓ 深合并
用户 YAML/JSON 配置(可选覆盖)
       ↓
Config 对象(属性式访问)
```

**逐行拆解**:

```python
DEFAULT: dict[str, Any] = {
    "workspace": {"root": ".", "allow_absolute": False},
    "model": {"backend": "mock", ...},
    "context": {"budget_tokens": 4000, "hard_limit_tokens": 6000, ...},
    ...
}
```
- 内置默认值保证**任何缺失字段都有安全 fallback**——你永远不用担心 KeyError。注意默认值不是随便定的:`backend: "mock"` 保证开箱即用且离线;`allow_absolute: False` 默认收紧安全;`budget/hard` 4000/6000 的比例留出折叠后的缓冲空间。

```python
def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)   # 递归合并
        else:
            out[k] = copy.deepcopy(v)
    return out
```
- **深合并**而非浅合并:用户只覆盖 `context.budget_tokens` 不会把 `context.hard_limit_tokens` 丢掉。浅合并(如 `dict.update`)会整节替换——用户 YAML 里写了两行 context 配置,其余 context 默认值就全没了,这类 bug 极难察觉。
- 两处 `deepcopy` 同样关键:保证返回的配置对象与传入的 `base`/`override` **不共享任何引用**,之后 `cfg.set()` 改动不会反向污染调用方的字典。

```python
class Config:
    def get(self, dotted: str, default: Any = None) -> Any:
        node = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node
```
- **点号路径访问**:`config.get("context.budget_tokens")` 比嵌套字典访问更简洁,全项目统一风格。注意实现细节:中途任何一层不是 dict 或键不存在,立即返回 default——**不会**因为中间节点缺失而抛异常。
- 另有 `set(dotted, value)` 运行期覆盖(评测 A/B 对照就靠它临时改 budget)与 `model_backend` 便捷属性。

**【为什么】配置是"数据"不是"代码"。** 用字典 + 深合并就够,不需要 pydantic:项目的配置项不到 40 个,校验需求轻量(真正的"参数校验"发生在安全层对工具参数的检查上),引入 pydantic 换来的是类型安全但失去"YAML 即所得"的直观性,还多一个依赖。这是一个"够用即可"的典型取舍。

**▶ 动手示例 4-1:配置的三层来源**(已验证)

```python
from mycoder.config import Config

cfg = Config()                                  # 第 1 层:内置 DEFAULT
print(cfg.get("context.budget_tokens"))         # 4000
cfg.load("config/default.yaml")                 # 第 2 层:叠加用户 YAML(深合并)
cfg.set("context.budget_tokens", 2000)          # 第 3 层:运行期覆盖
print(cfg.get("context.budget_tokens"))         # 2000
print(cfg.get("no.such.key", "fallback"))       # 缺失键 → 安全返回 fallback
print(cfg.model_backend)                        # mock(便捷属性)
```

真实输出:
```
4000
2000
fallback
mock
```

### 4.2 state.py — 会话状态模型

**为什么需要它**:Harness 主循环的每一步都产生数据——消息、工具调用、步、任务、结果。这些数据需要:
1. 可序列化(存 checkpoint、写 trajectory.jsonl)
2. 纯数据(无 I/O,便于测试)
3. 可脱敏(敏感信息替换)

**核心数据类**:

```python
@dataclass
class Message:
    role: str           # system / user / assistant / tool
    content: str
    name: str | None    # tool 消息的工具名
    tool_call_id: str | None
    tool_calls: list[dict] | None  # assistant 发起的工具调用
    meta: dict          # 附加信息(文件哈希/缓存命中标记等)

    def to_openai(self) -> dict:
        """转为 OpenAI 兼容格式"""
```
- `to_openai()` 把内部表示转成 HTTP 请求体格式——这是与外部模型服务对接的边界。**内部格式 ≠ 外部协议**:内部允许携带 `meta` 等私有字段,发请求前统一剥掉。

```python
@dataclass
class Step:
    index: int
    assistant: Message | None
    tool_calls: list[ToolCall]
    prompt_tokens: int          # 裁剪后实际送入模型的 token
    prompt_before_tokens: int   # 裁剪前 token(算压缩率用)
    pruned: bool
    prune_strategies: list[str]  # ["fold_old_turns", "drop_stale_turns", ...]
```
- `prompt_before_tokens` 与 `prompt_tokens` 的差就是**裁剪收益**,评测的核心指标(第 9 站 Layer 2 直接消费这两个数)。
- 其余:`TaskInput`(task_id/goal/files_hint/follow_up_of)是任务入口;`RunResult`(status/final_answer/steps/metrics/drift)是出口,`status` 取值 `completed | max_steps | error | interrupted`;`ToolCall.status` 取值 `pending | ok | error | denied | skipped`。

**学习要点**:
- 用 `@dataclass` 而非普通 class:自动生成 `__init__`/`__repr__`,减少样板代码
- 所有字段都是 `str`/`int`/`list`/`dict`——纯 JSON 可序列化,checkpoint 才能无损往返
- **可变类型字段必须 `field(default_factory=dict)`**:直接写 `meta: dict = {}` 会让所有实例共享同一个字典——Python 最经典的坑

**▶ 动手示例 4-2:消息 ↔ OpenAI 格式**(已验证)

```python
from mycoder.state import Message, TaskInput

m = Message("tool", "# a.py 共 2 行\ndef add(a, b):", name="file_read", tool_call_id="call_0")
print(m.to_openai())
```

真实输出:
```
{'role': 'tool', 'content': '# a.py 共 2 行\ndef add(a, b):', 'tool_call_id': 'call_0'}
```
注意:内部的 `meta` 等私有字段不会出现在外部格式里——这正是"内部格式 ≠ 外部协议"边界的体现。

task = TaskInput(task_id="t1", goal="把 greeting.txt 的问候语改成中文", files_hint=["greeting.txt"])
print(task.follow_up_of)   # None(非 follow-up 任务)
```

### 4.3 util.py — 通用工具函数

**设计原则**:小而通用的纯函数,被全项目复用。

```python
def sha256_file(path) -> str:
    """文件内容 SHA-256"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):  # 64KB 分块
            h.update(chunk)
    return h.hexdigest()
```
- **分块读取**:大文件不全读进内存,用 `iter(lambda: f.read(65536), b"")` 模式
- 这个函数被 `Workspace.snapshot()`(指纹)、`remember_file()`(去重)、`drift.py`(漂移检测)三处复用——**哈希是本项目"内容指纹"体系的公共底座**

```python
def atomic_write(path, content) -> None:
    """原子写:先写临时文件再 os.replace"""
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.replace(tmp, p)  # 原子操作
```
- **为什么原子写**:checkpoint/trajectory 写到一半崩溃会留下半截文件;`os.replace` 在同一文件系统内是原子操作,"要么看到旧文件,要么看到完整新文件",不存在中间态。注意临时文件必须与目标**同目录**(跨盘 `os.replace` 不原子)。

```python
def truncate(text, max_chars, head_ratio=0.6) -> str:
    """保留头 60% + 尾部"""
    head = int(max_chars * head_ratio)
    tail = max_chars - head - 30
    return text[:head] + "\n…[截断 N 字符]…\n" + text[-tail:]
```
- **头尾保留**:代码和日志的关键信息通常在开头(import/函数签名)和结尾(return/报错),中间是冗余。中间插一行"截断了 N 字符"让模型知道信息不完整,而不是产生"文件就这么短"的错觉。

### 4.4 artifacts.py — 三类运行工件

**为什么要三类工件**:对应"结果可复盘"的三个维度:

| 工件 | 文件 | 作用 | 写入方式 |
|------|------|------|----------|
| 轨迹 | trajectory.jsonl | 逐步追加的完整记录 | 追加写(崩溃可恢复) |
| 断点 | checkpoint.json | 可恢复的完整快照 | 原子写(由 checkpoint 模块产生) |
| 报告 | metrics.json + report.md | 聚合指标 + 人类可读 | 一次性写 |

(第 8 站的实测还会多出第四件:`trace.json` 链路追踪文件。)

```python
class Metrics:
    """指标累加器"""
    steps: int = 0
    tool_calls: int = 0
    read_calls: int = 0
    read_cache_hits: int = 0    # 去重命中
    compression_ratios: list     # 每次裁剪的压缩率
    files_remembered: int       # 沉淀的文件摘要数
    denied_actions: int         # 被安全层拦截的次数
```
- 这些字段就是评测报告的"数据源",直接映射到 report.md 的每一行。`snapshot()` 会额外派生出 avg/max 均值类字段(avg_prompt_tokens、max_compression_ratio 等)。

**学习要点**:
- `RunRecorder` 用**追加写**(jsonl)而非覆盖写:任何时刻崩溃,已发生的步骤都还在——与 checkpoint 的"覆盖快照"形成互补(日志保历史,快照保恢复)
- `ArtifactManager._render_report()` 把 Metrics 转成人类可读 Markdown——"可观测性"的落地

**✍ 练习**
- 基础:示例 4-1 改为加载 `config/default.yaml` 后打印 `harness.max_steps`、`safety.hitl_policy`、`memory.retrieval.mode` 三个键;把 `context.keep_last_turns` 改成 2 并确认 `get()` 读到新值。
- 基础:为 `Message` 补一个 `meta={"file_hash": "abc"}`,调用 `to_openai()` 确认 meta **不会**泄漏到外部格式。
- 进阶:自己实现一个 `_deep_merge`,与 `mycoder/config.py` 的版本对拍:构造"用户只覆盖 context 节一个键"的用例,断言其他 context 键仍在、且 `cfg.set` 不影响原始 YAML 字典。

**⚠ 易错点**
- `cfg.set()` 只改内存,不写回 YAML 文件;进程重启即失效。
- `get("a.b.c")` 在中间节点缺失/不是字典时返回 default,**不抛异常**——别依赖它做强校验。
- dataclass 字段用可变默认值(`= {}`/`= []`)是语法级错误源;本项目一律 `field(default_factory=...)`。

**☑ 自测清单**
- ☑ 我能画出配置的三层来源(DEFAULT → YAML → set)并解释为什么需要深合并;
- ☑ 我能说出 Step 里"裁剪前/后 token"两个字段分别叫什么、给谁用;
- ☑ 我能解释为什么 trajectory 用追加写而 checkpoint 用原子覆盖写。

---

## 第 5 章 · 第 2 站 模型后端:models/

> **本站学习目标**:理解后端抽象如何解耦"模型如何回答"与"Harness 如何调度";掌握 MockBackend 脚本机制与状态保存;了解本地 OpenAI 兼容后端的实现取舍。
> **前置知识**:第 0 章 ④⑤⑥;第 1 站 Message/ModelResponse 数据流。

### 为什么需要"后端"这一层抽象?

Harness 需要两种截然不同的"大脑":评测/测试要**确定性**(同一个输入第二次跑必须同样输出),真实使用要**真模型**。如果没有抽象层,主循环里就会到处是 `if mock: ... else: ...`。`ModelBackend` 抽象基类让 Harness 只认接口:

```python
class ModelBackend(ABC):
    @abstractmethod
    def complete(self, messages, tools, temperature) -> ModelResponse:
        """给定消息列表,返回补全结果"""

    def state(self) -> dict:    # 可 checkpoint 的状态
        return {}

    def load_state(self, state):  # 恢复状态(Resume 用)
        pass
```
- `complete()` 是唯一必须实现的方法——接住消息列表与工具 schema,返回统一格式。
- `state()`/`load_state()` 是**容易被忽视但极关键**的一对:**MockBackend 有游标状态**(脚本执行到第几轮),resume 时必须恢复游标,否则断点恢复后会从头重放脚本,后续行为全部错位。默认空实现则让无状态的 LocalOpenAIBackend 不需要关心这件事。

```python
@dataclass
class ModelResponse:
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 0, ...})
```
- **统一返回格式**:不管后端是 mock 还是 HTTP,Harness 只认这个结构。`tool_calls` 里每一项形如 `{"id": "call_0", "name": "file_read", "arguments": "{\"path\": \"a.py\"}"}`——注意 arguments 是**字符串**。

### 5.2 mock.py — 确定性脚本后端

**为什么需要 MockBackend**:
- 评测要求"同一输入必得同一输出"——真实 LLM 有随机性,做不到
- Mock 用脚本精确控制每轮输出,测的是**系统能力**而非模型能力(呼应 0.4 节误区 3)

```python
class MockBackend(ModelBackend):
    def __init__(self, script, seed=42, default_answer="任务已完成。"):
        self.script = list(script or [])
        self._turn = 0          # 脚本游标
        self._call_seq = 0      # 工具调用 ID 计数器

    def state(self) -> dict:
        return {"turn": self._turn, "call_seq": self._call_seq}

    def load_state(self, state):
        self._turn = int(state.get("turn", self._turn))
        self._call_seq = int(state.get("call_seq", self._call_seq))
```
- `state()`/`load_state()` 保存的是**游标位置**——resume 时从正确位置继续,而非从头重放

```python
    def complete(self, messages, tools, temperature):
        if self._turn < len(self.script):
            entry = self.script[self._turn]
        else:
            entry = {"content": self.default_answer}  # 脚本用尽兜底
        self._turn += 1
        ...
```
- 脚本用尽后返回默认终答,避免 Harness 空转——同时它意味着:**脚本写短了不会报错,只会"提前完成任务"**,测试时要核对步数。

**脚本格式**(与真实模型的 tool-calling 行为同构):
```python
script = [
    {"tool_calls": [{"name": "file_read", "arguments": {"path": "a.py"}}]},
    {"content": "分析完成,结论是..."}
]
```
每一轮要么发起工具调用,要么给出终答文本——与真模型的两条出路完全对应,所以用 Mock 写出的评测轨迹可以平滑迁移到真模型。

**学习要点**:
- `from_recipe()` 工厂方法:把"步骤列表"转成"脚本"——便捷构造
- MockBackend 是整个评测体系的**基石**,没有它就没有确定性

### 5.3 local_openai.py — 本地 OpenAI 兼容后端

**设计约束**:全部 localhost,零额外依赖(用 urllib 不用 requests)。

```python
class LocalOpenAIBackend(ModelBackend):
    def complete(self, messages, tools, temperature):
        payload = {
            "model": self.model,
            "messages": [m.to_openai() if hasattr(m, "to_openai") else m for m in messages],
            "temperature": ...,
        }
        if tools:
            payload["tools"] = tools_to_openai(tools)

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        ...
        return self._parse(body)
```
- URL 兼容逻辑:`.../v1` → 补 `/chat/completions`,容错用户填的 base_url 格式(Ollama 默认 `http://127.0.0.1:11434/v1`,llama.cpp 通常 8080,vLLM 8000)

```python
    def _parse(self, body):
        ...
        for tc in raw_calls:
            arguments_str = fn.get("arguments") or "{}"
            tool_calls.append({
                "id": ..., "name": ..., "arguments": arguments_str  # 保持字符串!
            })
```
- **arguments 保持 JSON 字符串**:OpenAI 兼容格式要求 arguments 是字符串,harness 在执行时自行 `json.loads()` 解析(第 8 站 `_execute_tools`)。Mock 与真实后端在这里保持一致。

**学习要点**:
- 用标准库 urllib 而非 requests:**零额外依赖**,核心运行时只需 PyYAML
- 内置重试与指数退避(max_retries/backoff_base/backoff_cap,见附录 B)包装网络抖动;`ConnectionError` 包装成可读提示

**▶ 动手示例 5-1:用 MockBackend 手写一个两步 Agent 循环**(已验证——这就是 Harness 主循环的"裸版",第 8 站会看到完整版)

```python
import json, tempfile
from mycoder.config import Config
from mycoder.context import ContextManager
from mycoder.state import Message
from mycoder.models import MockBackend
from mycoder.tools import Workspace

cfg = Config()
ctx = ContextManager(cfg)
ctx.set_task("查看 greeting.txt 的当前内容", ["greeting.txt"])

ws = Workspace(tempfile.mkdtemp())
ws.write_text("greeting.txt", "Hello, World!")

backend = MockBackend(script=[
    {"tool_calls": [{"name": "file_read", "arguments": {"path": "greeting.txt"}}]},
    {"content": "分析完成:greeting.txt 当前内容是 Hello, World!"},
])

# 第 1 步:模型发起工具调用
resp = backend.complete(ctx.assemble(), [])
print("模型输出 tool_calls:", json.dumps(resp.tool_calls, ensure_ascii=False))
# 把工具结果回填为一轮对话(真实项目里由 harness 的安全链+工具执行完成)
tool = ws.read_text("greeting.txt")
ctx.append_turn(Message("assistant", resp.content, tool_calls=resp.tool_calls or None),
                [Message("tool", f"# greeting.txt\n{tool}", name="file_read",
                         tool_call_id=resp.tool_calls[0]["id"])])

# 第 2 步:模型看到工具结果,给出终答
resp2 = backend.complete(ctx.assemble(), [])
print("模型终答:", resp2.content)
print("裁剪信息:", ctx.last_prune)
```

真实输出:
```
模型输出 tool_calls: [{"name": "file_read", "arguments": {"path": "greeting.txt"}, "id": "call_0"}]
模型终答: 分析完成:greeting.txt 当前内容是 Hello, World!
裁剪信息: PruneInfo(before_tokens=188, after_tokens=188, pruned=False, strategies=[])
```

**✍ 练习**
- 基础:把示例脚本改成 3 轮(先 file_read,再 file_write 写入新内容,最后终答),打印每轮 `backend.state()` 观察游标推进。
- 基础:用 `MockBackend.from_recipe(...)` 改写同一脚本,对比两种构造方式。
- 进阶:保存 `state()` 到字典 → 新建一个 MockBackend → `load_state()` → 继续调用,验证它能从第 3 轮(而非第 1 轮)继续。这正是断点恢复对后端的要求。

**⚠ 易错点**
- `arguments` 一律是 JSON **字符串**;自己解析时记得 `json.loads`,解析失败按 `{}` 处理(harness 的容错行为)。
- Mock 脚本用尽**不报错**,静默返回 `default_answer`——如果测试里步数对不上,先检查脚本是否写短了。
- LocalOpenAI 后端连不上时先确认服务在跑:`curl http://127.0.0.1:11434/v1/models`(Ollama);`model` 名必须与 `ollama list` 里的名字完全一致。

**☑ 自测清单**
- ☑ 我能解释 `state()/load_state()` 为什么存在于基类而不是 Mock 的私事;
- ☑ 我能手写一个两轮 Mock 脚本并说清每轮消息流的形态;
- ☑ 我知道为什么 `arguments` 全链路保持字符串。

---

## 第 6 章 · 第 3 站 工具框架:tools/

> **本站学习目标**:掌握 Tool 基类/注册表/依赖注入;吃透沙箱的四层路径防护;了解 7 个工具各自的设计要点。
> **前置知识**:第 0 章 ④⑧;JSON Schema 基础(只需懂 type/required/enum)。

### 为什么工具要先讲框架再讲实现?

Agent 的能力上限 = 模型上限 + 工具上限。工具系统要回答三个问题:**怎么声明**(让模型看懂)、**怎么执行**(让程序调用)、**怎么约束**(让调用安全)。`tools/base.py` 回答前两个,`sandbox.py` 铺第三个的底座,7 个具体工具则是"填空题"。

### 6.1 base.py — Tool 基类 + Registry

**设计原则**:工具只管"纯业务",安全交给 safety 层(呼应哲学二)。

```python
SAFE = "safe"    # 只读,无需审批
WARN = "warn"    # 写操作,告警
HITL = "hitl"    # 高风险,必须人工审批

class Tool(ABC):
    name: str
    description: str
    parameters: dict    # JSON Schema
    danger: str = SAFE

    @abstractmethod
    def execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        """执行业务逻辑(参数已经过安全层校验)"""
```
- `danger` 等级决定 HITL 是否需要审批——**声明式安全**:工具自己声明风险等级,审批策略由外部配置。新增工具只需 3 行声明 + 1 个 execute,安全防护自动到位。

```python
@dataclass
class ToolContext:
    workspace: Any    # 沙箱工作区
    memory: Any       # 结构化记忆(可空)
    config: Any       # 全局 Config
```
- **依赖注入**:工具不直接 import 全局对象,由 harness 通过 ToolContext 注入——单测里可以塞一个临时 Workspace/假 memory,完全隔离。

```python
class ToolRegistry:
    def register(self, tool): ...
    def get(self, name): ...
    def schemas(self): return [t.as_openai_schema() for t in self.all()]
```
- `schemas()` 批量导出 OpenAI tools 参数格式,送给模型后端——模型"看得见哪些工具"完全由注册表决定。

### 6.2 sandbox.py — 工作区沙箱

**安全关键点**:路径逃逸防护(4 层):

```python
class Workspace:
    def resolve(self, path) -> Path:
        p = Path(path)
        if p.is_absolute():
            if not self.allow_absolute:
                raise PathEscapeError(...)  # 1. 拒绝绝对路径
            candidate = p.resolve()
        else:
            candidate = (self.root / p).resolve()  # 2. 拼接 + resolve 展开 ../ 和符号链接

        # 3. commonpath 断言最终路径在 root 之内
        common = os.path.commonpath([str(self.root), str(candidate)])
        if common != str(self.root):
            raise PathEscapeError(...)  # 4. 双保险拦截
        return candidate
```

**【为什么】这四层一个都不能省:**
1. 绝对路径是最直接的逃逸(`C:\Windows\...`),默认整类拒绝;
2. `resolve()` 展开 `..` 和符号链接——不展开的话 `../../etc/passwd` 只是两个字符的组合,字符串层面根本看不出来恶意;符号链接更是"文件在界内、指向界外"的隐藏通道;
3. **为什么用 commonpath 而非 startswith**:`/root_evil` 会匹配 `startswith("/root")` 但不匹配 `commonpath`——前缀匹配是经典安全漏洞;
4. 双保险:即使未来有人改动前两层,最后一道断言仍然兜底。

```python
    def snapshot(self) -> dict[str, str]:
        """返回 {相对路径: sha256}"""
        for f in self._iter_safe():
            out[str(f.relative_to(self.root))] = sha256_file(f)
        return out
```
- `snapshot()` 是**漂移识别的数据源**:checkpoint 时存指纹,resume 时比对(第 7 站)
- 排除隐藏目录(`.git`/`.pytest_cache`)和 `__pycache__`——避免指纹被无关文件干扰

**学习要点**:沙箱不暴露裸文件句柄,只暴露受控原语(`read_text`/`write_text`/`list_files`)。所有 I/O 都过 `resolve()`,逃逸无处发生。

### 6.3 file_tools.py — 5 个文件工具

每个工具只做"纯业务",安全(路径隔离/参数校验)交给 safety 层。

```python
class ReadFileTool(Tool):
    parameters = {
        "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer", "minimum": 0},  # ← 范围约束
            "limit": {"type": "integer", "minimum": 1},
        },
        "required": ["path"],
    }
    danger = SAFE

    def execute(self, ctx, path, offset=0, limit=None):
        p = ctx.workspace.resolve(path)  # 安全:路径已隔离
        ...
        return ToolResult(
            output=f"# {path} 共 {len(lines)} 行\n\n{content}",
            meta={"path": ..., "file_hash": sha256_file(p)},  # ← meta 携带哈希
        )
```
- **meta 携带 file_hash**:记忆模块和去重层直接复用,避免二次计算(第 8 站 `_after_tool` 消费)
- 参数 Schema 里的 `minimum` 不是摆设——安全链的 `validate_params` 会真的检查(第 4 站)

```python
class EditFileTool(Tool):
    def execute(self, ctx, path, old_string, new_string, replace_all=False):
        count = text.count(old_string)
        if count == 0:
            return ToolResult(ok=False, error="未找到待替换字符串")
        if count > 1 and not replace_all:
            return ToolResult(ok=False, error="非唯一匹配")
        text = text.replace(old_string, new_string, 1 if not replace_all else -1)
```
- **唯一匹配保护**:防止误替换多处相同字符串——这是"精准编辑"的核心。宁可让模型多指定一点上下文,也不静默改错地方。

### 6.4 shell_tool.py — 受控命令执行

```python
class ShellExecTool(Tool):
    danger = HITL  # ← 最高风险,必须人工审批

    def execute(self, ctx, command, cwd=None, timeout=10):
        workdir = ctx.workspace.resolve(cwd) if cwd else ctx.workspace.root
        proc = subprocess.run(
            command, cwd=str(workdir), shell=True,
            capture_output=True, text=True,
            timeout=min(timeout, 30),  # ← 硬上限 30s
        )
```
- 工作目录锁定在工作区内
- 超时硬上限 30 秒,防止恶意 sleep——**注意:请求参数 timeout 只是"申请",代码里 min(timeout, 30) 才是"批准"**,工具层自己也有兜底,不把安全完全寄托在配置上

### 6.5 memory_tool.py — 记忆查询

```python
class MemoryQueryTool(Tool):
    danger = SAFE

    def execute(self, ctx, query, kind="all"):
        text = ctx.memory.search(query=query, kind=kind)
        return ToolResult(output=text or "(无相关记忆)")
```
- 把结构化记忆**对外开放成工具**:Agent 在 follow-up 阶段直接检索记忆,而非重读文件
- 这是"重复读文件降到 0"的关键工具(与第 6 站的记忆系统、第 9 站的 Layer 3 评测联动)

**▶ 动手示例 6-1:沙箱拦截 + 工具调用**(已验证)

```python
import tempfile
from mycoder.config import Config
from mycoder.tools import Workspace, ToolContext, build_registry
from mycoder.tools.sandbox import PathEscapeError

ws = Workspace(tempfile.mkdtemp())          # 默认 allow_absolute=False
ws.write_text("a.py", "def add(a, b):\n    return a + b\n")

try:
    ws.resolve("../outside.txt")            # 尝试逃逸
except PathEscapeError as e:
    print("逃逸拦截:", e)

reg = build_registry()                       # 标准 7 工具
print("注册的工具:", sorted(t.name for t in reg.all()))

ctx = ToolContext(workspace=ws, memory=None, config=Config())
r = reg.get("file_read").execute(ctx, path="a.py")
print("file_read 输出首行:", r.output.splitlines()[0])
r2 = reg.get("grep_search").execute(ctx, pattern="add", path=".")
print("grep 输出:", r2.output.splitlines()[0])
```

真实输出:
```
逃逸拦截: 路径逃逸被拦截(超出工作区): ../outside.txt
注册的工具: ['file_edit', 'file_list', 'file_read', 'file_write', 'grep_search', 'memory_query', 'shell_exec']
file_read 输出首行: # a.py 共 2 行 (行 0..1)
grep 输出: a.py:1:def add(a, b):
```

**✍ 练习**
- 基础:依次尝试 `ws.resolve("C:/Windows")`、`ws.resolve("a/../../x")`、`ws.resolve("./a.py")`,预测并验证哪个通过、哪个拦截。
- 进阶:写一个 `UpperCaseTool`(把指定文件内容转大写写回),声明 `parameters` Schema 与 `danger=WARN`,注册进自定义 Registry 并调用。注意:execute 里**不要**写任何路径校验代码——调用方安全链负责。
- 进阶(思考题):如果把 `_iter_safe` 里的隐藏目录过滤去掉,`snapshot()` 的漂移检测在第 7 站的场景里可能出现什么误报?

**⚠ 易错点**
- 工具参数路径一律**相对工作区**;模型给出绝对路径会被安全链拦截并回传 `[已拦截]`,这是设计行为不是 bug。
- `file_edit` 的 `old_string` 必须与文件内容**逐字符**一致(含缩进);匹配多处又不传 `replace_all=True` 会报"非唯一匹配"。
- `shell_exec` 是 `danger=HITL`,CLI 交互模式会停下来等你确认;自动化测试里记得配 `allow` 策略的 approver(见第 4 站)。

**☑ 自测清单**
- ☑ 我能背出 7 个工具名并按 SAFE/WARN/HITL 分组;
- ☑ 我能逐层解释 resolve() 的四层防护,并说出 startswith 的反例;
- ☑ 我能说清 ToolContext 依赖注入给测试带来什么好处。

---

## 第 7 章 · 第 4 站 安全边界:safety/

> **本站学习目标**:掌握五步安全链的顺序与各自职责;理解读/写去重的不同语义;掌握四种 HITL 审批策略与脱敏器的应用位置。
> **前置知识**:第 3 站的 `danger` 等级;正则表达式基础。

### 为什么安全是一整条"链"?

回顾哲学二:安全与业务正交。但"正交"不等于"一个函数搞定"——一次工具调用要过的关卡本来就有五类:参数对不对(协议层)、路径越没越界(沙箱层)、命令该不该跑(策略层)、是不是重复劳动(效率层)、要不要人拍板(风险层)。**把它们串成一条固定顺序的链**,任何一环拒绝即短路,后续环节不必再评估——既清晰又高效,还让"为什么拦我"有唯一确定的答案(报错里写明是哪一环)。

### 7.1 guard.py — 五步安全链

**调用链**:

```
schema 校验 → 路径隔离 → shell 白/黑名单 → 去重缓存 → HITL 审批
```

**第 1 步:参数校验**
```python
def validate_params(schema, params) -> list[str]:
    # 必填缺失 / 未知参数 / 类型错误 / enum 越界 / integer 范围(minimum/maximum)
    for key, value in params.items():
        spec = props[key]
        if expect_type and not _type_ok(expect_type, value):
            errors.append(f"类型应为 {expect_type}")
        if "enum" in spec and value not in spec["enum"]:
            errors.append("取值非法")
        if expect_type == "integer" and isinstance(value, int):
            if "minimum" in spec and value < spec["minimum"]:
                errors.append("低于下限")
```
- 轻量 JSON Schema 子集:只实现项目需要的(type/required/enum/minimum/maximum),不引第三方库。**【为什么】** 模型生成的参数不可信——LLM 可能幻觉出不存在的参数、类型错乱、越界值;在进入工具前用 schema 一票否决,工具内部就不必重复校验。

**第 2 步:路径隔离**
```python
    if tool.name in self._PATH_TOOLS:
        for key in ("path", "cwd"):
            if key in params:
                self.workspace.resolve(params[key])  # 抛 PathEscapeError 即拦截
```
- 复用第 3 站的四层沙箱防护。`_PATH_TOOLS` 白名单列出"哪些参数是路径"——新增带路径参数的工具时记得在这里登记。

**第 3 步:Shell 白/黑名单**
```python
    def _check_shell(self, command) -> str | None:
        tokens = command.strip().split()
        base = tokens[0].lower()
        if base not in allow_commands:     # 白名单
            return f"命令不在白名单"
        for pat in deny_patterns:          # 黑名单正则
            if re.search(pat, command):
                return f"命中高危模式"
```
- **双层设计**:白名单管"准入"(默认拒绝一切未声明命令,如 `rm` 根本进不来),黑名单管"组合"(白名单命令拼出危险形态,如 `python -c "import os; os.system(...)"` 里的重定向、`git` 后面接 `rm` 之类,由正则兜底)。默认表见 `config/default.yaml` 的 `safety.shell` 节。
- **【为什么】单靠黑名单不安全**(新花样层出不穷),单靠白名单不够用(白名单命令可组合出危险用法)——两层叠加显著提高绕过成本。

**第 4 步:去重缓存**
```python
    key = self._dedup_key(tool.name, params)
    if key in self._dedup:
        count, last_output = self._dedup[key]
        if tool.danger == HITL or tool.name in ("file_write", "file_edit"):
            self.skipped_repeats += 1     # 写操作重复 → 标记风险
        else:
            self.read_cache_hits += 1      # 读操作重复 → 返回缓存
        return GuardResult(True, cached_output=last_output)
```
- **读去重**:第二次相同 file_read 直接返回缓存,不再读盘——省时间,且结果必然相同(文件没被自己改过)
- **写去重**:不返回缓存(危险),只标记跳过。**【为什么语义不同】** 读操作是幂等的:重放缓存无害且高效。写操作重放同一个"写"可能是灾难(想象模型误把两次不同意图的写发成同参数调用,直接返回旧缓存会让模型以为写成功了)。所以写的重复只"标记 + 计数",把决定权留给上层。

**第 5 步:HITL 审批**
```python
    needs = tool.danger == HITL
    return GuardResult(True, needs_approval=needs, action=action)
```

**HITL 策略**(策略模式,四种 Provider 可插拔):
```python
class AllowAllProvider:  approve() → True   # 测试/无人值守用
class DenyAllProvider:   approve() → False  # 严格模式
class PromptProvider:    stdin 交互 y/n     # CLI 模式
class CallbackProvider:  回调函数决策        # 灵活适配(API/自定义)
```

**学习要点**:
- `GuardResult` 携带 `cached_output`:去重短路时直接回填缓存,调用方无需感知
- 安全检查是**链式的**:任何一步失败就 deny,不继续后续检查

### 7.2 redact.py — 敏感信息脱敏

```python
DEFAULT_PATTERNS = [
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END...", "[REDACTED_PRIVATE_KEY]"),
    (r"(?i)\bsk-[A-Za-z0-9]{16,}\b", "[REDACTED_API_KEY]"),
    (r"\bAKIA[0-9A-Z]{16}\b", "[REDACTED_AWS_KEY]"),
    (r"\bghp_[0-9A-Za-z]{20,}\b", "[REDACTED_GITHUB_TOKEN]"),
    (r"(?i)\b(api_key|password|token)\s*[:=]\s*\S+", r"\1: [REDACTED]"),
    (r"(?i)Bearer\s+[A-Za-z0-9._-]{6,}", "Bearer [REDACTED]"),
]

class Redactor:
    def redact(self, text):
        for regex, repl in self.patterns:
            text = regex.sub(repl, text)
        return text
```
- **应用于三处**:tool output(进上下文前,防敏感值进入模型记忆)、trajectory.jsonl(写盘前)、artifact export(导出前)——日志与工件是常常被忽略的泄露面
- 正则按顺序匹配,靠前优先——PEM 私钥块用 `.*?` 非贪婪匹配首尾,避免"贪吃到最后一个 END"把两段密钥间的正文也吞掉

**▶ 动手示例 7-1:去重缓存与脱敏**(已验证)

```python
import tempfile
from mycoder.config import Config
from mycoder.safety import SafetyGuard, Redactor
from mycoder.tools import Workspace, ReadFileTool

ws = Workspace(tempfile.mkdtemp())
ws.write_text("a.py", "x = 1\n")
guard = SafetyGuard(Config(), ws)
rt = ReadFileTool()

g1 = guard.check(rt, {"path": "a.py"})
print("第一次 check: allowed=%s cached=%s" % (g1.allowed, g1.cached_output is not None))
guard.record_executed(rt, {"path": "a.py"}, "文件内容X")   # 模拟执行后登记

g2 = guard.check(rt, {"path": "a.py"})
print("第二次 check: cached=%s(读去重命中)" % (g2.cached_output is not None))

red = Redactor(enabled=True)
print("脱敏:", red.redact("key: sk-abcdefgh12345678, password=hunter2"))
```

真实输出:
```
第一次 check: allowed=True cached=False
第二次 check: cached=True(读去重命中)
脱敏: key: [REDACTED_API_KEY], password= [REDACTED]
```

**✍ 练习**
- 基础:对同一 `(tool, params)` 先 `check` → `record_executed` → 再 `check`,打印两次 `GuardResult` 的差异;换 `WriteFileTool` 重复实验,观察写去重**不返回缓存**、只计数。
- 进阶:在配置里给 `safety.shell.deny_patterns` 加一条 `r"git\s+push.*--force"`,然后用 ShellExecTool + `deny` 审批策略验证 `git push --force` 被拦、`git status` 放行。
- 进阶:实现一个 `LoggingApprovalProvider`(打印审批请求并返回 True),体会 CallbackProvider 的适配方式。

**⚠ 易错点**
- 去重以 **(工具名, 规范化参数)** 为键:模型第二次读同一文件时拿到的可能是缓存——测试"文件变了内容也变"时,记得文件是被**本任务**改的(harness 写后已更新登记)还是外部改的。
- HITL 默认策略是 `prompt`(交互等待);在脚本/评测里不处理会"卡住",应显式设 `allow`/`deny`(CLI 有 `--hitl-policy` 参数)。
- 正则大小写:`sk-` 模式带 `(?i)`,但替换文本是固定大写标签;自己加模式时注意大小写语义。

**☑ 自测清单**
- ☑ 我能按序默写五步安全链,并说明为什么"去重"放在审批之前;
- ☑ 我能解释读去重与写去重语义差异的原因(幂等性);
- ☑ 我能说出脱敏器作用的三处位置。

---

## 第 8 章 · 第 5 站 上下文治理:context/

> **本站学习目标**:理解启发式 token 估算的取舍;掌握三层递进裁剪算法与"从完整历史全量重算"的设计;能独立解释压缩率从何而来。
> **前置知识**:第 0 章 ①②;第 1 站 Message/Step。

### 8.1 tokens.py — 启发式 Token 估算

**为什么不用真实 tokenizer**:
- 真实 tokenizer 需要模型分词器依赖(tiktoken/transformers),而不同模型的分词器还互不通用
- 评测只需**单调性 + 稳定性**(文本变长 → 估算值变大;同一文本两次估算相同),不需要与某个模型精确对齐

```python
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

def estimate_tokens(text) -> int:
    cjk = len(_CJK_RE.findall(text))     # 中文按字
    other = len(text) - cjk              # 非中文按 4 字符/token
    return cjk + (other + 3) // 4        # +3 向上取整
```
- **中文 1 字 ≈ 1 token**(主流 BPE 分词器对汉字基本一字一 token)
- **英文 4 字符 ≈ 1 token**(英文单词平均约 4~5 字符)

```python
def estimate_messages(messages) -> int:
    for m in messages:
        total += 4 + estimate_tokens(content)  # 每条消息 +4 token 结构开销
```
- `+4` 模拟 OpenAI 的角色/结构固定开销(每条消息的 role/name 等元数据)

**▶ 动手示例 8-1:估算直觉校准**(已验证)

```python
from mycoder.context import estimate_tokens
print(estimate_tokens("你好世界 hello world"))   # 7  = 4 汉字 + ceil(12/4)
print(estimate_tokens("def add(a, b):\n    return a + b"))  # 8
```

### 8.2 summarizer.py — 确定性历史摘要

**为什么需要摘要器**:裁剪旧历史不能直接丢弃(丢信息),要压缩成要点。

```python
class DeterministicSummarizer(Summarizer):
    def summarize_turn(self, step_index, assistant_content, tool_results):
        parts = [f"[步骤 {step_index}]"]
        parts.append("助手结论: " + truncate(assistant_content, 160))
        for name, out in tool_results:
            parts.append(f"- {name}: {truncate(out, 120)}")
        return "\n".join(parts)
```
- **确定性**:保留首句 + 工具名 + 结果首片段,不引入 LLM 随机性——"折叠"后的摘要仍是同一输入的同一输出
- `NoopSummarizer`:折叠时直接丢弃——**对照实验用**,评测摘要收益(第 9 站 Layer 2 可以关掉摘要观察质量差异)
- 另有 `LLMSummarizer`(配置 `context.summarizer: llm`):复用主后端压缩历史,**失败自动回退确定性**——第三方摘要挂了不能拖垮主链路

### 8.3 manager.py — ContextManager 核心

**这是上下文治理的中枢**,算法分 5 步:

```python
def assemble(self) -> list[Message]:
    # 1. 组装 base = system + goal + files + memory_block
    base = self._base_messages()
    before = estimate_messages(base + all_turns)  # 不治理的 token 数

    # 2. fold_old_turns: 保留最近 keep 轮原文,旧的折叠成摘要
    visible = self.raw_turns[-keep:]
    folded = self.raw_turns[:-keep]
    if folded:
        msgs.append(Message("system", "# 历史摘要\n" + self._fold_summary(folded)))

    # 3. drop_stale_turns: 仍超硬限 → 只保留最近 1 轮
    if estimate_messages(msgs) > hard and len(visible) > 1:
        visible = self.raw_turns[-1:]
        folded = self.raw_turns[:-1]

    # 4. truncate_long_content: 硬限额强制收缩
    if estimate_messages(msgs) > hard:
        msgs = self._enforce_budget(msgs, hard)

    # 5. 记录裁剪信息
    self.last_prune = PruneInfo(before, after, pruned, strategies)
```

**【为什么】三层递进(先折叠、再丢弃、最后截断)而不是一步到位?** 三种手段在"保信息"与"压 token"上的权衡不同:折叠保留要点(信息损失小、压缩中等)→ 只保留最近一轮(信息损失大、压缩强)→ 截断超长内容(针对"单条过大"而非"历史太多"的病根)。**按代价从小到大依次启用**,能用温和手段解决就不动用激进手段;同时 `strategies` 列表记录实际用了哪几档,评测时能分析行为。

**`_enforce_budget` 算法**:
```python
def _enforce_budget(self, msgs, hard):
    # 先截断超长内容(>max_file_content_chars)
    for m in msgs:
        if len(m.content) > cap:
            m.content = truncate(m.content, cap)
    # 反复把最长消息缩到 60%,直到达标
    while estimate_messages(msgs) > hard:
        largest = max(candidates, key=lambda m: len(m.content))
        largest.content = truncate(largest.content, max(40, int(len * 0.6)))
```
- **确定性收缩**:总是缩最长消息、缩到 60%——同一输入必得同一输出(若是"随机挑一条缩",评测就无法复现)

**关键设计(哲学三的落地)**:
```python
    msgs.extend(copy.deepcopy(self._flatten(visible)))  # ← 深拷贝!
```
- **深拷贝裁剪**:绝不改动 `raw_turns` 原始历史,保证可重放

**压缩率**:
```python
@property
def ratio(self) -> float:
    return max(0.0, 1.0 - self.after_tokens / self.before_tokens)
```

**【为什么】每次都从完整历史重算,不做增量折叠?** 增量折叠("已经折叠过的就不再管")看似高效,但会引入**状态漂移**:折叠结果本身成为状态,一旦哪一步出偏差,后续全部放大;且历史一旦被增量处理过,"裁剪前 token"就再也算不回来了。全量重算的成本 O(历史长度) 在本项目的任务尺度下完全可接受,换来的是绝对的确定性与可重放。

**▶ 动手示例 8-2:亲手触发三层裁剪**(已验证;完整 15 轮版请跑 `examples/context_demo.py`,真实输出见第 2 章第 3 步)

```python
from mycoder.config import Config
from mycoder.context import ContextManager
from mycoder.state import Message

cfg = Config()
cfg.set("context.hard_limit_tokens", 6000)
cfg.set("context.keep_last_turns", 6)
ctx = ContextManager(cfg)
ctx.set_task("分析大型文件", ["giant_test.py"])

for i in range(15):   # 每轮塞 ~750 token,制造膨胀
    ctx.append_turn(Message("assistant", f"第 {i} 轮: " + "x" * 1500),
                    [Message("tool", "结果 " + "y" * 1500, name="file_read")])

msgs = ctx.assemble()
print("裁剪前:", ctx.last_prune.before_tokens, "token")
print("裁剪后:", ctx.last_prune.after_tokens, "token")
print("压缩率: %.0f%%" % (ctx.last_prune.ratio * 100))
print("策略:", ctx.last_prune.strategies)
```

真实输出:
```
裁剪前: 11623 token
裁剪后: 5498 token
压缩率: 53%
策略: ['fold_old_turns']
```

注意只触发了第一档:折叠 9 轮旧历史后已降到硬限以内,**后两档不会启用**——这正是"按代价从小到大依次启用"的体现。把 `keep_last_turns` 调大或 `hard_limit_tokens` 调小(见练习),就能亲眼看到第二、三档登场。

**✍ 练习**
- 基础:示例 8-2 中把 `keep_last_turns` 依次改为 1 / 6 / 14,记录三种情况下出现的策略组合,解释差异。
- 进阶:实现一个自定义 Summarizer(如"只保留工具名清单,丢弃助手文本"),传给 `ContextManager(config, summarizer=...)`,对比压缩率与摘要内容——这正是 NoopSummarizer 对照实验的思路。
- 进阶:构造一个**单条**超长工具结果(如 50000 字符),观察 `truncate_long_content` 单独出现;再构造多条中等长度,观察另两档策略。理解"三种病、三种药"。

**⚠ 易错点**
- `budget_tokens`(4000,软预算)与 `hard_limit_tokens`(6000,硬上限)是**两个不同的旋钮**:前者决定何时开始折叠,后者是绝对红线。把前者调到大于后者不会报错,但治理行为会变得费解。
- `assemble()` 返回的消息是**深拷贝**,你可以安全地修改它,但改动不会写回历史——也别指望"改一下返回值影响下一轮"。
- token 估算是启发式:它保证单调与稳定,不保证等于真实模型的 tokenizer 结果;评测比较的是**相对变化**,不要拿估算值当计费依据。

**☑ 自测清单**
- ☑ 我能按序说出三层裁剪策略及其触发条件;
- ☑ 我能解释"全量重算 + 深拷贝"如何共同保证确定性;
- ☑ 我知道 PruneInfo 的四个字段各是什么、ratio 怎么算。

---

## 第 9 章 · 第 6 站 结构化记忆:memory/

> **本站学习目标**:掌握三层记忆的存储模型与持久化;理解"哈希指纹 → 摘要新鲜度 → 不重读"这条收益链路;了解混合检索(substring/vector/hybrid)。
> **前置知识**:第 3 站 meta 携带 file_hash;第 5 站 memory_block 注入位置。

### 为什么记忆要"结构化"而不是全文堆放?

把所有历史原文堆给模型,等于放弃治理(第 5 站的教训)。结构化记忆的思路:**文件级抽象**——一个 5000 行的文件,值得长期记住的是"它定义了哪些函数/类/导入"(几十 token),而不是全文。读取时按需检索,而不是全量背诵。

### 9.1 store.py — 三层存储

| 层级 | 数据结构 | 持久化文件 | 记什么 |
|------|----------|------------|--------|
| 任务摘要 | `TaskRecord` | tasks.json | 目标/状态/结论/关键决策/涉及文件 |
| 文件摘要 | `FileRecord` | files.json | 哈希指纹/摘要/符号(函数类导入)/最近访问 |
| 关联记忆 | relations dict | relations.json | 任务↔文件、任务↔父任务(follow-up)、文件↔文件(依赖) |

**文件摘要提取(确定性)**:
```python
_SYMBOL_RE = re.compile(r"^\s*(def |class |async def |import |from )")

def summarize_file_content(content, max_chars=600):
    lines = content.splitlines()
    head = "\n".join(lines[:8])           # 头 8 行
    symbols = [ln.strip() for ln in lines if _SYMBOL_RE.match(ln)][:20]  # 关键符号
    return summary, symbols
```
- 不用 LLM,用正则提取函数/类/导入行——确定性 + 零成本。**【为什么】** 代码文件的"骨架"(定义了什么)恰好是最规则、最可用正则捕获的信息;LLM 摘要又贵又不确定,对这个场景是杀鸡用牛刀。

**去重关键(收益链路的核心一环)**:
```python
def remember_file(self, path, content, sha256, task_id):
    digest = sha256 or sha256_text(content)
    rec = self.files.get(path)
    if rec is not None and rec.sha256 == digest:
        # 内容未变:摘要仍有效,不重算,不计为"重读"
        rec.last_read_at = now
        return False, rec    # ← 返回 False:没有真正更新
```
- **哈希一致性检查**:内容没变就不重算摘要——这是"重复读文件降到 0"的机制来源。配合第 3 站 meta 里现成的 `file_hash`,连内容哈希都不用重算。

**follow-up 上下文注入**:
```python
def followup_context(self, task_id, parent_task_id, max_files=12):
    pid = parent_task_id or self.parent_of(task_id)
    if pid in self.tasks:
        blocks.append(f"- 父任务 {pid}: {truncate(t.summary, 200)}")
        for f in self.relations["task_files"].get(pid, []):
            rec = self.files.get(f)
            blocks.append(f"- 文件 {f}: {truncate(rec.summary, 160)}")
```
- follow-up 任务自动拿到**父任务的文件摘要**,不必重读文件——注入点在第 8 站主循环 `_run` 开头(作为 `memory_block` 进 system 消息)

**检索**:
```python
def search(self, query, kind="all", mode=None):
    # kind="task": 搜任务 ID/goal/summary
    # kind="file": 搜文件路径/摘要
    # kind="relation": 搜关联
    # kind="all": 三层都搜
    # mode: substring(默认)/ vector / hybrid,未指定时用配置
```

### 9.2 retriever.py — 检索包装

```python
class MemoryRetriever:
    def should_re_read(self, path, digest) -> bool:
        """是否需要真正重读:已有与 digest 一致的摘要时返回 False"""
        return not self.memory.has_fresh_summary(path, digest)
```
- 这是 harness 判断"要不要重读文件"的入口:**摘要的新鲜度 = 摘要对应的 SHA-256 与当前文件一致**

### 9.3 vectors.py — 三种检索模式(可选深入)

```python
class EmbeddingProvider(ABC):        # 嵌入器抽象
class HashingEmbedder(...):          # 零依赖:字符 n-gram 哈希到定长向量
class FastEmbedEmbedder(...):        # 真实神经嵌入 bge-small(需 pip install fastembed)
class VectorIndex: ...               # 余弦相似度检索
class BM25: ...                      # 经典词频检索
class HybridRetriever: ...           # 向量 cosine + BM25 加权融合(alpha 可调)
```
- **【为什么】默认用 HashingEmbedder?** 零依赖、零下载、结果可复现;字符 n-gram 哈希对"同义改写"有弱语义效果(共享字符片段),对精确匹配天然友好。Layer 5 实测它已能把同义改写查询的 recall@3 从 28%(纯 substring)拉到 63%;要更进一步再升级 FastEmbed(见第 12 章 Layer 7)。

**▶ 动手示例 9-1:沉淀 → 检索 → follow-up 注入**(已验证)

```python
import tempfile
from mycoder.memory import StructuredMemory
from mycoder.tools import Workspace

ws = Workspace(tempfile.mkdtemp())
ws.write_text("a.py", "def add(a, b):\n    return a + b\n")

mem = StructuredMemory(tempfile.mkdtemp())
mem.remember_file("a.py", ws.read_text("a.py"), task_id="t1")
mem.remember_task("t1", "分析 a.py 的函数", status="completed", files=["a.py"])
mem.save()

print("检索 'add':")
print(mem.search("add")[:80])
print("follow-up 注入块:")
print(mem.followup_context("t2", "t1")[:120])
rec = mem.get_file("a.py")
print("摘要新鲜(哈希一致):", mem.has_fresh_summary("a.py", rec.sha256))
```

真实输出(节选):
```
检索 'add':
[文件] a.py |   摘要: def add(a, b): |     return a + b |   符号: def ad...
follow-up 注入块:
# 结构化记忆(来自之前的任务) | - 父任务 t1: 分析 a.py 的函数 | - 文件 a.py: ...
摘要新鲜(哈希一致): True
```

**✍ 练习**
- 基础:示例 9-1 之后修改 `a.py` 内容再次 `remember_file`,确认返回 `True`(真更新)且摘要变化;不改内容重跑,确认返回 `False`。
- 进阶:配置 `memory.retrieval.mode: hybrid` 后构造两个文件(`auth.py` 含 login/token,`math_utils.py` 含矩阵运算),用 `search("用户登录凭证", mode="substring")` 与 `mode="hybrid"` 对比排序差异。
- 进阶:读 `memory/store.py` 的 `stats()`,打印你实验后的记忆统计(任务数/文件数/关系数)。

**⚠ 易错点**
- 记忆默认持久化在 `.mycoder/memory/`;单测/实验请把 `memory.root` 指到临时目录,避免污染下一次实验。
- follow-up 注入需要**两个条件同时满足**:任务带 `follow_up_of` 字段 且 配置 `memory.followup_inject_summaries: true`。少了任何一个,"记忆收益评测"都会退化。
- `search()` 返回的是**格式化文本块**(给模型看的),不是结构化列表;要程序化消费请用 `get_task()/get_file()/rank()`。

**☑ 自测清单**
- ☑ 我能画出三层记忆与其持久化文件的对应关系;
- ☑ 我能完整复述"重复读文件 2→0"的机制链(自动沉淀 → 哈希去重 → follow-up 注入 / should_re_read);
- ☑ 我能说出 substring/vector/hybrid 三种模式各自的适用场景。

---

## 第 10 章 · 第 7 站 断点恢复:checkpoint/

> **本站学习目标**:掌握快照的自包含内容;掌握漂移识别的集合运算与精度来源。
> **前置知识**:第 1 站原子写;第 5 站 raw_turns;第 3 站 snapshot()。

### 为什么"中断可恢复"对 Agent 是一等公民需求?

长任务跑几十步、每步一次模型调用,几十分钟很常见——网络抖动、进程被杀、人工暂停都可能发生。没有断点,中断意味着全部重来(时间与 token 双重浪费)。MyCoder 把 checkpoint 做成**自包含快照**:只凭快照本身 + 当前工作区,就能在全新进程里续跑。

### 10.1 store.py — 断点存储

```python
class CheckpointStore:
    def save(self, task_id, snapshot):
        atomic_write(self.path(task_id), json.dumps(snapshot, ...))

    def load(self, task_id) -> dict | None:
        return json.loads(p.read_text())
```
- 简单的 JSON 落盘 + 原子写(第 1 站);"写到一半断电不留半截快照"在这里兑现
- **snapshot 自包含**(由 harness `_checkpoint()` 组装,字段见第 11 章):任务定义 + 上下文历史 + 工作区指纹 + 指标 + 后端状态

**何时落盘?** 三个触发点(配置 `checkpoint.*`):每 `interval_steps`(默认 4)步、上下文裁剪发生前(`on_prune`,裁剪是有损操作,先留后路)、任务终态(`final`)。**【为什么裁剪前必须存?】** 原始历史是唯一不可再生资产——工作区文件可以从磁盘重取,历史丢了就真的丢了。

### 10.2 drift.py — 漂移识别

**场景**:任务中断期间,人(或另一个进程)改了工作区。恢复前必须告诉 Agent"世界变了",否则它基于过时认知继续操作会出错。

```python
class WorkspaceDriftDetector:
    @staticmethod
    def compare(before, after) -> DriftReport:
        modified = sorted(k for k in (b_keys & a_keys) if before[k] != after[k])
        added = sorted(a_keys - b_keys)
        deleted = sorted(b_keys - a_keys)
        return DriftReport(modified, added, deleted)
```
- **集合运算**:
  - `modified` = 交集 ∩ 但哈希值不同
  - `added` = after 有 before 没有
  - `deleted` = before 有 after 没有
- **100% 准确**:逐文件 SHA-256 精确比对,不存在误判(内容级比对,不是时间戳/大小这种弱信号)

**▶ 动手示例 10-1:断点存取 + 三类漂移**(已验证)

```python
import tempfile
from mycoder.checkpoint import CheckpointStore, WorkspaceDriftDetector
from mycoder.tools import Workspace

cps = CheckpointStore(tempfile.mkdtemp())
cps.save("t1", {"step_index": 3, "goal": "demo"})
print("load 恢复 step:", cps.load("t1")["step_index"])

ws = Workspace(tempfile.mkdtemp())
ws.write_text("a.py", "v1"); before = ws.snapshot()
ws.write_text("a.py", "v2")            # 修改
ws.write_text("new.txt", "brand new")  # 新增
report = WorkspaceDriftDetector.compare(before, ws.snapshot())
print("漂移:", report.summary())       # modified=[a.py], added=[new.txt]
```

真实输出:
```
load 恢复 step: 3
漂移: 漂移: 已修改 1 个: a.py; 新增 1 个: new.txt
```

**✍ 练习**
- 基础:示例 10-1 再加一步 `ws` 内删除一个文件,验证 `deleted` 分类;删除后再新建同名但内容不同的文件,确认它出现在 `modified` 而非 `added`。
- 进阶:构造 100 个小文件的工作区,测 `snapshot()` + `compare()` 耗时,评估指纹法的规模上限——想一想:如果工作区有 10 万个文件,这个设计要怎么改?(提示:增量指纹/目录级聚合)

**⚠ 易错点**
- checkpoint 键是 `task_id`:同一 task_id 反复保存是**覆盖**语义(最新快照 wins),想留多个时点要自己换 ID 或改存储。
- 漂移报告是"报告"不是"拦截":发现漂移后继续跑还是先停下,由上层(及配置 `checkpoint.detect_drift`)决定。
- `load()` 找不到断点返回 `None` 而非抛异常;`resume()` 会转成 status=error 的 RunResult。

**☑ 自测清单**
- ☑ 我能列举快照的五大组成部分,并解释"自包含"为什么重要;
- ☑ 我能说出三个 checkpoint 触发点,并解释为什么裁剪前必须落盘;
- ☑ 我能用集合运算复述 modified/added/deleted 的定义。

---

## 第 11 章 · 第 8 站 主循环:agent/harness.py(核心站)

> **本站学习目标**:看懂装配工厂如何把八个模块接成一台机器;逐行理解主循环的六步;掌握工具执行的完整安全路径与 resume 流程。
> **前置知识**:前七站全部内容。这是交汇点,建议读完后重读一遍 3.3 的模块图。

这是整个项目的中枢,把所有模块编排成可中断、可恢复、可复盘的主循环。主循环本身不关心模型是不是真的"聪明",它只保证:**确定性、可观测、可恢复**。

### 11.1 装配工厂

```python
@classmethod
def build(cls, config, backend=None, workspace_root=None, ...):
    backend = backend or create_backend(config)
    ws = Workspace(ws_root, ...)
    registry = build_registry()           # 7 个工具
    memory = StructuredMemory(...)
    guard = SafetyGuard(config, ws, ...)
    cp = CheckpointStore(...)
    am = ArtifactManager(...)
    return cls(config, backend, ws, registry, memory, guard, cp, am, ...)
```
- 一行 `AgentHarness.build(config)` 装配所有组件——**【为什么】** 手工装配八个组件既啰嗦又容易漏(漏掉 redactor 之类不报错、只是默默不生效),工厂方法把"正确的组装方式"固化;同时所有参数都可注入覆盖,测试随时换成 Mock/临时目录。
- 细节:`build()` 还会把 `Tracer`(可观测性)挂成默认事件消费者;若调用方传入自己的 `on_event`(如 API 的 SSE 总线),**两者都收到事件**(`_dispatch` 分发)。

### 11.2 主循环 _run()

```python
def _run(self, task, start_step, metrics, stop_after_steps, drift, reason):
    # follow-up 记忆注入
    if task.follow_up_of and memory.followup_inject_summaries:
        mem_block = self.memory.followup_context(...)

    for step_idx in range(start_step, max_steps):
        # 1. 组装 + 裁剪上下文
        messages = self.context.assemble()
        # 2. 调用模型
        resp = self.backend.complete(messages, self.registry.schemas())
        # 3. 终答判断(空终答温和重问)
        if not resp.tool_calls:
            nudge = (not (resp.content or "").strip()
                     and empty_nudges < max_empty_nudges)
            if nudge:
                empty_nudges += 1
                self.context.append_turn(
                    assistant, [], user=Message("user", _EMPTY_ANSWER_REMINDER))
                continue
            final_answer = resp.content
            break
        # 4. 执行工具
        calls, tool_msgs = self._execute_tools(resp.tool_calls)
        self.context.append_turn(assistant, tool_msgs)
        # 5. 指标 & checkpoint
        if self.context.last_prune.pruned:
            self._checkpoint(task, step_idx + 1, reason="prune")
```

**【为什么】空终答要"温和重问"而不直接结束?** 小模型有个典型失败模式:返回"无工具调用 + 空文本"的空转回复(什么都没说就交卷)。直接终止会把"交白卷"静默当成功;直接报错又过于激进(模型可能下一轮就好了)。折中:注入一条用户提醒(`_EMPTY_ANSWER_REMINDER`:对文件的修改必须通过 file_edit/file_write 落盘),给模型**一次**补交机会(`harness.empty_answer_nudges`,默认 1,0 = 关闭),再空就如实终答。每次重问都记录进轨迹(`empty_answer_nudge` 事件),可观测不静默。

**中断控制**:`stop_after_steps` 让循环跑满 N 步后以 `status="interrupted"` 落盘退出——这是评测 Layer 4 制造"中断"的钩子,也是真实使用里手动暂停的机制。

**循环正常耗尽** `max_steps` 后以 `status="max_steps"` 结束——防死循环的最后一道闸。

**异常兜底**:任何异常被捕获 → `status="error"` → **仍然落盘 checkpoint(reason="error")**——崩溃时刻的状态是排障的金矿,不能丢。

### 11.3 工具执行 _execute_tools()

```python
def _execute_tools(self, raw_calls):
    for tc in raw_calls[:max_calls]:          # 单轮最多 8 个工具调用
        # 解析 arguments(JSON 字符串 → dict,失败容错为 {})
        params = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        # 安全链 + 执行
        output, meta = self._run_one_tool(tool, params, ctx)
        # 脱敏(进上下文前)
        output = self.redactor.redact(output)
```
- `max_tool_calls_per_turn`(默认 8)防止单轮工具风暴;`tool_msgs` 以 `tool` 角色消息回填,供模型下一轮观察。

### 11.4 单次工具调用 _run_one_tool()

```python
def _run_one_tool(self, tool, params, ctx):
    gr = self.guard.check(tool, params)       # 1. 安全链(五步)
    if not gr.allowed:
        return f"[已拦截] {gr.reason}", meta
    if gr.needs_approval:
        if not self.guard.approve(gr.action):  # 2. HITL 审批
            return "[已拦截] 审批未通过", meta
    if gr.cached_output is not None:           # 3. 去重短路
        return gr.cached_output, meta
    result = tool.execute(ctx, **params)       # 4. 真正执行
    self.guard.record_executed(tool, params, output)  # 5. 登记去重
    self._after_tool(tool.name, result.meta)   # 6. 记忆沉淀
    return self.redactor.redact(output), meta  # 7. 脱敏
```
- **七步顺序不可乱**:先安全后执行;先登记去重再沉淀记忆(都只在 `result.ok` 时);最后脱敏——保证"进上下文/进轨迹/进记忆的每一份文本都已是脱敏后的"。
- 工具抛异常被捕获为 `[工具异常] ...` 回传给模型——**单个工具失败不会拖垮整个任务**,模型有机会看到错误并换路子(这正是 Agent 的容错优势)。

### 11.5 记忆沉淀 _after_tool()

```python
def _after_tool(self, name, tool_meta):
    if name in self._FILE_TOOLS and memory.auto_remember_files:
        path = tool_meta.get("path")
        content = self.workspace.read_text(path)
        digest = tool_meta.get("file_hash")
        updated, _ = self.memory.remember_file(
            path=path, content=content, sha256=digest, task_id=self.current_task_id)
        if updated:
            self.metrics.files_remembered += 1
```
- **自动沉淀**:每次读/写/改文件后,自动把文件摘要存入记忆——Agent 下次不用重读。这里消费的 `file_hash` 正是第 3 站 ReadFileTool 塞进 meta 的,全链无重复计算。

### 11.6 Resume 流程

```python
def resume(self, task_id):
    cp = self.checkpoint.load(task_id)
    # 1. 工作区漂移识别
    before = cp.get("workspace_fingerprint", {})
    after = self.workspace.snapshot()
    drift = WorkspaceDriftDetector.compare(before, after)
    # 2. 恢复上下文
    self.backend.load_state(cp.get("backend_state", {}))  # ← 恢复 Mock 游标!
    self.context.raw_turns = [_turn_from_dict(t) for t in ctx.get("raw_turns", [])]
    # 3. 继续执行
    return self._run(task, start_step=cp.get("step_index", 0), ...)
```

**学习要点**:
- `start_step` 从 checkpoint 恢复,不会从头重跑
- `backend.load_state()` 恢复 Mock 游标,脚本从正确位置继续(第 5 站伏笔在此兑现)
- 漂移检测在 resume 开头,Agent 知道工作区是否被外部改动
- metrics 也从快照恢复(`_metrics_restore`)——恢复后的运行指标是**累计**口径,报告才完整

**▶ 动手示例 11-1:完整 Harness 离线跑一个任务**(已验证,~15 行,不依赖任何外部服务)

```python
import tempfile
from mycoder.config import Config
from mycoder.agent.harness import AgentHarness
from mycoder.models import MockBackend
from mycoder.state import TaskInput

tmp = tempfile.mkdtemp()
cfg = Config()
cfg.set("artifacts.root", tmp + "/artifacts")     # 工件/记忆/断点全部重定向,
cfg.set("memory.root", tmp + "/memory")           # 不污染仓库 .mycoder/
cfg.set("checkpoint.root", tmp + "/checkpoints")
cfg.set("logging.file", tmp + "/harness.log")
cfg.set("safety.hitl_policy", "allow")

backend = MockBackend(script=[
    {"tool_calls": [{"name": "file_write",
                     "arguments": {"path": "hello.py",
                                   "content": "def greet(name):\n    return f'你好, {name}!'\n"}}]},
    {"content": "已创建 hello.py,定义了 greet 函数。任务完成。"},
])
harness = AgentHarness.build(cfg, backend=backend, workspace_root=tmp,
                             memory_root=tmp + "/memory")
harness.workspace.write_text("README.md", "# demo\n")

result = harness.run(TaskInput(task_id="demo-001", goal="创建 hello.py,提供 greet 函数"))
print("status:", result.status)
print("final_answer:", result.final_answer)
print("steps:", len(result.steps), "| tool_calls:", result.metrics.get("tool_calls"))
import os
print("artifacts:", sorted(os.listdir(tmp + "/artifacts/demo-001")))
```

真实输出:
```
status: completed
final_answer: 已创建 hello.py,定义了 greet 函数。任务完成。
steps: 2 | tool_calls: 1
artifacts: ['checkpoint.json', 'metrics.json', 'report.md', 'trace.json', 'trajectory.jsonl']
```

跑完去看 `tmp/artifacts/demo-001/trajectory.jsonl`:每行一个 JSON 事件(task_start/step/tool_call/task_end),这就是"可复盘"的字面含义;`report.md` 是人读的汇总;`trace.json` 是带层级与耗时的链路追踪。

**✍ 练习**
- 基础:示例 11-1 中把脚本改为"先 file_read README.md 再终答",跑完后打开 trajectory.jsonl,找到那条 file_read 的 `tool_call` 记录并核对 `meta` 里的 `file_hash`。
- 进阶:`harness.run(task, stop_after_steps=1)` 中断 → 打印 `result.status`(应为 interrupted)→ 换一个新 MockBackend(同一脚本)→ `harness.resume("demo-001")`,验证第二个工具调用从脚本第 2 轮(而非第 1 轮)继续——对照第 10 章的 load_state。
- 进阶:构造一个"读去重"场景:脚本连续两轮用相同参数 file_read 同一文件,跑完后打印 `result.metrics["read_cache_hits"]` 与 `read_calls`,解释为什么 2 次调用只有 1 次 `read_calls`。

**⚠ 易错点**
- 示例若**不**重定向 artifacts/memory/checkpoint 根,会在仓库当前目录生成 `.mycoder/`——评测与实验请养成临时目录习惯。
- `resume` 前提是 checkpoint 存在;`AgentHarness.build` 与当初 run 时要用**同一个** `checkpoint.root`,否则"找不到断点"。
- Mock 脚本两轮都写终答、不发起工具调用 → 任务 1 步就 completed,`tool_calls=0`——不是 bug,是脚本决定的。
- 主循环的"步"计数与工具调用数不是一回事:一步可含多个工具调用(上限 8),空终答重问也会占一步。

**☑ 自测清单**
- ☑ 我能不看书写出主循环六步(注入→组装→调用→终答判断→执行→指标/断点);
- ☑ 我能解释空终答温和重问的动机与实现(注入 user 提醒 + 计数上限);
- ☑ 我能按序说出 _run_one_tool 的七步,并指出哪两步只在成功时执行;
- ☑ 我能独立完成"中断 → resume"实验并解释 Mock 游标为什么没乱。

---

## 第 12 章 · 第 9 站 评测闭环:eval/

> **本站学习目标**:理解五层离线评测 + Layer 6/6b/7 的分工;掌握"对照实验"的实验设计方法;学会阅读与解释评测报告。
> **前置知识**:第 0 章 ⑩(对照实验);第 8 站(各机制如何被度量)。

### 12.1 为什么要评测?评什么?

"我加了个功能,感觉好了"不是工程语言。**评测定量化**:收益是多少、代价是多少、边界在哪。本项目评测设计的两个基本原则:

1. **用 Mock 冻结模型变量**:五层离线评测全部跑在确定性脚本上——分数变化只能来自系统改动;
2. **一切结论皆对照**:每个 Layer 都是"开关开 vs 关"或"方案 A vs 方案 B"的双臂/三臂设计。

### 12.2 五层离线评测 + 三个按需 suite

```
Layer 1 回归: 运行时稳定性(能完成、工件齐全、断言满足)
Layer 2 上下文: 预算裁剪收益(治理 vs 不治理的 token 差)
Layer 3 记忆: follow-up 重读归零、正确率
Layer 4 恢复: checkpoint/resume + 漂移识别边界
Layer 5 检索: 混合检索召回率(substring/vector/hybrid, recall@3)
```

在离线五层之上还有几个**按需运行**的 suite(需本地模型或下载,不进 pytest):
- **Layer 6 真实任务评测**:Ollama(qwen3.5:2b)端到端执行 + 硬断言 + LLM-as-judge(`--suite real`,demo 脚本 `examples/real_model_demo.py`)
- **Layer 6b 裸模型基线对照**:固定模型与 Layer 6 同一任务集,只改"有没有 harness"——`single_shot`(单次调用,无工具循环)与 `naive_loop`(朴素 tool-calling 循环,无治理/记忆/断点/安全链)两条裸基线臂;存在 Layer 6 报告时自动并排三臂对照,直接度量 harness 的增量价值(`--suite real_baseline`,配置节 `eval.real_baseline`,实现 `mycoder/eval/raw_baseline.py`)
- **Layer 7 嵌入器对照**:FastEmbed bge-small vs 默认 HashingEmbedder 的检索收益对比(`--suite embedder`)

**核心理念**:用同一个确定性 mock 轨迹驱动,唯一变量是 harness 系统开关 → 测的是**系统能力**,不是模型能力。

**benchmark 数据**:26 个手写任务(回归 17/上下文 4/记忆 4/恢复 1,含负例与边界)+ 固定 seed 生成后**冻结入库**的 42 个任务(`benchmarks/tasks.generated.json`,提交进版本控制保证可复现)+ 82 条检索查询。

### 12.3 Layer 2 上下文治理评测(对照实验)

```python
def layer_context(self, tasks):
    for t in ct:
        # A 组:治理(budget=1500,强制折叠)
        rg, _ = self._run(t, wdg, budget=1500)
        # B 组:基线(budget=10_000_000,不治理)
        rb, _ = self._run(t, wdb, budget=10_000_000, keep_turns=1000)
        ratio = 1 - gov_total / base_total
```
- **A/B 对照**:同一任务,唯一变量是 budget → 压缩率就是治理收益

### 12.4 Layer 3 记忆收益评测

```python
def layer_memory(self, tasks):
    for parent in parents:
        self._run(parent, wd)  # 父任务:沉淀文件摘要
        for fo in follows:
            # treatment: 记忆开启 + memory_query 脚本
            rt = self._run(fo, wd, script_field="script", memory_enabled=True)
            # control: 记忆关闭 + file_read 脚本
            rc = self._run(fo, wd, script_field="control_script", memory_enabled=False)
            wt = self._count_reads(rt)  # treatment 的 file_read 次数
            wc = self._count_reads(rc)  # control 的 file_read 次数
```
- **对照变量**:treatment 用 memory_query,control 用 file_read → 重读次数差就是记忆收益(实测 2 → 0)
- 注意实验设计的细节:**两臂脚本不同但任务相同**——"模型选择用什么方式获取信息"本身就是被测变量之一

### 12.5 Layer 4 恢复正确性评测

```python
def layer_resume(self, tasks):
    for k in (1, 2, 3, 4, 5):           # 5 种中断点
        for want_drift in (False, True): # × 有无漂移 = 10 场景
            rg = self._run(t, wd, stop_after=k)  # 中断
            if want_drift:
                self._mutate_workspace(wd, k)    # 外部修改
            rc = self._resume(t, wd)              # 恢复
            got_drift = rc.drift.get("is_drift")
```
- 5×2 全组合矩阵:验证"该报漂移的报了、不该报的没报"(识别 10/10,恢复后完成率 100%)

### 12.6 Layer 5 检索召回评测(benchmarks/retrieval.json + retrieval_extra.json)

```python
def layer_retrieval(self):
    # 数据形态: {"tasks": [{"domain": "r01_auth", "queries": [...]}, ...]}
    # 核心文件 retrieval.json 38 条 + 扩展 retrieval_extra.json 44 条 = 82 条查询,
    # 覆盖 exact(精确)/synonym(同义改写)/distractor(干扰)/empty(空结果) 四类
    for domain in bench["tasks"]:
        for q in domain["queries"]:
            hyb = retriever.search(q["text"], mode="hybrid")
            sub = retriever.search(q["text"], mode="substring")
            # 统计 recall@1/3/5 与 MRR@5,按 kind 分别聚合
```

- **对照变量**:同一查询,`mode="hybrid"`(向量 cosine + BM25 加权) vs `mode="substring"`(字面匹配)
- **82 条实测结论**(默认零依赖 HashingEmbedder):分类通过率 exact 23/23、synonym 29/29、distractor 11/11、empty 19/19;平均 recall@3 substring=28% vs hybrid=63%;MRR@5 substring=0.44 vs hybrid=0.98 —— 字面匹配在"同义改写"场景大幅掉队,混合检索显著占优 → 实证记忆检索需要语义向量
- **Layer 7 延伸对照**:`python -m mycoder eval --suite embedder` 用 FastEmbed bge-small(真实神经嵌入,首次运行需下载模型)替换 HashingEmbedder 再跑同一数据集,量化升级收益

**指标释义**(新手常混):
- **recall@K**:前 K 条结果里"包含了应命中文档"的查询占比——考"找没找到";
- **MRR@5**(Mean Reciprocal Rank):应命中文档排名倒数的均值(排第 1 得 1 分、第 2 得 0.5 分……)——考"找得好不好,排得靠不靠前"。

### 12.7 如何读懂评测报告

`report.md` 按 Layer 分节,每节三要素:**通过率**(如 4/4)、**对照差值**(如 substring 28% vs hybrid 63%)、**结论句**。阅读顺序建议:先看有没有 fail → fail 的去 `.mycoder/eval/` 下对应 JSON 找具体任务 → 对照 `benchmarks/tasks.json` 里该任务的 `expect` 断言字段理解它考什么。`_check_expect` 的断言类型包括:文件存在/内容包含/内容不包含、步数上限、指标阈值等(见 `mycoder/eval/runner.py`)。

**▶ 动手示例 12-1:只跑一层并核对数字**

```bash
.conda/python.exe -m mycoder eval --suite retrieval --output .mycoder/eval
.conda/python.exe -m mycoder eval --suite context  --output .mycoder/eval
# 报告: .mycoder/eval/report.md —— 重点看"recall@3"与"平均压缩率"两行
```

**✍ 练习**
- 基础:分别跑 `--suite memory` 与 `--suite resume`,把报告中的关键数字(重读次数、漂移识别率)抄进笔记,并回溯到第 9/10 站指出对应机制。
- 进阶:改 `EvalRunner.layer_context` 中治理臂 budget 为 800 与 3000 各跑一次 Layer 2,对比压缩率与"预算内完成率"——体会"预算越紧压缩越高、但硬截断风险越大"的权衡。
- 进阶(思考题):为什么 Layer 4 要做 5×2 全组合,而不是各测一次?(提示:中断时点影响快照内容与已写文件集合,边界情况——如第 1 步就中断、最后一步前中断——各有独立风险。)

**⚠ 易错点**
- `--suite real / real_baseline` **不清空**输出目录(两份报告要共存做三臂对照),其余 suite 每次运行会重置输出目录——别把自定义文件放进去。
- Layer 6/6b 需要 Ollama 在本地跑着且模型已拉取;judge 用 2b 小模型曾出现全部打 0 分的不可靠结果——judge 结果要人工抽查,不要只看通过率(项目如实保留这一现象于 `.mycoder/real/real_report.json`)。
- 跑评测会写 `.mycoder/` 与临时工作区,不要在评测输出目录里放个人文件。

**☑ 自测清单**
- ☑ 我能说出五层离线评测各自"固定什么、改变什么、度量什么";
- ☑ 我能解释 recall@K 与 MRR@5 的区别,并说出 82 条查询的四个类别;
- ☑ 我能读懂 report.md 并定位一个失败任务的具体断言。

---

## 第 13 章 · 第 10 站 收尾:cli / api / examples / tests

> **本站学习目标**:掌握全部 CLI 子命令;理解 stdlib/FastAPI 两种 API 实现的取舍与事件流;了解测试套件的组织。
> **前置知识**:第 11 站主循环事件。

### 13.1 CLI (cli.py)

```python
# 子命令:run / resume / serve / eval / benchmark / artifacts / doctor / orchestrate
```
- `run`:运行单个任务(任务文件可携带 `script` 字段 → 自动用 MockBackend 回放;`setup_files` 预置工作区文件)
- `resume`:从断点恢复
- `serve`:启动 localhost API(`--impl stdlib|fastapi`)
- `eval`:运行评测(`--suite all|regression|context|memory|resume|retrieval|real|real_baseline|embedder`)
- `benchmark`:列出内置 benchmark 任务
- `artifacts`:查看/聚合某任务的运行工件
- `doctor`:环境诊断(新手第一步)
- `orchestrate`:把复杂目标分解为子任务并行编排执行(`--goal` / `--max-workers`)

**⚠ 再次强调**:CLI 默认加载**内置默认值**;要用 `config/default.yaml` 必须显式 `--config config/default.yaml`(第 1 章易错点)。

### 13.2 API

**标准库服务 (api/server.py)**

```python
# ThreadingHTTPServer,127.0.0.1:8910
# GET /health → {"service":"mycoder","version":"0.1"}
# POST /run → 启动任务
# POST /resume → 恢复任务
```

**FastAPI + SSE 服务 (api/event_bus.py + api/fastapi_server.py)**

```python
# POST /api/run                  → 启动任务,返回 task_id;可选 backend 字段按请求选后端
# POST /api/compare              → 一键双跑对照:同目标自动提交 mock+ollama 两臂(共享 compare_group)
# GET  /api/run/{id}             → 任务状态/结果快照(含 backend/arm/compare_group)
# GET  /api/run/{id}/events      → SSE 流式事件(含 done 哨兵 + 15s 心跳保活)
# GET  /api/runs                 → 全部任务列表与事件计数
# GET  /api/artifacts/{id}/{name}→ 下载工件
# GET  /health / /              → 健康检查 + Vue 3 运行监控页(monitor_page.py,零构建)
# GET  /vue.global.prod.js       → vendored Vue 运行时(static/,离线可用)
```

- `TaskEventBus`(api/event_bus.py)是事件中枢:harness 的 `on_event` 回调把事件推入总线,既驱动 SSE,也写入 `trace.json`
- `--impl fastapi` 时由 `create_app()` 装配;默认仍走零依赖的 stdlib 实现(`pip install 'mycoder-harness[api]'` 启用 FastAPI 路径)
- **【为什么】两种实现并存?** stdlib 版保证"任何一台裸 Python 机器"都能起 API(零依赖哲学);FastAPI 版提供 SSE 与更丰富的接口。默认行为不因可选依赖存在与否而改变。

### 13.3 测试套件

```
test_models.py        (15)  MockBackend 脚本 progression/state恢复
test_tools.py         (21)  每种工具 execute + error case
test_sandbox.py       (15)  路径逃逸拦截
test_safety.py        (70)  参数校验/隔离/HITL/去重/脱敏(参数化边界展开)
test_context.py       (19)  token估算/折叠/硬限额
test_memory.py        (19)  三层存储/去重/检索/持久化
test_checkpoint.py    (15)  断点/漂移
test_harness.py       (18)  主循环/安全拦截/恢复/空终答温和重问
test_backend.py        (9)  重试/退避/流式/usage 解析
test_cost.py           (5)  成本计量
test_eval.py          (18)  五层评测+benchmark 数据完整性
test_observability.py  (7)  Span/Tracer/trace.json/JSON 日志
test_vectors.py       (11)  Embedding/VectorIndex/BM25/HybridRetriever
test_api.py            (7)  FastAPI 路由/SSE/监控页/后端切换/双跑对照
test_orchestrator.py   (4)  子任务分解/并行/降级
test_real_eval.py      (4)  LLM-as-judge 解析/真实任务硬断言(离线部分)
test_real_baseline.py  (7)  Layer 6b 裸基线两臂/工具白名单/三臂对照(离线部分)
test_performance.py    (8)  压力测试(巨型文件)
总计: 272 项(18 个测试文件,含参数化展开数量)
```

**【为什么】把安全边界参数化到 70 项?** 安全不是"测过一次"的事:路径逃逸有无数种写法(`..`、编码变换、绝对路径、盘符……)。参数化让"一个场景 = 一行参数",扩展新边界 case 只加一行。这也是给读者的示范:**你的新工具/新安全规则也应该这样展开测试**。

### 13.4 性能测试

`test_performance.py` 使用 `giant_test.py`(~4669 行)对 8 个维度进行压力测试:
1. 文件读取 I/O
2. 文件列表
3. Grep 搜索
4. 记忆存储
5. 上下文管理
6. 断点 I/O
7. 工作区操作
8. 工具注册

每项 3 轮取平均,输出 avg/min/max 耗时。

**▶ 动手示例 13-1:任务文件驱动的 CLI 一次跑**

```bash
# 写一个带 script 的任务文件(保存为 task_demo.json):
# {
#   "task_id": "cli-demo",
#   "goal": "读取 notes.txt 并总结",
#   "setup_files": {"notes.txt": "会议纪要:周三发布 v1.2"},
#   "script": [
#     {"tool_calls": [{"name": "file_read", "arguments": {"path": "notes.txt"}}]},
#     {"content": "notes.txt 记录:周三发布 v1.2。"}
#   ]
# }
.conda/python.exe -m mycoder run --task-file task_demo.json --hitl-policy allow
# 输出 JSON:status / metrics / final_answer / artifacts_dir
```

**✍ 练习**
- 基础:按示例 13-1 构造任务文件并跑通;然后到 `artifacts_dir` 里打开 report.md。
- 进阶:`python -m mycoder serve`(stdlib 实现)下用 `curl -X POST` 提交一个带 script 的任务,轮询 `GET /api/run/{id}` 直到 completed。
- 进阶:`orchestrate --goal "..."` 跑一次编排,打开 `orchestration.json` 观察子任务分解与状态汇总。

**⚠ 易错点**
- `run` 的任务文件若不带 `script`,会按 `--backend`/配置装配后端(默认 mock,但无脚本的 Mock 只会直接终答)——想看真实模型行为要显式 `--backend local_openai` 且 Ollama 在线。
- `serve` 起两个实例会端口冲突(默认 8910);改 `--port` 即可。
- FastAPI 实现需要 api 依赖组;报 `fastapi 未安装` 时 `pip install 'mycoder-harness[api]'` 或退回 stdlib。

**☑ 自测清单**
- ☑ 我能写出 8 个 CLI 子命令并用任务文件跑通 run;
- ☑ 我能解释 stdlib/FastAPI 双实现共存的理由;
- ☑ 我知道 272 项测试分布在哪些文件、安全测试为什么特别多。

---

# 第六部分 总结

## 第 14 章 设计模式回顾与核心数据流

| 模式 | 落地位置 | 作用 |
|------|----------|------|
| 抽象基类 | ModelBackend / Tool | 解耦接口与实现 |
| 工厂方法 | AgentHarness.build() / build_registry() | 统一装配 |
| 依赖注入 | ToolContext(workspace, memory, config) | 测试隔离 |
| 责任链 | SafetyGuard.check() 五步链 | 安全检查正交 |
| 策略模式 | ApprovalProvider (Allow/Deny/Prompt/Callback) | HITL 灵活适配 |
| 深拷贝不可变 | ContextManager.assemble() | 确定性重放 |
| 原子写 | util.atomic_write() | 崩溃安全 |
| 追加写日志 | RunRecorder (trajectory.jsonl) | 崩溃可恢复 |
| A/B 对照实验 | EvalRunner layer_context/memory | 量化系统收益 |

**核心数据流**:
```
TaskInput → Harness.run() → [assemble → complete → check → execute → remember → checkpoint] → RunResult + Artifacts
```

> 复习建议:把上表当成**面试自测题**——遮住"落地位置"列,看模式名能否说出本项目在哪用了它、为什么用;再遮住"作用"列反向自测。

## 第 15 章 读完之后:实操进阶路线

读完本指南后,建议按以下顺序实操(均已预装,`conda activate D:\PythonProject\mycoder\.conda` 后直接运行):

1. `.conda/python.exe -m pytest tests/` — 全部 272 项测试通过,建立"改动前基线"
2. `python examples/context_demo.py` — 直观看到上下文治理的压缩效果
3. `python -m mycoder eval --suite all --output .mycoder/eval` — 生成五层评测报告并打开 report.md
4. `python -m mycoder serve` + 浏览器打开 http://127.0.0.1:8910/ — Vue 监控页提交任务,SSE 实时看事件流
5. 阅读 `tests/test_harness.py` 理解主循环测试方式
6. 尝试修改 `config/default.yaml` 的参数(如 budget_tokens),重跑评测观察行为变化

### P3 读者的扩展任务(任选其一,做完即"能贡献")

- **任务 A(加工具)**:仿照 `tools/memory_tool.py` 实现一个 `PythonReplTool`(在工作区受限地执行一段 Python 并返回 stdout),注册进 `build_registry`,补 3 个单测(正常/异常/危险行为拦截),并保证 272+ 项测试全绿。
- **任务 B(改策略)**:实现 `TopKSummarizer`(折叠时只保留最近 K 个工具结果、其余丢弃),通过 `context.summarizer` 配置接入,给 `test_context.py` 补 2 个用例。
- **任务 C(做实验)**:把 Layer 2 的治理臂 budget 扫描成 [500, 1000, 2000, 4000],画一张"预算-压缩率-完成率"表,写一段 200 字结论。
- **任务 D(接真模型)**:安装 Ollama + qwen3.5:2b,跑 `--suite real` 与 `--suite real_baseline`,对照第 0.2 节的三臂数字解释你的结果差异(模型方差是正常现象,如实记录)。

> 延伸阅读(仓库内):[ARCHITECTURE.md](ARCHITECTURE.md) 架构总览 · [TESTING.md](TESTING.md) 测试方法 · [EVAL_HARDENING.md](EVAL_HARDENING.md) 评测加固 · [WEB_BACKEND_SWITCH.md](WEB_BACKEND_SWITCH.md) 后端切换设计记录 · `kb_lora/` 企业知识库 LoRA 微调线(任务成功任务件可选导出 SFT 样本,`artifacts.sft_log: true`)。

---

# 第七部分 附录(检索区)

## 附录 A 完整术语表(按主题分组)

**Agent 与循环**
| 术语 | 定义 |
|------|------|
| Coding Agent | 能通过工具调用多步完成编码任务的 LLM 程序 |
| Harness | 包裹模型的运行底座:循环调度 + 安全 + 治理 + 记忆 + 断点 + 工件 |
| Step(步) | 主循环一次迭代:一次模型调用及其工具执行 |
| Turn(轮) | 一轮对话 = assistant 消息 + 其 tool 结果(可选轮末 user 追问) |
| 终答(final answer) | 模型不再发起工具调用时给出的回复,任务就此结束 |
| 空终答温和重问(nudge) | 模型返回空回复时注入用户提醒再给一次机会,上限 `harness.empty_answer_nudges` |
| follow-up(后续任务) | 以 `follow_up_of` 指向父任务的新任务,自动继承父任务记忆摘要 |
| Orchestrator(编排器) | 把目标分解为子任务、以独立工作区并行执行的组件 |

**模型侧**
| 术语 | 定义 |
|------|------|
| Token | 模型最小文本单位;本项目用启发式估算(中文 1 字、英文 4 字符 ≈1 token) |
| 上下文窗口 | 模型单次可见文本上限;项目内以 budget/hard 两个预算治理 |
| Tool Calling | 模型输出"工具名+参数"的结构化请求;`arguments` 为 JSON 字符串 |
| ModelBackend | 后端抽象:complete() 唯一必需;state()/load_state() 支持断点 |
| MockBackend | 确定性脚本后端,评测/测试的"冻结变量" |
| LocalOpenAIBackend | 本地 OpenAI 兼容 HTTP 后端(Ollama/llama.cpp/vLLM) |
| usage | 模型返回的 prompt/completion token 计量,成本核算数据源 |
| LLM-as-judge | 用另一个模型给任务结果打分的评审查方法(Layer 6) |

**上下文与记忆**
| 术语 | 定义 |
|------|------|
| 上下文治理 | 组装 + 裁剪 prompt 以满足预算的机制(ContextManager) |
| 软预算 budget_tokens | 超过即触发折叠的阈值(默认 4000) |
| 硬限额 hard_limit_tokens | 绝对红线(默认 6000),任何裁剪后都必须低于它 |
| 三层裁剪 | fold_old_turns(折叠旧轮)→ drop_stale_turns(只留最近 1 轮)→ truncate_long_content(截断超长) |
| PruneInfo | 一次 assemble 的裁剪档案:before/after tokens、pruned、strategies |
| 摘要器 | 把被折叠历史压成要点的组件(deterministic / llm / noop) |
| 结构化记忆 | 任务/文件/关联三层摘要存储(StructuredMemory) |
| 文件摘要新鲜度 | 摘要记录的 SHA-256 与当前文件一致 → `has_fresh_summary` |
| 嵌入器 | 文本→向量的组件:HashingEmbedder(零依赖默认)/ FastEmbedEmbedder |
| 混合检索 hybrid | 向量余弦 + BM25 加权融合,alpha 控制向量权重 |
| recall@K / MRR@5 | 检索指标:前 K 命中率 / 平均排名倒数 |

**安全与治理**
| 术语 | 定义 |
|------|------|
| 沙箱(Workspace) | 把文件访问限制在根目录内的受控原语集合 |
| 路径逃逸 | 用 ../、绝对路径、符号链接等越出工作区;resolve() 四层防护拦截 |
| 五步安全链 | schema 校验 → 路径隔离 → shell 白/黑名单 → 去重 → HITL |
| danger 等级 | 工具声明风险:safe / warn / hitl |
| HITL | 高风险操作人工审批;策略 allow/deny/prompt/callback |
| 去重(dedup) | 相同 (工具,参数) 调用:读类回缓存,写类只标记 |
| 脱敏(Redact) | 正则替换密钥/密码/令牌为 [REDACTED_*],作用于输出/轨迹/工件 |
| 白名单/黑名单 | shell 准入清单 + 危险模式正则,双层防护 |

**可靠性与工件**
| 术语 | 定义 |
|------|------|
| Checkpoint(断点) | 自包含快照:任务+上下文+指纹+指标+后端状态 |
| Resume(恢复) | 从断点续跑;恢复游标/历史/指标,并先做漂移识别 |
| 漂移(Drift) | 中断期间工作区被外部改动;逐文件 SHA-256 精确比对 |
| 原子写 | 临时文件 + os.replace,杜绝半截文件 |
| 工件(Artifacts) | 三类产物:trajectory.jsonl / checkpoint.json / metrics.json+report.md(另有 trace.json) |
| trace.json | OTLP 风格链路追踪(span 层级与耗时) |
| SFT 样本 | 任务成功时可选导出的 (instruction, output) 微调数据(`artifacts.sft_log`) |

**评测**
| 术语 | 定义 |
|------|------|
| 五层离线评测 | 回归/上下文/记忆/恢复/检索(Layer 1-5,全 Mock,进 pytest) |
| Layer 6 / 6b / 7 | 真实任务评测 / 裸基线三臂对照 / 嵌入器对照(按需运行) |
| 对照实验 | 固定任务与数据,只改一个系统开关,度量差值 |
| 冻结基准 | 固定 seed 生成后提交入库的任务集(tasks.generated.json,42 个) |
| 硬断言 | 对文件内容/存在性的确定性检查(区别于主观打分) |

## 附录 B 配置项速查表

> 来源:`mycoder/config.py` DEFAULT 与 `config/default.yaml`。CLI/API 默认加载内置默认值,要用 YAML 请显式 `--config config/default.yaml`。

| 配置项(dot-path) | 默认值 | 作用 | 详见 |
|------|--------|------|------|
| `workspace.root` | `"."` | 工具沙箱根目录 | 第 3 站 |
| `workspace.allow_absolute` | `false` | 是否允许绝对路径 | 第 3 站 |
| `model.backend` | `mock` | `mock` / `local_openai` | 第 2 站 |
| `model.mock.seed` | `42` | Mock 确定性种子 | 第 2 站 |
| `model.local_openai.base_url` | `http://127.0.0.1:8080/v1` | OpenAI 兼容端点 | 第 2 站 |
| `model.local_openai.model` | `qwen2.5-coder-7b` | 模型名(须与服务端一致) | 第 2 站 |
| `model.local_openai.temperature` | `0.0` | 采样温度 | 第 2 站 |
| `model.local_openai.timeout_seconds` | `60` | 请求超时 | 第 2 站 |
| `model.local_openai.max_retries` | `3` | 重试次数 | 第 2 站 |
| `model.local_openai.backoff_base / backoff_cap` | `0.5 / 8.0` | 指数退避基数/上限(秒) | 第 2 站 |
| `model.local_openai.stream` | `false` | 流式开关 | 第 2 站 |
| `model.pricing` | `{}` | 每 1k token 价目(按模型名,`*` 兜底) | — |
| `harness.max_steps` | `30` | 单任务最大步数 | 第 8 站 |
| `harness.max_tool_calls_per_turn` | `8` | 单轮最多工具调用数 | 第 8 站 |
| `harness.empty_answer_nudges` | `1` | 空终答温和重问次数(0=关) | 第 8 站 |
| `context.budget_tokens` | `4000` | 软预算(触发折叠) | 第 5 站 |
| `context.hard_limit_tokens` | `6000` | 硬上限 | 第 5 站 |
| `context.keep_last_turns` | `6` | 保留最近 N 轮原文 | 第 5 站 |
| `context.keep_last_tool_results` | `8` | 保留最近 N 条工具返回 | 第 5 站 |
| `context.max_file_content_chars` | `8000` | 单条工具返回截断阈值(字符) | 第 5 站 |
| `context.compressible_age` | `3` | 超过该轮数的历史可折叠 | 第 5 站 |
| `context.summarizer` | `deterministic` | `deterministic` / `llm` | 第 5 站 |
| `memory.enabled` | `true` | 结构化记忆总开关 | 第 6 站 |
| `memory.root` | `.mycoder/memory` | 记忆持久化目录 | 第 6 站 |
| `memory.auto_remember_files` | `true` | 读写文件后自动沉淀摘要 | 第 8 站 |
| `memory.followup_inject_summaries` | `true` | follow-up 注入父任务摘要 | 第 6 站 |
| `memory.retrieval.mode` | `substring` | `substring` / `vector` / `hybrid` | 第 6 站 |
| `memory.retrieval.alpha` | `0.5` | hybrid 向量权重(0~1) | 第 6 站 |
| `memory.retrieval.embedder` | `hashing` | `hashing` / `fastembed` | 第 6 站 |
| `checkpoint.enabled` | `true` | 断点总开关 | 第 7 站 |
| `checkpoint.root` | `.mycoder/checkpoints` | 断点目录 | 第 7 站 |
| `checkpoint.interval_steps` | `4` | 每 N 步自动落盘 | 第 7 站 |
| `checkpoint.on_prune` | `true` | 裁剪前强制落盘 | 第 7 站 |
| `checkpoint.detect_drift` | `true` | resume 时检测漂移 | 第 7 站 |
| `safety.hitl_policy` | `prompt` | `prompt` / `allow` / `deny` | 第 4 站 |
| `safety.dedup_enabled` | `true` | 重复调用拦截 | 第 4 站 |
| `safety.redaction_enabled` | `true` | 敏感信息脱敏 | 第 4 站 |
| `safety.shell.allow_commands` | echo/ls/dir/pwd/cat/... | shell 白名单 | 第 4 站 |
| `safety.shell.deny_patterns` | `rm\s+-rf` 等 | shell 黑名单正则 | 第 4 站 |
| `safety.allow_write_outside_ext` | `[]` | 额外允许写入的扩展名 | — |
| `artifacts.root` | `.mycoder/artifacts` | 工件目录 | 第 1 站 |
| `artifacts.redact_artifacts` | `true` | 导出工件时脱敏 | 第 4 站 |
| `artifacts.sft_log` | `false` | 成功任务导出 SFT 样本 | 第 15 章 |
| `logging.level` | `INFO` | 日志级别 | — |
| `logging.file` | `.mycoder/harness.log` | 日志文件 | — |
| `logging.format` | `text` | `text` / `json`(结构化行) | 第 10 站 |
| `observability.enabled` | `true` | 导出 trace.json 链路追踪 | 第 10 站 |
| `agent.orchestrator.enabled` | `false` | 子代理编排开关 | 第 10 站 |
| `agent.orchestrator.max_workers` | `4` | 并行子任务数 | 第 10 站 |
| `api.host` / `api.port` | `127.0.0.1` / `8910` | API 监听地址 | 第 10 站 |
| `eval.real.*` / `eval.real_baseline.*` | 见 default.yaml | Layer 6 / 6b 任务与 judge 配置 | 第 9 站 |

## 附录 C CLI / API 命令速查

**CLI(`.conda/python.exe -m mycoder ...`)**

| 命令 | 作用 | 常用参数 |
|------|------|----------|
| `run --task-file <file>` | 运行任务(文件含 script 时用 Mock 回放) | `--config` `--backend` `--workspace` `--hitl-policy` |
| `resume <task_id>` | 从断点恢复 | `--config` |
| `serve` | 启动 localhost API | `--impl stdlib\|fastapi` `--host` `--port` |
| `eval` | 运行评测 | `--suite all\|regression\|context\|memory\|resume\|retrieval\|real\|real_baseline\|embedder` `--output` |
| `benchmark` | 列出内置 benchmark 任务 | — |
| `artifacts` | 查看/聚合任务工件 | — |
| `doctor` | 环境诊断 | — |
| `orchestrate` | 子任务并行编排 | `--goal` `--max-workers` |

**HTTP API(FastAPI 实现,默认 127.0.0.1:8910)**

| 端点 | 方法 | 作用 |
|------|------|------|
| `/api/run` | POST | 提交任务(可带 `backend`、`script`),立即返回 task_id |
| `/api/compare` | POST | 一键双跑对照(mock + ollama 两臂,共享 compare_group) |
| `/api/run/{id}` | GET | 任务状态/结果快照 |
| `/api/run/{id}/events` | GET | SSE 实时事件流(done 哨兵 + 心跳) |
| `/api/runs` | GET | 任务列表(含 backend/arm/compare_group) |
| `/api/artifacts/{id}/{name}` | GET | 下载工件 |
| `/health` | GET | 健康检查 |

## 附录 D 测试与 benchmark 数据索引

- 测试文件清单与数量:见第 13.3 节表(共 **272 项 / 18 文件**)。运行方式:`.conda/python.exe -m pytest tests/`。
- benchmark 数据(`benchmarks/`):

| 文件 | 内容 |
|------|------|
| `tasks.json` | 26 个手写任务(回归 17 / 上下文 4 / 记忆 4 / 恢复 1),含负例与边界 |
| `tasks.generated.json` | 固定 seed 生成的冻结基准 42 任务(入库保证可复现) |
| `retrieval.json` | 检索召回核心数据 38 条查询 |
| `retrieval_extra.json` | 扩展 4 领域 44 条(合计 82 条:exact/synonym/distractor/empty) |
| `real_tasks.json` | Layer 6 真实编码任务 4 个 |
| `generators.py` | 冻结基准的生成脚本 |

## 附录 E FAQ(常见问题解答)

**环境类**

- **Q:必须用项目自带的 `.conda` 吗?我自己的 Python 3.11 行不行?**
  A:行。核心运行时唯一强制依赖是 PyYAML,`pip install -e .` 即可;但要跑完整测试/评测/FastAPI,按 `requirements-project.txt` 装,等价于 `conda env create -p .conda -f environment.yml`。
- **Q:`python -m mycoder` 报 `No module named mycoder`?**
  A:你在用别的解释器或不在仓库根目录。用 `.conda/python.exe` 并 `cd` 到仓库根。
- **Q:Windows 控制台中文乱码?**
  A:`set PYTHONIOENCODING=utf-8`(cmd)或改用 Git Bash / Windows Terminal。
- **Q:pytest 收集到的用例数和文档说的 272 不一样?**
  A:清理 `__pycache__` 与 `.pytest_cache` 后重跑;确认测试文件没有缺失(见附录 D 清单)。

**使用类**

- **Q:为什么我改了 `config/default.yaml` 没生效?**
  A:CLI/API 默认只读内置默认值,必须显式 `--config config/default.yaml`(第 1 章易错点)。
- **Q:任务一跑就结束,final_answer 是"任务已完成。"?**
  A:你用的是 Mock 后端且脚本为空/用尽,它返回了 `default_answer`。给任务文件加 `script`,或切 `--backend local_openai`。
- **Q:模型发起的文件操作被拦截了?**
  A:九成是路径问题:绝对路径或 `../` 越界会被沙箱拦截并回传 `[已拦截] …`。工具路径一律用工作区相对路径。
- **Q:shell 命令一直卡着等我确认?**
  A:`safety.hitl_policy` 默认 `prompt`(交互审批)。脚本场景用 `--hitl-policy allow/deny`。
- **Q:怎么切换到真实模型(Ollama)?**
  A:三种方式:改配置 `model.backend: local_openai`;CLI `--backend local_openai`;监控页「执行后端」选择。前提:Ollama 在线且 `model` 名与 `ollama list` 一致。
- **Q:`real_baseline` 报告在哪?为什么和 `real` 在同一个目录?**
  A:`--suite real` 与 `--suite real_baseline` 都写 `.mycoder/real/` 且**互相不清空**,就是为了三臂对照共存(`real_report.json` + `real_baseline_report.json`)。

**原理类**

- **Q:为什么评测不直接用真模型?**
  A:确定性。Mock 冻结模型变量,分数变化只能来自系统改动;真模型评测是补充(第 0.4 节误区 3)。
- **Q:token 估算不准怎么办?**
  A:它只需单调+稳定,不与某模型对齐;评测比的是相对差值。计费请用 API usage(`cost.py` 支持)。
- **Q:为什么裁剪在深拷贝上做?**
  A:原始历史是唯一可信数据源(可重放、可算 before_tokens、可进 checkpoint),裁剪只是投影(第 5 站)。
- **Q:读去重为什么返回缓存、写去重不返回?**
  A:读幂等,缓存安全;写重放可能掩盖真实执行状态,只标记 `skipped_repeats`(第 4 站)。
- **Q:上下文治理会不会丢关键信息?**
  A:三层递进尽量保信息(折叠保留要点);配置 `context.summarizer: llm` 可换模型压缩;硬截断是最后防线,`max_file_content_chars` 控制单条上限。
- **Q:漂移检测为什么 100% 准?成本呢?**
  A:内容级 SHA-256 逐文件比对,无误判;代价是全量指纹扫描,工作区极大时需增量方案(第 10 章练习)。

**评测类**

- **Q:怎么只跑某一层?**
  A:`--suite context`(或 regression/memory/resume/retrieval)。
- **Q:Layer 6 的 judge 全部 0 分正常吗?**
  A:2b 小模型当评委不可靠,项目如实保留结果;换更大模型或加长 `judge_timeout_seconds` 可改善,结论请以硬断言为主。
- **Q:评测结果会互相污染吗?**
  A:runner 每次运行前重置输出目录与临时工作区(real/real_baseline 除外);记忆/断点/工件都在隔离目录里。

**扩展开发类**

- **Q:加一个新工具要做哪几件事?**
  A:继承 `Tool` → 声明 name/description/parameters/danger → 实现 `execute`(不写安全代码)→ 注册进 `build_registry` → 若有路径参数登记 `_PATH_TOOLS` → 补测试(第 15 章任务 A)。
- **Q:想换摘要/嵌入/审批策略?**
  A:三者都是策略接口:Summarizer / EmbeddingProvider / ApprovalProvider,实现并注入即可。
- **Q:怎么接入非 OpenAI 兼容的模型?**
  A:实现 `ModelBackend.complete()`(必要时含 state/load_state),经 `AgentHarness.build(backend=...)` 注入,主循环零改动。

## 附录 F 易错点与调试技巧大全

> 各站"易错点"的汇总索引,按"症状 → 原因 → 解法/详见"组织。

| # | 症状 | 原因 | 详见 |
|---|------|------|------|
| 1 | 工具参数解析失败 / arguments 处理报错 | OpenAI 协议中 `arguments` 是 JSON **字符串**,须 `json.loads` | 第 2/8 站 |
| 2 | `../xxx` 或绝对路径被拦截 | 沙箱四层防护,设计行为 | 第 3 站 |
| 3 | Mock 任务"秒完成"、答非所问 | 脚本用尽后静默返回 `default_answer` | 第 2 站 |
| 4 | resume 后行为错乱/从头重放 | 未恢复后端游标;或两次 build 用了不同 checkpoint.root | 第 5/7/8 站 |
| 5 | 改了 assemble() 返回值但"没生效" | 返回的是深拷贝投影,不会写回 raw_turns | 第 5 站 |
| 6 | budget 调大后反而频繁硬截断 | budget(软)与 hard(硬)语义混淆 | 第 5 站 |
| 7 | 重复读同一文件拿到的内容"旧了" | 读去重缓存;或记忆摘要按哈希判定仍新鲜 | 第 4/6 站 |
| 8 | 写去重后文件似乎"没写"? | 写重复只标记 `skipped_repeats`,**不会**假装成功;检查是否真执行过第一次 | 第 4 站 |
| 9 | 断点文件损坏/半截 | 手动绕过 atomic_write 直接写 JSON | 第 1 站 |
| 10 | 评测跑了但报告是空的 | 看错输出目录;或 suite 名拼错 | 第 9 站 / 附录 C |
| 11 | `real`/`real_baseline` 目录"没被清理" | 设计如此,两份报告共存做三臂对照 | 第 9 站 |
| 12 | 交互式 shell 确认卡住自动化脚本 | `hitl_policy: prompt` 在等输入 | 第 4 站 |
| 13 | `file_edit` 报"非唯一匹配" | old_string 命中多处且未传 `replace_all` | 第 3 站 |
| 14 | 工具抛异常但任务没失败 | harness 把异常转成 `[工具异常]` 回传模型,任务继续(容错设计) | 第 8 站 |
| 15 | 数据类默认值共享导致诡异 bug | dataclass 可变默认值必须 `field(default_factory=...)` | 第 1 站 |
| 16 | CLI 改配置不生效 | 未传 `--config` | 第 1/10 站 |
| 17 | 检索想用语义匹配但结果和 substring 一样 | `memory.retrieval.mode` 仍是默认 substring | 第 6 站 |
| 18 | `.mycoder/` 越来越大 | 工件/记忆/断点持续落盘;评测前 runner 自行重置,平时可手动清理(不入库) | 第 2 章 |

**调试三板斧**:
1. **看轨迹**:`.mycoder/artifacts/<task_id>/trajectory.jsonl` 逐行读,每一步的模型输出/工具调用/拦截原因/裁剪策略都在里面;
2. **看事件**:`trace.json`(层级耗时)+ `--suite` 评测 JSON(逐任务明细);API 场景直接看 SSE 事件流;
3. **最小复现**:把问题缩到第 5/8/11 站的最小示例上复现,再放大——十站的"动手示例"就是为此准备的模板。

## 附录 G 学习自测总清单

完成全部十站后,用这份总清单验收(P2 毕业 = 全部能答"是"):

- **地基**:配置三层来源?深合并 vs 浅合并的坑?三类工件与写入方式?
- **后端**:state()/load_state() 的意义?Mock 脚本的两条出路与兜底行为?
- **工具**:7 个工具与 danger 分级?resolve() 四层防护与 startswith 反例?
- **安全**:五步链顺序?读/写去重语义差异?脱敏三处位置?
- **上下文**:三层裁剪策略与触发条件?全量重算 + 深拷贝为什么是确定性的根基?启发式 token 的取舍?
- **记忆**:三层存储与持久化文件?"重读 2→0"的机制链?hybrid vs substring 的实测差距?
- **断点**:快照五大组成?三个落盘时机?漂移的集合运算定义?
- **主循环**:六步默写?_run_one_tool 七步?空终答温和重问?中断→恢复全流程?
- **评测**:五层各自"固定/改变/度量"什么?recall@K 与 MRR?三臂对照(6b)的实验设计?
- **收尾**:8 个 CLI 子命令?双 API 实现取舍?272 项测试的分布与安全参数化思想?

---

> **版本与维护说明**:本文档与代码同步维护;文中数字(272 项测试、82 条查询、26+42 任务、三臂数据)为当前版本实测。若你按第 15 章做了扩展并改变了这些数字,请一并更新对应章节——文档与代码一样,也需要"测试"。
