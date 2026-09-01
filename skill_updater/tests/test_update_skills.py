import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from skill_updater import update_skills
from skill_updater.compatibility import scan_skill
from skill_updater.update_skills import (
    CompatibilityError,
    OverlayError,
    RegistryError,
    RunLogger,
    SkillEvent,
    SkillSpec,
    ValidationError,
    apply_overlay,
    deploy_skills,
    group_by_source,
    load_registry,
    main,
    prune_backups,
    prune_run_logs,
    recover_interrupted_replacement,
    require_review_branch,
    refresh_metadata,
    replace_with_rollback,
    run_updates,
    run_runtime_setup,
    stage_candidate,
    tree_hash,
    validate_candidate,
    validate_skill_compatibility,
)


FRONTMATTER = "---\nname: sample\ndescription: sample skill\n---\n\n# Sample\n"


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def valid_skill(path: Path, body: str = "") -> Path:
    name = path.name
    frontmatter = f"---\nname: {name}\ndescription: sample skill\n---\n\n# Sample\n"
    write(path / "SKILL.md", frontmatter + body)
    write(
        path / "agents/openai.yaml",
        'interface:\n  display_name: "Sample"\n'
        '  short_description: "Help with sample tasks and workflows"\n'
        f'  default_prompt: "Use ${name} to help with a relevant task."\n',
    )
    return path


def git_repo(path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "tests@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Skill Updater Tests"], check=True)
    return path


def commit_all(repo: Path, message: str = "fixture") -> None:
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", message],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def write_registry(
    path: Path,
    skills: list[dict[str, object]],
    retired_skills: list[dict[str, object]] | None = None,
) -> Path:
    payload: dict[str, object] = {"version": 1, "skills": skills}
    if retired_skills is not None:
        payload["retired_skills"] = retired_skills
    return write(path, json.dumps(payload, indent=2) + "\n")


class TempDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)

    def tearDown(self) -> None:
        self._temporary.cleanup()


class RegistryTests(TempDirTest):
    def test_load_registry_rejects_duplicate_names(self) -> None:
        registry = write(
            self.root / "registry.json",
            json.dumps(
                {
                    "version": 1,
                    "skills": [
                        {"name": "one", "repo": "o/r", "path": "skills/one"},
                        {"name": "one", "repo": "o/r", "path": "skills/two"},
                    ],
                }
            ),
        )

        with self.assertRaisesRegex(RegistryError, "duplicate skill: one"):
            load_registry(registry)

    def test_load_registry_rejects_missing_source_without_reason(self) -> None:
        registry = write(
            self.root / "registry.json",
            json.dumps({"version": 1, "skills": [{"name": "local", "enabled": False}]}),
        )

        with self.assertRaisesRegex(RegistryError, "local requires skip_reason"):
            load_registry(registry)

    def test_load_registry_rejects_unknown_runtime_setup(self) -> None:
        registry = write_registry(
            self.root / "registry.json",
            [{"name": "sample", "repo": "o/r", "path": "skills/sample", "runtime_setup": ["unknown"]}],
        )

        with self.assertRaisesRegex(RegistryError, "unknown runtime setup: unknown"):
            load_registry(registry)

    def test_load_registry_rejects_active_retired_overlap(self) -> None:
        registry = write_registry(
            self.root / "registry.json",
            [{"name": "sample", "repo": "o/r", "path": "skills/sample"}],
            retired_skills=[
                {
                    "name": "sample",
                    "installed_hashes": ["a" * 64],
                    "reason": "superseded",
                }
            ],
        )

        with self.assertRaisesRegex(RegistryError, "active skill is also retired: sample"):
            load_registry(registry)

    def test_load_registry_rejects_unsafe_retired_name(self) -> None:
        registry = write_registry(
            self.root / "registry.json",
            [],
            retired_skills=[
                {
                    "name": "../outside",
                    "installed_hashes": ["a" * 64],
                    "reason": "superseded",
                }
            ],
        )

        with self.assertRaisesRegex(RegistryError, "invalid retired skill name"):
            load_registry(registry)

    def test_load_registry_rejects_invalid_retired_hash(self) -> None:
        registry = write_registry(
            self.root / "registry.json",
            [],
            retired_skills=[
                {
                    "name": "legacy",
                    "installed_hashes": ["not-a-sha256"],
                    "reason": "superseded",
                }
            ],
        )

        with self.assertRaisesRegex(RegistryError, "invalid retired skill hash"):
            load_registry(registry)

    def test_tree_hash_ignores_transient_files(self) -> None:
        skill = valid_skill(self.root / "skill")
        first = tree_hash(skill)
        write(skill / "__pycache__" / "ignored.pyc", "noise")
        write(skill / ".DS_Store", "noise")

        self.assertEqual(first, tree_hash(skill))

    def test_tree_hash_changes_with_executable_mode(self) -> None:
        skill = valid_skill(self.root / "skill")
        script = write(skill / "scripts" / "run.sh", "#!/bin/sh\n")
        before = tree_hash(skill)
        script.chmod(0o755)

        self.assertNotEqual(before, tree_hash(skill))

    def test_tree_hash_ignores_non_executable_permission_differences(self) -> None:
        skill = valid_skill(self.root / "skill")
        file = skill / "SKILL.md"
        file.chmod(0o600)
        before = tree_hash(skill)
        file.chmod(0o644)

        self.assertEqual(before, tree_hash(skill))

    def test_project_registry_preserves_removed_upstream_skills_as_expected_skips(self) -> None:
        specs = {spec.name: spec for spec in load_registry(Path(__file__).parents[1] / "registry.json")}

        for name in ("diagnose", "zoom-out"):
            self.assertFalse(specs[name].enabled)
            self.assertIsNone(specs[name].repo)
            self.assertTrue(specs[name].skip_reason)


class AuditTests(TempDirTest):
    def test_audit_reports_installed_skill_without_registry_entry(self) -> None:
        skills_dir = self.root / "codex-home/skills"
        valid_skill(skills_dir / "known")
        valid_skill(skills_dir / "untracked")

        events = update_skills.audit_skills(
            [SkillSpec(name="known", repo="owner/repo", path="skills/known")],
            skills_dir,
        )

        self.assertEqual(1, len(events))
        self.assertEqual("untracked", events[0].status)
        self.assertEqual("untracked", events[0].skill)


