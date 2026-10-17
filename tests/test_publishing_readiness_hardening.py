"""Regression tests for hardened publishing metadata and deliverable diagnostics."""
import json
import tempfile
import unittest
from pathlib import Path

from publishing_completion import DEFAULT_PLATFORMS, build_completion_report, validate_pdf


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
    def test_large_pdf_page_markers_are_counted_across_chunk_boundaries(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "large-interior.pdf"
            chunk_size = 1024 * 1024
            header = b"%PDF-1.4\n"
            marker = b"/Type /Page /Parent 1 0 R >> endobj\n"
            # Place the marker across the scanner's first 1 MiB chunk boundary.
            filler_length = chunk_size - len(header) - 5
            path.write_bytes(header + (b"x" * filler_length) + marker + (b"x" * 1_100_000) + b"\n%%EOF\n")
            result = validate_pdf(path)
            self.assertEqual(result["page_marker_count"], 1)
            self.assertEqual(result["status"], "BASIC_CHECK_PASS")
            self.assertFalse(result["warnings"])
            self.assertFalse(result["errors"])

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
            (package / "cover.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
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
            (package / "cover.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
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
            (package / "cover.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
            (listing / "LISTING.json").write_text(json.dumps({
                "platform": "Sample", "fields": {"title": "Book", "author": "", "description": "Desc"}
            }), encoding="utf-8")
            (listing / "LISTING.txt").write_text("Title: Book", encoding="utf-8")
            report = build_completion_report(project, profiles=PROFILE)
            row = report["platforms"]["Sample"]
            self.assertEqual(row["status"], "NEEDS_REVIEW")
            self.assertTrue(any("author" in issue for issue in row["review_issues"]))


    def test_cover_with_wrong_image_signature_blocks_readiness(self):
        with tempfile.TemporaryDirectory() as temp:
            project, package, listing = make_project(Path(temp))
            (package / "cover.png").write_bytes(b"not actually a PNG image")
            (listing / "LISTING.json").write_text(json.dumps({
                "platform": "Sample",
                "fields": {"title": "Book", "author": "J.A.C.", "description": "Description"},
            }), encoding="utf-8")
            report = build_completion_report(project, profiles=PROFILE)
            row = report["platforms"]["Sample"]
            self.assertEqual(row["status"], "BLOCKED")
            self.assertTrue(any("PNG filename does not contain a PNG signature" in issue
                                for issue in row["validation_errors"]))
            self.assertTrue(row["package_image_checks"])

    def test_zero_byte_extra_package_file_blocks_readiness(self):
        with tempfile.TemporaryDirectory() as temp:
            project, package, listing = make_project(Path(temp))
            (package / "cover.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
            (package / "upload-notes.txt").write_bytes(b"")
            (listing / "LISTING.json").write_text(json.dumps({
                "platform": "Sample",
                "fields": {"title": "Book", "author": "J.A.C.", "description": "Description"},
            }), encoding="utf-8")
            report = build_completion_report(project, profiles=PROFILE)
            row = report["platforms"]["Sample"]
            self.assertEqual(row["status"], "BLOCKED")
            self.assertTrue(any("Package file is empty: upload-notes.txt" in issue
                                for issue in row["validation_errors"]))


    def test_realistic_four_platform_fixture_passes_expected_preflight(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "Nightmare Test Book"
            master = project / "MASTER"
            master.mkdir(parents=True)
            make_pdf(master / "Nightmare_MASTER.pdf", pages=3)
            png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
            pdf_bytes_path = master / "Nightmare_MASTER.pdf"
            pdf_bytes = pdf_bytes_path.read_bytes()

            for platform, profile in DEFAULT_PLATFORMS.items():
                package = project / "PLATFORMS" / profile["folder"]
                listing = project / "MARKETING" / "LISTINGS" / profile["listing_folder"]
                package.mkdir(parents=True)
                listing.mkdir(parents=True)
                for group in profile["required_any"]:
                    pattern = group[0]
                    if pattern == "*.pdf":
                        filename = "digital-interior.pdf"
                    elif "*interior*.pdf" in group:
                        filename = "Nightmare-interior.pdf"
                    elif "*cover*.pdf" in group:
                        filename = "Nightmare-cover.pdf"
                    elif any("cover" in item or "thumbnail" in item for item in group):
                        filename = "Nightmare-cover.png"
                    elif any("description" in item or "metadata" in item for item in group):
                        filename = "description.txt"
                    else:
                        self.fail(f"Test fixture does not understand requirement: {group}")
                    target = package / filename
                    if target.suffix.casefold() == ".pdf":
                        target.write_bytes(pdf_bytes)
                    elif target.suffix.casefold() == ".png":
                        target.write_bytes(png)
                    else:
                        target.write_text("Product description for test fixture.", encoding="utf-8")
                # Publishing readiness now verifies the package manifest against the
                # exact recursive inventory and the current MASTER PDF.
                import hashlib
                package_files = sorted(p for p in package.rglob("*") if p.is_file())
                (package / "PACKAGE_MANIFEST.json").write_text(json.dumps({
                    "schema_version": 1,
                    "status": "READY",
                    "files": [p.relative_to(package).as_posix() for p in package_files]
                             + ["PACKAGE_MANIFEST.json"],
                    "file_hashes": {
                        p.relative_to(package).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in package_files
                    },
                    "master_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                }), encoding="utf-8")
                (listing / "LISTING.json").write_text(json.dumps({
                    "platform": platform,
                    "fields": {"title": "Nightmare Test Book", "author": "J.A.C.",
                               "description": "A test listing description."},
                }), encoding="utf-8")
                # The readiness gate also requires a human-readable listing draft.
                (listing / "listing-draft.txt").write_text(
                    "Title: Nightmare Test Book\\nAuthor: J.A.C.\\nDescription: A test listing description.\\n",
                    encoding="utf-8",
                )

            report = build_completion_report(project)
            self.assertEqual(report["overall_status"], "READY_TO_UPLOAD", json.dumps({
                "summary": report["summary"],
                "platforms": {name: {key: row[key] for key in ("status", "missing_requirements", "validation_errors", "review_issues")}
                              for name, row in report["platforms"].items()},
            }, indent=2))
            self.assertEqual(report["summary"]["READY_TO_UPLOAD"], len(DEFAULT_PLATFORMS))
            for platform in DEFAULT_PLATFORMS:
                with self.subTest(platform=platform):
                    row = report["platforms"][platform]
                    self.assertEqual(row["status"], "READY_TO_UPLOAD")
                    self.assertFalse(row["missing_requirements"])
                    self.assertFalse(row["validation_errors"])

    def test_stale_package_interior_requires_review(self):
        with tempfile.TemporaryDirectory() as temp:
            project, package, listing = make_project(Path(temp))
            # Both PDFs are structurally readable, but their bytes differ from MASTER.
            make_pdf(package / "interior.pdf", pages=3)
            (package / "cover.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)
            (listing / "LISTING.json").write_text(json.dumps({
                "platform": "Sample",
                "fields": {"title": "Book", "author": "J.A.C.", "description": "Description"},
            }), encoding="utf-8")
            (listing / "LISTING.txt").write_text("Title: Book", encoding="utf-8")
            report = build_completion_report(project, profiles=PROFILE)
            row = report["platforms"]["Sample"]
            self.assertEqual(row["status"], "NEEDS_REVIEW")
            self.assertTrue(any("differs from the current MASTER" in issue for issue in row["review_issues"]))
            interior = next(item for item in row["package_pdf_checks"] if item["path"].endswith("interior.pdf"))
            self.assertFalse(interior["matches_master"])

    def test_pdf_and_image_symlinks_are_rejected_without_reading_targets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target_pdf = root / "target.pdf"
            make_pdf(target_pdf)
            target_image = root / "target.png"
            target_image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)
            pdf_link, image_link = root / "linked.pdf", root / "linked.png"
            try:
                pdf_link.symlink_to(target_pdf)
                image_link.symlink_to(target_image)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symlinks unavailable in this environment: {error}")
            pdf_result = validate_pdf(pdf_link)
            image_result = __import__("publishing_completion").validate_image(image_link)
            self.assertFalse(pdf_result["valid"])
            self.assertTrue(any("symbolic link" in issue for issue in pdf_result["errors"]))
            self.assertFalse(image_result["valid"])
            self.assertTrue(any("symbolic links" in issue for issue in image_result["errors"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
