#!/usr/bin/env bash
# Prints the analysis prompt so SKILL.md can inline it at load time. A script
# rather than a bare cat: Claude Code refuses a cat of any file outside the
# session's working directory in a skill's inline commands (measured on
# 2.1.222), and that refusal aborts the whole skill. A script in the skill's
# own folder is the documented way to bring a file in, and it is not refused.
cat "$(cd "$(dirname "$0")/.." && pwd)/references/premortem-prompt.md"
