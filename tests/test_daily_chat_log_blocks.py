import os
import unittest
import datetime
from zoneinfo import ZoneInfo


class _DummyDatabases:
    def __init__(self, db_obj: dict):
        self._db_obj = db_obj

    def retrieve(self, database_id: str):
        return self._db_obj


class _DummyPages:
    def __init__(self):
        self.calls = []
        self._next_id = 1

    def create(self, **kwargs):
        self.calls.append(kwargs)
        pid = f"page_{self._next_id}"
        self._next_id += 1
        return {"id": pid, "url": f"https://notion.so/{pid}"}


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
    def __init__(self, db_obj: dict, query_results: list[dict]):
        self.databases = _DummyDatabases(db_obj)
        self.pages = _DummyPages()
        self.blocks = _DummyBlocks()
        self._query_results = query_results
        self.request_calls = []

    def request(self, **kwargs):
        self.request_calls.append(kwargs)
        if kwargs.get("path", "").endswith("/query") and kwargs.get("method") == "POST":
            return {"results": self._query_results, "has_more": False, "next_cursor": None}
        return {}


class TestNotionDailyChatLogBlocks(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("NOTION_TOKEN", "test-token")
        os.environ.setdefault("NOTION_CHAT_LOGS_DB_ID", "db_chatlog")
        os.environ.setdefault("PROFILE_YAML_PATH", "/tmp/chronofold-profile-does-not-exist.yaml")

    def _make_service(self, query_results: list[dict]):
        from app.services.notion_service import NotionService

        db_obj = {
            "properties": {
                "Name": {"type": "title"},
            }
        }
        svc = NotionService(token="test-token")
        svc.client = _DummyClient(db_obj, query_results=query_results)
        return svc

    def test_creates_page_then_appends_block(self):
        svc = self._make_service(query_results=[])
        now_local = datetime.datetime(2026, 3, 10, 14, 30, 25, tzinfo=ZoneInfo("Asia/Shanghai"))

        svc._append_to_daily_chat_log_sync(role="User", content="实际内容...", now_local=now_local)

        self.assertEqual(len(svc.client.pages.calls), 1)
        props = svc.client.pages.calls[0]["properties"]
        title_prop = props["Name"]["title"][0]["text"]["content"]
        self.assertEqual(title_prop, "2026-03-10 对话实录")

        self.assertEqual(len(svc.client.blocks.children.calls), 1)
        children = svc.client.blocks.children.calls[0]["children"]
        self.assertEqual(children[0]["type"], "paragraph")
        rts = children[0]["paragraph"]["rich_text"]
        self.assertEqual(rts[0]["text"]["content"], "User [14:30:25]")
        self.assertTrue(rts[0]["annotations"]["bold"])
        self.assertEqual(rts[1]["text"]["content"], ": ")
        self.assertEqual(rts[2]["text"]["content"], "实际内容...")

    def test_uses_existing_page_when_found(self):
        svc = self._make_service(query_results=[{"id": "page_existing"}])
        now_local = datetime.datetime(2026, 3, 10, 8, 1, 2, tzinfo=ZoneInfo("Asia/Shanghai"))

        svc._append_to_daily_chat_log_sync(role="Bot", content="OK", now_local=now_local)

        self.assertEqual(len(svc.client.pages.calls), 0)
        self.assertEqual(len(svc.client.blocks.children.calls), 1)
        self.assertEqual(svc.client.blocks.children.calls[0]["block_id"], "page_existing")

    def test_accepts_data_source_id_by_falling_back_to_data_sources_query(self):
        from app.services.notion_service import NotionService

        class _DummyDataSources:
            def __init__(self, results: list[dict]):
                self._results = results
                self.calls = []

            def query(self, data_source_id: str, **kwargs):
                self.calls.append({"data_source_id": data_source_id, "kwargs": kwargs})
                return {"results": self._results, "has_more": False, "next_cursor": None}

        class _DummyDatabasesRaise:
            def __init__(self):
                self.calls = []

            def retrieve(self, database_id: str):
                self.calls.append(database_id)
                raise Exception("Invalid request URL.")

        class _DummyClientDSOnly:
            def __init__(self, ds_obj: dict, ds_results: list[dict]):
                self.databases = _DummyDatabasesRaise()
                self.data_sources = _DummyDataSources(ds_results)
                self.pages = _DummyPages()
                self.blocks = _DummyBlocks()
                self._ds_obj = ds_obj
                self.request_calls = []

            def request(self, **kwargs):
                self.request_calls.append(kwargs)
                path = kwargs.get("path") or ""
                if path.startswith("databases/") and path.endswith("/query"):
                    raise Exception("Invalid request URL.")
                if path.startswith("data_sources/") and kwargs.get("method") == "GET":
                    return self._ds_obj
                return {}

        os.environ["NOTION_CHAT_LOGS_DB_ID"] = "ds_123"
        svc = NotionService(token="test-token")
        svc.client = _DummyClientDSOnly(
            ds_obj={"properties": {"Name": {"type": "title"}}, "database_id": "db_real"},
            ds_results=[],
        )
        now_local = datetime.datetime(2026, 3, 10, 14, 30, 25, tzinfo=ZoneInfo("Asia/Shanghai"))

        svc._append_to_daily_chat_log_sync(role="User", content="hello", now_local=now_local)

        self.assertEqual(len(svc.client.pages.calls), 1)
        self.assertEqual(svc.client.pages.calls[0]["parent"]["database_id"], "db_real")
        self.assertGreaterEqual(len(svc.client.blocks.children.calls), 1)

    def test_database_with_data_sources_queries_via_data_source(self):
        from app.services.notion_service import NotionService

        class _DummyDataSources:
            def __init__(self, results: list[dict]):
                self._results = results
                self.calls = []

            def query(self, data_source_id: str, **kwargs):
                self.calls.append({"data_source_id": data_source_id, "kwargs": kwargs})
                return {"results": self._results, "has_more": False, "next_cursor": None}

        class _DummyDatabases:
            def __init__(self, db_obj: dict):
                self._db_obj = db_obj
                self.calls = []

            def retrieve(self, database_id: str):
                self.calls.append(database_id)
                return self._db_obj

        class _DummyClientDbWithDataSources:
            def __init__(self, db_obj: dict, ds_results: list[dict]):
                self.databases = _DummyDatabases(db_obj)
                self.data_sources = _DummyDataSources(ds_results)
                self.pages = _DummyPages()
                self.blocks = _DummyBlocks()
                self.request_calls = []

            def request(self, **kwargs):
                self.request_calls.append(kwargs)
                path = kwargs.get("path") or ""
                if path.startswith("databases/") and path.endswith("/query"):
                    raise Exception("Invalid request URL.")
                if path.startswith("data_sources/") and kwargs.get("method") == "GET":
                    return {"properties": {"Name": {"type": "title"}}}
                return {}

        os.environ["NOTION_CHAT_LOGS_DB_ID"] = "db_wrapper"
        svc = NotionService(token="test-token")
        svc.client = _DummyClientDbWithDataSources(
            db_obj={"data_sources": [{"id": "ds_real"}], "properties": {}},
            ds_results=[{"id": "page_existing"}],
        )
        now_local = datetime.datetime(2026, 3, 10, 9, 10, 11, tzinfo=ZoneInfo("Asia/Shanghai"))

        svc._append_to_daily_chat_log_sync(role="User", content="hello", now_local=now_local)

        self.assertEqual(len(svc.client.pages.calls), 0)
        self.assertEqual(len(svc.client.data_sources.calls), 1)
        self.assertEqual(svc.client.data_sources.calls[0]["data_source_id"], "ds_real")
        self.assertEqual(len(svc.client.blocks.children.calls), 1)
        self.assertEqual(svc.client.blocks.children.calls[0]["block_id"], "page_existing")
