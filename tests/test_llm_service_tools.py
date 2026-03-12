import os
import unittest


class _DummyFunction:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _DummyToolCall:
    def __init__(self, *, tool_call_id: str, name: str, arguments: str):
        self.id = tool_call_id
        self.type = "function"
        self.function = _DummyFunction(name=name, arguments=arguments)

    def model_dump(self):
        return {
            "id": self.id,
            "type": self.type,
            "function": {"name": self.function.name, "arguments": self.function.arguments},
        }


class _DummyMessage:
    def __init__(self, *, content, tool_calls):
        self.content = content
        self.tool_calls = tool_calls


class _DummyChoice:
    def __init__(self, message):
        self.message = message


class _DummyResponse:
    def __init__(self, message):
        self.choices = [_DummyChoice(message)]


class _DummyCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _RaisingCompletions:
    def __init__(self, exc: Exception):
        self.exc = exc
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        raise self.exc


class _DummyChat:
    def __init__(self, completions):
        self.completions = completions


class _DummyClient:
    def __init__(self, chat):
        self.chat = chat


class TestAskWithToolsMessages(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ.setdefault("AI_API_KEY", "test-key")

    async def test_tool_loop_executes_and_counts(self):
        from app.services.llm_service import LLMService

        tool_calls = [_DummyToolCall(tool_call_id="tc_1", name="sum", arguments='{"a": 1, "b": 2}')]
        responses = [
            _DummyResponse(_DummyMessage(content=None, tool_calls=tool_calls)),
            _DummyResponse(_DummyMessage(content="done", tool_calls=None)),
        ]
        completions = _DummyCompletions(responses)

        llm = LLMService()
        llm.client = _DummyClient(_DummyChat(completions))

        async def sum_async(a: int, b: int) -> int:
            return a + b

        content, executed = await llm.ask_with_tools_messages(
            messages=[{"role": "user", "content": None}, "bad-message"],
            tools=[{"type": "function", "function": {"name": "sum"}}],
            tool_map={"sum": sum_async},
        )

        self.assertEqual(content, "done")
        self.assertEqual(executed, 1)

        self.assertEqual(len(completions.calls), 2)
        first_messages = completions.calls[0]["messages"]
        self.assertTrue(all(isinstance(m, dict) for m in first_messages))
        self.assertEqual(first_messages[0]["role"], "user")
        self.assertEqual(first_messages[0]["content"], "")

        second_messages = completions.calls[1]["messages"]
        self.assertTrue(any(m.get("role") == "tool" and m.get("name") == "sum" for m in second_messages))

    async def test_invalid_tool_args_does_not_crash(self):
        from app.services.llm_service import LLMService

        tool_calls = [_DummyToolCall(tool_call_id="tc_bad", name="noop", arguments="{bad json")]
        responses = [
            _DummyResponse(_DummyMessage(content=None, tool_calls=tool_calls)),
            _DummyResponse(_DummyMessage(content="ok", tool_calls=None)),
        ]
        completions = _DummyCompletions(responses)

        llm = LLMService()
        llm.client = _DummyClient(_DummyChat(completions))

        def noop(**kwargs):
            return "should-not-run"

        content, executed = await llm.ask_with_tools_messages(
            messages=[{"role": "user", "content": "x"}],
            tools=[],
            tool_map={"noop": noop},
        )

        self.assertEqual(content, "ok")
        self.assertEqual(executed, 0)
        second_messages = completions.calls[1]["messages"]
        self.assertTrue(any(m.get("role") == "tool" and m.get("tool_call_id") == "tc_bad" for m in second_messages))

    async def test_llm_exception_is_raised(self):
        from app.services.llm_service import LLMService

        completions = _RaisingCompletions(RuntimeError("boom"))

        llm = LLMService()
        llm.client = _DummyClient(_DummyChat(completions))

        with self.assertRaises(RuntimeError):
            await llm.ask_with_tools_messages(
                messages=[{"role": "user", "content": "x"}],
                tools=[],
                tool_map={},
            )
