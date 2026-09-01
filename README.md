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
`main` directly. Open and review the pull request from that URL.

```bash
python3 skill_updater/update_skills.py refresh --check
python3 skill_updater/update_skills.py refresh --apply
python3 scripts/build_chatgpt_md.py
```

Run `refresh --apply` only from a dedicated review branch. The command refuses
to modify `main` or `master`.

After review and merge, deploy the canonical `main` state to Codex:

```bash
python3 skill_updater/update_skills.py deploy --check
python3 skill_updater/update_skills.py deploy --apply
```
