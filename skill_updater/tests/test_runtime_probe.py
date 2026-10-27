import json
import os
from pathlib import Path
import subprocess

from skill_updater.tests.test_update_skills import TempDirTest
from unittest import skipUnless


@skipUnless(os.environ.get("RUNTIME_TOOL_PYTHON"), "real runtime probe runs in the dedicated runtime CI job")
class RuntimeProbeTests(TempDirTest):
    def test_real_tools_distinguish_weak_tests_and_preserve_source(self):
        script = Path(__file__).resolve().parents[1] / "runtime_probe.py"
        result = subprocess.run([
            os.environ["RUNTIME_TOOL_PYTHON"], "-B", str(script), "--root", str(self.root / "fixture"),
        ], text=True, capture_output=True, timeout=180)
        self.assertEqual(0, result.returncode, result.stderr)
        evidence = json.loads(result.stdout)
        self.assertEqual("PASS", evidence["result"])
        self.assertEqual([2.0, 2.0], evidence["crap"])
        self.assertEqual(1, evidence["duplicate_pairs"])
        self.assertEqual(12, evidence["weak_survivors"])
        self.assertEqual(12, evidence["strong_killed"])
        self.assertTrue(evidence["source_preserved"])
