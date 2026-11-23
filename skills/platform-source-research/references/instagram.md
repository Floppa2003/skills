# Instagram

Apply the matching [route contract](route-contracts.md); read the sections needed for the task.

For discovery, use the relevant permitted public route. Search available account, hashtag, or place surfaces with task-relevant product, style, and location terms, then inspect the resulting posts and Reels. Bounded open-web discovery can supply additional leads.

Expand from supplied or discovered posts and Reels through visible authors, credited makers, hashtags, linked portfolios, and related work. Repeat this expansion from newly found relevant accounts and tags, checking their actual media against the task's criteria. Track already inspected accounts, tags, and posts; follow new branches that improve relevance or address a coverage gap, under the stopping conditions in [research-protocol.md](research-protocol.md).

For captions and metadata from known public post or Reel URLs, use an installed Instaloader only under the Local public social extraction contract; read [instagram-instaloader.md](instagram-instaloader.md). Use `video-transcript-downloader` only for a supported video URL, not as a profile or comment search engine.

For a public Instagram Reel video, read the original caption and hashtags, then use the available download or the ordinary [SaveClip](https://saveclip.app/ru9/instagram-reels-video-download) form under the Public media downloader contract. Preserve the canonical Reel URL rather than a temporary media/CDN URL. Verify the downloaded file decodes as video and matches the original Reel; a success label or an HTML error page with an `.mp4` extension does not confirm a download.

For photos from a public Instagram post or carousel, use the ordinary [SaveClip photo form](https://saveclip.app/ru9/instagram-photo-download) under the same Public media downloader contract. Submit the canonical post URL, choose the highest-resolution image offered by SaveClip, and download each requested image. Preserve the post URL and each image's original carousel position. Compare coverage with the source when visible and report missing or unverifiable items; photos alone do not establish complete coverage of a mixed photo/video carousel. Open the downloaded files to verify they decode as images and match the post. When a caption or metadata tool omits requested images, use this separate media-download route.

For public current Stories or saved Highlights, use the ordinary [Story Save](https://story-save.com/ru) form under the Public media downloader contract. Enter the public username, verify the returned account, select Stories or Highlights, and open the requested folders. Follow the offered photo/video download links. If browser asset export is unavailable, use a permitted download method for a link actually observed in the page; verify the downloaded media per the contract.

Preserve the canonical Instagram profile or Highlight URL, observed Highlight/story IDs, each item's position, the displayed relative date and retrieval time; retain Story Save as the retrieval provider. Keep relative dates as displayed rather than inventing exact publication or shooting dates. Apply the research protocol's coverage accounting separately to the folder catalog, returned items, saved files and inspected photos/video frames. Deduplicate by observed IDs or file hashes while retaining each folder context. A listed Highlight is not evidence that its contents were retrieved or inspected; saved Highlights do not provide arbitrary expired, unsaved Stories or a private archive.

Capability check, 2026-11-22: the public form returned photos and videos from current Stories and selected Highlights without credentials or payment. Recheck the needed capability on use; this observation does not guarantee continued availability, pricing or archive completeness.

For structured public profiles, posts, Reels, or comments, consider the Apify collection contract and [apify-social.md](apify-social.md). Instagram profile/hashtag/place discovery is not global full-text post search. Preserve carousel children and distinguish post captions from spoken words, comment counts from collected comments, and a partial view from complete history.
