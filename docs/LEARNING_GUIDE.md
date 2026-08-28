# MyCoder 项目学习指南 — 从零构建一个本地 Coding Agent Harness

> 本文档按照"如果你要从头写这个项目,你会怎么思考和编码"的顺序,逐模块拆解每一行代码的设计意图与实现细节。建议按顺序阅读,每个模块读完后对照源码走一遍。

---

## 环境准备:项目内置 `.conda` 环境(动手前必读)

本项目所有代码、测试、评测均基于**仓库内自带的 Conda 独立环境**,不再依赖系统 Python 或全局 Anaconda 的 base/命名环境。

| 项目 | 说明 |
|------|------|
| 环境位置 | `D:\PythonProject\mycoder\.conda\`(相对仓库即 `<repo>\.conda`) |
| 管理方式 | Anaconda 以**路径(prefix)**方式管理,环境名显示为完整路径 |
| Python 版本 | 3.11(pyproject 声明兼容 3.10+) |
| 预装内容 | 全部运行时依赖 + dev/api/vector 可选组 + 项目本体可编辑安装(`pip install -e .`) |
| 版本控制 | `.conda/` 已加入 .gitignore,**不入库** |

**日常使用**(三选一):

```bash
# 1) 激活后使用 python(PowerShell/cmd)
conda activate D:\PythonProject\mycoder\.conda

# 2) Git Bash 中激活
source .conda/Scripts/activate

# 3) 不激活,直接调用项目内解释器
.conda/python.exe -m pytest tests/       # cmd/PowerShell 写法: .conda\python.exe ...
```

**验证环境可用**:

```bash
.conda/python.exe --version                       # 应输出 Python 3.11.x
.conda/python.exe -m pytest tests/ --collect-only -q | tail -3   # 应列出 268 个用例
```

**环境坏了/换机器怎么重建**(一条命令,全部依赖自动就位):

```bash
conda env create -p .conda -f environment.yml
```

> `environment.yml` 使用 conda-forge 渠道的 python 3.11 + pip,再由 pip 安装 `requirements-project.txt`(其内部聚合 requirements-dev/api/vector 并执行 `-e .`)。IDE(VS Code/PyCharm)把解释器指向 `.conda/python.exe` 即可识别为 Conda 环境。

---

## 第〇章 学习路线总览

### 你处于哪个阶段?

- **只想把它跑起来**:读上面的「环境准备」,然后按 README「快速开始」依次跑 Demo → 测试 → 评测,即可获得直观感受;
- **想理解为什么这样设计**:精读本章 + [ARCHITECTURE.md](ARCHITECTURE.md) 的「核心设计原则」,再进入第 8 站主循环;
- **想逐行吃透源码甚至做贡献**:按下面 10 站顺序完整走读,每站读完跑对应单测(`tests/test_<模块>.py`)验证理解。

### 十站源码走读路线

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

### 模块关系一览(谁依赖谁)

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

**核心设计哲学(贯穿全程)**:
- **确定性优先**:同一输入必得同一输出,评测才能复现
- **安全与业务正交**:工具只管做事,安全在进入工具前拦截
- **深拷贝不可变**:裁剪不污染原始历史,保证可重放

---

## 第 1 站 地基:config / state / util / artifacts

### 1.1 config.py — 配置加载与合并

**为什么先写它**:整个项目所有模块都需要读配置(budget、max_steps、白名单……),所以配置层必须最先就位。

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
- 内置默认值保证**任何缺失字段都有安全 fallback**——你永远不用担心 KeyError。

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
- **深合并**而非浅合并:用户只覆盖 `context.budget_tokens` 不会把 `context.hard_limit_tokens` 丢掉。

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
- **点号路径访问**:`config.get("context.budget_tokens")` 比嵌套字典访问更简洁,全项目统一风格。

**学习要点**:
- 配置是"数据"不是"代码",用字典 + 深合并就够,不需要 pydantic
- `get()` 用 dotted string 避免层层 `["a"]["b"]["c"]`

---

### 1.2 state.py — 会话状态模型

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
- `to_openai()` 把内部表示转成 HTTP 请求体格式——这是与外部模型服务对接的边界。

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
- `prompt_before_tokens` vs `prompt_after_tokens` 的差就是**裁剪收益**,评测的核心指标。

**学习要点**:
- 用 `@dataclass` 而非普通 class:自动生成 `__init__`/`__repr__`,减少样板代码
- 所有字段都是 `str`/`int`/`list`/`dict`——纯 JSON 可序列化

---

### 1.3 util.py — 通用工具函数

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
- 这个函数被 `Workspace.snapshot()`(指纹)、`remember_file()`(去重)、`drift.py`(漂移检测)三处复用

```python
def atomic_write(path, content) -> None:
    """原子写:先写临时文件再 os.replace"""
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.replace(tmp, p)  # 原子操作
```
- **为什么原子写**:checkpoint/trajectory 写到一半崩溃会留下半截文件,`os.replace` 是原子操作,避免这个风险

```python
def truncate(text, max_chars, head_ratio=0.6) -> str:
    """保留头 60% + 尾部"""
    head = int(max_chars * head_ratio)
    tail = max_chars - head - 30
    return text[:head] + "\n…[截断 N 字符]…\n" + text[-tail:]
