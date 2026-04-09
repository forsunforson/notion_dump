import unittest
from unittest.mock import AsyncMock, patch


class _DummyMessage:
    def __init__(self, text: str):
        self.text = text
        self.reply_to_message = None
        self.replies: list[str] = []

    async def reply_text(self, text: str):
        self.replies.append(text)


class _DummyChat:
    def __init__(self, chat_id: int):
        self.id = chat_id


class _DummyUser:
    def __init__(self, first_name: str = "Tester"):
        self.first_name = first_name


class _DummyUpdate:
    def __init__(self, text: str, chat_id: int = 123):
        self.message = _DummyMessage(text)
        self.effective_chat = _DummyChat(chat_id)
        self.effective_user = _DummyUser()


class _DummyChatLog:
    def __init__(self):
        self.calls = []

    def log_message(self, role: str, content: str):
        self.calls.append((role, content))


class TestTelegramBotRunnerCommands(unittest.IsolatedAsyncioTestCase):
    def _make_runner(self):
        from app.jobs.bot_runner import TelegramBotRunner

        runner = object.__new__(TelegramBotRunner)
        runner.allowed_chat_id = 123
        runner.chat_log = _DummyChatLog()
        runner.llm = None
        runner.fetcher = None
        runner.prompt_manager = None
        runner._history_by_chat = {}
        return runner

    async def test_bot_command_returns_online_status(self):
        runner = self._make_runner()
        update = _DummyUpdate("/bot")

        await runner.handle_message(update, None)

        self.assertEqual(update.message.replies, ["✅ Telegram Bot is online."])

    async def test_sync_command_calls_run_sync_job(self):
        runner = self._make_runner()
        update = _DummyUpdate("/sync")

        with patch("main.run_sync_job", new=AsyncMock()) as mocked:
            await runner.handle_message(update, None)

        mocked.assert_awaited_once()
        self.assertEqual(update.message.replies, ["✅ Sync completed."])

    async def test_index_command_rebuilds_index_and_replies_count(self):
        runner = self._make_runner()
        update = _DummyUpdate("/index")

        service = AsyncMock()
        service.rebuild_all.return_value = {"a.md": {}, "b.md": {}}

        with patch("app.services.index_generator.IndexGeneratorService", return_value=service):
            await runner.handle_message(update, None)

        service.rebuild_all.assert_awaited_once()
        self.assertEqual(update.message.replies, ["✅ Index rebuilt. 2 files indexed."])

    async def test_help_command_outputs_supported_list(self):
        runner = self._make_runner()
        update = _DummyUpdate("/help")

        await runner.handle_message(update, None)

        self.assertTrue(update.message.replies)
        self.assertIn("/sync", update.message.replies[0])
        self.assertIn("/index", update.message.replies[0])

    async def test_log_commands_read_last_100_lines(self):
        from pathlib import Path
        runner = self._make_runner()
        logs_dir = Path(__file__).resolve().parents[1] / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "bot.log").write_text("a\n" * 120, encoding="utf-8")
        (logs_dir / "execution.log").write_text("x\n" * 60, encoding="utf-8")

        with patch("app.jobs.bot_runner.TelegramBotRunner._logs_dir", return_value=logs_dir):
            update1 = _DummyUpdate("/bot_log")
            await runner.handle_message(update1, None)
            self.assertTrue(update1.message.replies)
            self.assertIn("bot.log", update1.message.replies[0])

            update2 = _DummyUpdate("/execution_log")
            await runner.handle_message(update2, None)
            self.assertTrue(update2.message.replies)
            self.assertIn("execution.log", update2.message.replies[0])
