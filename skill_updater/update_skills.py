#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

try:
    from skill_updater.compatibility import CompatibilityFinding, scan_skill
    from skill_updater.openai_metadata import ensure_openai_yaml, validate_openai_yaml
except ModuleNotFoundError:
    from compatibility import CompatibilityFinding, scan_skill
    from openai_metadata import ensure_openai_yaml, validate_openai_yaml


ROOT = Path(__file__).resolve().parent
IGNORED_PARTS = {".git", "__pycache__", "node_modules"}
SENSITIVE_NAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "application_default_credentials.json",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "service-account.json",
    "service_account.json",
}
SENSITIVE_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}
PATH_STUB = re.compile(r"^(?:\.\.?/)+[^\r\n]+$")
SKILL_DIRECTORY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RUNTIME_SETUPS = {"npm_ci": ("npm", "ci")}


class RegistryError(ValueError):
    pass


class ValidationError(ValueError):
    pass


class OverlayError(RuntimeError):
    pass


class CompatibilityError(ValidationError):
    pass


@dataclass(frozen=True)
class SkillSpec:
    name: str
    repo: str | None = None
    path: str | None = None
    ref: str = "main"
    adapter: str = "directory"
    overlay: str | None = None
    enabled: bool = True
    installed_commit: str | None = None
    installed_hash: str | None = None
    skip_reason: str | None = None
    required_paths: tuple[str, ...] = ()
    runtime_setup: tuple[str, ...] = ()
    accepted_compatibility_fingerprints: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SkillSpec:
        normalized = dict(data)
        normalized["required_paths"] = tuple(normalized.get("required_paths", ()))
        normalized["runtime_setup"] = tuple(normalized.get("runtime_setup", ()))
        normalized["accepted_compatibility_fingerprints"] = tuple(
            normalized.get("accepted_compatibility_fingerprints", ())
        )
        return cls(**normalized)


@dataclass
class SkillEvent:
    skill: str
    status: str
    stage: str
    repo: str | None
    ref: str | None
    upstream_commit: str | None
    error_type: str | None
    message: str
    installed_copy_preserved: bool
    suggested_action: str | None = None


@dataclass(frozen=True)
class PreparedCandidate:
    root: Path
    tree_hash: str
    accepted_compatibility_fingerprints: tuple[str, ...]


@dataclass(frozen=True)
class RetiredSkill:
    name: str
    installed_hashes: tuple[str, ...]
    reason: str


