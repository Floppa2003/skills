#!/bin/bash
set -euo pipefail

LABEL="io.github.floppa2003.codex-skill-updater"
UPDATER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPOSITORY_ROOT="$(cd "$UPDATER_ROOT/.." && pwd -P)"
STATE_ROOT="${CODEX_HOME:-$HOME/.codex}/skill-updater-state"
LOG_ROOT="$STATE_ROOT/logs"
SOURCE="$UPDATER_ROOT/launchd/$LABEL.plist.in"
DESTINATION="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$UID"
SERVICE="$DOMAIN/$LABEL"

render_agent() {
    mkdir -p "$HOME/Library/LaunchAgents" "$LOG_ROOT"
    plutil -lint "$SOURCE"
    cp "$SOURCE" "$DESTINATION"
    plutil -remove ProgramArguments.1 "$DESTINATION"
    plutil -insert ProgramArguments.1 -string "$UPDATER_ROOT/sync_and_deploy.sh" "$DESTINATION"
    plutil -replace WorkingDirectory -string "$REPOSITORY_ROOT" "$DESTINATION"
    plutil -replace StandardOutPath -string "$LOG_ROOT/launchd.stdout.log" "$DESTINATION"
    plutil -replace StandardErrorPath -string "$LOG_ROOT/launchd.stderr.log" "$DESTINATION"
    plutil -lint "$DESTINATION"
}

install_agent() {
    render_agent
    if launchctl print "$SERVICE" >/dev/null 2>&1; then
        launchctl bootout "$SERVICE"
    fi
    launchctl bootstrap "$DOMAIN" "$DESTINATION"
    launchctl enable "$SERVICE"
    launchctl print "$SERVICE"
}

uninstall_agent() {
    if launchctl print "$SERVICE" >/dev/null 2>&1; then
        launchctl bootout "$SERVICE"
    fi
    rm -f "$DESTINATION"
}

case "${1:-install}" in
    install) install_agent ;;
    render) render_agent ;;
    status) launchctl print "$SERVICE" ;;
    uninstall) uninstall_agent ;;
    *) echo "usage: $0 [install|render|status|uninstall]" >&2; exit 64 ;;
esac
