import os
import unittest


class _DummyNotion:
    def __init__(self):
        self.calls = []

    def append_to_daily_chat_log(self, role: str, content: str):
        self.calls.append((role, content))


class _DummyResponse:
    def __init__(self, status: int, payload: dict):
        self.status = status
        self._payload = payload

    async def json(self):
        return self._payload

    async def text(self):
        return ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DummySession:
    def __init__(self, response: _DummyResponse):
        self._response = response
        self.post_calls = []

    def post(self, url, json=None, timeout=None):
        self.post_calls.append({"url": url, "json": json, "timeout": timeout})
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DummyClientSessionFactory:
    def __init__(self, response: _DummyResponse):
        self._response = response
        self.sessions = []

    def __call__(self, *args, **kwargs):
        s = _DummySession(self._response)
        self.sessions.append(s)
        return s


class TestTelegramServiceChatLog(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        os.environ["TELEGRAM_BOT_TOKEN"] = "bot-token"
        os.environ["TELEGRAM_CHAT_ID"] = "123"
        os.environ["NOTION_TOKEN"] = "test-token"

    async def test_send_message_also_appends_daily_chat_log(self):
        from unittest.mock import patch
        from app.services.telegram_service import TelegramService

        dummy_notion = _DummyNotion()
        response = _DummyResponse(status=200, payload={"ok": True})
        factory = _DummyClientSessionFactory(response)

        svc = TelegramService()
        svc.chat_log.notion = dummy_notion

        with patch("app.services.telegram_service.aiohttp.ClientSession", factory):
            ok = await svc.send_message("hello")

        self.assertTrue(ok)
        self.assertEqual(dummy_notion.calls, [("Bot", "hello")])

