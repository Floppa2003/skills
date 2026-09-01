from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


ALLOWED_SUFFIXES = {".md", ".py", ".js", ".mjs", ".ts", ".tsx", ".sh", ".json", ".yaml", ".yml"}
ALLOWED_SUFFIXES |= {
    ".bash",
    ".cfg",
    ".cjs",
    ".go",
    ".ini",
    ".java",
    ".kt",
    ".kts",
    ".lua",
    ".php",
    ".pl",
    ".rb",
    ".rs",
    ".rst",
    ".swift",
    ".toml",
    ".txt",
    ".zsh",
}
IGNORED_PARTS = {".git", "__pycache__", "node_modules"}
DOCUMENT_SUFFIXES = {".md", ".rst", ".txt"}
MAX_SCAN_BYTES = 2_000_000
PATTERNS = {
    "claude_path": re.compile(r"(?i)(?:~?/)?\.claude(?:/|\b)"),
    "anthropic_runtime": re.compile(
        r"(?i)\b(?:from|import)\s+anthropic\b|"
        r"\bAnthropic\s*\(|client\.messages\.create|claude-[\w.-]+"
    ),
    "claude_tool": re.compile(r"\b(?:AskUserQuestion|TodoWrite|TodoRead|EnterPlanMode|ExitPlanMode)\b"),
    "incompatible_metadata": re.compile(
        r"^(?:argument-hint|allowed-tools|user-invocable):", re.MULTILINE
    ),
    "provider_reference": re.compile(r"(?i)\b(?:claude(?:\s+code)?|anthropic)\b"),
    "slash_command_assumption": re.compile(
        r"(?<![\w./~])`?/[a-z][a-z0-9-]{2,}`?(?![\w./])"
    ),
}
BLOCKING_KINDS = {
    "claude_path",
    "anthropic_runtime",
    "claude_tool",
    "incompatible_metadata",
}
RUNTIME_DIRECTIVE = re.compile(
    r"(?i)(?:^|[-*]\s+)(?:you\s+)?(?:(?:must|required|should)\s+)?"
    r"(?:run|use|call|invoke|execute|load|read|write|edit|install|copy|source|open|create|spawn|launch)\b"
    r"|\b(?:MUST|REQUIRED)\b"
)
RUNTIME_CODE = re.compile(
    r"(?i)^\s*(?:from\s+anthropic\b|import\s+anthropic\b)"
    r"|client\.messages\.create"
    r"|\bAnthropic\s*\("
    r"|[\"']?model[\"']?\s*[:=]\s*[\"']?claude-"
)


@dataclass(frozen=True)
class CompatibilityFinding:
    path: str
    line: int
    kind: str
    match: str
    context: str
    disposition: str
    fingerprint: str

def files_to_scan(skill_dir: Path) -> list[Path]:
    paths = []
    for path in skill_dir.rglob("*"):
        relative = path.relative_to(skill_dir)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        if (
            path.is_symlink()
            or not path.is_file()
            or path.name == ".DS_Store"
            or path.stat().st_size > MAX_SCAN_BYTES
        ):
            continue
        if path.name == "SKILL.md" or path.suffix.lower() in ALLOWED_SUFFIXES or not path.suffix:
            sample = path.read_bytes()[:8192]
            if b"\0" not in sample:
                paths.append(path)
    return sorted(paths)


def _context(lines: list[str], line: int) -> str:
    start = max(0, line - 2)
    end = min(len(lines), line + 1)
    return "".join(lines[start:end]).strip()


def _fingerprint(kind: str, path: str, context: str) -> str:
    normalized = " ".join(context.split())
    payload = f"{kind}\0{path}\0{normalized}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def _disposition(kind: str, relative: Path, line_text: str) -> str:
    if kind not in BLOCKING_KINDS:
        return "review"
    is_document = relative.suffix.lower() in DOCUMENT_SUFFIXES
    if not is_document:
        return "block"
    if relative.as_posix() != "SKILL.md":
        return "review"
    if kind == "incompatible_metadata":
        return "block"
    if kind == "anthropic_runtime":
        return "block" if RUNTIME_DIRECTIVE.search(line_text) or RUNTIME_CODE.search(line_text) else "review"
    return "block" if RUNTIME_DIRECTIVE.search(line_text) else "review"


def scan_skill(skill_dir: Path) -> list[CompatibilityFinding]:
    findings: list[CompatibilityFinding] = []
    for path in files_to_scan(skill_dir):
        relative = path.relative_to(skill_dir)
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        for kind, pattern in PATTERNS.items():
            if kind == "slash_command_assumption" and relative.as_posix() != "SKILL.md":
                continue
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                excerpt = _context(lines, line)
                line_text = lines[line - 1].strip()
                relative_text = relative.as_posix()
                findings.append(
                    CompatibilityFinding(
                        path=relative_text,
                        line=line,
                        kind=kind,
                        match=match.group(0),
                        context=excerpt,
                        disposition=_disposition(kind, relative, line_text),
                        fingerprint=_fingerprint(kind, relative_text, excerpt),
                    )
                )
    return findings
