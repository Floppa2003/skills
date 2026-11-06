import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tarfile
from unittest.mock import patch

from skill_updater import update_skills
from skill_updater.tests.test_update_skills import TempDirTest, valid_skill, write


class ReleaseFixture(TempDirTest):
    def setUp(self):
        super().setUp()
        self.home = self.root / "canonical"
        self.skill = valid_skill(self.home / "skills/sample")
        self.registry = self.home / "skill_updater/registry.json"
        self.state = self.root / "state"
        self.tools = self.root / "tools"
        self.commands = self.root / "bin"
        self.environment = patch.dict(os.environ, {
            "SKILL_NATIVE_TOOL_DIR": str(self.tools), "SKILL_NATIVE_BIN_DIR": str(self.commands),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        arch = "aarch64" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"
        self.target = f"{arch}-{'apple-darwin' if sys.platform == 'darwin' else 'unknown-linux-gnu'}"
        self.helper = "agent-desktop-macos-helper" if sys.platform == "darwin" else "agent-desktop-linux-clipboard-owner"
        self.archives = {}
        self.record = self.release("v1.2.0", "a" * 40)
        self.payload = {"version": 1, "skills": [{
            "name": "sample", "enabled": False, "skip_reason": "local fixture",
            "installed_hash": update_skills.tree_hash(self.skill),
        }], "release_tools": [self.record]}
        self.save()

    def release(self, tag, commit, *, interpreter=None):
        archive = self.root / f"fixture-{tag}.tar.gz"
        program = f'''#!{interpreter or sys.executable}
import json,os,sys
if any(key in os.environ for key in ("GH_TOKEN","GITHUB_TOKEN","OPENAI_API_KEY","AWS_SECRET_ACCESS_KEY")):
    sys.exit(42)
data={{"version":"{tag[1:]}","os":"{'macos' if sys.platform == 'darwin' else 'linux'}","target":"{self.target.split('-')[0]}"}}
if sys.argv[1]=="skills":
    skill="agent-desktop" if sys.argv[3]=="desktop" else "agent-desktop-{'macos' if sys.platform == 'darwin' else 'linux'}"
    data={{"skill":skill,"full":True,"content":"# Guide\\nObserve, act, verify."}}
print(json.dumps({{"ok":True,"data":data}}))
'''
        with tarfile.open(archive, "w:gz") as output:
            for name, content in (("agent-desktop", program), (self.helper, "#!/bin/sh\nexit 0\n")):
                raw = content.encode()
                member = tarfile.TarInfo(name)
                member.size, member.mode = len(raw), 0o755
                output.addfile(member, io.BytesIO(raw))
        self.archives[tag] = archive
        return {"name": "agent-desktop", "repo": "vercel-labs/agent-desktop", "tag": tag,
                "source_commit": commit, "used_by": ["sample"], "assets": {self.target: {
                    "name": f"agent-desktop-{tag}-{self.target}.tar.gz",
                    "size": archive.stat().st_size, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                }}}

    def save(self):
        write(self.registry, json.dumps(self.payload, indent=2) + "\n")

    def native(self):
        from skill_updater import release_tools
        return release_tools

    def package_boundaries(self):
        """Replace network/signing only; retain real install, journal and probes."""
        native = self.native()

        def download(tool, destination):
            shutil.copy2(self.archives[tool.tag], destination)

        download_patch = patch.object(native, "download_asset", side_effect=download)
        signature_patch = patch.object(native, "verify_attestation", return_value=None)
        download_patch.start()
        signature_patch.start()
        self.addCleanup(download_patch.stop)
        self.addCleanup(signature_patch.stop)


class ReleaseRegistryTests(ReleaseFixture):
    def test_invalid_release_is_rejected_at_public_registry_boundary(self):
        for key, value in (("repo", "untrusted/other"), ("source_commit", "main"),
                           ("tag", "../../outside"), ("used_by", ["missing"]), ("assets", {})):
            with self.subTest(key=key):
                self.payload["release_tools"] = [self.record | {key: value}]
                self.save()
                with self.assertRaises(ValueError):
                    update_skills.load_registry(self.registry)

    def test_metadata_save_preserves_release_record(self):
        self.assertEqual(0, update_skills.refresh_metadata(self.registry, self.home, self.state, apply=True))
        self.assertEqual([self.record], json.loads(self.registry.read_text())["release_tools"])

    def github(self, proposal):
        def fetch(endpoint):
            if endpoint.endswith("/releases/latest"):
                asset = proposal["assets"][self.target]
                return {"tag_name": proposal["tag"], "draft": False, "prerelease": False,
                        "assets": [{"name": asset["name"], "size": asset["size"],
                                    "digest": "sha256:" + asset["sha256"]}]}
            return {"sha": proposal["source_commit"]}
        return fetch

    def test_refresh_proposes_release_pins_without_installing(self):
        proposal = self.release("v1.3.0", "b" * 40)
        native = self.native()
        with patch.object(native, "github_json", side_effect=self.github(proposal)):
            self.assertEqual(0, update_skills.run_updates(self.registry, self.home, self.state, apply=True, run_setup=False))
        self.assertEqual([proposal], json.loads(self.registry.read_text())["release_tools"])
        self.assertFalse(self.tools.exists())
        events = json.loads((self.state / "logs/last_run_summary.json").read_text())["events"]
        self.assertEqual(1, sum(event["skill"] == "runtime:agent-desktop" for event in events))

    def test_failed_or_same_tag_drift_preserves_complete_record(self):
        native = self.native()
        for proposal in (self.record | {"assets": {}}, self.record | {"source_commit": "b" * 40}):
            with self.subTest(proposal=proposal), patch.object(native, "github_json", side_effect=self.github(proposal)):
                self.assertEqual(2, update_skills.run_updates(self.registry, self.home, self.state, apply=True, run_setup=False))
                self.assertEqual([self.record], json.loads(self.registry.read_text())["release_tools"])


class ReleaseDeploymentTests(ReleaseFixture):
    def mutation_preserves_existing(self, *, adoption=False, version_probe=False):
        self.package_boundaries()
        native = self.native()
        tool = native.load_releases(self.payload)[0]
        root = self.tools / "agent-desktop"
        if adoption:
            native.prepare_release(tool, root)
            self.commands.mkdir()
            for name in tool.executables:
                (self.commands / name).symlink_to(root / "bin" / name)
        else:
            update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True)
        binary = root / "bin/agent-desktop"
        before = binary.read_bytes()
        method = "verify_version" if version_probe else "probe_release"
        original = getattr(native, method)

        def mutate(*args):
            result = original(*args)
            binary.write_bytes(binary.read_bytes() + b"# probe mutation\n")
            return result

        with patch.object(native, method, side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "modified|integrity|drift"):
                update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True)
        self.assertEqual(before, binary.read_bytes())

    def test_unchanged_installation_restores_probe_mutation(self):
        self.mutation_preserves_existing()

    def test_first_adoption_restores_probe_mutation(self):
        self.mutation_preserves_existing(adoption=True)

    def test_version_preflight_restores_probe_mutation(self):
        self.mutation_preserves_existing(version_probe=True)

    def test_read_only_startup_probe_uses_an_isolated_copy(self):
        self.package_boundaries()
        update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True)
        native = self.native()
        binary = self.tools / "agent-desktop/bin/agent-desktop"
        original_bytes = binary.read_bytes()
        original = native.verify_version

        def mutate(path, *args):
            original(path, *args)
            path.write_bytes(path.read_bytes() + b"# version changed itself\n")

        with patch.object(native, "verify_version", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "modified|integrity"):
                update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=False)
        self.assertEqual(original_bytes, binary.read_bytes())

    def test_audit_executes_version_not_only_recorded_hashes(self):
        provider = self.root / "external-python"
        provider.symlink_to(sys.executable)
        self.payload["release_tools"] = [self.release("v1.2.0", "a" * 40, interpreter=provider)]
        self.save()
        self.package_boundaries()
        update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True)
        provider.unlink()
        self.assertEqual(1, update_skills.main(["audit", "--strict", "--registry", str(self.registry),
                                               "--codex-home", str(self.home), "--work-root", str(self.state)]))

    def test_service_credentials_do_not_reach_candidate_commands(self):
        self.package_boundaries()
        with patch.dict(os.environ, {"GH_TOKEN": "fixture-private", "OPENAI_API_KEY": "fixture-private"}):
            self.assertEqual(0, update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True))

    def test_missing_release_check_and_audit_are_read_only(self):
        self.assertEqual(1, update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=False))
        self.assertFalse(self.tools.exists())
        self.assertFalse(self.state.exists())
        self.assertEqual(1, update_skills.main(["audit", "--strict", "--registry", str(self.registry),
                                               "--codex-home", str(self.home), "--work-root", str(self.state)]))

    def test_verified_install_adoption_drift_and_command_ownership(self):
        self.package_boundaries()
        self.assertEqual(0, update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True))
        self.assertEqual(0, update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=False))
        program = self.tools / "agent-desktop/bin/agent-desktop"
        write(program, program.read_text() + "# local change\n")
        with self.assertRaisesRegex(ValueError, "drift|modified|integrity"):
            update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True)

    def test_foreign_command_is_preserved(self):
        original = write(self.commands / "agent-desktop", "user command\n")
        self.package_boundaries()
        with self.assertRaisesRegex(ValueError, "entrypoint|unmanaged|foreign"):
            update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True)
        self.assertEqual("user command\n", original.read_text())

    def test_first_adoption_compares_verified_archive_not_manifest_claims(self):
        native = self.native()
        self.package_boundaries()
        tool = native.load_releases(self.payload)[0]
        paths = native.release_paths(self.state)
        native.prepare_release(tool, self.tools / "agent-desktop")
        self.commands.mkdir()
        for name in tool.executables:
            (self.commands / name).symlink_to(self.tools / "agent-desktop/bin" / name)
        self.assertEqual(0, update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True))
        native._receipt(tool, paths).unlink()
        program = self.tools / "agent-desktop/bin/agent-desktop"
        write(program, program.read_text() + "# modified\n")
        manifest = self.tools / "agent-desktop/installation.json"
        data = json.loads(manifest.read_text())
        data["files"]["bin/agent-desktop"] = hashlib.sha256(program.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "archive|modified|integrity"):
            update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True)

    def test_later_skill_failure_rolls_back_native_update(self):
        self.package_boundaries()
        self.assertEqual(0, update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True))
        original = (self.tools / "agent-desktop/bin/agent-desktop").read_bytes()
        receipt = self.state / "release-tools/agent-desktop.json"
        old_receipt = receipt.read_bytes()
        self.payload["release_tools"] = [self.release("v1.3.0", "b" * 40)]
        self.save()
        with patch.object(update_skills, "_deploy_skill_files", side_effect=RuntimeError("skill failure")):
            with self.assertRaisesRegex(RuntimeError, "skill failure"):
                update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True)
        self.assertEqual(original, (self.tools / "agent-desktop/bin/agent-desktop").read_bytes())
        self.assertEqual(old_receipt, receipt.read_bytes())
        self.assertFalse(list(receipt.parent.glob("*.pending.json")))

    def test_probe_cannot_silently_modify_its_installation(self):
        self.package_boundaries()
        native = self.native()
        original_probe = native.probe_release

        def mutating_probe(tool, root, private_root):
            result = original_probe(tool, root, private_root)
            program = root / "bin/agent-desktop"
            program.write_text(program.read_text() + "# changed by probe\n")
            return result

        with patch.object(native, "probe_release", side_effect=mutating_probe):
            with self.assertRaisesRegex(ValueError, "modified|integrity"):
                update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True)
        self.assertFalse((self.tools / "agent-desktop").exists())
        self.assertFalse((self.state / "release-tools/agent-desktop.json").exists())

    def test_interrupted_native_update_recovers_before_retry(self):
        self.package_boundaries()
        update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True)
        native = self.native()
        tool = native.load_releases(self.payload)[0]
        paths = native.release_paths(self.state)
        native._prepare_rollback(tool, paths, replacing=True)
        original = (self.tools / "agent-desktop/bin/agent-desktop").read_bytes()
        write(self.tools / "agent-desktop/bin/agent-desktop", "interrupted replacement\n")
        with self.assertRaisesRegex(ValueError, "interrupted"):
            update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=False)
        update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True)
        self.assertEqual(original, (self.tools / "agent-desktop/bin/agent-desktop").read_bytes())


