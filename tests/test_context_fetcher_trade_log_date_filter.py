import os
import tempfile
import unittest
from pathlib import Path


class TestContextFetcherTradeLogDateFilter(unittest.TestCase):
    def test_trade_filter_uses_property_date_not_created_time(self):
        from app.services.context_fetcher import ContextFetcher

        with tempfile.TemporaryDirectory() as td:
            os.environ["CHRONOFOLD_OUTPUT_DIR"] = td
            out_dir = Path(td)

            trade_in_range_by_created = """---
id: "t1"
title: "Trade New Page"
action: "BUY"
date: "2026-01-01"
created_time: "2026-03-11T00:00:00Z"
---
Trade Snapshot Log
"""
            (out_dir / "t1.md").write_text(trade_in_range_by_created, encoding="utf-8")

            cf = ContextFetcher()
            start = cf._parse_created_time_utc({"created_time": "2026-03-10T00:00:00Z"})
            end = cf._parse_created_time_utc({"created_time": "2026-03-12T00:00:00Z"})
            _, buckets = cf.collect_markdown_by_filters(
                filters={"trade": cf.make_trade_log_filter(start_utc=start, end_utc=end)}
            )
            self.assertEqual(len(buckets.get("trade") or []), 0)

