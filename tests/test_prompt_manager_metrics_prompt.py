import unittest


class TestPromptManagerMetricsPrompt(unittest.TestCase):
    def test_metrics_prompt_includes_workout_scoring_rules(self):
        from app.services.prompt_manager import PromptManager

        pm = PromptManager()
        system_prompt, user_prompt = pm.build_metrics_extraction_prompts(
            raw_content="""
---
title: "Daily Entry"
tags:
- "Daily"
---
# Daily Entry

### Workout

高翻 85kg
前蹲 94kg x 3 x 6

Done:
- workout
""".strip()
        )

        self.assertIn("结构化信息抽取器", system_prompt)
        self.assertIn("workout_volume_score 判定细则", user_prompt)
        self.assertIn("Done: workout", user_prompt)
        self.assertIn("看到具体重量、组数、次数、动作数量较多时", user_prompt)
        self.assertIn("高翻 85kg", user_prompt)
