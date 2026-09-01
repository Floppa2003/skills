#!/usr/bin/env python3
from __future__ import annotations

import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from skill_updater.update_skills import load_registry, validate_canonical_skills


SKILLS_DIR = ROOT / "skills"
REGISTRY_PATH = ROOT / "skill_updater/registry.json"
FORBIDDEN_NAMES = {
    "__MACOSX",
    ".DS_Store",
    ".bootstrap",
    ".import-v2",
    "node_modules",
    "__pycache__",
}
FORBIDDEN_ROOTS = {"archive", "archives", "chunks", "transport"}
FORBIDDEN_SUFFIXES = {
    ".7z",
    ".bz2",
    ".gz",
    ".orig",
    ".pyc",
    ".rar",
    ".tar",
    ".tgz",
    ".xz",
    ".zip",
    ".zst",
}
FORBIDDEN_TRANSPORT_TEXT = ("drive.google.com", "gdown")


def validate_clean_tree() -> None:
    if (ROOT / "AGENTS.md").exists():
        raise ValueError("repo-level AGENTS.md is forbidden")
    if (SKILLS_DIR / ".system").exists():
        raise ValueError("Codex-managed skills/.system is forbidden")
    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.splitlines()
    for value in tracked:
        path = Path(value)
        if path.parts and path.parts[0].casefold() in FORBIDDEN_ROOTS:
            raise ValueError(f"forbidden transport directory: {path.parts[0]}")
        if FORBIDDEN_NAMES.intersection(path.parts) or path.suffix.casefold() in FORBIDDEN_SUFFIXES:
            raise ValueError(f"forbidden repository artifact: {path.as_posix()}")
        if (
            path != Path("scripts/validate_repository.py")
            and path.parts
            and path.parts[0] != "skills"
            and (ROOT / path).is_file()
        ):
            try:
                content = (ROOT / path).read_text(encoding="utf-8").casefold()
            except UnicodeDecodeError:
                continue
            if any(marker in content for marker in FORBIDDEN_TRANSPORT_TEXT):
                raise ValueError(f"forbidden transport reference: {path.as_posix()}")


def validate_skills() -> None:
    specs = load_registry(REGISTRY_PATH)
    validate_canonical_skills(specs, SKILLS_DIR)


def main() -> int:
    validate_clean_tree()
    validate_skills()
    print(f"repository valid: skills={len(list(SKILLS_DIR.glob('*/SKILL.md')))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
