"""Pinned Agent Desktop releases, using the existing installation journal."""

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import tarfile
import tempfile
import time
from urllib.request import urlopen

try:
    from skill_updater.runtime_tools import (
        ToolPaths, _check_commands, _finish, _pending, _prepare_rollback, _receipt,
        _write_json, recover_bundle,
    )
    from skill_updater.runtime_process import owned_commands, run as _command
except ModuleNotFoundError:
    from runtime_tools import (
        ToolPaths, _check_commands, _finish, _pending, _prepare_rollback, _receipt,
        _write_json, recover_bundle,
    )
    from runtime_process import owned_commands, run as _command


TARGETS = {
    ("Darwin", "arm64"): "aarch64-apple-darwin",
    ("Darwin", "x86_64"): "x86_64-apple-darwin",
    ("Linux", "aarch64"): "aarch64-unknown-linux-gnu",
    ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
}
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_UNPACKED_BYTES = 128 * 1024 * 1024


def host_target() -> str:
    identity = (platform.system(), platform.machine().lower())
    try:
        return TARGETS[identity]
    except KeyError as exc:
        raise ValueError(f"unsupported native release host: {identity}") from exc


def files_for(target: str) -> tuple[str, ...]:
    helper = "agent-desktop-macos-helper" if target.endswith("apple-darwin") else "agent-desktop-linux-clipboard-owner"
    return "agent-desktop", helper


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ReleaseTool:
    name: str
    repo: str
    tag: str
    source_commit: str
    used_by: tuple[str, ...]
    assets: dict[str, ReleaseAsset]

    @property
    def tool(self) -> str:
        return self.name

    @property
    def executables(self) -> tuple[str, ...]:
        return files_for(host_target())

    @property
    def event_name(self) -> str:
        return f"runtime:{self.name}"


def load_releases(payload: dict) -> list[ReleaseTool]:
    records = payload.get("release_tools", [])
    if not isinstance(records, list):
        raise ValueError("release_tools must be a list")
    skills = {item["name"] for item in payload["skills"]}
    names = {item["name"] for item in payload.get("runtime_tools", [])}
    result = []
    for record in records:
        try:
            tool = ReleaseTool(**(record | {
                "used_by": tuple(record["used_by"]),
                "assets": {target: ReleaseAsset(**asset) for target, asset in record["assets"].items()},
            }))
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f"invalid native release record: {exc}") from exc
        if tool.name != "agent-desktop" or tool.repo != "vercel-labs/agent-desktop" or tool.name in names:
            raise ValueError(f"unsupported or duplicate native release: {tool.name}/{tool.repo}")
        if not TAG.fullmatch(tool.tag) or not COMMIT.fullmatch(tool.source_commit):
            raise ValueError(f"native release requires a stable tag and full source commit: {tool.name}")
        if not tool.used_by or not set(tool.used_by) <= skills:
            raise ValueError(f"native release references unknown dependent skills: {tool.name}")
        if not tool.assets or not tool.assets.keys() <= set(TARGETS.values()):
            raise ValueError(f"native release assets have unsupported or empty targets: {tool.name}")
        for target, asset in tool.assets.items():
            expected = f"agent-desktop-{tool.tag}-{target}.tar.gz"
            if (asset.name != expected or not SHA256.fullmatch(asset.sha256)
                    or type(asset.size) is not int or not 0 < asset.size <= MAX_ARCHIVE_BYTES):
                raise ValueError(f"invalid native release asset: expected={expected} actual={asset}")
        names.add(tool.name)
        result.append(tool)
    return result


def release_records(tools: list[ReleaseTool]) -> list[dict]:
    return [asdict(tool) for tool in tools]


def github_json(endpoint: str) -> dict:
    return json.loads(_command(["gh", "api", endpoint], timeout=60))


