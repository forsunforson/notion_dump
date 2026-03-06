import os
import unittest


class _DummyDatabases:
    def __init__(self, db_obj: dict):
        self._db_obj = db_obj

    def retrieve(self, database_id: str):
        return self._db_obj


class _DummyPages:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return {"id": "page_1", "url": "https://notion.so/page_1"}


class _DummyClient:
    def __init__(self, db_obj: dict):
        self.databases = _DummyDatabases(db_obj)
        self.pages = _DummyPages()

    def request(self, **kwargs):
        return {}


class TestNotionInboxContextBlocks(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("NOTION_TOKEN", "test-token")
        os.environ.setdefault("NOTION_INBOX_DATABASE_ID", "db_test")

    def _make_service(self):
        from app.services.notion_service import NotionService

        db_obj = {
            "properties": {
                "Name": {"type": "title"},
                "source": {"type": "rich_text"},
                "category": {"type": "select"},
                "captured_at": {"type": "date"},
            }
        }
        svc = NotionService(token="test-token")
        svc.client = _DummyClient(db_obj)
        return svc

    def test_append_to_inbox_with_context_question_adds_quote_then_paragraph(self):
        svc = self._make_service()
        svc.append_to_inbox(content="A1", context_question="Q1", source="Telegram", category="reflection")

        self.assertEqual(len(svc.client.pages.calls), 1)
        children = svc.client.pages.calls[0]["children"]
        self.assertGreaterEqual(len(children), 2)
        self.assertEqual(children[0]["type"], "quote")
        self.assertEqual(children[0]["quote"]["rich_text"][0]["text"]["content"], "Q1")
        self.assertEqual(children[1]["type"], "paragraph")
        self.assertEqual(children[1]["paragraph"]["rich_text"][0]["text"]["content"], "A1")

    def test_append_to_inbox_without_context_question_keeps_paragraph_only(self):
        svc = self._make_service()
        svc.append_to_inbox(content="A1", context_question="", source="Telegram", category="reflection")

        children = svc.client.pages.calls[0]["children"]
        self.assertGreaterEqual(len(children), 1)
        self.assertEqual(children[0]["type"], "paragraph")

