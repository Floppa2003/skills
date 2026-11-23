"""Offline regressions using real, externally supplied Telegram captures.

No HTML fixtures are bundled: captures contain transient peer hashes and avatars.
Run with Python's standard library only:

  python3 evals/test_telegram_discussion_parser.py \
    --full-fixture /path/target-widget-limit20.json \
    --initial-fixture /path/target-widget-initial.json \
    --landing-fixture /path/album_discussion.json \
    --reply-fixture /path/post-8011.json

The full and initial captures are of https://t.me/mironovanastasiia/7833,
with 13/13 and 5/13 real message nodes respectively. The landing capture is
the ordinary ?comment=1 page for the same post. Mutations below remove or
duplicate existing evidence; they do not invent comments or reply edges.
The reply capture is the real discussion widget for /mironovanastasiia/8011.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/telegram_discussion_parser.py"
SOURCE = "https://t.me/mironovanastasiia/7833"
FIXTURES = {}


class TelegramDiscussionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name in ("full", "initial", "landing", "reply"):
            path = FIXTURES.get(name) or os.environ.get(
                "TG_DISCUSSION_" + name.upper() + "_FIXTURE"
            )
            if not path:
                raise RuntimeError("Provide --%s-fixture with a real capture" % name)
            setattr(cls, name, json.loads(Path(path).read_text(encoding="utf-8")))
        cls.full_path = FIXTURES.get("full") or os.environ["TG_DISCUSSION_FULL_FIXTURE"]

    def parse(self, payload, source=SOURCE):
        # A missing implementation is an assertion failure, not a misleading
        # import failure. This was the observed RED state before implementation.
        self.assertTrue(SCRIPT.is_file(), "Offline Telegram parser is not implemented")
        spec = importlib.util.spec_from_file_location("telegram_discussion_parser", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.parse_discussion(payload, source)

    def test_full_capture_is_complete_only_for_the_current_snapshot(self):
        result = self.parse(self.full)
        self.assertEqual(result["reported_count"], 13)
        self.assertEqual(result["unique_count"], 13)
        self.assertFalse(result["has_more"])
        self.assertEqual(result["coverage"]["status"], "snapshot_complete")
        self.assertEqual(result["coverage"]["scope"], "current_public_widget_snapshot")

    def test_initial_capture_reports_five_of_thirteen_and_more_available(self):
        result = self.parse(self.initial)
        self.assertEqual(result["reported_count"], 13)
        self.assertEqual(result["unique_count"], 5)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["coverage"]["status"], "partial")

    def test_partial_coverage_explains_missing_comments(self):
        result = self.parse(self.initial)
        self.assertIn("more_comments_not_captured", result["coverage"]["reasons"])

    def test_landing_page_is_unavailable_not_an_empty_complete_thread(self):
        result = self.parse(self.landing)
        self.assertEqual(result["coverage"]["status"], "unavailable")
        self.assertIn("landing_page_not_comments", result["coverage"]["reasons"])
        self.assertIsNone(result["reported_count"])
        self.assertEqual(result["unique_count"], 0)
        self.assertIsNone(result["has_more"])

    def test_body_text_excludes_reply_templates(self):
        comments = {c["id"]: c for c in self.parse(self.full)["comments"]}
        self.assertEqual(comments["81131"]["text"], "Настя я тебя обожаю 💔🤌🏻")
        self.assertEqual(comments["81133"]["text"], "я прочла марципановые яйца, это о чем говорит?🧐")
        self.assertEqual(len(comments), 13)

    def test_datetime_attribute_overrides_localized_display_date(self):
        comments = {c["id"]: c for c in self.parse(self.full)["comments"]}
        self.assertEqual(comments["81249"]["published_at"], "2026-05-16T01:24:40+00:00")
        self.assertEqual(comments["81249"]["comment_url"], SOURCE + "?comment=81249")

    def test_bubble_group_identity_is_preserved_without_person_attribution(self):
        comments = {c["id"]: c for c in self.parse(self.full)["comments"]}
        self.assertEqual(comments["81143"]["author"], "нравственные стержни")
        self.assertEqual(comments["81143"]["author_url"], "https://t.me/acunapotato")

    def test_reply_templates_do_not_invent_reply_relationships(self):
        comments = self.parse(self.full)["comments"]
        self.assertTrue(comments)
        self.assertTrue(all("reply_to_id" not in c for c in comments))

    def test_explicit_reply_id_is_preserved_without_copying_quote_as_body(self):
        result = self.parse(self.reply, "https://t.me/mironovanastasiia/8011")
        comments = {c["id"]: c for c in result["comments"]}
        self.assertEqual(result["unique_count"], 9)
        self.assertEqual(comments["82598"]["reply_to_id"], "82597")
        self.assertEqual(comments["82610"]["reply_to_id"], "82597")
        self.assertEqual(comments["82598"]["author"], "LESYA MAGIC")
        self.assertNotEqual(comments["82598"]["text"], comments["82597"]["text"])

    def test_author_without_public_link_keeps_display_name_only(self):
        result = self.parse(self.reply, "https://t.me/mironovanastasiia/8011")
        comments = {c["id"]: c for c in result["comments"]}
        self.assertEqual(comments["82594"]["author"], "Kenneth Bhalla")
        self.assertIsNone(comments["82594"]["author_url"])

    def test_sticker_has_media_marker_without_template_text_or_media_urls(self):
        result = self.parse(self.full)
        comments = {c["id"]: c for c in result["comments"]}
        sticker = comments["81144"]
        self.assertEqual(sticker["text"], "")
        self.assertIn("sticker", sticker["attachments"])
        self.assertTrue(sticker["unsupported_notices"])
        self.assertEqual(result["coverage"]["content_status"], "partial")

    def test_source_mismatch_rejects_other_thread_records(self):
        result = self.parse(self.full, "https://t.me/mironovanastasiia/9999")
        self.assertEqual(result["coverage"]["status"], "invalid")
        self.assertEqual(result["comments"], [])
        self.assertIn("source_root_mismatch", result["coverage"]["reasons"])

    def test_one_wrong_comment_root_invalidates_the_capture(self):
        html = self.full["rawHtml"].replace(
            SOURCE + "?comment=81249", SOURCE.replace("7833", "9999") + "?comment=81249"
        )
        result = self.parse(html)
        self.assertEqual(result["coverage"]["status"], "invalid")
        self.assertEqual(result["comments"], [])

    def test_missing_count_does_not_become_complete(self):
        html = self.full["rawHtml"].replace('class="js-header"', 'class="removed-count"')
        result = self.parse(html)
        self.assertIsNone(result["reported_count"])
        self.assertEqual(result["unique_count"], 13)
        self.assertEqual(result["coverage"]["status"], "unknown")
        self.assertIn("reported_count_missing", result["coverage"]["reasons"])

    def test_missing_permalink_identity_is_reported(self):
        html = self.full["rawHtml"].replace(SOURCE, "")
        result = self.parse(html)
        self.assertEqual(result["coverage"]["status"], "unknown")
        self.assertEqual(result["identity_status"], "ambiguous")

    def test_duplicate_message_ids_do_not_inflate_count(self):
        result = self.parse(self.full["rawHtml"] + self.full["rawHtml"])
        self.assertEqual(result["unique_count"], 13)
        self.assertEqual(result["duplicate_count"], 13)
        self.assertEqual(result["coverage"]["status"], "snapshot_complete")

    def test_conflicting_duplicate_ids_do_not_become_complete(self):
        changed = self.full["rawHtml"].replace("Настя я тебя обожаю", "", 2)
        result = self.parse(self.full["rawHtml"] + changed)
        self.assertEqual(result["unique_count"], 13)
        self.assertEqual(result["coverage"]["status"], "invalid")
        self.assertIn("conflicting_duplicate_id:81131", result["coverage"]["reasons"])

    def test_malformed_permalink_is_reported_without_crashing(self):
        html = self.full["rawHtml"].replace(SOURCE + "?comment=81249", "https://[")
        result = self.parse(html)
        self.assertEqual(result["identity_status"], "ambiguous")
        self.assertEqual(result["coverage"]["status"], "unknown")

    def test_raw_html_and_firecrawl_data_envelope_are_supported(self):
        raw = self.parse(self.full["rawHtml"])
        nested = self.parse({"success": True, "data": self.full})
        self.assertEqual(raw["comments"], nested["comments"])
        self.assertEqual(nested["widget_url"], SOURCE + "?embed=1&discussion=1&comments_limit=20")

    def test_tokens_avatars_and_provider_metadata_do_not_escape(self):
        result = self.parse(self.full)
        encoded = json.dumps(result, ensure_ascii=False)
        for value in re.findall(r'data-peer-hash="([^"]+)"', self.full["rawHtml"]):
            if value:
                self.assertNotIn(value, encoded)
        for forbidden in ("data-peer", "cdn4.telesco.pe", "data:image", "conversationId", "scrapeId"):
            self.assertNotIn(forbidden, encoded)

    def test_cli_reads_real_json_and_emits_json(self):
        self.assertTrue(SCRIPT.is_file(), "Offline Telegram parser is not implemented")
        process = subprocess.run(
            [sys.executable, str(SCRIPT), "--input", str(self.full_path), "--source-url", SOURCE],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["unique_count"], 13)
        self.assertEqual(result["coverage"]["status"], "snapshot_complete")


if __name__ == "__main__":
    arguments = argparse.ArgumentParser(description=__doc__)
    for name in ("full", "initial", "landing", "reply"):
        arguments.add_argument("--" + name + "-fixture", required=True)
    known, remaining = arguments.parse_known_args()
    FIXTURES.update({name: getattr(known, name + "_fixture") for name in ("full", "initial", "landing", "reply")})
    unittest.main(argv=[sys.argv[0]] + remaining)
