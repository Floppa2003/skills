# Agent Desktop Installation Plan

> The lead implements inline; one read-only verifier with fork_context=false
> reviews the complete result. This is the only implementation checklist.

**Goal:** Install the approved Agent Desktop CLI and a narrow personal skill,
using the canonical skills repository without replacing native Computer Use.

**Architecture:** A locally authored router loads guides from the installed
binary. Official release archives stay outside Git; provenance and approved
runtime versions belong to repository metadata, local receipts record deployment.

**Tech Stack:** Existing Python 3.12 updater, GitHub Releases, native CLI/helper,
standard-library validation and existing metadata/manifest tooling.

**Spec:** The approved CLI/router proposal and the user's subsequent approval
of PR/merge/deployment including native GitHub Release/SHA-256 updater support.

## Constraints and Acceptance

- Preserve unrelated dirty files and all existing skills, overlays and schedules.
- No MCP server, new global AGENTS.md rules, npm install, cloud model service,
  broad skill import or permission changes.
- Pin official version, source commit and asset SHA-256; verify build provenance.
- Keep binary and its same-release helper together; preserve foreign commands
  or modified managed installations rather than overwriting them.
- The router must activate for explicit CLI/custom-harness/fallback use, not
  ordinary browser, API, research or native Computer Use tasks.
- Verify CLI version, core/platform guides, compatibility and permission state.
  A GUI capability claim requires a test on task-owned UI, not permission state
  or an exit code alone. Do not inspect private windows to prove installation.
- Maintain one approved-version source and use merged origin/main deployment
  for the skill. A runtime update proposal is not a completed installation.

## Implementation

- [x] Inspect upstream release, local environment and repository boundaries;
  verify archive digest/build attestation, staged CLI and embedded guides.
- [x] Create and validate the narrow router, metadata, registry entry and manifest.
- [x] Implement the authorized native-release lifecycle with regression checks.
- [x] Install the approved CLI/helper, verify actual installed state and perform
  the smallest safe task-owned UI control when feasible without new permissions.
- [ ] Run repository/updater and skill activation checks; independently review
  correctness, source provenance, security, routing and acceptance evidence.

## Release Conditions

External publication requires user authorization. After CI and independent
acceptance, merge the reviewed branch, deploy only from origin/main and verify
the actual remote source, installed skill hash and native runtime. Preserve the
primary dirty checkout. Close task-owned UI/processes and remove temporary
worktrees/builds; retain only focused evidence and intended installed state.

## Native Release Adapter

Files: release_tools.py owns typed release records, metadata-only refresh,
bounded verified archive preparation, inspection and deployment. Existing
runtime_tools.py journal/rollback and runtime_process.py writer barriers remain
the shared installation mechanics. update_skills.py composes both adapters;
check_refresh_result.py accounts for their events. Add focused tests in
tests/test_release_tools.py and extend publication tests. The existing runtime
validation CI job also executes the pinned Linux CLI and embedded-guide probe.

An optional release_tools list in registry.json pins repository, stable tag,
source commit, dependent skill, and Unix platform asset names, sizes and SHA-256.
The adapter initially supports agent-desktop only. Refresh reads GitHub metadata
without running candidate binaries; incomplete metadata or same-tag drift
preserves the whole prior record. Events use runtime:<name> and are included in
the existing all-sources publication gate.

Install under the user's data directory in agent-desktop/bin, with command links
in ~/.local/bin; environment overrides permit isolated tests/CI. Native receipts
live under work-root/release-tools, separately from approved registry inputs.
First adoption compares existing files to the verified archive, rather than
trusting their self-reported manifest. Candidate probes read version and bundled
core/platform guides with service credentials removed; they perform no GUI,
permission, clipboard, cloud or account operation. Later skill-deployment
failure must roll the native adapter back through the shared transaction.

Regression focus: registry preservation and failed-refresh accounting; invalid
or missing asset digests; archive traversal, symlinks and size/member bounds;
source/attestation mismatch; foreign commands and local drift; read-only
check/audit; first adoption; wrong-version/probe failure; interrupted recovery;
and rollback after a subsequent skill failure. Retain the existing Python
runtime behavior and its writer-lease regressions unchanged.
