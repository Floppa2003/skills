# Reusable skills

This repository is the canonical storage for reusable personal skills shared by
Codex and ChatGPT Web.

- Codex discovers `skills/*/SKILL.md` natively and follows its own local or
  project `AGENTS.md`.
- ChatGPT Web uses the generated [`CHATGPT.md`](CHATGPT.md) only as a routing
  manifest for the same skill files.

## Add or update a skill

For a GitHub-sourced skill, create a review branch and register it through the
managed updater so provenance, the reviewed source commit, and the canonical
tree hash stay synchronized:

```bash
git switch -c update/<skill-name>
python3 skill_updater/update_skills.py add \
  --name <skill-name> --repo <owner/repo> --path <path> --ref <ref>
```

For an intentionally local skill, add its directory and registry entry together.
Do not copy Codex-managed `.system` skills or generated dependencies. In either
case, keep the `SKILL.md` frontmatter `name` equal to its directory name, then
regenerate and validate the ChatGPT routing manifest:

```bash
python3 scripts/build_chatgpt_md.py
python3 scripts/build_chatgpt_md.py --check
python3 scripts/validate_repository.py
```

Commit the skill changes and regenerated `CHATGPT.md` together.

## Upstream updates and local deployment

`skill_updater/registry.json` records each original upstream, reviewed Codex
overlay, source commit, and canonical tree hash. The scheduled upstream workflow
updates a dedicated review branch and prints its compare URL; it never updates
`main` directly. Open and review the pull request from that URL. A complete
partial refresh can publish validated updates while preserving blocked skills;
the run remains failed and retains a diagnostic artifact naming the blockers.
Global failures or failed validation prevent publication.

Keep overlays limited to necessary compatibility and behavioral differences.
Preserve compatible upstream text; remove only provable redundancy, never
constraints or caveats. Keep normal patch context, verify replay against the
pinned upstream, and review conflicts instead of forcing patches through.

```bash
python3 skill_updater/update_skills.py refresh --check
python3 skill_updater/update_skills.py refresh --apply
python3 scripts/build_chatgpt_md.py
```

Run `refresh --apply` only from a dedicated review branch. The command refuses
to modify `main` or `master`.

### Runtime tools

The optional `runtime_tools` registry section tracks Git-pinned CLI dependencies
separately from native skills. Currently `ub-mode-tools` contains crapper, dryer
and mutator in one uv-managed Python 3.12 environment. Supporting packages are
fixed, not automatically upgraded.

Refresh proposes new source commits without executing their code. Read-only CI
installs those exact commits in disposable uv roots and checks real coverage,
duplicate and mutation controls. Run the same validation locally with
`python3 skill_updater/update_skills.py validate-runtimes`.

Merged-main deployment uses uv, detects source/entrypoint drift, probes the
result and restores the previous environment if installation, probing or skill
deployment fails. Its generated local receipts are deployment observations,
not another source of approved versions. An interrupted update is recovered
on the next authorized apply; checks never perform recovery. Keep local command
changes for review rather than forcing them through a deploy.

Managed commands hold a kernel writer lease even if their updater parent dies;
recovery waits for that lease before restoring files. Transaction tokens prevent
late commands from an older update from starting afterward. Audit checks the
actual isolated Python interpreter as well as package and command integrity.

Tool execution is not guaranteed read-only: upstream coverage can install
dependencies in the inspected project. CI is not an OS-level sandbox; builds
execute the selected upstream code with service tokens removed from their
environment. Only install source revisions you are willing to trust.

After review and merge, deploy the canonical `main` state to Codex:

```bash
skill_updater/sync_and_deploy.sh
```