def refresh_release(tool: ReleaseTool) -> ReleaseTool:
    release = github_json(f"repos/{tool.repo}/releases/latest")
    tag = release["tag_name"]
    if release["draft"] or release["prerelease"] or not TAG.fullmatch(tag):
        raise ValueError(f"native release is not a stable published version: {tag}")
    records = {asset["name"]: asset for asset in release["assets"]}
    assets = {}
    for target in tool.assets:
        name = f"agent-desktop-{tag}-{target}.tar.gz"
        asset = records[name]
        digest = asset["digest"]
        if not digest.startswith("sha256:"):
            raise ValueError(f"native release is missing a SHA-256 digest: {name}")
        assets[target] = ReleaseAsset(name, asset["size"], digest.removeprefix("sha256:"))
    commit = github_json(f"repos/{tool.repo}/commits/{tag}")["sha"]
    proposal = replace(tool, tag=tag, source_commit=commit, assets=assets)
    load_releases({"skills": [{"name": name} for name in tool.used_by],
                   "release_tools": release_records([proposal])})
    if tag == tool.tag and proposal != tool:
        raise ValueError(f"immutable native release changed: {tool.name} {tag}; prior pins preserved")
    if tuple(map(int, TAG.fullmatch(tag).groups())) < tuple(map(int, TAG.fullmatch(tool.tag).groups())):
        raise ValueError(f"native release downgrade refused: {tool.tag} -> {tag}")
    return proposal


def release_paths(work_root: Path) -> ToolPaths:
    tools = Path(os.environ.get("SKILL_NATIVE_TOOL_DIR", os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))))
    commands = Path(os.environ.get("SKILL_NATIVE_BIN_DIR", str(Path.home() / ".local/bin")))
    return ToolPaths(tools.expanduser().absolute(), commands.expanduser().absolute(), work_root / "release-tools")


def desired_release(tool: ReleaseTool) -> dict:
    asset = tool.assets[host_target()]
    return {"repository": tool.repo, "tag": tool.tag, "source_commit": tool.source_commit,
            "asset": asset.name, "archive_sha256": asset.sha256}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def installed_state(tool: ReleaseTool, root: Path) -> dict:
    expected_files = {f"bin/{name}" for name in tool.executables}
    allowed = expected_files | {"installation.json", "bin"}
    for path in root.rglob("*"):
        if path.is_symlink() or str(path.relative_to(root)) not in allowed:
            raise ValueError(f"native installation drift: unexpected file {path}")
    manifest = json.loads((root / "installation.json").read_text())
    if set(manifest["files"]) != expected_files:
        raise ValueError(f"native installation manifest file set differs: {root}")
    files = {name: file_hash(root / name) for name in sorted(expected_files)}
    if files != manifest["files"]:
        raise ValueError(f"native installation integrity: modified files in {root}")
    profile = {key: manifest[key] for key in desired_release(tool)}
    return {"profile": profile, "files": files, "manifest_sha256": file_hash(root / "installation.json"),
            "modes": {name: (root / name).stat().st_mode & 0o777 for name in files}}


def inspect_release(tool: ReleaseTool, paths: ToolPaths, *, pending_ok=False, adoption_files=None) -> dict | None:
    if _pending(tool, paths).exists() and not pending_ok:
        raise ValueError(f"interrupted native deployment: {_pending(tool, paths)}; approved apply required")
    root = paths.tools / tool.tool
    if root.is_symlink():
        raise ValueError(f"unmanaged native environment symlink: {root}")
    _check_commands(tool, paths, installed=root.exists())
    if not root.exists():
        return None
    state = installed_state(tool, root)
    marker = _receipt(tool, paths)
    if marker.exists():
        if json.loads(marker.read_text()) != state:
            raise ValueError(f"native installation drift: {root}; preserve local changes")
    elif adoption_files is None:
        raise ValueError(f"unmanaged native installation: {root}; approved apply must verify its archive")
    elif state["files"] != adoption_files or state["profile"] != desired_release(tool):
        raise ValueError(f"native installation differs from verified archive: {root}")
    with tempfile.TemporaryDirectory(prefix="native-inspect-") as directory:
        verify_version(root / "bin/agent-desktop", state["profile"]["tag"].removeprefix("v"),
                       command_environment(Path(directory)))
    if installed_state(tool, root) != state:
        raise ValueError(f"native version probe modified its installation: {root}")
    return state


