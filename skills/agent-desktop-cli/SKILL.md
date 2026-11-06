---
name: agent-desktop-cli
description: Use for desktop GUI tasks explicitly using agent-desktop, running from a terminal or custom harness, or lacking native Computer Use. Prefer native Computer Use when available; not for browser DOM or API extraction.
---

# Agent Desktop CLI

Use the installed `agent-desktop` CLI. This router does not replace native
Computer Use or provide a browser DOM/API connection.

Before the first desktop operation, run `agent-desktop version`,
`agent-desktop status`, `agent-desktop skills get desktop`, and
`agent-desktop skills get platform`. Read `data.content` in the successful JSON
guide responses and follow those version-matched instructions.

Load linked references only when needed with
`agent-desktop skills get desktop <reference>` or
`agent-desktop skills get platform <reference>`. These are binary-owned guides,
not paths relative to this skill. Use `agent-desktop <command> --help` for flags.

If the CLI is missing or a required permission is denied, report the specific
prerequisite. Ask before installing/upgrading software, changing OS permissions,
or enabling another integration. A permission grant does not authorize the
task's external, destructive, or sensitive actions.

Source and runtime: [vercel-labs/agent-desktop](https://github.com/vercel-labs/agent-desktop).
This is a locally authored router; detailed upstream guidance stays in the CLI.
