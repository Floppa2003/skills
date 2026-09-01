# Skill Resolution Protocol

`CHATGPT.md` is a routing manifest for ChatGPT Web. It does not define Codex
behavior and does not replace Codex `AGENTS.md` instructions.

For each user task:

1. If the user explicitly names a skill, select it.
2. Otherwise, select a skill when the task clearly matches its catalog
   description.
3. When several skills match, use the smallest sufficient set. Process and
   workflow skills run before implementation or domain skills when ordering
   affects the work.
4. After selecting a skill, read its current complete `SKILL.md`. The catalog
   description is only a routing hint, not the skill instructions.
5. Resolve relative paths from the selected skill's directory.
6. Load secondary references, scripts, assets, and templates only when needed;
   do not bulk-load directories.
7. Reuse provided scripts, assets, and templates when applicable instead of
   recreating equivalent artifacts.
8. Follow higher-priority system, project, and user instructions when they
   conflict with a skill.
9. For follow-up turns within the same continuing task, reuse already loaded
   routing and skill instructions while they remain applicable. Re-resolve the
   skill set when the task changes materially or there is reason to believe the
   repository changed.
10. `using-superpowers` is a meta-routing skill whose default "start every
    conversation" trigger is already subsumed by this protocol. Do not select
    it solely because a conversation or task started. Select it only when the
    user explicitly requests it or its distinct instructions are otherwise
    materially needed.
