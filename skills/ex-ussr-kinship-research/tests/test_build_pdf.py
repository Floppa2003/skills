"""PDF preflight accepts ordinary report prose and still rejects broken/active HTML."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.build_pdf import inspect_html

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_pdf.py"
PROSE = (
    "The hypothesis remains unresolved. The birth date is corroborated by a "
    "single-source extract, while another account is contradicted. "
    "Archive call number A-1234; citation C-0002; IG-family; artifact_id."
)


class PdfPreflight(unittest.TestCase):
    def test_english_prose_and_identifiers_are_allowed(self):
        problems, missing = inspect_html(f"<p>{PROSE}</p>", Path("report.html"))
        self.assertEqual((problems, missing), ([], []))

    def test_unfilled_placeholders_are_rejected(self):
        for source in ("<p><Name></p>", "<p><ФИО></p>", "<p>&lt;" + "x" * 400 + "&gt;</p>"):
            with self.subTest(source=source[:30]):
                problems, _ = inspect_html(source, Path("report.html"))
                self.assertTrue(problems)

    def test_active_html_and_unavailable_images_are_rejected(self):
        for source in (
            "<script>alert(1)</script>",
            '<a href="javascript:alert(1)">source</a>',
            '<img src="https://example.org/photo.jpg">',
            '<img src="missing-photo.jpg">',
        ):
            with self.subTest(source=source):
                problems, missing = inspect_html(source, Path("report.html"))
                self.assertTrue(problems or missing)

    def test_cli_accepts_report_and_legacy_flag_without_safety_bypass(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "report.html"
            for extra in ([], ["--allow-service-ids"]):
                report.write_text(f"<p>{PROSE}</p>", encoding="utf-8")
                command = [sys.executable, str(SCRIPT), "--html", str(report), "--check-only", *extra]
                self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
                report.write_text("<script>forbidden()</script>", encoding="utf-8")
                self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)


if __name__ == "__main__":
    unittest.main()
