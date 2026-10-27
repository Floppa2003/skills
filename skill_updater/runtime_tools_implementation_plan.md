# Managed Runtime Tools Implementation Plan

> Execution: the lead implements this plan inline, then one read-only verifier
> with fork_context=false reviews the complete result. This is the only task
> checklist; other records may link here without repeating it.

**Goal:** Track crapper, dryer and mutator in the existing canonical registry,
propose upstream updates through review, validate their working Python workflow,
and deploy approved versions with rollback.

**Architecture:** Add an optional root-level runtime_tools list without changing
the existing skills schema or count. Each uv tool bundle records its GitHub
packages, tracking branches, pinned commits, Python version, executable names,
fixed supporting requirements and dependent skills. Refresh resolves pins only;
a read-only CI job installs and probes candidates in disposable uv directories.
Merged-origin local deployment verifies ownership and drift, backs up and probes
changes, and rolls back the tool environment if tool or skill deployment fails.

**Tech stack:** Python 3.12 standard library, existing updater CLI and events,
uv, existing GitHub Actions workflows.

**Spec:** The approved task and this file's Scope and Acceptance sections.

## Scope and Constraints

- One canonical registry.json, no fake SKILL.md entries for programs.
- Initially one bundle: ub-mode-tools, primary uv tool crapper, three GitHub
  package sources; retain today's installed revisions as initial approved pins.
- Preserve 81 skills, existing overlays, local instructions and unrelated work.
- Keep existing daily schedule and manual review/merge. No auto-merge.
- Do not execute new upstream tool code in the write-permission refresh job.
- CI execution uses read-only permissions and no persisted checkout credentials;
  package/probe subprocesses do not inherit service tokens or project secrets.
- Pin supporting Python requirements to the verified environment; no automatic
  third-party dependency upgrades as part of this feature.
- No binaries or virtual environments in GitHub. ChatGPT remains a router.
- Local apply must preserve unrelated uv tools and refuse unmanaged entrypoint
  collisions or detected modifications to the managed tool environment.
- Fresh native skill activation and every language runtime are not acceptance
  claims. Python controls must establish actual analysis and mutation behavior.

## Review Focus

- Existing add/adopt/metadata/save paths must preserve runtime records.
- Failed or partial refresh must account for every skill and runtime exactly
  once and preserve failed runtime pins before publication.
- Check/audit modes must not change installed tools, profile state or commands.
- A failed candidate, interrupted install or later skill failure must preserve
  or restore the previously installed environment and command links.
- A missing package, wrong Git origin, edited source file or foreign command
  must not be reported as a current healthy installation.

## Implementation

### Registry and Refresh

Files: runtime_tools.py, update_skills.py, check_refresh_result.py,
tests/test_runtime_tools.py, tests/test_refresh_publication.py.

- [x] Add failing tests for round-trip preservation, invalid bundle contracts,
  local-Git pin advancement, failed-source preservation and runtime accounting.
- [x] Observe failure, then implement typed bundle loading and pin-only refresh.
  Reuse existing Git/event/atomic-registry behavior; do not install or import
  upstream packages during refresh.
- [x] Verify existing updater and publication tests plus the new refresh tests.

### Validation and Deployment

Files: runtime_tools.py, runtime_process.py, runtime_probe.py, update_skills.py,
tests/test_runtime_tools.py.

- [x] Add failing tests for read-only checks, origin/entrypoint/source drift,
  installation failure and rollback when later skill deployment fails.
- [x] Observe failure, then implement isolated uv validation, installed-profile
  inspection and a rollback-protected deployment context around skill deploy.
  Keep local deployment observations separate from canonical input pins.
- [x] Add a bounded maintained Python probe with known duplicate/nonduplicate
  controls and weak/strong mutation tests; verify source preservation and worker
  cleanup. Use the skill's 0.8 duplication threshold and CRAP < 10 requirement.
- [x] Run a real isolated install/probe and fault-injection rollback checks.

### Release Integration

Files: registry.json, scripts/validate_repository.py,
.github/workflows/repository-validation.yml, README.md.

- [x] Register the existing three tool pins and locked supporting requirements;
  wire repository validation, strict local audit and read-only runtime CI.
- [x] Run the complete updater suite, manifest check, repository validation,
  real tool probe and deployment preflight.
- [ ] Independently review the original scope and resolve all Critical/Important
  findings, rechecking corrections with the same verifier.
- [ ] With release authorization, publish PR, pass CI, merge, deploy only from
  origin/main and verify remote source, all skill hashes and live tool state.
- [ ] Finalize this checklist and remove task-owned ephemeral resources while
  retaining evidence and preserving the primary checkout's unrelated changes.

## Acceptance Evidence

Use local Git fixtures for commit refresh; existing registry round trips for
compatibility; temporary uv roots for installation/probe and rollback tests;
and the live installed bundle for a non-destructive current-state check. The
probe must observe nonempty metrics, a known exact duplicate and a negative
control, surviving mutations with weak tests, killed mutations with strong
tests, and unchanged source bytes. Pin changes are a review proposal, not a
claim that the candidate executed successfully; CI and deployment establish
that separately. Store task run evidence outside the repository under the
workspace's artifacts/skill-runtime-updates directory.
