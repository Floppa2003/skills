---
name: repo-task-proof-loop
description: Use when explicitly asked to run Repo Task Proof Loop for a substantial coding task with repo-local acceptance criteria, evidence, independent verification, and corrective work.
license: Apache-2.0
compatibility: Codex-compatible workflow. Bundled scripts require Python 3.10+; repository tools and execution access are needed to run checks.
metadata:
  author: DenisSergeevitch
  version: "1.0.0"
---

# Repo Task Proof Loop

Use this skill only on explicit request for Repo Task Proof Loop, especially for a feature, refactor, migration, or bug fix that should leave repo-local proof in `.agent/tasks/<TASK_ID>/`. Ordinary coding or review requests do not activate this workflow.

All task artifacts created by this workflow must stay inside the repository. Reuse an existing canonical specification and plan by linking them from `spec.md`; do not maintain a second requirement list or checklist. `evidence.json` is the structured evidence record and `evidence.md` its readable summary; update them together.

When the examples below mention `scripts/task_loop.py`, that path is relative to this skill root. Run it while your shell working directory is inside the target repository.

## What this skill does

1. Initializes a strict repo-local task folder under `.agent/tasks/<TASK_ID>/`
2. Seeds or updates the required artifact files
3. Optionally installs Codex role templates into `.codex/agents/`, only with explicit project-configuration approval
4. Optionally adds an `AGENTS.md` managed block under the same approval; neither action is a default or a prerequisite
5. Guides the agent through a strict loop:
   - spec freeze
   - builder implementation
   - evidence packing
   - fresh verification
   - minimal fix
   - recheck by the same independent verifier until `PASS`, a concrete blocker, or the agreed resource limit

See:
- `references/REFERENCE.md`
- `references/COMMANDS.md`
- `references/SUBAGENTS.md`
- `references/SCHEMAS.md`

## Commands this skill supports

Treat the following words as commands when the user invokes this skill:

- `init <TASK_ID>`: create `.agent/tasks/<TASK_ID>/` without changing project instructions or agent configuration
- `freeze <TASK_ID>`: create or refine `spec.md` from the user task, task file, and repo guidance
- `build <TASK_ID>`: implement the task against the frozen spec
- `evidence <TASK_ID>`: create or refresh `evidence.md`, `evidence.json`, and raw artifacts without changing production code
- `verify <TASK_ID>`: independently verify current work and record `verdict.json`, plus `problems.md` when needed
- `fix <TASK_ID>`: apply the smallest safe fix set from `problems.md`, then refresh the evidence bundle
- `run <TASK_ID>`: execute the full loop from spec freeze through verification
- `status <TASK_ID>`: summarize current artifact status

If the user does not supply a command, infer the next step from repo state:
- If the task folder does not exist, run `init` first. If the user clearly wants initialization only, stop there. Otherwise, after `init` succeeds and `.agent/tasks/<TASK_ID>/spec.md` exists, continue by re-evaluating repo state in the same turn. Do not overlap `init` with `freeze`, `build`, `evidence`, `verify`, `fix`, `validate`, `status`, or subagent work.
- If `spec.md` is missing or placeholder-only, do `freeze`
- If implementation is not yet complete, do `build`
- If evidence is stale or missing, do `evidence`
- If no fresh verdict exists, do `verify`
- If verdict is not `PASS`, fix reproducible defects; report blocked/unverified requirements when access, a decision, or a resource limit prevents progress. Do not retry unchanged failures indefinitely.

## Initialization step

Run the bundled initializer from the repository root or current working directory inside the repo:

```bash
scripts/task_loop.py init --task-id <TASK_ID>
```

Optional task seeding:

```bash
scripts/task_loop.py init --task-id <TASK_ID> --task-file path/to/task.md
scripts/task_loop.py init --task-id <TASK_ID> --task-text "User task text"
```

The initializer will:

- resolve the repo root
- create `.agent/tasks/<TASK_ID>/`
- create all required artifacts, including placeholders under `raw/`
- leave project instructions and agent configuration unchanged by default

Only after explicit project-configuration approval, `--install-subagents codex` installs missing Codex templates and `--guides agents` adds or refreshes the managed block in repo-root `AGENTS.md`. Differing existing agent files cause an error, not replacement; `--force` applies only to task artifacts and requires overwrite approval.
Nested guidance and higher-priority instructions still apply. Do not install role files merely to obtain a verifier; use the tools already available.
If `init` creates or rewrites `AGENTS.md` during a running Codex session, start a new Codex session before relying on the updated instructions. Codex snapshots project-doc guidance at session start.

