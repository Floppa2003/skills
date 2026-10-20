# Verification

The package checks exercise the helper in temporary Git repositories without
model calls. They do not certify a user's implementation or the quality of an
agent's review.

## Command

```bash
python3 scripts/verify_package.py
```

## What the smoke test checks

- `SKILL.md` frontmatter exists and the `name` matches the parent directory
- the skill body is non-empty
- `scripts/task_loop.py init --task-id demo-task --task-text "Implement a demo task."` succeeds inside a fresh temporary git repository
- `scripts/task_loop.py validate --task-id demo-task` returns `valid: true`
- a task-local init sentinel makes `validate` report initialization-in-progress instead of only a misleading missing-files failure when `init` is still active
- `scripts/task_loop.py status --task-id demo-task` reports `init_in_progress: true` when the init sentinel is present
- the expected repo-local artifacts are created under `.agent/tasks/demo-task/`
- default initialization leaves project instructions and agent configuration unchanged
- Codex agent installation and `AGENTS.md` managed blocks are independent opt-ins
- reruns preserve existing task files and user guidance outside managed blocks
- differing user-maintained agents are not overwritten, including with `--force`
- seeded guidance includes Codex guides but not another product's guide
- placeholders remain UNKNOWN even when structural validation succeeds
- malformed evidence fails structural validation
- invalid task IDs do not create task artifacts
- status inspection does not initialize an absent task
- metadata preserves explicit-only activation
- symlink paths, dangling links and hard-linked outputs fail before writes
- an existing initialization marker is preserved
- read commands refuse redirected task directories

The script's exit status and output are the current check result.
