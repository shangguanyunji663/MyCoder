# Web 端后端自由切换 + 一键双跑 A/B 对比 —— 设计与实施记录

> **状态**:方案已评审批准(2026-08-27),本文档为实施依据与变更记录。
> **定位**:补全"重在对比"架构叙事的最后一环——把 Mock 与真实模型(Ollama)的切换从"改配置+重启"降为零成本点击,并提供一键双跑对照。

---

## 一、必要性与背景

1. **切换摩擦高**:此前网页端想换执行后端必须修改 `config/default.yaml` 并重启服务,而核心工作流(离线演示 ⇄ 真模型干活 ⇄ 对比实验)恰恰需要反复横跳。
2. **名不符实待修正**:页面标签原本就写着"Mock script(留空走真实后端)",UI 心智上已有"选后端"概念,只是缺少控件。(该处代码缺陷——页面总是携带空 script 导致永远走 Mock——已于本次会话先行修复。)
3. **把"对比"变成日常操作**:同一目标 Mock 回放一次 + Ollama 真跑一次并排展示,系统收益与模型表现直接可比,呼应"重在对比"的产品定位。
4. **质量底线零妥协**:评测 Layer 1-5 与全部 pytest 用例(设计时为 258 项,现为 272 项)显式使用 MockBackend,不读此开关,"以 MOCK 为主"的原则不受影响。

## 二、可行性结论(基于代码事实)

| 判断 | 结论 |
|---|---|
| 服务端挂载点 | `fastapi_server.py` 的 `_build_backend()` 本就是"按请求选后端"的唯一收口点(13 行小函数),加可选参数即可 |
| 后端构造 | 复用现有 `create_backend(config)` 工厂,仅需向本任务的 Config 深拷贝注入 `model.backend` |
| 配置隔离 | 每任务 worker 已执行 `Config(config.to_dict())` 深拷贝,按请求覆盖互不污染 |
| 页面改动面 | 仅新增一个三档下拉与请求体可选字段,SSE 流与任务列表主体逻辑零改动 |
| 测试安全性 | 通过 monkeypatch 替身工厂断言"选对了后端",单测绝不真发 HTTP |

## 三、已确认的产品决策(2026-08-27)

| 问题 | 决策 |
|---|---|
| 切换粒度 | **仅三档**:跟随配置默认 / Mock(离线演示) / Ollama(local_openai);模型名一律来自配置文件,不在页面透传模型名、温度等参数 |
| 一键 A/B 对比 | **要做**:`POST /api/compare` 同一目标自动提交两臂任务(mock 臂 + ollama 臂),共享 compare_group 分组标识 |

## 四、总体原则

**以 MOCK 为主**:评测体系(Layer 1-5)、pytest 全量用例、CI 继续锁定 MockBackend。本功能只赋予**网页执行入口**运行期选择权;评测的数据口径不发生任何变化。

## 五、详细设计

### 5.1 接口协议

```
POST /api/run          入参增量: {backend?: "mock"|"local_openai"}
                       规则: 缺省=跟随服务端配置;script 非空时无论选什么都锁定 Mock
POST /api/compare      新增。入参 {goal, script?, follow_up_of?}
                       行为: 生成 compare_id,自动提交两臂:
                         arm-mock   = 强制 MockBackend(script 生效)
                         arm-local  = 强制 local_openai(忽略 script)
                       返回: {compare_id, task_ids:[mock_id, real_id]}
GET  /api/run/{id}     快照透出新字段: backend(实际使用)/arm/compare_group
GET  /api/runs         列表同步携带上述三元组,前端据此分组渲染
```

### 5.2 服务端改造(mycoder/api/fastapi_server.py)

- `_build_backend(cfg, task_data)` 升级:解析优先级 `显式 backend 字段 > script 存在 > 配置默认`;注入配置副本的 `model.backend` 后交工厂构造,返回 `(backend, resolved_name)`
- 任务记录持久化三元组 `{backend, arm, compare_group}`,随快照与列表接口透出
- stdlib 版 server.py **保持不动**(Mock-only,与既有文档口径一致)

