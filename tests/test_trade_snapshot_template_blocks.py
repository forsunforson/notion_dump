import os
import unittest


class _DummyBlocksChildren:
    def __init__(self):
        self.calls = []

    def append(self, **kwargs):
        self.calls.append(kwargs)
        return {"object": "list", "results": []}


class _DummyBlocks:
    def __init__(self):
        self.children = _DummyBlocksChildren()


class _DummyClient:
    def __init__(self):
        self.blocks = _DummyBlocks()


def _block_text(block: dict) -> str:
    t = block.get("type")
    payload = block.get(t) or {}
    rt = payload.get("rich_text") or []
    if not rt:
        return ""
    text_obj = rt[0].get("text") or {}
    return text_obj.get("content") or ""


class TestTradeSnapshotTemplateBlocks(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("NOTION_TOKEN", "test-token")
        os.environ["CHRONOFOLD_DISABLE_YFINANCE"] = "1"

    def test_appends_blocks_rendered_from_template(self):
        from app.services.notion_service import NotionService

        svc = NotionService(token="test-token")
        svc.client = _DummyClient()

        svc.append_trade_snapshot_log_to_page(
            page_id="page_1",
            ticker="02400.HK",
            action="BUY",
            price=12.34,
            quantity=100,
            cash_impact=1234.0,
            currency="HKD",
            total_amount=1234.0,
            notes="用户原话：买一点试试。",
            changes={"old_stock": 0, "new_stock": 100},
            captured_at="2026-03-10T12:00:00Z",
        )

        self.assertEqual(len(svc.client.blocks.children.calls), 1)
        children = svc.client.blocks.children.calls[0]["children"]
        self.assertTrue(any(b.get("type", "").startswith("heading_") for b in children))
        self.assertTrue(any(b.get("type") == "to_do" for b in children))

        texts = [_block_text(b) for b in children]
        self.assertTrue(any("交易标的：" in t and "02400.HK" in t for t in texts))
        self.assertTrue(any("成交均价：" in t and "12.34" in t for t in texts))

    def test_renders_market_beta_line_when_provided(self):
        from app.services.notion_service import NotionService

        template = "大盘水位 (Beta)： 恒指当日表现 [大涨 / 大跌 / 平盘]\n"
        rendered = NotionService._render_trade_snapshot_template(
            template,
            ticker="x",
            action="BUY",
            price=1.0,
            currency="HKD",
            market_beta_line="大盘水位 (Beta)： 恒生科技指数当日表现 大涨 (+2.00%)",
        )
        self.assertIn("恒生科技指数", rendered)
