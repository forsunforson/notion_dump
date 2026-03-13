import tempfile
import unittest
from pathlib import Path


class TestPromptManagerTelegramBotSoul(unittest.TestCase):
    def test_telegram_bot_system_prompt_appends_soul_when_present(self):
        from app.services.prompt_manager import PromptManager

        pm = PromptManager()
        with tempfile.TemporaryDirectory() as d:
            soul_path = Path(d) / "SOUL.md"
            soul_path.write_text("使命：保持清醒", encoding="utf-8")
            pm.soul_path = soul_path
            pm._soul_str = None

            system_prompt = pm.get_telegram_bot_system_prompt(
                user_name="u",
                primary_goals="g",
                timezone_str="t",
                today_str="2026-03-13",
                time_str="10:00",
                custom_traits={},
            )

            self.assertIn("# SOUL.md (使命锚点)", system_prompt)
            self.assertIn("使命：保持清醒", system_prompt)

    def test_telegram_bot_system_prompt_does_not_append_soul_when_missing(self):
        from app.services.prompt_manager import PromptManager

        pm = PromptManager()
        with tempfile.TemporaryDirectory() as d:
            pm.soul_path = Path(d) / "SOUL.md"
            pm._soul_str = None

            system_prompt = pm.get_telegram_bot_system_prompt(
                user_name="u",
                primary_goals="g",
                timezone_str="t",
                today_str="2026-03-13",
                time_str="10:00",
                custom_traits={},
            )

            self.assertNotIn("# SOUL.md (使命锚点)", system_prompt)
