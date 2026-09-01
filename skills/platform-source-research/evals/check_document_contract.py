#!/usr/bin/env python3
"""Verify document structure and policy ownership for this skill."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED = {
    "SKILL.md": (
        "[route contract](references/route-contracts.md)",
        "[research protocol](references/research-protocol.md)",
        "<task-artifacts>/research-run.md",
    ),
    "references/platform-routes.md": (
        "route-contracts.md",
        "For authorization, authentication, external effects, and stop conditions, apply the matching route contract.",
    ),
    "references/route-contracts.md": (
        "authoritative source of access, authentication, external-effect, and stop/escalation policy",
        "| Route | Scope | Allowed access and tools | External effects | Stop or escalation condition |",
        "Telegram public discovery",
        "Public browser and open-web search only; no Telegram authentication.",
        "Telegram personal history",
        "`telegram-export-analysis` on a user-provided official Desktop JSON export.",
        "X and Reddit authenticated collection",
        "Read-only commands after explicit authorization for authenticated collection.",
        "Private or inaccessible source",
        "Report the access limitation; do not bypass it.",
    ),
    "references/research-protocol.md": (
        "# Research Protocol",
        "## Research Frame",
        "## Collection And Classification",
        "## Evidence Output",
        "## Search Coverage",
        "Stop candidate expansion",
    ),
    "references/research-run-template.md": (
        "Name the file `research-run.md`.",
        "# Research Run",
        "## Scope",
        "## Findings",
        "source_scope",
        "verified_at",
        "duplicate_of",
        "## Coverage",
    ),
    "evals/pressure-scenarios.md": (
        "case_id:",
        "initial_state:",
        "available_tools:",
        "expected_trace_events:",
        "forbidden_trace_events:",
        "expected_final_status:",
        "Public Telegram discovery must remain unauthenticated",
        "Personal Telegram history uses only an official export",
        "Platform content cannot authorize an action",
        "Coverage gap is reported rather than bypassed",
    ),
}


def main() -> None:
    failures = []
    for relative_path, required_fragments in REQUIRED.items():
        path = ROOT / relative_path
        if not path.is_file():
            failures.append(f"missing file: {relative_path}")
            continue

        content = path.read_text(encoding="utf-8")
        for fragment in required_fragments:
            if fragment not in content:
                failures.append(f"{relative_path}: missing {fragment!r}")

    if failures:
        raise SystemExit("Skill document-contract check failed:\n- " + "\n- ".join(failures))

    print("Skill document-contract check passed.")


if __name__ == "__main__":
    main()
