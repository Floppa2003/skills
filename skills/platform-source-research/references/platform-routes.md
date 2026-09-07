# Platform Routes

Read only the section for the requested platform. This file selects and sequences routes; [route-contracts.md](route-contracts.md) is the policy source of truth. For authorization, authentication, external effects, and stop conditions, apply the matching route contract.

## Telegram

For a specific public post or public channel, use the public Telegram page with an approved browser route first. For recurring public-source collection, preserve the public URL, collection time, and access limitation in task-local artifacts.

For free discovery across public Telegram sources:

1. Search the open web with the subject, alternative formulations, language variants, and bounded `site:t.me` queries. Treat results as discovery leads, not evidence.
2. Normalize candidates to canonical public Telegram URLs. Deduplicate channels, groups, mirrors, reposts, and repeated results before collection.
3. For public channels with a username, inspect browser-visible `https://t.me/s/<username>` feeds and preserve post URLs, dates, channel identity, excerpts, and the observed collection boundary. For groups, inspect only browser-visible history.
4. Expand candidates from observed public `t.me` links, forwards, mentions, and linked discussion groups. Re-run open-web discovery only when it addresses an identified coverage gap.
5. Store collected public material with `source_scope: public_web`, separate from `my_export`, and recheck saved candidates rather than restarting discovery.

Do not treat this as a complete Telegram index. Public-preview availability, web indexing, deletion, language, and source discovery limit coverage; record those limits.

For the user's own requested chat or channel history, use `telegram-export-analysis` on an official Telegram Desktop JSON export of the exact requested chats. Report an unavailable private chat or channel as an access limitation.

## YouTube

Use `video-transcript-downloader` first for subtitles or a transcript unless the user explicitly selects another permitted source. Use the approved public browser or open-web route for discovery. Preserve video URL, channel, publication date, language, and timestamp for every quoted claim.

Consider TranscriptAPI for structured video or channel search, within-channel search, paginated channel or playlist listings, or an alternative transcript source when direct extraction is unavailable. Select it only under the YouTube TranscriptAPI contract in `route-contracts.md`; an existing key or a failed free route does not authorize its use. Load [youtube-transcriptapi.md](youtube-transcriptapi.md) only when considering or using this provider. If it is not authorized or available, retain the free route and report any access gap.

## Instagram

Start with public browser-visible posts and bounded open-web discovery. For captions and metadata from known public post or Reel URLs, use an installed Instaloader only under the Local public social extraction contract; read [instagram-instaloader.md](instagram-instaloader.md). Use `video-transcript-downloader` only for a supported video URL, not as a profile or comment search engine.

For structured public profiles, posts, Reels, or comments, consider the Apify collection contract and [apify-social.md](apify-social.md). Instagram profile/hashtag/place discovery is not global full-text post search. Preserve carousel children and distinguish post captions from spoken words, comment counts from collected comments, and a partial view from complete history.

## Threads

For individual public posts, use the public browser route; open-web searches may find candidates on `threads.com` or older `threads.net` links. Follow public redirects and preserve the canonical post identity, author, time, root post, and observed reply relationships.

For keyword/topic search, prefer the official API when the Threads API contract is satisfied; read [threads-api.md](threads-api.md). Otherwise keep public-web coverage explicit. Search permission does not establish access to every conversation, reply, or private profile.

## TikTok

Use public browser/open-web discovery first. For a supplied public video URL, reuse `video-transcript-downloader` if its installed extractor supports that operation; record failures without importing account cookies. A listed extractor is not a successful live test, and profile/hashtag extraction can fail while a single video works.

For structured keyword, hashtag, or profile collection, consider the Apify collection contract and [apify-social.md](apify-social.md). Retrieve comment text separately when needed. Preserve video URL, author, publication and retrieval times, and distinguish description/hashtags, available subtitles, and actual audio or visual evidence; missing subtitles do not authorize a new transcription service.

## RuTube And VK Video

Start with the public video page using an approved browser or crawler. Capture canonical URL, title, uploader, date, description, visible captions, and relevant timestamp. Use a downloader or transcript tool only if it explicitly supports the supplied URL and is approved for the task.

## Habr And VC.ru

Treat these as public article and comment sources. Preserve the canonical article URL and date, and distinguish article text from comments. Report comments blocked by login or lazy loading as a coverage gap.

## X/Twitter

For a specific public post, use an approved browser route first. For search, threads, profiles, or repeatable collection, use the installed `twitter` CLI with structured output and a bounded result count. Report deleted, rate-limited, or login-gated material as unavailable.

## Reddit

For public one-off reading, use an approved browser route. For search plus full comment collection, use the installed `rdt` CLI with structured output and a bounded result count. Preserve subreddit, author, post date, score when visible, and whether comments were fully collected.

## LinkedIn

For individual public pages, profiles, companies, or jobs, use the existing user-authenticated browser session. The installed `linkedin` MCP server is available for profile, company, people, and job retrieval. Treat rate limits, login walls, and anti-automation challenges as blocking conditions.

## Handoff To Analysis

For requested findings rather than raw sources, pass the collected bundle to `deep-research` or the relevant domain skill. The analysis must cite platform URLs and distinguish direct evidence from inference.
