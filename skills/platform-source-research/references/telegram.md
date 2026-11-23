# Telegram

Apply the matching [route contract](route-contracts.md); read the sections needed for the task.

To read channel posts or a public channel feed, use the public Telegram page with an approved browser route first. For recurring public-source collection, preserve the public URL, collection time, and access limitation in task-local artifacts.

For comments under a public channel post, use the official public discussion widget per [telegram-discussions.md](telegram-discussions.md). A post preview, group landing card or displayed comment count is not a retrieved discussion. Collect actual message records, explicit reply links and snapshot coverage; the reference includes an offline parser for saved HTML.

For a public Telegram post attachment, use the post's available direct download or the ordinary [TelegramDownloader](https://telegramdownloader.net/ru/) form under the Public media downloader contract: submit the exact post URL, follow the generated download link and the site's normal screen/timer, then use the visible final file button. Verify the file opens in its expected format and matches the original post. Preserve the canonical post URL. A `?comment=...` URL identifies a discussion comment; a file from the channel post does not establish the comment's attachment was retrieved.

For free discovery across public Telegram sources:

1. Search the open web with the subject, alternative formulations, language variants, and bounded `site:t.me` queries. Treat results as discovery leads, not evidence.
2. Normalize candidates to canonical public Telegram URLs. Deduplicate channels, groups, mirrors, reposts, and repeated results before collection.
3. For public channels with a username, inspect browser-visible `https://t.me/s/<username>` feeds and preserve post URLs, dates, channel identity, excerpts, and the observed collection boundary. For groups, inspect only browser-visible history.
4. Expand candidates from observed public `t.me` links, forwards, mentions, and linked discussion groups. Re-run open-web discovery only when it addresses an identified coverage gap.
5. Store collected public material with `source_scope: public_web`, separate from `my_export`, and recheck saved candidates rather than restarting discovery.

Do not treat this as a complete Telegram index. Public-preview availability, web indexing, deletion, language, and source discovery limit coverage; record those limits.

For the user's own requested chat or channel history, use `telegram-export-analysis` on an official Telegram Desktop JSON export of the exact requested chats. Report an unavailable private chat or channel as an access limitation.
