"""Git-pinned uv tool bundles, separate from native skill directories."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import base64
import configparser
from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import tomllib


NAME = re.compile(r"^[a-z][a-z0-9-]*$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
REQUIREMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*==[A-Za-z0-9.!+_-]+$")


@dataclass(frozen=True)
class GitPackage:
    name: str
    repo: str
    ref: str
    commit: str


@dataclass(frozen=True)
class ToolBundle:
    name: str
    tool: str
    python: str
    used_by: tuple[str, ...]
    packages: tuple[GitPackage, ...]
    requirements: tuple[str, ...]
    executables: tuple[str, ...]
    probe: str

    @property
    def event_name(self) -> str:
        return f"runtime:{self.name}"


def load_bundles(payload: dict) -> list[ToolBundle]:
    records = payload.get("runtime_tools", [])
    if not isinstance(records, list):
        raise ValueError("runtime_tools must be a list")
    skills = {item["name"] for item in payload["skills"]}
    result = []
    names = set()
    commands = set()
    for record in records:
        try:
            bundle = ToolBundle(**(record | {
                "packages": tuple(GitPackage(**item) for item in record["packages"]),
                "used_by": tuple(record["used_by"]),
                "requirements": tuple(record["requirements"]),
                "executables": tuple(record["executables"]),
            }))
        except (KeyError, TypeError) as exc:
            raise ValueError(f"invalid runtime bundle: {exc}") from exc
        if not NAME.fullmatch(bundle.name) or bundle.name in names:
            raise ValueError(f"invalid or duplicate runtime name: {bundle.name}")
        if bundle.python != "3.12" or bundle.probe != "ub-mode":
            raise ValueError(f"unsupported runtime Python/probe: {bundle.name}")
        package_names = [package.name for package in bundle.packages]
        if set(package_names) != {"crapper", "dryer", "mutator"} or len(package_names) != 3:
            raise ValueError(f"ub-mode runtime requires crapper, dryer and mutator: {bundle.name}")
        if bundle.tool != "crapper" or set(bundle.executables) != set(package_names) or len(bundle.executables) != 3:
            raise ValueError(f"invalid runtime primary tool/executables: {bundle.name}")
        if not bundle.used_by or not set(bundle.used_by) <= skills:
            raise ValueError(f"runtime references unknown or empty dependent skills: {bundle.name}")
        if commands.intersection(bundle.executables):
            raise ValueError(f"runtime executable collision: {bundle.name}")
        if not bundle.requirements or not all(REQUIREMENT.fullmatch(item) for item in bundle.requirements):
            raise ValueError(f"runtime requirements must be exact package==version pins: {bundle.name}")
        for package in bundle.packages:
            if not COMMIT.fullmatch(package.commit):
                raise ValueError(f"runtime requires a full Git commit: {package.name}")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", package.ref) or ".." in package.ref:
                raise ValueError(f"invalid runtime tracking ref: {package.ref}")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", package.repo) and not Path(package.repo).is_absolute():
                raise ValueError(f"runtime requires an explicit GitHub repository: {package.name}")
        names.add(bundle.name)
        commands.update(bundle.executables)
        result.append(bundle)
    return result


def bundle_records(bundles: list[ToolBundle]) -> list[dict]:
    return [asdict(bundle) for bundle in bundles]


def refresh_bundle(bundle: ToolBundle, destination: Path, clone_repo) -> ToolBundle:
    """Resolve tracking branches and inspect metadata without executing builds."""
    destination.mkdir(parents=True)
    packages = []
    for package in bundle.packages:
        source = destination / package.name
        commit = clone_repo(package.repo, package.ref, source)
        project = tomllib.loads((source / "pyproject.toml").read_text())["project"]
        if project["name"] != package.name:
            raise ValueError(f"runtime project name: expected={package.name} actual={project['name']}")
        packages.append(replace(package, commit=commit))
    return replace(bundle, packages=tuple(packages))


@dataclass(frozen=True)
class ToolPaths:
    tools: Path
    commands: Path
    state: Path


def _command(args: list[str], *, env=None, timeout=300) -> str:
    process = subprocess.Popen(args, env=env, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=timeout)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    if process.returncode:
        raise RuntimeError(f"runtime command failed ({process.returncode}): {args[0]}: {output[-8000:]}")
    return output


def tool_paths(work_root: Path) -> ToolPaths:
    tools = os.environ.get("UV_TOOL_DIR") or _command(["uv", "tool", "dir"]).strip()
    commands = os.environ.get("UV_TOOL_BIN_DIR") or _command(["uv", "tool", "dir", "--bin"]).strip()
    return ToolPaths(Path(tools).expanduser().absolute(), Path(commands).expanduser().absolute(),
                     work_root / "runtime-tools")


def source_url(package: GitPackage) -> str:
    return Path(package.repo).as_uri() if Path(package.repo).is_absolute() else f"https://github.com/{package.repo}.git"


def desired_profile(bundle: ToolBundle) -> dict:
    return {
        "python": bundle.python,
        "sources": {p.name: {"url": source_url(p), "commit": p.commit} for p in bundle.packages},
        "requirements": {name.lower().replace("_", "-"): version for name, version in
                         (item.split("==") for item in bundle.requirements)},
    }


def _receipt(bundle: ToolBundle, paths: ToolPaths) -> Path:
    return paths.state / f"{bundle.name}.json"


def _pending(bundle: ToolBundle, paths: ToolPaths) -> Path:
    return paths.state / f"{bundle.name}.pending.json"


def _backup(bundle: ToolBundle, paths: ToolPaths) -> Path:
    return paths.state / f".{bundle.name}.rollback"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _check_commands(bundle: ToolBundle, paths: ToolPaths, *, installed: bool) -> None:
    for name in bundle.executables:
        command = paths.commands / name
        expected = paths.tools / bundle.tool / "bin" / name
        if command.is_symlink() and command.resolve() == expected.resolve():
            if installed and (not expected.is_file() or not os.access(expected, os.X_OK)):
                raise ValueError(f"missing or nonexecutable runtime entrypoint: {expected}")
            continue
        if command.exists() or command.is_symlink():
            raise ValueError(f"unmanaged runtime entrypoint: {command}; expected symlink to {expected}")
        if installed:
            raise ValueError(f"missing runtime entrypoint: {command}")


def inspect_bundle(bundle: ToolBundle, paths: ToolPaths, *, pending_ok=False) -> dict | None:
    if _pending(bundle, paths).exists() and not pending_ok:
        raise ValueError(f"interrupted runtime deployment: {_pending(bundle, paths)}; apply is required for recovery")
    env = paths.tools / bundle.tool
    if env.is_symlink():
        raise ValueError(f"unmanaged runtime environment symlink: {env}")
    _check_commands(bundle, paths, installed=env.exists())
    if not env.exists():
        return None
    if not (env / "uv-receipt.toml").is_file():
        raise ValueError(f"unmanaged runtime environment: {env}")
    configuration = configparser.ConfigParser()
    configuration.read_string("[venv]\n" + (env / "pyvenv.cfg").read_text())
    version = configuration["venv"]["version_info"]
    if ".".join(version.split(".")[:2]) != bundle.python:
        raise ValueError(f"runtime Python: expected={bundle.python} actual={version}")
    receipt = tomllib.loads((env / "uv-receipt.toml").read_text())["tool"]
    if {item["name"] for item in receipt["entrypoints"]} != set(bundle.executables):
        raise ValueError(f"runtime entrypoint ownership drift: {env}")
    distributions = list(importlib.metadata.distributions(path=[str(env / f"lib/python{bundle.python}/site-packages")]))
    sources, requirements = {}, {}
    digest = hashlib.sha256()
    seen = set()
    # Verify wheel records before trusting Git provenance or deployment receipts.
    for dist in sorted(distributions, key=lambda item: item.metadata["Name"]):
        name = dist.metadata["Name"].lower().replace("_", "-")
        if name in seen:
            raise ValueError(f"runtime contains duplicate installed distribution: {name}")
        seen.add(name)
        direct = dist.read_text("direct_url.json")
        if direct:
            origin = json.loads(direct)
            sources[name] = {"url": origin["url"], "commit": origin.get("vcs_info", {}).get("commit_id")}
        else:
            requirements[name] = dist.version
        files = dist.files
        if not files:
            raise ValueError(f"runtime integrity: missing package RECORD for {name}")
        for item in sorted(files):
            if item.hash is None:
                continue
            path = dist.locate_file(item)
            if not path.is_file():
                raise ValueError(f"runtime integrity: missing installed file {path}")
            content = path.read_bytes()
            actual = base64.urlsafe_b64encode(hashlib.new(item.hash.mode, content).digest()).decode().rstrip("=")
            if actual != item.hash.value:
                raise ValueError(f"runtime integrity: modified installed file {path}")
    for path in sorted(env.rglob("*")):
        relative = path.relative_to(env)
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            digest.update(f"L:{relative}:{os.readlink(path)}\n".encode())
        elif path.is_file():
            digest.update(f"F:{relative}:".encode() + path.read_bytes())
    observed = {"python": bundle.python, "sources": sources, "requirements": requirements}
    if not distributions:
        raise ValueError(f"runtime environment has no Python {bundle.python} packages: {env}")
    state = {"profile": observed, "integrity": digest.hexdigest()}
    marker = _receipt(bundle, paths)
    if marker.exists():
        previous = json.loads(marker.read_text())
        if previous != state:
            raise ValueError(f"runtime installation drift: {env}; preserve local changes before deployment")
    elif observed != desired_profile(bundle):
        raise ValueError(f"unmanaged runtime profile: {env}; does not match approved source pins/requirements")
    return state


def _environment(paths: ToolPaths) -> dict:
    allowed = {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR"}
    result = {key: value for key, value in os.environ.items() if key in allowed}
    home = paths.state / "home"
    home.mkdir(parents=True, exist_ok=True)
    result.update({"HOME": str(home), "UV_TOOL_DIR": str(paths.tools),
                   "UV_TOOL_BIN_DIR": str(paths.commands), "UV_CACHE_DIR": str(paths.state / "cache"),
                   "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                   "PYTHONDONTWRITEBYTECODE": "1", "UV_PYTHON_DOWNLOADS": "never"})
    return result


def install_bundle(bundle: ToolBundle, paths: ToolPaths) -> None:
    primary = next(package for package in bundle.packages if package.name == bundle.tool)
    args = ["uv", "tool", "install", "--no-config", "--no-python-downloads", "--force",
            "--python", sys.executable]
    for package in bundle.packages:
        if package != primary:
            args += ["--with", f"{package.name} @ git+{source_url(package)}@{package.commit}"]
    for requirement in bundle.requirements:
        args += ["--with", requirement]
    args += ["--with-executables-from", ",".join(name for name in bundle.executables if name != bundle.tool),
             f"{primary.name} @ git+{source_url(primary)}@{primary.commit}"]
    _command(args, env=_environment(paths))


def probe_bundle(bundle: ToolBundle, paths: ToolPaths) -> dict:
    temporary = paths.state / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="probe-", dir=temporary) as directory:
        output = _command([
            str(paths.tools / bundle.tool / "bin/python"), "-B",
            str(Path(__file__).with_name("runtime_probe.py")), "--root", str(Path(directory) / "fixture"),
        ], env=_environment(paths), timeout=180)
    result = json.loads(output)
    if result.get("result") != "PASS":
        raise ValueError(f"runtime probe failed: {bundle.name}: {result}")
    return result


def validate_bundles(bundles: list[ToolBundle], work_root: Path) -> None:
    temporary = work_root / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    for bundle in bundles:
        with tempfile.TemporaryDirectory(prefix="runtime-", dir=temporary) as directory:
            root = Path(directory)
            paths = ToolPaths(root / "tools", root / "bin", root / "state")
            install_bundle(bundle, paths)
            observed = inspect_bundle(bundle, paths)
            if observed["profile"] != desired_profile(bundle):
                raise ValueError(f"staged runtime profile mismatch: {bundle.name}")
            evidence = probe_bundle(bundle, paths)
            print(f"runtime validated: {bundle.name}: {json.dumps(evidence, sort_keys=True)}")


def _prepare_rollback(bundle: ToolBundle, paths: ToolPaths, *, replacing: bool) -> None:
    backup = _backup(bundle, paths)
    if backup.exists():
        raise ValueError(f"orphan runtime backup requires inspection: {backup}")
    env = paths.tools / bundle.tool
    journal = {"tools": str(paths.tools), "commands": str(paths.commands), "phase": "preparing",
               "replacing": replacing, "had_environment": env.exists(),
               "had_state": _receipt(bundle, paths).exists(),
               "links": {name: (paths.commands / name).is_symlink() for name in bundle.executables}}
    _write_json(_pending(bundle, paths), journal)
    backup.mkdir()
    if replacing and env.exists():
        shutil.copytree(env, backup / "environment", symlinks=True)
    if journal["had_state"]:
        shutil.copy2(_receipt(bundle, paths), backup / "state.json")
    _write_json(_pending(bundle, paths), journal | {"phase": "prepared"})


def _finish(bundle: ToolBundle, paths: ToolPaths) -> None:
    journal = _pending(bundle, paths)
    _write_json(journal, json.loads(journal.read_text()) | {"phase": "committed"})
    shutil.rmtree(_backup(bundle, paths))
    journal.unlink()


def recover_bundle(bundle: ToolBundle, paths: ToolPaths) -> None:
    journal_path = _pending(bundle, paths)
    if not journal_path.exists():
        return
    journal = json.loads(journal_path.read_text())
    if (journal["tools"], journal["commands"]) != (str(paths.tools), str(paths.commands)):
        raise ValueError(f"runtime recovery paths differ: {journal_path}")
    if journal["phase"] not in {"preparing", "prepared", "committed"}:
        raise ValueError(f"unknown runtime recovery phase: {journal_path}")
    if set(journal["links"]) != set(bundle.executables) or not all(isinstance(value, bool) for value in journal["links"].values()):
        raise ValueError(f"invalid runtime recovery entrypoints: {journal_path}")
    if not all(isinstance(journal[key], bool) for key in ("replacing", "had_environment", "had_state")):
        raise ValueError(f"invalid runtime recovery flags: {journal_path}")
    if journal["phase"] == "prepared":
        backup = _backup(bundle, paths)
        if journal["replacing"] and journal["had_environment"] and not (backup / "environment").is_dir():
            raise ValueError(f"runtime recovery backup missing: {backup / 'environment'}")
        if journal["had_state"] and not (backup / "state.json").is_file():
            raise ValueError(f"runtime recovery state backup missing: {backup / 'state.json'}")
        env = paths.tools / bundle.tool
        _check_commands(bundle, paths, installed=False)
        if journal["replacing"]:
            if env.exists():
                shutil.rmtree(env)
            if journal["had_environment"]:
                shutil.copytree(_backup(bundle, paths) / "environment", env, symlinks=True)
        for name, existed in journal["links"].items():
            link = paths.commands / name
            if link.is_symlink():
                link.unlink()
            if existed:
                link.symlink_to(env / "bin" / name)
        if journal["had_state"]:
            shutil.copy2(_backup(bundle, paths) / "state.json", _receipt(bundle, paths))
        else:
            _receipt(bundle, paths).unlink(missing_ok=True)
    if _backup(bundle, paths).exists():
        shutil.rmtree(_backup(bundle, paths))
    journal_path.unlink()


@contextmanager
def deploy_bundles(bundles: list[ToolBundle], paths: ToolPaths):
    changed = []
    try:
        for bundle in bundles:
            recover_bundle(bundle, paths)
            observed = inspect_bundle(bundle, paths)
            replacing = observed is None or observed["profile"] != desired_profile(bundle)
            if replacing or not _receipt(bundle, paths).exists():
                changed.append(bundle)
                _prepare_rollback(bundle, paths, replacing=replacing)
            if replacing:
                install_bundle(bundle, paths)
                # The old receipt describes the old environment until commit.
                previous = _receipt(bundle, paths)
                previous.unlink(missing_ok=True)
                observed = inspect_bundle(bundle, paths, pending_ok=True)
            evidence = probe_bundle(bundle, paths)
            if bundle in changed:
                _write_json(_receipt(bundle, paths), observed)
            print(f"runtime ready: {bundle.name}: {json.dumps(evidence, sort_keys=True)}")
        yield
    except BaseException:
        for bundle in reversed(changed):
            recover_bundle(bundle, paths)
        raise
    else:
        for bundle in changed:
            _finish(bundle, paths)
