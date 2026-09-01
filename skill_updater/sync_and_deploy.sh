#!/bin/bash
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$REPOSITORY_ROOT/.venv/bin/python"
STATE_ROOT="${CODEX_HOME:-$HOME/.codex}/skill-updater-state"
TEMPORARY_PARENT="$(mktemp -d "${TMPDIR:-/tmp}/codex-skills-deploy.XXXXXX")"
TEMPORARY_ROOT="$TEMPORARY_PARENT/worktree"
TEMPORARY_VENV=""

cleanup() {
    if [[ -n "$TEMPORARY_VENV" ]]; then
        rm -rf "$TEMPORARY_VENV"
    fi
    git -C "$REPOSITORY_ROOT" worktree remove --force "$TEMPORARY_ROOT" >/dev/null 2>&1 || true
    rm -rf "$TEMPORARY_PARENT"
}
trap cleanup EXIT

install_requirements() {
    "$1" -m pip install \
        --disable-pip-version-check \
        --require-hashes \
        -r "$TEMPORARY_ROOT/scripts/requirements-chatgpt.txt"
}

is_python312() {
    [[ -x "$1" ]] && "$1" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))'
}

resolve_python312() {
    local candidate
    local resolved

    if [[ -n "${PYTHON312:-}" ]]; then
        if is_python312 "$PYTHON312"; then
            printf '%s\n' "$PYTHON312"
            return
        fi
        echo "PYTHON312 must point to an executable Python 3.12 interpreter" >&2
        return 1
    fi

    for candidate in /opt/homebrew/bin/python3.12 python3.12 python3; do
        resolved="$(command -v "$candidate" 2>/dev/null || true)"
        if [[ -n "$resolved" ]] && is_python312 "$resolved"; then
            printf '%s\n' "$resolved"
            return
        fi
    done

    echo "Python 3.12 is required; install python3.12 or set PYTHON312" >&2
    return 1
}

mkdir -p "$STATE_ROOT"
git -C "$REPOSITORY_ROOT" fetch --quiet origin main
git -C "$REPOSITORY_ROOT" worktree add --quiet --detach "$TEMPORARY_ROOT" origin/main
if [[ ! -x "$VENV_PYTHON" ]] || ! "$VENV_PYTHON" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))'; then
    BOOTSTRAP_PYTHON="$(resolve_python312)"
    TEMPORARY_VENV="$REPOSITORY_ROOT/.venv.build.$$"
    rm -rf "$TEMPORARY_VENV"
    "$BOOTSTRAP_PYTHON" -m venv "$TEMPORARY_VENV"
    install_requirements "$TEMPORARY_VENV/bin/python"
    rm -rf "$REPOSITORY_ROOT/.venv"
    mv "$TEMPORARY_VENV" "$REPOSITORY_ROOT/.venv"
    TEMPORARY_VENV=""
else
    install_requirements "$VENV_PYTHON"
fi

"$VENV_PYTHON" "$TEMPORARY_ROOT/skill_updater/update_skills.py" deploy \
    --apply \
    --repository-root "$TEMPORARY_ROOT" \
    --registry "$TEMPORARY_ROOT/skill_updater/registry.json" \
    --codex-home "${CODEX_HOME:-$HOME/.codex}" \
    --work-root "$STATE_ROOT"
"$VENV_PYTHON" "$TEMPORARY_ROOT/skill_updater/update_skills.py" audit \
    --strict \
    --registry "$TEMPORARY_ROOT/skill_updater/registry.json" \
    --codex-home "${CODEX_HOME:-$HOME/.codex}" \
    --work-root "$STATE_ROOT"
