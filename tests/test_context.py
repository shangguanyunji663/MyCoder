"""上下文治理测试:token 估算、折叠、硬限额强制、拷贝安全。"""
from mycoder.context import (
    ContextManager,
    DeterministicSummarizer,
    NoopSummarizer,
    estimate_messages,
    estimate_tokens,
)
from mycoder.state import Message
from mycoder.util import truncate


class TestTokens:
    def test_cjk_one_per_char(self):
        assert estimate_tokens("你好世界") == 4

    def test_ascii_four_per_token(self):
        assert estimate_tokens("abcd") == 1
        assert estimate_tokens("abcdefgh") == 2

    def test_empty(self):
        assert estimate_tokens("") == 0

    def test_messages_sum(self):
        msgs = [Message("user", "你好"), Message("tool", "abcd")]
        # 每个消息:4 token 结构开销 + 内容 token(你好=2, abcd=1)
        assert estimate_messages(msgs) == (4 + 2) + (4 + 1)


class TestAssemble:
    def test_base_only(self, config):
        cm = ContextManager(config)
        cm.set_task("写一个 hello.py", ["hello.py"])
        msgs = cm.assemble()
        assert msgs[0].role == "system"
        roles = [m.role for m in msgs]
        assert roles.count("user") == 1  # 任务目标
        assert any("hello.py" in m.content for m in msgs)  # 当前处理文件

    def test_no_prune_short(self, config):
        cm = ContextManager(config)
        cm.set_task("t")
        cm.append_turn(Message("assistant", "小"),
                       [Message("tool", "小结果", name="file_read")])
        cm.assemble()
        assert not cm.last_prune.pruned

    def test_fold_old_turns(self, config):
        cm = ContextManager(config)
        cm.set_task("t")
        for i in range(10):  # 超过 keep_last_turns=6
            cm.append_turn(Message("assistant", f"步骤{i}"),
                           [Message("tool", f"结果{i}" * 200, name="file_read")])
        msgs = cm.assemble()
        assert cm.last_prune.pruned
        assert "fold_old_turns" in cm.last_prune.strategies
        assert any("历史摘要" in m.content for m in msgs)

    def test_ratio_magnitude(self, config):
        cm = ContextManager(config)
        cm.set_task("t")
        for i in range(12):
            cm.append_turn(Message("assistant", f"a{i}"),
                           [Message("tool", "长内容" * 300 + str(i % 9), name="file_read")])
        cm.assemble()
        before = cm.last_prune.before_tokens
        after = cm.last_prune.after_tokens
        assert after < before
        assert cm.last_prune.ratio > 0.3  # 压缩效果明显

    def test_hard_limit_enforced(self, config):
        cfg = config
        cfg.set("context.budget_tokens", 500)
        cfg.set("context.hard_limit_tokens", 600)
        cfg.set("context.keep_last_turns", 3)
        cm = ContextManager(cfg)
        cm.set_task("t")
        for _i in range(8):
            cm.append_turn(Message("assistant", "x" * 400),
                           [Message("tool", "内容" * 2000, name="file_read")])
        msgs = cm.assemble()
        assert estimate_messages(msgs) <= 600
        assert any(s in cm.last_prune.strategies
                   for s in ("drop_stale_turns", "truncate_long_content"))

    def test_does_not_mutate_history(self, config):
        cm = ContextManager(config)
        cm.set_task("t")
        for i in range(8):
            cm.append_turn(Message("assistant", f"a{i}"),
                           [Message("tool", "长" * 500, name="file_read")])
        before = [t["tool"][0].content for t in cm.raw_turns]
        cm.assemble()
        cm.assemble()
        after = [t["tool"][0].content for t in cm.raw_turns]
        assert before == after  # 裁剪不污染原始历史

    def test_memory_block_injected(self, config):
        cm = ContextManager(config)
        cm.set_task("t", memory_block="# 结构化记忆\n- 父任务摘要")
        msgs = cm.assemble()
        assert any("结构化记忆" in m.content for m in msgs)

    def test_deterministic_replay(self, config):
        cm1, cm2 = ContextManager(config), ContextManager(config)
        for cm in (cm1, cm2):
            cm.set_task("t")
            for i in range(7):
                cm.append_turn(Message("assistant", f"a{i}"),
                               [Message("tool", f"结果{i}H" * 100, name="file_read")])
        assert estimate_messages(cm1.assemble()) == estimate_messages(cm2.assemble())


class TestSummarizer:
    def test_deterministic_output(self):
        s = DeterministicSummarizer()
        out = s.summarize_turn(1, "结论文字结论", [("file_read", "文件内容很长")])
        assert "[步骤 1]" in out and "file_read" in out

    def test_noop(self):
        s = NoopSummarizer()
        assert "已折叠" in s.summarize_turn(2, "x", [("t", "y")])

    def test_truncate_util(self):
        assert len(truncate("a" * 1000, 100)) <= 100
        assert truncate("short", 100) == "short"


class TestLLMSummarizer:
    def test_without_backend_falls_back_to_deterministic(self):
        from mycoder.context import LLMSummarizer
        s = LLMSummarizer(backend=None)
        out = s.summarize_turn(1, "结论", [("file_read", "内容")])
        assert "[步骤 1]" in out

    def test_uses_backend_content(self):
        from mycoder.context import LLMSummarizer
        from mycoder.models import MockBackend
        # 无脚本、固定 default_answer => 每次摘要都返回同一文本
        backend = MockBackend(script=[], default_answer="模型摘要:完成")
        s = LLMSummarizer(backend=backend)
        out = s.summarize_turn(1, "x", [("file_read", "y")])
        assert "模型摘要" in out

    def test_backend_failure_falls_back(self):
        from mycoder.context import LLMSummarizer

        class _Broken:
            def complete(self, *a, **k):
                raise ConnectionError("down")

        s = LLMSummarizer(backend=_Broken())
        out = s.summarize_turn(1, "结论", [("file_read", "内容")])
        assert "[步骤 1]" in out

    def test_empty_backend_content_falls_back(self):
        from mycoder.context import LLMSummarizer
        from mycoder.models import MockBackend
        backend = MockBackend(script=[], default_answer="   ")
        s = LLMSummarizer(backend=backend)
        out = s.summarize_turn(1, "结论", [("file_read", "内容")])
        assert "[步骤 1]" in out