def _load_registry_payload(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot read registry: {exc}") from exc
    if not isinstance(payload, dict):
        raise RegistryError("registry must be a mapping")
    if payload.get("version") != 1 or not isinstance(payload.get("skills"), list):
        raise RegistryError("registry requires version 1 and a skills list")
    return payload


def load_registry_state(path: Path) -> tuple[list[SkillSpec], list[RetiredSkill]]:
    payload = _load_registry_payload(path)
    specs = [SkillSpec.from_dict(item) for item in payload["skills"]]
    seen: set[str] = set()
    for spec in specs:
        if spec.name in seen:
            raise RegistryError(f"duplicate skill: {spec.name}")
        seen.add(spec.name)
        if spec.repo is None and not spec.skip_reason:
            raise RegistryError(f"{spec.name} requires skip_reason")
        if spec.repo is not None and spec.path is None:
            raise RegistryError(f"{spec.name} requires path")
        unknown_setups = set(spec.runtime_setup) - RUNTIME_SETUPS.keys()
        if unknown_setups:
            raise RegistryError(f"{spec.name} has unknown runtime setup: {sorted(unknown_setups)[0]}")
    raw = payload.get("retired_skills", [])
    if not isinstance(raw, list):
        raise RegistryError("retired_skills must be a list")
    retired = []
    retired_names: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise RegistryError("retired skill must be a mapping")
        name = item.get("name")
        hashes = item.get("installed_hashes")
        reason = item.get("reason")
        if not isinstance(name, str) or not SKILL_DIRECTORY_NAME.fullmatch(name):
            raise RegistryError(f"invalid retired skill name: {name}")
        if name in retired_names:
            raise RegistryError(f"duplicate retired skill: {name}")
        retired_names.add(name)
        if (
            not isinstance(hashes, list)
            or not hashes
            or any(not isinstance(value, str) or not SHA256.fullmatch(value) for value in hashes)
        ):
            raise RegistryError(f"invalid retired skill hash for {name}")
        if not isinstance(reason, str) or not reason.strip():
            raise RegistryError(f"retired skill {name} requires reason")
        retired.append(RetiredSkill(name, tuple(hashes), reason))
    overlap = seen & retired_names
    if overlap:
        raise RegistryError(f"active skill is also retired: {sorted(overlap)[0]}")
    return specs, retired


def load_registry(path: Path) -> list[SkillSpec]:
    return load_registry_state(path)[0]


def audit_skills(specs: list[SkillSpec], skills_dir: Path) -> list[SkillEvent]:
    registered = {spec.name for spec in specs}
    if not skills_dir.exists():
        return []
    return [
        SkillEvent(
            skill=skill_dir.name,
            status="untracked",
            stage="audit",
            repo=None,
            ref=None,
            upstream_commit=None,
            error_type=None,
            message="installed skill has no registry entry; provenance was not inferred",
            installed_copy_preserved=True,
            suggested_action="use adopt with an explicit source or add a disabled registry entry",
        )
        for skill_dir in sorted(skills_dir.iterdir())
        if skill_dir.is_dir() and not skill_dir.name.startswith(".") and skill_dir.name not in registered
    ]


def _ignored(path: Path) -> bool:
    return (
        any(part in IGNORED_PARTS for part in path.parts)
        or path.name == ".DS_Store"
        or path.suffix == ".pyc"
    )


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if _ignored(relative):
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        if path.is_symlink():
            digest.update(b"L")
            digest.update(os.readlink(path).encode("utf-8"))
        elif path.is_file():
            digest.update(b"F")
            digest.update(b"X" if path.stat().st_mode & 0o111 else b"-")
            digest.update(path.read_bytes())
        elif path.is_dir():
            digest.update(b"D")
    return digest.hexdigest()


def _frontmatter(skill_file: Path) -> dict[str, str]:
    try:
        content = skill_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError("missing SKILL.md") from exc
    if not content.startswith("---\n"):
        raise ValidationError("SKILL.md requires YAML frontmatter")
    end = content.find("\n---", 4)
    if end == -1:
        raise ValidationError("SKILL.md has unterminated frontmatter")
    fields: dict[str, str] = {}
    for line in content[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"\'')
    return fields


def _escapes(root: Path, link: Path) -> bool:
    target = (link.parent / os.readlink(link)).resolve(strict=False)
    try:
        target.relative_to(root.resolve())
        return False
    except ValueError:
        return True


def validate_candidate(root: Path, required_paths: tuple[str, ...] = ()) -> None:
    fields = _frontmatter(root / "SKILL.md")
    if not fields.get("name") or not fields.get("description"):
        raise ValidationError("SKILL.md requires name and description")
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if path.is_symlink() and _escapes(root, path):
            raise ValidationError(f"escaping symlink: {relative.as_posix()}")
        if path.is_file() and not path.is_symlink():
            if (
                path.name.lower() in SENSITIVE_NAMES
                or path.name.startswith(".env.")
                or path.suffix.lower() in SENSITIVE_SUFFIXES
            ):
                raise ValidationError(f"sensitive file: {relative.as_posix()}")
            if path.stat().st_size <= 512:
                try:
                    value = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    value = ""
                if PATH_STUB.fullmatch(value):
                    raise ValidationError(f"path stub: {relative.as_posix()}")
    for relative in required_paths:
        if not (root / relative).exists():
            raise ValidationError(f"missing required path: {relative}")


def group_by_source(specs: Iterable[SkillSpec]) -> dict[tuple[str, str], list[SkillSpec]]:
    grouped: dict[tuple[str, str], list[SkillSpec]] = defaultdict(list)
    for spec in specs:
        if spec.enabled and spec.repo:
            grouped[(spec.repo, spec.ref)].append(spec)
    return dict(grouped)


def _validate_repo_symlinks(source: Path, repo_root: Path) -> None:
    repo_root = repo_root.resolve()
    for link in source.rglob("*"):
        if not link.is_symlink():
            continue
        target = (link.parent / os.readlink(link)).resolve(strict=False)
        try:
            target.relative_to(repo_root)
        except ValueError as exc:
            raise ValidationError(f"source symlink escapes repository: {link}") from exc


def _copy_tree(source: Path, destination: Path, repo_root: Path) -> None:
    if not source.exists():
        raise ValidationError(f"missing upstream path: {source.relative_to(repo_root)}")
    _validate_repo_symlinks(source, repo_root)
    shutil.copytree(
        source,
        destination,
        symlinks=False,
        ignore=shutil.ignore_patterns(".git", ".DS_Store", "__pycache__", "*.pyc", "node_modules"),
    )


def canonicalize_skill_entrypoint(root: Path) -> None:
    entries = {path.name: path for path in root.iterdir()}
    if "SKILL.md" in entries:
        return
    lowercase_entrypoint = entries.get("skill.md")
    if lowercase_entrypoint:
        lowercase_entrypoint.rename(root / "SKILL.md")


def stage_candidate(spec: SkillSpec, repo: Path, stage_root: Path) -> Path:
    destination = stage_root / spec.name
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if spec.adapter == "uiux":
        destination.mkdir()
        shutil.copy2(repo / ".claude/skills/ui-ux-pro-max/SKILL.md", destination / "SKILL.md")
        source_root = repo / "src/ui-ux-pro-max"
        for name in ("scripts", "data", "templates"):
            source = source_root / name
            if source.exists():
                _copy_tree(source, destination / name, repo)
        return destination
    if spec.adapter not in {"directory", "repo_root"}:
        raise ValidationError(f"unknown adapter: {spec.adapter}")
    source = repo if spec.adapter == "repo_root" else repo / str(spec.path)
    _copy_tree(source, destination, repo)
    canonicalize_skill_entrypoint(destination)
    return destination


def _patch_command(skill_root: Path, patch_path: Path, dry_run: bool) -> subprocess.CompletedProcess[str]:
    command = ["patch", "-p1", "--forward", "--remove-empty-files", "--silent"]
    if dry_run:
        command.append("--dry-run")
    with patch_path.open("r", encoding="utf-8") as patch_file:
        return subprocess.run(
            command,
            cwd=skill_root,
            stdin=patch_file,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )


def apply_overlay(skill_root: Path, patch_path: Path) -> None:
    dry_run = _patch_command(skill_root, patch_path, dry_run=True)
    if dry_run.returncode:
        raise OverlayError(f"patch no longer applies: {dry_run.stdout.strip()}")
    applied = _patch_command(skill_root, patch_path, dry_run=False)
    if applied.returncode or list(skill_root.rglob("*.rej")):
        raise OverlayError(f"patch failed: {applied.stdout.strip()}")
    for backup in skill_root.rglob("*.orig"):
        backup.unlink()


def recover_interrupted_replacement(installed: Path) -> None:
    rollback = installed.parent / f".{installed.name}.skill-updater-rollback"
    if not rollback.exists():
        return
    if installed.exists():
        shutil.rmtree(rollback)
    else:
        rollback.rename(installed)


def replace_with_rollback(installed: Path, candidate: Path, backup: Path) -> None:
    recover_interrupted_replacement(installed)
    rollback = installed.parent / f".{installed.name}.skill-updater-rollback"
    try:
        if installed.exists():
            installed.rename(rollback)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(rollback, backup, symlinks=True)
        candidate.rename(installed)
    except Exception:
        if installed.exists():
            shutil.rmtree(installed)
        if rollback.exists():
            rollback.rename(installed)
        raise
    else:
        if rollback.exists():
            shutil.rmtree(rollback)


def remove_with_rollback(installed: Path, backup: Path) -> None:
    recover_interrupted_replacement(installed)
    rollback = installed.parent / f".{installed.name}.skill-updater-rollback"
    try:
        installed.rename(rollback)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(rollback, backup, symlinks=True)
        shutil.rmtree(rollback)
    except Exception:
        if not installed.exists() and rollback.exists():
            rollback.rename(installed)
        raise


class RunLogger:
    def __init__(self, log_dir: Path, run_id: str):
        self.log_dir = log_dir
        self.run_id = run_id
        self.events: list[SkillEvent] = []
        log_dir.mkdir(parents=True, exist_ok=True)
        self.readable_path = log_dir / f"{run_id}.log"
        self.jsonl_path = log_dir / f"{run_id}.jsonl"

    def emit(self, event: SkillEvent) -> None:
        self.events.append(event)
        payload = asdict(event)
        with self.jsonl_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        parts = [
            event.status.upper(),
            f"skill={event.skill}",
            f"stage={event.stage}",
            f"repo={event.repo or '-'}",
            f"commit={event.upstream_commit or '-'}",
            f"preserved={'yes' if event.installed_copy_preserved else 'no'}",
            f"message={event.message}",
        ]
        if event.suggested_action:
            parts.append(f"action={event.suggested_action}")
        with self.readable_path.open("a", encoding="utf-8") as stream:
            stream.write(" ".join(parts) + "\n")

    def finish(self) -> int:
        errors = [asdict(event) for event in self.events if event.status == "error_skip"]
        counts: dict[str, int] = defaultdict(int)
        for event in self.events:
            counts[event.status] += 1
        summary = {
            "run_id": self.run_id,
            "counts": dict(sorted(counts.items())),
            "errors": errors,
            "events": [asdict(event) for event in self.events],
        }
        temporary = self.log_dir / ".last_run_summary.json.tmp"
        temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.log_dir / "last_run_summary.json")
        return 2 if errors else 0


def prune_run_logs(log_dir: Path, keep: int = 12) -> None:
    run_ids = sorted(path.stem for path in log_dir.glob("*.jsonl"))
    for run_id in run_ids[:-keep]:
        for suffix in (".jsonl", ".log"):
            path = log_dir / f"{run_id}{suffix}"
            if path.exists():
                path.unlink()


def prune_backups(backup_root: Path, keep_per_skill: int = 4) -> None:
    if not backup_root.exists():
        return
    for skill_dir in backup_root.iterdir():
        if not skill_dir.is_dir():
            continue
        backups = sorted(path for path in skill_dir.iterdir() if path.is_dir())
        for path in backups[:-keep_per_skill]:
            shutil.rmtree(path)


def _run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode:
        rendered = " ".join(command)
        raise RuntimeError(f"command failed ({result.returncode}): {rendered}: {result.stdout.strip()}")
    return result


def require_review_branch(repository_root: Path) -> str:
    branch = _run(["git", "branch", "--show-current"], cwd=repository_root).stdout.strip()
    if not branch:
        raise RuntimeError("refresh --apply requires a named review branch")
    if branch in {"main", "master"}:
        raise RuntimeError(f"refresh --apply is forbidden on protected branch: {branch}")
    return branch


def clone_repo(repo: str, ref: str, destination: Path) -> str:
    local = Path(repo).expanduser()
    source = str(local) if local.exists() or repo.startswith("/") else f"https://github.com/{repo}.git"
    _run(["git", "clone", "--quiet", "--depth", "1", "--branch", ref, source, str(destination)])
    return _run(["git", "rev-parse", "HEAD"], cwd=destination).stdout.strip()


def runtime_setup_missing(spec: SkillSpec, root: Path) -> bool:
    return "npm_ci" in spec.runtime_setup and not (root / "node_modules").is_dir()


def run_runtime_setup(spec: SkillSpec, root: Path) -> None:
    for setup in spec.runtime_setup:
        _run(list(RUNTIME_SETUPS[setup]), cwd=root)


def _save_registry(path: Path, specs: list[SkillSpec]) -> None:
    retired = load_registry_state(path)[1] if path.exists() else []
    overlap = {spec.name for spec in specs} & {skill.name for skill in retired}
    if overlap:
        raise RegistryError(f"active skill is also retired: {sorted(overlap)[0]}")
    payload = {
        "version": 1,
        "retired_skills": [asdict(skill) for skill in retired],
        "skills": [asdict(spec) for spec in specs],
    }
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _compatibility_error(findings: list[CompatibilityFinding]) -> CompatibilityError:
    examples = "; ".join(
        f"{finding.path}:{finding.line} {finding.kind} [{finding.fingerprint}]"
        for finding in findings[:5]
    )
    suffix = "" if len(findings) <= 5 else f"; and {len(findings) - 5} more"
    return CompatibilityError(
        f"Codex-incompatible runtime references require an overlay: {examples}{suffix}"
    )


def validate_skill_compatibility(
    root: Path,
    accepted_fingerprints: tuple[str, ...] = (),
) -> list[CompatibilityFinding]:
    findings = scan_skill(root)
    _raise_compatibility_blockers(findings, accepted_fingerprints=accepted_fingerprints)
    return findings


def _raise_compatibility_blockers(
    findings: list[CompatibilityFinding],
    accepted_fingerprints: tuple[str, ...] = (),
) -> None:
    allowed = set(accepted_fingerprints)
    blockers = [
        finding
        for finding in findings
        if finding.disposition == "block" and finding.fingerprint not in allowed
    ]
    if blockers:
        raise _compatibility_error(blockers)


def _blocking_fingerprints(findings: list[CompatibilityFinding]) -> set[str]:
    return {
        finding.fingerprint
        for finding in findings
        if finding.disposition == "block"
    }


def _candidate_state(
    spec: SkillSpec,
    root: Path,
    findings: list[CompatibilityFinding] | None = None,
) -> PreparedCandidate:
    findings = findings if findings is not None else validate_skill_compatibility(
        root,
        spec.accepted_compatibility_fingerprints,
    )
    blockers = _blocking_fingerprints(findings)
    active_accepted = tuple(
        fingerprint
        for fingerprint in spec.accepted_compatibility_fingerprints
        if fingerprint in blockers
    )
    return PreparedCandidate(root, tree_hash(root), active_accepted)


def _finding_record(finding: CompatibilityFinding) -> dict[str, object]:
    return {
        "path": finding.path,
        "line": finding.line,
        "kind": finding.kind,
        "match": finding.match,
        "disposition": finding.disposition,
        "fingerprint": finding.fingerprint,
    }


def write_compatibility_report(
    work_root: Path,
    spec: SkillSpec,
    commit: str,
    upstream: list[CompatibilityFinding],
    final: list[CompatibilityFinding],
    accepted_fingerprints: tuple[str, ...] = (),
) -> None:
    payload = {
        "version": 1,
        "skill": spec.name,
        "repo": spec.repo,
        "path": spec.path,
        "ref": spec.ref,
        "upstream_commit": commit,
        "upstream_findings": [_finding_record(finding) for finding in upstream],
        "final_findings": [_finding_record(finding) for finding in final],
        "accepted_fingerprints": sorted(accepted_fingerprints),
        "new_blocking_fingerprints": sorted(
            finding.fingerprint
            for finding in final
            if finding.disposition == "block"
            and finding.fingerprint not in accepted_fingerprints
        ),
    }
    destination = work_root / "compatibility" / f"{spec.name}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)


def _prepare_staged_candidate(
    spec: SkillSpec,
    repository: Path,
    stage_root: Path,
    work_root: Path,
    commit: str,
) -> PreparedCandidate:
    stage = "stage"
    try:
        candidate = stage_candidate(spec, repository, stage_root)
        upstream_findings = scan_skill(candidate)
        if spec.overlay:
            stage = "overlay"
            apply_overlay(candidate, work_root / spec.overlay)
        stage = "metadata"
        ensure_openai_yaml(candidate, spec.name)
        stage = "validation"
        validate_candidate(candidate, spec.required_paths)
        stage = "compatibility"
        final_findings = scan_skill(candidate)
        write_compatibility_report(
            work_root,
            spec,
            commit,
            upstream_findings,
            final_findings,
            accepted_fingerprints=spec.accepted_compatibility_fingerprints,
        )
        _raise_compatibility_blockers(
            final_findings,
            accepted_fingerprints=spec.accepted_compatibility_fingerprints,
        )
        return _candidate_state(spec, candidate, final_findings)
    except Exception as exc:
        exc.candidate_preparation_stage = stage
        raise


def _prepare_candidate(
    spec: SkillSpec,
    work_root: Path,
) -> tuple[tempfile.TemporaryDirectory, PreparedCandidate, str]:
    temporary_root = work_root / "tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="lifecycle-", dir=temporary_root)
    try:
        repository = Path(temporary.name) / "repo"
        commit = clone_repo(str(spec.repo), spec.ref, repository)
        prepared = _prepare_staged_candidate(
            spec,
            repository,
            Path(temporary.name) / "stage",
            work_root,
            commit,
        )
        return temporary, prepared, commit
    except Exception:
        temporary.cleanup()
        raise


def _register_spec(registry_path: Path, specs: list[SkillSpec], spec: SkillSpec) -> None:
    if any(current.name == spec.name for current in specs):
        raise ValueError(f"skill already registered: {spec.name}")
    _save_registry(registry_path, [*specs, spec])


@contextmanager
def _exclusive_lock(work_root: Path) -> Iterator[None]:
    work_root.mkdir(parents=True, exist_ok=True)
    with (work_root / ".update.lock").open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another updater run is active") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def adopt_skill(spec: SkillSpec, registry_path: Path, codex_home: Path, work_root: Path) -> None:
    with _exclusive_lock(work_root):
        specs = load_registry(registry_path)
        installed = codex_home / "skills" / spec.name
        if not installed.exists():
            raise ValueError(f"installed skill is missing: {spec.name}")

        temporary, prepared, commit = _prepare_candidate(spec, work_root)
        try:
            run_runtime_setup(spec, prepared.root)
            prepared = _candidate_state(spec, prepared.root)
            candidate_hash = prepared.tree_hash
            installed_hash = tree_hash(installed)
            if installed_hash != candidate_hash:
                raise ValueError(
                    f"installed skill does not match explicit upstream source: "
                    f"installed hash={installed_hash}; upstream hash={candidate_hash}"
                )
            _register_spec(
                registry_path,
                specs,
                replace(
                    spec,
                    installed_commit=commit,
                    installed_hash=candidate_hash,
                    accepted_compatibility_fingerprints=prepared.accepted_compatibility_fingerprints,
                ),
            )
        finally:
            temporary.cleanup()


def add_skill(
    spec: SkillSpec,
    registry_path: Path,
    codex_home: Path,
    work_root: Path,
    replace_existing: bool = False,
) -> None:
    with _exclusive_lock(work_root):
        specs = load_registry(registry_path)
        registered = any(current.name == spec.name for current in specs)
        if registered and not replace_existing:
            raise ValueError(f"skill already registered: {spec.name}")
        installed = codex_home / "skills" / spec.name
        installed.parent.mkdir(parents=True, exist_ok=True)
        if installed.exists() and not replace_existing:
            raise ValueError(f"skill already installed: {spec.name}; pass --replace to overwrite it")

        temporary, prepared, commit = _prepare_candidate(spec, work_root)
        try:
            candidate_hash = prepared.tree_hash
            backup = work_root / "backups" / spec.name / datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")
            replace_with_rollback(installed, prepared.root, backup)
            try:
                _save_registry(
                    registry_path,
                    [
                        *[current for current in specs if current.name != spec.name],
                        replace(
                            spec,
                            installed_commit=commit,
                            installed_hash=candidate_hash,
                            accepted_compatibility_fingerprints=(
                                prepared.accepted_compatibility_fingerprints
                            ),
                        ),
                    ],
                )
            except Exception:
                if installed.exists():
                    shutil.rmtree(installed)
                if backup.exists():
                    backup.rename(installed)
                raise
        finally:
            temporary.cleanup()


def _event(
    spec: SkillSpec,
    status: str,
    stage: str,
    message: str,
    commit: str | None = None,
    error: Exception | None = None,
    preserved: bool = True,
    action: str | None = None,
) -> SkillEvent:
    return SkillEvent(
        skill=spec.name,
        status=status,
        stage=stage,
        repo=spec.repo,
        ref=spec.ref,
        upstream_commit=commit,
        error_type=type(error).__name__ if error else None,
        message=message,
        installed_copy_preserved=preserved,
        suggested_action=action,
    )


def _error_action(stage: str) -> str:
    return {
        "registry": "repair the registry JSON before the next run",
        "registry_state": "verify registry permissions; the next run will reconcile installed state",
        "recovery": "inspect the installed skill and its rollback directory",
        "fetch": "verify the repository, ref, and network access",
        "stage": "verify the registered upstream path and adapter",
        "overlay": "review upstream SKILL.md and refresh the Codex overlay",
        "metadata": "repair agents/openai.yaml or add a reviewed overlay",
        "runtime_setup": "inspect the registered runtime setup and its local package manager output",
        "validation": "inspect the staged skill for missing or unsafe files",
        "compatibility": "remove the runtime dependency or add a reviewed Codex overlay",
        "replacement": "inspect the backup and destination permissions",
    }.get(stage, "inspect the run log")


def _global_error(stage: str, error: Exception) -> SkillEvent:
    return SkillEvent(
        skill="*",
        status="error_skip",
        stage=stage,
        repo=None,
        ref=None,
        upstream_commit=None,
        error_type=type(error).__name__,
        message=str(error),
        installed_copy_preserved=True,
        suggested_action=_error_action(stage),
    )


def run_updates(
    registry_path: Path,
    codex_home: Path,
    work_root: Path = ROOT,
    apply: bool = False,
    run_setup: bool = True,
) -> int:
    run_id = datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")
    log = RunLogger(work_root / "logs", run_id)
    work_root.mkdir(parents=True, exist_ok=True)
    lock_path = work_root / ".update.lock"
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.emit(
                SkillEvent(
                    skill="*",
                    status="error_skip",
                    stage="lock",
                    repo=None,
                    ref=None,
                    upstream_commit=None,
                    error_type="ConcurrentRunError",
                    message="another updater run is active",
                    installed_copy_preserved=True,
                    suggested_action="wait for the active run to finish",
                )
            )
            return log.finish()

        try:
            specs = load_registry(registry_path)
        except Exception as exc:
            log.emit(_global_error("registry", exc))
            return log.finish()
        state = list(specs)
        index_by_name = {spec.name: index for index, spec in enumerate(specs)}
        skills_dir = codex_home / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        for event in audit_skills(specs, skills_dir):
            log.emit(event)
        stage_root = skills_dir / ".skill-updater-staging" / run_id
        stage_root.mkdir(parents=True)
        temporary_root = work_root / "tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        recovery_failed: set[str] = set()
        replacements: list[tuple[Path, Path, bool]] = []
        pending_update_events: list[SkillEvent] = []

        try:
            for spec in specs:
                try:
                    recover_interrupted_replacement(skills_dir / spec.name)
                except Exception as exc:
                    recovery_failed.add(spec.name)
                    log.emit(
                        _event(
                            spec,
                            "error_skip",
                            "recovery",
                            str(exc),
                            error=exc,
                            action=_error_action("recovery"),
                        )
                    )
                if not spec.enabled or not spec.repo:
                    log.emit(
                        _event(
                            spec,
                            "expected_skip",
                            "registry",
                            spec.skip_reason or "skill is intentionally unmanaged",
                        )
                    )

            with tempfile.TemporaryDirectory(prefix="run-", dir=temporary_root) as temporary:
                clone_root = Path(temporary)
                for group_number, ((repo_name, ref), repo_specs) in enumerate(
                    group_by_source(specs).items(), start=1
                ):
                    repo_path = clone_root / f"repo-{group_number}"
                    try:
                        commit = clone_repo(repo_name, ref, repo_path)
                    except Exception as exc:
                        for spec in repo_specs:
                            log.emit(
                                _event(
                                    spec,
                                    "error_skip",
                                    "fetch",
                                    str(exc),
                                    error=exc,
                                    action=_error_action("fetch"),
                                )
                            )
                        continue

                    for spec in repo_specs:
                        if spec.name in recovery_failed:
                            continue
                        installed = skills_dir / spec.name
                        stage = "stage"
                        try:
                            prepared = _prepare_staged_candidate(
                                spec,
                                repo_path,
                                stage_root,
                                work_root,
                                commit,
                            )
                            candidate = prepared.root
                            candidate_hash = prepared.tree_hash
                            stage = "compare"
                            current_hash = tree_hash(installed) if installed.exists() else None
                            if current_hash == candidate_hash:
                                state[index_by_name[spec.name]] = replace(
                                    spec,
                                    installed_commit=commit,
                                    installed_hash=candidate_hash,
                                    accepted_compatibility_fingerprints=(
                                        prepared.accepted_compatibility_fingerprints
                                    ),
                                )
                                if apply and run_setup and runtime_setup_missing(spec, installed):
                                    stage = "runtime_setup"
                                    run_runtime_setup(spec, candidate)
                                    prepared = _candidate_state(spec, candidate)
                                    stage = "replacement"
                                    backup = work_root / "backups" / spec.name / run_id
                                    replace_with_rollback(installed, candidate, backup)
                                    replacements.append((installed, backup, True))
                                    state[index_by_name[spec.name]] = replace(
                                        spec,
                                        installed_commit=commit,
                                        installed_hash=prepared.tree_hash,
                                        accepted_compatibility_fingerprints=(
                                            prepared.accepted_compatibility_fingerprints
                                        ),
                                    )
                                    pending_update_events.append(
                                        _event(
                                            spec,
                                            "updated",
                                            "runtime_setup",
                                            f"runtime dependencies restored; backup={backup}",
                                            commit=commit,
                                            preserved=False,
                                        )
                                    )
                                    continue
                                log.emit(
                                    _event(spec, "unchanged", "compare", "already current", commit=commit)
                                )
                                continue
                            if (
                                spec.installed_hash
                                and current_hash is not None
                                and current_hash != spec.installed_hash
                            ):
                                log.emit(
                                    _event(
                                        spec,
                                        "expected_skip",
                                        "local_drift",
                                        f"local hash={current_hash}; managed hash={spec.installed_hash}",
                                        commit=commit,
                                    )
                                )
                                continue
                            if not apply:
                                log.emit(
                                    _event(
                                        spec,
                                        "unchanged",
                                        "check",
                                        "update available; check mode made no changes",
                                        commit=commit,
                                    )
                                )
                                continue
                            if run_setup:
                                stage = "runtime_setup"
                                run_runtime_setup(spec, candidate)
                                prepared = _candidate_state(spec, candidate)
                                candidate_hash = prepared.tree_hash
                                if current_hash == candidate_hash:
                                    state[index_by_name[spec.name]] = replace(
                                        spec,
                                        installed_commit=commit,
                                        installed_hash=candidate_hash,
                                        accepted_compatibility_fingerprints=(
                                            prepared.accepted_compatibility_fingerprints
                                        ),
                                    )
                                    log.emit(
                                        _event(
                                            spec,
                                            "unchanged",
                                            "compare",
                                            "already current after runtime setup",
                                            commit=commit,
                                        )
                                    )
                                    continue
                            stage = "replacement"
                            backup = work_root / "backups" / spec.name / run_id
                            had_installed = installed.exists()
                            replace_with_rollback(installed, candidate, backup)
                            replacements.append((installed, backup, had_installed))
                            state[index_by_name[spec.name]] = replace(
                                spec,
                                installed_commit=commit,
                                installed_hash=candidate_hash,
                                accepted_compatibility_fingerprints=(
                                    prepared.accepted_compatibility_fingerprints
                                ),
                            )
                            pending_update_events.append(
                                _event(
                                    spec,
                                    "updated",
                                    "replacement",
                                    f"installed; backup={backup}",
                                    commit=commit,
                                    preserved=False,
                                )
                            )
                        except Exception as exc:
                            stage = getattr(exc, "candidate_preparation_stage", stage)
                            log.emit(
                                _event(
                                    spec,
                                    "error_skip",
                                    stage,
                                    str(exc),
                                    commit=commit,
                                    error=exc,
                                    preserved=installed.exists(),
                                    action=_error_action(stage),
                                )
                            )
        finally:
            try:
                if stage_root.exists():
                    shutil.rmtree(stage_root)
                parent = stage_root.parent
                if parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
            except Exception as exc:
                log.emit(_global_error("cleanup", exc))

        if apply:
            try:
                _save_registry(registry_path, state)
            except Exception as exc:
                rollback_errors = []
                for installed, backup, had_installed in reversed(replacements):
                    try:
                        if installed.exists():
                            shutil.rmtree(installed)
                        if had_installed:
                            if not backup.exists():
                                raise FileNotFoundError(f"missing replacement backup: {backup}")
                            backup.rename(installed)
                    except Exception as rollback_error:
                        rollback_errors.append(rollback_error)
                log.emit(_global_error("registry_state", exc))
                for rollback_error in rollback_errors:
                    log.emit(_global_error("recovery", rollback_error))
            else:
                for event in pending_update_events:
                    log.emit(event)
        prune_run_logs(work_root / "logs")
        prune_backups(work_root / "backups")
        return log.finish()


def validate_canonical_skills(
    specs: list[SkillSpec],
    skills_root: Path,
    *,
    update_hashes: bool = False,
) -> list[SkillSpec]:
    if (skills_root / ".system").exists():
        raise ValidationError("canonical skills must not contain .system")
    events = audit_skills(specs, skills_root)
    if events:
        raise ValidationError(f"untracked canonical skill: {events[0].skill}")
    state = []
    for spec in specs:
        skill = skills_root / spec.name
        if not skill.is_dir():
            raise ValidationError(f"registered skill is missing: {spec.name}")
        validate_candidate(skill, spec.required_paths)
        fields = _frontmatter(skill / "SKILL.md")
        if fields["name"] != spec.name:
            raise ValidationError(
                f"skill name mismatch: registry={spec.name} frontmatter={fields['name']}"
            )
        validate_openai_yaml(skill, spec.name)
        findings = validate_skill_compatibility(
            skill,
            spec.accepted_compatibility_fingerprints,
        )
        blockers = _blocking_fingerprints(findings)
        accepted = set(spec.accepted_compatibility_fingerprints)
        stale = accepted - blockers
        if stale:
            raise ValidationError(
                f"compatibility fingerprint mismatch for {spec.name}: "
                f"new=[] stale={sorted(stale)}"
            )
        actual_hash = tree_hash(skill)
        if not update_hashes and spec.installed_hash != actual_hash:
            raise ValidationError(
                f"canonical hash mismatch for {spec.name}: "
                f"expected={spec.installed_hash} actual={actual_hash}"
            )
        state.append(replace(spec, installed_hash=actual_hash))
    return state


def refresh_metadata(
    registry_path: Path,
    repository_root: Path,
    work_root: Path = ROOT,
    apply: bool = False,
) -> int:
    specs, _ = load_registry_state(registry_path)
    source = repository_root / "skills"
    temporary_root = work_root / "tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="metadata-", dir=temporary_root) as temporary:
        staged = Path(temporary) / "skills"
        shutil.copytree(
            source,
            staged,
            symlinks=True,
            ignore=shutil.ignore_patterns(".DS_Store", "__pycache__", "*.pyc", "node_modules"),
        )
        generated = []
        for spec in specs:
            skill = staged / spec.name
            if ensure_openai_yaml(skill, spec.name):
                generated.append(spec.name)
        state = validate_canonical_skills(specs, staged, update_hashes=True)
        tree_changed = tree_hash(staged) != tree_hash(source)
        registry_changed = state != specs
        if not tree_changed and not registry_changed:
            print("metadata current: generated=0")
            return 0
        if not apply:
            print(
                f"metadata changes available: generated={len(generated)} "
                f"registry_hashes={'yes' if registry_changed else 'no'}"
            )
            return 1

        backup = work_root / "backups" / "canonical-skills" / datetime.now().strftime(
            "%Y-%m-%dT%H-%M-%S-%f"
        )
        if tree_changed:
            replace_with_rollback(source, staged, backup)
        try:
            _save_registry(registry_path, state)
        except Exception:
            if tree_changed:
                if source.exists():
                    shutil.rmtree(source)
                backup.rename(source)
            raise
        print(f"metadata updated: generated={len(generated)}")
        return 0


def deploy_skills(
    registry_path: Path,
    repository_root: Path,
    codex_home: Path,
    work_root: Path = ROOT,
    apply: bool = False,
) -> int:
    specs, retired = load_registry_state(registry_path)
    source = repository_root / "skills"
    validate_canonical_skills(specs, source)

    destination = codex_home / "skills"
    destination.mkdir(parents=True, exist_ok=True)
    retirements = []
    retired_names = {skill.name for skill in retired}
    for skill in retired:
        installed = destination / skill.name
        if not installed.is_dir():
            continue
        actual_hash = tree_hash(installed)
        if actual_hash not in skill.installed_hashes:
            raise ValidationError(
                f"retired skill has local drift: {skill.name}; "
                f"actual={actual_hash} expected one of={list(skill.installed_hashes)}"
            )
        retirements.append(skill)
    untracked = [
        event
        for event in audit_skills(specs, destination)
        if event.skill not in retired_names
    ]
    if untracked:
        raise ValidationError(f"local skill is outside the canonical registry: {untracked[0].skill}")
    changed = [
        spec
        for spec in specs
        if not (destination / spec.name).is_dir()
        or tree_hash(destination / spec.name) != spec.installed_hash
        or runtime_setup_missing(spec, destination / spec.name)
    ]
    change_count = len(changed) + len(retirements)
    if not change_count:
        print("local deployment current: changed=0")
        return 0
    if not apply:
        print(f"local deployment changes available: changed={change_count}")
        return 1

    run_id = datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")
    stage_parent = destination / ".skill-updater-staging"
    stage = stage_parent / run_id
    stage.mkdir(parents=True)
    replacements: list[tuple[Path, Path, bool]] = []
    try:
        for spec in changed:
            candidate = stage / spec.name
            shutil.copytree(
                source / spec.name,
                candidate,
                symlinks=True,
                ignore=shutil.ignore_patterns(".DS_Store", "__pycache__", "*.pyc", "node_modules"),
            )
            validate_candidate(candidate, spec.required_paths)
            validate_openai_yaml(candidate, spec.name)
            run_runtime_setup(spec, candidate)
            if tree_hash(candidate) != spec.installed_hash:
                raise ValidationError(f"staged deployment hash mismatch for {spec.name}")

        for spec in changed:
            installed = destination / spec.name
            backup = work_root / "backups" / f"local-{spec.name}" / run_id
            had_installed = installed.exists()
            replace_with_rollback(installed, stage / spec.name, backup)
            replacements.append((installed, backup, had_installed))
        for skill in retirements:
            installed = destination / skill.name
            backup = work_root / "backups" / f"local-{skill.name}" / run_id
            remove_with_rollback(installed, backup)
            replacements.append((installed, backup, True))
    except Exception:
        for installed, backup, had_installed in reversed(replacements):
            if installed.exists():
                shutil.rmtree(installed)
            if had_installed:
                backup.rename(installed)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if stage_parent.exists() and not any(stage_parent.iterdir()):
            stage_parent.rmdir()
    prune_backups(work_root / "backups")
    print(f"local deployment updated: changed={change_count}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safely update registered Codex skills")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="check without replacing skills")
    mode.add_argument("--apply", action="store_true", help="apply valid updates")
    parser.add_argument("--registry", type=Path, default=ROOT / "registry.json")
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))),
    )
    parser.add_argument("--work-root", type=Path, default=ROOT)
    return parser


