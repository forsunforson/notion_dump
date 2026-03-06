import unittest


class TestPromptManagerReviewPrompt(unittest.TestCase):
    def test_daily_review_prompt_uses_daily_kick_templates(self):
        from app.services.prompt_manager import PromptManager

        pm = PromptManager()
        messages = pm.build_review_prompt(
            review_type="daily", profile="p", metrics_trend="m", notes_content="n"
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Espresso", messages[0]["content"])

        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("## ☕ 昨日浓缩", messages[1]["content"])

    def test_weekly_review_prompt_uses_socratic_templates(self):
        from app.services.prompt_manager import PromptManager

        pm = PromptManager()
        messages = pm.build_review_prompt(
            review_type="weekly", profile="p", metrics_trend="m", notes_content="n"
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("苏格拉底式", messages[0]["content"])

        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("## 1. 冰冷的镜像", messages[1]["content"])
