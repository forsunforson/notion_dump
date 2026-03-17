import unittest


class TestTradeAnalysisPrompt(unittest.TestCase):
    def test_build_trade_analysis_prompt_includes_investment_soul_and_profile(self):
        from app.services.prompt_manager import PromptManager

        pm = PromptManager()
        messages = pm.build_trade_analysis_prompt(
            profile="p1: v1",
            trade_logs="### 2026-03-10 T\nbody",
            as_of_date="2026-03-17",
            timezone="Asia/Shanghai",
            investment_philosophy="iph",
            monthly_goal="mgoal",
            net_worth_cny=123.0,
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("ChronoFold", messages[0]["content"])
        self.assertIn("Profile", messages[0]["content"])
        self.assertIn("p1: v1", messages[0]["content"])

        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("<trade_snapshot_logs", messages[1]["content"])
        self.assertIn("2026-03-10", messages[1]["content"])
        self.assertIn("iph", messages[1]["content"])
        self.assertIn("mgoal", messages[1]["content"])
        self.assertIn("123.0", messages[1]["content"])
