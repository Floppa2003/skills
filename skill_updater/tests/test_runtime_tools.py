import json
import base64
import csv
import hashlib
import io
import os
import shutil
import signal
import sys
import time
import subprocess
from unittest.mock import patch

from skill_updater import update_skills
from skill_updater.tests.test_update_skills import TempDirTest, commit_all, git_repo, valid_skill, write


class RuntimeFixture(TempDirTest):
    def setUp(self):
        super().setUp()
        self.home = self.root / "canonical"
        self.skill = valid_skill(self.home / "skills/sample")
        self.registry = self.home / "skill_updater/registry.json"
        self.state = self.root / "state"
        self.repositories = {}
        packages = []
        for name in ("crapper", "dryer", "mutator"):
            repo = git_repo(self.root / name)
            write(repo / "pyproject.toml", f'[project]\nname = "{name}"\nversion = "0.1.0"\n')
            commit_all(repo)
            sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            self.repositories[name] = repo
            packages.append({"name": name, "repo": str(repo), "ref": "main", "commit": sha})
        self.bundle = {
            "name": "ub-mode-tools", "tool": "crapper", "python": "3.12",
            "used_by": ["sample"], "packages": packages,
            "requirements": ["coverage==7.17.0", "pytest==9.1.1"],
            "executables": ["crapper", "dryer", "mutator"], "probe": "ub-mode",
        }
        self.payload = {
            "version": 1,
            "skills": [{"name": "sample", "enabled": False, "skip_reason": "local fixture"}],
            "runtime_tools": [self.bundle],
        }
        self.save()

    def save(self):
        write(self.registry, json.dumps(self.payload, indent=2) + "\n")

    def advance(self, name):
        repo = self.repositories[name]
        write(repo / "README.md", "new source revision\n")
        commit_all(repo, "upstream change")
        return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


class RuntimeRegistryTests(RuntimeFixture):
    def test_metadata_rewrite_preserves_runtime_sources(self):
        (self.skill / "agents/openai.yaml").unlink()
        self.assertEqual(0, update_skills.refresh_metadata(self.registry, self.home, self.state, apply=True))
        self.assertEqual([self.bundle], json.loads(self.registry.read_text()).get("runtime_tools"))

    def test_invalid_runtime_contracts_are_rejected_at_registry_boundary(self):
        for key, value in (("name", "../outside"), ("python", "3.99"), ("tool", "foreign"),
                           ("used_by", ["absent"]), ("probe", "arbitrary-command"),
                           ("requirements", ["package @ https://untrusted.example/package.whl"])):
            with self.subTest(key=key):
                self.payload["runtime_tools"] = [self.bundle | {key: value}]
                self.save()
                with self.assertRaises(ValueError):
                    update_skills.load_registry(self.registry)

    def test_refresh_advances_runtime_pins_without_running_package_code(self):
        repo = self.repositories["crapper"]
        write(repo / "setup.py", "raise RuntimeError('refresh executed upstream code')\n")
        commit_all(repo, "untrusted build hook")
        expected = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        result = update_skills.run_updates(self.registry, self.home, self.state, apply=True, run_setup=False)
        self.assertEqual(0, result)
        saved = json.loads(self.registry.read_text()).get("runtime_tools", [])
        self.assertEqual(1, len(saved))
        self.assertEqual(expected, saved[0]["packages"][0]["commit"])
        summary = json.loads((self.state / "logs/last_run_summary.json").read_text())
        self.assertEqual({"sample", "runtime:ub-mode-tools"}, {e["skill"] for e in summary["events"]})
        self.assertEqual("updated", next(e for e in summary["events"] if e["skill"].startswith("runtime:"))["status"])

    def test_check_mode_reports_new_pin_without_changing_registry(self):
        expected = self.advance("dryer")
        before = self.registry.read_bytes()
        self.assertEqual(0, update_skills.run_updates(self.registry, self.home, self.state, apply=False, run_setup=False))
        self.assertEqual(before, self.registry.read_bytes())
        summary = json.loads((self.state / "logs/last_run_summary.json").read_text())
        events = [e for e in summary["events"] if e["skill"] == "runtime:ub-mode-tools"]
        self.assertEqual(1, len(events))
        self.assertIn(expected, events[0]["message"])

    def test_failed_source_preserves_all_bundle_pins(self):
        self.advance("crapper")
        self.bundle["packages"][1]["ref"] = "missing-branch"
        self.save()
        self.assertEqual(2, update_skills.run_updates(self.registry, self.home, self.state, apply=True, run_setup=False))
        self.assertEqual([self.bundle], json.loads(self.registry.read_text()).get("runtime_tools"))
        summary = json.loads((self.state / "logs/last_run_summary.json").read_text())
        self.assertEqual(["runtime:ub-mode-tools"], [e["skill"] for e in summary["errors"]])
        self.assertTrue(summary["errors"][0]["installed_copy_preserved"])


