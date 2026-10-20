# Subagent integration

This skill can install Codex project role templates with separate approval.
Default initialization installs none. Use available subagent tools without
project configuration changes when possible.

On the Codex side, these are custom agent TOML config layers, not a separate manifest format.

## Installed files

### Codex

```text
.codex/agents/task-spec-freezer.toml
.codex/agents/task-builder.toml
.codex/agents/task-verifier.toml
.codex/agents/task-fixer.toml
```

The agent files are intentionally narrow and role-specific.

## Codex file shape

Codex custom agents under `.codex/agents/` are standalone TOML config layers.

Each file in this skill defines:

- `name`
- `description`
- `developer_instructions`

The Codex templates also use `nickname_candidates` for cleaner UI labels when several spawned children are visible at once.

Other `config.toml` keys could be added later if needed, but this skill mostly inherits the parent session's model, sandbox, tools, and MCP configuration.

Codex also ships built-in `default`, `worker`, and `explorer` roles. This skill adds task-specific roles alongside those built-ins rather than replacing the general-purpose ones.

## Built-in Codex roles in this workflow

- Use built-in `explorer` for bounded read-only discovery before spec freeze and for read-only proof probes after build.
- Use built-in `worker` only when the task cleanly splits into disjoint implementation or check shards with explicit ownership.
- Keep `task-builder` as the integration owner. Even in broader-task Codex fan-out runs, that role remains the single writer for `evidence.md` and `evidence.json`.
- Keep one read-only verifier started with `fork_context=false`, reused for corrections. The lead records its verdict; helper probes are not additional reviewers.

## Role definitions

### `task-spec-freezer`

Purpose:
- Freeze the task into `.agent/tasks/<TASK_ID>/spec.md`

Hard boundaries:
- May read repo guidance and relevant code
- Must not change production code
- Must not write verdict or problems files

### `task-builder`

Purpose:
- Implement the task and later pack evidence

Modes:
- `BUILD`
- `EVIDENCE`

Hard boundaries:
- In `BUILD`, implement against the spec
- In `EVIDENCE`, do not change production code

### `task-verifier`

Purpose:
- Independent verification against the current codebase, with the same verifier reused for corrections

Hard boundaries:
- Must not edit production code
- Must not patch the evidence bundle to make it look complete
- Must return the verdict report for the lead to persist in `verdict.json`
- Must return problem details when the verdict is not `PASS`

### `task-fixer`

Purpose:
- Repair only what the verifier identified

Hard boundaries:
- Must reread the spec and verifier output
- Must reconfirm the problem before editing
- Must regenerate evidence after the fix
- Must not write final sign-off

## Codex invocation pattern

Use explicit delegation language at the parent-orchestrator layer. The skill should spawn one named child, wait for it, and then continue when delegation is the right internal choice.
Do not spawn any child until `init <TASK_ID>` has finished and `.agent/tasks/<TASK_ID>/spec.md` exists.
Do not batch `init` with other commands or tool calls.

Codex-native expectations that matter here:

- The parent follows the active delegation and review policy; named roles are optional and depend on the exposed tool surface.
- Once delegation is authorized, the parent chooses the specific child roles. The user does not need to name the exact role or slash-command flow.
- Keep the task tree shallow. The parent session should orchestrate children directly instead of asking one custom task child to spawn more children.
- Inspect the current child-thread list with `/agent` in the CLI or the equivalent child-thread inventory surface exposed by the current Codex product surface before respawning or resuming a child.
- Use `send_input` to continue a live child.
- Reuse the verifier for corrections; its initial context must exclude the lead's reasoning and conversation history.
- Before reusing or resuming a child, inspect the current child-thread list rather than assuming the needed child is gone.

Default Codex path for narrower tasks:

- One lead for spec, implementation and evidence.
- One independent read-only verifier, reused for corrections.
- Separate implementation children only when authorized and useful.

Adaptive Codex fan-out path for broader tasks after delegation is explicitly authorized:

- Fan out up to 3 `explorer` children in parallel when the task needs parallel discovery before the spec is stable.
- Keep one `task-builder` child as the integration owner.
- If implementation splits cleanly, add bounded `worker` children in parallel with explicit file or module ownership.
- If proof needs multiple read-only probes, keep them bounded; the single verifier judges the result and the lead persists its report.

Suggested shape:

```text
Spawn one `task-spec-freezer` agent for TASK_ID <TASK_ID>. Wait for it. Tell it to freeze the spec in .agent/tasks/<TASK_ID>/spec.md using the repo guidance and the task source.
```

Repeat the same pattern for `task-builder`, `task-verifier`, and `task-fixer`.

Keep delegation depth flat. The narrower-task path uses one child per role at a time; the broader-task path may fan out multiple bounded `explorer` or `worker` children in parallel.

Fan-out variant:

```text
Spawn two `explorer` children in parallel for TASK_ID <TASK_ID>.

Explorer A scope:
- path prefix: <PATH_A>
- question: <QUESTION_A>

Explorer B scope:
- path prefix: <PATH_B>
- question: <QUESTION_B>

Wait for both. Then fold their findings into one spec-freezer or builder step.
```

## Same-session evidence packing

The preferred pattern is:

1. Spawn `task-builder`
2. Let it implement
3. Continue with the same child in `EVIDENCE` mode

In Codex, this same-session follow-up is the preferred path. Keep the builder child alive and send it a follow-up instruction for evidence packing so it can reuse its own command results and local context.
If the parent used parallel explorers or workers earlier, the builder should still stay the single owner of `evidence.md` and `evidence.json` and cite those sibling results only after validating they still apply.

Verifier independence comes from its initial isolated context and read-only role.
Reuse that verifier for rechecks, preserving the original acceptance criteria.

## Why the roles stay separate

The workflow is designed to keep:

- implementation
- judgment
- correction

as separate roles. This reduces self-justification and makes failures easier to localize.
