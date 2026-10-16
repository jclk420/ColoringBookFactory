"""Regression tests for hardened publishing metadata and deliverable diagnostics."""
import json
import tempfile
import unittest
from pathlib import Path

from publishing_completion import build_completion_report


def make_pdf(path: Path, pages: int = 2) -> None:
    body = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n"
    for number in range(pages):
        body += f"{number + 2} 0 obj << /Type /Page /Parent 1 0 R >> endobj\n".encode()
    path.write_bytes(body + b"x" * 100 + b"\n%%EOF\n")


def make_project(root: Path) -> tuple[Path, Path, Path]:
    project = root / "Book"
    master = project / "MASTER"
    package = project / "PLATFORMS" / "Sample"
    listing = project / "MARKETING" / "LISTINGS" / "Sample"
    master.mkdir(parents=True)
    package.mkdir(parents=True)
    listing.mkdir(parents=True)
    make_pdf(master / "Book_MASTER.pdf")
    make_pdf(package / "interior.pdf")
    return project, package, listing


PROFILE = {
    "Sample": {
        "folder": "Sample",
        "listing_folder": "Sample",
        "required_any": [["interior.pdf"], ["cover.png"]],
        "listing_any": [["*.json"], ["*.txt"]],
    }
}


class PublishingReadinessHardeningTests(unittest.TestCase):
    def test_missing_deliverables_include_exact_folder_and_machine_readable_expectations(self):
        with tempfile.TemporaryDirectory() as temp:
            project, package, listing = make_project(Path(temp))
            report = build_completion_report(project, profiles=PROFILE)
            row = report["platforms"]["Sample"]
            normalized_missing = [item.replace("\\", "/").casefold()
                                  for item in row["missing_requirements"]]
            self.assertTrue(any("/platforms/sample" in item for item in normalized_missing))
            self.assertTrue(any("/marketing/listings/sample" in item for item in normalized_missing))
            self.assertEqual(len(row["expected_deliverables"]), 4)
            self.assertTrue(all("folder" in item and "any_of" in item and "present" in item
                                for item in row["expected_deliverables"]))
            self.assertFalse(row["expected_deliverables"][1]["present"])

    def test_text_only_listing_cannot_be_marked_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            project, package, listing = make_project(Path(temp))
            (package / "cover.png").write_bytes(b"image placeholder")
            (listing / "LISTING.txt").write_text("Title: Book", encoding="utf-8")
            text_only_profile = {"Sample": {
                "folder": "Sample", "listing_folder": "Sample",
                "required_any": [["interior.pdf"], ["cover.png"]],
                "listing_any": [["*.txt"]],
            }}
            report = build_completion_report(project, profiles=text_only_profile)
            row = report["platforms"]["Sample"]
            self.assertEqual(row["status"], "NEEDS_REVIEW")
            self.assertTrue(any("No structured JSON listing metadata" in issue
                                for issue in row["review_issues"]))

    def test_non_object_listing_fields_block_readiness(self):
        with tempfile.TemporaryDirectory() as temp:
            project, package, listing = make_project(Path(temp))
            (package / "cover.png").write_bytes(b"image placeholder")
            (listing / "LISTING.json").write_text(json.dumps({
                "platform": "Sample", "fields": ["Book", "J.A.C.", "Description"]
            }), encoding="utf-8")
            (listing / "LISTING.txt").write_text("Title: Book", encoding="utf-8")
            report = build_completion_report(project, profiles=PROFILE)
            row = report["platforms"]["Sample"]
            self.assertEqual(row["status"], "BLOCKED")
            self.assertTrue(any("Listing fields must be an object" in issue
                                for issue in row["validation_errors"]))

    def test_blank_required_listing_fields_remain_review_items(self):
        with tempfile.TemporaryDirectory() as temp:
            project, package, listing = make_project(Path(temp))
            (package / "cover.png").write_bytes(b"image placeholder")
            (listing / "LISTING.json").write_text(json.dumps({
                "platform": "Sample", "fields": {"title": "Book", "author": "", "description": "Desc"}
            }), encoding="utf-8")
            (listing / "LISTING.txt").write_text("Title: Book", encoding="utf-8")
            report = build_completion_report(project, profiles=PROFILE)
            row = report["platforms"]["Sample"]
            self.assertEqual(row["status"], "NEEDS_REVIEW")
            self.assertTrue(any("author" in issue for issue in row["review_issues"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