class RuntimeDeploymentTests(RuntimeFixture):
    def setUp(self):
        super().setUp()
        from skill_updater.runtime_tools import load_bundles
        self.bundle = load_bundles(self.payload)[0]
        self.tool_dir = self.root / "uv-tools"
        self.bin_dir = self.root / "bin"
        self.environment = patch.dict(os.environ, {"UV_TOOL_DIR": str(self.tool_dir), "UV_TOOL_BIN_DIR": str(self.bin_dir)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.payload["skills"][0]["installed_hash"] = update_skills.tree_hash(self.skill)
        self.save()

    def install_fixture(self, bundle):
        env = self.tool_dir / bundle.tool
        site = env / "lib/python3.12/site-packages"
        write(env / "pyvenv.cfg", "version_info = 3.12.13\n")
        write(env / "bin/python", "fixture interpreter\n")
        records = []
        for package in bundle.packages:
            records.append((package.name, "0.1.0", {
                "url": self.repositories[package.name].as_uri(),
                "vcs_info": {"vcs": "git", "commit_id": package.commit},
            }))
        records += [("coverage", "7.17.0", None), ("pytest", "9.1.1", None)]
        for name, version, origin in records:
            module = write(site / name / "__init__.py", f"value = '{name}'\n")
            metadata = site / f"{name}-{version}.dist-info"
            files = [module, write(metadata / "METADATA", f"Name: {name}\nVersion: {version}\n")]
            if origin:
                files.append(write(metadata / "direct_url.json", json.dumps(origin)))
            output = io.StringIO()
            writer = csv.writer(output)
            for path in files:
                content = path.read_bytes()
                digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip("=")
                writer.writerow([str(path.relative_to(site)), f"sha256={digest}", len(content)])
            write(metadata / "RECORD", output.getvalue())
        self.bin_dir.mkdir(exist_ok=True)
        entrypoints = []
        for command in bundle.executables:
            executable = write(env / "bin" / command, "#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            link = self.bin_dir / command
            if not link.is_symlink():
                link.symlink_to(executable)
            entrypoints.append(f'{{ name = "{command}", install-path = "{link}", from = "{command}" }}')
        write(env / "uv-receipt.toml", "[tool]\nentrypoints = [" + ",".join(entrypoints) + "]\n")
        return env

    def test_deploy_check_accounts_for_missing_runtime_without_creating_it(self):
        before = self.registry.read_bytes()
        self.assertEqual(1, update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=False))
        self.assertFalse(self.tool_dir.exists())
        self.assertFalse(self.state.exists())
        self.assertEqual(before, self.registry.read_bytes())

    def test_foreign_entrypoint_is_not_overwritten(self):
        original = write(self.bin_dir / "crapper", "user-owned command\n")
        with self.assertRaisesRegex(ValueError, "entrypoint|unmanaged|foreign"):
            update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=False)
        self.assertEqual("user-owned command\n", original.read_text())

    def test_modified_installed_source_is_detected(self):
        env = self.install_fixture(self.bundle)
        write(env / "lib/python3.12/site-packages/crapper/__init__.py", "user modification\n")
        with self.assertRaisesRegex(ValueError, "modified|integrity|drift"):
            update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=False)

    def test_strict_audit_detects_missing_runtime(self):
        self.assertEqual(1, update_skills.main([
            "audit", "--strict", "--registry", str(self.registry),
            "--codex-home", str(self.home), "--work-root", str(self.state),
        ]))

    def test_install_failure_restores_environment_and_commands(self):
        from skill_updater import runtime_tools
        env = self.install_fixture(self.bundle)
        with patch.object(runtime_tools, "probe_bundle", return_value={"result": "PASS"}, create=True):
            self.assertEqual(0, update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True))
        marker = self.state / "runtime-tools/ub-mode-tools.json"
        self.assertTrue(marker.exists(), "deployment must record the verified runtime installation")
        before = marker.read_bytes()
        self.payload["runtime_tools"][0]["packages"][0]["commit"] = "b" * 40
        self.save()

        def broken_install(bundle, paths):
            write(env / "lib/python3.12/site-packages/crapper/__init__.py", "broken install\n")
            raise RuntimeError("installation failed")

        # Only the external installer/probe boundary is replaced for fault injection.
        with patch.object(runtime_tools, "install_bundle", side_effect=broken_install, create=True):
            with self.assertRaisesRegex(RuntimeError, "installation failed"):
                update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True)
        self.assertEqual("value = 'crapper'\n", (env / "lib/python3.12/site-packages/crapper/__init__.py").read_text())
        self.assertEqual(before, marker.read_bytes())
        self.assertEqual((env / "bin/crapper").resolve(), (self.bin_dir / "crapper").resolve())

    def test_later_skill_failure_restores_earlier_runtime_replacement(self):
        from skill_updater import runtime_tools
        env = self.install_fixture(self.bundle)
        with patch.object(runtime_tools, "probe_bundle", return_value={"result": "PASS"}, create=True):
            update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True)
        self.assertTrue((self.state / "runtime-tools/ub-mode-tools.json").exists())
        before = (env / "lib/python3.12/site-packages/crapper-0.1.0.dist-info/direct_url.json").read_bytes()
        self.payload["runtime_tools"][0]["packages"][0]["commit"] = "b" * 40
        self.save()
        live = self.root / "live"
        shutil.copytree(self.home / "skills", live / "skills")
        valid_skill(live / "skills/untracked")
        with patch.object(runtime_tools, "install_bundle", side_effect=lambda bundle, paths: self.install_fixture(bundle), create=True), \
             patch.object(runtime_tools, "probe_bundle", return_value={"result": "PASS"}, create=True):
            with self.assertRaisesRegex(ValueError, "outside the canonical registry"):
                update_skills.deploy_skills(self.registry, self.home, live, self.state, apply=True)
        self.assertEqual(before, (env / "lib/python3.12/site-packages/crapper-0.1.0.dist-info/direct_url.json").read_bytes())

    def test_missing_recovery_backup_preserves_live_environment(self):
        from skill_updater import runtime_tools
        env = self.install_fixture(self.bundle)
        paths = runtime_tools.tool_paths(self.state)
        runtime_tools._prepare_rollback(self.bundle, paths, replacing=True)
        shutil.rmtree(runtime_tools._backup(self.bundle, paths) / "environment")
        source = write(env / "lib/python3.12/site-packages/crapper/__init__.py", "current live source\n")
        with self.assertRaises((ValueError, FileNotFoundError)):
            runtime_tools.recover_bundle(self.bundle, paths)
        self.assertTrue(source.exists(), "a missing backup must not cause deletion of the live environment")
        self.assertEqual("current live source\n", source.read_text())

    def test_successful_pin_update_is_installed_and_then_current(self):
        from skill_updater import runtime_tools
        env = self.install_fixture(self.bundle)
        with patch.object(runtime_tools, "probe_bundle", return_value={"result": "PASS"}):
            update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True)
        self.payload["runtime_tools"][0]["packages"][0]["commit"] = "b" * 40
        self.save()
        with patch.object(runtime_tools, "install_bundle", side_effect=lambda bundle, paths: self.install_fixture(bundle)), \
             patch.object(runtime_tools, "probe_bundle", return_value={"result": "PASS"}):
            self.assertEqual(0, update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True))
        origin = json.loads((env / "lib/python3.12/site-packages/crapper-0.1.0.dist-info/direct_url.json").read_text())
        self.assertEqual("b" * 40, origin["vcs_info"]["commit_id"])
        marker = (self.state / "runtime-tools/ub-mode-tools.json").read_bytes()
        self.assertEqual(0, update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=False))
        self.assertEqual(marker, (self.state / "runtime-tools/ub-mode-tools.json").read_bytes())

    def test_interrupted_install_is_recovered_only_on_apply(self):
        from skill_updater import runtime_tools
        env = self.install_fixture(self.bundle)
        with patch.object(runtime_tools, "probe_bundle", return_value={"result": "PASS"}):
            update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True)
        paths = runtime_tools.tool_paths(self.state)
        runtime_tools._prepare_rollback(self.bundle, paths, replacing=True)
        source = write(env / "lib/python3.12/site-packages/crapper/__init__.py", "interrupted replacement\n")
        with self.assertRaisesRegex(ValueError, "interrupted"):
            update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=False)
        self.assertEqual("interrupted replacement\n", source.read_text())
        with patch.object(runtime_tools, "probe_bundle", return_value={"result": "PASS"}):
            self.assertEqual(0, update_skills.deploy_skills(self.registry, self.home, self.home, self.state, apply=True))
        self.assertEqual("value = 'crapper'\n", source.read_text())
        self.assertFalse(runtime_tools._pending(self.bundle, paths).exists())

    def test_runtime_subprocess_environment_excludes_credentials(self):
        from skill_updater import runtime_tools
        with patch.dict(os.environ, {"GITHUB_TOKEN": "synthetic-canary", "AWS_SECRET_ACCESS_KEY": "synthetic-canary",
                                     "UV_INDEX_URL": "https://synthetic-canary@example.invalid"}):
            result = runtime_tools._environment(runtime_tools.tool_paths(self.state))
        self.assertNotIn("GITHUB_TOKEN", result)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", result)
        self.assertNotIn("UV_INDEX_URL", result)
        self.assertNotIn("synthetic-canary", json.dumps(result))

    def test_corrupt_recovery_commands_cannot_touch_foreign_link(self):
        from skill_updater import runtime_tools
        env = self.install_fixture(self.bundle)
        paths = runtime_tools.tool_paths(self.state)
        runtime_tools._prepare_rollback(self.bundle, paths, replacing=False)
        foreign = self.root / "do-not-touch"
        foreign.symlink_to(self.root / "original-target")
        pending = runtime_tools._pending(self.bundle, paths)
        journal = json.loads(pending.read_text())
        journal["links"]["../do-not-touch"] = True
        pending.write_text(json.dumps(journal))
        with self.assertRaises(ValueError):
            runtime_tools.recover_bundle(self.bundle, paths)
        self.assertEqual(str(self.root / "original-target"), os.readlink(foreign))


