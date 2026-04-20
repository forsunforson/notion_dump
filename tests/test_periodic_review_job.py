import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class _FakePromptManager:
    def load_profile(self):
        return "profile"

    def build_review_prompt(self, **kwargs):
        return [
            {"content": "system"},
            {"content": "user"},
        ]

    def build_trade_analysis_prompt(self, **kwargs):
        return [
            {"content": "trade-system"},
            {"content": "trade-user"},
        ]


class _FakeLLMService:
    async def ask_text(self, system_prompt, user_prompt, max_tokens):
        if system_prompt == "trade-system":
            return "trade analysis"
        return "review body"


class _FakeContextFetcher:
    instances = []

    def __init__(self):
        self.daily_ranges = []
        self.trade_ranges = []
        self.filters_seen = None
        type(self).instances.append(self)

    def make_daily_entry_filter(self, *, start_utc, end_utc):
        self.daily_ranges.append((start_utc, end_utc))
        return lambda raw: False

    def make_trade_log_filter(self, *, start_utc, end_utc):
        self.trade_ranges.append((start_utc, end_utc))
        return lambda raw: False

    def collect_markdown_by_filters(self, *, filters):
        self.filters_seen = set(filters.keys())
        return 0, {"diary": [], "trade": []}

    def build_entry(self, *, raw, path, include_path=False):
        return None


class TestPeriodicReviewJob(unittest.IsolatedAsyncioTestCase):
    async def test_weekly_review_uses_same_range_for_diary_trade_and_metrics(self):
        from app.jobs.periodic_review import PeriodicReviewJob

        start_date = datetime.date(2026, 4, 14)
        end_date = datetime.date(2026, 4, 20)

        with tempfile.TemporaryDirectory() as td:
            reports_dir = Path(td)

            with (
                patch("app.jobs.periodic_review.ContextFetcher", _FakeContextFetcher),
                patch("app.jobs.periodic_review.PromptManager", _FakePromptManager),
                patch("app.jobs.periodic_review.LLMService", _FakeLLMService),
                patch("app.jobs.periodic_review.REPORTS_DIR", reports_dir),
                patch.object(PeriodicReviewJob, "_load_latest_net_worth_cny", return_value=None),
                patch.object(PeriodicReviewJob, "_load_metrics_in_range", return_value=[]) as mocked_metrics,
            ):
                job = PeriodicReviewJob(review_type="weekly")
                await job.run(start_date=start_date, end_date=end_date)
                self.assertTrue(
                    job.output_path.read_text(encoding="utf-8").startswith("周报范围：2026-04-14 ~ 2026-04-20")
                )

        cf = _FakeContextFetcher.instances[-1]
        self.assertEqual(cf.filters_seen, {"diary", "trade"})
        self.assertEqual(len(cf.daily_ranges), 1)
        self.assertEqual(len(cf.trade_ranges), 1)
        self.assertEqual(cf.trade_ranges[0], cf.daily_ranges[0])
        mocked_metrics.assert_called_once_with(start_date=start_date, end_date=end_date)
