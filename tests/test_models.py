"""模型后端测试:mock 脚本化语义、状态恢复、工厂装配、OpenAI 兼容解析。"""
import pytest

from mycoder.models import (LocalOpenAIBackend, MockBackend, ModelResponse,
                            create_backend, tools_to_openai)


class TestMockBackend:
    def test_script_progression(self):
        b = MockBackend(script=[{"tool_calls": [{"name": "x", "arguments": {}}]},
                                {"content": "终答"}])
        r1 = b.complete([])
        assert r1.tool_calls and r1.tool_calls[0]["name"] == "x"
        assert r1.finish_reason == "tool_calls"
        r2 = b.complete([])
        assert r2.content == "终答"
        assert r2.finish_reason == "stop"

    def test_exhausted_returns_default(self):
        b = MockBackend(default_answer="兜底")
        r = b.complete([])
        assert r.content == "兜底"

    def test_from_recipe(self):
        b = MockBackend.from_recipe(
            [{"name": "file_read", "arguments": {"path": "a.py"}}], answer="看完")
        r1 = b.complete([])
        assert r1.tool_calls[0]["name"] == "file_read"
        r2 = b.complete([])
        assert r2.content == "看完"

    def test_auto_ids(self):
        b = MockBackend(script=[{"tool_calls": [{"name": "x", "arguments": {}}]}])
        r = b.complete([])
        assert r.tool_calls[0]["id"].startswith("call_")

    @pytest.mark.parametrize("state,expect_turn", [
        ({"turn": 1, "call_seq": 2}, 1),
        ({"turn": 0, "call_seq": 0}, 0),
    ])
    def test_state_roundtrip(self, state, expect_turn):
        b = MockBackend(script=[{"content": "a"}, {"content": "b"}])
        b.load_state(state)
        assert b.state()["turn"] == expect_turn
        assert b.complete([]).content == ["a", "b"][expect_turn]

    def test_tool_call_args_preserved(self):
        b = MockBackend(script=[{"tool_calls": [{"name": "file_write",
                                                 "arguments": {"path": "p.py", "content": "x"}}]}])
        r = b.complete([])
        assert r.tool_calls[0]["arguments"] == {"path": "p.py", "content": "x"}


class TestBackendFactory:
    def test_create_mock(self):
        b = create_backend({"model": {"backend": "mock"}})
        assert isinstance(b, MockBackend)

    def test_create_unknown_raises(self):
        with pytest.raises(ValueError):
            create_backend({"model": {"backend": "nope"}})


class TestLocalOpenAI:
    def test_parse_tool_calls(self):
        body = {"choices": [{"message": {"content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "file_read", "arguments": '{"path": "a.py"}'}}]},
            "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 10}}
        b = LocalOpenAIBackend()
        r = b._parse(body)
        assert r.tool_calls[0]["id"] == "c1"
        assert r.tool_calls[0]["arguments"]["path"] == "a.py"
        assert r.usage["prompt_tokens"] == 10

    def test_parse_bad_arguments_json(self):
        body = {"choices": [{"message": {"tool_calls": [
            {"id": "c1", "function": {"name": "x", "arguments": "{bad"}}]}}]}
        r = LocalOpenAIBackend()._parse(body)
        assert "_raw" in r.tool_calls[0]["arguments"]

    def test_parse_plain_content(self):
        body = {"choices": [{"message": {"content": "你好"}, "finish_reason": "stop"}]}
        r = LocalOpenAIBackend()._parse(body)
        assert r.content == "你好"
        assert r.tool_calls == []


class TestSchemas:
    def test_tools_to_openai(self):
        from mycoder.tools import build_registry
        schemas = tools_to_openai(build_registry().all())
        assert len(schemas) == 7
        assert all(s["type"] == "function" for s in schemas)

    def test_model_response_defaults(self):
        r = ModelResponse()
        assert r.content == "" and r.tool_calls == []