---
name: workflow-opportunity-audit
description: Use when the user asks to analyze multiple sessions, memories, work-history records, or agent-setup patterns to discover repeated manual workflows and recommend missing reusable automation. Do not use for implementing an already identified automation, installing or cleaning skills, or reviewing a single workflow.
---

# Workflow Opportunity Audit

## Overview

Find evidence-backed opportunities. Prefer the smallest mechanism. Keep the audit read-only unless the user approves implementation.

## Evidence Boundary

1. Confirm period and scope. If absent, use 30 recent days and state it.
2. Start with compact sources:
   - `~/.codex/history.jsonl`;
   - `~/.codex/memories/MEMORY.md` and relevant rollout summaries;
   - installed skill names and descriptions;
   - scripts, validators, automations, and project plans indicated by those sources.
3. Open raw transcripts only to verify candidates. Do not read every transcript or enumerate whole workspaces; use indexes to target relevant paths.
4. Record source counts, period, sampling, and coverage gaps. Stop when additional sources repeat patterns without changing candidate ranking.

Keep analysis local, mask credentials and identifiers, and quote only minimum supporting text.

## Candidate Gate

Keep a candidate only when:

- it occurred at least twice independently, or one costly occurrence has concrete recurrence evidence;
- its inputs, procedure, and expected output are stable enough to reuse;
- reuse would materially reduce time, error risk, cost, or repeated user intervention;
- the current inventory does not already cover it adequately.

Treat similarity as a lead, not proof. Merge equivalent instances and distinguish project-local recurrence from cross-project reuse.

## Choose the Smallest Form

Evaluate forms in this order:

1. `skip`: coverage is adequate or evidence is weak;
2. instruction: judgment-heavy behavior belongs in project or global instructions;
3. validator or script: deterministic check or transformation;
4. skill: reusable procedural judgment or domain workflow;
5. subagent: bounded context isolation or independent review is repeatedly valuable;
6. automation: stable trigger, schedule, inputs, and safe action exist.

Do not recommend a global skill for repository-specific behavior or a subagent merely because a task is large. Do not create, install, schedule, or edit during the audit.

## Validation

For every retained candidate:

1. cite two dated occurrences, or explain concrete recurrence evidence for one costly event;
2. inspect the nearest existing capability and state the uncovered gap;
3. estimate benefit numerically when evidence supports it, otherwise label it qualitative;
4. state confidence and the smallest check that could change the recommendation.

Reject candidates supported only by keyword frequency, one ambiguous episode, or duplicated mirrors of the same work.

## Output

Lead with no more than five high-confidence candidates:

| Candidate | Evidence and recurrence | Existing coverage and gap | Smallest form | Expected benefit | Confidence | Recommendation |
|---|---|---|---|---|---|---|

Then include:

### Skip or Already Covered

List recurring workflows that do not justify new machinery and name the existing coverage.

### Coverage

State the inspected period, compact sources, targeted raw evidence, unavailable sources, and important uncertainty.

If no candidate passes the gate, say so explicitly. A justified `skip` is a successful audit.