```
- **头尾保留**:代码和日志的关键信息通常在开头(import/函数签名)和结尾(return/报错),中间是冗余

---

### 1.4 artifacts.py — 三类运行工件

**为什么要三类工件**:对应"结果可复盘"的三个维度:

| 工件 | 文件 | 作用 | 写入方式 |
|------|------|------|----------|
| 轨迹 | trajectory.jsonl | 逐步追加的完整记录 | 追加写(崩溃可恢复) |
| 断点 | checkpoint.json | 可恢复的完整快照 | 原子写(由 checkpoint 模块产生) |
| 报告 | metrics.json + report.md | 聚合指标 + 人类可读 | 一次性写 |

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
- 这些字段就是评测报告的"数据源",直接映射到 report.md 的每行

**学习要点**:
- `RunRecorder` 用**追加写**(jsonl)而非覆盖写:任何时刻崩溃,已发生的步骤都还在
- `ArtifactManager._render_report()` 把 Metrics 转成人类可读 Markdown——"可观测性"的落地

---

## 第 2 站 模型后端:models/

### 2.1 base.py — 抽象基类

**设计意图**:解耦"模型如何回答"和"Harness 如何调度"。

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
- `state()`/`load_state()` 是关键:**MockBackend 有游标状态**(脚本执行到第几轮),resume 时必须恢复游标,否则会从头重放
- 默认空实现:LocalOpenAIBackend 无状态,不需要覆写

```python
@dataclass
class ModelResponse:
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 0, ...})
```
- **统一返回格式**:不管后端是 mock 还是 HTTP,Harness 只认这个结构

---

### 2.2 mock.py — 确定性脚本后端

**为什么需要 MockBackend**:
- 评测要求"同一输入必得同一输出"——真实 LLM 有随机性,做不到
- Mock 用脚本精确控制每轮输出,测的是**系统能力**而非模型能力

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
- 脚本用尽后返回默认终答,避免 Harness 空转

**脚本格式**:
```python
script = [
    {"tool_calls": [{"name": "file_read", "arguments": {"path": "a.py"}}]},
    {"content": "分析完成,结论是..."}
]
```

**学习要点**:
- `from_recipe()` 工厂方法:把"步骤列表"转成"脚本"——便捷构造
- MockBackend 是整个评测体系的**基石**,没有它就没有确定性

---

### 2.3 local_openai.py — 本地 OpenAI 兼容后端

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
- URL 兼容逻辑:`.../v1` → 补 `/chat/completions`,容错用户填的 base_url 格式

```python
    def _parse(self, body):
        ...
        for tc in raw_calls:
            arguments_str = fn.get("arguments") or "{}"
            tool_calls.append({
                "id": ..., "name": ..., "arguments": arguments_str  # 保持字符串!
            })
```
- **arguments 保持 JSON 字符串**:OpenAI 兼容格式要求 arguments 是字符串,harness 在执行时自行 `json.loads()` 解析

**学习要点**:
- 用标准库 urllib 而非 requests:**零额外依赖**,部署只需 `pip install pyyaml`
- `ConnectionError` 包装网络异常,给用户可读的提示

---

## 第 3 站 工具框架:tools/

### 3.1 base.py — Tool 基类 + Registry

**设计原则**:工具只管"纯业务",安全交给 safety 层。

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
- `danger` 等级决定 HITL 是否需要审批——**声明式安全**,工具自己声明风险等级

```python
@dataclass
class ToolContext:
    workspace: Any    # 沙箱工作区
    memory: Any       # 结构化记忆(可空)
    config: Any       # 全局 Config
```
- **依赖注入**:工具不直接 import 全局对象,由 harness 通过 ToolContext 注入——便于测试隔离

```python
class ToolRegistry:
    def register(self, tool): ...
    def get(self, name): ...
    def schemas(self): return [t.as_openai_schema() for t in self.all()]
