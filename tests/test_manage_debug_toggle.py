import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class TestManageDebugToggle(unittest.TestCase):
    def test_manage_sh_toggles_persisted_state(self):
        project_root = Path(__file__).resolve().parents[1]
        manage_sh = project_root / "deploy" / "manage.sh"

        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "debug_state.json"

            env = os.environ.copy()
            env["LOCAL_DEBUG_STATE_PATH"] = str(state_path)

            r1 = subprocess.run(
                ["bash", str(manage_sh), "--debug-enable"],
                cwd=str(project_root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(r1.returncode, 0, msg=r1.stderr)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIs(state.get("enabled"), True)

            r2 = subprocess.run(
                ["bash", str(manage_sh), "--debug-disable"],
                cwd=str(project_root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(r2.returncode, 0, msg=r2.stderr)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIs(state.get("enabled"), False)

