import json
import os
import tempfile
import unittest
from pathlib import Path


class TestIndexGeneratorService(unittest.IsolatedAsyncioTestCase):
    async def test_update_files_writes_output_index(self):
        from app.services.index_generator import IndexGeneratorService

        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td) / "notion_output"
            profile_path = Path(td) / "profile.yaml"
            output_dir.mkdir(parents=True, exist_ok=True)
            profile_path.write_text(
                "preferences:\n"
                '  timezone: "Asia/Shanghai"\n',
                encoding="utf-8",
            )

            old_output_dir = os.environ.get("CHRONOFOLD_OUTPUT_DIR")
            old_profile_path = os.environ.get("PROFILE_YAML_PATH")
            os.environ["CHRONOFOLD_OUTPUT_DIR"] = str(output_dir)
            os.environ["PROFILE_YAML_PATH"] = str(profile_path)
            try:
                md_path = output_dir / "note-1.md"
                md_path.write_text(
                    "---\n"
                    'title: "Daily Entry"\n'
                    'type: "diary"\n'
                    'tags: ["Health", "Reflection"]\n'
                    'last_edited_time: "2026-04-08T16:30:00Z"\n'
                    "---\n"
                    "# Daily Entry\n\n"
                    "今天状态不错，训练完成，晚上复盘了交易计划。\n",
                    encoding="utf-8",
                )

                service = IndexGeneratorService(use_llm=False)
                await service.update_files([md_path])

                index_path = output_dir / "index.json"
                self.assertTrue(index_path.exists())

                data = json.loads(index_path.read_text(encoding="utf-8"))
                self.assertIn("note-1.md", data)
                self.assertEqual(data["note-1.md"]["date"], "2026-04-09")
                self.assertIsInstance(data["note-1.md"]["summary"], str)
                self.assertGreaterEqual(len(data["note-1.md"]["tags"]), 3)
                self.assertLessEqual(len(data["note-1.md"]["tags"]), 5)
            finally:
                if old_output_dir is None:
                    os.environ.pop("CHRONOFOLD_OUTPUT_DIR", None)
                else:
                    os.environ["CHRONOFOLD_OUTPUT_DIR"] = old_output_dir
                if old_profile_path is None:
                    os.environ.pop("PROFILE_YAML_PATH", None)
                else:
                    os.environ["PROFILE_YAML_PATH"] = old_profile_path

    async def test_build_entry_falls_back_to_created_time_when_needed(self):
        from app.services.index_generator import IndexGeneratorService

        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td) / "notion_output"
            profile_path = Path(td) / "profile.yaml"
            output_dir.mkdir(parents=True, exist_ok=True)
            profile_path.write_text(
                "preferences:\n"
                '  timezone: "Asia/Shanghai"\n',
                encoding="utf-8",
            )

            old_output_dir = os.environ.get("CHRONOFOLD_OUTPUT_DIR")
            old_profile_path = os.environ.get("PROFILE_YAML_PATH")
            os.environ["CHRONOFOLD_OUTPUT_DIR"] = str(output_dir)
            os.environ["PROFILE_YAML_PATH"] = str(profile_path)
            try:
                md_path = output_dir / "note-2.md"
                md_path.write_text(
                    "---\n"
                    'title: "Trade Log"\n'
                    'created_time: "2026-04-08T01:30:00Z"\n'
                    "---\n"
                    "Trade Snapshot Log\n\n"
                    "Sell some shares.\n",
                    encoding="utf-8",
                )

                service = IndexGeneratorService(use_llm=False)
                entry = await service.build_entry(md_path)

                self.assertEqual(entry["date"], "2026-04-08")
                self.assertTrue(entry["summary"])
                self.assertGreaterEqual(len(entry["tags"]), 3)
            finally:
                if old_output_dir is None:
                    os.environ.pop("CHRONOFOLD_OUTPUT_DIR", None)
                else:
                    os.environ["CHRONOFOLD_OUTPUT_DIR"] = old_output_dir
                if old_profile_path is None:
                    os.environ.pop("PROFILE_YAML_PATH", None)
                else:
                    os.environ["PROFILE_YAML_PATH"] = old_profile_path