```
- `schemas()` 批量导出 OpenAI tools 参数格式,送给模型后端

---

### 3.2 sandbox.py — 工作区沙箱

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
- **为什么用 commonpath 而非 startswith**:`/root_evil` 会匹配 `startswith("/root")` 但不匹配 `commonpath`
- resolve() 会展开 `..` 和符号链接,所以 `../../etc/passwd` 会被解析到工作区外

```python
    def snapshot(self) -> dict[str, str]:
        """返回 {相对路径: sha256}"""
        for f in self._iter_safe():
            out[str(f.relative_to(self.root))] = sha256_file(f)
        return out
```
- `snapshot()` 是**漂移识别的数据源**:checkpoint 时存指纹,resume 时比对

**学习要点**:
- 沙箱不暴露裸文件句柄,只暴露受控原语(`read_text`/`write_text`/`list_files`)
- 排除隐藏目录(`.git`/`.pytest_cache`)和 `__pycache__`——避免指纹被无关文件干扰

---

### 3.3 file_tools.py — 5 个文件工具

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
- **meta 携带 file_hash**:记忆模块和去重层直接复用,避免二次计算

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
- **唯一匹配保护**:防止误替换多处相同字符串——这是"精准编辑"的核心

---

### 3.4 shell_tool.py — 受控命令执行

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
- 超时硬上限 30 秒,防止恶意 sleep

**学习要点**:
- shell 是唯一 `danger=HITL` 的工具——执行命令风险最高
- 白名单/黑名单在 safety 层处理,工具本身不管

---

### 3.5 memory_tool.py — 记忆查询

```python
class MemoryQueryTool(Tool):
    danger = SAFE

    def execute(self, ctx, query, kind="all"):
        text = ctx.memory.search(query=query, kind=kind)
        return ToolResult(output=text or "(无相关记忆)")
```
- 把结构化记忆**对外开放成工具**:Agent 在 follow-up 阶段直接检索记忆,而非重读文件
- 这是"重复读文件降到 0"的关键工具

---

## 第 4 站 安全边界:safety/

### 4.1 guard.py — 五步安全链

**设计原则**:安全层与业务层正交。所有调用进入 execute 前都必须通过:

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
- 轻量 JSON Schema 子集:只实现项目需要的(type/required/enum/minimum/maximum),不引第三方库

**第 2 步:路径隔离**
```python
    if tool.name in self._PATH_TOOLS:
        for key in ("path", "cwd"):
            if key in params:
                self.workspace.resolve(params[key])  # 抛 PathEscapeError 即拦截
```

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
- **读去重**:第二次相同 file_read 直接返回缓存,不再读盘
- **写去重**:不返回缓存(危险),只标记跳过

**第 5 步:HITL 审批**
```python
    needs = tool.danger == HITL
    return GuardResult(True, needs_approval=needs, action=action)
```

**HITL 策略**:
```python
class AllowAllProvider:  approve() → True   # 测试用
class DenyAllProvider:   approve() → False  # 严格模式
class PromptProvider:    stdin 交互 y/n     # CLI 模式
class CallbackProvider:  回调函数决策        # 灵活适配
```

**学习要点**:
- `GuardResult` 携带 `cached_output`:去重短路时直接回填缓存,调用方无需感知
- 安全检查是**链式的**:任何一步失败就 deny,不继续后续检查

---

### 4.2 redact.py — 敏感信息脱敏

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
- **应用于**:tool output(进上下文前)、trajectory.jsonl(写盘前)、artifact export(导出前)
- 正则按顺序匹配,靠前优先——PEM 私钥块用 `.*?` 非贪婪匹配首尾

---

## 第 5 站 上下文治理:context/

### 5.1 tokens.py — 启发式 Token 估算

**为什么不用真实 tokenizer**:
- 真实 tokenizer 需要模型分词器依赖(tiktoken/transformers)
- 评测只需**单调性 + 稳定性**,不需要精确

```python
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

def estimate_tokens(text) -> int:
    cjk = len(_CJK_RE.findall(text))     # 中文按字
    other = len(text) - cjk              # 非中文按 4 字符/token
    return cjk + (other + 3) // 4        # +3 向上取整
```
- **中文 1 字 ≈ 1 token**(因为中文一个字通常就是一个 token)
- **英文 4 字符 ≈ 1 token**(因为英文一个单词约 4 字符)

```python
def estimate_messages(messages) -> int:
    for m in messages:
        total += 4 + estimate_tokens(content)  # 每条消息 +4 token 结构开销
