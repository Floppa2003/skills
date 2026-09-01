---
name: github-author-context
description: "GitHub contributor context: identity, activity, trust, company/team signal."
---

# GitHub Author Context

Build a compact maintainer-facing profile for a PR author or GitHub user. Use this by default during PR review unless the author is Peter (`steipete`, `Peter Steinberger`, or an obvious Peter-owned bot/account).

## Inputs

Prefer a GitHub login. From a PR:

```bash
gh pr view <n> --json author,url,headRepository,baseRepository -q '{author:.author.login,url:.url,repo:.baseRepository.nameWithOwner}'
```

Skip the profile pass for `steipete` unless the user explicitly asks.

## Source Order

1. OpenClaw contributor notes, only when the local maintainer tooling is available:
The helper is available only when `~/Projects/maintainers/scripts/clawtributors` is executable and the required maintainer directories exist. If it is unavailable, skip this source and continue with public GitHub evidence.

```bash
~/Projects/maintainers/scripts/clawtributors find github <login>
```

If a contributor file matches in `~/Projects/maintainers/contributors/people`, read only:

- `Identity`
- `Signals`
- `Context`
- `Evidence`
- `Notes`

Fallback only when the new contributor file is missing, the old maintainer paths exist, and old maintainer context might help:

```bash
rg -n -i "<login>|<name>|<discord>" ~/Projects/openclaw-maintainers/people ~/Projects/openclaw-maintainers/data
```

If an old person file matches, read only the relevant sections:

- `Verdict`
- `Identity`
- `Company Affiliation`
- `Metrics`
- `Discord Communication`
- `Evidence`
- `Risks` / `Concerns` / `Recommendation` when present

2. Live GitHub public profile:

```bash
gh api "users/<login>" --jq '{login,name,company,location,bio,blog,twitter_username,created_at,followers,following,public_repos}'
```

3. Target-repo activity:

```bash
gh search prs --repo <owner/repo> --author <login> --state merged --limit 20 --json number,title,mergedAt,url
gh search prs --repo <owner/repo> --author <login> --state open --limit 20 --json number,title,updatedAt,url
gh search issues --repo <owner/repo> --author <login> --state open --limit 20 --json number,title,updatedAt,url
```

4. Collaborator permission:

```bash
gh api "repos/<owner>/<repo>/collaborators/<login>/permission" --jq '{permission,user:.user.login}'
```

A `404` means `permission: unknown/not collaborator`. A network, authentication, or `gh` failure is not an absence of permission: report it and stop the profile pass rather than suppressing the error.

For OpenClaw, prefer the new `openclaw/maintainers` contributor file over recomputing activity unless freshness clearly matters.

5. Local git evidence when useful:

```bash
git log --all --author="<login>" --since="90 days ago" --oneline --decorate --no-merges | head -40
git shortlog -sne --all | rg -i "<login>|<name>|<email>"
```

## Output

Keep it short. Add this block near the top of a PR review:

```text
Author context: @login
- Sources: <maintainer-local if available; public GitHub; repository history>
- Maintainer-local evidence: <available/unavailable>
- Who: <name/company/location/role, confidence>
- Activity: <merged/open PRs, issues, reviews/commits if known>
- OpenClaw signal: <maintainer/candidate/drive-by/vendor/security/unknown>
- Risk: <review-load, broad PRs, low history, company-governance, none obvious>
```

When maintainer-local evidence is unavailable, write exactly:

```text
Author context sources: public GitHub and repository history.
Maintainer-local evidence: unavailable.
```

Do not quote private phone/email/contact details unless Peter asks. Separate employer from company-directed OpenClaw work; almost everyone has an employer.

## Contributor Notes

When the local maintainer helper is available, add a note only if a merge/rejection/close/review creates future review value: first good merge, unusually strong work, repeated quality problems, slop, no-repro churn, exceptional responsiveness, lack of follow-through, or identity confirmation. Otherwise, do not create a local note.

Use the maintainer repo helper so Markdown stays consistent:

```bash
~/Projects/maintainers/scripts/clawtributors note github <login> --kind merged --pr <n> --summary "Focused bug fix. Tests credible. Smooth review."
~/Projects/maintainers/scripts/clawtributors note github <login> --kind rejected --pr <n> --summary "Broad generated refactor; no reproducible bug; asked to split."
~/Projects/maintainers/scripts/clawtributors link github <login> discord <id> --username <discord> --confidence high --evidence "Self-linked authored PRs in #clawtributors."
```

Keep notes terse, factual, dated, and linked. Do not record ordinary noise.