def _lifecycle_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register and audit Codex skills with explicit provenance")
    commands = parser.add_subparsers(dest="command", required=True)

    def add_common_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--name", required=True)
        command.add_argument("--repo", required=True, help="GitHub owner/repo")
        command.add_argument("--path", required=True, help="path within the repository")
        command.add_argument("--ref", default="main")
        command.add_argument("--adapter", default="directory", choices=("directory", "repo_root", "uiux"))
        command.add_argument("--overlay")
        command.add_argument("--required-path", action="append", default=[])
        command.add_argument("--runtime-setup", action="append", choices=tuple(RUNTIME_SETUPS), default=[])

    def add_location_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--registry", type=Path, default=ROOT / "registry.json")
        command.add_argument(
            "--codex-home",
            type=Path,
            default=ROOT.parent,
        )
        command.add_argument("--work-root", type=Path, default=ROOT)

    def add_repository_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--registry", type=Path, default=ROOT / "registry.json")
        command.add_argument("--repository-root", type=Path, default=ROOT.parent)
        command.add_argument("--work-root", type=Path, default=ROOT)

    def add_mode(command: argparse.ArgumentParser) -> None:
        mode = command.add_mutually_exclusive_group(required=True)
        mode.add_argument("--check", action="store_true")
        mode.add_argument("--apply", action="store_true")

    add = commands.add_parser("add", help="install and register a skill atomically")
    add_common_arguments(add)
    add_location_arguments(add)
    add.add_argument("--replace", action="store_true")

    adopt = commands.add_parser("adopt", help="register an exact installed upstream skill")
    add_common_arguments(adopt)
    add_location_arguments(adopt)

    audit = commands.add_parser("audit", help="report installed skills without registry entries")
    add_location_arguments(audit)
    audit.add_argument("--strict", action="store_true", help="return nonzero when untracked skills exist")

    refresh = commands.add_parser("refresh", help="refresh canonical skills from registered upstreams")
    add_repository_arguments(refresh)
    add_mode(refresh)

    metadata = commands.add_parser("metadata", help="generate and validate agents/openai.yaml")
    add_repository_arguments(metadata)
    add_mode(metadata)

    deploy = commands.add_parser("deploy", help="deploy the canonical repository to local Codex")
    add_repository_arguments(deploy)
    deploy.add_argument(
        "--codex-home",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))),
    )
    add_mode(deploy)
    return parser