class ReleaseArchiveTests(ReleaseFixture):
    def probe_with_guides(self, content):
        native = self.native()
        tool = native.load_releases(self.payload)[0]
        os_name = "macos" if sys.platform == "darwin" else "linux"
        version = {"ok": True, "data": {"version": "1.2.0", "os": os_name,
                                           "target": self.target.split("-")[0]}}
        desktop = {"ok": True, "data": {"skill": "agent-desktop", "full": True, "content": content}}
        platform_guide = {"ok": True, "data": {"skill": "agent-desktop-" + os_name,
                                                  "full": True, "content": "# Platform guide\n"}}
        with patch.object(native, "_command", side_effect=[json.dumps(p) for p in (version, desktop, platform_guide)]):
            return native.probe_release(tool, self.root / "candidate", self.root / "private")

    def test_full_guides_block_unavailable_runtime_tools(self):
        for name in ("TodoWrite", "TodoRead", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode"):
            with self.subTest(tool=name):
                with self.assertRaisesRegex(ValueError, "compatibility|provider"):
                    self.probe_with_guides(f"# Guide\n\n## Linked reference\nUse {name} for desktop actions.\n")

    def test_documentary_provider_mentions_are_reported_not_runtime_directives(self):
        result = self.probe_with_guides("# Background\nClaude Code is another desktop client.\n")
        self.assertEqual("PASS", result["result"])
        self.assertTrue(result["compatibility_review"])

    def test_binary_guide_content_cannot_bypass_text_scan(self):
        with self.assertRaisesRegex(ValueError, "compatibility|coverage"):
            self.probe_with_guides("# Guide\n\0\nUse TodoWrite for desktop actions.\n")

    def test_archive_digest_mismatch_prevents_extraction(self):
        self.package_boundaries()
        record = self.record | {"assets": {self.target: self.record["assets"][self.target] | {"sha256": "0" * 64}}}
        native = self.native()
        tool = native.load_releases(self.payload | {"release_tools": [record]})[0]
        with self.assertRaisesRegex(ValueError, "digest"):
            native.prepare_release(tool, self.root / "candidate")
        self.assertFalse((self.root / "candidate/bin").exists())

    def test_unsafe_duplicate_and_missing_members_are_rejected(self):
        native = self.native()
        for case in ("traversal", "symlink", "duplicate", "missing", "oversize"):
            with self.subTest(case=case):
                archive = self.root / f"{case}.tar.gz"
                with tarfile.open(archive, "w:gz") as output:
                    if case != "missing":
                        member = tarfile.TarInfo("../outside" if case == "traversal" else "agent-desktop")
                        member.size, member.mode = 1, 0o755
                        if case == "symlink":
                            member.type, member.linkname, member.size = tarfile.SYMTYPE, "/outside", 0
                        output.addfile(member, io.BytesIO(b"x") if member.isfile() else None)
                        if case == "duplicate":
                            output.addfile(member, io.BytesIO(b"x"))
                        if case == "oversize":
                            member = tarfile.TarInfo(self.helper)
                            member.size = native.MAX_UNPACKED_BYTES + 1
                            output.addfile(member)
                self.archives[self.record["tag"]] = archive
                record = self.record | {"assets": {self.target: self.record["assets"][self.target] | {
                    "size": archive.stat().st_size, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                }}}
                tool = native.load_releases(self.payload | {"release_tools": [record]})[0]
                with patch.object(native, "download_asset", side_effect=lambda tool, dest: shutil.copy2(archive, dest)), \
                     patch.object(native, "verify_attestation", return_value=None):
                    with self.assertRaises(ValueError):
                        native.prepare_release(tool, self.root / f"candidate-{case}")
                self.assertFalse((self.root / "outside").exists())

    def test_signed_provenance_must_match_approved_source_and_asset(self):
        native = self.native()
        tool = native.load_releases(self.payload)[0]
        asset = tool.assets[self.target]
        verified = {"signature": {"certificate": {
            "sourceRepositoryURI": "https://github.com/" + tool.repo,
            "sourceRepositoryDigest": tool.source_commit, "githubWorkflowRepository": tool.repo,
        }}, "statement": {"subject": [{"name": asset.name, "digest": {"sha256": asset.sha256}}]}}
        with patch.object(native, "_command", return_value=json.dumps([{"verificationResult": verified}])):
            native.verify_attestation(tool, self.archives[tool.tag])
        verified["signature"]["certificate"]["sourceRepositoryDigest"] = "f" * 40
        with patch.object(native, "_command", return_value=json.dumps([{"verificationResult": verified}])):
            with self.assertRaisesRegex(ValueError, "attestation/source"):
                native.verify_attestation(tool, self.archives[tool.tag])
