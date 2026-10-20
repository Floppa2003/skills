
# Reference

When the examples below mention `scripts/task_loop.py`, that path is relative to this skill root. Run it while your shell working directory is inside the target repository.

This skill is designed to be portable, but the repository-local artifacts and subagent files it creates must stay in the target repository.

## Recommended install locations

### Codex

Project skill:
- `.agents/skills/repo-task-proof-loop/`

Personal skill:
- `$HOME/.agents/skills/repo-task-proof-loop/`

Follow the host's managed installation procedure when present. The initializer
writes task artifacts into the target repository, not into the skill directory.

## Repo files created by `init`

```text
.agent/tasks/TASK_ID/
  spec.md
  evidence.md
  evidence.json
  raw/
    build.txt
    test-unit.txt
    test-integration.txt
    lint.txt
    screenshot-1.png
  verdict.json
  problems.md
```

Only with explicit project-configuration approval and `--install-subagents codex`,
the initializer installs these files. Existing differing files cause an error:

```text
.codex/agents/
  task-spec-freezer.toml
  task-builder.toml
  task-verifier.toml
  task-fixer.toml
```

Only with explicit approval and `--guides agents` (or its `auto` alias), it inserts a managed workflow block into:

- repo-root `AGENTS.md`
The managed block is replaced in place on re-run; content outside the markers is preserved.
For Codex, the managed block always lives in repo-root `AGENTS.md`. That file acts as the repo-wide baseline. More-specific nested `AGENTS.override.md`, `AGENTS.md`, or configured fallback filenames still take precedence in their directory trees, and the initializer does not rewrite them.
If `init` creates or rewrites `AGENTS.md` during a running Codex session, start a new Codex session before relying on the updated instructions.
Both integration options default to `none`; task initialization does not require either.

## Commands

### Initialize workflow files

```bash
scripts/task_loop.py init --task-id my-task
```

Project instruction or role installation is a separate opt-in, not part of default initialization.

Seed the task from a task file:

```bash
scripts/task_loop.py init --task-id my-task --task-file docs/task.md
```

Seed the task from inline text:

```bash
scripts/task_loop.py init --task-id my-task --task-text "Implement feature X"
```

Control which guide files are created or updated:

```bash
scripts/task_loop.py init --task-id my-task --guides auto
scripts/task_loop.py init --task-id my-task --guides agents
scripts/task_loop.py init --task-id my-task --guides none
```

`--guides auto` is an explicit opt-in equivalent to `--guides agents`.

Control which project subagent sets are installed:

```bash
scripts/task_loop.py init --task-id my-task --install-subagents codex
scripts/task_loop.py init --task-id my-task --install-subagents none
```

### Validate the artifact set

```bash
scripts/task_loop.py validate --task-id my-task
```

Run `validate` only after `init` has finished. If it reports initialization in progress, wait and rerun instead of treating that output as the durable workflow state.

### Summarize current status

```bash
scripts/task_loop.py status --task-id my-task
```

Run `status` only after `init` has finished when you need stable task state. If it returns `init_in_progress: true`, treat that as a retry-later signal.

## Expected working pattern

1. Initialize the task folder
2. Freeze the spec
3. Implement
4. Pack evidence
5. Independently verify with one read-only child started with `fork_context=false`
6. Fix if needed
7. Ask the same verifier to recheck; stop at acceptance, a blocker, or the agreed limit

Codex adaptive orchestration:

- Keep normal Codex usage auto-mode-first and serial by default. Users do not need child-management details unless they explicitly want delegated or parallel agent work.
- Follow the active review and delegation policy; optional helper fan-out requires authorization and independently useful scopes.
- Once delegation is authorized, the parent may fan out bounded built-in `explorer` or `worker` children in parallel when a large Codex task has independent research questions, disjoint write scopes, or several read-only proof probes.
- Keep helper fan-out modest and wave-based. Prefer up to 3 parallel helper children at once, then wait before the next phase.
- Keep the task tree shallow. The parent session should orchestrate children directly instead of asking one custom task child to spawn more children.
- One integration builder still owns `evidence.md` and `evidence.json`.
- One independent verifier judges the task; the lead persists its report in `verdict.json` and `problems.md`.

For exact prompts to use with child agents, see `references/COMMANDS.md`.

## Notes

- The initializer does not write the final `spec.md` content for you. It creates the strict file structure and seeds the task statement when provided. The actual spec freeze is an agent step.
- `evidence.json` and `verdict.json` are created with valid placeholder content so validation can run immediately after `init`.
- `raw/screenshot-1.png` is created as a tiny placeholder PNG so the required path exists from the start.
- Guidance discovery for seeded task specs includes repo-visible `AGENTS.override.md` and `AGENTS.md` along the path to the working directory.
- That seeded guidance list is a workflow artifact, not a literal dump of Codex's automatic project-doc context.
- Codex can also load extra fallback filenames configured via `project_doc_fallback_filenames`. The initializer does not try to infer every user's Codex config layer, so treat the seeded guidance list as best-effort when custom fallback filenames matter.
- Codex may also render an `update_plan` checklist or todo list in the UI. Treat that as ephemeral session progress, not as durable proof-loop state.
- Codex CLI surfaces most relevant to this workflow are `/agent`, `/status`, `/review`, and `/init` (generic scaffold only).
- Before reusing or resuming a Codex child, inspect the current child-thread list in `/agent` in the CLI or the equivalent child-thread inventory surface exposed by the current Codex product surface.
- Built-in `explorer` is the preferred Codex role for read-only repo discovery and proof probes. Built-in `worker` is appropriate for bounded disjoint implementation or check shards when explicit ownership is possible.
- Claude-specific templates remain upstream reference assets and are not used by the Codex helper or workflow.
- Structural validation accepts seeded placeholders; it does not certify task completion. Inspect actual evidence at the tested revision.
