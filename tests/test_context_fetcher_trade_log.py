import unittest


class TestContextFetcherTradeLog(unittest.TestCase):
    def test_is_trade_log_entry_detects_marker(self):
        from app.services.context_fetcher import ContextFetcher

        self.assertTrue(ContextFetcher.is_trade_log_entry("x Trade Snapshot Log y"))
        self.assertTrue(ContextFetcher.is_trade_log_entry("trade snapshot log"))
        self.assertFalse(ContextFetcher.is_trade_log_entry("nope"))

