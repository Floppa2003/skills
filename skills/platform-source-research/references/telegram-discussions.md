# Public Telegram Discussions

Use this procedure when the task requires actual comments under a public channel post. Apply the existing Public platform source and Telegram public discovery contracts in [route-contracts.md](route-contracts.md). This reference adds a retrieval method, not a new access policy.

## Retrieve The Public Widget

1. Identify the canonical public channel post, `https://t.me/<username>/<post_id>`. For an album, establish its parent post: attachment links can point to another item in the same album.
2. Open the official discussion widget through an approved public browser or crawler:

   ```text
   https://t.me/<username>/<post_id>?embed=1&discussion=1&comments_limit=100
   ```

   `embed=1&discussion=1` is used by Telegram's public widget script; `comments_limit` is a supported widget attribute. Use a finite limit appropriate to the thread. A normal post preview, `/s/` feed, discussion-group landing card, or `?comment=1` page may show no messages even when this widget exposes them.
3. Preserve the retrieval time, canonical post URL, requested widget URL, actual response status and raw HTML. With an available approved Firecrawl scraper, request `rawHtml`, set `onlyMainContent: false`, and use a fresh capture when freshness matters. For an MCP response, save `result.structuredContent` or its `rawHtml`, not the entire tool-result envelope. Markdown alone can duplicate template text and omit reply relationships. If one permitted surface fails, record the failure and try another permitted public surface; do not infer every Telegram route is unavailable.
4. Confirm actual `.js-widget_message[data-post-id]` nodes belong to the expected post. Record the displayed count and visible older-message control. If older comments remain, use the widget's ordinary “Show more” control, or increase the finite initial limit and verify the resulting capture. Do not invent pagination endpoints or repurpose bootstrap peer hashes. A rate limit, sign-in wall or unavailable thread remains an access limitation under the contract.
5. From this skill's root directory, parse the saved capture offline (or use the script's absolute path):

   ```bash
   python3 scripts/telegram_discussion_parser.py \
     --input /absolute/path/to/capture.json \
     --source-url https://t.me/channel_name/123
   ```

The parser uses Python's standard library and performs no network calls. It accepts raw HTML or a JSON capture with `rawHtml`/`html`, including a `data` envelope. Retrieval and pagination remain the caller's responsibility. Inspect the returned coverage fields even when the process exits successfully.

## Preserve Evidence Without Inventing Replies

- Extract each message's own `.js-message_text`, author display name, public author link when present, `time[datetime]`, ID and observed comment permalink.
- Exclude `.js-reply_tpl` and `.js-message_reply_text` from the own body. The hidden reply template repeats the current comment; it is neither a second comment nor proof of a reply.
- Use an explicit `.tgme_widget_message_reply.js-reply_to[data-reply-to]` for a reply edge. Chronological neighbors are not parent/child replies. Keep a missing parent ID as a coverage gap.
- An author can be a name-only span. Preserve the name and a null URL; do not infer a username. A group/channel “send as” identity does not identify the individual writer.
- Prefer the ISO datetime attribute to the localized visible date. Preserve its timezone; convert only for display.
- Mark photos, stickers, custom emoji and unsupported content separately. A textual fallback or an extracted message record does not mean its media was viewed.
- Retain canonical post/comment links for citations. Do not publish raw bootstrap/API/peer hashes, cookies, signed media URLs, provider identifiers or avatar data. The parser emits only normalized evidence fields.

## Coverage Contract

The parser reports list coverage separately from content coverage:

| Status | Meaning |
|---|---|
| `snapshot_complete` | The expected root is verified, unique IDs match the displayed count, and no visible older-message control remains. |
| `partial` | The capture is missing counted comments or has a visible older-message control. |
| `unknown` | The displayed count or source identity cannot be established. |
| `unavailable` | The response is a landing page or exposes no expected comment nodes. |
| `unsupported` | The supplied capture format is not supported. |
| `invalid` | Conflicting roots, comment identities, counts or duplicate records make the capture unreliable. |

`snapshot_complete` applies only to the observed public snapshot, not deleted history, private discussions, every post in a channel or subsequently added messages. `coverage.content_status: partial` can coexist with a complete list when media or metadata is unresolved. Hidden live-update controls such as `.js-messages_more.autoload.hide` are not visible requests to load older comments.

For a negative research finding, state which threads and available text bodies were read, and separately identify uninspected media and missing replies. A comment asking where someone lives is a question, not evidence of their accommodation. A lack of an answer does not establish the opposite claim.

## Verification And Maintenance

Capability check, 2026-11-23: this public widget yielded real comments without credentials on eleven public post discussions. Counts agreed with unique IDs; an initial 5-of-13 capture became 13-of-13 after increasing the finite limit. Explicit replies, name-only authors and group send-as identities were observed. Recheck the needed capability on use; neither uptime nor pagination beyond the captured threads is guaranteed.

Regression tests are in `evals/test_telegram_discussion_parser.py`. They accept externally retained, real captures of a complete widget, a partial initial widget, a landing page and a widget with explicit replies. Keep those captures and their provenance in task artifacts; do not add raw transport data to the skill repository. The test module documents the fixture arguments and observed source posts.

Primary references:

- [Telegram Discussion Widget documentation](https://core.telegram.org/widgets/discussion)
- [Telegram public widget script](https://telegram.org/js/telegram-widget.js?24)
- [Telegram discussion threads](https://core.telegram.org/api/discussion)