```
- `+4` 模拟 OpenAI 的角色/结构固定开销

---

### 5.2 summarizer.py — 确定性历史摘要

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
- **确定性**:保留首句 + 工具名 + 结果首片段,不引入 LLM 随机性
- `NoopSummarizer`:折叠时直接丢弃——**对照实验用**,评测摘要收益

---

### 5.3 manager.py — ContextManager 核心

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
- **确定性收缩**:总是缩最长消息,缩到 60%——同一输入必得同一输出

**关键设计**:
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

**学习要点**:
- 每次都从**完整历史**重算,不做增量折叠——避免状态漂移,保证确定性
- 三层策略是**递进的**:先折叠,不行再丢弃,最后截断

---

## 第 6 站 结构化记忆:memory/

### 6.1 store.py — 三层存储

**三层结构**:

| 层级 | 数据结构 | 持久化文件 |
|------|----------|------------|
| 任务摘要 | `TaskRecord` | tasks.json |
| 文件摘要 | `FileRecord` | files.json |
| 关联记忆 | relations dict | relations.json |

**文件摘要提取(确定性)**:
```python
_SYMBOL_RE = re.compile(r"^\s*(def |class |async def |import |from )")

def summarize_file_content(content, max_chars=600):
    lines = content.splitlines()
    head = "\n".join(lines[:8])           # 头 8 行
    symbols = [ln.strip() for ln in lines if _SYMBOL_RE.match(ln)][:20]  # 关键符号
    return summary, symbols
```
- 不用 LLM,用正则提取函数/类/导入行——确定性 + 零成本

**去重关键**:
```python
def remember_file(self, path, content, sha256, task_id):
    digest = sha256 or sha256_text(content)
    rec = self.files.get(path)
    if rec is not None and rec.sha256 == digest:
        # 内容未变:摘要仍有效,不重算,不计为"重读"
        rec.last_read_at = now
        return False, rec    # ← 返回 False:没有真正更新
```
- **哈希一致性检查**:内容没变就不重算摘要——这是"重复读文件降到 0"的机制来源

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
- follow-up 任务自动拿到**父任务的文件摘要**,不必重读文件

**检索**:
```python
def search(self, query, kind="all"):
    # kind="task": 搜任务 ID/goal/summary
    # kind="file": 搜文件路径/摘要
    # kind="relation": 搜关联
    # kind="all": 三层都搜
```

---

### 6.2 retriever.py — 检索包装

```python
class MemoryRetriever:
    def should_re_read(self, path, digest) -> bool:
        """是否需要真正重读:已有与 digest 一致的摘要时返回 False"""
        return not self.memory.has_fresh_summary(path, digest)
```
- 这是 harness 判断"要不要重读文件"的入口

---

## 第 7 站 断点恢复:checkpoint/

### 7.1 store.py — 断点存储

```python
class CheckpointStore:
    def save(self, task_id, snapshot):
        atomic_write(self.path(task_id), json.dumps(snapshot, ...))

    def load(self, task_id) -> dict | None:
        return json.loads(p.read_text())
```
- 简单的 JSON 落盘 + 原子写
- **snapshot 自包含**:任务 + 上下文 + 工作区指纹 + 指标 + 后端状态

---

### 7.2 drift.py — 漂移识别

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
  - `modified` = 交集 ∩ 但值不同
  - `added` = after 有 before 没有
  - `deleted` = before 有 after 没有
- **100% 准确**:逐文件 SHA256 精确比对,不存在误判

---

## 第 8 站 主循环:agent/harness.py

**这是整个项目的中枢**,把所有模块编排成可中断、可恢复、可复盘的主循环。

### 8.1 装配工厂

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
- 一行 `AgentHarness.build(config)` 装配所有组件

### 8.2 主循环 _run()

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
        # 3. 终答判断
        if not resp.tool_calls:
            final_answer = resp.content
            break
        # 4. 执行工具
        calls, tool_msgs = self._execute_tools(resp.tool_calls)
        self.context.append_turn(assistant, tool_msgs)
        # 5. 指标 & checkpoint
        if self.context.last_prune.pruned:
            self._checkpoint(task, step_idx + 1, reason="prune")
```

### 8.3 工具执行 _execute_tools()

```python
def _execute_tools(self, raw_calls):
    for tc in raw_calls:
        # 解析 arguments(JSON 字符串 → dict)
        params = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        # 安全链 + 执行
        output, meta = self._run_one_tool(tool, params, ctx)
        # 脱敏(进上下文前)
        output = self.redactor.redact(output)
```

### 8.4 单次工具调用 _run_one_tool()

