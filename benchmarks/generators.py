"""参数化评测数据生成器(评测加固 P0)。

职责:用固定 seed 参数化生成五层评测数据,降低"数据与逻辑同源"的确定性 bias:
  * 样本量:每层从个位数扩到 15+(regression/context/memory 任务数、resume 场景数);
  * 负例/边界:每层 >=20% 的应失败或边界用例(kind=negative/boundary);
  * 场景标注:memory 带 memory_scenario(fresh_hit/stale/wrong_hit/missing),
    resume 带 stop_points/漂移类型/最终文件元数据,retrieval 查询带四类 type。

生成结果冻结落盘(tasks.generated.json / retrieval.json)提交入库:
既保留"改 seed 即可再生成一批"的参数化能力,又保证评测数据可审查、可 diff、可复现。

用法:
    python benchmarks/generators.py                # 用默认 seed 冻结到 benchmarks/
    python benchmarks/generators.py --seed 7       # 换 seed 再生成(压力集)
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

SEED = 20260819

_WORDS = ["alpha", "beta", "gamma", "delta", "omega", "kappa", "sigma", "lambda"]


# --------------------------------------------------------------------------
# Layer-1 regression:基础 CRUD 的正/负/边界变体
# --------------------------------------------------------------------------
def gen_regression_tasks(seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    tasks: list[dict] = []

    def _read(path: str, offset: int | None = None, limit: int | None = None) -> dict:
        args: dict = {"path": path}
        if offset is not None:
            args["offset"] = offset
        if limit is not None:
            args["limit"] = limit
        return {"name": "file_read", "arguments": args}

    def _write(path: str, content: str) -> dict:
        return {"name": "file_write", "arguments": {"path": path, "content": content}}

    def _edit(path: str, old: str, new: str, **extra) -> dict:
        return {"name": "file_edit",
                "arguments": {"path": path, "old_string": old, "new_string": new, **extra}}

    # ---- 正例 8:写入/读回/编辑/搜索 的参数化组合 ----
    for i in range(8):
        tid = f"g_reg_p{i:02d}"
        word = _WORDS[i % len(_WORDS)]
        mod = f"{word}_mod_{i}.py"
        n_lines = rng.randint(30, 120)
        marker = f"REG_P{i}_HEAD"
        keep = f"KEEP_LINE_{i} = True"
        content = (f"# {marker}\n{keep}\n"
                   + "".join(f"line_{j}: value={j}\n" for j in range(n_lines)))
        variant = i % 4
        if variant == 0:  # 写入 + 分页读回
            script = [{"tool_calls": [_write(mod, content)]},
                      {"tool_calls": [_read(mod, 0, rng.randint(10, 40))]},
                      {"content": f"已创建并读回 {mod}。"}]
            expect = {"files_created": [mod], "final_contains": mod}
        elif variant == 1:  # 嵌套路径写入 + 读回
            nested = f"pkg_{i}/src/{mod}"
            script = [{"tool_calls": [_write(nested, content)]},
                      {"tool_calls": [_read(nested, 0, 20)]},
                      {"content": f"嵌套路径 {nested} 处理完成。"}]
            expect = {"files_created": [nested], "final_contains": "完成"}
        elif variant == 2:  # 编辑精确性:只改目标行,其余不动
            new_marker = f"REG_P{i}_EDITED"
            script = [{"tool_calls": [_write(mod, content)]},
                      {"tool_calls": [_edit(mod, marker, new_marker)]},
                      {"content": "编辑完成,仅目标行变化。"}]
            expect = {"file_contains": {mod: new_marker},
                      "file_unchanged_except": {mod: keep},
                      "final_contains": "编辑完成"}
        else:  # 同轮多写 + 列目录 + 搜索
            other = f"{word}_extra_{i}.txt"
            script = [{"tool_calls": [_write(mod, content), _write(other, f"# {marker}\n")]},
                      {"tool_calls": [{"name": "file_list",
                                       "arguments": {"pattern": f"{word}_*"}}]},
                      {"tool_calls": [{"name": "grep_search",
                                       "arguments": {"pattern": marker, "path": "."}}]},
                      {"content": "多文件写入与搜索完成。"}]
            expect = {"files_created": [mod, other], "final_contains": "完成"}
        tasks.append({"task_id": tid, "layer": "regression", "kind": "positive",
                      "goal": f"参数化正例 {i}:对 {mod} 做基础文件操作。",
                      "files_hint": [mod], "script": script, "expect": expect})

    # ---- 负例 4:应失败/应被拦截 ----
    miss = f"missing_{rng.choice(_WORDS)}.txt"
    tasks.append({
        "task_id": "g_reg_n00_read_missing", "layer": "regression", "kind": "negative",
        "goal": f"读取不存在的 {miss}(应优雅失败,不崩溃)。",
        "files_hint": [miss],
        "script": [{"tool_calls": [_read(miss)]},
                   {"content": "目标文件不存在,已优雅处理。"}],
        "expect": {"should_fail_call": "file_read"},
    })
    orig = "VERSION = 1\nNAME = core\n"
    tasks.append({
        "task_id": "g_reg_n01_edit_no_match", "layer": "regression", "kind": "negative",
        "goal": "edit 的 old_string 在文件中不存在(应报错且文件不变)。",
        "files_hint": ["app_n1.py"],
        "setup_files": {"app_n1.py": orig},
        "script": [{"tool_calls": [_edit("app_n1.py", "NOT_PRESENT_STRING", "X")]},
                   {"content": "替换目标不存在,已报告错误。"}],
        "expect": {"should_fail_call": "file_edit", "file_equals": {"app_n1.py": orig}},
    })
    dup = "TAG = a\nTAG = a\n"
    tasks.append({
        "task_id": "g_reg_n02_edit_ambiguous", "layer": "regression", "kind": "negative",
        "goal": "edit 的 old_string 出现两次且未设 replace_all(应拒绝,文件不变)。",
        "files_hint": ["app_n2.py"],
        "setup_files": {"app_n2.py": dup},
        "script": [{"tool_calls": [_edit("app_n2.py", "TAG = a", "TAG = b")]},
                   {"content": "待替换串非唯一,已拒绝执行。"}],
        "expect": {"should_fail_call": "file_edit", "file_equals": {"app_n2.py": dup}},
    })
    tasks.append({
        "task_id": "g_reg_n03_unknown_param", "layer": "regression", "kind": "negative",
        "goal": "file_read 携带未知参数 bogus(参数校验应拦截)。",
        "files_hint": ["a.py"],
        "script": [{"tool_calls": [{"name": "file_read",
                                    "arguments": {"path": "a.py", "bogus": 1}}]},
                   {"content": "非法参数已被拦截。"}],
        "expect": {"should_fail_call": "file_read", "no_files_created": ["a.py"]},
    })

    # ---- 边界 3:空文件 / 控制字符 / 深嵌套路径 ----
    tasks.append({
        "task_id": "g_reg_b00_empty_file", "layer": "regression", "kind": "boundary",
        "goal": "创建并读取空文件(读取应为空而非报错)。",
        "files_hint": ["empty.txt"],
        "script": [{"tool_calls": [_write("empty.txt", "")]},
                   {"tool_calls": [_read("empty.txt")]},
                   {"content": "空文件创建并读取成功。"}],
        "expect": {"file_equals": {"empty.txt": ""}, "final_contains": "空文件"},
    })
    ctl = "CTL\x00\x01\x02END\n"
    tasks.append({
        "task_id": "g_reg_b01_control_chars", "layer": "regression", "kind": "boundary",
        "goal": "写入含控制字符的内容并读回(errors=replace 不炸)。",
        "files_hint": ["ctl.bin"],
        "script": [{"tool_calls": [_write("ctl.bin", ctl)]},
                   {"tool_calls": [_read("ctl.bin")]},
                   {"content": "控制字符内容往返完成。"}],
        "expect": {"file_equals": {"ctl.bin": ctl}, "final_contains": "往返"},
    })
    deep = "/".join(f"lvl{j}" for j in range(1, 6)) + "/deep.txt"
    tasks.append({
        "task_id": "g_reg_b02_deep_path", "layer": "regression", "kind": "boundary",
        "goal": "在 5 层深的嵌套目录写文件并读回(递归建目录)。",
        "files_hint": [deep],
        "script": [{"tool_calls": [_write(deep, "deep content\n")]},
                   {"tool_calls": [_read(deep)]},
                   {"content": "深路径写入读取完成。"}],
        "expect": {"files_created": [deep], "file_contains": {deep: "deep content"}},
    })
    return tasks


# --------------------------------------------------------------------------
# Layer-2 context:长上下文 + 保留率探针 + 折叠/贴边预算边界
# --------------------------------------------------------------------------
def gen_context_tasks(seed: int = SEED) -> list[dict]:
    rng = random.Random(seed + 1)
    tasks: list[dict] = []
    grep_pool_py = ["def func_", "return ", r"def func_[12][0-9]"]
    grep_pool_log = ["INFO", "WARN", "ERROR", "timeout"]
    for i in range(12):
        tid = f"g_ctx_c{i:02d}"
        is_py = i % 2 == 0
        word = _WORDS[i % len(_WORDS)]
        fname = f"ctx_{word}_{i}." + ("py" if is_py else "log")
        count = rng.choice([300, 500, 800, 1200])
        # 探针放在文件头部:折叠摘要截断保留头部,据此度量"信息保留率"
        probes = [f"PRB{i:02d}K{j}" for j in range(2)]
        stress = i in (6, 7)          # 多层折叠压力:更多轮次、更高 fold_min
        n_turns = rng.randint(11, 14) if stress else rng.randint(8, 11)
        turns: list[dict] = []
        turns.append({"tool_calls": [{"name": "file_read",
                                      "arguments": {"path": fname, "offset": 0, "limit": 200}}]})
        for t in range(1, n_turns):
            if t % 3 == 2:
                pat = rng.choice(grep_pool_py if is_py else grep_pool_log)
                turns.append({"tool_calls": [{"name": "grep_search",
                                              "arguments": {"pattern": pat, "path": fname}}]})
            else:
                turns.append({"tool_calls": [{"name": "file_read",
                                              "arguments": {"path": fname,
                                                            "offset": rng.randrange(0, count, 50),
                                                            "limit": rng.choice([80, 120, 200])}}]})
        turns.append({"content": f"长上下文任务 {tid} 完成。"})
        expect: dict = {"final_contains": "完成", "probe_contains": probes,
                        "fold_min": 5 if stress else 4}
        task = {"task_id": tid, "layer": "context", "kind": "positive",
                "goal": f"通读 {fname}({count} 行)并做多轮检索(长上下文+保留率探针)。",
                "files_hint": [fname],
                "generate_files": {fname: {"kind": "functions" if is_py else "logs",
                                           "count": count, "probes": probes}},
                "script": turns, "expect": expect}
        if i in (3, 9):   # 贴边预算边界:额外以极紧预算复跑,断言仍 100% 预算内
            task["budget_edge"] = True
            task["kind"] = "boundary"
        if stress:
            task["kind"] = "boundary"
        tasks.append(task)
    return tasks


# --------------------------------------------------------------------------
# Layer-3 memory:fresh_hit / stale / wrong_hit / missing 场景矩阵
# 注意:同一父任务的 follow-up 按列出顺序执行(missing 会清空记忆,须排在
# 不依赖记忆内容的场景之后),生成器已按此约束排序。
# --------------------------------------------------------------------------
def _mem_module(name: str, ver: int, j: int) -> str:
    api = f"{name}_core" if ver == 1 else f"{name}_core_v2"
    return (f"# MODULE:{name} v{ver}\n"
            f"def {api}(x):\n"
            f"    \"\"\"core operation v{ver}\"\"\"\n"
            f"    return x * {j + 2} + {ver}\n"
            f"def {name}_helper(y):\n"
            f"    return y + {j}\n")


def gen_memory_pairs(seed: int = SEED) -> list[dict]:
    rng = random.Random(seed + 2)
    tasks: list[dict] = []
    plan = [  # (name, [scenario...]) 分布:fresh2 stale3 missing2 wrong2
        ("calc", ["fresh", "stale", "missing"]),
        ("store", ["stale", "wrong", "missing"]),
        ("conv", ["fresh", "stale", "wrong"]),
    ]
    for j, (name, scenarios) in enumerate(plan):
        pid = f"g_mem_parent_{name}"
        mod = f"{name}_mod.py"
        tasks.append({
            "task_id": pid, "layer": "memory", "kind": "positive",
            "goal": f"实现 {mod},提供 {name}_core 与 {name}_helper。",
            "files_hint": [mod],
            "script": [{"tool_calls": [{"name": "file_write",
                                        "arguments": {"path": mod,
                                                      "content": _mem_module(name, 1, j)}}]},
                       {"content": f"{mod} 已实现。"}],
            "expect": {"files_created": [mod]},
        })
        for sc in scenarios:
            tid = f"g_mem_{sc}_{name}"
            caller = f"caller_{sc}_{name}.py"
            query = {"name": "memory_query",
                     "arguments": {"query": name, "kind": "all"}}
            read = {"name": "file_read", "arguments": {"path": mod}}
            control = [{"tool_calls": [dict(read)]},
                       {"tool_calls": [{"name": "file_write",
                                        "arguments": {"path": caller,
                                                      "content": f"# control\nimport {name}\n"}}]},
                       {"content": "对照组:重读后完成。"}]
            if sc == "fresh":
                script = [{"tool_calls": [query]},
                          {"tool_calls": [{"name": "file_write",
                                           "arguments": {"path": caller,
                                                         "content": f"from {name} import {name}_core\n"
                                                                    f"print({name}_core(3))\n"}}]},
                          {"content": f"已利用记忆完成 {caller},未重读 {mod}。"}]
                expect = {"files_created": [caller],
                          "file_contains": {caller: f"{name}_core(3)"}}
            elif sc == "stale":
                script = [{"tool_calls": [query]},
                          {"tool_calls": [dict(read)]},
                          {"tool_calls": [{"name": "file_write",
                                           "arguments": {"path": caller,
                                                         "content": f"from {name} import {name}_core_v2\n"
                                                                    f"print({name}_core_v2(3))\n"}}]},
                          {"content": f"检测到 {mod} 摘要过期,已重读新版本完成 {caller}。"}]
                expect = {"files_created": [caller],
                          "file_contains": {caller: f"{name}_core_v2(3)"}}
            elif sc == "missing":
                script = [{"tool_calls": [dict(read)]},
                          {"tool_calls": [{"name": "file_write",
                                           "arguments": {"path": caller,
                                                         "content": f"from {name} import {name}_core\n"
                                                                    f"print({name}_core(1))\n"}}]},
                          {"content": f"记忆缺失,已优雅降级重读 {mod} 完成 {caller}。"}]
                expect = {"files_created": [caller],
                          "file_contains": {caller: f"{name}_core(1)"}}
            else:  # wrong_hit
                script = [{"tool_calls": [query]},
                          {"tool_calls": [{"name": "file_write",
                                           "arguments": {"path": caller,
                                                         "content": f"from {name} import {name}_core\n"
                                                                    f"print({name}_core(2))\n"}}]},
                          {"content": f"记忆命中含干扰项,已选用真实的 {mod} 完成 {caller}。"}]
                expect = {"files_created": [caller],
                          "file_contains": {caller: f"{name}_core(2)"},
                          "file_not_contains": {caller: "DECOY"},
                          "final_not_contains": "DECOY_MARK"}
            task = {"task_id": tid, "layer": "memory",
                    "kind": "positive" if sc == "fresh" else "boundary",
                    "goal": f"follow-up({sc}):基于 {mod} 编写 {caller}。",
                    "files_hint": [mod, caller],
                    "follow_up_of": pid,
                    "memory_scenario": sc,
                    "script": script, "control_script": control, "expect": expect}
            if sc == "stale":
                task["scenario_mutate"] = {mod: _mem_module(name, 2, j)}
            elif sc == "missing":
                task["scenario_clear_memory"] = True
            elif sc == "wrong_hit":
                task["scenario_seed_memory_files"] = {
                    f"decoy_{name}.py": (f"# MODULE: decoy for {name}\n# DECOY_MARK_{name}\n"
                                         f"def fake_{name}(x):\n    return x\n")}
            tasks.append(task)
    assert rng  # 保留 rng 引用便于后续扩展参数化
    return tasks


# --------------------------------------------------------------------------
# Layer-4 resume:多任务结构 + 漂移类型矩阵元数据
# --------------------------------------------------------------------------
def gen_resume_tasks(seed: int = SEED) -> list[dict]:
    rng = random.Random(seed + 3)
    tasks = []
    specs = [
        ("a", "res_a", [1, 3]),
        ("b", "res_b", [2, 4]),
        ("c", "res_c", [1, 2]),
    ]
    for _j, (tag, dirname, stops) in enumerate(specs):
        tid = f"g_res_{tag}"
        script: list[dict] = []
        n_parts = rng.randint(4, 5)
        for p in range(1, n_parts + 1):
            script.append({"tool_calls": [{"name": "file_write",
                                           "arguments": {"path": f"{dirname}/part{p}.txt",
                                                         "content": f"{tid} part{p} done\n"}}]})
            if p == 2:
                script.append({"tool_calls": [{"name": "file_read",
                                               "arguments": {"path": f"{dirname}/part1.txt"}}]})
        final_rel = f"{dirname}/final.txt"
        final_content = f"{tid} final done\n"
        script.append({"tool_calls": [{"name": "file_write",
                                       "arguments": {"path": final_rel,
                                                     "content": final_content}}]})
        script.append({"tool_calls": [{"name": "file_list",
                                       "arguments": {"pattern": f"{dirname}/*"}}]})
        script.append({"content": f"{tid} 模块构建完成。"})
        tasks.append({
            "task_id": tid, "layer": "resume", "kind": "positive",
            "goal": f"分阶段构建 {dirname}/ 模块(中断/恢复/漂移场景)。",
            "files_hint": [final_rel],
            "script": script,
            "expect": {"final_contains": "构建完成"},
            "resume": {"stop_points": stops,
                       "final_files": [final_rel],
                       "final_answer_contains": "构建完成",
                       "file_contains": {final_rel: "final done"},
                       "drift_types": ["content_change", "whitespace_only",
                                       "reformat", "large_scale"]},
        })
    return tasks


# --------------------------------------------------------------------------
# Layer-5 retrieval:四类查询(exact/synonym/distractor/empty)+ 大 corpus
# --------------------------------------------------------------------------
_AUTH_DOCS = [
    ("a01", "实现了用户登录功能,包含 token 校验与会话管理。"),
    ("a02", "用户登出时清理会话状态并作废 token。"),
    ("a03", "JWT 令牌采用 HS256 签名,过期时间设为 2 小时。"),
    ("a04", "密码使用 bcrypt 加盐哈希存储,禁止明文保存。"),
    ("a05", "多因子认证支持短信验证码与邮箱链接两种方式。"),
    ("a06", "单点登录通过 SAML 协议对接企业身份提供商。"),
    ("a07", "OAuth2 授权码流程对接第三方登录。"),
    ("a08", "刷新令牌存于 HttpOnly Cookie,防止脚本窃取。"),
    ("a09", "会话超时 30 分钟无操作自动过期。"),
    ("a10", "登录连续失败五次触发账号锁定 15 分钟。"),
    ("a11", "图形验证码用于登录防爆破。"),
    ("a12", "RBAC 权限模型:角色继承菜单与接口权限。"),
    ("a13", "接口鉴权中间件校验 Bearer 令牌。"),
    ("a14", "CSRF 防护:表单携带一次性令牌。"),
    ("a15", "密码找回通过邮箱重置链接完成。"),
    ("a16", "设备指纹用于异地登录风险识别。"),
    ("a17", "API 网关统一做身份认证与限流。"),
    ("a18", "权限注解声明接口所需角色。"),
    ("a19", "用户表与角色表通过关联表映射。"),
    ("a20", "登录日志记录 IP 与 userAgent。"),
    ("a21", "令牌黑名单支持主动踢下线。"),
    ("a22", "密码强度策略:长度至少 12 且含大小写。"),
    ("a23", "扫码登录生成临时二维码票据。"),
    ("a24", "记住我功能生成持久化登录凭据。"),
    ("a25", "网关鉴权失败返回 401 并记录审计事件。"),
    ("a26", "会话数据存于 Redis 并设置 TTL。"),
]

_INFRA_DOCS = [
    ("b01", "数据库连接池最大 100 连接,空闲 60 秒回收。"),
    ("b02", "慢查询日志记录执行超过 1 秒的 SQL。"),
    ("b03", "覆盖索引优化范围查询,避免全表扫描。"),
    ("b04", "事务隔离级别默认可重复读。"),
    ("b05", "主从复制延迟超过 10 秒触发告警。"),
    ("b06", "分库分表按用户哈希路由。"),
    ("b07", "缓存穿透用空值缓存与布隆过滤器防护。"),
    ("b08", "缓存雪崩通过随机 TTL 错峰过期规避。"),
    ("b09", "缓存一致性采用先更新数据库再删缓存。"),
    ("b10", "消息队列削峰填谷,消费端批量拉取。"),
    ("b11", "网络抖动重试采用指数退避策略。"),
    ("b12", "令牌桶限流限制每秒最大请求数。"),
    ("b13", "熔断器半开状态探测下游恢复。"),
    ("b14", "降级预案返回兜底静态数据。"),
    ("b15", "核心监控指标含 QPS 与 P99 延迟。"),
    ("b16", "告警规则分级:提示、警告、严重。"),
    ("b17", "日志采集 Agent 统一收集容器 stdout。"),
    ("b18", "链路追踪注入 trace_id 贯穿全链路。"),
    ("b19", "容器编排使用 Deployment 管理副本。"),
    ("b20", "滚动发布按批次替换实例。"),
    ("b21", "灰度发布按流量百分比切换。"),
    ("b22", "自动扩缩容依据 CPU 利用率阈值。"),
    ("b23", "健康检查端点返回存活与就绪状态。"),
    ("b24", "死信队列隔离消费失败的消息。"),
]

_IO_DOCS = [
    ("c01", "文件读写工具支持相对路径与递归创建目录。"),
    ("c02", "路径沙箱拦截工作区之外的越界访问。"),
    ("c03", "Shell 命令白名单校验,拦截危险指令。"),
    ("c04", "归档解压支持 zip 与 tar 格式。"),
    ("c05", "编码转换在 UTF-8 与 GBK 之间无损切换。"),
    ("c06", "CSV 解析器处理带引号的转义字段。"),
    ("c07", "JSON 校验基于 JSON Schema 定义。"),
    ("c08", "大文件读取支持 offset 与 limit 分页。"),
    ("c09", "临时文件用完自动清理,避免残留。"),
    ("c10", "文件监听基于 inode 变更事件触发。"),
    ("c11", "符号链接创建需要显式授权。"),
    ("c12", "硬链接共享 inode 不占用额外空间。"),
    ("c13", "磁盘配额限制单用户最大存储。"),
    ("c14", "断点续传记录已下载分片偏移。"),
    ("c15", "校验和使用 SHA256 验证文件完整性。"),
    ("c16", "并发读写通过文件锁互斥。"),
    ("c17", "文本 diff 输出统一的变更块。"),
    ("c18", "正则搜索引擎支持多行模式。"),
    ("c19", "日志轮转按大小 100MB 切分。"),
    ("c20", "配置热加载监听变更并原子替换。"),
    ("c21", "管道把上一命令输出接入下一命令。"),
    ("c22", "标准输入输出重定向到文件描述符。"),
    ("c23", "环境变量注入子进程上下文。"),
    ("c24", "递归删除目录前先枚举确认非空。"),
]


def gen_retrieval_dataset(seed: int = SEED):  # seed 预留:后续压力数据集复现
    """四类查询:
      exact      —— 查询是某文档头部的原句子串 => substring 必须能命中;
      synonym    —— 同义改写无公共子串 => hybrid 应严格优于 substring;
      distractor —— 语料中不存在对应能力 => 强干扰项(avoid)不得进 top-3;
      empty      —— 与语料完全无关 => 不误召回(avoid 不进 top-3)。
    """
    tasks = [
        {
            "task_id": "r01_auth", "layer": "retrieval",
            "goal": "检索关于认证/会话/权限的记忆",
            "corpus": [{"id": i, "text": t} for i, t in _AUTH_DOCS],
            "queries": [
                {"q": "包含 token 校验与会话管理", "relevant": ["a01"], "type": "exact"},
                {"q": "bcrypt 加盐哈希存储", "relevant": ["a04"], "type": "exact"},
                {"q": "会话超时 30 分钟", "relevant": ["a09"], "type": "exact"},
                {"q": "图形验证码", "relevant": ["a11"], "type": "exact"},
                {"q": "角色继承菜单与接口权限", "relevant": ["a12"], "type": "exact"},
                {"q": "登入流程的会话校验", "relevant": ["a01"], "type": "synonym"},
                {"q": "密码加密存储方案", "relevant": ["a04"], "type": "synonym"},
                {"q": "双因素身份验证", "relevant": ["a05"], "type": "synonym"},
                {"q": "企业身份提供商 SAML 协议", "relevant": ["a06"], "type": "synonym"},
                {"q": "第三方授权接入", "relevant": ["a07"], "type": "synonym"},
                {"q": "刷新令牌 HttpOnly Cookie", "relevant": ["a08"], "type": "synonym"},
                {"q": "如何注销账号并永久删除全部个人数据", "relevant": [],
                 "avoid": ["a02", "a15"], "type": "distractor"},
                {"q": "人脸识别门禁硬件选型", "relevant": [],
                 "avoid": ["a04", "a12"], "type": "distractor"},
                {"q": "社交平台好友关系图谱分析", "relevant": [],
                 "avoid": ["a19"], "type": "distractor"},
                {"q": "量子计算原理与量子门电路", "relevant": [],
                 "avoid": ["a03", "a26"], "type": "empty"},
                {"q": "川菜麻辣火锅底料配方", "relevant": [],
                 "avoid": ["a01", "a20"], "type": "empty"},
                {"q": "火星探测器着陆轨道设计", "relevant": [],
                 "avoid": ["a17"], "type": "empty"},
            ],
        },
        {
            "task_id": "r02_infra", "layer": "retrieval",
            "goal": "检索关于数据/缓存/发布运维的记忆",
            "corpus": [{"id": i, "text": t} for i, t in _INFRA_DOCS],
            "queries": [
                {"q": "空闲 60 秒回收", "relevant": ["b01"], "type": "exact"},
                {"q": "指数退避", "relevant": ["b11"], "type": "exact"},
                {"q": "先更新数据库再删缓存", "relevant": ["b09"], "type": "exact"},
                {"q": "数据库连接不够用如何扩容池", "relevant": ["b01"], "type": "synonym"},
                {"q": "哪条 SQL 执行太慢怎么排查", "relevant": ["b02"], "type": "synonym"},
                {"q": "流量高峰消息堆积如何平滑", "relevant": ["b10"], "type": "synonym"},
                {"q": "下游故障时自动熔断保护", "relevant": ["b13"], "type": "synonym"},
                {"q": "大数据离线数仓 ETL 调度平台选型", "relevant": [],
                 "avoid": ["b17", "b15"], "type": "distractor"},
                {"q": "机房物理服务器采购与上架", "relevant": [],
                 "avoid": ["b07"], "type": "distractor"},
                {"q": "有机化学实验安全操作规程", "relevant": [],
                 "avoid": ["b04"], "type": "empty"},
                {"q": "宋代青花瓷鉴定要点", "relevant": [],
                 "avoid": ["b04"], "type": "empty"},
            ],
        },
        {
            "task_id": "r03_file_io", "layer": "retrieval",
            "goal": "检索关于文件/IO/工具链的记忆",
            "corpus": [{"id": i, "text": t} for i, t in _IO_DOCS],
            "queries": [
                {"q": "递归创建目录", "relevant": ["c01"], "type": "exact"},
                {"q": "offset 与 limit 分页", "relevant": ["c08"], "type": "exact"},
                {"q": "按大小 100MB 切分", "relevant": ["c19"], "type": "exact"},
                {"q": "怎么新建深层文件夹并写入内容", "relevant": ["c01"], "type": "synonym"},
                {"q": "特别大的文件怎么分段读", "relevant": ["c08"], "type": "synonym"},
                {"q": "两个进程同时写一个文件怎么办", "relevant": ["c16"], "type": "synonym"},
                {"q": "网盘产品会员定价与容量套餐", "relevant": [],
                 "avoid": ["c14"], "type": "distractor"},
                {"q": "区块链存储证明共识算法", "relevant": [],
                 "avoid": ["c15"], "type": "distractor"},
                {"q": "爵士乐即兴演奏技巧", "relevant": [],
                 "avoid": ["c18"], "type": "empty"},
                {"q": "亲子露营装备清单", "relevant": [],
                 "avoid": ["c04"], "type": "empty"},
            ],
        },
    ]
    return {"tasks": tasks}


# --------------------------------------------------------------------------
# 冻结落盘
# --------------------------------------------------------------------------
def freeze(seed: int = SEED, out_dir: str | Path = "benchmarks") -> dict:
    out = Path(out_dir)
    tasks = (gen_regression_tasks(seed) + gen_context_tasks(seed)
             + gen_memory_pairs(seed) + gen_resume_tasks(seed))
    (out / "tasks.generated.json").write_text(
        json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "retrieval.json").write_text(
        json.dumps(gen_retrieval_dataset(seed), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    by = {}
    for t in tasks:
        by[t["layer"]] = by.get(t["layer"], 0) + 1
    return {"seed": seed, "generated_tasks": len(tasks), "by_layer": by}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="冻结参数化评测数据到 benchmarks/")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out-dir", default=str(Path(__file__).resolve().parent))
    args = ap.parse_args()
    print(json.dumps(freeze(args.seed, args.out_dir), ensure_ascii=False))
