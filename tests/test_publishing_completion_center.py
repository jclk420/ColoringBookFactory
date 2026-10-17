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
            make_pdf(platform_dir / "interior.pdf")
            listing = project / "MARKETING" / "LISTINGS"
            listing.mkdir(parents=True)
            (listing / "metadata.json").write_text("{}", encoding="utf-8")
            report = build_completion_report(project, profiles={
                "Sample": {"folder": "Sample", "required_any": [["interior.pdf"]], "listing_any": [["metadata.json"]]}
            })
            row = report["platforms"]["Sample"]
            self.assertEqual(row["status"], "NEEDS_REVIEW")
            # Windows runners may expose the temp root through a DOS 8.3 alias (RUNNER~1)
            # while the module resolves it through the long name (runneradmin). Assert the
            # stable project-relative suffix rather than comparing OS-specific temp prefixes.
            self.assertTrue(row["package_folder"].replace("\\", "/").casefold().endswith("/platforms/sample"))
            self.assertFalse(row["upload_confirmed"])
            self.assertFalse(report["uploaded_or_published"])


    def test_package_symlink_is_blocked_and_not_counted_as_a_deliverable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Book"
            master = root / "MASTER"
            master.mkdir(parents=True)
            make_pdf(master / "Book_MASTER.pdf")
            package = root / "PLATFORMS" / "Sample"
            package.mkdir(parents=True)
            outside = Path(temp) / "outside.pdf"
            make_pdf(outside)
            link = package / "interior.pdf"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlinks unavailable in this environment: {exc}")
            (package / "cover.pdf").write_bytes(b"%PDF-1.4 " + b"x" * 100 + b" %%EOF")
            listing = root / "MARKETING" / "LISTINGS" / "Sample"
            listing.mkdir(parents=True)
            (listing / "metadata.json").write_text("{\"platform\":\"Sample\",\"fields\":{\"title\":\"T\",\"author\":\"A\",\"description\":\"D\"}}", encoding="utf-8")
            report = build_completion_report(root, profiles={
                "Sample": {"folder": "Sample", "listing_folder": "Sample",
                           "required_any": [["interior.pdf"], ["cover.pdf"]],
                           "listing_any": [["metadata.json"]]}
            })
            row = report["platforms"]["Sample"]
            self.assertEqual(row["status"], "BLOCKED")
            self.assertNotIn("interior.pdf", row["package_files"])
            self.assertTrue(any("symbolic link" in error and "interior.pdf" in error
                                for error in row["validation_errors"]))
            self.assertFalse(report["uploaded_or_published"])
    def test_default_profiles_do_not_borrow_another_platforms_listing(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "Book"
            master_dir = project / "MASTER"
            master_dir.mkdir(parents=True)
            make_pdf(master_dir / "Book_MASTER.pdf")
            for folder in ("KDP", "GUMROAD", "PAYHIP", "DIGITAL"):
                package = project / "PLATFORMS" / folder
                package.mkdir(parents=True)
                make_pdf(package / "interior.pdf")
                (package / "cover.pdf").write_bytes(b"%PDF-1.4\\n" + b"x" * 100 + b"\\n%%EOF")
            listing = project / "MARKETING" / "LISTINGS" / "KDP"
            listing.mkdir(parents=True)
            (listing / "LISTING.json").write_text('{"platform":"KDP"}', encoding="utf-8")
            (listing / "LISTING.txt").write_text("KDP draft", encoding="utf-8")
            report = build_completion_report(project)
            self.assertEqual(report["platforms"]["KDP"]["status"], "NEEDS_REVIEW")
            self.assertEqual(report["platforms"]["Gumroad"]["status"], "BLOCKED")
            self.assertTrue(any("Platform-specific listing" in issue for issue in report["platforms"]["Gumroad"]["missing_requirements"]))

    def test_complete_platform_can_reach_ready_to_upload_without_claiming_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "Book"
            master_dir = project / "MASTER"
            master_dir.mkdir(parents=True)
            make_pdf(master_dir / "Book_MASTER.pdf")
            package = project / "PLATFORMS" / "Sample"
            package.mkdir(parents=True)
            make_pdf(package / "interior.pdf")
            import hashlib
            master_digest = hashlib.sha256((master_dir / "Book_MASTER.pdf").read_bytes()).hexdigest()
            interior_digest = hashlib.sha256((package / "interior.pdf").read_bytes()).hexdigest()
            (package / "PACKAGE_MANIFEST.json").write_text(json.dumps({
                "schema_version": 1, "files": ["interior.pdf", "PACKAGE_MANIFEST.json"],
                "file_hashes": {"interior.pdf": interior_digest}, "master_sha256": master_digest
            }), encoding="utf-8")
            listing = project / "MARKETING" / "LISTINGS" / "Sample"
            listing.mkdir(parents=True)
            (listing / "LISTING.json").write_text(json.dumps({
                "platform": "Sample",
                "fields": {"title": "Book", "author": "J.A.C.", "description": "A coloring book"}
            }), encoding="utf-8")
            (listing / "LISTING.txt").write_text("Title: Book", encoding="utf-8")
            report = build_completion_report(project, profiles={
                "Sample": {"folder": "Sample", "listing_folder": "Sample",
                           "required_any": [["interior.pdf"]], "listing_any": [["*.json"], ["*.txt"]]}
            })
            self.assertEqual(report["platforms"]["Sample"]["status"], "READY_TO_UPLOAD")
            self.assertEqual(report["overall_status"], "READY_TO_UPLOAD")
            self.assertFalse(report["platforms"]["Sample"]["upload_confirmed"])
            self.assertFalse(report["uploaded_or_published"])

    def test_stale_package_manifest_hash_blocks_readiness(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "Book"
            master_dir = project / "MASTER"
            master_dir.mkdir(parents=True)
            make_pdf(master_dir / "Book_MASTER.pdf")
            package = project / "PLATFORMS" / "Sample"
            package.mkdir(parents=True)
            make_pdf(package / "interior.pdf")
            listing = project / "MARKETING" / "LISTINGS" / "Sample"
            listing.mkdir(parents=True)
            (listing / "LISTING.json").write_text(json.dumps({
                "platform": "Sample", "fields": {"title": "Book", "author": "J.A.C.", "description": "A book"}
            }), encoding="utf-8")
            (listing / "LISTING.txt").write_text("Book", encoding="utf-8")
            (package / "PACKAGE_MANIFEST.json").write_text(json.dumps({
                "schema_version": 1, "files": ["interior.pdf", "PACKAGE_MANIFEST.json"],
                "file_hashes": {"interior.pdf": "0" * 64},
                "master_sha256": hashlib.sha256((master_dir / "Book_MASTER.pdf").read_bytes()).hexdigest()
            }), encoding="utf-8")
            report = build_completion_report(project, profiles={
                "Sample": {"folder": "Sample", "listing_folder": "Sample",
                           "required_any": [["interior.pdf"]], "listing_any": [["*.json"], ["*.txt"]]}
            })
            row = report["platforms"]["Sample"]
            self.assertEqual(row["status"], "BLOCKED")
            self.assertIn("interior.pdf", row["manifest_verification"]["hash_mismatches"])

    def test_missing_package_manifest_never_claims_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "Book"
            master_dir = project / "MASTER"
            master_dir.mkdir(parents=True)
            make_pdf(master_dir / "Book_MASTER.pdf")
            package = project / "PLATFORMS" / "Sample"
            package.mkdir(parents=True)
            make_pdf(package / "interior.pdf")
            listing = project / "MARKETING" / "LISTINGS" / "Sample"
            listing.mkdir(parents=True)
            (listing / "LISTING.json").write_text(json.dumps({
                "platform": "Sample", "fields": {"title": "Book", "author": "J.A.C.", "description": "A book"}
            }), encoding="utf-8")
            (listing / "LISTING.txt").write_text("Book", encoding="utf-8")
            report = build_completion_report(project, profiles={
                "Sample": {"folder": "Sample", "listing_folder": "Sample",
                           "required_any": [["interior.pdf"]], "listing_any": [["*.json"], ["*.txt"]]}
            })
            self.assertEqual(report["platforms"]["Sample"]["status"], "NEEDS_REVIEW")
            self.assertTrue(any("manifest is missing" in item for item in report["platforms"]["Sample"]["review_issues"]))

    def test_invalid_package_pdf_blocks_readiness(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "Book"
            master_dir = project / "MASTER"
            master_dir.mkdir(parents=True)
            make_pdf(master_dir / "Book_MASTER.pdf")
            package = project / "PLATFORMS" / "Sample"
            package.mkdir(parents=True)
            (package / "interior.pdf").write_bytes(b"not a pdf")
            listing = project / "MARKETING" / "LISTINGS"
            listing.mkdir(parents=True)
            (listing / "draft.json").write_text("{}", encoding="utf-8")
            report = build_completion_report(project, profiles={
                "Sample": {"folder": "Sample", "required_any": [["interior.pdf"]], "listing_any": [["*.json"]]}
            })
            self.assertEqual(report["platforms"]["Sample"]["status"], "BLOCKED")
            self.assertTrue(report["platforms"]["Sample"]["validation_errors"])


    def test_ambiguous_master_candidates_are_reported_without_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "Book"
            master_dir = project / "MASTER"
            master_dir.mkdir(parents=True)
            make_pdf(master_dir / "Book_MASTER.pdf")
            make_pdf(master_dir / "Alternate_MASTER.pdf")
            report = build_completion_report(project, profiles={"Disabled": {"enabled": False}})
            self.assertIsNone(report["source_pdf"])
            self.assertEqual(len(report["source_pdf_candidates"]), 2)
            self.assertTrue(any("Multiple master PDF candidates" in row["action"] for row in report["actions"]))

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
