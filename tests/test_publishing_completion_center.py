"""Regression tests for the read-only publishing completion center."""
import json
import tempfile
import unittest
from pathlib import Path
from publishing_completion import build_completion_report, validate_pdf, write_report_no_clobber

def make_pdf(path: Path, pages: int = 2) -> None:
    body = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n"
    for number in range(pages):
        body += f"{number + 2} 0 obj << /Type /Page /Parent 1 0 R >> endobj\n".encode()
    path.write_bytes(body + b"x" * 100 + b"\n%%EOF\n")

class PublishingCompletionTests(unittest.TestCase):
    def test_rejects_missing_and_truncated_pdf(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(validate_pdf(Path(temp) / "missing.pdf")["status"], "BLOCKED")
            broken = Path(temp) / "broken.pdf"
            broken.write_bytes(b"%PDF-1.4 " + b"x" * 200)
            result = validate_pdf(broken)
            self.assertFalse(result["valid"])
            self.assertTrue(any("end-of-file" in error for error in result["errors"]))

    def test_valid_signature_and_eof_are_basic_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "Book_MASTER.pdf"
            make_pdf(path)
            result = validate_pdf(path)
            self.assertTrue(result["valid"])
            self.assertEqual(result["status"], "BASIC_CHECK_PASS")
            self.assertEqual(result["page_marker_count"], 2)

    def test_missing_master_and_package_files_are_actionable(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "Book"
            project.mkdir()
            report = build_completion_report(project, profiles={
                "Sample": {"folder": "SAMPLE", "required_any": [["interior.pdf"]], "listing_any": []}
            })
            self.assertEqual(report["overall_status"], "BLOCKED")
            self.assertTrue(any("master PDF" in row["action"] for row in report["actions"]))
            self.assertEqual(report["platforms"]["Sample"]["status"], "BLOCKED")
            self.assertTrue(report["platforms"]["Sample"]["missing_requirements"])

    def test_report_lists_exact_paths_and_never_claims_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "Book"
            master_dir = project / "MASTER"
            master_dir.mkdir(parents=True)
            make_pdf(master_dir / "Book_MASTER.pdf")
            platform_dir = project / "PLATFORMS" / "Sample"
            platform_dir.mkdir(parents=True)
            (platform_dir / "interior.pdf").write_bytes(b"dummy")
            listing = project / "MARKETING" / "LISTINGS"
            listing.mkdir(parents=True)
            (listing / "metadata.json").write_text("{}", encoding="utf-8")
            report = build_completion_report(project, profiles={
                "Sample": {"folder": "Sample", "required_any": [["interior.pdf"]], "listing_any": [["metadata.json"]]}
            })
            row = report["platforms"]["Sample"]
            self.assertEqual(row["status"], "NEEDS_REVIEW")
            # Windows runners may expose the temp root through a DOS 8.3 alias (RUNNER~1)\n            # while the module resolves it through the long name (runneradmin). Assert the\n            # stable project-relative suffix rather than comparing OS-specific temp prefixes.\n            self.assertTrue(row["package_folder"].replace("\\\\", "/").casefold().endswith("/platforms/sample"))
            self.assertFalse(row["upload_confirmed"])
            self.assertFalse(report["uploaded_or_published"])

    def test_report_writer_never_overwrites_existing_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "Book"
            project.mkdir()
            first = write_report_no_clobber(project, {"id": 1})
            first.write_text('{"keep": true}\n', encoding="utf-8")
            second = write_report_no_clobber(project, {"id": 2})
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(first.read_text(encoding="utf-8")), {"keep": True})
            self.assertEqual(json.loads(second.read_text(encoding="utf-8")), {"id": 2})

if __name__ == "__main__":
    unittest.main(verbosity=2)
