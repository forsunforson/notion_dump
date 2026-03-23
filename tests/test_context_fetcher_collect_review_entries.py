import os
import tempfile
import unittest
from pathlib import Path


class TestContextFetcherCollectReviewEntries(unittest.TestCase):
    def test_collects_diary_and_trade_entries_by_utc_range(self):
        from app.services.context_fetcher import ContextFetcher

        with tempfile.TemporaryDirectory() as td:
            os.environ["CHRONOFOLD_OUTPUT_DIR"] = td
            out_dir = Path(td)

            diary_md = """---
id: "1"
title: "Daily Entry"
type: "diary"
created_time: "2026-03-10T00:00:00Z"
---

# Daily Entry

hello
"""
            trade_md = """---
id: "2"
title: "Trade 1"
action: "SELL"
date: "2026-03-11"
created_time: "2026-03-20T00:00:00Z"
---

Trade Snapshot Log
成交均价： 12.34 HKD
"""
            (out_dir / "a.md").write_text(diary_md, encoding="utf-8")
            (out_dir / "b.md").write_text(trade_md, encoding="utf-8")

            cf = ContextFetcher()
            d0 = cf._parse_created_time_utc({"created_time": "2026-03-10T00:00:00Z"})
            d2 = cf._parse_created_time_utc({"created_time": "2026-03-12T00:00:00Z"})
            md_count, buckets = cf.collect_markdown_by_filters(
                filters={
                    "diary": cf.make_daily_entry_filter(start_utc=d0, end_utc=d2),
                    "trade": cf.make_trade_log_filter(start_utc=d0, end_utc=d2),
                }
            )
            diaries = [
                cf.build_entry(raw=it["raw"], path=it["path"]) for it in buckets.get("diary") or []
            ]
            diaries = [e for e in diaries if e]
            trades = [
                cf.build_entry(raw=it["raw"], path=it["path"], include_path=True)
                for it in buckets.get("trade") or []
            ]
            trades = [e for e in trades if e]

            self.assertEqual(md_count, 2)
            self.assertEqual(len(diaries), 1)
            self.assertEqual(len(trades), 1)
            self.assertEqual(diaries[0]["title"], "Daily Entry")
            self.assertEqual(trades[0]["title"], "Trade 1")
            self.assertEqual(trades[0]["local_date"], "2026-03-11")
