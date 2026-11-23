#!/usr/bin/env python3
"""Parse an already retrieved public Telegram Discussion Widget offline.

Usage:
  python3 telegram_discussion_parser.py --input capture.json \
    --source-url https://t.me/channel/123

Input is raw HTML, a Firecrawl JSON object containing rawHtml/html, or the
same object under data. rawHtml is preferred. No requests are made. Output
contains observed public comment fields, media type markers, and explicit
coverage; it never contains peer hashes, avatars, or arbitrary page metadata.

snapshot_complete means the unique message count agrees with the header and
there is no visible more control in this capture. It says nothing about
deleted, private, historical, or subsequently added comments. Media contents
are not downloaded or interpreted. Missing DOM evidence remains unknown.
"""

import argparse
from datetime import datetime
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit


VOID_TAGS = set("area base br col embed hr img input link meta param source track wbr".split())
QUOTE_CLASSES = {"js-reply_tpl", "js-message_reply_text", "js-reply_to", "tgme_widget_message_reply"}
TELEGRAM_HOSTS = {"t.me", "telegram.me", "telegram.dog"}


class Node:
    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.parent = tag, attrs or {}, parent
        self.classes = set(self.attrs.get("class", "").split())
        self.children = []


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        raw = dict(attrs)
        # Intentionally retain only structural/public fields, not peer hashes,
        # image sources, scripts, form data, or inline media URLs.
        keep = {k: v or "" for k, v in raw.items() if k in {
            "class", "href", "datetime", "data-post-id", "data-reply-to", "rel",
            "property", "content", "id",
        }}
        style = (raw.get("style") or "").replace(" ", "").lower()
        if "hidden" in raw or raw.get("aria-hidden") == "true" or "display:none" in style:
            keep["_hidden"] = "1"
        node = Node(tag, keep, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.stack[-1].tag not in {"script", "style"}:
            self.stack[-1].children.append(data)


def walk(node, exclude=frozenset()):
    for child in node.children:
        if isinstance(child, Node) and child.tag not in {"script", "style", "template"}:
            if not child.classes.intersection(exclude):
                yield child
                yield from walk(child, exclude)


def text_of(node):
    def collect(current):
        if current.tag in {"script", "style", "svg", "template"}:
            return ""
        if current.tag == "br":
            return "\n"
        value = "".join(collect(c) if isinstance(c, Node) else c for c in current.children)
        return "\n" + value + "\n" if current.tag in {"p", "li", "blockquote", "pre"} else value
    return "\n".join(re.sub(r"[^\S\n]+", " ", line).strip() for line in collect(node).splitlines()).strip()


def post_root(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in TELEGRAM_HOSTS:
            return None
        if parsed.username or parsed.password or parsed.port:
            return None
        match = re.fullmatch(r"/(?:s/)?([A-Za-z0-9_]+)/([1-9][0-9]*)/?", parsed.path)
        if match:
            return "https://t.me/" + match[1].lower() + "/" + match[2]
    except (ValueError, TypeError):
        pass
    return None


def public_author_url(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme in {"http", "https"} and parsed.hostname in TELEGRAM_HOSTS:
            if not (parsed.username or parsed.password or parsed.port):
                if re.fullmatch(r"/[A-Za-z0-9_]+/?", parsed.path):
                    return "https://t.me" + parsed.path.rstrip("/")
    except (ValueError, TypeError):
        pass
    return None


def unpack(payload):
    if isinstance(payload, str):
        if payload.lstrip().startswith("<"):
            return payload, {}
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return "", {}
    for _ in range(4):
        if not isinstance(payload, dict):
            break
        for key in ("rawHtml", "html"):
            if isinstance(payload.get(key), str) and payload[key].strip():
                metadata = payload.get("metadata", {})
                return payload[key], metadata if isinstance(metadata, dict) else {}
        payload = payload.get("data")
    return "", {}


def is_hidden(node):
    while node is not None:
        if node.attrs.get("_hidden") or node.classes.intersection({"hide", "hidden"}):
            return True
        node = node.parent
    return False


def parse_discussion(payload, source_url):
    """Return JSON-serializable evidence without fetching or executing anything."""
    source = post_root(source_url)
    result = {
        "source_url": source, "reported_count": None, "comments": [],
        "unique_count": 0, "duplicate_count": 0, "has_more": None,
        "identity_status": "ambiguous",
        "coverage": {"status": "unsupported", "scope": "current_public_widget_snapshot",
                     "content_status": "unknown", "reasons": []},
    }
    reasons = result["coverage"]["reasons"]

    def finish(status, reason=None):
        result["coverage"]["status"] = status
        if reason and reason not in reasons:
            reasons.append(reason)
        return result

    if not source:
        return finish("invalid", "invalid_public_source_url")
    html, metadata = unpack(payload)
    if not html:
        return finish("unsupported", "html_missing")
    document = Document(html).root
    nodes = list(walk(document))
    messages = [n for n in nodes if "js-widget_message" in n.classes and "data-post-id" in n.attrs]
    headers = [n for n in nodes if "tgme_post_discussion_header" in n.classes]
    widget = any("body_widget_discussion" in n.classes or "js-message_history" in n.classes for n in nodes)

    root_urls = [metadata[k] for k in ("sourceURL", "url") if isinstance(metadata.get(k), str)]
    for header in headers:
        root_urls.extend(n.attrs["href"] for n in walk(header) if n.tag == "a" and n.attrs.get("href"))
    for node in nodes:
        if node.tag == "link" and "canonical" in node.attrs.get("rel", "").split():
            root_urls.append(node.attrs.get("href", ""))
        elif node.tag == "meta" and node.attrs.get("property") == "og:url":
            root_urls.append(node.attrs.get("content", ""))
        elif node.classes.intersection({"tgme_widget_message_date", "message_media_view_in_telegram"}):
            root_urls.append(node.attrs.get("href", ""))
    observed_roots = {post_root(url) for url in root_urls} - {None}
    if observed_roots - {source}:
        result["identity_status"] = "mismatch"
        return finish("invalid", "source_root_mismatch")
    result["identity_status"] = "verified" if observed_roots else "ambiguous"
    for url in root_urls:
        if post_root(url) == source:
            query = parse_qsl(urlsplit(url).query)
            if ("embed", "1") in query and ("discussion", "1") in query:
                safe = [(k, v) for k, v in query if k in {"embed", "discussion", "comments_limit"} and v.isdigit()]
                result["widget_url"] = source + "?" + urlencode(safe)
                break

    if not widget and not messages:
        if any("tgme_page" in n.classes for n in nodes):
            return finish("unavailable", "landing_page_not_comments")
        return finish("unavailable", "comment_widget_unavailable")

    counts = set()
    for header in headers:
        for node in walk(header):
            if "js-header" not in node.classes:
                continue
            label = text_of(node).lower()
            match = re.fullmatch(r"([0-9][0-9,\s]*) comments?", label)
            if match:
                counts.add(int(re.sub(r"[,\s]", "", match[1])))
            elif label == "no comments":
                counts.add(0)
    if len(counts) == 1:
        result["reported_count"] = counts.pop()
    elif len(counts) > 1:
        return finish("invalid", "reported_count_conflict")
    else:
        reasons.append("reported_count_missing")
    result["has_more"] = any("js-messages_more" in n.classes and not is_hidden(n) for n in nodes)

    by_id = {}
    content_partial = False
    conflict = False
    for message in messages:
        comment_id = message.attrs["data-post-id"]
        if not re.fullmatch(r"[1-9][0-9]*", comment_id):
            reasons.append("invalid_comment_id")
            conflict = True
            continue
        bubble = next((n for n in walk(message) if "tgme_widget_message_bubble" in n.classes), None)
        if bubble is None:
            reasons.append("comment_bubble_missing:" + comment_id)
            content_partial = True
            continue
        body_nodes = list(walk(bubble, QUOTE_CLASSES))
        authors = [n for n in body_nodes if "tgme_widget_message_author_name" in n.classes]
        author = authors[0] if authors else None
        bodies = [n for n in body_nodes if "js-message_text" in n.classes]
        comment = {
            "id": comment_id,
            "author": text_of(author) if author else None,
            "author_url": public_author_url(author.attrs.get("href", "")) if author else None,
            "published_at": None, "comment_url": None,
            "text": "\n".join(text_of(n) for n in bodies), "attachments": [],
        }
        date_links = [n for n in body_nodes if "tgme_widget_message_date" in n.classes]
        for date_link in date_links:
            href = date_link.attrs.get("href", "")
            try:
                query = dict(parse_qsl(urlsplit(href).query))
            except ValueError:
                query = {}
            if post_root(href) == source and query.get("comment") == comment_id:
                # Keep the observed permalink's identity, stripping unrelated parameters.
                comment["comment_url"] = post_root(href) + "?" + urlencode({"comment": query["comment"]})
            elif query.get("comment") and query["comment"] != comment_id:
                conflict = True
                reasons.append("comment_permalink_id_mismatch:" + comment_id)
            for node in walk(date_link):
                if node.tag == "time" and node.attrs.get("datetime"):
                    value = node.attrs["datetime"]
                    try:
                        if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None:
                            comment["published_at"] = value
                    except ValueError:
                        pass
        if not comment["comment_url"]:
            result["identity_status"] = "ambiguous"
            reasons.append("comment_permalink_missing:" + comment_id)
        if not comment["published_at"] or author is None:
            content_partial = True
            reasons.append("comment_metadata_incomplete:" + comment_id)

        types = set()
        for node in body_nodes:
            if node.tag == "tg-emoji":
                types.add("custom_emoji")
            for marker, media_type in (
                ("tgme_widget_message_sticker_wrap", "sticker"),
                ("tgme_widget_message_photo_wrap", "photo"),
                ("tgme_widget_message_video_wrap", "video"),
                ("tgme_widget_message_voice", "voice"),
                ("tgme_widget_message_document_wrap", "document"),
            ):
                if marker in node.classes:
                    types.add(media_type)
        notices = list(dict.fromkeys(text_of(n) for n in body_nodes if "message_media_not_supported_label" in n.classes))
        if notices:
            comment["unsupported_notices"] = notices
            if not types:
                types.add("unsupported_media")
        comment["attachments"] = sorted(types)
        if types or notices or not bodies:
            content_partial = True
        if not bodies and not types:
            reasons.append("comment_body_missing:" + comment_id)

        replies = {
            n.attrs.get("data-reply-to", "") for n in walk(bubble, {"js-reply_tpl"})
            if "js-reply_to" in n.classes and re.fullmatch(r"[1-9][0-9]*", n.attrs.get("data-reply-to", ""))
        }
        if len(replies) == 1:
            comment["reply_to_id"] = replies.pop()
        elif len(replies) > 1:
            content_partial = True
            reasons.append("reply_relationship_ambiguous:" + comment_id)
        if comment_id in by_id:
            result["duplicate_count"] += 1
            if by_id[comment_id] != comment:
                conflict = True
                reasons.append("conflicting_duplicate_id:" + comment_id)
        else:
            by_id[comment_id] = comment

    result["comments"] = list(by_id.values())
    result["unique_count"] = len(by_id)
    result["coverage"]["content_status"] = "partial" if content_partial else "text_extracted"
    reasons[:] = dict.fromkeys(reasons)
    count = result["reported_count"]
    if conflict:
        return finish("invalid", "conflicting_comment_evidence")
    if not messages and count != 0:
        return finish("unavailable", "no_comment_nodes")
    if count is not None and result["unique_count"] > count:
        return finish("invalid", "unique_count_exceeds_reported_count")
    if result["identity_status"] != "verified":
        return finish("unknown", "source_identity_ambiguous")
    if count is None:
        return finish("unknown")
    if result["has_more"] or result["unique_count"] < count:
        return finish("partial", "more_comments_not_captured")
    return finish("snapshot_complete")


def main():
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--input", required=True, help="Saved raw HTML or Firecrawl JSON; '-' reads stdin")
    arguments.add_argument("--source-url", required=True, help="Expected public Telegram channel post URL")
    options = arguments.parse_args()
    try:
        payload = sys.stdin.read() if options.input == "-" else Path(options.input).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        arguments.exit(2, "Cannot read input: " + str(error) + "\n")
    result = parse_discussion(payload, options.source_url)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["coverage"]["status"] == "invalid" else 0


if __name__ == "__main__":
    sys.exit(main())
