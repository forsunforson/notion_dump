import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


class _DummyConverter:
    def __init__(self, body: str):
        self.body = body
        self.page_titles = {}

    def convert_page_content(self, page_id: str) -> str:
        return self.body


class TestSyncNotionChangeDetection(unittest.IsolatedAsyncioTestCase):
    async def test_download_page_ignores_frontmatter_only_updates(self):
        from app.jobs.sync_notion import SyncNotionJob

        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            file_path = out_dir / "page-1.md"
            file_path.write_text(
                "---\n"
                'title: "Daily Entry"\n'
                'last_edited_time: "2026-04-01T00:00:00Z"\n'
                "---\n"
                "# Daily Entry\n\n"
                "same body",
                encoding="utf-8",
            )

            job = object.__new__(SyncNotionJob)
            job.notion_api = type("DummyNotionAPI", (), {"get_blocks": AsyncMock(return_value=[])})()
            job.converter = _DummyConverter("same body")
            job.processed_count = 0
            job.get_page_metadata = AsyncMock(
                return_value={
                    "title": "Daily Entry",
                    "type": "page",
                    "page_obj": {"id": "page-1"},
                }
            )

            with patch("app.jobs.sync_notion.NotionMapper.page_to_dict", return_value={"title": "Daily Entry"}), patch(
                "app.jobs.sync_notion.NotionMapper.to_yaml",
                return_value="---\n"
                'title: "Daily Entry"\n'
                'last_edited_time: "2026-04-02T00:00:00Z"\n'
                "---\n",
            ):
                saved_path = await job.download_page("page-1", out_dir, recursive=False, page_obj={"id": "page-1"})

            self.assertIsNone(saved_path)
            self.assertIn('last_edited_time: "2026-04-02T00:00:00Z"', file_path.read_text(encoding="utf-8"))

    async def test_download_page_returns_path_when_body_changes(self):
        from app.jobs.sync_notion import SyncNotionJob

        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            file_path = out_dir / "page-1.md"
            file_path.write_text(
                "---\n"
                'title: "Daily Entry"\n'
                "---\n"
                "# Daily Entry\n\n"
                "old body",
                encoding="utf-8",
            )

            job = object.__new__(SyncNotionJob)
            job.notion_api = type("DummyNotionAPI", (), {"get_blocks": AsyncMock(return_value=[])})()
            job.converter = _DummyConverter("new body")
            job.processed_count = 0
            job.get_page_metadata = AsyncMock(
                return_value={
                    "title": "Daily Entry",
                    "type": "page",
                    "page_obj": {"id": "page-1"},
                }
            )

            with patch("app.jobs.sync_notion.NotionMapper.page_to_dict", return_value={"title": "Daily Entry"}), patch(
                "app.jobs.sync_notion.NotionMapper.to_yaml",
                return_value="---\n"
                'title: "Daily Entry"\n'
                "---\n",
            ):
                saved_path = await job.download_page("page-1", out_dir, recursive=False, page_obj={"id": "page-1"})

            self.assertEqual(saved_path, file_path)
            self.assertIn("new body", file_path.read_text(encoding="utf-8"))
