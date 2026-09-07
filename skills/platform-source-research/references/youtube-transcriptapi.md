# YouTube Through TranscriptAPI

Optional provider reference for the YouTube route. Access, secrets, external effects, and approval are governed by the YouTube TranscriptAPI row in [route-contracts.md](route-contracts.md).

## Contract And Sources

Checked 2026-09-07 against the [public OpenAPI specification](https://transcriptapi.com/openapi.json) and [pricing](https://transcriptapi.com/#pricing). Recheck before each collection run; reuse that check within the run. The [upstream skill](https://github.com/ZeroPointRepo/youtube-skills/blob/5c168578ec8424dbd1bd144d1cb53e8e6db276ee/skills/youtube-full/SKILL.md) is background, not the API contract or authorization to run its signup procedure.

This third-party captions and discovery service does not download video/audio or analyze visuals. No captions means missing transcript evidence, not a new speech-recognition job. Keep `video-watch` separate when visual evidence is needed.

## Requests

Use `GET` under `https://transcriptapi.com/api/v2/youtube/`. Send the existing `TRANSCRIPT_API_KEY` as a Bearer header through the approved secret mechanism, never in the URL, logs, or displayed commands. Send a `User-Agent` naming the actual agent. Do not forward credentials to another origin on redirects.

| Endpoint | Initial query parameters | Credits per successful request |
| --- | --- | --- |
| `search` | `q`, `type=video` or `type=channel` | 1 per page |
| `channel/search` | `channel`, `q` | 1 per page |
| `channel/videos` | `channel` | 1 per page |
| `playlist/videos` | `playlist` | 1 per page |
| `channel/latest` | `channel` | 0; latest 15 uploads via RSS, not full history |
| `channel/resolve` | `input` | 0 |
| `info` | `video_url` | 0; inspect `available_languages[].code` |
| `transcript` | `video_url`, `language`, `format=json`, `include_timestamp=true`, `send_metadata=true` | 1 |

Channels accept an `@handle`, channel URL, or `UC...` ID; resolving a handle first is unnecessary. Playlists accept a playlist URL or ID. Video endpoints accept a video URL or ID. Encode query parameters with an HTTP client's parameter encoder. The checked search API exposes no language filter or `limit` parameter; bound pages and selected videos in the collection workflow, not by inventing query parameters.

## Pagination And Language

- For search, within-channel search, channel videos, and playlists, read `results`, `has_more`, and `continuation_token`. Request each next page with `continuation=<token>` at the same endpoint, without repeating the initial query parameters. Deduplicate video IDs across pages and before fetching transcripts.
- Stop on the agreed page/credit cap or normal pagination exhaustion. If `has_more=true` but the token is absent, repeats, or produces no new records, stop and report partial coverage and the inconsistent response. A capped search is not an exhaustive YouTube search.
- Select transcript languages explicitly in user-requested priority order; use `info` when available tracks are unknown. For Russian captions, `language=ru,asr-ru` can request human or auto-generated Russian tracks. `asr` alone permits any available auto-caption language; it does not mean translation. Omitted language prefers English, then another available track.
- Inspect the returned `language`; label auto-generated captions and any mismatch. Do not silently translate or substitute languages. Available Russian captions do not prove that the original speech is Russian; verify that separately when the task requires spoken-language filtering.

## Budget, Reuse, And Failures

Before requests, estimate credits from the selected pages and transcripts and set finite page, video, and attempt bounds within the approved cap. At the checked rates, two paid listing/search pages plus five transcripts cost seven credits before retries. The 100 signup credits are a one-time allowance, not a recurring free quota. Zero-credit endpoints still need an authorized account and may require active credit or plan eligibility; they are not an anonymous fallback.

Track attempted requests and confirmed charges. Repeated successful retrievals, including the provider's cached responses, cost credits. Reserve worst-case credits before each paid attempt; if a timeout leaves charging uncertain, retain the reservation rather than assuming the request was free. Do not expand the budget or buy credits automatically.

Reuse successful task-local responses only when provider, endpoint, normalized parameters, language, source identity, and requested freshness still match. Store sanitized responses and retrieval times under the task's canonical artifact directory; exclude authorization headers and secret values. Do not reuse failed or malformed responses as evidence.

On 401/402, stop under the route contract. Correct a documented parameter error before retrying a 422. For 429, respect `Retry-After`; for transient 408/5xx, use at most two retries within the remaining attempt and credit bounds. Persistent 403 or other access blocks are limitations, not permission to change identities, import cookies, or bypass controls. A 404, empty transcript, or malformed success response is missing evidence, not proof that the video is empty or absent.

Use the existing `research-run.md` for provenance and coverage: record this provider, canonical YouTube URLs, query and language, retrieval time, pages checked, unique videos, credits used or reserved, and the stopping reason. Preserve timestamped caption segments; separate collected text from later summaries, translations, and conclusions.
