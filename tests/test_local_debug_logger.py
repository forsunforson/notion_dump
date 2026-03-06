import json
import tempfile
import unittest
from pathlib import Path


class TestLocalDebugLogger(unittest.TestCase):
    def test_disabled_by_default_does_not_write(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "logs" / "debug.log"
            state_path = Path(td) / "logs" / "debug_state.json"

            from app.utils.local_debug_logger import LocalDebugLogger

            dbg = LocalDebugLogger(session_id="t1", log_path=log_path, state_path=state_path)
            dbg.emit("evt", {"a": 1})

            self.assertFalse(log_path.exists())

    def test_levels_write_ndjson_events(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "logs" / "debug.log"
            state_path = Path(td) / "logs" / "debug_state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({"enabled": True}), encoding="utf-8")

            from app.utils.local_debug_logger import LocalDebugLogger

            dbg = LocalDebugLogger(session_id="t2", log_path=log_path, state_path=state_path)
            dbg.debug("d", {"k": "v"})
            dbg.info("i", {"k": "v"})
            dbg.warning("w", {"k": "v"})
            dbg.error("e", {"k": "v"})

            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 4)

            events = [json.loads(line) for line in lines]
            self.assertEqual([e["level"] for e in events], ["DEBUG", "INFO", "WARNING", "ERROR"])
            self.assertTrue(all(e["sessionId"] == "t2" for e in events))
            self.assertEqual([e["name"] for e in events], ["d", "i", "w", "e"])
            self.assertTrue(all(isinstance(e["seq"], int) and e["seq"] > 0 for e in events))
            self.assertTrue(all(isinstance(e["ts"], int) and e["ts"] > 0 for e in events))

    def test_rotation_creates_backup_files(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "logs" / "debug.log"
            state_path = Path(td) / "logs" / "debug_state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({"enabled": True}), encoding="utf-8")

            from app.utils.local_debug_logger import LocalDebugLogger

            dbg = LocalDebugLogger(
                session_id="t3",
                log_path=log_path,
                state_path=state_path,
                max_bytes=300,
                backup_count=2,
            )
            payload = {"text": "x" * 200}
            for i in range(20):
                dbg.emit(f"evt{i}", payload)

            self.assertTrue(log_path.exists())
            self.assertTrue((Path(str(log_path) + ".1")).exists())
