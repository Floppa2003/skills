import json
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path

from skill_updater.tests.test_update_skills import TempDirTest, commit_all, git_repo, write


SCRIPT = Path(__file__).resolve().parents[1] / "check_refresh_result.py"


class RefreshPublicationTests(TempDirTest):
    def setUp(self):
        super().setUp()
        self.repo = git_repo(self.root / "repo")
        self.registry = {"skills": [{"name": "good"}, {"name": "blocked"}]}
        write(self.repo / "skill_updater/registry.json", json.dumps(self.registry))
        write(self.repo / "skills/blocked/SKILL.md", "preserved\n")
        write(self.repo / "skills/good/SKILL.md", "original\n")
        commit_all(self.repo)
        self.events = [
            {"skill": "good", "status": "updated", "stage": "replacement", "message": "updated"},
            {"skill": "blocked", "status": "error_skip", "stage": "overlay",
             "message": "patch conflict", "installed_copy_preserved": True},
        ]
        write(self.repo / "skills/good/SKILL.md", "updated\n")

    def run_gate(self, exit_code=2):
        summary = {
            "events": self.events,
            "errors": [e for e in self.events if e["status"] == "error_skip"],
            "counts": dict(Counter(e["status"] for e in self.events)),
        }
        write(self.repo / "summary.json", json.dumps(summary))
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--exit-code", str(exit_code),
             "--summary", "summary.json", "--base", "HEAD",
             "--output", "output", "--report", "report.md"],
            cwd=self.repo, text=True, capture_output=True,
        )

    def test_complete_partial_refresh_is_publishable_and_explicit(self):
        result = self.run_gate()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("partial=true\n", (self.repo / "output").read_text())
        self.assertIn("blocked", (self.repo / "report.md").read_text())

    def test_success_is_not_reported_as_partial(self):
        self.events[1] = {"skill": "blocked", "status": "unchanged", "stage": "compare"}
        result = self.run_gate(0)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("partial=false\n", (self.repo / "output").read_text())

    def test_global_or_post_preparation_errors_block_publication(self):
        for stage in ("registry_state", "cleanup", "lock", "recovery", "replacement", "runtime_setup"):
            with self.subTest(stage=stage):
                self.events[1]["stage"] = stage
                self.assertNotEqual(0, self.run_gate().returncode)
                self.assertFalse((self.repo / "output").exists())

    def test_incomplete_run_cannot_publish_successful_subset(self):
        self.events.pop()
        self.assertNotEqual(0, self.run_gate(0).returncode)
        self.assertFalse((self.repo / "output").exists())

    def test_interruption_does_not_accept_old_summary(self):
        self.assertNotEqual(0, self.run_gate(130).returncode)
        self.assertFalse((self.repo / "output").exists())

    def test_failed_skill_files_must_be_unchanged(self):
        write(self.repo / "skills/blocked/SKILL.md", "changed despite failure\n")
        self.assertNotEqual(0, self.run_gate().returncode)
        self.assertFalse((self.repo / "output").exists())

    def test_failed_skill_registry_must_be_unchanged(self):
        self.registry["skills"][1]["installed_commit"] = "unverified"
        write(self.repo / "skill_updater/registry.json", json.dumps(self.registry))
        self.assertNotEqual(0, self.run_gate().returncode)
        self.assertFalse((self.repo / "output").exists())

    def test_local_drift_cannot_be_mistaken_for_success(self):
        self.events[1] = {"skill": "blocked", "status": "expected_skip", "stage": "local_drift"}
        self.assertNotEqual(0, self.run_gate(0).returncode)
        self.assertFalse((self.repo / "output").exists())

    def test_exit_code_and_errors_must_agree(self):
        self.assertNotEqual(0, self.run_gate(0).returncode)
        self.assertFalse((self.repo / "output").exists())

    def register_runtime(self):
        runtime = {"name": "ub-mode-tools", "packages": [{"commit": "a" * 40}]}
        self.registry["runtime_tools"] = [runtime]
        write(self.repo / "skill_updater/registry.json", json.dumps(self.registry))
        subprocess.run(["git", "add", "skill_updater/registry.json"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "runtime baseline"], cwd=self.repo, check=True, capture_output=True)
        return runtime

    def test_partial_refresh_accounts_for_runtime_once(self):
        self.register_runtime()
        self.events.append({"skill": "runtime:ub-mode-tools", "status": "unchanged", "stage": "compare"})
        result = self.run_gate()
        self.assertEqual(0, result.returncode, result.stderr)

    def test_failed_runtime_pin_change_blocks_publication(self):
        runtime = self.register_runtime()
        runtime["packages"][0]["commit"] = "b" * 40
        write(self.repo / "skill_updater/registry.json", json.dumps(self.registry))
        self.events.append({"skill": "runtime:ub-mode-tools", "status": "error_skip", "stage": "fetch",
                            "message": "source unavailable", "installed_copy_preserved": True})
        self.assertNotEqual(0, self.run_gate().returncode)
        self.assertFalse((self.repo / "output").exists())

    def test_missing_runtime_event_blocks_publication(self):
        self.register_runtime()
        self.assertNotEqual(0, self.run_gate().returncode)


if __name__ == "__main__":
    unittest.main()
