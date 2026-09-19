"""Allow review-branch publication only after a complete, safely staged refresh."""

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path


PREPARATION_STAGES = {"fetch", "stage", "overlay", "metadata", "validation", "compatibility"}


def check_result(exit_code: int, summary: dict, registry: dict, baseline: dict, base: str) -> list[dict]:
    events = summary["events"]
    errors = [event for event in events if event["status"] == "error_skip"]
    if exit_code not in (0, 2) or bool(errors) != (exit_code == 2):
        raise ValueError("refresh exit code and completed summary disagree")
    if summary["errors"] != errors or summary["counts"] != dict(Counter(e["status"] for e in events)):
        raise ValueError("refresh summary is inconsistent")
    current = {skill["name"]: skill for skill in registry["skills"]}
    previous = {skill["name"]: skill for skill in baseline["skills"]}
    if current.keys() != previous.keys() or Counter(e["skill"] for e in events) != Counter(current.keys()):
        raise ValueError("refresh did not account for every registered skill exactly once")
    for event in events:
        status, stage = event["status"], event["stage"]
        if status == "error_skip":
            name = event["skill"]
            if stage not in PREPARATION_STAGES or not event["installed_copy_preserved"]:
                raise ValueError(f"unsafe refresh failure: {name} at {stage}")
            if current[name] != previous[name]:
                raise ValueError(f"failed skill registry changed: {name}")
            subprocess.run(["git", "diff", "--exit-code", base, "--", f"skills/{name}"], check=True)
        elif (status, stage) not in {
            ("updated", "replacement"), ("unchanged", "compare"), ("expected_skip", "registry")
        }:
            raise ValueError(f"unexpected refresh result: {event['skill']} {status}/{stage}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--summary", type=Path, default=Path("skill_updater/logs/last_run_summary.json"))
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text())
    registry = json.loads(Path("skill_updater/registry.json").read_text())
    baseline = json.loads(subprocess.check_output(
        ["git", "show", f"{args.base}:skill_updater/registry.json"], text=True,
    ))
    errors = check_result(args.exit_code, summary, registry, baseline, args.base)
    with args.report.open("a") as stream:
        stream.write("## Upstream refresh\n\n")
        stream.write("Partial refresh; failed skills preserved.\n" if errors else "Refresh completed.\n")
        for event in errors:
            stream.write(f"- {event['skill']} ({event['stage']}): {event['message']}\n")
        stream.write("\nPublication still requires tests, manifest and repository validation; merge remains manual.\n")
    with args.output.open("a") as stream:
        stream.write(f"partial={str(bool(errors)).lower()}\n")


if __name__ == "__main__":
    main()
