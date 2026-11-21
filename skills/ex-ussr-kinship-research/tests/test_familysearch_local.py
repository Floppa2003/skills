"""Synthetic tests for local evidence analysis and GWAR search contracts."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_source_search import FakeClient, SCRIPTS, sample_fragment

import familysearch as fs
import gwar
import register_search
import research_common as common
from familysearch import compile_patterns


class LocalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.fragment = self.directory / "fragment.json"
        self.image_url = "https://www.familysearch.org/ark:/61903/3:1:TEST-IMAGE"


    def snapshot(self, **changes):
        return {"url": self.image_url, "scope": {"frame": 42, "description": "one relevant row"},
                "captured_at": "2026-10-26T12:00:00Z", "rows": [], **changes}


    def init_case(self):
        case = self.directory / "case"
        initialized = subprocess.run([sys.executable, str(SCRIPTS / "init_case.py"), "--case-dir", str(case),
                                      "--research-question", "Проверить запись"], capture_output=True, encoding="utf-8")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        return case


    def test_targeted_fragment_matches_relatives_without_network_or_invented_ids(self):
        row = {"url": self.image_url, "observed_id": "DGS:42:7", "name": "Иван Иванов",
               "text": "Primary Иван Иванов; Spouse Мария Петрова",
               "people": [{"name": "Иван Иванов", "label": "Primary"},
                          {"name": "Мария Петрова", "label": "Spouse"}]}
        common.save_json(self.fragment, self.snapshot(rows=[row]))
        with patch.object(common, "SourceClient", side_effect=AssertionError("network client")), \
                patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network request")):
            result = fs.browser_import([self.fragment, self.fragment], compile_patterns(surnames=["Петрова"]))
        self.assertEqual(result["coverage"]["observed_rows"], 1)
        self.assertFalse(result["coverage"]["complete"])
        self.assertEqual(result["hits"]["Петрова"][0]["pid"], "observed-2")
        self.assertFalse(result["hits"]["Петрова"][0]["principal"])
        record = result["candidates"][0]["record"]
        self.assertEqual(record["raw"]["browser_row"], row)
        self.assertNotIn("rels", record)
        output = self.directory / "analysis.json"
        common.save_json(output, result)
        case = self.init_case()
        protected = {name: (case / name).read_bytes() for name in
                     ("person-register.csv", "claims-register.csv", "relationship-register.csv")}
        self.assertEqual(register_search.register(case, output, "goal")["added_artifacts"], 1)
        self.assertEqual(register_search.register(case, output, "goal")["added_artifacts"], 0)
        fields, rows = register_search.read_register(case / "artifact-register.csv", "artifact_id")
        reference = json.loads(rows[0]["archival_reference"])
        self.assertEqual(reference["RID"], "")
        self.assertEqual(reference["local_observation_id"], "browser-observation:DGS:42:7")
        self.assertEqual(rows[0]["source_url_or_path"], self.image_url)
        self.assertEqual(rows[0]["independence_group"], "")
        for name, content in protected.items():
            self.assertEqual((case / name).read_bytes(), content)
        audit = subprocess.run([sys.executable, str(SCRIPTS / "audit_evidence.py"), "--case-dir", str(case), "--json"],
                               capture_output=True, encoding="utf-8")
        self.assertEqual(audit.returncode, 0, audit.stdout + audit.stderr)
        self.assertEqual(json.loads(audit.stdout)["errors"], [])


    def test_empty_browser_fragment_keeps_unresolved_coverage(self):
        common.save_json(self.fragment, self.snapshot())
        result = fs.browser_import([self.fragment], [])
        self.assertEqual(result["coverage"]["unresolved_pages"], [self.image_url])
        self.assertEqual(result["coverage"]["not_indexed_pages"], [])
        self.assertFalse(result["coverage"]["complete"])
        output = self.directory / "analysis.json"
        common.save_json(output, result)
        self.assertEqual(register_search.register(self.init_case(), output, "goal")["result_status"], "partial")


    def test_not_indexed_requires_explicit_source_evidence_and_is_not_book_coverage(self):
        common.save_json(self.fragment, self.snapshot(index_state="not-indexed"))
        with self.assertRaises(common.SourceError):
            fs.browser_import([self.fragment], [])
        common.save_json(self.fragment, self.snapshot(index_state="not-indexed", state_evidence="This image has not been indexed."))
        result = fs.browser_import([self.fragment], [])
        self.assertEqual(result["coverage"]["not_indexed_pages"], [self.image_url])
        self.assertFalse(result["coverage"]["complete"])


    def test_raw_empty_json_and_loading_rows_cannot_be_successful_observations(self):
        for snapshot in ({}, self.snapshot(loading=True, rows=[{"name": "Иван", "text": "Иван"}])):
            with self.subTest(snapshot=snapshot):
                common.save_json(self.fragment, snapshot)
                with self.assertRaises(common.SourceError):
                    fs.browser_import([self.fragment], [])
        common.save_json(self.fragment, self.snapshot(loading=True))
        self.assertEqual(fs.browser_import([self.fragment], [])["coverage"]["unresolved_pages"], [self.image_url])


    def test_unresolved_coverage_cannot_be_imported_as_not_found(self):
        output = self.directory / "analysis.json"
        common.save_json(output, {"source": "familysearch", "candidates": [],
                                  "coverage": {"complete": True, "unresolved_pages": [self.image_url]}})
        self.assertEqual(register_search.register(self.init_case(), output, "goal")["result_status"], "partial")

    def test_all_observed_names_and_text_are_searchable_locally(self):
        snapshot = sample_fragment()
        common.save_json(self.fragment, snapshot)
        patterns = compile_patterns({"surnames": {"latin": "Sidorov", "cyrillic": r"\bПетрова\b"}})
        with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network request")):
            result = fs.browser_import([self.fragment], patterns)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertFalse(result["hits"]["latin"][0]["principal"])
        self.assertFalse(result["hits"]["cyrillic"][0]["principal"])
        self.assertEqual(result["candidates"][0]["record"]["raw"]["browser_row"], snapshot["rows"][0])

    def test_minimal_fragment_searches_name_and_keeps_text_only_hits_unassigned(self):
        row = {"url": "https://www.familysearch.org/ark:/61903/1:1:TEST-ROW",
               "name": "Иван Петров", "text": "Birth, 1900. Parent: Мария Сидорова."}
        common.save_json(self.fragment, self.snapshot(rows=[row]))
        result = fs.browser_import([self.fragment], compile_patterns(surnames=["Петров", "Сидорова"]))
        self.assertEqual(len(result["candidates"]), 1)
        principal = result["hits"]["Петров"][0]
        self.assertEqual(principal["pid"], "principal")
        self.assertEqual(principal["name"], row["name"])
        self.assertTrue(principal["principal"])
        text_only = result["hits"]["Сидорова"][0]
        self.assertIsNone(text_only["pid"])
        self.assertIsNone(text_only["principal"])
        self.assertFalse(result["coverage"]["complete"])

    def test_source_hash_describes_original_file_bytes(self):
        common.save_json(self.fragment, sample_fragment())
        result = fs.browser_import([self.fragment], [])
        self.assertEqual(result["inputs"], [{"path": str(self.fragment.resolve()),
                                           "sha256": hashlib.sha256(self.fragment.read_bytes()).hexdigest()}])

    def test_invalid_search_configuration_fails_before_analysis(self):
        for config in ({"surnames": []}, {"surnames": {"name": "["}}, {"unknown": True}):
            with self.subTest(config=config), self.assertRaises(common.SourceError):
                compile_patterns(config)
        with self.assertRaises(common.SourceError):
            compile_patterns(surnames=[r"\p{L}"])

    def test_cli_writes_matches_with_partial_coverage(self):
        common.save_json(self.fragment, sample_fragment())
        output = self.directory / "analysis.json"
        result = subprocess.run([sys.executable, str(SCRIPTS / "familysearch.py"), "browser-import", str(self.fragment),
                                 "--surnames", "Sidorov", "--out", str(output)], capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = common.read_json(output)
        self.assertEqual(len(data["candidates"]), 1)
        self.assertFalse(data["coverage"]["complete"])

    def test_blocked_and_unresolved_pages_keep_distinct_states(self):
        common.save_json(self.fragment, self.snapshot(index_state="blocked", state_evidence="Access unavailable"))
        result = fs.browser_import([self.fragment], [])
        self.assertEqual(result["coverage"]["blocked_pages"], [self.image_url])
        self.assertEqual(result["coverage"]["unresolved_pages"], [])
        self.assertFalse(result["coverage"]["complete"])


class GwarContractTests(unittest.TestCase):
    def test_volost_and_settlement_cli_use_distinct_source_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient(lambda path, body, as_json: "public page" if not as_json else {"hits": {"total": 0, "hits": []}})
            for command, field, value in ((["volost", "--volost", "Условная волость"], "birth_place_volost", "Условная волость"),
                                          (["search", "--birth-place", "Условное село"], "birth_place", "Условное село")):
                output = Path(directory) / (field + ".json")
                with patch.object(gwar, "source_client", return_value=client):
                    self.assertEqual(gwar.main([*command, "--gubernia", "Условная губерния", "--out", str(output)]), 0)
                fields = client.calls[-1][1]["queryFields"]
                self.assertEqual(fields, {field: value, "birth_place_gubernia": "Условная губерния"})
                self.assertEqual(common.read_json(output)["query"], fields)


    def test_checkpoint_cannot_be_reused_for_a_different_query(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "checkpoint.json"
            client = FakeClient(lambda path, body, as_json: "public page" if not as_json else {"hits": {"total": 0, "hits": []}})
            gwar.collect(client, {"birth_place": "Условная", "birth_place_gubernia": "Губерния"}, list(gwar.KINDS.values()), 1000, output)
            before = output.read_bytes()
            calls = len(client.calls)
            with patch.object(gwar, "source_client", return_value=client), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gwar.main(["volost", "--volost", "Условная", "--gubernia", "Губерния", "--out", str(output)]), 1)
            self.assertEqual(len(client.calls), calls)
            self.assertEqual(output.read_bytes(), before)


    def test_public_http_request_has_no_authorization_header(self):
        client = common.SourceClient(gwar.BASE, interval=0)
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{}'
        with patch.object(client.opener, "open", return_value=response) as opened:
            client.request("/test")
        request = opened.call_args.args[0]
        self.assertIsNone(request.get_header("Authorization"))
        self.assertIsNone(request.get_header("Cookie"))


if __name__ == "__main__":
    unittest.main()
