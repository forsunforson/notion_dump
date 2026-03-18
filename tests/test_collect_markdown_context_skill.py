import os
import json
import tempfile
import unittest
from pathlib import Path


class TestCollectMarkdownContextSkill(unittest.TestCase):
    def test_collects_daily_and_trade_by_days(self):
        from app.skills.context_collect_skill import collect_markdown_context

        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            os.environ["CHRONOFOLD_OUTPUT_DIR"] = td
            os.environ["PROFILE_YAML_PATH"] = str(out_dir / "profile.yaml")
            (out_dir / "profile.yaml").write_text(
                "preferences:\n  timezone: Asia/Shanghai\n", encoding="utf-8"
            )

            (out_dir / "d.md").write_text(
                """---
title: "Daily Entry"
type: "diary"
created_time: "2026-03-10T00:00:00Z"
---

ok
""",
                encoding="utf-8",
            )
            (out_dir / "t.md").write_text(
                """---
title: "Trade"
created_time: "2026-03-11T00:00:00Z"
---

Trade Snapshot Log
""",
                encoding="utf-8",
            )
            (out_dir / "b.md").write_text(
                """---
title: "Book"
type: "book_review"
created_time: "2026-03-11T00:00:00Z"
---

good book
""",
                encoding="utf-8",
            )
            (out_dir / "m.md").write_text(
                """---
title: "Movie"
type: "movie_review"
created_time: "2026-03-11T00:00:00Z"
---

good movie
""",
                encoding="utf-8",
            )
            (out_dir / "c.md").write_text(
                """---
title: "Chatlog"
category: "chatlog"
created_time: "2026-03-11T00:00:00Z"
---

hi
""",
                encoding="utf-8",
            )

            s = collect_markdown_context(
                filters={
                    "diary": {"type": "daily_entry"},
                    "trade": {"type": "trade_log"},
                    "book": {"type": "book_review"},
                    "movie": {"type": "movie_review"},
                    "chat": {"type": "chatlog"},
                },
                start_date="2026-03-10",
                end_date="2026-03-12",
                max_items_per_filter=10,
                max_chars_per_item=200,
            )
            obj = json.loads(s)
            self.assertIn("meta", obj)
            self.assertIn("filters", obj)
            self.assertEqual(obj["filters"]["diary"]["count"], 1)
            self.assertEqual(obj["filters"]["trade"]["count"], 1)
            self.assertEqual(obj["filters"]["book"]["count"], 1)
            self.assertEqual(obj["filters"]["movie"]["count"], 1)
            self.assertEqual(obj["filters"]["chat"]["count"], 1)
