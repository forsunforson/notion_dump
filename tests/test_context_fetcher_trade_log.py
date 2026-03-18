import unittest


class TestContextFetcherTradeLog(unittest.TestCase):
    def test_is_trade_log_entry_detects_action_in_frontmatter(self):
        from app.services.context_fetcher import ContextFetcher

        self.assertTrue(
            ContextFetcher.is_trade_log_entry(
                "---\naction: BUY\ncreated_time: \"2026-03-10T00:00:00Z\"\n---\n\nx"
            )
        )
        self.assertTrue(
            ContextFetcher.is_trade_log_entry(
                "---\nAction: sell\ncreated_time: \"2026-03-10T00:00:00Z\"\n---\n\nx"
            )
        )
        self.assertFalse(
            ContextFetcher.is_trade_log_entry(
                "---\naction: HOLD\ncreated_time: \"2026-03-10T00:00:00Z\"\n---\n\nx"
            )
        )
        self.assertFalse(ContextFetcher.is_trade_log_entry("nope"))
