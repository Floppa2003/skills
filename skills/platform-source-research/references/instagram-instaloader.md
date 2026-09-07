# Instagram Through Instaloader

Use only for the Local public social extraction contract in [route-contracts.md](route-contracts.md). Instaloader is an unofficial local client, not an Instagram API entitlement or a guarantee of anonymous access.

## Capability And Prerequisites

Checked against [Instaloader 4.15.3](https://github.com/instaloader/instaloader/releases/tag/v4.15.3) and its [CLI documentation](https://instaloader.github.io/cli-options.html) on 2026-09-07. Check the installed version/help before relying on these flags. If missing, report the prerequisite; installation is a separate approved action. The base package is sufficient; the optional `browser-cookie3` extra is unnecessary for this route.

Public post/Reel metadata and captions may be retrievable without login. Comments, hashtags, locations, Stories, saved items and private history require login in the documented workflow and are outside this route. Even public posts may be login-gated or rate-limited; do not interpret failed extraction as a deleted or empty post.

## Bounded Metadata Collection

Normalize supplied or browser-verified `/p/<shortcode>/` and `/reel/<shortcode>/` links. Use a finite, deduplicated list of shortcodes. Set `ARTIFACT_DIR` to the task's canonical directory and `REQUEST_TIMEOUT` to its positive per-request timeout; set a separate wall-clock deadline in the runner. The following collects one post's JSON and caption text without downloading media:

```bash
instaloader \
  --no-pictures --no-videos --no-profile-pic --no-iphone \
  --no-compress-json --no-resume \
  --max-connection-attempts 1 --request-timeout "$REQUEST_TIMEOUT" \
  --abort-on 302,400,401,403,429 \
  --dirname-pattern "$ARTIFACT_DIR/instagram/{target}" \
  --filename-pattern '{shortcode}' -- "-$SHORTCODE"
```

Do not add login, password, session, browser-cookie, or unreviewed argument-file options. One attempt avoids built-in retry escalation; the request timeout is not a whole-run deadline. Keep stderr and exit status. On failure, retain useful earlier results as partial evidence and use only an independently permitted fallback.

`--count` does not cap ordinary profile downloads: it applies to hashtag/location/feed/saved targets. Do not pass a profile name expecting a small bounded sample. Discover a limited set of public post URLs first; do not start an unbounded profile archive. Keep any later authorized cache/resume state task-local and reuse it only for matching source, parameters, version, and freshness.

## Evidence

Inspect the resulting JSON/text for the requested shortcode, owner, publication date, caption, media type and carousel children; mark absent fields unknown. A post caption is not a speech transcript. Preserve the canonical Instagram URL and retrieval time in `research-run.md`; distinguish data fetched from data inferred. Download images/video only when required by the task, not merely because their URLs appear in metadata.