### 5.3 前端改造(mycoder/api/monitor_page.py)

1. 提交卡新增「执行后端」三选一控件;非"跟随配置"档才将 backend 写入请求体
2. 新增「▶ 双跑对比」按钮 → POST /api/compare → 同时订阅两臂 SSE
3. 任务列表行追加臂标签(`[mock]` / `[ollama]`)与 compare_group 标识
4. 新增「最新对比」区块:同组两臂均结束后,并排显示两列指标(状态/步骤/工具调用/Token/成本/耗时);数据复用现有轮询接口

## 六、实施步骤

| 步骤 | 内容 | 状态 |
|---|---|---|
| 0 | 撰写本设计记录文档;**回滚** `config/default.yaml` 的 `model.backend` 至 `mock`(撰写前曾临时翻转,见附注) | ✅ 已完成 |
| 1 | 服务端改造(5.2):_decide_backend 纯决策函数 + _build_backend 按名构造 + _launch 公共提交通道 + /api/compare 路由 | ✅ 已完成 |
| 2 | 前端改造(5.3) | ✅ 已完成 |
| 3 | 测试增补(tests/test_api.py 新增 4 用例:非法 backend 400/显式 local_openai 注入生效/script 锁 mock 工厂不被触发/compare 两臂元数据与 compare_id 正确);全量 pytest **262 收集,260 passed + 2 skipped**;ruff 全绿;mypy 干净(补一处存量 narrow ignore) | ✅ 已完成 |
| 4 | 文档同步:README API 小节、ARCHITECTURE API 层路由表、LEARNING_GUIDE 10.2 端点块、CHANGELOG Added/Fixed 各两条 | ✅ 已完成 |

**实施中额外发现并修复的生产缺陷**(超出原计划,已记入 CHANGELOG Fixed):
`tools/sandbox.py` 的 `snapshot()` 遍历用 `rglob('*') 先全量展开再过滤`,工作区位于大型项目根时每次 checkpoint 都白扫 `.conda/.mimosa` 数万条目——正是新测试在仓库根运行暴露的;改为 `os.walk` 进入前剪枝后语义不变(点文件/隐藏目录/__pycache__ 均仍排除,由既有 test_snapshot_excludes_hidden_and_pycache 守护),API 测试组耗时从 ~26s 降至 ~3s。

## 七、风险与对策

| 风险 | 对策 |
|---|---|
| 单测误连 Ollama | monkeypatch 替身工厂,只断言类型与注入配置 |
| Ollama 未启动 | 异常沿现有 worker 错误事件进入 SSE;验收专查错误文案是否人话 |
| 真实臂耗时长、页面久等 | 实时状态 + SSE 流式天然覆盖,不引入超时逻辑 |

## 八、验收清单

1. 自动化:pytest 全绿、ruff check 通过
2. 手工(Ollama 在线):三档提交行为各自正确;Ollama 臂 SSE 出现 model_call 且 Token>0;Mock 臂秒回剧本
3. 双跑:一次点击产生同组两任务,完成后「最新对比」出现并排指标
4. 故障态:停掉 Ollama 点对比,mock 臂正常完成、ollama 臂失败且理由清晰可读

## 九、明确不做(范围外)

- 页面透传模型名/温度等采样参数
- stdlib 实现的真实后端支持
- 评测体系的任何改动(继续全 Mock)
- LLM-as-judge 超时优化(独立议题,已在 FINAL_SUMMARY 记录短板)

---

## 附注:设计定稿时的仓库现状备忘

- `config/default.yaml` 在设计讨论期间被临时翻转为 `backend: local_openai`(qwen3.5:2b@11434)——早于"以 MOCK 为主"决策确认,**实施第 0 步必须先回滚**,并以注释说明切换方式。
- `mycoder/api/monitor_page.py` 中"总是携带空 script 导致页面永远走 Mock"的缺陷已在设计方案确定前修复(改为有脚本才携带字段),API 测试 3 项通过;该项 Fixed 尚未记入 CHANGELOG,随实施第 4 步一并补记。
