# Optional Apify Social Collection

Use only under the Apify social collection contract in [route-contracts.md](route-contracts.md). These are third-party scrapers, not Meta or TikTok official APIs. An installed `apify` skill or Membrane CLI is not evidence of a ready connection or collection authorization.

## Select The Narrowest Actor

Candidate capabilities checked against the linked publisher pages on 2026-09-07. Recheck the selected Actor's current input/output schema, build and pricing before each new run; do not load unrelated Actor documentation.

| Actor | Use | Boundary |
| --- | --- | --- |
| [apify/instagram-scraper](https://apify.com/apify/instagram-scraper) | Public post/Reel/profile data and comments; profile, hashtag or place discovery | Select one supported input/result mode. Search is not global full-text post search; comments need post/Reel URLs. |
| [clockworks/tiktok-scraper](https://apify.com/clockworks/tiktok-scraper) | Public keyword/hashtag/profile discovery, video metadata and available subtitles | Video description, subtitles and comment counts are distinct evidence types. Do not infer spoken language from description language. |
| [clockworks/tiktok-comments-scraper](https://apify.com/clockworks/tiktok-comments-scraper) | Comment text for selected public video URLs | Bound comments and replies separately; a count or sample is not the full discussion. |

## Preflight And Execution

1. Confirm the existing ready connection and authorized Actor/mode. Reuse the `apify` skill or an existing approved API/MCP connector for schema discovery and execution, but do not run its installation, login, `connection ensure`, scheduling, or generic account-management instructions. If a needed bounded operation is unavailable, report it.
2. Inspect the selected build's input/output and [run API](https://docs.apify.com/api/v2/actors-runs-post) contract. Set the supported input limits, finite run timeout, total result/comment bounds and allowed media downloads; do not assume every Actor accepts `limit` or the same field names. Record the selected build. A schema or pricing change invalidates a prior preflight.
3. Check [current pricing](https://apify.com/pricing), including startup/events, compute/proxy charges, dataset reads/storage and retries. The Free plan's credit allowance is not unlimited use or authorization to spend. Allocate the approved total across discovery, selected-item/comment runs and overhead. Use applicable server-side spend controls; an Actor charge cap need not cover later storage/retrieval. If the all-inclusive cap or approved retention cannot be enforced, stop before starting and ask for a bounded alternative.
4. Start only the approved run; record its ID immediately, poll within the deadline, and fetch bounded dataset pages. Cancel only the task's own running job when its deadline/bound is reached, then verify its terminal state. If a start request times out, reconcile whether it created a run before retrying; retain uncertain charges. Never start another job merely because a synchronous request timed out.
5. Validate records against the requested source IDs, dates, content type and required fields. Separate Actor error records from findings. Empty/blocked/private responses and truncated comment trees are coverage gaps, not absence proofs; reconcile a small public-browser control when feasible. Deduplicate before any paid detail/comment request.

## Reuse And Handoff

Reuse a successful dataset only when Actor/build, normalized inputs, source scope, schema and freshness still match; paginate the existing dataset rather than rerunning the Actor. Keep sanitized results and the Actor/build, run/dataset IDs, collection times, budget used/reserved and coverage boundary in the task's existing `research-run.md`.

Remote datasets are retained external artifacts, not local temporary files. Honor the approved retention, report their handles, and do not delete unrelated storage or create a recurring schedule. Access or budget failure does not authorize a social login, credential sharing, proxy changes, or an unapproved provider.
