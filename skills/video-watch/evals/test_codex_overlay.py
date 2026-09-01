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
                with mock.patch.dict(
                    os.environ,
                    {"HOME": str(home)},
                    clear=False,
                ):
                    os.environ.pop("GROQ_API_KEY", None)
                    os.environ.pop("OPENAI_API_KEY", None)
                    self.assertEqual(whisper.load_api_key(), (None, None))
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


if __name__ == "__main__":
    unittest.main()