def _lifecycle_spec(args: argparse.Namespace) -> SkillSpec:
    return SkillSpec(
        name=args.name,
        repo=args.repo,
        path=args.path,
        ref=args.ref,
        adapter=args.adapter,
        overlay=args.overlay,
        required_paths=tuple(args.required_path),
        runtime_setup=tuple(args.runtime_setup),
    )


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in {
        "add",
        "adopt",
        "audit",
        "refresh",
        "metadata",
        "deploy",
    }:
        args = _lifecycle_parser().parse_args(arguments)
        registry_path = args.registry.expanduser().resolve()
        work_root = args.work_root.expanduser().resolve()
        if args.command in {"refresh", "metadata", "deploy"}:
            repository_root = args.repository_root.expanduser().resolve()
            if args.command == "refresh":
                if args.apply:
                    require_review_branch(repository_root)
                return run_updates(
                    registry_path,
                    repository_root,
                    work_root,
                    apply=args.apply,
                    run_setup=False,
                )
            if args.command == "metadata":
                return refresh_metadata(
                    registry_path,
                    repository_root,
                    work_root,
                    apply=args.apply,
                )
            return deploy_skills(
                registry_path,
                repository_root,
                args.codex_home.expanduser().resolve(),
                work_root,
                apply=args.apply,
            )

        codex_home = args.codex_home.expanduser().resolve()
        if args.command == "add":
            add_skill(_lifecycle_spec(args), registry_path, codex_home, work_root, args.replace)
            return 0
        if args.command == "adopt":
            adopt_skill(_lifecycle_spec(args), registry_path, codex_home, work_root)
            return 0
        specs = load_registry(registry_path)
        events = audit_skills(specs, codex_home / "skills")
        for event in events:
            print(f"{event.status.upper()} skill={event.skill} message={event.message}")
        return 1 if args.strict and events else 0

    args = _parser().parse_args(arguments)
    return run_updates(
        registry_path=args.registry.resolve(),
        codex_home=args.codex_home.expanduser().resolve(),
        work_root=args.work_root.resolve(),
        apply=args.apply,
    )


if __name__ == "__main__":
    raise SystemExit(main())
