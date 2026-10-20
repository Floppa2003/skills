#!/usr/bin/env python3
"""Exercise the Codex package in disposable repositories; no model calls."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SKILL_ROOT = Path(__file__).resolve().parent.parent


class PackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="proof-loop-check-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def command(self, verb: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SKILL_ROOT / "scripts/task_loop.py"), verb,
             "--task-id", "demo", *args],
            cwd=self.repo, text=True, capture_output=True, timeout=20,
        )

    def init(self, *args: str) -> dict:
        result = self.command("init", "--task-text", "Implement a demo.", *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_frontmatter_and_explicit_activation(self) -> None:
        text = (SKILL_ROOT / "SKILL.md").read_text()
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("\nname: repo-task-proof-loop\n", text)
        metadata = (SKILL_ROOT / "agents/openai.yaml").read_text()
        self.assertIn("allow_implicit_invocation: false", metadata)

    def test_default_init_only_creates_task_artifacts(self) -> None:
        result = self.init()
        self.assertEqual(result["guide_file_actions"], {})
        self.assertEqual(result["installed_or_refreshed_subagent_files"], [])
        self.assertEqual({p.name for p in self.repo.iterdir()}, {".git", ".agent"})
        task = self.repo / ".agent/tasks/demo"
        for name in ("spec.md", "evidence.md", "evidence.json", "verdict.json",
                     "problems.md", "raw/build.txt", "raw/screenshot-1.png"):
            self.assertTrue((task / name).is_file(), name)

    def test_existing_guidance_and_task_survive_default_rerun(self) -> None:
        guide = self.repo / "AGENTS.md"
        guide.write_text("# Existing project rules\n")
        self.init()
        spec = self.repo / ".agent/tasks/demo/spec.md"
        spec.write_text("# Approved specification\n")
        self.init()
        self.assertEqual(guide.read_text(), "# Existing project rules\n")
        self.assertEqual(spec.read_text(), "# Approved specification\n")

    def test_placeholder_validation_does_not_mean_task_passed(self) -> None:
        self.init()
        validation = self.command("validate")
        self.assertEqual(validation.returncode, 0, validation.stderr)
        self.assertTrue(json.loads(validation.stdout)["valid"])
        status = json.loads(self.command("status").stdout)
        self.assertEqual(status["evidence_overall_status"], "UNKNOWN")
        self.assertEqual(status["verdict_overall_status"], "UNKNOWN")

    def test_optional_codex_install_and_guide_are_separate(self) -> None:
        result = self.init("--install-subagents", "codex")
        self.assertEqual(len(result["installed_or_refreshed_subagent_files"]), 4)
        self.assertFalse((self.repo / "AGENTS.md").exists())
        guide = self.repo / "AGENTS.md"
        guide.write_text("# Keep this rule\n")
        self.init("--guides", "agents")
        self.init("--guides", "agents")
        self.assertTrue(guide.read_text().startswith("# Keep this rule\n"))
        self.assertEqual(guide.read_text().count("<!-- repo-task-proof-loop:start -->"), 1)
        self.assertEqual({p.name for p in self.repo.iterdir()},
                         {".git", ".agent", ".codex", "AGENTS.md"})

    def test_differing_agent_is_not_overwritten(self) -> None:
        self.init("--install-subagents", "codex")
        agent = self.repo / ".codex/agents/task-builder.toml"
        agent.write_text("# User-maintained agent\n")
        result = self.command("init", "--install-subagents", "codex", "--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Existing agent differs", result.stderr)
        self.assertEqual(agent.read_text(), "# User-maintained agent\n")

    def test_guidance_seed_does_not_import_other_products(self) -> None:
        (self.repo / "AGENTS.md").write_text("# Rules\n")
        (self.repo / "AGENTS.override.md").write_text("# Overrides\n")
        (self.repo / "CLAUDE.md").write_text("# Other product\n")
        self.init()
        spec = (self.repo / ".agent/tasks/demo/spec.md").read_text()
        self.assertIn("- AGENTS.override.md", spec)
        self.assertIn("- AGENTS.md", spec)
        self.assertNotIn("- CLAUDE.md", spec)

    def test_init_sentinel_blocks_validation(self) -> None:
        self.init()
        sentinel = self.repo / ".agent/tasks/demo/.init-in-progress"
        sentinel.write_text("active\n")
        validation = self.command("validate")
        self.assertNotEqual(validation.returncode, 0)
        self.assertTrue(json.loads(validation.stdout)["init_in_progress"])
        self.assertTrue(json.loads(self.command("status").stdout)["init_in_progress"])

    def test_corrupt_evidence_fails_validation(self) -> None:
        self.init()
        (self.repo / ".agent/tasks/demo/evidence.json").write_text("{broken")
        result = self.command("validate")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stdout)["valid"])

    def test_invalid_task_id_does_not_create_artifacts(self) -> None:
        result = self.command("init", "--task-id", "../escape")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repo / ".agent").exists())

    def test_status_is_read_only_when_uninitialized(self) -> None:
        before = {p.name for p in self.repo.iterdir()}
        result = self.command("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["exists"])
        self.assertEqual(before, {p.name for p in self.repo.iterdir()})

    def test_symlink_destinations_are_rejected_before_writes(self) -> None:
        cases = [
            (".agent", True, ()),
            (".agent/tasks", True, ()),
            (".agent/tasks/demo", True, ()),
            (".agent/tasks/demo/raw", True, ()),
            (".agent/tasks/demo/evidence.json", False, ()),
            (".agent/tasks/demo/.init-in-progress", False, ()),
            ("AGENTS.md", False, ("--guides", "agents")),
            (".codex", True, ("--install-subagents", "codex")),
            (".codex/agents/task-builder.toml", False, ("--install-subagents", "codex")),
        ]
        for relative, directory, options in cases:
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as temporary:
                self.repo = Path(temporary) / "repo"
                self.repo.mkdir()
                subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
                outside = Path(temporary) / "outside"
                outside.mkdir()
                precious = outside / "keep"
                precious.write_text("user state\n")
                link = self.repo / relative
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(outside if directory else precious)
                result = self.command("init", *options)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("symlink", result.stderr)
                self.assertEqual(precious.read_text(), "user state\n")
                self.assertEqual({p.name for p in outside.iterdir()}, {"keep"})
                self.assertFalse((self.repo / ".agent/tasks/demo/spec.md").exists())

    def test_dangling_artifact_link_is_rejected(self) -> None:
        task = self.repo / ".agent/tasks/demo"
        task.mkdir(parents=True)
        target = self.repo / "not-created"
        (task / "evidence.json").symlink_to(target)
        result = self.command("init")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(target.exists())
        self.assertFalse((task / "spec.md").exists())

    def test_existing_init_marker_is_preserved(self) -> None:
        task = self.repo / ".agent/tasks/demo"
        task.mkdir(parents=True)
        marker = task / ".init-in-progress"
        marker.write_text("another initializer\n")
        result = self.command("init")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(marker.read_text(), "another initializer\n")
        self.assertFalse((task / "spec.md").exists())

    def test_force_does_not_modify_hard_link_target(self) -> None:
        task = self.repo / ".agent/tasks/demo"
        task.mkdir(parents=True)
        target = self.repo / "other-user-file"
        target.write_text("preserve\n")
        os.link(target, task / "spec.md")
        result = self.command("init", "--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_text(), "preserve\n")

    def test_read_commands_reject_redirected_task_directory(self) -> None:
        (self.repo / ".agent").symlink_to(self.repo / ".git")
        for command in ("validate", "status"):
            with self.subTest(command=command):
                result = self.command(command)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("symlink", result.stderr)


def main() -> int:
    global SKILL_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", type=Path, default=SKILL_ROOT)
    args = parser.parse_args()
    SKILL_ROOT = args.skill_root.resolve()
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(PackageTests)
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