def download_asset(tool: ReleaseTool, destination: Path) -> None:
    asset = tool.assets[host_target()]
    url = f"https://github.com/{tool.repo}/releases/download/{tool.tag}/{asset.name}"
    total = 0
    deadline = time.monotonic() + 120
    with urlopen(url, timeout=30) as response, destination.open("xb") as output:
        while chunk := response.read1(1024 * 1024):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"native asset download deadline exceeded: {asset.name}")
            total += len(chunk)
            if total > asset.size:
                raise ValueError(f"native asset exceeds approved size: {asset.name}")
            output.write(chunk)
    if total != asset.size:
        raise ValueError(f"native asset size: expected={asset.size} actual={total}")


def verify_attestation(tool: ReleaseTool, archive: Path) -> None:
    results = json.loads(_command(["gh", "attestation", "verify", str(archive), "--repo", tool.repo,
                                   "--format", "json"], timeout=120))
    asset = tool.assets[host_target()]
    for result in results:
        verified = result["verificationResult"]
        certificate = verified["signature"]["certificate"]
        subjects = verified["statement"]["subject"]
        if (certificate["sourceRepositoryURI"] == f"https://github.com/{tool.repo}"
                and certificate["sourceRepositoryDigest"] == tool.source_commit
                and certificate["githubWorkflowRepository"] == tool.repo
                and any(item["name"] == asset.name and item["digest"].get("sha256") == asset.sha256 for item in subjects)):
            return
    raise ValueError(f"native build attestation/source mismatch: {tool.name} {tool.tag}")


def prepare_release(tool: ReleaseTool, destination: Path) -> Path:
    asset = tool.assets[host_target()]
    destination.mkdir(parents=True)
    archive = destination / ".download.tar.gz"
    download_asset(tool, archive)
    if archive.stat().st_size != asset.size or file_hash(archive) != asset.sha256:
        raise ValueError(f"native archive digest/size mismatch: {asset.name}")
    verify_attestation(tool, archive)
    expected = set(tool.executables)
    seen, total = set(), 0
    (destination / "bin").mkdir()
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            if member.name not in expected or member.name in seen or not member.isfile():
                raise ValueError(f"unsafe native archive member: {member.name}")
            total += member.size
            if total > MAX_UNPACKED_BYTES or member.size <= 0:
                raise ValueError("native archive exceeds unpacked size contract")
            content = source.extractfile(member)
            with (destination / "bin" / member.name).open("xb") as output:
                shutil.copyfileobj(content, output)
            (destination / "bin" / member.name).chmod(0o755)
            seen.add(member.name)
    if seen != expected:
        raise ValueError(f"native archive members: expected={expected} actual={seen}")
    archive.unlink()
    manifest = {"schema_version": 1, "version": tool.tag.removeprefix("v"), **desired_release(tool),
                "verified_attestation": {"repository": tool.repo, "source_commit": tool.source_commit},
                "files": {f"bin/{name}": file_hash(destination / "bin" / name) for name in sorted(expected)}}
    _write_json(destination / "installation.json", manifest)
    return destination


def command_environment(private_root: Path) -> dict:
    environment = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL", "LC_CTYPE"}}
    home = private_root / "home"
    home.mkdir(parents=True, exist_ok=True)
    environment.update({"HOME": str(home), "AGENT_DESKTOP_HOME": str(private_root / "desktop-state")})
    return environment


def verify_version(binary: Path, expected: str, environment: dict) -> None:
    try:
        version = json.loads(_command([str(binary), "version"], env=environment, timeout=30))
    except (OSError, RuntimeError, TimeoutError) as exc:
        raise ValueError(f"native CLI cannot start: {binary}: {exc}") from exc
    target = host_target()
    expected_os = "macos" if target.endswith("apple-darwin") else "linux"
    data = version["data"]
    if (not version["ok"] or data["version"] != expected or data["os"] != expected_os
            or data["target"] != target.split("-")[0]):
        raise ValueError(f"native version/platform: expected={expected}/{target} actual={version}")


def probe_release(tool: ReleaseTool, root: Path, private_root: Path) -> dict:
    environment = command_environment(private_root)
    binary = str(root / "bin/agent-desktop")
    expected_version = tool.tag.removeprefix("v")
    verify_version(Path(binary), expected_version, environment)
    guides = []
    for guide in ("desktop", "platform"):
        result = json.loads(_command([binary, "skills", "get", guide, "--full"], env=environment, timeout=30))
        expected_skill = "agent-desktop" if guide == "desktop" else "agent-desktop-" + ("macos" if platform.system() == "Darwin" else "linux")
        if (not result["ok"] or result["data"]["skill"] != expected_skill
                or not result["data"]["full"] or not result["data"]["content"].strip()):
            raise ValueError(f"native guide missing: {guide}")
        if re.search(r"~/.claude|\.claude|anthropic|claude[_ -]code|claude-only", result["data"]["content"], re.I):
            raise ValueError(f"native guide requires provider-compatibility review: {guide}")
        guides.append(result["data"]["skill"])
    return {"result": "PASS", "version": expected_version, "guides": guides}


@contextmanager
def deploy_releases(tools: list[ReleaseTool], paths: ToolPaths):
    changed, evidence = [], {}
    try:
        for tool in tools:
            recover_bundle(tool, paths)
            root = paths.tools / tool.tool
            _check_commands(tool, paths, installed=root.exists())
            temporary = paths.state / "tmp"
            temporary.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=f"{tool.name}-", dir=temporary) as directory:
                work = Path(directory)
                candidate = None
                if root.exists() and not _receipt(tool, paths).exists():
                    candidate = prepare_release(tool, work / "candidate")
                    hashes = json.loads((candidate / "installation.json").read_text())["files"]
                    observed = inspect_release(tool, paths, adoption_files=hashes)
                else:
                    observed = inspect_release(tool, paths)
                replacing = observed is None or observed["profile"] != desired_release(tool)
                if replacing and candidate is None:
                    candidate = prepare_release(tool, work / "candidate")
                changed.append(tool)
                lease = _prepare_rollback(tool, paths, replacing=replacing)
                with owned_commands(lease):
                    if replacing:
                        if root.exists():
                            shutil.rmtree(root)
                        shutil.copytree(candidate, root)
                        paths.commands.mkdir(parents=True, exist_ok=True)
                        for name in tool.executables:
                            link = paths.commands / name
                            if link.is_symlink():
                                link.unlink()
                            link.symlink_to(root / "bin" / name)
                        _receipt(tool, paths).unlink(missing_ok=True)
                        hashes = json.loads((root / "installation.json").read_text())["files"]
                        observed = inspect_release(tool, paths, pending_ok=True, adoption_files=hashes)
                    evidence[tool.name] = probe_release(tool, root, work)
                    observed = inspect_release(tool, paths, pending_ok=True, adoption_files=observed["files"])
                    _write_json(_receipt(tool, paths), observed)
                print(f"native ready: {tool.name}: {json.dumps(evidence[tool.name], sort_keys=True)}")
        yield evidence
    except BaseException:
        for tool in reversed(changed):
            recover_bundle(tool, paths)
        raise
    else:
        for tool in changed:
            _finish(tool, paths)


def validate_releases(tools: list[ReleaseTool], work_root: Path) -> None:
    temporary = work_root / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    for tool in tools:
        with tempfile.TemporaryDirectory(prefix="native-", dir=temporary) as directory:
            root = Path(directory)
            with deploy_releases([tool], ToolPaths(root / "tools", root / "bin", root / "state")):
                pass
