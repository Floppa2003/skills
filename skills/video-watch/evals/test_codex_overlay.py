from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import setup  # noqa: E402
import whisper  # noqa: E402
import config  # noqa: E402
import download  # noqa: E402
import watch  # noqa: E402


class CodexOverlayTests(unittest.TestCase):
    def test_macos_dependency_check_never_invokes_brew(self) -> None:
        with (
            mock.patch.object(setup, "_which", return_value="/opt/homebrew/bin/brew"),
            mock.patch.object(setup.subprocess, "run") as run,
        ):
            ok, message = setup._install_macos(["ffmpeg", "yt-dlp"])

        self.assertFalse(ok)
        self.assertIn("brew install ffmpeg yt-dlp", message)
        run.assert_not_called()

    def test_whisper_does_not_read_project_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            (root / ".env").write_text("OPENAI_API_KEY=project-secret\n", encoding="utf-8")
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with (
                    mock.patch.dict(os.environ, {}, clear=True),
                    mock.patch.object(config, "CONFIG_FILE", home / ".env"),
                ):
                    self.assertEqual(whisper.load_api_key(), (None, None))
                    self.assertIsNone(config.load_gemini_key())
            finally:
                os.chdir(previous_cwd)

    def test_watch_requires_explicit_whisper_opt_in(self) -> None:
        source = (SCRIPTS / "watch.py").read_text(encoding="utf-8")

        self.assertIn('"--allow-whisper"', source)
        self.assertIn("args.allow_whisper", source)

    def test_keyless_caption_mode_can_proceed(self) -> None:
        with (
            mock.patch.object(setup, "_check_binaries", return_value=[]),
            mock.patch.object(setup, "_have_api_key", return_value=(False, None)),
            mock.patch.object(setup, "is_first_run", return_value=True),
        ):
            status = setup._status()

        self.assertTrue(status["can_proceed"])
        self.assertEqual(status["status"], "ready")

    def test_skill_frontmatter_is_codex_compatible(self) -> None:
        source = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", source, re.DOTALL)

        self.assertIsNotNone(match)
        frontmatter = match.group(1)
        self.assertIn("name: video-watch", frontmatter)
        self.assertNotIn("argument-hint:", frontmatter)
        self.assertNotIn("user-invocable:", frontmatter)
        self.assertNotIn("allowed-tools:", frontmatter)

    def test_runtime_has_no_claude_specific_references(self) -> None:
        for path in (ROOT / "SKILL.md", SCRIPTS / "setup.py", SCRIPTS / "whisper.py"):
            self.assertNotIn("claude", path.read_text(encoding="utf-8").lower())
        self.assertFalse((SCRIPTS / "build-skill.sh").exists())

    def test_cookies_rejected_and_inherited_ytdlp_config_disabled(self) -> None:
        for values in (("cookies.txt", None), (None, "chrome")):
            with self.assertRaisesRegex(SystemExit, "public sources only"):
                download.auth_args(*values)
        command = download._common(Path("."), download.auth_args())
        self.assertIn("--ignore-config", command)
        self.assertIn("--no-cookies-from-browser", command)

    def run_local_watch(self, *options):
        import contextlib
        import io
        with (
            tempfile.TemporaryDirectory() as temporary,
            mock.patch.dict(os.environ, {"WATCH_ENGINE": "gemini", "GEMINI_API_KEY": "test", "OPENAI_API_KEY": "test"}, clear=True),
            mock.patch.object(config, "CONFIG_FILE", Path(temporary) / "config"),
            mock.patch.object(sys, "argv", ["watch.py", "local.mp4", "--detail", "transcript", "--out-dir", temporary, *options]),
            mock.patch.object(watch, "download", return_value={"video_path": "local.mp4", "info": {}}),
            mock.patch.object(watch, "get_metadata", return_value={"duration_seconds": 1, "has_audio": True, "has_video": True}),
            mock.patch.object(watch, "run_gemini") as cloud,
            mock.patch.object(watch, "transcribe_video", return_value=([], "openai")) as asr,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            watch.main()
            return cloud.call_count, asr.call_count

    def test_saved_cloud_settings_do_not_authorize_uploads(self) -> None:
        self.assertEqual(self.run_local_watch(), (0, 0))
        self.assertEqual(self.run_local_watch("--engine", "auto"), (0, 0))

    def test_explicit_transcription_consent_allows_selected_backend(self) -> None:
        self.assertEqual(self.run_local_watch("--allow-whisper", "--whisper", "openai"), (0, 1))

    def test_explicit_video_analysis_selects_gemini(self) -> None:
        self.assertEqual(self.run_local_watch("--engine", "gemini", "--question", "Describe this video"), (1, 0))

    def test_provider_selection_without_consent_fails_before_network(self) -> None:
        with self.assertRaises(SystemExit) as error:
            self.run_local_watch("--whisper", "openai")
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