class AdoptionTests(TempDirTest):
    def setUp(self) -> None:
        super().setUp()
        self.repo = git_repo(self.root / "repo")
        self.codex_home = self.root / "codex-home"
        self.work_root = self.root / "updater"
        self.registry = write_registry(self.work_root / "registry.json", [])

    def test_adopt_registers_exact_installed_upstream_skill(self) -> None:
        upstream = valid_skill(self.repo / "skills/sample", body="upstream\n")
        commit_all(self.repo)
        shutil.copytree(upstream, self.codex_home / "skills/sample")
        spec = SkillSpec(name="sample", repo=str(self.repo), path="skills/sample")

        update_skills.adopt_skill(spec, self.registry, self.codex_home, self.work_root)

        saved = load_registry(self.registry)
        self.assertEqual(["sample"], [item.name for item in saved])
        self.assertEqual(tree_hash(self.codex_home / "skills/sample"), saved[0].installed_hash)
        self.assertTrue(saved[0].installed_commit)

    def test_adopt_rejects_mismatched_installed_skill_without_registry_change(self) -> None:
        valid_skill(self.repo / "skills/sample", body="upstream\n")
        commit_all(self.repo)
        valid_skill(self.codex_home / "skills/sample", body="local\n")
        spec = SkillSpec(name="sample", repo=str(self.repo), path="skills/sample")

        with self.assertRaisesRegex(ValueError, "does not match"):
            update_skills.adopt_skill(spec, self.registry, self.codex_home, self.work_root)

        self.assertEqual([], load_registry(self.registry))
        self.assertIn("local", (self.codex_home / "skills/sample/SKILL.md").read_text())

    def test_adopt_hashes_candidate_after_runtime_setup(self) -> None:
        upstream = valid_skill(self.repo / "skills/sample", body="upstream\n")
        commit_all(self.repo)
        installed = self.codex_home / "skills/sample"
        shutil.copytree(upstream, installed)
        write(installed / "generated/runtime.txt", "materialized\n")
        spec = SkillSpec(
            name="sample",
            repo=str(self.repo),
            path="skills/sample",
            runtime_setup=("npm_ci",),
        )

        def materialize(_spec: SkillSpec, candidate: Path) -> None:
            write(candidate / "generated/runtime.txt", "materialized\n")

        with patch("skill_updater.update_skills.run_runtime_setup", side_effect=materialize):
            update_skills.adopt_skill(spec, self.registry, self.codex_home, self.work_root)

        self.assertEqual(tree_hash(installed), load_registry(self.registry)[0].installed_hash)

    def test_adopt_prunes_fingerprint_removed_by_runtime_setup(self) -> None:
        upstream = valid_skill(
            self.repo / "skills/sample",
            body="Run `~/.claude/scripts/check.py` before completion.\n",
        )
        blocker = next(
            finding.fingerprint
            for finding in scan_skill(upstream)
            if finding.disposition == "block"
        )
        commit_all(self.repo)
        installed = valid_skill(
            self.codex_home / "skills/sample",
            body="Use the provider-neutral runtime.\n",
        )
        spec = SkillSpec(
            name="sample",
            repo=str(self.repo),
            path="skills/sample",
            runtime_setup=("npm_ci",),
            accepted_compatibility_fingerprints=(blocker,),
        )

        def remove_blocker(_spec: SkillSpec, candidate: Path) -> None:
            valid_skill(candidate, body="Use the provider-neutral runtime.\n")

        with patch("skill_updater.update_skills.run_runtime_setup", side_effect=remove_blocker):
            update_skills.adopt_skill(spec, self.registry, self.codex_home, self.work_root)

        saved = load_registry(self.registry)[0]
        self.assertEqual((), saved.accepted_compatibility_fingerprints)
        self.assertEqual(tree_hash(installed), saved.installed_hash)


class AddSkillTests(TempDirTest):
    def setUp(self) -> None:
        super().setUp()
        self.repo = git_repo(self.root / "repo")
        self.codex_home = self.root / "codex-home"
        self.work_root = self.root / "updater"
        self.registry = write_registry(self.work_root / "registry.json", [])
        valid_skill(self.repo / "skills/sample", body="upstream\n")
        commit_all(self.repo)
        self.spec = SkillSpec(name="sample", repo=str(self.repo), path="skills/sample")

    def test_add_installs_valid_skill_and_registers_source(self) -> None:
        update_skills.add_skill(self.spec, self.registry, self.codex_home, self.work_root)

        saved = load_registry(self.registry)
        self.assertIn("upstream", (self.codex_home / "skills/sample/SKILL.md").read_text())
        self.assertEqual(["sample"], [item.name for item in saved])
        self.assertEqual(tree_hash(self.codex_home / "skills/sample"), saved[0].installed_hash)

    def test_add_preserves_existing_skill_without_explicit_replacement(self) -> None:
        valid_skill(self.codex_home / "skills/sample", body="installed\n")

        with self.assertRaisesRegex(ValueError, "already installed"):
            update_skills.add_skill(self.spec, self.registry, self.codex_home, self.work_root)

        self.assertIn("installed", (self.codex_home / "skills/sample/SKILL.md").read_text())
        self.assertEqual([], load_registry(self.registry))

    def test_add_replaces_registered_skill_when_explicitly_requested(self) -> None:
        update_skills.add_skill(self.spec, self.registry, self.codex_home, self.work_root)
        valid_skill(self.repo / "skills/sample", body="replacement\n")
        commit_all(self.repo, "replacement")

        update_skills.add_skill(
            self.spec,
            self.registry,
            self.codex_home,
            self.work_root,
            replace_existing=True,
        )

        saved = load_registry(self.registry)
        self.assertIn("replacement", (self.codex_home / "skills/sample/SKILL.md").read_text())
        self.assertEqual(["sample"], [item.name for item in saved])
        self.assertEqual(tree_hash(self.codex_home / "skills/sample"), saved[0].installed_hash)

    def test_add_restores_existing_skill_when_registry_write_fails(self) -> None:
        valid_skill(self.codex_home / "skills/sample", body="installed\n")

        with patch("skill_updater.update_skills._save_registry", side_effect=OSError("write failed")):
            with self.assertRaisesRegex(OSError, "write failed"):
                update_skills.add_skill(
                    self.spec,
                    self.registry,
                    self.codex_home,
                    self.work_root,
                    replace_existing=True,
                )

        self.assertIn("installed", (self.codex_home / "skills/sample/SKILL.md").read_text())
        self.assertEqual([], load_registry(self.registry))

    def test_add_blocks_runtime_specific_reference_before_install(self) -> None:
        valid_skill(self.repo / "skills/sample", body="Run ~/.claude/tool.py\n")
        commit_all(self.repo, "runtime reference")

        with self.assertRaises(CompatibilityError):
            update_skills.add_skill(self.spec, self.registry, self.codex_home, self.work_root)

        self.assertFalse((self.codex_home / "skills/sample").exists())
        self.assertEqual([], load_registry(self.registry))

    def test_add_records_upstream_reference_removed_by_overlay(self) -> None:
        valid_skill(self.repo / "skills/sample", body="Run ~/.claude/tool.py\n")
        commit_all(self.repo, "runtime reference")
        write(
            self.work_root / "overlays/sample.patch",
            "--- a/SKILL.md\n"
            "+++ b/SKILL.md\n"
            "@@ -5,2 +5,2 @@\n"
            " # Sample\n"
            "-Run ~/.claude/tool.py\n"
            "+Run the runtime-neutral tool.\n",
        )
        spec = replace(self.spec, overlay="overlays/sample.patch")

        update_skills.add_skill(spec, self.registry, self.codex_home, self.work_root)

        report = json.loads((self.work_root / "compatibility/sample.json").read_text())
        upstream_blockers = [
            finding for finding in report["upstream_findings"] if finding["disposition"] == "block"
        ]
        self.assertEqual(1, len(upstream_blockers))
        self.assertEqual([], report["new_blocking_fingerprints"])
        self.assertIn("runtime-neutral", (self.codex_home / "skills/sample/SKILL.md").read_text())


