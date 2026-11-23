---
name: platform-source-research
description: Use when the task, supplied references, or likely source distribution calls for primary public posts, profiles, channels, comments, media, creator portfolios, or visual product discovery on social, video, or community platforms, even without a named platform.
---

# Platform Source Research

Collect source material from selected platforms, then hand it to the relevant analysis skill. This is a read-only acquisition router, not a reporting, publishing, or account-management workflow. Use `research-ops` for general source selection.

Do not use for ordinary web research where platform provenance is irrelevant, creative social-post ideas without source research, private-message analysis without explicit scope, or a platform write action.

## Select A Route

Select the narrowest route below and read its matching [route contract](references/route-contracts.md) before using tooling. Load only references needed for the task; existing session authorization and higher-priority instructions apply.

| Task | Procedure |
| --- | --- |
| Public Telegram comments | [Discussion widget](references/telegram-discussions.md) |
| Telegram posts, attachments, discovery, or official Desktop exports | [Telegram](references/telegram.md) |
| Instagram discovery, photos, carousels, Reels, current Stories, or saved Highlights | [Instagram](references/instagram.md) |
| X/Twitter, Reddit, LinkedIn, YouTube, Threads, TikTok, RuTube, VK Video, Habr, or VC.ru | [Platform routes](references/platform-routes.md) |

## Evidence And Handoff

1. Establish the question, selected platforms, time range, language/region, and whether only public material is in scope.
2. Reuse dedicated skills only if their access model matches the scope. Discovery, media download, captions, and comment retrieval are separate capabilities; verify the one needed.
3. Preserve the canonical URL, author/channel, date when available, exact excerpt or timestamp, and access limitation. Keep provenance separate from conclusions.
4. For multi-source or recurring work, follow the [research protocol](references/research-protocol.md). Keep its single canonical run artifact at `<task-artifacts>/research-run.md`, from [research-run-template.md](references/research-run-template.md).
5. Return the evidence bundle or hand it to `deep-research` for synthesis.