Claude templates are retained as upstream reference assets, not Codex instructions or an installed runtime.

Treat `init` as a serial prerequisite. Never overlap it with `freeze`, `build`, `evidence`, `verify`, `fix`, `validate`, `status`, or child-agent spawning.

## Heavy-task default workflow

Keep one lead agent by default. Delegate implementation only when authorized and useful for independent scopes. Follow the active review policy: create one read-only verifier with `fork_context=false`, then reuse it for corrections. Role prompts describe responsibilities, not a requirement to create one agent per phase.

### Preferred delegated sequence

1. Run `init <TASK_ID>` if needed. Wait for it to finish, then confirm `.agent/tasks/<TASK_ID>/spec.md` and the repo-local task structure exist before continuing.
2. Freeze or link the canonical spec; implement and pack evidence in the owning agent
3. Spawn one read-only verifier with `fork_context=false`; supply original requirements, relevant paths, the diff, and test evidence without the lead's reasoning
4. Have the lead record the verifier's report verbatim in `verdict.json` and `problems.md`; the verifier does not edit the shared checkout
5. Fix confirmed defects, refresh evidence, and ask that same verifier to recheck
6. Stop at verified acceptance, a concrete blocker, user cancellation, or the agreed resource limit. An exhausted limit leaves unresolved requirements incomplete.

### Codex adaptive fan-out

Use this only after the user has explicitly authorized Codex delegation and the task is broad enough to benefit from bounded parallel work. Use the simpler serial sequence above for narrow tasks.

Good fits:

- multiple independent codebase questions must be answered before the spec is stable
- implementation can be split into disjoint write scopes
- proof requires several independent read-only checks across different surfaces

Codex pattern:

1. `init` stays serial.
2. If the task is still ambiguous, fan out up to 3 built-in `explorer` children in parallel. Give each one a single question, subsystem, or path scope. Wait for them, then freeze the spec.
3. Spawn one spec-freezer child and wait for it.
4. Spawn one `task-builder` child as the integration owner.
5. If implementation splits cleanly, the parent may also spawn bounded built-in `worker` children in parallel. Each worker must have explicit file or module ownership and must not write `evidence.md`, `evidence.json`, `verdict.json`, or `problems.md`.
6. Use `send_input` or the equivalent follow-up surface to keep the integration builder alive for evidence packing. The builder remains the single owner of the evidence bundle.
7. If extra proof is needed, the parent may fan out a small bounded set of read-only `explorer` children to rerun disjoint checks or inspect separate proof gaps in parallel. Those children may report commands, outputs, and findings, but they do not write `verdict.json`.
8. Reuse the single independent verifier for corrections; helper probes do not replace it.

### Platform behavior

- In Codex, keep the normal path serial and auto-mode-first after `init`. Avoid surfacing delegation internals unless they materially affect the work.
- In Codex, follow the active delegation and review policy; installing this skill does not grant new tool or external-action permissions.
- In Codex, once delegation is authorized, the skill may choose the matching child roles and whether to stay one-child-at-a-time or use bounded fan-out. The user should not need to name specific child roles or slash commands.
- In Codex, child spawning is still an explicit parent-orchestrator action. If the current Codex surface blocks delegation, say so briefly only when it materially affects the work, then continue serially.
- In Codex, keep the task tree shallow. The parent session should spawn research, builder, fixer, and verifier children directly instead of asking one custom task child to orchestrate more children.
- In Codex, once delegation is authorized, choose between one-child-at-a-time delegation and bounded fan-out from the frozen spec, repo shape, and current delegation surface. Keep `init`, evidence ownership, and every verifier pass serialized either way.
- In Codex, keep helper fan-out modest and wave-based. Prefer up to 3 parallel helper children at once, wait for that wave to finish, then decide the next phase.
- Use only roles and tool arguments supported by the current surface; where named roles are unavailable, pass the bounded role prompt to the available subagent tool.
- In Codex, reuse the live builder child for evidence packing by sending it a follow-up instruction. Reuse the independent verifier for corrections, with current evidence and unchanged acceptance criteria.
- In Codex, inspect the current child-thread list before reusing or resuming a child. Use `/agent` in Codex CLI or any equivalent child-thread inventory surface available in the current Codex product surface.
- In Codex, the plan/todo checklist UI from `update_plan` is optional session guidance only. It is useful for live progress display, but it is not the source of truth for this workflow.
- If subagents are unavailable, perform a separate local review and explicitly state that independence was not verified.