```python
def _run_one_tool(self, tool, params, ctx):
    gr = self.guard.check(tool, params)       # 1. 安全链
    if not gr.allowed:
        return f"[已拦截] {gr.reason}", meta
    if gr.needs_approval:
        if not self.guard._approver.approve(gr.action):  # 2. HITL
            return "[已拦截] 审批未通过", meta
    if gr.cached_output is not None:           # 3. 去重短路
        return gr.cached_output, meta
    result = tool.execute(ctx, **params)       # 4. 真正执行
    self.guard.record_executed(tool, params, output)  # 5. 登记去重
    self._after_tool(tool.name, result.meta)   # 6. 记忆沉淀
    return self.redactor.redact(output), meta  # 7. 脱敏
```

### 8.5 记忆沉淀 _after_tool()

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
- **自动沉淀**:每次读/写/改文件后,自动把文件摘要存入记忆——Agent 下次不用重读

### 8.6 Resume 流程

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
- `backend.load_state()` 恢复 Mock 游标,脚本从正确位置继续
- 漂移检测在 resume 开头,Agent 知道工作区是否被外部改动

---

## 第 9 站 评测闭环:eval/

### 9.1 五层评测理念

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

### 9.2 Layer 2 上下文治理评测(对照实验)

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

### 9.3 Layer 3 记忆收益评测

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
- **对照变量**:treatment 用 memory_query,control 用 file_read → 重读次数差就是记忆收益

### 9.4 Layer 4 恢复正确性评测

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

**学习要点**:
- 评测的"对照实验"思想:固定任务/数据,只改变系统开关
- `experiment.py` 的 `compare_metrics()` 把两组指标做 diff → 可读的改进量

### 9.5 Layer 5 检索召回评测(benchmarks/retrieval.json + retrieval_extra.json)

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

---

## 第 10 站 收尾:cli / api / examples / tests

### 10.1 CLI (cli.py)

```python
# 子命令:run / resume / serve / eval / benchmark / artifacts / doctor / orchestrate
```
- `run`:运行单个任务
- `resume`:从断点恢复
- `serve`:启动 localhost API(`--impl stdlib|fastapi`)
- `eval`:运行评测(`--suite all|regression|context|memory|resume|retrieval|real|real_baseline|embedder`)
- `orchestrate`:把复杂目标分解为子任务并行编排执行(`--goal` / `--max-workers`)

### 10.2 API

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

### 10.3 测试套件

```
test_models.py        (15)  MockBackend 脚本 progression/state恢复
test_tools.py         (21)  每种工具 execute + error case
test_sandbox.py       (15)  路径逃逸拦截
test_safety.py        (70)  参数校验/隔离/HITL/去重/脱敏(参数化边界展开)
test_context.py       (19)  token估算/折叠/硬限额
test_memory.py        (19)  三层存储/去重/检索/持久化
test_checkpoint.py    (15)  断点/漂移
test_harness.py       (15)  主循环/安全拦截/恢复
test_backend.py        (9)  重试/退避/流式/usage 解析
test_cost.py           (5)  成本计量
test_eval.py          (18)  五层评测+benchmark 数据完整性
test_observability.py  (7)  Span/Tracer/trace.json/JSON 日志
test_vectors.py       (11)  Embedding/VectorIndex/BM25/HybridRetriever
test_api.py            (7)  FastAPI 路由/SSE/监控页/后端切换/双跑对照
test_orchestrator.py   (4)  子任务分解/并行/降级
test_real_eval.py      (4)  LLM-as-judge 解析/真实任务硬断言(离线部分)
test_real_baseline.py  (6)  Layer 6b 裸基线两臂/工具白名单/三臂对照(离线部分)
test_performance.py    (8)  压力测试(巨型文件)
总计: 268 项(18 个测试文件,含参数化展开数量)
```

### 10.4 性能测试

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

---

## 总结:设计模式回顾

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

读完本指南后,建议按以下顺序实操(均已预装,`conda activate D:\PythonProject\mycoder\.conda` 后直接运行):

1. `.conda/python.exe -m pytest tests/` — 全部 268 项测试通过,建立"改动前基线"
2. `python examples/context_demo.py` — 直观看到上下文治理的压缩效果
3. `python -m mycoder eval --suite all --output .mycoder/eval` — 生成五层评测报告并打开 report.md
4. `python -m mycoder serve` + 浏览器打开 http://127.0.0.1:8910/ — Vue 监控页提交任务,SSE 实时看事件流
5. 阅读 `tests/test_harness.py` 理解主循环测试方式
6. 尝试修改 `config/default.yaml` 的参数(如 budget_tokens),重跑评测观察行为变化