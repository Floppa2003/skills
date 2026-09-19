# Playwright CLI Workflows

Use the wrapper script and snapshot often.
Assume `PWCLI` is set and `pwcli` is an alias for `"$PWCLI"`.
In this repo, run commands from `output/playwright/<label>/` to keep artifacts contained.
Initialize the named session below before using these interaction snippets; they
are fragments of one workflow, not separate browser lifetimes. Run `open` only
when starting the owned session, and use `goto` for subsequent URLs. Entrypoint
examples beginning with `open` are alternative first-open examples: if a session
is already open for this task, replace that command with `goto`.

## Standard interaction loop

```bash
pwcli goto https://example.com
pwcli snapshot
pwcli click e3
pwcli snapshot
```

## Form submission

```bash
pwcli goto https://example.com/form
pwcli snapshot
pwcli fill e1 "user@example.com"
pwcli fill e2 "password123"
pwcli click e3
pwcli snapshot
pwcli screenshot
```

## Data extraction

```bash
pwcli goto https://example.com
pwcli snapshot
pwcli eval "document.title"
pwcli eval "el => el.textContent" e12
```

## Debugging and inspection

Capture console messages and network activity after reproducing an issue:

```bash
pwcli console warning
pwcli network
```

Record a trace around a suspicious flow:

```bash
pwcli tracing-start
# reproduce the issue
pwcli tracing-stop
pwcli screenshot
```

## Sessions and lifecycle

Use one named session per task; add another only when browser-state isolation is
required. Choose an unused name, not the shared `default`, and record the task,
session name, working directory, intended lifetime, and daemon/browser PID and
start time and profile path when available. Before opening, inspect session
metadata read-only using the installed CLI's registry layout; do not read cookies
or storage contents. A matching name is not proof of ownership: choose another
if it belongs to someone else. If ownership or name availability cannot be checked
safely, report the blocker. `open` with an existing name stops the previous session.

Do not use `list` for ownership-safe discovery or verification: it probes other
sessions and can remove unreachable sessions' metadata and sockets.

```bash
export PLAYWRIGHT_CLI_SESSION="<task-unique-name>"
pwcli open https://example.com
pwcli snapshot
pwcli goto https://example.com/checkout
```

Keep that name and working directory across CLI calls; pass
`--session "<task-unique-name>"` explicitly if the environment is not preserved.
Re-snapshot after navigation. A completed wrapper command does not end the
browser session. Do not add per-command auto-close to the wrapper.

### Finish the workflow

On success, failure, cancellation, or timeout:

1. Finalize task-started traces/recordings and save required artifacts before
   closing. Attempt cleanup even if capture failed; report both failures.
2. Gracefully close only sessions created and owned by this task, from the same
   working directory and with their recorded names. Recheck the current metadata
   and process identity against the ownership record before closing:

```bash
pwcli --session "<task-unique-name>" close
```

3. Inspect only this session's metadata read-only and confirm its recorded
   daemon/browser processes have exited. A zero exit code or absent registry entry alone does
   not prove cleanup. Check recorded process identity, including start time
   before any further action, to avoid confusing a reused PID with task state.
   Preserve retained artifacts and persistent profiles; remove only verified
   task-owned disposable leftovers after their processes exit.

If cleanup fails or ownership cannot be established, report the exact session,
PID/path, and blocker. Never substitute `close-all`, `kill-all`, blanket process
kills, or deletion of unknown profiles. Headless mode, a temporary-profile name,
or `PPID=1` does not establish ownership or abandonment.

When attachment to an existing user/shared browser is authorized, preserve that
browser and its prior tabs/profile. Release only the task-owned connection using
the attachment mode's supported detach mechanism; do not apply the owned-browser
`close` recipe. For an intentionally retained interactive deliverable, report its
session handle and purpose instead of closing it. In a custom Playwright program,
put owned context/browser cleanup in `finally` and handle cancellation at the
whole-workflow boundary, not after each interaction.

## Configuration file

By default, the CLI reads `playwright-cli.json` from the current directory. Use `--config` to point at a specific file.

Minimal example:

```json
{
  "browser": {
    "launchOptions": {
      "headless": false
    },
    "contextOptions": {
      "viewport": { "width": 1280, "height": 720 }
    }
  }
}
```

## Troubleshooting

- If an element ref fails, run `pwcli snapshot` again and retry.
- If a visible browser is needed, choose `--headed` at the first `open`. To change
  mode on an existing owned session, finalize captures, close and verify it using
  the lifecycle above, then deliberately restart with `--headed`; transient state
  may be lost. Never reopen a user/shared session as troubleshooting.
- If a flow depends on prior state, use a named `--session`.