Use the exact role prompts from `references/COMMANDS.md`.

## Spec freeze requirements

If an approved canonical spec or plan exists, `spec.md` contains links to those
documents, not copied requirements or a second checklist. Remove the seeded
placeholder requirement sections. Every role follows those links and preserves
the original requirement IDs in evidence and verdicts.

Only when no canonical spec exists, freeze one in `spec.md` containing at least:

- original task statement
- explicit acceptance criteria labeled `AC1`, `AC2`, ...
- constraints
- non-goals

It may also include:

- repo guidance sources
- verification plan
- assumptions resolved narrowly from the user request

Do not edit production code during spec freeze.

## Evidence packing requirements

`evidence.md` and `evidence.json` must judge each acceptance criterion independently with one of:

- `PASS`
- `FAIL`
- `UNKNOWN`

Evidence packing may run missing checks, but it must not keep changing production code.

Every `PASS` must cite concrete proof such as:

- file paths
- commands run
- exit codes
- output summaries
- artifact paths under `raw/`

Use the canonical requirement IDs; `AC1`, `AC2` are examples for a new spec.
Do not claim overall `PASS` in the evidence bundle unless every acceptance criterion is `PASS`.

## Independent verification requirements

Start the verifier with `fork_context=false`; reuse it on rechecks. At task acceptance, check the original requirements and previously unreported in-scope defects, not only known fixes.

The verifier must judge the current repository state and current rerun results, not the builder narrative.

The verifier returns the following reports for the lead to persist:

- `.agent/tasks/<TASK_ID>/verdict.json`
- `.agent/tasks/<TASK_ID>/problems.md` only when overall verdict is not `PASS`

`problems.md` must include, for each non-`PASS` criterion:

- criterion id and text
- status
- why it is not proven
- minimal reproduction steps
- expected vs actual
- affected files
- smallest safe fix
- corrective hint in 1-3 sentences

The verifier must not modify production code or backfill the evidence bundle.

## Fixer requirements

The fixer starts from these artifacts, then reads the relevant code and evidence:

- `spec.md`
- `verdict.json`
- `problems.md`

The fixer must:

- reconfirm each listed problem in the codebase before editing
- make the smallest safe change set
- avoid regressing already-passing criteria
- regenerate `evidence.md`, `evidence.json`, and raw artifacts
- stop without writing final sign-off

## Validation

Before claiming the workflow is correctly initialized or the artifact set is complete, run:

```bash
scripts/task_loop.py validate --task-id <TASK_ID>
```

Run `validate` only after `init` has fully finished. If it reports initialization in progress, wait and rerun it instead of treating that result as stable task failure.
`validate` checks artifact presence and JSON structure, not behavioral correctness. Placeholder files and the seeded PNG are not proof. Record the tested revision (including a dirty-tree fingerprint when applicable) with evidence; stale evidence cannot establish PASS.
The helper rejects symlink and hard-link destinations and preserves an existing initialization marker. Inspect and resolve their ownership before retrying; do not remove user state to bypass the check.

For a quick summary:

```bash
scripts/task_loop.py status --task-id <TASK_ID>
```

Run `status` only after `init` has fully finished when you need stable task state. If it reports `init_in_progress: true`, treat that as a retry-later condition.

## Guardrails

- Keep `.agent/tasks/<TASK_ID>/` inside the repo
- Treat the Codex todo/checklist UI as ephemeral progress only; the durable workflow state lives in `.agent/tasks/<TASK_ID>/`
- Never claim task completion unless every acceptance criterion is `PASS`
- Separate evaluator and fixer roles
- Keep Codex fan-out shallow and bounded. One builder owns evidence; one independent verifier judges it and the lead records its report.
- Reuse the independent verifier; preserve original acceptance criteria on rechecks
- Prefer the smallest defensible diffs during fixes
- Preserve existing project guidance; change managed blocks only with explicit approval