class RuntimeCommandTests(TempDirTest):
    def test_interrupt_stops_active_installer_before_rollback(self):
        pidfile = self.root / "installer.pid"
        program = "import os,sys,time; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
        driver = (
            "import sys; from skill_updater.runtime_tools import _command; "
            "_command([sys.executable,'-c',sys.argv[1],sys.argv[2]])"
        )
        process = subprocess.Popen([sys.executable, "-B", "-c", driver, program, str(pidfile)],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            for _ in range(100):
                if pidfile.exists():
                    break
                time.sleep(0.05)
            self.assertTrue(pidfile.exists(), "installer did not start")
            os.kill(process.pid, signal.SIGINT)
            process.communicate(timeout=5)
            child = int(pidfile.read_text())
            status = subprocess.run(["ps", "-o", "stat=", "-p", str(child)], capture_output=True, text=True).stdout.strip()
            self.assertFalse(status and not status.startswith("Z"), "interrupted updater left its installer writing")
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
            if pidfile.exists():
                try:
                    os.kill(int(pidfile.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_timeout_stops_its_child_process_without_killing_other_group(self):
        from skill_updater.runtime_tools import _command
        pidfile = self.root / "child.pid"
        script = (
            "import subprocess,sys,time; from pathlib import Path; "
            "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],"
            "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
            "Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)"
        )
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        try:
            with self.assertRaises((TimeoutError, subprocess.TimeoutExpired)):
                _command([sys.executable, "-c", script, str(pidfile)], timeout=1)
            child = int(pidfile.read_text())
            running = True
            for _ in range(20):
                status = subprocess.run(["ps", "-o", "stat=", "-p", str(child)], capture_output=True, text=True).stdout.strip()
                running = bool(status and not status.startswith("Z"))
                if not running:
                    break
                time.sleep(0.05)
            self.assertFalse(running, "runtime timeout left its child running")
            self.assertIsNone(other.poll(), "runtime timeout killed an unrelated process group")
        finally:
            other.terminate()
            other.wait(timeout=5)
            if pidfile.exists():
                try:
                    os.kill(int(pidfile.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass
