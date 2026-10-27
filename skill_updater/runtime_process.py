"""Owned runtime commands and a parent-death-safe filesystem writer barrier."""

import argparse
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


@dataclass(frozen=True)
class CommandLease:
    lock: Path
    gate: Path
    token: str


_LEASE: ContextVar[CommandLease | None] = ContextVar("runtime_command_lease", default=None)


@contextmanager
def owned_commands(lease: CommandLease):
    token = _LEASE.set(lease)
    try:
        yield
    finally:
        _LEASE.reset(token)


@contextmanager
def writer_lock(path: Path, timeout=305):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"runtime writer still active: {path}; recovery was not performed")
                time.sleep(0.05)
        # Closing keeps the lock alive in inherited child descriptors; an
        # explicit LOCK_UN would release their lease before they have exited.
        yield handle


def run(args: list[str], *, env=None, timeout=300) -> str:
    lease = _LEASE.get()
    if lease is not None:
        args = [sys.executable, "-B", str(Path(__file__).resolve()),
                "--writer-lock", str(lease.lock), "--gate", str(lease.gate),
                "--token", lease.token, "--timeout", str(timeout), "--", *args]
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--writer-lock", type=Path, required=True)
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    command = options.command[1:] if options.command[:1] == ["--"] else options.command
    if not command or options.timeout <= 0 or os.getsid(0) != os.getpid():
        raise ValueError("runtime worker requires a command, positive timeout and its own session")
    with writer_lock(options.writer_lock, timeout=options.timeout) as handle:
        # Recovery and command startup share this barrier. An old queued command
        # cannot start after recovery has removed or replaced its transaction.
        gate = json.loads(options.gate.read_text())
        if gate.get("token") != options.token or gate.get("phase") != "prepared":
            raise ValueError("obsolete runtime command lease; command was not started")
        process = subprocess.Popen(command, pass_fds=(handle.fileno(),))
        try:
            code = process.wait(timeout=options.timeout)
        except BaseException:
            os.killpg(os.getpgrp(), signal.SIGKILL)
            raise
        raise SystemExit(code if code >= 0 else 128 - code)


if __name__ == "__main__":
    main()