class CandidateValidationTests(TempDirTest):
    def test_canonical_validation_rejects_unaccepted_runtime_fingerprint(self) -> None:
        skills = self.root / "skills"
        skill = valid_skill(
            skills / "sample",
            body="Run `~/.claude/scripts/check.py` before completion.\n",
        )
        spec = SkillSpec(
            name="sample",
            repo="owner/repo",
            path="skills/sample",
            installed_hash=tree_hash(skill),
        )

        with self.assertRaises(CompatibilityError):
            update_skills.validate_canonical_skills([spec], skills)

    def test_canonical_validation_rejects_stale_accepted_fingerprint(self) -> None:
        skills = self.root / "skills"
        skill = valid_skill(skills / "sample")
        spec = SkillSpec(
            name="sample",
            repo="owner/repo",
            path="skills/sample",
            installed_hash=tree_hash(skill),
            accepted_compatibility_fingerprints=("stale",),
        )

        with self.assertRaisesRegex(ValidationError, "stale=.*stale"):
            update_skills.validate_canonical_skills([spec], skills)

    def test_compatibility_rejects_new_runtime_reference(self) -> None:
        skill = valid_skill(
            self.root / "sample",
            body="Run `~/.claude/scripts/check.py` before completion.\n",
        )

        with self.assertRaisesRegex(CompatibilityError, "Codex-incompatible runtime"):
            validate_skill_compatibility(skill)

    def test_compatibility_allows_provider_neutral_reference(self) -> None:
        skill = valid_skill(
            self.root / "sample",
            body="Supports OpenAI, Anthropic, and other providers.\n",
        )

        findings = validate_skill_compatibility(skill)

        self.assertEqual(["review"], sorted({finding.disposition for finding in findings}))

    def test_compatibility_allows_provider_neutral_runtime_path_documentation(self) -> None:
        skill = valid_skill(
            self.root / "sample",
            body="Claude Code uses `~/.claude/skills`; Codex uses its runtime directory.\n",
        )

        findings = validate_skill_compatibility(skill)

        self.assertEqual(["review"], sorted({finding.disposition for finding in findings}))

    def test_compatibility_allows_provider_neutral_model_example(self) -> None:
        skill = valid_skill(
            self.root / "sample",
            body="Provider-neutral docs may mention model names such as claude-sonnet as examples.\n",
        )

        findings = validate_skill_compatibility(skill)

        self.assertEqual(["review"], sorted({finding.disposition for finding in findings}))

    def test_compatibility_blocks_anthropic_api_example_used_as_runtime_code(self) -> None:
        skill = valid_skill(
            self.root / "sample",
            body='client = Anthropic()\nresponse = client.messages.create(model="claude-sonnet")\n',
        )

        with self.assertRaises(CompatibilityError):
            validate_skill_compatibility(skill)

    def test_compatibility_blocks_unquoted_claude_model_config(self) -> None:
        skill = valid_skill(self.root / "sample")
        write(skill / "config.yaml", "model: claude-sonnet\n")

        with self.assertRaises(CompatibilityError):
            validate_skill_compatibility(skill)

    def test_compatibility_scans_runtime_code_outside_scripts(self) -> None:
        skill = valid_skill(self.root / "sample")
        write(skill / "runner.py", "from anthropic import Anthropic\n")

        with self.assertRaises(CompatibilityError):
            validate_skill_compatibility(skill)

    def test_compatibility_allows_registered_runtime_fingerprint(self) -> None:
        candidate = valid_skill(
            self.root / "candidate",
            body="Run `~/.claude/scripts/check.py` before completion.\n",
        )
        accepted = tuple(
            finding.fingerprint
            for finding in scan_skill(candidate)
            if finding.disposition == "block"
        )

        validate_skill_compatibility(candidate, accepted)

    def test_compatibility_blocks_new_runtime_fingerprint_during_update(self) -> None:
        candidate = valid_skill(
            self.root / "candidate",
            body="Run `~/.claude/scripts/check.py` before completion.\n",
        )

        with self.assertRaises(CompatibilityError):
            validate_skill_compatibility(candidate)

    def test_rejects_path_stub_masquerading_as_directory(self) -> None:
        skill = valid_skill(self.root / "ui-ux-pro-max")
        write(skill / "scripts", "../../../src/ui-ux-pro-max/scripts")

        with self.assertRaisesRegex(ValidationError, "path stub: scripts"):
            validate_candidate(skill)

    def test_rejects_symlink_escaping_skill_root(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        skill = valid_skill(self.root / "sample")
        (skill / "scripts").symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(ValidationError, "escaping symlink: scripts"):
            validate_candidate(skill)

    def test_rejects_missing_frontmatter_description(self) -> None:
        skill = self.root / "sample"
        write(skill / "SKILL.md", "---\nname: sample\n---\n")

        with self.assertRaisesRegex(ValidationError, "name and description"):
            validate_candidate(skill)

    def test_rejects_environment_file(self) -> None:
        skill = valid_skill(self.root / "sample")
        write(skill / ".env", "TOKEN=secret")

        with self.assertRaisesRegex(ValidationError, "sensitive file: .env"):
            validate_candidate(skill)

    def test_rejects_common_credential_files(self) -> None:
        for name in (".npmrc", ".netrc", "client.pem", "service-account.json"):
            skill = valid_skill(self.root / name.replace(".", "-"))
            write(skill / name, "secret")

            with self.subTest(name=name):
                with self.assertRaisesRegex(ValidationError, "sensitive file"):
                    validate_candidate(skill)

    def test_accepts_valid_self_contained_skill(self) -> None:
        skill = valid_skill(self.root / "sample")
        write(skill / "scripts" / "run.py", "print('ok')\n")

        validate_candidate(skill, required_paths=("scripts/run.py",))


class StagingTests(TempDirTest):
    def test_runtime_setup_runs_allowlisted_npm_ci(self) -> None:
        skill = valid_skill(self.root / "sample")
        spec = SkillSpec(name="sample", repo="owner/repo", path="skills/sample", runtime_setup=("npm_ci",))

        with patch("skill_updater.update_skills._run") as run:
            run_runtime_setup(spec, skill)

        run.assert_called_once_with(["npm", "ci"], cwd=skill)

    def test_groups_multiple_skills_into_one_repo_fetch(self) -> None:
        grouped = group_by_source(
            [
                SkillSpec(name="one", repo="owner/repo", path="skills/one"),
                SkillSpec(name="two", repo="owner/repo", path="skills/two"),
            ]
        )

        self.assertEqual([("owner/repo", "main")], list(grouped))
        self.assertEqual(["one", "two"], [item.name for item in grouped[("owner/repo", "main")]])

    def test_disabled_local_skill_is_not_grouped(self) -> None:
        grouped = group_by_source(
            [SkillSpec(name="local", repo=None, path=None, enabled=False, skip_reason="local")]
        )

        self.assertEqual({}, grouped)

    def test_uiux_adapter_materializes_real_directories(self) -> None:
        repo = self.root / "repo"
        write(repo / ".claude/skills/ui-ux-pro-max/SKILL.md", FRONTMATTER)
        write(repo / "src/ui-ux-pro-max/scripts/search.py", "print('ok')\n")
        write(repo / "src/ui-ux-pro-max/data/styles.csv", "name\nminimal\n")
        write(repo / "src/ui-ux-pro-max/templates/base.md", "base\n")
        spec = SkillSpec(
            name="ui-ux-pro-max",
            repo="nextlevelbuilder/ui-ux-pro-max-skill",
            path=".claude/skills/ui-ux-pro-max",
            adapter="uiux",
        )

        staged = stage_candidate(spec, repo, self.root / "stage")

        self.assertTrue((staged / "scripts/search.py").is_file())
        self.assertTrue((staged / "data").is_dir())
        self.assertFalse((staged / "scripts").is_symlink())

    def test_directory_adapter_materializes_internal_repo_symlink(self) -> None:
        repo = self.root / "repo"
        write(repo / "shared/scripts/run.py", "print('ok')\n")
        skill = valid_skill(repo / "skills/sample")
        (skill / "scripts").symlink_to("../../shared/scripts", target_is_directory=True)
        spec = SkillSpec(name="sample", repo="owner/repo", path="skills/sample")

        staged = stage_candidate(spec, repo, self.root / "stage")

        self.assertTrue((staged / "scripts/run.py").is_file())
        self.assertFalse((staged / "scripts").is_symlink())

    def test_directory_adapter_canonicalizes_lowercase_skill_entrypoint(self) -> None:
        repo = self.root / "repo"
        write(repo / "skills/sample/skill.md", FRONTMATTER)
        spec = SkillSpec(name="sample", repo="owner/repo", path="skills/sample")

        staged = stage_candidate(spec, repo, self.root / "stage")

        self.assertTrue((staged / "SKILL.md").is_file())
        self.assertNotIn("skill.md", [path.name for path in staged.iterdir()])
        validate_candidate(staged)


class OverlayTests(TempDirTest):
    def test_applies_overlay_to_staged_skill(self) -> None:
        skill = valid_skill(self.root / "balanced", body="AskUserQuestion\n")
        patch = write(
            self.root / "balanced.patch",
            "--- a/SKILL.md\n+++ b/SKILL.md\n@@ -6,1 +6,1 @@\n-AskUserQuestion\n+ask the user directly\n",
        )

        apply_overlay(skill, patch)

        self.assertNotIn("AskUserQuestion", (skill / "SKILL.md").read_text())

    def test_removes_patch_backup_files(self) -> None:
        skill = valid_skill(self.root / "sample", body="before\n")
        patch = write(
            self.root / "sample.patch",
            "--- a/SKILL.md\n+++ b/SKILL.md\n@@ -6,1 +6,1 @@\n-before\n+after\n",
        )

        apply_overlay(skill, patch)

        self.assertFalse(list(skill.rglob("*.orig")))

    def test_removes_files_deleted_by_overlay(self) -> None:
        skill = valid_skill(self.root / "sample")
        write(skill / "scripts/obsolete.sh", "#!/bin/sh\n")
        patch = write(
            self.root / "remove.patch",
            "--- a/scripts/obsolete.sh\n+++ /dev/null\n@@ -1 +0,0 @@\n-#!/bin/sh\n",
        )

        apply_overlay(skill, patch)

        self.assertFalse((skill / "scripts/obsolete.sh").exists())

    def test_overlay_conflict_is_explicit(self) -> None:
        skill = valid_skill(self.root / "balanced", body="upstream changed\n")
        patch = write(
            self.root / "balanced.patch",
            "--- a/SKILL.md\n+++ b/SKILL.md\n@@ -6,1 +6,1 @@\n-missing text\n+replacement\n",
        )

        with self.assertRaisesRegex(OverlayError, "patch no longer applies"):
            apply_overlay(skill, patch)


class ReplacementTests(TempDirTest):
    def test_replacement_failure_restores_installed_copy(self) -> None:
        installed = valid_skill(self.root / "skills/sample", body="original\n")
        missing_candidate = self.root / "missing"
        backup = self.root / "backups/sample/one"

        with self.assertRaises(FileNotFoundError):
            replace_with_rollback(installed, missing_candidate, backup)

        self.assertIn("original", (installed / "SKILL.md").read_text())

    def test_interrupted_replacement_restores_original_before_retry(self) -> None:
        installed = self.root / "skills/sample"
        rollback = self.root / "skills/.sample.skill-updater-rollback"
        valid_skill(rollback, body="original\n")
        candidate = valid_skill(self.root / "stage/sample", body="new candidate\n")
        backup = self.root / "backups/sample/retry"

        replace_with_rollback(installed, candidate, backup)

        self.assertIn("new candidate", (installed / "SKILL.md").read_text())
        self.assertIn("original", (backup / "SKILL.md").read_text())
        self.assertFalse(rollback.exists())

    def test_completed_replacement_discards_stale_rollback(self) -> None:
        installed = valid_skill(self.root / "skills/sample", body="installed candidate\n")
        rollback = valid_skill(
            self.root / "skills/.sample.skill-updater-rollback",
            body="old installed copy\n",
        )

        recover_interrupted_replacement(installed)

        self.assertIn("installed candidate", (installed / "SKILL.md").read_text())
        self.assertFalse(rollback.exists())


class LoggingTests(TempDirTest):
    def test_error_skip_has_actionable_fields_and_exit_code(self) -> None:
        logger = RunLogger(self.root / "logs", run_id="2026-07-14T10-00-00")
        logger.emit(
            SkillEvent(
                skill="balanced",
                status="error_skip",
                stage="overlay",
                repo="owner/repo",
                ref="main",
                upstream_commit="abc123",
                error_type="OverlayError",
                message="patch no longer applies",
                installed_copy_preserved=True,
                suggested_action="refresh overlay",
            )
        )

        exit_code = logger.finish()
        summary = json.loads((self.root / "logs/last_run_summary.json").read_text())
        readable = (self.root / "logs/2026-07-14T10-00-00.log").read_text()

        self.assertEqual(2, exit_code)
        self.assertEqual("error_skip", summary["errors"][0]["status"])
        self.assertIn("skill=balanced", readable)
        self.assertIn("action=refresh overlay", readable)

    def test_retention_keeps_twelve_runs_and_four_backups(self) -> None:
        logs = self.root / "logs"
        backups = self.root / "backups/sample"
        for index in range(13):
            write(logs / f"2026-01-{index + 1:02d}T10-00-00.log", "log")
            write(logs / f"2026-01-{index + 1:02d}T10-00-00.jsonl", "{}\n")
        for index in range(5):
            valid_skill(backups / f"2026-01-{index + 1:02d}")

        prune_run_logs(logs, keep=12)
        prune_backups(self.root / "backups", keep_per_skill=4)

        self.assertEqual(12, len(list(logs.glob("*.jsonl"))))
        self.assertEqual(4, len(list(backups.iterdir())))


class UpdateRunTests(TempDirTest):
    def setUp(self) -> None:
        super().setUp()
        self.repo = git_repo(self.root / "repo")
        self.codex_home = self.root / "codex-home"
        self.work_root = self.root / "updater"

    def _registry(self, skills: list[dict[str, object]]) -> Path:
        return write_registry(self.work_root / "registry.json", skills)

    def test_error_skip_does_not_block_later_skill(self) -> None:
        broken = valid_skill(self.repo / "skills/broken")
        write(broken / "scripts", "../../../missing/scripts")
        valid_skill(self.repo / "skills/good", body="new\n")
        commit_all(self.repo)
        valid_skill(self.codex_home / "skills/broken", body="preserve me\n")
        registry = self._registry(
            [
                {"name": "broken", "repo": str(self.repo), "path": "skills/broken"},
                {"name": "good", "repo": str(self.repo), "path": "skills/good"},
            ]
        )

        exit_code = run_updates(registry, self.codex_home, self.work_root, apply=True)
        summary = json.loads((self.work_root / "logs/last_run_summary.json").read_text())
        events = {event["skill"]: event for event in summary["events"]}

        self.assertEqual(2, exit_code)
        self.assertEqual("error_skip", events["broken"]["status"])
        self.assertEqual("validation", events["broken"]["stage"])
        self.assertEqual("updated", events["good"]["status"])
        self.assertIn("preserve me", (self.codex_home / "skills/broken/SKILL.md").read_text())
        self.assertIn("new", (self.codex_home / "skills/good/SKILL.md").read_text())

    def test_update_report_does_not_accept_an_installed_runtime_fingerprint(self) -> None:
        body = "Run `~/.claude/scripts/check.py` before completion.\n"
        upstream = valid_skill(self.repo / "skills/sample", body=body)
        commit_all(self.repo)
        shutil.copytree(upstream, self.codex_home / "skills/sample")
        registry = self._registry(
            [{"name": "sample", "repo": str(self.repo), "path": "skills/sample"}]
        )

        self.assertEqual(2, run_updates(registry, self.codex_home, self.work_root, apply=False))

        report = json.loads((self.work_root / "compatibility/sample.json").read_text())
        blockers = [
            finding["fingerprint"]
            for finding in report["final_findings"]
            if finding["disposition"] == "block"
        ]
        self.assertEqual([], report["accepted_fingerprints"])
        self.assertEqual(blockers, report["new_blocking_fingerprints"])

    def test_apply_prunes_accepted_fingerprint_removed_upstream(self) -> None:
        upstream = valid_skill(
            self.repo / "skills/sample",
            body="Run `~/.claude/scripts/check.py` before completion.\n",
        )
        blocker = next(
            finding.fingerprint
            for finding in scan_skill(upstream)
            if finding.disposition == "block"
        )
        commit_all(self.repo, "accepted blocker")
        installed = self.codex_home / "skills/sample"
        shutil.copytree(upstream, installed)
        registry = self._registry(
            [
                {
                    "name": "sample",
                    "repo": str(self.repo),
                    "path": "skills/sample",
                    "installed_hash": tree_hash(installed),
                    "accepted_compatibility_fingerprints": [blocker],
                }
            ]
        )
        valid_skill(upstream, body="Use the provider-neutral runtime.\n")
        commit_all(self.repo, "remove blocker")

        self.assertEqual(0, run_updates(registry, self.codex_home, self.work_root, apply=True))

        saved = load_registry(registry)[0]
        self.assertEqual((), saved.accepted_compatibility_fingerprints)
        update_skills.validate_canonical_skills([saved], self.codex_home / "skills")

    def test_check_mode_never_replaces_installed_skill(self) -> None:
        valid_skill(self.repo / "skills/sample", body="upstream\n")
        commit_all(self.repo)
        valid_skill(self.codex_home / "skills/sample", body="installed\n")
        registry = self._registry(
            [{"name": "sample", "repo": str(self.repo), "path": "skills/sample"}]
        )

        exit_code = run_updates(registry, self.codex_home, self.work_root, apply=False)
        summary = json.loads((self.work_root / "logs/last_run_summary.json").read_text())

        self.assertEqual(0, exit_code)
        self.assertIn("installed", (self.codex_home / "skills/sample/SKILL.md").read_text())
        self.assertEqual("unchanged", summary["events"][0]["status"])
        self.assertIn("update available", summary["events"][0]["message"])

    def test_local_drift_is_expected_skip(self) -> None:
        valid_skill(self.repo / "skills/sample", body="upstream\n")
        commit_all(self.repo)
        registry = self._registry(
            [{"name": "sample", "repo": str(self.repo), "path": "skills/sample"}]
        )
        self.assertEqual(0, run_updates(registry, self.codex_home, self.work_root, apply=True))
        skill_file = self.codex_home / "skills/sample/SKILL.md"
        skill_file.write_text(skill_file.read_text() + "local edit\n")

        exit_code = run_updates(registry, self.codex_home, self.work_root, apply=True)
        summary = json.loads((self.work_root / "logs/last_run_summary.json").read_text())

        self.assertEqual(0, exit_code)
        self.assertEqual("expected_skip", summary["events"][0]["status"])
        self.assertIn("local edit", skill_file.read_text())

    def test_second_apply_is_idempotent(self) -> None:
        valid_skill(self.repo / "skills/sample", body="upstream\n")
        commit_all(self.repo)
        registry = self._registry(
            [{"name": "sample", "repo": str(self.repo), "path": "skills/sample"}]
        )

        self.assertEqual(0, run_updates(registry, self.codex_home, self.work_root, apply=True))
        self.assertEqual(0, run_updates(registry, self.codex_home, self.work_root, apply=True))
        summary = json.loads((self.work_root / "logs/last_run_summary.json").read_text())

        self.assertEqual("unchanged", summary["events"][0]["status"])

    def test_apply_restores_missing_runtime_dependencies_for_current_skill(self) -> None:
        upstream = valid_skill(self.repo / "skills/sample", body="upstream\n")
        commit_all(self.repo)
        shutil.copytree(upstream, self.codex_home / "skills/sample")
        registry = self._registry(
            [
                {
                    "name": "sample",
                    "repo": str(self.repo),
                    "path": "skills/sample",
                    "runtime_setup": ["npm_ci"],
                    "installed_hash": tree_hash(upstream),
                }
            ]
        )

        with patch("skill_updater.update_skills.run_runtime_setup") as setup:
            self.assertEqual(0, run_updates(registry, self.codex_home, self.work_root, apply=True))

        setup.assert_called_once()
        setup_spec, setup_root = setup.call_args.args
        self.assertEqual("sample", setup_spec.name)
        self.assertEqual(("npm_ci",), setup_spec.runtime_setup)
        self.assertEqual("sample", setup_root.name)
        self.assertNotEqual(self.codex_home / "skills/sample", setup_root)
        summary = json.loads((self.work_root / "logs/last_run_summary.json").read_text())
        self.assertEqual("runtime_setup", summary["events"][0]["stage"])

    def test_apply_hashes_candidate_after_mutating_runtime_setup(self) -> None:
        valid_skill(self.repo / "skills/sample", body="upstream\n")
        commit_all(self.repo)
        valid_skill(self.codex_home / "skills/sample", body="installed\n")
        registry = self._registry(
            [
                {
                    "name": "sample",
                    "repo": str(self.repo),
                    "path": "skills/sample",
                    "runtime_setup": ["npm_ci"],
                }
            ]
        )

        def materialize(_spec: SkillSpec, candidate: Path) -> None:
            write(candidate / "generated/runtime.txt", "materialized\n")

        with patch("skill_updater.update_skills.run_runtime_setup", side_effect=materialize):
            self.assertEqual(0, run_updates(registry, self.codex_home, self.work_root, apply=True))
            self.assertEqual(0, run_updates(registry, self.codex_home, self.work_root, apply=True))

        installed = self.codex_home / "skills/sample"
        saved = load_registry(registry)[0]
        self.assertEqual(tree_hash(installed), saved.installed_hash)
        summary = json.loads((self.work_root / "logs/last_run_summary.json").read_text())
        self.assertEqual("unchanged", summary["events"][0]["status"])

    def test_dependency_restoration_records_post_setup_state(self) -> None:
        upstream = valid_skill(self.repo / "skills/sample", body="upstream\n")
        commit_all(self.repo)
        installed = self.codex_home / "skills/sample"
        shutil.copytree(upstream, installed)
        registry = self._registry(
            [
                {
                    "name": "sample",
                    "repo": str(self.repo),
                    "path": "skills/sample",
                    "runtime_setup": ["npm_ci"],
                    "installed_hash": tree_hash(installed),
                }
            ]
        )

        def materialize(_spec: SkillSpec, candidate: Path) -> None:
            write(candidate / "generated/runtime.txt", "materialized\n")
            (candidate / "node_modules").mkdir()

        with patch("skill_updater.update_skills.run_runtime_setup", side_effect=materialize):
            self.assertEqual(0, run_updates(registry, self.codex_home, self.work_root, apply=True))
            self.assertEqual(0, run_updates(registry, self.codex_home, self.work_root, apply=True))

        saved = load_registry(registry)[0]
        self.assertEqual(tree_hash(installed), saved.installed_hash)
        summary = json.loads((self.work_root / "logs/last_run_summary.json").read_text())
        self.assertEqual("unchanged", summary["events"][0]["status"])

    def test_dependency_restoration_rejects_candidate_without_mutating_installed(self) -> None:
        upstream = valid_skill(self.repo / "skills/sample", body="upstream\n")
        commit_all(self.repo)
        installed = self.codex_home / "skills/sample"
        shutil.copytree(upstream, installed)
        installed_hash = tree_hash(installed)
        registry = self._registry(
            [
                {
                    "name": "sample",
                    "repo": str(self.repo),
                    "path": "skills/sample",
                    "runtime_setup": ["npm_ci"],
                    "installed_hash": installed_hash,
                }
            ]
        )

        def add_blocker(_spec: SkillSpec, candidate: Path) -> None:
            valid_skill(candidate, body="Run `~/.claude/scripts/check.py`.\n")

        with patch("skill_updater.update_skills.run_runtime_setup", side_effect=add_blocker):
            self.assertEqual(2, run_updates(registry, self.codex_home, self.work_root, apply=True))

        self.assertIn("upstream", (installed / "SKILL.md").read_text())
        self.assertEqual(installed_hash, tree_hash(installed))
        self.assertEqual(installed_hash, load_registry(registry)[0].installed_hash)
        summary = json.loads((self.work_root / "logs/last_run_summary.json").read_text())
        self.assertTrue(summary["errors"][0]["installed_copy_preserved"])

    def test_dependency_restoration_replacement_failure_preserves_registry_state(self) -> None:
        upstream = valid_skill(self.repo / "skills/sample", body="upstream\n")
        commit_all(self.repo)
        installed = self.codex_home / "skills/sample"
        shutil.copytree(upstream, installed)
        installed_hash = tree_hash(installed)
        registry = self._registry(
            [
                {
                    "name": "sample",
                    "repo": str(self.repo),
                    "path": "skills/sample",
                    "runtime_setup": ["npm_ci"],
                    "installed_hash": installed_hash,
                }
            ]
        )

        def materialize(_spec: SkillSpec, candidate: Path) -> None:
            write(candidate / "generated/runtime.txt", "materialized\n")

        with (
            patch("skill_updater.update_skills.run_runtime_setup", side_effect=materialize),
            patch(
                "skill_updater.update_skills.replace_with_rollback",
                side_effect=OSError("replacement failed"),
            ),
        ):
            self.assertEqual(2, run_updates(registry, self.codex_home, self.work_root, apply=True))

        self.assertEqual(installed_hash, tree_hash(installed))
        self.assertEqual(installed_hash, load_registry(registry)[0].installed_hash)

    def test_apply_prunes_fingerprint_removed_by_runtime_setup(self) -> None:
        upstream = valid_skill(
            self.repo / "skills/sample",
            body="Run `~/.claude/scripts/check.py` before completion.\n",
        )
        blocker = next(
            finding.fingerprint
            for finding in scan_skill(upstream)
            if finding.disposition == "block"
        )
        commit_all(self.repo)
        installed = valid_skill(self.codex_home / "skills/sample", body="old\n")
        registry = self._registry(
            [
                {
                    "name": "sample",
                    "repo": str(self.repo),
                    "path": "skills/sample",
                    "runtime_setup": ["npm_ci"],
                    "installed_hash": tree_hash(installed),
                    "accepted_compatibility_fingerprints": [blocker],
                }
            ]
        )

        def remove_blocker(_spec: SkillSpec, candidate: Path) -> None:
            valid_skill(candidate, body="Use the provider-neutral runtime.\n")

        with patch("skill_updater.update_skills.run_runtime_setup", side_effect=remove_blocker):
            self.assertEqual(0, run_updates(registry, self.codex_home, self.work_root, apply=True))

        saved = load_registry(registry)[0]
        self.assertEqual((), saved.accepted_compatibility_fingerprints)
        update_skills.validate_canonical_skills([saved], self.codex_home / "skills")

    def test_fetch_failure_creates_one_error_per_skill(self) -> None:
        missing = self.root / "missing-repo"
        registry = self._registry(
            [
                {"name": "one", "repo": str(missing), "path": "skills/one"},
                {"name": "two", "repo": str(missing), "path": "skills/two"},
            ]
        )

        exit_code = run_updates(registry, self.codex_home, self.work_root, apply=True)
        summary = json.loads((self.work_root / "logs/last_run_summary.json").read_text())

        self.assertEqual(2, exit_code)
        self.assertEqual(["one", "two"], [event["skill"] for event in summary["errors"]])
        self.assertTrue(all(event["stage"] == "fetch" for event in summary["errors"]))

    def test_interrupted_replacement_recovers_before_fetch_failure(self) -> None:
        rollback = self.codex_home / "skills/.sample.skill-updater-rollback"
        valid_skill(rollback, body="original\n")
        registry = self._registry(
            [{"name": "sample", "repo": str(self.root / "missing"), "path": "skills/sample"}]
        )

        exit_code = run_updates(registry, self.codex_home, self.work_root, apply=True)

        self.assertEqual(2, exit_code)
        self.assertIn(
            "original",
            (self.codex_home / "skills/sample/SKILL.md").read_text(),
        )
        self.assertFalse(rollback.exists())

    def test_invalid_registry_is_logged_as_global_error_skip(self) -> None:
        registry = write(self.work_root / "registry.json", "not json")

        exit_code = run_updates(registry, self.codex_home, self.work_root, apply=True)
        summary = json.loads((self.work_root / "logs/last_run_summary.json").read_text())

        self.assertEqual(2, exit_code)
        self.assertEqual("*", summary["errors"][0]["skill"])
        self.assertEqual("registry", summary["errors"][0]["stage"])

    def test_installed_upstream_candidate_repairs_stale_registry_state(self) -> None:
        upstream = valid_skill(self.repo / "skills/sample", body="upstream\n")
        commit_all(self.repo)
        old = valid_skill(self.root / "old", body="old\n")
        installed = self.codex_home / "skills/sample"
        shutil.copytree(upstream, installed)
        registry = self._registry(
            [
                {
                    "name": "sample",
                    "repo": str(self.repo),
                    "path": "skills/sample",
                    "installed_hash": tree_hash(old),
                }
            ]
        )

        exit_code = run_updates(registry, self.codex_home, self.work_root, apply=True)
        summary = json.loads((self.work_root / "logs/last_run_summary.json").read_text())
        saved = load_registry(registry)[0]

        self.assertEqual(0, exit_code)
        self.assertEqual("unchanged", summary["events"][0]["status"])
        self.assertEqual(tree_hash(installed), saved.installed_hash)

    def test_run_records_untracked_installed_skills_before_updates(self) -> None:
        valid_skill(self.repo / "skills/sample", body="upstream\n")
        commit_all(self.repo)
        valid_skill(self.codex_home / "skills/untracked", body="local\n")
        registry = self._registry(
            [{"name": "sample", "repo": str(self.repo), "path": "skills/sample"}]
        )

        exit_code = run_updates(registry, self.codex_home, self.work_root, apply=False)
        summary = json.loads((self.work_root / "logs/last_run_summary.json").read_text())
        events = {(event["skill"], event["status"]) for event in summary["events"]}

        self.assertEqual(0, exit_code)
        self.assertIn(("untracked", "untracked"), events)
        self.assertIn(("sample", "unchanged"), events)

    def test_registry_write_failure_restores_replaced_skill(self) -> None:
        valid_skill(self.repo / "skills/sample", body="upstream\n")
        commit_all(self.repo)
        valid_skill(self.codex_home / "skills/sample", body="installed\n")
        registry = self._registry(
            [{"name": "sample", "repo": str(self.repo), "path": "skills/sample"}]
        )

        with patch("skill_updater.update_skills._save_registry", side_effect=OSError("write failed")):
            exit_code = run_updates(registry, self.codex_home, self.work_root, apply=True)

        summary = json.loads((self.work_root / "logs/last_run_summary.json").read_text())
        self.assertEqual(2, exit_code)
        self.assertIn("installed", (self.codex_home / "skills/sample/SKILL.md").read_text())
        self.assertNotIn("updated", [event["status"] for event in summary["events"]])
        saved = load_registry(registry)
        self.assertEqual(["sample"], [spec.name for spec in saved])
        self.assertIsNone(saved[0].installed_hash)


class CanonicalRepositoryTests(TempDirTest):
    def test_refresh_apply_is_forbidden_on_main(self) -> None:
        repository = git_repo(self.root / "repository")

        with self.assertRaisesRegex(RuntimeError, "forbidden on protected branch: main"):
            require_review_branch(repository)

    def test_metadata_apply_generates_yaml_and_updates_managed_hash(self) -> None:
        repository = self.root / "repository"
        skill = repository / "skills/sample"
        write(skill / "SKILL.md", FRONTMATTER)
        registry = write_registry(
            self.root / "updater/registry.json",
            [{"name": "sample", "repo": "owner/repo", "path": "skills/sample"}],
        )

        exit_code = refresh_metadata(registry, repository, self.root / "updater", apply=True)

        self.assertEqual(0, exit_code)
        self.assertTrue((skill / "agents/openai.yaml").is_file())
        self.assertEqual(tree_hash(skill), load_registry(registry)[0].installed_hash)
        self.assertEqual(
            0,
            refresh_metadata(registry, repository, self.root / "updater", apply=False),
        )

    def test_deploy_replaces_local_skill_from_canonical_tree(self) -> None:
        repository = self.root / "repository"
        canonical = valid_skill(repository / "skills/sample", body="canonical\n")
        registry = write_registry(
            self.root / "updater/registry.json",
            [
                {
                    "name": "sample",
                    "repo": "owner/repo",
                    "path": "skills/sample",
                    "installed_hash": tree_hash(canonical),
                }
            ],
        )
        codex_home = self.root / "codex-home"
        valid_skill(codex_home / "skills/sample", body="local drift\n")

        exit_code = deploy_skills(
            registry,
            repository,
            codex_home,
            self.root / "updater",
            apply=True,
        )

        self.assertEqual(0, exit_code)
        self.assertIn("canonical", (codex_home / "skills/sample/SKILL.md").read_text())

    def test_deploy_rejects_canonical_hash_drift(self) -> None:
        repository = self.root / "repository"
        valid_skill(repository / "skills/sample")
        registry = write_registry(
            self.root / "updater/registry.json",
            [
                {
                    "name": "sample",
                    "repo": "owner/repo",
                    "path": "skills/sample",
                    "installed_hash": "stale",
                }
            ],
        )

        with self.assertRaisesRegex(ValidationError, "canonical hash mismatch"):
            deploy_skills(
                registry,
                repository,
                self.root / "codex-home",
                self.root / "updater",
            )

    def test_deploy_removes_exact_retired_skill(self) -> None:
        repository = self.root / "repository"
        (repository / "skills").mkdir(parents=True)
        codex_home = self.root / "codex-home"
        retired = valid_skill(codex_home / "skills/legacy", body="retired\n")
        registry = write_registry(
            self.root / "updater/registry.json",
            [],
            retired_skills=[
                {
                    "name": "legacy",
                    "installed_hashes": [tree_hash(retired)],
                    "reason": "superseded",
                }
            ],
        )

        self.assertEqual(
            1,
            deploy_skills(registry, repository, codex_home, self.root / "updater"),
        )
        self.assertEqual(
            0,
            deploy_skills(
                registry,
                repository,
                codex_home,
                self.root / "updater",
                apply=True,
            ),
        )

        self.assertFalse(retired.exists())

    def test_deploy_preserves_locally_modified_retired_skill(self) -> None:
        repository = self.root / "repository"
        (repository / "skills").mkdir(parents=True)
        codex_home = self.root / "codex-home"
        retired = valid_skill(codex_home / "skills/legacy", body="local changes\n")
        registry = write_registry(
            self.root / "updater/registry.json",
            [],
            retired_skills=[
                {
                    "name": "legacy",
                    "installed_hashes": ["a" * 64],
                    "reason": "superseded",
                }
            ],
        )

        with self.assertRaisesRegex(ValidationError, "retired skill has local drift"):
            deploy_skills(
                registry,
                repository,
                codex_home,
                self.root / "updater",
                apply=True,
            )

        self.assertTrue(retired.exists())

    def test_metadata_update_preserves_retired_skills(self) -> None:
        repository = self.root / "repository"
        skill = repository / "skills/sample"
        write(skill / "SKILL.md", FRONTMATTER)
        retired = [
            {
                "name": "legacy",
                "installed_hashes": ["a" * 64],
                "reason": "superseded",
            }
        ]
        registry = write_registry(
            self.root / "updater/registry.json",
            [{"name": "sample", "repo": "owner/repo", "path": "skills/sample"}],
            retired_skills=retired,
        )

        self.assertEqual(
            0,
            refresh_metadata(registry, repository, self.root / "updater", apply=True),
        )

        self.assertEqual(retired, json.loads(registry.read_text())["retired_skills"])

    def test_retirement_backup_failure_preserves_installed_skill(self) -> None:
        repository = self.root / "repository"
        (repository / "skills").mkdir(parents=True)
        codex_home = self.root / "codex-home"
        retired = valid_skill(codex_home / "skills/legacy", body="retired\n")
        retired_hash = tree_hash(retired)
        registry = write_registry(
            self.root / "updater/registry.json",
            [],
            retired_skills=[
                {
                    "name": "legacy",
                    "installed_hashes": [retired_hash],
                    "reason": "superseded",
                }
            ],
        )

        with patch("skill_updater.update_skills.shutil.copytree", side_effect=OSError("backup failed")):
            with self.assertRaisesRegex(OSError, "backup failed"):
                deploy_skills(
                    registry,
                    repository,
                    codex_home,
                    self.root / "updater",
                    apply=True,
                )

        self.assertEqual(retired_hash, tree_hash(retired))


class CliTests(TempDirTest):
    def test_main_runs_check_mode_with_explicit_paths(self) -> None:
        repo = git_repo(self.root / "repo")
        valid_skill(repo / "skills/sample", body="upstream\n")
        commit_all(repo)
        registry = write_registry(
            self.root / "updater/registry.json",
            [{"name": "sample", "repo": str(repo), "path": "skills/sample"}],
        )
        codex_home = self.root / "codex-home"

        exit_code = main(
            [
                "--check",
                "--registry",
                str(registry),
                "--codex-home",
                str(codex_home),
                "--work-root",
                str(self.root / "updater"),
            ]
        )

        self.assertEqual(0, exit_code)
        self.assertFalse((codex_home / "skills/sample").exists())

    def test_main_rejects_missing_mode(self) -> None:
        with self.assertRaises(SystemExit):
            main([])

    def test_main_add_registers_and_installs_skill(self) -> None:
        repo = git_repo(self.root / "repo")
        valid_skill(repo / "skills/sample", body="upstream\n")
        commit_all(repo)
        registry = write_registry(self.root / "updater/registry.json", [])
        codex_home = self.root / "codex-home"

        exit_code = main(
            [
                "add",
                "--name",
                "sample",
                "--repo",
                str(repo),
                "--path",
                "skills/sample",
                "--registry",
                str(registry),
                "--codex-home",
                str(codex_home),
                "--work-root",
                str(self.root / "updater"),
            ]
        )

        self.assertEqual(0, exit_code)
        self.assertTrue((codex_home / "skills/sample/SKILL.md").is_file())
        self.assertEqual(["sample"], [spec.name for spec in load_registry(registry)])

    def test_main_audit_strict_returns_nonzero_for_untracked_skill(self) -> None:
        registry = write_registry(self.root / "updater/registry.json", [])
        codex_home = self.root / "codex-home"
        valid_skill(codex_home / "skills/untracked")

        exit_code = main(
            [
                "audit",
                "--strict",
                "--registry",
                str(registry),
                "--codex-home",
                str(codex_home),
                "--work-root",
                str(self.root / "updater"),
            ]
        )

        self.assertEqual(1, exit_code)

class LaunchdTests(TempDirTest):
    def test_sync_wrapper_recovers_after_failed_dependency_install(self) -> None:
        upstream = git_repo(self.root / "upstream")
        script_path = Path(__file__).parents[1] / "sync_and_deploy.sh"
        copied_script = write(
            upstream / "skill_updater/sync_and_deploy.sh",
            script_path.read_text(),
        )
        copied_script.chmod(0o755)
        write(
            upstream / "skill_updater/update_skills.py",
            """\
import os
import sys
from pathlib import Path

with Path(os.environ["CALL_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(f"{sys.argv[1]}\\n")
""",
        )
        write(upstream / "skill_updater/registry.json", "{}\n")
        requirements = write(
            upstream / "scripts/requirements-chatgpt.txt",
            "--definitely-invalid-option\n",
        )
        commit_all(upstream)

        checkout = self.root / "checkout"
        subprocess.run(
            ["git", "clone", str(upstream), str(checkout)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        temporary_root = self.root / "tmp"
        temporary_root.mkdir()
        environment = os.environ.copy()
        environment.update(
            {
                "CALL_LOG": str(self.root / "calls.log"),
                "CODEX_HOME": str(self.root / "codex-home"),
                "PYTHON312": sys.executable,
                "TMPDIR": str(temporary_root),
            }
        )

        failed = subprocess.run(
            ["/bin/bash", str(checkout / "skill_updater/sync_and_deploy.sh")],
            cwd=checkout,
            env=environment,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(0, failed.returncode)
        self.assertFalse((checkout / ".venv").exists())

        requirements.write_text("", encoding="utf-8")
        commit_all(upstream, "repair requirements")
        recovered = subprocess.run(
            ["/bin/bash", str(checkout / "skill_updater/sync_and_deploy.sh")],
            cwd=checkout,
            env=environment,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, recovered.returncode, recovered.stderr)
        self.assertTrue((checkout / ".venv/bin/python").is_file())
        self.assertEqual(
            ["deploy", "audit"],
            (self.root / "calls.log").read_text(encoding="utf-8").splitlines(),
        )

    def test_sync_wrapper_uses_python312_venv_and_audits_the_deployed_snapshot(self) -> None:
        script_path = Path(__file__).parents[1] / "sync_and_deploy.sh"
        script = script_path.read_text()

        self.assertIn('VENV_PYTHON="$REPOSITORY_ROOT/.venv/bin/python"', script)
        self.assertIn('TEMPORARY_VENV="$REPOSITORY_ROOT/.venv.build.$$"', script)
        self.assertIn('resolve_python312()', script)
        self.assertIn('BOOTSTRAP_PYTHON="$(resolve_python312)"', script)
        self.assertIn('"$BOOTSTRAP_PYTHON" -m venv "$TEMPORARY_VENV"', script)
        self.assertIn('mv "$TEMPORARY_VENV" "$REPOSITORY_ROOT/.venv"', script)
        self.assertIn(
            '-r "$TEMPORARY_ROOT/scripts/requirements-chatgpt.txt"',
            script,
        )
        self.assertEqual(
            2,
            script.count(
                '"$VENV_PYTHON" "$TEMPORARY_ROOT/skill_updater/update_skills.py"'
            ),
        )
        self.assertEqual(2, script.count('"$TEMPORARY_ROOT/skill_updater/registry.json"'))
        self.assertIn(' audit \\\n    --strict', script)
        self.assertIn('/opt/homebrew/bin/python3.12', script)

    def test_schedule_is_daily_at_10_local_time(self) -> None:
        plist_path = (
            Path(__file__).parents[1]
            / "launchd/io.github.floppa2003.codex-skill-updater.plist.in"
        )
        with plist_path.open("rb") as stream:
            payload = plistlib.load(stream)

        self.assertEqual(
            {"Hour": 10, "Minute": 0},
            payload["StartCalendarInterval"],
        )

    def test_launchd_template_contains_no_machine_specific_paths(self) -> None:
        plist_path = (
            Path(__file__).parents[1]
            / "launchd/io.github.floppa2003.codex-skill-updater.plist.in"
        )
        content = plist_path.read_text(encoding="utf-8")

        self.assertNotIn("/Users/", content)

    @unittest.skipUnless(shutil.which("plutil"), "requires macOS plutil")
    def test_launchd_renderer_materializes_checkout_and_state_paths(self) -> None:
        updater_root = Path(__file__).parents[1]
        script_path = updater_root / "install_launchd.sh"
        home = self.root / "home"
        codex_home = self.root / "codex-home"
        environment = os.environ | {"HOME": str(home), "CODEX_HOME": str(codex_home)}

        completed = subprocess.run(
            ["/bin/bash", str(script_path), "render"],
            env=environment,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        rendered = (
            home
            / "Library/LaunchAgents/io.github.floppa2003.codex-skill-updater.plist"
        )
        with rendered.open("rb") as stream:
            payload = plistlib.load(stream)

        self.assertEqual("io.github.floppa2003.codex-skill-updater", payload["Label"])
        self.assertEqual(
            ["/bin/bash", str(updater_root / "sync_and_deploy.sh")],
            payload["ProgramArguments"],
        )
        self.assertEqual(str(updater_root.parent), payload["WorkingDirectory"])
        logs = codex_home / "skill-updater-state/logs"
        self.assertEqual(str(logs / "launchd.stdout.log"), payload["StandardOutPath"])
        self.assertEqual(str(logs / "launchd.stderr.log"), payload["StandardErrorPath"])


if __name__ == "__main__":
    unittest.main()
