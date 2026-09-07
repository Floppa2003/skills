# Threads Public Search

Use the Threads API contract in [route-contracts.md](route-contracts.md). This reference does not authorize app creation, OAuth setup, or permission changes.

## Contract And Access

Checked 2026-09-07 against Meta's [keyword-search documentation](https://developers.facebook.com/documentation/threads/keyword-search.md) and [official API collection](https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api). Recheck the relevant contract before a new collection run and reuse that check within the run.

The API needs a Meta app, a user access token, `threads_basic`, and approved `threads_keyword_search` permission for public search. Without search approval, results are limited to the authenticated user's own posts; token presence or HTTP success does not establish public coverage. Inspect permission status through the approved connection, never token values in chat or private configuration files.

## Requests And Coverage

- Use `GET https://graph.threads.net/v1.0/keyword_search` with an HTTP client's query encoder. Send authentication through the approved secret mechanism, not the URL or logs.
- `q` is the query; `search_type` selects `TOP` or `RECENT`; `search_mode` selects `KEYWORD` or `TAG`. Request only needed `fields`, such as `id,text,permalink,username,timestamp,media_type,has_replies`. Use documented `since`, `until`, and `limit` for the task's period and page size; a page limit is not a total-run limit.
- Bound requests and unique results before collecting. Follow the documented pagination cursors only at the approved API origin; deduplicate post IDs and stop on repeated cursors or pages with no new records. Do not forward authentication to another origin from a response-provided link.
- Preserve query, ordering, time bounds, requested/returned counts and the stopping reason. Search ordering, indexing, API scope and caps limit coverage; neither `TOP` nor `RECENT` is an exhaustive archive.
- Keyword search does not guarantee arbitrary reply/conversation access. `has_replies` is not reply text. Check the exact endpoint and permission before collecting a conversation; otherwise report replies as uncollected.

On permission/authentication/rate failure, stop this API route and report the specific access gap. Never silently substitute own posts, public-web snippets, or a different language for the requested public search. Preserve canonical post URLs, text and authorship separately from analysis.
